import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (tag, body) => { const r = await api('POST','/api/admin/products',{token:a.token,body}); console.log(tag, r.status, r.text.slice(0,300)); return r }
const nm = 'race-sweep-probe-xyz-' + Math.random().toString(36).slice(2,7)
await mk('A(with skuCode)', { name: nm, skuCode: nm, unit: '米', pricingType: 'per_meter', basePrice: 10.0, status: 'draft', stock: 10, colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'] })
const nm2 = 'race-sweep-probe2-' + Math.random().toString(36).slice(2,7)
await mk('B(no skuCode)', { name: nm2, unit: '米', pricingType: 'per_meter', basePrice: 10.0, status: 'draft', stock: 10, colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'] })
const nm3 = 'race-sweep-probe3-' + Math.random().toString(36).slice(2,7)
await mk('C(stock 0)', { name: nm3, skuCode: nm3, unit: '米', pricingType: 'per_meter', basePrice: 10.0, status: 'draft', stock: 0, colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'] })
