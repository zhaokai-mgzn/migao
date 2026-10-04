import { psql } from './lib.mjs'
const tabs=['stock_batches','inbound_orders','orders','finance_transactions','processing_orders','inbound_labels','stock_ledger_entries','stock_batch_consumptions','order_shipments']
for (const t of tabs) {
  try { console.log(t, psql(`select string_agg(column_name, ',' order by ordinal_position) c from information_schema.columns where table_name='${t}'`)[0].c.slice(0,220)) }
  catch(e){ console.log(t, 'ERR', String(e.message).slice(0,80)) }
}
console.log('tenants NOW:', JSON.stringify(psql('select id, name from tenants order by id')))
