// case_ids: APV-002
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import RequestApprovalModal from '@/components/approvals/RequestApprovalModal'
import { stocktakeDiffDraft } from '@/lib/approval-request'

/**
 * 「申请审批」弹窗（issue #7374 段 3）。
 *
 * 守三件事：① 金额默认取**门槛本身**（不填就得让人自己想，填小了等于白批）；
 * ② 理由必填（审批的人要知道为什么该放行）；③ 服务端拒的原话上屏。
 */
const approvalApi = vi.hoisted(() => ({ submit: vi.fn() }))
vi.mock('@/lib/api', () => ({ approvalApi }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const DRAFT = stocktakeDiffDraft({ stocktakeNo: 'PD202610220001', diffTotal: -12.5 })

describe('申请审批弹窗', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    approvalApi.submit.mockResolvedValue({ data: { success: true, data: { id: 'ap-new' } } })
  })

  it('打开即预填：对象 = 盘点单号、金额 = 差异合计', async () => {
    render(<RequestApprovalModal open onClose={() => {}} draft={DRAFT} />)

    expect(screen.getByTestId('approval-request-target').textContent).toContain('PD202610220001')
    expect((screen.getByTestId('approval-request-amount') as HTMLInputElement).value).toBe('12.5')
    expect(screen.getByTestId('approval-request-amount-hint').textContent).toContain('12.5')
  })

  it('🔴 理由必填：不写当场拦、不发请求', async () => {
    render(<RequestApprovalModal open onClose={() => {}} draft={DRAFT} />)
    fireEvent.click(screen.getByTestId('approval-request-submit'))

    await waitFor(() => expect(screen.getByTestId('approval-request-error')).toBeInTheDocument())
    expect(screen.getByTestId('approval-request-error').textContent).toContain('为什么')
    expect(approvalApi.submit).not.toHaveBeenCalled()
  })

  it('提交：带上 objectType / objectRef / 金额 / 理由（ref 由调用方给，不许人肉输入）', async () => {
    const onSubmitted = vi.fn()
    const onClose = vi.fn()
    render(<RequestApprovalModal open onClose={onClose} draft={DRAFT} onSubmitted={onSubmitted} />)

    fireEvent.change(screen.getByTestId('approval-request-reason'), {
      target: { value: '盘库发现帘头受潮，实物已报废' },
    })
    fireEvent.click(screen.getByTestId('approval-request-submit'))

    await waitFor(() =>
      expect(approvalApi.submit).toHaveBeenCalledWith({
        objectType: 'stocktake_diff',
        objectRef: 'PD202610220001',
        objectLabel: 'PD202610220001',
        amount: 12.5,
        reason: '盘库发现帘头受潮，实物已报废',
      }),
    )
    expect(onSubmitted).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('金额留空 ⇒ 请求里不带 amount（不是传 0 —— 0 会让「金额 ≥ 门槛」恒不成立）', async () => {
    render(<RequestApprovalModal open onClose={() => {}} draft={{ ...DRAFT, defaultAmount: null }} />)

    fireEvent.change(screen.getByTestId('approval-request-reason'), { target: { value: '先提一版' } })
    fireEvent.click(screen.getByTestId('approval-request-submit'))

    await waitFor(() => expect(approvalApi.submit).toHaveBeenCalled())
    expect(approvalApi.submit.mock.calls[0][0]).not.toHaveProperty('amount')
  })

  it('🔴 服务端拒的原话上屏（同一对象已有待审申请）', async () => {
    approvalApi.submit.mockRejectedValue({
      response: { status: 400, data: { message: '这个对象已经有一条待审申请（ap-1），请先等裁决或撤回它' } },
    })
    render(<RequestApprovalModal open onClose={() => {}} draft={DRAFT} />)

    fireEvent.change(screen.getByTestId('approval-request-reason'), { target: { value: '再提一次' } })
    fireEvent.click(screen.getByTestId('approval-request-submit'))

    await waitFor(() => expect(screen.getByTestId('approval-request-error')).toBeInTheDocument())
    expect(screen.getByTestId('approval-request-error').textContent).toContain('已经有一条待审申请')
  })
})
