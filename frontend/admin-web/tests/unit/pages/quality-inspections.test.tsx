// case_ids: UI-118, PG-087
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/**
 * 质检记录页（`/quality-inspections`，issue #7140 = #5652 的**商家面**）—— 大菜单「生产管理 ▸ 质检记录」。
 *
 * ## 这一页为什么存在
 *
 * 质检的载体（`quality_inspections` 表 + 成品帘级三态判定 + 原因必填 + 独立质检员岗位）与工人端报工
 * 三态早在 issue #5652 就落了，但 `frontend/admin-web` 里**一处消费都没有** ⇒ 质检员登录观星台没有
 * 工作台、商家看不到任何质检读数（用户 2026-10-17 实测原话：「之前让你做过质检流程，我看在观星台上
 * 没有任何地方体现出来了」）。
 *
 * ## 本文件钉住的事（每条都能单独变红）
 *
 * ① **待检成品帘看得见**：一条 = 一件成品帘（加工单号 / 订单号 / 成品帘名 / 最新判定；issue #7160 ——
 *    「数量」列已移除，弹窗里的判定与它无关），未检 ⇒ 显示「未检」（🔴 **不是**「合格」）；操作位是「录入判定」；
 * ② 🔴 **判定 ≠ 合格 ⇒ 原因必填**（前端拦一次：不白跑网络；服务端 422 才是真判据）；
 * ③ **提交体逐字段正确**：`order_item_id` / `result` / `reason`（合格时不带空原因）；
 * ④ 🔴 **读失败不印计数**：`counts` 只来自成功的读 —— 失败时摘要行说「数量读不到」，
 *    绝不出现「未检 0 件」这种**事实性假陈述**（同族：issue #6691 / #6703）；
 * ⑤ **空态 ≠ 失败**：真的没有待检行时才显示空态文案。
 */

const mockTargets = vi.fn()
const mockList = vi.fn()
const mockCreate = vi.fn()
const mockStats = vi.fn()

vi.mock('@/lib/api', () => ({
  qualityInspectionApi: {
    targets: (...args: unknown[]) => mockTargets(...args),
    list: (...args: unknown[]) => mockList(...args),
    create: (...args: unknown[]) => mockCreate(...args),
    stats: (...args: unknown[]) => mockStats(...args),
  },
}))

vi.mock('@/lib/permission', () => ({
  usePermission: () => ({
    has: () => true,
    permissions: ['production:inspect'],
    isAdmin: false,
  }),
}))

import QualityInspectionsPage from '@/app/(dashboard)/quality-inspections/page'

const pendingTarget = {
  order_item_id: 'item-1',
  processing_order_id: 'po-1',
  processing_order_no: 'JG-20261017-0001',
  order_no: 'DD-20261017-0001',
  processing_status: 'in_processing',
  product_name: '布艺遮光帘A',
  color_name: '米白',
  quantity: 2,
  unit: '套',
  state: 'pending' as const,
  latest: null,
}

const passedTarget = {
  ...pendingTarget,
  order_item_id: 'item-2',
  processing_order_no: 'JG-20261017-0002',
  order_no: 'DD-20261017-0002',
  product_name: '布艺遮光帘B',
  state: 'pass' as const,
  latest: {
    id: 'qi-2',
    order_item_id: 'item-2',
    processing_order_id: 'po-1',
    position_name: '布艺遮光帘B 米白',
    result: 'pass' as const,
    result_label: '合格',
    reason: null,
    inspector_name: '质检员小李',
    inspected_at: '2026-10-17T10:30:00+08:00',
  },
}

const passRecord = {
  id: 'qi-2',
  order_item_id: 'item-2',
  processing_order_id: 'po-1',
  position_name: '布艺遮光帘B 米白',
  result: 'pass',
  result_label: '合格',
  reason: null,
  inspector_name: '质检员小李',
  inspected_at: '2026-10-17T10:30:00+08:00',
}

function mockOkTargets(overrides: Partial<{
  items: unknown[]
  total: number
  counts: Record<string, number>
}> = {}) {
  mockTargets.mockResolvedValue({
    data: {
      data: {
        items: overrides.items ?? [pendingTarget, passedTarget],
        total: overrides.total ?? 2,
        page: 1,
        size: 20,
        counts: overrides.counts ?? { pending: 1, pass: 1, rework: 0, scrap: 0 },
      },
    },
  })
}

describe('质检记录页（/quality-inspections）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockList.mockResolvedValue({ data: { data: [passRecord] } })
    mockCreate.mockResolvedValue({ data: { data: passRecord } })
    mockStats.mockResolvedValue({
      data: {
        data: {
          window: { from: null, to: null, name: null },
          bucket: 'day',
          min_sample: 20,
          counts: { inspected: 2, first_pass: 1, current_pass: 1, rework: 1, scrap: 0 },
          rates: {
            first_pass_rate: 0.5,
            current_pass_rate: 0.5,
            rework_rate: 0.5,
            scrap_rate: 0,
          },
          trend: [],
          by_processing_order: [],
          by_product: [],
          by_inspector: [],
          backlog: { pending: 1, oldest_pending_hours: 2, approximate: true, approximate_from: 'processing_order.created_at' },
        },
      },
    })
    mockOkTargets()
  })

  it('⓪ 指标面板：默认「本月」拉一次，首检合格率与样本量同屏（issue #7192）', async () => {
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(mockStats).toHaveBeenCalledTimes(1))
    expect(mockStats.mock.calls[0][0]).toMatchObject({ bucket: 'day' })
    expect(await screen.findByTestId('quality-metric-first-pass')).toHaveTextContent('50.0%')
    expect(screen.getByTestId('quality-metric-sample')).toHaveTextContent('已检 2 件')
    expect(screen.getByTestId('quality-metrics-window-month')).toHaveAttribute('aria-pressed', 'true')
  })

  it('① 待检清单：未检显示「未检」（不是「合格」）且操作位是「录入判定」', async () => {
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(mockTargets).toHaveBeenCalled())
    expect(await screen.findByTestId('quality-targets-card')).toBeInTheDocument()
    expect(await screen.findByTestId('quality-target-item-1')).toBeInTheDocument()
    expect(screen.getByText('JG-20261017-0001')).toBeInTheDocument()
    // issue #7160：加工单对应的订单号同屏给出；「数量」列已移除（一行 = 一件成品帘，数量不构成判定输入）
    expect(screen.getByText('DD-20261017-0001')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '订单号' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '数量' })).not.toBeInTheDocument()
    expect(screen.getByText('布艺遮光帘A（米白）')).toBeInTheDocument()
    expect(screen.getByTestId('quality-target-state-item-1')).toHaveTextContent('未检')
    expect(screen.getByTestId('quality-target-state-item-2')).toHaveTextContent('合格')
    expect(screen.getByTestId('quality-target-record-item-1')).toHaveTextContent('录入判定')
    expect(screen.getByTestId('quality-target-record-item-2')).toHaveTextContent('复检')

    // 摘要行 = 逐状态条数（不是比率）
    expect(screen.getByTestId('quality-state-summary')).toHaveTextContent('未检 1 件')
    expect(screen.getByTestId('quality-state-summary')).toHaveTextContent('合格 1 件')
  })

  it('② 判定为返工而原因留空 ⇒ 当场提示，且不调提交端点', async () => {
    const user = userEvent.setup()
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-target-record-item-1')).toBeInTheDocument())
    await user.click(screen.getByTestId('quality-target-record-item-1'))
    await user.click(screen.getByTestId('quality-result-rework'))
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    expect(screen.getByTestId('quality-inspection-form-error')).toHaveTextContent('必须填写不合格原因')
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('③ 填写原因后提交：请求体逐字段正确（order_item_id / result / reason）', async () => {
    const user = userEvent.setup()
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-target-record-item-1')).toBeInTheDocument())
    await user.click(screen.getByTestId('quality-target-record-item-1'))
    await user.click(screen.getByTestId('quality-result-rework'))
    await user.type(screen.getByTestId('quality-inspection-reason'), '布面污渍')
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        order_item_id: 'item-1',
        result: 'rework',
        reason: '布面污渍',
      }),
    )
  })

  it('④ 判定为合格 ⇒ 请求体不带原因（空串不送）', async () => {
    const user = userEvent.setup()
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-target-record-item-1')).toBeInTheDocument())
    await user.click(screen.getByTestId('quality-target-record-item-1'))
    await user.click(screen.getByTestId('quality-result-pass'))
    await user.click(screen.getByRole('button', { name: '提交判定' }))

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({ order_item_id: 'item-1', result: 'pass' }),
    )
  })

  it('⑤ 🔴 待检清单读失败 ⇒ 失败锚常驻 + 计数行说「读不到」（绝不印「未检 0 件」）', async () => {
    mockTargets.mockRejectedValue(new Error('500'))
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-targets-load-error')).toBeInTheDocument())
    expect(screen.getByTestId('quality-targets-load-error')).toHaveAttribute('role', 'alert')
    expect(screen.getByTestId('quality-state-summary')).toHaveTextContent('数量读不到')
    expect(screen.getByTestId('quality-state-summary')).not.toHaveTextContent('未检 0 件')
    // 真没有数据 ≠ 读不到：失败时不得出现空态断言
    expect(screen.queryByTestId('quality-targets-empty')).not.toBeInTheDocument()
  })

  it('⑥ 真的没有待检行 ⇒ 空态（与读失败是两句话）', async () => {
    mockOkTargets({ items: [], total: 0, counts: { pending: 0, pass: 0, rework: 0, scrap: 0 } })
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-targets-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('quality-targets-load-error')).not.toBeInTheDocument()
    expect(screen.getByTestId('quality-state-summary')).toHaveTextContent('未检 0 件')
  })

  it('⑦ 流水读失败 ⇒ 流水区失败锚；不把「读不到」画成「还没有质检记录」', async () => {
    mockList.mockRejectedValue(new Error('500'))
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-records-load-error')).toBeInTheDocument())
    expect(screen.queryByTestId('quality-records-empty')).not.toBeInTheDocument()
  })

  it('⑧ 🔴 点「录入判定」⇒ 弹窗（role=dialog）当场可见；取消后关闭且零请求', async () => {
    const user = userEvent.setup()
    render(<QualityInspectionsPage />)

    await waitFor(() => expect(screen.getByTestId('quality-target-record-item-1')).toBeInTheDocument())
    await user.click(screen.getByTestId('quality-target-record-item-1'))

    // issue #7160：旧形态把表单渲染在整张列表卡片**最底部**（分页之后）⇒ 点击后视口内毫无变化，
    // 用户读成「点了没反应」。判据 = 点完当场有 `role=dialog`（且标题带上这一件的名字）。
    expect(await screen.findByRole('dialog', { name: /录入质检判定/ })).toBeInTheDocument()
    expect(screen.getByTestId('quality-inspection-form')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(mockCreate).not.toHaveBeenCalled()
  })
})
