// case_ids: UI-119
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 质检判定录入表单（`QualityCheckForm`，issue #7140 = #5652 的商家面）。
 *
 * ## 口径（本文件钉住的事，每条能单独变红）
 *
 * ① 默认判定 = **合格**；三态单选（合格 / 返工 / 报废）都在；
 * ② 🔴 **判定 ≠ 合格 ⇒ 原因必填**：不填 ⇒ 当场具名提示 + **零网络**（不白跑一趟；服务端 422 才是真判据）；
 * ③ **提交体逐字段正确**：`order_item_id` / `result` / `reason`；判定为合格时**不带**空原因键；
 * ④ 服务端下发的业务文案**原样显示**（不把 HTTP 状态码当商家文案）；没有业务文案才用兜底句；
 * ⑤ 提交成功后交给调用方（`onDone`）；「取消」只是收起表单（`onCancel`），**不发请求**；
 * ⑥ **呈现形态 = 弹窗**（issue #7160）：`role=dialog`，标题带上这一件成品帘的名字 ——
 *    旧形态是行内展开在列表最底部，点「录入判定」后视口内看不到任何变化（用户逐字：「不如弹窗」）。
 */

const mockCreate = vi.fn()

vi.mock('@/lib/api', () => ({
  qualityInspectionApi: {
    create: (...args: unknown[]) => mockCreate(...args),
  },
}))

import QualityCheckForm from '@/components/production/QualityCheckForm'

describe('质检判定录入表单', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCreate.mockResolvedValue({ data: { data: {} } })
  })

  it('① 三态单选都在，默认「合格」', () => {
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={() => {}} />)

    expect(screen.getByTestId('quality-result-pass')).toBeChecked()
    expect(screen.getByTestId('quality-result-rework')).not.toBeChecked()
    expect(screen.getByTestId('quality-result-scrap')).not.toBeChecked()
  })

  it('② 判定为报废而原因留空 ⇒ 具名提示且零调用', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-scrap'))
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    expect(screen.getByTestId('quality-inspection-form-error')).toHaveTextContent('必须填写不合格原因')
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('③ 填原因后提交：请求体逐字段正确（含成品帘 id）', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-9" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-rework'))
    await user.type(screen.getByTestId('quality-inspection-reason'), '  缝线开裂  ')
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        order_item_id: 'item-9',
        result: 'rework',
        reason: '缝线开裂',
      }),
    )
  })

  it('④ 判定为合格 ⇒ 请求体不带原因键（空串不送）', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-9" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledWith({ order_item_id: 'item-9', result: 'pass' }))
  })

  it('⑤ 服务端业务文案原样显示；成功后交给调用方', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    mockCreate.mockRejectedValueOnce({
      response: { data: { error: { message: '成品帘不存在' } } },
    })
    render(<QualityCheckForm orderItemId="item-1" onDone={onDone} onCancel={() => {}} />)

    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() =>
      expect(screen.getByTestId('quality-inspection-form-error')).toHaveTextContent('成品帘不存在'),
    )
    expect(onDone).not.toHaveBeenCalled()

    // 第二次改成成功 ⇒ 调 onDone（证明表单只在成功时才收起）
    mockCreate.mockResolvedValueOnce({ data: { data: {} } })
    await user.click(screen.getByRole('button', { name: '提交判定' }))
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
  })

  it('⑥「取消」只收起表单，不发请求', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={onCancel} />)

    await user.click(screen.getByRole('button', { name: '取消' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('⑦ 🔴 以弹窗呈现：role=dialog，标题写明是哪一件成品帘', () => {
    render(
      <QualityCheckForm
        orderItemId="item-1"
        subject="布艺遮光帘A（米白）"
        onDone={() => {}}
        onCancel={() => {}}
      />,
    )

    expect(screen.getByRole('dialog', { name: '为「布艺遮光帘A（米白）」录入质检判定' })).toBeInTheDocument()
  })
})
