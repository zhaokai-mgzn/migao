'use client'

import { useRef, useState } from 'react'
import { Image as ImageIcon } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { toastRequestError } from '@/lib/api-error'
import { imageRecognizeApi, uploadApi } from '@/lib/api'
import type { RecognizedField } from '@/lib/api'
import { filledFields, RECOGNIZE_SOURCE_TAG } from '@/lib/image-recognize'

/** 识别不出来时的统一提示（degraded 与「零个可用字段」两种情形同一条） */
export const RECOGNIZE_EMPTY_MESSAGE = '未识别到可用字段，请手工填写或换一张更清晰的图片'

interface ImageRecognizeButtonProps {
  targetType: 'product' | 'order'
  /** 只回传**有值**的字段候选；空值字段（内核有意留空）不在这里 */
  onRecognized: (fields: RecognizedField[]) => void
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
 * 链路：选图 → `uploadApi.uploadImage`（既有上传）→ `imageRecognizeApi.recognize` → 字段候选。
 *
 * 🔴 **绝不落库**：本组件只把识别到的字段**回传**给调用方填表，
 * **不发起任何 create/update/提交**（不碰 `productApi.createProduct` / `orderApi.createOrder`，
 * 也不提交任何 form）——「识别结果只填表，提交永远是人的动作」。
 */
export default function ImageRecognizeButton({
  targetType,
  onRecognized,
  className,
}: ImageRecognizeButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [loading, setLoading] = useState(false)
  const [fields, setFields] = useState<RecognizedField[]>([])

  const handleFile = async (file: File) => {
    setLoading(true)
    try {
      const uploadRes = await uploadApi.uploadImage(file)
      const url = uploadRes.data.data?.url
      if (!url) {
        toast.error('图片上传失败，请重试')
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
      onRecognized(usable)
    } catch (error) {
      // 后端错误已由 request.ts 拦截器统一提示；这里只兜底未经拦截器的异常
      toastRequestError(error, '图片识别失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={className}>
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
      {fields.length > 0 && (
        <div
          data-testid="image-recognize-result"
          className="mt-2 space-y-0.5 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2"
        >
          {/* 逐字段来源：有值的标 `[图片识别]`，留空的连内核给的原因一起显示（不写进表单） */}
          {fields.map((f) => (
            <p
              key={f.key}
              data-testid={`image-recognize-field-${f.key}`}
              className="text-xs leading-5 text-neutral-600"
            >
              {typeof f.value === 'string' && f.value.trim() !== ''
                ? `${RECOGNIZE_SOURCE_TAG} ${f.label}：${f.value}`
                : `${f.label}：未识别（${f.reason || '内核未给出原因'}）`}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}