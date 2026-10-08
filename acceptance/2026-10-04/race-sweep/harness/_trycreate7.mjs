import { loginApi, api } from './lib.mjs'
const a = await loginApi('13800138000')
const mk = async (tag, body) => { const r = await api('POST','/api/admin/products',{token:a.token,body}); console.log(tag, r.status, r.text.slice(0,120).replace(/\n/g,' ')); return r }
const base = { unit:'米', pricingType:'per_meter', basePrice:10.0, status:'draft', stock:5, colors:[{colorName:'探针色'}], doorWidths:['2.8m'] }
const stamp='20261004010446'; const rr=()=>Math.random().toString(36).slice(2,8)
// 探针完全同形（name===skuCode，长名）
await mk('P1 同形 name=skuCode=race-sweep-W4-<stamp>-<rnd>i', { name:`race-sweep-W4-${stamp}-${rr()}0`, skuCode:`race-sweep-W4-${stamp}-${rr()}0`, ...base })
await mk('P2 同形但不带 skuCode', { name:`race-sweep-W4-${stamp}-${rr()}1`, ...base })
await mk('P3 skuCode 短', { name:`race-sweep-W4-${stamp}-${rr()}2`, skuCode:`RW4${rr()}`, ...base })
await mk('P4 name 短 + 无 skuCode', { name:`race-sweep-A3-${rr()}`, ...base })
