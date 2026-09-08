// case_ids: UI-021, UI-022, UI-029
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MibaoChatPanel from '@/components/business/MibaoChatPanel'

// localStorage mock
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: vi.fn((key: string): string | null => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value }),
    removeItem: vi.fn((key: string) => { delete store[key] }),
    clear: vi.fn(() => { store = {} }),
    get length() { return Object.keys(store).length },
    key: vi.fn((index: number) => Object.keys(store)[index] ?? null),
  }
})()

Object.defineProperty(window, 'localStorage', { value: localStorageMock, writable: true })

const DEFAULT_HEIGHT = '85vh'

describe('MibaoChatPanel', () => {
  beforeEach(() => {
    localStorageMock.clear()
    vi.clearAllMocks()
  })

  it('renders with default height of 85vh', () => {
    const { container } = render(
      <MibaoChatPanel><div>test content</div></MibaoChatPanel>
    )
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')
    expect(panel).toBeInTheDocument()
    expect(panel!.getAttribute('style')).toContain('height: ' + DEFAULT_HEIGHT)
  })

  it('renders a visible resize handle', () => {
    render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const handle = screen.getByTestId('chat-panel-resize-handle')
    expect(handle).toBeInTheDocument()
    expect(handle).toBeVisible()
  })

  it('has ns-resize cursor on the resize handle', () => {
    render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const handle = screen.getByTestId('chat-panel-resize-handle')
    expect(handle.style.cursor).toBe('ns-resize')
  })

  it('renders children inside the content area', () => {
    render(<MibaoChatPanel><div data-testid="child-element">Hello World</div></MibaoChatPanel>)
    const contentArea = screen.getByTestId('chat-panel-content')
    const child = screen.getByTestId('child-element')
    expect(contentArea).toContainElement(child)
    expect(child).toHaveTextContent('Hello World')
  })

  it('restores height from localStorage when saved', () => {
    const origGetItem = localStorageMock.getItem
    localStorageMock.getItem = vi.fn((key: string) => {
      if (key === 'mibao_chat_panel_height') return '750'
      return null
    })
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    expect(panel.getAttribute('style')).toContain('height: 750px')
    localStorageMock.getItem = origGetItem
  })

  it('uses default height when localStorage has no record', () => {
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    expect(panel.getAttribute('style')).toContain('height: ' + DEFAULT_HEIGHT)
  })

  it('resize handle has accessibility attributes', () => {
    render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const handle = screen.getByTestId('chat-panel-resize-handle')
    expect(handle).toHaveAttribute('role', 'separator')
    expect(handle).toHaveAttribute('aria-orientation', 'horizontal')
    expect(handle).toHaveAttribute('aria-label')
  })

  // ── UI-019：把手加大 + 缩放上限放开到视口 100%（不留白）──

  it('底板/顶板拖拽把手加大到 h-3.5，方便抓取', () => {
    render(<MibaoChatPanel showTopHandle><div>test content</div></MibaoChatPanel>)
    const bottom = screen.getByTestId('chat-panel-resize-handle')
    const top = screen.getByTestId('chat-panel-resize-handle-top')
    const horizontal = screen.getByTestId('chat-panel-resize-handle-horizontal')
    expect(bottom.className).toContain('h-3.5')
    expect(top.className).toContain('h-3.5')
    expect(horizontal.className).toContain('w-3.5')
  })

  it('高度缩放上限为视口 100% —— 拖到底极限时贴满视口不留白（不再截断在 90%）', () => {
    const origH = window.innerHeight
    Object.defineProperty(window, 'innerHeight', { value: 900, writable: true, configurable: true })
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    // jsdom 无布局，桩掉 getBoundingClientRect 模拟初始 600px 高
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({
      width: 720, height: 600, top: 0, left: 0, right: 720, bottom: 600, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    const handle = screen.getByTestId('chat-panel-resize-handle')
    fireEvent.mouseDown(handle, { clientY: 100 })
    fireEvent.mouseMove(document, { clientY: 5000 })
    fireEvent.mouseUp(document)

    expect(panel.getAttribute('style')).toContain('height: 900px')
    Object.defineProperty(window, 'innerHeight', { value: origH, writable: true, configurable: true })
  })

  it('宽度缩放上限为视口 100% —— 拖到最宽贴满视口不留白', () => {
    const origW = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { value: 1200, writable: true, configurable: true })
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({
      width: 720, height: 600, top: 0, left: 0, right: 720, bottom: 600, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    const handle = screen.getByTestId('chat-panel-resize-handle-horizontal')
    // 向右拖 480px：720 → 1200（视口 100%，不留白）
    fireEvent.mouseDown(handle, { clientX: 100 })
    fireEvent.mouseMove(document, { clientX: 580 })
    fireEvent.mouseUp(document)

    expect(panel.getAttribute('style')).toContain('width: 1200px')
    Object.defineProperty(window, 'innerWidth', { value: origW, writable: true, configurable: true })
  })

  // ── UI-020：右下角斜向缩放把手（同时调宽高）──

  it('渲染右下角斜向缩放把手（nwse-resize 光标 + 无障碍标签）', () => {
    render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const corner = screen.getByTestId('chat-panel-resize-handle-corner')
    expect(corner).toBeInTheDocument()
    expect(corner.style.cursor).toBe('nwse-resize')
    expect(corner).toHaveAttribute('aria-label', '拖拽调整大小（斜向缩放）')
  })

  it('斜向拖拽右下角把手时宽度与高度同步变化', () => {
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({
      width: 720, height: 600, top: 0, left: 0, right: 720, bottom: 600, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    const corner = screen.getByTestId('chat-panel-resize-handle-corner')
    fireEvent.mouseDown(corner, { clientX: 700, clientY: 500 })
    fireEvent.mouseMove(document, { clientX: 750, clientY: 550 })
    fireEvent.mouseUp(document)

    const style = panel.getAttribute('style')!
    expect(style).toContain('width: 770px')
    expect(style).toContain('height: 650px')
  })

  it('斜向缩放受最小/最大边界钳制', () => {
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({
      width: 720, height: 600, top: 0, left: 0, right: 720, bottom: 600, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    const corner = screen.getByTestId('chat-panel-resize-handle-corner')
    // 大幅缩小：低于 MIN_WIDTH=480 / MIN_HEIGHT=300
    fireEvent.mouseDown(corner, { clientX: 700, clientY: 500 })
    fireEvent.mouseMove(document, { clientX: 100, clientY: 100 })
    fireEvent.mouseUp(document)

    const style = panel.getAttribute('style')!
    expect(style).toContain('width: 480px')
    expect(style).toContain('height: 300px')
  })

  // ── UI-029：双击手柄恢复默认尺寸 + 角把手误触防护（issue #3021）──

  it('双击底部手柄恢复默认尺寸（宽 100% / 高 85vh）并清除持久化', () => {
    localStorageMock.setItem('mibao_chat_panel_width', '900')
    localStorageMock.setItem('mibao_chat_panel_height', '700')
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    expect(panel.getAttribute('style')).toContain('width: 900px')
    expect(panel.getAttribute('style')).toContain('height: 700px')

    fireEvent.doubleClick(screen.getByTestId('chat-panel-resize-handle'))

    const style = panel.getAttribute('style')!
    expect(style).toContain('width: 100%')
    expect(style).toContain('height: 85vh')
    expect(localStorageMock.getItem('mibao_chat_panel_width')).toBeNull()
    expect(localStorageMock.getItem('mibao_chat_panel_height')).toBeNull()
  })

  it('双击右侧手柄同样恢复默认尺寸', () => {
    localStorageMock.setItem('mibao_chat_panel_width', '760')
    localStorageMock.setItem('mibao_chat_panel_height', '650')
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    expect(panel.getAttribute('style')).toContain('width: 760px')

    fireEvent.doubleClick(screen.getByTestId('chat-panel-resize-handle-horizontal'))

    const style = panel.getAttribute('style')!
    expect(style).toContain('width: 100%')
    expect(style).toContain('height: 85vh')
    expect(localStorageMock.getItem('mibao_chat_panel_width')).toBeNull()
    expect(localStorageMock.getItem('mibao_chat_panel_height')).toBeNull()
  })

  it('双击右下角把手恢复默认尺寸', () => {
    localStorageMock.setItem('mibao_chat_panel_width', '600')
    localStorageMock.setItem('mibao_chat_panel_height', '500')
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    expect(panel.getAttribute('style')).toContain('width: 600px')

    fireEvent.doubleClick(screen.getByTestId('chat-panel-resize-handle-corner'))

    const style = panel.getAttribute('style')!
    expect(style).toContain('width: 100%')
    expect(style).toContain('height: 85vh')
    expect(localStorageMock.getItem('mibao_chat_panel_width')).toBeNull()
    expect(localStorageMock.getItem('mibao_chat_panel_height')).toBeNull()
  })

  it('角把手单击未拖动时 mouseup 不冻结当前尺寸（防误触持久化 px）', () => {
    const { container } = render(<MibaoChatPanel><div>test content</div></MibaoChatPanel>)
    const panel = container.querySelector('[data-testid="chat-panel-resize-container"]')!
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({
      width: 720, height: 600, top: 0, left: 0, right: 720, bottom: 600, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    const corner = screen.getByTestId('chat-panel-resize-handle-corner')
    // 只有 mousedown + mouseup，没有任何 mousemove —— 不得写入 localStorage
    fireEvent.mouseDown(corner, { clientX: 700, clientY: 500 })
    fireEvent.mouseUp(document)

    expect(localStorageMock.getItem('mibao_chat_panel_width')).toBeNull()
    expect(localStorageMock.getItem('mibao_chat_panel_height')).toBeNull()
  })

  it('缩放手柄 title 提示「双击恢复默认大小」（底/右/角）', () => {
    render(<MibaoChatPanel showTopHandle><div>test content</div></MibaoChatPanel>)
    expect(screen.getByTestId('chat-panel-resize-handle')).toHaveAttribute('title', expect.stringContaining('双击恢复默认'))
    expect(screen.getByTestId('chat-panel-resize-handle-top')).toHaveAttribute('title', expect.stringContaining('双击恢复默认'))
    expect(screen.getByTestId('chat-panel-resize-handle-horizontal')).toHaveAttribute('title', expect.stringContaining('双击恢复默认'))
    expect(screen.getByTestId('chat-panel-resize-handle-corner')).toHaveAttribute('title', expect.stringContaining('双击恢复默认'))
  })
})
