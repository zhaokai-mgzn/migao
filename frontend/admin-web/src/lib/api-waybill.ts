import request from './request'
import type { ApiResponse } from '@/types'
import type { WaybillCapabilities, WaybillCreatePayload, WaybillCreated } from '@/types/waybill'

/**
 * 物流取号读面 / 取号写面（issue #8698 P0）。
 *
 * ## 为什么单独一个模块
 *
 * `frontend/admin-web/src/lib/api.ts` 有**只许向下**的行数棘轮
 * （`tests/unit_ci_workflows/loc_freeze_ledger.json`）⇒ 新接口面放新文件，不回 `api.ts` 加行。
 *
 * ## 🔴 前端不直连承运商
 *
 * 这里**只有**本系统的 `/api/admin/logistics/*`。任何承运商的密钥 / 签名 / 直连域名
 * 都不许出现在前端（口径 `docs/logistics-waybill-api-research.md` §3-4；
 * 判据 `tests/unit_ci_workflows/test_waybill_no_carrier_secrets.py`）。
 */
export const waybillApi = {
  /**
   * 承运商注册表 + 本租户生效承运商（`production:view`）。
   *
   * 能力位的**唯一来源**：发货页据此决定「取号」按钮可不可用，设置页据此渲染下拉 ——
   * 新增 / 删除一家承运商只改服务端注册表，两处 UI 自动跟着变。
   */
  getCapabilities: () =>
    request.get<ApiResponse<WaybillCapabilities>>('/api/admin/logistics/carriers'),

  /** 写本租户承运商（`system:manage`）；传 `null` = 清空 = 全手填。 */
  saveCarrier: (carrierCode: string | null) =>
    request.put<ApiResponse<WaybillCapabilities>>('/api/admin/logistics/carrier-config', { carrierCode }),

  /**
   * **取号**（`production:execute`）—— 注意：取号 ≠ 发货。
   *
   * 成功后运单号只回填到发货页的「快递单号」输入框，订单**仍待发货**；
   * 状态流转仍走既有的 `productionApi.shipOrder`（本单一行不改它）。
   */
  createWaybill: (orderId: string, payload: WaybillCreatePayload) =>
    request.post<ApiResponse<WaybillCreated>>(
      `/api/admin/logistics/orders/${encodeURIComponent(orderId)}/waybill`,
      payload,
    ),
}
