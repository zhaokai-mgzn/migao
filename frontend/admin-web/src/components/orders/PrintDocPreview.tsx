'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui'
import {
  printBodyFontPt,
  printPageBoxMm,
  printPageMarginMm,
  printUsableBoxMm,
  type PrintMediaId,
} from '@/lib/print-media'
import { captureNodeToPngBlob, copyPngToClipboard, downloadPng } from '@/lib/print-capture'
import type { PrintTarget } from '@/lib/print-doc'

/**
 * 打印前的**纸面自检层**（issue #5914 的功能③）—— 真尺寸纸框 + 溢出/页数自检 + 纸型提示。
 *
 * ## 为什么不是「通用预览器」
 *
 * 浏览器自带的打印预览已经能看版面，它答不了的是这三件（issue #5914 实证）：
 * ① 内容**超出这一联/这一页被裁**（销售单单联 128mm，>6 行明细即被 `overflow:hidden` 静默裁掉，
 *    裁掉的恰好是「本单应收 / 账户余额 / 收款码」）；
 * ② **非标纸型**（241×140 / 50×60）在驱动里没登记自定义纸型时的落差；
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
  /** 本单据由几张「纸」组成（洗水码 = 一部位一张） */
  sheets: number
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
  for (const sheet of sheets) {
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
    maxContentPx = Math.max(maxContentPx, contentPx)
  }
  const contentMm = round1(maxContentPx / PX_PER_MM)
  const overflowMm = round1(contentMm - limitMm)
  return {
    contentMm,
    limitMm,
    overflowMm,
    pages: Math.max(1, Math.ceil(contentMm / limitMm)),
    sheets: sheets.length,
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
}

export default function PrintDocPreview({
  target,
  title,
  media,
  children,
  onPrint,
  onClose,
}: PrintDocPreviewProps) {
  const box = printPageBoxMm(media)
  const margin = printPageMarginMm(media)
  const usable = printUsableBoxMm(media)
  const stageRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  const [check, setCheck] = useState<SheetCheckResult | null>(null)
  const [capturing, setCapturing] = useState(false)

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
      toast.error(error instanceof Error ? error.message : '截图失败')
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
          </div>
          <Button variant="secondary" size="sm" onClick={onClose} data-testid="print-preview-close">
            关闭
          </Button>
        </div>

        {/* ② 真尺寸纸框（按 mm），外层只做缩放适配 */}
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

        {/* ③ 自检结论 + 出口 */}
        <div className="border-t border-neutral-200 px-4 py-3">
          <div className="mb-2 text-sm" data-testid="print-preview-check">
            {check === null ? (
              <span className="text-neutral-500">正在量纸面…</span>
            ) : check.overflowMm > 0 ? (
              <span className="text-amber-700">
                内容 {check.contentMm}mm &gt; 可用 {check.limitMm}mm，超出 {check.overflowMm}mm
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
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="secondary" onClick={handleCapture} loading={capturing} data-testid="print-preview-capture">
              复制截图
            </Button>
            <Button onClick={onPrint} data-testid="print-preview-print">
              打印
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
