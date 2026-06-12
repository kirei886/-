/**
 * 起点 CSV 批量导入解析（纯函数，无第三方依赖）。
 *
 * 上车点逐行手填几十上百个不现实，这里把一段 CSV 文本解析成多条起点行，
 * 供 RoutePlanView 追加到起点列表。格式受控（四列简单结构），手写解析即可，
 * 不给精简的依赖树（axios/vue/vue-router）增负担。
 *
 * CSV 约定：每行 `名称, 经度(lng), 纬度(lat), 人数`。
 * - 表头自适应：首行含 名称/经度/纬度/lng/lat/人数 等关键词时按表头名映射列
 *   （允许乱序、人数列可缺）；否则按固定列序 名称,经度,纬度,人数 解析（无表头）。
 * - 人数列可选：缺列或留空 → passengers 省略，后端按 1 人计。
 * - 容忍 UTF-8 BOM、每格首尾空白、空行。
 * - 逐行校验，非法行不静默丢弃：收集「第 N 行:原因」到 errors，合法行进 rows。
 *
 * 校验范围与 models.py 对齐（lat ∈ [-90,90]、lng ∈ [-180,180]、人数非负整数），
 * 保证前端放行的值后端不会再拒。
 */

/** 解析出的单条起点行（坐标已转 number，人数可选） */
export interface ParsedRow {
  name: string
  lng: number
  lat: number
  passengers?: number
}

/** 解析结果：合法行 + 人类可读的逐行错误 */
export interface ParseResult {
  rows: ParsedRow[]
  errors: string[]
}

/** 列索引映射；passengers 为 -1 表示无人数列 */
interface ColumnMap {
  name: number
  lng: number
  lat: number
  passengers: number
}

/** 固定列序（无表头时）：名称,经度,纬度,人数 */
const FIXED_COLUMNS: ColumnMap = { name: 0, lng: 1, lat: 2, passengers: 3 }

/** 表头关键词 → 标准列名（小写匹配） */
const HEADER_ALIASES: Record<string, keyof ColumnMap> = {
  名称: 'name',
  站名: 'name',
  站点: 'name',
  name: 'name',
  经度: 'lng',
  lng: 'lng',
  longitude: 'lng',
  纬度: 'lat',
  lat: 'lat',
  latitude: 'lat',
  人数: 'passengers',
  乘车人数: 'passengers',
  passengers: 'passengers',
  count: 'passengers',
}

/** 拆一行 CSV 为各格（仅英文逗号分隔），去首尾空白 */
function splitCells(line: string): string[] {
  return line.split(',').map((c) => c.trim())
}

/** 判断首行是否表头：任一格命中表头关键词即认定为表头 */
function detectHeader(cells: string[]): ColumnMap | null {
  const map: ColumnMap = { name: -1, lng: -1, lat: -1, passengers: -1 }
  let matched = false
  cells.forEach((cell, idx) => {
    const key = HEADER_ALIASES[cell.toLowerCase()]
    if (key && map[key] === -1) {
      map[key] = idx
      matched = true
    }
  })
  // 至少命中关键词、且名称/经度/纬度三列齐全才算有效表头
  if (matched && map.name !== -1 && map.lng !== -1 && map.lat !== -1) {
    return map
  }
  return null
}

/**
 * 解析起点 CSV 文本。
 * @param text 整段 CSV 内容
 * @returns 合法行与逐行错误（行号按原文 1 基计，含被跳过的空行/表头）
 */
export function parseStartPointCsv(text: string): ParseResult {
  const rows: ParsedRow[] = []
  const errors: string[] = []

  // 去 UTF-8 BOM，按 \r\n / \n 切行
  const clean = text.replace(/^﻿/, '')
  const lines = clean.split(/\r?\n/)

  // 找首个非空行判断表头
  let headerRowIdx = -1
  let columns: ColumnMap = FIXED_COLUMNS
  for (let i = 0; i < lines.length; i += 1) {
    if (lines[i].trim() !== '') {
      const detected = detectHeader(splitCells(lines[i]))
      if (detected) {
        columns = detected
        headerRowIdx = i
      }
      break
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    if (i === headerRowIdx) continue // 跳过表头行
    const raw = lines[i]
    if (raw.trim() === '') continue // 跳过空行
    const lineNo = i + 1 // 原文 1 基行号，便于用户对照
    const cells = splitCells(raw)

    const name = (cells[columns.name] ?? '').trim()
    const lngRaw = (cells[columns.lng] ?? '').trim()
    const latRaw = (cells[columns.lat] ?? '').trim()

    if (!name) {
      errors.push(`第 ${lineNo} 行:名称为空`)
      continue
    }
    const lng = Number(lngRaw)
    const lat = Number(latRaw)
    if (!lngRaw || !Number.isFinite(lng) || lng < -180 || lng > 180) {
      errors.push(`第 ${lineNo} 行:经度无效（需 -180~180）`)
      continue
    }
    if (!latRaw || !Number.isFinite(lat) || lat < -90 || lat > 90) {
      errors.push(`第 ${lineNo} 行:纬度无效（需 -90~90）`)
      continue
    }

    const row: ParsedRow = { name, lng, lat }

    // 人数列可选：有列且非空才校验，否则省略（后端按 1 人计）
    if (columns.passengers !== -1) {
      const pRaw = (cells[columns.passengers] ?? '').trim()
      if (pRaw !== '') {
        const p = Number(pRaw)
        if (!Number.isInteger(p) || p < 0) {
          errors.push(`第 ${lineNo} 行:人数需为非负整数`)
          continue
        }
        row.passengers = p
      }
    }

    rows.push(row)
  }

  return { rows, errors }
}
