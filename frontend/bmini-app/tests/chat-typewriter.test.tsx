// case_ids: UI-079
/**
 * 黄金策（B 端手机端）客户端打字机 —— issue #7235 / 用例 UI-079（#5952 / #7086 的**手机端执行点**）
 *
 * ## 治的形态
 *
 * PC（`frontend/admin-web`）在 #5952 / #7086 已有客户端打字机；**手机端
 * `frontend/bmini-app` 全仓零 `typewriter` 命中** ⇒ 后端整段下发（一个 text 事件到齐、紧随 done）
 * 时商家看到的是「一次性刷出」。服务端**不动**（理由同 PC：节点级 astream + finalize_turn 收口 +
 * C 端跨片脱敏），揭示只发生在客户端。
 *
 * ## 判据（逐条能红）
 *
 * ① **直播消息从 0 起逐字**：先挂空占位、正文后到（真实事件序）⇒ t 时刻 `data-revealed` **< 全长**
 *    且恒为**全文前缀**；最终 == 全长；
 * ② **有界收敛**：长文自动加速，整段揭示 ≤ `TYPEWRITER_MAX_REVEAL_MS`（不会无限拖尾）；
 * ③ **历史回放/重挂载立刻全文**（挂载即完整 ⇒ 不重播）；
 * ④ **用户中断（wasAborted）立刻全文**；
 * ⑤ **减少动画（prefers-reduced-motion: reduce）立刻全文**；
 * ⑥ **结束之后仍在逐字**（#7086 的口径）：`isStreaming` 已翻假但尾巴没打完 ⇒ 继续揭示，不跳全文。
 *
 * 红证（修前红）：改前 `MessageBubble` 没有 `data-revealed` 属性 ⇒ 判据 ① 首条断言
 * `expect(revealed()).toBe(0)` 读到 `undefined` 当场红；把 hook 换成直返全文 ⇒ 判据 ① 的
 * 「t 时刻 < 全长」与 ⑥ 同时红（实测读数写 PR body）。
 */
import React from 'react'
import { render, act } from '@testing-library/react'
import MessageBubble from '../src/components/chat/MessageBubble'
import type { Message } from '../src/types'
import { TYPEWRITER_INTERVAL_MS, TYPEWRITER_MAX_REVEAL_MS } from '../src/hooks/use-typewriter'

jest.useFakeTimers()

function aiMsg(content: string, extra: Partial<Message> = {}): Message {
  return {
    id: 'm-typewriter-1',
    role: 'assistant',
    content,
    created_at: '2026-10-18T08:45:00+08:00',
    ...extra,
  }
}

/** 可见字符数（揭示进度） */
function revealed(container: HTMLElement): number | null {
  const el = container.querySelector('.message-bubble__content')
  const raw = el?.getAttribute('data-revealed')
  return raw == null ? null : Number(raw)
}

/** 可见正文（去掉流式光标——光标是 UI 装饰，不是揭示内容） */
function visibleText(container: HTMLElement): string {
  const content = container.querySelector('.message-bubble__content')
  if (!content) return ''
  const texts = Array.from(content.querySelectorAll('.message-bubble__line'))
    .filter((line) => !line.classList.contains('message-bubble__line--empty'))
    .map((line) => line.textContent || '')
  return texts.join('\n')
}

const FULL = '这是黄金策的一段回复，用来验证手机端逐字揭示的节奏与边界。'

function advance(ms: number) {
  act(() => {
    jest.advanceTimersByTime(ms)
  })
}

describe('MessageBubble — UI-079 手机端打字机', () => {
  beforeEach(() => {
    jest.clearAllTimers()
  })

  it('① 直播消息从 0 起逐字：t 时刻 < 全长且恒为全文前缀，最终等长', () => {
    const { container, rerender } = render(<MessageBubble message={aiMsg('', { isStreaming: true })} />)
    // 真实事件序：正文整段到达（一个 text 事件）
    rerender(<MessageBubble message={aiMsg(FULL, { isStreaming: true })} />)

    expect(revealed(container)).toBe(0)

    advance(TYPEWRITER_INTERVAL_MS * 3)
    const mid = revealed(container) ?? 0
    expect(mid).toBeGreaterThan(0)
    expect(mid).toBeLessThan(FULL.length)
    expect(FULL.startsWith(visibleText(container))).toBe(true)

    advance(TYPEWRITER_INTERVAL_MS * (FULL.length + 10))
    expect(revealed(container)).toBe(FULL.length)
    expect(visibleText(container)).toBe(FULL)
  })

  it('② 有界收敛：长文按 TYPEWRITER_MAX_REVEAL_MS 加速，揭示完不超过上界', () => {
    const long = '很长的回复内容'.repeat(40) // 320 字
    const { container, rerender } = render(<MessageBubble message={aiMsg('', { isStreaming: true })} />)
    rerender(<MessageBubble message={aiMsg(long, { isStreaming: true })} />)

    advance(TYPEWRITER_MAX_REVEAL_MS + TYPEWRITER_INTERVAL_MS * 2)
    expect(revealed(container)).toBe(long.length)
  })

  it('③ 历史回放 / 重挂载（挂载即完整）⇒ 立刻全文，不重播', () => {
    const { container } = render(<MessageBubble message={aiMsg(FULL)} />)
    expect(revealed(container)).toBe(FULL.length)
    expect(visibleText(container)).toBe(FULL)
  })

  it('④ 用户中断（wasAborted）⇒ 立刻全文，不把尾巴慢慢打完', () => {
    const { container, rerender } = render(<MessageBubble message={aiMsg('', { isStreaming: true })} />)
    rerender(<MessageBubble message={aiMsg(FULL, { isStreaming: false, wasAborted: true })} />)
    expect(revealed(container)).toBe(FULL.length)
  })

  it('⑤ 减少动画（prefers-reduced-motion: reduce）⇒ 立刻全文', () => {
    const original = window.matchMedia
    // jsdom 没有 matchMedia 实现；这里只为驱动 hook 的偏好分支
    ;(window as unknown as { matchMedia: unknown }).matchMedia = jest.fn().mockReturnValue({
      matches: true,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    })
    try {
      const { container, rerender } = render(<MessageBubble message={aiMsg('', { isStreaming: true })} />)
      rerender(<MessageBubble message={aiMsg(FULL, { isStreaming: true })} />)
      expect(revealed(container)).toBe(FULL.length)
    } finally {
      if (original) window.matchMedia = original
      else delete (window as any).matchMedia
    }
  })

  it('⑦ 揭示过程中不闪半张表：表头到了、分隔行没到 ⇒ DOM 里没有裸管道符', () => {
    const md = '最近的工单：\n| 工单号 | 客户 |\n| --- | --- |\n| AS-001 | 张女士 |'
    const headerEnd = '最近的工单：\n| 工单号 | 客户 |'.length
    const { container, rerender } = render(<MessageBubble message={aiMsg('', { isStreaming: true })} />)
    rerender(<MessageBubble message={aiMsg(md, { isStreaming: true })} />)

    // 揭示到「表头刚露完、分隔行还没到」——这一两百毫秒正是旧形态闪裸 `|` 的窗口
    advance(TYPEWRITER_INTERVAL_MS * headerEnd)
    expect(revealed(container)).toBe(headerEnd)
    expect(visibleText(container)).toBe('最近的工单：')
    expect(visibleText(container)).not.toContain('|')
    expect(container.querySelectorAll('.message-bubble__table')).toHaveLength(0)

    // 分隔行到齐 ⇒ 表格直接出现（不用等数据行）
    advance(TYPEWRITER_INTERVAL_MS * ('| --- | --- |'.length + 1))
    expect(container.querySelectorAll('.message-bubble__table')).toHaveLength(1)
  })

  it('⑥ 结束之后仍在逐字（#7086 口径）：isStreaming=false 但尾巴没打完 ⇒ 继续揭示', () => {
    const { container, rerender } = render(<MessageBubble message={aiMsg('', { isStreaming: true })} />)
    rerender(<MessageBubble message={aiMsg(FULL, { isStreaming: true })} />)
    advance(TYPEWRITER_INTERVAL_MS * 2)
    const beforeDone = revealed(container) ?? 0
    expect(beforeDone).toBeGreaterThan(0)
    expect(beforeDone).toBeLessThan(FULL.length)

    // store 的 done 事件：正文后紧随 done（整段到达 + 立刻结束）
    rerender(<MessageBubble message={aiMsg(FULL, { isStreaming: false })} />)
    expect(revealed(container)).toBe(beforeDone) // 没跳全文
    advance(TYPEWRITER_INTERVAL_MS * 5)
    expect(revealed(container)).toBeGreaterThan(beforeDone)
    expect(revealed(container)).toBeLessThan(FULL.length)
  })
})
