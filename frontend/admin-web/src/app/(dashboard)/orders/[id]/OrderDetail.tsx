'use client'

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { ChevronRight, Zap } from 'lucide-react'
import { toast } from 'sonner'
import dayjs from 'dayjs'
import { orderApi } from '@/lib/api'
import { useRouteId } from '@/lib/use-route-id'
import { Button, Loading } from '@/components/ui'
import { OrderProgressSteps } from '@/components/orders'
import CloseOrderModal from '@/components/orders/CloseOrderModal'
import type { Order, OrderItem } from '@/types'
import { normalizeOrderStatus } from '@/types'
import { cn } from '@/lib/utils'

// 格式化金额（含千分位+两位小数）
function formatAmount(amount?: number): string {
  return `¥${(amount ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatDateTime(time?: string): string {
  if (!time) return '-'
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

// 倒计时计算
function calcCountdown(deadline?: string): { h: number; m: number; s: number; expired: boolean } {
  if (!deadline) return { h: 0, m: 0, s: 0, expired: true }
  const diff = dayjs(deadline).diff(dayjs(), 'second')
  if (diff <= 0) return { h: 0, m: 0, s: 0, expired: true }
  const h = Math.floor(diff / 3600)
  const m = Math.floor((diff % 3600) / 60)
  const s = diff % 60
  return { h, m, s, expired: false }
}

// 安全获取明细金额：后端未返回 amount 时依次回退到 subtotal 或 unitPrice*quantity
function getItemAmount(item: OrderItem): number {
  if (typeof item.amount === 'number' && !Number.isNaN(item.amount)) return item.amount
  if (typeof item.subtotal === 'number' && !Number.isNaN(item.subtotal)) return item.subtotal
  const unit = typeof item.unitPrice === 'number' ? item.unitPrice : 0
  const qty = typeof item.quantity === 'number' ? item.quantity : 0
  return unit * qty
}

function getProcessingItemAmount(item: { amount?: number; unitPrice?: number; quantity?: number }): number {
  if (typeof item.amount === 'number' && !Number.isNaN(item.amount)) return item.amount
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
  const [closeModalOpen, setCloseModalOpen] = useState(false)
  const [closeSubmitting, setCloseSubmitting] = useState(false)

  // 倒计时
  const [countdown, setCountdown] = useState({ h: 0, m: 0, s: 0, expired: false })

  // 加载订单
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

  // 待付款倒计时定时器
  useEffect(() => {
    const displayStatus = order ? normalizeOrderStatus(order.status as string) : null
    if (!order || displayStatus !== 'pending_payment' || !order.paymentDeadline) return
    const update = () => setCountdown(calcCountdown(order.paymentDeadline))
    update()
    const timer = setInterval(update, 1000)
    return () => clearInterval(timer)
  }, [order])

  // 关闭订单
  const handleConfirmClose = async (reason: string) => {
    if (!order) return
    setCloseSubmitting(true)
    try {
      await orderApi.closeOrder(order.id, { reason })
      toast.success('订单已关闭')
      setCloseModalOpen(false)
      loadOrder()
    } catch {
      toast.error('关闭订单失败')
    } finally {
      setCloseSubmitting(false)
    }
  }

  const productGroups = useMemo(() => groupItems(order?.items), [order?.items])
  const processingTotal = useMemo(
    () => (order?.processingItems || []).reduce((sum, p) => sum + getProcessingItemAmount(p), 0),
    [order?.processingItems]
  )

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
        <span className="text-gray-900">订单详情</span>
      </div>

      {/* 页面标题 */}
      <h1 className="text-xl font-semibold text-gray-900 mb-5">订单详情</h1>

      {/* 订单状态区域 */}
      <StatusSection
        order={order}
        countdown={countdown}
        onClose={() => setCloseModalOpen(true)}
        onShip={() => router.push(`/orders/${order.id}/ship`)}
      />

      {/* 基础信息 */}
      <SectionCard title="基础信息">
        <div className="grid grid-cols-3 gap-y-4 gap-x-8 text-sm">
          <InfoRow label="订单编号" value={order.orderNo} />
          <InfoRow label="下单时间" value={formatDateTime(order.createdAt)} />
          <InfoRow label="支付时间" value={formatDateTime(order.paidAt)} />
          <InfoRow label="支付交易号" value={order.paymentNo || '-'} />
          <InfoRow label="发货时间" value={formatDateTime(order.shippedAt)} />
          <InfoRow label="确认收货时间" value={formatDateTime(order.receivedAt)} />
        </div>
      </SectionCard>

      {/* 商品信息 */}
      <SectionCard
        title="商品信息"
        rightAction={
          <span className="text-sm text-primary-600 font-medium">
            订单实收款：{formatAmount(order.actualAmount)}元
          </span>
        }
      >
        <ProductTable groups={productGroups} />

        {order.processingItems && order.processingItems.length > 0 && (
          <div className="mt-5">
            <ProcessingTable items={order.processingItems} total={processingTotal} />
          </div>
        )}
      </SectionCard>

      {/* 收货信息 */}
      <SectionCard title="收货信息">
        <div className="grid grid-cols-2 gap-y-4 gap-x-8 text-sm">
          <InfoRow label="收货人" value={order.customerName} />
          <InfoRow label="联系电话" value={order.customerPhone} />
          <div className="col-span-2">
            <InfoRow label="收货地址" value={order.customerAddress || '-'} />
          </div>
        </div>
      </SectionCard>

      {/* 关闭订单弹窗 */}
      <CloseOrderModal
        open={closeModalOpen}
        onClose={() => setCloseModalOpen(false)}
        onConfirm={handleConfirmClose}
        loading={closeSubmitting}
      />
    </div>
  )
}

// ============== 子组件 ==============

interface StatusSectionProps {
  order: Order
  countdown: { h: number; m: number; s: number; expired: boolean }
  onClose: () => void
  onShip: () => void
}

function StatusSection({ order, countdown, onClose, onShip }: StatusSectionProps) {
  const status = normalizeOrderStatus(order.status as string)

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-card p-6 mb-5">
      {status === 'pending_payment' && (
        <div className="flex items-center justify-between">
          <div>
            <div className="text-2xl font-semibold text-red-500 mb-3">待买家付款</div>
            <div className="flex items-center gap-2 text-sm text-gray-700">
              <span className="inline-block w-2 h-2 rounded-full bg-amber-400" />
              <span>
                支付倒计时：
                {countdown.expired ? (
                  <span className="text-red-500">已超时</span>
                ) : (
                  <span className="font-medium">
                    {countdown.h}h {countdown.m}m {countdown.s}s
                  </span>
                )}
              </span>
            </div>
          </div>
          <Button onClick={onClose} className="gap-1.5">
            关闭订单
            <Zap className="w-4 h-4" />
          </Button>
        </div>
      )}

      {status === 'pending_shipment' && (
        <div className="flex items-center justify-between gap-6">
          <div className="flex-1">
            <OrderProgressSteps
              status={status}
              paidAt={order.paidAt}
              shippedAt={order.shippedAt}
              receivedAt={order.receivedAt}
            />
          </div>
          <Button onClick={onShip} className="gap-1.5 shrink-0">
            发货
            <Zap className="w-4 h-4" />
          </Button>
        </div>
      )}

      {status === 'shipped' && (
        <OrderProgressSteps
          status={status}
          paidAt={order.paidAt}
          shippedAt={order.shippedAt}
          receivedAt={order.receivedAt}
        />
      )}

      {status === 'completed' && (
        <OrderProgressSteps
          status={status}
          paidAt={order.paidAt}
          shippedAt={order.shippedAt}
          receivedAt={order.receivedAt}
        />
      )}

      {status === 'closed' && (
        <div>
          <div className="text-2xl font-semibold text-gray-700 mb-2">已关闭</div>
          {order.closeReason && (
            <div className="text-sm text-gray-500">关闭原因：{order.closeReason}</div>
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
    <div className="bg-white rounded-lg border border-gray-200 shadow-card mb-5">
      <div className="flex items-center justify-between px-6 py-3.5 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <span className="inline-block w-1 h-4 bg-primary-500 rounded-sm" />
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
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
      <span className="text-gray-500 shrink-0">{label}：</span>
      <span className="text-gray-900 break-all">{value}</span>
    </div>
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
            <Th align="right">单价</Th>
            <Th align="center">数量</Th>
            <Th align="right">金额</Th>
            <Th align="right">商品合计</Th>
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
                  {formatAmount(getItemAmount(row))}
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
            <Th align="right">单价</Th>
            <Th align="center">数量</Th>
            <Th align="right">金额</Th>
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
                {formatAmount(getProcessingItemAmount(item))}
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
