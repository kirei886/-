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

from typing import List, NamedTuple, Optional

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

# OR-Tools 求解状态码
_STATUS_SUCCESS = 1    # ROUTING_SUCCESS
_STATUS_OPTIMAL = 7    # ROUTING_OPTIMAL
_STATUS_PARTIAL = 2    # ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED

# GLS（GUIDED_LOCAL_SEARCH）元启发式不会自我收敛：找到解后会持续扰动找更优，
# 不加约束就一直跑到 time_limit 才返回。班车这类小规模问题几毫秒即达最优，却仍
# 耗满时限（表现为「卡住」）。solution_limit 让其找到约 N 个改进解后收敛即停；
# 实测大小规模问题都在此前收敛到与跑满长时限完全一致的最优解，time_limit 仅作兜底。
_SOLUTION_LIMIT = 100


class SolveResult(NamedTuple):
    """求解结果。"""
    # 求解是否找到可行解
    success: bool
    # 各车辆的经停序列。外层每个元素对应一辆车，
    # 内层列表为该车按访问序经停的可达起点下标（0~M-1，不含 depot）。
    # 空车（未分配任何站点）不输出。仅在 success=True 时有效。
    routes: List[List[int]]
    # 与 routes 等长，记录每条非空路线对应的 OR-Tools 车辆下标（0~num_vehicles-1），
    # 供调用方反查该车的座位数 / 固定成本（阶段三车型池选型）。
    used_vehicle_indices: List[int]
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
    vehicle_fixed_costs: Optional[List[int]] = None,
    time_matrix: Optional[List[List[int]]] = None,
    service_times: Optional[List[int]] = None,
    latest_arrival: Optional[int] = None,
) -> SolveResult:
    """
    使用 OR-Tools 求解多车带容量约束的路径规划。

    Args:
        cost_matrix: 整数成本矩阵，shape=(1+num_starts, 1+num_starts)
                     节点 0=企业终点(depot)，1~num_starts=可达上车点
        num_starts:  可达起点数量（M）
        num_vehicles: 车队车辆数
        demands:     各节点需求，长度 = 1+num_starts，demands[0]（depot）应为 0，
                     阶段二每个上车点需求为该站乘车人数
        vehicle_capacities: 各车辆容量，长度 = num_vehicles
        max_solve_time: 最大求解时间（秒）
        vehicle_fixed_costs: 各车辆固定启用成本（已与弧成本同标度的整数，长度 = num_vehicles）；
                     仅当车辆被启用（路线非空）时收取，用于阶段三车型池自动选型。
                     缺省（None）时全 0，等价阶段二行为。
        time_matrix: 行驶时间矩阵（秒，整数），与 cost_matrix 同结构/同索引（阶段四：时间窗）。
                     depot 出弧=0、不可达=LARGE_COST。
        service_times: 各节点停靠时间（秒），长度 = 1+num_starts，depot（节点 0）应为 0。
        latest_arrival: 终点最晚到达时刻（秒，从当日 0 点起算）。
                     仅当 time_matrix 与 latest_arrival 同时给定时才建时间维度并约束；
                     任一缺省即退化为纯 CVRP（等价阶段三行为，现有用例零改动）。

    Returns:
        SolveResult，routes 为各车经停的可达起点下标（0~M-1）列表，
        used_vehicle_indices 为对应车辆下标。

    Notes:
        - 上车点为强制访问（不加 Disjunction），容量可行时默认必访；
          被迫走 LARGE_COST 死路的情况由调用方做相邻连通性二次校验拦截。
        - depot（节点 0）对每辆车都是起点兼终点，不受「只访问一次」约束，
          因此可承载多辆车收尾。
        - 固定成本仅对被启用车辆计入；depot→上车点弧成本为 0，
          故空车整条路线成本为 0、不收固定成本，求解器据此自动决定启用哪些车。
        - 时间窗：到达 j 的时间累积 = 行驶 time_matrix[i][j] + 在 j 停靠 service_times[j]；
          depot 出弧时间为 0（首段不计时），约束每辆车终点累积时间 ≤ latest_arrival。
    """
    total_nodes = 1 + num_starts  # depot + 可达起点
    if vehicle_fixed_costs is None:
        vehicle_fixed_costs = [0] * num_vehicles
    # 时间窗仅在时间矩阵与最晚到达同时给定时启用。
    enable_time_window = time_matrix is not None and latest_arrival is not None
    if service_times is None:
        service_times = [0] * total_nodes

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

    # 各车固定启用成本（仅启用车辆计入）——阶段三车型池自动选型的核心。
    for v in range(num_vehicles):
        if vehicle_fixed_costs[v]:
            model.SetFixedCostOfVehicle(vehicle_fixed_costs[v], v)

    # 时间维度（阶段四：时间窗）。仅在 time_matrix 与 latest_arrival 同时给定时建立。
    if enable_time_window:
        # 到达 j 的时间累积 = 行驶 time_matrix[i][j] + 在 j 停靠 service_times[j]。
        # depot 出弧 time_matrix[0][j]=0（首段不计时），depot 自身 service=0。
        def time_callback(from_routing_idx: int, to_routing_idx: int) -> int:
            i = manager.IndexToNode(from_routing_idx)
            j = manager.IndexToNode(to_routing_idx)
            return time_matrix[i][j] + service_times[j]

        time_transit_idx = model.RegisterTransitCallback(time_callback)
        # horizon 取「最晚到达」即可作为累积上界（终点不得晚于它）。
        model.AddDimension(
            time_transit_idx,
            0,                 # slack=0：不建模在站等待（本方案假设员工已在站候车）
            latest_arrival,    # 累积时间上界 = 最晚到达秒数
            True,              # 出发累积量固定为 0（各车从 0 起计耗时）
            "Time",
        )
        time_dim = model.GetDimensionOrDie("Time")
        # 约束每辆车终点（End=depot）的累积时间 ≤ 最晚到达。
        # fix_start_cumul_to_zero=True 使出发=0，故 End 累积量即该车全程（行驶+停靠）时间。
        for v in range(num_vehicles):
            time_dim.CumulVar(model.End(v)).SetRange(0, latest_arrival)

    # --- 求解参数 ---
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    # 找到约 _SOLUTION_LIMIT 个改进解后收敛即停（GLS 否则会耗满 time_limit）；
    # time_limit 退化为兜底，仅防极端超大问题失控。
    params.solution_limit = _SOLUTION_LIMIT
    params.time_limit.seconds = max_solve_time

    # --- 求解 ---
    solution = model.SolveWithParameters(params)
    raw_status = model.status()

    if solution is None or raw_status not in (_STATUS_SUCCESS, _STATUS_OPTIMAL, _STATUS_PARTIAL):
        # 给调用方/最终用户中文解释，英文枚举名保留在括号内便于排查。
        status_explain = {
            0: "求解器未运行",
            3: (
                "未找到可行方案：可能某站乘车人数超过了能单独承载它的单辆车座位数，"
                "或车队运力不足，请增大车型座位、增加车辆或拆分人数过多的站点"
            ),
            4: "求解超时仍未找到可行方案，请适当增大求解时间或放宽车队约束",
            5: "求解模型非法，请检查请求参数",
            6: (
                "约束无法满足（无可行方案）：可能某站乘车人数超过了能单独承载它的"
                "单辆车座位数，或车队总运力不足，请调整车型座位或车辆数"
            ),
        }
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
        explain = status_explain.get(raw_status, "未找到可行方案")
        return SolveResult(
            success=False,
            routes=[],
            used_vehicle_indices=[],
            raw_status=raw_status,
            message=f"{explain}（{status_name}）",
        )

    # --- 解析各车辆路径 ---
    # 每辆车：遍历 Start(v)..IsEnd，收集途经的非 depot 节点。
    # OR-Tools 节点 k（1~M）对应可达起点下标 k-1。空车跳过不输出。
    routes: List[List[int]] = []
    used_vehicle_indices: List[int] = []
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
            used_vehicle_indices.append(v)

    quality = "最优解" if raw_status == _STATUS_OPTIMAL else "可行解"
    return SolveResult(
        success=True,
        routes=routes,
        used_vehicle_indices=used_vehicle_indices,
        raw_status=raw_status,
        message=f"求解成功（{quality}），共 {len(routes)} 条线路",
    )
