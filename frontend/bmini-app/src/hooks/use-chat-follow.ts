import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 手机端对话区「贴底跟随」滚动（issue #7263）
 *
 * 用户逐字：「打字效果出来了，但是屏幕不是跟着文字自动往下滑动的，还需要人来滑动」。
 *
 * 旧实现的病灶：`ScrollView` 的 `scrollIntoView` 写成固定字符串（`scrollIntoViewRef` /
 * `counterRef` 是从没接到 JSX 的死代码）⇒ 只有首帧滚一次；且自动滚动只绑 `messages.length`，
 * 而打字机在 `MessageBubble` 内部逐字揭示（本地 state，20ms/字）**不改 messages** ⇒ 不跟随。
 *
 * 本 hook 的形态（判据见 `tests/chat-autoscroll.test.tsx`）：
 * 1. **贴底跟随**：内容长高（`followIfSticky`）⇒ 轮换两个底部锚点 ⇒ `scrollIntoView` 值变化
 *    ⇒ Taro 真正滚到底（Taro 只在 prop 值变化时滚）；100ms 节流 + 150ms 尾随落到最终底部；
 * 2. **不抢用户**：`scrollTop` 变小超过 6px ⇒ 用户在上滑回看 ⇒ 停止跟随；
 *    回到底部（`onScrollToLower`，`lowerThreshold=60`）⇒ 自动恢复；
 * 3. **强制回底**：新消息 / 流式状态变化 ⇒ 推进锚点并恢复跟随。
 */
export const ANCHORS = ['msg-anchor-a', 'msg-anchor-b'] as const

/** 上滑判定阈值（CSS px） */
const SCROLL_UP_TOLERANCE_PX = 6
/** 贴底推进的最小间隔（ms）——打字机 20ms/字，没必要每字都触发一次滚动 */
const BUMP_INTERVAL_MS = 100
/** 尾随提交延迟（ms）——最后一次增长可能不足一个间隔，兜一次「最终底部」 */
const SETTLE_DELAY_MS = 150

export function useChatFollow(
  messagesLength: number,
  isStreaming: boolean,
  onScrollOffset?: (scrollTop: number) => void,
) {
  const [anchorIndex, setAnchorIndex] = useState(0)
  const stickRef = useRef(true)
  const lastScrollTopRef = useRef(0)
  const lastBumpAtRef = useRef(0)
  const settleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const bump = useCallback(() => setAnchorIndex((prev) => (prev + 1) % ANCHORS.length), [])

  const followIfSticky = useCallback(() => {
    if (!stickRef.current) return
    const now = Date.now()
    if (now - lastBumpAtRef.current >= BUMP_INTERVAL_MS) {
      lastBumpAtRef.current = now
      bump()
    }
    if (settleTimerRef.current) clearTimeout(settleTimerRef.current)
    settleTimerRef.current = setTimeout(() => {
      if (stickRef.current) bump()
    }, SETTLE_DELAY_MS)
  }, [bump])

  const handleScroll = useCallback(
    (e: any) => {
      const scrollTop = Number(e?.detail?.scrollTop ?? 0)
      if (scrollTop < lastScrollTopRef.current - SCROLL_UP_TOLERANCE_PX) stickRef.current = false
      lastScrollTopRef.current = scrollTop
      onScrollOffset?.(scrollTop)
    },
    [onScrollOffset],
  )

  const handleScrollToLower = useCallback(() => {
    stickRef.current = true
  }, [])

  // 新消息 / 流式状态变化 ⇒ 强制回底并恢复跟随（切会话时消息数变化也走这里）
  useEffect(() => {
    stickRef.current = true
    bump()
  }, [messagesLength, isStreaming, bump])

  useEffect(
    () => () => {
      if (settleTimerRef.current) clearTimeout(settleTimerRef.current)
    },
    [],
  )

  return {
    anchorIndex,
    anchorId: ANCHORS[anchorIndex],
    followIfSticky,
    handleScroll,
    handleScrollToLower,
  }
}
