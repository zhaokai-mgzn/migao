'use client'

import { ArrowDown, Check, Copy } from 'lucide-react'
import { Fragment, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { OrderBrief } from '@/types'
import { normalizeOrderStatus } from '@/types'
import { Badge, Button, RowActions } from '@/components/ui'
import type { RowActionItem } from '@/components/ui'
import DateTimeCell from '@/components/common/DateTimeCell'
import OrderStatusBadge from './OrderStatusBadge'
import { isUrgentFlag, urgentBadgeText } from '@/lib/order-urgency'
import { processingFeeOf } from '@/lib/order-fee-display'
import RemarkPopover from './RemarkPopover'
// 行内快捷发货录入区（issue #8013）：展开在该行**下方**，不跳页、不用遮罩模态
import InlineShipForm from './InlineShipForm'
import { printDocTypeLabel } from '@/lib/print-doc'

/**
 * #1289: 获取备注列触发器的预览文本。
 * 优先使用 order.remark（旧字符串），否则从 order.remarks[] 取最新一条的 content。
 */
function getRemarkPreview(order: OrderBrief): string {
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

/** 列表「打印」列的悬浮说明：打了几次、打过哪些单据（缺值不编） */
export function printStatusTitle(order: OrderBrief): string {
  const count = order.printCount ?? 0
  const docs = (order.printedDocTypes ?? []).map((t) => printDocTypeLabel(t)).filter(Boolean)
  const parts = [`已打印 ${count} 次`]
  if (docs.length > 0) parts.push(`单据：${docs.join(' / ')}`)
  return parts.join(' · ')
}

/**
 * 最近打印时间的**紧凑**形态（列表列宽有限）：今年内 ⇒ `MM-DD HH:mm`，跨年 ⇒ `YYYY-MM-DD`。
 * 与 `DateTimeCell` 的区别：这里要的是"多久以前"，不是完整时间戳（完整值在详情页流水里）。
 */
export function formatPrintedAt(value: string, now: Date = new Date()): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  const sameYear = d.getFullYear() === now.getFullYear()
  const md = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  return sameYear ? `${md} ${pad(d.getHours())}:${pad(d.getMinutes())}` : `${d.getFullYear()}-${md}`
}

export interface OrderTableProps {
  /** 🔴 issue #6882：列表行是**列表形态**（明细没有 `id`/`skuCode`，但有 `productCode`= 真货号）。
   *  用详情类型 `Order` 接列表响应 = 让「详情字段在列表上也可选」的谎话继续成立。 */
  orders: OrderBrief[]
  loading: boolean
  onView: (order: OrderBrief) => void
  onRemark: (order: OrderBrief) => void
  onClose: (order: OrderBrief) => void
  /**
   * 兜底路径：跳**既有**发货页 `/orders/{id}/ship`。
   *
   * issue #8013 起主行动「发货」不再跳页（走 `onToggleShip` 就地展开）——本回调只在页面
   * 没接行内形态时兜底（老调用方 / 组件级测试），形态与改前一致。
   */
  onShip?: (order: OrderBrief) => void
  /**
   * issue #8013（列表即队列）：点行内主行动「发货」⇒ **展开 / 收起**该行下方的紧凑录入区。
   *
   * 与 `onShip` 的分工：本回调在场 ⇒ 行内形态（**不发生路由跳转**）；缺席 ⇒ 回退到 `onShip`。
   */
  onToggleShip?: (order: OrderBrief) => void
  /** 当前展开了录入区的订单 id（`null`/缺省 = 全部收起；收起态**不进 DOM**，不是 CSS 隐藏） */
  shippingOrderId?: string | null
  /** 录入区提交成功 ⇒ 页面收起 + **按既有方式刷新列表**（行状态随服务端真值更新 / 按筛选移出） */
  onShipped?: () => void
  /** 既有发货页仍是兜底路径（issue #8013 第 ⑤ 条）—— ⋯ 菜单里的「去发货页」 */
  onGoShipPage?: (order: OrderBrief) => void
  onRefund?: (order: OrderBrief) => void
  onConfirmPayment?: (order: OrderBrief) => void
  onConfirmReceive?: (order: OrderBrief) => void
  /**
   * 表体空态文案（issue #6733）。
   *
   * 🔴 本组件用的是**自有表体空态行**（不是共享 `ui/Table`），而「这次读到底成没成」是**页面**的事
   * （`/orders` 的 `loadError`）—— 组件自己看不见它。默认 `'暂无数据'` 保持改前行为不变；
   * 页面在读失败时传**空串**（失败原因由常驻失败面说），否则一屏会出现三种说法打架：
   * 计数「共 — 条」（不可知）+ 表体「暂无数据」（没有数据）+ 横幅「读失败」。
   */
  emptyText?: string
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

/**
 * 行内「⋯」菜单（issue #8011 由本表首例；issue #8038 收成**共享原语** `ui/RowActions`）。
 *
 * 本表是那一形态的首例，改前实现就写在本文件里；#8038 把它抽到 `components/ui/RowActions.tsx`
 * （`products` / `knowledge` 同批接入）—— 菜单的开合、键盘可达、`fixed` 落点、**收起态不进 DOM**
 * 现在**只有一份实现**。这里**不再**保留本地副本：抄一份 = 第二份会漂的口径
 * （`RowActionLink` 头注释已登记过同款教训）。
 *
 * 本表自己的判据（形态/主行动派生/复制订单号）：`tests/unit/pages/orders-list-row-actions.test.tsx`。
 */

/** 订单号复制（issue #8011）：17 位纯数字手抄必错，给一个**明确的**复制入口 */
async function copyOrderNo(orderNo: string) {
  try {
    await navigator.clipboard.writeText(orderNo)
    toast.success('订单号已复制')
  } catch {
    // 复制失败不能静默（否则用户以为已复制、粘出来是旧内容）—— 给出可执行的手动路径
    toast.error('复制失败，请手动选中订单号复制')
  }
}

export default function OrderTable({
  orders,
  loading,
  onView,
  onRemark,
  onClose,
  onShip,
  onToggleShip,
  shippingOrderId = null,
  onShipped,
  onGoShipPage,
  onRefund,
  onConfirmPayment,
  onConfirmReceive,
  emptyText = '暂无数据',
}: OrderTableProps) {
  /**
   * 焦点归位（issue #8027）：行内录入区**收起**后，把焦点还给触发它的那个「发货」按钮。
   *
   * 改前三条收起路径（提交成功 / `Escape` / 「取消」）最后焦点都落 `body` —— 连续录单时
   * 键盘 / 读屏用户每单都要重新找回位置。
   *
   * 🔴 **提交成功那条不能"收起时顺手 `focus()` 一下就完"**：`onShipped` 同时触发列表刷新，
   *    `loading` 期间表体整体换成「加载中…」（行按钮被卸载）⇒ 收起那一帧根本没有可聚焦的按钮。
   *    所以这里记下「欠谁一次焦点」，等行回来再还；行被刷新移出列表（按筛选筛掉）就放弃，
   *    不去抢别处的焦点。
   *
   * 落点 = **这一行的主行动按钮**：提交成功后行状态翻成已发货时，它已经是「确认收货」
   * （「发货」触发器随状态消失 ⇒ 焦点落在同一位置的新主行动，而不是掉回 `body`）。
   */
  const primaryButtonRefs = useRef(new Map<string, HTMLButtonElement>())
  const prevShippingOrderId = useRef<string | null>(shippingOrderId)
  const pendingFocusOrderId = useRef<string | null>(null)

  useEffect(() => {
    const prev = prevShippingOrderId.current
    prevShippingOrderId.current = shippingOrderId
    if (prev !== shippingOrderId) {
      // 只有**收起**才搬焦点（换行展开 / 再次展开都不搬 —— 焦点该留在用户点的那一处）
      pendingFocusOrderId.current = shippingOrderId === null ? prev : null
    }
    if (loading || pendingFocusOrderId.current === null) return
    const target = pendingFocusOrderId.current
    pendingFocusOrderId.current = null
    primaryButtonRefs.current.get(target)?.focus()
  }, [shippingOrderId, loading])

  /**
   * 行内操作（issue #8011）：**1 个主行动 + 1 个「⋯」菜单**。
   *
   * 主行动按**订单状态**派生（待付款→收款 / 待发货→发货 / 已发货→确认收货 / 其它→无主行动），
   * 其余动作收进菜单。🔴 **逐条保持改前的条件与回调** —— 本次只动**形态**，不动权限判断、
   * 不动「哪些状态哪些动作可做」（红灯面：`refundable` / `alreadyRefunded` / 可选回调缺省）。
   */
  const renderActions = (order: OrderBrief) => {
    const displayStatus = normalizeOrderStatus(order.status as string)
    // 后端允许退款的状态：confirmed / producing / shipped / completed
    // （前端展示态 pending_shipment 同时覆盖 confirmed + producing）
    const refundable = ['pending_shipment', 'shipped', 'completed'].includes(displayStatus)
    // 已退款标记：refundAmount > 0（退款不再把订单置为 cancelled，订单保持原状态）
    const alreadyRefunded = (order.refundAmount ?? 0) > 0

    // 主行动：**只**按状态派生；回调缺席（页面没接线）⇒ 同样不渲染，不摆一个点不动的按钮
    const primary: RowActionItem | null =
      displayStatus === 'pending_payment' && onConfirmPayment
        ? { key: 'payment', label: '收款', onClick: () => onConfirmPayment(order) }
        : displayStatus === 'pending_shipment' && (onToggleShip || onShip)
          ? {
              key: 'ship',
              label: '发货',
              // issue #8013：列表即队列 —— **就地展开**录入区（不跳页）；没接行内形态时回退发货页
              onClick: () => (onToggleShip ? onToggleShip(order) : onShip?.(order)),
            }
          : displayStatus === 'shipped' && onConfirmReceive
            ? { key: 'receive', label: '确认收货', onClick: () => onConfirmReceive(order) }
            : null

    const menuItems: RowActionItem[] = [
      { key: 'view', label: '查看详情', onClick: () => onView(order) },
      { key: 'remark', label: '备注', onClick: () => onRemark(order) },
    ]
    if (displayStatus === 'pending_payment') {
      menuItems.push({ key: 'close', label: '关闭订单', onClick: () => onClose(order) })
    }
    if (refundable && !alreadyRefunded && onRefund) {
      menuItems.push({ key: 'refund', label: '处理退款', onClick: () => onRefund(order) })
    }
    if (displayStatus === 'pending_shipment' && onGoShipPage) {
      // 兜底路径（issue #8013 第 ⑤ 条）：既有整页发货表单仍在 —— 想看商品 / 收货人再发货时走它
      menuItems.push({ key: 'ship-page', label: '去发货页', onClick: () => onGoShipPage(order) })
    }

    return (
      <RowActions
        testId={`order-actions-${order.id}`}
        menuTestId={`order-menu-${order.id}`}
        items={menuItems}
      >
        {primary && (
          // 行内主行动走 `ghost`（§32.2 / §32.4：表格行内不用实心主色 —— 一屏至多一个 primary，
          // 那一个是页面头的「新增订单」）
          <span data-testid={`order-primary-${order.id}`}>
            <Button
              variant="ghost"
              size="sm"
              className="px-2"
              type="button"
              onClick={primary.onClick}
              // 焦点归位的落点（issue #8027）：收起录入区时焦点回到这里。
              // 🔴 用 block body：箭头函数的返回值在 React 19 会被当成 ref 清理函数。
              ref={(el) => {
                if (el) primaryButtonRefs.current.set(order.id, el)
                else primaryButtonRefs.current.delete(order.id)
              }}
              // 展开态要让读屏 / 键盘用户可感知（issue #8013：就地展开必须是一次「看得见的状态变化」）
              aria-expanded={primary.key === 'ship' ? shippingOrderId === order.id : undefined}
            >
              {primary.label}
            </Button>
          </span>
        )}
      </RowActions>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-neutral-50 text-neutral-600 text-left">
            {/* 选择列（表头全选框 + 每行勾选框）已移除（issue #8052）：选完没有任何批量动作
                消费它 = 假动作（§31 P1：常驻控件必须真的能做事）。等真有批量能力时再连动作一起设计。 */}
            <th className="pl-0 pr-4 py-3 font-medium whitespace-nowrap">订单ID</th>
            {/* 状态 / 加急（issue #6717）：**决策列前置**。改前它们在第 10、11 位（真机实测
                1440×980 下「状态」表头 left = 1542，而容器右缘 2181、横向可视区只有 1044px
                ⇒ 出屏）—— 商家要横滚 791px 才看得到「这单什么状态、要不要插队」。
                现在紧跟「订单ID」：`table-layout: auto` 下列宽随数据浮动，但前两列的累积宽度
                远小于可视区 ⇒ 1440×980 与 1280×800 两档实测都在可视区内。
                ⚠️ 只改**顺序**，列**集合与数据口径一字未动**（判据 =
                tests/e2e/specs/orders/key-columns-reachability.spec.ts 的列集合冻结断言）。 */}
            <th className="px-4 py-3 font-medium whitespace-nowrap">状态</th>
            {/* 加急 / 到货日（issue #5177）：列表面就能看出哪些单要插队、承诺哪天到。
                🔴 显示的是**服务端值**（`isUrgent` 缺省即库列默认 FALSE）—— 不写死客户端默认。 */}
            <th className="px-4 py-3 font-medium whitespace-nowrap">加急</th>
            {/* 打印（issue #7902）：**这单打过没有**是列表要回答的问题（与状态/加急同属决策列）。
                只读服务端按 print_logs 汇总的读数：已打印 ⇒ 勾 + 最近时间（悬浮显示次数与打过的单据）；
                从未打印 ⇒ 灰字「未打印」。🔴 不用前端本地状态冒充 —— 换台电脑打过的纸也看得见。 */}
            <th className="px-4 py-3 font-medium whitespace-nowrap">打印</th>
            <th className="pl-0 pr-4 py-3 font-medium whitespace-nowrap">采购商品</th>
            {/* 采购明细（issue #7138）：**表头必须与数据格共用同一宽度下限**。
                改前表头没有 `min-w`、也不 nowrap，而这列的表头是全表**唯一**会换行的格 ——
                `table-layout: auto` 在有数据时靠数据格的 `min-w-[280px]` 撑住，**空数据态**
                （tbody 只有一条 `colSpan=14` 的空态行）时没有这个约束 ⇒ 列被压到 min-content
                = 一个汉字宽 ⇒ 表头竖排、整行塌掉（用户 2026-10-17 截图）。 */}
            <th className="px-4 py-3 font-medium min-w-[280px] whitespace-nowrap">
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
            {/* 制单人（issue #5835）：建单的 B 端操作者（`orders.created_by_name` 快照）。
                🔴 缺值渲染「—」—— 存量单 / 内部服务占位 / C 端自助下单从未采集过这个事实，
                **不留空**（「没采集」也是一条要看得见的读数）。 */}
            <th className="px-4 py-3 font-medium whitespace-nowrap">制单人</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">到货日</th>
            <th className="px-4 py-3 font-medium whitespace-nowrap">备注</th>
            {/* 操作（issue #6717）：**右缘冻结** —— 改前本列表头 left = 1929（容器右缘 2181），
                宽表一律溢出 ⇒ 行操作（查看/备注/发货/处理退款…）够不到。
                `sticky right-0` + **不透明背景**（表头取 50 灰阶，与既有一致；数据格用
                `bg-inherit` 继承 `<tr>` 的背景 ⇒ 选中 / hover 变色仍然生效且**不透明**：
                sticky 格必须挡住在它下面横向滚过的单元格，透明就是「穿透」的假修）。
                `z-20` / 数据格 `z-10`：都在表内内容之上。左分隔线 `border-l`：滚动时与左侧
                内容之间有一条缝（否则会看成两列粘在一起）。 */}
            <th className="sticky right-0 z-20 border-l border-neutral-200 bg-neutral-50 px-4 py-3 font-medium whitespace-nowrap">操作</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={14} className="px-4 py-16 text-center text-neutral-400">
                加载中…
              </td>
            </tr>
          ) : orders.length === 0 ? (
            <tr>
              <td data-testid="orders-empty" colSpan={14} className="px-4 py-16 text-center text-neutral-400">
                {/* 🔴 issue #6733：`emptyText` 由页面传入 —— 读失败时传空串（别把「读不到」说成「没有订单」）。 */}
                {emptyText}
              </td>
            </tr>
          ) : (
            orders.map((order) => {
              return (
                // issue #8013：行 + （可选）它自己的展开行 —— 两行同属一单，故外层用 Fragment 承 key
                <Fragment key={order.id}>
                {/* issue #6717：行背景**显式**声明在 `<tr>` 上（`sticky right-0` 的「操作」列
                    横滚时不得让下层内容穿透；退回 `bg-inherit` 会重新引入 #6729 的穿透缺陷） */}
                <tr className="border-b border-neutral-100 bg-white align-top transition-colors hover:bg-neutral-50">
                  {/* 订单ID（issue #8011：17 位纯数字手抄必错 ⇒ 单元格内给复制入口） */}
                  <td className="pl-0 pr-4 py-4 font-mono text-neutral-800 whitespace-nowrap">
                    <span className="inline-flex items-center gap-1">
                      {order.orderNo || order.id}
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-1"
                        aria-label="复制订单号"
                        data-testid={`order-copy-${order.id}`}
                        onClick={() => void copyOrderNo(order.orderNo || order.id)}
                        icon={<Copy className="h-3.5 w-3.5" />}
                      />
                    </span>
                  </td>

                  {/* 状态（issue #6717：决策列前置 —— 与表头同序） */}
                  <td className="px-4 py-4 whitespace-nowrap">
                    {/* 传原始后端状态（issue #3889）：producing 由 chip 展示为「生产中」而非归一为待发货 */}
                    <OrderStatusBadge status={order.status} />
                  </td>

                  {/* 加急（issue #5177 / #6717：订单级真值，与售后工单的 priority **零联动**）
                      issue #8011：非加急 ⇒ **空单元格**（不再逐行印「不加急」—— 同屏零信息量重复，
                      §31 P2）；加急 ⇒ 醒目徽标（同字号灰字扫视读不出来）。
                      🔴 取值口径仍走 `urgentBadgeText`（唯一真值源，PR-079）—— 只改**渲染条件**，
                      不改取值；「缺省 = 不加急」的语义因此一字未动。 */}
                  <td className="px-4 py-4 whitespace-nowrap" data-testid={`order-urgent-${order.id}`}>
                    {isUrgentFlag(order) && <Badge variant="warning">{urgentBadgeText(order)}</Badge>}
                  </td>

                  {/* 打印状态（issue #7902） */}
                  <td className="px-4 py-4 whitespace-nowrap" data-testid={`order-printed-${order.id}`}>
                    {order.printedAt ? (
                      <span
                        className="inline-flex items-center gap-1 text-neutral-700"
                        title={printStatusTitle(order)}
                      >
                        <Check className="h-3.5 w-3.5 text-emerald-600" />
                        已打印
                        <span className="text-xs text-neutral-500">
                          {formatPrintedAt(order.printedAt)}
                        </span>
                      </span>
                    ) : (
                      <span className="text-xs text-neutral-400">未打印</span>
                    )}
                  </td>

                  {/* 采购商品（与「采购明细」同源：N 条明细 ⇒ N 组「名称 + 货号」；
                      issue #4908：改前只渲染 items[0] ⇒ 多商品订单其余商品在列表上完全不可见） */}
                  <td className="pl-0 pr-4 py-4 min-w-[160px]">
                    {order.items?.length ? (
                      <div className="space-y-2">
                        {order.items.map((item, itemIdx) => (
                          // 行主键优先（issue #6883 起后端下发 `order_items.id`）；历史响应缺 id ⇒ 退回「订单 + 序号」
                          <div key={item.id ?? `${order.id}-product-${itemIdx}`} className="space-y-0.5">
                            <div className="text-neutral-900 font-medium leading-tight">
                              {item.productName}
                            </div>
                            <div className="text-xs text-neutral-500 leading-tight">
                              货号 {item.productCode || '-'}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-neutral-400">暂无数据</span>
                    )}
                  </td>

                  {/* 采购明细（名称 : 规格 : 单价 : 数量 : 加工费） */}
                  <td className="px-4 py-4 min-w-[280px]">
                    {order.items?.length || order.processingItems?.length ? (
                      <div className="space-y-1.5">
                      {order.items?.map((item, itemIdx) => {
                        // #2916 / #7138: 加工信息嵌套在明细项 processingInfo 内（列表接口不下发顶层
                        // processingItems）；金额一律由 `processingFeeOf` 按**权威 detail** 取。
                        const fee = processingFeeOf(item.processingInfo)
                        return (
                          // 行主键优先（issue #6883 起后端下发 `order_items.id`）；历史响应缺 id ⇒ 退回「订单 + 序号」
                          <div key={item.id ?? `${order.id}-item-${itemIdx}`} className="space-y-0.5">
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
                            {/* 加工项逐项明细（`定型 0元/米 × 18.3米 = 0元` 一族）已随 #4882 整块退场
                                （用户裁定 A：单价 / 数量 / 金额 / 算式都不再渲染）。
                                ⚠️ 行尾 `+ 加工费 X 元` 聚合与商品行本身**保留** —— 前者由
                                `processingFeeOf` 给出（权威 `processingFeeDetail.amount` 优先）。 */}
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

                  {/* 制单人（issue #5835）：`null` = 未采集 ⇒ 渲染「—」（不静默留空） */}
                  <td className="px-4 py-4 whitespace-nowrap text-neutral-700" data-testid={`order-creator-${order.id}`}>
                    {order.createdByName || <span className="text-xs text-neutral-400">—</span>}
                  </td>

                  {/* 到货日（issue #5177）：`null` = 未指定（不猜、不写死默认） */}
                  <td className="px-4 py-4 whitespace-nowrap text-neutral-700" data-testid={`order-delivery-${order.id}`}>
                    {order.requiredDeliveryDate || <span className="text-xs text-neutral-400">未指定</span>}
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

                  {/* 操作（issue #6717）：右缘冻结。`border-l` 与表头同位置，滚动时与左侧内容之间有分隔。
                      issue #6729（**#6717 的回归修复**）：原来写 `bg-inherit`，横滚时下层列的内容
                      （姓名/电话/地址）会**穿透**进冻结列（真机 `getComputedStyle` alpha<1 + 读图双重实证）。
                      修法 = 冻结格**自己**声明不透明底色：这里用 `bg-white`（与行底色同值，逐像素一致），
                      行 hover 变 `neutral-50` 时本格保持不透明白底 —— 与改前未选中态观感完全相同。
                      🔴 不要再退回 `bg-inherit` / 半透明色：背景一旦透明，冻结列必然穿透（类级判据会拦住）。 */}
                  <td className="sticky right-0 z-10 border-l border-neutral-100 bg-white pl-2 pr-3 py-4">
                    {renderActions(order)}
                  </td>
                </tr>
                {shippingOrderId === order.id && (
                  // 展开行（issue #8013）：录入区就在**这一行的下方** —— 不跳页、不用遮罩模态。
                  // 收起态整行**不进 DOM**（§31 P1 的机器读数：不是 CSS 隐藏、不是 `sr-only`）。
                  <tr
                    data-testid={`ship-inline-row-${order.id}`}
                    className="border-b border-neutral-100 bg-neutral-50/60"
                  >
                    <td colSpan={14} className="px-4 py-4">
                      <InlineShipForm
                        order={order}
                        onClose={() => onToggleShip?.(order)}
                        onShipped={() => onShipped?.()}
                      />
                    </td>
                  </tr>
                )}
                </Fragment>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
