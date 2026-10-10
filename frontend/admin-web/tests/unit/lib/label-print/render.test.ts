// case_ids: PP-011
// @vitest-environment jsdom
//
// PP-011（issue #6439）：洗水码位图的**渲染调度层**（`frontend/admin-web/src/lib/label-print/render.ts`）。
//
// ## 为什么这一层**能**测（改判前一版的「本文件不进单测」）
//
// 本仓没装 `canvas` 包 ⇒ jsdom 的 `getContext('2d')` 返回 null，真像素画不出来。但这一层要的并不是像素，
// 而是**调度**：按几何开画布 → 量字 → 照单画 → 取 ImageData 组成 job。canvas 是**可打桩**的
// （`HTMLCanvasElement.prototype.getContext` 替身）⇒ 调度与几何都能钉住。
//
// ⚠️ 边界（照实登记）：**像素效果**（字糊不糊、码清不清）测不了 —— 那由真机纸面核对覆盖
// （见 `acceptance/2026-10-06-direct-label-print/README.md` 的未覆盖项）。
//
// 逐条判据（都能判红）：
// ① **N 张 ⇒ N 个 job**，且每个 job 的像素宽高 = `resolveLabelGeometry` 的几何（1:1 送点阵，不缩放）；
// ② 画布**真按几何开**（不是浏览器默认 300×150）—— 改回不设 width/height ⇒ 必红；
// ③ **位图与 labels 同序**：只有有码的那张 `drawImage`（无码不画假码）；
// ④ 机器自报换一台 ⇒ 画布跟着变（不写死机型）；
// ⑤ 拿不到 2d 上下文 ⇒ **抛错**（不静默交出一张空白纸去打印）；
// ⑥ `canvasTextMeasure` 与绘制同一套字号口径（bold + 等宽族）。
import { describe, expect, it, vi } from 'vitest'
import { canvasTextMeasure, renderWashLabelJobs } from '@/lib/label-print/render'
import { resolveLabelGeometry, type WashLabelInput } from '@/lib/label-print/wash-label'

const LABELS: WashLabelInput[] = [
  {
    qrValue: 'https://app.migaozn.com/s/7Q2M4K8P',
    shortCode: '7Q2M4K8P',
    processingOrderNo: 'JG-20260921-8237',
    rows: [
      { key: 'customer', text: '客户 赵凯', maxLines: 1 },
      { key: 'pieceName', text: '客厅窗帘A', maxLines: 2 },
    ],
  },
  // 该部位被撤销（无码）⇒ 这一张**不许** drawImage
  {
    qrValue: null,
    shortCode: 'ABCDEFGH',
    processingOrderNo: 'JG-20260921-8237',
    rows: [{ key: 'pieceName', text: '卧室窗帘', maxLines: 2 }],
  },
]

/**
 * 打桩 `getContext`：返回一个**记账的**假 2d 上下文，并记下每张画布被开出来的宽高。
 *
 * 用 `vi.spyOn` 顶掉原型方法 ⇒ jsdom 那句 `Not implemented: getContext` 也不会再刷屏。
 */
function installCanvasStub() {
  const calls: string[] = []
  const canvases: Array<{ width: number; height: number }> = []
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    font: '',
    lineWidth: 1,
    textAlign: 'left',
    textBaseline: 'alphabetic',
    fillRect: (x: number, y: number, w: number, h: number) => calls.push(`fillRect:${x},${y},${w},${h}`),
    strokeRect: () => calls.push('strokeRect'),
    setLineDash: () => calls.push('setLineDash'),
    fillText: (text: string) => calls.push(`fillText:${text}`),
    drawImage: () => calls.push('drawImage'),
    // 0.6em/字符的等宽近似：与纯函数判据里的量字替身同口径
    measureText: (text: string) => ({ width: text.length * 6 }),
    getImageData: (_x: number, _y: number, w: number, h: number) => ({
      width: w,
      height: h,
      data: new Uint8ClampedArray(4),
    }),
  }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) {
    canvases.push({ width: this.width, height: this.height })
    return ctx as unknown as CanvasRenderingContext2D
  })
  return { calls, canvases }
}

describe('renderWashLabelJobs — 调度与几何（issue #6439 判据 ③）', () => {
  it('N 张 ⇒ N 个 job；宽高 = 画布几何（1:1 送点阵，不缩放）', async () => {
    const { calls, canvases } = installCanvasStub()
    const printer = { printerDPI: 300, printerWidth: 576 }
    const jobs = await renderWashLabelJobs(LABELS, [null, null], printer)
    const geometry = resolveLabelGeometry(printer)

    expect(jobs).toHaveLength(2)
    expect(jobs[0]).toMatchObject({
      widthPx: geometry.widthPx,
      heightPx: geometry.heightPx,
      jobName: 'wash-label-0',
    })
    expect(jobs[1].jobName).toBe('wash-label-1')
    // 🔴 画布**真按几何开**（不是浏览器默认 300×150）—— 改回不设宽高 ⇒ 本条必红
    expect(canvases).toEqual([
      { width: geometry.widthPx, height: geometry.heightPx },
      { width: geometry.widthPx, height: geometry.heightPx },
    ])
    // 白底铺满两张（热敏纸：不铺白 = 打出黑底的反色废纸）
    expect(calls.filter((c) => c.startsWith('fillRect:')).length).toBe(2)
  })

  it('🔴 二维码位图**与 labels 同序**：只有有码的那张 drawImage（无码不画假码）', async () => {
    const { calls } = installCanvasStub()
    const qr = {} as unknown as CanvasImageSource

    // 位图给第 0 张（有码）、第 1 张给 null（无码）⇒ 恰好画 1 次
    await renderWashLabelJobs(LABELS, [qr, null], null)
    expect(calls.filter((c) => c === 'drawImage')).toHaveLength(1)

    // 反向对照：位图**给错张**（给到无码那张）⇒ 一次都不画 —— 版式侧本来就没有 qr 位
    calls.length = 0
    await renderWashLabelJobs(LABELS, [null, qr], null)
    expect(calls.filter((c) => c === 'drawImage')).toHaveLength(0)
  })

  it('机器自报换一台 ⇒ 画布跟着变（不写死机型）', async () => {
    const { canvases } = installCanvasStub()
    const printer = { printerDPI: 300, printerWidth: 576 }
    await renderWashLabelJobs(LABELS, [], printer)
    const geometry = resolveLabelGeometry(printer)
    expect(canvases.every((c) => c.width === geometry.widthPx)).toBe(true)
    // 与「未连上机器」的兜底口径**不同** ⇒ 证明取了自报值而不是常量
    expect(geometry.widthPx).not.toBe(resolveLabelGeometry(null).widthPx)
  })

  it('拿不到 2d 上下文 ⇒ **抛错**（不静默交出一张空白纸去打印）', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    await expect(renderWashLabelJobs(LABELS, [], null)).rejects.toThrow(/canvas/)
  })

  it('空输入 ⇒ 空数组（不造占位）', async () => {
    installCanvasStub()
    expect(await renderWashLabelJobs([], [], null)).toEqual([])
  })
})

describe('canvasTextMeasure — 与绘制同一套字号口径', () => {
  it('用 bold + 指定 px 量字，宽度取 `measureText` 的读数', () => {
    const ctx = {
      font: '',
      measureText: (text: string) => ({ width: text.length }),
    } as unknown as CanvasRenderingContext2D

    const measure = canvasTextMeasure(ctx)
    expect(measure('7Q2M4K8P', 20)).toBe(8)
    expect(ctx.font).toContain('bold')
    expect(ctx.font).toContain('20px')
  })
})
