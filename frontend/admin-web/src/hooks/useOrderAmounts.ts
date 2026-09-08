import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * useOrderAmounts — 订单金额 + 优惠金额 + 实收款 双向联动逻辑
 *
 * Business truths (issue #672 + 用户报障修复):
 * 1. 优惠金额默认值为 '0.00'；实收款默认值 = 订单金额 - 优惠金额
 * 2. 恒等式：订单金额 - 优惠金额 = 实收款，任意字段编辑后始终成立
 * 3. 输入过程自由键入（中间态 '1'、'12.'、'' 原样保留，禁止每键重格式化吞键
 *    —— 修复「优惠金额输入框锁死」），仅在 blur（commitDiscount/commitActual）归一化
 * 4. 编辑优惠 → 实收 = 订单金额 - 优惠；编辑实收 → 优惠 = 订单金额 - 实收（双向联动，
 *    最后编辑的字段权威）
 * 5. 两个金额均不可为负（实收 > 应收 → 优惠 clamp 到 0；非法/负数输入 blur 归一为 0）
 * 6. 订单金额变化（增删商品/改数量）→ 按「最后编辑的字段」为基准反算另一个字段
 */

export type AmountField = 'discount' | 'actual'

export function useOrderAmounts(orderTotal: number) {
  const [discountAmount, setDiscountAmountRaw] = useState('0.00')
  const [actualAmount, setActualAmountRaw] = useState(() => orderTotal.toFixed(2))

  // 最后编辑的字段（ref：仅供本 hook 内部联动判断，不触发渲染）
  const lastEditedRef = useRef<AmountField | null>(null)
  // 同步最新值供事件回调使用，避免 stale closure
  const orderTotalRef = useRef(orderTotal)
  orderTotalRef.current = orderTotal
  const discountRef = useRef(discountAmount)
  discountRef.current = discountAmount
  const actualRef = useRef(actualAmount)
  actualRef.current = actualAmount

  // 订单金额变化（增删商品/改数量）→ 以最后编辑字段为基准反算另一个字段
  useEffect(() => {
    const total = orderTotal
    if (lastEditedRef.current === 'actual') {
      const actual = parseFloat(actualRef.current)
      const discount = Number.isNaN(actual) ? 0 : Math.max(0, total - actual)
      setDiscountAmountRaw(discount.toFixed(2))
    } else {
      const discount = parseFloat(discountRef.current)
      const actual = Number.isNaN(discount)
        ? total
        : Math.max(0, total - discount)
      setActualAmountRaw(actual.toFixed(2))
    }
  }, [orderTotal]) // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * 优惠金额输入（自由键入）：中间态原样保留；
   * 可解析且非负时联动 实收 = 订单金额 - 优惠
   */
  const setDiscountAmount = useCallback((val: string) => {
    lastEditedRef.current = 'discount'
    setDiscountAmountRaw(val)
    const num = parseFloat(val)
    if (!Number.isNaN(num) && num >= 0) {
      setActualAmountRaw(Math.max(0, orderTotalRef.current - num).toFixed(2))
    }
  }, [])

  /**
   * 实收款输入（自由键入）：中间态原样保留；
   * 可解析且非负时反算 优惠 = 订单金额 - 实收（clamp 到 0，不为负）
   */
  const setActualAmount = useCallback((val: string) => {
    lastEditedRef.current = 'actual'
    setActualAmountRaw(val)
    const num = parseFloat(val)
    if (!Number.isNaN(num) && num >= 0) {
      setDiscountAmountRaw(Math.max(0, orderTotalRef.current - num).toFixed(2))
    }
  }, [])

  /** 优惠金额 blur 归一化：非法/负数 → '0.00'，合法值补两位小数，并重算实收 */
  const commitDiscount = useCallback(() => {
    const num = parseFloat(discountRef.current)
    const clean = Number.isNaN(num) || num < 0 ? 0 : num
    setDiscountAmountRaw(clean.toFixed(2))
    setActualAmountRaw(Math.max(0, orderTotalRef.current - clean).toFixed(2))
  }, [])

  /** 实收款 blur 归一化：合法值补两位小数并反算优惠；非法/负数回退 恒等式默认（实收 = 应收 - 优惠） */
  const commitActual = useCallback(() => {
    const num = parseFloat(actualRef.current)
    if (Number.isNaN(num) || num < 0) {
      const discount = Math.max(0, parseFloat(discountRef.current) || 0)
      setActualAmountRaw(Math.max(0, orderTotalRef.current - discount).toFixed(2))
      return
    }
    setActualAmountRaw(num.toFixed(2))
    setDiscountAmountRaw(Math.max(0, orderTotalRef.current - num).toFixed(2))
  }, [])

  return {
    discountAmount,
    setDiscountAmount,
    commitDiscount,
    actualAmount,
    setActualAmount,
    commitActual,
  }
}
