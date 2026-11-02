import { psql, api, loginApi } from './lib.mjs'
console.log('打包 全列:', JSON.stringify(psql(`select id,position,unit_price::text p,applicable,status,coalesce(deleted,0) dl,created_at::text from production_operation_positions where tenant_id=20 and logical_name='打包' order by created_at`), null, 1))
const { token } = await loginApi('13870217889')
const lp = await api('GET', '/api/admin/production/operation-layers', { token })
console.log('读面 打包:', JSON.stringify((lp.json?.data?.operations ?? []).filter((o) => o.operation === '打包')))
const cat = await api('GET', '/api/admin/production/operations-catalog', { token })
console.log('catalog 打包:', JSON.stringify((cat.json?.data?.groups ?? []).flatMap((g) => g.operations ?? []).filter((o) => o.name === '打包')))
