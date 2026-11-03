// case_ids: UI-119, MC-181
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 质检判定录入表单（`QualityCheckForm`，issue #7140 = #5652 的商家面）。
 *
 * ## 口径（本文件钉住的事，每条能单独变红）
 *
 * ① 默认判定 = **合格**；三态单选（合格 / 返工 / 报废）都在；
 * ② 🔴 **判定 ≠ 合格 ⇒ 必须点选一项原因字典项**（issue #7197 ①）：没选 ⇒ 当场具名提示 + **零网络**
 *    （服务端 422 才是真判据）；重点负控：**只写了自由补充**也算没选；
 * ③ **提交体逐字段正确**：`order_item_id` / `result` / `reason_code` /（可选）`reason`；
 *    判定为合格时**不带**这两个键（空串不塞给服务端）；
 * ④ 服务端下发的业务文案**原样显示**（不把 HTTP 状态码当商家文案）；没有业务文案才用兜底句；
 * ⑤ 提交成功后交给调用方（`onDone`）；「取消」只是收起表单（`onCancel`），**不发请求**；
 * ⑥ **呈现形态 = 弹窗**（issue #7160）：`role=dialog`，标题带上这一件成品帘的名字 ——
 *    旧形态是行内展开在列表最底部，点「录入判定」后视口内看不到任何变化（用户逐字：「不如弹窗」）；
 * ⑦ **字典项来自服务端**（`GET /quality-inspections/reasons`）：六项短语按钮逐条上屏、顺序照下发；
 *    读不到 ⇒ 如实说「读不到」，**不**拿本地假表顶上（本地表迟早与校验面漂开）。
 */

const mockCreate = vi.fn()
const mockReasons = vi.fn()

vi.mock('@/lib/api', () => ({
  qualityInspectionApi: {
    create: (...args: unknown[]) => mockCreate(...args),
    reasons: (...args: unknown[]) => mockReasons(...args),
  },
}))

import QualityCheckForm from '@/components/production/QualityCheckForm'

/** 服务端字典（顺序即界面顺序；「其它」在最后）。 */
const DICTIONARY = [
  { code: 'fabric_stain', label: '布面污渍' },
  { code: 'fabric_hole', label: '布料破洞' },
  { code: 'color_diff', label: '色差' },
  { code: 'size_mismatch', label: '尺寸不符' },
  { code: 'stitching_defect', label: '走线不良' },
  { code: 'other', label: '其它' },
]

/** 与 `qualityInspectionApi.reasons()` 的返回形状一致（axios 风格外壳 + ApiResponse）。 */
const reasonsOk = () => ({ data: { success: true, data: { items: DICTIONARY } } })

describe('质检判定录入表单', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCreate.mockResolvedValue({ data: { data: {} } })
    mockReasons.mockResolvedValue(reasonsOk())
  })

  it('① 三态单选都在，默认「合格」', () => {
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={() => {}} />)

    expect(screen.getByTestId('quality-result-pass')).toBeChecked()
    expect(screen.getByTestId('quality-result-rework')).not.toBeChecked()
    expect(screen.getByTestId('quality-result-scrap')).not.toBeChecked()
  })

  it('② 判定为报废而没选原因项 ⇒ 具名提示（列全可选原因）且零调用', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-scrap'))
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    const error = screen.getByTestId('quality-inspection-form-error')
    expect(error).toHaveTextContent('请先点选一项不合格原因')
    expect(error).toHaveTextContent('布面污渍')
    expect(error).toHaveTextContent('其它')
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('③ 🔴 只写自由补充、没点原因项 ⇒ 仍然拒（自由文本顶替不了字典项）', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-rework'))
    await user.type(screen.getByTestId('quality-inspection-reason'), '缝线开裂')
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    expect(screen.getByTestId('quality-inspection-form-error')).toHaveTextContent('请先点选一项不合格原因')
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('④ 点原因项 + 写补充后提交：请求体逐字段正确（reason_code 必带、reason 是补充）', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-9" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-rework'))
    await user.click(await screen.findByTestId('quality-reason-stitching_defect'))
    await user.type(screen.getByTestId('quality-inspection-reason'), '  右帘下摆  ')
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        order_item_id: 'item-9',
        result: 'rework',
        reason_code: 'stitching_defect',
        reason: '右帘下摆',
      }),
    )
  })

  it('⑤ 只点原因项、不写补充 ⇒ 请求体不带 reason 键（空串不送）', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-9" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-rework'))
    await user.click(await screen.findByTestId('quality-reason-fabric_stain'))
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        order_item_id: 'item-9',
        result: 'rework',
        reason_code: 'fabric_stain',
      }),
    )
  })

  it('⑥ 判定为合格 ⇒ 请求体不带原因键（也不显示原因区）', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-9" onDone={() => {}} onCancel={() => {}} />)

    expect(screen.queryByTestId('quality-inspection-reason')).toBeNull()
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledWith({ order_item_id: 'item-9', result: 'pass' }))
  })

  it('⑦ 服务端业务文案原样显示；成功后交给调用方', async () => {
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

  it('⑧「取消」只收起表单，不发请求', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={onCancel} />)

    await user.click(screen.getByRole('button', { name: '取消' }))

    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('⑨ 🔴 以弹窗呈现：role=dialog，标题写明是哪一件成品帘', () => {
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

  it('⑩ 原因项逐条来自服务端字典（顺序照下发，界面不另造一份）', async () => {
    const user = userEvent.setup()
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-rework'))

    for (const item of DICTIONARY) {
      expect(await screen.findByTestId(`quality-reason-${item.code}`)).toHaveTextContent(item.label)
    }
    // 判定 = 合格时不出原因区（少一屏噪音）
    const group = screen.getByRole('radiogroup', { name: '不合格原因' })
    expect(group).toBeInTheDocument()
  })

  it('⑪ 字典读不到 ⇒ 如实说「读不到」，不编假表；提交仍由服务端兜底', async () => {
    const user = userEvent.setup()
    mockReasons.mockRejectedValueOnce(new Error('network'))
    render(<QualityCheckForm orderItemId="item-1" onDone={() => {}} onCancel={() => {}} />)

    await user.click(screen.getByTestId('quality-result-rework'))

    expect(await screen.findByTestId('quality-reasons-error')).toHaveTextContent('不合格原因读不到')
    // 没有读出任何假字典项
    expect(screen.queryByTestId('quality-reason-fabric_stain')).toBeNull()
    // 仍然拦在本地（不白跑一趟）
    await user.click(screen.getByRole('button', { name: '提交判定' }))
    expect(mockCreate).not.toHaveBeenCalled()
  })
})
