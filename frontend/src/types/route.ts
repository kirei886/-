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
  /** 乘车人数，缺省按 1 人计入容量需求 */
  passenger_count?: number
}

/** 企业终点 */
export interface EndPoint {
  id: string
  name: string
  address?: string
  lat: number
  lng: number
  /** 最晚到达时刻 HH:MM（24 小时制）；给定则启用时间窗约束 */
  latest_arrival_time?: string
}

/** 车型（车型池，阶段三自动选型） */
export interface VehicleType {
  /** 该车型座位数，≥1 */
  seats: number
  /** 该车型可用台数，≥1 */
  count: number
  /** 单辆启用成本，单位与优化目标一致（time=秒/distance=米/cost=加权值），默认 0 */
  fixed_cost?: number
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
  /** 车队车辆数，[1, 50]；为空时由 vehicle_capacities 长度或服务端默认值决定 */
  num_vehicles?: number
  /** 各车座位数数组（混合车型，每元素 ≥1）；为空时取服务端默认值 */
  vehicle_capacities?: number[]
  /** 车型池（阶段三）：求解器据座位数/台数/启用成本自动选型；与 vehicle_capacities 互斥 */
  vehicle_types?: VehicleType[]
  /** 每个上车点固定停靠时间（秒，全局统一，阶段四时间窗）；缺省取服务端默认 */
  service_time?: number
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
  /** 到达 to_id 的预计时刻（当日秒数，前端转 HH:MM，阶段四时间窗）；未启用时间窗时为 null */
  arrival_time?: number | null
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
  /** 该车承载总人数（各经停站点乘车人数之和） */
  load: number
  /** 该车座位数（阶段三体现自动选中的车型容量） */
  capacity: number
  /** 该车启用成本，单位与优化目标一致；阶段二回退路径为 0 */
  fixed_cost: number
  /** 该车发车时刻（当日秒数，前端转 HH:MM，阶段四时间窗）；未启用时间窗时为 null */
  departure_time?: number | null
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
