// p4：写面 —— ① 「写按钮随权限显隐」矩阵（同页可读 ⇒ 按钮必须有码才出现）
//                ② 真实页面写面旅程（点按钮 → 填表 → 提交 → DB 落库差）
//
// v1 → v2 修正（本会话实测的 4 条**判据侧**缺陷，全部改为「驱动到底 + 断言与字段对齐」）：
//   · W1：`selectOption({label:'客服'})` 选不中 ⇒ 表单停在「请选择岗位」，DB 自然无行（**假红**）⇒ 改为按 option 文本定位 select。
//   · W2：卡片**真的建成了**，但我的断言按 `question=` 精确匹配了「我填进另一个框的值」⇒ **假红** ⇒ 改为按 created_at 取最新行 + 探针串出现在任一字段。
//   · W3：商品选择弹窗**还在「加载中」**就点了提交 ⇒ 流程没走完 ⇒ 改为等弹窗加载完、选中商品、再提交。
//   · W4：关联订单用了伪造单号（本租户原本 0 订单）⇒ 改为**用 W3 真建出的订单号**串起来。
// 真值源：permissions（DB）+ 权限目录（origin/main），**不读被测读面自证**。
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { OUT, psql, scrub, PROBE, SUBJECT_SHA } from './lib.mjs'
import { launch, newPage, loginEmployeeUi, loginAdminUi, gotoLoaded, shot } from './ui.mjs'

const SESSION = JSON.parse(readFileSync(process.env.A06_SESSION || '/tmp/a06-session.json', 'utf8'))
const TENANT_ID = Number(process.env.TENANT_ID || 25)
const EMP_PWD = 'Migao@2026x'
const stamp = String(Date.now()).slice(-6)

const roles = psql(`select code, name from roles where tenant_id=${TENANT_ID} order by code`)
const permsByRole = Object.fromEntries(psql(
  `select r.code, array_agg(p.code order by p.code) as codes from roles r
   join role_permissions rp on rp.role_id=r.id join permissions p on p.id=rp.permission_id
   where r.tenant_id=${TENANT_ID} group by r.code`).map((r) => [r.code, r.codes]))
const has = (perms, code) => perms.includes('*') || perms.includes(code)

const BUTTON_MATRIX = [
  { path: '/orders', read: 'order:list', write: 'order:create', re: /新增订单/ },
  { path: '/products', read: 'product:list', write: 'product:create', re: /新增商品/ },
  { path: '/after-sales', read: 'after_sales:view', write: 'order:refund', re: /新建工单/ },
  { path: '/knowledge', read: 'knowledge:view', write: 'knowledge:manage', re: /新建知识卡片/ },
  { path: '/inbound-orders', read: 'inbound:view', write: 'inbound:create', re: /新建入库单/ },
  { path: '/employees', read: 'employee:list', write: 'employee:create', re: /新增员工/ },
]

const R = []
const rec = (state, id, name, detail, evidence = []) => R.push({ state, id, name, detail, evidence })
mkdirSync(join(OUT, 'shots'), { recursive: true })

const login = (page, roleCode) => roleCode === 'admin'
  ? loginAdminUi(page, '13800138000')
  : loginEmployeeUi(page, `a06_${roleCode}@${SESSION.tenantCode}`, EMP_PWD)

const fillPh = async (page, sub, value) => {
  await page.locator(`input[placeholder*="${sub}"], textarea[placeholder*="${sub}"]`).first().fill(value, { timeout: 8000 })
}
const clickText = async (page, re, scope = null, opts = {}) => {
  const base = scope || page
  await base.getByRole('button', { name: re }).first().click({ timeout: opts.timeout || 8000 })
}
const toastText = async (page) => page.evaluate(() => {
  const els = Array.from(document.querySelectorAll('[class*="toast"], [class*="Toast"], [role="alert"], [class*="message"], [class*="Message"]'))
  return els.map((e) => (e.textContent || '').trim()).filter(Boolean).slice(0, 6)
})

async function buttonMatrix(browser, role) {
  const perms = permsByRole[role.code] || []
  const { ctx, page } = await newPage(browser)
  const rows = []
  try {
    await login(page, role.code)
    for (const m of BUTTON_MATRIX) {
      if (!has(perms, m.read)) { rows.push({ path: m.path, skipped: '无读码（页面本身被拦，见 p2 负向）' }); continue }
      const { loading } = await gotoLoaded(page, m.path)
      const loc = page.getByRole('button', { name: m.re }).first()
      const cnt = await page.getByRole('button', { name: m.re }).count()
      const visible = cnt > 0 && await loc.isVisible().catch(() => false)
      const expect = has(perms, m.write)
      rows.push({ path: m.path, read: m.read, write: m.write, expectVisible: expect, actualVisible: visible, count: cnt, loading, ok: visible === expect })
    }
    const bad = rows.filter((r) => r.ok === false)
    rec(bad.length === 0 ? 'pass' : 'fail', `P4-BTN:${role.code}`, `写按钮显隐矩阵：${role.name}`,
      `检查 ${rows.filter((r) => r.ok !== undefined).length} 页；不符 ${bad.length} ${JSON.stringify(bad.map((b) => ({ p: b.path, write: b.write, expect: b.expectVisible, actual: b.actualVisible })))}`,
      ['DOM button 可见性', 'out/map.json#prefixes', 'permissions（DB）'])
  } catch (e) {
    rec('fail', `P4-BTN-ERR:${role.code}`, `写按钮矩阵异常：${role.name}`, String(e).slice(0, 300))
  } finally { await ctx.close().catch(() => {}) }
  return { roleCode: role.code, rows }
}

/** 岗位下拉：按 option 文本定位（v1 用 selectOption({label}) 直接失败）。 */
async function selectByOptionText(page, text) {
  for (const s of await page.locator('select').all()) {
    const opts = await s.locator('option').allTextContents()
    const hit = opts.find((o) => o.includes(text))
    if (hit) { await s.selectOption({ label: hit }); return { ok: true, options: opts } }
  }
  return { ok: false, options: [] }
}

async function j1CreateEmployee(browser) {
  const name = `${PROBE}员工${stamp}`
  const username = `a06_probe_${stamp}`
  const phone = `137${String(Date.now()).slice(-8)}`
  const { ctx, page } = await newPage(browser)
  try {
    await login(page, 'admin')
    await gotoLoaded(page, '/employees')
    await clickText(page, /新增员工/)
    await page.waitForTimeout(1200)
    await fillPh(page, '请输入姓名', name)
    await fillPh(page, '请输入手机号', phone)
    await fillPh(page, '员工登录账号', username)
    await fillPh(page, '请输入初始密码', 'Init@123456')
    const sel = await selectByOptionText(page, '客服')
    await page.waitForTimeout(500)
    await clickText(page, /^创建$/)
    await page.waitForTimeout(3000)
    const toasts = await toastText(page)
    const row = psql(`select id, username, phone, position, role, status, permissions::text as perms from users where tenant_id=${TENANT_ID} and username='${username}'`)[0]
    const exp = permsByRole['customer_service'] || []
    const snap = JSON.parse(row?.perms || '[]').sort()
    const same = !!row && JSON.stringify(snap) === JSON.stringify([...exp].sort())
    rec(row ? (same ? 'pass' : 'fail') : 'fail', 'P4-W1', '管理员在「员工管理」页建员工（页面操作 → DB 落库）',
      row ? `DB 落库 users#${row.id} username=${row.username} position=${row.position} status=${row.status}；权限快照(${snap.length}) == 岗位默认权限(${exp.length}) ⇒ ${same}；岗位下拉 option=${JSON.stringify(sel.options.slice(0, 4))}`
          : `DB 无此行（username=${username}）；页面反馈=${JSON.stringify(toasts)}；岗位下拉命中=${sel.ok} options=${JSON.stringify(sel.options.slice(0, 8))}`,
      ['out/shots/w1-employee.png', 'SQL: select * from users where username=…'])
    await shot(page, 'w1-employee')
  } catch (e) {
    rec('fail', 'P4-W1', '管理员建员工旅程异常', String(e).slice(0, 300))
    await shot(page, 'w1-employee-error').catch(() => {})
  } finally { await ctx.close().catch(() => {}) }
  return { created: false }
}

async function j2CreateKnowledge(browser) {
  const tag = `${PROBE}知识${stamp}`
  const { ctx, page } = await newPage(browser)
  try {
    await login(page, 'knowledge_editor')
    await gotoLoaded(page, '/knowledge')
    await clickText(page, /新建知识卡片/)
    await page.waitForTimeout(1200)
    const before = psql(`select count(*)::int as n from knowledge_cards where tenant_id=${TENANT_ID}`)[0]?.n
    await fillPh(page, '如：雪尼尔面料会起球吗', `${tag}问题`)
    await page.locator('select').first().selectOption({ index: 1 }).catch(() => {})
    await fillPh(page, '顾客可能的问法', `${tag}问法`)
    await fillPh(page, 'AI 客服将基于此内容回答', `${tag}回答`)
    await fillPh(page, '如：雪尼尔', `${tag}标签`)
    await page.waitForTimeout(400)
    await clickText(page, /^保存$/)
    await page.waitForTimeout(3000)
    const toasts = await toastText(page)
    const after = psql(`select count(*)::int as n from knowledge_cards where tenant_id=${TENANT_ID}`)[0]?.n
    const row = psql(`select id, question, answer, category, status, created_by from knowledge_cards where tenant_id=${TENANT_ID} order by created_at desc limit 1`)[0]
    const hit = row && JSON.stringify(row).includes(tag)
    rec(hit ? 'pass' : 'fail', 'P4-W2', '知识编辑在「知识库」页建卡片（页面操作 → DB 落库）',
      `建前 ${before} 条 → 建后 ${after} 条；最新行=${JSON.stringify(row)}；含探针串=${hit}；页面反馈=${JSON.stringify(toasts)}`,
      ['out/shots/w2-knowledge.png', 'SQL: select * from knowledge_cards order by created_at desc limit 1'])
    await shot(page, 'w2-knowledge')
  } catch (e) {
    rec('fail', 'P4-W2', '知识卡片旅程异常', String(e).slice(0, 300))
    await shot(page, 'w2-knowledge-error').catch(() => {})
  } finally { await ctx.close().catch(() => {}) }
}

async function j3CreateOrder(browser) {
  const buyer = `${PROBE}下单客户${stamp}`
  const { ctx, page } = await newPage(browser)
  let orderNo = null
  try {
    await login(page, 'sales')
    await gotoLoaded(page, '/orders')
    await clickText(page, /新增订单/)
    await page.waitForTimeout(1500)
    await fillPh(page, '请输入收货人姓名', buyer)
    await fillPh(page, '请输入 11 位手机号', `139${String(Date.now()).slice(-8)}`)
    await fillPh(page, '请输入详细收货地址', '浙江省绍兴市柯桥区测试路 1 号')
    // 商品选择：打开 → 搜索 → 等加载完 → 点**商品按钮**（该弹窗把每个商品渲染成 button，不是表格行）
    // → 关弹窗 → 校验「合计」真的变了（v2 点 tbody tr 点不到 ⇒ 弹窗不关 ⇒ 提交订单永不可点）
    await clickText(page, /点击搜索并选择商品/).catch(() => {})
    await page.waitForTimeout(1500)
    const dlg = page.locator('[role="dialog"]').last()
    const search = dlg.locator('input').first()
    if (await search.count()) { await search.fill('布'); await dlg.getByRole('button', { name: /^搜索$/ }).first().click().catch(() => {}) }
    for (let i = 0; i < 20; i++) { const t = await dlg.innerText().catch(() => ''); if (!/加载中/.test(t)) break; await page.waitForTimeout(800) }
    const productBtns = (await dlg.getByRole('button').allInnerTexts().catch(() => [])).slice(0, 12)
    const firstProduct = dlg.getByRole('button', { name: /布艺面料/ }).first()
    if (await firstProduct.count()) await firstProduct.click({ timeout: 6000 }).catch(() => {})
    await page.waitForTimeout(1000)
    if (await dlg.isVisible().catch(() => false)) await dlg.getByRole('button', { name: /^关闭$/ }).first().click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(1200)
    // 售卖形态改「布料」：按米下单，避开成品帘的「拼接/接高」加工组合闸门
    // （实测：成品帘 1.2×2.6 仍判「拼接 未定价 ⇒ 请先定价再下单」—— 那是产品**有意**的业务闸门，不是缺陷）
    await page.getByRole('button', { name: '布料', exact: true }).first().click().catch(() => {})
    await page.waitForTimeout(1000)
    // 商品级必填（v3 补：截图逐字给出「还差 5 项」= 颜色/宽/高/物流类型/物流公司 ⇒ 逐项补齐再提交）
    const colorNames = ['咖色', '米白', '白色', '灰色', '藏青', '黑色', '棕色', '米色', '浅灰', '深灰', '奶白']
    let colorClicked = null
    for (const n of colorNames) {
      const b = page.getByRole('button', { name: n, exact: true }).first()
      if (await b.count()) { await b.click().catch(() => {}); colorClicked = n; break }
    }
    // 净尺寸：宽 1.2 米（定高买宽 × 褶皱 ⇒ 用料 2.4 米 ≤ 门幅 2.8 ⇒ 不触发「拼接」，避开加工费未定价的业务闸门）
    await page.locator('input[placeholder*="6.6"]').first().fill('1.2').catch(() => {})
    await page.locator('input[placeholder*="2.6"]').first().fill('2.6').catch(() => {})
    await page.locator('[data-testid="logistics-section"] summary').first().click().catch(() => {})
    await page.waitForTimeout(500)
    await page.locator('[data-testid="order-logistics-type"]').first().selectOption({ index: 1 }).catch(() => {})
    await page.locator('[data-testid="logistics-section"] input').last().fill('四季安物流').catch(() => {})
    await page.waitForTimeout(500)
    const totalText = (await page.evaluate(() => (document.body.innerText.match(/合计[\s\S]{0,40}/) || [''])[0])).replace(/\n/g, ' ')
    await shot(page, 'w3-order-form')
    await clickText(page, /提交订单/, null, { timeout: 12000 })
    await page.waitForTimeout(4000)
    const toasts = await toastText(page)
    const validation = (await page.evaluate(() => (document.body.innerText.match(/还差[\s\S]{0,220}/) || [''])[0])).replace(/\n/g, ' | ')
    const row = psql(`select id, order_no, status, total_amount from orders where tenant_id=${TENANT_ID} and customer_name='${buyer}'`)[0]
    orderNo = row?.order_no || null
    rec(row ? 'pass' : 'fail', 'P4-W3', '销售在「订单列表」页新建订单（页面操作 → DB 落库）',
      row ? `DB 落库 orders#${row.id} order_no=${row.order_no} status=${row.status} 金额=${row.total_amount}；选中颜色=${colorClicked}`
          : `DB 无新行；选中颜色=${colorClicked} 合计=${JSON.stringify(totalText)} 校验清单=${JSON.stringify(validation)} 页面反馈=${JSON.stringify(toasts)}`,
      ['out/shots/w3-order-form.png', 'SQL: select * from orders where customer_name=…'])
    await shot(page, 'w3-order-after')
  } catch (e) {
    rec('fail', 'P4-W3', '销售建订单旅程异常', String(e).slice(0, 300))
    await shot(page, 'w3-order-error').catch(() => {})
  } finally { await ctx.close().catch(() => {}) }
  return { orderNo }
}

async function j4CreateTicket(browser, orderNo) {
  const desc = `${PROBE}售后工单${stamp}`
  const { ctx, page } = await newPage(browser)
  try {
    await login(page, 'customer_service')
    await gotoLoaded(page, '/after-sales')
    await clickText(page, /新建工单/)
    await page.waitForTimeout(1500)
    if (!orderNo) {
      rec('skip', 'P4-W4', '客服在「售后工单」页建工单', '前置不成立：本租户无可用订单（W3 未产出订单号）⇒ 关联订单为必填 ⇒ 本趟**未覆盖**（不冒充通过）', [])
      await shot(page, 'w4-ticket-noprecondition')
      return
    }
    await fillPh(page, '请输入订单号/客户姓名/手机号', orderNo)
    await fillPh(page, '请详细描述售后原因', desc)
    await clickText(page, /^退货$/).catch(() => {})
    await page.waitForTimeout(400)
    await shot(page, 'w4-ticket-form')
    await clickText(page, /提交工单/)
    await page.waitForTimeout(4000)
    const toasts = await toastText(page)
    const row = psql(`select id, ticket_no, ticket_type, status, order_id, description from after_sales_tickets where tenant_id=${TENANT_ID} and description='${desc}'`)[0]
    rec(row ? 'pass' : 'fail', 'P4-W4', '客服在「售后工单」页建工单（页面操作 → DB 落库）',
      row ? `DB 落库 after_sales_tickets#${row.id} ticket_no=${row.ticket_no} type=${row.ticket_type} status=${row.status} order_id=${row.order_id}（引用订单 ${orderNo}）`
          : `DB 无新行（引用订单 ${orderNo}）；页面反馈=${JSON.stringify(toasts)}`,
      ['out/shots/w4-ticket-form.png', 'SQL: select * from after_sales_tickets where description=…'])
    await shot(page, 'w4-ticket-after')
  } catch (e) {
    rec('fail', 'P4-W4', '客服建工单旅程异常', String(e).slice(0, 300))
    await shot(page, 'w4-ticket-error').catch(() => {})
  } finally { await ctx.close().catch(() => {}) }
}

async function main() {
  // ONLY=j3,j4 时只跑写面旅程（按钮矩阵与 W1/W2 已在 p4-writes.json v2 留档，避免重复建探针数据）
  const only = (process.env.ONLY || '').split(',').map((s) => s.trim()).filter(Boolean)
  const want = (k) => only.length === 0 || only.includes(k)
  const browser = await launch()
  const btnOut = []
  if (want('btn')) for (const role of roles) btnOut.push(await buttonMatrix(browser, role))
  if (want('w1')) await j1CreateEmployee(browser)
  if (want('w2')) await j2CreateKnowledge(browser)
  let orderNo = null
  if (want('w3')) ({ orderNo } = await j3CreateOrder(browser))
  if (want('w4')) await j4CreateTicket(browser, orderNo)
  await browser.close()

  const residue = psql(`select
      (select count(*) from users where tenant_id=${TENANT_ID} and (username like 'a06%' or nickname like '${PROBE}%')) as a06_users,
      (select count(*) from knowledge_cards where tenant_id=${TENANT_ID}) as knowledge_total,
      (select count(*) from orders where tenant_id=${TENANT_ID}) as orders_total,
      (select count(*) from after_sales_tickets where tenant_id=${TENANT_ID}) as tickets_total`)[0]

  const counts = R.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
  const file = join(OUT, 'p4-writes.json')
  let merged = { at: new Date().toISOString(), subjectSha: SUBJECT_SHA, tenantId: TENANT_ID, stamp, counts, rows: R, buttonMatrix: btnOut, residue, orderNo }
  if (only.length) {
    // 增量跑（ONLY=…）：与既有产物按 id 合并，**不丢**上一趟的行（否则就是"手抄读数与 JSON 分家"）
    try {
      const prev = JSON.parse(readFileSync(file, 'utf8'))
      const byId = new Map(prev.rows.map((r) => [r.id, r]))
      for (const r of R) byId.set(r.id, r)
      merged = { ...prev, ...merged, rows: [...byId.values()], buttonMatrix: btnOut.length ? btnOut : prev.buttonMatrix }
      merged.counts = merged.rows.reduce((a, x) => ({ ...a, [x.state]: (a[x.state] || 0) + 1 }), {})
    } catch { /* 首次跑，无既有产物 */ }
  }
  writeFileSync(file, JSON.stringify(scrub(merged), null, 2))
  console.log('== p4 counts:', JSON.stringify(counts))
  console.log('== 残留读数:', JSON.stringify(residue), 'orderNo=', orderNo)
  for (const x of R) console.log(`  [${x.state}] ${x.id} ${x.name} — ${x.detail.slice(0, 320)}`)
}

main().catch((e) => { console.error('p4 失败:', e); process.exit(1) })
