// 并发探针资源面：只取「A(20) 侧有行」的列表/按 id 读端点 + 「B(21) 侧有行」的反向 id。
// 复用上一线（tenant-isolation-sweep/harness/registry.mjs）的端点与 id 提取器写法。
import { psql } from './lib.mjs'

export const A = { phone: '13870217889', tenant: 20, label: '米高POC演示布艺' }
export const B = { phone: '13797101248', tenant: 21, label: 'POC彩排5605' }
export const C = { phone: '13800138000', tenant: 1, label: '词元通达' }

const pick = {
  items: (d) => (d?.items ?? []).map((x) => x.id),
  arr: (d) => (Array.isArray(d) ? d : []).map((x) => x.id),
  groups: (d) => (d?.groups ?? []).flatMap((g) => (g.operations ?? g.items ?? []).map((x) => x.id)),
  routings: (d) => (d?.routings ?? []).map((x) => x.id),
  combinations: (d) => (d?.combinations ?? []).map((x) => x.id),
  cards: (d) => (d?.items ?? d?.cards ?? []).map((x) => x.id),
}

/** 每个资源：列表端点（返回体提取器）+ 按 id 读端点 + 直连 DB 表 */
export const RESOURCES = [
  { key: 'products', label: '商品', table: 'products', list: '/api/admin/products?page=1&size=500', extract: pick.items, read: (id) => `/api/admin/products/${id}` },
  { key: 'customers', label: '客户', table: 'customer_profiles', list: '/api/admin/customers?page=1&size=500', extract: pick.items, read: (id) => `/api/admin/customers/${id}` },
  { key: 'orders', label: '订单', table: 'orders', list: '/api/admin/orders?page=1&size=500', extract: pick.items, read: (id) => `/api/admin/orders/${id}` },
  { key: 'processing_items', label: '加工项', table: 'processing_items', list: '/api/admin/processing-items?query=&page=1&size=500', extract: pick.items, read: (id) => `/api/admin/processing-items/${id}` },
  { key: 'processing_categories', label: '加工分类', table: 'processing_categories', list: '/api/admin/processing-categories', extract: pick.arr, read: (id) => `/api/admin/processing-categories/${id}` },
  { key: 'roles', label: '角色', table: 'roles', list: '/api/admin/roles?page=1&size=500', extract: pick.items, read: (id) => `/api/admin/roles/${id}` },
  { key: 'users', label: '员工用户', table: 'users', list: '/api/admin/users?page=1&size=500', extract: pick.items, read: (id) => `/api/admin/users/${id}` },
  { key: 'after_sales', label: '售后工单', table: 'after_sales_tickets', list: '/api/admin/after-sales?page=1&size=500', extract: pick.items, read: (id) => `/api/admin/after-sales/${id}` },
  { key: 'operations', label: '工序库', table: 'production_operations', list: '/api/admin/production/operations-catalog?page=1&size=500', extract: pick.groups, read: null },
  { key: 'routings', label: '工艺路线', table: 'production_route_templates', list: '/api/admin/production/routings', extract: pick.routings, read: null },
  { key: 'op_positions', label: '价目矩阵行', table: 'production_operation_positions', list: '/api/admin/production/operation-positions', extract: pick.arr, read: null },
  { key: 'route_rules', label: '路线规则', table: 'production_route_rules', list: '/api/admin/production/route-rules', extract: pick.arr, read: null },
  { key: 'stock_ledger', label: '库存流水', table: 'stock_ledger_entries', list: '/api/admin/stock-ledger?page=1&size=500', extract: pick.items, read: null },
  { key: 'finance_tx', label: '财务流水', table: 'finance_transactions', list: '/api/admin/finance/transactions?page=1&size=500', extract: pick.items, read: null },
  { key: 'shipments', label: '发货单', table: 'order_shipments', list: '/api/admin/shipments', extract: pick.arr, read: null },
  { key: 'knowledge_cards', label: '知识卡片', table: 'knowledge_cards', list: '/api/admin/knowledge/cards?page=1&size=500', extract: pick.cards, read: null },
  { key: 'processing_orders', label: '加工单', table: 'processing_orders', list: '/api/admin/processing-orders', extract: pick.arr, read: (id) => `/api/admin/processing-orders/${id}` },
  { key: 'inbound_orders', label: '入库单', table: 'inbound_orders', list: '/api/admin/inbound-orders', extract: pick.arr, read: (id) => `/api/admin/inbound-orders/${id}` },
]

export function dbIds(table, tenantId, limit = 20000) {
  const hasDel = psql(`select 1 as x from information_schema.columns where table_schema='public' and table_name='${table}' and column_name='deleted'`).length > 0
  const del = hasDel ? ' and coalesce(deleted,0)=0' : ''
  return psql(`select id::text as id from ${table} where tenant_id=${tenantId}${del} limit ${limit}`).map((r) => String(r.id))
}
