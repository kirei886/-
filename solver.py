"""
OR-Tools 路径求解器。

使用虚拟节点建模，实现"任意起点出发 → 经过所有可达上车点 → 到达企业终点"的最优顺序求解。

节点编号约定（与 cost_matrix.py 保持一致）：
  0        → 虚拟节点（dummy depot）
  1 ~ M    → 可达起点（M = len(reachable_starts)）
  M+1      → 终点
"""

from typing import List, NamedTuple, Optional

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from config import LARGE_COST

# OR-Tools 求解状态码
_STATUS_SUCCESS = 1    # ROUTING_SUCCESS
_STATUS_OPTIMAL = 7    # ROUTING_OPTIMAL
_STATUS_PARTIAL = 2    # ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED


class SolveResult(NamedTuple):
    """求解结果。"""
    # 求解是否找到可行解
    success: bool
    # 按顺序排列的节点索引（在 cost_matrix 的 sub_indices 中）
    # 索引 0~M-1 对应可达起点，索引 M 对应终点
    # 仅在 success=True 时有效
    ordered_sub_indices: List[int]
    # OR-Tools 原始状态码
    raw_status: int
    # 状态说明
    message: str


def solve(
    cost_matrix: List[List[int]],
    num_starts: int,
    max_solve_time: int,
) -> SolveResult:
    """
    使用 OR-Tools 求解多起点→单终点的最优经过顺序。

    Args:
        cost_matrix: 整数成本矩阵，shape=(1+num_starts+1, 1+num_starts+1)
                     节点 0=虚拟，1~num_starts=可达起点，num_starts+1=终点
        num_starts:  可达起点数量
        max_solve_time: 最大求解时间（秒）

    Returns:
        SolveResult，其中 ordered_sub_indices 是去掉虚拟节点后的
        顺序列表，索引含义：0~num_starts-1 为起点，num_starts 为终点

    Notes:
        - 所有起点均加入 Disjunction（penalty=LARGE_COST），强制全部经过
        - 终点节点不加 Disjunction，由路由模型自然处理为最终目的地
    """
    total_nodes = 1 + num_starts + 1  # 虚拟 + 起点 + 终点

    # --- 建模 ---
    manager = pywrapcp.RoutingIndexManager(total_nodes, 1, 0)
    model = pywrapcp.RoutingModel(manager)

    # 注册弧成本回调
    def transit_callback(from_routing_idx: int, to_routing_idx: int) -> int:
        i = manager.IndexToNode(from_routing_idx)
        j = manager.IndexToNode(to_routing_idx)
        return cost_matrix[i][j]

    transit_idx = model.RegisterTransitCallback(transit_callback)
    model.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # 强制所有起点必须被访问（penalty 极大，等价于强制经过）
    for node in range(1, num_starts + 1):
        model.AddDisjunction([manager.NodeToIndex(node)], LARGE_COST)

    # --- 求解参数 ---
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
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
            ordered_sub_indices=[],
            raw_status=raw_status,
            message=f"OR-Tools 求解失败，状态：{status_name}",
        )

    # --- 解析路径 ---
    # 遍历车辆 0 的路径，收集途经节点（去掉首尾虚拟节点）
    ordered_nodes: List[int] = []
    routing_idx = model.Start(0)

    while not model.IsEnd(routing_idx):
        node = manager.IndexToNode(routing_idx)
        if node != 0:  # 跳过虚拟节点
            ordered_nodes.append(node)
        routing_idx = solution.Value(model.NextVar(routing_idx))

    # 最后一个节点（终点）
    end_node = manager.IndexToNode(routing_idx)
    if end_node != 0:
        ordered_nodes.append(end_node)

    # 将 OR-Tools 节点编号（1~M+1）转换为 sub_indices 中的位置（0~M）
    # OR-Tools 节点 k -> sub_index k-1
    ordered_sub_indices = [node - 1 for node in ordered_nodes]

    quality = "最优解" if raw_status == _STATUS_OPTIMAL else "可行解"
    return SolveResult(
        success=True,
        ordered_sub_indices=ordered_sub_indices,
        raw_status=raw_status,
        message=f"求解成功（{quality}）",
    )
