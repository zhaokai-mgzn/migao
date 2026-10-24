// case_ids: UI-135
// @vitest-environment jsdom

import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'

import { contentBoxRgba, trimWhiteMarginFile, QR_CONTENT_LUMINANCE } from '@/lib/qr-image'

/**
 * 收款码**裁白边**（issue #7536）—— 用户 2026-10-23 逐字「我上传的二维码周围有白色区域，
 * 在报价单上不要展示白色区域，只把二维码展示上去」，随后裁定 **「直接改成上传时裁」**。
 *
 * 判据分两层：
 * - **算法层**（`contentBoxRgba`，纯函数）：白底 + 深色模块 ⇒ 外接框恰好是模块那一块；
 *   四边留白各不相同也必须裁对（上传图的白边往往不对称）；
 * - **失败层**（`trimWhiteMarginFile`，**上传前**跑）：拿不到像素（无 canvas / 解码失败 / 超时 /
 *   编码失败）**一律退回原文件** —— 上传「宁可有白边，也不许传不上去」。
 */

/** 造一块 100×100 的 RGBA 白底，在 `box` 处画深色方块 */
function rgbaWithBox(
  box: { x: number; y: number; width: number; height: number } | null,
  size = 100
): Uint8ClampedArray {
  const data = new Uint8ClampedArray(size * size * 4).fill(255)
  if (!box) return data
  for (let y = box.y; y < box.y + box.height; y += 1) {
    for (let x = box.x; x < box.x + box.width; x += 1) {
      const i = (y * size + x) * 4
      data[i] = 20
      data[i + 1] = 20
      data[i + 2] = 20
      data[i + 3] = 255
    }
  }
  return data
}

const BOX = { x: 31, y: 17, width: 40, height: 55 }

let restoreCanvas: (() => void) | null = null

/** 让 jsdom 的 canvas 可用：getContext 直接返回合成像素，toDataURL 记下输出尺寸 */
function stubCanvas(pixels: Uint8ClampedArray) {
  const outSizes: Array<{ width: number; height: number }> = []
  const realGetContext = HTMLCanvasElement.prototype.getContext
  const realToBlob = HTMLCanvasElement.prototype.toBlob
  HTMLCanvasElement.prototype.getContext = function getContext() {
    return {
      drawImage: () => undefined,
      getImageData: () => ({ data: pixels, width: 100, height: 100 }),
    } as unknown as CanvasRenderingContext2D
  } as unknown as typeof HTMLCanvasElement.prototype.getContext
  HTMLCanvasElement.prototype.toBlob = function toBlob(callback: BlobCallback) {
    outSizes.push({ width: this.width, height: this.height })
    callback(new Blob([`crop-${this.width}x${this.height}`], { type: 'image/png' }))
  }
  restoreCanvas = () => {
    HTMLCanvasElement.prototype.getContext = realGetContext
    HTMLCanvasElement.prototype.toBlob = realToBlob
  }
  return outSizes
}

/** 让 `new Image()` 立刻成功（`width`×`height`）或立刻失败 */
function stubImage(outcome: 'ok' | 'error') {
  class FakeImage {
    crossOrigin = ''
    naturalWidth = 100
    naturalHeight = 100
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    set src(_value: string) {
      queueMicrotask(() => (outcome === 'ok' ? this.onload?.() : this.onerror?.()))
    }
  }
  vi.stubGlobal('Image', FakeImage)
}

afterEach(() => {
  restoreCanvas?.()
  restoreCanvas = null
  vi.unstubAllGlobals()
})

describe('contentBoxRgba — 内容外接框（纯函数）', () => {
  it('① 白边裁到深色模块：四边留白各不相同也裁对', () => {
    expect(contentBoxRgba(rgbaWithBox(BOX), 100, 100)).toEqual(BOX)
  })

  it('② 抗锯齿灰边算内容（亮度 < 阈值即可，不是「纯黑才算」）', () => {
    const data = rgbaWithBox(null)
    // 在 (5,5) 放一个亮度 240 的灰点（< 245 阈值）⇒ 外接框从它开始
    const i = (5 * 100 + 5) * 4
    data[i] = 240
    data[i + 1] = 240
    data[i + 2] = 240
    expect(contentBoxRgba(data, 100, 100)).toEqual({ x: 5, y: 5, width: 1, height: 1 })
  })

  it('③ 无白边（整帧都是内容）⇒ 外接框 = 整帧', () => {
    expect(contentBoxRgba(rgbaWithBox({ x: 0, y: 0, width: 100, height: 100 }), 100, 100)).toEqual({
      x: 0,
      y: 0,
      width: 100,
      height: 100,
    })
  })

  it('④ 全白 / 全透明 ⇒ null（调用方保留原图）', () => {
    expect(contentBoxRgba(rgbaWithBox(null), 100, 100)).toBeNull()
    const transparent = new Uint8ClampedArray(100 * 100 * 4) // alpha 全 0
    expect(contentBoxRgba(transparent, 100, 100)).toBeNull()
  })

  it('⑤ 尺寸非法 / 像素不足 ⇒ null（不抛）', () => {
    expect(contentBoxRgba(new Uint8ClampedArray(4), 0, 0)).toBeNull()
    expect(contentBoxRgba(new Uint8ClampedArray(16), 100, 100)).toBeNull()
  })

  it('⑥ 阈值语义 = 「亮度 ≥ 阈值即背景」：调低阈值可以把浅灰底也当白底', () => {
    const data = rgbaWithBox(BOX)
    // 整帧铺一层亮度 200 的浅灰底（真实上传图常见：白底被手机拍成浅灰）
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] === 255) {
        data[i] = 200
        data[i + 1] = 200
        data[i + 2] = 200
      }
      data[i + 3] = 255
    }
    expect(QR_CONTENT_LUMINANCE).toBe(245)
    // 默认阈值 245：浅灰底 200 < 245 ⇒ 算内容（框 = 整帧）
    expect(contentBoxRgba(data, 100, 100)).toEqual({ x: 0, y: 0, width: 100, height: 100 })
    // 阈值降到 180：浅灰底 ≥ 180 ⇒ 背景，只剩深色模块
    expect(contentBoxRgba(data, 100, 100, 180)).toEqual(BOX)
  })
})

const makeFile = (name = 'qr.png') => new File(['original-bytes'], name, { type: 'image/png' })

describe('trimWhiteMarginFile — 上传前裁边（失败一律退回原文件）', () => {
  beforeEach(() => {
    // jsdom 没有 URL.createObjectURL（Node 20 起有 URL 但没有它）
    vi.stubGlobal('URL', Object.assign(URL, {
      createObjectURL: () => 'blob:mock',
      revokeObjectURL: () => undefined,
    }))
  })

  it('⑦ 有白边 ⇒ 输出裁好的 PNG File（尺寸 = 内容框，文件名改 .png）', async () => {
    const outSizes = stubCanvas(rgbaWithBox(BOX))
    stubImage('ok')
    const out = await trimWhiteMarginFile(makeFile('vx-qr.jpg'))
    expect(out.type).toBe('image/png')
    expect(out.name).toBe('vx-qr.png')
    expect(out.size).toBeGreaterThan(0)
    expect(outSizes).toEqual([{ width: 40, height: 55 }])
  })

  it('⑧ 无白边 ⇒ 原文件**同一个对象**（不重编码，省一次质量损失）', async () => {
    stubCanvas(rgbaWithBox({ x: 0, y: 0, width: 100, height: 100 }))
    stubImage('ok')
    const file = makeFile()
    await expect(trimWhiteMarginFile(file)).resolves.toBe(file)
  })

  it('⑨ 全白图 ⇒ 原文件（不裁成 0×0，更不传一张空图上去）', async () => {
    stubCanvas(rgbaWithBox(null))
    stubImage('ok')
    const file = makeFile()
    await expect(trimWhiteMarginFile(file)).resolves.toBe(file)
  })

  it('⑩ 拿不到 canvas（jsdom / 老浏览器）⇒ 原文件', async () => {
    stubImage('ok')
    // 不 stub canvas：jsdom 的 getContext 返回 null
    const file = makeFile()
    await expect(trimWhiteMarginFile(file)).resolves.toBe(file)
  })

  it('⑪ 图片解码失败（文件损坏 / 非图片）⇒ 原文件', async () => {
    stubImage('error')
    const file = makeFile()
    await expect(trimWhiteMarginFile(file)).resolves.toBe(file)
  })

  it('⑫ 空入参 ⇒ 原样返回（调用方据此照常上传/跳过）', async () => {
    const file = makeFile()
    await expect(trimWhiteMarginFile(file)).resolves.toBe(file)
    await expect(trimWhiteMarginFile(undefined as unknown as File)).resolves.toBeUndefined()
  })
})
