// case_ids: UI-126
/**
 * GFM 表格解析（B 端黄金策消息渲染，issue #7235 / 用例 UI-126）
 *
 * ## 治的形态
 *
 * 黄金策的查询类回复大量使用 GFM 表格（订单/加工单/售后工单清单）。B 端手机端
 * （`frontend/bmini-app/src/utils/richText.ts`）此前只认 `**粗体**` + `- `/`• ` 列表，
 * **表格不在子集内** ⇒ 每一行按普通文本渲染，商家看到的是一排 `|---|` 与 `| 单号 | ... |`。
 *
 * ## 判据（逐条能红）
 *
 * ① 表头 + 分隔行 + 数据行 ⇒ 一个 table 块（表头 / 对齐 / 数据行逐值）；
 * ② 列数按**分隔行**定：数据行缺格补空、多格截断（GFM 口径，不许错位）；
 * ③ 单元格内的 `**粗体**` 仍走 segments（表格不吞富文本）；
 * ④ 负控：没有分隔行的竖线文本（`a | b` 普通句子）**不是**表格；
 * ⑤ 负控（流式安全）：只有表头、分隔行还没到 ⇒ 原样文本，不闪出半张表；
 * ⑥ 空行结束表格（表格后紧跟的普通文本回到行渲染）；
 * ⑦ 对齐标记 `:--` / `:-:` / `--:` 逐列解析。
 *
 * 红证（修前红）：改前 `parseRichContent` 不存在 ⇒ 本文件 import 即失败；
 * 把表格分支摘掉（退回纯行解析）⇒ 判据 ① 的「块类型 = table」当场红（实测读数写 PR body）。
 */
import { parseRichContent } from '../src/utils/richText'

const TABLE = [
  '以下是最近的工单：',
  '| 工单号 | 客户 | 状态 |',
  '| --- | --- | --- |',
  '| AS-001 | 回归客户-O1 | 待处理 |',
  '| AS-002 | 回归客户-O5 | 已关闭 |',
  '共 2 条。',
].join('\n')

describe('parseRichContent — GFM 表格（UI-126）', () => {
  it('① 表头/分隔行/数据行 ⇒ 一个 table 块，前后普通行仍是 lines 块', () => {
    const blocks = parseRichContent(TABLE)
    expect(blocks.map((b) => b.kind)).toEqual(['lines', 'table', 'lines'])
    const table = blocks[1]
    if (table.kind !== 'table') throw new Error('第二个块必须是 table')
    expect(table.table.align).toEqual([undefined, undefined, undefined])
    expect(table.table.header.map((cell) => cell.map((s) => s.text).join(''))).toEqual([
      '工单号',
      '客户',
      '状态',
    ])
    expect(
      table.table.rows.map((row) => row.map((cell) => cell.map((s) => s.text).join(''))),
    ).toEqual([
      ['AS-001', '回归客户-O1', '待处理'],
      ['AS-002', '回归客户-O5', '已关闭'],
    ])
  })

  it('② 列数按分隔行定：缺格补空、多格截断（不错位）', () => {
    const md = ['| A | B |', '| --- | --- |', '| 1 |', '| 1 | 2 | 3 |'].join('\n')
    const blocks = parseRichContent(md)
    const table = blocks[0]
    if (table.kind !== 'table') throw new Error('第一个块必须是 table')
    expect(
      table.table.rows.map((row) => row.map((cell) => cell.map((s) => s.text).join(''))),
    ).toEqual([
      ['1', ''],
      ['1', '2'],
    ])
  })

  it('③ 单元格内 **粗体** 仍解析为 bold segment', () => {
    const md = ['| 名称 | 金额 |', '| --- | --- |', '| **加工费** | ¥120 |'].join('\n')
    const blocks = parseRichContent(md)
    const table = blocks[0]
    if (table.kind !== 'table') throw new Error('第一个块必须是 table')
    expect(table.table.rows[0][0]).toEqual([{ text: '加工费', bold: true }])
    expect(table.table.rows[0][1]).toEqual([{ text: '¥120' }])
  })

  it('④ 负控：没有分隔行的 a | b 普通句子不是表格', () => {
    const blocks = parseRichContent('尺码 a | b 都可以\n宽度 2.8 | 3.0 米')
    expect(blocks).toHaveLength(1)
    expect(blocks[0].kind).toBe('lines')
  })

  it('⑤ 负控（流式安全）：只有表头、分隔行未到 ⇒ 原样文本，不闪半张表', () => {
    const blocks = parseRichContent('| 单号 | 状态 |\n| 1 | 待处')
    expect(blocks.every((b) => b.kind === 'lines')).toBe(true)
    const text = blocks
      .flatMap((b) => (b.kind === 'lines' ? b.lines : []))
      .flatMap((line) => line.segments.map((s) => s.text))
      .join('')
    expect(text).toContain('|')
  })

  it('⑥ 空行结束表格：表格后的普通文本回到行渲染', () => {
    const md = ['| A |', '| --- |', '| 1 |', '', '合计 1 条'].join('\n')
    const blocks = parseRichContent(md)
    expect(blocks.map((b) => b.kind)).toEqual(['table', 'lines'])
    const tail = blocks[1].kind === 'lines' ? blocks[1].lines : []
    // 表格后的空行保留为空行占位，正文回到行渲染（不并进表格）
    expect(tail.map((line) => line.segments.map((s) => s.text).join(''))).toEqual([
      '',
      '合计 1 条',
    ])
  })

  it('⑦ 对齐标记逐列解析（:-- 左 / :-: 中 / --: 右）', () => {
    const md = ['| 左 | 中 | 右 |', '| :-- | :-: | --: |', '| 1 | 2 | 3 |'].join('\n')
    const blocks = parseRichContent(md)
    const table = blocks[0]
    if (table.kind !== 'table') throw new Error('第一个块必须是 table')
    expect(table.table.align).toEqual(['left', 'center', 'right'])
  })

  it('⑧ 首尾管道可省略（GFM 允许），列数仍按分隔行', () => {
    const blocks = parseRichContent('单号 | 状态\n--- | ---\n1 | 待处理')
    const table = blocks[0]
    if (table.kind !== 'table') throw new Error('第一个块必须是 table')
    expect(table.table.header.map((c) => c.map((s) => s.text).join(''))).toEqual(['单号', '状态'])
  })

  it('⑨ parseRichText 既有口径不变（回归负控）', () => {
    // 表格引入不许改动原来「行内粗体 + bullet」的对外契约
    const blocks = parseRichContent('- **订单与履约** - 订单/物流查询')
    expect(blocks).toEqual([
      {
        kind: 'lines',
        lines: [
          {
            segments: [
              { text: '订单与履约', bold: true },
              { text: ' - 订单/物流查询' },
            ],
            bullet: true,
          },
        ],
      },
    ])
  })
})
