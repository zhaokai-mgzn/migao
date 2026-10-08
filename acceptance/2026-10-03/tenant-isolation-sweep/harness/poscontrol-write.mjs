// 假绿自查③：同租户**写端点**正对照（值=现值的幂等 PUT）⇒ 证明「不是所有写都被 403」
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, psql, log } from '../../config-writeface-sweep/harness/lib.mjs'
const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const recs = []; const rec = (id, name, verdict, detail, evidence) => { recs.push({ id, name, verdict, detail, evidence }); log(`${verdict === 'pass' ? '✅' : '❌'} [${id}] ${name} — ${detail}`) }
const tok = (await loginApi('13870217889')).token
const hasDel = (t) => psql(`select 1 x from information_schema.columns where table_schema='public' and table_name='${t}' and column_name='deleted'`).length > 0
const CASES = [
  ['products', 'products', (id) => `/api/admin/products/${id}`, (r) => ({ name: r.name, unit: r.unit ?? '米', basePrice: Number(r.base_price ?? 0), status: r.status ?? 'on_sale' }), ['name', 'base_price', 'status', 'updated_at']],
  ['categories', 'categories', (id) => `/api/admin/categories/${id}`, (r) => ({ name: r.name }), ['name', 'sort_order', 'updated_at']],
  ['processing_items', 'processing_items', (id) => `/api/admin/processing-items/${id}`, (r) => ({ name: r.name, categoryId: r.category_id, unit: '米' }), ['name', 'status', 'updated_at']],
  ['customers', 'customer_profiles', (id) => `/api/admin/customers/${id}`, () => ({}), ['phone', 'vip_level', 'updated_at']],
]
for (const [key, table, path, build, cols] of CASES) {
  const row = psql(`select * from ${table} where tenant_id=20${hasDel(table) ? ' and coalesce(deleted,0)=0' : ''} limit 1`)[0]
  if (!row) { rec('PCW-' + key, '同租户写正对照·' + table, 'skip', '租户20 无存活行'); continue }
  const snap = () => JSON.stringify(psql(`select ${cols.join(',')} from ${table} where id='${row.id}'`))
  const before = snap()
  const r = await api('PUT', path(row.id), { token: tok, body: build(row) })
  const after = snap()
  rec('PCW-' + key, '同租户写正对照·' + table, r.status === 200 && before === after ? 'pass' : 'fail',
    `A(20) 幂等 PUT 自己的对象 → ${r.status}；库未变=${before === after}`,
    [`PUT ${path(row.id)} body=${JSON.stringify(build(row)).slice(0, 180)} → ${r.status} ${JSON.stringify(r.json).slice(0, 200)}`,
     `before=${before.slice(0, 200)}`, `after=${after.slice(0, 200)}`])
}
writeFileSync(OUT + 'poscontrol-write.json', JSON.stringify(recs, null, 1))
