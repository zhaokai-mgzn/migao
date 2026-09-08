import type { ChatMessage } from '@/types'

/**
 * 交互组件渲染状态
 *
 * 企业级固定渲染（issue #3036）：渲染决策收敛为纯函数，依据消息级状态
 * （interactive / interactiveAnswered / isStreaming）——与组件挂载、FAB
 * 重开、会话切换、页面刷新均无关，杜绝「一会可交互、一会只读/消失」。
 */
export type InteractiveRenderState = 'interactive' | 'readonly' | 'hidden'

/**
 * 决策：给定消息，返回交互组件应处的渲染状态。
 *
 * - hidden：无 interactive，或流式中（卡片延迟到流结束展示，避免闪烁）
 * - interactive：有 interactive 且未答复 → 可点击操作
 * - readonly：有 interactive 且已答复（interactiveAnswered=true）→ 同构只读
 *   变体（按钮置灰不可点），历史回放/FAB 重开均保持锁定，防重复提交
 */
export function resolveInteractiveState(
  message: Pick<
    ChatMessage,
    'interactive' | 'interactiveAnswered' | 'isStreaming'
  >,
): InteractiveRenderState {
  if (!message.interactive) return 'hidden'
  if (message.isStreaming) return 'hidden'
  return message.interactiveAnswered ? 'readonly' : 'interactive'
}