import { describe, it, expect } from 'vitest'

describe('components/layout — #568', () => {
  for (const c of ['Header', 'NotificationBell', 'Sidebar']) {
    it(`${c} can be imported`, async () => {
      const mod = await import(`@/components/layout/${c}`)
      expect(mod.default || mod).toBeDefined()
    })
  }
})
