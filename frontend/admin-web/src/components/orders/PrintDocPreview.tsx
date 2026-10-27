'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import { printBodyFontPt, printContentInsetMm, printPageBoxMm, type PrintMediaId } from '@/lib/print-media'
import { captureNodeToPngBlob, copyPngToClipboard, downloadPng } from '@/lib/print-capture'
import { extractApiErrorMessage } from '@/lib/api-error'
import type { PrintBatchController, PrintTarget } from '@/lib/print-doc'
import { PRINT_TARGET_SPECS } from '@/lib/print-doc'
// 纸型 → 打印机引导 + 本机登记（issue #7957）：浏览器**不能**选/读打印机 ⇒ 只做提示与登记
import { printerKindOf, readPrinterName, savePrinterName } from '@/lib/print-printer'

/**
 * 打印前的**纸面自检层**（issue #5914 的功能③）—— 真尺寸纸框 + 溢出/页数自检 + 纸型提示。
 *
 * ## 为什么不是「通用预览器」
 *
 * 浏览器自带的打印预览已经能看版面，它答不了的是这三件（issue #5914 实证）：
 * ① 内容**超出这一联/这一页被裁**（销售单单联 128mm，>6 行明细即被 `overflow:hidden` 静默裁掉，
 *    裁掉的恰好是「本单应收 / 账户余额 / 收款码」）；
 * ② **非标纸型**（241×140 / 50×150）在驱动里没登记自定义纸型时的落差；
 * ③ 同一页挂着四份单据时**这次到底打哪一张、什么纸**。
 *
 * ## 三条硬约束
 *
 * 1. **不产生第二份字段映射**：预览渲染的是**同一个单据组件**（守卫 C5：列清单全仓唯一）；
 * 2. 🔴 预览实例**永远不上纸**：它拿到的 `printTarget` 是 `null` ⇒ 不带 `data-print-target`
 *    ⇒ 打印媒体下仍是 `display: none`（否则打印会出**两份**）。本组件的显形规则一律包在
 *    `@media screen` 里，绝不外溢到打印；
 * 3. **尺寸从介质矩阵读**（`printPageBoxMm` / `printUsableBoxMm` / `printBodyFontPt`）——
 *    本组件**不自带**任何纸型字面量。
 */

/** 自检结果（纸面装不装得下） */
export interface SheetCheckResult {
  /** 内容实际高度（mm） */
  contentMm: number
  /** 单页/单联可用高度（mm） */
  limitMm: number
  /** 超出多少（mm）；`<= 0` = 装得下 */
  overflowMm: number
  /** 预计页数（A4 这类自然分页的介质才有意义；连续纸固定 1） */
  pages: number
  /** 本单据由几张「纸」组成（水洗唛 = 一部位 × 开数） */
  sheets: number
  /**
   * **超出的那几张**（1 起，按纸序）；空数组 = 都装得下。
   *
   * 为什么逐张列（issue #7833）：洗水唛一张一味位、还按开数重复出纸，
   * 「内容超出」只报一个总高度时，商家不知道该改哪一张/哪一行；具名到张才是可行动的读数。
   */
  overflowSheets: number[]
}

const PX_PER_MM = 96 / 25.4

function round1(value: number): number {
  return Math.round(value * 10) / 10
}

/** 量出纸面自检结果（纯几何，无业务口径）；`sheets` 为空 ⇒ `null`（没有可量的纸） */
export function measureSheets(stage: HTMLElement, limitMm: number): SheetCheckResult | null {
  const sheets = Array.from(stage.querySelectorAll<HTMLElement>('[data-print-sheet]'))
  if (sheets.length === 0) return null
  const limitPx = limitMm * PX_PER_MM
  let maxContentPx = 0
  const overflowSheets: number[] = []
  sheets.forEach((sheet, index) => {
    // 🔴 量的是**内容真实高度**，不是容器高度：销售单的 `.sales-sheet` 固定 128mm + `overflow:hidden`
    // ⇒ `scrollHeight` **恒 ≥ 纸高**（装得下也报 128mm，实测还会因取整变成 128.1mm ⇒ 5 行明细
    // 被误判「超出 0.1mm」）。做法：临时摘掉固定高度与裁切 → 量 → **同一帧内**还原
    // （浏览器不会在 JS 执行中间绘制，屏幕上看不到这一下）。
    const savedHeight = sheet.style.height
    const savedOverflow = sheet.style.overflow
    sheet.style.height = 'auto'
    sheet.style.overflow = 'visible'
    const contentPx = sheet.scrollHeight > 0 ? sheet.scrollHeight : sheet.offsetHeight
    sheet.style.height = savedHeight
    sheet.style.overflow = savedOverflow
    if (contentPx > limitPx) overflowSheets.push(index + 1)
    maxContentPx = Math.max(maxContentPx, contentPx)
  })
  const contentMm = round1(maxContentPx / PX_PER_MM)
  const overflowMm = round1(contentMm - limitMm)
  return {
    contentMm,
    limitMm,
    overflowMm,
    pages: Math.max(1, Math.ceil(contentMm / limitMm)),
    sheets: sheets.length,
    overflowSheets,
  }
}

export interface PrintDocPreviewProps {
  /** 当前预览的单据；`null` ⇒ 本层不渲染（调用方据此条件挂载，避免多挂一份单据） */
  target: PrintTarget | null
  title: string
  media: PrintMediaId
  /** 该单据（**同一个组件**，且**不传 `printTarget`** —— 预览实例永远不上纸） */
  children: ReactNode
  /** 点「打印」（由调用方经 `usePrintDoc().requestPrint` 走唯一入口） */
  onPrint: () => void
  onClose: () => void
  /**
   * 单据级的**打印前提示槽**（issue #6867 / B5）：纸面自检答不了的问题放这里 —— 例如
   * 「这张加工单还没有可扫二维码，现在打出来的纸扫不了」+ 一键补码。
   *
   * 🔴 为什么**不**放进纸框（`children`）：纸框量的是**纸面要印的内容**（`measureSheets`），
   * 往里加一行提示会被当成正文 ⇒ 报「超出 mm、直接打印会被裁掉」那句**假**结论；
   * 而提示本身又不该印到纸上（它是屏幕态的操作入口）。放页脚 ⇒ 纸面读数与纸面元素都不受影响。
   */
  notice?: ReactNode
  /**
   * 单据级的**附加动作**（issue #7288）：某张单据除了系统打印之外还有第二条通道时放这里 ——
   * 洗水唛的「蓝牙无线打印」（免驱动 Web Bluetooth）就挂在这个槽里。
   *
   * 🔴 位置 = 页脚动作行、**「复制截图」之前**（右下角）；不传 ⇒ 页脚与改前逐字一致，
   * 其它单据（销售单 / 发货单 / 报价单）不受影响。
   */
  actions?: ReactNode
  /**
   * 本页可打印的单据与**展示顺序**（issue #7544）—— 给了它就长出一排「单据标签」，
   * 商家在**同一个层里**换单据看，而不是先在页面上找对应的那个按钮。
   *
   * 不传 ⇒ 本层与改前逐字一致（发货页 / 加工单生产页各只有一份单据，不需要选择器）。
   */
  docs?: readonly PrintTarget[]
  /** 换单据（配合 `docs`）：调用方应当只切预览目标、**不置位打印目标**（`usePrintDoc().selectPreview`） */
  onSelect?: (target: PrintTarget) => void
  /**
   * 单据标签的**显示名**（issue #7891）：同一个打印目标在不同订单下可能叫不同的纸 ——
   * 作业单两型里「加工单」（成品帘）/「面料单」（只裁剪的面料单）是**同一份 A4 纸**，
   * 标题由 `printTargetTitle(target, kind)` 给（缺省仍读 `PRINT_TARGET_SPECS`）。
   *
   * 不传 ⇒ 标签与改前逐字一致（行为零变化）。
   */
  titleOf?: (target: PrintTarget) => string
  /**
   * **联合打印**（issue #7902）：勾选多份单据 → 一张一张出纸。
   *
   * 状态机在 `lib/print-doc.ts` 的 `usePrintBatch`（本组件只管界面）；「真正开印」仍由
   * `usePrintDoc` 的唯一入口负责 —— 本层不出现第二处 `window.print()`。
   *
   * 不传 ⇒ 页脚与改前逐字一致（其它使用方零影响）。
   */
  batch?: PrintBatchController
  /**
   * 联合打印面板里每份单据的**张数**（issue #7941：只报数，不再由调用方拼「3 张」这种展示串）——
   * 水洗唛 = 部位数，其它纸 = 1；算不出来就不传（不编数字）。
   *
   * 🔴 为什么是 `number` 而不是字符串：面板要**汇总**（「已选 2 份 · 5 张纸」），
   * 而展示串无法求和 —— 汇总只能在**数字**上做，展示格式由面板一处决定。
   */
  sheetsOf?: (target: PrintTarget) => number
  /** 点「打印这一张」（联合打印进行中）—— 调用方负责置位打印目标 + 写打印流水 */
  onBatchPrintCurrent?: () => void
}

export default function PrintDocPreview({
  target,
  title,
  media,
  children,
  onPrint,
  onClose,
  notice,
  actions,
  docs,
  onSelect,
  titleOf,
  batch,
  sheetsOf,
  onBatchPrintCurrent,
}: PrintDocPreviewProps) {
  // 纸的**整幅尺寸**取自介质矩阵（issue #7816：洗水唛改回固定 50×150，不再有「按内容撑开」的长度）
  const box = printPageBoxMm(media)
  // 纸框的**版面内缩**（不是 `@page` 边距：A4 的 `@page` 边距是 0、内缩在单据容器 padding 上，issue #7309）
  const margin = printContentInsetMm(media)
  const usable = { widthMm: box.widthMm - margin.xMm * 2, heightMm: box.heightMm - margin.yMm * 2 }
  const stageRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  const [check, setCheck] = useState<SheetCheckResult | null>(null)
  const [capturing, setCapturing] = useState(false)
  // 本机登记的打印机名（按纸型记；换纸型跟着换。issue #7957）
  const [printerName, setPrinterName] = useState<string | null>(() => readPrinterName(media))
  const [printerEditing, setPrinterEditing] = useState(false)
  const [printerDraft, setPrinterDraft] = useState('')

  // 切换纸型 ⇒ 换成该纸型的登记（A4 的名字不能出现在连续纸的提示里）
  useEffect(() => {
    setPrinterName(readPrinterName(media))
    setPrinterEditing(false)
  }, [media])

  // 缩放：只做「适配屏幕」，不改纸的真尺寸（纸框本身始终是 mm 单位）
  useEffect(() => {
    if (!target) return
    const available = Math.min(window.innerWidth * 0.82, 1080)
    setScale(Math.min(1, available / (box.widthMm * PX_PER_MM)))
  }, [target, box.widthMm])

  // 纸面自检：渲染完量一次（预览实例是屏幕态的同一份 DOM，所以量出来的就是纸面要印的东西）。
  // 🔴 **必须重试到量到为止**：单据组件在 `useEffect(() => setMounted(true))` 之后才渲染出内容
  // （真浏览器实测：首帧量不到 `data-print-sheet` ⇒ 自检永远停在「正在量纸面…」）。
  // 上限 20 次 × 50ms = 1s：超过就**如实**停在「正在量纸面…」，不编一个读数出来。
  useEffect(() => {
    if (!target) {
      setCheck(null)
      return
    }
    const stage = stageRef.current
    if (!stage) return
    let cancelled = false
    let timer = 0
    let tries = 0
    const tick = () => {
      if (cancelled) return
      const result = measureSheets(stage, usable.heightMm)
      tries += 1
      if (result !== null || tries >= 20) {
        setCheck(result)
        return
      }
      timer = window.setTimeout(tick, 50)
    }
    timer = window.setTimeout(tick, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [target, media, children, usable.heightMm])

  if (!target) return null

  // 面板读数的两处派生（数字只在这里算一次：全选与否、总张数）
  const selecting = batch?.stage === 'panel'
  const allSelected = !!batch && batch.candidates.length > 0 && batch.selected.length === batch.candidates.length
  const totalSheets = batch
    ? batch.selected.reduce((sum, doc) => sum + Math.max(1, sheetsOf?.(doc) ?? 1), 0)
    : 0

  const paperWidthPx = box.widthMm * PX_PER_MM * scale
  const paperHeightPx = box.heightMm * PX_PER_MM * scale

  async function handleCapture() {
    const stage = stageRef.current
    const paper = stage?.querySelector<HTMLElement>('[data-print-paper]')
    if (!paper) return
    setCapturing(true)
    try {
      const { blob, skippedImages } = await captureNodeToPngBlob(paper)
      const copied = await copyPngToClipboard(blob)
      const note =
        skippedImages > 0 ? `（${skippedImages} 张图片未取到，截图里可能缺失）` : ''
      if (copied) {
        toast.success(`已复制${title}截图到剪贴板${note}`)
      } else {
        downloadPng(blob, `${title}-${Date.now()}.png`)
        toast.warning(`浏览器不允许写剪贴板，已改为下载 PNG${note}`)
      }
    } catch (error) {
      // 2026-10-17：并入共享原语（UI-112 的形态面判据）—— 本地错误仍用它的 message，
      // 传输层错误（axios）的 `Request failed with status code NNN` 不再当失败原因上屏。
      toast.error(extractApiErrorMessage(error, '截图失败'))
    } finally {
      setCapturing(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/60 p-4"
      data-testid="print-preview"
      role="dialog"
      aria-label={`${title}打印预览`}
    >
      <style>{`
        /* 🔴 预览实例的显形规则「只在屏幕上」生效：打印媒体下它必须保持 display:none，
           否则同一份单据会同时以「真单据 + 预览副本」两张上纸。
           单据容器（*-print-area）是 .print-preview-doc 的「直接子级」（预览实例 inline 渲染、
           不 portal），故按子级选择器覆盖它的屏幕态 display:none。 */
        @media screen {
          .print-preview-doc > * {
            display: block !important;
            position: static !important;
            width: 100% !important;
          }
        }
      `}</style>

      <div className="flex max-h-full w-full max-w-5xl flex-col rounded-lg bg-white shadow-xl">
        {/* ① 表头：单据名 + 本次纸型（非标纸型必须明写 mm，驱动里没登记时用户才知道要配） */}
        <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
          <div className="min-w-0">
            <div className="text-base font-semibold text-neutral-900">{title} · 打印预览</div>
            <div className="text-xs text-neutral-500" data-testid="print-preview-media">
              纸型 {box.widthMm}mm × {box.heightMm}mm（可用 {usable.widthMm}mm × {usable.heightMm}mm
              {margin.xMm > 0 || margin.yMm > 0
                ? ` · 页边距 ${margin.yMm}mm ${margin.xMm}mm`
                : ' · 无边距'}
              ）· 正文 {printBodyFontPt(media)}pt
            </div>
            <div
              className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-500"
              data-testid="print-printer-hint"
            >
              <span>
                {printerName ? `打印机：${printerName}` : `打印机：${printerKindOf(media)}`}
                {!printerName && <span className="text-neutral-400">（未登记本机名称）</span>}
              </span>
              {!printerEditing ? (
                <button
                  type="button"
                  onClick={() => {
                    setPrinterDraft(printerName ?? '')
                    setPrinterEditing(true)
                  }}
                  data-testid="print-printer-edit"
                  className="rounded px-1 text-neutral-600 underline decoration-neutral-300 underline-offset-2 transition-colors hover:text-neutral-900"
                >
                  {printerName ? '更改' : '登记本机名称'}
                </button>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <input
                    autoFocus
                    value={printerDraft}
                    onChange={(e) => setPrinterDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.currentTarget.blur()
                    }}
                    placeholder="例：HP LaserJet M404"
                    data-testid="print-printer-input"
                    className="h-7 w-44 rounded-md border border-neutral-300 bg-white px-2 text-xs text-neutral-900 outline-none focus:border-primary-400"
                  />
                  <button
                    type="button"
                    data-testid="print-printer-save"
                    onClick={() => {
                      savePrinterName(media, printerDraft)
                      setPrinterName(readPrinterName(media))
                      setPrinterEditing(false)
                    }}
                    className="rounded px-1 font-medium text-primary-700 hover:text-primary-800"
                  >
                    保存
                  </button>
                  <button
                    type="button"
                    data-testid="print-printer-cancel"
                    onClick={() => setPrinterEditing(false)}
                    className="rounded px-1 text-neutral-500 hover:text-neutral-800"
                  >
                    取消
                  </button>
                </span>
              )}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} data-testid="print-preview-close">
            关闭
          </Button>
        </div>

        {/* ② 单据标签（issue #7544）＝ 同页多份单据时**唯一**的换单据入口；
            联合打印面板打开时（issue #7949，用户 2026-10-27「横着放置一行」「点击联合打印后顶部出现多选框进行勾选」）
            **同一行**切换成多选 chip —— 不另起一张竖排列表（竖排 4 行会把纸面预览挤掉一截）。
            点击 = 勾选这份纸 + 顺带把它切到预览（勾选与「看哪张」是同一次点击的两个结果）。 */}
        {docs && docs.length > 1 && onSelect && (
          <div
            className="flex flex-wrap items-center gap-2 border-b border-neutral-200 px-4 py-2"
            role="group"
            aria-label={selecting ? '勾选这次要出的纸' : '选择单据'}
            data-testid="print-preview-docs"
          >
            {docs.map((doc, i) => {
              const spec = PRINT_TARGET_SPECS[doc]
              const active = doc === target
              const docBox = printPageBoxMm(spec.media)
              const label = titleOf ? titleOf(doc) : spec.title
              const sheets = Math.max(1, sheetsOf?.(doc) ?? 1)
              const checked = !!batch && batch.selected.includes(doc)
              return (
                <button
                  key={doc}
                  type="button"
                  // 面板态 = 多选框语义；常态 = 单选（换单据看）
                  role={selecting ? 'checkbox' : undefined}
                  aria-checked={selecting ? checked : undefined}
                  aria-pressed={selecting ? undefined : active}
                  data-testid={selecting ? `print-batch-doc-${doc}` : `print-preview-doc-${doc}`}
                  onClick={() => {
                    if (selecting && batch) batch.toggle(doc)
                    onSelect(doc)
                  }}
                  className={`inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg border px-3 text-sm transition-colors ${
                    selecting
                      ? checked
                        ? 'border-primary-200 bg-primary-50/60 font-medium text-neutral-900'
                        : 'border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300 hover:bg-neutral-50'
                      : active
                        ? 'border-primary-500 bg-primary-50 font-medium text-primary-700'
                        : 'border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-50'
                  }`}
                >
                  {selecting && (
                    <span
                      aria-hidden="true"
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                        checked
                          ? 'border-primary-500 bg-primary-500 text-white'
                          : 'border-neutral-300 bg-white text-transparent'
                      }`}
                    >
                      <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" aria-hidden="true">
                        <path
                          d="M2.5 6.5 5 9l4.5-5.5"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </span>
                  )}
                  {/* 序号 = 真实出纸顺序（用户 2026-10-27「数字仍然展示」）—— 弱化成行内小字，
                      不占独立列宽；左→右读序与序号同向，两者互为校验 */}
                  {selecting && (
                    <span className="text-xs tabular-nums text-neutral-400">{i + 1}</span>
                  )}
                  {label}
                  {/* 纸型**从介质矩阵取**（不是标签自带的第二份字面量）—— 换纸后这里跟着变 */}
                  <span className={`text-xs font-normal ${selecting && checked ? 'text-neutral-500' : 'text-neutral-400'}`}>
                    {docBox.widthMm}×{docBox.heightMm}mm
                  </span>
                  {selecting && (
                    <span className="text-xs tabular-nums text-neutral-500">{sheets} 张</span>
                  )}
                  {active && (
                    <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-500">当前</span>
                  )}
                </button>
              )
            })}
          </div>
        )}

        {/* ②b 联合打印的**唯一**常驻面（issue #7949）：一行 = 标题/说明 + 已选读数 + 三个动作。
            勾选项在上一行（与单据标签同一行），故本面板只有**一行**高度（改前是 4 行列表 + 页脚 ≈ 6 行）。 */}
        {batch && batch.stage === 'panel' && (
          <div
            className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-neutral-200 bg-neutral-50 px-4 py-2"
            data-testid="print-batch-panel"
            aria-label="联合打印"
          >
            <span className="text-sm font-medium text-neutral-900">联合打印</span>
            <span className="hidden text-xs text-neutral-500 sm:inline">按顺序逐张出纸，每张记一条打印流水</span>
            <span className="ml-auto text-xs tabular-nums text-neutral-500" data-testid="print-batch-summary">
              已选 {batch.selected.length} 份 · {totalSheets} 张纸
            </span>
            {/* 辅助动作降为文字按钮（§32.2 层级） */}
            <button
              type="button"
              onClick={batch.toggleAll}
              aria-pressed={allSelected}
              data-testid="print-batch-toggle-all"
              className="rounded-md px-2 py-1 text-xs font-medium text-neutral-600 transition-colors hover:bg-white hover:text-neutral-900"
            >
              {allSelected ? '取消全选' : '全选'}
            </button>
            <Button variant="ghost" size="sm" onClick={batch.closePanel} data-testid="print-batch-cancel">
              取消
            </Button>
            <Button size="sm" onClick={batch.start} disabled={batch.selected.length === 0} data-testid="print-batch-start">
              开始联合打印
            </Button>
          </div>
        )}

        {/* ③ 真尺寸纸框（按 mm），外层只做缩放适配 */}
        <div className="flex-1 overflow-auto bg-neutral-100 p-4">
          <div
            className="print-preview-stage mx-auto"
            ref={stageRef}
            style={{ width: `${paperWidthPx}px`, height: `${paperHeightPx}px` }}
          >
            <div
              data-print-paper
              data-testid="print-preview-paper"
              className="origin-top-left bg-white shadow ring-1 ring-neutral-300"
              style={{
                width: `${box.widthMm}mm`,
                minHeight: `${box.heightMm}mm`,
                padding: `${margin.yMm}mm ${margin.xMm}mm`,
                transform: `scale(${scale})`,
                fontSize: `${printBodyFontPt(media)}pt`,
              }}
            >
              {/* 🔴 预览实例不传 printTarget ⇒ 不带 data-print-target ⇒ 打印媒体下不上纸 */}
              <div className="print-preview-doc">{children}</div>
            </div>
          </div>
        </div>

        {/* ④ 自检结论 + 出口 */}
        <div className="border-t border-neutral-200 px-4 py-3">
          {/* 单据级提示槽（issue #6867）：在出口**之前**、纸框**之外** —— 商家先看见「这张纸扫不了」，
              再决定是打还是先补码（放进纸框会污染纸面自检读数，见 `notice` 的 props 注释）。 */}
          {notice && <div className="mb-2">{notice}</div>}
          {/* 联合打印进度（issue #7902）：**哪一张、第几张、出没出纸**在同一行说完 ——
              商家按这张纸的纸型换纸/换驱动，屏幕要一直告诉他现在在打哪一份。 */}
          {batch?.stage === 'running' && (
            <div className="mb-2 flex flex-wrap items-center gap-2" data-testid="print-batch-progress">
              <span className="inline-flex items-center rounded-full bg-primary-50 px-2.5 py-0.5 text-xs font-semibold text-primary-700">
                联合打印 {batch.index + 1}/{batch.selected.length}
              </span>
              <span className="text-sm font-medium text-neutral-900">
                {batch.current ? (titleOf ? titleOf(batch.current) : PRINT_TARGET_SPECS[batch.current].title) : ''}
              </span>
              <span className="text-xs tabular-nums text-neutral-500">
                {box.widthMm}×{box.heightMm}mm
              </span>
              <span className="text-xs text-neutral-500" data-testid="print-batch-printer">
                {printerName ? `打印机：${printerName}` : `请选：${printerKindOf(media)}`}
              </span>
              <span className="text-xs text-neutral-500">{batch.fired ? '已出纸' : '待出纸'}</span>
            </div>
          )}
          <div className="mb-2 text-sm" data-testid="print-preview-check">
            {check === null ? (
              <span className="text-neutral-500">正在量纸面…</span>
            ) : check.overflowMm > 0 ? (
              <span className="text-amber-700">
                内容 {check.contentMm}mm &gt; 可用 {check.limitMm}mm，超出 {check.overflowMm}mm
                {check.overflowSheets.length > 0
                  ? `（第 ${check.overflowSheets.join('、')} 张）`
                  : ''}
                —— 直接打印会被裁掉（纸面从底部丢内容）；请拆单，或改用其它介质再打。
              </span>
            ) : (
              <span className="text-neutral-600">
                内容 {check.contentMm}mm ≤ 可用 {check.limitMm}mm，装得下
                {check.sheets > 1 ? `（共 ${check.sheets} 张）` : ''}
                {check.limitMm > 0 && check.contentMm / check.limitMm > 0.5 && check.sheets === 1
                  ? `，预计 ${check.pages} 页`
                  : ''}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2" data-testid="print-preview-actions">
            {actions}
            <Button variant="secondary" onClick={handleCapture} loading={capturing} data-testid="print-preview-capture">
              复制截图
            </Button>
            {batch && batch.stage === 'idle' && batch.candidates.length > 1 && (
              <Button variant="secondary" onClick={() => batch.openPanel(target ?? undefined)} data-testid="print-batch-entry">
                联合打印
              </Button>
            )}
            {batch?.stage === 'running' ? (
              <>
                <Button variant="secondary" onClick={batch.stop} data-testid="print-batch-stop">
                  结束
                </Button>
                {batch.fired ? (
                  <Button onClick={batch.next} data-testid="print-batch-next">
                    {batch.index + 1 >= batch.selected.length ? '完成' : '下一张'}
                  </Button>
                ) : (
                  <Button onClick={() => onBatchPrintCurrent?.()} data-testid="print-preview-print">
                    打印这一张
                  </Button>
                )}
              </>
            ) : (
              <Button onClick={onPrint} data-testid="print-preview-print">
                打印
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
