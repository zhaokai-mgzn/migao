// 营销海报绘制层（issue #7351）—— **薄到只剩「按版面 ops 填字/画块」**。
//
// 版面判断全部在 `./marketing-poster-layout`（纯函数、可在 jsdom 里穷举）；
// 本文件只负责把 ops 画到 canvas 并导出 PNG。依赖通过参数注入
// （`createCanvas` / `loadImage`）⇒ 单测用替身即可，不需要真 canvas。
//
// 🔴 商品主图跨域：先带 `crossOrigin=anonymous` 载入（可导出）；失败退化为无图海报
// （`hadImage=false`），**不静默返回白图**。若浏览器已污染画布导致 toDataURL 抛错，
// 自动重绘一次无图版面再导出（降级可见：商品名/价格/文案仍完整）。

import {
  layoutMarketingPoster,
  type MarketingPosterView,
  type PosterLayout,
  type PosterOp,
} from './marketing-poster-layout'

/** 绘制层需要的最小 canvas 能力（`HTMLCanvasElement` 的结构子集） */
export interface PosterCanvasLike {
  width: number
  height: number
  getContext(type: '2d'): PosterContextLike | null
  toDataURL(type?: string, quality?: number): string
}

export interface PosterContextLike {
  fillStyle: string
  font: string
  textBaseline: string
  textAlign: string
  fillRect(x: number, y: number, w: number, h: number): void
  fillText(text: string, x: number, y: number): void
  drawImage(image: unknown, sx: number, sy: number, sw: number, sh: number, dx: number, dy: number, dw: number, dh: number): void
}

export interface PosterImageLike {
  width?: number
  height?: number
  naturalWidth?: number
  naturalHeight?: number
}

export interface PosterRenderDeps {
  createCanvas: (width: number, height: number) => PosterCanvasLike
  loadImage: (url: string) => Promise<PosterImageLike | null>
}

export interface RenderedPoster {
  dataUrl: string
  width: number
  height: number
  /** 商品主图是否真的画进去了（false = 降级为无图海报） */
  hadImage: boolean
}

const FONT_FAMILY = '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif'

function paint(ctx: PosterContextLike, layout: PosterLayout, image: PosterImageLike | null): void {
  ctx.textBaseline = 'top'
  for (const op of layout.ops) {
    if (op.kind === 'rect') {
      ctx.fillStyle = op.color
      ctx.fillRect(op.x, op.y, op.w, op.h)
      continue
    }
    paintText(ctx, op)
  }

  if (image) {
    const iw = Number(image.naturalWidth || image.width || 0)
    const ih = Number(image.naturalHeight || image.height || 0)
    if (iw > 0 && ih > 0) {
      const { x, y, w, h } = layout.imageRect
      const scale = Math.max(w / iw, h / ih)
      const sw = w / scale
      const sh = h / scale
      const sx = (iw - sw) / 2
      const sy = (ih - sh) / 2
      ctx.drawImage(image, sx, sy, sw, sh, x, y, w, h)
    }
  }
}

function paintText(ctx: PosterContextLike, op: Extract<PosterOp, { kind: 'text' }>): void {
  ctx.fillStyle = op.color
  ctx.font = `${op.weight} ${op.fontPx}px ${FONT_FAMILY}`
  ctx.textAlign = op.align
  ctx.fillText(op.text, op.x, op.y)
}

/**
 * 渲染一张营销海报 ⇒ PNG data URL（750×1000）。
 *
 * @throws 用户可读的「海报生成失败，请重试」（技术细节只进 console）；连无图版面都导不出时原样抛出，
 *         由组件展示失败态（「海报生成失败，请重试」）。
 */
export async function renderMarketingPoster(
  view: MarketingPosterView,
  deps: PosterRenderDeps,
): Promise<RenderedPoster> {
  const layout = layoutMarketingPoster(view)
  const canvas = deps.createCanvas(layout.width, layout.height)
  canvas.width = layout.width
  canvas.height = layout.height
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    console.error('营销海报渲染失败：画布拿不到 2d 上下文')
    throw new Error('海报生成失败，请重试')
  }

  let image: PosterImageLike | null = null
  if (view.product.image) {
    try {
      image = await deps.loadImage(view.product.image)
    } catch {
      image = null
    }
  }

  paint(ctx, layout, image)

  try {
    return {
      dataUrl: canvas.toDataURL('image/png'),
      width: layout.width,
      height: layout.height,
      hadImage: image !== null,
    }
  } catch {
    // 跨域污染（商品图没有 CORS 头）⇒ 无图重绘一次再导出；仍失败则如实抛错。
    const clean = deps.createCanvas(layout.width, layout.height)
    clean.width = layout.width
    clean.height = layout.height
    const cleanCtx = clean.getContext('2d')
    if (!cleanCtx) {
      console.error('营销海报渲染失败：画布拿不到 2d 上下文')
      throw new Error('海报生成失败，请重试')
    }
    paint(cleanCtx, layout, null)
    return {
      dataUrl: clean.toDataURL('image/png'),
      width: layout.width,
      height: layout.height,
      hadImage: false,
    }
  }
}
