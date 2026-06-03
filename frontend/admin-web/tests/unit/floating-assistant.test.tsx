/**
 * FloatingAssistant 组件测试
 *
 * 覆盖：
 * - 面板打开/关闭
 * - 点击"打开工作台"按钮时面板自动收起 + 路由跳转
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

// Mock dependencies
const mockPush = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: (...args: any[]) => mockPush(...args),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    createSession: vi.fn(),
    getHistory: vi.fn().mockResolvedValue([]),
    sendMessage: vi.fn(),
    uploadChatImages: vi.fn(),
  },
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: () => ({
    accessToken: 'test-token',
  }),
}))

vi.mock('@/components/icons/MibaoLogo', () => ({
  MibaoLogo: ({ size }: { size: number }) => <span data-testid="mibao-logo" data-size={size}>🤖</span>,
}))

vi.mock('@/lib/utils', () => ({
  cn: (...args: (string | undefined | false | null)[]) => args.filter(Boolean).join(' '),
}))

import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'

describe('FloatingAssistant', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    // jsdom 不支持 scrollIntoView
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('默认状态下只显示 FAB 按钮，面板关闭', () => {
    render(<FloatingAssistant />)

    // FAB 按钮可见
    const fab = screen.getByTitle('打开米宝')
    expect(fab).toBeInTheDocument()

    // 面板不可见（opacity-0 + pointer-events-none）
    const panel = screen.getByText('米宝 · 智能工作助手').closest('div.fixed')
    expect(panel?.className).toContain('pointer-events-none')
  })

  it('点击 FAB 打开面板', () => {
    render(<FloatingAssistant />)

    const fab = screen.getByTitle('打开米宝')
    fireEvent.click(fab)

    // 面板应变为可见（pointer-events-auto）
    const panel = screen.getByText('米宝 · 智能工作助手').closest('div.fixed')
    expect(panel?.className).toContain('pointer-events-auto')

    // FAB 图标变为关闭
    expect(screen.getByTitle('关闭米宝')).toBeInTheDocument()
  })

  it('点击"打开工作台"按钮时面板自动收起并跳转到 /chat/', () => {
    render(<FloatingAssistant />)

    // 1. 先打开面板
    const fab = screen.getByTitle('打开米宝')
    fireEvent.click(fab)

    // 确认面板已打开
    let panel = screen.getByText('米宝 · 智能工作助手').closest('div.fixed')
    expect(panel?.className).toContain('pointer-events-auto')

    // 2. 点击"打开工作台"按钮（Maximize2 图标对应的按钮）
    const workspaceBtn = screen.getByTitle('打开工作台')
    fireEvent.click(workspaceBtn)

    // 3. 面板应自动收起
    panel = screen.getByText('米宝 · 智能工作助手').closest('div.fixed')
    expect(panel?.className).toContain('pointer-events-none')

    // 4. 路由应跳转到 /chat/
    expect(mockPush).toHaveBeenCalledTimes(1)
    expect(mockPush).toHaveBeenCalledWith('/chat/')
  })

  it('点击"打开工作台"后 FAB 按钮恢复为"打开米宝"状态', () => {
    render(<FloatingAssistant />)

    // 打开面板
    fireEvent.click(screen.getByTitle('打开米宝'))
    expect(screen.getByTitle('关闭米宝')).toBeInTheDocument()

    // 点击"打开工作台"
    fireEvent.click(screen.getByTitle('打开工作台'))

    // FAB 应恢复为"打开米宝"（因为面板已收起）
    expect(screen.getByTitle('打开米宝')).toBeInTheDocument()
    expect(screen.queryByTitle('关闭米宝')).not.toBeInTheDocument()
  })
})
