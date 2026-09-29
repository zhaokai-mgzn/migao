// case_ids: UI-068
/**
 * 看板**可插拔指标卡**的显隐判定（issue #5792）。
 *
 * ## 用户要求（原话）
 *
 * 「**AI 接待占比这个需要设计成可插拔的，未来有部分企业可能未购买智能客服**」
 * ⇒ 卡片显隐必须由**服务端下发的能力位**决定，而不是各组件自己判权限码。
 *
 * ## 三条口径（本文件逐条钉死）
 *
 *   ① **保守**：能力位**缺省/undefined** ⇒ 不渲染（与 false 同待遇）——
 *      能力位没下发时我们**不知道**企业有没有买 ⇒ 宁可不显示，也不显示来源不明的数字；
 *   ② **未购买 ⇒ 卡片不渲染**，不是渲染成 0、不是空白占位；
 *   ③ 判定只读能力位（端侧不判权限码）。
 */
import { describe, it, expect } from 'vitest'
import {
  PLUGGABLE_DASHBOARD_CARDS,
  shouldRenderCard,
  visiblePluggableCards,
  type CapabilityBits,
} from '@/lib/dashboard-cards'

const AI_CARD = PLUGGABLE_DASHBOARD_CARDS.find((c) => c.key === 'ai-service-rate')

describe('可插拔看板卡：显隐判定（issue #5792）', () => {
  it('注册表里「AI 接待占比」依赖 `aiService` 能力位（不是散落的 if）', () => {
    expect(AI_CARD).toBeDefined()
    expect(AI_CARD!.requires).toBe('aiService')
    expect(AI_CARD!.title).toBe('AI 接待占比')
  })

  it.each([
    ['能力位缺省（undefined）', undefined, false],
    ['能力位为空对象', {}, false],
    ['明确未启用（false）', { aiService: false }, false],
    ['明确启用（true）', { aiService: true }, true],
    ['启用但另一个位为假（互不干扰）', { mibaoChat: false, aiService: true }, true],
  ])('🔴 %s ⇒ 渲染=%s（缺省**不**渲染是保守口径，不是 false 的巧合）', (_n, bits, expected) => {
    expect(shouldRenderCard(AI_CARD!, bits as CapabilityBits | undefined)).toBe(expected)
    expect(visiblePluggableCards(bits as CapabilityBits | undefined).length).toBe(expected ? 1 : 0)
  })

  it('类级元守卫：注册表里每个 `requires` 都必须是**已知能力位**（拼错键不会静默隐藏卡片）', () => {
    // 为什么还要它（`requires` 已被类型约束为 `keyof CapabilityBits`，tsc 能挡 typo）：
    // 类型一旦被**放宽**（有人改成 `requires: string` 去接"未来更多能力位"）⇒ tsc 就挡不住了，
    // 那时拼错的键会让卡片**永远不渲染**且没有任何东西变红。本判据把键集**运行时**钉住，
    // 与类型构成双保险（类型挡编译期、本判据挡运行期）。
    const KNOWN: readonly (keyof CapabilityBits)[] = ['mibaoChat', 'aiService']
    for (const card of PLUGGABLE_DASHBOARD_CARDS) {
      expect(KNOWN, `卡片 ${card.key} 的 requires=${card.requires} 不是已知能力位`).toContain(card.requires)
    }
  })
})
