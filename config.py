import os

from dotenv import load_dotenv

# 加载项目根目录下的 .env（若存在）
load_dotenv()

# 百度地图 AK：从环境变量读取，不再由前端请求体传入
BAIDU_MAP_AK: str = os.getenv("BAIDU_MAP_AK", "")

# 成本权重（固定，不对外暴露）
TIME_WEIGHT: float = 1.0
DISTANCE_WEIGHT: float = 0.001  # 统一量纲，距离单位为米

# OR-Tools 默认最大求解时间（秒）
# 求解器加了 solution_limit 收敛即停（见 solver.py），time_limit 退化为兜底；
# 班车规模问题毫秒级收敛，5 秒足够覆盖较大问题，仅防极端规模失控。
DEFAULT_MAX_SOLVE_TIME: int = 5

# 车队默认配置(阶段二:混合车型,各车独立座位数)
# 容量语义为「座位数」,每站需求 = passenger_count(缺省 1 人)。
# 请求未传 vehicle_capacities 时,用 DEFAULT_VEHICLE_CAPACITY 填充 DEFAULT_NUM_VEHICLES 辆统一容量数组。
DEFAULT_NUM_VEHICLES: int = 3
DEFAULT_VEHICLE_CAPACITY: int = 20

# 车辆默认固定启用成本(阶段三:车型池自动选型)
# 单位与优化目标一致(time=秒/distance=米/cost=加权值)。回退路径(仅给 vehicle_capacities
# 或走默认)不收固定成本,保持阶段二行为;仅 vehicle_types 显式给定时按车型 fixed_cost 计入。
DEFAULT_VEHICLE_FIXED_COST: int = 0

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
