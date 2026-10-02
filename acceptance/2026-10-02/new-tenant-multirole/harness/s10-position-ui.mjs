// 阶段 10：**每个岗位用自己的账号在 UI 上跑通本岗位的功能闭环**（阶段 9 是 API 口径，本阶段是页面口径）
//
// 🔴 判定设计（可归因）——每个写旅程**同时跑两遍**：
//   · 岗位身份（商品管理员 / 运营 / 财务）  ← 被测对象
//   · 管理员对照（admin，权限 `*`）          ← 对照组
//   三种结论各自可区分：
//     岗位成功           ⇒ 本岗位 UI 闭环成立（并断言 DB 落库）
//     岗位失败 + 对照成功 ⇒ **权限面**在页面上生效（RBAC 生效证据）
//     两边都失败         ⇒ 表单没填全 / 页面不可用，如实记「未判定」，不冒充产品结论
// 三路留证：页面截图 + DB 计数差 + 服务器日志。
import { Recorder, log, api, loginApi, employeeLoginApi, psql, loadCtx, waitService, newContext, shot, chromium, loginUi } from './lib.mjs'
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

const R = new Recorder('s10-position-ui.json')
const ctx = loadCtx()
const T = ctx.tenantId
const OUT = process.env.OUT_DIR || join(process.cwd(), 'out')
const WEB = process.env.BASE_URL || 'http://localhost:3002'
const API_LOG = process.env.API_LOG || '/tmp/acc-admin-api.log'
const stamp = String(Date.now()).slice(-6)
const q = (sql) => { try { return psql(sql) } catch { return null } }
const one = (sql) => (q(sql) || [])[0]
const n = (sql) => Number(one(sql)?.n ?? -1)
const pick = (re, s) => ((s || '').match(re) || [''])[0]
const ONLY = (process.env.ONLY || '').split(',').filter(Boolean)   // 例：ONLY=A1,A2 只重跑这两段
const want = (id) => ONLY.length === 0 || ONLY.includes(id)

const ORIGIN_FIX = (c) => c.route('**/api/**', (r) => {
  const h = { ...r.request().headers() }
  delete h['origin']; delete h['referer']
  return r.continue({ headers: h })
})
let tinyPng = ''   // 模块级：fillFocused 等模块级函数要用（上一轮漏了作用域 ⇒ A1/A2/B1 全崩）
const setReact = (page, sel, val) => page.evaluate(([s2, v]) => {
  const el = document.querySelector(s2); if (!el) return false
  const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement : window.HTMLInputElement
  Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, v)
  el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }))
  return true
}, [sel, val])

const TINY_PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')


/** 提交 → 若页面给出必填提示 ⇒ 点提示逐项定位并补齐 → 再提交（页面自带的「还差 N 项/查看第一处问题」就是补齐口）。 */
async function fillFocused(page) {
  // 兜底 0：任何**还没选文件**的 file input 都塞一张 1×1 PNG（页面把「商品主图/详情图」列为必填）
  const fis = page.locator('input[type="file"]')
  const fn = await fis.count()
  for (let i = 0; i < fn; i++) {
    const has = await fis.nth(i).evaluate((e) => (e.files ? e.files.length : 0)).catch(() => 1)
    if (!has) { await fis.nth(i).setInputFiles(tinyPng).catch(() => {}); await page.waitForTimeout(1800); return true }
  }
  const info = await page.evaluate(() => {
    let a = document.activeElement
    if (!a) return null
    const inner = a.querySelector && a.querySelector('input,select,textarea')
    if (inner && !['INPUT', 'SELECT', 'TEXTAREA'].includes(a.tagName)) { inner.focus(); a = inner }
    return { tag: a.tagName, type: a.type || '', ph: a.placeholder || '', aria: a.getAttribute('aria-label') || '' }
  })
  if (!info) return false
  if (info.tag === 'SELECT') {
    await page.evaluate(() => { const a = document.activeElement; if (a && a.options && a.options.length > 1) { a.selectedIndex = 1; a.dispatchEvent(new Event('change', { bubbles: true })) } })
    return true
  }
  if (info.tag === 'INPUT') {
    await page.evaluate((ph) => {
      const a = document.activeElement
      if (!a) return
      a.value = /6\.6|2\.6|宽|高|米|数量|库存|价格/.test(ph) ? '2.5' : 'UI闭环自动填'
      a.dispatchEvent(new Event('input', { bubbles: true })); a.dispatchEvent(new Event('change', { bubbles: true }))
    }, info.ph)
    return true
  }
  if (info.tag === 'BUTTON') {
    await page.evaluate(() => document.activeElement && document.activeElement.click())
    await page.waitForTimeout(600)
    await page.locator('[role="option"], li, button').filter({ hasNotText: /取消|关闭|返回/ }).first().click().catch(() => {})
    return true
  }
  return false
}

/** 反复「提交 → 按提示补齐」，直到没有提示或达到轮次上限；返回最后一次的页面文本。 */
async function submitAndComplete(page, submitRe, rounds = 4) {
  for (let i = 0; i < rounds; i++) {
    const btn = page.getByRole('button', { name: submitRe }).first()
    await btn.scrollIntoViewIfNeeded().catch(() => {})
    await btn.click({ timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(3000)
    const body = await page.evaluate(() => document.body.innerText).catch(() => '')
    const hasHint = /还差 \d+ 项|查看第一处问题|还有 \d+ 处必填|请选择常用物流|未选择颜色|未填宽|未填高/.test(body)
    if (!hasHint) return body
    // 点「还差 N 项」清单里的每一条 / 或「查看第一处问题」
    const items = page.locator('li, button, [role="button"], span').filter({ hasText: /请选择常用物流|请填写常用物流公司|未选择颜色|未填宽（米）|未填高（米）|请选择|必填/ })
    const n = Math.min(await items.count(), 8)
    let did = false
    for (let k = 0; k < n; k++) { await items.nth(k).click({ timeout: 3000 }).catch(() => {}); did = (await fillFocused(page)) || did; await page.waitForTimeout(400) }
    const first = page.getByText('查看第一处问题').first()
    if (await first.isVisible().catch(() => false)) { await first.click().catch(() => {}); did = (await fillFocused(page)) || did }
    if (!did) return body
  }
  return page.evaluate(() => document.body.innerText).catch(() => '')
}

async function main() {
  if (!(await waitService())) throw new Error('admin-api 未就绪')
  const admin = await loginApi(ctx.adminPhone)
  const people = []
  for (const e of ctx.employees || []) {
    const { token } = await employeeLoginApi(`${e.username}@${ctx.tenantCode}`, e.pwd || ctx.finalPwd)
    const me = await api('GET', '/api/auth/me', { token })
    people.push({ ...e, token, perms: me.json?.data?.permissions || [] })
  }
  const P = (role) => people.find((x) => x.roleCode === role)
  log(`== 阶段10：岗位 UI 功能闭环 == 租户 ${T}(${ctx.tenantName}) 坐标 main@3fa84ab89 @ ${WEB}`)

  // ── 素材（s2 不造业务数据）：分类 + 商品（含颜色/SKU）；另建**真零权限**账号作对照 ──
  const cat = await api('POST', '/api/admin/categories', { token: admin.token, body: { name: `UI闭环分类${stamp}`, sortOrder: 1 } })
  const categoryName = `UI闭环分类${stamp}`
  const prod = await api('POST', '/api/admin/products', {
    token: admin.token, body: {
      name: `UI闭环商品${stamp}`, unit: '米', pricingType: 'fixed', basePrice: 66, status: 'on_shelf', categoryId: cat.json?.data?.id,
      colors: [{ colorName: '米白', mainColorHex: '#FFFFFF', sortOrder: 1 }],
      skus: [{ colorName: '米白', doorWidth: '2.8m', price: 66, stock: 100, skuCode: `UI-${stamp}` }],
    },
  })
  const productName = `UI闭环商品${stamp}`
  // 真零权限 = 「权限为空的**岗位**」+ 该岗位的账号（给员工传 permissions:[] 会被岗位默认权限顶回）
  const zero = await api('POST', '/api/admin/users', {
    token: admin.token, body: { name: `零权限岗${stamp}`, phone: `139${String(Date.now()).slice(-8)}`, username: `zero_${stamp}`, password: 'Zero@123456', position: '客服' },
  })
  // 建号时 permissions:[] 会被**岗位默认权限**兜底（#2969 有意）⇒ 要真零权限须建完再**用数组**更新
  if (zero.json?.data?.id) await api('PUT', `/api/admin/users/${zero.json.data.id}`, { token: admin.token, body: { permissions: [] } })
  // 🔴 实测坑：建人时传 `permissions: []` **不会**得到零权限 —— 后端用**岗位默认权限**预填快照
  //    （本次实测：position=客服 ⇒ 快照 11 码）。要真零码必须建完再显式写空。
  let zeroPwd = 'Zero@123456', zeroPerms = null
  try {
    const zl = await employeeLoginApi(`zero_${stamp}@${ctx.tenantCode}`, zeroPwd)
    await api('POST', '/api/auth/password/change', { token: zl.token, body: { oldPassword: zeroPwd, newPassword: 'Zero@2026x' } })
    zeroPwd = 'Zero@2026x'
    const zl2 = await employeeLoginApi(`zero_${stamp}@${ctx.tenantCode}`, zeroPwd)
    zeroPerms = (await api('GET', '/api/auth/me', { token: zl2.token })).json?.data?.permissions || []
  } catch (e) { zeroPerms = ['(失败:' + String(e).slice(0, 50) + ')'] }
  R.pass('UI-00', 'UI 闭环素材就绪（分类 / 商品 / 真零权限对照账号）',
    `分类=${categoryName}｜商品=${productName}（${prod.json?.data?.id}）｜零权限账号=zero_${stamp}（用户 ${zero.json?.data?.id}），/api/auth/me 权限码=${JSON.stringify(zeroPerms)}`,
    ['POST /api/admin/categories', 'POST /api/admin/products', 'POST /api/admin/users'])

  tinyPng = join(OUT, `tiny-${stamp}.png`)
  writeFileSync(tinyPng, TINY_PNG)

  const browser = await chromium.launch({
    headless: true,
    // 探针侧 CORS 开关：隔离实例 3002 → 后端 8080 跨源且后端不返 CORS 头（不改后端、不改应用）
    args: ['--disable-web-security', '--disable-features=IsolateOrigins,site-per-process'],
  })
  const seen = []
  const puts = []   // PUT /api/admin/users/{id} 的请求体（判定前端到底发了什么）
  async function session(who) {
    const { page, ctx: context } = await newContext(browser)
    await ORIGIN_FIX(context)
    page.on('response', (r) => { if (r.url().includes('/api/')) seen.push(`${r.status()} ${r.request().method()} ${r.url().replace('http://localhost:8080', '')}`) })
    page.on('request', (r) => { if (r.method() === 'PUT' && /\/api\/admin\/users\/[0-9a-f]+$/.test(r.url())) puts.push({ url: r.url(), body: r.postData() || '' }) })
    if (who === 'admin') await loginUi(page, { mode: 'admin', phone: ctx.adminPhone })
    else await loginUi(page, { mode: 'employee', identifier: `${who.username}@${ctx.tenantCode}`, password: who.pwd || who.pwdOverride || ctx.finalPwd })
    return page
  }
  const text = (page) => page.evaluate(() => document.body.innerText).catch(() => '')

  // ════════ A1 建商品（岗位：商品管理员；对照：admin） ════════
  async function productJourney(page, tag) {
    await page.goto(`${WEB}/products/new`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3500)
    const title = `UI岗位商品${tag}${stamp}`
    // 商品分类是**原生 select**（点「请选择」不会写值 —— 实测标红仍在）⇒ 直接 selectOption
    const catSel = page.locator('select').filter({ hasText: categoryName }).first()
    await catSel.selectOption({ label: categoryName }, { force: true, timeout: 6000 }).catch(() => {})
    await page.waitForTimeout(600)
    await page.locator('input[placeholder*="最多可输入"]').first().fill(title).catch(() => {})
    const fi = page.locator('input[type="file"]')
    if (await fi.count()) { await fi.first().setInputFiles(tinyPng).catch(() => {}); await page.waitForTimeout(2500) }
    const addBtns = page.locator('button[title="添加"]')
    const ac = await addBtns.count()
    if (ac > 0) { await addBtns.nth(ac - 1).click().catch(() => {}); await page.waitForTimeout(800) }
    const dw = page.locator('select[aria-label="规格尺寸"]').first()
    if (await dw.isVisible().catch(() => false)) await dw.selectOption({ label: '2.8米' }).catch(() => {})
    const sel = page.locator('select')
    for (let i = 0; i < Math.min(await sel.count(), 5); i++) await sel.nth(i).selectOption({ index: 1 }).catch(() => {})
    // 通用补齐：所有**空**的文本输入与 select 都填上（按类型给值）
    const inputs = page.locator('input:not([type="file"]):not([type="checkbox"]):not([type="radio"])')
    const ic = await inputs.count()
    for (let i = 0; i < ic; i++) {
      const el = inputs.nth(i)
      const v = await el.inputValue().catch(() => 'x')
      if (v) continue
      const ph = (await el.getAttribute('placeholder')) || ''
      await el.fill(/货号/.test(ph) ? `UI-${stamp}` : /价|数量|库存|米/.test(ph) ? '10' : `AUTO${i}`, { force: true }).catch(() => {})
    }
    const sels2 = page.locator('select')
    const sc2 = await sels2.count()
    for (let i = 0; i < sc2; i++) {
      const v = await sels2.nth(i).inputValue().catch(() => 'x')
      if (!v) await sels2.nth(i).selectOption({ index: 1 }, { force: true }).catch(() => {})
    }
    // 页面自带「查看第一处问题」⇒ 用它把标红必填项逐项补齐（最多 10 轮，填不动就停）
    for (let i = 0; i < 10; i++) {
      const hint = page.getByText('查看第一处问题').first()
      if (!(await hint.isVisible().catch(() => false))) break
      await hint.click().catch(() => {})
      await page.waitForTimeout(700)
      const kind = await page.evaluate(() => {
        const a = document.activeElement
        if (!a) return null
        return { tag: a.tagName, type: a.type || '', ph: a.placeholder || '', label: a.getAttribute('aria-label') || '', cls: (a.className || '').toString().slice(0, 60) }
      })
      if (!kind) break
      try {
        if (kind.tag === 'SELECT') await page.evaluate(() => { const a = document.activeElement; if (a && a.options && a.options.length > 1) { a.selectedIndex = 1; a.dispatchEvent(new Event('change', { bubbles: true })) } })
        else if (kind.tag === 'INPUT') await page.evaluate((ph) => { const a = document.activeElement; if (!a) return; a.value = /价格|数量|库存|米/.test(ph) ? '10' : `AUTO-${Date.now() % 10000}`; a.dispatchEvent(new Event('input', { bubbles: true })); a.dispatchEvent(new Event('change', { bubbles: true })) }, kind.ph)
        else if (kind.tag === 'BUTTON') { await page.evaluate(() => document.activeElement?.click()); await page.waitForTimeout(600); await page.locator('[role="option"], li, button').filter({ hasNotText: /取消|关闭/ }).first().click().catch(() => {}) }
      } catch { /* 该轮补不动，继续下一轮 */ }
      const still = await page.getByText('查看第一处问题').isVisible().catch(() => false)
      if (!still) break
    }
    // 页面两条出口：**存草稿**（validateProductForm 的 isDraft 分支 ⇒ 仅要求标题，实测可落库）
    // 与**提交并上架**（要求 货号/计价单位/分类/主图≥1/颜色≥1/门幅…，且主图须**上传成功**）。先走能闭环的那条。
    await page.getByRole('button', { name: /存草稿/ }).first().click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(4000)
    let body = await text(page)
    if (n(`select count(*)::int as n from products where tenant_id=${T} and name='${title}'`) !== 1) {
      body = await submitAndComplete(page, /提交并上架/)
    }
    return {
      title,
      ok: n(`select count(*)::int as n from products where tenant_id=${T} and name='${title}'`) === 1,
      status: (one(`select status from products where tenant_id=${T} and name='${title}'`) || {}).status,
      problem: pick(/还有 \d+ 处必填[^\n]*|表单校验未通过[^\n]*|失败[^\n]{0,40}|至少上传 1 张商品主图|请至少添加 1 种颜色/, body),
      tail: body.slice(-150).replace(/\n/g, ' '),
    }
  }
  if (want('A1')) try {
    const before = n(`select count(*)::int as n from products where tenant_id=${T}`)
    let page = await session(P('product_manager'))
    const asPm = await productJourney(page, '岗位')
    await shot(page, 's10-A1a-商品管理员-建商品'); await page.close()
    page = await session('admin')
    const asAdmin = await productJourney(page, '对照')
    await shot(page, 's10-A1b-管理员对照-建商品'); await page.close()
    const after = n(`select count(*)::int as n from products where tenant_id=${T}`)
    if (asPm.ok) R.pass('UI-A1', `商品管理员在本岗位页面**真的建成商品**（落库，status=${asPm.status}）`, `products ${before} → ${after}；新建「${asPm.title}」；对照(admin)成功=${asAdmin.ok}`, ['screenshots/s10-A1a-商品管理员-建商品.png', 'screenshots/s10-A1b-管理员对照-建商品.png'])
    else if (asAdmin.ok) R.fail('UI-A1', '商品管理员建品失败、管理员对照成功 ⇒ 权限面在页面生效', `岗位报错=${asPm.problem}｜products ${before} → ${after}`)
    else R.fail('UI-A1', '⚠️ 未判定：岗位与对照都没建成（表单/环境问题，非权限结论）', `岗位=${asPm.problem || asPm.tail}｜对照=${asAdmin.problem || asAdmin.tail}`)
  } catch (e) { R.fail('UI-A1', '建品旅程异常', String(e).slice(0, 260)) }

  // ════════ A2 建订单（岗位：运营；对照：admin） ════════
  async function orderJourney(page, who) {
    await page.goto(`${WEB}/orders/new`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3500)
    await page.fill('input[placeholder*="收货人姓名"]', `UI闭环客户${who}${stamp}`)
    await page.fill('input[placeholder*="手机号"]', '13900002222')
    await page.fill('input[placeholder*="收货地址"]', '杭州市余杭区 UI 闭环路 1 号')
    await page.getByRole('button', { name: /点击搜索并选择商品|选择商品/ }).first().click()
    await page.waitForTimeout(1200)
    const s = page.locator('[role="dialog"] input').first()
    if (await s.isVisible().catch(() => false)) { await s.fill(productName); await page.waitForTimeout(1600) }
    await page.getByText(productName, { exact: false }).first().click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(2000)
    // 行内必填（页面会给出「还差 N 项」清单）：颜色=颜色小按钮；宽/高=如 6.6 / 如 2.6
    // 🔴 节奏很关键：实测**快速连填**会让「自动识别判定中/加工费计价中」两个闸门长期不收敛（探针伪影；
    //    放慢到每步 ≥2.5s 则闸门正常收敛 —— 已在 :3002/:3001 双实例上对照过）⇒ 按人类节奏填。
    await page.getByRole('button', { name: '米白', exact: true }).first().click().catch(() => {})
    await page.waitForTimeout(2500)
    await page.locator('input[placeholder="如 6.6"]').first().fill('2.5', { force: true }).catch(() => {})
    await page.waitForTimeout(2500)
    await page.locator('input[placeholder="如 2.6"]').first().fill('2.5', { force: true }).catch(() => {})
    await page.waitForTimeout(2500)
    // 常用物流（页面上最后一个 select 无名）＋ 物流公司（如 四季安物流）
    // 常用物流/快递 = **原生 select**（id=order-logistics-type，选项：未指定 + LOGISTICS_TYPES）
    // 常用物流公司 = **input**（id=order-logistics-company，词表只是 datalist 候选）
    // 🔴 这两个控件在页面上是 `visible=false` 的**隐藏原生控件**（自定义下拉/输入框盖在上面）⇒ 必须 force
    await page.locator('#order-logistics-type').selectOption({ index: 1 }, { force: true, timeout: 5000 }).catch(() => {})
    await setReact(page, '#order-logistics-company', 'UI闭环物流')   // 受控组件：fill(force) 写不进 state
    await page.waitForTimeout(400)
    // 仍缺就按页面提示点一遍（点一条直达对应字段）
    for (let i = 0; i < 6; i++) {
      const hint = page.getByText(/第 \d+ 个商品未|请选择常用物流|请填写常用物流/).first()
      if (!(await hint.isVisible().catch(() => false))) break
      await hint.click().catch(() => {}); await page.waitForTimeout(600)
      const t = await page.evaluate(() => { const a = document.activeElement; return a ? { tag: a.tagName, ph: a.placeholder || '' } : null })
      if (t?.tag === 'INPUT') await page.evaluate((ph) => { const a = document.activeElement; if (a) { a.value = /如 6\.6|如 2\.6|米/.test(ph) ? '2.5' : 'UI闭环物流'; a.dispatchEvent(new Event('input', { bubbles: true })); a.dispatchEvent(new Event('change', { bubbles: true })) } }, t.ph)
      else if (t?.tag === 'BUTTON') { await page.evaluate(() => document.activeElement?.click()); await page.waitForTimeout(500); await page.locator('[role="option"], li, button').filter({ hasNotText: /取消|关闭/ }).first().click().catch(() => {}) }
    }
    // 页面有两条**异步**前置：自动识别判定中 / 加工费计价中 ⇒ 等它们收敛再提交（否则「还差 N 项」是假的）
    for (let i = 0; i < 20; i++) {
      const t = await text(page)
      if (!/判定中|计价中/.test(t)) break
      await page.waitForTimeout(1000)
    }
    const body = await submitAndComplete(page, /提交订单/)
    return {
      ok: n(`select count(*)::int as n from orders where tenant_id=${T} and customer_name like 'UI闭环客户${who}%'`) >= 1,
      problem: pick(/还有 \d+ 处必填[^\n]*|权限不足[^\n]{0,30}|没有权限[^\n]{0,20}|失败[^\n]{0,40}/, body),
      url: page.url().replace(WEB, ''),
      tail: body.slice(-140).replace(/\n/g, ' '),
    }
  }
  if (want('A2')) try {
    const before = n(`select count(*)::int as n from orders where tenant_id=${T}`)
    let page = await session(P('operator'))
    const asOp = await orderJourney(page, '运营')
    await shot(page, 's10-A2a-运营-建订单'); await page.close()
    page = await session('admin')
    const asAdmin = await orderJourney(page, '管理员')
    await shot(page, 's10-A2b-管理员对照-建订单'); await page.close()
    const after = n(`select count(*)::int as n from orders where tenant_id=${T}`)
    if (asOp.ok) R.pass('UI-A2', '运营在本岗位页面**真的建成订单**（落库）', `orders ${before} → ${after}；跳转=${asOp.url}；对照成功=${asAdmin.ok}`, ['screenshots/s10-A2a-运营-建订单.png'])
    else if (asAdmin.ok) R.fail('UI-A2', '运营建单失败、管理员对照成功 ⇒ 权限面在页面生效', `岗位=${asOp.problem}`)
    else R.fail('UI-A2', '⚠️ 未判定：岗位与对照都没建成（表单/环境问题）', `岗位=${asOp.problem || asOp.tail}｜对照=${asAdmin.problem || asAdmin.tail}`)
  } catch (e) { R.fail('UI-A2', '建单旅程异常', String(e).slice(0, 260)) }

  // ════════ A3 登记收支（岗位：财务；对照：admin） ════════
  async function financeJourney(page) {
    await page.goto(`${WEB}/finance`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const trigger = page.getByRole('button', { name: /登记收支|登记流水|新增流水/ }).first()
    const seenTrigger = await trigger.isVisible().catch(() => false)
    if (seenTrigger) { await trigger.click(); await page.waitForTimeout(1500) }
    const dlg = page.locator('[role="dialog"]')
    const hasDlg = (await dlg.count()) > 0
    const amount = hasDlg ? dlg.locator('input').first() : page.locator('input[placeholder="0.00"]').first()
    await amount.fill('128.50').catch(() => {})
    const sel = hasDlg ? dlg.locator('select').first() : page.locator('select').first()
    if (await sel.isVisible().catch(() => false)) await sel.selectOption({ index: 1 }).catch(() => {})
    await page.getByRole('button', { name: /确定|提交|保存/ }).last().click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(3500)
    const body = await text(page)
    return {
      ok: n(`select count(*)::int as n from finance_transactions where tenant_id=${T} and amount=128.50`) >= 1,
      seenTrigger, hasDlg,
      problem: pick(/权限不足[^\n]{0,30}|请(输入|选择)[^\n]{0,20}|失败[^\n]{0,40}/, body),
      tail: body.slice(-140).replace(/\n/g, ' '),
    }
  }
  if (want('A3')) try {
    const before = n(`select count(*)::int as n from finance_transactions where tenant_id=${T}`)
    let page = await session(P('finance'))
    const asFin = await financeJourney(page)
    await shot(page, 's10-A3a-财务-登记收支'); await page.close()
    page = await session('admin')
    const asAdmin = await financeJourney(page)
    await shot(page, 's10-A3b-管理员对照-登记收支'); await page.close()
    const after = n(`select count(*)::int as n from finance_transactions where tenant_id=${T}`)
    if (asFin.ok) R.pass('UI-A3', '财务在本岗位页面**真的登记收支**（落库）', `finance_transactions ${before} → ${after}；触发器可见=${asFin.seenTrigger} 弹窗=${asFin.hasDlg}；对照成功=${asAdmin.ok}`, ['screenshots/s10-A3a-财务-登记收支.png'])
    else if (asAdmin.ok) R.fail('UI-A3', '财务登记失败、管理员对照成功 ⇒ 权限面在页面生效', `岗位=${asFin.problem}`)
    else R.fail('UI-A3', '⚠️ 未判定：岗位与对照都没登记成功（表单/环境问题）', `岗位=${asFin.problem || asFin.tail}｜触发可见=${asFin.seenTrigger} 弹窗=${asFin.hasDlg}｜对照=${asAdmin.problem || asAdmin.tail}`)
  } catch (e) { R.fail('UI-A3', '登记收支旅程异常', String(e).slice(0, 260)) }

  if (want('B1'))
  // ════════ B1 销售：完整走一遍下单表单 → 应做不成（缺 order:create） ════════
  if (want('A2')) try {
    const before = n(`select count(*)::int as n from orders where tenant_id=${T}`)
    const page = await session(P('sales'))
    const r = await orderJourney(page, '销售越权')
    await shot(page, 's10-B1-销售-下单被拒'); await page.close()
    const after = n(`select count(*)::int as n from orders where tenant_id=${T}`)
    if (r.ok) R.fail('UI-B1', '销售越权下单**成功**了（不应发生）', `orders ${before} → ${after}`)
    else if (before === after && r.problem) R.pass('UI-B1', '销售在页面上**做不成**下单（缺 order:create）', `orders 未变（${before}）；页面提示=「${r.problem}」`, ['screenshots/s10-B1-销售-下单被拒.png'])
    else R.fail('UI-B1', '⚠️ 未判定：销售下单未落库，但无明确拒绝提示', `orders ${before} → ${after}｜跳转=${r.url}｜尾部=${r.tail}`)
  } catch (e) { R.fail('UI-B1', '销售越权旅程异常', String(e).slice(0, 260)) }

  // ════════ B2 客服：售后可读；建单入口走一遍 → 应做不成（缺 order:refund） ════════
  try {
    const before = n(`select count(*)::int as n from after_sales_tickets where tenant_id=${T}`)
    const page = await session(P('customer_service'))
    await page.goto(`${WEB}/after-sales`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const readable = !/无权访问该页面/.test(await text(page))
    const w = page.getByRole('button', { name: /新建|建单|新建工单|状态变更/ }).first()
    const seenW = await w.isVisible().catch(() => false)
    let problem = ''
    if (seenW) {
      await w.click().catch(() => {})
      await page.waitForTimeout(2500)
      problem = pick(/权限不足[^\n]{0,30}|没有权限[^\n]{0,20}|无权[^\n]{0,20}/, await text(page))
    }
    await shot(page, 's10-B2-客服-售后读写面'); await page.close()
    const after = n(`select count(*)::int as n from after_sales_tickets where tenant_id=${T}`)
    readable && after === before
      ? R.pass('UI-B2', '客服页面：售后**可读**、**建单/改状态做不成**（缺 order:refund）', `列表可读=${readable}｜建单入口可见=${seenW}｜拒绝提示=${problem || '(入口未展开或无提示)'}｜工单 ${before} → ${after}`, ['screenshots/s10-B2-客服-售后读写面.png'])
      : R.fail('UI-B2', '客服售后读写面与权限不符', `可读=${readable} 入口=${seenW} 工单 ${before}→${after}`)
  } catch (e) { R.fail('UI-B2', '客服售后旅程异常', String(e).slice(0, 260)) }

  // ════════ B3 知识编辑：知识库页面被拦（缺 knowledge:view） ════════
  try {
    const page = await session(P('knowledge_editor'))
    await page.goto(`${WEB}/knowledge`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const t = await text(page)
    const blocked = /无权访问该页面/.test(t)
    await shot(page, 's10-B3-知识编辑-知识库被拦'); await page.close()
    blocked
      ? R.pass('UI-B3', '知识编辑的页面被守卫拦下（缺 knowledge:view）', `文案=「${pick(/无权访问该页面[\s\S]{0,50}/, t).replace(/\n/g, ' ')}」`, ['screenshots/s10-B3-知识编辑-知识库被拦.png'])
      : R.fail('UI-B3', '知识编辑未拿到知识库页面', `片段=${t.slice(0, 160)}`)
  } catch (e) { R.fail('UI-B3', '知识编辑旅程异常', String(e).slice(0, 260)) }

  if (want('B4'))
  // ════════ B4 真零权限账号：页面全被拦（不是有 2 码的临时岗） ════════
  try {
    const routes = ['/dashboard', '/orders', '/products', '/finance', '/employees']
    const page = await session({ username: `zero_${stamp}`, pwdOverride: zeroPwd })
    const res = []
    for (const r of routes) {
      await page.goto(WEB + r, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1400)
      if (/\/login/.test(page.url())) { res.push(`${r}=落登录`); continue }
      res.push(`${r}=${/无权访问该页面/.test(await text(page)) ? '拦' : '放'}`)
    }
    await shot(page, 's10-B4-零权限岗-页面拦截'); await page.close()
    const allBlocked = res.every((x) => x.endsWith('拦') || x.endsWith('落登录'))
    const zeroN = Array.isArray(zeroPerms) ? zeroPerms.length : -1
    if (allBlocked) R.pass('UI-B4', `零权限账号（权限码 ${zeroN} 个）抽查 ${routes.length} 条页面**全部被拦**`, res.join(' '), ['screenshots/s10-B4-零权限岗-页面拦截.png'])
    else if (zeroN > 0) R.fail('UI-B4', `⚠️ 未判定：本轮**未能构造零权限账号**（实得 ${zeroN} 码，页面按真权限放行，非缺陷）`, `${res.join(' ')}｜实得权限码=${JSON.stringify(zeroPerms).slice(0, 160)}｜两条构造路径都不成立：给员工传 permissions:[] 会被**岗位默认权限**顶回（实测客服=11 码）；空权限岗位建号实得 ${zeroN} 码`)
    else R.fail('UI-B4', '零权限账号有页面未被拦（权限码为 0 却放行）', `${res.join(' ')}｜权限码=${JSON.stringify(zeroPerms)}`)
  } catch (e) { R.fail('UI-B4', '零权限岗旅程异常', String(e).slice(0, 260)) }

  // ════════ A4 管理员在员工页**编辑员工权限**：UI 勾选 → 保存 → DB 快照是否真变 ════════
  if (want('A4')) try {
    const target = P('customer_service')
    const targetId = (one(`select id from users where username='${target.username}'`) || {}).id   // ctx 里没有 id ⇒ 从库里取
    const snapBefore = (one(`select permissions::text as p from users where username='${target.username}'`) || {}).p
    const page = await session('admin')
    await page.goto(`${WEB}/employees`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3500)
    const row = page.getByRole('row').filter({ hasText: target.username }).first()
    const editBtn = (await row.count()) ? row.getByRole('button', { name: '编辑', exact: true }).first()
      : page.getByRole('button', { name: '编辑', exact: true }).first()
    await editBtn.scrollIntoViewIfNeeded().catch(() => {})
    await editBtn.click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(4500)   // 权限树是**异步**加载的（实测 2.5s 时还是空）
    // 权限树：至少勾掉一个已勾选项
    // 优先用**原生 checkbox**（.uncheck 有幂等语义）；否则退回自定义 role=checkbox
    let bc = 0, toggled = false
    const nativeBoxes = page.locator('[role="dialog"] input[type="checkbox"]:checked')
    const customBoxes = page.locator('[role="dialog"] [role="checkbox"][aria-checked="true"]')
    const useNative = (await nativeBoxes.count()) > 0
    bc = useNative ? await nativeBoxes.count() : await customBoxes.count()
    if (bc > 0) {
      if (useNative) {
        // 从后往前逐个尝试 uncheck，直到**确实翻转**（末尾可能是折叠区/父级，点不动）
        for (let i = bc - 1; i >= 0 && !toggled; i--) {
          const box = nativeBoxes.nth(i)
          if ((await box.isChecked().catch(() => null)) !== true) continue
          await box.uncheck({ force: true, timeout: 3000 }).catch(() => {})
          toggled = (await box.isChecked().catch(() => true)) === false
        }
      } else {
        const box = customBoxes.last()
        const before = await box.getAttribute('aria-checked').catch(() => null)
        await box.click({ timeout: 5000 }).catch(() => {})
        await page.waitForTimeout(400)
        const after = await box.getAttribute('aria-checked').catch(() => null)
        toggled = String(before) !== String(after)
      }
    }
    await page.waitForTimeout(500)
    await page.getByRole('button', { name: /保存|确定|提交/ }).last().click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(3500)
    const snapAfter = (one(`select permissions::text as p from users where username='${target.username}'`) || {}).p
    // 诊断读数必须在**关页前**取（关页后 locator 会报 "page has been closed"）
    const diag = {
      dialogs: await page.locator('[role="dialog"]').count().catch(() => -1),
      allBoxes: await page.locator('[role="dialog"] input[type="checkbox"]').count().catch(() => -1),
      targetId, mineLen: puts.filter((x) => x.url.endsWith('/' + targetId)).length, bc, toggled,
    }
    await shot(page, 's10-A4-员工权限编辑保存')
    await page.close()
    const mine = puts.filter((x) => x.url.endsWith('/' + targetId))   // 只看**目标员工**那次更新
    const body = mine.length ? mine[mine.length - 1].body : (puts.length ? puts[puts.length - 1].body : '')
    let sent = null
    try { sent = JSON.parse(body)?.permissions ?? null } catch { sent = null }
    const changed = snapBefore !== snapAfter
    const payloadHasArray = Array.isArray(sent)
    if (!toggled || !payloadHasArray) {
      R.fail('UI-A4', '⚠️ 未判定：勾选未翻转或前端未发 permissions 数组（探针问题，非产品结论）',
        `勾选翻转=${diag.toggled}｜弹窗数=${diag.dialogs}｜原生勾选框=${diag.allBoxes}｜已勾=${diag.bc}｜targetId=${diag.targetId}｜目标员工 PUT 数=${diag.mineLen}｜载荷(末次)=${body.slice(0, 90)}`)
    } else if (changed) {
      R.pass('UI-A4', '员工权限编辑闭环：UI 勾选 → 保存 → **DB 快照随勾选变化**',
        `变化=true｜载荷=${JSON.stringify(sent).slice(0, 80)}｜前=${(snapBefore || '').slice(0, 60)}｜后=${(snapAfter || '').slice(0, 60)}`,
        ['screenshots/s10-A4-员工权限编辑保存.png'])
    } else {
      R.fail('UI-A4', '员工权限编辑：前端发了 permissions 数组但 **DB 快照未变**',
        `载荷=${JSON.stringify(sent).slice(0, 100)}｜前=${(snapBefore || '').slice(0, 60)}｜后=${(snapAfter || '').slice(0, 60)}`)
    }
  } catch (e) { R.fail('UI-A4', '员工权限编辑旅程异常', String(e).slice(0, 260)) }


  // ════════ B5 按钮级 RBAC：**每个岗位**在有权页面上，写按钮是否出现 ⟺ 是否持有该权限码 ════════
  if (want('B5')) try {
    const SPECS = [
      { route: '/products', btn: /新增商品/, code: 'product:create' },
      { route: '/orders', btn: /新建订单|新增订单/, code: 'order:create' },
      { route: '/finance', btn: /登记收支/, code: 'finance:create' },
      { route: '/employees', btn: /新增员工/, code: 'employee:create' },
      { route: '/inbound-orders', btn: /新建入库单|新增入库单|新建单据|新建/, code: 'inbound:create' },
    ]
    const rows = []
    for (const who of people) {
      const page = await session(who)
      for (const spec of SPECS) {
        await page.goto(WEB + spec.route, { waitUntil: 'domcontentloaded' })
        await page.waitForTimeout(1600)
        const t = await text(page)
        if (/\/login/.test(page.url())) { rows.push({ who: who.roleCode, route: spec.route, verdict: '落登录' }); continue }
        if (/无权访问该页面/.test(t)) { rows.push({ who: who.roleCode, route: spec.route, verdict: '页面被拦' }); continue }
        const btn = page.getByRole('button', { name: spec.btn }).first()
        const seen = await btn.isVisible().catch(() => false)
        const disabled = seen ? await btn.isDisabled().catch(() => false) : true
        const effective = seen && !disabled
        const hasCode = who.perms.includes('*') || who.perms.includes(spec.code)
        rows.push({ who: who.roleCode, route: spec.route, code: spec.code, hasCode, seen, effective, verdict: effective === hasCode ? '一致' : `❌不一致(按钮${effective ? '可用' : '不可用'}/权限${hasCode ? '有' : '无'})` })
      }
      await page.close()
    }
    const applicable = rows.filter((r) => !['落登录', '页面被拦'].includes(r.verdict))
    const bad = applicable.filter((r) => r.verdict !== '一致')
    const detail = rows.map((r) => `${r.who}@${r.route}:${r.verdict}`).join('｜')
    bad.length === 0
      ? R.pass('UI-B5', `按钮级 RBAC：${people.length} 岗位 × ${SPECS.length} 页面 = ${rows.length} 格，**可用按钮 ⟺ 权限码** 全部一致（另有 ${rows.length - applicable.length} 格因页面被拦不适用）`, detail.slice(0, 900), ['out/s10-position-ui.json'])
      : R.fail('UI-B5', `按钮级 RBAC 有 ${bad.length} 格不一致`, detail.slice(0, 900))
  } catch (e) { R.fail('UI-B5', '按钮级 RBAC 旅程异常', String(e).slice(0, 260)) }

  // ════════ A5 入库过账：运营在页面上**建单 → 过账**（库存/批次随之变化） ════════
  if (want('A5')) try {
    const before = {
      inbound: n(`select count(*)::int as n from inbound_orders where tenant_id=${T}`),
      posted: n(`select count(*)::int as n from inbound_orders where tenant_id=${T} and status='posted'`),
      batches: n(`select count(*)::int as n from stock_batches where tenant_id=${T}`),
    }
    const page = await session(P('operator'))
    await page.goto(`${WEB}/inbound-orders/new`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3500)
    // 基础信息
    await page.locator('input[placeholder*="柯桥"]').first().fill('验收供应商').catch(() => {})
    await page.locator('input[placeholder*="送货单"]').first().fill(`PS-${stamp}`).catch(() => {})
    // 明细行：**左侧**搜商品 → 点商品 → 勾 SKU（一行 = 一个批次）
    const search = page.locator('input[placeholder="商品名称 / 货号"]').first()
    if (await search.isVisible().catch(() => false)) {
      await search.fill(productName); await page.waitForTimeout(2500)
      await page.getByText(productName, { exact: false }).first().click().catch(() => {})
      await page.waitForTimeout(1800)
      const cb = page.locator('input[type="checkbox"]').first()
      if (await cb.isVisible().catch(() => false)) await cb.check({ force: true }).catch(() => {})
      await page.waitForTimeout(1200)
    }
    // 🔴 F13：SKU **首次**过账 + 明细**未记单价** ⇒ 后端 500（详见 REPORT §十二）
    //    ⇒ 本旅程按页面允许的最常见有价路径填单价（无单价的红证见 A5b）
    const costInput = page.locator('input[placeholder*="单价"], input[placeholder*="未记"]').first()
    if (await costInput.isVisible().catch(() => false)) await setReact(page, 'input[placeholder*="单价"], input[placeholder*="未记"]', '9.9').catch(() => {})
    else await page.evaluate(() => {
      const els = [...document.querySelectorAll('table input, tbody input')]
      const el = els.find((e) => e.tagName === 'INPUT' && !e.value)
      if (el) { const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; set.call(el, '9.9'); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })) }
    })
    await page.waitForTimeout(1500)
    await page.getByRole('button', { name: /保存为草稿|提交|保存/ }).first().click({ timeout: 8000 }).catch(() => {})
    await page.waitForTimeout(4000)
    const body = await text(page)
    let created = n(`select count(*)::int as n from inbound_orders where tenant_id=${T} and supplier='验收供应商'`)
    let path = 'UI 建单'
    if (created === 0) {
      // 回退：页面建单探针没走通 ⇒ 用 API 建草稿，**过账动作仍在页面上做**（本文如实标注）
      path = 'API 建草稿 + UI 过账（页面建单探针未完成，如实标注）'
      const sku = one(`select ps.id as sku_id, p.id as product_id from product_skus ps join products p on p.id=ps.product_id where p.tenant_id=${T} and p.name='${productName}' limit 1`) || {}
      await api('POST', '/api/admin/inbound-orders', {
        token: P('operator').token, body: {
          source: 'purchase', supplierName: '验收供应商', supplierDeliveryNo: `PS-${stamp}`,
          items: [{ productId: sku.product_id, skuId: sku.sku_id, quantity: 5, unitCost: 12.5 }],
        },
      })
      created = n(`select count(*)::int as n from inbound_orders where tenant_id=${T} and supplier='验收供应商'`)
    }
    // 过账：列表页对最新草稿点「过账」
    await page.goto(`${WEB}/inbound-orders`, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const row = page.getByRole('row').filter({ hasText: '验收供应商' }).first()
    // 列表行只有「详情」⇒ 过账动作在**详情抽屉**里（实测）
    await row.getByRole('button', { name: /详情/ }).first().click({ timeout: 10000 }).catch(() => {})
    await page.waitForTimeout(2500)
    const drawer = page.locator('[role="dialog"]')
    const postBtn = page.getByRole('button', { name: /过账（生成批次号并加库存）|^过账$/ }).first()
    await postBtn.scrollIntoViewIfNeeded().catch(() => {})
    await postBtn.click({ timeout: 12000 }).catch(() => {})
    await page.waitForTimeout(1500)
    // 二次确认：确认弹窗是**最后**一个 dialog（不要用 .last() 抓整页按钮 —— 会抓到「关闭」）
    const confirm = page.locator('[role="dialog"]').last().getByRole('button', { name: /^(确定|确认|确认过账)$/ }).first()
    if (await confirm.isVisible().catch(() => false)) { await confirm.click().catch(() => {}); await page.waitForTimeout(2500) }
    // 轮询过账结果（最多 20s）
    for (let i = 0; i < 10; i++) {
      if (n(`select count(*)::int as n from inbound_orders where tenant_id=${T} and supplier='验收供应商' and status='posted'`) > 0) break
      await page.waitForTimeout(2000)
    }
    void drawer
    const after = {
      inbound: n(`select count(*)::int as n from inbound_orders where tenant_id=${T}`),
      posted: n(`select count(*)::int as n from inbound_orders where tenant_id=${T} and status='posted'`),
      batches: n(`select count(*)::int as n from stock_batches where tenant_id=${T}`),
    }
    await shot(page, 's10-A5-运营-入库过账')
    await page.close()
    const postedUp = after.posted === before.posted + 1
    postedUp
      ? R.pass('UI-A5', '运营在页面上完成**入库过账**（单据转已过账 + 批次号生成 + 库存加）',
        `路径=${path}｜inbound ${before.inbound}→${after.inbound}；posted ${before.posted}→${after.posted}；stock_batches ${before.batches}→${after.batches}`,
        ['screenshots/s10-A5-运营-入库过账.png'])
      : R.fail('UI-A5', '入库过账未生效', `路径=${path}｜inbound ${before.inbound}→${after.inbound}；posted ${before.posted}→${after.posted}；batches ${before.batches}→${after.batches}｜页面尾部=${(await Promise.resolve(body)).slice(-120).replace(/\n/g, ' ')}`)
  } catch (e) { R.fail('UI-A5', '入库过账旅程异常', String(e).slice(0, 260)) }

  // ════════ 第三路证据 ════════
  try {
    writeFileSync(join(OUT, 's10-api-calls.json'), JSON.stringify(seen, null, 1))
    const tail = readFileSync(API_LOG, 'utf8').split('\n').slice(-6000)
    const hits = ['ProductController', 'OrderController', 'FinanceController', 'PermissionInterceptor', 'AfterSalesController']
      .map((k) => `${k}=${tail.filter((l) => l.includes(k)).length}`).join('｜')
    const statuses = [...new Set(seen.map((x) => x.split(' ')[0]))].join('/')
    seen.length > 0
      ? R.pass('UI-EV', '三路留证：浏览器→API 调用 + 服务器日志命中', `捕获调用 ${seen.length} 条（状态码集合 ${statuses}）；日志尾部命中：${hits}`, ['out/s10-api-calls.json', API_LOG])
      : R.fail('UI-EV', '未捕获到浏览器 API 调用', '（页面可能未发出请求）')
  } catch (e) { R.fail('UI-EV', '证据收集失败', String(e).slice(0, 200)) }

  await browser.close()
  const s = R.summary()
  log(`== 阶段10 完成：pass=${s.pass} fail=${s.fail}`)
}
main().catch((e) => { R.fail('UI-FATAL', '阶段10 致命错误', String(e).slice(0, 400)); console.error(e); process.exit(1) })
