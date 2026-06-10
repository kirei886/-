<script setup lang="ts">
/**
 * 路线结果页（端到端最小闭环）。
 *
 * 左栏录入起点 / 终点 / 优化目标 → 调后端 planRoute → 右栏百度地图画线打点。
 * 范围限定为现有后端能力：多起点、单终点、单条最优经停路线。
 */
import { onMounted, ref } from 'vue'
import { planRoute } from '@/api/route'
import { useRouteMap, ROUTE_PALETTE, type MapPoint } from '@/composables/useRouteMap'
import type {
  OptimizeType,
  RouteRequest,
  RouteResponse,
  StartPoint,
} from '@/types/route'

// 左栏表单行：坐标用字符串便于输入，提交时转 number
interface PointForm {
  id: string
  name: string
  lng: string
  lat: string
}

let seq = 0
function nextId(prefix: string): string {
  seq += 1
  return `${prefix}-${seq}`
}

// 示例默认值（成都），方便演示直接出图
const startPoints = ref<PointForm[]>([
  { id: nextId('s'), name: '天府软件园', lng: '104.0668', lat: '30.5470' },
  { id: nextId('s'), name: '武侯祠', lng: '104.0489', lat: '30.6463' },
  { id: nextId('s'), name: '春熙路', lng: '104.0817', lat: '30.6571' },
])
const endPoint = ref<PointForm>({
  id: nextId('e'),
  name: '公司总部',
  lng: '104.0667',
  lat: '30.5728',
})
const optimizeType = ref<OptimizeType>('time')
// 车队参数（阶段一：固定车辆数 + 统一容量，容量语义为单车最多经停站点数）
const numVehicles = ref<string>('3')
const vehicleCapacity = ref<string>('2')

const mapEl = ref<HTMLElement | null>(null)
const { initMap, drawRoute, scriptError } = useRouteMap()

/** 第 v 辆车的配色，与地图画线一致 */
function vehicleColor(vIdx: number): string {
  return ROUTE_PALETTE[vIdx % ROUTE_PALETTE.length]
}

const submitting = ref(false)
const errorMsg = ref<string | null>(null)
const result = ref<RouteResponse | null>(null)

function addStart(): void {
  startPoints.value.push({ id: nextId('s'), name: '', lng: '', lat: '' })
}
function removeStart(index: number): void {
  startPoints.value.splice(index, 1)
}

// 米 → 公里，保留 1 位
function formatKm(meters: number): string {
  return (meters / 1000).toFixed(1)
}
// 秒 → 分钟，取整
function formatMin(seconds: number): string {
  return Math.round(seconds / 60).toString()
}

/** 校验并组装请求体；任一坐标非法返回 null */
function buildRequest(): RouteRequest | null {
  const parsed: StartPoint[] = []
  for (const s of startPoints.value) {
    const lat = Number(s.lat)
    const lng = Number(s.lng)
    if (!s.name.trim() || !Number.isFinite(lat) || !Number.isFinite(lng)) {
      errorMsg.value = `起点「${s.name || '未命名'}」名称或坐标无效`
      return null
    }
    parsed.push({ id: s.id, name: s.name.trim(), lat, lng })
  }
  if (parsed.length === 0) {
    errorMsg.value = '至少需要 1 个起点'
    return null
  }
  const eLat = Number(endPoint.value.lat)
  const eLng = Number(endPoint.value.lng)
  if (!endPoint.value.name.trim() || !Number.isFinite(eLat) || !Number.isFinite(eLng)) {
    errorMsg.value = '终点名称或坐标无效'
    return null
  }
  const nVehicles = Number(numVehicles.value)
  const capacity = Number(vehicleCapacity.value)
  if (!Number.isInteger(nVehicles) || nVehicles < 1) {
    errorMsg.value = '车辆数需为不小于 1 的整数'
    return null
  }
  if (!Number.isInteger(capacity) || capacity < 1) {
    errorMsg.value = '单车最多站点需为不小于 1 的整数'
    return null
  }
  return {
    start_points: parsed,
    end_point: { id: endPoint.value.id, name: endPoint.value.name.trim(), lat: eLat, lng: eLng },
    optimize_type: optimizeType.value,
    num_vehicles: nVehicles,
    vehicle_capacity: capacity,
  }
}

/** 当前所有点位（起点 + 终点），供地图打点定位 */
function collectPoints(req: RouteRequest): MapPoint[] {
  return [
    ...req.start_points.map((p) => ({ id: p.id, name: p.name, lat: p.lat, lng: p.lng })),
    { id: req.end_point.id, name: req.end_point.name, lat: req.end_point.lat, lng: req.end_point.lng },
  ]
}

async function onSubmit(): Promise<void> {
  errorMsg.value = null
  const req = buildRequest()
  if (!req) return

  submitting.value = true
  result.value = null
  try {
    const res = await planRoute(req)
    result.value = res
    if (res.status === 'success') {
      drawRoute(res, collectPoints(req))
    } else {
      errorMsg.value = res.message
    }
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '请求失败，请检查后端服务'
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  if (mapEl.value) {
    try {
      await initMap(mapEl.value)
    } catch {
      // 地图加载失败（多为 AK 未配置）在地图区降级展示，不阻塞表单
    }
  }
})
</script>

<template>
  <div class="route-plan">
    <!-- 左栏：录入 -->
    <aside class="panel">
      <h2 class="panel__title">班车路径规划</h2>

      <section class="field-group">
        <div class="field-group__head">
          <span>上车点</span>
          <button class="btn-text" type="button" @click="addStart">+ 添加</button>
        </div>
        <div v-for="(s, i) in startPoints" :key="s.id" class="point-row">
          <input v-model="s.name" class="input input--name" placeholder="名称" />
          <input v-model="s.lng" class="input input--coord" placeholder="经度" />
          <input v-model="s.lat" class="input input--coord" placeholder="纬度" />
          <button
            class="btn-remove"
            type="button"
            :disabled="startPoints.length <= 1"
            title="删除"
            @click="removeStart(i)"
          >
            ×
          </button>
        </div>
      </section>

      <section class="field-group">
        <div class="field-group__head"><span>终点</span></div>
        <div class="point-row">
          <input v-model="endPoint.name" class="input input--name" placeholder="名称" />
          <input v-model="endPoint.lng" class="input input--coord" placeholder="经度" />
          <input v-model="endPoint.lat" class="input input--coord" placeholder="纬度" />
        </div>
      </section>

      <section class="field-group">
        <div class="field-group__head"><span>优化目标</span></div>
        <label class="radio"><input v-model="optimizeType" type="radio" value="time" />时间</label>
        <label class="radio"><input v-model="optimizeType" type="radio" value="distance" />距离</label>
        <label class="radio"><input v-model="optimizeType" type="radio" value="cost" />成本</label>
      </section>

      <section class="field-group">
        <div class="field-group__head"><span>车队</span></div>
        <div class="point-row">
          <label class="fleet-field">
            <span class="fleet-field__label">车辆数</span>
            <input v-model="numVehicles" class="input input--coord" type="number" min="1" />
          </label>
          <label class="fleet-field">
            <span class="fleet-field__label">单车最多站点</span>
            <input v-model="vehicleCapacity" class="input input--coord" type="number" min="1" />
          </label>
        </div>
      </section>

      <button class="btn-primary" type="button" :disabled="submitting" @click="onSubmit">
        {{ submitting ? '求解中…' : '生成方案' }}
      </button>

      <p v-if="errorMsg" class="msg msg--error">{{ errorMsg }}</p>

      <!-- 成功结果摘要 -->
      <section v-if="result && result.status === 'success'" class="result">
        <div class="result__stats">
          <div class="stat">
            <span class="stat__num">{{ result.routes.length }}</span>
            <span class="stat__unit">条线路</span>
          </div>
          <div class="stat">
            <span class="stat__num">{{ formatKm(result.total_distance) }}</span>
            <span class="stat__unit">km 总里程</span>
          </div>
          <div class="stat">
            <span class="stat__num">{{ formatMin(result.total_duration) }}</span>
            <span class="stat__unit">min 总耗时</span>
          </div>
        </div>
        <div
          v-for="route in result.routes"
          :key="route.vehicle_index"
          class="vehicle"
        >
          <div class="vehicle__head">
            <span class="vehicle__dot" :style="{ backgroundColor: vehicleColor(route.vehicle_index) }"></span>
            <span class="vehicle__name">车 {{ route.vehicle_index + 1 }}</span>
            <span class="vehicle__meta">
              {{ route.load }} 站 · {{ formatKm(route.total_distance) }} km · {{ formatMin(route.total_duration) }} min
            </span>
          </div>
          <div class="vehicle__order">{{ route.route_order.join(' → ') }}</div>
        </div>
        <p v-if="result.unreachable_points.length" class="msg msg--warn">
          不可达起点已剔除：{{ result.unreachable_points.join('、') }}
        </p>
      </section>
    </aside>

    <!-- 右栏：地图 -->
    <main class="map-wrap">
      <div ref="mapEl" class="map"></div>
      <div v-if="scriptError" class="map-mask">
        <p>地图加载失败：{{ scriptError }}</p>
        <p class="map-mask__hint">请在 frontend/.env 配置 VITE_BAIDU_MAP_AK(浏览器端 AK)</p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.route-plan {
  display: flex;
  height: 100%;
}

.panel {
  width: 360px;
  flex-shrink: 0;
  padding: 20px;
  overflow-y: auto;
  border-right: 1px solid #e5e6eb;
}

.panel__title {
  margin: 0 0 16px;
  font-size: 18px;
  font-weight: 600;
}

.field-group {
  margin-bottom: 18px;
}

.field-group__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #4e5969;
}

.point-row {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}

.input {
  height: 32px;
  padding: 0 8px;
  border: 1px solid #d9dce0;
  border-radius: 4px;
  font-size: 13px;
  outline: none;
}
.input:focus {
  border-color: #e1372e;
}
.input--name {
  flex: 1;
  min-width: 0;
}
.input--coord {
  width: 72px;
}

.radio {
  margin-right: 14px;
  font-size: 13px;
  color: #1f2329;
  cursor: pointer;
}

.btn-text {
  border: none;
  background: none;
  color: #e1372e;
  font-size: 13px;
  cursor: pointer;
}

.btn-remove {
  width: 32px;
  border: 1px solid #d9dce0;
  border-radius: 4px;
  background: #fff;
  color: #8a8f99;
  cursor: pointer;
}
.btn-remove:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary {
  width: 100%;
  height: 38px;
  border: none;
  border-radius: 6px;
  background: #e1372e;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.msg {
  margin: 12px 0 0;
  font-size: 13px;
}
.msg--error {
  color: #e1372e;
}
.msg--warn {
  color: #c97a00;
}

.result {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #e5e6eb;
}
.result__stats {
  display: flex;
  gap: 24px;
  margin-bottom: 14px;
}
.stat {
  display: flex;
  flex-direction: column;
}
.stat__num {
  font-size: 24px;
  font-weight: 700;
  color: #1f2329;
}
.stat__unit {
  font-size: 12px;
  color: #8a8f99;
}
.result__order {
  font-size: 13px;
}
.result__label {
  display: block;
  margin-bottom: 4px;
  font-weight: 600;
  color: #4e5969;
}
.result__chips {
  color: #1f2329;
  word-break: break-all;
}

.fleet-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #4e5969;
}
.fleet-field__label {
  white-space: nowrap;
}

.vehicle {
  margin-top: 12px;
  font-size: 13px;
}
.vehicle__head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.vehicle__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.vehicle__name {
  font-weight: 600;
  color: #1f2329;
}
.vehicle__meta {
  color: #8a8f99;
  font-size: 12px;
}
.vehicle__order {
  color: #1f2329;
  word-break: break-all;
}

.map-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
}
.map {
  width: 100%;
  height: 100%;
}
.map-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #f5f6f7;
  color: #4e5969;
  text-align: center;
  padding: 0 24px;
}
.map-mask__hint {
  font-size: 13px;
  color: #8a8f99;
}
</style>
