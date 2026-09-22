// case_ids: PR-079
//
// PR-079（issue #5177）：订单详情页上的**加急 / 到货日改单控件**（`OrderUrgencyPanel`）。
//
// 三条口径（冻结契约 + §15.1）：
//   ① **缺省不变**：初值取**服务端值**，`isUrgent` 缺省即「不加急」——
//      **不得默认勾上**（勾了就是替商家编造一个插队事实）；
//   ② **零联动**：只读写**订单**的加急字段，与售后工单的 `priority` 无任何关系
//      —— 请求体里除了 `{isUrgent, requiredDeliveryDate}` **不许有第三个键**，
//      且本组件从不碰 `afterSalesApi`（本文件把售后 API 也替身进来并断言其零调用）；
//   ③ **结果可见**：保存后徽标刷新成**服务端真值**（父级重新拉单）——
//      「加了急但库里没变」在屏幕上看得见（徽标不动），而不是被本地 state 假装成成功。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { toast } from 'sonner'

const mockUpdateUrgency = vi.fn()
const mockAfterSalesUpdate = vi.fn()
const mockAfterSalesList = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    updateUrgency: (...a: unknown[]) => mockUpdateUrgency(...a),
  },
  // 售后侧的替身：本组件**不得**触碰任何一个（零联动的机械判据）
  afterSalesApi: {
    updateTicketStatus: (...a: unknown[]) => mockAfterSalesUpdate(...a),
    getTickets: (...a: unknown[]) => mockAfterSalesList(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import OrderUrgencyPanel from '@/components/orders/OrderUrgencyPanel'
import type { Order } from '@/types'

const order = (over: Partial<Order> = {}): Order =>
  ({
    id: 'order-001',
    orderNo: 'MG-0001',
    status: 'pending_shipment',
    totalAmount: 299,
    actualAmount: 299,
    customerName: '测试客户',
    customerPhone: '13800000000',
    hasProcessing: false,
    ...over,
  }) as Order

const dateInput = () => screen.getByLabelText('要求到货日') as HTMLInputElement
/** 加急开关 = `role="switch"` 的按钮 ⇒ 状态读 `aria-checked`（不是 `checked`） */
const urgentSwitch = () => screen.getByLabelText('加急')
const isUrgentOn = () => urgentSwitch().getAttribute('aria-checked') === 'true'

describe('OrderUrgencyPanel（PR-079）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUpdateUrgency.mockResolvedValue({ data: { success: true, data: null } })
  })

  it('缺省不变：服务端为「不加急 / 未指定」时，勾选框**不勾**、日期框为空', () => {
    render(<OrderUrgencyPanel order={order({ isUrgent: false, requiredDeliveryDate: null })} onChanged={vi.fn()} />)

    expect(isUrgentOn()).toBe(false)
    expect(dateInput().value).toBe('')
    expect(screen.getByTestId('order-urgency-badge').textContent).toBe('不加急')
  })

  it('字段整体缺席（老响应）也按「不加急 / 未指定」渲染 —— 不默认勾上', () => {
    render(<OrderUrgencyPanel order={order()} onChanged={vi.fn()} />)
    expect(isUrgentOn()).toBe(false)
    expect(dateInput().value).toBe('')
  })

  it('勾上加急 + 填到货日 ⇒ PUT 只带这两个键（**没有第三个键**，零联动）', async () => {
    render(<OrderUrgencyPanel order={order({ isUrgent: false, requiredDeliveryDate: null })} onChanged={vi.fn()} />)

    fireEvent.click(urgentSwitch())
    fireEvent.change(dateInput(), { target: { value: '2026-09-30' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(mockUpdateUrgency).toHaveBeenCalledTimes(1))
    expect(mockUpdateUrgency.mock.calls[0][0]).toBe('order-001')
    // 🔴 键集**精确相等**：多一个 `priority`（售后字段）或别的键都会让这条红
    expect(mockUpdateUrgency.mock.calls[0][1]).toEqual({
      isUrgent: true,
      requiredDeliveryDate: '2026-09-30',
    })
    // 零联动：售后 API 一次都不许被碰
    expect(mockAfterSalesUpdate).not.toHaveBeenCalled()
    expect(mockAfterSalesList).not.toHaveBeenCalled()
  })

  it('结果可见：保存后服务端回「已加急」⇒ 徽标变「加急」；再取消 ⇒ 徽标变回「不加急」', async () => {
    /** 带「重新拉单」语义的父级：保存成功后把 order 换成服务端最新值（页面上的可见结果） */
    function Harness() {
      const [current, setCurrent] = useState(order({ isUrgent: false, requiredDeliveryDate: null }))
      return (
        <OrderUrgencyPanel
          order={current}
          onChanged={() =>
            // 模拟 loadOrder()：服务端现在回的是加急=true / 到货日=2026-09-30
            setCurrent(order({ isUrgent: true, requiredDeliveryDate: '2026-09-30' }))
          }
        />
      )
    }
    render(<Harness />)

    expect(screen.getByTestId('order-urgency-badge').textContent).toBe('不加急')

    fireEvent.click(urgentSwitch())
    fireEvent.change(dateInput(), { target: { value: '2026-09-30' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    // **用户可见结果**：徽标真的变了（不是「API 被调用过」）
    await waitFor(() => expect(screen.getByTestId('order-urgency-badge').textContent).toBe('加急'))
    expect(dateInput().value).toBe('2026-09-30')
    expect(toast.success).toHaveBeenCalled()
  })

  it('取消加急：勾选框取消后保存 ⇒ 请求体 isUrgent:false，服务端回「不加急」时徽标**消失**', async () => {
    function Harness() {
      const [current, setCurrent] = useState(order({ isUrgent: true, requiredDeliveryDate: '2026-09-30' }))
      return (
        <OrderUrgencyPanel
          order={current}
          onChanged={() => setCurrent(order({ isUrgent: false, requiredDeliveryDate: null }))}
        />
      )
    }
    render(<Harness />)

    // 初值来自服务端：已加急
    await waitFor(() => expect(screen.getByTestId('order-urgency-badge').textContent).toBe('加急'))
    expect(isUrgentOn()).toBe(true)

    fireEvent.click(urgentSwitch())
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(mockUpdateUrgency).toHaveBeenCalledTimes(1))
    expect(mockUpdateUrgency.mock.calls[0][1]).toEqual({
      isUrgent: false,
      requiredDeliveryDate: '2026-09-30',
    })
    // 🔴 徽标**消失**（变成「不加急」）—— 这条是「字段/服务端值缺失就红」的反空断言
    await waitFor(() => expect(screen.getByTestId('order-urgency-badge').textContent).toBe('不加急'))
  })

  it('清空到货日：日期框清空后保存 ⇒ `requiredDeliveryDate: \'\'`（清空 ≠ 不改）', async () => {
    render(<OrderUrgencyPanel order={order({ isUrgent: false, requiredDeliveryDate: '2026-09-30' })} onChanged={vi.fn()} />)

    expect(dateInput().value).toBe('2026-09-30')
    fireEvent.change(dateInput(), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(mockUpdateUrgency).toHaveBeenCalledTimes(1))
    expect(mockUpdateUrgency.mock.calls[0][1]).toEqual({
      isUrgent: false,
      requiredDeliveryDate: '',
    })
  })

  it('保存失败：不上报 onChanged（徽标不假装成功），并给出错误提示', async () => {
    mockUpdateUrgency.mockRejectedValueOnce(new Error('到货日格式不正确'))
    const onChanged = vi.fn()

    render(<OrderUrgencyPanel order={order({ isUrgent: false, requiredDeliveryDate: null })} onChanged={onChanged} />)
    fireEvent.click(urgentSwitch())
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(mockUpdateUrgency).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(onChanged).not.toHaveBeenCalled())
    // 拦截器已 toast 的用真实实现兜底；这里 mock 了 sonner ⇒ 至少要有一次 error 提示
    expect(toast.error).toHaveBeenCalled()
  })
})
