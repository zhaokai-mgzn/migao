// case_ids: APV-001
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

  it('🔴 已裁决的行不给通过/驳回按钮；待审行给', async () => {
    approvalApi.list.mockImplementation(() => wrap([PENDING, APPROVED]))
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approvals-table')).toBeInTheDocument())
    expect(screen.getByTestId('approval-approve-ap1')).toBeInTheDocument()
    expect(screen.getByTestId('approval-reject-ap1')).toBeInTheDocument()
    // 已通过（且申请人是本人）⇒ 没有通过/驳回，也没有撤回（不是待审）
    expect(screen.queryByTestId('approval-approve-ap2')).toBeNull()
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
    // 别人的申请：没有撤回
    expect(screen.queryByTestId('approval-withdraw-ap1')).toBeNull()
    // 自己的申请：有撤回
    expect(screen.getByTestId('approval-withdraw-ap4')).toBeInTheDocument()
  })

  it('🔴 驳回必须写原因（不写当场拦、不发请求）；通过可不写', async () => {
    approvalApi.list.mockImplementation(() => wrap([PENDING]))
    render(<ApprovalsPage />)

    await waitFor(() => expect(screen.getByTestId('approval-reject-ap1')).toBeInTheDocument())
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
