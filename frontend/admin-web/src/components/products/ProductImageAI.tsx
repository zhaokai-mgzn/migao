'use client'

import { useEffect, useState } from 'react'
import Image from 'next/image'
import { Sparkles } from 'lucide-react'
import { Button } from '@/components/ui'
import { aiProductImageApi, type AiProductImageKind } from '@/lib/api'
import { toastRequestError } from '@/lib/api-error'

/**
 * 建品页「AI 生成商品图」入口（issue #7335 / #7533）。
 *
 * 交互：先上传样图（色卡 / 面料实拍）→ 选用途 → 生成 ⇒ **生成成功即自动填入图片位**：
 * 主图写进封面位（`images[0]`），细节 / 工艺 / 场景追加到详情图末位。不再需要「用这张」——
 * 改前那一步藏在预览旁，商家漏点就等于**白生成**：表单没变 ⇒ 提交载荷没有该 URL ⇒ 保存后也没有
 * （issue #7533 的实测根因）。
 *
 * 🔴 用户 2026-10-25 18:00 改判：**只追加，不覆盖** —— 「生成的图片不要直接覆盖，默认添加到主图或者详情图」。
 * 改前「再生成一张」会把上一张从两个列表里摘掉（先出详情图、再出主图时详情图被悄悄删掉 =「详情图存不下来」），
 * 主图还会抢封面位。现在一律追加到对应列表末尾；列表满（主图 5 / 详情图 9）⇒ 明确提示先删一张。
 * 仍**不落库**：结果只写进表单，提交永远是商家的动作。
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

/**
 * 失败话术（issue #7552）：按 admin-api 的 `error.code` 分叉，**不在前端切字符串**。
 *
 * 三类不同的下一个动作：模型/能力不可用（该找平台）≠ 额度用尽（该等额度）≠ 真·瞬时（该重试）。
 * 话术里不出现服务名 / 内部地址（§31 P3）—— 那些只进日志。
 */
const PLATFORM_UNAVAILABLE = '该能力暂不可用，已反馈平台；可先上传图片继续建品。'

/** 生成成功但图片位已满 ⇒ 不是失败，是「先腾个位置」。不静默丢图，也不假装已填入。 */
const MAIN_FULL = '主图已满 5 张，先在图片列表里删一张再生成。'
const DETAIL_FULL = '详情图已满 9 张，先在详情图列表里删一张再生成。'

const FAILURE_MESSAGES: Record<string, string> = {
  AI_PRODUCT_IMAGE_MODEL_UNSUPPORTED: PLATFORM_UNAVAILABLE,
  AI_PRODUCT_IMAGE_DISABLED: PLATFORM_UNAVAILABLE,
  AI_PRODUCT_IMAGE_NOT_CONFIGURED: PLATFORM_UNAVAILABLE,
  AI_PRODUCT_IMAGE_QUOTA_EXCEEDED: '今日额度已用完，可明天再试；也可直接上传图片。',
}

/** 失败话术：认 `error.code`；没有码（网络 / 超时）才用「稍后重试」兜底。 */
function failureMessage(error: unknown): string {
  const code = (error as { response?: { data?: { error?: { code?: string } } } })?.response?.data
    ?.error?.code
  return (code && FAILURE_MESSAGES[code]) || FAILURE_MESSAGE
}

interface ProductImageAIProps {
  /** 样图候选 = 已上传的主图与详情图（色卡 / 面料实拍，调用方去重）；为空时入口不可用。默认用第 1 张，可切换。 */
  sampleImages?: string[]
  /** 商品名（提示词里用；可空） */
  productName?: string
  /** 主图：追加到主图列表末尾；返回 false = 已满（调用方没写进去，需要提示先删一张）。 */
  onApplyMain: (url: string) => boolean
  /** 细节 / 工艺 / 场景图：追加到详情图列表末尾；返回 false = 已满。 */
  onApplyDetail: (url: string) => boolean
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
  /** 上一次**自动填入表单**的结果（只用于「再生成一张」按钮文案与绿色状态行）。 */
  const [applied, setApplied] = useState<{ url: string; kind: AiProductImageKind } | null>(null)

  /** 图片列表变化（上传 / 删除 / 自动填入）时，样图始终指向仍然存在的一张。 */
  useEffect(() => {
    if (!sampleImages.includes(sample)) setSample(sampleImages[0] || '')
  }, [sampleImages, sample])

  const clearFeedback = () => {
    setResult('')
    setError('')
  }

  /** 写进表单：主图 ⇒ 主图列表末尾；其余 ⇒ 详情图列表末尾。返回是否写进去了（满了就是 false）。 */
  const apply = (url: string, target: AiProductImageKind): boolean => {
    const ok = target === 'main' ? onApplyMain(url) : onApplyDetail(url)
    if (ok) setApplied({ url, kind: target })
    return ok
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
      // 生成成功即落位（issue #7533）：多一步「用这张」= 商家漏点即白生成。
      if (!apply(url, kind)) {
        setError(kind === 'main' ? MAIN_FULL : DETAIL_FULL)
      }
    } catch (e) {
      const message = failureMessage(e)
      setError(message)
      // 拦截器已统一提示时这里不重复弹（toastRequestError 内部判定）
      toastRequestError(e, message)
    } finally {
      setLoading(false)
    }
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
              {applied ? '再生成一张' : '生成'}
            </Button>
            <span className="text-xs text-neutral-400">细节图会加入下方「详情图」。</span>
            {error && <span className="text-xs text-red-600">{error}</span>}
            {applied && (
              <span role="status" className="text-xs text-green-600">
                {applied.kind === 'main' ? '已加入主图' : '已加入「详情图」'}；可继续生成其他用途。
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
              <p className="text-xs text-neutral-500">
                请核对颜色与工艺；不满意可再生成一张（替换这一张），或在图片列表里删除。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
