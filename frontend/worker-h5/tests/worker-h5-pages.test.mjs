// case_ids: PG-065
//
// 工人端**页面开关**的前端消费面（V141，母单 #5161）。
//
// 治的形态（独立复核）：后端 `GET /api/worker/me` + `pages[]` 已合入 main，
// 而**全仓零消费方** ⇒ 开关不改变工人看到的任何东西（「文件名在 ≠ 被触发」）。
// 本文件把「开关**真的**改变页面」钉在**渲染结果**上（不是"源码里有这行"）：
// 删掉过滤 / 删掉门控 / 把 fail-open 改成 fail-closed ⇒ 对应断言当场红（红证见每条 test 注释）。
//
// 🔴 本文件钉五条（与交付单的五条判据一一对应）：
//   ① `cut_calc` ∈ pages ⇔ 入口栏出现/消失「裁高计算（一体机）」（`/w/machine.html`）；
//   ② `report` ∉ pages ⇒ **显式**「本机未开报工页」视图（不静默留一个扫不动码的页面）；
//   ③ `me` 失败 / `pages` 缺失 ⇒ **fail-open**（报工页照旧可用）+ 显式提示（降级态要看得见）；
//   ④ 两条跨应用入口**已移出本页**（2026-10-10 用户裁定，issue #6635）⇒ 反向钉住（出现即红）；
//   ⑤ 闲置登出兜底与服务端**同源**（`DEFAULT_WORKER_IDLE_MINUTES === 43200`，防回退到 15）。
//
// 🔴 前端**不**做权限门禁（本包边界）：`pages` 只决定「页面上看不看得见」，
// 真正的准入仍在服务端 `/api/worker/**`（后端 `WorkerPages` 类注释是单一真值源）。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { createApi, PAGES_UNREAD, SESSION_HEADER, STORAGE_KEY } from '../src/api.mjs'
import { applyDeviceHome, createApp, DEVICE_HOME_KEY } from '../src/app.mjs'
import { deviceHomeFromLocation } from '../src/scan-input.mjs'
import {
  DEFAULT_PAGES,
  DEFAULT_WORKER_IDLE_MINUTES,
  effectivePages,
  initialState,
  PAGE_CUT_CALC,
  PAGE_ORDER,
  PAGE_REPORT,
  PAGE_SHIPMENT,
  permUnreadNotice,
  reduce,
  renderPage,
} from '../src/render.mjs'

/** 后端 `WorkerPages.ALL` 的逐字镜像（改后端闭词表 ⇒ 本文件红）。 */
const BACKEND_PAGE_KEYS = [PAGE_REPORT, PAGE_ORDER, PAGE_CUT_CALC, PAGE_SHIPMENT]

/** 裁高计算入口（本页唯一的入口；文案 2026-10-10 起用「裁高计算（一体机）」）。 */
const MACHINE_ENTRY = '/w/machine.html'

/** 已移出本页的两条跨应用入口（2026-10-10 用户裁定；反向钉住：渲染里出现即红）。 */
const REMOVED_CROSS_APP = [
  ['拍照入库', '/b/#/pages/worker/inbound/index'],
  ['补打入库标签', '/b/#/pages/worker/reprint/index'],
]

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 43200 }

/**
 * 去掉「标识符里出现的路径」造成的**假命中**（`view.` 命中 `wx.` 的同族坑）。
 *
 * 🔴 为什么必须有：判据 ① 的"链接不在了"必须按**真链接**判 —— 若页面别处把这条路径拼进了
 * 一个**不含点号的标识符**（如 `machineHtml`），朴素的 `html.includes('/w/machine.html')`
 * 会照样绿，而工人**看不到**入口。
 *
 * ⚠️ 只掐「**紧邻**路径的标识符尾巴」那一段，**不**动路径本身：
 * 早先写成「删掉 `xxx.html`」会连 `href="/w/machine.html"` 里的**真路径**一起吃掉
 * ⇒ 判绿/判红都变成假的（这正是本文件要治的形态，不能自己先犯）。
 */
const deglue = (html) => html.replace(/([A-Za-z0-9_$])(?=\/w\/machine\.html|\/b\/#\/pages\/worker\/)/g, '')

/** 去 HTML 注释后的可见文本（注释里的锚点不是入口，同 #5052 的口径）。 */
const visible = (html) => html.replace(/<!--[\s\S]*?-->/g, '')

/**
 * 登录后的状态（`extra` 直接落在 state 上：`mode` / `view` 这类**装配层**才管的键
 * 不经 action 传 —— 那会把"装配"和"状态转移"两件事混在一起）。
 */
const loggedIn = (pages, extra = {}) => {
  const base = reduce(
    reduce(initialState(), { type: 'worker', worker: WORKER }),
    pages === undefined ? { type: 'pages' } : { type: 'pages', pages },
  )
  return { ...base, ...extra }
}

/** 极简 fetch 替身：记录每次调用，按队列返回响应（与既有 api 测试同口径）。 */
function stubFetch(responses) {
  const calls = []
  const queue = [...responses]
  const fn = async (url, init = {}) => {
    calls.push({ url, init, headers: init.headers ?? {} })
    const next = queue.shift() ?? { status: 200, body: { success: true, data: {} } }
    return { ok: next.status >= 200 && next.status < 300, status: next.status, json: async () => next.body }
  }
  fn.calls = calls
  return fn
}

/** 内存 storage（浏览器是 localStorage；这里用替身 ⇒ 无需 DOM）。 */
function memStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    _dump: () => Object.fromEntries(map),
  }
}

// ── 上游契约：页面键闭词表 + 默认全开（两处各一份，必须逐值相同）────────────────────────────

test('页面键闭词表 = 后端 WorkerPages.ALL 的逐字镜像（4 键 + 顺序；改一边不改另一边 ⇒ 红）', () => {
  assert.deepEqual(DEFAULT_PAGES, BACKEND_PAGE_KEYS, '默认页面集合与后端 WorkerPages.defaultPages() 不一致')
  assert.equal(new Set(DEFAULT_PAGES).size, DEFAULT_PAGES.length, '闭词表有重复键（后端是 Set，重复 = 两套口径）')
  assert.deepEqual(
    BACKEND_PAGE_KEYS,
    ['report', 'order', 'cut_calc', 'shipment'],
    '页面键是**冻结契约**（后端闭词表逐字）：拼错一个字母 ⇒ 商家的开关静默失效',
  )
})

test('`pages` 未被读过 / 空数组 ⇒ 按默认全开（fail-open，不是"全关"）', () => {
  // 红证：把 effectivePages 的 unread 分支换成"空集合" ⇒ 本断言当场红
  assert.deepEqual([...effectivePages(initialState()).opened].sort(), [...DEFAULT_PAGES].sort())
  assert.equal(effectivePages(initialState()).unread, true)
  assert.deepEqual([...effectivePages(loggedIn([])).opened].sort(), [...DEFAULT_PAGES].sort())
})

// ── 判据 ①：pages ⇔ 机台模式入口 ────────────────────────────────────────────────────────

test('🔴 ① `cut_calc` ∈ pages ⇒ 入口栏出现「裁高计算（一体机）」链接；∉ ⇒ 入口栏**不渲染**', () => {
  const on = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_CUT_CALC]), null))
  assert.equal(deglue(on).includes(MACHINE_ENTRY), true, '`cut_calc` 已开却没给裁高计算入口（那台屏走不到裁高页）')
  assert.match(on, /id="wh5-machine-entry"[^>]*href="\/w\/machine\.html"/, '入口必须是真链接（href 在）')
  assert.match(on, />裁高计算（一体机）<\/a>/, '入口文案要在链接里（且是人话 —— 2026-10-10 用户裁定）')

  const off = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_ORDER, PAGE_SHIPMENT]), null))
  // 「变异真的被读到」的自证：把过滤去掉 ⇒ deglue 后**必然**含这条路径（控件句按此判）
  assert.equal(deglue(off).includes(MACHINE_ENTRY), false, '`cut_calc` 没开却仍在渲染入口（开关形同虚设）')
  assert.ok(!/机台模式|裁高计算/.test(off), '入口区不该出现裁高计算文案')
  assert.ok(!off.includes('id="wh5-worker-entries"'), '没有可渲染的入口 ⇒ **不留空入口栏**（2026-10-10 改版）')
})

test('🔴 ① 红证：去掉入口栏的 `cut_calc` 过滤（无条件出裁高链接）⇒ 同一条判定必红', () => {
  const html = visible(renderPage(loggedIn([PAGE_REPORT]), null))
  const unfiltered = `${html}<nav class="wh5-entries" id="wh5-worker-entries"><a class="wh5-entry" id="wh5-machine-entry" href="${MACHINE_ENTRY}">裁高计算（一体机）</a></nav>`
  assert.equal(deglue(html).includes(MACHINE_ENTRY), false, '对照：真渲染下判定判绿（`cut_calc` 没开）')
  assert.equal(deglue(unfiltered).includes(MACHINE_ENTRY), true, '变异体确实是"无条件出入口链接"这一形态')
  assert.notDeepEqual(
    deglue(visible(unfiltered)).includes(MACHINE_ENTRY),
    deglue(visible(html)).includes(MACHINE_ENTRY),
    '去掉过滤后判定读数必须改变（否则本判据是空断言）',
  )
})

test('机台入口在**每一个登录后视图**都在（页头是共用件：扫 / 选套 / 主屏）', () => {
  const selecting = renderPage(
    loggedIn([PAGE_CUT_CALC], { mode: 'select', view: { needs_selection: [{}], selections: [] } }),
  )
  assert.equal(deglue(selecting).includes(MACHINE_ENTRY), true, '旧码选套屏丢了裁高计算入口')
})

// ── 判据 ②：**不硬拦截**（菜单显隐语义；2026-09-29 用户逐字改判，口径以 B 端 H5 为准）──────

test('🔴 ② `report` ∉ pages ⇒ 页面**照旧可用** + 一条**非阻断**提示（不拦访问）', () => {
  const html = renderPage(loggedIn([PAGE_ORDER, PAGE_CUT_CALC, PAGE_SHIPMENT]), null)
  // 提示：显式、可定位
  assert.match(html, /id="wh5-report-menu-closed"/, '必须有可定位的非阻断提示（菜单没开要说出来）')
  assert.match(html, /菜单未开报工页/, '提示要说清是"菜单未开"（不是码坏了）')
  assert.match(html, /本机报工仍可用/, '提示必须写明"页面仍可用"（否则读起来像被挡）')
  assert.match(html, /工人端页面/, '出口必须点名去哪里开 = 管理员的「工人端页面」')
  assert.match(html, /换一台|换一个/, '再给一条出口（换设备 / 换工人）')
  // 🔴 **不拦截**：报工主流程照旧（扫水洗唛 / 报工都能用）
  assert.match(html, /id="wh5-scan"/, '`report` 关掉就把扫码框挡掉 = 硬拦截（B 端 H5 不是这个语义）')
  assert.match(html, /id="wh5-report-menu-closed"[^>]*>/, '提示必须是**一条提示**，不是"整页替换"')
  assert.ok(!html.includes('id="wh5-report-closed"'), '旧的硬拦截视图不得再出现')
})

test('🔴 ② 双向钉住「不拦截」：去掉提示 ⇒ 红；把页面挡掉 ⇒ 也红', () => {
  // (a) 提示被去掉（只留能用的页面）⇒ 判定必红
  const noNotice = renderPage(loggedIn(DEFAULT_PAGES), null)
  assert.ok(!noNotice.includes('id="wh5-report-menu-closed"'), '对照：`report` 已开时本来就没有这条提示')
  // (b) 页面被挡掉（`wh5-scan` 不渲染）⇒ 判定也必红（= 改前那版硬门控的形态）
  const gatedForm = `${noNotice.replace('id="wh5-scan"', 'id="wh5-scan-gated-away"')}`
  assert.ok(!gatedForm.includes('id="wh5-scan"'), '变异体确实是"页面被挡掉"这一形态')
  // 两条判据各自只对一种变异敏感 —— 任一侧坏掉都会被下面任一 assert 抓住
  const withReportClosed = renderPage(loggedIn([PAGE_ORDER, PAGE_CUT_CALC, PAGE_SHIPMENT]), null)
  assert.equal(withReportClosed.includes('id="wh5-report-menu-closed"'), true, '提示在')
  assert.equal(withReportClosed.includes('id="wh5-scan"'), true, '页面也在（提示 ≠ 拦截）')
  assert.notEqual(withReportClosed.includes('id="wh5-scan"'), gatedForm.includes('id="wh5-scan"'))
  assert.notEqual(withReportClosed.includes('id="wh5-report-menu-closed"'), noNotice.includes('id="wh5-report-menu-closed"'))
})

test('🔴 ② `report` ∈ pages ⇒ 报工主流程**照旧**，且**没有**那条提示', () => {
  const scan = renderPage(loggedIn(DEFAULT_PAGES), null)
  assert.match(scan, /id="wh5-scan"/, '报工页已开却拿不到扫码入口 = 门控做反了')
  assert.ok(!scan.includes('id="wh5-report-menu-closed"'), '报工页已开不该出现"菜单未开"提示')
  const main = renderPage(loggedIn(DEFAULT_PAGES, {
    mode: 'main',
    view: {
      granularity: 'set_position',
      set_no: 1,
      position: { position_name: '布帘' },
      operation: { operation_id: 'op-1', logical_name: '定型', unit: '米', qty: 3, unit_price: 2 },
      alternatives: [],
      needs_selection: [],
      completed: false,
    },
  }))
  assert.match(main, /id="wh5-report"/, '报工页已开却拿不到【开工】按钮 = 门控做反了')
})

// ── 判据 ③：fail-open + 显式提示 ─────────────────────────────────────────────────────────

test('🔴 ③ `me` 失败 ⇒ fail-open（报工页照旧可用）+ 显式提示「按全开运行」', async () => {
  const boom = stubFetch([{ status: 500, body: { success: false, error: { message: '后端炸了' } } }])
  const api = createApi({ fetchImpl: boom, storage: memStorage(), baseUrl: 'https://app.migaozn.com' })
  await assert.rejects(() => api.readMe(), (e) => e.code === PAGES_UNREAD, '读面失败必须可分辨（PAGES_UNREAD）')

  // 红证：把 fail-open 改成 fail-closed（抛错时 pages=[] 且不允许全开）⇒ 下面两条当场红
  const degraded = loggedIn(null, { pagesUnread: true })
  const html = renderPage(degraded, null)
  assert.match(html, /id="wh5-scan"/, '读不到权限就把报工页挡掉 = 把"开关没读到"变成"活干不了"')
  assert.match(html, /id="wh5-perm-unread"/, '降级态必须在页面上**显式**说出来（silent fallback 会被当成开关生效）')
  assert.match(html, /按全开运行/, '提示文案要说清"按全开运行"')
  assert.equal(effectivePages(degraded).unread, true)
  assert.deepEqual([...effectivePages(degraded).opened].sort(), [...DEFAULT_PAGES].sort())
})

test('🔴 ③ `pages` 缺失 / 非数组 ⇒ 同一 fail-open 口径（旧版服务端不得让工人丢了报工页）', async () => {
  const noPages = stubFetch([
    { status: 200, body: { success: true, data: { worker_id: 'w-1', worker_name: '张三' } } },
  ])
  const api = createApi({ fetchImpl: noPages, storage: memStorage(), baseUrl: 'https://app.migaozn.com' })
  const me = await api.readMe()
  assert.equal(me.pages, null, '`pages` 缺失必须原样回 null（由调用方 fail-open），不得在这里编一份默认值')
  const html = renderPage(loggedIn(me.pages, { pagesUnread: me.pages === null }), null)
  assert.match(html, /id="wh5-scan"/, '无 `pages` 键却挡住报工 = fail-closed（本单硬约束是 fail-open）')
  assert.match(html, /id="wh5-perm-unread"/, '无 `pages` 键也要显式提示')
})

test('🔴 ③ 红证：改成 fail-closed ⇒ 判定必红（读数对照）', () => {
  // 两态的**可观察差**必须存在，否则本判据是空断言：
  //   ① 读不到权限（本单要求的 fail-open）⇒ 提示走 `wh5-perm-unread`（"按全开运行"）
  //   ② `report` 明示关掉 ⇒ 提示走 `wh5-report-menu-closed`，但**页面照旧**（不拦截）
  const failOpen = renderPage(loggedIn(null, { pagesUnread: true }), null)
  const reportOff = renderPage(loggedIn([PAGE_ORDER]), null)
  assert.equal(failOpen.includes('id="wh5-perm-unread"'), true, 'fail-open：降级提示在')
  assert.equal(reportOff.includes('id="wh5-perm-unread"'), false, '读到了权限就不该报"读不到"')
  assert.equal(reportOff.includes('id="wh5-report-menu-closed"'), true, '`report` 关掉 ⇒ 菜单提示在')
  // 🔴 两种口径都**不挡页面**（这是本单改判后的硬口径）
  assert.equal(failOpen.includes('id="wh5-scan"'), true, 'fail-open：扫码入口在')
  assert.equal(reportOff.includes('id="wh5-scan"'), true, '`report` 关掉也不拦访问（B 端 H5 语义）')
  assert.notEqual(
    failOpen.includes('id="wh5-perm-unread"'),
    reportOff.includes('id="wh5-perm-unread"'),
    '两种口径必须给出不同读数（否则本判据证明不了两个提示态可分）',
  )
})

// ── 判据 ④：两条跨应用入口不受 pages 影响（防误删）────────────────────────────────────────

test('🔴 ④ 两条跨应用入口**不再**由本页承载（2026-10-10 用户裁定；反向钉住 + 可达性移交工人工作台）', () => {
  for (const pages of [DEFAULT_PAGES, [PAGE_REPORT], [PAGE_ORDER], [PAGE_CUT_CALC], []]) {
    const html = visible(renderPage(loggedIn(pages, { pagesUnread: pages.length === 0 }), null))
    for (const [label, href] of REMOVED_CROSS_APP) {
      assert.equal(html.includes(href), false, `pages=${JSON.stringify(pages)} 时本页仍带着已移除的「${label}」入口`)
    }
    assert.ok(!html.includes('/b/#/pages/worker/'), '本页不得再出现任何 `/b/` 跨应用入口')
  }
  // ⚠️ 可达性**没有丢**：那两页的动线由**工人工作台**承载
  // （frontend/bmini-app/src/pages/worker/home/index.tsx；入口台账 `PAGE_ENTRY_LEDGER` 的 `from` 就是它），
  // 跨仓那一条判据在 frontend/bmini-app/tests/page-entry-reachability.test.ts 的 L5。
})

// ── 判据 ⑤：闲置兜底与服务端同源 ─────────────────────────────────────────────────────────

test('🔴 ⑤ 闲置登出兜底与服务端默认同源（43200 = 30 天），不得回退到 15', () => {
  assert.equal(DEFAULT_WORKER_IDLE_MINUTES, 43200, '兜底必须 = 服务端 WorkerSessionService.DEFAULT_IDLE_MINUTES')
  assert.notEqual(DEFAULT_WORKER_IDLE_MINUTES, 15, '改前那处字面 15 会让前端比服务端早 43185 分钟踢人')
})

test('🔴 ⑤ 红证：把兜底改回 15 ⇒ 本判据必红（读数对照）', () => {
  const fallbackAfter = 43200
  const fallbackBefore = 15
  assert.notEqual(fallbackAfter, fallbackBefore, '两版兜底的读数必须不同（否则本判据是空断言）')
  assert.equal(DEFAULT_WORKER_IDLE_MINUTES === fallbackAfter, true, '现值必须等于服务端同源值')
  assert.equal(DEFAULT_WORKER_IDLE_MINUTES === fallbackBefore, false, '现值不得等于改前的字面 15')
})

// ── 上游契约：`GET /api/worker/me` 这条路本身 ────────────────────────────────────────────

test('api.readMe() 打 `GET /api/worker/me` 并带既有的 X-Worker-Session-Id 头', async () => {
  const f = stubFetch([
    {
      status: 200,
      body: {
        success: true,
        data: { session_id: 'sess-1', worker_id: 'w-1', worker_no: 'A017', worker_name: '张三', idle_minutes: 43200 },
      },
    },
    {
      status: 200,
      body: { success: true, data: { worker_id: 'w-1', worker_name: '张三', pages: ['report', 'cut_calc'] } },
    },
  ])
  const store = memStorage()
  const api = createApi({ fetchImpl: f, storage: store, baseUrl: 'https://app.migaozn.com' })
  await api.login({ workerNo: 'A017', pin: '1234' })
  const me = await api.readMe()

  assert.equal(f.calls.length, 2, `只应发两次请求（login + me），实际 ${f.calls.length}`)
  assert.equal(f.calls[1].url, 'https://app.migaozn.com/api/worker/me', '读面端点必须是 GET /api/worker/me')
  assert.equal(f.calls[1].init?.method ?? 'GET', 'GET', '自助读面必须是只读 GET')
  assert.equal(f.calls[1].headers[SESSION_HEADER], 'sess-1', '必须带既有 session 头（身份只由服务端解）')
  assert.equal(SESSION_HEADER, 'X-Worker-Session-Id')
  assert.deepEqual(me.pages, ['report', 'cut_calc'], '`pages` 必须原样带回（本包不重排、不补全）')
  assert.ok(store.getItem(STORAGE_KEY), '登录态未受影响（读面不写本地）')
})

test('api.readMe() 的 401 ⇒ 抛 SESSION_EXPIRED 并清本地（身份面口径不变，不吞成 PAGES_UNREAD）', async () => {
  const f = stubFetch([
    {
      status: 200,
      body: {
        success: true,
        data: { session_id: 'sess-1', worker_id: 'w-1', worker_no: 'A017', worker_name: '张三', idle_minutes: 43200 },
      },
    },
    { status: 401, body: { success: false, error: { message: '工人登录已失效，请重新登录' } } },
  ])
  const store = memStorage()
  const api = createApi({ fetchImpl: f, storage: store, baseUrl: 'https://app.migaozn.com' })
  await api.login({ workerNo: 'A017', pin: '1234' })
  await assert.rejects(() => api.readMe(), (e) => e.code === 'SESSION_EXPIRED', '401 必须原样上抛会话过期')
  assert.equal(store.getItem(STORAGE_KEY), null, '401 ⇒ 清本地登录态（沿用既有口径）')
})

test('切换工人后页面集必须重拉（`logout` 清空 ⇒ 不沿用上一个人的页面）', () => {
  const before = loggedIn([PAGE_REPORT], { pagesUnread: false })
  assert.deepEqual([...effectivePages(before).opened], [PAGE_REPORT])
  const afterLogout = reduce(before, { type: 'logout' })
  assert.equal(afterLogout.pages, null, '登出后不得留着上一个人的页面集')
  assert.equal(effectivePages(afterLogout).unread, true, '重拉的窗口期按全开跑（fail-open），不是按上一个人的权限')
  // 重登后换一份页面集 ⇒ 渲染随之改变（"换人换权限"的接线处）
  const next = reduce(
    reduce(initialState(), { type: 'worker', worker: WORKER }),
    { type: 'pages', pages: [PAGE_REPORT, PAGE_CUT_CALC] },
  )
  assert.equal(deglue(renderPage(next, null)).includes(MACHINE_ENTRY), true, '换人后新权限没生效')
})

test('未知页面键被**忽略**（不因为多一个字符串就冒出对应的面）', () => {
  const html = renderPage(loggedIn([PAGE_REPORT, 'unknown_page', PAGE_CUT_CALC]), null)
  assert.ok(!html.includes('unknown_page'), '未知键不得出现在页面上')
  assert.equal(deglue(html).includes(MACHINE_ENTRY), true, '已知键仍要生效（未知键不能把整份集合废掉）')
})

test('`permUnreadNotice` 是**显式**文案（不是空串 —— 空串等于静默降级）', () => {
  assert.equal(typeof permUnreadNotice, 'string')
  assert.ok(permUnreadNotice.trim().length > 0, '提示文案不得为空')
  assert.match(permUnreadNotice, /全开/, '文案要说清降级口径 = 按全开运行')
})

// ── 判据 ⑥：设备级预设（issue #6635；用户 2026-10-10 裁定 = 设备级、零后端改动）──────────────
//
// 「让工人拿扫码枪直接扫码就默认为机台模式，而其他工人扫码默认报工」——落法 = **本机默认页**：
// 机台那台屏打开一次 `?page=cut_calc` 就记住，此后每次打开 `/w/` 直接落到裁高页；
// 手机工人不带参数 ⇒ 仍是报工页。**零后端改动**（不新增字段 / 不新增端点）。

test('🔴 ⑥ `?page=` 解析：只认两个值；`keep=1` = 只本次', () => {
  assert.deepEqual(deviceHomeFromLocation('https://app.migaozn.com/w/?page=cut_calc'), { page: 'cut_calc', once: false })
  assert.deepEqual(deviceHomeFromLocation('https://app.migaozn.com/w/?page=report'), { page: 'report', once: false })
  assert.deepEqual(deviceHomeFromLocation('https://app.migaozn.com/w/?page=report&keep=1'), { page: 'report', once: true })
  // 不认识的取值 ⇒ 当没带（绝不把任意参数读成设备预设）
  assert.deepEqual(deviceHomeFromLocation('https://app.migaozn.com/w/?page=machine'), { page: null, once: false })
  assert.deepEqual(deviceHomeFromLocation('https://app.migaozn.com/w/'), { page: null, once: false })
  assert.deepEqual(deviceHomeFromLocation('不是 URL'), { page: null, once: false })
})

test('🔴 ⑥ 钉住裁高页 ⇒ 落到 `/w/machine.html`；无参数 + 已钉住 ⇒ 仍然落过去（"开机即机台模式"）', () => {
  const store = memStorage()
  const nav = []
  const replace = (url) => nav.push(url)

  assert.equal(applyDeviceHome({ location: 'https://app.migaozn.com/w/?page=cut_calc', storage: store, replace, navigate: true }), 'cut_calc')
  assert.equal(nav.at(-1), '/w/machine.html', '钉住后本次就该换到裁高页')
  assert.equal(store.getItem(DEVICE_HOME_KEY), 'cut_calc', '预设要落盘（否则刷新就丢）')

  nav.length = 0
  assert.equal(applyDeviceHome({ location: 'https://app.migaozn.com/w/', storage: store, replace, navigate: true }), 'cut_calc')
  assert.equal(nav.at(-1), '/w/machine.html', '本机已钉住 ⇒ 下次打开 `/w/` 仍落到裁高页')
})

test('🔴 ⑥ 机台页的「去报工页」= `keep=1`：本次留在报工页，且**不改**本机预设', () => {
  const store = memStorage({ [DEVICE_HOME_KEY]: 'cut_calc' })
  const nav = []
  assert.equal(
    applyDeviceHome({ location: 'https://app.migaozn.com/w/?page=report&keep=1', storage: store, replace: (u) => nav.push(u), navigate: true }),
    'report',
  )
  assert.deepEqual(nav, [], 'keep=1 不得跳走')
  assert.equal(store.getItem(DEVICE_HOME_KEY), 'cut_calc', 'keep=1 不得改机台的预设（改了这台屏下次就不是机台模式了）')
})

test('🔴 ⑥ 取消钉住：`?page=report`（不带 keep）⇒ 本机回到普通报工页', () => {
  const store = memStorage({ [DEVICE_HOME_KEY]: 'cut_calc' })
  const nav = []
  assert.equal(applyDeviceHome({ location: 'https://app.migaozn.com/w/?page=report', storage: store, replace: (u) => nav.push(u), navigate: true }), 'report')
  assert.deepEqual(nav, [], '取消钉住后原地不动（就是报工页）')
  assert.equal(store.getItem(DEVICE_HOME_KEY), null, '取消钉住要落盘')
})

test('🔴 ⑥ 没钉过的本机（工人手机）⇒ **永远**留在报工页（不把普通工人带进机台页）', () => {
  const nav = []
  assert.equal(applyDeviceHome({ location: 'https://app.migaozn.com/w/', storage: memStorage(), replace: (u) => nav.push(u), navigate: true }), 'report')
  assert.deepEqual(nav, [])
})

test('🔴 ⑥ 不传 `replace` ⇒ 换页动作缺省取 `location.replace`（真浏览器那一条路径）', () => {
  // 红证（真浏览器验收实测过的形态）：把缺省 `go()` 去掉 ⇒ 本断言当场红 —— 而 `boot()` 只有一个
  // `globalThis.location`，它**不会**替调用方传 `replace` ⇒ 那条路径上的人再也换不过去（页面停在 `/w/`）。
  const nav = []
  const location = { href: 'https://app.migaozn.com/w/', replace: (url) => nav.push(url) }
  assert.equal(applyDeviceHome({ location, storage: memStorage({ [DEVICE_HOME_KEY]: 'cut_calc' }), navigate: true }), 'cut_calc')
  assert.deepEqual(nav, ['/w/machine.html'], '缺省换页动作没生效 ⇒ boot() 那处只拿到返回值、什么也没跳')
})

test('🔴 ⑥ **未登录不得换页**（机台页没有登录面 ⇒ 换过去 = 把人关在门外）', () => {
  // 红证（真浏览器验收实测踩过）：`navigate` 这道门去掉 ⇒ 未登录的机台屏被换到 `/w/machine.html`，
  // 而那一页**没有登录表单**（`#wh5-worker-no` 取不到）⇒ 工人连登录都做不到。
  const nav = []
  const location = { href: 'https://app.migaozn.com/w/?page=cut_calc', replace: (url) => nav.push(url) }
  const store = memStorage()
  assert.equal(
    applyDeviceHome({ location, storage: store, navigate: false }),
    'cut_calc',
    '返回值仍是"该落裁高页"（登录后由登录成功那处补跳），但**现在不跳**',
  )
  assert.deepEqual(nav, [], '未登录就换页 = 把人关在门外（机台页没有登录面）')
  assert.equal(store.getItem(DEVICE_HOME_KEY), 'cut_calc', '预设照旧落盘（登录成功后据此补跳）')

  // 接线判据：`boot()` 那道门必须真的接上 session
  const src = readFileSync(new URL('../src/app.mjs', import.meta.url), 'utf8')
  assert.match(src, /navigate: hasSession/, 'boot() 里 `navigate` 必须由「有没有工人 session」决定')
  assert.match(src, /const hasSession = Boolean\(api\.sessionId\(\)\)/, '门的值必须真来自 session')
})

test('🔴 ⑥ 存储不可用（隐私模式）⇒ 按"没钉成功"处理，**绝不因此拦住报工**', () => {
  const nav = []
  const hostile = {
    getItem: () => { throw new Error('storage disabled') },
    setItem: () => { throw new Error('storage disabled') },
    removeItem: () => { throw new Error('storage disabled') },
  }
  assert.equal(applyDeviceHome({ location: 'https://app.migaozn.com/w/?page=cut_calc', storage: hostile, replace: (u) => nav.push(u), navigate: true }), 'report')
  assert.deepEqual(nav, [], '存不下 ⇒ 不换页（留在报工页，活照干）')
})

test('🔴 ⑥ `applyDeviceHome` 是装配层唯一的换页出口（登录成功后也走它）', () => {
  // 反空跑：页码册里不能出现第二处写死 `/w/machine.html` 的跳转（否则"只此一处"是假的）
  const src = readFileSync(new URL('../src/app.mjs', import.meta.url), 'utf8')
  // 只判**代码行**（注释里提到那个路径是文档，不算写死）
  const code = src.split('\n').filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line)).join('\n')
  assert.equal((code.match(/machine\.html/g) ?? []).length, 0, 'app.mjs 的代码里不得写死机台页路径（换页只用 MACHINE_ENTRY_HREF）')
  assert.match(src, /MACHINE_ENTRY_HREF/, '换页用共享常量')
  assert.match(src, /applyDeviceHome/, '装配层必须接线设备预设')
  // 登录成功那处也要应用（机台屏的工人一次登录后就落到裁高页）
  assert.match(src, /gotoPinnedHome\(\)/, '登录成功后没有应用设备预设 ⇒ 机台屏登完还停在报工页')
})

test('`createApp` 导出面照旧（装配层没被设备预设改坏）', () => {
  assert.equal(typeof createApp, 'function')
})
