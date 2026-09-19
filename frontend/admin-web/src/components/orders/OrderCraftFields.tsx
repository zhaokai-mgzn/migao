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
 *
 * ── 展示重构（issue #4420，用户 2026-09-19：「信息偏多，不能全部挤在一块区域」）──
 *
 * 录入项本身一个没减（8 个下拉 + 19 项特殊选项 + 拼色配布边），改的是**信息层次**：
 * ① 8 个主工艺参数留在**首屏常显**（录单主路径，不该藏）；
 * ② 19 项特殊选项收进**可展开区**（长尾选项，展开前只显示「已选 N 项」摘要）；
 * ③ 每个区块有**标题 + 一句话说明**，不再是一个大 grid 平铺。
 *
 * ── 交互改造（issue #4489，用户 2026-09-19：「现在要一个个点过去」）──────────────
 *
 * 病根：8 个字段都是**下拉** ⇒ 每个都要「点开 → 点选项」两步（最多 16 次点击）。
 * ① 枚举字段改 **chips**（一击即中，省掉「展开」那一步）；三态字段用**三段分段按钮**，
 *    「未指定」档保留（三态硬约束不变）；
 * ② 部位 → 是否定型 的**联动默认**（真值源见 `IS_SHAPED_DEFAULT_BY_CURTAIN_TYPE`）；
 * ③ **手改留痕**：手改过的「是否定型」不再被部位联动覆盖（同 #4434 纪律）。
 *
 * ⚠️ **落库一字未动**：chips 与下拉写的是**同一份** `CraftSpecInput` 键，
 * `lib/order-craft-fields.ts` 的 `buildCraftSpec` 不因本改造改一个字符。
 */

import { useId, useState } from 'react'
import { ChevronDown, ChevronRight, Settings2 } from 'lucide-react'
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

const LABEL_CLASS = 'block text-sm font-medium text-neutral-700 mb-1.5'

/** 一个 chip 档：`value === undefined` 即「未指定」档（该键不落库） */
interface ChipOption<T> {
  value: T
  label: string
}

/** 枚举字段的 chips（含「未指定」档） */
const toChipOptions = (values: readonly string[]): ChipOption<string | undefined>[] => [
  { value: undefined, label: '未指定' },
  ...values.map((v) => ({ value: v, label: v })),
]

/** 打开方式 chips：开数是数字（`openCount` 落库为 number），文案取自 `craft-display` 单一真值 */
const OPEN_COUNT_CHIPS: ChipOption<number | undefined>[] = [
  { value: undefined, label: '未指定' },
  ...OPEN_COUNT_OPTIONS.map((o) => ({ value: o.value, label: o.label })),
]

/**
 * 三态 chips（`undefined` 未指定 / `true` 是 / `false` 否）——**三段，不合并**。
 *
 * 「没问过」与「否」是两个真值：合并会让下游把「没问过」当成「不做定型」。
 */
const TRI_STATE_CHIPS: ChipOption<boolean | undefined>[] = [
  { value: undefined, label: '未指定' },
  { value: true, label: '是' },
  { value: false, label: '否' },
]

/**
 * 单选 chips 组（issue #4489）——**一击即中**：一眼全见，点一下即选，省掉下拉「先展开再选」。
 *
 * 语义用 `radiogroup` / `radio`（单选 + 可聚焦），不用 listbox：
 * `aria-checked` 让「未指定」与「否」在无障碍树上也是两个不同档（三态字段的硬约束）。
 */
function ChipGroup<T>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: ReadonlyArray<ChipOption<T>>
  value: T
  onChange: (next: T) => void
}) {
  return (
    <div>
      <div className={LABEL_CLASS}>{label}</div>
      <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const active = option.value === value
          return (
            <button
              key={option.label}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(option.value)}
              className={
                'h-9 px-3 rounded border text-sm transition-colors ' +
                (active
                  ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                  : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
              }
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * 部位 → 是否定型 的**联动默认档**（issue #4489）。
 *
 * 真值源（不是我发明的）：`backend/ai-agent-service/app/clarification/curtain_checklist.py`
 * 的 `is_shaped.default_rule = curtain_type`，note 原文
 * 「布帘默认是/纱帘默认否/帘头是（面料红线：真丝等不耐高温须不定型）」；
 * `docs/curtain-fabric-quote-rules.md` §10 同口径。
 *
 * 表外的部位取值（如将来新增）⇒ **不猜**：不给默认（`undefined`），商家自己选。
 */
const IS_SHAPED_DEFAULT_BY_CURTAIN_TYPE: Record<string, boolean> = {
  布帘: true,
  纱帘: false,
  帘头: true,
}

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

  const inputClass =
    'w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'

  const isMixed = value.style === STYLE_MIXED
  const metersSource = edgeMeters === null ? METERS_SOURCE_FOLLOW : METERS_SOURCE_MANUAL
  const effectiveEdgeMeters = edgeMeters ?? (Number(mainMeters) || 0)

  /** 特殊选项默认收起（issue #4420）：19 项长尾选项是密度主因，展开前只报「已选 N 项」 */
  const [specialOpen, setSpecialOpen] = useState(false)
  const selectedSpecialCount = (value.specialOptions ?? []).length

  /**
   * 「是否定型」是否已被**用户/上游**定过（手改留痕，同 #4434）——
   * 定过 ⇒ 改部位**不得**覆盖它（手改过的值只能由用户显式改回）。
   *
   * 初值取 `value.isShaped !== undefined`：编辑存量行时该值也是**已定的真值**，
   * 不能因为「不是本次会话点的」就被部位联动冲掉。
   */
  const [isShapedTouched, setIsShapedTouched] = useState(value.isShaped !== undefined)

  const changeCurtainType = (next: string | undefined) => {
    const patch: Partial<CraftSpecInput> = { curtainType: next }
    // 联动只在「没被定过」时生效；部位回到「未指定」⇒ 不动已联动的值（不删商家已见到的真值）
    const linked = next === undefined ? undefined : IS_SHAPED_DEFAULT_BY_CURTAIN_TYPE[next]
    if (!isShapedTouched && linked !== undefined) patch.isShaped = linked
    onChange(patch)
  }

  const changeIsShaped = (next: boolean | undefined) => {
    setIsShapedTouched(true)
    onChange({ isShaped: next })
  }

  const toggleOption = (option: string) => {
    const current = value.specialOptions ?? []
    const next = current.includes(option)
      ? current.filter((o) => o !== option)
      : [...current, option]
    onChange({ specialOptions: next })
  }

  return (
    <div className="pt-3 mt-1 border-t border-neutral-100">
      <div className="flex items-center gap-2 mb-1">
        <Settings2 className="w-4 h-4 text-neutral-500" />
        <span className="text-sm font-medium text-neutral-700">工艺规格</span>
        <span className="text-xs text-neutral-400">（不填则按行业默认）</span>
      </div>
      <p className="mb-3 text-xs text-neutral-400">
        加工类型默认「定高买宽」、款式默认「单色」、褶距按标准档 2.0 倍自动算 —— 都可改
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* 选部位会带出「是否定型」的行业默认（布帘是 / 纱帘否），手改过就不再覆盖 */}
        <ChipGroup
          label="部位"
          options={toChipOptions(CURTAIN_TYPE_OPTIONS)}
          value={value.curtainType}
          onChange={changeCurtainType}
        />

        <ChipGroup
          label="工艺"
          options={toChipOptions(CRAFT_OPTIONS)}
          value={value.craft}
          onChange={(next) => onChange({ craft: next })}
        />

        <ChipGroup
          label="加工类型"
          options={toChipOptions(CUTTING_MODE_OPTIONS)}
          value={value.cuttingMode}
          onChange={(next) => onChange({ cuttingMode: next })}
        />

        <ChipGroup
          label="打开方式"
          options={OPEN_COUNT_CHIPS}
          value={value.openCount}
          onChange={(next) => onChange({ openCount: next })}
        />

        <ChipGroup
          label="是否定型"
          options={TRI_STATE_CHIPS}
          value={value.isShaped}
          onChange={changeIsShaped}
        />

        <ChipGroup
          label="款式"
          options={toChipOptions(STYLE_OPTIONS)}
          value={value.style}
          onChange={(next) => onChange({ style: next })}
        />

        <div>
          <label htmlFor={fieldId('pleatSpacing')} className={LABEL_CLASS}>
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

        <ChipGroup
          label="是否对花"
          options={TRI_STATE_CHIPS}
          value={value.hasPattern}
          onChange={(next) => onChange({ hasPattern: next })}
        />

        {/* 花距只在「对花 = 是」时才有意义（对花为否时留着会让下游多算一个花距） */}
        {value.hasPattern === true && (
          <div>
            <label htmlFor={fieldId('patternRepeat')} className={LABEL_CLASS}>
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
          以免与「加工选项」的勾选控件在选择器上争用）。
          issue #4420：19 项长尾选项**默认收起**，展开前只报「已选 N 项」——
          收起不改变可选项集合（展开后 19 项一个不少），改的只是首屏密度。 */}
      <div className="mt-4 rounded-lg border border-neutral-200">
        <button
          type="button"
          onClick={() => setSpecialOpen((v) => !v)}
          aria-expanded={specialOpen}
          className="w-full flex items-center justify-between gap-2 px-3 py-2.5 text-left"
        >
          <span className="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-700">
            {specialOpen ? (
              <ChevronDown className="w-4 h-4 text-neutral-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-neutral-400" />
            )}
            特殊选项
            <span className="text-xs font-normal text-neutral-400">（部位级，可多选）</span>
          </span>
          <span
            className={
              'text-xs ' + (selectedSpecialCount > 0 ? 'text-primary-600 font-medium' : 'text-neutral-400')
            }
          >
            {selectedSpecialCount > 0 ? `已选 ${selectedSpecialCount} 项` : '未选'}
          </span>
        </button>
        {specialOpen && (
          <div className="flex flex-wrap gap-2 px-3 pb-3">
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
        )}
      </div>

      {/* 双拼（拼色）：配布边是**一条独立面料明细行**（§4.8） */}
      {isMixed && (
        <div className="mt-4 rounded-lg border border-neutral-200 bg-neutral-50/60 p-3">
          <div className="text-sm font-medium text-neutral-700 mb-2">
            双拼 · 配布边（§4.8：一扇窗 = 主布行 + 配布边行）
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor={fieldId('edgeMeters')} className={LABEL_CLASS}>
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
              <label htmlFor={fieldId('edgeUnitPrice')} className={LABEL_CLASS}>
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
