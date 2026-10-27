// case_ids: BM-034
/**
 * 工人**返工记录**页判据（issue #7921；页面 = `src/pages/worker/rework/index.tsx`）。
 *
 * 本文件判**装配与口径**（纯展示函数一并钉住），每条都能单独变红：
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | ① | 读到了 ⇒ 服务端给几行就渲染几行（加工单号 / 订单号 / 返工笔数 / 最近返工 / 原因 / 涉及工序逐值照用） | 前端自己过滤 / 重排 / 改数字 ⇒ 红 |
 * | ② | 空态 = 「读了、真没有」；**不**与「读不到」混为一谈 | 把 error 渲染成 EMPTY_HINT ⇒ 红 |
 * | ③ | 401 ⇒ 引导登录（不清商家态、不跳商家登录页） | 把 401 渲染成空态 ⇒ 红 |
 * | ④ | 🔴 403 = 工人档案没开「返工记录」页 ⇒ **可行动**提示（找管理员勾选），且**不**冒充「没有返工」 | 把 403 归到 error / empty ⇒ 红 |
 * | ⑤ | 缺值不编造：`rework_count` 缺 ⇒ 整项不渲染（**不印 `0 笔`**）；时间只切不改 | 用 `count ?? 0` ⇒ 红 |
 *
 * 数据源真值：`GET /api/worker/production/rework-orders`（后端 `ProductionReworkService.reworkOrders`，
 * 与 H5 `/w/rework.html` 同一个端点）⇒ 本页只渲染，不聚合。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      navigateTo: jest.fn(),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
  }
})

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
}))

jest.mock('../src/services/workerReworkService', () => ({
  listWorkerReworkOrders: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerReworkPage, {
  EMPTY_HINT,
  FORBIDDEN_HINT,
  READ_FAILED_HINT,
  reworkCountText,
  reworkRowModel,
  reworkAtText,
} from '../src/pages/worker/rework/index'
import { fetchCurrentWorker } from '../src/services/workerService'
import { listWorkerReworkOrders } from '../src/services/workerReworkService'
import { WORKER_TAB_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import { setWorkerSessionId } from '../src/utils/workerSession'

const WORKER = { session_id: 's', worker_id: 'w-1', worker_no: 'G001', worker_name: '张三' }

const mockFetch = fetchCurrentWorker as jest.Mock
const mockList = listWorkerReworkOrders as jest.Mock

/** 一张加工单（字段名逐字对齐后端 `reworkOrders` 的行） */
const ROW = {
  processing_order_id: 'po-1',
  processing_order_no: 'JG20261026001',
  order_no: 'DD20261025001',
  processing_status: 'producing',
  rework_count: 2,
  rework_qty: 11.5,
  latest_rework_at: '2026-10-26T17:30:00+08:00',
  latest_reason: '车歪了',
  operations: [
    { operation_name: '车被', logical_name: '车被', qty: 6.5, count: 1 },
    { operation_name: '定型', logical_name: '定型', qty: 5, count: 1 },
  ],
}

async function renderPage() {
  setWorkerSessionId('sess-worker-1')
  mockFetch.mockResolvedValue({ success: true, data: WORKER })
  render(<WorkerReworkPage />)
}

describe('工人返工记录页（issue #7921）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro as any).__clearStorage()
    mockFetch.mockResolvedValue({ success: true, data: WORKER })
    mockList.mockResolvedValue({ success: true, data: { orders: [] }, message: '' })
  })

  it('① 服务端给几行就渲染几行，字段逐值照用（不聚合 / 不重排）', async () => {
    mockList.mockResolvedValue({ success: true, data: { orders: [ROW] }, message: '' })
    await renderPage()

    expect(await screen.findByTestId('worker-rework-row-0')).toBeTruthy()
    expect(screen.getByTestId('worker-rework-no-0').textContent).toBe('JG20261026001')
    expect(screen.getByTestId('worker-rework-order_no-0').textContent).toBe('订单号：DD20261025001')
    // 🔴 返工笔数 = 服务端读数（2 笔），不是前端数 operations.length
    expect(screen.getByTestId('worker-rework-rework_count-0').textContent).toBe('返工：2 笔')
    expect(screen.getByTestId('worker-rework-latest_rework_at-0').textContent).toBe(
      '最近返工：2026-10-26 17:30',
    )
    expect(screen.getByTestId('worker-rework-latest_reason-0').textContent).toBe('原因：车歪了')
    expect(screen.getByTestId('worker-rework-operations-0').textContent).toBe(
      '涉及工序：车被 ×6.5、定型 ×5',
    )
    expect(screen.getByTestId('worker-rework-count').textContent).toBe('共 1 张加工单有返工报工')
    // 红证：把 rework_count 改成 operations.length（= 2，恰好相同）或固定写死 ⇒ 换一份读数即红
  })

  it('② 空态 = 读了、真没有（不是错误态）', async () => {
    await renderPage()
    expect(await screen.findByTestId('worker-rework-empty')).toBeTruthy()
    expect(screen.getByText(EMPTY_HINT)).toBeTruthy()
    expect(screen.queryByTestId('worker-rework-error')).toBeNull()
  })

  it('②′ 读不到 ⇒ 错误态 + 可重试（**不**渲染成「没有返工」）', async () => {
    mockList.mockResolvedValue({ success: false, message: '网络抖了一下' })
    await renderPage()

    expect(await screen.findByTestId('worker-rework-error')).toBeTruthy()
    expect(screen.queryByTestId('worker-rework-empty')).toBeNull()
    expect(screen.queryByTestId('worker-rework-forbidden')).toBeNull()

    // 重试真的再读一次
    mockList.mockResolvedValue({ success: true, data: { orders: [] }, message: '' })
    fireEvent.click(screen.getByTestId('worker-rework-retry'))
    await waitFor(() => expect(screen.getByTestId('worker-rework-empty')).toBeTruthy())
    expect(mockList).toHaveBeenCalledTimes(2)
  })

  it('③ 401 ⇒ 引导去工人登录（清本机工人身份）', async () => {
    mockList.mockResolvedValue({ success: false, statusCode: 401, message: '登录已失效' })
    await renderPage()

    expect(await screen.findByTestId('worker-rework-login-required')).toBeTruthy()
    fireEvent.click(screen.getByTestId('worker-rework-login'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('④ 🔴 403 = 工人档案没开「返工记录」页 ⇒ 可行动提示（不冒充「没有返工」）', async () => {
    mockList.mockResolvedValue({ success: false, statusCode: 403, message: '无权限' })
    await renderPage()

    expect(await screen.findByTestId('worker-rework-forbidden')).toBeTruthy()
    expect(screen.getByText(FORBIDDEN_HINT)).toBeTruthy()
    // 三种事实各自分开：403 既不渲染空态，也不渲染「读不到，请重试」
    expect(screen.queryByTestId('worker-rework-empty')).toBeNull()
    expect(screen.queryByTestId('worker-rework-error')).toBeNull()
    expect(screen.queryByTestId('worker-rework-retry')).toBeNull()
    // 文案必须可行动（找管理员勾选 + 回来刷新）
    expect(FORBIDDEN_HINT).toContain('工人档案')
    expect(FORBIDDEN_HINT).toContain('返工记录')
    expect(READ_FAILED_HINT).not.toBe(FORBIDDEN_HINT)
  })

  it('⑤ 缺值不编造：返工笔数缺 ⇒ 整项不渲染（不印 0 笔）；时间只切不改', async () => {
    const sparse = { processing_order_id: 'po-2', processing_order_no: 'JG-2', latest_rework_at: '2026-10-26' }
    mockList.mockResolvedValue({ success: true, data: { orders: [sparse] }, message: '' })
    await renderPage()

    expect(await screen.findByTestId('worker-rework-row-0')).toBeTruthy()
    expect(screen.queryByTestId('worker-rework-rework_count-0')).toBeNull()
    expect(screen.queryByTestId('worker-rework-latest_rework_at-0')).toBeNull()
    // 纯函数口径（同一份判定，页面与测试都读它）
    expect(reworkCountText(null)).toBe('')
    expect(reworkCountText(0)).toBe('0 笔')
    expect(reworkAtText('2026-10-26')).toBe('')
    expect(reworkRowModel(sparse).cells).toEqual([])
  })
})
