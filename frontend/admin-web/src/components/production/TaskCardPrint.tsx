'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { QRCodeSVG } from 'qrcode.react'
import { printPageRule } from '@/lib/print-media'
import { cn } from '@/lib/utils'
import type { PrintTarget } from '@/lib/print-doc'
// 纸面**内容**的单一真值（issue #6656）：本组件与免驱动直连通道（`lib/label-print/*`）读
// **同一份**有序行清单 —— 两条通道各派生一份字段 = 改一处另一处不红，
// 而那正是「直连打印机打出来的和这里预览的不一样」的根因。
// 取值口径（工艺规格 → `lib/craft-display.ts`、套序 → `groupBySet`）全在这个模块里，本文件不再自己派生。
import { washLabelRows, type WashLabelRowKey } from '@/lib/wash-label-content'
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
  /**
   * 本次打印的目标（`'labels'` = 打印本单据）。**必须由调用方置位**：标签的显形规则按
   * `[data-print-target='labels']` 限定 ⇒ 不置位就**不上纸**（issue #5914 的「一次只放一份」）。
   */
  printTarget?: PrintTarget | null
  /**
   * **原地渲染**（`true`）而不是 portal 到 `document.body`（issue #5914）—— 只有**打印预览层**
   * 用它：预览要把**同一份单据**摆进真尺寸纸框里，portal 会让它跑到框外（且屏幕态仍是 `display:none`）。
   * 缺省 `false` = 既有行为（portal 到 body，屏幕上隐藏、仅打印呈现）。
   */
  inline?: boolean
  className?: string
}

/**
 * 快照行 id 的读取口：后端 `buildSnapshot` **无条件**落 `itemId`（= `order_items.id` 主键，
 * 也是 `position.order_item_id` 的来源），但 `ProcessingOrderItem` 类型未登记该键
 * ⇒ 本地补一个读取口，用它把**快照行**与**部位**对齐（对不上 ⇒ 该张不出这些行，不猜）。
 */
type SnapshotItem = ProcessingOrderItem & { itemId?: string }

/** 行 ⇒ `data-testid` 的中段（与 issue #5646 起的既有 testid 逐字一致，别改名） */
const WASH_LABEL_TESTID_SEGMENT: Record<WashLabelRowKey, string> = {
  customer: 'customer',
  setNo: 'set-no',
  positionKind: 'kind',
  pieceName: 'position',
  color: 'color',
  meters: 'meters',
  size: 'size',
  craft: 'craft',
  orderNo: 'order-no',
  delivery: 'delivery',
  remark: 'remark',
  formula: 'formula',
}

/** 行 ⇒ `data-testid`（订单号是加工单级的**单**一处，不带张序） */
function washLabelRowTestId(key: WashLabelRowKey, index: number): string {
  return key === 'orderNo' ? 'task-card-order-no' : `task-card-label-${WASH_LABEL_TESTID_SEGMENT[key]}-${index}`
}

/**
 * 行 ⇒ 本渲染器（CSS）的样式。
 *
 * 🔴 **只在本文件里**决策：折行 / `line-clamp` 是**排版**，不进单一真值模块
 * （位图渲染器读行里的 `maxLines` 自己排）。
 */
const WASH_LABEL_ROW_CLASS: Record<WashLabelRowKey, string> = {
  customer: 'truncate',
  setNo: 'whitespace-nowrap',
  positionKind: 'truncate',
  pieceName: '',
  color: 'truncate',
  meters: 'truncate',
  size: 'truncate',
  craft: 'line-clamp-2',
  orderNo: 'whitespace-nowrap',
  delivery: 'whitespace-nowrap',
  remark: 'line-clamp-2',
  formula: 'line-clamp-2 text-neutral-600',
}

export default function TaskCardPrint({
  processingOrderNo,
  orderNo,
  customerName,
  expectedDeliveryDate,
  positions,
  qrPlaceholderHint,
  items,
  printTarget,
  inline,
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

  const doc = (
    <div
      className={cn('task-card-print-area print-doc text-neutral-900', className)}
      {...(printTarget === 'labels' ? { 'data-print-target': 'labels' } : {})}
    >
      {/* 🔴 纸型规则**只在本次打印目标为本单据时**进文档（issue #5914 的 P1-2）：
          `@page` 是**文档级**规则 —— 同页多份单据并存时**最后声明的那条赢**。 */}
      {printTarget === 'labels' && <style>{printPageRule('label-50x60')}</style>}
      <style>{`
        .task-card-print-area { display: none; }
        /* 洗水码本体：固定 50mm × 60mm（竖版），超出一律裁掉（纸面只有这么大） */
        .task-card-label { width: 50mm; height: 60mm; overflow: hidden; box-sizing: border-box;
          padding: 1.2mm; font-size: 6pt; line-height: 1.2; display: flex; flex-direction: column;
          break-after: page; page-break-after: always; }
        /* 最后一张不再分页（否则末尾多吐一张空白） */
        .task-card-label:last-child { break-after: auto; page-break-after: auto; }
        @media print {
          body > *:not(.print-doc) { display: none !important; }
          /* 🔴 只有「本次目标」上纸（issue #5914）：否则打印会同时吐出别的单据的版面 */
          .task-card-print-area[data-print-target='labels'] {
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
        const qrValue = position ? (position.scan_url ?? position.part_token ?? null) : null
        const item = position?.order_item_id ? itemsById.get(position.order_item_id) : undefined
        // 🔴 纸面**内容与行序**的唯一来源（issue #6656；与免驱动直连通道同一份）：
        // 客户 / 套序 / 部位 / 件名 / 色号（去重）/ 用料 / 宽高 / 加工方式 / 订单 / 交期 / 备注 / 算料公式
        // 的取值口径全在 `washLabelRows` 里面 —— 本文件**不再自己派生**（派生两份 = 两条通道会画得不一样）。
        const rows = position
          ? washLabelRows({
              position,
              item,
              setNo: (setView?.setIndex ?? 0) + 1,
              setCount: setView?.setCount ?? 1,
              customerName,
              orderNo,
              expectedDeliveryDate,
            })
          : []

        return (
          <div
            key={position?.order_item_id ?? `label-${index}`}
            className="task-card-label"
            data-print-sheet
            data-testid={`task-card-label-${index}`}
          >
            {/* ① 加工单号 —— **主标识**：绝不折行、绝不省略（折行会把纸面底部内容挤出纸外，issue #4949） */}
            <div
              className="shrink-0 whitespace-nowrap text-[7pt] font-bold tracking-wide"
              data-testid="task-card-no"
            >
              {processingOrderNo}
            </div>

            {/* 中部文字块：空间不够时**只裁这里**（底部码与短码 shrink-0，绝不裁）。
                `data-testid` 是给「纸面内容 = 唯一真值模块」那条判据读**整块逐行文本**用的：
                在本块里内联多写一行（绕过 `washLabelRows`）⇒ 那条判据必红。 */}
            <div
              className="mt-[0.5mm] min-h-0 flex-1 overflow-hidden"
              data-testid={`task-card-label-rows-${index}`}
            >
              {position ? (
                <>
                  {/* ② 有序行清单（`washLabelRows`）：内容与行序的单一真值，两条打印通道共用。
                      折行 / clamp 由本文件的 `WASH_LABEL_ROW_CLASS` 决定（排版不进真值模块）。 */}
                  {rows.map((row) => (
                    <div
                      key={row.key}
                      className={WASH_LABEL_ROW_CLASS[row.key] || undefined}
                      data-testid={washLabelRowTestId(row.key, index)}
                    >
                      {row.text}
                    </div>
                  ))}
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
    </div>
  )

  // 🔴 预览层里**不 portal**（issue #5914）：同一份单据要摆进真尺寸纸框，portal 会跑到框外
  return inline ? doc : createPortal(doc, document.body)
}
