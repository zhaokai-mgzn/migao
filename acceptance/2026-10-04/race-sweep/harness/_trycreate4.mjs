import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (tag, name) => { const r = await api('POST','/api/admin/products',{token:a.token,body:{ name, unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:10, colors:[{colorName:'探针色'}], doorWidths:['2.8m'] }}); console.log(tag, r.status, `len=${String(name).length}`, String(name).slice(0,60)); return r }
await mk('A 串', 'race-sweep-W4-20261004010446-abc12')
await mk('B 无前缀同长', 'xace-sweep-W4-20261004010446-abc123')
await mk('C 前缀换成短', 'race-sw-W4-20261004010446-abc123')
await mk('D 纯串重复', 'race-sweep-W4-20261004010446-abc123')
