// case_ids: PG-020
// 复用既有用例 PG-020（工序库写面 / 工序库页 —— 同页既有前端单测 production-operations.test.tsx
// 也是这么挂的）；本单不新增用例 ID，理由见 PR body（新增用例会触发 case-trust burn-down 预算 +
// 与 #4361 争生成物）。
// PG-020（issue #4363 前端半边；契约所有者 #4361）：工序库页 /production/operations ——
// ① provenance 徽标（三态 实证 / 推算 / 占位待确认）可见，且「占位待确认」指向**既有版本化改价写面**；
// ② 「一键套用行业模板」入口（存量非 1 号租户工序库为空 ⇒ 这是补救路径），交互照知识库页范式
//    （确认弹窗 + 套用结果 toast「新增 N 条、跳过 M 条」）。
// 反 placeholder：断言落到**真实数据行**（工序名/单价/分组 + 路线步骤），且徽标**双向断言**
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

vi.mock('@/lib/api', () => ({
  productionApi: {
    getOperationsCatalog: (...args: unknown[]) => mockGetOperationsCatalog(...args),
    getRoutings: (...args: unknown[]) => mockGetRoutings(...args),
    updateOperation: (...args: unknown[]) => mockUpdateOperation(...args),
    getSeedTemplates: (...args: unknown[]) => mockGetSeedTemplates(...args),
    applySeedTemplate: (...args: unknown[]) => mockApplySeedTemplate(...args),
    getRoutingGaps: (...args: unknown[]) => mockGetRoutingGaps(...args),
    getRouteSignals: (...args: unknown[]) => mockGetRouteSignals(...args),
  },
}))

import { toast } from 'sonner'
import ProcessConfigPage from '@/app/(dashboard)/production/routings/page'

/** 三态齐备的工序目录：实证 / 推算 / 占位待确认 各一道（真实行，带库口径单价） */
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

const ROUTINGS = {
  total: 2,
  routings: [
    {
      id: 1,
      curtain_type: '布帘',
      craft: '韩褶',
      operation_count: 2,
      source: '推算',
      operations: [
        { seq: 1, operation: '精裁-布', group: '裁剪', unit: '套', unit_price: 8.5, is_must_finish: false, is_start_marker: true },
        { seq: 2, operation: '罗马帘-成型', group: '裁剪', unit: '件', unit_price: 3, is_must_finish: false, is_start_marker: false },
      ],
    },
    {
      id: 2,
      curtain_type: '罗马帘',
      craft: '平幔',
      operation_count: 1,
      source: '占位待确认',
      operations: [
        { seq: 1, operation: '罗马帘-成型', group: '裁剪', unit: '件', unit_price: 3, is_must_finish: false, is_start_marker: false },
      ],
    },
  ],
}

/** 行业模板目录（契约：#4361 GET /api/admin/production/seed-templates） */
const TEMPLATES = [
  { templateId: 'curtain', industry: 'curtain', name: '布艺 / 窗帘 生产模板', version: 1, description: '窗帘行业预置工序与工艺路线（初始价，待客户确认）' },
]

/** 套用结果（契约：POST /api/admin/production/seed-templates/{templateId}/apply） */
const APPLY_RESULT = { created_operations: 30, created_routings: 9, skipped: 4 }

const ok = (data: unknown) => ({ data: { success: true, data } })

describe('工序库页 provenance 徽标 + 一键套用行业模板（issue #4363）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 103, name: '罗马帘-成型', unit_price: 3 }))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok(TEMPLATES))
    mockApplySeedTemplate.mockReset().mockResolvedValue(ok(APPLY_RESULT))
    mockGetRoutingGaps.mockReset().mockResolvedValue(ok({ unrouted_operations: [], signal_keys_without_route: [] }))
    mockGetRouteSignals.mockReset().mockResolvedValue(ok({ total: 0, signals: [] }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('渲染真实工序数据：总数 + 工序名 + 库口径单价（反 placeholder）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('3'))
    expect(screen.getByTestId('operation-row-101')).toHaveTextContent('精裁-布')
    expect(screen.getByTestId('operation-row-101')).toHaveTextContent('¥8.50')
    expect(screen.getByTestId('operation-row-103')).toHaveTextContent('罗马帘-成型')
  })

  it("source='占位待确认' 的工序渲染「待确认」徽标（商家看得懂的「初始价·待确认」）", async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-103')).toBeInTheDocument())

    const badge = within(screen.getByTestId('operation-row-103')).getByTestId('operation-source-103')
    expect(badge).toHaveTextContent('初始价·待确认')
  })

  it("source='实证' 的行**不**渲染「待确认」徽标（双向断言，防永远显示）", async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-101')).toBeInTheDocument())

    const row = screen.getByTestId('operation-row-101')
    expect(within(row).getByTestId('operation-source-101')).toHaveTextContent('实证')
    expect(within(row).queryByText(/待确认/)).not.toBeInTheDocument()
  })

  it("source='推算' 的行渲染「推算」徽标且不带「待确认」（三态互斥）", async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-102')).toBeInTheDocument())

    const row = screen.getByTestId('operation-row-102')
    expect(within(row).getByTestId('operation-source-102')).toHaveTextContent('推算')
    expect(within(row).queryByText(/待确认/)).not.toBeInTheDocument()
  })

  it('「占位待确认」是可行动引导：点徽标即进入该工序的改价入口（既有版本化写面）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-103')).toBeInTheDocument())

    // 未点击前没有输入框（改价入口是徽标本身，不是只有一个红点）
    expect(screen.queryByTestId('operation-price-input-103')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('operation-source-103'))
    expect(screen.getByTestId('operation-price-input-103')).toBeInTheDocument()
  })

  it('工艺路线区展示路线的 source（三态口径与工序一致）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('routing-布帘×韩褶')).toBeInTheDocument())

    expect(within(screen.getByTestId('routing-布帘×韩褶')).getByTestId('routing-source-布帘×韩褶')).toHaveTextContent('推算')
    const placeholderRoute = within(screen.getByTestId('routing-罗马帘×平幔'))
    expect(placeholderRoute.getByTestId('routing-source-罗马帘×平幔')).toHaveTextContent('初始价·待确认')
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
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('3'))
    expect(screen.queryByTestId('seed-templates')).not.toBeInTheDocument()
  })

  it('工序库为空 ⇒ 空态显式指向「补套行业模板」（存量租户补救路径）', async () => {
    mockGetOperationsCatalog.mockResolvedValue(ok({ total: 0, groups: [] }))
    mockGetRoutings.mockResolvedValue(ok({ total: 0, routings: [] }))
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operations-catalog-empty')).toBeInTheDocument())
    expect(screen.getByTestId('operations-catalog-empty')).toHaveTextContent('补套行业模板')
  })
})
