'use client'

// 商品图生成卡（issue #7541）—— 黄金策对话内「对已选商品生成商品图」的预览 + 下载。
//
// 服务端只回一张**临时**图片地址（生图内核不落库、不写表单，见
// `backend/ai-agent-service/app/tools/product_image_generate.py`）；本组件只负责
// 展示 + 提供下载入口。手机端另有 `frontend/bmini-app/src/components/cards/GeneratedImageCard.tsx`
// 负责「保存到相册」。
//
// 降级口径（不静默、不撒谎）：
// - 载荷里没有图片地址 ⇒ 说明「这次没拿到图」并给出下一步（重新生成 / 后台上传），不画空图框；
// - 图片加载失败 ⇒ 提示链接可能已过期（内核回的是 24 小时临时地址），点「重新加载」可重试；
// - 跨域取不到文件 ⇒ 在新窗口打开并说明可用「图片另存为」，**不谎报已下载**。

import { useCallback, useMemo, useState } from 'react'
import { Download, Image as ImageIcon } from 'lucide-react'
import Button from '@/components/ui/Button'

/** 用途 → 用户可见的中文名（与后端 `KIND_LABELS` 同一套语义；不显示内部 kind 值）。 */
const KIND_LABELS: Record<string, string> = {
  main: '商品主图',
  texture: '材质细节图',
  craft: '工艺细节图',
  scene: '场景效果图',
}

interface GeneratedImageCardProps {
  data: Record<string, unknown>
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

export default function GeneratedImageCard({ data }: GeneratedImageCardProps) {
  const view = useMemo(() => {
    const product = asRecord(data.product)
    const kind = String(product.kind ?? 'main')
    return {
      imageUrl: typeof data.image_url === 'string' ? data.image_url.trim() : '',
      name: typeof product.name === 'string' ? product.name.trim() : '',
      kindLabel: KIND_LABELS[kind] ?? '商品图',
    }
  }, [data])

  const [imageFailed, setImageFailed] = useState(false)
  const [hint, setHint] = useState('')
  const [downloading, setDownloading] = useState(false)

  const fileName = `商品图-${view.name || '商品'}.png`

  const handleDownload = useCallback(async () => {
    if (!view.imageUrl) return
    setHint('')
    setDownloading(true)
    try {
      // 生成图在外部图片服务上：`<a download>` 对跨域地址不生效，所以先取成文件再存。
      const response = await fetch(view.imageUrl)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = fileName
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(objectUrl)
    } catch {
      // 取不到文件 ⇒ 打开原图让商家自行另存（不谎报「已下载」）
      window.open(view.imageUrl, '_blank', 'noopener')
      setHint('图片没能直接下载，已在新窗口打开 —— 右键「图片另存为」即可保存。')
    } finally {
      setDownloading(false)
    }
  }, [view.imageUrl, fileName])

  if (!view.imageUrl) {
    return (
      <div
        data-testid="generated-image-card-empty"
        className="bg-neutral-50 border border-neutral-200 rounded-lg p-3 text-xs text-neutral-600 space-y-1"
      >
        <p>这次没有拿到商品图，暂时没法预览。</p>
        <p className="text-neutral-500">
          可以让我重新生成一次；也可以直接在「商品管理」里上传商品图。
        </p>
      </div>
    )
  }

  return (
    <div
      data-testid="generated-image-card"
      className="border border-neutral-200 rounded-lg p-3 space-y-2 bg-white"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-neutral-700">{view.kindLabel}</span>
        {view.name && (
          <span className="text-xs text-neutral-500 truncate max-w-[60%]">{view.name}</span>
        )}
      </div>

      {imageFailed ? (
        <div
          data-testid="generated-image-card-image-failed"
          className="bg-neutral-50 border border-neutral-200 rounded p-3 text-xs text-neutral-600 space-y-1"
        >
          <p>图片没能加载出来，链接可能已经过期。</p>
          <p className="text-neutral-500">
            可以让我重新生成一次；也可以直接在「商品管理」里上传商品图。
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setImageFailed(false)}
            aria-label="重新加载图片"
          >
            重新加载
          </Button>
        </div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- 生成图是外部临时地址，不走 next/image 优化
        <img
          data-testid="generated-image-card-img"
          src={view.imageUrl}
          alt={view.name ? `商品图：${view.name}` : '商品图'}
          className="w-full max-w-xs rounded border border-neutral-100"
          onError={() => setImageFailed(true)}
        />
      )}

      <div className="flex items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          icon={<Download className="w-4 h-4" aria-hidden />}
          loading={downloading}
          onClick={handleDownload}
        >
          下载图片
        </Button>
        <span className="inline-flex items-center gap-1 text-xs text-neutral-400">
          <ImageIcon className="w-3 h-3" aria-hidden />
          手机上可在对话里保存到相册
        </span>
      </div>

      {hint && (
        <p data-testid="generated-image-card-hint" className="text-xs text-neutral-500">
          {hint}
        </p>
      )}
    </div>
  )
}
