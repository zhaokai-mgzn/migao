// case_ids: OR-053
//
// OR-053（issue #5835）：订单列表的**制单人**列 + 按制单人**模糊**过滤。
//
// 用户 2026-09-30 逐字裁定：
//   ① 「制单人这个字段可以不用加到订单详情中，但是要加到订单列表中，并且支持根据制单人过滤」
//   ② 过滤控件 = **文本框模糊匹配**（不做下拉清单接口）
//   ③ 存量单（没有制单人）在列表里显示「**—**」，且**不参与**「按人」筛选
//
// ## 为什么单独一个文件
// `tests/unit/pages/orders.test.tsx` 把 `@/components/orders` **整体 mock** 掉了
// （`OrderTable` 换成了一个只渲染订单号/客户名的替身）⇒ 真表头与真单元格在那份 mock 下
// 根本不存在，本用例的两条渲染判据在那里**测不到**。这里**不 mock**
// `@/components/orders` 与 `@/types`，用真组件 + 真类型，端到端钉住「列表列 / 查询框 → 请求参数」。
//
// ## 断言的是**用户可见结果**（§15.1，不是「函数被调用过」）
//   ① 表头逐字有「制单人」列；行里渲染的是**后端给的**姓名（或「—」）；
//   ② 输入 + 查询 ⇒ 请求真的带 `creator`（且**不是**塞进 `keyword`）；
//   ③ 重置 ⇒ 输入框真的清空、搜索态真的回到满列表（不是「重置按钮被点过」）。
//
// 红证（实跑读数见 PR body）：
//   把 `apiParams.creator = search.creator` 删掉 ⇒ 判据 ② 红；
//   把 `order.createdByName || '—'` 改成恒渲染姓名 ⇒ 判据 ①b 红；
//   把 `setCreator('')` 从 `handleReset` 删掉 ⇒ 判据 ③ 红。
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockGetOrders = vi.fn()

// 只 mock「外部世界」（网络/路由），不 mock 被测组件与纯映射模块 —— 判据要跑真组件
const h = vi.hoisted(() => ({ params: new URLSearchParams() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => h.params,
  usePathname: () => '/orders',
}))
vi.mock('next/link', () => ({
  default: ({ children, ...props }: any) => <a {...props}>{children}</a>,
}))
vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrders: (...args: any[]) => mockGetOrders(...args),
    updateOrderStatus: vi.fn(),
    exportOrders: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() } }))

import OrdersPage from '@/app/(dashboard)/orders/page'

/** 两单：一单有制单人（快照），一单是存量单（`createdByName` 缺省 = 未采集）。 */
const ORDER_WITH_CREATOR = {
  id: 'order-with-creator',
  orderNo: 'MG202609300001',
  customerName: '张先生',
  status: 'pending',
  totalAmount: 1999,
  createdAt: '2026-09-30T10:00:00',
  createdByName: '蒋雪云',
}
const ORDER_WITHOUT_CREATOR = {
  id: 'order-legacy',
  orderNo: 'MG202609300002',
  customerName: '李女士',
  status: 'confirmed',
  totalAmount: 3500,
  createdAt: '2026-09-29T10:00:00',
  createdByName: null,
}

/** 列表请求的**最后一次**入参（判据只认最后一次，避免被挂载那次的请求顶掉）。 */
function lastParams(): Record<string, unknown> {
  return (mockGetOrders.mock.calls.at(-1)?.[0] ?? {}) as Record<string, unknown>
}

describe('订单列表 · 制单人列与过滤（issue #5835）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.params = new URLSearchParams()
    mockGetOrders.mockResolvedValue({
      data: { data: { items: [ORDER_WITH_CREATOR, ORDER_WITHOUT_CREATOR], total: 2 } },
    })
  })

  it('① 表头有「制单人」列，且行里渲染后端给的制单人姓名', async () => {
    render(<OrdersPage />)

    await waitFor(() => expect(screen.getByText('MG202609300001')).toBeInTheDocument())
    // 表头（判据 ① 的存在性半边）
    expect(screen.getByRole('columnheader', { name: '制单人' })).toBeInTheDocument()
    // 行里的**值**来自后端快照列，不是前端拼的
    expect(screen.getByTestId('order-creator-order-with-creator').textContent).toBe('蒋雪云')
  })

  it('② 存量单（未采集制单人）渲染「—」，不是空字符串', async () => {
    render(<OrdersPage />)

    await waitFor(() => expect(screen.getByText('MG202609300002')).toBeInTheDocument())
    const cell = screen.getByTestId('order-creator-order-legacy')
    expect(cell.textContent).toBe('—')
    // 反空跑：同一张表的另一行**确实**渲染了姓名 —— 否则「—」可能只是因为列根本没渲染
    expect(screen.getByTestId('order-creator-order-with-creator').textContent).toBe('蒋雪云')
  })

  it('③ 输入制单人 + 查询 ⇒ 请求带 `creator`（独立参数，不并入 keyword）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())
    const before = mockGetOrders.mock.calls.length

    const input = screen.getByPlaceholderText('请输入制单人姓名')
    fireEvent.change(input, { target: { value: '蒋' } })
    fireEvent.click(screen.getByRole('button', { name: /查询/ }))

    await waitFor(() => expect(mockGetOrders.mock.calls.length).toBeGreaterThan(before))
    const params = lastParams()
    expect(params.creator).toBe('蒋')
    // 🔴 `keyword` 后端匹配的是客户姓名 / 电话 / 订单号 —— 制单人**不得**塞进去
    //    （塞进去会把「制单人姓蒋」变成「客户姓蒋」⇒ 筛错对象）
    expect(params.keyword).toBeUndefined()
  })

  it('④ 重置 ⇒ 输入框清空、搜索态清空（请求不再带 `creator`）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const input = screen.getByPlaceholderText('请输入制单人姓名') as HTMLInputElement
    fireEvent.change(input, { target: { value: '蒋' } })
    fireEvent.click(screen.getByRole('button', { name: /查询/ }))
    await waitFor(() => expect(lastParams().creator).toBe('蒋'))

    fireEvent.click(screen.getByRole('button', { name: /重置/ }))

    await waitFor(() => expect(lastParams().creator).toBeUndefined())
    // 「重置」的结果对用户可见：输入框空了（不是「重置按钮被点过」）
    expect((screen.getByPlaceholderText('请输入制单人姓名') as HTMLInputElement).value).toBe('')
    // 反空跑：列表本身还在（否则「请求不带 creator」可能只是因为页面根本没在跑）
    expect(screen.getByText('MG202609300001')).toBeInTheDocument()
  })

  it('⑤ 反空跑：不填制单人 ⇒ 请求**不得**带 `creator`（缺省 = 不过滤）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(lastParams().creator).toBeUndefined()
    // 页面确实渲染了（否则上面的「没传」可能只是因为根本没跑起来）
    expect(screen.getByRole('columnheader', { name: '制单人' })).toBeInTheDocument()
  })
})
