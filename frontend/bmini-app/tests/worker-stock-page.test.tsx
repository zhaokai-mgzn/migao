// case_ids: BM-056, BM-034
/**
 * 工人**库存修正**页（issue #8104；页面 = `src/pages/worker/stock/index.tsx`）
 *
 * 数据源：`GET /api/worker/batch-stock/batches`（搜批次 + 原因闭词表）+
 * `POST /api/worker/batch-stock/correction`（提交修正，幂等键 `client_request_id`）。
 *
 * ## 判据（每条都能单独变红）
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | ① | 🔴 **未登录 ⇒ 只渲染引导 + 去工人登录**，一个读 / 写请求都不发 | 把 gate 去掉 ⇒ 无 session 也发搜索请求，红 |
 * | ② | 登录后**页头工人来自服务端**（不是本机拼），批次行显示系统余量 + 品名/货号/缸号 | 用本机缓存的名字 ⇒ 红 |
 * | ③ | 选中批次 ⇒ 修正面板 + 原因**来自服务端**（端侧不写第二份选项），默认选第一个 | 端侧硬编码原因列表 ⇒ 服务端多/少一项时红 |
 * | ④ | 🔴 **提交前二次确认**，文案里同时有「系统读数」和「实盘读数」；取消 ⇒ 一个写请求都不发 | 去掉 `showModal` ⇒ 红 |
 * | ⑤ | 🔴 **提交体是白名单**（camelCase：`batchId` / `actualMeters` / `reason` / `note` / `clientRequestId`）；**没有** workerId / workerName | 把身份塞进 body ⇒ 红 |
 * | ⑥ | **回执四数上屏** + 三态分开说；零差异（unchanged）明说「未写入」 | 三态并成一句 ⇒ 红 |
 * | ⑦ | 🔴 **幂等**：同一份输入重试 ⇒ 同一个 `clientRequestId`；改了输入再提交 ⇒ 换新键 | 每次提交都新生成 ⇒ 重试双记，红 |
 * | ⑧ | **校验先于请求**：空 / 负数 / 2 位小数 ⇒ 不发请求 + 可行动文案 | 放行 `-1` ⇒ 红 |
 * | ⑨ | 🔴 **401 单独一态**：会话失效 ⇒ 引导登录（清本机工人身份），不是「读不到」/「没有批次」 | 把 401 当空态 ⇒ 红 |
 * | ⑩ | **空态 / 读失败互斥**：空结果给「换个关键词」，读失败给「重试」；点重试会再读一次 | 两者共用一个态 ⇒ 红 |
 * | ⑪ | 🔴 **拍照识别入口（issue #8210）**：扫标签二维码优先（0 次 LLM）→ vision 兜底 → 手输；认出批次号后**自动定位并打开修正面板**，提交仍要工人自己来 | 把 vision 排到扫码前 ⇒ ⑬ 的调用计数红 |
 * | ⑫ | **认出来但没这个批次** ⇒ 说「没找到批次 X」（不是空态、不是读失败） | 复用空态文案 ⇒ ⑭ 红 |
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      navigateTo: jest.fn(() => Promise.resolve()),
      redirectTo: jest.fn(() => Promise.resolve()),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      getCurrentInstance: jest.fn(() => ({ router: { params: {} } })),
      showModal: jest.fn(() => Promise.resolve({ confirm: true, cancel: false })),
      // 拍照 / 选图（h5 与小程序同 API；识别入口的两个兜底都从这里拿图）
      chooseImage: jest.fn(() => Promise.resolve({ tempFilePaths: ['/tmp/label.jpg'] })),
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/workerService', () => ({
  fetchCurrentWorker: jest.fn(),
  workerLogout: jest.fn(),
}))

jest.mock('../src/services/workerStockService', () => ({
  searchStockBatches: jest.fn(),
  submitBatchCorrection: jest.fn(),
  recognizeBatchNo: jest.fn(),
}))

// 识别入口的四个依赖（页面只接线；顺序与降级判据在 utils/workerStockRecognize 的纯函数里钉）
jest.mock('../src/utils/inbound/barcodeDecode', () => ({
  decodeBarcodeFromPhoto: jest.fn(),
}))
jest.mock('../src/services/workerInboundService', () => ({
  getInboundLabel: jest.fn(),
  uploadInboundPhoto: jest.fn(),
  uploadInboundPhotoSmart: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerStockPage, { EMPTY_HINT } from '../src/pages/worker/stock/index'
import { fetchCurrentWorker } from '../src/services/workerService'
import {
  recognizeBatchNo,
  searchStockBatches,
  submitBatchCorrection,
} from '../src/services/workerStockService'
import { getInboundLabel, uploadInboundPhotoSmart } from '../src/services/workerInboundService'
import { decodeBarcodeFromPhoto } from '../src/utils/inbound/barcodeDecode'
import { STOCK_RECOGNIZE_MANUAL_HINT } from '../src/utils/workerStockRecognize'
import { STOCK_WORKER_LOGIN_REQUIRED, WORKER_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import { clearWorkerSession, getWorkerSessionId, setWorkerSessionId } from '../src/utils/workerSession'
import type { CorrectionReceipt, StockBatchRow } from '../src/utils/workerStock'

const mockFetchWorker = fetchCurrentWorker as jest.Mock
const mockSearch = searchStockBatches as jest.Mock
const mockSubmit = submitBatchCorrection as jest.Mock
const mockRecognize = recognizeBatchNo as jest.Mock
const mockDecode = decodeBarcodeFromPhoto as jest.Mock
const mockUpload = uploadInboundPhotoSmart as jest.Mock
const mockLabel = getInboundLabel as jest.Mock
const mockChooseImage = Taro.chooseImage as jest.Mock
const mockShowModal = Taro.showModal as jest.Mock
const mockNavigateTo = Taro.navigateTo as jest.Mock

const WORKER = {
  session_id: 'sess-worker-1',
  worker_id: 'w-1',
  worker_no: 'CY-1001',
  worker_name: '张三',
}

const ROW: StockBatchRow = {
  batch_id: 7,
  batch_no: 'PC-20261020-0007',
  product_id: 'prod-1',
  product_name: '雪尼尔窗帘布',
  sku_code: '2659-04-28',
  dye_lot: 'A12',
  inbound_no: 'RK-20261020-0001',
  received_date: '2026-10-20',
  remaining_meters: 45.5,
}

const REASONS = [
  { code: 'miscount', label: '数量记错了' },
  { code: 'damaged', label: '破损 / 报废' },
  { code: 'wrong_batch', label: '报工选错批次' },
  { code: 'other', label: '其他' },
]

function receipt(overrides: Partial<CorrectionReceipt> = {}): CorrectionReceipt {
  return {
    run_id: 'wc-req-1',
    batch_id: 7,
    batch_no: 'PC-20261020-0007',
    product_name: '雪尼尔窗帘布',
    sku_code: '2659-04-28',
    status: 'applied',
    before_meters: 45.5,
    actual_meters: 42,
    delta_meters: -3.5,
    after_meters: 42,
    worker_name: '张三',
    worker_no: 'CY-1001',
    ...overrides,
  }
}

async function renderLoggedIn() {
  setWorkerSessionId('sess-worker-1')
  render(<WorkerStockPage />)
  await screen.findByTestId('worker-stock-row-0')
}

async function selectAndFill(meters: string) {
  fireEvent.click(screen.getByTestId('worker-stock-row-0'))
  await screen.findByTestId('worker-stock-panel')
  fireEvent.change(screen.getByTestId('worker-stock-meters'), { target: { value: meters } })
}

beforeEach(() => {
  jest.clearAllMocks()
  clearWorkerSession()
  mockFetchWorker.mockResolvedValue({ success: true, data: WORKER })
  mockSearch.mockResolvedValue({
    success: true,
    data: { items: [ROW], total: 1, page: 1, size: 20, reasons: REASONS },
  })
  mockSubmit.mockResolvedValue({ success: true, data: receipt() })
  mockShowModal.mockResolvedValue({ confirm: true, cancel: false })
  // 识别入口的默认替身：没解出码 + 没认出来 ⇒ 走「手输」兜底（各用例按需覆盖）
  mockChooseImage.mockResolvedValue({ tempFilePaths: ['/tmp/label.jpg'] })
  mockDecode.mockResolvedValue({ text: null, source: null, hint: '' })
  mockUpload.mockResolvedValue({ success: true, data: { url: 'https://cdn.example.com/label.jpg' } })
  mockLabel.mockResolvedValue({ success: true, data: { batchNo: null } })
  mockRecognize.mockResolvedValue({ success: true, data: { fields: [], degraded: true } })
})

// ═══════════════════════════════════════════════════ ① 未登录

it('① 无工人身份 ⇒ 只渲染引导 + 去登录；一个搜索 / 提交请求都不发', async () => {
  render(<WorkerStockPage />)

  const gate = await screen.findByTestId('worker-stock-gate')
  expect(gate.textContent).toContain(STOCK_WORKER_LOGIN_REQUIRED)
  expect(mockSearch).not.toHaveBeenCalled()
  expect(mockSubmit).not.toHaveBeenCalled()

  fireEvent.click(screen.getByText('去登录工人身份'))
  expect(mockNavigateTo).toHaveBeenCalledWith({ url: WORKER_LOGIN_ROUTE })
})

// ═══════════════════════════════════════════════════ ② 列表

it('② 登录后：页头工人来自服务端 + 批次行显示批次号 / 品名货号缸号 / 系统余量', async () => {
  await renderLoggedIn()

  await waitFor(() => {
    expect(screen.getByTestId('worker-stock-worker').textContent).toContain('张三')
    expect(screen.getByTestId('worker-stock-worker').textContent).toContain('CY-1001')
  })
  // 首屏 = 空关键词（最近入库的批次）
  expect(mockSearch).toHaveBeenCalledWith('')
  expect(screen.getByTestId('worker-stock-batch-no-0').textContent).toBe('PC-20261020-0007')
  expect(screen.getByTestId('worker-stock-row-meta-0').textContent).toContain('雪尼尔窗帘布')
  expect(screen.getByTestId('worker-stock-remaining-0').textContent).toContain('45.5')
})

// ═══════════════════════════════════════════════════ ③ 选中 ⇒ 面板

it('③ 选中批次 ⇒ 面板出现；原因来自服务端（四选一，默认第一个）', async () => {
  await renderLoggedIn()
  fireEvent.click(screen.getByTestId('worker-stock-row-0'))

  const panel = await screen.findByTestId('worker-stock-panel')
  expect(panel.textContent).toContain('PC-20261020-0007')
  expect(screen.getByTestId('worker-stock-before').textContent).toContain('45.5')
  for (const reason of REASONS) {
    expect(screen.getByTestId(`worker-stock-reason-${reason.code}`).textContent).toBe(reason.label)
  }
  // 默认预选第一个原因（工人少点一次；仍可改）
  expect(screen.getByTestId('worker-stock-reason-miscount').className).toContain('--active')
})

// ═══════════════════════════════════════════════════ ④⑤⑥ 提交

it('④ 提交前二次确认：文案同时含系统读数与实盘读数；确认后提交体是白名单 + 回执四数上屏', async () => {
  await renderLoggedIn()
  await selectAndFill('42.5')
  fireEvent.click(screen.getByTestId('worker-stock-reason-damaged'))
  fireEvent.click(screen.getByTestId('worker-stock-submit'))

  await waitFor(() => expect(mockShowModal).toHaveBeenCalledTimes(1))
  const content = String(mockShowModal.mock.calls[0][0].content)
  expect(content).toContain('45.5') // 系统读数
  expect(content).toContain('42.5') // 实盘读数

  await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1))
  const body = mockSubmit.mock.calls[0][0]
  expect(Object.keys(body).sort()).toEqual(
    ['actualMeters', 'batchId', 'clientRequestId', 'reason'].sort(),
  )
  expect(body.batchId).toBe(7)
  expect(body.actualMeters).toBe(42.5)
  expect(body.reason).toBe('damaged')
  expect(typeof body.clientRequestId).toBe('string')
  expect(body.clientRequestId.length).toBeGreaterThan(0)
  expect(body).not.toHaveProperty('workerId')
  expect(body).not.toHaveProperty('workerName')

  const receiptCard = await screen.findByTestId('worker-stock-receipt')
  expect(receiptCard.textContent).toContain('已修正')
  expect(screen.getByTestId('worker-stock-receipt-before').textContent).toContain('45.5')
  expect(screen.getByTestId('worker-stock-receipt-actual').textContent).toContain('42')
  expect(screen.getByTestId('worker-stock-receipt-delta').textContent).toContain('-3.5')
  expect(screen.getByTestId('worker-stock-receipt-after').textContent).toContain('42')
})

it('⑤ 确认框点「再检查一下」⇒ 一个写请求都不发', async () => {
  await renderLoggedIn()
  await selectAndFill('42')
  mockShowModal.mockResolvedValue({ confirm: false, cancel: true })

  fireEvent.click(screen.getByTestId('worker-stock-submit'))
  await waitFor(() => expect(mockShowModal).toHaveBeenCalledTimes(1))
  expect(mockSubmit).not.toHaveBeenCalled()
})

it('⑥ 零差异（unchanged）⇒ 明说「未写入任何变更」；列表余量按回执回写', async () => {
  mockSubmit.mockResolvedValue({
    success: true,
    data: receipt({
      status: 'unchanged',
      before_meters: 42,
      actual_meters: 42,
      delta_meters: 0,
      after_meters: 42,
    }),
  })
  await renderLoggedIn()
  await selectAndFill('42')
  fireEvent.click(screen.getByTestId('worker-stock-submit'))

  const receiptCard = await screen.findByTestId('worker-stock-receipt')
  expect(receiptCard.textContent).toContain('与系统一致')
  expect(receiptCard.textContent).toContain('未写入')
  await waitFor(() =>
    expect(screen.getByTestId('worker-stock-remaining-0').textContent).toContain('42'),
  )
})

// ═══════════════════════════════════════════════════ ⑦ 幂等

it('⑦ 同一份输入重试 ⇒ 复用同一个 client_request_id；改了米数再提交 ⇒ 换新键', async () => {
  mockSubmit
    .mockResolvedValueOnce({ success: false, message: '网络超时，请重试' })
    .mockResolvedValue({ success: true, data: receipt() })

  await renderLoggedIn()
  await selectAndFill('42')
  fireEvent.click(screen.getByTestId('worker-stock-submit'))
  await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(1))
  const firstKey = mockSubmit.mock.calls[0][0].clientRequestId

  // 同一份输入，再点一次 ⇒ 幂等键必须一致（服务端按回放处理，不双记）
  fireEvent.click(screen.getByTestId('worker-stock-submit'))
  await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(2))
  expect(mockSubmit.mock.calls[1][0].clientRequestId).toBe(firstKey)

  // 改了米数 ⇒ 这是一次**新的**提交 ⇒ 新键（否则服务端按上一次回放、静默不落账）
  fireEvent.change(screen.getByTestId('worker-stock-meters'), { target: { value: '40' } })
  fireEvent.click(screen.getByTestId('worker-stock-submit'))
  await waitFor(() => expect(mockSubmit).toHaveBeenCalledTimes(3))
  expect(mockSubmit.mock.calls[2][0].clientRequestId).not.toBe(firstKey)
})

// ═══════════════════════════════════════════════════ ⑧ 校验先于请求

it.each([
  ['', '请填实盘米数'],
  ['-1', '只能填数字'],
  ['42.55', '1 位小数'],
])('⑧ 实盘米数 = %s ⇒ 不发写请求，提示「%s」', async (meters, hint) => {
  await renderLoggedIn()
  await selectAndFill(meters)
  fireEvent.click(screen.getByTestId('worker-stock-submit'))

  await waitFor(() => expect(screen.getByTestId('worker-stock-message').textContent).toContain(hint))
  expect(mockShowModal).not.toHaveBeenCalled()
  expect(mockSubmit).not.toHaveBeenCalled()
})

// ═══════════════════════════════════════════════════ ⑨ 401

it('⑨ 搜索 401 ⇒ 引导登录（清本机工人身份），不是空态 / 读失败态', async () => {
  setWorkerSessionId('sess-worker-1')
  mockSearch.mockResolvedValue({ success: false, statusCode: 401, message: '工人身份已失效' })

  render(<WorkerStockPage />)

  expect(await screen.findByTestId('worker-stock-gate')).toBeTruthy()
  expect(getWorkerSessionId()).toBeNull()
  expect(screen.queryByTestId('worker-stock-empty')).toBeNull()
  expect(screen.queryByTestId('worker-stock-error')).toBeNull()
})

// ═══════════════════════════════════════════════════ ⑩ 空态 / 读失败

it('⑩ 空结果 ⇒ 「换个关键词」（不是读失败态）', async () => {
  setWorkerSessionId('sess-worker-1')
  mockSearch.mockResolvedValue({ success: true, data: { items: [], reasons: REASONS } })

  render(<WorkerStockPage />)

  const empty = await screen.findByTestId('worker-stock-empty')
  expect(empty.textContent).toContain(EMPTY_HINT)
  expect(screen.queryByTestId('worker-stock-row-0')).toBeNull()
  expect(screen.queryByTestId('worker-stock-error')).toBeNull()
})

it('⑪ 读失败 ⇒ 「重试」态；点重试会再读一次并渲染出行（与空态互斥）', async () => {
  setWorkerSessionId('sess-worker-1')
  mockSearch
    .mockResolvedValueOnce({ success: false, message: '读取失败，请重试' })
    .mockResolvedValueOnce({ success: true, data: { items: [ROW], reasons: REASONS } })

  render(<WorkerStockPage />)

  await screen.findByTestId('worker-stock-error')
  expect(screen.queryByTestId('worker-stock-empty')).toBeNull()

  fireEvent.click(screen.getByTestId('worker-stock-retry'))
  await waitFor(() => expect(screen.getByTestId('worker-stock-row-0')).toBeTruthy())
  expect(screen.queryByTestId('worker-stock-error')).toBeNull()
  expect(mockSearch).toHaveBeenCalledTimes(2)
})

// ═══════════════════════════════════════════════════ ⑫⑬ 拍照识别批次号（issue #8210）

it('⑫ 解不出码 ⇒ 走 vision 兜底；认出批次号后自动定位并打开修正面板（提交仍要工人自己来）', async () => {
  mockRecognize.mockResolvedValue({
    success: true,
    data: {
      targetType: 'batch',
      fields: [{ key: 'batch_no', value: 'PC-20261020-0007', source: '[图片识别]' }],
      degraded: false,
    },
  })
  await renderLoggedIn()

  fireEvent.click(screen.getByTestId('worker-stock-recognize'))

  // 面板自动打开（工人只需填实盘米数 —— 识别只做定位）
  const panel = await screen.findByTestId('worker-stock-panel')
  expect(panel.textContent).toContain('PC-20261020-0007')
  expect(mockChooseImage).toHaveBeenCalled()
  expect(mockUpload).toHaveBeenCalledTimes(1)
  expect(mockRecognize).toHaveBeenCalledTimes(1)
  expect(mockRecognize.mock.calls[0][0]).toEqual(['https://cdn.example.com/label.jpg'])
  // 定位走**既有**搜索面（不新造读端点）：关键词 = 识别出来的批次号
  expect(mockSearch).toHaveBeenCalledWith('PC-20261020-0007')
  // 识别**不提交**：提交仍是工人动作
  expect(mockSubmit).not.toHaveBeenCalled()
})

it('⑬ 标签二维码命中 ⇒ 0 次 LLM（不上传、不问 vision），批次号从标签详情来', async () => {
  mockDecode.mockResolvedValue({
    text: 'https://app.migaozn.com/i/7K3M9QP2',
    source: 'h5-dom-canvas',
    hint: '',
  })
  mockLabel.mockResolvedValue({ success: true, data: { batchNo: 'PC-20261020-0007' } })
  await renderLoggedIn()

  fireEvent.click(screen.getByTestId('worker-stock-recognize'))

  const panel = await screen.findByTestId('worker-stock-panel')
  expect(panel.textContent).toContain('PC-20261020-0007')
  expect(mockLabel).toHaveBeenCalledWith('7K3M9QP2')
  expect(mockUpload).not.toHaveBeenCalled()
  expect(mockRecognize).not.toHaveBeenCalled()
})

it('⑭ 认出来但本企业没有这个批次 ⇒ 明说「没找到批次 X」（不是空态、不是读失败）', async () => {
  mockRecognize.mockResolvedValue({
    success: true,
    data: {
      targetType: 'batch',
      fields: [{ key: 'batch_no', value: 'PC-20261031-9999', source: '[图片识别]' }],
      degraded: false,
    },
  })
  mockSearch.mockResolvedValue({ success: true, data: { items: [], total: 0, reasons: REASONS } })
  setWorkerSessionId('sess-worker-1')
  render(<WorkerStockPage />)
  await screen.findByTestId('worker-stock-empty')

  fireEvent.click(screen.getByTestId('worker-stock-recognize'))

  await waitFor(() =>
    expect(screen.getByTestId('worker-stock-message').textContent).toContain('没找到批次'),
  )
  expect(screen.getByTestId('worker-stock-message').textContent).toContain('PC-20261031-9999')
  expect(screen.getByTestId('worker-stock-message').textContent).toContain('手输')
  expect(screen.queryByTestId('worker-stock-panel')).toBeNull()
})

it('⑮ 没认出来 ⇒ 给手输出路（不静默），且不发写请求', async () => {
  setWorkerSessionId('sess-worker-1')
  render(<WorkerStockPage />)
  await screen.findByTestId('worker-stock-row-0')

  fireEvent.click(screen.getByTestId('worker-stock-recognize'))

  await waitFor(() =>
    expect(screen.getByTestId('worker-stock-message').textContent).toContain(
      STOCK_RECOGNIZE_MANUAL_HINT,
    ),
  )
  expect(screen.queryByTestId('worker-stock-panel')).toBeNull()
  expect(mockSubmit).not.toHaveBeenCalled()
})
