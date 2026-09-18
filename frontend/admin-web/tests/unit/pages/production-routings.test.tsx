// case_ids: PG-020, PP-014
// PG-020（issue #4203 / #4204）+ PP-014（issue #4307）**合并后**的单页用户面（issue #4416）：
// 工序库与工艺路线合并为「工艺配置」/production/routings —— 两半能力**一个都不能少**。
//
// ① 工序库半边（原 /production/operations）：GET /operations-catalog 按分组渲染真实工序
//    （名称/部位/作用域/单位/计件单价/必完），并支持改单价 / 必完开关 / 作用域（PUT）；
// ② 路线半边（原 /production/routings）：路线序列渲染 + 从**工序库调色板**选工序 → 上移/下移/删除
//    → 保存（PUT /routings/{id}，body {operations:[…]} 且**顺序等于屏幕顺序**）；
// ③ 保存被拒逐条展示后端护栏理由（`error.details[].message`），空序列本地拦；
// ④ 缺口区**分类**：有意挂起（等客户确认 #4261）vs 真的没进路线 —— 前者不得被渲染成「系统漏了」；
// ⑤ 新建路线 / 新增工序 / 信号映射增删改；
// ⑥ 就绪度检查器把「工序 → 路线」的先后依赖显性化；空序列路线标为「空壳 · 不可用」；
// ⑦ 新建路线后**自动进入序列编辑**（消灭「建壳了但没排序」的静默态）；
// ⑧ 行业模板卡**仅工序库为空时**出现（开租已自动套用，见 RegistrationService），补套能力不退化；
// ⑨ 信号映射**降级为存量单兜底**（折叠区）且文案按 R-f 改写（#4385）；
// ⑩ 任一只读端点失败不得白屏，失败处给可读提示。
// 反 placeholder：断言落**真实数据行**与**请求体**，不断言「页面存在」。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetRoutings = vi.fn()
const mockUpdateRoutingSequence = vi.fn()
const mockCreateRouting = vi.fn()
const mockGetOperationsCatalog = vi.fn()
const mockCreateOperation = vi.fn()
const mockUpdateOperation = vi.fn()
const mockGetRoutingGaps = vi.fn()
const mockGetRouteSignals = vi.fn()
const mockCreateRouteSignal = vi.fn()
const mockUpdateRouteSignal = vi.fn()
const mockDeleteRouteSignal = vi.fn()
const mockGetSeedTemplates = vi.fn()
const mockApplySeedTemplate = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getRoutings: (...a: unknown[]) => mockGetRoutings(...a),
    updateRoutingSequence: (...a: unknown[]) => mockUpdateRoutingSequence(...a),
    createRouting: (...a: unknown[]) => mockCreateRouting(...a),
    getOperationsCatalog: (...a: unknown[]) => mockGetOperationsCatalog(...a),
    createOperation: (...a: unknown[]) => mockCreateOperation(...a),
    updateOperation: (...a: unknown[]) => mockUpdateOperation(...a),
    getRoutingGaps: (...a: unknown[]) => mockGetRoutingGaps(...a),
    getRouteSignals: (...a: unknown[]) => mockGetRouteSignals(...a),
    createRouteSignal: (...a: unknown[]) => mockCreateRouteSignal(...a),
    updateRouteSignal: (...a: unknown[]) => mockUpdateRouteSignal(...a),
    deleteRouteSignal: (...a: unknown[]) => mockDeleteRouteSignal(...a),
    getSeedTemplates: (...a: unknown[]) => mockGetSeedTemplates(...a),
    applySeedTemplate: (...a: unknown[]) => mockApplySeedTemplate(...a),
  },
}))

import { toast } from 'sonner'
import ProcessConfigPage from '@/app/(dashboard)/production/routings/page'

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 工序库（库口径）：含 作用域 / provenance / 必完 / 首工序 —— 合并后左栏即调色板 */
const CATALOG = {
  total: 4,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 'op-v54-01', name: '精裁-布', group: '裁剪', position: '布帘', scope: 'position', unit: '套', unit_price: 8.5, is_must_finish: true, is_start_marker: true, source: '占位待确认' },
        { id: 'op-v54-02', name: '裁剪-布', group: '裁剪', position: '布帘', scope: 'position', unit: '套', unit_price: 7, is_must_finish: false, is_start_marker: true },
      ],
    },
    {
      group: '车位',
      operations: [
        { id: 'op-v54-03', name: '韩褶-布', group: '车位', position: '布帘', scope: 'position', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
      ],
    },
    {
      group: '后道',
      operations: [
        { id: 'op-v54-04', name: '外帘装袋', group: '后道', position: '外帘', scope: 'set', unit: '件', unit_price: 0.4, is_must_finish: true, is_start_marker: false },
      ],
    },
  ],
}

/**
 * 路线：一条正常（布帘×韩褶）+ 一条**空壳**（纱帘×韩褶，`operation_count: 0`）。
 * 空壳来自 `POST /routings` 允许 `operations` 缺省（服务端护栏「空序列拒」只拦 PUT）
 * ⇒ 它会被 `findRouting` 正常命中并返回 0 道工序 ⇒ **该部位静默拿到 0 道工序**。
 */
const ROUTINGS = {
  total: 2,
  routings: [
    {
      id: 11,
      curtain_type: '布帘',
      craft: '韩褶',
      operation_count: 3,
      operations: [
        { seq: 1, operation: '精裁-布', group: '裁剪', unit: '套', unit_price: 8.5, is_must_finish: true, is_start_marker: true },
        { seq: 2, operation: '韩褶-布', group: '车位', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
        { seq: 3, operation: '外帘装袋', group: '后道', unit: '件', unit_price: 0.4, is_must_finish: true, is_start_marker: false },
      ],
    },
    { id: 12, curtain_type: '纱帘', craft: '韩褶', operation_count: 0, operations: [] },
  ],
}

/**
 * 缺口真值：`裁剪-布/裁剪-纱/质检/腰靠垫` 是**有意挂起、等客户确认**（#4261），
 * 后端 `routingGaps()` 明写「不要让商家/前端把它们读成「系统漏了」」⇒ 必须与真缺口分开渲染。
 */
const GAPS = {
  unrouted_operations: [
    { name: '裁剪-布', group_name: '裁剪', unit: '套', unit_price: 7, pending_confirmation: true, note: '有意挂起、等客户输入（issue #4261 提问清单）' },
    { name: '裁剪-纱', group_name: '裁剪', unit: '套', unit_price: 6, pending_confirmation: true, note: '有意挂起、等客户输入（issue #4261 提问清单）' },
    { name: '质检', group_name: '后道', unit: '件', unit_price: 1.5, pending_confirmation: true, note: '有意挂起、等客户输入（issue #4261 提问清单）' },
    { name: '腰靠垫', group_name: '其他', unit: '个', unit_price: 3, pending_confirmation: true, note: '有意挂起、等客户输入（issue #4261 提问清单）' },
    { name: '打孔-布', group_name: '车位', unit: '个', unit_price: 0.6, pending_confirmation: false, note: '该工序有价但没有任何活跃路线消费它' },
  ],
  unrouted_operation_total: 5,
  pending_confirmation_total: 4,
  signal_keys_without_route: [{ curtain_type: '罗马帘', craft: '韩褶', route_key: '罗马帘×韩褶', signal: '罗马帘' }],
}

const SIGNALS = {
  total: 2,
  signals: [
    { id: 31, signal: '帘头', curtain_type: '帘头', craft: '韩褶' },
    { id: 32, signal: '纱', curtain_type: '纱帘', craft: '韩褶' },
  ],
}

const TEMPLATES = [
  { templateId: 'curtain', industry: 'curtain', name: '布艺窗帘行业模板', version: 1, description: '35 道工序 + 9 条路线' },
]

/** 后端护栏失败响应体（**真实**信封：`error.details[].message` 逐条理由 —— issue #4308「冻结补遗 ②」） */
const guardError = (reasons: string[]) => ({
  response: {
    status: 422,
    data: {
      success: false,
      error: {
        code: 'VALIDATION_ERROR',
        message: `工艺路线校验未通过：${reasons.length} 项`,
        details: reasons.map((message, i) => ({ field: `operations[${i}]`, message })),
      },
      suggestion: '请修正后重试',
    },
  },
  message: 'Request failed with status code 422',
})

/** 展开折叠的「存量单兜底 · 信号映射」区（默认收起：它是兜底层，不是主配置步骤） */
const openSignalSection = async () => {
  // 先等页面加载完（收起态下 toggle 才在 DOM 里）
  await waitFor(() => expect(screen.getByTestId('route-signals-toggle')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('route-signals-toggle'))
  await waitFor(() => expect(screen.getByTestId('route-signals-body')).toBeInTheDocument())
}

describe('工艺配置页 /production/routings（工序库 + 工艺路线合并，issue #4416）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockGetRoutingGaps.mockReset().mockResolvedValue(ok(GAPS))
    mockGetRouteSignals.mockReset().mockResolvedValue(ok(SIGNALS))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockApplySeedTemplate.mockReset().mockResolvedValue(ok({ created_operations: 35, created_routings: 9, skipped: 0 }))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-03', name: '韩褶-布', unit_price: 2.5 }))
    mockUpdateRoutingSequence.mockReset().mockResolvedValue(ok({ id: 11 }))
    mockCreateRouting.mockReset().mockResolvedValue(ok({ id: 13, curtain_type: '罗马帘', craft: '韩褶', operation_count: 0, operations: [] }))
    mockCreateOperation.mockReset().mockResolvedValue(ok({ id: 'op-new' }))
    mockCreateRouteSignal.mockReset().mockResolvedValue(ok({ id: 33 }))
    mockUpdateRouteSignal.mockReset().mockResolvedValue(ok({ id: 31 }))
    mockDeleteRouteSignal.mockReset().mockResolvedValue(ok(undefined))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  // ────────────────────────── ① 工序库半边（PG-020） ──────────────────────────

  it('工序库半边：真实工序数据（总数 + 工序名 + 库口径单价）与路线半边**同页共存**', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('4'))
    // 判据 3：同一页面上两半同时可见（不再是两个菜单各一半）
    expect(screen.getByTestId('routings-total')).toHaveTextContent('2')

    expect(within(screen.getByTestId('operation-row-op-v54-03')).getByText('韩褶-布')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-op-v54-01')).getByText('精裁-布')).toBeInTheDocument()
    expect(screen.getByTestId('operation-row-op-v54-03')).toHaveTextContent('¥1.20')
    expect(screen.getByTestId('operation-row-op-v54-01')).toHaveTextContent('¥8.50')
  })

  it('工序库半边：按分组展示（裁剪/车位/后道 三个分组标题 + 各自行数）', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-group-裁剪')).toBeInTheDocument())
    expect(within(screen.getByTestId('operation-group-裁剪')).getAllByTestId(/^operation-row-/)).toHaveLength(2)
    expect(within(screen.getByTestId('operation-group-车位')).getAllByTestId(/^operation-row-/)).toHaveLength(1)
    expect(within(screen.getByTestId('operation-group-后道')).getAllByTestId(/^operation-row-/)).toHaveLength(1)
  })

  it('工序库半边：必完开关按库口径渲染，且 is_start_marker 不显示为「必完」', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-04')).toBeInTheDocument())
    expect(within(screen.getByTestId('operation-row-op-v54-04')).getByTestId('operation-must-finish-op-v54-04')).toBeChecked()
    expect(within(screen.getByTestId('operation-row-op-v54-02')).getByTestId('operation-must-finish-op-v54-02')).not.toBeChecked()
    // 首工序（is_start_marker）**不是**「必完」：op-v54-02 是首工序但库口径 is_must_finish=false
    // ⇒ 必须显示「首工序」徽标、**不得**显示「必完」（把首工序误当完工门槛 = 这张单永远完不了工）
    const startMarkerRow = screen.getByTestId('operation-row-op-v54-02')
    expect(startMarkerRow).toHaveTextContent('首工序')
    expect(within(startMarkerRow).queryByText('必完')).not.toBeInTheDocument()
  })

  it('工序库半边：作用域（部位级/套级）逐行可见且可改，走 PUT 只提交 scope', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-scope-op-v54-04')).toBeInTheDocument())
    expect(screen.getByTestId('operation-scope-op-v54-04')).toHaveValue('set')
    expect(screen.getByTestId('operation-scope-op-v54-03')).toHaveValue('position')

    await userEvent.selectOptions(screen.getByTestId('operation-scope-op-v54-03'), 'set')
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-03', { scope: 'set' }))
  })

  it('工序库半边：改单价 → 保存 → PUT 只提交 unit_price 并刷新工序库', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-03')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('operation-price-edit-op-v54-03'))
    const input = screen.getByTestId('operation-price-input-op-v54-03')
    await userEvent.clear(input)
    await userEvent.type(input, '2.5')
    await userEvent.click(screen.getByTestId('operation-price-save-op-v54-03'))

    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-03', { unit_price: 2.5 }))
    await waitFor(() => expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(2))
  })

  it('工序库半边：切必完开关 → PUT 提交 is_must_finish 布尔值', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-03')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('operation-must-finish-op-v54-03'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-03', { is_must_finish: true }))
  })

  it('工序库半边：改单价失败 → toast.error 且不刷新（不把失败伪装成成功）', async () => {
    mockUpdateOperation.mockRejectedValueOnce(new Error('403 forbidden'))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-03')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('operation-price-edit-op-v54-03'))
    const input = screen.getByTestId('operation-price-input-op-v54-03')
    await userEvent.clear(input)
    await userEvent.type(input, '9.9')
    await userEvent.click(screen.getByTestId('operation-price-save-op-v54-03'))

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalled())
    expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(1)
  })

  // ────────────────────────── ② 路线半边（PP-014） ──────────────────────────

  it('路线半边：真实路线数据（路线数 + 部位×工艺标题 + 每道工序含单位/单价/必完）', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    const box = screen.getByTestId('routing-布帘×韩褶')
    expect(box).toHaveTextContent('3 道工序')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-1')).toHaveTextContent('精裁-布')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-1')).toHaveTextContent('¥8.50')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-2')).toHaveTextContent('¥1.20')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-3')).toHaveTextContent('必完')
  })

  it('序列编辑：从左栏工序库点「加入」→ 保存 → PUT 的 operations 顺序等于屏幕顺序', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-1')).toHaveTextContent('精裁-布')
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-1')).toHaveTextContent('必完')

    // 左栏调色板直接加入（不再需要「从工序库添加」下拉 —— 工序库就在同一页）
    await userEvent.click(screen.getByTestId('operation-add-op-v54-02'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(mockUpdateRoutingSequence).toHaveBeenCalledWith(11, {
        operations: ['精裁-布', '韩褶-布', '外帘装袋', '裁剪-布'],
      }),
    )
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByTestId('routing-save-布帘×韩褶')).not.toBeInTheDocument())
  })

  it('序列编辑：未进入编辑态时左栏「加入」不可用（避免误加进别的路线）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-add-op-v54-03')).toBeInTheDocument())

    expect(screen.getByTestId('operation-add-op-v54-03')).toBeDisabled()
    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    expect(screen.getByTestId('operation-add-op-v54-03')).toBeEnabled()
  })

  it('序列编辑：下移改变顺序后保存，PUT 请求体的顺序随之变化', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-draft-down-布帘×韩褶-1'))
    expect(screen.getByTestId('routing-draft-name-布帘×韩褶-1')).toHaveTextContent('韩褶-布')
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(mockUpdateRoutingSequence).toHaveBeenCalledWith(11, {
        operations: ['韩褶-布', '精裁-布', '外帘装袋'],
      }),
    )
  })

  it('序列编辑：删除一道后保存，被删工序不再出现在请求体里', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-draft-remove-布帘×韩褶-2'))
    expect(screen.queryByTestId('routing-draft-step-布帘×韩褶-3')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(mockUpdateRoutingSequence).toHaveBeenCalledWith(11, { operations: ['精裁-布', '外帘装袋'] }),
    )
  })

  it('空序列：本地拦住不发请求，并说明为什么不能空', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-纱帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-纱帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-纱帘×韩褶'))

    await waitFor(() => expect(screen.getByTestId('routing-error-纱帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('序列不能为空')
    expect(mockUpdateRoutingSequence).not.toHaveBeenCalled()
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  it('保存被拒（护栏）：后端每条理由**逐条**展示，不合并成一句「保存失败」', async () => {
    mockUpdateRoutingSequence.mockRejectedValueOnce(
      guardError([
        '工序「罗马帘-打孔」不在工序库中',
        '工序「裁剪-布」在序列中重复出现 2 次',
        '路线至少要有一道必完工序（当前 0 道）',
      ]),
    )
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() => expect(screen.getByTestId('routing-error-布帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('工序不存在：工序「罗马帘-打孔」不在工序库中')
    expect(screen.getByTestId('routing-error-item-1')).toHaveTextContent('工序重复：')
    expect(screen.getByTestId('routing-error-item-2')).toHaveTextContent('缺少必完工序：')
    expect(within(screen.getByTestId('routing-error-布帘×韩褶')).getAllByTestId(/^routing-error-item-/)).toHaveLength(3)
    expect(screen.getByTestId('routing-save-布帘×韩褶')).toBeInTheDocument()
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  it('保存被拒（无 details 时退化）：只有 error.message 也逐条可读，不得弹通用文案', async () => {
    mockUpdateRoutingSequence.mockRejectedValueOnce({
      response: {
        status: 422,
        data: { success: false, error: { code: 'VALIDATION_ERROR', message: '路线至少要有一道必完工序' } },
      },
      message: 'Request failed with status code 422',
    })
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('缺少必完工序：路线至少要有一道必完工序'),
    )
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument()
  })

  it('新增工序：提交名称/分组/单位/单价（POST /production/operations）并刷新工序库', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('routings-new-operation'))
    await userEvent.type(screen.getByTestId('routings-create-op-name'), '罗马帘-穿杆')
    await userEvent.type(screen.getByTestId('routings-create-op-group_name'), '车位')
    await userEvent.type(screen.getByTestId('routings-create-op-unit'), '套')
    await userEvent.type(screen.getByTestId('routings-create-op-unit_price'), '4.5')
    await userEvent.click(screen.getByTestId('routings-create-operation-submit'))

    await waitFor(() =>
      expect(mockCreateOperation).toHaveBeenCalledWith({
        name: '罗马帘-穿杆',
        group_name: '车位',
        unit: '套',
        unit_price: 4.5,
      }),
    )
    await waitFor(() => expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(2))
  })

  // ────────────────────────── ⑥⑦ 引导：就绪度 + 空壳 + 自动进编辑 ──────────────────────────

  it('新建路线：POST /routings 后**自动进入序列编辑**（消灭「建壳了但没排序」的静默态）', async () => {
    // 第二次拉取时新路线已在库里（真实后端行为）—— 空序列路线
    mockGetRoutings
      .mockReset()
      .mockResolvedValueOnce(ok(ROUTINGS))
      .mockResolvedValue(
        ok({
          total: 3,
          routings: [...ROUTINGS.routings, { id: 13, curtain_type: '罗马帘', craft: '韩褶', operation_count: 0, operations: [] }],
        }),
      )
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('routings-new-route'))
    await userEvent.type(screen.getByTestId('routings-create-curtain-type'), '罗马帘')
    await userEvent.type(screen.getByTestId('routings-create-craft'), '韩褶')
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({ curtain_type: '罗马帘', craft: '韩褶', operations: [] }),
    )
    // 已自动进入该路线的编辑态（而不是只 toast 一下就结束）
    await waitFor(() => expect(screen.getByTestId('routing-save-罗马帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-empty-罗马帘×韩褶')).toHaveTextContent('从左侧工序库')
  })

  it('空壳路线（序列为空）标为「空壳 · 不可用」并说明后果（该部位会静默拿到 0 道工序）', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routing-纱帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-empty-shell-纱帘×韩褶')).toHaveTextContent('空壳')
    expect(screen.getByTestId('routing-纱帘×韩褶')).toHaveTextContent('0 道工序')
    // 正常路线不得被误标
    expect(screen.queryByTestId('routing-empty-shell-布帘×韩褶')).not.toBeInTheDocument()
  })

  it('就绪度检查器：三步状态可读，空壳路线让「工艺路线」步判为未完成', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('process-readiness')).toBeInTheDocument())
    expect(screen.getByTestId('readiness-step-operations')).toHaveAttribute('data-state', 'done')
    // 有一条空壳路线 ⇒ 路线步未完成（否则该部位静默 0 工序）
    expect(screen.getByTestId('readiness-step-routings')).toHaveAttribute('data-state', 'todo')
    expect(screen.getByTestId('readiness-step-routings')).toHaveTextContent('空壳')
    expect(screen.getByTestId('readiness-step-gaps')).toHaveAttribute('data-state', 'todo')
  })

  it('就绪度检查器：工序库为空 ⇒ 第 ① 步未完成，且行业模板补救卡出现', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok({ total: 0, groups: [] }))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('readiness-step-operations')).toHaveAttribute('data-state', 'todo'))
    expect(screen.getByTestId('seed-templates')).toBeInTheDocument()
  })

  // ────────────────────────── ④ 缺口分类（有意挂起 vs 真缺口） ──────────────────────────

  it('缺口区：真未进路线（打孔-布）与**有意挂起**（裁剪-布/裁剪-纱/质检/腰靠垫）分开渲染', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-gap-unrouted-count')).toHaveTextContent('1'))
    expect(screen.getByTestId('routings-gap-pending-count')).toHaveTextContent('4')

    // 真缺口：可行动
    expect(screen.getByTestId('routings-gap-unrouted-打孔-布')).toHaveTextContent('¥0.60')
    // 有意挂起：带「等客户确认」说明，**不得**渲染成「系统漏了」
    for (const name of ['裁剪-布', '裁剪-纱', '质检', '腰靠垫']) {
      expect(screen.getByTestId(`routings-gap-pending-${name}`)).toBeInTheDocument()
      expect(screen.queryByTestId(`routings-gap-unrouted-${name}`)).not.toBeInTheDocument()
    }
    expect(screen.getByTestId('routings-gap-pending-裁剪-布')).toHaveTextContent('等客户确认')
    // 无路线的信号组合：罗马帘目前会回落到默认路线，必须可见
    expect(screen.getByTestId('routings-gap-signal-罗马帘-韩褶')).toHaveTextContent('罗马帘 × 韩褶')
  })

  // ────────────────────────── ⑧ 行业模板：仅空态补救 ──────────────────────────

  it('行业模板卡：工序库非空时**不渲染**（开租已自动套用，不该让用户手动点）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('4'))
    expect(screen.queryByTestId('seed-templates')).not.toBeInTheDocument()
  })

  it('行业模板卡（空态补救）：套用走 POST 并报服务端真实数字', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok({ total: 0, groups: [] }))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('seed-template-apply-curtain')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('seed-template-apply-curtain'))
    await userEvent.click(screen.getByTestId('seed-template-apply-confirm'))

    await waitFor(() => expect(mockApplySeedTemplate).toHaveBeenCalledWith('curtain'))
    await waitFor(() =>
      expect(vi.mocked(toast.success)).toHaveBeenCalledWith(expect.stringContaining('新增 35 道工序')),
    )
  })

  // ────────────────────────── ⑤⑨ 信号映射：降级为存量单兜底 ──────────────────────────

  it('信号映射区：默认收起，展开后文案说明它只在**订单没填部位/工艺**时兜底', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('route-signals-section')).toBeInTheDocument())

    // 默认收起（它是兜底层，不是主配置步骤）
    expect(screen.queryByTestId('route-signals-body')).not.toBeInTheDocument()
    expect(screen.getByTestId('route-signals-section')).toHaveTextContent('存量单兜底')

    await openSignalSection()
    // R-f（#4385）口径：不再是「命中优先于默认路线」的主路径
    expect(screen.getByTestId('route-signals-section')).toHaveTextContent('订单没有填')
    expect(screen.getByTestId('route-signals-section')).not.toHaveTextContent('命中优先于默认路线')
  })

  it('信号映射：列表渲染 + 新增走 POST /production/route-signals', async () => {
    render(<ProcessConfigPage />)
    await openSignalSection()
    await waitFor(() => expect(screen.getByTestId('route-signal-31')).toHaveTextContent('帘头'))

    await userEvent.click(screen.getByTestId('route-signal-new'))
    await userEvent.type(screen.getByTestId('route-signal-signal'), '罗马帘')
    await userEvent.type(screen.getByTestId('route-signal-curtain_type'), '罗马帘')
    await userEvent.type(screen.getByTestId('route-signal-craft'), '韩褶')
    await userEvent.click(screen.getByTestId('route-signal-submit'))

    await waitFor(() =>
      expect(mockCreateRouteSignal).toHaveBeenCalledWith({ signal: '罗马帘', curtain_type: '罗马帘', craft: '韩褶' }),
    )
  })

  it('信号映射：编辑走 PUT /{id}、删除走 DELETE /{id}（二次确认后）', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ProcessConfigPage />)
    await openSignalSection()
    await waitFor(() => expect(screen.getByTestId('route-signal-32')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('route-signal-edit-32'))
    const curtainInput = screen.getByTestId('route-signal-curtain_type')
    await userEvent.clear(curtainInput)
    await userEvent.type(curtainInput, '纱帘(改)')
    await userEvent.click(screen.getByTestId('route-signal-submit'))
    await waitFor(() =>
      expect(mockUpdateRouteSignal).toHaveBeenCalledWith(32, { signal: '纱', curtain_type: '纱帘(改)', craft: '韩褶' }),
    )

    await userEvent.click(screen.getByTestId('route-signal-delete-31'))
    await waitFor(() => expect(mockDeleteRouteSignal).toHaveBeenCalledWith(31))
    expect(confirmSpy).toHaveBeenCalled()
    confirmSpy.mockRestore()
  })

  // ────────────────────────── ⑩ 失败不白屏 ──────────────────────────

  it('路线列表加载失败：错误提示 + 重试（不白屏）', async () => {
    mockGetRoutings.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(ROUTINGS))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-error')).toHaveTextContent('工艺路线加载失败'))
    await userEvent.click(screen.getByTestId('routings-retry'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    expect(screen.queryByTestId('routings-error')).not.toBeInTheDocument()
  })

  it('工序库加载失败：只让左栏给可读提示，路线半边照常渲染（不整页白屏）', async () => {
    mockGetOperationsCatalog.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(CATALOG))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operations-catalog-error')).toHaveTextContent('工序库加载失败'))
    expect(screen.getByTestId('routings-total')).toHaveTextContent('2')
  })

  // ────────────────────────── ⑦ 护栏**就地预检**（不等后端 422） ──────────────────────────

  it('护栏就地预检：序列缺必完工序 ⇒ 编辑区立刻给黄条（这道单永远完不了工）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    // 起始序列有 2 道必完 ⇒ 不该报
    expect(screen.queryByTestId('routing-precheck-布帘×韩褶')).not.toBeInTheDocument()

    // 删掉两道必完工序（seq 1 与 3）⇒ 剩 韩褶-布（非必完）
    await userEvent.click(screen.getByTestId('routing-draft-remove-布帘×韩褶-3'))
    await userEvent.click(screen.getByTestId('routing-draft-remove-布帘×韩褶-1'))

    await waitFor(() => expect(screen.getByTestId('routing-precheck-布帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-precheck-布帘×韩褶')).toHaveTextContent('必完')
    // 预检只是提示，不阻断保存（后端仍是唯一权威）
    expect(screen.getByTestId('routing-save-布帘×韩褶')).toBeEnabled()
  })

  it('护栏就地预检：序列引用了工序库里没有的工序 ⇒ 该行标红并指名', async () => {
    // 路线引用了库中已不存在的工序（停用/被删）—— 保存必被后端拒，但页面必须**先**让人看见
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          {
            id: 11,
            curtain_type: '布帘',
            craft: '韩褶',
            operation_count: 2,
            operations: [
              { seq: 1, operation: '精裁-布', group: '裁剪', unit: '套', unit_price: 8.5, is_must_finish: true },
              { seq: 2, operation: '罗马帘-打孔', group: null, unit: null, unit_price: null, is_must_finish: false },
            ],
          },
        ],
      }),
    )
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))

    await waitFor(() => expect(screen.getByTestId('routing-draft-missing-布帘×韩褶-2')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-missing-布帘×韩褶-2')).toHaveTextContent('工序库中不存在')
    // 库里有的那一道不得被误标
    expect(screen.queryByTestId('routing-draft-missing-布帘×韩褶-1')).not.toBeInTheDocument()
  })

  it('缺口/信号接口失败：页面不白屏，失败处给可读提示（路线列表照常渲染）', async () => {
    mockGetRoutingGaps.mockReset().mockRejectedValueOnce(new Error('500'))
    mockGetRouteSignals.mockReset().mockRejectedValueOnce(new Error('500'))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('routings-gaps-unavailable')).toHaveTextContent('缺口数据加载失败')
    expect(screen.getByTestId('routing-布帘×韩褶')).toBeInTheDocument()
    await openSignalSection()
    expect(screen.getByTestId('route-signals-error')).toHaveTextContent('信号映射加载失败')
  })
})
