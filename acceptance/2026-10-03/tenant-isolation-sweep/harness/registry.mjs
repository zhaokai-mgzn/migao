// 资源面注册表：每个「有 tenant 维度」的资源 = 表 + 列表端点 + 按 id 读端点 + 写端点 + id 提取器
// 数据来源：information_schema（79 张含 tenant_id 的表）× OpenAPI（244 path）
// 纪律：绝不猜 id 形态；id 一律**直连 DB 取真值**（见 snapshot.mjs），随机不存在 id 用于防「一律 404」假绿。
import { psql } from '../../config-writeface-sweep/harness/lib.mjs'

// 列表返回体的 id 提取器（形态实测：items / records / 裸数组 / 命名键）
const pick = {
  items: (d) => (d?.items ?? []).map((x) => x.id),
  arr: (d) => (Array.isArray(d) ? d : []).map((x) => x.id),
  routings: (d) => (d?.routings ?? []).map((x) => x.id),
  combinations: (d) => (d?.combinations ?? []).map((x) => x.id),
  cards: (d) => (d?.items ?? d?.cards ?? []).map((x) => x.id),
  groups: (d) => (d?.groups ?? []).flatMap((g) => (g.operations ?? g.items ?? []).map((x) => x.id)),
}

export const RESOURCES = [
  // ── 商品 / 客户 / 分类 ───────────────────────────────────────────
  { key:'products',      label:'商品',       table:'products',              list:'/api/admin/products?page=1&size=1000',  extract:pick.items, read:(id)=>`/api/admin/products/${id}`, write:'PUT', writeBody:()=>({}), snap:['name','base_price','status','stock','updated_at','deleted'] },
  { key:'customers',     label:'客户',       table:'customer_profiles',     list:'/api/admin/customers?page=1&size=1000', extract:pick.items, read:(id)=>`/api/admin/customers/${id}`, write:'PUT', writeBody:()=>({}), snap:['wechat_nickname','phone','vip_level','customer_status','craft_mode','updated_at'] },
  { key:'customer_tags', label:'客户标签',   table:'customer_tags',         list:'/api/admin/customer-tags',              extract:pick.arr,   read:null, write:'PUT', writeBody:()=>({}), snap:['name','color','hit_count','updated_at'] },
  { key:'categories',    label:'商品分类',   table:'categories',            list:'/api/admin/categories',                 extract:pick.arr,   read:null, write:'PUT', writeBody:()=>({}), snap:['name','parent_id','sort_order','updated_at','deleted'] },
  // ── 工序库 / 工艺路线 / 价目矩阵 / 路线规则 ─────────────────────
  { key:'operations',    label:'工序库',     table:'production_operations', list:'/api/admin/production/operations-catalog?page=1&size=1000', extract:pick.groups, read:null, write:'PUT', writeBody:()=>({}), snap:['name','group_name','unit_price','scope','status','updated_at','deleted'] },
  { key:'routings',      label:'工艺路线',   table:'production_route_templates', list:'/api/admin/production/routings',   extract:pick.routings, read:null, write:'PUT', writeBody:()=>({}), snap:['name','is_default','positions','mainline','status','updated_at','deleted'] },
  { key:'route_rules',   label:'路线规则',   table:'production_route_rules',list:'/api/admin/production/route-rules',     extract:pick.arr,   read:null, write:'DELETE', writeBody:null, snap:['trigger_value','operation','action','priority','status','updated_at','deleted'] },
  { key:'op_positions',  label:'价目矩阵行', table:'production_operation_positions', list:'/api/admin/production/operation-positions', extract:pick.arr, read:null, write:'PUT', writeBody:()=>({}), snap:['logical_name','position','unit_price','status','updated_at','deleted'] },
  { key:'fee_combos',    label:'加工费组合', table:'processing_fee_combinations', list:'/api/admin/production/processing-fee-combinations', extract:pick.combinations, read:null, write:'PUT', writeBody:()=>({}), snap:['composition_key','unit_price','status','updated_at','deleted'] },
  // ── 加工项 / 加工分类 / 订单 / 加工单 ───────────────────────────
  { key:'processing_items', label:'加工项',  table:'processing_items',      list:'/api/admin/processing-items?query=&page=1&size=1000', extract:pick.items, read:(id)=>`/api/admin/processing-items/${id}`, write:'PUT', writeBody:()=>({}), snap:['name','unit','status','updated_at','deleted'] },
  { key:'processing_categories', label:'加工分类', table:'processing_categories', list:'/api/admin/processing-categories', extract:pick.arr, read:(id)=>`/api/admin/processing-categories/${id}`, write:'PUT', writeBody:()=>({}), snap:['name','sort_order','status','updated_at','deleted'] },
  { key:'orders',        label:'订单',       table:'orders',                list:'/api/admin/orders?page=1&size=1000',   extract:pick.items, read:(id)=>`/api/admin/orders/${id}`, write:'PUT', writeBody:null, writeVia:'content', snap:['order_no','status','total_amount','remark','updated_at','deleted'] },
  { key:'processing_orders', label:'加工单', table:'processing_orders',     list:'/api/admin/processing-orders',         extract:pick.arr,   read:(id)=>`/api/admin/processing-orders/${id}`, write:'PATCH', writeBody:()=>({}), snap:['processing_order_no','status','remark','route_key','updated_at','deleted'] },
  { key:'inbound_orders',label:'入库单',     table:'inbound_orders',        list:'/api/admin/inbound-orders',            extract:pick.arr,   read:(id)=>`/api/admin/inbound-orders/${id}`, write:'PATCH', writeBody:()=>({}), snap:['inbound_no','status','total_amount','remark','updated_at','deleted'] },
  { key:'shipments',     label:'发货单',     table:'order_shipments',       list:'/api/admin/shipments',                 extract:pick.arr,   read:null, write:null, snap:['shipment_no','tracking_no','updated_at','deleted'] },
  { key:'stock_batches', label:'库存批次',   table:'stock_batches',         list:'/api/admin/batch-stock/batches',       extract:pick.items, read:null, write:null, snap:['batch_no','quantity','updated_at','deleted'] },
  { key:'stock_ledger',  label:'库存流水',   table:'stock_ledger_entries',  list:'/api/admin/stock-ledger?page=1&size=1000', extract:pick.items, read:null, write:null, snap:['reason','delta','before_qty','after_qty','created_at'] },
  { key:'finance_tx',    label:'财务流水',   table:'finance_transactions',  list:'/api/admin/finance/transactions?page=1&size=1000', extract:pick.items, read:null, write:null, snap:['transaction_no','type','amount','status','updated_at','deleted'] },
  // ── 通知 / 知识 / 角色 / 售后 ──────────────────────────────────
  { key:'notif_templates', label:'通知模板', table:'notification_templates', list:'/api/admin/notification-templates?page=1&size=1000', extract:pick.items, read:null, write:'PUT', writeBody:()=>({}), snap:['name','status','updated_at'] },
  { key:'notif_rules',   label:'通知规则',   table:'notification_rules',    list:'/api/admin/notification-rules?page=1&size=1000', extract:pick.items, read:null, write:'PUT', writeBody:()=>({}), snap:['event_type','enabled','updated_at'] },
  { key:'knowledge_cards', label:'知识卡片', table:'knowledge_cards',       list:'/api/admin/knowledge/cards?page=1&size=1000', extract:pick.cards, read:null, write:'PUT', writeBody:()=>({}), snap:['title','question','status','version','updated_at','deleted'] },
  { key:'roles',         label:'角色',       table:'roles',                 list:'/api/admin/roles?page=1&size=1000',    extract:pick.items, read:(id)=>`/api/admin/roles/${id}`, write:'PUT', writeBody:()=>({}), snap:['name','code','status','updated_at','deleted'] },
  { key:'after_sales',   label:'售后工单',   table:'after_sales_tickets',   list:'/api/admin/after-sales?page=1&size=1000', extract:pick.items, read:(id)=>`/api/admin/after-sales/${id}`, write:null, snap:['ticket_no','status','updated_at','deleted'], writeVia:'status' },
  { key:'users',         label:'员工用户',   table:'users',                 list:'/api/admin/users?page=1&size=1000',    extract:pick.items, read:(id)=>`/api/admin/users/${id}`, write:'PUT', writeBody:()=>({}), snap:['nickname','role','status','updated_at','deleted'] },
  { key:'agent_sessions',label:'客服会话',   table:'agent_sessions',        list:'/api/admin/agent-sessions?page=1&size=1000', extract:pick.items, read:(id)=>`/api/admin/agent-sessions/${id}`, write:null, snap:['status','updated_at','deleted'] },
  { key:'employees',     label:'客服员工',   table:'agent_employees',       list:'/api/admin/workers?page=1&size=1000',  extract:pick.items, read:null, write:null, snap:['name','status','updated_at','deleted'] },
  { key:'remnants',      label:'布头余料',   table:'fabric_remnants',       list:'/api/admin/production/remnants',       extract:pick.arr,   read:null, write:null, snap:['piece_seq','status','length_m','created_at'] },
]

/** 从 DB 取某资源在某租户的**真值 id 集合**（含 tenant_id 直连核对）。 */
export function dbIds(table, tenantId, limit = 100000) {
  const hasDel = psql(`select 1 as x from information_schema.columns where table_schema='public' and table_name='${table}' and column_name='deleted'`).length > 0
  const del = hasDel ? ' and coalesce(deleted,0)=0' : ''
  const rows = psql(`select id::text as id from ${table} where tenant_id=${tenantId}${del} limit ${limit}`)
  return rows.map((r) => String(r.id))
}

/** 取一行完整快照（字段级），用于前后比对。 */
/** 只保留真实存在的列（防「快照列写错 ⇒ SQL 报错」这类假红源）。 */
export function realCols(table, cols) {
  const have = new Set(psql(`select column_name from information_schema.columns where table_schema='public' and table_name='${table}'`).map((r) => r.column_name))
  return cols.filter((c) => have.has(c))
}

export function rowSnapshot(table, id, cols) {
  const hasDel = psql(`select 1 as x from information_schema.columns where table_schema='public' and table_name='${table}' and column_name='deleted'`).length > 0
  const sel = ['id::text as id', ...cols.filter((c) => c !== 'id'), 'tenant_id'].join(', ')
  return psql(`select ${sel} from ${table} where id::text='${String(id).replace(/'/g, "''")}' limit 1`)[0] ?? null
}
export { psql }
