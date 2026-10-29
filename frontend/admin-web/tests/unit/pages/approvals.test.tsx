// case_ids: APV-001
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import ApprovalsPage, { actionsFor } from '@/app/(dashboard)/approvals/page'

/**
 * 审批中心页面（issue #7374，P1-2 的商家面）。
 *
 * 守三件事（与后端判据一一对应）：
 * 1. **只对「待审」给裁决按钮** —— 已通过/已驳回/已撤回的行不给按钮（服务端 CAS 也会拒，
 *    但让能点的都失败是坏界面）；
 * 2. **批一次用一次**：通过后被业务用掉（`consumedAt` 非空）要单独标「已使用」，
 *    不让「已通过」被读成「还能再批一次」；
 * 3. **服务端拒绝原话上屏**：自批 / 已裁决过 / 非本人撤回 —— 都是服务端判定，不吞成「操作失败」。
 */
const approvalApi = vi.hoisted(() => ({
  list: vi.fn(),
  detail: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  withdraw: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ approvalApi }))
vi.mock('@/lib/permission', () => ({
  usePermission: () => ({ has: () => true, permissions: [], isAdmin: true }),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

// 当前登录人（撤回只对申请人本人显形）
const authState = vi.hoisted(() => ({ userId: 'u-me' as string | null }))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) => {
    const state = { user: authState.userId ? { id: authState.userId } : null }
    return typeof selector === 'function' ? selector(state) : state
  },
}))

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

const PENDING = {
  id: 'ap1',
  objectType: 'price_change',
  objectRef: 'sku-1',
  objectLabel: '遮光布 米白 2.8m',
  amount: 1200,
  payload: null,
  reason: '客户要 3% 折扣',
  status: 'pending' as const,
  requestedBy: 'u-other',
  requestedByName: '王小美',
  requestedAt: '2026-10-23T10:00:00+08:00',
  decidedBy: null,
  decidedByName: null,
  decidedAt: null,
  decisionNote: null,
  consumedAt: null,
  consumedRef: null,
}

const APPROVED = {
  ...PENDING,
  id: 'ap2',
  status: 'approved' as const,
  requestedBy: 'u-me',
  decidedBy: 'u-boss',
  decidedByName: '李经理',
  decidedAt: '2026-10-23T11:00:00+08:00',
  decisionNote: '可以',
}

const CONSUMED = { ...APPROVED, id: 'ap3', consumedAt: '2026-10-23T11:30:00+08:00', consumedRef: 'SO-1' }

/**
 * 行内「⋯」菜单的开合（issue #8039）：`驳回` / `撤回` 收进菜单，
 * **收起态不进 DOM** —— 页面判据因此必须先点触发器。
 */
const openRowMenu = (rowId: string) => {
  fireEvent.click(
    within(screen.getByTestId(`approval-row-menu-${rowId}`)).getByRole('button', { name: '更多操作' }),
  )
}

describe('审批中心页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.userId = 'u-me'
    approvalApi.list.mockImplementation(() => wrap([]))
  })

  it('🟢 动作矩阵：只对「待审」给动作；无写权只剩本人撤回；已使用则不给裁决', () => {
    // 待审 + 有写权 + 非本人
    expect(actionsFor('pending', true, false, null)).toEqual(['approve', 'reject'])
    // 待审 + 无写权 + 本人 ⇒ 只能撤回
    expect(actionsFor('pending', false, true, null)).toEqual(['withdraw'])
    // 待审 + 无写权 + 非本人 ⇒ 什么都不给
    expect(actionsFor('pending', false, false, null)).toEqual([])
    // 已使用（consumedAt 非空）⇒ 连裁决也不行
    expect(actionsFor('pending', true, false, '2026-10-23T11:30:00+08:00')).toEqual([])
    // 已裁决三态一律没有动作
    expect(actionsFor('approved', true, true, null)).toEqual([])
    expect(actionsFor('rejected', true, true, null)).toEqual([])
    expect(actionsFor('withdrawn', true, true, null)).toEqual([])
  })

  it('没有审批单 ⇒ 空态（不是空表格）', async () => {
    render(<ApprovalsPage />)
    await waitFor(() => expect(screen.getByTestId('approvals-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('approvals-table')).toBeNull()
  })

  // issue #8056：加载态 = 通用表格骨架（#8036 / #8048 已验收口径），不再是裸「加载中…」+ 空白表体。
  it('加载中：渲染 table-skeleton，且不出现裸「加载中…」文案（#8056）', async () => {
    approvalApi.list.mockReturnValue(new Promise(() => {}))
    render(<ApprovalsPage />)
    expect(await screen.findByTestId('table-skeleton')).toBeInTheDocument()
    // 红证：把加载分支改回裸文案 ⇒ 本条红
    expect(screen.queryByText(/加载中/)).not.toBeInTheDocument()
  })

  it('🔴 已裁决的行不给通过/驳回按钮；待审行给', async () => {
    approvalApi.list.mockImplementation(() => wrap([PENDING, APPROVED]))
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approvals-table')).toBeInTheDocument())
    // 待审行：主行动 = 「通过」（#8039），`驳回` 收进 ⋯ 菜单（收起态不进 DOM）
    expect(screen.getByTestId('approval-approve-ap1')).toBeInTheDocument()
    expect(screen.queryByTestId('approval-reject-ap1')).toBeNull()
    openRowMenu('ap1')
    expect(screen.getByTestId('approval-reject-ap1')).toBeInTheDocument()
    // 已通过（且申请人是本人）⇒ 没有通过/驳回，也没有撤回（不是待审）；连 ⋯ 都不摆
    expect(screen.queryByTestId('approval-approve-ap2')).toBeNull()
    expect(screen.queryByTestId('approval-actions-ap2')).toBeNull()
    expect(screen.queryByTestId('approval-reject-ap2')).toBeNull()
    expect(screen.queryByTestId('approval-withdraw-ap2')).toBeNull()
  })

  it('🔴 批一次用一次：已被业务用掉的审批挂「已使用」，不再给动作', async () => {
    approvalApi.list.mockImplementation(() => wrap([CONSUMED]))
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approval-consumed-ap3')).toBeInTheDocument())
    expect(screen.getByTestId('approval-consumed-ap3').textContent).toContain('已使用')
    expect(screen.queryByTestId('approval-approve-ap3')).toBeNull()
  })

  it('撤回只对申请人本人显形', async () => {
    approvalApi.list.mockImplementation(() =>
      wrap([PENDING, { ...PENDING, id: 'ap4', requestedBy: 'u-me' }]),
    )
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approvals-table')).toBeInTheDocument())
    // 别人的申请：菜单里没有撤回（展开后才可判 —— 收起态本来就取不到）
    openRowMenu('ap1')
    expect(screen.queryByTestId('approval-withdraw-ap1')).toBeNull()
    // 自己的申请：菜单里有撤回
    openRowMenu('ap4')
    expect(screen.getByTestId('approval-withdraw-ap4')).toBeInTheDocument()
  })

  it('🟢 操作列 = 1 主行动 + ⋯ 菜单：每行可点 ≤ 2、收起态菜单项不进 DOM（#8039）', async () => {
    approvalApi.list.mockImplementation(() =>
      wrap([PENDING, { ...PENDING, id: 'ap4', requestedBy: 'u-me' }]),
    )
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approval-row-ap1')).toBeInTheDocument())

    // 别人的申请：主行动「通过」+ ⋯ 触发器 = 2 个可点（驳回藏在菜单里，不占平级）
    const other = screen.getByTestId('approval-actions-ap1')
    const otherClickable = within(other).getAllByRole('button')
    expect(otherClickable).toHaveLength(2)
    expect(otherClickable[0].textContent).toBe('通过')
    expect(within(other).queryByRole('menu')).toBeNull()

    // 本人的申请（可裁决 + 可撤回）：可点数仍是 2
    const own = screen.getByTestId('approval-actions-ap4')
    expect(within(own).getAllByRole('button')).toHaveLength(2)
    expect(within(own).queryByRole('menuitem')).toBeNull()
    expect(screen.queryByTestId('approval-withdraw-ap4')).toBeNull()

    // 展开后可达：驳回 / 撤回（收起态根本不进 DOM，不是 CSS 隐藏）
    openRowMenu('ap4')
    expect(within(own).getByRole('menu')).toBeInTheDocument()
    expect(within(own).getAllByRole('menuitem')).toHaveLength(2)
    expect(within(own).getByTestId('approval-reject-ap4')).toBeInTheDocument()
    expect(within(own).getByTestId('approval-withdraw-ap4')).toBeInTheDocument()

    // 危险动作（撤回）仍走原调用路径：菜单项不是死项
    fireEvent.click(within(own).getByTestId('approval-withdraw-ap4'))
    await waitFor(() => expect(approvalApi.withdraw).toHaveBeenCalledWith('ap4'))
  })

  it('🔴 驳回必须写原因（不写当场拦、不发请求）；通过可不写', async () => {
    approvalApi.list.mockImplementation(() => wrap([PENDING]))
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approval-approve-ap1')).toBeInTheDocument())
    // 驳回在 ⋯ 菜单里（#8039）：先展开再点；二次确认弹窗（Modal）一字未改
    openRowMenu('ap1')
    fireEvent.click(screen.getByTestId('approval-reject-ap1'))
    fireEvent.click(screen.getByTestId('approval-decide-submit'))

    await waitFor(() => expect(screen.getByTestId('approval-decide-error')).toBeInTheDocument())
    expect(screen.getByTestId('approval-decide-error').textContent).toContain('驳回要写一句为什么')
    expect(approvalApi.reject).not.toHaveBeenCalled()

    // 通过：不写原因也能提交
    fireEvent.click(screen.getByTestId('approval-approve-ap1'))
    fireEvent.click(screen.getByTestId('approval-decide-submit'))
    await waitFor(() => expect(approvalApi.approve).toHaveBeenCalledWith('ap1', undefined))
  })

  it('🔴 服务端拒绝原话上屏（不能给自己的申请裁决）', async () => {
    approvalApi.list.mockImplementation(() => wrap([PENDING]))
    approvalApi.approve.mockRejectedValue({
      response: { status: 400, data: { message: '不能裁决自己提交的申请' } },
    })
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approval-approve-ap1')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('approval-approve-ap1'))
    fireEvent.click(screen.getByTestId('approval-decide-submit'))

    await waitFor(() => expect(screen.getByTestId('approval-decide-error')).toBeInTheDocument())
    expect(screen.getByTestId('approval-decide-error').textContent).toContain('不能裁决自己提交的申请')
  })

  it('计数与筛选：类型/状态筛选只留对应行', async () => {
    approvalApi.list.mockImplementation(() => wrap([PENDING, APPROVED, CONSUMED]))
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approvals-counts')).toBeInTheDocument())
    const counts = screen.getByTestId('approvals-counts').textContent || ''
    expect(counts).toContain('待审 1 条')
    expect(counts).toContain('已通过 2 条')

    fireEvent.change(screen.getByTestId('approvals-filter-status'), { target: { value: 'pending' } })
    await waitFor(() => expect(screen.getByTestId('approval-row-ap1')).toBeInTheDocument())
    expect(screen.queryByTestId('approval-row-ap2')).toBeNull()

    // 类型筛选到「退款」⇒ 空态（本组没有退款类）
    fireEvent.change(screen.getByTestId('approvals-filter-type'), { target: { value: 'refund' } })
    await waitFor(() => expect(screen.getByTestId('approvals-empty')).toBeInTheDocument())
  })

  it('🔴 金额为空写「—」而不是 ¥0.00（没有金额约束 ≠ 金额为零）', async () => {
    approvalApi.list.mockImplementation(() => wrap([{ ...PENDING, amount: null }]))
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approval-row-ap1')).toBeInTheDocument())
    expect(screen.getByTestId('approval-row-ap1').textContent).toContain('—')
    expect(document.body.textContent).not.toContain('¥0.00')
  })

  it('加载失败 ⇒ 常驻失败态 + 可重试出口', async () => {
    approvalApi.list.mockRejectedValue({ response: { status: 500, data: {} } })
    render(<ApprovalsPage />)
    await waitFor(() => expect(screen.getByTestId('approvals-load-error')).toBeInTheDocument())
    expect(screen.getByTestId('approvals-load-error-retry')).toBeInTheDocument()
  })
})
