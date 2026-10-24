// case_ids: UI-005, APV-001
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import ApprovalBell from '@/components/layout/ApprovalBell'

/**
 * 顶栏「待审批」入口（issue #7593，用户 2026-10-24 裁定）。
 *
 * 守四件事（每条都会红）：
 * 1. **无 `finance:view` 不渲染**（负控：入口按读码门控，没这个码的岗位顶栏不该多一个图标）；
 * 2. **徽标 = 待审条数**（静态菜单项的病灶正是「0 条与 12 条长得一样」）；
 * 3. **面板封顶 5 条**（§31 P1 常驻面克制）+ **不摆内部码**（`price_change` 不上屏，§31 P3）；
 * 4. **「去审批中心 →」把用户带到 `/approvals`**（历史四档状态只有页面能给，面板不自称能裁决）。
 */
const approvalApi = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/lib/api', () => ({ approvalApi }))

const perm = vi.hoisted(() => ({ allowed: true }))
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({ has: () => perm.allowed, permissions: [], isAdmin: false }),
}))

const push = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

function pendingItem(i: number, over: Record<string, unknown> = {}) {
  return {
    id: `ap${i}`,
    objectType: 'price_change',
    objectRef: `sku-${i}`,
    objectLabel: `遮光布 ${i}`,
    amount: 1200,
    payload: null,
    reason: '客户要折扣',
    status: 'pending',
    requestedBy: 'u-other',
    requestedByName: '王小美',
    requestedAt: '2026-10-23T10:00:00+08:00',
    decidedBy: null,
    decidedByName: null,
    decidedAt: null,
    decisionNote: null,
    consumedAt: null,
    consumedRef: null,
    ...over,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  perm.allowed = true
  approvalApi.list.mockReturnValue(wrap([]))
})

describe('顶栏「待审批」入口（issue #7593）', () => {
  it('🔴 没有 `finance:view` ⇒ 整个入口不渲染（负控）', async () => {
    perm.allowed = false
    render(<ApprovalBell />)
    expect(screen.queryByTestId('approval-bell')).toBeNull()
    // 连请求都不该发（省一次无权限的 403）
    expect(approvalApi.list).not.toHaveBeenCalled()
  })

  it('🔴 徽标 = 待审条数；面板只摆前 5 条且**不出现内部码**', async () => {
    approvalApi.list.mockReturnValue(wrap(Array.from({ length: 7 }, (_, i) => pendingItem(i))))
    render(<ApprovalBell />)

    await waitFor(() => expect(screen.getByTestId('approval-bell-badge')).toHaveTextContent('7'))

    fireEvent.click(screen.getByTestId('approval-bell'))
    const items = await screen.findAllByTestId('approval-bell-item')
    // §31 P1：常驻面不随条数增长 ⇒ 面板封顶 5 条（第 6/7 条不渲染，不是 CSS 隐藏）
    expect(items).toHaveLength(5)
    // §31 P3：显示人话「改价」，不把 `price_change` 摆到商家面前
    expect(items[0]).toHaveTextContent('改价 · 遮光布 0')
    expect(screen.queryByText(/price_change/)).toBeNull()
    // 列表只请求待审一档（徽标数 = pending 条数，不掺「已通过」）
    expect(approvalApi.list).toHaveBeenCalledWith({ status: 'pending' })
  })

  it('没有待审 ⇒ 无徽标 + 面板空态文案（不是「加载中」冒充）', async () => {
    render(<ApprovalBell />)
    fireEvent.click(screen.getByTestId('approval-bell'))
    expect(await screen.findByTestId('approval-bell-empty')).toHaveTextContent('没有待审批的单据')
    expect(screen.queryByTestId('approval-bell-badge')).toBeNull()
  })

  it('「去审批中心 →」把用户带到 `/approvals` 并收起面板', async () => {
    approvalApi.list.mockReturnValue(wrap([pendingItem(0)]))
    render(<ApprovalBell />)
    await waitFor(() => expect(screen.getByTestId('approval-bell-badge')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('approval-bell'))
    fireEvent.click(await screen.findByTestId('approval-bell-viewall'))

    expect(push).toHaveBeenCalledWith('/approvals')
    expect(screen.queryByTestId('approval-bell-panel')).toBeNull()
  })

  it('列表接口失败 ⇒ 入口仍在、无徽标（顶栏不能因为一次网络抖动整块消失）', async () => {
    approvalApi.list.mockRejectedValue(new Error('boom'))
    render(<ApprovalBell />)
    await waitFor(() => expect(approvalApi.list).toHaveBeenCalled())
    expect(screen.getByTestId('approval-bell')).toBeInTheDocument()
    expect(screen.queryByTestId('approval-bell-badge')).toBeNull()
  })
})
