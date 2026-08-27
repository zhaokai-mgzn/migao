// @vitest-environment jsdom
// case_ids: OR-001, OR-002

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import RefundOrderModal from '@/components/orders/RefundOrderModal'
import type { Order } from '@/types'

const order: Order = {
  id: 'order-1',
  orderNo: 'MG202600001',
  customerName: '张三',
  customerPhone: '13800000000',
  totalAmount: 1999,
  actualAmount: 1999,
  discountAmount: 0,
  status: 'completed',
  hasProcessing: false,
}

function renderModal(props: Partial<React.ComponentProps<typeof RefundOrderModal>> = {}) {
  const onClose = vi.fn()
  const onConfirm = vi.fn()
  const utils = render(
    <RefundOrderModal open onClose={onClose} onConfirm={onConfirm} order={order} {...props} />
  )
  return { onClose, onConfirm, ...utils }
}

describe('RefundOrderModal', () => {
  it('renders title and order number', () => {
    renderModal()
    expect(screen.getByText('处理退款')).toBeInTheDocument()
    expect(screen.getByText(/MG202600001/)).toBeInTheDocument()
  })

  it('amount input defaults to actualAmount (实收)', () => {
    renderModal()
    const input = screen.getByLabelText('退款金额') as HTMLInputElement
    expect(input.value).toBe('1999')
  })

  it('renders preset refund reasons', () => {
    renderModal()
    expect(screen.getByLabelText('质量问题')).toBeInTheDocument()
    expect(screen.getByLabelText('客户退货')).toBeInTheDocument()
    expect(screen.getByLabelText('协商一致')).toBeInTheDocument()
  })

  it('submit calls onConfirm with refundAmount and refundReason', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderModal()
    await user.click(screen.getByLabelText('质量问题'))
    await user.click(screen.getByRole('button', { name: '确定' }))
    expect(onConfirm).toHaveBeenCalledWith({ refundAmount: 1999, refundReason: '质量问题' })
  })

  it('uses custom reason when 其它原因 selected', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderModal()
    await user.click(screen.getByLabelText('其它原因'))
    await user.type(screen.getByPlaceholderText('请输入退款原因'), '客户要求全退')
    await user.click(screen.getByRole('button', { name: '确定' }))
    expect(onConfirm).toHaveBeenCalledWith({ refundAmount: 1999, refundReason: '客户要求全退' })
  })

  it('does NOT confirm when amount is invalid (empty/<=0)', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderModal()
    const input = screen.getByLabelText('退款金额')
    await user.clear(input)
    await user.click(screen.getByRole('button', { name: '确定' }))
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('cancel calls onClose', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(onClose).toHaveBeenCalled()
  })

  it('returns null when closed', async () => {
    render(<RefundOrderModal open={false} onClose={vi.fn()} onConfirm={vi.fn()} order={order} />)
    await waitFor(() => {
      expect(screen.queryByText('处理退款')).not.toBeInTheDocument()
    })
  })
})
