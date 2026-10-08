// 探针侧登记复核：商品更新端点的「最小合法载荷」到底是什么（解释 422 与 200 的差异）
import { api, loginApi, psql, log } from '../../config-writeface-sweep/harness/lib.mjs'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const tok = (await loginApi('13870217889')).token
const row = psql(`select id::text as id, name, unit, base_price, status, category_id, pricing_type from products where tenant_id=20 and coalesce(deleted,0)=0 limit 1`)[0]
const recs = []
const snap = () => JSON.stringify(psql(`select name, unit, base_price, status, category_id, pricing_type, updated_at from products where id='${row.id}'`))
for (const [label, body] of [
  ['仅 name', { name: row.name }],
  ['name+unit+basePrice+status', { name: row.name, unit: row.unit ?? '米', basePrice: Number(row.base_price ?? 0), status: row.status ?? 'on_sale' }],
  ['+categoryId+pricingType', { name: row.name, unit: row.unit ?? '米', basePrice: Number(row.base_price ?? 0), status: row.status ?? 'on_sale', categoryId: row.category_id ?? undefined, pricingType: row.pricing_type ?? 'fixed' }],
]) {
  const before = snap()
  const r = await api('PUT', `/api/admin/products/${row.id}`, { token: tok, body })
  const after = snap()
  const rec = { label, status: r.status, body: JSON.stringify(r.json).slice(0, 300), dbSame: before === after }
  recs.push(rec)
  log(`[${label}] → ${r.status} ${rec.body} 库未变=${rec.dbSame}`)
}
writeFileSync(OUT + 'probe5-products.json', JSON.stringify({ row, recs }, null, 1))
