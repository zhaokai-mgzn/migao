'use client'

import { useEffect, useState } from 'react'

/** 服务端整段下发（SSE `text` / `text_delta`）时的默认揭示节奏 —— 20ms/字（docs/design/ui-design-spec.md §3.3） */
export const TYPEWRITER_INTERVAL_MS = 20

export interface TypewriterOptions {
  /**
   * 是否仍在流式中（默认 true）。
   * `false` ⇒ **立刻**等于全文（结束 / 中断 / 错误 / 切会话 / 历史回放都走这条）。
   */
  streaming?: boolean
  /** 每字间隔（毫秒，默认 {@link TYPEWRITER_INTERVAL_MS}）；`0` = 不逐字 */
  intervalMs?: number
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
 * 客户端打字机（issue #5952；用户 2026-10-02 裁定「选 2（客户端打字机）」）。
 *
 * **服务端不动**：后端仍整段下发 —— `graph.astream(stream_mode="updates")` 是**节点级**更新，
 * 且 `finalize_turn` 有后置收口（追加确认卡 XML / 用工具返回 message 替换回复）、
 * C 端出站还有跨片脱敏约束 ⇒ 服务端逐字会与「收口后才是最终文本」冲突。逐字只发生在客户端揭示层。
 *
 * 三条不变量（判据钉在 frontend/admin-web/tests/unit/hooks/use-typewriter.test.ts）：
 * 1. **单调**：已揭示字符数**只增不减** —— 收口把文本**替换**（先短后长 / 整段改写）时，
 *    揭示位置不回头，绝不出现「先短后长再回退」；
 * 2. **以最终内容为准**：可见文本**永远是当前 `text` 的前缀** —— 收口版一到，后续揭示的就是收口版内容；
 * 3. **立刻收敛**：`streaming=false` / `intervalMs<=0` / 减少动画 / 组件卸载 ⇒ 直接是全文，不许卡在半截。
 *
 * @returns 当前应显示的文本（完整文本的前缀）
 */
export function useTypewriter(text: string, options: TypewriterOptions = {}): string {
  const { streaming = true, intervalMs = TYPEWRITER_INTERVAL_MS } = options
  const full = text ?? ''
  const [revealed, setRevealed] = useState(0)

  // 立刻收敛：流式结束 / 不逐字时，可见即全文（不做任何追赶动画）
  const instant = !streaming || intervalMs <= 0 || prefersReducedMotion()

  useEffect(() => {
    if (instant) {
      setRevealed(full.length)
      return
    }
    const timer = setInterval(() => {
      setRevealed(prev => {
        // 收口把文本改短（极端）⇒ 夹到当前长度；否则每次只 +1，绝不回退
        if (prev >= full.length) return full.length
        return prev + 1
      })
    }, intervalMs)
    return () => clearInterval(timer)
    // ⚠️ 依赖里**只放 `full.length`**：放的若是 `full`，每个流式分片都会重建定时器，
    // 分片比揭示间隔更密时计时器被反复重置 ⇒ 永远揭示不出第一个字（#5952 实现期实测坑）。
  }, [instant, intervalMs, full.length])

  return full.slice(0, Math.min(revealed, full.length))
}
