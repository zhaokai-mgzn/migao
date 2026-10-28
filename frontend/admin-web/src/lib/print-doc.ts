'use client'

import { useCallback, useEffect, useState } from 'react'
import { peekPaymentQrcodes } from './use-payment-qrcodes'
import { printPageBoxMm, type PrintMediaId } from './print-media'
// 纸面标题按**作业单两型**给名（issue #7891）：真值在 `processing-order.ts`（只 import 类型 ⇒ 无循环）
import { workOrderDocTitleOf, type WorkOrderKind } from './processing-order'

/**
 * 打印前的异步素材等待（issue #7536）—— 目前唯一的异步素材是收款码。
 *
 * 🔴 **不等就出纸的形态**：`beforeprint` 派发完当帧快照 ⇒ 异步取回的码来不及进 DOM
 * ⇒ 「第一次打印没有收款码、第二次才有」（实测读数见 `use-payment-qrcodes.ts` 口径 3）。
 *
 * 只等**已经在取**的那一份（`peekPaymentQrcodes()`）：没人要码的页面（洗水唛 / 发货单 / 销售单 ——
 * 销售单自 issue #7589 起不印收款码）
 * 不会因此多发一次请求 —— 而那条请求要 `order:list`，在别的页面上会变成 403 提示。
 * 上限 2.5s：请求卡住时**宁可出纸**也不让「打印」按钮变成没反应的死键。
 */
export const PRINT_ASSET_WAIT_MS = 2500

async function waitForPendingPrintAssets(): Promise<void> {
  const pending = peekPaymentQrcodes()
  if (!pending) return
  await Promise.race([
    pending.catch(() => undefined),
    new Promise((resolve) => setTimeout(resolve, PRINT_ASSET_WAIT_MS)),
  ])
}

/** 让出一帧（两次 rAF：一次等 React 提交，一次等浏览器布局）；无 rAF 的环境退化为 setTimeout */
function afterNextPaint(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame !== 'function') {
      setTimeout(resolve, 0)
      return
    }
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  })
}

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
export const PRINT_TARGETS = ['quotation', 'sales', 'processing', 'labels'] as const

export type PrintTarget = (typeof PRINT_TARGETS)[number]

/**
 * 每个目标位的**展示元数据**（预览层的标题 + 该单据印在什么纸上）。
 * 🔴 纸型只在这里指到介质 id —— 尺寸/边距/字号一律由介质矩阵给（`lib/print-media.json`），
 * 本表**不是**第二份纸型真值。
 */
export const PRINT_TARGET_SPECS: Record<PrintTarget, { title: string; media: PrintMediaId }> = {
  quotation: { title: '报价单', media: 'a4' },
  processing: { title: '加工单', media: 'a4' },
  sales: { title: '销售单', media: 'continuous-241x140' },
  labels: { title: '水洗唛', media: 'label-50x140' },
}

/**
 * 预览 / 纸面标题（issue #7891）：`processing` 目标按**作业单两型**给名 ——
 * 成品帘 ⇒「加工单」、面料单 ⇒「面料单」（真值 = {@link workOrderDocTitleOf}，
 * 用户 2026-10-27 逐字「面料单就叫面料单，不要叫裁剪单」）；其它目标位原样回 {@link PRINT_TARGET_SPECS}。
 *
 * 为什么不把它写进 `PRINT_TARGET_SPECS`：那张表是**目标位**的名字（一份单据一个位，屏上到处在引用），
 * 而「加工单 / 面料单」是**同一份纸**按这单的业务类型给的**纸面名** —— 写进 specs 等于说
 * 「加工单这个位置有两种名字」，屏上的单据标签就会随单漂移。
 * ⚠️ 已知边界：预览层的**单据标签行**（`PrintDocPreview` 内部）仍读 `PRINT_TARGET_SPECS`，
 * 本 helper 只管**标题 / 纸面名**。
 */
export function printTargetTitle(target: PrintTarget, kind?: WorkOrderKind): string {
  return target === 'processing' ? workOrderDocTitleOf(kind) : PRINT_TARGET_SPECS[target].title
}

/**
 * 单据类型 → 屏上中文名（打印流水 / 列表汇总用）。
 *
 * 🔴 流水里的 `doc_title` 是**打印当时的快照**（「加工单」还是「面料单」由当时的作业单两型决定），
 * 所以展示优先用快照；只有快照缺值（存量行 / 早期记录）才回落到本函数 —— **不覆写历史**。
 */
export function printDocTypeLabel(docType: string): string {
  const spec = PRINT_TARGET_SPECS[docType as PrintTarget]
  return spec ? spec.title : docType
}

/** 介质 id → 纸面尺寸文案（登录流水里「打歪了」第一眼看的就是它）；查不到 ⇒ 原样回 id */
export function printMediaLabel(mediaId: string | null | undefined): string {
  if (!mediaId) return '—'
  try {
    const box = printPageBoxMm(mediaId as PrintMediaId)
    return `${box.widthMm}×${box.heightMm}mm`
  } catch {
    // 介质矩阵里没有这个 id（历史行 / 未来新增）⇒ 原样显示 id，**不编一个尺寸**
    return mediaId
  }
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
  /**
   * **只换预览的单据**（issue #7544）—— 打印中心里的单据标签用它。
   *
   * 🔴 与 `openPreview` 的差别就一格：**不动 `printTarget`**。换单据是「看一眼另一份」，
   * 不是「这次就印它」；混用会让「打印前 Ctrl+P」打出用户没选的那一份（纸是耗材）。
   */
  selectPreview: (target: PrintTarget) => void
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

  /**
   * 缺省目标**跟着数据变**（issue #7891）：加工单生产页的缺省纸是「洗水唛」，但面料单
   * （`order_kind='outbound'`）**没有**洗水唛、只有那份 A4「面料单」—— 而作业单读面是异步回来的
   * ⇒ 首帧 `singleDocTarget` 还是 `'labels'`，之后再没人改它 ⇒ 面料单页直接 Ctrl+P **一张纸都不出**。
   *
   * 只在「还没打印过」时跟随（`printNonce === 0`）：一旦用户/页面指定了这次要印哪一份，
   * 后续的数据变化**不得**改掉他的选择（纸是耗材；打印前换目标 = 打错纸）。
   */
  useEffect(() => {
    if (printNonce !== 0) return
    if (singleDocTarget) setPrintTarget(singleDocTarget)
  }, [singleDocTarget, printNonce])

  // 🔴 打印发生在**提交之后**：本 effect 跑的时候，目标单据的 `data-print-target` 已经进 DOM。
  // 不许把 `window.print()` 挪回点击处理器里 —— 那正是 #5914 的「首次打印空白纸」。
  useEffect(() => {
    if (printNonce === 0) return
    // 没有异步素材在飞（发货单 / 洗水唛 / 没人要收款码的页面）⇒ **同步开印**，
    // 与 #5914 的行为一字不差（也保住既有判据的「同一段同步代码」读数）。
    if (!peekPaymentQrcodes()) {
      window.print()
      return
    }
    let cancelled = false
    void (async () => {
      // 🔴 纸面上的**异步素材**必须先到（issue #7536）：收款码是取回来的，而浏览器在
      // `beforeprint` 派发完**当帧**就对 DOM 做纸面快照 ⇒ 不等它，第一次打印的纸上没有码
      //（实测：当帧 img 数 0，1.5s 后才是 1）。
      await waitForPendingPrintAssets()
      // 再让一帧：等 React 把取回来的码提交进 DOM（提交发生在 Promise 回调之后）
      await afterNextPaint()
      if (!cancelled) window.print()
    })()
    return () => {
      cancelled = true
    }
  }, [printNonce])

  const requestPrint = useCallback((target: PrintTarget) => {
    setPrintTarget(target)
    setPrintNonce((nonce) => nonce + 1)
  }, [])

  const openPreview = useCallback((target: PrintTarget) => {
    setPrintTarget(target)
    setPreviewTarget(target)
  }, [])

  const selectPreview = useCallback((target: PrintTarget) => setPreviewTarget(target), [])

  const closePreview = useCallback(() => setPreviewTarget(null), [])

  return { printTarget, previewTarget, requestPrint, openPreview, selectPreview, closePreview }
}

/* ============================================================================
 * 联合打印（issue #7902）—— 一次操作打多份纸，但**一张一张出**
 * ==========================================================================*/

/** 一次联合打印的批次号（写打印流水用；`crypto.randomUUID` 不可用 ⇒ 时间戳兜底，判据只要求非空且同批相同） */
export function newPrintBatchId(): string {
  const c = typeof crypto !== 'undefined' ? crypto : undefined
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  return `batch-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

export interface PrintBatchController {
  /** `idle` = 不在联合打印里；`panel` = 勾选面板打开；`running` = 逐张引导中 */
  stage: 'idle' | 'panel' | 'running'
  /** 本次**可**联合打印的单据（页面按派单/权限给；顺序 = 出纸顺序） */
  candidates: readonly PrintTarget[]
  /** 已勾选的单据（顺序 = 出纸顺序） */
  selected: PrintTarget[]
  /** 逐张引导：当前第几张（0-based） */
  index: number
  /** 当前这一张是否已经出过纸（出纸后主按钮变「下一张」） */
  fired: boolean
  /** 本次联合打印的批次号（未开始 ⇒ `null`；写打印流水用） */
  batchId: string | null
  /** 逐张引导时当前这份纸；`null` ⇒ 没在引导 */
  current: PrintTarget | null
  /** 打开勾选面板；`preferred` = 当前正在看的那一份（默认勾它，缺省勾第一份） */
  openPanel: (preferred?: PrintTarget) => void
  closePanel: () => void
  toggle: (target: PrintTarget) => void
  /** 全选 / 全不选（当前全选 ⇒ 清空） */
  toggleAll: () => void
  start: () => void
  /** 出纸后立刻记一笔（**不改阶段**，主按钮仍停在「下一张」） */
  markFired: () => void
  /** 前进到下一张；最后一张 ⇒ 直接收尾 */
  next: () => void
  stop: () => void
}

/**
 * 联合打印的状态机（**只做状态**，不碰 `window.print()` —— 开印仍由 `usePrintDoc` 的唯一入口负责）。
 *
 * ## 为什么是「逐张引导」而不是「连打 N 张」
 *
 * ① 浏览器**不保证** `window.print()` 会阻塞到出纸完成（`afterprint` 的时机在各驱动上不同），
 *    自动连打会在真机上变成「点了没反应」或「一次弹 N 个对话框」；
 * ② 四份单据的纸型不同（241×140 三联纸 / A4 / 50×150 标签）——**每份都要换纸/换驱动设置**，
 *    物理上就必须一张一张来；
 * ③ 商家要能中途停（少打一张标签纸 = 少浪费一张耗材）。
 * ⇒ 主按钮 = 「打印这一张」，出纸后变「下一张」，进度与顺序在屏上一直可见。
 *
 * @param candidates 本次可联合打印的单据（页面给；顺序 = 出纸顺序）。集合变小（如作业单被取消）时，
 *   已勾选但不再可打印的项会被**静默剔除** —— 宁可少打一张，也不打一张数据已经没有的纸。
 */
export function usePrintBatch(candidates: readonly PrintTarget[]): PrintBatchController {
  const [stage, setStage] = useState<'idle' | 'panel' | 'running'>('idle')
  const [selected, setSelected] = useState<PrintTarget[]>([])
  const [index, setIndex] = useState(0)
  const [fired, setFired] = useState(false)
  const [batchId, setBatchId] = useState<string | null>(null)

  // 候选集合收缩 ⇒ 同步剔除（勾选状态是「这一次要打什么」的意图，不是账本）
  useEffect(() => {
    setSelected((prev) => {
      const next = prev.filter((t) => candidates.includes(t))
      return next.length === prev.length ? prev : next
    })
  }, [candidates])

  const openPanel = useCallback((preferred?: PrintTarget) => {
    setStage('panel')
    // 面板打开时默认**只勾当前正在看的那一份**：联合打印是显式动作，不默认把纸全打一遍（纸是耗材）；
    // 已有勾选则保持（用户在面板里调整到一半关掉再打开，不该被重置）
    setSelected((prev) =>
      prev.length > 0
        ? prev
        : [preferred && candidates.includes(preferred) ? preferred : candidates[0]].filter(
            Boolean,
          ) as PrintTarget[],
    )
  }, [candidates])

  const closePanel = useCallback(() => setStage('idle'), [])

  const toggle = useCallback((target: PrintTarget) => {
    setSelected((prev) =>
      prev.includes(target) ? prev.filter((t) => t !== target) : [...prev, target],
    )
  }, [])

  const toggleAll = useCallback(() => {
    setSelected((prev) => (prev.length === candidates.length ? [] : [...candidates]))
  }, [candidates])

  const start = useCallback(() => {
    if (selected.length === 0) return
    // 顺序 = 候选顺序（业务流水序：报价单 → 销售单 → 加工单 → 水洗唛），不按点击顺序
    const ordered = candidates.filter((t) => selected.includes(t))
    setSelected(ordered)
    setIndex(0)
    setFired(false)
    setBatchId(newPrintBatchId())
    setStage('running')
  }, [candidates, selected])

  const markFired = useCallback(() => setFired(true), [])

  const stop = useCallback(() => {
    setStage('idle')
    setIndex(0)
    setFired(false)
    setBatchId(null)
  }, [])

  const next = useCallback(() => {
    setIndex((prev) => {
      if (prev + 1 >= selected.length) {
        // 最后一张 ⇒ 收尾（用微任务避免在渲染期改多个 state 的交错分支）
        setStage('idle')
        setFired(false)
        setBatchId(null)
        return 0
      }
      setFired(false)
      return prev + 1
    })
  }, [selected.length])

  return {
    stage,
    candidates,
    selected,
    index,
    fired,
    batchId,
    current: stage === 'running' ? (selected[index] ?? null) : null,
    openPanel,
    closePanel,
    toggle,
    toggleAll,
    start,
    markFired,
    next,
    stop,
  }
}
