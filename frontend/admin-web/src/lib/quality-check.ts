import { chipToneClasses, type ChipTone } from '@/lib/status-chip'
import type { QualityInspectionRecord, QualityTargetState } from '@/types'

/**
 * 质检记录的**展示口径**（纯函数；issue #7140 = #5652 的商家面）。
 *
 * ## 为什么单独成模块
 *
 * 同一套标签 / 颜色 / 时刻格式要在**两个面**上用（质检记录页 + 作业单生产明细里的质检区）。
 * 各写一份 ⇒ 两处迟早给出不同的判定名（仓内已有先例：套序号/套数两份实现让同一张单的屏幕
 * 与纸面互相矛盾）。所以这里的四个函数是**唯一实现**。
 *
 * ## 口径（不得改写）
 *
 * - 判定三态的中文名 = 服务端 `QualityCheckService.label()` 的**同一组词**（合格 / 返工 / 报废）：
 *   服务端下发了 `result_label` 就逐字用它（`resultLabel()` 优先取它），本文件的表只是**缺键兜底**；
 * - `pending`（未检）**不是**判定：它是「还没有任何记录」的事实，文案不得写成「合格」；
 * - 缺值（`null` / 缺键）一律渲染 `—`，**不折成 0、不写 undefined、不编占位名**（同 `issue #5652`）。
 */

/** 待检清单的状态 → 商家面人话名。 */
export const QUALITY_STATE_LABELS: Record<QualityTargetState, string> = {
  pending: '未检',
  pass: '合格',
  rework: '返工',
  scrap: '报废',
}

/** 状态 → 语义色（沿用订单/售后 chips 的 token 体系，不新造色阶）。 */
export const QUALITY_STATE_TONES: Record<QualityTargetState, ChipTone> = {
  pending: 'neutral',
  pass: 'success',
  rework: 'warning',
  scrap: 'error',
}

/** 状态 chip 的类名（与 `StatusChip` 同一份 token 映射）。 */
export function qualityStateChipClass(state: QualityTargetState): string {
  return chipToneClasses[QUALITY_STATE_TONES[state]]
}

/** 判定中文标签：优先用服务端下发的 `result_label`（同一份词），缺键才按本地表兜底。 */
export function qualityResultLabel(
  result?: string | null,
  label?: string | null,
): string {
  if (label) return label
  if (result === 'pass' || result === 'rework' || result === 'scrap') {
    return QUALITY_STATE_LABELS[result]
  }
  return '—'
}

/** 状态的中文名（`latest == null` 就是 `pending`，两句话语义不同、不许混）。 */
export function qualityStateLabel(state: QualityTargetState): string {
  return QUALITY_STATE_LABELS[state]
}

/**
 * 按成品帘取**最新一条**记录（输入须是服务端的倒序表 —— 排序口径在服务端，
 * 与 `QualityCheckService.list()` 同一份：`inspected_at` 倒序、同刻按 `created_at` 倒序）。
 *
 * ⚠️ 前端只是**取第一条**，不重排、不比较时间（那会造出第二份排序口径）。
 */
export function latestInspectionOf(
  records: QualityInspectionRecord[] | null | undefined,
  orderItemId: string,
): QualityInspectionRecord | null {
  if (!records || !orderItemId) return null
  for (const record of records) {
    if (record.order_item_id === orderItemId) return record
  }
  return null
}

/** 记录表里「每件成品帘的最新判定」（同一份取法，不另写一份）。 */
export function latestByItem(
  records: QualityInspectionRecord[] | null | undefined,
): Map<string, QualityInspectionRecord> {
  const out = new Map<string, QualityInspectionRecord>()
  for (const record of records ?? []) {
    if (!out.has(record.order_item_id)) out.set(record.order_item_id, record)
  }
  return out
}

/**
 * 时刻展示（`YYYY-MM-DD HH:mm`）。
 *
 * 服务端给的是**带时区偏移**的 ISO 串（业务时钟 = Asia/Shanghai）⇒ 用 `Date` 解析后按**浏览器时区**
 * 展示（商家看的是自己所在时区的时刻）。解析不出来 / 缺值 ⇒ `—`（不印 `Invalid Date`）。
 */
export function formatMoment(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** 成品帘展示名：商品名（+ 色号）；两者都缺 ⇒ `—`（不编名）。 */
export function qualityItemName(productName?: string | null, colorName?: string | null): string {
  const name = (productName ?? '').trim()
  const color = (colorName ?? '').trim()
  if (name && color) return `${name}（${color}）`
  if (name) return name
  if (color) return color
  return '—'
}

/**
 * 比率展示（0~1 ⇒ 百分比，一位小数）。
 *
 * 🔴 `null` / 缺值 ⇒ `—`（**0 样本**），不是 `0%` —— 「还没有数据」与「合格率为零」
 * 是两句话（issue #7192 的口径；服务端对 0 分母也只给 `null`）。
 */
export function formatRate(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

/** 小时展示（一位小数）；缺值 ⇒ `—`（不印 `0.0 小时` 冒充「刚进来的」）。 */
export function formatHours(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(1)} 小时`
}
