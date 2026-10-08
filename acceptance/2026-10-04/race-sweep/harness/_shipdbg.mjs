import { api, loginApi, psql, log } from './lib.mjs'
import { skuIdsByCode } from './lib2.mjs'
const STAMP='20261004010446'; const rnd=()=>Math.random().toString(36).slice(2,8)
const a = await loginApi('13800138000'); const TOK=a.token
const sku = skuIdsByCode(25).find(s=>s.sku_code.includes('A2'))
const key = `race-sweep-dbg-${STAMP}-${rnd()}`
const bo = { customerName:'race-sweep-dbg', customerPhone:'13900000000', customerAddress:'race-sweep-addr',
  logisticsType:'express', logisticsCompany:'race-sweep-log', remark:`race-sweep-dbg-${STAMP}-${rnd()}`,
  items:[{ productId: sku.product_id, productName: sku.sku_code, quantity:'1.0', unitPrice:10.0, subtotal:'10.0',
           processingInfo:{ skuId:String(sku.id), skuCode: sku.sku_code } }] }
const c = await api('POST','/api/admin/agent/orders',{token:TOK,body:bo})
const oid = c.json.data.id
console.log('created', oid, c.json.data.orderNo)
const pay = await api('PUT',`/api/admin/orders/${oid}/payment`,{token:TOK})
console.log('pay', pay.status, psql(`select status from orders where tenant_id=25 and id='${oid}'`)[0]?.status)
// ① 顺序发货（单发，无并发）
const r1 = await api('POST',`/api/admin/production/orders/${oid}/ship`,{token:TOK,headers:{'X-Client-Request-Id':key},body:{logisticsCompany:'race-sweep-logA',trackingNo:'race-sweep-TN-A'}})
console.log('ship seq #1', r1.status, r1.text.slice(0,300))
console.log('  db order:', JSON.stringify(psql(`select status, logistics_type, logistics_company from orders where tenant_id=25 and id='${oid}'`)))
console.log('  db shipment:', JSON.stringify(psql(`select shipment_no, source, tracking_no, client_request_id from order_shipments where tenant_id=25 and order_id='${oid}'`)))
console.log('  db key:', JSON.stringify(psql(`select client_request_id, endpoint, response_payload is not null as has_payload from client_request_keys where tenant_id=25 and client_request_id='${key}'`)))
// ② 同键再发一次（顺序）
const r2 = await api('POST',`/api/admin/production/orders/${oid}/ship`,{token:TOK,headers:{'X-Client-Request-Id':key},body:{logisticsCompany:'race-sweep-logB',trackingNo:'race-sweep-TN-B'}})
console.log('ship seq #2', r2.status, r2.text.slice(0,300))
console.log('  db order:', JSON.stringify(psql(`select status, logistics_type, logistics_company from orders where tenant_id=25 and id='${oid}'`)))
console.log('  db shipment:', JSON.stringify(psql(`select shipment_no, source, tracking_no, client_request_id from order_shipments where tenant_id=25 and order_id='${oid}'`)))
