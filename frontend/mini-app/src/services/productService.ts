/**
 * 商品相关 API 服务（C 端只读）
 *
 * 走 ai-agent-service 的 C 端端点（JWT 认证 + 服务端转发 admin-api），
 * C 端不直连 admin-api，避免 customer 角色被 RequirePermission 拒绝。
 */

import { get } from '../utils/request'
import { AI_API_BASE_URL } from '../utils/constants'
import type { ApiResponse } from '../types'

/** C 端可展示的商品精简字段 */
export interface MiniProduct {
  id: string
  name: string
  price: number | string
  image?: string
  sales_count?: number
}

/** C 端「我的订单」精简字段 */
export interface MiniOrder {
  id: string
  order_no: string
  status: string
  status_text: string
  total_amount: number | string
  created_at: string
}

/** C 端「我的售后」精简字段 */
export interface MiniTicket {
  id: string
  ticket_no: string
  status: string
  ticket_type: string
  created_at: string
}

/**
 * 我的订单（「我的」页入口，强制按当前用户过滤）
 * GET /api/chat/orders/mine?page=1&size=5
 */
export async function getMyOrders(size = 5): Promise<MiniOrder[]> {
  const res = await get<ApiResponse<{ items: MiniOrder[]; total: number }>>(
    '/api/chat/orders/mine',
    { baseURL: AI_API_BASE_URL, params: { page: 1, size } },
  )
  if (!res.success || !res.data) return []
  return (res.data.items || []).map((o: any) => ({
    id: o.id,
    order_no: o.order_no || '',
    status: o.status || '',
    status_text: o.status_text || o.status || '',
    total_amount: o.total_amount ?? 0,
    created_at: o.created_at || '',
  }))
}

/**
 * 我的售后工单（「我的」页入口，强制按当前用户过滤）
 * GET /api/chat/after-sales/mine?page=1&size=5
 */
export async function getMyTickets(size = 5): Promise<MiniTicket[]> {
  const res = await get<ApiResponse<{ items: MiniTicket[]; total: number }>>(
    '/api/chat/after-sales/mine',
    { baseURL: AI_API_BASE_URL, params: { page: 1, size } },
  )
  if (!res.success || !res.data) return []
  return (res.data.items || []).map((t: any) => ({
    id: t.id,
    ticket_no: t.ticket_no || '',
    status: t.status || '',
    ticket_type: t.ticket_type || '',
    created_at: t.created_at || '',
  }))
}

/**
 * 收款二维码（支付页展示，issue #3990）
 * GET /api/chat/payment-qrcodes → {wechat: {image_url, payee_name}, alipay: {...}}
 */
export async function getPaymentQrcodes(): Promise<Record<string, { image_url?: string; payee_name?: string }>> {
  const res = await get<ApiResponse<Record<string, { image_url?: string; payee_name?: string }>>>(
    '/api/chat/payment-qrcodes',
    { baseURL: AI_API_BASE_URL },
  )
  if (!res.success || !res.data) return {}
  return res.data
}

export default { getMyOrders, getMyTickets, getPaymentQrcodes }


