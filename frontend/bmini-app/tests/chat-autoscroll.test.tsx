// case_ids: UI-079
/**
 * 手机端对话区「贴底跟随」（issue #7263）
 *
 * 用户逐字：「打字效果出来了，但是屏幕不是跟着文字自动往下滑动的，还需要人来滑动」。
 * 旧实现 `scrollIntoView` 是固定字符串（ref 是死代码）⇒ 只有首帧滚一次；且只绑
 * `messages.length`，打字机逐字揭示（本地 state）不改 messages ⇒ 不跟随。
 *
 * 判据 = issue「目标形态」四条：贴底跟随 / 不抢用户 / 回底恢复 / 新消息强制回底。
 */
import { renderHook, act } from '@testing-library/react'
import { useChatFollow } from '../src/hooks/use-chat-follow'

function scrollTo(result: { current: ReturnType<typeof useChatFollow> }, scrollTop: number) {
  act(() => {
    result.current.handleScroll({ detail: { scrollTop } })
  })
}

describe('useChatFollow — 打字机逐字上屏时贴底跟随（issue #7263）', () => {
  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.clearAllTimers()
    jest.useRealTimers()
  })

  it('贴底时内容长高（逐字揭示）⇒ 锚点推进（scrollIntoView 值变化）', () => {
    const { result } = renderHook(() => useChatFollow(2, true))
    const before = result.current.anchorId

    act(() => {
      result.current.followIfSticky()
    })

    expect(result.current.anchorId).not.toBe(before)
  })

  it('用户上滑离开底部 ⇒ 内容再长高也不推进（不抢滚动）', () => {
    const { result } = renderHook(() => useChatFollow(2, true))
    scrollTo(result, 500)
    scrollTo(result, 100) // 上滑 400px ⇒ 用户在回看
    const before = result.current.anchorId

    act(() => {
      result.current.followIfSticky()
    })

    expect(result.current.anchorId).toBe(before)
  })

  it('回到底部（onScrollToLower）⇒ 恢复跟随', () => {
    const { result } = renderHook(() => useChatFollow(2, true))
    scrollTo(result, 500)
    scrollTo(result, 100)
    act(() => {
      result.current.handleScrollToLower()
    })
    const before = result.current.anchorId

    act(() => {
      result.current.followIfSticky()
    })

    expect(result.current.anchorId).not.toBe(before)
  })

  it('上滑后来了新消息 ⇒ 强制回底并恢复跟随', () => {
    const { result, rerender } = renderHook(
      ({ count }: { count: number }) => useChatFollow(count, false),
      { initialProps: { count: 2 } },
    )
    scrollTo(result, 500)
    scrollTo(result, 100)
    const before = result.current.anchorId

    rerender({ count: 3 })

    expect(result.current.anchorId).not.toBe(before)
  })

  it('滚动位置透传给页面（issue #7265 折叠顶栏用）', () => {
    const onScrollOffset = jest.fn()
    const { result } = renderHook(() => useChatFollow(2, false, onScrollOffset))

    scrollTo(result, 320)

    expect(onScrollOffset).toHaveBeenCalledWith(320)
  })
})
