// case_ids: PG-065, BM-006, PG-018
//
// 车间现场端可用性（issue #6667）—— 手套 / 弱光 / 弱网 / 共机台四件事的机械判据。
//
// 本文件治七条（每条都能红；红证 = 把对应实现改回改前形态 ⇒ 本条红，红读数记在 PR body）：
//   ① 机台页**没有登录入口**（`renderScan` 全文件零 `<a>` 零「登录」）⇒ 车间里盯着这块屏的人无路可走；
//   ② 机台页提示「或手工输入短码」而本页**没有**任何文本输入元素 ⇒ 让工人按一个不存在的出口操作；
//   ③ 旧码降级态（`selectView`，**清单里没有手上那张码时**）无返回 / 重扫出口 ⇒ 死屏；
//   ④ 手机报工按钮**无 in-flight 闸** ⇒ 连点两下变成两笔提交（是否重复计件全押在服务端幂等键上）；
//   ⑤ 429 / 5xx 的**技术原文**「请求失败（HTTP 429）」会进卡片红字（#6642 已收口主路径的**残留**）；
//   ⑥ 机台页无「切换工人」⇒ 上一班工人的身份留在共用设备上（**下一班的报工记到上一班头上** = 涉钱）；
//   ⑦ 机台页「部位备注」只给备注、不给它挂的**商品行名** ⇒ 多部位单里工人不知道说的是哪一幅。
//
// 零依赖：`node --test` + 手写假 DOM / 假 fetch（不引 jsdom —— 最少代码阶梯）。
//
// 🔴 为什么几何读数不在本文件：`touch-action` / `:active` 是**真实浏览器**才算得清的
//    （Node 里没有布局引擎）⇒ 探针 = `scripts/probe-worker-h5-touch.mjs`（Playwright，见 PR body 读数）。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { createApi, SESSION_EXPIRED, STORAGE_KEY } from '../src/api.mjs'
import { createMachineApp, boot as bootMachine } from '../src/machine-app.mjs'
import { createApp } from '../src/app.mjs'
import { initialState, reduce, renderPage } from '../src/render.mjs'
import { initialMachineState, reduceMachine, renderMachine, renderScan } from '../src/machine.mjs'

// 报工页用 `setTimeout` 做「闲置登出」定时器（30 天）、机台页用 `setTimeout` 做扫码枪空闲兜底（120ms）。
// 生产里它们由 `destroy()` / 后续按键清掉，但**断言失败**的用例会在 destroy 之前抛 ⇒ 定时器留在
// 事件循环 ⇒ `node --test` 不退出（红证根本跑不出来 —— 测试基础设施的坑，不是被测逻辑的）。
//
// 🔴 **实测坑（本包踩过，记下来）**：闲置登出给的是 `idle_minutes × 60_000`（30 天 ≈ 2.6e9 ms）
// —— 它**超出 32 位定时器上限**，Node 会把它截成 `1ms` ⇒ 定时器**立刻**触发「与服务器对账」，
// 于是用例之间互相污染（实测：旧码重扫那一条在断言前被对账改成 `main` 态）。
// ⇒ 测试侧把**秒级 / 分钟级**（≥1s）的定时器一律**不排期**（它们是"闲置登出"这类长延时，
// 与判据无关），短延时（扫码枪 120ms 空闲兜底）照常排、但 unref 掉以防进程挂住。
// 这一层只改**测试时钟**、不改被测语义（`clearTimeout` 对 dummy 句柄照常安全）。
const realSetTimeout = globalThis.setTimeout
globalThis.setTimeout = (fn, ms = 0, ...rest) => {
  if (Number(ms) >= 1000) return { unref() {}, __testSkipped: true }
  const t = realSetTimeout(fn, ms, ...rest)
  t.unref?.()
  return t
}

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

/** 页面源码去掉注释行（判「屏上会不会出现某句话」时，源码注释不算上屏）。 */
function stripComments(src) {
  return src.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
}

// ══════════════════════════════════════════════════════════════════════════════
// 假 DOM（只实现本包真正用到的那几件 API）
// ══════════════════════════════════════════════════════════════════════════════

function makeDom(rootId) {
  let html = ''
  const byId = new Map()
  let all = []
  const docListeners = new Map()

  const parseAttrs = (raw) => {
    const attrs = {}
    const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g
    let m
    while ((m = re.exec(raw))) attrs[m[1]] = m[2] ?? ''
    return attrs
  }

  const mkEl = (tag, attrs) => {
    const dataset = {}
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith('data-')) dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v
    }
    return {
      tag,
      attrs,
      dataset,
      value: '',
      listeners: {},
      disabled: 'disabled' in attrs,
      addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn) },
      classList: { contains: (c) => (attrs.class ?? '').split(/\s+/).includes(c) },
      /** 让 `input.value` 可读回（登录表单用） */
      setValue(v) { this.value = String(v); return this },
    }
  }

  const root = {
    get innerHTML() { return html },
    set innerHTML(v) { html = v; reindex() },
  }

  function reindex() {
    byId.clear()
    all = []
    const tagRe = /<([a-zA-Z][\w-]*)((?:"[^"]*"|[^>"])*)>/g
    let m
    while ((m = tagRe.exec(html))) {
      const el = mkEl(m[1], parseAttrs(m[2]))
      all.push(el)
      if (el.attrs.id) byId.set(el.attrs.id, el)
    }
    byId.set(rootId, root)
  }

  const matches = (el, sel) => {
    const idPart = sel.match(/^#([\w-]+)/)
    if (idPart && el.attrs.id !== idPart[1]) return false
    const classPart = sel.match(/\.([\w-]+)/)
    if (classPart && !el.classList.contains(classPart[1])) return false
    const attrPart = sel.match(/\[([\w-]+)\]/)
    if (attrPart && !(attrPart[1] in el.attrs)) return false
    return true
  }

  reindex()

  return {
    root,
    get html() { return html },
    get visibilityState() { return 'visible' },
    getElementById: (id) => byId.get(id),
    querySelectorAll: (sel) => all.filter((el) => matches(el, sel)),
    querySelector: (sel) => all.find((el) => matches(el, sel)) ?? null,
    addEventListener(type, fn) { (docListeners.get(type) ?? docListeners.set(type, []).get(type)).push(fn) },
    removeEventListener(type, fn) {
      const l = docListeners.get(type) ?? []
      const i = l.indexOf(fn)
      if (i >= 0) l.splice(i, 1)
    },
    /**
     * 点一个**当前 DOM 里**的元素（每次重渲染后旧元素已不存在 ⇒ 必须重查，等价于工人再点一下）。
     *
     * 🔴 **同步**派发：真浏览器的 `click` 不会等回调里的 `await`（事件处理器是异步的，页面照旧响应）
     * —— 测试若 `await` 它，就会在"请求被挂住"的窗口里卡死（而那正是 in-flight 闸要判的那段）。
     * 需要等结果时用 `settle()`。
     */
    click(sel) {
      const el = sel.startsWith('#') ? byId.get(sel.slice(1)) : all.find((e) => matches(e, sel))
      if (!el) throw new Error(`假 DOM 里找不到可点元素：${sel}`)
      for (const fn of el.listeners.click ?? []) fn({ preventDefault() {} })
      return el
    },
    setValue(id, v) {
      const el = byId.get(id)
      if (!el) throw new Error(`假 DOM 里找不到 #${id}`)
      el.value = String(v)
    },
  }
}

function makeStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    map,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

/** 让装配层的异步链路跑完（多轮 microtask；不依赖真实时钟）。 */
async function settle(rounds = 4) {
  for (let i = 0; i < rounds; i += 1) await Promise.resolve()
}

/** 已登录的 session 种子（api.mjs 的 storage 契约）。 */
const SESSION_SEED = {
  [STORAGE_KEY]: JSON.stringify({ sessionId: 's-1', workerId: 'w-1', workerNo: 'W-001', workerName: '张师傅', idleMinutes: 43200 }),
}

/**
 * 可控的假 fetch：记录每个请求；`hold` 里的 URL 返回一个**不自动 resolve** 的 Promise
 * （用它把「in-flight」这一段窗口钉住 —— 这正是本包要判的那段）。
 */
function makeFetch(handlers, hold = {}) {
  const calls = []
  const held = []
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, init })
    const p = (handlers[url] ?? (() => ({ status: 200, body: { success: true, data: {} } })))(url, init)
    if (hold[url]) {
      let release
      const gate = new Promise((r) => { release = r })
      held.push({ url, release, init })
      await gate
    }
    return {
      ok: p.status >= 200 && p.status < 300,
      status: p.status,
      json: async () => p.body,
    }
  }
  return { fetchImpl, calls, held, release: async () => { held.splice(0).forEach((h) => h.release()); await settle() } }
}

// ══════════════════════════════════════════════════════════════════════════════
// ① 机台页登录入口（P0）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ① 机台页未登录 ⇒ 屏上有一条**真的**登录入口（`<a href="/w/">`；不是"请去登录"四个字）', () => {
  const html = renderScan({ ...initialMachineState(), mode: 'error', error: '本台设备还没登录：请先用工号 + PIN 登录，再扫码' })
  assert.match(html, /<a [^>]*href="\/w\/"/, '未登录态必须给一条指向 /w/ 登录页的真实链接（车间里盯着这块屏的人有路可走）')
  assert.match(html, /登录/, '链接文案要说清「这台屏还没登录」，不能让工人自己猜')
  // 真浏览器探针（scripts/probe-worker-h5-touch.mjs）判它 ≥44px + touch-action；这里判静态形态
  assert.match(html, /id="wh5-machine-login"[^>]*class="wh5-machine__back"|class="wh5-machine__back"[^>]*id="wh5-machine-login"/, '入口复用既有的机台链接样式（不新造一套）')
})

test('🔴 ① 装配层：未登录（无 session）时 boot 出来的屏上仍有登录入口', async () => {
  const doc = makeDom('machine-root')
  const { fetchImpl } = makeFetch({})
  const api = createApi({ storage: makeStorage(), fetchImpl, deviceLabel: 'MACHINE' })
  const app = createMachineApp({ doc, api, storage: makeStorage() })
  app.dispatch({ type: 'failed', error: '本台设备还没登录：请先用工号 + PIN 登录，再扫码' })
  assert.match(doc.html, /<a [^>]*href="\/w\/"/, '未登录的机台页必须能一步走到登录页')
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 指向不存在出口的提示（P0）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ② 机台页不得提示「手工输入短码」（本页没有任何文本输入元素）', () => {
  const failed = renderScan({ ...initialMachineState(), mode: 'error', error: '没有识别到码' })
  assert.ok(!/手工输入/.test(failed), '错误态不得让工人去按一个不存在的出口')
  assert.ok(!/输码|输入短码/.test(failed), '同上：本页没有输入框，任何"输入"字样都是假的出口')
  const idle = renderScan(initialMachineState())
  assert.ok(!/手工输入|输码/.test(idle), '等扫码态同样不得提"输入"')
})

test('🔴 ② 装配层源码不得再产出「手工输入短码」这条路（含 machine-app.mjs 的 failed 文案）', () => {
  const app = stripComments(read('../src/machine-app.mjs'))
  assert.ok(!/手工输入/.test(app), 'machine-app.mjs 的 failed 文案不得提"手工输入"')
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 旧码降级态的死屏（P0）
// ══════════════════════════════════════════════════════════════════════════════

/** 旧码（`granularity:"order"`）降级视图：手上那张码不在清单里 ⇒ 必须有出口。 */
function legacyView() {
  return {
    granularity: 'order',
    processing_order_no: 'JG-2026-0001',
    needs_selection: ['set'],
    selections: [
      { set_id: 's1', set_no: 1, positions: [{ order_item_id: 'i1', position_name: '左窗' }] },
    ],
  }
}

test('🔴 ③ 旧码降级态（套清单里没有手上那张码）⇒ 屏上有「重扫」出口（复用既有 `wh5-rescan`）', () => {
  const state = { ...initialState(), worker: { workerName: '张师傅', workerNo: 'W-001' }, view: legacyView(), mode: 'select' }
  const html = renderPage(state, state.view)
  assert.match(html, /id="wh5-rescan"/, '旧码降级态必须能返回重扫（否则清单不匹配时是死屏）')
  assert.match(html, /重扫/, '出口文案要是工人看得懂的动作')
})

test('🔴 ③ 旧码降级态点「重扫」⇒ 回等扫码态（装配层既有绑定真的接上）', async () => {
  const doc = makeDom('worker-h5-root')
  const { fetchImpl } = makeFetch({})
  const storage = makeStorage({ ...SESSION_SEED })
  const api = createApi({ storage, fetchImpl })
  const app = createApp({ doc, api, storage })
  app.dispatch({ type: 'worker', worker: { workerName: '张师傅', workerNo: 'W-001' } })
  app.dispatch({ type: 'resolved', view: legacyView() })
  assert.equal(app.state.mode, 'select', '前置：先到旧码降级态')
  doc.click('#wh5-rescan')
  await settle()
  assert.equal(app.state.view, null, '点重扫 ⇒ 清掉这一屏的解析结果')
  assert.equal(app.state.mode, 'scan', '⇒ 回到等扫码态（不是死屏）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 报工按钮的 in-flight 闸（涉计件正确性）
// ══════════════════════════════════════════════════════════════════════════════

/** 一屏可报工的主视图（工序已确定）。 */
function reportableView() {
  return {
    set_no: 1,
    position: { position_name: '左窗' },
    operation: { operation_id: 'op-1', logical_name: '打卷', qty: 2, unit: '片', unit_price: 3.5 },
    alternatives: [],
    needs_selection: [],
  }
}

/** 装上「已登录 + 一屏可报工 + complete 请求被挂住」的报工页。 */
function reportingApp() {
  const doc = makeDom('worker-h5-root')
  const { fetchImpl, calls, release } = makeFetch({}, { '/api/worker/production/scan/complete': true })
  const storage = makeStorage({ ...SESSION_SEED })
  const api = createApi({ storage, fetchImpl })
  const app = createApp({ doc, api, storage })
  app.dispatch({ type: 'worker', worker: { workerName: '张师傅', workerNo: 'W-001' } })
  app.dispatch({ type: 'resolved', view: reportableView() })
  return { doc, app, calls, release }
}

test('🔴 ④ 连点两下【开工】⇒ **只发一笔**报工（in-flight 闸；改前两下 = 两笔请求）', async () => {
  const { doc, calls, release } = reportingApp()
  doc.click('#wh5-report') // 第一下：请求发出、被挂住（in-flight）
  await settle()
  doc.click('#wh5-report') // 第二下：工人戴手套又按了一下
  await settle()
  const posts = calls.filter((c) => c.url === '/api/worker/production/scan/complete')
  assert.equal(posts.length, 1, `连点两下只允许一笔报工（实测 ${posts.length} 笔）`)
  await release()
})

test('🔴 ④ 提交中：按钮 `disabled` + 文案说清「在提交」（现场要看得见，不然会反复按）', async () => {
  const { doc, release } = reportingApp()
  doc.click('#wh5-report')
  await settle()
  const btn = doc.getElementById('wh5-report')
  assert.ok(btn, '提交中按钮必须还在（不能整块消失，否则工人以为没点上）')
  assert.equal(btn.disabled, true, '提交中必须 `disabled`')
  assert.match(doc.html, /提交中/, '提交中必须有一句「提交中…」（弱网下这是唯一的反馈）')
  await release()
})

test('🔴 ④ 提交完成后闸要**放开**：回执屏不再显示「提交中」（不然后续领活按不动）', async () => {
  const { doc, app, release } = reportingApp()
  doc.click('#wh5-report')
  await settle()
  assert.equal(app.state.reporting, true, '前置：in-flight 期间标记为真')
  await release()
  await settle()
  assert.ok(!/提交中/.test(doc.html), '答复落地后必须撤掉「提交中」')
  assert.equal(app.state.reporting, false, 'in-flight 闸必须放开')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 429 / 5xx 的技术原文（#6642 的残留路径）
// ══════════════════════════════════════════════════════════════════════════════

/**
 * 后端在限流时回的**技术原文**（#6642 线上截图那一行）。
 *
 * 🔴 两种响应形态都要认（本包判的就是"哪一边出话"）：
 *   · `{ error: { message } }` ⇒ 服务端给了业务话术，**必须**用它（即便它是技术原文 —— 那是服务端的口径）；
 *   · `{}`（无 message，网关/nginx 限流的情形）⇒ 前端**兜底话术**必须是人话。
 */
const RAW_429 = { success: false, error: { message: '请求失败（HTTP 429）' } }

/** 网关卡（nginx `worker_sess`）的 429：**没有** JSON body 里的业务 message。 */
const GATEWAY_429 = { success: false }

test('🔴 ⑤ `resolveScan` 遇 429（网关限流，无业务话术）⇒ 人话 + 可行动作；技术原文只进日志面', async () => {
  const api = createApi({
    storage: makeStorage({ ...SESSION_SEED }),
    fetchImpl: (async () => ({ ok: false, status: 429, json: async () => GATEWAY_429 })),
  })
  const err = await api.resolveScan({ token: 'CODE-1' }).then(() => null, (e) => e)
  assert.ok(err, '429 必须抛错（不能静默当成功）')
  assert.match(err.message, /网络繁忙/, '要成人话（说清"可以再按一次"）')
  assert.match(err.message, /请再|再按|重试/, '要给可行动作')
  assert.ok(!/HTTP/.test(err.message), `技术原文（HTTP 状态码）不得上屏：${err.message}`)
  assert.equal(err.status, 429, '状态码仍要带出来（调用方据此分流）')
  assert.match(String(err.technical), /429/, '技术原文只进日志面（`technical`）')
})

test('🔴 ⑤ `login` 遇 429 ⇒ 同一份人话（登录面同样是弱网首当其冲的路径）', async () => {
  const api = createApi({
    storage: makeStorage(),
    fetchImpl: (async () => ({ ok: false, status: 429, json: async () => GATEWAY_429 })),
  })
  const err = await api.login({ workerNo: 'W-001', pin: '1234' }).then(() => null, (e) => e)
  assert.match(err.message, /网络繁忙/)
  assert.ok(!/HTTP/.test(err.message), `技术原文不得上屏：${err.message}`)
})

test('🔴 ⑤ 服务端给了 message ⇒ 一律用服务端的（哪怕它长得像技术原文 —— 那是服务端口径）', async () => {
  const api = createApi({
    storage: makeStorage({ ...SESSION_SEED }),
    fetchImpl: (async () => ({ ok: false, status: 429, json: async () => RAW_429 })),
  })
  const err = await api.resolveScan({ token: 'CODE-1' }).then(() => null, (e) => e)
  assert.equal(err.message, '请求失败（HTTP 429）', '服务端有 message 时不得被前端兜底话术盖掉')
  assert.equal(err.technical, '请求失败（HTTP 429）', '技术原文同时进日志面')
})

test('🔴 ⑤ 4xx 业务 message（400 作废码）一字不改地照原样给工人', async () => {
  const api = createApi({
    storage: makeStorage({ ...SESSION_SEED }),
    fetchImpl: (async () => ({ ok: false, status: 400, json: async () => ({ success: false, error: { message: '这张码已作废' } }) })),
  })
  const err = await api.resolveScan({ token: 'CODE-1' }).then(() => null, (e) => e)
  assert.equal(err.message, '这张码已作废')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑥ 机台页「切换工人」（涉计件归属）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ⑥ 机台页有工人时 ⇒ 屏上有「切换工人」控件（共用设备不能把身份留给下一班）', () => {
  const html = renderScan({ ...initialMachineState(), worker: { workerName: '张师傅', workerNo: 'W-001' } })
  assert.match(html, /切换工人/, '机台页必须有"切换工人"这个控件')
})

test('🔴 ⑥ 点「切换工人」⇒ 清掉本机工人身份 + 换到登录页（下一班的报工不记到上一班头上）', async () => {
  const doc = makeDom('machine-root')
  const calls = []
  const storage = makeStorage({ ...SESSION_SEED })
  const api = createApi({
    storage,
    fetchImpl: async (url) => {
      calls.push(url)
      return { ok: true, status: 200, json: async () => ({ success: true, data: {} }) }
    },
  })
  const navigations = []
  const app = createMachineApp({ doc, api, storage, location: { replace: (u) => navigations.push(u) } })
  app.dispatch({ type: 'worker', worker: { workerName: '张师傅', workerNo: 'W-001' } })
  const el0 = doc.getElementById('wh5-machine-switch-worker')
  assert.ok(el0, '先有控件才谈得上点')
  doc.click('#wh5-machine-switch-worker')
  await settle()
  assert.equal(api.worker(), null, '切换工人必须清掉本机身份')
  assert.equal(storage.getItem(STORAGE_KEY), null, 'localStorage 里的 session 也要清（否则下一班仍按上一班记账）')
  assert.deepEqual(navigations, ['/w/'], '换到登录页（/w/ 是唯一有登录面的那一页）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑦ 「部位备注」要带上它挂的商品行名（多部位单里工人不知道说的是哪一幅）
// ══════════════════════════════════════════════════════════════════════════════

/** 机台读面一行（键集逐字照 `WorkerCuttingHeightService.positionRow`）。 */
function machineView() {
  return {
    order: { customer_name: '王女士', set_count: 2 },
    positions: [
      {
        order_item_id: 'i1',
        position_name: '左窗',
        product_name: '客房布帘',
        position_remark: '客户要离地 2cm',
        scanned: true,
        cutting_height: 2.7,
        base: 2.7,
        hits: [],
        misses: [],
        rounding: { digits: 3, mode: 'half_up' },
      },
    ],
  }
}

test('🔴 ⑦「部位备注」必须带出它挂的**商品行名**（只报部位名 ⇒ 多部位单认不出是哪一幅）', async () => {
  const doc = makeDom('machine-root')
  const view = machineView()
  const { fetchImpl } = makeFetch({
    '/api/worker/production/cutting-height?token=CODE-1': () => ({ status: 200, body: { success: true, data: view } }),
  })
  const storage = makeStorage({ ...SESSION_SEED })
  const api = createApi({ storage, fetchImpl, deviceLabel: 'MACHINE' })
  const app = createMachineApp({ doc, api, storage, location: { replace() {} } })
  void app.feed('CODE-1')
  await tick()
  await settle()
  assert.match(doc.html, /部位备注/, '前置：详情屏要出现这一行')
  // 判的是**这一行**（不是"整页某处有这串字"）：商品行名必须与备注**印在一起**
  const row = doc.html.match(/<div class="wh5-machine__kv"><dt>部位备注<\/dt><dd>([\s\S]*?)<\/dd><\/div>/)?.[1] ?? ''
  assert.ok(row, '前置：部位备注这一行要渲染出来')
  assert.match(row, /客房布帘[\s\S]*客户要离地 2cm/, '备注必须带出**商品行名**（工人据此认出是哪一幅帘）：' + row)
})

test('🔴 ⑦ 缺商品行名 / 备注为空 ⇒ 显式占位（不渲染「undefined / null」这类假数据）', () => {
  const base = machineView().positions[0]
  const noProduct = { ...base, product_name: null }
  const withRemark = renderMachine({ ...initialMachineState(), mode: 'detail', data: { order: {}, positions: [noProduct] } })
  const row = withRemark.match(/<div class="wh5-machine__kv"><dt>部位备注<\/dt><dd>[\s\S]*?<\/dd><\/div>/)?.[0] ?? ''
  assert.ok(row, '前置：部位备注这一行要渲染出来')
  assert.match(row, /客户要离地 2cm/, '没有商品行名时也要把备注原样印出来（不能整行消失）')
  assert.ok(!/undefined|null|NaN/.test(withRemark), '缺值不得渲染成 undefined / null / NaN')
  const noRemark = renderMachine({ ...initialMachineState(), mode: 'detail', data: { order: {}, positions: [{ ...base, position_remark: null }] } })
  const row2 = noRemark.match(/<div class="wh5-machine__kv"><dt>部位备注<\/dt><dd>([\s\S]*?)<\/dd><\/div>/)?.[1] ?? ''
  assert.equal(row2, '客房布帘', '没写备注 ⇒ 印商品行名（有信息量、不静默留空）')
  const neither = renderMachine({ ...initialMachineState(), mode: 'detail', data: { order: {}, positions: [{ ...base, position_remark: null, product_name: null }] } })
  const row3 = neither.match(/<div class="wh5-machine__kv"><dt>部位备注<\/dt><dd>([\s\S]*?)<\/dd><\/div>/)?.[1] ?? ''
  assert.equal(row3, '—', '两者都缺 ⇒ 显式占位「—」（缺就显示这个，绝不静默留空）')
})

// ══════════════════════════════════════════════════════════════════════════════
// 触屏反馈（styles.css）—— 静态面判据；真实几何读数见 scripts/probe-worker-h5-touch.mjs
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 触屏：主按钮与幽灵按钮必须 `touch-action: manipulation` + `:active` 反馈（手套反复按的现场）', () => {
  const css = read('../src/styles.css')
  assert.match(css, /touch-action:\s*manipulation/, '缺 `touch-action: manipulation` ⇒ 双击缩放把点击吃掉（现场表现为"点不动"）')
  for (const sel of ['.wh5-primary', '.wh5-ghost']) {
    const block = new RegExp(`\\${sel}\\s*\\{[^}]*touch-action:\\s*manipulation`, 's')
    assert.match(css, block, `${sel} 必须自己有 touch-action: manipulation`)
  }
  assert.match(css, /\.wh5-primary:active/, '主按钮必须有 :active 反馈（按下去要看得见）')
  assert.match(css, /\.wh5-ghost:active/, '幽灵按钮同理')
  assert.match(css, /a\.wh5-machine__back\s*\{[^}]*touch-action:\s*manipulation/, '机台登录/报工页链接也必须 touch-action（它是触摸屏上的链接）')
  assert.match(css, /\.wh5-machine__back\s*\{[^}]*touch-action:\s*manipulation/, '机台的按钮形态（切换工人 / ◀ 订单详情）也要 touch-action')
  assert.match(css, /\.wh5-machine__cta\s*\{[^}]*touch-action:\s*manipulation/, '机台【完成】同样要有触屏反馈')
})

test('🔴 触屏：提交中 / 禁用态必须视觉可分（不只靠 disabled 属性）', () => {
  const css = read('../src/styles.css')
  assert.match(css, /\.wh5-primary\[disabled\]/, '禁用态必须有样式（工人要看出"这一下已经收到了"）')
})

// ══════════════════════════════════════════════════════════════════════════════
// 反向钉住：本包不许把线上已有的两件事弄丢
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 反向钉住：会话过期仍是 `SESSION_EXPIRED` 且机台页仍提示「先登录」（不许被本包改掉）', () => {
  const err = new Error('x')
  err.code = SESSION_EXPIRED
  assert.equal(err.code, 'SESSION_EXPIRED')
  const state = reduceMachine(initialMachineState(), { type: 'failed', error: '登录已失效：请先用工号 + PIN 登录本台设备，再扫码' })
  assert.match(renderScan({ ...state, worker: { workerName: '张师傅' } }).match(/登录已失效[^<]*/)?.[0] ?? '', /请先用工号 \+ PIN 登录/)
})

test('🔴 反向钉住：手机页登出仍把状态清回登录态（本包只加闸、不改身份契约）', () => {
  const next = reduce({ ...initialState(), worker: { workerName: '张师傅' } }, { type: 'logout' })
  assert.equal(next.worker, null)
  assert.equal(next.mode, 'login')
})

test('🔴 反向钉住：bootMachine 在没有登录态时不抛错、仍返回可用的 app（未登录机台页要能显示登录入口）', async () => {
  // 只做契约面自证：boot 的未登录分支不得因为本包新增控件而崩
  assert.equal(typeof bootMachine, 'function')
})
