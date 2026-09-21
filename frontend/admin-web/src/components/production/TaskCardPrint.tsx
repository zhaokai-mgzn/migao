'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { QRCodeSVG } from 'qrcode.react'
import { cn } from '@/lib/utils'
// 工艺规格展示的单一真值定义（设计文档 §4.9「一份 spec，三处渲染」）—— 纸面**只取它的值**，
// 不另写一份推导（否则就是第二份口径，漂移的那一份不会变红）。
import { craftSpecRows, type CraftSpecRow } from '@/lib/craft-display'
// 「第 N 套 / 共 M 套」的**唯一实现**：与进度表**同一份**口径 —— 纸面与屏幕不得各算一套
import { groupBySet } from './ProductionProgressTable'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

/**
 * 加工单**洗水码**（可打印纸面，issue #4964；取代 #4946 的 60×30 横向版）
 *
 * 用户裁定（2026-09-21，逐字意图）：洗水码改**竖版 30mm × 60mm 单列**，照**真实工单**
 * （亿家纺织「成品定制」58mm 竖排小票）的信息顺序；字段面 = 加工单号 / 客户 / 第N套共M套 /
 * 部位 / 件名 / 色号 / 用料 / 宽高 / 加工方式 / 订单号 / 交期 / 备注 / 算料公式 + 二维码与**大字**短码。
 *
 * 🔴 **退场两项**（同一次字段裁定**未选**，勿"顺手加回"）：
 *   ① **工序摘要** —— 工人扫部位码后在 H5 看该部位工序清单（`#4967`），纸面不印；
 *   ② **完整套号**（`JG-…-001`）—— 与行①的加工单号重复，纯占纸面。
 *
 * 打印隔离沿用项目既有范式（见 `frontend/admin-web/src/components/orders/ShipmentDoc.tsx` 文件头的 6 条约束）：
 * 1. **屏幕隐藏、打印可见**：页面已有屏幕布局，本组件 `display:none` + `@media print` 显形；
 * 2. **portal 到 body + display:none 隔离**：`body > *:not(.task-card-print-area) { display:none !important }`
 *    —— display:none 不占版面高度，避免按隐藏内容高度分页打出空白页；
 *    `.task-card-print-area` 必须是 portal 容器本身的 class（不能再包一层）；
 * 3. 不得放进 Modal（面板 `max-h` 会裁掉多页明细）；每页只挂一份（全局选择器）；
 * 4. 二维码内容只放**该部位自己的** `scan_url ?? part_token`（token 化、可撤销），
 *    不放单号拼接串、不放加工单级 `qr_token`；**缺码不画假码**（出占位框）；
 * 5. 🔴 **纸面高度预算（竖版 30×60 的实测账，勿随手加行）**：60mm 高减去上下各 1.2mm 内边距
 *    ⇒ 可用 **57.6mm**；6pt / `line-height 1.2` ⇒ **每行 2.54mm**。当前构成（17 行上限）：
 *    加工单号(7pt，2.96) + 客户 + 套序 + 部位 + 件名(≤2 行) + 色号 + 用料 + 宽高 + 加工方式(≤2 行)
 *    + 订单号 + 交期 + 备注(≤2 行) + 算料公式(≤2 行) ≈ **43.2mm**，底部「二维码 + 短码」行 ≈ **12mm**
 *    ⇒ 合计 ≈ **55.2mm ≤ 57.6mm**（余量 ~2.4mm）。
 *    ⚠️ **余量是给「版式不折行」用的**：60×30 横版时代实测过一次折行吃掉 2.96mm、把纸面底部的人可读短码
 *    挤出纸外（issue #4949）。⇒ 本版把**二维码 + 短码**放在 `shrink-0` 的底部行、文字块用
 *    `min-h-0 overflow-hidden` 承载 —— **空间不够时被裁的是补充文字，绝不裁码与短码**
 *    （短码是设计里明写的降级入口：`docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）。
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
  /** 该部位对应的加工单快照明细（色号/用料/加工方式/备注/算料公式的取值来源） */
  items?: ProcessingOrderItem[]
  className?: string
}

/**
 * 快照行 id 的读取口：后端 `buildSnapshot` **无条件**落 `itemId`（= `order_items.id` 主键，
 * 也是 `position.order_item_id` 的来源），但 `ProcessingOrderItem` 类型未登记该键
 * ⇒ 本地补一个读取口，用它把**快照行**与**部位**对齐（对不上 ⇒ 该张不出这些行，不猜）。
 */
type SnapshotItem = ProcessingOrderItem & { itemId?: string }

/** 用料 = 面料米数优先；没有则退回加工费米数（两者都是「要用多少料」的同一件事） */
const METERS_LABELS = ['面料米数', '加工费米数']

/** 取工艺规格行的值（只按标签取，不重算 —— 格式化真值在 `craft-display`） */
function specValue(rows: CraftSpecRow[], ...labels: string[]): string {
  for (const label of labels) {
    const hit = rows.find((row) => row.label === label)
    if (hit) return hit.value
  }
  return ''
}

/** 成品尺寸：两边都必须是有限数才出（半个尺寸没有意义）⇒ `3×2.75米` */
function sizeText(width?: number | null, height?: number | null): string {
  const ok = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
  return ok(width) && ok(height) ? `${width}×${height}米` : ''
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
  // 套序/套数走**与进度表同一份**实现
  const setViews = groupBySet(list)

  return createPortal(
    <div className={cn('task-card-print-area text-neutral-900', className)}>
      <style>{`
        .task-card-print-area { display: none; }
        @page { size: 30mm 60mm; margin: 0; }
        /* 洗水码本体：固定 30mm × 60mm（竖版），超出一律裁掉（纸面只有这么大） */
        .task-card-label { width: 30mm; height: 60mm; overflow: hidden; box-sizing: border-box;
          padding: 1.2mm; font-size: 6pt; line-height: 1.2; display: flex; flex-direction: column;
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

        const item = position?.order_item_id ? itemsById.get(position.order_item_id) : undefined
        const specRows = craftSpecRows(item)
        // 加工方式 = 工艺 · 加工类型 · 打开方式 · 定型（**值**一律取自 `craft-display` 的同一份格式化，不重算）。
        // 其中「是否定型」在纸面上按**行业措辞**收成「定型 / 不定型」—— 真实工单就是这么写的
        // （图1「单开-韩褶-定型」、图3「双开韩褶 定高买宽 定型」）；单印一个「是」在 27.6mm 宽的
        // 纸面上读不出是哪个字段的「是」。**只映射展示形态，不改值本身**。
        const shaped = specValue(specRows, '是否定型')
        const craftMode = [
          specValue(specRows, '工艺'),
          specValue(specRows, '加工类型'),
          specValue(specRows, '打开方式'),
          shaped === '是' ? '定型' : shaped === '否' ? '不定型' : '',
        ]
          .filter((value) => value !== '')
          .join(' · ')
        const meters = specValue(specRows, ...METERS_LABELS)
        const formula = specValue(specRows, '算料公式')
        // 备注 = 特殊选项（真实工单的「防翘扣 / 花边」那一类）+ 快照备注（缺值不渲染）
        const remark = [specValue(specRows, '特殊选项'), (item?.remark ?? '').trim()]
          .filter((value) => value !== '')
          .join('；')
        // 件名：部位名优先，退回商品名（纸面要能认出「这一张是给哪一件的」）
        const pieceName = position ? position.position_name || position.product_name || '' : ''
        const colorName = typeof item?.colorName === 'string' ? item.colorName.trim() : ''
        // 色号已含在件名里 ⇒ 不重复渲染（纸面只有 27.6mm 宽，重复 = 挤掉别的字段）
        const showColor = colorName !== '' && !pieceName.includes(colorName)
        const size = sizeText(position?.width, position?.height)

        return (
          <div
            key={position?.order_item_id ?? `label-${index}`}
            className="task-card-label"
            data-testid={`task-card-label-${index}`}
          >
            {/* ① 加工单号 —— **主标识**：绝不折行、绝不省略（折行会把纸面底部内容挤出纸外，issue #4949） */}
            <div
              className="shrink-0 whitespace-nowrap text-[7pt] font-bold tracking-wide"
              data-testid="task-card-no"
            >
              {processingOrderNo}
            </div>

            {/* 中部文字块：空间不够时**只裁这里**（底部码与短码 shrink-0，绝不裁） */}
            <div className="mt-[0.5mm] min-h-0 flex-1 overflow-hidden">
              {position ? (
                <>
                  {customerName && (
                    <div className="truncate" data-testid={`task-card-label-customer-${index}`}>
                      客户 {customerName}
                    </div>
                  )}
                  {/* ② 套序：真值源 §1 的行业措辞（`第 N 套 / 共 M 套`） */}
                  <div className="whitespace-nowrap" data-testid={`task-card-label-set-no-${index}`}>
                    第 {setNo} 套 / 共 {setCount} 套
                  </div>
                  {position.position_kind && (
                    <div className="truncate" data-testid={`task-card-label-kind-${index}`}>
                      部位 {position.position_kind}
                    </div>
                  )}
                  {/* ③ 件名（可折 2 行；认件） */}
                  <div className="line-clamp-2" data-testid={`task-card-label-position-${index}`}>
                    {pieceName || '—'}
                  </div>
                  {showColor && (
                    <div className="truncate" data-testid={`task-card-label-color-${index}`}>
                      色号 {colorName}
                    </div>
                  )}
                  {meters && (
                    <div className="truncate" data-testid={`task-card-label-meters-${index}`}>
                      用料 {meters}
                    </div>
                  )}
                  {size && (
                    <div className="truncate" data-testid={`task-card-label-size-${index}`}>
                      宽高 {size}
                    </div>
                  )}
                  {craftMode && (
                    <div className="line-clamp-2" data-testid={`task-card-label-craft-${index}`}>
                      加工方式 {craftMode}
                    </div>
                  )}
                  <div className="whitespace-nowrap" data-testid="task-card-order-no">
                    订单 {orderNo ?? '—'}
                  </div>
                  <div className="whitespace-nowrap" data-testid={`task-card-label-delivery-${index}`}>
                    交期 {expectedDeliveryDate ?? '—'}
                  </div>
                  {remark && (
                    <div className="line-clamp-2" data-testid={`task-card-label-remark-${index}`}>
                      备注 {remark}
                    </div>
                  )}
                  {/* 算料公式（用户字段裁定里的「备注（工艺备注 / 算料公式）」）：
                      形态 = `韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米` ≈ 21.7em
                      ⇒ 27.6mm 宽（≈13em/行）下要 **3 行**才装得下；**clamp 到 2 行会把末端的
                      `= 13.3米`（结果）切掉**，纸面成了「… = …」（渲染实拍实测，issue #4964）。
                      实测余量够 3 行（最坏高度那张正文 2 行时到 40.19mm，QR 行起于 46.9mm）。 */}
                  {formula && (
                    <div className="line-clamp-3 text-neutral-600" data-testid={`task-card-label-formula-${index}`}>
                      {formula}
                    </div>
                  )}
                </>
              ) : (
                <div className="text-neutral-600">
                  该加工单暂无商品/无码可打印{qrPlaceholderHint ? `（${qrPlaceholderHint}）` : ''}
                </div>
              )}
            </div>

            {/* ④ 底部（`shrink-0`）：二维码 + **大字**人可读短码 —— 纸面的功能件，永不被裁 */}
            <div className="mt-[0.5mm] flex shrink-0 items-center gap-[1mm]">
              {qrValue ? (
                <QRCodeSVG value={qrValue} size={45} level="M" title={qrValue} data-testid="task-card-qr" />
              ) : (
                <div
                  data-testid="task-card-qr-placeholder"
                  className="flex h-[12mm] w-[12mm] shrink-0 items-center justify-center border border-dashed border-neutral-400 text-center text-[5pt] text-neutral-500"
                >
                  {qrPlaceholderHint ?? '待生成'}
                </div>
              )}
              {position && (
                <div className="min-w-0">
                  <div className="text-neutral-600">扫码报工</div>
                  <div
                    className="truncate font-mono text-[8pt] font-bold"
                    data-testid={`task-card-label-short-code-${index}`}
                  >
                    {position.part_short_code || '—'}
                  </div>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>,
    document.body,
  )
}
