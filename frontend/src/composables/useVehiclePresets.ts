/**
 * 车型池预设的本地持久化（localStorage）。
 *
 * 车型配置基本固定、每次重录繁琐，这里把「车型池」存成具名预设，
 * 跨会话保留，供 RoutePlanView 下拉载入 / 另存 / 删除。
 *
 * 预设只存车型池本身（座位数 / 台数 / 启用成本），不含起点/终点/优化目标。
 * 所有写操作做兜底：localStorage 不可用（隐私模式、配额满）时静默降级，
 * 预设是增强功能，绝不阻塞主表单提交。
 */
import { ref, type Ref } from 'vue'
import type { VehicleType } from '@/types/route'

/** 单条具名预设 */
export interface VehiclePreset {
  name: string
  types: VehicleType[]
}

const STORAGE_KEY = 'shuttle.vehicle-presets'

/** 从 localStorage 读取并解析；任何异常兜底为空数组 */
function readFromStorage(): VehiclePreset[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as VehiclePreset[]) : []
  } catch {
    return []
  }
}

/** 写回 localStorage；失败静默（不可用 / 配额满） */
function writeToStorage(presets: VehiclePreset[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(presets))
  } catch {
    // 忽略：预设不持久化也不影响主流程
  }
}

export function useVehiclePresets(): {
  presets: Ref<VehiclePreset[]>
  save: (name: string, types: VehicleType[]) => void
  remove: (name: string) => void
  get: (name: string) => VehiclePreset | undefined
} {
  const presets = ref<VehiclePreset[]>(readFromStorage())

  /** 保存预设；同名则覆盖 */
  function save(name: string, types: VehicleType[]): void {
    const trimmed = name.trim()
    if (!trimmed) return
    const next = presets.value.filter((p) => p.name !== trimmed)
    next.push({ name: trimmed, types })
    presets.value = next
    writeToStorage(next)
  }

  function remove(name: string): void {
    const next = presets.value.filter((p) => p.name !== name)
    presets.value = next
    writeToStorage(next)
  }

  function get(name: string): VehiclePreset | undefined {
    return presets.value.find((p) => p.name === name)
  }

  return { presets, save, remove, get }
}
