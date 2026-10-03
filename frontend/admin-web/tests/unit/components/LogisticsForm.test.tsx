// case_ids: UI-040, OR-058
// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LogisticsForm from '@/components/orders/LogisticsForm'

/**
 * LogisticsForm（编辑物流弹窗）—— 含发货单「经手人」（issue #3768 / UI-040）
 *
 * 关键语义：发货人回填已有值供纠正；**留空时提交空串**（由 buildLogisticsPayload 省略该字段），
 * 后端据此保留原发货人 —— 即「改运单号的人」不会被写成经手人。
 */

const baseProps = {
  open: true,
  onClose: vi.fn(),
  onSubmit: vi.fn().mockResolvedValue(undefined),
}

describe('LogisticsForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    baseProps.onSubmit = vi.fn().mockResolvedValue(undefined)
    baseProps.onClose = vi.fn()
  })

  it('打开时渲染物流公司/运单号/发货人三个字段', () => {
    render(<LogisticsForm {...baseProps} />)

    expect(screen.getByText('物流公司')).toBeInTheDocument()
    expect(screen.getByText('运单号')).toBeInTheDocument()
    expect(screen.getByText('发货人')).toBeInTheDocument()
  })

  it('open=false 时不渲染', () => {
    render(<LogisticsForm {...baseProps} open={false} />)

    expect(screen.queryByText('物流公司')).not.toBeInTheDocument()
  })

  it('回填 initialData（含已落库的发货人）', () => {
    render(
      <LogisticsForm
        {...baseProps}
        initialData={{
          company: '顺丰速运',
          trackingNo: 'SF1234567890',
          shippingMethod: 'logistics',
          shipperName: '李四',
        }}
      />
    )

    expect(screen.getByDisplayValue('顺丰速运')).toBeInTheDocument()
    expect(screen.getByDisplayValue('SF1234567890')).toBeInTheDocument()
    expect(screen.getByDisplayValue('李四')).toBeInTheDocument()
  })

  it('必填校验：物流公司与运单号为空时提示且不下发', async () => {
    const user = userEvent.setup()
    render(<LogisticsForm {...baseProps} />)

    await user.click(screen.getByRole('button', { name: '确认保存' }))

    expect(await screen.findByText('请输入物流公司')).toBeInTheDocument()
    expect(screen.getByText('请输入运单号')).toBeInTheDocument()
    expect(baseProps.onSubmit).not.toHaveBeenCalled()
    expect(baseProps.onClose).not.toHaveBeenCalled()
  })

  it('提交带 trimmed 发货人（可纠正经手人）', async () => {
    const user = userEvent.setup()
    render(<LogisticsForm {...baseProps} initialData={{ company: '顺丰速运', trackingNo: 'SF1', shippingMethod: 'logistics' }} />)

    await user.type(screen.getByPlaceholderText('发货单「经手人」；留空则保留原发货人'), '  王五  ')
    await user.click(screen.getByRole('button', { name: '确认保存' }))

    await waitFor(() =>
      expect(baseProps.onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ company: '顺丰速运', trackingNo: 'SF1', shipperName: '王五' })
      )
    )
    expect(baseProps.onClose).toHaveBeenCalled()
  })

  it('发货人留空时提交空串（后端保留原经手人，不写成当次操作人）', async () => {
    const user = userEvent.setup()
    render(
      <LogisticsForm
        {...baseProps}
        initialData={{ company: '顺丰速运', trackingNo: 'SF1', shippingMethod: 'logistics', shipperName: '' }}
      />
    )

    await user.click(screen.getByRole('button', { name: '确认保存' }))

    await waitFor(() =>
      expect(baseProps.onSubmit).toHaveBeenCalledWith(expect.objectContaining({ shipperName: '' }))
    )
  })

  it('提交失败时抛出以阻止自动关闭（父组件负责提示）', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockRejectedValue(new Error('boom'))
    render(
      <LogisticsForm
        {...baseProps}
        onSubmit={onSubmit}
        initialData={{ company: '顺丰速运', trackingNo: 'SF1', shippingMethod: 'logistics' }}
      />
    )

    await user.click(screen.getByRole('button', { name: '确认保存' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(baseProps.onClose).not.toHaveBeenCalled()
  })

  // ── 兼容性钉子（issue #6239 / OR-058）──────────────────────────────────────
  // 后端新增了「shippingMethod=logistics 且运单号为空 ⇒ 422」这条服务端规则。
  // 本弹窗是它**必须不打断**的路径：运单号必填 + 回填已存值 ⇒ 永远带非空运单号过来。
  // 别人若把这个弹窗改成允许空运单号提交，这一条会当场红（下面这条即该契约的前端承载体）。
  it('编辑物流路径的提交契约：运单号必填 ⇒ 永远带非空运单号 + logistics 提交（不会踩后端新校验）', async () => {
    const user = userEvent.setup()
    render(
      <LogisticsForm
        {...baseProps}
        initialData={{ company: '顺丰速运', trackingNo: 'SFOLD', shippingMethod: 'logistics' }}
      />
    )

    await user.click(screen.getByRole('button', { name: '确认保存' }))

    await waitFor(() => expect(baseProps.onSubmit).toHaveBeenCalledTimes(1))
    const submitted = (baseProps.onSubmit as any).mock.calls[0][0]
    expect(submitted.shippingMethod).toBe('logistics')
    expect(submitted.trackingNo.trim().length).toBeGreaterThan(0)
  })

  it('运单号留空 ⇒ 前端拦下、不调 onSubmit（与后端新校验同一条口径）', async () => {
    const user = userEvent.setup()
    render(
      <LogisticsForm
        {...baseProps}
        initialData={{ company: '顺丰速运', trackingNo: '', shippingMethod: 'logistics' }}
      />
    )

    await user.click(screen.getByRole('button', { name: '确认保存' }))

    await waitFor(() => expect(screen.getByText('请输入运单号')).toBeTruthy())
    expect(baseProps.onSubmit).not.toHaveBeenCalled()
  })
})
