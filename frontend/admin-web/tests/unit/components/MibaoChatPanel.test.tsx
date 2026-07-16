import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
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
})
