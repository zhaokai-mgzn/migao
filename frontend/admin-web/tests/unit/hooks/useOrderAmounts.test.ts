// case_ids: OR-009, OR-010
// useOrderAmounts — 优惠金额/实收款双向联动（issue #672 + 用户报障修复）：
// ① 修复「优惠金额输入被每键重格式化吞键 → 输入框锁死」：setDiscountAmount/setActualAmount
//   必须原样保留输入中间态（'1'、'12.'、''），仅在 blur（commitXxx）归一化；
// ② 双向联动：编辑优惠 → 实收 = 订单金额 - 优惠；编辑实收 → 优惠 = 订单金额 - 实收（恒等式恒成立）；
// ③ 订单金额变化 → 按「最后编辑的字段」为基准反算另一个字段。
import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useOrderAmounts } from '@/hooks/useOrderAmounts'

describe('useOrderAmounts — 优惠金额/实收款双向联动', () => {
  const ORDER_TOTAL = 1000.5

  it('BT-1: 优惠金额默认值为 0.00', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    expect(result.current.discountAmount).toBe('0.00')
  })

  it('BT-2: 实收款默认值 = 订单金额 - 优惠金额 = 订单金额（优惠=0时）', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    expect(result.current.actualAmount).toBe(ORDER_TOTAL.toFixed(2))
  })

  // ===== 修复「输入锁死」：输入中间态必须原样保留，禁止每键重格式化 =====

  it('BT-3: 输入优惠 "1" → 状态保持 "1"（不被重格式化为 "1.00" 吞掉后续键入）', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    act(() => {
      result.current.setDiscountAmount('1')
    })
    expect(result.current.discountAmount).toBe('1')
  })

  it('BT-4: 连续键入 "1" → "15" → 状态逐步保留（"0.0015" 吞键路径不复存在）', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    act(() => {
      result.current.setDiscountAmount('1')
    })
    expect(result.current.discountAmount).toBe('1')
    act(() => {
      result.current.setDiscountAmount('15')
    })
    expect(result.current.discountAmount).toBe('15')
  })

  it('BT-5: 输入中间态 "12." 与清空 "" 均原样保留', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    act(() => {
      result.current.setDiscountAmount('12.')
    })
    expect(result.current.discountAmount).toBe('12.')
    act(() => {
      result.current.setDiscountAmount('')
    })
    expect(result.current.discountAmount).toBe('')
  })

  // ===== 优惠 → 实收 单向联动（原有真值保留）=====

  it('BT-6: 输入优惠 "200" → 实收款联动 = 订单金额 - 200', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    act(() => {
      result.current.setDiscountAmount('200')
    })
    expect(result.current.actualAmount).toBe((ORDER_TOTAL - 200).toFixed(2))
  })

  it('BT-7: 优惠金额 = 订单金额 时，实收款应为 0', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    act(() => {
      result.current.setDiscountAmount(ORDER_TOTAL.toFixed(2))
    })
    expect(result.current.actualAmount).toBe('0.00')
  })

  it('BT-8: 优惠中间态不可解析（""/"abc"）→ 实收款保持不变（不误联动）', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    act(() => {
      result.current.setDiscountAmount('200')
    })
    const synced = result.current.actualAmount
    act(() => {
      result.current.setDiscountAmount('')
    })
    expect(result.current.actualAmount).toBe(synced)
    act(() => {
      result.current.setDiscountAmount('abc')
    })
    expect(result.current.actualAmount).toBe(synced)
  })

  // ===== 实收 → 优惠 反向联动（用户报障：输入实收款不联动优惠金额）=====

  it('BT-9: 输入实收款 "365"（订单 380）→ 优惠金额自动反算 15.00', () => {
    const { result } = renderHook(() => useOrderAmounts(380))
    act(() => {
      result.current.setActualAmount('365')
    })
    expect(result.current.discountAmount).toBe('15.00')
    expect(result.current.actualAmount).toBe('365')
  })

  it('BT-10: 实收款 > 订单金额 → 优惠金额 clamp 到 0（不为负）', () => {
    const { result } = renderHook(() => useOrderAmounts(380))
    act(() => {
      result.current.setActualAmount('500')
    })
    expect(result.current.discountAmount).toBe('0.00')
  })

  it('BT-11: 实收中间态不可解析（""/"-"）→ 优惠金额保持不变（不误联动）', () => {
    const { result } = renderHook(() => useOrderAmounts(380))
    act(() => {
      result.current.setActualAmount('365')
    })
    const synced = result.current.discountAmount
    act(() => {
      result.current.setActualAmount('')
    })
    expect(result.current.discountAmount).toBe(synced)
    act(() => {
      result.current.setActualAmount('-')
    })
    expect(result.current.discountAmount).toBe(synced)
  })

  it('BT-12: 先改实收再改优惠 → 实收款按新优惠重新联动（最后编辑者权威）', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))
    act(() => {
      result.current.setActualAmount('500')
    })
    expect(result.current.discountAmount).toBe((ORDER_TOTAL - 500).toFixed(2))
    act(() => {
      result.current.setDiscountAmount('200')
    })
    expect(result.current.actualAmount).toBe((ORDER_TOTAL - 200).toFixed(2))
  })

  // ===== blur 归一化（commitDiscount / commitActual）=====

  it('BT-13: commitDiscount 把非法/负数归一为 0.00，合法值补两位小数，并重算实收', () => {
    const { result } = renderHook(() => useOrderAmounts(ORDER_TOTAL))

    act(() => {
      result.current.setDiscountAmount('-50')
    })
    act(() => {
      result.current.commitDiscount()
    })
    expect(result.current.discountAmount).toBe('0.00')
    expect(result.current.actualAmount).toBe(ORDER_TOTAL.toFixed(2))

    act(() => {
      result.current.setDiscountAmount('abc')
    })
    act(() => {
      result.current.commitDiscount()
    })
    expect(result.current.discountAmount).toBe('0.00')

    act(() => {
      result.current.setDiscountAmount('12.5')
    })
    act(() => {
      result.current.commitDiscount()
    })
    expect(result.current.discountAmount).toBe('12.50')
    expect(result.current.actualAmount).toBe((ORDER_TOTAL - 12.5).toFixed(2))
  })

  it('BT-14: commitActual 把实收归一为两位小数并重算优惠；非法值回退为 应收-优惠', () => {
    const { result } = renderHook(() => useOrderAmounts(380))

    act(() => {
      result.current.setActualAmount('365')
    })
    act(() => {
      result.current.commitActual()
    })
    expect(result.current.actualAmount).toBe('365.00')
    expect(result.current.discountAmount).toBe('15.00')

    // 非法输入 blur → 回退恒等式默认（实收 = 应收 - 当前优惠 = 380 - 15）
    act(() => {
      result.current.setActualAmount('')
    })
    act(() => {
      result.current.commitActual()
    })
    expect(result.current.actualAmount).toBe('365.00')
    expect(result.current.discountAmount).toBe('15.00')
  })

  // ===== 订单总额变化（增删商品/改数量）=====

  it('BT-15: 订单总额变化 → 未编辑过 → 实收款 = 新总额 - 优惠', () => {
    const { result, rerender } = renderHook(
      ({ total }) => useOrderAmounts(total),
      { initialProps: { total: ORDER_TOTAL } }
    )

    rerender({ total: 2000 })

    expect(result.current.actualAmount).toBe('2000.00')
  })

  it('BT-16: 订单总额变化 → 最后编辑的是优惠 → 实收款 = 新总额 - 优惠', () => {
    const { result, rerender } = renderHook(
      ({ total }) => useOrderAmounts(total),
      { initialProps: { total: ORDER_TOTAL } }
    )

    act(() => {
      result.current.setDiscountAmount('200')
    })
    expect(result.current.actualAmount).toBe((ORDER_TOTAL - 200).toFixed(2))

    rerender({ total: 2000 })

    expect(result.current.actualAmount).toBe((2000 - 200).toFixed(2))
  })

  it('BT-17: 订单总额变化 → 最后编辑的是实收 → 实收款保持，优惠金额反算', () => {
    const { result, rerender } = renderHook(
      ({ total }) => useOrderAmounts(total),
      { initialProps: { total: ORDER_TOTAL } }
    )

    act(() => {
      result.current.setActualAmount('888')
    })

    rerender({ total: 2000 })

    expect(result.current.actualAmount).toBe('888')
    expect(result.current.discountAmount).toBe((2000 - 888).toFixed(2))
  })

  it('BT-18: discountAmount/actualAmount 初始化基于 orderTotal', () => {
    const { result: r1 } = renderHook(() => useOrderAmounts(500))
    expect(r1.current.actualAmount).toBe('500.00')

    const { result: r2 } = renderHook(() => useOrderAmounts(0))
    expect(r2.current.actualAmount).toBe('0.00')
  })
})
