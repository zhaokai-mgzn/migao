'use client'

// 营销海报卡（issue #7351）—— 黄金策对话内的海报预览 + 下载。
//
// 服务端只下发**事实 + 商家确认过的文案**（`{product, copy}`，见
// `backend/ai-agent-service/app/tools/marketing_poster.py`）；本组件在浏览器里把
// 750×1000 的海报画成 PNG：PC 点「下载海报」直接落盘，手机端另有一端
// （`frontend/bmini-app/src/components/cards/PosterCard.tsx`）负责长按保存到相册。
//
// 降级口径（不静默、不撒谎）：
// - 商品图跨域载不进来 ⇒ 仍生成**无图海报**（商品名/价格/文案完整），并明说「商品图未能加载」；
// - 画布拿不到 2d / 导出失败 ⇒ 展示重试态，不返回白图。

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Download, Image as ImageIcon, RefreshCw } from 'lucide-react'
import Button from '@/components/ui/Button'
import { resolveImageUrl } from '@/lib/utils'
import { extractApiErrorMessage } from '@/lib/api-error'
import { posterViewFromCard, type MarketingPosterView } from '@/lib/marketing-poster-layout'
import {
  renderMarketingPoster,
  type PosterCanvasLike,
  type PosterImageLike,
} from '@/lib/marketing-poster-canvas'

interface MarketingPosterCardProps {
  data: Record<string, unknown>
}

type RenderState =
  | { status: 'loading' }
  | { status: 'ready'; dataUrl: string; hadImage: boolean }
  | { status: 'error'; message: string }

function createCanvas(width: number, height: number): PosterCanvasLike {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas as unknown as PosterCanvasLike
}

function loadImage(url: string): Promise<PosterImageLike | null> {
  return new Promise((resolve) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    // CORS 失败 ⇒ 再试一次不限 CORS（能画但可能污染画布；导出失败由绘制层降级为无图）
    image.onerror = () => {
      const retry = new Image()
      retry.onload = () => resolve(retry)
      retry.onerror = () => resolve(null)
      retry.src = url
    }
    image.src = url
  })
}

export default function MarketingPosterCard({ data }: MarketingPosterCardProps) {
  const view: MarketingPosterView = useMemo(() => {
    const parsed = posterViewFromCard(data)
    return {
      ...parsed,
      product: {
        ...parsed.product,
        image: parsed.product.image ? resolveImageUrl(parsed.product.image) : null,
      },
    }
  }, [data])

  const [state, setState] = useState<RenderState>({ status: 'loading' })
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let mounted = true
    setState({ status: 'loading' })
    renderMarketingPoster(view, { createCanvas, loadImage })
      .then((rendered) => {
        if (!mounted) return
        setState({ status: 'ready', dataUrl: rendered.dataUrl, hadImage: rendered.hadImage })
      })
      .catch((error: unknown) => {
        if (!mounted) return
        setState({ status: 'error', message: extractApiErrorMessage(error, '海报生成失败，请重试') })
      })
    return () => {
      mounted = false
    }
  }, [view, reloadKey])

  const handleDownload = useCallback(() => {
    if (state.status !== 'ready') return
    const anchor = document.createElement('a')
    anchor.href = state.dataUrl
    anchor.download = `营销海报-${view.product.name}.png`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  }, [state, view.product.name])

  return (
    <div
      data-testid="marketing-poster-card"
      className="bg-white border border-neutral-200 rounded-xl p-3 shadow-sm max-w-[320px]"
    >
      <div className="flex items-center gap-1.5 mb-2 text-xs font-medium text-neutral-600">
        <ImageIcon className="w-4 h-4 text-primary-600" aria-hidden />
        营销海报
      </div>

      {state.status === 'loading' && (
        <div
          data-testid="marketing-poster-loading"
          className="w-full aspect-[3/4] rounded-lg bg-neutral-100 animate-pulse"
          aria-label="海报生成中"
        />
      )}

      {state.status === 'error' && (
        <div className="py-6 text-center text-xs text-neutral-500" data-testid="marketing-poster-error">
          <p>{state.message}</p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            icon={<RefreshCw className="w-4 h-4" />}
            onClick={() => setReloadKey((key) => key + 1)}
          >
            重试
          </Button>
        </div>
      )}

      {state.status === 'ready' && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element -- data URL 无需 next/image 优化 */}
          <img
            data-testid="marketing-poster-img"
            src={state.dataUrl}
            alt={`${view.product.name} 营销海报`}
            className="w-full rounded-lg border border-neutral-100"
          />
          {!state.hadImage && (
            <p className="mt-1.5 text-xs text-amber-600" data-testid="marketing-poster-no-image">
              商品图未能加载，已生成无图海报（商品名/价格/文案完整）
            </p>
          )}
          <div className="mt-2 flex items-center justify-between gap-2">
            <Button
              size="sm"
              icon={<Download className="w-4 h-4" />}
              onClick={handleDownload}
              data-testid="marketing-poster-download"
            >
              下载海报
            </Button>
            <span className="text-xs text-neutral-400">尺寸 750×1000 PNG</span>
          </div>
          <p className="mt-1.5 text-xs text-neutral-400">
            想换文案直接告诉黄金策（如「海报主标题改成开门红」），我会重新生成。
          </p>
        </>
      )}
    </div>
  )
}
