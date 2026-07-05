/**
 * MessageList 组件测试 — #954
 *
 * 覆盖：
 * - wasAborted=true 时显示"对话已中断"
 * - wasAborted=false/undefined 且 content 为空时显示"（已处理）"
 * - 正常有内容时不显示状态文案
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// ===========================================================================
// Mock useChatStore — 控制 messages 数据
// ===========================================================================
const mockChatStore = {
  messages: [] as any[],
  currentSessionId: null as string | null,
  isLoadingMessages: false,
  isStreaming: false,
}

vi.mock('@/store/chat', () => ({
  useChatStore: (selector?: (state: any) => any) => {
    if (typeof selector === 'function') return selector(mockChatStore)
    return mockChatStore
  },
}))

// ===========================================================================
// Mock sub-components
// ===========================================================================
vi.mock('@/components/chat/ToolResultCard', () => ({
  default: () => null,
}))

vi.mock('@/components/chat/InteractiveMessage', () => ({
  default: ({ interactive }: any) => null,
}))

// ===========================================================================
// Mock other dependencies
// ===========================================================================
vi.mock('@/store/auth', () => ({
  useAuthStore: {
    getState: () => ({ accessToken: 'test-token' }),
  },
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
  cn: (...args: (string | undefined | false | null)[]) => args.filter(Boolean).join(' '),
}))

vi.mock('react-markdown', () => ({
  default: ({ children }: any) => <span data-testid="md-content">{children}</span>,
}))

vi.mock('remark-gfm', () => ({
  default: () => { },
}))

import MessageList from '@/components/chat/MessageList'
import type { ChatMessage } from '@/types'

// ===========================================================================
// Helpers
// ===========================================================================
function makeAiMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'ai-1',
    role: 'assistant',
    content: '',
    isStreaming: false,
    created_at: '2025-01-01T00:00:00Z',
    ...overrides,
  }
}

// ===========================================================================
// Tests
// ===========================================================================
describe('MessageList — #954 中断文案', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset store mock
    mockChatStore.messages = []
    mockChatStore.currentSessionId = null
    mockChatStore.isLoadingMessages = false
  })

  it('BT-1: wasAborted=true 且 content 为空 → 显示"对话已中断"', () => {
    mockChatStore.currentSessionId = 's1'
    mockChatStore.messages = [
      makeAiMsg({ content: '', isStreaming: false, wasAborted: true }),
    ]

    render(<MessageList />)

    // 应显示"对话已中断"而不是"（已处理）"
    expect(screen.getByText('对话已中断')).toBeInTheDocument()
    expect(screen.queryByText('（已处理）')).not.toBeInTheDocument()
  })

  it('BT-3: wasAborted=false 且 content 为空 → 显示"（已处理）"兜底文案', () => {
    mockChatStore.currentSessionId = 's1'
    mockChatStore.messages = [
      makeAiMsg({ content: '', isStreaming: false, wasAborted: false }),
    ]

    render(<MessageList />)

    // 应显示"（已处理）"
    expect(screen.getByText('（已处理）')).toBeInTheDocument()
    expect(screen.queryByText('对话已中断')).not.toBeInTheDocument()
  })

  it('BT-3: wasAborted 未定义（undefined）且 content 为空 → 显示"（已处理）"兜底文案', () => {
    mockChatStore.currentSessionId = 's1'
    mockChatStore.messages = [
      makeAiMsg({ content: '', isStreaming: false, wasAborted: undefined }),
    ]

    render(<MessageList />)

    // 应显示"（已处理）"（向后兼容，wasAborted 未定义时保持原行为）
    expect(screen.getByText('（已处理）')).toBeInTheDocument()
  })

  it('BT-2: 正常有内容时显示实际内容，不显示任何状态文案', () => {
    mockChatStore.currentSessionId = 's1'
    mockChatStore.messages = [
      makeAiMsg({ content: '你好，这是正常回复', isStreaming: false }),
    ]

    render(<MessageList />)

    // 应显示实际内容
    expect(screen.getByTestId('md-content')).toHaveTextContent('你好，这是正常回复')
    // 不应显示任何状态文案
    expect(screen.queryByText('对话已中断')).not.toBeInTheDocument()
    expect(screen.queryByText('（已处理）')).not.toBeInTheDocument()
  })

  it('BT-1 边界：isStreaming=true 时不显示任何状态文案', () => {
    mockChatStore.currentSessionId = 's1'
    mockChatStore.messages = [
      makeAiMsg({ content: '', isStreaming: true, wasAborted: true }),
    ]

    render(<MessageList />)

    // 流式进行中，不应显示中断文案或已处理文案（应显示加载动画）
    expect(screen.queryByText('对话已中断')).not.toBeInTheDocument()
    expect(screen.queryByText('（已处理）')).not.toBeInTheDocument()
  })

  it('无会话时显示空状态', () => {
    mockChatStore.currentSessionId = null

    render(<MessageList />)

    expect(screen.getByText('选择或创建一个对话')).toBeInTheDocument()
  })
})
