/**
 * 路径规划接口类型定义。
 *
 * 严格对齐后端 models.py 的 Pydantic 模型。
 * 注意：RouteRequest 不含 baidu_map_ak —— AK 已与后端解耦，由后端从环境变量读取。
 */

/** 优化目标 */
export type OptimizeType = 'time' | 'distance' | 'cost'

/** 上车点 */
export interface StartPoint {
  id: string
  name: string
  address?: string
  /** 纬度，[-90, 90] */
  lat: number
  /** 经度，[-180, 180] */
  lng: number
  /** 预计乘车人数，当前版本仅透传 */
  passenger_count?: number
}

/** 企业终点 */
export interface EndPoint {
  id: string
  name: string
  address?: string
  lat: number
  lng: number
}

/** 规划请求体 */
export interface RouteRequest {
  /** 起点列表，至少 1 个 */
  start_points: StartPoint[]
  end_point: EndPoint
  /** 优化目标，默认 time */
  optimize_type?: OptimizeType
  /** OR-Tools 最大求解时间（秒），[1, 300]，默认 30 */
  max_solve_time?: number
  /** 车队车辆数，[1, 50]；为空时取服务端默认值 */
  num_vehicles?: number
  /** 单车容量（阶段一语义为单车最多经停站点数）；为空时取服务端默认值 */
  vehicle_capacity?: number
}

/** 单段路径 */
export interface Segment {
  from_id: string
  to_id: string
  /** 分段距离（米） */
  distance: number
  /** 分段耗时（秒） */
  duration: number
  /**
   * 百度地图返回的路径轨迹点。
   * 每个元素为 "lng,lat;lng,lat;..." 格式的字符串（bd09ll 坐标系）。
   */
  path: string[]
}

/** 单辆车的子路线 */
export interface VehicleRoute {
  /** 车辆序号，从 0 开始 */
  vehicle_index: number
  /** 该车经停站点 ID 顺序，末位为企业终点 */
  route_order: string[]
  /** 该车总距离（米） */
  total_distance: number
  /** 该车总耗时（秒） */
  total_duration: number
  segments: Segment[]
  /** 该车承载量（阶段一为经停站点数） */
  load: number
}

/** 规划响应体 */
export interface RouteResponse {
  status: 'success' | 'no_solution' | 'error'
  message: string
  /** 各车辆子路线 */
  routes: VehicleRoute[]
  /** 车队总距离（米），各路线之和 */
  total_distance: number
  /** 车队总耗时（秒），各路线之和 */
  total_duration: number
  /** 不可达点位 ID 列表 */
  unreachable_points: string[]
}
