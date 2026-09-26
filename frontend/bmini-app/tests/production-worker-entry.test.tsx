// case_ids: BM-006, PG-018
/**
 * bmini 报工页的**身份面收口**（issue #5647 的 G4 + G10）。
 *
 * ## 两处半成品（本文件各锁一条）
 * ① **G4 读面**：页面读的是 `/api/admin/production/orders/{id}/operations`（**商家会话**），
 *    而只登录了工号 + PIN 的车间设备没有商家会话 ⇒ 读面 401、页面全空。工人又被
 *    `SecurityConfig.ADMIN_API_REJECTED_ROLES` 拒在 `/api/admin/**` 之外 ⇒ **不可能**靠
 *    「给工人商家权限」解决。收口 = 有工人 session 时读 `GET /api/worker/production/orders/{id}/operations`
 *    （服务端**同一份**读面 `ProductionService#getOperations`，字段逐字同源）；
 *    无工人 session（纯商家设备）时保持商家路径**一字不变**（商家打不开 = 红线）。
 * ② **G10 写面**：页面同时存在 URL 定工序的 `.../operations/{id}/report` 与 `scan/complete`
 *    两条写路径 ⇒ 防呆④（非本部位码）/ 防呆⑤（工序必须确定）/ 一次事务 / `done_at`
 *    在 URL 定工序那条路上**全都不生效**。收口 = 写面只有一个入口 `scan/complete`，
 *    凭证 = 读面下发的**部位任务码** `part_token`（issue #4946 一部位一码，键恒在）；
 *    **没有码就不提供写入口** —— 回退到 URL 定工序 = 把防呆整条绕开。离线补传队列同绑这条路
 *    （凭证随队列项落盘、幂等键复用 ⇒ 服务端同键重放只记一次）。
 *
 * ## 红证（每条判据的失败形态，逐条都实测过）
 * - 把 `loadOrder` 的读面写死成 `getOrderOperations` ⇒ ①红（2026-09-26 实测：工人设备读面 401 的形态）。
 * - 把 `loadOrder` 的读面写死成 `getWorkerOrderOperations` ⇒ ②红（商家账号打不开）。
 * - 把 `handleReport` 改回 `reportOperation(orderId, operationId, …)` ⇒ ③红。
 * - 去掉 `part_token` 判空（无码也发请求）⇒ ④红。
 * - 补传不带凭证 / 重新生成幂等键 ⇒ ⑤红。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  // 真内存 storage：工人登录态（`worker_session_id`）与离线队列都落在本机持久化上，
  // 空实现会让「读面按身份分流」「补传复用幂等键」两条判据失去判别性。
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
  // 锁用真身（issue #4116 §5-1）：页面调 `reportInFlightLock.tryAcquire()`，
  // 一并 mock 掉会拿到 undefined ⇒ 点「完成报工」直接抛错。
  getOrderOperations: jest.fn(),
  getWorkerOrderOperations: jest.fn(),
  getOrderPiecework: jest.fn(),
  scanResolve: jest.fn(),
  completeByScan: jest.fn(),
  shipOrder: jest.fn(),
}))

import Taro from '@tarojs/taro'
import ProductionPage from '../src/pages/production/index/index'
import {
  completeByScan,
  getOrderOperations,
  getOrderPiecework,
  getWorkerOrderOperations,
} from '../src/services/productionService'
import type { OrderOperations } from '../src/services/productionService'
import { flushPendingReports, listPendingReports } from '../src/utils/productionOffline'
import { clearWorkerSession, setWorkerSessionId } from '../src/utils/workerSession'

const ORDER_ID = 'CSO260926-00001'
/** 布帘这一行的部位任务码（一部位一码，issue #4946） */
const PART_TOKEN = 'part-token-bu-1'

/** 读面夹具：布帘**有**任务码、纱帘**没有**（存量单 / 已撤销 ⇒ 键在、值 null）。 */
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
            is_start_marker: true, status: 'done', done_qty: 11,
          },
          {
            id: 'op2', seq: 2, operation: '韩褶', group: '车位', unit: '米',
            qty: 11, unit_price: 5, is_must_finish: true,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
      {
        position_name: '纱帘',
        order_item_id: 'item-B',
        part_token: null,
        operations: [
          {
            id: 'op3', seq: 3, operation: '定型', group: '后道', unit: '米',
            qty: 11, unit_price: 4, is_must_finish: false,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
    ],
    progress: { total: 3, done: 1, percent: 33 },
    work_logs: [],
  }
}

const mockGet = getOrderOperations as jest.Mock
const mockWorkerGet = getWorkerOrderOperations as jest.Mock
const mockComplete = completeByScan as jest.Mock

/** 报工成功回执（`worker_name` 由**服务端**回执 —— 身份不在请求体里，issue #4733）。 */
function okComplete(operationId = 'op2') {
  return {
    success: true,
    data: {
      operation_id: operationId, done_qty: 11, status: 'done',
      order_completed: false, worker_name: '张师傅',
    },
  }
}

/** 打开页面并把本单工序拉到屏上。 */
async function openPage() {
  render(<ProductionPage />)
  fireEvent.click(screen.getByText('扫一扫'))
  await screen.findByText('韩褶')
}

describe('bmini 报工页读面按身份分流（issue #5647 G4）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockWorkerGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockComplete.mockResolvedValue(okComplete())
    ;(getOrderPiecework as jest.Mock).mockResolvedValue({ success: false, message: '网络异常' })
  })

  it('🔴 有工人 session ⇒ 读面走 /api/worker/**（工人路径），商家读面一次都不调', async () => {
    setWorkerSessionId('sess-worker-1')

    await openPage()

    expect(mockWorkerGet).toHaveBeenCalledWith(ORDER_ID)
    // 判据核心：纯工号 + PIN 的车间设备**没有**商家会话 ⇒ 走商家读面必然 401、页面全空。
    // 红证：把 `loadOrder` 的读面写死成 `getOrderOperations` ⇒ 本断言收到 0 次调用（红）。
    expect(mockGet).not.toHaveBeenCalled()
    expect(screen.getByText('布帘')).toBeTruthy()
    expect(screen.getByText('纱帘')).toBeTruthy()
  })

  it('无工人 session（纯商家设备）⇒ 读面仍是商家路径（商家账号打不开 = 红线）', async () => {
    clearWorkerSession()

    await openPage()

    expect(mockGet).toHaveBeenCalledWith(ORDER_ID)
    // 红证：把读面写死成 `getWorkerOrderOperations` ⇒ 本断言收到 0 次调用（红）。
    expect(mockWorkerGet).not.toHaveBeenCalled()
    expect(screen.getByText('韩褶')).toBeTruthy()
  })
})

describe('bmini 报工写面唯一入口 = scan/complete（issue #5647 G10）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    clearWorkerSession()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockWorkerGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockComplete.mockResolvedValue(okComplete())
    ;(getOrderPiecework as jest.Mock).mockResolvedValue({ success: false, message: '网络异常' })
  })

  it('🔴 点「完成报工」⇒ 调 completeByScan（凭证 = 本部位 part_token，工序 + 数量随 body）', async () => {
    await openPage()

    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() =>
      expect(mockComplete).toHaveBeenCalledWith(
        PART_TOKEN,
        'op2',
        // 第 3 参 = 本次动作的幂等键（issue #4206）
        expect.stringMatching(/^report-/),
        // 第 4 参 = 数量三键（冻结契约字段；身份**不在**里面，issue #4733）
        { qty: 11, qualified_qty: 11, work_type: 'normal' },
      ),
    )
  })

  it('数量可改仍生效：输入 8 ⇒ 写面收到的 qty/qualified_qty 都是 8（issue #4206 判据 1 不退化）', async () => {
    await openPage()

    fireEvent.change(screen.getAllByPlaceholderText('完成数量')[1], { target: { value: '8' } })
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() =>
      expect(mockComplete).toHaveBeenCalledWith(
        PART_TOKEN, 'op2', expect.stringMatching(/^report-/),
        { qty: 8, qualified_qty: 8, work_type: 'normal' },
      ),
    )
  })

  it('🔴 部位没有任务码（part_token=null）⇒ 不给写入口：不加按钮 + 显式提示', async () => {
    await openPage()

    // 布帘（有码）2 道工序 ⇒ 2 个按钮；纱帘（无码）那道**不出现**按钮。
    // 红证：去掉 `part_token` 判空 ⇒ 这里变 3 个（无码也发一个注定无从校验的报工请求）。
    expect(screen.getAllByText('完成报工')).toHaveLength(2)
    expect(screen.getByText(/本部位暂无任务码/)).toBeTruthy()
  })

  it('🔴 离线补传同绑唯一写入口：凭证随队列项落盘 + 补传复用同一幂等键', async () => {
    mockComplete.mockResolvedValueOnce({ success: false, offline: true, message: '网络异常，请检查网络连接' })

    await openPage()
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() => expect(listPendingReports()).toHaveLength(1))
    const queued = listPendingReports()[0]
    const key = mockComplete.mock.calls[0][2]
    // 凭证与幂等键都必须随队列项落盘：补传要「同一个入口 + 同一个键」才只记一次
    expect(queued.token).toBe(PART_TOKEN)
    expect(queued.requestId).toBe(key)
    expect(queued.sendQty).toBe(true)

    mockComplete.mockResolvedValue(okComplete())
    const result = await flushPendingReports()

    expect(result.sent).toHaveLength(1)
    expect(mockComplete).toHaveBeenLastCalledWith(
      PART_TOKEN, 'op2', key, { qty: 11, qualified_qty: 11, work_type: 'normal' },
    )
    expect(listPendingReports()).toHaveLength(0)
  })
})
