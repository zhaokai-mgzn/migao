'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui'
import { processingOrderApi } from '@/lib/api'
// 工艺规格展示的单一真值定义（设计文档 §4.9「一份 spec，三处渲染」）
import { craftSpecLine } from '@/lib/craft-display'
// 「工艺行但不要门幅」的唯一实现（issue #6893：本组件已在属性行里印过门幅）；
// 数量 + 单位的**唯一**取值口（issue #6901：屏幕块与「复制全部」文本共用，不各拼一份 ——
// 订单行自己的 `unit` 键 DTO 未下发 ⇒ 由调用方补加工单**快照行**的单位）
import { craftRowsWithoutDoorWidth, quantityWithUnit } from '@/lib/order-item-sku'
// 工序清单的索引 / 状态文案（issue #6901）：唯一实现 = `lib/operation-list.ts`
// （🔴 纸面自 issue #7274 起**不印工序** ⇒ 屏幕块直接走这一份，不再经 `./ProcessingDoc` 转出）；
// 显示名一律走仓内**唯一**口径 `lib/operation-display.ts`（issue #4621）
import { operationsByItem, operationStatusText } from '@/lib/operation-list'
import { operationDisplayName } from '@/lib/operation-display'
// 状态文案单一来源：与列表页共用（加工单状态机语义见 lib/processing-order.ts）；
// issue #7079：作业单两型（加工单 / 出库作业单）的中文业务名与判定也取同一份 ——
// 🔴 机器键（`processing` / `outbound`）绝不上屏。
import {
  ORDER_KIND_LABELS,
  PROCESSING_ORDER_STATUS_LABELS as STATUS_TEXT,
  orderKindOf,
  workOrderKindOf,
  type WorkOrderKind,
} from '@/lib/processing-order'
// 米数展示口径（0.1 米粒度、去尾随 .0）—— 与库存/批次账同一份工具
import { formatStockQuantity } from '@/lib/stock-quantity'
import type {
  ProcessingOrder,
  ProcessingOrderItem,
  ProductionOperation,
  ProductionPosition,
} from '@/types'
import { SellingMethodLabels } from '@/types'

interface Props {
  orderId: string
  orderStatus: string
  /**
   * **没有作业单时该生成哪一型**（订单详情读面键 `work_order_kind`，issue #7079 第 5 包）。
   *
   * 🔴 它同时就是「这单发货前**要不要**作业」的判据：`null` = 不要（订单直发，不渲染生成入口）。
   * **不许**改用 `order.processingItems?.length` 自己推（那只覆盖「含加工项」那一半 ⇒
   * 卖布单没有生成出口）。值由服务端 `OrderShipGuard.requiredOrderKind` 给出（与发货守卫同一份判据）。
   */
  workOrderKind: WorkOrderKind
  /**
   * @deprecated issue #7079 第 5 包起**不再消费**（只覆盖「含加工项」的单侧信号，卖布单被漏掉）；
   * 判据一律走 {@link Props.workOrderKind}。保留字段只为兼容存量调用点，新代码不要传。
   */
  hasProcessing?: boolean
  /**
   * 本订单的**工序清单**（既有读面 `GET /api/admin/production/orders/{id}/operations`
   * 的 `positions[]`，issue #6901）—— 由订单详情页加载后原样传进来（本组件**不取数**）。
   * 缺省/空 ⇒ 屏幕明细块与「复制全部」文本都**不出现**工序行（不印空标题）。
   */
  operations?: ProductionPosition[] | null
  /** 加工单状态上报（issue #3889）：详情页据此守卫「含加工项且加工单未完成」的发货入口 */
  onStatusChange?: (po: ProcessingOrder | null) => void
  /**
   * 把本块的**加工单读面刷新**交给调用方（issue #6867 / B5）：补码成功后页面要重读加工单，
   * 才能把新短链 / 短码刷到纸面上。**只交出刷新函数、不交出数据** —— 读面仍归本块所有
   * （详情页不写第二份读面、也不缓存一份会漂的副本）。
   */
  onReloadReady?: (reload: () => Promise<void>) => void
}

const STEP_ORDER: ProcessingOrder['status'][] = ['generated', 'issued', 'in_processing', 'completed']

function formatAmount(v?: number): string {
  if (v == null) return '—'
  return String(v)
}

/**
 * 生产明细页路径（issue #7634）：作业单状态的**唯一**写面。
 * 用加工单号（服务端与前端同一口径，`useRouteId` 认单号/订单号/UUID）。
 */
function PRODUCTION_PATH(processingOrderNo: string): string {
  return `/processing-orders/${processingOrderNo}/production`
}

/**
 * 售卖方式展示名（issue #6664 第 5 条）：真值源 = `types` 的 `SellingMethodLabels`
 * （与 `OrderItemList` / `OrderDetail` 同一份映射），**未知值落人话兜底**、不裸奔英文键。
 */
const SELLING_METHOD_EXTRA: Record<string, string> = {
  per_meter: '按米',
  per_piece: '按件',
}

function sellingMethodLabel(value: string): string {
  return (SellingMethodLabels as Record<string, string>)[value]
    ?? SELLING_METHOD_EXTRA[value]
    ?? '未知方式'
}

/**
 * 快照行的**属性行**片段（门幅 / 货号 / 方式 / 宽 / 高 / 数量+单位）—— **唯一**一份实现，
 * 屏幕块与「复制全部」文本共用（issue #6901：两处是同一条事实的两个渲染面，
 * 各拼一份必然漂移 —— 复制出去的文本少一项，车间就照旧按老习惯做）。
 *
 * 🔴 货号（issue #6901）：快照键 `sku`（`buildSnapshot` 从 `products.sku_code` 落）；
 * 缺值 ⇒ 该片段不出现（**不印空标签** —— 同族口径见 `craftSpecRows` 丢弃缺值行）。
 */
export function snapshotAttrParts(
  item: Pick<ProcessingOrderItem, 'sku' | 'doorWidth' | 'sellingMethod' | 'width' | 'height'>,
  quantity: { quantity?: unknown; unit?: unknown } = {},
  separator = ' ',
): string[] {
  const qty = quantityWithUnit(quantity)
  return [
    item.doorWidth ? `门幅${separator}${item.doorWidth}` : '',
    item.sku ? `货号${separator}${item.sku}` : '',
    item.sellingMethod ? `方式${separator}${sellingMethodLabel(item.sellingMethod)}` : '',
    item.width != null ? `宽${separator}${item.width}m` : '',
    item.height != null ? `高${separator}${item.height}m` : '',
    qty ? `数量${separator}${qty}` : '',
  ].filter(Boolean)
}

/**
 * 一道工序的**片段**（应做数量+单位、状态）—— 屏幕块与「复制全部」文本共用。
 * 显示名一律走仓内唯一口径 `operationDisplayName()`（`@/lib/operation-display`）；
 * 🔴 纸面自 issue #7274 起不再消费工序清单。
 */
export function operationParts(op: ProductionOperation): string[] {
  const qty = quantityWithUnit({ quantity: op.qty, unit: op.unit })
  return [qty, operationStatusText(op.status)].filter((part) => part !== '')
}

/** 作业单**纯文本**（复制给加工方/贴 Excel，一行一加工项）
 *
 * issue #7079：两型的措辞不同 —— 出库作业单**没有加工方、没有交期** ⇒ 这两行不出现（缺值不渲染）。
 */
function toPlainText(po: ProcessingOrder, operations?: ProductionPosition[] | null): string {
  const operationsIndex = operationsByItem(operations)
  const outbound = orderKindOf(po) === 'outbound'
  const lines: string[] = []
  lines.push(`${ORDER_KIND_LABELS[orderKindOf(po)]}：${po.processingOrderNo}`)
  if (po.customerName) lines.push(`客户：${po.customerName}`)
  if (po.processor) lines.push(`加工方：${po.processor}`)
  if (po.expectedDeliveryDate) lines.push(`交期：${po.expectedDeliveryDate}`)
  lines.push(`状态：${STATUS_TEXT[po.status] ?? po.status}`)
  lines.push('')
  ;(po.items ?? []).forEach((it: ProcessingOrderItem, i: number) => {
    lines.push(`【${i + 1}】${it.productName ?? ''}${it.colorName ? `（${it.colorName}）` : ''}${it.sku ? `【${it.sku}】` : ''}`)
    // 属性行（门幅 / 货号 / 方式 / 宽 / 高 / 数量+单位）：与屏幕块**同一份**片段生成器
    // （issue #6901：货号此前两处都缺；文本用 `:` 分隔 = 贴 Excel 的既有形态）
    const attrs = snapshotAttrParts(it, { quantity: it.quantity, unit: it.unit }, ':')
    if (attrs.length) lines.push(`  ${attrs.join('  ')}`)
    // 工艺规格（issue #4355 / 设计文档 §4.9 ③）：加工方拿到的文本必须带工艺，否则车间按老习惯做。
    // 🔴 issue #6893：**去掉「门幅」**—— 上一行属性里已经写了 `门幅:…`（同一份文本里印两遍）。
    const specRows = craftRowsWithoutDoorWidth(it)
    if (specRows.length) lines.push(`  工艺规格：${specRows.map(craftSpecLine).join('  ')}`)
    ;(it.processingItems ?? []).forEach((p) => {
      const opt = Array.isArray(p.options) && p.options.length ? `（${p.options.join('/')}）` : ''
      lines.push(`  加工：${p.name}${opt}${p.quantity != null ? ` × ${p.quantity}${p.unit ?? ''}` : ''}`)
    })
    // 工序清单（issue #6901）：**这一套要做哪几道** —— 显示名 / 应做（数量+单位）/ 状态。
    // 缺值（订单还没生成加工单 / 该行对不上 `order_item_id`）⇒ **整块不出现**（不印空标题）。
    const operations = it.itemId ? operationsIndex.get(it.itemId)?.operations ?? [] : []
    if (operations.length) {
      lines.push('  工序：')
      operations.forEach((op) => {
        const parts = operationParts(op)
        lines.push(`    ${operationDisplayName(op)}${parts.length ? `：${parts.join('  ')}` : ''}`)
      })
    }
    // 部位备注（issue #5685）：缺键 / 空串 / 纯空白 ⇒ 不出现该行（与屏幕上同一口径）
    if (it.remark?.trim()) lines.push(`  备注：${it.remark}`)
    lines.push('')
  })
  if (po.remark) lines.push(`整体备注：${po.remark}`)
  if (po.cancelledReason) lines.push(`取消原因：${po.cancelledReason}`)
  return lines.join('\n')
}

export default function ProcessingOrderBlock({
  orderId,
  orderStatus,
  workOrderKind,
  operations,
  onStatusChange,
  onReloadReady,
}: Props) {
  const router = useRouter()
  const [po, setPo] = useState<ProcessingOrder | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await processingOrderApi.detail(orderId)
      const data = res.data?.data ?? null
      setPo(data)
      setNotFound(!data)
      onStatusChange?.(data)
    } catch {
      setNotFound(true)
      setPo(null)
      onStatusChange?.(null)
    } finally {
      setLoading(false)
    }
  }, [orderId, onStatusChange])

  useEffect(() => {
    if (orderId) load()
  }, [orderId, load])

  // 交出刷新函数（issue #6867 / B5）：补码成功后页面据此重读本单，把新码刷到纸面上。
  // `load` 是稳定引用（useCallback，依赖 orderId / onStatusChange）⇒ 本 effect 不会自激循环。
  useEffect(() => {
    onReloadReady?.(load)
  }, [load, onReloadReady])

  // 作业单两型（issue #7079）：缺键 = 存量单 ⇒ 按**加工单**处理（不把存量单读成出库）。
  // 出库作业单**没有加工方、没有交期** ⇒ 那两处写面与展示整块不渲染；也**不**走「发加工」。
  const kind = po ? orderKindOf(po) : 'processing'
  const outbound = kind === 'outbound'
  // 「要不要作业」+「要哪一型」都取**订单详情读面**的同一个信号（issue #7079 第 5 包）——
  // 卖布单行上没有加工项，只按 processingItems 推会判「不需要」⇒ 没有生成出口。
  // wire 键是 snake_case（issue #7319）；本组件的 prop 保持 camelCase 的组件 API，这里显式换一次键。
  const neededKind = workOrderKindOf({ work_order_kind: workOrderKind })
  // 🔴 本块**只读**（issue #7634，用户裁定「统一走智能派单」）：派单只在智能派单页做，
  // 状态流转只在生产明细页做 —— 这里既不发 POST /generate，也不发 PATCH 状态。
  // 「能不能派单」= 派单池的收单口径（待付款也在池里，issue #7634）；终态/已取消单不进池。
  const canDispatch = ['pending', 'pending_payment', 'confirmed', 'producing'].includes(orderStatus)
  /** 需要作业单但还没有 ⇒ 只给「去智能派单」入口 */
  const needsWorkOrder = notFound && neededKind !== null
  // 工序清单按 `order_item_id` 索引一次（issue #6901；与洗水码/批号同一把钥匙）
  const operationsIndex = operationsByItem(operations)

  const handleCopy = async () => {
    if (!po) return
    try {
      await navigator.clipboard.writeText(toPlainText(po, operations))
    } catch {
      // 剪贴板不可用时退化为选中文本
      setError('复制失败，请手动选择文本复制')
    }
  }

  /** 失败提示：本块唯一的失败面 = 「复制全部」拿不到剪贴板 */
  const errorBlock = <p className="text-xs text-red-500">{error}</p>

  return (
    <div className="mt-6">

      <div className="flex items-center justify-between po-no-print">
        <h3 className="text-base font-semibold text-neutral-900">作业单</h3>
        {/* 「复制全部」留在这里：它是**文本通道**（作业单文本发给加工方 / 贴进 Excel），
            不是打印通道。issue #7544 只把**打印**收口到页面级唯一入口（预览层里选「加工单」），
            区块内不再有自己的打印按钮 —— 同页两个打印入口正是这张单里要消掉的形态。 */}
        {po && (
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={handleCopy}>复制全部</Button>
          </div>
        )}
      </div>
      {error && <div className="mt-2">{errorBlock}</div>}

      {loading && <div className="py-4 text-sm text-neutral-400">加载中…</div>}

      {/* 🔴 无作业单 ⇒ **只给入口**（issue #7634）：五个写动作（生成作业单 / 发加工 / 开始加工 /
          加工完成 / 取消）全部退出本块 —— 派单在「智能派单」页做（同料合并更省料），
          状态流转在生产明细页做。本块不再有任何让销售订单直接推进生产的口子。 */}
      {!loading && needsWorkOrder && neededKind && canDispatch && (
        <div className="mt-3 rounded-lg border border-primary-100 bg-primary-50/50 p-4">
          <p className="text-sm text-neutral-600">
            该订单需要{ORDER_KIND_LABELS[neededKind]}。到「智能派单」勾选本单派单 —— 同料订单合并领料，更省料。
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            待付款与加急订单同样在「智能派单」派（加急走插队区立即派单）。
          </p>
          <Button className="mt-3" size="sm" data-testid="po-go-pool" onClick={() => router.push('/production/pool')}>
            去智能派单
          </Button>
        </div>
      )}

      {!loading && needsWorkOrder && neededKind && !canDispatch && (
        <div data-testid="processing-order-generate-not-yet" className="mt-2 text-sm text-neutral-500">
          <p>该订单需要作业单（{ORDER_KIND_LABELS[neededKind]}），当前状态还不能派单。</p>
          <p className="mt-1">仅「待付款 / 已确认 / 生产中」的订单可派单。</p>
        </div>
      )}

      {!loading && notFound && neededKind === null && (
        <>
          <p className="mt-2 text-sm text-neutral-400">该订单无需作业单（没有加工项，也不是卖布单）。</p>
          {/* 可行动出口（issue #7222）：只宣判不给出路 ⇒ 商家不知道去哪儿安排裁剪。
              没标售卖形态时系统**不会**生成裁剪 / 打包作业，也不会拦发货（三段静默放行）。 */}
          <p className="mt-1 text-sm text-neutral-400">
            如果是卖布单（按米卖布），这张单还没有标记售卖形态 —— 系统不会生成裁剪 / 打包作业，
            也不会拦发货。请作废后重新下单，并在下单页把「售卖形态」选成「布料」。
          </p>
        </>
      )}

      {po && (
        <div className="po-print-area mt-3 rounded-lg border border-neutral-200 p-4">
          {/* 头部 */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-100 pb-3">
            <div>
              <span className="text-lg font-semibold text-neutral-900">{po.processingOrderNo}</span>
              {/* 类型可见（issue #7079）：中文业务名「加工单」/「出库作业单」，机器键不上屏 */}
              <span
                className="ml-2 rounded bg-neutral-100 px-2 py-0.5 text-xs font-medium text-neutral-600"
                data-testid="processing-order-kind"
              >
                {ORDER_KIND_LABELS[kind]}
              </span>
              <span className="ml-2 rounded bg-primary-50 px-2 py-0.5 text-xs font-medium text-primary-700">
                {STATUS_TEXT[po.status] ?? po.status}
              </span>
            </div>
            <div className="text-sm text-neutral-500">
              {/* 出库作业单（issue #7079）：**没有加工方、没有交期** ⇒ 这两个写面不渲染，
                  改为如实说明原因（不印空标题，也不给「—」冒充有值）。 */}
              {outbound ? (
                <span>卖布单不设加工方与交期</span>
              ) : (
                <>
                  {po.processor && <span className="mr-3">加工方：{po.processor}</span>}
                  {po.expectedDeliveryDate && <span>交期：{po.expectedDeliveryDate}</span>}
                </>
              )}
            </div>
          </div>

          {/* 状态时间线 */}
          {po.status !== 'cancelled' && (
            <div className="mt-3 flex items-center gap-1 text-xs">
              {STEP_ORDER.map((s, i) => {
                const done = STEP_ORDER.indexOf(po.status) >= i
                return (
                  <span key={s} className="flex items-center gap-1">
                    <span className={`rounded-full px-2 py-0.5 ${done ? 'bg-primary-600 text-white' : 'bg-neutral-100 text-neutral-400'}`}>
                      {STATUS_TEXT[s]}
                    </span>
                    {i < STEP_ORDER.length - 1 && <span className="text-neutral-300">→</span>}
                  </span>
                )
              })}
            </div>
          )}
          {po.status === 'cancelled' && po.cancelledReason && (
            <p className="mt-3 text-xs text-red-500">取消原因：{po.cancelledReason}</p>
          )}

          {/* 快照明细（不含销售价——决策 2） */}
          <div className="mt-3 space-y-3">
            {(po.items ?? []).map((it, idx) => {
              // 工艺规格（issue #4355 / 设计文档 §4.9 ③）：渲染快照里固化的那一份，缺值行已丢弃。
              // 🔴 issue #6893：去掉「门幅」—— 紧跟的属性行里已印 `门幅 …`。
              const specRows = craftRowsWithoutDoorWidth(it)
              // 工序清单（issue #6901）：本行对应的那一组（同一把钥匙 = 快照 `itemId` = `order_item_id`）
              const itemOperations = it.itemId ? operationsIndex.get(it.itemId)?.operations ?? [] : []
              return (
              <div key={idx} className="rounded-md bg-neutral-50 p-3 text-sm">
                <div className="font-medium text-neutral-900">
                  {it.productName}
                  {/* 🔴 issue #6901：货号**只印一处** —— 紧跟的属性行里已有 `货号 0012`
                      （P2 信息不重复：同一真值印两处只是噪音，用户实测同款问题见 #6893 的门幅） */}
                  {it.colorName && <span className="ml-2 text-primary-600">{it.colorName}</span>}
                </div>
                <div className="mt-1 text-xs text-neutral-500">
                  {snapshotAttrParts(it, { quantity: it.quantity, unit: it.unit }).join(' · ')}
                </div>
                {/* 排料结果（V119 / issue #5158）：**应领米数**（排料口径）与公式口径并列。
                    缺键（未指派批次 / 排不了料的单）⇒ 整块不出现（缺值不渲染，不显示 0 冒充省了）。 */}
                {it.plannedMeters != null && (
                  <div
                    className="mt-1.5 text-xs text-neutral-600"
                    data-testid={`po-item-cutting-plan-${idx}`}
                  >
                    应领 {formatStockQuantity(Number(it.plannedMeters))} 米（公式{' '}
                    {formatStockQuantity(Number(it.formulaMeters ?? it.plannedMeters))} 米
                    {Number(it.savedMeters ?? 0) > 0 &&
                      ` · 省 ${formatStockQuantity(Number(it.savedMeters))} 米`}
                    ）
                  </div>
                )}
                {/* 工艺规格：无任何工艺键（存量单）时整块不出现 */}
                {specRows.length > 0 && (
                  <div className="mt-1.5 space-y-0.5" data-testid="po-item-craft-spec">
                    <div className="text-xs font-medium text-neutral-600">工艺规格</div>
                    {specRows.map((row) => (
                      <div key={row.label} className="flex flex-wrap gap-x-2 text-xs">
                        <span className="text-neutral-400">{row.label}</span>
                        <span className="text-neutral-700">{row.value}</span>
                      </div>
                    ))}
                  </div>
                )}
                {(it.processingItems ?? []).length > 0 && (
                  <ul className="mt-1.5 space-y-0.5 text-xs text-amber-700">
                    {(it.processingItems ?? []).map((p, pi) => (
                      <li key={pi}>
                        加工：{p.name}
                        {Array.isArray(p.options) && p.options.length > 0 && `（${(p.options as string[]).join('/')}）`}
                        {p.quantity != null && ` × ${p.quantity}${p.unit ?? ''}`}
                      </li>
                    ))}
                  </ul>
                )}
                {/* **工序清单**（issue #6901）：这一套要做哪几道（显示名 / 应做 / 状态）。
                    缺值（订单还没生成加工单 / 该行对不上 `order_item_id`）⇒ **整块不出现**。 */}
                {itemOperations.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5 text-xs text-neutral-600" data-testid="po-item-operations">
                    <li className="font-medium text-neutral-600">工序</li>
                    {itemOperations.map((op, oi) => (
                      <li key={op.id ?? oi} data-testid="po-item-operation">
                        <span className="text-neutral-700">{operationDisplayName(op)}</span>
                        {operationParts(op).length > 0 && ` · ${operationParts(op).join(' · ')}`}
                      </li>
                    ))}
                  </ul>
                )}
                {/* **部位备注**（issue #5685）：快照行键 `remark` —— 生成加工单那一刻从
                    `order_items.processing_info.remark` 逐字固化（下单页写侧单点构造）。
                    缺值不渲染：缺键 / 空串 / **纯空白**（= 未填，与写侧 trim 口径一致）⇒ 该行不出现。 */}
                {it.remark?.trim() && (
                  <div className="mt-1 text-xs text-neutral-500">备注：{it.remark}</div>
                )}
              </div>
              )
            })}
          </div>
          {po.remark && <p className="mt-2 text-xs text-neutral-500">整体备注：{po.remark}</p>}

          {/* 出库作业单（issue #7079）：卖布单**不生成加工单**，只按裁剪 / 打包两道出库作业推进 ——
              页面级一次说明，不逐行重复。 */}
          {outbound && (
            <p className="mt-2 text-xs text-neutral-500" data-testid="processing-order-outbound-note">
              卖布单只做出库作业（裁剪 / 打包），没有加工方与交期，报工后按件计件。
            </p>
          )}

          {/* 操作区（issue #7634）：本块**不写生产状态** —— 四个动作只在生产明细页。
              这里只给一个去处，避免商家在销售订单里"直接加工"。 */}
          <div className="po-no-print mt-4 flex flex-wrap items-center gap-2 border-t border-neutral-100 pt-3">
            <Button size="sm" data-testid="po-go-production" onClick={() => router.push(PRODUCTION_PATH(po.processingOrderNo))}>
              去生产明细
            </Button>
            {po.status === 'completed' && (
              <span className="text-xs text-green-600">加工已完成，可发货（发货需在订单物流中填写运单）</span>
            )}
          </div>

        </div>
      )}
    </div>
  )
}
