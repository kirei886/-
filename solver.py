"""
OR-Tools 多车路径求解器（CVRP）。

以企业终点为车队 depot，实现「N 辆车从公司出发 → 各自经过若干上车点 →
返回公司」的带容量约束最优分配与经停顺序求解。

节点编号约定（与 cost_matrix.py 保持一致）：
  0        → 企业终点（depot，每辆车的起点兼终点）
  1 ~ M    → 可达上车点（M = len(reachable_starts)）

弧成本中 depot→上车点为 0（空驶免费，保留「起点任意、首段免费」语义），
上车点→公司、上车点间为真实成本。
"""

from typing import List, NamedTuple

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

# OR-Tools 求解状态码
_STATUS_SUCCESS = 1    # ROUTING_SUCCESS
_STATUS_OPTIMAL = 7    # ROUTING_OPTIMAL
_STATUS_PARTIAL = 2    # ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED


class SolveResult(NamedTuple):
    """求解结果。"""
    # 求解是否找到可行解
    success: bool
    # 各车辆的经停序列。外层每个元素对应一辆车，
    # 内层列表为该车按访问序经停的可达起点下标（0~M-1，不含 depot）。
    # 空车（未分配任何站点）不输出。仅在 success=True 时有效。
    routes: List[List[int]]
    # OR-Tools 原始状态码
    raw_status: int
    # 状态说明
    message: str


def solve(
    cost_matrix: List[List[int]],
    num_starts: int,
    num_vehicles: int,
    demands: List[int],
    vehicle_capacities: List[int],
    max_solve_time: int,
) -> SolveResult:
    """
    使用 OR-Tools 求解多车带容量约束的路径规划。

    Args:
        cost_matrix: 整数成本矩阵，shape=(1+num_starts, 1+num_starts)
                     节点 0=企业终点(depot)，1~num_starts=可达上车点
        num_starts:  可达起点数量（M）
        num_vehicles: 车队车辆数
        demands:     各节点需求，长度 = 1+num_starts，demands[0]（depot）应为 0，
                     阶段一每个上车点需求为 1
        vehicle_capacities: 各车辆容量，长度 = num_vehicles
        max_solve_time: 最大求解时间（秒）

    Returns:
        SolveResult，routes 为各车经停的可达起点下标（0~M-1）列表

    Notes:
        - 上车点为强制访问（不加 Disjunction），容量可行时默认必访；
          被迫走 LARGE_COST 死路的情况由调用方做相邻连通性二次校验拦截。
        - depot（节点 0）对每辆车都是起点兼终点，不受「只访问一次」约束，
          因此可承载多辆车收尾。
    """
    total_nodes = 1 + num_starts  # depot + 可达起点

    # --- 建模 ---
    manager = pywrapcp.RoutingIndexManager(total_nodes, num_vehicles, 0)
    model = pywrapcp.RoutingModel(manager)

    # 注册弧成本回调
    def transit_callback(from_routing_idx: int, to_routing_idx: int) -> int:
        i = manager.IndexToNode(from_routing_idx)
        j = manager.IndexToNode(to_routing_idx)
        return cost_matrix[i][j]

    transit_idx = model.RegisterTransitCallback(transit_callback)
    model.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # 注册需求回调 + 容量维度（强制拆车的关键）
    def demand_callback(from_routing_idx: int) -> int:
        node = manager.IndexToNode(from_routing_idx)
        return demands[node]

    demand_idx = model.RegisterUnaryTransitCallback(demand_callback)
    model.AddDimensionWithVehicleCapacity(
        demand_idx,
        0,                    # 无中途装载松弛
        vehicle_capacities,   # 每辆车容量
        True,                 # 容量从 0 起算
        "Capacity",
    )

    # --- 求解参数 ---
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.seconds = max_solve_time

    # --- 求解 ---
    solution = model.SolveWithParameters(params)
    raw_status = model.status()

    if solution is None or raw_status not in (_STATUS_SUCCESS, _STATUS_OPTIMAL, _STATUS_PARTIAL):
        status_names = {
            0: "ROUTING_NOT_SOLVED",
            1: "ROUTING_SUCCESS",
            2: "ROUTING_PARTIAL_SUCCESS",
            3: "ROUTING_FAIL",
            4: "ROUTING_FAIL_TIMEOUT",
            5: "ROUTING_INVALID",
            6: "ROUTING_INFEASIBLE",
            7: "ROUTING_OPTIMAL",
        }
        status_name = status_names.get(raw_status, f"UNKNOWN({raw_status})")
        return SolveResult(
            success=False,
            routes=[],
            raw_status=raw_status,
            message=f"OR-Tools 求解失败，状态：{status_name}",
        )

    # --- 解析各车辆路径 ---
    # 每辆车：遍历 Start(v)..IsEnd，收集途经的非 depot 节点。
    # OR-Tools 节点 k（1~M）对应可达起点下标 k-1。空车跳过不输出。
    routes: List[List[int]] = []
    for v in range(num_vehicles):
        pickups: List[int] = []
        routing_idx = model.Start(v)
        while not model.IsEnd(routing_idx):
            node = manager.IndexToNode(routing_idx)
            if node != 0:  # 跳过 depot
                pickups.append(node - 1)
            routing_idx = solution.Value(model.NextVar(routing_idx))
        if pickups:
            routes.append(pickups)

    quality = "最优解" if raw_status == _STATUS_OPTIMAL else "可行解"
    return SolveResult(
        success=True,
        routes=routes,
        raw_status=raw_status,
        message=f"求解成功（{quality}），共 {len(routes)} 条线路",
    )
