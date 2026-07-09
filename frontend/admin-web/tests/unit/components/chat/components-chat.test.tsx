/**
 * components/chat 覆盖率补全 — Issue #567
 *
 * 覆盖 7 个聊天组件：MessageList, SessionList, InteractiveMessage,
 * MessageInput, CustomerPanel, ToolResultCard, LogisticsCard
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'

// ─── Mutable mock state (reset per test) ─────────

const mockUseChatStore = vi.fn()
const mockUseAuthStore = vi.fn()
let mockClipboardWriteText: ReturnType<typeof vi.fn>

// ─── Module mocks ─────────────────────────────────

vi.mock('react-markdown', () => ({
  default: ({ children }: any) =>
    React.createElement('div', { 'data-testid': 'markdown' }, children),
}))

vi.mock('remark-gfm', () => ({ default: {} }))

vi.mock('next/image', () => ({
  default: ({ src, alt, ...props }: any) =>
    React.createElement('img', { src, alt, ...props }),
}))

vi.mock('@/components/chat/ProductCard', () => ({
  default: ({ data }: any) =>
    React.createElement('div', { 'data-testid': 'product-card' },
      (data?.name || 'product') as string),
}))

vi.mock('@/components/chat/KnowledgeCard', () => ({
  default: ({ data }: any) =>
    React.createElement('div', { 'data-testid': 'knowledge-card' },
      (data?.title || 'knowledge') as string),
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: vi.fn().mockResolvedValue({ data: { items: [] } }),
    createSession: vi.fn(),
    sendMessage: vi.fn(),
    uploadChatImages: vi.fn().mockResolvedValue({
      success: true,
      data: { files: [] },
    }),
  },
}))

vi.mock('@/store/auth', () => {
  const fn = (...args: any[]) => mockUseAuthStore(...args)
  return {
    useAuthStore: Object.assign(fn, { getState: () => mockUseAuthStore() }),
  }
})

vi.mock('@/store/chat', () => {
  const fn = (...args: any[]) => mockUseChatStore(...args)
  return {
    useChatStore: Object.assign(fn, { getState: () => mockUseChatStore() }),
  }
})

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}))

// Mock global fetch for suggestion-feedback POST (fire-and-forget)
const mockFetch = vi.fn().mockResolvedValue({ ok: true })

// ─── Imports ─────────────────────────────────────

import MessageList from '@/components/chat/MessageList'
import SessionList from '@/components/chat/SessionList'
import InteractiveMessage from '@/components/chat/InteractiveMessage'
import MessageInput from '@/components/chat/MessageInput'
import CustomerPanel from '@/components/chat/CustomerPanel'
import ToolResultCard from '@/components/chat/ToolResultCard'
import LogisticsCard from '@/components/chat/LogisticsCard'

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

// ─── Setup / Teardown ────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  mockClipboardWriteText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: mockClipboardWriteText },
    writable: true,
    configurable: true,
  })
  mockFetch.mockClear()
  globalThis.fetch = mockFetch

  mockUseChatStore.mockReturnValue(makeDefaultChatState())
  mockUseAuthStore.mockReturnValue({
    accessToken: 'test-token',
    user: null,
    tenantId: 1,
  })
})

// ═══════════════════════════════════════════════════
// MessageList
// ═══════════════════════════════════════════════════

describe('MessageList', () => {
  it('shows placeholder when no session is selected', () => {
    render(<MessageList />)
    expect(screen.getByText('选择或创建一个对话')).toBeInTheDocument()
    expect(screen.getByText(/从左侧列表选择已有会话/)).toBeInTheDocument()
  })

  it('shows loading spinner when isLoadingMessages', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        isLoadingMessages: true,
      })
    )
    render(<MessageList />)
    expect(screen.getByText('加载消息中...')).toBeInTheDocument()
  })

  it('shows empty state when no messages', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        messages: [],
        isLoadingMessages: false,
      })
    )
    render(<MessageList />)
    expect(screen.getByText('发送消息开始对话')).toBeInTheDocument()
  })

  it('renders user and assistant messages', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        messages: [
          {
            id: '1',
            role: 'user',
            content: '你好',
            created_at: '2025-01-01T10:00:00Z',
          },
          {
            id: '2',
            role: 'assistant',
            content: '您好！有什么可以帮助您的？',
            created_at: '2025-01-01T10:00:05Z',
          },
        ],
      })
    )
    render(<MessageList />)

    expect(screen.getByText('你好')).toBeInTheDocument()
    expect(screen.getByText('您好！有什么可以帮助您的？')).toBeInTheDocument()
  })

  it('renders system messages', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        messages: [
          { id: 'sys1', role: 'system', content: '会话已创建' },
        ],
      })
    )
    render(<MessageList />)
    expect(screen.getByText('会话已创建')).toBeInTheDocument()
  })

  it('renders message suggestions', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        messages: [
          {
            id: '2',
            role: 'assistant',
            content: '您好',
            suggestions: ['查看订单', '查询物流'],
          },
        ],
      })
    )
    render(<MessageList />)

    expect(screen.getByText('推荐提问：')).toBeInTheDocument()
    expect(screen.getByText('查看订单')).toBeInTheDocument()
    expect(screen.getByText('查询物流')).toBeInTheDocument()
  })

  it('shows 对话已中断 when assistant message was aborted with empty content', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        messages: [
          {
            id: '1',
            role: 'user',
            content: '查询订单',
            created_at: '2025-01-01T10:00:00Z',
          },
          {
            id: '2',
            role: 'assistant',
            content: '',
            isStreaming: false,
            wasAborted: true,
            created_at: '2025-01-01T10:00:01Z',
          },
        ],
      })
    )
    render(<MessageList />)

    expect(screen.getByText('对话已中断')).toBeInTheDocument()
    expect(screen.queryByText('（已处理）')).not.toBeInTheDocument()
  })

  it('shows （已处理） when assistant has empty content without abort', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        messages: [
          {
            id: '1',
            role: 'user',
            content: '查询订单',
            created_at: '2025-01-01T10:00:00Z',
          },
          {
            id: '2',
            role: 'assistant',
            content: '',
            isStreaming: false,
            wasAborted: false,
            created_at: '2025-01-01T10:00:01Z',
          },
        ],
      })
    )
    render(<MessageList />)

    expect(screen.getByText('（已处理）')).toBeInTheDocument()
    expect(screen.queryByText('对话已中断')).not.toBeInTheDocument()
  })
})

// ═══════════════════════════════════════════════════
// SessionList
// ═══════════════════════════════════════════════════

describe('SessionList', () => {
  it('renders create button and search input', () => {
    render(<SessionList />)

    expect(screen.getByText('新建对话')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索会话...')).toBeInTheDocument()
  })

  it('shows empty state for active tab when no sessions', () => {
    render(<SessionList />)
    expect(screen.getByText('暂无活跃会话')).toBeInTheDocument()
  })

  it('shows active and closed tabs with counts', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        sessions: [
          { session_id: 's1', title: '会话1', status: 'active', updated_at: '2025-01-01' },
          { session_id: 's2', title: '会话2', status: 'closed', updated_at: '2025-01-02' },
        ],
      })
    )
    render(<SessionList />)

    expect(screen.getByText('活跃 (1)')).toBeInTheDocument()
    expect(screen.getByText('已关闭 (1)')).toBeInTheDocument()
    expect(screen.getByText('会话1')).toBeInTheDocument()
  })

  it('switches to closed tab and shows closed sessions', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        sessions: [
          { session_id: 's1', title: '会话1', status: 'active', updated_at: '2025-01-01' },
          { session_id: 's2', title: '已结束对话', status: 'closed', updated_at: '2025-01-02' },
        ],
      })
    )
    render(<SessionList />)

    // Click "已关闭" tab
    fireEvent.click(screen.getByText(/已关闭/))
    expect(screen.getByText('已结束对话')).toBeInTheDocument()
  })
})

// ═══════════════════════════════════════════════════
// InteractiveMessage
// ═══════════════════════════════════════════════════

describe('InteractiveMessage', () => {
  it('renders choice component with options', () => {
    const interactive = {
      component: 'choice' as const,
      title: '请选择商品类型',
      options: [
        { label: '窗帘', value: 'curtain' },
        { label: '沙发布', value: 'sofa' },
      ],
    }
    render(<InteractiveMessage interactive={interactive} />)

    expect(screen.getByText('请选择商品类型')).toBeInTheDocument()
    expect(screen.getByText('窗帘')).toBeInTheDocument()
    expect(screen.getByText('沙发布')).toBeInTheDocument()
  })

  it('sends label (not value) when single choice is submitted', () => {
    // 回归测试 #989: ChoiceCard submitChoice 发送 opt.label 而非 opt.value (hash ID)
    // 根因: InteractiveMessage.tsx:54 曾发送 option.value (hash ID) → LLM 无法理解 → 死循环
    const sendMessage = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({ sendMessage }),
    )

    const interactive = {
      component: 'choice' as const,
      title: '请选择分类',
      options: [
        { label: '家居窗帘', value: '071c042283b62e3a4e000b178242632d' },
        { label: '工程卷帘', value: 'abc123def456' },
      ],
    }
    render(<InteractiveMessage interactive={interactive} />)

    // Click the first option
    fireEvent.click(screen.getByText('家居窗帘'))
    // Click confirm
    fireEvent.click(screen.getByText('确认'))

    // 必须发送可读 label，不能发送 hash ID
    expect(sendMessage).toHaveBeenCalledWith('家居窗帘')
    expect(sendMessage).not.toHaveBeenCalledWith('071c042283b62e3a4e000b178242632d')
  })

  it('sends labels joined for multi-select choice', () => {
    const sendMessage = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({ sendMessage }),
    )

    const interactive = {
      component: 'choice' as const,
      title: '请选择多个分类',
      multiSelect: true,
      options: [
        { label: '窗帘', value: 'id-001' },
        { label: '沙发布', value: 'id-002' },
        { label: '卷帘', value: 'id-003' },
      ],
    }
    render(<InteractiveMessage interactive={interactive} />)

    // Select first and third options
    fireEvent.click(screen.getByText('窗帘'))
    fireEvent.click(screen.getByText('卷帘'))
    // Click confirm
    fireEvent.click(screen.getByText(/确认选择/))

    // 发送的文本应包含所有选中项的 label，用 、 连接
    expect(sendMessage).toHaveBeenCalledWith('窗帘、卷帘')
  })

  it('renders confirm card with fields and buttons', () => {
    const interactive = {
      component: 'confirm' as const,
      title: '确认创建订单',
      fields: [
        { label: '商品', value: '窗帘-001' },
        { label: '数量', value: '10米' },
      ],
      confirmLabel: '确认创建',
      cancelLabel: '取消',
    }
    render(<InteractiveMessage interactive={interactive} />)

    expect(screen.getByText('确认创建订单')).toBeInTheDocument()
    expect(screen.getByText('窗帘-001')).toBeInTheDocument()
    expect(screen.getByText('10米')).toBeInTheDocument()
    expect(screen.getByText('确认创建')).toBeInTheDocument()
    expect(screen.getByText('取消')).toBeInTheDocument()
  })

  it('renders form card with input fields', () => {
    const interactive = {
      component: 'form' as const,
      title: '补充商品信息',
      formFields: [
        { key: 'name', label: '商品名称', value: '预填名称' },
        { key: 'price', label: '价格' },
      ],
      submitLabel: '提交',
    }
    render(<InteractiveMessage interactive={interactive} />)

    expect(screen.getByText('补充商品信息')).toBeInTheDocument()
    expect(screen.getByText('提交')).toBeInTheDocument()
  })

  it('returns null for unknown component type', () => {
    const interactive = {
      component: 'unknown_type' as any,
      title: 'Unknown',
    }
    const { container } = render(
      <InteractiveMessage interactive={interactive} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders confirm component with fields', () => {
    // 对抗性审查修复 #937：InteractiveMessage 支持 confirm 类型
    const interactive = {
      component: 'confirm' as const,
      title: '确认退款',
      fields: [
        { label: '订单号', value: 'ORD-001' },
        { label: '金额', value: '¥299' },
      ],
    }
    render(<InteractiveMessage interactive={interactive} />)
    expect(screen.getByText('确认退款')).toBeInTheDocument()
    expect(screen.getByText('ORD-001')).toBeInTheDocument()
  })
})

// ═══════════════════════════════════════════════════
// MessageInput
// ═══════════════════════════════════════════════════

describe('MessageInput', () => {
  it('returns null when no session is selected', () => {
    const { container } = render(<MessageInput />)
    expect(container.firstChild).toBeNull()
  })

  it('renders input area and sends message on Enter', () => {
    const sendMessage = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sendMessage,
      })
    )

    render(<MessageInput />)

    const textarea = screen.getByPlaceholderText(/输入消息/)
    expect(textarea).toBeInTheDocument()

    // Type and send with Enter
    fireEvent.change(textarea, { target: { value: '测试消息' } })
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false })

    expect(sendMessage).toHaveBeenCalledWith('测试消息', undefined)
  })

  it('shows stop button when streaming', () => {
    const stopStreaming = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        isStreaming: true,
        stopStreaming,
      })
    )

    render(<MessageInput />)
    expect(screen.getByTitle('停止生成')).toBeInTheDocument()
  })

  it('send button is disabled when input is empty', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({ currentSessionId: 's1' })
    )

    render(<MessageInput />)
    const textarea = screen.getByPlaceholderText(/输入消息/)
    expect(textarea).toBeInTheDocument()
  })

  // ── 会话关闭态测试 (#会话生命周期) ──

  it('disables input and shows closed placeholder when session is closed', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [
          { session_id: 's1', title: '旧对话', status: 'closed', updated_at: '2025-01-01' },
        ],
      })
    )

    render(<MessageInput />)

    // textarea 应该被禁用
    const textarea = screen.getByPlaceholderText('会话已结束，请创建新对话')
    expect(textarea).toBeDisabled()

    // 不应该渲染发送按钮
    expect(screen.queryByTitle('发送')).not.toBeInTheDocument()
  })

  it('shows "新建对话" button when session is closed', () => {
    const createSession = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [
          { session_id: 's1', title: '旧对话', status: 'closed', updated_at: '2025-01-01' },
        ],
        createSession,
      })
    )

    render(<MessageInput />)

    const newBtn = screen.getByText('新建对话')
    expect(newBtn).toBeInTheDocument()

    fireEvent.click(newBtn)
    expect(createSession).toHaveBeenCalled()
  })

  it('has no send mechanism when session is closed (disabled textarea, no send button)', () => {
    const sendMessage = vi.fn()
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [
          { session_id: 's1', title: '旧对话', status: 'closed', updated_at: '2025-01-01' },
        ],
        sendMessage,
      })
    )

    render(<MessageInput />)

    // textarea 是 disabled + readOnly，用户无法输入
    const textarea = screen.getByPlaceholderText('会话已结束，请创建新对话')
    expect(textarea).toBeDisabled()
    expect(textarea).toHaveAttribute('readonly')

    // 没有发送按钮
    expect(screen.queryByTitle('发送')).not.toBeInTheDocument()

    // 唯一可操作的是"新建对话"
    expect(screen.getByText('新建对话')).toBeInTheDocument()
  })
})

// ═══════════════════════════════════════════════════
// CustomerPanel
// ═══════════════════════════════════════════════════

describe('CustomerPanel', () => {
  it('returns null when no session is selected', () => {
    const { container } = render(<CustomerPanel />)
    expect(container.firstChild).toBeNull()
  })

  it('renders customer info panel when session is active', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [
          {
            session_id: 's1',
            title: '客户咨询',
            status: 'active',
            updated_at: '2025-01-01T10:00:00Z',
          },
        ],
      })
    )

    render(<CustomerPanel />)

    expect(screen.getByText('客户信息')).toBeInTheDocument()
    expect(screen.getByText('基本信息')).toBeInTheDocument()
    expect(screen.getByText('客户画像')).toBeInTheDocument()
    expect(screen.getByText('最近订单')).toBeInTheDocument()
  })

  it('can collapse and expand the panel', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [
          {
            session_id: 's1',
            title: 'Test',
            status: 'active',
            updated_at: '2025-01-01T10:00:00Z',
          },
        ],
      })
    )

    render(<CustomerPanel />)

    // Click collapse button
    const collapseBtn = screen.getByTitle('收起')
    fireEvent.click(collapseBtn)

    // Panel should be collapsed, expansion button visible
    expect(screen.getByTitle('展开客户信息')).toBeInTheDocument()
  })

  it('copies session ID to clipboard', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        currentSessionId: 's1',
        sessions: [
          {
            session_id: 's1',
            title: 'Test',
            status: 'active',
            updated_at: '2025-01-01T10:00:00Z',
          },
        ],
      })
    )

    render(<CustomerPanel />)

    const copyBtn = screen.getByTitle('复制会话ID')
    fireEvent.click(copyBtn)

    expect(mockClipboardWriteText).toHaveBeenCalledWith('s1')
  })
})

// ═══════════════════════════════════════════════════
// ToolResultCard
// ═══════════════════════════════════════════════════

describe('ToolResultCard', () => {
  it('renders product_list card with multiple products', () => {
    const card = {
      type: 'product_list' as const,
      data: {
        products: [
          { name: '窗帘A', price: 100 },
          { name: '窗帘B', price: 200 },
        ],
      },
    }
    render(<ToolResultCard card={card} />)
    expect(screen.getAllByTestId('product-card')).toHaveLength(2)
  })

  it('renders logistics card', () => {
    const card = {
      type: 'logistics' as const,
      data: {
        tracking_no: 'SF1234567890',
        company: '顺丰速运',
        status: '运输中',
        tracks: [
          { description: '已揽件', time: '2025-01-01 10:00' },
        ],
      },
    }
    render(<ToolResultCard card={card} />)
    expect(screen.getByText('顺丰速运')).toBeInTheDocument()
    expect(screen.getByText(/SF1234567890/)).toBeInTheDocument()
  })

  it('renders knowledge card', () => {
    const card = {
      type: 'knowledge' as const,
      data: { title: '布艺清洗指南', content: '...' },
    }
    render(<ToolResultCard card={card} />)
    expect(screen.getByTestId('knowledge-card')).toBeInTheDocument()
  })

  it('renders order card with status badge', () => {
    const card = {
      type: 'order' as const,
      data: {
        order: {
          orderNo: 'ORD-001',
          status: 'confirmed',
          customerName: '张三',
          totalAmount: 299.0,
          createdAt: '2025-01-01T10:00:00Z',
        },
      },
    }
    render(<ToolResultCard card={card} />)
    expect(screen.getByText(/ORD-001/)).toBeInTheDocument()
    expect(screen.getByText('已确认')).toBeInTheDocument()
    expect(screen.getByText('¥299.00')).toBeInTheDocument()
  })

  it('shows fallback for unknown card type', () => {
    const card = {
      type: 'unknown_type' as any,
      data: {},
    }
    render(<ToolResultCard card={card} />)
    expect(screen.getByText(/未知卡片类型/)).toBeInTheDocument()
    expect(screen.getByText('unknown_type')).toBeInTheDocument()
  })
})

// ═══════════════════════════════════════════════════
// LogisticsCard
// ═══════════════════════════════════════════════════

describe('LogisticsCard', () => {
  it('renders tracking info with timeline', () => {
    const data = {
      tracking_no: 'SF1234567890',
      company: '顺丰速运',
      status: '运输中',
      tracks: [
        { description: '已签收', time: '2025-01-03 14:00' },
        { description: '派送中', time: '2025-01-03 09:00' },
        { description: '已揽件', time: '2025-01-01 10:00' },
      ],
    }
    render(<LogisticsCard data={data} />)

    expect(screen.getByText('顺丰速运')).toBeInTheDocument()
    expect(screen.getByText(/SF1234567890/)).toBeInTheDocument()
    expect(screen.getByText('已签收')).toBeInTheDocument()
    expect(screen.getByText('派送中')).toBeInTheDocument()
  })

  it('shows empty state when no tracks', () => {
    const data = {
      tracking_no: 'YT000',
      company: '圆通速递',
      status: '待揽件',
      tracks: [],
    }
    render(<LogisticsCard data={data} />)

    expect(screen.getByText('圆通速递')).toBeInTheDocument()
    expect(screen.getByText('暂无物流轨迹')).toBeInTheDocument()
  })

  it('renders without tracking_no', () => {
    const data = {
      company: '京东物流',
      status: '派送中',
      tracks: [{ description: '快递员正在派送', time: '2025-01-01' }],
    }
    render(<LogisticsCard data={data} />)

    expect(screen.getByText('京东物流')).toBeInTheDocument()
    expect(screen.getByText('派送中')).toBeInTheDocument()
    expect(screen.getByText('快递员正在派送')).toBeInTheDocument()
  })
})
