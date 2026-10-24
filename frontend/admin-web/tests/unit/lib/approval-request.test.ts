// case_ids: APV-002
import { describe, expect, it } from 'vitest'
import { creditOverrideDraft, priceChangeDraft, stocktakeDiffDraft } from '@/lib/approval-request'

/**
 * 审批申请的**对象口径**（issue #7374 段 3）—— 与后端闸门的 `consume()` 逐字对齐。
 *
 * 写错 ref 或金额低于门槛，后果是「审批通过了却用不上」，而审批中心看起来完全正常。
 * 所以这三条口径必须由纯函数钉死，逐格判据（不靠人记）。
 */
describe('审批申请的对象口径', () => {
  it('改价：ref = SKU id，金额不预填（前端拿不到成本价）但提示里点名「要 ≥ 成本价」', () => {
    const draft = priceChangeDraft({ skuId: '42', skuLabel: '遮光布 米白 2.8m' })
    expect(draft.objectType).toBe('price_change')
    expect(draft.objectRef).toBe('42')
    expect(draft.objectLabel).toBe('遮光布 米白 2.8m')
    expect(draft.defaultAmount).toBeNull()
    expect(draft.amountHint).toContain('成本价')
    // 拿得到成本时，提示里给出具体数字（审批人不用去别处查）
    expect(priceChangeDraft({ skuId: '42', costHint: '¥95.00' }).amountHint).toContain('¥95.00')
  })

  it('盘点差异：ref = **盘点单号**（不是 id），金额预填 = 差异合计的绝对值', () => {
    // 🔴 StocktakeService 用 `stocktake.getStocktakeNo()` 找审批 ⇒ 传 id 会「批了也用不上」
    const draft = stocktakeDiffDraft({ stocktakeNo: 'PD202610220001', diffTotal: -12.5 })
    expect(draft.objectType).toBe('stocktake_diff')
    expect(draft.objectRef).toBe('PD202610220001')
    expect(draft.defaultAmount).toBe(12.5)      // 盘盈盘亏都要正数门槛
    expect(draft.amountHint).toContain('12.5')
  })

  it('盘点差异：还没数完（差异合计未知）⇒ 不预填金额，提示改口径', () => {
    const draft = stocktakeDiffDraft({ stocktakeNo: 'PD202610220002', diffTotal: null })
    expect(draft.defaultAmount).toBeNull()
    expect(draft.amountHint).toContain('还没数完')
  })

  it('超授信：ref = **客户手机号**，金额 = 本次超出额', () => {
    const draft = creditOverrideDraft({ customerPhone: '13800000001', customerName: '张记布艺', excess: 860 })
    expect(draft.objectType).toBe('credit_override')
    expect(draft.objectRef).toBe('13800000001')
    expect(draft.objectLabel).toBe('张记布艺')
    expect(draft.defaultAmount).toBe(860)
    expect(draft.amountHint).toContain('860')
  })
})
