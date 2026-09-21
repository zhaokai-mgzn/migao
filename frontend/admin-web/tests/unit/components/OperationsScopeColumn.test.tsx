// case_ids: PG-039
// PG-039（issue #4384 A1）的**前端半边**，2026-09-21 **改判**（issue #4960，用户裁定原文）：
//   「下发加工的时候仍然要实例化，这种情况仍然得保留作用域，所以不能直接删，作用域得换一种叫法，
//     现在很难理解」＋「要么还是移除作用域，生成工序实例时，显示为 工序名+布/纱？」
// ⇒ **只删商家写面**：抽屉里的 `variant-scope-*` 控件与那句解释一起退场；
//   **语义与 DB 取值（`position` / `set`）一字不动** —— 后端 `production_operations.scope`
//   仍是实例化的唯一来源，本页只是**不再让商家改它**。
//   （实例显示名走 `frontend/admin-web/src/lib/operation-display.ts` 的 `operationDisplayName`。）
//
// 判据（**移除**类 ⇒ 红证形态 = 「改前**存在**，断言它**不存在**」，不是「找不到元素」）：
//   ① 抽屉里**没有** `variant-scope-*`（不是禁用、不是隐藏）；
//   ② 抽屉说明句不再出现「作用域 / 按套 / 按件」（商家不需要这个概念）；
//   ③ 这一屏的写请求**不带** `scope` 键（退场的是**用户动作**，不是请求契约）；
//   ④ 维护面其余各项**一个都没少**（分组 / 单位 / 停用 / 删除）。
//
// 为什么这条判据仍承重（真值源 docs/curtain-production-rules.md §8）：**外帘**是加工单打印行部位、
// **不是**路线键，但 V54/V58 种子把 外帘打卷/外帘装袋/外帘发货 逐条写进每一条部位路线（含纱帘）
// ⇒ 一樘「布 + 纱」时这 3 道各实例化 2 次 ⇒ 各 ¥1.0 双付。「每樘窗一次」这件事**仍在**
// （DB 值 `scope='set'`），变的只是它**不再是一个商家配置项**。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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
// issue #4677 的 `operation-layers` 读面：本文件的判据不涉及「打包发货」聚合 ⇒ 恒给空段。
// ⚠️ 该读面在**本页**并非零消费者（`production-routings.test.tsx` 的 B3 用 `operation-price-打包`
// 判它的聚合口径）—— 这里只是本文件不需要那份夹具（原 `layersOf()` 手工聚合器随之删除）。
const mockGetOperationLayers = vi.fn()
const mockGetRouteRules = vi.fn()
// issue #4616：规则创建弹窗的触发值取值域（工艺词表 + 加工项目录）
const mockGetRouteRuleOptions = vi.fn()
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

/** 工序库（只用于 provenance 徽标与分组/单位写面的**库行**） */
const CATALOG = {
  total: 2,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 'op-v54-01', name: '精裁-布', group: '裁剪', position: '布帘', unit: '米', unit_price: 0.4, is_start_marker: true, scope: 'position' },
      ],
    },
    {
      group: '后道',
      operations: [
        { id: 'op-v54-24', name: '外帘打卷', group: '后道', position: '外帘', unit: '套', unit_price: 1, is_start_marker: false, scope: 'set' },
      ],
    },
  ],
}

/**
 * 价目读面的行（契约 #4587 ①）：`scope` 仍是**服务端契约键**（本页不再据此渲染任何控件）。
 * ⚠️ `外帘打卷` 这一行的 DB 值仍是 `set`（「每樘窗一次」这件事**没变**）—— 变的只是
 * 商家面不再有可以改它的控件。
 */
const POSITIONS = [
  { id: 'pos-精裁-布帘', operation: '精裁', position: '布帘', unit_price: 0.4, variant_operation_id: 'op-v54-01', unit: '米', group: '裁剪', scope: 'position' },
  { id: 'pos-外帘打卷-布帘', operation: '外帘打卷', position: '布帘', unit_price: 1, variant_operation_id: 'op-v54-24', unit: '套', group: '后道', scope: 'set' },
]

const ROUTINGS = { total: 0, routings: [] }

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 打开某道工序的「管理▸」抽屉（分组 / 单位 / 停用 / 删除 的**唯一**入口） */
const openVariant = async (operation: string) => {
  render(<ProcessConfigPage />)
  await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId(`matrix-manage-${operation}`))
  await waitFor(() => expect(screen.getByTestId('operations-manage-drawer')).toBeInTheDocument())
}

describe('工序「作用域」写面退场（issue #4960；原 #4384 A1 / #4588 收进抽屉）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-24' }))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok([]))
    mockApplySeedTemplate.mockReset()
    mockGetRoutingGaps.mockReset().mockResolvedValue(ok({ unrouted_operations: [], signal_keys_without_route: [] }))
    mockGetRouteSignals.mockReset().mockResolvedValue(ok({ total: 0, signals: [] }))
    mockGetOperationPositions.mockReset().mockResolvedValue(ok(POSITIONS))
    mockGetOperationLayers.mockReset().mockResolvedValue(ok({ operations: [], delivery: [] }))
    mockGetRouteRules.mockReset().mockResolvedValue(ok([]))
    mockGetRouteRuleOptions.mockReset().mockResolvedValue(ok({ crafts: [], processing_items: [] }))
    mockUpdateOperationPosition.mockReset().mockResolvedValue(ok({ id: 'pos-精裁-布帘' }))
    mockDeleteOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-24', deleted: true }))
    mockDeleteRouteRule.mockReset().mockResolvedValue(ok({ id: 1, deleted: true }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('#4960-② 抽屉里没有 `variant-scope-*`，说明句也不再解释「作用域 / 按套 / 按件」', async () => {
    await openVariant('外帘打卷')

    // 改前的事实：这里有一个 `<select data-testid="variant-scope-op-v54-24" value="set">`
    //（两档选项「按套 / 按件」）＋ 一句「按套 = 每套窗只做一次；按件 = 每件各做一次」。
    expect(document.body.querySelector('[data-testid^="variant-scope-"]')).toBeNull()

    const drawer = screen.getByTestId('operations-manage-drawer')
    expect(drawer).not.toHaveTextContent('作用域')
    // ⚠️ 只断言**作用域专属**的措辞：抽屉的「适用条件」一节里「特殊选项按套收费（元/套）」
    // 说的是**计价**（另一本账），不能拿光秃秃的「按套」当判据。
    expect(drawer).not.toHaveTextContent('每套窗只做一次')
    expect(drawer).not.toHaveTextContent('按件')
    // 抽屉本身照旧（移除的是一项配置，不是整块维护面）
    expect(drawer).toHaveTextContent('外帘打卷')
  })

  it('#4960-③ 写面只剩 分组 / 单位 / 停用 / 删除，且写请求里**没有** `scope` 键', async () => {
    await openVariant('外帘打卷')

    // 分组 · 单位：铅笔 → 保存 ⇒ body 恰为 `{group_name, unit}`（不含 scope）
    await userEvent.click(screen.getByTestId('variant-meta-edit-op-v54-24'))
    await userEvent.click(screen.getByTestId('variant-meta-save-op-v54-24'))
    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-24', { group_name: '后道', unit: '套' }),
    )
    expect(Object.keys(mockUpdateOperation.mock.calls[0][1] as object)).toEqual(['group_name', 'unit'])

    // 停用：既有写面照旧（`PUT /operations/{id}` 的 `status`）
    await userEvent.click(screen.getByTestId('variant-disable-op-v54-24'))
    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-24', { status: 'inactive' }))

    // 删除入口仍在（二次确认那一套见 production-routings.test.tsx ⑰-⑬）
    expect(screen.getByTestId('variant-delete-op-v54-24')).toBeInTheDocument()

    // 全量反向断言：**没有任何**写请求带 `scope` 键
    for (const call of mockUpdateOperation.mock.calls) {
      expect(Object.keys(call[1] as object)).not.toContain('scope')
    }
  })
})
