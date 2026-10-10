// case_ids: PP-011
//
// PP-011（issue #6439）：生产明细页的「直连打印机」入口（**与浏览器打印并存**）。
//
// 用户 2026-10-06：「不要做成打印机定制功能 … 只要功能支持能连接上不同类型的打印机即可」
// 「需要考虑用户有通过 window 电脑安装打印机驱动或者蓝牙连接，或者 usb 连接各种情况」。
//
// 逐条判据（都能判红）：
// ① **环境不支持 ⇒ 动手前就说清**（按钮禁用 + 可行动文案），不是点下去才失败
//    —— 文案里必须含**系统打印兜底路径**（装驱动的机器照样能打，这才叫「不绑定机型」）；
// ② **成功路径的调用序**：留痕 → 加载 provider → 连接 → 渲染位图 → 送印（顺序即语义）；
// ③ 取消选设备（`user-cancelled`）⇒ 状态行给**取消**的文案（不是「连不上」），且**不送印**；
// ④ 打印失败（`print-failed`）⇒ 状态行给**打不出**的文案（不是「连不上」）—— 两类出口完全不同；
// ⑤ 直连这条**不得碰** `window.print()`（两条通道并存、互不干扰；
//    浏览器打印那条路由 `lib/print-doc.ts` 的 `usePrintDoc` 单点负责，守卫在
//    `tests/unit_ci_workflows/test_print_single_doc_on_paper.py`）。
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DirectLabelPrint from '@/components/production/DirectLabelPrint'
import { LabelPrintError, type LabelPrinterProvider, type PrintJob } from '@/lib/label-print/lpapi'
import type { LabelPrintEnv } from '@/lib/label-print/capability'
import type { WashLabelInput } from '@/lib/label-print/wash-label'

// jsdom 没有 canvas ⇒ QR 组件换成占位（QR 本体由 qrcode.react 自身保障）
vi.mock('qrcode.react', () => ({
  QRCodeCanvas: () => <canvas data-testid="qr-canvas" />,
  QRCodeSVG: () => <svg data-testid="qr-svg" />,
}))

const LABELS: WashLabelInput[] = [
  {
    qrValue: 'https://app.migaozn.com/s/7Q2M4K8P',
    shortCode: '7Q2M4K8P',
    processingOrderNo: 'JG-20260921-8237',
    rows: [
      { key: 'customer', text: '客户 赵凯', maxLines: 1 },
      { key: 'pieceName', text: '客厅窗帘A', maxLines: 2 },
    ],
  },
  {
    qrValue: 'https://app.migaozn.com/s/3N8R5T1W',
    shortCode: '3N8R5T1W',
    processingOrderNo: 'JG-20260921-8237',
    rows: [{ key: 'pieceName', text: '卧室窗帘B', maxLines: 2 }],
  },
]

const JOB: PrintJob[] = [
  { imageData: { width: 576, height: 320, data: new Uint8ClampedArray(4) } as unknown as ImageData, widthPx: 576, heightPx: 320, jobName: 'wash-label-0' },
]

function fakeProvider(over: { connectError?: LabelPrintError; printError?: LabelPrintError } = {}) {
  const order: string[] = []
  const provider: LabelPrinterProvider = {
    id: 'lpapi-ble',
    label: '德佟 LPAPI（Web Bluetooth）',
    deviceName: null,
    printerInfo: null,
    connect: vi.fn(async () => {
      order.push('connect')
      if (over.connectError) throw over.connectError
      ;(provider as { deviceName: string | null }).deviceName = 'DP235S-Y608220585'
    }),
    print: vi.fn(async () => {
      order.push('print')
      if (over.printError) throw over.printError
    }),
  }
  return { provider, order }
}

/** jsdom 里 `navigator.bluetooth` 不存在 ⇒ 不显式给 env 的话按钮是 disabled 的（正是判据 ① 的行为） */
const OK_ENV: LabelPrintEnv = { secureContext: true, hasBluetoothApi: true, isIos: false, isWechat: false }

type DirectLabelPrintProps = Parameters<typeof DirectLabelPrint>[0]

/** 缺省 `labels` / `env` 在这里补齐；调用方只给**要覆盖**的那几项 */
const renderIt = (props: Partial<DirectLabelPrintProps> = {}) =>
  render(<DirectLabelPrint {...props} labels={props.labels ?? LABELS} env={props.env ?? OK_ENV} />)

describe('DirectLabelPrint — 环境不支持时动手前说清（issue #6439 判据 ①）', () => {
  it('无 Web Bluetooth ⇒ 按钮禁用 + 文案含系统打印兜底', () => {
    renderIt({
      env: { secureContext: true, hasBluetoothApi: false, isIos: false, isWechat: false },
      loadProvider: vi.fn(),
    })
    expect(screen.getByTestId('production-direct-print-button')).toBeDisabled()
    const hint = screen.getByTestId('direct-print-hint')
    expect(hint.textContent).toContain('打印任务卡')
  })

  it('环境可用 ⇒ 按钮可用，不显示失败文案（不制造噪音）', () => {
    renderIt({
      env: { secureContext: true, hasBluetoothApi: true, isIos: false, isWechat: false },
      loadProvider: vi.fn(),
    })
    expect(screen.getByTestId('production-direct-print-button')).not.toBeDisabled()
    expect(screen.queryByTestId('direct-print-hint')).toBeNull()

    // 🔴 **DOM 面**：markdown 强调标记不得原样上屏。2026-10-06 的 Playwright 读图验收抓到真形态 ——
    //    页面把 `**免驱动**` 连星号一起印了出来（六条门禁全绿，只有肉眼/多模态看得见，正是 §15.7 的教训）。
    //    红证：把 `DIRECT_PRINT_READY_HINT` 里的 `**` 加回去 ⇒ 本条必红。
    const ready = screen.getByTestId('direct-print-ready')
    expect(ready.textContent).toContain('免驱动')
    expect(ready.textContent).not.toContain('*')
  })
})

describe('DirectLabelPrint — 成功路径的调用序（issue #6439 判据 ②）', () => {
  it('留痕 → 连接 → 渲染 → 送印（一张一张送）', async () => {
    const user = userEvent.setup()
    const { provider, order } = fakeProvider()
    const onRecordPrint = vi.fn(() => order.push('record'))
    const renderJobs = vi.fn(async () => {
      order.push('render')
      return JOB
    })
    renderIt({ onRecordPrint, renderJobs, loadProvider: async () => provider })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(provider.print).toHaveBeenCalledWith(JOB))
    expect(order).toEqual(['record', 'connect', 'render', 'print'])
    expect(screen.getByTestId('direct-print-status').textContent).toContain('1')
  })

  it('已连接过 ⇒ 不再重复连接（第二次点只渲染 + 送印）', async () => {
    const user = userEvent.setup()
    const { provider, order } = fakeProvider()
    renderIt({ renderJobs: async () => JOB, loadProvider: async () => provider })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(provider.print).toHaveBeenCalledTimes(1))
    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(provider.print).toHaveBeenCalledTimes(2))
    expect(order.filter((step) => step === 'connect')).toHaveLength(1)
  })
})

describe('DirectLabelPrint — 失败各有出口（issue #6439 判据 ③④）', () => {
  it('取消选设备 ⇒ 状态说「取消」，且**不送印**', async () => {
    const user = userEvent.setup()
    const { provider } = fakeProvider({ connectError: new LabelPrintError('user-cancelled') })
    renderIt({ renderJobs: async () => JOB, loadProvider: async () => provider })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(screen.getByTestId('direct-print-status').textContent).toContain('取消'))
    expect(provider.print).not.toHaveBeenCalled()
  })

  it('打印失败 ⇒ 状态说「已连上但没打出来」（与「连不上」是两句话）', async () => {
    const user = userEvent.setup()
    const { provider } = fakeProvider({ printError: new LabelPrintError('print-failed') })
    renderIt({ renderJobs: async () => JOB, loadProvider: async () => provider })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(screen.getByTestId('direct-print-status').textContent).toContain('没打出来'))
  })

  it('SDK 没加载起来（离线/被拦截）⇒ 给「刷新重试」的可行动文案，不是静默失败', async () => {
    const user = userEvent.setup()
    renderIt({ renderJobs: async () => JOB, loadProvider: async () => null })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(screen.getByTestId('direct-print-status').textContent).toContain('刷新'))
  })
})

describe('DirectLabelPrint — 与浏览器打印并存（issue #6439 判据 ⑤）', () => {
  it('直连打印**不触发** window.print', async () => {
    const user = userEvent.setup()
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    const { provider } = fakeProvider()
    renderIt({ renderJobs: async () => JOB, loadProvider: async () => provider })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(provider.print).toHaveBeenCalled())
    expect(printSpy).not.toHaveBeenCalled()
    printSpy.mockRestore()
  })
})
