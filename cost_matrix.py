"""
成本矩阵构建。

将百度地图返回的 distance/duration 数据，按照优化目标转换为
OR-Tools 所需的整数成本矩阵，并检测不可达点位。

节点编号约定（与 solver.py 保持一致）：
  0          → 虚拟节点（dummy depot）
  1 ~ N      → start_points（上车点）
  N+1        → end_point（企业终点）
"""

from typing import Dict, List, NamedTuple, Tuple

from baidu_map import MatrixBuildError, RouteData, fetch_route_matrix
from config import DISTANCE_WEIGHT, LARGE_COST, TIME_WEIGHT


class CostMatrixResult(NamedTuple):
    """成本矩阵构建结果。"""
    # OR-Tools 整数成本矩阵，shape = (total_nodes × total_nodes)
    # total_nodes = 1 (虚拟节点) + len(reachable_starts) + 1 (终点)
    cost_matrix: List[List[int]]

    # 可达起点的原始索引（在 start_points 中的位置）
    reachable_indices: List[int]

    # 不可达起点的原始索引
    unreachable_indices: List[int]

    # 原始路网数据矩阵（用于阶段四组装分段结果）
    # shape = [len(reachable_starts) + 1][len(reachable_starts) + 1]
    # 索引 0~N-1 对应 reachable_starts，索引 N 对应 end_point
    route_data: List[List[RouteData]]


def _compute_cost(duration: float, distance: float, optimize_type: str) -> float:
    """根据优化目标计算单段成本。"""
    if optimize_type == "time":
        return duration
    elif optimize_type == "distance":
        return distance
    else:  # "cost"
        return TIME_WEIGHT * duration + DISTANCE_WEIGHT * distance


def _to_int_cost(value: float) -> int:
    """浮点成本转整数（OR-Tools 要求整数），乘以 100 保留精度。"""
    return int(round(value * 100))


def build_cost_matrix(
    start_coords: List[Tuple[float, float]],
    end_coord: Tuple[float, float],
    ak: str,
    optimize_type: str,
) -> CostMatrixResult:
    """
    构建 OR-Tools 所需的成本矩阵。

    流程：
    1. 组合所有点位（starts + end），调用百度地图批量算路
    2. 检测不可达点位（某起点到终点不可达，则剔除）
    3. 按优化目标生成成本值
    4. 构建带虚拟节点的 OR-Tools 整数矩阵

    OR-Tools 矩阵节点编号：
      0        → 虚拟节点
      1 ~ M    → 可达起点（M = len(reachable_indices)）
      M+1      → 终点

    Args:
        start_coords: 起点坐标列表 [(lat, lng), ...]
        end_coord: 终点坐标 (lat, lng)
        ak: 百度地图 AK
        optimize_type: 优化目标，"time" / "distance" / "cost"

    Returns:
        CostMatrixResult

    Raises:
        MatrixBuildError: 矩阵构建失败
        InvalidAKError: AK 无效
    """
    n_starts = len(start_coords)

    # 所有点位合并：starts[0..N-1] + end[N]
    all_coords = list(start_coords) + [end_coord]
    n_all = len(all_coords)  # N + 1

    # 调用百度地图，获取完整 (N+1) × (N+1) 路网矩阵
    raw_matrix = fetch_route_matrix(all_coords, all_coords, ak)

    # 检测不可达起点：某起点到终点（索引 N）不可达，则剔除
    end_idx = n_starts  # 在 all_coords 中终点的索引
    reachable_indices: List[int] = []
    unreachable_indices: List[int] = []

    for i in range(n_starts):
        if raw_matrix[i][end_idx].reachable:
            reachable_indices.append(i)
        else:
            unreachable_indices.append(i)

    # 如果所有起点都不可达，直接失败
    if not reachable_indices:
        raise MatrixBuildError("所有起点均不可达终点，无法构建成本矩阵")

    # 提取可达起点子矩阵 + 终点行列
    # 节点顺序：reachable_starts... + end
    sub_indices = reachable_indices + [end_idx]  # 在 all_coords 中的索引
    M = len(reachable_indices)  # 可达起点数量
    sub_size = M + 1            # 可达起点 + 终点

    # 构建子路网矩阵（用于阶段四查询原始 distance/duration）
    route_data: List[List[RouteData]] = [
        [raw_matrix[sub_indices[i]][sub_indices[j]] for j in range(sub_size)]
        for i in range(sub_size)
    ]

    # 构建 OR-Tools 成本矩阵，总节点数 = 1 (虚拟) + M (可达起点) + 1 (终点)
    total_nodes = 1 + M + 1  # 虚拟节点=0，起点=1~M，终点=M+1
    cost_matrix: List[List[int]] = [
        [0] * total_nodes for _ in range(total_nodes)
    ]

    # 填充真实节点间的成本（OR-Tools 节点 1~M+1 对应 sub_indices 0~M）
    for i in range(sub_size):
        for j in range(sub_size):
            rd = route_data[i][j]
            if i == j:
                cost = 0
            elif not rd.reachable:
                cost = LARGE_COST
            else:
                cost = _to_int_cost(_compute_cost(rd.duration, rd.distance, optimize_type))
            # OR-Tools 节点偏移 +1（节点 0 是虚拟节点）
            cost_matrix[i + 1][j + 1] = cost

    # 虚拟节点（0）的成本设置：
    #   虚拟节点 → 任意可达起点（1~M）：0（允许从任意起点出发）
    #   虚拟节点 → 终点（M+1）：LARGE_COST（禁止直接去终点跳过所有起点）
    #   终点（M+1）→ 虚拟节点（0）：0（闭环）
    #   任意起点 → 虚拟节点（0）：LARGE_COST（禁止中途回到虚拟节点）
    for i in range(1, M + 1):
        cost_matrix[0][i] = 0              # 虚拟节点 → 起点：免费
        cost_matrix[i][0] = LARGE_COST    # 起点 → 虚拟节点：禁止

    cost_matrix[0][M + 1] = LARGE_COST    # 虚拟节点 → 终点：禁止
    cost_matrix[M + 1][0] = 0             # 终点 → 虚拟节点：闭环

    return CostMatrixResult(
        cost_matrix=cost_matrix,
        reachable_indices=reachable_indices,
        unreachable_indices=unreachable_indices,
        route_data=route_data,
    )
