import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (n) => { const sku='R'.repeat(n); const r = await api('POST','/api/admin/products',{token:a.token,body:{ name:'race-sweep-M-'+Math.random().toString(36).slice(2,8), skuCode:sku, unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:5, colors:[{colorName:'探针色'}], doorWidths:['2.8m'] }}); console.log(`len=${n} ->`, r.status, r.status===500?'':''); return r }
for (const n of [8,12,16,20,24,26,28,29,30,31,32,34,36]) await mk(n)
