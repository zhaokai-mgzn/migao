'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { QRCodeSVG } from 'qrcode.react'
import { printPageRuleForLength } from '@/lib/print-media'
// 纸长 = 内容高度（issue #7776）：与免驱动直连通道、打印预览**同一个函数**算出同一个数
import { washLabelBatchLengthMm } from '@/lib/label-print/wash-label-metrics'
import { cn } from '@/lib/utils'
import type { PrintTarget } from '@/lib/print-doc'
// 纸面**内容**的单一真值（issue #6656）：本组件与免驱动直连通道（`lib/label-print/*`）读
// **同一份**有序行清单 —— 两条通道各派生一份字段 = 改一处另一处不红，
// 而那正是「直连打印机打出来的和这里预览的不一样」的根因。
// 取值口径（工艺规格 → `lib/craft-display.ts`、套序 → `groupBySet`）全在这个模块里，本文件不再自己派生。
import {
  WASH_LABEL_COMPANY_SUBTITLE,
  washLabelCompanyName,
  washLabelRows,
  type WashLabelRowKey,
} from '@/lib/wash-label-content'
// 纸面抬头用的企业名（与发货单 / 报价单 / 加工单 / 销售单**同一份**读取口，issue #7219）
import { useCompanyName } from '@/lib/use-company-name'
// 「第 N 套 / 共 M 套」的**唯一实现**：与进度表**同一份**口径 —— 纸面与屏幕不得各算一套
import { groupBySet } from './ProductionProgressTable'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

/**
 * 加工单**洗水码**（可打印纸面，issue #4964 → 版式改判 issue #5646）
 *
 * 用户裁定（2026-09-26，逐字意图）：「**洗水码宽是50，长度根据我们实际需要来定**」
 * ⇒ 纸宽由 #4946 的**竖版 30mm** 改为 **50mm**；长度按同一裁定口径随纸面字段增加而加长
 * （#5646 = 60mm ⇒ 2026-10-25 = **70mm**，见下方第 5 条实测账）。
 * 照**真实工单**（亿家纺织「成品定制」58mm 竖排小票）的信息顺序；字段面 = **纸面抬头（企业名 / 成品定制）**
 * + 加工单号 / 客户 / 第N套共M套 / 部位 / 颜色 / 门幅 / 用料 / 宽高 / 加工方式 / 订单号 / 交期
 * / **特殊选项** / 备注 + 二维码与**大字**短码。
 * （2026-10-25 用户逐字「参考第二张图重新设计，把特殊选项，备注也加上」⇒ ① 抬头块照参考工单加；
 *   ② 特殊选项与备注**各成一行**（改前把「特殊选项；备注」并成一行 ⇒ 纸上分不出哪句是哪类）；
 *   ③ **纸长 60mm → 按内容自适应**（issue #7776），见下方第 5 条。）
 * （2026-10-25 用户逐字「移除商品名称展示，保留货号，颜色，门幅和其他工艺信息，移除褶倍公式字段展示」
 *   ⇒ **件名（商品名称）与算料公式（褶倍公式）两行退场**；颜色改恒印、门幅新增。货号待**加工单快照**
 *   补 `productCode`（后端单，issue #7776 的待办项）—— 未在册前**不拿 SKU 组合码冒充货号**（#7636）。）
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
 * 5. 🔴 **纸长预算：纸长 = 内容高度**（issue #7776；2026-10-25 用户逐字「字体太小了，可以把长度延长些，
 *    因为长度可以无限长，宁愿长点也要把字体和信息都呈现出来……上下两头留白太多了」）：
 *    几何 = **宽 50mm 固定** / **长按内容撑开**（最短 **50mm × 70mm**、上限 150mm）。
 *    **实测方法**（同 #4949）：真组件 → 内联真 Tailwind 产物 → Chromium（`@media print`）按 `@page`
 *    出 PDF，逐元素量底边/右边。纸宽侧读数沿用 #5646 实测：容器 **49.998mm** 宽、正文右边界 48.799mm
 *    减 1.2mm 内边距 ⇒ **版心宽 47.599mm**；正文 **9pt** / `line-height 1.2` ⇒ **每行 3.81mm**
 *    （2026-10-25 6pt → 9pt，1.5 倍）；最短纸长 70mm 减上下各 1.2mm 内边距 ⇒ **可用 67.6mm**。
 *    **逐项预算**：抬头块 12.1mm（企业名 10pt **4.23** + 「成品定制」7pt **2.96** + 0.5 间距）
 *    + 加工单号 10pt **4.23** + 正文每行 **3.81** + 底部行 = 二维码 **11.906mm**
 *    （`text-[12pt]` 短码那两行 8.9mm 不超过它）+ 内边距 **2.4mm** + 两处块间距 **1.0mm**。
 *    常规单（正文 ≈ 15 行）≈ **85mm**；最坏构成（加工方式 / 特殊选项 / 备注各折满 2 行 ≈ 18 行）≈ **96mm**。
 *    ⇒ **纸长不写死**：`frontend/admin-web/src/lib/label-print/wash-label-metrics.ts` 的 `washLabelLengthMm()`
 *    按纸面内容算（上取整到 1mm、夹在 `[70, 150]`），`@page` 用 `printPageRuleForLength()` 现拼，
 *    标签本体的行内 style 给**同一个数**（预览纸框读的也是它）。正文总高 ≤ 纸长上限 150mm。
 *    ⚠️ **余量是给「版式不折行」用的**：30×60 横版时代实测过一次折行吃掉 2.96mm、把纸面底部的人可读短码
 *    挤出纸外（issue #4949）。⇒ 本版把**二维码 + 短码**放在 `shrink-0` 的底部行、文字块用
 *    `min-h-0 overflow-hidden` 承载 —— **空间不够时被裁的是补充文字，绝不裁码与短码**
 *    （短码是设计里明写的降级入口：`docs/design/worker-h5-scan-and-report.md` §1.4「不是可选项」）。
 *    🔴 **退场行腾出的高度不要"顺手加行"填回去**：件名与算料公式各占 2 行（≈15mm），
 *    抬字号（6pt → 9pt）恰好吃回这部分预算 —— 再加一行就会把常规单推到 100mm 以上。
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
  /** 该部位对应的加工单快照明细（颜色/门幅/用料/加工方式/特殊选项/备注的取值来源） */
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
  /**
   * **纸长（mm）** —— 由调用方（生产页）用 `washLabelBatchLengthMm()` 算好后传进来，
   * 好让**打印 / 预览 / 蓝牙直连**三处读同一个数（issue #7776）。不传 ⇒ 本组件自己按
   * 纸面行清单算（`Ctrl+P` 直接打印那条路，算出来与传进来的是同一个函数、同一个值）。
   */
  labelLengthMm?: number
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
  color: 'color',
  doorWidth: 'door-width',
  meters: 'meters',
  size: 'size',
  craft: 'craft',
  orderNo: 'order-no',
  delivery: 'delivery',
  specialOptions: 'special-options',
  remark: 'remark',
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
  color: 'truncate',
  doorWidth: 'truncate',
  meters: 'truncate',
  size: 'truncate',
  craft: 'line-clamp-2',
  orderNo: 'whitespace-nowrap',
  delivery: 'whitespace-nowrap',
  specialOptions: 'line-clamp-2',
  remark: 'line-clamp-2',
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
  labelLengthMm: labelLengthProp,
  className,
}: TaskCardPrintProps) {
  // 打印只发生在客户端；SSR/首帧无 document，portal 前先等 mounted
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  // 纸面抬头：与四张 A4/三联纸单据**同一份**读取口（模块级缓存 ⇒ 同页多份只读一次）
  const companyName = washLabelCompanyName(useCompanyName())

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

  // 🔴 纸面**内容与行序**的唯一来源（issue #6656；与免驱动直连通道同一份）：
  // 客户 / 套序 / 部位 / 颜色 / 门幅 / 用料 / 宽高 / 加工方式 / 订单 / 交期 / 特殊选项 / 备注
  // 的取值口径全在 `washLabelRows` 里面 —— 本文件**不再自己派生**（派生两份 = 两条通道会画得不一样）。
  const rowsByLabel = labels.map((position, index) => {
    if (!position) return []
    const setView = setViews[index]
    const item = position.order_item_id ? itemsById.get(position.order_item_id) : undefined
    return washLabelRows({
      position,
      item,
      setNo: (setView?.setIndex ?? 0) + 1,
      setCount: setView?.setCount ?? 1,
      customerName,
      orderNo,
      expectedDeliveryDate,
    })
  })
  // 纸长 = 这一批里最高的那张（`@page` 是文档级规则，每页纸型不能各不相同）；
  // 调用方（生产页）把同一个数也传给预览与直连通道 —— 三处同源，预览与纸上不会再对不上。
  const labelLengthMm =
    labelLengthProp ??
    washLabelBatchLengthMm(
      rowsByLabel.map((rows, index) => ({
        rows,
        hasCompany: companyName !== '',
        hasQr: Boolean(labels[index]?.scan_url ?? labels[index]?.part_token),
      })),
    )

  const doc = (
    <div
      className={cn('task-card-print-area print-doc text-neutral-900', className)}
      {...(printTarget === 'labels' ? { 'data-print-target': 'labels' } : {})}
    >
      {/* 🔴 纸型规则**只在本次打印目标为本单据时**进文档（issue #5914 的 P1-2）：
          `@page` 是**文档级**规则 —— 同页多份单据并存时**最后声明的那条赢**。 */}
      {printTarget === 'labels' && <style>{printPageRuleForLength('label-50x70', labelLengthMm)}</style>}
      <style>{`
        .task-card-print-area { display: none; }
        /* 洗水码本体：宽固定 50mm、长按内容撑开（issue #7776；行内 style 给实际纸长，
           这里的 70mm 是最短纸长 = 介质矩阵 label-50x70 的 pageBoxMm）。
           ⚠️ 这段注释在**模板字面量**里 ⇒ 不许写 markdown 星号（copy-no-markdown-emphasis 判据会红） */
        .task-card-label { width: 50mm; height: 70mm; overflow: hidden; box-sizing: border-box;
          padding: 1.2mm; font-size: 9pt; line-height: 1.2; display: flex; flex-direction: column;
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
        const qrValue = position ? (position.scan_url ?? position.part_token ?? null) : null
        // 纸面行清单（内容与行序的唯一真值）已在上面按张算好（纸长要按它们逐张算）
        const rows = rowsByLabel[index] ?? []

        return (
          <div
            key={position?.order_item_id ?? `label-${index}`}
            className="task-card-label"
            // 🔴 纸长**按内容撑开**（issue #7776）：与 `@page` 同一个数（上面那一处），
            // 预览纸框也读它 ⇒ 「预览这张纸」与「打出这张纸」是同一张。
            style={{ height: `${labelLengthMm}mm` }}
            data-print-sheet
            data-testid={`task-card-label-${index}`}
          >
            {/* ① 纸面抬头（用户 2026-10-25 裁定照参考工单「亿家纺织 / 成品定制」的形态）：
                企业名 + 副标题，居中两行。企业名缺值 ⇒ **整块不渲染**（纸面是给客户看的，
                不印空行、不印「未设置」）。与免驱动直连通道（`lib/label-print/wash-label.ts`
                的 `company` 块）同字号同位置。 */}
            {companyName !== '' && (
              <div className="shrink-0 text-center" data-testid="task-card-company">
                <div className="text-[10pt] font-bold">{companyName}</div>
                <div className="text-[7pt] text-neutral-600">{WASH_LABEL_COMPANY_SUBTITLE}</div>
              </div>
            )}

            {/* ② 加工单号 —— **主标识**：绝不折行、绝不省略（折行会把纸面底部内容挤出纸外，issue #4949） */}
            <div
              className="shrink-0 whitespace-nowrap text-[10pt] font-bold tracking-wide"
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
                  className="flex h-[12mm] w-[12mm] shrink-0 items-center justify-center border border-dashed border-neutral-400 text-center text-[7pt] text-neutral-500"
                >
                  {qrPlaceholderHint ?? '待生成'}
                </div>
              )}
              {position && (
                <div className="min-w-0">
                  <div className="text-neutral-600">扫码报工</div>
                  <div
                    className="truncate font-mono text-[12pt] font-bold"
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
