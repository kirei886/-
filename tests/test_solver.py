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
