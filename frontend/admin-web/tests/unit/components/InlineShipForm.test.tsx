// case_ids: OR-001, OR-002, OR-003, OR-004, OR-005, OR-058, UI-057, UI-058, UI-130
/**
 * 行内快捷发货录入区（`InlineShipForm`）的**组件级**判据（issue #8013）。
 *
 * 页面级判据（不跳页 / 展开位置 / 列表刷新 / 行状态更新）在
 * `frontend/admin-web/tests/unit/pages/orders-inline-ship.test.tsx`；本文件只钉**这个组件自己**的契约
 * （QA Growth Gate 要求每个新增源码文件有同路径测试，见 `.github/tech-stack.yml` 的 admin-web 规则）：
 *
 * ① 与服务端**同口径**的前端预校验：显式 `shippingMethod=logistics` + 空运单号 ⇒ 行内报错、**不提交**；
 * ② 提交成功 ⇒ 只调一次原子发货端点、payload 四键齐、**通知页面**（`onShipped`）——
 *    组件**不自己**刷新列表、不自己跳页（那是页面的职责）；
 * ③ **幂等键语义**：失败后重试**复用同值**（服务端同键回放，不会发两次货）；成功后作废（下一单拿新键）；
 * ④ `shippingMethod=none`（无需物流）⇒ 单号 / 承运商字段不渲染，空单号**直接提交**（不被错拦）；
 * ⑤ 失败（4xx）⇒ 输入原样保留 + **行内**错误文案（服务端原文优先），不弹独占式 toast；
 * ⑥ `Escape` 触发 `onClose`（键盘可达）。
 *
 * **红证**（实现前 / 回退时）：去掉空单号拦截 ⇒ ① 红；成功后不清键 ⇒ ③ 的「新键」红；
 * 失败分支里重建键 ⇒ ③ 的「复用同值」红；`none` 也要求单号 ⇒ ④ 红；失败清空输入 ⇒ ⑤ 红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

// 发货人默认当前登录人（不是「管理员」这类角色名）
const authMock = vi.hoisted(() => ({
  state: { user: { id: '1', username: 'admin', name: '王师傅', permissions: ['*'], roles: [] } },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

const shipApi = vi.hoisted(() => ({ shipOrder: vi.fn() }))
vi.mock('@/lib/api', () => ({ productionApi: shipApi }))

import InlineShipForm from '@/components/orders/InlineShipForm'
import type { OrderBrief } from '@/types'

const ORDER = {
  id: 'order-1',
  orderNo: 'MG-0001',
  status: 'pending_shipment',
} as unknown as OrderBrief

function renderForm() {
  const onClose = vi.fn()
  const onShipped = vi.fn()
  render(<InlineShipForm order={ORDER} onClose={onClose} onShipped={onShipped} />)
  return { onClose, onShipped }
}

function submit() {
  fireEvent.click(screen.getByRole('button', { name: '确认发货' }))
}

describe('InlineShipForm · 行内快捷发货录入区（issue #8013）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    shipApi.shipOrder.mockResolvedValue({ data: { data: { order_id: 'order-1', status: 'shipped' } } })
  })

  it('① 默认态：物流发货 + 发货人默认当前登录人；空运单号 ⇒ 行内报错且不提交', async () => {
    const { onShipped } = renderForm()

    expect((screen.getByTestId('ship-inline-shipper') as HTMLInputElement).value).toBe('王师傅')
    expect((screen.getByLabelText('物流方式') as HTMLSelectElement).value).toBe('logistics')
    expect(screen.getByLabelText('运单号')).toBeInTheDocument()

    submit()

    expect(screen.getByTestId('ship-inline-error').textContent).toContain('快递单号')
    expect(shipApi.shipOrder).not.toHaveBeenCalled()
    expect(onShipped).not.toHaveBeenCalled()

    // 开始输入 ⇒ 旧错误立即退场（不把一个已修好的错误留在屏上）
    fireEvent.change(screen.getByLabelText('运单号'), { target: { value: 'SF1' } })
    expect(screen.queryByTestId('ship-inline-error')).toBeNull()
  })

  it('② 提交成功 ⇒ 只调一次、payload 四键齐、通知页面；成功后**换新**幂等键', async () => {
    const { onShipped } = renderForm()

    fireEvent.change(screen.getByLabelText('运单号'), { target: { value: 'SF1234567890' } })
    fireEvent.change(screen.getByLabelText('物流公司'), { target: { value: '顺丰速运' } })
    submit()

    await waitFor(() => expect(shipApi.shipOrder).toHaveBeenCalledTimes(1))
    const [orderId, payload, firstKey] = shipApi.shipOrder.mock.calls[0]
    expect(orderId).toBe('order-1')
    expect(payload).toEqual(
      expect.objectContaining({
        company: '顺丰速运',
        trackingNo: 'SF1234567890',
        shippingMethod: 'logistics',
        shipperName: '王师傅',
      }),
    )
    expect(typeof firstKey).toBe('string')
    await waitFor(() => expect(onShipped).toHaveBeenCalledTimes(1))

    // 成功后作废：同一屏再发一单（模拟下一件发货）必须拿**新**键
    submit()
    await waitFor(() => expect(shipApi.shipOrder).toHaveBeenCalledTimes(2))
    expect(shipApi.shipOrder.mock.calls[1][2]).not.toBe(firstKey)
  })

  it('③ 失败后重试 ⇒ **复用同一个**幂等键（服务端同键回放，不会发两次货）', async () => {
    // 🔴 两次都失败：这一次要证的是「重试复用同值」，不是「重试会成功」
    shipApi.shipOrder.mockRejectedValue({
      isAxiosError: true,
      response: { status: 500, data: { error: { message: '服务端出错了，请稍后重试' } } },
    })
    const { onShipped } = renderForm()

    fireEvent.change(screen.getByLabelText('运单号'), { target: { value: 'SF-FAIL-001' } })
    submit()
    await waitFor(() => expect(shipApi.shipOrder).toHaveBeenCalledTimes(1))
    const firstKey = shipApi.shipOrder.mock.calls[0][2]

    submit()
    await waitFor(() => expect(shipApi.shipOrder).toHaveBeenCalledTimes(2))
    expect(shipApi.shipOrder.mock.calls[1][2]).toBe(firstKey)
    // 两次都没成功 ⇒ 一次都不通知页面（写了 0 行，别假装成功）
    expect(onShipped).not.toHaveBeenCalled()
  })

  it('④ `shippingMethod=none` ⇒ 单号 / 承运商字段不渲染，空单号直接提交', async () => {
    renderForm()

    fireEvent.change(screen.getByLabelText('物流方式'), { target: { value: 'none' } })
    expect(screen.queryByLabelText('运单号')).toBeNull()
    expect(screen.queryByLabelText('物流公司')).toBeNull()
    expect(screen.queryByTestId('ship-inline-error')).toBeNull()

    submit()

    await waitFor(() => expect(shipApi.shipOrder).toHaveBeenCalledTimes(1))
    expect(shipApi.shipOrder.mock.calls[0][1]).toEqual(
      expect.objectContaining({ shippingMethod: 'none', trackingNo: '', company: '' }),
    )
  })

  it('⑤ 失败 ⇒ 输入原样保留、服务端原文在行内可见、不通知页面', async () => {
    shipApi.shipOrder.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 422, data: { error: { message: '作业单未完成，不能发货' } } },
    })
    const { onShipped } = renderForm()

    fireEvent.change(screen.getByLabelText('运单号'), { target: { value: 'SF-KEEP-001' } })
    submit()

    await waitFor(() =>
      expect(within(screen.getByTestId('ship-inline-form')).getByTestId('ship-inline-error').textContent).toBe(
        '作业单未完成，不能发货',
      ),
    )
    expect((screen.getByLabelText('运单号') as HTMLInputElement).value).toBe('SF-KEEP-001')
    expect(onShipped).not.toHaveBeenCalled()
  })

  it('⑥ `Escape` ⇒ 收起（`onClose` 一次），且不触发任何提交', () => {
    const { onClose } = renderForm()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(shipApi.shipOrder).not.toHaveBeenCalled()
  })
})
