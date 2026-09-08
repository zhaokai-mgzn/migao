/**
 * 交互组件渲染决策纯函数 — resolveInteractiveState
 * case_ids: UI-030
 *
 * 企业级固定渲染（issue #3036）：同一消息任何时候渲染结果一致——
 * interactive（等待用户）/ readonly（已答只读）/ hidden（无组件或流式中），
 * 决策依据是消息级状态（interactive/interactiveAnswered/isStreaming），
 * 与组件挂载/卸载、FAB 重开、会话切换均无关。
 */
import { describe, it, expect } from 'vitest'
import { resolveInteractiveState } from '@/lib/interactive-render'
import type { ChatMessage } from '@/types'

function msg(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: 'm1',
    role: 'assistant',
    content: '请选择',
    ...overrides,
  }
}

describe('resolveInteractiveState', () => {
  it('无 interactive → hidden（纯文本消息不渲染交互组件）', () => {
    expect(resolveInteractiveState(msg({}))).toBe('hidden')
  })

  it('有 interactive + 未答 + 非流式 → interactive（可点击）', () => {
    expect(resolveInteractiveState(msg({
      interactive: { component: 'choice', title: '请选择' },
    }))).toBe('interactive')
  })

  it('有 interactive + 已答 → readonly（只读变体，不可重复提交）', () => {
    expect(resolveInteractiveState(msg({
      interactive: { component: 'confirm', title: '确认创建订单' },
      interactiveAnswered: true,
    }))).toBe('readonly')
  })

  it('流式中 → hidden（卡片延迟到流结束展示）', () => {
    expect(resolveInteractiveState(msg({
      interactive: { component: 'choice', title: '请选择' },
      isStreaming: true,
    }))).toBe('hidden')
  })

  it('流式中 + 已答 → hidden（流式优先隐藏）', () => {
    expect(resolveInteractiveState(msg({
      interactive: { component: 'choice', title: '请选择' },
      isStreaming: true,
      interactiveAnswered: true,
    }))).toBe('hidden')
  })

  it('deterministic：同一输入恒返回同一结果（不依赖上下文/挂载状态）', () => {
    const base = msg({
      interactive: { component: 'choice', title: '请选择' },
      interactiveAnswered: false,
    })
    const a = resolveInteractiveState(base)
    const b = resolveInteractiveState({ ...base })
    expect(a).toBe(b)
    expect(a).toBe('interactive')
  })
})