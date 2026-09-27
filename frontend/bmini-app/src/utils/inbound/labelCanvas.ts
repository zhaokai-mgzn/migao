/**
 * 把标签**绘制计划**画到 canvas（issue #5052 P3）
 *
 * 这一层薄到只剩「按计划填方块 / 写文字」——所有**版面判断**（截断可见、缺码不画码、整数倍点阵）
 * 都在 `./labelLayout` 里，故本文件不需要重复一套版面判据。
 *
 * 🔴 **1:1 不缩放不裁切**（设计 §7.2 / N9）：画布尺寸 = 计划尺寸，绘制**不做任何 transform**。
 * 缩放会把二维码糊掉（扫不出来），裁切会把短码切掉（降级入口没了）——两者都不会报错。
 *
 * 依赖注入：本模块只认一个**窄接口** `LabelCanvasContextLike`（`CanvasRenderingContext2D` 的结构子集），
 * 于是判据可以在没有 canvas 的 jest/jsdom 里跑（真 `getContext('2d')` 在 jsdom 里返回 `null`）。
 */
import { layoutInboundLabel, type InboundLabelPlan, type InboundLabelView } from './labelLayout'

const BACKGROUND = '#ffffff'
const INK = '#000000'

/** 送打印机/绘制共用的位图（`ImageData` 的结构子集） */
export interface RasterImageLike {
  data: Uint8ClampedArray | number[]
  width: number
  height: number
}

/** 需要的最小 canvas 能力（`CanvasRenderingContext2D` 的结构子集；测试用假实现） */
export interface LabelCanvasContextLike {
  fillStyle: string
  font: string
  textBaseline: string
  fillRect(x: number, y: number, w: number, h: number): void
  fillText(text: string, x: number, y: number): void
  /** 取位图（送打印用）；假实现可返回同尺寸的空白位图 */
  getImageData?(x: number, y: number, w: number, h: number): RasterImageLike
}

export interface LabelCanvasElementLike {
  width: number
  height: number
  getContext(type: '2d'): LabelCanvasContextLike | null
}

export interface RenderedLabel {
  plan: InboundLabelPlan
  canvas: LabelCanvasElementLike
  /** 送打印的位图（与画布 **1:1**；`1:1 不缩放` 的可判形态就是这两个数与计划相等） */
  image: RasterImageLike
  widthPx: number
  heightPx: number
}

/** 按计划绘制（调用方负责先把画布尺寸设成 `plan.widthPx × plan.heightPx`） */
export function paintInboundLabel(ctx: LabelCanvasContextLike, plan: InboundLabelPlan): void {
  ctx.fillStyle = BACKGROUND
  ctx.fillRect(0, 0, plan.widthPx, plan.heightPx)

  for (const op of plan.ops) {
    if (op.kind === 'rect') {
      ctx.fillStyle = op.color
      ctx.fillRect(op.x, op.y, op.w, op.h)
      continue
    }
    ctx.fillStyle = INK
    ctx.font = `${op.bold ? 'bold ' : ''}${op.fontPx}px sans-serif`
    ctx.textBaseline = 'top'
    ctx.fillText(op.text, op.x, op.y)
  }

  if (plan.qr) {
    ctx.fillStyle = INK
    for (let row = 0; row < plan.qr.moduleCount; row += 1) {
      for (let col = 0; col < plan.qr.moduleCount; col += 1) {
        if (plan.qr.matrix[row * plan.qr.moduleCount + col] !== 1) continue
        ctx.fillRect(
          plan.qr.x + col * plan.qr.cellPx,
          plan.qr.y + row * plan.qr.cellPx,
          plan.qr.cellPx,
          plan.qr.cellPx,
        )
      }
    }
  }
}

/**
 * 渲染一张标签 ⇒ 计划 + 位图。
 *
 * @param createCanvas 画布工厂（浏览器传 `document.createElement('canvas')`；测试传替身）
 * @throws 画布拿不到 2d 上下文 ⇒ 抛错（**不静默返回白图**：白图会被当成「打出来了」）
 */
export function renderInboundLabel(
  view: InboundLabelView,
  createCanvas: (widthPx: number, heightPx: number) => LabelCanvasElementLike,
): RenderedLabel {
  const plan = layoutInboundLabel(view)
  const canvas = createCanvas(plan.widthPx, plan.heightPx)
  canvas.width = plan.widthPx
  canvas.height = plan.heightPx
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('标签渲染失败：画布拿不到 2d 上下文（不静默返回空白标签）')
  paintInboundLabel(ctx, plan)
  const image = ctx.getImageData
    ? ctx.getImageData(0, 0, plan.widthPx, plan.heightPx)
    : { data: new Uint8ClampedArray(plan.widthPx * plan.heightPx * 4), width: plan.widthPx, height: plan.heightPx }
  return { plan, canvas, image, widthPx: plan.widthPx, heightPx: plan.heightPx }
}
