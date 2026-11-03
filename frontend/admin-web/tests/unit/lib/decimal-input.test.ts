// case_ids: MC-159
/**
 * 数字录入的**解析 / 校验 / 话术**单一口径（issue #8004）。
 *
 * 本文件钉的是本单的**核心判据 ②**：涉钱面的精度**不许**丢，也不许被悄悄改。
 * 每条都是**逐值**断言（`12.345` / `0.10` / `1,234.56` / `12.` 四个用户点名的形态各一条），
 * 不是「看着像数字就算过」。
 */
import { describe, expect, it } from 'vitest'
import {
  decimalMessage,
  finalizeDraft,
  interpretDecimal,
  MONEY_RULES,
  type DecimalRules,
} from '@/lib/decimal-input'

const money = MONEY_RULES
const rules = (over: Partial<DecimalRules> = {}): DecimalRules => ({ ...money, ...over })

describe('判据 ②：精度不丢（涉钱面的四个点名形态逐条钉死）', () => {
  it('`12.345` ⇒ 拒绝（最多 2 位小数），**不许**静默四舍五入成 12.35 或截断成 12.34', () => {
    const r = interpretDecimal('12.345', money)
    expect(r).toEqual({ state: 'invalid', reason: 'too-many-decimals' })
    // 反面砝码：任何 `ok` 都是静默改价
    expect(r.state).not.toBe('ok')
  })

  it('`0.10` ⇒ 0.1（规范串去尾随 0，数值精确）', () => {
    expect(interpretDecimal('0.10', money)).toEqual({ state: 'ok', value: 0.1, canonical: '0.1' })
  })

  it('`1,234.56` ⇒ 1234.56（千分位**接受并去掉**，不因逗号退回 1 或 NaN）', () => {
    expect(interpretDecimal('1,234.56', money)).toEqual({
      state: 'ok',
      value: 1234.56,
      canonical: '1234.56',
    })
    expect(finalizeDraft('1,234.56', money).text).toBe('1234.56')
  })

  it('尾随小数点 `12.`：打字时是中间态（原样留在框里），失焦收尾成 12 —— 两端都不许吞', () => {
    expect(interpretDecimal('12.', money)).toEqual({ state: 'draft' })
    expect(finalizeDraft('12.', money).result).toEqual({ state: 'ok', value: 12, canonical: '12' })
    expect(finalizeDraft('12.', money).text).toBe('12')
  })

  it('其余精度形态：`.5` / `0` / `0.1` / `12.30` 各有确定读法', () => {
    expect(interpretDecimal('.5', money)).toEqual({ state: 'ok', value: 0.5, canonical: '0.5' })
    expect(interpretDecimal('0', money)).toEqual({ state: 'ok', value: 0, canonical: '0' })
    expect(interpretDecimal('12.30', money)).toEqual({ state: 'ok', value: 12.3, canonical: '12.3' })
  })
})

describe('判据 ③：解析失败必须「有话说」—— 四态分清，不静默变 0 / 变 NaN', () => {
  it('空串是 empty（还没填），不是 0；`-` / `.` 是 draft（还在敲），不是错', () => {
    expect(interpretDecimal('', money)).toEqual({ state: 'empty' })
    expect(interpretDecimal('   ', money)).toEqual({ state: 'empty' })
    expect(interpretDecimal('-', money)).toEqual({ state: 'draft' })
    expect(interpretDecimal('.', money)).toEqual({ state: 'draft' })
  })

  it('只差收尾的中间态（`1,` / `1,234.`）失焦收成完整值，打字中不报错', () => {
    expect(interpretDecimal('1,', money)).toEqual({ state: 'draft' })
    expect(interpretDecimal('1,234.', money)).toEqual({ state: 'draft' })
    expect(finalizeDraft('1,', money).text).toBe('1')
    expect(finalizeDraft('1,234.', money).text).toBe('1234')
  })

  it('真·非法：`abc` / 科学计数法 `1e3` / `12.3.4` / 千分位分组错 `1,2`（失焦）⇒ not-a-number', () => {
    for (const raw of ['abc', '1e3', '12.3.4', '1 2']) {
      expect(interpretDecimal(raw, money), raw).toEqual({ state: 'invalid', reason: 'not-a-number' })
    }
    // 千分位分组不成立时：打字中当中间态（还会长），失焦后才判错
    expect(interpretDecimal('1,2345', money)).toEqual({ state: 'draft' })
    expect(interpretDecimal('1,2345', money, { finalize: true })).toEqual({
      state: 'invalid',
      reason: 'not-a-number',
    })
    expect(interpretDecimal('1,2', money)).toEqual({ state: 'draft' }) // 打字中还在长
    expect(interpretDecimal('1,2', money, { finalize: true })).toEqual({
      state: 'invalid',
      reason: 'not-a-number',
    })
    // 只剩符号 / 小数点：失焦仍解析不出 ⇒ 出声（不是静默 0）
    expect(interpretDecimal('-', money, { finalize: true })).toEqual({
      state: 'invalid',
      reason: 'not-a-number',
    })
  })

  it('数值域：超过 1e15（定点形态不再成立）⇒ not-a-number（不谎报、不落指数形态）', () => {
    expect(interpretDecimal('1234567890123456', money)).toEqual({
      state: 'invalid',
      reason: 'not-a-number',
    })
  })

  it('话术表：五种原因各不相同、都带口径名、都可行动（无一泛泛「输入有误」）', () => {
    const msgs = {
      'not-a-number': decimalMessage('not-a-number', '退款金额', money),
      'too-many-decimals': decimalMessage('too-many-decimals', '退款金额', money),
      'below-min': decimalMessage('below-min', '退款金额', rules({ min: 0.01 })),
      'above-max': decimalMessage('above-max', '退款金额', rules({ max: 9999 })),
      empty: decimalMessage('empty', '退款金额', money),
    }
    expect(new Set(Object.values(msgs)).size).toBe(5)
    for (const [reason, text] of Object.entries(msgs)) {
      expect(text, reason).toContain('退款金额')
      expect(text.length, reason).toBeGreaterThanOrEqual(6) // 最短的一条是「请填写退款金额」
    }
    expect(msgs['too-many-decimals']).toContain('2 位小数')
    expect(msgs['too-many-decimals']).toContain('不会替你四舍五入')
    expect(msgs['below-min']).toContain('0.01')
    expect(msgs['above-max']).toContain('9999')
    expect(msgs.empty).toBe('请填写退款金额')
  })

  it('小数位为 0 的整数格说「只能填整数」（不是「最多 0 位小数」）', () => {
    const r = rules({ decimals: 0 })
    expect(decimalMessage('too-many-decimals', '数量', r)).toContain('只能填整数')
  })
})

describe('判据 ④：负数 / 零 / 超上限按业务口径拒绝（下限由调用方给，不在这里拍）', () => {
  it('负数（min = 0）⇒ below-min；零在 min = 0.01 的格（如退款金额）⇒ below-min', () => {
    expect(interpretDecimal('-1', money)).toEqual({ state: 'invalid', reason: 'below-min' })
    expect(interpretDecimal('-0.01', money)).toEqual({ state: 'invalid', reason: 'below-min' })
    expect(interpretDecimal('0', rules({ min: 0.01 }))).toEqual({
      state: 'invalid',
      reason: 'below-min',
    })
    // 对照：min = 0 的格允许 0（优惠金额 / 实收款可以填 0）
    expect(interpretDecimal('0', money).state).toBe('ok')
  })

  it('超上限 ⇒ above-max；上限不设 ⇒ 不判（不自造涉钱上限）', () => {
    expect(interpretDecimal('101', rules({ max: 100 }))).toEqual({
      state: 'invalid',
      reason: 'above-max',
    })
    expect(interpretDecimal('101', money).state).toBe('ok')
    expect(interpretDecimal('100', rules({ max: 100 })).state).toBe('ok')
  })
})
