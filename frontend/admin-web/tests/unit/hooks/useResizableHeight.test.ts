import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useResizableHeight } from '@/hooks/useResizableHeight'

const STORAGE_KEY = 'test_mibao_height'

describe('useResizableHeight', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('returns defaultHeight when no stored value', () => {
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: 'calc(100vh - 80px)', minHeight: 300 })
    )
    expect(result.current.containerStyle.height).toBe('calc(100vh - 80px)')
  })

  it('returns stored height from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, '600')
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: 'calc(100vh - 80px)', minHeight: 300 })
    )
    expect(result.current.containerStyle.height).toBe('600px')
  })

  it('falls back to defaultHeight for invalid localStorage value', () => {
    localStorage.setItem(STORAGE_KEY, 'not-a-number')
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: 'calc(100vh - 80px)', minHeight: 300 })
    )
    expect(result.current.containerStyle.height).toBe('calc(100vh - 80px)')
  })

  it('falls back for negative stored value', () => {
    localStorage.setItem(STORAGE_KEY, '-100')
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300 })
    )
    expect(result.current.containerStyle.height).toBe('70vh')
  })

  it('handleProps has correct accessibility attributes', () => {
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300 })
    )
    expect(result.current.handleProps.role).toBe('separator')
    expect(result.current.handleProps.tabIndex).toBe(0)
    expect(result.current.handleProps['aria-orientation']).toBe('horizontal')
    expect(typeof result.current.handleProps.onMouseDown).toBe('function')
  })

  it('mousedown sets isDragging to true', () => {
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300 })
    )
    expect(result.current.isDragging).toBe(false)
    const fakeEvent = {
      clientY: 500,
      currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 600 }) } },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent
    act(() => { result.current.handleProps.onMouseDown(fakeEvent) })
    expect(result.current.isDragging).toBe(true)
  })

  it('drag down increases height', () => {
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
    })
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300, maxHeight: 1000 })
    )
    const fakeEvent = {
      clientY: 500,
      currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 600 }) } },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent
    act(() => { result.current.handleProps.onMouseDown(fakeEvent) })
    act(() => { capturedMoveHandler!({ clientY: 600 } as MouseEvent) })
    expect(result.current.containerStyle.height).toBe('700px')
  })

  it('clamps to minHeight when dragging up', () => {
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
    })
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300 })
    )
    const fakeEvent = {
      clientY: 500,
      currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 400 }) } },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent
    act(() => { result.current.handleProps.onMouseDown(fakeEvent) })
    act(() => { capturedMoveHandler!({ clientY: 200 } as MouseEvent) })
    expect(result.current.containerStyle.height).toBe('300px')
  })

  it('clamps to maxHeight when dragging down', () => {
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
    })
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300, maxHeight: 800 })
    )
    const fakeEvent = {
      clientY: 500,
      currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 600 }) } },
      preventDefault: vi.fn(),
    } as unknown as React.MouseEvent
    act(() => { result.current.handleProps.onMouseDown(fakeEvent) })
    act(() => { capturedMoveHandler!({ clientY: 1000 } as MouseEvent) })
    expect(result.current.containerStyle.height).toBe('800px')
  })

  it('persists height to localStorage on mouseup', () => {
    let capturedUpHandler: (() => void) | null = null
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
      if (event === 'mouseup') capturedUpHandler = handler as () => void
    })
    const removeSpy = vi.spyOn(document, 'removeEventListener')
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300, maxHeight: 1000 })
    )
    act(() => { result.current.handleProps.onMouseDown({
      clientY: 500, currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 600 }) } }, preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    act(() => { capturedMoveHandler!({ clientY: 700 } as MouseEvent) })
    act(() => { capturedUpHandler!() })
    expect(localStorage.getItem(STORAGE_KEY)).toBe('800')
    expect(result.current.isDragging).toBe(false)
    expect(removeSpy).toHaveBeenCalledWith('mousemove', expect.any(Function))
  })

  it('handles localStorage write failure gracefully', () => {
    let capturedUpHandler: (() => void) | null = null
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
      if (event === 'mouseup') capturedUpHandler = handler as () => void
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('QuotaExceededError') })
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300 })
    )
    act(() => { result.current.handleProps.onMouseDown({
      clientY: 500, currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 600 }) } }, preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    act(() => { capturedMoveHandler!({ clientY: 700 } as MouseEvent) })
    expect(() => { act(() => { capturedUpHandler!() }) }).not.toThrow()
    expect(result.current.isDragging).toBe(false)
  })

  it('resetHeight clears localStorage and restores default', () => {
    localStorage.setItem(STORAGE_KEY, '500')
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: 'calc(100vh - 80px)', minHeight: 300 })
    )
    expect(result.current.containerStyle.height).toBe('500px')
    act(() => { result.current.resetHeight() })
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(result.current.containerStyle.height).toBe('calc(100vh - 80px)')
  })

  it('sets body userSelect none during drag, restores after', () => {
    let capturedUpHandler: (() => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mouseup') capturedUpHandler = handler as () => void
    })
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300 })
    )
    expect(document.body.style.userSelect).not.toBe('none')
    act(() => { result.current.handleProps.onMouseDown({
      clientY: 500, currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 600 }) } }, preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    expect(document.body.style.userSelect).toBe('none')
    expect(document.body.style.cursor).toBe('ns-resize')
    act(() => { capturedUpHandler!() })
    expect(document.body.style.userSelect).not.toBe('none')
  })

  it('defaults maxHeight to window.innerHeight when not provided', () => {
    let capturedMoveHandler: ((e: MouseEvent) => void) | null = null
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(document, 'addEventListener').mockImplementation((event: string, handler: any) => {
      if (event === 'mousemove') capturedMoveHandler = handler as (e: MouseEvent) => void
    })
    const orig = window.innerHeight
    Object.defineProperty(window, 'innerHeight', { value: 900, writable: true, configurable: true })
    const { result } = renderHook(() =>
      useResizableHeight({ storageKey: STORAGE_KEY, defaultHeight: '70vh', minHeight: 300 })
    )
    act(() => { result.current.handleProps.onMouseDown({
      clientY: 500, currentTarget: { parentElement: { getBoundingClientRect: () => ({ height: 400 }) } }, preventDefault: vi.fn(),
    } as unknown as React.MouseEvent) })
    act(() => { capturedMoveHandler!({ clientY: 2000 } as MouseEvent) })
    expect(result.current.containerStyle.height).toBe('900px')
    Object.defineProperty(window, 'innerHeight', { value: orig, writable: true, configurable: true })
  })
})
