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
import {
  WASH_LABEL_COMPANY_SUBTITLE,
  washLabelCompanyName,
  washLabelCopies,
  washLabelRows,
  type WashLabelRowKey,
} from '@/lib/wash-label-content'
// 纸面抬头用的企业名（与发货单 / 报价单 / 加工单 / 销售单**同一份**读取口，issue #7219）
import { useCompanyName } from '@/lib/use-company-name'
// 「第 N 套 / 共 M 套」的**唯一实现**：与进度表**同一份**口径 —— 纸面与屏幕不得各算一套
import { groupBySet } from './ProductionProgressTable'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

/**
 * 加工单**水洗唛**（可打印纸面，issue #4964 → 版式历次改判 #5646 / #7776 / **#7816**）
 *
 * ## 历次裁定的沿革（改版别把历史读成"仍然有效"）
 *
 * - 2026-09-26（issue #5646，**逐字原话，勿删**）：「洗水码宽是50，长度根据我们实际需要来定」
 *   ⇒ 纸宽 50mm 固定、长度随字段增加而加长（60mm → 70mm）。
 * - 2026-10-25（issue #7776）：字号 6pt → 9pt、纸长按内容撑开（夹 70~150mm）、件名与算料公式退场。
 * - 2026-10-26（issue #7816）：纸型固定 50×150、正文 12pt、加「褶法」、份数 = 开数、
 *   订单号提到第一行、加工单号/交期/扫码报工/短码退场、二维码底部居中并放大。
 * - **2026-10-26（issue #7833，现行）**：纸面**折行印全文**（去 `truncate` / `line-clamp`）、
 *   头尾各一条虚线标界线、单号行改印**加工单号**（17 位订单号退出纸面）、
 *   加工方式**去「加工方式」前缀**并**并入加工费组合项**、不再印「加工类型」（定高买宽/定宽买高）。
 *
 * ## 本版（2026-10-26，issue #7833）用户逐字裁定 —— 一次收齐
 *
 * ⑥ 「JG-20261026-8172 这个加工单有超高倒幅，但是在加工单的各个环节都没有体现出来，打印的
 *    洗水唛中也需要体现加工费组合中的信息」⇒ 加工方式行**并入** `processingItems[].name`
 *    （加工费组合键：韩褶 / 超高 / 超宽 / 倒幅 / 定型 …，取值见 `lib/processing-combo.ts`）；
 * ⑦ 「加工方式这几个字可以移除」⇒ 该行**只印值**（`韩褶 · 超高 · 倒幅 · 双开 · 定型`）；
 * ⑧ 「把定高买宽和定宽买高的工艺规格信息不要展示在洗水唛上」⇒ 不再印「加工类型」；
 * ⑨ 「订单号是否可以短一些…只留加工单号，删掉订单行」⇒ 第一行改印 `单号 JG-…`（订单号不上纸）；
 * ⑩ 「打印后的结果出现了文字缩写…自动去换行打印」+「头尾加下虚线」⇒ 行内**折行印全文**
 *    （无省略号 / 无行数截断）+ 标签上下各一条虚线。
 *
 * ## 上一版（2026-10-26，issue #7816）口令（仍然有效的那部分）
 *
 * ① 「水洗唛长度不足，设置为打印50*150」⇒ 纸型**固定 50mm × 150mm**（作废 #7776 的"按内容撑开"）；
 * ② 「如果订单是双开的要打印两份，单开的要打印1份，三开打印3份，4开打印4份，这个都要在
 *    打印预览中默认设置好」⇒ **份数 = 打开方式开数**（`washLabelCopies`，两条通道共用）；
 * ③ 「字体还是太小，可以再大一点」⇒ 正文 9pt → **12pt**（抬头 14pt / 副标题 10pt）；
 * ④ 「要体现出是否采用的韩褶公式以及韩褶的折数，用一个字段表示即可」⇒ 新增 **褶法** 行
 *    （`褶法 韩褶公式 52折` / `褶法 倍数法`，见 `lib/wash-label-content.ts` 的 `washLabelPleats`）；
 * ⑤ 「把订单号放到第一行，客户那一行上面」「移除加工单号」「移除交期字段」
 *    「二维码放到底部居中」「移除扫码报工和短码文字」「二维码可以放大一点」。
 *
 * 字段面（从上到下）= **纸面抬头（企业名 / 成品定制）** → **单号（加工单号）** / 客户 /
 * 第 N 套共 M 套 / 部位 / **货号** / 门幅 / 用料 / 宽高 / 加工方式（含加工费组合项，无前缀）/
 * 褶法 / 特殊选项 / 备注 → 底部**居中二维码**（80 CSS px = 21.17mm）。
 * 一行粒度 = 一部位（商品行）**一张 × 开数份**。
 *
 * 🔴 **退场项（历次字段裁定未选，勿"顺手加回"）**：
 *   ① **工序摘要** —— 工人扫部位码后在 H5 看该部位工序清单（`#4967`），纸面不印；
 *   ② **完整套号**（`JG-…-001`）—— 与加工单号重复，纯占纸面；
 *   ③ **件名（商品名称）与算料公式（褶倍公式）** —— 2026-10-25 用户逐字「移除商品名称展示…
 *      移除褶倍公式字段展示」；
 *   ④ **交期 / 扫码报工 / 人可读短码** —— 2026-10-26 用户逐字（见上 ⑤）。
 *      ⚠️ 短码退场**改变了** `docs/design/worker-h5-scan-and-report.md` §1.4 的"手输降级入口"：
 *      纸面不再提供手输码 ⇒ 扫不出码时只能看屏幕/重新出码（用户裁定，登记在本文件与 CHANGELOG）。
 *   ⑤ **加工类型（定高买宽 / 定宽买高）** —— issue #7833 用户逐字「不要展示在洗水唛上」。
 *      ⚠️ **加工单号**在 #7816 曾退场，issue #7833 起以「单号」行**回到纸面**（它取代了 17 位订单号）——
 *      这是用户 2026-10-26 的**后一次**裁定，不是把 #7816 读错了。
 *
 * ## 纸面几何与垂直预算（实测口径沿用 #4949 / #5646）
 *
 * 纸型 = **50mm × 150mm**（固定；真值源 = `lib/print-media.json` 的 `label-50x150`，本文件不写第二份）。
 * 容器实测沿 #5646：正文右边界 48.799mm 减 1.2mm 内边距 ⇒ **版心宽 47.6mm**；
 * 150mm 高减上下各 1.2mm 内边距 ⇒ **可用 147.6mm**。
 * 正文 12pt / `line-height 1.2` ⇒ **每行 5.08mm**（≈ 11.2 个汉字/行；9pt 时代是 15 个字）。
 * 逐项预算（最坏构成：单号 / 加工方式 / 特殊选项 / 备注各折满 2 行 = 16 行）：
 * 抬头块（企业名 14pt **5.9** + 「成品定制」10pt **4.23** + 0.5 间距 = **10.66**）+ 正文 16 × 5.08 = **81.28**
 * + 两处块间距 **1.5** + 底部二维码 **21.17**（80 CSS px）+ 上下内边距 **2.4**
 * ⇒ **117.01mm ≤ 147.6mm**（余量 **30.59mm** ≈ 6 行）。
 * 🔴 **折行印全文（issue #7833）**：行里**没有** `truncate` / `line-clamp-*`（省略号 = 静默吃掉半截字），
 * 长值（客户 / 部位 / 货号 / 加工方式 / 特殊选项 / 备注）一律折行；真装不下时由「打印预览」的
 * 纸面自检如实报出「内容 Xmm > 可用 Ymm」，**不靠裁切掩盖**（同 `SalesDoc` 的 #7715 口径）。
 * 头尾虚线 = `.task-card-label` 的上下各一条 `1px dashed`（用户同批「头尾加下虚线，这样能清晰知道界线」）。
 * ⚠️ **余量是给「版式不折行」用的**：30×60 横版时代实测过一次折行吃掉 2.96mm、把纸面底部的
 * 功能件挤出纸外（issue #4949）。⇒ 二维码放在 `shrink-0` 的底部行、文字块用
 * `min-h-0 overflow-hidden` 承载 —— **空间不够时被裁的是补充文字，绝不裁码**。
 * 🔴 **别把"余量"读成"可以加行"**：这张纸的岗位信息已经齐了，加行会重新把字号挤回 9pt。
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
 * 5. ⚠️ **别把这个水洗唛挪到德佟 DP30S 上打**：DP30S 是 **203dpi 的 2 英寸头**，**有效打印宽度通常只有
 *    48mm（384 dots）** ⇒ **50mm 宽打不满**，右侧约 2mm 打不到（约束登记在 issue #5052「裁定记录 5」）。
 *    本版按用户 2026-09-26 裁定做 50mm —— 水洗唛今天由 admin-web 走 A4/标签打印机出，**不是 DP30S**；
 *    若将来要上 DP30S，必须先改回 ≤48mm 并重算本条的预算账。
 */
interface TaskCardPrintProps {
  /** 加工单号 —— **纸面第一行**（客户之上；issue #7833 起取代 17 位订单号） */
  processingOrderNo?: string
  /** 加工单公共属性：客户名 —— **每张标签都要呈现** */
  customerName?: string
  /** 部位（= 商品行）列表；一个部位按开数出 N 张，码取自该部位自己的 scan_url/part_token */
  positions?: ProductionPosition[]
  /** 缺码时的占位文案（撤销后传「已撤销」，避免纸面指向不存在的按钮）；缺省＝待生成 */
  qrPlaceholderHint?: string
  /** 该部位对应的加工单快照明细（货号/门幅/用料/加工方式/褶法/特殊选项/备注/开数的取值来源） */
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
  docNo: 'doc-no',
  customer: 'customer',
  setNo: 'set-no',
  positionKind: 'kind',
  sku: 'sku',
  doorWidth: 'door-width',
  meters: 'meters',
  size: 'size',
  craft: 'craft',
  pleats: 'pleats',
  specialOptions: 'special-options',
  remark: 'remark',
}

/**
 * 行 ⇒ `data-testid`。
 *
 * 🔴 2026-10-26 起**每张纸都带张序**（份数 = 开数 ⇒ 同一部位会重复出纸）：订单号那行也按张编，
 * 否则两份纸里 `getAllByTestId('task-card-order-no')` 拿不到第二张（判据会静默只覆盖第一张）。
 */
function washLabelRowTestId(key: WashLabelRowKey, index: number): string {
  return `task-card-label-${WASH_LABEL_TESTID_SEGMENT[key]}-${index}`
}

/**
 * 行 ⇒ 本渲染器（CSS）的样式。
 *
 * 🔴 **只在本文件里**决策：折行是**排版**，不进单一真值模块。
 *
 * 🔴 **纸面不许藏字（issue #7833）**：这里**没有** `truncate` / `line-clamp-*` / `text-overflow`
 * —— 用户 2026-10-26 逐字「打印后的结果出现了文字缩写…自动去换行打印」。
 * 长值一律折行（`break-words`）；纯数字行用 `whitespace-nowrap` 只是**不折行**（不藏字）。
 * 守卫 = `tests/unit_ci_workflows/test_print_paper_full_text_guard.py` 的 C4。
 */
const WASH_LABEL_ROW_CLASS: Record<WashLabelRowKey, string> = {
  // 单号（加工单号）是纸上唯一的单据身份 ⇒ 允许折断、绝不省略/裁切
  docNo: 'break-all',
  customer: 'break-words',
  setNo: 'whitespace-nowrap',
  positionKind: 'break-words',
  sku: 'break-words',
  doorWidth: 'break-words',
  meters: 'break-words',
  size: 'break-words',
  craft: 'break-words',
  pleats: 'whitespace-nowrap',
  specialOptions: 'break-words',
  remark: 'break-words whitespace-pre-line',
}

export default function TaskCardPrint({
  processingOrderNo,
  customerName,
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

  /**
   * 逐张展开：部位 × **开数**（2026-10-26 用户裁定「双开打两份…单开打一份」）。
   *
   * 🔴 份数口径只读 `washLabelCopies`（与免驱动直连通道**同一个**函数）；
   * `sourceIndex` 保留部位序（套序 / 快照行都按它对齐），`sheetIndex` 是纸面张序（testid 用它）。
   */
  const sheets = labels.flatMap((position, sourceIndex) => {
    const item = position?.order_item_id ? itemsById.get(position.order_item_id) : undefined
    const copies = position ? washLabelCopies(item) : 1
    return Array.from({ length: copies }, () => ({ position, sourceIndex }))
  })

  // 🔴 纸面**内容与行序**的唯一来源（issue #6656；与免驱动直连通道同一份）：
  // 单号 / 客户 / 套序 / 部位 / 货号 / 门幅 / 用料 / 宽高 / 加工方式 / 褶法 / 特殊选项 / 备注
  // 的取值口径全在 `washLabelRows` 里面 —— 本文件**不再自己派生**（派生两份 = 两条通道会画得不一样）。
  const rowsBySheet = sheets.map(({ position, sourceIndex }) => {
    if (!position) return []
    const setView = setViews[sourceIndex]
    const item = position.order_item_id ? itemsById.get(position.order_item_id) : undefined
    return washLabelRows({
      position,
      item,
      setNo: (setView?.setIndex ?? 0) + 1,
      setCount: setView?.setCount ?? 1,
      customerName,
      processingOrderNo,
    })
  })

  const doc = (
    <div
      className={cn('task-card-print-area print-doc text-neutral-900', className)}
      {...(printTarget === 'labels' ? { 'data-print-target': 'labels' } : {})}
    >
      {/* 🔴 纸型规则**只在本次打印目标为本单据时**进文档（issue #5914 的 P1-2）：
          `@page` 是**文档级**规则 —— 同页多份单据并存时**最后声明的那条赢**。 */}
      {printTarget === 'labels' && <style>{printPageRule('label-50x150')}</style>}
      <style>{`
        .task-card-print-area { display: none; }
        /* 水洗唛本体：固定 50mm × 150mm（issue #7816），超出一律裁掉（纸面只有这么大）。
           ⚠️ 这段注释在模板字面量里 ⇒ 不许写 markdown 星号（copy-no-markdown-emphasis 判据会红） */
        .task-card-label { width: 50mm; height: 150mm; overflow: hidden; box-sizing: border-box;
          padding: 1.2mm; font-size: 12pt; line-height: 1.2; display: flex; flex-direction: column;
          /* 头尾虚线（issue #7833）：这张纸的上下界线，一眼看得出从哪裁/贴到哪 */
          border-top: 1px dashed #000; border-bottom: 1px dashed #000;
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

      {sheets.map(({ position }, sheetIndex) => {
        const qrValue = position ? (position.scan_url ?? position.part_token ?? null) : null
        const rows = rowsBySheet[sheetIndex] ?? []

        return (
          <div
            key={`${position?.order_item_id ?? 'label'}-${sheetIndex}`}
            className="task-card-label"
            data-print-sheet
            data-testid={`task-card-label-${sheetIndex}`}
          >
            {/* ① 纸面抬头（用户 2026-10-25 裁定照参考工单「亿家纺织 / 成品定制」的形态）：
                企业名 + 副标题，居中两行。企业名缺值 ⇒ **整块不渲染**（纸面是给客户看的，
                不印空行、不印「未设置」）。与免驱动直连通道（`lib/label-print/wash-label.ts`
                的 `company` 块）同字号同位置。 */}
            {companyName !== '' && (
              <div className="shrink-0 text-center" data-testid="task-card-company">
                <div className="text-[14pt] font-bold">{companyName}</div>
                <div className="text-[10pt] text-neutral-600">{WASH_LABEL_COMPANY_SUBTITLE}</div>
              </div>
            )}

            {/* ② 中部文字块（第一行 = **订单号**，2026-10-26 用户裁定「放到第一行，客户上面」）。
                空间不够时**只裁这里**（底部码 shrink-0，绝不裁）。
                `data-testid` 是给「纸面内容 = 唯一真值模块」那条判据读**整块逐行文本**用的：
                在本块里内联多写一行（绕过 `washLabelRows`）⇒ 那条判据必红。 */}
            <div
              className="mt-[0.5mm] min-h-0 flex-1 overflow-hidden"
              data-testid={`task-card-label-rows-${sheetIndex}`}
            >
              {position ? (
                <>
                  {/* 有序行清单（`washLabelRows`）：内容与行序的单一真值，两条打印通道共用。
                      折行 / clamp 由本文件的 `WASH_LABEL_ROW_CLASS` 决定（排版不进真值模块）。 */}
                  {rows.map((row) => (
                    <div
                      key={row.key}
                      className={WASH_LABEL_ROW_CLASS[row.key] || undefined}
                      data-testid={washLabelRowTestId(row.key, sheetIndex)}
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

            {/* ③ 底部（`shrink-0`）：**居中**二维码 —— 纸面的功能件，永不被裁。
                2026-10-26 用户裁定「二维码放到底部居中」「移除扫码报工和短码文字」「二维码可以放大一点」
                ⇒ 80 CSS px（21.17mm），不再画短码/说明字。 */}
            <div className="mt-[1mm] flex shrink-0 items-center justify-center">
              {qrValue ? (
                <QRCodeSVG value={qrValue} size={80} level="M" title={qrValue} data-testid="task-card-qr" />
              ) : (
                <div
                  data-testid="task-card-qr-placeholder"
                  className="flex h-[20mm] w-[20mm] shrink-0 items-center justify-center border border-dashed border-neutral-400 text-center text-[9pt] text-neutral-500"
                >
                  {qrPlaceholderHint ?? '待生成'}
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
