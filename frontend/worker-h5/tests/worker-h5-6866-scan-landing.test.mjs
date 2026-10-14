// case_ids: PG-018, BM-045, DF-017
//
// 工人端 H5 —— **已登录工人扫部位码落地 `/w/?t=<码>` 必须自己解析**（issue #6866）。
//
// 病灶（现场，2026-10-14）：唯一消费 URL 码的地方是**登录成功**那一支
// （`frontend/worker-h5/src/app.mjs` 的 `wh5-login` 处理器 → `doScan`）；`boot()` 在**已有 session**
// 时只拉 `current-worker` + `/me`，**从不读 `?t=`**。工人会话闲置默认 30 天（`#6473`）⇒ 已登录是常态
// ⇒ 主路径失效，现场读作「扫了还要再输一遍单号」（与设计 `docs/design/worker-h5-scan-and-report.md`
// §0.2「一次扫码 = 1 步」相反）。
//
// 🔴 本文件把「装载时消费 URL 里的码」钉在**真装配入口 `boot()`**上（不是"源码里有这行"）：
// 假 localStorage（已登录）+ 假 `location`（`?t=`）+ 记录型假 `fetch`，然后 `await boot()`。
//   ① 已登录 + URL 带码 ⇒ 出现一次 `GET /api/worker/production/scan?token=<码>` 且屏上**不是**输码空态；
//   ② 读面不得写库 ⇒ 这条自动路径**零** `POST /api/worker/production/scan/complete`；
//   ③ 没有码 ⇒ 行为一字不变（已登录 / 未登录都是今天的输码空态）；
//      `?page=cut_calc` 的设备级预设门控照旧（未登录不换页、已登录按预设换页，**不解析码**）；
//   ④ 解析失败（无效码 / 已撤销 / 跨租户）⇒ 落到既有错误面（不白屏、不静默）。
//
// 红证（修前实测，同一份夹具）：① 的 `scan` 请求读数 = `[]`、屏上 `wh5-code` = 在 ⇒ 两条当场红。
import test, { afterEach } from 'node:test'
import assert from 'node:assert/strict'

import { boot } from '../src/app.mjs'
import { DEVICE_HOME_KEY } from '../src/app.mjs'
import { STORAGE_KEY } from '../src/api.mjs'

const PART_TOKEN = 'part-token-abc'
const SCAN_PATH = '/api/worker/production/scan'
const COMPLETE_PATH = '/api/worker/production/scan/complete'
const LANDING = `https://app.migaozn.com/w/?t=${PART_TOKEN}`

/** 服务端一屏（键与 `WorkerProductionScanService` 的响应逐字同形；页面按它渲染解析结果）。 */
const screen = () => ({
  granularity: 'set_position',
  set_no: '14',
  set_index: 13,
  set_count: 3,
  position: { order_item_id: 'oi-1', position_name: '布帘' },
  operation: { operation_id: 'op-1', determined_by: 'system', logical_name: '定型', unit: '米', qty: 11 },
  alternatives: [],
  needs_selection: [],
  completed: false,
})

const SESSION = JSON.stringify({ sessionId: 'sess-6866', workerId: 'w-1', workerNo: 'W-001', workerName: '张师傅' })
const WORKER_BODY = { worker_id: 'w-1', worker_no: 'W-001', worker_name: '张师傅' }
const ME_BODY = { worker_id: 'w-1', worker_name: '张师傅', pages: ['report', 'order', 'cut_calc', 'shipment'] }

/** 记录型假 fetch（与既有 worker-h5 测试同口径：队列出响应 + 逐次留痕）。 */
function stubFetch(routes) {
  const calls = []
  const fn = async (url, init = {}) => {
    const record = { url: String(url), method: init.method ?? 'GET', init }
    calls.push(record)
    const path = record.url.split('?')[0]
    const route = routes[path]
    const next = route ?? { status: 200, body: { success: true, data: {} } }
    return {
      ok: next.status >= 200 && next.status < 300,
      status: next.status,
      json: async () => next.body,
    }
  }
  fn.calls = calls
  /** 只留下命中该路径前缀的调用（`?` 之后不参与匹配）。 */
  fn.hits = (path) => calls.filter((c) => c.url.split('?')[0] === path)
  return fn
}

/** 内存 storage（浏览器是 localStorage）。 */
function memStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    dump: () => Object.fromEntries(map),
  }
}

/** 极简假 doc：装配层只用到 root / getElementById / querySelectorAll / addEventListener。 */
function fakeDoc() {
  const root = { innerHTML: '' }
  const listeners = new Map()
  return {
    root,
    html: () => root.innerHTML,
    getElementById: (id) => (id === 'worker-h5-root' ? root : null),
    querySelectorAll: () => [],
    addEventListener: (t, fn) => listeners.set(t, [...(listeners.get(t) ?? []), fn]),
    removeEventListener: (t, fn) => listeners.set(t, (listeners.get(t) ?? []).filter((f) => f !== fn)),
  }
}

/**
 * 每个用例**必须**销毁装配层（否则 30 天闲置定时器溢出成 1ms、`checkAlive` 立刻起一轮后台请求，
 * 与被测断言抢时序 ⇒ 变成 flake）。销毁是产物自身的公开出口（`app.destroy()`）。
 */
let opened = null
afterEach(() => { opened?.destroy(); opened = null })


/**
 * 装载一次（**真装配入口**）：注入已登录的 localStorage / 假 location / 假 fetch，然后 `boot()`。
 *
 * 🔴 `globalThis` 的读写都发生在 `boot()` 调用时（模块顶部只注册 `if (document.getElementById(...))`）
 * ⇒ 在这里临时换掉再还回去是安全的（同进程的其它测试文件不受影响）。
 */
async function loadPage({ href, storage, fetchImpl }) {
  const saved = {
    document: globalThis.document,
    localStorage: globalThis.localStorage,
    location: globalThis.location,
    fetch: globalThis.fetch,
  }
  const doc = fakeDoc()
  globalThis.document = doc
  globalThis.localStorage = storage
  globalThis.location = { href }
  globalThis.fetch = fetchImpl
  try {
    const app = await boot()
    opened = app
    return { app, doc, html: doc.html() }
  } finally {
    Object.assign(globalThis, saved)
  }
}

const loggedInStorage = (extra = {}) => memStorage({ [STORAGE_KEY]: SESSION, ...extra })

// ── 判据 ①：已登录 + URL 带码 ⇒ 装载时自动解析一次 ──────────────────────────────────────

test('🔴 ① 已登录 + /w/?t=<码> ⇒ boot() 之后自动 GET 解析一次，屏上是解析结果（不是输码空态）', async () => {
  const fetchImpl = stubFetch({
    '/api/worker/production/current-worker': { status: 200, body: { success: true, data: WORKER_BODY } },
    '/api/worker/me': { status: 200, body: { success: true, data: ME_BODY } },
    [SCAN_PATH]: { status: 200, body: { success: true, data: screen() } },
  })

  const { doc, html } = await loadPage({ href: LANDING, storage: loggedInStorage(), fetchImpl })

  // 🔴 红证读数（修前）：scan 请求 = [] ⇒ 下面第一条当场红
  const scan = fetchImpl.hits(SCAN_PATH)
  assert.equal(scan.length, 1, `装载时必须恰好解析一次（扫码落地 = 1 步）；实测 ${scan.length} 次`)
  assert.equal(scan[0].method, 'GET', '解析是读面，必须 GET')
  assert.equal(scan[0].url, `${SCAN_PATH}?token=${PART_TOKEN}`, '解析必须带上 URL 里那把码（token）')
  assert.equal(html.includes('id="wh5-code"'), false, '已在解析结果上，不该还停在「输码」空态')
  assert.equal(doc.root.innerHTML.includes('定型'), true, '解析结果必须真的渲染上屏（工序名）')
})

// ── 判据 ②：读面不得写库 ───────────────────────────────────────────────────────────────

test('🔴 ② 自动落地这一路只读：零 POST /scan/complete（写路仍只在工人点按钮时发生）', async () => {
  const fetchImpl = stubFetch({
    '/api/worker/production/current-worker': { status: 200, body: { success: true, data: WORKER_BODY } },
    '/api/worker/me': { status: 200, body: { success: true, data: ME_BODY } },
    [SCAN_PATH]: { status: 200, body: { success: true, data: screen() } },
  })

  const { app } = await loadPage({ href: LANDING, storage: loggedInStorage(), fetchImpl })

  // 反向自证（防恒真）：写面接口本身是接上的 —— 解析结果在 state 上挂着它的 token
  assert.equal(app.state.view?.__token, PART_TOKEN, '解析结果必须把码带在 state 上（否则写路无从发起）')
  assert.deepEqual(fetchImpl.hits(COMPLETE_PATH), [], '装载 ≠ 报工：自动路径不得发任何 scan/complete')
  assert.equal(fetchImpl.calls.some((c) => c.method !== 'GET'), false, '装载这一路全部必须是读面')
})

// ── 判据 ③：没有码 ⇒ 行为一字不变 ──────────────────────────────────────────────────────

test('③ 已登录 + /w/ 不带码 ⇒ 仍是今天的输码空态（且一个解析请求都不发）', async () => {
  const fetchImpl = stubFetch({
    '/api/worker/production/current-worker': { status: 200, body: { success: true, data: WORKER_BODY } },
    '/api/worker/me': { status: 200, body: { success: true, data: ME_BODY } },
  })

  const { doc, html } = await loadPage({ href: 'https://app.migaozn.com/w/', storage: loggedInStorage(), fetchImpl })

  assert.deepEqual(fetchImpl.hits(SCAN_PATH), [], '没有码 ⇒ 不得解析（不得拿路径段/页面名当码）')
  assert.equal(html.includes('id="wh5-code"'), true, '没有码就该是输码框（工人手输兜底）')
  assert.equal(doc.root.innerHTML.includes('id="wh5-operation"'), false, '没有码 ⇒ 没有解析结果面')
})

test('③ 未登录 + /w/ 不带码 ⇒ 仍是登录表单（本单不改未登录路径）', async () => {
  const fetchImpl = stubFetch({})
  const { html } = await loadPage({ href: 'https://app.migaozn.com/w/', storage: memStorage(), fetchImpl })
  assert.equal(html.includes('id="wh5-login"'), true, '未登录必须看到工号 + PIN 表单')
  assert.equal(fetchImpl.calls.length, 0, '未登录装载不发任何请求')
})

test('③ `?page=cut_calc` 门控照旧：已登录 ⇒ 换页且**不解析码**（预设优先）', async () => {
  const fetchImpl = stubFetch({
    '/api/worker/production/current-worker': { status: 200, body: { success: true, data: WORKER_BODY } },
    '/api/worker/me': { status: 200, body: { success: true, data: ME_BODY } },
    [SCAN_PATH]: { status: 200, body: { success: true, data: screen() } },
  })
  const storage = loggedInStorage()
  let navigated = null

  // `applyDeviceHome` 缺省换页动作 = 传进来的 `location.replace`（真浏览器里就是 globalThis.location）
  const saved = { document: globalThis.document, localStorage: globalThis.localStorage, location: globalThis.location, fetch: globalThis.fetch }
  const doc = fakeDoc()
  globalThis.document = doc
  globalThis.localStorage = storage
  globalThis.location = {
    href: `https://app.migaozn.com/w/?page=cut_calc&t=${PART_TOKEN}`,
    replace: (url) => { navigated = url },
  }
  globalThis.fetch = fetchImpl
  try {
    opened = await boot()
  } finally {
    Object.assign(globalThis, saved)
  }

  assert.equal(navigated, '/w/machine.html', '已登录 + 设备预设 ⇒ 必须换到裁高页')
  assert.equal(storage.getItem(DEVICE_HOME_KEY), 'cut_calc', '预设必须被钉在本机')
  assert.deepEqual(fetchImpl.hits(SCAN_PATH), [], '预设优先：换页了就不再解析码（否则是两条路同时生效）')
})

test('③ `?page=cut_calc` 门控照旧：**未登录**不换页（机台页没有登录面，换过去 = 把人关在门外）', async () => {
  const fetchImpl = stubFetch({})
  const storage = memStorage()
  const saved = { document: globalThis.document, localStorage: globalThis.localStorage, location: globalThis.location, fetch: globalThis.fetch }
  const doc = fakeDoc()
  globalThis.document = doc
  globalThis.localStorage = storage
  globalThis.location = {
    href: `https://app.migaozn.com/w/?page=cut_calc&t=${PART_TOKEN}`,
    replace: (url) => { throw new Error(`未登录不得换页（实测换到 ${url}）`) },
  }
  globalThis.fetch = fetchImpl
  try {
    opened = await boot()
  } finally {
    Object.assign(globalThis, saved)
  }

  assert.equal(doc.html().includes('id="wh5-login"'), true, '未登录必须留在登录页')
  assert.deepEqual(fetchImpl.hits(SCAN_PATH), [], '未登录不得解析码（码此刻无法校验归属）')
})

// ── 判据 ④：解析失败 ⇒ 落到既有错误面 ────────────────────────────────────────────────

test('④ 无效码 / 已撤销 / 跨租户 ⇒ 落到既有错误面（不白屏、不静默吞掉）', async () => {
  const fetchImpl = stubFetch({
    '/api/worker/production/current-worker': { status: 200, body: { success: true, data: WORKER_BODY } },
    '/api/worker/me': { status: 200, body: { success: true, data: ME_BODY } },
    [SCAN_PATH]: {
      status: 404,
      body: { success: false, error: { code: 'SCAN_NOT_FOUND', message: '这张码已作废，请找车间主管换一张' } },
    },
  })

  const { app, html } = await loadPage({ href: LANDING, storage: loggedInStorage(), fetchImpl })

  // 服务端点名的原因**逐字**上屏（既不吞掉、也不换一句泛化的）
  assert.match(html, /这张码已作废，请找车间主管换一张/, '解析失败必须把服务端那句原因显式上屏')
  assert.equal(/id="wh5-error"/.test(html) || /id="wh5-notice"/.test(html), true, '失败要落在既有的错误/提示面')
  assert.equal(app.state.view, null, '失败不得留一个半截解析结果')
  assert.equal(html.includes('id="wh5-code"'), true, '失败后面仍可用（输码兜底还在 ⇒ 没白屏、没把工人锁在外面）')
})
