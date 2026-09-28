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
 * 加工单**洗水码**（可打印纸面，issue #4964 → 版式改判 issue #5646）
 *
 * 用户裁定（2026-09-26，逐字意图）：「**洗水码宽是50，长度根据我们实际需要来定**」
 * ⇒ 本版把纸型由 #4946 的**竖版 30mm × 60mm** 改为 **竖版 50mm × 60mm**（长度见下方第 5 条实测账）。
 * 照**真实工单**（亿家纺织「成品定制」58mm 竖排小票）的信息顺序；字段面 = 加工单号 / 客户 / 第N套共M套 /
 * 部位 / 件名 / 色号 / 用料 / 宽高 / 加工方式 / 订单号 / 交期 / 备注 / 算料公式 + 二维码与**大字**短码。
 *
 * 🔴 **退场两项**（同一次字段裁定**未选**，勿"顺手加回"）：
 *   ① **工序摘要** —— 工人扫部位码后在 H5 看该部位工序清单（`#4967`），纸面不印；
 *   ② **完整套号**（`JG-…-001`）—— 与行①的加工单号重复，纯占纸面。
 *
 * 🔴 **30mm → 50mm 时被推翻的三条「窄版心妥协」**（宽 30→50 把版心由 27.6mm 抬到 47.599mm，+72%）：
 *   ① **件名不再 clamp 到 2 行** —— 版心约 22.5em/行（旧 ≈13em/行）⇒ 实测最长件名折 2 行，
 *      再给 clamp 只会平白砍掉真名（该 clamp 当年只为 27.6mm 版心而设）；
 *   ② **加工方式不再折 2 行** —— 实测「加工方式 罗马帘 · 定宽买高 · 三开 · 定型」(≈22em) 在 47.599mm
 *      下**恰好 1 行**（30mm 下同样的值要 2 行）；`line-clamp-2` 仅作**预算上界**保留；
 *   ③ **算料公式 clamp 3 行 → 2 行** —— 两条真公式串（`curtain_calc._formula_text` 的两种登记形态）
 *      在 47.599mm 下都**恰好 2 行**（30mm 下「韩褶公式」串要 3 行）。容量不退反增：
 *      本版 2 × 22.5em = **45em** > 30mm 时代的 3 × 13em = **39em**。
 *   `色号`的**去重**（件名已含色号 ⇒ 不重复渲染）**保留**：50mm 下恢复独立渲染只会多印一遍同名信息、
 *   白吃 2.538mm 高度预算（实测件名已含色号的单占比不低），**不恢复**。
 *
 * 打印隔离沿用项目既有范式（见 `frontend/admin-web/src/components/orders/ShipmentDoc.tsx` 文件头的 6 条约束）：
 * 1. **屏幕隐藏、打印可见**：页面已有屏幕布局，本组件 `display:none` + `@media print` 显形；
 * 2. **portal 到 body + display:none 隔离**：`body > *:not(.print-doc) { display:none !important }`
 *    —— display:none 不占版面高度，避免按隐藏内容高度分页打出空白页；
 *    `.task-card-print-area` 必须是 portal 容器本身的 class（不能再包一层），且**必须同时带共享标记类
 *    `print-doc`**（issue #4983，来自 #4965 的实测）：按「自己那一份」写选择器
 *    （`body > *:not(.task-card-print-area)`）会把**兄弟单据也选进来**整份 `display:none` 掉 ——
 *    同一页挂两份打印单据时各自把对方藏掉；共享 `print-doc` 是让「排除所有打印单据」成立的唯一写法。
 *    守卫 = `tests/unit_ci_workflows/test_print_doc_convention_guard.py`；
 * 3. 不得放进 Modal（面板 `max-h` 会裁掉多页明细）；每页只挂一份（全局选择器）；
 * 4. 二维码内容只放**该部位自己的** `scan_url ?? part_token`（token 化、可撤销），
 *    不放单号拼接串、不放加工单级 `qr_token`；**缺码不画假码**（出占位框）；
 * 5. 🔴 **纸面高度预算（竖版 50×60 的实测账，勿随手加行；issue #5646）**：
 *    **实测方法**（同 #4949）：真组件 → 内联真 Tailwind 产物 → Chromium（`@media print`）按 `@page`
 *    出 PDF，逐元素量底边/右边。本版读数：容器 **49.998mm × 59.998mm**、PDF MediaBox
 *    **142.08 × 169.92 pt = 50.13 × 59.97mm**（= `@page 50mm 60mm`，每张独占一页）、
 *    正文右边界 48.799mm 减 1.2mm 内边距 ⇒ **版心宽 47.599mm**、6pt / `line-height 1.2`
 *    ⇒ **每行 2.538mm**（行高与 30mm 时代**同值**；变的是每行装多少字：27.6mm ≈ 13em/行 → 47.599mm ≈ **22.5em/行**）。
 *    60mm 高减上下各 1.2mm ⇒ 可用 **57.6mm**。逐行实测（**最坏场景**：长件名 + 备注 2 行 + 算料公式 2 行）：
 *    加工单号(7pt, **2.96**) + 客户 2.538 + 套序 2.538 + 部位 2.538 + 件名(2 行, **5.077**) + 色号 2.538
 *    + 用料 2.538 + 宽高 2.538 + 加工方式(1 行, 2.538) + 订单号 2.538 + 交期 2.538 + 备注(2 行, **5.077**)
 *    + 算料公式(2 行, **5.077**) ⇒ 中部文字块 **38.071mm**；再加加工单号块 2.96、中部上下各 0.5mm 间距
 *    与底部「二维码(45px = **11.906**) + 人可读短码」行 ⇒ 正文总高 **56.337mm ≤ 60mm**。
 *    **保守上界**（加工方式也按 `line-clamp-2` 折满 2 行）= 38.071 + 2.538 = **40.612mm** ⇒ 正文 **58.878mm**。
 *    **长度取值理由**（用户 2026-09-26「长度按实际需要来定」）：按最坏 **56.337mm** 向上取整到标准标签长度
 *    ⇒ **60mm**（余量 **3.663mm** ≈ 1.44 行；即便退化成上面的保守上界也仍有 **1.122mm** 余量）。
 *    ⚠️ 长度与 #4946 同值**是实测结论、不是沿用**：`L` 逐值扫描（50/54/55/56/57/58/59/60/62mm）给出
 *    「中部文字块不被裁」的最小 L = **57mm**（56mm 实测被裁 **0.265mm**、55mm 被裁 **1.323mm**）
 *    ⇒ **60mm 以下不安全**。
 *    ⚠️ **余量是给「版式不折行」用的**：30×60 横版时代实测过一次折行吃掉 2.96mm、把纸面底部的人可读短码
 *    挤出纸外（issue #4949）。⇒ 本版把**二维码 + 短码**放在 `shrink-0` 的底部行、文字块用
 *    `min-h-0 overflow-hidden` 承载 —— **空间不够时被裁的是补充文字，绝不裁码与短码**
 *    （短码是设计里明写的降级入口：`docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）。
 *    件名已按第 ① 条**去掉 clamp** ⇒ 超过「2 行」的件名（需 > 45em ≈ 45 个汉字，实测最长件名只用 2 行）
 *    会把中部补充文字挤出可视区 —— 这正是上面那条设计取舍的**兜底面**，不是静默裁切：码与短码仍在。
 * 6. ⚠️ **别把这个洗水码挪到德佟 DP30S 上打**：DP30S 是 **203dpi 的 2 英寸头**，**有效打印宽度通常只有
 *    48mm（384 dots）** ⇒ **50mm 宽打不满**，右侧约 2mm 打不到（约束登记在 issue #5052「裁定记录 5」）。
 *    本版按用户 2026-09-26 裁定做 50mm —— 洗水码今天由 admin-web 走 A4/标签打印机出，**不是 DP30S**；
 *    若将来要上 DP30S，必须先改回 ≤48mm 并重算本条的预算账。
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

/** 宽高（= 窗宽 × 窗高；成品宽 = 窗宽、成品高 = 窗高，用户 2026-09-21 裁定 issue #5030）：
 * 两边都必须是有限数才出（半个尺寸没有意义）⇒ `3×2.75米` */
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
    <div className={cn('task-card-print-area print-doc text-neutral-900', className)}>
      <style>{`
        .task-card-print-area { display: none; }
        @page { size: 50mm 60mm; margin: 0; }
        /* 洗水码本体：固定 50mm × 60mm（竖版），超出一律裁掉（纸面只有这么大） */
        .task-card-label { width: 50mm; height: 60mm; overflow: hidden; box-sizing: border-box;
          padding: 1.2mm; font-size: 6pt; line-height: 1.2; display: flex; flex-direction: column;
          break-after: page; page-break-after: always; }
        /* 最后一张不再分页（否则末尾多吐一张空白） */
        .task-card-label:last-child { break-after: auto; page-break-after: auto; }
        @media print {
          body > *:not(.print-doc) { display: none !important; }
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
        // （图1「单开-韩褶-定型」、图3「双开韩褶 定高买宽 定型」）；单印一个「是」在纸面上读不出
        // 是哪个字段的「是」。**只映射展示形态，不改值本身**。
        // 版心 47.599mm ≈ 22.5em/行（issue #5646 实测）⇒ 实测最长形态
        // 「加工方式 罗马帘 · 定宽买高 · 三开 · 定型」(≈22em) **恰好 1 行**；`line-clamp-2` 只作预算上界。
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
        // 色号已含在件名里 ⇒ 不重复渲染。**50mm 下仍保留这条去重**（issue #5646 按实测裁定）：
        // 版心由 27.6mm 抬到 47.599mm 后空间虽宽裕，但恢复独立渲染只会把同一个色号多印一遍、
        // 白吃 2.538mm（一行）高度预算，而预算已用到 58.878/60mm。
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
                  {/* ③ 件名（可折行、不再 clamp；认件） */}
                  <div data-testid={`task-card-label-position-${index}`}>
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
                      形态 = `韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米`；
                      另一登记形态 = `褶倍数公式：(5.5÷2)×2 → 每片 2.75×2=5.5米 ×2片 = 11米`。
                      🔴 issue #5646 实测改判 **clamp 3 行 → 2 行**：两条真公式串在 47.599mm 版心
                      （≈22.5em/行）下都**恰好 2 行**（30mm 时代「韩褶公式」串要 3 行）。
                      容量不退反增：2 × 22.5em = **45em** > 旧口径 3 × 13em = **39em**；
                      高度预算同时省下 2.538mm（这正是最坏情况能收进 60mm 的原因）。
                      ⚠️ 不许再回到 3 行：最坏构成（件名 2 + 加工方式 2 + 备注 2 + 公式 3 行）
                      实测需 61.4mm > 60mm ⇒ 会把中部文字挤出纸外。 */}
                  {formula && (
                    <div className="line-clamp-2 text-neutral-600" data-testid={`task-card-label-formula-${index}`}>
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
