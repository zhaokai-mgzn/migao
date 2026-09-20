// case_ids: BM-004, BM-005, BM-006
/**
 * 工人登录态（issue #4733）前端契约测试。
 *
 * ## 本文件锁的四条（每条都能红）
 * ① **报工请求体不再带身份**：`worker_id`/`worker_name` 已从契约移除（旧实现逐字
 *    `worker_id: user?.id` ⇒ 工人扫码端用的是**商家账号 id** ⇒ 计件记错人）。
 *    红证：把 `payload.worker_id` 加回去 ⇒ 逐字断言必红。
 * ② **身份随 `X-Worker-Session-Id` 走**：报工请求头必须带工人 session；无 session ⇒ 不带
 *    （由服务端 401 显式拒绝，**不在前端补一个默认工人**）。
 * ③ **登录成功后本地只存工人会话**，不动商家 `auth_token`（两条链路分离）。
 * ④ **登出/切换清本地**：否则下一个人扫码直接记到上一个人头上。
 */
import Taro from '@tarojs/taro'
import {
  CLIENT_REQUEST_ID_HEADER,
  reportOperation,
} from '../src/services/productionService'
import { workerLogin, workerLogout, switchWorker } from '../src/services/workerService'
import {
  WORKER_SESSION_HEADER,
  clearWorkerSession,
  getWorkerSessionId,
  hasWorkerSession,
} from '../src/utils/workerSession'
import { STORAGE_KEYS } from '../src/utils/constants'

const ORDER_ID = 'CSO260920-00001'

/** 身份**不在请求体里**（issue #4733）。 */
const PAYLOAD = { qty: 11, qualified_qty: 11, work_type: 'normal' as const }

function lastRequest(): any {
  const calls = (Taro.request as jest.Mock).mock.calls
  expect(calls.length).toBeGreaterThan(0)
  return calls[calls.length - 1][0]
}

function ok(data: any = { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false }) {
  return { statusCode: 200, data: { success: true, data } }
}

describe('工人登录态（issue #4733）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
  })

  // ============================================================ ① 请求体不带身份

  it('报工请求体**不含** worker_id/worker_name（身份由服务端从 session 解）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())

    await reportOperation(ORDER_ID, 'op2', PAYLOAD, 'report-key-1')

    const request = lastRequest()
    expect(request.data).toEqual({ qty: 11, qualified_qty: 11, work_type: 'normal' })
    expect(request.data).not.toHaveProperty('worker_id')
    expect(request.data).not.toHaveProperty('worker_name')
  })

  it('报工走**工人路径** /api/worker/**（工人身份到不了 /api/admin/**）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())

    await reportOperation(ORDER_ID, 'op2', PAYLOAD, 'report-key-1')

    const url = String(lastRequest().url)
    expect(url).toContain('/api/worker/production/')
    expect(url).not.toContain('/api/admin/')
  })

  // ============================================================ ② 身份随请求头走

  it('已登录工人 ⇒ 请求头带 X-Worker-Session-Id（幂等键同时保留）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'sess-abc')

    await reportOperation(ORDER_ID, 'op2', PAYLOAD, 'report-key-1')

    const header = lastRequest().header
    expect(header[WORKER_SESSION_HEADER]).toBe('sess-abc')
    expect(header[CLIENT_REQUEST_ID_HEADER]).toBe('report-key-1')
  })

  it('未登录工人 ⇒ **不带**该头（由服务端 401 显式拒绝；前端不补默认工人）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())

    await reportOperation(ORDER_ID, 'op2', PAYLOAD, 'report-key-1')

    expect(lastRequest().header[WORKER_SESSION_HEADER]).toBeUndefined()
  })

  // ============================================================ ③ 登录只存工人会话

  it('工号 + PIN 登录 ⇒ 存 session 与当前工人；**不动**商家 auth_token', async () => {
    Taro.setStorageSync(STORAGE_KEYS.TOKEN, 'merchant-jwt')
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 200,
      data: {
        success: true,
        data: {
          session_id: 'sess-1', worker_id: 'w-1', worker_no: 'W001',
          worker_name: '张三', idle_minutes: 15, idle_expires_at: '2026-09-20T10:00:00Z',
        },
      },
    })

    const res = await workerLogin('W001', '246810', 'PAD-车间-01')

    expect(res.success).toBe(true)
    expect(getWorkerSessionId()).toBe('sess-1')
    expect(hasWorkerSession()).toBe(true)
    // 两条链路分离：商家 token 一字不动
    expect(Taro.getStorageSync(STORAGE_KEYS.TOKEN)).toBe('merchant-jwt')
    // 登录请求**不带** Authorization（工人不是商家账号）
    const loginRequest = lastRequest()
    expect(loginRequest.header.Authorization).toBeUndefined()
    expect(loginRequest.data).toEqual({
      workerNo: 'W001', pin: '246810', deviceLabel: 'PAD-车间-01', tenantId: 1,
    })
  })

  it('登录失败（401）⇒ 不落任何工人会话', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 401,
      data: { success: false, error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' } },
    })

    const res = await workerLogin('W001', '000000')

    expect(res.success).toBe(false)
    expect(getWorkerSessionId()).toBeNull()
  })

  // ============================================================ ④ 切换 / 登出清本地

  it('快速切换工人 ⇒ 旧 session 随请求头发出（服务端据此结束旧会话）+ 覆盖为新 session', async () => {
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'sess-old')
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 200,
      data: {
        success: true,
        data: { session_id: 'sess-new', worker_id: 'w-2', worker_no: 'W002', worker_name: '李四' },
      },
    })

    const res = await switchWorker('W002', '135790')

    expect(res.success).toBe(true)
    expect(lastRequest().header[WORKER_SESSION_HEADER]).toBe('sess-old')
    expect(getWorkerSessionId()).toBe('sess-new')
  })

  it('登出 ⇒ 本地工人会话清空（否则下一个人扫码记到上一个人头上）', async () => {
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'sess-1')
    ;(Taro.request as jest.Mock).mockResolvedValue({ statusCode: 200, data: { success: true } })

    await workerLogout()

    expect(getWorkerSessionId()).toBeNull()
    expect(hasWorkerSession()).toBe(false)
  })

  it('登出接口失败 ⇒ **仍然**清本地（工人以为退了就必须真退）', async () => {
    Taro.setStorageSync(STORAGE_KEYS.WORKER_SESSION, 'sess-1')
    ;(Taro.request as jest.Mock).mockRejectedValue(Object.assign(new Error('boom'), { statusCode: 500 }))

    await workerLogout()

    expect(getWorkerSessionId()).toBeNull()
  })

  it('clearWorkerSession 是幂等的（无 session 时调用不抛）', () => {
    expect(() => clearWorkerSession()).not.toThrow()
    expect(getWorkerSessionId()).toBeNull()
  })
})
