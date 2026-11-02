import { loginApi, api } from './lib.mjs'
import { PROBE } from './config.mjs'
const a = await loginApi('13800138000')
const STAMP = '20261004010446'
const rnd = () => Math.random().toString(36).slice(2,8)
for (let i=0;i<5;i++) {
  const nm = `${PROBE}-W4-${STAMP}-${rnd()}`
  const r = await api('POST','/api/admin/products',{token:a.token,body:{ name: nm, skuCode: nm, unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:10, colors:[{colorName:'探针色'}], doorWidths:['2.8m'] }})
  console.log(i, nm, r.status, r.text.slice(0,220).replace(/\n/g,' '))
}
