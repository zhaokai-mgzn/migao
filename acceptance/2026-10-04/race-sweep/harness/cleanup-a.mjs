// 租户 25 内**只删本线探针对象**：用 pg_constraint 的 FK 图做通用级联（从探针根对象出发）
import { psql, log, OUT } from './lib.mjs'
import { execSql } from './lib2.mjs'
import { T_A, PROBE as M } from './config.mjs'
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const ev = { at: new Date().toISOString(), tenant: T_A, roots: {}, steps: [], errors: [], blocked: [] }
const titleOf = (t) => psql(`select id, name from products where tenant_id=${T_A} and name like '${M}%'`)

// ── 根集合（本线探针对象） ──
const roots = {
  products: `tenant_id=${T_A} and name like '${M}%'`,
  product_skus: `tenant_id=${T_A} and product_id in (select id from products where tenant_id=${T_A} and name like '${M}%')`,
  orders: `tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')`,
  // 列名口径（现取 information_schema 核对）：inbound_orders = {supplier, supplier_doc_no, warehouse, remark, source, import_run_id}；
  // **没有 dye_lot**（缸号在 inbound_order_items.dye_lot 与 stock_batches.dye_lot）
  inbound_orders: `tenant_id=${T_A} and (coalesce(supplier,'') like '${M}%' or coalesce(remark,'') like '${M}%' or coalesce(supplier_doc_no,'') like '${M}%')`,
  client_request_keys: `tenant_id=${T_A} and client_request_id like '${M}%'`,
}
const extra = {
  stock_batches: `tenant_id=${T_A} and (product_id in (select id from products where tenant_id=${T_A} and name like '${M}%') or sku_id in (select id from product_skus where tenant_id=${T_A} and product_id in (select id from products where tenant_id=${T_A} and name like '${M}%')) or supplier like '${M}%' or dye_lot like '${M}%' or inbound_order_id in (select id from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')))`,
  stock_batch_consumptions: `tenant_id=${T_A} and (stocktake_run_id like '${M}%' or batch_id in (select id from stock_batches where tenant_id=${T_A} and (supplier like '${M}%' or dye_lot like '${M}%')))`,
  stock_ledger_entries: `tenant_id=${T_A} and (product_id in (select id from products where tenant_id=${T_A} and name like '${M}%') or sku_id in (select id from product_skus where tenant_id=${T_A} and product_id in (select id from products where tenant_id=${T_A} and name like '${M}%')) or note like '%${M}%' or coalesce(ref_no,'') in (select order_no from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')) or coalesce(ref_no,'') in (select inbound_no from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')))`,
  order_shipments: `tenant_id=${T_A} and order_id in (select id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%'))`,
  // 列名口径：finance_transactions = {transaction_no, order_id, order_no, type, amount, remark, …}；**没有 ref_no**
  finance_transactions: `tenant_id=${T_A} and (order_id in (select id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')) or coalesce(order_no,'') in (select order_no from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')) or coalesce(remark,'') like '%${M}%')`,
  // 列名口径：processing_orders = {order_id, processing_order_no, …}；**没有 order_no**（那是 orders 的列）
  processing_orders: `tenant_id=${T_A} and (order_id in (select id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')) or coalesce(processing_order_no,'') in (select order_no from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')))`,
}
for (const [t, p] of Object.entries({ ...roots, ...extra })) {
  try { ev.roots[t] = { predicate: p, rows: psql(`select count(*)::int c from ${t} where ${p}`)[0].c } } catch (e) { ev.roots[t] = { predicate: p, error: String(e.message).slice(0, 120) } }
}

// ── FK 图（全库，不限 tenant_id：子表往往没有 tenant_id） ──
const fks = psql(`select tc.table_name as child, kcu.column_name as child_col, ccu.table_name as parent, ccu.column_name as parent_col
                  from information_schema.table_constraints tc
                  join information_schema.key_column_usage kcu on kcu.constraint_name = tc.constraint_name and kcu.table_schema = tc.table_schema
                  join information_schema.constraint_column_usage ccu on ccu.constraint_name = tc.constraint_name and ccu.table_schema = tc.table_schema
                  where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public'`)
const childrenOf = {}
for (const f of fks) (childrenOf[f.parent] ??= []).push(f)

// ── 从根出发求闭包（不反向引用父表；遇到环就跳过） ──
const pred = { ...roots, ...extra }
const order = []                       // 先父后子
const enqueue = (t) => { if (!pred[t]) { pred[t] = null; order.push(t) } else order.push(t) }
for (const t of Object.keys(pred)) order.push(t)
const known = new Set(Object.keys(pred))
for (let i = 0; i < order.length; i++) {
  const parent = order[i]
  for (const f of (childrenOf[parent] ?? [])) {
    const child = f.child
    if (known.has(child)) continue          // 已处理 / 根（根的谓词更精确）
    const p = pred[parent]
    if (!p) continue                        // 父表谓词未知 ⇒ 不扩散（保守）
    known.add(child); order.push(child)
    pred[child] = `${f.child_col} in (select ${f.parent_col} from ${parent} where ${p})`
  }
}
// 删除顺序 = 逆序（最深/最子表先删）
// 兜底：若子表已自带标记谓词，仍可能引用本线 products/product_skus（子表没有名字列）⇒ OR 上 FK 成员判定
for (const f of fks) {
  if (!['products', 'product_skus'].includes(f.parent)) continue
  if (!pred[f.child] || !pred[f.parent]) continue
  pred[f.child] = `(${pred[f.child]}) or ${f.child_col} in (select ${f.parent_col} from ${f.parent} where ${pred[f.parent]})`
}
const deleteOrder = [...order].reverse().filter((t) => pred[t])
ev.plan = { tablesInClosure: order.length, deleteOrder: deleteOrder.length }

const DRY = process.argv.includes('--dry')
let total = 0
for (let round = 1; round <= (DRY ? 1 : 4); round++) {
  let progress = 0
  for (const t of deleteOrder) {
    if (DRY) {
      // dry：只验谓词能否被 PG 解析（列名/子查询正确性），不做任何写
      try { const n = psql(`select count(*)::int c from ${t} where ${pred[t]}`)[0].c; if (n) ev.dryRows = (ev.dryRows ?? 0) + n }
      catch (e) { ev.errors.push({ round, table: t, kind: 'predicate_unparseable', msg: String(e.message).split('\n')[0].slice(0, 140) }) }
      continue
    }
    const r = execSql(`delete from ${t} where ${pred[t]}`)
    if (r.ok) { if (r.rows) { progress += r.rows; total += r.rows; ev.steps.push({ round, table: t, deleted: r.rows }) } }
    else ev.blocked.push({ round, table: t, msg: r.error })
  }
  if (!progress) break
}
ev.totalDeleted = total
// 现取读数
ev.after = {
  // 扫描面 = 根表 + 曾出现 FK 阻塞/列名错误的子表（含原来漏掉的 finance_transactions / inbound_labels / processing_orders）
  products: psql(`select count(*)::int c from products where tenant_id=${T_A} and name like '${M}%'`)[0].c,
  finance_transactions: psql(`select count(*)::int c from finance_transactions where tenant_id=${T_A} and (coalesce(remark,'') like '%${M}%' or coalesce(order_no,'') in (select order_no from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')))`)[0].c,
  processing_orders: psql(`select count(*)::int c from processing_orders where tenant_id=${T_A} and order_id in (select id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%'))`)[0].c,
  inbound_labels: psql(`select count(*)::int c from inbound_labels where tenant_id=${T_A} and inbound_order_id in (select id from inbound_orders where tenant_id=${T_A} and (coalesce(supplier,'') like '${M}%' or coalesce(remark,'') like '%${M}%'))`)[0].c,
  stock_batches: psql(`select count(*)::int c from stock_batches where tenant_id=${T_A} and (product_id in (select id from products where tenant_id=${T_A} and name like '${M}%') or coalesce(supplier,'') like '${M}%' or coalesce(dye_lot,'') like '${M}%')`)[0].c,
  orders: psql(`select count(*)::int c from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')`)[0].c,
  inbounds: psql(`select count(*)::int c from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')`)[0].c,
  keys: psql(`select count(*)::int c from client_request_keys where tenant_id=${T_A} and client_request_id like '${M}%'`)[0].c,
  ledger: psql(`select count(*)::int c from stock_ledger_entries where tenant_id=${T_A} and note like '%${M}%'`)[0].c,
  consumptions: psql(`select count(*)::int c from stock_batch_consumptions where tenant_id=${T_A} and stocktake_run_id like '${M}%'`)[0].c,
}
ev.blockedTop = Object.entries(ev.blocked.reduce((m, b) => { const k = b.table; (m[k] ??= 0); m[k]++; return m }, {})).sort((a, b) => b[1] - a[1]).slice(0, 8)
writeFileSync(join(OUT, DRY ? 'cleanup-tenantA-dry.json' : 'cleanup-tenantA.json'), JSON.stringify(ev, null, 2))
log(`租户 ${T_A} 探针清理：删除 ${total} 行；现取残留 ${JSON.stringify(ev.after)}；阻塞表 Top=${JSON.stringify(ev.blockedTop)}`)
