// case_ids: BM-023, BM-024, BM-026
/**
 * 工人**拍照补打**页的行为判据（issue #5640；验收判据 2~11）
 *
 * 与 P3 的 `worker-inbound-page.test.tsx` **同族**（同一套替身手法、同一批能力文案真值），
 * 但走的是另一条主链：**拍照/手输 → 码空间判定 → 单据详情 → 补打一张新标签**。
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | P1 | 没有工人 session ⇒ 明说去登录（不渲染拍照入口、不静默跳走） | 直接渲染拍照步 ⇒ 红 |
 * | P2 | 打印能力缺口**动手前**上屏（iOS ⇒ 一进页面就看到 iPhone 打不了） | 打完才失败 ⇒ 红 |
 * | P3 | 解码出 `/i/<短码>` ⇒ 查详情 + 上屏；**不**调打印留痕（还没点打印） | 提前留痕 ⇒ 红 |
 * | P4 | 🔴 解码出 `/s/<短码>` ⇒ 屏上说「洗水码」+ 报工入口，**一次都不查入库详情** | 把它当入库码查 ⇒ 红 |
 * | P5 | 🔴 404 / 410 **分开呈现**（两个 testid、两句不同的话：查无此码 / 已撤销） | 合成一句话 ⇒ 红 |
 * | P6 | 手输含 `O` 的 8 位 ⇒ **原样**送去查询（抄错归一化在服务端） | 客户端严格字母表闸 ⇒ 红 |
 * | P7 | 打印走唯一入口：**先留痕后送数据**，屏上显示服务端读数（前端不 +1） | 顺序颠倒 / 本地 +1 ⇒ 红 |
 * | P8 | h5 下不调 `Taro.login`（工人身份走工号 + PIN） | 页面加 `Taro.login` ⇒ 红 |
 */
import React from 'react'
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react'
import Taro from '@tarojs/taro'

const ORIGINAL_TARO_ENV = process.env.TARO_ENV
process.env.TARO_ENV = 'h5'

/** 送数据的调用序（判据 P7：留痕必须排在送数据之前） */
const printLog: string[] = []

jest.mock('../src/utils/workerSession', () => ({
  hasWorkerSession: jest.fn(() => true),
  workerSessionHeaders: jest.fn(() => ({ 'X-Worker-Session-Id': 's1' })),
}))

jest.mock('../src/utils/inbound/barcodeDecode', () => ({
  decodeBarcodeFromPhoto: jest.fn(async () => ({
    text: 'https://app.migaozn.com/i/ABCD0234',
    source: 'h5-dom-canvas',
    hint: '',
  })),
}))

jest.mock('../src/utils/inbound/lpapiTransport', () => ({
  loadLpapi: jest.fn(async () => ({ getInstance: () => ({}) })),
  createLpapiTransport: jest.fn(() => ({
    id: 'fake',
    label: '测试打印机',
    print: async () => {
      printLog.push('transport')
    },
  })),
}))

jest.mock('../src/utils/inbound/labelPageKit', () => ({
  SDK_UNAVAILABLE_HINT: '打印组件没加载起来（测试替身文案，与真实台账同键）',
  createH5CanvasFactory: () => (widthPx: number, heightPx: number) => ({
    width: widthPx,
    height: heightPx,
    getContext: () => ({
      fillStyle: '',
      font: '',
      textBaseline: '',
      fillRect: () => undefined,
      fillText: () => undefined,
      getImageData: (x: number, y: number, w: number, h: number) => ({
        data: new Uint8ClampedArray(w * h * 4),
        width: w,
        height: h,
      }),
    }),
    toDataURL: () => 'data:image/png;base64,AA',
  }),
  renderLabelPreview: jest.fn(() => ({
    // ⚠️ 这里刻意**不复述像素口径的数字**：唯一真值是介质矩阵，而判据
    //    `tests/inbound-print-geometry-single-source.test.ts` 的 C2 会扫全仓
    //    「同时写着那组口径」的文件 ⇒ 判据/替身里复述一遍会把它判红（它是对的，别绕）。
    url: 'data:image/png;base64,AA',
    widthPx: 1,
    heightPx: 1,
    notice: '',
  })),
}))

jest.mock('../src/services/workerInboundService', () => ({
  getInboundLabel: jest.fn(),
  // 🔴 补打链**不允许**出现任何识别/上传调用（0 次 LLM）：这对替身就是为了让"先问模型"那条路当场红
  recognizeInbound: jest.fn(),
  uploadInboundPhoto: jest.fn(),
  recordInboundLabelPrint: jest.fn(async (code: string) => {
    printLog.push('recordPrint')
    return { success: true, message: '', data: { shortCode: code, printCount: 3 } }
  }),
}))

import WorkerReprintPage from '../src/pages/worker/reprint/index'
import { hasWorkerSession } from '../src/utils/workerSession'
import { decodeBarcodeFromPhoto } from '../src/utils/inbound/barcodeDecode'
import { PRINT_FAILURE_HINTS, PRINT_READY_HINT } from '../src/utils/inbound/printCapability'
import { REPORT_PAGE_ROUTE } from '../src/utils/inbound/codeSpace'
import { isValidShortCode } from '../src/utils/inbound/shortCode'
import {
  getInboundLabel,
  recordInboundLabelPrint,
  recognizeInbound,
  uploadInboundPhoto,
} from '../src/services/workerInboundService'

const mockHasWorkerSession = hasWorkerSession as jest.Mock
const mockDecode = decodeBarcodeFromPhoto as jest.Mock
const mockChooseImage = Taro.chooseImage as jest.Mock
const mockNavigateTo = Taro.navigateTo as jest.Mock
const mockGetLabel = getInboundLabel as jest.Mock
const mockRecordPrint = recordInboundLabelPrint as jest.Mock
const mockRecognize = recognizeInbound as jest.Mock
const mockUploadPhoto = uploadInboundPhoto as jest.Mock

const VIEW = {
  shortCode: 'ABCD0234',
  inboundNo: 'RK-20260927-0001',
  skuCode: 'MG-1001',
  productName: '遮光布',
  colorName: '米白',
  doorWidth: '280',
  quantity: '60.5',
  printCount: 1,
}

function setPrintEnv({ ios, secure = true, bluetooth = true }: { ios: boolean; secure?: boolean; bluetooth?: boolean }) {
  ;(window as any).isSecureContext = secure
  Object.defineProperty(window.navigator, 'bluetooth', { value: bluetooth ? {} : undefined, configurable: true })
  Object.defineProperty(window.navigator, 'userAgent', {
    value: ios
      ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15'
      : 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36',
    configurable: true,
  })
}

/** 走「拍照 → 识别」这一步 */
async function shootAndRecognize() {
  mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:photo-a'], tempFiles: [{ originalFileObj: null }] })
  fireEvent.click(screen.getByTestId('reprint-pick'))
  await waitFor(() => expect(screen.getByTestId('reprint-recognize')).toBeTruthy())
  fireEvent.click(screen.getByTestId('reprint-recognize'))
}

/** 走「手输短码 → 查询」这一步 */
async function typeAndLookup(code: string) {
  fireEvent.click(screen.getByTestId('reprint-to-manual'))
  fireEvent.change(screen.getByTestId('reprint-manual-code'), { target: { value: code } })
  fireEvent.click(screen.getByTestId('reprint-manual-submit'))
}

describe('工人拍照补打页', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    printLog.length = 0
    process.env.TARO_ENV = 'h5'
    mockHasWorkerSession.mockReturnValue(true)
    mockDecode.mockResolvedValue({
      text: 'https://app.migaozn.com/i/ABCD0234',
      source: 'h5-dom-canvas',
      hint: '',
    })
    mockGetLabel.mockResolvedValue({ success: true, message: '', data: VIEW })
    setPrintEnv({ ios: false })
  })

  afterAll(() => {
    process.env.TARO_ENV = ORIGINAL_TARO_ENV
  })

  it('P1 没有工人 session ⇒ 明说去登录（不渲染拍照入口、不静默跳走）', () => {
    mockHasWorkerSession.mockReturnValue(false)
    render(<WorkerReprintPage />)
    expect(screen.getByTestId('reprint-worker-login-required')).toBeTruthy()
    expect(screen.queryByTestId('reprint-pick')).toBeNull()
    fireEvent.click(screen.getByTestId('reprint-go-worker-login'))
    expect(mockNavigateTo).toHaveBeenCalledWith({ url: '/pages/worker/login/index' })
  })

  it('P2 iOS 环境 ⇒ 一进页面（零操作）就说明「iPhone 打不了」，不是打完才失败', () => {
    setPrintEnv({ ios: true })
    render(<WorkerReprintPage />)
    const banner = screen.getByTestId('reprint-print-capability')
    expect(banner.textContent).toBe(PRINT_FAILURE_HINTS['ios-unsupported'])
    expect(banner.textContent).toContain('iPhone')
    expect(mockGetLabel).not.toHaveBeenCalled()
  })

  it('P2 安卓 Chrome + HTTPS ⇒ 正向提示（可打印）', () => {
    render(<WorkerReprintPage />)
    expect(screen.getByTestId('reprint-print-capability').textContent).toBe(PRINT_READY_HINT)
  })

  it('P3 解码出 /i/<短码> ⇒ 查详情并上屏；此时**不**调打印留痕', async () => {
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-step-detail')).toBeTruthy())
    expect(mockGetLabel).toHaveBeenCalledWith('ABCD0234')
    expect(screen.getByText(/RK-20260927-0001/)).toBeTruthy()
    expect(screen.getByText(/遮光布/)).toBeTruthy()
    // 🔴 红证：还没点打印 ⇒ 一次留痕都不该有（"先留痕"不是"提前留痕"）
    expect(mockRecordPrint).not.toHaveBeenCalled()
    // 🔴 0 次 LLM（验收判据 2）：整条补打链**没有任何**识别/上传调用
    expect(mockRecognize).not.toHaveBeenCalled()
    expect(mockUploadPhoto).not.toHaveBeenCalled()
  })

  it('P4 🔴 解码出 /s/<短码> ⇒ 说是「洗水码」+ 报工入口，且一次都不查入库详情', async () => {
    mockDecode.mockResolvedValueOnce({
      text: 'https://app.migaozn.com/s/7K3M9QP2',
      source: 'h5-dom-canvas',
      hint: '',
    })
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-wash-code')).toBeTruthy())
    expect(screen.getByTestId('reprint-wash-code').textContent).toContain('洗水码')
    expect(mockGetLabel).not.toHaveBeenCalled()
    expect(screen.queryByTestId('reprint-step-detail')).toBeNull()
    // 入口真的可点，且指向报工页（不是"说一句就完了"）
    fireEvent.click(screen.getByTestId('reprint-go-report'))
    expect(mockNavigateTo).toHaveBeenCalledWith({ url: REPORT_PAGE_ROUTE })
    // 🔴 红证：这段 URL 的末段**看起来就是**一个 8 位短码 ⇒ 不看码空间的那条路会把它送去查详情
    expect('https://app.migaozn.com/s/7K3M9QP2'.split('/').pop()).toHaveLength(8)
    expect(mockGetLabel).not.toHaveBeenCalled()
  })

  it('P4 非米高二维码 ⇒ 明确告知「不是米高的标签」，也不查详情', async () => {
    mockDecode.mockResolvedValueOnce({ text: 'https://example.com/x/1', source: 'h5-dom-canvas', hint: '' })
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-foreign')).toBeTruthy())
    expect(screen.getByTestId('reprint-foreign').textContent).toContain('不是米高的标签')
    expect(mockGetLabel).not.toHaveBeenCalled()
  })

  it('P4 解码失败 ⇒ 提示重拍 + 引导手输（不猜单、不预填）', async () => {
    mockDecode.mockResolvedValueOnce({
      text: null,
      source: 'h5-dom-canvas',
      hint: '这张照片里没有可识别的二维码。',
    })
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-undecoded')).toBeTruthy())
    expect(screen.getByTestId('reprint-undecoded').textContent).toMatch(/重拍|手输/)
    expect(mockGetLabel).not.toHaveBeenCalled()
  })

  it('P5 🔴 404 与 410 分开呈现：两个 testid、两句不同的话', async () => {
    mockGetLabel.mockResolvedValueOnce({
      success: false,
      message: '入库标签不存在',
      statusCode: 404,
      code: 'NOT_FOUND',
      suggestion: '请核对标签上的短码（8 位，字母与数字；字母 O/I/L 会被当作 0/1 处理）',
    })
    const first = render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-not-found')).toBeTruthy())
    const notFoundText = screen.getByTestId('reprint-not-found').textContent || ''
    expect(notFoundText).toContain('查无此码')
    expect(screen.queryByTestId('reprint-revoked')).toBeNull()
    first.unmount()

    mockGetLabel.mockResolvedValueOnce({
      success: false,
      message: '该入库标签已作废',
      statusCode: 410,
      code: 'LABEL_REVOKED',
      suggestion: '这张纸对应的标签已被撤销 —— 请按单据重新补打一张（旧码不再可用）',
    })
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-revoked')).toBeTruthy())
    const revokedText = screen.getByTestId('reprint-revoked').textContent || ''
    expect(revokedText).toContain('已撤销')
    expect(revokedText).not.toBe(notFoundText)
    expect(screen.queryByTestId('reprint-not-found')).toBeNull()
    // 撤销是业务动作 ⇒ 屏上要给"下一步怎么办"，而不是一句"查无此码"
    expect(revokedText).toMatch(/重新|补打|文员/)
  })

  it('P6 🔴 手输含 O 的 8 位 ⇒ 原样送去查询（抄错归一化在服务端，客户端不自行归一化）', async () => {
    render(<WorkerReprintPage />)
    await typeAndLookup('ABCDO234')
    await waitFor(() => expect(screen.getByTestId('reprint-step-detail')).toBeTruthy())
    expect(mockGetLabel).toHaveBeenCalledWith('ABCDO234')
    // 🔴 红证：「只认严格字母表」的客户端闸会把这个码拦下 ⇒ 上面那行永远不会发生
    expect(isValidShortCode('ABCDO234')).toBe(false)
    expect(mockGetLabel).toHaveBeenCalledTimes(1)
  })

  it('P6 手输形态不合法 ⇒ 明说 8 位、一次请求都不发', async () => {
    render(<WorkerReprintPage />)
    await typeAndLookup('ABCD')
    await waitFor(() => expect(screen.getByTestId('reprint-manual-invalid')).toBeTruthy())
    expect(screen.getByTestId('reprint-manual-invalid').textContent).toContain('8 位')
    expect(mockGetLabel).not.toHaveBeenCalled()
  })

  it('P7 打印：**先留痕后送数据**，屏上显示服务端读数（前端不 +1）', async () => {
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-step-detail')).toBeTruthy())
    fireEvent.click(screen.getByTestId('reprint-print'))
    await waitFor(() => expect(screen.getByTestId('reprint-print-state')).toBeTruthy())
    expect(printLog).toEqual(['recordPrint', 'transport'])
    const state = screen.getByTestId('reprint-print-state').textContent || ''
    // 服务端说第 3 次 ⇒ 屏上就是 3（不是 1 + 本地计数）
    expect(state).toContain('3')
    // 🔴 红证：顺序颠倒 ⇒ 同一个断言失败（"先打出来再说"是本单明令禁止的形态）
    expect(['transport', 'recordPrint']).not.toEqual(['recordPrint', 'transport'])
  })

  it('P7 打印组件加载不出来 ⇒ 给专属文案且**一次都不留痕**', async () => {
    const lpapi = require('../src/utils/inbound/lpapiTransport')
    ;(lpapi.loadLpapi as jest.Mock).mockResolvedValueOnce(null)
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-step-detail')).toBeTruthy())
    fireEvent.click(screen.getByTestId('reprint-print'))
    await waitFor(() => expect(screen.getByTestId('reprint-print-state')).toBeTruthy())
    expect(screen.getByTestId('reprint-print-state').textContent).toContain('测试替身文案')
    expect(mockRecordPrint).not.toHaveBeenCalled()
    expect(printLog).toEqual([])
  })

  it('P8 h5 下不调 Taro.login（工人身份走工号 + PIN）', async () => {
    render(<WorkerReprintPage />)
    fireEvent.click(screen.getByTestId('reprint-pick'))
    await waitFor(() => expect(mockChooseImage).toHaveBeenCalled())
    expect(Taro.login).not.toHaveBeenCalled()
  })

  it('P9 🔴 缺码不画假码（补打上下文）：详情没有短码 ⇒ 一次留痕都不发、也不送数据', async () => {
    // 服务端给了一张**没有短码**的标签（数据异常）⇒ 页面必须拒绝打印，而不是拿占位码去画一张「扫出来是错的」标签
    mockGetLabel.mockResolvedValueOnce({
      success: true,
      message: '',
      data: { ...VIEW, shortCode: null },
    })
    render(<WorkerReprintPage />)
    await shootAndRecognize()
    await waitFor(() => expect(screen.getByTestId('reprint-step-detail')).toBeTruthy())
    expect(screen.getByText(/（缺失）/)).toBeTruthy()
    fireEvent.click(screen.getByTestId('reprint-print'))
    await waitFor(() => expect(screen.getByTestId('reprint-error')).toBeTruthy())
    expect(screen.getByTestId('reprint-error').textContent).toContain('没有短码')
    expect(mockRecordPrint).not.toHaveBeenCalled()
    expect(printLog).toEqual([])
    // 版心仍按真值给出（缺码只影响二维码那一步，不影响纸型/版面）
    expect(screen.getByTestId('reprint-label-bound').textContent).toContain('1:1 送打印')
  })

  it('P8 页面不碰商家面：整条链只走 /api/worker/**（源码面）', () => {
    const fs = require('fs')
    const path = require('path')
    const file = path.join(__dirname, '..', 'src/pages/worker/reprint/index.tsx')
    const code = fs
      .readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    expect(code).not.toContain('/api/admin/')
  })
})

/**
 * 落地页深链的**页面侧**（issue #5052 实现 PR；设计 §5.4）。
 *
 * 启动器（`src/app.tsx`）只做搬运，判定与分文都在本页：`router.params.code` ⇒ 码空间 ⇒
 * 入库码才查详情（非入库码**一次请求都不发**）。启动器那一半的判据在
 * `tests/inbound-landing-deeplink.test.tsx`（D5/D6）；两半合起来才是「扫标签 → 看到那张单」的整条链。
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | R1 | 🔴 入库短码落地 ⇒ **自动**查详情并上屏（短码原样带走，不归一化） | 不消费参数 ⇒ 停在拍照步（红） |
 * | R2 | 🔴 洗水码落地 ⇒ 洗水码文案 + 报工入口，**一次都不查入库详情** | 当入库码查 ⇒ 红 |
 * | R3 | 别域名 / 纯文本 / 空值 ⇒ 明确提示（`foreign` / `invalid-input`），都不查详情 | 静默当没有参数 ⇒ 红 |
 * | R4 | 未登录 ⇒ **不消费**（不拿 401 当"查无此单"），登录入口照给 | 无 session 也发请求 ⇒ 红 |
 */
describe('落地页深链的页面侧（`?code=` 被消费且按码空间分流）', () => {
  const mockTaroCurrent = Taro.getCurrentInstance as jest.Mock

  beforeEach(() => {
    jest.clearAllMocks()
    printLog.length = 0
    process.env.TARO_ENV = 'h5'
    mockHasWorkerSession.mockReturnValue(true)
    mockGetLabel.mockResolvedValue({ success: true, message: '', data: VIEW })
    setPrintEnv({ ios: false })
    mockTaroCurrent.mockReturnValue({ router: { path: 'pages/worker/reprint/index', params: {} } })
  })

  afterAll(() => {
    mockTaroCurrent.mockReturnValue({ router: { path: '', params: {} } })
    process.env.TARO_ENV = ORIGINAL_TARO_ENV
  })

  /** 从启动器/小程序带进来的页面参数（两条路都落在这一处） */
  function landWith(code: string) {
    mockTaroCurrent.mockReturnValue({ router: { path: 'pages/worker/reprint/index', params: { code } } })
  }

  it('R1 🔴 入库短码落地 ⇒ 自动查详情并上屏（短码原样带走）', async () => {
    landWith('ABCD0234')
    render(<WorkerReprintPage />)
    await waitFor(() => expect(mockGetLabel).toHaveBeenCalledWith('ABCD0234'))
    await waitFor(() => expect(screen.getByTestId('reprint-step-detail')).toBeTruthy())
    // 抄错形态（O/I/L）也照样原样送服务端（归一化在服务端）
    cleanup()
    jest.clearAllMocks()
    landWith('ABCDO234')
    render(<WorkerReprintPage />)
    await waitFor(() => expect(mockGetLabel).toHaveBeenCalledWith('ABCDO234'))
  })

  it('R2 🔴 洗水码落地 ⇒ 洗水码文案 + 报工入口，**一次都不查入库详情**', async () => {
    landWith('https://app.migaozn.com/s/7K3M9QP2')
    render(<WorkerReprintPage />)
    await waitFor(() => expect(screen.getByTestId('reprint-wash-code')).toBeTruthy())
    expect(mockGetLabel).not.toHaveBeenCalled()
    expect(screen.getByTestId('reprint-wash-code').textContent).toContain('洗水码')
    fireEvent.click(screen.getByTestId('reprint-go-report'))
    expect(mockNavigateTo).toHaveBeenCalledWith({ url: REPORT_PAGE_ROUTE })
  })

  it('R3 🔴 别域名 / 纯文本 ⇒ 「这不是米高的标签」；空值 ⇒ 「8 位短码」提示（都不查详情）', async () => {
    for (const [raw, testId] of [
      ['https://evil.example/i/ABCD2345', 'reprint-foreign'],
      ['MG-1001', 'reprint-foreign'],
      ['', 'reprint-manual-invalid'],
    ] as [string, string][]) {
      cleanup()
      jest.clearAllMocks()
      landWith(raw)
      render(<WorkerReprintPage />)
      await waitFor(() => expect(screen.getByTestId(testId)).toBeTruthy())
      expect({ raw, called: mockGetLabel.mock.calls.length }).toEqual({ raw, called: 0 })
    }
  })

  it('R4 未登录 ⇒ 不消费深链（不拿 401 当"查无此单"），登录入口照给', async () => {
    mockHasWorkerSession.mockReturnValue(false)
    landWith('ABCD0234')
    render(<WorkerReprintPage />)
    await waitFor(() => expect(screen.getByTestId('reprint-worker-login-required')).toBeTruthy())
    expect(mockGetLabel).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('reprint-go-worker-login'))
    expect(mockNavigateTo).toHaveBeenCalledWith({ url: '/pages/worker/login/index' })
  })

  it('R1 没有 `code` 参数 ⇒ 页面照旧（不自动查询、空跑反证）', async () => {
    render(<WorkerReprintPage />)
    await waitFor(() => expect(screen.getByTestId('reprint-step-photo')).toBeTruthy())
    expect(mockGetLabel).not.toHaveBeenCalled()
  })
})
