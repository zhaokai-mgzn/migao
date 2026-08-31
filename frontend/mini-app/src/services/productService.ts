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
 * 新品推荐（商家显式打标的在售商品）
 * GET /chat/products/new-arrivals?size=6
 */
export async function getNewArrivals(size = 6): Promise<MiniProduct[]> {
  const res = await get<ApiResponse<{ items: MiniProduct[]; total: number }>>(
    '/chat/products/new-arrivals',
    { baseURL: AI_API_BASE_URL, params: { size } },
  )
  if (!res.success || !res.data) return []
  return (res.data.items || []).map((p: any) => ({
    id: p.id,
    name: p.name || '',
    price: p.price ?? 0,
    image: p.image,
    sales_count: p.sales_count ?? 0,
  }))
}

/**
 * 我的订单（「我的」页入口，强制按当前用户过滤）
 * GET /chat/orders/mine?page=1&size=5
 */
export async function getMyOrders(size = 5): Promise<MiniOrder[]> {
  const res = await get<ApiResponse<{ items: MiniOrder[]; total: number }>>(
    '/chat/orders/mine',
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
 * GET /chat/after-sales/mine?page=1&size=5
 */
export async function getMyTickets(size = 5): Promise<MiniTicket[]> {
  const res = await get<ApiResponse<{ items: MiniTicket[]; total: number }>>(
    '/chat/after-sales/mine',
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

export default { getNewArrivals, getMyOrders, getMyTickets }


