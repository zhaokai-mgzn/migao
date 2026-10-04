// 只读审计：本线在租户 25 的**残留面**（含原扫描集的盲区表），并按时间戳切分「本线窗口(≤09:24)」与「重放窗口(≥09:30)」
import { psql, OUT } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
const M='race-sweep', T=25
const rows = (sql) => { try { return psql(sql) } catch (e) { return [{ error: String(e.message).split('\n')[0].slice(0,120) }] } }
const audit = {
  at: new Date().toISOString(),
  probeOrders: rows(`select id, order_no, remark, created_at from orders where tenant_id=${T} and (remark like '${M}%' or customer_name like '${M}%') order by created_at`),
  finance_transactions: rows(`select id, transaction_no, order_id, order_no, remark, occurred_at, created_at from finance_transactions where tenant_id=${T} and (coalesce(remark,'') like '%${M}%' or order_id in (select id from orders where tenant_id=${T} and (remark like '${M}%' or customer_name like '${M}%'))) order by created_at`),
  inbound_labels: rows(`select id, inbound_order_id, short_code, created_at from inbound_labels where tenant_id=${T} and inbound_order_id in (select id from inbound_orders where tenant_id=${T} and (coalesce(supplier,'') like '${M}%' or coalesce(remark,'') like '%${M}%'))`),
  processing_orders: rows(`select id, order_id, processing_order_no, status, created_at from processing_orders where tenant_id=${T} and order_id in (select id from orders where tenant_id=${T} and (remark like '${M}%' or customer_name like '${M}%'))`),
  products: rows(`select id, name, created_at from products where tenant_id=${T} and name like '${M}%' order by created_at`),
  stock_ledger_entries: rows(`select count(*)::int c from stock_ledger_entries where tenant_id=${T} and note like '%${M}%'`),
  batch_conversations_note: '时间戳口径：本线观测窗口 09:04–09:24 +08；重放窗口自 09:30:44 +08（构建点切到 sha-6838a05）之后',
}
writeFileSync(join(OUT,'residue-audit.json'), JSON.stringify(audit,null,2))
console.log('probeOrders:', audit.probeOrders.length, JSON.stringify(audit.probeOrders.slice(0,2)))
console.log('finance_transactions:', audit.finance_transactions.length, JSON.stringify(audit.finance_transactions.slice(0,3)))
console.log('inbound_labels:', JSON.stringify(audit.inbound_labels))
console.log('processing_orders:', JSON.stringify(audit.processing_orders))
console.log('products:', audit.products.length, JSON.stringify(audit.products.slice(0,2)))
