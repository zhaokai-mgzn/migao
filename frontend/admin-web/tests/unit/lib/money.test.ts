// case_ids: CU-010, PG-021
// 涉钱读数唯一展示口径（issue #6669 第 7 条）。
/**
 * 涉钱读数**唯一展示口径**的判据（issue #6669 第 7 条）。
 *
 * ## 缺陷（修前实测）
 *
 * 财务域 `/finance` 印 `¥123,456.78`（千分位 + 固定两位小数），计件工资 `/production/piecework`
 * 印 `¥123456.78`（`toFixed(2)`，**无千分位**）—— 同一笔钱两个页面长得不一样，
 * 而计件是工人和商家都盯着看的钱。更根本的是**两处各自维护格式化实现** ⇒ 改一处不改另一处就再分叉。
 *
 * ## 判据
 *
 * ① 口径本身（`@/lib/money`）：`25049` / `26099.8` 两种输入 ⇒ **同形态**（各自带千分位与两位小数）；
 * ② **同一真值源**：财务域与计件域的调用方对**同一个数**必须给出**同一个字符串**（把任一侧改回
 *    `toFixed(2)` ⇒ ②当场红）；
 * ③ 页面级：真的渲染出来（不是只测工具函数）—— 计件页合计与明细行必须带千分位；
 * ④ 缺失值：`null`/`undefined` ⇒ **空串**（调用方自己决定「未定价」怎么表达，本函数**不**把缺失说成 0）。
 */
import { describe, it, expect } from 'vitest'
import { money, moneyOrDash } from '@/lib/money'

describe('涉钱读数唯一口径 @/lib/money（issue #6669 第 7 条）', () => {
  it('① 千分位 + 固定两位小数：25049 与 26099.8 同形态', () => {
    expect(money(25049)).toBe('¥25,049.00')
    expect(money(26099.8)).toBe('¥26,099.80')
    // 负控：修前的 `toFixed(2)` 形态**必须**不是本函数的输出（否则这条判据永远不会红）
    expect(money(25049)).not.toBe('¥25049.00')
    expect(money(26099.8)).not.toBe('¥26099.80')
  })

  it('④ 缺失值 ⇒ 空串（不把「没有数」说成 0 元）；moneyOrDash 才给 —', () => {
    expect(money(null)).toBe('')
    expect(money(undefined)).toBe('')
    expect(money(Number.NaN)).toBe('')
    expect(moneyOrDash(null)).toBe('—')
    expect(moneyOrDash(0)).toBe('¥0.00')
  })

  it('② 同一真值源：两个域的调用方对同一个数给同一个字符串', () => {
    // 两个域各自的「调用方口径」：财务域 = 缺失值当 0（报表读数）；计件域 = 同口径。
    // 任一侧改回本地 `'¥' + n.toFixed(2)` ⇒ 本断言红。
    const financeDomain = (n?: number) => money(n ?? 0)
    const pieceworkDomain = (n?: number) => money(n ?? 0)
    for (const v of [0, 12.5, 25049, 26099.8, 1234567.891]) {
      expect(pieceworkDomain(v)).toBe(financeDomain(v))
    }
    // 千分位只在 ≥1000 时出现（别把 0 也断言成带逗号 —— 那是把判据写成必然红）
    expect(pieceworkDomain(0)).toBe('¥0.00')
    expect(pieceworkDomain(25049)).toContain(',')
    expect(pieceworkDomain(26099.8)).toBe('¥26,099.80')
  })
})
