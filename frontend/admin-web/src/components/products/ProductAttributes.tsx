'use client'

import { useEffect, useState } from 'react'
import { Input, Select } from '@/components/ui'

interface ProductAttributesProps {
  value: {
    skuCode: string
    brand: string
    unit: string
    specifications: Record<string, string>
  }
  onChange: (patch: {
    skuCode?: string
    brand?: string
    unit?: string
    specifications?: Record<string, string>
  }) => void
  errors?: {
    skuCode?: string
    unit?: string
  }
}

/**
 * 属性 key 与 PRD 截图保持一致：
 * - 货号(skuCode)、品牌(brand)、计价单位(unit) 落入根字段
 * - 其余落入 specifications: { weight, material, function, craft, style, pattern }
 */
const CUSTOM = '__custom__'

const BRAND_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '无品牌', label: '无品牌' },
  { value: '米高', label: '米高' },
  { value: CUSTOM, label: '其他（自定义输入）' },
]
const BRAND_BUILTIN = new Set(['无品牌', '米高'])

const UNIT_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '米', label: '米' },
  { value: '卷', label: '卷' },
  { value: '件', label: '件' },
  { value: '套', label: '套' },
  { value: '平方米', label: '平方米' },
]

const WEIGHT_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '100g以下', label: '100g以下' },
  { value: '100-200g', label: '100-200g' },
  { value: '200-300g', label: '200-300g' },
  { value: '300-400g', label: '300-400g' },
  { value: '400g以上', label: '400g以上' },
  { value: CUSTOM, label: '其他' },
]

const MATERIAL_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '涤纶', label: '涤纶' },
  { value: '棉', label: '棉' },
  { value: '麻', label: '麻' },
  { value: '丝绸', label: '丝绸' },
  { value: '混纺', label: '混纺' },
  { value: '绒布', label: '绒布' },
  { value: '雪尼尔', label: '雪尼尔' },
  { value: CUSTOM, label: '其他' },
]

const FUNCTION_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '遮光', label: '遮光' },
  { value: '隔热', label: '隔热' },
  { value: '防紫外线', label: '防紫外线' },
  { value: '防水', label: '防水' },
  { value: '防霉', label: '防霉' },
  { value: '隔音', label: '隔音' },
  { value: CUSTOM, label: '其他' },
]

const CRAFT_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '提花', label: '提花' },
  { value: '印花', label: '印花' },
  { value: '绣花', label: '绣花' },
  { value: '烫金', label: '烫金' },
  { value: '植绒', label: '植绒' },
  { value: '色织', label: '色织' },
  { value: CUSTOM, label: '其他' },
]

const STYLE_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '现代简约', label: '现代简约' },
  { value: '北欧', label: '北欧' },
  { value: '中式', label: '中式' },
  { value: '欧式', label: '欧式' },
  { value: '田园', label: '田园' },
  { value: '轻奢', label: '轻奢' },
  { value: CUSTOM, label: '其他' },
]

const PATTERN_OPTIONS = [
  { value: '', label: '请选择' },
  { value: '纯色', label: '纯色' },
  { value: '条纹', label: '条纹' },
  { value: '格子', label: '格子' },
  { value: '花卉', label: '花卉' },
  { value: '几何', label: '几何' },
  { value: '卡通', label: '卡通' },
  { value: CUSTOM, label: '其他' },
]

interface FieldCellProps {
  label: string
  required?: boolean
  error?: string
  children: React.ReactNode
}

/** 标签左、控件右的横向字段单元（PRD 风格） */
function FieldCell({ label, required, error, children }: FieldCellProps) {
  return (
    <div>
      <div className="flex items-center gap-3">
        <label className="shrink-0 w-[72px] text-sm text-gray-600 text-right leading-9">
          {required && <span className="text-red-500 mr-0.5">*</span>}
          {label}
        </label>
        <div className="flex-1 min-w-0">{children}</div>
      </div>
      {error && <p className="ml-[84px] mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

interface AttrSelectInputProps {
  label: string
  required?: boolean
  options: { value: string; label: string }[]
  builtinValues: Set<string>
  value: string
  onChange: (v: string) => void
  error?: string
  customPlaceholder?: string
}

/** “内置选项 + 其他自定义” 组合控件 */
function AttrSelectInput({
  label,
  required,
  options,
  builtinValues,
  value,
  onChange,
  error,
  customPlaceholder = '请输入自定义内容',
}: AttrSelectInputProps) {
  // 是否处于自定义模式：值非空且不在内置中 -> 自定义；
  // 用户主动选择“其他”时由本地 state 显式标记为自定义模式
  const externallyCustom = !!value && !builtinValues.has(value)
  const [customMode, setCustomMode] = useState<boolean>(externallyCustom)

  // 外部 value 变化时同步
  useEffect(() => {
    if (externallyCustom) setCustomMode(true)
  }, [externallyCustom])

  const isCustom = customMode || externallyCustom

  return (
    <FieldCell label={label} required={required} error={error}>
      {isCustom ? (
        <div className="flex items-center gap-1.5">
          <Input
            value={value}
            placeholder={customPlaceholder}
            onChange={(e) => onChange(e.target.value)}
            className="flex-1"
          />
          <button
            type="button"
            onClick={() => {
              setCustomMode(false)
              onChange('')
            }}
            className="shrink-0 h-9 px-2 text-xs text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded"
            title="重新选择"
          >
            换一项
          </button>
        </div>
      ) : (
        <Select
          options={options}
          value={builtinValues.has(value) ? value : ''}
          placeholder="请选择"
          onChange={(e) => {
            const v = e.target.value
            if (v === CUSTOM) {
              setCustomMode(true)
              onChange('')
            } else {
              setCustomMode(false)
              onChange(v)
            }
          }}
        />
      )}
    </FieldCell>
  )
}

// 各属性的内置值集合（用于判断是否处于自定义模式）
const buildBuiltin = (opts: { value: string }[]) =>
  new Set(opts.map((o) => o.value).filter((v) => v && v !== CUSTOM))

const WEIGHT_BUILTIN = buildBuiltin(WEIGHT_OPTIONS)
const MATERIAL_BUILTIN = buildBuiltin(MATERIAL_OPTIONS)
const FUNCTION_BUILTIN = buildBuiltin(FUNCTION_OPTIONS)
const CRAFT_BUILTIN = buildBuiltin(CRAFT_OPTIONS)
const STYLE_BUILTIN = buildBuiltin(STYLE_OPTIONS)
const PATTERN_BUILTIN = buildBuiltin(PATTERN_OPTIONS)
const UNIT_BUILTIN = buildBuiltin(UNIT_OPTIONS)

export default function ProductAttributes({
  value,
  onChange,
  errors,
}: ProductAttributesProps) {
  const { skuCode, brand, unit, specifications } = value

  const setSpec = (key: string, v: string) => {
    const next = { ...specifications }
    if (v) next[key] = v
    else delete next[key]
    onChange({ specifications: next })
  }

  // 品牌：单独处理（含“无品牌”/“米高”内置）
  const externalBrandCustom = !!brand && !BRAND_BUILTIN.has(brand)
  const [brandCustomMode, setBrandCustomMode] = useState<boolean>(externalBrandCustom)
  useEffect(() => {
    if (externalBrandCustom) setBrandCustomMode(true)
  }, [externalBrandCustom])
  const isBrandCustom = brandCustomMode || externalBrandCustom

  return (
    <div id="pf-unit">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-x-8 gap-y-4">
        {/* 第 1 行：货号 / 品牌 / 计价单位 */}
        <FieldCell label="货号" required error={errors?.skuCode}>
          <Input
            placeholder="请输入商品货号"
            maxLength={30}
            value={skuCode}
            onChange={(e) => onChange({ skuCode: e.target.value })}
          />
        </FieldCell>

        <FieldCell label="品牌">
          {isBrandCustom ? (
            <div className="flex items-center gap-1.5">
              <Input
                value={brand}
                placeholder="请输入品牌名称"
                onChange={(e) => onChange({ brand: e.target.value })}
                className="flex-1"
              />
              <button
                type="button"
                onClick={() => {
                  setBrandCustomMode(false)
                  onChange({ brand: '' })
                }}
                className="shrink-0 h-9 px-2 text-xs text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded"
              >
                换一项
              </button>
            </div>
          ) : (
            <Select
              options={BRAND_OPTIONS}
              value={BRAND_BUILTIN.has(brand) ? brand : ''}
              placeholder="请选择"
              onChange={(e) => {
                const v = e.target.value
                if (v === CUSTOM) {
                  setBrandCustomMode(true)
                  onChange({ brand: '' })
                } else {
                  setBrandCustomMode(false)
                  onChange({ brand: v })
                }
              }}
            />
          )}
        </FieldCell>

        <AttrSelectInput
          label="计价单位"
          required
          options={UNIT_OPTIONS}
          builtinValues={UNIT_BUILTIN}
          value={unit}
          onChange={(v) => onChange({ unit: v })}
          error={errors?.unit}
        />

        {/* 第 2 行：克重 / 材质 / 功能 */}
        <AttrSelectInput
          label="克重"
          options={WEIGHT_OPTIONS}
          builtinValues={WEIGHT_BUILTIN}
          value={specifications.weight || ''}
          onChange={(v) => setSpec('weight', v)}
        />
        <AttrSelectInput
          label="材质"
          options={MATERIAL_OPTIONS}
          builtinValues={MATERIAL_BUILTIN}
          value={specifications.material || ''}
          onChange={(v) => setSpec('material', v)}
        />
        <AttrSelectInput
          label="功能"
          options={FUNCTION_OPTIONS}
          builtinValues={FUNCTION_BUILTIN}
          value={specifications.function || ''}
          onChange={(v) => setSpec('function', v)}
        />

        {/* 第 3 行：工艺 / 风格 / 图案 */}
        <AttrSelectInput
          label="工艺"
          options={CRAFT_OPTIONS}
          builtinValues={CRAFT_BUILTIN}
          value={specifications.craft || ''}
          onChange={(v) => setSpec('craft', v)}
        />
        <AttrSelectInput
          label="风格"
          options={STYLE_OPTIONS}
          builtinValues={STYLE_BUILTIN}
          value={specifications.style || ''}
          onChange={(v) => setSpec('style', v)}
        />
        <AttrSelectInput
          label="图案"
          options={PATTERN_OPTIONS}
          builtinValues={PATTERN_BUILTIN}
          value={specifications.pattern || ''}
          onChange={(v) => setSpec('pattern', v)}
        />
      </div>
    </div>
  )
}
