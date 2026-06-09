# 成本权重（固定，不对外暴露）
TIME_WEIGHT: float = 1.0
DISTANCE_WEIGHT: float = 0.001  # 统一量纲，距离单位为米

# OR-Tools 默认最大求解时间（秒）
DEFAULT_MAX_SOLVE_TIME: int = 30

# 百度地图 API
BAIDU_MAP_ROUTE_MATRIX_URL = "https://api.map.baidu.com/routematrix/v2/driving"
BAIDU_MAP_DIRECTION_URL = "https://api.map.baidu.com/direction/v2/driving"

# 矩阵构建分批大小（origins 和 destinations 各不超过该值）
MATRIX_BATCH_SIZE: int = 7

# 百度地图请求重试配置
MAX_RETRIES: int = 3
RETRY_BASE_DELAY: float = 0.5   # 初始等待秒数，指数退避
BATCH_SLEEP_INTERVAL: float = 0.2  # 批次间隔秒数

# OR-Tools 虚拟节点成本（极大值，用于禁止某些路径）
LARGE_COST: int = 10_000_000
