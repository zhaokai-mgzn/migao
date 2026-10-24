// case_ids: UI-011, UI-079
/**
 * PC 端「贴底跟随」滚动 hook（issue #7263）
 *
 * 用户逐字：「打字效果出来了，但是屏幕不是跟着文字自动往下滑动的，还需要人来滑动」。
 * 根因 = 自动滚底只绑 `messages`，而打字机在气泡内部逐字揭示（`useTypewriter` 的本地
 * state，20ms/字）不改 `messages` ⇒ 揭示期间一次都不触发。
 *
 * 四条判据（对应 issue 的「目标形态」）：
 * 1. 贴底时内容长高（ResizeObserver 回调）⇒ 滚到底；
 * 2. 用户上滑离开底部 ⇒ **不**抢滚动；
 * 3. 滑回底部附近 ⇒ 恢复跟随；
 * 4. `scrollToBottom()`（发新消息 / 切会话）⇒ 强制回底并恢复跟随。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  isNearBottom,
  useStickToBottom,
  STICK_THRESHOLD_PX,
} from '@/hooks/use-stick-to-bottom'

/** 可手动触发的 ResizeObserver 替身：jsdom 不提供，setup 里的 stub 也不会回调 */
class FakeResizeObserver {
  static instances: FakeResizeObserver[] = []
  private callback: ResizeObserverCallback
  constructor(cb: ResizeObserverCallback) {
    this.callback = cb
    FakeResizeObserver.instances.push(this)
  }
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  trigger() {
    this.callback([], this as unknown as ResizeObserver)
  }
}

function makeContainer(scrollHeight = 1000, clientHeight = 500) {
  const el = document.createElement('div')
  Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: clientHeight, configurable: true })
  el.scrollTop = scrollHeight - clientHeight // 初始就在底部
  el.scrollTo = vi.fn((opts: ScrollToOptions) => {
    el.scrollTop = Number(opts.top ?? 0)
  }) as typeof el.scrollTo
  return el
}

function renderStick(container?: HTMLElement) {
  const el = container ?? makeContainer()
  const content = document.createElement('div')
  const containerRef = { current: el }
  const contentRef = { current: content }
  const hook = renderHook(() => useStickToBottom(containerRef, contentRef, 'k'))
  return { el, hook }
}

function scrollTo(el: HTMLElement, top: number) {
  el.scrollTop = top
  act(() => {
    el.dispatchEvent(new Event('scroll'))
  })
}

describe('isNearBottom — 距底判定', () => {
  it('内容不足一屏 ⇒ 恒为真（没有可滚动的空间）', () => {
    expect(isNearBottom({ scrollTop: 0, scrollHeight: 300, clientHeight: 500 })).toBe(true)
  })

  it('距底 ≤ 阈值 ⇒ 真；超过阈值 ⇒ 假（阈值边界逐值）', () => {
    const base = { scrollHeight: 1000, clientHeight: 500 }
    expect(isNearBottom({ ...base, scrollTop: 500 })).toBe(true) // 距底 0
    expect(
      isNearBottom({ ...base, scrollTop: 500 - STICK_THRESHOLD_PX }),
    ).toBe(true) // 距底 = 阈值
    expect(
      isNearBottom({ ...base, scrollTop: 500 - STICK_THRESHOLD_PX - 1 }),
    ).toBe(false) // 距底 = 阈值 + 1
  })
})

describe('useStickToBottom — 贴底跟随（issue #7263）', () => {
  beforeEach(() => {
    FakeResizeObserver.instances = []
    globalThis.ResizeObserver = FakeResizeObserver as unknown as typeof ResizeObserver
  })

  it('贴底时内容长高（逐字揭示）⇒ 跟到底', () => {
    const { el } = renderStick()
    expect(FakeResizeObserver.instances).toHaveLength(1)

    act(() => FakeResizeObserver.instances[0].trigger())

    expect(el.scrollTop).toBe(el.scrollHeight)
  })

  it('用户上滑离开底部 ⇒ 内容再长高也不抢滚动', () => {
    const { el } = renderStick()
    scrollTo(el, 100) // 距底 400 > 80 ⇒ 停止跟随

    act(() => FakeResizeObserver.instances[0].trigger())

    expect(el.scrollTop).toBe(100)
  })

  it('滑回底部附近 ⇒ 恢复跟随', () => {
    const { el } = renderStick()
    scrollTo(el, 100)
    act(() => FakeResizeObserver.instances[0].trigger())
    expect(el.scrollTop).toBe(100)

    scrollTo(el, el.scrollHeight - el.clientHeight - 20) // 距底 20 ≤ 80 ⇒ 重新贴底
    act(() => FakeResizeObserver.instances[0].trigger())

    expect(el.scrollTop).toBe(el.scrollHeight)
  })

  it('scrollToBottom()（新消息/切会话）⇒ 强制回底并恢复跟随', () => {
    const { el, hook } = renderStick()
    scrollTo(el, 0) // 先离开底部

    act(() => hook.result.current.scrollToBottom('smooth'))

    expect(el.scrollTo).toHaveBeenLastCalledWith({ top: el.scrollHeight, behavior: 'smooth' })
    expect(el.scrollTop).toBe(el.scrollHeight)

    // 恢复跟随：内容再长高仍跟到底
    el.scrollTo = vi.fn()
    act(() => FakeResizeObserver.instances[0].trigger())
    expect(el.scrollTop).toBe(el.scrollHeight)
  })
})
