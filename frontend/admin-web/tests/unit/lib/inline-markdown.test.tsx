// case_ids: PR-105
/**
 * 行内强调渲染器（issue #5194 **改判**，用户 2026-09-23 裁定）—— `@/lib/inline-markdown` 单元面。
 *
 * ## 分工
 *
 * 本文件只判**渲染器本身**（标记 ↔ 元素的映射 + 不许吞字的负控）；
 * 「真实组件把标记喂进来了吗」在
 * `tests/unit/components/CraftCalcGlossary.test.tsx` /
 * `tests/unit/components/TenantParamsPanel.test.tsx` /
 * `tests/unit/pages/production-routings.test.tsx` 的 DOM 判据里（那三条同时判
 * 「裸标记不上屏」与「强调真的以元素呈现」—— 只判前者的话，把标记删掉也能绿 = 丢强调）。
 *
 * ## 为什么不是 `react-markdown`（已装依赖，聊天气泡在用）
 *
 * 它的语义比本仓需要**宽**：`*x*` 会变斜体（文案里的 `****` 掩码、单星号、正则片段是
 * **数据不是强调**），且默认输出块级 `<p>`（这些文案嵌在 `<p>`/`<span>`/`<td>` 里 ⇒ 非法嵌套）。
 */
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { InlineMarkdown } from '@/lib/inline-markdown'

function box(text: string) {
  const { container } = render(<InlineMarkdown text={text} />)
  return container
}

describe('InlineMarkdown：只认 `**粗**` 与 `` `等宽` ``，其余逐字原样', () => {
  it('① 映射：`**x**` ⇒ <strong>、`` `x` `` ⇒ <code>（可混排在句子里）', () => {
    const c = box('甲**乙**丙`丁`戊')
    expect(Array.from(c.querySelectorAll('strong')).map((el) => el.textContent)).toEqual(['乙'])
    expect(Array.from(c.querySelectorAll('code')).map((el) => el.textContent)).toEqual(['丁'])
    // 注入：把 `<strong>` 改回纯文本 ⇒ 上面第一条红
    expect(c.textContent).toBe('甲乙丙丁戊')
  })

  it('② 语义不变：去掉标记后的可见文本与原文**逐字相等**（不吞字、不加字）', () => {
    const c = box('超高的判据是**客户口径**（可配），非 ERP 实证`oversize_height_threshold`')
    // 注入：解析时把标记**连同内容**一起丢掉 ⇒ 本条红
    expect(c.textContent).toBe('超高的判据是客户口径（可配），非 ERP 实证oversize_height_threshold')
  })

  it('③ 负控：单星号 / 未闭合 `**` / 掩码 `****` / 正则片段**不得**被当成强调', () => {
    for (const raw of ['单个*星号*不斜体', '未闭合的 **星号照原样上屏', '手机号 138****8888', '正则 \\*\\* 片段']) {
      const c = box(raw)
      expect(c.querySelectorAll('strong').length, raw).toBe(0)
      expect(c.querySelectorAll('code').length, raw).toBe(0)
      // 注入：把 `*` 也当强调解析 ⇒ 掩码 `****` 会被吞成空串、本条红
      expect(c.textContent, raw).toBe(raw)
    }
  })

  it('④ 无注入面：尖括号 / 属性样式文本按**文本**呈现（不建元素、不碰 dangerouslySetInnerHTML）', () => {
    const raw = '<img src=x onerror=alert(1)>'
    const c = box(raw)
    expect(c.querySelectorAll('img').length).toBe(0)
    expect(c.textContent).toBe(raw)
  })
})
