/**
 * 收款码图片的**裁白边**（issue #7536）—— 在**上传时**裁，纸面直接用裁好的图。
 *
 * 用户 2026-10-23 逐字：「我上传的二维码周围有白色区域，在报价单上不要展示白色区域，
 * 只把二维码展示上去」；同日追加裁定：「直接改成上传时裁」。
 * 纸面把整图塞进 22mm 见方的框 ⇒ 图里的白边被一起印上，二维码只剩中间一小块。
 *
 * ## 为什么在上传时裁（而不是每次渲染时裁）
 *
 * 渲染时裁要先把 OSS 上的图读进 canvas —— **跨域**（未开 CORS）会让画布被污染、读不到像素，
 * 那种情况下只能退回原图 ⇒ 同一张图在别人机器上有没有白边**不可预期**。
 * 上传时裁的输入是**用户本地文件**（`File`），没有跨域问题，裁一次、此后所有纸面都干净，
 * 也不再让每次打印都做一遍像素扫描。
 *
 * ## 口径（三条）
 *
 * 1. **裁到内容外接框**：亮度 ≥ 245 且不透明的像素视为背景，取其余像素的包围盒
 *    （抗锯齿边缘自然落在框内，不额外留白 —— 纸本身是白的，阅读器需要的静区由纸面提供）；
 * 2. **拿不到像素就退回原文件**：无 canvas（jsdom / 老浏览器）/ 解码失败 / 编码失败 ⇒
 *    返回**原始 `File`**（照旧能上传成功，纸面与修前一致）；上传**不因裁边失败而失败**；
 * 3. **没有白边 ⇒ 原样返回原文件**（外接框 = 整帧时不重编码，不白掉一次质量损失）。
 *
 * ⚠️ **存量图不会自动变干净**：本口径只作用于**新上传**的图；已经上传的带白边图需要
 * 在「企业基础设置 → 收款码」**重新上传一次**（界面文案已提示，见 `settings/page.tsx`）。
 *
 * 纯函数 `contentBoxRgba` 单独导出：判断「裁得对不对」不需要真起 canvas
 * （判据 = `frontend/admin-web/tests/unit/lib/qr-image.test.ts`）。
 */

/** 亮度阈值：≥ 该值视为白底（0~255；二维码模块是深色，抗锯齿边 ≤ 240） */
export const QR_CONTENT_LUMINANCE = 245

/** 内容外接框（像素坐标，左上原点） */
export interface QrPixelBox {
  x: number
  y: number
  width: number
  height: number
}

/**
 * 从 RGBA 像素里取「非白内容」的外接框。
 *
 * @param data `ImageData.data`（RGBA，长度 = width × height × 4）
 * @returns 外接框；全白 / 全透明 / 尺寸非法 ⇒ `null`（调用方据此保留原图）
 */
export function contentBoxRgba(
  data: Uint8ClampedArray | number[],
  width: number,
  height: number,
  threshold: number = QR_CONTENT_LUMINANCE
): QrPixelBox | null {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null
  if (data.length < width * height * 4) return null

  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4
      const alpha = data[i + 3]
      if (alpha === 0) continue // 透明像素不是内容
      // 亮度用感知公式（与眼睛的权重一致）：白底上任何一种深色模块都能被认出来
      const luminance = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]
      if (luminance >= threshold) continue
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    }
  }

  if (maxX < 0 || maxY < 0) return null
  return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 }
}

/** 从本地文件载入图片（上传前裁边：本地文件没有跨域问题） */
function loadImageFromFile(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    const cleanup = () => URL.revokeObjectURL(url)
    // 上限 3s：超大图解码卡住时**不许**把上传流程挂死（超时 ⇒ 原文件照传）
    const timer = setTimeout(() => {
      cleanup()
      reject(new Error('qr image decode timeout'))
    }, 3000)
    img.onload = () => {
      clearTimeout(timer)
      cleanup()
      resolve(img)
    }
    img.onerror = () => {
      clearTimeout(timer)
      cleanup()
      reject(new Error('qr image decode failed'))
    }
    img.src = url
  })
}

/** canvas → PNG Blob（浏览器 API；jsdom / 老浏览器没有 toBlob ⇒ 抛，由外层退回原文件） */
function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    if (typeof canvas.toBlob !== 'function') {
      reject(new Error('canvas.toBlob unavailable'))
      return
    }
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('canvas.toBlob returned null'))
    }, 'image/png')
  })
}

/**
 * **上传前**把收款码图裁到二维码本体：`File` ⇒ 裁好的 `File`（PNG）。
 *
 * 🔴 **任何失败都返回原文件**（读不到像素 / 无 canvas / 解码或编码失败 / 全白 / 无白边）——
 * 上传流程「宁可有白边，也不许传不上去」。
 */
export async function trimWhiteMarginFile(file: File): Promise<File> {
  if (!file || typeof document === 'undefined') return file
  try {
    const img = await loadImageFromFile(file)
    const width = img.naturalWidth
    const height = img.naturalHeight
    if (width <= 0 || height <= 0) return file

    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(img, 0, 0)

    const { data } = ctx.getImageData(0, 0, width, height)
    const box = contentBoxRgba(data, width, height)
    if (!box) return file
    // 无白边：整帧即内容，不重编码（省一次质量损失）
    if (box.width >= width && box.height >= height) return file

    const out = document.createElement('canvas')
    out.width = box.width
    out.height = box.height
    const outCtx = out.getContext('2d')
    if (!outCtx) return file
    outCtx.drawImage(canvas, box.x, box.y, box.width, box.height, 0, 0, box.width, box.height)

    const blob = await canvasToBlob(out)
    const baseName = file.name.replace(/\.[^.]+$/, '') || 'payment-qrcode'
    return new File([blob], `${baseName}.png`, { type: 'image/png' })
  } catch {
    return file
  }
}
