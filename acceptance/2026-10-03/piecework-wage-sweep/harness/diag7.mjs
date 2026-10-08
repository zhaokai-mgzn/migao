import { psql } from './lib.mjs'
import { readFileSync } from 'node:fs'
const ctx = JSON.parse(readFileSync('out/probe-ctx.json', 'utf8'))
const zs = ctx.probes.filter((p) => ['Z1', 'Z2', 'Z3'].includes(p.tag))
console.log('Z orders:', JSON.stringify(zs.map((p) => ({ tag: p.tag, orderId: p.orderId }))))
for (const z of zs) {
  console.log('===', z.tag, z.orderId)
  console.log(JSON.stringify(psql(`select o.operation_name, o.unit_price::text as up, o.qty::text, o.created_at::text, coalesce(o.deleted,0) dl
    from processing_position_operations o join processing_orders p on p.id=o.processing_order_id
    where p.order_id='${z.orderId}' order by o.deleted, o.seq`)))
}
console.log('复烫 行:', JSON.stringify(psql(`select id,position,unit_price::text,coalesce(deleted,0) dl,updated_at::text from production_operation_positions where tenant_id=20 and logical_name='复烫' order by position,created_at`)))
console.log('P0基线 复烫:', JSON.stringify(JSON.parse(readFileSync('out/p0-surface.json','utf8')).interference.positionPriceBaseline.filter(r=>r.logical_name==='复烫')))
