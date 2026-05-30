'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { ChevronRight, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { orderApi } from '@/lib/api'
import { useRouteId } from '@/lib/use-route-id'
import { Button, Loading } from '@/components/ui'
import type { Order, OrderItem } from '@/types'
import { cn } from '@/lib/utils'

const LOGISTICS_COMPANIES = [
  '德邦快递',
  '顺丰速运',
  '中通快递',
  '圆通速递',
  '韵达快递',
  '申通快递',
]

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

  const [order, setOrder] = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  // 物流表单
  const [shippingMethod, setShippingMethod] = useState<'logistics' | 'none'>('logistics')
  const [logisticsCompany, setLogisticsCompany] = useState(LOGISTICS_COMPANIES[0])
  const [trackingNo, setTrackingNo] = useState('')

  const loadOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    try {
      const res = await orderApi.getOrder(orderId)
      const data = res.data?.data
      if (data) setOrder(data)
    } catch (e) {
      console.error('加载订单失败:', e)
      toast.error('加载订单详情失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    loadOrder()
  }, [loadOrder])

  const productGroups = useMemo(() => groupItems(order?.items), [order?.items])
  const processingTotal = useMemo(
    () => (order?.processingItems || []).reduce((sum, p) => sum + (p.amount || 0), 0),
    [order?.processingItems]
  )

  const handleSubmit = async () => {
    if (!order) return
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
      })
      await orderApi.updateOrderStatus(order.id, { status: 'shipped' })
      toast.success('发货成功')
      router.push(`/orders/${order.id}`)
    } catch {
      toast.error('发货失败')
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
    return (
      <div className="p-6 text-center py-12">
        <p className="text-gray-500 mb-4">订单不存在或已被删除</p>
        <Button onClick={() => router.push('/orders')}>返回订单列表</Button>
      </div>
    )
  }

  return (
    <div className="p-6">
      {/* 面包屑 */}
      <div className="flex items-center gap-1.5 text-sm text-gray-500 mb-3">
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
        <span className="text-gray-900">商品发货</span>
      </div>

      {/* 标题 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold text-gray-900">商品发货</h1>
          <Zap className="w-5 h-5 text-amber-500 fill-amber-500" />
        </div>
      </div>
      <div className="border-b border-gray-200 mb-6" />

      {/* 确认商品信息 */}
      <SectionLabel>确认商品信息</SectionLabel>
      <div className="bg-white rounded-lg border border-gray-200 shadow-card mb-6">
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <span className="inline-block w-1 h-4 bg-primary-500 rounded-sm" />
            <h2 className="text-base font-semibold text-gray-900">商品信息</h2>
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
      <div className="bg-white rounded-lg border border-gray-200 shadow-card mb-6">
        <div className="flex items-center gap-2 px-6 py-3.5 border-b border-gray-100">
          <span className="inline-block w-1 h-4 bg-primary-500 rounded-sm" />
          <h2 className="text-base font-semibold text-gray-900">收货信息</h2>
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
      <div className="bg-white rounded-lg border border-gray-200 shadow-card mb-6">
        <div className="px-6 py-6 space-y-5">
          {/* 发货方式 */}
          <div className="flex items-center gap-4 text-sm">
            <span className="text-gray-700 w-20 shrink-0">
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
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-700 w-20 shrink-0">
                  <span className="text-red-500 mr-1">*</span>物流公司：
                </span>
                <select
                  value={logisticsCompany}
                  onChange={(e) => setLogisticsCompany(e.target.value)}
                  className={cn(
                    'h-9 px-3 pr-9 rounded border border-gray-300 bg-white text-sm appearance-none min-w-[220px]',
                    'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
                    'bg-no-repeat bg-[right_0.75rem_center]'
                  )}
                  style={{
                    backgroundImage:
                      "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
                  }}
                >
                  {LOGISTICS_COMPANIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              {/* 快递单号 */}
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-700 w-20 shrink-0">
                  <span className="text-red-500 mr-1">*</span>快递单号：
                </span>
                <input
                  value={trackingNo}
                  onChange={(e) => setTrackingNo(e.target.value)}
                  placeholder="请输入快递单号"
                  className={cn(
                    'h-9 px-3 rounded border border-gray-300 bg-white text-sm min-w-[320px]',
                    'placeholder:text-gray-400',
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
  return <div className="text-sm font-medium text-gray-700 mb-2.5">{children}</div>
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-gray-500 shrink-0">{label}：</span>
      <span className="text-gray-900 break-all">{value}</span>
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
    <label className="flex items-center gap-2 cursor-pointer text-gray-700">
      <input
        type="radio"
        checked={checked}
        onChange={onChange}
        className="w-4 h-4 border-gray-300 text-primary-600 focus:ring-primary-500"
      />
      {label}
    </label>
  )
}

function ProductTable({ groups }: { groups: ProductGroup[] }) {
  if (groups.length === 0) {
    return <div className="text-center text-gray-400 py-8 text-sm">暂无商品</div>
  }

  return (
    <div className="overflow-x-auto rounded border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-600">
          <tr>
            <Th>商品</Th>
            <Th>商品货号</Th>
            <Th>颜色</Th>
            <Th>规格尺寸</Th>
            <Th align="right">单价(元/米)</Th>
            <Th align="center">数量(米)</Th>
            <Th align="right">金额(元)</Th>
            <Th align="right">商品合计(元)</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {groups.map((group) =>
            group.rows.map((row, rowIdx) => (
              <tr key={`${group.key}-${row.id || rowIdx}`} className="hover:bg-gray-50/50">
                {rowIdx === 0 && (
                  <td
                    rowSpan={group.rows.length}
                    className="px-3 py-3 align-top border-r border-gray-100 font-medium text-gray-900"
                  >
                    {group.productName}
                  </td>
                )}
                <Td>{row.productCode || '-'}</Td>
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
                    className="px-3 py-3 text-right align-top border-l border-gray-100 text-primary-600 font-semibold"
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
    <div className="overflow-x-auto rounded border border-gray-200">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-600">
          <tr>
            <Th>加工项</Th>
            <Th align="right">单价(元/米)</Th>
            <Th align="center">数量(米)</Th>
            <Th align="right">金额(元)</Th>
            <Th align="right">加工合计</Th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {items.map((item, idx) => (
            <tr key={item.id || idx} className="hover:bg-gray-50/50">
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
                  className="px-3 py-3 text-right align-top border-l border-gray-100 text-primary-600 font-semibold"
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
}: {
  children: React.ReactNode
  align?: 'left' | 'right' | 'center'
}) {
  return (
    <th
      className={cn(
        'px-3 py-2.5 text-xs font-semibold text-gray-600 whitespace-nowrap',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        align === 'left' && 'text-left'
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
        'px-3 py-3 text-gray-700',
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
