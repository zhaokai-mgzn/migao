// 构建点判别：/ship 的响应形状 = 构建点的**内容级**读数
//   新面（含 #6157/#6181）：data ⊇ {shipment_no, shipment_source} 且 order_shipments 落行
//   旧面：data = {order_id, status, tracking_no, logistics_company} 且**零**发货单/零占位行
import { api, loginApi, psql } from './lib.mjs'
import { skuIdsByCode, fanOut } from './lib2.mjs'
import { writeFileSync } from 'node:fs'
const rnd=()=>Math.random().toString(36).slice(2,8)
const a = await loginApi('13800138000'); const TOK=a.token
const sku = skuIdsByCode(25).find(s=>s.sku_code.includes('A2'))
const out=[]
for (let i=0;i<12;i++) {
  const bo = { customerName:`race-sweep-shape${i}`, customerPhone:'13900000000', customerAddress:'race-sweep-addr',
    logisticsType:'express', logisticsCompany:'race-sweep-log', remark:`race-sweep-shape${i}-${rnd()}`,
    items:[{ productId: sku.product_id, productName: sku.sku_code, quantity:'1.0', unitPrice:10.0, subtotal:'10.0',
             processingInfo:{ skuId:String(sku.id), skuCode: sku.sku_code } }] }
  const c = await api('POST','/api/admin/agent/orders',{token:TOK,body:bo}); const oid=c.json.data.id
  await api('PUT',`/api/admin/orders/${oid}/payment`,{token:TOK})
  const r = await api('POST',`/api/admin/production/orders/${oid}/ship`,{token:TOK,headers:{'X-Client-Request-Id':`race-sweep-shape${i}-${rnd()}`},body:{logisticsCompany:'race-sweep-logR',trackingNo:`TS${i}`}})
  const d = r.json?.data ?? {}
  const shipRows = psql(`select count(*)::int c from order_shipments where tenant_id=25 and order_id='${oid}'`)[0].c
  const face = ('shipment_no' in d) ? 'new(#6157/#6181)' : 'legacy(无 shipment_no)'
  out.push({ i, status: r.status, dataKeys: Object.keys(d).sort(), shipmentRows: shipRows, face })
  console.log(`#${i} ${r.status} [${face}] keys=${Object.keys(d).sort().join(',')} shipmentRows=${shipRows}`)
}
writeFileSync('acceptance/2026-10-04/race-sweep/out/buildpoint-shape-sample.json', JSON.stringify({ at: new Date().toISOString(), samples: out, faces: Object.fromEntries([...new Set(out.map(o=>o.face))].map(f=>[f, out.filter(o=>o.face===f).length])) }, null, 2))
console.log('faces:', JSON.stringify(Object.fromEntries([...new Set(out.map(o=>o.face))].map(f=>[f, out.filter(o=>o.face===f).length]))))
