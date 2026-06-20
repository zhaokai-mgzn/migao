import { describe, it, expect } from 'vitest'

describe('components/dashboard — #570', () => {
  for (const c of ['ActiveSessions', 'OrderStatusChart', 'OrderTrendChart', 'RecentOrders', 'StatCard']) {
    it(`${c} can be imported`, async () => {
      const mod = await import(`@/components/dashboard/${c}`)
      expect(mod.default || mod).toBeDefined()
    })
  }
})
