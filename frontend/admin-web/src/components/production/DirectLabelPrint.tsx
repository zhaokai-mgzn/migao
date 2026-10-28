'use client'

import { useMemo, useRef, useState } from 'react'
import { QRCodeCanvas } from 'qrcode.react'
import { Bluetooth } from 'lucide-react'
import { Button } from '@/components/ui'
import { cn } from '@/lib/utils'
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
 * 「蓝牙无线打印」入口（issue #6439 建立 → **issue #7288 搬进预览页脚**）——
 * **免驱动**把洗水唛送到标签机（浏览器 Web Bluetooth）。
 *
 * ## 现在挂在哪
 *
 * 「水洗唛 · 打印预览」（`frontend/admin-web/src/components/orders/PrintDocPreview.tsx`）的**页脚动作行**
 * （右下角），与「复制截图 / 打印」并排。用户 2026-10-18 逐字：「把这个直连打印机这个功能不如做到
 * 水洗唛打印预览中，在右下角加个按钮叫蓝牙无线打印」。
 *
 * 好处 = **两条通道在同一个视野里**：预览里看到的就是要打的那张纸，走系统打印还是蓝牙直连不必先关弹层。
 * 改前它常驻页面第一屏（按钮 + 一整行说明），而纸面预览在弹层里 ⇒ 两个入口分在两个视野。
 *
 * ## 与浏览器打印的关系：**并存，不是替换**
 *
 * 「打印任务卡」→ 预览里的「打印」（`window.print()` + `@page`）覆盖**任何装了驱动**的打印机
 * （Windows 驱动 / USB / 网络 / 已配对蓝牙）—— 那是**唯一**能覆盖任意品牌的路，**本组件不动它**。
 * 本组件是「懒得装驱动」时的补充：只覆盖**带 SDK 协议**的机型。
 * ⇒ 两者互不干扰（本组件**不碰** `window.print`，由守卫
 * `tests/unit_ci_workflows/test_print_single_doc_on_paper.py` 钉住「`window.print` 只有一处」）。
 *
 * ## 纸面与预览**同一份**（issue #6656）
 *
 * 打出来的位图读的就是预览那份有序行清单（`frontend/admin-web/src/lib/wash-label-content.ts` 的
 * `washLabelRows` + 同读介质 `label-50x140`）⇒ 搬入口**不改版式**；唯一不可统一的仍是纸的物理宽度
 * （打印头 384 点 = 48mm < 纸宽 50mm，登记在 `lib/print-media.json`）。
 *
 * ## 可注入面（为什么留这两个口）
 *
 * - `loadProvider`：真实现要动态注入厂商 UMD bundle；测试传替身 ⇒ 单测不碰网络与蓝牙。
 * - `renderJobs`：真实现要真 canvas（本仓 jsdom 没装 `canvas` 包，跑不了）⇒ 测试传替身；
 *   版式与绘制本身另有纯函数判据（`tests/unit/lib/label-print/wash-label.test.ts`）。
 *
 * ## 留痕
 *
 * 与「打印」同口径：**先上报计数、失败不阻断**（`onRecordPrint` 由页面注入，内部 fire-and-forget）
 * —— 换通道不换纪律。
 *
 * ## 边界（照实登记）
 *
 * 预览层关掉即卸载 ⇒ 通道缓存（`providerRef`）随之丢弃：**再开预览要重新选一次设备**。
 * 这是把入口搬进弹层的代价，有意接受（同一次预览里连打多张不受影响 —— 预览在打印后不会自动关）。
 */
export interface DirectLabelPrintProps {
  /** 本次要打的洗水唛（一部位一张；页面用 `toWashLabelInputs(positions)` 生成） */
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

/** 缺省通道：动态加载 npm 依赖 `lpapi-ble`（与 bmini 侧同一个包）→ 造 LPAPI provider */
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
      // ① 留痕（fire-and-forget，失败不阻断 —— 与「打印」同口径）
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
      const jobs = await (renderJobs ?? defaultRenderJobs)(
        labels,
        collectQrSources(),
        provider.printerInfo,
      )

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

  /**
   * 按钮左侧的那一格说明（**同一格**承载三种状态，不叠三段文字）：
   * 本次结果 > 通道不可用的原因 > 通道能力说明。
   * 优先级写成「结果优先」：客户端过之后，能力说明就不该再占位（否则同一行既说「已发送」又说「只支持…」）。
   */
  const note = status.text
    ? { kind: 'status' as const, testId: 'direct-print-status', text: status.text }
    : !capability.ok
      ? { kind: 'hint' as const, testId: 'direct-print-hint', text: capability.hint }
      : { kind: 'ready' as const, testId: 'direct-print-ready', text: DIRECT_PRINT_READY_HINT }
  const noteIsAlert = note.kind === 'status' && status.kind === 'error'

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      <span
        data-testid={note.testId}
        role={noteIsAlert ? 'alert' : undefined}
        className={cn(
          'max-w-[520px] text-xs leading-snug',
          noteIsAlert ? 'text-red-600' : note.kind === 'hint' ? 'text-neutral-500' : 'text-neutral-400',
        )}
      >
        {note.text}
      </span>

      <Button
        variant="secondary"
        icon={<Bluetooth className="w-4 h-4" />}
        data-testid="production-direct-print-button"
        disabled={!capability.ok || busy || !hasLabels}
        loading={busy}
        onClick={handlePrint}
      >
        蓝牙无线打印
      </Button>

      {/* 二维码位图源：屏幕不显示（`display:none` 不影响 canvas 位图内容），
          只在送印时被 `drawImage` 取用 —— 复用页面已装的 `qrcode.react`，不引第二个编码器。
          🔴 **只在通道可用时才渲染**：不可用时这些位图永远用不上，渲染它们纯属白烧 CPU
          （jsdom 下还会为每张刷一条 `getContext() not implemented`）。 */}
      {capability.ok && hasLabels && (
        <div ref={qrBoxRef} aria-hidden="true" style={{ display: 'none' }} data-testid="direct-print-qr-sources">
          {labels.map((label, index) =>
            label.qrValue ? (
              <QRCodeCanvas key={`qr-${index}`} value={label.qrValue} size={256} level="M" />
            ) : null,
          )}
        </div>
      )}
    </div>
  )
}
