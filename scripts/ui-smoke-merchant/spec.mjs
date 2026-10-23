// MIGAO 商家后端（admin-web）全面功能冒烟 spec —— 真浏览器 + 真后端 + 商家 persona
// 阶段 1：admin-web 全部页面（33 旅程）。用法：node spec.mjs [--group 名称前缀]
// 环境：BASE_URL（默认 http://127.0.0.1:3001）、OUT_DIR（截图/报告输出目录）、PHONE、SMS_CODE
// case_ids: UI-014, UI-016（admin-web 全站冒烟，视觉/布局旅程）
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
// 判据最小单元（issue #4226）：加工单号**形态**判据 + 404 探测豁免的**结构化**判据。
// 抽到同目录纯函数模块的理由：它们的可信度要能单独验证（见 criteria.test.mjs，node:test 无新依赖）。
// issue #6982 追加：发货页三态（form/guard/none）与「发货单条数**恰 +1**」两条纯判据同源。
import { ORDER_NO_SHAPE, matchProcessingOrderNo, isConsoleProbe404, isProbe404Exempt, SHIP_FORM_MARKERS, classifyShipPage, shipmentDeltaOk } from './criteria.mjs'

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
// .env 值两侧可能带引号（本文件**不用字面量**写那两个引号字符：`tests/unit_ci_workflows/
// _source_parsing.py` 的 `java_code()` 词法走查**不认正则字面量**，正则里的引号会被当成字符串定界符
// ⇒ 从那一行起不再剥注释 ⇒ 名称台账判据读到注释里的旧注册名（**假红**，2026-10-16 实测））
const QUOTES = /[\u0022\u0027]+/g
mkdirSync(OUT, { recursive: true })
mkdirSync(join(OUT, 'screenshots'), { recursive: true })

const results = []
const failReasons = new Map()
// ── 冒烟自造对象台账（SDQS D4，docs/testing/smoke-data-quality.md）──────────────
// 为什么需要它：自造数据要能**枚举 / 体检 / 清理自证**。旧形态里 `productsNew` 建完就不管
// （商品列表长期被「冒烟SKU商品…」占据），而「自造了几件 / 几件有 SKU / 清掉了几件」没有任何读数
// ⇒ `scripts/smoke_data_quality.py` 的 DQ-2 / DQ-5 无从判定（数据面只能靠人看）。
const FIXTURES = { products: [], orders: [] }
const recordFixture = (kind, rec) => { FIXTURES[kind].push(rec); return rec }
const markFixtureCleaned = (id) => {
  const f = FIXTURES.products.find((x) => x.id === id)
  if (f) f.cleaned = true
}
// 失败响应账本（本轮新增）：`console.error` 只说「401」不说是**谁**返回的 —— 没有 URL 就无法归因
// （2026-10-14 实测：单看 console 文案分不清是 admin-api 还是 ai-agent，归因卡死）。
const failedResponses = []
// ────────────────────────── 结果分类（#6790 / AGENTS.md 铁律）──────────────────────────
// 三态，**不许互相冒充**（issue #6790 判据 ③④）：
//   pass         —— 真跑并通过；
//   unconfigured —— 依赖面**未配置**（ai-agent 未按 AGENTS.md 传 BASE_URL/SERVICE_TOKEN）⇒ 成因不在产品；
//   skipped      —— 前置数据/依赖不满足（`depends_on`）⇒ 没跑，不是失败也不是通过。
// ⚠️ 「没跑」必须长得像「没跑」：这两种都不算 pass，也不与真实失败混在一张表里。
const UNCONFIGURED = process.env.SMOKE_UNCONFIGURED === '1'
// 未配置的**具体成因**（起栈脚本按形态给出，例如 #6801 的验签公钥失配）——
// 没有它，「未配置」只剩一个笼统标签，排查还得回去翻日志。
const UNCONFIGURED_WHY = (process.env.SMOKE_UNCONFIGURED_WHY || '').trim()
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
  // 🔴 issue #6982：`17-` 只判「发货页表单渲染（N 控件）」即 done(true)、**不点【确认发货】**
  //   ⇒ 云 dev 库 `order_shipments` 全表长期 **0 行**（「发货单」这个单据从没被真发过一次）。
  //   本旅程**真点【确认发货】+ 从 API/真库读回**断言落地；名字用 `17b-` 前缀是**有意**的 ——
  //   它与 `17-order-ship` 同族（同一页面的另一种终态），`--group 17` 会**两条一起跑**
  //   （若叫 `33-`，`--group 17` 只跑渲染那条 ⇒ 真提交这条在单组验收里**根本不跑** = 空判据）。
  '17b-ship-order-real',
  '18-after-sales-list', '19-after-sales-detail', '20-customers-list', '21-customer-detail',
  '22-finance', '23-employees', '24-roles', '25-settings', '26-notifications',
  // 🔴 2026-10-15（issue #6942 ③）台账 ⇄ **实际注册名**同批对齐：旧形态写的是
  //   `27-corporate` / `28-register`，而看门狗到点时补记 skip 用的是**台账里的名字**
  //   ⇒ 给**不存在的旅程**补记 skip（实测 `--group 28` 匹配不到任何旅程：0 pass / 0 fail / 29 skip）。
  //   下面 5 个名字逐字取自各自的注册点（`journey('<名>')`），与台账的**双向**对账
  //   （台账 ⊄ 实际 / 实际 ⊄ 台账都算漂移）由 `test_ui_smoke_name_ledger.py` 判据 G（静态面）
  //   + 本文件 finalize 的 `journeyLedgerDrift()`（运行面：**记了却没登记**的名字当场红）共同盯着。
  '27-corporate-home', '28-corporate-about', '29-corporate-contact', '30-corporate-services',
  '31-register',
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

/**
 * 浏览器为**失败请求**另打的那条 console 文案（形如 `[console.error] Failed to load resource: the
 * server responded with a status of 400 ()`，**不带 URL**）。
 * 为什么要有它：issue #6942 ② 的发码 400 在 console 面**只能靠「这次登录确实点过发码」这个上下文 +
 * 条数**来消化（URL 在 `[http]` 那条上），而判据（`test_ui_smoke_criteria_trust.py`）**禁止**把这个
 * 文案连同它的匹配散落在豁免逻辑里 ⇒ 抽成**一个**判据函数：**按前缀/条数消化，不按文案做匹配**。
 */
const isConsoleResourceLoadError = (e) => {
  const s = String(e)
  return s.startsWith('[console.error] ')
    && s.includes('resource')
    && /\b\d{3}\b/.test(s)
}

/**
 * issue #6942 ① 的**类级判据**：`[http] 404 GET /api/admin/products/<id>` ⇒ 返回那个 `id`。
 *
 * 病灶形态（issue 正文逐字）：`404 GET /api/admin/products/73cc4ac45d4053719865a88d3570b932`
 * —— 旅程打向一件**已被删掉**的商品（同轮里它上一次还是绿的 ⇒ 数据依赖）。
 * 只认「商品**详情**」这一条路径（`/api/admin/products/<id>`），列表/计数端点不在射程内。
 * `SMOKE_PRODUCT_404_STRICT=1` 会让它**不靠 console 面**也能判红（判据红证的注入点，见
 * `test_ui_smoke_name_ledger.py::test_product_404_criterion_can_be_injected_red`）。
 */
/** 该失败响应是不是「我们确实点过发码、而后端拒了」的那一条（issue #6942 ②）。 */
const smsSendToleratedResponse = (status, method, url) =>
  Number(status) >= 400 && method === 'POST' && String(url).includes('/api/auth/sms/send')

const PRODUCT_DETAIL_404 = /\[http\] 404 GET (https?:\/\/[^\s]*\/api\/admin\/products\/[^\s/]+)$/
const product404Missing = (errs) => {
  const hits = errs.map((e) => (String(e).match(PRODUCT_DETAIL_404) || [])[1]).filter(Boolean)
  if (hits.length) return hits
  return process.env.SMOKE_PRODUCT_404_STRICT === '1' ? errs.filter((e) => String(e) === '[smoke-inject] product-404') : []
}

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
    // 判据红证的注入点（issue #6942 ①）：`SMOKE_PRODUCT_404_STRICT=1` 时把这一条塞进本旅程的错误面
    // ⇒ `product404Missing()` 必须判红。**只在显式开了这个开关时**才注入（默认零影响）。
    if (process.env.SMOKE_PRODUCT_404_STRICT === '1') errs.push('[smoke-inject] product-404')
    const failedFrom = failedResponses.length
    page.removeAllListeners('console')
    page.removeAllListeners('pageerror')
    const onConsole = (msg) => {
      if (msg.type() !== 'error') return
      const text = msg.text().slice(0, 300)
      errs.push(`[console.error] ${text}`)
    }
    const onPageError = (err) => errs.push(`[pageerror] ${String(err).slice(0, 300)}`)
    page.on('console', onConsole)
    page.on('pageerror', onPageError)
    const done = async (ok, why, ev, errClass) => {
      page.removeListener('console', onConsole)
      page.removeListener('pageerror', onPageError)
      // 把本旅程窗口内的**失败响应**（带 URL）并进错误清单，让 401 可归因（上述账本）
      for (const f of [...new Set(failedResponses.slice(failedFrom))]) errs.push(`[http] ${f}`)
      // 发码 400 的**带标签**消化（issue #6942 ②）。边界（照实说清，避免「凡是 400 都放过」）：
      //   · 判据是**结构化**的：本旅程窗口内确实出现过 `[http] <状态> POST /api/auth/sms/send`（URL 可核）；
      //   · **按条数**摘掉：每次发码失败 = 1 条 `[http]` + 浏览器为那次失败另打的 1 条**无 URL 的**
      //     「资源加载失败」console 文案 ⇒ 摘 `1 × 发码失败次数` 条 console（**不是**「凡是 400 都吞掉」：
      //     页面上别的 400 只要多出来就照旧判红。2026-10-15 复核：`.slice(-n)` 摘**最老**的 n 条 ——
      //     只有「本旅程真发起过发码」时才摘，且每次最多 1 条，故不会误伤别的 400）；
      //   · 摘掉的内容**照实印进 note**（不隐藏）。不按文案匹配（`criteria` 静态判据禁止扫 console 文案）。
      const sendErrUrls = errs.filter((e) => e.startsWith('[http] ') && e.includes('/api/auth/sms/send'))
      if (sendErrUrls.length) {
        const status = (sendErrUrls[0].match(/^(?:\[http\] )?(\d{3}) /) || [])[1]
        const drop = new Set(sendErrUrls)
        const resourceErrors = errs.filter(isConsoleResourceLoadError)
        // ⚠️ 只摘**落在本旅程窗口内且能对上次数**的那些：`smsSendTolerated` 在 `smsLogin` 里计数
        const n = Math.min(sendErrUrls.length, Math.max(1, smsSendTolerated.count))
        for (const e of resourceErrors.slice(-n)) drop.add(e)
        for (let i = errs.length - 1; i >= 0; i--) if (drop.has(errs[i])) errs.splice(i, 1)
        rec.notes.push(`已知环境限制：发码被后端拒（${status || '?'} POST 发码端点）——`
          + ' 本机 `sms.bypass-code` 非空（万能码）⇒ 登录**不依赖发码**，该响应不计入本旅程失败')
      }
      // 🔴 issue #6942 ① 的**类级判据**（实例判据在 `15-orders-new` 的自造商品前置上）：
      //    「打向**不存在**的商品对象的 404」在本旅程窗口内出现 ⇒ 直接判红并**点名那个 id**。
      //    为什么必须有这一条：触发它的是**数据依赖**（别的旅程/上一轮把对象清掉了），
      //    症状是偶发、归因要翻 console/网络日志；有了它，下一次再出现同一病灶时读数**当场可归因**。
      //    豁免边界：只有 `GET /api/admin/products/<id>`（详情/选择商品）这条；列表/其他端点不在此列。
      for (const f of product404Missing(errs)) {
        rec.pass = false
        rec.errors.push(`指向**不存在**的商品对象：404 GET ${f} —— 前置对象被清掉了（issue #6942 ①：`
          + '旅程要**自造自己的前置**，不复用可能被别的旅程/上一轮删掉的 id）')
      }
      // 分类优先于 pass：未配置 / 前置不满足**都不是**产品失败（#6790 判据 ③④）
      const klass = typeof errClass === 'string' && errClass
        ? errClass
        : (!ok && UNCONFIGURED && AI_AGENT_JOURNEYS.has(name) ? 'unconfigured' : null)
      rec.error_class = klass
      if (klass === 'unconfigured') {
        rec.unconfigured = true
        rec.pass = false
        if (errs.length) rec.errors.push(...errs)
        console.log(`➖ ${name} [未配置] ${UNCONFIGURED_WHY || 'ai-agent 未按 AGENTS.md 传 AI_AGENT_BASE_URL / AI_AGENT_SERVICE_TOKEN'}`)
        if (UNCONFIGURED_WHY) rec.notes.push(`[未配置] ${UNCONFIGURED_WHY}`)
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
 * ⚠️ **归因订正（2026-10-14 现取实测，issue #6940）**：本条原先把**两种完全不同的原因**写成了一条叙事 ——
 *   「`INCIDENT_PRODUCTION_ROUTING_UNRESOLVED`（tenantId=25，租户未配默认工艺）」是 2026-10 早期在
 *   **另一个租户**上看到的形态；而本租户（32）**已有**默认工艺 `韩褶` 与默认路线模板
 *   `窗帘工序路线（默认）`，真正挡住生成的是**订单状态**，服务端逐字：
 *   `{"orderRef":"…","success":false,"message":"订单 … 当前状态 [pending] 不允许生成加工单，须为已确认","code":"VALIDATION_ERROR"}`
 *   （`data` **并不为空**）。⇒ 旧写法把「探针单没确认」误报成「租户没配路线」，
 *   于是 16-/17-/32- 三条旅程**以错误的理由 skip**（skip 的面 = 未覆盖，理由错 ⇒ 没人会去修真因）。
 *
 * 现在：① 探针单先**自造前置**（`PUT /api/admin/orders/{id}/payment` 确认收款 ⇒ confirmed）再探生成能力；
 *   ② `why` **只用服务端自己给的 `message`/`code`**（不再抄任何历史叙事）。
 * 仍保留 skip 语义：真配不出来（服务端明确说缺工艺/缺路线）⇒ skip 并**逐字印出服务端的话**（skip ≠ pass）。
 */
async function processingRouteAvailable(page) {
  const api = await adminApi(page)
  const probeId = await createOrderFixture(page, '冒烟路线探测')
  // 生成加工单要求订单**已确认**（服务端逐字：「当前状态 [pending] 不允许生成加工单，须为已确认」）⇒
  // 前置**自造**：先确认收款（pending → confirmed）再探生成能力（不自造就会把「没确认」误判成「租户没配路线」）。
  await api.put(`/api/admin/orders/${probeId}/payment`).catch(() => {})
  const gen = await api.post('/api/admin/processing-orders/generate', { orderIds: [probeId] })
  const results = Array.isArray(gen?.data) ? gen.data : []
  const ok = results.some((r) => r && r.success !== false)
  // 归因**只用服务端逐字**（禁止再抄历史叙事 —— 那是 2026-10-14 实测过的错归因来源）
  const detail = results
    .map((r) => `${r?.orderRef ?? '?'} → ${r?.message ?? '(服务端未给 message)'}${r?.code ? ` [${r.code}]` : ''}`)
    .join('；')
  const why = ok
    ? ''
    : `本租户指定单（${probeId}）生成加工单未落库 —— 服务端逐字：${detail || '(data 为空且未给 message)'}`
  if (ok) await cleanupOrder(page, probeId)
  return { ok, why, probeId }
}

/**
 * 自造商品的前置清理（同为「先建再测、跑完清理」）。
 *
 * 🔴 2026-10-15（issue #6942 ①）**真栈现取读数**：`DELETE /api/admin/products/{id}` 对
 *   `on_sale` 商品**必 422** —— 逐字
 *   `{"success":false,"error":{"code":"VALIDATION_ERROR","message":"当前状态[出售中]不允许删除，请先下架后再删除"}}`
 *   ⇒ 旧形态「建了就删」**一件都没删掉**（残留商品在列表里，恰恰就是 #6942 ① 那个
 *   `404 GET /api/admin/products/<id>` 的**来源**：列表页拿到的是已被清掉的旧 id）。
 *   正确顺序 = 先 `PUT /{id}/status {"status":"off_sale"}` 再 `DELETE`（`ProductController` 的
 *   上下架端点 + 删除闸门）。
 * 返回三态读数（清理**不举手**，由调用方决定怎么用）：
 *   `{ok, status, after, why}` —— `ok` = 删除调用 2xx；`after` = 清理后 `GET /{id}` 的状态码
 *   （**404 = 真没了**，这是唯一能证明「不留尾巴」的结构化读数）。
 */
async function cleanupProduct(page, id) {
  try {
    const api = await adminApi(page)
    const at = (await page.context().cookies()).find((c) => c.name === 'access_token')
    const raw = (method, path, body) => fetch(`${API_BASE}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', Cookie: `access_token=${at.value}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    // ① 状态闸门（**现取**当前状态再决定要不要下架）：
    //    后端 `ProductService.deleteProduct` 只允许 `draft` / `off_sale` 删除（`on_sale` / `under_review` 拒），
    //    而 `draft → off_sale` 的流转**本身是非法**的（逐字：`状态流转无效: 草稿 → 已下架，允许的目标状态: 审核中/出售中`）
    //    ⇒ 对草稿商品硬下架会 422、再删照样 422。⇒ 先看状态：只有 `on_sale` / `under_review` 才下架。
    let cur = ''
    try {
      const g = await raw('GET', `/api/admin/products/${id}`)
      if (g.status === 404) return { ok: true, status: null, del: null, after: 404, why: '已不存在（无需清理）' }
      cur = ((await g.json()).data || {}).status || ''
    } catch { cur = '' }
    let status = null
    if (cur && cur !== 'draft' && cur !== 'off_sale') {
      try { status = (await raw('PUT', `/api/admin/products/${id}/status`, { status: 'off_sale' })).status } catch { status = -1 }
    }
    // ② 删除
    let del = -1
    try { del = (await raw('DELETE', `/api/admin/products/${id}`)).status } catch { del = -1 }
    // ③ 结构化复探（**真没了**才算干净）
    let after = -1
    try { after = (await raw('GET', `/api/admin/products/${id}`)).status } catch { after = -1 }
    return { ok: del >= 200 && del < 300, status, del, after,
      why: after === 404 ? '已删除（GET 404）' : `GET 仍返回 ${after}（残留）` }
  } catch (e) {
    return { ok: false, status: -1, del: -1, after: -1, why: `清理异常：${String(e).slice(0, 160)}` }
  }
}

/** 本租户商品总数（分页 meta.total；**按 tenant 过滤**的原生读数，用于自证「自造的前置真的清掉了」）。 */
async function productCount(page) {
  const api = await adminApi(page)
  const res = await api.get('/api/admin/products?page=1&size=1')
  // 分页器两种形态都认（`data.total` / `data.pagination.total`），取不到就报出来而不是猜 0
  const total = res?.data?.total ?? res?.data?.pagination?.total ?? res?.data?.items?.length
  if (typeof total !== 'number') throw new Error(`商品总数读数失败（无法从分页响应取 total）：${JSON.stringify(res).slice(0, 200)}`)
  return total
}

/**
 * 把「自造商品 → 跑完删掉」变成**有判据的清理**（issue #6942 ①「清理不留尾巴」）：
 * 删不掉（`GET /{id}` 仍非 404）⇒ `rec.pass = false` + 逐字 errors；价格/计数对不上 ⇒ 只记 note
 *（计数会被同轮别的旅程的自造/清理扰动，适合当**佐证**不适合当硬判据）。
 * `phase` 是「哪一次清理」（成功路径 / 兜底路径），便于读数归因。
 */
async function cleanupProductStrict(page, rec, id, phase) {
  let res = await cleanupProduct(page, id)
  if (res.after !== 404) {  // 可恢复态（token 走弱）⇒ 自补登录态后重试一次
    await ensureLoggedIn(page).catch(() => {})
    res = await cleanupProduct(page, id)
  }
  if (res.after === 404) markFixtureCleaned(id)
  const cnt = await productCount(page).catch(() => null)
  if (res.after !== 404) {
    rec.pass = false
    rec.errors.push(`自造商品清理失败（${phase}）：id=${id} 的 DELETE→${res.del} / 下架→${res.status} / `
      + `清理后 GET→${res.after}（${res.why}）—— 残留必须清掉（issue #6942 ①）`)
  } else {
    rec.notes.push(`自造商品 ${id} 已清理（${phase}；下架 ${res.status} / DELETE ${res.del} / GET 404${cnt === null ? '' : `，商品总数 ${cnt}`}）`)
  }
  return res
}

/**
 * 自造一件商品前置（issue #6942 ①：**旅行自造自己的前置**，不复用可能被别的旅程/上一轮清掉的 id）。
 *
 * 病灶：`15-orders-new` 旧形态从 `/api/admin/products?page=1&size=1` 取**列表首个商品**当搜索词 ——
 * 那是**别人的**对象：列表里只要出现一件**已删除**的商品（同轮里它上一次还是绿的 ⇒ 典型的
 * 跨旅程/跨轮残留），打向它的请求就是 `404 GET /api/admin/products/73cc4ac45d4053719865a88d3570b932`。
 * 口径 = 本文件既有的「先建再测、跑完清理」（`10-` / `11-` 同族做法）：前置**自造**，
 * 判据不再依赖任何外部对象；清理**不举手**（清不掉只记 note，不冒充旅程失败）。
 */
async function createProductFixture(page, { name, skuCode }) {
  const api = await adminApi(page)
  // 🔴 SDQS D1/D2（docs/testing/smoke-data-quality.md）：商品夹具**必须**带 SKU 矩阵
  //    （颜色 × 门幅 × 价格 × 库存 × 货号）。旧形态只 POST 商品级字段 ⇒ `product_skus` 零行
  //    ⇒「SKU 选择 / 价格本 / 采购单 / 库存」全链没有数据可测，而页面照样渲染、冒烟照样绿。
  //    2026-10-23 用户投诉的「冒烟数据商品 SKU 都没有」就是这条。
  const colors = [{ colorName: '米白', mainColorHex: '#F5EFE0' }, { colorName: '浅灰', mainColorHex: '#C9C9C9' }]
  const doorWidths = ['2.8', '3.2']
  const basePrice = 30.8
  const skus = colors.flatMap((c) => doorWidths.map((w) => ({
    colorName: c.colorName,
    doorWidth: w,
    price: basePrice,
    stock: 120,
    skuCode: `${skuCode}-${c.colorName}-${w}`,
  })))
  const created = await api.post('/api/admin/products', {
    name, skuCode, unit: '米', pricingType: 'per_meter',
    categoryId: process.env.SMOKE_CATEGORY_ID || await defaultCategoryId(page), basePrice,
    status: 'on_sale', doorWidths, colors, sellingMethods: ['bulk_cut'], skus,
  })
  const id = created?.data?.id || created?.id || ''
  if (!id) throw new Error(`前置建品失败（未返回 id）：${JSON.stringify(created).slice(0, 200)}`)
  recordFixture('products', { id, name, withSkus: skus.length, cleaned: false })
  return id
}

/** 按名字读回商品（建品旅程用：DOM 可见 ≠ 数据落地，SDQS D5）。 */
async function readProductByName(page, name) {
  const api = await adminApi(page)
  const res = await api.get(`/api/admin/products?page=1&size=100&keyword=${encodeURIComponent(name)}`)
  const items = res?.data?.items ?? res?.data?.records ?? []
  return items.find((p) => p.name === name) || items[0] || null
}

/** 读回商品的 SKU 行（`ProductResponse.skus`；取不到返回空数组，不猜）。 */
async function readProductSkus(page, id) {
  const api = await adminApi(page)
  const res = await api.get(`/api/admin/products/${id}`)
  const detail = res?.data ?? res
  return Array.isArray(detail?.skus) ? detail.skus : []
}

/**
 * 数据质量快照（SDQS §3.1）：跑完从**管理端 API 现读**各实体面，写 `smoke-data.json`。
 *
 * 🔴 为什么不从 DOM 统计：DOM 只能证明「渲染了」，证明不了「数据在」——
 *    2026-10-23 那次 33/33 绿，DOM 上是「商品列表 1 行」，而数据面 `product_skus` 是 0 行。
 * 🔴 任何一片读不到都写 `collected: false` + `why`（fail-closed）：`smoke_data_quality.py`
 *    会把它判成 `DQ-U` 不可判定（退出码 3），**不许**当通过。
 */
async function collectDataSnapshot(page) {
  const snap = {
    schema_version: 1,
    collected_at: new Date().toISOString(),
    base_url: BASE,
    ran_journeys: [...new Set(results.map((r) => r.journey))],
    run: { journeys_total: results.length, journeys_pass: results.filter((r) => r.pass).length },
    entities: {},
    fixtures: {},
    collection_errors: [],
  }
  const finishFixtures = () => {
    const created = FIXTURES.products
    snap.fixtures = {
      products_created: created.length,
      products_with_skus: created.filter((f) => Number(f.withSkus) > 0).length,
      products_residue: created.filter((f) => !f.cleaned).length,
      residue_samples: created.filter((f) => !f.cleaned).map((f) => f.name || f.id).slice(0, 5),
      orders_created: FIXTURES.orders.length,
    }
  }
  const items = (res) => {
    const d = res?.data
    if (Array.isArray(d)) return d
    if (Array.isArray(d?.items)) return d.items
    if (Array.isArray(d?.records)) return d.records
    return []
  }
  const totalOf = (res, list) => Number(res?.data?.total ?? res?.data?.pagination?.total ?? list.length)

  let api
  try {
    api = await adminApi(page)
  } catch (e) {
    const why = `登录态不可用，数据快照无法采集：${String(e).slice(0, 160)}`
    for (const name of ['products', 'skus', 'orders', 'customers', 'after_sales']) {
      snap.entities[name] = { collected: false, why }
    }
    snap.collection_errors.push(why)
    finishFixtures()
    return snap
  }

  // 商品 + SKU（SKU 只在商品详情里）
  try {
    const listRes = await api.get('/api/admin/products?page=1&size=100')
    const list = items(listRes)
    const sampled = list.slice(0, 60)
    const skuRows = []
    let withSkus = 0
    for (const p of sampled) {
      try {
        const rows = await readProductSkus(page, p.id)
        if (rows.length) withSkus++
        skuRows.push(...rows)
      } catch (e) {
        snap.collection_errors.push(`product/${p.id}: ${String(e).slice(0, 120)}`)
      }
    }
    snap.entities.products = { collected: true, total: totalOf(listRes, list), sampled: sampled.length, with_skus: withSkus }
    // 门幅 canonical = 裸数值（与 SkuMatrix.tsx 的 normalizeDoorWidth 同口径）
    const canonical = (v) => /^[0-9]+(\.[0-9]+)?$/.test(String(v ?? ''))
    const bad = skuRows.filter((s) => !canonical(s.doorWidth ?? s.door_width))
    snap.entities.skus = {
      collected: true,
      total: skuRows.length,
      door_width_noncanonical: bad.length,
      door_width_noncanonical_samples: [...new Set(bad.map((s) => String(s.doorWidth ?? s.door_width ?? '')))].slice(0, 5),
      without_price: skuRows.filter((s) => !(Number(s.price) > 0)).length,
    }
  } catch (e) {
    const why = `商品面读取失败：${String(e).slice(0, 160)}`
    snap.entities.products = { collected: false, why }
    snap.entities.skus = { collected: false, why }
    snap.collection_errors.push(why)
  }

  // 订单 / 客户 / 售后（分页 total 读数；订单另记「有明细」条数）
  for (const [name, path] of [
    ['orders', '/api/admin/orders?page=1&size=100'],
    ['customers', '/api/admin/customers?page=1&size=1'],
    ['after_sales', '/api/admin/after-sales?page=1&size=100'],
  ]) {
    try {
      const res = await api.get(path)
      const list = items(res)
      const ent = { collected: true, total: totalOf(res, list) }
      if (name === 'orders') ent.with_items = list.filter((o) => Array.isArray(o.items) && o.items.length > 0).length
      snap.entities[name] = ent
    } catch (e) {
      snap.entities[name] = { collected: false, why: `${name} 读取失败：${String(e).slice(0, 160)}` }
      snap.collection_errors.push(`${name}: ${String(e).slice(0, 160)}`)
    }
  }

  finishFixtures()
  return snap
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

/**
 * 等**文本变成期望值**（不是「等它可见」）—— issue #6940 实测的错形态：
 * 元素**本来就可见**（旧状态文本）时 `waitVisible` 会**立刻返回**，紧接着比较文本 = **拿旧值断言新状态**
 * ⇒ 结构上**必假红**（`16-` 的 `[发加工]` 徽标：按钮已经切到「开始加工」= 状态确实变了，徽标却还是「已生成」，
 * 因为比较发生在重取回来之前）。改成有界轮询后，这条断言才**有意义**：
 * 文本若始终不变 ⇒ 真的红了（渲染没跟着状态走）。
 */
const waitForText = async (locator, expected, timeout) => {
  const deadline = Date.now() + timeout
  let last = ''
  for (;;) {
    last = ((await locator.textContent().catch(() => '')) ?? '').trim()
    if (last === expected) return last
    if (Date.now() >= deadline) return last
    await new Promise((r) => setTimeout(r, 200))
  }
}

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
/** 切到「管理员登录」tab（默认 tab 是「员工登录」；用正则子串定位，避免 exact 匹配不到「标题+副标题」）。
 *
 * 🔴 2026-10-15（issue #6942 ②，单组跑登录路径确定性）**现取读数**：旧形态的「门禁」是
 *   「点一下 tab → 看 `#phone` 在不在」。`#phone` **只**属于管理员 tab（员工 tab 是 `id="identifier"`，
 *   `frontend/admin-web/src/app/login/page.tsx` 现取），所以那个门禁**方向是对的**；但它是
 *   **一次性点击 + 一次 5s 等待**，点空（落在 hydration 窗口 / 路由重置）时**没有第二道判据**
 *   —— 单组跑时表现为停在 `/login`（截图证据：`12-processing.png` 停在**员工登录 tab**）。
 *   门禁改判 **tab 的 `aria-selected`**（切 tab 成功 = 该 tab 变成选中态），不顺就重点，最多 3 次。
 */
async function openAdminLoginTab(page) {
  const tab = page.getByRole('tab', { name: /管理员登录/ }).first()
  await tab.waitFor({ state: 'visible', timeout: 8000 })
  // 🔴 真实栈偶发（探针实测 + 本单多轮复现）：`/login` 的 SSR 骨架先到，React **还没 hydrate** 就点 tab
  //    ⇒ 点击不改变 tab 状态 ⇒ `page.fill('#phone')` 30s 超时
  //    （全量跑里表现为 01-login ❌，随后所有旅程连锁 ❌；单跑时表现为 ensureLoggedIn 超时）。
  //    修法 = **等 hydration 再点**（`Object.keys(document.body)` 上出现 `__react*` 私有键）。
  await page.waitForFunction(
    () => Object.keys(document.body).some((k) => k.startsWith('__react')),
    null, { timeout: 30000 },
  ).catch(() => {})  // 拿不到也不静默成功：下面的选中态门禁仍是硬门禁
  let onAdminTab = false
  for (let i = 0; i < 3 && !onAdminTab; i++) {
    await tab.click().catch(() => {})
    onAdminTab = await page.waitForFunction(
      () => {
        const tabs = [...document.querySelectorAll('[role="tab"]')]
        const admin = tabs.find((t) => (t.textContent || '').includes('管理员登录'))
        return !!admin && admin.getAttribute('aria-selected') === 'true'
      },
      null, { timeout: 5000 },
    ).then(() => true).catch(() => false)
  }
  if (!onAdminTab) {
    throw new Error('未切到「管理员登录」tab（点了 3 次，该 tab 的 aria-selected 仍非 true）——'
      + '旧形态只靠「点一次 + 等 #phone」，点空时没有第二道判据（issue #6942 ②）')
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

/** 手机号 + 短信验证码登录（管理员 tab）→ 等落点 /dashboard。三处调用点共用，选择器只有这一份。
 *
 * 🔴 issue #6942 ②（单组跑登录路径的**确定性**）：旧形态把「点获取验证码」当**硬门禁**，
 *   而本机 `POST /api/auth/sms/send` 会**确定性** 400 —— 两个来源都实测到（`SmsService` 的
 *   `LIMIT_KEY_PREFIX` 60 秒防刷 / `DAILY_LIMIT = 10` 每日上限）：逐字
 *   `{"success":false,"error":{"code":"ILLEGAL_STATE","message":"今日发送次数已达上限"}}`
 *   ⇒ 单组跑（`--group 12` / `--group 15` … 把 `01-login` 过滤掉、无前置会话）时**登不进去**：
 *   旅程被弹回 `/login` + 三条 401（成对读数见 PR body）。全量跑之所以「正常」，只是因为
 *   `01-login` 先跑过一次、cookie 已在 —— 那是**顺序依赖**，不是确定性。
 *
 * 口径（**不放宽任何断言**）：**发码不是判据，能登录才是**。故发码这一步既不**阻断**、
 *   也不**冒充产品失败**：
 *   ① 发码失败**只记不抛**，登录断言（`#code` 可填 + 落到 `/dashboard`）一条都没删 ——
 *      真登不进去时仍是硬红，只是归因不再落在发码这个**非判据**步骤上；
 *   ② 发码那一条 400 在 `failedResponses` 里被**带标签地**消化：`smsSendTolerated` 只登记
 *      「我们确实点过发码、且它失败了」的那一条响应 URL，由本步骤自己从错误面摘掉、**照实印进 note**；
 *      **别的**失败响应照旧判红 ⇒ 不是「凡是 400 都放过」。
 * 为什么可容忍：本机栈 `sms.bypass-code` 非空（万能码，见 `SmsService#verifyCode`）
 *   ⇒ `POST /api/auth/sms/login` 带 `SMS_CODE` **无需先发码**即 200（2026-10-14/15 真栈探针逐字读数）；
 *   发码 400 时前端**不启动倒计时**（`login/page.tsx` 的 `setCodeError` 分支）⇒ 按钮仍可点、
 *   `#code` 仍可填 —— 「发码失败 ≠ 登不进去」这条前提是**实测**的，不是猜的。
 */
const smsSendTolerated = { count: 0 }

async function smsLogin(page, { where, settleMs }) {
  return loginStep(where, async () => {
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 25000 })
    await openAdminLoginTab(page)
    await expectText(page, '管理员登录')
    await page.fill('#phone', PHONE)
    // 发码：失败**只记不抛**（发码不是判据，能登录才是）；按钮不 visible 时不阻断，
    // 让下面的硬门禁（`#code` 可填 + 落到 /dashboard）给出真读数。issue #6942 ②。
    let sendErr = ''
    const watchSend = (r) => {
      if (smsSendToleratedResponse(r.status(), r.request().method(), r.url())) smsSendTolerated.count += 1
    }
    page.on('response', watchSend)
    try {
      const btn = page.getByRole('button', { name: /获取验证码/ })
      await btn.waitFor({ state: 'visible', timeout: 8000 })
      await btn.click({ timeout: 8000 })
    } catch (e) {
      sendErr = String((e && e.message) || e).slice(0, 200)
    } finally {
      page.removeListener('response', watchSend)
    }
    await page.waitForTimeout(settleMs)
    await page.fill('#code', SMS_CODE)
    await safeClick(page, page.getByRole('button', { name: /登\s*录|登录/ }).last(), '登录')
    try {
      await page.waitForURL('**/dashboard**', { timeout: 20000 })
    } catch (e) {
      throw new Error(
        `登录未落到 /dashboard（发码${sendErr ? `失败：${sendErr}` : '未报错'}）：`
        + `${String((e && e.message) || e).slice(0, 220)}`,
      )
    }
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
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
    await nav(page, '/products', '')
    // 等页面就位（表头「商品标题」或首行）——旧形态 `nav(..., '商品列表')` 的 8s 文案等待
    // 在真栈上偶发不够（列表先请求后渲染，实测超时）；判据不变，只把等待方式换成显式就位。
    if (!(await waitVisible(page.getByText('商品标题').first(), 20000))) {
      if (!(await waitVisible(page.locator('tbody tr, [role="row"]').first(), 8000))) {
        throw new Error(`商品页 20s 内未就位（url=${page.url()}）`)
      }
    }
    // 列表有行（种子/存量商品）
    // 🔴 SDQS D1/D5（docs/testing/smoke-data-quality.md）：**空态/加载态不得冒充通过**。
    //    旧形态在 0 行时记 ✅（「列表为空（允许），仅验证渲染」），且截图可能拍在「加载中…」——
    //    「没加载完」被读成「数据空」、又被读成「通过」。现在：有界等待**有内容的行**；
    //    等不到 ⇒ 判红（数据前置不合格，由 DQ-1/DQ-4 与旅程**双面**兜住）。
    const rows = page.locator('tbody tr, [class*="Table"] [class*="row"], [role="row"]')
    let n = 0
    let firstRowText = ''
    for (let i = 0; i < 20; i++) {
      const texts = (await rows.allInnerTexts().catch(() => [])).map((t) => t.trim()).filter((t) => t && !t.includes('加载中'))
      if (texts.length > 0) { n = texts.length; firstRowText = texts[0]; break }
      await page.waitForTimeout(500)
    }
    if (n === 0) {
      throw new Error('商品列表 10s 内没有任何数据行 —— 空态/加载态不是有效结论（SDQS D1/D5；'
        + '先确认冒烟环境有商品种子，再跑本旅程）')
    }
    await h.done(true, '', `商品列表渲染 ${n} 行；首行：${firstRowText.replace(/\s+/g, ' ').slice(0, 40)}`)
  } catch (e) {
    await h.done(false, `商品列表失败: ${String(e).slice(0, 300)}`)
  }
}

async function productsNew(page) {
  // `--group` 过滤掉的旅程记 skip（没跑 ≠ 失败）；这几条**没接在 `jrun` 上**，故各自守卫（#6790）
  // ⚠️ `h` 必须在 guard **之前**取：旧形态先 `markSkipped(h, …)` 后 `const h` ⇒ 过滤档命中时
  //    `h` 还在 TDZ 里（ReferenceError）——「没跑」变成了「崩了」。
  const h = await journey('09-products-new')(page)
  if (!inGroup('09-products-new')) { await markSkipped(h, '--group 09-products-new 过滤（本轮未跑）'); return }
  // 自造对象台账（SDQS D4）：建了哪件、几件有 SKU、清掉了没有 —— 快照据此判 DQ-2/DQ-5
  const fixture = recordFixture('products', { id: '', name: '', withSkus: 0, cleaned: false })
  try {
    await ensureLoggedIn(page)
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
    // ── SDQS D1（docs/testing/smoke-data-quality.md）：建品**必须**把 SKU 矩阵填出来 ──
    // 旧形态只填标题 + 一档门幅就「存草稿」⇒ 造出来的商品 `product_skus` **零行**，而旅程照记 ✅
    // （2026-10-23 用户投诉「冒烟数据商品 SKU 都没有」）。这里填「2 颜色 × 1 门幅」= 2 条 SKU：
    // 颜色走批量输入框（`BatchColorInput`），价格/库存走批量填写（`SkuMatrix` 的批量工具栏）。
    const colorInput = page.locator('textarea[placeholder*="每行一个颜色名称"]').first()
    if (!(await waitVisible(colorInput, 10000))) throw new Error('建品页 10s 内未见「批量添加颜色」输入框')
    await colorInput.fill('米白,浅灰')
    await page.getByRole('button', { name: '添加颜色', exact: true }).first().click()
    await page.waitForTimeout(600)
    const priceInput = page.locator('input[placeholder="价格"]').first()
    if (!(await waitVisible(priceInput, 8000))) throw new Error('建品页未见 SKU 批量「价格」输入框')
    await priceInput.fill('30.8')
    const stockInput = page.locator('input[placeholder="数量"]').first()
    await stockInput.fill('120')
    await page.getByRole('button', { name: '批量填写', exact: true }).first().click()
    await page.waitForTimeout(600)
    // SKU 矩阵逐行非空（只数行数会被「空行」骗过 —— 价格/库存是逐格 input）
    const matrixRows = page.locator('table:has(th:has-text("价格（元）")) tbody tr')
    const skuRowCount = await matrixRows.count()
    if (skuRowCount < 2) throw new Error(`SKU 矩阵应 ≥2 行（2 颜色 × 1 门幅），现取 ${skuRowCount} 行`)
    const cellValues = await matrixRows.evaluateAll((rows) => rows.map((r) => [...r.querySelectorAll('input')].map((i) => i.value)))
    const emptyCells = cellValues.filter((vals) => vals.length < 2 || !vals[0] || vals[1] === '').length
    if (emptyCells > 0) throw new Error(`SKU 矩阵有 ${emptyCells} 行价格/库存为空：${JSON.stringify(cellValues).slice(0, 200)}`)
    await page.getByRole('button', { name: /存草稿|存为草稿/ }).first().click().catch(() => {})
    await page.waitForTimeout(2500)
    await nav(page, '/products', '')
    // 列表就位等待（与 08- 同法）：页面标题/表头现取为「商品标题」，旧形态等的「商品列表」文案不存在
    if (!(await waitVisible(page.getByText('商品标题').first(), 20000))) {
      if (!(await waitVisible(page.locator('tbody tr, [role="row"]').first(), 8000))) {
        throw new Error(`商品列表 20s 内未就位（url=${page.url()}）`)
      }
    }
    // 🔴 2026-10-24 真栈实测：表头「商品标题」先渲染、**行数据仍在「加载中…」** ⇒ 定长 1.8s 后
    //    判可见是**假红**（截图：列表区 spinner 仍在转，本旅程却判红）。改成有界等待自造商品名出现。
    if (!(await waitVisible(page.locator(`text=${pname}`).first(), 20000))) {
      const bodyText = (await page.evaluate(() => document.body.innerText).catch(() => '')).replace(/\s+/g, ' ').slice(0, 160)
      throw new Error(`新建商品未出现在列表（20s 内未见「${pname}」；页面文案：${bodyText || '<空>'}）`)
    }
    // ── 读回（SDQS D5：DOM 可见 ≠ 数据落地）──
    // 列表里能看到 ≠ `product_skus` 有行：2026-10-23 那次正是「列表可见 + SKU 零行」还记了 ✅。
    const rec = await readProductByName(page, pname)
    if (!rec?.id) throw new Error(`建品后 API 读不到「${pname}」（列表可见、接口读不到 ⇒ 数据没落地）`)
    fixture.id = rec.id
    fixture.name = pname
    const skus = await readProductSkus(page, rec.id)
    fixture.withSkus = skus.length
    if (skus.length < 2) throw new Error(`自造商品 ${rec.id} 只有 ${skus.length} 条 SKU（应 ≥2）：冒烟数据不合格（SDQS D1）`)
    const badPrice = skus.filter((s) => !(Number(s.price) > 0))
    const badDoor = skus.filter((s) => !/^[0-9]+(\.[0-9]+)?$/.test(String(s.doorWidth ?? s.doorWidth ?? '')))
    if (badPrice.length || badDoor.length) {
      throw new Error(`SKU 数据不合格：价格≤0 ${badPrice.length} 条 / 门幅非 canonical ${badDoor.length} 条：${JSON.stringify(skus).slice(0, 240)}`)
    }
    await h.done(true, '', `门幅 值/显示分离 ✓(${JSON.stringify(optInfo)}→'${storedValue}') + 建品可见 ✓(${pname})`
      + ` + 读回 SKU ${skus.length} 条 ✓(${skus.map((s) => `${s.colorName}/${s.doorWidth}/¥${s.price}/${s.stock}`).join('; ')})`)
  } catch (e) {
    await h.done(false, `新建商品页失败: ${String(e).slice(0, 300)}`)
  } finally {
    // 清理自证（SDQS D4/DQ-5）：草稿可删；删不掉 ⇒ 本旅程判红（**不是** note —— 旧形态正是「建完不管」）
    if (fixture.id) {
      const res = await cleanupProduct(page, fixture.id)
      if (res.after === 404) {
        markFixtureCleaned(fixture.id)
        h.rec.notes.push(`自造商品 ${fixture.id} 已清理（GET 404）`)
      } else {
        h.rec.pass = false
        h.rec.errors.push(`自造商品清理失败：id=${fixture.id} DELETE→${res.del} / 清理后 GET→${res.after}（${res.why}）`)
      }
    }
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
      if (mine) await cleanupProductStrict(page, h.rec, mine, '无可查看行时的失败路径')
      throw new Error(mine ? `自造 on_sale 商品 ${mine} 后列表仍无「查看」按钮` : `商品列表 ${n} 行但无一行带「查看」`)
    }
    await viewRow.locator('button:text-is("查看")').first().click()
    await page.waitForTimeout(1800)
    const url = page.url()
    if (!/\/products\/[^/]+$/.test(url)) throw new Error(`点击行未跳转详情，仍在 ${url}`)
    const bodyLen = await page.evaluate(() => document.body.innerText.length)
    if (bodyLen < 50) throw new Error('详情页空白')
    if (mine) await cleanupProductStrict(page, h.rec, mine, '详情页渲染后')
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
    if (mine) await cleanupProductStrict(page, h.rec, mine, '门幅回显后')
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
    await ensureLoggedIn(page)
    // 登录态自补（房内既有形态，见 10-/11-/13- 等）：本旅程在**单组跑**（`--group 12`，01-login 被一并过滤掉）
    // 时也必须自足 —— 下面的前置自造要直连 admin-api，没有 cookie 会当场「未取到 access_token cookie」
    // （2026-10-14 实测；全量跑时 cookie 已在，本行立即返回、不重复发码）。
    // 加工分类前置**自造**（#4882 起表单只剩「名称 + 加工分类」两个必填项）：
    // ⚠️ 本租户可能**一个活跃分类都没有**（2026-10-14 实测：8 行全软删）⇒ 弹窗改渲染
    //    「当前还没有加工分类，加工项必须归属于一个加工分类。请先创建：」+ 内联输入，此时 `select` 不存在
    //    ⇒ 必填分类为空 ⇒ **保存被客户端校验挡住、POST 根本不发**（列表恒等不到新行，api 日志里连该名字都搜不到）。
    //    ⇒ 先用 API 建一个（同房内「自造商品/订单」做法），页面随后就会把分类渲染成下拉。
    // ⚠️ **必须在 `nav()` 之前**：页面在加载时就把分类列表拉进内存（实测截图：晚建于页面加载 ⇒ 弹窗**仍**走
    //    「请先创建」分支 + 头部「加工分类 (0)」，即使库里已有分类）。
    const catApi = await adminApi(page)
    const cats = await catApi.get('/api/admin/processing-categories')
      .then((r) => (Array.isArray(r?.data) ? r.data : [])).catch(() => [])
    if (cats.length === 0) {
      await catApi.post('/api/admin/processing-categories', { name: `冒烟分类${Date.now()}` }).catch(() => {})
    }
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
    await page.locator('select').first().selectOption({ index: 1 }).catch(() => {})
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
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
  // 🔴 issue #6942 ①：本旅程**自造自己的商品前置**（不复用列表首个商品 —— 那可能是**已删**的残留对象
  //    ⇒ `404 GET /api/admin/products/<被删的 id>`）。`n0` 是清理自证用的租户商品总数读数。
  const fxName = `冒烟建单商品${Date.now()}`
  let fxId = ''
  let n0 = 0
  let cleaned = false
  // 清理 = **断言**（issue #6942「清理不留尾巴」）：删不掉 / 计数没回基线 ⇒ 本旅程判红。
  //   逐字证据进 errors（不是 note）—— 上一形态把「清理失败」只记 note，等于「漏了也没人红」。
  const cleanupFixture = async (phase) => {
    if (!fxId || cleaned) return
    let res = await cleanupProduct(page, fxId)
    // 删不掉时先自补一次登录态再重试一次（长旅程里 token 走弱会让删除 401 —— 那是**可恢复**的）
    if (res.after !== 404) {
      await ensureLoggedIn(page).catch(() => {})
      res = await cleanupProduct(page, fxId)
    }
    const n1 = await productCount(page).catch((e) => {
      h.rec.errors.push(`清理后商品总数复读失败（${phase}）：${String(e).slice(0, 160)}`)
      return -1
    })
    cleaned = true
    // 判据 ①（结构化）：`GET /{id}` 必须 404 = 对象真没了
    if (res.after !== 404) {
      h.rec.pass = false
      h.rec.errors.push(`自造商品清理失败（${phase}）：id=${fxId} 的 DELETE→${res.del} / 下架→${res.status} / `
        + `清理后 GET→${res.after}（${res.why}）—— 残留必须清掉（issue #6942 ①）`)
      return n1
    }
    // 判据 ②（计数）：总数回到基线（删除成功却没掉数 = 清的不是这一件）
    if (n1 !== n0 && n1 >= 0) {
      h.rec.pass = false
      h.rec.errors.push(`自造商品「已删除」（GET 404）但商品总数 ${n0} → ${n1}（期望回到 ${n0}；自造 id=${fxId}）`)
    }
    return n1
  }
  try {
    await ensureLoggedIn(page)
    n0 = await productCount(page)
    fxId = await createProductFixture(page, { name: fxName, skuCode: `SMOKE-ON-${Date.now()}` })
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
    // 弹窗内搜索商品。⚠️ 旧形态把搜索词**写死成 `遮光窗帘`**（本租户没有这个商品 ⇒ 恒空）；
    //    改过的形态又退化成「取列表首个商品的名字」—— 那是**别人的对象**，被别的旅程/上一轮清掉
    //    就变成 `404`（issue #6942 ①）。现在搜索词 = **本旅程刚造的那件商品**。
    const kw = fxName
    const searchInput = page.locator('[role="dialog"] input[placeholder*="搜索商品"]').first()
    await searchInput.waitFor({ state: 'visible', timeout: 6000 })
    await searchInput.fill(kw)
    await page.getByRole('button', { name: /^搜索$/ }).click().catch(async () => {
      await page.locator('[role="dialog"] button:has-text("搜索")').click()
    })
    await page.waitForTimeout(1500)
    // 选中**自造的那件**（按它的名字过滤 —— 语义与旧形态一致：搜到了就选；只是对象换成自己的）
    const result = page.locator('[role="dialog"] button').filter({ hasText: kw.slice(0, 8) }).first()
    if (await result.isVisible().catch(() => false)) {
      await result.click()
      await page.waitForTimeout(2000)
    } else {
      throw new Error(`商品搜索结果为空（搜索词 = 本旅程自造商品「${kw}」⇒ 搜索链路退化）`)
    }
    // 前置使命已达成（商品已选进表单）⇒ **立刻**清理，别拖到旅程末尾（长旅程里 session 走弱会让
    //   DELETE 401，上一版就是这么漏掉一件的：`清理失败 —— 留痕由残留计数断言承接` 却没人红）
    const nAfterClean = await cleanupFixture('选品后立刻清')
    // 提交订单
    await page.getByRole('button', { name: /提交订单/ }).first().click().catch(() => {})
    await page.waitForTimeout(2500)
    const url = page.url()
    if (url.includes('/orders')) {
      await h.done(true, '', `新建订单提交后跳转 ${url}（自造商品 ${fxName} 已清理，商品总数 ${n0}→${nAfterClean ?? '?'}）`)
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
  } finally {
    // 兜底清理（失败路径 / 早退路径）；成功路径已在选品后清过一次（`cleaned` 去重）
    if (!h.rec.skipped && fxId) await cleanupFixture('兜底清理')
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
      // 状态流转**带二次确认弹窗**（实测截图逐字：「确认状态流转 —— 将加工单 JG-… 标记为「开始加工」。
      // 该动作会写入加工单状态、不可撤销，请确认后再提交。」+ 取消/确认）⇒ 不点「确认」等于**没发生**：
      // 徽标停在上一态、下一态按钮永不出现（2026-10-14 实测的假红形态，issue #6940）。
      // 写法照房内既有形态（`[role="dialog"] button` + hasText 过滤，见 19-/21- 的删除确认）：
      // 该形态不进 `ui_smoke_name_registry.json` / `ui_smoke_first_match.json` 两份**冻结台账**
      // （那两份只许缩短 ⇒ 新站点一律不许再往里加）。
      const flowConfirm = page.locator('[role="dialog"] button').filter({ hasText: /^确\s*认$/ }).last()
      if (await waitVisible(flowConfirm, 3000)) await flowConfirm.click().catch(() => {})
      // 效果层断言（issue #4305）：旧写法断言**全页文本**「已发加工」是**空判据** ——
      // 加工单块的状态时间线恒含四个步骤文案（已生成→已发加工→加工中→加工完成），
      // 无论实际状态如何都能命中（假绿）。改判两件真效果：
      //   ① `.po-print-area` 内的**状态徽标**（该容器内唯一的 `span.bg-primary-50`）逐字等于期望；
      //   ② **按钮切换**（按钮由状态驱动渲染）：发加工后「发加工」消失、「开始加工」出现，依此类推。
      const badge = poBlock.locator('span.bg-primary-50').first()
      // 等**文本**变成期望值（issue #6940）：旧写法 `waitVisible(badge) ? textContent() : ''` 在徽标
      // 本来就可见时立刻返回 ⇒ 拿**旧状态文本**比较新状态 = 结构上必假红（实测：按钮已切到下一态，
      // 徽标却读到「已生成」）。这里改成有界轮询：文本若始终不变 ⇒ 才是真红。
      await waitVisible(badge, 12000)
      const badgeText = await waitForText(badge, expectText, 12000)
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
// 分工（issue #6982，**有意**）：
//   · `17-order-ship` —— 含加工项订单 ⇒ 体现「加工单前置守卫」这个**合法**分支（守卫可达性）；
//   · `33-ship-order-real` —— 不含加工项的订单 ⇒ 表单可提交，跑**真提交 + 断言落地**。
//     （含加工项订单在守卫未满足时**没有可提交的表单**，故真提交只能落在无守卫的订单上。）
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
    // 🔴 issue #6982 ③：**守卫出现是合法分支** —— 记 `skip`（既不是红，也不与「页面无表单」混判）；
    //    只有「表单与守卫都不见」才是红（那才是真正的未定态：页面没渲染完 / 路由打错 / 产品缺陷）。
    const submit = page.getByRole('button', { name: /确认发货/ }).first()
    const guard = page.getByText(/须先完成加工单后再发货|当前订单状态不允许发货/).first()
    await Promise.race([waitVisible(submit, 15000), waitVisible(guard, 15000)])
    if (await waitVisible(guard, 1000)) {
      await markSkipped(h, `加工单前置守卫分支（订单 ${orderId} 含加工项且加工单未流转到 completed）——本旅程的断言面不成立，未跑`)
      return
    }
    if (!(await waitVisible(submit, 1000))) {
      throw new Error(`发货页未定态（15s 内既未见表单「${SHIP_FORM_MARKERS.submit}」，也未见加工单守卫；url=${page.url()}）`)
    }
    const hasForm = await page.locator('input, textarea, select').count()
    if (hasForm === 0) throw new Error(`发货页无表单（15s 内既未见表单，也未见加工单守卫；url=${page.url()}）`)
    await h.done(true, '', `发货页表单渲染（${hasForm} 控件）`)
  } catch (e) {
    await h.done(false, `发货页失败: ${String(e).slice(0, 300)}`)
  }
}

// ────────────────────────── 发货**真提交**（issue #6982）──────────────────────────
// 判据可信度的分界线：`17-` 判「表单渲染」= 只证**页面长得对**（issue #6982 正文：它「不点【确认发货】」，
// 于是云 dev 库 `order_shipments` 全表长期 0 行）；本旅程判「提交后**从 API / 真库读**到的状态真的落地」
// = 证 **UI → HTTP → 库**这条端到端。与 `17-` 的分工是**有意**的（见上面 orderShipJourney 的注释）。

/** 建一张**不含加工项**的订单（发货表单可提交；含加工项的单走加工单守卫 ⇒ 由 `17-` 承担）。 */
async function createPlainOrderFixture(page, tag) {
  const api = await adminApi(page)
  const created = await api.post('/api/admin/orders', {
    customerName: tag, customerPhone: '13900002223', customerAddress: '杭州市西湖区冒烟路 3 号',
    logisticsType: 'express', logisticsCompany: '顺丰速运',
    discountAmount: 0, items: [{
      productId: SMOKE_PRODUCT_ID, productName: '2699系列雪尼尔窗帘面料',
      quantity: 2, unitPrice: 23.8, subtotal: 47.6,
    }],
  })
  const id = created?.data?.id
  if (!id) throw new Error(`前置建单失败（未返回 data.id）：${JSON.stringify(created).slice(0, 200)}`)
  return id
}

/**
 * 发货单快照（**一次调用、两条读路**）—— issue #6982 硬判据 ②。
 *
 * `api` = 本租户/本订单的真实读面 `GET /api/admin/orders/{id}/shipments`（与 UI 同一登录主体）；
 * `db`  = `order_shipments` 真值（`psql`）。
 *
 * 🔴 **`db` 是 fail-closed 的**：连不上库 / 读不出 `count|<tracking>` 形态 / `psql` 不在 PATH
 * ⇒ **抛错（判红）**，不降级成「跳过」—— 库读不到时「发货单真的落库了」这件事**未被证明**，
 * 而静默降级正是本单要治的病（「没跑」必须长得像「没跑」）。DSN 读 admin-api 的 `.env`
 * （worktree 形态下 `scripts/ui_smoke_merchant.sh` 会从主仓补一份），`SMOKE_DB_DSN_FILE` 可覆盖。
 */
async function shipmentSnapshot(page, orderId) {
  const api = await adminApi(page)
  const read = await api.get(`/api/admin/orders/${orderId}/shipments`)
  const apiCount = (read?.data?.shipments ?? []).length

  const envFile = process.env.SMOKE_DB_DSN_FILE || join(REPO_ROOT, 'backend', 'admin-api', '.env')
  if (!existsSync(envFile)) {
    throw new Error(`真库读数不可得：找不到 ${envFile}（SMOKE_DB_DSN_FILE 可覆盖）⇒ 「发货单真的落库了」未被证明，不得读成通过`)
  }
  const kv = {}
  for (const line of readFileSync(envFile, 'utf8').split('\n')) {
    const m = /^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/.exec(line)
    if (m) kv[m[1]] = m[2].replace(QUOTES, '')
  }
  // psql 的 `-tA` 用 `|` 分隔列 ⇒ 不拼字符串（SQL 里出现**奇数个**单引号会把
  // `tests/unit_ci_workflows/_source_parsing.py` 的 `java_code()` 词法走查带偏：
  // 它把单引号当字符串定界符，SQL 字面量里借来的那个引号会让随后的代码被**误当字符串**保留，
  // 于是文件里更靠后的注释不再被抹掉 ⇒ 名称台账判据 G 读到注释里的旧注册名 ⇒ 假红）
  const res = spawnSync('psql', [
    '-h', kv.RDS_HOST || '', '-p', kv.RDS_PORT || '5432', '-U', kv.RDS_USER || '', '-d', kv.RDS_DB || '',
    '-tAc', "select count(*), coalesce(max(tracking_no), '') from order_shipments where order_id = '" + orderId + "' and deleted = 0",
  ], { encoding: 'utf8', env: { ...process.env, PGPASSWORD: kv.RDS_PASSWORD || '' } })
  if (res.error) {
    throw new Error(`真库读数不可得：psql 未执行（${res.error.message}）⇒ 「发货单真的落库了」未被证明，不得读成通过`)
  }
  if (res.status !== 0) {
    const why = String(res.stderr).trim().slice(0, 200)
    throw new Error(`真库读数不可得：psql 退出码 ${res.status} / ${why}`)
  }
  const row = String(res.stdout).trim().split('\n')[0]
  const m = /^(\d+)\|(.*)$/.exec(row)
  if (!m) {
    const got = JSON.stringify(row)
    throw new Error(`真库读数不可得：order_shipments 快照形态不符（读到 ${got}，期望 count|tracking）`)
  }
  return { apiCount, dbCount: Number(m[1]), dbTracking: m[2] }
}

/**
 * `33-ship-order-real` —— **真点发货 + 断言落地**（issue #6982 的三条硬判据）。
 *
 * 判据**一律从 API / 真库读**：不读 toast、不读前端状态（前端状态正是「渲染即过」那一族）。
 * 幂等键 `X-Client-Request-Id` 的三层：① UI 发出的请求头非空（真提交那一半）；
 * ② **复用 UI 发的那个键**做同键重放 ⇒ `replayed=true` ∧ 不再 +1 ∧ 运单号不被覆写。
 * ⚠️ 重放必须复用 UI 真发出去的那个键（自造一个键只证得了服务端幂等，证不了「UI 发的这个键就是幂等键」）；
 * 复用同一 cookie ⇒ 同一租户/用户/权限主体，故这一条**不是**拿 API 直调顶替 UI 旅程 ——
 * 真提交那一半由上面的真实点击承担。
 */
async function orderShipRealJourney(page, seedOrderId) {
  const h = await journey('17b-ship-order-real')(page)
  const stamp = Date.now()
  const trackingNo = `SF${stamp}`
  try {
    await ensureLoggedIn(page)
    const api = await adminApi(page)
    let orderId = seedOrderId
    if (!orderId) {
      orderId = await createPlainOrderFixture(page, `冒烟发货提交${stamp}`)
      // 待付款不可发货 ⇒ 先确认收款（与 16- 的第一步同法）
      await api.put(`/api/admin/orders/${orderId}/payment`)
    }
    const before = await shipmentSnapshot(page, orderId)

    // 提交前**立刻**装监听：捕获 UI 真发出去的那一次请求（方法 + URL + 请求头 + 响应体）
    let fired = null
    let resolveFired
    const firedP = new Promise((r) => { resolveFired = r })
    const onResponse = (r) => {
      if (r.request().method() !== 'POST' || !r.url().includes('/production/orders/') || !r.url().includes('/ship')) return
      fired = r
      resolveFired(r)
    }
    page.on('response', onResponse)

    await nav(page, `/orders/${orderId}/ship`, '')
    const submit = page.getByRole('button', { name: /确认发货/ }).first()
    const guard = page.getByText(/须先完成加工单后再发货|当前订单状态不允许发货/).first()
    // 三态判定与 `17-` **同一份口径**（issue #6982 ③）：守卫 = 合法分支 ⇒ skip；两者都不见 ⇒ 红。
    // 口径的纯函数在 `criteria.mjs` 的 `classifyShipPage`（可独立红证），这里只做观测。
    await Promise.race([waitVisible(submit, 15000), waitVisible(guard, 15000)])
    const verdict = classifyShipPage({
      submitVisible: await submit.isVisible().catch(() => false),
      guardVisible: await guard.isVisible().catch(() => false),
    })
    if (verdict === 'guard') {
      await markSkipped(h, `加工单前置守卫分支（订单 ${orderId}）——真提交的断言面不成立，未跑`)
      return
    }
    if (verdict !== 'form') {
      throw new Error(`发货页未定态（15s 内既未见表单「${SHIP_FORM_MARKERS.submit}」，也未见加工单守卫；url=${page.url()}）`)
    }

    await page.getByPlaceholder('请输入实际发货人姓名').fill('冒烟发货人')
    await page.getByPlaceholder(SHIP_FORM_MARKERS.trackingPlaceholder).first().fill(trackingNo)
    await submit.click()
    // 🔴 判别力不许丢：**必须真的提交过一次**（空跑 ⇒ 红）。「页面渲染出表单」在这里**不成立** ——
    // 只有 UI 真打出了原子端点的 POST 才有读数（页面若退回两步老路 ⇒ 本判据 20s 超时判红）。
    await Promise.race([firedP, new Promise((r) => setTimeout(r, 20000))])
    page.removeListener('response', onResponse)
    if (!fired) {
      throw new Error(`提交后 20s 内未见 UI 发出 POST …/production/orders/{id}/ship（未真提交；url=${page.url()}）`)
    }

    const status = fired.status()
    const respText = await fired.text()
    if (status !== 200) {
      const body200 = respText.slice(0, 200)
      throw new Error(`原子端点返回 HTTP ${status}（期望 200）：${body200}`)
    }
    // 硬判据：请求头 `X-Client-Request-Id`（服务端幂等键的**唯一来源**）
    const sentRequestId = fired.request().headers()['x-client-request-id']
    if (!sentRequestId) throw new Error('UI 发出的发货请求**未带** X-Client-Request-Id（幂等键缺失 ⇒ 重试会发两次货）')
    const shipBody = JSON.parse(respText)
    const shipmentNo = shipBody?.data?.shipment_no
    if (!shipmentNo) {
      throw new Error(`原子端点响应无 data.shipment_no（信封形态变了？）：${JSON.stringify(shipBody).slice(0, 200)}`)
    }

    // ① 提交后**从 API 读**订单状态（不读 toast、不读前端状态）
    const readOrder = (await api.get(`/api/admin/orders/${orderId}`))?.data ?? {}
    if (readOrder.status !== 'shipped') {
      throw new Error(`提交后 API 读回的订单状态是 ${JSON.stringify(readOrder.status)}（期望 shipped）`)
    }
    if (readOrder.logistics?.trackingNo !== trackingNo) {
      throw new Error(`提交后 API 读回的运单号是 ${JSON.stringify(readOrder.logistics?.trackingNo)}（期望 ${trackingNo}）`)
    }

    // ② `order_shipments` **恰 +1 行**（真库读数 + API 读面各判一次）
    const after = await shipmentSnapshot(page, orderId)
    if (!shipmentDeltaOk(before.dbCount, after.dbCount)) {
      throw new Error(`order_shipments 未**恰 +1**：库读数 ${before.dbCount} → ${after.dbCount}`
        + `（API 读面 ${before.apiCount} → ${after.apiCount}）`)
    }
    if (!shipmentDeltaOk(before.apiCount, after.apiCount)) {
      throw new Error(`发货单读面 GET /orders/{id}/shipments 未**恰 +1**：${before.apiCount} → ${after.apiCount}`)
    }
    if (after.dbTracking !== trackingNo) {
      throw new Error(`库里的运单号是 ${JSON.stringify(after.dbTracking)}（期望 ${trackingNo}）`)
    }

    // ②的另一面：**同一 `X-Client-Request-Id` 重放** ⇒ 回放首次结果 ∧ 不再 +1 ∧ 运单号不被覆写
    // ⚠️ 重放**必须复用 UI 真发出去的那个键**（从请求头取；自造一个键只证得了服务端幂等，
    //    证不了「UI 发的这个键就是幂等键」）。复用同一 cookie ⇒ 同一租户/用户/权限主体。
    const replayBody = {
      company: '顺丰速运', trackingNo: 'SF-REPLAY-MUST-NOT-OVERWRITE',
      shippingMethod: 'logistics', logisticsType: 'express', shipperName: '重放探针',
    }
    // 用**浏览器会话的 cookie** 走 node 侧裸 fetch（与 adminApi 同一主体），但**读状态码 + 文本**
    // 而不抛：判红要能归因（端点 4xx 与「回放标志没置上」是两件不同的事，读数必须分开）。
    const at = (await page.context().cookies()).find((c) => c.name === 'access_token')
    const replayRes = await fetch(API_BASE + `/api/admin/production/orders/${orderId}/ship`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Cookie: `access_token=${at ? at.value : ''}`,
        'X-Client-Request-Id': sentRequestId,
      },
      body: JSON.stringify(replayBody),
    })
    const replayText = await replayRes.text()
    if (replayRes.status !== 200) {
      throw new Error(`同键重放（复用 UI 的 X-Client-Request-Id=${String(sentRequestId).slice(0, 8)}…）`
        + ` 被端点拒绝：HTTP ${replayRes.status}：${replayText.slice(0, 300)}`)
    }
    let replay = null
    try {
      replay = JSON.parse(replayText)
    } catch (e) {
      throw new Error(`同键重放响应不是 JSON：${replayText.slice(0, 200)}`)
    }
    if (replay?.data?.replayed !== true) {
      throw new Error(`同键第二次调用未回放（replayed=${JSON.stringify(replay?.data?.replayed)}）`
        + `：${JSON.stringify(replay?.data).slice(0, 200)}`)
    }
    if (replay?.data?.shipment_no !== shipmentNo) {
      throw new Error(`同键重放未回放首次结果：shipment_no=${JSON.stringify(replay?.data?.shipment_no)}（期望 ${shipmentNo}）`)
    }
    const afterReplay = await shipmentSnapshot(page, orderId)
    if (!shipmentDeltaOk(after.dbCount, afterReplay.dbCount, 0)) {
      throw new Error(`同键重放**又建了一行**：库读数 ${after.dbCount} → ${afterReplay.dbCount}（幂等失效）`)
    }
    if (afterReplay.dbTracking !== trackingNo) {
      throw new Error(`同键重放**覆写了运单号**：${trackingNo} → ${afterReplay.dbTracking}`)
    }

    await h.done(true, '', `订单 ${orderId}：UI 提交（X-Client-Request-Id=${String(sentRequestId).slice(0, 8)}…）`
      + ` → API 读回 status=${readOrder.status}/trackingNo=${readOrder.logistics?.trackingNo}；order_shipments `
      + `库 ${before.dbCount}→${after.dbCount}（API 读面 ${before.apiCount}→${after.apiCount}）；`
      + `同键重放 replayed=${replay.data.replayed} 且库仍 ${afterReplay.dbCount} 行、运单号未变`)
  } catch (e) {
    await h.done(false, `发货真提交失败: ${String(e).slice(0, 400)}`)
  }
}

// ────────────────────────── 售后 ──────────────────────────
async function afterSalesListJourney(page) {
  const h = await journey('18-after-sales-list')(page)
  try {
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
    // 🔴 issue #6942 ②：本旅程是同族**漏改处**（早先逐条补 `ensureLoggedIn` 时漏了它）
    //    ⇒ 单组跑（`--group 21`，无 01-login 前置）时 `/customers` 会把会话弹回 `/login`
    //    报「客户管理 8s 内不可见」+ 401。判据由 `test_ui_smoke_name_ledger.py` 判据 K 兜住。
    await ensureLoggedIn(page)
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
    await ensureLoggedIn(page)
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
  // 发码 400 是**登录路径**的环境限制（issue #6942 ②），不是本页的写请求失败 ⇒ 不进 `bad`；
  // 别的 4xx 一条都不放过（这段账本的意义就在「写请求失败必须判红」）。
  const onResponse = (r) => {
    if (r.status() < 400 || r.status() >= 500) return
    if (smsSendToleratedResponse(r.status(), r.request().method(), r.url())) {
      h.rec.notes.push('已知环境限制：登录发码被后端拒（不影响本页只读判定，issue #6942 ②）')
      return
    }
    bad.push(`${r.status()} ${r.request().method()} ${r.url()}`)
  }
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
    await ensureLoggedIn(page)
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
// 🔴 issue #6942 ③：门户四页**各自注册成一条旅程**（`journey('<名>')` 注册什么名，`jrun` 就用什么名）。
//    旧形态是 `jrun('27-corporate', corporatePages)` 里面再 `journey('27-corporate-home')` ——
//    注册名与台账名分家、`--group` 前缀过滤看不到内层名，正是名称漂移的温床。
async function corporateHome(page) {
  await corporatePage(page, '27-corporate-home', '/')
}

async function corporateAbout(page) {
  await corporatePage(page, '28-corporate-about', '/about')
}

async function corporateContact(page) {
  await corporatePage(page, '29-corporate-contact', '/contact')
}

async function corporateServices(page) {
  await corporatePage(page, '30-corporate-services', '/services')
}

/** 门户静态页渲染（四页同判据：非空白 + 渲染长度进证据）。 */
async function corporatePage(page, name, path) {
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

/**
 * 运行面的**名称台账漂移**判据（issue #6942 ③ 的 fail-closed 一半）：
 * 「**记了却没登记**」的名字 ⇒ 非空。进 `results` 就是**真实失败**（退出码 1）。
 *
 * 为什么必须有这一半：静态面判据（`test_ui_smoke_name_ledger.py` 判据 G）只能核
 * 「台账里的名字 **⊆** 代码里出现的名字」；反方向（新增了一条旅程却忘了登记台账）它**看不到**
 * —— 新名字是在 `journey('<新名>')` 的**注册点**才出现的，静态面上与台账无关。
 * 运行面能看见：真正被记录的名字一定经过 `journey()`，于是「记了却没登记」当场可判。
 */
function journeyLedgerDrift(recs) {
  const led = new Set(ALL_JOURNEY_NAMES)
  return [...new Set(recs.map((r) => r.journey))].filter((n) => !led.has(n))
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  page.on('response', (r) => { if (r.status() >= 400) failedResponses.push(`${r.status()} ${r.request().method()} ${r.url()}`) })

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
  // 🔴 issue #6982：**发货真提交**（真点【确认发货】→ 从 API / 真库读回断言落地）。
  // 传空 seed ⇒ 旅程**自造一张不含加工项**的订单（`16-` 那张含加工项，其发货页通常是守卫页
  // ⇒ 拿它做「真提交」会变成结构性 skip）；自造前置、不登记依赖（同 #6790 判据 ④ 的做法）。
  // 与 `16-` / `17-` 同形：**不走 `jrun` 的 45s 硬超时**（本旅程要跑真提交 + 两条读路 + 重放，
  // 45s 偏紧），故用 `inGroup` 显式登记（名称台账判据 G 认的就是 `jrun` / `inGroup` 两个注册点）。
  if (inGroup('17b-ship-order-real')) {
    await orderShipRealJourney(page, '')
  } else {
    recordSkip('17b-ship-order-real')
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
  await jrun('27-corporate-home', corporateHome, page)
  await jrun('28-corporate-about', corporateAbout, page)
  await jrun('29-corporate-contact', corporateContact, page)
  await jrun('30-corporate-services', corporateServices, page)
  await jrun('31-register', registerJourney, page)
  })()

  await Promise.race([runAll, runWatchdog])
  // 预算到点：剩下的旅程显式记 skip（不是失败）
  const recorded = new Set(results.map((r) => r.journey))
  for (const n of ALL_JOURNEY_NAMES) {
    if (!recorded.has(n)) recordSkip(n, `整轮预算 ${RUN_BUDGET_MS / 1000}s 到点：本轮未跑`)
  }
  // 🔴 运行面名称台账守卫（issue #6942 ③）：记了**却没登记**的名字 ⇒ 真实失败（fail-closed，见 journeyLedgerDrift）
  const ledgerDrift = journeyLedgerDrift(results)
  if (ledgerDrift.length) {
    const why = `旅程名台账漂移（**记了却没登记**）：${ledgerDrift.join(' ')} —— `
      + `把它们按**逐字注册名**补进 ALL_JOURNEY_NAMES（否则看门狗到点时会漏记 / 给不存在的名字补记 skip）`
    results.push({ journey: 'journey-name-ledger', pass: false, skipped: false, unconfigured: false,
      error_class: null, errors: [why], notes: [], evidence: [] })
    console.log(`❌ journey-name-ledger\n   ${why}`)
  }

  // ── 数据质量快照（SDQS，docs/testing/smoke-data-quality.md）──────────────
  // 🔴 旅程绿 ≠ 数据可用：2026-10-23 报 33/33 绿，而同轮自造商品一条 SKU 都没有。
  //    快照从**管理端 API 现读**各实体面；壳脚本用 scripts/smoke_data_quality.py 判 DQ-*，
  //    非零即折进整体退出码（数据不合格 = 冒烟红）。
  const snap = await collectDataSnapshot(page).catch((e) => ({
    schema_version: 1,
    collected_at: new Date().toISOString(),
    ran_journeys: [...new Set(results.map((r) => r.journey))],
    run: { journeys_total: results.length, journeys_pass: results.filter((r) => r.pass).length },
    entities: {},
    fixtures: {},
    collection_errors: [`快照采集异常：${String(e).slice(0, 300)}`],
  }))
  wfs(join(OUT, 'smoke-data.json'), JSON.stringify(snap, null, 2))
  console.log(`\n== 数据质量快照: ${join(OUT, 'smoke-data.json')}`
    + `（商品 ${snap.entities?.products?.total ?? '?'} 件 / 有 SKU ${snap.entities?.products?.with_skus ?? '?'} 件`
    + ` / 自造 ${snap.fixtures?.products_created ?? '?'} 件·带 SKU ${snap.fixtures?.products_with_skus ?? '?'} 件）`)

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
