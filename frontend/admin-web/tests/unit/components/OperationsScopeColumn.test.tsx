// case_ids: PG-039
// PG-039（issue #4384 A1，前端半边）：工序「作用域」档位（部位级 / 套级）**可见且可就地改**
// （`PUT /api/admin/production/operations/{id}` body 带 scope）。
//
// ⚠️ issue #4588（母单 #4586 包 B；契约 #4587）**改了承载形态**：原来这一列在「工序库明细」折叠次区，
// 现在收进「工艺项」单表的行尾「管理▸」抽屉（用户 2026-09-19 追加裁定：「作用域 · 必完 完全不知道干嘛的，
// 也可以移除」⇒ 移除的是**主表显示**，不是语义/入口）⇒ 判据落在抽屉里，并**反向断言主表不出现「作用域」**。
// 作用域取值来源也随之明确：**变体元数据**（矩阵每格的 `scope`，契约 #4587 ①），不是工序库列表那一列。
//
// 为什么这条判据承重（真值源 docs/curtain-production-rules.md §8）：**外帘**是加工单打印行部位、
// **不是**路线键，但 V54/V58 种子把 外帘打卷/外帘装袋/外帘发货 逐条写进每一条部位路线（含纱帘）
// ⇒ 一樘「布 + 纱」时这 3 道各实例化 2 次 ⇒ 各 ¥1.0 双付。用户裁定（2026-09-19）：
// 「套级工序先按**每樘窗一次**实现，打卷是否每帘一次**留成可配**」
// ⇒ 「留成可配」的落码形态就是抽屉里这个控件：商家能看见、能改。
//
// 反 placeholder：断言渲染出**真实取值**（套级/部位级逐个不同），不是只断言控件存在；
// 且写路径必须真发出 `{ scope }`（只断言「按钮可点」= 空断言）。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetOperationsCatalog = vi.fn()
const mockGetRoutings = vi.fn()
const mockUpdateOperation = vi.fn()
const mockGetSeedTemplates = vi.fn()
const mockApplySeedTemplate = vi.fn()
// issue #4416：工序库并入「工艺配置」单页 ⇒ 该页还会拉缺口/信号两条只读端点
const mockGetRoutingGaps = vi.fn()
const mockGetRouteSignals = vi.fn()
// issue #4433（P3）：该页新增两条只读面 —— 部位价目矩阵 / 条件工序规则
const mockGetOperationPositions = vi.fn()
const mockGetRouteRules = vi.fn()
// issue #4588：矩阵格写面 + 工序/规则软删（本文件只用到 updateOperation，其余备齐 mock 形态）
const mockUpdateOperationPosition = vi.fn()
const mockDeleteOperation = vi.fn()
const mockDeleteRouteRule = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getOperationsCatalog: (...args: unknown[]) => mockGetOperationsCatalog(...args),
    getRoutings: (...args: unknown[]) => mockGetRoutings(...args),
    updateOperation: (...args: unknown[]) => mockUpdateOperation(...args),
    getSeedTemplates: (...args: unknown[]) => mockGetSeedTemplates(...args),
    applySeedTemplate: (...args: unknown[]) => mockApplySeedTemplate(...args),
    getRoutingGaps: (...args: unknown[]) => mockGetRoutingGaps(...args),
    getRouteSignals: (...args: unknown[]) => mockGetRouteSignals(...args),
    getOperationPositions: (...args: unknown[]) => mockGetOperationPositions(...args),
    getRouteRules: (...args: unknown[]) => mockGetRouteRules(...args),
    updateOperationPosition: (...args: unknown[]) => mockUpdateOperationPosition(...args),
    deleteOperation: (...args: unknown[]) => mockDeleteOperation(...args),
    deleteRouteRule: (...args: unknown[]) => mockDeleteRouteRule(...args),
  },
}))

import { toast } from 'sonner'
import ProcessConfigPage from '@/app/(dashboard)/production/routings/page'

/** 工序库（只用于 provenance 徽标；作用域**不再**从这里取） */
const CATALOG = {
  total: 2,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 'op-v54-01', name: '精裁-布', group: '裁剪', position: '布帘', unit: '米', unit_price: 0.4, is_must_finish: false, is_start_marker: true, scope: 'position' },
      ],
    },
    {
      group: '后道',
      operations: [
        { id: 'op-v54-24', name: '外帘打卷', group: '后道', position: '外帘', unit: '套', unit_price: 1, is_must_finish: false, is_start_marker: false, scope: 'set' },
      ],
    },
  ],
}

/**
 * 部位价目矩阵（契约 #4587 ①）：每格的 6 个变体元数据键里带 `scope` —— 抽屉的作用域就是它。
 * 两档齐备且**不同**：外帘打卷 = 套级（每樘窗一次）；精裁-布 = 部位级。
 */
const POSITIONS = [
  { id: 'pos-精裁-布帘', operation: '精裁', position: '布帘', unit_price: 0.4, applicable: true, variant_operation_id: 'op-v54-01', variant_name: '精裁-布', unit: '米', group: '裁剪', scope: 'position', is_must_finish: false },
  { id: 'pos-外帘打卷-布帘', operation: '外帘打卷', position: '布帘', unit_price: 1, applicable: true, variant_operation_id: 'op-v54-24', variant_name: '外帘打卷', unit: '套', group: '后道', scope: 'set', is_must_finish: false },
]

const ROUTINGS = { total: 0, routings: [] }

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 抽屉里某变体的「作用域」控件（select）—— 当前值即矩阵里那一档，改它就是改档。 */
const scopeControl = (id: string | number) =>
  screen.getByTestId(`variant-scope-${id}`) as HTMLSelectElement

const renderMatrix = async () => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
}

/** 打开某逻辑工序的「管理▸」抽屉（作用域 / 必完 的**唯一**入口，issue #4588） */
const openVariant = async (operation: string) => {
  await renderMatrix()
  await userEvent.click(screen.getByTestId(`matrix-manage-${operation}`))
  await waitFor(() => expect(screen.getByTestId('operations-manage-drawer')).toBeInTheDocument())
}

describe('工序「作用域」档位（issue #4384 A1；#4588 收进行抽屉）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-24', scope: 'position' }))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok([]))
    mockApplySeedTemplate.mockReset()
    mockGetRoutingGaps.mockReset().mockResolvedValue(ok({ unrouted_operations: [], signal_keys_without_route: [] }))
    mockGetRouteSignals.mockReset().mockResolvedValue(ok({ total: 0, signals: [] }))
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(POSITIONS))
    mockGetRouteRules.mockReset().mockResolvedValue(ok([]))
    mockUpdateOperationPosition.mockReset().mockResolvedValue(ok({ id: 'pos-精裁-布帘' }))
    mockDeleteOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-24', deleted: true }))
    mockDeleteRouteRule.mockReset().mockResolvedValue(ok({ id: 1, deleted: true }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('判据 4a：作用域入口在**抽屉**里；主表**不出现**「作用域」（用户 2026-09-19 裁定）', async () => {
    await openVariant('外帘打卷')

    const drawer = screen.getByTestId('operations-manage-drawer')
    // 红证（形态改造前）：`variant-scope-*` 不存在（当时这一列在已取消的「工序库明细」折叠区里）
    expect(within(drawer).getByTestId('variant-scope-op-v54-24')).toBeInTheDocument()
    // 反向断言：收进抽屉 = 主表里没有这个词（只断言「抽屉里有」会漏掉「两处都显示」）
    expect(within(screen.getByTestId('craft-operations-panel')).queryByText('作用域')).toBeNull()
  })

  it('判据 4b：逐行渲染**真实取值**（外帘打卷 = 套级；精裁-布 = 部位级）', async () => {
    await renderMatrix()

    await userEvent.click(screen.getByTestId('matrix-manage-外帘打卷'))
    expect(scopeControl('op-v54-24')).toHaveValue('set')
    expect(scopeControl('op-v54-24').selectedOptions[0]).toHaveTextContent('套级')

    await userEvent.click(screen.getByTestId('operations-manage-close'))
    await userEvent.click(screen.getByTestId('matrix-manage-精裁'))

    // 同一屏里必须与套级**区分开**（一律渲染成同一档 = 这个控件没有信息量）
    expect(scopeControl('op-v54-01')).toHaveValue('position')
    expect(scopeControl('op-v54-01').selectedOptions[0]).toHaveTextContent('部位级')
  })

  it('判据 4c：可就地改档 —— 套级改回部位级 ⇒ PUT 只提交 { scope }（不带单价等无关字段）', async () => {
    await openVariant('外帘打卷')

    await userEvent.selectOptions(scopeControl('op-v54-24'), 'position')

    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-24', { scope: 'position' }),
    )
    // 只提交 scope（部分更新口径）：顺手带上 unit_price 会把并发改动覆盖回去
    expect(mockUpdateOperation.mock.calls[0][1]).toEqual({ scope: 'position' })
    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalled())
  })

  it('判据 4d：可双向改 —— 部位级改成套级 ⇒ PUT { scope: "set" }', async () => {
    await openVariant('精裁')

    await userEvent.selectOptions(scopeControl('op-v54-01'), 'set')

    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-01', { scope: 'set' }),
    )
  })

  it('判据 4e：写失败不假装成功（报错且不弹成功 toast）', async () => {
    mockUpdateOperation.mockRejectedValueOnce(new Error('boom'))
    await openVariant('外帘打卷')

    await userEvent.selectOptions(scopeControl('op-v54-24'), 'position')

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalled())
    expect(vi.mocked(toast.success)).not.toHaveBeenCalled()
  })
})
