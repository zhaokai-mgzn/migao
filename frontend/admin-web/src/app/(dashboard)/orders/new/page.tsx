'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ChevronDown, ChevronRight, Ruler, Search, Package, User, Receipt, Settings2, Plus, Trash2, UserPlus, Phone, MapPin } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { orderApi, productApi, customerApi, processingItemApi, craftCalcApi, feePreviewApi, type CraftCalcResult, type CraftCalcParams, type FeePreviewResult } from '@/lib/api'
import { resolveImageUrl } from '@/lib/utils'
import { useOrderAmounts } from '@/hooks/useOrderAmounts'
import { Button, Card, Input, Modal } from '@/components/ui'
import OrderCraftFields from '@/components/orders/OrderCraftFields'
import OrderExtraOptions from '@/components/orders/OrderExtraOptions'
import {
  METERS_SOURCE_FORMULA,
  // 与配布边米数来源的 `METERS_SOURCE_MANUAL` 同值（都是「人工指定」）但**是另一个字段**
  // ⇒ 别名进来，避免两个来源的常量在同一文件里撞名（tsc 会直接报 duplicate identifier）。
  METERS_SOURCE_MANUAL as LINE_METERS_SOURCE_MANUAL,
  craftCalcErrorText,
  craftCalcParamsOf,
  craftCalcSignature,
  isAutoCalcUnavailable,
} from '@/lib/craft-calc-request'
import {
  COMPONENT_ROLE_EDGE,
  CURTAIN_BODY_BOTH,
  CURTAIN_BODY_CLOTH,
  CURTAIN_BODY_OPTIONS,
  CURTAIN_BODY_SHEER,
  CURTAIN_TYPE_SHEER,
  DEFAULT_CUTTING_MODE,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  STYLE_MIXED,
  bodyHasSheerLine,
  buildCraftSpec,
  buildEdgeLineCraftSpec,
  buildMainLineGroupKeys,
  buildSheerLineCraftSpec,
  createDefaultCraftSpec,
  curtainTypeOfBody,
  defaultIsShapedForBody,
  type CraftSpecInput,
  type CurtainBody,
} from '@/lib/order-craft-fields'
import { describeLogisticsProfile } from '@/lib/logistics'
// D6 自动识别（issue #4526 · 设计 §5.1/§5.2）：超高/超宽 = 宽高 vs 门幅；倒幅/正幅 = cuttingMode 推导
// ⚠️ 取自 **admin-web 专属**模块（不是三端同源的 `craft-display`，见该文件头）
import { detectAutoFeatures, type AutoFeature } from '@/lib/craft-auto-features'
// 费用明细的「加工 + 特殊选项」两半拆分（issue #4526 · 设计 §4.3 / 判据 5）——唯一实现
import { buildFeeDetailDisplay } from '@/lib/order-fee-display'
// #4371：加工项类型改为**店铺级目录**的 `ProcessingItem`（旧 `ProductProcessingItem` 已随解耦删除）
import type { Product, ProcessingItem, OrderItemFormData, Customer } from '@/types'

interface OrderProductSku {
  id: string
  productId?: string
  colorId: string
  colorName?: string
  sellingMethod?: string
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
   * 售卖形态（issue #4493）——**商品组级**属性：同一块布按米卖还是做成帘。
   * 存在行上、由组级处理器在组内同步（与颜色 / 门幅同一机制）。
   */
  saleForm: SaleForm
  /**
   * **帘体**（issue #4521）—— 用户口径四类购买情况里的前三类：
   * `布帘`（用料按韩折公式算）/ `纱帘`（**买多少填多少，不算料**）/ `布帘+纱帘`（两条明细行）。
   *
   * **组级**（与 `saleForm` 同一机制、组内同步）：一个商品组 = 一樘帘 —— 改帘体不该只改一半
   * （主布行按公式算了料、纱帘行还留着）。
   */
  curtainBody: CurtainBody
  quantity: number
  unitPrice: number
  /**
   * 成品宽 / 高（米，**部位级**）—— issue #4420，用户 2026-09-19 裁定「宽高必填」。
   *
   * ⚠️ 归属层级：`position-instance-routing-model.md` §5.9.2 已裁定宽高是**部位级**
   * （一樘「布 + 纱」的布帘与纱帘高度常不同，共用一行宽高必有一个部位的高度是错的）。
   * 本页一行 = 一个部位（裁定 R-a）⇒ 行级即部位级，语义一致。
   */
  width: number | null
  height: number | null
  processingItems: ProcessingItem[]
  selectedProcessing: Record<string, { selected: boolean; qty: number }>
  /** 工艺规格录入（issue #4375 §4.2/§4.5）—— 未填的键不落库；三条默认档见 createDefaultCraftSpec */
  craft: CraftSpecInput
  // ── 「樘窗」输入已移除（issue #4486，用户裁定「我感觉不需要」）──
  // 代价已如实登记：商家手工路径不再能跨行绑樘窗 ⇒ 布 + 纱会算成 2 樘窗 ⇒ 套级工序
  // （外帘打卷/装袋/发货）各实例化 2 次（计件工资双付，约 ¥3/樘）。见 issue #4486。
  // ⚠️ **底层机制保留**：`lib/order-craft-fields.ts` 的 `resolveWindowCraftLineIds` /
  // `buildWindowGroupKey` 与消费端 `ProcessingOrderService` 一字未动（API / Agent 仍可写该键）；
  // 且 **`craftLineId` 仍用于配布边配对**（§4.8 主布行 + 配布边行），见 `buildLineProcessingInfo`。
  /** 配布边米数（§4.8）；`null` = 未改过 ⇒ 跟随主布米数 */
  edgeMeters: number | null
  /** 配布边单价；`null` = 未填 ⇒ 不生成配布边明细行（后端单价必须 > 0，不凭空造价） */
  edgeUnitPrice: number | null
  /**
   * 纱帘米数（issue #4521）；`null` = 未改过 ⇒ 跟随主布米数。
   * 只有帘体含**纱帘明细行**（`bodyHasSheerLine` = 布帘+纱帘）时有意义。
   */
  sheerMeters: number | null
  /** 纱帘单价；`null` = 未填 ⇒ 不生成纱帘明细行（后端单价必须 > 0，不凭空造价） */
  sheerUnitPrice: number | null
  /**
   * 商家**手改过**打开方式（issue #4493 的宽→开数联动）——落在**行状态**里，
   * 不放组件内 state（收起/展开重挂不丢）。手改过 ⇒ 改宽**不得覆盖**。
   */
  openCountTouched: boolean
  /**
   * 商家**手改过**是否定型（issue #4521，承接 #4489 的「手改留痕」纪律）——
   * 落在**行状态**里（同 `openCountTouched`）。手改过 ⇒ 改帘体**不得覆盖**。
   */
  isShapedTouched: boolean
  /**
   * 用料米数来源（真值源 §8：折数/用料**必须带来源**，防多渠道不一致）—— issue #4434。
   * `公式计算` = 由算料引擎试算预填（宽/高/开数/拼次变化时自动重算）；
   * `人工指定` = 商家手改过 ⇒ **试算不得静默改回**（只有显式「恢复按公式计算」才切回）。
   */
  metersSource: string
  /** 最近一次算料试算结果（含**后端产出**的公式串）—— `null` = 还没算过 */
  calc: CraftCalcResult | null
  /** 试算失败原因（行内显式提示；**不退回任何估算值**） */
  calcError: string | null
}

const sellingMethodLabel: Record<string, string> = {
  bulk_cut: '散剪',
  full_roll: '整卷',
  per_meter: '按米',
  per_piece: '按件',
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

/** 正小数输入：空串 / 非法 / 非正 ⇒ `null`（宽高必填由提交校验拦，不在这里造 0） */
function decimalOrNull(raw: string): number | null {
  if (raw.trim() === '') return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

// 加工项数量规则（issue #3005 回滚 #2986）：行业加工费按米计价、辅料含在加工费中，
// 无 per_piece/每米数量密度——per_meter → 数量=面料米数；per_set/fixed/per_area → 1
function deriveProcessingQty(pi: ProcessingItem, fabricMeters: number): number {
  const method = pi.pricingMethod
  if (method === 'per_meter') return Math.max(1, fabricMeters)
  return 1
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
 * 该行的**自动识别特征**（issue #4526 · 设计 §5.1/§5.2）—— 纯推导，**不是可勾选项**。
 *
 * 用户 2026-09-19：「超高 / 超宽是和门幅标准比较的……**这个要求做到自动识别**」。
 * 门幅取 SKU 的 `doorWidth`（缺省 2.8）；倒幅/正幅由 `cuttingMode` 唯一推导。
 *
 * ⚠️ 这些特征**进组合键**（R9：`打孔+超高+定型` 与 ERP 逐字同构）⇒ 与手选加工项一起落
 * `processingInfo.processingItems`（服务端的特征名唯一来源就是它），但**不计入手选计数**、
 * 也不在手选列表里出 checkbox（判据 8：手选项 ⇒ 红）。
 */
function autoFeaturesOf(line: OrderLineItem): AutoFeature[] {
  return detectAutoFeatures({
    width: line.width,
    height: line.height,
    doorWidth: line.selectedSku?.doorWidth,
    cuttingMode: line.craft.cuttingMode,
    isShaped: line.craft.isShaped,
  })
}

/** 该行已勾选的加工项明细（提交 payload 与加工费预览**共用**这一份构造） */
function processingDetailsOf(line: OrderLineItem): Array<Record<string, unknown>> {
  const handPicked = Object.entries(line.selectedProcessing)
    .filter(([, v]) => v.selected)
    .map(([piId, v]) => {
      const pi = line.processingItems.find((p) => p.id === piId)
      if (!pi) return null
      const unit = Number(pi.unitPrice) || 0
      const qty = Math.max(1, Number(v.qty) || 1)
      return {
        id: pi.id,
        name: pi.name,
        unitPrice: unit,
        quantity: qty,
        unit: pi.unit,
        pricingMethod: pi.pricingMethod,
        subtotal: unit * qty,
      }
    })
    .filter(Boolean) as Array<Record<string, unknown>>

  // 自动识别特征（R9/D6）：与手选加工项**同一数组** —— 服务端 `featureNames` 只读
  // `processingItems[].name`（`ProcessingFeeQueryService.featureNames`），不在这里带上
  // ⇒ 组合键里永远没有超高/超宽/倒幅 ⇒ 组合价目匹配不到（设计 §5.3 特征集合）。
  // 它们**没有单价**（不在加工项目录里）：单价恒 0，钱由**组合价目**决定（R10 的前提）。
  const derived = autoFeaturesOf(line).map((feature) => ({
    name: feature.name,
    unitPrice: 0,
    quantity: 1,
    subtotal: 0,
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
function buildLineProcessingInfo(line: OrderLineItem): Record<string, unknown> | undefined {
  const sku = line.selectedSku
  const colorName = uniqueColors(line.product?.skus).find(
    (c) => c.id === line.selectedColorId
  )?.name
  const processingDetails = processingDetailsOf(line)

  // 工艺规格落库（issue #4375 §4.2/§4.5）：只落用户真填了的键（缺值不写）。
  // 拼色（双拼）时主布行额外绑组（§4.8）：componentRole=主布 + craftLineId。
  // ⚠️ **樘窗跨行分组已移除**（issue #4486，用户裁定）：不再写 `buildWindowGroupKey`。
  //    但 **`craftLineId` 自指仍保留** —— 它是 §4.8「配布边行被主布行吸收」的配对键
  //    （消费端 `isAbsorbedEdgeRow` 按组键判定），删了配布边行会独立成部位。
  // **布料单无加工**（issue #4493，用户裁定）：不写任何工艺规格、不写加工项。
  // ⇒ 下游（订单详情 / 加工单）的「工艺规格」块自然不出现，且加工单不会被生成
  //   （`ProcessingOrderService` 以「无加工项」拦），与既有链路零冲突。
  const isFabric = line.saleForm === SALE_FORM_FABRIC
  const edgePrice = isFabric ? null : edgeUnitPriceOf(line)
  const sheerPrice = isFabric ? null : sheerUnitPriceOf(line)
  // **有同行件**（配布边 / 纱帘）时主布行才写绑组键（issue #4521 把纱帘纳入同一口径）：
  // 两行必须共用**同一个客户端行标识**，否则消费端 `craftGroupKey` 按各自 `itemId` 成组
  // ⇒ 一樘帘被算成两樘 ⇒ 套级工序（外帘打卷/装袋/发货）实例化两次、计件双付（#4395 的病根）。
  const isPaired = edgePrice !== null || sheerPrice !== null
  // 部位（issue #4521）：主帘缺省即布帘 ⇒ **不写**；只有「只买纱帘」显式写 `curtainType=纱帘`
  // （它是**另一个部位** —— 不写就会被下游当成布帘，取到错的工序路线）。
  const curtainType = isFabric ? undefined : curtainTypeOfBody(line.curtainBody)
  const mainSpec = isFabric
    ? {}
    : {
        ...buildCraftSpec(line.craft),
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
    sellingMethod: sku?.sellingMethod,
    doorWidth: sku?.doorWidth,
    ...(isFabric ? {} : { processingItems: processingDetails }),
    ...mainSpec,
  }

  // 加工费米数（裁定 R-b：= 该樘窗**主布行**米数）+ 算料输出（#4273：输入与输出都要落）。
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
    const pi = line.processingItems.find((p) => p.id === piId)
    if (!pi) return
    next[piId] = { ...cfg, qty: deriveProcessingQty(pi, meters) }
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

function createEmptyLineItem(groupId: string = genId()): OrderLineItem {
  return {
    id: genId(),
    groupId,
    product: null,
    productLoading: false,
    selectedColorId: null,
    selectedSku: null,
    saleForm: SALE_FORM_FINISHED,
    // 帘体默认「布帘」（issue #4521）：不带纱帘的普通窗帘 = 绝大多数场景
    curtainBody: CURTAIN_BODY_CLOTH,
    quantity: 1,
    unitPrice: 0,
    width: null,
    height: null,
    processingItems: [],
    selectedProcessing: {},
    // 默认档（issue #4420/#4493/#4521）：工艺「韩褶」/ 加工类型「定高买宽」/ 款式「单色」/
    // 褶距 0.125 / 是否对花「否」/ 是否定型「是」（布帘默认）—— 都是**商家看得见的真值**
    craft: createDefaultCraftSpec(),
    edgeMeters: null,
    edgeUnitPrice: null,
    sheerMeters: null,
    sheerUnitPrice: null,
    openCountTouched: false,
    isShapedTouched: false,
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
 * 一个商品组 = 一樘帘，需要纱帘时由**帘体**（`curtainBody`）表达，而不是再加一行。
 * 落库仍可能是**两条**明细行（主布行 + 纱帘行），但那由帘体派生，不需要商家手工加行。
 */

/**
 * 纱帘**明细行**是否成立（issue #4521）：帘体 = **布帘+纱帘**（组合态）**且**填了纱帘单价。
 *
 * ⚠️ 「只买纱帘」不走这里：那一行本身就是纱帘（单价 = 该行 `unitPrice`），再生成一条 = 凭空多一行。
 *
 * 与配布边同一口径（`edgeUnitPriceOf`）：后端 `unitPrice` 带 `@Positive`（必须 > 0）
 * ⇒ 不填价就不生成行，**不凭空造价**。
 */
function sheerUnitPriceOf(line: OrderLineItem): number | null {
  if (!bodyHasSheerLine(line.curtainBody)) return null
  return line.sheerUnitPrice != null && line.sheerUnitPrice > 0 ? line.sheerUnitPrice : null
}

/** 纱帘米数：默认 = 主布米数（= 该行数量），可编辑（「买多少就是多少」是商家给定值） */
function sheerMetersOf(line: OrderLineItem): number {
  return line.sheerMeters ?? (Number(line.quantity) || 0)
}

/**
 * 算料试算的入参（**唯一装配点**）：`craftCalcParamsOf` 需要**部位**判「纱帘不算料」
 * （issue #4521），而部位在行上是从帘体派生的 ⇒ 在这里派生一次，两处调用共用。
 */
function calcInputOf(line: OrderLineItem) {
  return {
    width: line.width,
    height: line.height,
    craft: line.craft,
    curtainType: curtainTypeOfBody(line.curtainBody),
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
  /** 选中客户的常用物流档案（只读提示，issue #4419；发货页按同一档案带出方式/公司） */
  const [pickedLogisticsHint, setPickedLogisticsHint] = useState('')

  // 表单错误
  const [errors, setErrors] = useState<Record<string, string>>({})

  // ===== 加工项目录（店铺级，独立于商品）=====
  // issue #4371：加工项与商品解耦 —— 目录只加载一次，商品选择不再过滤/触发加工项请求
  const [processingCatalog, setProcessingCatalog] = useState<ProcessingItem[]>([])
  const [processingCatalogLoading, setProcessingCatalogLoading] = useState(false)

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
      prev.map((it) =>
        it.processingItems === processingCatalog ? it : { ...it, processingItems: processingCatalog }
      )
    )
  }, [processingCatalog, processingCatalogLoading])

  // ===== 行项更新工具 =====
  const updateLineItem = useCallback(
    (lineId: string, patch: Partial<OrderLineItem>) => {
      setLineItems((prev) => prev.map((it) => (it.id === lineId ? { ...it, ...patch } : it)))
    },
    []
  )

  const addLineItem = () => {
    setLineItems((prev) => [...prev, createEmptyLineItem()])
  }

  /**
   * **帘体**（**组级**，issue #4521）：一个商品组 = 一樘帘 ⇒ 组内同步。
   *
   * 三条口径：
   * 1. **是否定型默认跟着帘体走**（真值源 §10 布帘是 / 纱帘否）—— 但**只在商家没手改过时**
   *    （`isShapedTouched` 落在行状态里，同 `openCountTouched` 的纪律：手改过的值只能显式改回）；
   * 2. **用料来源**：纱帘 = 商家给定（`人工指定`，且不发算料请求）；布帘 = 回到公式计算；
   * 3. 切到纱帘时清掉上一次的算料结果/错误（纱帘不算料，留着旧公式串会骗人）。
   */
  const handleCurtainBodyChange = (groupId: string, body: CurtainBody) => {
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.groupId !== groupId) return it
        const next: OrderLineItem = {
          ...it,
          curtainBody: body,
          metersSource:
            body === CURTAIN_BODY_SHEER ? LINE_METERS_SOURCE_MANUAL : METERS_SOURCE_FORMULA,
        }
        if (body === CURTAIN_BODY_SHEER) {
          next.calc = null
          next.calcError = null
        }
        if (!it.isShapedTouched) {
          next.craft = { ...it.craft, isShaped: defaultIsShapedForBody(body) }
        }
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
    const autoSku = skusOfColor.length === 1 ? skusOfColor[0] : null
    patchGroup(groupId, {
      selectedColorId: colorId,
      selectedSku: autoSku,
      ...(autoSku ? { unitPrice: Number(autoSku.price) } : {}),
    })
  }

  /** 门幅 / 售卖方式（**组级**）：同上；并把「高」默认成门幅（仅定高买宽，可改） */
  const handleSelectSkuForGroup = (groupId: string, sku: OrderProductSku) => {
    const sample = lineItems.find((l) => l.groupId === groupId)
    const isFixedHeight = (sample?.craft.cuttingMode ?? DEFAULT_CUTTING_MODE) === DEFAULT_CUTTING_MODE
    const defaultHeight = isFixedHeight ? heightFromDoorWidth(sku.doorWidth) : null
    setLineItems((prev) =>
      prev.map((it) => {
        if (it.groupId !== groupId) return it
        const next: OrderLineItem = { ...it, selectedSku: sku, unitPrice: Number(sku.price) || 0 }
        // 只在「还没填高」时补默认值 —— 商家填过的值不覆盖（同「手改留痕」纪律）
        if (defaultHeight !== null && it.height === null) next.height = defaultHeight
        return next
      })
    )
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
        // 布料单没有帘体/纱帘（issue #4521）：清掉纱帘选配，避免切回成品帘时凭空多一条纱帘行
        curtainBody: CURTAIN_BODY_CLOTH,
        sheerMeters: null,
        sheerUnitPrice: null,
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
    setPickedLogisticsHint(describeLogisticsProfile(c.defaultLogisticsType, c.defaultLogisticsCompany))
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

    updateLineItem(lineId, {
      product: detail,
      productLoading: false,
      unitPrice: fallbackPrice,
      processingItems: processingCatalog,
      selectedProcessing: {},
    })
  }

  // ===== 颜色 / 规格 选择 =====
  const handleSelectColor = (line: OrderLineItem, colorId: string) => {
    const skusOfColor = (line.product?.skus || []).filter((s) => s.colorId === colorId)
    const autoSku = skusOfColor.length === 1 ? skusOfColor[0] : null
    updateLineItem(line.id, {
      selectedColorId: colorId,
      selectedSku: autoSku,
      unitPrice: autoSku ? Number(autoSku.price) : line.unitPrice,
    })
  }

  const handleSelectSku = (line: OrderLineItem, sku: OrderProductSku) => {
    updateLineItem(line.id, {
      selectedSku: sku,
      unitPrice: Number(sku.price) || 0,
    })
  }

  const toggleProcessing = (
    line: OrderLineItem,
    pi: ProcessingItem,
    selected: boolean
  ) => {
    const prev = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
    updateLineItem(line.id, {
      selectedProcessing: {
        ...line.selectedProcessing,
        // 选中即按当前面料米数推导数量（per_meter=米数，其余=1）；取消勾选保留原值（issue #3005 回滚 #2986）
        [pi.id]: { selected, qty: selected ? deriveProcessingQty(pi, line.quantity) : prev.qty },
      },
    })
  }

  // 行商品数量（面料米数）**手工改**（issue #4434）：
  // ① 标记来源「人工指定」⇒ 后续算料试算**不得静默改回**（真值源 §8：折数/用料必须带来源）；
  // ② 已选中加工项数量联动重算（per_meter=面料米数，其余=1）（issue #3005 回滚 #2986）。
  const handleLineQtyChange = (line: OrderLineItem, qty: number) => {
    updateLineItem(line.id, {
      quantity: qty,
      metersSource: LINE_METERS_SOURCE_MANUAL,
      selectedProcessing: requantifyProcessing(line, qty),
    })
  }

  /** 「恢复按公式计算」（issue #4434）：显式切回 ⇒ 下一次试算重新预填数量 */
  const restoreFormulaMeters = (line: OrderLineItem) => {
    updateLineItem(line.id, { metersSource: METERS_SOURCE_FORMULA, calcError: null })
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
        .map((l) => `${l.id}:${l.metersSource}:${craftCalcSignature(craftCalcParamsOf(calcInputOf(l)))}`)
        .join(';'),
    [lineItems]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: CraftCalcParams }> = []
    for (const line of lineItems) {
      if (line.metersSource !== METERS_SOURCE_FORMULA) continue
      const params = craftCalcParamsOf(calcInputOf(line))
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
        processingInfo: buildLineProcessingInfo(l),
      })),
    }),
    [pricedLines]
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
  const unpricedCount = (feePreview?.items ?? []).filter((row, i) => {
    const line = pricedLines[i]
    if (!line || line.saleForm === SALE_FORM_FABRIC) return false
    return (
      (row.processingFeeDetail as { fee_source?: string } | undefined)?.fee_source === 'unpriced'
    )
  }).length

  // ===== 费用汇总 =====
  const totals = useMemo(() => {
    let productSubtotal = 0
    let edgeSubtotal = 0
    let sheerSubtotal = 0

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
      // 纱帘（issue #4521）：也是一条**独立面料明细行** ⇒ 金额必须计入订单总额，
      // 否则后端「应收 - 优惠 ≈ 实收」校验会拒单。
      const sheerPrice = sheerUnitPriceOf(item)
      if (sheerPrice !== null) {
        sheerSubtotal += sheerMetersOf(item) * sheerPrice
      }
    })

    // 加工费 = **服务端取价结果**（issue #4450）。
    // 此前这里是本地 `Σ 加工项单价 × 数量`，与服务端 #4406 的组合取价口径不同 ⇒ 提交必被拒。
    // 预览未就绪时按 0 —— 由提交闸门拦住（不得用本地估算值提交）。
    const processingFee = feePreview?.processingFeeTotal ?? 0

    return {
      productSubtotal,
      edgeSubtotal,
      sheerSubtotal,
      processingFee,
      total: productSubtotal + edgeSubtotal + sheerSubtotal + processingFee,
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
      // 带纱帘 ⇒ 纱帘单价必填（issue #4521）。为什么这里**不**沿用配布边的「不填不生成」：
      // 配布边是款式=拼色的**副产物**，而帘体是商家**显式选**的 —— 显式选了「布帘+纱帘」
      // 却静默丢掉纱帘行 = 交付一张与商家所见不符的错单（比拦住提交危险得多）。
      if (line.saleForm !== SALE_FORM_FABRIC && bodyHasSheerLine(line.curtainBody)) {
        if (!(Number(line.sheerUnitPrice) > 0)) {
          e[`${prefix}_sheerUnitPrice`] = `第 ${idx + 1} 个商品的纱帘单价须大于 0（或把帘体改回「布帘」）`
        }
      }
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

    // 樘窗跨行分组已移除（issue #4486）；`craftLineId` 仍由 `buildLineProcessingInfo`
    // 按**本行自指**写入，供 §4.8 配布边行被主布行吸收（不是跨行分组）。
    const items: OrderItemFormData[] = pricedLines.flatMap((line, lineIndex) => {
      // 加工费 = **服务端取价结果**（issue #4450）：页面显示 === 落库。
      // 预览行与 `pricedLines` **同序**（服务端按下标一一对应）。
      const lineFee = Number(feePreview?.items[lineIndex]?.processingFee) || 0

      // `processingInfo` 由**同一个** `buildLineProcessingInfo` 构造（预览也是它）
      const baseInfo = buildLineProcessingInfo(line)
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

      // 配布边行（§4.8 一樘窗 = 主布行 + 配布边行）：
      // - **不携带工艺规格**（折数/开数/幅数是一樘窗的属性 ⇒ 两行都带会让工序与计件翻倍）
      // - **不挂加工项**（硬约束：加工费只挂主布行）
      // - **不关联主布商品**（后端按 productId 聚合库存/销量 ⇒ 复用会双扣库存、双计销量）
      // - **绑组键与所在樘窗同一个**（issue #4395）：配布边行与主布行同属一樘窗 ⇒ 用 `pairKey`
      //   而不是本行自指（主布行被并进别的樘窗时，自指会把配布边行丢在组外）
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

      // 纱帘行（issue #4521）：与主布行**同一樘帘**（同 `craftLineId`）、携带**同一份工艺规格**
      // —— 纱帘是**另一个部位**（工序路线按 `纱帘×工艺` 取 ⇒ 不带规格会被当成布帘），
      // 这与配布边行「刻意不带规格」正好相反（配布边不是部位，带了会让工序与计件翻倍）。
      // - **不挂加工项**（硬约束：加工费只挂主布行）
      // - **不关联主布商品**（后端按 productId 聚合库存/销量 ⇒ 复用会双扣库存、双计销量）
      // - 宽 / 高与主布行**同一份**：尺寸数量是商品组级属性（用户口径）⇒ 一樘帘共用
      const sheerPrice = sheerUnitPriceOf(line)
      if (sheerPrice !== null) {
        const sku = line.selectedSku
        const colorName = uniqueColors(line.product!.skus).find(
          (c) => c.id === line.selectedColorId
        )?.name
        const sheerMeters = sheerMetersOf(line)
        rows.push({
          productName: CURTAIN_TYPE_SHEER,
          quantity: sheerMeters,
          unitPrice: sheerPrice,
          subtotal: sheerMeters * sheerPrice,
          width: Number(line.width),
          height: Number(line.height),
          processingInfo: {
            saleForm: SALE_FORM_FINISHED,
            colorName,
            skuCode: sku?.skuCode,
            doorWidth: sku?.doorWidth,
            ...buildSheerLineCraftSpec(
              pairKey,
              buildCraftSpec(line.craft),
              line.sheerMeters === null ? METERS_SOURCE_FOLLOW : METERS_SOURCE_MANUAL
            ),
            // 纱帘用料米数 = 商家给定值（「买多少就是多少」）⇒ 落 `fabric_meters`，
            // 让加工单的「应做数量」拿到真值（#4273 同口径）。
            fabric_meters: sheerMeters,
          },
        } as OrderItemFormData)
      }

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
                        onChangeWidth={(w) =>
                          updateLineItem(line.id, {
                            width: w,
                            // **宽 → 打开方式**联动（真值源 §10 的启发式）：手改过就不覆盖
                            ...(w !== null && !line.openCountTouched
                              ? { craft: { ...line.craft, openCount: deriveOpenCount(w) } }
                              : {}),
                          })
                        }
                        onChangeHeight={(h) => updateLineItem(line.id, { height: h })}
                        onToggleProcessing={(pi, sel) => toggleProcessing(line, pi, sel)}
                        onChangeCraft={(patch) =>
                          updateLineItem(line.id, {
                            craft: { ...line.craft, ...patch },
                            // 商家手改了打开方式 ⇒ 记下来（行状态），之后改宽不再覆盖
                            ...(patch.openCount !== undefined
                              ? { openCountTouched: true }
                              : {}),
                            // 手改过「是否定型」⇒ 记下来，之后改帘体不再覆盖（issue #4521）
                            ...(patch.isShaped !== undefined ? { isShapedTouched: true } : {}),
                          })
                        }
                        onEdgeMetersChange={(m) => updateLineItem(line.id, { edgeMeters: m })}
                        onEdgeUnitPriceChange={(p) =>
                          updateLineItem(line.id, { edgeUnitPrice: p })
                        }
                        onSheerMetersChange={(m) => updateLineItem(line.id, { sheerMeters: m })}
                        onSheerUnitPriceChange={(p) =>
                          updateLineItem(line.id, { sheerUnitPrice: p })
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
              {/* 选中客户的常用物流档案（只读提示，issue #4419）：发货时按同一档案带出方式/公司 */}
              {pickedLogisticsHint && (
                <p className="mt-2 text-xs text-neutral-400" data-testid="picked-logistics-hint">
                  常用物流：{pickedLogisticsHint}
                </p>
              )}
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
                                  | { unit_price?: number; meters?: number; fee_source?: string }
                                  | undefined
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
                                      d?.fee_source === 'unpriced'
                                        ? '未定价（按 0 计）'
                                        : (expr ?? '—')
                                    }
                                    amount={feeDisplay.baseAmount}
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
                            {/* 配布边逐行（§4.8 一樘窗 = 主布行 + 配布边行） */}
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
                            {/* 纱帘（issue #4521）：与配布边同构的独立面料行 —— 米数 × 单价 */}
                            {group.lines.map((line) => {
                              const p = sheerUnitPriceOf(line)
                              if (p === null) return null
                              const m = sheerMetersOf(line)
                              return (
                                <CostRow
                                  key={`s_${line.id}`}
                                  label="纱帘"
                                  expr={`${m} 米 × ${formatAmount(p)}/米`}
                                  amount={m * p}
                                />
                              )
                            })}
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
                {totals.sheerSubtotal > 0 && (
                  <Row label="纱帘" value={formatAmount(totals.sheerSubtotal)} />
                )}
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
                  <div className="rounded bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700">
                    有 {unpricedCount} 行加工费未定价 —— 这些行按 0 计入订单金额，
                    请到「加工费组合」定价后再下单
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
                    type="number"
                    id="discountAmount"
                    min={0}
                    step={0.01}
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
                    type="number"
                    id="actualAmount"
                    min={0}
                    step={0.01}
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
  onEdgeMetersChange: (meters: number | null) => void
  onEdgeUnitPriceChange: (price: number | null) => void
  /** 纱帘米数 / 单价（issue #4521）—— 帘体含纱帘时才有意义 */
  onSheerMetersChange: (meters: number | null) => void
  onSheerUnitPriceChange: (price: number | null) => void
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
          <input
            type="number"
            min={1}
            placeholder="米"
            value={line.quantity || ''}
            onChange={(e) => {
              const raw = e.target.value
              if (raw === '') onChangeQty(0)
              else if (/^\d*\.?\d*$/.test(raw)) onChangeQty(Number(raw))
            }}
            className={inputClass}
          />
          {errQty && <p className="mt-1 text-sm text-red-600">{errQty}</p>}
        </div>
        <div>
          <Label required>单价 (¥/米)</Label>
          <input
            type="number"
            min={0}
            step={0.01}
            value={line.unitPrice}
            onChange={(e) => onChangePrice(Number(e.target.value) || 0)}
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
  /** 帘体（issue #4521）：组级 —— 布帘 / 纱帘 / 布帘+纱帘（决定用料来源与落库行数） */
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
  /** 帘体（组级，issue #4521）：布帘 / 纱帘 / 布帘+纱帘 */
  onChangeCurtainBody: (body: CurtainBody) => void
  /** 删除整个商品组 */
  onRemoveGroup: () => void
  /** 渲染本组这一樘帘（由页面传入，保证 props 装配只有一处） */
  renderPosition: (line: OrderLineItem) => React.ReactNode
  /** 布料行（无部位）的 米数 / 单价 回调（issue #4493） */
  onChangeQty: (lineId: string, qty: number) => void
  onChangePrice: (lineId: string, price: number) => void
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
  open,
  onToggle,
  children,
}: {
  step: number
  title: string
  /** 收起时显示的已选摘要 */
  summary?: string
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="border-t border-neutral-100 first:border-t-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center gap-2 py-2.5 text-left"
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
        <span className="ml-auto flex items-center gap-1.5 min-w-0">
          {!open && summary && (
            <span className="text-xs text-neutral-500 truncate">{summary}</span>
          )}
          {open ? (
            <ChevronDown className="w-4 h-4 text-neutral-400 shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-neutral-400 shrink-0" />
          )}
        </span>
      </button>
      {open && <div className="pb-4">{children}</div>}
    </div>
  )
}

/**
 * **商品组**（issue #4485；issue #4521 起 = **一樘帘**）：一块布（同商品 / 同色 / 同门幅）
 * 下渲染**一份** ①尺寸与数量 ②工艺规格 ③加工项 ④特殊选项。
 *
 * 用户 2026-09-19 口径：「新增部位应该在**已选择的商品下**去新增，现在像是两个商品，
 * 商品的**基础属性应该共用**」→ 随后进一步裁定「**移除部位功能，其实完全不需要**」：
 * 一个商品组 = 一樘帘，需要纱帘时改**帘体**（`curtainBody`），而不是再加一行。
 *
 * 为什么这样切：裁定 **R-a**「一行 `order_items` = 一个部位」是**落库**口径，与展示无关
 * —— 旧实现把落库口径直接当成了 UI 结构（复制一行 = 复制整张商品卡）⇒ 同一商品的两个部位
 * 看起来像两个商品、颜色与门幅还要各选一遍。
 *
 * 本组件只负责**商品基础属性**（选择商品 / 颜色 / 门幅·售卖方式 / 售卖形态 / 帘体）与那一樘帘的排布；
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
      {/* 组头 = **商品基础属性**（一组一份，部位共用） */}
      <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-neutral-100 bg-neutral-50/60 rounded-t-xl">
        <div className="flex items-center gap-2 min-w-0">
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
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-sm font-semibold text-neutral-900">
            {formatAmount(groupAmount)}
          </span>
          {canRemove && (
            <button
              type="button"
              onClick={onRemoveGroup}
              className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-red-600 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              删除
            </button>
          )}
        </div>
      </div>

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
                                {sku.sellingMethod && (
                                  <span className="ml-2 text-xs text-neutral-500">
                                    {sellingMethodLabel[sku.sellingMethod] || sku.sellingMethod}
                                  </span>
                                )}
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

        {/* **帘体**（issue #4521，用户口径的四类购买情况）——**商品组级**，与售卖形态同层：
            它决定「用料怎么来」（布帘按韩折公式算；纱帘**买多少填多少**）与「落库几行」
            （含纱帘 ⇒ 主布行 + 纱帘行；只买纱帘 ⇒ 一行 `curtainType=纱帘`）。
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
              {group.curtainBody === CURTAIN_BODY_SHEER
                ? '纱帘：买多少填多少（不自动算料）'
                : group.curtainBody === CURTAIN_BODY_BOTH
                  ? '布帘 + 纱帘：主布按韩折公式算料，纱帘填实际米数 —— 提交后是两条明细行'
                  : '布帘：按韩折公式自动算用料米数'}
            </p>
            {/* 纱帘单价缺失的提示（issue #4521）：**常显**（不塞进可收起的步骤里 —— 否则
                商家只知道「提交失败」却找不到该改哪里）；它就该长在「帘体」这个选择旁边。 */}
            {errors[`line_${group.lines[0].id}_sheerUnitPrice`] && (
              <p className="mt-1.5 text-sm text-red-600">
                {errors[`line_${group.lines[0].id}_sheerUnitPrice`]}
              </p>
            )}
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
          /* 一樘帘（issue #4521）：一个商品组 = 一樘帘 ⇒ 只渲染**一份** ①~④。
             「新增部位」已移除（用户裁定「移除部位功能，其实完全不需要」）——
             需要纱帘时改**帘体**，不是再加一行。 */
          <div className="space-y-3">{renderPosition(group.lines[0])}</div>
        )}
      </div>
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
  onEdgeMetersChange,
  onEdgeUnitPriceChange,
  onSheerMetersChange,
  onSheerUnitPriceChange,
}: LineItemBlockProps) {
  /** 当前展开的**向导步骤**（issue #4511 手风琴）：1 尺寸与数量 / 2 工艺规格 / 3 加工项 / 4 特殊选项 */
  const [openStep, setOpenStep] = useState(1)
  const stepProps = (n: number) => ({
    open: openStep === n,
    onToggle: () => setOpenStep(openStep === n ? 0 : n),
  })
  const selectedProcessingCount = Object.values(line.selectedProcessing).filter(
    (c) => c.selected
  ).length
  /** 自动识别特征（D6）—— 只读展示，**不计入** `selectedProcessingCount`（不是手选项） */
  const autoFeatures = autoFeaturesOf(line)
  /** 布料组整组无加工（issue #4493）⇒ 自动识别块也不渲染 */
  const isFabricLine = line.saleForm === SALE_FORM_FABRIC

  const errQty = errors[`line_${line.id}_quantity`]
  const errPrice = errors[`line_${line.id}_unitPrice`]
  const errWidth = errors[`line_${line.id}_width`]
  const errHeight = errors[`line_${line.id}_height`]

  /** 摘要（issue #4420）：一眼看懂「这是什么、多大、多少钱」—— 部位已移除（#4521）⇒ 取帘体 */
  const summarySpec = [
    line.curtainBody,
    line.craft.craft,
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

            {/* ① 尺寸与数量 */}
            <WizardStep
              step={1}
              title="尺寸与数量"
              summary={`${summarySize} · ${line.quantity} 米 · ${formatAmount(Number(line.unitPrice) || 0)}/米`}
              {...stepProps(1)}
            >
            {/* 尺寸与数量（issue #4420 分区①）：宽 / 高 必填 + 数量 / 单价 */}
            <div className="pt-3 border-t border-neutral-100">
              <p className="mb-3 text-xs text-neutral-400">
                宽 / 高按成品尺寸填，单位米 —— **一樘帘共用一份尺寸**（主布与纱帘同宽同高）
              </p>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <div>
                  <Label required>宽 (米)</Label>
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    placeholder="如 6.6"
                    value={line.width ?? ''}
                    onChange={(e) => onChangeWidth(decimalOrNull(e.target.value))}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errWidth && <p className="mt-1 text-sm text-red-600">{errWidth}</p>}
                </div>
                <div>
                  <Label required>高 (米)</Label>
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    placeholder="如 2.6"
                    value={line.height ?? ''}
                    onChange={(e) => onChangeHeight(decimalOrNull(e.target.value))}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errHeight && <p className="mt-1 text-sm text-red-600">{errHeight}</p>}
                </div>
                <div>
                  {/* label 文案保持「数量」不变（既有判据按此定位输入框），单位进 placeholder */}
                  <Label required>数量</Label>
                  <input
                    type="number"
                    min={1}
                    placeholder="米"
                    value={line.quantity || ''}
                    onChange={(e) => {
                      const raw = e.target.value
                      // #2987：允许清空输入（空态传 0 显示为空，不再被强制弹回默认 1）；
                      // 仅接受合法数字（含按米小数如 2.5），非法字符忽略防 NaN；
                      // 最终由提交校验「数量须大于 0」兜底
                      if (raw === '') {
                        onChangeQty(0)
                      } else if (/^\d*\.?\d*$/.test(raw)) {
                        onChangeQty(Number(raw))
                      }
                    }}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errQty && <p className="mt-1 text-sm text-red-600">{errQty}</p>}
                  {/* 算料来源与公式（issue #4434）—— 公式串**原样渲染后端产出**，前端不自拼。
                      ⚠️ 纱帘（issue #4521）：**买多少就是多少**，没有公式可恢复 ⇒ 只报口径，
                      不给「恢复按公式计算」按钮（点了也没有公式可算）。 */}
                  {line.curtainBody === CURTAIN_BODY_SHEER ? (
                    <p className="mt-1 text-xs text-neutral-500">
                      纱帘按实际买多少填，不自动算料
                    </p>
                  ) : line.metersSource === LINE_METERS_SOURCE_MANUAL ? (
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
                    line.curtainBody !== CURTAIN_BODY_SHEER &&
                    isAutoCalcUnavailable(calcInputOf(line)) && (
                      <p className="mt-1 text-xs text-amber-600">
                        该工艺无自动算料，请手填米数
                      </p>
                    )}
                </div>
                <div>
                  <Label required>单价 (¥/米)</Label>
                  <input
                    type="number"
                    min={0}
                    step={0.01}
                    value={line.unitPrice}
                    onChange={(e) => onChangePrice(Number(e.target.value) || 0)}
                    className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  {errPrice && <p className="mt-1 text-sm text-red-600">{errPrice}</p>}
                </div>
              </div>
            </div>

            </WizardStep>

            {/* ② 工艺规格（§4.2 字段表 A + §4.8 双拼） */}
            <WizardStep
              step={2}
              title="工艺规格"
              summary={summarySpec || '按行业默认'}
              {...stepProps(2)}
            >
              <OrderCraftFields
                value={line.craft}
                onChange={onChangeCraft}
                mainMeters={line.quantity}
                sheer={bodyHasSheerLine(line.curtainBody)}
                sheerMeters={line.sheerMeters}
                onSheerMetersChange={onSheerMetersChange}
                sheerUnitPrice={line.sheerUnitPrice}
                onSheerUnitPriceChange={onSheerUnitPriceChange}
                edgeMeters={line.edgeMeters}
                onEdgeMetersChange={onEdgeMetersChange}
                edgeUnitPrice={line.edgeUnitPrice}
                onEdgeUnitPriceChange={onEdgeUnitPriceChange}
              />
            </WizardStep>

            {/* ③ 加工项 */}
            <WizardStep
              step={3}
              title="加工项"
              summary={selectedProcessingCount > 0 ? `已选 ${selectedProcessingCount} 项` : '未选'}
              {...stepProps(3)}
            >
              {processingLoading ? (
                <div className="text-sm text-neutral-400 py-2">加工项加载中…</div>
              ) : line.processingItems.length === 0 ? (
                <div className="text-sm text-neutral-400 py-2">暂无可用加工项</div>
              ) : (
                <div className="space-y-2">
                  {line.processingItems.map((pi) => {
                    const cfg = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
                    return (
                      <div
                        key={pi.id}
                        className={
                          'flex items-center gap-3 p-3 rounded border transition-colors ' +
                          (cfg.selected
                            ? 'border-primary-300 bg-primary-50/40'
                            : 'border-neutral-200 bg-white')
                        }
                      >
                        <input
                          type="checkbox"
                          checked={cfg.selected}
                          onChange={(e) => onToggleProcessing(pi, e.target.checked)}
                          className="w-4 h-4 accent-primary-600"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-neutral-900">{pi.name}</div>
                        </div>
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
                      </div>
                    )
                  })}

                  {/* 自动识别（issue #4526 · D6）：超高/超宽 = 宽高 vs 门幅，倒幅/正幅 = cuttingMode
                      推导 —— **只读**（不是可勾选项：手选项 = 与 cuttingMode 冲突的第二份口径）。
                      标来源「推算」：本条判据是**推理非实证**（设计 §5.2），不假装定论。
                      ⚠️ 布料组整组无加工（#4493）⇒ 这块也整块不渲染（与「加工项」「费用明细」同闸门）。 */}
                  {!isFabricLine && autoFeatures.length > 0 && (
                    <div
                      data-testid="auto-detected-features"
                      className="rounded border border-dashed border-neutral-300 bg-neutral-50/60 px-3 py-2"
                    >
                      <div className="text-xs font-medium text-neutral-600">
                        自动识别（按宽高与门幅推算，不可手选）
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {autoFeatures.map((feature) => (
                          <span
                            key={feature.name}
                            title={feature.reason}
                            className="inline-flex items-center gap-1 rounded border border-neutral-300 bg-white px-2 py-0.5 text-xs text-neutral-700"
                          >
                            {feature.name}
                            <span className="text-neutral-400">（{feature.source}）</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </WizardStep>

            {/* ④ 特殊选项（issue #4511：从工艺规格里**抽出来**，与 ②③ 平级） */}
            <WizardStep
              step={4}
              title="特殊选项"
              summary={(line.craft.specialOptions ?? []).length > 0 ? `已选 ${(line.craft.specialOptions ?? []).length} 项` : '未选'}
              {...stepProps(4)}
            >
              <OrderExtraOptions
                value={line.craft.specialOptions}
                onChange={(next) => onChangeCraft({ specialOptions: next })}
              />
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
}: {
  label: string
  expr: string
  amount: number
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-neutral-500 truncate">
        <span className="text-neutral-400">{label}</span>
        <span className="ml-1.5 tabular-nums">{expr}</span>
      </span>
      <span className="text-neutral-700 tabular-nums shrink-0">{formatAmount(amount)}</span>
    </div>
  )
}

