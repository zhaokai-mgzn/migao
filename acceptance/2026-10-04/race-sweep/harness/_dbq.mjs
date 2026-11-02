import { psql, log, OUT } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
const idx = psql("select indexname, indexdef from pg_indexes where tablename='stock_batch_consumptions' and indexdef ilike '%unique%'")
const cons = psql("select count(*)::int c from stock_batch_consumptions where tenant_id=25")
console.log('unique idx:', JSON.stringify(idx, null, 1))
console.log('consumptions25:', JSON.stringify(cons))
writeFileSync(join(OUT, 'db-index-readback.json'), JSON.stringify({ at: new Date().toISOString(), stockBatchConsumptionsUniqueIndexes: idx, consumptions25: cons }, null, 2))
