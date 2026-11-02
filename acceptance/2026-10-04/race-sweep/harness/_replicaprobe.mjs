import { api, loginApi, psql, log } from './lib.mjs'
import { skuIdsByCode } from './lib2.mjs'
const STAMP='20261004010446'; const rnd=()=>Math.random().toString(36).slice(2,8)
const a = await loginApi('13800138000'); const TOK=a.token
const sku = skuIdsByCode(25).find(s=>s.sku_code.includes('A2'))
const rows=[]
for (let i=0;i<10;i++) {
  const bo = { customerName:`race-sweep-rep${i}`, customerPhone:'13900000000', customerAddress:'race-sweep-addr',
    logisticsType:'express', logisticsCompany:'race-sweep-log', remark:`race-sweep-rep${i}-${STAMP}-${rnd()}`,
    items:[{ productId: sku.product_id, productName: sku.sku_code, quantity:'1.0', unitPrice:10.0, subtotal:'10.0',
             processingInfo:{ skuId:String(sku.id), skuCode: sku.sku_code } }] }
  const c = await api('POST','/api/admin/agent/orders',{token:TOK,body:bo}); const oid=c.json.data.id
  await api('PUT',`/api/admin/orders/${oid}/payment`,{token:TOK})
  const r = await api('POST',`/api/admin/production/orders/${oid}/ship`,{token:TOK,headers:{'X-Client-Request-Id':`race-sweep-rep${i}-${rnd()}`},body:{logisticsCompany:'race-sweep-logR',trackingNo:`TR${i}`}})
  const keys = Object.keys(r.json?.data ?? {}).sort().join(',')
  const ship = psql(`select count(*)::int c from order_shipments where tenant_id=25 and order_id='${oid}'`)[0].c
  const key = psql(`select count(*)::int c from client_request_keys where tenant_id=25 and endpoint like '%ship%' and created_at > now() - interval '2 minutes'`)[0].c
  rows.push({ i, status: r.status, keys, shipments: ship })
  console.log(`#${i} status=${r.status} dataKeys=[${keys}] shipmentRows=${ship}`)
}
console.log(JSON.stringify(rows))
