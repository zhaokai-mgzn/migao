// case_ids: UI-126
/**
 * C 端（元元）助手消息的 **GFM 表格**渲染 —— issue #7235 / 用例 UI-126
 *
 * ## 为什么 C 端也在这个用例里
 *
 * 手机端表格裸上屏是**一份最小解析器的同一类缺陷**：C 端 `frontend/mini-app/src/utils/richText.ts`
 * 与 B 端 `frontend/bmini-app/src/utils/richText.ts` 是同口径的两份本地实现（#6306：不建跨 App
 * 共享模块）。B 端治、C 端不治 ⇒ 顾客侧看到同样的 `| --- |`（只是没人报）。
 * ⇒ 本文件把 C 端也钉进同一条用例（判据与 B 端 `frontend/bmini-app/tests/chat-rich-text-table.test.ts`
 * + `chat-table-render.test.tsx` **同口径**）。
 *
 * ## 判据（逐条能红）
 *
 * ① 表头 + 分隔行 + 数据行 ⇒ table 块（列数按分隔行定、缺格补空）；
 * ② 只有表头、分隔行未到（流式中间态）⇒ 仍是普通文本，不闪半张表；
 * ③ 渲染：`.message-bubble__table` 在场、DOM 文本零字面 `|`、表头 3 格 / 数据行 3 格；
 * ④ 负控：普通句子里的 `|` 不是表格。
 *
 * 红证（修前红）：改前两处实现都只有行解析 ⇒ 判据 ① 的 `parseRichContent` import 失败、
 * 判据 ③ 的 `.message-bubble__table` 零命中（实测读数写 PR body）。
 */
import React from 'react'
import { render } from '@testing-library/react'
import { parseRichContent } from '../src/utils/richText'
import MessageBubble from '../src/components/chat/MessageBubble'
import type { Message } from '../src/types'

const TABLE = [
  '最近的订单：',
  '| 单号 | 客户 | 状态 |',
  '| --- | --- | --- |',
  '| ORD-001 | 张女士 | 待发货 |',
  '| ORD-002 | 李先生 | 已发货 |',
].join('\n')

function aiMsg(content: string): Message {
  return {
    id: 'm-table-c1',
    role: 'assistant',
    content,
    created_at: '2026-10-18T08:45:00+08:00',
  }
}

const cellText = (cell: Array<{ text: string }>) => cell.map((s) => s.text).join('')

describe('C 端 richText — GFM 表格（UI-126）', () => {
  it('① 表头 + 分隔行 + 数据行 ⇒ table 块，列数按分隔行定', () => {
    const blocks = parseRichContent(TABLE)
    expect(blocks.map((b) => b.kind)).toEqual(['lines', 'table'])
    const table = blocks[1]
    if (table.kind !== 'table') throw new Error('第二个块必须是 table')
    expect(table.table.header.map(cellText)).toEqual(['单号', '客户', '状态'])
    expect(table.table.rows.map((row) => row.map(cellText))).toEqual([
      ['ORD-001', '张女士', '待发货'],
      ['ORD-002', '李先生', '已发货'],
    ])

    const truncated = parseRichContent(['| A | B |', '| --- | --- |', '| 1 |'].join('\n'))
    const t2 = truncated[0]
    if (t2.kind !== 'table') throw new Error('第一个块必须是 table')
    expect(t2.table.rows.map((row) => row.map(cellText))).toEqual([['1', '']])
  })

  it('② 负控（流式安全）：只有表头、分隔行未到 ⇒ 仍是普通文本', () => {
    const blocks = parseRichContent('| 单号 | 状态 |\n| 1 | 待处')
    expect(blocks.every((b) => b.kind === 'lines')).toBe(true)
  })
})

describe('C 端 MessageBubble — 表格渲染（UI-126）', () => {
  it('③ 表格渲染成表格组件，DOM 文本零字面管道符、列数不错位', () => {
    const { container } = render(<MessageBubble message={aiMsg(TABLE)} />)
    expect(container.querySelectorAll('.message-bubble__table')).toHaveLength(1)
    expect(container.textContent).not.toContain('|')
    const rows = container.querySelectorAll('.message-bubble__table-row')
    expect(rows).toHaveLength(3)
    expect(container.querySelectorAll('.message-bubble__table-cell--header')).toHaveLength(3)
    expect(container.querySelectorAll('.message-bubble__table-scroll')).toHaveLength(1)
    expect(container.querySelectorAll('.message-bubble__wrapper--wide')).toHaveLength(1)
  })

  it('④ 负控：普通句子里的 | 不是表格', () => {
    const { container } = render(<MessageBubble message={aiMsg('尺码 a | b 都可以')} />)
    expect(container.querySelector('.message-bubble__table')).toBeNull()
    expect(container.textContent).toContain('a | b')
  })
})
