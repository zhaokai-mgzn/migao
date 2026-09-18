/**
 * 下单页工艺规格**写侧**（issue #4375 包 4b · 设计文档 §4.2 字段表 A / §4.5 键名口径 / §4.8 主布·配布边）。
 *
 * 本文件只做两件事：**选项清单**（下拉/多选的合法值）+ **processingInfo 键构造**。
 * ⚠️ 展示映射的单一真值是 `lib/craft-display.ts`（§4.9「一份 spec，三处渲染」）——
 * 本文件**不重复定义**标签/格式化，也不推导金额（拼色/定型/特殊选项加价待 issue #4341 裁定）。
 *
 * 两条硬约束：
 * 1. **缺值不写**：用户没填 ⇒ 该键**不出现**（不写空串 / `0` / `false` 占位 —— 下游会当成真值）；
 *    但用户**显式**选的「否」（`isShaped=false` / `hasPattern=false`）是真值，必须写。
 * 2. **键名 camelCase**（§4.5）：与既有 `processingInfo`（`colorName`/`sellingMethod`/`specialOptions`）
 *    及 Java 消费端同口径；算料输出键（snake_case）不在本包范围内。
 */

import { craftSpecRows } from './craft-display'

/** 部位（§4.2 `curtainType`）—— 工序路线的索引键之一，错值会让加工单取到错误路线 */
export const CURTAIN_TYPE_OPTIONS = ['布帘', '纱帘', '帘头'] as const

/** 工艺（§4.2 `craft`）—— 须与库侧 `production_routings.craft` **逐字一致**（「韩式褶」非法） */
export const CRAFT_OPTIONS = ['韩褶', '打孔', '四爪钩', '穿杆', '平幔'] as const

/** 加工类型（§4.2 `cuttingMode`） */
export const CUTTING_MODE_OPTIONS = ['定高买宽', '定宽买高'] as const

/**
 * 打开方式（§4.2 `openCount`）——**开数（正整数）**，不是固定枚举（issue #4387 判据 1）：
 * 用户口径明确含**三开**（「定高买宽，定宽买高，单开，双开，三开这些信息也要在订单上体现」）。
 * 下拉列出行业常见的 1/2/3/4；更大的开数（如 5 开）由 API / Agent 直写，
 * 展示侧照 `craft-display.ts` 的兜底如实标「N 开」。
 *
 * ⚠️ **文案不在这里定义**：`单开/双开/三开/四开` 是展示映射，单一真值是 `lib/craft-display.ts`
 * （§4.9「一份 spec，三处渲染」）—— 本文件从它取文案，避免同一真值出现第二份推导。
 */
export const OPEN_COUNT_OPTIONS: ReadonlyArray<{ value: number; label: string }> = [1, 2, 3, 4].map(
  (value) => ({
    value,
    label: craftSpecRows({ openCount: value })[0]?.value ?? String(value),
  })
)

/** 款式（§4.2 `style`） */
export const STYLE_OPTIONS = ['单色', '拼色'] as const

/** 款式「拼色」= 双拼（真值源 §8：拼2次 口语叫双拼色）—— 唯一会拆主布/配布边两行的取值 */
export const STYLE_MIXED = '拼色'

/**
 * 特殊选项清单（19 项，**部位级**，真值源 `docs/curtain-production-rules.md` §1【默】）。
 *
 * 逐字抄自 `backend/ai-agent-service/app/production/routing.py`
 * （`SPECIAL_OPTION_ROUTINGS` ∪ `OPTION_FACTOR_SCOPES` ∪ `NON_PIECEWORK_OPTIONS`，
 * 覆盖率门禁 = `tests/test_production/test_special_options.py`）。
 * 库侧增删选项而此处不跟 ⇒ `order-craft-fields.test.ts` 的清单判据会红（不是静默漂移）。
 */
export const SPECIAL_OPTIONS = [
  '余料带回(布)', '余料带回(纱)', '布绑带', '纱绑带', '加logo条', '加立边',
  '加花边', '拼1次', '拼2次', '拼3次', '加铅块', '接高', '双眼皮接高',
  '扣环', '抱枕', '防翘扣', '一分二', '余料做绑带', '余料做帘头',
] as const

/** 明细行角色（§4.8）：主布 / 配布边 */
export const COMPONENT_ROLE_MAIN = '主布'
export const COMPONENT_ROLE_EDGE = '配布边'

/** 配布边米数来源（§4.8 / 真值源 §8 口径纪律：用料必须带来源，防多渠道不一致） */
export const METERS_SOURCE_FOLLOW = '跟随主布'
export const METERS_SOURCE_MANUAL = '人工指定'

/**
 * 一行明细的工艺规格录入值 —— **全部可缺省**（未填的键不落库）。
 *
 * 三态字段（`isShaped` / `hasPattern`）刻意用 `boolean | undefined` 而非 `boolean`：
 * 「未指定」与「否」是两个不同的真值，合并会让「没问过」被下游当成「不做定型」。
 */
export interface CraftSpecInput {
  curtainType?: string
  craft?: string
  cuttingMode?: string
  /** 开数（正整数；下拉列 1/2/3/4，更大开数由 API/Agent 直写）—— issue #4387 */
  openCount?: number
  /** 是否定型：`true` 是 / `false` 否 / `undefined` 未指定 */
  isShaped?: boolean
  /** 褶距（米） */
  pleatSpacing?: number
  /** 是否对花：三态同 `isShaped` */
  hasPattern?: boolean
  /** 花距（米）—— 仅「是否对花 = 是」时有意义 */
  patternRepeat?: number
  /** 单色 / 拼色 */
  style?: string
  /** 部位级特殊选项 */
  specialOptions?: string[]
}

/** 非空字符串（去空白）；空串 / 纯空白 ⇒ `null`（视为未填） */
function text(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/** 正有限数（0 / 负数 / NaN / Infinity ⇒ `null`）——「0」在本表单里就是「没填」 */
function positive(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

/**
 * 把录入值转成 `processingInfo` 的工艺规格键（**只含真填了的键**）。
 *
 * 这是「缺值不写」的唯一落点：下游（Java `buildSnapshot` 白名单 / Python `build_routing`）
 * 一旦读到 `craft=""` 或 `isShaped=false` 就会当成真值 —— 空值比缺键危险得多。
 */
export function buildCraftSpec(input: CraftSpecInput): Record<string, unknown> {
  const spec: Record<string, unknown> = {}

  const curtainType = text(input.curtainType)
  if (curtainType !== null) spec.curtainType = curtainType

  const craft = text(input.craft)
  if (craft !== null) spec.craft = craft

  const cuttingMode = text(input.cuttingMode)
  if (cuttingMode !== null) spec.cuttingMode = cuttingMode

  const openCount = positive(input.openCount)
  if (openCount !== null) spec.openCount = openCount

  // 显式布尔（含 false）才是真值；undefined = 未指定 ⇒ 不写
  if (typeof input.isShaped === 'boolean') spec.isShaped = input.isShaped

  const pleatSpacing = positive(input.pleatSpacing)
  if (pleatSpacing !== null) spec.pleatSpacing = pleatSpacing

  if (typeof input.hasPattern === 'boolean') spec.hasPattern = input.hasPattern

  // 花距只在「对花 = 是」时落库：对花为否时它自相矛盾，留着会让下游多算一个花距
  if (input.hasPattern === true) {
    const patternRepeat = positive(input.patternRepeat)
    if (patternRepeat !== null) spec.patternRepeat = patternRepeat
  }

  const style = text(input.style)
  if (style !== null) spec.style = style

  const options = (input.specialOptions ?? [])
    .map((option) => text(option))
    .filter((option): option is string => option !== null)
  if (options.length > 0) spec.specialOptions = options

  return spec
}

/**
 * 主布行的**樘窗绑组键**（§4.8；樘窗语义 = issue #4387）：`componentRole=主布` +
 * `craftLineId`（自指，§4.8 表注「`craftLineId` 自指亦可」）。
 *
 * **`craftLineId` 标识同一樘窗（一个窗户）**，不是「同组只出一个部位」：部位 = 一行明细 = 一件帘，
 * 布行与纱行同组时**各成一个部位**；只有配布边行不独立成部位。
 *
 * 只在拼色时写 —— 单色单缺省即主布（§4.8 存量单兼容），少写两个键就少一份下游兼容面。
 * `craftLineId` 用**客户端行标识**：服务端生成 `order_item.id` 之前两行只能靠同一个共享 token
 * 绑组（消费端组键 = 本行 `craftLineId`，缺省回落本行 `itemId`）。
 */
export function buildMainLineGroupKeys(lineId: string): Record<string, unknown> {
  return { componentRole: COMPONENT_ROLE_MAIN, craftLineId: lineId }
}

/**
 * 配布边行的工艺键（§4.8）：`componentRole=配布边` + `craftLineId`（指向主布行）+ `metersSource`。
 *
 * **刻意不携带工艺规格**：折数 / 开数 / 幅数是一扇窗的属性，不是每块布的属性 ——
 * 两行都带 ⇒ 加工单生成两个部位 ⇒ 工序与计件翻倍、用料双算。
 */
export function buildEdgeLineCraftSpec(
  mainLineId: string,
  metersSource: string
): Record<string, unknown> {
  return {
    componentRole: COMPONENT_ROLE_EDGE,
    craftLineId: mainLineId,
    metersSource,
  }
}
