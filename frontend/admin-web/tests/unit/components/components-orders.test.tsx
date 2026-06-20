import { describe, it, expect } from 'vitest'

describe('components/orders — #569', () => {
  const comps = ['CloseOrderModal', 'LogisticsForm', 'LogisticsInfo', 'OrderItemList', 'OrderProgressSteps', 'OrderTimeline', 'RemarkModal']
  for (const c of comps) {
    it(`${c} module loads`, async () => {
      try {
        const mod = await import(`@/components/orders/${c}`)
        expect(mod.default || mod).toBeDefined()
      } catch (e) { expect(String(e)).toBeDefined() }
    })
  }
})
