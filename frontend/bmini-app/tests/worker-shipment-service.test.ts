// case_ids: BM-050
/**
 * 工人**拍照发货**服务层的判据（issue #6761；服务 = `src/services/workerShipmentService.ts`）
 *
 * 三条不能破的纪律（沿用 #5648 已落码的口径，见 `frontend/worker-h5/src/shipment.mjs` 的注释；
 * 本包**只读参考**它，绝不 import 跨包文件 —— 跨包静态 import 会让部署构建上下文红，见 #6744/#6745）：
 *
 * | # | 判据 | 红证（怎么让它单独变红） |
 * |---|---|---|
 * | S1 | **端点与字段面照后端逐字同名**：`/api/worker/shipment/recognize` / `orders/{orderId}/ship` / `orders/{orderId}` | 端点拼错 / 把 `images` 写成别的键 ⇒ 红 |
 * | S2 | 🔴 **请求体白名单**：`worker_id` / `worker_name` 一个字节都不进 body（身份只由 `X-Worker-Session-Id` 解） | 往 body 里加 `worker_id` ⇒ 红 |
 * | S3 | 🔴 **幂等键 `X-Client-Request-Id`**：存在；传入同一把 ⇒ **重试复用同一把**（超时重发不重复发货） | 忽略入参每次新生成 / 不带头 ⇒ 红 |
 * | S4 | 🔴 **不预填**：`value` 为 null / 空串的格子 ⇒ **空串**（**不是** 0、不是猜测值），且逐格列出「要手输」 | 把 null 折成 '0' ⇒ 红 |
 * | S5 | **实发读面照实说**：单位/套/卷三样；`null` ⇒ 「—」，**不印 0** | 把 null 当 0 印出来 ⇒ 红 |
 * | S6 | **照片引用 + 识别留痕原样随发货请求提交**（识别本身不落库） | 丢掉 photoRefs / recognition ⇒ 红 |
 */
import Taro from '@tarojs/taro'
import {
  SHIPMENT_ENDPOINTS,
  SHIPMENT_FIELD_KEYS,
  SHIPMENT_IDEMPOTENCY_HEADER,
  buildShipBody,
  buildShipmentItem,
  formatShippedTotals,
  newShipmentRequestId,
  postWorkerShipment,
  prefillFromRecognition,
  readWorkerShipment,
  recognizeShipment,
} from '../src/services/workerShipmentService'
import { WORKER_SESSION_HEADER, clearWorkerSession, setWorkerSessionId } from '../src/utils/workerSession'

/** 后端 `ImageRecognitionClient.ImageRecognitionResult` 的形状：`{target_type, fields[], degraded}` */
const FIELDS = [
  { key: 'order_no', label: '订单号', value: 'ORD-20260926-0001', source: '[图片识别]' },
  { key: 'product_name', label: '商品名称', value: '遮光布', source: '[图片识别]' },
  { key: 'quantity', label: '数量', value: null, source: '[图片识别]', reason: '图上没有写明数量' },
  { key: 'width', label: '宽', value: '', source: '[图片识别]', reason: '方向不明、不猜顺序' },
  { key: 'height', label: '高', value: '2.4', source: '[图片识别]' },
]

function ok(data: any = {}) {
  return { statusCode: 200, data: { success: true, data } }
}

/** 全部请求（按调用次序）—— 判据看的是**真请求**，不是「某个函数被调过」 */
function requests(): any[] {
  return (Taro.request as jest.Mock).mock.calls.map((call) => call[0])
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage()
})

describe('拍照发货服务：端点与字段面逐字同名（后端 WorkerShipmentController / targets.py 的 shipment）', () => {
  it('S1 三个端点逐字等于后端契约', () => {
    expect(SHIPMENT_ENDPOINTS).toEqual({
      recognize: '/api/worker/shipment/recognize',
      ship: '/api/worker/shipment/orders/{orderId}/ship',
      detail: '/api/worker/shipment/orders/{orderId}',
    })
    // 识别字段面与后端 `app/vision/targets.py` 的 shipment target 逐字同名
    expect(SHIPMENT_FIELD_KEYS).toEqual(['order_no', 'product_name', 'quantity', 'width', 'height'])
    // 幂等头名与后端 `ClientRequestIdService.HEADER` 逐字同名
    expect(SHIPMENT_IDEMPOTENCY_HEADER).toBe('X-Client-Request-Id')
  })

  it('S1 识别请求体只有 `images`（识别**不落库、不提交**）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok({ fields: FIELDS, degraded: false }))
    setWorkerSessionId('sess-1')

    await recognizeShipment(['https://oss/1.jpg'])

    const req = requests()[0]
    expect(req.url).toContain('/api/worker/shipment/recognize')
    expect(req.data).toEqual({ images: ['https://oss/1.jpg'] })
    expect(req.header[WORKER_SESSION_HEADER]).toBe('sess-1')
  })

  it('S1 发货 / 读面端点里的 `{orderId}` 被替换且被 URL 编码', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok({}))
    setWorkerSessionId('sess-1')

    await postWorkerShipment('CSO/1', buildShipBody({ trackingNo: 'SF1' }), 'key-1')
    await readWorkerShipment('CSO/1')

    expect(requests()[0].url).toContain('/api/worker/shipment/orders/CSO%2F1/ship')
    expect(requests()[1].url).toContain('/api/worker/shipment/orders/CSO%2F1')
  })
})

describe('拍照发货服务：三条不能破的纪律', () => {
  it('S2 🔴 请求体白名单：`worker_id` / `worker_name` 一个字节都不进 body', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok({}))
    setWorkerSessionId('sess-1')

    await postWorkerShipment(
      'CSO1',
      buildShipBody({
        trackingNo: 'SF123',
        logisticsCompany: '顺丰',
        photoRefs: ['https://oss/1.jpg'],
        recognition: { fields: FIELDS },
        items: [buildShipmentItem({ orderItemId: null, productName: '遮光布', shippedQuantity: '12', unit: '米' })],
      }),
      'key-1',
    )

    const body = requests()[0].data
    const keys = Object.keys(body)
    expect(keys).not.toContain('worker_id')
    expect(keys).not.toContain('worker_name')
    // 结构上也**没有** order_id / status：身份与状态都由服务端定
    expect(keys).not.toContain('order_id')
    expect(keys).not.toContain('status')
    expect(keys.sort()).toEqual(['items', 'logisticsCompany', 'photoRefs', 'recognition', 'trackingNo'])
    // 身份只在请求头里（一条链只有一个身份来源）
    expect(requests()[0].header[WORKER_SESSION_HEADER]).toBe('sess-1')
  })

  it('S2 白名单是**构造式**的：混入的额外键（如身份）进不了 body', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    setWorkerSessionId('sess-1')

    const body = buildShipBody({
      trackingNo: 'SF1',
      items: [buildShipmentItem({ shippedQuantity: '3', unit: '件' })],
      // 故意混入身份：构造式白名单必须把它挡在外面（多余键在 TS 里是 excess property，
      // 在运行期则是**真会到达服务端**的那一类 —— 所以这里断言的是最终请求体）
      worker_id: 'w-1',
      worker_name: '张三',
    } as any)
    await postWorkerShipment('CSO1', body, 'key-1')

    expect(Object.keys(requests()[0].data)).toEqual(['trackingNo', 'items'])
    expect(JSON.stringify(requests()[0].data)).not.toContain('w-1')
    expect(JSON.stringify(requests()[0].data)).not.toContain('张三')
  })

  it('S3 🔴 幂等键：存在，且**重试复用同一把**（超时重发不许重复发货）', async () => {
    setWorkerSessionId('sess-1')
    const body = buildShipBody({ trackingNo: 'SF1' })

    // 第一次：服务端 5xx（**有** statusCode ⇒ 请求层不重试，立刻答复）
    ;(Taro.request as jest.Mock).mockResolvedValueOnce({
      statusCode: 500,
      data: { success: false, message: '服务端繁忙' },
    })
    const first = await postWorkerShipment('CSO1', body, 'ship-key-1')
    expect(first.success).toBe(false)
    expect(first.statusCode).toBe(500)

    // 页面拿**同一把**键重发（键是入参、只绑一次 ⇒ 请求层内的退避重试也必然带同一把）
    ;(Taro.request as jest.Mock).mockResolvedValue(ok({ order_id: 'CSO1', status: 'shipped' }))
    const second = await postWorkerShipment('CSO1', body, 'ship-key-1')
    expect(second.success).toBe(true)

    const keys = requests().map((req) => req.header[SHIPMENT_IDEMPOTENCY_HEADER])
    expect(keys.length).toBeGreaterThanOrEqual(2)
    expect(Array.from(new Set(keys))).toEqual(['ship-key-1'])
  })

  it('S3 不传键时自动生成一把非空键（并带前缀便于服务端台账溯源）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    setWorkerSessionId('sess-1')

    await postWorkerShipment('CSO1', buildShipBody({ trackingNo: 'SF1' }))

    const key = requests()[0].header[SHIPMENT_IDEMPOTENCY_HEADER]
    expect(typeof key).toBe('string')
    expect(key.length).toBeGreaterThan(0)
    expect(key.startsWith('shipment-')).toBe(true)
    expect(newShipmentRequestId()).not.toBe(newShipmentRequestId())
  })

  it('S1 读面失败/业务拒绝 ⇒ `success:false` + 服务端原文（不谎报已发货）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 200,
      data: { success: false, message: '当前状态（已发货）不可发货：仅 待发货 / 生产中 / 已打包 可发货' },
    })
    setWorkerSessionId('sess-1')

    const res = await postWorkerShipment('CSO1', buildShipBody({ trackingNo: 'SF1' }), 'k')

    expect(res.success).toBe(false)
    expect(res.message).toBe('当前状态（已发货）不可发货：仅 待发货 / 生产中 / 已打包 可发货')
  })
})

describe('拍照发货服务：识别候选 ⇒ 不预填（不确定的格子留空 + 逐格说清要手输）', () => {
  it('S4 🔴 null / 空串 ⇒ 空串（**不是** 0、不是猜测值）', () => {
    const draft = prefillFromRecognition(FIELDS)

    expect(draft.orderNo).toBe('ORD-20260926-0001')
    expect(draft.productName).toBe('遮光布')
    expect(draft.quantity).toBe('')
    expect(draft.width).toBe('')
    expect(draft.height).toBe('2.4')
    // 单位**不从识别结果推**（识别面只认数量）：默认空，页面给三选一
    expect(draft.unit).toBe('')
    // 红证：把 null 折成 '0' ⇒ 上面两条 `toBe('')` 收到 '0' ⇒ 红
  })

  it('S4 逐格列出「这一格要手输」（键 + 中文名 + 为什么）', () => {
    const draft = prefillFromRecognition(FIELDS)

    expect(draft.uncertain.map((cell) => cell.key)).toEqual(['quantity', 'width'])
    expect(draft.uncertain.map((cell) => cell.label)).toEqual(['数量', '宽'])
    for (const cell of draft.uncertain) {
      expect(cell.reason.length).toBeGreaterThan(0)
    }
  })

  it('S4 识别整张表为空 ⇒ 全部留空（不编造订单号）', () => {
    const draft = prefillFromRecognition(undefined)

    expect(draft.orderNo).toBe('')
    expect(draft.quantity).toBe('')
    expect(draft.uncertain).toEqual([])
  })

  it('S4 数字 0 是**真值**（不是「没认出来」）：照实抄下来', () => {
    const draft = prefillFromRecognition([
      { key: 'quantity', label: '数量', value: 0 as any, source: '[图片识别]' },
    ])

    expect(draft.quantity).toBe('0')
    expect(draft.uncertain).toEqual([])
  })
})

describe('拍照发货服务：实发读面说人话（单位 / 套 / 卷三样，null ⇒ 「—」）', () => {
  it('S5 单位 + 套 + 卷三样都在；值为 0 / null 的维度不印 0', () => {
    expect(
      formatShippedTotals({ by_unit: { 米: 12.5, 件: 3 }, set_count: 2, roll_count: null }),
    ).toBe('12.5米 / 3件 / 2套')
  })

  it('S5 全空 ⇒ 「—」（**不印 0**：空集不是「发了 0 件」）', () => {
    expect(formatShippedTotals({ by_unit: {}, set_count: null, roll_count: null })).toBe('—')
    expect(formatShippedTotals(undefined)).toBe('—')
    // 红证：把 null 折成 0 并照印 ⇒ 收到 '0套 / 0卷' ⇒ 红
  })

  it('S5 卷只有真的 > 0 才出现（0 卷 = 这一维不适用）', () => {
    expect(formatShippedTotals({ by_unit: { 米: 5 }, set_count: 0, roll_count: 3 })).toBe('5米 / 3卷')
  })
})

describe('拍照发货服务：退避与清理', () => {
  afterAll(() => {
    clearWorkerSession()
  })

  it('无工人 session ⇒ 服务层不发伪造身份（仍自带请求，由服务端 401 显式拒绝）', async () => {
    clearWorkerSession()
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 401,
      data: { success: false, message: '尚未登录工人身份，请先用工号 + PIN 登录' },
    })

    const res = await postWorkerShipment('CSO1', buildShipBody({ trackingNo: 'SF1' }), 'k')

    expect(res.success).toBe(false)
    expect(res.message).toContain('尚未登录工人身份')
    const headers = requests()[0].header
    expect(headers[WORKER_SESSION_HEADER]).toBeUndefined()
    expect(JSON.stringify(requests()[0].data)).not.toContain('worker')
  })
})
