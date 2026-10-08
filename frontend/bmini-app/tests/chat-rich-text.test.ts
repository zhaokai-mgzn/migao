// case_ids: UI-084
/**
 * richText 解析器测试（B 端黄金策消息富文本渲染，issue #6346 / 用例 UI-084）
 *
 * 与 C 端 `frontend/mini-app/tests/rich-text.test.ts`（UI-042）同口径 —— B 端此前是纯文本
 * `pre-wrap`，`**` 与 `- ` 原样上屏。覆盖：
 * - 成对 **x** → bold 段；行内多个 bold；bold 与普通文本混合
 * - 未闭合 ** 原样保留（流式安全：LLM 边输出边解析时不应闪出解析产物）
 * - 单个 * 不误吞（价格场景「¥29/米」等）
 * - `- ` / `• ` 开头行 → bullet 行（能力清单用的就是这个形态）
 * - 空行保留（段落间距）；空内容 → 空数组
 */
import { parseRichText } from '../src/utils/richText'

describe('parseRichText（B 端）', () => {
  it('成对粗体解析为 bold 段，混合普通文本', () => {
    const lines = parseRichText('您好 **9231 遮光窗帘** 正在促销')
    expect(lines).toHaveLength(1)
    expect(lines[0].segments).toEqual([
      { text: '您好 ' },
      { text: '9231 遮光窗帘', bold: true },
      { text: ' 正在促销' },
    ])
  })

  it('一行内多个粗体段', () => {
    const lines = parseRichText('**几米** 和 **颜色** 都需要确认')
    expect(lines[0].segments).toEqual([
      { text: '几米', bold: true },
      { text: ' 和 ' },
      { text: '颜色', bold: true },
      { text: ' 都需要确认' },
    ])
  })

  it('未闭合的 ** 原样保留（流式安全）', () => {
    const lines = parseRichText('选 **颜色')
    expect(lines[0].segments).toEqual([{ text: '选 **颜色' }])
  })

  it('单个星号不误吞', () => {
    const lines = parseRichText('单价 ¥29/米 * 2.8 = 81.2')
    expect(lines[0].segments).toEqual([{ text: '单价 ¥29/米 * 2.8 = 81.2' }])
  })

  it('- 开头行解析为 bullet 行，行内 bold 保留', () => {
    const lines = parseRichText('- **订单与履约** - 订单/物流查询\n- 生产进度与报工')
    expect(lines).toHaveLength(2)
    expect(lines[0].bullet).toBe(true)
    expect(lines[0].segments).toEqual([
      { text: '订单与履约', bold: true },
      { text: ' - 订单/物流查询' },
    ])
    expect(lines[1].bullet).toBe(true)
    expect(lines[1].segments).toEqual([{ text: '生产进度与报工' }])
  })

  it('• 开头行同样解析为 bullet', () => {
    const lines = parseRichText('• 轨道顺滑\n• 静音')
    expect(lines.every((l) => l.bullet)).toBe(true)
  })

  it('空行保留（段落间距）', () => {
    const lines = parseRichText('第一段\n\n第二段')
    expect(lines).toHaveLength(3)
    expect(lines[1].segments).toEqual([{ text: '' }])
    expect(lines[1].bullet).toBeUndefined()
  })

  it('空内容返回空数组', () => {
    expect(parseRichText('')).toEqual([])
    expect(parseRichText(undefined as unknown as string)).toEqual([])
  })

  it('纯普通文本整行一个 segment', () => {
    const lines = parseRichText('欢迎咨询窗帘定制')
    expect(lines[0].segments).toEqual([{ text: '欢迎咨询窗帘定制' }])
  })
})
