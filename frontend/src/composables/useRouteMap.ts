/**
 * 路线结果地图绘制器。
 *
 * 复用 useBaiduMap().load() 加载 BMapGL，封装地图实例化与路线绘制：
 * 画分段 polyline、按经停顺序打点标号、自动调整视野。
 *
 * 坐标系说明：后端响应的 segment.path 元素为 "lng,lat;lng,lat;..." 字符串
 * （BD09LL），与百度地图 JS API 一致，可直接拆分构造 Point，无需转换。
 */
import { ref, shallowRef } from 'vue'
import { useBaiduMap } from './useBaiduMap'
import type { RouteResponse } from '@/types/route'

/** 地图打点用的点位（坐标 + 名称），由调用方根据输入构造 */
export interface MapPoint {
  id: string
  name: string
  lat: number
  lng: number
}

// 多车配色板：每辆车取一种颜色循环使用
export const ROUTE_PALETTE = ['#e1372e', '#1f6fe5', '#15a06a', '#e6a700', '#8c52ff']
const ROUTE_STROKE_WEIGHT = 6
const ROUTE_STROKE_OPACITY = 0.85

// 默认中心（成都），仅在无点位时用于初始化展示
const DEFAULT_CENTER = { lng: 104.0668, lat: 30.5728 }
const DEFAULT_ZOOM = 12

export function useRouteMap() {
  const { load, loading: scriptLoading, error: scriptError } = useBaiduMap()

  // 地图实例与覆盖物用 shallowRef，避免 Vue 深度代理 BMapGL 对象
  const map = shallowRef<any>(null)
  const ready = ref(false)

  /**
   * 初始化地图实例。需在容器 DOM 挂载后调用。
   */
  async function initMap(container: HTMLElement): Promise<void> {
    await load()
    const BMapGL = (window as any).BMapGL
    const instance = new BMapGL.Map(container)
    instance.centerAndZoom(
      new BMapGL.Point(DEFAULT_CENTER.lng, DEFAULT_CENTER.lat),
      DEFAULT_ZOOM,
    )
    instance.enableScrollWheelZoom(true)
    instance.addControl(new BMapGL.NavigationControl())
    instance.addControl(new BMapGL.ScaleControl())
    map.value = instance
    ready.value = true
  }

  /** 清空所有覆盖物（路线、标记） */
  function clear(): void {
    if (map.value) {
      map.value.clearOverlays()
    }
  }

  /**
   * 把 "lng,lat;lng,lat;..." 字符串解析为 BMapGL.Point 数组。
   */
  function parsePath(pathStr: string): any[] {
    const BMapGL = (window as any).BMapGL
    const points: any[] = []
    for (const pair of pathStr.split(';')) {
      const [lngStr, latStr] = pair.split(',')
      const lng = Number(lngStr)
      const lat = Number(latStr)
      if (Number.isFinite(lng) && Number.isFinite(lat)) {
        points.push(new BMapGL.Point(lng, lat))
      }
    }
    return points
  }

  /**
   * 绘制多车路线规划结果。
   *
   * 每辆车一种配色：画该车分段 polyline、按车内经停顺序打点标号；
   * 企业终点所有车共用，只画一次。
   *
   * @param response 后端规划响应（提供 routes 数组）
   * @param points   当前输入的所有点位（起点 + 终点），用于打点定位
   */
  function drawRoute(response: RouteResponse, points: MapPoint[]): void {
    if (!map.value) return
    const BMapGL = (window as any).BMapGL
    clear()

    const pointMap = new Map(points.map((p) => [p.id, p]))
    const viewportPoints: any[] = []
    // 终点 ID（各车 route_order 末位一致），统一最后画一次
    let endId: string | null = null

    response.routes.forEach((route, vIdx) => {
      const color = ROUTE_PALETTE[vIdx % ROUTE_PALETTE.length]

      // 1. 画该车分段 polyline。path 为空时退化为 from→to 直线，避免断线。
      for (const seg of route.segments) {
        let linePoints: any[] = []
        for (const pathStr of seg.path) {
          linePoints = linePoints.concat(parsePath(pathStr))
        }
        if (linePoints.length === 0) {
          const from = pointMap.get(seg.from_id)
          const to = pointMap.get(seg.to_id)
          if (from && to) {
            linePoints = [
              new BMapGL.Point(from.lng, from.lat),
              new BMapGL.Point(to.lng, to.lat),
            ]
          }
        }
        if (linePoints.length >= 2) {
          const polyline = new BMapGL.Polyline(linePoints, {
            strokeColor: color,
            strokeWeight: ROUTE_STROKE_WEIGHT,
            strokeOpacity: ROUTE_STROKE_OPACITY,
          })
          map.value.addOverlay(polyline)
          viewportPoints.push(...linePoints)
        }
      }

      // 2. 按车内经停顺序打点 + 标号。route_order 末位为终点（共用，跳过）。
      const lastIndex = route.route_order.length - 1
      route.route_order.forEach((id, index) => {
        if (index === lastIndex) {
          endId = id
          return
        }
        const p = pointMap.get(id)
        if (!p) return
        const pt = new BMapGL.Point(p.lng, p.lat)
        const marker = new BMapGL.Marker(pt)
        map.value.addOverlay(marker)

        const label = new BMapGL.Label(`车${vIdx + 1}-${index + 1}. ${p.name}`, {
          position: pt,
          offset: new BMapGL.Size(12, -6),
        })
        label.setStyle({
          color: '#fff',
          backgroundColor: color,
          border: 'none',
          borderRadius: '4px',
          padding: '2px 6px',
          fontSize: '12px',
          whiteSpace: 'nowrap',
        })
        map.value.addOverlay(label)
        viewportPoints.push(pt)
      })
    })

    // 3. 企业终点：所有车共用，只画一次（灰黑标）。
    if (endId) {
      const p = pointMap.get(endId)
      if (p) {
        const pt = new BMapGL.Point(p.lng, p.lat)
        map.value.addOverlay(new BMapGL.Marker(pt))
        const label = new BMapGL.Label(`终. ${p.name}`, {
          position: pt,
          offset: new BMapGL.Size(12, -6),
        })
        label.setStyle({
          color: '#fff',
          backgroundColor: '#1f2329',
          border: 'none',
          borderRadius: '4px',
          padding: '2px 6px',
          fontSize: '12px',
          whiteSpace: 'nowrap',
        })
        map.value.addOverlay(label)
        viewportPoints.push(pt)
      }
    }

    // 4. 不可达起点用灰色标记区分。
    for (const id of response.unreachable_points) {
      const p = pointMap.get(id)
      if (!p) continue
      const pt = new BMapGL.Point(p.lng, p.lat)
      const label = new BMapGL.Label(`✕ ${p.name}（不可达）`, {
        position: pt,
        offset: new BMapGL.Size(12, -6),
      })
      label.setStyle({
        color: '#fff',
        backgroundColor: '#8a8f99',
        border: 'none',
        borderRadius: '4px',
        padding: '2px 6px',
        fontSize: '12px',
        whiteSpace: 'nowrap',
      })
      map.value.addOverlay(label)
      viewportPoints.push(pt)
    }

    // 5. 自动缩放到合适视野。
    if (viewportPoints.length > 0) {
      map.value.setViewport(viewportPoints)
    }
  }

  return {
    map,
    ready,
    scriptLoading,
    scriptError,
    initMap,
    drawRoute,
    clear,
  }
}
