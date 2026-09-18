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

// ── 默认档（用户 2026-09-19 裁定；issue #4420）────────────────────────────────
//
// 三条默认值都是**真值**（商家在界面上看得见 ⇒ 必须落库），不是占位符：
// 商家不选 ≠ 没这回事，而是「按行业默认走」—— 缺键会让下游（Java 快照 / Python 建路线）
// 只能靠猜（#4362 的信号派生是为此存在的**兜底**，不是主路径）。

/** 加工类型默认「定高买宽」—— 真值源 §2：层高 ≤2.8m 用定高布最省料，是绝大多数家用场景 */
export const DEFAULT_CUTTING_MODE = '定高买宽'

/** 款式默认「单色」—— 拼色会额外拆出配布边行，不能默认替顾客加钱 */
export const DEFAULT_STYLE = '单色'

/**
 * 每折吃布（米）—— 真值源 `curtain-fabric-quote-rules.md` §8「每折吃布 0.25 米」。
 *
 * ⚠️ 与 `backend/ai-agent-service/app/tools/curtain_calc.py` 的 `PLEAT_FABRIC_PER_FOLD`
 * **同值**；同步守卫 = `tests/unit/lib/craft-calc-defaults.test.ts`（读 Python 源逐值比对，
 * 漂移即红）—— 本仓「副本必须有同步守卫」纪律的落点（同族 #4393）。
 */
export const PLEAT_FABRIC_PER_FOLD = 0.25

/** 标准档名义倍数 —— 同 `curtain_calc.py` 的 `DEFAULT_CRAFT_TIERS.standard.fullness` */
export const STANDARD_FULLNESS = 2.0

/**
 * 默认褶距（米）= 每折吃布 ÷ 标准档倍数 = 0.25 ÷ 2.0 = **0.125**（12.5cm）。
 *
 * 用户 2026-09-19 裁定：「褶距**随倍数自动算**（可改）」。
 * 公式来源：真值源 §8「每折吃布 0.25 米（折距 10cm ≈ 2.5 倍褶）」⇒ 褶距 = 0.25 ÷ 倍数。
 *
 * ⚠️ 已知真值冲突（照实登记，待裁定）：引导清单 `curtain_checklist.py` 给 `pleat_spacing`
 * 的行业默认是 **0.1m（=2.5 倍）**，与本处 0.125（=2.0 倍）差 25%。两者不能同时是默认 ——
 * 本处以**用户选定的标准档 2.0 倍**为准（自洽），清单那处待单独收口。
 */
export const DEFAULT_PLEAT_SPACING = PLEAT_FABRIC_PER_FOLD / STANDARD_FULLNESS

/**
 * 新明细行的**默认工艺规格**（三条默认值）。
 *
 * 与硬约束 1「缺值不写」的关系：默认值是**商家看得见的真值** ⇒ 必须写；
 * 「缺值不写」管的是**既没填也没默认**的键。
 */
export function createDefaultCraftSpec(): CraftSpecInput {
  return {
    cuttingMode: DEFAULT_CUTTING_MODE,
    style: DEFAULT_STYLE,
    pleatSpacing: DEFAULT_PLEAT_SPACING,
  }
}

/**
 * 特殊选项清单（19 项，**部位级**，真值源 `docs/curtain-production-rules.md` §1【默】）。
 *
 * 逐字抄自 `backend/ai-agent-service/app/production/routing.py`
 * （`SPECIAL_OPTION_ROUTINGS` ∪ `OPTION_FACTOR_SCOPES` ∪ `NON_PIECEWORK_OPTIONS`，
 * 覆盖率门禁 = `tests/test_production/test_special_options.py`）。
 * 库侧增删选项而此处不跟 ⇒ `order-craft-fields.test.ts` 的清单判据会红（不是静默漂移）。
 *
 * ⚠️ **选项名 = ERP 名，且它是 join key**（issue #4389 裁定 R-e）：本清单是**写侧** ——
 * 用户勾选的值经 `buildCraftSpec` 落进 `processingInfo.specialOptions`，服务端拿它去
 * `production_option_routings` / `production_option_factors.option_name` **逐字**匹配。
 * 与库侧差一个字 ⇒ 条件工序不加、计件系数静默退回 1.0（**少发工人钱**）。
 * 故 `一分为二` / `余料带回-布` / `余料带回-纱` 必须与 `routing.py` 及迁移 V59 ∪ V65 逐字一致。
 */
export const SPECIAL_OPTIONS = [
  '余料带回-布', '余料带回-纱', '布绑带', '纱绑带', '加logo条', '加立边',
  '加花边', '拼1次', '拼2次', '拼3次', '加铅块', '接高', '双眼皮接高',
  '扣环', '抱枕', '防翘扣', '一分为二', '余料做绑带', '余料做帘头',
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

// ── 樘窗绑组（issue #4395）：一樘窗的多条**部位行**写同一个 `craftLineId` ──────────
//
// 病根（#4387 的「未做」项）：下单页**只在拼色时**写 `craftLineId` ⇒ 顾客下「布 + 纱」
// （两条明细行、都不带该键）⇒ 消费端 `ProcessingOrderService.craftGroupKey` 回落到各自 `itemId`
// ⇒ **两行各成一樘窗** ⇒ 套级工序（外帘打卷/装袋/发货）在加工单上出现 2 次
// （#4384 A2 的红证因此不会转绿）。
//
// ⚠️ **语义边界**：`craftLineId` 标识**樘窗**（一个窗户），**不是**「面料行组」——
// 部位 = 一行明细 = 一件帘 ⇒ 布行与纱行**各成部位**（读侧不合并），只有配布边行不独立成部位。
// 不得改成「组内只留一个部位」（那会与 #4387 钉死的语义冲突）。

/** 「主布行」的部位取值（§4.2 `curtainType`）—— 樘窗代表行优先取它 */
const CURTAIN_TYPE_CLOTH = '布帘'

/** 樘窗绑组的入参行（纯函数：只取判组需要的三个字段） */
export interface WindowLineRef {
  /** 客户端行标识 —— `craftLineId` 的取值来源（服务端生成 `order_item.id` 之前只有它可用） */
  id: string
  /** 樘窗名称 / 窗号；去空白后非空且与他人相同 ⇒ 同樘窗。未填 ⇒ 不参与绑组 */
  windowLabel?: string
  /** 部位（§4.2 `curtainType`）—— 用于挑「主布行」作代表行 */
  curtainType?: string
}

/**
 * 把「同一樘窗的多条部位行」解析成 `行标识 → craftLineId`（issue #4395 判据 1 的纯函数半边）。
 *
 * 三条口径（**缺值不写**是本源文件的硬约束 1，这里逐条对齐）：
 * 1. **未填窗号 ⇒ 不写**：缺省回落本行 `itemId` ⇒ 各自成组 = **存量语义逐字不变**；
 * 2. **窗号只有一行 ⇒ 不写**：单行樘窗的组键本来就 = 本行 `itemId`，写它没有信息量；
 * 3. **代表行 = 组内第一条「部位=布帘」的行**（= 主布行；§4.8 的 `craftLineId` 口径就是
 *    「主布行的行标识」，`R-b` 加工费也落主布行）；组内没有布帘（纱 + 帘头）⇒ 取**组内首行**
 *    （不猜、不丢组 —— 静默丢组会让整樘窗没有归属层级）。
 */
export function resolveWindowCraftLineIds(
  lines: ReadonlyArray<WindowLineRef>
): Record<string, string> {
  const groups = new Map<string, WindowLineRef[]>()
  for (const line of lines) {
    const label = text(line.windowLabel)
    if (label === null) continue
    const group = groups.get(label)
    if (group) group.push(line)
    else groups.set(label, [line])
  }

  const craftLineIds: Record<string, string> = {}
  for (const group of groups.values()) {
    if (group.length < 2) continue
    const representative =
      group.find((line) => text(line.curtainType) === CURTAIN_TYPE_CLOTH) ?? group[0]
    for (const line of group) craftLineIds[line.id] = representative.id
  }
  return craftLineIds
}

/**
 * 樘窗行的绑组键：**只写 `craftLineId`**。
 *
 * 不写 `componentRole`：缺省即主布（§4.8 存量兼容），而**纱行既不是主布也不是配布边**
 * ⇒ 角色由读侧按部位 / 组内顺序判定，写侧不冒充。
 */
export function buildWindowGroupKey(craftLineId: string): Record<string, unknown> {
  return { craftLineId }
}
