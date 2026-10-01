// case_ids: OR-055
/**
 * 「修改订单」弹窗（issue #5842；用户 2026-10-01 裁定「买家未付款的订单要允许修改」）。
 *
 * 判据（每条都在下面有对应用例）：
 * ① 打开即带出订单真值（收货三件套 / 每行数量单价）；
 * ② 改数量单价 ⇒ 请求带新值，且**不带 `subtotal` / `totalAmount`**（金额一律服务端重算 ——
 *    客户端带一个金额字段出来就是"我信它"的第一步）；
 * ③ 勾加工项 ⇒ `processingInfo.processingItems` 变，而**其它键原样带回**
 *    （`craftLineId` 樘窗组键 / `processingMeters` 米数是加工单快照的固化真相，丢了就少活/算错钱）；
 * ④ 客户端闸门（数量 < 1）⇒ 不发请求 + 明说哪一行；
 * ⑤ 保存失败（后端 422 中文文案）⇒ 弹窗**保持打开**（不许装作已保存）。
 *
 * 红证方向：把 `buildProcessingInfo` 的"其余键原样带回"删掉 ⇒ 用例 ③ 红；
 * 把 `subtotal` 加回 payload ⇒ 用例 ② 红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockUpdateOrderContent = vi.fn()
const mockGetProcessingItems = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    updateOrderContent: (...args: any[]) => mockUpdateOrderContent(...args),
  },
  processingItemApi: {
    getProcessingItems: (...args: any[]) => mockGetProcessingItems(...args),
  },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { toast } from 'sonner'
import EditOrderContentModal from '@/components/orders/EditOrderContentModal'

/** 订单真值（含加工项：`craftLineId` / `processingMeters` 是必须原样带回的"其余键"） */
const order: any = {
  id: 'order-1',
  orderNo: 'MG20261001001',
  status: 'pending',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区xx小区',
  totalAmount: 599,
  discountAmount: 0,
  actualAmount: 599,
  items: [
    {
      id: 'item-1',
      productId: 'prod-1',
      productName: '蜂巢帘',
      quantity: 2,
      unitPrice: 299.5,
      width: 2.8,
      height: 3,
      processingInfo: {
        craftLineId: 'L1',
        processingMeters: 6,
        processingItems: [{ id: 'pi-1', name: '韩褶', quantity: 2 }],
        specialOptions: [],
      },
    },
  ],
}

function renderModal(overrides: Record<string, unknown> = {}) {
  const onClose = vi.fn()
  const onSaved = vi.fn()
  render(
    <EditOrderContentModal
      open
      order={order}
      onClose={onClose}
      onSaved={onSaved}
      {...overrides}
    />,
  )
  return { onClose, onSaved }
}

describe('EditOrderContentModal（修改订单 · 待付款内容编辑）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProcessingItems.mockResolvedValue({
      data: { data: { items: [{ id: 'pi-1', name: '韩褶' }, { id: 'pi-2', name: '定型' }] } },
    })
    mockUpdateOrderContent.mockResolvedValue({ data: { data: order } })
  })

  it('① 打开即带出订单真值（收货三件套 + 每行数量/单价）', async () => {
    renderModal()
    expect(screen.getByTestId('edit-customer-name')).toHaveValue('张三')
    expect(screen.getByTestId('edit-customer-phone')).toHaveValue('13800138000')
    expect(screen.getByTestId('edit-customer-address')).toHaveValue('北京市朝阳区xx小区')
    expect(screen.getByTestId('edit-line-quantity-0')).toHaveValue(2)
    expect(screen.getByTestId('edit-line-price-0')).toHaveValue(299.5)
    // 已选的加工项呈勾选态（不是"看起来没选"）
    await waitFor(() => {
      expect(screen.getByTestId('edit-line-0-processing-韩褶')).toBeChecked()
    })
  })

  it('② 改数量/单价 ⇒ 请求带新值，且**不带** subtotal / totalAmount（金额服务端重算）', async () => {
    const user = userEvent.setup()
    const { onSaved } = renderModal()
    await waitFor(() => expect(screen.getByTestId('edit-line-0-processing-韩褶')).toBeChecked())

    await user.clear(screen.getByTestId('edit-line-quantity-0'))
    await user.type(screen.getByTestId('edit-line-quantity-0'), '3')
    await user.clear(screen.getByTestId('edit-line-price-0'))
    await user.type(screen.getByTestId('edit-line-price-0'), '100')
    await user.click(screen.getByTestId('edit-submit'))

    await waitFor(() => expect(mockUpdateOrderContent).toHaveBeenCalledTimes(1))
    const [id, payload] = mockUpdateOrderContent.mock.calls[0]
    expect(id).toBe('order-1')
    expect(payload.items[0].quantity).toBe(3)
    expect(payload.items[0].unitPrice).toBe(100)
    // 🔴 金额字段**不存在**（不是"传了 0"）：不给字段比"收了再忽略"更不容易被后人误用
    expect(Object.keys(payload.items[0])).not.toContain('subtotal')
    expect(Object.keys(payload)).not.toContain('totalAmount')
    expect(onSaved).toHaveBeenCalled()
  })

  it('③ 勾加工项 ⇒ processingItems 变，其它键（樘窗组键/加工费米数）**原样带回**', async () => {
    const user = userEvent.setup()
    renderModal()
    await waitFor(() => expect(screen.getByTestId('edit-line-0-processing-定型')).toBeInTheDocument())

    await user.click(screen.getByTestId('edit-line-0-processing-定型'))
    await user.click(screen.getByTestId('edit-submit'))

    await waitFor(() => expect(mockUpdateOrderContent).toHaveBeenCalledTimes(1))
    const info = mockUpdateOrderContent.mock.calls[0][1].items[0].processingInfo
    expect(info.processingItems.map((row: any) => row.name)).toEqual(['韩褶', '定型'])
    // 原有加工项的 id/数量按名字保留（不重置成 1）；新勾的默认 1
    expect(info.processingItems.find((row: any) => row.name === '韩褶')).toMatchObject({ id: 'pi-1', quantity: 2 })
    expect(info.processingItems.find((row: any) => row.name === '定型')).toMatchObject({ quantity: 1 })
    // 其余键原样带回
    expect(info.craftLineId).toBe('L1')
    expect(info.processingMeters).toBe(6)
  })

  it('④ 客户端闸门：数量 < 1 ⇒ 不发请求 + 指明哪一行', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.clear(screen.getByTestId('edit-line-quantity-0'))
    await user.click(screen.getByTestId('edit-submit'))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('第 1 行的数量不能小于 1'))
    expect(mockUpdateOrderContent).not.toHaveBeenCalled()
  })

  it('⑤ 保存失败（后端 422 中文文案）⇒ 弹窗保持打开，不当作已保存', async () => {
    const user = userEvent.setup()
    mockUpdateOrderContent.mockRejectedValue(new Error('订单当前状态为「已确认」，只有「待付款」的订单可以修改内容'))
    const { onSaved, onClose } = renderModal()
    await user.click(screen.getByTestId('edit-submit'))

    await waitFor(() => expect(mockUpdateOrderContent).toHaveBeenCalledTimes(1))
    expect(onSaved).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByTestId('edit-order-content-modal')).toBeInTheDocument()
  })
})
