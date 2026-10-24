/**
 * 富文本解析（B 端黄金策消息渲染，issue #6346 / #7235）
 *
 * 与 C 端 `frontend/mini-app/src/utils/richText.ts`（UI-042）**同口径**的最小子集：
 * `**粗体**` + `- ` / `• ` 列表 + **GFM 表格**（issue #7235）。B 端此前是纯文本 `pre-wrap`，
 * `**` / `- ` / `| --- |` 原样上屏（C 端早就治过，B 端漏课；两端各持一份本地实现，
 * **不做跨 App 共享模块**：共享模块落在发布集之外会白屏，#6306 教训）。
 *
 * 设计约束（逐条有判据，见 tests/chat-rich-text.test.ts 与 tests/chat-rich-text-table.test.ts）：
 * - 流式安全：未闭合的 `**` 原样保留（边输出边解析时不闪出解析产物）；
 *   **表格同理** —— 分隔行没到齐就还是普通文本，不闪出半张表；
 * - 单个 `*` 不误吞（价格场景「¥29/米」等）；
 * - 纯函数、无依赖，供 MessageBubble 按块渲染。
 */

export interface RichSegment {
  text: string
  bold?: boolean
}

export interface RichLine {
  segments: RichSegment[]
  /** 是否列表项（`- ` / `• ` 开头） */
  bullet?: boolean
}

/** 单元格对齐（GFM 分隔行的 `:--` / `:-:` / `--:`；无标记 = undefined） */
export type TableAlign = 'left' | 'center' | 'right' | undefined

/** GFM 表格：表头 / 逐列对齐 / 数据行（单元格已做行内粗体解析） */
export interface RichTable {
  header: RichSegment[][]
  align: TableAlign[]
  rows: RichSegment[][][]
}

/** 渲染块：普通行（可含多行）或表格 */
export type RichBlock =
  | { kind: 'lines'; lines: RichLine[] }
  | { kind: 'table'; table: RichTable }

/** 行内粗体解析：只匹配成对 **x**，未闭合与单个 * 原样保留 */
function parseBold(body: string): RichSegment[] {
  const segments: RichSegment[] = []
  const re = /\*\*([^*]+)\*\*/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(body)) !== null) {
    if (m.index > last) segments.push({ text: body.slice(last, m.index) })
    segments.push({ text: m[1], bold: true })
    last = m.index + m[0].length
  }
  if (last < body.length) segments.push({ text: body.slice(last) })
  return segments.length > 0 ? segments : [{ text: '' }]
}

/** 普通行解析（既有口径，未变） */
function parseLine(line: string): RichLine {
  const trimmed = line.trimStart()
  const bullet = /^[-•]\s+/.test(trimmed)
  const body = bullet ? trimmed.replace(/^[-•]\s+/, '') : line
  return { segments: parseBold(body), ...(bullet ? { bullet: true } : {}) }
}

/**
 * 按竖线切单元格（GFM：首尾竖线可省略）。
 * 不含竖线的行**不是**表格行（返回 null）—— 这是「普通句子里的 `|`」与表格的分界。
 */
function splitTableRow(line: string): string[] | null {
  const trimmed = line.trim()
  if (!trimmed.includes('|')) return null
  let body = trimmed
  if (body.startsWith('|')) body = body.slice(1)
  if (body.endsWith('|')) body = body.slice(0, -1)
  return body.split('|').map((cell) => cell.trim())
}

/** 解析分隔行（`| --- | :-- |`）→ 逐列对齐；不是分隔行返回 null */
function parseTableAlign(line: string): TableAlign[] | null {
  const cells = splitTableRow(line)
  if (!cells || cells.length === 0) return null
  const align: TableAlign[] = []
  for (const cell of cells) {
    if (!/^:?-+:?$/.test(cell)) return null
    const left = cell.startsWith(':')
    const right = cell.endsWith(':')
    align.push(left && right ? 'center' : right ? 'right' : left ? 'left' : undefined)
  }
  return align
}

/**
 * 富文本解析（块级）：把内容切成「普通行块」与「表格块」。
 *
 * 表格识别 = **表头行 + 分隔行**（列数必须一致，GFM 口径）：
 * - 分隔行未到 ⇒ 仍是普通行（流式安全，不闪半张表）；
 * - 数据行缺格补空、多格截断（列数按分隔行定，不错位）；
 * - 空行 / 非竖线行结束表格。
 */
export function parseRichContent(content: string): RichBlock[] {
  if (!content) return []
  const lines = content.split('\n')
  const blocks: RichBlock[] = []
  let pending: RichLine[] = []
  const flush = () => {
    if (pending.length > 0) {
      blocks.push({ kind: 'lines', lines: pending })
      pending = []
    }
  }

  let i = 0
  while (i < lines.length) {
    const header = splitTableRow(lines[i])
    const align = i + 1 < lines.length ? parseTableAlign(lines[i + 1]) : null
    if (header && align && header.length === align.length) {
      const rows: RichSegment[][][] = []
      let j = i + 2
      while (j < lines.length) {
        const cells = splitTableRow(lines[j])
        if (!cells) break
        rows.push(align.map((_, ci) => parseBold(cells[ci] ?? '')))
        j++
      }
      flush()
      blocks.push({
        kind: 'table',
        table: { header: header.map((cell) => parseBold(cell)), align, rows },
      })
      i = j
      continue
    }
    pending.push(parseLine(lines[i]))
    i++
  }
  flush()
  return blocks
}

/** 行级解析（既有对外契约，保留 —— 粗体 / bullet / 空行逐行） */
export function parseRichText(content: string): RichLine[] {
  if (!content) return []
  return content.split('\n').map(parseLine)
}
