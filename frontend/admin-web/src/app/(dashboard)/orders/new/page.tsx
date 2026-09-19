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
  DEFAULT_CUTTING_MODE,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  STYLE_MIXED,
  buildCraftSpec,
  buildEdgeLineCraftSpec,
  buildMainLineGroupKeys,
  createDefaultCraftSpec,
  type CraftSpecInput,
} from '@/lib/order-craft-fields'
import { describeLogisticsProfile } from '@/lib/logistics'
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
  /** 卡片是否收起（issue #4420 展示重构）—— 收起只影响渲染，不影响任何录入值 */
  collapsed: boolean
  /**
   * 商家**手改过**打开方式（issue #4493 的宽→开数联动）——落在**行状态**里，
   * 不放组件内 state（收起/展开重挂不丢）。手改过 ⇒ 改宽**不得覆盖**。
   */
  openCountTouched: boolean
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

/** 该行已勾选的加工项明细（提交 payload 与加工费预览**共用**这一份构造） */
function processingDetailsOf(line: OrderLineItem): Array<Record<string, unknown>> {
  return Object.entries(line.selectedProcessing)
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
  const isPaired = edgePrice !== null
  const mainSpec = isFabric
    ? {}
    : isPaired
      ? { ...buildCraftSpec(line.craft), ...buildMainLineGroupKeys(line.id) }
      : buildCraftSpec(line.craft)

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
    quantity: 1,
    unitPrice: 0,
    width: null,
    height: null,
    processingItems: [],
    selectedProcessing: {},
    // 三条默认档（issue #4420）：加工类型「定高买宽」/ 款式「单色」/ 褶距 0.125 —— 都是真值
    craft: createDefaultCraftSpec(),
    edgeMeters: null,
    edgeUnitPrice: null,
    collapsed: false,
    openCountTouched: false,
    metersSource: METERS_SOURCE_FORMULA,
    calc: null,
    calcError: null,
  }
}

/**
 * 「新增部位」（issue #4420，**issue #4485 改为嵌套**）：在**同一商品**下追加一个部位行。
 *
 * 新行**继承商品基础属性**（商品 / 颜色 / 门幅·售卖方式 / 单价 / 宽高）与**同一个 `groupId`**
 * ⇒ 渲染时它落在**同一张商品卡**里，商家看到的是「一个商品的两个部位」，而不是两个商品。
 *
 * 三条刻意**不**继承：
 * 1. **部位**（`curtainType`）：留着会让商家以为已选好 ⇒ 两行同部位 ⇒ 加工单长出两套同部位工序；
 * 2. **加工项**（`selectedProcessing`）：加工项按部位选（布帘要定型、纱帘不要），继承会**静默加钱**；
 * 3. **数量**：各部位用料不同，必须各自算/各自填（沿用默认值 + 显式提示，见 `needsManualMeters`）。
 */
function createPositionLine(source: OrderLineItem): OrderLineItem {
  return {
    ...createEmptyLineItem(source.groupId),
    product: source.product,
    selectedColorId: source.selectedColorId,
    selectedSku: source.selectedSku,
    unitPrice: source.unitPrice,
    width: source.width,
    height: source.height,
    processingItems: source.processingItems,
    craft: { ...source.craft, curtainType: undefined },
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
   * 「新增部位」（issue #4420）：在**同一商品**下追加一个部位行（布帘 + 纱帘 = 两行）。
   *
   * 插在源行**后面**（不是列表末尾）—— 同樘窗的部位行相邻，商家一眼能看出它们是一组。
   */
  const addPositionLine = (sourceId: string) => {
    setLineItems((prev) => {
      const idx = prev.findIndex((it) => it.id === sourceId)
      if (idx < 0) return prev
      const next = [...prev]
      next.splice(idx + 1, 0, createPositionLine(prev[idx]))
      return next
    })
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

  const removeLineItem = (lineId: string) => {
    setLineItems((prev) => (prev.length <= 1 ? prev : prev.filter((it) => it.id !== lineId)))
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
        .map((l) => `${l.id}:${l.metersSource}:${craftCalcSignature(craftCalcParamsOf(l))}`)
        .join(';'),
    [lineItems]
  )

  useEffect(() => {
    const targets: Array<{ id: string; params: CraftCalcParams }> = []
    for (const line of lineItems) {
      if (line.metersSource !== METERS_SOURCE_FORMULA) continue
      const params = craftCalcParamsOf(line)
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
                    onAddPosition={() => addPositionLine(group.lines[0].id)}
                    onRemoveGroup={() => removeGroup(group.id)}
                    onChangeQty={(lineId, q) => {
                      const target = lineItems.find((l) => l.id === lineId)
                      if (target) handleLineQtyChange(target, q)
                    }}
                    onChangePrice={(lineId, p) => updateLineItem(lineId, { unitPrice: p })}
                    renderPosition={(line, li) => (
                      <LineItemBlock
                        key={line.id}
                        index={li}
                        line={line}
                        canRemove={group.lines.length > 1}
                        errors={errors}
                        processingLoading={processingCatalogLoading}
                        onRemove={() => removeLineItem(line.id)}
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
                        onToggleCollapsed={() =>
                          updateLineItem(line.id, { collapsed: !line.collapsed })
                        }
                        onToggleProcessing={(pi, sel) => toggleProcessing(line, pi, sel)}
                        onChangeCraft={(patch) =>
                          updateLineItem(line.id, {
                            craft: { ...line.craft, ...patch },
                            // 商家手改了打开方式 ⇒ 记下来（行状态），之后改宽不再覆盖
                            ...(patch.openCount !== undefined
                              ? { openCountTouched: true }
                              : {}),
                          })
                        }
                        onEdgeMetersChange={(m) => updateLineItem(line.id, { edgeMeters: m })}
                        onEdgeUnitPriceChange={(p) =>
                          updateLineItem(line.id, { edgeUnitPrice: p })
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
                                return (
                                  <CostRow
                                    key={`p_${line.id}`}
                                    label={
                                      line.craft.curtainType
                                        ? `加工·${line.craft.curtainType}`
                                        : '加工'
                                    }
                                    expr={
                                      d?.fee_source === 'unpriced'
                                        ? '未定价（按 0 计）'
                                        : (expr ?? '—')
                                    }
                                    amount={Number(feeRow?.processingFee) || 0}
                                  />
                                )
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
  index: number
  line: OrderLineItem
  canRemove: boolean
  errors: Record<string, string>
  processingLoading: boolean
  onRemove: () => void
  onChangeQty: (q: number) => void
  /** 「恢复按公式计算」（issue #4434）：切回算料预填（手改后不会被静默改回，只能显式恢复） */
  onRestoreFormula: () => void
  onChangePrice: (p: number) => void
  /** 成品宽 / 高（米，部位级；issue #4420 必填） */
  onChangeWidth: (w: number | null) => void
  onChangeHeight: (h: number | null) => void
  /** 卡片收起 / 展开（issue #4420）—— 只影响渲染 */
  onToggleCollapsed: () => void
  onToggleProcessing: (pi: ProcessingItem, selected: boolean) => void
  onChangeCraft: (patch: Partial<CraftSpecInput>) => void
  onEdgeMetersChange: (meters: number | null) => void
  onEdgeUnitPriceChange: (price: number | null) => void
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
  /** 售卖形态（issue #4493）：组级 —— 决定这一组下面出什么（布料 = 没有部位行） */
  saleForm: SaleForm
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
  /** 在本商品下新增一个部位行 */
  onAddPosition: () => void
  /** 删除整个商品组（含其下所有部位行） */
  onRemoveGroup: () => void
  /** 渲染一个部位行（由页面传入，保证部位行的 props 装配只有一处） */
  renderPosition: (line: OrderLineItem, positionIndex: number) => React.ReactNode
  /** 布料行（无部位）的 米数 / 单价 回调（issue #4493） */
  onChangeQty: (lineId: string, qty: number) => void
  onChangePrice: (lineId: string, price: number) => void
}

/**
 * **商品组**（issue #4485）：一块布（同商品 / 同色 / 同门幅）下挂**多个部位行**。
 *
 * 用户 2026-09-19 口径：「新增部位应该在**已选择的商品下**去新增，现在像是两个商品，
 * 商品的**基础属性应该共用**。」
 *
 * 为什么这样切：裁定 **R-a**「一行 `order_items` = 一个部位」是**落库**口径，与展示无关
 * —— 旧实现把落库口径直接当成了 UI 结构（复制一行 = 复制整张商品卡）⇒ 同一商品的两个部位
 * 看起来像两个商品、颜色与门幅还要各选一遍。
 *
 * 本组件只负责**商品基础属性**（选择商品 / 颜色 / 门幅·售卖方式）与部位行的排布；
 * 组内改颜色或门幅 ⇒ **组内所有部位行同步**（它们是同一块布的属性）。
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
  onAddPosition,
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
          <span className="text-xs text-neutral-400 shrink-0">
            {group.lines.length} 个部位
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
                ? '布料：按米卖，没有加工（不出现宽高 / 工艺规格 / 部位 / 加工项，也不生成加工单）'
                : '成品帘：做成帘，需要部位 / 宽高 / 工艺规格与加工项'}
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
          <>
            {/* 部位行（issue #4485）：嵌在**本商品**下，商品基础属性共用 */}
            <div className="space-y-3">
              {group.lines.map((line, li) => renderPosition(line, li))}
            </div>

            <button
              type="button"
              onClick={onAddPosition}
              className="mt-3 w-full h-10 rounded-lg border border-dashed border-neutral-300 bg-white text-sm text-neutral-500 hover:border-primary-500 hover:text-primary-600 hover:bg-primary-50/30 transition-colors inline-flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" />
              新增部位（同一商品，共用颜色与门幅）
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function LineItemBlock({
  index,
  line,
  canRemove,
  errors,
  processingLoading,
  onRemove,
  onChangeQty,
  onRestoreFormula,
  onChangePrice,
  onChangeWidth,
  onChangeHeight,
  onToggleCollapsed,
  onToggleProcessing,
  onChangeCraft,
  onEdgeMetersChange,
  onEdgeUnitPriceChange,
}: LineItemBlockProps) {
  const colorOptions = useMemo(() => uniqueColors(line.product?.skus), [line.product])
  /** 加工选项默认折叠（issue #4489 判据 3）—— 只影响渲染 */
  const [processingOpen, setProcessingOpen] = useState(false)
  const selectedProcessingCount = Object.values(line.selectedProcessing).filter(
    (c) => c.selected
  ).length

  const errQty = errors[`line_${line.id}_quantity`]
  const errPrice = errors[`line_${line.id}_unitPrice`]
  const errWidth = errors[`line_${line.id}_width`]
  const errHeight = errors[`line_${line.id}_height`]

  const colorName = colorOptions.find((c) => c.id === line.selectedColorId)?.name
  /** 收起时的摘要（issue #4420）：一眼看懂「这是什么、多大、多少钱」 */
  const summarySpec = [
    line.craft.curtainType,
    line.craft.craft,
    line.craft.cuttingMode,
    line.craft.openCount ? OPEN_COUNT_LABEL[line.craft.openCount] : undefined,
    line.craft.style,
  ]
    .filter(Boolean)
    .join(' · ')
  const summarySize =
    line.width && line.height ? `${line.width} × ${line.height} m` : '未填宽高'
  const summaryAmount = formatAmount(
    (Number(line.quantity) || 0) * (Number(line.unitPrice) || 0)
  )

  return (
    <div className="rounded-xl border border-neutral-200 bg-white">
      {/* 行项头部 = **摘要行**（issue #4420）：
          收起时也能一眼看懂「什么商品 / 什么工艺 / 多大 / 多少钱」——
          这是「信息偏多、不能全挤一块」的第一层解法：把**结论**常显、把**录入项**收起来。 */}
      <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-neutral-100 bg-neutral-50/60 rounded-t-xl">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!line.collapsed}
          className="flex items-start gap-2.5 text-left min-w-0 flex-1"
        >
          <span className="inline-flex items-center justify-center w-6 h-6 shrink-0 rounded-full bg-primary-600 text-white text-xs font-semibold mt-0.5">
            {index + 1}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5">
              {line.collapsed ? (
                <ChevronRight className="w-3.5 h-3.5 text-neutral-400 shrink-0" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5 text-neutral-400 shrink-0" />
              )}
              {/* 组头已写商品名 ⇒ 行头只写**部位**（issue #4508：不重复显示商品名） */}
              <span className="text-sm font-medium text-neutral-900 truncate">
                部位 {index + 1}
              </span>
              {colorName && (
                <span className="text-xs text-primary-600 shrink-0">{colorName}</span>
              )}
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-neutral-500">
              {summarySpec && <span>{summarySpec}</span>}
              <span className="text-neutral-300">|</span>
              <span className={line.width && line.height ? '' : 'text-amber-600'}>
                {summarySize}
              </span>
              <span className="text-neutral-300">|</span>
              <span className="font-medium text-neutral-700">{summaryAmount}</span>
            </span>
          </span>
        </button>
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-red-600 transition-colors shrink-0"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        )}
      </div>

      {/* ⚠️ **收起用 CSS 隐藏，不卸载**（issue #4489 的组件包发现）：
          组件内的「手改留痕」标志是 `useState`，卸载重挂会丢 —— 手改回「未指定」这一档
          与「从没点过」在 props 上不可区分 ⇒ 重挂后被联动重新覆盖。保持挂载即消除该窄路径。 */}
      <div className={line.collapsed ? 'hidden' : 'p-4'}>

            {/* 尺寸与数量（issue #4420 分区①）：宽 / 高 必填 + 数量 / 单价 */}
            <div className="pt-3 border-t border-neutral-100">
              <div className="flex items-center gap-2 mb-1">
                <Ruler className="w-4 h-4 text-neutral-500" />
                <span className="text-sm font-medium text-neutral-700">尺寸与数量</span>
              </div>
              <p className="mb-3 text-xs text-neutral-400">
                宽 / 高按成品尺寸填，单位米。同一樘窗的布帘与纱帘高度常不同 ⇒ 每个部位各填各的
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
                  {/* 算料来源与公式（issue #4434）—— 公式串**原样渲染后端产出**，前端不自拼 */}
                  {line.metersSource === LINE_METERS_SOURCE_MANUAL ? (
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
                    isAutoCalcUnavailable(line) && (
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

            {/* 加工选项（店铺级目录，与商品解耦 —— issue #4371）。
                issue #4489 判据 3：**默认折叠**（与「特殊选项」同款）—— 商家「太多点选了」，
                未选时只报「未选」，展开才列目录。 */}
            <div className="pt-2 border-t border-neutral-100">
              <button
                type="button"
                onClick={() => setProcessingOpen((v) => !v)}
                aria-expanded={processingOpen}
                className="w-full flex items-center justify-between gap-2 mb-1"
              >
                <span className="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-700">
                  {processingOpen ? (
                    <ChevronDown className="w-4 h-4 text-neutral-400" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-neutral-400" />
                  )}
                  <Settings2 className="w-4 h-4 text-neutral-500" />
                  加工选项
                  <span className="text-xs font-normal text-neutral-400">（可选）</span>
                </span>
                <span
                  className={
                    'text-xs ' +
                    (selectedProcessingCount > 0
                      ? 'text-primary-600 font-medium'
                      : 'text-neutral-400')
                  }
                >
                  {selectedProcessingCount > 0 ? `已选 ${selectedProcessingCount} 项` : '未选'}
                </span>
              </button>
              {processingOpen && (
                <>
              {processingLoading ? (
                <div className="text-sm text-neutral-400 py-2">加工项加载中…</div>
              ) : line.processingItems.length === 0 ? (
                <div className="text-sm text-neutral-400 py-2">暂无可用加工项</div>
              ) : (
                <div className="space-y-2">
                  {line.processingItems.map((pi) => {
                    const cfg = line.selectedProcessing[pi.id] || { selected: false, qty: 1 }
                    const finalPrice = Number(pi.unitPrice) || 0
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
                          <div className="text-xs text-neutral-500 mt-0.5">
                            ¥{finalPrice.toFixed(2)} / {pi.unit || '项'}
                          </div>
                        </div>
                        {/* 加工项行显示「名称 + 数量 + 金额」，数量=面料米数（按米）或 1（按套/一口价/面积）（issue #3005 回滚 #2986） */}
                        {cfg.selected && (
                          <span className="text-sm font-semibold text-primary-600 shrink-0">
                            {Math.max(1, Number(cfg.qty) || 1)}{pi.unit || '项'} ·{' '}
                            {formatAmount(finalPrice * (Math.max(1, Number(cfg.qty) || 1)))}
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
                </>
              )}
            </div>

            {/* 「樘窗」输入已移除（issue #4486，用户裁定「我感觉不需要」）；
                「新增部位」按钮移到**商品组底部**（issue #4485：部位嵌在商品下，不是新开一张商品卡）。 */}

            {/* 工艺规格（§4.2 字段表 A + §4.8 双拼）。
                ⚠️ **不收起**（issue #4508 撤销了 #4493 的「默认收起为摘要」那一层）：
                它把「特殊选项」藏进了**第二层折叠**（用户实测「特殊选项怎么看不到了」）。
                「点选多」这个问题已由**默认档 8 项全覆盖**解决 ⇒ 商家常态本就不用点，
                收起是多余的，还赔上了特殊选项的可见性。 */}
            <div className="pt-3 border-t border-neutral-100">
              <OrderCraftFields
                value={line.craft}
                onChange={onChangeCraft}
                mainMeters={line.quantity}
                edgeMeters={line.edgeMeters}
                onEdgeMetersChange={onEdgeMetersChange}
                edgeUnitPrice={line.edgeUnitPrice}
                onEdgeUnitPriceChange={onEdgeUnitPriceChange}
              />
            </div>
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

