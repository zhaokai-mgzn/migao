// 对照租户 B 的**可选**自造 / 播种 / 自清（issue #6937 §3）
//
// 走**真实入驻流程**（不是直插 DB），副作用务必读清：
//   ① 新建 tenants 行 + 该租户 admin users 行 + 入驻默认种子（角色/权限/岗位）；
//   ② 留一行 tenant_applications（phone=BOOTSTRAP_PHONE）——**不清它会挡同名再入驻**（实测 422
//      「该企业已有入驻申请，请勿重复提交」）；
//   ③ `seed` 会用 B 的 token 建 1 分类 / 1 商品 / 1 订单，作为隔离面负例的「B 侧有真行」前置。
// 自清：`node bootstrap-tenant-b.mjs wipe --tenant=<id> --phone=<手机号>`（下面前置自证，措辞不符即拒删）。
//
// 用法：
//   BOOTSTRAP_PHONE=<手机号> BOOTSTRAP_COMPANY='6937验收对照-<tag>' SMS_CODE=123456 \
//     node acceptance/2026-10-03/lib/bootstrap-tenant-b.mjs register
//   ... seed   --tenant=<id> --phone=<手机号>
//   ... wipe   --tenant=<id> --phone=<手机号>
import { api, psql, psqlWrite, log } from '../config-writeface-sweep/harness/lib.mjs'

// 本脚本**建**租户，所以不能依赖 subjects.mjs 的 fail-closed 主体注入（那时 B 还不存在）；
// 只取端点与短信码，且短信码同样不许静默默认。
const API_BASE = process.env.API_BASE || 'http://localhost:8080'
const SMS_CODE = (process.env.SMS_CODE ?? '').trim()
const PREFIX = process.env.BOOTSTRAP_PREFIX || '6937验收对照'
const args = Object.fromEntries(process.argv.slice(2).map((a) => { const [k, v] = a.replace(/^--/, '').split('='); return [k, v ?? true] }))
const mode = process.argv[2]?.startsWith('--') ? 'register' : process.argv[2]
const phone = () => String(args.phone || process.env.BOOTSTRAP_PHONE || '').trim()
const tenantId = () => String(args.tenant || '').trim()
const rowsOfTenant = (id) => {
  const tables = psql("select table_name from information_schema.columns where table_schema='public' and column_name='tenant_id' group by 1 order by 1").map((r) => r.table_name)
  let total = 0; const per = {}
  for (const t of tables) { const n = psql(`select count(*)::int c from ${t} where tenant_id=${id}`)[0].c; if (n) { per[t] = n; total += n } }
  return { total, per, tables: tables.length }
}

if (mode === 'register') {
  if (!phone() || !process.env.BOOTSTRAP_COMPANY) {
    console.error('🔴 缺注入口：BOOTSTRAP_PHONE / BOOTSTRAP_COMPANY 必须显式给（本脚本**不**猜手机号）。')
    process.exit(2)
  }
  const company = process.env.BOOTSTRAP_COMPANY
  const send = await api('POST', '/api/auth/sms/send', { body: { phone: phone() } })
  log(`[register] sms/send ${phone()} → ${send.status} ${send.text.slice(0, 160)}`)
  const reg = await api('POST', '/api/auth/register', { body: {
    companyName: company, contactName: `${PREFIX}管理员`, phone: phone(), smsCode: SMS_CODE,
    industry: '布艺纺织', province: '广东省', city: '深圳市', address: '6937 验收探针地址' } })
  log(`[register] register ${company} → ${reg.status} ${reg.text.slice(0, 300)}`)
  if (!reg.json?.success) {
    console.error('🔴 入驻未成功。若为「该企业已有入驻申请」⇒ 先清 tenant_applications 里 phone=' + phone() + ' 的残留行：')
    console.error(`   select id,phone,company_name,status from tenant_applications where phone='${phone()}'`)
    process.exit(1)
  }
  const t = psql(`select t.id, t.name, t.code from tenants t join users u on u.tenant_id=t.id where u.phone='${phone()}' and u.role='admin' order by t.id desc limit 1`)[0]
  if (!t) { console.error('🔴 入驻返回 success 但库里找不到该手机号的 tenants 行'); process.exit(1) }
  console.log(`\n✅ 对照租户已建：TENANT_B=${t.id} PHONE_B=${phone()}（${t.name} / ${t.code}）`)
  console.log(`   export TENANT_B=${t.id} PHONE_B=${phone()}\n   api=${API_BASE}`)
} else if (mode === 'seed') {
  const id = tenantId()
  const l = await api('POST', '/api/auth/sms/login', { body: { phone: phone(), code: SMS_CODE } })
  if (!l.json?.success) { console.error(`🔴 B 侧登录失败（seed 前置）：${l.status} ${l.text.slice(0, 200)}`); process.exit(1) }
  const token = l.json.data.accessToken ?? l.json.data.access_token
  const step = async (label, path, body) => {
    const r = await api('POST', path, { token, body })
    log(`[seed] ${label} POST ${path} → ${r.status} ${r.text.slice(0, 200)}`)
    if (!r.json?.success) { console.error(`🔴 seed 失败：${label}`); process.exit(1) }
    return r.json.data
  }
  const cat = await step('分类', '/api/admin/categories', { name: `${PREFIX}分类` })
  const prod = await step('商品', '/api/admin/products', { name: `${PREFIX}商品`, categoryId: cat.id, unit: '米', basePrice: 12.5, status: 'on_sale' })
  const order = await step('订单', '/api/admin/orders', { customerName: `${PREFIX}客户`, customerPhone: phone(), customerAddress: '6937 验收探针地址', logisticsType: 'express', logisticsCompany: '顺丰', remark: '6937 probe', items: [{ productName: `${PREFIX}商品`, quantity: 1, unitPrice: 12.5, subtotal: 12.5 }] })
  console.log(`\n✅ B(${id}) 播种完成：category=${cat.id} product=${prod.id} order=${order.id ?? '—'}`)
  console.log(`   落地核对：select count(*) from products where tenant_id=${id};`)
} else if (mode === 'wipe') {
  const id = tenantId()
  if (!/^\d+$/.test(id) || !/^\d{6,}$/.test(phone())) { console.error('🔴 用法：wipe --tenant=<数字 id> --phone=<手机号>'); process.exit(2) }
  const t = psql(`select id, name, code from tenants where id=${id}`)[0]
  if (!t) { console.error(`🔴 tenants 无 id=${id} ⇒ 不删（幂等：已清即无事可做）`); process.exit(0) }
  const users = psql(`select phone, role from users where tenant_id=${id}`)
  const foreigners = users.filter((u) => u.phone !== phone())
  // 机械自证：① 企业名在探针命名域内 ② 该租户下**没有**外来手机号（防误删真租户）
  if (!String(t.name).startsWith(PREFIX) || foreigners.length > 0) {
    console.error(`🔴 拒删：tenant id=${id} name='${t.name}'（须以 '${PREFIX}' 开头）；外来手机号 ${JSON.stringify(foreigners)}`)
    process.exit(1)
  }
  const before = rowsOfTenant(id)
  console.log(`[wipe] 清理前：tenants 含 id=${id}（${t.name}/${t.code}）；tenant_id=${id} 子表行数合计=${before.total}（表 ${before.tables} 张）`)
  const tables = psql("select table_name from information_schema.columns where table_schema='public' and column_name='tenant_id' group by 1 order by 1").map((r) => r.table_name)
  for (const tb of tables) { try { psqlWrite(`delete from ${tb} where tenant_id=${id}`) } catch (e) { console.error(`  ⚠️ ${tb}: ${String(e.message).slice(0, 120)}`) } }
  psqlWrite(`delete from tenant_applications where phone='${phone()}'`)
  psqlWrite(`delete from tenants where id=${id}`)
  const after = rowsOfTenant(id)
  const tAfter = psql(`select count(*)::int c from tenants where id=${id}`)[0].c
  const appAfter = psql(`select count(*)::int c from tenant_applications where phone='${phone()}'`)[0].c
  console.log(`[wipe] 清理后：tenants id=${id} 行数=${tAfter}；tenant_id=${id} 子表行数合计=${after.total}；tenant_applications(phone=${phone()}) 行数=${appAfter}`)
  console.log(`[wipe] 全库 tenants 现值=${JSON.stringify(psql('select id,name,code from tenants order by id'))}`)
  if (after.total !== 0 || tAfter !== 0 || appAfter !== 0) { console.error('🔴 自清未到 0 ⇒ 残留未清干净（上表为现取）'); process.exit(1) }
  console.log('✅ 自清到 0（子表残留 / tenants 行 / 入驻申请 三处均为 0，现取）')
} else {
  console.error('用法：bootstrap-tenant-b.mjs register | seed --tenant=<id> --phone=<p> | wipe --tenant=<id> --phone=<p>')
  process.exit(2)
}
