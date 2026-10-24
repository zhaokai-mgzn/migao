// case_ids: PR-053
/**
 * 营销海报绘制层（issue #7351）—— 薄，但**每条降级路径都要钉住**：
 * 1. 有图 ⇒ cover-fit 裁剪后画进 imageRect，`hadImage=true`；
 * 2. 没图 / 图取不到 ⇒ 照常出无图海报，`hadImage=false`（不谎报有图）；
 * 3. 跨域污染导致 `toDataURL` 抛错 ⇒ **无图重绘**后导出，`hadImage=false`；
 * 4. 拿不到 2d 上下文 ⇒ 抛错（不返回白图）。
 */
import { describe, it, expect, vi } from 'vitest'
import {
  renderMarketingPoster,
  type PosterCanvasLike,
  type PosterContextLike,
  type PosterImageLike,
} from '@/lib/marketing-poster-canvas'

const DATA = {
  product: {
    id: 'p1',
    name: '高遮光雪尼尔窗帘',
    price: 299,
    unit: '米',
    image: 'https://img.example.com/1.jpg',
    specs: ['遮光率：95%'],
  },
  copy: { title: '新品上市', selling_points: ['高遮光'] },
}

function fakeCtx() {
  return {
    fillStyle: '',
    font: '',
    textAlign: 'left' as CanvasTextAlign,
    textBaseline: 'top' as CanvasTextBaseline,
    fillRect: vi.fn(),
    fillText: vi.fn(),
    drawImage: vi.fn(),
  }
}

function fakeCanvas(ctx: ReturnType<typeof fakeCtx> | null, toDataURL = () => 'data:image/png;base64,OK') {
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ctx,
    toDataURL: vi.fn(toDataURL),
  }
  return canvas as unknown as PosterCanvasLike
}

// 1000×360（比 imageRect 670×360 更宽）⇒ 必走横向裁剪：scale=1、sw=670、sx=165
const IMAGE: PosterImageLike = { naturalWidth: 1000, naturalHeight: 360, width: 1000, height: 360 }

describe('renderMarketingPoster', () => {
  it('有图：按 cover-fit 裁剪进 imageRect，hadImage=true', async () => {
    const ctx = fakeCtx()
    const canvas = fakeCanvas(ctx)
    const rendered = await renderMarketingPoster(DATA, {
      createCanvas: () => canvas,
      loadImage: async () => IMAGE,
    })

    expect(rendered).toMatchObject({ width: 750, height: 1000, hadImage: true })
    // 1000×360 画进 670×360：scale=max(670/1000, 360/360)=1 ⇒ 横向裁剪、垂直满高
    expect(ctx.drawImage).toHaveBeenCalledTimes(1)
    const [, sx, sy, sw, sh, x, y, w, h] = ctx.drawImage.mock.calls[0]
    expect([x, y, w, h]).toEqual([40, 250, 670, 360])
    expect([sx, sy, sw, sh]).toEqual([165, 0, 670, 360])
    // 标题 / 商品名 / 价格都真的被画了
    const texts = ctx.fillText.mock.calls.map((c) => c[0])
    expect(texts).toContain('新品上市')
    expect(texts).toContain('高遮光雪尼尔窗帘')
    expect(texts.some((t: string) => t.startsWith('¥299'))).toBe(true)
  })

  it('没图：loadImage 不被调用，仍出海报且 hadImage=false', async () => {
    const ctx = fakeCtx()
    const loadImage = vi.fn(async () => IMAGE)
    const rendered = await renderMarketingPoster(
      { ...DATA, product: { ...DATA.product, image: null } },
      { createCanvas: () => fakeCanvas(ctx), loadImage },
    )

    expect(loadImage).not.toHaveBeenCalled()
    expect(rendered.hadImage).toBe(false)
    expect(ctx.drawImage).not.toHaveBeenCalled()
  })

  it('图取不到：不抛错、降级无图（hadImage=false）', async () => {
    const ctx = fakeCtx()
    const rendered = await renderMarketingPoster(DATA, {
      createCanvas: () => fakeCanvas(ctx),
      loadImage: async () => null,
    })
    expect(rendered.hadImage).toBe(false)
    expect(ctx.drawImage).not.toHaveBeenCalled()
  })

  it('跨域污染：toDataURL 抛错 ⇒ 无图重绘并导出，hadImage=false', async () => {
    const dirty = fakeCtx()
    const clean = fakeCtx()
    let canvasCount = 0
    const rendered = await renderMarketingPoster(DATA, {
      createCanvas: () => {
        canvasCount += 1
        if (canvasCount === 1) {
          return fakeCanvas(dirty, () => {
            throw new Error('SecurityError: tainted canvas')
          })
        }
        return fakeCanvas(clean)
      },
      loadImage: async () => IMAGE,
    })

    expect(rendered).toMatchObject({ dataUrl: 'data:image/png;base64,OK', hadImage: false })
    expect(dirty.drawImage).toHaveBeenCalledTimes(1)
    // 第二张画布**没有**再画图（污染源被移除）
    expect(clean.drawImage).not.toHaveBeenCalled()
    expect(clean.fillText).toHaveBeenCalled()
  })

  it('拿不到 2d 上下文 ⇒ 抛错（不返回白图）', async () => {
    await expect(
      renderMarketingPoster(DATA, { createCanvas: () => fakeCanvas(null), loadImage: async () => IMAGE }),
    ).rejects.toThrow(/海报生成失败，请重试/)
  })
})
