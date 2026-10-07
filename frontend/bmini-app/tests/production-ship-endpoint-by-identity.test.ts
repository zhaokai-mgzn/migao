// case_ids: BM-039
/**
 * 发货**按身份选端点**（issue #6472，S1 + S2）。
 *
 * ## 病灶（现取）
 * 报工页的发货块（`isCompleted && !shipped`）对**任何身份**渲染，而它打的端点是
 * `POST /api/admin/production/orders/{id}/ship` —— 一台**只有工人身份**的车间设备
 * （工人零商家权限，`/api/admin/**` 的拒绝集合含 `worker`，见 `WorkerProductionController`
 * 类注释与 issue #4727）点下去**必被服务端拒绝**：界面给了做不成的动作。
 *
 * 而**工人发货端点早已存在**（issue #5648）：`WorkerShipmentController` 的
 * `POST /api/worker/shipment/orders/{orderId}/ship`。
 *
 * ## 本文件锁五条（每条都能红）
 * ① **工人身份 ⇒ `worker/shipment` 恰一次、`/api/admin/.../ship` 零次**
 *    （断言请求 URL 集合，不是「某个函数被调过」—— `migao-dev-flow` §28.2「判据本体绿 ≠ 接线在」）；
 * ② **商家身份 ⇒ 逐字反向**（`/api/admin/.../ship` 一次、`worker/shipment` 零次）；
 * ③ **工人路径带工人 session 头 + 幂等键**（工人端点只认 `X-Worker-Session-Id`；发货不可逆 ⇒ 重试要能去重）；
 * ④ **商家路径 body 逐字不变**（只有 `{trackingNo, logisticsCompany}`，**不带** `items`）——
 *    商家端点由服务端取「订单未发余量」，客户端多传会改它的写面语义；
 * ⑤ **工人路径 body 必须带非空 `items[]`**（服务端 `OrderShipmentService#parseDetails` 的硬契约：
 *    缺/空 ⇒ 422「发货明细不能为空」）⇒ 工人身份下点发货不是「换个 URL 继续失败」。
 *
 * ## 红证（S5 实测，注入 ⇒ 红 ⇒ 还原 ⇒ 绿）
 * - 把页面/服务里的工人分支摘掉（`hasWorkerSession()` 判据写死 false）⇒ ①红（工人设备走商家端点）。
 * - 把 `workerShipItems` 的 `items` 改成 `[]` ⇒ ⑤红（服务端 422 的端侧等价形态）。
 * - 把商家分支的 body 加上 `items` ⇒ ④红。
 */
import Taro from '@tarojs/taro'
import {
  CLIENT_REQUEST_ID_HEADER,
  shipOrder,
  shipWorkerOrder,
  workerShipItems,
  type ProductionPosition,
} from '../src/services/productionService'
import {
  WORKER_SESSION_HEADER,
  clearWorkerSession,
  setWorkerSessionId,
} from '../src/utils/workerSession'

const ORDER_ID = 'CSO261007-00001'

/** 读面夹具（`GET .../operations` 的形状）：两个部位，各带首道工序的应做数量与单位。 */
const POSITIONS: ProductionPosition[] = [
  {
    position_name: '布帘',
    order_item_id: 'item-A',
    operations: [
      {
        id: 'op1', seq: 1, operation: '精裁-布', logical_name: '精裁', position: '布帘',
        group: '裁剪', unit: '米', qty: 12.5, unit_price: 3.5, is_must_finish: false,
        is_start_marker: true, status: 'done', done_qty: 12.5,
      },
    ],
  },
  {
    position_name: '纱帘',
    order_item_id: 'item-B',
    operations: [
      {
        id: 'op2', seq: 2, operation: '定型-纱', logical_name: '定型', position: '纱帘',
        group: '后道', unit: '米', qty: 8, unit_price: 4, is_must_finish: false,
        is_start_marker: false, status: 'done', done_qty: 8,
      },
    ],
  },
]

function ok(data: any = { order_id: ORDER_ID, status: 'shipped' }) {
  return { statusCode: 200, data: { success: true, data } }
}

/** 全部请求（按调用次序），取 URL / body / header 用。 */
function requests(): any[] {
  return (Taro.request as jest.Mock).mock.calls.map((call) => call[0])
}

function shipUrls(): string[] {
  return requests()
    .map((req) => String(req.url))
    .filter((url) => url.includes('/ship'))
}

beforeEach(() => {
  jest.clearAllMocks()
  ;(Taro as any).__clearStorage()
})

describe('发货按身份选端点（issue #6472）', () => {
  // ============================================================ ① 工人身份

  it('工人身份：调 `worker/shipment` **恰一次**，`/api/admin/.../ship` **零次**', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    setWorkerSessionId('sess-worker-1')

    await shipWorkerOrder(ORDER_ID, 'SF123456', POSITIONS)

    const urls = shipUrls()
    expect(urls).toHaveLength(1)
    expect(urls[0]).toContain(`/api/worker/shipment/orders/${ORDER_ID}/ship`)
    // 🔴 反向断言：工人设备打 `/api/admin/**` 必被拒（拒绝集合含 worker）
    expect(urls.filter((url) => url.includes('/api/admin/'))).toEqual([])
  })

  it('工人身份：带工人 session 头（工人端点只认它）+ 幂等键（发货不可逆，重试要去重）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    setWorkerSessionId('sess-worker-1')

    await shipWorkerOrder(ORDER_ID, 'SF123456', POSITIONS)

    const header = requests()[0].header
    expect(header[WORKER_SESSION_HEADER]).toBe('sess-worker-1')
    expect(typeof header[CLIENT_REQUEST_ID_HEADER]).toBe('string')
    expect(header[CLIENT_REQUEST_ID_HEADER].length).toBeGreaterThan(0)
  })

  it('工人身份：幂等键可由调用方传入（重试复用同一个键 ⇒ 服务端不重复发货）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    setWorkerSessionId('sess-worker-1')

    await shipWorkerOrder(ORDER_ID, 'SF123456', POSITIONS, undefined, 'ship-key-1')

    expect(requests()[0].header[CLIENT_REQUEST_ID_HEADER]).toBe('ship-key-1')
  })

  // ============================================================ ⑤ 工人路径 body 契约

  it('工人路径 body 带**非空** `items[]`（服务端缺/空 ⇒ 422，不是「换个 URL 继续失败」）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    setWorkerSessionId('sess-worker-1')

    await shipWorkerOrder(ORDER_ID, 'SF123456', POSITIONS)

    const body = requests()[0].data
    expect(body.trackingNo).toBe('SF123456')
    // 一部位一行、字段面与服务端 `parseDetails` 逐字同名
    expect(body.items).toEqual([
      { order_item_id: 'item-A', shipped_quantity: 12.5, unit: '米' },
      { order_item_id: 'item-B', shipped_quantity: 8, unit: '米' },
    ])
    // 🔴 身份不在 body 里（工人端点只读 session；body 自称无效）
    expect(body).not.toHaveProperty('worker_id')
    expect(body).not.toHaveProperty('worker_name')
  })

  it('`workerShipItems`：缺 `order_item_id` 的部位跳过（不冒充已知）；无工序 ⇒ 跳过', () => {
    const items = workerShipItems([
      { position_name: '手写行', operations: [] } as ProductionPosition,
      {
        position_name: '配件行', order_item_id: null,
        operations: [{ id: 'opx', operation: '配件', group: '配件', unit: '件', qty: 2, unit_price: 1, is_must_finish: false, is_start_marker: false, status: 'done', done_qty: 2, seq: 1 }],
      } as ProductionPosition,
      POSITIONS[0],
    ])
    expect(items).toEqual([{ order_item_id: 'item-A', shipped_quantity: 12.5, unit: '米' }])
  })

  // ============================================================ ②④ 商家身份

  it('商家身份：调 `/api/admin/.../ship` **恰一次**，`worker/shipment` **零次**', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    // 无工人 session（纯商家设备）
    clearWorkerSession()

    await shipOrder(ORDER_ID, 'SF123456')

    const urls = shipUrls()
    expect(urls).toHaveLength(1)
    expect(urls[0]).toContain(`/api/admin/production/orders/${ORDER_ID}/ship`)
    expect(urls.filter((url) => url.includes('/api/worker/'))).toEqual([])
  })

  it('商家路径 body **逐字不变**（只有单号/承运商，不带 `items`/幂等键）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue(ok())
    clearWorkerSession()

    await shipOrder(ORDER_ID, 'SF123456')

    const request = requests()[0]
    // 商家端点由服务端取「订单未发余量」⇒ 客户端**不传** items（多传会改它的写面语义）
    expect(request.data).toEqual({ trackingNo: 'SF123456', logisticsCompany: undefined })
    expect(request.header).not.toHaveProperty(WORKER_SESSION_HEADER)
    expect(request.header).not.toHaveProperty(CLIENT_REQUEST_ID_HEADER)
  })

  // ============================================================ 失败回执

  it('服务端拒绝 ⇒ `success:false` + 服务端原文（不谎报已发货）', async () => {
    ;(Taro.request as jest.Mock).mockResolvedValue({
      statusCode: 200,
      data: { success: false, message: '发货明细不能为空：需要逐行给出**实发**数量' },
    })
    setWorkerSessionId('sess-worker-1')

    const res = await shipWorkerOrder(ORDER_ID, 'SF123456', POSITIONS)

    expect(res.success).toBe(false)
    expect(res.message).toBe('发货明细不能为空：需要逐行给出**实发**数量')
  })
})
