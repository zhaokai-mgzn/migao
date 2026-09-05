'use client'

import { ArrowDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Order } from '@/types'
import { normalizeOrderStatus } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'
import OrderStatusBadge from './OrderStatusBadge'
import RemarkPopover from './RemarkPopover'

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

/** 加工项明细条目（processingInfo.processingItems 中的元素） */
interface ProcessingDetail {
  id?: string
  name?: string
  unitPrice?: number
  quantity?: number
  amount?: number
  subtotal?: number
}

/**
 * 单个订单明细项的加工费合计（#2916）。
 * 列表接口把加工信息嵌套在每个明细项的 processingInfo 内：
 * { processingFee: <该项加工费合计>, processingItems: [{id,name,unitPrice,quantity,subtotal}] }
 * 优先取 processingFee 字段，缺省时按加工项明细（amount/subtotal）求和兜底。
 */
function getItemProcessingFee(pi: Record<string, unknown> | undefined): number {
  if (!pi) return 0
  const direct = Number(pi.processingFee ?? 0)
  if (Number.isFinite(direct) && direct > 0) return direct
  const list = Array.isArray(pi.processingItems) ? (pi.processingItems as ProcessingDetail[]) : []
  return list.reduce((sum, p) => {
    const amt = Number(p?.amount ?? p?.subtotal ?? 0)
    return sum + (Number.isFinite(amt) ? amt : 0)
  }, 0)
}

/** 加工项明细金额：amount → subtotal → unitPrice*quantity 兜底 */
function getProcessingDetailAmount(p: ProcessingDetail): number {
  const amt = Number(p?.amount ?? p?.subtotal ?? 0)
  if (Number.isFinite(amt) && amt > 0) return amt
  const unit = Number(p?.unitPrice ?? 0)
  const qty = Number(p?.quantity ?? 0)
  return (Number.isFinite(unit) ? unit : 0) * (Number.isFinite(qty) ? qty : 0)
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
    // 后端允许退款的状态：confirmed / producing / shipped / completed
    // （前端展示态 pending_shipment 同时覆盖 confirmed + producing）
    const refundable = ['pending_shipment', 'shipped', 'completed'].includes(displayStatus)
    // 已退款标记：refundAmount > 0（退款不再把订单置为 cancelled，订单保持原状态）
    const alreadyRefunded = (order.refundAmount ?? 0) > 0
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
    }
    if (refundable && !alreadyRefunded && onRefund) {
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
          <tr className="bg-neutral-50 text-neutral-600 text-left">
            <th className="pl-2 pr-3 py-3 font-medium w-10">
              <input
                type="checkbox"
                checked={allSelected}
                ref={(el) => {
                  if (el) el.indeterminate = someSelected
                }}
                onChange={toggleAll}
                className="w-4 h-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500"
              />
            </th>
            <th className="pl-0 pr-4 py-3 font-medium whitespace-nowrap">订单ID</th>
            <th className="pl-0 pr-4 py-3 font-medium whitespace-nowrap">采购商品</th>
            <th className="px-4 py-3 font-medium">
              <div className="flex flex-col">
                <span>采购明细</span>
                <span className="text-xs font-normal text-neutral-400">(名称:单价×数量+加工费)</span>
              </div>
            </th>
            <th className="px-4 py-3 font-medium text-right whitespace-nowrap">累计金额(元)</th>
            <th className="px-4 py-3 font-medium text-right whitespace-nowrap">实收款(元)</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">收货人信息</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">
              <span className="inline-flex items-center gap-1">
                下单时间
                <ArrowDown className="w-3.5 h-3.5 text-neutral-400" />
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
              <td colSpan={11} className="px-4 py-16 text-center text-neutral-400">
                加载中…
              </td>
            </tr>
          ) : orders.length === 0 ? (
            <tr>
              <td colSpan={11} className="px-4 py-16 text-center text-neutral-400">
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
                    'border-b border-neutral-100 align-top transition-colors',
                    checked ? 'bg-primary-50/40' : 'hover:bg-neutral-50'
                  )}
                >
                  <td className="pl-2 pr-3 py-4">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleOne(order.id)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-4 h-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500"
                    />
                  </td>

                  {/* 订单ID */}
                  <td className="pl-0 pr-4 py-4 font-mono text-neutral-800 whitespace-nowrap">
                    {order.orderNo || order.id}
                  </td>

                  {/* 采购商品（取第一项展示：名称 + 货号） */}
                  <td className="pl-0 pr-4 py-4 min-w-[160px]">
                    {firstItem ? (
                      <div className="space-y-1">
                        <div className="text-neutral-900 font-medium leading-tight">
                          {firstItem.productName}
                        </div>
                        <div className="text-xs text-neutral-500 leading-tight">
                          货号 {(firstItem as any).skuCode || firstItem.productCode || '-'}
                        </div>
                      </div>
                    ) : (
                      <span className="text-neutral-400">暂无数据</span>
                    )}
                  </td>

                  {/* 采购明细（名称 : 规格 : 单价 : 数量 : 加工费） */}
                  <td className="px-4 py-4 min-w-[280px]">
                    {order.items?.length || order.processingItems?.length ? (
                      <div className="space-y-1.5">
                      {order.items?.map((item) => {
                        // #2916: 加工信息嵌套在明细项 processingInfo 内（列表接口不下发顶层 processingItems）
                        const pi = item.processingInfo
                        const fee = getItemProcessingFee(pi)
                        const procList = (Array.isArray(pi?.processingItems) ? pi.processingItems : []) as ProcessingDetail[]
                        return (
                          <div key={item.id} className="space-y-0.5">
                            <div className="text-neutral-700 leading-tight text-xs">
                              <span>{item.productName || item.productCode || '-'}</span>
                              {': '}
                              <span className="font-mono">{formatNumber(item.unitPrice)}</span>元
                              {' × '}<span className="font-mono">{formatNumber(item.quantity)}</span>米
                              {' = '}<span className="font-mono">{formatNumber(getItemAmount(item))}</span>元
                              {fee > 0 && (
                                <span className="text-neutral-400">{' + 加工费'}<span className="font-mono">{formatNumber(fee)}</span>元</span>
                              )}
                            </div>
                            {procList.length > 0 && procList.map((proc, idx) => (
                              <div
                                key={proc.id || idx}
                                className="text-amber-600 leading-tight text-xs"
                              >
                                <span className="font-medium">{proc.name}</span>
                                {' × '}<span className="font-mono">{formatNumber(proc.unitPrice)}</span>元/米
                                {' × '}<span className="font-mono">{formatNumber(proc.quantity)}</span>米
                                {' = '}<span className="font-mono">{formatNumber(getProcessingDetailAmount(proc))}</span>元
                              </div>
                            ))}
                          </div>
                        )
                      })}
                      </div>
                    ) : (
                      <span className="text-neutral-400">暂无数据</span>
                    )}
                  </td>

                  {/* 累计金额 */}
                  <td className="px-4 py-4 text-right font-mono text-neutral-900 whitespace-nowrap">
                    {formatNumber(order.totalAmount)}
                  </td>

                  {/* 实收款 */}
                  <td className="px-4 py-4 text-right font-mono text-neutral-900 whitespace-nowrap">
                    {formatNumber(order.actualAmount)}
                  </td>

                  {/* 收货人信息 */}
                  <td className="px-4 py-4 min-w-[200px]">
                    <div className="space-y-0.5 text-neutral-700 leading-tight">
                      <div>姓名：{order.customerName || '-'}</div>
                      <div>电话：{order.customerPhone || '-'}</div>
                      <div className="truncate max-w-[220px]" title={order.customerAddress}>
                        地址：{order.customerAddress || '-'}
                      </div>
                    </div>
                  </td>

                  {/* 下单时间 */}
                  <td className="px-4 py-4 whitespace-nowrap">
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
                        <span className="text-xs text-neutral-500 truncate block">
                          💬 {getRemarkPreview(order)}
                        </span>
                      ) : (
                        <span className="text-xs text-neutral-300">-</span>
                      )}
                    </RemarkPopover>
                  </td>

                  {/* 操作 */}
                  <td className="pl-2 pr-3 py-4">{renderActions(order)}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
