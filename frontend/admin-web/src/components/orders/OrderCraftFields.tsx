'use client'

/**
 * 下单页「工艺规格」录入区（issue #4375 包 4b · 设计文档 §4.6 入口 2）。
 *
 * 商家手工录单是布艺商家的主路径（行业 ERP 的订单录入页就是这一页）——
 * 本组件把这页此前**一个都不写**的工艺参数变成可录入项（部位/工艺/加工类型/打开方式/
 * 是否定型/款式/褶距/是否对花 + 19 项部位级特殊选项）。
 *
 * 三条边界：
 * 1. **本组件只录入，不落库**：值的裁剪（缺值不写 / camelCase 键名）在
 *    `lib/order-craft-fields.ts` 的 `buildCraftSpec`，两处不重复一套规则。
 * 2. **不动金额**：拼色/定型/特殊选项加价待 issue #4341 裁定，本组件不显示任何加价。
 * 3. **三态而非布尔**：「是否定型 / 是否对花」的「未指定」与「否」是两个真值 ——
 *    合并会让「没问过」被下游当成「不做定型」。
 */

import { useId } from 'react'
import { Settings2 } from 'lucide-react'
import { Select } from '@/components/ui'
import {
  CRAFT_OPTIONS,
  CURTAIN_TYPE_OPTIONS,
  CUTTING_MODE_OPTIONS,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  SPECIAL_OPTIONS,
  STYLE_MIXED,
  STYLE_OPTIONS,
  type CraftSpecInput,
} from '@/lib/order-craft-fields'

/** 下拉的「未指定」档（值 = 空串 ⇒ 该键不落库） */
const UNSET = { value: '', label: '未指定' }

const toOptions = (values: readonly string[]) => [
  UNSET,
  ...values.map((v) => ({ value: v, label: v })),
]

/** 三态布尔下拉：`''` 未指定 / `'true'` 是 / `'false'` 否 */
const TRI_STATE_OPTIONS = [UNSET, { value: 'true', label: '是' }, { value: 'false', label: '否' }]

const OPEN_COUNT_SELECT_OPTIONS = [
  UNSET,
  ...OPEN_COUNT_OPTIONS.map((o) => ({ value: String(o.value), label: o.label })),
]

/** 三态布尔 → 下拉值 */
const triState = (value: boolean | undefined): string =>
  value === undefined ? '' : String(value)

/** 下拉值 → 三态布尔（`''` ⇒ `undefined`，键不落库） */
const fromTriState = (raw: string): boolean | undefined =>
  raw === '' ? undefined : raw === 'true'

export interface OrderCraftFieldsProps {
  /** 当前录入值（未填的键缺省 ⇒ 不落库） */
  value: CraftSpecInput
  /** 局部更新（只合并传入的键） */
  onChange: (patch: Partial<CraftSpecInput>) => void
  /** 主布米数（= 该行数量）；拼色时作为配布边米数的默认值 */
  mainMeters: number
  /** 配布边米数；`null` = 未改过（跟随主布） */
  edgeMeters: number | null
  onEdgeMetersChange: (meters: number | null) => void
  /** 配布边单价；`null` = 未填（不生成配布边明细行 —— 后端单价必须 > 0，不凭空造价） */
  edgeUnitPrice: number | null
  onEdgeUnitPriceChange: (price: number | null) => void
}

export default function OrderCraftFields({
  value,
  onChange,
  mainMeters,
  edgeMeters,
  onEdgeMetersChange,
  edgeUnitPrice,
  onEdgeUnitPriceChange,
}: OrderCraftFieldsProps) {
  const uid = useId().replace(/:/g, '')
  const fieldId = (name: string) => `craft-${uid}-${name}`

  /** 数字输入：空串 / 非法 ⇒ `null`（键不落库）；否则正有限数 */
  const numberOrNull = (raw: string): number | null => {
    if (raw.trim() === '') return null
    const parsed = Number(raw)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }

  const labelClass = 'block text-sm font-medium text-neutral-700 mb-1.5'
  const inputClass =
    'w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'

  const isMixed = value.style === STYLE_MIXED
  const metersSource = edgeMeters === null ? METERS_SOURCE_FOLLOW : METERS_SOURCE_MANUAL
  const effectiveEdgeMeters = edgeMeters ?? (Number(mainMeters) || 0)

  const toggleOption = (option: string) => {
    const current = value.specialOptions ?? []
    const next = current.includes(option)
      ? current.filter((o) => o !== option)
      : [...current, option]
    onChange({ specialOptions: next })
  }

  return (
    <div className="pt-2 border-t border-neutral-100">
      <div className="flex items-center gap-2 mb-3">
        <Settings2 className="w-4 h-4 text-neutral-500" />
        <span className="text-sm font-medium text-neutral-700">工艺规格（可选）</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div>
          <label htmlFor={fieldId('curtainType')} className={labelClass}>
            部位
          </label>
          <Select
            id={fieldId('curtainType')}
            options={toOptions(CURTAIN_TYPE_OPTIONS)}
            value={value.curtainType ?? ''}
            onChange={(e) => onChange({ curtainType: e.target.value || undefined })}
          />
        </div>

        <div>
          <label htmlFor={fieldId('craft')} className={labelClass}>
            工艺
          </label>
          <Select
            id={fieldId('craft')}
            options={toOptions(CRAFT_OPTIONS)}
            value={value.craft ?? ''}
            onChange={(e) => onChange({ craft: e.target.value || undefined })}
          />
        </div>

        <div>
          <label htmlFor={fieldId('cuttingMode')} className={labelClass}>
            加工类型
          </label>
          <Select
            id={fieldId('cuttingMode')}
            options={toOptions(CUTTING_MODE_OPTIONS)}
            value={value.cuttingMode ?? ''}
            onChange={(e) => onChange({ cuttingMode: e.target.value || undefined })}
          />
        </div>

        <div>
          <label htmlFor={fieldId('openCount')} className={labelClass}>
            打开方式
          </label>
          <Select
            id={fieldId('openCount')}
            options={OPEN_COUNT_SELECT_OPTIONS}
            value={value.openCount ? String(value.openCount) : ''}
            onChange={(e) =>
              onChange({ openCount: e.target.value === '' ? undefined : Number(e.target.value) })
            }
          />
        </div>

        <div>
          <label htmlFor={fieldId('isShaped')} className={labelClass}>
            是否定型
          </label>
          <Select
            id={fieldId('isShaped')}
            options={TRI_STATE_OPTIONS}
            value={triState(value.isShaped)}
            onChange={(e) => onChange({ isShaped: fromTriState(e.target.value) })}
          />
        </div>

        <div>
          <label htmlFor={fieldId('style')} className={labelClass}>
            款式
          </label>
          <Select
            id={fieldId('style')}
            options={toOptions(STYLE_OPTIONS)}
            value={value.style ?? ''}
            onChange={(e) => onChange({ style: e.target.value || undefined })}
          />
        </div>

        <div>
          <label htmlFor={fieldId('pleatSpacing')} className={labelClass}>
            褶距
          </label>
          <input
            id={fieldId('pleatSpacing')}
            type="number"
            min={0}
            step={0.01}
            placeholder="米，如 0.1"
            value={value.pleatSpacing ?? ''}
            onChange={(e) => onChange({ pleatSpacing: numberOrNull(e.target.value) ?? undefined })}
            className={inputClass}
          />
        </div>

        <div>
          <label htmlFor={fieldId('hasPattern')} className={labelClass}>
            是否对花
          </label>
          <Select
            id={fieldId('hasPattern')}
            options={TRI_STATE_OPTIONS}
            value={triState(value.hasPattern)}
            onChange={(e) => onChange({ hasPattern: fromTriState(e.target.value) })}
          />
        </div>

        {/* 花距只在「对花 = 是」时才有意义（对花为否时留着会让下游多算一个花距） */}
        {value.hasPattern === true && (
          <div>
            <label htmlFor={fieldId('patternRepeat')} className={labelClass}>
              花距
            </label>
            <input
              id={fieldId('patternRepeat')}
              type="number"
              min={0}
              step={0.01}
              placeholder="米，如 0.6"
              value={value.patternRepeat ?? ''}
              onChange={(e) => onChange({ patternRepeat: numberOrNull(e.target.value) ?? undefined })}
              className={inputClass}
            />
          </div>
        )}
      </div>

      {/* 特殊选项：部位级多选（toggle 按钮，与页面既有的按钮组选择同款；不用 checkbox
          以免与「加工选项」的勾选控件在选择器上争用） */}
      <div className="mt-4">
        <span className={labelClass}>特殊选项（部位级，可多选）</span>
        <div className="flex flex-wrap gap-2">
          {SPECIAL_OPTIONS.map((option) => {
            const active = (value.specialOptions ?? []).includes(option)
            return (
              <button
                key={option}
                type="button"
                aria-pressed={active}
                onClick={() => toggleOption(option)}
                className={
                  'h-8 px-2.5 rounded border text-xs transition-colors ' +
                  (active
                    ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                    : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                }
              >
                {option}
              </button>
            )
          })}
        </div>
      </div>

      {/* 双拼（拼色）：配布边是**一条独立面料明细行**（§4.8） */}
      {isMixed && (
        <div className="mt-4 rounded-lg border border-neutral-200 bg-neutral-50/60 p-3">
          <div className="text-sm font-medium text-neutral-700 mb-2">
            双拼 · 配布边（§4.8：一扇窗 = 主布行 + 配布边行）
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor={fieldId('edgeMeters')} className={labelClass}>
                配布边米数
              </label>
              <input
                id={fieldId('edgeMeters')}
                type="number"
                min={0}
                step={0.01}
                value={effectiveEdgeMeters}
                onChange={(e) => onEdgeMetersChange(numberOrNull(e.target.value))}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-neutral-400">默认 = 主布米数，可编辑</p>
              <p className="mt-0.5 text-xs text-neutral-500">
                配布边米数来源：{metersSource}
              </p>
            </div>
            <div>
              <label htmlFor={fieldId('edgeUnitPrice')} className={labelClass}>
                配布边单价
              </label>
              <input
                id={fieldId('edgeUnitPrice')}
                type="number"
                min={0}
                step={0.01}
                placeholder="¥ / 米"
                value={edgeUnitPrice ?? ''}
                onChange={(e) => onEdgeUnitPriceChange(numberOrNull(e.target.value))}
                className={inputClass}
              />
              <p className="mt-1 text-xs text-neutral-400">
                填写后才会生成配布边明细行（配布用料加价口径待客户裁定，不凭空造价）
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
