// case_ids: CH-001, CH-002, CH-003
/**
 * SessionInsight（会话洞察面板）组件测试 — Issue #2567
 *
 * 面板按米宝（B端工作助手）定位重构为工作台账：
 *   概览（身份+业务域计数）/ 待确认横幅 / 处理进度时间线 / 业务对象分组标签 / 会话信息。
 * 覆盖：抽屉开关、空状态、工具时间线（写徽标 + 失败 suggestion）、
 * 待确认检测、实体提取与点击追问、会话标识复制。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// ─── Mutable mock state (reset per test) ─────────

const mockUseChatStore = vi.fn()
let mockClipboardWriteText: ReturnType<typeof vi.fn>

vi.mock('@/store/chat', () => {
  const fn = (...args: any[]) => mockUseChatStore(...args)
  return {
    useChatStore: Object.assign(fn, { getState: () => mockUseChatStore() }),
  }
})

// ─── Imports under test ──────────────────────────

import SessionInsight from '@/components/chat/SessionInsight'

// ─── Helpers ─────────────────────────────────────

function makeDefaultChatState(overrides: Record<string, unknown> = {}) {
  return {
    sessions: [] as any[],
    currentSessionId: null as string | null,
    messages: [] as any[],
    isStreaming: false,
    isLoadingSessions: false,
    isLoadingMessages: false,
    searchKeyword: '',
    setSearchKeyword: vi.fn(),
    createSession: vi.fn(),
    selectSession: vi.fn(),
    sendMessage: vi.fn(),
    closeSession: vi.fn(),
    reopenSession: vi.fn(),
    stopStreaming: vi.fn(),
    clearCurrentSession: vi.fn(),
    fetchSessions: vi.fn(),
    fetchQuickActions: vi.fn(),
    abortController: null,
    quickActions: [],
    isLoadingQuickActions: false,
    error: null,
    ...overrides,
  }
}

function makeSession(overrides: Record<string, unknown> = {}) {
  return {
    session_id: 's1',
    title: 't',
    status: 'active',
    message_count: 1,
    updated_at: '2025-01-01T10:00:00Z',
    created_at: '2025-01-01T10:00:00Z',
    ...overrides,
  }
}

// ─── Setup / Teardown ────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockClipboardWriteText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: mockClipboardWriteText },
    writable: true,
    configurable: true,
  })
  mockUseChatStore.mockReturnValue(makeDefaultChatState())
})

// ═══════════════════════════════════════════════════

describe('SessionInsight', () => {
  it('returns null when no session is selected', () => {
    const { container } = render(<SessionInsight isOpen onClose={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows 米宝 identity, session stats and copies session id', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ title: '客户咨询', message_count: 12, updated_at: '2025-01-01T10:30:00Z' })],
        messages: [
          { id: 'm1', role: 'user', content: '查订单' },
          { id: 'm2', role: 'assistant', content: '好的' },
        ],
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    // 概览：面板标题 + 米宝身份 + 状态 + 消息计数
    expect(screen.getByText('会话洞察')).toBeInTheDocument()
    expect(screen.getByText('米宝 · B端工作助手')).toBeInTheDocument()
    expect(screen.getByText('进行中')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()

    // 会话标识复制
    fireEvent.click(screen.getByTitle('复制会话标识'))
    expect(mockClipboardWriteText).toHaveBeenCalledWith('s1')
  })

  it('renders tool activity timeline with labels, write badge and error suggestion', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 3 })],
        messages: [
          {
            id: 'm1', role: 'assistant', content: '处理中',
            tool_calls: [
              { name: 'order_query', input: { order_id: 'ORD-1' }, status: 'completed' },
              { name: 'order_manage', input: { order_id: 'ORD-1', action: 'confirm' }, status: 'completed' },
              { name: 'aftersale_query', input: {}, status: 'error', result: { success: false, suggestion: '请检查工单号' } },
            ],
          },
        ],
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    // 处理进度时间线：工具中文名
    expect(screen.getByText('处理进度')).toBeInTheDocument()
    expect(screen.getByText('查询订单')).toBeInTheDocument()
    expect(screen.getByText('订单管理')).toBeInTheDocument()
    expect(screen.getByText('查询售后')).toBeInTheDocument()
    // 写操作徽标：order_manage 标记「写」
    expect(screen.getAllByText('写')).toHaveLength(1)
    // 失败工具展示 suggestion
    expect(screen.getByText('请检查工单号')).toBeInTheDocument()
    // 概览领域计数 chips（order ×2 + aftersale ×1）
    expect(screen.getByText('订单 ×2')).toBeInTheDocument()
    expect(screen.getByText('售后 ×1')).toBeInTheDocument()
  })

  it('shows empty processing state when no tool calls', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ title: '新对话', message_count: 2, updated_at: '2025-01-01T10:30:00Z' })],
        messages: [
          { id: 'm1', role: 'user', content: '你好' },
          { id: 'm2', role: 'assistant', content: '您好！有什么可以帮助您的？' },
        ],
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    expect(screen.getByText(/暂无处理记录/)).toBeInTheDocument()
  })

  it('shows pending-confirm banner for unanswered interactive', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 2 })],
        messages: [
          { id: 'm1', role: 'user', content: '创建订单' },
          { id: 'm2', role: 'assistant', content: '', interactive: { component: 'confirm', title: '确认创建订单' } },
        ],
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    expect(screen.getByText('米宝在等你确认')).toBeInTheDocument()
    expect(screen.getByText('确认创建订单')).toBeInTheDocument()
  })

  it('hides pending-confirm banner after user answers', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 4 })],
        messages: [
          { id: 'm1', role: 'user', content: '创建订单' },
          { id: 'm2', role: 'assistant', content: '', interactive: { component: 'confirm', title: '确认创建订单' } },
          { id: 'm3', role: 'user', content: '确认' },
          { id: 'm4', role: 'assistant', content: '订单已创建' },
        ],
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    expect(screen.queryByText('米宝在等你确认')).not.toBeInTheDocument()
  })

  // ── 业务对象（实体提取 + 点击追问）──

  it('extracts order entities from persisted tool args and follows up on click', () => {
    const sendMessage = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 3 })],
        messages: [
          {
            id: 'm1', role: 'assistant', content: '查到订单',
            tool_calls: [
              { tool: 'order_query', args: { order_id: 'ORD-001' } },
            ],
          },
        ],
        sendMessage,
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    // 业务对象区展示了订单实体（带类型前缀）
    expect(screen.getByText('业务对象')).toBeInTheDocument()
    expect(screen.getByText('订单 ORD-001')).toBeInTheDocument()

    // 点击标签应发送追问
    fireEvent.click(screen.getByText('订单 ORD-001'))
    expect(sendMessage).toHaveBeenCalledWith('查看订单 ORD-001')
  })

  it('extracts product entities from card data', () => {
    const sendMessage = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 2 })],
        messages: [
          {
            id: 'm1', role: 'assistant', content: '商品结果',
            cards: [
              { type: 'product_list', data: { products: [{ name: '遮光窗帘' }, { name: '透光纱帘' }] } },
            ],
          },
        ],
        sendMessage,
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    expect(screen.getByText('商品 遮光窗帘')).toBeInTheDocument()
    expect(screen.getByText('商品 透光纱帘')).toBeInTheDocument()

    fireEvent.click(screen.getByText('商品 遮光窗帘'))
    expect(sendMessage).toHaveBeenCalledWith('查看 遮光窗帘 详情')
  })

  it('extracts logistics entities from tool input and follows up via title', () => {
    const sendMessage = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 1 })],
        messages: [
          {
            id: 'm1', role: 'assistant', content: '物流',
            tool_calls: [
              { name: 'logistics_track', input: { tracking_no: 'SF1234567890' }, status: 'completed' },
            ],
          },
        ],
        sendMessage,
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    expect(screen.getAllByText(/SF1234567890/).length).toBeGreaterThanOrEqual(1)

    // 点击业务对象中的物流标签
    const tag = screen.getByTitle('点击追问：查询物流 SF1234567890')
    fireEvent.click(tag)
    expect(sendMessage).toHaveBeenCalledWith('查询物流 SF1234567890')
  })

  it('deduplicates entities across cards and tool_calls', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 4 })],
        messages: [
          {
            id: 'm1', role: 'assistant', content: 'a',
            tool_calls: [{ name: 'order_query', input: { order_id: 'ORD-001' }, status: 'completed' }],
            cards: [{ type: 'order', data: { order: { orderNo: 'ORD-001' } } }],
          },
        ],
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    // ORD-001 在 tool_call 和 card 中各出现一次，实体去重后业务对象区只展示 1 个标签
    const occurrences = screen.getAllByText(/ORD-001/)
    expect(occurrences).toHaveLength(1)
  })

  it('shows empty business-objects state when no entities', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ message_count: 1 })],
        messages: [
          { id: 'm1', role: 'assistant', content: '你好，有什么可以帮您？' },
        ],
      })
    )

    render(<SessionInsight isOpen onClose={vi.fn()} />)

    // 业务对象为空
    expect(screen.getByText(/暂无业务对象/)).toBeInTheDocument()
  })

  it('drawer opens when isOpen=true and hides when isOpen=false', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [makeSession({ title: 'test', updated_at: '2025-01-01T10:30:00Z' })],
        messages: [],
      })
    )

    const { rerender } = render(<SessionInsight isOpen onClose={vi.fn()} />)
    // 展开：抽屉可见 + 遮罩存在
    expect(screen.getByTestId('session-insight-drawer')).toHaveClass('translate-x-0')
    expect(screen.getByTestId('session-insight-overlay')).toBeInTheDocument()

    // 收起：抽屉移出 + 遮罩消失
    rerender(<SessionInsight isOpen={false} onClose={vi.fn()} />)
    expect(screen.getByTestId('session-insight-drawer')).toHaveClass('translate-x-full')
    expect(screen.queryByTestId('session-insight-overlay')).not.toBeInTheDocument()
  })
})
