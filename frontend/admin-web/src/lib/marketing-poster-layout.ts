// 营销海报版面（issue #7351）—— **纯函数**：只算坐标与文字，不碰 canvas / DOM。
//
// 为什么单独一层：海报的「画出来对不对」在 CI 里没有真 canvas（jsdom 的
// `getContext('2d')` 返回 null），把版面判断（换行 / 截断 / 缺图降级 / 价格缺省）
// 收进纯函数后，判据可以逐条断言，绘制层薄到只剩「按 ops 填字/画块」。
// 同族先例 = `frontend/bmini-app/src/utils/inbound/labelLayout.ts|labelCanvas.ts`。
//
// 画布固定 750×1000（朋友圈/群的竖版比例 3:4），1:1 不缩放：下载/长按保存得到的就是
// 750×1000 的 PNG。

export const POSTER_WIDTH = 750
export const POSTER_HEIGHT = 1000

const PADDING = 40
const INK = '#0A2540'
const GOLD = '#C8A45C'
const MUTED = '#6B7280'
const PRICE_RED = '#C0392B'
const PAPER = '#F7F5F1'

export interface PosterProduct {
  name: string
  price: number | string | null
  unit: string
  image: string | null
  specs: string[]
}

export interface PosterCopy {
  title: string
  selling_points: string[]
}

export interface MarketingPosterView {
  product: PosterProduct
  copy: PosterCopy
}

export interface PosterTextOp {
  kind: 'text'
  text: string
  x: number
  y: number
  fontPx: number
  weight: 'normal' | 'bold'
  color: string
  align: 'left' | 'center'
}

export interface PosterRectOp {
  kind: 'rect'
  x: number
  y: number
  w: number
  h: number
  color: string
}

export type PosterOp = PosterTextOp | PosterRectOp

export interface PosterLayout {
  width: number
  height: number
  background: string
  /** 商品主图区域（绘制层按 cover 裁切填充；无图时画占位块） */
  imageRect: { x: number; y: number; w: number; h: number }
  ops: PosterOp[]
  /** 有任何文字被截断（用省略号收尾）—— 供测试/回归判断版面是否够用 */
  truncated: boolean
}

/** 从卡片载荷（服务端 tool data）安全解析出海报视图；缺字段一律给安全默认。 */
export function posterViewFromCard(data: Record<string, unknown>): MarketingPosterView {
  const product = (data?.product as Record<string, unknown>) || {}
  const copy = (data?.copy as Record<string, unknown>) || {}

  const specs = Array.isArray(product.specs)
    ? product.specs
        .filter((s): s is string => typeof s === 'string' && s.trim() !== '')
        .map((s) => s.trim())
    : []
  const points = Array.isArray(copy.selling_points)
    ? copy.selling_points
        .filter((s): s is string => typeof s === 'string' && s.trim() !== '')
        .map((s) => s.trim())
    : []

  const rawPrice = product.price
  const price =
    typeof rawPrice === 'number' || (typeof rawPrice === 'string' && rawPrice.trim() !== '')
      ? rawPrice
      : null

  return {
    product: {
      name: typeof product.name === 'string' && product.name.trim() ? product.name.trim() : '未命名商品',
      price,
      unit: typeof product.unit === 'string' && product.unit.trim() ? product.unit.trim() : '件',
      image: typeof product.image === 'string' && product.image.trim() ? product.image : null,
      specs,
    },
    copy: {
      title: typeof copy.title === 'string' && copy.title.trim() ? copy.title.trim() : '',
      selling_points: points,
    },
  }
}

/** 价格文案：数字 → `¥299` / `¥299.50`；缺价 → `价格面议`（**不伪装成 ¥0.00**）。 */
export function posterPriceText(price: number | string | null): string {
  if (price === null || price === undefined || price === '') return '价格面议'
  const n = typeof price === 'number' ? price : Number(price)
  if (!Number.isFinite(n)) return '价格面议'
  const rounded = Math.round(n * 100) / 100
  return `¥${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(2)}`
}

/** 文本宽度估算：CJK（含全角标点）按 1 em，ASCII 按 0.55 em（与 canvas 度量同量级）。 */
export function estimateTextWidth(text: string, fontPx: number): number {
  let em = 0
  for (const ch of text) {
    em += /[\u2E80-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/.test(ch) ? 1 : 0.55
  }
  return em * fontPx
}

/** 按宽度换行；`maxLines` 之后的文字用省略号收尾（返回 truncated 标记）。 */
export function wrapText(
  text: string,
  fontPx: number,
  maxWidth: number,
  maxLines: number,
): { lines: string[]; truncated: boolean } {
  const clean = (text || '').replace(/\s+/g, ' ').trim()
  if (!clean) return { lines: [], truncated: false }

  const lines: string[] = []
  let current = ''
  let truncated = false

  for (const ch of clean) {
    const next = current + ch
    if (estimateTextWidth(next, fontPx) > maxWidth && current) {
      lines.push(current)
      current = ch
      if (lines.length === maxLines) {
        truncated = true
        current = ''
        break
      }
    } else {
      current = next
    }
  }
  if (current && lines.length < maxLines) lines.push(current)
  if (lines.length === 0) return { lines: [], truncated: false }

  if (truncated || (lines.length === maxLines && current)) {
    const last = lines[lines.length - 1]
    let clipped = last
    while (clipped && estimateTextWidth(clipped + '…', fontPx) > maxWidth) {
      clipped = clipped.slice(0, -1)
    }
    lines[lines.length - 1] = clipped + '…'
    truncated = true
  }
  return { lines, truncated }
}

/** 单行截断（规格行 / 页脚等不允许换行的位置） */
export function truncateLine(text: string, fontPx: number, maxWidth: number): string {
  const clean = (text || '').replace(/\s+/g, ' ').trim()
  if (estimateTextWidth(clean, fontPx) <= maxWidth) return clean
  let clipped = clean
  while (clipped && estimateTextWidth(clipped + '…', fontPx) > maxWidth) {
    clipped = clipped.slice(0, -1)
  }
  return clipped + '…'
}

/**
 * 版面：750×1000，自上而下 = 品牌条 → 促销主标题 → 商品主图 → 商品名 →
 * 规格（一行，事实数据）→ 价格 → 卖点（≤3 行，操作员文案）→ 页脚。
 *
 * 所有营销文案都来自 `view.copy`，本函数**不生成/补全任何文案**；
 * 缺价显示「价格面议」，缺图由绘制层画占位块。
 */
export function layoutMarketingPoster(view: MarketingPosterView): PosterLayout {
  const ops: PosterOp[] = []
  let truncated = false

  // 纸底 + 顶部品牌条
  ops.push({ kind: 'rect', x: 0, y: 0, w: POSTER_WIDTH, h: POSTER_HEIGHT, color: PAPER })
  ops.push({ kind: 'rect', x: 0, y: 0, w: POSTER_WIDTH, h: 84, color: INK })
  ops.push({
    kind: 'text', text: '黄金策 · 商品海报', x: PADDING, y: 30, fontPx: 22,
    weight: 'bold', color: GOLD, align: 'left',
  })

  // 促销主标题（最多 2 行；纯文案来自操作员）
  const title = wrapText(view.copy.title, 46, POSTER_WIDTH - PADDING * 2, 2)
  truncated = truncated || title.truncated
  title.lines.forEach((line, i) => {
    ops.push({
      kind: 'text', text: line, x: POSTER_WIDTH / 2, y: 112 + i * 58,
      fontPx: 46, weight: 'bold', color: INK, align: 'center',
    })
  })

  // 商品主图
  const imageRect = { x: PADDING, y: 250, w: POSTER_WIDTH - PADDING * 2, h: 360 }
  ops.push({ kind: 'rect', x: imageRect.x, y: imageRect.y, w: imageRect.w, h: imageRect.h, color: '#E5E7EB' })

  // 商品名（最多 2 行）
  const name = wrapText(view.product.name, 34, POSTER_WIDTH - PADDING * 2, 2)
  truncated = truncated || name.truncated
  name.lines.forEach((line, i) => {
    ops.push({
      kind: 'text', text: line, x: PADDING, y: 636 + i * 44,
      fontPx: 34, weight: 'bold', color: INK, align: 'left',
    })
  })

  // 规格（一行事实；来自服务端商品数据）
  if (view.product.specs.length > 0) {
    const specText = truncateLine(view.product.specs.join(' · '), 20, POSTER_WIDTH - PADDING * 2)
    truncated = truncated || specText.endsWith('…')
    ops.push({
      kind: 'text', text: specText, x: PADDING, y: 730, fontPx: 20,
      weight: 'normal', color: MUTED, align: 'left',
    })
  }

  // 价格 + 单位
  const priceText = posterPriceText(view.product.price)
  ops.push({
    kind: 'text', text: priceText, x: PADDING, y: 768, fontPx: 56,
    weight: 'bold', color: priceText === '价格面议' ? MUTED : PRICE_RED, align: 'left',
  })
  if (priceText !== '价格面议') {
    ops.push({
      kind: 'text',
      text: `/${truncateLine(view.product.unit, 22, 120)}`,
      x: PADDING + estimateTextWidth(priceText, 56) + 6,
      y: 796, fontPx: 22, weight: 'normal', color: MUTED, align: 'left',
    })
  }

  // 卖点（≤3 行，操作员文案）
  view.copy.selling_points.slice(0, 3).forEach((point, i) => {
    const line = truncateLine(point, 24, POSTER_WIDTH - PADDING * 2 - 24)
    truncated = truncated || line.endsWith('…')
    ops.push({ kind: 'rect', x: PADDING + 2, y: 858 + i * 36 + 8, w: 8, h: 8, color: GOLD })
    ops.push({
      kind: 'text', text: line, x: PADDING + 24, y: 850 + i * 36,
      fontPx: 24, weight: 'normal', color: INK, align: 'left',
    })
  })

  // 页脚
  ops.push({ kind: 'rect', x: 0, y: 968, w: POSTER_WIDTH, h: 32, color: INK })
  ops.push({
    kind: 'text', text: '黄金策 · 智慧经营', x: PADDING, y: 974, fontPx: 18,
    weight: 'normal', color: '#E8D3A2', align: 'left',
  })

  return {
    width: POSTER_WIDTH,
    height: POSTER_HEIGHT,
    background: PAPER,
    imageRect,
    ops,
    truncated,
  }
}
