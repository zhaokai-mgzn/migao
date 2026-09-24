'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, ChevronDown, ChevronRight, Ruler, Search, Package, User, Receipt, Settings2, Plus, Trash2, UserPlus, Phone, MapPin, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { urgencyRequestFields } from '@/lib/order-urgency'
import { orderApi, productApi, customerApi, processingItemApi, productionApi, craftCalcApi, autoFeaturesApi, doorWidthPlanApi, feePreviewApi, type AutoFeaturesParams, type AutoFeaturesResult, type CraftCalcResult, type CraftCalcParams, type DoorWidthPlanParams, type DoorWidthPlanResult, type FeePreviewResult, type FeePreviewRow } from '@/lib/api'
import { resolveImageUrl, cn } from '@/lib/utils'
import { useOrderAmounts } from '@/hooks/useOrderAmounts'
import { Button, Card, Input, Modal, NumberInput } from '@/components/ui'
import OrderCraftFields from '@/components/orders/OrderCraftFields'
import OrderExtraOptions from '@/components/orders/OrderExtraOptions'
import {
  METERS_SOURCE_FORMULA,
  // 与配布边米数来源的 `METERS_SOURCE_MANUAL` 同值（都是「人工指定」）但**是另一个字段**
  // ⇒ 别名进来，避免两个来源的常量在同一文件里撞名（tsc 会直接报 duplicate identifier）。
  METERS_SOURCE_MANUAL as LINE_METERS_SOURCE_MANUAL,
  CRAFT_CALC_FORMULA_PLEAT,
  DEFAULT_CRAFT_NAME,
  JOIN_GAP_MAX_METERS,
  craftCalcErrorText,
  craftCalcParamsOf,
  craftCalcSignature,
  craftPlanCandidateLabel,
  craftPlanHasSplice,
  craftPlanSpliceText,
  defaultCraftCalcFormula,
  defaultCraftCalcTier,
  derivedJoinHeightOptionOf,
  derivedJoinSpliceItemOf,
  derivedSpliceOptionOf,
  derivedSpecialOptionsOf,
  effectiveCraftCalcFormula,
  effectiveJoinSourceNamesOf,
  effectiveSpecialOptionsOf,
  isAutoCalcUnavailable,
  joinGapOf,
  SPLICE_ITEM_NAME,
  type CraftPlanOverrides,
} from '@/lib/craft-calc-request'
import {
  COMPONENT_ROLE_EDGE,
  CURTAIN_BODY_CLOTH,
  CURTAIN_BODY_OPTIONS,
  CURTAIN_BODY_SHEER,
  CURTAIN_TYPE_SHEER,
  DEFAULT_CUTTING_MODE,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  STANDARD_FULLNESS,
  STYLE_MIXED,
  buildCraftSpec,
  buildEdgeLineCraftSpec,
  buildMainLineGroupKeys,
  createDefaultCraftSpec,
  curtainTypeOfBody,
  defaultIsShapedForBody,
  type CraftSpecInput,
  type CurtainBody,
} from '@/lib/order-craft-fields'
// 常用物流/快递（issue #4874）：词表唯一真值在 `lib/logistics.ts`，**不另造**一份候选
import { LOGISTICS_COMPANIES, LOGISTICS_TYPES } from '@/lib/logistics'
// D6 自动识别（issue #4526 · 设计 §5.1/§5.2）：倒幅 = cuttingMode 推导；**超高/超宽 = 企业阈值参数判定**
// 🔴 **issue #5130（2026-09-22）改判**：原注释写「超高/超宽 = 宽高 vs 门幅」—— 那是**当时**的口径，
//    现已**退役**（判定面与门幅彻底脱钩，不再按加工类型分流、超宽也不含褶倍）。
//    真值源 = `backend/ai-agent-service/app/tools/curtain_calc.py` 的 `detect_auto_features`（服务端）。
// ⚠️ #4592：`定高买宽`（= 正幅，缺省档）**不推导** —— 正幅不在加工项目录（V83）里，
//    推它会让默认订单的组合键永远匹配不到价（加工费恒 ¥0.00）
// ⚠️ 取自 **admin-web 专属**模块（不是三端同源的 `craft-display`，见该文件头）
// `AUTO_FEATURE_NAMES`（#4566）：下单页用它把目录里的**自动推导特征**滤出**手选**列表
// （它们在目录里必须存在 —— 商家配「加工费组合」要能选到；但手选控件必须没有它们，判据 8）
import {
  AUTO_FEATURE_NAMES,
  CUTTING_MODE_FIXED_HEIGHT,
  CUTTING_MODE_FIXED_WIDTH,
  effectiveCuttingModeOf,
  parseDoorWidth,
  type AutoFeature,
  type AutoFeatureName,
  type AutoFeatureNotice,
} from '@/lib/craft-auto-features'
// 门幅选择规则（issue #4877 → **issue #5043 包 2b 起由服务端给**）：**可行 / 不可行 + 哪个最省**
// —— 定高买宽取可行集里最小门幅、定宽买高取分幅最少；所有门幅都不满足 ⇒ 必然走接高。
// ⚠️ 前端本地实现（`@/lib/door-width-plan`）**已退场**：它与引擎 `resolve_fabric_plan` 不是同一条规则
// （实测：韩褶下门幅 3.2 时引擎 1 幅 / 前端 2 幅）⇒ 规则面一律走 `doorWidthPlanApi`。
// 费用明细的「加工 + 特殊选项」两半拆分（issue #4526 · 设计 §4.3 / 判据 5）——唯一实现
import { buildFeeDetailDisplay } from '@/lib/order-fee-display'
// #4371：加工项类型改为**店铺级目录**的 `ProcessingItem`（旧 `ProductProcessingItem` 已随解耦删除）
import type { Product, ProcessingItem, OrderItemFormData, Customer, CraftCalcConfig } from '@/types'

interface OrderProductSku {
  id: string
  productId?: string
  colorId: string
  colorName?: string
  doorWidth?: string
  price: number
  stock?: number
  skuCode?: string
}

interface ProductDetail extends Omit<Product, 'skus'> {
  skus?: OrderProductSku[]
  basePrice?: number
}

interface OrderLineItem {
  id: string
  /**
   * **商品组标识**（issue #4485）——同一块布（同一商品 / 颜色 / 门幅）下的多个**部位行**共用它。
   *
   * 为什么用「扁平数组 + 组标识」而不是嵌套结构：裁定 **R-a**「一行 `order_items` = 一个部位」
   * 是**落库**口径，提交与既有判据都按扁平数组走；分组**只是展示与编辑归属**
   * ⇒ 用组标识把「同一商品」标出来，渲染时分组，模型一字不改。
   */
  groupId: string
  product: ProductDetail | null
  productLoading: boolean
  selectedColorId: string | null
  selectedSku: OrderProductSku | null
  /**
   * **这个 SKU 是「规则自动选中」还是「客服手选」**（issue #4899）。
   *
   * 为什么必须有这一位：门幅规则的产品行为是「**不覆盖客服的手选**」——但**自动选中**若也算
   * 「已选」，规则就永远不再重算 ⇒ 尺寸 / 加工类型一变，页面会停在**旧门幅**上
   * （用户 2026-09-21 人工验证：「无法通过工艺&加工项选配反选最优的门幅 SKU」）。
   * ⇒ 自动选中的一律**可被规则改选**，手选的一律**不被覆盖**（只提示可换最优）。
   * ⚠️ 只活在**行状态**里，不进订单 payload。
   */
  skuAutoSelected: boolean
  /**
   * 售卖形态（issue #4493）——**商品组级**属性：同一块布按米卖还是做成帘。
   * 存在行上、由组级处理器在组内同步（与颜色 / 门幅同一机制）。
   */
  saleForm: SaleForm
  /**
   * **帘体**（issue #4521）—— 用户口径四类购买情况里的前三类：
   * `布帘` / `纱帘` —— **两者用料算法完全一致**（2026-09-21 用户裁定，见 `lib/craft-calc-request.ts`）。
   *
   * **组级**（与 `saleForm` 同一机制、组内同步）：一个商品组 = 一套帘 —— 改帘体不该只改一半
   * （主布行按公式算了料、纱帘行还留着）。
   */
  curtainBody: CurtainBody
  quantity: number
  unitPrice: number
  /**
   * 成品宽 / 高（米，**部位级**）—— issue #4420，用户 2026-09-19 裁定「宽高必填」。
   *
   * ⚠️ 归属层级：`position-instance-routing-model.md` §5.9.2 已裁定宽高是**部位级**
   * （一套「布 + 纱」的布帘与纱帘高度常不同，共用一行宽高必有一个部位的高度是错的）。
   * 本页一行 = 一个部位（裁定 R-a）⇒ 行级即部位级，语义一致。
   */
  width: number | null
  height: number | null
  processingItems: ProcessingItem[]
  selectedProcessing: Record<string, { selected: boolean; qty: number }>
  /**
   * 商家**不采纳**的系统推算特征名（issue #4657）—— 推算结果会**进加工费组合键**
   * ⇒ 推算错 = 价格错，商家必须能纠正。缺省（`undefined`）= 全部采纳。
   */
  rejectedAutoFeatures?: string[]
  /**
   * 商家**强制加**的自动识别特征名（issue #4657）—— 系统没推、但商家知道该算
   * （例：SKU 没录门幅 ⇒ 系统按默认 2.8 米兜底 ⇒ 本该超宽却漏判）。
   */
  manualAutoFeatures?: string[]
  /** 工艺规格录入（issue #4375 §4.2/§4.5）—— 未填的键不落库；三条默认档见 createDefaultCraftSpec */
  craft: CraftSpecInput
  // ── 「套窗」输入已移除（issue #4486，用户裁定「我感觉不需要」）──
  // 代价已如实登记：商家手工路径不再能跨行绑套窗 ⇒ 布 + 纱会算成 2 套窗 ⇒ 套级工序
  // （外帘打卷/装袋/发货）各实例化 2 次（计件工资双付，约 ¥3/套）。见 issue #4486。
  // ⚠️ **底层机制保留**：`lib/order-craft-fields.ts` 的 `resolveWindowCraftLineIds` /
  // `buildWindowGroupKey` 与消费端 `ProcessingOrderService` 一字未动（API / Agent 仍可写该键）；
  // 且 **`craftLineId` 仍用于配布边配对**（§4.8 主布行 + 配布边行），见 `buildLineProcessingInfo`。
  /**
   * 配布边米数（§4.8）；`null` = 未改过 ⇒ 跟随主布米数
   */
  edgeMeters: number | null
  /** 配布边单价；`null` = 未填 ⇒ 不生成配布边明细行（后端单价必须 > 0，不凭空造价） */
  edgeUnitPrice: number | null
  /**
   * **加工费就地改单价**（issue #4874，用户 2026-09-21：「订单中加工费组合**未配置**的情况下，
   * **允许更改该单价**」）—— 元/米，`null` = 没改过。
   *
   * 只在「`fee_source='unpriced'` **且组合键非空**」时可填；填了就：
   * ① 立刻以该价重发 `feePreview`（页面金额跟着变）② 随建单写进
   * `processingInfo.processingFeeOverride`（后端 #4872 采用后 `fee_source='manual'`，
   * 并在建单成功后同步进「加工费组合」配置）。
   *
   * ⚠️ 组合键为空（缺选配信息）⇒ **不给**改单价入口：没有 key 可同步，改了也无处落地。
   */
  processingFeeOverride: number | null
  /**
   * 商家**手改过**打开方式（issue #4493 的宽→开数联动）——落在**行状态**里，
   * 不放组件内 state（收起/展开重挂不丢）。手改过 ⇒ 改宽**不得覆盖**。
   */
  openCountTouched: boolean
  /**
   * 商家**手改过**是否定型（承接 #4489 的「手改留痕」纪律）—— 落在**行状态**里
   * （同 `openCountTouched`）。手改过 ⇒ 改帘体**不得覆盖**。
   *
   * ⚠️ issue #4566：定型已搬到**加工项** ⇒ 本标记跟踪的是「商家手动勾/取消过『定型』**加工项**」，
   * 而不是工艺规格里的某个字段（字段已随裁定退场）。
   */
  shapedItemTouched: boolean
  /**
   * 用料米数来源（真值源 §8：褶数/用料**必须带来源**，防多渠道不一致）—— issue #4434。
   * `公式计算` = 由算料引擎试算预填（宽/高/开数/拼次变化时自动重算）；
   * `人工指定` = 商家手改过 ⇒ **试算不得静默改回**（只有显式「恢复按公式计算」才切回）。
   */
  metersSource: string
  /**
   * 「人工指定」**生效时**的试算入参签名（issue #5202 · 根因 2）。
   *
   * 与**当前**签名不一致 ⇒ 说明商家手填的米数**没有跟随**这次改动（宽/高/门幅/工艺变了）。
   * 页面据此**显式告知**「已人工指定，未跟随」+ 一键恢复 —— **不得静默覆盖商家手填的数**
   * （真值源 §8：用料必须带来源），也**不得**让商家自己猜为什么数没变（用户第 8 点的病灶）。
   */
  metersManualSignature?: string
  /**
   * **人工加 / 改的推导项**（issue #5202 · 裁定 4/6）—— `undefined` = 没改过（由推导决定）。
   *
   * 一旦有值 ⇒ 随试算请求**显式下发**（契约 #5200 §四 R7：`auto=false`，**逐字采用**、不再自动改判）。
   * 与既有「手改留痕」纪律同族（`openCountTouched` / `shapedItemTouched` / `craft.cuttingMode` 的有无）。
   */
  planOverrides?: CraftPlanOverrides
  /**
   * 商家**不采纳**的「推导出的特殊选项」名（issue #5211）—— 记的是**选项名**（不是布尔位）：
   * 推导换成别的项（`拼2次` → `拼3次`）时，不对新的那一项继续生效（同 `rejectedAutoFeatures`）。
   *
   * 为什么不采纳必须有出口：这些项的下游是**工序插入 + 计件**（`拼2次` → 插 `拼2次-布`、计件
   * 0.8/1.2/1.6 元/幅；`接高` → 插 `接高-布`、计件 1.0 元/幅）⇒ 推导错 = 多插一道工序、多算工钱。
   */
  rejectedDerivedOptions?: string[]
  /**
   * 商家**手改过加工类型**（issue #5202 · 裁定 6）—— 落在**行状态**里（同 `openCountTouched` /
   * `shapedItemTouched`，收起/展开重挂不丢）。
   *
   * 为什么必须有一位：`createDefaultCraftSpec()` 也写 `craft.cuttingMode = 定高买宽`（默认档），
   * 只按「有值」判「人工覆盖」⇒ 默认档会**恒顶掉**服务端推导（三项输入收敛当场失效），
   * 而且 `data.plan.auto` 会永远显示「人工指定」（假话）。点过（含点「未指定」）⇒ 人工锁定，
   * 此后**不再被推导覆盖**。
   */
  cuttingModeTouched: boolean
  /** 最近一次算料试算结果（含**后端产出**的公式串）—— `null` = 还没算过 */
  calc: CraftCalcResult | null
  /** 试算失败原因（行内显式提示；**不退回任何估算值**） */
  calcError: string | null
  /**
   * 最近一次**自动特征判定**结果（issue #4976 包 2b）—— 判定来自**服务端**（用户裁定 B）。
   * `undefined` / `null` = **还没判**（提交闸门会拦，见 `autoFeaturesBlockReason`）。
   */
  autoFeatures?: AutoFeaturesResult | null
  /** 判定失败原因（行内显式提示；**不放行提交** —— 组合键少一项 = 钱会错） */
  autoFeaturesError?: string | null
  /**
   * 最近一次**门幅规则**结果（issue #5043 包 2b）—— 规则来自**服务端**（前端 `door-width-plan.ts` 退场）。
   * `undefined` / `null` = **还没算** ⇒ {@link cuttingModeOf} 返回 `undefined`（**不猜朝向**）。
   */
  doorWidthPlan?: DoorWidthPlanResult | null
  /** 规则失败原因（行内显式提示；**不回落任何本地规则**） */
  doorWidthPlanError?: string | null
}

/** 开数 → 中文标签（复用 lib 的单一映射，不另写一份） */
const OPEN_COUNT_LABEL: Record<number, string> = Object.fromEntries(
  OPEN_COUNT_OPTIONS.map((o) => [o.value, o.label])
)

function formatAmount(amount: number): string {
  return `¥${(amount || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function genId(): string {
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
function deriveProcessingQty(fabricMeters: number): number {
  return Math.max(1, fabricMeters)
}

/** 试算防抖（issue #4434）：连打宽高时只在停手后发一次请求 */
const CRAFT_CALC_DEBOUNCE_MS = 400

/** 加工费计价预览防抖（issue #4450） */
const FEE_PREVIEW_DEBOUNCE_MS = 300

/**
 * **售卖形态**（issue #4493，用户裁定）：同一块布既能**按米卖（布料）**、也能**做成帘（成品帘）**。
 *
 * - `布料` ⇒ **无加工**：不出现宽高 / 工艺规格 / 部位行 / 加工项 / 加工费，也不生成加工单；
 * - `成品帘` ⇒ 上述全有（宽高**必填**）。
 *
 * 默认 `成品帘`：与今天的行为一致（所有字段照旧出现）⇒ 不静默改变任何现有商家的下单形态。
 */
const SALE_FORM_FABRIC = '布料'
const SALE_FORM_FINISHED = '成品帘'
type SaleForm = typeof SALE_FORM_FABRIC | typeof SALE_FORM_FINISHED

/**
 * 「加工费组合」定价面的入口（issue #4590）—— **与后端同源同值**：后端
 * `ProcessingFeeCalculator.PRICING_ENTRY` 给未定价组合拼的 hint 里就是这条路径。
 *
 * 它落点 = 合并页 `/production/processing?tab=fees` 的**第二个 tab「加工费组合」**
 * （`production/processing-fees/page.tsx` 是这条旧路径的重定向入口，见该文件头）
 * ⇒ 就是商家真正能定价的那一屏。⚠️ 前端**不另写**第三个路径：
 * `orders-new-fee-preview.test.tsx` 直接读后端源码比对（同源判据，改一边必红）。
 */
const PRICING_ENTRY = '/production/processing-fees'

/**
 * 未定价行**没有可匹配的组合**时的展示名（issue #4590 的边界）：服务端 `composition` 为空 =
 * 本行没选配任何加工项 ⇒ **缺选配信息**，与「组合未定价」是两回事，不许混同、也不许显示空组合名。
 */
const UNPRICED_NO_COMPOSITION = '没有可匹配的组合（缺选配信息）'

/**
 * 未定价行的**组合展示名**（issue #4590）：`items.join(' + ')` —— 与「加工费组合」页
 * **同一写法**（`production/processing/page.tsx`：`(row.items ?? []).join(' + ') || row.composition_key`），
 * 保证商家在告警里读到的名字与定价页上的组合名逐字一致（否则还是对不上号）。
 *
 * `items` 是服务端**展示用**的归一化加工项名（与 `composition` 同源，键名冻结）⇒ 不自己拆键。
 */
function unpricedCombinationLabel(
  detail: { composition?: unknown; items?: unknown } | undefined
): string {
  const items = Array.isArray(detail?.items)
    ? detail.items.filter((v): v is string => typeof v === 'string' && v.trim() !== '')
    : []
  if (items.length > 0) return items.join(' + ')
  // `items` 缺席（旧服务端）⇒ 回落到归一化组合键（与定价页的兜底同口径），再空才算「缺选配信息」
  const composition = typeof detail?.composition === 'string' ? detail.composition.trim() : ''
  return composition !== '' ? composition : UNPRICED_NO_COMPOSITION
}

/**
 * `fee_source` 三态的可读**来源**（issue #4874「加工费组合」明细块的「来源」列）——
 * 值域与后端 `ProcessingFeeCalculator.FEE_SOURCE_*` **逐字一致**
 * （`matched` 组合价目 / `manual` 手动改价 / `unpriced` 未定价）；未知值**原样显示**（不吞、不猜）。
 */
const FEE_SOURCE_LABELS: Record<string, string> = {
  matched: '组合价目',
  manual: '手动改价',
  unpriced: '未定价',
}

/**
 * 「定型」加工项名（**V83 目录逐字**）—— 它的勾选态就是 `isShaped` 的真值来源（issue #4566）。
 *
 * 用户 2026-09-19 裁定：「工艺规格中的**工艺，定型**，对花我觉得**直接通过加工项来勾选**，
 * 其他保留」⇒ 定型是目录里的**手选特征**项（`unit_price=0`，价在加工费组合上）。
 */
const SHAPED_ITEM_NAME = '定型'

/**
 * 该行的**手选加工项**清单 —— 滤掉**自动推导特征**（`超高`/`超宽`/`倒幅`）。
 *
 * 为什么目录里有它们却要滤掉：商家配「加工费组合」时必须能选到它们
 * （组合名就是 `韩褶+超高+定型` 这种形态），但**下单页**的勾选控件不能有
 * —— 它们是**推导**出来的（判据 8：自动识别特征出现手选项 ⇒ 红）。
 * 单一真值 = `craft-auto-features.ts` 的 `AUTO_FEATURE_NAMES`（此处不抄第二份名字数组）。
 */
function handPickableProcessingItems(items: ProcessingItem[]): ProcessingItem[] {
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
function craftFromItems(line: OrderLineItem): string | undefined {
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
function isShapedFromItems(line: OrderLineItem): boolean | undefined {
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
function derivedCraftSpec(line: OrderLineItem, calcConfig: CraftCalcConfig | null): CraftSpecInput {
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
function cuttingModeOf(line: OrderLineItem): string | undefined {
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
function withShapedDefault(
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
function pickAutoSkuForColor(
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
function autoFeaturesOf(line: OrderLineItem): AutoFeature[] {
  const rows = line.autoFeatures?.auto_features ?? []
  return rows
    .filter((f) => (AUTO_FEATURE_NAMES as readonly string[]).includes(f.name))
    .map((f) => ({ name: f.name as AutoFeatureName, source: '推算' as const, reason: f.reason }))
}

/** 自动特征判定的**入参**（`null` = 宽高没填齐 ⇒ 不发请求，提交校验本来也拦） */
function autoFeatureParamsOf(
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
function autoFeatureParamsSignature(params: AutoFeaturesParams | null): string {
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
function doorWidthParamsOf(line: OrderLineItem): DoorWidthPlanParams | null {
  const width = Number(line.width)
  const height = Number(line.height)
  if (!Number.isFinite(width) || width <= 0) return null
  if (!Number.isFinite(height) || height <= 0) return null
  const doorWidths = (line.product?.skus ?? [])
    .filter((sku) => sku.colorId === line.selectedColorId)
    .map((sku) => parseDoorWidth(sku.doorWidth))
    .filter((g): g is number => g !== null)
  if (doorWidths.length === 0) return null
  const params: DoorWidthPlanParams = {
    width,
    height,
    door_widths: doorWidths,
    open_count: line.craft.openCount,
    fullness: STANDARD_FULLNESS,
  }
  if (line.craft.cuttingMode) params.cutting_mode = line.craft.cuttingMode
  const selected = parseDoorWidth(line.selectedSku?.doorWidth)
  if (selected !== null) params.selected_door_width = selected
  return params
}

/** 规则入参签名：**只含入参**（结果写回行状态 ⇒ 用它当依赖会自激成请求风暴） */
function doorWidthParamsSignature(params: DoorWidthPlanParams | null): string {
  if (params === null) return ''
  return [
    params.width,
    params.height,
    params.door_widths.join(','),
    params.cutting_mode ?? '',
    params.selected_door_width ?? '',
    params.open_count ?? '',
    params.fullness ?? '',
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
function autoFeaturesBlockReason(
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
function autoFeatureNoticesOf(line: OrderLineItem): AutoFeatureNotice[] {
  // 🔴 issue #5036：提示改由**服务端**给（用户 2026-09-21 裁定「统一迁移到服务端；未来 agent 也需要」）
  // —— 引擎读的是**该租户配置**的 `hem_margin`（宽方向余量已按 issue #5030 退场）⇒ 与判定**同源**。
  // 迁移前本函数在前端本地算、读**模块常量副本**（0.3）⇒ 租户改过 `hem_margin` 后这里会显示
  // **错的数**，且「几何矛盾」的**判断本身**也会错 —— 那正是本单要消灭的脱钩。
  // 本页只**展示**：`kind` / `reason` 一律照服务端返回，**不编**口径（`#4662` 的裁定 C 不变）。
  return line.autoFeatures?.notices ?? []
}

/**
 * **系统识别**块里的一行（issue #4657）：系统推算的（含被**不采纳**的，留痕要看得见）
 * 或商家**强制加**的。
 *
 * ⚠️ 不复用 lib 的 `AutoFeature`：那里 `source` 只可能是 `推算`（推导产生）；
 * 本行多了 `手动加`（商家强制加、系统没推）这一档 —— 它只在**页面侧**有意义。
 */
interface SystemAutoFeatureRow {
  /**
   * 特征 / 加工项名 —— **不再是** `AutoFeatureName`（issue #5230）：这一块除了服务端推算的
   * 超高 / 超宽 / 倒幅与商家强制加的项，还要承载**派生加工项**「拼接」
   * （它不在 `AUTO_FEATURE_NAMES` 里 —— 那一份清单是**手选控件要滤掉**的名字，
   * 而拼接**必须留在手选列表**里：裁定 4「接高、拼接也允许人工加」）。
   */
  name: string
  source: '推算' | '手动加'
  reason: string
  /** 系统推算过、但被商家**不采纳** ⇒ **不在**生效值里（只作留痕展示） */
  rejected: boolean
}

/** 商家对系统推算的**裁决**（issue #4657）：`adopt` 恢复系统推算 · `reject` 不采纳 · `add` 强制加 */
type AutoFeatureDecision = 'adopt' | 'reject' | 'add'

/** 强制加那一行的依据文案（系统没推算依据可引用 ⇒ 照实说明「未推算」，不编一个理由） */
const MANUAL_ADD_REASON = '系统未推算，商家手动加'

/**
 * 该行**推导项裁决 / 落库 / 拼接派生**的**同一份**入参（issue #5230 收敛）——
 * 面板显示、`processingInfo.specialOptions`、**拼接派生**三处都经它 ⇒ 不可能各说各话。
 *
 * ⚠️ `joinWidthOverride`（人工加接宽）也要在场：它**不进** `specialOptions`（接宽没有选项出口，
 * 用户 2026-09-23 裁定「移除接宽逻辑」），但它是**拼接派生**的判据之一 ——
 * 漏一处就会出现「商家人工加了接宽、拼接却没进组合键」。
 */
function derivedOptionInputOf(line: OrderLineItem) {
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
function isHandPickedProcessingItem(line: OrderLineItem, name: string): boolean {
  return line.processingItems.some(
    (pi) => pi.name === name && line.selectedProcessing[pi.id]?.selected === true
  )
}

/**
 * 派生加工项「拼接」那一行的**依据文案**（issue #5230）—— 说清是**接高还是接宽**带来的接缝，
 * 并照实写明「拼N次不派生」（商家核对判定时要看得见边界）。
 */
function joinSpliceReasonOf(line: OrderLineItem): string {
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
function autoFeatureRowsOf(line: OrderLineItem): SystemAutoFeatureRow[] {
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
function effectiveAutoFeaturesOf(line: OrderLineItem): SystemAutoFeatureRow[] {
  return autoFeatureRowsOf(line).filter((row) => !row.rejected)
}

/** 该行已勾选的加工项明细（提交 payload 与加工费预览**共用**这一份构造） */
function processingDetailsOf(line: OrderLineItem): Array<Record<string, unknown>> {
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
function buildLineProcessingInfo(
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

  if (
    processingDetails.length === 0 &&
    !sku &&
    !colorName &&
    Object.keys(mainSpec).length === 0 &&
    !isFabric
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

  // 加工费米数（裁定 R-b：= 该套窗**主布行**米数）+ 算料输出（#4273：输入与输出都要落）。
  // ⚠️ `ProcessingFeeCalculator.METER_KEYS = (processingMeters, fabric_meters)` ——
  //    一个都不写 ⇒ 服务端判「缺加工费米数」⇒ 加工费按 0 计（#4450 实证的第二处缺口）。
  const meters = Number(line.quantity)
  if (Number.isFinite(meters) && meters > 0) info.processingMeters = meters
  const calcMeters = Number(line.calc?.fabric_meters)
  if (Number.isFinite(calcMeters) && calcMeters > 0) info.fabric_meters = calcMeters
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
  if (Number.isFinite(override) && override > 0) info.processingFeeOverride = override

  return info
}

/** 加工费计价失败 → 可读提示（**不给估算值**：未确认金额前不得提交） */
function feePreviewErrorText(error: unknown): string {
  const anyErr = error as {
    response?: { data?: { message?: string; error?: { message?: string } } }
    message?: string
  }
  const detail =
    anyErr?.response?.data?.error?.message || anyErr?.response?.data?.message || anyErr?.message
  return detail ? `加工费计价失败：${detail}` : '加工费计价失败，请稍后重试'
}

/**
 * 面料米数变化 ⇒ 已选中加工项的 `per_meter` 数量联动（issue #3005 回滚 #2986）。
 *
 * 抽成纯函数：手工改数量（`handleLineQtyChange`）与算料试算写回（issue #4434）**必须走同一条**，
 * 否则两条路径对「加工项数量」的口径会分叉。
 */
function requantifyProcessing(
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
function heightFromDoorWidth(doorWidth: string | undefined): number | null {
  if (!doorWidth) return null
  const m = String(doorWidth).match(/(\d+(?:\.\d+)?)/)
  if (!m) return null
  const n = Number(m[1])
  return Number.isFinite(n) && n > 0 ? n : null
}

/**
 * 宽 → 打开方式（真值源 §10 的启发式，**今天未落码**）：
 * 「≤2.2m 默认单开、>2.2m 默认双开、大窗（>5m）四开」。
 *
 * ⚠️ 只在商家**没手改过**打开方式时联动（`openCountTouched` 落在**行状态**里，
 * 不放组件内 state —— 收起/展开不会丢，同 #4489 的教训）。
 */
function deriveOpenCount(width: number): number {
  if (width > 5) return 4
  if (width > 2.2) return 2
  return 1
}

/**
 * **人工加拼次**的取值（issue #5202 · 裁定 4）：`由推导决定` + `0~3`。
 *
 * 值域 = 契约 #5200 §四 的 `splice_times`（人工覆盖 0~3）；`≥ 4` **不得发明「拼4次」**（R5），
 * 那属于「需人工处理」，不是下单页能填的一档。
 */
const SPLICE_OVERRIDE_OPTIONS: Array<{ label: string; value: number | undefined }> = [
  { label: '由推导决定', value: undefined },
  { label: '不拼接', value: 0 },
  { label: '拼1次', value: 1 },
  { label: '拼2次', value: 2 },
  { label: '拼3次', value: 3 },
]

/**
 * 人工加 / 改推导项的状态合并（issue #5202）：`null` / `undefined` = **清掉该项**（回到由推导决定）；
 * 数字 ⇒ 原样留在状态里（**越界的也要留** —— 留了页面才报得出「超限」，请求面由 `joinGapOf` 拒发）。
 */
function mergePlanOverrides(
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
function positiveOrNull(value: number | null): number | null {
  return value !== null && Number.isFinite(value) && value > 0 ? value : null
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

function createEmptyLineItem(groupId: string = genId()): OrderLineItem {
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
    craft: createDefaultCraftSpec(),
    edgeMeters: null,
    edgeUnitPrice: null,
    processingFeeOverride: null,
    openCountTouched: false,
    shapedItemTouched: false,
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
function calcInputOf(line: OrderLineItem, calcConfig: CraftCalcConfig | null) {
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
function edgeUnitPriceOf(line: OrderLineItem): number | null {
  if (line.craft.style !== STYLE_MIXED) return null
  return line.edgeUnitPrice != null && line.edgeUnitPrice > 0 ? line.edgeUnitPrice : null
}

/** 配布边米数（§4.8 已裁定口径）：默认 = 主布米数（= 该行数量），可编辑 */
function edgeMetersOf(line: OrderLineItem): number {
  return line.edgeMeters ?? (Number(line.quantity) || 0)
}

export default function NewOrderPage() {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)

  // ===== 行项数组 =====
  const [lineItems, setLineItems] = useState<OrderLineItem[]>(() => [createEmptyLineItem()])

  // ===== 商品搜索弹窗 =====
  const [productModalOpen, setProductModalOpen] = useState(false)
  const [activeLineId, setActiveLineId] = useState<string | null>(null)
  const [productKeyword, setProductKeyword] = useState('')
  const [productResults, setProductResults] = useState<Product[]>([])
  const [productSearchLoading, setProductSearchLoading] = useState(false)

  // ===== 收货信息 =====
  const [customerName, setCustomerName] = useState('')
  const [customerPhone, setCustomerPhone] = useState('')
  const [customerAddress, setCustomerAddress] = useState('')
  const [remark, setRemark] = useState('')

  // ===== 客户选择弹窗（#3102：选已有客户快捷回填收货信息，保留手动兜底）=====
  const [customerModalOpen, setCustomerModalOpen] = useState(false)
  const [customerKeyword, setCustomerKeyword] = useState('')
  const [customerResults, setCustomerResults] = useState<Customer[]>([])
  const [customerSearchLoading, setCustomerSearchLoading] = useState(false)
  /**
   * **常用物流/快递**与**常用物流公司**（issue #4874，用户 2026-09-21：「新增订单时**收货信息**中
   * 缺少用户的常用物流/快递以及常用公司，选择客户后要默认带出」）—— 两个**可编辑**控件，
   * 选客户时按客户档案带出（`Customer.defaultLogisticsType` / `defaultLogisticsCompany`）。
   *
   * 缺省 `''` = **未指定**：**不编造**默认值（客户没录过常用物流时渲染成「快递」看起来像已配置），
   * 提交时缺值不写（`logisticsType` / `logisticsCompany` 是顶层可选字段）。
   */
  const [logisticsType, setLogisticsType] = useState('')
  const [logisticsCompany, setLogisticsCompany] = useState('')

  /**
   * **加急**与**要求到货日**（issue #5177，做在**订单**上 —— 不是售后页）。
   *
   * 🔴 缺省不变：`isUrgent` 缺省 `false`（= **不勾**）、`requiredDeliveryDate` 缺省 `''`（= **未指定**）
   * ⇒ 提交时**这两个键都不出现在请求体里**（后端库列 `NOT NULL DEFAULT FALSE` / `NULL`）。
   * **不得默认勾上加急** —— 勾了就是替商家编造一个「插队」事实。
   * 与售后工单的 `priority` **零联动**（不 import、不读写任何售后字段）。
   */
  const [isUrgent, setIsUrgent] = useState(false)
  const [requiredDeliveryDate, setRequiredDeliveryDate] = useState('')

  // 表单错误
  const [errors, setErrors] = useState<Record<string, string>>({})

  // ===== 加工项目录（店铺级，独立于商品）=====
  // issue #4371：加工项与商品解耦 —— 目录只加载一次，商品选择不再过滤/触发加工项请求
  const [processingCatalog, setProcessingCatalog] = useState<ProcessingItem[]>([])
  const [processingCatalogLoading, setProcessingCatalogLoading] = useState(false)

  /**
   * **算料配置**（issue #4874）—— 与「工艺配置 → 算料配置」**同源**：公式名与档位一律从
   * `GET /api/admin/production/craft-calc-config` 读，**前端不写死第二份**。
   *
   * ⚠️ 加载失败**不阻断录入**：页面对 `null` 的处理 = 公式走 `defaultCraftCalcFormula(null)`
   * （`pleat`）+ 档位走 `defaultCraftCalcTier(null)`（`standard`），并在界面上**显式提示**
   * 「配置未加载」——静默按缺省走 = 商家以为按自己配的口径算（算错钱且无人知道）。
   */
  const [calcConfig, setCalcConfig] = useState<CraftCalcConfig | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setProcessingCatalogLoading(true)
      try {
        const res = await processingItemApi.getProcessingItems({ page: 1, size: 100 })
        if (!cancelled) setProcessingCatalog(res.data?.data?.items || [])
      } catch (e) {
        if (!cancelled) setProcessingCatalog([])
      } finally {
        if (!cancelled) setProcessingCatalogLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  // 目录到达后同步到各行项（行项可能在目录加载完成前就已选好商品）
  useEffect(() => {
    if (processingCatalogLoading) return
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.processingItems === processingCatalog) return it
        const next: OrderLineItem = { ...it, processingItems: processingCatalog }
        // 目录到达 ⇒ 按帘体补「定型」的**默认勾选**（issue #4566；商家手动改过的不覆盖）
        return { ...next, selectedProcessing: withShapedDefault(next) }
      })
    )
  }, [processingCatalog, processingCatalogLoading])

  /**
   * **算料配置**加载（issue #4874）—— 只加载一次，失败**只提示不阻断**（`calcConfig` 保持 `null`
   * ⇒ 页面按缺省口径走 + 显式提示）。旧请求返回时不再写状态（`cancelled`）⇒ 不会用过期配置覆盖。
   */
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const res = await productionApi.getCraftCalcConfig()
        if (cancelled) return
        setCalcConfig(res.data?.data?.config ?? null)
      } catch (e) {
        // 读不到 ⇒ 保持 `null`（页面按缺省口径走 + 「工艺规格」里显式提示配置未加载）
        if (!cancelled) setCalcConfig(null)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  // ===== 行项更新工具 =====
  const updateLineItem = useCallback(
    (
      lineId: string,
      patch: Partial<OrderLineItem> | ((line: OrderLineItem) => Partial<OrderLineItem>)
    ) => {
      setLineItems((prev) =>
        prev.map((it) =>
          it.id === lineId ? { ...it, ...(typeof patch === 'function' ? patch(it) : patch) } : it
        )
      )
    },
    []
  )

  /**
   * 自动识别特征的**裁决**（issue #4657）—— 生效值 = `推算 ∪ 强制加 − 不采纳`。
   *
   * - `reject` = **不采纳**（推算错会直接算错加工费，商家必须能纠正）；
   * - `add` = **强制加**（系统漏判，如 SKU 没录门幅 ⇒ 按默认 2.8 兜底 ⇒ 本该超宽却没推）；
   * - `adopt` = **恢复系统推算**（同时清掉强制加 —— 两个来源不会同时留下同一个名字）。
   *
   * 裁决随**行状态**走，落库的是**生效值**（`processingDetailsOf`）⇒ 日后推算判据修正
   * **不影响**已下的单（快照，零迁移：`processingInfo` JSON 已能承载）。
   */
  const decideAutoFeature = useCallback(
    (lineId: string, name: string, decision: AutoFeatureDecision) => {
      updateLineItem(lineId, (it) => {
        const without = (list: string[] | undefined) => (list ?? []).filter((n) => n !== name)
        if (decision === 'reject') {
          return {
            rejectedAutoFeatures: [...new Set([...(it.rejectedAutoFeatures ?? []), name])],
            manualAutoFeatures: without(it.manualAutoFeatures),
          }
        }
        if (decision === 'add') {
          return {
            rejectedAutoFeatures: without(it.rejectedAutoFeatures),
            manualAutoFeatures: [...new Set([...(it.manualAutoFeatures ?? []), name])],
          }
        }
        return {
          rejectedAutoFeatures: without(it.rejectedAutoFeatures),
          manualAutoFeatures: without(it.manualAutoFeatures),
        }
      })
    },
    [updateLineItem]
  )

  /**
   * 「推导出的特殊选项」的**裁决**（issue #5211：拼N次 / 接高）—— 与 {@link decideAutoFeature}
   * 同族纪律：这些项会进 `processingInfo.specialOptions`（**插工序 + 计件**）⇒ 推导错 = 多插一道
   * 工序、多算工钱 ⇒ 商家必须能**不采纳** / **恢复采纳**。
   *
   * 按**选项名**留痕（不是布尔位）：日后推导换成别的项时，对新的那一项不作废
   * （同 `rejectedAutoFeatures` 的按名裁决）。
   */
  const decideDerivedOption = useCallback(
    (lineId: string, name: string, decision: 'adopt' | 'reject') => {
      updateLineItem(lineId, (it) => {
        const without = (it.rejectedDerivedOptions ?? []).filter((n) => n !== name)
        return {
          rejectedDerivedOptions:
            decision === 'adopt' ? without : [...new Set([...without, name])],
        }
      })
    },
    [updateLineItem]
  )

  const addLineItem = () => {
    setLineItems((prev) => [...prev, createEmptyLineItem()])
  }

  /**
   * **帘体**（**组级**，issue #4521）：一个商品组 = 一套帘 ⇒ 组内同步。
   *
   * 两条口径：
   * 1. **是否定型默认跟着帘体走**（真值源 §10 布帘是 / 纱帘否）—— 但**只在商家没手改过时**
   *    （`shapedItemTouched` 落在行状态里，同 `openCountTouched` 的纪律：手改过的值只能显式改回）。
   *    ⚠️ issue #4566：它现在写的是「定型」**加工项**的勾选态（`withShapedDefault`），
   *    不再是工艺规格里的字段（字段已随裁定退场）；
   * 2. **用料来源**：两种帘体**同一条**算料链路 ⇒ 一律回到「公式计算」
   *    （`人工指定` 只能由商家手改数量进入，见 `handleLineQtyChange`）。
   *
   * ⚠️ **2026-09-21 用户裁定（口径反转）**：原第 3 条边界「切到纱帘就清掉算料结果/错误
   * （纱帘不算料）」**已退场** —— 纱帘不再是不算料的特例 ⇒ 不得因为切帘体而丢弃/跳过算料结果。
   */
  const handleCurtainBodyChange = (groupId: string, body: CurtainBody) => {
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.groupId !== groupId) return it
        const next: OrderLineItem = {
          ...it,
          curtainBody: body,
          // 纱帘与布帘**同一算法**（2026-09-21 裁定）⇒ 切帘体后一律回到「公式计算」
          metersSource: METERS_SOURCE_FORMULA,
        }
        // 定型默认随帘体（#4566）：写「定型」加工项的勾选态，商家手改过则不覆盖
        // （⚠️ 与用料算法无关，不动）
        next.selectedProcessing = withShapedDefault(next)
        return next
      })
    )
  }

  /**
   * 组内同步（issue #4485）：把 patch 写到同 `groupId` 的**所有**行 ——
   * 商品 / 颜色 / 门幅·售卖方式 / 售卖形态都是**一组一份**的属性（部位共用）。
   */
  const patchGroup = useCallback((groupId: string, patch: Partial<OrderLineItem>) => {
    setLineItems((prev) => prev.map((it) => (it.groupId === groupId ? { ...it, ...patch } : it)))
  }, [])

  /**
   * 颜色（**组级**，issue #4485）：同一块布的颜色 ⇒ 组内所有部位行同步。
   * 顺带按门幅给「高」填默认值（用户 2026-09-19 裁定，可改）。
   */
  const handleSelectColorForGroup = (groupId: string, colorId: string) => {
    const sample = lineItems.find((l) => l.groupId === groupId)
    const skusOfColor = (sample?.product?.skus || []).filter((s) => s.colorId === colorId)
    // issue #4877 裁定 C：多门幅时按**门幅规则**选默认（可行集最小门幅 / 定宽买高分幅最少）
    const autoSku = sample ? pickAutoSkuForColor(sample, skusOfColor) : null
    patchGroup(groupId, {
      selectedColorId: colorId,
      selectedSku: autoSku,
      skuAutoSelected: Boolean(autoSku),
      ...(autoSku ? { unitPrice: Number(autoSku.price) } : {}),
    })
  }

  /** 门幅 / 售卖方式（**组级**）：同上；并把「高」默认成门幅（仅定高买宽，可改） */
  const handleSelectSkuForGroup = (
    groupId: string,
    sku: OrderProductSku,
    source: 'auto' | 'manual' = 'manual'
  ) => {
    const sample = lineItems.find((l) => l.groupId === groupId)
    const isFixedHeight = (sample?.craft.cuttingMode ?? DEFAULT_CUTTING_MODE) === DEFAULT_CUTTING_MODE
    const defaultHeight = isFixedHeight ? heightFromDoorWidth(sku.doorWidth) : null
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.groupId !== groupId) return it
        const next: OrderLineItem = {
          ...it,
          selectedSku: sku,
          unitPrice: Number(sku.price) || 0,
          skuAutoSelected: source === 'auto',
        }
        // 只在「还没填高」时补默认值 —— 商家填过的值不覆盖（同「手改留痕」纪律）
        if (defaultHeight !== null && it.height === null) next.height = defaultHeight
        return next
      })
    )
  }

  /**
   * 尺寸 / 加工类型变化后：该组**还没选门幅** ⇒ 按**门幅规则**补一个默认（issue #4877 裁定 C）。
   *
   * ⚠️ 只在 `selectedSku` **为空**时补 —— 客服手选过就**不覆盖**（同「手改留痕」纪律）；
   * 规则判不了（缺尺寸 / 门幅未维护 / 多个 SKU 同门幅）⇒ **什么都不做**（不猜）。
   */
  const autoSelectSkuByRuleForGroup = (groupId: string, patch: Partial<OrderLineItem>) => {
    const sample = lineItems.find((l) => l.groupId === groupId)
    if (!sample) return
    // **客服手选过 ⇒ 不覆盖**（只提示可换最优，用户裁定）；**规则自己选的 ⇒ 要能重算**（issue #4899）
    if (sample.selectedSku && !sample.skuAutoSelected) return
    const next = { ...sample, ...patch }
    const skusOfColor = (next.product?.skus ?? []).filter((s) => s.colorId === next.selectedColorId)
    const sku = pickAutoSkuForColor(next, skusOfColor)
    // 规则解没变 ⇒ 不动作（避免无谓 setState 与单价抖动）
    if (sku && sku.id !== sample.selectedSku?.id) handleSelectSkuForGroup(groupId, sku, 'auto')
  }

  /**
   * 售卖形态（**组级**，issue #4493）：布料 ⇒ 组内**只保留一行**（布料没有部位），
   * 并清掉工艺规格 / 加工项 / 宽高（布料单无加工）；成品帘 ⇒ 组内所有行标回成品帘。
   */
  const handleSaleFormChange = (groupId: string, form: SaleForm) => {
    setLineItems((prev) => {
      const groupLines = prev.filter((l) => l.groupId === groupId)
      if (groupLines.length === 0) return prev
      if (form !== SALE_FORM_FABRIC) {
        return prev.map((l) => (l.groupId === groupId ? { ...l, saleForm: form } : l))
      }
      const at = prev.findIndex((l) => l.groupId === groupId)
      const kept: OrderLineItem = {
        ...groupLines[0],
        saleForm: form,
        craft: {},
        selectedProcessing: {},
        width: null,
        height: null,
        calc: null,
        calcError: null,
        metersSource: METERS_SOURCE_FORMULA,
        // 布料单没有帘体（issue #4521）：切回成品帘时从「布帘」重新开始。
        // ⚠️ issue #4874：`布帘+纱帘` 档已删除 ⇒ 不再需要清「纱帘米数 / 纱帘单价」
        curtainBody: CURTAIN_BODY_CLOTH,
        processingFeeOverride: null,
      }
      const next = prev.filter((l) => l.groupId !== groupId)
      next.splice(at, 0, kept)
      return next
    })
  }

  /** 删除整个商品组（含其下所有部位行）；至少保留一组 */
  const removeGroup = (groupId: string) => {
    setLineItems((prev) => {
      const next = prev.filter((l) => l.groupId !== groupId)
      return next.length === 0 ? prev : next
    })
    setErrors({})
  }

  // ===== 商品搜索 =====
  const searchProducts = useCallback(async () => {
    setProductSearchLoading(true)
    try {
      const res = await productApi.getProducts({
        keyword: productKeyword.trim() || undefined,
        page: 1,
        size: 30,
      })
      setProductResults(res.data?.data?.items || [])
    } catch (e) {
      toastRequestError(e, '搜索商品失败')
    } finally {
      setProductSearchLoading(false)
    }
  }, [productKeyword])

  useEffect(() => {
    if (productModalOpen) {
      searchProducts()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productModalOpen])

  const openProductModalFor = (lineId: string) => {
    setActiveLineId(lineId)
    setProductModalOpen(true)
  }

  // ===== 客户搜索（#3102）=====
  const searchCustomers = useCallback(async () => {
    setCustomerSearchLoading(true)
    try {
      const res = await customerApi.getCustomers({
        keyword: customerKeyword.trim() || undefined,
        page: 1,
        size: 30,
      })
      setCustomerResults(res.data?.data?.items || [])
    } catch (e) {
      toastRequestError(e, '搜索客户失败')
    } finally {
      setCustomerSearchLoading(false)
    }
  }, [customerKeyword])

  useEffect(() => {
    if (customerModalOpen) {
      searchCustomers()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerModalOpen])

  // 选中客户 → 自动回填收货信息（仍可手动修改）
  // 取值优先级（issue #4419）：客户档案的**默认收货地址**优先（客户管理「收货信息」卡片维护的
  // defaultReceiverName/Phone/Address）；档案没录收货信息时才回退到 #3102 的旧口径
  // （姓名=昵称 / 手机号=phone / 地址=省市区前缀）。
  const handlePickCustomer = (c: Customer) => {
    const name = c.defaultReceiverName || c.wechatNickname || c.name || c.nickname || ''
    const phone = c.defaultReceiverPhone || c.phone || ''
    const region = [c.regionProvince, c.regionCity, c.regionDistrict].filter(Boolean).join(' ')
    const address = c.defaultReceiverAddress || region
    if (name) setCustomerName(name)
    if (phone) setCustomerPhone(phone)
    if (address) setCustomerAddress(address)
    // 常用物流（issue #4874）：按**客户档案**带出，**可改**。档案没录 ⇒ 置空（未指定），
    // 不编造「快递」默认值、也不把上一个客户的档案留在界面上。
    setLogisticsType(c.defaultLogisticsType ?? '')
    setLogisticsCompany(c.defaultLogisticsCompany ?? '')
    setCustomerModalOpen(false)
    setCustomerKeyword('')
    setCustomerResults([])
  }

  // ===== 选中商品后加载详情 =====
  const handlePickProduct = async (product: Product) => {
    const lineId = activeLineId
    setProductModalOpen(false)
    if (!lineId) return

    updateLineItem(lineId, {
      productLoading: true,
      selectedProcessing: {},
      selectedColorId: null,
      selectedSku: null,
      quantity: 1,
      unitPrice: 0,
    })

    // 加载商品详情（含 SKU）；加工项不再随商品加载（issue #4371：与商品解耦，走店铺级目录）
    let detail: ProductDetail | null = null
    try {
      const res = await productApi.getProduct(product.id)
      detail = res.data?.data as unknown as ProductDetail
    } catch (e) {
      toastRequestError(e, '加载商品详情失败')
      detail = product as unknown as ProductDetail
    }

    const fallbackPrice =
      Number(detail?.price) || Number(detail?.basePrice) || Number(product.price) || 0

    updateLineItem(lineId, (it) => {
      const next: OrderLineItem = {
        ...it,
        product: detail,
        productLoading: false,
        unitPrice: fallbackPrice,
        processingItems: processingCatalog,
        selectedProcessing: {},
      }
      return {
        product: next.product,
        productLoading: next.productLoading,
        unitPrice: next.unitPrice,
        processingItems: next.processingItems,
        // 换商品 = 清空勾选 ⇒ 按帘体补「定型」的默认勾选（issue #4566）
        selectedProcessing: withShapedDefault(next),
      }
    })
  }

  // ===== 颜色 / 规格 选择 =====
  const handleSelectColor = (line: OrderLineItem, colorId: string) => {
    const skusOfColor = (line.product?.skus || []).filter((s) => s.colorId === colorId)
    // issue #4877 裁定 C：多门幅时按**门幅规则**选默认（可行集最小门幅 / 定宽买高分幅最少）
    const autoSku = pickAutoSkuForColor(line, skusOfColor)
    updateLineItem(line.id, {
      selectedColorId: colorId,
      selectedSku: autoSku,
      skuAutoSelected: Boolean(autoSku),
      unitPrice: autoSku ? Number(autoSku.price) : line.unitPrice,
    })
  }

  const handleSelectSku = (line: OrderLineItem, sku: OrderProductSku) => {
    updateLineItem(line.id, {
      selectedSku: sku,
      unitPrice: Number(sku.price) || 0,
    })
  }

  /**
   * 勾选 / 取消一个加工项。
   *
   * **工艺单值护栏**（issue #4566）：路线键的工艺维是**单值** ⇒ 新勾的项带 `craftHint` 时，
   * 自动取消**另一个**带 `craftHint`（不同名）的已勾项，并 `toast` 说明换了哪一个
   * （**不静默**：同一张单出现两套工艺声明 = 两套工序，商家必须看见换了）。
   *
   * 勾/取消「定型」⇒ 记下「商家手动改过」（`shapedItemTouched`）⇒ 之后改帘体不再覆盖默认档。
   */
  const toggleProcessing = (
    line: OrderLineItem,
    pi: ProcessingItem,
    selected: boolean
  ) => {
    const prev = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
    const nextSelected: Record<string, { selected: boolean; qty: number }> = {
      ...line.selectedProcessing,
      // 选中即按当前面料米数推导数量（per_meter=米数，其余=1）；取消勾选保留原值（issue #3005 回滚 #2986）
      [pi.id]: { selected, qty: selected ? deriveProcessingQty(line.quantity) : prev.qty },
    }

    // 工艺单值护栏：一张单只能有一个工艺声明
    let replaced: ProcessingItem | undefined
    if (selected && pi.craftHint) {
      replaced = line.processingItems.find(
        (other) =>
          other.id !== pi.id &&
          Boolean(other.craftHint) &&
          other.craftHint !== pi.craftHint &&
          nextSelected[other.id]?.selected === true
      )
      if (replaced) {
        nextSelected[replaced.id] = { ...nextSelected[replaced.id], selected: false }
      }
    }

    updateLineItem(line.id, {
      selectedProcessing: nextSelected,
      // 加工项一变 ⇒ **组合键就变** ⇒ 上一组合的人工改价**必须清掉**（issue #4878 独立复核 P1）。
      // 不清的后果：`buildLineProcessingInfo` 只按「有值」就把 override 写进 processingInfo
      // ⇒ 商家为「组合 A」输的价会**静默给组合 B 定价**（后端按 manual 采用），
      // 而 fee_source 翻 manual 后改价输入框消失 ⇒ 商家连"改过价"都看不见（错钱且无感）。
      processingFeeOverride: null,
      // 手改过定型（勾或取消）⇒ 留痕，改帘体不再覆盖
      ...(pi.name === SHAPED_ITEM_NAME ? { shapedItemTouched: true } : {}),
    })

    if (replaced) {
      toast.info(`一张单只能有一个工艺：已把「${replaced.name}」换成「${pi.name}」`)
    }
  }

  // 行商品数量（面料米数）**手工改**（issue #4434）：
  // ① 标记来源「人工指定」⇒ 后续算料试算**不得静默改回**（真值源 §8：褶数/用料必须带来源）；
  // ② 已选中加工项数量联动重算（per_meter=面料米数，其余=1）（issue #3005 回滚 #2986）；
  // ③ **记下改这一笔时的入参签名**（issue #5202 · 根因 2）：此后宽/高/门幅/工艺若变 ⇒
  //    页面显式告知「已人工指定，未跟随」+ 一键恢复（**不静默覆盖**，也不让商家自己猜）。
  const handleLineQtyChange = (line: OrderLineItem, qty: number) => {
    updateLineItem(line.id, {
      quantity: qty,
      metersSource: LINE_METERS_SOURCE_MANUAL,
      metersManualSignature: craftCalcSignature(craftCalcParamsOf(calcInputOf(line, calcConfig))),
      selectedProcessing: requantifyProcessing(line, qty),
    })
  }

  /** 「恢复按公式计算」（issue #4434）：显式切回 ⇒ 下一次试算重新预填数量（并清掉「未跟随」告知） */
  const restoreFormulaMeters = (line: OrderLineItem) => {
    updateLineItem(line.id, {
      metersSource: METERS_SOURCE_FORMULA,
      calcError: null,
      metersManualSignature: undefined,
    })
  }

  // ===== 算料试算（issue #4434 · 前置 #4421）=====
  //
  // 三条口径：
  // ① **单一真值**：用料米数由算料引擎（后端端点）算，前端**不复制任何公式**；公式串也由后端产出；
  // ② **只预填「公式计算」的行**：商家手改过数量的行（`人工指定`）不得被静默改回（真值源 §8）；
  // ③ **失败不静默**：400（拼次纸表未登记 / 非韩褶）在行内显式提示，数量保持原样，**不退回估算值**。
  const calcSignature = useMemo(
    () =>
      lineItems
        .map(
          (l) =>
            `${l.id}:${l.metersSource}:${craftCalcSignature(craftCalcParamsOf(calcInputOf(l, calcConfig)))}`
        )
        .join(';'),
    [lineItems, calcConfig]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: CraftCalcParams }> = []
    for (const line of lineItems) {
      if (line.metersSource !== METERS_SOURCE_FORMULA) continue
      const params = craftCalcParamsOf(calcInputOf(line, calcConfig))
      if (params) targets.push({ id: line.id, params })
    }
    if (targets.length === 0) return

    let cancelled = false
    const timer = setTimeout(async () => {
      const results: Array<{ id: string; calc: CraftCalcResult | null; error: string | null }> =
        await Promise.all(
          targets.map(async ({ id, params }) => {
            try {
              const res = await craftCalcApi.preview(params)
              return { id, calc: (res.data?.data ?? null) as CraftCalcResult | null, error: null }
            } catch (e) {
              return { id, calc: null, error: craftCalcErrorText(e) }
            }
          })
        )
      if (cancelled) return
      setLineItems((prev) =>
        prev.map((it) => {
          const hit = results.find((r) => r.id === it.id)
          if (!hit) return it
          if (hit.error) return { ...it, calcError: hit.error }
          const meters = Number(hit.calc?.fabric_meters)
          if (!Number.isFinite(meters) || meters <= 0) {
            return {
              ...it,
              calcError: '算料未返回有效用料米数（数量保持原样，请核对宽高与工艺）',
            }
          }
          return {
            ...it,
            calc: hit.calc,
            calcError: null,
            quantity: meters,
            selectedProcessing: requantifyProcessing(it, meters),
          }
        })
      )
    }, CRAFT_CALC_DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // 依赖**只含入参签名**：试算会写回 quantity，若用行数组当依赖会自激成请求风暴
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calcSignature])

  // ===== 自动特征判定（issue #4976 包 2b：判定移到服务端）=====
  //
  // 与上面的试算 effect **同形态**（防抖 + 取消 + 只按入参签名触发），但**入参不同**：
  // 试算受 `CALC_CRAFTS` 门控（四爪钩/穿杆/平幔 不发），判定**每一行都发**。
  const autoFeatureSignature = useMemo(
    () =>
      lineItems
        .map((l) => `${l.id}:${autoFeatureParamsSignature(autoFeatureParamsOf(l, calcConfig))}`)
        .join(';'),
    // ⚠️ `calcConfig` 必须进依赖：两个**企业阈值**是判定入参的一部分（issue #5130）——
    // 漏了它 ⇒ 商家改完算料配置存盘后，页面**停在旧判定**上（可配却不生效的静默形态）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lineItems, calcConfig]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: AutoFeaturesParams }> = []
    for (const line of lineItems) {
      const params = autoFeatureParamsOf(line, calcConfig)
      if (params) targets.push({ id: line.id, params })
    }
    if (targets.length === 0) return

    let cancelled = false
    const timer = setTimeout(async () => {
      const results: Array<{ id: string; data: AutoFeaturesResult | null; error: string | null }> =
        await Promise.all(
          targets.map(async ({ id, params }) => {
            try {
              const res = await autoFeaturesApi.preview(params)
              return { id, data: res.data?.data ?? null, error: null }
            } catch (e) {
              return { id, data: null, error: craftCalcErrorText(e) }
            }
          })
        )
      if (cancelled) return
      setLineItems((prev) =>
        prev.map((it) => {
          const hit = results.find((r) => r.id === it.id)
          if (!hit) return it
          // 判定**只**写这两个字段：不碰数量/加工项（判定不产生米数）
          return { ...it, autoFeatures: hit.data, autoFeaturesError: hit.error }
        })
      )
    }, CRAFT_CALC_DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoFeatureSignature])

  // ===== 门幅规则（issue #5043 包 2b：规则移到服务端）=====
  //
  // 与上面两个 effect **同形态**（防抖 + 取消 + 只按入参签名触发）。
  // ⚠️ **必须在试算之前拿到**：`cuttingModeOf` 读本结果 ⇒ 它会进 `calcSignature` ⇒ 规则落行后
  // 试算会带着**正确**的加工类型再算一次（这正是「规则与试算同源」要的时序）。
  const doorWidthSignature = useMemo(
    () =>
      lineItems
        .map((l) => `${l.id}:${doorWidthParamsSignature(doorWidthParamsOf(l))}`)
        .join(';'),
    [lineItems]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: DoorWidthPlanParams }> = []
    for (const line of lineItems) {
      const params = doorWidthParamsOf(line)
      if (params) targets.push({ id: line.id, params })
    }
    if (targets.length === 0) return

    let cancelled = false
    const timer = setTimeout(async () => {
      const results: Array<{ id: string; data: DoorWidthPlanResult | null; error: string | null }> =
        await Promise.all(
          targets.map(async ({ id, params }) => {
            try {
              const res = await doorWidthPlanApi.preview(params)
              return { id, data: res.data?.data ?? null, error: null }
            } catch (e) {
              return { id, data: null, error: craftCalcErrorText(e) }
            }
          })
        )
      if (cancelled) return
      setLineItems((prev) =>
        prev.map((it) => {
          const hit = results.find((r) => r.id === it.id)
          if (!hit) return it
          const withPlan: OrderLineItem = { ...it, doorWidthPlan: hit.data, doorWidthPlanError: hit.error }
          // 规则**不产生米数** ⇒ 只写规则字段 + （规则到了才做得了的）**默认 SKU 补选**。
          if (!hit.data || hit.data.state !== 'single_panel') return withPlan
          // 只在「还没选」或「上次也是规则自动选的」时补 —— 客服手选过就**不覆盖**（同「手改留痕」纪律）
          if (withPlan.selectedSku !== null && !withPlan.skuAutoSelected) return withPlan
          const skusOfColor = (withPlan.product?.skus ?? []).filter(
            (sku) => sku.colorId === withPlan.selectedColorId
          )
          const autoSku = pickAutoSkuForColor(withPlan, skusOfColor)
          if (!autoSku) return withPlan
          return {
            ...withPlan,
            selectedSku: autoSku,
            unitPrice: Number(autoSku.price) || 0,
            skuAutoSelected: true,
          }
        })
      )
    }, CRAFT_CALC_DEBOUNCE_MS)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doorWidthSignature])

  // ===== 加工费计价预览（issue #4450 · 前置 #4406）=====
  //
  // **为什么必须有它**：本页此前本地自算（Σ 加工项），而服务端创建订单按**选配组合取价**
  // ⇒ 页面总额 ≠ 服务端总额 ⇒ 命中创建路径「实收金额与应收不一致」校验 ⇒ **拒单**。
  // 用服务端**同一份**取价实现提前拿到结果 ⇒ 页面显示 === 落库。
  //
  // ⚠️ 入参 = **即将提交的那一份** `processingInfo`（同一个 `buildLineProcessingInfo`）——
  //    预览与提交各拼一份就是「显示 ≠ 落库」的第二次分叉。
  /**
   * **商品组**（issue #4485）：按 `groupId` 把扁平行数组分组（保持出现顺序）。
   *
   * 为什么仍保留扁平数组：裁定 **R-a**「一行 `order_items` = 一个部位」是**落库**口径 ——
   * 提交 / 校验 / 算料 / 取价都按扁平数组走；分组**只是展示与编辑归属**，模型一字不改。
   */
  const productGroups = useMemo<ProductGroup[]>(() => {
    const order: string[] = []
    const byId = new Map<string, ProductGroup>()
    for (const line of lineItems) {
      let g = byId.get(line.groupId)
      if (!g) {
        g = {
          id: line.groupId,
          product: line.product,
          productLoading: line.productLoading,
          selectedColorId: line.selectedColorId,
          selectedSku: line.selectedSku,
          saleForm: line.saleForm,
          curtainBody: line.curtainBody,
          lines: [],
        }
        byId.set(line.groupId, g)
        order.push(line.groupId)
      }
      g.lines.push(line)
    }
    return order.map((id) => byId.get(id)!)
  }, [lineItems])

  /** 参与计价的行（与提交时的过滤条件**同一口径**：必须有商品） */
  const pricedLines = useMemo(() => lineItems.filter((l) => l.product), [lineItems])

  const feePreviewPayload = useMemo(
    () => ({
      items: pricedLines.map((l) => ({
        processingInfo: buildLineProcessingInfo(l, calcConfig),
      })),
    }),
    [pricedLines, calcConfig]
  )

  /** 行 id → 取价行下标（`pricedLines` 与 `feePreview.items` 同序） */
  const feeIndexByLineId = useMemo(() => {
    const m = new Map<string, number>()
    pricedLines.forEach((l, i) => m.set(l.id, i))
    return m
  }, [pricedLines])

  const feePreviewSignature = useMemo(() => JSON.stringify(feePreviewPayload), [feePreviewPayload])

  const [feePreview, setFeePreview] = useState<FeePreviewResult | null>(null)
  const [feePreviewError, setFeePreviewError] = useState<string | null>(null)
  const [feePreviewPending, setFeePreviewPending] = useState(false)

  useEffect(() => {
    // 没商品 ⇒ 没有可计价的行（本页初始态）⇒ 不请求
    if (pricedLines.length === 0) {
      setFeePreview(null)
      setFeePreviewError(null)
      setFeePreviewPending(false)
      return
    }
    setFeePreviewPending(true)
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const res = await feePreviewApi.preview(feePreviewPayload)
        if (cancelled) return
        setFeePreview(res.data?.data ?? null)
        setFeePreviewError(null)
      } catch (e) {
        if (cancelled) return
        setFeePreview(null)
        setFeePreviewError(feePreviewErrorText(e))
      } finally {
        if (!cancelled) setFeePreviewPending(false)
      }
    }, FEE_PREVIEW_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // 依赖只含**入参签名**：结果写回 totals 不改动入参 ⇒ 不会自激成请求风暴
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feePreviewSignature, pricedLines.length])

  /** 未定价的行数（服务端按 0 计）—— 必须显式可见：`¥0.00` 与「本来就不收」分不清 */
  // ⚠️ **布料行不计入「未定价」**（issue #4493）：布料无加工 ⇒ 服务端按 0 计是**正常**的，
  // 把它算成「未定价」会让每一张布料单都挂一条假警报。
  /**
   * 未定价行**按组合归并**（issue #4590）：只报行数 = 商家不知道该给哪个组合定价
   * （用户原话：「这里要把具体的加工项组合告知用户，不然用户不知道设置哪个组合」）。
   *
   * 组合名与**行名**（商品名 + 帘体）都取自既有真值：名字 = `items.join(' + ')`
   * （与「加工费组合」页同一写法，见 {@link unpricedCombinationLabel}）；
   * 行名 = 费用明细里已有的「商品名」（一个商品组 = 一套帘 ⇒ 同组同名，去重后即「哪些行」）。
   * 同一组合命中多行 ⇒ **合并计数**（「布帘 + 韩褶（2 行）」）；多个组合 ⇒ 逐条列。
   */
  const unpricedGroups = useMemo(() => {
    const byComposition = new Map<
      string,
      {
        composition: string
        label: string
        lineNames: string[]
        count: number
        optionTotal: number
      }
    >()
    ;(feePreview?.items ?? []).forEach((row, i) => {
      const line = pricedLines[i]
      if (!line || line.saleForm === SALE_FORM_FABRIC) return
      const detail = row.processingFeeDetail as
        | { fee_source?: string; composition?: unknown; items?: unknown; special_options_total?: unknown }
        | undefined
      if (detail?.fee_source !== 'unpriced') return
      const composition = typeof detail.composition === 'string' ? detail.composition : ''
      const entry = byComposition.get(composition) ?? {
        composition,
        label: unpricedCombinationLabel(detail),
        lineNames: [],
        count: 0,
        optionTotal: 0,
      }
      entry.count += 1
      // 选项那半照常计入行金额（issue #4594）—— 告警要说清「哪半 0、哪半照计」
      entry.optionTotal += Number(detail.special_options_total) || 0
      const name = line.product?.name?.trim()
      if (name && !entry.lineNames.includes(name)) entry.lineNames.push(name)
      byComposition.set(composition, entry)
    })
    return [...byComposition.values()]
  }, [feePreview, pricedLines])

  /** 未定价行数（= 各组合命中行数之和；告警里的「N 行」就是它） */
  const unpricedCount = unpricedGroups.reduce((n, g) => n + g.count, 0)

  /** 未定价行里**已定价特殊选项**的合计（issue #4594）：这半**照常计入订单金额** */
  const unpricedOptionTotal = unpricedGroups.reduce((sum, g) => sum + g.optionTotal, 0)

  // ===== 费用汇总 =====
  const totals = useMemo(() => {
    let productSubtotal = 0
    let edgeSubtotal = 0

    lineItems.forEach((item) => {
      if (!item.product) return
      productSubtotal += (Number(item.quantity) || 0) * (Number(item.unitPrice) || 0)
      // 双拼配布边（§4.8）：配布边是一条**独立面料明细行** ⇒ 金额必须计入订单总额，
      // 否则后端「应收 - 优惠 ≈ 实收」校验会拒单（金额 = 商家自己填的单价 × 米数，
      // 本包不引入任何工艺加价 —— 加价口径待 issue #4341 裁定）。
      const edgePrice = edgeUnitPriceOf(item)
      if (edgePrice !== null) {
        edgeSubtotal += edgeMetersOf(item) * edgePrice
      }
      // ⚠️ issue #4874：`布帘+纱帘` 那一族（含 `totals.sheerSubtotal` 与费用明细「纱帘」行）
      // 已**整体删除** —— 需要纱帘时它是**独立商品组**的一行（走本函数的商品小计），
      // 不再由主布行派生。
    })

    // 加工费 = **服务端取价结果**（issue #4450）。
    // 此前这里是本地 `Σ 加工项单价 × 数量`，与服务端 #4406 的组合取价口径不同 ⇒ 提交必被拒。
    // 预览未就绪时按 0 —— 由提交闸门拦住（不得用本地估算值提交）。
    const processingFee = feePreview?.processingFeeTotal ?? 0

    return {
      productSubtotal,
      edgeSubtotal,
      processingFee,
      total: productSubtotal + edgeSubtotal + processingFee,
    }
  }, [lineItems, feePreview])

  // ===== 优惠金额 + 实收款 双向联动逻辑 =====
  const {
    discountAmount,
    setDiscountAmount,
    commitDiscount,
    actualAmount,
    setActualAmount,
    commitActual,
  } = useOrderAmounts(totals.total)

  // 提交用数值：输入中间态（''/非法）兜底为默认值，负数 clamp 0
  const discountNumber = (() => {
    const num = Number(discountAmount)
    return Number.isNaN(num) || num < 0 ? 0 : num
  })()
  const actualNumber = (() => {
    const num = Number(actualAmount)
    return Number.isNaN(num) || num < 0 ? totals.total : num
  })()

  // ===== 校验 =====
  const validate = (): boolean => {
    const e: Record<string, string> = {}

    if (lineItems.length === 0) {
      e.lineItems = '请至少添加一个商品'
    }

    // 加工费计价闸门（issue #4450）：**页面总额必须就是服务端将算出的总额**，
    // 否则提交会被创建路径的「实收金额与应收不一致」拒单。
    // ⇒ 计价未就绪 / 失败时**一律不许提交**（宁可让商家等一下，也不要发一个必被拒的单）。
    if (pricedLines.length > 0) {
      if (feePreviewError) {
        e.feePreview = feePreviewError
      } else if (!feePreview || feePreviewPending) {
        e.feePreview = '加工费计价中，请稍候再提交'
      }
    }

    lineItems.forEach((line, idx) => {
      const prefix = `line_${line.id}`
      // 自动特征判定闸门（issue #4976 包 2b）：判定缺席 ⇒ 组合键少一项 ⇒ 取价错
      // （与上面的加工费计价闸门同口径；判定不产生米数，所以放在逐行校验之前）
      const autoBlock = autoFeaturesBlockReason([line], calcConfig)
      if (autoBlock) e[`${prefix}_autoFeatures`] = autoBlock
      if (!line.product) {
        e[`${prefix}_product`] = `第 ${idx + 1} 个商品未选择`
        return
      }
      const colorOptions = uniqueColors(line.product.skus)
      const skuOptions =
        line.selectedColorId != null
          ? (line.product.skus || []).filter((s) => s.colorId === line.selectedColorId)
          : []
      if (colorOptions.length > 0 && line.selectedColorId == null) {
        e[`${prefix}_color`] = `第 ${idx + 1} 个商品未选择颜色`
      }
      if (skuOptions.length > 0 && !line.selectedSku) {
        e[`${prefix}_spec`] = `第 ${idx + 1} 个商品未选择规格`
      }
      // 宽 / 高**必填**（issue #4420）——但**仅成品帘**（issue #4493，用户裁定）：
      // 布料按米卖，没有成品尺寸 ⇒ 布料单既不显示也不校验宽高
      // （否则布料单会被「未填宽」直接卡住提交，实测形态）。
      if (line.saleForm !== SALE_FORM_FABRIC) {
        // 它们是**不可推导的原始输入**（设计 §5.9.3）—— 丢了永远拿不回来，而用料 / 幅数 /
        // 加工单复核全靠它。只存米数 = 把输入扔了只留输出（#4273 的根因形态）。
        if (!(Number(line.width) > 0)) {
          e[`${prefix}_width`] = `第 ${idx + 1} 个商品未填宽（米）`
        }
        if (!(Number(line.height) > 0)) {
          e[`${prefix}_height`] = `第 ${idx + 1} 个商品未填高（米）`
        }
      }
      if (!line.quantity || line.quantity <= 0) {
        e[`${prefix}_quantity`] = '数量须大于 0'
      }
      if (line.unitPrice == null || line.unitPrice <= 0) {
        e[`${prefix}_unitPrice`] = '单价须大于 0'
      }
      // ⚠️ issue #4874：原「带纱帘 ⇒ 纱帘单价必填」的校验已随 `布帘+纱帘` 档**整体删除**
      // （帘体不再有该档；独立纱帘组那一行的单价由既有的「单价须大于 0」兜住）。
    })

    if (!customerName.trim()) e.customerName = '请输入收货人姓名'
    if (!customerPhone.trim()) e.customerPhone = '请输入手机号'
    else if (!/^1[3-9]\d{9}$/.test(customerPhone.trim())) e.customerPhone = '手机号格式不正确'
    if (!customerAddress.trim()) e.customerAddress = '请输入收货地址'

    setErrors(e)
    return Object.keys(e).length === 0
  }

  // ===== 提交 =====
  const handleSubmit = async () => {
    if (!validate()) {
      toast.error('请完善订单信息')
      return
    }

    // 套窗跨行分组已移除（issue #4486）；`craftLineId` 仍由 `buildLineProcessingInfo`
    // 按**本行自指**写入，供 §4.8 配布边行被主布行吸收（不是跨行分组）。
    const items: OrderItemFormData[] = pricedLines.flatMap((line, lineIndex) => {
      // 加工费 = **服务端取价结果**（issue #4450）：页面显示 === 落库。
      // 预览行与 `pricedLines` **同序**（服务端按下标一一对应）。
      const lineFee = Number(feePreview?.items[lineIndex]?.processingFee) || 0

      // `processingInfo` 由**同一个** `buildLineProcessingInfo` 构造（预览也是它）
      const baseInfo = buildLineProcessingInfo(line, calcConfig)
      const productSub = (Number(line.quantity) || 0) * (Number(line.unitPrice) || 0)
      const edgePrice = edgeUnitPriceOf(line)
      const pairKey = line.id

      const rows: OrderItemFormData[] = [
        {
          productId: line.product!.id,
          productName: line.product!.name,
          quantity: Number(line.quantity),
          unitPrice: Number(line.unitPrice),
          // 宽 / 高（issue #4420）：`order_items.width/height` 是**部位级**原生列，
          // 后端 DTO 已带 `@DecimalMin(0)`（#4089 A17）。此前这页一个都不写 ⇒
          // 订单详情 / 加工单 / 任务卡的宽高渲染永远拿不到值（#4403 的根因）。
          width: Number(line.width),
          height: Number(line.height),
          subtotal: productSub + lineFee,
          processingInfo: baseInfo
            ? // `processingFee` 用**服务端试算值**；`processingFeeDetail` **不送** ——
              // 服务端创建时按同一份取价写入权威构成，送一份客户端副本只会多一个可漂移的面。
              { ...baseInfo, processingFee: lineFee }
            : undefined,
        } as OrderItemFormData,
      ]

      // 配布边行（§4.8 一套窗 = 主布行 + 配布边行）：
      // - **不携带工艺规格**（褶数/开数/幅数是一套窗的属性 ⇒ 两行都带会让工序与计件翻倍）
      // - **不挂加工项**（硬约束：加工费只挂主布行）
      // - **不关联主布商品**（后端按 productId 聚合库存/销量 ⇒ 复用会双扣库存、双计销量）
      // - **绑组键与所在套窗同一个**（issue #4395）：配布边行与主布行同属一套窗 ⇒ 用 `pairKey`
      //   而不是本行自指（主布行被并进别的套窗时，自指会把配布边行丢在组外）
      if (edgePrice !== null) {
        const sku = line.selectedSku
        const colorName = uniqueColors(line.product!.skus).find(
          (c) => c.id === line.selectedColorId
        )?.name
        const edgeMeters = edgeMetersOf(line)
        rows.push({
          productName: COMPONENT_ROLE_EDGE,
          quantity: edgeMeters,
          unitPrice: edgePrice,
          subtotal: edgeMeters * edgePrice,
          processingInfo: {
            colorName,
            skuCode: sku?.skuCode,
            doorWidth: sku?.doorWidth,
            ...buildEdgeLineCraftSpec(
              pairKey,
              line.edgeMeters === null ? METERS_SOURCE_FOLLOW : METERS_SOURCE_MANUAL
            ),
          },
        } as OrderItemFormData)
      }

      // ⚠️ issue #4874：原「纱帘行」（`布帘+纱帘` 档的第二条明细行，携带同一份工艺规格、
      // 同 `craftLineId`）已**整体删除** —— 该档不再存在。纱帘若要单独成行，走**独立商品组**
      // （帘体 = 纱帘 ⇒ 该行显式写 `curtainType=纱帘`，部位语义与工序路线一字未动）。

      return rows
    })
    const actual = actualNumber
    let finalRemark = remark.trim()
    if (Math.abs(actual - totals.total) > 0.001) {
      const note = `实收款：¥${actual.toFixed(2)}（订单总额 ¥${totals.total.toFixed(2)}，优惠 ¥${discountNumber.toFixed(2)}）`
      finalRemark = finalRemark ? `${finalRemark}\n${note}` : note
    }

    setSubmitting(true)
    try {
      await orderApi.createOrder({
        customerName: customerName.trim(),
        customerPhone: customerPhone.trim(),
        customerAddress: customerAddress.trim(),
        actualAmount: actual,
        // 后端校验 应收 - 优惠 ≈ 实收（容差 0.01），必须随单携带，否则实收≠应收会被拒
        discountAmount: discountNumber,
        // **常用物流/快递 + 常用物流公司**（issue #4874）随建单落 `orders` 两列（后端 #4872）。
        // 缺值**不写**（`undefined`）——「未指定」与「快递」是两个真值，写死默认值 = 编造。
        logisticsType: logisticsType || undefined,
        logisticsCompany: logisticsCompany.trim() || undefined,
        // **加急 / 要求到货日**（issue #5177，做在订单上）：**未勾/未填 ⇒ 键不出现** ——
        // 「没填」与「显式不加急」在请求体上必须能区分（后端库列 NOT NULL DEFAULT FALSE / NULL）。
        // 不写死默认值（#4419 同族口径）；与售后 priority 零联动。
        ...urgencyRequestFields(isUrgent, requiredDeliveryDate),
        remark: finalRemark || undefined,
        items,
      })
      toast.success('订单创建成功')
      router.push('/orders')
    } catch (err) {
      toastRequestError(err, '创建订单失败')
    } finally {
      setSubmitting(false)
    }
  }

  // ====== 渲染 ======
  return (
    <div className="p-6 max-w-[1280px] mx-auto">
      {/* 顶部：返回 + 标题 */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push('/orders')}
          className="p-2 rounded-lg border border-neutral-200 hover:bg-neutral-50 transition-colors"
          aria-label="返回"
        >
          <ArrowLeft className="w-5 h-5 text-neutral-600" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-neutral-900">新增订单</h1>
          <p className="text-sm text-neutral-500 mt-0.5">
            支持添加多个商品，每个商品可单独配置加工项
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：商品行项 + 收货信息 */}
        <div className="lg:col-span-2 space-y-6">
          {/* ============= 商品信息（多行项） ============= */}
          <Card>
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <SectionTitle icon={<Package className="w-4 h-4" />} title="商品信息" />
                <span className="text-xs text-neutral-400">
                  共 {lineItems.length} 个商品
                </span>
              </div>

              <div className="space-y-4">
                {productGroups.map((group, gi) => (
                  <ProductGroupBlock
                    key={group.id}
                    index={gi}
                    group={group}
                    canRemove={productGroups.length > 1}
                    errors={errors}
                    onPickProduct={() => openProductModalFor(group.lines[0].id)}
                    onSelectColor={(colorId) => handleSelectColorForGroup(group.id, colorId)}
                    onSelectSku={(sku) => handleSelectSkuForGroup(group.id, sku)}
                    onChangeSaleForm={(form) => handleSaleFormChange(group.id, form)}
                    onChangeCurtainBody={(body) => handleCurtainBodyChange(group.id, body)}
                    onRemoveGroup={() => removeGroup(group.id)}
                    onChangeQty={(lineId, q) => {
                      const target = lineItems.find((l) => l.id === lineId)
                      if (target) handleLineQtyChange(target, q)
                    }}
                    onChangePrice={(lineId, p) => updateLineItem(lineId, { unitPrice: p })}
                    renderPosition={(line) => (
                      <LineItemBlock
                        key={line.id}
                        line={line}
                        errors={errors}
                        processingLoading={processingCatalogLoading}
                        onChangeQty={(q) => handleLineQtyChange(line, q)}
                        onRestoreFormula={() => restoreFormulaMeters(line)}
                        onChangePrice={(p) => updateLineItem(line.id, { unitPrice: p })}
                        onChangeWidth={(w) => {
                          updateLineItem(line.id, {
                            width: w,
                            // **宽 → 打开方式**联动（真值源 §10 的启发式）：手改过就不覆盖
                            ...(w !== null && !line.openCountTouched
                              ? { craft: { ...line.craft, openCount: deriveOpenCount(w) } }
                              : {}),
                          })
                          // 尺寸齐了 ⇒ 若该组还没选门幅，按**门幅规则**补默认（issue #4877 裁定 C）
                          autoSelectSkuByRuleForGroup(line.groupId, { width: w })
                        }}
                        onChangeHeight={(h) => {
                          updateLineItem(line.id, { height: h })
                          autoSelectSkuByRuleForGroup(line.groupId, { height: h })
                        }}
                        onToggleProcessing={(pi, sel) => toggleProcessing(line, pi, sel)}
                        onChangeCraft={(patch) => {
                          updateLineItem(line.id, {
                            craft: { ...line.craft, ...patch },
                            // 商家手改了打开方式 ⇒ 记下来（行状态），之后改宽不再覆盖
                            ...(patch.openCount !== undefined
                              ? { openCountTouched: true }
                              : {}),
                            // 加工类型**点过就是人工覆盖**（issue #5202 · 裁定 6）：连点「未指定」
                            // 也算点过 —— 否则默认档会继续替商家说话（默认档 ≠ 他的选择）。
                            ...('cuttingMode' in patch ? { cuttingModeTouched: true } : {}),
                          })
                          // 加工类型（定高买宽 / 定宽买高）变了 ⇒ 规则解可能变 ⇒ 未选门幅时补默认
                          autoSelectSkuByRuleForGroup(line.groupId, {
                            craft: { ...line.craft, ...patch },
                          })
                        }}
                        onAutoFeatureDecision={(name, decision) =>
                          decideAutoFeature(line.id, name, decision)
                        }
                        onEdgeMetersChange={(m) => updateLineItem(line.id, { edgeMeters: m })}
                        onEdgeUnitPriceChange={(p) =>
                          updateLineItem(line.id, { edgeUnitPrice: p })
                        }
                        // 加工费组合明细（issue #4874）：取价行（未定价 ⇒ 可就地改单价）
                        feeRow={
                          feeIndexByLineId.get(line.id) === undefined
                            ? null
                            : feePreview?.items[feeIndexByLineId.get(line.id)!] ?? null
                        }
                        calcConfig={calcConfig}
                        // 人工加 / 改推导项（issue #5202 · 裁定 4/6）：`null` = 清掉该项（回到由推导决定）
                        onChangePlanOverrides={(patch) =>
                          updateLineItem(line.id, (it) => ({
                            planOverrides: mergePlanOverrides(it.planOverrides, patch),
                          }))
                        }
                        // 推导出的特殊选项的裁决（issue #5211）：不采纳 ⇒ 该项不进 specialOptions
                        // （不插工序、不计件）
                        onDerivedOptionDecision={(name, decision) =>
                          decideDerivedOption(line.id, name, decision)
                        }
                        onProcessingFeeOverrideChange={(p) =>
                          updateLineItem(line.id, { processingFeeOverride: p })
                        }
                      />
                    )}
                  />
                ))}
              </div>

              <button
                type="button"
                onClick={addLineItem}
                className="mt-4 w-full h-11 rounded-lg border border-dashed border-neutral-300 bg-white text-sm text-neutral-500 hover:border-primary-500 hover:text-primary-600 hover:bg-primary-50/30 transition-colors inline-flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                添加商品
              </button>
            </div>
          </Card>

          {/* ============= 收货信息 ============= */}
          <Card>
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <SectionTitle icon={<User className="w-4 h-4" />} title="收货信息" />
                {/* #3102: 选择已有客户快捷回填收货信息 */}
                <button
                  type="button"
                  onClick={() => setCustomerModalOpen(true)}
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-primary-600 hover:text-primary-700 transition-colors"
                >
                  <UserPlus className="w-4 h-4" />
                  选择客户
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Input
                  label="收货人姓名"
                  placeholder="请输入收货人姓名"
                  value={customerName}
                  onChange={(e) => setCustomerName(e.target.value)}
                  error={errors.customerName}
                  required
                />
                <Input
                  label="手机号"
                  placeholder="请输入 11 位手机号"
                  value={customerPhone}
                  onChange={(e) => setCustomerPhone(e.target.value)}
                  error={errors.customerPhone}
                  maxLength={11}
                  required
                />
              </div>
              <div className="mt-4">
                <Input
                  label="收货地址"
                  placeholder="请输入详细收货地址"
                  value={customerAddress}
                  onChange={(e) => setCustomerAddress(e.target.value)}
                  error={errors.customerAddress}
                  required
                />
              </div>
              {/* **常用物流 / 快递** + **常用物流公司**（issue #4874，用户 2026-09-21：
                  「新增订单时收货信息中缺少用户的常用物流/快递以及常用公司，选择客户后要默认带出」）
                  —— 两个**可编辑**控件（词表唯一真值 = `lib/logistics.ts`），选客户时按档案带出，
                  随建单提交顶层 `logisticsType` / `logisticsCompany`（后端 #4872 落 `orders` 两列）。
                  ⚠️ 原先那条**只读**提示 `picked-logistics-hint` 已删除（不留两份口径）。 */}
              <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="order-logistics-type"
                    className="block text-sm font-medium text-neutral-700 mb-1.5"
                  >
                    常用物流/快递
                  </label>
                  <select
                    id="order-logistics-type"
                    data-testid="order-logistics-type"
                    value={logisticsType}
                    onChange={(e) => setLogisticsType(e.target.value)}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  >
                    {/* 「未指定」是真值：客户没录过常用物流时**不编造**「快递」（#4419 口径） */}
                    <option value="">未指定</option>
                    {LOGISTICS_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label
                    htmlFor="order-logistics-company"
                    className="block text-sm font-medium text-neutral-700 mb-1.5"
                  >
                    常用物流公司
                  </label>
                  {/* 候选来自 `LOGISTICS_COMPANIES`，但**允许自定义**（词表只是候选，不是白名单） */}
                  <input
                    id="order-logistics-company"
                    data-testid="order-logistics-company"
                    list="order-logistics-company-options"
                    placeholder="如 四季安物流"
                    value={logisticsCompany}
                    onChange={(e) => setLogisticsCompany(e.target.value)}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <datalist id="order-logistics-company-options">
                    {LOGISTICS_COMPANIES.map((c) => (
                      <option key={c} value={c} />
                    ))}
                  </datalist>
                </div>
              </div>
              <div className="mt-4">
                <label className="block text-sm font-medium text-neutral-700 mb-1.5">备注</label>
                <textarea
                  value={remark}
                  onChange={(e) => setRemark(e.target.value)}
                  placeholder="可填写发货要求、特殊说明等（选填）"
                  rows={3}
                  className="w-full px-3 py-2 rounded border border-neutral-300 text-sm resize-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
              </div>
            </div>
          </Card>
        </div>

        {/* 右侧：费用明细 + 操作 */}
        <div className="space-y-6">
          {/* 加急 / 要求到货日（issue #5177）：**做在订单上**（不是售后页）——
              加急单在池看板上走「加急插队区」（不进池、立即单派），到货日是派单排序键。 */}
          <Card>
            <div className="p-6">
              <SectionTitle icon={<Zap className="w-4 h-4" />} title="加急 / 到货日" />
              <div className="mt-4 space-y-4">
                <div className="flex items-start gap-3">
                  {/*
                    开关用 `role="switch"` 的按钮（**不是** `<input type="checkbox">`）：
                    下单页上已有「加工项」勾选框，多一个原生 checkbox 会让既有的
                    `getByRole('checkbox')` 变成「命中多个」（页面上不再有唯一的 checkbox）。
                  */}
                  <button
                    type="button"
                    role="switch"
                    aria-checked={isUrgent}
                    aria-label="加急"
                    onClick={() => setIsUrgent((v) => !v)}
                    className={cn(
                      'mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
                      isUrgent ? 'bg-primary-600' : 'bg-neutral-300'
                    )}
                  >
                    <span
                      className={cn(
                        'ml-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
                        isUrgent && 'translate-x-4'
                      )}
                    />
                  </button>
                  <span className="text-sm text-neutral-700">
                    加急（插队）
                    <span className="block text-xs text-neutral-400 mt-0.5">
                      加急单不进池，在池看板上单独立即派单
                    </span>
                  </span>
                </div>
                <div>
                  <label
                    htmlFor="requiredDeliveryDate"
                    className="block text-sm font-medium text-neutral-700 mb-1.5"
                  >
                    要求到货日
                  </label>
                  <input
                    type="date"
                    id="requiredDeliveryDate"
                    value={requiredDeliveryDate}
                    onChange={(e) => setRequiredDeliveryDate(e.target.value)}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <p className="mt-1 text-xs text-neutral-400">
                    留空 = 未指定（不填就是不填，不猜一个日期）；到货日越早，池看板上排得越前
                  </p>
                </div>
              </div>
            </div>
          </Card>

          <Card>
            <div className="p-6">
              <SectionTitle icon={<Receipt className="w-4 h-4" />} title="费用明细" />

              {/* 行项费用构成（issue #4420 重设计；**issue #4488② 改为按商品组合并**）。
                  用户 2026-09-19：「费用计算也不对」⇒「**按商品合并商品金额**」。
                  商品金额按**商品组**并成一行（米数 = 各部位之和）；**加工费仍逐部位**
                  （加工费按部位归属，不合并 —— 合并会看不出是哪个部位收的）。 */}
              {productGroups.some((g) => g.product) && (
                <div className="mb-4 space-y-3">
                  {productGroups
                    .filter((g) => g.product)
                    .map((group, gi) => {
                      const groupMeters = group.lines.reduce(
                        (acc, l) => acc + (Number(l.quantity) || 0),
                        0
                      )
                      const groupUnit = Number(group.lines[0].unitPrice) || 0
                      const groupSub = group.lines.reduce(
                        (acc, l) =>
                          acc + (Number(l.quantity) || 0) * (Number(l.unitPrice) || 0),
                        0
                      )
                      const groupProc = group.lines.reduce((acc, l) => {
                        const i = feeIndexByLineId.get(l.id)
                        return acc + (i === undefined ? 0 : Number(feePreview?.items[i]?.processingFee) || 0)
                      }, 0)
                      const groupEdge = group.lines.reduce((acc, l) => {
                        const p = edgeUnitPriceOf(l)
                        return acc + (p === null ? 0 : edgeMetersOf(l) * p)
                      }, 0)
                      const groupColor = uniqueColors(group.product?.skus).find(
                        (c) => c.id === group.selectedColorId
                      )?.name
                      const isFabric = group.saleForm === SALE_FORM_FABRIC
                      return (
                        <div
                          key={group.id}
                          className="rounded-lg border border-neutral-200 overflow-hidden"
                        >
                          <div className="flex items-center justify-between gap-2 px-3 py-2 bg-neutral-50/70">
                            <span className="text-xs font-medium text-neutral-700 truncate">
                              <span className="text-neutral-400 mr-1">{gi + 1}.</span>
                              {group.product?.name}
                              {groupColor && (
                                <span className="ml-1.5 font-normal text-primary-600">
                                  {groupColor}
                                </span>
                              )}
                              {isFabric && (
                                <span className="ml-1.5 font-normal text-neutral-500">布料</span>
                              )}
                            </span>
                            <span className="text-sm font-semibold text-neutral-900 shrink-0">
                              {formatAmount(groupSub + groupProc + groupEdge)}
                            </span>
                          </div>
                          <div className="px-3 py-2 space-y-1">
                            {/* 商品金额**按商品组合并成一行**（米数 = 各部位之和，总额不变） */}
                            <CostRow
                              label="商品"
                              expr={`${groupMeters} 米 × ${formatAmount(groupUnit)}/米`}
                              amount={groupSub}
                            />
                            {/* 加工费**逐部位**（成品帘才有） */}
                            {!isFabric &&
                              group.lines.map((line) => {
                                const i = feeIndexByLineId.get(line.id)
                                const feeRow = i === undefined ? undefined : feePreview?.items[i]
                                const d = feeRow?.processingFeeDetail as
                                  | {
                                      unit_price?: number
                                      meters?: number
                                      fee_source?: string
                                      composition?: unknown
                                      items?: unknown
                                      special_options_total?: unknown
                                    }
                                  | undefined
                                /** 该行已定价特殊选项的合计（issue #4594：组合未定价时它**照常计入**） */
                                const rowOptionTotal = Number(d?.special_options_total) || 0
                                const unit = Number(d?.unit_price)
                                const meters = Number(d?.meters)
                                const expr =
                                  Number.isFinite(unit) && Number.isFinite(meters)
                                    ? `${meters} 米 × ${formatAmount(unit)}/米`
                                    : null
                                // 判据 5（issue #4526）：加工行只显示**组合那半** —— 整个
                                // `processingFee` 含特殊选项那半，直接显示再单列特殊选项行 = 双算。
                                const feeDisplay = buildFeeDetailDisplay({
                                  processingFee: feeRow?.processingFee,
                                  processingFeeDetail: feeRow?.processingFeeDetail ?? null,
                                })
                                return (
                                  <CostRow
                                    key={`p_${line.id}`}
                                    label={
                                      line.curtainBody === CURTAIN_BODY_SHEER
                                        ? '加工·纱帘'
                                        : '加工'
                                    }
                                    expr={
                                      // 未定价行**点名组合**（issue #4590）：只写「未定价（按 0 计）」
                                      // 等于让商家自己回费用明细里猜是哪个组合没价。
                                      // issue #4594：未定价只指**组合那半** —— 已定价特殊选项照常计入
                                      // （它们另有逐项行），行内必须说清「哪半 0」，否则看起来像一分不收。
                                      d?.fee_source === 'unpriced'
                                        ? `组合未定价（组合那半按 0 计）· ${unpricedCombinationLabel(d)}${
                                            rowOptionTotal > 0
                                              ? `；特殊选项照计 ${formatAmount(rowOptionTotal)}`
                                              : ''
                                          }`
                                        : (expr ?? '—')
                                    }
                                    amount={feeDisplay.baseAmount}
                                    // 未定价 ⇒ **不渲染 `¥0.00`**（仓库硬纪律）：那格写「未定价」，
                                    // 组合名与「选项照计」在上面的算式里已经说清（issue #4590/#4594）
                                    amountLabel={
                                      d?.fee_source === 'unpriced' ? '未定价' : undefined
                                    }
                                  />
                                )
                              })}
                            {/* 特殊选项逐项（issue #4526 · 设计 §4.3 / 判据 5）：按**套**收费，
                                与加工费是**两半** —— 逐行 `名称 单价/套 × 套数`，合计进订单金额。
                                未定价的选项显式标「未定价（按 0 计）」，不静默。 */}
                            {!isFabric &&
                              group.lines.flatMap((line) => {
                                const i = feeIndexByLineId.get(line.id)
                                const feeRow = i === undefined ? undefined : feePreview?.items[i]
                                const display = buildFeeDetailDisplay({
                                  processingFee: feeRow?.processingFee,
                                  processingFeeDetail: feeRow?.processingFeeDetail ?? null,
                                })
                                return display.specialOptionRows.map((option) => (
                                  <CostRow
                                    key={`o_${line.id}_${option.key}`}
                                    label={option.label}
                                    expr={option.expr}
                                    amount={option.amount}
                                  />
                                ))
                              })}
                            {/* 拼色加价（#4855，用户 2026-09-21 裁定）：行金额的**第三个分量** ——
                                拼色款另加 2.4 元/米 × 面料米数（报价侧同源同价）。
                                键缺席（存量单 / 旧服务端）⇒ 0 ⇒ 不渲染该行（显示口径逐字不变）。 */}
                            {!isFabric &&
                              group.lines.map((line) => {
                                const i = feeIndexByLineId.get(line.id)
                                const feeRow = i === undefined ? undefined : feePreview?.items[i]
                                const display = buildFeeDetailDisplay({
                                  processingFee: feeRow?.processingFee,
                                  processingFeeDetail: feeRow?.processingFeeDetail ?? null,
                                })
                                return display.mixedColorSurcharge > 0 ? (
                                  <CostRow
                                    key={`m_${line.id}`}
                                    label="拼色加价"
                                    expr={display.mixedColorSurchargeExpr}
                                    amount={display.mixedColorSurcharge}
                                  />
                                ) : null
                              })}
                            {/* 配布边逐行（§4.8 一套窗 = 主布行 + 配布边行） */}
                            {group.lines.map((line) => {
                              const p = edgeUnitPriceOf(line)
                              if (p === null) return null
                              const m = edgeMetersOf(line)
                              return (
                                <CostRow
                                  key={`e_${line.id}`}
                                  label="配布边"
                                  expr={`${m} 米 × ${formatAmount(p)}/米`}
                                  amount={m * p}
                                />
                              )
                            })}
                            {/* ⚠️ issue #4874：原「纱帘」逐行（`布帘+纱帘` 档派生的第二条面料行）
                                已整体删除 —— 该档不再存在，需要纱帘时它是独立商品组的一行
                                （并入上面的「商品」金额，不再单列）。 */}
                          </div>
                        </div>
                      )
                    })}
                </div>
              )}

              <dl className="space-y-3 text-sm">
                <Row label="商品小计" value={formatAmount(totals.productSubtotal)} />
                {totals.edgeSubtotal > 0 && (
                  <Row label="配布边" value={formatAmount(totals.edgeSubtotal)} />
                )}
                {/* ⚠️ issue #4874：`totals.sheerSubtotal` 与「纱帘」汇总行已整体删除 */}
                <Row
                  label="加工费"
                  value={formatAmount(totals.processingFee)}
                  highlight={totals.processingFee > 0}
                />
                {/* 加工费计价状态（issue #4450）：数字来自**服务端**，状态必须显式可见 */}
                {feePreviewError && (
                  <div className="rounded bg-red-50 px-2.5 py-1.5 text-xs text-red-700">
                    {feePreviewError}（未确认金额前无法提交）
                  </div>
                )}
                {!feePreviewError && feePreviewPending && pricedLines.length > 0 && (
                  <div className="text-xs text-neutral-400">加工费计价中…</div>
                )}
                {!feePreviewError && unpricedCount > 0 && (
                  <div
                    data-testid="unpriced-fee-alert"
                    className="rounded bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700"
                  >
                    <p>
                      有 {unpricedCount} 行加工费未定价 ——{' '}
                      <span className="font-medium">组合那半按 0 计</span>
                      {unpricedOptionTotal > 0
                        ? `；已定价的特殊选项照常计入（合计 ${formatAmount(unpricedOptionTotal)}）`
                        : ''}
                      。请为下列加工项组合定价后再下单：
                    </p>
                    {/* 逐条点名（issue #4590）：组合名与「加工费组合」页逐字一致；同一组合合并计数 */}
                    <ul className="mt-1 list-disc pl-4 space-y-0.5">
                      {unpricedGroups.map((g) => (
                        <li key={g.composition}>
                          {g.label}（{g.count} 行
                          {g.lineNames.length > 0 ? `：${g.lineNames.join('、')}` : ''}）
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1">
                      定价入口：
                      <Link
                        href={PRICING_ENTRY}
                        className="underline underline-offset-2 hover:text-amber-900"
                      >
                        「加工费组合」
                      </Link>
                    </p>
                  </div>
                )}
                {errors.feePreview && (
                  <div className="rounded bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700">
                    {errors.feePreview}
                  </div>
                )}
                <div className="my-2 border-t border-dashed border-neutral-200" />
                <div className="flex items-baseline justify-between">
                  <span className="text-neutral-700">订单金额</span>
                  <span className="text-lg font-semibold text-primary-600">
                    {formatAmount(totals.total)}
                  </span>
                </div>

                {/* 优惠金额 — issue #672；双向联动 + blur 归一化（修复输入被每键重格式化吞键锁死） */}
                <div className="pt-3 mt-2 border-t border-neutral-100">
                  <label htmlFor="discountAmount" className="block text-sm font-medium text-neutral-700 mb-1.5">
                    优惠金额 (¥)
                  </label>
                  <input
                    type="text"
                    inputMode="decimal"
                    id="discountAmount"
                    value={discountAmount}
                    onChange={(e) => setDiscountAmount(e.target.value)}
                    onBlur={commitDiscount}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <p className="mt-1 text-xs text-neutral-400">默认 0；修改后实收款自动联动（订单金额 - 优惠）</p>
                </div>

                <div className="pt-3 mt-2 border-t border-neutral-100">
                  <label htmlFor="actualAmount" className="block text-sm font-medium text-neutral-700 mb-1.5">
                    实收款 (¥)
                  </label>
                  <input
                    type="text"
                    inputMode="decimal"
                    id="actualAmount"
                    value={actualAmount}
                    onChange={(e) => setActualAmount(e.target.value)}
                    onBlur={commitActual}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <p className="mt-1 text-xs text-neutral-400">默认与订单金额（扣除优惠后）一致；手动输入后自动反算优惠金额</p>
                </div>
              </dl>
            </div>
          </Card>

          <div className="flex flex-col gap-2">
            <Button onClick={handleSubmit} loading={submitting} className="w-full" size="lg">
              提交订单
            </Button>
            <Button
              variant="secondary"
              onClick={() => router.push('/orders')}
              className="w-full"
              size="lg"
              disabled={submitting}
            >
              取消
            </Button>
          </div>
        </div>
      </div>

      {/* 商品搜索弹窗 */}
      <Modal
        open={productModalOpen}
        onClose={() => setProductModalOpen(false)}
        title="选择商品"
        width={680}
        footer={
          <Button variant="secondary" onClick={() => setProductModalOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Input
              placeholder="搜索商品名称 / 货号"
              value={productKeyword}
              onChange={(e) => setProductKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchProducts()}
            />
            <Button onClick={searchProducts} loading={productSearchLoading} className="shrink-0">
              搜索
            </Button>
          </div>

          <div className="max-h-[420px] overflow-y-auto -mx-2 px-2">
            {productSearchLoading ? (
              <p className="text-center text-neutral-400 py-8 text-sm">加载中…</p>
            ) : productResults.length === 0 ? (
              <p className="text-center text-neutral-400 py-8 text-sm">
                {productKeyword ? '未找到相关商品' : '暂无可选商品'}
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {productResults.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => handlePickProduct(p)}
                    className="flex items-center gap-3 p-3 rounded-lg border border-neutral-200 bg-white hover:border-primary-400 hover:bg-primary-50/40 transition-colors text-left"
                  >
                    {p.images?.[0] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={resolveImageUrl(p.images[0])}
                        alt={p.name}
                        className="w-12 h-12 rounded object-cover bg-neutral-50 border border-neutral-200 shrink-0"
                      />
                    ) : (
                      <div className="w-12 h-12 rounded bg-neutral-100 border border-neutral-200 flex items-center justify-center text-neutral-300 shrink-0">
                        <Package className="w-5 h-5" />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-neutral-900 truncate">{p.name}</div>
                      <div className="text-xs text-neutral-400 mt-0.5 truncate">
                        {p.categoryName || '-'} · {p.skuCode || p.unit || '-'}
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-neutral-900 shrink-0">
                      ¥{Number(p.price ?? 0).toFixed(2)}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </Modal>

      {/* 客户选择弹窗（#3102）：选已有客户 → 回填收货信息；未命中可关闭后手动输入 */}
      <Modal
        open={customerModalOpen}
        onClose={() => setCustomerModalOpen(false)}
        title="选择客户"
        width={560}
        footer={
          <Button variant="secondary" onClick={() => setCustomerModalOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Input
              placeholder="搜索客户姓名 / 手机号"
              value={customerKeyword}
              onChange={(e) => setCustomerKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchCustomers()}
            />
            <Button onClick={searchCustomers} loading={customerSearchLoading} className="shrink-0">
              搜索
            </Button>
          </div>

          <div className="max-h-[380px] overflow-y-auto -mx-2 px-2">
            {customerSearchLoading ? (
              <p className="text-center text-neutral-400 py-8 text-sm">加载中…</p>
            ) : customerResults.length === 0 ? (
              <p className="text-center text-neutral-400 py-8 text-sm">
                {customerKeyword ? '未找到相关客户，可关闭后手动填写收货信息' : '暂无可选客户'}
              </p>
            ) : (
              <div className="space-y-2">
                {customerResults.map((c) => {
                  const name = c.wechatNickname || c.name || c.nickname || '未命名客户'
                  const region = [c.regionProvince, c.regionCity, c.regionDistrict].filter(Boolean).join(' ')
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => handlePickCustomer(c)}
                      className="flex w-full items-center gap-3 p-3 rounded-lg border border-neutral-200 bg-white hover:border-primary-400 hover:bg-primary-50/40 transition-colors text-left"
                    >
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-50 text-primary-600">
                        <User className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-neutral-900 truncate">{name}</div>
                        <div className="text-xs text-neutral-400 mt-0.5 flex items-center gap-3">
                          {c.phone && (
                            <span className="inline-flex items-center gap-1">
                              <Phone className="w-3 h-3" />
                              {c.phone}
                            </span>
                          )}
                          {region && (
                            <span className="inline-flex items-center gap-1 truncate">
                              <MapPin className="w-3 h-3 shrink-0" />
                              {region}
                            </span>
                          )}
                        </div>
                      </div>
                      {c.sourceChannel && (
                        <span className="shrink-0 rounded bg-neutral-100 px-1.5 py-0.5 text-[11px] text-neutral-500">
                          {c.sourceChannel === 'wechat_mini' ? '小程序' : c.sourceChannel === 'h5' ? 'H5' : c.sourceChannel}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}

// ====== 行项卡片 ======
interface LineItemBlockProps {
  line: OrderLineItem
  errors: Record<string, string>
  processingLoading: boolean
  onChangeQty: (q: number) => void
  /** 「恢复按公式计算」（issue #4434）：切回算料预填（手改后不会被静默改回，只能显式恢复） */
  onRestoreFormula: () => void
  onChangePrice: (p: number) => void
  /** 成品宽 / 高（米；issue #4420 必填） */
  onChangeWidth: (w: number | null) => void
  onChangeHeight: (h: number | null) => void
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
}


/**
 * **布料行**（issue #4493，用户裁定「如果是布料下单就**无加工**了」）：
 * 只有 **米数 / 单价** —— 不出现宽高 / 工艺规格 / 部位行 / 加工项 / 加工费。
 *
 * 为什么不复用部位行：部位行整套（工艺规格 8 项 + 宽高 + 加工项 + 算料）对布料**全是噪音**，
 * 而且宽高对布料没有意义（布料按米卖，没有成品尺寸）。
 */
function FabricRow({
  line,
  errors,
  onChangeQty,
  onChangePrice,
}: {
  line: OrderLineItem
  errors: Record<string, string>
  onChangeQty: (q: number) => void
  onChangePrice: (p: number) => void
}) {
  const errQty = errors[`line_${line.id}_quantity`]
  const errPrice = errors[`line_${line.id}_unitPrice`]
  const inputClass =
    'w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'
  return (
    <div className="rounded-lg border border-neutral-200 p-3">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label required>数量</Label>
          {/* 布料行的数字框同样换掉（issue #5202）：吞键缺陷与帘行同源；#5210 起 = 共享 `NumberInput` */}
          <NumberInput
            value={line.quantity}
            onChange={(next) => onChangeQty(next ?? 0)}
            decimals={3}
            placeholder="米"
            aria-label="数量"
            className={inputClass}
          />
          {errQty && <p className="mt-1 text-sm text-red-600">{errQty}</p>}
        </div>
        <div>
          <Label required>单价 (¥/米)</Label>
          <NumberInput
            value={line.unitPrice}
            onChange={(next) => onChangePrice(next ?? 0)}
            decimals={3}
            aria-label="单价 (¥/米)"
            className={inputClass}
          />
          {errPrice && <p className="mt-1 text-sm text-red-600">{errPrice}</p>}
        </div>
      </div>
      <p className="mt-1.5 text-xs text-neutral-400">
        布料按米计价：没有加工费，也不生成加工单
      </p>
    </div>
  )
}

/** 一个**商品组**：同商品 / 同色 / 同门幅下的多个部位行（issue #4485） */
interface ProductGroup {
  id: string
  product: ProductDetail | null
  productLoading: boolean
  selectedColorId: string | null
  selectedSku: OrderProductSku | null
  /** 售卖形态（issue #4493）：组级 —— 决定这一组下面出什么（布料 = 没有加工） */
  saleForm: SaleForm
  /** 帘体（issue #4521；**issue #4874 收窄为两档**：`布帘` / `纱帘`，`布帘+纱帘` 已删除） */
  curtainBody: CurtainBody
  lines: OrderLineItem[]
}

interface ProductGroupBlockProps {
  index: number
  group: ProductGroup
  canRemove: boolean
  errors: Record<string, string>
  /** 选择商品（组级）：选完写回**组内所有部位行** */
  onPickProduct: () => void
  /** 颜色（组级）：同一块布的颜色，组内同步 */
  onSelectColor: (colorId: string) => void
  /** 门幅 / 售卖方式（组级）：同上 */
  onSelectSku: (sku: OrderProductSku) => void
  /** 售卖形态（组级，issue #4493）：布料 / 成品帘 */
  onChangeSaleForm: (form: SaleForm) => void
  /** 帘体（组级，issue #4521；#4874 起只有 `布帘` / `纱帘` 两档） */
  onChangeCurtainBody: (body: CurtainBody) => void
  /** 删除整个商品组 */
  onRemoveGroup: () => void
  /** 渲染本组这一套帘（由页面传入，保证 props 装配只有一处） */
  renderPosition: (line: OrderLineItem) => React.ReactNode
  /** 布料行（无部位）的 米数 / 单价 回调（issue #4493） */
  onChangeQty: (lineId: string, qty: number) => void
  onChangePrice: (lineId: string, price: number) => void
}


/**
 * **可折叠头部**（issue #4679）—— 折叠开关的**唯一实现**：`button` 语义 + `aria-expanded`
 * + chevron（键盘可达：回车 / 空格都触发）。两处使用者共用它 —— **向导步骤**（#4511）与
 * **商品卡组头**（#4679）；用户口径「别新造一套折叠组件」。
 *
 * - `trailing`：**始终**渲染的右侧内容（组头的金额）；
 * - `summary`：**仅收起时**渲染的摘要（向导步骤的已选结果 / 组头的尺寸·米数）
 *   —— 收起 ≠ 看不出这是哪一行。
 */
function CollapsibleHeader({
  open,
  onToggle,
  className = '',
  summary,
  trailing,
  children,
}: {
  open: boolean
  onToggle: () => void
  className?: string
  /** 收起时显示的摘要 */
  summary?: React.ReactNode
  /** 始终显示的右侧内容 */
  trailing?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className={`flex items-center gap-2 text-left ${className}`}
    >
      {children}
      <span className="ml-auto flex items-center gap-1.5 min-w-0">
        {!open && summary && (
          <span className="text-xs text-neutral-500 truncate">{summary}</span>
        )}
        {trailing}
        {open ? (
          <ChevronDown className="w-4 h-4 text-neutral-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-neutral-400 shrink-0" />
        )}
      </span>
    </button>
  )
}

/**
 * **向导步骤**（issue #4511，用户口径「加个由上到下的向导，参考苹果商店的购买商品选配」）。
 *
 * 三条形态约定：
 * - **平级**：每步是兄弟，不嵌套（特殊选项不再挂在工艺规格下面）；
 * - **编号 + 收起摘要**：收起时显示已选结果（一眼看到当前配置）；
 * - **手风琴**：由调用方持有「当前展开的是第几步」⇒ 展开一步自动收起同级其它。
 */
function WizardStep({
  step,
  title,
  summary,
  badges,
  open,
  onToggle,
  children,
}: {
  step: number
  title: string
  /** 收起时显示的已选摘要 */
  summary?: string
  /**
   * 标题旁的**就地徽标**（issue #4658）：① 尺寸与数量那行显示系统识别结果 ——
   * 商家**填尺寸时**就看得见提示（不必翻到②工艺规格才发现）。展开/收起都渲染。
   */
  badges?: React.ReactNode
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="border-t border-neutral-100 first:border-t-0"
      data-testid={`wizard-step-${step}`}
    >
      <CollapsibleHeader
        open={open}
        onToggle={onToggle}
        className="w-full py-2.5"
        summary={summary}
      >
        <span
          className={
            'inline-flex items-center justify-center w-5 h-5 shrink-0 rounded-full text-[11px] font-semibold ' +
            (open ? 'bg-primary-600 text-white' : 'bg-neutral-100 text-neutral-500')
          }
        >
          {step}
        </span>
        <span className="text-sm font-medium text-neutral-700 shrink-0">{title}</span>
        {badges}
      </CollapsibleHeader>
      {open && <div className="pb-4">{children}</div>}
    </div>
  )
}

/**
 * **商品组**（issue #4485；issue #4521 起 = **一套帘**）：一块布（同商品 / 同色 / 同门幅）
 * 下渲染**一份** ①尺寸与数量 ②工艺规格 ③加工项 ④特殊选项。
 *
 * ⚠️ issue #4874（用户 2026-09-21 需求批次）—— 下单页**两步化**：区块 1 = 尺寸与数量 + 工艺规格、
 * 区块 2 = 加工项 + 特殊选项（原四段手风琴的序号 / 摘要 / 展开态全部按新结构走）；
 * 「布帘+纱帘」档整族删除；「加工项」区块新增**加工费组合明细块**（可就地改未定价单价）；
 * 收货信息补**常用物流/快递 + 常用物流公司**两个可编辑控件；收货信息里的「套窗」等术语统一为「套 / 帘」。
 *
 * 用户 2026-09-19 口径：「新增部位应该在**已选择的商品下**去新增，现在像是两个商品，
 * 商品的**基础属性应该共用**」→ 随后进一步裁定「**移除部位功能，其实完全不需要**」：
 * 一个商品组 = 一套帘，需要纱帘时改**帘体**（`curtainBody`），而不是再加一行。
 *
 * 为什么这样切：裁定 **R-a**「一行 `order_items` = 一个部位」是**落库**口径，与展示无关
 * —— 旧实现把落库口径直接当成了 UI 结构（复制一行 = 复制整张商品卡）⇒ 同一商品的两个部位
 * 看起来像两个商品、颜色与门幅还要各选一遍。
 *
 * 本组件只负责**商品基础属性**（选择商品 / 颜色 / 门幅·售卖方式 / 售卖形态 / 帘体）与那一套帘的排布；
 * 组内改颜色、门幅、售卖形态或帘体 ⇒ **组内所有行同步**（它们是同一块布的属性）。
 */
function ProductGroupBlock({
  index,
  group,
  canRemove,
  errors,
  onPickProduct,
  onSelectColor,
  onSelectSku,
  onChangeSaleForm,
  onChangeCurtainBody,
  onRemoveGroup,
  renderPosition,
  onChangeQty,
  onChangePrice,
}: ProductGroupBlockProps) {
  /**
   * **整卡折叠态**（issue #4679，用户原话「这里加个可折叠的交互」）—— 组头整行是开关。
   * **默认展开**（不改现有默认行为）；状态落在**本组件** ⇒ 多商品时各卡独立、互不影响。
   * 与卡体内四步手风琴（#4511）正交：那是「哪一步展开」，这是「整卡展开」。
   */
  const [open, setOpen] = useState(true)
  const colorOptions = useMemo(() => uniqueColors(group.product?.skus), [group.product])
  const skuOptions = useMemo(() => {
    if (!group.product?.skus || group.selectedColorId == null) return []
    return group.product.skus.filter((s) => s.colorId === group.selectedColorId)
  }, [group.product, group.selectedColorId])

  const first = group.lines[0]
  const errProduct = errors[`line_${first.id}_product`]
  const errColor = errors[`line_${first.id}_color`]
  const errSpec = errors[`line_${first.id}_spec`]
  const colorName = colorOptions.find((c) => c.id === group.selectedColorId)?.name
  const groupAmount = group.lines.reduce(
    (s, l) => s + (Number(l.quantity) || 0) * (Number(l.unitPrice) || 0),
    0
  )
  /** 收起时组头仍要能看出「这是哪一行」（#4679 判据 5）：顺手带出尺寸 / 米数 */
  const collapsedSummary = [
    first.width && first.height ? `${first.width} × ${first.height} m` : null,
    first.quantity ? `${first.quantity} 米` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  // **空商品组**（issue #4508，用户实测反馈「进入新增商品页面不应该有个默认商品 1」）：
  // 还没选商品 ⇒ **只渲染「选择商品」入口**，不渲染组壳（组头序号/商品名/N 个部位/金额、
  // 部位行、「新增部位」、售卖形态）—— 否则刚进页面就看起来"已经有一个商品了"。
  // ⚠️ 内部仍保留这一行（`lineItems` 初值不变）⇒ 提交 / 算料 / 取价的装配路径一律不动。
  if (!group.product) {
    const firstLine = group.lines[0]
    return (
      <div className="rounded-xl border border-dashed border-neutral-300 bg-white p-4">
        <Label required>选择商品</Label>
        <button
          type="button"
          onClick={onPickProduct}
          className="w-full h-11 rounded-lg border border-dashed border-neutral-300 bg-white text-sm text-neutral-500 hover:border-primary-500 hover:text-primary-600 transition-colors inline-flex items-center justify-center gap-2"
        >
          <Search className="w-4 h-4" />
          点击搜索并选择商品
        </button>
        {errors[`line_${firstLine.id}_product`] && (
          <p className="mt-1.5 text-sm text-red-600">
            {errors[`line_${firstLine.id}_product`]}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-neutral-200 bg-white">
      {/* 组头 = **商品基础属性**（一组一份）+ **整卡折叠开关**（issue #4679）：
          点组头整行 ⇒ 收起/展开卡片体。「删除」是开关的**兄弟节点**（不在 `<button>` 内）
          ⇒ 点删除只删、不被折叠吞掉；收起后它仍可用（不随卡片体卸载）。 */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-neutral-100 bg-neutral-50/60 rounded-t-xl">
        <CollapsibleHeader
          open={open}
          onToggle={() => setOpen(!open)}
          className="flex-1 min-w-0"
          summary={collapsedSummary}
          trailing={
            <span className="text-sm font-semibold text-neutral-900 shrink-0">
              {formatAmount(groupAmount)}
            </span>
          }
        >
          <span className="inline-flex items-center justify-center w-6 h-6 shrink-0 rounded-full bg-primary-600 text-white text-xs font-semibold">
            {index + 1}
          </span>
          <span className="text-sm font-medium text-neutral-900 truncate">
            {group.product?.name ?? `商品 ${index + 1}`}
          </span>
          {colorName && <span className="text-xs text-primary-600 shrink-0">{colorName}</span>}
          {/* 组头报**帘体**（issue #4521）：部位行已移除 ⇒ 原来的「N 个部位」不再有意义 */}
          <span className="text-xs text-neutral-400 shrink-0">
            {group.saleForm === SALE_FORM_FABRIC ? '布料' : group.curtainBody}
          </span>
        </CollapsibleHeader>
        {canRemove && (
          <button
            type="button"
            onClick={onRemoveGroup}
            className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-red-600 transition-colors shrink-0"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        )}
      </div>

      {open && (
      <div className="p-4">
        {/* 商品选择 */}
        <div className="mb-4">
          <Label required>选择商品</Label>
          {group.product ? (
            <div className="flex items-center gap-3 p-3 rounded-lg border border-neutral-200 bg-neutral-50/60">
              {group.product.images?.[0] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={resolveImageUrl(group.product.images[0])}
                  alt={group.product.name}
                  className="w-14 h-14 rounded object-cover bg-white border border-neutral-200"
                />
              ) : (
                <div className="w-14 h-14 rounded bg-neutral-100 border border-neutral-200 flex items-center justify-center text-neutral-300">
                  <Package className="w-6 h-6" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-neutral-900 truncate">
                  {group.product.name}
                </div>
                <div className="text-xs text-neutral-500 mt-0.5">
                  {group.product.categoryName || '-'} · 货号：{group.product.skuCode || '-'}
                </div>
              </div>
              <button
                onClick={onPickProduct}
                className="text-sm text-primary-600 hover:text-primary-700"
              >
                重新选择
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={onPickProduct}
              className="w-full h-11 rounded-lg border border-dashed border-neutral-300 bg-white text-sm text-neutral-500 hover:border-primary-500 hover:text-primary-600 transition-colors inline-flex items-center justify-center gap-2"
            >
              <Search className="w-4 h-4" />
              点击搜索并选择商品
            </button>
          )}
          {errProduct && <p className="mt-1.5 text-sm text-red-600">{errProduct}</p>}
        </div>

        {/* 颜色 + 规格 */}
        {group.product && (
          <>
            {group.productLoading ? (
              <div className="text-sm text-neutral-400 py-4">商品规格加载中…</div>
            ) : (
              <>
                {colorOptions.length > 0 && (
                  <div className="mb-4">
                    <Label required>颜色</Label>
                    <div className="flex flex-wrap gap-2">
                      {colorOptions.map((c) => {
                        const active = group.selectedColorId === c.id
                        return (
                          <button
                            key={c.id}
                            type="button"
                            onClick={() => onSelectColor(c.id)}
                            className={
                              'h-9 px-3 rounded border text-sm transition-colors ' +
                              (active
                                ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                                : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                            }
                          >
                            {c.name}
                          </button>
                        )
                      })}
                    </div>
                    {errColor && <p className="mt-1.5 text-sm text-red-600">{errColor}</p>}
                  </div>
                )}

                {group.selectedColorId != null && skuOptions.length > 0 && (
                  <div className="mb-4">
                    <Label required>门幅 / 售卖方式</Label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {skuOptions.map((sku) => {
                        const active = group.selectedSku?.id === sku.id
                        return (
                          <button
                            key={sku.id}
                            type="button"
                            onClick={() => onSelectSku(sku)}
                            className={
                              'flex items-center justify-between gap-2 px-3 py-2 rounded border text-sm transition-colors ' +
                              (active
                                ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                                : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                            }
                          >
                            <div className="text-left">
                              <div className="font-medium">
                                {sku.doorWidth || '默认规格'}
                              </div>
                              <div className="text-xs text-neutral-400 mt-0.5">
                                库存 {sku.stock ?? 0}
                              </div>
                            </div>
                            <span className="text-sm font-semibold">
                              ¥{Number(sku.price).toFixed(2)}
                            </span>
                          </button>
                        )
                      })}
                    </div>
                    {errSpec && <p className="mt-1.5 text-sm text-red-600">{errSpec}</p>}
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* **售卖形态**（issue #4493，用户裁定）——放在**商品公共属性区**：
            它和「商品 / 颜色 / 门幅」一起定义「这一组是什么、怎么卖」，而且**决定这一组下面出什么**
            （布料 ⇒ 没有部位行）。同一块布既能按米卖、也能做成帘 ⇒ 组级，不是行级、也不是商品属性。 */}
        {group.product && (
          <div className="mb-4">
            <Label required>售卖形态</Label>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="售卖形态">
              {([SALE_FORM_FINISHED, SALE_FORM_FABRIC] as SaleForm[]).map((form) => {
                const active = group.saleForm === form
                return (
                  <button
                    key={form}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => onChangeSaleForm(form)}
                    className={
                      'h-9 px-3 rounded border text-sm transition-colors ' +
                      (active
                        ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                        : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                    }
                  >
                    {form}
                  </button>
                )
              })}
            </div>
            <p className="mt-1.5 text-xs text-neutral-400">
              {group.saleForm === SALE_FORM_FABRIC
                ? '布料：按米卖，没有加工（不出现宽高 / 工艺规格 / 加工项，也不生成加工单）'
                : '成品帘：做成帘，需要宽高 / 工艺规格与加工项'}
            </p>
          </div>
        )}

        {/* **帘体**（issue #4521；#4874 收窄为两档）——**商品组级**，与售卖形态同层：
            它决定这条明细行的**部位**（`curtainType`：布帘缺省不写 / 纱帘显式写 —— 工序路线的
            索引键）与**落库几行**（各一行；「布 + 纱」= 两个商品组）。
            ⚠️ **用料算法与帘体无关**（2026-09-21 用户裁定：纱帘与布帘**完全一致**）——
            两种帘体走同一条算料链路，这里不再有「哪种不算料」的分支。
            取代了原来的「部位」字段与「新增部位」按钮 —— 那两者让商家能选出**自相矛盾**的组合。 */}
        {group.product && group.saleForm !== SALE_FORM_FABRIC && (
          <div className="mb-4">
            <Label required>帘体</Label>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="帘体">
              {CURTAIN_BODY_OPTIONS.map((body) => {
                const active = group.curtainBody === body
                return (
                  <button
                    key={body}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => onChangeCurtainBody(body)}
                    className={
                      'h-9 px-3 rounded border text-sm transition-colors ' +
                      (active
                        ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                        : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
                    }
                  >
                    {body}
                  </button>
                )
              })}
            </div>
            <p className="mt-1.5 text-xs text-neutral-400">
              {/* ⚠️ issue #4874：「布帘+纱帘」档已整体移除 ⇒ 这里不再有那一档的说明文案。
                  ⚠️ 2026-09-21 口径反转：**两种帘体用料算法完全一致** ⇒ 说明文案不再分叉
                  （原「纱帘：买多少填多少（不自动算料）」已删除）。 */}
              按所选用料公式自动算用料米数（布帘 / 纱帘同一算法）
            </p>
          </div>
        )}

        {group.saleForm === SALE_FORM_FABRIC ? (
          /* 布料单（issue #4493）：只有 米数 / 单价 —— 没有宽高、工艺规格、部位、加工项 */
          <FabricRow
            line={group.lines[0]}
            errors={errors}
            onChangeQty={(q) => onChangeQty(group.lines[0].id, q)}
            onChangePrice={(v) => onChangePrice(group.lines[0].id, v)}
          />
        ) : (
          /* 一套帘（issue #4521）：一个商品组 = 一套帘 ⇒ 只渲染**一份** ①~④。
             「新增部位」已移除（用户裁定「移除部位功能，其实完全不需要」）——
             需要纱帘时改**帘体**，不是再加一行。 */
          <div className="space-y-3">{renderPosition(group.lines[0])}</div>
        )}
      </div>
      )}
    </div>
  )
}

function LineItemBlock({
  line,
  errors,
  processingLoading,
  onChangeQty,
  onRestoreFormula,
  onChangePrice,
  onChangeWidth,
  onChangeHeight,
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
}: LineItemBlockProps) {
  /** 当前展开的**向导步骤**（issue #4511 手风琴）：1 尺寸与数量 / 2 工艺规格 / 3 加工项 / 4 特殊选项 */
  const [openStep, setOpenStep] = useState(1)
  /**
   * 加工项**一级分类导航 + 关键字搜索**（issue #4576）—— 纯**展示态**。
   *
   * ⚠️ 与勾选态（`line.selectedProcessing`）**严格分离**：过滤只影响**渲染**，
   * 被过滤掉但仍勾选的项**照样**计入已选摘要与提交 payload（`processingDetailsOf` 只读勾选态）。
   * 这里**没有**第二份勾选状态，也**没有**第二套落库路径。
   */
  const [activeCategoryId, setActiveCategoryId] = useState('')
  const [processingQuery, setProcessingQuery] = useState('')
  const stepProps = (n: number) => ({
    open: openStep === n,
    onToggle: () => setOpenStep(openStep === n ? 0 : n),
  })
  const selectedProcessingCount = Object.values(line.selectedProcessing).filter(
    (c) => c.selected
  ).length
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
   */
  const derivedOptions = derivedSpecialOptionsOf(derivedOptionInputOf(line))
  const effectiveOptions = effectiveSpecialOptionsOf(derivedOptionInputOf(line))
  /** 一个推导项在本行的**状态**（面板与落库共用同一判定 ⇒ 不可能各说各话） */
  const derivedOptionState = (name: string): 'manual' | 'merged' | 'rejected' =>
    (line.craft.specialOptions ?? []).includes(name)
      ? 'manual' // 商家在②特殊选项里手工勾过 ⇒ 人工优先
      : effectiveOptions.includes(name)
        ? 'merged'
        : 'rejected'
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
   * 「改」入口的展开态（issue #5202）：`null` = **跟随默认** —— 推导没就绪（`plan === null`）时
   * **默认展开**（人工兜底是唯一出路，收起会让商家无从下手），推导就绪后默认收起（三项输入收敛）。
   * 商家点过之后就按他点的来（不再被推导到达 / 消失牵动）。
   */
  const [craftEditTouched, setCraftEditTouched] = useState<boolean | null>(null)
  const craftEditOpen = craftEditTouched ?? plan === null
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
  /** 未定价 **且组合键非空** ⇒ 可就地改单价 */
  const canOverrideFee = feeIsUnpriced && feeCompositionKey !== ''
  /**
   * 该行**有没有任何选配**（手选加工项 ∪ 自动识别特征）—— 没有 ⇒ 组合键必然为空，
   * 「加工费组合」块整块不渲染（无组合可展示、也无价可改），与「缺选配信息」是两回事。
   */
  const hasAnyProcessingSelection = processingDetailsOf(line).length > 0

  /**
   * ① 尺寸行旁的**就地徽标**（issue #4658）—— 生效特征名 + （门幅走了默认值时的）提示。
   *
   * 与 ②「系统识别」块**读同一份** `autoFeatures`（同一**服务端判定**结果，issue #4976 包 2b ⇒
   * 严禁第二份推导实现）。被**不采纳**的不出现在徽标里（徽标 = 生效值）。
   */
  const sizeAutoBadges =
    !isFabricLine && (autoFeatures.length > 0 || doorWidthMissing) ? (
      <span data-testid="size-auto-badges" className="flex items-center gap-1 shrink-0">
        {autoFeatures.map((row) => (
          <span
            key={row.name}
            data-testid={`size-auto-badge-${row.name}`}
            title={row.reason}
            className="rounded border border-amber-200 bg-amber-50 px-1 text-[10px] leading-4 text-amber-700"
          >
            {row.name}
          </span>
        ))}
        {doorWidthMissing && (
          <span
            data-testid="size-door-width-missing"
            title="该 SKU 未维护门幅 —— 系统不按缺省门幅推算（分幅与加工类型判不了；超高/超宽是按净窗宽高与企业阈值判的）"
            className="rounded border border-neutral-300 bg-neutral-100 px-1 text-[10px] leading-4 text-neutral-500"
          >
            门幅未维护
          </span>
        )}
      </span>
    ) : null

  const errQty = errors[`line_${line.id}_quantity`]
  const errPrice = errors[`line_${line.id}_unitPrice`]
  const errWidth = errors[`line_${line.id}_width`]
  const errHeight = errors[`line_${line.id}_height`]

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
              title="尺寸与数量 · 工艺规格"
              badges={sizeAutoBadges}
              summary={`${summarySize} · ${line.quantity} 米 · ${formatAmount(Number(line.unitPrice) || 0)}/米 · ${summarySpec || '按行业默认'}`}
              {...stepProps(1)}
            >
            {/* 尺寸与数量（issue #4420 分区①）：宽 / 高 必填 + 数量 / 单价 */}
            <div className="pt-3 border-t border-neutral-100">
              <p className="mb-3 text-xs text-neutral-400">
                宽 / 高按<strong>窗户净尺寸</strong>填，单位米（成品宽 = 窗宽、成品高 = 窗高）——
                <strong>一套帘共用一份尺寸</strong>（同一商品组内主布与纱帘同宽同高）
              </p>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <div>
                  <Label required>窗宽 (米)</Label>
                  {/* 三项输入之一（issue #5202）；数字框能打出 `0.`（如 0.5 米窄窗） */}
                  <NumberInput
                    value={line.width}
                    onChange={(next) => onChangeWidth(positiveOrNull(next))}
                    decimals={3}
                    placeholder="如 6.6"
                    aria-label="窗宽 (米)"
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errWidth && <p className="mt-1 text-sm text-red-600">{errWidth}</p>}
                </div>
                <div>
                  <Label required>窗高 (米)</Label>
                  {/* 三项输入之一（issue #5202） */}
                  <NumberInput
                    value={line.height}
                    onChange={(next) => onChangeHeight(positiveOrNull(next))}
                    decimals={3}
                    placeholder="如 2.6"
                    aria-label="窗高 (米)"
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errHeight && <p className="mt-1 text-sm text-red-600">{errHeight}</p>}
                </div>
                <div>
                  {/* label = 「用料米数」（issue #4598）：这个输入框的值**就是加工费米数**
                      （`info.processingMeters = line.quantity`，加工费 = 组合单价 × 它），
                      而它的值本身由算料写回（`fabric_meters`）—— 叫「数量」会被商家读成「买几套」。
                      ⚠️ 布料行（`FabricRow`）**不改**：布料按 `sellingMethod` 卖布，不是同一个业务。 */}
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
                  {/* issue #4598：把口径写在旁边 —— 商家一眼对得上加工费是按哪个数算的 */}
                  <p className="mt-1 text-xs text-neutral-400">= 加工费米数</p>
                  {/* 算料来源与公式（issue #4434）—— 公式串**原样渲染后端产出**，前端不自拼。
                      ⚠️ 2026-09-21 口径反转：纱帘与布帘**用料算法完全一致** ⇒ 原「纱帘按实际买多少填，
                      不自动算料 / 没有公式可恢复」的专属分支已删除（两种帘体走同一条渲染路径：
                      公式串 /「人工指定 + 恢复按公式计算」/ 算料错误提示一律一视同仁）。 */}
                  {line.metersSource === LINE_METERS_SOURCE_MANUAL ? (
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
                          不静默覆盖商家手填的数，也不让商家自己猜为什么数没变（一键恢复就在上面）。 */}
                      {metersStale && (
                        <p data-testid="meters-manual-stale" className="mt-1 text-xs text-amber-700">
                          用料已人工指定（{line.quantity} 米）—— 宽 / 高 / 门幅或工艺改动后系统
                          <strong>未跟随</strong>重算（不会静默覆盖你手填的数）；点上方「恢复按公式计算」
                          按新参数重算。
                        </p>
                      )}
                    </>
                  ) : line.calc?.formula_text ? (
                    <p className="mt-1 text-xs text-neutral-400 break-words">
                      {line.calc.formula_text}
                    </p>
                  ) : null}
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
            </div>

              {/* ===== 推导结果（issue #5202；契约 #5200 §四）=====
                  商家**主动填的只有三项**（颜色 + 净窗宽 + 净窗高）⇒ 加工类型 / 分幅 / 拼接 /
                  接高 / 接宽 / 用料一律**只读展示**服务端推导（`data.plan`）；要改走下面「改工艺参数」
                  入口（裁定 6：自动推导的工艺配置仍然能人工修改，改过留痕、不再被覆盖）。
                  `reason` 与**候选逐条**（含不可行的）都摆出来：裁定 3 要系统逐个「再算一遍」，
                  商家要能核对判定。 */}
              {!isFabricLine && line.calc && (
                <div
                  data-testid="craft-plan"
                  className="mt-3 rounded border border-neutral-200 bg-neutral-50/60 px-3 py-2"
                >
                  {plan ? (
                    <>
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs">
                        <span className="font-medium text-neutral-600">用料方案（系统推导）</span>
                        <span data-testid="craft-plan-mode" className="text-neutral-900">
                          加工类型：{plan.cutting_mode}
                        </span>
                        <span data-testid="craft-plan-source" className="text-neutral-500">
                          {plan.auto ? '系统推导' : '人工指定（不再被自动改判）'}
                        </span>
                        {/* 工艺**不在** `plan` 里（没有几何依据）：一律「系统默认 · 可改」—— 
                            真值路径 = ③加工项里勾带 `craft_hint` 的工艺项（#4566）。 */}
                        <span data-testid="craft-plan-craft" className="text-neutral-500">
                          工艺 {lineCraft ?? `${DEFAULT_CRAFT_NAME}（系统默认，可在③加工项改）`}
                        </span>
                        <span data-testid="craft-plan-door-width" className="text-neutral-500">
                          门幅 {plan.door_width ?? '—'} 米
                        </span>
                        <span data-testid="craft-plan-panels" className="text-neutral-500">
                          分幅 {plan.panels ?? '—'}
                        </span>
                        <span data-testid="craft-plan-splice" className="text-neutral-500">
                          拼接 {spliceOption ?? craftPlanSpliceText(plan)}
                          {spliceOption !== null
                            ? derivedOptionState(spliceOption) === 'merged'
                              ? '（已并入特殊选项 ⇒ 插工序 + 计件）'
                              : derivedOptionState(spliceOption) === 'manual'
                                ? '（你在②特殊选项里手工勾过 ⇒ 人工优先）'
                                : '（已忽略：不插工序、不计件）'
                            : ''}
                        </span>
                        <span data-testid="craft-plan-join-height" className="text-neutral-500">
                          接高 {plan.join_height_m ?? '—'} 米
                        </span>
                        <span data-testid="craft-plan-join-width" className="text-neutral-500">
                          接宽 {plan.join_width_m ?? '—'} 米
                        </span>
                        <span
                          data-testid="craft-plan-meters"
                          className="font-medium text-neutral-900"
                        >
                          用料 {plan.meters} 米
                        </span>
                      </div>
                      <p data-testid="craft-plan-reason" className="mt-1 text-[11px] text-neutral-500">
                        依据：{plan.reason}
                      </p>
                      {/* **推导出的特殊选项**（拼N次 / 接高；issue #5211）—— 它们会进
                          `processingInfo.specialOptions` ⇒ 服务端**插工序**（`拼2次-布` / `接高-布`）
                          + **计件**（0.8/1.2/1.6、1.0 元/幅）⇒ 推导错 = 多插一道工序、多算工钱
                          ⇒ 必须**可见可撤**（同自动识别特征的 #4657 纪律：推导可裁决，不留暗箱）。
                          ⚠️ 接宽不在此列（issue #5214：全仓无该选项/工序出口，不给它造口径）。 */}
                      {derivedOptions.length > 0 && (
                        <div data-testid="craft-plan-derived-options" className="mt-1.5 space-y-0.5">
                          {derivedOptions.map((name) => {
                            const state = derivedOptionState(name)
                            return (
                              <p
                                key={name}
                                data-testid={`craft-plan-derived-option-${name}`}
                                className="text-[11px] text-neutral-500"
                              >
                                「{name}」
                                {state === 'manual'
                                  ? '：你在②特殊选项里手工勾过 ⇒ 人工优先'
                                  : state === 'merged'
                                    ? '：已并入特殊选项（⇒ 插工序 + 计件）'
                                    : '：已忽略（手工剔除）—— 不插工序、不计件'}
                                {state === 'merged' && (
                                  <button
                                    type="button"
                                    data-testid={`craft-plan-derived-reject-${name}`}
                                    onClick={() => onDerivedOptionDecision(name, 'reject')}
                                    className="ml-1.5 text-neutral-500 underline hover:text-neutral-700"
                                  >
                                    不采纳
                                  </button>
                                )}
                                {state === 'rejected' && (
                                  <button
                                    type="button"
                                    data-testid={`craft-plan-derived-adopt-${name}`}
                                    onClick={() => onDerivedOptionDecision(name, 'adopt')}
                                    className="ml-1.5 text-primary-600 underline hover:text-primary-700"
                                  >
                                    采纳
                                  </button>
                                )}
                              </p>
                            )
                          })}
                        </div>
                      )}
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
                    </>
                  ) : (
                    <p data-testid="craft-plan-unavailable" className="text-xs text-amber-700">
                      推导服务未就绪：算料响应没有返回推导方案（`data.plan`）—— 加工类型 / 拼接 /
                      接高接宽请人工确认（系统不会自行猜一个方案）。
                    </p>
                  )}
                </div>
              )}

              {/* 工艺参数（原 ②，已并入区块 1）—— §4.2 字段表 A + §4.8 双拼
                  + **就地「改」入口**（issue #5202 · 裁定 6）：默认收起，推导结果在上一块只读展示 */}
              <div className="pt-4 mt-4 border-t border-neutral-100">
                <button
                  type="button"
                  data-testid="craft-plan-edit"
                  aria-expanded={craftEditOpen}
                  onClick={() => setCraftEditTouched(!craftEditOpen)}
                  className="h-8 px-3 rounded border border-neutral-300 bg-white text-xs text-neutral-600 hover:border-neutral-400 transition-colors"
                >
                  {craftEditOpen ? '收起工艺参数' : '改工艺参数 / 人工加接高接宽拼接'}
                </button>
                {craftEditOpen && (
                  <div className="mt-3">
                <OrderCraftFields
                  value={derivedCraftSpec(line, calcConfig)}
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

              {/* **系统识别**（issue #4658：从 ③加工项 移到 ②工艺规格）—— 为什么归这里：
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
                        接宽只在「倒幅」下成立（契约订正 v1.1 ③）。 */}
                    <div
                      data-testid="craft-plan-manual"
                      className="rounded border border-neutral-200 bg-white px-3 py-2"
                    >
                      <div className="text-xs font-medium text-neutral-600">
                        人工加 / 改（改过的项不再被自动推导覆盖）
                      </div>
                      <div
                        className="mt-2 flex flex-wrap items-center gap-1.5"
                        role="radiogroup"
                        aria-label="拼接（人工加）"
                      >
                        <span className="text-xs text-neutral-500">拼接</span>
                        {SPLICE_OVERRIDE_OPTIONS.map((option) => {
                          const active =
                            (line.planOverrides?.spliceTimes ?? null) ===
                            (option.value ?? null)
                          return (
                            <button
                              key={option.label}
                              type="button"
                              role="radio"
                              aria-checked={active}
                              onClick={() => onChangePlanOverrides({ spliceTimes: option.value })}
                              className={
                                'h-8 px-3 rounded-full border text-xs transition-colors ' +
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
                )}
              </div>
            </WizardStep>

            {/* ② **加工项 · 特殊选项**（issue #4874 两步化：区块 2 = 加工项 + 特殊选项）
                —— 用户 2026-09-21：「另外两个（加工项 + 特殊选项）合并」。 */}
            <WizardStep
              step={2}
              title="加工项 · 特殊选项"
              summary={
                // #4576：摘要里带上**工艺**（哪一项），不再让商家回头数；计数口径不变（仍只数**手选**项）
                // #4874：并入 ④特殊选项 ⇒ 摘要合并（未选特殊选项时不出现那一段，不留「· 特殊选项 0 项」噪音）
                (selectedProcessingCount > 0
                  ? `已选 ${selectedProcessingCount} 项${lineCraft ? ` · 工艺：${lineCraft}` : ''}`
                  : '未选') +
                ((line.craft.specialOptions ?? []).length > 0
                  ? `${selectedProcessingCount > 0 ? ' · ' : ''}特殊选项 ${(line.craft.specialOptions ?? []).length} 项`
                  : '')
              }
              {...stepProps(2)}
            >
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

              {/* ===== **加工费组合**明细块（issue #4874）=====
                  用户 2026-09-21：「订单中加工费组合**未配置**的情况下，**允许更改该单价**，
                  并且在**加工项下面添加具体的组合名**」。
                  逐行 = 组合名（`feeDetail.items.join(' + ')`，与「加工费组合」页**逐字同源**）
                  + 单价（元/米）+ 来源 + 操作；单价与来源**只读**，未定价行给「改单价」输入。
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
                    <span className="text-neutral-400">单价</span>
                    {/* 改单价入口的**两条准入**（缺一不可；issue #4878 独立复核 P1 补第二条）：
                        ① 本行组合**未定价** ∧ 组合键非空（原本的唯一准入）；
                        ② 本行**已经带着商家输入的 override** —— 改价后预览会返回 `fee_source='manual'`
                           ⇒ `feeIsUnpriced` 变 false ⇒ 若只按 ① 渲染，输入框**当场消失**：
                           商家打错一个字就再也改不了（唯一出路是把售卖形态切到布料再切回来，
                           而那会连带清空尺寸/工艺）。⇒ **override 是商家输的，入口就一直在**。 */}
                    {(feeIsUnpriced && canOverrideFee) || line.processingFeeOverride != null ? (
                      <span className="inline-flex items-center gap-1">
                        <NumberInput
                          data-testid="fee-unit-price-override"
                          aria-label="改单价（元/米）"
                          placeholder="元/米"
                          value={line.processingFeeOverride}
                          onChange={(next) => onProcessingFeeOverrideChange(positiveOrNull(next))}
                          decimals={3}
                          className="w-24 h-8 px-2 rounded border border-neutral-300 text-xs focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                        />
                        <span className="text-neutral-500">元/米</span>
                      </span>
                    ) : feeIsUnpriced ? (
                      <span className="text-amber-600">未定价</span>
                    ) : (
                      <span
                        data-testid="fee-unit-price"
                        className="text-neutral-700 tabular-nums"
                      >
                        {Number.isFinite(feeUnitPrice) ? `${formatAmount(feeUnitPrice)}/米` : '—'}
                      </span>
                    )}
                    <span className="text-neutral-400">
                      来源：
                      {feeSource !== '' ? FEE_SOURCE_LABELS[feeSource] ?? feeSource : '—'}
                    </span>
                    {/* 缺选配信息（组合键为空）⇒ **不给**改单价入口：没有 key 可同步 */}
                    {feeIsUnpriced && !canOverrideFee && (
                      <span data-testid="fee-combination-no-composition" className="text-amber-600">
                        缺选配信息 ⇒ 没有组合键可同步，无法就地改单价
                      </span>
                    )}
                    {/* 定价入口（与页面既有告警同一路径；已定价行无需它） */}
                    {feeIsUnpriced && (
                      <Link
                        href={PRICING_ENTRY}
                        className="text-primary-600 underline underline-offset-2 hover:text-primary-700"
                      >
                        去「加工费组合」定价
                      </Link>
                    )}
                  </div>
                </div>
              )}

              {/* 特殊选项（原向导 ④，已并入区块 2）—— issue #4511：从工艺规格里抽出来，与加工项平级 */}
              <div className="pt-4 mt-4 border-t border-neutral-100">
                <OrderExtraOptions
                  value={line.craft.specialOptions}
                  onChange={(next) => onChangeCraft({ specialOptions: next })}
                />
              </div>
            </WizardStep>

      </div>
    </div>
  )
}

// ====== 工具函数 ======
function uniqueColors(skus?: OrderProductSku[]): Array<{ id: string; name: string }> {
  const map = new Map<string, string>()
  ;(skus || []).forEach((s) => {
    if (s.colorId != null) map.set(s.colorId, s.colorName || `颜色${s.colorId}`)
  })
  return Array.from(map.entries()).map(([id, name]) => ({ id, name }))
}

// ====== 内联小组件 ======
function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-6 h-6 rounded bg-primary-50 text-primary-600 inline-flex items-center justify-center">
        {icon}
      </span>
      <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
    </div>
  )
}

function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block text-sm font-medium text-neutral-700 mb-1.5">
      {children}
      {required && <span className="text-red-500 ml-1">*</span>}
    </label>
  )
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-neutral-500">{label}</span>
      <span className={highlight ? 'text-orange-600 font-medium' : 'text-neutral-800'}>{value}</span>
    </div>
  )
}

/**
 * 一行**可核对的算式**（issue #4420）：左 = 「数量 单位 × 单价」，右 = 金额。
 *
 * 为什么要把算式显式写出来：用户口径「需要额外把计算公式体现出来，比如
 * 展示窗帘米数 × 组合加工费 = 具体费用」—— 只给金额时，商家对不上报价单与加工单，
 * 也无从判断系统算得对不对（#4118 的「双算」正是靠这种不透明活下来的）。
 */
function CostRow({
  label,
  expr,
  amount,
  amountLabel,
}: {
  label: string
  expr: string
  amount: number
  /** 覆盖金额那格（未定价 ⇒ 「未定价」，**不得**渲染成 `¥0.00` —— 仓库硬纪律） */
  amountLabel?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-neutral-500 truncate">
        <span className="text-neutral-400">{label}</span>
        <span className="ml-1.5 tabular-nums">{expr}</span>
      </span>
      <span
        className={
          amountLabel
            ? 'text-amber-600 shrink-0'
            : 'text-neutral-700 tabular-nums shrink-0'
        }
      >
        {amountLabel ?? formatAmount(amount)}
      </span>
    </div>
  )
}

