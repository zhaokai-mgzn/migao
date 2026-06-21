import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * useOrderAmounts — 订单金额 + 优惠金额 + 实收款 联动逻辑
 *
 * Business truths (issue #672):
 * 1. 优惠金额默认值为 0
 * 2. 实收款默认值 = 订单金额 - 优惠金额
 * 3. 修改优惠金额 → 未手动改过实收款时 → 自动联动更新
 * 4. 手动改过实收款 → actualTouched=true → 优惠变化不再联动
 * 5. 优惠金额不能为负数 (min=0)
 */
export function useOrderAmounts(orderTotal: number) {
  const [discountAmount, setDiscountAmountRaw] = useState('0.00')
  const [actualAmount, setActualAmountRaw] = useState(() => orderTotal.toFixed(2))
  const [actualTouched, setActualTouched] = useState(false)

  // Track the current orderTotal for use in event handlers without stale closure
  const orderTotalRef = useRef(orderTotal)
  orderTotalRef.current = orderTotal

  // When orderTotal changes (e.g. more items added), sync actualAmount if not touched
  useEffect(() => {
    if (!actualTouched) {
      const discount = parseFloat(discountAmount) || 0
      const newActual = Math.max(0, orderTotal - discount)
      setActualAmountRaw(newActual.toFixed(2))
    }
  }, [orderTotal]) // eslint-disable-line react-hooks/exhaustive-deps

  // When discountAmount changes, sync actualAmount if not touched
  useEffect(() => {
    if (!actualTouched) {
      const discount = parseFloat(discountAmount) || 0
      const newActual = Math.max(0, orderTotalRef.current - discount)
      setActualAmountRaw(newActual.toFixed(2))
    }
  }, [discountAmount]) // eslint-disable-line react-hooks/exhaustive-deps

  const setDiscountAmount = useCallback((val: string) => {
    // Clamp to non-negative
    const num = parseFloat(val)
    const clamped = Number.isNaN(num) ? '0.00' : Math.max(0, num).toFixed(2)
    setDiscountAmountRaw(clamped)
  }, [])

  const setActualAmount = useCallback((val: string) => {
    setActualTouched(true)
    setActualAmountRaw(val)
  }, [])

  return {
    discountAmount,
    setDiscountAmount,
    actualAmount,
    setActualAmount,
    actualTouched,
  }
}
