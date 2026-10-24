// case_ids: PR-053
/**
 * 营销海报版面（issue #7351）—— 纯函数判据
 *
 * 钉住四类**会红**的形态：
 * 1. 版面尺寸固定 750×1000（下载/长按保存得到的就是这个尺寸）；
 * 2. 文案只来自 `copy`，缺价不伪装成 ¥0.00（「价格面议」）；缺图由绘制层降级；
 * 3. 换行/截断有界（标题 ≤2 行、商品名 ≤2 行、卖点 ≤3 行，超出省略号）；
 * 4. `posterViewFromCard` 对残缺载荷给安全默认，不抛错。
 */
import { describe, it, expect } from 'vitest'
import {
  POSTER_HEIGHT,
  POSTER_WIDTH,
  estimateTextWidth,
  layoutMarketingPoster,
  posterPriceText,
  posterViewFromCard,
  truncateLine,
  wrapText,
} from '@/lib/marketing-poster-layout'

const VIEW = {
  product: {
    name: '高遮光雪尼尔窗帘',
    price: 299,
    unit: '米',
    image: 'https://img.example.com/1.jpg',
    specs: ['遮光率：95%', '材质：雪尼尔'],
  },
  copy: { title: '新品上市', selling_points: ['高遮光', '免烫易打理', '整窗定制'] },
}

describe('layoutMarketingPoster', () => {
  it('固定 750×1000 版面，所有绘画操作都在画布内', () => {
    const layout = layoutMarketingPoster(VIEW)
    expect(layout.width).toBe(POSTER_WIDTH)
    expect(layout.height).toBe(POSTER_HEIGHT)
    expect(POSTER_WIDTH).toBe(750)
    expect(POSTER_HEIGHT).toBe(1000)
    expect(layout.imageRect).toEqual({ x: 40, y: 250, w: 670, h: 360 })

    for (const op of layout.ops) {
      if (op.kind === 'rect') {
        expect(op.x).toBeGreaterThanOrEqual(0)
        expect(op.y).toBeGreaterThanOrEqual(0)
        expect(op.x + op.w).toBeLessThanOrEqual(POSTER_WIDTH)
        expect(op.y + op.h).toBeLessThanOrEqual(POSTER_HEIGHT)
      } else {
        expect(op.y).toBeGreaterThanOrEqual(0)
        expect(op.y + op.fontPx).toBeLessThanOrEqual(POSTER_HEIGHT)
      }
    }
  })

  it('主标题 / 商品名 / 价格 / 卖点 / 规格逐条上版面（文案来自 copy，不自动生成）', () => {
    const layout = layoutMarketingPoster(VIEW)
    const texts = layout.ops.filter((op) => op.kind === 'text').map((op) => op.text)
    expect(texts).toContain('新品上市')
    expect(texts).toContain('高遮光雪尼尔窗帘')
    expect(texts).toContain('¥299')
    expect(texts).toContain('/米')
    expect(texts).toContain('高遮光')
    expect(texts).toContain('免烫易打理')
    expect(texts).toContain('整窗定制')
    expect(texts).toContain('遮光率：95% · 材质：雪尼尔')
    expect(layout.truncated).toBe(false)
  })

  it('卖点最多 3 条（第 4 条起不上版面）', () => {
    const layout = layoutMarketingPoster({
      ...VIEW,
      copy: { ...VIEW.copy, selling_points: ['一', '二', '三', '四'] },
    })
    const texts = layout.ops.filter((op) => op.kind === 'text').map((op) => op.text)
    expect(texts).toContain('三')
    expect(texts).not.toContain('四')
  })

  it('缺价显示「价格面议」，不伪装成 ¥0.00（也不画单位）', () => {
    const layout = layoutMarketingPoster({
      ...VIEW,
      product: { ...VIEW.product, price: null },
    })
    const texts = layout.ops.filter((op) => op.kind === 'text').map((op) => op.text)
    expect(texts).toContain('价格面议')
    expect(texts.some((t) => t.startsWith('¥'))).toBe(false)
    expect(texts).not.toContain('/米')
  })

  it('超长标题被截断成 ≤2 行并标记 truncated', () => {
    const layout = layoutMarketingPoster({
      ...VIEW,
      copy: { ...VIEW.copy, title: '超'.repeat(60) },
    })
    const titleOps = layout.ops.filter(
      (op) => op.kind === 'text' && op.fontPx === 46 && op.text.includes('超'),
    )
    expect(titleOps.length).toBeLessThanOrEqual(2)
    expect(layout.truncated).toBe(true)
  })
})

describe('posterPriceText', () => {
  it('整数价 / 两位小数 / 非法值', () => {
    expect(posterPriceText(299)).toBe('¥299')
    expect(posterPriceText('299.5')).toBe('¥299.50')
    expect(posterPriceText(null)).toBe('价格面议')
    expect(posterPriceText('abc')).toBe('价格面议')
  })
})

describe('wrapText / truncateLine / estimateTextWidth', () => {
  it('CJK 宽于 ASCII（量级判据）', () => {
    expect(estimateTextWidth('窗帘', 10)).toBeGreaterThan(estimateTextWidth('ab', 10))
  })

  it('换行不超过 maxLines，超出用省略号', () => {
    const result = wrapText('一二三四五六七八九十', 10, 30, 2)
    expect(result.lines.length).toBeLessThanOrEqual(2)
    expect(result.truncated).toBe(true)
    expect(result.lines[result.lines.length - 1].endsWith('…')).toBe(true)
  })

  it('单行截断保留省略号且不超宽', () => {
    const line = truncateLine('一二三四五六七八九十', 10, 30)
    expect(line.endsWith('…')).toBe(true)
    expect(estimateTextWidth(line, 10)).toBeLessThanOrEqual(30)
  })
})

describe('posterViewFromCard（残缺载荷安全默认）', () => {
  it('空载荷不抛错：商品名/单位/价格有安全默认', () => {
    const view = posterViewFromCard({})
    expect(view.product.name).toBe('未命名商品')
    expect(view.product.unit).toBe('件')
    expect(view.product.price).toBeNull()
    expect(view.product.image).toBeNull()
    expect(view.copy.title).toBe('')
    expect(view.copy.selling_points).toEqual([])
  })

  it('过滤空卖点 / 非法规格', () => {
    const view = posterViewFromCard({
      product: { name: ' 窗帘 ', price: '199', unit: ' ', specs: ['材质：棉', '', 3] },
      copy: { title: ' 开门红 ', selling_points: [' 高遮光 ', '', null] },
    })
    expect(view.product.name).toBe('窗帘')
    expect(view.product.unit).toBe('件')
    expect(view.product.specs).toEqual(['材质：棉'])
    expect(view.copy.title).toBe('开门红')
    expect(view.copy.selling_points).toEqual(['高遮光'])
  })
})
