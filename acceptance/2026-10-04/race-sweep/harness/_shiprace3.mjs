import { api, loginApi, psql } from './lib.mjs'
const a = await loginApi('13800138000'); const TOK=a.token
const r = await api('POST','/api/admin/production/orders/0000000000000000000000000000dead/ship',{token:TOK,headers:{'X-Client-Request-Id':'<IDEM-KEY-f74391>'},body:{logisticsCompany:'x',trackingNo:'y'}})
console.log('nonexistent order ->', r.status, r.text.slice(0,300))
const r2 = await api('POST','/api/admin/production/orders/0000000000000000000000000000dead/ship',{token:TOK,body:{logisticsCompany:'x',trackingNo:'y'}})
console.log('no-key variant ->', r2.status, r2.text.slice(0,300))
