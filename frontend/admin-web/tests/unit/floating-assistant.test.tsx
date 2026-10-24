// case_ids: UI-011, UI-023, UI-132
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

    expect(screen.getByTitle('打开黄金策')).toBeInTheDocument()
    expect(screen.queryByText('黄金策 · 企业智能生产管家')).not.toBeInTheDocument()
  })

  it('点击 FAB 打开面板，居中大窗两栏布局', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开黄金策'))

    // 面板标题可见
    expect(screen.getByText('黄金策 · 企业智能生产管家')).toBeInTheDocument()
    // 居中大窗：会话列表 + 聊天区两栏
    expect(screen.getByTestId('session-list')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    // FAB 在面板打开时隐藏
    expect(screen.queryByTitle('打开黄金策')).not.toBeInTheDocument()
  })

  it('点击居中遮罩关闭面板', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开黄金策'))
    expect(screen.getByText('黄金策 · 企业智能生产管家')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('float-assistant-overlay'))
    expect(screen.queryByText('黄金策 · 企业智能生产管家')).not.toBeInTheDocument()
  })

  it('点击关闭按钮收起面板', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开黄金策'))
    expect(screen.getByText('黄金策 · 企业智能生产管家')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('关闭'))
    expect(screen.queryByText('黄金策 · 企业智能生产管家')).not.toBeInTheDocument()
  })

  it('打开面板时自动加载会话列表', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开黄金策'))

    expect(mockFetchSessions).toHaveBeenCalled()
  })

  // ── UI-021：最小化浮窗尺寸自适应 / 缩放把手 / 越界钳制 ──

  function setViewport(width: number, height: number) {
    Object.defineProperty(window, 'innerWidth', { value: width, writable: true, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: height, writable: true, configurable: true })
  }

  function openMinimized() {
    render(<FloatingAssistant />)
    fireEvent.click(screen.getByTitle('打开黄金策'))
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

  it('最小化浮窗默认位置贴底 —— 无底部预留空间（#3106）', () => {
    setViewport(1024, 768)
    const win = openMinimized()
    // 默认高度 614 → 默认 top = 768 - 614 = 154px（贴底，去掉原 -80px 底部预留）
    expect(win.style.top).toBe('154px')
    // 右侧保留 16px 边距（1024 - 400 - 16 = 608）
    expect(win.style.left).toBe('608px')
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
    fireEvent.mouseDown(screen.getByText('黄金策'), { clientX: 500, clientY: 500 })
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

  // ── 全屏（最大化）模式：尺寸归视口所有 — 历史 px 残留不得覆盖（issue #7508） ──
  //
  // 缺陷类：模式自有布局契约（全屏 = 铺满视口）被持久化的用户控件状态（拖拽过的 px 宽高）覆盖 ⇒
  // 「点了最大化却还是一个小窗，右上角还露着底下的页面」。之所以「换一台电脑就正常」：
  // mibao_chat_panel_width/height 存在**本机** localStorage，别的机器没有残留。
  function openFullscreen() {
    render(<FloatingAssistant />)
    fireEvent.click(screen.getByTitle('打开黄金策'))
    fireEvent.click(screen.getByTitle('全屏'))
    return screen.getByTestId('chat-panel-resize-container')
  }

  it('全屏铺满视口 —— 历史 px 宽高（mibao_chat_panel_*）不得覆盖', () => {
    setViewport(1440, 900)
    localStorage.setItem('mibao_chat_panel_width', '620')
    localStorage.setItem('mibao_chat_panel_height', '480')
    const panel = openFullscreen()
    expect(panel.style.width).toBe('100%')
    expect(panel.style.height).toBe('100%')
  })

  it('全屏不渲染任何缩放手柄（最大化态不该还能被拖成小窗）', () => {
    setViewport(1440, 900)
    localStorage.setItem('mibao_chat_panel_width', '620')
    localStorage.setItem('mibao_chat_panel_height', '480')
    openFullscreen()
    expect(screen.queryByTestId('chat-panel-resize-handle-top')).toBeNull()
    expect(screen.queryByTestId('chat-panel-resize-handle')).toBeNull()
    expect(screen.queryByTestId('chat-panel-resize-handle-horizontal')).toBeNull()
    expect(screen.queryByTestId('chat-panel-resize-handle-corner')).toBeNull()
  })

  it('全屏无遮罩（最大化不留模态底）、退出全屏恢复遮罩与历史尺寸', () => {
    setViewport(1440, 900)
    localStorage.setItem('mibao_chat_panel_width', '620')
    localStorage.setItem('mibao_chat_panel_height', '480')
    const panel = openFullscreen()
    expect(screen.queryByTestId('float-assistant-overlay')).toBeNull()

    fireEvent.click(screen.getByTitle('退出全屏'))
    expect(screen.getByTestId('float-assistant-overlay')).toBeInTheDocument()
    expect(panel.style.width).toBe('620px')
    expect(panel.style.height).toBe('480px')
    // 退出全屏后缩放手柄回来（恢复可调整）
    expect(screen.getByTestId('chat-panel-resize-handle')).toBeInTheDocument()
  })

  it('无历史尺寸时全屏同样铺满（对照：不是靠清缓存才正常）', () => {
    setViewport(1440, 900)
    const panel = openFullscreen()
    expect(panel.style.width).toBe('100%')
    expect(panel.style.height).toBe('100%')
  })

  // ── 类级元守卫：面板**四个模式**的「外观契约」逐格成立（不是只钉全屏那一格） ──
  //
  // 面板是四模式状态机（closed / centered / fullscreen / minimized）。模式一旦**串味**，用户看到的就是
  // 「功能坏了」——本单正是这个形态：fullscreen 的状态确实生效了（无遮罩 + 图标变「退出全屏」），
  // 但几何被历史 px 顶翻 ⇒ 看起来像「点了最大化没反应」。
  // 本文即**登记面**：新增/改动任一模式必须在这张表里加行，否则该模式的外观没有任何断言。
  type ModeChrome = {
    panel: boolean     // 居中大窗 / 全屏 的面板根节点
    overlay: boolean   // 模态遮罩（只有居中态有）
    fab: boolean       // 悬浮球（只有关闭态有）
    minimized: boolean // 最小化浮窗
    handles: boolean   // 缩放手柄（最大化态不许有：否则还能被拖成小窗）
  }

  const MODE_MATRIX: Array<{ mode: string; enter: () => void; chrome: ModeChrome }> = [
    {
      mode: 'closed',
      enter: () => {},
      chrome: { panel: false, overlay: false, fab: true, minimized: false, handles: false },
    },
    {
      mode: 'centered',
      enter: () => fireEvent.click(screen.getByTitle('打开黄金策')),
      chrome: { panel: true, overlay: true, fab: false, minimized: false, handles: true },
    },
    {
      mode: 'fullscreen',
      enter: () => {
        fireEvent.click(screen.getByTitle('打开黄金策'))
        fireEvent.click(screen.getByTitle('全屏'))
      },
      chrome: { panel: true, overlay: false, fab: false, minimized: false, handles: false },
    },
    {
      mode: 'minimized',
      enter: () => {
        fireEvent.click(screen.getByTitle('打开黄金策'))
        fireEvent.click(screen.getByTitle('收起'))
      },
      chrome: { panel: false, overlay: false, fab: false, minimized: true, handles: false },
    },
  ]

  it.each(MODE_MATRIX)('模式外观契约 —— $mode', ({ enter, chrome }) => {
    render(<FloatingAssistant />)
    enter()
    expect(screen.queryByTestId('chat-panel-resize-container') !== null).toBe(chrome.panel)
    expect(screen.queryByTestId('float-assistant-overlay') !== null).toBe(chrome.overlay)
    expect(screen.queryByTitle('打开黄金策') !== null).toBe(chrome.fab)
    expect(screen.queryByTestId('float-minimized-window') !== null).toBe(chrome.minimized)
    expect(screen.queryByTestId('chat-panel-resize-handle') !== null).toBe(chrome.handles)
  })
})
