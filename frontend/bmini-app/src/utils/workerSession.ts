/**
 * 工人登录态载体（issue #4733）—— **计件归属的唯一根**在客户端的落点。
 *
 * <p>与商家账号（`auth_token`）**彻底分离**：商家 token 是 JWT（`Authorization: Bearer`），
 * 工人身份是不可猜的 session id（`X-Worker-Session-Id`）。两者可同时存在（同一台 PAD 上
 * 商家开着后台、工人报工），互不覆盖。</p>
 *
 * <p>⚠️ 本模块**只**负责「存/取/清」与请求头拼装 —— 它**不是**身份真值源：
 * 真值在服务端 `worker_sessions`（页头显示、报工归属都由服务端解）。前端存的值只影响
 * 「拿哪个 session 去请求」，改它只会让自己 401，改不了「这笔活记到谁头上」。</p>
 */

import Taro from '@tarojs/taro'
import { STORAGE_KEYS } from './constants'

/** 工人 session 请求头（与服务端 `WorkerSessionService.SESSION_HEADER` 逐字同名）。 */
export const WORKER_SESSION_HEADER = 'X-Worker-Session-Id'

/** 当前工人（服务端返回的快照；`worker_id` 由服务端解，前端不得自造）。 */
export interface CurrentWorker {
  session_id: string
  worker_id: string
  worker_no?: string | null
  worker_name?: string | null
  device_label?: string | null
  idle_expires_at?: string | null
  idle_minutes?: number
}

/** 读取工人 session id（无 ⇒ null）。 */
export function getWorkerSessionId(): string | null {
  try {
    return Taro.getStorageSync(STORAGE_KEYS.WORKER_SESSION) || null
  } catch {
    return null
  }
}

/** 写入工人 session id。 */
export function setWorkerSessionId(sessionId: string): void {
  try {
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, sessionId)
  } catch {}
}

/** 清除工人登录态（登出 / 401 / 闲置超时）。 */
export function clearWorkerSession(): void {
  try {
    Taro.removeStorageSync(STORAGE_KEYS.WORKER_SESSION)
    Taro.removeStorageSync(STORAGE_KEYS.WORKER)
  } catch {}
}

/** 读取缓存的当前工人（仅用于首屏渲染；真值仍以服务端 `current-worker` 为准）。 */
export function getCachedWorker(): CurrentWorker | null {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEYS.WORKER)
    return raw ? (raw as CurrentWorker) : null
  } catch {
    return null
  }
}

/** 缓存当前工人（登录 / 切换 / 刷新时调用）。 */
export function setCachedWorker(worker: CurrentWorker): void {
  try {
    Taro.setStorageSync(STORAGE_KEYS.WORKER, worker)
  } catch {}
}

/**
 * 工人请求头（无 session ⇒ 空对象：调用方仍会发请求，由服务端 401 显式拒绝 ——
 * **不**在前端静默补一个默认工人）。
 */
export function workerSessionHeaders(): Record<string, string> {
  const sessionId = getWorkerSessionId()
  return sessionId ? { [WORKER_SESSION_HEADER]: sessionId } : {}
}

/** 是否已登录工人身份（**本地判据**，只用于决定跳不跳登录页）。 */
export function hasWorkerSession(): boolean {
  return !!getWorkerSessionId()
}
