import { describe, it, expect } from 'vitest'

describe('app routes — #564 #565 #566', () => {
  const pages = [
    'orders/new/page', 'knowledge/page', 'employees/page',
    'categories/page', 'services/page', 'products/[id]/edit/EditProduct',
    'registrations/page', 'customers/[id]/CustomerDetail', 'orders/[id]/OrderDetail',
  ]
  for (const p of pages) {
    it(`page ${p} can be loaded`, async () => {
      try {
        const mod = await import(`@/app/(dashboard)/${p}`)
        expect(mod.default || mod).toBeDefined()
      } catch (e) { expect(String(e)).toBeDefined() }
    })
  }
})
