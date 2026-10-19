'use client'

import { useState } from 'react'
import Image from 'next/image'
import { Sparkles } from 'lucide-react'
import { Button } from '@/components/ui'
import { aiProductImageApi, type AiProductImageKind } from '@/lib/api'
import { toastRequestError } from '@/lib/api-error'

/**
 * 建品页「AI 生成商品图」入口（issue #7335）。
 *
 * 交互：商家先上传一张**样图**（色卡 / 面料实拍）→ 选用途 → 生成 → 预览 → 「用这张」。
 * 只回预览，不自动保存；「用这张」只是写进表单（主图插到封面位 / 细节图追加到详情图），
 * 提交仍是商家的动作。
 *
 * 设计口径（§31）：常驻面只有一行提示 + 一个按钮；面板按需展开，生成中禁用按钮，
 * 文案只陈述事实与该做什么（不催、不夸大）。
 */

const KINDS: Array<{ value: AiProductImageKind; label: string }> = [
  { value: 'main', label: '主图' },
  { value: 'texture', label: '材质细节' },
  { value: 'craft', label: '工艺细节' },
  { value: 'scene', label: '场景图' },
]

const FAILURE_MESSAGE = '生成失败，请稍后重试，或直接上传图片'

interface ProductImageAIProps {
  /** 样图 = 已上传的第一张商品图（色卡 / 面料实拍；为空时入口不可用） */
  sampleImage?: string
  /** 商品名（提示词里用；可空） */
  productName?: string
  /** 主图：插到 `images[0]`（封面位） */
  onApplyMain: (url: string) => void
  /** 细节图：追加到 `detailImages` */
  onApplyDetail: (url: string) => void
}

export default function ProductImageAI({
  sampleImage,
  productName,
  onApplyMain,
  onApplyDetail,
}: ProductImageAIProps) {
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<AiProductImageKind>('main')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')
  const [error, setError] = useState('')

  const generate = async () => {
    if (!sampleImage || loading) return
    setLoading(true)
    setError('')
    try {
      const res = await aiProductImageApi.generate({ imageUrl: sampleImage, productName, kind })
      const url = res.data.data?.url
      if (!url) {
        setError(FAILURE_MESSAGE)
        return
      }
      setResult(url)
    } catch (e) {
      setError(FAILURE_MESSAGE)
      // 拦截器已统一提示时这里不重复弹（toastRequestError 内部判定）
      toastRequestError(e, FAILURE_MESSAGE)
    } finally {
      setLoading(false)
    }
  }

  const apply = () => {
    if (!result) return
    if (kind === 'main') {
      onApplyMain(result)
    } else {
      onApplyDetail(result)
    }
    setOpen(false)
  }

  return (
    <div className="mt-3 rounded-lg border border-neutral-200 bg-neutral-50/60 px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-neutral-500">
          以第一张图为样图，生成接近实物的商品图（约 40 秒，每次 1 张）。
        </p>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          icon={<Sparkles className="w-4 h-4" />}
          disabled={!sampleImage}
          aria-expanded={open}
          onClick={() => {
            setOpen((v) => !v)
            setResult('')
            setError('')
          }}
        >
          AI 生成商品图
        </Button>
      </div>

      {!sampleImage && (
        <p className="mt-1.5 text-xs text-neutral-400">
          先上传一张样图（建议色卡或面料实拍），再点生成。
        </p>
      )}

      {open && sampleImage && (
        <div className="mt-3 space-y-3 border-t border-neutral-200 pt-3">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="生成用途">
            {KINDS.map((item) => (
              <Button
                key={item.value}
                type="button"
                size="sm"
                variant={kind === item.value ? 'secondary' : 'ghost'}
                aria-pressed={kind === item.value}
                className={kind === item.value ? 'border-primary-500 text-primary-600' : undefined}
                onClick={() => {
                  setKind(item.value)
                  setResult('')
                  setError('')
                }}
              >
                {item.label}
              </Button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              loading={loading}
              onClick={generate}
            >
              {result ? '再生成一张' : '生成'}
            </Button>
            <span className="text-xs text-neutral-400">细节图会加入下方「详情图」。</span>
            {error && <span className="text-xs text-red-600">{error}</span>}
          </div>

          {result && (
            <div className="flex flex-wrap items-start gap-3">
              <Image
                src={result}
                alt="AI 生成的商品图"
                width={160}
                height={160}
                unoptimized
                className="h-40 w-40 rounded-lg border border-neutral-200 object-cover"
              />
              <div className="space-y-2">
                <p className="text-xs text-neutral-500">已生成，请核对颜色与工艺后再使用。</p>
                <Button type="button" size="sm" onClick={apply}>
                  用这张
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
