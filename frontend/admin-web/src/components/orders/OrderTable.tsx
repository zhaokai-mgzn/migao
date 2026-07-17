'use client'

import { ArrowDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Order } from '@/types'
import { normalizeOrderStatus } from '@/types'
import RemarkPopover from './RemarkPopover'
import DateTimeCell from '@/components/common/DateTimeCell'
import OrderStatusBadge from './OrderStatusBadge'

/**
 * #1289: 获取备注列触发器的预览文本。
 * 优先使用 order.remark（旧字符串），否则从 order.remarks[] 取最新一条的 content。
 */
function getRemarkPreview(order: Order): string {
  if (order.remark) {
    return order.remark.replace(/^\[[\d\-:\s]+\]\s*/gm, '')
  }
  if (order.remarks && order.remarks.length > 0) {
    const sorted = [...order.remarks].sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    )
    return sorted[0].content
  }
  return ''
}

export interface OrderTableProps {
  orders: Order[]
  loading: boolean
  selectedIds: string[]
  onSelectChange: (ids: string[]) => void
  onView: (order: Order) => void
  onRemark: (order: Order) => void
  onClose: (order: Order) => void
  onShip: (order: Order) => void
  onRefund?: (order: Order) => void
  onConfirmPayment?: (order: Order) => void
  onConfirmReceive?: (order: Order) => void
}

function formatNumber(value: number | undefined): string {
  if (value === undefined || value === null) return '0'
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

/** 安全获取明细金额：amount → subtotal → unitPrice*quantity 三级兜底 */
function getItemAmount(item: { amount?: number; subtotal?: number; unitPrice?: number; quantity?: number }): number {
  if (typeof item.amount === 'number' && !Number.isNaN(item.amount)) return item.amount
  if (typeof item.subtotal === 'number' && !Number.isNaN(item.subtotal)) return item.subtotal
  const unit = typeof item.unitPrice === 'number' ? item.unitPrice : 0
  const qty = typeof item.quantity === 'number' ? item.quantity : 0
  return unit * qty
}

function ActionLink({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className="text-primary-600 hover:text-primary-700 hover:underline transition-colors"
    >
      {children}
    </button>
  )
}

export default function OrderTable({
  orders,
  loading,
  selectedIds,
  onSelectChange,
  onView,
  onRemark,
  onClose,
  onShip,
  onRefund,
  onConfirmPayment,
  onConfirmReceive,
}: OrderTableProps) {
  const allSelected = orders.length > 0 && orders.every((o) => selectedIds.includes(o.id))
  const someSelected = orders.some((o) => selectedIds.includes(o.id)) && !allSelected

  const toggleAll = () => {
    if (allSelected) {
      onSelectChange(selectedIds.filter((id) => !orders.find((o) => o.id === id)))
    } else {
      const newIds = Array.from(new Set([...selectedIds, ...orders.map((o) => o.id)]))
      onSelectChange(newIds)
    }
  }

  const toggleOne = (id: string) => {
    if (selectedIds.includes(id)) {
      onSelectChange(selectedIds.filter((sid) => sid !== id))
    } else {
      onSelectChange([...selectedIds, id])
    }
  }

  const renderActions = (order: Order) => {
    const displayStatus = normalizeOrderStatus(order.status as string)
    const actions: React.ReactNode[] = [
      <ActionLink key="view" onClick={() => onView(order)}>查看</ActionLink>,
      <ActionLink key="remark" onClick={() => onRemark(order)}>备注</ActionLink>,
    ]
    if (displayStatus === 'pending_payment') {
      actions.push(<ActionLink key="close" onClick={() => onClose(order)}>关闭</ActionLink>)
      if (onConfirmPayment) {
        actions.push(
          <ActionLink key="confirm-payment" onClick={() => onConfirmPayment(order)}>
            确认付款
          </ActionLink>
        )
      }
    } else if (displayStatus === 'pending_shipment') {
      actions.push(<ActionLink key="ship" onClick={() => onShip(order)}>发货</ActionLink>)
    } else if (displayStatus === 'shipped' && onConfirmReceive) {
      actions.push(
        <ActionLink key="confirm-receive" onClick={() => onConfirmReceive(order)}>
          确认收货
        </ActionLink>
      )
    } else if (displayStatus === 'refund' && onRefund) {
      actions.push(<ActionLink key="refund" onClick={() => onRefund(order)}>处理退款</ActionLink>)
    }
    return (
      <div className="flex items-center gap-3 whitespace-nowrap">
        {actions.map((action, idx) => (
          <span key={idx}>{action}</span>
        ))}
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 text-gray-600 text-left">
            <th className="px-4 py-3 font-medium w-10">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected
                }}
                onChange={toggleAll}
                className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
              />
            </th>
            <th className="pl-0 pr-4 py-3 font-medium whitespace-nowrap">订单ID</th>
            <th className="pl-0 pr-4 py-3 font-medium whitespace-nowrap">采购商品</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">
              <div className="flex flex-col">
                <span>采购明细</span>
                <span className="text-xs font-normal text-gray-400">(名称:单价×数量+加工费)</span>
              </div>
            </th>
            <th className="px-4 py-3 font-medium text-right whitespace-nowrap">累计金额(元)</th>
            <th className="px-4 py-3 font-medium text-right whitespace-nowrap">实收款(元)</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">收货人信息</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">
              <span className="inline-flex items-center gap-1">
                下单时间
                <ArrowDown className="w-3.5 h-3.5 text-gray-400" />
              </span>
            </th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">状态</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">备注</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">操作</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={11} className="px-4 py-16 text-center text-gray-400">
                加载中…
              </td>
            </tr>
          ) : orders.length === 0 ? (
            <tr>
              <td colSpan={11} className="px-4 py-16 text-center text-gray-400">
                暂无数据
              </td>
            </tr>
          ) : (
            orders.map((order) => {
              const checked = selectedIds.includes(order.id)
              const firstItem = order.items?.[0]
              return (
                <tr
                  key={order.id}
                  className={cn(
                    'border-b border-gray-100 align-top transition-colors',
                    checked ? 'bg-primary-50/40' : 'hover:bg-gray-50'
                  )}
                >
                  <td className="px-4 py-4">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleOne(order.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                    />
                  </td>

                  {/* 订单ID */}
                  <td className="pl-0 pr-4 py-4 font-mono text-gray-800 whitespace-nowrap">
                    {order.orderNo || order.id}
                  </td>

                  {/* 采购商品（取第一项展示：名称 + 货号） */}
                  <td className="pl-0 pr-4 py-4 min-w-[160px]">
                    {firstItem ? (
                      <div className="space-y-1">
                        <div className="text-gray-900 font-medium leading-tight">
                          {firstItem.productName}
                        </div>
                        <div className="text-xs text-gray-500 leading-tight">
                          货号 {(firstItem as any).skuCode || firstItem.productCode || '-'}
                        </div>
                      </div>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>

                  {/* 采购明细（名称 : 规格 : 单价 : 数量 : 加工费） */}
                  <td className="px-4 py-4 min-w-[280px]">
                    <div className="space-y-1.5">
                      {order.items?.map((item) => {
                        const pi = (item as any).processingInfo
                        const fee = pi?.totalAmount || pi?.totalFee || 0
                        return (
                          <div key={item.id} className="text-gray-700 leading-tight text-xs">
                            <span>{item.productName || item.productCode || '-'}</span>
                            {': '}
                            <span className="font-mono">{formatNumber(item.unitPrice)}</span>元
                            {' × '}<span className="font-mono">{formatNumber(item.quantity)}</span>米
                            {' = '}<span className="font-mono">{formatNumber(getItemAmount(item))}</span>元
                            {fee > 0 && (
                              <span className="text-gray-400">{' + 加工费'}<span className="font-mono">{formatNumber(fee)}</span>元</span>
                            )}
                          </div>
                        )
                      })}
                      {order.processingItems?.map((proc, idx) => (
                        <div
                          key={proc.id || idx}
                          className="text-amber-600 leading-tight text-xs"
                        >
                          <span className="font-medium">{proc.name}</span>
                          {' × '}<span className="font-mono">{formatNumber(proc.unitPrice)}</span>元/米
                          {' × '}<span className="font-mono">{formatNumber(proc.quantity)}</span>米
                          {' = '}<span className="font-mono">{formatNumber(proc.amount)}</span>元
                        </div>
                      ))}
                    </div>
                  </td>

                  {/* 累计金额 */}
                  <td className="px-4 py-4 text-right font-mono text-gray-900 whitespace-nowrap">
                    {formatNumber(order.totalAmount)}
                  </td>

                  {/* 实收款 */}
                  <td className="px-4 py-4 text-right font-mono text-gray-900 whitespace-nowrap">
                    {formatNumber(order.actualAmount)}
                  </td>

                  {/* 收货人信息 */}
                  <td className="px-4 py-4 min-w-[200px]">
                    <div className="space-y-0.5 text-gray-700 leading-tight">
                      <div>姓名：{order.customerName || '-'}</div>
                      <div>电话：{order.customerPhone || '-'}</div>
                      <div className="truncate max-w-[220px]" title={order.customerAddress}>
                        地址：{order.customerAddress || '-'}
                      </div>
                    </div>
                  </td>

                  {/* 下单时间 */}
                  <td className="px-4 py-4">
                    <DateTimeCell value={order.createdAt} />
                  </td>

                  {/* 状态 */}
                  <td className="px-4 py-4 whitespace-nowrap">
                    <OrderStatusBadge status={normalizeOrderStatus(order.status as string)} />
                  </td>

                  {/* 备注预览 — #1289: 同时检查 remark 字符串和 remarks[] 数组 */}
                  <td className="px-4 py-4 min-w-[100px] max-w-[160px]">
                    <RemarkPopover remark={order.remark} remarks={order.remarks}>
                      {order.remark || (order.remarks && order.remarks.length > 0) ? (
                        <span className="text-xs text-gray-500 truncate block">
                          💬 {getRemarkPreview(order)}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-300">-</span>
                      )}
                    </RemarkPopover>
                  </td>

                  {/* 操作 */}
                  <td className="px-4 py-4">{renderActions(order)}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
