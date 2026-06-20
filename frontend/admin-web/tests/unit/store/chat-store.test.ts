import { describe, it, expect } from 'vitest'

describe('store/chat — #571', () => {
  it('can be imported', async () => {
    const mod = await import('@/store/chat')
    expect(mod.useChatStore || mod.default || mod).toBeDefined()
  })
})
