// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— **API 客户端 + 登录态**（issue #4716 §2.1 / §3.1~§3.3）。
//
// 本文件锁三条（每条都能红）：
//   ① 登录：工号 + PIN ⇒ `POST /api/worker/login`，session 落本地，后续请求带 `X-Worker-Session-Id`；
//   ② 🔴 **未登录不得报工**：无 session 时 `completeByScan()` 必须**抛错且一个请求都不发**（红证：去掉该闸 ⇒ 必红）；
//   ②′ 写入口 = `POST /api/worker/production/scan/complete`，**默认 body 只带 token**（#4792：
//      哪道工序由系统定 ⇒ 防呆⑤；一键改才带 `operation_id` ⇒ 归属由服务端校验 ⇒ 防呆④）；
//   ③ 401（session 过期/被切换）⇒ **回落未登录 + 清本地缓存**，绝不静默重试或按上一个人记账。
import test from 'node:test'
import assert from 'node:assert/strict'

import { createApi, SESSION_HEADER, STORAGE_KEY } from '../src/api.mjs'

/** 极简 fetch 替身：记录每次调用，按队列返回响应。 */
function stubFetch(responses) {
  const calls = []
  const queue = [...responses]
  const fn = async (url, init = {}) => {
    calls.push({ url, init, body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} })
    const next = queue.shift() ?? { status: 200, body: { success: true, data: {} } }
    return {
      ok: next.status >= 200 && next.status < 300,
      status: next.status,
      json: async () => next.body,
    }
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

const LOGIN_OK = {
  status: 200,
  body: {
    success: true,
    data: { session_id: 'sess-1', worker_id: 'w-1', worker_no: 'A017', worker_name: '张三', idle_minutes: 15 },
  },
}

test('① 登录：工号 + PIN ⇒ /api/worker/login，并把 session_id / 工人名落本地', async () => {
  const f = stubFetch([LOGIN_OK])
  const store = memStorage()
  const api = createApi({ fetchImpl: f, storage: store, baseUrl: 'https://app.migaozn.com' })

  const s = await api.login({ workerNo: 'A017', pin: '1234', tenantId: 7 })

  assert.equal(f.calls.length, 1)
  assert.equal(f.calls[0].url, 'https://app.migaozn.com/api/worker/login')
  assert.deepEqual(f.calls[0].body, { workerNo: 'A017', pin: '1234', deviceLabel: 'H5', tenantId: 7 })
  assert.equal(s.sessionId, 'sess-1')
  assert.equal(s.workerName, '张三')
  assert.equal(api.sessionId(), 'sess-1')
  assert.equal(api.worker().workerName, '张三')
  assert.ok(store.getItem(STORAGE_KEY), '登录态必须落本地（设备记住登录）')
})

test('① 后续请求带 X-Worker-Session-Id（与 #4733 逐字同名）', async () => {
  const f = stubFetch([LOGIN_OK, { status: 200, body: { success: true, data: { granularity: 'set_position' } } }])
  const api = createApi({ fetchImpl: f, storage: memStorage(), baseUrl: 'https://app.migaozn.com' })
  await api.login({ workerNo: 'A017', pin: '1234' })
  await api.resolveScan({ token: 'tok-1' })

  assert.equal(SESSION_HEADER, 'X-Worker-Session-Id')
  assert.equal(f.calls[1].headers[SESSION_HEADER], 'sess-1')
  assert.match(f.calls[1].url, /\/api\/worker\/production\/scan\?token=tok-1$/)
})

test('🔴 ② 未登录不得报工：无 session ⇒ 抛错且**一个请求都不发**', async () => {
  const f = stubFetch([])
  const api = createApi({ fetchImpl: f, storage: memStorage(), baseUrl: 'https://app.migaozn.com' })

  await assert.rejects(
    () => api.completeByScan({ token: 'tok-1' }),
    /登录/,
  )
  assert.equal(f.calls.length, 0, '未登录时报工必须 fail-closed，不得发出请求')
})

test('② 已登录报工：走工人路径 `scan/complete` + 幂等键 + 身份**不进 body**（默认只带 token）', async () => {
  const f = stubFetch([
    LOGIN_OK,
    {
      status: 200,
      body: {
        success: true,
        data: {
          operation_id: 'op-1', done_qty: 11, status: 'done', order_completed: false,
          set_no: 14, position: { order_item_id: 'oi-1', position_name: '布帘' }, set_completed: false,
          next_operation: { operation_id: 'op-2', logical_name: '打卷' },
        },
      },
    },
  ])
  const api = createApi({ fetchImpl: f, storage: memStorage(), baseUrl: 'https://app.migaozn.com' })
  await api.login({ workerNo: 'A017', pin: '1234' })

  const r = await api.completeByScan({ token: 'tok-1', clientRequestId: 'req-1' })

  assert.equal(f.calls[1].url, 'https://app.migaozn.com/api/worker/production/scan/complete')
  // 🔴 默认**只带 token**：URL 里没有 orderId/operationId ⇒ 哪道工序由**服务端**推断（防呆⑤），
  // 数量由服务端取「剩余应做」（A 模式：做完扫一次 = 完工）
  assert.deepEqual(f.calls[1].body, { token: 'tok-1' })
  assert.ok(!('worker_id' in f.calls[1].body), '工人路径的身份只来自 session，body 不得带 worker_id')
  assert.equal(f.calls[1].headers['X-Client-Request-Id'], 'req-1')
  assert.equal(r.doneQty, 11)
  assert.equal(r.setNo, 14, '回执的套号必须透出来（一屏要用）')
  assert.equal(r.nextOperation.operation_id, 'op-2', '回执的「下一道」必须透出来（接着做）')
})

test('② 一键改 / 显式数量：才带 operation_id / qty（默认路径一个都不带）', async () => {
  const f = stubFetch([
    LOGIN_OK,
    { status: 200, body: { success: true, data: { operation_id: 'op-2', done_qty: 6 } } },
  ])
  const api = createApi({ fetchImpl: f, storage: memStorage(), baseUrl: '' })
  await api.login({ workerNo: 'A017', pin: '1234' })

  await api.completeByScan({ token: 'tok-1', operationId: 'op-2', qty: 6, qualifiedQty: 6, workType: 'rework' })

  assert.deepEqual(f.calls[1].body, { token: 'tok-1', operation_id: 'op-2', qty: 6, qualified_qty: 6, work_type: 'rework' })
})

test('🔴 ③ 401（闲置超时 / 已被切换）⇒ 抛 SESSION_EXPIRED 且**清本地缓存**（不静默续期）', async () => {
  const f = stubFetch([LOGIN_OK, { status: 401, body: { success: false, error: { code: 'UNAUTHORIZED' } } }])
  const store = memStorage()
  const api = createApi({ fetchImpl: f, storage: store, baseUrl: 'https://app.migaozn.com' })
  await api.login({ workerNo: 'A017', pin: '1234' })

  await assert.rejects(() => api.resolveScan({ token: 'tok-1' }), (e) => e.code === 'SESSION_EXPIRED')
  assert.equal(api.sessionId(), null, '401 后必须回落未登录')
  assert.equal(store.getItem(STORAGE_KEY), null, '401 后必须清本地缓存（不许把上一个人留在设备上）')
})

test('登录失败（工号/PIN 错）⇒ 抛错且不落任何登录态', async () => {
  const f = stubFetch([{ status: 401, body: { success: false, error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' } } }])
  const store = memStorage()
  const api = createApi({ fetchImpl: f, storage: store, baseUrl: '' })

  await assert.rejects(() => api.login({ workerNo: 'A017', pin: 'x' }), /工号或 PIN 不正确/)
  assert.equal(api.sessionId(), null)
  assert.equal(store.getItem(STORAGE_KEY), null)
})

test('logout：调 /api/worker/session/logout 并清本地（幂等，无 session 也清）', async () => {
  const f = stubFetch([LOGIN_OK, { status: 200, body: { success: true } }])
  const store = memStorage()
  const api = createApi({ fetchImpl: f, storage: store, baseUrl: '' })
  await api.login({ workerNo: 'A017', pin: '1234' })
  await api.logout()

  assert.match(f.calls[1].url, /\/api\/worker\/session\/logout$/)
  assert.equal(api.sessionId(), null)
  assert.equal(store.getItem(STORAGE_KEY), null)
})

test('currentWorker：页头「当前工人」取自**服务端**（不是前端 state）', async () => {
  const f = stubFetch([
    LOGIN_OK,
    { status: 200, body: { success: true, data: { worker_id: 'w-1', worker_no: 'A017', worker_name: '李四' } } },
  ])
  const api = createApi({ fetchImpl: f, storage: memStorage(), baseUrl: '' })
  await api.login({ workerNo: 'A017', pin: '1234' })
  const w = await api.currentWorker()

  assert.match(f.calls[1].url, /\/api\/worker\/production\/current-worker$/)
  assert.equal(w.workerName, '李四', '页头必须以服务端返回为准（PAD 共用时前端 state 不可信）')
})

test('🔴 红线：写请求 body 绝不携带 unit_price / factor / set_id / order_item_id（历史计件单价一字不动，§3.6 W6）', async () => {
  const f = stubFetch([
    LOGIN_OK,
    { status: 200, body: { success: true, data: { operation_id: 'op-2', done_qty: 11 } } },
  ])
  const api = createApi({ fetchImpl: f, storage: memStorage(), baseUrl: '' })
  await api.login({ workerNo: 'A017', pin: '1234' })

  // 即便调用方硬塞这些键，也不得进入请求体（服务端白名单只认 token/operation_id/qty/qualified_qty/work_type）
  await api.completeByScan({
    token: 'tok-1', operationId: 'op-2', qty: 11, qualifiedQty: 11, workType: 'normal',
    unitPrice: 9.9, factor: 2, setId: 'set-1', orderItemId: 'oi-1', clientRequestId: 'req-2',
  })

  const body = f.calls[1].body
  assert.ok(!('unit_price' in body), '🔴 写请求 body 不得携带 unit_price（历史计件单价是工资凭证）')
  assert.ok(!('factor' in body), '🔴 写请求 body 不得携带 factor')
  // 🔴 D1（#4792）：旧码收口需要切片① 契约扩展 ⇒ 本单**不**硬塞 set_id/order_item_id
  assert.ok(!('set_id' in body), '本单不扩契约：body 不得出现 set_id')
  assert.ok(!('order_item_id' in body), '本单不扩契约：body 不得出现 order_item_id')
  assert.deepEqual(Object.keys(body).sort(), ['operation_id', 'qty', 'qualified_qty', 'token', 'work_type'])
})

test('🔴 红线：页面只读 unit_price 用于显示（未定价 ≠ 0），从不写它', async () => {
  const src = (await import('node:fs')).readFileSync(new URL('../src/render.mjs', import.meta.url), 'utf8')
    + (await import('node:fs')).readFileSync(new URL('../src/api.mjs', import.meta.url), 'utf8')
  // 判据形态：看**代码**（剥掉注释行）里有没有这两个键的读写 —— 注释里「提到」不算
  // （与 case_ids 声明同族口径：正文提及 ≠ 声明）。
  const code = src.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
  assert.ok(!/unit_price\s*:/.test(code), '前端不得构造 unit_price 字段（服务端在报工那一刻固化的快照）')
  assert.ok(!/\bfactor\b/.test(code), '前端不得触碰 factor')
  assert.match(src, /unit_price/, '但**读**面必须保留 unit_price（未定价 ≠ 0 的显示判据要用它）')
})
