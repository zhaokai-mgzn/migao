'use client'

import { ArrowDown, Check, Copy, MoreHorizontal } from 'lucide-react'
import { Fragment, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import type { OrderBrief } from '@/types'
import { normalizeOrderStatus } from '@/types'
import { Badge, Button } from '@/components/ui'
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
  selectedIds: string[]
  onSelectChange: (ids: string[]) => void
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
 * 行内「⋯」菜单（issue #8011）—— 把同名级文字链收进一个菜单，行内只留 **1 主行动 + 1 触发器**。
 *
 * ## 为什么必须收（真机读数，2026-10-24 `14-orders-list.png`）
 *
 * 改前每行 4 个同级文字链（`查看 · 备注 · 发货 · 处理退款`）⇒ 20 行/页 = **单屏 80 个可点文本**，
 * 没有层级、没有主行动（`migao-dev-flow` §31 P1/P2：常驻面克制 + 信息不重复）。
 *
 * ## 实现口径
 *
 * - **收起态菜单项不进 DOM**（`{open && …}`，不是 CSS 隐藏）—— 否则「单屏 80 个可点文本」只换了长相；
 * - 面板 `position: fixed`：本表在 `overflow-x-auto` 里（#6717 右缘冻结列），
 *   绝对定位的子面板会被横向滚动容器**纵向裁掉**（最后一行的菜单点开就没了）⇒ 用 fixed 脱离裁切，
 *   并在滚动 / 缩放时收起（否则面板与行脱位）；
 * - 键盘：`aria-haspopup="menu"` / `aria-expanded` / `role="menu"` / `role="menuitem"`，
 *   `Escape` 与「点外部」都收起 —— 收敛**不得**把动作藏成不可达。
 */
interface RowMenuItem {
  key: string
  label: string
  onClick: () => void
}

function RowActionMenu({ menuId, items }: { menuId: string; items: RowMenuItem[] }) {
  /** `null` = 收起；有坐标 = 展开（坐标在**点开的那一刻**量，避免与行脱位） */
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const open = anchor !== null

  useEffect(() => {
    if (!open) return
    const close = () => setAnchor(null)
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null
      // 触发器自己交给 onClick 处理（否则一次点击会先关后开）
      if (triggerRef.current?.contains(target as Node)) return
      // 面板里的动作同样不在这里关（它的 onClick 自己关，保证动作先执行）
      if (target?.closest?.(`[data-row-menu="${menuId}"]`)) return
      close()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    // 表格容器可横滚、页面可竖滚 ⇒ 面板会与行脱位，直接收起（比假装还在正确位置诚实）
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open, menuId])

  const toggle = () => {
    if (open) {
      setAnchor(null)
      return
    }
    const rect = triggerRef.current?.getBoundingClientRect()
    if (!rect) return
    setAnchor({ top: rect.bottom + 4, left: rect.right })
  }

  return (
    <span className="relative inline-flex" data-testid={menuId}>
      {/* 纯图标按钮必须 `aria-label`（§32.2 第 5 条）；行内层级一律 ghost（不用实心主色） */}
      <Button
        ref={triggerRef}
        type="button"
        variant="ghost"
        size="sm"
        className="px-1.5"
        aria-label="更多操作"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
        icon={<MoreHorizontal className="h-4 w-4" />}
      />
      {open && (
        <div
          role="menu"
          data-row-menu={menuId}
          style={{ top: anchor.top, left: anchor.left, transform: 'translateX(-100%)' }}
          className="fixed z-50 min-w-[9rem] rounded-lg border border-neutral-200 bg-white py-1 shadow-lg"
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              onClick={() => {
                setAnchor(null)
                item.onClick()
              }}
              className="flex w-full items-center px-3 py-1.5 text-left text-sm text-neutral-700 hover:bg-neutral-50"
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </span>
  )
}

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
  selectedIds,
  onSelectChange,
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
    const primary: RowMenuItem | null =
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

    const menuItems: RowMenuItem[] = [
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
      <div
        className="flex items-center gap-1 whitespace-nowrap"
        data-testid={`order-actions-${order.id}`}
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
              // 展开态要让读屏 / 键盘用户可感知（issue #8013：就地展开必须是一次「看得见的状态变化」）
              aria-expanded={primary.key === 'ship' ? shippingOrderId === order.id : undefined}
            >
              {primary.label}
            </Button>
          </span>
        )}
        <RowActionMenu menuId={`order-menu-${order.id}`} items={menuItems} />
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-neutral-50 text-neutral-600 text-left">
            <th className="pl-2 pr-3 py-3 font-medium w-10 whitespace-nowrap">
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
              <td colSpan={15} className="px-4 py-16 text-center text-neutral-400">
                加载中…
              </td>
            </tr>
          ) : orders.length === 0 ? (
            <tr>
              <td data-testid="orders-empty" colSpan={15} className="px-4 py-16 text-center text-neutral-400">
                {/* 🔴 issue #6733：`emptyText` 由页面传入 —— 读失败时传空串（别把「读不到」说成「没有订单」）。 */}
                {emptyText}
              </td>
            </tr>
          ) : (
            orders.map((order) => {
              const checked = selectedIds.includes(order.id)
              return (
                // issue #8013：行 + （可选）它自己的展开行 —— 两行同属一单，故外层用 Fragment 承 key
                <Fragment key={order.id}>
                <tr
                  className={cn(
                    'border-b border-neutral-100 align-top transition-colors',
                    // issue #6717：「操作」列是 `sticky right-0`，而 sticky 格的背景**只能**继承
                    // `<tr>` 的背景（用祖先链上的 `.bg-white` 让 `bg-inherit` 变透明 ⇒ 横向滚过它
                    // 下面的单元格会**穿透**显示）。故行背景必须**显式**声明在这里：
                    // 未被选中 ⇒ `bg-white`（与卡片底色同值，外观不变）；选中 ⇒ 既有的 50/40。
                    checked ? 'bg-primary-50/40' : 'bg-white hover:bg-neutral-50'
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
                      issue #6729（**#6717 的回归修复**）：原来写 `bg-inherit` —— 它继承的是 `<tr>` 的背景，
                      而**选中态的行背景就是半透明的**（`bg-primary-50/40` = `rgba(238,242,248,0.4)`）
                      ⇒ 继承到的也半透明 ⇒ 横滚时下层列的内容（姓名/电话/地址）**穿透**进冻结列
                      （真机 `getComputedStyle` alpha=0.4 + 读图双重实证）。
                      修法 = **把「继承」换成「同一个颜色的不透明版」**：
                        · 未选中：行底色是 `bg-white` ⇒ 本格也 `bg-white`（逐像素一致）；
                        · 选中：用 `bg-primary-50-lit`（= `bg-primary-50/40` 叠在白底上的**已合成色**
                          `#f8fafc`）⇒ 与同行其它格**逐像素同色**；不能直接用 `bg-primary-50`
                          （那是**未合成**的原色 `#eef2f8`，比同行其它格深一档 = 视觉不一致）。
                      ⇒ 冻结格任何交互态下 alpha 恒为 1，而**行底色机制一字未改**（未选中 / hover 观感不变）。
                      🔴 不要再退回 `bg-inherit`：行底色一旦半透明，冻结列必然穿透（类级判据会拦住）。 */}
                  <td
                    className={cn(
                      'sticky right-0 z-10 border-l border-neutral-100 pl-2 pr-3 py-4',
                      checked ? 'bg-primary-50-lit' : 'bg-white',
                    )}
                  >
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
                    <td colSpan={15} className="px-4 py-4">
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
