// case_ids: PR-022
/**
 * 富文本 → **可读纯文本**（issue #6403 缺陷 2）—— 纯函数，**只给展示层用**。
 *
 * 病（用户 2026-10-06 实测，图 1 / 图 3）：识别结果卡的「商品描述」逐字显示
 * `<p>常青藤系列纯色遮光窗帘，18 款…</p><p>色号包含：…</p>` —— 而那个值是 **HTML 片段**
 * （落点是 `ProductForm` 的 `RichTextEditor`，入库需要 HTML ⇒ **不许**从落值里删标签）。
 *
 * 口径（issue #6403）：**只改展示、不改落值** —— 展示层把它转成读得懂的一串
 * （块级标签 ⇒ 分段、实体解码、其余标签剥掉、连续空行收敛）；
 * 反向守卫 = `buildProductPrefill` 落给表单的 `description` 仍是**原始 HTML**（判据 5）。
 */
import { describe, expect, it } from 'vitest'
import { htmlToPlainText } from '@/lib/rich-text-plain'
import { buildProductPrefill } from '@/lib/image-recognize'

describe('富文本 → 可读纯文本（issue #6403 缺陷 2）', () => {
  it('判据 3a：块级标签 ⇒ 分段，且**不残留** < >', () => {
    const out = htmlToPlainText(
      '<p>常青藤系列纯色遮光窗帘，18 款</p><p>色号包含：2699-01</p>',
    )

    expect(out).not.toMatch(/[<>]/)
    expect(out.split('\n').filter((line) => line.trim() !== '')).toEqual([
      '常青藤系列纯色遮光窗帘，18 款',
      '色号包含：2699-01',
    ])
  })

  it('判据 3b：实体解码（命名 + 数字）', () => {
    expect(htmlToPlainText('<p>A &amp; B</p>')).toBe('A & B')
    expect(htmlToPlainText('&#39;米白&#39;')).toBe("'米白'")
    expect(htmlToPlainText('&lt;p&gt;不是标签&lt;/p&gt;')).toBe('<p>不是标签</p>')
  })

  it('判据 3c：纯文本入参**原样**返回', () => {
    expect(htmlToPlainText('常青藤系列纯色遮光窗帘')).toBe('常青藤系列纯色遮光窗帘')
    expect(htmlToPlainText('A & B')).toBe('A & B')
  })

  it('判据 3d：其余标签剥掉、连续空行收敛', () => {
    expect(
      htmlToPlainText('<div><span style="color:red">红</span></div>\n\n\n<p>蓝</p>'),
    ).toBe('红\n\n蓝')
    expect(htmlToPlainText('<p>a</p><!-- 注释 --><p>b</p>')).toBe('a\n\nb')
  })

  it('判据 3e：空值 / null / undefined 安全（不抛）', () => {
    expect(htmlToPlainText('')).toBe('')
    expect(htmlToPlainText(null)).toBe('')
    expect(htmlToPlainText(undefined)).toBe('')
  })
})

describe('落值口径未变（issue #6403 缺陷 2 的反向守卫）', () => {
  it('判据 5：buildProductPrefill 落给表单的 description 仍是**原始 HTML**', () => {
    const html = '<p>常青藤系列纯色遮光窗帘</p><p>色号包含：2699-01</p>'
    const { initialData } = buildProductPrefill([
      { key: 'description', label: '商品描述', value: html, source: '[米宝解读]', reason: null },
    ])

    expect(initialData.description).toBe(html)
  })
})
