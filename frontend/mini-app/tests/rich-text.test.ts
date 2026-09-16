// case_ids: UI-042
/**
 * richText 解析器测试（C 端助手消息富文本渲染，UI-042）
 *
 * 覆盖：
 * - 成对 **x** → bold 段；行内多个 bold；bold 与普通文本混合
 * - 未闭合 ** 原样保留（流式安全：LLM 边输出边解析时不应闪出解析产物）
 * - 单个 * 不误吞（价格场景「¥29/米」等）
 * - `- ` / `• ` 开头行 → bullet 行（选项列表）
 * - 空行保留（段落间距）；空内容 → 空数组
 */
import { parseRichText } from '../src/utils/richText'

describe('parseRichText', () => {
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
    const lines = parseRichText('- **A类母婴级标准**，无甲醛\n- 遮光率 95%')
    expect(lines).toHaveLength(2)
    expect(lines[0].bullet).toBe(true)
    expect(lines[0].segments).toEqual([
      { text: 'A类母婴级标准', bold: true },
      { text: '，无甲醛' },
    ])
    expect(lines[1].bullet).toBe(true)
    expect(lines[1].segments).toEqual([{ text: '遮光率 95%' }])
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
