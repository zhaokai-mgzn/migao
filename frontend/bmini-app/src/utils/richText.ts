/**
 * 富文本解析（B 端黄金策消息渲染，issue #6346）
 *
 * 与 C 端 `frontend/mini-app/src/utils/richText.ts`（UI-042）**同口径**的最小子集：
 * `**粗体**` + `- ` / `• ` 列表 —— B 端此前是纯文本 `pre-wrap`，`**` / `- ` 原样上屏
 * （C 端早就治过，B 端漏课；两端各持一份本地实现，**不做跨 App 共享模块**：
 * 共享模块落在发布集之外会白屏，#6306 教训）。
 *
 * 设计约束（逐条有判据，见 tests/rich-text.test.ts）：
 * - 流式安全：未闭合的 `**` 原样保留（边输出边解析时不闪出解析产物）
 * - 单个 `*` 不误吞（价格场景「¥29/米」等）
 * - 纯函数、无依赖，供 MessageBubble 按行渲染
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

export function parseRichText(content: string): RichLine[] {
  if (!content) return []
  return content.split('\n').map((line) => {
    const trimmed = line.trimStart()
    const bullet = /^[-•]\s+/.test(trimmed)
    const body = bullet ? trimmed.replace(/^[-•]\s+/, '') : line
    return { segments: parseBold(body), ...(bullet ? { bullet: true } : {}) }
  })
}
