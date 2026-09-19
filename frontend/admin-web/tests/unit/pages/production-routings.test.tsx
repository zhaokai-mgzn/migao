// case_ids: PG-020, PP-014
// PG-020（issue #4203 / #4204）+ PP-014（issue #4307）**合并后**的单页用户面（issue #4416）：
// 工序库与工艺路线合并为「工艺配置」/production/routings —— 两半能力**一个都不能少**。
//
// ① 工序库半边（原 /production/operations）：GET /operations-catalog 按分组渲染真实工序
//    （名称/部位/作用域/单位/计件单价/必完），并支持改单价 / 必完开关 / 作用域（PUT）；
// ② 路线半边（原 /production/routings）：路线序列渲染 + 从**工序库调色板**选工序 → 上移/下移/删除
//    → 保存（PUT /routings/{id}，body {operations:[…]} 且**顺序等于屏幕顺序**）；
// ③ 保存被拒逐条展示后端护栏理由（`error.details[].message`），空序列本地拦；
// ④ **两个 tab**（issue #4482）：工艺项 / 工艺路线；缺口区已按用户裁定**整体移除**；
// ⑤ 新建路线 / 新增工序 / 信号映射增删改；
// ⑥ 就绪度检查器把「工序 → 路线」的先后依赖显性化；空序列路线标为「空壳 · 不可用」；
// ⑦ 新建路线后**自动进入序列编辑**（消灭「建壳了但没排序」的静默态）；
// ⑧ 行业模板卡**仅工序库为空时**出现（开租已自动套用，见 RegistrationService），补套能力不退化；
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
const mockGetSeedTemplates = vi.fn()
// issue #4453 探针：信号映射是**研发内部机制**，商家页**不得**消费 ⇒ 它必须恒不被调用
const mockGetRouteSignals = vi.fn()
const mockApplySeedTemplate = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getRoutings: (...a: unknown[]) => mockGetRoutings(...a),
    updateRoutingSequence: (...a: unknown[]) => mockUpdateRoutingSequence(...a),
    createRouting: (...a: unknown[]) => mockCreateRouting(...a),
    getOperationsCatalog: (...a: unknown[]) => mockGetOperationsCatalog(...a),
    createOperation: (...a: unknown[]) => mockCreateOperation(...a),
    updateOperation: (...a: unknown[]) => mockUpdateOperation(...a),
    getSeedTemplates: (...a: unknown[]) => mockGetSeedTemplates(...a),
    getRouteSignals: (...a: unknown[]) => mockGetRouteSignals(...a),
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


/** 渲染并切到「工艺路线」tab（issue #4482：路线内容在第二个 tab，默认落在「工艺项」） */
const renderOnRoutes = async () => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('process-config-tab-routes')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('process-config-tab-routes'))
}

describe('工艺配置页 /production/routings（工序库 + 工艺路线合并，issue #4416）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockGetRouteSignals.mockReset()
    mockApplySeedTemplate.mockReset().mockResolvedValue(ok({ created_operations: 35, created_routings: 9, skipped: 0 }))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-03', name: '韩褶-布', unit_price: 2.5 }))
    mockUpdateRoutingSequence.mockReset().mockResolvedValue(ok({ id: 11 }))
    mockCreateRouting.mockReset().mockResolvedValue(ok({ id: 13, curtain_type: '罗马帘', craft: '韩褶', operation_count: 0, operations: [] }))
    mockCreateOperation.mockReset().mockResolvedValue(ok({ id: 'op-new' }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  // ────────────────────────── ① 工序库半边（PG-020） ──────────────────────────

  it('tab「工艺项」：真实工序数据（总数 + 工序名 + 库口径单价）；切到「工艺路线」看到路线', async () => {
    render(<ProcessConfigPage />)

    // 默认落在「工艺项」tab ⇒ 工序库可见、路线不可见（issue #4482：不再左右平铺）
    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('4'))
    expect(screen.queryByTestId('routings-total')).not.toBeInTheDocument()

    expect(within(screen.getByTestId('operation-row-op-v54-03')).getByText('韩褶-布')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-op-v54-01')).getByText('精裁-布')).toBeInTheDocument()
    expect(screen.getByTestId('operation-row-op-v54-03')).toHaveTextContent('¥1.20')
    expect(screen.getByTestId('operation-row-op-v54-01')).toHaveTextContent('¥8.50')

    // 切到「工艺路线」⇒ 路线可见、工序库不可见（互斥，不堆在一屏）
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    expect(screen.queryByTestId('operations-catalog-total')).not.toBeInTheDocument()
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
    await renderOnRoutes()

    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    const box = screen.getByTestId('routing-布帘×韩褶')
    expect(box).toHaveTextContent('3 道工序')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-1')).toHaveTextContent('精裁-布')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-1')).toHaveTextContent('¥8.50')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-2')).toHaveTextContent('¥1.20')
    expect(within(box).getByTestId('routing-step-布帘×韩褶-3')).toHaveTextContent('必完')
  })

  it('序列编辑：从左栏工序库点「加入」→ 保存 → PUT 的 operations 顺序等于屏幕顺序', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-1')).toHaveTextContent('精裁-布')
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-1')).toHaveTextContent('必完')

    // 工序库在**另一个 tab** ⇒ 编辑器自带「添加工序」选择器（issue #4482）
    await userEvent.selectOptions(screen.getByTestId('routing-add-select-布帘×韩褶'), '裁剪-布')
    await userEvent.click(screen.getByTestId('routing-add-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(mockUpdateRoutingSequence).toHaveBeenCalledWith(11, {
        operations: ['精裁-布', '韩褶-布', '外帘装袋', '裁剪-布'],
      }),
    )
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByTestId('routing-save-布帘×韩褶')).not.toBeInTheDocument())
  })

  it('序列编辑：未进入编辑态时**没有**「添加工序」选择器（避免误加进别的路线）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    expect(screen.queryByTestId('routing-add-select-布帘×韩褶')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    expect(screen.getByTestId('routing-add-select-布帘×韩褶')).toBeInTheDocument()
    // 未选工序时「加入」禁用
    expect(screen.getByTestId('routing-add-布帘×韩褶')).toBeDisabled()
  })

  it('序列编辑：下移改变顺序后保存，PUT 请求体的顺序随之变化', async () => {
    await renderOnRoutes()
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
    await renderOnRoutes()
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
    await renderOnRoutes()
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
    await renderOnRoutes()
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
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.click(screen.getByTestId('routing-save-布帘×韩褶'))

    await waitFor(() =>
      expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('缺少必完工序：路线至少要有一道必完工序'),
    )
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument()
  })

  it('新增工序：提交名称/分组/单位/单价（POST /production/operations）并刷新工序库', async () => {
    await renderOnRoutes()
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
    await renderOnRoutes()
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
    await renderOnRoutes()

    await waitFor(() => expect(screen.getByTestId('routing-纱帘×韩褶')).toBeInTheDocument())
    expect(screen.getByTestId('routing-empty-shell-纱帘×韩褶')).toHaveTextContent('空壳')
    expect(screen.getByTestId('routing-纱帘×韩褶')).toHaveTextContent('0 道工序')
    // 正常路线不得被误标
    expect(screen.queryByTestId('routing-empty-shell-布帘×韩褶')).not.toBeInTheDocument()
  })

  it('就绪度检查器：**两步**状态可读，空壳路线让「工艺路线」步判为未完成', async () => {
    await renderOnRoutes()

    await waitFor(() => expect(screen.getByTestId('process-readiness')).toBeInTheDocument())
    expect(screen.getByTestId('readiness-step-operations')).toHaveAttribute('data-state', 'done')
    // 有一条空壳路线 ⇒ 路线步未完成（否则该部位静默 0 工序）
    expect(screen.getByTestId('readiness-step-routings')).toHaveAttribute('data-state', 'todo')
    expect(screen.getByTestId('readiness-step-routings')).toHaveTextContent('空壳')
    // 原第 ③ 步「缺口」已按用户裁定移除（issue #4482）
    expect(screen.queryByTestId('readiness-step-gaps')).not.toBeInTheDocument()
  })

  it('就绪度检查器：工序库为空 ⇒ 第 ① 步未完成，且行业模板补救卡出现', async () => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok({ total: 0, groups: [] }))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('readiness-step-operations')).toHaveAttribute('data-state', 'todo'))
    expect(screen.getByTestId('seed-templates')).toBeInTheDocument()
  })

  // ────────────────────────── ④ 缺口分类（有意挂起 vs 真缺口） ──────────────────────────

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

  // ────────────────────────── ⑪ 两个 tab（issue #4482） ──────────────────────────

  it('两个 tab 存在且默认落在「工艺项」；切换后内容互斥（不再左右平铺）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('process-config-tabs')).toBeInTheDocument())

    const opsTab = screen.getByTestId('process-config-tab-operations')
    const routesTab = screen.getByTestId('process-config-tab-routes')
    expect(opsTab).toHaveTextContent('工艺项')
    expect(routesTab).toHaveTextContent('工艺路线')
    expect(opsTab).toHaveAttribute('data-state', 'active')
    expect(routesTab).toHaveAttribute('data-state', 'inactive')

    // 默认：工序库在、路线不在
    expect(screen.getByTestId('operations-catalog')).toBeInTheDocument()
    expect(screen.queryByTestId('routings-total')).not.toBeInTheDocument()

    await userEvent.click(routesTab)
    expect(routesTab).toHaveAttribute('data-state', 'active')
    expect(screen.queryByTestId('operations-catalog')).not.toBeInTheDocument()
    expect(screen.getByTestId('routings-total')).toBeInTheDocument()
  })

  it('切 tab **不丢状态**：在「工艺路线」编辑序列 → 切走 → 切回，draft 仍在', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))
    await userEvent.selectOptions(screen.getByTestId('routing-add-select-布帘×韩褶'), '裁剪-布')
    await userEvent.click(screen.getByTestId('routing-add-布帘×韩褶'))
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-4')).toHaveTextContent('裁剪-布')

    await userEvent.click(screen.getByTestId('process-config-tab-operations'))
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))

    // 编辑态与 draft 都还在（两栏挂在同一组件上，state 不随 tab 重置）
    expect(screen.getByTestId('routing-draft-step-布帘×韩褶-4')).toHaveTextContent('裁剪-布')
    expect(screen.getByTestId('routing-save-布帘×韩褶')).toBeInTheDocument()
  })

  it('缺口功能已**整体移除**：页面无缺口区、无就绪度第③步、文本无「缺口」', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    for (const id of ['routings-gaps', 'routings-gaps-unavailable', 'readiness-step-gaps']) {
      expect(screen.queryByTestId(id)).toBeNull()
    }
    expect(document.body.textContent ?? '').not.toContain('缺口')
  })

  // ────────────────────────── ⑩ 失败不白屏 ──────────────────────────

  it('路线列表加载失败：错误提示 + 重试（不白屏）', async () => {
    mockGetRoutings.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(ROUTINGS))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-error')).toHaveTextContent('工艺路线加载失败'))
    await userEvent.click(screen.getByTestId('routings-retry'))
    // 重试成功后回到正常 tab 结构（默认「工艺项」）⇒ 切到「工艺路线」看列表
    await userEvent.click(await screen.findByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    expect(screen.queryByTestId('routings-error')).not.toBeInTheDocument()
  })

  it('工序库加载失败：只在「工艺项」tab 给可读提示，路线 tab 照常渲染（不整页白屏）', async () => {
    mockGetOperationsCatalog.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(CATALOG))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operations-catalog-error')).toHaveTextContent('工序库加载失败'))
    // 路线 tab 不受影响
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
  })

  // ────────────────────────── ⑦ 护栏**就地预检**（不等后端 422） ──────────────────────────

  it('护栏就地预检：序列缺必完工序 ⇒ 编辑区立刻给黄条（这道单永远完不了工）', async () => {
    await renderOnRoutes()
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
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-布帘×韩褶')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-布帘×韩褶'))

    await waitFor(() => expect(screen.getByTestId('routing-draft-missing-布帘×韩褶-2')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-missing-布帘×韩褶-2')).toHaveTextContent('工序库中不存在')
    // 库里有的那一道不得被误标
    expect(screen.queryByTestId('routing-draft-missing-布帘×韩褶-1')).not.toBeInTheDocument()
  })

  it('工艺配置页不得出现「信号映射」这个概念：不渲染该区、不发起 /route-signals 请求、页面文本无「信号」', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('4'))

    // ① 不再渲染任何信号映射 UI（红证：修复前 route-signals-section / toggle / body / route-signal-* 全在）
    for (const id of [
      'route-signals-section',
      'route-signals-toggle',
      'route-signals-body',
      'route-signals-error',
      'route-signals-empty',
      'route-signal-31',
      'route-signal-new',
      'routings-gap-signals',
    ]) {
      expect(screen.queryByTestId(id)).toBeNull()
    }

    // ② 页面不再发起任何 /route-signals 请求（红证：修复前 load() 会调 getRouteSignals）
    expect(mockGetRouteSignals).not.toHaveBeenCalled()

    // ③ 连「信号」这两个字都不该露（用户裁定：客户完全不理解）
    expect(document.body.textContent ?? '').not.toContain('信号')
  })

})
