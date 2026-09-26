// case_ids: BM-009
/**
 * 管理面手机端服务层（issue #5654）—— 端点/请求体/三态分类
 *
 * 本文件钉的是**与后端契约逐字一致**的那一层（本单不新增后端端点，也不改返回形状）：
 * - 请求路径与 HTTP 方法（含 `PATCH /api/admin/inbound-orders/{id}` 这个过账动作）；
 * - 派单请求体**四个键**（`orderIds/batches/assignmentRule/pooled`）与 `pooled` 的两种取值；
 * - 🔴 **三态可区分**：403 ⇒ `forbidden` + 逐字「无「XX」…权限（需要权限码 …）」；
 *   422/其它 ⇒ `error` + 服务端文案（不泛化、不吞）；`success:false` ⇒ **不算 ok**。
 * - 计件报表用 `period` 参数、按工人下钻用 `worker_name`（下划线键，与后端 `@RequestParam` 同名）。
 *
 * 红证（实测注入，逐条跑过）：
 * ① 把 403 分支去掉（一律 error）⇒「403 ⇒ forbidden + 逐字文案」当场红；
 * ② 把 `dispatchPoolOrders` 的 `pooled` 写死 `true` ⇒「加急单派 pooled=false」红；
 * ③ 把 `postInboundOrder` 的 `patch` 换成 `put` ⇒ 方法断言红。
 */
import { get, patch, post, put } from '../src/utils/request'
import {
  dispatchPoolOrders,
  fetchMyPermissions,
  getPieceworkReport,
  getProductionPool,
  listAfterSales,
  listInboundOrders,
  postInboundOrder,
  previewPoolDispatch,
  updateAfterSalesStatus,
  buildPoolDispatchBody,
  formatYuanAmount,
  formatWaitHours,
  periodOf,
  previousPeriodOf,
} from '../src/services/adminOpsService'
import { missingPermissionText } from '../src/utils/adminPermission'

jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
}))

const mockGet = get as jest.MockedFunction<typeof get>
const mockPost = post as jest.MockedFunction<typeof post>
const mockPut = put as jest.MockedFunction<typeof put>
const mockPatch = patch as jest.MockedFunction<typeof patch>

/** 后端业务失败形态：带 HTTP 状态码 + `error.message` */
function httpError(statusCode: number, message: string): any {
  const error: any = new Error(`Request failed with status ${statusCode}`)
  error.statusCode = statusCode
  error.data = { success: false, error: { code: 'X', message } }
  return error
}

beforeEach(() => {
  jest.clearAllMocks()
})

describe('管理面服务层：端点与请求体（issue #5654）', () => {
  it('待派池：GET /api/admin/production/pool（maxWaitHours 缺省不传）', async () => {
    mockGet.mockResolvedValue({ success: true, data: { orderCount: 0 } } as any)
    const res = await getProductionPool()
    expect(mockGet).toHaveBeenCalledWith('/api/admin/production/pool', {
      baseURL: expect.any(String),
      params: undefined,
    })
    expect(res).toEqual({ status: 'ok', data: { orderCount: 0 } })
  })

  it('派单请求体四个键逐字：orderIds/batches/assignmentRule/pooled', () => {
    expect(buildPoolDispatchBody(['o1', 'o2'], true)).toEqual({
      orderIds: ['o1', 'o2'],
      batches: [],
      assignmentRule: null,
      pooled: true,
    })
  })

  it('成批预览与派单都打到 pool 子路径，且 pooled 区分成批 / 加急单派', async () => {
    mockPost.mockResolvedValue({ success: true, data: { orderCount: 1 } } as any)
    await previewPoolDispatch(['o1'])
    expect(mockPost).toHaveBeenCalledWith(
      '/api/admin/production/pool/preview',
      { orderIds: ['o1'], batches: [], assignmentRule: null, pooled: true },
      { baseURL: expect.any(String) },
    )

    mockPost.mockClear()
    mockPost.mockResolvedValue({ success: true, data: [{ orderRef: 'o9', success: true }] } as any)
    await dispatchPoolOrders(['o9'], false)
    expect(mockPost).toHaveBeenCalledWith(
      '/api/admin/production/pool/dispatch',
      { orderIds: ['o9'], batches: [], assignmentRule: null, pooled: false },
      { baseURL: expect.any(String) },
    )
  })

  it('入库单：列表带筛选参数、详情按 id（URL 编码）、过账是 PATCH {action:post}', async () => {
    mockGet.mockResolvedValue({ success: true, data: [] } as any)
    await listInboundOrders({ status: 'draft' })
    expect(mockGet).toHaveBeenCalledWith('/api/admin/inbound-orders', {
      baseURL: expect.any(String),
      params: { status: 'draft' },
    })

    mockPatch.mockResolvedValue({ success: true, data: { id: 'i1', status: 'posted' } } as any)
    const res = await postInboundOrder('RK 2026/1')
    expect(mockPatch).toHaveBeenCalledWith(
      '/api/admin/inbound-orders/RK%202026%2F1',
      { action: 'post' },
      { baseURL: expect.any(String) },
    )
    expect(res.status).toBe('ok')
  })

  it('售后：列表分页参数（page/size/status）、改状态走 PUT {status}', async () => {
    mockGet.mockResolvedValue({ success: true, data: { items: [], total: 0 } } as any)
    await listAfterSales({ status: 'pending' })
    expect(mockGet).toHaveBeenCalledWith('/api/admin/after-sales', {
      baseURL: expect.any(String),
      params: { page: 1, size: 20, status: 'pending' },
    })

    mockPut.mockResolvedValue({ success: true } as any)
    const res = await updateAfterSalesStatus('t1', 'resolved')
    expect(mockPut).toHaveBeenCalledWith(
      '/api/admin/after-sales/t1/status',
      { status: 'resolved' },
      { baseURL: expect.any(String) },
    )
    expect(res).toEqual({ status: 'ok', data: true })
  })

  it('计件报表：period 必传，worker_name 为下划线键（与后端 @RequestParam 同名）', async () => {
    mockGet.mockResolvedValue({ success: true, data: { period: '2026-09', total: 0 } } as any)
    await getPieceworkReport({ period: '2026-09', workerName: '张三' })
    expect(mockGet).toHaveBeenCalledWith('/api/admin/production/piecework/summary', {
      baseURL: expect.any(String),
      params: { period: '2026-09', worker_name: '张三' },
    })
  })
})

describe('管理面服务层：三态可区分（无权限 / 失败 / 有数据）', () => {
  it('403 ⇒ forbidden + 逐字「无「XX」…（需要权限码 …）」（4 项读写各一条）', async () => {
    mockGet.mockRejectedValue(httpError(403, 'Forbidden'))
    expect(await getProductionPool()).toEqual({
      status: 'forbidden',
      message: '无「智能派单」查看权限（需要权限码 processing:view）',
    })
    expect(await listInboundOrders()).toEqual({
      status: 'forbidden',
      message: '无「入库过账」查看权限（需要权限码 inbound:view）',
    })
    expect(await listAfterSales()).toEqual({
      status: 'forbidden',
      message: '无「售后处理」查看权限（需要权限码 after_sales:view）',
    })
    expect(await getPieceworkReport({ period: '2026-09' })).toEqual({
      status: 'forbidden',
      message: '无「计件工资报表」查看权限（需要权限码 processing:manage）',
    })

    mockPatch.mockRejectedValue(httpError(403, 'Forbidden'))
    expect(await postInboundOrder('i1')).toEqual({
      status: 'forbidden',
      message: '无「入库过账」过账权限（需要权限码 inbound:create）',
    })
    mockPut.mockRejectedValue(httpError(403, 'Forbidden'))
    expect(await updateAfterSalesStatus('t1', 'closed')).toEqual({
      status: 'forbidden',
      message: '无「售后处理」处理权限（需要权限码 order:refund）',
    })
    mockPost.mockRejectedValue(httpError(403, 'Forbidden'))
    expect(await dispatchPoolOrders(['o1'])).toEqual({
      status: 'forbidden',
      message: '无「智能派单」派单权限（需要权限码 processing:update）',
    })
  })

  it('非 403 失败 ⇒ error + 服务端文案（不泛化、不吞）', async () => {
    mockPost.mockRejectedValue(httpError(422, '加急订单不允许参与池化派单'))
    expect(await dispatchPoolOrders(['o1'])).toEqual({
      status: 'error',
      message: '加急订单不允许参与池化派单',
    })

    mockPut.mockRejectedValue(httpError(422, '工单状态不允许从 [待处理] 变更为 [已完成]'))
    expect(await updateAfterSalesStatus('t1', 'resolved')).toEqual({
      status: 'error',
      message: '工单状态不允许从 [待处理] 变更为 [已完成]',
    })
  })

  it('HTTP 200 但 success=false ⇒ **不算 ok**（不把「服务端说失败」渲染成空数据）', async () => {
    mockGet.mockResolvedValue({ success: false, error: { code: 'E', message: '期间格式非法' } } as any)
    expect(await getPieceworkReport({ period: 'bad' })).toEqual({
      status: 'error',
      message: '期间格式非法',
    })
  })

  it('写动作无响应体（ApiResponse<Void>）⇒ 只判 success', async () => {
    mockPut.mockResolvedValue({ success: true } as any)
    expect(await updateAfterSalesStatus('t1', 'closed')).toEqual({ status: 'ok', data: true })
    mockPut.mockResolvedValue({ success: false, error: { code: 'E', message: '不允许' } } as any)
    expect(await updateAfterSalesStatus('t1', 'closed')).toEqual({
      status: 'error',
      message: '不允许',
    })
  })
})

describe('管理面服务层：权限集合与文案', () => {
  it('fetchMyPermissions：读 GET /api/auth/me 的 permissions；失败 ⇒ null（未知，不是空集）', async () => {
    mockGet.mockResolvedValue({ success: true, data: { permissions: ['inbound:view'] } } as any)
    expect(await fetchMyPermissions()).toEqual(['inbound:view'])

    mockGet.mockRejectedValue(httpError(500, 'boom'))
    expect(await fetchMyPermissions()).toBeNull()
  })

  it('missingPermissionText 逐字（4 项 × 读写；文案必须说清缺哪个码）', () => {
    expect(missingPermissionText('pool', 'read')).toBe(
      '无「智能派单」查看权限（需要权限码 processing:view）',
    )
    expect(missingPermissionText('pool', 'write')).toBe(
      '无「智能派单」派单权限（需要权限码 processing:update）',
    )
    expect(missingPermissionText('inbound', 'write')).toBe(
      '无「入库过账」过账权限（需要权限码 inbound:create）',
    )
    expect(missingPermissionText('after-sales', 'write')).toBe(
      '无「售后处理」处理权限（需要权限码 order:refund）',
    )
    expect(missingPermissionText('piecework', 'read')).toBe(
      '无「计件工资报表」查看权限（需要权限码 processing:manage）',
    )
  })
})

describe('管理面服务层：展示助手（只格式化，不算业务数）', () => {
  it('金额按**元**两位小数（不除以 100 —— 与 dashboard 的「分」是两套单位）', () => {
    expect(formatYuanAmount(1234.5)).toBe('¥1234.50')
    expect(formatYuanAmount(null)).toBe('-')
    expect(formatYuanAmount(0)).toBe('¥0.00')
  })

  it('等待时长按服务端 waitHours 渲染（不做第二份口径）', () => {
    expect(formatWaitHours(3.5)).toBe('3.5 小时')
    expect(formatWaitHours(30)).toBe('1 天 6 小时')
    expect(formatWaitHours(null)).toBe('-')
  })

  it('期间计算：本月 / 上月（跨年正确）', () => {
    expect(periodOf(new Date(2026, 8, 26))).toBe('2026-09')
    expect(previousPeriodOf(new Date(2026, 0, 15))).toBe('2025-12')
  })
})
