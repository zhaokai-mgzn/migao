'use client'

import { useCallback, useEffect, useState } from 'react'
import type { PrintMediaId } from './print-media'

/**
 * 打印 / 预览 / 截图的**唯一入口**（issue #5914）—— 一次只允许**一份**单据上纸。
 *
 * ## 为什么必须收敛成一处（实测，不是推断）
 *
 * `window.print()` 与 `setState(target)` 写在**同一个事件处理器**里时，print 触发的那一刻 DOM 里
 * **还没有** `data-print-target`（React 的提交发生在处理器返回之后）。真实 Chromium 读数：
 *
 * ```
 * at-call:TARGET_MISSING   beforeprint:TARGET_MISSING   after-call:TARGET_MISSING
 * ```
 *
 * ⇒ 目标单据拿不到 `visibility: visible` 防御，而页面上别处的
 * `@media print { body * { visibility: hidden } }` 照样生效 ⇒ **第一次点打印打出一张空白纸**
 * （第二次才对，因为那时 attribute 已提交）。
 *
 * 现在 `window.print()` 只在**提交之后**的 effect 里调用 ⇒ 时序不再依赖浏览器。
 * 同一条纪律还保证了「只放一份单据上纸」：各单据按 `printTarget` 决定自己是否 `display: block`
 * （见各 `*Doc.tsx` 的 `@media print` 块与 `docs/design/print-media-matrix.md`）。
 *
 * 守卫：`src/**` 里出现**第二处** `window.print()` ⇒ 红
 * （`tests/unit_ci_workflows/test_print_single_doc_on_paper.py`）。
 */

/** 可打印单据的**目标位**（= 页面上「这次要印哪一份」）。新增单据必须同时登记进本清单与介质矩阵。 */
export const PRINT_TARGETS = ['shipment', 'quotation', 'processing', 'sales', 'labels'] as const

export type PrintTarget = (typeof PRINT_TARGETS)[number]

/**
 * 每个目标位的**展示元数据**（预览层的标题 + 该单据印在什么纸上）。
 * 🔴 纸型只在这里指到介质 id —— 尺寸/边距/字号一律由介质矩阵给（`lib/print-media.json`），
 * 本表**不是**第二份纸型真值。
 */
export const PRINT_TARGET_SPECS: Record<PrintTarget, { title: string; media: PrintMediaId }> = {
  shipment: { title: '发货单', media: 'a4' },
  quotation: { title: '报价单', media: 'a4' },
  processing: { title: '加工单', media: 'a4' },
  sales: { title: '销售单', media: 'continuous-241x140' },
  labels: { title: '水洗唛', media: 'label-50x60' },
}

export interface PrintDocController {
  /** 本次打印目标（各单据据此决定「我上不上纸」）；`null` = 本次没有任何单据上纸 */
  printTarget: PrintTarget | null
  /** 预览层当前展示的单据；`null` = 预览层关闭 */
  previewTarget: PrintTarget | null
  /** 点「打印」：置位目标 → **提交之后**才开印 */
  requestPrint: (target: PrintTarget) => void
  /** 点「预览」：置位目标 + 打开纸面自检层 */
  openPreview: (target: PrintTarget) => void
  closePreview: () => void
}

/**
 * @param singleDocTarget 本页**只有一份**可打印单据时的缺省目标（发货页 = 发货单、加工单生产页 = 洗水码）。
 *   置了它，用户不点按钮直接 Ctrl+P 也打得出东西（与 #5914 之前的页面行为一致）；
 *   订单详情页**不传** —— 那里同页四份单据，缺省任何一份都会顶掉别人的纸型。
 */
export function usePrintDoc(singleDocTarget?: PrintTarget): PrintDocController {
  const [printTarget, setPrintTarget] = useState<PrintTarget | null>(singleDocTarget ?? null)
  const [previewTarget, setPreviewTarget] = useState<PrintTarget | null>(null)
  // 用**递增计数**而不是布尔：连点两次「打印」同一份单据时，effect 也必须再跑一次
  const [printNonce, setPrintNonce] = useState(0)

  // 🔴 打印发生在**提交之后**：本 effect 跑的时候，目标单据的 `data-print-target` 已经进 DOM。
  // 不许把 `window.print()` 挪回点击处理器里 —— 那正是 #5914 的「首次打印空白纸」。
  useEffect(() => {
    if (printNonce === 0) return
    window.print()
  }, [printNonce])

  const requestPrint = useCallback((target: PrintTarget) => {
    setPrintTarget(target)
    setPrintNonce((nonce) => nonce + 1)
  }, [])

  const openPreview = useCallback((target: PrintTarget) => {
    setPrintTarget(target)
    setPreviewTarget(target)
  }, [])

  const closePreview = useCallback(() => setPreviewTarget(null), [])

  return { printTarget, previewTarget, requestPrint, openPreview, closePreview }
}
