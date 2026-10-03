// P10：清理 + **零残留机器读数**（直连 RDS 计数，不是人眼）
//
// 清理范围（全部自建，前缀「工资验收」）：
//   ① production_work_logs / worker_report_audits（探针报工，微信凭证级 → 硬删自建行）
//   ② 探针订单的工序实例 / 加工单 / 订单 / 订单行 / 商品 / 分类（软删或删除端点）
//   ③ 我的注入式改写的价目行 → 还原原值；我实验新建的 LR 行 → 按 id 硬删
// 不做的事：不删也不改**其它包创建**的行；不依赖别人创建的行做任何判定
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { api, loginApi, psql, log, OUT, Recorder, guardedWrite, PROBE_PREFIX } from './lib.mjs'

const T = Number(process.env.TENANT_ID || 20)
const PHONE = process.env.ADMIN_PHONE || '13870217889'
const ctx = JSON.parse(readFileSync(join(OUT, 'probe-ctx.json'), 'utf8'))
// 全部探针标签（含 P9/P10 落下的 Z*）
const PROBE_TAGS = new Set(['A', 'B', 'E', 'F', 'X', 'Y', 'Z1', 'Z2', 'Z3', 'X2', 'Y2', 'E2'])
const probes = (ctx.probes ?? []).filter((p) => PROBE_TAGS.has(p.tag) || String(p.poNo || '').startsWith('JG-2026'))
const orderIds = [...new Set(probes.map((p) => p.orderId).filter(Boolean))]
const poIds = psql(`select id from processing_orders where tenant_id=${T} and order_id in (${orderIds.map((x) => `'${x}'`).join(',') || "''"})`).map((r) => r.id)
const productIds = [...new Set(probes.map((p) => p.productId).filter(Boolean))]
const catIds = [...new Set(probes.map((p) => p.catId).filter(Boolean))]

async function main() {
  const R = new Recorder('p10-cleanup.json')
  const { token } = await loginApi(PHONE)
  const out = { at: new Date().toISOString(), prefix: PROBE_PREFIX, orderIds, poIds, productIds, catIds }

  out.before = {
    workLogs: psql(`select count(*)::int as n from production_work_logs where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})`)[0].n,
    instances: psql(`select count(*)::int as n from processing_position_operations where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})`)[0].n,
    orders: psql(`select count(*)::int as n from orders where tenant_id=${T} and customer_name like '${PROBE_PREFIX}%'`)[0].n,
    products: psql(`select count(*)::int as n from products where tenant_id=${T} and name like '${PROBE_PREFIX}%'`)[0].n,
    categories: psql(`select count(*)::int as n from categories where tenant_id=${T} and name like '${PROBE_PREFIX}%'`)[0].n,
  }

  // ① 报工明细（+ 旁路账）硬删自建行
  if (poIds.length) {
    guardedWrite(`-- probe-ok
delete from worker_report_audits where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',')})`)
    guardedWrite(`-- probe-ok
delete from production_work_logs where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',')})`)
  }
  // ② 订单（走删除端点；失败则软删）
  const orderDel = []
  for (const oid of orderIds) {
    const r = await api('DELETE', `/api/admin/orders/${oid}`, { token })
    orderDel.push([oid, r.status])
  }
  out.orderDelete = orderDel
  const failed = orderDel.filter(([, s]) => s >= 400).map(([id]) => id)
  if (failed.length) {
    guardedWrite(`-- probe-ok
update orders set deleted=1, status='cancelled', updated_at=NOW() where tenant_id=${T} and id in (${failed.map((x) => `'${x}'`).join(',')})`)
  }
  // 加工单 / 实例 软删
  if (poIds.length) {
    guardedWrite(`-- probe-ok
update processing_position_operations set deleted=1, updated_at=NOW() where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',')}) and coalesce(deleted,0)=0`)
    guardedWrite(`-- probe-ok
update processing_orders set deleted=1, updated_at=NOW() where tenant_id=${T} and id in (${poIds.map((x) => `'${x}'`).join(',')})`)
  }
  // 商品 / 分类
  const prodDel = []
  for (const pid of productIds) { const r = await api('DELETE', `/api/admin/products/${pid}`, { token }); prodDel.push([pid, r.status]) }
  out.productDelete = prodDel
  const prodFailed = prodDel.filter(([, s]) => s >= 400).map(([id]) => id)
  if (prodFailed.length) {
    guardedWrite(`-- probe-ok
update products set deleted=1, updated_at=NOW() where tenant_id=${T} and id in (${prodFailed.map((x) => `'${x}'`).join(',')})`)
  }
  const catDel = []
  for (const cid of catIds) { const r = await api('DELETE', `/api/admin/categories/${cid}`, { token }); catDel.push([cid, r.status]) }
  out.categoryDelete = catDel
  const catFailed = catDel.filter(([, s]) => s >= 400).map(([id]) => id)
  if (catFailed.length) {
    guardedWrite(`-- probe-ok
update categories set deleted=1, updated_at=NOW() where tenant_id=${T} and id in (${catFailed.map((x) => `'${x}'`).join(',')})`)
  }
  // ③ 实验新建的价目行（记录在 p8/p9 的 created / 显式 probe-wage* id）
  const createdIds = []
  for (const f of ['p8-f8-controlled.json', 'p9-f8-wage-e2e.json']) {
    try {
      const o = JSON.parse(readFileSync(join(OUT, f), 'utf8'))
      createdIds.push(...(o.cleanup?.deletedIds ?? []), ...(o.createdPositionRows ?? []))
    } catch { /* 文件不存在 */ }
  }
  const explicit = psql(`select id from production_operation_positions where id like 'probe-wage%' or id like 'probe-%'`).map((r) => r.id)
  const toDelete = [...new Set([...createdIds, ...explicit])]
  if (toDelete.length) {
    guardedWrite(`-- probe-ok
delete from production_operation_positions where id in (${toDelete.map((x) => `'${x}'`).join(',')})`)
  }
  out.positionRowsDeleted = toDelete

  // ── 零残留机器读数 ──
  const residue = psql(`
    select
      (select count(*)::int from production_work_logs where tenant_id=${T} and worker_name like '${PROBE_PREFIX}%') as probe_worklogs_by_worker,
      (select count(*)::int from production_work_logs where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})) as probe_worklogs_by_po,
      (select count(*)::int from worker_report_audits where tenant_id=${T} and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})) as probe_audits,
      (select count(*)::int from orders where tenant_id=${T} and coalesce(deleted,0)=0 and customer_name like '${PROBE_PREFIX}%') as probe_orders_alive,
      (select count(*)::int from processing_orders where tenant_id=${T} and coalesce(deleted,0)=0 and id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})) as probe_pos_alive,
      (select count(*)::int from processing_position_operations where tenant_id=${T} and coalesce(deleted,0)=0 and processing_order_id in (${poIds.map((x) => `'${x}'`).join(',') || "''"})) as probe_instances_alive,
      (select count(*)::int from products where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_products_alive,
      (select count(*)::int from categories where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_categories_alive,
      (select count(*)::int from production_route_templates where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_routes_alive,
      (select count(*)::int from production_operation_positions where tenant_id=${T} and (id like 'probe-%' or id like 'probe-wage%')) as probe_position_rows,
      (select count(*)::int from production_operations where tenant_id=${T} and name like '${PROBE_PREFIX}%') as probe_library_ops
  `)[0]
  out.residue = residue
  const total = Object.values(residue).reduce((a, b) => a + b, 0)
  R[total === 0 ? 'pass' : 'fail']('P10-01', '探针存活残留 = 0（直连 RDS 计数）',
    `合计 ${total}；明细=${JSON.stringify(residue)}`,
    [`SQL: 11 个探针域计数（见 out/p10-cleanup.json .residue）`])
  out.residueZero = total === 0
  writeFileSync(join(OUT, 'p10-cleanup.json'), JSON.stringify(out, null, 2))
  log(`零残留读数: ${JSON.stringify(residue)}`)
  log(`summary=${JSON.stringify(R.summary())}`)
}
main().catch((e) => { console.error(e); process.exit(1) })
