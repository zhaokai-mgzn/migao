import { api, loginApi, psql } from './lib.mjs'
import { readFileSync } from 'node:fs'
const ctx = JSON.parse(readFileSync('out/probe-ctx.json', 'utf8'))
const A = ctx.probes.find((p) => p.tag === 'A')
const { token } = await loginApi('13870217889')
const cat = await api('GET', '/api/admin/production/operations-catalog', { token })
const d = cat.json?.data ?? {}
console.log('catalog data keys:', Object.keys(d))
for (const [k, v] of Object.entries(d)) console.log(' ', k, Array.isArray(v) ? `array[${v.length}]` : typeof v)
const arrs = Object.values(d).filter(Array.isArray)
console.log('sample row:', JSON.stringify(arrs[0]?.[0]).slice(0, 400))
const all = arrs.flat()
console.log('含定型 行:', JSON.stringify(all.filter((o) => JSON.stringify(o).includes('定型'))).slice(0, 900))
console.log('db 定型行:', JSON.stringify(psql(`select id,name,unit_price::text,scope,position,status from production_operations where tenant_id=20 and name like '%定型%'`)))
console.log('探针单A 定型实例:', JSON.stringify(psql(`select id,operation_name,unit_price::text,qty::text,done_qty::text from processing_position_operations where processing_order_id='${A.poId}' and operation_name like '%定型%'`)))
console.log('探针单A 价目行(精裁/定型/熨烫):', JSON.stringify(psql(`select logical_name,position,unit_price::text,coalesce(deleted,0) dl,created_at::text from production_operation_positions where tenant_id=20 and logical_name in ('定型','熨烫','精裁') order by logical_name,position,created_at`)))
