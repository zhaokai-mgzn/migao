'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { QRCodeSVG } from 'qrcode.react'
import { cn } from '@/lib/utils'
// 工艺规格展示的单一真值定义（设计文档 §4.9「一份 spec，三处渲染」）
import { craftSpecLine, craftSpecRows } from '@/lib/craft-display'
// 工序显示名的**唯一**口径（issue #4621）：逻辑名 · 部位 —— 纸面**不得**直接渲染变体名
import { operationDisplayName } from '@/lib/operation-display'
// 「第 N 套 / 共 M 套」的**唯一实现**（issue #4949）：与进度表**同一份**口径 —— 纸面与屏幕不得各算一套
import { groupBySet } from './ProductionProgressTable'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

/**
 * 加工单**洗水码**（可打印纸面，issue #4946；取代此前的 A4 任务卡）
 *
 * 用户裁定（2026-09-21，逐字意图）：加工单按**商品行 = 部位**生产（一个加工单 3 个商品 ⇒ **3 张**
 * 洗水码），每张带**该商品自己的二维码**（= 该部位自己的工序集），而**加工单公共属性
 * （加工单号/订单号/客户名/交期/套号）逐张都要呈现**。
 * 纸面 = **60mm × 30mm**（固定长宽、横向，用户裁定），只能承载**摘要**：部位名 + 工序摘要
 * （道数 + 前几道显示名）+ 工艺摘要（`craftSpecRows` 单行收敛）+ 二维码 + 人可读短码。
 * 真值源：docs/curtain-production-rules.md §1（加工单打印物含二维码，二维码是扫码报工入口）/ §5 扫码报工闭环。
 *
 * 打印隔离沿用项目既有范式（见 components/orders/ShipmentDoc.tsx 文件头的 6 条约束）：
 * 1. **屏幕隐藏、打印可见**：页面已有屏幕布局，本组件 `display:none` + `@media print` 显形，
 *    屏幕上零视觉改动、打印时只有这些洗水码。
 * 2. **portal 到 body + display:none 隔离**：`body > *:not(.task-card-print-area) { display:none !important }`
 *    —— display:none 不占版面高度，避免按隐藏内容高度分页打出空白页。
 *    `.task-card-print-area` 必须是 portal 容器本身的 class（不能再包一层）。
 * 3. 不得放进 Modal（面板 max-h 会裁掉多页明细）；每页只挂一份（全局选择器）。
 * 4. 二维码内容只放**该部位自己的** `scan_url ?? part_token`（token 化、可撤销），
 *    不放单号拼接串、不放加工单级 `qr_token`（issue #4946：粒度 = 商品行）。
 *    **缺码不画假码**：出占位框（工人按短码手输或找班长补码）。
 * 5. 🔴 **纸面高度预算**（issue #4949，实测，勿随手加行）：60×30mm 减去上下各 1.2mm 内边距
 *    ⇒ 可用 **27.6mm**。当前占用 = 行①（加工单号 + 第 N 套/共 M 套，**必须单行** 2.96mm）
 *    + 行②（订单/客户/交期 2.54mm）+ `mt-[0.5mm]` + 行③ 右列（二维码 14.82mm + 「扫码报工」
 *    2.54mm + 人可读短码 2.54mm = **19.89mm**）= **25.89mm，余量 1.7mm**。
 *    ⚠️ 行① 一旦折行（两个长标识同排、无 `shrink-0`/`whitespace-nowrap`）就吃 **5.92mm**
 *    ⇒ 越过预算 ⇒ `overflow:hidden` 会**静默裁掉纸面底部的人可读短码**（实测裁 1.25mm）——
 *    而短码是设计里明写的**降级入口**（扫码工具读不出来时手输，见
 *    `docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）。加行/加字号前先算这笔账。
 */
interface TaskCardPrintProps {
  processingOrderNo: string
  orderNo?: string
  /** 加工单公共属性：客户名 —— **每张标签都要呈现** */
  customerName?: string
  /** 加工单公共属性：交期 —— **每张标签都要呈现** */
  expectedDeliveryDate?: string
  /** 部位（= 商品行）列表；一个部位一张洗水码，码取自该部位自己的 scan_url/part_token */
  positions?: ProductionPosition[]
  /** 缺码时的占位文案（撤销后传「已撤销」，避免纸面指向不存在的按钮）；缺省＝待生成 */
  qrPlaceholderHint?: string
  /** 该部位对应的加工单快照明细（condensed 工艺摘要用；键与 position.order_item_id 对齐） */
  items?: ProcessingOrderItem[]
  className?: string
}

/** 摘要里最多印几道工序显示名（60×30mm 装不下全部；超出以「…」收口，绝不溢出纸面） */
const OPS_SUMMARY_LIMIT = 3

/**
 * 快照行 id 的读取口：后端 `buildSnapshot` **无条件**落 `itemId`（= `order_items.id` 主键，
 * 也是 `position.order_item_id` 的来源），但 `ProcessingOrderItem` 类型未登记该键
 * ⇒ 本地补一个读取口，用它把**快照行**与**部位**对齐（对不上 ⇒ 该张不出工艺摘要，不猜）。
 */
type SnapshotItem = ProcessingOrderItem & { itemId?: string }

/** 工序摘要：`工序 11 道：精裁 · 布帘 → 三边 · 布帘 → 韩褶 · 布帘 …`（显示名只走 #4621 的唯一实现） */
function opsSummary(position: ProductionPosition): string {
  const operations = position.operations ?? []
  const names = operations.map((op) => operationDisplayName(op)).filter((name) => name !== '')
  const shown = names.slice(0, OPS_SUMMARY_LIMIT)
  const body = shown.length > 0 ? `：${shown.join(' → ')}${names.length > shown.length ? ' …' : ''}` : ''
  return `工序 ${operations.length} 道${body}`
}

/** 工艺摘要（issue #4355 的摘要形态）：`工艺：韩褶 · 加工类型：定高买宽 · …`（单行由 CSS 收敛） */
function craftSummary(item?: ProcessingOrderItem): string {
  if (!item) return ''
  return craftSpecRows(item).map((row) => craftSpecLine(row)).join(' · ')
}

export default function TaskCardPrint({
  processingOrderNo,
  orderNo,
  customerName,
  expectedDeliveryDate,
  positions,
  qrPlaceholderHint,
  items,
  className,
}: TaskCardPrintProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  if (!mounted) return null

  const list = positions ?? []
  // 快照行按 `itemId` 索引（与 position.order_item_id 对齐）
  const itemsById = new Map<string, ProcessingOrderItem>()
  for (const item of items ?? []) {
    const id = (item as SnapshotItem).itemId
    if (id) itemsById.set(id, item)
  }
  // 0 个部位 ⇒ 仍出**一张**显式占位（明确「无商品/无码可打印」），而不是什么都不打
  const labels: (ProductionPosition | null)[] = list.length > 0 ? list : [null]
  // 套序/套数走**与进度表同一份**实现（issue #4949）
  const setViews = groupBySet(list)

  return createPortal(
    <div className={cn('task-card-print-area text-neutral-900', className)}>
      <style>{`
        .task-card-print-area { display: none; }
        @page { size: 60mm 30mm; margin: 0; }
        /* 洗水码本体：固定 60mm × 30mm，超出一律裁掉（纸面只有这么大） */
        .task-card-label { width: 60mm; height: 30mm; overflow: hidden; box-sizing: border-box;
          padding: 1.2mm; font-size: 6pt; line-height: 1.2;
          break-after: page; page-break-after: always; }
        /* 最后一张不再分页（否则末尾多吐一张空白） */
        .task-card-label:last-child { break-after: auto; page-break-after: auto; }
        @media print {
          body > *:not(.task-card-print-area) { display: none !important; }
          .task-card-print-area {
            display: block;
            position: static;
            width: auto;
          }
          /* 防御：页面其他组件残留的 "body * { visibility: hidden }" 打印隔离
             （如 ProcessingOrderBlock）会连同本组件一起藏掉 —— 显式恢复自身可见 */
          .task-card-print-area, .task-card-print-area * { visibility: visible; }
        }
      `}</style>

      {labels.map((position, index) => {
        const setView = position ? setViews[index] : undefined
        const setNo = setView ? setView.setIndex + 1 : 1
        const setCount = setView ? setView.setCount : 1
        const qrValue = position ? (position.scan_url ?? position.part_token ?? null) : null
        const craft = craftSummary(position?.order_item_id ? itemsById.get(position.order_item_id) : undefined)

        return (
          <div
            key={position?.order_item_id ?? `label-${index}`}
            className="task-card-label flex flex-col justify-between"
            data-testid={`task-card-label-${index}`}
          >
            {/* 加工单公共属性（**逐张**都在）：加工单号 + 套序。
                🔴 行①**必须单行**（issue #4949）：加工单号 `shrink-0` + 右span `whitespace-nowrap`
                —— 折行会吃 2.96mm，把纸面底部的人可读短码挤出纸外（实测被裁 1.25mm）。
                完整套号放不进行①（两个长标识同排 ⇒ 折行）⇒ 移到左列（那里有纵向余量，见下）。 */}
            <div className="flex items-baseline justify-between gap-[1mm]">
              <span
                className="shrink-0 whitespace-nowrap text-[7pt] font-bold tracking-wide"
                data-testid="task-card-no"
              >
                {processingOrderNo}
              </span>
              {position && (
                <span
                  className="whitespace-nowrap text-neutral-600"
                  data-testid={`task-card-label-set-no-${index}`}
                >
                  第 {setNo} 套 / 共 {setCount} 套
                </span>
              )}
            </div>

            {/* 加工单公共属性：订单号 / 客户名 / 交期 */}
            <div className="truncate text-neutral-700">
              订单 <span data-testid="task-card-order-no">{orderNo ?? '—'}</span> · 客户{' '}
              {customerName ?? '—'} · 交期 {expectedDeliveryDate ?? '—'}
            </div>

            <div className="mt-[0.5mm] flex min-h-0 flex-1 items-start gap-[1mm]">
              <div className="min-w-0 flex-1">
                {position ? (
                  <>
                    <div
                      className="truncate font-semibold"
                      data-testid={`task-card-label-position-${index}`}
                    >
                      {position.position_name || position.product_name || '—'}
                    </div>
                    {/* 工序摘要（道数 + 显示名；变体名不上纸面，issue #4621） */}
                    <div data-testid={`task-card-label-ops-${index}`}>
                      {opsSummary(position)}
                    </div>
                    {/* 工艺摘要（issue #4355 的摘要形态）：单行收敛，缺值不渲染 */}
                    {craft && (
                      <div
                        className="truncate text-neutral-600"
                        data-testid={`task-card-label-craft-${index}`}
                      >
                        {craft}
                      </div>
                    )}
                    {/* 完整套号（issue #4949）：从行①搬进**左列** —— 左列实测只用 10.15mm/19.89mm
                        （QR 列高才是纸面的约束），有纵向余量；而行① 放不下两个长标识。纸面标识一个不少。 */}
                    {position.set_no && (
                      <div
                        className="truncate text-neutral-500"
                        data-testid={`task-card-label-set-code-${index}`}
                      >
                        套号 {position.set_no}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-neutral-600">
                    该加工单暂无商品/无码可打印{qrPlaceholderHint ? `（${qrPlaceholderHint}）` : ''}
                  </div>
                )}
              </div>

              <div className="w-[17mm] shrink-0 text-center">
                {qrValue ? (
                  <QRCodeSVG value={qrValue} size={56} level="M" title={qrValue} data-testid="task-card-qr" />
                ) : (
                  <div
                    data-testid="task-card-qr-placeholder"
                    className="mx-auto flex h-[15mm] w-[15mm] items-center justify-center border border-dashed border-neutral-400 text-center text-[5pt] text-neutral-500"
                  >
                    {qrPlaceholderHint ?? '待生成'}
                  </div>
                )}
                <div className="text-neutral-600">扫码报工</div>
                {position && (
                  <div
                    className="truncate font-mono font-semibold"
                    data-testid={`task-card-label-short-code-${index}`}
                  >
                    {position.part_short_code || '—'}
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })}
    </div>,
    document.body,
  )
}
