/**
 * 洗水码位图的**默认渲染器**（issue #6439）—— 把 `WashLabelInput[]` 变成可送印的 {@link PrintJob}[]。
 *
 * 这一层是**不纯的那一半**（真 canvas）：`layoutWashLabel` 算位置、`paintWashLabel` 照单画，
 * 本文件只负责「开画布 / 取 ImageData / 量字」。
 *
 * ⚠️ 边界（照实登记）：本仓 `admin-web` **没装 `canvas` 包** ⇒ jsdom 里跑不了真画布
 * ⇒ 本文件**不进单测**；被它调用的两个纯函数（版式 / 绘制）另有判据（`tests/unit/lib/label-print-wash-label.test.ts`），
 * 组件测试则注入 `renderJobs` 替身。**真机纸面效果**由真机验收覆盖。
 */
import type { PrintJob } from './lpapi'
import {
  layoutWashLabel,
  paintWashLabel,
  resolveLabelGeometry,
  type LabelPrinterInfoLike,
  type TextMeasure,
  type WashLabelInput,
} from './wash-label'

/** 用真 canvas 的量字（与 `paintWashLabel` 的字号口径一致：fontPx 即 CSS px） */
export function canvasTextMeasure(ctx: CanvasRenderingContext2D): TextMeasure {
  return (text, fontPx) => {
    ctx.font = `bold ${fontPx}px ui-monospace, SFMono-Regular, Menlo, monospace`
    return ctx.measureText(text).width
  }
}

/**
 * 渲染成位图任务（**一张洗水码一个 job**）。
 *
 * @param qrSources 与 `labels` **同序**的二维码位图（页面从隐藏的 `QRCodeCanvas` 取；缺位 ⇒ `null`，不画假码）
 * @param printerInfo 机器自报参数（决定画布几何 —— 不写死机型）
 */
export async function renderWashLabelJobs(
  labels: WashLabelInput[],
  qrSources: Array<CanvasImageSource | null>,
  printerInfo?: LabelPrinterInfoLike | null,
): Promise<PrintJob[]> {
  const geometry = resolveLabelGeometry(printerInfo)
  const jobs: PrintJob[] = []

  for (let index = 0; index < labels.length; index += 1) {
    const canvas = document.createElement('canvas')
    canvas.width = geometry.widthPx
    canvas.height = geometry.heightPx
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('浏览器没有提供 canvas 2d 上下文')

    const layout = layoutWashLabel(labels[index], geometry, canvasTextMeasure(ctx))
    paintWashLabel(ctx, layout, qrSources[index] ?? null)

    jobs.push({
      imageData: ctx.getImageData(0, 0, geometry.widthPx, geometry.heightPx),
      widthPx: geometry.widthPx,
      heightPx: geometry.heightPx,
      jobName: `wash-label-${index}`,
    })
  }

  return jobs
}
