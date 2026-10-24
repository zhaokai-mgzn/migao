'use client'

import { useCallback, useEffect, useRef } from 'react'
import type { RefObject } from 'react'

/**
 * 「贴底跟随」滚动（issue #7263）
 *
 * ## 治的形态（用户 2026-10-18 逐字）
 *
 * > 「打字效果出来了，但是屏幕不是跟着文字自动往下滑动的，还需要人来滑动」
 *
 * 根因：`MessageList` 的自动滚底只绑 `messages` 数组，而打字机在气泡内部逐字揭示
 * （`useTypewriter` 的本地 state，20ms/字）**不改 messages** ⇒ 揭示期间一次都不触发。
 *
 * ## 形态（四条不变量，判据见 tests/unit/hooks/use-stick-to-bottom.test.tsx）
 *
 * 1. **贴底跟随**：内容容器**真实高度**变化（逐字 / 图片 / 卡片加载）⇒ 还在底部附近就滚到底；
 * 2. **不抢用户**：用户滑离底部超过阈值 ⇒ 停止跟随；滑回底部附近 ⇒ 自动恢复；
 * 3. **强制回底**：`scrollToBottom()`（新消息 / 切会话）⇒ 回到底部并恢复跟随；
 * 4. **零新依赖**：只借 `ResizeObserver`（浏览器原生）与滚动容器的几何读数。
 *
 * ⚠️ 逐字揭示用**即时**滚动（`scrollTop = scrollHeight`），不用 smooth —— 20ms 一帧的
 * smooth 动画会互相打断，看起来像「抖动追赶」。
 */

/** 距底多少 CSS px 以内算「用户还在看底部」 */
export const STICK_THRESHOLD_PX = 80

export interface ScrollMetrics {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

/** 纯判定：用户是否贴着底部（内容不足一屏 ⇒ 恒为真） */
export function isNearBottom(
  { scrollTop, scrollHeight, clientHeight }: ScrollMetrics,
  threshold = STICK_THRESHOLD_PX,
): boolean {
  if (scrollHeight <= clientHeight) return true
  return scrollHeight - (scrollTop + clientHeight) <= threshold
}

/**
 * @param containerRef 滚动容器（`overflow-y-auto`）
 * @param contentRef   内容容器（它的高度变化 = 有新内容上屏）
 * @param attachKey    容器挂载/重挂载的信号（例：`sessionId:消息数`）—— 空态/加载态时容器还没渲染，
 *                     没有这个信号 effect 不会重跑，列表出现后就不再有 ResizeObserver
 */
export function useStickToBottom(
  containerRef: RefObject<HTMLElement | null>,
  contentRef: RefObject<HTMLElement | null>,
  attachKey?: unknown,
) {
  const stickRef = useRef(true)

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = 'auto') => {
      const el = containerRef.current
      if (!el) return
      stickRef.current = true
      if (typeof el.scrollTo === 'function') {
        el.scrollTo({ top: el.scrollHeight, behavior })
      } else {
        el.scrollTop = el.scrollHeight
      }
    },
    [containerRef],
  )

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onScroll = () => {
      stickRef.current = isNearBottom({
        scrollTop: el.scrollTop,
        scrollHeight: el.scrollHeight,
        clientHeight: el.clientHeight,
      })
    }
    el.addEventListener('scroll', onScroll, { passive: true })

    let observer: ResizeObserver | undefined
    const content = contentRef.current
    if (content && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => {
        if (!stickRef.current) return
        // 即时贴底（不是 smooth）：逐字揭示 20ms 一帧，smooth 会被下一帧打断
        el.scrollTop = el.scrollHeight
      })
      observer.observe(content)
    }

    return () => {
      el.removeEventListener('scroll', onScroll)
      observer?.disconnect()
    }
  }, [containerRef, contentRef, attachKey])

  return { scrollToBottom, stickRef }
}
