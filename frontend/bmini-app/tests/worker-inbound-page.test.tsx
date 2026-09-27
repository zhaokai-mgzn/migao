// case_ids: BM-018, BM-019
/**
 * 工人**拍照入库页**的行为判据（issue #5052 P3；验收判据 10 / 11 + 页面级联调）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | C1 | **身份分流**：没有工人 session ⇒ 明说去登录（不渲染拍照、不静默跳走） | 直接渲染拍照步 ⇒ 红 |
 * | C2 | **能力缺口动手前上屏**：iOS 环境下一进页面（**零操作**）就看到「iPhone 打不了」 | 只在打完失败后显示 ⇒ 红 |
 * | C3 | **h5 下不调 `Taro.login`**（工人身份走工号 + PIN） | 页面加 `Taro.login` ⇒ 红 |
 * | C4 | **过账二次确认**：点取消 ⇒ 一次都不建单；确认 ⇒ 建单 + 过账（不可逆动作的护栏） | 取消也提交 ⇒ 红 |
 * | C5 | 数量非法 ⇒ 端侧先拦（不白跑一次 400），文案取自**同一份**口径真值 | 静默放行 ⇒ 红 |
 * | C6 | 打印组件加载不出来 ⇒ 给「sdk-unavailable」这条**专属**文案（不是一句"打印失败"） | 通用文案 ⇒ 红 |
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Taro from '@tarojs/taro'

const ORIGINAL_TARO_ENV = process.env.TARO_ENV
process.env.TARO_ENV = 'h5'

jest.mock('../src/utils/workerSession', () => ({
  hasWorkerSession: jest.fn(() => true),
  workerSessionHeaders: jest.fn(() => ({ 'X-Worker-Session-Id': 's1' })),
}))

jest.mock('../src/utils/inbound/barcodeDecode', () => ({
  decodeBarcodeFromPhoto: jest.fn(async () => ({ text: 'MG-1001', source: 'h5-dom-canvas', hint: '' })),
}))

jest.mock('../src/utils/inbound/lpapiTransport', () => ({
  loadLpapi: jest.fn(async () => null),
  createLpapiTransport: jest.fn(),
}))

jest.mock('../src/services/workerInboundService', () => ({
  newInboundRequestId: jest.fn(() => 'req-1'),
  uploadInboundPhoto: jest.fn(async () => ({ success: true, data: { url: 'https://oss/1.jpg' }, message: '' })),
  recognizeInbound: jest.fn(async () => ({
    success: true,
    message: '',
    data: {
      path: 'barcode_decode',
      barcode: 'MG-1001',
      degraded: false,
      requiresManualEntry: false,
      productName: '遮光布',
      colorName: '米白',
      quantityMeters: '60.5',
      skuMatches: [{ skuId: 9, productId: 'p1', productName: '遮光布', skuCode: 'MG-1001', colorName: '米白' }],
      message: '条码命中已有货号，请核对后填写米数。',
    },
  })),
  createInboundDraft: jest.fn(),
  postInboundDraft: jest.fn(),
  getInboundLabel: jest.fn(),
  recordInboundLabelPrint: jest.fn(),
}))

import WorkerInboundPage from '../src/pages/worker/inbound/index'
import { hasWorkerSession } from '../src/utils/workerSession'
import { PRINT_FAILURE_HINTS, PRINT_READY_HINT } from '../src/utils/inbound/printCapability'
import { INBOUND_WORKER_LOGIN_REQUIRED, WORKER_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import {
  createInboundDraft,
  postInboundDraft,
  getInboundLabel,
} from '../src/services/workerInboundService'

const mockHasWorkerSession = hasWorkerSession as jest.Mock
const mockChooseImage = Taro.chooseImage as jest.Mock
const mockShowModal = Taro.showModal as jest.Mock
const mockNavigateTo = Taro.navigateTo as jest.Mock
const mockCreateDraft = createInboundDraft as jest.Mock
const mockPostDraft = postInboundDraft as jest.Mock
const mockGetLabel = getInboundLabel as jest.Mock

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

/** 走到「标签」步（拍照 → 识别 → 确认 → 过账） */
async function driveToLabelStep() {
  mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:photo-a'], tempFiles: [{ originalFileObj: null }] })
  fireEvent.click(screen.getByTestId('inbound-pick'))
  await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
  fireEvent.click(screen.getByTestId('inbound-recognize'))
  await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())
  fireEvent.change(screen.getByTestId('inbound-quantity'), { target: { value: '60.5' } })
  fireEvent.click(screen.getByTestId('inbound-confirm-toggle'))
  fireEvent.click(screen.getByTestId('inbound-submit'))
}

describe('工人拍照入库页', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    process.env.TARO_ENV = 'h5'
    mockHasWorkerSession.mockReturnValue(true)
    mockShowModal.mockResolvedValue({ confirm: true, cancel: false })
    mockCreateDraft.mockResolvedValue({
      success: true,
      message: '',
      data: { draftId: 'd1', inboundNo: 'RK-20260927-0001', status: 'draft', items: [{ skuId: 9, shortCode: null }] },
    })
    mockPostDraft.mockResolvedValue({
      success: true,
      message: '',
      data: {
        draftId: 'd1',
        inboundNo: 'RK-20260927-0001',
        status: 'posted',
        items: [{ skuId: 9, skuCode: 'MG-1001', quantity: '60.5', shortCode: 'ABCD2345', printCount: 0 }],
      },
    })
    mockGetLabel.mockResolvedValue({
      success: true,
      message: '',
      data: { shortCode: 'ABCD2345', inboundNo: 'RK-20260927-0001', productName: '遮光布', quantity: '60.5' },
    })
    setPrintEnv({ ios: false })
  })

  afterAll(() => {
    process.env.TARO_ENV = ORIGINAL_TARO_ENV
  })

  it('C1 没有工人 session ⇒ 明说去登录（不渲染拍照入口、不静默跳走）', () => {
    mockHasWorkerSession.mockReturnValue(false)
    render(<WorkerInboundPage />)
    expect(screen.getByText(INBOUND_WORKER_LOGIN_REQUIRED)).toBeTruthy()
    expect(screen.queryByTestId('inbound-pick')).toBeNull()
    fireEvent.click(screen.getByTestId('inbound-go-worker-login'))
    expect(mockNavigateTo).toHaveBeenCalledWith({ url: WORKER_LOGIN_ROUTE })
  })

  it('C2 iOS 环境 ⇒ 一进页面（零操作）就说明「iPhone 打不了」，不是打完才失败', () => {
    setPrintEnv({ ios: true })
    render(<WorkerInboundPage />)
    const banner = screen.getByTestId('inbound-print-capability')
    expect(banner.textContent).toBe(PRINT_FAILURE_HINTS['ios-unsupported'])
    expect(banner.textContent).toContain('iPhone')
    // 零操作：没有调用任何服务端端点
    expect(mockCreateDraft).not.toHaveBeenCalled()
    expect(mockPostDraft).not.toHaveBeenCalled()
  })

  it('C2 非 HTTPS 环境 ⇒ 给出「安全上下文」那条专属文案', () => {
    setPrintEnv({ ios: false, secure: false })
    render(<WorkerInboundPage />)
    expect(screen.getByTestId('inbound-print-capability').textContent).toBe(
      PRINT_FAILURE_HINTS['insecure-context'],
    )
  })

  it('C2 安卓 Chrome 且 HTTPS ⇒ 显示正向提示（可打印）', () => {
    render(<WorkerInboundPage />)
    expect(screen.getByTestId('inbound-print-capability').textContent).toBe(PRINT_READY_HINT)
  })

  it('C3 h5 下不调 Taro.login（工人身份走工号 + PIN）', async () => {
    render(<WorkerInboundPage />)
    fireEvent.click(screen.getByTestId('inbound-pick'))
    await waitFor(() => expect(mockChooseImage).toHaveBeenCalled())
    expect(Taro.login).not.toHaveBeenCalled()
  })

  it('C4 过账二次确认：取消 ⇒ 一次都不建单、不调过账端点', async () => {
    mockShowModal.mockResolvedValueOnce({ confirm: false, cancel: true })
    render(<WorkerInboundPage />)
    await driveToLabelStep()
    await waitFor(() => expect(mockShowModal).toHaveBeenCalled())
    expect(mockCreateDraft).not.toHaveBeenCalled()
    expect(mockPostDraft).not.toHaveBeenCalled()
  })

  it('C5 米数留空 ⇒ 端侧先拦（不调建单端点）', async () => {
    render(<WorkerInboundPage />)
    mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:a'], tempFiles: [] })
    fireEvent.click(screen.getByTestId('inbound-pick'))
    await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
    fireEvent.click(screen.getByTestId('inbound-recognize'))
    await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())
    fireEvent.change(screen.getByTestId('inbound-quantity'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('inbound-confirm-toggle'))
    fireEvent.click(screen.getByTestId('inbound-submit'))
    await waitFor(() => expect(screen.getByTestId('inbound-error').textContent).toContain('请填写入库米数'))
    expect(mockCreateDraft).not.toHaveBeenCalled()
  })

  it('C5 服务端 400 的文案**原样上屏**（数量口径真值在服务端，端侧不重写第二份）', async () => {
    // 服务端 `InboundOrderService.requireItemNumbers` 的拒绝文案（本用例复刻它，断言"原样透出"）
    const SERVER_400 = '数量必须大于 0，最多 1 位小数（库存按 0.1 米粒度记）'
    mockCreateDraft.mockResolvedValueOnce({ success: false, message: SERVER_400 })
    render(<WorkerInboundPage />)
    mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:a'], tempFiles: [] })
    fireEvent.click(screen.getByTestId('inbound-pick'))
    await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
    fireEvent.click(screen.getByTestId('inbound-recognize'))
    await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())
    fireEvent.change(screen.getByTestId('inbound-quantity'), { target: { value: '2.755' } })
    fireEvent.click(screen.getByTestId('inbound-confirm-toggle'))
    fireEvent.click(screen.getByTestId('inbound-submit'))
    await waitFor(() => expect(screen.getByTestId('inbound-error').textContent).toBe(SERVER_400))
    // 建单被拒 ⇒ **不**继续过账（不产生"半张单"）
    expect(mockPostDraft).not.toHaveBeenCalled()
  })

  it('C4 确认过账 ⇒ 建单 + 过账 + 出标签；打印组件缺失时给专属文案', async () => {
    render(<WorkerInboundPage />)
    await driveToLabelStep()
    await waitFor(() => expect(screen.getByTestId('inbound-step-label')).toBeTruthy())
    expect(mockCreateDraft).toHaveBeenCalledTimes(1)
    expect(mockPostDraft).toHaveBeenCalledTimes(1)
    // 建单请求体里只有入库语义（无 adjustment / operator / tenantId）
    const body = mockCreateDraft.mock.calls[0][0]
    expect(Object.keys(body).sort()).toEqual(
      ['dyeLot', 'productId', 'quantity', 'remark', 'skuId', 'supplier', 'supplierDocNo'].sort(),
    )
    expect(body.quantity).toBe('60.5')
    // 短码出现在屏上（人可读，工人可抄）
    expect(screen.getByText(/ABCD2345/)).toBeTruthy()

    // 打印：能力可用但 SDK 加载失败 ⇒ sdk-unavailable 的**专属**文案（不是"打印失败"）
    fireEvent.click(screen.getByTestId('inbound-print'))
    await waitFor(() =>
      expect(screen.getByTestId('inbound-print-state').textContent).toBe(
        PRINT_FAILURE_HINTS['sdk-unavailable'],
      ),
    )
  })
})
