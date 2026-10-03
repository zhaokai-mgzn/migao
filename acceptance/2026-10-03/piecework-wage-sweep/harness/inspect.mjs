// 只读诊断：把探针对象的库内逐行读数打出来（人工核对用，非判据）
import { psql } from './lib.mjs'
import { readFileSync } from 'node:fs'
const ctx = JSON.parse(readFileSync('out/probe-ctx.json', 'utf8'))
const poIds = ctx.probes.map((p) => p.poId)
const inList = poIds.map((x) => `'${x}'`).join(',')
console.log('probes:', JSON.stringify(ctx.probes.map((p) => ({ tag: p.tag, po: p.poNo, poId: p.poId, order: p.orderId }))))
console.log('== work logs ==')
console.table(psql(`select operation_name,worker_name,qualified_qty::text,qty::text,unit_price::text,price_state,work_type,work_date::text from production_work_logs where processing_order_id in (${inList}) order by created_at`))
console.log('== instances ==')
console.table(psql(`select operation_name,qty::text,done_qty::text,unit_price::text,status from processing_position_operations where processing_order_id in (${inList}) order by processing_order_id,seq`))
