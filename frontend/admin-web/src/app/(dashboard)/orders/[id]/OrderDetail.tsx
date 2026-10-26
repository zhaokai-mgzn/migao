'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { ChevronRight, Printer, Zap, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import DateTimeCell from '@/components/common/DateTimeCell'
// 页面码拒绝态（issue #7276）：无 `order:detail` ⇒ 本页直接给「无权访问」，与 layout 的
// `ROUTE_PERMISSION_MAP` 拒绝态**同一个组件**（不新造第二套文案/样式）。
import AccessDenied from '@/components/common/AccessDenied'
// 工序清单读面（issue #6901）：**屏幕**加工单块要印「这一单要做哪几道工序」——
// **复用既有读面** `GET /api/admin/production/orders/{id}/operations`（权限码 order:list，
// 与同页其它读面同码）；**不新造端点、不在展示组件里取数/重算**（组件只负责渲染）。
// 🔴 纸面 `ProcessingDoc` 自 issue #7274 起**不印**工序（用户裁定「工序细节不用在打印单上」）。
import { orderApi, productionApi } from '@/lib/api'
import { useRouteId } from '@/lib/use-route-id'
import { Button, Loading, Modal } from '@/components/ui'
import { OrderProgressSteps, CloseOrderModal, LogisticsForm, RefundOrderModal, ProcessingOrderBlock, ShipmentDoc, QuotationDoc, ProcessingDoc, SalesDoc, OrderUrgencyPanel, EditOrderContentModal, PrintDocPreview, ProcessingQrMissingNotice } from '@/components/orders'
import { PRINT_TARGET_SPECS, usePrintDoc, type PrintTarget } from '@/lib/print-doc'
// 权限（issue #6867 / B5）：补码入口与端点同码显隐（端点方法级 `processing:manage`）
import { usePermission } from '@/lib/permission'
// 「发货前要不要作业」的唯一读点 + 按型分岔的引导句（issue #7079 第 5 包）
import { WORK_ORDER_NEEDED_COPY, workOrderKindOf } from '@/lib/processing-order'
// 费用构成（issue #5843）：详情页原先只算商品金额，与页脚订单级总额（**含**加工费）对不上
// ⇒ 补「商品合计 + 加工费 + 其它构成 = 订单金额」这一块。判定与渲染都在
// `components/orders/OrderFeeBreakdown.tsx` + `lib/order-fee-display.ts`（本页只接线、不自算）。
// ⚠️ 直连组件路径（不走 `@/components/orders` 桶）：订单详情页单测把桶整体替身，
// 直连才能让**真组件**参与渲染（否则「等式可见」这类判据测的是替身 = 空断言）。
import OrderFeeBreakdown from '@/components/orders/OrderFeeBreakdown'
import type { Order, OrderItem, LogisticsFormData, ProcessingOrder, ProductionPosition } from '@/types'
import { normalizeOrderStatus, displayOrderStatus } from '@/types'
import { craftRowsWithoutDoorWidth } from '@/lib/order-item-sku'
// 整卷售卖的分配文案（issue #5846）：**同一份**渲染实现（含负差额告警）——
// 该函数/组件此前只在明细组件里、**没有任何页面渲染它**（功能是没接线的死代码）。
import { RollAllocationNote } from '@/components/orders/OrderItemList'
// 发货读面（issue #5651）：销售单的数量列消费**实发**，判定在 lib 里
import type { OrderShipmentRead } from '@/lib/sales-shipment'
import { cn } from '@/lib/utils'
// 发货方式回填（issue #6254）：判定在 lib 里（本页只接线），口径 = 只透传**真采集到**的取值、
// 未采集（NULL）返回 undefined = 未记录
import { shippingMethodForEdit } from '@/lib/data-adapter'
// 物流方式词表（issue #7850）：详情页「收货信息」块的**只读**读数 —— 复用 `lib/logistics.ts`
// 的单一真值定义，**不新造第二份 express/logistics 中文词表**。
// 🔴 用 `logisticsTypeText()`（枚举转中文、未登记原样回显、缺值 ⇒ null）而**不**用同文件的
// `logisticsTypeLabel()`：后者是**表单**口径（缺值回落「快递」，下拉框需要一个可选中的值），
// 印在只读面上会把「未登记」变成「快递」= 编值（#4419 既有裁定 / #6869 同族）。
import { logisticsTypeText } from '@/lib/logistics'

// 格式化金额（含千分位+两位小数）
function formatAmount(amount?: number): string {
  return `¥${(amount ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

// 🔴 issue #7110：这里原本有个 `calcCountdown`（支付倒计时）。后端**没有**「支付截止」真值
// （`orders` 无列、无写入点、无「超时未付」规则）⇒ 倒计时**从未渲染过**，已连同
// `Order.paymentDeadline` 类型键一起撤下（同 #7078 撤下 `paymentNo` 的处理）。

// 安全获取明细金额：后端未返回 amount 时依次回退到 subtotal 或 unitPrice*quantity
// ⚠️ 只管**商品行**（`order_items` 自己的单价/小计）—— 与 #4882 退场的加工项明细无关。
function getItemAmount(item: OrderItem): number {
  if (typeof item.amount === 'number' && !Number.isNaN(item.amount)) return item.amount
  if (typeof item.subtotal === 'number' && !Number.isNaN(item.subtotal)) return item.subtotal
  const unit = typeof item.unitPrice === 'number' ? item.unitPrice : 0
  const qty = typeof item.quantity === 'number' ? item.quantity : 0
  return unit * qty
}

// 商品分组：同一 productId（或 productName）合并为一组（实现 rowspan 视觉效果）
interface ProductGroup {
  key: string
  productName: string
  rows: OrderItem[]
  groupTotal: number
}

function groupItems(items?: OrderItem[]): ProductGroup[] {
  if (!items || items.length === 0) return []
  const map = new Map<string, ProductGroup>()
  items.forEach((item) => {
    const key = item.productId || item.productName
    if (!map.has(key)) {
      map.set(key, {
        key,
        productName: item.productName,
        rows: [],
        groupTotal: 0,
      })
    }
    const group = map.get(key)!
    group.rows.push(item)
    group.groupTotal += getItemAmount(item)
  })
  return Array.from(map.values())
}

export default function OrderDetailPage() {
  const router = useRouter()
  const orderId = useRouteId('id')

  const [order, setOrder] = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  /**
   * 发货读面（issue #5651 收口）：`null` = 还没取到 / 取失败 —— 销售单据此显式标「未取到」，
   * **不**退回「未发货」的无标记形态。
   */
  const [shipments, setShipments] = useState<OrderShipmentRead | null>(null)
  /**
   * 发货明细读失败（issue #6691）：`shipments === null` 本身**分不出**「还没取到」与「没取到」
   * ⇒ 单独一个失败标记，屏上给「读不到 + 重试」的出口（改前只有 `console.error`，
   * 商家在页面上看不出「销售单数量列印的是订单数量而不是实发」是故障）。
   */
  const [shipmentsReadError, setShipmentsReadError] = useState(false)
  const [closeModalOpen, setCloseModalOpen] = useState(false)
  const [closeSubmitting, setCloseSubmitting] = useState(false)

  // 加工单（ProcessingOrderBlock 经 onStatusChange 上报；issue #3889 发货入口守卫用）
  const [processingOrder, setProcessingOrder] = useState<ProcessingOrder | null>(null)

  /**
   * 工序清单（issue #6901 / #7274）：**屏幕**加工单块（`ProcessingOrderBlock`）要印
   * 「这一单要做哪几道工序」—— 由本页加载后向下传（组件自己不取数）。纸面 `ProcessingDoc`
   * 自 issue #7274 起**不印**工序 ⇒ 不再向下传。
   *
   * 取不到 / 空 ⇒ `[]` ⇒ 屏幕块**不出现**工序清单（缺值不渲染，不印空表）。
   * 失败**不打扰商家**（本轮不弹 toast）：它只影响屏幕加工单块的一块内容，而工序读面失败与
   * 「订单/加工单读失败」不是一回事（后者必须让商家知道）。
   */
  const [orderOperations, setOrderOperations] = useState<ProductionPosition[]>([])

  /**
   * 加工单**缺码**提示的接线（issue #6867 / B5）。
   *
   * 病：存量加工单没有短码（V155 不回填）⇒ 商家直接点「打印加工单」时纸面**静默**印「无码」，
   * 看起来打好了、纸却扫不了。修：缺码时在打印预览上给一条可行动的提示 + 一键补码入口
   * （端点 = 既有 `.../qr-token/regenerate`，issue #4287 —— **不新增后端**）。
   *
   * `blockReloadRef`：补码成功后要把**纸面**上的短链与短码刷新出来 —— 加工单读面在
   * `ProcessingOrderBlock`（它自取自持），故让该块把它的 `load` 交给本页调用（不复制第二份读面）。
   */
  const { has: hasPermission } = usePermission()
  const blockReloadRef = useRef<(() => Promise<void>) | null>(null)
  const canManageProcessing = hasPermission('processing:manage')
  /**
   * 本页**页面码** = `order:detail`（issue #7276）。
   *
   * 病：改前详情读面挂 `order:list` ⇒ 岗位权限页里「订单详情」那个勾选项**勾了不生效**
   * （用户现场：「虽然页面上提示我没权限操作，但是我仍然能访问，RBAC权限没控制住？」）。
   * 修：服务端两个读面收码到 `order:detail`，前端同批加**页内拒绝态** —— 无本码时
   * 直接渲染 `AccessDenied`，且**一个读请求都不发**（不是先请求再看 403）。
   * ⚠️ 这只是体验层：真正的关口是 admin-api 的 `@RequirePermission("order:detail")` 403
   * （前端 `has()` 可被绕过，服务端不可）。
   */
  const canViewOrderDetail = hasPermission('order:detail')
  /**
   * 加工单块（`ProcessingOrderBlock`）的读面码 = `production:view`
   * （`ProcessingOrderController.GET /{id}`）。无本码 ⇒ **不请求、不渲染**：改前它无条件请求，
   * 于是客服/销售/财务（持 `order:detail`、**不持** `production:view`）一进详情页就吃一条
   * 403 「没有权限执行此操作」—— 而同一屏的订单数据却照常渲染，正是用户截图里那句
   * 「提示没权限，但仍然能访问」。**无权限的面不发请求**才是干净形态。
   */
  const canViewProcessingOrder = hasPermission('production:view')
  /** 纸面**确实缺码**（两键都空）—— 有码的单不出现本提示（别对一张有效的纸喊缺码） */
  const processingQrMissing = !processingOrder?.scan_url && !processingOrder?.short_code

  // 确认付款 / 确认收货 / 编辑物流
  const [confirmPaymentOpen, setConfirmPaymentOpen] = useState(false)
  const [paymentSubmitting, setPaymentSubmitting] = useState(false)
  const [confirmReceiveOpen, setConfirmReceiveOpen] = useState(false)
  const [receiveSubmitting, setReceiveSubmitting] = useState(false)
  const [showEditLogistics, setShowEditLogistics] = useState(false)

  /**
   * 修改订单内容（issue #5842）：**仅「待付款」**显示入口（与后端
   * `OrderStatusTransitions.assertContentEditable` 同一口径 —— 只有 pending 可改，其余 422）。
   */
  const [editContentOpen, setEditContentOpen] = useState(false)

  // 退款
  const [refundModalOpen, setRefundModalOpen] = useState(false)
  const [refundSubmitting, setRefundSubmitting] = useState(false)

  /**
   * 本次打印的目标（issue #4965）：本页**同时挂着两份纸质单据**（发货单 `ShipmentDoc` +
   * 报价单 `QuotationDoc`），它们的 `visibility: visible` 打印防御是**同特异性**的兄弟规则
   * ⇒ 后渲染者胜，会把先渲染那份重新藏掉（CI `Demo path specs` 实测红）。故由页面统一置位：
   * 点哪个按钮就只让那份单据显形（另一份的 `visibility` 防御不生效）。
   */
  // 🔴 打印**只能**走这一个入口（issue #5914）：`window.print()` 已收敛进 `usePrintDoc()`
  // 的 effect —— 在 target 提交进 DOM **之后**才开印（同 tick 调 print = 首次打印空白纸）。
  const { printTarget, previewTarget, requestPrint, openPreview, selectPreview, closePreview } = usePrintDoc()

  /**
   * 补码成功后**重新读加工单**（issue #6867 / B5）：纸面读的是 `processingOrder.scan_url` /
   * `short_code`，它们归 `ProcessingOrderBlock` 的读面所有 ⇒ 由该块自刷新（本页不写第二份读面），
   * 刷新结果经既有 `onStatusChange` 回传 ⇒ 预览层与纸面同步拿到新码（提示随之退场）。
   */
  const reloadProcessingForQr = async () => {
    await blockReloadRef.current?.()
  }
  /** 稳定引用（`ProcessingOrderBlock` 的交接 effect 依赖它 ⇒ 每次渲染换一个新函数会让该 effect 空跑） */
  const acceptBlockReload = useCallback((reload: () => Promise<void>) => {
    blockReloadRef.current = reload
  }, [])

  /**
   * 发货明细读面（issue #5651 收口）：销售单数量列要印**实发**（真值 owner = `order_shipment_items`）。
   * 🔴 取不到 ⇒ `null`（**不是** `{shipments: []}`）：纸面会显式标「发货明细未取到」，
   * 绝不把读面故障显示成「未发货」（用缺数据冒充业务状态）。
   *
   * 抽成独立回调是为了给**重试出口**（issue #6691）：`shipments === null` 时页面说不清
   * 是「还在取」还是「没取到」，重试按钮要能**只**重发这一条读面。
   */
  const loadShipments = useCallback(async () => {
    if (!orderId) return
    setShipmentsReadError(false)
    try {
      const shipmentsRes = await orderApi.getOrderShipments(orderId)
      setShipments(shipmentsRes.data?.data ?? null)
    } catch (e) {
      // 拦截器已 toast（issue #6691）：此处只标**失败态**并保留 `null`（=「没取到」的语义）
      console.error('加载发货明细失败:', e)
      setShipmentsReadError(true)
    }
  }, [orderId])

  /**
   * 工序清单（issue #6901）：与订单详情**同一轮**加载（拿到订单后立即取，见 `loadOrder`）。
   * 端点 = 既有读面 `GET /api/admin/production/orders/{id}/operations`（权限码 `order:list`，
   * 与同页其它读面同码）；**不新造端点**。
   *
   * 🔴 失败隔离：读不到 ⇒ 空清单（**屏幕**块不出现工序清单，不编工序、不猜状态），
   * 且**不打扰商家** —— 它只影响屏幕加工单块的一块内容，与「订单详情读失败」不是一回事。
   */
  const loadOperations = useCallback(async () => {
    if (!orderId) return
    try {
      const res = await productionApi.getOrderOperations(orderId)
      setOrderOperations(res.data?.data?.positions ?? [])
    } catch (e) {
      console.error('加载工序清单失败:', e)
      setOrderOperations([])
    }
  }, [orderId])

  // 加载订单
  const loadOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    try {
      const res = await orderApi.getOrder(orderId)
      const data = res.data?.data
      if (data) setOrder(data)
      // 发货明细与工序清单**互不依赖**（一条失败不拖另一条），与订单详情同一轮取完
      await Promise.all([loadShipments(), loadOperations()])
    } catch (e) {
      console.error('加载订单失败:', e)
      toastRequestError(e, '加载订单详情失败')
    } finally {
      setLoading(false)
    }
  }, [orderId, loadShipments, loadOperations])

  useEffect(() => {
    // issue #7276：无 `order:detail` ⇒ **一个读请求都不发**（不是先打再吃 403）
    if (!canViewOrderDetail) {
      setLoading(false)
      return
    }
    loadOrder()
  }, [loadOrder, canViewOrderDetail])

  // 关闭订单
  const handleConfirmClose = async (reason: string) => {
    if (!order) return
    setCloseSubmitting(true)
    try {
      await orderApi.closeOrder(order.id, { reason })
      toast.success('订单已关闭')
      setCloseModalOpen(false)
      loadOrder()
    } catch (e) {
      toastRequestError(e, '关闭订单失败')
    } finally {
      setCloseSubmitting(false)
    }
  }

  // 确认付款
  const handleConfirmPayment = async () => {
    if (!order) return
    setPaymentSubmitting(true)
    try {
      await orderApi.confirmPayment(order.id)
      toast.success('已确认收款')
      setConfirmPaymentOpen(false)
      loadOrder()
    } catch (e) {
      toastRequestError(e, '确认付款失败')
    } finally {
      setPaymentSubmitting(false)
    }
  }

  // 确认收货
  const handleConfirmReceive = async () => {
    if (!order) return
    setReceiveSubmitting(true)
    try {
      await orderApi.updateOrderStatus(order.id, { status: 'completed' })
      toast.success('已确认收货')
      setConfirmReceiveOpen(false)
      loadOrder()
    } catch (e) {
      toastRequestError(e, '确认收货失败')
    } finally {
      setReceiveSubmitting(false)
    }
  }

  // 提交物流信息更新
  const handleSubmitLogistics = async (data: LogisticsFormData) => {
    if (!order) return
    try {
      await orderApi.updateLogistics(order.id, data)
      toast.success('物流信息已更新')
      setShowEditLogistics(false)
      loadOrder()
    } catch (err) {
      toastRequestError(err, '更新物流信息失败')
      throw err // 抛出以阻止 LogisticsForm 自动关闭
    }
  }

  // 提交退款（后端 PUT /api/admin/orders/{id}/refund，退款不改变订单状态）
  const handleConfirmRefund = async (data: { refundAmount: number; refundReason: string }) => {
    if (!order) return
    setRefundSubmitting(true)
    try {
      await orderApi.refundOrder(order.id, data)
      toast.success('退款成功')
      setRefundModalOpen(false)
      loadOrder()
    } catch (e) {
      console.error(e)
      toastRequestError(e, '退款失败')
    } finally {
      setRefundSubmitting(false)
    }
  }

  const productGroups = useMemo(() => groupItems(order?.items), [order?.items])

  // issue #7276：无页面码 ⇒ **直接拒绝态**（服务端同码 403 是第二道；这条只是让商家一眼看懂）
  if (!canViewOrderDetail) {
    return <AccessDenied />
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <Loading size="lg" text="加载订单详情..." />
      </div>
    )
  }

  if (!order) {
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">订单不存在或已被删除</p>
        <Button onClick={() => router.push('/orders')}>返回销售订单</Button>
      </div>
    )
  }

  return (
    <div className="p-6">
      {/* 面包屑 */}
      <div className="flex items-center gap-1.5 text-sm text-neutral-500 mb-3">
        <button onClick={() => router.push('/')} className="hover:text-primary-600 transition-colors">
          首页
        </button>
        <ChevronRight className="w-3.5 h-3.5" />
        {/* issue #5271：组名随侧边栏 IA 改判（原「订单管理」→「交易管理」）—— 页内面包屑必须
            与 Header 的 `ROUTE_BREADCRUMB_MAP`、与真实侧边栏组名一致，否则同屏出现两个组名 */}
        <span>交易管理</span>
        <ChevronRight className="w-3.5 h-3.5" />
        <button onClick={() => router.push('/orders')} className="hover:text-primary-600 transition-colors">
          销售订单
        </button>
        <ChevronRight className="w-3.5 h-3.5" />
        <span className="text-neutral-900">订单详情</span>
      </div>

      {/* 页面标题 + **本页唯一的打印入口**（issue #7544）。
          🔴 入口放在页面级、**不在任何状态分支里**：打印与订单状态无关 —— 已关闭 / 退款中的单子
          同样要能补打报价单或销售单（改前它由 `PRINT_TARGETS_BY_STATUS` 按状态给出，
          这两个状态一个按钮都没有）。要打哪一份由预览层里的单据标签选。 */}
      <div className="flex items-center justify-between gap-3 mb-5">
        <h1 className="text-xl font-semibold text-neutral-900">订单详情</h1>
        <Button
          variant="secondary"
          icon={<Printer className="w-4 h-4" />}
          data-testid="order-print-entry"
          onClick={() => openPreview(DEFAULT_ORDER_PRINT_DOC)}
        >
          打印
        </Button>
      </div>

      {/* 发货明细读失败（issue #6691）：与「还没取到」分开说 —— 这一块读不到时，
          销售单的数量列印的是**订单数量**（不是实发），必须让商家知道 + 给重试出口。 */}
      {shipmentsReadError && (
        <div
          data-testid="order-shipments-read-error"
          role="alert"
          className="mb-4 flex items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800"
        >
          <span>发货明细读取失败 —— 单据数量列会按订单数量打印（不是实发口径），请稍后重试</span>
          <Button variant="secondary" size="sm" data-testid="order-shipments-retry" onClick={() => void loadShipments()}>
            重试
          </Button>
        </div>
      )}

      {/* 订单状态区域 */}
      <StatusSection
        order={order}
        processingOrder={processingOrder}
        onClose={() => setCloseModalOpen(true)}
        onEditContent={() => setEditContentOpen(true)}
        onShip={() => router.push(`/orders/${order.id}/ship`)}
        onConfirmPayment={() => setConfirmPaymentOpen(true)}
        onConfirmReceive={() => setConfirmReceiveOpen(true)}
        onEditLogistics={() => setShowEditLogistics(true)}
        onRefund={() => setRefundModalOpen(true)}
      />

      {/* 基础信息 */}
      <SectionCard title="基础信息">
        <div className="grid grid-cols-3 gap-y-4 gap-x-8 text-sm">
          <InfoRow label="订单编号" value={order.orderNo} />
          <InfoRow label="下单时间" value={<DateTimeCell value={order.createdAt} />} />
          <InfoRow label="支付时间" value={<DateTimeCell value={order.paidAt} />} />
          {/* issue #7078：原「支付交易号」行已**撤下** —— 系统不走在线支付渠道，没有交易号的真值源，
              建了也是恒 "-"（#6882「屏幕面读后端未下发的字段」同类）。前端类型面的 `paymentNo`
              一并删除（编译器成为类级守卫，防再读）。 */}
          <InfoRow label="发货时间" value={<DateTimeCell value={order.shippedAt} />} />
          <InfoRow label="确认收货时间" value={<DateTimeCell value={order.receivedAt} />} />
        </div>
      </SectionCard>

      {/* 加急 / 要求到货日（issue #5177）—— **订单页上直接改**（不是售后页）；
          PUT /api/admin/orders/{id}/urgency；保存后 loadOrder 重新拉单，徽标刷新为服务端真值。 */}
      <OrderUrgencyPanel order={order} onChanged={loadOrder} />

      {/* 商品信息 */}
      <SectionCard
        title="商品信息"
        rightAction={
          <span className="text-sm text-primary-600 font-medium">
            订单实收款：{formatAmount(order.actualAmount)}
          </span>
        }
      >
        <ProductTable groups={productGroups} />

        {/* 费用构成（issue #5843）：商品合计 + 加工费 + 其它构成 = 订单金额 —— 商家照着它对账。
            `goodsTotal` 取「商品合计」列之和（**同一份**行金额口径），加工费那一侧走共享层。 */}
        <OrderFeeBreakdown
          items={order.items ?? []}
          goodsTotal={productGroups.reduce((sum, group) => sum + group.groupTotal, 0)}
          orderTotal={order.totalAmount}
        />

        {/* 加工项表（加工项 | 单价 | 数量 | 金额 | 加工合计）已随 #4882 整表退场：
            加工项不再有单价/计价方式，逐项金额列即无真值可言 ⇒ 不再渲染。
            ⚠️ `order.processingItems` 本身**保留** —— 它是「含加工项」判定与发货守卫
            （下方 `hasProcessing`）的判据源，不是展示物。 */}

        {/* 金额汇总：订单金额 / 优惠金额 / 已退款 / 实收款 — issue #672 */}
        <AmountSummary
          totalAmount={order.totalAmount}
          discountAmount={order.discountAmount}
          actualAmount={order.actualAmount}
          refundAmount={order.refundAmount}
          refundAt={order.refundAt}
        />
      </SectionCard>

      {/* 加工单（issue #3340）：订单 producing 阶段的子进度。
          🔴 issue #7634：本块**只读** —— 派单在「智能派单」页、状态流转在生产明细页；
          订单详情不再传 isUrgent / items（不再直派、不再取批次候选）。 */}
      {canViewProcessingOrder && <ProcessingOrderBlock
        orderId={order.id}
        orderStatus={order.status}
        // issue #7079 第 5 包：要不要作业 / 要哪一型，一律取服务端读面（`work_order_kind`）——
        // 旧写法 `processingItems.length > 0` 只覆盖「含加工项」那一半，卖布单被漏掉 ⇒ 没有生成出口。
        workOrderKind={workOrderKindOf(order)}
        operations={orderOperations}
        onStatusChange={setProcessingOrder}
        onReloadReady={acceptBlockReload}
      />}

      {/* 纸质发货单（issue #3768）：屏幕上隐藏，仅打印呈现；已发货/已完成可在此补打 */}
      <ShipmentDoc order={order} logistics={order.logistics} printTarget={printTarget} />

      {/* 纸质报价单（issue #4965）：屏幕上隐藏，仅打印呈现；照真实报价单 A4 制式
          （每商品行一套 + 金额汇总 + 扫码支付）。页面级挂载一份 —— 与 ShipmentDoc 同范式
          （不进 Modal、每页只挂一份，见组件文件头 6 条约束）。 */}
      <QuotationDoc order={order} printTarget={printTarget} />

      {/* 纸质加工单（A4，issue #5651）：照客户实证制式「按套分块」；右上 QR = **加工单级稳定短链**
          （`processingOrder.scan_url` = `{base}/o/{短码}`，issue #6867）—— **不回落加工单号**：
          回落就退回「扫出来只有一串文本、打不开任何页面」的旧形态。
          页面级挂载一份 —— 与 ShipmentDoc / QuotationDoc 同范式（见 ProcessingDoc 文件头）。 */}
      <ProcessingDoc
        order={order}
        processingOrder={processingOrder}
        printTarget={printTarget}
      />

      {/* 纸质销售单（**三联纸 241mm × 140mm**，issue #5651）：随货给客户的那张；
          🔴 页脚**不印收款码**（issue #7589，用户 2026-10-24 逐字「销售单打印处右下角的二维码移除掉」）
          —— 收款码只留在报价单上。
          `processingOrder` 只用于左上角的**作业单扫码报工码**（issue #7530）：码值取服务端
          `scan_url`，与 `ProcessingDoc` **同一份来源**（不新增读面）；无码 ⇒ 该块不出现。 */}
      <SalesDoc
        order={order}
        shipments={shipments}
        processingOrder={processingOrder}
        printTarget={printTarget}
      />

      {/* 打印前的**纸面自检层**（issue #5914）：真尺寸纸框 + 溢出/页数自检 + 「打印 / 复制截图」。
          🔴 预览实例**不传 printTarget** ⇒ 打印媒体下仍是 display:none（否则一次会出两份）。 */}
      <PrintDocPreview
        target={previewTarget}
        title={previewTarget ? PRINT_TARGET_SPECS[previewTarget].title : ''}
        media={previewTarget ? PRINT_TARGET_SPECS[previewTarget].media : 'a4'}
        onPrint={() => previewTarget && requestPrint(previewTarget)}
        onClose={closePreview}
        docs={ORDER_PRINT_DOCS}
        onSelect={selectPreview}
        notice={
          // 加工单预览才挂缺码提示（issue #6867 / B5）：**有码 ⇒ 什么都不渲染**；
          // 缺码 ⇒ 事实照旧可见（读面事实，谁打印谁受影响），**补码按钮**按 `processing:manage`
          // 显隐（照 #4287 口径，避免「按钮可见却 403」）—— 两条分界都在组件的 props 里。
          previewTarget === 'processing' ? (
            <ProcessingQrMissingNotice
              orderId={order.id}
              missing={processingQrMissing}
              canManage={canManageProcessing}
              onRegenerated={reloadProcessingForQr}
            />
          ) : null
        }
      >
        {/* `inline` = 原地渲染进真尺寸纸框（不 portal 到 body，issue #5914） */}
        {previewTarget === 'shipment' && (
          <ShipmentDoc order={order} logistics={order.logistics} inline />
        )}
        {previewTarget === 'quotation' && <QuotationDoc order={order} inline />}
        {previewTarget === 'processing' && (
          <ProcessingDoc
            order={order}
            processingOrder={processingOrder}
            inline
          />
        )}
        {previewTarget === 'sales' && (
          <SalesDoc order={order} shipments={shipments} processingOrder={processingOrder} inline />
        )}
      </PrintDocPreview>

      {/* 收货信息 */}
      <SectionCard title="收货信息">
        <div className="grid grid-cols-2 gap-y-4 gap-x-8 text-sm">
          <InfoRow label="收货人" value={order.customerName} />
          <InfoRow label="联系电话" value={order.customerPhone} />
          <div className="col-span-2">
            <InfoRow label="收货地址" value={order.customerAddress || '-'} />
          </div>
          {/* **安装小区**（issue #7856）：与收货地址**并列**（两个事实：货发窗帘店 / 帘子装进客户家）。
              缺值 `-` —— 与相邻行同口径（这一片是「读得全」的信息面，不是纸面）。 */}
          <div className="col-span-2">
            <InfoRow label="安装小区" value={order.installCommunity || '-'} />
          </div>
          {/* 物流方式 / 物流公司（issue #7850）：下单页自 #5840 起把这两项当必填，服务端落在
              `orders.logistics_type` / `logistics_company` 两列并随详情读面下发，但本块此前只印
              收货人 / 电话 / 地址 ⇒ 商家在详情页看不出这一单走快递还是物流专线、哪家承运。
              缺值一律印 `-`（本页既有 `InfoRow` 纪律），**不臆造「快递」**。 */}
          <InfoRow label="物流方式" value={logisticsTypeText(order.logisticsType) ?? '-'} />
          <InfoRow label="物流公司" value={order.logisticsCompany?.trim() || '-'} />
        </div>
      </SectionCard>

      {/* 备注信息 */}
      {order.remark && (
        <SectionCard title="备注记录">
          <div className="p-3 bg-neutral-50 rounded-lg">
            <p className="text-sm text-neutral-700 whitespace-pre-wrap">{order.remark}</p>
          </div>
        </SectionCard>
      )}

      {/* 修改订单内容（issue #5842）：仅「待付款」显示入口（后端也只有 pending 可改） */}
      {editContentOpen && order && (
        <EditOrderContentModal
          open={editContentOpen}
          order={order}
          onClose={() => setEditContentOpen(false)}
          onSaved={() => {
            setEditContentOpen(false)
            loadOrder()
          }}
        />
      )}

      {/* 关闭订单弹窗 */}
      <CloseOrderModal
        open={closeModalOpen}
        onClose={() => setCloseModalOpen(false)}
        onConfirm={handleConfirmClose}
        loading={closeSubmitting}
      />

      {/* 确认付款弹窗 */}
      <ConfirmModal
        open={confirmPaymentOpen}
        title="确认付款"
        message="确认已收到付款？确认后订单将进入待发货状态。"
        loading={paymentSubmitting}
        onClose={() => setConfirmPaymentOpen(false)}
        onConfirm={handleConfirmPayment}
      />

      {/* 确认收货弹窗 */}
      <ConfirmModal
        open={confirmReceiveOpen}
        title="确认收货"
        message="确认客户已收到货物？确认后订单将标记为已完成。"
        loading={receiveSubmitting}
        onClose={() => setConfirmReceiveOpen(false)}
        onConfirm={handleConfirmReceive}
      />

      {/* 编辑物流弹窗 */}
      {showEditLogistics && (
        <LogisticsForm
          open={showEditLogistics}
          onClose={() => setShowEditLogistics(false)}
          onSubmit={handleSubmitLogistics}
          initialData={{
            company: order.logistics?.logisticsCompany || '',
            trackingNo: order.logistics?.trackingNo || '',
            // 🔴 未采集（NULL）**不再被读成 `logistics`**（issue #6254）：改前这里是一条
            // 「非 `none` ⇒ `logistics`」的兜底表达式，把「没采集过」静默解释成它的反面语义
            // ⇒ 弹窗保存时会把一条 NULL 记录凭空写成 `logistics`（造数据）。
            shippingMethod: shippingMethodForEdit(order.logistics?.shippingMethod),
            // 发货人可在此纠正（存量订单为空时填上；不动则后端保留原值，不会被编辑人顶替）
            shipperName: order.logistics?.shipperName || '',
          }}
        />
      )}

      {/* 退款弹窗 */}
      <RefundOrderModal
        open={refundModalOpen}
        order={order}
        onClose={() => {
          if (!refundSubmitting) setRefundModalOpen(false)
        }}
        onConfirm={handleConfirmRefund}
        loading={refundSubmitting}
      />
    </div>
  )
}

// 通用确认弹窗
interface ConfirmModalProps {
  open: boolean
  title: string
  message: string
  loading?: boolean
  onClose: () => void
  onConfirm: () => void
}

function ConfirmModal({ open, title, message, loading, onClose, onConfirm }: ConfirmModalProps) {
  return (
    <Modal
      open={open}
      onClose={loading ? () => {} : onClose}
      title={title}
      maskClosable={!loading}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={loading}>
            取消
          </Button>
          <Button onClick={onConfirm} loading={loading}>
            确定
          </Button>
        </>
      }
    >
      <div className="flex items-start gap-2 py-1">
        <AlertTriangle className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" />
        <p className="text-sm text-neutral-700 leading-relaxed">{message}</p>
      </div>
    </Modal>
  )
}

// ============== 子组件 ==============

/**
 * 订单详情可打印的单据与**展示顺序**（issue #7544）—— 与订单状态**无关**：任何状态都能打这几份。
 *
 * 改前这里是一张「订单状态 × 可打单据」的矩阵（#6434），病在两头：
 * ① 已关闭 / 退款中的单子**一张都打不出来**（商家要补一张报价单给客户对账时是死路）；
 * ② 四个按钮常驻在状态卡上，单据一多就把操作行铺满 —— 而它们其实是**同一个动作**的四个选项。
 *
 * => 收敛成一个入口：页面上只有一个「打印」，进来后在预览层的单据标签里选。
 * 顺序 = 用得最频繁的两份在前（销售单随货、加工单下车间），其余按纸型从大到小。
 */
const ORDER_PRINT_DOCS = ['sales', 'processing', 'quotation', 'shipment'] as const satisfies readonly PrintTarget[]

/** 打开打印层时默认选中的单据：销售单（每一单都必然用到的那张） */
const DEFAULT_ORDER_PRINT_DOC: PrintTarget = ORDER_PRINT_DOCS[0]

interface StatusSectionProps {
  order: Order
  /** 加工单（ProcessingOrderBlock 上报；null = 无加工单/未生成/查询失败） */
  processingOrder: ProcessingOrder | null
  onClose: () => void
  /** 修改订单内容（issue #5842）—— **只在「待付款」分支渲染入口**（见 StatusSection 的 pending 段） */
  onEditContent: () => void
  onShip: () => void
  onConfirmPayment: () => void
  onConfirmReceive: () => void
  onEditLogistics: () => void
  onRefund: () => void
}

function StatusSection({
  order,
  processingOrder,
  onClose,
  onEditContent,
  onShip,
  onConfirmPayment,
  onConfirmReceive,
  onEditLogistics,
  onRefund,
}: StatusSectionProps) {
  const status = normalizeOrderStatus(order.status as string)
  const display = displayOrderStatus(order.status as string)
  // issue #3889：producing（生产中）从 pending_shipment 展示中独立（醒目 chip，见 pending_shipment 分支）
  const producing = (order.status as string) === 'producing'
  // 发货入口守卫（issue #3889；issue #7079 第 5 包扩到卖布单）：**需要作业单**且作业单不是「已完成」
  // → 先引导去做作业单，不渲染可点的「发货」。判据 = 服务端读面键 `work_order_kind`
  // （后端 `OrderShipGuard.needsWork` = 含加工项 **或** 有卖布行 —— 与 assertProcessingCompletedBeforeShip
  // 「countCompleted==0 拦截」同一份），不再按 `processingItems` 单侧推。
  const needsWorkOrder = workOrderKindOf(order) !== null
  const processingBlocked = needsWorkOrder && processingOrder?.status !== 'completed'
  // 退款展示不再依赖 'refund' 状态：refundAmount > 0 即视为已退款（订单保持原状态）
  const refunded = (order.refundAmount ?? 0) > 0

  return (
    <div className="bg-white rounded-lg border border-neutral-200 shadow-card p-6 mb-5">
      {refunded && (
        <div className="flex items-center gap-2 mb-4">
          <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-red-50 text-red-600 text-xs font-semibold">
            已退款 {formatAmount(order.refundAmount)}
          </span>
          {order.refundAt && <span className="text-xs text-neutral-500">退款时间：<DateTimeCell value={order.refundAt} /></span>}
        </div>
      )}
      {status === 'pending_payment' && (
        <div className="flex items-center justify-between">
          <div>
            <div className="text-2xl font-semibold text-red-500 mb-3">待买家付款</div>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {/* 修改订单（issue #5842）：买家未付款（待付款）时的内容编辑入口 ——
                收货信息 / 商品明细 / 加工项；金额保存时由服务端重算。
                只在 pending_payment 分支出现：其余状态后端一律 422，界面不给死路。 */}
            <Button variant="secondary" data-testid="edit-order-content" onClick={onEditContent} className="gap-1.5">
              修改订单
            </Button>
            <Button variant="secondary" onClick={onClose} className="gap-1.5">
              关闭订单
            </Button>
            <Button onClick={onConfirmPayment} className="gap-1.5">
              确认付款
              <Zap className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}

      {status === 'pending_shipment' && (
        <div>
          <OrderProgressSteps
            status={status}
            // issue #3916：producing（生产中）独立真实状态，向导第 2 步显示「生产中」
            producing={producing}
            paidAt={order.paidAt}
            shippedAt={order.shippedAt}
            receivedAt={order.receivedAt}
          />
          <div className="mt-6 pt-5 border-t border-neutral-100 flex items-center justify-end gap-3">
            {producing && (
              <span className="mr-auto inline-flex items-center px-2.5 py-1 rounded-full bg-amber-50 text-amber-600 text-xs font-semibold">
                {display.label}
              </span>
            )}
            {!refunded && (
              <Button variant="secondary" onClick={onRefund}>
                退款
              </Button>
            )}
            {processingBlocked ? (
              // 引导句**按型分岔**（issue #7079 第 5 包）：卖布单要的不是「加工单」而是「出库作业单」，
              // 套用加工单文案会让商家在错的单子里找那张纸。
              <span className="text-sm text-amber-600">
                {WORK_ORDER_NEEDED_COPY[workOrderKindOf(order) ?? 'processing'].shipBlocked}
              </span>
            ) : (
              <Button onClick={onShip} className="gap-1.5">
                发货
                <Zap className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
      )}

      {status === 'shipped' && (
        <div>
          <OrderProgressSteps
            status={status}
            paidAt={order.paidAt}
            shippedAt={order.shippedAt}
            receivedAt={order.receivedAt}
          />
          <div className="mt-6 pt-5 border-t border-neutral-100 flex items-center justify-end gap-3">
            {!refunded && (
              <Button variant="secondary" onClick={onRefund}>
                退款
              </Button>
            )}
            <Button variant="secondary" onClick={onEditLogistics}>
              编辑物流
            </Button>
            <Button onClick={onConfirmReceive} className="gap-1.5">
              确认收货
              <Zap className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}

      {status === 'completed' && (
        <div>
          <OrderProgressSteps
            status={status}
            paidAt={order.paidAt}
            shippedAt={order.shippedAt}
            receivedAt={order.receivedAt}
          />
          <div className="mt-6 pt-5 border-t border-neutral-100 flex items-center justify-end gap-3">
            {!refunded && (
              <Button variant="secondary" onClick={onRefund}>
                退款
              </Button>
            )}
          </div>
        </div>
      )}

      {status === 'closed' && (
        <div>
          <div className="text-2xl font-semibold text-neutral-700 mb-2">已关闭</div>
          {order.closeReason && (
            <div className="text-sm text-neutral-500">关闭原因：{order.closeReason}</div>
          )}
        </div>
      )}

      {status === 'refund' && (
        <div className="text-2xl font-semibold text-amber-600">退款/售后中</div>
      )}
    </div>
  )
}

interface SectionCardProps {
  title: string
  rightAction?: React.ReactNode
  children: React.ReactNode
}

function SectionCard({ title, rightAction, children }: SectionCardProps) {
  return (
    <div className="bg-white rounded-lg border border-neutral-200 shadow-card mb-5">
      <div className="flex items-center justify-between px-6 py-3.5 border-b border-neutral-100">
        <div className="flex items-center gap-2">
          <span className="inline-block w-1 h-4 bg-primary-500 rounded-sm" />
          <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
        </div>
        {rightAction}
      </div>
      <div className="px-6 py-5">{children}</div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-neutral-500 shrink-0">{label}：</span>
      <span className="text-neutral-900 break-all">{value}</span>
    </div>
  )
}

/**
 * 工艺规格（issue #4355 / 设计文档 §4.9 ② 订单）。
 *
 * 渲染 `order_items.processing_info` 里**已经落库**的那一份对象（直读，不二次推导 —— §4.9
 * 一致性硬约束：报价单展示的工艺参数必须就是下单落库的那一份）。
 * 缺值不渲染：无任何工艺键 ⇒ 整块不出现（存量单形态）；**绝不**出现 undefined/null/NaN。
 */
function CraftSpecList({ source }: { source?: Record<string, unknown> }) {
  // 🔴 issue #6893：改前直调 `craftSpecRows(source)` —— 它会带出「门幅」行，而本表「规格尺寸」列
  // 上面一行已经印了 `门幅${pi.doorWidth}` ⇒ 同一真值印两处（§31 P2）+ 一个只有标题的
  // 「工艺规格」组。口径 = `craftRowsWithoutDoorWidth()`（= `orderItemSku().specRows` 的同一实现）。
  const rows = craftRowsWithoutDoorWidth(source)
  if (rows.length === 0) return null
  return (
    <div className="mt-1 space-y-0.5" data-testid="order-craft-spec">
      <div className="text-xs font-medium text-neutral-500">工艺规格</div>
      {rows.map((row) => (
        <div key={row.label} className="flex flex-wrap justify-center gap-x-1.5 text-xs">
          <span className="text-neutral-400">{row.label}</span>
          <span className="text-neutral-700">{row.value}</span>
        </div>
      ))}
    </div>
  )
}

function ProductTable({ groups }: { groups: ProductGroup[] }) {
  if (groups.length === 0) {
    return <div className="text-center text-neutral-400 py-8 text-sm">暂无商品</div>
  }

  return (
    <div className="overflow-x-auto rounded border border-neutral-200">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-neutral-600">
          <tr>
            {/* 整表统一居中（issue #7590）：改前 商品/货号/颜色/规格 左对齐、数量居中、金额三列右对齐
                ⇒ 同一张表三种对齐并存，列与列之间没有稳定参照边（用户截图）。
                现在对齐由下面的 `Th` / `Td` 一处承担，调用点不再逐列传 `align`。 */}
            <Th>商品</Th>
            <Th>商品货号</Th>
            <Th>颜色</Th>
            <Th>规格尺寸</Th>
            <Th>单价</Th>
            <Th>数量</Th>
            <Th>金额</Th>
            <Th>商品合计</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {groups.map((group) =>
            group.rows.map((row, rowIdx) => (
              <tr key={`${group.key}-${row.id || rowIdx}`} className="hover:bg-neutral-50/50">
                {rowIdx === 0 && (
                  <td
                    rowSpan={group.rows.length}
                    className="px-3 py-3 text-center align-top border-r border-neutral-100 font-medium text-neutral-900"
                  >
                    {group.productName}
                  </td>
                )}
                {/* 🔴 issue #6882：原读 `row.sku` —— 详情响应里**没有这个键**（真值 = `skuCode`，
                    由 `OrderService.convertToItemResponse` 从 `products.sku_code` 回填）⇒ 这一列恒 `-`。 */}
                <Td>{row.skuCode || '-'}</Td>
                <Td>{(row.processingInfo as any)?.colorName || '-'}</Td>
                <Td>
                  {(() => {
                    const pi = row.processingInfo as any
                    const sm: Record<string, string> = { bulk_cut: '散剪', full_roll: '整卷', per_meter: '按米', per_piece: '按件' }
                    const parts: string[] = []
                    if (pi?.sellingMethod) parts.push(sm[pi.sellingMethod] || pi.sellingMethod)
                    if (pi?.doorWidth) parts.push(`门幅${pi.doorWidth}`)
                    return parts.join(' / ') || '-'
                  })()}
                  {/* 整卷售卖（issue #5846）：订单行显示「整卷 N + 散剪 M 米」——
                      渲染实现与明细组件共用一份（`RollAllocationNote`），负差额在这里也看得见。
                      `roll_count` / `roll_length_m` 任一为空 ⇒ 整块不出现（不编数字）。 */}
                  <RollAllocationNote item={row} withPrefix={false} />
                  {/* 工艺规格（issue #4355 / 设计文档 §4.9 ②）：直读 processing_info，缺值行已丢弃 */}
                  <CraftSpecList source={row.processingInfo} />
                  {/* **部位备注**（issue #5685）：商家写的「这个数字怎么来的」（算料依据的人工说明）。
                      真值 = `order_items.processing_info.remark`（顶层字符串）——**直读、不二次推导**。
                      **缺值不渲染**：键缺席 / `null` / 空串 / 纯空白 ⇒ 该行不出现（不显示空行、
                      不显示 `undefined`）。 */}
                  {typeof (row.processingInfo as any)?.remark === 'string' &&
                    (row.processingInfo as any).remark.trim() !== '' && (
                      <div
                        data-testid="order-item-remark"
                        className="mt-1 flex flex-wrap justify-center gap-x-1.5 text-xs"
                      >
                        <span className="text-neutral-400">部位备注</span>
                        <span className="text-neutral-700">
                          {(row.processingInfo as any).remark}
                        </span>
                      </div>
                    )}
                  {/* **安装位置**（issue #7856）：真值 = 后端投影的 `item.installRoom`
                      （= `processing_info.installRoom`，件级）。**缺值不渲染**：不显示 `-`、
                      不显示空行 —— 与上面「部位备注」同一口径。 */}
                  {typeof row.installRoom === 'string' && row.installRoom.trim() !== '' && (
                    <div
                      data-testid="order-item-install-room"
                      className="mt-1 flex flex-wrap justify-center gap-x-1.5 text-xs"
                    >
                      <span className="text-neutral-400">安装位置</span>
                      <span className="text-neutral-700">{row.installRoom}</span>
                    </div>
                  )}
                </Td>
                <Td className="text-red-500 font-medium">
                  {formatAmount(row.unitPrice)}
                </Td>
                <Td className="text-primary-600 font-medium">
                  {row.quantity}
                </Td>
                <Td className="text-primary-600 font-medium">
                  {formatAmount(getItemAmount(row))}
                </Td>
                {rowIdx === 0 && (
                  <td
                    rowSpan={group.rows.length}
                    className="px-3 py-3 text-center align-top border-l border-neutral-100 text-primary-600 font-semibold"
                  >
                    {formatAmount(group.groupTotal)}
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

/**
 * 表头 / 数据格（issue #7590）：**整表一律居中**。
 *
 * 改前对齐是**逐列参数**（商品/货号/颜色/规格 左、数量 中、单价/金额/商品合计 右）⇒ 同一张表
 * 三种对齐并存。用户裁定「都设计成居中」⇒ 对齐收敛成**表级一条规则**：这两个组件只服务这一张
 * 订单商品表（非导出），要改对齐就改这里，调用点不再有可漂移的旋钮。
 */
function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        'px-3 py-2.5 text-xs font-semibold text-neutral-600 whitespace-nowrap text-center',
        className
      )}
    >
      {children}
    </th>
  )
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={cn('px-3 py-3 text-neutral-700 text-center', className)}>{children}</td>
}

// ===== 金额汇总：订单金额 / 优惠金额 / 已退款 / 实收款 — issue #672 =====
function AmountSummary({
  totalAmount,
  discountAmount,
  actualAmount,
  refundAmount,
  refundAt,
}: {
  totalAmount: number
  discountAmount?: number
  actualAmount: number
  refundAmount?: number
  refundAt?: string
}) {
  const discount = discountAmount ?? 0
  const refunded = (refundAmount ?? 0) > 0
  return (
    <div className="mt-5 pt-4 border-t border-neutral-100">
      <div className="flex items-center gap-6 text-sm">
        <div className="flex items-center gap-2">
          <span className="text-neutral-500">订单金额</span>
          <span className="text-neutral-900 font-medium">{formatAmount(totalAmount)}</span>
        </div>
        <div className="text-neutral-300">|</div>
        <div className="flex items-center gap-2">
          <span className="text-neutral-500">优惠金额</span>
          <span className={discount > 0 ? 'text-green-600 font-medium' : 'text-neutral-900'}>
            {discount > 0 ? `-${formatAmount(discount)}` : formatAmount(0)}
          </span>
        </div>
        {refunded && (
          <>
            <div className="text-neutral-300">|</div>
            <div className="flex items-center gap-2">
              <span className="text-neutral-500">已退款</span>
              <span className="text-red-600 font-semibold">{formatAmount(refundAmount)}</span>
              {refundAt && (
                <span className="text-xs font-normal text-neutral-400">(<DateTimeCell value={refundAt} />)</span>
              )}
            </div>
          </>
        )}
        <div className="text-neutral-300">|</div>
        <div className="flex items-center gap-2">
          <span className="text-neutral-500">实收款</span>
          <span className="text-primary-600 font-semibold">{formatAmount(actualAmount)}</span>
        </div>
      </div>
    </div>
  )
}
