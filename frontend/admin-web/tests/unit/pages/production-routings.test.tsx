// case_ids: PG-020, PP-014, OR-041
// PG-020（issue #4203 / #4204）+ PP-014（issue #4307）**合并后**的单页用户面（issue #4416），
// 本单（issue #4433 = 母单 #4423 的 P3）把它适配到**新路线模型**（P1 #4427 / P2 #4432 / P2b #4459 / P2c #4500）。
//
// 新模型下的用户面判据（#4433）：
// ① **部位价目矩阵**（tab「工艺项」主区）：`GET /operation-positions` 的格数**整份**渲染（真实规模见 issue #4529：30 逻辑工序 × 4 部位 = 120 格；本文件用自己的夹具 28 × 3 判「不过滤」这一行为）
//    **整份呈现** —— 同一道工序三个部位各自真实价与适用性；`applicable=false` 的行**不得被过滤**；
//    服务端顺序（`(operation, position)`）**不得重排**；
// ② 「**不做**」（`applicable=false`）与「**没定价**」（`applicable=true` 但 `unit_price=null`）
//    在界面上**可区分**（同 `route_source` 的「静默 = 未知」纪律）；
// ③ **具名路线**：列表显示 `name` + **默认徽标** + 适用帘种 + 主线道数；**不再**出现「部位 × 工艺」标题；
// ④ 危险操作**护栏就地展示**：删默认 ⇒ 拦；删最后一条 ⇒ 拦（后端也会 422，前端不许把理由吞成一句）；
// ⑤ **改名只改 `name`**（对话框里**不出现**工序名/主线编辑）；
// ⑥ **删除二次确认** → `DELETE` → 刷新；失败**逐条**展示理由；
// ⑦ **设为默认** → `PUT {is_default:true}`；默认行不显示该入口；**绝不**提交 `is_default:false`（后端 422）；
// ⑧ **统一规则区**（tab「工艺路线」次区）：26 条规则**不截断**，触发键**逐字取自后端**（#4389 join key 纪律）；
// ⑨ **就绪度新增「默认路线」格**：无默认 ⇒ `data-state=todo` + 后果说明；
// ⑩ **零退化**：工序库半边（分组/搜索/改价/必完/作用域/新增工序）+ 路线半边 + 两个 tab + 切 tab 不丢状态；
// ⑪ 商家页**不得**出现「信号」（issue #4453 裁定：内部机制名不入商家面）。
// 反 placeholder：断言落**真实数据行**与**请求体**，不断言「页面存在」。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetRoutings = vi.fn()
const mockUpdateRouting = vi.fn()
const mockCreateRouting = vi.fn()
const mockDeleteRouting = vi.fn()
const mockGetOperationsCatalog = vi.fn()
const mockCreateOperation = vi.fn()
const mockUpdateOperation = vi.fn()
const mockGetSeedTemplates = vi.fn()
const mockGetOperationPositions = vi.fn()
const mockGetRouteRules = vi.fn()
// issue #4453 探针：信号映射是**研发内部机制**，商家页**不得**消费 ⇒ 它必须恒不被调用
const mockGetRouteSignals = vi.fn()
const mockApplySeedTemplate = vi.fn()
// issue #4528 = 包 E：算料配置读写（tab「算料配置」）
const mockGetCraftCalcConfig = vi.fn()
const mockUpdateCraftCalcConfig = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getRoutings: (...a: unknown[]) => mockGetRoutings(...a),
    updateRouting: (...a: unknown[]) => mockUpdateRouting(...a),
    createRouting: (...a: unknown[]) => mockCreateRouting(...a),
    deleteRouting: (...a: unknown[]) => mockDeleteRouting(...a),
    getOperationsCatalog: (...a: unknown[]) => mockGetOperationsCatalog(...a),
    createOperation: (...a: unknown[]) => mockCreateOperation(...a),
    updateOperation: (...a: unknown[]) => mockUpdateOperation(...a),
    getSeedTemplates: (...a: unknown[]) => mockGetSeedTemplates(...a),
    getOperationPositions: (...a: unknown[]) => mockGetOperationPositions(...a),
    getRouteRules: (...a: unknown[]) => mockGetRouteRules(...a),
    getRouteSignals: (...a: unknown[]) => mockGetRouteSignals(...a),
    applySeedTemplate: (...a: unknown[]) => mockApplySeedTemplate(...a),
    getCraftCalcConfig: (...a: unknown[]) => mockGetCraftCalcConfig(...a),
    updateCraftCalcConfig: (...a: unknown[]) => mockUpdateCraftCalcConfig(...a),
  },
}))

import { toast } from 'sonner'
import ProcessConfigPage from '@/app/(dashboard)/production/routings/page'

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 工序库（库口径）：含 作用域 / provenance / 必完 / 首工序 —— 工艺项 tab 的次区（明细） */
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
 * 部位价目矩阵：**服务端顺序** = `(operation, position)`（Java 自然序：三边 < 精裁 < 车被）。
 * 三态齐备 —— ① 有价（applicable=true）② **不做**（applicable=false ⇒ unit_price=null）
 * ③ **没定价**（applicable=true 但 unit_price=null）。
 */
const POSITIONS = [
  { operation: '三边', position: '帘头', unit_price: null, applicable: false },
  { operation: '三边', position: '布帘', unit_price: 1.2, applicable: true },
  { operation: '三边', position: '纱帘', unit_price: null, applicable: true },
  { operation: '精裁', position: '帘头', unit_price: null, applicable: false },
  { operation: '精裁', position: '布帘', unit_price: 8.5, applicable: true },
  { operation: '精裁', position: '纱帘', unit_price: 6, applicable: true },
  { operation: '车被', position: '帘头', unit_price: null, applicable: false },
  { operation: '车被', position: '布帘', unit_price: 3, applicable: true },
  { operation: '车被', position: '纱帘', unit_price: null, applicable: false },
]

/** 规则区：工艺触发 insert（带锚点）/ 工艺触发 remove（带部位限定）/ 特殊选项触发 insert */
const RULES = [
  { id: 1, trigger_kind: 'craft', trigger_value: '韩褶', position: null, action: 'insert', operation: '韩褶', after_operation: '三边', priority: 10, status: 'active' },
  { id: 2, trigger_kind: 'craft', trigger_value: '打孔', position: '布帘', action: 'remove', operation: '熨烫', after_operation: null, priority: 20, status: 'active' },
  { id: 3, trigger_kind: 'option', trigger_value: '拼2次', position: '纱帘', action: 'insert', operation: '拼缝', after_operation: null, priority: 30, status: 'active' },
]

/**
 * 具名路线（新结构）：① 默认 + 三帘种 + 3 道主线 ② 纱帘专线（**空主线** ⇒ 空壳）。
 * ⚠️ 主线存的是**逻辑工序名**（`精裁`/`三边`，与 V71 种子同款书写），而 `production_operations.name`
 * 仍是旧名（`精裁-布`）—— 两者之间**没有**暴露给前端的映射 ⇒ 前端不发明元数据（静默 = 未知）；
 * `外帘装袋` 两侧同名（旧名不带部位后缀）⇒ 它是「库口径可见」的那一道。
 * 旧形态（`curtain_type` × `craft` 展开快照）已随 P2b 退场 ⇒ 前端不得再按那个键渲染。
 */
const ROUTINGS = {
  total: 2,
  routings: [
    { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘', '纱帘', '帘头'], mainline: ['精裁', '三边', '外帘装袋'], status: 'active' },
    { id: 12, name: '纱帘专线', is_default: false, positions: ['纱帘'], mainline: [], status: 'active' },
  ],
}

const TEMPLATES = [
  { templateId: 'curtain', industry: 'curtain', name: '布艺窗帘行业模板', version: 1, description: '35 道工序 + 9 条路线' },
]

/**
 * 算料引擎**默认配置**（issue #4528）：本租户没有配置行时后端返回的那一份
 * （`GET /api/admin/production/craft-calc-config` ⇒ `{source:'default', config}`）。
 *
 * ⚠️ 逐值**写死**（真值源 §8 / 包 D 既有常量）：判据不得从实现推导 —— 否则「前端抄了一份默认值」
 * 这类缺陷不会红。前端**不持有**这份常量（它只在测试里当"后端会回什么"的替身）。
 */
const ENGINE_DEFAULT_CALC_CONFIG = {
  per_fold_single: 0.25,
  per_fold_mixed_times: { '1': 0.65, '2': 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: {
    standard: { fullness: 2.0, label: '标准工艺' },
    economy: { fullness: 1.8, label: '经济工艺' },
  },
  default_formula: 'pleat',
  side_margin: 0.3,
  meters_rounding_step: 0.1,
}

/** 后端护栏失败信封（逐条理由；**不**含顶层 `error_messages` —— 那个字段后端不存在） */
const CALC_GUARD_REJECTION = {
  response: {
    data: {
      success: false,
      error: {
        code: 'VALIDATION_ERROR',
        message: '算料配置有 2 处不合法，已整份拒绝',
        details: [
          { field: 'min_fullness', message: '不得低于行业红线 1.5' },
          { field: 'default_formula', message: '必须是 [pleat, fullness] 之一' },
        ],
      },
    },
  },
}

/** 后端护栏失败响应体（**真实**信封：`error.details[].message` 逐条理由 —— issue #4308「冻结补遗 ②」） */
const guardError = (reasons: string[]) => ({
  response: {
    status: 422,
    data: {
      success: false,
      error: {
        code: 'VALIDATION_ERROR',
        message: `工艺路线校验未通过：${reasons.length} 项`,
        details: reasons.map((message, i) => ({ field: `mainline[${i}]`, message })),
      },
      suggestion: '请修正后重试',
    },
  },
  message: 'Request failed with status code 422',
})

/** 渲染并切到「工艺路线」tab（路线内容在第二个 tab，默认落在「工艺项」） */
const renderOnRoutes = async () => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('process-config-tab-routes')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('process-config-tab-routes'))
}

/** 渲染并展开「工序库明细」折叠区（工序项 tab 的次区 —— 主区是部位价目矩阵） */
const renderCatalogDetail = async () => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('operations-catalog-toggle')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('operations-catalog-toggle'))
}

/** 渲染路线 tab 并展开「条件工序规则」折叠区（26 条规则的呈现面） */
const renderRules = async () => {
  await renderOnRoutes()
  await waitFor(() => expect(screen.getByTestId('route-rules-toggle')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('route-rules-toggle'))
}

describe('工艺配置页 /production/routings（新路线模型，issue #4433 = 母单 #4423 的 P3）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(POSITIONS))
    mockGetRouteRules.mockReset().mockResolvedValue(ok(RULES))
    mockGetRouteSignals.mockReset()
    mockApplySeedTemplate.mockReset().mockResolvedValue(ok({ created_operations: 35, created_routings: 9, skipped: 0 }))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-03', name: '韩褶-布', unit_price: 2.5 }))
    mockUpdateRouting.mockReset().mockResolvedValue(ok({ id: 12 }))
    mockCreateRouting.mockReset().mockResolvedValue(ok({ id: 13, name: '罗马帘专线', is_default: false, positions: ['布帘'], mainline: [], status: 'active' }))
    mockDeleteRouting.mockReset().mockResolvedValue(ok({ id: 12 }))
    mockCreateOperation.mockReset().mockResolvedValue(ok({ id: 'op-new' }))
    mockGetCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'default', config: ENGINE_DEFAULT_CALC_CONFIG }))
    mockUpdateCraftCalcConfig.mockReset().mockResolvedValue(ok({ source: 'stored', config: ENGINE_DEFAULT_CALC_CONFIG }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  // ══════════════════ ①② 部位价目矩阵（tab「工艺项」主区） ══════════════════

  it('部位价目矩阵：84 格**整份**渲染 —— applicable=false 的行不得被过滤', async () => {
    // 真实规模：28 逻辑工序 × 3 部位 = 84 格，其中约 1/3 是 applicable=false（「不做」）
    const positions = ['布帘', '纱帘', '帘头']
    const big = Array.from({ length: 28 }, (_, i) => `工序${i + 1}`).flatMap((operation, oi) =>
      positions.map((position, pi) => ({
        operation,
        position,
        unit_price: pi === 1 ? null : oi + pi,
        applicable: pi !== 1,
      })),
    )
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(big))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    // 28 行 × 3 列 = 84 格（注入：过滤掉 applicable=false ⇒ 格数变 56，断言红）
    expect(screen.getByTestId('operation-price-matrix-total')).toHaveTextContent('28')
    expect(screen.getByTestId('operation-price-matrix-cells')).toHaveTextContent('84')
    expect(screen.getAllByTestId(/^matrix-row-/)).toHaveLength(28)
    expect(screen.getAllByTestId(/^matrix-cell-/)).toHaveLength(84)
    // 被「不做」的那一列仍然在（不是被整列/整行滤掉）
    expect(screen.getAllByTestId(/^matrix-cell-.*-纱帘$/)).toHaveLength(28)
    expect(screen.getByTestId('matrix-cell-工序1-纱帘')).toHaveTextContent('不做')
  })

  it('部位价目矩阵：同一道工序三个部位各自显示真实价/适用性，且**服务端顺序不重排**', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())

    // 行序 = 服务端顺序（(operation, position) ⇒ 三边 / 精裁 / 车被）；注入：前端按字母重排 ⇒ 红
    const rows = screen.getAllByTestId(/^matrix-row-/)
    expect(rows.map((r) => r.getAttribute('data-operation'))).toEqual(['三边', '精裁', '车被'])

    // 同一道「精裁」：布帘 ¥8.50 / 纱帘 ¥6.00 / 帘头 不做 —— 三个部位三份数据（不是一行一个价）
    expect(screen.getByTestId('matrix-cell-精裁-布帘')).toHaveTextContent('¥8.50')
    expect(screen.getByTestId('matrix-cell-精裁-纱帘')).toHaveTextContent('¥6.00')
    expect(screen.getByTestId('matrix-cell-精裁-帘头')).toHaveTextContent('不做')
    expect(screen.getByTestId('matrix-cell-三边-布帘')).toHaveTextContent('¥1.20')
    // 列序 = 业务口径（布帘 / 纱帘 / 帘头），不是服务端格序
    expect(within(screen.getByTestId('operation-price-matrix')).getAllByRole('columnheader').map((c) => c.textContent)).toEqual([
      '工序',
      '布帘',
      '纱帘',
      '帘头',
    ])
  })

  it('「不做」与「没定价」在界面上**可区分**（同 route_source 的「静默 = 未知」纪律）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())

    // applicable=false ⇒ 「不做」+ data-state=na（明确不做，不是漏配）
    const na = screen.getByTestId('matrix-cell-车被-纱帘')
    expect(na).toHaveAttribute('data-state', 'na')
    expect(na).toHaveTextContent('不做')
    expect(na).not.toHaveTextContent('未定价')

    // applicable=true 但没价 ⇒ 「未定价」+ data-state=unpriced（有定价动作但还没填）
    const unpriced = screen.getByTestId('matrix-cell-三边-纱帘')
    expect(unpriced).toHaveAttribute('data-state', 'unpriced')
    expect(unpriced).toHaveTextContent('未定价')
    expect(unpriced).not.toHaveTextContent('不做')

    // 有价的格不得被渲染成上面两态
    expect(screen.getByTestId('matrix-cell-三边-布帘')).toHaveAttribute('data-state', 'priced')
  })

  it('部位价目矩阵：端点失败只在该区给可读提示（不白屏、不影响其余区）', async () => {
    mockGetOperationPositions.mockReset().mockRejectedValueOnce(new Error('500'))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-price-matrix-error')).toHaveTextContent('部位价目加载失败'))
    // 路线半边照常（切过去仍渲染真实数据）
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
  })

  // ══════════════════ ③ 具名路线（name + 默认徽标 + 适用帘种） ══════════════════

  it('路线列表显示 name + 默认徽标 + 适用帘种 + 主线道数；不再出现「部位 × 工艺」标题', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    const box = screen.getByTestId('routing-11')
    expect(within(box).getByTestId('routing-name-11')).toHaveTextContent('窗帘工序路线（默认）')
    expect(within(box).getByTestId('routing-default-11')).toHaveTextContent('默认')
    expect(within(box).getByTestId('routing-positions-11')).toHaveTextContent('布帘')
    expect(within(box).getByTestId('routing-positions-11')).toHaveTextContent('纱帘')
    expect(within(box).getByTestId('routing-positions-11')).toHaveTextContent('帘头')
    expect(within(box).getByTestId('routing-mainline-count-11')).toHaveTextContent('3')

    // 非默认路线**不得**带默认徽标（注入：徽标写死 ⇒ 红）
    expect(within(screen.getByTestId('routing-12')).queryByTestId('routing-default-12')).toBeNull()
    expect(within(screen.getByTestId('routing-12')).getByTestId('routing-positions-12')).toHaveTextContent('纱帘')

    // 旧形态退场：不再按 (部位 × 工艺) 渲染
    expect(document.body.textContent ?? '').not.toContain('×')
  })

  it('空壳口径：主线为空 ⇒ 「空壳 · 不可用」（正常路线不得被误标）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-12')).toBeInTheDocument())

    expect(screen.getByTestId('routing-empty-shell-12')).toHaveTextContent('空壳')
    expect(screen.getByTestId('routing-12')).toHaveTextContent('0 道')
    expect(within(screen.getByTestId('routing-11')).queryByTestId('routing-empty-shell-11')).toBeNull()
  })

  // ══════════════════ ④ 危险操作护栏（就地展示理由） ══════════════════

  it('删默认 ⇒ 删除按钮**禁用**且就地给出可读理由（不靠后端 422 才知道）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-11')).toBeInTheDocument())

    expect(screen.getByTestId('routing-delete-11')).toBeDisabled()
    const reason = screen.getByTestId('routing-delete-blocked-11')
    expect(reason).toHaveTextContent('默认')
    expect(reason).toHaveTextContent('设为默认')
    // 非默认路线可删（不得把护栏套到所有行上）
    expect(screen.getByTestId('routing-delete-12')).toBeEnabled()
  })

  it('删最后一条 ⇒ 删除按钮**禁用**且就地说明后果', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [{ id: 11, name: '唯一路线', is_default: true, positions: ['布帘'], mainline: ['精裁'], status: 'active' }],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-11')).toBeInTheDocument())

    expect(screen.getByTestId('routing-delete-11')).toBeDisabled()
    expect(screen.getByTestId('routing-delete-blocked-11')).toHaveTextContent('最后一条')
  })

  it('恰一条默认：默认行**不显示**「设为默认」入口（后端 is_default:false ⇒ 422，前端不得发）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-11')).toBeInTheDocument())

    expect(screen.queryByTestId('routing-set-default-11')).toBeNull()
    expect(screen.getByTestId('routing-set-default-12')).toBeInTheDocument()
  })

  // ══════════════════ ⑤ 改名（只改 name） ══════════════════

  it('改名：对话框**只有路线名称**（不出现工序名/主线编辑），PUT 只提交 name', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-rename-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-rename-11'))
    const modal = await screen.findByTestId('routing-rename-modal')
    expect(within(modal).getByTestId('routing-rename-input')).toHaveValue('窗帘工序路线（默认）')
    // 用户裁定「只是更改工艺路线总名」：对话框里**不得**出现工序名/主线编辑入口
    expect(within(modal).queryByTestId('routing-rename-mainline')).toBeNull()
    expect(modal.textContent ?? '').not.toContain('工序名')

    await userEvent.clear(within(modal).getByTestId('routing-rename-input'))
    await userEvent.type(within(modal).getByTestId('routing-rename-input'), '窗帘主线（默认）')
    await userEvent.click(screen.getByTestId('routing-rename-submit'))

    // 只提交 name —— 改名不得顺带重写主线（那是计件工资的输入）
    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalledWith(11, { name: '窗帘主线（默认）' }))
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
  })

  it('改名失败（重名 409/422）：理由**逐条**就地展示，不吞成一句「保存失败」', async () => {
    mockUpdateRouting.mockReset().mockRejectedValueOnce(
      guardError(['工艺路线「纱帘专线」已存在']),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-rename-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-rename-12'))
    await userEvent.clear(await screen.findByTestId('routing-rename-input'))
    await userEvent.type(screen.getByTestId('routing-rename-input'), '纱帘专线')
    await userEvent.click(screen.getByTestId('routing-rename-submit'))

    await waitFor(() => expect(screen.getByTestId('routing-op-error-item-0')).toHaveTextContent('已存在'))
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument()
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  // ══════════════════ ⑥ 删除（二次确认 + DELETE + 刷新） ══════════════════

  it('删除：**二次确认**后才发 DELETE，成功后刷新列表', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-delete-12'))
    // 只打开确认框 ⇒ 不得发请求（注入：去掉确认直接删 ⇒ 红）
    expect(await screen.findByTestId('routing-confirm-modal')).toHaveAttribute('data-kind', 'delete')
    expect(mockDeleteRouting).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('routing-confirm-delete-12'))
    await waitFor(() => expect(mockDeleteRouting).toHaveBeenCalledWith(12))
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
  })

  it('删除：确认框可取消 —— 取消后不发 DELETE', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-delete-12'))
    await userEvent.click(await screen.findByTestId('routing-confirm-cancel'))
    expect(mockDeleteRouting).not.toHaveBeenCalled()
    expect(screen.queryByTestId('routing-confirm-modal')).toBeNull()
  })

  it('删除被后端拒（护栏 422）：理由逐条就地展示，且商家面不出现内部机制名', async () => {
    mockDeleteRouting.mockReset().mockRejectedValueOnce(
      guardError([
        '默认路线不能删：删了该租户就没有默认路线 ⇒ 缺信号订单建单全部 fail-closed。请先把另一条设为默认，再删这条',
      ]),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-delete-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-delete-12'))
    await userEvent.click(await screen.findByTestId('routing-confirm-delete-12'))

    await waitFor(() => expect(screen.getByTestId('routing-op-error-item-0')).toBeInTheDocument())
    expect(screen.getByTestId('routing-op-error-item-0')).toHaveTextContent('默认路线不能删')
    // issue #4453：内部机制名不入商家面（只换词，不删理由）
    expect(document.body.textContent ?? '').not.toContain('信号')
    expect(document.body.textContent ?? '').not.toContain('fail-closed')
    expect(mockGetRoutings).toHaveBeenCalledTimes(1)
  })

  // ══════════════════ ⑦ 设为默认（PUT is_default:true） ══════════════════

  it('设为默认：二次确认 → `PUT {is_default:true}` → 刷新', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-set-default-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-set-default-12'))
    expect(await screen.findByTestId('routing-confirm-modal')).toHaveAttribute('data-kind', 'default')
    expect(mockUpdateRouting).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('routing-confirm-default-12'))
    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalledWith(12, { is_default: true }))
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
  })

  it('页面**绝不**提交 `is_default:false`（后端 422：取消默认 ⇒ 零默认 ⇒ 建单全 fail-closed）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-set-default-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-set-default-12'))
    await userEvent.click(await screen.findByTestId('routing-confirm-default-12'))
    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalled())

    const payloads = mockUpdateRouting.mock.calls.map((c) => c[1] as Record<string, unknown>)
    expect(payloads.every((p) => p.is_default !== false)).toBe(true)
  })

  // ══════════════════ ⑧ 统一规则区（26 条不截断，触发键逐字取自后端） ══════════════════

  it('规则区：26 条**整份**渲染（不截断），触发键**逐字**取自后端', async () => {
    const big = Array.from({ length: 26 }, (_, i) => ({
      id: 100 + i,
      trigger_kind: i % 2 === 0 ? 'craft' : 'option',
      trigger_value: `触发${i + 1}`,
      position: i % 3 === 0 ? null : '布帘',
      action: i % 4 === 0 ? 'remove' : 'insert',
      operation: `工序${i + 1}`,
      after_operation: i % 4 === 0 ? null : '三边',
      priority: (i + 1) * 10,
      status: 'active',
    }))
    mockGetRouteRules.mockReset().mockResolvedValue(ok(big))
    await renderRules()

    await waitFor(() => expect(screen.getByTestId('route-rules-total')).toBeInTheDocument())
    expect(screen.getByTestId('route-rules-total')).toHaveTextContent('26')
    // 注入：把 26 条截断成前 20 条（.slice(0,20)）⇒ 断言红
    expect(screen.getAllByTestId(/^route-rule-\d+$/)).toHaveLength(26)
    expect(screen.getByTestId('route-rule-trigger-100')).toHaveTextContent('触发1')
  })

  it('规则区：触发 → 动作 → 目标工序 / 部位限定 / priority 都可读（null = 不限部位 / 追加末尾）', async () => {
    await renderRules()
    await waitFor(() => expect(screen.getByTestId('route-rule-1')).toBeInTheDocument())

    // ① 工艺触发 · 插入 after 锚点
    const r1 = screen.getByTestId('route-rule-1')
    expect(within(r1).getByTestId('route-rule-trigger-1')).toHaveTextContent('韩褶')
    expect(within(r1).getByTestId('route-rule-action-1')).toHaveTextContent('插入')
    expect(within(r1).getByTestId('route-rule-action-1')).toHaveTextContent('三边')
    expect(within(r1).getByTestId('route-rule-target-1')).toHaveTextContent('韩褶')
    expect(within(r1).getByTestId('route-rule-position-1')).toHaveTextContent('不限')
    expect(within(r1).getByTestId('route-rule-priority-1')).toHaveTextContent('10')

    // ② 工艺触发 · 移除（带部位限定）
    const r2 = screen.getByTestId('route-rule-2')
    expect(within(r2).getByTestId('route-rule-action-2')).toHaveTextContent('移除')
    expect(within(r2).getByTestId('route-rule-position-2')).toHaveTextContent('布帘')
    expect(within(r2).getByTestId('route-rule-target-2')).toHaveTextContent('熨烫')

    // ③ 特殊选项触发（触发键**逐字**：拼2次 —— 前端不得"纠正"成「拼两次」）
    const r3 = screen.getByTestId('route-rule-3')
    expect(within(r3).getByTestId('route-rule-trigger-3')).toHaveTextContent('拼2次')
    expect(within(r3).getByTestId('route-rule-position-3')).toHaveTextContent('纱帘')
  })

  // ══════════════════ ⑨ 就绪度「默认路线」格 ══════════════════

  it('就绪度新增「默认路线」格：有默认 ⇒ done；无默认 ⇒ todo + 说明后果', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('readiness-step-default-route')).toBeInTheDocument())
    expect(screen.getByTestId('readiness-step-default-route')).toHaveAttribute('data-state', 'done')
  })

  it('就绪度「默认路线」格：零默认 ⇒ todo，并说明「没有指定工艺的订单一张加工单也生成不了」', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [{ id: 11, name: '唯一路线', is_default: false, positions: ['布帘'], mainline: ['精裁'], status: 'active' }],
      }),
    )
    await renderOnRoutes()

    await waitFor(() => expect(screen.getByTestId('readiness-step-default-route')).toHaveAttribute('data-state', 'todo'))
    expect(screen.getByTestId('readiness-step-default-route')).toHaveTextContent('加工单')
    expect(screen.getByTestId('readiness-step-default-route')).toHaveTextContent('设为默认')
  })

  // ══════════════════ ⑩ 零退化：工序库半边 / 路线半边 / 两个 tab / 切 tab 不丢状态 ══════════════════

  it('工序库半边（折叠明细）：按分组展示 + 搜索过滤，真实行数与库口径单价', async () => {
    await renderCatalogDetail()
    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('4'))

    expect(within(screen.getByTestId('operation-group-裁剪')).getAllByTestId(/^operation-row-/)).toHaveLength(2)
    expect(within(screen.getByTestId('operation-group-车位')).getAllByTestId(/^operation-row-/)).toHaveLength(1)
    expect(within(screen.getByTestId('operation-group-后道')).getAllByTestId(/^operation-row-/)).toHaveLength(1)
    expect(screen.getByTestId('operation-row-op-v54-03')).toHaveTextContent('¥1.20')

    // 搜索框过滤工序库明细（也过滤矩阵行）
    await userEvent.type(screen.getByTestId('operations-search'), '韩褶')
    await waitFor(() => expect(screen.queryByTestId('operation-group-裁剪')).toBeNull())
    expect(screen.getByTestId('operation-row-op-v54-03')).toBeInTheDocument()
  })

  it('工序库半边：改单价 → PUT **只带** unit_price；必完/作用域各只带自己的字段', async () => {
    await renderCatalogDetail()
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-03')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('operation-price-edit-op-v54-03'))
    const input = screen.getByTestId('operation-price-input-op-v54-03')
    await userEvent.clear(input)
    await userEvent.type(input, '2.5')
    await userEvent.click(screen.getByTestId('operation-price-save-op-v54-03'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-03', { unit_price: 2.5 }))

    await userEvent.click(screen.getByTestId('operation-must-finish-op-v54-03'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-03', { is_must_finish: true }))

    expect(screen.getByTestId('operation-scope-op-v54-04')).toHaveValue('set')
    await userEvent.selectOptions(screen.getByTestId('operation-scope-op-v54-03'), 'set')
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-03', { scope: 'set' }))
  })

  it('工序库半边：首工序（is_start_marker）**不得**被渲染成「必完」', async () => {
    await renderCatalogDetail()
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-02')).toBeInTheDocument())

    const row = screen.getByTestId('operation-row-op-v54-02')
    expect(row).toHaveTextContent('首工序')
    expect(within(row).queryByText('必完')).not.toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-op-v54-04')).getByTestId('operation-must-finish-op-v54-04')).toBeChecked()
  })

  it('工序库半边：新增工序（POST /operations）后刷新工序库', async () => {
    await renderCatalogDetail()
    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toBeInTheDocument())

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

  it('路线半边：主线逐道渲染 —— 库里查得到的带单位/单价/必完，逻辑名**不发明**元数据', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-step-11-1')).toBeInTheDocument())

    // 逻辑工序名「精裁」在工序库里没有同名行 ⇒ 只显示名字（静默 = 未知，不得冒充已知）
    const logical = screen.getByTestId('routing-step-11-1')
    expect(logical).toHaveTextContent('精裁')
    expect(logical).not.toHaveTextContent('¥')
    expect(logical).not.toHaveTextContent('必完')
    // 「外帘装袋」两侧同名 ⇒ 库口径（单位/单价/必完）可见
    expect(screen.getByTestId('routing-step-11-3')).toHaveTextContent('外帘装袋')
    expect(screen.getByTestId('routing-step-11-3')).toHaveTextContent('¥0.40')
    expect(screen.getByTestId('routing-step-11-3')).toHaveTextContent('必完')
    // 空壳那条没有步骤可渲染
    expect(screen.queryByTestId('routing-step-12-1')).toBeNull()
  })

  it('序列编辑：添加工序 → 保存 ⇒ `PUT {mainline:[...]}` 顺序等于屏幕顺序', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    expect(screen.getByTestId('routing-draft-step-11-1')).toHaveTextContent('精裁')

    await userEvent.selectOptions(screen.getByTestId('routing-add-select-11'), '裁剪-布')
    await userEvent.click(screen.getByTestId('routing-add-11'))
    await userEvent.click(screen.getByTestId('routing-save-11'))

    await waitFor(() =>
      expect(mockUpdateRouting).toHaveBeenCalledWith(11, { mainline: ['精裁', '三边', '外帘装袋', '裁剪-布'] }),
    )
    await waitFor(() => expect(mockGetRoutings).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByTestId('routing-save-11')).not.toBeInTheDocument())
  })

  it('序列编辑：下移/删除改变顺序后保存，请求体随之变化', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await userEvent.click(screen.getByTestId('routing-draft-down-11-1'))
    expect(screen.getByTestId('routing-draft-name-11-1')).toHaveTextContent('三边')
    await userEvent.click(screen.getByTestId('routing-draft-remove-11-3'))
    await userEvent.click(screen.getByTestId('routing-save-11'))

    await waitFor(() => expect(mockUpdateRouting).toHaveBeenCalledWith(11, { mainline: ['三边', '精裁'] }))
  })

  it('空主线：本地拦住不发请求，并说明为什么不能空', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-12')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-12'))
    await userEvent.click(screen.getByTestId('routing-save-12'))

    await waitFor(() => expect(screen.getByTestId('routing-error-12')).toBeInTheDocument())
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('不能为空')
    expect(mockUpdateRouting).not.toHaveBeenCalled()
  })

  it('保存被拒（主线护栏）：后端理由**逐条**展示，不合并成一句「保存失败」', async () => {
    mockUpdateRouting.mockReset().mockRejectedValueOnce(
      guardError([
        '工序「罗马帘-打孔」不在工序库中',
        '工序「精裁」在主线中重复出现 2 次',
        '路线至少要有一道必完工序（当前 0 道）',
      ]),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await userEvent.click(screen.getByTestId('routing-save-11'))

    await waitFor(() => expect(screen.getByTestId('routing-error-11')).toBeInTheDocument())
    expect(within(screen.getByTestId('routing-error-11')).getAllByTestId(/^routing-error-item-/)).toHaveLength(3)
    expect(screen.getByTestId('routing-error-item-0')).toHaveTextContent('工序不存在')
    expect(screen.getByTestId('routing-error-item-1')).toHaveTextContent('工序重复')
    expect(screen.getByTestId('routing-error-item-2')).toHaveTextContent('缺少必完工序')
  })

  it('护栏就地预检：主线缺必完工序 ⇒ 黄条；但**判不了就不判**（逻辑名/库中缺失 ⇒ 静默 = 未知）', async () => {
    // 两道都能在工序库里查到、且都不是必完 ⇒ 判得动 ⇒ 黄条
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘'], mainline: ['韩褶-布', '裁剪-布'], status: 'active' },
        ],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    expect(screen.getByTestId('routing-precheck-11')).toHaveTextContent('必完')
    // 预检只是提示，不阻断保存（后端仍是唯一权威）
    expect(screen.getByTestId('routing-save-11')).toBeEnabled()
  })

  it('护栏就地预检：主线的逻辑工序名拿不到「必完」口径 ⇒ **不误报**黄条（未知 ≠ 违规）', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    // 主线是逻辑名（精裁/三边）⇒ 工序库里查不到同名的 is_must_finish ⇒ 判不了就不判
    expect(screen.queryByTestId('routing-precheck-11')).toBeNull()
    expect(screen.queryByTestId('routing-precheck-missing-11')).toBeNull()
  })

  it('护栏就地预检：主线引用了工序库里没有的工序 ⇒ 该行标红并指名', async () => {
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 1,
        routings: [
          { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘'], mainline: ['韩褶-布', '罗马帘-打孔'], status: 'active' },
        ],
      }),
    )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await waitFor(() => expect(screen.getByTestId('routing-draft-missing-11-2')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-missing-11-2')).toHaveTextContent('工序库中不存在')
    expect(screen.queryByTestId('routing-draft-missing-11-1')).toBeNull()
  })

  it('新建路线：提交 `{name, positions, is_default}` 并自动进入主线编辑', async () => {
    mockGetRoutings
      .mockReset()
      .mockResolvedValueOnce(ok(ROUTINGS))
      .mockResolvedValue(
        ok({
          total: 3,
          routings: [...ROUTINGS.routings, { id: 13, name: '罗马帘专线', is_default: false, positions: ['布帘'], mainline: [], status: 'active' }],
        }),
      )
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))

    await userEvent.click(screen.getByTestId('routings-new-route'))
    await userEvent.type(screen.getByTestId('routings-create-name'), '罗马帘专线')
    await userEvent.click(screen.getByTestId('routings-create-position-帘头')) // 取消勾选「帘头」
    await userEvent.click(screen.getByTestId('routings-create-route-submit'))

    await waitFor(() =>
      expect(mockCreateRouting).toHaveBeenCalledWith({ name: '罗马帘专线', positions: ['布帘', '纱帘'] }),
    )
    // 建壳后**自动进入主线编辑**（消灭「建了条空壳但没人知道」的静默态）
    await waitFor(() => expect(screen.getByTestId('routing-save-13')).toBeInTheDocument())
    expect(screen.getByTestId('routing-draft-empty-13')).toHaveTextContent('从工序库选择')
  })

  it('两个 tab 存在且默认落在「工艺项」；切换后内容互斥（不平铺）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('process-config-tabs')).toBeInTheDocument())

    const opsTab = screen.getByTestId('process-config-tab-operations')
    const routesTab = screen.getByTestId('process-config-tab-routes')
    expect(opsTab).toHaveTextContent('工艺项')
    expect(routesTab).toHaveTextContent('工艺路线')
    expect(opsTab).toHaveAttribute('data-state', 'active')
    expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument()
    expect(screen.queryByTestId('routings-total')).not.toBeInTheDocument()

    await userEvent.click(routesTab)
    expect(routesTab).toHaveAttribute('data-state', 'active')
    expect(screen.queryByTestId('operation-price-matrix')).not.toBeInTheDocument()
    expect(screen.getByTestId('routings-total')).toBeInTheDocument()
  })

  it('切 tab **不丢状态**：在「工艺路线」编辑主线 → 切走 → 切回，draft 仍在', async () => {
    await renderOnRoutes()
    await waitFor(() => expect(screen.getByTestId('routing-edit-11')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('routing-edit-11'))
    await userEvent.selectOptions(screen.getByTestId('routing-add-select-11'), '裁剪-布')
    await userEvent.click(screen.getByTestId('routing-add-11'))
    expect(screen.getByTestId('routing-draft-step-11-4')).toHaveTextContent('裁剪-布')

    await userEvent.click(screen.getByTestId('process-config-tab-operations'))
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))

    // 注入：把 draft 改成随 tab 重置 ⇒ 红
    expect(screen.getByTestId('routing-draft-step-11-4')).toHaveTextContent('裁剪-布')
    expect(screen.getByTestId('routing-save-11')).toBeInTheDocument()
  })

  it('只读端点失败不白屏：路线列表失败给提示 + 重试；工序库失败只在该区提示', async () => {
    mockGetRoutings.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(ROUTINGS))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('routings-error')).toHaveTextContent('工艺路线加载失败'))
    await userEvent.click(screen.getByTestId('routings-retry'))
    await userEvent.click(await screen.findByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
  })

  it('工序库加载失败：展开明细后只在该区给可读提示，矩阵与路线半边照常', async () => {
    mockGetOperationsCatalog.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok(CATALOG))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('operations-catalog-toggle'))
    await waitFor(() => expect(screen.getByTestId('operations-catalog-error')).toHaveTextContent('工序库加载失败'))
  })

  // ══════════════════ ⑪ 商家面不得出现内部机制名 ══════════════════

  it('工艺配置页不得出现「信号映射」这个概念：不渲染该区、不发起请求、页面文本无「信号」', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())

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
    expect(mockGetRouteSignals).not.toHaveBeenCalled()
    expect(document.body.textContent ?? '').not.toContain('信号')
  })

/**
 * ══════════════════ ⑫ 算料配置 tab（issue #4528 = 包 E） ══════════════════
 *
 * 判据（每条都能红）：
 * ① 切到本 tab ⇒ 发**一次** `GET`，渲染**引擎默认值**并标注「当前使用系统默认值」
 *    （把默认值伪装成商家配置 ⇒ 红；前端自带一份默认值 ⇒ 与后端逐值比对时红）；
 * ② 改一个参数 ⇒ `PUT` 带**全量 9 键**（缺键 = 让后端静默回默认值 ⇒ 红）；
 * ③ 非法值 ⇒ 后端 422 的**逐条**理由可见，且**不静默回退默认值**（草稿保持用户输入、不显示「已保存」⇒ 红）；
 * ④ 切 tab 不丢草稿（state 挂在本组件上）。
 */
describe('算料配置 tab（issue #4528）', () => {
  it('切到算料配置 tab ⇒ GET 一次 + 渲染引擎默认值 + 标注「当前使用系统默认值」', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    // 懒加载：没切过去之前**不**发请求
    expect(mockGetCraftCalcConfig).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())
    expect(mockGetCraftCalcConfig).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('craft-calc-config-source')).toHaveTextContent('当前使用系统默认值')
    // 默认值来自**后端**（逐值渲染，前端不持有）
    expect(screen.getByTestId('craft-calc-config-scalar-per_fold_single')).toHaveValue(0.25)
    expect(screen.getByTestId('craft-calc-config-scalar-min_fullness')).toHaveValue(1.5)
    expect(screen.getByTestId('craft-calc-config-default_formula')).toHaveValue('pleat')
    expect(screen.getByTestId('craft-calc-config-tier-standard-fullness')).toHaveValue(2)
    expect(screen.getByTestId('craft-calc-config-mixed-1')).toHaveValue(0.65)
  })

  it('改「单色每折吃布」⇒ PUT 带全量 9 键（缺键会让后端静默回默认值）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const input = screen.getByTestId('craft-calc-config-scalar-per_fold_single')
    await userEvent.clear(input)
    await userEvent.type(input, '0.5')
    mockUpdateCraftCalcConfig.mockResolvedValueOnce(
      ok({ source: 'stored', config: { ...ENGINE_DEFAULT_CALC_CONFIG, per_fold_single: 0.5 } }),
    )
    await userEvent.click(screen.getByTestId('craft-calc-config-save'))

    await waitFor(() => expect(mockUpdateCraftCalcConfig).toHaveBeenCalledTimes(1))
    const body = mockUpdateCraftCalcConfig.mock.calls[0][0] as Record<string, unknown>
    expect(body.per_fold_single).toBe(0.5)
    expect(Object.keys(body).sort()).toEqual(
      [
        'per_fold_single',
        'per_fold_mixed_times',
        'margin_single',
        'margin_multi',
        'min_fullness',
        'tiers',
        'default_formula',
        'side_margin',
        'meters_rounding_step',
      ].sort(),
    )
    // 保存成功后口径来源如实变「已保存为您的配置」
    await waitFor(() =>
      expect(screen.getByTestId('craft-calc-config-source')).toHaveTextContent('已保存为您的配置'),
    )
  })

  it('非法值 ⇒ 422 逐条理由就地可见，且**不静默回退默认值**', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const input = screen.getByTestId('craft-calc-config-scalar-min_fullness')
    await userEvent.clear(input)
    await userEvent.type(input, '1')
    mockUpdateCraftCalcConfig.mockRejectedValueOnce(CALC_GUARD_REJECTION)
    await userEvent.click(screen.getByTestId('craft-calc-config-save'))

    const reasons = await screen.findByTestId('craft-calc-config-reasons')
    expect(reasons).toHaveTextContent('不得低于行业红线 1.5')
    expect(reasons).toHaveTextContent('必须是 [pleat, fullness] 之一')
    // 不静默回退：用户输入**还在**（没有被悄悄写回默认 1.5），且来源仍标注「系统默认值」
    expect(screen.getByTestId('craft-calc-config-scalar-min_fullness')).toHaveValue(1)
    expect(screen.getByTestId('craft-calc-config-source')).toHaveTextContent('当前使用系统默认值')
  })

  it('切 tab 不丢草稿（编辑中的参数在切走再切回后仍在）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-panel')).toBeInTheDocument())

    const input = screen.getByTestId('craft-calc-config-scalar-margin_multi')
    await userEvent.clear(input)
    await userEvent.type(input, '0.45')

    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routings-list')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    expect(screen.getByTestId('craft-calc-config-scalar-margin_multi')).toHaveValue(0.45)
  })

  it('算料配置加载失败 ⇒ 就地报错 + 重试入口（不白屏、不拿默认值顶替）', async () => {
    mockGetCraftCalcConfig.mockReset().mockRejectedValueOnce(new Error('500')).mockResolvedValue(ok({
      source: 'default',
      config: ENGINE_DEFAULT_CALC_CONFIG,
    }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-calc'))

    await waitFor(() => expect(screen.getByTestId('craft-calc-config-error')).toHaveTextContent('算料配置加载失败'))
    expect(screen.queryByTestId('craft-calc-config-scalar-per_fold_single')).toBeNull()

    await userEvent.click(screen.getByTestId('craft-calc-config-retry'))
    await waitFor(() => expect(screen.getByTestId('craft-calc-config-scalar-per_fold_single')).toHaveValue(0.25))
  })
})
})
