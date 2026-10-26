// case_ids: PP-011
//
// PP-011（issue #6439 建入口 → **issue #7288 搬进「水洗唛 · 打印预览」页脚并改名「蓝牙无线打印」**）：
// 免驱动直连通道的入口组件（**与系统打印并存**）。
//
// 用户 2026-10-06：「不要做成打印机定制功能 … 只要功能支持能连接上不同类型的打印机即可」
// 「需要考虑用户有通过 window 电脑安装打印机驱动或者蓝牙连接，或者 usb 连接各种情况」。
// 用户 2026-10-18（#7288）：「把这个直连打印机这个功能不如做到水洗唛打印预览中，在右下角加个按钮叫蓝牙无线打印」。
//
// 逐条判据（都能判红）：
// ① **环境不支持 ⇒ 动手前就说清**（按钮禁用 + 可行动文案），不是点下去才失败
//    —— 文案里必须含**系统打印兜底路径**，且指的是页脚里那个「打印」（#7288 后旧名「打印任务卡」已不适用）；
// ② **成功路径的调用序**：留痕 → 加载 provider → 连接 → 渲染位图 → 送印（顺序即语义）；
// ③ 取消选设备（`user-cancelled`）⇒ 状态行给**取消**的文案（不是「连不上」），且**不送印**；
// ④ 打印失败（`print-failed`）⇒ 状态行给**打不出**的文案（不是「连不上」）—— 两类出口完全不同；
// ⑤ 直连这条**不得碰** `window.print()`（两条通道并存、互不干扰；
//    浏览器打印那条路由 `lib/print-doc.ts` 的 `usePrintDoc` 单点负责，守卫在
//    `tests/unit_ci_workflows/test_print_single_doc_on_paper.py`）；
// ⑥ **页脚形态**：按钮文案 = 「蓝牙无线打印」，说明是一行（与按钮并排，不摊开成一段）——
//    页脚动作行只有一行高，长段落会把「打印」挤出视野（#7288 的搬家前提）。
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

// 🔴 夹具只带 `qrValue` / `companyName` / `rows` / `qrPlaceholderHint`（`WashLabelInput` 的现行字段面）：
//    `shortCode`（人可读短码）与 `processingOrderNo`（加工单号）随 issue #7816 **已从纸面退场**，
//    类型里也不再存在 —— 写回来 ⇒ 打印出纸上没有的字（且本文件的签名判据会红）。
const LABELS: WashLabelInput[] = [
  {
    qrValue: 'https://app.migaozn.com/s/7Q2M4K8P',
    rows: [
      { key: 'customer', text: '客户 赵凯', maxLines: 1 },
      { key: 'color', text: '客厅窗帘A', maxLines: 2 },
    ],
  },
  {
    qrValue: 'https://app.migaozn.com/s/3N8R5T1W',
    rows: [{ key: 'color', text: '卧室窗帘B', maxLines: 2 }],
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
    const button = screen.getByTestId('production-direct-print-button')
    expect(button).toBeDisabled()
    // #7288：按钮文案 = 用户点名的「蓝牙无线打印」（改回旧名「直连打印机打印」⇒ 本行必红）
    expect(button).toHaveTextContent('蓝牙无线打印')
    const hint = screen.getByTestId('direct-print-hint')
    // #7288：兜底路径指的是页脚里那个「打印」——旧措辞「打印任务卡」在弹层里点不到
    expect(hint.textContent).toContain('系统打印')
    expect(hint.textContent).not.toContain('打印任务卡')
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
    // ⑥ 页脚形态：这行说明与按钮**并排**在动作行里 ⇒ 必须是一行短句（改回改前那段 40+ 字长说明 ⇒ 必红）
    expect(ready.textContent!.length).toBeLessThanOrEqual(32)
  })
})

describe('DirectLabelPrint — 成功路径的调用序（issue #6439 判据 ②）', () => {
  it('留痕 → 连接 → 渲染 → 送印（一张一张送）', async () => {
    const user = userEvent.setup()
    const { provider, order } = fakeProvider()
    const onRecordPrint = vi.fn(() => order.push('record'))
    // 替身签名与组件的 `renderJobs` prop **逐参一致**（三个参数；多一个/少一个 ⇒ 类型与判据都红）
    const renderJobs = vi.fn(
      async (
        _labels: WashLabelInput[],
        _qrSources: Array<CanvasImageSource | null>,
        _printerInfo: Record<string, unknown> | null,
      ) => {
        order.push('render')
        return JOB
      },
    )
    renderIt({ onRecordPrint, renderJobs, loadProvider: async () => provider })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(provider.print).toHaveBeenCalledWith(JOB))
    expect(order).toEqual(['record', 'connect', 'render', 'print'])
    expect(screen.getByTestId('direct-print-status').textContent).toContain('1')

    // 🔴 渲染器签名 = `(labels, qrSources, printerInfo)` **恰好三个参数**
    //    （issue #7816：纸长固定 50×150 ⇒ `labelLengthMm` 不再是入参；多传一个 ⇒ 本条必红）
    expect(renderJobs.mock.calls[0]).toHaveLength(3)
    // ① 逐张的输入原样交下去（不在这里改内容 / 不截断份数）
    expect(renderJobs.mock.calls[0][0]).toBe(LABELS)
    // ② 二维码位图**与 labels 同序**、每张一位（本夹具两张都有码）
    expect(renderJobs.mock.calls[0][1]).toHaveLength(2)
    // ③ 第三参 = 机器自报参数（假 provider 没自报 ⇒ null），不是纸长之类的版面参数
    expect(renderJobs.mock.calls[0][2]).toBeNull()
  })

  it('🔴 份数 = 开数（issue #7816）：同一部位展开成 N 条 ⇒ N 张都送渲染、都送印（不按部位/码去重）', async () => {
    const user = userEvent.setup()
    const { provider } = fakeProvider()
    // 双开商品在 `toWashLabelInputs` 里被展开成 2 条**内容相同**的记录（份数口径只有那一处）
    const twoCopies: WashLabelInput[] = [LABELS[0], LABELS[0]]
    const renderJobs = vi.fn(async (labels: WashLabelInput[]) =>
      labels.map((_label, index) => ({ ...JOB[0], jobName: `wash-label-${index}` })),
    )
    renderIt({ labels: twoCopies, renderJobs, loadProvider: async () => provider })

    await user.click(screen.getByTestId('production-direct-print-button'))
    await waitFor(() => expect(provider.print).toHaveBeenCalledTimes(1))
    // 两条都进了渲染器（去重 ⇒ 1 ⇒ 必红），也都被送印
    expect(renderJobs.mock.calls[0][0]).toHaveLength(2)
    expect((provider.print as unknown as { mock: { calls: PrintJob[][] } }).mock.calls[0][0]).toHaveLength(2)
    await waitFor(() => expect(screen.getByTestId('direct-print-status').textContent).toContain('2 张'))
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
