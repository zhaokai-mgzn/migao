// case_ids: UI-084
/**
 * 米宝（B 端小程序 / H5）气泡富文本渲染 —— issue #6346 / 用例 UI-084
 *
 * ## 治的形态
 *
 * `frontend/bmini-app/src/components/chat/MessageBubble.tsx` 此前把整段 `content` 塞进**一个**
 * `white-space: pre-wrap` 的 `<Text>` ⇒ 换行保留、但 markdown 标记**原样上屏**：
 * 米宝能力清单（`**订单与履约** - 订单/物流查询…`）里商家看到的是字面 `**` 与 `- `。
 * C 端在 2026-09-15（UI-042）就治过同一形态，B 端漏课。
 *
 * ## 判据（逐条能红）
 *
 * ① 成对 `**x**` ⇒ 加粗样式类，**DOM 文本里不得出现字面 `**`**；
 * ② `- ` 开头行 ⇒ bullet 行容器（标记不进文本）；
 * ③ 多行内容 ⇒ 按行渲染（行数 = `\n` 切分数），空行保留 `--empty` 占位；
 * ④ **负控**：未闭合 `**`（流式中间态）原样保留，不许被吞成半截加粗。
 *
 * 红证（修前红）：本轮修复前的渲染是「一个 Text 装全文」⇒ 断言 ① 的
 * `textContent` 含字面 `**`、断言 ②/③ 的 `.message-bubble__line` 选择器**零命中** ⇒ 当场红。
 */
import React from 'react'
import { render } from '@testing-library/react'
import MessageBubble from '../src/components/chat/MessageBubble'
import type { Message } from '../src/types'

function aiMsg(content: string): Message {
  return {
    id: 'm-rich-1',
    role: 'assistant',
    content,
    created_at: '2026-10-05T08:45:00+08:00',
  }
}

describe('MessageBubble — UI-084 B 端富文本渲染', () => {
  it('成对 **粗体** 走加粗样式，DOM 文本无字面星号', () => {
    const { container } = render(
      <MessageBubble message={aiMsg('您好！我擅长**数据查询与分析**：')} />,
    )
    expect(container.textContent).not.toContain('**')
    const strong = container.querySelector('.message-bubble__text-strong')
    expect(strong?.textContent).toBe('数据查询与分析')
  })

  it('- 开头行渲染为 bullet 行（列表标记不进文本）', () => {
    const { container } = render(
      <MessageBubble message={aiMsg('- 订单与物流查询\n- 生产进度与报工')} />,
    )
    const bullets = container.querySelectorAll('.message-bubble__line--bullet')
    expect(bullets).toHaveLength(2)
    expect(Array.from(bullets).map((b) => b.textContent)).toEqual([
      '订单与物流查询',
      '生产进度与报工',
    ])
  })

  it('多行能力清单按行渲染：行数 = 换行切分数 + 1，空行保留段间距', () => {
    const content = '您好！我是米宝。\n\n📦 **订单与履约** - 订单/物流查询\n🏭 **生产与算料** - 工序库'
    const { container } = render(<MessageBubble message={aiMsg(content)} />)
    const lines = container.querySelectorAll('.message-bubble__line')
    expect(lines).toHaveLength(4)
    expect(container.querySelectorAll('.message-bubble__line--empty')).toHaveLength(1)
    expect(container.textContent).not.toContain('**')
    expect(container.querySelectorAll('.message-bubble__text-strong')).toHaveLength(2)
  })

  it('负控：未闭合 ** 原样保留（流式中间态不闪出半截加粗）', () => {
    const { container } = render(<MessageBubble message={aiMsg('选 **颜色')} />)
    expect(container.textContent).toContain('选 **颜色')
    expect(container.querySelector('.message-bubble__text-strong')).toBeNull()
  })
})
