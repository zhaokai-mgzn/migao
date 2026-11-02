import { api, loginApi, psql, log } from './lib.mjs'
import { skuIdsByCode, fanOut, timedApi } from './lib2.mjs'
import { one } from './lib.mjs'
const STAMP='20261004010446'; const rnd=()=>Math.random().toString(36).slice(2,8)
const a = await loginApi('13800138000'); const TOK=a.token
const sku = skuIdsByCode(25).find(s=>s.sku_code.includes('A2'))
const bo = { customerName:'race-sweep-shiprace', customerPhone:'13900000000', customerAddress:'race-sweep-addr',
  logisticsType:'express', logisticsCompany:'race-sweep-log', remark:`race-sweep-shiprace-${STAMP}-${rnd()}`,
  items:[{ productId: sku.product_id, productName: sku.sku_code, quantity:'1.0', unitPrice:10.0, subtotal:'10.0',
           processingInfo:{ skuId:String(sku.id), skuCode: sku.sku_code } }] }
const c = await api('POST','/api/admin/agent/orders',{token:TOK,body:bo}); const oid = c.json.data.id
await api('PUT',`/api/admin/orders/${oid}/payment`,{token:TOK})
const key = `race-sweep-shiprace-${STAMP}-${rnd()}`
const t = Date.now()
const res = await fanOut(4, () => timedApi('POST',`/api/admin/production/orders/${oid}/ship`,{token:TOK,headers:{'X-Client-Request-Id':key},body:{logisticsCompany:'race-sweep-logR',trackingNo:`race-sweep-TN-${rnd()}`}}, t), t)
console.log('statuses', res.map(r=>r.status))
res.forEach((r,i)=>console.log(' body',i,r.text.slice(0,220)))
console.log('db shipment:', JSON.stringify(psql(`select shipment_no, source, tracking_no, client_request_id from order_shipments where tenant_id=25 and order_id='${oid}'`)))
console.log('db key:', JSON.stringify(psql(`select client_request_id, endpoint, response_payload is not null as has_payload from client_request_keys where tenant_id=25 and client_request_id='${key}'`)))
console.log('db order:', JSON.stringify(psql(`select status from orders where tenant_id=25 and id='${oid}'`)))
