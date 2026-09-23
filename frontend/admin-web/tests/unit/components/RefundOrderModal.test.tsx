// @vitest-environment jsdom
// case_ids: OR-001, OR-002, UI-055

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
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

  // ── 退款金额的数值语义（issue #5228 缺口 2，**涉钱面**）──────────────────────
  //
  // ⚠️ 判据**不建在「`0.` 中间态」上**：jsdom 把 `type="number"` 的 `"0."` 归一成 `""`，
  // 真 Chromium 归一成 `"0"`（#5228 主会话真浏览器实测，两套读数**相反**）⇒ 判据一律用
  // `fireEvent.change` **一次给完整串**，钉与引擎无关的语义。

  it('完整串 `0.5` ⇒ 回调 refundAmount: 0.5（原值：不取整、不被当空）', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderModal()
    fireEvent.change(screen.getByLabelText('退款金额'), { target: { value: '0.5' } })
    await user.click(screen.getByRole('button', { name: '确定' }))
    expect(onConfirm).toHaveBeenCalledWith({ refundAmount: 0.5, refundReason: '质量问题' })
  })

  it('清空 ⇒ 不回调（空**不是 0**）：确定被禁用，且即便点下去也不回调', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderModal()
    const confirm = screen.getByRole('button', { name: '确定' })
    fireEvent.change(screen.getByLabelText('退款金额'), { target: { value: '' } })
    expect(confirm).toBeDisabled()
    fireEvent.click(confirm) // 绕过 disabled 属性直点：证明守卫在**处理函数**里，不只是个属性
    await user.click(confirm)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('`0` ⇒ 不回调（0 被**显式判为无效**，而不是被当空吞掉、也不是按 0 提交）', async () => {
    const user = userEvent.setup()
    const { onConfirm } = renderModal()
    const confirm = screen.getByRole('button', { name: '确定' })
    fireEvent.change(screen.getByLabelText('退款金额'), { target: { value: '0' } })
    expect(confirm).toBeDisabled()
    fireEvent.click(confirm)
    await user.click(confirm)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('returns null when closed', async () => {
    render(<RefundOrderModal open={false} onClose={vi.fn()} onConfirm={vi.fn()} order={order} />)
    await waitFor(() => {
      expect(screen.queryByText('处理退款')).not.toBeInTheDocument()
    })
  })
})
