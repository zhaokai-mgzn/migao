// 线③ 夹具引导：登录租户A(25) → 入驻流程建临时租户B(§4.3) → 两租户各建探针商品/SKU → 落 fixtures.json
// 只产探针对象（前缀 race-sweep）；不改产品代码。
import { api, loginApi, psql, log, OUT, sleep } from './lib.mjs'
import { T_A, PHONE_A, T_B_NAME, PHONE_B, REGISTER_INDUSTRY, SMS_CODE, PROBE } from './config.mjs'
import { writeFileSync, existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const FIXPATH = join(OUT, 'fixtures.json')
const stamp = process.env.RUN_STAMP || new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')
const FIX = existsSync(FIXPATH) ? JSON.parse(readFileSync(FIXPATH, 'utf8')) : {}
const R = { stamp, tenantA: T_A, phoneA: PHONE_A, tenantB: null, phoneB: PHONE_B, products: {}, inbound: [], orders: [], notes: [] }

// ── 1. 租户 A 登录 ──
const a = await loginApi(PHONE_A, SMS_CODE)
log(`A 登录：tenantId=${a.user.tenantId} role=${a.user.role} user.id=${a.user.id}`)
R.tokenA = a.token; R.userA = a.user.id
if (a.user.tenantId !== T_A) throw new Error(`A 登录租户不符：期望 ${T_A}，实得 ${a.user.tenantId}`)

// ── 2. 临时对照租户 B：产品入驻流程（BRIEF §4.3） ──
async function ensureTenantB() {
  const existing = psql(`select id, name from tenants where name = '${T_B_NAME}'`)
  if (existing.length) { log(`租户 B 已存在：id=${existing[0].id}`); return Number(existing[0].id) }
  const sms = await api('POST', '/api/auth/sms/send', { body: { phone: PHONE_B } })
  log(`B 短信验证码下发：status=${sms.status} body=${sms.text.slice(0, 160)}`)
  const reg = await api('POST', '/api/auth/register', { body: {
    companyName: T_B_NAME, contactName: '隔离对照管理员', phone: PHONE_B, smsCode: SMS_CODE,
    industry: REGISTER_INDUSTRY, address: '隔离对照（探针租户，收尾即清）',
    description: '并发竞态跨租户串号对照租户（probe: race-sweep）',
  } })
  log(`B 入驻提交：status=${reg.status} body=${reg.text.slice(0, 300)}`)
  R.register = { status: reg.status, body: reg.json }
  for (let i = 0; i < 20; i++) {
    const t = psql(`select id, name from tenants where name = '${T_B_NAME}'`)
    if (t.length) { log(`租户 B 已开通：id=${t[0].id}`); return Number(t[0].id) }
    await sleep(1500)
  }
  throw new Error('租户 B 未在 30s 内开通，register 读数见 out/fixtures.json')
}
R.tenantB = await ensureTenantB()
const b = await loginApi(PHONE_B, SMS_CODE)
log(`B 登录：tenantId=${b.user.tenantId} role=${b.user.role} user.id=${b.user.id}`)
if (b.user.tenantId !== R.tenantB) throw new Error(`B 登录租户不符：期望 ${R.tenantB}，实得 ${b.user.tenantId}`)
R.tokenB = b.token; R.userB = b.user.id

// ── 3. 探针商品（每租户：2 个，各 1 SKU）──
async function mkProduct(token, tenant, tag, stock) {
  const name = `${PROBE}-${tag}-${stamp}`
  const r = await api('POST', '/api/admin/products', { token, body: {
    name, skuCode: `${PROBE}-${tag}-${stamp}`, unit: '米', pricingType: 'per_meter',
    basePrice: 10.0, status: 'draft', stock,
    colors: [{ colorName: '探针色' }], doorWidths: ['2.8m'],
  } })
  if (r.status !== 200) throw new Error(`建品失败 ${tenant}/${tag}: ${r.status} ${r.text.slice(0, 300)}`)
  const p = r.json.data
  const det = await api('GET', `/api/admin/products/${p.id}`, { token })
  const skus = det.json?.data?.skus ?? []
  if (!skus.length) throw new Error(`建品后无 SKU ${tenant}/${tag}: ${det.text.slice(0, 300)}`)
  const sku = skus[0]
  log(`${tenant}/${tag} 商品 id=${p.id} sku.id=${sku.id} sku.stock=${sku.stock} skuCode=${sku.skuCode}`)
  return { id: p.id, name, skuId: sku.id, skuCode: sku.skuCode, stockAtCreate: sku.stock }
}

R.products.a1 = await mkProduct(a.token, T_A, 'A1', 10)
R.products.a2 = await mkProduct(a.token, T_A, 'A2', 10)
R.products.b1 = await mkProduct(b.token, R.tenantB, 'B1', 10)

// 库侧复核
R.db = {
  productsA: psql(`select id, name from products where tenant_id=${T_A} and name like '${PROBE}-%'`),
  skusA: psql(`select id, product_id, sku_code, stock from product_skus where tenant_id=${T_A} and sku_code like '${PROBE}-%'`),
  productsB: psql(`select id, name from products where tenant_id=${R.tenantB} and name like '${PROBE}-%'`),
  skusB: psql(`select id, product_id, sku_code, stock from product_skus where tenant_id=${R.tenantB} and sku_code like '${PROBE}-%'`),
}

writeFileSync(FIXPATH, JSON.stringify(R, null, 2))
log(`夹具已落盘 ${FIXPATH}（tenantB=${R.tenantB}，探针商品 ${Object.keys(R.products).length} 个）`)
console.log(JSON.stringify({ ok: true, tenantB: R.tenantB, products: R.products }, null, 2))
