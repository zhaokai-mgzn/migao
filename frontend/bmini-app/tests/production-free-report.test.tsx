// case_ids: BM-036
/**
 * 工人**无码自由报工**（issue #6598）—— bmini 报工页的端侧判据。
 *
 * ## 用户裁定（2026-10-09，逐字）
 * 「当前工人报工只能按固定顺序报工，这个设计是不对的，**允许工人自由报工**」；
 * 追问后当场选定开放范围 = **整张加工单内任选任意工序（不扫码也能自由报）**。
 * 看到该现象的链路 = 扫码报工（扫部位任务码后系统只给「下一道」，要给「不是这道？改」才换得了）。
 *
 * ## 本文件锁什么
 * ① **无 `part_token` 的本位也有写入口**：`part_token` 缺失不再等于「不能报工」——
 *    改走既有工人端点 `POST /api/worker/production/orders/{orderId}/operations/{operationId}/report`
 *    （工序由工人**显式**选，服务端校验归属 / 未软删 / 同租户）；
 * ② **清单来自服务端**：页面不自聚合、不推算「下一道」（`positions[].operations[]` 就是服务端下发的清单）；
 * ③ **跨部位可报**：任一部位的工序都能直接报（不再被「必须落在本次扫码码内」挡住）；
 * ④ **失败展示服务端 message**，且**不清空列表**（工人可继续报别的）；
 * ⑤ **无码补传不重复计件**：离线入队记住「这个条目从来不需要码」，补传走**同一条**无码端点 +
 *    **复用同一幂等键**；
 * ⑥ **扫码定位不回归**：有码的部位仍走 `completeByScan`（扫码保留为快捷定位，不是唯一入口）。
 *
 * ## 边界（照实登记，不粉饰）
 * - 本文件判**端侧行为**；服务端的「任意工序 + 显式确定 + 同一份记账」判据在
 *   `backend/admin-api/src/test/java/com/migao/admin/service/ProductionWorkerFreeReportTest.java`。
 * - 商家侧凭证模型**不放宽**：`frontend/worker-h5/**`（`/w/` 工号 + PIN 面）本包不改
 *   （见 PR body 的未做项登记）。
 *
 * ## 红证（每条判据的失败形态，实测读数见 PR body）
 * - 把无码分支删掉（只留 `part_token` 那条）⇒ ①③红（无码部位没有按钮）。
 * - 让无码分支改发 `completeByScan('')` ⇒ ①红（凭证为空，服务端 422）。
 * - 无码补传时重新生成幂等键 ⇒ ⑤红（同一次报工被服务端当成两次首执 ⇒ 重复计件）。
 * - 有码部位改走无码端点 ⇒ ⑥红。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  // 真内存 storage：工人登录态与离线补传队列都落在本机持久化上 —— 空实现（jest.fn()）
  // 会让「队列里到底存了什么」「补传复用了哪个键」两条断言失去判别性。
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
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/productionService', () => ({
  ...jest.requireActual('../src/services/productionService'),
  // 在飞锁用真身（issue #4116 §5-1）：页面调 `reportInFlightLock.tryAcquire()`，
  // 一并 mock 掉会拿到 undefined ⇒ 一次点击就抛错。
  getOrderOperations: jest.fn(),
  getWorkerOrderOperations: jest.fn(),
  getOrderPiecework: jest.fn(),
  scanResolve: jest.fn(),
  completeByScan: jest.fn(),
  reportOperationFree: jest.fn(),
  shipOrder: jest.fn(),
  shipWorkerOrder: jest.fn(),
}))

import Taro from '@tarojs/taro'
import ProductionPage from '../src/pages/production/index/index'
import {
  completeByScan,
  getOrderPiecework,
  getWorkerOrderOperations,
  reportOperationFree,
} from '../src/services/productionService'
import type { OrderOperations } from '../src/services/productionService'
import { flushPendingReports, listPendingReports } from '../src/utils/productionOffline'
import { setWorkerSessionId } from '../src/utils/workerSession'

const ORDER_ID = 'CSO261009-00001'
/** 有码部位（扫码快捷定位那条路仍在）。 */
const PART_TOKEN = 'part-token-bu-1'

/**
 * 读面夹具（**全部来自服务端**）：布帘**有**任务码；纱帘**没有**（存量单 / 已撤销 ⇒ 键在、值 null）。
 *
 * 布帘 1 道待做 + 纱帘 2 道待做 —— 覆盖「同部位」与「跨部位」两种自由报工。
 */
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
            qty: 11, unit_price: 3.5, is_must_finish: false,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
      {
        position_name: '纱帘',
        order_item_id: 'item-B',
        // 🔴 无任务码 —— issue #6598 起**不再**等于「不能报工」
        part_token: null,
        operations: [
          {
            id: 'op2', seq: 2, operation: '定型', group: '后道', unit: '米',
            qty: 11, unit_price: 4, is_must_finish: false,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
          {
            id: 'op3', seq: 3, operation: '打卷', group: '后道', unit: '米',
            qty: 11, unit_price: 2, is_must_finish: false,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
    ],
    progress: { total: 3, done: 0, percent: 0 },
    work_logs: [],
  }
}

const mockWorkerGet = getWorkerOrderOperations as jest.Mock
const mockComplete = completeByScan as jest.Mock
const mockFreeReport = reportOperationFree as jest.Mock

/** 报工成功回执（`worker_name` 由**服务端**回执 —— 身份不在请求体里，issue #4733）。 */
function okReport(operationId = 'op2') {
  return {
    success: true,
    data: {
      operation_id: operationId, done_qty: 11, status: 'done',
      order_completed: false, worker_name: '张师傅',
    },
  }
}

/** 打开页面并把本单工序拉到屏上（工人身份的车间设备）。 */
async function openPage() {
  render(<ProductionPage />)
  fireEvent.click(screen.getByText('扫一扫'))
  await screen.findByText('定型')
}

describe('bmini 报工页：无码自由报工（issue #6598）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    setWorkerSessionId('sess-worker-1')
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockWorkerGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockComplete.mockResolvedValue(okReport('op1'))
    mockFreeReport.mockResolvedValue(okReport())
    ;(getOrderPiecework as jest.Mock).mockResolvedValue({ success: false, message: '网络异常' })
  })

  it('🔴 无 part_token 的部位**仍然**有写入口（清单来自服务端，每道工序一个按钮）', async () => {
    await openPage()

    // 三道工序（布帘 1 + 纱帘 2）**全都有**「完成报工」——无码不再是「无写入口」。
    // 红证：把 `!position.part_token` 那条老分支（不渲染按钮）还原 ⇒ 这里只剩 1 个。
    expect(screen.getAllByText('完成报工')).toHaveLength(3)
    // 旧提示（「本部位暂无任务码，无法报工」）是 #5647 G10 的口径，已被本次用户裁定取代 ⇒ 必须消失。
    expect(screen.queryByText(/本部位暂无任务码/)).toBeNull()
  })

  it('🔴 跨部位自由报：点纱帘（无码）的工序 ⇒ 走无码端点，工序由工人**显式**给', async () => {
    await openPage()

    // [1] = 纱帘的第一道（定型，op2）—— 与布帘不同部位
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() =>
      expect(mockFreeReport).toHaveBeenCalledWith(
        ORDER_ID,
        'op2',
        // 第 3 参 = 本次动作的幂等键（重发复用同一个键 ⇒ 服务端不重复计件）
        expect.stringMatching(/^report-/),
        // 第 4 参 = 数量三键（冻结契约字段；身份**不在**里面，issue #4733）
        { qty: 11, qualified_qty: 11, work_type: 'normal' },
      ),
    )
    // 无码路径**不碰**扫码端点（凭证为空去撞 scan/complete = 必然被拒）
    expect(mockComplete).not.toHaveBeenCalled()
  })

  it('🔴 扫码定位不回归：有 part_token 的部位仍走 completeByScan', async () => {
    await openPage()

    // [0] = 布帘（有码）的那道
    fireEvent.click(screen.getAllByText('完成报工')[0])

    await waitFor(() =>
      expect(mockComplete).toHaveBeenCalledWith(
        PART_TOKEN, 'op1', expect.stringMatching(/^report-/),
        { qty: 11, qualified_qty: 11, work_type: 'normal' },
      ),
    )
    expect(mockFreeReport).not.toHaveBeenCalled()
  })

  it('失败只展示服务端 message，且列表不清空（工人可继续报别的工序）', async () => {
    mockFreeReport.mockResolvedValue({ success: false, message: '该工序已报满（本次未重复计件）' })

    await openPage()
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await screen.findByText('该工序已报满（本次未重复计件）')
    // 列表仍在 ⇒ 工人能接着报下一道（不清空是本页既有纪律）
    expect(screen.getAllByText('完成报工')).toHaveLength(3)
  })

  it('🔴 无码报工离线入队：记住「这条从来不需要码」+ 幂等键复用 ⇒ 补传不重复计件', async () => {
    mockFreeReport.mockResolvedValueOnce({
      success: false, offline: true, message: '网络异常，请检查网络连接',
    })

    await openPage()
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() => expect(listPendingReports()).toHaveLength(1))
    const queued = listPendingReports()[0]
    const key = mockFreeReport.mock.calls[0][2]
    // 🔴 无码条目**不得**被当成「旧版本缺凭证」出队丢弃 —— 它本来就不需要码。
    // 红证：把 `kind` / 端点判别去掉（退回「token 空 ⇒ 出队」）⇒ 下面的 await 拿不到 sent。
    expect(queued.requestId).toBe(key)
    expect(mockFreeReport).toHaveBeenLastCalledWith(
      ORDER_ID, 'op2', key, { qty: 11, qualified_qty: 11, work_type: 'normal' },
    )

    // 联网后补传：走**同一条**无码端点 + **同一个**幂等键（服务端据此去重）
    mockFreeReport.mockReset()
    mockFreeReport.mockResolvedValue(okReport())
    const result = await flushPendingReports()

    expect(result.sent).toHaveLength(1)
    expect(result.rejected).toHaveLength(0)
    expect(mockFreeReport).toHaveBeenCalledWith(
      ORDER_ID, 'op2', key, { qty: 11, qualified_qty: 11, work_type: 'normal' },
    )
    expect(listPendingReports()).toHaveLength(0)
  })
})
