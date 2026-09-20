// case_ids: PG-020
// 复用既有用例 PG-020（工序库写面 / 工艺配置页 —— 同页既有前端单测 production-routings.test.tsx
// 也是这么挂的）；本单不新增用例 ID，理由见 PR body（新增用例会触发 case-trust burn-down 预算 +
// 与 #4361 争生成物）。
// PG-020（issue #4363 前端半边；契约所有者 #4361）：工序的 provenance 徽标（三态 实证 / 推算 /
// 占位待确认）可见；「一键套用行业模板」入口（存量非 1 号租户工序库为空 ⇒ 这是补救路径），
// 交互照知识库页范式（确认弹窗 + 套用结果 toast「新增 N 条、跳过 M 条」）。
//
// ⚠️ issue #4588（母单 #4586 包 B；契约 #4587）**改了承载形态**：「工序库明细」折叠次区已取消，
// 工序的明细面（含 provenance 徽标）收进「工艺项」单表的行尾「管理▸」抽屉；而**改价入口统一到
// 矩阵格**（一屏一张表 ⇒ 只有一个价载体）。徽标因此从「可点击的改价入口」变为**纯标注**：
// 点它不再冒输入框，改价只能从矩阵格进（这条本身就是 #4588 的验收判据）。
// 反 placeholder：断言落到**真实数据行**（矩阵真实价 + 抽屉里的部位/元数据），且徽标**双向断言**
// （占位行必须渲染「待确认」；实证行必须**不**渲染 —— 防「永远显示」的空断言）。
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
// issue #4677：两层分区读面（页面同时读 `operation-positions` 与 `operation-layers`）
const mockGetOperationLayers = vi.fn()
const mockGetRouteRules = vi.fn()
// issue #4616：规则创建弹窗的触发值取值域（工艺词表 + 加工项目录）
const mockGetRouteRuleOptions = vi.fn()
// issue #4588：矩阵格写面 + 工序/规则软删（本文件只用到矩阵格入口，其余备齐 mock 形态）
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
    getOperationLayers: (...args: unknown[]) => mockGetOperationLayers(...args),
    getRouteRules: (...args: unknown[]) => mockGetRouteRules(...args),
    getRouteRuleOptions: (...args: unknown[]) => mockGetRouteRuleOptions(...args),
    updateOperationPosition: (...args: unknown[]) => mockUpdateOperationPosition(...args),
    deleteOperation: (...args: unknown[]) => mockDeleteOperation(...args),
    deleteRouteRule: (...args: unknown[]) => mockDeleteRouteRule(...args),
  },
}))

import { toast } from 'sonner'
import ProcessConfigPage from '@/app/(dashboard)/production/routings/page'

/** 三态齐备的工序库：实证 / 推算 / 占位待确认 各一道（`id` 与矩阵的 `variant_operation_id` 同源） */
const CATALOG = {
  total: 3,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 101, name: '精裁-布', group: '裁剪', position: '布帘', unit: '套', unit_price: 8.5, is_must_finish: false, is_start_marker: true, source: '实证' },
        { id: 102, name: '上车布-纱', group: '裁剪', position: '纱帘', unit: '米', unit_price: 0.5, is_must_finish: false, is_start_marker: false, source: '推算' },
        { id: 103, name: '罗马帘-成型', group: '裁剪', position: '罗马帘', unit: '件', unit_price: 3, is_must_finish: false, is_start_marker: false, source: '占位待确认' },
      ],
    },
  ],
}

/**
 * 部位价目矩阵（契约 #4587 ①）：变体元数据把三态工序逐道挂到逻辑工序上
 * ⇒ 抽屉里每道变体都能查到自己的 provenance（按 `variant_operation_id` = 工序库 `id`）。
 */
const POSITIONS = [
  { id: 'pos-精裁-布帘', operation: '精裁', position: '布帘', unit_price: 8.5, applicable: true, variant_operation_id: '101', unit: '套', group: '裁剪', scope: 'position', is_must_finish: false },
  { id: 'pos-上车布-纱帘', operation: '上车布', position: '纱帘', unit_price: 0.5, applicable: true, variant_operation_id: '102', unit: '米', group: '裁剪', scope: 'position', is_must_finish: false },
  { id: 'pos-罗马帘-帘头', operation: '罗马帘', position: '帘头', unit_price: 3, applicable: true, variant_operation_id: '103', unit: '件', group: '裁剪', scope: 'position', is_must_finish: false },
]

const ROUTINGS = {
  total: 2,
  routings: [
    { id: 11, name: '窗帘工序路线（默认）', is_default: true, positions: ['布帘', '纱帘', '帘头'], mainline: ['精裁-布'], status: 'active' },
    { id: 12, name: '罗马帘专线', is_default: false, positions: ['罗马帘'], mainline: [], status: 'active' },
  ],
}

/** 行业模板目录（契约：#4361 GET /api/admin/production/seed-templates） */
const TEMPLATES = [
  { templateId: 'curtain', industry: 'curtain', name: '布艺 / 窗帘 生产模板', version: 1, description: '窗帘行业预置工序与工艺路线（初始价，待客户确认）' },
]

/** 套用结果（契约：POST /api/admin/production/seed-templates/{templateId}/apply） */
const APPLY_RESULT = { created_operations: 30, created_routings: 9, skipped: 4 }

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 打开某逻辑工序的「管理▸」抽屉（变体明细面 —— 原「工序库明细」折叠区的落点） */
const openVariant = async (operation: string) => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId(`matrix-manage-${operation}`))
  await waitFor(() => expect(screen.getByTestId('operations-manage-drawer')).toBeInTheDocument())
}

describe('工序 provenance 徽标 + 一键套用行业模板（issue #4363；#4588 收进抽屉）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 103, name: '罗马帘-成型', unit_price: 3 }))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockApplySeedTemplate.mockReset().mockResolvedValue(ok(APPLY_RESULT))
    mockGetRoutingGaps.mockReset().mockResolvedValue(ok({ unrouted_operations: [], signal_keys_without_route: [] }))
    mockGetRouteSignals.mockReset().mockResolvedValue(ok({ total: 0, signals: [] }))

/**
 * `getOperationLayers` 的替身（issue #4677）：页面读**两个**端点 ——
 * ① `GET /operation-positions`（拿格的 `id` ⇒ 抽屉写面寻址）与 ② `GET /operation-layers`
 * （两层分区 + 「打包发货」一列价聚合）。两者必须是**同一份**数据 ⇒ 这里从 `POSITIONS`
 * **按既有 `scope` 分区**（口径照抄后端 `ProductionRoutingReadService.deliveryView`）。
 */
const layersOf = (cells: any[]) => {
  const deliveryCells = new Map<string, any[]>()
  const operations: any[] = []
  for (const c of cells) {
    if (c.scope === 'set') deliveryCells.set(c.operation, [...(deliveryCells.get(c.operation) ?? []), c])
    else operations.push(c)
  }
  const delivery = [...deliveryCells.entries()].map(([operation, group]) => {
    const applicable = group.filter((c) => c.applicable === true)
    const prices = [...new Set(applicable.filter((c) => c.unit_price != null).map((c) => c.unit_price))]
    const unpriced = applicable.some((c) => c.unit_price == null)
    const price_state =
      applicable.length === 0
        ? 'no_applicable_position'
        : unpriced
          ? 'unpriced'
          : prices.length === 1
            ? 'priced'
            : 'multiple_prices'
    const first = (k: string) => group.find((c) => c[k] != null)?.[k] ?? null
    return {
      operation,
      scope: 'set',
      unit: first('unit'),
      group: first('group'),
      is_must_finish: first('is_must_finish'),
      price: price_state === 'priced' ? prices[0] : null,
      price_state,
      different_price_count: price_state === 'multiple_prices' ? prices.length : 0,
      applicable_positions: applicable.map((c) => c.position),
    }
  })
  return { operations, delivery }
}

    mockGetOperationPositions.mockReset().mockResolvedValue(ok(POSITIONS))
    // (issue #4677) 分区读面与矩阵夹具**同源** —— 一处换、两处同步
    mockGetOperationLayers.mockReset().mockResolvedValue(ok(layersOf(POSITIONS)))

    mockGetRouteRules.mockReset().mockResolvedValue(ok([]))
    mockGetRouteRuleOptions.mockReset().mockResolvedValue(ok({ crafts: [], processing_items: [] }))
    mockUpdateOperationPosition.mockReset().mockResolvedValue(ok({ id: 'pos-罗马帘-帘头' }))
    mockDeleteOperation.mockReset().mockResolvedValue(ok({ id: '103', deleted: true }))
    mockDeleteRouteRule.mockReset().mockResolvedValue(ok({ id: 1, deleted: true }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('渲染真实数据：这一屏的价来自**部位价目矩阵**，部位/元数据在抽屉里（反 placeholder）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix-total')).toHaveTextContent('3'))

    // 价：矩阵格（唯一价载体）
    expect(screen.getByTestId('matrix-cell-精裁-布帘')).toHaveTextContent('¥8.50')
    expect(screen.getByTestId('matrix-cell-罗马帘-帘头')).toHaveTextContent('¥3.00')
    // issue #4622：矩阵行首**不再**显示变体名（改前这里断言的是 `matrix-variants-罗马帘` = `罗马帘-成型`）
    expect(screen.queryByTestId('matrix-variants-罗马帘')).toBeNull()

    // 抽屉：条目主标识 = **部位**（不是变体名）+ 分组·单位（逐字来自矩阵，不是发明出来的）
    await userEvent.click(screen.getByTestId('matrix-manage-罗马帘'))
    const row = screen.getByTestId('variant-row-103')
    expect(row).toHaveTextContent('帘头')
    expect(row).not.toHaveTextContent('罗马帘-成型')
    expect(row).toHaveTextContent('裁剪')
    expect(row).toHaveTextContent('件')
  })

  it("source='占位待确认' 的变体渲染「初始价·待确认」徽标（商家看得懂的文案）", async () => {
    await openVariant('罗马帘')

    const badge = within(screen.getByTestId('variant-row-103')).getByTestId('variant-source-103')
    expect(badge).toHaveTextContent('初始价·待确认')
  })

  it("source='实证' 的行**不**渲染「待确认」徽标（双向断言，防永远显示）", async () => {
    await openVariant('精裁')

    const row = screen.getByTestId('variant-row-101')
    expect(within(row).getByTestId('variant-source-101')).toHaveTextContent('实证')
    expect(within(row).queryByText(/待确认/)).not.toBeInTheDocument()
  })

  it("source='推算' 的行渲染「推算」徽标且不带「待确认」（三态互斥）", async () => {
    await openVariant('上车布')

    const row = screen.getByTestId('variant-row-102')
    expect(within(row).getByTestId('variant-source-102')).toHaveTextContent('推算')
    expect(within(row).queryByText(/待确认/)).not.toBeInTheDocument()
  })

  it('改价只有**一个**入口（矩阵格）：抽屉里的徽标只做标注，点它不开输入框', async () => {
    await openVariant('罗马帘')

    // 未点击前没有输入框
    expect(screen.queryByTestId('matrix-price-input-罗马帘-帘头')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('variant-source-103'))
    // #4588：徽标不再承担改价入口（一屏一张表 ⇒ 价只有一个载体）
    expect(screen.queryByTestId('matrix-price-input-罗马帘-帘头')).not.toBeInTheDocument()

    await userEvent.click(screen.getByTestId('operations-manage-close'))
    await userEvent.click(screen.getByTestId('matrix-price-edit-罗马帘-帘头'))
    expect(screen.getByTestId('matrix-price-input-罗马帘-帘头')).toBeInTheDocument()
  })

  it('工艺路线区渲染**新模型**的真实数据（总名 + 默认徽标；默认徽标不得写死）', async () => {
    render(<ProcessConfigPage />)
    // issue #4482：路线内容在「工艺路线」tab 上（默认落在「工艺项」）
    await waitFor(() => expect(screen.getByTestId('process-config-tab-routes')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('process-config-tab-routes'))
    await waitFor(() => expect(screen.getByTestId('routing-11')).toBeInTheDocument())

    // ⚠️ issue #4433（P2b #4459 之后）：路线 provenance 已不在契约里（`templateView` 无 source）
    // ⇒ 本文件不再断言它（按不存在的字段渲染 = 发明）；改断言新形态的等价事实：总名 + 默认徽标。
    expect(screen.getByTestId('routing-name-11')).toHaveTextContent('窗帘工序路线（默认）')
    expect(screen.getByTestId('routing-default-11')).toHaveTextContent('默认')
    expect(within(screen.getByTestId('routing-12')).queryByTestId('routing-default-12')).toBeNull()
  })

  // ⚠️ issue #4416：行业模板卡**仅在工序库为空时**渲染（开租时 RegistrationService 已自动套用，
  // 常驻卡片会让商家误以为必须手点）⇒ 这一组用例必须先把工序库置空。
  it('行业模板列表渲染真实数据（名称 + 版本 + 说明）', async () => {
    mockGetOperationsCatalog.mockResolvedValue(ok({ total: 0, groups: [] }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('seed-template-curtain')).toBeInTheDocument())

    const row = screen.getByTestId('seed-template-curtain')
    expect(row).toHaveTextContent('布艺 / 窗帘 生产模板')
    expect(row).toHaveTextContent('v1')
    expect(row).toHaveTextContent('初始价，待客户确认')
  })

  it('一键套用：先确认（未确认不得调端点）→ 调 apply → toast 显示 mock 返回的真实数字', async () => {
    mockGetOperationsCatalog.mockResolvedValue(ok({ total: 0, groups: [] }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('seed-template-curtain')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('seed-template-apply-curtain'))
    // 防误触：确认弹窗先出现，此时**尚未**调用 apply 端点
    expect(screen.getByTestId('seed-template-apply-confirm')).toBeInTheDocument()
    expect(mockApplySeedTemplate).not.toHaveBeenCalled()

    await userEvent.click(screen.getByTestId('seed-template-apply-confirm'))
    await waitFor(() => expect(mockApplySeedTemplate).toHaveBeenCalledWith('curtain'))

    // 数字必须来自 mock 响应（30 道工序 / 9 条路线 / 跳过 4 条），不是写死的占位文案
    const message = vi.mocked(toast.success).mock.calls.at(-1)?.[0] as string
    expect(message).toContain('30')
    expect(message).toContain('9')
    expect(message).toContain('4')
    expect(message).toContain('跳过')
  })

  it('套用后重新拉取工序目录（结果可见，不静默）', async () => {
    mockGetOperationsCatalog.mockResolvedValue(ok({ total: 0, groups: [] }))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('seed-template-curtain')).toBeInTheDocument())
    expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByTestId('seed-template-apply-curtain'))
    await userEvent.click(screen.getByTestId('seed-template-apply-confirm'))

    await waitFor(() => expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(2))
  })

  it('工序库非空 ⇒ **不渲染**行业模板卡（开租已自动套用，不该让用户手动点）', async () => {
    // ⚠️ issue #4677（设计 §6 修法 A）**改判**：入口判据从「工序库为空」变成「**缺失即显示**」
    // （工序库为空 ∨ 两条基础路线不齐）⇒ 这条用例的前提必须是**两条基础路线齐**
    // （否则它测的就不是「工序库非空」这件事，而是「缺布料路线」）。
    // 判据本身**不放宽**：什么都不缺 ⇒ 不给一个点了也没用的入口。
    mockGetRoutings.mockReset().mockResolvedValue(
      ok({
        total: 2,
        routings: [
          ...ROUTINGS.routings,
          { id: 13, name: '布料工序路线', is_default: false, positions: ['布料'], mainline: ['裁剪', '打包'], status: 'active' },
        ],
      }),
    )
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument())
    expect(screen.queryByTestId('seed-templates')).not.toBeInTheDocument()
  })

  it('工序库为空 ⇒ 仍显式给出「补套行业模板」这条补救路径（存量租户）', async () => {
    mockGetOperationsCatalog.mockResolvedValue(ok({ total: 0, groups: [] }))
    mockGetRoutings.mockResolvedValue(ok({ total: 0, routings: [] }))
    render(<ProcessConfigPage />)

    // 卡片（含标题里的「补套行业模板」）+ 就绪度第 1 步的指路文案
    await waitFor(() => expect(screen.getByTestId('seed-templates')).toBeInTheDocument())
    expect(screen.getByTestId('seed-templates')).toHaveTextContent('补套行业模板')
    expect(screen.getByTestId('readiness-step-operations')).toHaveTextContent('行业模板')
  })
})
