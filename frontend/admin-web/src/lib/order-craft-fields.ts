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
 * **帘体**（issue #4521；issue #4874 收窄）—— 用户口径的购买情况里的前两类：
 *
 * | 帘体 | 落库形态 | 用料 |
 * |---|---|---|
 * | `布帘` | 一条明细行（部位缺省 = 布帘） | **按公式算**（算料引擎试算预填，可改） |
 * | `纱帘` | 一条明细行（`curtainType=纱帘`） | **与布帘完全相同的算法**（算料引擎试算预填，可改）<br>⚠️ 2026-09-21 用户裁定：「订单中选择纱帘时，用料算法和布帘的用料算法完全一致」—— 原「买多少就是多少 / 不算料」作废 |
 *
 * ⚠️ **`布帘+纱帘` 档已整体移除**（issue #4874，用户 2026-09-21 需求批次第 2 条
 * 「订单需要**移除布帘+纱帘的选项**」）：它那一**整族**派生（`bodyHasSheerLine` /
 * 纱帘米数 / 纱帘单价 / 第二条纱帘明细行 / 费用明细「纱帘」行 / `totals.sheerSubtotal` /
 * 提交校验里的纱帘单价必填）**一并删除，不留半截死代码**。
 * 「布 + 纱」这一购买形态仍可达：一个商品组勾**帘体 = 布帘**（主布行）、另一个商品组勾
 * **帘体 = 纱帘**（独立一行 `curtainType=纱帘`，按该行 `unitPrice` 计价）。
 *
 * 最后一类「布料」不在本枚举里 —— 它是 `SaleForm`（售卖形态）的另一档，整组无加工。
 */
export const CURTAIN_BODY_OPTIONS = ['布帘', '纱帘'] as const

export type CurtainBody = (typeof CURTAIN_BODY_OPTIONS)[number]

export const CURTAIN_BODY_CLOTH = '布帘'
export const CURTAIN_BODY_SHEER = '纱帘'

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
 * `production_route_rules.trigger_value` **逐字**匹配（`trigger_kind='option'`）。
 * 与库侧差一个字 ⇒ 条件工序不加（**少做工**）。
 * ⚠️ issue #5245 A4：旧载体 `production_option_routings` / `production_option_factors`
 * 已**物理删除**（清僵尸对象）—— 别再按旧表名核对清单。
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
// ⚠️ **`接宽` 不在本清单里**（issue #5230 v2，用户 2026-09-23 裁定「**移除接宽逻辑，接高在特殊选项中
//    选择，但是仍然得自动推导**」）：接宽保持「算料 + 面板提示」概念，**没有**选项 / 工序 / 计件出口
//    ⇒ 它进不了 `processingInfo.specialOptions`（选项名是 join key：清单里没有的名字插不了工序、
//    计件也认不出，后端会按「缺工序」fail-closed 422）。
//    企业侧与它相关的唯一落点 = **派生的「拼接」加工项**（走 `processingItems[]`，见
//    `lib/craft-calc-request.ts::derivedJoinSpliceItemOf`）。

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
  /**
   * **用料公式**（issue #4874，用户 2026-09-21：「加上用料公式字段，如果选择韩褶公式，
   * 那就自动算出褶数，如果选择的是褶倍数公式，那就展示是经济档还是标准档」）：
   * `pleat` 韩褶公式（褶数法）/ `fullness` 褶倍数公式（倍数法）。
   *
   * ⚠️ 值域 = `lib/craft-calc-request.ts` 的 `CRAFT_CALC_FORMULAS`（与算料引擎
   * `curtain_calc.FORMULA_LABELS` 同源，由 `craft-calc-formula-sync.test.ts` 逐值守）——
   * 本文件**不重抄**公式名，也不持有中文标签真值。
   *
   * ⚠️ **落库**（与 `craftTier` 同族，两者要么都落、要么都不落）：`buildCraftSpec` 写进
   * `processingInfo.formula`（camelCase，缺值不写）。它是**褶距字段的替换位** ——
   * 褶距原本是落库的写侧键（`order_items.pleat_spacing` + `processingInfo.pleatSpacing`）
   * ⇒ 新字段若不落库，订单行就不再自描述「这单按哪个公式算的料」，只能靠人读 `formulaText`
   * 那段散文串反推（本仓明令禁止「从散文里猜语义」）。
   * ⚠️ **不新增 DB 列**（`OrderLineCraftFields.materialize` 不映射它）：它进 `processingInfo`
   * JSONB，不进加工单快照白名单 —— 褶数 / 米数由算料输出键承担
   * （契约登记：`docs/wiki/CONTRACT-LEDGER.md` 的「下单行要素」行）。
   */
  formula?: string
  /**
   * **算料档位**（issue #4874）—— 键 = 算料配置 `tiers` 的键（`standard` / `economy` …），
   * 文案取 `tiers[key].label`（**读面取值**，前端不写死档位真值）。
   *
   * 与 `formula` 的区别：档位**必须落库**（`buildCraftSpec` 写 `processingInfo.craftTier`）——
   * 加工单要能看出这单按哪个档位算的料。**不再钉死 `standard`**（#4874 改判）。
   */
  craftTier?: string
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

  // ⚠️ 褶距**已整体移除**（issue #4874，用户 2026-09-21：「移除订单的工艺规格中的褶距字段」）：
  // 本函数不再写 `pleatSpacing`，`CraftSpecInput` 也不再有该键 —— 存量单的**读侧**仍容错
  // （`craft-display.ts` 照旧能渲染老单里的该键，缺值不渲染、不炸）。
  const formula = text(input.formula)
  if (formula !== null) spec.formula = formula

  const craftTier = text(input.craftTier)
  if (craftTier !== null) spec.craftTier = craftTier

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
 * **刻意不携带工艺规格**：褶数 / 开数 / 幅数是一扇窗的属性，不是每块布的属性 ——
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

// ── 套绑组（issue #4395）：一樘窗的多条**部位行**写同一个 `craftLineId` ──────────
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
