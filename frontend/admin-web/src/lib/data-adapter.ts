/**
 * 数据适配层 — 前后端数据格式转换
 *
 * 从 api.ts 提取的纯函数，确保前端表单数据正确转换为后端 API 期望格式。
 * 如果这些转换出错，数据会静默损坏。
 */

import type {
  ProductFormData,
  LogisticsFormData,
  CloseOrderParams,
} from '@/types'

/**
 * 将商品表单数据转换为创建/更新 API 的 payload。
 *
 * 转换规则：
 * - price → basePrice（后端字段名不同）
 * - images[0] → mainImage（后端需要单独的主图字段）
 * - 其余字段透传
 */
export function buildProductPayload(
  data: ProductFormData,
): Omit<ProductFormData, 'price'> & { basePrice: number; mainImage: string | null } {
  const { price, images, ...rest } = data
  return {
    ...rest,
    basePrice: price,
    mainImage: images?.[0] || null,
    images,
  }
}

/**
 * 将物流表单数据转换为更新物流 API 的 payload。
 *
 * 转换规则：
 * - company → logisticsCompany（前端用 company，后端用 logisticsCompany）
 * - trackingNo 透传
 * - shipperName 透传（发货单「经手人」，issue #3768）；留空则不下发，由后端按当前登录用户兜底
 * - logisticsType 透传（express 快递 / logistics 物流专线，issue #4419）；留空则不下发，
 *   由后端按列默认值 express 兜底
 * - shippingMethod 透传（issue #6239）：logistics 物流发货 / none 无需物流。
 *   用户在发货页做的这个选择此前**被前端丢掉**（后端从不读取）⇒「无需物流」与
 *   「物流发货但没填单号」在库里不可区分。
 *   ⚠️ **未采集（undefined）= 不下发该键**（issue #6254）：改前这里兜底成 `'logistics'`，
 *   于是「库里没采集过」与「采集到 logistics」在请求体里**不可区分**，后端据此把一条
 *   NULL 记录**凭空写成** `logistics`（造数据）；省略该键则后端按「不传 = 不改」保留原值
 *   （口径同 OR-058 判据 5②）。
 */
export function buildLogisticsPayload(data: LogisticsFormData): {
  logisticsCompany: string
  trackingNo: string
  shipperName?: string
  logisticsType?: string
  shippingMethod?: 'logistics' | 'none'
} {
  return {
    logisticsCompany: data.company,
    trackingNo: data.trackingNo,
    shipperName: data.shipperName?.trim() || undefined,
    logisticsType: data.logisticsType || undefined,
    shippingMethod: data.shippingMethod,
  }
}

/**
 * 订单详情「编辑物流」弹窗的**发货方式回填**（issue #6254）。
 *
 * <p>口径：只透传记录里**真实采集到**的取值（`logistics` / `none`）；
 * `NULL`（未采集 —— 工人 / 商家 / 生产 / 智能体那几条发货写面从不写这一列，
 * 且它们**结构性不产生「无需物流」语义**）⇒ 返回 `undefined` = **未记录**，
 * 由 {@link buildLogisticsPayload} 省略该键 ⇒ 后端保留原值。</p>
 *
 * <p>🔴 改前这里是「非 `none` ⇒ `logistics`」的兜底表达式
 * —— 把「未采集」静默解释成它的**反面语义**（物流发货）。</p>
 */
export function shippingMethodForEdit(
  shippingMethod: 'logistics' | 'none' | null | undefined,
): 'logistics' | 'none' | undefined {
  return shippingMethod === 'logistics' || shippingMethod === 'none' ? shippingMethod : undefined
}

/**
 * 将关单参数转换为取消订单 API 的 payload。
 *
 * 转换规则：
 * - reason → closeReason（前端用 reason，后端用 closeReason）
 */
export function buildCloseOrderPayload(
  data?: CloseOrderParams,
): { closeReason: string } {
  return {
    closeReason: data?.reason || '',
  }
}

/**
 * 退款参数（前端字段命名）
 */
export interface RefundOrderParams {
  refundAmount?: number        // 退款金额（缺省时不发送 refund_amount，后端视为全额退款）
  refundReason?: string        // 退款原因
}

/**
 * 将退款参数转换为退款 API 的 payload。
 *
 * 后端端点：PUT /api/admin/orders/{id}/refund
 * 转换规则（蛇形命名）：
 * - refundAmount → refund_amount（缺省则省略该字段）
 * - refundReason → refund_reason（trim 后下发）
 */
export function buildRefundPayload(data?: RefundOrderParams): { refund_reason: string; refund_amount?: number } {
  const payload: { refund_reason: string; refund_amount?: number } = {
    refund_reason: data?.refundReason?.trim() || '',
  }
  if (data?.refundAmount !== undefined && data.refundAmount !== null) {
    payload.refund_amount = data.refundAmount
  }
  return payload
}
