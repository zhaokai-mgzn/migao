import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (tag, name, extra={}) => { const r = await api('POST','/api/admin/products',{token:a.token,body:{ name, skuCode:name, unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:10, colors:[{colorName:'探针色'}], doorWidths:['2.8m'], ...extra }}); console.log(tag, r.status, String(name).slice(0,60), r.text.slice(0,150).replace(/\n/g,' ')); return r }
const s='20261004010446-abc123'
await mk('1 全同(仅名不同)', `race-sweep-W4-${s}`)
await mk('2 name无前缀', `W4-${s}`)
await mk('3 name无数字', 'race-sweep-W4-abcdef')
await mk('4 name 短', `race-sweep-A1-${s}`)
await mk('5 name 与首次同形态(探针色)', `race-sweep-Z9-${s}`)
