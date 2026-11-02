import { api, loginApi, psql, one } from './lib.mjs'
import { readFileSync } from 'node:fs'
const ctx = JSON.parse(readFileSync('out/probe-ctx.json', 'utf8'))
const A = ctx.probes.find((p) => p.tag === 'A')
const B = ctx.probes.find((p) => p.tag === 'B')
const { token } = await loginApi('13870217889')
// ① 幂等键重放：逐字读数
const rowsA = psql(`select id, operation_name, qty::text, done_qty::text from processing_position_operations
  where processing_order_id='${A.poId}' and coalesce(deleted,0)=0 order by seq`)
const op = rowsA.find((r) => r.operation_name === '布三边')
for (const key of ['diag-idem-1', 'diag-idem-1', 'diag-idem-2']) {
  const r = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${op.id}/report`,
    { token, body: { worker_name: '工资验收工人甲674096', qty: 1, qualified_qty: 1, work_type: 'normal' }, headers: { 'X-Client-Request-Id': key } })
  console.log(`key=${key} → HTTP ${r.status} :`, r.text.slice(0, 260))
}
console.log('qty=1 行数:', one(`select count(*)::int n from production_work_logs where processing_order_id='${A.poId}' and qualified_qty=1`).n)

// ② 超报：把 布三边 剩余压到 2 再报 5
const cur = one(`select qty::text, done_qty::text from processing_position_operations where id='${op.id}'`)
await import('./lib.mjs').then(({ guardedWrite }) => guardedWrite(`-- probe-ok
update processing_position_operations set done_qty=10 where id='${op.id}'`))
for (const q of [2, 5]) {
  const r = await api('POST', `/api/admin/production/orders/${A.orderId}/operations/${op.id}/report`,
    { token, body: { worker_name: '工资验收工人甲674096', qty: q, qualified_qty: q, work_type: 'normal' }, headers: { 'X-Client-Request-Id': `diag-over-${q}` } })
  console.log(`超报 q=${q} → HTTP ${r.status} :`, r.text.slice(0, 200))
  if (q === 5) break
}

// ③ 工序库读面：定型 的关键字段
const cat = await api('GET', '/api/admin/production/operations-catalog', { token })
const arr = cat.json?.data?.operations ?? cat.json?.data ?? []
console.log('catalog type:', Array.isArray(arr) ? `array[${arr.length}]` : typeof arr)
console.log('catalog 命中 name=定型:', JSON.stringify(arr.filter((o) => String(o.name).includes('定型'))))
console.log('catalog 命中 name=精裁:', JSON.stringify(arr.filter((o) => String(o.name).includes('精裁'))))
console.log('db 定型行:', JSON.stringify(psql(`select id,name,unit_price::text,scope,position,status from production_operations where tenant_id=20 and name like '%定型%'`)))
