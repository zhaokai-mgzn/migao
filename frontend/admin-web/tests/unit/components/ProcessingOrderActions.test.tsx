// @vitest-environment jsdom
// case_ids: PG-092, PG-095

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
// 冻结墙钟（issue #4761 同款）：跨午夜不会假红
import { FROZEN_NOW } from '../helpers/frozen-clock'
import ProcessingOrderActions from '@/components/production/ProcessingOrderActions'

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    update: vi.fn(),
  },
}))

import { processingOrderApi } from '@/lib/api'

const mockedUpdate = processingOrderApi.update as unknown as ReturnType<typeof vi.fn>

function po(status: string, over: Record<string, unknown> = {}) {
  return {
    id: 'po-1',
    orderId: 'order-001',
    orderNo: 'ORD-1',
    processingOrderNo: 'JG-20260912-0001',
    status,
    items: [],
    ...over,
  }
}

describe('ProcessingOrderActions（issue #7634 状态流转只在生产明细页；#7723 移除「发加工」）', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW)
    vi.clearAllMocks()
    mockedUpdate.mockResolvedValue({ data: { data: po('issued') } })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('#7723 判据（红证）：任何状态下都**没有**「发加工」按钮（外发已搬到智能派单）', () => {
    for (const status of ['generated', 'issued', 'in_processing']) {
      const view = render(<ProcessingOrderActions po={po(status) as never} />)
      expect(screen.queryByTestId('po-action-issue')).toBeNull()
      expect(screen.queryByText('发加工')).toBeNull()
      view.unmount()
    }
  })

  it('PG-092 判据 3：开始加工 / 加工完成 / 取消 三个动作仍可用', async () => {
    // ① 开始加工：确认弹框后才发请求
    const first = render(<ProcessingOrderActions po={po('issued') as never} />)
    await userEvent.click(screen.getByTestId('po-action-start'))
    expect(mockedUpdate).not.toHaveBeenCalled()
    expect(screen.getByText(/标记为「开始加工」/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith('po-1', { action: 'start' }))
    first.unmount()

    // ② 加工完成：同一条确认通道
    mockedUpdate.mockClear()
    const second = render(<ProcessingOrderActions po={po('in_processing') as never} />)
    await userEvent.click(screen.getByTestId('po-action-complete'))
    await userEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith('po-1', { action: 'complete' }))
    second.unmount()

    // ③ 取消：原因必填（空原因按钮禁用），填了才提交
    mockedUpdate.mockClear()
    render(<ProcessingOrderActions po={po('issued') as never} />)
    await userEvent.click(screen.getByTestId('po-action-cancel'))
    const confirmCancel = screen.getByText('确认取消')
    expect(confirmCancel).toBeDisabled()
    await userEvent.type(screen.getByPlaceholderText('取消原因（必填，涉及订单状态联动）'), '客户改单')
    await userEvent.click(confirmCancel)
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith('po-1', {
      action: 'cancel',
      reason: '客户改单',
    }))
  })

  it('出库作业单：取消文案是「取消作业单」（issue #7079 口径不丢）', async () => {
    render(<ProcessingOrderActions po={po('issued', { order_kind: 'outbound' }) as never} />)

    expect(screen.queryByTestId('po-action-issue')).toBeNull()
    expect(screen.getByTestId('po-action-cancel')).toHaveTextContent('取消作业单')
    expect(screen.queryByText('取消加工单')).toBeNull()
  })

  it('PG-092 判据 4：终态没有状态动作（已完工 / 已取消都只读）', () => {
    const completed = render(<ProcessingOrderActions po={po('completed') as never} />)
    expect(screen.queryByTestId('po-action-start')).toBeNull()
    expect(screen.queryByTestId('po-action-complete')).toBeNull()
    expect(screen.queryByTestId('po-action-cancel')).toBeNull()
    completed.unmount()

    render(<ProcessingOrderActions po={po('cancelled') as never} />)
    expect(screen.queryByTestId('po-action-cancel')).toBeNull()
  })
})
