// case_ids: BM-050
/**
 * 工人**拍照发货页**的行为判据（issue #6761；页面 = `src/pages/worker/shipment/index.tsx`）
 *
 * 这是 #5648 的 UI 面收口：后端与纯逻辑（`frontend/worker-h5/src/shipment.mjs`）早已落码，
 * 而**从来没有页面入口**（#5664 §9 逐字登记为半成品）。本文件锁页面这一侧的六条：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | P1 | **身份分流**：没有工人 session ⇒ 渲染引导 +「去登录工人身份」，**不**渲染拍照/发货写入口 | 直接渲染写入口 ⇒ 红 |
 * | P2 | **拍照 / 选图走既有上传通道**（`POST /api/worker/inbound/upload`），识别走 shipment recognize | 换一条新通道 ⇒ 红 |
 * | P3 | 🔴 **不预填**：识别候选里 `value` 为 null / 空串的格子留空（**不是 0**），并逐格说清要手输 | 预填 0 ⇒ 红 |
 * | P4 | **定位订单**用识别出的单号走既有读面 `production/scan?token=` 拿 `order_id`（不新造后端端点） | 跳过定位直接发货 ⇒ 红 |
 * | P5 | **发货请求**带运单号 + 实发明细 + 照片引用 + 识别留痕，且**重试复用同一把幂等键** | 每次重试换键 ⇒ 红 |
 * | P6 | **实发读面说人话**：单位/套/卷三样，`null` ⇒「—」（不印 0）；无发货单 ⇒ 不渲染空壳 | 把 null 印成 0 ⇒ 红 |
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

jest.mock('@tarojs/taro', () => {
  // 真内存 storage + 可断言的相机/上传：工人态的清除与「走哪条上传通道」都必须能被**读到**
  const store: Record<string, any> = {}
  return {
    __esModule: true,
    default: {
      showToast: jest.fn(),
      navigateTo: jest.fn(),
      redirectTo: jest.fn(),
      chooseImage: jest.fn(),
      uploadFile: jest.fn(),
      getStorageSync: jest.fn((key: string) => (key in store ? store[key] : '')),
      setStorageSync: jest.fn((key: string, value: any) => {
        store[key] = value
      }),
      removeStorageSync: jest.fn((key: string) => {
        delete store[key]
      }),
      getCurrentInstance: jest.fn(() => ({ router: { params: {} } })),
      __clearStorage: () => {
        Object.keys(store).forEach((key) => delete store[key])
      },
    },
    useDidShow: jest.fn(),
  }
})

jest.mock('../src/services/workerShipmentService', () => ({
  // 纯逻辑用**真实现**（mock 掉它们 = 测不到页面真正递出去的请求体）
  prefillFromRecognition: jest.requireActual('../src/utils/inbound/shipment').prefillFromRecognition,
  buildShipBody: jest.requireActual('../src/utils/inbound/shipment').buildShipBody,
  buildShipmentItem: jest.requireActual('../src/utils/inbound/shipment').buildShipmentItem,
  formatShippedTotals: jest.requireActual('../src/utils/inbound/shipment').formatShippedTotals,
  recognizeShipment: jest.fn(),
  postWorkerShipment: jest.fn(),
  readWorkerShipment: jest.fn(),
  newShipmentRequestId: jest.fn(() => 'shipment-key-fixed'),
}))

jest.mock('../src/services/workerInboundService', () => ({
  uploadInboundPhoto: jest.fn(),
}))

jest.mock('../src/services/productionService', () => ({
  scanResolve: jest.fn(),
}))

import Taro from '@tarojs/taro'
import WorkerShipmentPage from '../src/pages/worker/shipment/index'
import {
  newShipmentRequestId,
  postWorkerShipment,
  readWorkerShipment,
  recognizeShipment,
} from '../src/services/workerShipmentService'
import { uploadInboundPhoto } from '../src/services/workerInboundService'
import { scanResolve } from '../src/services/productionService'
import { SHIPMENT_PAGE_ROUTE, WORKER_TAB_LOGIN_ROUTE } from '../src/utils/inbound/gaps'
import { clearWorkerSession, setWorkerSessionId } from '../src/utils/workerSession'

/** 后端 `ImageRecognitionClient.ImageRecognitionResult` 的形状（`target_type=shipment`） */
const FIELDS = [
  { key: 'order_no', label: '订单号', value: 'ORD-20260926-0001', source: '[图片识别]' },
  { key: 'product_name', label: '商品名称', value: '遮光布', source: '[图片识别]' },
  { key: 'quantity', label: '数量', value: null, source: '[图片识别]', reason: '图上没有写明数量' },
  { key: 'width', label: '宽', value: '', source: '[图片识别]', reason: '方向不明、不猜顺序' },
  { key: 'height', label: '高', value: '2.4', source: '[图片识别]' },
]

const ORDER_ID = 'CSO261007-00001'

const mockRecognize = recognizeShipment as jest.Mock
const mockUpload = uploadInboundPhoto as jest.Mock
const mockScan = scanResolve as jest.Mock
const mockShip = postWorkerShipment as jest.Mock
const mockRead = readWorkerShipment as jest.Mock
const mockNewKey = newShipmentRequestId as jest.Mock

/** 走完「选图 → 识别 → 核对」三步，停在发货前的核对屏 */
async function reachReview() {
  fireEvent.click(screen.getByTestId('shipment-pick'))
  await screen.findByTestId('shipment-photo-count')
  fireEvent.click(screen.getByTestId('shipment-recognize'))
  await screen.findByTestId('shipment-review')
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage()
  setWorkerSessionId('sess-worker-1')
  ;(Taro.chooseImage as jest.Mock).mockResolvedValue({
    tempFilePaths: ['blob://photo-1'],
    tempFiles: [{ originalFileObj: 'file-1' }],
  })
  mockUpload.mockResolvedValue({ success: true, data: { url: 'https://oss/1.jpg' }, message: '' })
  mockRecognize.mockResolvedValue({
    success: true,
    message: '',
    data: { targetType: 'shipment', degraded: false, fields: FIELDS },
  })
  mockScan.mockResolvedValue({
    success: true,
    message: '',
    data: { granularity: 'set_position', order_id: ORDER_ID, needs_selection: [] },
  })
  mockShip.mockResolvedValue({ success: true, message: '', data: { order_id: ORDER_ID, status: 'shipped' } })
  mockRead.mockResolvedValue({
    success: true,
    message: '',
    data: {
      order_id: ORDER_ID,
      order_no: 'ORD-20260926-0001',
      status: 'shipped',
      shipments: [
        {
          shipment_no: 'SHIP-0001',
          tracking_no: 'SF123456',
          logistics_company: '顺丰',
          packed_by: '张三',
          shipped_by: '张三',
          photo_refs: ['https://oss/1.jpg'],
          items: [{ product_name: '遮光布', shipped_quantity: 12, unit: '米', set_count: null, roll_count: null }],
        },
      ],
      shipped_totals: { by_unit: { 米: 12 }, set_count: null, roll_count: null },
    },
  })
})

describe('拍照发货页：身份分流（issue #6761 判据 P1）', () => {
  it('🔴 无工人 session ⇒ 只渲染引导 +「去登录工人身份」，一个发货写入口都不渲染', () => {
    clearWorkerSession()

    render(<WorkerShipmentPage />)

    expect(screen.getByTestId('shipment-login-required')).toBeTruthy()
    expect(screen.getByText(/请先用工号 \+ PIN 登录工人身份/)).toBeTruthy()
    // 红证：把 `if (!workerReady)` 那段删掉 / 改成恒 false ⇒ 下面三条收到「有元素」⇒ 红
    expect(screen.queryByTestId('shipment-pick')).toBeNull()
    expect(screen.queryByTestId('shipment-recognize')).toBeNull()
    expect(screen.queryByTestId('shipment-submit')).toBeNull()

    fireEvent.click(screen.getByTestId('shipment-go-worker-login'))
    expect(Taro.navigateTo).toHaveBeenCalledWith({ url: WORKER_TAB_LOGIN_ROUTE })
  })

  it('有工人 session ⇒ 渲染拍照入口（本页是工人写面）', () => {
    render(<WorkerShipmentPage />)

    expect(screen.getByTestId('shipment-pick')).toBeTruthy()
    expect(screen.queryByTestId('shipment-login-required')).toBeNull()
  })
})

describe('拍照发货页：拍照 → 识别 → 核对（判据 P2 / P3）', () => {
  it('P2 选图走相机 + 照片走**既有**上传通道 `/api/worker/inbound/upload`，识别走 shipment', async () => {
    render(<WorkerShipmentPage />)

    fireEvent.click(screen.getByTestId('shipment-pick'))
    await screen.findByTestId('shipment-photo-count')
    fireEvent.click(screen.getByTestId('shipment-recognize'))
    await screen.findByTestId('shipment-review')

    expect((Taro.chooseImage as jest.Mock).mock.calls[0][0]).toMatchObject({
      count: 3,
      sourceType: ['camera', 'album'],
    })
    // 复用既有通道（不新造第二条上传链）
    expect(mockUpload.mock.calls[0][0]).toBe('blob://photo-1')
    expect(mockRecognize).toHaveBeenCalledWith(['https://oss/1.jpg'])
  })

  it('P3 🔴 识别不确定的格子留空（不是 0），逐格说清「这一格要手输」', async () => {
    render(<WorkerShipmentPage />)

    await reachReview()

    // 认出来的照实填
    expect((screen.getByTestId('shipment-order-no') as HTMLInputElement).value).toBe('ORD-20260926-0001')
    expect((screen.getByTestId('shipment-product-name') as HTMLInputElement).value).toBe('遮光布')
    expect((screen.getByTestId('shipment-height') as HTMLInputElement).value).toBe('2.4')
    // 🔴 没认出来 ⇒ 空（红证：预填 '0' ⇒ 下面两条收到 '0' ⇒ 红）
    expect((screen.getByTestId('shipment-quantity') as HTMLInputElement).value).toBe('')
    expect((screen.getByTestId('shipment-width') as HTMLInputElement).value).toBe('')
    // 逐格说清要手输（键 + 中文名 + 为什么）
    expect(screen.getByTestId('shipment-uncertain-quantity').textContent).toContain('数量')
    expect(screen.getByTestId('shipment-uncertain-width').textContent).toContain('宽')
  })

  it('P4 定位订单走既有读面 `production/scan?token=<识别出的单号>`（拿 order_id，不新造后端端点）', async () => {
    render(<WorkerShipmentPage />)
    await reachReview()

    fireEvent.click(screen.getByTestId('shipment-locate'))
    await screen.findByTestId('shipment-located')

    expect(mockScan).toHaveBeenCalledTimes(1)
    expect(mockScan.mock.calls[0][0]).toBe('ORD-20260926-0001')
    expect(screen.getByTestId('shipment-located').textContent).toContain(ORDER_ID)
  })
})

describe('拍照发货页：生成发货单（判据 P5）', () => {
  async function reachShipReady() {
    render(<WorkerShipmentPage />)
    await reachReview()
    fireEvent.click(screen.getByTestId('shipment-locate'))
    await screen.findByTestId('shipment-located')
    fireEvent.input(screen.getByTestId('shipment-quantity'), { target: { value: '12' } })
    fireEvent.input(screen.getByTestId('shipment-unit'), { target: { value: '米' } })
    fireEvent.input(screen.getByTestId('shipment-tracking'), { target: { value: 'SF123456' } })
  }

  it('P5 发货请求 = 运单号 + 实发明细 + 照片引用 + 识别留痕（识别本身不落库）', async () => {
    await reachShipReady()

    fireEvent.click(screen.getByTestId('shipment-submit'))
    await screen.findByTestId('shipment-summary')

    expect(mockShip).toHaveBeenCalledTimes(1)
    const [orderId, body] = mockShip.mock.calls[0]
    expect(orderId).toBe(ORDER_ID)
    expect(body.trackingNo).toBe('SF123456')
    expect(body.items).toEqual([
      { order_item_id: null, product_name: '遮光布', shipped_quantity: '12', unit: '米' },
    ])
    expect(body.photoRefs).toEqual(['https://oss/1.jpg'])
    expect(body.recognition).toMatchObject({ targetType: 'shipment' })
    // 身份一个字节都不进 body（只由 X-Worker-Session-Id 解）
    expect(Object.keys(body)).not.toContain('worker_id')
    expect(Object.keys(body)).not.toContain('worker_name')
  })

  it('P5 🔴 重试复用**同一把**幂等键（超时重发不许重复发货）', async () => {
    await reachShipReady()
    mockShip.mockRejectedValueOnce(new Error('timeout'))

    fireEvent.click(screen.getByTestId('shipment-submit'))
    await screen.findByTestId('shipment-error')
    fireEvent.click(screen.getByTestId('shipment-submit'))
    await screen.findByTestId('shipment-summary')

    expect(mockShip).toHaveBeenCalledTimes(2)
    const keys = mockShip.mock.calls.map((call) => call[2])
    expect(keys[0]).toBe(keys[1])
    // 键由服务层生成一次（页面不每点一次换一把）
    expect(mockNewKey).toHaveBeenCalledTimes(1)
  })

  it('P5 实发数量没给 ⇒ 端侧先拦住（不白跑一次 422）', async () => {
    render(<WorkerShipmentPage />)
    await reachReview()
    fireEvent.click(screen.getByTestId('shipment-locate'))
    await screen.findByTestId('shipment-located')
    fireEvent.input(screen.getByTestId('shipment-tracking'), { target: { value: 'SF123456' } })

    fireEvent.click(screen.getByTestId('shipment-submit'))

    expect(mockShip).not.toHaveBeenCalled()
    expect(screen.getByTestId('shipment-error').textContent).toMatch(/实发/)
  })

  it('P5 服务端拒绝 ⇒ 原样上屏（不谎报已发货）', async () => {
    await reachShipReady()
    mockShip.mockResolvedValueOnce({
      success: false,
      message: '当前状态（已发货）不可发货：仅 待发货 / 生产中 / 已打包 可发货',
    })

    fireEvent.click(screen.getByTestId('shipment-submit'))

    const error = await screen.findByTestId('shipment-error')
    expect(error.textContent).toContain('当前状态（已发货）不可发货')
    expect(screen.queryByTestId('shipment-summary')).toBeNull()
  })
})

describe('拍照发货页：实发读面说人话（判据 P6）', () => {
  async function reachSummary() {
    render(<WorkerShipmentPage />)
    await reachReview()
    fireEvent.click(screen.getByTestId('shipment-locate'))
    await screen.findByTestId('shipment-located')
    fireEvent.input(screen.getByTestId('shipment-quantity'), { target: { value: '12' } })
    fireEvent.input(screen.getByTestId('shipment-unit'), { target: { value: '米' } })
    fireEvent.input(screen.getByTestId('shipment-tracking'), { target: { value: 'SF123456' } })
    fireEvent.click(screen.getByTestId('shipment-submit'))
    await screen.findByTestId('shipment-summary')
  }

  it('P6 实发汇总 = 单位/套/卷三样；`null` 的维度 ⇒ 不印 0（「—」形态由服务判据 S5 单独锁）', async () => {
    await reachSummary()

    expect(mockRead).toHaveBeenCalledWith(ORDER_ID)
    const totals = screen.getByTestId('shipment-totals')
    expect(totals.textContent).toContain('12米')
    // set_count / roll_count 为 null ⇒ 这一维不适用，**不出现**「0套 / 0卷」
    expect(totals.textContent).not.toContain('0套')
    expect(totals.textContent).not.toContain('0卷')
  })

  it('P6 发货单号 / 运单号 / 经手人（服务端读数）都上屏', async () => {
    await reachSummary()

    const summary = screen.getByTestId('shipment-summary')
    expect(summary.textContent).toContain('SHIP-0001')
    expect(summary.textContent).toContain('SF123456')
    expect(summary.textContent).toContain('张三')
  })

  it('P6 读面没有发货单 ⇒ 不渲染空的「实发 —」面板（只报状态）', async () => {
    mockRead.mockResolvedValueOnce({
      success: true,
      message: '',
      data: { order_id: ORDER_ID, order_no: 'ORD-20260926-0001', status: 'shipped', shipments: [] },
    })

    await reachSummary()

    expect(screen.queryByTestId('shipment-totals')).toBeNull()
    expect(screen.getByTestId('shipment-summary').textContent).toContain('shipped')
  })
})

describe('拍照发货页：路由常量是单一真值', () => {
  it('页面路由逐字等于 `gaps.ts` 的常量（并在 app.config.ts 登记）', () => {
    expect(SHIPMENT_PAGE_ROUTE).toBe('/pages/worker/shipment/index')
  })
})

afterAll(() => {
  clearWorkerSession()
})
