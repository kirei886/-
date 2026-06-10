/**
 * axios 实例。
 *
 * baseURL 优先取 VITE_API_BASE_URL；未配置时走 '/api'，由 Vite 开发代理转发到后端。
 */
import axios from 'axios'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 60_000, // 路径规划含百度地图调用 + OR-Tools 求解，耗时较长
  headers: {
    'Content-Type': 'application/json',
  },
})

export default apiClient
