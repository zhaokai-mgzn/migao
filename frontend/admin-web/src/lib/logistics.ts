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
 * - 承运商**带物流类型归属**（issue #8079）：候选按用户选的类型收敛，否则真机上能填出
 *   「物流类型 = 快递 + 物流公司 = 德邦快递」这种自相矛盾的组合（用户 2026-10-29：「全链路都要区分」）。
 *
 * ⚠️ 词表只做**候选**：两处下拉一律允许自定义填写（POC 客户可能有其他承运商），
 * 因此不得把它当成白名单校验（后端列是自由文本 VARCHAR，无 DB CHECK）。
 */

/** 物流类型：express 快递 / logistics 物流专线（与 V47 迁移的列注释同口径） */
export const LOGISTICS_TYPES = [
  { value: 'express', label: '快递' },
  { value: 'logistics', label: '物流/专线' },
] as const

/** 物流类型枚举值（单据列是自由文本，前端只在**候选面**收敛，见文件头 ⚠️） */
export type LogisticsType = (typeof LOGISTICS_TYPES)[number]['value']

/** 后端列默认值（V47 `logistics_type DEFAULT 'express'`）：订单没记类型时表单取它（唯一真值） */
export const DEFAULT_LOGISTICS_TYPE: LogisticsType = 'express'

/** 承运商候选 = 名称 + **物流类型归属**（issue #8079；原先是纯 `string[]`，与类型词表互不相关） */
export interface LogisticsCompany {
  name: string
  type: LogisticsType
}

/**
 * 常用承运商候选（发货页原有 6 家 + 域文档点名的物流专线承运商）。
 *
 * 🔴 顺序即优先级：每种类型的**第一位 = 该类型的默认承运商**
 * （`express` ⇒ 德邦快递，`logistics` ⇒ 四季安物流）；E2E 依赖「德邦快递」是快递默认值。
 */
export const LOGISTICS_COMPANIES: readonly LogisticsCompany[] = [
  { name: '德邦快递', type: 'express' },
  { name: '顺丰速运', type: 'express' },
  { name: '中通快递', type: 'express' },
  { name: '圆通速递', type: 'express' },
  { name: '韵达快递', type: 'express' },
  { name: '申通快递', type: 'express' },
  { name: '四季安物流', type: 'logistics' },
]

/** 是否为**登记过**的物流类型（其余一律按「未知」处理，不参与收敛） */
export function isLogisticsType(value?: string | null): value is LogisticsType {
  return LOGISTICS_TYPES.some((t) => t.value === value)
}

/**
 * 某物流类型下的承运商候选（顺序 = {@link LOGISTICS_COMPANIES}，**第一家即该类型默认承运商**）。
 *
 * 未知 / 空类型 ⇒ **全量**：档案面「常用物流方式」未指定、建单页「未指定」时不能凭空缩小候选。
 */
export function logisticsCompaniesFor(type?: string | null): string[] {
  const source = isLogisticsType(type)
    ? LOGISTICS_COMPANIES.filter((c) => c.type === type)
    : LOGISTICS_COMPANIES
  return source.map((c) => c.name)
}

/** 切换物流类型的结果：校正后的承运商 + 一次**可见提示**（`notice = null` ⇒ 没改动，不该提示） */
export interface CarrierSwitch {
  company: string
  notice: string | null
}

/**
 * 切换「物流类型」时校正已选承运商（issue #8079）—— 调用方负责渲染 `notice`（**不静默改**）。
 *
 * 口径：
 * - 当前承运商属于**另一种**类型 ⇒ 落到新类型第一家 + 提示（例：「快递-顺丰速运」切到「物流/专线」
 *   ⇒ 四季安物流，不残留顺丰）；
 * - 当前已在新类型里 ⇒ 不动、不提示（商家自己的选择不被覆盖）；
 * - 当前是**词表之外的自定义承运商** ⇒ 不动：词表只是候选、不是白名单，自定义值的归属无从判断，
 *   改写它等于替商家丢数据。
 */
export function switchCarrier(current: string, nextType: LogisticsType): CarrierSwitch {
  const entry = LOGISTICS_COMPANIES.find((c) => c.name === current)
  if (!entry || entry.type === nextType) return { company: current, notice: null }
  const [first] = logisticsCompaniesFor(nextType)
  if (!first) return { company: current, notice: null }
  return {
    company: first,
    notice: `已将物流公司改为「${first}」（${logisticsTypeLabel(nextType)}）`,
  }
}

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

/**
 * **纸面口径**的物流方式：登记枚举 → 中文；**未登记/非枚举 ⇒ 原样回显**。
 *
 * 🔴 与 {@link logisticsTypeLabel} 的**有意差异**（issue #6869）：那个是**表单**口径，
 * 未知值回落「快递」（= 与后端列默认值一致，表单需要一个可选中的值）；
 * 而纸面（报价单 / 加工单）是**给客户的凭证** —— 把未知值或客户自录的值印成「快递」就是**编值**。
 * 故这里回显原值，缺值 ⇒ `null`（该栏不印）。
 *
 * 实证（用户 2026-10-14 逐字）：「货运 express · 顺丰速运，**不要用英文**，人家看不懂」——
 * 病根是纸面直接拼了后端枚举 `express`，没走任何词表。
 */
export function logisticsTypeText(type?: string | null): string | null {
  const value = (type || '').trim()
  if (value === '') return null
  return LOGISTICS_TYPES.find((t) => t.value === value)?.label ?? value
}

/**
 * 纸面「货运」栏文案：`快递 · 顺丰速运`（枚举转中文 + 承运商）。
 *
 * 两者都缺 ⇒ 空串（调用方据此决定该栏印不印）。**唯一实现点** —— 报价单与加工单共用，
 * 不各写一份会漂的拼接。
 */
export function freightText(type?: string | null, company?: string | null): string {
  return [logisticsTypeText(type), (company || '').trim()].filter(Boolean).join(' · ')
}
