import { useState } from 'react'
import { View, Text, Input, Textarea } from '@tarojs/components'
import type { InteractiveData } from '../../types'
import './FormCard.scss'

interface FormCardProps {
  data: InteractiveData
  onAction: (value: string) => void
}

/** 字段值集合：field.key -> 用户输入 */
type FieldValues = Record<string, string>

/** 校验错误集合：field.key -> 错误文案 */
type FieldErrors = Record<string, string>

// key 启发式判定字段类型（interact form 契约无显式 type，按语义 key 推断）
const PHONE_KEYS = ['phone', 'mobile']
const NUMBER_KEYS = ['quantity', 'price', 'amount', 'stock', 'width', 'height', 'meter', 'count', 'num']
const ADDRESS_KEYS = ['address', 'addr', 'detail']

function isPhoneKey(key: string): boolean {
  return PHONE_KEYS.some((k) => key.toLowerCase().includes(k))
}

function isNumberKey(key: string): boolean {
  return NUMBER_KEYS.some((k) => key.toLowerCase().includes(k))
}

function isAddressKey(key: string): boolean {
  return ADDRESS_KEYS.some((k) => key.toLowerCase().includes(k))
}

/** 单字段校验：必填 + 手机号 + 数字 */
function validateField(key: string, label: string, value: string, required: boolean): string {
  const v = (value || '').trim()
  if (required && !v) return `${label}为必填项`
  if (!v) return ''
  if (isPhoneKey(key)) {
    if (!/^1[3-9]\d{9}$/.test(v)) return '请输入 11 位手机号'
  }
  if (isNumberKey(key)) {
    const n = Number(v)
    if (Number.isNaN(n) || n <= 0) return '请输入大于 0 的数字'
  }
  return ''
}

/**
 * 表单卡片：多字段信息收集（interact form 组件）
 *
 * 用户填写后点击提交，序列化为 `__FORM__|{json}` 回传（后端注入本轮 LLM 上下文，
 * 与 __PAGE__ 分页协议同一类结构化交互协议）。
 *
 * 数据安全：
 * - 手机号字段数字键盘 + 长度限制 11
 * - 提交前本地校验（必填/手机号/数字），错误不发送
 * - 地址字段用多行输入，防超长粘贴（maxlength 200）
 */
export default function FormCard({ data, onAction }: FormCardProps) {
  const fields = data.formFields || []
  const [values, setValues] = useState<FieldValues>(() => {
    const init: FieldValues = {}
    for (const f of fields) init[f.key] = f.value || ''
    return init
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [submitting, setSubmitting] = useState(false)

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    // 输入变化时清除该字段错误
    setErrors((prev) => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const handleSubmit = () => {
    if (submitting) return
    // 全量校验：任一错误则不提交
    const errs: FieldErrors = {}
    for (const f of fields) {
      const e = validateField(f.key, f.label, values[f.key] || '', !!f.required)
      if (e) errs[f.key] = e
    }
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    setSubmitting(true)
    try {
      const payload = JSON.stringify(values)
      onAction(`__FORM__|${payload}`)
    } finally {
      // 提交后不重置 submitting（消息已发出，卡片保留展示）
      setSubmitting(false)
    }
  }

  return (
    <View className='form-card'>
      <Text className='form-card__title'>{data.title}</Text>

      <View className='form-card__fields'>
        {fields.map((field, idx) => {
          const value = values[field.key] || ''
          const error = errors[field.key]
          const isPhone = isPhoneKey(field.key)
          const isNumber = isNumberKey(field.key)
          const isAddress = isAddressKey(field.key)
          const inputType = isNumber ? 'number' : 'text'

          return (
            <View key={`ff-${idx}`} className={`form-card__field${error ? ' form-card__field--error' : ''}`}>
              <View className='form-card__field-label-row'>
                <Text className='form-card__field-label'>
                  {field.required && <Text className='form-card__required'>*</Text>}
                  {field.label}
                </Text>
                {error && <Text className='form-card__field-error'>{error}</Text>}
              </View>
              {isAddress ? (
                <Textarea
                  className='form-card__input form-card__input--textarea'
                  value={value}
                  placeholder={field.placeholder || `请输入${field.label}`}
                  maxlength={200}
                  autoHeight
                  onInput={(e) => handleChange(field.key, e.detail.value)}
                />
              ) : (
                <Input
                  className='form-card__input'
                  value={value}
                  type={inputType}
                  placeholder={field.placeholder || `请输入${field.label}`}
                  maxlength={isPhone ? 11 : 100}
                  onInput={(e) => handleChange(field.key, e.detail.value)}
                />
              )}
            </View>
          )
        })}
      </View>

      <View className='form-card__actions'>
        <View
          className='form-card__submit'
          onClick={handleSubmit}
          hoverClass='form-card__submit--hover'
        >
          <Text className='form-card__submit-text'>{data.submitLabel || '提交'}</Text>
        </View>
        {data.cancelLabel && (
          <View
            className='form-card__cancel'
            onClick={() => onAction(data.cancelValue || '取消')}
            hoverClass='form-card__cancel--hover'
          >
            <Text className='form-card__cancel-text'>{data.cancelLabel}</Text>
          </View>
        )}
      </View>
    </View>
  )
}
