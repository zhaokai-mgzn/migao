import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (tag, skuCode) => { const r = await api('POST','/api/admin/products',{token:a.token,body:{ name:'race-sweep-L-'+Math.random().toString(36).slice(2,8), skuCode, unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:5, colors:[{colorName:'探针色'}], doorWidths:['2.8m'] }}); console.log(`${tag} len=${skuCode.length} ->`, r.status); return r }
await mk('L38','R'.repeat(38))
await mk('L40','R'.repeat(40))
await mk('L44','R'.repeat(44))
await mk('L46','R'.repeat(46))
await mk('L47','R'.repeat(47))
await mk('L48','R'.repeat(48))
await mk('L49','R'.repeat(49))
