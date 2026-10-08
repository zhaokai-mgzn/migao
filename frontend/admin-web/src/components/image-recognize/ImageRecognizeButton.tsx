'use client'

import { useRef, useState } from 'react'
import { Image as ImageIcon } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { toastRequestError } from '@/lib/api-error'
import { imageRecognizeApi, uploadApi } from '@/lib/api'
import type { RecognizedField } from '@/lib/api'
import { filledFields, hasReference, RECOGNIZE_NO_REASON, RECOGNIZE_SOURCE_TAG, referenceFields } from '@/lib/image-recognize'
import FormInterpretCard, { type FormInterpretFields } from './FormInterpretCard'

/** 识别不出来时的统一提示（degraded 与「零个可用字段」两种情形同一条） */
export const RECOGNIZE_EMPTY_MESSAGE = '未识别到可用字段，请手工填写或换一张更清晰的图片'

/** 解读模式失败时的**可行动**文案（失败不能只说「失败」——要告诉商家下一步能做什么） */
export const INTERPRET_FAILURE_MESSAGE = '识别或解读失败，可重试或手工填写'
/** 解读回了计划但一个字段都没有（同样必须可行动，且**不渲染空卡片**） */
export const INTERPRET_EMPTY_MESSAGE = '这次没有可填的字段，可重试或手工填写'

interface ImageRecognizeButtonProps {
  targetType: 'product' | 'order'
  /**
   * 回传**有值**的字段候选（空值字段 —— 内核有意留空 —— 不在这里）；
   * **另带**「参考字段」（`reference`，issue #6529）：它们 `value` 为空、**不进表单**，
   * 调用方只用来「按名称查目录 / 展示」（订单侧明细就是这样拿到「目录里没有这个商品」的）。
   */
  onRecognized: (fields: RecognizedField[]) => void
  /**
   * 「识别 + **一次性**推理」模式（issue #6367 包 P3；建品页用）。
   *
   * 打开后：按钮旁多一个**可选的一句话要求**输入框，选图后走
   * `imageRecognizeApi.interpret`（不是 `recognize`），结果先落成**内嵌卡片**
   * （两段分组 + 每格可勾选），由商家点「一键填入」才进表单 ——
   * 一次性、不留上下文、不追加轮次。
   *
   * 缺省 = 既有的纯识别链路（建单页仍是这条；防「必须有 LLM 才能用」那条判据）。
   */
  interpret?: boolean
  className?: string
}

/**
 * 预填来源徽标（`[图片识别]`）。
 *
 * 放在本文件是为了**不新增文件**：徽标文案与 `recognized-marker-*` testid 只有这一份实现，
 * 建品页（`ProductForm` 的 `FieldRow`）与建单页（收货信息四个字段）共用它。
 */
export function RecognizedBadge({ fieldKey }: { fieldKey: string }) {
  return (
    <span
      data-testid={`recognized-marker-${fieldKey}`}
      className="ml-1.5 inline-block align-middle whitespace-nowrap rounded border border-primary-200 bg-primary-50 px-1 text-[10px] leading-4 text-primary-600"
    >
      {RECOGNIZE_SOURCE_TAG}
    </span>
  )
}

/**
 * 「拍照 / 上传识别」按钮（issue #5321 包 1「页面快通道」）。
 *
 * 链路：选图 → `uploadApi.uploadImage`（既有上传）→ 识别 → 字段候选。
 * `interpret` 打开时走 {@link ImageRecognizeButtonProps.interpret} 描述的那条一次性推理链路。
 *
 * 🔴 **绝不落库**：本组件只把识别到的字段**回传**给调用方填表，
 * **不发起任何 create/update/提交**（不碰 `productApi.createProduct` / `orderApi.createOrder`，
 * 也不提交任何 form）——「识别结果只填表，提交永远是人的动作」。
 * 两条链路共用这一点：解读模式同样只调 `onRecognized`（由结果卡的「一键填入」触发）。
 */
export default function ImageRecognizeButton({
  targetType,
  onRecognized,
  interpret = false,
  className,
}: ImageRecognizeButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [loading, setLoading] = useState(false)
  const [fields, setFields] = useState<RecognizedField[]>([])
  // 解读模式的状态：那句可选要求 / 结果计划 / 缩略图 / 可行动的失败文案
  const [hint, setHint] = useState('')
  const [plan, setPlan] = useState<FormInterpretFields | null>(null)
  const [imageUrl, setImageUrl] = useState('')
  const [failure, setFailure] = useState('')

  const handleFile = async (file: File) => {
    setLoading(true)
    if (interpret) {
      // 每一次都是**新的一次性推理**：旧结果先清掉（不留旧卡片，失败时也不留空卡片）
      setPlan(null)
      setImageUrl('')
      setFailure('')
    }
    try {
      const uploadRes = await uploadApi.uploadImage(file)
      const url = uploadRes.data.data?.url
      if (!url) {
        if (interpret) setFailure(INTERPRET_FAILURE_MESSAGE)
        toast.error('图片上传失败，请重试')
        return
      }

      if (interpret) {
        // 一次性推理：图 + 商家那句话 → 字段计划（每格的来源由服务端标注：抄的 / 推的）。
        // 空串提示由 `lib/api.ts` 统一丢掉该键（这里原样透传，不重复一份规则）。
        const res = await imageRecognizeApi.interpret(targetType, [url], hint)
        const result = res.data.data
        if (!result || !Array.isArray(result.fields) || result.fields.length === 0) {
          setFailure(INTERPRET_EMPTY_MESSAGE)
          return
        }
        setImageUrl(url)
        setPlan(result.fields)
        return
      }

      const res = await imageRecognizeApi.recognize(targetType, [url])
      const result = res.data.data
      const all = result?.fields || []
      const usable = filledFields(all)
      setFields(all)
      if (!result || result.degraded || usable.length === 0) {
        toast.error(RECOGNIZE_EMPTY_MESSAGE)
        return
      }
      onRecognized([...usable, ...referenceFields(all)])
    } catch (error) {
      if (interpret) setFailure(INTERPRET_FAILURE_MESSAGE)
      // 后端错误已由 request.ts 拦截器统一提示；这里只兜底未经拦截器的异常
      toastRequestError(error, '图片识别失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="secondary"
          onClick={() => inputRef.current?.click()}
          loading={loading}
          data-testid="image-recognize-button"
        >
          <ImageIcon className="w-4 h-4 mr-1.5" />
          拍照 / 上传识别
        </Button>
        {interpret && (
          /* 一句可选要求（如「客厅雪尼尔，韩褶，遮光」）：只喂给这一次推理，不留上下文 */
          <input
            type="text"
            value={hint}
            maxLength={200}
            onChange={(e) => setHint(e.target.value)}
            placeholder="补充一句（可选）：如 客厅用、韩褶、遮光"
            aria-label="补充一句要求（可选）"
            data-testid="image-recognize-hint"
            className="h-9 w-56 rounded-lg border border-neutral-300 px-2.5 text-xs text-neutral-700 placeholder:text-neutral-400 focus:border-primary-400 focus:outline-none"
          />
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        data-testid="image-recognize-input"
        onChange={(e) => {
          const file = e.target.files?.[0]
          // 清空 value：同一张图再选一次也要能触发 onChange
          e.target.value = ''
          if (file) void handleFile(file)
        }}
      />
      {failure && (
        <p data-testid="image-recognize-failure" className="mt-2 text-xs leading-5 text-red-600">
          {failure}
        </p>
      )}
      {interpret && plan && imageUrl && (
        /* 结果卡就嵌在按钮下方（表单内）——不是弹窗、不是对话、不留上下文 */
        <FormInterpretCard key={imageUrl} imageUrl={imageUrl} fields={plan} onFill={onRecognized} />
      )}
      {fields.length > 0 && (
        <div
          data-testid="image-recognize-result"
          className="mt-2 space-y-0.5 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2"
        >
          {/* 逐字段来源：有值的标 `[图片识别]`，留空的连内核给的原因一起显示（不写进表单）；
              「参考」（图上读到、没采纳）**单独一行**如实说清 —— 它同样不写进表单 */}
          {fields.map((f) => (
            <div key={f.key}>
              <p
                data-testid={`image-recognize-field-${f.key}`}
                className="text-xs leading-5 text-neutral-600"
              >
                {typeof f.value === 'string' && f.value.trim() !== ''
                  ? `${RECOGNIZE_SOURCE_TAG} ${f.label}：${f.value}`
                  : `${f.label}：未识别（${f.reason || RECOGNIZE_NO_REASON}）`}
              </p>
              {hasReference(f) && (
                <p
                  data-testid={`image-recognize-reference-${f.key}`}
                  className="text-xs leading-5 text-amber-700"
                >
                  图上读到（未采纳，仅供查目录）：{f.reference}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
