'use client'

import { useMemo, useState } from 'react'
import Image from 'next/image'
import { Button } from '@/components/ui'
import { resolveImageUrl } from '@/lib/utils'
import { htmlToPlainText } from '@/lib/rich-text-plain'
import type { RecognizedField } from '@/lib/api'
import { RECOGNIZE_NO_REASON, referenceFields } from '@/lib/image-recognize'
import {
  PAGE_FILL_SOURCE_DECLARED,
  PAGE_FILL_SOURCE_INTERPRETED,
  PAGE_FILL_SOURCE_RECOGNIZED,
  type PageFillField,
} from '@/lib/agent-page-fill'
import {
  declaredCellsOf,
  renamedColorValue,
  type DeclaredFacts,
} from '@/lib/declared-facts'

/**
 * 卡片消费 / 回传的字段集合 —— 直接复用既有**字段计划**的形状，**不另造第二份**
 * （形状 owner = 服务端契约：`{key,label,value,source,reason,candidates,note,note_source}`）。
 */
export type FormInterpretFields = PageFillField[]

interface FormInterpretCardProps {
  /** 已上传的图片 URL（缩略图用 —— 就是识别用的那张，不是另拍的，也不是装饰） */
  imageUrl: string
  fields: FormInterpretFields
  /**
   * 商家在「补充一句」里写下的**字面事实**（issue #7528，`lib/declared-facts.ts` 解析）。
   *
   * 给了就多出第三段 `[商家填写]`（货号 / 门幅 / 规格属性），并把颜色按命名规则改名 ——
   * 这些都是**确定性解析**的结果（零 LLM），与另外两枚来源（`[图片识别]` / `[米宝解读]`）可分辨。
   */
  facts?: DeclaredFacts
  /** 「一键填入」：把**选中的、有值的**格子交回页面（沿用页面既有的 `onRecognized` 回调） */
  onFill: (fields: RecognizedField[]) => void
  className?: string
}

/** 有值 = 可填候选；空值格是内核**有意留空**（不确定的宁可不填）⇒ 只展示原因、不可选 */
function hasValue(field: PageFillField): boolean {
  return typeof field.value === 'string' && field.value.trim() !== ''
}

/**
 * 来源归口 —— **只比对字符串**（`source` 一共三个取值：抄的 / 推的 / 商家写的）。
 * 没给来源的格子（= 抄不到）归到第一段：它的 `reason` 也要让商家看见，不该凭空消失。
 */
function sourceGroupOf(field: PageFillField): string {
  if (field.source === PAGE_FILL_SOURCE_INTERPRETED) return PAGE_FILL_SOURCE_INTERPRETED
  if (field.source === PAGE_FILL_SOURCE_DECLARED) return PAGE_FILL_SOURCE_DECLARED
  return PAGE_FILL_SOURCE_RECOGNIZED
}

const GROUPS = [
  {
    source: PAGE_FILL_SOURCE_RECOGNIZED,
    testid: 'form-interpret-group-recognized',
    title: `${PAGE_FILL_SOURCE_RECOGNIZED} 从图上抄的`,
  },
  {
    source: PAGE_FILL_SOURCE_INTERPRETED,
    testid: 'form-interpret-group-interpreted',
    title: `${PAGE_FILL_SOURCE_INTERPRETED} 黄金策推的`,
  },
  {
    source: PAGE_FILL_SOURCE_DECLARED,
    testid: 'form-interpret-group-declared',
    title: `${PAGE_FILL_SOURCE_DECLARED} 按你写的那句话`,
  },
] as const

/**
 * 长文本格（颜色串 / 规格串，动辄上百字）**独占一行**：挤在三列里会变成又高又窄的
 * 「面条」，正是这次要消掉的形态。
 */
function isWideField(field: PageFillField): boolean {
  if (!hasValue(field)) return false
  const text = htmlToPlainText(String(field.value))
  return text.length > 40 || text.includes('\n')
}

/**
 * 把「商家填写」与颜色命名规则合并进字段计划（issue #7528）—— 纯函数，**不改入参**。
 *
 * 三条合并规则：
 * 1. **颜色改名**：有命名规则且 `color` 格有值 ⇒ 按 `货号-序号+颜色名` 改写（来源仍是
 *    `[图片识别]`：颜色内容是图上抄的，只有**命名格式**是商家写的 —— 在 `note` 里说清）；
 * 2. **空格才填**：`[图片识别]` 已有值的格**一律不动**（图是事实源，错也是他看得见的）；
 * 3. **可覆盖模型推断**：`[米宝解读]` 的值是人推的，商家明说的字面事实优先。
 */
export function mergeDeclaredFacts(
  fields: FormInterpretFields,
  facts?: DeclaredFacts,
): FormInterpretFields {
  if (!facts) return fields
  let merged = fields

  if (facts.colorRule) {
    merged = merged.map((field) => {
      if (field.key !== 'color' || !hasValue(field)) return field
      const renamed = renamedColorValue(String(field.value), facts.colorRule)
      if (!renamed) return field
      const note = field.note
        ? `${field.note}（已按你写的命名规则改为 ${renamed}）`
        : `已按你写的命名规则（货号-序号+颜色名）改为 ${renamed}`
      return { ...field, value: renamed, note }
    })
  }

  for (const cell of declaredCellsOf(facts)) {
    const index = merged.findIndex((field) => field.key === cell.key)
    if (index < 0) {
      merged = [
        ...merged,
        {
          key: cell.key,
          label: cell.label,
          value: cell.value,
          source: PAGE_FILL_SOURCE_DECLARED,
          reason: cell.reason,
          candidates: [],
          note: null,
          note_source: null,
        },
      ]
      continue
    }
    const existing = merged[index]
    if (hasValue(existing) && existing.source !== PAGE_FILL_SOURCE_INTERPRETED) continue
    merged = merged.map((field, i) =>
      i === index
        ? {
            ...field,
            value: cell.value,
            source: PAGE_FILL_SOURCE_DECLARED,
            reason: cell.reason,
            note: null,
            note_source: null,
          }
        : field,
    )
  }
  return merged
}

/**
 * 「识别 + 一次性推理」的**内嵌结果卡**（issue #6367 包 P3）—— 纯展示 + 一次填充回调。
 *
 * 用户口径（逐字）：**不是**弹窗 / 对话 / 气泡；分段展示，各带 `note` 依据；
 * 每格可勾选/取消，「一键填入」把选中的格子交回页面。
 *
 * 段：`[图片识别]` 从图上抄的 / `[米宝解读]` 黄金策推的 / `[商家填写]` 按他写的那句话
 * （第三段是 issue #7528：货号 / 门幅 / 规格属性 —— 由 `lib/declared-facts.ts` 确定性解析）。
 *
 * 🔴 **版式 = 横版整行**（用户 2026-11-06 反馈：改前是 `w-72` 的竖版窄条，字段一行一个，
 * 长颜色串拉成一米多高的面条，非常占版面）：卡片刻意**不再自带固定窄宽**（`w-full`，
 * 由落点决定宽度），字段按来源分段后铺成 `1 → 2 → 3` 列网格，长文本格独占一行。
 *
 * 🔴 **不落库**：本组件不 import 任何写端点，也只调调用方给的那一个 `onFill`
 * （= 页面既有的 `onRecognized`）——「填表」与「提交」是两件事，后者永远是人的动作。
 * 🔴 **空值格不是可填项**：没有勾选框，只显示 `reason`（内核给的原因，前端不另写文案）。
 */
export default function FormInterpretCard({
  imageUrl,
  fields,
  facts,
  onFill,
  className,
}: FormInterpretCardProps) {
  const merged = useMemo(() => mergeDeclaredFacts(fields, facts), [fields, facts])

  // 默认全选：识别 + 解读 + 商家填写的结果都是**候选**，商家取消掉不想要的即可
  // （多一步「全选」没有价值）。🔴 存的是**取消勾选的**键（而不是选中键）：
  // 商家改那句文字后，新解析出来的格子会出现在 `merged` 里，存选中键会让它**默认不选中**。
  const [deselected, setDeselected] = useState<string[]>([])
  const isSelected = (field: PageFillField) => hasValue(field) && !deselected.includes(field.key)
  const selectedCount = merged.filter(isSelected).length

  const toggle = (key: string) =>
    setDeselected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))

  /**
   * 「一键填入」= 选中的**有值**格子 + **参考格**（issue #6529：`value` 为空、`reference` 有值）。
   *
   * 参考格带出去不是"填表"（它的 `value` 就是空的，任何映射函数都写不进表单）——它是
   * 「按名称**查目录**」的输入：订单侧明细正是靠它才对商家说得出「目录里没有这个商品」。
   */
  const handleFill = () =>
    onFill([...merged.filter(isSelected), ...referenceFields(merged)])

  return (
    <div
      data-testid="form-interpret-card"
      className={`w-full rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-3 text-left ${className || ''}`}
    >
      {/* 头部：缩略图 + 一句说明 + 「一键填入」贴右 —— 按钮不再吃掉一整行的高度 */}
      <div className="flex flex-wrap items-center gap-3">
        <Image
          src={resolveImageUrl(imageUrl)}
          alt="识别用的图片"
          width={56}
          height={56}
          unoptimized
          data-testid="form-interpret-thumb"
          className="h-14 w-14 shrink-0 rounded border border-neutral-200 object-cover"
        />
        <p className="min-w-0 flex-1 text-xs leading-5 text-neutral-600">
          识别 + 米宝解读（一次性，不留上下文）。勾选要填的格子，再点「一键填入」；不勾的一律不动。
        </p>
        {/* `type="button"`：本卡片就渲染在**表单里**，缺省 type 会提交表单 */}
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="shrink-0"
          data-testid="form-interpret-fill"
          disabled={selectedCount === 0}
          onClick={handleFill}
        >
          一键填入
        </Button>
      </div>

      {GROUPS.map((group) => {
        const groupFields = merged.filter((field) => sourceGroupOf(field) === group.source)
        // 这一段没有格子就不占版面（有格子的那一段照常显示）
        if (groupFields.length === 0) return null
        return (
          <section
            key={group.source}
            data-testid={group.testid}
            className="mt-3 border-t border-neutral-200/80 pt-2"
          >
            <p className="text-[11px] font-medium text-neutral-500">{group.title}</p>
            {/* 横版铺开：窄屏 1 列 → 中屏 2 列 → 宽屏 3 列（长文本格整行通栏） */}
            <div
              data-testid={`${group.testid}-grid`}
              className="mt-1.5 grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3"
            >
              {groupFields.map((field) => (
                <div
                  key={field.key}
                  data-testid={`form-interpret-field-${field.key}`}
                  className={isWideField(field) ? 'min-w-0 sm:col-span-2 xl:col-span-3' : 'min-w-0'}
                >
                  {hasValue(field) ? (
                    <label className="flex items-start gap-1.5">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        data-testid={`form-interpret-check-${field.key}`}
                        checked={isSelected(field)}
                        onChange={() => toggle(field.key)}
                      />
                      {/* issue #6403 缺陷 2：值可能是 HTML（富文本区的落值口径）⇒ 展示层转可读纯文本；
                          落值一个字不改（`onFill` 回传的仍是原始 HTML） */}
                      <span className="min-w-0 text-xs leading-5 text-neutral-700 whitespace-pre-line break-words">
                        {field.label}：{htmlToPlainText(field.value)}
                      </span>
                    </label>
                  ) : (
                    <div>
                      <p
                        data-testid={`form-interpret-reason-${field.key}`}
                        className="text-xs leading-5 text-neutral-500"
                      >
                        {field.label}：未填（{field.reason || RECOGNIZE_NO_REASON}）
                      </p>
                      {field.reference && (
                        /* 「参考」（issue #6529）：图上读到、但没采纳 —— 如实说清，且**不进表单** */
                        <p
                          data-testid={`form-interpret-reference-${field.key}`}
                          className="text-xs leading-5 text-amber-700"
                        >
                          {field.label}：图上读到（未采纳，仅供查目录）{field.reference}
                        </p>
                      )}
                    </div>
                  )}
                  {field.note && (
                    <p
                      data-testid={`form-interpret-note-${field.key}`}
                      className="ml-5 text-[11px] leading-4 text-neutral-400"
                    >
                      依据：{field.note}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
