// p7：收尾残留清理（只删本轮探针对象；前缀 A06 / A06验收 / a06_；按 FK 子表优先）
import { psql, psqlWrite, PROBE, log, OUT } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const TENANT_ID = Number(process.env.TENANT_ID || 25)
const dry = process.argv.includes('--dry')

const before = psql(`select
  (select count(*) from users where tenant_id=${TENANT_ID} and (username like 'a06%' or nickname like '${PROBE}%' or worker_no like 'A06W%')) as users,
  (select count(*) from knowledge_cards where tenant_id=${TENANT_ID}) as knowledge,
  (select count(*) from orders where tenant_id=${TENANT_ID}) as orders,
  (select count(*) from after_sales_tickets where tenant_id=${TENANT_ID}) as tickets,
  (select count(*) from inbound_orders where tenant_id=${TENANT_ID}) as inbound`)[0]

const stmts = [
  `delete from knowledge_cards where tenant_id=${TENANT_ID} and (title like '${PROBE}%' or question like '${PROBE}%' or keywords like '${PROBE}%')`,
  `delete from after_sales_tickets where tenant_id=${TENANT_ID} and description like '${PROBE}%'`,
  `delete from order_items where order_id in (select id from orders where tenant_id=${TENANT_ID} and customer_name like '${PROBE}%')`,
  `delete from orders where tenant_id=${TENANT_ID} and customer_name like '${PROBE}%'`,
  `update users set deleted=1, status='disabled', username=null, phone=null where tenant_id=${TENANT_ID} and (username like 'a06%' or nickname like '${PROBE}%' or worker_no like 'A06W%')`,
]

const ran = []
for (const sql of stmts) {
  if (dry) { ran.push({ sql, out: '(dry)' }); continue }
  const out = psqlWrite(sql)
  ran.push({ sql, out: String(out || '').trim().slice(0, 120) })
}

const after = psql(`select
  (select count(*) from users where tenant_id=${TENANT_ID} and (username like 'a06%' or nickname like '${PROBE}%' or worker_no like 'A06W%')) as users,
  (select count(*) from knowledge_cards where tenant_id=${TENANT_ID}) as knowledge,
  (select count(*) from orders where tenant_id=${TENANT_ID}) as orders,
  (select count(*) from after_sales_tickets where tenant_id=${TENANT_ID}) as tickets,
  (select count(*) from inbound_orders where tenant_id=${TENANT_ID}) as inbound`)[0]

const out = { at: new Date().toISOString(), tenantId: TENANT_ID, dry, before, after, ran }
writeFileSync(join(OUT, 'p7-cleanup.json'), JSON.stringify(out, null, 2))
log(`== p7 清理 before=${JSON.stringify(before)} after=${JSON.stringify(after)} dry=${dry}`)
for (const r of ran) log(`   ${r.out || '(ok)'}  <= ${r.sql.slice(0, 110)}`)
