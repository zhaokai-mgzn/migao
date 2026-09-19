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

/**
 * 部位（§4.2 `curtainType`）—— 工序路线的索引键之一，错值会让加工单取到错误路线。
 *
 * ⚠️ **下单页不再让商家选部位**（issue #4521，用户 2026-09-19 裁定「**移除部位功能，其实完全不需要**」）：
 * 一个商品组 = 一樘帘，主帘**缺省即布帘**（与下游 `ProcessingOrderService.DEFAULT_CURTAIN_TYPE` 同值），
 * 只有**纱帘行**显式写 `curtainType=纱帘` —— 它是**另一个部位**，不写就会被当成布帘取错路线。
 * 本清单仍是枚举真值（API / Agent 直写与三端展示侧照它走）。
 */
export const CURTAIN_TYPE_OPTIONS = ['布帘', '纱帘', '帘头'] as const

/** 部位「布帘」= 主帘的**缺省值**（写侧刻意**不写**该键，下游缺省即此值） */
export const CURTAIN_TYPE_CLOTH = '布帘'

/** 部位「纱帘」= 下单页唯一**显式写**的部位（帘体含纱帘时的那条纱帘行） */
export const CURTAIN_TYPE_SHEER = '纱帘'

/**
 * **帘体**（issue #4521）—— 用户口径的四类购买情况里的前三类：
 *
 * | 帘体 | 落库形态 | 用料 |
 * |---|---|---|
 * | `布帘` | 一条明细行（部位缺省 = 布帘） | **按韩折公式算**（算料引擎试算预填，可改） |
 * | `纱帘` | 一条明细行（`curtainType=纱帘`） | **商家手填**（「买多少就是多少」，不算料） |
 * | `布帘+纱帘` | **两条**明细行：主布行 + 纱帘行（同 `craftLineId`） | 主布算料；纱帘手填 |
 *
 * 第四类「布料」不在本枚举里 —— 它是 `SaleForm`（售卖形态）的另一档，整组无加工。
 */
export const CURTAIN_BODY_OPTIONS = ['布帘', '纱帘', '布帘+纱帘'] as const

export type CurtainBody = (typeof CURTAIN_BODY_OPTIONS)[number]

export const CURTAIN_BODY_CLOTH = '布帘'
export const CURTAIN_BODY_SHEER = '纱帘'
export const CURTAIN_BODY_BOTH = '布帘+纱帘'

/**
 * 该帘体是否**组合**（布帘 + 纱帘）—— 唯一会额外生成一条**纱帘明细行**的帘体。
 *
 * ⚠️ 与「含纱帘」区分：`只买纱帘` 也含纱帘，但那一行**本身就是**纱帘（单价 = 该行单价），
 * 不再出「纱帘米数 / 纱帘单价」子块、也不额外生成行 —— 否则会凭空多出第三条明细行。
 */
export function bodyHasSheerLine(body: CurtainBody): boolean {
  return body === CURTAIN_BODY_BOTH
}

/**
 * 该帘体在主帘行上的**部位**（写侧）：只有「只买纱帘」显式写；
 * 布帘 / 布帘+纱帘 的主帘行**不写**（缺省即布帘，少写一个键就少一份下游兼容面）。
 */
export function curtainTypeOfBody(body: CurtainBody): string | undefined {
  return body === CURTAIN_BODY_SHEER ? CURTAIN_TYPE_SHEER : undefined
}

/**
 * 该帘体的「是否定型」默认档 —— 真值源 §10「**布帘默认是 / 纱帘默认否**」
 * （`curtain_checklist.py` 的 `is_shaped.default_rule = curtain_type`）。
 *
 * ⚠️ issue #4521：这条默认原先是**选部位联动**出来的（#4489）；部位选择移除后改由
 * **帘体结构**决定 —— 同一份真值源，只是触发方式从「交互」变成「结构」。
 *
 * ⚠️ issue #4566：它现在是「定型」**加工项**的默认**勾选态**（页面侧 `withShapedDefault`），
 * 不再是 `craft.isShaped` 的默认值 —— 真值源不变，只是承载它的控件搬到了加工项。
 */
export function defaultIsShapedForBody(body: CurtainBody): boolean {
  return body !== CURTAIN_BODY_SHEER
}

/**
 * 工艺枚举真值（§4.2 `craft`）—— 须与库侧 `production_routings.craft` **逐字一致**（「韩式褶」非法）。
 *
 * ⚠️ issue #4566（用户 2026-09-19 裁定「工艺…直接通过加工项来勾选」）：下单页**不再让商家选工艺**
 * ⇒ 本清单不再是下单选项目，而是**加工项 `craftHint` 的合法值域**（V78 的
 * `processing_items.craft_hint`，目录里 5 个工艺项声明它）。工艺值的写侧来源 = 页面侧
 * `craftFromItems`（勾选的工艺项的 `craftHint`），本文件**不再提供默认工艺**。
 *
 * ⚠️ `四爪钩` 仍是合法工艺枚举，但 **V83 加工项目录里没有对应项**（它是配件、不是打褶方式）
 * ⇒ 下单页暂时不可达（已知取舍，归属 issue #4365 阶段 2）；存量单的 `craft='四爪钩'` 照旧派生。
 */
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
 * 是否对花默认「否」—— 真值源 §1 下单行要素实证（ERP 订单录入页：「是否对花: **不对花**」）。
 * 三态里的「未指定」仍是独立真值，只是**默认**给「否」（商家看得见、可改）。
 */
export const DEFAULT_HAS_PATTERN = false

/**
 * 新明细行的**默认工艺规格**。
 *
 * 为什么扩到 4 项（issue #4493）：用户 2026-09-19「**现在太多点选了**」—— 8 个字段每个都要点一次。
 * 把**有行业默认**的字段全部预填 ⇒ 商家**常态 0 点击**，只在偏离默认时改。
 * 打开方式不在这里：它按**窗宽**联动（真值源 §10 的启发式，见页面侧 `deriveOpenCount`）。
 *
 * ⚠️ **`craft` / `isShaped` 不在这里**（issue #4566，用户 2026-09-19 裁定）：它们已搬到
 * **加工项**（工艺 = 勾选的工艺项的 `craftHint`；定型 = 「定型」加工项的勾选态）⇒
 * 前端**不得**再补一份默认工艺/默认定型（那正是让 ERP「工艺+特征」组合名匹配不上的那份口径）。
 * 两者由页面侧的**唯一派生点** `derivedCraftSpec` 写进 `buildCraftSpec`。
 *
 * ⚠️ 与硬约束 1「缺值不写」的关系：默认值是**商家看得见的真值** ⇒ 必须写；
 * 「缺值不写」管的是**既没填也没默认**的键。
 */
export function createDefaultCraftSpec(): CraftSpecInput {
  return {
    cuttingMode: DEFAULT_CUTTING_MODE,
    style: DEFAULT_STYLE,
    pleatSpacing: DEFAULT_PLEAT_SPACING,
    hasPattern: DEFAULT_HAS_PATTERN,
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
 * 与库侧差一个字 ⇒ 条件工序不加（**少做工**）。
 * ⚠️ 其中「计件系数」那半已退场（issue #4589 用户裁定）：计件工资 = 数量 × 计件单价，
 * `OPTION_FACTOR_SCOPES` 自该单起**零消费**（保留仅为已发布迁移种子的真值源镜像）
 * ⇒ 选项名对不上**不再**影响工人到手金额。
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
 * 三态字段（`hasPattern`）刻意用 `boolean | undefined` 而非 `boolean`：
 * 「未指定」与「否」是两个不同的真值，合并会让「没问过」被下游当成「不对花」。
 *
 * ⚠️ `craft` / `isShaped` **不是商家在本表单里选的**（issue #4566，用户 2026-09-19 裁定
 * 「工艺、定型…直接通过加工项来勾选」）：它们的真值来源是**加工项**
 * （工艺 = 勾选的工艺项的 `craftHint`；定型 = 「定型」加工项的勾选态），
 * 由页面侧唯一派生点 `derivedCraftSpec` 填进来。本类型仍是**落库键的载体**（`buildCraftSpec` 照旧写它们）。
 * `isShaped` 的 `undefined` 档现在表达「目录里没有『定型』项」（老租户未重建目录）⇒ 不写该键。
 */
export interface CraftSpecInput {
  // ⚠️ **没有 `curtainType`**（issue #4521）：部位已从录入面移除 —— 主帘缺省即布帘（不写），
  //    纱帘行的部位由 `buildSheerLineCraftSpec` 显式写死。留一个可录键 = 留一条能写错路线的口子。
  /** 工艺（#4566：由加工项 `craftHint` 派生，不猜默认） */
  craft?: string
  cuttingMode?: string
  /** 开数（正整数；下拉列 1/2/3/4，更大开数由 API/Agent 直写）—— issue #4387 */
  openCount?: number
  /** 是否定型（#4566：由「定型」加工项的勾选态派生；目录无该项 ⇒ `undefined`） */
  isShaped?: boolean
  /** 褶距（米） */
  pleatSpacing?: number
  /** 是否对花：`true` 是 / `false` 否 / `undefined` 未指定（**本表单唯一的三态字段**） */
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

  // 部位**不在本函数里**（issue #4521）：主帘缺省即布帘 ⇒ 不写；纱帘行由
  // `buildSheerLineCraftSpec` 显式写 `curtainType=纱帘`。
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

/**
 * **纱帘行**的工艺键（issue #4521）：`curtainType=纱帘` + 与主布行**同一份工艺规格** +
 * 同 `craftLineId`（同一樘帘）+ 用料来源。
 *
 * 与配布边行的**关键区别**（刻意不同，别照抄 `buildEdgeLineCraftSpec`）：
 * - 纱帘**是另一个部位**（自己的工序路线：纱帘×韩褶）⇒ **必须携带工艺规格**；
 *   配布边不是部位（同一扇窗的一块布）⇒ 刻意不带，否则工序与计件翻倍。
 * - 纱帘行的用料由商家给定（「买多少就是多少」）⇒ 走 `metersSource` 留痕，不写算料输出。
 *
 * `saleForm` 也显式写：纱帘行**不挂加工项**（加工费只挂主布行），而读侧对存量单的兜底是
 * 「无加工项 ⇒ 布料」（#4493）⇒ 不写会被读成布料单。
 */
export function buildSheerLineCraftSpec(
  mainLineId: string,
  spec: Record<string, unknown>,
  metersSource: string
): Record<string, unknown> {
  return {
    ...spec,
    curtainType: CURTAIN_TYPE_SHEER,
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
