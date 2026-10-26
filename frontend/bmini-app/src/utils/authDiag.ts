/**
 * 登录态「启动探针」（issue #7825）。
 *
 * ## 为什么需要它
 *
 * 用户 2026-10-26 反馈「现在每次扫码后都要重新登录」。线上**已有** 30 天续期链路（issue #7249），
 * 但「为什么还是掉了」在**手机上不可观测** —— 端侧既不上报、也不留痕，只能靠猜
 * （可能是浏览器清数据、可能是 refresh cookie 没带上、可能是某次 401 把 token 清了）。
 *
 * 本模块只做一件事：把**续期/兑换/被清**的结果记进本地环形缓冲（最多 20 条），
 * 并在登录页 `?diag=1` 时原样上屏 —— 下一次「又掉线」时能拿到原因，而不是再一次猜。
 *
 * ## 口径
 *
 * · **只记方式与结果**，不记 token / 票据 / 密码（detail 里也不许塞凭据）；
 * · 写失败静默（存储被禁 / 隐私模式）—— 探针本身**绝不能**成为新的故障点；
 * · 环形缓冲**只增不删**（超出 20 条丢最旧），`clearAuthDiag()` 仅供测试与「重置」使用。
 */

import Taro from '@tarojs/taro'

/** 存储键（带前缀，避免与业务键撞车） */
export const AUTH_DIAG_STORAGE_KEY = 'auth_diag'

/** 环形缓冲上限 */
export const AUTH_DIAG_MAX = 20

/** 记录种类 —— 新增种类必须同时在本注释里写清「它回答什么问题」 */
export type AuthDiagKind =
  /** 续期成功（拿到新 access token） */
  | 'refresh_ok'
  /** 续期被拒（401：cookie 不存在 / 已过期 / 已轮换吊销） */
  | 'refresh_401'
  /** 续期遇到服务端不可判定（503 fail-closed） */
  | 'refresh_unavailable'
  /** 续期响应 2xx 但没有 accessToken（契约异常） */
  | 'refresh_no_token'
  /** 续期请求本身失败（断网 / 超时 / DNS） */
  | 'refresh_network'
  /** 启动时本机没有 token（首次使用 / 存储被清） */
  | 'boot_no_token'
  /** 启动时 token 已过期且续期失败 ⇒ 被登出 */
  | 'boot_expired_refresh_failed'
  /** 某次业务 401 把商家会话清掉了（记录是哪个端点） */
  | 'session_cleared_401'
  /** 扫码票据兑换成功 */
  | 'qr_login_ok'
  /** 扫码票据兑换失败（过期 / 已用 / 网络） */
  | 'qr_login_failed'

export interface AuthDiagEntry {
  /** 毫秒时间戳（本机时区显示） */
  at: number
  kind: AuthDiagKind
  detail: string
}

/** 读环形缓冲（坏数据 / 读失败一律回空表，绝不抛）。 */
export function readAuthDiag(): AuthDiagEntry[] {
  try {
    const raw = Taro.getStorageSync(AUTH_DIAG_STORAGE_KEY)
    if (!raw) return []
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((entry): entry is AuthDiagEntry =>
        !!entry && typeof entry.at === 'number' && typeof entry.kind === 'string')
      .map(entry => ({ at: entry.at, kind: entry.kind, detail: String(entry.detail || '') }))
  } catch {
    return []
  }
}

/** 记一条（写失败静默；同时打一行 console.info，便于连真机调试时在控制台看到）。 */
export function recordAuthDiag(kind: AuthDiagKind, detail = ''): void {
  try {
    const next = [...readAuthDiag(), { at: Date.now(), kind, detail: String(detail).slice(0, 120) }]
    Taro.setStorageSync(AUTH_DIAG_STORAGE_KEY, JSON.stringify(next.slice(-AUTH_DIAG_MAX)))
  } catch {}
  try {
    // eslint-disable-next-line no-console
    console.info('[auth-diag]', kind, detail)
  } catch {}
}

/** 清空（测试 / 「我的」页重置用）。 */
export function clearAuthDiag(): void {
  try {
    Taro.removeStorageSync(AUTH_DIAG_STORAGE_KEY)
  } catch {}
}

/** 时间戳 → `MM-DD HH:mm:ss`（本机时区；探针上屏用，不参与任何判定）。 */
export function formatAuthDiagTime(at: number): string {
  const d = new Date(at)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
