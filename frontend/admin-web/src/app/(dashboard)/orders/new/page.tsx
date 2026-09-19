'use client'

import { useEffect, useMemo, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ChevronDown, ChevronRight, Ruler, Search, Package, User, Receipt, Settings2, Plus, Trash2, UserPlus, Phone, MapPin } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { orderApi, productApi, customerApi, processingItemApi, craftCalcApi, type CraftCalcResult, type CraftCalcParams } from '@/lib/api'
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
} from '@/lib/craft-calc-request'
import {
  COMPONENT_ROLE_EDGE,
  METERS_SOURCE_FOLLOW,
  METERS_SOURCE_MANUAL,
  OPEN_COUNT_OPTIONS,
  STYLE_MIXED,
  buildCraftSpec,
  buildEdgeLineCraftSpec,
  buildMainLineGroupKeys,
  buildWindowGroupKey,
  createDefaultCraftSpec,
  resolveWindowCraftLineIds,
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
  product: ProductDetail | null
  productLoading: boolean
  selectedColorId: string | null
  selectedSku: OrderProductSku | null
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
  /**
   * 樘窗名称 / 窗号（issue #4395）：同一樘窗的多条部位行（布行 + 纱行）填**同一个**窗号
   * ⇒ 提交时写同一个 `craftLineId`（樘窗分组）。留空 ⇒ 本行自成一樘窗（存量语义不变）。
   */
  windowLabel: string
  /** 配布边米数（§4.8）；`null` = 未改过 ⇒ 跟随主布米数 */
  edgeMeters: number | null
  /** 配布边单价；`null` = 未填 ⇒ 不生成配布边明细行（后端单价必须 > 0，不凭空造价） */
  edgeUnitPrice: number | null
  /** 卡片是否收起（issue #4420 展示重构）—— 收起只影响渲染，不影响任何录入值 */
  collapsed: boolean
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

function createEmptyLineItem(): OrderLineItem {
  return {
    id: genId(),
    product: null,
    productLoading: false,
    selectedColorId: null,
    selectedSku: null,
    quantity: 1,
    unitPrice: 0,
    width: null,
    height: null,
    processingItems: [],
    selectedProcessing: {},
    // 三条默认档（issue #4420）：加工类型「定高买宽」/ 款式「单色」/ 褶距 0.125 —— 都是真值
    craft: createDefaultCraftSpec(),
    windowLabel: '',
    edgeMeters: null,
    edgeUnitPrice: null,
    collapsed: false,
    metersSource: METERS_SOURCE_FORMULA,
    calc: null,
    calcError: null,
  }
}

/**
 * 「新增部位」（issue #4420）：复制本行的**商品 / 颜色 / 门幅 / 宽高 / 工艺规格**，
 * 只清空「部位」—— 一行 = 一个部位（裁定 R-a），布帘 + 纱帘 = 两行。
 *
 * 为什么继承 `windowLabel`：同一樘窗（一个窗户）的多条部位行要填**同一个窗号**才能绑成一樘窗
 * （#4395，套级工序与加工费按樘窗归属）。新行默认同窗 ⇒ 商家不用再手填一遍。
 *
 * 为什么清空 `curtainType` 而不是留原值：留着会让商家**以为**已经选好了新部位 ——
 * 两行同部位会让加工单长出两套同部位工序（§4.8 的重复计件同族错误）。
 */
function createPositionLine(source: OrderLineItem): OrderLineItem {
  return {
    ...createEmptyLineItem(),
    product: source.product,
    selectedColorId: source.selectedColorId,
    selectedSku: source.selectedSku,
    unitPrice: source.unitPrice,
    width: source.width,
    height: source.height,
    processingItems: source.processingItems,
    craft: { ...source.craft, curtainType: undefined },
    windowLabel: source.windowLabel,
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

  // ===== 费用汇总 =====
  const totals = useMemo(() => {
    let productSubtotal = 0
    let edgeSubtotal = 0
    let processingFee = 0

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
      Object.entries(item.selectedProcessing).forEach(([piId, cfg]) => {
        if (!cfg.selected) return
        const pi = item.processingItems.find((p) => p.id === piId)
        if (!pi) return
        const price = Number(pi.unitPrice) || 0
        const q = Math.max(1, Number(cfg.qty) || 1)
        processingFee += price * q
      })
    })

    return {
      productSubtotal,
      edgeSubtotal,
      processingFee,
      total: productSubtotal + edgeSubtotal + processingFee,
    }
  }, [lineItems])

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
      // 宽 / 高**必填**（issue #4420，用户 2026-09-19 裁定）：
      // 它们是**不可推导的原始输入**（设计 §5.9.3）—— 丢了永远拿不回来，而用料 / 幅数 /
      // 加工单复核全靠它。只存米数 = 把输入扔了只留输出（#4273 的根因形态）。
      if (!(Number(line.width) > 0)) {
        e[`${prefix}_width`] = `第 ${idx + 1} 个商品未填宽（米）`
      }
      if (!(Number(line.height) > 0)) {
        e[`${prefix}_height`] = `第 ${idx + 1} 个商品未填高（米）`
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

    // 樘窗绑组（issue #4395）：同一樘窗的多条**部位行**（布行 + 纱行 + 将来的帘头行）
    // 写**同一个** `craftLineId`。解析规则（未填 / 只有一行 / 代表行取谁）在纯函数里，判据也在那里。
    const windowCraftLineIds = resolveWindowCraftLineIds(
      lineItems.map((l) => ({
        id: l.id,
        windowLabel: l.windowLabel,
        curtainType: l.craft.curtainType,
      }))
    )

    const items: OrderItemFormData[] = lineItems
      .filter((l) => l.product)
      .flatMap((line) => {
        const sku = line.selectedSku
        const colorName =
          uniqueColors(line.product!.skus).find((c) => c.id === line.selectedColorId)?.name

        const processingDetails = Object.entries(line.selectedProcessing)
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

        const lineProcessingFee = processingDetails.reduce(
          (sum, d) => sum + ((d.unitPrice as number) || 0) * ((d.quantity as number) || 0),
          0
        )

        const productSub = (Number(line.quantity) || 0) * (Number(line.unitPrice) || 0)

        // 工艺规格落库（issue #4375 §4.2/§4.5）：只落用户真填了的键（缺值不写）。
        // 拼色（双拼）时主布行额外绑组（§4.8）：componentRole=主布 + craftLineId。
        // 樘窗绑组（issue #4395）：同樘窗的多条部位行共用**同一个** `craftLineId`
        //   —— 拼色行沿用「自指」兜底（§4.8 表注「craftLineId 自指亦可」），但同樘窗有组键时**以组键为准**。
        const edgePrice = edgeUnitPriceOf(line)
        const isPaired = edgePrice !== null
        const windowKey = windowCraftLineIds[line.id]
        const pairKey = windowKey ?? line.id
        const mainSpec = isPaired
          ? { ...buildCraftSpec(line.craft), ...buildMainLineGroupKeys(pairKey) }
          : {
              ...buildCraftSpec(line.craft),
              ...(windowKey ? buildWindowGroupKey(windowKey) : {}),
            }

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
            subtotal: productSub + lineProcessingFee,
            processingInfo:
              processingDetails.length > 0 || sku || colorName || Object.keys(mainSpec).length > 0
                ? {
                    colorId: line.selectedColorId ?? undefined,
                    colorName,
                    skuId: sku?.id,
                    skuCode: sku?.skuCode,
                    sellingMethod: sku?.sellingMethod,
                    doorWidth: sku?.doorWidth,
                    processingFee: lineProcessingFee,
                    processingItems: processingDetails,
                    ...mainSpec,
                  }
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
                {lineItems.map((line, idx) => (
                  <LineItemBlock
                    key={line.id}
                    index={idx}
                    line={line}
                    canRemove={lineItems.length > 1}
                    errors={errors}
                    processingLoading={processingCatalogLoading}
                    onPickProduct={() => openProductModalFor(line.id)}
                    onRemove={() => removeLineItem(line.id)}
                    onSelectColor={(colorId) => handleSelectColor(line, colorId)}
                    onSelectSku={(sku) => handleSelectSku(line, sku)}
                    onChangeQty={(q) => handleLineQtyChange(line, q)}
                    onRestoreFormula={() => restoreFormulaMeters(line)}
                    onChangePrice={(p) => updateLineItem(line.id, { unitPrice: p })}
                    onChangeWidth={(w) => updateLineItem(line.id, { width: w })}
                    onChangeHeight={(h) => updateLineItem(line.id, { height: h })}
                    onToggleCollapsed={() =>
                      updateLineItem(line.id, { collapsed: !line.collapsed })
                    }
                    onAddPosition={() => addPositionLine(line.id)}
                    onToggleProcessing={(pi, sel) => toggleProcessing(line, pi, sel)}
                    onChangeCraft={(patch) =>
                      updateLineItem(line.id, { craft: { ...line.craft, ...patch } })
                    }
                    onChangeWindowLabel={(label) => updateLineItem(line.id, { windowLabel: label })}
                    onEdgeMetersChange={(m) => updateLineItem(line.id, { edgeMeters: m })}
                    onEdgeUnitPriceChange={(p) => updateLineItem(line.id, { edgeUnitPrice: p })}
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

              {/* 行项费用构成（issue #4420 重设计）。
                  此前只有「商品名 ×数量 · ¥单价 +加工 ¥x」一行摘要 —— **看不出钱是怎么来的**，
                  而商家要拿它对报价单与加工单。现在每行摊开成**可核对的算式**：
                  商品「米数 × 单价」、加工项逐条「数量 单位 × 单价」、配布边单列。 */}
              {lineItems.some((l) => l.product) && (
                <div className="mb-4 space-y-3">
                  {lineItems
                    .filter((l) => l.product)
                    .map((line, idx) => {
                      const meters = Number(line.quantity) || 0
                      const unit = Number(line.unitPrice) || 0
                      const sub = meters * unit
                      const procRows = Object.entries(line.selectedProcessing)
                        .filter(([, v]) => v.selected)
                        .map(([piId, cfg]) => {
                          const pi = line.processingItems.find((p) => p.id === piId)
                          const qty = Math.max(1, Number(cfg.qty) || 1)
                          const price = Number(pi?.unitPrice) || 0
                          return {
                            name: pi?.name ?? '加工项',
                            qty,
                            unitLabel: pi?.unit || '项',
                            price,
                            amount: price * qty,
                          }
                        })
                      const procFee = procRows.reduce((s, r) => s + r.amount, 0)
                      const edgePrice = edgeUnitPriceOf(line)
                      const edgeMeters = edgeMetersOf(line)
                      const edgeFee = edgePrice === null ? 0 : edgeMeters * edgePrice
                      return (
                        <div
                          key={line.id}
                          className="rounded-lg border border-neutral-200 overflow-hidden"
                        >
                          <div className="flex items-center justify-between gap-2 px-3 py-2 bg-neutral-50/70">
                            <span className="text-xs font-medium text-neutral-700 truncate">
                              <span className="text-neutral-400 mr-1">{idx + 1}.</span>
                              {line.product?.name}
                              {line.craft.curtainType && (
                                <span className="ml-1.5 font-normal text-neutral-500">
                                  {line.craft.curtainType}
                                </span>
                              )}
                            </span>
                            <span className="text-sm font-semibold text-neutral-900 shrink-0">
                              {formatAmount(sub + procFee + edgeFee)}
                            </span>
                          </div>
                          <div className="px-3 py-2 space-y-1">
                            <CostRow
                              label="商品"
                              expr={`${meters} 米 × ${formatAmount(unit)}/米`}
                              amount={sub}
                            />
                            {procRows.map((r, i) => (
                              <CostRow
                                key={`${r.name}_${i}`}
                                label={r.name}
                                expr={`${r.qty} ${r.unitLabel} × ${formatAmount(r.price)}`}
                                amount={r.amount}
                              />
                            ))}
                            {edgeFee > 0 && edgePrice !== null && (
                              <CostRow
                                label="配布边"
                                expr={`${edgeMeters} 米 × ${formatAmount(edgePrice)}/米`}
                                amount={edgeFee}
                              />
                            )}
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
  onPickProduct: () => void
  onRemove: () => void
  onSelectColor: (colorId: string) => void
  onSelectSku: (sku: OrderProductSku) => void
  onChangeQty: (q: number) => void
  /** 「恢复按公式计算」（issue #4434）：切回算料预填（手改后不会被静默改回，只能显式恢复） */
  onRestoreFormula: () => void
  onChangePrice: (p: number) => void
  /** 成品宽 / 高（米，部位级；issue #4420 必填） */
  onChangeWidth: (w: number | null) => void
  onChangeHeight: (h: number | null) => void
  /** 卡片收起 / 展开（issue #4420）—— 只影响渲染 */
  onToggleCollapsed: () => void
  /** 新增部位（issue #4420）：同一商品下追加一个部位行（布帘 + 纱帘 = 两行） */
  onAddPosition: () => void
  onToggleProcessing: (pi: ProcessingItem, selected: boolean) => void
  onChangeCraft: (patch: Partial<CraftSpecInput>) => void
  /** 樘窗窗号（issue #4395）：同樘窗的多条部位行填同一个值 */
  onChangeWindowLabel: (label: string) => void
  onEdgeMetersChange: (meters: number | null) => void
  onEdgeUnitPriceChange: (price: number | null) => void
}

function LineItemBlock({
  index,
  line,
  canRemove,
  errors,
  processingLoading,
  onPickProduct,
  onRemove,
  onSelectColor,
  onSelectSku,
  onChangeQty,
  onRestoreFormula,
  onChangePrice,
  onChangeWidth,
  onChangeHeight,
  onToggleCollapsed,
  onAddPosition,
  onToggleProcessing,
  onChangeCraft,
  onChangeWindowLabel,
  onEdgeMetersChange,
  onEdgeUnitPriceChange,
}: LineItemBlockProps) {
  const colorOptions = useMemo(
    () => uniqueColors(line.product?.skus),
    [line.product]
  )
  const skuOptions = useMemo(() => {
    if (!line.product?.skus || line.selectedColorId == null) return []
    return line.product.skus.filter((s) => s.colorId === line.selectedColorId)
  }, [line.product, line.selectedColorId])

  const errProduct = errors[`line_${line.id}_product`]
  const errColor = errors[`line_${line.id}_color`]
  const errSpec = errors[`line_${line.id}_spec`]
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
              <span className="text-sm font-medium text-neutral-900 truncate">
                {line.product?.name ?? `商品 ${index + 1}`}
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

      {!line.collapsed && (
      <div className="p-4">
        {/* 商品选择 */}
        <div className="mb-4">
          <Label required>选择商品</Label>
          {line.product ? (
            <div className="flex items-center gap-3 p-3 rounded-lg border border-neutral-200 bg-neutral-50/60">
              {line.product.images?.[0] ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={resolveImageUrl(line.product.images[0])}
                  alt={line.product.name}
                  className="w-14 h-14 rounded object-cover bg-white border border-neutral-200"
                />
              ) : (
                <div className="w-14 h-14 rounded bg-neutral-100 border border-neutral-200 flex items-center justify-center text-neutral-300">
                  <Package className="w-6 h-6" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-neutral-900 truncate">
                  {line.product.name}
                </div>
                <div className="text-xs text-neutral-500 mt-0.5">
                  {line.product.categoryName || '-'} · 货号：{line.product.skuCode || '-'}
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
        {line.product && (
          <>
            {line.productLoading ? (
              <div className="text-sm text-neutral-400 py-4">商品规格加载中…</div>
            ) : (
              <>
                {colorOptions.length > 0 && (
                  <div className="mb-4">
                    <Label required>颜色</Label>
                    <div className="flex flex-wrap gap-2">
                      {colorOptions.map((c) => {
                        const active = line.selectedColorId === c.id
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

                {line.selectedColorId != null && skuOptions.length > 0 && (
                  <div className="mb-4">
                    <Label required>门幅 / 售卖方式</Label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      {skuOptions.map((sku) => {
                        const active = line.selectedSku?.id === sku.id
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

            {/* 尺寸与数量（issue #4420 分区①）：宽 / 高 必填 + 数量 / 单价 */}
            <div className="pt-3 border-t border-neutral-100">
              <div className="flex items-center gap-2 mb-1">
                <Ruler className="w-4 h-4 text-neutral-500" />
                <span className="text-sm font-medium text-neutral-700">尺寸与数量</span>
              </div>
              <p className="mb-3 text-xs text-neutral-400">
                宽 / 高按**成品尺寸**填，单位米。同一樘窗的布帘与纱帘高度常不同 ⇒ 每个部位各填各的
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

            {/* 加工选项（店铺级目录，与商品解耦 —— issue #4371） */}
            <div className="pt-2 border-t border-neutral-100">
              <div className="flex items-center gap-2 mb-3">
                <Settings2 className="w-4 h-4 text-neutral-500" />
                <span className="text-sm font-medium text-neutral-700">加工选项（可选）</span>
              </div>
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
            </div>

            {/* 樘窗与部位（issue #4420 分区④ + #4395 樘窗绑组）：
                一行 = 一个部位（裁定 R-a）⇒ 同一商品的布帘 + 纱帘 = 两行。
                「新增部位」把商品/颜色/门幅/宽高/工艺一次带过去，商家只改部位与差异项。 */}
            <div className="pt-3 border-t border-neutral-100">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <label
                  htmlFor={`window-${line.id}`}
                  className="block text-sm font-medium text-neutral-700"
                >
                  樘窗
                </label>
                <button
                  type="button"
                  onClick={onAddPosition}
                  className="inline-flex items-center gap-1 text-xs font-medium text-primary-600 hover:text-primary-700 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  新增部位
                </button>
              </div>
              <input
                id={`window-${line.id}`}
                type="text"
                placeholder="同窗填同一名称，如 客厅主窗"
                value={line.windowLabel}
                onChange={(e) => onChangeWindowLabel(e.target.value)}
                className="w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              />
              <p className="mt-1.5 text-xs text-neutral-400">
                一樘窗 = 一个窗户。同一扇窗的布帘 / 纱帘各占一行、填同一个窗号才会绑成一樘窗
                （套级工序与加工费按樘窗归属）；留空 = 本行自成一樘窗。
                「新增部位」会带出本行的商品与尺寸，只清空部位。
              </p>
            </div>

            {/* 工艺规格（§4.2 字段表 A + §4.8 双拼）：下单页此前一个工艺字段都不写 */}
            <OrderCraftFields
              value={line.craft}
              onChange={onChangeCraft}
              mainMeters={line.quantity}
              edgeMeters={line.edgeMeters}
              onEdgeMetersChange={onEdgeMetersChange}
              edgeUnitPrice={line.edgeUnitPrice}
              onEdgeUnitPriceChange={onEdgeUnitPriceChange}
            />
          </>
        )}
      </div>
      )}
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

