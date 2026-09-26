// case_ids: BM-006
/**
 * 工人端弱网降级测试（issue #4206，真值源 `docs/curtain-production-rules.md` §5
 * 「【默】弱网降级：扫码页缓存待做清单，离线报工补传」）。
 *
 * ## 病灶（修复前实测）
 * `loadOrder` 直连网络、**不落 storage**；报工失败只弹全局 toast ⇒ 断网时列表空白、
 * 报工请求**必然丢单**（工人以为报了，服务端一条没有）。
 *
 * ## issue #5647（G10）之后：补传绑在**唯一写入口** `scan/complete` 上
 * 队列项多两个字段 —— `token`（本部位任务码 = 报工凭证，`scan/complete` 靠它定位
 * 「哪一套、哪个部位」）与 `sendQty`（在线时传了数量才补传数量：A 模式一屏【开工】
 * **不传数量**，由服务端取「剩余应做」，补传必须逐字同形）。
 * 幂等语义**一格不放宽**：凭证与幂等键一起落盘、补传复用同一个键。
 *
 * ## 本文件锁四条（每条都有红证）
 * ① 断网 ⇒ `loadOrder` 命中本机缓存仍能出待做清单，并**显式标注离线**（不得静默把缓存
 *    当服务端真值展示）；
 * ② 报工**传输层**失败（无 HTTP 状态码）⇒ 进本机队列，且队列项持久化**该次报工的幂等键 +
 *    报工凭证**；
 * ③ 恢复网络 ⇒ 自动补传，**复用同一幂等键 + 同一凭证**重发（仍走 `scan/complete`，
 *    不存在第二条补传路径）；成功后出队；
 * ④ 业务拒绝（有 HTTP 状态码，如数量超上限 422 / 非本部位 404）**不入队**（该键在服务端已被
 *    `ClientRequestIdService.discard` 释放，重发会重复执行，且业务错误重试无意义）。
 *
 * ## 红证（每条判据的失败形态）
 * - 删掉页面里的 `getCachedOrderOperations` 兜底 ⇒ ①红（断网后列表为空）。
 * - 删掉 `enqueuePendingReport` 调用 ⇒ ②红（队列空 = 丢单）。
 * - 补传时用 `newReportRequestId()` 重新生成键（而不是复用队列项里的键）⇒ ③红
 *   （同一次报工被服务端记两遍，实测口径见 issue #4206 判据 2）。
 * - 补传丢掉队列项里的 `token`（改用 orderId/operationId 走 URL 定工序的老路）⇒ ③红
 *   （凭证一变 = 服务端按「哪一套哪个部位」重新定位，防呆④⑤ 与一次事务全丢）。
 * - 把「传输层失败」判据写成「只要 success=false 就入队」⇒ ④红（业务拒绝也入队，
 *   恢复网络后被反复重发）。
 *
 * mock：Taro（**真内存 storage**，否则队列/缓存读写无意义）+ productionService（网络层）
 * + authStore（当前员工 = 报工人）。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  // 真内存 storage：本文件的判据全部落在「本机持久化」上，`jest.fn()` 空实现会让
  // 缓存/队列读写全变 no-op ⇒ 断言失去判别性（既可能假绿也可能假红）。
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      scanCode: jest.fn(),
      showToast: jest.fn(),
      navigateTo: jest.fn(),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      getCurrentInstance: jest.fn(() => ({ router: { params: {} } })),
      onNetworkStatusChange: jest.fn(),
      getNetworkType: jest.fn(),
      request: jest.fn(),
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/productionService', () => ({
  ...jest.requireActual('../src/services/productionService'),
  getOrderOperations: jest.fn(),
  // 扫码主闭环（切片 ②）：本文件测逐道报工与补传链路 ⇒ 解析面默认返回 undefined
  scanResolve: jest.fn(),
  completeByScan: jest.fn(),
  getOrderPiecework: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    user: { id: 'u1', nickname: '张师傅', avatar: null, tenantId: 1, role: 'operator' },
  })),
}))

import Taro from '@tarojs/taro'
import ProductionPage from '../src/pages/production/index/index'
import {
  completeByScan,
  getOrderOperations,
  getOrderPiecework,
} from '../src/services/productionService'
import type { OrderOperations, ReportPayload } from '../src/services/productionService'
import {
  cacheOrderOperations,
  enqueuePendingReport,
  flushPendingReports,
  getCachedOrderOperations,
  listPendingReports,
  listWorkLogs,
} from '../src/utils/productionOffline'
import { setupNetworkListener } from '../src/utils/errorHandler'

const ORDER_ID = 'CSO260915-02615'
/** 布帘这一行的部位任务码（一部位一码，issue #4946）——收口后报工的唯一凭证。 */
const PART_TOKEN = 'part-token-bu-1'

function makeDetail(): OrderOperations {
  return {
    order_id: ORDER_ID,
    qr_token: 'qr-token-1',
    positions: [
      {
        position_name: '布帘',
        order_item_id: 'item-A',
        part_token: PART_TOKEN,
        operations: [
          {
            id: 'op1', seq: 1, operation: '精裁', group: '裁剪', unit: '米',
            qty: 11, unit_price: 3.5, is_must_finish: true,
            is_start_marker: true, status: 'done', done_qty: 11,
          },
          {
            id: 'op2', seq: 2, operation: '韩褶', group: '车位', unit: '米',
            qty: 11, unit_price: 5, is_must_finish: true,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
    ],
    progress: { total: 2, done: 1, percent: 50 },
  }
}

// 身份**不在请求体里**（issue #4733）：服务端从工人 session 解身份
const PAYLOAD: ReportPayload = {
  qty: 11,
  qualified_qty: 11,
  work_type: 'normal',
}

function makePending(requestId: string, overrides: Record<string, any> = {}) {
  return {
    requestId,
    token: PART_TOKEN,
    orderId: ORDER_ID,
    operationId: 'op2',
    operationName: '韩褶',
    unit: '米',
    payload: PAYLOAD,
    // 逐道报工 = 工人在界面上确认过数量 ⇒ 补传要把数量一起发
    sendQty: true,
    createdAt: 1700000000000,
    ...overrides,
  }
}

const mockGet = getOrderOperations as jest.Mock
const mockComplete = completeByScan as jest.Mock
const mockPiecework = getOrderPiecework as jest.Mock

describe('ProductionPage 弱网降级（issue #4206 / 补传收口 #5647）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockPiecework.mockResolvedValue({ success: false, message: '网络异常' })
    mockComplete.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false, worker_name: '张师傅' },
    })
  })

  it('断网：loadOrder 命中本机缓存仍出待做清单，并显式标注离线', async () => {
    // 先在线拉一次（写入本机缓存），再模拟断网重查
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')
    expect(getCachedOrderOperations(ORDER_ID)?.order_id).toBe(ORDER_ID)

    mockGet.mockResolvedValueOnce({ success: false, offline: true, message: '网络异常，请检查网络连接' })
    fireEvent.click(screen.getByText('查单'))

    // 待做清单仍在（来自缓存），且**标注**为离线缓存而不是冒充服务端真值
    expect(await screen.findByText(/离线模式：展示本机缓存的待做清单/)).toBeTruthy()
    expect(screen.getByText('韩褶')).toBeTruthy()
    expect(screen.getByText('精裁')).toBeTruthy()
  })

  it('服务端明确答复失败（有状态码，如「加工单不存在」）⇒ 不拿旧缓存冒充真值', async () => {
    // 本机有该单的旧缓存，但服务端这次**答复了**（非传输层失败）⇒ 必须以服务端答复为准
    cacheOrderOperations(ORDER_ID, makeDetail())
    mockGet.mockResolvedValue({ success: false, message: '加工单不存在' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    expect(await screen.findByText('加工单不存在')).toBeTruthy()
    // 旧缓存不得被当成待做清单渲染出来（否则工人会对着已作废的清单报工）
    expect(screen.queryByText('韩褶')).toBeNull()
    expect(screen.queryByText(/离线模式/)).toBeNull()
  })

  it('报工传输失败 ⇒ 入本机队列，队列项持久化该次报工的幂等键与报工凭证', async () => {
    mockComplete.mockResolvedValue({ success: false, offline: true, message: '网络异常，请检查网络连接' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() => expect(listPendingReports()).toHaveLength(1))
    const call = mockComplete.mock.calls[0]
    // 唯一写入口的入参序：凭证 → 工序 → 幂等键 → 数量三键
    expect(call[0]).toBe(PART_TOKEN)
    expect(call[1]).toBe('op2')
    expect(call[2]).toMatch(/^report-/)
    expect(call[3]).toEqual(PAYLOAD)
    // 队列项必须留住**这一次**动作的键与凭证（补传复用它们的前提）
    const queued = listPendingReports()[0]
    expect(queued.requestId).toBe(call[2])
    expect(queued.token).toBe(PART_TOKEN)
    expect(await screen.findByText(/已存入本机待补传队列/)).toBeTruthy()
  })

  it('业务拒绝（有 HTTP 状态码）不入队（重发会重复执行且重试无意义）', async () => {
    mockComplete.mockResolvedValue({ success: false, message: '报工数量超上限：本次最多可报 11' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')
    fireEvent.click(screen.getAllByText('完成报工')[1])

    expect(await screen.findByText('报工数量超上限：本次最多可报 11')).toBeTruthy()
    expect(listPendingReports()).toHaveLength(0)
  })

  it('恢复补传 ⇒ 复用同一幂等键与同一凭证重发、成功出队、再补传不重复发送', async () => {
    enqueuePendingReport(makePending('report-fixed-key'))

    const first = await flushPendingReports()

    expect(mockComplete).toHaveBeenCalledTimes(1)
    // 判据核心：补传走**同一条写路径**、用的键**就是**入队时那一个（新生成键 = 服务端记两遍）
    expect(mockComplete).toHaveBeenCalledWith(PART_TOKEN, 'op2', 'report-fixed-key', PAYLOAD)
    expect(first.sent).toHaveLength(1)
    expect(first.remaining).toBe(0)
    expect(listPendingReports()).toHaveLength(0)

    const second = await flushPendingReports()
    expect(mockComplete).toHaveBeenCalledTimes(1)
    expect(second.sent).toHaveLength(0)
    // 补传落地的报工要进本机报工明细（工人能看到「已补上」）
    expect(listWorkLogs(ORDER_ID)).toHaveLength(1)
  })

  it('🔴 A 模式【开工】入队的条目**不**补发数量（在线路径本就不传数量，服务端取剩余应做）', async () => {
    enqueuePendingReport(makePending('report-no-qty', { sendQty: false }))

    await flushPendingReports()

    // 第 4 参缺席 ⇒ 服务端仍按「剩余应做」算；补发一个客户端算的数会在别人已推进时被超上限拒
    const call = mockComplete.mock.calls[0]
    expect(call[0]).toBe(PART_TOKEN)
    expect(call[1]).toBe('op2')
    expect(call[2]).toBe('report-no-qty')
    expect(call[3]).toBeUndefined()
  })

  it('🔴 旧版本入队的条目没有报工凭证 ⇒ 显式出队并回报原因（不静默丢单、也不发注定被拒的请求）', async () => {
    enqueuePendingReport(makePending('report-legacy-no-token', { token: '' }))

    const result = await flushPendingReports()

    expect(mockComplete).not.toHaveBeenCalled()
    expect(result.rejected).toHaveLength(1)
    expect(result.rejected[0].message).toMatch(/扫码凭证/)
    expect(listPendingReports()).toHaveLength(0)
  })

  it('补传时仍断网 ⇒ 队列原样保留（丢单与重复计件都不允许）', async () => {
    enqueuePendingReport(makePending('report-still-offline'))
    mockComplete.mockResolvedValue({ success: false, offline: true, message: '网络异常，请检查网络连接' })

    const result = await flushPendingReports()

    expect(result.remaining).toBe(1)
    expect(listPendingReports()[0].requestId).toBe('report-still-offline')
  })

  it('补传被服务端拒绝 ⇒ 出队并把原因回报给调用方（不静默丢单）', async () => {
    enqueuePendingReport(makePending('report-rejected'))
    mockComplete.mockResolvedValue({ success: false, message: '前道工序「精裁」尚未完成' })

    const result = await flushPendingReports()

    expect(result.rejected).toHaveLength(1)
    expect(result.rejected[0].message).toBe('前道工序「精裁」尚未完成')
    expect(result.rejected[0].operationName).toBe('韩褶')
    expect(listPendingReports()).toHaveLength(0)
  })

  it('网络恢复 ⇒ 监听器自动补传（工人无需再点一次）', async () => {
    enqueuePendingReport(makePending('report-on-reconnect'))
    setupNetworkListener()
    const onNetworkStatusChange = (Taro.onNetworkStatusChange as jest.Mock).mock.calls[0][0]

    onNetworkStatusChange({ isConnected: true, networkType: 'wifi' })

    await waitFor(() => expect(mockComplete).toHaveBeenCalledWith(
      PART_TOKEN, 'op2', 'report-on-reconnect', PAYLOAD,
    ))
    await waitFor(() => expect(listPendingReports()).toHaveLength(0))
  })

  /**
   * issue #4206 判据 4 要求的那一条：**「离线入队 → 恢复补传 → 只落一次报工」**。
   * 前两条用例分别盖住「入队」与「复用键」，本条把整条链路串起来（页面动作 + 网络监听器），
   * 并断言两次请求**逐字同键同凭证** —— 服务端按 `(tenant_id, key)` 去重，同键即「同一笔报工」。
   */
  it('端到端：离线报工入队 → 网络恢复自动补传 → 同键只落一次报工', async () => {
    // ① 离线报工（传输层失败）⇒ 入本机队列
    mockComplete.mockResolvedValueOnce({ success: false, offline: true, message: '网络异常，请检查网络连接' })
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() => expect(listPendingReports()).toHaveLength(1))
    const queued = listPendingReports()[0]

    // ② 网络恢复：监听器自动补传（服务端这次收下了）
    mockComplete.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false, worker_name: '张师傅' },
    })
    setupNetworkListener()
    const onNetworkStatusChange = (Taro.onNetworkStatusChange as jest.Mock).mock.calls[0][0]
    onNetworkStatusChange({ isConnected: true, networkType: 'wifi' })

    // ③ 只落一次：两次请求是**同一个幂等键 + 同一个凭证**（服务端只执行一次、第二次回放）
    await waitFor(() => expect(mockComplete).toHaveBeenCalledTimes(2))
    const [offlineAttempt, replay] = mockComplete.mock.calls
    expect(offlineAttempt[0]).toBe(queued.token)
    expect(offlineAttempt[2]).toBe(queued.requestId)
    expect(replay[0]).toBe(offlineAttempt[0])
    expect(replay[2]).toBe(offlineAttempt[2])
    expect(replay[3]).toEqual(offlineAttempt[3])
    expect(listPendingReports()).toHaveLength(0)
    // 补传成功才记明细：一条动作在明细里只能有一行
    expect(listWorkLogs(ORDER_ID)).toHaveLength(1)
  })
})
