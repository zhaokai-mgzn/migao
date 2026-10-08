import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (tag, body) => { const r = await api('POST','/api/admin/products',{token:a.token,body}); console.log(tag, r.status, r.text.slice(0,180).replace(/\n/g,' ')); return r }
const base = { unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:10, colors:[{colorName:'探针色'}], doorWidths:['2.8m'] }
let n = Math.random().toString(36).slice(2,7)
await mk('1 带skuCode', { name:`race-sweep-Q1-${n}`, skuCode:`race-sweep-Q1-${n}`, ...base })
await mk('2 不带skuCode', { name:`race-sweep-Q2-${n}`, ...base })
await mk('3 最短名', { name:`Q${n}`, ...base })
