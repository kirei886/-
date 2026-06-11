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
import { useVehiclePresets } from '@/composables/useVehiclePresets'
import type {
  OptimizeType,
  RouteRequest,
  RouteResponse,
  StartPoint,
  VehicleType,
} from '@/types/route'

// 左栏表单行：坐标用字符串便于输入，提交时转 number
interface PointForm {
  id: string
  name: string
  lng: string
  lat: string
  passengers: string
}

let seq = 0
function nextId(prefix: string): string {
  seq += 1
  return `${prefix}-${seq}`
}

// 示例默认值（成都），方便演示直接出图
const startPoints = ref<PointForm[]>([
  { id: nextId('s'), name: '天府软件园', lng: '104.0668', lat: '30.5470', passengers: '12' },
  { id: nextId('s'), name: '武侯祠', lng: '104.0489', lat: '30.6463', passengers: '8' },
  { id: nextId('s'), name: '春熙路', lng: '104.0817', lat: '30.6571', passengers: '15' },
])
const endPoint = ref<PointForm>({
  id: nextId('e'),
  name: '公司总部',
  lng: '104.0667',
  lat: '30.5728',
  passengers: '',
})
const optimizeType = ref<OptimizeType>('time')
// 车队（阶段三：车型池，座位数 / 台数 / 启用成本；求解器据此自动选型）
// 中间态用字符串便于输入，提交时转 number
interface VehicleTypeForm {
  id: string
  seats: string
  count: string
  fixedCost: string
}
const vehicleTypes = ref<VehicleTypeForm[]>([
  { id: nextId('v'), seats: '40', count: '1', fixedCost: '0' },
  { id: nextId('v'), seats: '11', count: '3', fixedCost: '500' },
])

// 车型池预设（localStorage 持久化）
const { presets, save: savePreset, remove: removePreset, get: getPreset } = useVehiclePresets()
const selectedPreset = ref<string>('')
const presetNameInput = ref<string>('')

const mapEl = ref<HTMLElement | null>(null)
const { initMap, drawRoute, clear: clearMap, scriptError } = useRouteMap()

/** 线路序（routes 数组位置）对应的配色，与地图画线一致 */
function vehicleColor(routeIdx: number): string {
  return ROUTE_PALETTE[routeIdx % ROUTE_PALETTE.length]
}

const submitting = ref(false)
const errorMsg = ref<string | null>(null)
const result = ref<RouteResponse | null>(null)
// 本次结果对应的点位 id→站名映射（提交时快照，使摘要显示站名而非内部 ID）。
const pointNames = ref<Map<string, string>>(new Map())

/** 把一条线路的 route_order（站点 ID 序列）渲染为站名序列；查不到名字时回退显示 ID。 */
function routeOrderNames(order: string[]): string {
  return order.map((id) => pointNames.value.get(id) ?? id).join(' → ')
}

function addStart(): void {
  startPoints.value.push({ id: nextId('s'), name: '', lng: '', lat: '', passengers: '' })
}
function removeStart(index: number): void {
  startPoints.value.splice(index, 1)
}

function addVehicleType(): void {
  vehicleTypes.value.push({ id: nextId('v'), seats: '20', count: '1', fixedCost: '0' })
}
function removeVehicleType(index: number): void {
  vehicleTypes.value.splice(index, 1)
}

/**
 * 校验并解析车型池为请求所需的 VehicleType[]；非法时设 errorMsg 并返回 null。
 * 供 buildRequest 与 saveCurrentPreset 共用。
 */
function parseVehicleTypes(): VehicleType[] | null {
  if (vehicleTypes.value.length === 0) {
    errorMsg.value = '至少需要 1 种车型'
    return null
  }
  const parsed: VehicleType[] = []
  for (const vt of vehicleTypes.value) {
    const seats = Number(vt.seats)
    const count = Number(vt.count)
    if (!Number.isInteger(seats) || seats < 1) {
      errorMsg.value = '车型座位数需为不小于 1 的整数'
      return null
    }
    if (!Number.isInteger(count) || count < 1) {
      errorMsg.value = '车型台数需为不小于 1 的整数'
      return null
    }
    // 启用成本留空 → 0；填了须为非负整数。
    // 注意：<input type="number"> + v-model 在部分输入序列下会把绑定值强制转成
    // number 类型（而非 string），直接 .trim() 会抛 TypeError 中断提交（按钮卡死、
    // 请求发不出）。故用 String() 包一层兜底，兼容 string / number 两种运行时类型。
    let fixedCost = 0
    const raw = String(vt.fixedCost ?? '').trim()
    if (raw !== '') {
      const c = Number(raw)
      if (!Number.isInteger(c) || c < 0) {
        errorMsg.value = '车型启用成本需为非负整数'
        return null
      }
      fixedCost = c
    }
    parsed.push({ seats, count, fixed_cost: fixedCost })
  }
  return parsed
}

/** 载入选中的预设到车型池表单 */
function loadPreset(name: string): void {
  if (!name) return
  const preset = getPreset(name)
  if (!preset) return
  vehicleTypes.value = preset.types.map((t) => ({
    id: nextId('v'),
    seats: String(t.seats),
    count: String(t.count),
    fixedCost: String(t.fixed_cost ?? 0),
  }))
}

/** 把当前车型池另存为具名预设（先校验，通过才存） */
function saveCurrentPreset(): void {
  errorMsg.value = null
  const name = presetNameInput.value.trim()
  if (!name) {
    errorMsg.value = '请输入预设名称'
    return
  }
  const parsed = parseVehicleTypes()
  if (!parsed) return
  savePreset(name, parsed)
  selectedPreset.value = name
  presetNameInput.value = ''
}

/** 删除当前选中的预设 */
function removeSelectedPreset(): void {
  if (!selectedPreset.value) return
  removePreset(selectedPreset.value)
  selectedPreset.value = ''
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
    const point: StartPoint = { id: s.id, name: s.name.trim(), lat, lng }
    // 人数留空 → 省略字段，后端按 1 人计；填了则必须是非负整数。
    // 同 fixedCost：<input type="number"> 可能把绑定值变成 number，String() 兜底防 .trim() 抛错。
    const raw = String(s.passengers ?? '').trim()
    if (raw !== '') {
      const n = Number(raw)
      if (!Number.isInteger(n) || n < 0) {
        errorMsg.value = `起点「${s.name.trim()}」人数需为非负整数`
        return null
      }
      point.passenger_count = n
    }
    parsed.push(point)
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
  const vehicle_types = parseVehicleTypes()
  if (!vehicle_types) {
    return null
  }
  return {
    start_points: parsed,
    end_point: { id: endPoint.value.id, name: endPoint.value.name.trim(), lat: eLat, lng: eLng },
    optimize_type: optimizeType.value,
    vehicle_types,
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
  // 先清空上一次的结果与地图：无论本次校验是否通过，旧结果都不应残留，
  // 否则校验失败时屏幕仍显示上一次的方案，易被误认为「无反馈」或「输入未生效」。
  errorMsg.value = null
  result.value = null
  clearMap()
  const req = buildRequest()
  if (!req) return

  submitting.value = true
  try {
    const res = await planRoute(req)
    result.value = res
    if (res.status === 'success') {
      const pts = collectPoints(req)
      // 快照 id→站名，供摘要把 route_order 渲染成站名。
      pointNames.value = new Map(pts.map((p) => [p.id, p.name]))
      drawRoute(res, pts)
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
          <input
            v-model="s.passengers"
            class="input input--num"
            type="number"
            min="0"
            placeholder="人数"
            title="乘车人数，留空按 1 人计"
          />
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
        <div class="field-group__head">
          <span>车队（车型池）</span>
          <button class="btn-text" type="button" @click="addVehicleType">+ 添加</button>
        </div>
        <div v-for="(vt, i) in vehicleTypes" :key="vt.id" class="point-row">
          <span class="vehicle-row__label">车型 {{ i + 1 }}</span>
          <input
            v-model="vt.seats"
            class="input input--num"
            type="number"
            min="1"
            placeholder="座位数"
            title="该车型座位数"
          />
          <input
            v-model="vt.count"
            class="input input--num"
            type="number"
            min="1"
            placeholder="台数"
            title="该车型可用台数"
          />
          <input
            v-model="vt.fixedCost"
            class="input input--num"
            type="number"
            min="0"
            placeholder="启用成本"
            title="单辆启用成本，单位随优化目标（时间=秒/距离=米/成本=加权值），留空为 0"
          />
          <button
            class="btn-remove"
            type="button"
            :disabled="vehicleTypes.length <= 1"
            title="删除"
            @click="removeVehicleType(i)"
          >
            ×
          </button>
        </div>
        <!-- 预设：车型池跨会话复用 -->
        <div class="preset-bar">
          <select
            v-model="selectedPreset"
            class="input input--preset"
            @change="loadPreset(selectedPreset)"
          >
            <option value="">选择预设…</option>
            <option v-for="p in presets" :key="p.name" :value="p.name">{{ p.name }}</option>
          </select>
          <button
            v-if="selectedPreset"
            class="btn-text"
            type="button"
            @click="removeSelectedPreset"
          >
            删除
          </button>
        </div>
        <div class="preset-bar">
          <input
            v-model="presetNameInput"
            class="input input--preset"
            placeholder="预设名称"
          />
          <button class="btn-text" type="button" @click="saveCurrentPreset">保存预设</button>
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
          v-for="(route, idx) in result.routes"
          :key="route.vehicle_index"
          class="vehicle"
        >
          <div class="vehicle__head">
            <span class="vehicle__dot" :style="{ backgroundColor: vehicleColor(idx) }"></span>
            <span class="vehicle__name">线路 {{ idx + 1 }}（{{ route.capacity }} 座）</span>
            <span class="vehicle__meta">
              {{ route.load }} 人 · {{ formatKm(route.total_distance) }} km · {{ formatMin(route.total_duration) }} min
              <template v-if="route.fixed_cost"> · 启用成本 {{ route.fixed_cost }}</template>
            </span>
          </div>
          <div class="vehicle__order">{{ routeOrderNames(route.route_order) }}</div>
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
.input--num {
  width: 64px;
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
  padding: 8px 10px;
  border: 1px solid #f5c2c0;
  border-radius: 4px;
  background: #fdecec;
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

.vehicle-row__label {
  display: flex;
  align-items: center;
  width: 40px;
  font-size: 13px;
  color: #4e5969;
}

.preset-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.input--preset {
  flex: 1;
  min-width: 0;
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
