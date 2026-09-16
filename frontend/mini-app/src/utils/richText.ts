/**
 * 富文本解析（C 端助手消息渲染，UI-042）
 *
 * 最小子集：**粗体** + `- ` / `• ` 列表（LLM 回复实际出现的 markdown 形态，真机实测）
 * 设计约束：
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
