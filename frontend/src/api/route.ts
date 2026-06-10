/**
 * 路径规划接口封装。
 */
import apiClient from './client'
import type { RouteRequest, RouteResponse } from '@/types/route'

/**
 * 调用后端路径规划接口。
 *
 * 对应后端 POST /api/v1/route/plan。
 */
export async function planRoute(req: RouteRequest): Promise<RouteResponse> {
  const { data } = await apiClient.post<RouteResponse>('/v1/route/plan', req)
  return data
}
