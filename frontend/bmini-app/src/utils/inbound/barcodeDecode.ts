/**
 * **解码优先**：照片里的二维码/条码在**设备侧**先解一次（issue #5052 P3；设计 §6.1）
 *
 * ## 为什么这是成本守卫，而不是优化
 *
 * 照片里含可解条码时走 vision = **白烧一次 LLM 调用**（设计 §11.1 第 7 条判据）。所以顺序是硬的：
 * **先解码，解出来就不问模型**。服务端也按同一顺序判（`WorkerInboundService.recognize`：
 * `barcode` 非空 ⇒ `PATH_BARCODE`，**一次 LLM 都不调**）—— 端侧这一半的职责是
 * **把解出来的原文带上**（不带 = 服务端只能走 vision，钱就花了）。
 *
 * ## 两侧都要给得出路径（设计 §6.1 的「已知缺口」）
 *
 * | 平台 | 取像素 | 解码 | 状态 |
 * |---|---|---|---|
 * | h5（唯一上线形态） | `<img>` + canvas `getImageData` | `jsQR` | ✅ 已实测（本机 jest 用替身判据） |
 * | weapp（小程序链路**已搁置**） | `Taro.createOffscreenCanvas`（**h5 里是 `temporarilyNotSupport` 的 stub**） | 同 `jsQR` | ⚠️ **取不到 ⇒ 返回 null**，等价于「解码失败」⇒ 回落到服务端 vision（**不静默失败**：页面上写明本次走了 vision 路径） |
 *
 * ⚠️ **未实测项**（照实登记，不编造）：weapp 的离屏画布解码**本机无小程序运行时 ⇒ 未实测**。
 * 它的失败方向是**安全的**：取不到像素 ⇒ `null` ⇒ 走服务端 vision 兜底（多花一次 LLM，
 * 但不会给工人一个错的 SKU）。重启条件：拿到微信开发者工具 / 真机后跑一次
 * `decodeBarcodeFromPhoto` 并断言 `source === 'weapp-offscreen'`。
 */
import Taro from '@tarojs/taro'
import jsQR from 'jsqr'
import { isH5 } from '../platform'
import type { RasterImageLike } from './labelCanvas'

/** 解码来源（页面据此显示「本次走了哪条路」——不静默） */
export type DecodeSource = 'h5-dom-canvas' | 'weapp-offscreen'

/**
 * 小程序端**取不到像素**时给工人的话（文案在**调用点**，台账只登记它 —— 见 `./gaps`）。
 * 「登记而不接线」的机械形态就是：文案写在一个从没被渲染过的地方。
 */
export const WEAPP_DECODE_UNAVAILABLE_HINT =
  '小程序端暂不能在本机解码照片（Taro.createOffscreenCanvas 这条能力未实测），已改用服务端识别。'

export interface DecodeOutcome {
  /** 条码/二维码原文（`null` = 没解出来 ⇒ 交给服务端 vision 兜底） */
  text: string | null
  /** 走的是哪条取像素路径（`null` = 连像素都没取到） */
  source: DecodeSource | null
  /** 给操作者看的一句话（取不到像素时必须说清，**不许静默**） */
  hint: string
}

/** 纯解码：像素 → 文本（`jsQR`；无 DOM 依赖，可在 jest 里直接跑） */
export function decodeQrFromImageData(image: RasterImageLike): string | null {
  if (!image || !image.data || !image.width || !image.height) return null
  const data = image.data instanceof Uint8ClampedArray ? image.data : Uint8ClampedArray.from(image.data)
  try {
    const result = jsQR(data, image.width, image.height, { inversionAttempts: 'dontInvert' })
    const text = result?.data ? String(result.data).trim() : ''
    return text || null
  } catch {
    // 解码库抛错 = 这张图解不出来（不是本页故障）；交给服务端 vision 兜底
    return null
  }
}

/** h5：`File`/`Blob`/blob URL ⇒ 像素（`<img>` + canvas；**不做缩放**，按原始像素解） */
export async function loadPixelsFromFileH5(src: Blob | string): Promise<RasterImageLike | null> {
  if (typeof document === 'undefined' || typeof Image === 'undefined') return null
  const url = typeof src === 'string' ? src : URL.createObjectURL(src)
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = () => reject(new Error('图片加载失败'))
      el.src = url
    })
    const width = image.naturalWidth || image.width
    const height = image.naturalHeight || image.height
    if (!width || !height) return null
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(image as any, 0, 0)
    const pixels = ctx.getImageData(0, 0, width, height)
    return { data: pixels.data, width, height }
  } catch {
    return null
  } finally {
    if (typeof src !== 'string' && typeof URL !== 'undefined' && URL.revokeObjectURL) {
      URL.revokeObjectURL(url)
    }
  }
}

/**
 * weapp：临时文件路径 ⇒ 像素（`Taro.createOffscreenCanvas`）。
 * ⚠️ h5 下该 API 是 `temporarilyNotSupport` 的 stub（已登记进 `H5_API_OUTLET_LEDGER`），
 * 故本函数**只在非 h5** 分支被调用；取不到就返回 `null`（**不抛**：抛会把「小程序端解不了码」
 * 变成一次崩溃，而正确行为是回落到服务端 vision）。
 */
export async function loadPixelsFromPathWeapp(filePath: string): Promise<RasterImageLike | null> {
  if (isH5()) return null
  try {
    // ⚠️ 逐字写 `Taro.createOffscreenCanvas`（**不**用 `(Taro as any).xxx` 之类绕过写法）：
    // 全仓的 h5 平台守卫按 `Taro.<api>` 的文本形态扫用法，写成变量别名会让这处调用**从射程里消失**
    // ⇒ 缺口就"登记了却没人接线"（正是本单要防的形态）。类型上 Taro 4.2.1 自带该 API 声明。
    if (typeof Taro.createOffscreenCanvas !== 'function') return null
    const canvas: any = Taro.createOffscreenCanvas({ type: '2d', width: 1, height: 1 })
    const image = canvas.createImage()
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error('图片加载失败'))
      image.src = filePath
    })
    const width = image.width || canvas.width
    const height = image.height || canvas.height
    if (!width || !height) return null
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(image, 0, 0, width, height)
    const pixels = ctx.getImageData(0, 0, width, height)
    return { data: pixels.data, width, height }
  } catch {
    return null
  }
}

/** 一张待解码的照片（两端的形态不同：h5 是本地文件，weapp 是临时路径） */
export interface PendingPhoto {
  /** h5：`File`/`Blob`（或 blob URL 字符串）；weapp：临时文件路径 */
  file?: Blob | string | null
  /** weapp 的临时文件路径（`Taro.chooseImage` 的 `tempFilePaths[]`） */
  tempFilePath?: string | null
}

/**
 * 解一张照片。**取不到像素 ⇒ 明确说出原因**（不是静默返回 null 让上层猜）。
 */
export async function decodeBarcodeFromPhoto(photo: PendingPhoto): Promise<DecodeOutcome> {
  if (isH5()) {
    const src = photo.file ?? photo.tempFilePath ?? null
    const pixels = src ? await loadPixelsFromFileH5(src as Blob | string) : null
    if (!pixels) {
      return { text: null, source: null, hint: '这张照片读不出像素（可能不是图片），已改用服务端识别。' }
    }
    const text = decodeQrFromImageData(pixels)
    return { text, source: 'h5-dom-canvas', hint: text ? '' : '这张照片里没有可识别的二维码，已改用服务端识别。' }
  }
  const path = photo.tempFilePath ?? (typeof photo.file === 'string' ? photo.file : null)
  const pixels = path ? await loadPixelsFromPathWeapp(path) : null
  if (!pixels) {
    return {
      text: null,
      source: null,
      hint: WEAPP_DECODE_UNAVAILABLE_HINT,
    }
  }
  const text = decodeQrFromImageData(pixels)
  return { text, source: 'weapp-offscreen', hint: text ? '' : '照片里没有可识别的二维码，已改用服务端识别。' }
}
