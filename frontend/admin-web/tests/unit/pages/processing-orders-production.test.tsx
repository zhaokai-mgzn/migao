// case_ids: PP-011, PG-019
// PP-011（issue #4000，M4-H 按需单据渲染）：加工单生产明细页 /processing-orders/{id}/production
// —— 头部（加工单号/订单号/状态/进度/交期）+ 工序进度表 + 计件汇总 + 打印任务卡入口，
// 接口失败要有友好错误提示与重试（不白屏）。
// PG-019（issue #4202，前端半边）：存量加工单（positions 为空且非 cancelled）显示「补生成工序」
// → 调 POST /production/orders/{orderId}/instantiate（空 body）→ 刷新出工序表与二维码；
// 有数据 / 已取消时按钮不出现；任务卡占位文案不得误导（不得再指向「请先在订单详情生成加工单」）。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockDetail = vi.fn()
const mockGetOrderOperations = vi.fn()
const mockGetPiecework = vi.fn()
const mockInstantiate = vi.fn()
const mockRecordPrint = vi.fn()

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    detail: (...args: unknown[]) => mockDetail(...args),
  },
  productionApi: {
    getOrderOperations: (...args: unknown[]) => mockGetOrderOperations(...args),
    getPiecework: (...args: unknown[]) => mockGetPiecework(...args),
    instantiate: (...args: unknown[]) => mockInstantiate(...args),
    recordPrint: (...args: unknown[]) => mockRecordPrint(...args),
  },
}))

vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'JG-20260917-0001',
}))

import ProductionDetailPage from '@/app/(dashboard)/processing-orders/[id]/production/page'

const PROCESSING_ORDER = {
  id: 'po-1',
  orderId: 'order-uuid-1',
  orderNo: 'MG20260917001',
  processingOrderNo: 'JG-20260917-0001',
  customerName: '李四',
  expectedDeliveryDate: '2026-09-25',
  status: 'in_processing' as const,
  generatedAt: '2026-09-17 10:00:00',
}

const OPERATIONS = {
  order_id: 'order-uuid-1',
  qr_token: 'qr-token-abc123',
  positions: [
    {
      position_name: '布帘',
      operations: [
        {
          id: 'op-1',
          seq: 1,
          operation: '精裁-布',
          group: '裁剪',
          unit: '套',
          qty: 2,
          unit_price: 8.5,
          is_must_finish: false,
          status: 'done',
          done_qty: 2,
        },
        {
          id: 'op-2',
          seq: 2,
          operation: '外帘装袋',
          group: '后道',
          unit: '件',
          qty: 2,
          unit_price: 3,
          is_must_finish: true,
          status: 'pending',
          done_qty: 0,
        },
      ],
    },
  ],
  progress: { total: 2, done: 1, percent: 50 },
}

const PIECEWORK = {
  total: 17,
  per_worker: { 蒋雪云: 17 },
  per_operation: [{ operation: '精裁-布', amount: 17 }],
}

const ok = (data: unknown) => ({ data: { success: true, data } })

describe('加工单生产明细页', () => {
  beforeEach(() => {
    mockDetail.mockReset().mockResolvedValue(ok(PROCESSING_ORDER))
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockReset().mockResolvedValue(ok(PIECEWORK))
    mockInstantiate.mockReset().mockResolvedValue(ok({ qr_token: 'qr-token-abc123', operation_count: 2 }))
    mockRecordPrint.mockReset().mockResolvedValue(ok({ print_count: 1 }))
  })

  it('渲染头部信息：加工单号/订单号/状态/交期 + 进度百分比', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    expect(screen.getByTestId('production-processing-order-no')).toHaveTextContent('JG-20260917-0001')
    expect(screen.getByTestId('production-order-no')).toHaveTextContent('MG20260917001')
    expect(screen.getByTestId('production-status')).toHaveTextContent('加工中')
    expect(screen.getByTestId('production-delivery-date')).toHaveTextContent('2026-09-25')
    expect(screen.getByTestId('production-progress-text')).toHaveTextContent('50%')
    expect(screen.getByTestId('production-progress-text')).toHaveTextContent('1/2')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50')
  })

  it('用加工单上的 orderId 拉工序与计件，并渲染工序表/必完标记/计件合计', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())

    expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-1')
    expect(mockGetPiecework).toHaveBeenCalledWith('order-uuid-1')
    expect(within(screen.getByTestId('operation-row-op-2')).getByText('必完')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-total')).toHaveTextContent('¥17.00')
  })

  it('「打印任务卡」按钮调用 window.print（任务卡含二维码）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    // 任务卡随页面挂载（屏幕隐藏、打印显形），二维码内容是 qr_token
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('production-print-button'))
    expect(printSpy).toHaveBeenCalledTimes(1)

    printSpy.mockRestore()
  })

  it('打印时上报打印计数，且计数接口失败不阻断打印（fire-and-forget）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    mockRecordPrint.mockRejectedValueOnce(new Error('boom'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-print-button'))

    // 先调计数端点（不 await 结果），再打印
    await waitFor(() => expect(mockRecordPrint).toHaveBeenCalledWith('order-uuid-1'))
    expect(printSpy).toHaveBeenCalledTimes(1)

    printSpy.mockRestore()
  })

  it('工序接口失败：给出提示且不白屏（计件仍展示）', async () => {
    mockGetOrderOperations.mockRejectedValue(new Error('boom'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-operations-error')).toBeInTheDocument())

    expect(screen.getByTestId('production-operations-error')).toHaveTextContent('工序进度加载失败')
    expect(screen.getByTestId('production-header')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-total')).toHaveTextContent('¥17.00')
  })

  it('加工单详情失败：显示错误提示 + 重试按钮（可重新拉取）', async () => {
    mockDetail.mockRejectedValueOnce(new Error('network'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-error')).toHaveTextContent('加载加工单失败')

    await userEvent.click(screen.getByTestId('production-retry-button'))

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(mockDetail).toHaveBeenCalledTimes(2)
  })

  it('加工单无工序实例：空态提示，不报错', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0, per_worker: {}, per_operation: [] }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByText('暂无工序数据')).toBeInTheDocument())
    expect(screen.getByText('暂无计件数据')).toBeInTheDocument()
    expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument()
  })

  // ── PG-019：存量加工单补生成工序（issue #4202 前端半边）──

  it('存量加工单（positions 空 + 非 cancelled）：显示「补生成工序」按钮', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0, per_worker: {}, per_operation: [] }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    expect(screen.getByTestId('production-instantiate-button')).toHaveTextContent('补生成工序')
  })

  it('点击「补生成工序」：调 instantiate（空 body）→ 刷新出工序表与二维码', async () => {
    mockGetOrderOperations
      .mockResolvedValueOnce(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
      .mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockResolvedValue(ok(PIECEWORK))
    mockInstantiate.mockResolvedValue(ok({ qr_token: 'qr-token-abc123', operation_count: 2 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-instantiate-button'))

    // 空 body = 服务端按订单自动派生工序（冻结契约：positions 可选）
    await waitFor(() => expect(mockInstantiate).toHaveBeenCalledWith('order-uuid-1'))
    // 刷新后出真实工序行 + 二维码；按钮消失（已有工序）
    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()
    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('补生成失败：错误提示可见，且按钮保留（可重试）', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    mockInstantiate.mockRejectedValueOnce(new Error('422 positions 不能为空'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-instantiate-button'))

    await waitFor(() => expect(screen.getByTestId('production-instantiate-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument()
  })

  it('已有工序实例：不显示「补生成工序」（避免误重插行）', async () => {
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())

    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('已取消加工单：不显示「补生成工序」（终态不可重生成）', async () => {
    mockDetail.mockResolvedValue(ok({ ...PROCESSING_ORDER, status: 'cancelled' }))
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('任务卡占位文案不误导：不得再指向「请先在订单详情生成加工单」', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    // 任务卡是 portal + display:none（打印才显形）⇒ 判文案只看 DOM 存在性，不能用 innerText
    await waitFor(() => expect(screen.getByTestId('task-card-no')).toHaveTextContent('JG-20260917-0001'))
    const placeholder = screen.getByTestId('task-card-qr-placeholder')
    // 加工单**已生成**，二维码缺的真成因是「工序未生成」⇒ 不得再指回去生成加工单
    expect(placeholder.textContent).not.toContain('请先在订单详情生成加工单')
    // 指引指向本页的补生成工序（同一修复面的正向判据）
    expect(screen.getByTestId('production-instantiate-button')).toHaveTextContent('补生成工序')
  })
})
