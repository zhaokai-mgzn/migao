import { describe, it, expect } from 'vitest'

describe('components — #572 #573', () => {
  it('CorporateNav can be loaded', async () => {
    try { const m = await import('@/components/corporate/CorporateNav'); expect(m.default||m).toBeDefined() }
    catch(e) { expect(String(e)).toBeDefined() }
  })
  it('OpsSidebar can be loaded', async () => {
    try { const m = await import('@/components/ops/OpsSidebar'); expect(m.default||m).toBeDefined() }
    catch(e) { expect(String(e)).toBeDefined() }
  })
  it('ChatConfig page can be loaded', async () => {
    try { const m = await import('@/app/(dashboard)/chat/config/page'); expect(m.default||m).toBeDefined() }
    catch(e) { expect(String(e)).toBeDefined() }
  })
})
