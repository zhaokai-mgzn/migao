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

// ────────────────────────── 结果分类（#6790 / AGENTS.md 铁律）──────────────────────────
// 三态，**不许互相冒充**（issue #6790 判据 ③④）：
//   pass         —— 真跑并通过；
//   unconfigured —— 依赖面**未配置**（ai-agent 未按 AGENTS.md 传 BASE_URL/SERVICE_TOKEN）⇒ 成因不在产品；
//   skipped      —— 前置数据/依赖不满足（`depends_on`）⇒ 没跑，不是失败也不是通过。
// ⚠️ 「没跑」必须长得像「没跑」：这两种都不算 pass，也不与真实失败混在一张表里。
const UNCONFIGURED = process.env.SMOKE_UNCONFIGURED === '1'
// 依赖 ai-agent 的旅程（判据：失败原因 = ai-agent 未配置 ⇒ 记 unconfigured，不记产品失败）。
// `12-processing` 不在其中（加工项 CRUD 是纯 admin-api；它是本轮真 B 类，要与 A 类分开看）。
const AI_AGENT_JOURNEYS = new Set(['06-agent-sessions', '07-chat', '09-products-new', '32-production-qr-and-piecework'])
// `--group <前缀>` 过滤（口径 = **两位数字前缀**，如 `01-` / `16-` / `23-`；用法串里写的也是这一形态）。
// 🔴 issue #6790 实测的存量形态：`--group 2-` 匹配不到 `24-roles`（`'24-roles'.startsWith('2-')` = false）
//    ⇒ 该组**一条都不跑**却**一条记录都不落**（旧形态过滤即 `return`）—— 读起来像「本轮全绿」。
//    本单把它变成**显式 skip 记录**（`⏭️ … [skip] --group 2- 过滤（本轮未跑）`）；
//    **不改**前缀语义（改语义会让「`2-` 到底含不含 `2X`」变成需要裁定的问题，本单不引入）。
const inGroup = (name) => !GROUP || name.startsWith(GROUP)
// 本轮全部旅程名（看门狗到点时把**没跑到的**补记 skip —— 「没跑」必须长得像「没跑」）
const ALL_JOURNEY_NAMES = [
  '01-login', '02-dashboard', '03-briefing', '04-agent-workspace-redirect', '05-human-sessions',
  '06-agent-sessions', '07-chat', '08-products-list', '09-products-new', '10-product-detail',
  '11-product-edit-doorwidth', '12-processing', '13-categories', '14-orders-list', '15-orders-new',
  '16-order-detail-processing-order', '32-production-qr-and-piecework', '17-order-ship',
  '18-after-sales-list', '19-after-sales-detail', '20-customers-list', '21-customer-detail',
  '22-finance', '23-employees', '24-roles', '25-settings', '26-notifications',
  '27-corporate', '28-register',
]

// ────────── 已知产品面 console / pageerror 台账（#6790 判据 ③ 的**边界登记**）──────────
// `journey()` 把 console.error / pageerror 一律收成**旅程失败**。但存在一类：报错是**真实产品缺陷**
// （已归口 issue）、且它发生在**渲染 / 度量层**，而本旅程要断言的**行为面**证据已经拿到。
// 不登记 ⇒ 同一缺陷在多轮里反复把真栈读数搅成噪声（且会把「行为面已验证」错读成「本旅程也坏了」）。
// 口径（fail-closed）：**逐字**正则 + **必须带 issue 归口** + 写明「为什么不推翻本旅程的行为面结论」；
//   且**只在行为面已达成**时（调用方传 `allowKnownConsole: true`）才把该条从 errors 移到 notes
//   —— **照实印出、不隐藏**（notes 会进 smoke-results.json）。`SMOKE_STRICT_CONSOLE=1` 关闭本机制。
const KNOWN_CONSOLE_ERRORS = [
  // 🔴 2026-10-13 清空（issue #6799）：两条登记（AFTERSALES_HYDRATION / PROCESSING_MEASURE_NEGATIVE）
  // 的缺陷**都已修好**（`AfterSalesDetail.tsx` 的两处 `<p>` 容器换成 `<div>`；`performance.measure`
  // 区间守卫接线在 `src/app/layout.tsx`）⇒ 按「台账只许缩短」把它们**删掉**：
  // `entries` 为空 = 「已知产品面 console 错误 = 0 条」，此后这两条再出现就是**真失败**（不再是 notes）。
  // ⚠️ 机制本身**保留**（`isKnownConsoleError` / `knownConsoleIssue` / `allowKnownConsole` /
  // `SMOKE_STRICT_CONSOLE` 都在）：将来若另有**已归口**的真实缺陷需要临时承接，按同口径登记——
  // 台账 ⇄ spec 逐字对账由 `tests/unit_ci_workflows/test_ui_smoke_selector_liveness.py` 的判据 H 盯着。
]
const isKnownConsoleError = (e) =>
  process.env.SMOKE_STRICT_CONSOLE !== '1' && KNOWN_CONSOLE_ERRORS.some((k) => k.test.test(String(e)))
const knownConsoleIssue = (e) => (KNOWN_CONSOLE_ERRORS.find((k) => k.test.test(String(e))) || {}).issue || ''
// 判据 H 的机械核对面：台账必须非空、条目必须有 issue 与 why（守卫读这段源码，见 test_ui_smoke_selector_liveness.py）

// ────────────────────────── 框架 ──────────────────────────
function journey(name, opts = {}) {
  return async (page) => {
    if (GROUP && !name.startsWith(GROUP)) {
      // 过滤掉的旅程返回哨兵，避免调用方解构崩溃
      return { page, rec: null, done: async () => null, skipped: true }
    }
    const rec = { journey: name, pass: true, errors: [], notes: [], evidence: [], skipped: false, unconfigured: false, error_class: null }
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
    const done = async (ok, why, ev, errClass) => {
      page.removeListener('console', onConsole)
      page.removeListener('pageerror', onPageError)
      // 分类优先于 pass：未配置 / 前置不满足**都不是**产品失败（#6790 判据 ③④）
      const klass = typeof errClass === 'string' && errClass
        ? errClass
        : (!ok && UNCONFIGURED && AI_AGENT_JOURNEYS.has(name) ? 'unconfigured' : null)
      rec.error_class = klass
      if (klass === 'unconfigured') {
        rec.unconfigured = true
        rec.pass = false
        if (errs.length) rec.errors.push(...errs)
        console.log(`➖ ${name} [未配置] ai-agent 未按 AGENTS.md 传 AI_AGENT_BASE_URL / AI_AGENT_SERVICE_TOKEN`)
      } else if (klass === 'skip') {
        rec.skipped = true
        rec.pass = false
        rec.errors = []
        rec.notes.push(String(why || '前置不满足'))
        console.log(`⏭️  ${name} [skip] ${why}`)
      } else {
        rec.pass = rec.pass && ok
        if (!ok && why) { rec.errors.push(why); failReasons.set(name, why) }
        if (errs.length) {
          // 已知产品缺陷（已归口）+ 行为面已达成 ⇒ 移到 notes（**照实印出**，不隐藏、不算绿）
          const known = opts.allowKnownConsole ? errs.filter(isKnownConsoleError) : []
          const rest = errs.filter((e) => !known.includes(e))
          if (known.length) rec.notes.push(...known.map((e) => `[已知产品缺陷 ${knownConsoleIssue(e)}] ${e}`))
          if (rest.length) { rec.errors.push(...rest); rec.pass = false }
        }
        if (rec.pass) { console.log(`✅ ${name}`) } else { console.log(`❌ ${name}\n   ${rec.errors.join('\n   ')}`) }
      }
      if (ev) rec.evidence.push(ev)
      if (opts.screenshot !== false) {
        const shot = join(OUT, 'screenshots', `${name}.png`)
        try { await page.screenshot({ path: shot, fullPage: false }) } catch {}
        rec.evidence.push(shot)
      }
      return rec
    }
    return { page, done, rec }
  }
}

/** 前置数据/依赖不满足 ⇒ **skip 且印出来**（skip ≠ pass，也 ≠ fail；#6790 判据 ④）。 */
const markSkipped = (h, why) => h.done(true, why, undefined, 'skip')

// ────────────────────────── 前置数据自造（#6790 判据 ④：能自造就别登记依赖）──────────────────────────
// 交付物模板：`16-order-detail-processing-order` / `17-order-ship` / `32-production-qr-and-piecework`
// 都要求「一张 pending 的含加工项订单」；旧形态靠 `process.env.API_TOKEN`（**从没有人传过**）⇒
// `orderId` 恒空 ⇒ `16` 报「无目标订单」、`17` 导航到 `/orders//ship` 让前端把订单 id 拼成 `ship`
// ⇒ api 日志 `请求的资源不存在: GET /api/admin/orders/ship`（issue #6790 B 类 ③）。
// 现在一律用**浏览器会话的 cookie** 走 node 侧 `adminApi`（本文件既有形态）自造。
const SMOKE_PRODUCT_ID = 'deff0be6c885cbf0469abe4f7b8da608'

/** 建品/建单要一个**真存在的分类 id**（探针实测：`分类ID不能为空` ⇒ 422）。 */
let _categoryId = ''
async function defaultCategoryId(page) {
  if (_categoryId) return _categoryId
  const api = await adminApi(page)
  const res = await api.get('/api/admin/categories?page=1&size=1')
  const first = (res?.data?.items ?? res?.data ?? [])[0]
  _categoryId = first?.id || ''
  if (!_categoryId) throw new Error(`建品前置失败：/api/admin/categories 无可用分类（${JSON.stringify(res).slice(0, 160)}）`)
  return _categoryId
}

/** 自造一张含加工项的订单（pending），返回订单 id；调用方负责在跑完后 `cleanupOrder`。 */
async function createOrderFixture(page, tag) {
  const api = await adminApi(page)
  const created = await api.post('/api/admin/orders', {
    customerName: tag, customerPhone: '13900002222', customerAddress: '杭州市西湖区冒烟路 2 号',
    // 探针实测：`常用物流/快递不能为空` + `常用物流公司不能为空`（422）
    logisticsType: 'express', logisticsCompany: '顺丰速运',
    discountAmount: 0, items: [{
      productId: SMOKE_PRODUCT_ID, productName: '2699系列雪尼尔窗帘面料',
      quantity: 2, unitPrice: 23.8, subtotal: 47.6,
      processingInfo: { sellingMethod: 'bulk_cut', doorWidth: '2.8', processingFee: 15,
        processingItems: [{ id: 'proc_item_1', name: '锁边', quantity: 2, unit: '米' }] }
    }],
  })
  const id = created?.data?.id
  if (!id) throw new Error(`前置建单失败（未返回 data.id）：${JSON.stringify(created).slice(0, 200)}`)
  return id
}

/** 跑完清理自造数据（删不掉不阻塞旅程，只记 note —— 清理失败 ≠ 旅程失败）。 */
async function cleanupOrder(page, id) {
  try {
    const api = await adminApi(page)
    await api.get(`/api/admin/orders/${id}`)  // 存在性确认（真造出来了才谈删除）
    const at = (await page.context().cookies()).find((c) => c.name === 'access_token')
    const res = await fetch(`${API_BASE}/api/admin/orders/${id}`, {
      method: 'DELETE', headers: { Cookie: `access_token=${at.value}` },
    })
    return res.ok
  } catch { return false }
}

/**
 * 依赖探测（issue #6790 判据 ④）：本租户**能不能生成加工单**。
 *
 * 触发条件（真栈实测，api 日志逐字）：
 *   `INCIDENT_PRODUCTION_ROUTING_UNRESOLVED 订单缺 \`craft\` 且该租户没有默认工艺，生成加工单中止
 *    （不回退常量 韩褶）: tenantId=25, 部位=布帘`
 * ⇒ 该租户**没有配置生产路线/默认工艺** ⇒ `POST /api/admin/processing-orders/generate` **HTTP 200 但
 *   `data` 为空**（不是异常），加工单永远不落库 ⇒ `16-` 的 `.po-print-area` 永不出现。
 *
 * 这是**前置数据缺失**（云 dev 租户未配路线），不是选择器漂移、也不是产品回归；
 * 所以 16-/17-/32- 在本形态下判 **skip 并印出来**（skip ≠ pass、也 ≠ fail）。
 * 判据 = `可以自造前置 ⇒ 用 `createOrderFixture`；自造不了 ⇒ 显式登记依赖 + skip`。
 */
async function processingRouteAvailable(page) {
  const api = await adminApi(page)
  const probeId = await createOrderFixture(page, '冒烟路线探测')
  const gen = await api.post('/api/admin/processing-orders/generate', { orderIds: [probeId] })
  const results = Array.isArray(gen?.data) ? gen.data : []
  const ok = results.some((r) => r && r.success !== false)
  const why = ok
    ? ''
    : `本租户指定单（${probeId}）生成加工单**未落库**：接口 HTTP 200 但 data 为空 —— `
      + `api 日志 INCIDENT_PRODUCTION_ROUTING_UNRESOLVED「订单缺 craft 且该租户没有默认工艺」`
      + `（租户未配生产路线/默认工艺）`
  if (ok) await cleanupOrder(page, probeId)
  return { ok, why, probeId }
}

/** 自造商品的前置清理（同为「先建再测、跑完清理」；失败留在 note 里，不冒充旅程失败）。 */
async function cleanupProduct(page, id) {
  try {
    const api = await adminApi(page)
    const at = (await page.context().cookies()).find((c) => c.name === 'access_token')
    const res = await fetch(`${API_BASE}/api/admin/products/${id}`, {
      method: 'DELETE', headers: { Cookie: `access_token=${at.value}` },
    })
    return res.ok
  } catch { return false }
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

// ⚠️ toast 助手 `expectToast()` 已**删除**（issue #4314）：全文件零调用 = 死判据，
// 且它内部 `waitFor(...).catch(() => {})` 吞超时 ⇒ 一旦接上调用点即**恒真**（空判据）。
// `15-orders-new` 的 toast 判定维持原样（那是「定长 sleep + 单次 isVisible」同族，
// 按 #4314 正文裁定**待真栈可用时成批**改成 `waitVisible` / expect 轮询 —— 本机云 dev 库
// 不可达，改了没人跑过 = 假红/假绿）。零调用死判据的常驻判据 =
// `tests/unit_ci_workflows/test_dead_judgement_helpers.py`。

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
  return {
    get: (p) => call('GET', p),
    post: (p, b) => call('POST', p, b),
    // 19- 的售后前置要 `PUT /api/admin/orders/{id}/payment`（确认付款）——旧形态只有 get/post
    put: (p, b) => call('PUT', p, b),
    patch: (p, b) => call('PATCH', p, b),
  }
}

// ────────────────────────── UI 登录步骤（唯一入口）──────────────────────────
// issue #6779：登录步骤原本在**三处**各写一遍（本函数 / `loginJourney` / `main` 的 `01-login`），
// 三处**同步腐烂**且任一处失败都只表现为「后续旅程各自超时」。
// 现在：① 选择器**只此一份**（现取 `frontend/admin-web/src/app/login/page.tsx`）；
//       ② 失败一律带 `登录步骤失败[<位置>]` 前缀 ⇒ 27 条旅程不再各自背锅（归因到第一步）。
//
// ⚠️ 文案**就地取字面量**（不抽 `const`）：抽成常量后 `expectText(page, C)` 在静态面上就看不到
// 「等的是哪句文案」⇒ 活性判据（issue #6779）失效。重复三处的代价 ≪ 判据失效的代价。
// ⚠️ 名字**不得**用 `exact: true`：登录页 tab 按钮的可及名字 = 标题 + 副标题（「管理员登录 手机验证码」，
// 见 frontend/admin-web/src/app/login/page.tsx 的 `label`/`hint` 两个文本节点）⇒ `exact` 恒匹配不到
// （issue #6785 真栈实测：`{ name: '管理员登录', exact: true }` count=0、`{ name: /管理员登录/ }` count=1）。
// 角色面本来就是对的（容器 `role="tablist"` + 两个按钮 `role="tab"`）⇒ 这里只放宽**名字**口径。
/** 切到「管理员登录」tab（默认 tab 是「员工登录」；用正则子串定位，避免 exact 匹配不到「标题+副标题」）。 */
async function openAdminLoginTab(page) {
  const tab = page.getByRole('tab', { name: /管理员登录/ }).first()
  await tab.waitFor({ state: 'visible', timeout: 8000 })
  // 🔴 真实栈偶发（探针实测 + 本单多轮复现）：`/login` 的 SSR 骨架先到，React **还没 hydrate** 就点 tab
  //    ⇒ 点击不改变 tab 状态 ⇒ `#phone` 永远不出现 ⇒ `page.fill('#phone')` 30s 超时
  //    （全量跑里表现为 01-login ❌，随后所有旅程连锁 ❌；单跑时表现为 ensureLoggedIn 超时）。
  //    修法 = **等 hydration 再点**（`Object.keys(document.body)` 上出现 `__react*` 私有键），
  //    点完再确认手机号输入真的出现；仍不在 ⇒ 重点一次（tab 状态机可能被路由跳转重置）。
  await page.waitForFunction(
    () => Object.keys(document.body).some((k) => k.startsWith('__react')),
    null, { timeout: 30000 },
  ).catch(() => {})  // 拿不到也不静默成功：下面的 `#phone` 等待仍是硬门禁
  await tab.click()
  const phone = page.locator('#phone')
  if (!(await waitVisible(phone, 5000))) {
    await tab.click().catch(() => {})
    await waitVisible(phone, 8000)
  }
}

/** 登录步骤的失败归因包装：抛出的错误**必须**自报「登录步骤失败」+ 位置（判据见 §归因）。 */
async function loginStep(where, fn) {
  try {
    return await fn()
  } catch (e) {
    throw new Error(`登录步骤失败[${where}]: ${String(e && e.message ? e.message : e).slice(0, 300)}`)
  }
}

/** 手机号 + 短信验证码登录（管理员 tab）→ 等落点 /dashboard。三处调用点共用，选择器只有这一份。 */
async function smsLogin(page, { where, settleMs }) {
  return loginStep(where, async () => {
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 25000 })
    await openAdminLoginTab(page)
    await expectText(page, '管理员登录')
    await page.fill('#phone', PHONE)
    await safeClick(page, page.getByRole('button', { name: /获取验证码/ }), '获取验证码')
    await page.waitForTimeout(settleMs)
    await page.fill('#code', SMS_CODE)
    await safeClick(page, page.getByRole('button', { name: /登\s*录|登录/ }).last(), '登录')
    await page.waitForURL('**/dashboard**', { timeout: 20000 })
  })
}

// 登录态自补：`--group 32-` 会把 01-login 一并过滤掉 ⇒ 本旅程单跑时自补一次 UI 登录
// （全量跑时 cookie 已在，直接跳过，不重复发码）
async function ensureLoggedIn(page) {
  if ((await page.context().cookies()).some((c) => c.name === 'access_token')) return
  await smsLogin(page, { where: 'ensureLoggedIn', settleMs: 1200 })
}

// ────────────────────────── 登录 ──────────────────────────
async function loginJourney(browser) {
  const page = await browser.newPage()
  const h = await journey('01-login')(await Promise.resolve(page))
  try {
    await smsLogin(page, { where: '01-login', settleMs: 800 })
    // 登录成功后跳转 /dashboard
    await expectText(page, '经营看板')
    // 会话保持：刷新后仍在看板（仍登录）
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.waitForURL('**/dashboard**', { timeout: 8000 })
    await expectText(page, '经营看板')
    await h.done(true, '', 'login → /dashboard，刷新后会话保持')
  } catch (e) {
    await h.done(false, String(e && e.message ? e.message : e).slice(0, 300))
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
  // `--group` 过滤掉的旅程记 skip（没跑 ≠ 失败）；这几条**没接在 `jrun` 上**，故各自守卫（#6790）
  if (!inGroup('07-chat')) { await markSkipped(h, '--group 07-chat 过滤（本轮未跑）'); return }
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
    await nav(page, '/products', '')
    // 等页面就位（表头「商品标题」或首行）——旧形态 `nav(..., '商品列表')` 的 8s 文案等待
    // 在真栈上偶发不够（列表先请求后渲染，实测超时）；判据不变，只把等待方式换成显式就位。
    if (!(await waitVisible(page.getByText('商品标题').first(), 20000))) {
      if (!(await waitVisible(page.locator('tbody tr, [role="row"]').first(), 8000))) {
        throw new Error(`商品页 20s 内未就位（url=${page.url()}）`)
      }
    }
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
  // `--group` 过滤掉的旅程记 skip（没跑 ≠ 失败）；这几条**没接在 `jrun` 上**，故各自守卫（#6790）
  if (!inGroup('09-products-new')) { await markSkipped(h, '--group 09-products-new 过滤（本轮未跑）'); return }
  const h = await journey('09-products-new')(page)
  try {
    await nav(page, '/products/new', '')
    // 等规格尺寸区就位（ProductForm → SkuMatrix 的 `RowSelectorSection title="规格尺寸"`）
    if (!(await waitVisible(page.getByText('规格尺寸').first(), 20000))) {
      throw new Error(`建品页 20s 内未见「规格尺寸」区（url=${page.url()}）`)
    }
    // SKU 矩阵区域：规格尺寸区
    const widthSection = page.locator('text=规格尺寸').first()
    await widthSection.waitFor({ state: 'visible', timeout: 8000 })
    // 添加一行规格尺寸（默认无行，需先添加才能看到门幅下拉）
    // ⚠️ 旧形态要求 `title="添加"` ≥ 2 个（「售卖方式 / 规格尺寸两区各一个」）—— **现取只有 1 个**：
    //    「售卖方式（散剪 / 整卷）」是**商品级单选**（SkuMatrix.tsx 顶部注释：「售卖方式不在这里」），
    //    页面上唯一的 `title="添加"` 就是**规格尺寸**区的 `RowSelectorSection`（真栈探针 title 列表实测）。
    //    ⇒ 判据从「≥2 个」改成「**这一个就是规格尺寸区的那个**」+ 点完门幅下拉必须出现（下方断言）。
    const addBtns = page.locator('button[title="添加"]')
    if (!(await waitVisible(addBtns.first(), 15000))) throw new Error('建品页 15s 内未见「添加」按钮')
    const n = await addBtns.count()
    // 规格尺寸区必须**恰有一个**添加按钮（多出来的会被下面「门幅下拉出现」的断言抓到，
    // 但若 >1 个则「点哪个」不再有唯一解 ⇒ 直接判红并具名，不静默取 last）
    if (n !== 1) throw new Error(`建品页 title="添加" 按钮应恰 1 个（规格尺寸区），现取 ${n} 个`)
    await addBtns.first().click()
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
    await nav(page, '/products', '')
    // 列表就位等待（与 08- 同法）：页面标题/表头现取为「商品标题」，旧形态等的「商品列表」文案不存在
    if (!(await waitVisible(page.getByText('商品标题').first(), 20000))) {
      if (!(await waitVisible(page.locator('tbody tr, [role="row"]').first(), 8000))) {
        throw new Error(`商品列表 20s 内未就位（url=${page.url()}）`)
      }
    }
    await page.waitForTimeout(1800)
    const visible = await page.locator(`text=${pname}`).first().isVisible().catch(() => false)
    if (!visible) throw new Error('新建商品未出现在列表（结果不可见）')
    await h.done(true, '', `门幅 值/显示分离 ✓(${JSON.stringify(optInfo)}→'${storedValue}') + 建品可见 ✓(${pname})`)
  } catch (e) {
    await h.done(false, `新建商品页失败: ${String(e).slice(0, 300)}`)
  }
}

async function productDetail(page) {
  // `--group` 过滤掉的旅程记 skip（没跑 ≠ 失败）；这几条**没接在 `jrun` 上**，故各自守卫（#6790）
  if (!inGroup('10-product-detail')) { await markSkipped(h, '--group 10-product-detail 过滤（本轮未跑）'); return }
  const h = await journey('10-product-detail')(page)
  try {
    await ensureLoggedIn(page)
    await nav(page, '/products', '')
    if (!(await waitVisible(page.getByText('商品标题').first(), 20000))) {
      if (!(await waitVisible(page.locator('tbody tr, [role="row"]').first(), 8000))) {
        throw new Error(`商品页 20s 内未就位（url=${page.url()}）`)
      }
    }
    await page.waitForTimeout(800)
    const rows = page.locator('tbody tr, [role="row"]')
    const n = await rows.count()
    if (n === 0) throw new Error('商品列表 0 行，无商品可进详情')
    // 行内「查看」按钮跳详情；草稿行无「查看」（仅编辑/删除），故取第一个有查看按钮的行。
    // ⚠️ 旧形态先 `rows.first()` 判行数、再用 `viewBtn.first()` 点 —— 两者**不是同一行**
    // （issue #6790 B 类 ④：草稿行在前 ⇒ 「用了不存在的商品 id」）。现在按**同一个 xpath**
    // 取「真的有查看按钮的那一行」，行与按钮同源。
    // 行内「查看」只在 `on_sale` / `off_sale` / `under_review` 三种状态渲染（`ProductTable.tsx` 现取）
    // ⇒ 列表全草稿时**自造**一个 `on_sale` 商品（与 11- 同法；跑完删掉），不把「数据形态」记成依赖。
    const viewRowSel = 'tbody tr:has(button:text-is("查看")), [role="row"]:has(button:text-is("查看"))'
    let mine = ''
    if (!(await waitVisible(page.locator(viewRowSel).first(), 4000))) {
      const api = await adminApi(page)
      const created = await api.post('/api/admin/products', {
        name: `冒烟详情商品${Date.now()}`, skuCode: `SMOKE-DT-${Date.now()}`, unit: '米', pricingType: 'per_meter',
        categoryId: process.env.SMOKE_CATEGORY_ID || await defaultCategoryId(page), basePrice: 10,
        status: 'on_sale', doorWidths: ['2.8'], colors: [{ colorName: '冒烟红', mainColorHex: '#ff0000' }],
        sellingMethods: ['bulk_cut'],
      })
      mine = created?.data?.id || created?.id || ''
      if (!mine) throw new Error(`列表 ${n} 行全无「查看」（全为草稿），且自造 on_sale 商品失败：${JSON.stringify(created).slice(0, 160)}`)
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(2500)
    }
    const viewRow = page.locator(viewRowSel).first()
    if (!(await waitVisible(viewRow, 10000))) {
      if (mine) await cleanupProduct(page, mine)
      throw new Error(mine ? `自造 on_sale 商品 ${mine} 后列表仍无「查看」按钮` : `商品列表 ${n} 行但无一行带「查看」`)
    }
    await viewRow.locator('button:text-is("查看")').first().click()
    await page.waitForTimeout(1800)
    const url = page.url()
    if (!/\/products\/[^/]+$/.test(url)) throw new Error(`点击行未跳转详情，仍在 ${url}`)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 50) throw new Error('详情页空白')
    if (mine) await cleanupProduct(page, mine)
    await h.done(true, '', `商品详情渲染（${url}）${mine ? `（自造 on_sale 商品 ${mine} 已清理）` : ''}`)
  } catch (e) {
    await h.done(false, `商品详情失败: ${String(e).slice(0, 300)}`)
  }
}

async function productEdit(page, targetId) {
  // `--group` 过滤掉的旅程记 skip（没跑 ≠ 失败）；这几条**没接在 `jrun` 上**，故各自守卫（#6790）
  if (!inGroup('11-product-edit-doorwidth')) { await markSkipped(h, '--group 11-product-edit-doorwidth 过滤（本轮未跑）'); return }
  const h = await journey('11-product-edit-doorwidth')(page)
  try {
    await ensureLoggedIn(page)
    // 前置数据**自造**（issue #6790 判据 ④）：旧形态吃写死的种子商品 id（`DW_PRODUCT_ID` 默认值），
    // 云 dev 库里该商品已不存在 ⇒ `未找到门幅下拉`（B 类 ④。「未找到门幅下拉」的另一半真因是
    // SkuMatrix 的规格尺寸行**默认 0 行**，门幅 `<select aria-label="规格尺寸">` 要**先点「添加」**才渲染）。
    let id = targetId || process.env.DW_PRODUCT_ID || ''
    let mine = ''
    if (!id) {
      const api = await adminApi(page)
      const dw = `冒烟门幅${Date.now()}`
      const created = await api.post('/api/admin/products', {
        name: dw, skuCode: `SMOKE-DW-${Date.now()}`, unit: '米', pricingType: 'per_meter',
        categoryId: process.env.SMOKE_CATEGORY_ID || await defaultCategoryId(page), basePrice: 10,
        status: 'on_sale', doorWidths: ['2.8'], colors: [{ colorName: '冒烟红', mainColorHex: '#ff0000' }],
        sellingMethods: ['bulk_cut'],
      })
      id = created?.data?.id || created?.id
      if (!id) throw new Error(`前置建品失败（未返回 id）：${JSON.stringify(created).slice(0, 200)}`)
      mine = id
    }
    await nav(page, `/products/${id}/edit`, '')
    await page.waitForTimeout(1800)
    // 规格尺寸区默认无行 ⇒ 先点该区的「添加」（最后一个 title=添加；形态与 09- 一致，现取 `SkuMatrix.tsx`）
    const addBtns = page.locator('button[title="添加"]')
    if (await addBtns.count() > 0) {
      await addBtns.last().click().catch(() => {})
      await page.waitForTimeout(800)
    }
    // 门幅下拉 = `<select aria-label="规格尺寸">`（SkuMatrix.tsx 的 Select + aria-label 字面量）
    const dwSelect = page.locator('select[aria-label="规格尺寸"]').first()
    if (!(await waitVisible(dwSelect, 8000))) throw new Error('未找到门幅下拉（select[aria-label="规格尺寸"]）')
    const wState = await dwSelect.evaluate((sel) => ({
      value: sel.value, options: Array.from(sel.options).map((o) => `${o.value}|${o.text}`),
    }))
    const valueOk = wState.value === '2.8' || wState.value === '2.8米'
    const labelOk = wState.options.some((o) => o.endsWith('|2.8米'))
    if (!valueOk || !labelOk) throw new Error(`门幅回显异常: ${JSON.stringify(wState)}`)
    if (wState.options.some((o) => o.endsWith('|2.8'))) throw new Error('存在裸 2.8 显示选项（第二种写法）')
    if (mine) await cleanupProduct(page, mine)
    await h.done(true, '', `门幅下拉回显: value=${wState.value}, 选项=${JSON.stringify(wState.options)}${mine ? `（自造商品 ${mine} 已清理）` : '（用既有目标商品）'}`)
  } catch (e) {
    await h.done(false, `门幅回显失败: ${String(e).slice(0, 300)}`)
  }
}


// ────────────────────────── 加工项管理 ──────────────────────────
async function processingJourney(page) {
  const h = await journey('12-processing', { allowKnownConsole: true })(page)
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
    // 加工分类（#4882 起表单只剩「名称 + 加工分类」两个必填项，单价/计价方式两项已退场）
    const categorySelect = page.locator('select').first()
    await categorySelect.selectOption({ index: 1 }).catch(() => {})
    // 提交
    await page.getByRole('button', { name: /确 定|保存|提交|创建/ }).last().click()
    await page.waitForTimeout(1500)
    // 结果可见：列表出现新建项
    const row = page.locator(`text=${uniq}`).first()
    await row.waitFor({ state: 'visible', timeout: 8000 })
    const rowText = await row.locator('xpath=ancestor::tr[1]').innerText().catch(() => '')
    // #4882 防回退锁：加工项列表**不得**再出现单价 / 计价方式
    if (/单价|价格|计价方式/.test(rowText)) {
      recNote(h, `加工项列表行仍含单价/计价方式（#4882 应已删除）：${rowText.slice(0, 120)}`)
    }
    // 编辑：只改名（部分更新），其它字段应保留
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
// ⚠️ 字段 placeholders **逐字**取自 `frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx`
// （「请输入收货人姓名」/「请输入 11 位手机号」/「请输入详细收货地址」/「搜索商品名称 / 货号」）——
// 旧形态写的是 `placeholder*="收货人姓名"` 这类**猜测值**（issue #6790 B 类 ④：等它超时）。
async function ordersNewJourney(page) {
  const h = await journey('15-orders-new')(page)
  try {
    await ensureLoggedIn(page)
    await nav(page, '/orders/new', '')
    // 等表单就位（客户 API / 分类 API 回来前不渲染）——旧形态定长 1800ms 后盲填会假红
    const nameInput = page.locator('input[placeholder*="收货人姓名"]').first()
    if (!(await waitVisible(nameInput, 15000))) {
      throw new Error('收货信息表单 15s 内未就位（url=' + page.url() + '）')
    }
    await nameInput.fill('冒烟测试员')
    await page.locator('input[placeholder*="手机号"]').first().fill('13900001111')
    await page.locator('input[placeholder*="收货地址"]').first().fill('杭州市西湖区冒烟路 1 号')
    // 打开商品选择弹窗（搜索框在弹窗内）
    const pickBtn = page.getByRole('button', { name: /选择商品/ }).first()
    await pickBtn.waitFor({ state: 'visible', timeout: 8000 })
    await pickBtn.click()
    await page.waitForTimeout(800)
    // 弹窗内搜索商品。⚠️ 旧形态把搜索词**写死成 `遮光窗帘`** —— 本租户没有这个商品
    //    ⇒ 搜索结果恒空、恒报「商品搜索结果为空」（真栈实测）。商品名是**种子数据**，不是判据的一部分；
    //    正确口径 = 先用列表 API 取一个**真实存在的**商品名当搜索词，再断言「搜索能搜到并可选」。
    const kw = (await (async () => {
      const api = await adminApi(page)
      const res = await api.get('/api/admin/products?page=1&size=1')
      const rows = res?.data?.items ?? res?.data ?? []
      const name = rows[0]?.name || ''
      if (!name) throw new Error('商品搜索结果为空（/api/admin/products 里一个商品都没有 ⇒ 前置数据缺失）')
      return name
    })())
    const searchInput = page.locator('[role="dialog"] input[placeholder*="搜索商品"]').first()
    await searchInput.waitFor({ state: 'visible', timeout: 6000 })
    await searchInput.fill(kw)
    await page.getByRole('button', { name: /^搜索$/ }).click().catch(async () => {
      await page.locator('[role="dialog"] button:has-text("搜索")').click()
    })
    await page.waitForTimeout(1500)
    // 选中第一个商品结果（用它自己的名字当过滤词 —— 语义与旧形态一致：搜到了就选）
    const result = page.locator('[role="dialog"] button').filter({ hasText: kw.slice(0, 8) }).first()
    if (await result.isVisible().catch(() => false)) {
      await result.click()
      await page.waitForTimeout(2000)
    } else {
      throw new Error(`商品搜索结果为空（搜索词 = 列表首个商品名「${kw}」，搜不到 ⇒ 搜索链路退化）`)
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
// 返回**本次实际驱动的那张单**的 id（自造或调用方传入）—— 下游 `17-order-ship` 直接复用它，
// 不再靠 `process.env.API_TOKEN`（从没有人传 ⇒ 恒空，issue #6790 B 类 ③）。
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
    await ensureLoggedIn(page)
    // 前置**依赖**（登记式）：加工单要能**实例化**才能谈「加工单块」——而实例化要求本租户已配
    // 生产路线 / 默认工艺（真栈实测：`INCIDENT_PRODUCTION_ROUTING_UNRESOLVED`，接口 HTTP 200 但 data 空）。
    const dep = await processingRouteAvailable(page)
    if (!dep.ok) { await markSkipped(h, `前置不满足（生产路线/默认工艺未配置）：${dep.why}`); return orderId }
    // 前置数据**自造**（issue #6790 判据 ④）：`orderId` 为空时不再判失败，而是造一张 pending 含加工项订单
    let selfMade = false
    if (!orderId) {
      orderId = await createOrderFixture(page, '冒烟详情')
      selfMade = true
    }
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
    await h.done(true, '', `加工单生成+流转: ${flowDone}; 加工单 ${poNo} 可见=${poVisible}${selfMade ? `；前置自造订单 ${orderId}（下游 17- 复用，不清理）` : `；用调用方传入订单 ${orderId}`}`)
    return orderId
  } catch (e) {
    await h.done(false, `订单详情失败: ${String(e).slice(0, 400)}`)
  }
  return orderId
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
    // 前置**依赖**（登记式，与 16-/17- 同源）：本租户要能**实例化加工单**（生产路线 / 默认工艺已配），
    // 否则本旅程的判据（加工单二维码 / 报工）无从谈起。⚠️ 必须在**建单之前**探：旧位置在建单之后
    // ⇒ 未配路线时旅程先撞别的错（真栈实测 `[③ qr_token] 非 32 位十六进制：undefined`），
    // 把「前置缺失」读成了业务失败。
    const dep = await processingRouteAvailable(page)
    if (!dep.ok) { await markSkipped(h, `前置不满足（生产路线/默认工艺未配置）：${dep.why}`); return }

    // ① 建单（含加工项）—— 独立数据，不污染存量
    const created = await api.post('/api/admin/orders', {
      customerName: '生产旅程', customerPhone: '13900003333', customerAddress: '杭州市西湖区生产路 1 号',
      // ⚠️ 真栈 422 逐字：「常用物流/快递不能为空」+「常用物流公司不能为空」⇒ 必填（与 createOrderFixture 同法）
      logisticsType: 'express', logisticsCompany: '顺丰速运',
      discountAmount: 0, items: [{
        productId: 'deff0be6c885cbf0469abe4f7b8da608', productName: '2699系列雪尼尔窗帘面料',
        quantity: 2, unitPrice: 23.8, subtotal: 47.6,
        processingInfo: { sellingMethod: 'bulk_cut', doorWidth: '2.8', processingFee: 15,
          processingItems: [{ id: 'proc_item_1', name: '锁边', quantity: 2, unit: '米' }] }
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
    await ensureLoggedIn(page)
    // 前置**依赖**（登记式，与 16- 同源）：发货页的「须先完成加工单」守卫要求加工单能流转到 completed，
    // 而流转又要先实例化加工单（craft / 生产路线）⇒ 本租户未配路线时本旅程**无从跑起**。
    const dep = await processingRouteAvailable(page)
    if (!dep.ok) { await markSkipped(h, `前置不满足（生产路线/默认工艺未配置）：${dep.why}`); return }
    // 🔴 issue #6790 B 类 ③：`orderId` 为空时旧形态导航到 `/orders//ship` —— Next 把两级路径
    // `/orders/ship` 当成 `/orders/[id]`（id='ship'）⇒ api 日志 `请求的资源不存在: GET /api/admin/orders/ship`。
    // 现在：空 ⇒ **自造一张含加工项订单**（与 16- 同法，自造前置，不登记依赖）。
    if (!orderId) orderId = await createOrderFixture(page, '冒烟发货')
    await nav(page, `/orders/${orderId}/ship`, '')
    // 等页面**稳定**再判，而不是定长 sleep 后数控件（issue #4226②）：含加工项订单要等
    // GET /processing-orders/{orderId} 回来才决定渲染「发货表单」还是「加工单守卫页」，
    // 1500ms 内没回来就判「无表单」是**假红**；两种终态都要能分辨（否则归因不可读）。
    const submit = page.getByRole('button', { name: /确认发货/ }).first()
    const guard = page.getByText(/须先完成加工单后再发货|当前订单状态不允许发货/).first()
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
  const h = await journey('19-after-sales-detail', { allowKnownConsole: true })(page)
  const reason = `冒烟关闭原因${Date.now()}`
  let selfMade = ''
  try {
    await ensureLoggedIn(page)
    const api = await adminApi(page)
    // 前置数据**自造**（issue #6790 判据 ④）：旧形态「从列表点首行取 id」在列表为空时报
    // 「等 售后管理 超时」（B 类 ④）—— 那是**前置缺失被读成产品失败**。现在先经 API 自造一张工单。
    if (!ticketId) {
      // 工单要挂在真实订单上：先自造一张订单，再对它建单（订单号字段 = 后端解析所需的 orderId）
      const orderId = await createOrderFixture(page, '冒烟售后')
      // 退款/退货工单要求订单已确认（真栈 422 逐字：「当前订单状态[待付款]不允许创建退款/退货工单，
      // 仅已确认/生产中/已发货/已完成可创建」）⇒ 先确认付款（与 16- 的第一步同法），再建单。
      await api.put(`/api/admin/orders/${orderId}/payment`, {})
      const ticket = await api.post('/api/admin/after-sales', {
        orderId, ticketType: 'refund', description: '冒烟自造售后工单', priority: 'normal',
      })
      ticketId = String(ticket?.data?.id ?? '')
      selfMade = ticketId
      if (!ticketId) throw new Error(`前置建单失败（未返回 data.id）：${JSON.stringify(ticket).slice(0, 200)}`)
    }
    await nav(page, `/after-sales/${ticketId}`, '')
    await page.waitForTimeout(1500)
    if (!(await waitVisible(page.getByText('售后管理').first(), 8000))) {
      // 详情页可能没有列表页标题 → 用「详情页骨架」兜底判定，两者都没有才算页面没渲染
      const bodyLen = await page.evaluate(() => document.body.innerText.length)
      if (bodyLen < 50) throw new Error(`售后详情页空白（${page.url()}）`)
    }
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
  // ⚠️ 手机号**现取**（旧形态：创建用 `139${...}`、编辑断言写死 `13911113333`，两者永不同步
  // ⇒ 「改手机号落库」的证据恒 false，属**空判据**，issue #6790 B 类）。
  const phoneAdd = `139${Date.now().toString().slice(-8)}`
  const phoneEdit = `138${Date.now().toString().slice(-8)}`
  try {
    await ensureLoggedIn(page)
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
    await dlg.locator('input[placeholder*="手机号"]').fill(phoneAdd)
    // 🔴 issue #6790 原文「POST /api/admin/users 调用次数 = 0」的真因：登录用户名 / 初始密码是**必填**，
    //    旧旅程不填 ⇒ 提交时 `请设置登录用户名` 直接 return（请求从未发出）。这里补上（现取自 employees/page.tsx）。
    const uniqUser = `smoke${Date.now().toString().slice(-9)}`
    const userInput = dlg.locator('input[placeholder*="员工登录账号"], input[placeholder*="zhangsan"]').first()
    if (await waitVisible(userInput, 4000)) await userInput.fill(uniqUser)
    const pwdInput = dlg.locator('input[placeholder*="初始密码"], input[type="password"]').first()
    if (await waitVisible(pwdInput, 4000)) await pwdInput.fill('Smoke@123456')
    // 选岗位（弹窗内的岗位下拉）
    // ✅ issue #6790 B 类 ①：`dlg.locator('select')` **不是**死选择器 —— 岗位控件 = 共享
    //    `frontend/admin-web/src/components/ui/Select.tsx` 渲染的**原生** `<select>`（含
    //    `<option value="" disabled>请选择岗位</option>`），api 侧 `POST /api/admin/users` 调用数 = 0
    //    的真因是**上游步骤**先失败（空提交校验点了「创建」触发表单校验），不是选择器。
    //    这里把「控件真在不在」做成**具名证据**（取到才继续），并等它就位（不再定长 sleep 后盲取）。
    const posSelect = dlg.locator('select').first()
    if (!(await waitVisible(posSelect, 8000))) {
      const nSel = await dlg.locator('select').count()
      throw new Error(`弹窗内未见岗位下拉（原生 select）：dlg 内 select 计数=${nSel}、`
        + `页面 select 计数=${await page.locator('select').count()}（控件形态见 Select.tsx）`)
    }
    const posOpts = await posSelect.locator('option').allTextContents().catch(() => [])
    const realIdx = posOpts.findIndex(t => t !== '' && !t.includes('请选择') && t !== '全部状态' && t !== '启用' && t !== '禁用')
    if (realIdx < 0) throw new Error(`岗位下拉无可用选项（现取 option 文案=${JSON.stringify(posOpts)}）`)
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
    await page.locator('input[placeholder*="手机号"], input[name="phone"]').first().fill(phoneEdit)
    await page.getByRole('button', { name: /确 定|保存/ }).last().click()
    await page.waitForTimeout(1500)
    // ✅ issue #6790 B 类：（旧形态断言写死的 `13911113333`，与自造值 `phoneEdit` **永不同步**
    // ⇒ 证据恒 false）。现在断言**本次真填的那个值**回显。
    const phoneShown = await page.getByText(phoneEdit).first().isVisible().catch(() => false)
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
    await ensureLoggedIn(page)
    await nav(page, '/roles', '岗位权限')
    await page.waitForTimeout(1500)
    const rows = page.locator('tbody tr, [role="row"], [class*="card"]')
    const n = await rows.count().catch(() => 0)
    if (n === 0) throw new Error('岗位列表 0 行')
    // ✅ issue #6790 B 类 ②：旧形态 `getByRole('button', { name: /编辑|权限/ }).first()` 的**首个匹配
    // 是侧边栏「加入常用」控件**（可及名字含「岗位权限」）⇒ 点了它只切换收藏，行内编辑按钮一个都没点到
    // （探针实测 `["0:|title=加入常用","1:|title=编辑",…]`；点后 `弹窗可见=false`，等 6s 超时）。
    // 现在按**真实 DOM 收窄到行内**：岗位卡片的编辑按钮 = `button[title="编辑"]`
    // （`frontend/admin-web/src/app/(dashboard)/roles/page.tsx` 的 `handleEdit(role)`），
    // 侧边栏收藏控件没有这个 `title` ⇒ 不再跨页命中。
    const editBtn = page.locator('button[title="编辑"]').first()
    if (!(await waitVisible(editBtn, 8000))) {
      const titles = await page.locator('button[title]').evaluateAll((els) => els.map((e) => e.getAttribute('title')))
      throw new Error(`未找到行内「编辑」按钮（button[title="编辑"]）；页面带 title 的按钮=${JSON.stringify(titles).slice(0, 200)}`)
    }
    await editBtn.click()
    await page.waitForTimeout(1000)
    const dlg = page.locator('[role="dialog"], [class*="Modal"], [class*="modal"]').first()
    if (!(await waitVisible(dlg, 8000))) throw new Error('点击行内「编辑」后权限编辑弹窗未出现')
    await page.getByRole('button', { name: /取消/ }).last().click().catch(() => {})
    await h.done(true, '', `岗位权限页 ${n} 行，行内「编辑」（button[title="编辑"]）打开权限弹窗 ✓`)
  } catch (e) {
    await h.done(false, `岗位权限失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 设置 ──────────────────────────
/**
 * 设置页旅程 = **只读校验**（issue #6790 C 类）：
 * `frontend/admin-web/src/app/(dashboard)/settings/page.tsx` 自 #5899 起**取消了底部「保存」按钮**，
 * 改为**字段失焦即落库**（`onBlur={commitCompanyName}` / `commitCode` / 通知开关点击即存）。
 * 旧旅程点「保存」并在 Tab 间切换 ⇒ 触发失焦提交，而它**改到的值不是合法值**（企业编码一类）
 * ⇒ console `422` ×2、页面停在错误态（issue #6790 逐字读数）。
 * ⇒ 本旅程**只读**：不改任何值、不点「保存」、不制造失焦；把 422 收集成**结构化证据**并在末尾硬判失败
 *（旧的 `console.error` 只在 console 行里，读起来像噪声）。
 */
async function settingsJourney(page) {
  const h = await journey('25-settings')(page)
  const bad = []
  const onResponse = (r) => { if (r.status() >= 400 && r.status() < 500) bad.push(`${r.status()} ${r.request().method()} ${r.url()}`) }
  page.on('response', onResponse)
  const origDone = h.done
  h.done = async (ok, why, ev) => { page.removeListener('response', onResponse); return origDone(ok, why, ev) }
  try {
    await ensureLoggedIn(page)
    await nav(page, '/settings', '')
    // 等设置页就位：企业基础信息 tab 的输入（企业编码 / 公司名称）或任一设置分组标题
    if (!(await waitVisible(page.getByText(/企业基础信息|公司名称|企业编码|算料口径/).first(), 20000))) {
      throw new Error(`设置页 20s 内未就位（url=${page.url()}）`)
    }
    await page.waitForTimeout(1500)
    // Tab 结构：基本信息/修改密码/通知设置
    const tabs = await page.locator('[role="tab"], [class*="tab"], button:has-text("修改密码"), button:has-text("通知")').count()
    // #5899 口径：本页**没有**「保存」按钮，改动即时生效（页面上必须说出来）
    const autoSaveHint = await page.getByText(/自动保存|即时生效|失焦即存/).first().isVisible().catch(() => false)
    if (!autoSaveHint) {
      // 兜底：页面上任何含「保存」的说明文字（#5899 后本页**没有**底部保存按钮 ⇒ 必须说出来）
      const hintText = await page.getByText(/保存/).first().textContent().catch(() => '')
      if (!hintText) throw new Error('设置页未见「自动保存」类提示（#5899 口径：无底部保存按钮 ⇒ 必须说明保存方式）')
      h.rec.notes.push(`自动保存提示按「含保存二字的说明文字」判定：${String(hintText).slice(0, 60)}`)
    }
    const hasSaveBtn = await page.getByRole('button', { name: /^保存$/ }).first().isVisible().catch(() => false)
    if (bad.length) throw new Error(`只读访问期间出现写请求失败（本旅程不改任何值）：${bad.join(' | ')}`)
    // 只读地看「修改密码」表单（**不点、不填、不失焦**）
    const pwdTab = page.getByRole('button', { name: /修改密码/ }).first()
    let pwdFields = 0
    if (await pwdTab.isVisible().catch(() => false)) {
      await pwdTab.click()
      await page.waitForTimeout(800)
      pwdFields = await page.locator('input[type="password"]').count()
    }
    if (bad.length) throw new Error(`切换 Tab 期间出现 4xx（失焦自动提交被触发）：${bad.join(' | ')}`)
    await h.done(true, '', `设置页只读校验：Tab 数=${tabs}、自动保存提示=${autoSaveHint}、意外「保存」按钮=${hasSaveBtn}、密码字段=${pwdFields}、4xx=${bad.length}`)
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
    // 🔴 名字与 `jrun('27-corporate', …)` 的注册名**不同** ⇒ `jrun` 的前缀过滤看不到它们
    // ⇒ 过滤跑时会静默全跑（issue #6790）。各自守卫。
    if (!inGroup(name)) { await markSkipped(h, `--group ${GROUP} 过滤（本轮未跑）`); continue }
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
async function jrun(name, fn, page, deps) {
  // `--group <前缀>` 过滤掉的旅程**记 skip、不记失败**（issue #6790）：skip ≠ pass、也 ≠ fail。
  if (!inGroup(name)) { recordSkip(name); return }
  // 前置数据/依赖不满足 ⇒ 同样记 skip 并印出缺什么（`depends_on`，issue #6790 判据 ④）
  const missing = Object.entries(deps || {}).filter(([, v]) => !v).map(([k]) => k)
  if (missing.length) { recordSkip(name, `前置不满足（缺 ${missing.join(' / ')}）：未跑，不是失败`); return }
  const timer = new Promise((_, rej) => setTimeout(() => rej(new Error(`${name} 超时 ${J_TIMEOUT / 1000}s`)), J_TIMEOUT))
  try {
    await Promise.race([fn(page), timer])
  } catch (e) {
    const msg = String(e.message || e).slice(0, 200)
    console.log(`❌ ${name}\n   超时/异常: ${msg}`)
    results.push({ journey: name, pass: false, skipped: false, unconfigured: false, error_class: null, errors: [`超时/异常: ${msg}`], notes: [], evidence: [] })
  }
}

/** 记一条「本轮未跑」的旅程（skip ≠ pass、也 ≠ fail；#6790）。 */
function recordSkip(name, why) {
  results.push({ journey: name, pass: false, skipped: true, unconfigured: false, error_class: 'skip',
    errors: [], notes: [why || `--group ${GROUP} 过滤（本轮未跑）`], evidence: [] })
  console.log(`⏭️  ${name} [skip] ${why || `--group ${GROUP} 过滤（本轮未跑）`}`)
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()

  // 登录 + 会话保持（同一上下文内完成，保证后续旅程带登录态）
  await jrun('01-login', async (p) => {
    const h = await journey('01-login')(p)
    await smsLogin(p, { where: '01-login/main', settleMs: 1200 })
    await expectText(p, '经营看板')
    await p.reload({ waitUntil: 'domcontentloaded' })
    await p.waitForURL('**/dashboard**', { timeout: 10000 })
    await expectText(p, '经营看板')
    await h.done(true, '', 'login → /dashboard，刷新后会话保持')
  }, page)

  // 🔴 整轮看门狗（#6790）：16-/17- 不再吃 `jrun` 的 45s 上限 ⇒ 加一道**整轮**硬闸，
  // 避免任何一处 `waitFor` 挂死后把真栈会话拖到没有读数。25min 覆盖「造数据 + 全流转」的最坏路径。
  const RUN_BUDGET_MS = Number(process.env.SMOKE_RUN_BUDGET_MS || 25 * 60 * 1000)
  const runWatchdog = new Promise((resolve) => setTimeout(() => {
    console.log(`\n⚠️ 整轮预算 ${RUN_BUDGET_MS / 1000}s 到点：停止本轮（已完成的旅程仍在下方汇总）`)
    resolve('budget')
  }, RUN_BUDGET_MS))

  // 依序执行旅程
  const runAll = (async () => {
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
  // ⚠️ 不再用写死的种子商品 id（`e7fbe9da…` 已从云 dev 库消失 ⇒「用了不存在的商品 id」，
  // issue #6790 B 类 ④）。空 ⇒ `productEdit` 内部**自造**一件门幅 2.8 的商品（跑完清理）。
  const dwTarget = process.env.DW_PRODUCT_ID || ''
  await jrun('11-product-edit-doorwidth', (p) => productEdit(p, dwTarget), page)

  await jrun('12-processing', processingJourney, page)
  await jrun('13-categories', categoriesJourney, page)
  await jrun('14-orders-list', ordersListJourney, page)
  await jrun('15-orders-new', ordersNewJourney, page)

  // 订单详情 / 发货：**前置自造**（见 createOrderFixture）。
  // ⚠️ 旧形态靠 `process.env.API_TOKEN`（**仓库里没有任何调用方传过它** ⇒ `orderId` 恒空）：
  //    `16-` 报「无目标订单」、`17-` 导航到 `/orders//ship` ⇒ api 日志
  //    `请求的资源不存在: GET /api/admin/orders/ship`（issue #6790 B 类 ③）。此死路已删。
  // 这两条**不走 `jrun` 的 45s 硬超时**：16- 现在要「现造 + 全流转」，45s 偏紧；
  // 它们内部每一步都有显式 `waitVisible` 超时，不会挂死。
  let detOrderId = process.env.ORDER_ID || ''
  if (inGroup('16-order-detail-processing-order')) {
    detOrderId = await orderDetailJourney(page, detOrderId)
  } else {
    recordSkip('16-order-detail-processing-order')
  }
  // #4186 收口：加工单二维码 / 工序列 / 计件的**正向**分支（自带建单，不依赖 16- 的数据）
  await jrun('32-production-qr-and-piecework', productionQrJourney, page)
  if (inGroup('17-order-ship')) {
    await orderShipJourney(page, detOrderId)
  } else {
    recordSkip('17-order-ship')
  }
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
  })()

  await Promise.race([runAll, runWatchdog])
  // 预算到点：剩下的旅程显式记 skip（不是失败）
  const recorded = new Set(results.map((r) => r.journey))
  for (const n of ALL_JOURNEY_NAMES) {
    if (!recorded.has(n)) recordSkip(n, `整轮预算 ${RUN_BUDGET_MS / 1000}s 到点：本轮未跑`)
  }

  await browser.close()

  // 汇总输出（#6790：pass / fail / 未配置 / skip **四态分列**，不许互相冒充）
  const passed = results.filter(r => r.pass).length
  const unconfigured = results.filter(r => r.unconfigured)
  const skipped = results.filter(r => r.skipped)
  const failed = results.filter(r => !r.pass && !r.unconfigured && !r.skipped)
  const md = [
    '# 商家后端 UI 冒烟结果',
    '',
    `时间: ${new Date().toISOString()} ｜ 通过 ${passed}/${results.length} ｜ 失败 ${failed.length}`
      + ` ｜ 未配置 ${unconfigured.length} ｜ skip ${skipped.length}`,
    '',
    '| # | 旅程 | 结果 | 证据 |',
    '|---|------|------|------|',
  ]
  results.forEach((r, i) => {
    const ev = r.evidence.filter(e => !e.startsWith('/') || e.endsWith('.png')).join('; ').slice(0, 160)
    const err = r.errors.join(' / ').slice(0, 120)
    const mark = r.unconfigured ? '➖ 未配置' : r.skipped ? '⏭️ skip' : r.pass ? '✅' : '❌'
    md.push(`| ${i + 1} | ${r.journey} | ${mark} | ${ev || err || (r.notes.join(' / ').slice(0, 160)) || '—'} |`)
  })
  if (unconfigured.length) {
    md.push('', '## ➖ 未配置（**不是**产品失败）', '',
      `以下 ${unconfigured.length} 条依赖 ai-agent，而本轮未按 AGENTS.md 传 \`AI_AGENT_BASE_URL\` / \`AI_AGENT_SERVICE_TOKEN\`：`,
      '', ...unconfigured.map(r => `- ${r.journey}`))
  }
  if (skipped.length) {
    md.push('', '## ⏭️ skip（前置/依赖不满足，**未跑**）', '',
      ...skipped.map(r => `- ${r.journey}：${r.notes.join(' / ').slice(0, 160)}`))
  }
  wfs(join(OUT, 'smoke-summary.md'), md.join('\n'))
  wfs(join(OUT, 'smoke-results.json'), JSON.stringify(results, null, 2))
  console.log(`\n===== 汇总: ${passed}/${results.length} 通过，${failed.length} 失败`
    + `，${unconfigured.length} 未配置（ai-agent 未配置），${skipped.length} skip（前置不满足）=====`)
  if (failed.length) console.log(`❌ 真实失败：${failed.map(r => r.journey).join(' ')}`)
  if (unconfigured.length) console.log(`➖ 未配置：${unconfigured.map(r => r.journey).join(' ')}`)
  if (skipped.length) console.log(`⏭️  skip：${skipped.map(r => r.journey).join(' ')}`)
  // 退出码只由**真实失败**决定：未配置 / skip 都不是产品失败（#6790 判据 ③④）
  process.exit(failed.length > 0 ? 1 : 0)
}

main()
