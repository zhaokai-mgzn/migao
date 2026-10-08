import { psql, OUT } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
const out = { at: new Date().toISOString(), at_local: 'see host date', tenants: psql('select id, name, code, status, created_at from tenants order by id') }
writeFileSync(join(OUT, 'tenants-now.json'), JSON.stringify(out, null, 2))
console.log(JSON.stringify(out, null, 2))
