import { useEffect, useState } from 'react'

/** 揭示节奏 —— 20ms/字（与 PC `frontend/admin-web/src/hooks/use-typewriter.ts` 同口径） */
export const TYPEWRITER_INTERVAL_MS = 20

/**
 * 整段揭示的**时长上界**（毫秒，默认 3000）：长回复按「整段 ≤ 该时长」自动加速，
 * 避免用户为动画干等（短回复 ≤ 150 字时步长恒为 1，仍是 20ms/字 的原始节奏）。
 */
export const TYPEWRITER_MAX_REVEAL_MS = 3000

export interface TypewriterOptions {
  /**
   * 立刻等于全文、不逐字（用户中断 `wasAborted` / 调用方已知无需揭示）。默认 `false`。
   * ⚠️ **「流式结束」不在此列** —— 见下方「为什么不看 streaming」。
   */
  instant?: boolean
  /** 每字间隔（毫秒，默认 {@link TYPEWRITER_INTERVAL_MS}）；`0` = 不逐字 */
  intervalMs?: number
  /** 整段揭示时长上界（毫秒，默认 {@link TYPEWRITER_MAX_REVEAL_MS}）；`<=0` = 不封顶 */
  maxRevealMs?: number
}

/** 是否声明了「减少动态效果」（H5 / 无 matchMedia ⇒ 按未声明处理 = 播放） */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/**
 * 客户端打字机 —— **手机端执行点**（issue #7235；PC 同口径见 issue #5952 / #7086）。
 *
 * **服务端不动**：后端仍整段下发（`graph.astream(stream_mode="updates")` 是节点级更新，
 * `finalize_turn` 有后置收口，C 端出站还有跨片脱敏）⇒ 逐字只发生在客户端揭示层。
 *
 * 🔴 **为什么不看 `isStreaming`**（#7086 的根因，手机端同款）：正文是**一个** `text` 事件整段到达、
 * 紧随 `done`，`isStreaming` 翻假距正文到达只有几十～两百毫秒。把「流结束 ⇒ 立刻全文」
 * 当不变量 ⇒ 揭示窗口 ≈ 0，用户看到的就是「一次性上屏」。
 * ⇒ 揭示**只由「内容是否在长」驱动、不绑生命周期**：直播消息挂载时是空占位 ⇒ 从 0 起逐字，
 * 且**流结束后继续把尾巴打完**；挂载时就已完整的消息（历史回放 / 切会话重挂载）⇒ 首帧即全文、不重播。
 *
 * 三条不变量（判据见 tests/chat-typewriter.test.tsx）：
 * 1. **单调**：已揭示字符数只增不减；
 * 2. **以最终内容为准**：可见文本永远是当前 `text` 的前缀；
 * 3. **有界收敛**：`instant` / 减少动画 ⇒ 直接全文；直播消息在
 *    {@link TYPEWRITER_MAX_REVEAL_MS} 内有界揭示完。
 */
export function useTypewriter(text: string, options: TypewriterOptions = {}): string {
  const {
    instant = false,
    intervalMs = TYPEWRITER_INTERVAL_MS,
    maxRevealMs = TYPEWRITER_MAX_REVEAL_MS,
  } = options
  const full = text ?? ''
  // 首帧揭示位置 = **挂载时已有的长度**：历史回放 / 重挂载（进来就完整）⇒ 直接全文；
  // 直播消息挂载时是空占位（正文后到）⇒ 从 0 起逐字。
  const [revealed, setRevealed] = useState(full.length)

  const snap = instant || intervalMs <= 0 || prefersReducedMotion()
  const drained = revealed >= full.length

  useEffect(() => {
    if (snap) {
      setRevealed(full.length)
      return
    }
    if (drained) return
    // 每次揭示的步长：默认 1 字/间隔；长文按 maxRevealMs 加速 ⇒「整段 ≤ 上界」的有界收尾
    const perTick =
      maxRevealMs > 0 ? Math.max(1, Math.ceil((intervalMs * full.length) / maxRevealMs)) : 1
    const timer = setInterval(() => {
      setRevealed((prev) => {
        if (prev >= full.length) return full.length
        return Math.min(full.length, prev + perTick)
      })
    }, intervalMs)
    return () => clearInterval(timer)
    // ⚠️ 依赖里**只放 `full.length`**：放的若是 `full`，每个流式分片都会重建定时器，
    // 分片比揭示间隔更密时计时器被反复重置 ⇒ 永远揭示不出第一个字（#5952 实测坑）。
  }, [snap, drained, intervalMs, maxRevealMs, full.length])

  return full.slice(0, Math.min(revealed, full.length))
}
