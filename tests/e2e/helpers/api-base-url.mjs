/**
 * fixture 录制脚本的 API 基址解析（issue #8391）。
 *
 * 唯一真值 = 环境变量 `BASE_URL`。缺失 / 非法 ⇒ **抛错**（fail-closed），
 * 绝不静默回落到 Playwright 的本机默认地址。
 *
 * 病史（issue #8391，run 41358293178 逐字）：月度 fixture 重录 job 的 env 是
 * `BASE_URL=https://api.migaozn.com`，而登录走 `auth.helper.ts` 的
 * `NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8080'`（录制 job 从不设前者）
 * ⇒ 录到第三行就 `ECONNREFUSED 127.0.0.1:8080 → POST /api/auth/sms/login`，
 * 同一形态 2026-09 起连红三次。
 *
 * 为什么单独一个无依赖 `.mjs`：录制入口 `record-fixtures.ts` 依赖 `@playwright/test`，
 * 而判据 job 不装 `tests/node_modules` ⇒ 解析必须能被 `tests/unit_ci_workflows/`
 * 的判据用**真 node** 跑一次（行为面，不是静态字符串匹配）。
 */

export const BASE_URL_ENV = 'BASE_URL'

/**
 * @param {Record<string, string | undefined>} [env]
 * @returns {string} 归一化（去掉末尾斜杠）的 API 基址
 */
export function resolveRecordingBaseUrl(env = process.env) {
  const raw = typeof env[BASE_URL_ENV] === 'string' ? env[BASE_URL_ENV].trim() : ''
  if (!raw) {
    throw new Error(
      `${BASE_URL_ENV} 未设置：fixture 录制必须显式给出 API 基址` +
        `（例：${BASE_URL_ENV}=https://api.migaozn.com）。` +
        '本脚本不再静默回落到本机默认地址 —— 那样会把「配置缺失」伪装成一次网络拒绝（issue #8391）。',
    )
  }
  let parsed
  try {
    parsed = new URL(raw)
  } catch {
    throw new Error(`${BASE_URL_ENV} 不是合法 URL：${JSON.stringify(raw)}`)
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`${BASE_URL_ENV} 只支持 http/https：${JSON.stringify(raw)}`)
  }
  return raw.replace(/\/+$/, '')
}
