import { psql } from './lib.mjs'
import { execSql } from './lib2.mjs'
const M='race-sweep', T=25
const mine = `select id from products where tenant_id=${T} and name like '${M}%'`
const fks = psql(`select tc.constraint_name, tc.table_name as child, kcu.column_name as child_col, ccu.table_name as parent, ccu.column_name as parent_col
  from information_schema.table_constraints tc
  join information_schema.key_column_usage kcu on kcu.constraint_name=tc.constraint_name and kcu.table_schema=tc.table_schema
  join information_schema.constraint_column_usage ccu on ccu.constraint_name=tc.constraint_name and ccu.table_schema=tc.table_schema
  where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public' and ccu.table_name='products'`)
for (const f of fks) {
  try { const n = psql(`select count(*)::int c from ${f.child} where ${f.child_col} in (${mine})`)[0].c
    if (n) console.log('child', f.child, f.child_col, f.constraint_name, 'rows', n) } catch(e) { console.log('err', f.child, String(e.message).slice(0,80)) }
}
console.log('--- attempt deletes ---')
for (const sql of [`delete from product_skus where product_id in (${mine})`, `delete from products where tenant_id=${T} and name like '${M}%'`]) {
  console.log(sql.slice(0,60), JSON.stringify(execSql(sql)))
}
console.log('products left:', psql(`select count(*)::int c from products where tenant_id=${T} and name like '${M}%'`)[0].c)
