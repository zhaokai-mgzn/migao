/**
 * 物流口径**单一真值定义**（客户常用物流档案 + 发货页），多处渲染/提交共用。
 *
 * 用户 2026-09-19 反馈（issue #4419）：「客户管理功能缺乏对客户的……常用物流/快递方式以及
 * 常用物流/快递公司 的记录」——本文件是「常用物流方式/公司」的**唯一词表**：
 *   ① 客户管理「收货信息」卡片（读/写 customer_profiles.default_logistics_*）
 *   ② 发货页（带出客户常用值 → 写 order_logistics.logistics_company/logistics_type）
 *
 * 领域口径（docs/curtain-production-rules.md §6 物流）：
 * - `express` 快递（顺丰/中通等）/ `logistics` 物流专线（四季安等）；POC 客户更多选物流专线。
 * - 客户基本固定选同一家承运商 ⇒ 客户级档案，下单/发货自动带出、可改。
 *
 * ⚠️ 词表只做**候选**：两处下拉一律允许自定义填写（POC 客户可能有其他承运商），
 * 因此不得把它当成白名单校验（后端列是自由文本 VARCHAR，无 DB CHECK）。
 */

/** 物流类型：express 快递 / logistics 物流专线（与 V47 迁移的列注释同口径） */
export const LOGISTICS_TYPES = [
  { value: 'express', label: '快递' },
  { value: 'logistics', label: '物流/专线' },
] as const

/** 常用承运商候选（发货页原有 6 家 + 域文档点名的物流专线承运商） */
export const LOGISTICS_COMPANIES = [
  '德邦快递',
  '顺丰速运',
  '中通快递',
  '圆通速递',
  '韵达快递',
  '申通快递',
  '四季安物流',
] as const

/** 物流类型 → 中文标签；未知/空值回退到「快递」（与后端列默认值 express 一致） */
export function logisticsTypeLabel(type?: string | null): string {
  return LOGISTICS_TYPES.find((t) => t.value === type)?.label ?? '快递'
}

/**
 * 「物流/专线 · 四季安物流」这类可读描述；**两者都缺 ⇒ 空串**。
 * 缺值不得补默认值（会把「客户没录过常用物流」渲染成「快递」，看起来像已配置）。
 */
export function describeLogisticsProfile(type?: string | null, company?: string | null): string {
  const parts = [type ? logisticsTypeLabel(type) : '', (company || '').trim()].filter(Boolean)
  return parts.join(' · ')
}
