import { psql } from './lib.mjs'
import { readFileSync } from 'node:fs'
const ctx = JSON.parse(readFileSync('out/probe-ctx.json', 'utf8'))
const P = ctx.probes.find((p) => p.tag === 'F')
console.log('F po:', P?.poNo, P?.poId)
console.log(JSON.stringify(psql(`select id,operation_name,unit_price::text as up, qty::text from processing_position_operations where processing_order_id='${P?.poId}' order by seq`), null, 1))
