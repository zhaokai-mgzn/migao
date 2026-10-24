// case_ids: UI-135, UI-062
// @vitest-environment jsdom

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, cleanup } from '@testing-library/react'

const mockGetPaymentQrcodes = vi.fn()
vi.mock('@/lib/api', () => ({
  settingsApi: { getPaymentQrcodes: (...args: unknown[]) => mockGetPaymentQrcodes(...args) },
}))
import {
  usePaymentQrcodes,
  loadPaymentQrcodesOnce,
  peekPaymentQrcodes,
  __resetPaymentQrcodesCache,
} from '@/lib/use-payment-qrcodes'
import type { PaymentQrcodeMap } from '@/types'

/**
 * 收款码读取口（**单一实现**，issue #5651 抽取；取码时点与裁边 = issue #7536）。
 * 今天**只有报价单**（#4965）的「扫码支付」块用它（销售单的收款码已按 issue #7589 移除）——
 * 纸面不一致 = 客户扫了打不开的码。
 *
 * 判据（逐条对应 hook 文件头的口径）：
 * ① 调用方注入 ⇒ **直接用**，一次请求都不发；
 * ② **要出纸 / 正在预览才取**（`active`）—— 常驻挂载的屏幕态不取：那条请求要 `order:list`，
 *    在没有该权限的页面上会变成「一进页面弹一条 403」（#7536 的设计约束，与 #7285 同族）；
 * ③ **预览层也要有码**（issue #7536 的红证）：`inline` 实例挂载即取，**不再**等 `beforeprint`
 *    —— 旧实现只在 `beforeprint` 取，预览层根本不派发该事件 ⇒ 预览里永远没有码（用户报障原图）；
 * ④ 失败 / 抛错 / 空响应 ⇒ 一律 `{}`（调用方据此**整块不出现**：🔴 缺码不画假码）；
 * ⑤ 模块级缓存 ⇒ 多个实例 / 多次打印**共享一次请求**，且打印前能 `peek` 到那份 Promise。
 */
describe('usePaymentQrcodes（收款码读取口 · 单一实现，issue #5651 / #7536）', () => {
  beforeEach(() => {
    mockGetPaymentQrcodes.mockReset()
    __resetPaymentQrcodesCache()
    cleanup()
  })

  it('① 调用方注入 ⇒ 直接用，不发任何请求（连裁边都不做）', () => {
    const provided: PaymentQrcodeMap = {
      wechat: { paymentType: 'wechat', imageUrl: '/uploads/qr.png', payeeName: '亿家纺织' },
    }
    const { result } = renderHook(() => usePaymentQrcodes(provided, { active: true }))
    expect(result.current).toBe(provided)
    expect(mockGetPaymentQrcodes).not.toHaveBeenCalled()
  })

  it('② 未注入 + 未要出纸（`active` 缺省）⇒ 挂载时零请求（无 `order:list` 的页面不弹 403）', () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: { data: {} } })
    renderHook(() => usePaymentQrcodes())
    expect(mockGetPaymentQrcodes).not.toHaveBeenCalled()
    // 也没偷偷开始取（打印前 `peek` 拿不到东西 ⇒ 不会白等）
    expect(peekPaymentQrcodes()).toBeNull()
  })

  it('③ 🔴 红证（issue #7536）：`active`（预览层 / 本次打印目标）⇒ 挂载即取，不等 beforeprint', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({
      data: { data: { alipay: { imageUrl: '/uploads/a.png' } } },
    })
    const { result } = renderHook(() => usePaymentQrcodes(undefined, { active: true }))
    // 修前形态 = 这里 0 次（只挂 beforeprint）⇒ 预览层里永远是空
    await act(async () => {
      await Promise.resolve()
    })
    expect(mockGetPaymentQrcodes).toHaveBeenCalledTimes(1)
    expect(result.current).toEqual({ alipay: { imageUrl: '/uploads/a.png' } })
  })

  it('④ `beforeprint` 兜底仍在：Ctrl+P / 浏览器菜单打印不经过 usePrintDoc', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: { data: { wechat: { imageUrl: '/uploads/w.png' } } } })
    const { result } = renderHook(() => usePaymentQrcodes())
    await act(async () => {
      window.dispatchEvent(new Event('beforeprint'))
    })
    expect(mockGetPaymentQrcodes).toHaveBeenCalledTimes(1)
    expect(result.current).toEqual({ wechat: { imageUrl: '/uploads/w.png' } })
  })

  it('⑤ 两个实例 / 两次打印共享**一次**请求（模块级缓存），且打印前 `peek` 得到同一份 Promise', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: { data: {} } })
    const first = renderHook(() => usePaymentQrcodes(undefined, { active: true }))
    const second = renderHook(() => usePaymentQrcodes(undefined, { active: true }))
    const peeked = peekPaymentQrcodes()
    // 打印前 await 的必须是**同一份**在飞的 Promise（不是「拿到东西了」这种存在性断言）
    expect(peeked).toBe(loadPaymentQrcodesOnce())
    await act(async () => {
      await Promise.resolve()
    })
    expect(mockGetPaymentQrcodes).toHaveBeenCalledTimes(1)
    expect(first.result.current).toEqual({})
    expect(second.result.current).toEqual({})
    await expect(peeked!).resolves.toEqual({})
  })

  it('⑥ 请求失败（无权限 / 网络）⇒ 空 map（调用方整块不出现，不画假码）', async () => {
    mockGetPaymentQrcodes.mockRejectedValue(new Error('403'))
    const { result } = renderHook(() => usePaymentQrcodes(undefined, { active: true }))
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current).toEqual({})
  })

  it('⑦ 同步抛错（环境未就绪 / 未 mock）同样按「无码」处理，不冒泡', async () => {
    mockGetPaymentQrcodes.mockImplementation(() => {
      throw new Error('boom')
    })
    const { result } = renderHook(() => usePaymentQrcodes(undefined, { active: true }))
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current).toEqual({})
  })

  it('⑧ 响应体缺 data 层 ⇒ 空 map（不把 undefined 透给调用方）', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: undefined })
    const { result } = renderHook(() => usePaymentQrcodes(undefined, { active: true }))
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current).toEqual({})
  })

  it('⑨ 取回的 imageUrl 经 `resolveImageUrl` 规范化（白边已在**上传时**裁好，渲染口不碰像素）', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({
      data: { data: { wechat: { imageUrl: '/uploads/w.png', payeeName: '亿家纺织' } } },
    })
    const { result } = renderHook(() => usePaymentQrcodes(undefined, { active: true }))
    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.wechat?.imageUrl).toBe('/uploads/w.png')
    expect(result.current.wechat?.payeeName).toBe('亿家纺织')
  })

  it('⑩ 直接调用加载口（打印前等待用）：同一份缓存 Promise，重复调用不重复请求', async () => {
    mockGetPaymentQrcodes.mockResolvedValue({ data: { data: {} } })
    const a = loadPaymentQrcodesOnce()
    const b = loadPaymentQrcodesOnce()
    expect(a).toBe(b)
    await expect(a).resolves.toEqual({})
    expect(mockGetPaymentQrcodes).toHaveBeenCalledTimes(1)
  })
})
