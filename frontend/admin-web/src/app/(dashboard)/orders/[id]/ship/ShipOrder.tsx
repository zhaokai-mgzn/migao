'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { ChevronRight, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { orderApi, productionApi, processingOrderApi, customerApi } from '@/lib/api'
import { useRouteId } from '@/lib/use-route-id'
import { Button, Loading, SELECT_CONTROL } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { useAuthStore } from '@/store/auth'
import type { Order, OrderItem } from '@/types'
import { cn } from '@/lib/utils'
import { LOGISTICS_COMPANIES, LOGISTICS_TYPES } from '@/lib/logistics'
// 发货幂等键（`X-Client-Request-Id`）的**唯一生成点**（issue #6935 / #6983；列表行内发货共用，issue #8013）
import { newClientRequestId } from '@/lib/client-request-id'
// 商品身份（品名/货号/颜色/门幅）的**唯一读取口**（issue #6882：原先这里直读三个不存在的键）
import { orderItemSku } from '@/lib/order-item-sku'
// 「发货前要不要作业」的唯一读点 + 按型分岔的阻断文案（issue #7079 第 5 包）
import { WORK_ORDER_NEEDED_COPY, workOrderKindOf } from '@/lib/processing-order'

// 可发货订单状态（后端枚举：pending/confirmed/producing/shipped/completed/cancelled；
// producing = 加工单流转后订单进入「生产中」，仍属待发货；'processing' 是历史误写，从不产生）
const SHIPPABLE_STATUSES = new Set(['pending_shipment', 'confirmed', 'producing'])

function formatAmount(amount?: number): string {
  return `¥${(amount ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

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
    group.groupTotal += item.amount || 0
  })
  return Array.from(map.values())
}

export default function ShipOrder() {
  const router = useRouter()
  // useRouteId 已识别 'ship' 后缀，会自动取倒数第 2 段（订单 ID）
  const orderId = useRouteId('id')

  // 发货人默认预填当前登录人姓名（与右上角用户卡片同一条兜底链，但**不**退化为「管理员」
  // ——那是角色名不是人名，印到纸质发货单上就是伪造经手人）；允许改成实际发货人，
  // 留空时后端还会用 SecurityUser.userId 再兜一次（issue #3768）。
  const currentUser = useAuthStore((s) => s.user)
  const defaultShipperName = currentUser?.name || currentUser?.nickname || currentUser?.username || ''

  const [order, setOrder] = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  /**
   * 订单本体读失败（issue #8057）：修前 `catch` 只 `toastRequestError`，`order` 留在 `null`
   * ⇒ 本页印「订单不存在或已被删除」——把**没读到**说成**这张单没了**（与销售订单详情同一种病）。
   */
  const [loadError, setLoadError] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // 加工单前置守卫（issue #3889）：订单详情接口不下发加工单状态，
  // 含加工项订单额外查询加工单；无「已完成」加工单时阻断发货表单
  // （与后端 assertProcessingCompletedBeforeShip「countCompleted==0 拦截」口径一致）。
  const [processingBlocked, setProcessingBlocked] = useState(false)
  const [poChecked, setPoChecked] = useState(false)

  // 物流表单
  const [shippingMethod, setShippingMethod] = useState<'logistics' | 'none'>('logistics')
  const [logisticsType, setLogisticsType] = useState<string>('express')
  const [logisticsCompany, setLogisticsCompany] = useState<string>(LOGISTICS_COMPANIES[0])
  const [logisticsTouched, setLogisticsTouched] = useState(false)
  const [trackingNo, setTrackingNo] = useState('')
  const [shipperName, setShipperName] = useState(defaultShipperName)
  const [shipperTouched, setShipperTouched] = useState(false)

  // 登录用户信息可能晚于首屏到达：仅在用户还没动过该字段时回填，不覆盖手工输入
  useEffect(() => {
    if (!shipperTouched && defaultShipperName) {
      setShipperName(defaultShipperName)
    }
  }, [defaultShipperName, shipperTouched])

  const loadOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    setLoadError(false)
    try {
      const res = await orderApi.getOrder(orderId)
      const data = res.data?.data
      if (data) setOrder(data)
    } catch (e) {
      console.error('加载订单失败:', e)
      setLoadError(true)
      toastRequestError(e, '加载订单详情失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    loadOrder()
  }, [loadOrder])

  const shippable = !!order && SHIPPABLE_STATUSES.has(order.status)

  // 该订单**发货前要不要作业**（issue #7079 第 5 包）：一律取订单详情读面键 `work_order_kind`
  // （后端 `OrderShipGuard.needsWork` 的同一份判据：含加工项 **或** 有卖布行）——
  // 🔴 不再按 `order.processingItems` 推（那只覆盖「含加工项」一半 ⇒ 卖布单**完全不拦**，
  // 用户填完整张表单、提交时才撞服务端那句「须先完成出库作业单的裁剪与打包报工」）。
  const needsWorkOrder = workOrderKindOf(order ?? {}) !== null

  // 作业单状态查询：仅「可发货状态 + 需要作业单」的订单需要（其余短路为已检查）
  useEffect(() => {
    if (!order || !shippable) {
      setPoChecked(true)
      setProcessingBlocked(false)
      return
    }
    if (!needsWorkOrder) {
      setPoChecked(true)
      setProcessingBlocked(false)
      return
    }
    let cancelled = false
    setPoChecked(false)
    processingOrderApi
      .detail(order.id)
      .then((res) => {
        if (cancelled) return
        setProcessingBlocked(res.data?.data?.status !== 'completed')
        setPoChecked(true)
      })
      .catch(() => {
        if (cancelled) return
        // 查询失败/无加工单按后端口径保守阻断（countCompleted==0 不可发货）
        setProcessingBlocked(true)
        setPoChecked(true)
      })
    return () => {
      cancelled = true
    }
  }, [order, shippable, needsWorkOrder])

  /**
   * 订单自带的**常用物流两列**（issue #4874；后端 #4872 在 `orders` 上新增，
   * 下单页选客户时带出并随建单落库）—— 空串/null = 订单没记这一半。
   */
  const orderLogisticsType = (order?.logisticsType ?? '').trim()
  const orderLogisticsCompany = (order?.logisticsCompany ?? '').trim()

  // ① **订单值优先**（issue #4874，用户 2026-09-21：「订单需要……收货信息缺常用物流/快递以及常用公司，
  // 选择客户后要默认带出」）：订单上已经记了这单该用哪家承运商 ⇒ 直接用它，**不回查**客户档案。
  // 用户已手动改过（`logisticsTouched`）⇒ 任何来源都不覆盖（手改留痕，与发货人预填同一口径）。
  useEffect(() => {
    if (logisticsTouched) return
    if (orderLogisticsType) setLogisticsType(orderLogisticsType)
    if (orderLogisticsCompany) setLogisticsCompany(orderLogisticsCompany)
  }, [orderLogisticsType, orderLogisticsCompany, logisticsTouched])

  // ② 订单**没记**的那一半 ⇒ 回落既有的「按订单收货手机号反查客户档案」逻辑（issue #4419）。
  // ⚠️ 既有兜底**不删、不改成门禁**：存量单（建单早于 #4872）订单上两列必为空 ⇒ 只能反查；
  // 反查失败/查不到客户一律静默保持当前值，绝不阻断发货。
  // 用户已手动改过物流字段（logisticsTouched）则不再覆盖 —— 与发货人预填同一口径。
  useEffect(() => {
    const phone = order?.customerPhone
    if (!phone || logisticsTouched) return
    // 订单两半都齐 ⇒ 无需反查（订单值就是权威来源）
    if (orderLogisticsType && orderLogisticsCompany) return
    let cancelled = false
    customerApi
      .getCustomers({ keyword: phone, page: 1, size: 5 })
      .then((res) => {
        if (cancelled) return
        // 关键词是模糊匹配 ⇒ 必须按手机号**精确**命中，否则会把别的客户的常用物流带出来。
        // 两个号码都算命中（issue #4436）：订单带的是**收货电话**，而客户档案里
        // 「默认收货电话」可以≠「账户手机号」（送到工地/仓库、联系人是另一人）——
        // 只认账户手机号会让那类订单静默带不出。
        const hit = (res.data?.data?.items || []).find(
          (c) => c.phone === phone || c.defaultReceiverPhone === phone
        )
        if (!hit) return
        // 只补**订单没记**的那一半（订单有值时不覆盖 —— 这正是「订单优先」的落点）
        if (hit.defaultLogisticsType && !orderLogisticsType) setLogisticsType(hit.defaultLogisticsType)
        if (hit.defaultLogisticsCompany && !orderLogisticsCompany)
          setLogisticsCompany(hit.defaultLogisticsCompany)
      })
      .catch(() => {
        /* 带出失败不影响发货（默认值仍在） */
      })
    return () => {
      cancelled = true
    }
  }, [order?.customerPhone, logisticsTouched, orderLogisticsType, orderLogisticsCompany])

  // 常用公司可能是预置列表之外的自定义承运商 ⇒ 补进下拉，否则 select 显示不出已存值
  const logisticsCompanyOptions = useMemo(() => {
    const list: string[] = [...LOGISTICS_COMPANIES]
    if (logisticsCompany && !list.includes(logisticsCompany)) list.unshift(logisticsCompany)
    return list
  }, [logisticsCompany])

  const productGroups = useMemo(() => groupItems(order?.items), [order?.items])

  /**
   * 本次发货请求的**幂等键**（`X-Client-Request-Id`，issue #6935 / #6983）；`null` = 下一件发货是新事。
   *
   * 生成口径住在 `src/lib/client-request-id.ts`（列表的行内快捷发货 issue #8013 是**同一个写面**的
   * 第二个入口，规则抄两份迟早漂）。本页只负责「何时生成 / 何时作废」：提交期间一次生成、
   * 失败重试复用同值、成功后作废。
   */
  const shipRequestIdRef = useRef<string | null>(null)

  /**
   * 🔴 **发货的唯一提交入口 = 原子端点**（issue #6983）：
   * `POST /api/admin/production/orders/{id}/ship` 在**单事务**里做三件事 ——
   * 记物流 + 原子流转 `shipped` + 建可查的发货单（`order_shipments`），加工单守卫也在里面。
   *
   * ⛔ **不得改回两步老路（先调 `orderApi` 的 updateLogistics，再调它的 updateOrderStatus）**：
   * 那两步既不建发货单（发货单列表永远为空），又非原子（第一步写了物流、第二步失败 ⇒ 部分写入），
   * 且都不带幂等键。类级判据见 `tests/unit/pages/ship-order.test.tsx` 的
   * 「发货页不得再走两步老路」组（扫本文件源码 ⇒ 旧调用回潮即红）。
   */
  const handleSubmit = async () => {
    if (!order) return
    if (!shipperName.trim()) {
      toast.error('请输入发货人')
      return
    }
    if (shippingMethod === 'logistics' && !trackingNo.trim()) {
      toast.error('请输入快递单号')
      return
    }
    setSubmitting(true)
    const clientRequestId = shipRequestIdRef.current ?? newClientRequestId()
    shipRequestIdRef.current = clientRequestId
    try {
      await productionApi.shipOrder(
        order.id,
        {
          company: shippingMethod === 'logistics' ? logisticsCompany : '',
          trackingNo: shippingMethod === 'logistics' ? trackingNo.trim() : '',
          shippingMethod,
          // 物流类型（issue #4419）：express 快递 / logistics 物流专线；无需物流时不写
          logisticsType: shippingMethod === 'logistics' ? logisticsType : undefined,
          shipperName: shipperName.trim(),
        },
        clientRequestId,
      )
      // 成功 ⇒ 作废本次幂等键（下一次发货是一件新事）
      shipRequestIdRef.current = null
      toast.success('发货成功')
      router.push(`/orders/${order.id}`)
    } catch (e) {
      // 失败 ⇒ **保留**该键（重试复用同值：服务端同键回放，不会发两次货）
      toastRequestError(e, '发货失败')
    } finally {
      setSubmitting(false)
    }
  }


  const handleCancel = () => {
    if (order) router.push(`/orders/${order.id}`)
    else router.push('/orders')
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <Loading size="lg" text="加载订单详情..." />
      </div>
    )
  }

  if (!order) {
    // 失败 ≠ 不存在（issue #8057）：没读到时不许印「订单不存在或已被删除」这句事实性断言。
    if (loadError) {
      return (
        <div className="p-6 space-y-4">
          <ListLoadError
            testId="ship-order-load-error"
            message="订单详情加载失败 —— 不是「订单不存在」，是没读到。请检查网络后重试。"
            onRetry={() => void loadOrder()}
            retrying={loading}
          />
          <Button variant="secondary" onClick={() => router.push('/orders')}>返回销售订单</Button>
        </div>
      )
    }
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">订单不存在或已被删除</p>
        <Button onClick={() => router.push('/orders')}>返回销售订单</Button>
      </div>
    )
  }

  // 状态守卫：仅待发货状态可进入发货页。
  if (!SHIPPABLE_STATUSES.has(order.status)) {
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">当前订单状态不允许发货</p>
        <Button onClick={() => router.push(`/orders/${order.id}`)}>返回订单详情</Button>
      </div>
    )
  }

  // 发货前置守卫（issue #3889；issue #7079 第 5 包扩到**卖布单**）：**需要作业单**且作业单未完成
  // → 明确阻断并给可行动出口，不再渲染发货表单 —— 判据 = 读面键 `work_order_kind`（与后端
  // `OrderShipGuard.needsWork` 同一份），阻断文案按型分岔（加工单 / 出库作业单）。
  if (needsWorkOrder && !poChecked) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <Loading size="lg" text="加载订单详情..." />
      </div>
    )
  }
  if (needsWorkOrder && processingBlocked) {
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">
          {WORK_ORDER_NEEDED_COPY[workOrderKindOf(order) ?? 'processing'].shipBlocked}，请返回订单详情处理作业单
        </p>
        <Button onClick={() => router.push(`/orders/${order.id}`)}>返回订单详情</Button>
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
        <button
          onClick={() => router.push(`/orders/${order.id}`)}
          className="hover:text-primary-600 transition-colors"
        >
          订单详情
        </button>
        <ChevronRight className="w-3.5 h-3.5" />
        <span className="text-neutral-900">商品发货</span>
      </div>

      {/* 标题 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-neutral-900">商品发货</h1>
          <Zap className="w-5 h-5 text-amber-500 fill-amber-500" />
        </div>
        {/* 发货**不出纸**（issue #7902）：「发货单」这张纸整体退场，纸统一在销售订单详情的
            打印层里出（用户 2026-10-27 逐字「移除发货单打印」「统一到销售单上打印」）。
            本页只剩「照着屏幕确认商品 → 填运单号 → 确认发货」这一条动作链。 */}
      </div>
      <div className="border-b border-neutral-200 mb-6" />

      {/* 确认商品信息 */}
      <SectionLabel>确认商品信息</SectionLabel>
      <div className="bg-white rounded-lg border border-neutral-200 shadow-card mb-6">
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-neutral-100">
          <div className="flex items-center gap-2">
            <span className="inline-block w-1 h-4 bg-primary-500 rounded-sm" />
            <h2 className="text-base font-semibold text-neutral-900">商品信息</h2>
          </div>
          <span className="text-sm text-primary-600 font-medium">
            订单实收款：{formatAmount(order.actualAmount)}
          </span>
        </div>
        <div className="px-6 py-5">
          <ProductTable groups={productGroups} />
          {/* 加工项表（加工项 | 单价 | 数量 | 金额 | 加工合计）已随 #4882 整表退场 ——
              它与订单详情那张是同构副本，用户已裁定订单详情整表退场（A 方案）；
              发货页留一张同构表 = 把删掉的表换个地方长回来。
              ⚠️ `order.processingItems` 本身**保留**：下方发货守卫 `hasProcessing` 仍以它判「含加工项」。 */}
        </div>
      </div>

      {/* 确认收货信息 */}
      <SectionLabel>确认收货信息</SectionLabel>
      <div className="bg-white rounded-lg border border-neutral-200 shadow-card mb-6">
        <div className="flex items-center gap-2 px-6 py-3.5 border-b border-neutral-100">
          <span className="inline-block w-1 h-4 bg-primary-500 rounded-sm" />
          <h2 className="text-base font-semibold text-neutral-900">收货信息</h2>
        </div>
        <div className="px-6 py-5">
          <div className="grid grid-cols-2 gap-y-4 gap-x-8 text-sm">
            <InfoRow label="收货人" value={order.customerName} />
            <InfoRow label="联系电话" value={order.customerPhone} />
            <div className="col-span-2">
              <InfoRow label="收货地址" value={order.customerAddress || '-'} />
            </div>
          </div>
        </div>
      </div>

      {/* 确认物流 */}
      <SectionLabel>确认物流</SectionLabel>
      <div className="bg-white rounded-lg border border-neutral-200 shadow-card mb-6">
        <div className="px-6 py-6 space-y-5">
          {/* 发货人（发货单纸面「经手人」）：默认当前登录人，可改成实际经手人 */}
          <div className="flex items-center gap-4 text-sm">
            <span className="text-neutral-700 w-20 shrink-0">
              <span className="text-red-500 mr-1">*</span>发货人：
            </span>
            <input
              value={shipperName}
              onChange={(e) => {
                setShipperName(e.target.value)
                setShipperTouched(true)
              }}
              placeholder="请输入实际发货人姓名"
              className={cn(
                'h-9 px-3 rounded border border-neutral-300 bg-white text-sm min-w-[220px]',
                'placeholder:text-neutral-400',
                'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'
              )}
            />
            <span className="text-xs text-neutral-400">默认当前登录人，按实际经手人修改</span>
          </div>

          {/* 发货方式 */}
          <div className="flex items-center gap-4 text-sm">
            <span className="text-neutral-700 w-20 shrink-0">
              <span className="text-red-500 mr-1">*</span>发货方式：
            </span>
            <div className="flex items-center gap-6">
              <RadioOption
                checked={shippingMethod === 'logistics'}
                onChange={() => setShippingMethod('logistics')}
                label="物流发货"
              />
              <RadioOption
                checked={shippingMethod === 'none'}
                onChange={() => setShippingMethod('none')}
                label="无需物流"
              />
            </div>
          </div>

          {/* 物流公司 */}
          {shippingMethod === 'logistics' && (
            <>
              {/* 物流类型（issue #4419）：客户常用物流类型带出，可改；此前 admin-web 从不设置
                  order_logistics.logistics_type ⇒ 一律落库默认 express。
                  与上面「发货方式（物流发货/无需物流）」是两个维度，故命名为「物流类型」。 */}
              <div className="flex items-center gap-4 text-sm">
                <span className="text-neutral-700 w-20 shrink-0">物流类型：</span>
                <div className="flex items-center gap-6">
                  {LOGISTICS_TYPES.map((t) => (
                    <RadioOption
                      key={t.value}
                      checked={logisticsType === t.value}
                      onChange={() => {
                        setLogisticsType(t.value)
                        setLogisticsTouched(true)
                      }}
                      label={t.label}
                    />
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-4 text-sm">
                <span className="text-neutral-700 w-20 shrink-0">
                  <span className="text-red-500 mr-1">*</span>物流公司：
                </span>
                <select
                  value={logisticsCompany}
                  onChange={(e) => {
                    setLogisticsCompany(e.target.value)
                    setLogisticsTouched(true)
                  }}
                  className={cn(SELECT_CONTROL, 'min-w-[220px]')}
                >
                  {logisticsCompanyOptions.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              {/* 快递单号 */}
              <div className="flex items-center gap-4 text-sm">
                <span className="text-neutral-700 w-20 shrink-0">
                  <span className="text-red-500 mr-1">*</span>快递单号：
                </span>
                <input
                  value={trackingNo}
                  onChange={(e) => setTrackingNo(e.target.value)}
                  placeholder="请输入快递单号"
                  className={cn(
                    'h-9 px-3 rounded border border-neutral-300 bg-white text-sm min-w-[320px]',
                    'placeholder:text-neutral-400',
                    'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'
                  )}
                />
              </div>
            </>
          )}
        </div>
      </div>

      {/* 底部操作 */}
      <div className="flex items-center gap-3">
        <Button onClick={handleSubmit} loading={submitting}>
          确认发货
        </Button>
        <Button variant="secondary" onClick={handleCancel} disabled={submitting}>
          取消发货
        </Button>
      </div>

    </div>
  )
}

// ========== 子组件 ==========

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-sm font-medium text-neutral-700 mb-2.5">{children}</div>
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-neutral-500 shrink-0">{label}：</span>
      <span className="text-neutral-900 break-all">{value}</span>
    </div>
  )
}

function RadioOption({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: () => void
  label: string
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-neutral-700">
      <input
        type="radio"
        checked={checked}
        onChange={onChange}
        className="w-4 h-4 border-neutral-300 text-primary-600 focus:ring-primary-500"
      />
      {label}
    </label>
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
            {/* 整表统一居中（issue #7590）：与订单详情页「商品信息」表同一形态 —— 改前 商品/货号/颜色/
                门幅 左对齐、数量居中、金额三列右对齐 ⇒ 三种对齐并存。对齐由下面的 `Th` / `Td` 一处承担。 */}
            <Th>商品</Th>
            <Th>商品货号</Th>
            <Th>颜色</Th>
            <Th>门幅</Th>
            <Th>单价(元/米)</Th>
            <Th>数量(米)</Th>
            <Th>金额(元)</Th>
            <Th>商品合计(元)</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {groups.map((group) =>
            group.rows.map((row, rowIdx) => {
              // 🔴 issue #6882：商品身份四件套走**唯一读取口**。原读 `row.productCode` /
              // `row.color` / `row.specification` —— 这三个键**都不在详情响应里**（`order_items`
              // 表也没有那几列）⇒ 这三列在真单上恒 `-`（真值：货号 `skuCode`、颜色
              // `processingInfo.colorName`、门幅 `processingInfo.doorWidth`）。
              const sku = orderItemSku(row)
              return (
              <tr key={`${group.key}-${row.id || rowIdx}`} className="hover:bg-neutral-50/50">
                {rowIdx === 0 && (
                  <td
                    rowSpan={group.rows.length}
                    className="px-3 py-3 text-center align-top border-r border-neutral-100 font-medium text-neutral-900"
                  >
                    {group.productName}
                  </td>
                )}
                <Td>{sku.code || '-'}</Td>
                <Td>{sku.color || '-'}</Td>
                <Td>{sku.doorWidth || '-'}</Td>
                <Td className="text-red-500 font-medium">
                  {formatAmount(row.unitPrice)}
                </Td>
                <Td className="text-primary-600 font-medium">
                  {row.quantity}
                </Td>
                <Td className="text-primary-600 font-medium">
                  {formatAmount(row.amount)}
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
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}

/** 表头 / 数据格（issue #7590）：**整表一律居中**（口径同订单详情页 `ProductTable`）。
 *
 *  改前对齐是逐列参数（商品/货号/颜色/门幅 左、数量 中、金额三列 右）⇒ 同一张表三种对齐并存。
 *  这两个组件只服务这一张发货页商品表（非导出）⇒ 对齐只有这一处，调用点不再有可漂移的旋钮。 */
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
