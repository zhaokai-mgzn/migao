/**
 * 扫码即登录（issue #7825）—— 手机端把二维码票据换成**自己的**登录态。
 *
 * ## 为什么需要它
 *
 * 顶栏「手机端」二维码（issue #7198）原来只是一条**裸链接**（`<B端H5地址>`）：
 * 换一台没有登录态的浏览器 / App（微信 ↔ 相机 ↔ Safari）、或本机存储被清 / 会话过期后，
 * 扫码必然停在登录页，只能重新输「用户名@企业编码 + 密码」（用户 2026-10-26 的原话）。
 *
 * 现在 PC 侧（已登录）签发一张 **120 秒、单次有效** 的票据，二维码内容形如
 * `<B端H5地址>?qr=<票据>`；本模块在**启动时**（模块加载期，早于任何页面判断登录态）
 * 把它兑换成一份与密码登录**完全同形**的会话（access token + HttpOnly refresh cookie）。
 *
 * ## 三条纪律（都有判据，见 `tests/qr-login.test.ts`）
 *
 * 1. **兑换先于判登录**：`qrLoginReady` 是模块级 Promise，`authStore.checkAuth/initialize` 先 await 它
 *    —— 否则页面会先判「未登录」并跳登录页，兑换结果永远没人用（同 #7249 的时序坑）；
 * 2. **失败不毁既有会话**：兑换失败只提示、不 logout、不清 token（过期二维码不该把已登录的人踢出去）。
 *    因此这里**不用** `utils/request` 的 `post()`（它的 401 分支会清态+跳登录页）；
 * 3. **票据不留在地址栏**：兑换结束（成功或失败）都 `replaceState` 抹掉 `?qr=`，
 *    避免被复制、进历史、进 referer。
 */

import Taro from '@tarojs/taro'
import { API_BASE_URL, REQUEST_CONFIG } from './constants'
import { recordAuthDiag } from './authDiag'
import { persistSession } from './auth'
import type { ApiResponse, User } from '../types'

/** 二维码票据的查询参数名（与 admin-web 的 `?qr=` 同一份契约） */
export const QR_TICKET_PARAM = 'qr'

/** 兑换端点（后端 `POST /api/auth/qr/exchange`，公开 + 凭据是票据本身） */
export const QR_EXCHANGE_PATH = '/api/auth/qr/exchange'

/** 兑换失败的唯一提示（与后端 `AuthService.QR_TICKET_INVALID_MESSAGE` 逐字一致） */
export const QR_TICKET_EXPIRED_HINT = '二维码已过期，请重新扫码'

interface LocationLike {
  search?: string
  hash?: string
  href?: string
}

interface HistoryLike {
  replaceState: (data: unknown, title: string, url?: string) => void
}

function currentLocation(): LocationLike | null {
  return typeof window === 'undefined' ? null : (window.location as LocationLike)
}

function currentHistory(): HistoryLike | null {
  return typeof window === 'undefined' ? null : (window.history as HistoryLike)
}

function readParam(query: string, name: string): string {
  try {
    return (new URLSearchParams(query.replace(/^\?/, '')).get(name) || '').trim()
  } catch {
    return ''
  }
}

/**
 * 从地址里读票据：`/b/?qr=xxx`（直链）与 `/b/#/pages/…?qr=xxx`（hash 路由）两种形态都认。
 * 没有 ⇒ 空串（**不编默认值**）。
 */
export function readQrTicket(loc: LocationLike | null = currentLocation()): string {
  if (!loc) return ''
  const fromSearch = readParam(String(loc.search || ''), QR_TICKET_PARAM)
  if (fromSearch) return fromSearch
  const hash = String(loc.hash || '')
  const q = hash.indexOf('?')
  return q === -1 ? '' : readParam(hash.slice(q + 1), QR_TICKET_PARAM)
}

/**
 * 抹掉地址栏里的票据（search 与 hash 两处都抹）。成功失败都调用 —— 失败也不该留着一张废票。
 * 读不到 location / 抛错 ⇒ 静默（**绝不**因为抹参失败而中断登录）。
 */
export function stripQrTicket(
  loc: LocationLike | null = currentLocation(),
  history: HistoryLike | null = currentHistory(),
): void {
  if (!loc || !history || !loc.href) return
  try {
    const url = new URL(String(loc.href))
    let changed = false

    if (url.searchParams.has(QR_TICKET_PARAM)) {
      url.searchParams.delete(QR_TICKET_PARAM)
      changed = true
    }

    const hash = url.hash
    const q = hash.indexOf('?')
    if (q !== -1) {
      const params = new URLSearchParams(hash.slice(q + 1))
      if (params.has(QR_TICKET_PARAM)) {
        params.delete(QR_TICKET_PARAM)
        const rest = params.toString()
        url.hash = `${hash.slice(0, q)}${rest ? `?${rest}` : ''}`
        changed = true
      }
    }

    if (changed) history.replaceState(null, '', url.toString())
  } catch {}
}

/**
 * 用票据换会话。成功 ⇒ 落地 token / user / tenant（与密码登录**同一写点** `persistSession`）；
 * 失败 ⇒ 返回 `false`，**不动**任何既有会话。
 */
export async function exchangeQrTicket(ticket: string): Promise<boolean> {
  const value = ticket.trim()
  if (!value) return false

  try {
    const response = await Taro.request({
      url: `${API_BASE_URL}${QR_EXCHANGE_PATH}`,
      method: 'POST',
      data: { ticket: value },
      header: { 'Content-Type': 'application/json', 'X-Client-Type': 'wechat_mini' },
      timeout: REQUEST_CONFIG.TIMEOUT,
    })

    const statusCode = Number((response as { statusCode?: number })?.statusCode || 0)
    const payload = (response as { data?: ApiResponse<{ accessToken: string; user: User }> })?.data
    const accessToken = payload?.data?.accessToken
    const user = payload?.data?.user

    // token 与 user 必须成对出现：缺一个就不算登录成功（否则「登录了但没有身份」= 半成品状态）
    if (statusCode >= 200 && statusCode < 300 && accessToken && user) {
      persistSession(accessToken, user)
      recordAuthDiag('qr_login_ok', `user=${user.id ?? '-'}`)
      return true
    }

    recordAuthDiag('qr_login_failed', `status=${statusCode} ${payload?.error?.message || ''}`.trim())
    return false
  } catch (error: any) {
    recordAuthDiag('qr_login_failed', `network ${error?.message || ''}`.trim())
    return false
  }
}

/** 启动流程：有票据就兑换 + 抹参（无票据 ⇒ 立即返回 false，不发任何请求）。 */
async function consumeTicketFromUrl(): Promise<boolean> {
  const ticket = readQrTicket()
  if (!ticket) return false

  const ok = await exchangeQrTicket(ticket)
  stripQrTicket()
  if (!ok) {
    Taro.showToast({ title: QR_TICKET_EXPIRED_HINT, icon: 'none' })
  }
  return ok
}

/**
 * 启动门（模块加载即开始）：`authStore.checkAuth/initialize` 必须先 await 它。
 *
 * 放在模块级而不是 `useEffect` 里，是因为 React 的**子组件 effect 先于父组件 effect** ——
 * 页面在 `app.tsx` 的 effect 之前就会判登录态（#7249 的时序同族坑）。
 */
export const qrLoginReady: Promise<boolean> = consumeTicketFromUrl()
