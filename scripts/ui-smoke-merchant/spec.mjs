// MIGAO 商家后端（admin-web）全面功能冒烟 spec —— 真浏览器 + 真后端 + 商家 persona
// 阶段 1：admin-web 全部页面（33 旅程）。用法：node spec.mjs [--group 名称前缀]
// 环境：BASE_URL（默认 http://127.0.0.1:3001）、OUT_DIR（截图/报告输出目录）、PHONE、SMS_CODE
// case_ids: UI-014, UI-016（admin-web 全站冒烟，视觉/布局旅程）
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { createRequire } from 'node:module'
// 判据最小单元（issue #4226）：加工单号**形态**判据 + 404 探测豁免的**结构化**判据。
// 抽到同目录纯函数模块的理由：它们的可信度要能单独验证（见 criteria.test.mjs，node:test 无新依赖）。
import { ORDER_NO_SHAPE, matchProcessingOrderNo, isConsoleProbe404, isProbe404Exempt } from './criteria.mjs'

// playwright 依赖挂在仓库 tests/ 目录（worktree 内未安装，统一用主仓库 tests/node_modules）
const REPO_ROOT = process.env.REPO_ROOT || join(import.meta.dirname, '..', '..')
const { chromium } = createRequire(join(REPO_ROOT, 'tests', 'package.json'))('playwright')

const BASE = process.env.BASE_URL || 'http://127.0.0.1:3001'
// 管理端 API（node 侧直连，见 adminApi 的注释说明为什么不从页面内 fetch）
const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8090'
const OUT = process.env.OUT_DIR || '/tmp/ui-smoke/out'
const PHONE = process.env.PHONE || '13800138000'
const SMS_CODE = process.env.SMS_CODE || '123456'
const GROUP = process.argv.includes('--group') ? process.argv[process.argv.indexOf('--group') + 1] : ''
mkdirSync(OUT, { recursive: true })
mkdirSync(join(OUT, 'screenshots'), { recursive: true })

const results = []
const failReasons = new Map()

// ────────────────────────── 框架 ──────────────────────────
function journey(name, opts = {}) {
  return async (page) => {
    if (GROUP && !name.startsWith(GROUP)) {
      // 过滤掉的旅程返回哨兵，避免调用方解构崩溃
      return { page, rec: null, done: async () => null, skipped: true }
    }
    const rec = { journey: name, pass: true, errors: [], notes: [], evidence: [] }
    results.push(rec)
    const errs = []
    page.removeAllListeners('console')
    page.removeAllListeners('pageerror')
    const onConsole = (msg) => {
      if (msg.type() === 'error') errs.push(`[console.error] ${msg.text().slice(0, 300)}`)
    }
    const onPageError = (err) => errs.push(`[pageerror] ${String(err).slice(0, 300)}`)
    page.on('console', onConsole)
    page.on('pageerror', onPageError)
    const done = async (ok, why, ev) => {
      page.removeListener('console', onConsole)
      page.removeListener('pageerror', onPageError)
      rec.pass = rec.pass && ok
      if (!ok && why) { rec.errors.push(why); failReasons.set(name, why) }
      if (ev) rec.evidence.push(ev)
      if (errs.length) { rec.errors.push(...errs); rec.pass = false }
      if (opts.screenshot !== false) {
        const shot = join(OUT, 'screenshots', `${name}.png`)
        try { await page.screenshot({ path: shot, fullPage: false }) } catch {}
        rec.evidence.push(shot)
      }
      if (rec.pass) { console.log(`✅ ${name}`) } else { console.log(`❌ ${name}\n   ${rec.errors.join('\n   ')}`) }
      return rec
    }
    return { page, done, rec }
  }
}

// 通用断言工具
const expectText = async (page, text, opts = { exact: false }) => {
  const loc = opts.exact ? page.getByText(text, { exact: true }) : page.getByText(text)
  await loc.first().waitFor({ state: 'visible', timeout: 8000 })
  return loc.first()
}

async function nav(page, path, waitText) {
  await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 20000 })
  if (waitText) await expectText(page, waitText)
}

async function safeClick(page, locator, label) {
  await locator.waitFor({ state: 'visible', timeout: 8000 })
  await locator.click()
}

// 等元素出现（返回 true/false，超时**不抛**、返回 false）—— issue #4226②：
// 「定长 sleep 后单次 isVisible()」在真浏览器上偶发不可见 ⇒ 假红（`17-order-ship` 被
// 加工单守卫阻断就是这么来的）。判定「页面/按钮是否就位」一律走本助手。
const waitVisible = (locator, timeout) =>
  locator.waitFor({ state: 'visible', timeout }).then(() => true).catch(() => false)

// toast 校验（antd/message 样式：出现即可）
async function expectToast(page, text) {
  await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout: 6000 }).catch(() => {})
}

// 管理端 API（node 侧直连，复用浏览器会话的登录态）。
// 为什么不从页面内 fetch：access_token 是 HttpOnly+Secure+SameSite=Strict cookie，
// 浏览器在 http 跨端口（3003 → 809x）下**不发**它 ⇒ 页面内 fetch 必 401（实测）；
// node 侧显式带 Cookie 头则 200，且无 CORS 参与、鉴权主体与 UI 会话是同一用户/租户。
async function adminApi(page) {
  const at = (await page.context().cookies()).find((c) => c.name === 'access_token')
  if (!at?.value) throw new Error('未取到 access_token cookie（浏览器未登录）')
  const call = async (method, path, body) => {
    const res = await fetch(API_BASE + path, {
      method,
      headers: { 'Content-Type': 'application/json', Cookie: `access_token=${at.value}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const text = await res.text()
    if (!res.ok) throw new Error(`${method} ${path} → HTTP ${res.status}：${text.slice(0, 200)}`)
    return JSON.parse(text)
  }
  return { get: (p) => call('GET', p), post: (p, b) => call('POST', p, b) }
}

// 登录态自补：`--group 32-` 会把 01-login 一并过滤掉 ⇒ 本旅程单跑时自补一次 UI 登录
// （全量跑时 cookie 已在，直接跳过，不重复发码）
async function ensureLoggedIn(page) {
  if ((await page.context().cookies()).some((c) => c.name === 'access_token')) return
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 25000 })
  await expectText(page, '手机号登录')
  await page.fill('#phone', PHONE)
  await safeClick(page, page.getByRole('button', { name: /获取验证码/ }), '获取验证码')
  await page.waitForTimeout(1200)
  await page.fill('#code', SMS_CODE)
  await safeClick(page, page.getByRole('button', { name: /登\s*录|登录/ }).last(), '登录')
  await page.waitForURL('**/dashboard**', { timeout: 20000 })
}

// ────────────────────────── 登录 ──────────────────────────
async function loginJourney(browser) {
  const page = await browser.newPage()
  const h = await journey('01-login')(await Promise.resolve(page))
  try {
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 20000 })
    await expectText(page, '手机号登录')
    await page.fill('#phone', PHONE)
    await safeClick(page, page.getByRole('button', { name: /获取验证码/ }), '获取验证码')
    await page.waitForTimeout(800)
    await page.fill('#code', SMS_CODE)
    await safeClick(page, page.getByRole('button', { name: /登\s*录|登录/ }), '登录')
    // 登录成功后跳转 /dashboard
    await page.waitForURL('**/dashboard**', { timeout: 15000 })
    await expectText(page, '经营看板')
    // 会话保持：刷新后仍在看板（仍登录）
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForURL('**/dashboard**', { timeout: 8000 })
    await expectText(page, '经营看板')
    await h.done(true, '', 'login → /dashboard，刷新后会话保持')
  } catch (e) {
    await h.done(false, `登录失败: ${String(e).slice(0, 300)}`)
  }
  return page
}

// ────────────────────────── 看板 ──────────────────────────
async function dashboardJourney(page) {
  const h = await journey('02-dashboard')(page)
  try {
    await nav(page, '/dashboard', '经营看板')
    // 统计卡片：数字非空（拦截 stats API 或直接读 DOM 数字）
    const statCards = page.locator('.grid').first()
    await statCards.waitFor({ state: 'visible', timeout: 8000 })
    const cardTexts = await page.locator('text=/^[¥0-9.,万]+$/').allTextContents()
    const digits = await page.evaluate(() => {
      const body = document.body.innerText
      const nums = body.match(/\d+/g) || []
      return nums.length
    })
    if (digits === 0) throw new Error('看板无任何数字渲染')
    await h.done(true, '', `看板渲染数字片段: ${cardTexts.slice(0, 5).join('|')}`)
  } catch (e) {
    await h.done(false, `看板失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 每日简报 ──────────────────────────
async function briefingJourney(page) {
  const h = await journey('03-briefing')(page)
  try {
    await nav(page, '/briefing', '每日经营简报')
    await page.waitForTimeout(1500)
    // 日报生成（若已有今日简报则直接渲染；无则点生成）
    const genBtn = page.getByRole('button', { name: /生成|立即生成|重新生成/ }).first()
    if (await genBtn.isVisible().catch(() => false)) {
      await genBtn.click()
      await page.waitForTimeout(4000)
    }
    const hasContent = await page.evaluate(() => document.body.innerText.length)
    if (hasContent < 50) throw new Error('简报页几乎空白')
    await h.done(true, '', `简报页渲染，body 文本长度 ${hasContent}`)
  } catch (e) {
    await h.done(false, `简报失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 智能客服 ──────────────────────────
async function agentWorkspaceRedirect(page) {
  const h = await journey('04-agent-workspace-redirect')(page)
  try {
    await nav(page, '/agent-workspace', '在线接待')
    await page.waitForURL('**/agent-workspace/human-sessions**', { timeout: 8000 })
    await h.done(true, '', '重定向到 /agent-workspace/human-sessions')
  } catch (e) {
    await h.done(false, `重定向失败: ${String(e).slice(0, 300)}`)
  }
}

async function humanSessions(page) {
  const h = await journey('05-human-sessions')(page)
  try {
    await nav(page, '/agent-workspace/human-sessions', '在线接待')
    await page.waitForTimeout(1500)
    // ai-agent 未起时为空态/错误态但不白屏
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 20) throw new Error('页面空白')
    await h.done(true, '', '在线接待页渲染（ai-agent 未起，空态）— UI-only')
  } catch (e) {
    await h.done(false, `在线接待失败: ${String(e).slice(0, 300)}`)
  }
}

async function agentSessions(page) {
  const h = await journey('06-agent-sessions')(page)
  try {
    await nav(page, '/agent-workspace/sessions', '')
    await page.waitForTimeout(1500)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 20) throw new Error('页面空白')
    await h.done(true, '', '会话历史页渲染（ai-agent 未起，空态）— UI-only')
  } catch (e) {
    await h.done(false, `会话历史失败: ${String(e).slice(0, 300)}`)
  }
}

async function chatPage(page) {
  const h = await journey('07-chat')(page)
  try {
    await nav(page, '/chat', '')
    await page.waitForTimeout(1500)
    const input = page.locator('textarea, input[type="text"]').first()
    const hasInput = await input.isVisible().catch(() => false)
    if (!hasInput) throw new Error('对话输入框不可见')
    await h.done(true, '', '对话页输入框可用（ai-agent 未起）— UI-only')
  } catch (e) {
    await h.done(false, `对话页失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 商品 ──────────────────────────
async function productsList(page) {
  const h = await journey('08-products-list')(page)
  try {
    await nav(page, '/products', '商品列表')
    await page.waitForTimeout(1500)
    // 列表有行（种子/存量商品）
    const rows = page.locator('tbody tr, [class*="Table"] [class*="row"], [role="row"]')
    const n = await rows.count().catch(() => 0)
    if (n === 0) {
      // 允许空列表（干净环境），但标题必须渲染
      const title = await page.getByText('商品列表').first().isVisible().catch(() => false)
      if (!title) throw new Error('商品列表页标题不可见')
      await h.done(true, '列表为空（允许），仅验证渲染', `rows=${n}`)
      return
    }
    await h.done(true, '', `商品列表渲染 ${n} 行`)
  } catch (e) {
    await h.done(false, `商品列表失败: ${String(e).slice(0, 300)}`)
  }
}

async function productsNew(page) {
  const h = await journey('09-products-new')(page)
  try {
    await nav(page, '/products/new', '')
    await page.waitForTimeout(1800)
    // SKU 矩阵区域：规格尺寸区
    const widthSection = page.locator('text=规格尺寸').first()
    await widthSection.waitFor({ state: 'visible', timeout: 8000 })
    // 添加一行规格尺寸（默认无行，需先添加才能看到门幅下拉）
    const addBtns = page.locator('button[title="添加"]')
    const n = await addBtns.count()
    if (n < 2) throw new Error('未找到规格尺寸添加按钮')
    await addBtns.nth(n - 1).click()  // 最后一个 title=添加 属于规格尺寸区（前面是售卖方式）
    await page.waitForTimeout(800)
    // 门幅下拉（aria-label=规格尺寸）：#3641 值/显示分离 —— 选项 label='2.8米'、value=canonical '2.8'
    const dwSelect = page.locator('select[aria-label="规格尺寸"]').first()
    await dwSelect.waitFor({ state: 'visible', timeout: 6000 })
    const optInfo = await dwSelect.evaluate((s) => Array.from(s.options).map(o => `${o.value}|${o.text}`))
    const has28miLabel = optInfo.some(o => o.endsWith('|2.8米'))
    const hasBare28 = optInfo.some(o => o.endsWith('|2.8'))
    if (!has28miLabel) throw new Error(`门幅下拉缺 '2.8米' 选项: ${JSON.stringify(optInfo)}`)
    if (hasBare28) throw new Error(`门幅下拉存在裸 '2.8' 显示选项（第二种写法）: ${JSON.stringify(optInfo)}`)
    // 选中 '2.8米' → 落表单的值应为 canonical '2.8'
    await dwSelect.selectOption({ label: '2.8米' })
    const storedValue = await dwSelect.inputValue()
    if (storedValue !== '2.8') throw new Error(`选中 2.8米 后表单值应为 canonical '2.8'，实际 '${storedValue}'`)
    // 真实建品（草稿）：标题必填即可提交；提交后列表可见 → 结果闭环
    const pname = `冒烟SKU商品${Date.now()}`
    await page.locator('input[placeholder*="最多可输入"], input[placeholder*="标题"]').first().fill(pname).catch(async () => {
      await page.locator('form input').first().fill(pname)
    })
    // 选一个分类（草稿无分类会触发后端 category_id FK 500，另记为后端发现；走查用正常路径）
    const catSelect = page.locator('select').first()
    const catOpts = await catSelect.locator('option').allTextContents().catch(() => [])
    const catIdx = catOpts.findIndex(t => t && !t.includes('请选择'))
    if (catIdx > 0) await catSelect.selectOption({ index: catIdx })
    await page.getByRole('button', { name: /存草稿|存为草稿/ }).first().click().catch(() => {})
    await page.waitForTimeout(2500)
    await nav(page, '/products', '商品列表')
    await page.waitForTimeout(1800)
    const visible = await page.locator(`text=${pname}`).first().isVisible().catch(() => false)
    if (!visible) throw new Error('新建商品未出现在列表（结果不可见）')
    await h.done(true, '', `门幅 值/显示分离 ✓(${JSON.stringify(optInfo)}→'${storedValue}') + 建品可见 ✓(${pname})`)
  } catch (e) {
    await h.done(false, `新建商品页失败: ${String(e).slice(0, 300)}`)
  }
}

async function productDetail(page) {
  const h = await journey('10-product-detail')(page)
  try {
    // 取列表第一行点击进详情（ProductTable 行为点击跳转，非 <a>）
    await nav(page, '/products', '商品列表')
    await page.waitForTimeout(1800)
    const rows = page.locator('tbody tr, [role="row"]')
    const n = await rows.count()
    if (n === 0) throw new Error('商品列表 0 行，无商品可进详情')
    // 行内「查看」按钮跳详情；草稿行无「查看」（仅编辑/删除），故取第一个有查看按钮的行
    const viewBtn = page.locator('tbody tr button:has-text("查看"), [role="row"] button:has-text("查看")').first()
    await viewBtn.waitFor({ state: 'visible', timeout: 6000 })
    await viewBtn.click()
    await page.waitForTimeout(1800)
    const url = page.url()
    if (!/\/products\/[^/]+$/.test(url)) throw new Error(`点击行未跳转详情，仍在 ${url}`)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 50) throw new Error('详情页空白')
    await h.done(true, '', `商品详情渲染（${url}）`)
  } catch (e) {
    await h.done(false, `商品详情失败: ${String(e).slice(0, 300)}`)
  }
}

async function productEdit(page, targetId) {
  const h = await journey('11-product-edit-doorwidth')(page)
  try {
    // 用种子/新建的门幅='2.8' 商品验证回显
    if (!targetId) { await h.done(false, '无目标商品（需先建门幅 2.8 商品）'); return }
    await nav(page, `/products/${targetId}/edit`, '')
    await page.waitForTimeout(1800)
    // 门幅下拉：显示 '2.8米'（label），不空白、无第二种写法
    const wState = await page.evaluate(() => {
      const sel = document.querySelector('select[aria-label="规格尺寸"]')
      if (!sel) return []
      const opts = Array.from(sel.options)
      return [{ value: sel.value, options: opts.map(o => `${o.value}|${o.text}`) }]
    })
    if (wState.length === 0) throw new Error('未找到门幅下拉')
    const dw = wState[0]
    const valueOk = dw.value === '2.8' || dw.value === '2.8米'
    const labelOk = dw.options.some(o => o.endsWith('|2.8米'))
    if (!valueOk || !labelOk) throw new Error(`门幅回显异常: ${JSON.stringify(dw)}`)
    if (dw.options.some(o => o.endsWith('|2.8'))) throw new Error('存在裸 2.8 显示选项（第二种写法）')
    await h.done(true, '', `门幅下拉回显: value=${dw.value}, 选项=${JSON.stringify(dw.options)}`)
  } catch (e) {
    await h.done(false, `门幅回显失败: ${String(e).slice(0, 300)}`)
  }
}


// ────────────────────────── 加工项管理 ──────────────────────────
async function processingJourney(page) {
  const h = await journey('12-processing')(page)
  const uniq = `冒烟加工项${Date.now()}`
  try {
    await nav(page, '/processing', '加工项管理')
    await page.waitForTimeout(1200)
    // 新建
    const addBtn = page.getByRole('button', { name: /新增加工项|新建加工项|添加加工项/ }).first()
    await safeClick(page, addBtn, '新增加工项')
    const dlg = page.locator('[role="dialog"], [class*="Modal"], [class*="modal"]').first()
    await dlg.waitFor({ state: 'visible', timeout: 6000 }).catch(() => {})
    await page.fill('input[placeholder*="名称"], input[placeholder*="加工项"], input[id*="name"], input[name="name"]', uniq).catch(async () => {
      await page.locator('form input').first().fill(uniq)
    })
    // 计价方式（per_meter 默认/选择）
    const pricingSelect = page.locator('select').first()
    await pricingSelect.selectOption({ label: /按购买米数计价/ }).catch(async () => {
      const opt = page.locator('option', { hasText: '按购买米数计价' }).first()
      await pricingSelect.selectOption({ index: await opt.evaluate(o => o.index).catch(() => 0) })
    })
    // 价格
    const priceInput = page.locator('input[placeholder*="价格"], input[name="unitPrice"], input[type="number"]').first()
    await priceInput.fill('15.5')
    // 提交
    await page.getByRole('button', { name: /确 定|保存|提交|创建/ }).last().click()
    await page.waitForTimeout(1500)
    // 结果可见：列表出现新建项（名称/价格）
    const row = page.locator(`text=${uniq}`).first()
    await row.waitFor({ state: 'visible', timeout: 8000 })
    const rowText = await row.locator('xpath=ancestor::tr[1]').innerText().catch(() => '')
    if (!/15\.5/.test(rowText)) recNote(h, '列表行未见价格 15.5，可能列名不同')
    // 编辑：只改名（部分更新），价格应保留
    await page.locator(`text=${uniq}`).first().click()
    await page.waitForTimeout(1000)
    const editBtn = page.getByRole('button', { name: /编辑/ }).first()
    if (await editBtn.isVisible().catch(() => false)) {
      await editBtn.click()
      await page.waitForTimeout(800)
      const nameInput = page.locator('form input, input[placeholder*="名称"]').first()
      await nameInput.fill(uniq + '改')
      await page.getByRole('button', { name: /确 定|保存|提交/ }).last().click()
      await page.waitForTimeout(1500)
      const edited = page.locator(`text=${uniq}改`).first()
      await edited.waitFor({ state: 'visible', timeout: 8000 })
    }
    // 启停 toggle（PP-007/PP-008：状态开关）
    const toggle = page.locator('button[role="switch"], [class*="toggle"], [class*="switch"]').first()
    const toggleSeen = await toggle.isVisible().catch(() => false)
    // 删除
    await page.locator(`text=${uniq}改`).first().click()
    await page.waitForTimeout(800)
    const delBtn = page.getByRole('button', { name: /删除/ }).first()
    if (await delBtn.isVisible().catch(() => false)) {
      await delBtn.click()
      await page.getByRole('button', { name: /确认删除|确定|确认/ }).last().click().catch(() => {})
      await page.waitForTimeout(1200)
    }
    await h.done(true, '', `加工项 新建→列表可见→编辑→删除 完成；启停toggle可见=${toggleSeen}`)
  } catch (e) {
    await h.done(false, `加工项旅程失败: ${String(e).slice(0, 400)}`)
  }
}
function recNote(h, note) { h.rec.notes.push(note) }

// ────────────────────────── 分类管理 ──────────────────────────
async function categoriesJourney(page) {
  const h = await journey('13-categories')(page)
  const uniq = `冒烟分类${Date.now()}`
  try {
    await nav(page, '/categories', '分类管理')
    await page.waitForTimeout(1200)
    const addBtn = page.getByRole('button', { name: /新增分类|添加分类|新建分类/ }).first()
    if (await addBtn.isVisible().catch(() => false)) {
      await addBtn.click()
      await page.waitForTimeout(600)
      await page.locator('input').first().fill(uniq)
      await page.getByRole('button', { name: /添加|保存|确 定|创建/ }).last().click()
      await page.waitForTimeout(1200)
      await page.locator(`text=${uniq}`).first().waitFor({ state: 'visible', timeout: 6000 })
      // 删除：定位新建分类所在行的删除按钮（避免误删他行/422）
      const myRow = page.locator('div.group').filter({ hasText: uniq }).first()
      const delBtn = myRow.locator('button[title="删除"]').first()
      if (await delBtn.isVisible().catch(() => false)) {
        await delBtn.click()
        await page.waitForTimeout(800)
        const confirmBtn = page.locator('[role="dialog"] button').filter({ hasText: /删除/ }).last()
        if (await confirmBtn.isVisible().catch(() => false)) {
          await confirmBtn.click()
          await page.waitForTimeout(1500)
        }
        const gone = (await page.locator(`text=${uniq}`).count()) === 0
        if (!gone) { h.rec.notes.push('分类删除未生效（可能被业务校验拦截，见 console 422）') }
      } else {
        h.rec.notes.push('新建分类行未见删除按钮')
      }
      await h.done(true, '', '分类 新建→可见→行内删除')
    } else {
      await h.done(true, '未见新增按钮（可能入口不同），仅验证渲染', '')
    }
  } catch (e) {
    await h.done(false, `分类旅程失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 订单列表 ──────────────────────────
async function ordersListJourney(page) {
  const h = await journey('14-orders-list')(page)
  try {
    await nav(page, '/orders', '订单列表')
    await page.waitForTimeout(1500)
    const rows = page.locator('tbody tr, [role="row"]')
    const n = await rows.count().catch(() => 0)
    if (n === 0) { await h.done(false, '订单列表 0 行'); return }
    // 分页：翻到下一页
    const nextBtn = page.getByRole('button', { name: /下一页|next/ }).first()
    if (await nextBtn.isVisible().catch(() => false)) {
      await nextBtn.click()
      await page.waitForTimeout(1200)
      await h.done(true, '', `订单列表 ${n} 行，下一页可点击`)
    } else {
      await h.done(true, '', `订单列表 ${n} 行（无分页按钮或单页）`)
    }
  } catch (e) {
    await h.done(false, `订单列表失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 新建订单（UI 旅程） ──────────────────────────
async function ordersNewJourney(page) {
  const h = await journey('15-orders-new')(page)
  try {
    await nav(page, '/orders/new', '')
    await page.waitForTimeout(1800)
    // 客户信息（收货人/手机号/地址）
    await page.fill('input[placeholder*="收货人姓名"]', '冒烟测试员')
    await page.fill('input[placeholder*="手机号"]', '13900001111')
    await page.fill('input[placeholder*="收货地址"]', '杭州市西湖区冒烟路 1 号')
    // 打开商品选择弹窗（搜索框在弹窗内）
    const pickBtn = page.getByRole('button', { name: /选择商品/ }).first()
    await pickBtn.waitFor({ state: 'visible', timeout: 8000 })
    await pickBtn.click()
    await page.waitForTimeout(800)
    // 弹窗内搜索商品
    const searchInput = page.locator('[role="dialog"] input[placeholder*="搜索商品"]').first()
    await searchInput.waitFor({ state: 'visible', timeout: 6000 })
    await searchInput.fill('遮光窗帘')
    await page.getByRole('button', { name: /^搜索$/ }).click().catch(async () => {
      await page.locator('[role="dialog"] button:has-text("搜索")').click()
    })
    await page.waitForTimeout(1500)
    // 选中第一个商品结果
    const result = page.locator('[role="dialog"] button').filter({ hasText: /遮光窗帘/ }).first()
    if (await result.isVisible().catch(() => false)) {
      await result.click()
      await page.waitForTimeout(2000)
    } else {
      throw new Error('商品搜索结果为空（未找到 遮光窗帘）')
    }
    // 提交订单
    await page.getByRole('button', { name: /提交订单/ }).first().click().catch(() => {})
    await page.waitForTimeout(2500)
    const url = page.url()
    if (url.includes('/orders')) {
      await h.done(true, '', `新建订单提交后跳转 ${url}`)
    } else {
      const toastOk = await page.getByText('订单创建成功').first().isVisible().catch(() => false)
      if (toastOk) { await h.done(true, '', '新建订单 toast 成功') }
      else {
        const errVisible = await page.getByText(/请完善|请输入|请选择|不能为空/).first().isVisible().catch(() => false)
        await h.done(errVisible, `提交未成功且无校验提示: ${url}`, '表单校验提示可见')
      }
    }
  } catch (e) {
    await h.done(false, `新建订单失败: ${String(e).slice(0, 400)}`)
  }
}

// ────────────────────────── 订单详情 + 加工单（重点） ──────────────────────────
async function orderDetailJourney(page, orderId) {
  const h = await journey('16-order-detail-processing-order')(page)
  // 加工单「开始加工/加工完成」用 window.confirm —— 必须接受，否则流转被自动拒绝
  page.on('dialog', (d) => d.accept())
  // ③ 结构化 404 判据（issue #4226③）：加工单块挂载时会先 GET /processing-orders/{orderId} 探测
  // （未生成时后端 404，组件 catch → notFound → 展示生成按钮）——该 404 是预期探测，豁免但不隐藏（记 note）。
  // ⚠️ 豁免必须按 `response.status()` 收集的**结构化**事实判定：旧写法扫「错误消息文本里含 404」
  // 会把旅程**自身**抛出、文案里恰好带 404 的错误一并豁免 ⇒ 假绿。
  const responses = []
  const onResponse = (r) => { if (r.status() === 404) responses.push({ url: r.url(), status: r.status() }) }
  page.on('response', onResponse)
  const origDone = h.done
  h.done = async (ok, why, ev) => {
    page.removeListener('response', onResponse)
    const res = await origDone(ok, why, ev)
    // 仅当「失败原因**全部**是这次真探测在 console 打出的文案」且确有对应结构化 404 响应时才豁免
    if (isProbe404Exempt(res.errors, responses)) {
      const n = res.errors.filter(isConsoleProbe404).length
      res.notes.push(`加工单未生成前 GET /processing-orders/{orderId} 404 探测（预期，${n} 条 console 文案；结构化 404 响应 ${responses.length} 次）`)
      res.errors = res.errors.filter((e) => !isConsoleProbe404(e))
      if (res.errors.length === 0) { res.pass = true; console.log(`✅ ${h.rec.journey}（404 探测豁免）`) }
    }
    return res
  }
  try {
    if (!orderId) { await h.done(false, '无目标订单'); return }
    await nav(page, `/orders/${orderId}`, '')
    // 确认收款（pending → confirmed；#3583 闸门语义：需显式确认弹窗）
    const payBtn = page.getByRole('button', { name: /确认付款/ }).first()
    if (await waitVisible(payBtn, 12000)) {
      await payBtn.click()
      // 确认弹窗（闸门）
      const confirmBtn = page.getByRole('button', { name: /确 认|确认付款|确定/ }).last()
      if (await waitVisible(confirmBtn, 6000)) {
        await confirmBtn.click()
      }
    }
    // 加工单生成（confirmation 门禁的 UI 侧：按钮 + 结果可见）
    const genBtn = page.getByRole('button', { name: /生成加工单/ }).first()
    if (await waitVisible(genBtn, 12000)) {
      await genBtn.click()
    }
    // ① 加工单块出现：**在加工单块容器内**取单号（issue #4226①：不猜前缀，也不全页乱匹配）。
    // 真实加工单号前缀是 JG-（实测 JG-20260918-9049），旧正则 /PO-…|PG-…/ 永不命中
    // ⇒ 证据恒为「加工单可见=false」= 空判据。容器 = ProcessingOrderBlock 的打印区
    // `.po-print-area`（该组件内唯一，po 为 null 时不渲染）；组件无 data-testid 且前端不属本包所有权。
    const poBlock = page.locator('.po-print-area').first()
    const poVisible = await waitVisible(poBlock, 12000)
    const poNo = poVisible ? matchProcessingOrderNo(await poBlock.textContent().catch(() => '')) : null
    // 状态流转：发加工 → 开始加工 → 加工完成
    let flowDone = ''
    for (const [btn, expectText] of [['发加工', '已发加工'], ['开始加工', '加工中'], ['加工完成', '加工完成']]) {
      const b = page.getByRole('button', { name: new RegExp(btn) }).first()
      // ② 等按钮出现（不是定长 sleep 后单次 isVisible）：偶发不可见会让加工单停在未完成态，
      // 下游 `17-order-ship` 被「须先完成加工单后再发货」守卫阻断（A/B 两轮均红 = 噪声淹没真回归）
      if (!(await waitVisible(b, 12000))) { flowDone += ` [${btn}不可见]`; break }
      await b.click()
      if (btn === '发加工') {
        // 内联表单：加工方/交期（等表单就位再填，不再定长 sleep 后盲填）
        const processor = page.locator('input[placeholder*="加工方"]').first()
        if (await waitVisible(processor, 8000)) await processor.fill('冒烟加工厂').catch(() => {})
        const issueBtn = page.getByRole('button', { name: /确认发加工/ }).first()
        if (await waitVisible(issueBtn, 8000)) await issueBtn.click().catch(() => {})
      }
      // 效果层断言（issue #4305）：旧写法断言**全页文本**「已发加工」是**空判据** ——
      // 加工单块的状态时间线恒含四个步骤文案（已生成→已发加工→加工中→加工完成），
      // 无论实际状态如何都能命中（假绿）。改判两件真效果：
      //   ① `.po-print-area` 内的**状态徽标**（该容器内唯一的 `span.bg-primary-50`）逐字等于期望；
      //   ② **按钮切换**（按钮由状态驱动渲染）：发加工后「发加工」消失、「开始加工」出现，依此类推。
      const badge = poBlock.locator('span.bg-primary-50').first()
      const badgeText = (await waitVisible(badge, 12000)) ? ((await badge.textContent()) ?? '').trim() : ''
      const badgeOk = badgeText === expectText
      const nextBtn = { 发加工: '开始加工', 开始加工: '加工完成', 加工完成: null }[btn]
      const switched = nextBtn
        ? await waitVisible(page.getByRole('button', { name: new RegExp(nextBtn) }).first(), 12000)
        : true
      flowDone += ` [${btn}→徽标「${badgeText || '未取到'}」${badgeOk ? '✓' : '✗期望' + expectText};按钮切换${switched ? '✓' : '✗'}]`
      if (!badgeOk || !switched) {
        throw new Error(
          `[${btn}] 效果层断言未过：状态徽标=「${badgeText}」（期望「${expectText}」）、按钮切换=${switched}`,
        )
      }
    }
    if (!poVisible || !poNo) throw new Error(`加工单块/单号未出现（订单 ${orderId}：生成后 12s 内 ${poVisible ? '块已见但单号不匹配' : `未见 .po-print-area 块`} ${ORDER_NO_SHAPE.source}；流转${flowDone || '未开始'}）`)
    await h.done(true, '', `加工单生成+流转: ${flowDone}; 加工单 ${poNo} 可见=${poVisible}`)
  } catch (e) {
    await h.done(false, `订单详情失败: ${String(e).slice(0, 400)}`)
  }
}

// ────────────────────────── 生产报工正向旅程（#4186） ──────────────────────────
/**
 * 加工单二维码 + 计件**正向**旅程（issue #4186 收口要求）。
 *
 * 原「qr_token 为空 ⇒ 任务卡落占位」这一半自洽，但「非空 ⇒ 出二维码」这一半**从未被行使**；
 * 本旅程把它固化成可复跑的正向判据（每条断言锚定具体值/存在性 + 语义，不写「不抛异常就算过」）：
 *  ① API 建一张含加工项的订单（独立数据，与 16- 旅程同量级，不动存量）
 *  ② UI：订单详情 → 「确认付款」（pending→confirmed）→ 「生成加工单」
 *     （未确认付款时「生成加工单」按钮不出现 —— 这是本旅程第一步必须做的原因）
 *  ③ GET /api/admin/production/orders/{orderId}/operations：qr_token 为 32 位十六进制 **且** positions 非空
 *  ④ 生产明细页 DOM **计数**真值：task-card-qr ≥ 1、task-card-qr-placeholder = 0、operation-row-* ≥ 1
 *  ⑤ 报工一次（normal）→ 刷新后进度不再 0%、计件合计 > 0 且 piecework-empty 不存在
 *
 * ⚠️ 任务卡是 `display:none`（打印才显形）⇒ 用 innerText 判「页面含二维码」会**假阴性**，
 *    DOM 计数（locator.count()）才是真值。
 */
async function productionQrJourney(page) {
  // ⚠️ 补登录态**必须早于 journey()**（即早于本旅程的 console 监听窗口）：
  // `--group 32-` 会把 01-login 一并过滤掉，而补登录时 60s 防刷窗口可能正生效
  // （另一会话刚为同一手机号发过码）⇒ POST /api/auth/sms-code 回 400，
  // 该 400 与本次要固化的链路无关，落在监听窗口内就会**把全绿的旅程翻成红**（实测）。
  await ensureLoggedIn(page)
  const h = await journey('32-production-qr-and-piecework')(page)
  try {
    const api = await adminApi(page)

    // ① 建单（含加工项）—— 独立数据，不污染存量
    const created = await api.post('/api/admin/orders', {
      customerName: '生产旅程', customerPhone: '13900003333', customerAddress: '杭州市西湖区生产路 1 号',
      discountAmount: 0, items: [{
        productId: 'deff0be6c885cbf0469abe4f7b8da608', productName: '2699系列雪尼尔窗帘面料',
        quantity: 2, unitPrice: 23.8, subtotal: 47.6,
        processingInfo: { sellingMethod: 'bulk_cut', doorWidth: '2.8', processingFee: 15,
          processingItems: [{ id: 'proc_item_1', name: '锁边', unitPrice: 7.5, quantity: 2, unit: '米', pricingMethod: 'per_meter', subtotal: 15 }] }
      }],
    })
    const orderId = created?.data?.id
    if (!orderId) throw new Error(`[① 建单] 未返回 data.id：${JSON.stringify(created).slice(0, 200)}`)

    // ② UI：确认付款 → 生成加工单
    await nav(page, `/orders/${orderId}`, '')
    // 等按钮就位而不是定长 sleep：详情页首屏要先过鉴权初始化 + 拉订单，实测曾停在「加载中…」
    // （截图：整页只有一个 spinner）⇒ 定长 2.5s 后判 isVisible 会假红
    const payBtn = page.getByRole('button', { name: /确认付款/ }).first()
    const canPay = await payBtn.waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false)
    if (!canPay) throw new Error(`[② 确认付款] 15s 内未见「确认付款」按钮（url=${page.url()}；新单应为 pending 且有该闸门按钮）`)
    // 闸门弹窗（#3583）：弹窗确认键文本恰为「确定」（与页面的「确认付款」按钮可区分）；
    // 定长 sleep 判不出「弹窗是否真的开了 / 请求是否还在飞」——实测曾因确认后 1.8s 仍在 loading 而假红
    // （截图：弹窗开着、确定键转圈），故改为等弹窗出现（首点被 hydration 吞掉时重试一次）。
    const confirmBtn = page.getByRole('button', { name: '确定', exact: true })
    let modalUp = false
    for (let i = 0; i < 2 && !modalUp; i++) {
      await safeClick(page, payBtn, '确认付款')
      modalUp = await confirmBtn.waitFor({ state: 'visible', timeout: 4000 }).then(() => true).catch(() => false)
    }
    if (!modalUp) throw new Error('[② 确认付款] 点击「确认付款」后确认闸门弹窗未出现（#3583 语义）')
    await confirmBtn.click()
    // 等按钮出现而不是定长 sleep：确认收款 → 订单转 confirmed → 加工单块才渲染生成按钮
    const genBtn = page.getByRole('button', { name: /生成加工单/ }).first()
    const canGen = await genBtn.waitFor({ state: 'visible', timeout: 12000 }).then(() => true).catch(() => false)
    if (!canGen) {
      const st = (await api.get(`/api/admin/orders/${orderId}`).catch(() => ({})))?.data?.status
      throw new Error(`[② 生成加工单] 确认付款后 12s 内仍未出现「生成加工单」按钮（order.status=${st}，期望 confirmed/producing）`)
    }
    await safeClick(page, genBtn, '生成加工单')
    // 等生成效果可见（加工单块渲染出加工单号）再读 API：生成是后端点 + 前端 load()，定长 sleep 会假红
    await page.getByText(/JG-\d{8}-\d+/).first().waitFor({ state: 'visible', timeout: 12000 }).catch(() => {})

    // ③ API 判据（#4186 核心）
    const ops = (await api.get(`/api/admin/production/orders/${orderId}/operations`))?.data
    const qrToken = String(ops?.qr_token ?? '')
    const positions = Array.isArray(ops?.positions) ? ops.positions : []
    const opTotal = positions.reduce((n, p) => n + (Array.isArray(p.operations) ? p.operations.length : 0), 0)
    if (!/^[0-9a-f]{32}$/.test(qrToken)) throw new Error(`[③ qr_token] 非 32 位十六进制：${JSON.stringify(ops?.qr_token)}（UI 生成加工单后应立即有码）`)
    if (opTotal < 1) throw new Error(`[③ positions] 工序实例为空：部位 ${positions.length} 个 / 工序 ${opTotal} 道`)
    if (Number(ops?.progress?.total) !== opTotal) throw new Error(`[③ progress.total] ${ops?.progress?.total} 与工序数 ${opTotal} 不一致`)

    // ④ 生产明细页：DOM 计数（不是 innerText）
    const poNo = String((await api.get(`/api/admin/processing-orders/${orderId}`))?.data?.processingOrderNo ?? '')
    if (!/^JG-\d{8}-\d+$/.test(poNo)) throw new Error(`[④ 加工单号] 非 JG-YYYYMMDD-NNNN：${JSON.stringify(poNo)}`)
    await nav(page, `/processing-orders/${poNo}/production`, '加工单生产明细')
    // 等数据就位再计数：任务卡是 display:none（打印才显形）⇒ **只能等 attached，等 visible 会永远超时**；
    // 等「二维码 或 占位」其一出现 = 工序数据已到达，此后计数才是稳定真值（定长 sleep 会假红）
    await page.locator('[data-testid="task-card-qr"], [data-testid="task-card-qr-placeholder"]').first()
      .waitFor({ state: 'attached', timeout: 15000 }).catch(() => {})
    const qrN = await page.locator('[data-testid="task-card-qr"]').count()
    const phN = await page.locator('[data-testid="task-card-qr-placeholder"]').count()
    const rowN = await page.locator('[data-testid^="operation-row-"]').count()
    if (qrN < 1) throw new Error(`[④ task-card-qr] 计数 ${qrN}（期望 ≥1）——qr_token 非空却未渲染二维码`)
    if (phN !== 0) throw new Error(`[④ task-card-qr-placeholder] 计数 ${phN}（期望 0）——落占位分支`)
    if (rowN < 1) throw new Error(`[④ operation-row-*] 计数 ${rowN}（期望 ≥1）`)
    if (rowN !== opTotal) throw new Error(`[④ DOM↔API 不一致] operation-row-*=${rowN}，而 /operations 工序数=${opTotal}`)

    // ⑤ 报工一次：取各部位**首道**工序（无前道 ⇒ 不触越站闸门）中应做量>0 且单价>0 的一道（保证计件 > 0）
    const firsts = positions.map((p) => (p.operations ?? []).slice().sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))[0]).filter(Boolean)
    const target = firsts.find((o) => Number(o.qty) > 0 && Number(o.unit_price) > 0) ?? firsts.find((o) => Number(o.qty) > 0)
    if (!target) throw new Error(`[⑤ 报工] 无可报工序（各部位首道工序应做量均 ≤ 0）：${JSON.stringify(firsts.map(o => [o.operation, o.qty, o.unit_price]))}`)
    const qty = Number(target.qty)
    const rep = (await api.post(`/api/admin/production/orders/${orderId}/operations/${target.id}/report`,
      { worker_id: 'ui-smoke-worker', worker_name: '冒烟工人', qty, qualified_qty: qty, work_type: 'normal' }))?.data
    if (rep?.status !== 'done') throw new Error(`[⑤ 报工] 未推进到 done：${JSON.stringify(rep)}（工序「${target.operation}」应做 ${qty}）`)

    // 刷新页面读真值：进度不再 0% + 计件合计 > 0
    await page.reload({ waitUntil: 'domcontentloaded' })
    // 等工序表就位（operation-row-* 只在 /operations 返回后渲染）——进度文案与它同源，
    // 数据未到达时百分数只是过渡值 0%，据此断言会假红；等工序行 attached 后读到的才是最终值
    await page.locator('[data-testid^="operation-row-"]').first().waitFor({ state: 'attached', timeout: 15000 }).catch(() => {})
    await page.locator('[data-testid="piecework-total"], [data-testid="piecework-empty"]').first()
      .waitFor({ state: 'attached', timeout: 15000 }).catch(() => {})
    const progressText = String(await page.locator('[data-testid="production-progress-text"]').first().textContent().catch(() => '') ?? '').trim()
    const totalN = await page.locator('[data-testid="piecework-total"]').count()
    const emptyN = await page.locator('[data-testid="piecework-empty"]').count()
    const totalText = totalN ? String(await page.locator('[data-testid="piecework-total"]').first().textContent() ?? '').trim() : ''
    const totalAmount = Number(totalText.replace(/[^0-9.]/g, ''))
    if (!progressText || progressText.startsWith('0%')) throw new Error(`[⑤ 进度] 报工后仍为 ${JSON.stringify(progressText)}（期望非 0%）`)
    if (emptyN !== 0) throw new Error(`[⑤ piecework-empty] 计数 ${emptyN}（期望 0）——报工后计件汇总仍落空态`)
    if (totalN !== 1) throw new Error(`[⑤ piecework-total] 计数 ${totalN}（期望 1）`)
    if (!(totalAmount > 0)) throw new Error(`[⑤ 计件合计] ${JSON.stringify(totalText)}（期望 > 0）`)

    await h.done(true, '', `订单 ${orderId} / 加工单 ${poNo}：qr_token=${qrToken}；工序 ${opTotal} 道；DOM qr=${qrN} 占位=${phN} 行=${rowN}；报工「${target.operation}」${qty}${target.unit ?? ''} → 进度 ${progressText}、计件 ${totalText}`)
  } catch (e) {
    await h.done(false, `生产报工正向旅程失败: ${String(e.message || e).slice(0, 400)}`)
  }
}

// ────────────────────────── 发货页 ──────────────────────────
async function orderShipJourney(page, orderId) {
  const h = await journey('17-order-ship')(page)
  try {
    await nav(page, `/orders/${orderId}/ship`, '')
    // 等页面**稳定**再判，而不是定长 sleep 后数控件（issue #4226②）：含加工项订单要等
    // GET /processing-orders/{orderId} 回来才决定渲染「发货表单」还是「加工单守卫页」，
    // 1500ms 内没回来就判「无表单」是**假红**；两种终态都要能分辨（否则归因不可读）。
    const submit = page.getByRole('button', { name: /确认发货/ }).first()
    const guard = page.getByText(/须先完成加工单后再发货/).first()
    await Promise.race([waitVisible(submit, 15000), waitVisible(guard, 15000)])
    if (await waitVisible(guard, 1000)) {
      throw new Error(`发货表单被加工单前置守卫阻断（订单 ${orderId} 的加工单未流转到 completed ⇒ 16- 前置未达成）`)
    }
    const hasForm = await page.locator('input, textarea, select').count()
    if (hasForm === 0) throw new Error(`发货页无表单（15s 内既未见表单，也未见加工单守卫；url=${page.url()}）`)
    await h.done(true, '', `发货页表单渲染（${hasForm} 控件）`)
  } catch (e) {
    await h.done(false, `发货页失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 售后 ──────────────────────────
async function afterSalesListJourney(page) {
  const h = await journey('18-after-sales-list')(page)
  try {
    await nav(page, '/after-sales', '售后管理')
    await page.waitForTimeout(1500)
    const rows = page.locator('tbody tr, [role="row"]')
    const n = await rows.count().catch(() => 0)
    await h.done(true, '', `售后工单列表渲染 ${n} 行`)
  } catch (e) {
    await h.done(false, `售后列表失败: ${String(e).slice(0, 300)}`)
  }
}

async function afterSalesDetailJourney(page, ticketId) {
  const h = await journey('19-after-sales-detail')(page)
  const reason = `冒烟关闭原因${Date.now()}`
  if (!ticketId) {
    // 从列表点击首行进详情，从 URL 取 id
    await nav(page, '/after-sales', '售后管理')
    await page.waitForTimeout(1500)
    const firstRow = page.locator('tbody tr, [role="row"]').first()
    if (await firstRow.count().catch(() => 0) === 0) { await h.done(false, '售后列表 0 行'); return }
    await firstRow.click()
    await page.waitForTimeout(1800)
    const m = page.url().match(/\/after-sales\/([0-9a-fA-F-]+)/)
    if (!m) { await h.done(false, `点击行未进入售后详情: ${page.url()}`); return }
    ticketId = m[1]
  }
  try {
    if (!ticketId) { await h.done(false, '无目标工单'); return }
    await nav(page, `/after-sales/${ticketId}`, '')
    await page.waitForTimeout(1500)
    // pending → processing
    const acceptBtn = page.getByRole('button', { name: /接受处理/ }).first()
    if (await acceptBtn.isVisible().catch(() => false)) {
      await acceptBtn.click()
      await page.getByRole('button', { name: /确认/ }).last().click().catch(() => {})
      await page.waitForTimeout(1500)
    }
    // processing → closed（关闭原因必填语义 #3541：填写 remark 并落库）
    const closeBtn = page.getByRole('button', { name: /关闭工单/ }).first()
    if (await closeBtn.isVisible().catch(() => false)) {
      await closeBtn.click()
      await page.waitForTimeout(800)
      const remarkInput = page.locator('textarea, input[placeholder*="原因"], input[placeholder*="备注"]').first()
      await remarkInput.fill(reason).catch(() => {})
      await page.getByRole('button', { name: /确认/ }).last().click().catch(() => {})
      await page.waitForTimeout(1800)
      // 结果可见：详情页展示关闭原因
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(1800)
      const reasonVisible = await page.getByText(reason).first().isVisible().catch(() => false)
      await h.done(reasonVisible, reasonVisible ? '' : '关闭原因未回显', `关闭原因落库回显=${reasonVisible}`)
    } else {
      await h.done(true, '工单状态不可关闭（可能已终态），仅验证渲染', '')
    }
  } catch (e) {
    await h.done(false, `售后详情失败: ${String(e).slice(0, 400)}`)
  }
}

// ────────────────────────── 客户 ──────────────────────────
async function customersListJourney(page) {
  const h = await journey('20-customers-list')(page)
  try {
    await nav(page, '/customers', '客户管理')
    await page.waitForTimeout(1500)
    const rows = page.locator('tbody tr, [role="row"]')
    const n = await rows.count().catch(() => 0)
    // wechatNickname 语义（#3562）：列表不得显示空名/报错
    const bodyText = await page.evaluate(() => document.body.innerText)
    const hasErr = /服务器错误|Internal Server|加载失败/.test(bodyText)
    await h.done(n > 0 && !hasErr, hasErr ? '客户列表页报错' : (n === 0 ? '客户列表 0 行' : ''), `客户列表 ${n} 行`)
  } catch (e) {
    await h.done(false, `客户列表失败: ${String(e).slice(0, 300)}`)
  }
}

async function customerDetailJourney(page) {
  const h = await journey('21-customer-detail')(page)
  try {
    await nav(page, '/customers', '客户管理')
    await page.waitForTimeout(1500)
    const firstLink = page.locator('a[href*="/customers/"]').first()
    const href = await firstLink.getAttribute('href').catch(() => null)
    if (!href) { await h.done(true, '无客户可进详情', ''); return }
    await nav(page, href, '')
    await page.waitForTimeout(1500)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 50) throw new Error('客户详情空白')
    // 编辑入口（若无编辑则记录）
    const editBtn = page.getByRole('button', { name: /编辑/ }).first()
    const editSeen = await editBtn.isVisible().catch(() => false)
    await h.done(true, '', `客户详情渲染（${href}），编辑入口=${editSeen}`)
  } catch (e) {
    await h.done(false, `客户详情失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 财务 ──────────────────────────
async function financeJourney(page) {
  const h = await journey('22-finance')(page)
  try {
    await nav(page, '/finance', '财务对账')
    await page.waitForTimeout(1500)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 50) throw new Error('财务页空白')
    await h.done(true, '', '财务对账页渲染')
  } catch (e) {
    await h.done(false, `财务页失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 员工 ──────────────────────────
async function employeesJourney(page) {
  const h = await journey('23-employees')(page)
  const uniq = `冒烟员工${Date.now()}`
  try {
    await nav(page, '/employees', '员工管理')
    await page.waitForTimeout(1500)
    const rows = page.locator('tbody tr, [role="row"]')
    const n0 = await rows.count().catch(() => 0)
    // 新建
    const addBtn = page.getByRole('button', { name: /新增员工|新建员工|添加员工/ }).first()
    await safeClick(page, addBtn, '新增员工')
    await page.waitForTimeout(800)
    // 空提交 → 校验提示（姓名/手机号/岗位必填）
    await page.getByRole('button', { name: /创建|确 定|保存/ }).last().click().catch(() => {})
    await page.waitForTimeout(600)
    const vErr = await page.getByText(/请输入姓名|请输入手机号|请选择岗位/).first().isVisible().catch(() => false)
    // 填真实数据（弹窗内）
    const dlg = page.locator('[role="dialog"]')
    await dlg.locator('input[placeholder*="姓名"]').fill(uniq)
    await dlg.locator('input[placeholder*="手机号"]').fill(`139${Date.now().toString().slice(-8)}`)
    // 选岗位（弹窗内的岗位下拉）
    const posSelect = dlg.locator('select').first()
    const posOpts = await posSelect.locator('option').allTextContents().catch(() => [])
    const realIdx = posOpts.findIndex(t => t !== '' && !t.includes('请选择') && t !== '全部状态' && t !== '启用' && t !== '禁用')
    if (realIdx < 0) throw new Error('岗位下拉无可用选项')
    await posSelect.selectOption({ index: realIdx })
    await page.getByRole('button', { name: /创建|确 定|保存/ }).last().click()
    await page.waitForTimeout(1800)
    // 结果可见：列表出现
    const row = page.locator(`text=${uniq}`).first()
    await row.waitFor({ state: 'visible', timeout: 8000 })
    // 编辑：改手机号 → 验证落库（HR-008）
    const empRow = page.locator('tbody tr').filter({ hasText: uniq }).first()
    const editBtn = empRow.locator('button:has-text("编辑")').first()
    await editBtn.waitFor({ state: 'visible', timeout: 6000 }).catch(() => {})
    await editBtn.click({ force: true }).catch(async () => {
      await page.getByRole('button', { name: /编辑/ }).first().click()
    })
    await page.waitForTimeout(1000)
    await page.locator('input[placeholder*="手机号"], input[name="phone"]').first().fill(`138${Date.now().toString().slice(-8)}`)
    await page.getByRole('button', { name: /确 定|保存/ }).last().click()
    await page.waitForTimeout(1500)
    const phoneShown = await page.getByText('13911113333').first().isVisible().catch(() => false)
    // 删除
    const delBtn = empRow.locator('button:has-text("删除")').first()
    if (await delBtn.isVisible().catch(() => false)) {
      await delBtn.click()
      await page.waitForTimeout(800)
      await page.locator('[role="dialog"] button').filter({ hasText: /删除|确定/ }).last().click().catch(() => {})
      await page.waitForTimeout(1500)
    }
    await h.done(true, '', `员工 新建→可见→改手机号落库=${phoneShown}→删除；空提交校验=${vErr}`)
  } catch (e) {
    await h.done(false, `员工旅程失败: ${String(e).slice(0, 400)}`)
  }
}

// ────────────────────────── 岗位权限 ──────────────────────────
async function rolesJourney(page) {
  const h = await journey('24-roles')(page)
  try {
    await nav(page, '/roles', '岗位权限')
    await page.waitForTimeout(1500)
    const rows = page.locator('tbody tr, [role="row"], [class*="card"]')
    const n = await rows.count().catch(() => 0)
    if (n === 0) throw new Error('岗位列表 0 行')
    // 打开岗位权限编辑（第一行）
    const editBtn = page.getByRole('button', { name: /编辑|权限/ }).first()
    if (await editBtn.isVisible().catch(() => false)) {
      await editBtn.click()
      await page.waitForTimeout(1000)
      const dlg = page.locator('[role="dialog"], [class*="Modal"], [class*="modal"]').first()
      await dlg.waitFor({ state: 'visible', timeout: 6000 })
      await page.getByRole('button', { name: /取消/ }).last().click().catch(() => {})
    }
    await h.done(true, '', `岗位权限页 ${n} 行，权限编辑弹窗可开`)
  } catch (e) {
    await h.done(false, `岗位权限失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 设置 ──────────────────────────
async function settingsJourney(page) {
  const h = await journey('25-settings')(page)
  try {
    await nav(page, '/settings', '企业基础信息')
    await page.waitForTimeout(1500)
    // Tab 结构：基本信息/修改密码/通知设置
    const tabs = await page.locator('[role="tab"], [class*="tab"], button:has-text("修改密码"), button:has-text("通知")').count()
    // 基本信息保存
    const saveBtn = page.getByRole('button', { name: /保存/ }).first()
    if (await saveBtn.isVisible().catch(() => false)) {
      await saveBtn.click()
      await page.waitForTimeout(1200)
    }
    // 修改密码 Tab（#3583 闸门：需当前密码）
    const pwdTab = page.getByRole('button', { name: /修改密码/ }).first()
    if (await pwdTab.isVisible().catch(() => false)) {
      await pwdTab.click()
      await page.waitForTimeout(800)
      const pwdInputs = page.locator('input[type="password"]')
      if (await pwdInputs.count().then(c => c > 0)) {
        await h.done(true, '', `设置页 Tab 数=${tabs}，修改密码表单可见（闸门校验留 UI 观察）`)
        return
      }
    }
    // 通知设置
    const notifBtn = page.getByRole('button', { name: /通知设置|系统通知/ }).first()
    if (await notifBtn.isVisible().catch(() => false)) {
      await notifBtn.click()
      await page.waitForTimeout(800)
    }
    await h.done(true, '', `设置页渲染，Tab 数=${tabs}`)
  } catch (e) {
    await h.done(false, `设置页失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 通知中心 ──────────────────────────
async function notificationsJourney(page) {
  const h = await journey('26-notifications')(page)
  try {
    await nav(page, '/notifications', '通知中心')
    await page.waitForTimeout(1500)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 30) throw new Error('通知页空白')
    // 标记全部已读（主操作）
    const readAll = page.getByRole('button', { name: /全部已读|标记已读/ }).first()
    if (await readAll.isVisible().catch(() => false)) {
      await readAll.click()
      await page.waitForTimeout(1000)
    }
    await h.done(true, '', '通知中心渲染，已读操作可用')
  } catch (e) {
    await h.done(false, `通知页失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 门户/注册 ──────────────────────────
async function corporatePages(page) {
  const pages = [
    ['27-corporate-home', '/', ''],
    ['28-corporate-about', '/about', ''],
    ['29-corporate-contact', '/contact', ''],
    ['30-corporate-services', '/services', ''],
  ]
  for (const [name, path, _] of pages) {
    const h = await journey(name)(page)
    try {
      await page.goto(BASE + path, { waitUntil: 'domcontentloaded', timeout: 20000 })
      await page.waitForTimeout(1200)
      const bodyLen = await page.evaluate(() => document.body.innerText.length)
      if (bodyLen < 30) throw new Error(`${path} 页面空白`)
      await h.done(true, '', `${path} 渲染（${bodyLen} 字符）`)
    } catch (e) {
      await h.done(false, `${path} 失败: ${String(e).slice(0, 200)}`)
    }
  }
}

async function registerJourney(page) {
  const h = await journey('31-register')(page)
  try {
    await page.goto(BASE + '/register', { waitUntil: 'domcontentloaded', timeout: 20000 })
    await page.waitForTimeout(1200)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    const hasForm = await page.locator('input').count().catch(() => 0)
    await h.done(bodyLen > 30, bodyLen > 30 ? '' : '注册页空白', `注册页渲染，输入控件=${hasForm}`)
  } catch (e) {
    await h.done(false, `注册页失败: ${String(e).slice(0, 200)}`)
  }
}

// ────────────────────────── 主执行器 ──────────────────────────
import { writeFileSync as wfs } from 'node:fs'

// 旅程级 45s 硬超时：挂死的旅程记录失败并继续，不拖死整轮
const J_TIMEOUT = 45000
async function jrun(name, fn, page) {
  if (GROUP && !name.startsWith(GROUP)) return
  const timer = new Promise((_, rej) => setTimeout(() => rej(new Error(`${name} 超时 ${J_TIMEOUT / 1000}s`)), J_TIMEOUT))
  try {
    await Promise.race([fn(page), timer])
  } catch (e) {
    const msg = String(e.message || e).slice(0, 200)
    console.log(`❌ ${name}\n   超时/异常: ${msg}`)
    results.push({ journey: name, pass: false, errors: [`超时/异常: ${msg}`], notes: [], evidence: [] })
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()

  // 登录 + 会话保持（同一上下文内完成，保证后续旅程带登录态）
  await jrun('01-login', async (p) => {
    const h = await journey('01-login')(p)
    await p.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 25000 })
    await expectText(p, '手机号登录')
    await p.fill('#phone', PHONE)
    await safeClick(p, p.getByRole('button', { name: /获取验证码/ }), '获取验证码')
    await p.waitForTimeout(1200)
    await p.fill('#code', SMS_CODE)
    await safeClick(p, p.getByRole('button', { name: /登\s*录|登录/ }).last(), '登录')
    await p.waitForURL('**/dashboard**', { timeout: 20000 })
    await expectText(p, '经营看板')
    await p.reload({ waitUntil: 'domcontentloaded' })
    await p.waitForURL('**/dashboard**', { timeout: 10000 })
    await expectText(p, '经营看板')
    await h.done(true, '', 'login → /dashboard，刷新后会话保持')
  }, page)

  // 依序执行旅程
  await jrun('02-dashboard', dashboardJourney, page)
  await jrun('03-briefing', briefingJourney, page)
  await jrun('04-agent-workspace-redirect', agentWorkspaceRedirect, page)
  await jrun('05-human-sessions', humanSessions, page)
  await jrun('06-agent-sessions', agentSessions, page)
  await jrun('07-chat', chatPage, page)
  await jrun('08-products-list', productsList, page)
  await jrun('09-products-new', productsNew, page)
  await jrun('10-product-detail', productDetail, page)

  // 门幅回显：#3641 —— 编辑库内 doorWidth='2.8米' 的商品，验证回显 canonical '2.8'、下拉显示 '2.8米'
  const dwTarget = process.env.DW_PRODUCT_ID || 'e7fbe9da0387b04be98b839ed97caf2b'
  await jrun('11-product-edit-doorwidth', (p) => productEdit(p, dwTarget), page)

  await jrun('12-processing', processingJourney, page)
  await jrun('13-categories', categoriesJourney, page)
  await jrun('14-orders-list', ordersListJourney, page)
  await jrun('15-orders-new', ordersNewJourney, page)

  // 订单详情：用 API 创建含加工项的订单（独立数据，不污染存量）
  const apiBase = API_BASE
  const token = process.env.API_TOKEN || ''
  let orderId = ''
  if (token) {
    try {
      const r = await fetch(`${apiBase}/api/admin/orders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({
          customerName: '冒烟测试', customerPhone: '13900002222', customerAddress: '测试地址',
          discountAmount: 0, items: [{
            productId: 'deff0be6c885cbf0469abe4f7b8da608', productName: '2699系列雪尼尔窗帘面料',
            quantity: 2, unitPrice: 23.8, subtotal: 47.6,
            processingInfo: { sellingMethod: 'bulk_cut', doorWidth: '2.8', processingFee: 15,
              processingItems: [{ id: 'proc_item_1', name: '锁边', unitPrice: 7.5, quantity: 2, unit: '米', pricingMethod: 'per_meter', subtotal: 15 }] }
          }],
        }),
      })
      const body = await r.json()
      orderId = body.data?.id || ''
    } catch (e) { console.log('⚠️ API 建单失败:', String(e).slice(0, 200)) }
  }

  const detOrderId = orderId || process.env.ORDER_ID || ''
  await jrun('16-order-detail-processing-order', (p) => orderDetailJourney(p, detOrderId), page)
  // #4186 收口：加工单二维码 / 工序列 / 计件的**正向**分支（自带建单，不依赖 16- 的数据）
  await jrun('32-production-qr-and-piecework', productionQrJourney, page)
  await jrun('17-order-ship', (p) => orderShipJourney(p, detOrderId), page)
  await jrun('18-after-sales-list', afterSalesListJourney, page)
  const aftersalesId = process.env.AFTERSALES_ID || ''
  await jrun('19-after-sales-detail', (p) => afterSalesDetailJourney(p, aftersalesId), page)
  await jrun('20-customers-list', customersListJourney, page)
  await jrun('21-customer-detail', customerDetailJourney, page)
  await jrun('22-finance', financeJourney, page)
  await jrun('23-employees', employeesJourney, page)
  await jrun('24-roles', rolesJourney, page)
  await jrun('25-settings', settingsJourney, page)
  await jrun('26-notifications', notificationsJourney, page)
  await jrun('27-corporate', corporatePages, page)
  await jrun('28-register', registerJourney, page)

  await browser.close()

  // 汇总输出
  const passed = results.filter(r => r.pass).length
  const failed = results.length - passed
  const md = [
    '# 商家后端 UI 冒烟结果',
    '',
    `时间: ${new Date().toISOString()} ｜ 通过 ${passed}/${results.length} ｜ 失败 ${failed}`,
    '',
    '| # | 旅程 | 结果 | 证据 |',
    '|---|------|------|------|',
  ]
  results.forEach((r, i) => {
    const ev = r.evidence.filter(e => !e.startsWith('/') || e.endsWith('.png')).join('; ').slice(0, 160)
    const err = r.errors.join(' / ').slice(0, 120)
    md.push(`| ${i + 1} | ${r.journey} | ${r.pass ? '✅' : '❌'} | ${ev || err || '—'} |`)
  })
  wfs(join(OUT, 'smoke-summary.md'), md.join('\n'))
  wfs(join(OUT, 'smoke-results.json'), JSON.stringify(results, null, 2))
  console.log(`\n===== 汇总: ${passed}/${results.length} 通过，${failed} 失败 =====`)
  process.exit(failed > 0 ? 1 : 0)
}

main()
