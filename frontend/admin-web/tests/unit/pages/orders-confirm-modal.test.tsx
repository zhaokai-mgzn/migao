// case_ids: OR-001, UI-048
/**
 * 订单列表的两个确认动作（「确认付款」/「确认收货」）—— issue #6664 第 4 条。
 *
 * 改前（缺陷形态）：`window.confirm('确认已收到客户付款？')` —— 原生弹窗无理由/不可撤销说明，
 * 与仓内自研 `Modal`（UI-048 家族：删除二次确认改弹框）**同一个动作两个世界观**；
 * 且这两个动作**没有在飞行态**，连点会重复发请求。
 *
 * 本文件的独立价值：`tests/unit/pages/orders.test.tsx` 把 `OrderTable` 整体 mock 掉了
 * ⇒ 它**碰不到**这两个动作。这里渲染**真** `OrderTable`，把按钮路径真跑一遍。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

const authMock = vi.hoisted(() => ({
  state: { user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: [] } },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

const api = vi.hoisted(() => ({
  getOrders: vi.fn(),
  confirmPayment: vi.fn(),
  updateOrderStatus: vi.fn(),
  deleteOrder: vi.fn(),
  refundOrder: vi.fn(),
  addRemark: vi.fn(),
  closeOrder: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ orderApi: api }))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

// lucide-react：**惰性代理** mock —— 不逐个列图标（列不全会让 UI 组件一 import 就炸），
// 也不对任意 key 返回组件（`then` / Symbol 也被当组件会让 vitest 死等 ⇒ 实测整个 run 挂死）。
// 只对**组件名形态**（首字母大写）返回 stub，其余 key 原样返回 undefined。
vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

import OrdersPage from '@/app/(dashboard)/orders/page'

function order(over: Record<string, unknown>) {
  return {
    id: 'o-1',
    orderNo: 'CSO260101-0001',
    customerName: '张女士',
    status: 'pending_payment',
    totalAmount: 1000,
    createdAt: '2026-01-01T02:00:00Z',
    items: [],
    ...over,
  }
}

function listResolve(rows: any[]) {
  return Promise.resolve({ data: { data: { items: rows, total: rows.length } } })
}

describe('订单列表确认动作走自研 Modal（issue #6664 第 4 条）', () => {
  const confirmSpy = vi.fn(() => true)
  const alertSpy = vi.fn()

  beforeEach(() => {
    api.getOrders.mockReset()
    api.confirmPayment.mockReset()
    api.updateOrderStatus.mockReset()
    confirmSpy.mockClear()
    alertSpy.mockClear()
    // 原生弹窗在 jsdom 里会打「Not implemented」噪声，且本包要求**零** window.confirm / alert
    vi.spyOn(window, 'confirm').mockImplementation(confirmSpy as any)
    vi.spyOn(window, 'alert').mockImplementation(alertSpy as any)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('① 「确认付款」⇒ 弹自研 Modal（写明动作 + 不可撤销）；**零** window.confirm', async () => {
    api.getOrders.mockResolvedValue(listResolve([order({ status: 'pending_payment' })]))
    render(<OrdersPage />)

    fireEvent.click(await screen.findByText('确认付款'))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/确认付款|已收到客户付款/)).toBeInTheDocument()
    expect(within(dialog).getByText(/不可撤销|无法撤销|请确认/)).toBeInTheDocument()
    // 原生弹窗一次都不许出现
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('② 在飞行态：请求未落地时按钮 disabled，连点不会重复发请求', async () => {
    api.getOrders.mockResolvedValue(listResolve([order({ status: 'pending_payment' })]))
    let release: (v: any) => void = () => {}
    api.confirmPayment.mockImplementation(
      () => new Promise((resolve) => { release = resolve }),
    )
    render(<OrdersPage />)

    fireEvent.click(await screen.findByText('确认付款'))
    const dialog = await screen.findByRole('dialog')
    const confirmBtn = within(dialog).getByRole('button', { name: /确认/ })
    fireEvent.click(confirmBtn)

    // 在飞：按钮不可点（第二次点击不应再发请求）
    await waitFor(() => expect(api.confirmPayment).toHaveBeenCalledTimes(1))
    expect(within(dialog).getByRole('button', { name: /确认/ })).toBeDisabled()
    fireEvent.click(within(dialog).getByRole('button', { name: /确认/ }))
    expect(api.confirmPayment).toHaveBeenCalledTimes(1)

    release({ data: { success: true } })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('③ 取消 ⇒ 一个请求都不发（弹框是闸门，不是装饰）', async () => {
    api.getOrders.mockResolvedValue(listResolve([order({ status: 'pending_payment' })]))
    render(<OrdersPage />)

    fireEvent.click(await screen.findByText('确认付款'))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: /取消/ }))

    expect(api.confirmPayment).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('④ 「确认收货」同样走自研 Modal；**零** window.confirm / window.alert', async () => {
    api.getOrders.mockResolvedValue(listResolve([order({ status: 'shipped' })]))
    api.updateOrderStatus.mockResolvedValue({ data: { success: true } })
    render(<OrdersPage />)

    fireEvent.click(await screen.findByText('确认收货'))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/确认收货|客户已收到货物/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: /确认/ }))

    await waitFor(() =>
      expect(api.updateOrderStatus).toHaveBeenCalledWith('o-1', { status: 'completed' }),
    )
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(alertSpy).not.toHaveBeenCalled()
  })
})
