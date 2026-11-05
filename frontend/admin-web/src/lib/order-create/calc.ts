/**
 * 下单页的**算料联动**（输入 → 推导 → 加工信息） —— issue #8725 第一档切片产物。
 *
 * 单一职责：把「商家录入的一行」推导成**引擎入参 / 加工信息 / 加工项数量**：
 * 工艺与定型、自动识别特征、门幅与分幅、卷数与卷长、配布边、试算入参（{@link calcInputOf}）、
 * 以及落库用的 {@link buildLineProcessingInfo}。**全纯：不读 React 状态、不发请求、不写盘。**
 *
 * 依赖方向：`calc.ts → display.tsx`（只用 {@link uniqueColors} 一处取颜色名）。
 * 反向依赖不存在 —— 这才让「算料」与「价格预览」可以各自被理解、各自被替换。
 *
 * ⚠️ 行为冻结：`tests/unit/pages/orders-new-slice-characterization.test.tsx` 逐字节比对
 * 同一批输入下的推导读数 —— 这里改一处取整，那条判据立刻具名红。
 */
import { type AutoFeaturesParams, type DoorWidthPlanParams } from '@/lib/api'
import {
  METERS_SOURCE_FORMULA,
  craftCalcParamsOf,
  defaultCraftCalcTier,
  derivedJoinSpliceItemOf,
  effectiveCraftCalcFormula,
  effectiveJoinSourceNamesOf,
  effectiveSpecialOptionsOf,
  type CraftPlanOverrides,
} from '@/lib/craft-calc-request'
import {
  CURTAIN_BODY_CLOTH,
  DEFAULT_OPEN_COUNT,
  STYLE_MIXED,
  buildCraftSpec,
  buildMainLineGroupKeys,
  craftItemKeyOf,
  createDefaultCraftSpec,
  curtainTypeOfBody,
  defaultIsShapedForBody,
  type CraftSpecInput,
} from '@/lib/order-craft-fields'
import {
  AUTO_FEATURE_NAMES,
  effectiveCuttingModeOf,
  parseDoorWidth,
  type AutoFeature,
  type AutoFeatureName,
  type AutoFeatureNotice,
} from '@/lib/craft-auto-features'
import { type CraftCalcConfig, type ProcessingItem } from '@/types'
import {
  SALE_FORM_FABRIC,
  SALE_FORM_FINISHED,
  type OrderLineItem,
  type OrderProductSku,
  type ProductDetail,
  type SystemAutoFeatureRow,
} from '@/lib/order-create/types'
import { uniqueColors } from '@/lib/order-create/display'

export function genId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `li_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

/**
 * 加工项数量规则（**#4882 后的口径**）：恒等于面料米数，下限 1。
 *
 * 沿革：#3005 回滚 #2986 时按 `pi.pricingMethod` 分叉（`per_meter` → 米数，`per_set`/`fixed`/
 * `per_area` → 1）；**#4882（用户裁定）**把「加工项单价 / 计价方式」整体删除 ⇒ 分叉的判据字段
 * 已不存在，且 V83 目录 16 项**全为** `per_meter`（#3005 行业口径：加工费按米计价、辅料含在
 * 加工费中）⇒ 直接返回 `Math.max(1, fabricMeters)`，签名不再需要加工项。
 */
export function deriveProcessingQty(fabricMeters: number): number {
  return Math.max(1, fabricMeters)
}

/** 试算防抖（issue #4434）：连打宽高时只在停手后发一次请求 */
export const CRAFT_CALC_DEBOUNCE_MS = 400

/**
 * **「人工加 / 改」是否显示**（2026-09-30 第四批；用户逐字「人工加 / 改**先隐藏**，本期不需要该功能」）。
 *
 * `false` ⇒ 那一块带 `hidden`（`display:none`：屏幕上与无障碍树上都不存在，**不是**「藏在折叠里」）。
 * 「先隐藏」≠ 删除：`planOverrides` 的整条链路（请求面 `join_height_m` / `splice_times`、契约 #5200 §四 R7
 * 的「人工值不再被推导改判」、落库与留痕）**一字未动**，**节点也仍在 DOM** ⇒ 11 条既有页面判据
 * **一条不降**（铁律 8）。重新打开 = 置 `true`，并同批改回 `.github/cases/order.yml` OR-052 的判据 11。
 */
export const SHOW_MANUAL_OVERRIDES = false

/** 加工费计价预览防抖（issue #4450） */
export const FEE_PREVIEW_DEBOUNCE_MS = 300

/**
 * 「定型」加工项名（**V83 目录逐字**）—— 它的勾选态就是 `isShaped` 的真值来源（issue #4566）。
 *
 * 用户 2026-09-19 裁定：「工艺规格中的**工艺，定型**，对花我觉得**直接通过加工项来勾选**，
 * 其他保留」⇒ 定型是目录里的**手选特征**项（`unit_price=0`，价在加工费组合上）。
 */
export const SHAPED_ITEM_NAME = '定型'

/**
 * 「韩褶」加工项名（**目录名** —— V83 种子第 02 项；契约快照 `api_admin_processing-items` 里 `pi-v83-1-02`；
 * 原名照 ERP 附件逐字写「韩折」，V139 迁移改名为「韩褶」）——
 * 系统**推荐组合**里的那个工艺项（2026-09-28 用户裁定）。
 *
 * 🔴 **按目录名匹配**（{@link withCraftItemDefault}：`pi.name === DEFAULT_CRAFT_ITEM_NAME`）⇒
 * 目录改名（V139）而本常量不改 = 找不到项 = 推荐组合**静默不预选**（无报错、无提示）。
 *
 * 它的 `craftHint = 韩褶`（= `lib/craft-calc-request.ts::DEFAULT_CRAFT_NAME`）⇒ 勾它 = 工艺是韩褶；
 * 工艺的唯一派生点仍是「勾选的工艺项的 `craftHint`」（{@link craftFromItems}）⇒
 * **预选加工项**不新增第二份工艺口径（#4566 的纪律：前端不补一份默认工艺）。
 *
 * 用户 2026-09-28（下单页布局，**原话**）：「正常用户提供净窗高 / 窗宽，然后再确认是否要韩折 / 打孔 /
 * 定型等信息即可」⇒ 这套推荐组合由系统**预选**、商家一键「全不采纳」可撤（撤过即留痕，不再勾回）。
 */
export const DEFAULT_CRAFT_ITEM_NAME = '韩褶'

/**
 * 该行的**手选加工项**清单 —— 滤掉**自动推导特征**（`超高`/`超宽`/`倒幅`）。
 *
 * 为什么目录里有它们却要滤掉：商家配「加工费组合」时必须能选到它们
 * （组合名就是 `韩褶+超高+定型` 这种形态），但**下单页**的勾选控件不能有
 * —— 它们是**推导**出来的（判据 8：自动识别特征出现手选项 ⇒ 红）。
 * 单一真值 = `craft-auto-features.ts` 的 `AUTO_FEATURE_NAMES`（此处不抄第二份名字数组）。
 */
export function handPickableProcessingItems(items: ProcessingItem[]): ProcessingItem[] {
  const autoNames: readonly string[] = AUTO_FEATURE_NAMES
  return items.filter((pi) => !autoNames.includes(pi.name))
}

/**
 * 该行的**工艺**（issue #4566）—— 唯一取值函数：取**已勾选**加工项里第一个带 `craftHint` 的项。
 *
 * `craftHint` 是 V78 给加工项加的**显式声明**列（`processing_items.craft_hint`，目录里 5 个工艺项
 * 声明它：`打孔`→打孔 · `韩褶`/`韩定+S钩`→**韩褶** · `穿杆`→穿杆 · `平幔`→平幔）。
 *
 * ⚠️ 都没有 ⇒ `undefined`（**不猜、不填默认韩褶**）：后端 `deriveRouteKey` 会走
 * 「显式 craft → `craft_hint` → 信号表 → 租户默认工艺」的降级链 —— 前端再补一份默认工艺
 * 就是第二份口径（且正是它让 ERP 的「工艺+特征」组合名一行都匹配不上）。
 *
 * 按 `processingItems`（目录顺序）取，不按点击顺序 —— 单值护栏（`toggleProcessing`）保证
 * 同单至多一个带 `craftHint` 的勾选项，这里只是让取值与点击先后无关。
 */
export function craftFromItems(line: OrderLineItem): string | undefined {
  return (
    line.processingItems.find(
      (pi) => Boolean(pi.craftHint) && line.selectedProcessing[pi.id]?.selected === true
    )?.craftHint ?? undefined
  )
}

/**
 * 该行的**是否定型**（issue #4566）—— = 「定型」加工项是否被勾选。
 *
 * 三态语义留在**键的缺席**上：目录里没有「定型」项（老租户未重建目录）⇒ `undefined`
 * ⇒ `buildCraftSpec` **不写该键**（后端按缺值处理，与今天「未指定」档同语义），**不报错**。
 */
export function isShapedFromItems(line: OrderLineItem): boolean | undefined {
  const item = line.processingItems.find((pi) => pi.name === SHAPED_ITEM_NAME)
  if (!item) return undefined
  return line.selectedProcessing[item.id]?.selected === true
}

/**
 * 送进 `buildCraftSpec` / `craftCalcParamsOf` 的**派生后**工艺规格（页面侧**唯一派生点**）。
 *
 * `craft` / `isShaped` 的真值来源已从「工艺规格控件」搬到**加工项**（#4566）⇒ 读侧一律走本函数。
 * ⚠️ `lib/craft-calc-request.ts` **不得**再加第二份派生逻辑（同一真值两处推导 = 页面显示 ≠ 落库）。
 *
 * issue #4874：**用料公式 / 档位**在这里解析成**落库真值**（两者同族，要么都落、要么都不落）——
 * 公式 = `effectiveCraftCalcFormula`（**显式选择 ⇒ 工艺推导 ⇒ 算料配置兜底**；
 * 配置取不到 ⇒ 常量 `pleat`）——⚠️ 必须先工艺推导：否则「打孔 ⇒ 倍数法」（#4527）会被
 * 配置兜底顶掉（页面按韩褶口径发请求、后端按打孔口径算）；
 * 档位 = `line.craft.craftTier ?? defaultCraftCalcTier(配置.tiers)`（**落在配置里真实存在的档位键上**）。
 * 两者都是**读面取值**（前端不持有档位/公式真值）⇒ 页面显示 / 试算请求 / 落库三者同一份。
 *
 * ⚠️ **issue #5020**：`cuttingMode` 也在这里兜底 —— 见 {@link cuttingModeOf}。
 */
export function derivedCraftSpec(line: OrderLineItem, calcConfig: CraftCalcConfig | null): CraftSpecInput {
  const craft = craftFromItems(line)
  return {
    ...line.craft,
    cuttingMode: cuttingModeOf(line),
    craft,
    isShaped: isShapedFromItems(line),
    formula: effectiveCraftCalcFormula({ formula: line.craft.formula, craft }, calcConfig),
    craftTier: line.craft.craftTier ?? defaultCraftCalcTier(calcConfig),
  }
}

/**
 * 该行**实际据以算料 / 落库**的加工类型（issue #5020）—— 页面侧**唯一**读加工类型的入口。
 *
 * - 客服**显式选过**（`line.craft.cuttingMode` 有值）⇒ **逐字返回**（人工覆盖优先，规则永不改判）；
 * - **未指定**（`undefined` / 空串）⇒ 返回**门幅规则推导出的那一档**（**服务端** `doorWidthPlanApi` 的
 *   `effectiveCuttingMode`：定高买宽可行 ⇒ 定高买宽；否则 ⇒ 定宽买高/倒幅）⇒ 加工类型 chips
 *   **自动选中**，且**一点即改**（点一下就把显式值写回 `craft.cuttingMode`，从此不再自动推导）；
 * - 规则判不了（缺尺寸 / 缺门幅 / 表外）⇒ `undefined`（chips 停在「未指定」，**不猜**）。
 *
 * ⚠️ **为什么不复用 `craft.cuttingMode` 直接落库**：那样「未指定」会落一个空键（下游按缺值处理 ⇒
 * 引擎只能自己猜朝向），且界面看不到系统到底按哪种在算 —— 与「商家看得见的真值」纪律相悖。
 * ⚠️ **不新增行状态位**：「显式 vs 未指定」已经由 `craft.cuttingMode` 的**有无**表达（同
 * `openCountTouched` 的留痕精神）⇒ 无需第二个布尔位，也不会出现「两位不同步」。
 */
export function cuttingModeOf(line: OrderLineItem): string | undefined {
  // **单点收敛**（issue #5202）：优先级 = 商家显式选过（**留痕位** `cuttingModeTouched`）
  // → `data.plan.cutting_mode`（算料引擎推导）→ `door-width-plan` 的 `effective_cutting_mode`
  // （几何规则面）→ 默认档兜底 → 不猜。
  // ⚠️ 判「显式」必须看留痕位：`createDefaultCraftSpec()` 也会写 `craft.cuttingMode = 定高买宽`，
  // 只按「有值」判断 ⇒ 默认档恒顶掉服务端推导（三项收敛当场失效）。
  // 实现落在 `lib/craft-auto-features.ts::effectiveCuttingModeOf`（页面**只此一处**读加工类型，
  // chips / 判定面 / 试算面 / 落库四处共用 ⇒ 不会各读各的）。
  return effectiveCuttingModeOf({
    explicit: line.cuttingModeTouched ? line.craft.cuttingMode : undefined,
    plan: line.calc?.plan,
    doorWidthPlan: line.doorWidthPlan,
    defaultValue: line.craft.cuttingMode,
  })
}

/**
 * 「定型」加工项的**默认勾选**（真值源 §10：布帘默认是 / 纱帘默认否）—— 返回新的 `selectedProcessing`。
 *
 * 今天的行为逐字保留（原来由 `defaultIsShapedForBody` 写 `craft.isShaped`，现在写**勾选态**）：
 * 布帘默认**勾上**「定型」、纱帘默认**不勾**。三条边界：
 * ① 商家**手动勾/取消过**定型（`shapedItemTouched`）⇒ 原样返回（不覆盖，同 `openCountTouched` 纪律）；
 * ② 目录里**没有**「定型」项 ⇒ 原样返回（不报错、不凭空造项 ⇒ `isShaped` 落 `undefined`）；
 * ③ 已经等于默认档 ⇒ 原样返回（不做无意义的状态更新）。
 */
export function withShapedDefault(
  line: OrderLineItem
): Record<string, { selected: boolean; qty: number }> {
  if (line.shapedItemTouched) return line.selectedProcessing
  const item = line.processingItems.find((pi) => pi.name === SHAPED_ITEM_NAME)
  if (!item) return line.selectedProcessing
  const selected = defaultIsShapedForBody(line.curtainBody)
  const prev = line.selectedProcessing[item.id]
  if (prev?.selected === selected) return line.selectedProcessing
  return {
    ...line.selectedProcessing,
    [item.id]: { selected, qty: prev?.qty ?? deriveProcessingQty(line.quantity) },
  }
}

/**
 * 「韩褶」加工项的**默认勾选**（2026-09-28 用户裁定：商家只提供净窗宽 / 净窗高，再确认
 * 「是否要韩折 / 打孔 / 定型」即可 ⇒ 推荐组合由系统**预选**，一键「全不采纳」可撤）。
 *
 * 与 {@link withShapedDefault} 三条边界**逐字同构**（手改留痕 / 目录无此项 / 已是目标态），
 * 只多一条：**布料组整组无加工**（#4493）⇒ 不为它勾任何项。
 */
export function withCraftItemDefault(
  line: OrderLineItem
): Record<string, { selected: boolean; qty: number }> {
  if (line.craftItemTouched) return line.selectedProcessing
  if (line.saleForm === SALE_FORM_FABRIC) return line.selectedProcessing
  // ⚠️ **按规范 key 找项**（`craftItemKeyOf`）：目录里的工艺项可能是「韩折」（V139 之前的
  // ERP 写法）而代码里的规范名是「韩褶」—— 直接比名字会让推荐与预选在老目录上**静默失效**
  // （2026-09-29 云测试环境实测：租户目录是「韩折」⇒ 推荐条只剩「定型」）。
  const item = line.processingItems.find(
    (pi) => craftItemKeyOf(pi.name) === craftItemKeyOf(DEFAULT_CRAFT_ITEM_NAME)
  )
  if (!item) return line.selectedProcessing
  const prev = line.selectedProcessing[item.id]
  if (prev?.selected === true) return line.selectedProcessing
  return {
    ...line.selectedProcessing,
    [item.id]: { selected: true, qty: prev?.qty ?? deriveProcessingQty(line.quantity) },
  }
}

/**
 * **推荐组合的预选**（下单页的唯一入口）= 定型（真值源 §10：按帘体）∪ 韩褶（工艺默认）。
 *
 * 三处调用点（目录到达 / 改帘体 / 换商品 / 布料切回成品帘）共用同一个入口 ——
 * 避免两套默认各补一半（同 #4489 的「默认只能有一个来源」纪律）。
 */
export function withRecommendedItemDefaults(
  line: OrderLineItem
): Record<string, { selected: boolean; qty: number }> {
  const withShaped = withShapedDefault(line)
  return withCraftItemDefault({ ...line, selectedProcessing: withShaped })
}

/**
 * **推荐组合的项名**（**目录里的实际名字**，2026-09-28；2026-09-29 改为别名容错）= 工艺默认
 * 「韩褶 / 韩折」+ 帘体的定型默认（真值源 §10：布帘是 / 纱帘否）；布料组整组无加工（#4493）⇒ 空。
 *
 * 与 {@link withRecommendedItemDefaults} 是**同一份口径的两个读法**（预选 / 界面展示）——
 * 名字在这里只出现一次，避免「预选勾了 A、界面推荐写着 B」。
 *
 * ⚠️ 与预选**同一条纪律**：按 {@link craftItemKeyOf} 取规范 key 找项，并把**目录里的名字**
 * 返回（而不是代码里写死的规范名）—— 否则老目录（工艺项叫「韩折」）上推荐条会少一项。
 */
export function recommendedItemNamesOf(line: OrderLineItem): string[] {
  if (line.saleForm === SALE_FORM_FABRIC) return []
  const names: string[] = []
  const craftItem = line.processingItems.find(
    (pi) => craftItemKeyOf(pi.name) === craftItemKeyOf(DEFAULT_CRAFT_ITEM_NAME)
  )
  if (craftItem) names.push(craftItem.name)
  if (defaultIsShapedForBody(line.curtainBody)) {
    const shapedItem = line.processingItems.find(
      (pi) => craftItemKeyOf(pi.name) === craftItemKeyOf(SHAPED_ITEM_NAME)
    )
    if (shapedItem) names.push(shapedItem.name)
  }
  return names
}

/**
 * 该行的**自动识别特征**（issue #4526 · 设计 §5.1/§5.2）—— 纯推导，**不是可勾选项**。
 *
 * 用户 2026-09-19：「超高 / 超宽是和门幅标准比较的……**这个要求做到自动识别**」。
 * 门幅取 SKU 的 `doorWidth`（缺省 2.8）；倒幅由 `cuttingMode` 唯一推导
 * （`定高买宽` = 正幅，**不推导** —— issue #4592：正幅不在加工项目录里，推它会让默认订单
 * 的组合键永远匹配不到价）。
 *
 * ⚠️ 这些特征**进组合键**（`打孔+超高+定型` 与 ERP 逐字同构）⇒ 与手选加工项一起落
 * `processingInfo.processingItems`（服务端的特征名唯一来源就是它），但**不计入手选计数**、
 * 也**不在手选列表里出 checkbox**（判据 8：手选项 ⇒ 红；由 `handPickableProcessingItems` 滤掉）。
 * ⚠️ `定型` 已**不在**本函数里（#4566）：它是手选加工项，其勾选态单独派生 `isShaped`。
 * ⚠️ **本页不是推导真值源**：判定一律**来自服务端** `POST /api/admin/orders/auto-features`
 * （引擎 `curtain_calc.detect_auto_features`）—— 本页**不得**出现第二份推导。
 * 🔴 **issue #5130 改判**：原注释写「判据一律走 `lib/craft-auto-features.ts`（#4662 起「超宽」含**褶倍**）」
 * —— 前端的本地推导实现已随 issue #5035 删除，且**超宽现已不含褶倍**（#4662 判定面已退役）。
 */
/**
 * 该颜色的**默认选中 SKU**（issue #4877 裁定 C：**规则驱动默认选中**）。
 *
 * ① 只有一个 SKU ⇒ 直接选它（既有行为，与门幅规则无关）；
 * ② 多个门幅 ⇒ 交给**门幅规则**（**服务端** `doorWidthPlanApi`：可行集取最小门幅 / 定宽买高取分幅最少）；
 *    **同一最优门幅下有多个 SKU**（散剪/整卷）时也要选出一个**默认**（issue #4899 + #5014：
 *    **散剪（`bulk_cut`）优先** → 有库存优先 → 单价低者优先 → 按 id 稳定）—— 什么都不选会让界面谎报「门幅未维护」；
 *    该默认是**自动选中**（`skuAutoSelected`）⇒ 客服一点即改、规则也会随输入变化重算；
 * ③ 规则不可判定（缺尺寸 / 缺加工类型 / 门幅未维护）⇒ **不自动选**（不猜）。
 *
 * ⚠️ 调用点只有「换颜色」（那里本来就会重置 `selectedSku`）⇒ **不会覆盖客服已手选的门幅**。
 */
export function pickAutoSkuForColor(
  line: OrderLineItem,
  skusOfColor: OrderProductSku[]
): OrderProductSku | null {
  if (skusOfColor.length === 1) return skusOfColor[0]
  // **门幅规则**（**服务端**，issue #5043 包 2b）：规则解的门幅由服务端给 —— 前端**不再本地算**。
  // 规则还没到 / 判不了（缺尺寸 / 缺门幅 / 多门幅但规则不可判定）⇒ `null`（不猜）；
  // 规则到达后由规则 effect 补默认（见 `doorWidthSignature` 那个 effect 的写回）。
  const plan = line.doorWidthPlan
  if (!plan || plan.state !== 'single_panel' || plan.door_width === null) return null
  const exact = skusOfColor.filter((sku) => parseDoorWidth(sku.doorWidth) === plan.door_width)
  if (exact.length === 0) return null
  if (exact.length === 1) return exact[0]
  // **同一最优门幅下有多个 SKU** ⇒ 也必须选出一个**默认**（issue #4899）：
  // 什么都不选 = 界面显示「门幅未维护」（误导：不是没维护，是没选到）+ 客服无从下手。
  // 平局口径：**有库存优先 → 单价低者优先 → 按 id 稳定**。
  //
  // ⚠️ 2026-09-21（V111，用户裁定）：平局口径的**首位**「售卖方式 = 散剪优先」（#5014）**已退场**
  // —— 那条口径的前提是「每个门幅有散剪/整卷两个销售属性」，而用户已裁定售卖方式是
  // **商品级基础属性**、SKU 组合只有 **颜色 × 门幅** ⇒ 同一 (颜色, 门幅) 只有**一行** SKU，
  // 「按售卖方式选哪一支」这个问题本身不存在了（`OrderProductSku` 也已无 `sellingMethod` 字段，
  // 留着这个比较是**死代码**：首项恒为 0）。#5014 的其余判据（有库存/单价/id 三级平局）一字不动。
  const [best] = [...exact].sort(
    (a, b) =>
      Number(Number(b.stock ?? 0) > 0) - Number(Number(a.stock ?? 0) > 0) ||
      Number(a.price ?? 0) - Number(b.price ?? 0) ||
      String(a.id).localeCompare(String(b.id))
  )
  return best ?? null
}

/**
 * 该行的自动特征 —— **判定来自服务端**（issue #4976 包 2b，用户 2026-09-21 裁定 B
 * 「**判定移到服务端**」，前端只展示服务端结论）。
 *
 * ⚠️ **本页不再本地推导**：此前的 `detectAutoFeatures(...)` 调用已退场（静态判据
 * `orders-new-auto-features.test.ts` 的「本页不得本地判特征」钉住）。
 *
 * 为什么必须搬：判定进**加工费组合键**（`processingInfo.processingItems[].name`）⇒ 判定即钱。
 * 服务端判定用的是**该租户的配置**（`hem_margin` / 档位褶倍；宽方向余量 `side_margin` 已按 issue #5030 **整体退场**）与**该 SKU 的门幅**，
 * 而前端只持有一份常量副本 ⇒ 商家改过配置后两边会算出不同的键（本单要消灭的正是这种脱钩）。
 *
 * 只保留服务端认得的名字（`AUTO_FEATURE_NAMES` 与加工项目录 V83 逐值对齐，有守卫）——
 * 服务端若返回目录里没有的名字，进组合键会**永远匹配不到价** ⇒ 宁可漏也不要污染键。
 */
export function autoFeaturesOf(line: OrderLineItem): AutoFeature[] {
  const rows = line.autoFeatures?.auto_features ?? []
  return rows
    .filter((f) => (AUTO_FEATURE_NAMES as readonly string[]).includes(f.name))
    .map((f) => ({ name: f.name as AutoFeatureName, source: '推算' as const, reason: f.reason }))
}

/** 自动特征判定的**入参**（`null` = 宽高没填齐 ⇒ 不发请求，提交校验本来也拦） */
export function autoFeatureParamsOf(
  line: OrderLineItem,
  calcConfig: CraftCalcConfig | null
): AutoFeaturesParams | null {
  const width = Number(line.width)
  const height = Number(line.height)
  if (!Number.isFinite(width) || width <= 0) return null
  if (!Number.isFinite(height) || height <= 0) return null
  const params: AutoFeaturesParams = { width, height }
  // 门幅：**取该 SKU 的**（`parseDoorWidth` 是唯一解析点，issue #4877）。
  // 解析不到 ⇒ **不发该键**（**不回落默认门幅**）。
  // ⚠️ 它**不参与**超高/超宽的判定（issue #5130 起判定读**企业阈值参数**）——
  // 它只剩「几何矛盾」提示与回显用途。
  const doorWidth = parseDoorWidth(line.selectedSku?.doorWidth)
  if (doorWidth !== null) params.fabric_width = doorWidth
  // ⚠️ issue #5020（rebase 时采纳 main 的口径）：走**派生后**的加工类型（`cuttingModeOf`），
  // 不是 `line.craft.cuttingMode` —— 后者在「未指定」时是 `undefined` ⇒ 判定面「两个方向都不判」，
  // 而规则面已按自动解算料 ⇒ **界面显示 ≠ 落库**（正是本单要消灭的那种不一致）。
  const cuttingMode = cuttingModeOf(line)
  if (cuttingMode) params.cutting_mode = cuttingMode
  // 🔴 issue #5130：两个**企业阈值参数**是超高/超宽判据 ⇒ **必须随请求下发**。
  // 不下发 ⇒ 引擎回落默认值 ⇒ 商家在「算料配置」里改的阈值**静默不生效**
  // （可配却不生效 = 本仓明令禁止的形态；同族先例：issue #5030 的 `side_margin`）。
  if (calcConfig) params.config = calcConfig
  return params
}

/** 判定入参签名：**只含入参**（判定结果写回行状态 ⇒ 用它当依赖会自激成请求风暴） */
export function autoFeatureParamsSignature(params: AutoFeaturesParams | null): string {
  if (params === null) return ''
  return [
    params.width,
    params.height,
    params.fabric_width ?? '',
    params.cutting_mode ?? '',
    // 企业阈值改了 ⇒ 签名变 ⇒ 重发判定（否则商家改了配置、页面停在旧判定上）
    params.config?.oversize_width_threshold ?? '',
    params.config?.oversize_height_threshold ?? '',
  ].join('|')
}

/**
 * 门幅规则的**入参**（issue #5043 包 2b）—— `null` = 宽高没填齐 / 该颜色没有可用门幅 ⇒ 不发请求。
 *
 * ⚠️ **只传「客服显式选的」加工类型**：**不能**传 {@link cuttingModeOf} —— 那一档正是本请求要
 * 算出来的东西（用它当入参 = 自激 + 循环依赖）。
 */
export function doorWidthParamsOf(
  line: OrderLineItem,
  calcConfig: CraftCalcConfig | null
): DoorWidthPlanParams | null {
  const width = Number(line.width)
  const height = Number(line.height)
  if (!Number.isFinite(width) || width <= 0) return null
  if (!Number.isFinite(height) || height <= 0) return null
  const doorWidths = (line.product?.skus ?? [])
    .filter((sku) => sku.colorId === line.selectedColorId)
    .map((sku) => parseDoorWidth(sku.doorWidth))
    .filter((g): g is number => g !== null)
  if (doorWidths.length === 0) return null
  // 🔴 **用料口径必须与算料同源**（2026-09-30 现取实测）：门幅依据文案里会回显「用料 N 米」，
  // 本请求若不带 `formula`，服务端就按**默认公式**算词 —— 实测同屏出现「门幅依据 用料 6.4 米」
  // vs「公式 / 摘要 / 算料 6.3 米」（6.4 = 倍数法 2×3.2，6.3 = 韩褶公式 0.25×24+0.3）
  // ⇒ 商家看到同一件事两个数。故**取算料同一份入参**（`craftCalcParamsOf(calcInputOf(...))`，
  // 与上面试算 effect 逐字同源），页面不另拼第二份口径。
  // ⚠️ 同时**不再塞常量 `fullness`**：算料请求根本不发它（褶倍/档位由服务端按 `craft_tier`
  // + 租户算料配置解析）⇒ 留着它就是第二份口径（正是本次分叉的形态）。
  const calc = craftCalcParamsOf(calcInputOf(line, calcConfig))
  const params: DoorWidthPlanParams = {
    width,
    height,
    door_widths: doorWidths,
    open_count: calc?.open_count ?? line.craft.openCount,
  }
  if (calc?.mounting) params.mounting = calc.mounting
  if (calc?.craft_tier) params.craft_tier = calc.craft_tier
  if (calc?.formula) params.formula = calc.formula
  if (calc?.craft) params.craft = calc.craft
  if (calc?.has_pattern !== undefined) params.has_pattern = calc.has_pattern
  if (calc?.pattern_repeat !== undefined) params.pattern_repeat = calc.pattern_repeat
  if (line.craft.cuttingMode) params.cutting_mode = line.craft.cuttingMode
  const selected = parseDoorWidth(line.selectedSku?.doorWidth)
  if (selected !== null) params.selected_door_width = selected
  return params
}

/** 规则入参签名：**只含入参**（结果写回行状态 ⇒ 用它当依赖会自激成请求风暴） */
export function doorWidthParamsSignature(params: DoorWidthPlanParams | null): string {
  if (params === null) return ''
  return [
    params.width,
    params.height,
    params.door_widths.join(','),
    params.cutting_mode ?? '',
    params.selected_door_width ?? '',
    params.open_count ?? '',
    // 用料口径（与算料同源的那些键）**必须进签名** —— 漏项 ⇒ 改了公式/工艺不重发
    // ⇒ 门幅依据静默停在旧口径（与判据 2 的「签名漏项」同族）
    params.mounting ?? '',
    params.craft_tier ?? '',
    params.formula ?? '',
    params.craft ?? '',
    params.has_pattern ?? '',
    params.pattern_repeat ?? '',
  ].join('|')
}

/**
 * 提交闸门（issue #4976 包 2b）：**判定没就绪 ⇒ 不许提交**。
 *
 * 与既有「加工费计价闸门」（#4450）同口径：组合键是**服务端取价的键**，
 * 判定缺席 ⇒ 键少一项 ⇒ 服务端按另一个组合取价（或取不到价）⇒ 页面总额 ≠ 服务端总额
 * ⇒ 被创建路径的「实收金额与应收不一致」拒单（或**少收/多收**）。
 * ⇒ 宁可让商家等一下，也不发一个键不完整的单。
 */
export function autoFeaturesBlockReason(
  lineItems: OrderLineItem[],
  calcConfig: CraftCalcConfig | null
): string | null {
  for (const line of lineItems) {
    if (autoFeatureParamsOf(line, calcConfig) === null) continue
    if (line.autoFeaturesError) return '自动识别判定失败，请稍候重试后再提交'
    if (!line.autoFeatures) return '自动识别判定中，请稍候再提交'
  }
  return null
}

/**
 * 该行要**显式告知**商家的提示 —— **2026-09-22 改判（issue #5130）后只剩一类**：
 * 加工类型与**几何**矛盾 ⇒ 系统实际会按哪种算。
 *
 * ⚠️ 提示**不是特征**：不进组合键、不改推算（裁定 C 的前半句「以商家选的为准」）。
 * 🔴 **issue #5036 起来源 = 服务端**（用户 2026-09-21 裁定「统一迁移到服务端；未来 agent 也需要」）
 * —— 见下，本页只展示。
 * 🔴 **issue #5130 改判**：旧的两类（缺门幅 ⇒ 都判不了 / 缺褶倍 ⇒ 未判超宽）已随判据替换**退役**
 * —— 它们说的是**旧判据**（与门幅 / 褶倍比），在新判据下是**假话**。
 * 「门幅未维护」的告知由几何层徽标承担（`door-width-missing` / `size-door-width-missing`）。
 */
export function autoFeatureNoticesOf(line: OrderLineItem): AutoFeatureNotice[] {
  // 🔴 issue #5036：提示改由**服务端**给（用户 2026-09-21 裁定「统一迁移到服务端；未来 agent 也需要」）
  // —— 引擎读的是**该租户配置**的 `hem_margin`（宽方向余量已按 issue #5030 退场）⇒ 与判定**同源**。
  // 迁移前本函数在前端本地算、读**模块常量副本**（0.3）⇒ 租户改过 `hem_margin` 后这里会显示
  // **错的数**，且「几何矛盾」的**判断本身**也会错 —— 那正是本单要消灭的脱钩。
  // 本页只**展示**：`kind` / `reason` 一律照服务端返回，**不编**口径（`#4662` 的裁定 C 不变）。
  return line.autoFeatures?.notices ?? []
}

/** 强制加那一行的依据文案（系统没推算依据可引用 ⇒ 照实说明「未推算」，不编一个理由） */
export const MANUAL_ADD_REASON = '系统未推算，商家手动加'

/**
 * 该行**推导项裁决 / 落库 / 拼接派生**的**同一份**入参（issue #5230 收敛）——
 * 面板显示、`processingInfo.specialOptions`、**拼接派生**三处都经它 ⇒ 不可能各说各话。
 *
 * ⚠️ `joinWidthOverride`（人工加接宽）也要在场：它**不进** `specialOptions`（接宽没有选项出口，
 * 用户 2026-09-23 裁定「移除接宽逻辑」），但它是**拼接派生**的判据之一 ——
 * 漏一处就会出现「商家人工加了接宽、拼接却没进组合键」。
 */
export function derivedOptionInputOf(line: OrderLineItem) {
  return {
    manualOptions: line.craft.specialOptions,
    plan: line.calc?.plan,
    spliceTimesOverride: line.planOverrides?.spliceTimes,
    joinHeightOverride: line.planOverrides?.joinHeightM,
    joinWidthOverride: line.planOverrides?.joinWidthM,
    rejectedOptions: line.rejectedDerivedOptions,
  }
}

/** 该行**手选控件**里是否勾了某个名字的加工项（手选优先：同一名字不得在组合键里算两次） */
export function isHandPickedProcessingItem(line: OrderLineItem, name: string): boolean {
  return line.processingItems.some(
    (pi) => pi.name === name && line.selectedProcessing[pi.id]?.selected === true
  )
}

/**
 * 派生加工项「拼接」那一行的**依据文案**（issue #5230）—— 说清是**接高还是接宽**带来的接缝，
 * 并照实写明「拼N次不派生」（商家核对判定时要看得见边界）。
 */
export function joinSpliceReasonOf(line: OrderLineItem): string {
  const names = effectiveJoinSourceNamesOf(derivedOptionInputOf(line))
  return `${names.join(' / ')}发生 ⇒ 一幅帘由多块布接成，需拼接工序（派生自接高/接宽；拼N次不派生）`
}

/**
 * 系统识别块的**展示行** —— 系统推算的（含被不采纳的）+ 商家强制加的 + **派生加工项**。
 *
 * 单一真值：推算一律走 {@link autoFeaturesOf}（**服务端判定**，issue #4976 包 2b ——
 * 用户裁定 B「判定移到服务端」）—— **本页不得出现第二份推导**
 * （静态判据钉住：页面里不得再出现本地判特征调用 `detectAutoFeatures(…)`）。
 *
 * ⚠️ **「拼接」是唯一走这一块的派生加工项**（issue #5230）：它进的是 `processingItems[]`
 * （顾客侧加工费组合键）而不是 `specialOptions` —— 与接高 / 接宽那两条**工序 + 计件**的通路
 * **并行且互斥**（同一件事的两笔账）。它同样可**不采纳**（`rejectedAutoFeatures` 按名留痕）。
 */
export function autoFeatureRowsOf(line: OrderLineItem): SystemAutoFeatureRow[] {
  const rejected = line.rejectedAutoFeatures ?? []
  const detected = autoFeaturesOf(line)
  const rows: SystemAutoFeatureRow[] = detected.map((f) => ({
    ...f,
    rejected: rejected.includes(f.name),
  }))
  for (const name of new Set(line.manualAutoFeatures ?? [])) {
    // 强制加：只认自动识别清单里的名字（不凭一个字符串造出目录里没有的组合键加项 —— #4592 的教训）
    if (!(AUTO_FEATURE_NAMES as readonly string[]).includes(name)) continue
    // 系统已推算出来的不重复列（生效值里也不会出现两次）
    if (detected.some((f) => f.name === name)) continue
    rows.push({
      name: name as AutoFeatureName,
      source: '手动加',
      reason: MANUAL_ADD_REASON,
      rejected: false,
    })
  }
  // 派生「拼接」（issue #5230 口径 3 / 判据 3、4、5、6、8）：
  // 接高**生效**（在生效特殊选项里）或 接宽**发生**（缺口合法）⇒ 派生；两者都没有 / 接高被不采纳
  // ⇒ 不派生；**拼N次不派生**（裁定边界）。商家已手工勾了拼接 ⇒ 不重复派生（同一名字只出现一次）。
  const spliceItem = derivedJoinSpliceItemOf(derivedOptionInputOf(line))
  if (spliceItem !== null && !isHandPickedProcessingItem(line, spliceItem)) {
    rows.push({
      name: spliceItem,
      source: '推算',
      reason: joinSpliceReasonOf(line),
      rejected: rejected.includes(spliceItem),
    })
  }
  return rows
}

/**
 * 该行的**生效**自动识别特征 = `推算 ∪ 强制加 − 不采纳`（issue #4657）——
 * **唯一**喂给加工费组合键的清单（界面徽标与 `processingDetailsOf` 共用它，
 * 绝不允许「两个来源各说各话」）。
 *
 * 为什么合成放在**页面侧**而不是 `lib/craft-auto-features.ts`：那个文件是**推导判据**的
 * 单一真值（判据修正另有其单），本函数是**商家裁决**的合成 —— 两者变化原因不同，
 * 且裁决态是**行状态**（随行落库 ⇒ 日后判据变化不影响已下的单）。
 */
export function effectiveAutoFeaturesOf(line: OrderLineItem): SystemAutoFeatureRow[] {
  return autoFeatureRowsOf(line).filter((row) => !row.rejected)
}

/** 该行已勾选的加工项明细（提交 payload 与加工费预览**共用**这一份构造） */
export function processingDetailsOf(line: OrderLineItem): Array<Record<string, unknown>> {
  const handPicked = Object.entries(line.selectedProcessing)
    .filter(([, v]) => v.selected)
    .map(([piId, v]) => {
      const pi = line.processingItems.find((p) => p.id === piId)
      if (!pi) return null
      // issue #4882：快照收缩为 `{id, name, quantity, unit}` —— 单价 / 小计 / 计价方式整体不落
      // （后端 `processing_items` 已无这些列；钱由「加工费组合」按 `[].name` 派生组合键取价）。
      return {
        id: pi.id,
        name: pi.name,
        quantity: Math.max(1, Number(v.qty) || 1),
        unit: pi.unit,
      }
    })
    .filter(Boolean) as Array<Record<string, unknown>>

  // 自动识别特征（R9/D6）：与手选加工项**同一数组** —— 服务端 `featureNames` 只读
  // `processingItems[].name`（`ProcessingFeeQueryService.featureNames`），**带上了**才进组合键
  // ⇒ **组合加项 = 手选加工项 ∪ {超高, 超宽, 倒幅}**（设计 §5.3 特征集合）。
  // ⚠️ 本数组是组合键的真值源 ⇒ 这里**不得**出现 `processing_items` 目录（V83）里没有的名字：
  //    #4592 实测 `正幅` 就因此让**每张默认订单**的组合键永远匹配不到价（加工费恒 ¥0.00）。
  // 它们**没有单价**（不在加工项目录里）：钱由**组合价目**决定（R10 的前提）——
  // ⚠️ #4882 后连加工项本身也不再有单价 ⇒ 这里更不该出现任何价格键（快照只留 name + quantity）。
  const derived = effectiveAutoFeaturesOf(line).map((feature) => ({
    name: feature.name,
    quantity: 1,
  }))

  return [...handPicked, ...derived]
}

/**
 * 逐行 `processingInfo` 的**唯一构造点**（issue #4450）。
 *
 * 为什么必须唯一：加工费试算（`POST /orders/fee-preview`）与提交落库**必须看到同一份选配** ——
 * 组合键由 `processingItems[].name` 派生、加工费米数由 `processingMeters` / `fabric_meters` 取
 * （`ProcessingFeeCalculator.METER_KEYS`）。两处各拼一份 ⇒ 「页面显示 ≠ 落库」（#4406 的 R10）。
 *
 * ⚠️ **不含 `processingFee`**：它由服务端取价结果决定（写进来就是循环依赖）；
 * 提交时由调用方补上服务端返回的那个数。
 */
export function buildLineProcessingInfo(
  line: OrderLineItem,
  calcConfig: CraftCalcConfig | null
): Record<string, unknown> | undefined {
  const sku = line.selectedSku
  const colorName = uniqueColors(line.product?.skus).find(
    (c) => c.id === line.selectedColorId
  )?.name
  const processingDetails = processingDetailsOf(line)

  // 工艺规格落库（issue #4375 §4.2/§4.5）：只落用户真填了的键（缺值不写）。
  // 拼色（双拼）时主布行额外绑组（§4.8）：componentRole=主布 + craftLineId。
  // ⚠️ **套窗跨行分组已移除**（issue #4486，用户裁定）：不再写 `buildWindowGroupKey`。
  //    但 **`craftLineId` 自指仍保留** —— 它是 §4.8「配布边行被主布行吸收」的配对键
  //    （消费端 `isAbsorbedEdgeRow` 按组键判定），删了配布边行会独立成部位。
  // **布料单无加工**（issue #4493，用户裁定）：不写任何工艺规格、不写加工项。
  // ⇒ 下游（订单详情 / 加工单）的「工艺规格」块自然不出现，且加工单不会被生成
  //   （`ProcessingOrderService` 以「无加工项」拦），与既有链路零冲突。
  const isFabric = line.saleForm === SALE_FORM_FABRIC
  const edgePrice = isFabric ? null : edgeUnitPriceOf(line)
  // **有同行件**（配布边）时主布行才写绑组键：
  // 两行必须共用**同一个客户端行标识**，否则消费端 `craftGroupKey` 按各自 `itemId` 成组
  // ⇒ 一套帘被算成两套 ⇒ 套级工序（外帘打卷/装袋/发货）实例化两次、计件双付（#4395 的病根）。
  // ⚠️ issue #4874：`布帘+纱帘` 那一档（第二条纱帘明细行）已整体删除 ⇒ 这里只剩配布边一种同行件。
  const isPaired = edgePrice !== null
  // 部位（issue #4521）：主帘缺省即布帘 ⇒ **不写**；只有「只买纱帘」显式写 `curtainType=纱帘`
  // （它是**另一个部位** —— 不写就会被下游当成布帘，取到错的工序路线）。
  const curtainType = isFabric ? undefined : curtainTypeOfBody(line.curtainBody)
  const mainSpec = isFabric
    ? {}
    : {
        // `craft` / `isShaped` 由**加工项**派生（#4566）⇒ 走唯一派生点，不读 `line.craft` 的那两个键
        ...buildCraftSpec({
          ...derivedCraftSpec(line, calcConfig),
          // **推导出的项并入生效特殊选项**（issue #5211：拼N次 / 接高）—— 单点：面板显示、
          // 计价预览入参、提交 payload 三者同源（`effectiveSpecialOptionsOf` =
          // 手工勾选 ∪ 推导项 − 不采纳）。接宽**不在本单**（issue #5214：全仓无该选项/工序出口）。
          // 为什么必须落地：`processingInfo.specialOptions` 的下游是**插工序**（`拼2次-布` /
          // `接高-布`）与**计件**（拼次 0.8/1.2/1.6、接高 1.0 元/幅）⇒ 只显示不落地 = 工人不报工、
          // 计件少发钱，而且**不报错**（静默少东西）。
          // ⚠️ 落点是 `specialOptions`（工序 + 计件）**不是** `processingItems`（加工费组合键，
          //    那是顾客侧价格的另一条通路 —— 见 issue #5211 的订正段）。
          specialOptions: effectiveSpecialOptionsOf({
            manualOptions: line.craft.specialOptions,
            plan: line.calc?.plan,
            spliceTimesOverride: line.planOverrides?.spliceTimes,
            joinHeightOverride: line.planOverrides?.joinHeightM,
            rejectedOptions: line.rejectedDerivedOptions,
          }),
        }),
        ...(curtainType ? { curtainType } : {}),
        ...(isPaired ? buildMainLineGroupKeys(line.id) : {}),
      }

  // **部位备注**（issue #5685）：商家手写的「这个数字怎么来的」（算料依据说明）——
  // 落库载体 = `processingInfo.remark`（JSONB 顶层字符串，与 `craft` / `formula` 同层）。
  // **缺值不落键**（空串 / 纯空白 ⇒ 视为未填）：写 `""` 会被下游读成「填过」，详情页多一行空值。
  // 上限 200 由录入控件 `maxLength` 挡（服务端不截断，页面也不静默截断）。
  const remark = line.remark?.trim()
  // **安装位置**（issue #7856）：同一口径 —— 有值才落键，空串 / 纯空白 = 未填。
  const installRoom = line.installRoom?.trim()

  if (
    processingDetails.length === 0 &&
    !sku &&
    !colorName &&
    Object.keys(mainSpec).length === 0 &&
    !isFabric &&
    // 只填了备注 / 安装位置的行**不得**被整份丢掉（否则商家写了「公式--48个折」而 payload 里什么都没有）
    !remark &&
    !installRoom
  ) {
    return undefined
  }

  const info: Record<string, unknown> = {
    // **售卖形态显式落库**（issue #4493，用户裁定「显式写 saleForm」）：
    // 不靠「有没有加工项」推导 —— 那是派生信号，会让「布料单」与「成品单**漏选**加工项」
    // 在下游长得一模一样（前者正常、后者是错单），报表与排查分不开。
    // 存量单无该键 ⇒ 读侧按「有加工项 = 成品帘」兜底（见 `readSaleForm`）。
    saleForm: line.saleForm,
    colorId: line.selectedColorId ?? undefined,
    colorName,
    skuId: sku?.id,
    skuCode: sku?.skuCode,
    // ⚠️ SKU 不再带售卖方式（SKU 组合 = 颜色 × 门幅，售卖方式是**商品级基础属性**）
    // ⇒ 本行售卖方式偏好不再由 SKU 派生；行级 `sellingMethod` 由订单侧另行承载
    doorWidth: sku?.doorWidth,
    ...(isFabric ? {} : { processingItems: processingDetails }),
    ...mainSpec,
  }

  // 部位备注（issue #5685）：**有值才落键**（缺值不写 `""`）—— 逐字透传商家的输入（只去首尾空白）。
  if (remark) info.remark = remark
  // 安装位置（issue #7856）：同上 —— 缺值不落键（写 `""` 会被下游读成「填过」，纸面多印一行空值）。
  if (installRoom) info.installRoom = installRoom

  // 加工费米数（裁定 R-b：= 该套窗**主布行**米数）+ 算料输出（#4273：输入与输出都要落）。
  // ⚠️ `ProcessingFeeCalculator.METER_KEYS = (processingMeters, fabric_meters)` ——
  //    一个都不写 ⇒ 服务端判「缺加工费米数」⇒ 加工费按 0 计（#4450 实证的第二处缺口）。
  const meters = Number(line.quantity)
  if (Number.isFinite(meters) && meters > 0) info.processingMeters = meters
  const calcMeters = Number(line.calc?.fabric_meters)
  if (Number.isFinite(calcMeters) && calcMeters > 0) info.fabric_meters = calcMeters
  // **算料输出逐键落库**（issue #4273）：加工单实例化的「应做数量」按 `calc_info` 取真值 ——
  // 「折」类读 `pleat_count`（`routing.py` 的 FOLD_KEYS）、「幅」类读 `panels`（PANEL_KEYS）；
  // 缺键 ⇒ 折/幅/套类**兜底 1** 且 `qty_source=fallback`（车间按 1 折报工 = 假完工）。
  // 键名 = 试算响应同键 = 下游 `ProcessingOrderService.CALC_INFO_KEYS` 白名单口径
  // ⇒ **只透传、零映射、不自拼**（前端换算 = 第二份算料逻辑）。
  // **缺值不写**：算料没产出该键（倍数法无褶数 ⇒ `pleat_count=0`；定高买宽无幅数 ⇒ `plan.panels=null`）
  // ⇒ 不落键 —— 写 0/null 会被下游当成真值（「不做」与「没算」必须可区分）。
  const pleatCount = Number(line.calc?.pleat_count)
  if (Number.isFinite(pleatCount) && pleatCount > 0) info.pleat_count = pleatCount
  const perPanelPleats = Number(line.calc?.per_panel_pleats)
  if (Number.isFinite(perPanelPleats) && perPanelPleats > 0) info.per_panel_pleats = perPanelPleats
  // 幅数（`panels`）：引擎产出在推导方案里（`plan.panels`，issue #5201），订单层键名是**扁平**的
  // `panels`（`CALC_INFO_KEYS` / `CALC_OUTPUT_SNAPSHOT_KEYS` 同口径）—— 同一份引擎输出的**搬运**，
  // 不是第二次推导（逐值断言 = 同文件单测判据 1）。
  const panels = Number(line.calc?.plan?.panels)
  if (Number.isFinite(panels) && panels > 0) info.panels = panels
  const fullness = Number(line.calc?.fullness)
  if (Number.isFinite(fullness) && fullness > 0) info.fullness = fullness
  const fullnessActual = Number(line.calc?.fullness_actual)
  if (Number.isFinite(fullnessActual) && fullnessActual > 0) info.fullness_actual = fullnessActual
  // 算料公式串（issue #4546）：把**试算响应**里的 `formula_text` 原样落进订单层 camelCase 键
  // `formulaText` —— 详情页据此告知商家「用料是怎么算出来的」。
  // 🔴 **只透传、不得自拼**（`lib/api.ts` 头注释：公式串由 ai-agent 后端产出，前端自拼 = 第二份算料逻辑）。
  // **无试算结果 ⇒ 不写该键**（写空串会让详情页多出一行空值）。
  const formulaText = line.calc?.formula_text
  if (typeof formulaText === 'string' && formulaText.trim() !== '') info.formulaText = formulaText

  // **加工费就地改单价**（issue #4874）：只在「未定价 **且组合键非空**」时有值（页面侧的入口
  // 也只在这时出现）—— 组合键为空时改了也无处同步（后端的 key 就是它）。
  // ⚠️ 它与 `processingItems` **同一份构造** ⇒ 试算（`feePreview`）与提交看到的是同一个价。
  const override = Number(line.processingFeeOverride)
  // #7658：`0` 是有效单价（本单免加工费）⇒ 只有 `null` / 非数值才表示「不改价」
  if (line.processingFeeOverride != null && Number.isFinite(override) && override >= 0) {
    info.processingFeeOverride = override
  }

  return info
}

/**
 * 面料米数变化 ⇒ 已选中加工项的 `per_meter` 数量联动（issue #3005 回滚 #2986）。
 *
 * 抽成纯函数：手工改数量（`handleLineQtyChange`）与算料试算写回（issue #4434）**必须走同一条**，
 * 否则两条路径对「加工项数量」的口径会分叉。
 */
export function requantifyProcessing(
  line: OrderLineItem,
  meters: number
): Record<string, { selected: boolean; qty: number }> {
  const next: Record<string, { selected: boolean; qty: number }> = { ...line.selectedProcessing }
  Object.entries(next).forEach(([piId, cfg]) => {
    if (!cfg.selected) return
    // 目录里找不到该项（勾选后被停用/移除）⇒ 保持原数量，不凭空改（同 #4882 前的处置）
    if (!line.processingItems.some((p) => p.id === piId)) return
    next[piId] = { ...cfg, qty: deriveProcessingQty(meters) }
  })
  return next
}

/**
 * 门幅 → 成品高**默认值**（用户 2026-09-19 裁定）：
 * 「选完窗帘的门幅后，就可以把门幅高度默认设置为商品的高了，不用手填，**允许用户改**即可」。
 *
 * ⚠️ **只在「定高买宽」下默认**：定高布的**门幅就是它的固定高度**（2.8m）⇒ 默认成立；
 * 定宽买高时门幅是**宽度**（如 1.4m），拿它当高是错的 ⇒ 不默认（宁可不填，也不填一个错的）。
 * 取不到数字 ⇒ `null`（不猜、不填 0）。
 */
export function heightFromDoorWidth(doorWidth: string | undefined): number | null {
  if (!doorWidth) return null
  const m = String(doorWidth).match(/(\d+(?:\.\d+)?)/)
  if (!m) return null
  const n = Number(m[1])
  return Number.isFinite(n) && n > 0 ? n : null
}

/**
 * ~~宽 → 打开方式（真值源 §10 的启发式）~~ —— **已整体删除**（2026-09-29 用户裁定逐字：
 * 「打开方式默认改成双开，**不要自动推算**」）。
 *
 * 缺省档改由 `lib/order-craft-fields.ts::DEFAULT_OPEN_COUNT`（双开）承担；改窗宽**不再**联动开数。
 * 留痕位 `openCountTouched` 一字未动（商家手改过的值仍然只由商家自己改回）。
 */

/**
 * 人工加 / 改推导项的状态合并（issue #5202）：`null` / `undefined` = **清掉该项**（回到由推导决定）；
 * 数字 ⇒ 原样留在状态里（**越界的也要留** —— 留了页面才报得出「超限」，请求面由 `joinGapOf` 拒发）。
 */
export function mergePlanOverrides(
  prev: CraftPlanOverrides | undefined,
  patch: { spliceTimes?: number | null; joinHeightM?: number | null; joinWidthM?: number | null }
): CraftPlanOverrides {
  const next: Record<string, number> = { ...(prev ?? {}) } as Record<string, number>
  for (const [key, value] of Object.entries(patch)) {
    if (value === null || value === undefined) delete next[key]
    else next[key] = value
  }
  return next as CraftPlanOverrides
}

/**
 * 正数 ⇒ 原样；其余（空 / 0 / 负数 / 非数）⇒ `null` —— **数字输入框的提交口径**
 * （原 `decimalOrNull(raw: string)` 的等价物：数字框已经把文本解析成数字，故这里收数字）。
 */
export function positiveOrNull(value: number | null): number | null {
  return value !== null && Number.isFinite(value) && value > 0 ? value : null
}

/**
 * 「本单加工费单价」的取值口径（issue #7658）：**0 是有效价**（免加工费），负数 / 非数值 = 没填。
 *
 * ⚠️ 与 {@link positiveOrNull} **刻意分开**：那 8 个数字框里 0 是「没填」（单价 0 元 / 米数 0 是不成立
 * 的输入），而加工费单价填 0 是商家的**明确意思**（这一单不收加工费）⇒ 用同一个口径会把 0 丢掉，
 * 正是用户 2026-10-24 报的「改成 0 后费用明细未联动」。
 */
export function nonNegativeOrNull(value: number | null): number | null {
  return value !== null && Number.isFinite(value) && value >= 0 ? value : null
}

/**
 * 本页 8 个数字框**一律用共享 `NumberInput`**（issue #5210 收敛：原先的页面私有 `NumberField`
 * 与 `components/ui/NumberInput.tsx` 是同一真值的两份实现 —— 「要么收敛，要么显式登记，不许静默并存」）。
 *
 * 病根（issue #5202 · 用户第 7 点「不能直接输入 0，所以导致无法输入 0.？」）：受控数字框把值经
 * `Number` 承载（`value={qty || ''}` / `Number(raw)`）⇒ 输入 `0` 被渲染成空串、输入 `0.` 被
 * `Number('0.') = 0` 顶掉 ⇒ **永远打不出 `0.5`**（窄窗真实存在）。两份实现都用
 * `type="text"` + `inputMode="decimal"` + 字符串草稿解决它。
 *
 * ## 收敛口径（等价优先；逐站点证据见 issue #5210，测试 = `tests/unit/pages/orders-new-number-parity.test.tsx`）
 *
 * - `decimals={3}`：本页这 8 格**都没有本地精度校验**（`validate()` 只校验 `> 0`），旧实现原样承载
 *   任意位数 ⇒ 取 2（组件默认）会**新增**「3 位小数被静默改值」的行为差异（尺寸/米数直接改钱），
 *   取 3 则把差异收窄到 >3 位（<1 毫米 / <0.1 分）；且接高那格的服务端可辨粒度本就是 3 位
 *   （`curtain_calc.derive_plan` 对人工接高取 `round(float(join_height_m), 3)`）。
 * - **不传 `min` / `max`**：旧实现从不夹紧，本页非法值一律由**可见校验**兜底（「数量须大于 0」/
 *   「单价须大于 0」/「未填宽（米）」/ 接高上限**就地报错**）⇒ 传 `min`/`max` 等于让输入框
 *   **静默改值**（接高那格尤其：页面明确要求不得把 0.15 静默截成 0.1）。
 * - **不传 `allowEmpty`**（默认 `true`）：旧实现在「清空 + 失焦」后同样落 `null`（各站点再分别落
 *   0 / null）⇒ 同口径；`false` 会把清空**回退到上一个有效值** = 新增行为差异。
 * - `className` 逐字沿用各站点原有字面量（`check-ui-regression.sh` 比对 neutral token）。
 */

/**
 * 商品卷长 → 行上的「每卷米数」默认值（issue #5846，用户裁定 A）。
 *
 * 用户口径：「下单页**默认带出**商品 `products.roll_length_m`」。商品未配 / 非正值 ⇒ `null`
 * （**不落 0、不猜**：「不知道」不许伪装成「0 米一卷」—— 与 `ProductRollAllocation` 同一条红线）。
 *
 * ⚠️ 它只是**输入框的默认值**（用户没动过它 ⇒ 不进 payload，服务端照旧按货号卷长派生）；
 * 用户把它改成别的值 ⇒ 才作为**显式**每卷米数下发。
 */
export function defaultRollLengthOf(product: ProductDetail | null | undefined): number | null {
  const v = Number(product?.rollLengthM)
  return Number.isFinite(v) && v > 0 ? v : null
}

/**
 * 行状态 → 建单 payload 的整卷售卖两个键（issue #5846）。
 *
 * 🔴 **两个键各自独立**（用户 2026-10-01 **二次裁定取消「成对」契约**）：给哪个发哪个，
 * 缺的那一半由服务端**回落**（显式 ?? 货号卷长），回落不到 ⇒ 保持 NULL（不猜）。
 *
 * - 卷数填了（含 `0` —— 「全散剪」是真实结论）⇒ 发 `rollCount`；
 * - 每卷米数**被用户改过**（≠ 商品卷长）或**卷数填了且该格有值** ⇒ 发 `rollLengthM`；
 *   仍是商品默认值（没动过）⇒ **不发**（让服务端按货号卷长派生，与改造前的请求体一致）。
 */
export function rollFieldsOf(line: OrderLineItem): { rollCount?: number; rollLengthM?: number } {
  const fields: { rollCount?: number; rollLengthM?: number } = {}
  const rollsFilled = typeof line.rollCount === 'number'
  if (rollsFilled) {
    fields.rollCount = line.rollCount as number
  }
  if (typeof line.rollLengthM === 'number') {
    const touched = line.rollLengthM !== defaultRollLengthOf(line.product)
    if (rollsFilled || touched) {
      fields.rollLengthM = line.rollLengthM
    }
  }
  return fields
}

export function createEmptyLineItem(groupId: string = genId()): OrderLineItem {
  return {
    id: genId(),
    groupId,
    product: null,
    productLoading: false,
    selectedColorId: null,
    selectedSku: null,
    skuAutoSelected: false,
    saleForm: SALE_FORM_FINISHED,
    // 帘体默认「布帘」（issue #4521）：不带纱帘的普通窗帘 = 绝大多数场景
    curtainBody: CURTAIN_BODY_CLOTH,
    quantity: 1,
    unitPrice: 0,
    // 整卷售卖（issue #5846）：缺省 = **未填**（`null`，不是 0）——
    // 「0 卷」（全散剪）是一个要人**显式**录的结论，不能拿默认值冒充
    rollCount: null,
    rollLengthM: null,
    width: null,
    height: null,
    processingItems: [],
    selectedProcessing: {},
    // 默认档（issue #4420/#4493/#4521）：加工类型「定高买宽」/ 款式「单色」/ 是否对花「否」
    // —— 都是**商家看得见的真值**。
    // ⚠️ #4874：**褶距已整体移除**（连常量一起）；**用料公式 / 档位**的缺省不写在这里
    // （它们是**读面取值** —— 公式取算料配置 `default_formula`、档位取 `tiers` 的键，
    //   由页面侧 `derivedCraftSpec` 解析 ⇒ 这里不持有第二份真值）。
    // ⚠️ #4566：`craft` / `isShaped` **不在**这里 —— 它们由**加工项**派生
    // （工艺 = 勾选的工艺项的 `craftHint`；定型 = 「定型」加工项的勾选态），前端不补默认。
    // 打开方式缺省 = **双开**（2026-09-29 用户裁定：「打开方式默认改成双开，不要自动推算」）——
    // 旧的「按窗宽启发式自动写开数」已随 `deriveOpenCount` 删除。
    craft: { ...createDefaultCraftSpec(), openCount: DEFAULT_OPEN_COUNT },
    edgeMeters: null,
    edgeUnitPrice: null,
    processingFeeOverride: null,
    openCountTouched: false,
    shapedItemTouched: false,
    craftItemTouched: false,
    // issue #5202：默认档**不是**商家的选择（`cuttingModeTouched=false` ⇒ 加工类型按服务端推导/规则）
    cuttingModeTouched: false,
    metersSource: METERS_SOURCE_FORMULA,
    calc: null,
    calcError: null,
  }
}

/**
 * 「新增部位」已**整体移除**（issue #4521，用户 2026-09-19 裁定「移除部位功能，其实完全不需要」）。
 *
 * 为什么移除：用户口径是「**尺寸数量 / 工艺规格 / 加工项 / 特殊选项都跟着商品基础属性走**，
 * 部位只决定商品实际用料米数」—— 既然只有一个可变的「用料米数」，就没有第二个部位行可加：
 * 一个商品组 = 一套帘，需要纱帘时由**帘体**（`curtainBody`）表达，而不是再加一行。
 * 落库仍可能是**两条**明细行（主布行 + 纱帘行），但那由帘体派生，不需要商家手工加行。
 */

/**
 * ~~纱帘**明细行**是否成立~~ —— **整族已删除**（issue #4874，用户 2026-09-21：
 * 「订单需要**移除布帘+纱帘的选项**」）：`sheerUnitPriceOf` / `sheerMetersOf` /
 * 第二条纱帘明细行 / 费用明细「纱帘」行 / 提交校验里的纱帘单价必填**全部退场**
 * （`布帘+纱帘` 档已从 `CURTAIN_BODY_OPTIONS` 移除 ⇒ 这些函数不再有调用点）。
 *
 * 需要「布 + 纱」时：一个商品组勾**帘体 = 布帘**、另一个商品组勾**帘体 = 纱帘**
 * —— 后者那一行**本身就是**纱帘（`curtainType=纱帘`，按该行 `unitPrice` 计价），
 * 部位语义（`CURTAIN_TYPE_SHEER`）一字未动。
 */

/**
 * 算料试算的入参（**唯一装配点**）：部位在行上是从帘体派生的 ⇒ 在这里派生一次，两处调用共用。
 * ⚠️ **2026-09-21 用户裁定（口径反转）**：纱帘与布帘**用料算法完全一致** ⇒ 部位**不再**决定
 * 「算不算料」（原 #4521 的纱帘 fail-closed 已删）；这里仍带 `curtainType` 是因为它要自描述
 * **部位**（工序路线的索引键），与用料算法无关。
 *
 * ⚠️ #4566：`craft` 传**派生后**的规格（`craftFromItems` / `isShapedFromItems`）——
 * `craftCalcParamsOf` 读的是 `line.craft.craft`，若这里传原始值，试算会按「未指定工艺」
 * 或旧默认工艺算 ⇒ **页面显示 ≠ 落库**（工艺 → 公式/悬挂方式的分支取错）。
 *
 * ⚠️ #4874：**用料公式 / 档位**同样从派生规格带出（`formula` / `craftTier`）——
 * 公式进 `formula`、档位进 `craft_tier`，并且档位**同源落库**（`processingInfo.craftTier`）。
 */
export function calcInputOf(line: OrderLineItem, calcConfig: CraftCalcConfig | null) {
  const craft = derivedCraftSpec(line, calcConfig)
  return {
    width: line.width,
    height: line.height,
    craft,
    curtainType: curtainTypeOfBody(line.curtainBody),
    formula: craft.formula,
    craftTier: craft.craftTier,
    // **门幅**（issue #5202 · 根因 1）：该行所选 SKU 的门幅 —— 唯一解析点仍是
    // `parseDoorWidth`（#4877：没有缺省门幅，解析不到 ⇒ 不发该键、不猜）。
    fabricWidth: parseDoorWidth(line.selectedSku?.doorWidth),
    // **加工类型**：**只带商家显式选过的**（契约 #5200 §四 R7 的「人工覆盖」）。
    // ⚠️ 判「显式」看**留痕位**（`cuttingModeTouched`）—— `createDefaultCraftSpec()` 也写
    // `craft.cuttingMode = 定高买宽`，按「有值」判断 ⇒ 默认档被当成人工覆盖（`auto=false`）⇒
    // 推导从第一笔单起就恒不生效（静默失效）。传 `cuttingModeOf(line)` 同理更糟。
    cuttingModeOverride: line.cuttingModeTouched ? line.craft.cuttingMode : undefined,
    // 人工加（裁定 4）：拼次 / 接高 / 接宽 —— 越界值由 `craftCalcParamsOf` 拒发（fail-closed）
    planOverrides: line.planOverrides ?? null,
  }
}

/**
 * 配布边行是否成立（§4.8）：款式 = 拼色 **且** 商家填了配布边单价。
 *
 * 为什么不给单价兜底默认值：后端 `OrderCreateRequest.OrderItemRequest.unitPrice` 带
 * `@Positive`（单价必须 > 0），而配布边的用料加价口径**待客户裁定**（issue #4341 第 4 项）
 * ⇒ 凭空给一个价就是**静默改钱**。宁可少一行，也不编价。
 */
export function edgeUnitPriceOf(line: OrderLineItem): number | null {
  if (line.craft.style !== STYLE_MIXED) return null
  return line.edgeUnitPrice != null && line.edgeUnitPrice > 0 ? line.edgeUnitPrice : null
}

/** 配布边米数（§4.8 已裁定口径）：默认 = 主布米数（= 该行数量），可编辑 */
export function edgeMetersOf(line: OrderLineItem): number {
  return line.edgeMeters ?? (Number(line.quantity) || 0)
}
