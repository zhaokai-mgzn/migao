import { api, loginApi, psql } from './lib.mjs'
import { skuIdsByCode } from './lib2.mjs'
const STAMP='20261004010446'; const rnd=()=>Math.random().toString(36).slice(2,8)
const a = await loginApi('13800138000'); const TOK=a.token
const sku = skuIdsByCode(25).find(s=>s.sku_code.includes('A2'))
for (let i=0;i<2;i++) {
  const bo = { customerName:`race-sweep-fresh${i}`, customerPhone:'13900000000', customerAddress:'race-sweep-addr',
    logisticsType:'express', logisticsCompany:'race-sweep-log', remark:`race-sweep-fresh${i}-${STAMP}-${rnd()}`,
    items:[{ productId: sku.product_id, productName: sku.sku_code, quantity:'1.0', unitPrice:10.0, subtotal:'10.0',
             processingInfo:{ skuId:String(sku.id), skuCode: sku.sku_code } }] }
  const c = await api('POST','/api/admin/agent/orders',{token:TOK,body:bo}); const oid=c.json.data.id
  await api('PUT',`/api/admin/orders/${oid}/payment`,{token:TOK})
  const key = `race-sweep-fresh${i}-${STAMP}-${rnd()}`
  const r = await api('POST',`/api/admin/production/orders/${oid}/ship`,{token:TOK,headers:{'X-Client-Request-Id':key},body:{logisticsCompany:'race-sweep-logF',trackingNo:`race-sweep-TNF${i}`}})
  console.log(`#${i} ship ->`, r.status, r.text.slice(0,260))
  console.log(`   db shipment:`, JSON.stringify(psql(`select shipment_no, source from order_shipments where tenant_id=25 and order_id='${oid}'`)))
  console.log(`   db key:`, JSON.stringify(psql(`select client_request_id from client_request_keys where tenant_id=25 and client_request_id='${key}'`)))
}
