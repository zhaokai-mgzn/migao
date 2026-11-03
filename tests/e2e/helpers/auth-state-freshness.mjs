/**
 * Playwright storageState（`tests/e2e/.auth/admin.json`）的**复用判定**（issue #6411）。
 *
 * 病史（issue #6411 逐字读数）：原判据只看文件 mtime 与 1 小时比
 * （`age < 3600_000` ⇒ 直接 `return`，不校验 token 是否还有效），而登录态的**真实有效期**
 * 由后端下发的 JWT `exp` 决定（实测约 30 分钟，同一份 `admin.json` 10:15:40 生成、
 * 10:23 绿、10:49 起全红且 mtime 未变）⇒ **复用窗口 > 有效窗口**：
 * 复用一个已失效的 token，所有 spec 连带红，且没有任何一句话指向「登录态过期」。
 *
 * 口径（三级，前一极能判就不用后一级）：
 *   ① token 是合法 JWT ⇒ **只认 `exp`**：`exp` 已过 / 距 `exp` 不足安全余量 ⇒ **重新登录**
 *      （不复用失效态）；余量充足 ⇒ 可复用。此时 mtime **不参与**判定。
 *   ② token 不是合法 JWT / 解不出 `exp`（`E2E_MOCK_AUTH=true` 的占位 token）⇒ 回落 **mtime**，
 *      且**必须出声**（`message` 里明写「按 mtime 兜底」）—— 静默兜底会把本缺陷重新藏起来。
 *   ③ 文件不存在 / mtime 不可用 ⇒ 不可复用。
 *
 * 为什么是**无依赖 `.mjs`**（与 `tests/e2e/helpers/api-base-url.mjs` 同一范式）：
 * 判定要能被 `tests/unit_ci_workflows/` 的判据用**真 node** 跑一次（行为面，不是静态字符串匹配），
 * 而那边不装 `tests/node_modules`。
 *
 * 边界（照实登记）：「`exp` 还没到 ≠ 后端一定接受这个 token」（token 可能被提前吊销 /
 * 服务端重启换密钥）。本模块只保证**不再复用一个自己已声明失效的 token**；
 * 无后端时 auth.setup 仍无法自愈（那属环境事实，见 issue #6411 的「剩下那一半在仓外」）。
 */

/** mtime 兜底的复用窗口（历史口径原样保留；只在解不出 `exp` 时生效）。 */
export const DEFAULT_MAX_AGE_MS = 60 * 60 * 1000

/** 距 `exp` 不足该余量即视为「即将过期」⇒ 重新登录（避免跑到一半在 spec 里过期）。 */
export const DEFAULT_SAFETY_MARGIN_MS = 5 * 60 * 1000

/** 毫秒 → 人话（用于 `message`，让判红可归因）。 */
function formatDuration(ms) {
  const abs = Math.abs(ms)
  if (abs >= 60_000) return `${Math.round((abs / 60_000) * 10) / 10} 分钟`
  return `${Math.round(abs / 1000)} 秒`
}

/**
 * 解出 JWT 的 `exp`（毫秒）。不是合法 JWT / 无 `exp` / 解析失败 ⇒ `null`。
 *
 * @param {unknown} token
 * @returns {number | null}
 */
export function decodeJwtExpMs(token) {
  if (typeof token !== 'string') return null
  const parts = token.trim().split('.')
  if (parts.length !== 3) return null
  let payload
  try {
    payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'))
  } catch {
    return null
  }
  const exp = payload && payload.exp
  if (typeof exp !== 'number' || !Number.isFinite(exp) || exp <= 0) return null
  return exp * 1000
}

/**
 * 从 storageState 里取出 access token：优先 `access_token` cookie（middleware 读它），
 * 退而取 zustand persist 的 `auth-storage.state.accessToken`（AuthGuard 读它）。
 *
 * @param {unknown} storageState
 * @returns {string | null}
 */
export function readAccessToken(storageState) {
  if (!storageState || typeof storageState !== 'object') return null
  const cookies = Array.isArray(storageState.cookies) ? storageState.cookies : []
  const cookie = cookies.find((c) => c && c.name === 'access_token')
  if (cookie && typeof cookie.value === 'string' && cookie.value) return cookie.value

  const origins = Array.isArray(storageState.origins) ? storageState.origins : []
  for (const origin of origins) {
    const items = origin && Array.isArray(origin.localStorage) ? origin.localStorage : []
    const entry = items.find((i) => i && i.name === 'auth-storage')
    if (!entry || typeof entry.value !== 'string') continue
    try {
      const parsed = JSON.parse(entry.value)
      const token = parsed && parsed.state && parsed.state.accessToken
      if (typeof token === 'string' && token) return token
    } catch {
      // 坏值当作「这个 origin 解不出」处理，继续找下一个
    }
  }
  return null
}

/**
 * 复用判定（纯函数：不读盘、不联网、不看环境变量）。
 *
 * @param {object} [options]
 * @param {unknown} [options.storageState] `admin.json` 解析后的对象
 * @param {number | null} [options.mtimeMs] `admin.json` 的 mtime（毫秒）
 * @param {number} [options.now] 当前时间（毫秒；判据可注入，便于确定性测试）
 * @param {number} [options.maxAgeMs] mtime 兜底窗口
 * @param {number} [options.safetyMarginMs] 距 `exp` 的安全余量
 * @returns {{reuse: boolean, source: 'jwt-exp' | 'mtime', reason: string, message: string, remainingMs?: number}}
 */
export function decideAuthStateReuse(options = {}) {
  const {
    storageState = null,
    mtimeMs = null,
    now = Date.now(),
    maxAgeMs = DEFAULT_MAX_AGE_MS,
    safetyMarginMs = DEFAULT_SAFETY_MARGIN_MS,
  } = options

  const expMs = decodeJwtExpMs(readAccessToken(storageState))

  // ① 解不出 exp（占位 token / 非 JWT）⇒ mtime 兜底，且**出声**
  if (expMs === null) {
    const hasMtime = typeof mtimeMs === 'number' && Number.isFinite(mtimeMs)
    if (!hasMtime) {
      return {
        reuse: false,
        source: 'mtime',
        reason: 'no-mtime',
        message: 'admin.json 的 mtime 不可用 ⇒ 无法兜底 ⇒ 重新登录',
      }
    }
    const ageMs = now - mtimeMs
    const reuse = ageMs >= 0 && ageMs < maxAgeMs
    return {
      reuse,
      source: 'mtime',
      reason: reuse ? 'mtime-fallback-fresh' : 'mtime-fallback-stale',
      message:
        `token 解不出 exp（不是合法 JWT），**按 mtime 兜底**（未校验 token 有效期）：` +
        `文件年龄 ${formatDuration(ageMs)} / 窗口 ${formatDuration(maxAgeMs)} ⇒ ` +
        (reuse ? '可复用' : '重新登录'),
    }
  }

  // ② 有 exp ⇒ 只认 exp（mtime 不参与）
  const remainingMs = expMs - now
  if (remainingMs <= 0) {
    return {
      reuse: false,
      source: 'jwt-exp',
      reason: 'token-expired',
      message: `token 的 exp 已过 ${formatDuration(remainingMs)}（mtime 不作为复用依据）⇒ 重新登录`,
      remainingMs,
    }
  }
  if (remainingMs <= safetyMarginMs) {
    return {
      reuse: false,
      source: 'jwt-exp',
      reason: 'token-expiring',
      message:
        `token 距 exp 只剩 ${formatDuration(remainingMs)}（安全余量 ${formatDuration(safetyMarginMs)}；` +
        'mtime 不作为复用依据）⇒ 重新登录',
      remainingMs,
    }
  }
  return {
    reuse: true,
    source: 'jwt-exp',
    reason: 'token-fresh',
    message: `token 距 exp 还有 ${formatDuration(remainingMs)} ⇒ 可复用`,
    remainingMs,
  }
}
