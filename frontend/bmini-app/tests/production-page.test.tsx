// case_ids: BM-006
/**
 * 工人端扫码报工页测试（issue #3997，M4-G-3，消费 M4-G-2 冻结契约）
 *
 * 链路：扫一扫 / 手输单号 → GET .../operations → 按部位分组工序 → 点「完成报工」
 *       → POST .../report（qty 默认=应做数量，work_type=normal）→ 刷新进度 / 完工提示。
 * 断言口径：报工参数**逐字**断言（冻结字段名不可改）；失败时列表**不清空**（工人可继续）。
 * mock：Taro API（scanCode）+ productionService（网络层）+ authStore（当前员工=报工人）。
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => ({
  __esModule: true,
  default: {
    scanCode: jest.fn(),
    showToast: jest.fn(),
    navigateTo: jest.fn(),
    getStorageSync: jest.fn(() => ''),
    setStorageSync: jest.fn(),
    removeStorageSync: jest.fn(),
  },
  useDidShow: jest.fn(),
}))

jest.mock('../src/services/productionService', () => ({
  getOrderOperations: jest.fn(),
  reportOperation: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({
    user: { id: 'u1', nickname: '张师傅', avatar: null, tenantId: 1, role: 'operator' },
  })),
}))

import Taro from '@tarojs/taro'
import ProductionPage from '../src/pages/production/index/index'
import { getOrderOperations, reportOperation } from '../src/services/productionService'
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

describe('ProductionPage（工人扫码报工）', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(Taro.scanCode as jest.Mock).mockResolvedValue({ result: ORDER_ID })
    mockGet.mockResolvedValue({ success: true, data: makeDetail() })
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
      expect(mockReport).toHaveBeenCalledWith(ORDER_ID, 'op2', {
        worker_id: 'u1',
        worker_name: '张师傅',
        qty: 11,
        qualified_qty: 11,
        work_type: 'normal',
      }),
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
