// case_ids: UI-084
/**
 * 黄金策（B 端 admin-web）聊天回复的**软换行**渲染 —— issue #6346 / 用例 UI-084
 *
 * ## 治的形态
 *
 * `frontend/ai-agent-service/app/agents/agents/mibao.py` 的 `capabilities` 直答是**每行一条能力、
 * 行尾单个 `\n`**（用 `**强调**` 标重点）；而 `frontend/admin-web/src/components/chat/MessageList.tsx`
 * 的 `<ReactMarkdown remarkPlugins={[remarkGfm]}>` 没挂 breaks 语义 ⇒ CommonMark 把段落内的单个
 * `\n` 当**软换行（= 空格）** ⇒ 8 行能力清单被折成**一整段无分段长文**（用户 2026-10-05 实测截图：
 * 「这个回复是不是没排版」）。
 *
 * ## 判据（逐条能红）
 *
 * ① 含 3 个 `\n` 的助手回复 ⇒ 渲染出 **3 个 `<br>`**（软换行 = 真换行）；
 * ② 段落间的空行（`\n\n`）⇒ **两个 `<p>`**（块级语义不回归）；
 * ③ `**强调**` 仍走 `<strong>`（加粗没被这次改动弄丢）；
 * ④ 负控：**行内**单个 `*`（价格场景）不被当强调吞掉。
 *
 * 红证（修前红，§28.1 出口①）：把 `remarkPlugins={[remarkGfm, remarkBreaks]}` 里的 `remarkBreaks`
 * 临时摘掉再跑本文件 ⇒ 断言 ① 的 `<br>` 计数 `3 → 0` 当场红（实测读数写在 PR body）。
 *
 * 本文件**不 mock react-markdown**（判据必须打在真实渲染管线上）—— 与
 * `tests/unit/components/MessageList-typewriter.test.tsx`（那里 mock 了 markdown）分工不同。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import type { ChatMessage } from '@/types'

// ===========================================================================
// Mocks（store / api / 子组件；**不** mock react-markdown 与 remark 插件）
// ===========================================================================
const mockChatStore = {
  messages: [] as ChatMessage[],
  currentSessionId: 's1' as string | null,
  isLoadingMessages: false,
  isStreaming: false,
  sessions: [{ id: 's1' }] as Array<{ id: string }>,
}

vi.mock('@/store/chat', () => ({
  useChatStore: (selector?: (state: typeof mockChatStore) => unknown) =>
    typeof selector === 'function' ? selector(mockChatStore) : mockChatStore,
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: vi.fn(),
    createSession: vi.fn(),
    getHistory: vi.fn(),
  },
}))

vi.mock('@/lib/utils', () => ({
  cn: (...args: Array<string | undefined | false | null>) => args.filter(Boolean).join(' '),
}))

// 打字机在组件层默认「不逐步」= 立刻等于全文（细节判据在 tests/unit/hooks/use-typewriter.test.tsx）。
// 返回值写在工厂里：`vi.clearAllMocks()` 会清掉 `mockImplementation`（该文件注释有实测记录）。
vi.mock('@/hooks/use-typewriter', () => ({
  TYPEWRITER_INTERVAL_MS: 20,
  useTypewriter: (text: string) => text,
}))

vi.mock('@/components/chat/InteractiveMessage', () => ({ default: () => null }))
vi.mock('@/components/chat/WelcomePanel', () => ({ default: () => null }))
vi.mock('@/components/chat/ToolResultCard', () => ({ default: () => null }))

import MessageList from '@/components/chat/MessageList'

function aiMsg(content: string): ChatMessage {
  return {
    id: 'ai-soft-break-1',
    role: 'assistant',
    content,
    isStreaming: false,
    created_at: '2026-10-05T08:45:00+08:00',
  }
}

beforeEach(() => {
  mockChatStore.messages = []
  mockChatStore.currentSessionId = 's1'
  mockChatStore.isLoadingMessages = false
})

describe('MessageList — UI-084 软换行渲染', () => {
  it('段落内单个换行渲染成 <br>（能力清单不再被折成一整段）', () => {
    mockChatStore.messages = [
      aiMsg('您好！我是黄金策。\n📦 **订单与履约** - 订单/物流查询\n🏭 **生产与算料** - 工序库\n⚠️ 创建/修改类操作黄金策不做。'),
    ]
    const view = render(<MessageList />)
    const text = view.container.textContent || ''
    expect(text).toContain('订单与履约')
    expect(view.container.querySelectorAll('br')).toHaveLength(3)
    // 对照：整段仍是一个段落（软换行不产生块级分割）
    expect(view.container.querySelectorAll('p')).toHaveLength(1)
    view.unmount()
  })

  it('空行分段 ⇒ 两个 <p>（块级语义不回归）', () => {
    mockChatStore.messages = [aiMsg('第一段\n\n第二段')]
    const view = render(<MessageList />)
    expect(view.container.querySelectorAll('p')).toHaveLength(2)
    expect(view.container.querySelectorAll('br')).toHaveLength(0)
    view.unmount()
  })

  it('**强调** 仍走 <strong>（加粗没被这次改动弄丢）', () => {
    mockChatStore.messages = [aiMsg('📦 **订单与履约** - 订单/物流查询')]
    const view = render(<MessageList />)
    const strong = view.container.querySelector('strong')
    expect(strong?.textContent).toBe('订单与履约')
    view.unmount()
  })

  it('负控：行内单个 * 不被当强调吞掉', () => {
    mockChatStore.messages = [aiMsg('单价 ¥29/米 * 2.8 = 81.2')]
    const view = render(<MessageList />)
    expect(view.container.textContent).toContain('单价 ¥29/米 * 2.8 = 81.2')
    expect(view.container.querySelector('em')).toBeNull()
    view.unmount()
  })
})
