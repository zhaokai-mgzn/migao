'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { ChevronRight, Printer, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { orderApi, processingOrderApi, customerApi } from '@/lib/api'
import { useRouteId } from '@/lib/use-route-id'
import { Button, Loading } from '@/components/ui'
import { ShipmentDoc } from '@/components/orders'
import { useAuthStore } from '@/store/auth'
import type { Order, OrderItem } from '@/types'
import { cn } from '@/lib/utils'
import { LOGISTICS_COMPANIES, LOGISTICS_TYPES } from '@/lib/logistics'

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
    try {
      const res = await orderApi.getOrder(orderId)
      const data = res.data?.data
      if (data) setOrder(data)
    } catch (e) {
      console.error('加载订单失败:', e)
      toastRequestError(e, '加载订单详情失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    loadOrder()
  }, [loadOrder])

  const shippable = !!order && SHIPPABLE_STATUSES.has(order.status)

  // 加工单状态查询：仅「可发货状态 + 含加工项」的订单需要（其余短路为已检查）
  useEffect(() => {
    if (!order || !shippable) {
      setPoChecked(true)
      setProcessingBlocked(false)
      return
    }
    const hasProcessing = (order.processingItems?.length ?? 0) > 0
    if (!hasProcessing) {
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
  }, [order, shippable])

  // 客户常用物流档案（issue #4419）：按订单收货手机号反查客户档案，带出常用物流方式/公司。
  // 「带出」是增强而非门禁：查不到客户 / 请求失败一律静默保持默认值，绝不阻断发货。
  // 用户已手动改过物流字段（logisticsTouched）则不再覆盖 —— 与发货人预填同一口径。
  useEffect(() => {
    const phone = order?.customerPhone
    if (!phone || logisticsTouched) return
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
        if (hit.defaultLogisticsType) setLogisticsType(hit.defaultLogisticsType)
        if (hit.defaultLogisticsCompany) setLogisticsCompany(hit.defaultLogisticsCompany)
      })
      .catch(() => {
        /* 带出失败不影响发货（默认值仍在） */
      })
    return () => {
      cancelled = true
    }
  }, [order?.customerPhone, logisticsTouched])

  // 常用公司可能是预置列表之外的自定义承运商 ⇒ 补进下拉，否则 select 显示不出已存值
  const logisticsCompanyOptions = useMemo(() => {
    const list: string[] = [...LOGISTICS_COMPANIES]
    if (logisticsCompany && !list.includes(logisticsCompany)) list.unshift(logisticsCompany)
    return list
  }, [logisticsCompany])

  const productGroups = useMemo(() => groupItems(order?.items), [order?.items])
  const processingTotal = useMemo(
    () => (order?.processingItems || []).reduce((sum, p) => sum + (p.amount || 0), 0),
    [order?.processingItems]
  )

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
    try {
      await orderApi.updateLogistics(order.id, {
        company: shippingMethod === 'logistics' ? logisticsCompany : '',
        trackingNo: shippingMethod === 'logistics' ? trackingNo.trim() : '',
        shippingMethod,
        // 物流类型（issue #4419）：express 快递 / logistics 物流专线；无需物流时不写
        logisticsType: shippingMethod === 'logistics' ? logisticsType : undefined,
        shipperName: shipperName.trim(),
      })
      await orderApi.updateOrderStatus(order.id, { status: 'shipped' })
      toast.success('发货成功')
      router.push(`/orders/${order.id}`)
    } catch (e) {
      toastRequestError(e, '发货失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handlePrint = () => {
    window.print()
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
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">订单不存在或已被删除</p>
        <Button onClick={() => router.push('/orders')}>返回订单列表</Button>
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

  // 加工单前置守卫（issue #3889）：含加工项且加工单未完成 → 明确阻断，不再渲染发货表单
  const hasProcessing = (order.processingItems?.length ?? 0) > 0
  if (hasProcessing && !poChecked) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <Loading size="lg" text="加载订单详情..." />
      </div>
    )
  }
  if (hasProcessing && processingBlocked) {
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">该订单含加工项，须先完成加工单后再发货，请返回订单详情处理加工单</p>
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
        <span>订单管理</span>
        <ChevronRight className="w-3.5 h-3.5" />
        <button onClick={() => router.push('/orders')} className="hover:text-primary-600 transition-colors">
          订单列表
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
        {/* 发货前置动作：先打纸面发货单照着拣货/打包，再回来填运单号确认发货 */}
        <Button variant="secondary" onClick={handlePrint} className="gap-1.5">
          <Printer className="w-4 h-4" />
          打印发货单
        </Button>
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
            订单实收款：{formatAmount(order.actualAmount)}元
          </span>
        </div>
        <div className="px-6 py-5">
          <ProductTable groups={productGroups} />
          {order.processingItems && order.processingItems.length > 0 && (
            <div className="mt-5">
              <ProcessingTable items={order.processingItems} total={processingTotal} />
            </div>
          )}
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
                  className={cn(
                    'h-9 px-3 pr-9 rounded border border-neutral-300 bg-white text-sm appearance-none min-w-[220px]',
                    'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                    'bg-no-repeat bg-[right_0.75rem_center]'
                  )}
                  style={{
                    backgroundImage:
                      "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
                  }}
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

      {/*
        纸质发货单：屏幕上隐藏（display:none），仅 @media print 呈现 ——
        本页屏幕布局已有商品/收货信息，再显示一份会重复；发货前打印时物流栏留空供手写，
        发货后如需带运单号/发货人的单据，到订单详情页「打印发货单」补打。
      */}
      <ShipmentDoc order={order} shipperName={shipperName} />
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
            <Th className="pl-0">商品</Th>
            <Th className="pl-0">商品货号</Th>
            <Th>颜色</Th>
            <Th>规格尺寸</Th>
            <Th align="right">单价(元/米)</Th>
            <Th align="center">数量(米)</Th>
            <Th align="right">金额(元)</Th>
            <Th align="right">商品合计(元)</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {groups.map((group) =>
            group.rows.map((row, rowIdx) => (
              <tr key={`${group.key}-${row.id || rowIdx}`} className="hover:bg-neutral-50/50">
                {rowIdx === 0 && (
                  <td
                    rowSpan={group.rows.length}
                    className="pl-0 pr-3 py-3 align-top border-r border-neutral-100 font-medium text-neutral-900"
                  >
                    {group.productName}
                  </td>
                )}
                <Td className="pl-0">{row.productCode || '-'}</Td>
                <Td>{row.color || '-'}</Td>
                <Td>{row.specification || '-'}</Td>
                <Td align="right" className="text-red-500 font-medium">
                  {formatAmount(row.unitPrice)}
                </Td>
                <Td align="center" className="text-primary-600 font-medium">
                  {row.quantity}
                </Td>
                <Td align="right" className="text-primary-600 font-medium">
                  {formatAmount(row.amount)}
                </Td>
                {rowIdx === 0 && (
                  <td
                    rowSpan={group.rows.length}
                    className="px-3 py-3 text-right align-top border-l border-neutral-100 text-primary-600 font-semibold"
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

function ProcessingTable({
  items,
  total,
}: {
  items: NonNullable<Order['processingItems']>
  total: number
}) {
  return (
    <div className="overflow-x-auto rounded border border-neutral-200">
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-neutral-600">
          <tr>
            <Th>加工项</Th>
            <Th align="right">单价(元/米)</Th>
            <Th align="center">数量(米)</Th>
            <Th align="right">金额(元)</Th>
            <Th align="right">加工合计</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-100">
          {items.map((item, idx) => (
            <tr key={item.id || idx} className="hover:bg-neutral-50/50">
              <Td>{item.name}</Td>
              <Td align="right">{formatAmount(item.unitPrice)}</Td>
              <Td align="center" className="text-primary-600 font-medium">
                {item.quantity}
              </Td>
              <Td align="right" className="text-red-500 font-medium">
                {formatAmount(item.amount)}
              </Td>
              {idx === 0 && (
                <td
                  rowSpan={items.length}
                  className="px-3 py-3 text-right align-top border-l border-neutral-100 text-primary-600 font-semibold"
                >
                  {formatAmount(total)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Th({
  children,
  align = 'left',
  className,
}: {
  children: React.ReactNode
  align?: 'left' | 'right' | 'center'
  className?: string
}) {
  return (
    <th
      className={cn(
        'px-3 py-2.5 text-xs font-semibold text-neutral-600 whitespace-nowrap',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        align === 'left' && 'text-left',
        className
      )}
    >
      {children}
    </th>
  )
}

function Td({
  children,
  align = 'left',
  className,
}: {
  children: React.ReactNode
  align?: 'left' | 'right' | 'center'
  className?: string
}) {
  return (
    <td
      className={cn(
        'px-3 py-3 text-neutral-700',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        align === 'left' && 'text-left',
        className
      )}
    >
      {children}
    </td>
  )
}
