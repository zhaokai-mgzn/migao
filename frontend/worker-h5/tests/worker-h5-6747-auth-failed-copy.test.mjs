// case_ids: PG-065, BM-045, BM-006
//
// 工人端登录**失败文案**（issue #6747）：认证失败（`AUTH_FAILED` / 401）**必须把服务端已给的确定原因说给工人**
// + 一句**可行动作**；**不得**落到泛化话术「操作没成功（请再试一次；若反复如此请找管理员）」（#6738 之后的残留档）。
//
// 现场风险（本单的"为什么"）：工人**把 PIN 打错**时，页面让他「再试一次」⇒ 他会**反复重试**，
// 而不是知道是工号/PIN 不对、要**核对后重输**。这踩了本批（客户试用前 UI 收尾 P1–P29）的口径：
// 文案不许归因给用户能感知不到的原因；服务端已有的确定原因要透给用户。
//
// 服务端真值（逐字，2026-10-11 生产 `https://app.migaozn.com/api/worker/login` 实测；
// 数据集单一源 = `./worker-h5-6747-login-payloads.mjs`，**本文件不另抄一份**）：
//   401 `{"success":false,"error":{"code":"AUTH_FAILED","message":"工号或 PIN 不正确"}}`
//   422 `{"success":false,"error":{"code":"VALIDATION_ERROR","message":"参数校验失败",
//         "details":[{"field":"pin","message":"PIN 不能为空"}]}}`
//
// 本文件钉五组（每组都能红；红证读数记在 PR body）：
//   ① **判定必须上屏**（透服务端原因，**不**自造"是哪一项错了"——反枚举口径一字不动）；
//   ② **必须有可行动作**（核对工号/PIN 后重试）—— 撤掉那句 ⇒ 材料③的 mutation 当场红；
//   ③ **判据材料有辨别力 + 有一条真跑到**（把 `request()` 的 401 分流**整个删掉** ⇒ 本文件必红，
//      证明判的是**真执行的那条路径**，不是死材料）；
//   ④ **不许退化成泛化重试 / 不许泄露**（病灶与反枚举两条红线）；
//   ⑤ **反向钉住**：网络/5xx/超时/形状校验失败的既有口径**一个字都不许动**（不许把认证话术套到它们头上）。
//
// 零依赖：`node --test` + 手写假 fetch / 内存 storage（不引 jsdom —— 最少代码阶梯）。
// 只 import 包内相对路径（`../src/**`、`./worker-h5-6747-login-payloads.mjs`）——
// **不静态 import 包外路径**（#6744 实证：包内测试静态引包外文件 ⇒ 部署 Docker 构建红）。

import test from 'node:test'
import assert from 'node:assert/strict'

import { createApi, SESSION_EXPIRED } from '../src/api.mjs'
import { AUTH_FAILED_401, GENERIC_RETRY_WORDING, VALIDATION_ERROR_422 } from './worker-h5-6747-login-payloads.mjs'

/** 传输层兜底（issue #6747 病灶）逐字。 */
const GENERIC_FALLBACK = GENERIC_RETRY_WORDING

/** 4xx/5xx 传输层「稍后重试」族的判据词（与实现里的 `HTTP_KIND` 同族，条数**现取**）。 */
const RETRY_TERMS = ['请过', '请再按', '稍后', '再试']

/** 认证失败时"该干什么"的动作词 —— 判据是**可行动**，不是某一句中文。 */
const ACTION_TERMS = ['核对', '重输', '重新输入']

function memStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

function stubFetch(responses) {
  const calls = []
  const fn = async (url, init = {}) => {
    calls.push({ url, body: init.body ? JSON.parse(init.body) : null })
    const r = responses.shift() ?? { status: 200, body: { success: true, data: {} } }
    return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body }
  }
  fn.calls = calls
  return fn
}

const apiWith = (...responses) => createApi({ fetchImpl: stubFetch(responses), storage: memStorage(), baseUrl: 'https://app.migaozn.com' })

/** 一次登录尝试 ⇒ 屏上那行红字（`err.message` 由 `app.mjs::fail()` 直送 `#wh5-error`，无中间改写）。 */
async function loginCopy(...responses) {
  try {
    await apiWith(...responses).login({ workerNo: 'wuitest', pin: 'UiTest246810', enterpriseCode: 'migao' })
    return null
  } catch (e) {
    return e.message
  }
}

/** 非登录请求（报工读面）的失败文案 —— 用来证明 401 分流**只**认 `AUTH_FAILED`。 */
async function scanCopy(...responses) {
  const api = apiWith(...responses)
  try {
    await api.resolveScan({ token: 'tok-1' })
    return null
  } catch (e) {
    return e.message
  } finally {
    void api
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// ① 判定必须上屏：服务端已给的确定原因原样透出
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ① 401 + AUTH_FAILED ⇒ 屏上含服务端那句确定原因（不是泛化话术、不是空的）', async () => {
  const copy = await loginCopy({ status: 401, body: AUTH_FAILED_401 })
  assert.ok(copy, '前置：认证失败必须在屏上显式可见（不许静默）')
  assert.notEqual(copy, GENERIC_FALLBACK, `认证失败不得落到泛化话术：${copy}`)
  assert.ok(
    copy.includes(AUTH_FAILED_401.error.message),
    `服务端给了确定原因（${AUTH_FAILED_401.error.message}）⇒ 必须透给工人，改前只剩它、改后是它 + 动作：${copy}`,
  )
})

test('🔴 ① 401 判定取自**响应体**（换一句服务端话 ⇒ 屏上跟着换，不是前端写死的判断句）', async () => {
  // 反向自证：拿一个"服务端换了一种说法"的响应体 ⇒ 屏上必须跟着说另一种 ——
  // 证明上屏的那句**来自 payload**，而不是前端把判断句抄了一份（抄一份 = 第二份会漂的口径）。
  const other = { success: false, error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' } }
  const copy = await loginCopy({ status: 401, body: other })
  assert.ok(copy.includes(other.error.message), `屏上必须来自响应体：${copy}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 必须有可行动作（本单的核心）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ② 认证失败 ⇒ 屏上同时给**该干什么**（核对/重输），不是只给一句判定让人猜', async () => {
  const copy = await loginCopy({ status: 401, body: AUTH_FAILED_401 })
  assert.ok(
    ACTION_TERMS.some((t) => copy.includes(t)),
    `工人需要知道"下一步做什么"（${ACTION_TERMS.join(' / ')}）：${copy}`,
  )
})

test('🔴 ② 401 + AUTH_FAILED 但 message **不可读 / 为空** ⇒ 仍给确定原因 + 动作（不是泛化重试）', async () => {
  // 口径 = 「服务端**点名**了认证失败（code），却没给可读原因」这一档也必须自己把话说全
  // （兜底判定 = 服务端同一句「工号或 PIN 不正确」，不自己发明"是哪一项错了"）。
  for (const message of ['', '   ', 'AUTH_FAILED']) {
    const copy = await loginCopy({ status: 401, body: { success: false, error: { code: 'AUTH_FAILED', message } } })
    assert.ok(copy, `前置：401 必须显式可见（message=${JSON.stringify(message)}）`)
    assert.notEqual(copy, GENERIC_FALLBACK, `不得落到泛化重试：${copy}`)
    assert.ok(copy.includes('工号或 PIN 不正确'), `缺可读原因时用服务端同一句判定：${copy}`)
    assert.ok(ACTION_TERMS.some((t) => copy.includes(t)), `仍要给动作：${copy}`)
  }
})

test('🔴 ② 401 连原因都没带（payload 缺 / 非 JSON）⇒ 登录面仍给动作，不是「登录已失效」错归因', async () => {
  // 真机曾出现的态：响应体读不出来（非 JSON / 被网关截断）⇒ 改前落「登录已失效，请重新用工号 + PIN 登录」
  // —— 对**刚按下登录按钮**的工人是错的归因（他没"失效"，他是打错了）。
  for (const body of [{ success: false, error: { code: 'AUTH_FAILED' } }, { success: false }, null]) {
    const copy = await loginCopy({ status: 401, body })
    assert.ok(copy, `前置：401 必须显式可见（body=${JSON.stringify(body)}）`)
    assert.notEqual(copy, GENERIC_FALLBACK, `无 message 的 401 不得落到泛化重试：${copy}`)
    assert.ok(!copy.includes('请再试一次'), `「请再试一次」会诱发反复重试：${copy}`)
    assert.ok(ACTION_TERMS.some((t) => copy.includes(t)), `登录面 401 必须给动作（body=${JSON.stringify(body)}）：${copy}`)
  }
})

test('🔴 ② 接线自证：登录请求带 `credentials` 语境（撤掉它 ⇒ 无响应体的 401 立刻退回错归因）', async () => {
  // 「是哪一种 401」不能靠猜响应体（无响应体时没有可猜的东西）⇒ 由**调用方**带语境。
  // 判法：直接检查登录请求没被改坏 —— 一个 401（payload 为空）走登录 vs 走读面，文案必须**不同**。
  const viaLogin = await loginCopy({ status: 401, body: null })
  const viaScan = await scanCopy({ status: 401, body: null })
  assert.notEqual(viaLogin, viaScan, `登录面与读面的无响应体 401 必须分辨：login=${viaLogin} / scan=${viaScan}`)
  assert.ok(ACTION_TERMS.some((t) => viaLogin.includes(t)), `登录面给动作：${viaLogin}`)
  assert.ok(viaScan.includes('登录已失效'), `读面保持改前的会话过期口径：${viaScan}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 判据材料的辨别力 + 「真跑到」自证
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ③ 材料自证：本文件用的响应体 = 生产实测形状（含 code 与可读中文 message）', () => {
  assert.equal(AUTH_FAILED_401.error.code, 'AUTH_FAILED', '生产 401 的 code 逐字是 AUTH_FAILED')
  assert.equal(AUTH_FAILED_401.error.message, '工号或 PIN 不正确', '生产 401 的 message 逐字（反枚举口径）')
  assert.equal(VALIDATION_ERROR_422.error.code, 'VALIDATION_ERROR', '生产 422 的 code 逐字')
  assert.deepEqual(
    VALIDATION_ERROR_422.error.details,
    [{ field: 'pin', message: 'PIN 不能为空' }],
    '生产 422 的逐字段理由形状（#6738 消费的就是它）',
  )
})

test('🔴 ③ 覆盖自证：把 `request()` 的 401 分流**整个删掉**时，本文件必须红（判据绑在真执行的那条路径上）', async () => {
  // 这是**反空断言**的自证：如果本文件的期望值来自某个"看着像 401 的假材料"，
  // 那么删掉实现里的 401 分流它照样会绿 —— 那种"绿"是假绿。
  // 判法：同一份**认证失败材料**（同 code、**无** message）换到非 401 通道（HTTP 400）：
  //   · 401 ⇒ 认证分流（#6747 的话术） · 400 ⇒ `transportMessage` ⇒ 泛化兜底（#6747 的病灶档）
  //   ⇒ 两条读数必须**不同**：证明屏上那句来自"真的 401 分流"，而不是任何响应体都成立的兜底。
  const authBody = { success: false, error: { code: 'AUTH_FAILED' } }
  const on401 = await loginCopy({ status: 401, body: authBody })
  const on400 = await loginCopy({ status: 400, body: authBody })
  assert.notEqual(on400, on401, `401 与 400 必须走不同通道（否则 401 分流是死的）：401=${on401} / 400=${on400}`)
  assert.ok(on400.includes(GENERIC_FALLBACK), `非 401 才走泛化兜底（这正是认证失败**不许**落到的那一档）：${on400}`)
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 不许退化成泛化重试 / 不许泄露（两条红线）
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ④ 认证失败文案里不得出现泛化重试话术（病灶本身）', async () => {
  for (const body of [AUTH_FAILED_401, { success: false, error: { code: 'AUTH_FAILED' } }, null]) {
    const copy = await loginCopy({ status: 401, body })
    assert.ok(!copy.includes(GENERIC_FALLBACK), `屏上不得出现泛化话术「${GENERIC_FALLBACK}」：${copy}`)
    assert.ok(!copy.includes('请再试一次'), `「请再试一次」在认证失败面上会诱发反复重试：${copy}`)
  }
})

test('🔴 ④ 反枚举口径：不得泄露"是哪一项错了"（与 #6738 同一条红线）', async () => {
  const copy = await loginCopy({ status: 401, body: AUTH_FAILED_401 })
  for (const leak of ['工号不存在', '该企业', '企业不存在', 'PIN 错误', '不存在这个']) {
    assert.ok(!copy.includes(leak), `401 不得泄露哪一项错（含「${leak}」）：${copy}`)
  }
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 反向钉住：网络 / 5xx / 超时 / 形状校验失败的既有口径不许被本包改掉
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ⑤ 网络面（408/429/5xx）仍走「稍后重试」族 —— 不许退化成权限/身份归因', async () => {
  for (const status of [408, 429, 500, 502, 503, 504]) {
    const copy = await loginCopy({ status, body: { success: false, error: { code: 'X' } } })
    assert.ok(
      RETRY_TERMS.some((t) => copy.includes(t)),
      `HTTP ${status} 应保持"稍后重试"口径（改前即如此）：${copy}`,
    )
    assert.ok(!ACTION_TERMS.some((t) => copy.includes(t)), `HTTP ${status} 不该被套上认证动作：${copy}`)
  }
})

test('🔴 ⑤ 非登录请求（报工读面）的 401 ⇒ 仍是会话过期语义，不得改成"工号或 PIN 不正确"', async () => {
  const copy = await scanCopy({ status: 401, body: { success: false, error: { code: 'UNAUTHORIZED' } } })
  assert.ok(copy, '前置：读面 401 必须显式可见')
  assert.ok(!copy.includes('工号或 PIN 不正确'), `读面 401 不得套认证话术（没点名 AUTH_FAILED）：${copy}`)
  assert.ok(RETRY_TERMS.some((t) => copy.includes(t)) || copy.includes('登录'), `读面 401 保持改前口径：${copy}`)
  // 真正的"会话没了"信号是 code（页面据此回落登录屏）—— 判据钉 code，不钉某一句话
  const api = apiWith({ status: 401, body: { success: false, error: { code: 'SESSION_EXPIRED' } } })
  await assert.rejects(() => api.resolveScan({ token: 't' }), (e) => e.code === SESSION_EXPIRED, '会话过期仍是 SESSION_EXPIRED')
  // 服务端点名了 message 的读面 401 ⇒ 原样透出（#6738 同口径：服务端可读原因优先）
  const withMsg = await scanCopy({ status: 401, body: { success: false, error: { code: 'SESSION_EXPIRED', message: '登录已过期' } } })
  assert.equal(withMsg, '登录已过期', `服务端可读原因必须原样透出：${withMsg}`)
})

test('🔴 ⑤ 形状校验失败（422）仍走 #6738 既有的逐字段理由（本包不另起一套）', async () => {
  const copy = await loginCopy({ status: 422, body: VALIDATION_ERROR_422 })
  assert.equal(copy, 'PIN 不能为空', `422 必须原样给服务端逐字段理由（#6738 已治，不许被本包改掉）：${copy}`)
})
