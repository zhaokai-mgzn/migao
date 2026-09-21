'use client'

/**
 * 下单页「工艺规格」录入区（issue #4375 包 4b · 设计文档 §4.6 入口 2）。
 *
 * 商家手工录单是布艺商家的主路径（行业 ERP 的订单录入页就是这一页）——
 * 本组件把这页此前**一个都不写**的工艺参数变成可录入项。
 *
 * ⚠️ **「工艺」与「是否定型」已搬到加工项**（issue #4566，用户 2026-09-19 裁定逐字：
 * 「工艺规格中的 **工艺，定型**，对花我觉得**直接通过加工项来勾选**，其他保留，这样的区分和
 * 交互是否更合理？」）⇒ **本组件不再录入这两项**：
 * - **工艺**：加工项里 5 个工艺项**显式声明** `craftHint`（V78 的 `processing_items.craft_hint`）
 *   ⇒ 页面侧由勾选项派生（`craftFromItems`）。**必须**这么改：加工费组合键的唯一来源是
 *   `processingInfo.processingItems[].name`，而 ERP 91 项加工费名字全是「工艺+特征」形态
 *   （`韩折+超高+定型`）—— 工艺留在本组件里 ⇒ ERP 的名字一行都匹配不上。
 * - **是否定型**：加工项目录里的 `定型` 项勾选态即 `isShaped`（后端
 *   `ProcessingOrderService` 读的就是这个键）。
 *
 * **对花保留**（它不在加工项里）：它是**算料输入** —— 定宽买高时每幅加 1 个花距
 * （见 `curtain_calc.py`），且 ERP 91 项加工费名单里 **0 行**含对花。
 * 保留的还有：加工类型 / 打开方式 / 款式 / 褶距 / 纱帘子块 / 拼色配布边子块。
 *
 * ⚠️ **19 项部位级特殊选项已迁出**（issue #4511）：用户口径「加工项 - 工艺规格 - 特殊选项
 * 都放到**平级**」⇒ 它现在由 `OrderExtraOptions` 渲染、由页面侧的**向导步骤**包壳。
 *
 * 三条边界：
 * 1. **本组件只录入，不落库**：值的裁剪（缺值不写 / camelCase 键名）在
 *    `lib/order-craft-fields.ts` 的 `buildCraftSpec`，两处不重复一套规则。
 * 2. **不动金额**：拼色/定型/特殊选项加价待 issue #4341 裁定，本组件不显示任何加价。
 * 3. **三态而非布尔**：`是否对花` 的「未指定」与「否」是两个真值 —— 合并会让「没问过」
 *    被下游当成「不对花」。（#4566 后本组件**只剩这一个三态字段**。）
 *
 * ── 展示重构（issue #4420，用户 2026-09-19：「信息偏多，不能全部挤在一块区域」）──
 *
 * 录入项本身一个没减（8 个下拉 + 19 项特殊选项 + 拼色配布边），改的是**信息层次**：
 * ① 主工艺参数留在**首屏常显**（录单主路径，不该藏）；
 * ② （19 项特殊选项已迁出，见 `OrderExtraOptions`）；
 * ③ 每个区块有**标题 + 一句话说明**，不再是一个大 grid 平铺。
 *
 * ── 交互改造（issue #4489，用户 2026-09-19：「现在要一个个点过去」）──────────────
 *
 * 病根：字段都是**下拉** ⇒ 每个都要「点开 → 点选项」两步（最多 16 次点击）。
 * ① 枚举字段改 **chips**（一击即中，省掉「展开」那一步）；三态字段用**三段分段按钮**，
 *    「未指定」档保留（三态硬约束不变）。
 *
 * ── 移除「部位」+ 纱帘选配（issue #4521，用户 2026-09-19 裁定）────────────────────
 *
 * 「尺寸数量 / 工艺规格 / 加工项 / 特殊选项都是跟着商品基础属性走的，**部位只决定商品实际
 * 用料米数**……不如把纱帘的设计参考拼色那样的交互，**移除部位功能，其实完全不需要**」
 * 「相当于参考款式一样，在工艺规格中增加一个纱帘选项，如果**带纱帘就像配布边一样，
 * 让用户输入米数和单价**」。
 *
 * ① **部位字段整体移除** —— 主帘缺省即布帘；纱帘由页面侧的**帘体**选择承载；
 * ② ~~**纱帘子块**（`sheer`）~~ —— **已随 `布帘+纱帘` 档一并删除**（issue #4874）；
 * ③ 「是否定型」的行业默认**改由帘体结构决定**（`defaultIsShapedForBody`）—— 同一份真值源；
 *    #4566 后它落到「定型」加工项的**默认勾选态**上（页面侧 `withShapedDefault`）。
 *
 * ── issue #4874（用户 2026-09-21 需求批次）────────────────────────────────────
 *
 * ① **褶距控件整体删除**（「移除订单的工艺规格中的褶距字段」）—— `pleatSpacing` 连同
 *    `DEFAULT_PLEAT_SPACING` / `buildCraftSpec` 的写键一起退场；存量单的**读侧**仍容错。
 * ② **新增「用料公式」chips**（`pleat` 韩褶公式·褶数法 / `fullness` 褶倍数公式·倍数法）：
 *    - 选 `pleat` ⇒ 展示**自动算出的褶数**（试算响应 `pleat_count`；没结果展示「—」，
 *      **不许编数**）；
 *    - 选 `fullness` ⇒ 展示**档位 chips**（经济档 / 标准档）——值域 = 算料配置 `tiers` 的**键**、
 *      文案取 `tiers[key].label`（**读面取值**，前端不写死档位真值）。档位进算料请求的
 *      `craft_tier`，并落库 `processingInfo.craftTier`（不再钉死 `standard`）。
 * ③ **配置加载失败不阻断录入**：按缺省（韩褶公式 + 标准档）走，并**显式提示**配置未加载
 *    （静默按缺省走 = 商家以为按自己配的口径算）。
 * ④ **纱帘子块删除**（帘体已无「布帘+纱帘」档）。
 */

import { useId } from 'react'
import {
  CUTTING_MODE_OPTIONS,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  STYLE_MIXED,
  STYLE_OPTIONS,
  type CraftSpecInput,
} from '@/lib/order-craft-fields'
// 用料公式 / 档位（issue #4874）：值域与文案都取自**算料配置读面**（不在本组件里写死第二份）
import {
  CRAFT_CALC_FORMULA_LABELS,
  CRAFT_CALC_FORMULA_PLEAT,
  CRAFT_CALC_FORMULAS,
  CRAFT_CALC_TIER,
  craftCalcTierOptions,
  defaultCraftCalcFormula,
  defaultCraftCalcTier,
} from '@/lib/craft-calc-request'
import type { CraftCalcConfig } from '@/types'

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
 * 「没问过」与「否」是两个真值：合并会让下游把「没问过」当成「不对花」。
 * ⚠️ #4566 后本组件**只剩「是否对花」**用三态（「是否定型」已搬到加工项）。
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
  autoNote,
}: {
  label: string
  options: ReadonlyArray<ChipOption<T>>
  value: T
  onChange: (next: T) => void
  /**
   * 「**这一档是系统按规则自动选的**」标记（issue #5020）—— 只用于加工类型。
   *
   * 为什么要有它：未指定时页面按门幅规则**自动选中**一档（客服看得到选中态），但「自动选的」
   * 与「客服自己点的」在界面上**长得一样** ⇒ 不标出来，客服会以为自己选过（也就不会去核对）。
   * 文案与门幅提示（`door-width-suboptimal` 一族）同一口径：**只是告知，不改值**。
   */
  autoNote?: boolean
}) {
  return (
    <div>
      <div className={LABEL_CLASS}>
        {label}
        {autoNote && (
          <span
            data-testid="cutting-mode-auto"
            title="加工类型未指定 ⇒ 系统按门幅规则自动选中（定高买宽可行 ⇒ 定高买宽；否则 ⇒ 倒幅）；点任意一档即可覆盖"
            className="ml-1.5 rounded border border-neutral-300 bg-neutral-100 px-1 text-[10px] font-normal leading-4 text-neutral-500"
          >
            自动
          </span>
        )}
      </div>
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

export interface OrderCraftFieldsProps {
  /** 当前录入值（未填的键缺省 ⇒ 不落库） */
  value: CraftSpecInput
  /** 局部更新（只合并传入的键） */
  onChange: (patch: Partial<CraftSpecInput>) => void
  /** 主布米数（= 该行数量）；配布边米数的默认值取它 */
  mainMeters: number
  /**
   * 租户**算料配置**（issue #4874）—— 读面 `productionApi.getCraftCalcConfig()`
   * （`GET /api/admin/production/craft-calc-config`）。档位 chips 的**值域**（`tiers` 的键）
   * 与**文案**（`tiers[key].label`）都取自它 ⇒ 前端不持有第二份档位真值。
   * `null` = 配置未加载 ⇒ 不渲染档位 chips，只出**显式提示**（不静默）。
   */
  calcConfig: CraftCalcConfig | null
  /**
   * 最近一次算料试算的**褶数**（响应 `pleat_count`）；`null` = 还没结果 ⇒ 展示「—」，
   * **不许编数**（编一个褶数 = 第二份算料逻辑）。
   */
  pleatCount: number | null
  /** 配布边米数；`null` = 未改过（跟随主布） */
  edgeMeters: number | null
  onEdgeMetersChange: (meters: number | null) => void
  /** 配布边单价；`null` = 未填（不生成配布边明细行 —— 后端单价必须 > 0，不凭空造价） */
  edgeUnitPrice: number | null
  onEdgeUnitPriceChange: (price: number | null) => void
  /**
   * 加工类型是否是**系统按规则自动选中的**（issue #5020）—— `true` ⇒ 标签旁出「自动」标记。
   *
   * 由页面侧给出（`derivedCraftSpec` 的唯一派生点知道「显式 vs 未指定」）⇒ 本组件**不**自己
   * 判断（否则就是第二份「谁在算加工类型」的口径）。缺省 `false` = 不标（既有调用点行为不变）。
   */
  cuttingModeAuto?: boolean
}

export default function OrderCraftFields({
  value,
  onChange,
  mainMeters,
  calcConfig,
  pleatCount,
  edgeMeters,
  onEdgeMetersChange,
  edgeUnitPrice,
  onEdgeUnitPriceChange,
  cuttingModeAuto = false,
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
  const edgeSource = edgeMeters === null ? METERS_SOURCE_FOLLOW : METERS_SOURCE_MANUAL
  const effectiveEdgeMeters = edgeMeters ?? (Number(mainMeters) || 0)

  /** 公式 chips 的候选（值域 = `CRAFT_CALC_FORMULAS`，与算料引擎逐字同源；文案只有一份） */
  const formulaOptions: ReadonlyArray<ChipOption<string>> = CRAFT_CALC_FORMULAS.map((formula) => ({
    value: formula,
    label: CRAFT_CALC_FORMULA_LABELS[formula] ?? formula,
  }))
  /** 档位候选 = **算料配置** `tiers` 的键（值）+ `label`（文案）；配置未加载 ⇒ 空 */
  const tierOptions = craftCalcTierOptions(calcConfig)
  /** 生效公式 = 商家选的 ⇒ 算料配置的兜底 ⇒ 常量兜底（与页面侧同一份解析函数） */
  const effectiveFormula = value.formula ?? defaultCraftCalcFormula(calcConfig)
  /** 配置未加载（含读取失败）—— 显式提示，不静默按缺省走 */
  const calcConfigMissing = calcConfig === null

  return (
    <div>
      {/* ⚠️ **本组件不再自带标题**（issue #4511）：用户截图里「工艺规格」出现了两次
          （页面侧的折叠头 + 这里的标题）。标题与序号由页面侧的**向导步骤**统一提供，
          本组件只负责 8 个字段本体。 */}
      <p className="mb-3 text-xs text-neutral-400">
        加工类型默认「定高买宽」、款式默认「单色」—— 都可改；
        <span className="text-neutral-500">工艺与定型请在「加工项」里勾选</span>
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* ⚠️ 「部位」字段已移除（issue #4521，用户裁定「移除部位功能，其实完全不需要」）：
            主帘缺省即布帘；纱帘由页面侧的**帘体**选择承载（`curtainBody`）——
            这里再放一个部位下拉 = 让商家能选出一个与帘体矛盾的部位（两条真值打架）。
            ⚠️ 「工艺」chip 组已移除（issue #4566）：工艺改由**加工项**勾选派生（工艺项的 `craftHint`）
            —— 留一个可录键 = 与加工项派生的第二份口径打架（且 ERP 的「工艺+特征」组合名匹配不上）。
            ⚠️ 「是否定型」三段 chip 组已移除（同 #4566）：定型是加工项目录里的**手选特征**项。 */}
        <ChipGroup
          label="加工类型"
          options={toChipOptions(CUTTING_MODE_OPTIONS)}
          value={value.cuttingMode}
          onChange={(next) => onChange({ cuttingMode: next })}
          autoNote={cuttingModeAuto}
        />

        <ChipGroup
          label="打开方式"
          options={OPEN_COUNT_CHIPS}
          value={value.openCount}
          onChange={(next) => onChange({ openCount: next })}
        />

        <ChipGroup
          label="款式"
          options={toChipOptions(STYLE_OPTIONS)}
          value={value.style}
          onChange={(next) => onChange({ style: next })}
        />

        {/* **用料公式**（issue #4874，用户 2026-09-21：「加上用料公式字段，如果选择韩褶公式，
            那就自动算出褶数，如果选择的是褶倍数公式，那就展示是经济档还是标准档」）。
            ⚠️ 原「褶距」number 输入框**已删除**（同一批需求：「移除订单的工艺规格中的褶距字段」）
            —— 留一个可录键 = 与算料引擎的档位口径打架（引擎算分幅时**不读**褶距，只按档位取倍数）。 */}
        <ChipGroup
          label="用料公式"
          options={formulaOptions}
          value={effectiveFormula}
          onChange={(next) => onChange({ formula: next })}
        />

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

      {/* **褶数 / 档位**（issue #4874）—— 与「用料公式」chips 联动：
          `pleat`（韩褶公式）⇒ 展示**自动算出的褶数**（试算响应 `pleat_count`）；
          `fullness`（褶倍数公式）⇒ 展示**档位 chips**（值域与文案都取算料配置）。 */}
      {effectiveFormula === CRAFT_CALC_FORMULA_PLEAT && (
        <div className="mt-3" data-testid="craft-pleat-count">
          <span className={LABEL_CLASS}>自动算出的褶数</span>
          <span className="text-sm font-medium text-neutral-900 tabular-nums">
            {/* 没结果就是「—」：**不编数**（编一个褶数 = 第二份算料逻辑） */}
            {typeof pleatCount === 'number' && Number.isFinite(pleatCount) ? pleatCount : '—'}
          </span>
          <span className="ml-1.5 text-xs text-neutral-400">（按韩褶公式试算得出，改宽高即重算）</span>
        </div>
      )}

      {effectiveFormula !== CRAFT_CALC_FORMULA_PLEAT && tierOptions.length > 0 && (
        <div className="mt-3" data-testid="craft-tier-options">
          <ChipGroup
            label="档位"
            options={tierOptions}
            /* 生效档位（issue #4878 独立复核 P2）：公式 chips 显示的是**生效**值
               （`effectiveFormula`），档位 chips 若显示 `value.craftTier ?? ''`，未选时
               **一个都不选中**，而派生/请求/落库用的却是缺省档 ⇒「页面所见 = 请求 = 落库」
               在缺省态不成立（商家看到"没选"，系统按标准档算了钱）。⇒ 同样显示生效值。 */
            value={value.craftTier ?? defaultCraftCalcTier(calcConfig)}
            onChange={(next) => onChange({ craftTier: next })}
          />
          <p className="mt-1 text-xs text-neutral-400">
            档位来自「工艺配置 → 算料配置」的档位表（可增删），随单落库
          </p>
        </div>
      )}

      {/* **配置未加载**（issue #4874）：不阻断录入，但**不许静默** —— 商家必须知道
          现在按的是缺省口径（配置读不到时档位可选值也无从展示）。 */}
      {calcConfigMissing && (
        <p data-testid="craft-calc-config-missing" className="mt-3 text-xs text-amber-600">
          算料配置未加载（「工艺配置 → 算料配置」读取失败）—— 本次按缺省口径试算：
          {CRAFT_CALC_FORMULA_LABELS[CRAFT_CALC_FORMULA_PLEAT] ?? CRAFT_CALC_FORMULA_PLEAT}
          + 档位 {CRAFT_CALC_TIER}；档位可选值需配置加载后才能展示
        </p>
      )}

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
                配布边米数来源：{edgeSource}
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
