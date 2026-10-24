// @vitest-environment jsdom
// case_ids: PG-092

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
// 冻结墙钟（issue #4761 同款）：交期「今天」由冻结时刻派生，跨午夜不会假红
import { FROZEN_NOW } from '../helpers/frozen-clock'
import ProcessingOrderActions from '@/components/production/ProcessingOrderActions'

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    update: vi.fn(),
  },
}))

import { processingOrderApi } from '@/lib/api'

const mockedUpdate = processingOrderApi.update as unknown as ReturnType<typeof vi.fn>

/** 本地时区「今天」（yyyy-MM-dd）—— 与组件 `todayLocal()` 同一真值源 */
function todayLocal(): string {
  const mm = String(FROZEN_NOW.getMonth() + 1).padStart(2, '0')
  const dd = String(FROZEN_NOW.getDate()).padStart(2, '0')
  return `${FROZEN_NOW.getFullYear()}-${mm}-${dd}`
}

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

describe('ProcessingOrderActions（issue #7634：状态流转只在生产明细页发生）', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW)
    vi.clearAllMocks()
    mockedUpdate.mockResolvedValue({ data: { data: po('issued') } })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('PG-092 判据 3（红证）：四个状态动作在生产明细页可用', async () => {
    // ① 发加工：加工方 + 交期 ⇒ PATCH action=issue（交期边界校验在生产侧照旧）
    const { unmount } = render(<ProcessingOrderActions po={po('generated') as never} />)
    await userEvent.click(screen.getByTestId('po-action-issue'))
    await userEvent.type(screen.getByPlaceholderText('加工方（如：朝阳加工厂）'), '朝阳加工厂')
    await userEvent.type(screen.getByPlaceholderText('交期 yyyy-MM-dd'), todayLocal())
    await userEvent.click(screen.getByText('确认发加工'))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith('po-1', {
      action: 'issue',
      processor: '朝阳加工厂',
      expectedDeliveryDate: todayLocal(),
      reason: undefined,
    }))
    unmount()

    // ② 开始加工：确认弹框后才发请求
    mockedUpdate.mockClear()
    const second = render(<ProcessingOrderActions po={po('issued') as never} />)
    await userEvent.click(screen.getByTestId('po-action-start'))
    expect(mockedUpdate).not.toHaveBeenCalled()
    expect(screen.getByText(/标记为「开始加工」/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith('po-1', { action: 'start' }))
    second.unmount()

    // ③ 加工完成：同一条确认通道
    mockedUpdate.mockClear()
    const third = render(<ProcessingOrderActions po={po('in_processing') as never} />)
    await userEvent.click(screen.getByTestId('po-action-complete'))
    await userEvent.click(screen.getByRole('button', { name: '确认' }))
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith('po-1', { action: 'complete' }))
    third.unmount()

    // ④ 取消：原因必填（空原因按钮禁用），填了才提交
    mockedUpdate.mockClear()
    render(<ProcessingOrderActions po={po('issued') as never} />)
    await userEvent.click(screen.getByTestId('po-action-cancel'))
    const confirmCancel = screen.getByText('确认取消')
    expect(confirmCancel).toBeDisabled()
    await userEvent.type(screen.getByPlaceholderText('取消原因（必填，涉及订单状态联动）'), '客户改单')
    await userEvent.click(confirmCancel)
    await waitFor(() => expect(mockedUpdate).toHaveBeenCalledWith('po-1', {
      action: 'cancel',
      processor: undefined,
      expectedDeliveryDate: undefined,
      reason: '客户改单',
    }))
  })

  it('发加工：过去交期被拦截，不发请求（issue #3901 边界不因搬家而丢）', async () => {
    const past = new Date(FROZEN_NOW.getTime() - 24 * 3600 * 1000)
    const yyyy = past.getFullYear()
    const mm = String(past.getMonth() + 1).padStart(2, '0')
    const dd = String(past.getDate()).padStart(2, '0')

    render(<ProcessingOrderActions po={po('generated') as never} />)
    await userEvent.click(screen.getByTestId('po-action-issue'))
    await userEvent.type(screen.getByPlaceholderText('交期 yyyy-MM-dd'), `${yyyy}-${mm}-${dd}`)
    await userEvent.click(screen.getByText('确认发加工'))

    expect(await screen.findByText('交付日期不能早于今天')).toBeInTheDocument()
    expect(mockedUpdate).not.toHaveBeenCalled()
  })

  it('出库作业单：没有「发加工」，取消文案是「取消作业单」（issue #7079 口径不丢）', async () => {
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
