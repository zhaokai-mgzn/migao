// case_ids: BM-018, BM-019, BM-032
/**
 * 工人**拍照入库页**的行为判据（issue #5052 P3；验收判据 10 / 11 + 页面级联调；
 * 卷数 × 卷长口径改判见 issue #6812）
 *
 * | # | 判据 | 红证 |
 * |---|---|---|
 * | C1 | **身份分流**：没有工人 session ⇒ 明说去登录（不渲染拍照、不静默跳走） | 直接渲染拍照步 ⇒ 红 |
 * | C2 | **能力缺口动手前上屏**：iOS 环境下一进页面（**零操作**）就看到「iPhone 打不了」 | 只在打完失败后显示 ⇒ 红 |
 * | C3 | **h5 下不调 `Taro.login`**（工人身份走工号 + PIN） | 页面加 `Taro.login` ⇒ 红 |
 * | C4 | **过账二次确认**：点取消 ⇒ 一次都不建单；确认 ⇒ 建单 + 过账（不可逆动作的护栏） | 取消也提交 ⇒ 红 |
 * | C5 | 卷长非法/留空 ⇒ 端侧先拦（不白跑一次 422），文案取自**同一份**口径真值 | 静默放行 ⇒ 红 |
 * | C6 | 打印组件加载不出来 ⇒ 给「sdk-unavailable」这条**专属**文案（不是一句"打印失败"） | 通用文案 ⇒ 红 |
 * | C7 | **雪花号 id 逐字原样**（issue #6340）：SKU 选项与建单请求体里的 `skuId` 都是 `2106900122848247810`
 *        （> 2^53 = 9007199254740991）**字符串**，不得被 `Number()` 吞掉末两位 | 页面写回 `Number(chosenSku?.skuId)` ⇒ 红 |
 * | C8 | **两格数字（#6812）**：数量格 = **卷数**（默认 `1`）、卷长格 = **每卷米数**（识别到的米数落这里）；
 *        载荷 `quantity` + `rollLengthM`；确认文案把两格都念出来 | 米数仍进「数量」格 ⇒ 红（`quantity==='1'`、
 *        页面上取不到 `inbound-roll-length`、`body.quantity==='67.2'` 三条同时红） |
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

/** 🔴 真实量级雪花号（issue #6340 实测值，2.1e18 > 2^53）：玩具 id 测不出精度洞（#5904 的盲区成因） */
const REAL_SNOWFLAKE_SKU_ID = '2106900122848247810'

/** 后端识别回执里的「米数」：issue #6812 起它落进**卷长**那格（每卷米数），不再进「数量」格 */
const RECOGNIZED_METERS_PER_ROLL = '67.2'

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
      quantityMeters: RECOGNIZED_METERS_PER_ROLL,
      skuMatches: [{ skuId: REAL_SNOWFLAKE_SKU_ID, productId: 'p1', productName: '遮光布', skuCode: 'MG-1001', colorName: '米白' }],
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

/**
 * 走到「标签」步（拍照 → 识别 → 确认 → 过账）。
 * `rollLengthM` 缺省时**不覆盖**卷长格（保留识别预填值 / 空值），便于分别验两条路。
 */
async function driveToLabelStep({ rollLengthM }: { rollLengthM?: string } = {}) {
  mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:photo-a'], tempFiles: [{ originalFileObj: null }] })
  fireEvent.click(screen.getByTestId('inbound-pick'))
  await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
  fireEvent.click(screen.getByTestId('inbound-recognize'))
  await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())
  if (rollLengthM !== undefined) {
    fireEvent.change(screen.getByTestId('inbound-roll-length'), { target: { value: rollLengthM } })
  }
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
      data: { draftId: 'd1', inboundNo: 'RK-20260927-0001', status: 'draft', items: [{ skuId: REAL_SNOWFLAKE_SKU_ID, shortCode: null }] },
    })
    mockPostDraft.mockResolvedValue({
      success: true,
      message: '',
      data: {
        draftId: 'd1',
        inboundNo: 'RK-20260927-0001',
        status: 'posted',
        items: [{ skuId: REAL_SNOWFLAKE_SKU_ID, skuCode: 'MG-1001', quantity: RECOGNIZED_METERS_PER_ROLL, shortCode: 'ABCD2345', printCount: 0 }],
      },
    })
    mockGetLabel.mockResolvedValue({
      success: true,
      message: '',
      data: { shortCode: 'ABCD2345', inboundNo: 'RK-20260927-0001', productName: '遮光布', quantity: RECOGNIZED_METERS_PER_ROLL },
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

  it('C5 卷长留空 ⇒ 端侧先拦（不调建单端点），且文案说清缺的是哪一格', async () => {
    render(<WorkerInboundPage />)
    mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:a'], tempFiles: [] })
    fireEvent.click(screen.getByTestId('inbound-pick'))
    await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
    fireEvent.click(screen.getByTestId('inbound-recognize'))
    await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())
    fireEvent.change(screen.getByTestId('inbound-roll-length'), { target: { value: '' } })
    fireEvent.click(screen.getByTestId('inbound-confirm-toggle'))
    fireEvent.click(screen.getByTestId('inbound-submit'))
    await waitFor(() => expect(screen.getByTestId('inbound-error').textContent).toContain('请填写卷长'))
    expect(mockCreateDraft).not.toHaveBeenCalled()
  })

  it('C5 服务端 400/422 的文案**原样上屏**（口径真值在服务端，端侧不重写第二份）', async () => {
    // 服务端对「米数不是 0.1 的整数倍」这类载荷的拒绝文案（本用例复刻它，断言"原样透出"）
    const SERVER_422 = '卷长最多 2 位小数，且入库米数（卷数 × 卷长）必须是 0.1 米的整数倍'
    mockCreateDraft.mockResolvedValueOnce({ success: false, message: SERVER_422 })
    render(<WorkerInboundPage />)
    mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:a'], tempFiles: [] })
    fireEvent.click(screen.getByTestId('inbound-pick'))
    await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
    fireEvent.click(screen.getByTestId('inbound-recognize'))
    await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())
    // 🔴 端侧**不拦**这一条（0.1 粒度是服务端口径）⇒ 必须真的发出去、把服务端文案原样带回
    fireEvent.change(screen.getByTestId('inbound-roll-length'), { target: { value: '2.755' } })
    fireEvent.click(screen.getByTestId('inbound-confirm-toggle'))
    fireEvent.click(screen.getByTestId('inbound-submit'))
    await waitFor(() => expect(screen.getByTestId('inbound-error').textContent).toBe(SERVER_422))
    // 建单被拒 ⇒ **不**继续过账（不产生"半张单"）
    expect(mockPostDraft).not.toHaveBeenCalled()
  })

  it('C8 卷数默认 1、识别到的米数落进卷长；确认文案把两格都说清（#6812）', async () => {
    render(<WorkerInboundPage />)
    mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:a'], tempFiles: [] })
    fireEvent.click(screen.getByTestId('inbound-pick'))
    await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
    fireEvent.click(screen.getByTestId('inbound-recognize'))
    await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())

    // 卷数格 = 默认 `1`（**不是**识别到的 67.2 —— 这正是旧口径的形态）
    expect((screen.getByTestId('inbound-quantity') as HTMLInputElement).value).toBe('1')
    // 识别到的米数落在**卷长**格
    expect((screen.getByTestId('inbound-roll-length') as HTMLInputElement).value).toBe(RECOGNIZED_METERS_PER_ROLL)

    fireEvent.click(screen.getByTestId('inbound-confirm-toggle'))
    fireEvent.click(screen.getByTestId('inbound-submit'))
    await waitFor(() => expect(mockShowModal).toHaveBeenCalled())

    // 确认文案必须把两格都念出来（只说一格 ⇒ 工人确认的是自己没看到的数）
    const confirmText = String(mockShowModal.mock.calls[0][0]?.content || '')
    expect(confirmText).toContain(`${RECOGNIZED_METERS_PER_ROLL} 米/卷`)
    expect(confirmText).toContain('1 卷')
    // 🔴 端侧只念两格、**不做乘积**（真值在服务端；端侧再算一份就是第二份会漂的口径）
    expect(confirmText).not.toContain('合计')

    await waitFor(() => expect(mockCreateDraft).toHaveBeenCalled())
    const body = mockCreateDraft.mock.calls[0][0]
    expect(body.quantity).toBe('1')
    expect(body.rollLengthM).toBe(RECOGNIZED_METERS_PER_ROLL)
  })

  it('C8 识别不到米数（降级）⇒ 卷长格留空、卷数仍是默认 1，且不预填品名', async () => {
    const { recognizeInbound } = require('../src/services/workerInboundService')
    ;(recognizeInbound as jest.Mock).mockResolvedValueOnce({
      success: true,
      message: '识别不确定，请手工录入',
      data: {
        path: 'vision',
        degraded: true,
        requiresManualEntry: true,
        productName: '遮光布',
        colorName: '米白',
        quantityMeters: RECOGNIZED_METERS_PER_ROLL,
        skuMatches: [{ skuId: REAL_SNOWFLAKE_SKU_ID, productId: 'p1', skuCode: 'MG-1001', colorName: '米白' }],
        message: '识别不确定，请手工录入',
      },
    })
    render(<WorkerInboundPage />)
    mockChooseImage.mockResolvedValueOnce({ tempFilePaths: ['blob:a'], tempFiles: [] })
    fireEvent.click(screen.getByTestId('inbound-pick'))
    await waitFor(() => expect(screen.getByTestId('inbound-recognize')).toBeTruthy())
    fireEvent.click(screen.getByTestId('inbound-recognize'))
    await waitFor(() => expect(screen.getByTestId('inbound-step-confirm')).toBeTruthy())

    expect((screen.getByTestId('inbound-roll-length') as HTMLInputElement).value).toBe('')
    expect((screen.getByTestId('inbound-quantity') as HTMLInputElement).value).toBe('1')
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
      ['dyeLot', 'productId', 'quantity', 'remark', 'rollLengthM', 'skuId', 'supplier', 'supplierDocNo'].sort(),
    )
    // 卷数 × 卷长：数量格是**卷数**（默认 1），米数在 rollLengthM（#6812）
    expect(body.quantity).toBe('1')
    expect(body.rollLengthM).toBe(RECOGNIZED_METERS_PER_ROLL)
    // C7（#6340 靶心）：雪花号 id **逐字原样字符串**回传；`Number()` 会吞末两位 ⇒ 服务端查不到该 SKU
    expect(body.skuId).toBe(REAL_SNOWFLAKE_SKU_ID)
    expect(String(body.skuId)).toBe('2106900122848247810')
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
