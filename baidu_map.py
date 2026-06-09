"""
百度地图 API 封装。

提供两个核心能力：
1. fetch_route_matrix() — 批量获取所有点位间的 distance/duration，用于构建成本矩阵
2. fetch_segment_detail() — 获取单段路径的 polyline、精确 distance/duration
"""

import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import httpx

from config import (
    BAIDU_MAP_DIRECTION_URL,
    BAIDU_MAP_ROUTE_MATRIX_URL,
    BATCH_SLEEP_INTERVAL,
    MATRIX_BATCH_SIZE,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)


class RouteData(NamedTuple):
    """单段路径的距离和耗时。"""
    duration: float   # 秒
    distance: float   # 米
    reachable: bool


class MatrixBuildError(Exception):
    """成本矩阵构建失败时抛出。"""


class InvalidAKError(Exception):
    """百度地图 AK 无效或无权限时抛出。"""


# 百度地图 AK 相关错误码
_AK_ERROR_CODES = {3, 5, 100}
# 流量限制错误码（可重试）
_RATE_LIMIT_CODES = {102, 103, 104}


def _coords_to_str(points: List[Tuple[float, float]]) -> str:
    """将 (lat, lng) 列表转换为百度地图 origins/destinations 字符串格式。"""
    return "|".join(f"{lat},{lng}" for lat, lng in points)


def _request_with_retry(
    url: str,
    params: Dict[str, Any],
    context: str = "",
) -> Dict[str, Any]:
    """
    带指数退避重试的 HTTP GET 请求。

    Args:
        url: 请求地址
        params: 查询参数
        context: 用于错误信息的上下文描述

    Returns:
        解析后的 JSON 响应体

    Raises:
        InvalidAKError: AK 无效或无权限
        MatrixBuildError: 重试耗尽或其他不可恢复错误
    """
    last_error: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = httpx.get(url, params=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            last_error = e
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            time.sleep(delay)
            continue

        status_code = data.get("status", -1)

        if status_code == 0:
            return data

        if status_code in _AK_ERROR_CODES:
            raise InvalidAKError(
                f"百度地图 AK 无效或无权限（status={status_code}，message={data.get('message')}）"
            )

        if status_code in _RATE_LIMIT_CODES:
            # 流量限制，退避后重试
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            last_error = MatrixBuildError(
                f"{context} 流量超限（status={status_code}），等待 {delay:.1f}s 后重试"
            )
            time.sleep(delay)
            continue

        # 其他错误（非法参数、服务不可用等），直接失败
        raise MatrixBuildError(
            f"{context} 百度地图接口错误（status={status_code}，message={data.get('message')}）"
        )

    raise MatrixBuildError(
        f"{context} 重试 {MAX_RETRIES} 次后仍失败：{last_error}"
    )


def fetch_route_matrix(
    origins: List[Tuple[float, float]],
    destinations: List[Tuple[float, float]],
    ak: str,
) -> List[List[RouteData]]:
    """
    批量获取多起点到多终点的路径数据，返回二维矩阵。

    矩阵索引：result[i][j] 表示 origins[i] → destinations[j]

    分批策略：将 origins 和 destinations 各自按 MATRIX_BATCH_SIZE 分批，
    依次请求并拼装完整矩阵。批次间 sleep BATCH_SLEEP_INTERVAL 避免限流。

    Args:
        origins: 起点列表，每个元素为 (lat, lng)
        destinations: 终点列表，每个元素为 (lat, lng)
        ak: 百度地图 AK

    Returns:
        二维 RouteData 矩阵，shape = [len(origins)][len(destinations)]

    Raises:
        InvalidAKError: AK 无效
        MatrixBuildError: 构建失败
    """
    n_orig = len(origins)
    n_dest = len(destinations)

    # 初始化结果矩阵，默认不可达
    matrix: List[List[RouteData]] = [
        [RouteData(duration=0.0, distance=0.0, reachable=False)] * n_dest
        for _ in range(n_orig)
    ]

    # 分批遍历 origins
    for orig_start in range(0, n_orig, MATRIX_BATCH_SIZE):
        orig_batch = origins[orig_start: orig_start + MATRIX_BATCH_SIZE]

        # 分批遍历 destinations
        for dest_start in range(0, n_dest, MATRIX_BATCH_SIZE):
            dest_batch = destinations[dest_start: dest_start + MATRIX_BATCH_SIZE]

            context = (
                f"origins[{orig_start}:{orig_start+len(orig_batch)}] × "
                f"destinations[{dest_start}:{dest_start+len(dest_batch)}]"
            )

            params = {
                "origins": _coords_to_str(orig_batch),
                "destinations": _coords_to_str(dest_batch),
                "ak": ak,
                "coord_type": "bd09ll",
                "output": "json",
            }

            data = _request_with_retry(BAIDU_MAP_ROUTE_MATRIX_URL, params, context)
            results = data.get("result", [])

            # 填充矩阵：result 顺序为 orig[0]→所有dest, orig[1]→所有dest, ...
            for i, orig_idx in enumerate(range(orig_start, orig_start + len(orig_batch))):
                for j, dest_idx in enumerate(range(dest_start, dest_start + len(dest_batch))):
                    flat_idx = i * len(dest_batch) + j
                    if flat_idx >= len(results):
                        continue
                    item = results[flat_idx]
                    duration = float(item.get("duration", {}).get("value", 0))
                    distance = float(item.get("distance", {}).get("value", 0))
                    # 百度地图对同一点 origin==destination 返回 duration=0, distance=0
                    # 对不可达路径也返回 duration=0, distance=0，通过 orig_idx != dest_idx 区分
                    reachable = (duration > 0 and distance > 0) or (orig_idx == dest_idx)
                    matrix[orig_idx][dest_idx] = RouteData(
                        duration=duration,
                        distance=distance,
                        reachable=reachable,
                    )

            # 批次间隔，避免触发 QPS 限制
            if not (
                orig_start + MATRIX_BATCH_SIZE >= n_orig
                and dest_start + MATRIX_BATCH_SIZE >= n_dest
            ):
                time.sleep(BATCH_SLEEP_INTERVAL)

    return matrix


def fetch_segment_detail(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    ak: str,
) -> Dict[str, Any]:
    """
    获取单段路径的详细信息，包含 polyline、精确 distance/duration。

    Args:
        origin: 起点 (lat, lng)
        destination: 终点 (lat, lng)
        ak: 百度地图 AK

    Returns:
        包含以下字段的字典：
            - duration: float，耗时（秒）
            - distance: float，距离（米）
            - path: list，路径轨迹点（来自百度地图 steps 中的 path 字段）
            - success: bool，是否成功获取
            - message: str，失败时的说明

    Notes:
        此函数捕获所有异常，失败时返回 success=False 而不抛出，
        避免 polyline 获取失败影响整体结果返回。
    """
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "ak": ak,
        "coord_type": "bd09ll",
        "ret_coordtype": "bd09ll",
        "output": "json",
    }

    try:
        data = _request_with_retry(BAIDU_MAP_DIRECTION_URL, params, "单段路径详情")
    except InvalidAKError:
        raise
    except Exception as e:
        return {
            "duration": 0.0,
            "distance": 0.0,
            "path": [],
            "success": False,
            "message": str(e),
        }

    # 解析驾车规划结果
    try:
        route = data["result"]["routes"][0]
        duration = float(route.get("duration", 0))
        distance = float(route.get("distance", 0))

        # 从各 step 中提取路径轨迹点
        path: List[Any] = []
        for step in route.get("steps", []):
            step_path = step.get("path", "")
            if step_path:
                # 百度地图 path 字段为 "lng,lat;lng,lat;..." 格式的字符串
                path.append(step_path)

        return {
            "duration": duration,
            "distance": distance,
            "path": path,
            "success": True,
            "message": "",
        }
    except (KeyError, IndexError, TypeError) as e:
        return {
            "duration": 0.0,
            "distance": 0.0,
            "path": [],
            "success": False,
            "message": f"解析路径详情失败：{e}",
        }
