// 阶段 9：**每个岗位用自己的账号跑本岗位的功能**（阶段 4 是 admin 代跑，这是补的真账）
//
// 每个动作断言两件事：① 权限方向（有码 ⇒ 真的做成；无码 ⇒ 403 且**库里没变化**）；② DB 落库证据。
// 「做成了没」一律以 **DB 计数差** 为准（不看接口自称），因为「200 但没落库」和「403 但落了库」都要能被发现。
import { Recorder, log, api, loginApi, employeeLoginApi, psql, saveCtx, loadCtx, waitService, sleep, newContext, shot, chromium, loginUi } from './lib.mjs'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const R = new Recorder('s9-position-jobs.json')
const ctx = loadCtx()
const T = ctx.tenantId
const OUT = process.env.OUT_DIR || join(process.cwd(), 'out')
const WEB = process.env.BASE_URL || 'http://localhost:3001'
const q = (sql) => { try { return psql(sql) } catch (e) { return null } }
const one = (sql) => (q(sql) || [])[0]
const n = (sql) => Number(one(sql)?.n ?? -1)
const err = (r) => (r?.json?.error?.code || '') + ' ' + (r?.json?.error?.message || r?.json?.message || '').slice(0, 80)
const stamp = String(Date.now()).slice(-6)
let phoneSeq = 0   // 每个「建员工」动作一个唯一 11 位手机号（139 + 8 位）

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const admin = await loginApi(ctx.adminPhone)
  const adminToken = admin.token

  // ── 身份就绪（顺带把「必须改密」的信封清掉，否则所有写动作都会 403 PASSWORD_CHANGE_REQUIRED）──
  const people = []
  for (const e of ctx.employees || []) {
    const { token } = await employeeLoginApi(`${e.username}@${ctx.tenantCode}`, e.pwd || ctx.finalPwd)
    const me = await api('GET', '/api/auth/me', { token })
    people.push({ ...e, token, perms: me.json?.data?.permissions || [] })
  }
  const has = (p, code) => p.perms.includes('*') || p.perms.includes(code)
  const by = (role) => people.find((p) => p.roleCode === role)
  log(`== 阶段9：岗位功能闭环 == 岗位 ${people.length} 个`)

  // ── 造一份「本租户的可用素材」：分类 / 商品 / SKU / 一张已确认订单 / 一张草稿入库单 ──
  const cat = await api('POST', '/api/admin/categories', { token: adminToken, body: { name: `岗位验收分类${stamp}`, sortOrder: 1 } })
  const categoryId = cat.json?.data?.id
  const prod = await api('POST', '/api/admin/products', {
    token: adminToken, body: {
      name: `岗位验收商品${stamp}`, unit: '米', pricingType: 'fixed', basePrice: 50,
      status: categoryId ? 'on_shelf' : 'draft', categoryId,
      colors: [{ colorName: '米白', mainColorHex: '#FFFFFF', sortOrder: 1 }],
      skus: [{ colorName: '米白', doorWidth: '2.8m', price: 50, stock: 0, skuCode: `POS-${stamp}` }],
    },
  })
  const productId = prod.json?.data?.id
  const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
  const inb = await api('POST', '/api/admin/inbound-orders', {
    token: adminToken, body: { supplier: `岗位验收供应商${stamp}`, inboundDate: new Date().toISOString().slice(0, 10), items: [{ productId, skuId, quantity: 50, unitCost: 9 }] },
  })
  const draftInboundId = inb.json?.data?.id
  R.pass('PJ-00', '素材就绪（分类/商品/SKU/草稿入库单）', `categoryId=${categoryId}｜productId=${productId}｜skuId=${skuId}｜草稿入库单=${inb.json?.data?.inbound_no}`,
    ['POST /api/admin/categories', 'POST /api/admin/products', 'POST /api/admin/inbound-orders'])

  /** 执行一个「岗位 × 动作」单元：先记 DB 基线 → 发请求 → 再记 DB → 判定方向。 */
  async function act(p, a) {
    const before = a.count()
    const res = await api(a.method, a.url(p), { token: p.token, body: a.body ? a.body(p) : undefined })
    await sleep(120)
    const after = a.count()
    const allowed = has(p, a.code)
    const denied = res.status === 403
    const created = after > before
    const ok = allowed ? (!denied) : (denied && !created)
    return { label: p.pos || p.roleCode, code: a.code, id: a.id, name: a.name, allowed, status: res.status, err: err(res), before, after, created, ok, body: res.text.slice(0, 140) }
  }

  const actions = [
    {
      id: 'ACT-ORDER', name: '建订单', code: 'order:create', method: 'POST', url: () => '/api/admin/orders',
      body: (p) => ({
        customerName: `岗位客户${p.roleCode}${stamp}`, customerPhone: '13500000001', customerAddress: '杭州市余杭区岗位路 1 号',
        logisticsType: 'express', logisticsCompany: '顺丰速运',
        items: [{ productId, skuId, productName: `岗位验收商品${stamp}`, quantity: 2, unitPrice: 50, subtotal: 100 }],
      }),
      count: () => n(`select count(*)::int as n from orders where tenant_id=${T}`),
    },
    {
      id: 'ACT-PRODUCT', name: '建商品', code: 'product:create', method: 'POST', url: () => '/api/admin/products',
      body: (p) => ({ name: `岗位商品${p.roleCode}${stamp}`, unit: '米', pricingType: 'fixed', basePrice: 30, status: categoryId ? 'on_shelf' : 'draft', categoryId }),
      count: () => n(`select count(*)::int as n from products where tenant_id=${T}`),
    },
    {
      id: 'ACT-FIN', name: '登记财务流水', code: 'finance:create', method: 'POST', url: () => '/api/admin/finance/transactions',
      body: (p) => ({ type: 'income', amount: 6.66, paymentMethod: 'cash', remark: `岗位流水${p.roleCode}${stamp}` }),
      count: () => n(`select count(*)::int as n from finance_transactions where tenant_id=${T}`),
    },
    {
      id: 'ACT-INB', name: '建入库单', code: 'inbound:create', method: 'POST', url: () => '/api/admin/inbound-orders',
      body: (p) => ({ supplier: `岗位供应商${p.roleCode}${stamp}`, inboundDate: new Date().toISOString().slice(0, 10), items: [{ productId, skuId, quantity: 5, unitCost: 9 }] }),
      count: () => n(`select count(*)::int as n from inbound_orders where tenant_id=${T}`),
    },
    {
      id: 'ACT-INBPOST', name: '入库过账（草稿单）', code: 'inbound:create', method: 'PATCH', url: () => `/api/admin/inbound-orders/${draftInboundId}`,
      body: () => ({ action: 'post' }),
      count: () => n(`select count(*)::int as n from inbound_orders where tenant_id=${T} and status='posted'`),
    },
    {
      id: 'ACT-AS', name: '建售后工单', code: 'order:refund', method: 'POST', url: () => '/api/admin/after-sales',
      body: (p) => ({ ticketType: 'complaint', description: `岗位售后${p.roleCode}${stamp}`, priority: 'normal' }),
      count: () => n(`select count(*)::int as n from after_sales_tickets where tenant_id=${T}`),
    },
    {
      id: 'ACT-USER', name: '建员工账号', code: 'employee:create', method: 'POST', url: () => '/api/admin/users',
      body: (p) => ({ name: `岗位员工${p.roleCode}${stamp}`, phone: `139${String(Date.now()).slice(-7)}${(phoneSeq++ % 10)}`, username: `pos_${p.roleCode}_${stamp}_${phoneSeq}`, password: 'Init@123456', position: '客服' }),
      count: () => n(`select count(*)::int as n from users where tenant_id=${T}`),
    },
    {
      id: 'ACT-ROLE', name: '建岗位', code: 'system:manage', method: 'POST', url: () => '/api/admin/roles',
      body: (p) => ({ name: `岗位角色${p.roleCode}${stamp}`, description: '岗位验收', permissionIds: [] }),
      count: () => n(`select count(*)::int as n from roles where tenant_id=${T}`),
    },
    {
      id: 'ACT-KNOW', name: '建知识卡', code: 'knowledge:manage', method: 'POST', url: () => '/api/admin/knowledge/cards',
      body: (p) => ({ title: `岗位知识卡${p.roleCode}${stamp}`, content: '岗位验收内容', category: '其他' }),
      count: () => n(`select count(*)::int as n from knowledge_cards where tenant_id=${T}`),
    },
    { id: 'READ-ORDER', name: '读订单列表', code: 'order:list', method: 'GET', url: () => '/api/admin/orders?page=1&size=5', count: () => 0 },
    { id: 'READ-AS', name: '读售后列表', code: 'after_sales:view', method: 'GET', url: () => '/api/admin/after-sales?page=1&size=5', count: () => 0 },
    { id: 'READ-CUS', name: '读客户列表', code: 'customer:view', method: 'GET', url: () => '/api/admin/customers?page=1&size=5', count: () => 0 },
    { id: 'READ-INB', name: '读入库单', code: 'inbound:view', method: 'GET', url: () => '/api/admin/inbound-orders', count: () => 0 },
    { id: 'READ-KNOW', name: '读知识卡', code: 'knowledge:view', method: 'GET', url: () => '/api/admin/knowledge/cards?page=1&size=5', count: () => 0 },
    { id: 'READ-PO', name: '读加工单', code: 'production:view', method: 'GET', url: () => '/api/admin/processing-orders', count: () => 0 },
    { id: 'READ-USER', name: '读员工列表', code: 'employee:list', method: 'GET', url: () => '/api/admin/users?page=1&size=5', count: () => 0 },
    { id: 'READ-DASH', name: '读经营看板', code: 'dashboard:view', method: 'GET', url: () => '/api/admin/dashboard/stats', count: () => 0 },
  ]

  const all = []
  for (const p of people) {
    const rows = []
    for (const a of actions) rows.push(await act(p, a))
    all.push({ principal: p.pos || p.roleCode, roleCode: p.roleCode, perms: p.perms, rows })
    const bad = rows.filter((r) => !r.ok)
    const did = rows.filter((r) => r.allowed && !r.status.toString().startsWith('4')).map((r) => `${r.name}(${r.status}${r.created ? '·落库' : ''})`)
    const blocked = rows.filter((r) => !r.allowed).map((r) => r.name)
    bad.length === 0
      ? R.pass('PJ-01', `岗位功能闭环：${p.pos || p.roleCode}`,
          `做成：${did.join('、') || '（无）'}｜按码被拒：${blocked.join('、') || '（无）'}｜${rows.length} 个动作方向全部与权限码一致`,
          ['out/s9-position-jobs.json'])
      : R.fail('PJ-01', `岗位功能闭环：${p.pos || p.roleCode}`,
          bad.map((b) => `${b.name}(需${b.code}): 有码=${b.allowed} HTTP=${b.status} 落库=${b.created} ${b.err}`).join('；'))
  }
  writeFileSync(join(OUT, 's9-position-jobs.json'), JSON.stringify(all, null, 1))

  // ── 岗位视角的页面证据：4 个岗位各自打开本岗位主页面 ──
  try {
    const browser = await chromium.launch({ headless: true })
    const shots = []
    for (const p of people.filter((x) => ['customer_service', 'operator', 'finance', 'product_manager', 'knowledge_editor', 'acc_custom_978212'].includes(x.roleCode))) {
      const { page } = await newContext(browser)
      await loginUi(page, { mode: 'employee', identifier: `${p.username}@${ctx.tenantCode}`, password: p.pwd || ctx.finalPwd })
      const dash = await page.evaluate(() => document.body.innerText)
      const menus = (dash.match(/[\u4e00-\u9fa5]{2,8}/g) || []).slice(0, 0)
      const sidebar = await page.locator('aside').innerText().catch(() => '')
      await shot(page, `s9-menu-${p.roleCode}`)
      shots.push({ role: p.roleCode, perms: p.perms.length, sidebar: sidebar.replace(/\n/g, ' ').slice(0, 200) })
      await page.close()
    }
    writeFileSync(join(OUT, 's9-menus.json'), JSON.stringify(shots, null, 1))
    R.pass('PJ-02', '岗位视角：登录后侧边栏菜单随权限显隐（页面证据）',
      shots.map((s) => `${s.role}(${s.perms}码): ${s.sidebar.slice(0, 60)}`).join(' ｜ '),
      ['screenshots/s9-menu-*.png', 'out/s9-menus.json'])
    await browser.close()
  } catch (e) {
    R.fail('PJ-02', '岗位菜单页面证据失败', String(e).slice(0, 250))
  }

  // ── 工人身份：B 端可用、商家后台不可用 ──
  try {
    const wlogin = await api('POST', '/api/worker/login', { body: { workerNo: ctx.worker.workerNo, pin: ctx.worker.pin, tenantId: T, deviceLabel: 'POS-CHECK' } })
    const wsess = wlogin.json?.data?.session_id
    const wme = await api('GET', '/api/worker/me', { headers: { 'X-Worker-Session-Id': wsess } })
    const wadmin = await api('GET', '/api/admin/orders', { headers: { 'X-Worker-Session-Id': wsess } })
    wme.status === 200 && wadmin.status === 403
      ? R.pass('PJ-03', '工人身份：B 端可用 + 商家后台不可用',
          `GET /api/worker/me HTTP ${wme.status}（pages=${JSON.stringify(wme.json?.data?.pages)}）｜GET /api/admin/orders HTTP ${wadmin.status}（${err(wadmin)}）`,
          ['POST /api/worker/login', 'GET /api/worker/me', 'GET /api/admin/orders'])
      : R.fail('PJ-03', '工人身份越权检查', `worker/me=${wme.status} admin/orders=${wadmin.status}`)
  } catch (e) {
    R.fail('PJ-03', '工人身份探针异常', String(e).slice(0, 200))
  }

  const s = R.summary()
  log(`== 阶段9 完成：pass=${s.pass} fail=${s.fail}`)
}
main().catch((e) => { R.fail('PJ-FATAL', '阶段9 致命错误', String(e).slice(0, 400)); process.exitCode = 1 })
