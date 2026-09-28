// case_ids: UI-062
// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, cleanup } from '@testing-library/react'

const mockGetPaymentQrcodes = vi.fn()
vi.mock('@/lib/api', () => ({
  settingsApi: { getPaymentQrcodes: (...args: unknown[]) => mockGetPaymentQrcodes(...args) },
}))

import { usePaymentQrcodes } from '@/lib/use-payment-qrcodes'
import type { PaymentQrcodeMap } from '@/types'

/**
 * 收款码读取口（**单一实现**，issue #5651 抽取）—— 报价单（#4965）与销售单（#5651）的
 * 「扫码支付」块共用这一份。抽出来的理由：同一件事实两处各写一次 ⇒ 将来改一处、
 * 另一处静默不一致，而纸面不一致 = 客户扫了打不开的码。
 *
 * 判据（四条，逐条对应 hook 文件头的口径）：
 * ① 调用方注入 ⇒ **直接用**，一次请求都不发（注入优先，测试与调用方都能控）；
 * ② 没注入 ⇒ **打印时**才取（`beforeprint`）—— 组件在详情页常驻挂载，挂载即拉会在
 *    每次打开详情页都发请求，而绝大多数打开并不打印；
 * ③ 失败 / 抛错 / 空响应 ⇒ 一律 `{}`（调用方据此**整块不出现**：🔴 缺码不画假码）；
 * ④ 卸载后移除监听（否则离开页面后每次打印仍会发请求，且可能对已卸载组件 setState）。
 */
describe('usePaymentQrcodes（收款码读取口 · 单一实现，issue #5651）', () => {
  beforeEach(() => {
    mockGetPaymentQrcodes.mockReset()
  })

  it('① 调用方注入 ⇒ 直接用，不发任何请求', () => {
    const provided: PaymentQrcodeMap = {
      wechat: { paymentType: 'wechat', imageUrl: '/uploads/qr.png', payeeName: '亿家纺织' },
    }
    const { result } = renderHook(() => usePaymentQrcodes(provided))
    expect(result.current).toBe(provided)
    expect(mockGetPaymentQrcodes).not.toHaveBeenCalled()
  })

  it('② 未注入 ⇒ 挂载时**不**取，`beforeprint` 时才取（打印时点）', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: { data: { alipay: { imageUrl: '/uploads/a.png' } } } })
    const { result } = renderHook(() => usePaymentQrcodes())
    // 挂载即拉 = 每次打开详情页都发请求（而绝大多数打开并不打印）⇒ 挂载时必须零请求
    expect(mockGetPaymentQrcodes).not.toHaveBeenCalled()
    expect(result.current).toEqual({})
    await act(async () => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    expect(mockGetPaymentQrcodes).toHaveBeenCalledTimes(1)
    expect(result.current).toEqual({ alipay: { imageUrl: '/uploads/a.png' } })
  })

  it('③ 请求失败（无权限 / 网络）⇒ 空 map（调用方整块不出现，不画假码）', async () => {
    mockGetPaymentQrcodes.mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => usePaymentQrcodes())
    await act(async () => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    expect(result.current).toEqual({})
  })

  it('③ 同步抛错（环境未就绪）同样按「无码」处理，不冒泡', async () => {
    mockGetPaymentQrcodes.mockImplementation(() => {
      throw new Error('boom')
    })
    const { result } = renderHook(() => usePaymentQrcodes())
    await act(async () => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    expect(result.current).toEqual({})
  })

  it('③ 响应体缺 data 层 ⇒ 空 map（不把 undefined 透给调用方）', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: undefined })
    const { result } = renderHook(() => usePaymentQrcodes())
    await act(async () => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    expect(result.current).toEqual({})
  })

  it('④ 卸载后移除监听：再触发 beforeprint 不再发请求', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: { data: {} } })
    const { unmount } = renderHook(() => usePaymentQrcodes())
    unmount()
    await act(async () => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    expect(mockGetPaymentQrcodes).not.toHaveBeenCalled()
    cleanup()
  })
})
