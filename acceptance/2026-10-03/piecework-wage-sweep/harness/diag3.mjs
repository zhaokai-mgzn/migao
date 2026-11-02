import { api, loginApi, psql } from './lib.mjs'
const { token } = await loginApi('13870217889')
const cat = await api('GET', '/api/admin/production/operations-catalog', { token })
const all = (cat.json?.data?.groups ?? []).flatMap((g) => g.operations ?? [])
console.log('op 键:', Object.keys(all[0]).join(','))
console.log('定型 行:', JSON.stringify(all.filter((o) => o.name === '定型')))
const lp = await api('GET', '/api/admin/production/operation-layers', { token })
const ld = lp.json?.data ?? {}
console.log('layers keys:', Object.keys(ld))
console.log('定型 layers:', JSON.stringify(JSON.stringify(ld).match(/.{0,0}/) ? (ld.operations ?? []).filter((o) => o.operation === '定型') : null))
