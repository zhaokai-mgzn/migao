/**
 * 工人认证服务（issue #4733）：工号 + PIN 登录 / 当前工人 / 快速切换 / 登出。
 *
 * <p>与商家认证（`utils/auth.ts` 的 `employeeLogin`）**彻底分离**：那条链路走账号密码 + JWT，
 * 这条走工号 + PIN + 工人 session。工人**不得**获得商家权限 —— 登录成功后拿到的 session
 * 只对 `/api/worker/**` 有效。</p>
 *
 * <p>🔴 本模块**不**在本地拼 `worker_id`：身份的权威在服务端（`worker_sessions`），
 * 前端只负责把 session id 存下来并在请求头里回传。</p>
 */

import { get, post } from '../utils/request'
import { API_BASE_URL, DEFAULT_TENANT_ID } from '../utils/constants'
import {
  clearWorkerSession,
  setCachedWorker,
  setWorkerSessionId,
  workerSessionHeaders,
  type CurrentWorker,
} from '../utils/workerSession'

/** 工人接口的响应信封（与 productionService 同形：兼容 {message} 与 {error:{message}}）。 */
export interface WorkerResponse<T> {
  success: boolean
  data?: T
  message?: string
  error?: { code?: string; message?: string }
  offline?: boolean
}

/** 登录/切换返回的会话载荷。 */
export interface WorkerSessionPayload {
  session_id: string
  worker_id: string
  worker_no?: string | null
  worker_name?: string | null
  idle_minutes?: number
  idle_expires_at?: string | null
}

function toResponse<T>(res: WorkerResponse<T> | undefined, fallback: string): WorkerResponse<T> {
  return {
    success: !!res?.success && !!res?.data,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
  }
}

function fail<T>(error: any, fallback: string): WorkerResponse<T> {
  return {
    success: false,
    message: error?.data?.message || error?.message || fallback,
    offline: !error?.statusCode,
  }
}

/**
 * 工号 + PIN 登录 ⇒ 存 session 并缓存当前工人。
 *
 * <p>登录成功**只**写 `worker_session_id` 与展示缓存 —— 商家 `auth_token` 一字不动
 * （同一台 PAD 上商家开着后台、工人报工，两者互不覆盖）。</p>
 */
export async function workerLogin(
  workerNo: string,
  pin: string,
  deviceLabel?: string,
  tenantId: number = DEFAULT_TENANT_ID,
): Promise<WorkerResponse<WorkerSessionPayload>> {
  try {
    const res = await post<WorkerResponse<WorkerSessionPayload>>(
      '/api/worker/login',
      { workerNo, pin, deviceLabel, tenantId },
      { baseURL: API_BASE_URL, skipAuth: true },
    )
    const normalized = toResponse(res, '登录失败，请重试')
    if (normalized.success && normalized.data) {
      persistSession(normalized.data)
    }
    return normalized
  } catch (error: any) {
    return fail(error, '登录失败，请重试')
  }
}

/**
 * 快速切换工人（共用 PAD，设计 W2）：服务端结束旧 session（`switched`）+ 建新 session。
 *
 * <p>🔴 旧 session **立即失效** ⇒ 切换后用旧 id 报工必 401（不把活记到上一个人头上）。
 * 本函数**不碰**扫码上下文（调用方保留当前屏的 `detail` 即可「一步切完继续报」）。</p>
 */
export async function switchWorker(
  workerNo: string,
  pin: string,
  deviceLabel?: string,
  tenantId: number = DEFAULT_TENANT_ID,
): Promise<WorkerResponse<WorkerSessionPayload>> {
  try {
    const res = await post<WorkerResponse<WorkerSessionPayload>>(
      '/api/worker/session/switch',
      { workerNo, pin, deviceLabel, tenantId },
      { baseURL: API_BASE_URL, headers: workerSessionHeaders(), skipAuth: true },
    )
    const normalized = toResponse(res, '切换失败，请重试')
    if (normalized.success && normalized.data) {
      persistSession(normalized.data)
    }
    return normalized
  } catch (error: any) {
    return fail(error, '切换失败，请重试')
  }
}

/**
 * 拉取「当前工人」—— 报工页页头「当前工人：张三」的数据来源。
 *
 * <p>数据来自**服务端 session**（不是前端 state）：页头显示的正是「这笔活会记到谁头上」，
 * 前端自己拼一个名字就等于把工资凭证交给了客户端。</p>
 */
export async function fetchCurrentWorker(): Promise<WorkerResponse<CurrentWorker>> {
  try {
    const res = await get<WorkerResponse<CurrentWorker>>('/api/worker/production/current-worker', {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
    })
    const normalized = toResponse(res, '未登录工人身份')
    if (normalized.success && normalized.data) {
      setCachedWorker(normalized.data)
    }
    return normalized
  } catch (error: any) {
    return fail(error, '未登录工人身份')
  }
}

/** 主动登出（幂等；服务端留 `end_reason=logout` 痕）。 */
export async function workerLogout(): Promise<void> {
  try {
    await post<WorkerResponse<void>>('/api/worker/session/logout', {}, {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
      skipAuth: true,
    })
  } catch {
    // 登出失败也要清本地：否则工人以为退了、下一个人扫码直接记到上一个人头上
  } finally {
    clearWorkerSession()
  }
}

/** 落 session + 展示缓存。 */
function persistSession(payload: WorkerSessionPayload): void {
  setWorkerSessionId(payload.session_id)
  setCachedWorker({
    session_id: payload.session_id,
    worker_id: payload.worker_id,
    worker_no: payload.worker_no ?? null,
    worker_name: payload.worker_name ?? null,
    idle_minutes: payload.idle_minutes,
    idle_expires_at: payload.idle_expires_at ?? null,
  })
}
