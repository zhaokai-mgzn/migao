'use client'

import { useEffect, useState } from 'react'

/** 揭示节奏 —— 20ms/字（docs/design/ui-design-spec.md §3.3） */
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

/** 是否声明了「减少动态效果」（SSR / 无 matchMedia ⇒ 按未声明处理 = 播放） */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/**
 * 客户端打字机（issue #5952；用户 2026-10-02 裁定「选 2（客户端打字机）」；
 * issue #7086 修「真实事件序下不播」）。
 *
 * **服务端不动**：后端仍整段下发 —— `graph.astream(stream_mode="updates")` 是**节点级**更新，
 * 且 `finalize_turn` 有后置收口（追加确认卡 XML / 用工具返回 message 替换回复）、
 * C 端出站还有跨片脱敏约束 ⇒ 服务端逐字会与「收口后才是最终文本」冲突。逐字只发生在客户端揭示层。
 *
 * 🔴 **为什么不看 `streaming`**（#7086 的根因）：正文是**一个** `text` 事件整段到达、紧随 `done`，
 * HTTP body 随即结束 ⇒ `isStreaming` 翻假距正文到达只有几十～两百毫秒。旧实现把
 * 「`streaming: false` ⇒ 立刻等于全文」当不变量 ⇒ **揭示窗口 ≈ 0，一帧都播不完**
 * （实测：结束瞬间已是 37/37 全文），用户看到的就是「一次性上屏」。
 * ⇒ 揭示**只由「内容是否在长」驱动、不绑生命周期**：直播消息挂载时是空占位 ⇒ 从 0 起逐字，
 * 且**流结束后继续把尾巴打完**；挂载时就已完整的消息（历史回放 / 切会话重挂载）⇒ 首帧即全文、不重播。
 *
 * 三条不变量（判据钉在 frontend/admin-web/tests/unit/hooks/use-typewriter.test.tsx）：
 * 1. **单调**：已揭示字符数**只增不减** —— 收口把文本**替换**（先短后长 / 整段改写）时，
 *    揭示位置不回头，绝不出现「先短后长再回退」；
 * 2. **以最终内容为准**：可见文本**永远是当前 `text` 的前缀** —— 收口版一到，后续揭示的就是收口版内容；
 * 3. **有界收敛**：`instant` / 减少动画 / 组件卸载 ⇒ 直接是全文（不卡半截）；直播消息则在
 *    **有界时长**内揭示完（{@link TYPEWRITER_MAX_REVEAL_MS}），不随文本长度无限拖尾。
 *
 * @returns 当前应显示的文本（完整文本的前缀）
 */
export function useTypewriter(text: string, options: TypewriterOptions = {}): string {
  const {
    instant = false,
    intervalMs = TYPEWRITER_INTERVAL_MS,
    maxRevealMs = TYPEWRITER_MAX_REVEAL_MS,
  } = options
  const full = text ?? ''
  // 首帧揭示位置 = **挂载时已有的长度**：历史回放 / 重挂载（进来就完整）⇒ 直接全文；
  // 直播消息挂载时是空占位（正文后到）⇒ 从 0 起逐字。这就是「不绑流式生命周期」的落点。
  const [revealed, setRevealed] = useState(full.length)

  // 立刻收敛：显式 instant / 不逐字 / 减少动态效果
  const snap = instant || intervalMs <= 0 || prefersReducedMotion()
  const drained = revealed >= full.length

  useEffect(() => {
    if (snap) {
      setRevealed(full.length)
      return
    }
    if (drained) return
    // 每次揭示的步长：默认 1 字/间隔；长文按 maxRevealMs 加速 ⇒ 「整段 ≤ 上界」的有界收尾
    const perTick =
      maxRevealMs > 0 ? Math.max(1, Math.ceil((intervalMs * full.length) / maxRevealMs)) : 1
    const timer = setInterval(() => {
      setRevealed(prev => {
        // 收口把文本改短（极端）⇒ 夹到当前长度；否则按步长前进，绝不越过全文
        if (prev >= full.length) return full.length
        return Math.min(full.length, prev + perTick)
      })
    }, intervalMs)
    return () => clearInterval(timer)
    // ⚠️ 依赖里**只放 `full.length`**：放的若是 `full`，每个流式分片都会重建定时器，
    // 分片比揭示间隔更密时计时器被反复重置 ⇒ 永远揭示不出第一个字（#5952 实现期实测坑）。
  }, [snap, drained, intervalMs, maxRevealMs, full.length])

  return full.slice(0, Math.min(revealed, full.length))
}
