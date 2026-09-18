// case_ids: PG-019
// PG-019（issue #4203）：生产模块菜单入口 + 生产看板页 ——
// ① 侧边栏出现「生产管理」组三个节点（生产看板 /production、工序库 /production/operations、
//    计件工资 /production/piecework，权限码统一 processing:manage）；
// ② /production 看板渲染**真实数据**（≥1 行加工单 + 每单工序进度 + 计件合计）。
// 反 placeholder：看板断言必须落到真实数据行，不能只断言页面存在。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'

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

describe('生产管理菜单入口（侧边栏）', () => {
  it('侧边栏出现「生产管理」组与三个节点，路径与权限码正确', () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />)

    const group = screen.getByText('生产管理').closest('.mb-4') as HTMLElement
    expect(group).toBeTruthy()
    const links = group.querySelectorAll('a')
    expect(links).toHaveLength(3)
    expect(links[0].textContent).toContain('生产看板')
    expect(links[0]).toHaveAttribute('href', '/production')
    expect(links[1].textContent).toContain('工序库')
    expect(links[1]).toHaveAttribute('href', '/production/operations')
    expect(links[2].textContent).toContain('计件工资')
    expect(links[2]).toHaveAttribute('href', '/production/piecework')
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

  it('权限码口径一致：生产管理组三项统一 processing:manage（与既有 menu.ts 口径一致）', () => {
    const group = menuGroups.find((g) => g.key === 'production')
    expect(group).toBeTruthy()
    expect(group!.children.map((c) => c.permissionCode)).toEqual([
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
    // 每单工序进度
    expect(screen.getByTestId('production-row-progress-po-1')).toHaveTextContent('36%')
    expect(screen.getByTestId('production-row-progress-po-1')).toHaveTextContent('4/11')
    expect(screen.getByTestId('production-row-progress-po-2')).toHaveTextContent('0%')
    // 每单计件合计
    expect(screen.getByTestId('production-row-piecework-po-1')).toHaveTextContent('¥17.00')
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
