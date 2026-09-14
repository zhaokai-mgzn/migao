// e2e/lib/login.js — C 端 e2e **共用登录前置步骤（单一事实源）**，多个工作包共用，禁止各写一份
/**
 * ## 为什么 e2e 不能走「真实微信登录」（环境限制，不是产品缺陷）
 *
 * 产品侧的登录链路是：`Taro.login()` 取 code → `POST /api/auth/mini/login {code, tenantId}`
 * （`frontend/mini-app/src/utils/auth.ts:18-34`）。但**在微信开发者工具模拟器里，该 code 被后端判
 * `WECHAT_API_ERROR: code 无效`**（appid/secret 与开发者工具登录账号不匹配，实测于 2026-09-14），
 * 因此 e2e 无法用真实微信登录建立会话。这是**测试环境限制**。
 *
 * ⇒ 本步骤用「与手工登录等价」的方式建立会话：调 admin-api 的短信登录（测试环境短信网关 bypass，
 *    13800138000 + 万能码 123456）拿 JWT，再把 C 端真正读取的几个 storage key 写进去。
 *
 * ## 严禁事项
 * - **严禁**为了让 e2e 通过而修改产品鉴权代码（`src/store/authStore.ts` / `src/utils/auth.ts` /
 *   admin-api 鉴权）—— 这是环境限制，绕道产品代码 = 把测试脚手架变成产品缺陷。
 * - 本文件只在**测试环境**使用；不允许出现在任何生产构建路径里。
 *
 * ## 写了哪些 key（与产品读取点一一对应）
 * | key | 产品读取点 | 值 |
 * |---|---|---|
 * | `auth_token` | `src/utils/auth.ts:63` `getToken()`（`checkAuth()` 用它判定已登录，`authStore.ts:137`） | JWT 字符串 |
 * | `auth_user` | `src/utils/auth.ts:74` `getUser()`（`app.tsx:20` → `initialize()` 用它恢复 `user`，导航名/副标题依赖 `botName`/`tenantName`） | `JSON.stringify(user)` |
 * | `tenant_id` | `src/utils/auth.ts:87` `getTenantId()` | number |
 * | `auth-store` | zustand `persist`（`authStore.ts:153` `name: 'auth-store'`）的快照，冷启动 `user` 兜底来源 | `{"state":{...},"version":0}` |
 *
 * ## ⚠️ 注入形状 = **逐字镜像生产存下的形状**（不补字段、不改名）
 *
 * 2026-09-14 发现的**产品侧契约不一致**（另一包修产品，本文件**只镜像不遮蔽**）：
 * - 生产写入路径：`src/utils/auth.ts:47` `setStorageSync(USER, JSON.stringify(user))`，
 *   而 `user` 直接来自接口响应 ⇒ **生产存下的 user 是 admin-api 的原始 camelCase 形状**
 *   （`backend/admin-api/.../dto/LoginResponse.java` 的 UserInfo：`id, nickname, avatar, role,
 *   identityType, roles, tenantId, tenantName, botName` —— **没有 `tenant_id`**）。
 * - 但 C 端类型声明 `User.tenant_id: number`（**必填**，`src/types/index.ts:11`）⇒ 运行时恒
 *   `undefined`，**类型在骗人**；而 `src/utils/imageUpload.ts:25` 会读 `getTenantId()`。
 * ⇒ 若 harness 在注入时**补一个 `tenant_id` 让断言过**，就会造出「**harness 形状 ≠ 生产形状**」：
 *   将来任何读 `user.tenant_id` 的代码会**e2e 绿、生产挂** —— 这正是我们要治的「证据层假绿」。
 *   **故本文件不做任何补字段/改名**，注入的就是响应原物；契约不一致由产品侧修复收口。
 *
 * 唯一例外是独立的 storage key `tenant_id`（不是 user 的字段）：生产在
 * `src/utils/auth.ts:48` 存的是**登录请求里的 tenantId**；短信登录没有该参数，
 * 故取本次会话的 `user.tenantId`（语义同为「会话所属租户」），并在此显式声明这一差异。
 *
 * 依赖：**只用 node 内置 + 传入的 mp**（不 require harness）—— 这样红证脚本可以脱离模拟器运行。
 */
const STORAGE = {
  TOKEN: 'auth_token',
  USER: 'auth_user',
  TENANT_ID: 'tenant_id',
  STORE: 'auth-store',
}

/** 登录态缺失/不可用时的显著标记（会被 run.js 打进报告，供验收报告引用） */
const LOGIN_MISSING = 'LOGIN_MISSING'

const CHAT_PAGE = '/pages/chat/index/index'

const DEFAULTS = {
  apiBase: process.env.E2E_LOGIN_API_BASE || 'https://app.migaozn.com',
  phone: process.env.E2E_LOGIN_PHONE || '13800138000',
  code: process.env.E2E_LOGIN_CODE || '123456',
}

/**
 * 镜像产品侧 `checkTokenValidity()`（`src/utils/auth.ts:118`）：
 * 非三段 JWT ⇒ 不可用；有 exp 且已过期 ⇒ 不可用；解析失败 ⇒ 视为可用（交由后端验证，与产品一致）。
 */
function isTokenUsable(token, nowSec = Math.floor(Date.now() / 1000)) {
  const raw = typeof token === 'string' ? token.trim() : ''
  if (!raw) return false
  const parts = raw.split('.')
  if (parts.length !== 3) return false
  try {
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(Buffer.from(b64, 'base64').toString('utf8'))
    if (!payload.exp) return true
    return payload.exp > nowSec
  } catch {
    return true
  }
}

/** 纯判据：登录态是否可用（供 run.js 失败关闭 + 红证脚本使用；**不允许恒真**） */
function resolveLoginState(token, nowSec = Math.floor(Date.now() / 1000)) {
  if (typeof token !== 'string' || !token.trim()) {
    return { ok: false, marker: LOGIN_MISSING, reason: 'storage 无 auth_token（未登录）' }
  }
  if (!isTokenUsable(token, nowSec)) {
    return { ok: false, marker: LOGIN_MISSING, reason: 'auth_token 已过期或不是合法 JWT（三段/exp 校验不过）' }
  }
  return { ok: true, marker: null, reason: '已登录' }
}

// ── storage 读写：优先 wx 方法直调（不依赖 wx 是否在 evaluate 作用域内），失败退回 evaluate ──

async function readStorage(mp, key) {
  try {
    return await mp.callWxMethod('getStorageSync', key)
  } catch (e) {
    return await mp.evaluate((k) => wx.getStorageSync(k), key)
  }
}

async function writeStorage(mp, key, value) {
  try {
    await mp.callWxMethod('setStorageSync', key, value)
  } catch (e) {
    await mp.evaluate((k, v) => wx.setStorageSync(k, v), key, value)
  }
}

/** 清空 storage（冷环境验证用：把「环境残留登录态」彻底去掉，见 README「冷环境复跑」） */
async function clearStorage(mp) {
  try {
    await mp.callWxMethod('clearStorageSync')
  } catch (e) {
    await mp.evaluate(() => wx.clearStorageSync())
  }
}

/**
 * 短信登录换 JWT（测试环境 SMS bypass）。`fetchImpl` 可注入，便于红证脚本脱离网络运行。
 */
async function smsLoginSession({
  apiBase = DEFAULTS.apiBase,
  phone = DEFAULTS.phone,
  code = DEFAULTS.code,
  fetchImpl = globalThis.fetch,
  timeoutMs = 20000,
} = {}) {
  if (typeof fetchImpl !== 'function') throw new Error('当前 node 无 fetch（需 node>=18）')
  const url = `${String(apiBase).replace(/\/+$/, '')}/api/auth/sms/login`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetchImpl(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, code }),
      signal: controller.signal,
    })
    const text = await res.text()
    if (!res.ok) throw new Error(`HTTP ${res.status}：${text.slice(0, 200)}`)
    const body = JSON.parse(text)
    if (!body || body.success !== true) {
      throw new Error(`业务失败：${(body && body.error && body.error.message) || text.slice(0, 200)}`)
    }
    const data = body.data || {}
    const token = data.accessToken || data.token
    const user = data.user
    if (!token || !user) throw new Error('登录响应缺少 accessToken/user')
    // **原物直存**（见文件头「注入形状 = 逐字镜像生产」）：不补字段、不改名，
    // 即使 C 端 User 类型声明了接口并不返回的 tenant_id，也不在这里「修好」它。
    return { token, user, tenantId: user.tenantId ?? null, url }
  } finally {
    clearTimeout(timer)
  }
}

/**
 * 确保本次 e2e 有可用登录态（**失败关闭**：返回 ok=false 时调用方必须让整轮失败，不许继续跑）。
 *
 * 流程：读 storage → 判据（纯函数）→ 不可用则短信登录注入 → reLaunch 让页面重新读 storage → 复核。
 * 返回 { ok, source:'storage'|'injected'|'none', token, user, tenantId, marker, reason }
 */
async function ensureLoggedIn(mp, opts = {}) {
  const {
    force = false,
    apiBase = DEFAULTS.apiBase,
    phone = DEFAULTS.phone,
    code = DEFAULTS.code,
    fetchImpl = globalThis.fetch,
  } = opts

  const existing = await readStorage(mp, STORAGE.TOKEN)
  const state = resolveLoginState(existing)
  if (state.ok && !force) {
    return { ok: true, source: 'storage', token: existing, marker: null, reason: state.reason }
  }

  let session
  try {
    session = await smsLoginSession({ apiBase, phone, code, fetchImpl })
  } catch (e) {
    return {
      ok: false,
      source: 'none',
      marker: LOGIN_MISSING,
      reason:
        `建立登录态失败（短信登录 ${apiBase}）：${e.message}\n` +
        '   ⇒ 无登录态时断言依赖的租户数据（botName/租户副标/订单脱敏）会缺失或降级，' +
        '那种「绿」属于环境残留假绿，故直接失败。',
    }
  }

  await writeStorage(mp, STORAGE.TOKEN, session.token)
  await writeStorage(mp, STORAGE.USER, JSON.stringify(session.user))
  if (session.tenantId !== null && session.tenantId !== undefined) {
    await writeStorage(mp, STORAGE.TENANT_ID, session.tenantId)
  }
  // zustand persist 快照（zustand ^5.0.15 的包裹形状 = {"state":…,"version":0}）：
  // 生产里 `login()` 的 `set({token,user,isLoggedIn})` 会由 persist 写出这一份（partialize 只留这三项，
  // authStore.ts:156-160）⇒ 这里同样**原物镜像**，user 用响应原样、不补字段。
  await writeStorage(
    mp,
    STORAGE.STORE,
    JSON.stringify({ state: { token: session.token, user: session.user, isLoggedIn: true }, version: 0 })
  )

  try {
    await mp.reLaunch(CHAT_PAGE)
  } catch (e) {
    // reLaunch 失败不致命：run.js 会在注入后重启模拟器会话（冷启动读取注入态）
    console.warn(`[login] reLaunch 失败（将由调用方重启会话）: ${e.message.slice(0, 120)}`)
  }

  const after = await readStorage(mp, STORAGE.TOKEN)
  const recheck = resolveLoginState(after)
  if (!recheck.ok) {
    return { ok: false, source: 'injected', marker: LOGIN_MISSING, reason: `注入后复核失败：${recheck.reason}`, user: session.user }
  }
  return {
    ok: true,
    source: 'injected',
    token: after,
    user: session.user,
    tenantId: session.tenantId,
    marker: null,
    reason: `已通过短信登录注入（${session.url}）`,
  }
}

module.exports = {
  STORAGE,
  LOGIN_MISSING,
  CHAT_PAGE,
  DEFAULTS,
  isTokenUsable,
  resolveLoginState,
  readStorage,
  writeStorage,
  clearStorage,
  smsLoginSession,
  ensureLoggedIn,
}
