import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (tag, body) => { const r = await api('POST','/api/admin/products',{token:a.token,body}); console.log(tag, r.status, r.text.slice(0,200).replace(/\n/g,' ')); return r }
const base = { unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:10, colors:[{colorName:'探针色'}], doorWidths:['2.8m'] }
await mk('A `race-sweep-W4-<stamp>-<rnd>`', { name:`race-sweep-W4-20261004010446-${Math.random().toString(36).slice(2,8)}`, ...base })
await mk('B `RACE-SWEEP-W4-<stamp>-<rnd>`', { name:`RACE-SWEEP-W4-20261004010446-${Math.random().toString(36).slice(2,8)}`, ...base })
await mk('C `race-sweep-W3-<stamp>-<rnd>`', { name:`race-sweep-W3-20261004010446-${Math.random().toString(36).slice(2,8)}`, ...base })
await mk('D `race-sweep-W4-abc`', { name:`race-sweep-W4-abc`, ...base })
