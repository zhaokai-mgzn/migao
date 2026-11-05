/**
 * 下单页的**展示 / 价格预览口径** —— issue #8725 第一档切片产物。
 *
 * 单一职责：把「数字与枚举」变成**用户可读的字**（金额格式化 / 未定价文案 / 费用来源标签 /
 * 拼接接高选项 / 加工项徽标 / 颜色表 / 计价错误话术）。**不做任何算料推导、不发请求。**
 *
 * 与 `calc.ts` 的关系是**单向**的：`calc.ts → 本文件`（取色口一处），反向不存在
 * —— 依赖成环会让「算料」与「展示」又变成同一件事（判据见
 * `tests/unit/pages/orders-new-slice-structure-guard.test.ts` 的判据 ⑤）。
 *
 * ⚠️ 行为冻结：`tests/unit/pages/orders-new-slice-characterization.test.tsx` 逐字节比对
 * 同一批输入下的渲染结果 —— 这里改一个格式化位数，那条判据立刻具名红。
 */
import { OPEN_COUNT_OPTIONS } from '@/lib/order-craft-fields'
import { type OrderProductSku } from '@/lib/order-create/types'

/** 开数 → 中文标签（复用 lib 的单一映射，不另写一份） */
/**
 * 用料方案「逐项白话」的 label → **既有 testid**（2026-09-29 第二次裁定把六个 span 收成一张列表
 * ⇒ testid 由这张表给，判据仍按 testid 定位、不按文案 —— 文案会变，判据不该跟着碎）。
 */
export const CRAFT_PLAN_ITEM_TESTIDS: Record<string, string> = {
  工艺: 'craft-plan-craft',
  门幅: 'craft-plan-door-width',
  分幅: 'craft-plan-panels',
  拼接: 'craft-plan-splice',
  接高: 'craft-plan-join-height',
  接宽: 'craft-plan-join-width',
}

/** 逐项明细里**哪一项可能被人工改过**（label → `planSources` 的键）—— 用来标「（人工）」 */
export const CRAFT_PLAN_MANUAL_SOURCE_BY_LABEL: Record<
  string,
  'cuttingMode' | 'spliceTimes' | 'joinHeightM' | 'joinWidthM'
> = {
  拼接: 'spliceTimes',
  接高: 'joinHeightM',
  接宽: 'joinWidthM',
}

export const OPEN_COUNT_LABEL: Record<number, string> = Object.fromEntries(
  OPEN_COUNT_OPTIONS.map((o) => [o.value, o.label])
)

export function formatAmount(amount: number): string {
  return `¥${(amount || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * 「加工费组合」定价面的入口（issue #4590）—— **与后端下发的域指针同源**。
 *
 * ⚠️ 口径沿革（issue #6839 = B1 包）：后端 hint 此前给的是**路径**（`ProcessingFeeCalculator.PRICING_ENTRY`），
 * 2026-10-13 起改为**页名**「企业基础设置 → 加工费组合」——URL 属内部标识、不再下发。
 * ⇒ 同源判据的**真值源**随之换成页名：本文件里链接的**可见文案**必须逐字带着后端下发的那个指针
 * （由 `tests/unit/pages/orders-new-fee-preview.test.tsx` 直接读后端源码比对，改一边必红）。
 *
 * 它落点 = 合并页 `/production/processing?tab=fees` 的**第二个 tab「加工费组合」**
 * （`production/processing-fees/page.tsx` 是这条旧路径的重定向入口，见该文件头）
 * ⇒ 就是商家真正能定价的那一屏。⚠️ 前端**不另写**第三个路径。
 *
 * 🔴 反面教材（issue #6853）：上一版注释断言「后端 `PRICING_ENTRY` 给未定价组合拼的 hint 里就是这条路径」，
 * 而 B1 已把后端那个常量删掉 ⇒ 注释断言了一个**不存在**的后端常量（陈旧跨包前提，已同批改准）。
 */
export const PRICING_ENTRY = '/production/processing-fees'

/**
 * 未定价行**没有可匹配的组合**时的展示名（issue #4590 的边界）：服务端 `composition` 为空 =
 * 本行没选配任何加工项 ⇒ **缺选配信息**，与「组合未定价」是两回事，不许混同、也不许显示空组合名。
 */
export const UNPRICED_NO_COMPOSITION = '没有可匹配的组合（缺选配信息）'

/**
 * 未定价行的**组合展示名**（issue #4590）：`items.join(' + ')` —— 与「加工费组合」页
 * **同一写法**（`production/processing/page.tsx`：`(row.items ?? []).join(' + ') || row.composition_key`），
 * 保证商家在告警里读到的名字与定价页上的组合名逐字一致（否则还是对不上号）。
 *
 * `items` 是服务端**展示用**的归一化加工项名（与 `composition` 同源，键名冻结）⇒ 不自己拆键。
 */
export function unpricedCombinationLabel(
  detail: { composition?: unknown; items?: unknown } | undefined
): string {
  const items = Array.isArray(detail?.items)
    ? detail.items.filter((v): v is string => typeof v === 'string' && v.trim() !== '')
    : []
  if (items.length > 0) return items.join(' + ')
  // `items` 缺席（旧服务端）⇒ 回落到归一化组合键（与定价页的兜底同口径），再空才算「缺选配信息」
  const composition = typeof detail?.composition === 'string' ? detail.composition.trim() : ''
  return composition !== '' ? composition : UNPRICED_NO_COMPOSITION
}

/**
 * `fee_source` 三态的可读**来源**（issue #4874「加工费组合」明细块的「来源」列）——
 * 值域与后端 `ProcessingFeeCalculator.FEE_SOURCE_*` **逐字一致**
 * （`matched` 组合价目 / `manual` 手动改价 / `unpriced` 未定价）；未知值**原样显示**（不吞、不猜）。
 */
export const FEE_SOURCE_LABELS: Record<string, string> = {
  matched: '组合价目',
  manual: '手动改价',
  unpriced: '未定价',
}

/** 加工费计价失败 → 可读提示（**不给估算值**：未确认金额前不得提交） */
export function feePreviewErrorText(error: unknown): string {
  const anyErr = error as {
    response?: { data?: { message?: string; error?: { message?: string } } }
    message?: string
  }
  const detail =
    anyErr?.response?.data?.error?.message || anyErr?.response?.data?.message || anyErr?.message
  return detail ? `加工费计价失败：${detail}` : '加工费计价失败，请稍后重试'
}

/**
 * **人工加拼次**的取值（issue #5202 · 裁定 4）：`由推导决定` + `0~3`。
 *
 * 值域 = 契约 #5200 §四 的 `splice_times`（人工覆盖 0~3）；`≥ 4` **不得发明「拼4次」**（R5），
 * 那属于「需人工处理」，不是下单页能填的一档。
 */
export const SPLICE_OVERRIDE_OPTIONS: Array<{ label: string; value: number | undefined }> = [
  { label: '由推导决定', value: undefined },
  { label: '不拼接', value: 0 },
  { label: '拼1次', value: 1 },
  { label: '拼2次', value: 2 },
  { label: '拼3次', value: 3 },
]

// ====== 工具函数 ======
export function uniqueColors(skus?: OrderProductSku[]): Array<{ id: string; name: string }> {
  const map = new Map<string, string>()
  ;(skus || []).forEach((s) => {
    if (s.colorId != null) map.set(s.colorId, s.colorName || `颜色${s.colorId}`)
  })
  return Array.from(map.entries()).map(([id, name]) => ({ id, name }))
}
