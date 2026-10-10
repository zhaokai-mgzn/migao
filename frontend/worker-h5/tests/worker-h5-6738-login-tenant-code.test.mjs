// case_ids: BM-045, PG-065, BM-006
//
// 工人端登录：**企业编码归一** + **形状校验失败的屏面文案**（issue #6738）。
//
// 本文件钉四组（每组都能红；红证 = 把实现改回改前形态 ⇒ 必红，读数记在 PR body）：
//   ① **归一**：企业编码提交前归一为小写（去首尾空白、保留下划线与连字符）——纯函数 + **真装配层**两处；
//   ② **文案**：形状校验失败（422 `VALIDATION_ERROR`）**不得**把服务端的内部口径「参数校验失败」印上屏；
//      服务端已经给了**逐字段**的可行动理由（`error.details[].message`，实测
//      `{"field":"pin","message":"PIN 不能为空"}`）⇒ 必须用它；
//   ③ **不泄露**：反枚举口径**一字不动**（工号不存在 / PIN 错 / 企业编码不存在 ⇒ 同一个 401 同一文案）；
//   ④ **类级**：worker-h5 面挂到**既有**那把用户可见文案尺子（`frontend/admin-web/scripts/user-copy-scan.mjs`）
//      —— **不新立第二把**；worker-h5 面的豁免台账必须是 **0**（只许缩短、未登记即红）。
//
// 🔴 **真值不只靠读码（本单实测，2026-10-11 对生产 `https://app.migaozn.com/api/worker/login`）**：
//    · `enterpriseCode:"UITEST01"` + PIN 有值  ⇒ **401** `{"code":"AUTH_FAILED","message":"工号或 PIN 不正确"}`
//      —— 大写**不会**触发 422：服务端 `WorkerTenantResolver.resolve` 先过
//      `LoginIdentifiers.normalize()`（转小写）再解析 ⇒ 归一是**前端自证一致**，不是"修一个 422"；
//    · `enterpriseCode:"UITEST01"` + **PIN 留空** ⇒ **422** `{"code":"VALIDATION_ERROR",
//      "message":"参数校验失败","details":[{"field":"pin","message":"PIN 不能为空"}]}` ← 屏上那句「参数校验失败」的真身；
//    · `workerNo:""` ⇒ 422 同上（`details[0].message = "工号不能为空"`）；
//    · `enterpriseCode:""` ⇒ 422 但是**可行动**文案（「无法识别租户：请填写企业编码（向商家索取，例如 migao）」）。
//    ⇒ 复算：`curl -s -X POST https://app.migaozn.com/api/worker/login -H 'Content-Type: application/json' \
//        -d '{"workerNo":"w001","pin":"","enterpriseCode":"UITEST01"}'`
//
// 零依赖：`node --test` + 手写假 DOM / 假 fetch（不引 jsdom —— 最少代码阶梯）。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { createApi } from '../src/api.mjs'
import { createApp } from '../src/app.mjs'
import { normalizeEnterpriseCode } from '../src/scan-input.mjs'

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** 服务端在形状校验失败时回的**内部口径**（`GlobalExceptionHandler` 的 `MethodArgumentNotValidException` 分支）。 */
const INTERNAL_WORDING = '参数校验失败'

/** 生产实测的三个响应形状（逐字，2026-10-11）。 */
const RESP_422_PIN_BLANK = {
  success: false,
  error: { code: 'VALIDATION_ERROR', message: INTERNAL_WORDING, details: [{ field: 'pin', message: 'PIN 不能为空' }] },
}
const RESP_422_TENANT_MISSING = {
  success: false,
  error: { code: 'VALIDATION_ERROR', message: '无法识别租户：请填写企业编码（向商家索取，例如 migao）' },
}
/** 反枚举口径（企业编码不存在 / 工号不存在 / PIN 错 ⇒ 同一个 401 同一文案）。 */
const RESP_401_AUTH_FAILED = { success: false, error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' } }

// ══════════════════════════════════════════════════════════════════════════════
// 夹具：假 DOM / 假 fetch / 内存 storage
// ══════════════════════════════════════════════════════════════════════════════

/** 报工页用 `setTimeout` 做闲置登出（30 天 ≈ 2.6e9 ms 超出 32 位上限 ⇒ Node 截成 1ms 会**立刻**触发对账，
 *  实测会污染用例）⇒ 测试侧对 ≥1s 的长延时**不排期**；短延时照排但 unref（只改测试时钟，不改被测语义）。 */
const realSetTimeout = globalThis.setTimeout
globalThis.setTimeout = (fn, ms = 0, ...rest) => {
  if (Number(ms) >= 1000) return { unref() {}, __testSkipped: true }
  const t = realSetTimeout(fn, ms, ...rest)
  t.unref?.()
  return t
}

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
      addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn) },
      classList: { contains: (c) => (attrs.class ?? '').split(/\s+/).includes(c) },
    }
  }

  const root = { get innerHTML() { return html }, set innerHTML(v) { html = v; reindex() } }

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
    return true
  }

  reindex()

  return {
    get html() { return html },
    get visibilityState() { return 'visible' },
    getElementById: (id) => byId.get(id),
    querySelectorAll: (sel) => all.filter((el) => matches(el, sel)),
    querySelector: (sel) => all.find((el) => matches(el, sel)) ?? null,
    addEventListener(type, fn) { (docListeners.get(type) ?? docListeners.set(type, []).get(type)).push(fn) },
    removeEventListener() {},
    async click(sel) {
      const el = sel.startsWith('#') ? byId.get(sel.slice(1)) : all.find((e) => matches(e, sel))
      if (!el) throw new Error(`假 DOM 里找不到可点元素：${sel}`)
      for (const fn of el.listeners.click ?? []) await fn({ preventDefault() {} })
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
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

/** 记录请求的 fetch 替身；`respond` 决定每个请求的答复（默认 200 空）。 */
function makeFetch(respond = () => ({ status: 200, body: { success: true, data: {} } })) {
  const calls = []
  const fn = async (url, init = {}) => {
    calls.push({ url, body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} })
    const r = respond(url, init)
    return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body }
  }
  fn.calls = calls
  return fn
}

/** 屏上红字（`#wh5-error` 的文本）—— 判据对象是**工人看到的那句话**，不是 `err.message`。 */
const errorText = (html) => html.match(/<p class="wh5-error" id="wh5-error">([\s\S]*?)<\/p>/)?.[1]?.trim() ?? null

/** 装上登录页并点一次「登 录」。 */
async function submitLogin({ enterpriseCode, respond }) {
  const doc = makeDom('worker-h5-root')
  const f = makeFetch(respond)
  const api = createApi({ storage: makeStorage(), fetchImpl: f })
  const app = createApp({ doc, api, location: { href: 'https://app.migaozn.com/w/', replace() {} }, storage: makeStorage() })
  app.dispatch({ type: 'notice', notice: null }) // 绑一次事件（装配层在 draw() 里 bind）
  doc.setValue('wh5-worker-no', 'w001')
  doc.setValue('wh5-pin', '1234')
  if (enterpriseCode !== undefined) doc.setValue('wh5-enterprise-code', enterpriseCode)
  await doc.click('#wh5-login')
  return { doc, app, calls: f.calls, error: errorText(doc.html), state: app.state }
}

// ══════════════════════════════════════════════════════════════════════════════
// ① 归一（issue #6738 要求 1）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ① 归一纯函数：大写 ⇒ 小写，去首尾空白，`-`/`_` 原样保留（**不重定义格式**）', () => {
  assert.equal(normalizeEnterpriseCode('UITEST01'), 'uitest01', '大写是最常见的手误（用户照屏抄）')
  assert.equal(normalizeEnterpriseCode('  UITest01  '), 'uitest01', '首尾空白一并去掉')
  assert.equal(normalizeEnterpriseCode('UI-Test_01'), 'ui-test_01', '连字符与下划线原样保留（存量 tenant_7478359537 形态）')
  assert.equal(normalizeEnterpriseCode('migao'), 'migao', '本来就合规的串逐字不变')
})

test('🔴 ① 归一纯函数：空 / null / undefined / 非字符串 ⇒ 空串（不抛错、不猜）', () => {
  for (const v of ['', '   ', null, undefined]) {
    assert.equal(normalizeEnterpriseCode(v), '', `${JSON.stringify(v)} ⇒ 空串`)
  }
})

test('🔴 ① 装配层真接线：输入框里是大写 ⇒ **请求体里是小写**（撤掉归一 ⇒ 本条必红）', async () => {
  const { calls } = await submitLogin({ enterpriseCode: '  UITEST01  ', respond: () => ({ status: 401, body: RESP_401_AUTH_FAILED }) })
  const login = calls.find((c) => c.url === '/api/worker/login')
  assert.ok(login, '前置：必须真的发了登录请求')
  assert.equal(login.body.enterpriseCode, 'uitest01', `提交体必须已归一小写（实测 ${JSON.stringify(login.body.enterpriseCode)}）`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 形状校验失败的屏面文案（issue #6738 要求 2）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ② 422（逐字段 details）⇒ 屏上印**服务端给的可行动理由**，不印内部口径「参数校验失败」', async () => {
  const { error } = await submitLogin({ enterpriseCode: 'uitest01', respond: () => ({ status: 422, body: RESP_422_PIN_BLANK }) })
  assert.ok(error, '前置：失败必须在屏上显式可见（不许静默）')
  assert.ok(!error.includes(INTERNAL_WORDING), `屏上不得出现内部口径「${INTERNAL_WORDING}」：${error}`)
  assert.ok(error.includes('PIN 不能为空'), `必须把服务端已给的**逐字段**理由印出来（工人才知道改哪一格）：${error}`)
})

test('🔴 ② 422（服务端已给可行动 message）⇒ 原样保留它，且不得被内部口径盖掉', async () => {
  const { error } = await submitLogin({ enterpriseCode: '', respond: () => ({ status: 422, body: RESP_422_TENANT_MISSING }) })
  assert.ok(!error.includes(INTERNAL_WORDING), `屏上不得出现内部口径：${error}`)
  assert.ok(error.includes('企业编码'), `服务端那条本来就说得清（要填企业编码）⇒ 必须原样带给工人：${error}`)
})

test('🔴 ② 有逐字段 details ⇒ 顶层那句内部措辞**无论写成什么都上不了屏**（不是只治一句话）', async () => {
  // 判据钉的是**不变量**（有 details ⇒ 不看顶层 message），不是某一句中文：
  // 换一句内部措辞（请求参数不合法）照样必须被 details 顶掉。
  const { error } = await submitLogin({
    enterpriseCode: 'uitest01',
    respond: () => ({
      status: 422,
      body: { success: false, error: { code: 'VALIDATION_ERROR', message: '请求参数不合法', details: [{ field: 'workerNo', message: '工号不能为空' }] } },
    }),
  })
  assert.ok(!/请求参数不合法/.test(error), `顶层的内部措辞不上屏：${error}`)
  assert.ok(error.includes('工号不能为空'), `屏上必须是 details 里的逐字段理由：${error}`)
})

test('🔴 ② 无 details 且服务端也没写 message ⇒ 兜底话指到该核对的那几格（可行动）', async () => {
  const { error } = await submitLogin({
    enterpriseCode: 'uitest01',
    respond: () => ({ status: 422, body: { success: false, error: { code: 'VALIDATION_ERROR' } } }),
  })
  assert.ok(!error.includes(INTERNAL_WORDING), `屏上不得出现内部口径：${error}`)
  assert.ok(/企业编码/.test(error) && /工号/.test(error) && /PIN/.test(error), `兜底话要指到该核对的那三格：${error}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 不泄露：反枚举口径一字不动（issue #6738 边界）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ③ 401 反枚举文案原样上屏（企业编码不存在 / 工号不存在 / PIN 错 ⇒ 同一句）', async () => {
  const { error } = await submitLogin({ enterpriseCode: 'nosuchtenant123', respond: () => ({ status: 401, body: RESP_401_AUTH_FAILED }) })
  assert.equal(error, '工号或 PIN 不正确', '反枚举口径一字不动（本包不得改写它、也不得为它补"是哪个错了"的提示）')
})

test('🔴 ③ 401 文案里不得出现任何"哪一项错了"的分辨信息', async () => {
  const { error } = await submitLogin({ enterpriseCode: 'uitest01', respond: () => ({ status: 401, body: RESP_401_AUTH_FAILED }) })
  for (const leak of ['企业编码', '工号不存在', '该企业', '不存在']) {
    assert.ok(!error.includes(leak), `401 不得泄露哪一项错（含「${leak}」）：${error}`)
  }
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 类级：挂到**既有**那把尺子 + 台账只许缩短（issue #6738 要求 3）
// ══════════════════════════════════════════════════════════════════════════════

const SCANNER = join(ROOT, 'frontend', 'admin-web', 'scripts', 'user-copy-scan.mjs')
/** 剥注释：讲沿革的注释不算屏面文案。 */
const stripComments = (code) => code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*(\/\/|\*|\/\*).*$/gm, '')

test('🔴 ④ 既有扫描器**声明**了 worker-h5 扫描根（挂上去了，不是口头说挂了）', () => {
  const src = readFileSync(SCANNER, 'utf8')
  assert.match(src, /worker-h5/, '既有尺子（user-copy-scan.mjs）必须把 worker-h5 纳入扫描面')
  assert.match(src, /WORKER_H5/, '要有一个具名的 worker-h5 面描述（判据可具名到它）')
})

test('🔴 ④ worker-h5 面的豁免台账必须是 **0**（只许缩短；未登记即红）', () => {
  const src = readFileSync(SCANNER, 'utf8')
  const ledger = src.match(/export const WORKER_H5_EXEMPT = \[([\s\S]*?)\]/)?.[1] ?? null
  assert.ok(ledger !== null, 'worker-h5 面必须有自己的豁免台账（显式为空数组 = 0 条）')
  assert.equal(ledger.trim(), '', 'worker-h5 面当前必须**零豁免**（实测 0 命中；加一条就是放宽）')
})

test('🔴 ④ worker-h5 源码不得把内部口径当**兜底文案**写死（前端不复制服务端的开发术语）', () => {
  for (const rel of ['api.mjs', 'app.mjs', 'render.mjs', 'scan-input.mjs']) {
    const code = stripComments(readFileSync(join(SRC_DIR, rel), 'utf8'))
    assert.ok(!code.includes(INTERNAL_WORDING), `${rel} 不得出现内部口径「${INTERNAL_WORDING}」（它不是给人看的文案）`)
  }
})
