'use client'

import { useMemo, useRef, useState } from 'react'
import { QRCodeCanvas } from 'qrcode.react'
import { Bluetooth } from 'lucide-react'
import { Button } from '@/components/ui'
import {
  DIRECT_PRINT_READY_HINT,
  directPrintHint,
  probeDirectPrint,
  readLabelPrintEnv,
  type LabelPrintEnv,
} from '@/lib/label-print/capability'
import { LabelPrintError, type LabelPrinterProvider, type PrintJob } from '@/lib/label-print/lpapi'
import type { WashLabelInput } from '@/lib/label-print/wash-label'

/**
 * 「直连打印机」入口（issue #6439）—— **免驱动**把洗水码送到标签机（浏览器 Web Bluetooth）。
 *
 * ## 与浏览器打印的关系：**并存，不是替换**
 *
 * 「打印任务卡」（`window.print()` + `@page`）覆盖**任何装了驱动**的打印机
 * （Windows 驱动 / USB / 网络 / 已配对蓝牙）—— 那是**唯一**能覆盖任意品牌的路，**本单不动它**。
 * 本组件是「懒得装驱动」时的补充：只覆盖**带 SDK 协议**的机型。
 * ⇒ 两者互不干扰（本组件**不碰** `window.print`，由守卫
 * `tests/unit_ci_workflows/test_print_single_doc_on_paper.py` 钉住「`window.print` 只有一处」）。
 *
 * ## 可注入面（为什么留这两个口）
 *
 * - `loadProvider`：真实现要动态注入厂商 UMD bundle；测试传替身 ⇒ 单测不碰网络与蓝牙。
 * - `renderJobs`：真实现要真 canvas（本仓 jsdom 没装 `canvas` 包，跑不了）⇒ 测试传替身；
 *   版式与绘制本身另有纯函数判据（`tests/unit/lib/label-print-wash-label.test.ts`）。
 *
 * ## 留痕
 *
 * 与「打印任务卡」同口径：**先上报计数、失败不阻断**（`onRecordPrint` 由页面注入，
 * 内部 fire-and-forget）—— 换通道不换纪律。
 */
export interface DirectLabelPrintProps {
  /** 本次要打的洗水码（一部位一张；页面用 `toWashLabelInputs(positions)` 生成） */
  labels: WashLabelInput[]
  /** 打印留痕（fire-and-forget，失败不得阻断打印 —— 与浏览器打印那条路同口径） */
  onRecordPrint?: () => void
  /** 环境快照（缺省读真实浏览器环境；测试注入） */
  env?: LabelPrintEnv
  /** 通道加载（缺省注入厂商 UMD；测试注入替身） */
  loadProvider?: () => Promise<LabelPrinterProvider | null>
  /** 位图渲染（缺省真 canvas；测试注入替身） */
  renderJobs?: (
    labels: WashLabelInput[],
    qrSources: Array<CanvasImageSource | null>,
    printerInfo: Record<string, unknown> | null,
  ) => Promise<PrintJob[]>
  className?: string
}

type Phase = 'load' | 'connect' | 'render' | 'print'

/** 缺省通道：注入厂商 UMD → 造 LPAPI provider（**不引 npm 依赖**，见 `public/vendor/README.md`） */
async function defaultLoadProvider(): Promise<LabelPrinterProvider | null> {
  const { createLpapiProvider, loadLpapiApi } = await import('@/lib/label-print/lpapi')
  const api = await loadLpapiApi()
  return api ? createLpapiProvider(api) : null
}

/** 缺省渲染：真 canvas（一张一个 job） */
async function defaultRenderJobs(
  labels: WashLabelInput[],
  qrSources: Array<CanvasImageSource | null>,
  printerInfo: Record<string, unknown> | null,
): Promise<PrintJob[]> {
  const { renderWashLabelJobs } = await import('@/lib/label-print/render')
  return renderWashLabelJobs(labels, qrSources, printerInfo)
}

export default function DirectLabelPrint({
  labels,
  onRecordPrint,
  env,
  loadProvider,
  renderJobs,
  className,
}: DirectLabelPrintProps) {
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<{ kind: 'idle' | 'ok' | 'error'; text: string }>({
    kind: 'idle',
    text: '',
  })
  /** 已连接的通道（**缓存**：第二条起不再弹设备框，BLE 掉线时经失败分类清空以便重连） */
  const providerRef = useRef<LabelPrinterProvider | null>(null)
  /** 隐藏的二维码位图源（`QRCodeCanvas` 渲染出的真 canvas，`display:none` 不影响其位图内容） */
  const qrBoxRef = useRef<HTMLDivElement | null>(null)

  const capability = useMemo(() => probeDirectPrint(env ?? readLabelPrintEnv()), [env])
  const hasLabels = labels.length > 0

  /** 与 `labels` **同序**取二维码位图源：无码的位置给 `null`（不画假码） */
  const collectQrSources = (): Array<CanvasImageSource | null> => {
    const canvases = Array.from(qrBoxRef.current?.querySelectorAll('canvas') ?? [])
    let cursor = 0
    return labels.map((label) => (label.qrValue ? (canvases[cursor++] ?? null) : null))
  }

  const handlePrint = async () => {
    setBusy(true)
    setStatus({ kind: 'idle', text: '' })
    let phase: Phase = 'load'
    try {
      // ① 留痕（fire-and-forget，失败不阻断 —— 与「打印任务卡」同口径）
      onRecordPrint?.()

      // ② 通道（已连过就复用）
      let provider = providerRef.current
      if (!provider) {
        phase = 'load'
        provider = (await (loadProvider ?? defaultLoadProvider)()) ?? null
        if (!provider) {
          setStatus({ kind: 'error', text: directPrintHint('sdk-unavailable') })
          return
        }
        providerRef.current = provider
      }

      // ③ 连接（取消是 resolve 回来的状态码，由 provider 翻成 user-cancelled）
      phase = 'connect'
      if (!provider.deviceName) await provider.connect()

      // ④ 渲染（几何取自机器自报参数）
      phase = 'render'
      const jobs = await (renderJobs ?? defaultRenderJobs)(labels, collectQrSources(), provider.printerInfo)

      // ⑤ 送印
      phase = 'print'
      await provider.print(jobs)
      setStatus({ kind: 'ok', text: `已发送 ${jobs.length} 张到 ${provider.deviceName ?? '标签打印机'}` })
    } catch (error) {
      const reason =
        error instanceof LabelPrintError
          ? error.reason
          : phase === 'render'
            ? 'render-failed'
            : phase === 'load'
              ? 'sdk-unavailable'
              : phase === 'connect'
                ? 'connect-failed'
                : 'print-failed'
      setStatus({ kind: 'error', text: directPrintHint(reason) })
      // 取消 / 连不上 / 组件没起来 ⇒ 丢掉缓存通道，下次点击重新走「选设备」
      if (reason === 'user-cancelled' || reason === 'connect-failed' || reason === 'sdk-unavailable') {
        providerRef.current = null
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          data-testid="production-direct-print-button"
          disabled={!capability.ok || busy || !hasLabels}
          loading={busy}
          onClick={handlePrint}
        >
          <Bluetooth className="w-4 h-4 mr-1.5" />
          直连打印机打印
        </Button>
        {status.text && (
          <span
            data-testid="direct-print-status"
            className={status.kind === 'error' ? 'text-xs text-red-600' : 'text-xs text-neutral-600'}
            role={status.kind === 'error' ? 'alert' : undefined}
          >
            {status.text}
          </span>
        )}
      </div>

      {!capability.ok && (
        <p data-testid="direct-print-hint" className="mt-1.5 text-xs text-neutral-500">
          {capability.hint}
        </p>
      )}
      {capability.ok && (
        <p className="mt-1.5 text-xs text-neutral-400" data-testid="direct-print-ready">
          {DIRECT_PRINT_READY_HINT}
        </p>
      )}

      {/* 二维码位图源：屏幕不显示（`display:none` 不影响 canvas 位图内容），
          只在送印时被 `drawImage` 取用 —— 复用页面已装的 `qrcode.react`，不引第二个编码器。
          🔴 **只在通道可用时才渲染**：不可用时这些位图永远用不上，渲染它们纯属白烧 CPU
          （jsdom 下还会为每张刷一条 `getContext() not implemented`）。 */}
      {capability.ok && hasLabels && (
        <div ref={qrBoxRef} aria-hidden="true" style={{ display: 'none' }} data-testid="direct-print-qr-sources">
          {labels.map((label, index) =>
            label.qrValue ? (
              <QRCodeCanvas key={`${label.shortCode}-${index}`} value={label.qrValue} size={256} level="M" />
            ) : null,
          )}
        </div>
      )}
    </div>
  )
}
