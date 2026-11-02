// 假绿自查③：同租户**写端点**正对照（值=现值的幂等 PUT）⇒ 证明「不是所有写都被 403」
// 主体 A 由 env 注入（issue #6937）
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, psql, psqlWrite, log } from '../../config-writeface-sweep/harness/lib.mjs'
import { T, PH, SMS_CODE } from '../../lib/subjects.mjs'
const OUT = process.env.OUT_DIR ? process.env.OUT_DIR.replace(/\/?$/, '/') : fileURLToPath(new URL('../out/', import.meta.url))
const recs = []; const rec = (id, name, verdict, detail, evidence) => { recs.push({ id, name, verdict, detail, evidence }); log(`${verdict === 'pass' ? '✅' : verdict === 'fail' ? '❌' : '⏭️'} [${id}] ${name} — ${detail}`) }
const tok = (await loginApi(PH.A, SMS_CODE)).token
const hasDel = (t) => psql(`select 1 x from information_schema.columns where table_schema='public' and table_name='${t}' and column_name='deleted'`).length > 0
const CASES = [
  ['products', 'products', (id) => `/api/admin/products/${id}`, (r) => ({ name: r.name, unit: r.unit ?? '米', basePrice: Number(r.base_price ?? 0), status: r.status ?? 'on_sale', categoryId: r.category_id ?? undefined, pricingType: r.pricing_type ?? 'fixed' }), ['name', 'base_price', 'status', 'updated_at']],
  ['categories', 'categories', (id) => `/api/admin/categories/${id}`, (r) => ({ name: r.name }), ['name', 'sort_order', 'updated_at']],
  ['processing_items', 'processing_items', (id) => `/api/admin/processing-items/${id}`, (r) => ({ name: r.name, categoryId: r.category_id, unit: '米' }), ['name', 'status', 'updated_at']],
  ['customers', 'customer_profiles', (id) => `/api/admin/customers/${id}`, () => ({}), ['phone', 'vip_level', 'updated_at']],
]
for (const [key, table, path, build, cols] of CASES) {
  const row = psql(`select * from ${table} where tenant_id=${T.A}${hasDel(table) ? ' and coalesce(deleted,0)=0' : ''} limit 1`)[0]
  if (!row) { rec('PCW-' + key, '同租户写正对照·' + table, 'skip', `租户 ${T.A}（A）无存活行`); continue }
  // 整行快照（不是只挑几列）：少列 = 看不见「空 body 改写了别的列」
  const full = () => psql(`select * from ${table} where id='${row.id}'`)[0]
  const before = JSON.stringify(full())
  const r = await api('PUT', path(row.id), { token: tok, body: build(row) })
  let after = JSON.stringify(full())
  let restored = null
  if (before !== after) {
    // ⚠️ 实测（#6937）：`{}`/部分载荷不是幂等 ⇒ 探针写脏了自己的行 ⇒ **逐字段还原**（jsonb_populate_record：类型安全）
    const b = JSON.parse(before)
    const cols = Object.keys(b).filter((c) => c !== 'id')
    const json = before.replace(/'/g, "''")
    psqlWrite(`update ${table} t set (${cols.join(', ')}) = `
      + `(select ${cols.join(', ')} from jsonb_populate_record(null::${table}, '${json}'::jsonb)) where t.id='${row.id}'`)
    restored = JSON.stringify(full()) === before
    after = JSON.stringify(full())
  }
  const net = before === after
  rec('PCW-' + key, '同租户写正对照·' + table, r.status === 200 && net ? 'pass' : 'fail',
    `A(${T.A}) 幂等 PUT 自己的对象 → ${r.status}；净残留=0=${net}${restored === null ? '（探针未改库）' : `（⚠️载荷非幂等 ⇒ 已逐字段还原：${restored ? '回到基线' : '🔴 还原失败'}）`}`,
    [`PUT ${path(row.id)} body=${JSON.stringify(build(row)).slice(0, 180)} → ${r.status} ${JSON.stringify(r.json).slice(0, 200)}`,
     `before(整行)=${before.slice(0, 240)}`, `after(整行)=${after.slice(0, 240)}`])
}
writeFileSync(OUT + 'poscontrol-write.json', JSON.stringify(recs, null, 1))
