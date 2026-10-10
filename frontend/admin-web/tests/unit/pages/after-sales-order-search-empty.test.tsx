// case_ids: AS-001
/**
 * 售后新建工单「关联订单」搜索**无结果时什么都不显示**（issue #6664 第 9 条）。
 *
 * 改前（缺陷形态）：`orderSearchResults.length > 0 &&` 直接短路 ⇒ 搜不到时界面上**只有搜索框**，
 * 用户不知道是「没搜」还是「没这条订单」，会反复点搜索按钮。
 * 判据：给出空态文案「没有找到匹配订单」；有结果时**不**出现该文案（两态互斥）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const h = vi.hoisted(() => ({ params: new URLSearchParams() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => h.params,
}))

const api = vi.hoisted(() => ({
  getTickets: vi.fn(),
  createTicket: vi.fn(),
  getOrders: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  afterSalesApi: { getTickets: api.getTickets, createTicket: api.createTicket },
  orderApi: { getOrders: api.getOrders },
}))

// lucide-react：**惰性代理** mock —— 只对**组件名形态**（首字母大写）返回 stub；
// 任意 key 都返回组件会让 `then` / Symbol 也变成 thenable ⇒ vitest 死等（实测整个 run 挂死）。
vi.mock('lucide-react', async (importOriginal) =>
  (await import('../helpers/lucide-mock')).lucideMock((await importOriginal()) as Record<string, unknown>))

import AfterSalesPage from '@/app/(dashboard)/after-sales/page'

describe('售后新建工单 - 搜订单无结果空态（issue #6664 第 9 条）', () => {
  beforeEach(() => {
    api.getTickets.mockReset()
    api.createTicket.mockReset()
    api.getOrders.mockReset()
    api.getTickets.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
  })

  async function openCreateModalAndSearch(user: ReturnType<typeof userEvent.setup>, keyword: string) {
    await user.click(screen.getByRole('button', { name: /新建工单/ }))
    const input = await screen.findByPlaceholderText('请输入订单号/客户姓名/手机号')
    await user.type(input, keyword)
    // 搜索按钮 = 搜索框同排的那个（输入框的 keydown 也走同一 handler，这里点按钮）
    const searchBtn = input.parentElement!.querySelector('button') as HTMLButtonElement
    await user.click(searchBtn)
    return input
  }

  it('① 搜索无结果 ⇒ 显示「没有找到匹配订单」（不是什么都不显示）', async () => {
    const user = userEvent.setup()
    api.getOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })

    render(<AfterSalesPage />)
    await openCreateModalAndSearch(user, '不存在的单号')

    expect(await screen.findByText(/没有找到匹配订单/)).toBeInTheDocument()
  })

  it('② 搜索有结果 ⇒ 列出订单，且**不**出现空态文案（两态互斥）', async () => {
    const user = userEvent.setup()
    api.getOrders.mockResolvedValue({
      data: { data: { items: [{ id: 'o-9', orderNo: 'CSO260101-0009', customerName: '李女士', totalAmount: 88 }], total: 1 } },
    })

    render(<AfterSalesPage />)
    await openCreateModalAndSearch(user, 'CSO260101-0009')

    expect(await screen.findByText('CSO260101-0009')).toBeInTheDocument()
    expect(screen.queryByText(/没有找到匹配订单/)).toBeNull()
  })

  it('③ 没搜过 ⇒ 不预先显示空态（空态只在「搜过且没结果」时出现）', async () => {
    const user = userEvent.setup()
    render(<AfterSalesPage />)

    await user.click(screen.getByRole('button', { name: /新建工单/ }))
    await screen.findByPlaceholderText('请输入订单号/客户姓名/手机号')

    expect(screen.queryByText(/没有找到匹配订单/)).toBeNull()
  })
})
