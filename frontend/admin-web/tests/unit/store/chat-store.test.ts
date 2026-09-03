// case_ids: CH-008
import { describe, it, expect } from 'vitest'

describe('store/chat — #571', () => {
  it('can be imported', async () => {
    const mod = await import('@/store/chat')
    expect(mod.useChatStore || mod.default || mod).toBeDefined()
  })
})

describe('store/chat P0-B 回归 — ai-api 直连 fetch 带 credentials（整页刷新后 cookie 认证）', () => {
  it('源代码中所有直连 ai-api 的 fetch 均含 credentials: include', async () => {
    const fs = await import('fs')
    const storeSrc = fs.readFileSync('src/store/chat.ts', 'utf8')
    const messageListSrc = fs.readFileSync('src/components/chat/MessageList.tsx', 'utf8')
    const apiSrc = fs.readFileSync('src/lib/api.ts', 'utf8')
    // 三个文件里对 AI_SERVICE_URL 的 fetch 都必须带 credentials
    for (const [name, src] of [['store/chat.ts', storeSrc], ['MessageList.tsx', messageListSrc], ['lib/api.ts', apiSrc]]) {
      const fetchBlocks = src.split('AI_SERVICE_URL}/').slice(1)
      for (const block of fetchBlocks) {
        // 每个 fetch 配置块（到首个 }) 或 body 前）应含 credentials
        const config = block.slice(0, block.indexOf('body:') > -1 ? block.indexOf('body:') : block.indexOf('})') + 2)
        expect(config, `${name} 的 ai-api fetch 缺 credentials`).toContain("credentials: 'include'")
      }
    }
  })
})
