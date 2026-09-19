// case_ids: PP-011, PG-019, PP-014
// PP-011（issue #4000，M4-H 按需单据渲染）：加工单生产明细页 /processing-orders/{id}/production
// —— 头部（加工单号/订单号/状态/进度/交期）+ 工序进度表 + 计件汇总 + 打印任务卡入口，
// 接口失败要有友好错误提示与重试（不白屏）。
// PG-019（issue #4202，前端半边）：存量加工单（positions 为空且非 cancelled）显示「补生成工序」
// → 调 POST /production/orders/{orderId}/instantiate（空 body）→ 刷新出工序表与二维码；
// 有数据 / 已取消时按钮不出现；任务卡占位文案不得误导（不得再指向「请先在订单详情生成加工单」）。
// PG-019（issue #4240，前端半边）：真值源 §1「二维码 token 化、可撤销」的 UI 发射点 ——
// 生产明细页「撤销二维码」入口（二次确认后才发 POST .../qr-token/revoke，按 processing:manage 显隐）
// → 撤销后刷新回占位态 + 可见「已撤销」反馈。
// PP-014（issue #4307 交付物 2，契约所有者 = 后端 4308）：`route_source` **四态**的用户侧可观测面
// —— derived 不提示 / partial 提示另一半取默认 / missing_route 提示「识别的是 X（route_requested_key）
// 但库里没这条路线」/ default 高亮提示核对工序与计件单价；字段缺失 = 未知 ⇒ 不得显示成「已派生」。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockDetail = vi.fn()
const mockGetOrderOperations = vi.fn()
const mockGetPiecework = vi.fn()
const mockInstantiate = vi.fn()
const mockRecordPrint = vi.fn()
const mockRevokeQrToken = vi.fn()

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    detail: (...args: unknown[]) => mockDetail(...args),
  },
  productionApi: {
    getOrderOperations: (...args: unknown[]) => mockGetOrderOperations(...args),
    getPiecework: (...args: unknown[]) => mockGetPiecework(...args),
    instantiate: (...args: unknown[]) => mockInstantiate(...args),
    recordPrint: (...args: unknown[]) => mockRecordPrint(...args),
    revokeQrToken: (...args: unknown[]) => mockRevokeQrToken(...args),
  },
}))

// 权限显隐用例需要切换当前用户（usePermission → useAuthStore(selector)）
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => (selector ? selector(mockUseAuthStore()) : mockUseAuthStore()),
}))

vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'JG-20260917-0001',
}))

import ProductionDetailPage from '@/app/(dashboard)/processing-orders/[id]/production/page'

const PROCESSING_ORDER = {
  id: 'po-1',
  orderId: 'order-uuid-1',
  orderNo: 'MG20260917001',
  processingOrderNo: 'JG-20260917-0001',
  customerName: '李四',
  expectedDeliveryDate: '2026-09-25',
  status: 'in_processing' as const,
  generatedAt: '2026-09-17 10:00:00',
}

const OPERATIONS = {
  order_id: 'order-uuid-1',
  qr_token: 'qr-token-abc123',
  positions: [
    {
      position_name: '布帘',
      operations: [
        {
          id: 'op-1',
          seq: 1,
          operation: '精裁-布',
          group: '裁剪',
          unit: '套',
          qty: 2,
          unit_price: 8.5,
          is_must_finish: false,
          status: 'done',
          done_qty: 2,
        },
        {
          id: 'op-2',
          seq: 2,
          operation: '外帘装袋',
          group: '后道',
          unit: '件',
          qty: 2,
          unit_price: 3,
          is_must_finish: true,
          status: 'pending',
          done_qty: 0,
        },
      ],
    },
  ],
  progress: { total: 2, done: 1, percent: 50 },
}

const PIECEWORK = {
  total: 17,
  per_worker: { 蒋雪云: 17 },
  per_operation: [{ operation: '精裁-布', amount: 17 }],
}

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 撤销后后端语义：qr_token 置空（工序实例仍在），见 PG-019 data_checks「二维码撤销」 */
const OPERATIONS_REVOKED = { ...OPERATIONS, qr_token: null }

describe('加工单生产明细页', () => {
  beforeEach(() => {
    // 默认 operator（持有 processing:manage ⇒ 撤销入口可见）
    mockUseAuthStore.mockReset().mockReturnValue({
      user: { id: 'u-1', name: '运营', roles: ['operator'], permissions: ['processing:manage'] },
    })
    mockDetail.mockReset().mockResolvedValue(ok(PROCESSING_ORDER))
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockReset().mockResolvedValue(ok(PIECEWORK))
    mockInstantiate.mockReset().mockResolvedValue(ok({ qr_token: 'qr-token-abc123', operation_count: 2 }))
    mockRecordPrint.mockReset().mockResolvedValue(ok({ print_count: 1 }))
    mockRevokeQrToken.mockReset().mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, revoked: true }))
  })

  it('渲染头部信息：加工单号/订单号/状态/交期 + 进度百分比', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    expect(screen.getByTestId('production-processing-order-no')).toHaveTextContent('JG-20260917-0001')
    expect(screen.getByTestId('production-order-no')).toHaveTextContent('MG20260917001')
    expect(screen.getByTestId('production-status')).toHaveTextContent('加工中')
    expect(screen.getByTestId('production-delivery-date')).toHaveTextContent('2026-09-25')
    expect(screen.getByTestId('production-progress-text')).toHaveTextContent('50%')
    expect(screen.getByTestId('production-progress-text')).toHaveTextContent('1/2')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50')
  })

  it('用加工单上的 orderId 拉工序与计件，并渲染工序表/必完标记/计件合计', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())

    expect(mockGetOrderOperations).toHaveBeenCalledWith('order-uuid-1')
    expect(mockGetPiecework).toHaveBeenCalledWith('order-uuid-1')
    expect(within(screen.getByTestId('operation-row-op-2')).getByText('必完')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-total')).toHaveTextContent('¥17.00')
  })

  it('「打印任务卡」按钮调用 window.print（任务卡含二维码）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())

    // 任务卡随页面挂载（屏幕隐藏、打印显形），二维码内容是 qr_token
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('production-print-button'))
    expect(printSpy).toHaveBeenCalledTimes(1)

    printSpy.mockRestore()
  })

  it('打印时上报打印计数，且计数接口失败不阻断打印（fire-and-forget）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    mockRecordPrint.mockRejectedValueOnce(new Error('boom'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-print-button'))

    // 先调计数端点（不 await 结果），再打印
    await waitFor(() => expect(mockRecordPrint).toHaveBeenCalledWith('order-uuid-1'))
    expect(printSpy).toHaveBeenCalledTimes(1)

    printSpy.mockRestore()
  })

  it('工序接口失败：给出提示且不白屏（计件仍展示）', async () => {
    mockGetOrderOperations.mockRejectedValue(new Error('boom'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-operations-error')).toBeInTheDocument())

    expect(screen.getByTestId('production-operations-error')).toHaveTextContent('工序进度加载失败')
    expect(screen.getByTestId('production-header')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-total')).toHaveTextContent('¥17.00')
  })

  it('加工单详情失败：显示错误提示 + 重试按钮（可重新拉取）', async () => {
    mockDetail.mockRejectedValueOnce(new Error('network'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-error')).toHaveTextContent('加载加工单失败')

    await userEvent.click(screen.getByTestId('production-retry-button'))

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(mockDetail).toHaveBeenCalledTimes(2)
  })

  it('加工单无工序实例：空态提示，不报错', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0, per_worker: {}, per_operation: [] }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByText('暂无工序数据')).toBeInTheDocument())
    expect(screen.getByText('暂无计件数据')).toBeInTheDocument()
    expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument()
  })

  // ── PG-019：存量加工单补生成工序（issue #4202 前端半边）──

  it('存量加工单（positions 空 + 非 cancelled）：显示「补生成工序」按钮', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0, per_worker: {}, per_operation: [] }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    expect(screen.getByTestId('production-instantiate-button')).toHaveTextContent('补生成工序')
  })

  it('点击「补生成工序」：调 instantiate（空 body）→ 刷新出工序表与二维码', async () => {
    mockGetOrderOperations
      .mockResolvedValueOnce(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
      .mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockResolvedValue(ok(PIECEWORK))
    mockInstantiate.mockResolvedValue(ok({ qr_token: 'qr-token-abc123', operation_count: 2 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-instantiate-button'))

    // 空 body = 服务端按订单自动派生工序（冻结契约：positions 可选）
    await waitFor(() => expect(mockInstantiate).toHaveBeenCalledWith('order-uuid-1'))
    // 刷新后出真实工序行 + 二维码；按钮消失（已有工序）
    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()
    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('补生成失败：错误提示可见，且按钮保留（可重试）', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    mockInstantiate.mockRejectedValueOnce(new Error('422 positions 不能为空'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-instantiate-button'))

    await waitFor(() => expect(screen.getByTestId('production-instantiate-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-instantiate-button')).toBeInTheDocument()
  })

  it('已有工序实例：不显示「补生成工序」（避免误重插行）', async () => {
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-1')).toBeInTheDocument())

    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('已取消加工单：不显示「补生成工序」（终态不可重生成）', async () => {
    mockDetail.mockResolvedValue(ok({ ...PROCESSING_ORDER, status: 'cancelled' }))
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-instantiate-button')).not.toBeInTheDocument()
  })

  it('任务卡占位文案不误导：不得再指向「请先在订单详情生成加工单」', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ order_id: 'order-uuid-1', qr_token: null, positions: [], progress: { total: 0, done: 0, percent: 0 } }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    // 任务卡是 portal + display:none（打印才显形）⇒ 判文案只看 DOM 存在性，不能用 innerText
    await waitFor(() => expect(screen.getByTestId('task-card-no')).toHaveTextContent('JG-20260917-0001'))
    const placeholder = screen.getByTestId('task-card-qr-placeholder')
    // 加工单**已生成**，二维码缺的真成因是「工序未生成」⇒ 不得再指回去生成加工单
    expect(placeholder.textContent).not.toContain('请先在订单详情生成加工单')
    // 指引指向本页的补生成工序（同一修复面的正向判据）
    expect(screen.getByTestId('production-instantiate-button')).toHaveTextContent('补生成工序')
  })

  // ── PG-019（#4240 前端半边）：撤销二维码入口（真值源 §1「token 化、可撤销」）──

  it('#4240 有二维码 + 有 processing:manage：入口可达，点开只弹二次确认（未确认不发请求）', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    const entry = screen.getByTestId('production-revoke-button')
    expect(entry).toHaveTextContent('撤销二维码')

    await userEvent.click(entry)

    // 二次确认弹窗出现（口径：真值源 §1 撤销是安全相关写操作，避免误触作废已打印纸件）
    expect(await screen.findByRole('dialog', { name: '撤销二维码' })).toBeInTheDocument()
    // **未确认 ⇒ 一个请求都不许发**（红证：去掉确认直接调端点 ⇒ 本条必红）
    expect(mockRevokeQrToken).not.toHaveBeenCalled()
  })

  it('#4240 弹窗点「取消」：关窗且不发请求', async () => {
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-revoke-button'))
    await screen.findByRole('dialog', { name: '撤销二维码' })

    await userEvent.click(screen.getByTestId('production-revoke-cancel'))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: '撤销二维码' })).not.toBeInTheDocument())
    expect(mockRevokeQrToken).not.toHaveBeenCalled()
    // 入口保留（可再次发起）
    expect(screen.getByTestId('production-revoke-button')).toBeInTheDocument()
  })

  it('#4240 确认撤销：按 orderId 调 revoke → 刷新回占位态 + 可见「已撤销」反馈 + 入口消失', async () => {
    mockGetOrderOperations
      .mockResolvedValueOnce(ok(OPERATIONS))
      .mockResolvedValue(ok(OPERATIONS_REVOKED))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-revoke-button'))
    await screen.findByRole('dialog', { name: '撤销二维码' })
    await userEvent.click(screen.getByTestId('production-revoke-confirm'))

    // 生产端点一律走**订单 id**（不是加工单号），与既有 instantiate/print 同口径
    await waitFor(() => expect(mockRevokeQrToken).toHaveBeenCalledWith('order-uuid-1'))

    // 撤销后刷新数据 ⇒ 任务卡二维码回到占位态（旧码在页面上不再出现）
    await waitFor(() => expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument())
    expect(screen.queryByTestId('task-card-qr')).not.toBeInTheDocument()
    // 占位文案要说清为什么没码（不能仍指向不存在的「补生成工序」按钮）
    expect(screen.getByTestId('task-card-qr-placeholder').textContent).toContain('已撤销')

    // 可见反馈（屏幕上的「已撤销」提示，不是仅 toast）
    const notice = screen.getByTestId('production-revoke-success')
    expect(notice).toBeVisible()
    expect(notice).toHaveTextContent('已撤销')
    expect(notice).toHaveTextContent('旧码')
    // 已无可撤销对象 ⇒ 入口收起（防对空 token 重复撤销）
    expect(screen.queryByTestId('production-revoke-button')).not.toBeInTheDocument()
  })

  it('#4240 权限显隐：无 processing:manage（客服）时入口不渲染（有二维码也不渲染）', async () => {
    mockUseAuthStore.mockReturnValue({
      user: { id: 'u-2', name: '客服小王', roles: ['customer_service'], permissions: ['order:list'] },
    })
    render(<ProductionDetailPage />)

    // 页面数据照常加载（工序/二维码都在）—— 挡住的只是写入口
    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    // 红证：去掉显隐判断（无条件渲染按钮）⇒ 本条必红
    expect(screen.queryByTestId('production-revoke-button')).not.toBeInTheDocument()
    // 其它入口不受影响（打印任务卡沿用类级 order:list 口径，仍可见）
    expect(screen.getByTestId('production-print-button')).toBeInTheDocument()
  })

  it('#4240 无二维码（qr_token 为空）：不渲染撤销入口（无可撤销对象）', async () => {
    mockGetOrderOperations.mockResolvedValue(ok({ ...OPERATIONS_REVOKED, positions: [] }))
    mockGetPiecework.mockResolvedValue(ok({ total: 0 }))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-revoke-button')).not.toBeInTheDocument()
  })

  it('#4240 撤销失败：弹窗内可见错误提示，不误报成功，入口保留（可重试）', async () => {
    mockRevokeQrToken.mockRejectedValueOnce(new Error('403 Forbidden'))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('task-card-qr')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('production-revoke-button'))
    await screen.findByRole('dialog', { name: '撤销二维码' })
    await userEvent.click(screen.getByTestId('production-revoke-confirm'))

    await waitFor(() => expect(screen.getByTestId('production-revoke-error')).toBeInTheDocument())
    expect(screen.getByTestId('production-revoke-error')).toHaveTextContent('撤销二维码失败')
    // 失败不得走到「已撤销」反馈，也不得把二维码改成占位态
    expect(screen.queryByTestId('production-revoke-success')).not.toBeInTheDocument()
    expect(screen.getByTestId('task-card-qr')).toBeInTheDocument()
    expect(screen.getByTestId('production-revoke-button')).toBeInTheDocument()
  })
})

// ── 路线来源提示（issue #4307 交付物 2 / #4308 P1「静默回落」的用户侧可观测面）──
// 四态：derived 不提示；partial 提示「另一半取默认值」；missing_route 提示「识别的是 X，
// 但库里没有这条路线」；default 高亮提示「本单没有填部位/做法，请核对工序与计件单价」。
// 红证（实现前）：三态全部静默 ⇒ 罗马帘订单拿到布帘 11 道工序而用户面零提示。
describe('加工单生产明细页 — 路线来源提示（PP-014）', () => {
  const withRoute = (routeSource: string, routeKey: string, routeRequestedKey?: string) => ({
    ...PROCESSING_ORDER,
    routeSource,
    routeKey,
    ...(routeRequestedKey ? { routeRequestedKey } : {}),
  })

  beforeEach(() => {
    mockUseAuthStore.mockReset().mockReturnValue({
      user: { id: 'u-1', name: '运营', roles: ['operator'], permissions: ['processing:manage'] },
    })
    mockGetOrderOperations.mockReset().mockResolvedValue(ok(OPERATIONS))
    mockGetPiecework.mockReset().mockResolvedValue(ok(PIECEWORK))
    mockRecordPrint.mockReset().mockResolvedValue(ok({ print_count: 1 }))
  })

  it('default（两维全不命中）：高亮提示 + 报出实际使用的路线键', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('default', '布帘×韩褶')))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-route-default')).toBeInTheDocument())
    expect(screen.getByTestId('production-route-default')).toHaveTextContent('没有填部位/做法')
    expect(screen.getByTestId('production-route-default')).toHaveTextContent('请核对工序与计件单价')
    expect(screen.getByTestId('production-route-default-detail')).toHaveTextContent('布帘×韩褶')
    expect(screen.queryByTestId('production-route-partial')).not.toBeInTheDocument()
  })

  it('partial（只命中一维）：提示另一半取默认值，且不显示成 default', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('partial', '纱帘×韩褶')))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-route-partial')).toBeInTheDocument())
    expect(screen.getByTestId('production-route-partial')).toHaveTextContent('只填了一半')
    expect(screen.queryByTestId('production-route-default')).not.toBeInTheDocument()
  })

  it('missing_route（两维都命中但库里没这条路线）：报出识别到的键 route_requested_key', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('missing_route', '布帘×韩褶', '罗马帘×韩褶')))
    render(<ProductionDetailPage />)

    await waitFor(() => expect(screen.getByTestId('production-route-missing_route')).toBeInTheDocument())
    expect(screen.getByTestId('production-route-missing_route')).toHaveTextContent('工序库里没有这条路线')
    expect(screen.getByTestId('production-route-missing_route-detail')).toHaveTextContent('本单识别的是 罗马帘×韩褶')
    expect(screen.getByTestId('production-route-missing_route-detail')).toHaveTextContent('本单实际使用：布帘×韩褶')
  })

  it('derived（正常派生）/ 字段缺失：不提示，且不得把「未知」显示成「已派生」', async () => {
    mockDetail.mockReset().mockResolvedValue(ok(withRoute('derived', '布帘×韩褶')))
    const { unmount } = render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-route-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-partial')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-missing_route')).not.toBeInTheDocument()
    unmount()

    // 存量实例（字段缺失）⇒ 静默 = 未知，不提示任何来源
    mockDetail.mockReset().mockResolvedValue(ok(PROCESSING_ORDER))
    render(<ProductionDetailPage />)
    await waitFor(() => expect(screen.getByTestId('production-header')).toBeInTheDocument())
    expect(screen.queryByTestId('production-route-default')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-partial')).not.toBeInTheDocument()
    expect(screen.queryByTestId('production-route-missing_route')).not.toBeInTheDocument()
  })
})
