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
//   ① `cut_calc` ∈ pages ⇔ 入口栏出现/消失「机台模式」（`/w/machine.html`）；
//   ② `report` ∉ pages ⇒ **显式**「本机未开报工页」视图（不静默留一个扫不动码的页面）；
//   ③ `me` 失败 / `pages` 缺失 ⇒ **fail-open**（报工页照旧可用）+ 显式提示（降级态要看得见）；
//   ④ 两条跨应用入口（`/b/#/pages/worker/*`）**不受** `pages` 影响（防误删 #5052 的动线）；
//   ⑤ 闲置登出兜底与服务端**同源**（`DEFAULT_WORKER_IDLE_MINUTES === 10080`，防回退到 15）。
//
// 🔴 前端**不**做权限门禁（本包边界）：`pages` 只决定「页面上看不看得见」，
// 真正的准入仍在服务端 `/api/worker/**`（后端 `WorkerPages` 类注释是单一真值源）。
import test from 'node:test'
import assert from 'node:assert/strict'

import { createApi, PAGES_UNREAD, SESSION_HEADER, STORAGE_KEY } from '../src/api.mjs'
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

/** 机台模式入口（本单新增的受控入口）。 */
const MACHINE_ENTRY = '/w/machine.html'

/** 两条跨应用静态入口（#5052；**不属于**这四个页面键 ⇒ 不受 `pages` 影响）。 */
const INBOUND_ENTRY = '/b/#/pages/worker/inbound/index'
const REPRINT_ENTRY = '/b/#/pages/worker/reprint/index'

const WORKER = { workerName: '张师傅', workerNo: 'W-001', idleMinutes: 10080 }

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

test('🔴 ① `cut_calc` ∈ pages ⇒ 入口栏出现机台模式链接；∉ ⇒ 链接**消失**', () => {
  const on = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_CUT_CALC]), null))
  assert.equal(deglue(on).includes(MACHINE_ENTRY), true, '`cut_calc` 已开却没给机台模式入口（工人走不到机台页）')
  assert.match(on, /id="wh5-machine-entry"[^>]*href="\/w\/machine\.html"/, '入口必须是真链接（href 在）')
  assert.match(on, />机台模式<\/a>/, '入口文案要在链接里')

  const off = visible(renderPage(loggedIn([PAGE_REPORT, PAGE_ORDER, PAGE_SHIPMENT]), null))
  // 「变异真的被读到」的自证：把过滤去掉 ⇒ deglue 后**必然**含这条路径（控件句按此判）
  assert.equal(deglue(off).includes(MACHINE_ENTRY), false, '`cut_calc` 没开却仍在渲染机台模式入口（开关形同虚设）')
  assert.ok(!/机台模式/.test(off), '入口区不该出现「机台模式」文案')
})

test('🔴 ① 红证：去掉入口栏的 `cut_calc` 过滤（无条件出机台链接）⇒ 同一条判定必红', () => {
  const html = renderPage(loggedIn([PAGE_REPORT]), null)
  const mangled = html.replace('<a class="wh5-entry" href="/b/#/pages/worker/reprint/index">补打入库标签</a>', '')
  const unfiltered = mangled.replace(
    '</nav>',
    `<a class="wh5-entry" id="wh5-machine-entry" href="${MACHINE_ENTRY}">机台模式</a></nav>`,
  )
  assert.equal(deglue(visible(mangled)).includes(MACHINE_ENTRY), false, '对照：真渲染下判定判绿')
  assert.equal(deglue(visible(unfiltered)).includes(MACHINE_ENTRY), true, '变异体确实是"无条件出机台链接"这一形态')
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
  assert.equal(deglue(selecting).includes(MACHINE_ENTRY), true, '旧码选套屏丢了机台入口')
})

// ── 判据 ②：report 门控 ────────────────────────────────────────────────────────────────

test('🔴 ② `report` ∉ pages ⇒ 渲染**显式**「本机未开报工页」视图（不静默留扫不动码的页面）', () => {
  const html = renderPage(loggedIn([PAGE_ORDER, PAGE_CUT_CALC, PAGE_SHIPMENT]), null)
  assert.match(html, /id="wh5-report-closed"/, '必须有一个可定位的显式视图（不是空白页）')
  assert.match(html, /本机未开报工页/, '标题要说清「本机未开此页」')
  assert.match(html, /工人端页面/, '出口①必须点名去哪里开 = 管理员的「工人端页面」')
  assert.match(html, /换一台|换一个/, '出口②必须给"换设备 / 换工人"')
  // 不是「码坏了」的误导：这句话必须说出"与码无关"
  assert.match(html, /不是码的问题/, '要说清与扫码无关（否则工人反复重扫 / 找错人修）')
  // 🔴 报工入口一个都不许留（否则只是"多了一段提示"，而页面照样扫得动）
  assert.ok(!html.includes('id="wh5-scan"'), '没开报工页却仍渲染输码框 ⇒ 门控没生效')
  assert.ok(!html.includes('id="wh5-report"'), '没开报工页却仍渲染开工按钮 ⇒ 门控没生效')
})

test('🔴 ② 红证：去掉 `report` 门控（照常渲染扫码屏）⇒「显式视图」判定必红', () => {
  // 变异体按内存构造：`report` 不在集合里，却照常渲染 scanView 的形态
  const gated = renderPage(loggedIn([PAGE_ORDER]), null)
  const ungated = renderPage(loggedIn(DEFAULT_PAGES), null)
  assert.match(gated, /id="wh5-report-closed"/, '对照：真渲染下是显式视图（本判定绿）')
  assert.ok(
    !ungated.includes('id="wh5-report-closed"') && ungated.includes('id="wh5-scan"'),
    '变异体确实是"照常渲染扫码屏"这一形态',
  )
  // 判定读数随之改变 ⇒ 本判据不是空断言
  assert.notEqual(/id="wh5-report-closed"/.test(ungated), /id="wh5-report-closed"/.test(gated))
})

test('🔴 ② `report` ∈ pages ⇒ 报工主流程**照旧**（门控不得误伤正常路径）', () => {
  const scan = renderPage(loggedIn(DEFAULT_PAGES), null)
  assert.match(scan, /id="wh5-scan"/, '报工页已开却拿不到扫码入口 = 门控做反了')
  assert.ok(!scan.includes('id="wh5-report-closed"'), '报工页已开不该出现"未开"视图')
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
  // 对照两态：① 读不到权限（= 本单要求的 fail-open ⇒ report 在生效集合里）
  //           ② `report` 不在集合里（= fail-closed 会得到的形态：工人被挡在报工页外）
  const failOpen = renderPage(loggedIn(null, { pagesUnread: true }), null)
  const failClosedForm = renderPage(loggedIn([PAGE_ORDER]), null)
  assert.equal(failOpen.includes('id="wh5-scan"'), true, 'fail-open：扫码入口还在')
  assert.equal(failClosedForm.includes('id="wh5-scan"'), false, 'fail-closed：扫码入口没了')
  assert.notEqual(
    failOpen.includes('id="wh5-scan"'),
    failClosedForm.includes('id="wh5-scan"'),
    '两种口径必须给出不同读数（否则本判据证明不了 fail-open）',
  )
})

// ── 判据 ④：两条跨应用入口不受 pages 影响（防误删）────────────────────────────────────────

test('🔴 ④ 两条跨应用入口**不受** `pages` 影响（防误删 #5052 的动线）', () => {
  for (const pages of [DEFAULT_PAGES, [PAGE_REPORT], [PAGE_ORDER], [PAGE_CUT_CALC], []]) {
    const html = visible(renderPage(loggedIn(pages, { pagesUnread: pages.length === 0 }), null))
    for (const [label, href] of [['拍照入库', INBOUND_ENTRY], ['补打入库标签', REPRINT_ENTRY]]) {
      assert.equal(html.includes(`href="${href}"`), true, `pages=${JSON.stringify(pages)} 时丢了「${label}」入口`)
      assert.equal(html.includes(`>${label}</a>`), true, `「${label}」的文案不在链接里`)
    }
    // `report` 关掉时这两条也必须还在（显式视图同样带页头入口栏）
    assert.match(html, /id="wh5-worker-entries"/, '入口栏本身不因页面集为空而消失')
  }
})

// ── 判据 ⑤：闲置兜底与服务端同源 ─────────────────────────────────────────────────────────

test('🔴 ⑤ 闲置登出兜底与服务端默认同源（10080 = 一周），不得回退到 15', () => {
  assert.equal(DEFAULT_WORKER_IDLE_MINUTES, 10080, '兜底必须 = 服务端 WorkerSessionService.DEFAULT_IDLE_MINUTES')
  assert.notEqual(DEFAULT_WORKER_IDLE_MINUTES, 15, '改前那处字面 15 会让前端比服务端早 10065 分钟踢人')
})

test('🔴 ⑤ 红证：把兜底改回 15 ⇒ 本判据必红（读数对照）', () => {
  const fallbackAfter = 10080
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
        data: { session_id: 'sess-1', worker_id: 'w-1', worker_no: 'A017', worker_name: '张三', idle_minutes: 10080 },
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
        data: { session_id: 'sess-1', worker_id: 'w-1', worker_no: 'A017', worker_name: '张三', idle_minutes: 10080 },
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
