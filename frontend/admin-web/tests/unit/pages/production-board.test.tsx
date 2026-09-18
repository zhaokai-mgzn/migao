// case_ids: PG-019, PP-014
// PG-019（issue #4203）：生产模块菜单入口 + 生产看板页 ——
// ① 侧边栏出现「生产管理」组节点（生产看板 /production、工序库 /production/operations、
//    工艺路线 /production/routings、计件工资 /production/piecework，权限码统一 processing:manage）；
// ② /production 看板渲染**真实数据**（≥1 行加工单 + 每单工序进度 + 计件合计）。
// 反 placeholder：看板断言必须落到真实数据行，不能只断言页面存在。
// PP-014（issue #4307 前端半边）：菜单组新增第 4 项「工艺路线」—— 页面存在但侧边栏进不去
// 等于没交付；本文件的链接清单 + 权限码断言随之由三项改四项（红证：加项后旧断言即红）。
// PG-019 / issue #4360（分页 + 懒加载）：看板原先对**全部**加工单一次性扇出详情
// （1 + 2N 次 HTTP，100 单 = 201 请求）——本文件的请求数断言即该缺陷的红证锚点：
// ① 首屏只为当前页（默认 20）发详情请求；② 切页只为新页发；③ 切回已加载页不重复发；
// ④ 「刷新」显式清缓存并重取当前页。判据是**调用次数**，不是渲染结果（渲染不出请求扇出）。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockList = vi.fn()
const mockGetOrderOperations = vi.fn()
const mockGetPiecework = vi.fn()

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    list: (...args: unknown[]) => mockList(...args),
  },
  productionApi: {
    getOrderOperations: (...args: unknown[]) => mockGetOrderOperations(...args),
    getPiecework: (...args: unknown[]) => mockGetPiecework(...args),
  },
  briefingApi: {
    getConfig: vi.fn().mockResolvedValue({ data: { data: { enabled: false } } }),
  },
}))

// 侧边栏测试：模拟已登录的管理员（全权限）
vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({
    user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'], roles: ['admin'] },
  }),
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('@/components/ui/Logo', () => ({
  default: (props: any) => <span data-testid="logo" {...props} />,
}))

import ProductionBoardPage from '@/app/(dashboard)/production/page'
import Sidebar from '@/components/layout/Sidebar'
import { menuGroups } from '@/config/menu'

const ORDERS = [
  {
    id: 'po-1',
    orderId: 'order-uuid-1',
    orderNo: 'MG20260917001',
    processingOrderNo: 'JG-20260917-0001',
    customerName: '李四',
    status: 'in_processing' as const,
  },
  {
    id: 'po-2',
    orderId: 'order-uuid-2',
    orderNo: 'MG20260917002',
    processingOrderNo: 'JG-20260917-0002',
    customerName: '王五',
    status: 'generated' as const,
  },
]

const ok = (data: unknown) => ({ data: { success: true, data } })

// 100 张加工单：请求扇出缺陷的**最小可判规模**（100 单 = 200 次详情请求）
const MANY_ORDERS = Array.from({ length: 100 }, (_, i) => ({
  id: `po-${i + 1}`,
  orderId: `order-uuid-${i + 1}`,
  orderNo: `MG20260917${String(i + 1).padStart(3, '0')}`,
  processingOrderNo: `JG-20260917-${String(i + 1).padStart(4, '0')}`,
  customerName: `客户${i + 1}`,
  status: 'in_processing' as const,
}))

describe('生产管理菜单入口（侧边栏）', () => {
  it('侧边栏出现「生产管理」组与四个节点，路径与权限码正确', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)

    const group = screen.getByText('生产管理').closest('.mb-4') as HTMLElement
    expect(group).toBeTruthy()
    const links = group.querySelectorAll('a')
    // 4 项：生产看板 / 工序库 / 工艺路线（issue #4307 新增）/ 计件工资
    expect(links).toHaveLength(4)
    expect(links[0].textContent).toContain('生产看板')
    expect(links[0]).toHaveAttribute('href', '/production')
    expect(links[1].textContent).toContain('工序库')
    expect(links[1]).toHaveAttribute('href', '/production/operations')
    expect(links[2].textContent).toContain('工艺路线')
    expect(links[2]).toHaveAttribute('href', '/production/routings')
    expect(links[3].textContent).toContain('计件工资')
    expect(links[3]).toHaveAttribute('href', '/production/piecework')
  })

  it('「加工单」不搬家：仍留在「订单管理」组（避免动既有 IA）', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)

    const tradeGroup = screen.getByText('订单管理').closest('.mb-4') as HTMLElement
    expect(within(tradeGroup).getByText('加工单')).toBeInTheDocument()
    expect(within(tradeGroup).getByText('加工单').closest('a')).toHaveAttribute('href', '/processing-orders')
    // 生产管理组内不得出现「加工单」
    const productionGroup = screen.getByText('生产管理').closest('.mb-4') as HTMLElement
    expect(within(productionGroup).queryByText('加工单')).not.toBeInTheDocument()
  })

  it('权限码口径一致：生产管理组四项统一 processing:manage（与既有 menu.ts 口径一致）', () => {
    const group = menuGroups.find((g) => g.key === 'production')
    expect(group).toBeTruthy()
    expect(group!.children.map((c) => c.permissionCode)).toEqual([
      'processing:manage',
      'processing:manage',
      'processing:manage',
      'processing:manage',
    ])
  })
})

describe('生产看板页 /production', () => {
  beforeEach(() => {
    mockList.mockReset().mockResolvedValue(ok(ORDERS))
    mockGetOrderOperations.mockReset().mockImplementation((orderId: string) =>
      Promise.resolve(
        ok(
          orderId === 'order-uuid-1'
            ? { positions: [{ position_name: '布帘', operations: [] }], progress: { total: 11, done: 4, percent: 36 } }
            : { positions: [], progress: { total: 0, done: 0, percent: 0 } },
        ),
      ),
    )
    mockGetPiecework.mockReset().mockImplementation((orderId: string) =>
      Promise.resolve(ok(orderId === 'order-uuid-1' ? { total: 17, per_worker: {}, per_operation: [] } : { total: 0 })),
    )
  })

  it('渲染真实数据：≥1 行加工单 + 每单工序进度 + 计件合计', async () => {
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())

    // 两行都渲染（不是空壳）
    expect(screen.getAllByTestId(/^production-row-po-/)).toHaveLength(2)
    expect(screen.getByTestId('production-row-po-1')).toHaveTextContent('JG-20260917-0001')
    expect(screen.getByTestId('production-row-po-1')).toHaveTextContent('MG20260917001')
    // 每单工序进度（issue #4360：详情懒加载 ⇒ 行先渲染，进度/计件随后异步补齐）
    await waitFor(() => expect(screen.getByTestId('production-row-progress-po-1')).toHaveTextContent('36%'))
    expect(screen.getByTestId('production-row-progress-po-1')).toHaveTextContent('4/11')
    expect(screen.getByTestId('production-row-progress-po-2')).toHaveTextContent('0%')
    // 每单计件合计
    await waitFor(() => expect(screen.getByTestId('production-row-piecework-po-1')).toHaveTextContent('¥17.00'))
    expect(screen.getByTestId('production-row-piecework-po-2')).toHaveTextContent('¥0.00')
  })

  it('按加工单上的 orderId 拉工序进度与计件（复用既有端点）', async () => {
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())
    expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-1')
    expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-2')
    expect(mockGetPiecework).toHaveBeenCalledWith('order-uuid-1')
  })

  it('无加工单：空态提示，不报错', async () => {
    mockList.mockResolvedValue(ok([]))
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-board-empty')).toBeInTheDocument())
  })

  it('列表失败：错误提示 + 重试按钮', async () => {
    mockList.mockRejectedValueOnce(new Error('boom'))
    render(<ProductionBoardPage />)

    await waitFor(() => expect(screen.getByTestId('production-board-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-board-retry')).toBeInTheDocument()
  })
})

// ── issue #4360：请求扇出 ⇒ 分页 + 懒加载（判据 = HTTP 调用次数）──────────────
describe('生产看板页 /production 分页 + 懒加载（issue #4360）', () => {
  const PAGE_SIZE = 20
  const detailCalls = () => mockGetOrderOperations.mock.calls.length
  const rowCount = () => screen.getAllByTestId(/^production-row-po-/).length
  // 等「当前页详情都发完」：最后一次调用的 orderId 是页内第 N 条（默认 20）
  const waitPageLoaded = (last: number) =>
    waitFor(() => expect(mockGetOrderOperations).toHaveBeenCalledWith(`order-uuid-${last}`))

  beforeEach(() => {
    mockList.mockReset().mockResolvedValue(ok(MANY_ORDERS))
    mockGetOrderOperations.mockReset().mockImplementation((orderId: string) =>
      Promise.resolve(ok({ positions: [], progress: { total: 10, done: 3, percent: 30 } })),
    )
    mockGetPiecework.mockReset().mockImplementation((orderId: string) => Promise.resolve(ok({ total: 17 })))
  })

  it('100 张单首屏：只为当前页（20）发详情，不对 100 行扇出', async () => {
    render(<ProductionBoardPage />)

    await waitPageLoaded(PAGE_SIZE)
    expect(rowCount()).toBe(PAGE_SIZE)
    // 缺陷形态是 100 次（每单 1 次）；修复后 ≤ 页大小
    expect(detailCalls()).toBeLessThanOrEqual(PAGE_SIZE)
    expect(mockGetPiecework.mock.calls.length).toBeLessThanOrEqual(PAGE_SIZE)
    expect(detailCalls()).toBe(PAGE_SIZE)
    expect(mockGetOrderOperations).not.toHaveBeenCalledWith(`order-uuid-${PAGE_SIZE + 1}`)
  })

  it('切到第 2 页：只为第 2 页发详情（累计 = 2 × 页大小）', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)

    await user.click(screen.getByRole('button', { name: '2' }))

    await waitPageLoaded(PAGE_SIZE * 2)
    expect(detailCalls()).toBe(2 * PAGE_SIZE)
    expect(mockGetPiecework.mock.calls.length).toBe(2 * PAGE_SIZE)
    expect(rowCount()).toBe(PAGE_SIZE)
    expect(screen.getByTestId(`production-row-po-${PAGE_SIZE + 1}`)).toBeInTheDocument()
  })

  it('切回第 1 页：命中缓存，不重复请求', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)
    await user.click(screen.getByRole('button', { name: '2' }))
    await waitPageLoaded(PAGE_SIZE * 2)
    const before = detailCalls()

    await user.click(screen.getByRole('button', { name: '1' }))

    await waitFor(() => expect(screen.getByTestId('production-row-po-1')).toBeInTheDocument())
    expect(detailCalls()).toBe(before)
    expect(mockGetPiecework.mock.calls.length).toBe(before)
  })

  it('点「刷新」：清缓存并重新请求当前页', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)
    await user.click(screen.getByRole('button', { name: '2' }))
    await waitPageLoaded(PAGE_SIZE * 2)
    const before = detailCalls()

    await user.click(screen.getByRole('button', { name: /刷新/ }))

    await waitFor(() => expect(detailCalls()).toBe(before + PAGE_SIZE))
    expect(mockGetPiecework.mock.calls.length).toBe(before + PAGE_SIZE)
  })

  it('页大小可见可切：20 → 50 只为新页补发详情', async () => {
    const user = userEvent.setup()
    render(<ProductionBoardPage />)
    await waitPageLoaded(PAGE_SIZE)

    await user.selectOptions(screen.getByRole('combobox'), '50')

    await waitPageLoaded(50)
    expect(detailCalls()).toBe(50)
    expect(rowCount()).toBe(50)
    expect(screen.getByRole('combobox')).toHaveValue('50')
  })
})
