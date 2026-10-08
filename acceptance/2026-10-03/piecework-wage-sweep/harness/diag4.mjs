import { psql } from './lib.mjs'
console.log('新增价目行 fd9f...:', JSON.stringify(psql(`select id,logical_name,position,unit_price::text,coalesce(deleted,0) dl,created_at::text,updated_at::text from production_operation_positions where id='fd9f56514d599a9429433529dd5156e1'`)))
console.log('打包 全部价目行:', JSON.stringify(psql(`select id,position,unit_price::text,coalesce(deleted,0) dl,created_at::text from production_operation_positions where tenant_id=20 and logical_name='打包' order by created_at`)))
console.log('logo条 工序库行:', JSON.stringify(psql(`select id,name,unit_price::text,updated_at::text from production_operations where tenant_id=20 and name like 'logo%'`)))
console.log('logo条 价目行:', JSON.stringify(psql(`select id,position,unit_price::text,coalesce(deleted,0) dl,updated_at::text from production_operation_positions where tenant_id=20 and logical_name='logo条' order by position`)))
