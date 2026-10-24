// case_ids: OR-027
/**
 * 订单列表「下单时间」窗口的兜底（issue #7404：用户裁定「需要做个兜底，不允许查全部」「最多回溯近 3 年」）。
 *
 * 红证（会怎么红）：
 * - 把 `resolveOrderDateWindow` 的两端皆空分支删掉（改成原样返回空串）⇒ 前两条必红；
 * - 把 `ORDER_LOOKBACK_MONTHS` 从 36 改成 12 ⇒ `falls back to 36 months` 必红。
 */
import { describe, expect, it } from 'vitest'
import { ORDER_LOOKBACK_MONTHS, resolveOrderDateWindow } from '@/lib/order-search-window'

const TODAY = new Date(2026, 9, 20) // 2026-10-20（本地时区，与 build 的 formatYmd 同口径）

describe('订单列表时间窗兜底（#7404）', () => {
  it('两端都没选 ⇒ 兜底最近 36 个月，并标记 filled（调用方据此回填输入框）', () => {
    const w = resolveOrderDateWindow('', '', TODAY)
    expect(w.filled).toBe(true)
    expect(w.endDate).toBe('2026-10-20')
    expect(w.startDate).toBe('2023-10-20')
    expect(ORDER_LOOKBACK_MONTHS).toBe(36)
  })

  it('只清空起点 ⇒ 也走兜底（否则就是「从很久以前到今天」= 查全部）', () => {
    const w = resolveOrderDateWindow('', '2026-10-20', TODAY)
    expect(w.filled).toBe(false)
    // 兜底交给后端按「截止日往前 36 个月」补齐；前端不擅自改写用户选的截止日
    expect(w.startDate).toBe('')
    expect(w.endDate).toBe('2026-10-20')
  })

  it('显式区间原样透传（要查三年前的某一单，自己选日期即可，不被截断）', () => {
    const w = resolveOrderDateWindow('2019-01-01', '2019-12-31', TODAY)
    expect(w.filled).toBe(false)
    expect(w.startDate).toBe('2019-01-01')
    expect(w.endDate).toBe('2019-12-31')
  })

  it('只给了起点 ⇒ 原样透传（终点由后端兜到「今天」）', () => {
    const w = resolveOrderDateWindow('2024-05-01', '', TODAY)
    expect(w.filled).toBe(false)
    expect(w.startDate).toBe('2024-05-01')
    expect(w.endDate).toBe('')
  })
})
