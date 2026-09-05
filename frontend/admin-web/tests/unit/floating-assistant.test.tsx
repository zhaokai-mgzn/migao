// case_ids: UI-011, UI-023
/**
 * FloatingAssistant 组件测试 — 重构后版本
 *
 * 覆盖：FAB 打开/关闭、最小化/还原、标题栏按钮、最小化浮窗拖拽移动/缩放/越界钳制
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// Mock dependencies
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

vi.mock('@/components/icons/MibaoLogo', () => ({
  MibaoLogo: ({ size }: { size: number }) => <span data-testid="mibao-logo" data-size={size}>🤖</span>,
}))

vi.mock('@/lib/utils', () => ({ cn: (...args: any[]) => args.filter(Boolean).join(' ') }))

// Mock chat store
const mockFetchSessions = vi.fn()
vi.mock('@/store/chat', () => {
  const fn = () => ({
    fetchSessions: mockFetchSessions,
    sessions: [],
    currentSessionId: null,
    messages: [],
    isStreaming: false,
    isLoadingSessions: false,
    isLoadingMessages: false,
  })
  return { useChatStore: Object.assign(fn, { getState: () => fn() }) }
})

// Mock chat components
vi.mock('@/components/chat/SessionList', () => ({ default: () => <div data-testid="session-list">SessionList</div> }))
vi.mock('@/components/chat/ChatArea', () => ({ default: () => <div data-testid="chat-area">ChatArea</div> }))

import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'

describe('FloatingAssistant', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('默认状态下只显示 FAB 按钮', () => {
    render(<FloatingAssistant />)

    expect(screen.getByTitle('打开米宝')).toBeInTheDocument()
    expect(screen.queryByText('米宝 · 智能助手')).not.toBeInTheDocument()
  })

  it('点击 FAB 打开面板，居中大窗两栏布局', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))

    // 面板标题可见
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()
    // 居中大窗：会话列表 + 聊天区两栏
    expect(screen.getByTestId('session-list')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    // FAB 在面板打开时隐藏
    expect(screen.queryByTitle('打开米宝')).not.toBeInTheDocument()
  })

  it('点击居中遮罩关闭面板', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('float-assistant-overlay'))
    expect(screen.queryByText('米宝 · 智能助手')).not.toBeInTheDocument()
  })

  it('点击关闭按钮收起面板', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('关闭'))
    expect(screen.queryByText('米宝 · 智能助手')).not.toBeInTheDocument()
  })

  it('打开面板时自动加载会话列表', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))

    expect(mockFetchSessions).toHaveBeenCalled()
  })

  // ── UI-021：最小化浮窗尺寸自适应 / 缩放把手 / 越界钳制 ──

  function setViewport(width: number, height: number) {
    Object.defineProperty(window, 'innerWidth', { value: width, writable: true, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: height, writable: true, configurable: true })
  }

  function openMinimized() {
    render(<FloatingAssistant />)
    fireEvent.click(screen.getByTitle('打开米宝'))
    fireEvent.click(screen.getByTitle('收起'))
    return screen.getByTestId('float-minimized-window')
  }

  it('最小化浮窗默认高度按视口自适应（宽 400、高不低于 600、上限 760）', () => {
    setViewport(1024, 1080)
    const win = openMinimized()
    expect(win.style.width).toBe('400px')
    expect(win.style.height).toBe('760px')
  })

  it('小视口下浮窗默认高度不超过视口（贴边不留白）', () => {
    setViewport(1024, 768)
    const win = openMinimized()
    expect(win.style.height).toBe('614px')
  })

  it('底部把手拖拽可调整最小化浮窗高度，松开后持久化尺寸', () => {
    setViewport(1024, 768)
    const win = openMinimized()
    const bottom = screen.getByTestId('float-minimized-resize-bottom')
    fireEvent.mouseDown(bottom, { clientY: 700 })
    fireEvent.mouseMove(document, { clientY: 760 })
    expect(win.style.height).toBe('674px')
    expect(win.style.width).toBe('400px')
    fireEvent.mouseUp(document)
    const saved = JSON.parse(localStorage.getItem('mibao_minimized_size')!)
    expect(saved.h).toBe(674)
    expect(saved.w).toBe(400)
  })

  it('右下角把手斜向拖拽时宽度与高度同步调整', () => {
    setViewport(1024, 768)
    const win = openMinimized()
    const corner = screen.getByTestId('float-minimized-resize-corner')
    expect(corner.style.cursor).toBe('nwse-resize')
    fireEvent.mouseDown(corner, { clientX: 900, clientY: 700 })
    fireEvent.mouseMove(document, { clientX: 960, clientY: 740 })
    expect(win.style.width).toBe('460px')
    expect(win.style.height).toBe('654px')
    fireEvent.mouseUp(document)
    expect(JSON.parse(localStorage.getItem('mibao_minimized_size')!).w).toBe(460)
    expect(JSON.parse(localStorage.getItem('mibao_minimized_size')!).h).toBe(654)
  })

  it('拖拽移动按当前浮窗尺寸钳制 —— 可贴满左右/上下极限不留白', () => {
    setViewport(1024, 768)
    const win = openMinimized()
    fireEvent.mouseDown(screen.getByText('米宝'), { clientX: 500, clientY: 500 })
    fireEvent.mouseMove(document, { clientX: 5000, clientY: 5000 })
    expect(win.style.left).toBe('624px')   // 1024 - 400
    expect(win.style.top).toBe('154px')    // 768 - 614
    fireEvent.mouseMove(document, { clientX: -500, clientY: -500 })
    expect(win.style.left).toBe('0px')
    expect(win.style.top).toBe('0px')
    fireEvent.mouseUp(document)
  })

  it('存储的越界位置在打开时自动钳回可见区域', () => {
    setViewport(1024, 768)
    localStorage.setItem('mibao_minimized_pos', JSON.stringify({ x: 9999, y: -9999 }))
    const win = openMinimized()
    expect(win.style.left).toBe('624px')
    expect(win.style.top).toBe('0px')
  })
})
