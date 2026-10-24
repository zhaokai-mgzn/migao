// case_ids: APV-002
import { describe, expect, it } from 'vitest'
import { creditDraftFromRejection } from '@/lib/approval-request'

/**
 * 授信申请草稿（issue #7374 段 4）—— 从服务端拒绝**原话**里取下单要用的三件套。
 *
 * 边界最要紧的两条：
 * ① 金额取「尚缺额」而**不是**订单总额（批多了会白占客户额度）；
 * ② 不是授信拒绝的文案 ⇒ 返回 `null`（页面上不许凭空冒出一个申请入口）。
 */
const REJECT =
  '超出客户授信额度：本单 ¥8,600 + 已欠 ¥2,000 > 额度 ¥10,000，尚缺 ¥600。' +
  '如需放行，请先申请 credit_override 审批（objectType=credit_override，objectRef=客户手机号，金额 ≥ 尚缺额）'

describe('授信申请草稿（从拒绝原文生成）', () => {
  it('🔴 ref = 客户手机号，金额 = 「尚缺」那个数（不是订单总额）', () => {
    const draft = creditDraftFromRejection(REJECT, {
      customerPhone: '13800000001',
      customerName: '张记布艺',
      fallbackAmount: 8600,
    })!
    expect(draft.objectType).toBe('credit_override')
    expect(draft.objectRef).toBe('13800000001')
    expect(draft.objectLabel).toBe('张记布艺')
    expect(draft.defaultAmount).toBe(600)            // ← 尚缺 600，不是 8600
    expect(draft.amountHint).toContain('600')
  })

  it('「尚缺」带千分位/无 ¥ 符号也能认', () => {
    const draft = creditDraftFromRejection('超出客户授信额度：尚缺 1,200.50 元', {
      customerPhone: '13900000002',
      fallbackAmount: 5000,
    })!
    // 千分位要一起吃掉：只认到 `1` 的话申请的额度小 1000 倍 ⇒ 批了还是过不了
    expect(draft.defaultAmount).toBe(1200.5)
  })

  it('解析不到尚缺额 ⇒ 退回传进来的兜底金额', () => {
    const draft = creditDraftFromRejection('超出客户授信额度，请联系管理员', {
      customerPhone: '13800000003',
      fallbackAmount: 8600,
    })!
    expect(draft.defaultAmount).toBe(8600)
  })

  it('🔴 不是授信拒绝的文案 ⇒ null（不凭空冒入口）', () => {
    expect(creditDraftFromRejection('创建订单失败', { customerPhone: '13800000001', fallbackAmount: 100 })).toBeNull()
    expect(creditDraftFromRejection('', { customerPhone: '13800000001', fallbackAmount: 100 })).toBeNull()
  })

  it('没有手机号 ⇒ null（授信闸门按手机号找审批，没手机号批了也对不上）', () => {
    expect(creditDraftFromRejection(REJECT, { customerPhone: '  ', fallbackAmount: 100 })).toBeNull()
  })
})
