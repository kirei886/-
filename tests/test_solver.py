"""
solver.solve 的单元测试（免网络，使用人造成本矩阵）。

节点约定：0=企业终点(depot)，1~M=可达上车点。
弧成本：depot→上车点=0（空驶免费），上车点→终点 / 上车点间=真实成本，
不可达腿=LARGE_COST。
"""

import math
import time

from config import LARGE_COST
from solver import solve


def _build_matrix(m: int, large_legs: set[tuple[int, int]] | None = None) -> list[list[int]]:
    """
    构造 (1+m)×(1+m) 成本矩阵。

    - 节点 0 = depot：depot→任意上车点 = 0
    - 上车点间 / 上车点→depot = 固定真实成本 100
    - large_legs 中的 (i, j) 腿置为 LARGE_COST（模拟不可达）
    """
    large_legs = large_legs or set()
    n = 1 + m
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 0
            elif i == 0:
                matrix[i][j] = 0          # depot → 上车点：免费
            else:
                matrix[i][j] = 100        # 上车点 → 终点 / 上车点间：真实成本
    for (i, j) in large_legs:
        matrix[i][j] = LARGE_COST
    return matrix


def _all_pickups(routes: list[list[int]]) -> list[int]:
    flat: list[int] = []
    for r in routes:
        flat.extend(r)
    return flat


def test_capacity_forces_split():
    """容量=2、5 站点、3 车 → 拆成多条非空线路，站点无重无漏。"""
    m = 5
    matrix = _build_matrix(m)
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=3,
        demands=[0] + [1] * m,
        vehicle_capacities=[2] * 3,
        max_solve_time=5,
    )

    assert result.success
    # 至少拆成 3 条（5 站点 / 单车容量 2 → 需 ≥3 辆）
    assert len(result.routes) >= 3
    # 每条线路不超过容量
    for r in result.routes:
        assert 1 <= len(r) <= 2
    # 站点无重无漏，恰好覆盖 0~m-1
    pickups = _all_pickups(result.routes)
    assert sorted(pickups) == list(range(m))


def test_single_vehicle_regression():
    """单车 + 容量足够 → 一条线路覆盖全部站点（回归原单车语义）。"""
    m = 4
    matrix = _build_matrix(m)
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=1,
        demands=[0] + [1] * m,
        vehicle_capacities=[10],
        max_solve_time=5,
    )

    assert result.success
    assert len(result.routes) == 1
    assert sorted(result.routes[0]) == list(range(m))


def test_insufficient_capacity_no_solution():
    """车队总运力 < 站点数 → 无可行解。"""
    m = 5
    matrix = _build_matrix(m)
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=2,
        demands=[0] + [1] * m,
        vehicle_capacities=[2] * 2,  # 总运力 4 < 5
        max_solve_time=5,
    )

    assert not result.success


def test_solution_covers_all_when_feasible():
    """含一条不可达腿但仍有可行排列 → 求解成功且覆盖全部站点。"""
    m = 3
    # 禁止 上车点1→上车点2（节点 1→2），求解器可绕开
    matrix = _build_matrix(m, large_legs={(1, 2)})
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=2,
        demands=[0] + [1] * m,
        vehicle_capacities=[3] * 2,
        max_solve_time=5,
    )

    assert result.success
    pickups = _all_pickups(result.routes)
    assert sorted(pickups) == list(range(m))


def test_mixed_capacity_split():
    """混合车型 [3,2]、5 站点各需求 1 → 拆分满足各车容量、站点无重无漏。"""
    m = 5
    matrix = _build_matrix(m)
    capacities = [3, 2]  # 总运力 5，恰好够 5 站
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=len(capacities),
        demands=[0] + [1] * m,
        vehicle_capacities=capacities,
        max_solve_time=5,
    )

    assert result.success
    loads = sorted((len(r) for r in result.routes), reverse=True)
    for load, cap in zip(loads, sorted(capacities, reverse=True)):
        assert load <= cap
    pickups = _all_pickups(result.routes)
    assert sorted(pickups) == list(range(m))


def test_mixed_capacity_split_feasible():
    """混合车型 [3,2]、4 站点各需求 1 → 求解成功，各车不超容量、无重无漏。"""
    m = 4
    matrix = _build_matrix(m)
    capacities = [3, 2]
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=len(capacities),
        demands=[0] + [1] * m,
        vehicle_capacities=capacities,
        max_solve_time=5,
    )

    assert result.success
    # 每条线路站点数不超过对应车容量（按降序匹配即可验证可行性边界）
    loads = sorted((len(r) for r in result.routes), reverse=True)
    cap_sorted = sorted(capacities, reverse=True)
    for load, cap in zip(loads, cap_sorted):
        assert load <= cap
    pickups = _all_pickups(result.routes)
    assert sorted(pickups) == list(range(m))


def test_multi_passenger_demand():
    """各站需求 >1（人数）：demands=[0,2,2,1]、容量 [3,2] → 成功且分配不超容量。"""
    m = 3
    matrix = _build_matrix(m)
    demands = [0, 2, 2, 1]  # 站点人数：2、2、1，总需求 5
    capacities = [3, 2]     # 总运力 5，恰好够
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=len(capacities),
        demands=demands,
        vehicle_capacities=capacities,
        max_solve_time=5,
    )

    assert result.success
    pickups = _all_pickups(result.routes)
    assert sorted(pickups) == list(range(m))
    # 每辆车承载人数不超过某辆车容量（验证多人需求真实计入容量维度）
    for r in result.routes:
        route_demand = sum(demands[s + 1] for s in r)
        assert route_demand <= max(capacities)


def test_fixed_cost_suppresses_extra_vehicles():
    """高固定启用成本 → 求解器倾向少开车：容量足够时把 3 站并到 1 辆车。

    本矩阵下弧成本与拆分方式无关（每个上车点恰好贡献一条 100 成本出弧），
    故仅固定成本影响开车数。两辆车容量各 3、固定成本高 → 用 1 辆即可覆盖 3 站。
    """
    m = 3
    matrix = _build_matrix(m)
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=2,
        demands=[0] + [1] * m,
        vehicle_capacities=[3, 3],
        max_solve_time=5,
        vehicle_fixed_costs=[5000, 5000],
    )

    assert result.success
    # 高固定成本下应只启用 1 辆车
    assert len(result.routes) == 1
    assert len(result.used_vehicle_indices) == 1
    assert sorted(_all_pickups(result.routes)) == list(range(m))


def test_vehicle_type_pool_selects_cheaper():
    """车型池选型：大车(容量 5、固定成本低) vs 两辆小车(容量 2、固定成本高)。

    3 站总需求 3，大车单辆即可承载且固定成本远低 → 求解器应只选大车(下标 0)。
    """
    m = 3
    matrix = _build_matrix(m)
    capacities = [5, 2, 2]
    fixed_costs = [100, 10000, 10000]
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=len(capacities),
        demands=[0] + [1] * m,
        vehicle_capacities=capacities,
        max_solve_time=5,
        vehicle_fixed_costs=fixed_costs,
    )

    assert result.success
    # 只启用 1 辆，且是低成本大车（下标 0、容量 5）
    assert result.used_vehicle_indices == [0]
    chosen = result.used_vehicle_indices[0]
    assert capacities[chosen] == 5
    assert sorted(_all_pickups(result.routes)) == list(range(m))


def test_fixed_costs_default_none_regression():
    """vehicle_fixed_costs 缺省（None）→ 等价阶段二行为，求解成功覆盖全部。"""
    m = 4
    matrix = _build_matrix(m)
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=2,
        demands=[0] + [1] * m,
        vehicle_capacities=[3, 3],
        max_solve_time=5,
    )

    assert result.success
    assert len(result.used_vehicle_indices) == len(result.routes)
    assert sorted(_all_pickups(result.routes)) == list(range(m))


def _build_grid_matrix(m: int) -> list[list[int]]:
    """
    构造 (1+m)×(1+m) 成本矩阵，上车点按网格散布，腿成本为真实欧氏距离。

    与 _build_matrix 的「所有真实腿都是 100」不同，这里各腿成本互不相同，
    经停顺序会显著影响总成本 —— 让 GLS 有真实的优化空间，可据此检验
    「短时限收敛解」与「跑满长时限解」是否同质。depot→上车点仍为 0（空驶免费）。
    """
    pts = [(0, 0)] + [((i % 4) * 1000, (i // 4) * 1000) for i in range(m)]

    def dist(a: int, b: int) -> int:
        return int(math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]))

    n = 1 + m
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j or i == 0:
                matrix[i][j] = 0
            else:
                matrix[i][j] = dist(i, j)
    return matrix


def test_large_problem_converges_fast():
    """大问题（12 站 6 车）应在远小于时限内返回（solution_limit 收敛，不耗满 time_limit）。

    防回归：此前 GLS 无 solution_limit 时，任何成功求解都耗满 time_limit。
    给 30 秒时限但断言墙钟 < 5 秒，证明求解器靠 solution_limit 提前收敛。
    """
    m = 12
    matrix = _build_grid_matrix(m)
    start = time.monotonic()
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=6,
        demands=[0] + [3] * m,
        vehicle_capacities=[10] * 6,
        max_solve_time=30,  # 给足时限；若耗满即回归
    )
    elapsed = time.monotonic() - start

    assert result.success
    assert sorted(_all_pickups(result.routes)) == list(range(m))
    # 收敛即停，不该接近 30 秒时限
    assert elapsed < 5, f"求解耗时 {elapsed:.2f}s，疑似未收敛而耗满时限"


def test_short_time_limit_keeps_quality():
    """短时限（5s）与长时限（30s）对同一大问题应得到同质解（solution_limit 不牺牲质量）。

    两者都在 solution_limit 内收敛，目标值（各车总腿成本之和）应一致。
    """
    m = 12
    matrix = _build_grid_matrix(m)
    demands = [0] + [3] * m
    caps = [10] * 6

    def total_cost(routes: list[list[int]]) -> int:
        """各车经停序列的真实腿成本之和（depot 出弧为 0，不计入）。"""
        cost = 0
        for r in routes:
            nodes = [0] + [s + 1 for s in r] + [0]
            for a, b in zip(nodes, nodes[1:]):
                cost += matrix[a][b]
        return cost

    short = solve(matrix, num_starts=m, num_vehicles=6, demands=demands,
                  vehicle_capacities=caps, max_solve_time=5)
    long = solve(matrix, num_starts=m, num_vehicles=6, demands=demands,
                 vehicle_capacities=caps, max_solve_time=30)

    assert short.success and long.success
    # solution_limit 在两个时限下都先触发，解质量应一致
    assert total_cost(short.routes) == total_cost(long.routes)


# --- 阶段四：时间窗约束 ---
# 复用 _build_matrix 作为时间矩阵：depot 出弧=0，上车点间/到终点=100 秒，对角=0。


def test_time_window_feasible_when_loose():
    """宽松最晚到达 → 时间窗可行，覆盖全部站点。"""
    m = 3
    matrix = _build_matrix(m)
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=2,
        demands=[0] + [1] * m,
        vehicle_capacities=[3, 3],
        max_solve_time=5,
        time_matrix=matrix,            # 时间矩阵=成本矩阵（秒）
        service_times=[0, 30, 30, 30],  # 每站停靠 30 秒
        latest_arrival=100_000,        # 极宽松
    )
    assert result.success
    pickups = _all_pickups(result.routes)
    assert sorted(pickups) == list(range(m))


def test_time_window_infeasible_when_tight():
    """最晚到达小于最快单段行驶时间 → 无可行解。"""
    m = 3
    matrix = _build_matrix(m)
    # 任一上车点→终点都要 100 秒，latest_arrival=50 必然超窗。
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=3,
        demands=[0] + [1] * m,
        vehicle_capacities=[1, 1, 1],
        max_solve_time=5,
        time_matrix=matrix,
        service_times=[0, 0, 0, 0],
        latest_arrival=50,
    )
    assert not result.success


def test_service_time_pushes_over_window():
    """同一窗口下，加大停靠时间使总时长超窗 → 由可行变无解（锁住 service_time 真进时间维）。

    单站单车：行驶 100 秒。窗口 200 秒。
    停靠 50 秒 → 100+50=150 ≤ 200 可行；停靠 150 秒 → 100+150=250 > 200 无解。
    """
    m = 1
    matrix = _build_matrix(m)
    base = dict(
        num_starts=m,
        num_vehicles=1,
        demands=[0, 1],
        vehicle_capacities=[5],
        max_solve_time=5,
        time_matrix=matrix,
        latest_arrival=200,
    )
    ok = solve(matrix, service_times=[0, 50], **base)
    bad = solve(matrix, service_times=[0, 150], **base)
    assert ok.success
    assert not bad.success


def test_time_window_default_none_regression():
    """不传时间窗参数 → 退化为纯 CVRP，求解成功覆盖全部（既有行为零改动）。"""
    m = 4
    matrix = _build_matrix(m)
    result = solve(
        matrix,
        num_starts=m,
        num_vehicles=2,
        demands=[0] + [1] * m,
        vehicle_capacities=[3, 3],
        max_solve_time=5,
    )
    assert result.success
    assert sorted(_all_pickups(result.routes)) == list(range(m))
