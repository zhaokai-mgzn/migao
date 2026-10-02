// case_ids: UI-079, UI-080
/**
 * 米宝（B 端）对话渲染层——issue #5952 的两条面：
 *
 * A. **客户端打字机**（UI-079；用户 2026-10-02 裁定「选 2」）：组件接入 `useTypewriter` 后，
 *    流式期间 `data-revealed`（可见字符数）必须**从 0 长到全长**，结束/中断 ⇒ 立刻全文。
 *    ⚠️ 本文件只判「组件是否真接入」；逐字与「收口替换」的细粒度判据在
 *    `tests/unit/hooks/use-typewriter.test.tsx`（组件层用真实计时器，避免与测试库的
 *    `waitFor` 轮询互锁）。
 *
 * B. **不向用户暴露 tool**（UI-080；对齐 C 端先例 issue #2857）：带 `tool_calls` 的消息
 *    只许出现**人性化进度文案**，工具名 / 入参 / 结果一个都不许进 DOM。
 *
 * 红证（修前红）：
 * - UI-079 组：`AIMessageContent` 未接 `useTypewriter` 时 `data-revealed` 属性**根本不存在**
 *   ⇒ 首条断言当场红（组件级 `grep -n "useTypewriter" src/components/chat/MessageList.tsx` = 0 命中）。
 * - UI-080 组：把 `AIMessageContent` 的 `tool_calls` 分支改回「渲染工具名 + JSON.stringify(input)」
 *   ⇒ 工具名 / 入参断言当场红（判据是具名字符串，不是 `not None` 这类弱断言）。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import type { ChatMessage } from '@/types'

// ===========================================================================
// Mocks
// ===========================================================================
const mockChatStore = {
  messages: [] as ChatMessage[],
  currentSessionId: 's1' as string | null,
  isLoadingMessages: false,
  isStreaming: false,
  sessions: [] as Array<{ id: string }>,
}

vi.mock('@/store/chat', () => ({
  useChatStore: (selector?: (state: typeof mockChatStore) => unknown) => {
    if (typeof selector === 'function') return selector(mockChatStore)
    return mockChatStore
  },
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

vi.mock('react-markdown', () => ({
  default: ({ children }: { children?: React.ReactNode }) => (
    <span data-testid="md-content">{children}</span>
  ),
}))

vi.mock('remark-gfm', () => ({ default: () => {} }))

// 打字机在组件层默认**不逐步**（= 立刻等于全文）：组件级只判「接没接上 + 收没收敛」，
// 逐字细节由 tests/unit/hooks/use-typewriter.test.tsx 判。理由不只是分层 —— 真实 hook 的
// `setInterval` 会以 50 次/秒持续触发 React 更新，把 `waitFor`/`findBy*` 的轮询饿死
// （实测：`findByText('正在处理您的请求...')` 在 5s 内一次都没拿到窗口 ⇒ 假红）。
const { mockUseTypewriter } = vi.hoisted(() => ({ mockUseTypewriter: vi.fn((text: string) => text) }))
vi.mock('@/hooks/use-typewriter', () => ({
  TYPEWRITER_INTERVAL_MS: 20,
  // 默认替身即「不逐步」（返回值写在工厂里 —— `vi.clearAllMocks()` 会清掉
  // `mockImplementation`，写在测试里会被 beforeEach 清空 ⇒ 假红，实测踩过）
  useTypewriter: mockUseTypewriter,
}))

vi.mock('@/components/chat/InteractiveMessage', () => ({ default: () => null }))
vi.mock('@/components/chat/WelcomePanel', () => ({ default: () => null }))
vi.mock('@/components/chat/ToolResultCard', () => ({ default: () => null }))

import MessageList from '@/components/chat/MessageList'

const FULL_TEXT = '米宝回复的第一句话，后面还有很多字，需要足够长才能观察到逐字揭示的过程。'

function aiMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'ai-1',
    role: 'assistant',
    content: '',
    isStreaming: false,
    created_at: '2026-10-02T10:00:00+08:00',
    ...overrides,
  }
}

function revealedAttr(): string | null {
  return document.querySelector('[data-revealed]')?.getAttribute('data-revealed') ?? null
}

beforeEach(() => {
  // ⚠️ 不能用 `vi.clearAllMocks()`：它会连替身的默认实现一起清掉 ⇒ 默认替身返回值变
  // `undefined` ⇒ 渲染成空白（实测踩过）。这里只清调用记录。
  mockUseTypewriter.mockClear()
  mockChatStore.messages = []
  mockChatStore.currentSessionId = 's1'
  mockChatStore.isLoadingMessages = false
})

// ===========================================================================
// A. 客户端打字机（组件接入）
// ===========================================================================
describe('MessageList — UI-079 客户端打字机接入', () => {
  it('UI-079 流式回复（真实打字机）：可见字符数从 0 增长到全长（不是一次到位）', async () => {
    // 本用例是唯一要真 hook 的：临时换成真实现（`importActual` 保证「测的是真对象」，
    // 不是把判据钉在替身上），跑完即还原。
    const actual = await vi.importActual<typeof import('@/hooks/use-typewriter')>('@/hooks/use-typewriter')
    mockUseTypewriter.mockImplementation(actual.useTypewriter)
    try {
      mockChatStore.messages = [aiMsg({ content: FULL_TEXT, isStreaming: true })]
      const view = render(<MessageList />)
      expect(revealedAttr()).toBe('0')
      await waitFor(() => {
        const n = Number(revealedAttr())
        expect(n).toBeGreaterThan(0)
        expect(n).toBeLessThan(FULL_TEXT.length)
      })
      await waitFor(() => {
        expect(revealedAttr()).toBe(String(FULL_TEXT.length))
      })
      expect(screen.getByTestId('md-content').textContent).toBe(FULL_TEXT)
      view.unmount()
    } finally {
      mockUseTypewriter.mockImplementation((text: string) => text)
    }
  })

  it('UI-079 流式结束 ⇒ 立刻等于全文（不再残留半截）', () => {
    mockChatStore.messages = [aiMsg({ content: FULL_TEXT, isStreaming: true })]
    const { rerender } = render(<MessageList />)
    expect(revealedAttr()).toBe(String(FULL_TEXT.length)) // 流式中 ⇒ 进度属性在（本文件用「不逐步」替身，故已满）

    // 后端 message_end：isStreaming=false 落到归属会话 ⇒ 立刻全文
    mockChatStore.messages = [aiMsg({ content: FULL_TEXT, isStreaming: false })]
    rerender(<MessageList />)

    expect(screen.getByTestId('md-content').textContent).toBe(FULL_TEXT)
    expect(revealedAttr()).toBeNull() // 非流式不再暴露进度属性
  })

  it('UI-079 中断（wasAborted=true）⇒ 立刻显示已收到的全文，不卡半截', () => {
    mockChatStore.messages = [
      aiMsg({ content: FULL_TEXT, isStreaming: false, wasAborted: true }),
    ]

    render(<MessageList />)

    expect(screen.getByTestId('md-content').textContent).toBe(FULL_TEXT)
    expect(screen.queryByText('对话已中断')).toBeNull()
  })

  it('UI-079 历史回放（非流式）⇒ 首帧即全文，不逐字', () => {
    mockChatStore.messages = [aiMsg({ content: FULL_TEXT, isStreaming: false })]
    render(<MessageList />)
    expect(screen.getByTestId('md-content').textContent).toBe(FULL_TEXT)
  })

  it('UI-079 切会话/重挂载 ⇒ 立即等于该会话全文（不从头再打一遍）', () => {
    mockChatStore.messages = [aiMsg({ id: 'h-1', content: FULL_TEXT, isStreaming: false })]
    const { unmount } = render(<MessageList />)
    expect(screen.getByTestId('md-content').textContent).toBe(FULL_TEXT)
    unmount()

    mockChatStore.currentSessionId = 's2'
    mockChatStore.messages = [aiMsg({ id: 'h-2', content: FULL_TEXT, isStreaming: false })]
    render(<MessageList />)
    expect(screen.getByTestId('md-content').textContent).toBe(FULL_TEXT)
  })
})

// ===========================================================================
// B. 不向用户暴露 tool（对齐 C 端先例 issue #2857）
// ===========================================================================
describe('MessageList — UI-080 不暴露 tool（仅可感知进度）', () => {
  const TOOL_NAME = 'order_query'
  const TOOL_ARG_VALUE = 'SO-2026-001'
  const TOOL_RESULT_VALUE = 'RESULT_SECRET_2026'

  /** 工具名 / 入参值 / 结果值 / 原始 JSON 形态都不许进 DOM */
  function expectNoToolDetails(container: HTMLElement) {
    const html = container.innerHTML
    expect(html).not.toContain(TOOL_NAME)
    expect(html).not.toContain(TOOL_ARG_VALUE)
    expect(html).not.toContain(TOOL_RESULT_VALUE)
    expect(html).not.toContain('tool_calls')
    expect(html).not.toContain('tool_name')
    expect(html).not.toContain('"input"')
    expect(html).not.toContain('"args"')
    // 具名断言：连「工具调用」这类技术词与原始 JSON 花括号入参都不出现
    expect(container.textContent).not.toContain('工具调用')
    expect(container.textContent).not.toContain('{"order_no"')
  }

  it('UI-080 工具执行中（无正文）⇒ 只有人性化进度，工具名/入参/结果一个都不出现', () => {
    mockChatStore.messages = [
      aiMsg({
        content: '',
        isStreaming: true,
        tool_calls: [
          { name: TOOL_NAME, input: { order_no: TOOL_ARG_VALUE }, status: 'running' },
        ],
      }),
    ]

    const { container } = render(<MessageList />)

    // 可感知的进度仍在（用户裁定的不是「让界面长时间无反馈」）；气泡内与气泡下可能各一处
    expect(screen.getAllByText('正在处理您的请求...').length).toBeGreaterThan(0)
    expectNoToolDetails(container)
  })

  it('UI-080 有正文 + 工具同时在场 ⇒ 正文照常显示，工具细节仍不可见', () => {
    mockChatStore.messages = [
      aiMsg({
        content: '已经帮您查到这笔订单了。',
        isStreaming: false,
        tool_calls: [
          {
            name: TOOL_NAME,
            input: { order_no: TOOL_ARG_VALUE },
            result: { secret: TOOL_RESULT_VALUE },
            status: 'completed',
          },
        ],
      }),
    ]

    const { container } = render(<MessageList />)

    expect(screen.getByTestId('md-content').textContent).toBe('已经帮您查到这笔订单了。')
    expectNoToolDetails(container)
  })

  it('UI-080 仅 tool_calls、无正文的历史消息 ⇒ 不显示工具名，也不假装有回复', () => {
    mockChatStore.messages = [
      aiMsg({
        content: '',
        isStreaming: false,
        tool_calls: [
          { name: TOOL_NAME, input: { order_no: TOOL_ARG_VALUE }, status: 'completed' },
        ],
      }),
    ]

    const { container } = render(<MessageList />)

    expect(screen.getByText('（已处理）')).toBeTruthy()
    expectNoToolDetails(container)
  })

  it('UI-080 工具失败（status=error）⇒ 静默处理，不弹工具名 / 不弹原始错误串', () => {
    mockChatStore.messages = [
      aiMsg({
        content: '查询没成功，您可以稍后再问一次。',
        isStreaming: false,
        tool_calls: [
          {
            name: TOOL_NAME,
            input: { order_no: TOOL_ARG_VALUE },
            result: { error: `Error: ${TOOL_RESULT_VALUE}` },
            status: 'error',
          },
        ],
      }),
    ]

    const { container } = render(<MessageList />)

    expect(screen.getByTestId('md-content').textContent).toBe('查询没成功，您可以稍后再问一次。')
    expectNoToolDetails(container)
  })
})
