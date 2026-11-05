/**
 * 物流取号（电子面单）**能力面类型**（issue #8698 P0）。
 *
 * 与后端 `Carrier` / `WaybillCapabilities` 逐字段对齐（`com.migao.admin.controller.WaybillController`
 * 的 `carrierPayload` / `capabilityPayload`）。**不是** `@/types` 的追加 ——
 * `frontend/admin-web/src/types/index.ts` 有行数冻结（`loc_freeze_ledger.json`）⇒
 * 新类型一律落 `types/<域>.ts`（口径见 `migao-dev-flow` §34.4）。
 */

/** 物流类型（与 `lib/logistics.ts` 的 `LOGISTICS_TYPES` 同域） */
export type WaybillLogisticsType = 'express' | 'logistics'

/** 承运商**生效形态**：`api` = 已接入取号；`manual` = 退回手填 */
export type WaybillMode = 'api' | 'manual'

/** 承运商注册表的一行 —— 能力位来自服务端（**前端不复制词表、不按名字硬编码**）。 */
export interface WaybillCarrier {
  code: string
  displayName: string
  logisticsType: WaybillLogisticsType | null
  /** 轨迹查询编码映射（既有轨迹工具认的 code；`null` = 今天没有映射） */
  trackQueryCode: string | null
  canCreate: boolean
  canCancel: boolean
  canTrack: boolean
  mode: WaybillMode
}

/** 本租户的取号能力面（设置页与发货页共用的**唯一读面**）。 */
export interface WaybillCapabilities {
  carriers: WaybillCarrier[]
  /** 库里存的承运商 code（`null` = 没配 ⇒ 全 hand-fill） */
  configuredCarrier: string | null
  /** 解析后的生效承运商（未登记 ⇒ manual） */
  effectiveCarrier: WaybillCarrier
  /** 是否处于手填兜底（= 今天不能自动取号） */
  manualFallback: boolean
}

/** 取号请求体（与后端 `WaybillCreateRequest` 逐字段对齐）。 */
export interface WaybillCreatePayload {
  receiverName?: string
  receiverPhone?: string
  receiverAddress?: string
  packageCount?: number
  weightKg?: number
}

/** 取号结果（**不含订单状态** —— 取号 ≠ 发货）。 */
export interface WaybillCreated {
  trackingNo: string
  carrierCode: string
  carrierName: string
}
