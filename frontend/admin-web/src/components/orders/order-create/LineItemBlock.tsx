/**
 * 下单页的**部位行**（工艺规格 + 算料读数 + 加工项 + 加工费）—— issue #8725 第一档切片产物。
 *
 * 单一职责：把一行帘子的**全部录入面与推导读数**渲染出来并把改动交回页面
 * （`onChangeXxx` 回调）；**不持有账单状态、不自己发请求**（试算/取价一律由页面发起后经 props 传入）。
 *
 * ⚠️ 与本文件同名的 `LineItemBlockProps` 就是它的对外契约 —— 切片**没有**放宽或收窄任何一个 prop。
 */
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Check, Pencil, X } from 'lucide-react'
import { RECOGNIZE_SOURCE_TAG } from '@/lib/image-recognize'
import { type FeePreviewRow } from '@/lib/api'
import { cn } from '@/lib/utils'
import { NumberInput } from '@/components/ui'
import OrderCraftFields from '@/components/orders/OrderCraftFields'
import OrderExtraOptions from '@/components/orders/OrderExtraOptions'
import InstallRoomChips from '@/components/orders/InstallRoomChips'
import { INSTALL_ROOM_MAX_LENGTH } from '@/lib/install-info'
import {
  JOIN_GAP_MAX_METERS,
  METERS_SOURCE_MANUAL as LINE_METERS_SOURCE_MANUAL,
  craftCalcParamsOf,
  craftCalcSignature,
  craftPlanCandidateLabel,
  craftPlanHasSplice,
  craftPlanItemSourcesOf,
  craftPlanReasonText,
  craftPlanSpliceText,
  derivedJoinHeightOptionOf,
  derivedSpecialOptionsOf,
  derivedSpliceOptionOf,
  effectiveCraftCalcFormula,
  effectiveSpecialOptionsOf,
  isAutoCalcUnavailable,
} from '@/lib/craft-calc-request'
import { metersFormulaLegend } from '@/lib/meters-formula-legend'
import { craftPlanConclusionOf } from '@/lib/craft-plan-conclusion'
import { STYLE_MIXED, curtainTypeOfBody, type CraftSpecInput } from '@/lib/order-craft-fields'
import { craftSpecRows } from '@/lib/craft-display'
import { AUTO_FEATURE_NAMES, CUTTING_MODE_FIXED_HEIGHT, CUTTING_MODE_FIXED_WIDTH, parseDoorWidth } from '@/lib/craft-auto-features'
import { type CraftCalcConfig, type ProcessingItem } from '@/types'
import { SALE_FORM_FABRIC, type AutoFeatureDecision, type OrderLineItem } from '@/lib/order-create/types'
import {
  CRAFT_PLAN_ITEM_TESTIDS,
  CRAFT_PLAN_MANUAL_SOURCE_BY_LABEL,
  FEE_SOURCE_LABELS,
  OPEN_COUNT_LABEL,
  PRICING_ENTRY,
  SPLICE_OVERRIDE_OPTIONS,
  UNPRICED_NO_COMPOSITION,
  formatAmount,
} from '@/lib/order-create/display'
import {
  SHOW_MANUAL_OVERRIDES,
  autoFeatureNoticesOf,
  autoFeatureRowsOf,
  calcInputOf,
  craftFromItems,
  cuttingModeOf,
  derivedCraftSpec,
  derivedOptionInputOf,
  handPickableProcessingItems,
  nonNegativeOrNull,
  processingDetailsOf,
  recommendedItemNamesOf,
} from '@/lib/order-create/calc'
import { WizardStep } from '@/components/orders/order-create/WizardStep'
import { Label } from '@/components/orders/order-create/primitives'

// ====== 行项卡片 ======
export interface LineItemBlockProps {
  line: OrderLineItem
  errors: Record<string, string>
  /** **「哪儿缺了」的定向信号**（issue #5840）：见 {@link ProductGroupBlockProps.errorFocus} */
  errorFocus: { key: string; tick: number }
  processingLoading: boolean
  onChangeQty: (q: number) => void
  /** 「恢复按公式计算」（issue #4434）：切回算料预填（手改后不会被静默改回，只能显式恢复） */
  onRestoreFormula: () => void
  onChangePrice: (p: number) => void
  onToggleProcessing: (pi: ProcessingItem, selected: boolean) => void
  onChangeCraft: (patch: Partial<CraftSpecInput>) => void
  /**
   * 自动识别特征的**裁决**（issue #4657）—— `reject` 不采纳 · `add` 强制加 · `adopt` 恢复系统推算。
   * 生效值 = `推算 ∪ 强制加 − 不采纳` ⇒ 唯一喂给加工费组合键（绝不允许两个来源各说各话）。
   */
  onAutoFeatureDecision: (name: string, decision: AutoFeatureDecision) => void
  onEdgeMetersChange: (meters: number | null) => void
  onEdgeUnitPriceChange: (price: number | null) => void
  /**
   * 该行的**加工费取价行**（issue #4874）：`feePreview.items[i]`（服务端组合取价结果）。
   * `null` = 该行还没取价（无商品 / 未就绪）⇒ 「加工费组合」明细块不渲染。
   */
  feeRow: FeePreviewRow | null
  /** 租户算料配置（issue #4874）：公式缺省 + 档位 chips 的值域与文案都取自它 */
  calcConfig: CraftCalcConfig | null
  /**
   * **人工加 / 改推导项**（issue #5202 · 裁定 4/6）：拼次 / 接高 / 接宽 ——
   * `null` / `undefined` = 清掉该项（回到由推导决定）。
   */
  onChangePlanOverrides: (patch: {
    spliceTimes?: number | null
    joinHeightM?: number | null
    joinWidthM?: number | null
  }) => void
  /**
   * 「推导出的特殊选项」的**裁决**（issue #5211：拼N次 / 接高）—— `reject` 不采纳（该项不进
   * `specialOptions`）· `adopt` 恢复推导。与自动识别特征的 `onAutoFeatureDecision`（#4657）同族。
   */
  onDerivedOptionDecision: (name: string, decision: 'adopt' | 'reject') => void
  /** 「改单价」（元/米，issue #4874）：`null` = 清空（回到未改过） */
  onProcessingFeeOverrideChange: (price: number | null) => void
  /**
   * **推荐组合的裁决**（2026-09-28）：`adopt` 采纳（把推荐项勾上）· `reject` 全不采纳（取消）。
   *
   * ⚠️ 必须是**一次整份写**的回调：逐项调 `onToggleProcessing` 会各写一次全量
   * `selectedProcessing` ⇒ 后一次覆盖前一次，只剩最后一项生效。
   */
  onRecommendedDecision: (decision: 'adopt' | 'reject') => void
  /**
   * **部位备注**（issue #5685）：行级自由文本 —— 上游原样存进行状态，落库由
   * `buildLineProcessingInfo` 单点完成（**不在回调里拼 payload**）。
   */
  onChangeRemark: (remark: string) => void
  /**
   * **安装位置**（issue #7856）：行级自由文本 —— 与 {@link LineItemBlockProps.onChangeRemark}
   * 同一范式：只存进行状态，落库由 `buildLineProcessingInfo` 单点完成（缺值不落键）。
   */
  onChangeInstallRoom: (room: string) => void
  /** **门幅 / 规格**节点（2026-09-30 第四批）：与用料米数 / 单价同一行（组级算、行内渲染） */
  specPicker?: React.ReactNode
  /** 门幅的**来源说明 + 推导细节**（同上）：整行平铺在规格行下方 */
  specExtras?: React.ReactNode
}

/** 部位备注的输入上限（issue #5685）—— 服务端不截断 ⇒ 由录入控件 `maxLength` 挡住 */
export const REMARK_MAX_LENGTH = 200

export function LineItemBlock({
  line,
  errors,
  errorFocus,
  processingLoading,
  onChangeQty,
  onRestoreFormula,
  onChangePrice,
  onToggleProcessing,
  onChangeCraft,
  onAutoFeatureDecision,
  onEdgeMetersChange,
  onEdgeUnitPriceChange,
  feeRow,
  calcConfig,
  onChangePlanOverrides,
  onDerivedOptionDecision,
  onProcessingFeeOverrideChange,
  onRecommendedDecision,
  onChangeRemark,
  onChangeInstallRoom,
  specPicker,
  specExtras,
}: LineItemBlockProps) {
  /**
   * 当前展开的**向导步骤**（issue #4511 手风琴）：1 用料与规格 / 2 加工项（2026-09-29 两步化
   * —— 原「③ 其他」已并入 ② 的第二块「特殊选项」，见 `OrderExtraOptions` 的渲染点）。
   */
  const [openStep, setOpenStep] = useState(1)
  /**
   * 本行的**错误计数**（issue #5840）—— 挂在①步骤标题的 `badges` 上 ⇒ **该步收起时也看得见**
   * 「这儿缺 N 项」。行级报错当前全部住在①（商品 / 颜色 / 规格 / 宽高 / 数量 / 单价 / 自动识别）。
   */
  const lineErrorCount = Object.keys(errors).filter((k) => k.startsWith(`line_${line.id}_`)).length
  /**
   * 提交失败 / 点了汇总里某一条 ⇒ **①自动展开**（issue #5840）。
   * 手风琴一次只开一步：若商家正开在②，①里的报错原本是看不见的。
   * ⚠️ 依赖 `tick`（不是 key）：同一处连按两次也要重新展开。
   */
  useEffect(() => {
    if (errorFocus.tick === 0 || lineErrorCount === 0) return
    setOpenStep(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [errorFocus.tick])
  // ⚠️ 2026-09-29（用户裁定「移除这种设计，当前编辑态就是允许用户直接更改的」）：
  // 「用料米数 / 单价」的**只读展示 + 点「改」**编辑态**已整体删除** —— 两个框常态就是可编辑输入框
  // （`metersEditOpen` / `priceEditOpen` 连同两个按钮一起退场）。
  /** **系统推荐组合**在本行的实例（目录里没有该项 ⇒ 不出现，如老租户未重建目录；布料组 ⇒ 空） */
  const recommendedItems = line.processingItems.filter((pi) =>
    recommendedItemNamesOf(line).includes(pi.name)
  )
  /**
   * 加工项**一级分类导航 + 关键字搜索**（issue #4576）—— 纯**展示态**。
   *
   * ⚠️ 与勾选态（`line.selectedProcessing`）**严格分离**：过滤只影响**渲染**，
   * 被过滤掉但仍勾选的项**照样**计入已选摘要与提交 payload（`processingDetailsOf` 只读勾选态）。
   * 这里**没有**第二份勾选状态，也**没有**第二套落库路径。
   */
  const [activeCategoryId, setActiveCategoryId] = useState('')
  const [processingQuery, setProcessingQuery] = useState('')
  /**
   * 「加工费组合」块的**改价编辑态**（issue #7658，用户 2026-10-24「样式改成工艺项 · 计件单价的样式」）：
   * 读态只显示「价 + ✏️」，点铅笔才出输入框，✓ 保存 / ✕ 取消。草稿只活在本地 ⇒ 录入过程中
   * **不发预览**（与「工序库 / 工艺项」改计件单价同一交互：改完点保存才生效）。
   */
  const [feeEditing, setFeeEditing] = useState(false)
  const [feeDraft, setFeeDraft] = useState<number | null>(null)
  const stepProps = (n: number) => ({
    open: openStep === n,
    onToggle: () => setOpenStep(openStep === n ? 0 : n),
  })
  const selectedProcessingCount = Object.values(line.selectedProcessing).filter(
    (c) => c.selected
  ).length
  /**
   * 勾选的加工项**名字**（按目录顺序）—— 2026-09-30 第五批：摘要里**逐项列出来**。
   *
   * 用户原话：「这里勾选上的和显示的不一致」—— 改前摘要只写「已选 2 项 · 工艺：韩褶」，
   * 而实际勾上的是「定型 + 韩褶」两项 ⇒ 商家对不上号（只能回头把这一步展开数一遍）。
   * ⚠️ 名字**只**从目录取（`line.processingItems`）：目录里已找不到的勾选 id 没有可读名
   * ⇒ 那种情况下回落旧的「工艺：X」形态（**不编名字**）。
   */
  const selectedProcessingNames = line.processingItems
    .filter((pi) => line.selectedProcessing[pi.id]?.selected)
    .map((pi) => pi.name)
  /**
   * **系统识别**（issue #4658 放置 + #4657 可采纳/不采纳）—— 只读 + 可裁决，**不计入**
   * `selectedProcessingCount`（不是手选项）。
   *
   * - `autoFeatureRows` = 展示行（含被**不采纳**的 —— 留痕要看得见）；
   * - `autoFeatures` = **生效值** = `推算 ∪ 强制加 − 不采纳`（与 `processingDetailsOf` 同一份）；
   * - `addableAutoFeatures` = 系统**没推**也没强制加的特征 ⇒ 提供「强制加」入口
   *   （门幅数据缺失导致漏判时，商家要能补）。
   */
  const autoFeatureRows = autoFeatureRowsOf(line)
  const autoFeatures = autoFeatureRows.filter((row) => !row.rejected)
  const addableAutoFeatures = AUTO_FEATURE_NAMES.filter(
    (name) => !autoFeatureRows.some((row) => row.name === name)
  )
  /** 系统识别**提示**：加工类型与几何**矛盾** ⇒ 系统实际会按哪种算（服务端产出） */
  /**
   * 系统识别**提示**：加工类型与几何**矛盾** ⇒ 系统实际会按哪种算（服务端产出）。
   *
   * 🔴 **2026-09-22 改判（issue #5130）**：提示条目只剩 `cutting-mode-conflict` 一条 ——
   * `missing-door-width`（「未维护门幅 ⇒ 超高/超宽都判不了」）与 `missing-fullness`
   * （「缺褶倍 ⇒ 未判超宽」）两条随判据替换（净窗宽/净窗高 vs **企业阈值参数**）**退役**
   * （旧文案在新判据下成了**假话**）。⇒ issue #4899 加的「未选规格时摘掉 `missing-door-width`」
   * 这条 `filter` 也随之删除（它的前提 = 该条目存在）。
   */
  const autoFeatureNotices = autoFeatureNoticesOf(line)
  /**
   * 门幅（issue #4877）：**已无缺省门幅** —— 解析不到 ⇒ `null` ⇒ 界面显式说「无法判定」。
   * 旧行为「按默认 2.8 米推算」= 本单要替换掉的错误做法（真单实测：门幅 2.8/3.2 之差会让
   * 同一张单得出「需接高」与「单幅可做」两种相反结论）。
   */
  const selectedDoorWidth = parseDoorWidth(line.selectedSku?.doorWidth)
  /**
   * 「**SKU 未维护门幅**」——必须**先有一个选中的 SKU**（issue #4899）：
   * 否则「还没选规格」会被显示成「门幅未维护」（误导：不是没维护，是根本还没选）。
   */
  const doorWidthMissing = line.selectedSku !== null && selectedDoorWidth === null
  /**
   * **门幅规则**（issue #4877）：候选 = 本行该颜色的 SKU 门幅；解 = 可行集取最小门幅 /
   * 定宽买高取分幅最少。所选门幅**不可行** ⇒ `infeasible`（需接高，强告警）；
   * **非最优** ⇒ `suboptimal`（提示可换最省门幅 —— 只提示，**不改客服的选择**）。
   */
  /**
   * **门幅规则**（issue #5043 包 2b，**服务端**）：规则解 + 四态裁决都由 `doorWidthPlanApi` 给 ——
   * 前端 `@/lib/door-width-plan` 已退场（它与引擎 `resolve_fabric_plan` 不是同一条规则）。
   * 还没到 / 判不了 ⇒ `undecidable` + `unknown`（**不提示最优** —— 没有可比对象）。
   */
  const doorWidthChoice = {
    plan: {
      state: (line.doorWidthPlan?.state ?? 'undecidable') as
        | 'single_panel'
        | 'needs_splice'
        | 'undecidable',
      // 规则还没到 ⇒ 按**输入完整性**给原因（这**不是**口径判断，只是「连问都问不了」）：
      // 宽高没填齐 ⇒ `missing-size`；该颜色没有可用门幅 ⇒ `no-door-width`。
      code: line.doorWidthPlan
        ? line.doorWidthPlan.code
        : !Number.isFinite(Number(line.width)) ||
            Number(line.width) <= 0 ||
            !Number.isFinite(Number(line.height)) ||
            Number(line.height) <= 0
          ? 'missing-size'
          : 'no-door-width',
    },
    verdict: line.doorWidthPlan?.verdict ?? 'unknown',
    suggestion: line.doorWidthPlan?.suggestion ?? null,
  }
  /**
   * 手选加工项（issue #4566）—— 滤掉**自动推导特征**（超高/超宽/倒幅）。
   * 它们在目录里**必须存在**（商家配「加工费组合」要能选到），但**不得**出现在手选控件里
   * （判据 8：自动识别特征出现手选项 ⇒ 红）。单一真值 = `AUTO_FEATURE_NAMES`。
   */
  const handPickableItems = handPickableProcessingItems(line.processingItems)

  /**
   * 加工项按**一级分类**分组（issue #4576）—— 主轴 = 分类导航（用户口径：
   * 「加工项**有一级分类**，可以**先选一级分类再选具体加工项**，同时也加**关键字快速搜索**」）。
   *
   * 分类取目录响应**已有**的 `categoryId` / `categoryName`（`processing_categories`）。
   * 边界：目录没配分类 / 只有一类 ⇒ **退回全部平铺**（不渲染选择器、不报错）；
   * 缺分类的项归入「未分类」组，与有分类的项混排时照常可选。
   */
  const processingCategoryGroups: Array<{
    id: string
    name: string
    items: ProcessingItem[]
  }> = []
  for (const pi of handPickableItems) {
    const id = pi.categoryId ? String(pi.categoryId) : ''
    let group = processingCategoryGroups.find((g) => g.id === id)
    if (!group) {
      group = { id, name: pi.categoryName || '未分类', items: [] }
      processingCategoryGroups.push(group)
    }
    group.items.push(pi)
  }
  /** 分类只有 1 个 ⇒ 不渲染选择器（一个 tab 是噪音），直接显示该类下的项 */
  const hasProcessingCategoryNav = processingCategoryGroups.length > 1
  /** 选中的分类已不在目录里（换商品 / 目录变化）⇒ 落回第一类（不报错） */
  const activeCategory =
    processingCategoryGroups.find((g) => g.id === activeCategoryId) ?? processingCategoryGroups[0]
  const trimmedQuery = processingQuery.trim().toLowerCase()
  const searchingProcessing = trimmedQuery.length > 0
  /**
   * 可见加工项：搜索**跨分类**命中（命中即跨分类展示，并在结果里标出所属分类）；
   * 未搜索 ⇒ 只显示**当前选中分类**的项（无分类导航时即全部平铺）。
   */
  const visibleProcessingItems = searchingProcessing
    ? handPickableItems.filter((pi) => pi.name.toLowerCase().includes(trimmedQuery))
    : activeCategory?.items ?? []
  const categoryNameOf = (pi: ProcessingItem) =>
    pi.categoryName || processingCategoryGroups.find((g) => g.items.includes(pi))?.name || ''
  /** 该行**工艺**（#4566 派生值）—— ③ 已选摘要与 ② 工艺规格摘要**共用**同一个取值点 */
  const lineCraft = craftFromItems(line)
  /**
   * **用料公式的参数说明**（2026-09-29 用户裁定）—— 只解释公式串里的数是**哪个参数**、
   * 要改去哪改；数值全部取自同一次算料响应 / 算料配置（见 lib 头注释：**不解析公式串**、
   * 取不到就整条不出现）。
   */
  const metersLegend = metersFormulaLegend({
    formula: effectiveCraftCalcFormula(
      { formula: line.craft.formula, craft: lineCraft },
      calcConfig
    ),
    width: line.width,
    openCount: line.craft.openCount,
    pleatCount: line.calc?.pleat_count ?? null,
    perFold: line.calc?.per_fold ?? null,
    fullness: line.calc?.fullness ?? null,
    config: calcConfig,
  })

  /** 布料组整组无加工（issue #4493）⇒ 自动识别块也不渲染 */
  const isFabricLine = line.saleForm === SALE_FORM_FABRIC

  // ===== 推导方案（issue #5202；契约 #5200 §四）=====
  /**
   * **推导方案**：加工类型 / 分幅 / 拼次 / 接高 / 接宽 / 用料 —— 全部由服务端给，页面**只读展示**
   * （前端不实现第二份推导：候选枚举、选优、0.1 米上限都在算料引擎）。
   * ⚠️ `plan` **不含工艺**（工艺没有几何依据，见 `lib/craft-calc-request.ts::DEFAULT_CRAFT_NAME`）。
   */
  const plan = line.calc?.plan ?? null
  /** 算料回来了但响应里**没有** `plan` ⇒ 后端未接线（显式降级，不崩、不猜） */
  const planUnavailable = line.calc !== null && plan === null
  /**
   * 「推导出的特殊选项」（拼N次 / 接高；issue #5211）的**单点取值** —— 面板显示与落库
   * `specialOptions` 用**同一对函数**（`derivedSpecialOptionsOf` / `effectiveSpecialOptionsOf`）：
   * `derivedOptions` = 系统推导出的项；`effectiveOptions` = 实际生效的（= 落库值）。
   *
   * ⚠️ 面板那一行必须读 `effectiveOptions`（**不是** `plan.splice_option`）—— 读 plan 就会在
   * 「人工加 / 不采纳 / 手工勾过」三种情形下与订单内容不一致（#5211 要收口的正是这个）。
   * ⚠️ **②特殊选项那一排 chips 的勾选态也读它**（issue #7849；用户逐字「推导出拼一次，但是在特殊选项
   * 中没有选中」）—— 选择器读人工勾选态 = 同屏两个真值：面板说「已并入特殊选项」，选择器却显示没选。
   */
  const derivedOptions = derivedSpecialOptionsOf(derivedOptionInputOf(line))
  const effectiveOptions = effectiveSpecialOptionsOf(derivedOptionInputOf(line))
  /**
   * **②特殊选项的勾选动作**（issue #7849）—— 勾选态 = **生效集**（所见 = 所提交），
   * 落到**两份既有状态**上（不新增状态、不改推导 / 落库链路）：
   * - 勾上一个还没生效的项 ⇒ 记**人工勾选**（`craft.specialOptions`，人工优先）；
   * - 取消一个人工项 ⇒ 从 `craft.specialOptions` 移除；
   * - 取消一个**推导**项 ⇒ 记**不采纳**（`rejectedDerivedOptions`）—— 只删人工项没用：
   *   推导下一帧就会把它加回生效集，变成「点不掉的选中」；
   * - 勾回一个被不采纳的推导项 ⇒ **采纳**（同一位取反）。
   * ⚠️ 推导项**不写**进人工勾选态：写进去 `derivedOptionState` 会把它读成「你手工勾过 ⇒ 人工优先」。
   */
  const onChangeSpecialOptions = (next: string[]) => {
    const manual = line.craft.specialOptions ?? []
    const added = next.filter((name) => !effectiveOptions.includes(name))
    const removed = effectiveOptions.filter((name) => !next.includes(name))
    onChangeCraft({
      specialOptions: [
        ...manual.filter((name) => !removed.includes(name)),
        ...added.filter((name) => !derivedOptions.includes(name)),
      ],
    })
    for (const name of derivedOptions) {
      if (added.includes(name)) onDerivedOptionDecision(name, 'adopt')
      else if (removed.includes(name)) onDerivedOptionDecision(name, 'reject')
    }
  }
  /**
   * **引擎拒绝了本行本次算料**（issue #5287 ②/③/④）—— `line.calcError` 就是引擎/后端给的那**一条**
   * 错误原文（成功 ⇒ `null`；被拒 ⇒ 非空）。⚠️ 「某一项到底生没生效」**只许**读它：
   * 前端**不得**自写一份「拼次是否合法 / 加工类型配不配」的判断（那是第二份引擎判定 —— 判据 4）。
   */
  const engineRejected = line.calcError !== null
  /** 一个推导项在本行的**状态**（面板与落库共用同一判定 ⇒ 不可能各说各话） */
  const derivedOptionState = (
    name: string
  ): 'manual' | 'merged' | 'rejected' | 'engine-rejected' => {
    const state =
      (line.craft.specialOptions ?? []).includes(name)
        ? 'manual' // 商家在②特殊选项里手工勾过 ⇒ 人工优先
        : effectiveOptions.includes(name)
          ? 'merged'
          : 'rejected'
    // 引擎拒绝了本次算料 ⇒ **「已并入」不成立**（并进去也插不了工序、计不了件）——
    // 与错误态**同源**（同一份 `line.calcError`），不是前端自己判出来的「拼次不合法」（判据 3/4）。
    return state === 'merged' && engineRejected ? 'engine-rejected' : state
  }
  /**
   * **项级来源**（issue #5287 ①b · 用户裁定**甲**）—— 加工类型 / 拼次 / 接高 / 接宽**各带自己的来源**。
   * 判据与**请求面同源**（键有没有真发给引擎，见 `lib/craft-calc-request.ts::craftPlanItemSourcesOf`）；
   * 块级 `craft-plan-source` 退为**汇总**，不承担项级归属。
   */
  const planSources = craftPlanItemSourcesOf(craftCalcParamsOf(calcInputOf(line, calcConfig)))
  /** 面板「拼接」那一行显示的拼次名（生效值；没有 ⇒ 回落 `craftPlanSpliceText` 的不拼接 / N≥4 文案） */
  const spliceOption = derivedSpliceOptionOf({
    plan,
    spliceTimesOverride: line.planOverrides?.spliceTimes,
  })
  /** 接高（issue #5211；接宽不在本单，见 #5214） */
  const joinHeightOption = derivedJoinHeightOptionOf({
    plan,
    joinHeightOverride: line.planOverrides?.joinHeightM,
  })
  const canRejectJoinHeight = joinHeightOption !== null && derivedOptionState(joinHeightOption) === 'merged'
  const canRejectSplice = spliceOption !== null && derivedOptionState(spliceOption) === 'merged'
  /**
   * **用料方案的结论表达**（2026-09-29 用户第二次裁定）—— 只做措辞：数全部取自引擎推导方案
   * （`plan`），拼接那一档复用既有 `craftPlanSpliceText`（同一档不许两份文案）。
   * ⚠️ 拼接取**生效值**（人工加优先，同旧形态）：`spliceOption` 已经把 `planOverrides` 算进去。
   * ⚠️ 位置**必须在 `planSources` / `spliceOption` 之后**（它们都是 `const`，提前引用会 TDZ 崩渲染）。
   */
  const craftPlanConclusion = craftPlanConclusionOf({
    panels: plan?.panels ?? null,
    spliceTimes: line.planOverrides?.spliceTimes ?? plan?.splice_times ?? null,
    spliceText: spliceOption ?? (plan ? craftPlanSpliceText(plan) : null),
    joinHeightM: plan?.join_height_m ?? null,
    joinWidthM: plan?.join_width_m ?? null,
    doorWidth: plan?.door_width ?? null,
    craft: lineCraft ?? null,
    craftIsDefault: !lineCraft,
  })
  /**
   * 逐项明细 + **项级「人工」标注**（issue #5287 ①b 的甲口径，2026-09-29 第二次裁定收窄）：
   * 「系统推导」是常态 ⇒ **不再逐项写**（用户实测读着吵）；**人工改过的那一项**必须还看得见
   * （否则「谁定的」这条信息就没了 —— 判据要的是可归属，不是常显）。
   */
  const craftPlanItems = craftPlanConclusion.items.map((item) => {
    const key = CRAFT_PLAN_MANUAL_SOURCE_BY_LABEL[item.label]
    return key && planSources[key] === 'manual'
      ? { ...item, value: `${item.value}（人工）` }
      : item
  })
  /**
   * 「改」入口的展开态（issue #5202）：`null` = **跟随默认** —— 推导没就绪（`plan === null`）时
   * **默认展开**（人工兜底是唯一出路，收起会让商家无从下手），推导就绪后默认收起（三项输入收敛）。
   * 商家点过之后就按他点的来（不再被推导到达 / 消失牵动）。
   */
  const [craftEditTouched, setCraftEditTouched] = useState<boolean | null>(null)
  const craftEditOpen = craftEditTouched ?? plan === null
  /**
   * **该行生效的工艺规格**（页面侧唯一派生点的一次求值）——展开态控件 / 试算 / 落库 / 收起态读数
   * 全都读它这一份（不要各自调一次 `derivedCraftSpec`）。
   */
  const craftSpec = derivedCraftSpec(line, calcConfig)
  /**
   * **收起态摆出来的「当前工艺参数」读数**（issue #6399，2026-10-06 用户逐字「订单详情中，
   * 这里折叠的部分得把折叠的内容展示出来，不然用户不知道选择了什么，而且得**高亮展示**」）。
   *
   * 为什么需要它：改前收起态只有一句**静态**按钮文案，加工类型 / 打开方式 / 款式 / 用料公式的
   * **当前值**全在被折叠的 `OrderCraftFields` 里（收起时那棵子树根本不渲染）⇒ 商家要核对
   * 「系统现在按哪种在算」只能点开一次。
   *
   * 两张「唯一真值」都不新造：取值 = 上一个 `craftSpec`（唯一派生点）；标签与格式化 =
   * `craft-display.ts::craftSpecRows`（订单详情 / 加工单 / 任务卡 / C 端报价卡同源）。
   * ⚠️ **只取按钮自己承诺的那四项**：档位那行走的是 `craft-display` 的**兜底**文案（`标准工艺`），
   * 与展开态下拉里的**租户配置文案**（如 `标准档`）不是同一个字面量 ⇒ 同一屏摆两份 = 同一真值两种
   * 说法，故**刻意不收进来**（要看得展开，那里是权威那份）。
   */
  const craftPlanCurrentRows = craftSpecRows({
    cuttingMode: craftSpec.cuttingMode,
    openCount: craftSpec.openCount,
    style: craftSpec.style,
    formula: craftSpec.formula,
  })
  /**
   * **生效加工类型**（**单点**：`lib/craft-auto-features.ts::effectiveCuttingModeOf`）——
   * 人工加的入口按它分档（契约订正 v1.1 ③：接高只在「定高买宽」、接宽只在「倒幅」）。
   */
  const effectiveCuttingMode = cuttingModeOf(line)
  const canJoinHeight = effectiveCuttingMode === CUTTING_MODE_FIXED_HEIGHT
  const canJoinWidth = effectiveCuttingMode === CUTTING_MODE_FIXED_WIDTH
  /** 当前生效的那一档的人工缺口 + **就地报错**（超限 ⇒ 请求面拒发该键，且**不静默截断**） */
  const joinGapRaw = canJoinHeight
    ? line.planOverrides?.joinHeightM
    : canJoinWidth
      ? line.planOverrides?.joinWidthM
      : undefined
  const joinGapOverLimit =
    joinGapRaw !== undefined &&
    joinGapRaw !== null &&
    Number.isFinite(Number(joinGapRaw)) &&
    Number(joinGapRaw) > JOIN_GAP_MAX_METERS
  /**
   * **人工指定的米数没有跟随本次改动**（issue #5202 · 根因 2）—— 判据 = 手改那一刻的入参签名
   * 与**当前**签名不同。刻意做成**派生值**（不落状态）：落状态就要再维护一份同步逻辑，
   * 而「同步逻辑没跑到」正是单向棘轮的来源。
   */
  const metersStale =
    line.metersSource === LINE_METERS_SOURCE_MANUAL &&
    line.metersManualSignature !== undefined &&
    line.metersManualSignature !==
      craftCalcSignature(craftCalcParamsOf(calcInputOf(line, calcConfig)))

  /**
   * **告知句内的「推导值 / 差」**（issue #5281 · owner 2026-09-23 裁定口径 **A** / 判据 2′）——
   * 告知元素内必须**同时**含三个量：① 当前生效值（手填，见句首）② 系统的推导值 ③ 两者的差
   * （相等 ⇒ 显式写「相同」）；推导值未返回 ⇒ 显式写**不可比**，**不得静默缺项**。
   *
   * **真值源纪律**：推导值一律取 `plan.meters` —— 与面板 `craft-plan-meters`（`用料 {plan.meters} 米`）
   * **同源**，商家在告知里看到的数与他上方面板看到的是**同一个**。
   * ⛔ 不得改取 `line.calc.fabric_meters`：它是**算料结果**（数量预填用的那个），与面板展示的推导用料
   * **可以不是同一个数**（页面自己的 `craft-plan-meters-mismatch` 就是为这种不等而存在的）
   * ⇒ 拿它当推导值，差会与商家眼前的推导值打架（同一屏两个「系统说的数」）。
   *
   * **差的格式化**：`plan.meters - line.quantity` 直接相减会漏出 IEEE-754 长尾
   * （实测 `5.8 - 7.7 = -1.9000000000000004`）⇒ 一律按 **0.01 米**收口（`toFixed(2)`）后展示；
   * 取绝对值（商家要的是"差多少"，方向由句内那两个数本身可见）。收口后为 0 ⇒ 显式写「相同」——
   * **判定与展示用同一个数** ⇒ 不会出现「相同」与「差 0 米」互相矛盾的那种文案。
   */
  const metersCompareText = (() => {
    if (plan === null || !Number.isFinite(Number(plan.meters))) {
      return '本次未返回推导值，无法比较'
    }
    const delta = Number((Number(plan.meters) - Number(line.quantity)).toFixed(2))
    return delta === 0
      ? `系统推导用料 ${plan.meters} 米，与你手填的相同`
      : `系统推导用料 ${plan.meters} 米，差 ${Math.abs(delta)} 米`
  })()

  /**
   * **加工费取价明细**（issue #4874）—— 键名冻结于后端 `ProcessingFeeCalculator.detail`：
   * `composition`（归一化组合键）/ `items`（展示用加工项名，与「加工费组合」页同源）/
   * `unit_price` / `fee_source`（`matched` / `manual` / `unpriced`）。
   */
  const feeDetail = feeRow?.processingFeeDetail as
    | {
        fee_source?: unknown
        composition?: unknown
        items?: unknown
        unit_price?: unknown
        /** 被本单改价覆盖的那条组合价目价（issue #7642；只有「已配置组合 + 本单改价」才下发） */
        configured_unit_price?: unknown
      }
    | undefined
  /** 组合键（**空 = 缺选配信息**）——「改单价」入口的准入条件之一（没有 key 就没法同步） */
  const feeCompositionKey =
    typeof feeDetail?.composition === 'string' ? feeDetail.composition.trim() : ''
  const feeSource = typeof feeDetail?.fee_source === 'string' ? feeDetail.fee_source : ''
  const feeIsUnpriced = feeSource === 'unpriced'
  /** 组合名：`items.join(' + ')`（与「加工费组合」页逐字同源）；缺值按口径回落，不留空 */
  const feeItems = Array.isArray(feeDetail?.items)
    ? feeDetail.items.filter((v): v is string => typeof v === 'string' && v.trim() !== '')
    : []
  const feeCombinationLabel =
    feeItems.length > 0
      ? feeItems.join(' + ')
      : feeCompositionKey !== ''
        ? feeCompositionKey
        : // 未定价 **且**两边都空 = 缺选配信息（既有文案，一字不改）；已定价行缺 items 才是「—」
          feeIsUnpriced
          ? UNPRICED_NO_COMPOSITION
          : '—'
  const feeUnitPrice = Number(feeDetail?.unit_price)
  /**
   * **本单单价可改**（issue #7642）：组合键非空就够 —— 已配置的组合也允许改**本单**单价
   * （用户 2026-10-24「新增订单中的加工费组合需要允许修改」；旧口径「只给未定价行」= 配了价目之后
   * 某一单要按谈好的价收**没有任何入口**）。组合键为空（缺选配信息）⇒ 没有 key 可落地 ⇒ 不给入口。
   */
  const canOverrideFee = feeCompositionKey !== ''
  /**
   * 被本单改价**覆盖**的那条组合价目价（issue #7642）—— 只有「已配置的组合被本单改价」时服务端才下发
   * （`processingFeeDetail.configured_unit_price`）；`NaN` = 没有价目可覆盖（未配置行 / 没改价）。
   */
  const feeOverriddenConfiguredPrice = Number(feeDetail?.configured_unit_price)
  /**
   * **组合价目参考价**：改价前 = 命中价（`matched` 的 `unit_price`）；改价后 = 被覆盖的价目价
   * （服务端 `configured_unit_price`）。两个时刻都能回答「价目是多少」—— 否则商家改完价就再也看不到
   * 自己改的是哪一条价目，「价目不变」也就无从核对。
   */
  const feeReferencePrice =
    Number.isFinite(feeOverriddenConfiguredPrice) && feeOverriddenConfiguredPrice > 0
      ? feeOverriddenConfiguredPrice
      : feeSource === 'matched' && Number.isFinite(feeUnitPrice) && feeUnitPrice > 0
        ? feeUnitPrice
        : null
  /**
   * **读态显示的本单单价**（issue #7658）：已改价 ⇒ 商家填的价（**`0` 也显示 `¥0.00/米`**，不是「未定价」）；
   * 未改价 ⇒ 已配置组合的价（`matched` 的 `unit_price`）；两者都没有 ⇒ `null`（渲染「未定价」）。
   *
   * ⚠️ 与 {@link feeReferencePrice} 分工：那是**价目**参考价（改价后仍摆着，用于核对「价目不变」），
   * 这是**本单生效价** —— 同一屏两个数，语义不同，不互相顶替。
   */
  const feeReadPrice =
    line.processingFeeOverride != null && Number.isFinite(line.processingFeeOverride)
      ? line.processingFeeOverride
      : feeSource === 'matched' && Number.isFinite(feeUnitPrice)
        ? feeUnitPrice
        : null
  /**
   * 该行**有没有任何选配**（手选加工项 ∪ 自动识别特征）—— 没有 ⇒ 组合键必然为空，
   * 「加工费组合」块整块不渲染（无组合可展示、也无价可改），与「缺选配信息」是两回事。
   */
  const hasAnyProcessingSelection = processingDetailsOf(line).length > 0

  /**
   * ① 尺寸行旁的**就地徽标** —— 2026-09-28 随「净尺寸」一起搬到**组级**：
   * 单一实现 = 模块级 `sizeAutoBadgesOf(line)`（组级与行内共用，避免两份判定各说各话）。
   */

  const errQty = errors[`line_${line.id}_quantity`]
  const errPrice = errors[`line_${line.id}_unitPrice`]
  // ⚠️ 2026-09-28：`errWidth` / `errHeight` 的渲染点随「净尺寸」搬到了组级
  // （`ProductGroupBlock` 直接读同一个 `errors` 键）⇒ 这里不再取，避免留一份没人读的变量。

  /** 摘要（issue #4420）：一眼看懂「这是什么、多大、多少钱」—— 部位已移除（#4521）⇒ 取帘体 */
  const summarySpec = [
    line.curtainBody,
    // 工艺取**派生值**（#4566：来自加工项的 `craftHint`）—— 不读 `line.craft.craft`（那里已没有真值）
    lineCraft,
    line.craft.cuttingMode,
    line.craft.openCount ? OPEN_COUNT_LABEL[line.craft.openCount] : undefined,
    line.craft.style,
  ]
    .filter(Boolean)
    .join(' · ')
  const summarySize =
    line.width && line.height ? `${line.width} × ${line.height} m` : '未填宽高'

  /**
   * **「怎么推出来的」一整趴**（2026-09-30 第五批）—— 门幅来源与推导细节 / 用料公式与参数说明 /
   * 用料方案（结论 · 逐项 · 依据）三块，原样搬进 ① 标题右侧（`aside`），不再压在表单下方。
   * ⚠️ 只搬**读数**：裁决入口（接高 / 拼接的采纳 / 不采纳）在 系统识别 块里、**只此一处**。
   */
  const derivationAside = (
    /* **一整块推导细节**（🔴 2026-09-30 第六批；用户逐字「推导细节都收拢到一个折叠区域，打开后展示
       全部细节，直接用一行展示这块的标题+推导细节，默认折叠，通过文案提示用户可以打开」）——
       改前是 ① 门幅 / ② 用料公式 / ③ 用料方案 **三条各自折叠**；现在**只有这一块**是可折叠的，
       三块原样收进它里面（编号即标题），标题行 = 引导语，**不折叠套折叠**。 */
    <details data-testid="derivation-panel" className="w-full">
      <summary className="cursor-pointer text-[11px] text-neutral-400 hover:text-neutral-600">
        推导细节（默认收起，点标题展开）
      </summary>
      <div className="mt-1.5 space-y-1.5">
              {/* 门幅的**来源说明 + 推导细节**（`sku-choice-reason` / `door-width-details`）——
                  整行平铺在规格行下方：塞进第一格会把长句挤成三行、反而更高。 */}
              {specExtras}
              {/* **公式 + 参数说明（整行平铺）**（2026-09-29 第二次裁定）：原来挤在左列里 ⇒
                  右半边全空（用户原话「推导说明的右侧空白也能利用起来，把文案完全平铺开」）。
                  公式串仍是**后端产出、原样渲染**（前端不自拼）；参数说明给「哪个数是哪个参数」
                  + 「要改去哪改」，末段是**算料配置页的深链**（`CRAFT_CALC_ENTRY`）。 */}
              {line.metersSource !== LINE_METERS_SOURCE_MANUAL && line.calc?.formula_text && (
                /* 🔴 2026-09-30 第六批：同上 —— 这里退回「② 的标题行 + 内容」，折叠由整块那一个管。 */
                <div
                  data-testid="meters-formula-block"
                  className="rounded border border-neutral-200 bg-neutral-50/60 px-3 py-2"
                >
                  <p className="text-xs text-neutral-600">
                    <span className="font-medium">② 用料公式</span>
                  </p>
                  <p
                    data-testid="meters-formula-text"
                    className="mt-1 text-xs text-neutral-500 break-words"
                  >
                    {line.calc.formula_text}
                  </p>
                  {metersLegend && (
                    <>
                      <p
                        data-testid="meters-formula-legend"
                        className="mt-1 text-xs text-neutral-500"
                      >
                        参数说明：
                        {metersLegend.params.map((p) => `${p.value}=${p.name}`).join(' · ')}
                      </p>
                      <p
                        data-testid="meters-formula-legend-where"
                        className="mt-0.5 text-xs text-neutral-400"
                      >
                        {metersLegend.where.prefix}
                        <Link
                          href={metersLegend.where.linkHref}
                          data-testid="craft-calc-entry"
                          className="text-primary-600 underline underline-offset-2 hover:text-primary-700"
                        >
                          {metersLegend.where.linkLabel}
                        </Link>
                      </p>
                    </>
                  )}
                </div>
              )}
              {/* ===== 推导结果（issue #5202；契约 #5200 §四）=====
                  商家**主动填的只有三项**（颜色 + 净窗宽 + 净窗高）⇒ 加工类型 / 分幅 / 拼接 /
                  接高 / 接宽 / 用料一律**只读展示**服务端推导（`data.plan`）；要改走下面「改工艺参数」
                  入口（裁定 6：自动推导的工艺配置仍然能人工修改，改过留痕、不再被覆盖）。
                  `reason` 与**候选逐条**（含不可行的）都摆出来：裁定 3 要系统逐个「再算一遍」，
                  商家要能核对判定。 */}
              {!isFabricLine && line.calc && (
                <div
                  data-testid="craft-plan"
                  className="rounded border border-neutral-200 bg-neutral-50/60 px-3 py-2"
                >
                  {/* **③ 用料方案的标题行**（2026-09-30 第五批；🔴 第六批改判）：结论与逐项**都在这一块里** ——
                      第六批起它不再自己折叠（整块推导细节一起展开，用户逐字「推导细节都收拢到一个折叠区域，
                      打开后展示全部细节」）；2026-09-29 那条「结论常显」随之作废，那个数仍**常显在
                      用料米数输入框**上（同一份算料结果）。旧文留档：结论常显在 summary 上
                      点标题才展开逐项与依据 —— **不再折叠套折叠**（用户 2026-09-30 逐字
                      「就不要折叠套折叠了，可以排版对每块推导工艺做一些说明文字，比如 1 2 3 或者
                      直接门幅 工艺之类的标题？注意排版，不要占用太大空间，默认全部折叠，
                      需要引导用户查看推导细节」）。 */}
                  <p className="text-xs text-neutral-600">
                    <span className="font-medium">③ 用料方案</span>
                    {plan && (
                      <>
                        <span data-testid="craft-plan-mode" className="text-neutral-900">
                        加工类型：{plan.cutting_mode}
                        {/* **项级**来源（甲，issue #5287 ①b）：只在**人工改过**时标出来 ——
                        「（系统推导）」是常态，逐项重复只是噪声（用户实测读着吵）。 */}
                        {planSources.cuttingMode === 'manual' && (
                        <span
                        data-testid="craft-plan-mode-source"
                        className="ml-1 text-amber-600"
                        >
                        （人工指定）
                        </span>
                        )}
                        </span>
                        <span
                        data-testid="craft-plan-headline"
                        className="rounded bg-primary-50 px-1.5 font-medium text-primary-700"
                        >
                        {craftPlanConclusion.headline}
                        </span>
                        <span
                        data-testid="craft-plan-meters"
                        className={
                        engineRejected
                        ? 'font-medium text-red-600'
                        : 'font-medium text-neutral-900'
                        }
                        >
                        {/* 判据 5（issue #5287 ③）：引擎拒绝时这块显示的是**上一次成功试算的旧值**
                        （失败分支只写 `calcError`、**不更新** `calc`）⇒ 必须标「已失效」，
                        否则商家会把一个已不成立的数当成本次用料（而金额仍按它计）。 */}
                        {engineRejected
                        ? `用料 ${plan.meters} 米（已失效：本次算料被引擎拒绝，该值是上一次成功试算的旧值）`
                        : `用料 ${plan.meters} 米`}
                        </span>
                        
                      </>
                    )}
                  </p>
                  {plan ? (
                    <>
                      {/* **结论 + 逐项白话**（2026-09-29 用户第二次裁定）：旧形态把引擎的**内部读数**
                          原样摊开（`来源汇总：人工指定 0 项 · 系统推导 4 项（逐项见括号）` / `分幅 —` /
                          `接高 — 米`）⇒ 用户读不出「到底要不要拼接 / 接高 / 接宽 / 分幅」。
                          数一律取自引擎 `plan`（`craftPlanConclusionOf` 只做措辞，不重算任何几何/用料）。 */}
                      <ul
                        data-testid="craft-plan-items"
                        className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-neutral-500"
                      >
                        {craftPlanItems.map((item) => (
                          <li key={item.label}>
                            {item.label}{' '}
                            <span
                              className="text-neutral-700"
                              data-testid={CRAFT_PLAN_ITEM_TESTIDS[item.label]}
                            >
                              {item.value}
                            </span>
                          </li>
                        ))}
                      </ul>
                      {/* 拼接那一档的**下游处置**（并入特殊选项 / 引擎拒绝 / 人工勾过）要说清 ——
                          推导错 = 多插一道工序、多算工钱（issue #5211）。 */}
                      {spliceOption !== null && (
                        <p
                          data-testid="craft-plan-splice-state"
                          className="mt-0.5 text-[11px] text-neutral-500"
                        >
                          {derivedOptionState(spliceOption) === 'merged'
                            ? '拼接已并入特殊选项 ⇒ 插工序 + 计件'
                            : derivedOptionState(spliceOption) === 'engine-rejected'
                              ? '拼接未生效：引擎拒绝本次参数组合 ⇒ 不插工序、不计件（原因见上方红字）'
                              : derivedOptionState(spliceOption) === 'manual'
                                ? '拼接是你在特殊选项里手工勾的 ⇒ 人工优先'
                                : '拼接已忽略：不插工序、不计件'}
                        </p>
                      )}
                      {/* **推导依据默认收起**（2026-09-29 用户裁定：「这里的推算过程太多太细了」）——
                          结论留在上面那行（加工类型 / 用料 / 拼接 / 接高接宽），逐条依据与每个候选
                          **要核对时**再展开。⚠️ 收起的只是**默认展开态**：`craft-plan-reason` /
                          `craft-plan-candidates` 照旧渲染（既有判据仍读得到），红证方向 = 整块删掉。 */}
                        <p data-testid="craft-plan-reason" className="mt-1 text-[11px] text-neutral-500">
                          {/* 引擎文案里的**候选键是英文枚举**（契约 #5200 §三：键名冻结）——
                              展示层换成与下方候选清单**同一份**中文名（2026-09-30 用户逐字
                              「这里的 `fixed_height`，用中文术语，不要用英文」）。 */}
                          依据：{craftPlanReasonText(plan.reason)}
                        </p>
                        <ul data-testid="craft-plan-candidates" className="mt-1.5 space-y-0.5">
                          {(plan.candidates ?? []).map((candidate) => (
                            <li
                              key={candidate.key}
                              data-testid={`craft-plan-candidate-${candidate.key}`}
                              className="text-[11px] text-neutral-500"
                            >
                              <span className="text-neutral-600">
                                {craftPlanCandidateLabel(candidate.key)}
                              </span>
                              {candidate.feasible ? (
                                <span className="text-neutral-700">
                                  ：可行 · 用料 {candidate.meters ?? '—'} 米 · 拼接{' '}
                                  {candidate.splice_times ?? 0} 次
                                </span>
                              ) : (
                                <span className="text-neutral-400">
                                  ：不可行 —— {candidate.reason}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      {/* R4（裁定 1：出现拼几次就只能是单色）—— **显式冲突告知**，绝不替商家改款式 */}
                      {craftPlanHasSplice(plan) && line.craft.style === STYLE_MIXED && (
                        <p
                          data-testid="craft-plan-style-conflict"
                          className="mt-1 text-xs text-amber-700"
                        >
                          系统推导出「{craftPlanSpliceText(plan)}」⇒ 款式只能是单色（拼N次 ≠ 拼色）；
                          当前款式是「{STYLE_MIXED}」—— 请自行改回「单色」（系统不会替你改款式）。
                        </p>
                      )}
                      {/* R5：`splice_option=null` 且 N ≥ 4 ⇒ 明说「需人工处理」（**不发明「拼4次」**） */}
                      {plan.splice_option === null && Number(plan.splice_times) >= 4 && (
                        <p
                          data-testid="craft-plan-splice-manual"
                          className="mt-1 text-xs text-amber-700"
                        >
                          拼 {plan.splice_times} 次没有对应的特殊选项（只有 拼1次 / 拼2次 / 拼3次）
                          ⇒ 需人工处理。
                        </p>
                      )}
                      {/* 单点口径（契约 #5200 判据 10）：`plan.meters` 必须等于 `fabric_meters`
                          —— 不等就摆到台面上（数量一律按算料结果，不显示成一个"看起来对"的两个数） */}
                      {Number(plan.meters) !== Number(line.calc?.fabric_meters) && (
                        <p
                          data-testid="craft-plan-meters-mismatch"
                          className="mt-1 text-xs text-amber-700"
                        >
                          推导用料 {plan.meters} 米 ≠ 算料结果 {line.calc?.fabric_meters} 米 ——
                          数量按算料结果（单一来源），请核对。
                        </p>
                      )}
                      {/* 候选逐条已移入上面的「推导依据」折叠项（`craft-plan-candidates` 只有一处） */}
                    </>
                  ) : (
                    <p data-testid="craft-plan-unavailable" className="text-xs text-amber-700">
                      推导方案暂不可用（系统不会自行猜一个方案）：请确认已选规格（颜色 / 门幅）
                      并填好净尺寸；若都已就绪仍无方案，加工类型 / 拼接 / 接高接宽请人工确认。
                    </p>
                  )}
                </div>
              )}
      </div>
    </details>
  )

  return (
    <div className="rounded-xl border border-neutral-200 bg-white">
      {/* ⚠️ **行头已移除**（issue #4521）：组头已经写了商品名 / 颜色 / 帘体 / 金额 ——
          部位行头再写一遍是同屏重复（#4508 修过一次「商品名重复」，这次去掉的是**整块**多余）；
          「卡片收起」也随之取消：四个**手风琴步骤**本身就是密度控制（#4511）。 */}
      <div className="p-4">

            {/* ① **尺寸与数量 · 工艺规格**（issue #4874 两步化：区块 1 = 尺寸与数量 + 工艺规格）
                —— 用户 2026-09-21：「尺寸数量+工艺规格合并到一个区块」。
                序号/摘要/展开态按新结构走：摘要同时带出尺寸米数单价**与**工艺规格的合并结果。 */}
            <WizardStep
              step={1}
              title="用料与规格"
              badges={
                // **该步收起时也看得见**（issue #5840）：手风琴一次只开一步，开在②时①里的
                // 宽高 / 数量 / 单价报错原本一个字都看不见。
                lineErrorCount > 0 ? (
                  <span
                    data-testid="wizard-step-error-badge"
                    className="shrink-0 rounded bg-red-50 px-1.5 text-xs font-medium text-red-600"
                  >
                    缺 {lineErrorCount} 项
                  </span>
                ) : undefined
              }
              summary={`${summarySize} · ${line.quantity} 米 · ${formatAmount(Number(line.unitPrice) || 0)}/米 · ${summarySpec || '按行业默认'}`}
              aside={derivationAside}
              {...stepProps(1)}
            >
            {/* **用料与规格（系统推导）**（2026-09-28 布局）——这里只剩**推导读数**：
                用料米数 / 单价常态**只读展示**（值分别来自算料引擎与所选规格），要改才点「改」
                就地变输入框；净窗宽 / 净窗高已提到**组级**（商品 / 颜色之后 —— 那才是商家唯一的输入面），
                「部位备注」移入下一步「其他」。
                ⚠️ 手改留痕一字未变：改用料 ⇒ `人工指定` + 记下本次入参签名（未跟随要显式告知 + 一键恢复）。 */}
            <div className="pt-4 border-t border-neutral-100">
              {/* **规格 / 用料 / 单价 —— 同一行三格**（2026-09-30 第四批；用户逐字「门幅放进用料与规格中，
                  和用料米数、单价放一行」）。
                  为什么这三个同屏：它们是**同一件事的三个数** —— 门幅决定分幅与用料、用料 × 单价 = 金额；
                  且三者都是「**系统给、商家可就地改**」（2026-09-29 裁定：常态可编辑，无「改」入口）。
                  ⚠️ `specPicker` 由组级传入（唯一一份 JSX）；未选颜色 / 该颜色无可用规格 ⇒ 退回两格。 */}
              <div
                data-testid="spec-input-row"
                className={'grid grid-cols-1 gap-4 ' + (specPicker ? 'sm:grid-cols-3' : 'sm:grid-cols-2')}
              >
                {specPicker && <div>{specPicker}</div>}
                <div>
                  {/* label = 「用料米数」（issue #4598）：这个输入框的值**就是加工费米数**
                      （`info.processingMeters = line.quantity`，加工费 = 组合单价 × 它），
                      而它的值本身由算料写回（`fabric_meters`）—— 叫「数量」会被商家读成「买几套」。
                      ⚠️ 布料行（`FabricRow`）**不改**：布料按 `sellingMethod` 卖布，不是同一个业务。 */}
                  {/* 2026-09-29（用户裁定「移除这种设计，当前编辑态就是允许用户直接更改的」）：
                      常态**可编辑** —— 只读展示 + 点「改」那套已删除；算料结果照旧写回这个框，
                      商家要覆盖就**直接改**（一改 `metersSource` 即翻「人工指定」，留痕不变）。 */}
                  <Label required>用料米数</Label>
                  {/* issue #5202：换成保留原始文本的数字框 —— 改前 `value={line.quantity || ''}`
                      + `Number(raw)` 会把 `0` 渲染成空串（输入 "0" 当场清空 ⇒ 打不出 "0.5"）。 */}
                  <NumberInput
                    value={line.quantity}
                    onChange={(next) => onChangeQty(next ?? 0)}
                    decimals={3}
                    placeholder="米"
                    aria-label="用料米数"
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errQty && <p className="mt-1 text-sm text-red-600">{errQty}</p>}
                  {/* 🔴 2026-09-30 第六批（用户逐字「= 加工费米数 这个直接移除」）：这行旁注**整条删除** ——
                      字段名「用料米数」本身已说明它就是加工费米数（`info.processingMeters = line.quantity`），
                      再写一行只是噪声。旧文留档（不再渲染）：把口径写在旁边 —— 商家一眼对得上加工费按哪个数算。 */}
                  {/* 算料来源（issue #4434）：**公式串与参数说明已移到下方「整行」块**
                      （2026-09-29 第二次裁定：「推导说明的右侧空白也能利用起来，把文案完全平铺开」）
                      —— 这里只留「人工指定」这条**与输入框直接相关**的状态与一键恢复。 */}
                  {line.metersSource === LINE_METERS_SOURCE_MANUAL && (
                    <>
                      <p className="mt-1 text-xs text-amber-600">
                        人工指定
                        <button
                          type="button"
                          onClick={onRestoreFormula}
                          className="ml-1.5 underline hover:text-amber-700"
                        >
                          恢复按公式计算
                        </button>
                      </p>
                      {/* **显式告知**（issue #5202 · 根因 2）：人工指定的数**没跟随**这次改动 ——
                          不静默覆盖商家手填的数，也不让商家自己猜为什么数没变（一键恢复就在上面）。
                          ⚠️ 判据 2′（issue #5281）：句内**补上**推导值与差（`metersCompareText`）——
                          改前商家要知道"差多少"得自己去上方面板按「用料方案（系统推导）」那行自己减。 */}
                      {metersStale && (
                        <p data-testid="meters-manual-stale" className="mt-1 text-xs text-amber-700">
                          用料已人工指定（{line.quantity} 米；{metersCompareText}）—— 宽 / 高 / 门幅或工艺改动后系统
                          <strong>未跟随</strong>重算（不会偷偷覆盖你手填的数）；点上方「恢复按公式计算」
                          按新参数重算。
                        </p>
                      )}
                    </>
                  )}
                  {line.calcError && <p className="mt-1 text-xs text-red-600">{line.calcError}</p>}
                  {/* 非韩褶不自动算用料（issue #4488，用户裁定）：加工项直接体现费用 ⇒ 米数手填。
                      **不静默停在默认 1 米** —— 那会让「1 米 × 单价」直接算出一个错金额。 */}
                  {!line.calc &&
                    !line.calcError &&
                    Number(line.width) > 0 &&
                    Number(line.height) > 0 &&
                    isAutoCalcUnavailable(calcInputOf(line, calcConfig)) && (
                      <p className="mt-1 text-xs text-amber-600">
                        该工艺无自动算料，请手填米数
                      </p>
                    )}
                </div>
                <div>
                  {/* 单价来自所选规格（SKU）；2026-09-29 起常态**可编辑**（议价等人工改价直接改） */}
                  <Label required>单价 (¥/米)</Label>
                  <NumberInput
                    value={line.unitPrice}
                    onChange={(next) => onChangePrice(next ?? 0)}
                    decimals={3}
                    aria-label="单价 (¥/米)"
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errPrice && <p className="mt-1 text-sm text-red-600">{errPrice}</p>}
                </div>
              </div>
              {/* **识别来的工艺要求**（issue #5794）—— 逐字说出「按图选了什么」，商家一眼可核对
                  （用户口径「根据图中客户要求来决定工艺规格和加工项选择了，**不能选错**」）。 */}
              {line.recognizedCraftText && (
                <p data-testid="recognized-craft-note" className="mt-2 text-xs text-primary-600">
                  {RECOGNIZE_SOURCE_TAG} 按图中客户要求：{line.recognizedCraftText}
                </p>
              )}

            </div>

              {/* 工艺参数（原 ②，已并入区块 1）—— §4.2 字段表 A + §4.8 双拼
                  + **就地「改」入口**（issue #5202 · 裁定 6）：默认收起，推导结果在上一块只读展示
                  + **收起态把当前所选摆出来并高亮**（issue #6399，2026-10-06 用户逐字「这里折叠的
                    部分得把折叠的内容展示出来，不然用户不知道选择了什么，而且得高亮展示」）——
                    展开态**不**重复渲染（内容本来就在眼前）。 */}
              <div className="pt-4 mt-4 border-t border-neutral-100">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                  <button
                    type="button"
                    data-testid="craft-plan-edit"
                    aria-expanded={craftEditOpen}
                    onClick={() => setCraftEditTouched(!craftEditOpen)}
                    className="h-8 px-3 rounded border border-neutral-300 bg-white text-xs text-neutral-600 hover:border-neutral-400 transition-colors"
                  >
                    {craftEditOpen ? '收起工艺参数' : '改工艺参数（加工类型 / 打开方式 / 款式 / 用料公式）'}
                  </button>
                  {!craftEditOpen && craftPlanCurrentRows.length > 0 && (
                    <div
                      data-testid="craft-plan-current"
                      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded border border-primary-200 bg-primary-50 px-2 py-1"
                    >
                      <span className="text-[11px] text-neutral-500">当前</span>
                      {craftPlanCurrentRows.map((row) => (
                        <span key={row.label} className="text-[11px] text-neutral-500">
                          {row.label}
                          <span className="ml-1 font-medium text-primary-700">{row.value}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                {craftEditOpen && (
                  <div className="mt-3">
                <OrderCraftFields
                  value={craftSpec}
                  onChange={onChangeCraft}
                  mainMeters={line.quantity}
                  calcConfig={calcConfig}
                  pleatCount={line.calc?.pleat_count ?? null}
                  // issue #5020：未指定加工类型 ⇒ 系统按门幅规则自动选中 ⇒ 标出「自动」
                  // （客服看得见「这不是我选的」，且点任意一档即可覆盖）
                  cuttingModeAuto={!line.craft.cuttingMode && Boolean(cuttingModeOf(line))}
                  edgeMeters={line.edgeMeters}
                  onEdgeMetersChange={onEdgeMetersChange}
                  edgeUnitPrice={line.edgeUnitPrice}
                  onEdgeUnitPriceChange={onEdgeUnitPriceChange}
                />
                  </div>
                )}

              {/* **系统识别**（2026-09-29 起**常态可见**）—— issue #4658 的**归属**口径未变
                  （它在 ①用料与规格 里，不在 ②加工项），变的是**不再藏在「改工艺参数」按钮后面**：
                  用户 2026-09-29 裁定「推导出的（系统识别 + 人工加 / 改）这两部分应该合并到
                  用料与规格那里」⇒ 两块与上面那块推导读数并列、直接可见。 为什么归这里：
                  它由「窗宽/窗高 + SKU 门幅」推出、产出进**加工费组合键** ⇒ 属**规格/报价**语义；
                  且它**不可手选、与加工项勾选无联动** ⇒ 放在「你勾什么」的加工项区会误导。
                  这里**紧挨推导依据**展示（`reason` 逐条显示，商家要能核对判定）。

                  issue #4657：推算错 = 价格错（推算特征进组合键）⇒ 每条可**采纳 / 不采纳**，
                  系统漏判时可**强制加**；**生效值** = `推算 ∪ 强制加 − 不采纳`（唯一喂给组合键）。
                  标来源「推算」：本条判据是**推理非实证**，不假装定论；门幅走默认值时也照实标出。
                  ⚠️ 布料组整组无加工（#4493）⇒ 这块整块不渲染（与「加工项」「费用明细」同闸门）。 */}
              {!isFabricLine && (
                <div
                  data-testid="auto-detected-features"
                  className="mt-3 rounded border border-dashed border-neutral-300 bg-neutral-50/60 px-3 py-2"
                >
                  <div className="text-xs font-medium text-neutral-600">
                    系统识别（按窗宽窗高与门幅推算，不可手选；可采纳 / 不采纳）
                  </div>
                  {/* issue #4899：规则**判不了**时要显式说明「缺什么就动不了」，不许静默什么都不做
                      （用户实测「无法反选门幅」的一种形态 = 尺寸没填、页面却一言不发） */}
                  {!line.selectedSku &&
                    doorWidthChoice.plan.state === 'undecidable' &&
                    doorWidthChoice.plan.code === 'missing-size' && (
                      <p data-testid="door-width-need-size" className="mt-1 text-xs text-neutral-500">
                        填完窗宽窗高后，系统会按规则自动选最优门幅（可行集里最小门幅 / 定宽买高分幅最少）
                      </p>
                    )}
                  {doorWidthMissing && (
                    <p data-testid="door-width-missing" className="mt-1 text-xs text-amber-600">
                      该 SKU 未维护门幅 ⇒ 分幅与加工类型判不了（系统不按缺省门幅推算）—— 请先补商品门幅。
                      （⚠️ 超高 / 超宽不受此影响：它们按净窗宽 / 净窗高与本租户的阈值判定）
                    </p>
                  )}
                  {/* **门幅规则**（issue #4877）：① 所选门幅不可行 ⇒ 需接高（强告警）；
                      ② 可行但**不是最省**（非规则解）⇒ 提示可换最优门幅。
                      ⚠️ 只是**提示**：不改客服已选的门幅、不进加工费组合键。 */}
                  {doorWidthChoice.verdict === 'infeasible' && doorWidthChoice.suggestion && (
                    <p
                      data-testid="door-width-needs-splice"
                      className="mt-1 text-xs font-medium text-danger-600"
                    >
                      {doorWidthChoice.suggestion}
                    </p>
                  )}
                  {doorWidthChoice.verdict === 'suboptimal' && doorWidthChoice.suggestion && (
                    <p data-testid="door-width-suboptimal" className="mt-1 text-xs text-amber-700">
                      {doorWidthChoice.suggestion}
                    </p>
                  )}
                  {/* **提示**（issue #4662 / #5130 改判）：加工类型与几何**矛盾** ⇒ 系统实际会按哪种算
                      （与算料引擎的自动回落一致）。
                      🔴 **原注释的「① 缺褶倍 ⇒ 未判超宽」已随 issue #5130 退役** —— 该提示
                      （`missing-fullness`）与 `missing-door-width` 两条都已从引擎删除（新判据不读褶倍/门幅）。
                      ⚠️ 提示**不改推算、不进组合键** —— 只把「商家所选加工类型」与「引擎实际计算」的
                      不一致**摆到台面上**（用户 2026-09-20 裁定 C）。 */}
                  {autoFeatureNotices.map((notice) => (
                    <p
                      key={notice.kind}
                      data-testid={`auto-feature-notice-${notice.kind}`}
                      className="mt-1 text-xs text-amber-700"
                    >
                      {notice.reason}
                    </p>
                  ))}
                  <ul className="mt-1.5 space-y-1">
                    {autoFeatureRows.map((row) => (
                      <li
                        key={row.name}
                        data-testid={`auto-feature-${row.name}`}
                        className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5"
                      >
                        <span
                          title={row.reason}
                          className={
                            'text-xs ' +
                            (row.rejected ? 'text-neutral-400 line-through' : 'text-neutral-700')
                          }
                        >
                          <span className="font-medium">{row.name}</span>
                          <span className="text-neutral-400">（{row.source}）</span>
                        </span>
                        {/* 逐条显示**判定依据**（#4658：商家要能核对「为什么判它超宽」） */}
                        <span className="text-[11px] text-neutral-500">{row.reason}</span>
                        {row.rejected ? (
                          <>
                            {/* 留痕（#4657）：谁改的、原推算是什么 —— 一行看得见 */}
                            <span
                              data-testid={`auto-feature-rejected-${row.name}`}
                              className="text-[11px] text-amber-600"
                            >
                              已忽略系统推算（依据：{row.reason}）
                            </span>
                            <button
                              type="button"
                              data-testid={`auto-feature-adopt-${row.name}`}
                              onClick={() => onAutoFeatureDecision(row.name, 'adopt')}
                              className="text-[11px] text-primary-600 underline hover:text-primary-700"
                            >
                              采纳
                            </button>
                          </>
                        ) : row.source === '手动加' ? (
                          <>
                            <span
                              data-testid={`auto-feature-manual-${row.name}`}
                              className="text-[11px] text-amber-600"
                            >
                              手动加（系统未推算）
                            </span>
                            <button
                              type="button"
                              data-testid={`auto-feature-remove-${row.name}`}
                              onClick={() => onAutoFeatureDecision(row.name, 'adopt')}
                              className="text-[11px] text-neutral-500 underline hover:text-neutral-700"
                            >
                              移除
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            data-testid={`auto-feature-reject-${row.name}`}
                            onClick={() => onAutoFeatureDecision(row.name, 'reject')}
                            className="text-[11px] text-neutral-500 underline hover:text-neutral-700"
                          >
                            不采纳
                          </button>
                        )}
                      </li>
                    ))}
                    {autoFeatureRows.length === 0 && (
                      <li className="text-xs text-neutral-400">
                        系统未识别出特征（如确有，可手动加）
                      </li>
                    )}
                  </ul>
                  {/* ===== **推导出的工序项**（2026-09-30 第五批；用户逐字「系统识别（按窗宽窗高与门幅推算，
                      不可手选；可采纳 / 不采纳）这里再加**接高和拼接**两项」）=====
                      为什么放这里：它和上面那些特征同属「**系统推的、你可裁决**」；改前它的裁决入口在
                      「用料方案」块里 ⇒ 同一件事两个操作面。现在**收敛到这一处**（用料方案只留读数）。

                      ⚠️ 它们**不是特征**（`lib/craft-auto-features.ts` 明文：不进 `AUTO_FEATURE_NAMES`、
                      不进特征那一路的组合键 —— #4592 的 P0）：值是**引擎 `plan` 推出来的特殊选项**，
                      走 `specialOptions` ⇒ 服务端插工序（`拼2次-布` / `接高-布`）+ 计件（0.8/1.2/1.6、1.0 元/幅）。
                      ⇒ 一律读引擎，**前端不自己算**接高 / 拼几次。

                      ⚠️ 拼接**可手动选档**（用户 2026-09-30 逐字「拼接…可以先不做自动推导，
                      **能让用户选择即可**」）：档位复用 `SPLICE_OVERRIDE_OPTIONS`（唯一真值），
                      落库走既有 `planOverrides.spliceTimes`；「由推导决定」= **不覆盖**（引擎说了算）。
                      接高本批**不给手动档**（只做采纳 / 不采纳；人工加接高米数仍随「人工加 / 改」隐藏）。 */}
                  <div
                    data-testid="craft-plan-derived-options"
                    className="mt-2 border-t border-dashed border-neutral-200 pt-1.5"
                  >
                    <p className="text-[11px] text-neutral-400">
                      推导出的工序项（进特殊选项 ⇒ 插工序 + 计件；可采纳 / 不采纳）
                    </p>
                    {derivedOptions.length === 0 && (
                      <p data-testid="craft-plan-derived-empty" className="mt-0.5 text-xs text-neutral-400">
                        系统未推导出接高 / 拼接（按当前尺寸与门幅不需要）
                      </p>
                    )}
                    {derivedOptions.map((name) => {
                      const state = derivedOptionState(name)
                      return (
                        <p
                          key={name}
                          data-testid={`craft-plan-derived-option-${name}`}
                          className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[11px] text-neutral-500"
                        >
                          <span className="font-medium text-neutral-700">「{name}」</span>
                          <span>
                            {state === 'manual'
                              ? '你在②特殊选项里手工勾过 ⇒ 人工优先'
                              : state === 'merged'
                                ? '已并入特殊选项（⇒ 插工序 + 计件）'
                                : state === 'engine-rejected'
                                  ? '未生效（引擎拒绝本次参数组合 ⇒ 不插工序、不计件）'
                                  : '已忽略（手工剔除）—— 不插工序、不计件'}
                          </span>
                          {state === 'merged' && (
                            <button
                              type="button"
                              data-testid={`craft-plan-derived-reject-${name}`}
                              onClick={() => onDerivedOptionDecision(name, 'reject')}
                              className="text-neutral-500 underline hover:text-neutral-700"
                            >
                              不采纳
                            </button>
                          )}
                          {state === 'rejected' && (
                            <button
                              type="button"
                              data-testid={`craft-plan-derived-adopt-${name}`}
                              onClick={() => onDerivedOptionDecision(name, 'adopt')}
                              className="text-primary-600 underline hover:text-primary-700"
                            >
                              采纳
                            </button>
                          )}
                        </p>
                      )
                    })}
                    {/* **拼接档位**（人工选；「由推导决定」= 交给引擎） */}
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-[11px] text-neutral-500">拼接</span>
                      <div
                        className="flex flex-wrap gap-1"
                        role="radiogroup"
                        aria-label="拼接（人工加）"
                      >
                        {SPLICE_OVERRIDE_OPTIONS.map((option) => {
                          const active =
                            (line.planOverrides?.spliceTimes ?? null) === (option.value ?? null)
                          return (
                            <button
                              key={option.label}
                              type="button"
                              role="radio"
                              aria-checked={active}
                              onClick={() => onChangePlanOverrides({ spliceTimes: option.value })}
                              className={
                                'h-6 px-2 rounded-full border text-[11px] transition-colors ' +
                                (active
                                  ? 'border-primary-600 bg-primary-50 text-primary-700'
                                  : 'border-neutral-300 bg-white text-neutral-600 hover:border-neutral-400')
                              }
                            >
                              {option.label}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  </div>
                  {/* **强制加**（#4657）：系统没推、但商家知道该算 —— 门幅数据缺失导致漏判时的唯一补救 */}
                  {addableAutoFeatures.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <span className="text-[10px] text-neutral-400">系统未推算？手动加：</span>
                      {addableAutoFeatures.map((name) => (
                        <button
                          key={name}
                          type="button"
                          data-testid={`auto-feature-add-${name}`}
                          onClick={() => onAutoFeatureDecision(name, 'add')}
                          className="rounded border border-neutral-300 bg-white px-1.5 text-[11px] leading-5 text-neutral-600 hover:border-neutral-400"
                        >
                          + {name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

                    {/* ===== 人工加 / 改（issue #5202 · 裁定 4/6）=====
                        自动推导的工艺配置**仍能人工修改**；人工改过的项随请求**显式下发**
                        （契约 #5200 §四 R7 ⇒ `auto=false`，此后不再被推导改判）。
                        上限（裁定 5）：接高 / 接宽缺口 ≤ 0.1 米；接高只在「定高买宽」下成立、
                        接宽只在「倒幅」下成立（契约订正 v1.1 ③）。
                    🔴 **2026-09-30 第四批：本期隐藏**（用户逐字「人工加 / 改**先隐藏**，本期不需要该功能」）。
                    形态 = `display:none`（`hidden` 类 ⇒ 屏幕上与**无障碍树**上都不存在，**不是**「藏在折叠里、
                    商家还能展开」）—— 但**节点仍在 DOM**：11 条既有页面判据（接高上限不截断 / 拼次落库 /
                    项级来源 / 引擎拒绝态）**一条不降**（铁律 8「只简化实现代码、不降测试门禁」）。
                    重新启用 = 把 `SHOW_MANUAL_OVERRIDES` 置 `true`（同批改回 OR-052 判据 11）。 */}
                    <div
                      data-testid="craft-plan-manual"
                      className={
                        (SHOW_MANUAL_OVERRIDES ? '' : 'hidden ') +
                        'rounded border border-neutral-200 bg-white px-3 py-2'
                      }
                    >
                      <div className="text-xs font-medium text-neutral-600">
                        人工加 / 改（改过的项不再被自动推导覆盖）
                      </div>
                      {/* ⚠️ **2026-09-30 第五批**：拼接档位已搬到「系统识别 → 推导出的工序项」里
                          （用户要求「拼接能让用户选择即可」）⇒ 这里**不再留第二份**同名 radiogroup
                          （两份会让「同一件事两个操作面」成立，也会让按 aria-label 取元素的判据歧义）。
                          本块（本期 `hidden`）只剩**人工加接高 / 接宽**。 */}
                      {canJoinHeight || canJoinWidth ? (
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                          <span className="text-neutral-500">
                            人工加{canJoinHeight ? '接高' : '接宽'}（米，≤ {JOIN_GAP_MAX_METERS}）
                          </span>
                          <NumberInput
                            data-testid={
                              canJoinHeight
                                ? 'craft-plan-join-height-input'
                                : 'craft-plan-join-width-input'
                            }
                            aria-label={`人工加${canJoinHeight ? '接高' : '接宽'}（米）`}
                            value={
                              (canJoinHeight
                                ? line.planOverrides?.joinHeightM
                                : line.planOverrides?.joinWidthM) ?? null
                            }
                            onChange={(next) =>
                              onChangePlanOverrides(
                                canJoinHeight ? { joinHeightM: next } : { joinWidthM: next }
                              )
                            }
                            decimals={3}
                            className="w-24 h-8 px-2 rounded border border-neutral-300 text-xs focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                          />
                        </div>
                      ) : (
                        <p className="mt-2 text-[11px] text-neutral-400">
                          加工类型未定 ⇒ 无法人工加接高 / 接宽（接高只在「定高买宽」下成立、
                          接宽只在「倒幅」下成立）
                        </p>
                      )}
                      {joinGapOverLimit && (
                        <p data-testid="craft-plan-join-error" className="mt-1 text-xs text-red-600">
                          缺口 {String(joinGapRaw)} 米超出上限 {JOIN_GAP_MAX_METERS} 米 ⇒ 不可加
                          （上限是硬规则；系统不会替你截断成 {JOIN_GAP_MAX_METERS} 米，
                          也不会把这个数发出去）
                        </p>
                      )}
                    </div>
              </div>
            </WizardStep>

            {/* ② **加工项**（2026-09-29 两步化：本步 = 「勾什么加工项」+ 「特殊选项」+ 「部位备注」
                —— 原 ③ 其他 已并入本步的第二、三块，不再单独占一个折叠步骤） */}
            <WizardStep
              step={2}
              title="加工项"
              summary={
                // #4576：摘要里带上**工艺**（哪一项），不再让商家回头数；计数口径不变（仍只数**手选**项）
                // 2026-09-29：**特殊选项**并入本步 ⇒ 摘要里一并报它的项数（折叠时也看得见）
                // ⚠️ 项数按**生效集**数（issue #7849）：展开后那一排 chips 勾着的就是生效集 ---- 摘要数人工项
                // 会出现「摘要 0 项、展开却有 1 项选中」这种同屏打架。
                [
                  selectedProcessingCount > 0
                    ? `已选 ${selectedProcessingCount} 项` +
                      (selectedProcessingNames.length > 0
                        ? ` · ${selectedProcessingNames.join(' + ')}`
                        : lineCraft
                          ? ` · 工艺：${lineCraft}`
                          : '')
                    : '未选',
                  effectiveOptions.length > 0
                    ? `特殊选项 ${effectiveOptions.length} 项`
                    : null,
                  (line.remark ?? '').trim() !== '' ? '有部位备注' : null,
                ]
                  .filter(Boolean)
                  .join(' · ')
              }
              {...stepProps(2)}
            >
              {/* ===== **系统推荐组合**（2026-09-28 用户裁定）=====
                  用户口径：「正常用户提供净窗高 / 窗宽，然后再确认是否要韩折 / 打孔 / 定型等信息即可」
                  ⇒ 推荐组合（韩褶 + 布帘「定型」）由系统**预选**，商家在这里一键**采纳 / 全不采纳**。
                  撤过就留痕（`craftItemTouched` / `shapedItemTouched`）⇒ 换商品 / 改帘体不再勾回。
                  为什么预选的是**加工项**：工艺的唯一派生点仍是「勾选的工艺项的 `craftHint`」（#4566）。 */}
              {recommendedItems.length > 0 && (
                <div
                  data-testid="processing-recommended"
                  className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded border border-primary-100 bg-primary-50/40 px-3 py-2"
                >
                  <span className="text-xs text-neutral-600">系统推荐：</span>
                  <span
                    data-testid="processing-recommended-names"
                    className="text-xs font-medium text-neutral-900"
                  >
                    {recommendedItems.map((pi) => pi.name).join(' + ')}
                  </span>
                  <button
                    type="button"
                    data-testid="processing-recommended-adopt"
                    onClick={() => onRecommendedDecision('adopt')}
                    className="text-xs text-primary-600 underline underline-offset-2 hover:text-primary-700"
                  >
                    采纳
                  </button>
                  <button
                    type="button"
                    data-testid="processing-recommended-reject"
                    onClick={() => onRecommendedDecision('reject')}
                    className="text-xs text-neutral-500 underline underline-offset-2 hover:text-neutral-700"
                  >
                    全不采纳
                  </button>
                </div>
              )}
              {processingLoading ? (
                <div className="text-sm text-neutral-400 py-2">加工项加载中…</div>
              ) : handPickableItems.length === 0 ? (
                <div className="text-sm text-neutral-400 py-2">暂无可用加工项</div>
              ) : (
                <div className="space-y-3">
                  {/* 关键字搜索（issue #4576）—— 项数 > 8 才出现（项少时搜索框本身是噪音）。
                      跨分类命中；清空后回到当前选中的分类。过滤只影响渲染，不动勾选态。 */}
                  {handPickableItems.length > 8 && (
                    <input
                      type="search"
                      data-testid="processing-search"
                      aria-label="搜索加工项"
                      placeholder="搜索加工项…"
                      value={processingQuery}
                      onChange={(e) => setProcessingQuery(e.target.value)}
                      className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    />
                  )}

                  {/* 一级分类导航（issue #4576）—— **只有一类时不渲染**（一个 tab 是噪音），
                      直接显示该类下的项；目录没配分类 ⇒ 全部平铺。两种边界都不报错。 */}
                  {hasProcessingCategoryNav && (
                    <div
                      data-testid="processing-category-selector"
                      className="flex flex-wrap gap-1.5"
                    >
                      {processingCategoryGroups.map((group) => {
                        const active = !searchingProcessing && group.id === activeCategory?.id
                        return (
                          <button
                            key={group.id || 'uncategorized'}
                            type="button"
                            data-testid={`processing-category-${group.id || 'uncategorized'}`}
                            aria-pressed={active}
                            onClick={() => {
                              // 点分类 = 回到该分类的浏览态（清掉搜索，避免「选了分类却还在看全局结果」）
                              setProcessingQuery('')
                              setActiveCategoryId(group.id)
                            }}
                            className={
                              'h-8 px-3 rounded-full border text-sm transition-colors ' +
                              (active
                                ? 'border-primary-600 bg-primary-50 text-primary-700'
                                : 'border-neutral-300 bg-white text-neutral-600 hover:border-neutral-400')
                            }
                          >
                            {group.name}
                          </button>
                        )
                      })}
                    </div>
                  )}

                  {/* 工艺项 = **单选**语义：单值护栏**只在带 `craftHint` 的项之间**生效
                      ⇒ 这个区别不因改成分类导航而丢掉（#4576 用户口径）。 */}
                  {visibleProcessingItems.some((pi) => Boolean(pi.craftHint)) && (
                    <p className="text-xs text-neutral-400">
                      带「单选」的工艺项只能选一个 —— 换选会自动取消前一个
                    </p>
                  )}

                  {/* #4566：手选列表 = 目录**滤掉自动推导特征**后的清单（超高/超宽/倒幅不出控件） */}
                  <div className="flex flex-wrap gap-2">
                    {visibleProcessingItems.map((pi) => {
                      const cfg = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
                      return (
                        <div
                          key={pi.id}
                          className={
                            'rounded border transition-colors ' +
                            (cfg.selected
                              ? 'border-primary-300 bg-primary-50/40'
                              : 'border-neutral-200 bg-white')
                          }
                        >
                          <label className="flex items-center gap-2 h-9 px-3 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={cfg.selected}
                              onChange={(e) => onToggleProcessing(pi, e.target.checked)}
                              aria-label={pi.name}
                              className="w-4 h-4 accent-primary-600 shrink-0"
                            />
                            <span className="text-sm font-medium text-neutral-900">{pi.name}</span>
                            {/* 「单选」标记：只挂在**工艺项**（`craftHint` 非空）上 */}
                            {Boolean(pi.craftHint) && (
                              <span
                                data-testid={`processing-single-badge-${pi.id}`}
                                title="工艺项：一张单只能选一个"
                                className="rounded border border-amber-200 bg-amber-50 px-1 text-[10px] leading-4 text-amber-700"
                              >
                                单选
                              </span>
                            )}
                            {/* 搜索跨分类命中时标出所属分类（未搜索时只显示当前分类，无需重复标） */}
                            {searchingProcessing && (
                              <span className="text-[10px] text-neutral-400">
                                {categoryNameOf(pi)}
                              </span>
                            )}
                            {/* **不展示加工项单价**（issue #4526 · R10，用户 2026-09-19「订单上的
                                加工项选择控件不要展示加工项单价」）：ERP 的加工项是**组合价目**
                                （特征集合 → 元/米），**价格只在组合上存在** ⇒ 逐项显示单价必然误导
                                （同一真值两个数：逐项之和对不上组合价，商家会照错的数对账）。
                                只保留「数量 + 单位」供核对勾了什么 —— 摘的是**钱**，不是数量。
                                行金额同样不显示（它与组合价不是同一口径；金额一律见「费用明细」）。 */}
                            {cfg.selected && (
                              <span className="text-sm font-semibold text-primary-600 shrink-0">
                                {Math.max(1, Number(cfg.qty) || 1)}
                                {pi.unit || '项'}
                              </span>
                            )}
                          </label>
                        </div>
                      )
                    })}
                  </div>

                  {/* 搜索无命中 ⇒ 不静默留白 */}
                  {visibleProcessingItems.length === 0 && (
                    <div className="text-sm text-neutral-400 py-2">没有匹配的加工项</div>
                  )}

                  {/* ⚠️ 「自动识别」块**已移出**本区（issue #4658）：加工项区**只保留可勾的东西**
                      —— 该块由宽高 + 门幅推出、产出进加工费组合键，属**规格/报价**语义，
                      且**不可手选、与勾选无联动** ⇒ 现渲染在 ②工艺规格（`auto-detected-features`）。 */}
                </div>
              )}

              {/* ===== **加工费组合**明细块（issue #4874；#7642 起已配置的组合也能改**本单**单价）=====
                  用户 2026-09-21：「订单中加工费组合**未配置**的情况下，**允许更改该单价**，
                  并且在**加工项下面添加具体的组合名**」；
                  🔴 用户 2026-10-24（issue #7642）：「**新增订单中的加工费组合需要允许修改**」⇒ 已配置的行
                  **也给**「改本单单价」入口（价目那一份不动；未配置行仍按 #4872 在建单后记入价目）。
                  逐行 = 组合名（`feeDetail.items.join(' + ')`，与「加工费组合」页**逐字同源**）
                  + 单价（**读态价 + ✏️**，点铅笔才出输入框 —— 用户 2026-10-24：「样式改成工艺项 ·
                  计件单价的样式」，issue #7658）+ 组合价目参考价 + 来源。
                  ⚠️ 改完立刻以该价**重发 `feePreview`**（同一份 `buildLineProcessingInfo` ⇒ 页面金额
                  与提交口径一致），并以 `processingInfo.processingFeeOverride` 随建单提交（后端 #4872）。 */}
              {hasAnyProcessingSelection && (
                <div
                  data-testid="processing-fee-combinations"
                  className="mt-3 rounded border border-neutral-200 bg-neutral-50/60 px-3 py-2"
                >
                  <div className="text-xs font-medium text-neutral-600">加工费组合</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
                    <span data-testid="fee-combination-name" className="text-neutral-700">
                      {feeCombinationLabel}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <span className="text-neutral-400">单价</span>
                      {/* 改价（issue #7658）：与「工序库 / 工艺项」的计件单价同一套交互 ——
                          读态 = `¥7.00/米` + ✏️；点铅笔才出输入框 + ✓ 保存 / ✕ 取消。
                          ① 草稿只活在本地 ⇒ 录入过程**不发预览**（改完点 ✓ 才生效）；
                          ② `0` 是有效价（本单免加工费），空框 = 不改价（按组合价目）—— 两者都可达；
                          ③ issue #4878 P1 的「入口常驻」由「读态一直有铅笔」满足，不会改完就消失。 */}
                      {feeEditing && canOverrideFee ? (
                        <>
                          <NumberInput
                            data-testid="fee-unit-price-override"
                            aria-label="改本单单价（元/米）"
                            placeholder="元/米"
                            value={feeDraft}
                            onChange={(next) => setFeeDraft(nonNegativeOrNull(next))}
                            decimals={3}
                            className="w-24 h-8 px-2 rounded border border-neutral-300 text-xs focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                          />
                          <span className="text-neutral-500">元/米</span>
                          <button
                            type="button"
                            aria-label="保存单价"
                            data-testid="fee-price-save"
                            title="保存本单单价"
                            onClick={() => {
                              onProcessingFeeOverrideChange(feeDraft)
                              setFeeEditing(false)
                            }}
                            className="rounded p-1 text-primary-600 hover:bg-neutral-100"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            aria-label="取消改价"
                            data-testid="fee-price-cancel"
                            title="取消（不改这一单的价）"
                            onClick={() => setFeeEditing(false)}
                            className="rounded p-1 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-700"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <>
                          <span
                            data-testid="fee-unit-price"
                            className={cn(
                              'tabular-nums',
                              feeReadPrice == null ? 'text-amber-600' : 'text-neutral-700',
                            )}
                          >
                            {feeReadPrice == null ? '未定价' : `¥${formatAmount(feeReadPrice)}/米`}
                          </span>
                          {canOverrideFee && (
                            <button
                              type="button"
                              aria-label="改本单单价"
                              data-testid="fee-price-edit"
                              title={
                                feeReferencePrice != null
                                  ? `改本单单价（组合价目 ${formatAmount(feeReferencePrice)}/米 不变）`
                                  : '改本单单价（建单后记入「加工费组合」价目）'
                              }
                              onClick={() => {
                                setFeeDraft(
                                  line.processingFeeOverride ??
                                    (Number.isFinite(feeUnitPrice) ? feeUnitPrice : null),
                                )
                                setFeeEditing(true)
                              }}
                              className="rounded p-1 text-neutral-500 hover:bg-neutral-100 hover:text-primary-600"
                            >
                              <Pencil className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </>
                      )}
                      {/* **组合价目**参考价（issue #7642）：只在**本单已改价**时摆出来 ——
                          读态价本身就是价目时再摆一遍是重复信息（§31 P2）。 */}
                      {line.processingFeeOverride != null && feeReferencePrice != null && (
                        <span
                          data-testid="fee-configured-price"
                          className="text-neutral-400 tabular-nums"
                        >
                          组合价目 {formatAmount(feeReferencePrice)}/米
                        </span>
                      )}
                    </span>
                    <span className="text-neutral-400">
                      来源：
                      {feeSource !== '' ? FEE_SOURCE_LABELS[feeSource] ?? feeSource : '—'}
                    </span>
                    {/* #7642：已配置的组合被本单改价 ⇒ 明说「价目不变」（钱的口径要看得见；
                        未配置行改价会记入价目，故这条提示只对「有价目参考价」的行显示） */}
                    {line.processingFeeOverride != null && feeReferencePrice != null && (
                      <span data-testid="fee-override-scope" className="text-neutral-500">
                        本单改价，组合价目不变
                      </span>
                    )}
                    {/* 缺选配信息（组合键为空）⇒ **不给**改单价入口：没有 key 可落地 */}
                    {feeIsUnpriced && !canOverrideFee && (
                      <span data-testid="fee-combination-no-composition" className="text-amber-600">
                        缺选配信息 ⇒ 这行还没匹配到加工费组合，无法就地改单价
                      </span>
                    )}
                    {/* 定价入口（与页面既有告警同一路径；已定价行无需它） */}
                    {feeIsUnpriced && (
                      <Link
                        href={PRICING_ENTRY}
                        className="text-primary-600 underline underline-offset-2 hover:text-primary-700"
                      >
                        去「企业基础设置 → 加工费组合」定价
                      </Link>
                    )}
                  </div>
                </div>
              )}

              {/* ===== **特殊选项**（2026-09-29 用户裁定逐字：「其他的这块选择区域归属到加工项
                  区域中，不要单独搞个折叠块了，用户打开加工项区域时一同打开，另外不要命名叫
                  『其他』，改成**特殊选项**」）=====
                  ① 19 项清单与选项名（join key）一字未动，写侧仍是 `onChangeCraft` 唯一通路；
                  ② 「部位备注」同批并入本步（它原本也住在 ③）；
                  ③ 原 ③ 的折叠壳与 `stepProps(3)` 一并删除 ⇒ 下单页只剩**两步**。
                  ⚠️ 勾选态传的是**生效集**（issue #7849）：系统推导并入的那几项也在这里显示为选中 ——
                  改前传人工勾选态 ⇒ 面板说「已并入特殊选项」而这里没选，同一件事两个真值。 */}
              <div className="mt-4 pt-4 border-t border-neutral-100">
                <div className="text-sm font-medium text-neutral-700 mb-2">特殊选项</div>
                {/* 🔴 issue #8007：布/纱派生键按**本行帘种**落库 ⇒ 选择器必须拿到 `curtainType` */}
                <OrderExtraOptions
                  value={effectiveOptions}
                  curtainType={curtainTypeOfBody(line.curtainBody)}
                  onChange={onChangeSpecialOptions}
                />
              </div>

              {/* **部位备注**（issue #5685）：商家自由文本 —— 写「**这个数字怎么来的**」
                  （算料依据的人工说明，例：`公式--48个折`）。客户现行加工单/扫码端就有这一行。
                  ① 上限 **200 字符**：由 `maxLength` **挡住**超长输入（服务端不截断 ⇒ 前端必须挡；
                     且**不静默截断**商家已写的内容），字数提示让商家看得见还剩多少；
                  ② 缺值（空 / 纯空白）⇒ `processingInfo` 里**不落键**（见 `buildLineProcessingInfo`），
                     下游读侧按「缺值不渲染」处理。 */}
              <div className="mt-4">
                <Label>部位备注</Label>
                <input
                  type="text"
                  data-testid="line-item-remark"
                  aria-label="部位备注"
                  maxLength={REMARK_MAX_LENGTH}
                  value={line.remark ?? ''}
                  onChange={(e) => onChangeRemark(e.target.value)}
                  placeholder="如：公式--48个折（写清这个数字怎么来的）"
                  className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
                <p data-testid="line-item-remark-counter" className="mt-1 text-xs text-neutral-400">
                  {(line.remark ?? '').length}/{REMARK_MAX_LENGTH}
                </p>
              </div>

              {/* **安装位置**（issue #7856）：这一扇窗装在那户人家的哪个空间（主卧 / 阳台 …）。
                  紧挨「部位备注」（同属「只上纸的附注」那一类，商家在同一处一口气写完）。
                  🔴 它不是「部位 / 帘种」（布帘 / 纱帘 = `curtainType`）—— 两个事实不许混。
                  ① 12 字上限由 `maxLength` 挡住（服务端超长 422）；
                  ② 选填：空 ⇒ `processingInfo` 里**不落键**，纸面该行不印；
                  ③ 词表 chips 只是录入捷径（自由输入照旧允许）。 */}
              <div className="mt-4">
                <Label>安装位置</Label>
                <input
                  type="text"
                  data-testid="line-item-install-room"
                  aria-label="安装位置"
                  maxLength={INSTALL_ROOM_MAX_LENGTH}
                  value={line.installRoom ?? ''}
                  onChange={(e) => onChangeInstallRoom(e.target.value)}
                  placeholder="主卧 / 阳台…（选填）"
                  className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
                <InstallRoomChips
                  value={line.installRoom ?? ''}
                  onPick={(room) => onChangeInstallRoom(room)}
                />
              </div>
            </WizardStep>

      </div>
    </div>
  )
}
