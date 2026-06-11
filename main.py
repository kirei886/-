from typing import List, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from baidu_map import InvalidAKError, MatrixBuildError, fetch_segment_detail
from config import (
    BAIDU_MAP_AK,
    DEFAULT_NUM_VEHICLES,
    DEFAULT_VEHICLE_CAPACITY,
    LARGE_COST,
)
from cost_matrix import build_cost_matrix
from models import RouteRequest, RouteResponse, Segment, VehicleRoute
from solver import solve

app = FastAPI(
    title="嘟嘟巴士企业班车路径规划",
    description="多起点单一终点班车路径优化工具",
    version="1.0.0",
)


def _error_response(message: str) -> RouteResponse:
    return RouteResponse(status="error", message=message)


@app.post("/api/v1/route/plan", response_model=RouteResponse)
def plan_route(request: RouteRequest) -> RouteResponse:
    """
    企业班车路径规划接口（同步，多车 CVRP）。

    接收多个上车点和一个企业终点，按固定车辆数 + 统一容量分配多条班车线路，
    每条线路返回最优经停顺序、距离、耗时和分段路径详情。
    """
    ak = BAIDU_MAP_AK
    if not ak:
        return _error_response("服务端未配置百度地图 AK，请在 .env 中设置 BAIDU_MAP_AK")
    max_solve_time = request.max_solve_time or 30
    # 车队容量数组(混合车型)：优先用请求体数组；缺省时用统一容量填充。
    if request.vehicle_capacities:
        vehicle_capacities = list(request.vehicle_capacities)
    else:
        num_vehicles = request.num_vehicles or DEFAULT_NUM_VEHICLES
        vehicle_capacities = [DEFAULT_VEHICLE_CAPACITY] * num_vehicles
    num_vehicles = len(vehicle_capacities)

    # 起点/终点坐标列表
    start_coords: List[Tuple[float, float]] = [
        (p.lat, p.lng) for p in request.start_points
    ]
    end_coord: Tuple[float, float] = (request.end_point.lat, request.end_point.lng)

    # --- 步骤1：构建成本矩阵（含不可达检测） ---
    try:
        matrix_result = build_cost_matrix(
            start_coords, end_coord, ak, request.optimize_type
        )
    except InvalidAKError as e:
        return _error_response(f"百度地图 AK 无效：{e}")
    except MatrixBuildError as e:
        return _error_response(f"成本矩阵构建失败：{e}")

    # 收集不可达点位 ID
    unreachable_ids = [
        request.start_points[i].id for i in matrix_result.unreachable_indices
    ]

    # 可达起点列表（用于后续 ID 映射）
    reachable_starts = [
        request.start_points[i] for i in matrix_result.reachable_indices
    ]
    num_starts = len(reachable_starts)

    # --- 步骤1.5：运力预判 ---
    # 阶段二每站点需求 = passenger_count（缺省 1 人），容量语义为座位数。
    demands = [0] + [(p.passenger_count or 1) for p in reachable_starts]
    if num_starts > 0:
        max_demand = max(demands[1:])
        max_capacity = max(vehicle_capacities)
        # 单站人数超过最大车容量：无任何车可单独承载该站，必然无解。
        if max_demand > max_capacity:
            return RouteResponse(
                status="no_solution",
                message=(
                    f"运力不足：单站乘车人数 {max_demand} 超过最大车容量 {max_capacity}"
                ),
                unreachable_points=unreachable_ids,
            )
        # 总需求超过车队总运力。
        total_demand = sum(demands)
        total_capacity = sum(vehicle_capacities)
        if total_demand > total_capacity:
            return RouteResponse(
                status="no_solution",
                message=(
                    f"运力不足：总乘车人数 {total_demand} 超过车队总运力 {total_capacity}"
                    f"（{len(vehicle_capacities)} 辆车座位之和）"
                ),
                unreachable_points=unreachable_ids,
            )

    # --- 步骤2：OR-Tools 多车求解 ---
    # 节点 0 = depot（终点），1~M = 可达起点；需求 depot=0、每站点=该站乘车人数

    solve_result = solve(
        matrix_result.cost_matrix,
        num_starts=num_starts,
        num_vehicles=num_vehicles,
        demands=demands,
        vehicle_capacities=vehicle_capacities,
        max_solve_time=max_solve_time,
    )

    if not solve_result.success:
        return RouteResponse(
            status="no_solution",
            message=solve_result.message,
            unreachable_points=unreachable_ids,
        )

    # --- 节点映射工具 ---
    # OR-Tools/成本矩阵节点：0=终点(depot)，k(1~M)=可达起点 k-1
    # 求解器返回的 pickup 下标为「可达起点下标」(0~M-1)，对应节点 pickup+1
    def pickup_to_id(sub_idx: int) -> str:
        return reachable_starts[sub_idx].id

    def pickup_to_coord(sub_idx: int) -> Tuple[float, float]:
        p = reachable_starts[sub_idx]
        return (p.lat, p.lng)

    end_id = request.end_point.id
    # 成本矩阵 / route_data 中的节点下标：终点=0，可达起点 sub_idx -> sub_idx+1
    def pickup_to_node(sub_idx: int) -> int:
        return sub_idx + 1

    # --- 步骤3：逐车组装结果 ---
    vehicle_routes: List[VehicleRoute] = []
    warnings: List[str] = []
    fleet_distance = 0.0
    fleet_duration = 0.0

    for v_idx, pickups in enumerate(solve_result.routes):
        # 该车真实经停的「节点序列」：起点们 + 终点(0)
        # 相邻腿用于连通性校验与分段查询。
        leg_nodes = [pickup_to_node(s) for s in pickups] + [0]

        # 连通性二次校验：相邻真实腿成本 >= LARGE_COST 视为走死路
        for idx in range(len(leg_nodes) - 1):
            a = leg_nodes[idx]
            b = leg_nodes[idx + 1]
            if matrix_result.cost_matrix[a][b] >= LARGE_COST:
                from_id = pickup_to_id(a - 1) if a != 0 else end_id
                to_id = pickup_to_id(b - 1) if b != 0 else end_id
                return RouteResponse(
                    status="no_solution",
                    message=f"部分站点间无法连通：{from_id} → {to_id}",
                    unreachable_points=unreachable_ids,
                )

        # 分段 polyline + 精确距离/耗时
        segments: List[Segment] = []
        route_distance = 0.0
        route_duration = 0.0

        for idx in range(len(leg_nodes) - 1):
            a = leg_nodes[idx]
            b = leg_nodes[idx + 1]
            from_id = pickup_to_id(a - 1) if a != 0 else end_id
            to_id = pickup_to_id(b - 1) if b != 0 else end_id
            from_coord = pickup_to_coord(a - 1) if a != 0 else end_coord
            to_coord = pickup_to_coord(b - 1) if b != 0 else end_coord

            detail = fetch_segment_detail(from_coord, to_coord, ak)
            if detail["success"]:
                distance = detail["distance"]
                duration = detail["duration"]
                path = detail["path"]
            else:
                # polyline 获取失败：降级使用矩阵中的原始数据
                rd = matrix_result.route_data[a][b]
                distance = rd.distance
                duration = rd.duration
                path = []
                warnings.append(f"{from_id}→{to_id} 路径轨迹获取失败，已使用估算数据")

            route_distance += distance
            route_duration += duration
            segments.append(Segment(
                from_id=from_id,
                to_id=to_id,
                distance=distance,
                duration=duration,
                path=path,
            ))

        route_order = [pickup_to_id(s) for s in pickups] + [end_id]
        route_load = sum((reachable_starts[s].passenger_count or 1) for s in pickups)
        vehicle_routes.append(VehicleRoute(
            vehicle_index=v_idx,
            route_order=route_order,
            total_distance=route_distance,
            total_duration=route_duration,
            segments=segments,
            load=route_load,
        ))
        fleet_distance += route_distance
        fleet_duration += route_duration

    # --- 步骤4：组装最终响应 ---
    has_unreachable = bool(unreachable_ids)
    has_warnings = bool(warnings)

    if has_unreachable and has_warnings:
        message = (
            f"{solve_result.message}；"
            f"以下站点不可达已剔除：{', '.join(unreachable_ids)}；"
            f"{'; '.join(warnings)}"
        )
    elif has_unreachable:
        message = (
            f"{solve_result.message}；"
            f"以下站点不可达已剔除：{', '.join(unreachable_ids)}"
        )
    elif has_warnings:
        message = f"{solve_result.message}；{'; '.join(warnings)}"
    else:
        message = solve_result.message

    return RouteResponse(
        status="success",
        message=message,
        routes=vehicle_routes,
        total_distance=fleet_distance,
        total_duration=fleet_duration,
        unreachable_points=unreachable_ids,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": f"服务内部错误：{str(exc)}"},
    )
