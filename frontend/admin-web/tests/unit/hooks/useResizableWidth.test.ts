// case_ids: UI-021, UI-022, UI-029
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useResizableWidth } from '@/hooks/useResizableWidth'

const STORAGE_KEY = 'test_mibao_width'

describe('useResizableWidth', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('returns defaultWidth when no stored value', () => {
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: 'min(920px, calc(100vw - 3rem))', minWidth: 480 })
    )
    expect(result.current.containerStyle.width).toBe('min(920px, calc(100vw - 3rem))')
  })

  it('returns stored width from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, '800')
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    expect(result.current.containerStyle.width).toBe('800px')
  })

  it('falls back to defaultWidth for invalid/negative stored value', () => {
    localStorage.setItem(STORAGE_KEY, 'not-a-number')
    const { result: r1 } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    expect(r1.current.containerStyle.width).toBe('100%')

    localStorage.setItem(STORAGE_KEY, '-10')
    const { result: r2 } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    expect(r2.current.containerStyle.width).toBe('100%')
  })

  it('handleProps has correct accessibility attributes', () => {
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    expect(result.current.handleProps.role).toBe('separator')
    expect(result.current.handleProps.tabIndex).toBe(0)
    expect(result.current.handleProps['aria-orientation']).toBe('vertical')
    expect(result.current.handleProps['aria-label']).toBe('拖拽调整宽度')
    expect(typeof result.current.handleProps.onMouseDown).toBe('function')
  })

  it('mousedown sets isDragging to true', () => {
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    expect(result.current.isDragging).toBe(false)
    act(() => { result.current.handleProps.onMouseDown({
      clientX: 500,
      currentTarget: { closest: () => ({ getBoundingClientRect: () => ({ width: 720 }) }) },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    expect(result.current.isDragging).toBe(true)
  })

  it('drag right increases width', () => {
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
    })
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 1000 })
    )
    // startX 800 > clientX 500 → 右拖（clientX 增大）时宽度增大
    act(() => { result.current.handleProps.onMouseDown({
      clientX: 800,
      currentTarget: { closest: () => ({ getBoundingClientRect: () => ({ width: 720 }) }) },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    act(() => { capturedMoveHandler!({ clientX: 900 } as MouseEvent) })
    expect(result.current.containerStyle.width).toBe('820px')
  })

  it('clamps to minWidth when dragging far left', () => {
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
    })
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    act(() => { result.current.handleProps.onMouseDown({
      clientX: 800,
      currentTarget: { closest: () => ({ getBoundingClientRect: () => ({ width: 720 }) }) },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    // 向左拖出视野外 → 收窄到最小宽度 480
    act(() => { capturedMoveHandler!({ clientX: -500 } as MouseEvent) })
    expect(result.current.containerStyle.width).toBe('480px')
  })

  it('clamps to maxWidth when dragging right', () => {
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
    })
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 800 })
    )
    act(() => { result.current.handleProps.onMouseDown({
      clientX: 800,
      currentTarget: { closest: () => ({ getBoundingClientRect: () => ({ width: 720 }) }) },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    // 向右拖出视野外 → 达到最大宽度 800
    act(() => { capturedMoveHandler!({ clientX: 5000 } as MouseEvent) })
    expect(result.current.containerStyle.width).toBe('800px')
  })

  it('persists width to localStorage on mouseup', () => {
    let capturedUpHandler: (() => void) | null = null
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
      if (event === 'mouseup') capturedUpHandler = handler as () => void
    })
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 1000 })
    )
    act(() => { result.current.handleProps.onMouseDown({
      clientX: 800,
      currentTarget: { closest: () => ({ getBoundingClientRect: () => ({ width: 720 }) }) },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    act(() => { capturedMoveHandler!({ clientX: 900 } as MouseEvent) })
    act(() => { capturedUpHandler!() })
    expect(localStorage.getItem(STORAGE_KEY)).toBe('820')
    expect(result.current.isDragging).toBe(false)
  })

  it('resetWidth clears localStorage and restores default', () => {
    localStorage.setItem(STORAGE_KEY, '500')
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    expect(result.current.containerStyle.width).toBe('500px')
    act(() => { result.current.resetWidth() })
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(result.current.containerStyle.width).toBe('100%')
  })

  it('sets body userSelect none during drag, restores after', () => {
    let capturedUpHandler: (() => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mouseup') capturedUpHandler = handler as () => void
    })
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    expect(document.body.style.userSelect).not.toBe('none')
    act(() => { result.current.handleProps.onMouseDown({
      clientX: 800,
      currentTarget: { closest: () => ({ getBoundingClientRect: () => ({ width: 720 }) }) },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    expect(document.body.style.userSelect).toBe('none')
    expect(document.body.style.cursor).toBe('ew-resize')
    act(() => { capturedUpHandler!() })
    expect(document.body.style.userSelect).not.toBe('none')
  })

  // ── setWidth API（UI-020 右下角斜向缩放共用）──
  it('setWidth clamps to min/max and updates container style', () => {
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 900 })
    )
    act(() => { result.current.setWidth(600) })
    expect(result.current.containerStyle.width).toBe('600px')
    act(() => { result.current.setWidth(10) })
    expect(result.current.containerStyle.width).toBe('480px')
    act(() => { result.current.setWidth(5000) })
    expect(result.current.containerStyle.width).toBe('900px')
  })

  it('setWidth defaults max to window.innerWidth when maxWidth not provided', () => {
    const orig = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true })
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480 })
    )
    act(() => { result.current.setWidth(5000) })
    expect(result.current.containerStyle.width).toBe('1024px')
    Object.defineProperty(window, 'innerWidth', { value: orig, writable: true, configurable: true })
  })

  it('setWidth rounds fractional values', () => {
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 1000 })
    )
    act(() => { result.current.setWidth(543.6) })
    expect(result.current.containerStyle.width).toBe('544px')
  })

  // ── UI-029：残留尺寸视口钳制 —— 窗口变化后不留死白/不溢出（issue #3021）──

  it('mount 时把超过视口的残留宽度钳制到视口上限', () => {
    localStorage.setItem(STORAGE_KEY, '1900')
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 1024 })
    )
    expect(result.current.containerStyle.width).toBe('1024px')
  })

  it('窗口 resize 时钳制超视口残留，且不放大刻意缩小的浮窗', () => {
    localStorage.setItem(STORAGE_KEY, '1500')
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 2000 })
    )
    // jsdom 默认 innerWidth=1024 → mount 钳制
    expect(result.current.containerStyle.width).toBe('1024px')

    // 视口缩小到 800 → resize 后钳到 800
    Object.defineProperty(window, 'innerWidth', { value: 800, writable: true, configurable: true })
    act(() => { window.dispatchEvent(new Event('resize')) })
    expect(result.current.containerStyle.width).toBe('800px')

    // 视口变大到 1600 → 不放大用户刻意缩小的浮窗
    Object.defineProperty(window, 'innerWidth', { value: 1600, writable: true, configurable: true })
    act(() => { window.dispatchEvent(new Event('resize')) })
    expect(result.current.containerStyle.width).toBe('800px')
    Object.defineProperty(window, 'innerWidth', { value: 1024, writable: true, configurable: true })
  })

  it('无残留宽度时钳制不生效（保持 defaultWidth）', () => {
    const { result } = renderHook(() =>
      useResizableWidth({ storageKey: STORAGE_KEY, defaultWidth: '100%', minWidth: 480, maxWidth: 1024 })
    )
    act(() => { window.dispatchEvent(new Event('resize')) })
    expect(result.current.containerStyle.width).toBe('100%')
  })
})