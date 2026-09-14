'use client'

import type { Order, OrderItem, LogisticsInfo } from '@/types'
import { cn, formatFullDateTime } from '@/lib/utils'

/**
 * 发货单（可打印纸质文档，issue #3768 / UI-040）
 *
 * 设计要点（都是踩过的约束，勿随手改）：
 * 1. **屏幕隐藏、打印可见**：发货页/订单详情页已有各自的屏幕布局，再显示一份会重复；
 *    本组件自带 `display:none` + `@media print` 覆盖，保证屏幕上零视觉改动、
 *    打印时**只有**这份文档（`body * { visibility: hidden }` 隔离，与加工单同套路）。
 * 2. **不得放进 Modal**：`Modal` 面板是 `max-h-full` + 内部 `overflow-y-auto`，
 *    打印只会打出可视区那一屏（多页明细会被裁掉）。故调用方一律渲染在页面级。
 * 3. **每页只挂一份**：`.shipment-print-area` 是全局选择器，挂两份会打印出两套单据。
 * 4. 数据全部取自订单本身（明细不可变，见 OrderItemImmutabilityTest/PG-014），
 *    不需要快照表 —— 这是「发货单不建实体」的依据。
 * 5. 运单号未产生时留空线（纸面手写），不编造。
 */
interface ShipmentDocProps {
  order: Order
  /** 已发货订单的物流（补打时传入）；发货前不传 = 运单号栏留空供纸面填写 */
  logistics?: Pick<LogisticsInfo, 'logisticsCompany' | 'trackingNo' | 'shipperName'> | null
  /** 发货页当前输入的发货人（尚未保存也要印在纸面），优先于 order.logistics */
  shipperName?: string
  className?: string
}

function formatAmount(amount?: number): string {
  return (amount ?? 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatQty(qty?: number): string {
  return String(qty ?? 0)
}

export default function ShipmentDoc({ order, logistics, shipperName, className }: ShipmentDocProps) {
  const items = order.items || []
  const processingItems = order.processingItems || []

  const totalQty = items.reduce((sum, it) => sum + (it.quantity || 0), 0)
  const totalAmount = items.reduce((sum, it) => sum + (it.amount || 0), 0)
  const processingTotal = processingItems.reduce((sum, it) => sum + (it.amount || 0), 0)

  const shipper = (shipperName || logistics?.shipperName || '').trim()
  const company = (logistics?.logisticsCompany || '').trim()
  const trackingNo = (logistics?.trackingNo || '').trim()

  return (
    <div className={cn('shipment-print-area text-neutral-900', className)}>
      <style>{`
        .shipment-print-area { display: none; }
        @page { size: A4; margin: 12mm; }
        @media print {
          body * { visibility: hidden; }
          .shipment-print-area, .shipment-print-area * { visibility: visible; }
          .shipment-print-area {
            display: block;
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
            font-size: 12px;
          }
        }
      `}</style>

      <div className="text-center text-xl font-semibold tracking-[0.5em] mb-1">发货单</div>
      <div className="text-center text-xs text-neutral-500 mb-4">{order.orderNo}</div>

      <table className="w-full border-collapse mb-3">
        <tbody>
          <tr>
            <DocCell label="订单号" value={order.orderNo} />
            <DocCell label="下单时间" value={formatFullDateTime(order.createdAt)} />
          </tr>
          <tr>
            <DocCell label="发货人" value={shipper || undefined} />
            <DocCell label="打印时间" value={formatFullDateTime(new Date().toISOString())} />
          </tr>
        </tbody>
      </table>

      <SectionTitle>收货信息</SectionTitle>
      <table className="w-full border-collapse mb-4">
        <tbody>
          <tr>
            <DocCell label="收货人" value={order.customerName} />
            <DocCell label="联系电话" value={order.customerPhone} />
          </tr>
          <tr>
            <td className="border border-neutral-400 px-2 py-1.5" colSpan={4}>
              <span className="text-neutral-500">收货地址：</span>
              {order.customerAddress || ''}
            </td>
          </tr>
        </tbody>
      </table>

      <SectionTitle>商品明细</SectionTitle>
      {/* table-layout: fixed —— 列宽由表头声明的百分比决定（auto 布局按内容分配，
          长商品名/长地址会把列撑歪，纸面每单都可能不一样）；配合表头 whitespace-nowrap 防折行 */}
      <table className="w-full border-collapse mb-2" style={{ tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <DocTh className="w-[26%]">商品</DocTh>
            <DocTh className="w-[9%]">货号</DocTh>
            <DocTh className="w-[9%]">颜色</DocTh>
            <DocTh className="w-[12%]">规格尺寸</DocTh>
            <DocTh align="right" className="w-[13%]">单价(元/米)</DocTh>
            <DocTh align="right" className="w-[11%]">数量(米)</DocTh>
            <DocTh align="right" className="w-[14%]">金额(元)</DocTh>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && (
            <tr>
              <td className="border border-neutral-400 px-2 py-3 text-center text-neutral-500" colSpan={7}>
                暂无商品明细
              </td>
            </tr>
          )}
          {items.map((item: OrderItem, idx: number) => (
            <tr key={item.id || idx}>
              <DocTd>{item.productName}</DocTd>
              <DocTd>{item.productCode || ''}</DocTd>
              <DocTd>{item.color || ''}</DocTd>
              <DocTd>{item.specification || ''}</DocTd>
              <DocTd align="right">{formatAmount(item.unitPrice)}</DocTd>
              <DocTd align="right">{formatQty(item.quantity)}</DocTd>
              <DocTd align="right">{formatAmount(item.amount)}</DocTd>
            </tr>
          ))}
          {items.length > 0 && (
            <tr>
              <td className="border border-neutral-400 px-2 py-1.5 text-right font-semibold" colSpan={5}>
                合计
              </td>
              <DocTd align="right" bold>
                {formatQty(totalQty)}
              </DocTd>
              <DocTd align="right" bold>
                {formatAmount(totalAmount)}
              </DocTd>
            </tr>
          )}
        </tbody>
      </table>

      {processingItems.length > 0 && (
        <>
          <SectionTitle>加工项</SectionTitle>
          <table className="w-full border-collapse mb-2">
            <thead>
              <tr>
                <DocTh>加工项</DocTh>
                <DocTh align="right">单价(元/米)</DocTh>
                <DocTh align="right">数量(米)</DocTh>
                <DocTh align="right">金额(元)</DocTh>
              </tr>
            </thead>
            <tbody>
              {processingItems.map((item, idx) => (
                <tr key={item.id || idx}>
                  <DocTd>{item.name}</DocTd>
                  <DocTd align="right">{formatAmount(item.unitPrice)}</DocTd>
                  <DocTd align="right">{formatQty(item.quantity)}</DocTd>
                  <DocTd align="right">{formatAmount(item.amount)}</DocTd>
                </tr>
              ))}
              <tr>
                <td className="border border-neutral-400 px-2 py-1.5 text-right font-semibold" colSpan={3}>
                  加工费合计
                </td>
                <DocTd align="right" bold>
                  {formatAmount(processingTotal)}
                </DocTd>
              </tr>
            </tbody>
          </table>
        </>
      )}

      <SectionTitle>备注</SectionTitle>
      <div className="border border-neutral-400 px-2 py-2 mb-4 min-h-[40px] whitespace-pre-wrap">
        {order.remark || ''}
      </div>

      <SectionTitle>物流</SectionTitle>
      <table className="w-full border-collapse">
        <tbody>
          <tr>
            <DocCell label="物流公司" value={company || undefined} />
            <DocCell label="运单号" value={trackingNo || undefined} />
          </tr>
        </tbody>
      </table>
    </div>
  )
}

// ========== 打印友好的表格原子（纯边框、无底色，避免打印丢背景） ==========

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="font-semibold mb-1">{children}</div>
}

function DocCell({ label, value }: { label: string; value?: string }) {
  return (
    <>
      <td className="border border-neutral-400 px-2 py-1.5 w-24 text-neutral-500 whitespace-nowrap">{label}</td>
      <td className="border border-neutral-400 px-2 py-1.5">{value || ''}</td>
    </>
  )
}

function DocTh({
  children,
  align = 'left',
  className,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  className?: string
}) {
  return (
    <th
      className={cn(
        'border border-neutral-400 px-2 py-1.5 font-semibold whitespace-nowrap',
        align === 'right' ? 'text-right' : 'text-left',
        className
      )}
    >
      {children}
    </th>
  )
}

function DocTd({
  children,
  align = 'left',
  bold = false,
}: {
  children: React.ReactNode
  align?: 'left' | 'right'
  bold?: boolean
}) {
  return (
    <td
      className={cn(
        'border border-neutral-400 px-2 py-1.5',
        align === 'right' ? 'text-right' : 'text-left',
        bold && 'font-semibold'
      )}
    >
      {children}
    </td>
  )
}
