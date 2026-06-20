import { describe, it, expect } from 'vitest'

describe('components/chat — #567', () => {
  const comps = ['ChatArea', 'CustomerPanel', 'InteractiveMessage', 'KnowledgeCard', 'LogisticsCard', 'MessageInput', 'MessageList', 'ProductCard', 'QuickActions', 'SessionList', 'ToolResultCard']
  for (const c of comps) {
    it(`${c} can be imported`, async () => {
      const mod = await import(`@/components/chat/${c}`)
      expect(mod.default || mod).toBeDefined()
    })
  }
})
