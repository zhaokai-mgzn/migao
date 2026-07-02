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
 * - shippingMethod 不下发（后端不需要）
 */
export function buildLogisticsPayload(data: LogisticsFormData): {
  logisticsCompany: string
  trackingNo: string
} {
  return {
    logisticsCompany: data.company,
    trackingNo: data.trackingNo,
  }
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
