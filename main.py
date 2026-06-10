from typing import List, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from baidu_map import InvalidAKError, MatrixBuildError, fetch_segment_detail
from config import BAIDU_MAP_AK, LARGE_COST
from cost_matrix import build_cost_matrix
from models import RouteRequest, RouteResponse, Segment
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
    企业班车路径规划接口（同步）。

    接收多个上车点和一个企业终点，返回最优经过顺序、总耗时、总距离和分段路径详情。
    """
    ak = BAIDU_MAP_AK
    if not ak:
        return _error_response("服务端未配置百度地图 AK，请在 .env 中设置 BAIDU_MAP_AK")
    max_solve_time = request.max_solve_time or 30

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

    # --- 步骤2：OR-Tools 求解 ---
    solve_result = solve(
        matrix_result.cost_matrix,
        num_starts=num_starts,
        max_solve_time=max_solve_time,
    )

    if not solve_result.success:
        return RouteResponse(
            status="no_solution",
            message=solve_result.message,
            unreachable_points=unreachable_ids,
        )

    # ordered_sub_indices: 0~num_starts-1 对应可达起点，num_starts 对应终点
    ordered_sub = solve_result.ordered_sub_indices

    # --- 步骤2.5：检查相邻站点连通性 ---
    # OR-Tools 对不可达路段赋予 LARGE_COST 惩罚但不硬禁止，
    # 若被迫走了死路则成本矩阵中该段 >= LARGE_COST，需在此拦截。
    for idx in range(len(ordered_sub) - 1):
        from_sub = ordered_sub[idx]
        to_sub = ordered_sub[idx + 1]
        # cost_matrix 节点偏移 +1（节点 0 为虚拟节点）
        if matrix_result.cost_matrix[from_sub + 1][to_sub + 1] >= LARGE_COST:
            from_id = reachable_starts[from_sub].id if from_sub < num_starts else request.end_point.id
            to_id = reachable_starts[to_sub].id if to_sub < num_starts else request.end_point.id
            return RouteResponse(
                status="no_solution",
                message=f"部分站点间无法连通：{from_id} → {to_id}",
                unreachable_points=unreachable_ids,
            )

    # --- 步骤3：将 sub_indices 映射为真实站点 ID ---
    # sub_indices 中的坐标来源：reachable_starts[0..M-1] + end_point
    def sub_idx_to_id(sub_idx: int) -> str:
        if sub_idx < num_starts:
            return reachable_starts[sub_idx].id
        return request.end_point.id

    def sub_idx_to_coord(sub_idx: int) -> Tuple[float, float]:
        if sub_idx < num_starts:
            p = reachable_starts[sub_idx]
            return (p.lat, p.lng)
        return end_coord

    route_order = [sub_idx_to_id(i) for i in ordered_sub]

    # --- 步骤4：补充分段路径详情（polyline + 精确 distance/duration） ---
    segments: List[Segment] = []
    warnings: List[str] = []
    total_distance = 0.0
    total_duration = 0.0

    for idx in range(len(ordered_sub) - 1):
        from_sub = ordered_sub[idx]
        to_sub = ordered_sub[idx + 1]

        from_id = sub_idx_to_id(from_sub)
        to_id = sub_idx_to_id(to_sub)
        from_coord = sub_idx_to_coord(from_sub)
        to_coord = sub_idx_to_coord(to_sub)

        detail = fetch_segment_detail(from_coord, to_coord, ak)

        if detail["success"]:
            distance = detail["distance"]
            duration = detail["duration"]
            path = detail["path"]
        else:
            # polyline 获取失败：降级使用矩阵中的原始数据
            rd = matrix_result.route_data[from_sub][to_sub]
            distance = rd.distance
            duration = rd.duration
            path = []
            warnings.append(f"{from_id}→{to_id} 路径轨迹获取失败，已使用估算数据")

        total_distance += distance
        total_duration += duration
        segments.append(Segment(
            from_id=from_id,
            to_id=to_id,
            distance=distance,
            duration=duration,
            path=path,
        ))

    # --- 步骤5：组装最终响应 ---
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
        route_order=route_order,
        total_distance=total_distance,
        total_duration=total_duration,
        segments=segments,
        unreachable_points=unreachable_ids,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": f"服务内部错误：{str(exc)}"},
    )
