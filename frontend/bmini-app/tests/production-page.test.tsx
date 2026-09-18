// case_ids: BM-006
/**
 * 工人端扫码报工页测试（issue #3997 M4-G-3 / issue #4206 补齐，消费 M4-G-2 冻结契约）
 *
 * 链路：扫一扫 / 手输单号 / 深链带参直达 → GET .../operations → 按部位分组工序
 *       → 改「完成数量」→ 点「完成报工」→ POST .../report → 刷新进度 + 计件累计 + 报工明细。
 * 断言口径：报工参数**逐字**断言（冻结字段名不可改）；失败时列表**不清空**（工人可继续）。
 * mock：Taro API（scanCode + **真内存 storage**）+ productionService（网络层）+ authStore。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/** 启动/跳转参数（深链直达判据用；由 Taro.getCurrentInstance().router.params 读出） */
let launchParams: Record<string, string> = {}

jest.mock('@tarojs/taro', () => {
  // 真内存 storage：报工明细/待做清单缓存落在本机持久化上，空实现 jest.fn() 会让这些
  // 断言失去判别性（读永远拿不到写进去的值）。
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
  // 锁用真身（issue #4116 §5-1）：页面调用 reportInFlightLock.tryAcquire()，
  // 若一并 mock 掉会拿到 undefined ⇒ 点「完成报工」直接抛错
  ...jest.requireActual('../src/services/productionService'),
  getOrderOperations: jest.fn(),
  reportOperation: jest.fn(),
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
  getOrderOperations,
  getOrderPiecework,
  reportOperation,
} from '../src/services/productionService'
import type { OrderOperations } from '../src/services/productionService'

const ORDER_ID = 'CSO260915-02615'

/** 冻结契约响应（字段名逐字对齐 issue #3997 契约 1） */
function makeDetail(overrides: Partial<OrderOperations> = {}): OrderOperations {
  return {
    order_id: ORDER_ID,
    qr_token: 'qr-token-1',
    positions: [
      {
        position_name: '布帘',
        operations: [
          {
            id: 'op1', seq: 1, operation: '精裁', group: '裁剪', unit: '米',
            qty: 11, unit_price: 3.5, factor: 1, is_must_finish: true,
            is_start_marker: true, status: 'done', done_qty: 11,
          },
          {
            id: 'op2', seq: 2, operation: '韩褶', group: '车位', unit: '米',
            qty: 11, unit_price: 5, factor: 1, is_must_finish: true,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
      {
        position_name: '纱帘',
        operations: [
          {
            id: 'op3', seq: 3, operation: '定型', group: '后道', unit: '米',
            qty: 11, unit_price: 4, factor: 1, is_must_finish: true,
            is_start_marker: false, status: 'pending', done_qty: 0,
          },
        ],
      },
    ],
    progress: { total: 3, done: 1, percent: 33 },
    ...overrides,
  }
}

const mockGet = getOrderOperations as jest.Mock
const mockReport = reportOperation as jest.Mock
const mockPiecework = getOrderPiecework as jest.Mock

describe('ProductionPage（工人扫码报工）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    launchParams = {}
    ;(Taro as any).__clearStorage()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockPiecework.mockResolvedValue({
      success: true,
      data: {
        total: 62.5,
        per_worker: { 张师傅: 62.5 },
        per_operation: [{ operation: '韩褶', amount: 55 }, { operation: '精裁', amount: 38.5 }],
      },
    })
    mockReport.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
    })
  })

  it('扫码成功 → 按部位分组展示工序（工序名 / 应做数量+单位 / 单价）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))

    expect(await screen.findByText('布帘')).toBeTruthy()
    expect(screen.getByText('纱帘')).toBeTruthy()
    expect(screen.getByText('精裁')).toBeTruthy()
    expect(screen.getByText('韩褶')).toBeTruthy()
    expect(screen.getByText('定型')).toBeTruthy()
    // 应做数量 + 单位 + 单价（B 端可见计件单价）
    expect(screen.getAllByText('应做 11米 · ¥5.00').length).toBeGreaterThan(0)
    expect(screen.getByText('应做 11米 · ¥3.50')).toBeTruthy()
    // 进度
    expect(screen.getByText('已完 1/3 道 · 33%')).toBeTruthy()
  })

  it('点「完成报工」→ 调用 reportOperation（qty 默认=应做数量、work_type=normal）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    // 第 2 道工序（韩褶）对应按钮
    const buttons = screen.getAllByText('完成报工')
    fireEvent.click(buttons[1])

    await waitFor(() =>
      expect(mockReport).toHaveBeenCalledWith(
        ORDER_ID,
        'op2',
        {
          worker_id: 'u1',
          worker_name: '张师傅',
          qty: 11,
          qualified_qty: 11,
          work_type: 'normal',
        },
        // 第 4 参 = 本次动作的幂等键（issue #4206：页面生成并随请求发出，
        // 传输层失败时同一个键随队列项持久化，补传复用它 ⇒ 服务端不重复计件）
        expect.stringMatching(/^report-/),
      ),
    )
  })

  it('报工成功 → 刷新进度（重新拉取工序列表）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')
    mockGet.mockClear()

    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
  })

  it('order_completed=true → 展示「✅ 订单生产完成」', async () => {
    mockReport.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: true },
    })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    fireEvent.click(screen.getAllByText('完成报工')[1])

    expect(await screen.findByText('✅ 订单生产完成')).toBeTruthy()
  })

  it('报工失败（success=false）→ 展示后端 message 且不清空工序列表', async () => {
    mockReport.mockResolvedValue({ success: false, message: '该工序已报工完成，无需重复报工' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    fireEvent.click(screen.getAllByText('完成报工')[1])

    expect(await screen.findByText('该工序已报工完成，无需重复报工')).toBeTruthy()
    // 列表仍在（工人可继续报其它工序）
    expect(screen.getByText('精裁')).toBeTruthy()
    expect(screen.getByText('定型')).toBeTruthy()
  })

  it('扫码取消/失败 → 引导手输，手输单号可查询', async () => {
    ;(Taro.scanCode as jest.Mock).mockRejectedValue({ errMsg: 'scanCode:fail cancel' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    await waitFor(() =>
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('手动输入') }),
      ),
    )

    fireEvent.change(screen.getByPlaceholderText('或手输加工单号'), {
      target: { value: ORDER_ID },
    })
    fireEvent.click(screen.getByText('查单'))

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
    expect(await screen.findByText('韩褶')).toBeTruthy()
  })

  it('扫到非加工单二维码 → 提示且不发请求', async () => {
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: 'https://example.com/vip?x=1 ' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    await waitFor(() =>
      expect(Taro.showToast).toHaveBeenCalledWith(
        expect.objectContaining({ title: expect.stringContaining('无法识别') }),
      ),
    )
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('拉取工序失败 → 展示后端 message', async () => {
    mockGet.mockResolvedValue({ success: false, message: '加工单不存在' })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))

    expect(await screen.findByText('加工单不存在')).toBeTruthy()
  })
})

/**
 * issue #4206 补齐面 1：数量可改（默认 = 应做数量、上限 = 应做数量，服务端仍守上限）。
 *
 * 修复前 `handleReport` 写死 `qty: operation.qty, qualified_qty: operation.qty`，
 * 全页唯一 `<Input>` 是加工单号 ⇒ 工人做了 8 米只能按 11 米报（计件虚高、数量不可核对）。
 */
describe('ProductionPage 完成数量可编辑（issue #4206 判据 1）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    launchParams = {}
    ;(Taro as any).__clearStorage()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockPiecework.mockResolvedValue({ success: true, data: { total: 0, per_worker: {}, per_operation: [] } })
    mockReport.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 8, status: 'done', order_completed: false },
    })
  })

  it('数量输入默认 = 应做数量（未报过时）并提示本次上限', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    // 3 道工序各一个数量输入框；op2（韩褶，应做 11、已报 0）默认 11
    const inputs = screen.getAllByPlaceholderText('完成数量') as HTMLInputElement[]
    expect(inputs).toHaveLength(3)
    expect(inputs[1].value).toBe('11')
    // 韩褶 与 定型 都是「应做 11 / 已报 0」⇒ 上限提示各一行
    expect(screen.getAllByText('本次最多 11米').length).toBeGreaterThanOrEqual(2)
  })

  it('改成 8 米报工 ⇒ 请求体 qty/qualified_qty 都是 8（不是写死的应做数量）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    fireEvent.change(screen.getAllByPlaceholderText('完成数量')[1], { target: { value: '8' } })
    fireEvent.click(screen.getAllByText('完成报工')[1])

    await waitFor(() =>
      expect(mockReport).toHaveBeenCalledWith(
        ORDER_ID,
        'op2',
        {
          worker_id: 'u1',
          worker_name: '张师傅',
          qty: 8,
          qualified_qty: 8,
          work_type: 'normal',
        },
        expect.stringMatching(/^report-/),
      ),
    )
  })

  it('数量超上限 ⇒ 前端拦下不发请求（红证：服务端上限之外再加一道客户端防线）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    fireEvent.change(screen.getAllByPlaceholderText('完成数量')[1], { target: { value: '999' } })
    fireEvent.click(screen.getAllByText('完成报工')[1])

    expect(await screen.findByText(/数量超上限：本次最多可报 11米/)).toBeTruthy()
    expect(mockReport).not.toHaveBeenCalled()
  })

  it('已报过的工序默认 = 剩余待报（应做 − 已报），不会一报就撞服务端上限', async () => {
    mockGet.mockResolvedValue({
      success: true,
      data: makeDetail({
        positions: [
          {
            position_name: '布帘',
            operations: [
              {
                id: 'op2', seq: 2, operation: '韩褶', group: '车位', unit: '米',
                qty: 11, unit_price: 5, factor: 1, is_must_finish: true,
                is_start_marker: false, status: 'pending', done_qty: 5,
              },
            ],
          },
        ],
        progress: { total: 1, done: 0, percent: 0 },
      }),
    })

    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    const input = screen.getAllByPlaceholderText('完成数量')[0] as HTMLInputElement
    expect(input.value).toBe('6')
    expect(screen.getByText('本次最多 6米')).toBeTruthy()
  })
})

/**
 * issue #4206 补齐面 3：报工成功后显示「该工序累计计件金额 + 本单报工明细（人/工序/数量/时间）」。
 *
 * 修复前页面只渲染单价，`piecework` 端点小程序侧**零调用**、`production_work_logs`
 * 无任何前端消费点 ⇒ 工人看不到自己这一单挣了多少、也看不到「谁在什么时候报了多少」。
 */
describe('ProductionPage 计件累计与报工明细（issue #4206 判据 3）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    launchParams = {}
    ;(Taro as any).__clearStorage()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockPiecework.mockResolvedValue({
      success: true,
      data: {
        total: 93.5,
        per_worker: { 张师傅: 93.5 },
        per_operation: [{ operation: '韩褶', amount: 55 }, { operation: '精裁', amount: 38.5 }],
      },
    })
    mockReport.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
    })
  })

  it('展示本单累计计件金额 + 该工序累计计件金额（消费 piecework 端点）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')

    await waitFor(() => expect(mockPiecework).toHaveBeenCalledWith(ORDER_ID))
    expect(await screen.findByText('本单累计计件 ¥93.50')).toBeTruthy()
    expect(screen.getByText('累计计件 ¥55.00')).toBeTruthy()   // 韩褶
    expect(screen.getByText('累计计件 ¥38.50')).toBeTruthy()   // 精裁
  })

  it('报工成功后出现本单报工明细（人 / 工序 / 数量 / 时间）', async () => {
    render(<ProductionPage />)
    fireEvent.click(screen.getByText('扫一扫'))
    await screen.findByText('韩褶')
    expect(screen.queryByText('本单报工明细')).toBeNull()

    fireEvent.click(screen.getAllByText('完成报工')[1])

    expect(await screen.findByText('本单报工明细')).toBeTruthy()
    expect(screen.getByText(/张师傅 · 韩褶 · 11米 · \d{2}-\d{2} \d{2}:\d{2}/)).toBeTruthy()
  })
})

/**
 * issue #4206 补齐面 4：二维码/跳转带参直达报工页（小程序内跳转可带参直达）。
 *
 * 修复前页面无任何启动参数处理 ⇒ 带 `order_id` 的跳转落在空页面上，工人仍要手输单号。
 */
describe('ProductionPage 深链带参直达（issue #4206 判据 4）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    launchParams = {}
    ;(Taro as any).__clearStorage()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
    mockPiecework.mockResolvedValue({ success: true, data: { total: 0, per_worker: {}, per_operation: [] } })
    mockReport.mockResolvedValue({
      success: true,
      data: { operation_id: 'op2', done_qty: 11, status: 'done', order_completed: false },
    })
  })

  it('启动参数带 order_id ⇒ 免扫码/免手输，直接出该单工序', async () => {
    launchParams = { order_id: ORDER_ID }

    render(<ProductionPage />)

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
    expect(await screen.findByText('韩褶')).toBeTruthy()
    expect(screen.getByText('已完 1/3 道 · 33%')).toBeTruthy()
  })

  it('启动参数带 qr（二维码原串，含 migao:// 形态）同样直达', async () => {
    launchParams = { qr: `migao://production/${ORDER_ID}?token=abc123` }

    render(<ProductionPage />)

    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(ORDER_ID))
    expect(await screen.findByText('韩褶')).toBeTruthy()
  })

  it('无启动参数 ⇒ 不发请求，仍是空态（不瞎猜单号）', async () => {
    render(<ProductionPage />)

    await waitFor(() => expect(screen.getByText('扫码或输入加工单号后显示本单工序')).toBeTruthy())
    expect(mockGet).not.toHaveBeenCalled()
  })
})
