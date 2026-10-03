// P10c：按**前缀**兜底清零（覆盖前几次脚本崩溃时建出来、没进 probe-ctx 的对象）
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { psql, log, OUT, Recorder, guardedWrite, PROBE_PREFIX } from './lib.mjs'
const T = Number(process.env.TENANT_ID || 20)
const R = new Recorder('p10c-cleanup.json')
const out = { at: new Date().toISOString() }
out.leftoversBefore = psql(`
  select
    (select count(*)::int from orders where tenant_id=${T} and coalesce(deleted,0)=0 and customer_name like '${PROBE_PREFIX}%') as orders,
    (select count(*)::int from products where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as products,
    (select count(*)::int from categories where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as categories,
    (select count(*)::int from processing_orders po join orders o on o.id=po.order_id
       where po.tenant_id=${T} and coalesce(po.deleted,0)=0 and o.customer_name like '${PROBE_PREFIX}%') as processing_orders`)[0]
// 按前缀软删（含订单下的加工单）
guardedWrite(`-- probe-ok
update processing_orders set deleted=1, updated_at=NOW()
where tenant_id=${T} and coalesce(deleted,0)=0
  and order_id in (select id from orders where tenant_id=${T} and customer_name like '${PROBE_PREFIX}%')`)
guardedWrite(`-- probe-ok
update products set deleted=1, status='draft', updated_at=NOW()
where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%'`)
guardedWrite(`-- probe-ok
update categories set deleted=1, updated_at=NOW()
where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%'`)
guardedWrite(`-- probe-ok
update orders set deleted=1, status='cancelled', updated_at=NOW()
where tenant_id=${T} and coalesce(deleted,0)=0 and customer_name like '${PROBE_PREFIX}%'`)
guardedWrite(`-- probe-ok
update production_route_templates set deleted=1, updated_at=NOW()
where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%'`)

const residue = psql(`
  select
    (select count(*)::int from production_work_logs where tenant_id=${T} and worker_name like '${PROBE_PREFIX}%') as probe_worklogs,
    (select count(*)::int from orders where tenant_id=${T} and coalesce(deleted,0)=0 and customer_name like '${PROBE_PREFIX}%') as probe_orders_alive,
    (select count(*)::int from products where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_products_alive,
    (select count(*)::int from categories where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_categories_alive,
    (select count(*)::int from production_route_templates where tenant_id=${T} and coalesce(deleted,0)=0 and name like '${PROBE_PREFIX}%') as probe_routes_alive,
    (select count(*)::int from production_operation_positions where tenant_id=${T} and id like 'probe-%') as probe_position_rows,
    (select count(*)::int from production_operations where tenant_id=${T} and name like '${PROBE_PREFIX}%') as probe_library_ops,
    (select count(*)::int from processing_orders po join orders o on o.id=po.order_id
       where po.tenant_id=${T} and coalesce(po.deleted,0)=0 and o.customer_name like '${PROBE_PREFIX}%') as probe_processing_orders_alive
`)[0]
out.residue = residue
const total = Object.values(residue).reduce((a, b) => a + b, 0)
R[total === 0 ? 'pass' : 'fail']('P10c-01', '探针存活残留 = 0（直连 RDS，8 个域，按前缀兜底）',
  `合计 ${total}；${JSON.stringify(residue)}`, ['SQL: 见 out/p10c-cleanup.json .residue'])
out.residueZero = total === 0
writeFileSync(join(OUT, 'p10c-cleanup.json'), JSON.stringify(out, null, 2))
log(`zero-residue: ${JSON.stringify(residue)}`)
log(`summary=${JSON.stringify(R.summary())}`)
