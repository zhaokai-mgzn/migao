'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Check, X, ChevronRight } from 'lucide-react'
import type { InteractiveComponent, InteractiveOption, InteractiveFormField } from '@/types'
import { useChatStore } from '@/store/chat'

interface Props {
  interactive: InteractiveComponent
  disabled?: boolean  // 已回复后禁止再次点击
}

export default function InteractiveMessage({ interactive, disabled }: Props) {
  if (interactive.component === 'choice') {
    return <ChoiceCard interactive={interactive} disabled={disabled} />
  }
  if (interactive.component === 'confirm') {
    return <ConfirmCard interactive={interactive} disabled={disabled} />
  }
  if (interactive.component === 'form') {
    return <FormCard interactive={interactive} disabled={disabled} />
  }
  return null
}

/**
 * 选项卡片 — 单选/多选按钮
 */
function ChoiceCard({ interactive, disabled }: Props) {
  const { sendMessage } = useChatStore()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [submitted, setSubmitted] = useState(false)

  const options = Array.isArray(interactive.options) ? interactive.options : []
  const multi = interactive.multiSelect || false

  const toggleOption = (value: string) => {
    if (submitted || disabled) return
    if (multi) {
      setSelected(prev => {
        const next = new Set(prev)
        if (next.has(value)) next.delete(value)
        else next.add(value)
        return next
      })
    } else {
      setSelected(new Set([value]))
    }
  }

  const submitChoice = () => {
    if (selected.size === 0) return
    const values = Array.from(selected).join('、')
    setSubmitted(true)
    sendMessage(values)
  }

  return (
    <div className="mt-2 border border-primary-200 rounded-xl overflow-hidden bg-white shadow-sm">
      {/* 标题 */}
      <div className="px-3 py-2 bg-primary-50 border-b border-primary-100">
        <p className="text-xs font-medium text-primary-700">{interactive.title}</p>
      </div>

      {/* 选项列表 */}
      <div className="p-2 space-y-1">
        {options.map((opt: InteractiveOption) => {
          const isSelected = selected.has(opt.value)
          return (
            <button
              key={opt.value}
              onClick={() => toggleOption(opt.value)}
              disabled={submitted || disabled}
              className={cn(
                'w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left text-sm transition-colors',
                isSelected
                  ? 'bg-primary-100 border border-primary-300 text-primary-800'
                  : 'bg-gray-50 border border-gray-100 text-gray-700 hover:bg-gray-100',
                (submitted || disabled) && 'opacity-60 cursor-not-allowed'
              )}
            >
              <span className="flex-1">
                <span className="font-medium">{opt.label}</span>
                {opt.description && (
                  <span className="ml-1.5 text-xs text-gray-400">{opt.description}</span>
                )}
              </span>
              {isSelected && <Check className="w-4 h-4 text-primary-600 flex-shrink-0" />}
            </button>
          )
        })}
      </div>

      {/* 确认按钮 */}
      {!submitted && (
        <div className="px-3 py-2 border-t border-gray-100 flex justify-end">
          <button
            onClick={submitChoice}
            disabled={selected.size === 0}
            className={cn(
              'flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              selected.size > 0
                ? 'bg-primary-600 text-white hover:bg-primary-700'
                : 'bg-gray-100 text-gray-400 cursor-not-allowed'
            )}
          >
            {multi ? '确认选择' : '确认'}
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * 确认卡片 — 展示信息 + 确认/取消
 */
function ConfirmCard({ interactive, disabled }: Props) {
  const { sendMessage } = useChatStore()
  const [submitted, setSubmitted] = useState(false)

  const fields = Array.isArray(interactive.fields) ? interactive.fields : []
  const confirmLabel = interactive.confirmLabel || '确认'
  const cancelLabel = interactive.cancelLabel || '取消'
  const confirmValue = interactive.confirmValue || '确认'
  const cancelValue = interactive.cancelValue || '取消'

  const handleAction = (value: string) => {
    if (submitted || disabled) return
    setSubmitted(true)
    sendMessage(value)
  }

  return (
    <div className="mt-2 border border-amber-200 rounded-xl overflow-hidden bg-white shadow-sm">
      {/* 标题 */}
      <div className="px-3 py-2 bg-amber-50 border-b border-amber-100">
        <p className="text-xs font-medium text-amber-700">{interactive.title}</p>
      </div>

      {/* 字段列表 */}
      <div className="p-3 space-y-2">
        {fields.map((field, i) => (
          <div key={i} className="flex items-center text-sm">
            <span className="text-gray-400 w-16 flex-shrink-0 text-xs">{field.label}</span>
            <span className="text-gray-800 font-medium ml-2">{field.value}</span>
          </div>
        ))}
      </div>

      {/* 操作按钮 */}
      {!submitted && (
        <div className="px-3 py-2 border-t border-gray-100 flex gap-2 justify-end">
          <button
            onClick={() => handleAction(cancelValue)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors"
          >
            <X className="w-3 h-3" />
            {cancelLabel}
          </button>
          <button
            onClick={() => handleAction(confirmValue)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-500 text-white hover:bg-amber-600 transition-colors"
          >
            <Check className="w-3 h-3" />
            {confirmLabel}
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * 内联表单 — 一次性收集多个信息字段
 * 用于图片识别后预填已知信息，让用户补充/确认缺失字段后一次性提交
 */
function FormCard({ interactive, disabled }: Props) {
  const { sendMessage } = useChatStore()
  const formFields = Array.isArray(interactive.formFields) ? interactive.formFields : []
  const submitLabel = interactive.submitLabel || '提交'

  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const f of formFields) {
      initial[f.key] = f.value || ''
    }
    return initial
  })
  const [submitted, setSubmitted] = useState(false)

  const setField = (key: string, val: string) => {
    if (submitted || disabled) return
    setValues(prev => ({ ...prev, [key]: val }))
  }

  const handleSubmit = () => {
    if (submitted || disabled) return
    // 构建结构化提交文本：每行 "label: value"
    const lines = formFields
      .map(f => `${f.label}: ${values[f.key] || '（未填写）'}`)
      .join('\n')
    setSubmitted(true)
    sendMessage(lines)
  }

  return (
    <div className="mt-2 border border-green-200 rounded-xl overflow-hidden bg-white shadow-sm">
      {/* 标题 */}
      <div className="px-3 py-2 bg-green-50 border-b border-green-100">
        <p className="text-xs font-medium text-green-700">{interactive.title}</p>
      </div>

      {/* 表单字段 */}
      <div className="p-3 space-y-2.5">
        {formFields.map((field: InteractiveFormField) => (
          <div key={field.key}>
            <label className="block text-xs text-gray-500 mb-1">
              {field.label}
              {field.required && <span className="text-red-400 ml-0.5">*</span>}
            </label>
            <input
              type="text"
              value={values[field.key] || ''}
              onChange={e => setField(field.key, e.target.value)}
              placeholder={field.placeholder || `请输入${field.label}`}
              disabled={submitted || disabled}
              className={cn(
                'w-full px-2.5 py-1.5 rounded-lg border text-sm transition-colors',
                'focus:outline-none focus:ring-1 focus:ring-green-400 focus:border-green-400',
                (submitted || disabled)
                  ? 'bg-gray-50 border-gray-200 text-gray-400'
                  : 'bg-white border-gray-200 text-gray-800'
              )}
            />
          </div>
        ))}
      </div>

      {/* 提交按钮 */}
      {!submitted && (
        <div className="px-3 py-2 border-t border-gray-100 flex justify-end">
          <button
            onClick={handleSubmit}
            disabled={disabled}
            className={cn(
              'flex items-center gap-1 px-4 py-1.5 rounded-lg text-xs font-medium transition-colors',
              disabled
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                : 'bg-green-600 text-white hover:bg-green-700'
            )}
          >
            <Check className="w-3 h-3" />
            {submitLabel}
          </button>
        </div>
      )}
    </div>
  )
}
