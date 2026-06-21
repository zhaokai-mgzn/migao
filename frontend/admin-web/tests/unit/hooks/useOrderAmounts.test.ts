import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useOrderAmounts } from '@/hooks/useOrderAmounts'

describe('useOrderAmounts — 优惠金额联动逻辑 (issue #672)', () => {
  const ORDER_TOTAL = 1000.50

  it('BT-1: 优惠金额默认值为 0', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    expect(result.current.discountAmount).toBe('0.00')
  })

  it('BT-2: 实收款默认值 = 订单金额 - 优惠金额 = 订单金额（优惠=0时）', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    expect(result.current.actualAmount).toBe(ORDER_TOTAL.toFixed(2))
  })

  it('BT-3: 修改优惠金额 → 实收款未手动改过 → 自动联动更新', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))

    act(() => {
      result.current.setDiscountAmount('200')
    })

    expect(result.current.discountAmount).toBe('200.00')
    expect(result.current.actualAmount).toBe((ORDER_TOTAL - 200).toFixed(2))
    expect(result.current.actualTouched).toBe(false)
  })

  it('BT-4: 修改优惠金额 → 实收款自动联动（整数金额）', () => {
    const { result } = renderHook(() => useOrderAmounts(1000))

    act(() => {
      result.current.setDiscountAmount('300')
    })

    expect(result.current.actualAmount).toBe('700.00')
  })

  it('BT-5: 用户手动修改实收款 → actualTouched=true → 优惠金额再变化不再联动', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))

    act(() => {
      result.current.setActualAmount('500')
    })

    expect(result.current.actualTouched).toBe(true)
    expect(result.current.actualAmount).toBe('500')

    act(() => {
      result.current.setDiscountAmount('200')
    })

    expect(result.current.actualAmount).toBe('500')
  })

  it('BT-6: 优惠金额 = 订单金额 时，实收款应为 0', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))

    act(() => {
      result.current.setDiscountAmount(ORDER_TOTAL.toFixed(2))
    })

    expect(result.current.actualAmount).toBe('0.00')
  })

  it('BT-7: 优惠金额不可为负数 — setDiscountAmount 自动 clamp 到 0', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))

    act(() => {
      result.current.setDiscountAmount('-50')
    })

    expect(Number(result.current.discountAmount)).toBeGreaterThanOrEqual(0)
  })

  it('BT-8: 订单总额变化 → 未touched时 → 实收款联动更新', () => {
    const { result, rerender } = renderHook(
      ({ total }) => useOrderAmounts(total),
      { initialProps: { total: ORDER_TOTAL } }
    )

    act(() => {
      result.current.setDiscountAmount('200')
    })
    expect(result.current.actualAmount).toBe((ORDER_TOTAL - 200).toFixed(2))

    const newTotal = 2000
    rerender({ total: newTotal })

    expect(result.current.actualAmount).toBe((newTotal - 200).toFixed(2))
  })

  it('BT-9: 订单总额变化 → 已touched → 实收款不变', () => {
    const { result, rerender } = renderHook(
      ({ total }) => useOrderAmounts(total),
      { initialProps: { total: ORDER_TOTAL } }
    )

    act(() => {
      result.current.setActualAmount('888')
    })
    expect(result.current.actualTouched).toBe(true)

    rerender({ total: 2000 })

    expect(result.current.actualAmount).toBe('888')
  })

  it('BT-10: discountAmount 初始化基于 orderTotal', () => {
    const { result: r1 } = renderHook(() => useOrderAmounts(500))
    expect(r1.current.actualAmount).toBe('500.00')

    const { result: r2 } = renderHook(() => useOrderAmounts(0))
    expect(r2.current.actualAmount).toBe('0.00')
  })
})
