import type { WaybillCapabilities, WaybillCarrier, WaybillMode } from '@/types/waybill'

/**
 * 物流取号**能力位驱动**的唯一判定处（issue #8698；口径
 * `docs/logistics-waybill-api-research.md` §3-5 / §8）。
 *
 * ## 本模块治什么
 *
 * 发货页要回答「能不能自动取号」，设置页要回答「这家店配了谁、它能做什么」。
 * 两个问题的答案**只能来自服务端注册表**（`GET /api/admin/logistics/carriers` 的
 * `carriers[].canCreate/canCancel/canTrack`）—— 前端**不复制**承运商词表、**不按承运商名
 * 写 if/else**（那正是「注册表新增一家 carrier，UI 不跟着变」的病灶）。
 *
 * ## 三条硬口径
 *
 * 1. **读不到能力面 ≠ 能取号**：能力面缺失 / 解析不出 ⇒ 返回 {@link MANUAL_CARRIER}（手填）。
 *    这不是「降级容错」，是 fail-closed —— 编一个「可以取号」出来会让商家点到一个必然报错的按钮。
 * 2. **未登记 / 未接入的承运商一律落到 manual**（服务端口径 §3-3）：注册表里没有的名字 ⇒
 *    手填，且**不产生任何外呼**（本模块是纯函数，本身也没有任何网络能力）。
 * 3. **能力位是「交集」不是「声明」**：服务端已经把「声明 ∧ 实现」算好下发；
 *    前端只读 `canCreate` 一个字段，不自己推。
 */

/** 手填兜底条目 —— 前端**唯一**的兜底形状（不编任何承运商名字）。 */
export const MANUAL_CARRIER: WaybillCarrier = {
  code: 'manual',
  displayName: '手填单号',
  logisticsType: null,
  trackQueryCode: null,
  canCreate: false,
  canCancel: false,
  canTrack: false,
  mode: 'manual',
}

/**
 * 空能力面（接口没回 / 读失败 / 还没加载完）⇒ **全 manual**。
 *
 * `effectiveCarrier` 与唯一一条 `carriers` 都是 {@link MANUAL_CARRIER} ⇒
 * 发货页的「取号」按钮必然禁用、说明文案走手填分支（不按端、不按名字硬编码）。
 */
export function emptyCapabilities(): WaybillCapabilities {
  return {
    carriers: [MANUAL_CARRIER],
    configuredCarrier: null,
    effectiveCarrier: MANUAL_CARRIER,
    manualFallback: true,
  }
}

/** 按 code 找承运商（找不到 ⇒ `undefined`，**不编默认值**）。 */
export function findCarrier(
  capabilities: WaybillCapabilities | null | undefined,
  code: string | null | undefined,
): WaybillCarrier | undefined {
  if (!capabilities || !code) return undefined
  return capabilities.carriers.find((c) => c.code === code)
}

/**
 * 按**商家可见名**找承运商（发货页的既有选择器存的是名字；名字 = 服务端注册表的 displayName）。
 *
 * 名字与注册表 `displayName` 逐字对齐（跨端契约）；自定义承运商（词表外手填）⇒ `undefined`。
    ⚠️ 本模块**不出现任何承运商名字面量**（判据 `tests/unit/lib/waybill.test.ts` 的「判据 2b」扫源码）——
    例子一律写成「服务端下发的 displayName」，别在这里抄一份词表。
 */
export function findCarrierByName(
  capabilities: WaybillCapabilities | null | undefined,
  displayName: string | null | undefined,
): WaybillCarrier | undefined {
  const name = (displayName ?? '').trim()
  if (!capabilities || !name) return undefined
  return capabilities.carriers.find((c) => c.displayName === name)
}

/** 发货页「取号」按钮的判定结果（能力位 + 一句可行动的说明）。 */
export interface WaybillCapabilityView {
  /** 命中的注册表行（未登记 ⇒ {@link MANUAL_CARRIER}） */
  carrier: WaybillCarrier
  /** 按钮可不可用 —— **只**看注册表能力位 */
  canCreate: boolean
  mode: WaybillMode
  /** 按钮禁用 / 可用时的说明（给出下一步动作，不是笼统「不可用」） */
  hint: string
}

/**
 * 发货页按「当前选的承运商」取能力位。
 *
 * @param company 发货页选中的承运商**名字**（词表外自定义值也合法 —— 词表只是候选）
 *
 * 判定顺序（**数据驱动，没有承运商名分支**）：
 * 1. 注册表里有这一家且 `canCreate` ⇒ 可用（`mode=api`）；
 * 2. 注册表里有这一家但没接入 ⇒ 禁用 + 「未接入取号，请手填单号」；
 * 3. 注册表里没有（自定义承运商 / 能力面没读到）⇒ 禁用 + 手填。
 */
export function waybillCapabilityFor(
  capabilities: WaybillCapabilities | null | undefined,
  company: string | null | undefined,
): WaybillCapabilityView {
  const registered = findCarrierByName(capabilities, company)
  const carrier = registered ?? MANUAL_CARRIER
  const canCreate = carrier.canCreate === true
  return {
    carrier,
    canCreate,
    mode: canCreate ? 'api' : 'manual',
    hint: canCreate
      ? `由「${carrier.displayName}」自动取号（取号后订单仍待发货，需再点「确认发货」）`
      : registered
        ? `「${registered.displayName}」未接入取号，请手填单号`
        : '当前承运商未接入取号，请手填单号',
  }
}

/** 某物流类型下的承运商候选（设置页下拉用；`null/未知` ⇒ 全量）。 */
export function carriersOfType(
  capabilities: WaybillCapabilities | null | undefined,
  logisticsType?: string | null,
): WaybillCarrier[] {
  if (!capabilities) return [MANUAL_CARRIER]
  const all = capabilities.carriers.filter((c) => c.code !== 'manual')
  if (!logisticsType) return all
  return all.filter((c) => c.logisticsType === logisticsType)
}

/**
 * 设置页的一行摘要：这家承运商**今天能不能自动取号** + 一句话（不摆内部 code）。
 *
 * 文案只陈述事实 + 该做什么（产品口径：智能专业的优雅绅士，不堆感叹号 / 不责备）。
 */
export function carrierSummary(carrier: WaybillCarrier): string {
  if (carrier.code === 'manual') return '不自动取号，发货时手填单号'
  if (carrier.canCreate) return '已接入取号，发货时自动生成运单号'
  return '未接入取号，发货时手填单号'
}
