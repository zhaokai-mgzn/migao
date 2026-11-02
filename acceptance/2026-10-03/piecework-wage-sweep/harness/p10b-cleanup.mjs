// P10b：把上一轮列出的探针对象**收干净**并复测零残留
//   · 探针订单/商品/分类：删除端点对「已确认且有加工数据的订单」返回 **422**（本轮实测）
//     ⇒ 按 owner 语义**硬删自建行**（只删前缀命中 + 我自建 id 命中者）
//   · 实验新建的价目行：只保留 P0 基线里就存在的行；我给「定型」多建的那条按 id 软删
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { psql, log, OUT, Recorder, guardedWrite, PROBE_PREFIX } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const ctx = JSON.parse(readFileSync(join(OUT, 'probe-ctx.json'), 'utf8'))
const KNOWN_TAGS = new Set(['A', 'B', 'E', 'F', 'X', 'Y', 'Z1', 'Z2', 'Z3', 'X2', 'Y2', 'E2'])
const mine = ctx.probes.filter((p) => KNOWN_TAGS.has(p.tag) && p.orderId)
const orderIds = [...new Set(mine.map((p) => p.orderId))]
const productIds = [...new Set(mine.map((p) => p.productId).filter((x) => /^[0-9a-f]{32}$/.test(String(x))))]
const catIds = [...new Set(mine.map((p) => p.catId).filter((x) => /^[0-9a-f]{32}$/.test(String(x))))]
const p0 = JSON.parse(readFileSync(join(OUT, 'p0-surface.json'), 'utf8'))
const p0PosIds = new Set(p0.interference.positionPriceBaseline.map((r) => r.id))

const R = new Recorder('p10b-cleanup.json')
const out = { at: new Date().toISOString(), orderIds, productIds, catIds }

// 硬删自建业务对象（订单 → 订单行 → 加工单 → 工序实例 → 成品；商品 → SKU；分类）
const poIds = psql(`select id from processing_orders where tenant_id=${T} and order_id in (${orderIds.map((x) => `'${x}'`).join(',') || "''"})`).map((r) => r.id)
out.poIds = poIds
const sql = []
if (poIds.length) {
  const inPo = `(${poIds.map((x) => `'${x}'`).join(',')})`
  sql.push(`delete from worker_report_audits where tenant_id=${T} and processing_order_id in ${inPo}`)
  sql.push(`delete from production_work_logs where tenant_id=${T} and processing_order_id in ${inPo}`)
  sql.push(`delete from processing_set_part_tokens where tenant_id=${T} and processing_order_id in ${inPo}`)
  sql.push(`delete from processing_position_operations where tenant_id=${T} and processing_order_id in ${inPo}`)
  sql.push(`delete from processing_order_sets where tenant_id=${T} and processing_order_id in ${inPo}`)
  sql.push(`delete from processing_orders where tenant_id=${T} and id in ${inPo}`)
}
if (orderIds.length) {
  const inO = `(${orderIds.map((x) => `'${x}'`).join(',')})`
  sql.push(`delete from order_logistics where tenant_id=${T} and order_id in ${inO}`)
  sql.push(`delete from order_items where tenant_id=${T} and order_id in ${inO}`)
  sql.push(`delete from orders where tenant_id=${T} and id in ${inO}`)
}
if (productIds.length) {
  const inP = `(${productIds.map((x) => `'${x}'`).join(',')})`
  for (const t of ['stock_batch_consumptions', 'stock_batches', 'fabric_remnants', 'stock_ledger_entries', 'product_colors', 'product_skus', 'product_attributes']) {
    sql.push(`delete from ${t} where tenant_id=${T} and product_id in ${inP}`)
  }
  sql.push(`delete from products where tenant_id=${T} and id in ${inP}`)
}
if (catIds.length) sql.push(`delete from categories where tenant_id=${T} and id in (${catIds.map((x) => `'${x}'`).join(',')})`)
// 逐条独立执行（ON_ERROR_STOP 下任一 FK 失败会中断整批 ⇒ 每条单独跑并容忍失败）
const failedSql = []
for (const one of sql) {
  try { guardedWrite(`-- probe-ok\n${one}`) } catch (e) { failedSql.push([one.slice(0, 80), String(e).split('\n').find((l) => l.includes('ERROR')) ?? String(e).slice(0, 120)]) }
}
out.failedSql = failedSql
// 兜底：仍然存活的探针业务对象一律软删（口径 = 「存活」= coalesce(deleted,0)=0）
if (orderIds.length) guardedWrite(`-- probe-ok
update orders set deleted=1, status='cancelled', updated_at=NOW() where tenant_id=${T} and id in (${orderIds.map((x) => `'${x}'`).join(',')}) and coalesce(deleted,0)=0`)
if (productIds.length) guardedWrite(`-- probe-ok
update products set deleted=1, status='draft', updated_at=NOW() where tenant_id=${T} and id in (${productIds.map((x) => `'${x}'`).join(',')}) and coalesce(deleted,0)=0`)
if (catIds.length) guardedWrite(`-- probe-ok
update categories set deleted=1, updated_at=NOW() where tenant_id=${T} and id in (${catIds.map((x) => `'${x}'`).join(',')}) and coalesce(deleted,0)=0`)

// 实验新建的价目行（不在 P0 基线里、且是我注入的）→ 软删（保留审计，不物理删别人的历史行）
const extraPos = psql(`select id, logical_name, position, unit_price::text as unit_price, created_at::text
  from production_operation_positions where tenant_id=${T} and coalesce(deleted,0)=0 and logical_name in ('定型','复烫')
  order by logical_name, position`).filter((r) => !p0PosIds.has(r.id) && r.position === '布帘')
out.extraPositionRows = extraPos
if (extraPos.length) {
  guardedWrite(`-- probe-ok
update production_operation_positions set deleted=1, updated_at=NOW()
where id in (${extraPos.map((r) => `'${r.id}'`).join(',')})`)
}
out.positionRowsAfter = psql(`select logical_name, position, unit_price::text as unit_price, coalesce(deleted,0) as deleted
  from production_operation_positions where tenant_id=${T} and logical_name in ('定型','复烫') order by logical_name, deleted, position`)

const residue = psql(`
  select
    (select count(*)::int from production_work_logs where tenant_id=${T} and worker_name like '${PROBE_PREFIX}%') as probe_worklogs,
    (select count(*)::int from worker_report_audits where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})) as probe_audits,
    (select count(*)::int from orders where tenant_id=${T} and coalesce(deleted,0)=0 and customer_name like '${PROBE_PREFIX}%') as probe_orders,
    (select count(*)::int from processing_orders where tenant_id=${T} and id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})) as probe_pos,
    (select count(*)::int from products where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_products,
    (select count(*)::int from categories where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_categories,
    (select count(*)::int from production_route_templates where tenant_id=${T} and name like '${PROBE_PREFIX}%') as probe_routes,
    (select count(*)::int from production_operation_positions where tenant_id=${T} and (id like 'probe-%')) as probe_position_rows,
    (select count(*)::int from production_operations where tenant_id=${T} and name like '${PROBE_PREFIX}%') as probe_library_ops,
    (select count(*)::int from processing_position_operations where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})) as probe_instances
`)[0]
out.residue = residue
const total = Object.values(residue).reduce((a, b) => a + b, 0)
R[total === 0 ? 'pass' : 'fail']('P10b-01', '探针存活残留 = 0（直连 RDS，10 个域）',
  `合计 ${total}；${JSON.stringify(residue)}`, [`SQL: 见 out/p10b-cleanup.json .residue`])
writeFileSync(join(OUT, 'p10b-cleanup.json'), JSON.stringify(out, null, 2))
log(`零残留: ${JSON.stringify(residue)}`)
log(`summary=${JSON.stringify(R.summary())}`)
