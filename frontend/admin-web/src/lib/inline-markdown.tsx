import type { ReactNode } from 'react'

/**
 * 商家可见文案里的**行内强调**渲染（issue #5194 改判，用户 2026-09-23 裁定）。
 *
 * ## 为什么要有它
 *
 * 算料 / 余料这些说明文案的**单一真值**在 `@/lib/craft-calc-glossary` 与 `@/lib/tenant-params`
 * （以及各组件里与该口径同源的 JSX 文本）。作者用 `**强调**` 与 `` `键名` `` 标出
 * 「哪几个字是重点」「哪一段是配置键」—— 但渲染层原先只有**纯文本插值**，
 * 标记被**原样上屏**成字面星号 / 反引号（商家截图实证：`**净窗高**超过…`、
 * `净窗高 > 超高阈值（\`oversize_height_threshold\`）`）。
 *
 * 两条出路里选了「**渲染**」而不是「删掉标记」（#5206 走的是后者，随后按用户裁定改判）：
 * 删标记能让星号消失，但**强调本身也没了** —— 商家看到的是没有层级的长散文。
 *
 * ## 范围（有意收窄：这不是 markdown 解析器）
 *
 * 只认**两种行内标记**，其余**逐字原样**（含未闭合的 `**`、单星号 `*`、手机号掩码 `****`、
 * 正则片段）：
 * - `**x**` ⇒ `<strong>x</strong>`
 * - `` `x` `` ⇒ `<code>x</code>`
 *
 * 🔴 **不复用 `react-markdown`**（仓库里已装、聊天页在用）—— 它的语义**比这里宽**：
 * ① `*x*` 会被当作斜体（本仓文案里的单星号、掩码 `****` 是**数据不是强调**）；
 * ② 默认输出**块级** `<p>`，而这些文案嵌在 `<p>` / `<span>` / `<td>` 里 ⇒ 非法嵌套。
 * 本模块只做**行内**替换、返回片段（fragment），嵌进上述任一位置都合法。
 *
 * ## 判据（`tests/unit/lib/inline-markdown.test.tsx`，逐条能红）
 *
 * ① `**x**` ⇒ `<strong>`、`` `x` `` ⇒ `<code>`；② 其它文本**逐字不变**（`textContent` 相等）；
 * ③ 未闭合 / 单个 `*` / 掩码 `****` **不得**被吞（负控）；④ **绝不**产生 HTML 注入面
 * （本模块只建元素、不碰 `dangerouslySetInnerHTML`）。
 */
export function InlineMarkdown({ text }: { text: string }): ReactNode {
  // 每次渲染新建（不用模块级 `g` 正则：`lastIndex` 是**跨调用共享**的状态，容易被递归渲染踩到）
  const token = /\*\*([^*]+)\*\*|`([^`]+)`/g
  const nodes: ReactNode[] = []
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = token.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index))
    const key = match.index
    nodes.push(
      match[1] !== undefined ? (
        <strong key={key}>{match[1]}</strong>
      ) : (
        <code key={key} className="rounded bg-neutral-100 px-1 py-0.5">
          {match[2]}
        </code>
      )
    )
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return <>{nodes}</>
}

export default InlineMarkdown
