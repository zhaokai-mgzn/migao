// case_ids: UI-126
/**
 * 黄金策（B 端手机端）表格渲染 —— issue #7235 / 用例 UI-126
 *
 * ## 治的形态
 *
 * `frontend/bmini-app/src/components/chat/MessageBubble.tsx` 此前只有「按行 + 粗体 + bullet」渲染，
 * GFM 表格整段按普通文本上屏（用户 2026-10-18 手机端实测：一排 `|---|`）。
 *
 * ## 判据（逐条能红）
 *
 * ① 一段带表格的回复 ⇒ 渲染出 `.message-bubble__table`，且 **DOM 文本里零字面 `|`**（不再是裸 markdown）；
 * ② 行数 = 表头 1 + 数据行 N，表头单元格 3 个、数据行也 3 个（列数不错位）；
 * ③ 表格包在 `scrollX` 容器里（窄屏可横滑，不把气泡撑破）；
 * ④ 负控：普通句子里的 `|`（`a | b`）**不**渲染成表格；
 * ⑤ 表格里的粗体仍走 `.message-bubble__text-strong`；
 * ⑥ 既有行渲染契约不回归（`.message-bubble__line` 计数仍按普通行算）。
 *
 * 红证（修前红）：改前 `MessageBubble` 没有任何表格 DOM ⇒ 判据 ① 的 `.message-bubble__table`
 * 零命中、且 `container.textContent` 含字面 `|`（实测读数写 PR body）。
 */
import React from 'react'
import { render } from '@testing-library/react'
import MessageBubble from '../src/components/chat/MessageBubble'
import type { Message } from '../src/types'

function aiMsg(content: string): Message {
  return {
    id: 'm-table-1',
    role: 'assistant',
    content,
    created_at: '2026-10-18T08:45:00+08:00',
  }
}

const TABLE = [
  '最近的售后工单：',
  '| 工单号 | 客户 | 状态 |',
  '| --- | --- | --- |',
  '| AS-20261018-0005 | 回归客户-O5 | 🟡 待处理 |',
  '| AS-20261018-0004 | 回归客户-O1 | 🟡 待处理 |',
].join('\n')

describe('MessageBubble — UI-126 表格渲染', () => {
  it('① 带表格的回复渲染成表格组件，DOM 文本零字面管道符', () => {
    const { container } = render(<MessageBubble message={aiMsg(TABLE)} />)
    expect(container.querySelectorAll('.message-bubble__table')).toHaveLength(1)
    expect(container.textContent).not.toContain('|')
    expect(container.textContent).not.toContain('---')
  })

  it('② 行数 = 表头 1 + 数据行 2，列数 3 不错位', () => {
    const { container } = render(<MessageBubble message={aiMsg(TABLE)} />)
    const rows = container.querySelectorAll('.message-bubble__table-row')
    expect(rows).toHaveLength(3)
    const headerCells = container.querySelectorAll('.message-bubble__table-cell--header')
    expect(headerCells).toHaveLength(3)
    expect(Array.from(headerCells).map((c) => c.textContent)).toEqual([
      '工单号',
      '客户',
      '状态',
    ])
    const bodyRows = container.querySelectorAll(
      '.message-bubble__table-row:not(.message-bubble__table-row--header)',
    )
    expect(bodyRows).toHaveLength(2)
    expect(bodyRows[0].querySelectorAll('.message-bubble__table-cell')).toHaveLength(3)
  })

  it('③ 表格包在横向滚动容器里（窄屏可横滑）', () => {
    const { container } = render(<MessageBubble message={aiMsg(TABLE)} />)
    const scroll = container.querySelector('.message-bubble__table-scroll')
    expect(container.querySelectorAll('.message-bubble__table-scroll')).toHaveLength(1)
    expect(scroll?.querySelectorAll('.message-bubble__table')).toHaveLength(1)
    // 有表格的气泡允许比纯文本气泡更宽（78% → 94%），否则 3 列必然挤成一列
    expect(container.querySelectorAll('.message-bubble__wrapper--wide')).toHaveLength(1)
  })

  it('④ 负控：普通句子里的 | 不是表格', () => {
    const { container } = render(<MessageBubble message={aiMsg('尺码 a | b 都可以')} />)
    expect(container.querySelector('.message-bubble__table')).toBeNull()
    expect(container.textContent).toContain('a | b')
  })

  it('⑤ 表格单元格里的 **粗体** 仍加粗', () => {
    const md = ['| 名称 | 金额 |', '| --- | --- |', '| **加工费** | ¥120 |'].join('\n')
    const { container } = render(<MessageBubble message={aiMsg(md)} />)
    const strong = container.querySelector('.message-bubble__table .message-bubble__text-strong')
    expect(strong?.textContent).toBe('加工费')
    expect(container.textContent).not.toContain('**')
  })

  it('⑥ 既有行渲染契约不回归：表格外的普通行仍按 line 渲染', () => {
    const { container } = render(<MessageBubble message={aiMsg(TABLE)} />)
    const lines = container.querySelectorAll('.message-bubble__line')
    expect(lines).toHaveLength(1)
    expect(lines[0].textContent).toBe('最近的售后工单：')
  })
})
