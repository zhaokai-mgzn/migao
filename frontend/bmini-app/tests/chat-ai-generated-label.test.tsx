// case_ids: BM-007
/**
 * AI 生成内容标识（微信「深度合成 → AI问答」类目备注 + 《人工智能生成合成内容标识办法》2025-09-01）
 *
 * 机构要求原文（微信类目页）：**所有人工智能生成合成内容需在 AI 生成内容显著位置进行标注**，
 * 如明确标注为「AI生成、人工智能生成」或同等含义字样。
 *
 * 三层判据：
 * 1. 气泡级：assistant 消息的来源标识含「AI生成」（改前只有「🤖 AI 助手」= 不含要求字样）
 * 2. 对照：人工客服消息**不得**被打成 AI 生成（否则转人工后顾客看到的是假标识）
 * 3. 页面级：对话页常驻说明（不随消息滚动消失），且**真的挂在该页上**（源码接线断言）
 *
 * 边界（照实登记）：bmini 当前无复制/导出入口（chat 面无剪贴板调用）⇒ 本判据不覆盖「复制带标」；
 * 隐式标识（元数据）对纯文本对话无载体，口径未明（见 docs/algorithm-filing-research.md 待确认项 4）。
 */
import '@testing-library/jest-dom'
import fs from 'fs'
import path from 'path'
import { render, screen } from '@testing-library/react'
import MessageBubble from '../src/components/chat/MessageBubble'
import AiGeneratedNote from '../src/components/chat/AiGeneratedNote'

const AI_MESSAGE = {
  id: 'm-ai',
  role: 'assistant',
  content: '您好，我是黄金策。',
  created_at: '2026-11-04T04:00:00Z',
}

const HUMAN_MESSAGE = {
  ...AI_MESSAGE,
  id: 'm-human',
  content: '人工客服接手了。',
  source: 'human',
}

describe('AI 生成内容标识（BM-007）', () => {
  it('assistant 气泡的来源标识含「AI生成」', () => {
    render(<MessageBubble message={AI_MESSAGE as any} />)
    expect(screen.getByTestId('ai-generated-label').textContent).toContain('AI生成')
  })

  it('人工客服消息不冒充 AI 生成，且带人工标识', () => {
    render(<MessageBubble message={HUMAN_MESSAGE as any} />)
    expect(screen.queryByTestId('ai-generated-label')).toBeNull()
    expect(screen.getByTestId('human-agent-label').textContent).toContain('人工客服')
  })

  it('常驻提示文案含「人工智能生成」', () => {
    render(<AiGeneratedNote />)
    expect(screen.getByTestId('ai-generated-disclaimer').textContent).toContain('人工智能生成')
  })

  it('对话页真的挂了这条常驻提示（接线，不是只写了组件）', () => {
    const page = fs.readFileSync(
      path.resolve(__dirname, '../src/pages/chat/index/index.tsx'),
      'utf-8',
    )
    expect(page).toContain(
      "import AiGeneratedNote from '../../../components/chat/AiGeneratedNote'",
    )
    expect(page).toContain('<AiGeneratedNote />')
  })
})
