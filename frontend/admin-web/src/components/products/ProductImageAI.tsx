'use client'

import { useEffect, useState } from 'react'
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
  /** 样图候选 = 已上传的商品图（色卡 / 面料实拍）；为空时入口不可用。默认用第 1 张，可切换。 */
  sampleImages?: string[]
  /** 商品名（提示词里用；可空） */
  productName?: string
  /** 主图：插到 `images[0]`（封面位） */
  onApplyMain: (url: string) => void
  /** 细节图：追加到 `detailImages` */
  onApplyDetail: (url: string) => void
}

export default function ProductImageAI({
  sampleImages = [],
  productName,
  onApplyMain,
  onApplyDetail,
}: ProductImageAIProps) {
  const [open, setOpen] = useState(false)
  const [sample, setSample] = useState(sampleImages[0] || '')
  const [kind, setKind] = useState<AiProductImageKind>('main')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  const [applied, setApplied] = useState('')

  /** 图片列表变化（上传 / 删除 / 用这张后插封面）时，样图始终指向仍然存在的一张。 */
  useEffect(() => {
    if (!sampleImages.includes(sample)) setSample(sampleImages[0] || '')
  }, [sampleImages, sample])

  const clearFeedback = () => {
    setResult('')
    setError('')
    setApplied('')
  }

  const generate = async () => {
    if (!sample || loading) return
    setLoading(true)
    setError('')
    try {
      const res = await aiProductImageApi.generate({ imageUrl: sample, productName, kind })
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
      setApplied('已插入封面位')
    } else {
      onApplyDetail(result)
      setApplied('已加入「详情图」')
    }
    // 不收起面板：存量商品常要一次补主图 + 材质 + 工艺 + 场景，收起后每张都要重开。
    setResult('')
  }

  return (
    <div className="mt-3 rounded-lg border border-neutral-200 bg-neutral-50/60 px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-neutral-500">
          以样图生成接近实物的商品图（约 40 秒，每次 1 张）。
        </p>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          icon={<Sparkles className="w-4 h-4" />}
          disabled={sampleImages.length === 0}
          aria-expanded={open}
          onClick={() => {
            setOpen((v) => !v)
            clearFeedback()
          }}
        >
          AI 生成商品图
        </Button>
      </div>

      {sampleImages.length === 0 && (
        <p className="mt-1.5 text-xs text-neutral-400">
          先上传一张样图（建议色卡或面料实拍），再点生成。
        </p>
      )}

      {open && sampleImages.length > 0 && (
        <div className="mt-3 space-y-3 border-t border-neutral-200 pt-3">
          {sampleImages.length > 1 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-neutral-500">样图</span>
              {sampleImages.slice(0, 5).map((url, index) => (
                <button
                  key={url}
                  type="button"
                  aria-label={`使用第${index + 1}张作为样图`}
                  aria-pressed={sample === url}
                  onClick={() => {
                    setSample(url)
                    clearFeedback()
                  }}
                  className={`rounded-md border p-0.5 ${
                    sample === url ? 'border-primary-500 ring-1 ring-primary-500' : 'border-neutral-200'
                  }`}
                >
                  <Image
                    src={url}
                    alt={`样图 ${index + 1}`}
                    width={40}
                    height={40}
                    unoptimized
                    className="h-10 w-10 rounded object-cover"
                  />
                </button>
              ))}
            </div>
          )}
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
                  clearFeedback()
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
            {applied && (
              <span role="status" className="text-xs text-green-600">
                {applied}；可继续生成其他用途。
              </span>
            )}
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
