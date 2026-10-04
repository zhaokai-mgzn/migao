import { psql, OUT } from './lib.mjs'
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
const M='race-sweep', T=25
const out = {
  at: new Date().toISOString(),
  tenants: psql('select id, name, code, status from tenants order by id'),
  tenant25_probe_residue: {
    products: psql(`select count(*)::int c from products where tenant_id=${T} and name like '${M}%'`)[0].c,
    product_skus: psql(`select count(*)::int c from product_skus where tenant_id=${T} and sku_code ilike '%RACE%'`)[0].c,
    orders: psql(`select count(*)::int c from orders where tenant_id=${T} and (remark like '${M}%' or customer_name like '${M}%')`)[0].c,
    inbound_orders: psql(`select count(*)::int c from inbound_orders where tenant_id=${T} and (supplier like '${M}%' or remark like '${M}%')`)[0].c,
    stock_ledger_entries: psql(`select count(*)::int c from stock_ledger_entries where tenant_id=${T} and note like '%${M}%'`)[0].c,
    stock_batch_consumptions: psql(`select count(*)::int c from stock_batch_consumptions where tenant_id=${T} and stocktake_run_id like '${M}%'`)[0].c,
    client_request_keys: psql(`select count(*)::int c from client_request_keys where tenant_id=${T} and client_request_id like '${M}%'`)[0].c,
    tenant_applications_probe_phone: psql(`select count(*)::int c from tenant_applications where phone='13800138001'`)[0].c,
  },
  tenant26_exists: psql('select count(*)::int c from tenants where id=26')[0].c,
}
writeFileSync(join(OUT,'residue-final.json'), JSON.stringify(out,null,2))
console.log(JSON.stringify(out,null,2))
