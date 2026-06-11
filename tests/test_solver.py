"""
solver.solve 的单元测试（免网络，使用人造成本矩阵）。

节点约定：0=企业终点(depot)，1~M=可达上车点。
弧成本：depot→上车点=0（空驶免费），上车点→终点 / 上车点间=真实成本，
不可达腿=LARGE_COST。
"""

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
