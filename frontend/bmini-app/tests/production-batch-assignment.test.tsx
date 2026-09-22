// case_ids: BM-007
/**
 * 工人端「去哪个批次裁多少米」（issue #5145 阶段 1，母单 #5144 的原始诉求）。
 *
 * 链路：文员生成加工单时**指定批次** ⇒ 后端在**工人端读面**（`GET /api/admin/production/orders/{orderId}/operations`）
 * 的 `positions[]` 上**只在该部位真的指派过批次时**追加 `batch_no` + `batch_meters` 两键
 * ⇒ 页面在既有「用料 X 米」那一行的展示位追加「批次 <批次号> 裁 <米数> 米」，工人一眼知道去哪个批次裁多少米。
 *
 * 口径（与 `specSummary` 既有各键**逐字同款**）：**缺键就不显示** —— 不补默认值、不显示占位符、
 * 不显示「未知」；**两键都在**才追加（只有一个 ⇒ 不显示，免得显示半句话）。
 *
 * 红证（每条断言都有能**单独**让它红的变异）：
 * - ① / ④：删掉那句追加（= 改前形态）⇒ ① / ④ 红；
 * - ② / ⑤：判据写成「有 batch_no（或 batch_meters）就显示」⇒ ② / ⑤ 红（显示半句话）；
 * - ⑥：判据写成真值判断 `if (batchNo && batchMeters)` ⇒ ⑥ 红（`裁 0 米` 被 falsy 静默吞掉）；
 * - ③：缺键时补占位（如「批次 未知」）/ 给缺键编默认值 ⇒ ③ 红（那一行逐字变样）。
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'

/** 启动/跳转参数（深链带 `order_id` 直达，省去扫码交互 —— 本文件只测展示位） */
let launchParams: Record<string, string> = {}

jest.mock('@tarojs/taro', () => {
  // 真内存 storage：页面 loadOrder 成功会把待做清单落本机（空实现会让缓存断言失去判别性）
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
      getCurrentInstance: jest.fn(() => ({ router: { params: launchParams } })),
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
  // 锁用真身（issue #4116 §5-1）：页面会取 reportInFlightLock
  ...jest.requireActual('../src/services/productionService'),
  getOrderOperations: jest.fn(),
  getOrderPiecework: jest.fn(),
  reportOperation: jest.fn(),
  shipOrder: jest.fn(),
  scanResolve: jest.fn(),
  completeByScan: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    user: { id: 'u1', nickname: '张师傅', avatar: null, tenantId: 1, role: 'operator' },
  })),
}))

import Taro from '@tarojs/taro'
import ProductionPage from '../src/pages/production/index/index'
import { getOrderOperations, getOrderPiecework } from '../src/services/productionService'
import type { OrderOperations, ProductionPosition } from '../src/services/productionService'

const ORDER_ID = 'CSO260923-00001'

/** 契约响应夹具（与 production-page.test.tsx 同口径：一个部位 + 完整规格可见面） */
function makeDetail(position: Partial<ProductionPosition> = {}): OrderOperations {
  return {
    order_id: ORDER_ID,
    positions: [
      {
        position_name: '布帘',
        order_item_id: 'item-A',
        width: 6.6,
        height: 2.92,
        craft: '韩褶',
        openCount: 4,
        cuttingMode: '定高买宽',
        isShaped: true,
        fullness: 2.0,
        fabric_meters: 12.3,
        operations: [
          {
            id: 'op1', seq: 1, operation: '精裁', group: '裁剪', unit: '米',
            qty: 11, unit_price: 3.5, is_must_finish: true,
            is_start_marker: true, status: 'pending', done_qty: 0,
          },
        ],
        // 批次两键由各用例按需注入（缺省 = 服务端未指派 ⇒ 一个键都不下发）
        ...position,
      },
    ],
    progress: { total: 1, done: 0, percent: 0 },
    work_logs: [],
  }
}

const mockGet = getOrderOperations as jest.Mock
const mockPiecework = getOrderPiecework as jest.Mock

/** 深链直达渲染；就绪锚点 = 既有规格行（批次那一句拼接在它后面） */
async function renderOrder(detail: OrderOperations): Promise<void> {
  mockGet.mockResolvedValue({ success: true, data: detail })
  launchParams = { order_id: ORDER_ID }
  render(<ProductionPage />)
  await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
  expect(await screen.findByText(/用料 12\.3 米/)).toBeTruthy()
}

describe('工人端批次指派可见面（issue #5145 阶段 1）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    launchParams = {}
    ;(Taro as any).__clearStorage()
    mockPiecework.mockResolvedValue({
      success: true,
      data: { total: 0, per_worker: {}, per_operation: [] },
    })
  })

  it('① 两键都在 ⇒ 追加「批次 PC-… 裁 2.7 米」（工人知道去哪个批次裁多少米）', async () => {
    await renderOrder(makeDetail({ batch_no: 'PC-20260923-0001', batch_meters: 2.7 }))

    expect(await screen.findByText(/批次 PC-20260923-0001 裁 2\.7 米/)).toBeTruthy()
  })

  it('② 只有 batch_no（缺米数）⇒ 不显示（不显示半句话）', async () => {
    await renderOrder(makeDetail({ batch_no: 'PC-20260923-0001' }))

    expect(screen.queryByText(/批次/)).toBeNull()
    // 缺的只是批次那一句，既有「用料」行照旧
    expect(screen.getByText(/用料 12\.3 米/)).toBeTruthy()
  })

  it('③ 两键都缺（未指派）⇒ 不显示，且既有规格行**逐字不变**（缺键不补默认值/占位符）', async () => {
    await renderOrder(makeDetail())

    expect(screen.queryByText(/批次/)).toBeNull()
    // 逐字断言整行：任何占位/默认值（「批次 未知」「裁 undefined 米」…）都会让这行变样 ⇒ 红
    expect(
      screen.getByText(
        '尺寸 6.6 × 2.92 · 韩褶 · 开数 4 · 定高买宽 · 定型 · 褶倍 2 · 用料 12.3 米',
      ),
    ).toBeTruthy()
  })

  it('④ 既有「用料 X 米」展示位不受影响（批次是**追加**，不改写既有那一行）', async () => {
    await renderOrder(makeDetail({ batch_no: 'PC-20260923-0001', batch_meters: 2.7 }))

    expect(
      screen.getByText(
        '尺寸 6.6 × 2.92 · 韩褶 · 开数 4 · 定高买宽 · 定型 · 褶倍 2 · 用料 12.3 米 · 批次 PC-20260923-0001 裁 2.7 米',
      ),
    ).toBeTruthy()
  })

  it('⑤ 只有 batch_meters（缺批次号）⇒ 不显示（对称于 ②）', async () => {
    await renderOrder(makeDetail({ batch_meters: 2.7 }))

    expect(screen.queryByText(/批次/)).toBeNull()
    expect(screen.queryByText(/裁 2\.7 米/)).toBeNull()
  })

  it('⑥ batch_meters=0 且两键都在 ⇒ 显示「裁 0 米」（0 是值、不是缺键，不得被真值判断吞掉）', async () => {
    await renderOrder(makeDetail({ batch_no: 'PC-20260923-0001', batch_meters: 0 }))

    expect(await screen.findByText(/批次 PC-20260923-0001 裁 0 米/)).toBeTruthy()
  })
})
