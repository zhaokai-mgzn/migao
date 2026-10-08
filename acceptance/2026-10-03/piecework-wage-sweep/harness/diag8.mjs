import { psql } from './lib.mjs'
console.log('存活订单:', JSON.stringify(psql(`select id, order_no, customer_name, coalesce(deleted,0) dl, status from orders where tenant_id=20 and customer_name like '工资验收%'`)))
console.log('存活商品:', JSON.stringify(psql(`select id, name, coalesce(deleted,0) dl, status from products where tenant_id=20 and name like '工资验收%'`)))
console.log('存活分类:', JSON.stringify(psql(`select id, name, coalesce(deleted,0) dl from categories where tenant_id=20 and name like '工资验收%'`)))
console.log('复烫/定型 活跃价目行:', JSON.stringify(psql(`select logical_name,position,unit_price::text,coalesce(deleted,0) dl,created_at::text from production_operation_positions where tenant_id=20 and logical_name in ('复烫','定型') and coalesce(deleted,0)=0 order by logical_name,position`)))
