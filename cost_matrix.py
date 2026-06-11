"""
成本矩阵构建。

将百度地图返回的 distance/duration 数据，按照优化目标转换为
OR-Tools 所需的整数成本矩阵，并检测不可达点位。

节点编号约定（与 solver.py 保持一致）：
  0          → 企业终点（depot，车队起点兼终点）
  1 ~ M      → 可达上车点
"""

from typing import List, NamedTuple, Tuple

from baidu_map import MatrixBuildError, RouteData, fetch_route_matrix
from config import DISTANCE_WEIGHT, LARGE_COST, TIME_WEIGHT


class CostMatrixResult(NamedTuple):
    """成本矩阵构建结果。"""
    # OR-Tools 整数成本矩阵，shape = (total_nodes × total_nodes)
    # total_nodes = 1 (depot=终点) + len(reachable_starts)
    cost_matrix: List[List[int]]

    # 可达起点的原始索引（在 start_points 中的位置）
    reachable_indices: List[int]

    # 不可达起点的原始索引
    unreachable_indices: List[int]

    # 原始路网数据矩阵（用于组装分段结果）
    # shape = [1 + len(reachable_starts)][1 + len(reachable_starts)]
    # 索引 0 对应 end_point（depot），索引 1~M 对应 reachable_starts
    route_data: List[List[RouteData]]

    # 行驶时间矩阵（秒，整数），与 cost_matrix 同结构/同索引（阶段四：时间窗）。
    # 复用 route_data 的 duration，无需额外请求百度。语义与成本矩阵一致：
    #   depot → 任意上车点 = 0（首段不计时，等价「从任意起点出发」）
    #   上车点 → 终点 / 上车点间 = 真实行驶秒数
    #   不可达腿 = LARGE_COST
    time_matrix: List[List[int]]


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
    4. 构建以企业终点为 depot 的 OR-Tools 整数矩阵

    OR-Tools 矩阵节点编号：
      0        → 企业终点（depot，车队起点兼终点）
      1 ~ M    → 可达起点（M = len(reachable_indices)）

    弧成本语义（保留「首段免费、起点任意」，且对每辆车独立成立）：
      depot → 任意上车点 = 0（空驶免费，等价「从任意起点出发」）
      上车点 → 终点 / 上车点间 = 真实成本
      不可达腿 = LARGE_COST

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

    # 节点顺序：depot(终点) + 可达上车点
    # sub_indices[0] = 终点，sub_indices[1..M] = 可达起点
    sub_indices = [end_idx] + reachable_indices  # 在 all_coords 中的索引
    M = len(reachable_indices)   # 可达起点数量
    total_nodes = 1 + M          # depot + 可达起点

    # 构建子路网矩阵（用于查询原始 distance/duration）
    # route_data[i][j] = 节点 i → 节点 j 的真实路网数据
    route_data: List[List[RouteData]] = [
        [raw_matrix[sub_indices[i]][sub_indices[j]] for j in range(total_nodes)]
        for i in range(total_nodes)
    ]

    # 构建 OR-Tools 成本矩阵
    cost_matrix: List[List[int]] = [
        [0] * total_nodes for _ in range(total_nodes)
    ]
    # 行驶时间矩阵（秒，整数），与成本矩阵同结构/同索引（阶段四：时间窗）。
    # 复用 route_data 的 duration，语义对齐成本：depot 出弧=0、不可达=LARGE_COST。
    time_matrix: List[List[int]] = [
        [0] * total_nodes for _ in range(total_nodes)
    ]

    for i in range(total_nodes):
        for j in range(total_nodes):
            if i == j:
                cost_matrix[i][j] = 0
                time_matrix[i][j] = 0
            elif i == 0:
                # depot → 任意上车点：免费（空驶，等价「从任意起点出发」）；
                # 时间同理为 0（首段不计时），约束的是首个上车点→…→公司的总时长。
                cost_matrix[i][j] = 0
                time_matrix[i][j] = 0
            else:
                rd = route_data[i][j]
                if not rd.reachable:
                    cost_matrix[i][j] = LARGE_COST
                    time_matrix[i][j] = LARGE_COST
                else:
                    cost_matrix[i][j] = _to_int_cost(
                        _compute_cost(rd.duration, rd.distance, optimize_type)
                    )
                    time_matrix[i][j] = int(round(rd.duration))

    return CostMatrixResult(
        cost_matrix=cost_matrix,
        reachable_indices=reachable_indices,
        unreachable_indices=unreachable_indices,
        route_data=route_data,
        time_matrix=time_matrix,
    )
