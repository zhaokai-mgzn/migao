// 线③ 收尾清理：① 租户 25 内**只删本线探针对象**（race-sweep 标记）② 清空临时租户 26 并删除其 tenants 行
// 算法：按 FK 拓扑迭代（每轮删得动的表删一批，直到一轮零进展）—— 不硬编码外键顺序，避免漏表。
// 纪律：租户 25 的删除谓词**只认本线标记**（绝不做整表/整租户删除）。
import { psql, log, OUT } from './lib.mjs'
import { execSql } from './lib2.mjs'
import { T_A, PROBE } from './config.mjs'
import { writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const FIX = existsSync(join(OUT, 'fixtures.json')) ? JSON.parse(readFileSync(join(OUT, 'fixtures.json'), 'utf8')) : {}
const T_B = Number(process.env.TEMP_TENANT || FIX.tenantB || 0)
const DRY = process.argv.includes('--dry')
const M = PROBE                                  // race-sweep
const evidence = { at: new Date().toISOString(), tenantA: T_A, tenantB: T_B, dry: DRY, before: {}, after: {}, steps: [], errors: [] }

const allTables = () => psql("select table_name from information_schema.columns where table_schema='public' and column_name='tenant_id' group by 1 order by 1").map((r) => r.table_name)
const colsOf = (t) => psql(`select column_name from information_schema.columns where table_schema='public' and table_name='${t}'`).map((r) => r.column_name)

// 本线在租户 A 的探针对象集合（先取 id，再按 id 级联删）
function probeIdsA() {
  const ids = {}
  ids.products = psql(`select id::text id from products where tenant_id=${T_A} and name like '${M}%'`).map((r) => r.id)
  ids.orders = psql(`select id::text id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')`).map((r) => r.id)
  ids.inbounds = psql(`select id::text id from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')`).map((r) => r.id)
  ids.batches = psql(`select id::text id from stock_batches where tenant_id=${T_A} and (supplier like '${M}%' or dye_lot like '${M}%')`).map((r) => r.id)
  ids.inboundNos = psql(`select inbound_no from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')`).map((r) => r.inbound_no)
  ids.orderNos = psql(`select order_no from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')`).map((r) => r.order_no)
  return ids
}
const q = (list) => list.length ? list.map((x) => `'${String(x).replace(/'/g, "''")}'`).join(',') : null
function probePredicates(t) {
  const ids = FIX._idsA || probeIdsA()
  const p = {}
  const add = (table, sql) => { if (sql) p[table] = sql }
  add('products', `tenant_id=${T_A} and name like '${M}%'`)
  add('product_skus', `tenant_id=${T_A} and product_id in (select id from products where tenant_id=${T_A} and name like '${M}%')`)
  add('orders', `tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')`)
  add('order_items', `order_id in (select id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%'))`)
  add('order_shipments', `tenant_id=${T_A} and order_id in (select id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%'))`)
  add('order_shipment_items', `shipment_id in (select id from order_shipments where tenant_id=${T_A} and order_id in (select id from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')))`)
  add('inbound_orders', `tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')`)
  add('inbound_order_items', `order_id in (select id from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%'))`)
  add('stock_batches', `tenant_id=${T_A} and (supplier like '${M}%' or dye_lot like '${M}%')`)
  add('stock_batch_consumptions', `tenant_id=${T_A} and (stocktake_run_id like '${M}%' or batch_id in (select id from stock_batches where tenant_id=${T_A} and (supplier like '${M}%' or dye_lot like '${M}%')))`)
  add('stock_ledger_entries', `tenant_id=${T_A} and (note like '%${M}%' or ref_no in (${q(ids.inboundNos) ?? 'null'}) or ref_no in (${q(ids.orderNos) ?? 'null'}))`)
  add('client_request_keys', `tenant_id=${T_A} and client_request_id like '${M}%'`)
  add('finance_transactions', `tenant_id=${T_A} and (ref_no in (${q(ids.orderNos) ?? 'null'}) or remark like '${M}%')`)
  add('processing_orders', `tenant_id=${T_A} and order_no in (${q(ids.orderNos) ?? 'null'})`)
  add('tenant_applications', `phone = '13800138001'`)
  return p
}

// 通用 FK 容错迭代删除：每轮尝试所有表，删得动就删，零进展即停
function sweep(predicates, label) {
  let total = 0
  const deleted = {}
  for (let round = 1; round <= 12; round++) {
    let progress = 0
    for (const [table, pred] of Object.entries(predicates)) {
      const cols = colsOf(table)
      if (!cols.length) continue
      const r = execSql(`delete from ${table} where ${pred}`)
      if (r.ok) { if (r.rows) { progress += r.rows; deleted[table] = (deleted[table] ?? 0) + r.rows } }
      else if (!/foreign key|violates|still referenced|不存在|does not exist/i.test(r.error || '')) {
        evidence.errors.push({ label, table, round, msg: r.error })
      }
    }
    total += progress
    evidence.steps.push({ label, round, deletedThisRound: progress })
    if (progress === 0) break
  }
  return { total, deleted }
}

// ── ① 租户 25：本线探针对象 ──
const predsA = probePredicates(T_A)
evidence.before.tenantA = {
  products: psql(`select count(*)::int c from products where tenant_id=${T_A} and name like '${M}%'`)[0].c,
  orders: psql(`select count(*)::int c from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')`)[0].c,
  inbounds: psql(`select count(*)::int c from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')`)[0].c,
  keys: psql(`select count(*)::int c from client_request_keys where tenant_id=${T_A} and client_request_id like '${M}%'`)[0].c,
  ledger: psql(`select count(*)::int c from stock_ledger_entries where tenant_id=${T_A} and note like '%${M}%'`)[0].c,
}
if (!DRY) {
  const rA = sweep(predsA, 'tenantA')
  evidence.after.tenantA = { deleted: rA.deleted, total: rA.total }
  evidence.after.tenantA.readback = evidence.before.tenantA && Object.fromEntries(Object.keys(evidence.before.tenantA).map((k) => [k,
    k === 'products' ? psql(`select count(*)::int c from products where tenant_id=${T_A} and name like '${M}%'`)[0].c
    : k === 'orders' ? psql(`select count(*)::int c from orders where tenant_id=${T_A} and (remark like '${M}%' or customer_name like '${M}%')`)[0].c
    : k === 'inbounds' ? psql(`select count(*)::int c from inbound_orders where tenant_id=${T_A} and (supplier like '${M}%' or remark like '${M}%')`)[0].c
    : k === 'keys' ? psql(`select count(*)::int c from client_request_keys where tenant_id=${T_A} and client_request_id like '${M}%'`)[0].c
    : psql(`select count(*)::int c from stock_ledger_entries where tenant_id=${T_A} and note like '%${M}%'`)[0].c]))
}

// ── ② 临时租户 B：整租户清空 + tenants 行删除 ──
if (T_B) {
  evidence.before.tenantB = { tenantRow: psql(`select id, name, code, status from tenants where id=${T_B}`) ,
    perTable: {} }
  const tables = allTables()
  const predB = Object.fromEntries(tables.map((t) => [t, `tenant_id=${T_B}`]))
  predB.tenant_applications = `phone = '13800138001'`
  if (!DRY) {
    const rB = sweep(predB, 'tenantB')
    evidence.after.tenantB = { deleted: rB.deleted, totalDeletedRows: rB.total }
    // users 先于 tenants（BRIEF §4.3 的 FK 拓扑序）
    const ru = execSql(`delete from users where tenant_id=${T_B}`)
    if (ru.ok) evidence.after.tenantB.usersDeleted = ru.rows; else evidence.errors.push({ label: 'tenantB', table: 'users', msg: ru.error })
    const rt = execSql(`delete from tenants where id=${T_B}`)
    if (rt.ok) evidence.after.tenantB.tenantsDeleted = rt.rows; else evidence.errors.push({ label: 'tenantB', table: 'tenants', msg: rt.error })
    // 残余扫描（任何含 tenant_id 的表）
    const leftovers = []
    for (const t of tables) {
      try { const n = psql(`select count(*)::int c from ${t} where tenant_id=${T_B}`)[0].c; if (n > 0) leftovers.push({ table: t, rows: n }) } catch { /* 表不可计数 */ }
    }
    evidence.after.tenantB.leftovers = leftovers
    evidence.after.tenantB.tenantRow = psql(`select id, name from tenants where id=${T_B}`)
  }
}
// ── ③ 现取读数：tenants 只剩 25 ──
evidence.tenantsAfter = psql('select id, name from tenants order by id')
writeFileSync(join(OUT, `cleanup${DRY ? '-dry' : ''}.json`), JSON.stringify(evidence, null, 2))
log(`清理完成：tenants 现取 = ${JSON.stringify(evidence.tenantsAfter)}；租户25 探针残留 = ${JSON.stringify(evidence.after.tenantA?.readback ?? {})}；租户${T_B} 残余表 = ${JSON.stringify(evidence.after.tenantB?.leftovers ?? [])}`)
console.log(JSON.stringify({ tenants: evidence.tenantsAfter, errors: evidence.errors.slice(0, 6) }, null, 2))
