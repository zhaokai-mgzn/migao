import { describe, it, expect } from 'vitest'

describe('lib/token-refresh-manager — #574', () => {
  it('can be imported', async () => {
    const mod = await import('@/lib/token-refresh-manager')
    expect(mod.TokenRefreshManager || mod.default || mod).toBeDefined()
  })
})
