/**
 * 缺料风险页 `/production/material-shortage` 的**口径单点**（issue #6282，承接 #6280 的冻结契约 v1）。
 *
 * 页面只做「取值 + 拼装」：需求 / 库存 / 缺口 / 条数**一律原样渲染服务端值**
 * （`MaterialShortageService.compute` 是唯一算法），本模块没有一处四则运算，
 * 也没有一处自己的好坏判定。
 *
 * ## 三条纪律（每条都有会红的判据，见 `tests/unit/pages/material-shortage.test.tsx`）
 *
 * 1. **常驻面只列真正缺的**（§31 P1）：`gapMeters > 0` 的行才进默认列表；
 *    缺口 = 0 / 有余量 / 单位不可比**都不算缺料**（可通过「显示全部」看到 —— 负控）。
 * 2. **未知 ≠ 0**：服务端 `default-property-inclusion: non_null` ⇒ `gapMeters` /
 *    `demandQty` / `daysToDeadline` 读不出时**键缺失**。一律渲染「未知」，
 *    **不得**回落成 0（回落就是把「读不出」画成「没问题」）。
 * 3. **不摆内部标识**（§31 P3）：`productId` 只进 `href`；`fields` 的字段名与
 *    `basis` 的内部键**不上屏**（它们是给判据和 agent 看的）。
 */

import { displayEnum } from '@/lib/enum-display'
import type { MaterialShortageHistoryDepth, MaterialShortageView } from '@/types'

/** 读不出 ⇒ 事实陈述「未知」（**不是** 0，也不是「暂无数据」） */
export const UNKNOWN = '未知'

/** 空态：事实陈述「当前没有缺料」（§31 P4 —— 不是「暂无数据」） */
export const NO_SHORTAGE = '当前没有缺料'

/** 交期未知（`daysToDeadline` 缺键）—— **不得**显示成「0 天」（issue #6282 要求 5） */
export const DEADLINE_UNKNOWN = '紧迫性未知'

/** 六档分层的**商家话**标签（档名本身是服务端口径词，不上屏 —— §31 P3） */
export const BAND_LABELS: Record<string, string> = {
  blocked: '交期已过',
  critical: '交期紧张',
  soon: '交期临近',
  short: '有缺口',
  safe: '有余量',
  unknown: '单位不可比',
}

/** 档位标签：未知档位**不猜**（渲染「未知」而不是原样回显内部键） */
export function bandLabel(band: string | null | undefined): string {
  // 缺值与未知值都落到 `未知`（原语义：`if (!band) return UNKNOWN`）⇒ emptyLabel 也给 UNKNOWN
  return displayEnum(BAND_LABELS, band, UNKNOWN, UNKNOWN)
}

/** 缺口（米）：缺键 / null ⇒ `null` = **未知**（不是 0） */
export function gapMeters(row: { gapMeters?: number | null }): number | null {
  const v = row.gapMeters
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/**
 * 默认面（常驻列表）= 只留**缺口 > 0** 的行。
 *
 * 缺口 0（刚好够）/ 负（有余量）/ 未知（单位不可比）**都不进** —— 这一条同时是
 * §31 P1（别一屏几百行）与「缺料」的语义本身。
 */
export function shortageRows<T extends { gapMeters?: number | null }>(rows: readonly T[]): T[] {
  return rows.filter((r) => {
    const gap = gapMeters(r)
    return gap !== null && gap > 0
  })
}

/** 米数：缺值 ⇒ 「未知」（**不印 0**）；真 0 / 负数照实印（缺口为负 = 有余量） */
export function formatMeters(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNKNOWN
  const text = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)
  return `${text} 米`
}

/** 影响订单：服务端 `orderCount`（缺键 ⇒ 未知，不印 0） */
export function ordersText(row: { orderCount?: number | null }): string {
  const n = row.orderCount
  return typeof n === 'number' && Number.isFinite(n) ? `${n} 个订单` : UNKNOWN
}

/**
 * 最早要求到货日 + 交期未知的披露。
 *
 * 🔴 `daysToDeadline` 缺键 ⇒ **「紧迫性未知」**（issue #6282 要求 5：实测 dev 库 432 张未完成
 * 订单的交期填充率为 0 ⇒ 这一档会占满，印成「0 天」等于把「没填」说成「今天到期」）。
 */
export function deadlineText(earliest: string | null | undefined, days?: number | null): string {
  if (typeof days !== 'number' || !Number.isFinite(days)) return DEADLINE_UNKNOWN
  const relative = days < 0 ? `已过 ${-days} 天` : days === 0 ? '今天到期' : `${days} 天后`
  return earliest ? `${earliest}（${relative}）` : relative
}

/**
 * 单位不可比的披露（issue #6282 要求 3 —— **必须看得见**）。
 *
 * 这些行的需求与缺口**读不出来**（商品单位不是「米」），把它们渲染成 0 或缺省行
 * 就是把「读不出」说成「没有需求」。
 */
export function nonComparableNote(view: MaterialShortageView | null | undefined): string | null {
  if (!view) return null
  const products = view.nonComparable?.products ?? view.nonComparableProducts ?? 0
  const lines = view.nonComparable?.lines ?? view.nonComparableLines ?? 0
  if (products <= 0) return null
  return `另有 ${products} 个成品（${lines} 行订单）单位不是「米」⇒ 需求与缺口读不出，未计入上面的数字`
}

/**
 * 历史深度披露（issue #6282 要求 4；`HistoryDepth.sufficient` 是预测层的**唯一**开关）。
 *
 * `sufficient == false` ⇒ 页面必须明说「预测层未启用」并给出真实深度 vs 要求深度，
 * 让「周消耗速率 / 预计耗尽日 = 未知」有归因，而不是让人误读成 0。
 */
export function historyDepthNote(hd: MaterialShortageHistoryDepth | null | undefined): string | null {
  if (!hd || hd.sufficient) return null
  return `预测层未启用：真实历史深度 ${hd.weeks} 周 < 要求 ${hd.requiredWeeks} 周`
    + ` ⇒ 周消耗速率与预计耗尽日为${UNKNOWN}`
}

/** 截断披露（服务端 `limit` 截断只动 `rows`，聚合用全量行） */
export function truncationNote(view: MaterialShortageView | null | undefined): string | null {
  if (!view?.truncated) return null
  return `本页显示前 ${view.count} 个（共 ${view.rowsTotal} 个候选，按紧迫度排序）`
}

/**
 * 缺料条数 = 有缺口四档之和（`blocked / critical / soon / short`）。
 *
 * 用服务端 `bandCounts`（全量行算，不随 `limit` 变）而不是本页 `rows.length` ——
 * 后者在截断时会把「共 N 个缺料」说小。
 */
export function shortageCount(counts: Record<string, number> | null | undefined): number {
  if (!counts) return 0
  return ['blocked', 'critical', 'soon', 'short'].reduce((sum, band) => sum + (counts[band] ?? 0), 0)
}

/** 六档分层的**一行**披露（只列非空档 —— §31 P1：常驻面不随档数膨胀） */
export function bandCountsText(counts: Record<string, number> | null | undefined): string {
  if (!counts) return ''
  return ['blocked', 'critical', 'soon', 'short', 'safe', 'unknown']
    .filter((band) => (counts[band] ?? 0) > 0)
    .map((band) => `${bandLabel(band)} ${counts[band]}`)
    .join(' · ')
}
