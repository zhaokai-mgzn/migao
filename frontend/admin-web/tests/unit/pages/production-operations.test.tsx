// case_ids: PG-020
// PG-020（issue #4203 / #4204，前端半边）：工序库页 /production/operations ——
// 消费 GET /api/admin/production/operations-catalog（30 道工序，按分组）与
// GET /api/admin/production/routings（6 条工艺路线），并支持改单价 / 必完开关（PUT）。
// 反 placeholder：必须断言渲染出**真实数据**（工序名/单价/分组/路线步骤），不能只断言页面存在。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetOperationsCatalog = vi.fn()
const mockGetRoutings = vi.fn()
const mockUpdateOperation = vi.fn()
// 行业模板（issue #4363 新增的第三条只读端点 + 套用写面）：本文件只做本页回归，返回空目录
const mockGetSeedTemplates = vi.fn()
const mockApplySeedTemplate = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getOperationsCatalog: (...args: unknown[]) => mockGetOperationsCatalog(...args),
    getRoutings: (...args: unknown[]) => mockGetRoutings(...args),
    updateOperation: (...args: unknown[]) => mockUpdateOperation(...args),
    getSeedTemplates: (...args: unknown[]) => mockGetSeedTemplates(...args),
    applySeedTemplate: (...args: unknown[]) => mockApplySeedTemplate(...args),
  },
}))

import { toast } from 'sonner'
import OperationsCatalogPage from '@/app/(dashboard)/production/operations/page'

const CATALOG = {
  total: 30,
  groups: [
    {
      group: '裁剪',
      operations: [
        { id: 101, name: '精裁-布', group: '裁剪', position: '布帘', unit: '套', unit_price: 8.5, is_must_finish: false, is_start_marker: true },
        { id: 102, name: '精裁-纱', group: '裁剪', position: '纱帘', unit: '套', unit_price: 6, is_must_finish: false, is_start_marker: false },
      ],
    },
    {
      group: '车位',
      operations: [
        { id: 201, name: '韩褶-布', group: '车位', position: '布帘', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
      ],
    },
    {
      group: '后道',
      operations: [
        { id: 301, name: '外帘装袋', group: '后道', position: '外帘', unit: '件', unit_price: 0.4, is_must_finish: true, is_start_marker: false },
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
      operation_count: 3,
      operations: [
        { seq: 1, operation: '精裁-布', group: '裁剪', unit: '套', unit_price: 8.5, is_must_finish: false, is_start_marker: true },
        { seq: 2, operation: '韩褶-布', group: '车位', unit: '米', unit_price: 1.2, is_must_finish: false, is_start_marker: false },
        { seq: 3, operation: '外帘装袋', group: '后道', unit: '件', unit_price: 0.4, is_must_finish: true, is_start_marker: false },
      ],
    },
    {
      id: 2,
      curtain_type: '布帘',
      craft: '打孔',
      operation_count: 1,
      operations: [
        { seq: 1, operation: '打孔-布', group: '车位', unit: '个', unit_price: 0.6, is_must_finish: false, is_start_marker: false },
      ],
    },
  ],
}

const ok = (data: unknown) => ({ data: { success: true, data } })

describe('工序库页 /production/operations', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 201, name: '韩褶-布', unit_price: 2.5 }))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok([]))
    mockApplySeedTemplate.mockReset()
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('渲染真实工序数据：总数 + ≥1 道工序名 + 库口径单价', async () => {
    render(<OperationsCatalogPage />)

    await waitFor(() => expect(screen.getByTestId('operations-catalog-total')).toHaveTextContent('30'))

    expect(within(screen.getByTestId('operation-row-201')).getByText('韩褶-布')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-101')).getByText('精裁-布')).toBeInTheDocument()
    expect(screen.getByTestId('operation-row-201')).toHaveTextContent('¥1.20')
    expect(screen.getByTestId('operation-row-101')).toHaveTextContent('¥8.50')
  })

  it('按工序分组展示（裁剪/车位/后道 三个分组标题 + 各自行数）', async () => {
    render(<OperationsCatalogPage />)

    await waitFor(() => expect(screen.getByTestId('operation-group-裁剪')).toBeInTheDocument())
    expect(within(screen.getByTestId('operation-group-裁剪')).getAllByTestId(/^operation-row-/)).toHaveLength(2)
    expect(within(screen.getByTestId('operation-group-车位')).getAllByTestId(/^operation-row-/)).toHaveLength(1)
    expect(within(screen.getByTestId('operation-group-后道')).getAllByTestId(/^operation-row-/)).toHaveLength(1)
  })

  it('渲染工艺路线：路线数与每道步骤（含库口径单位/单价）', async () => {
    render(<OperationsCatalogPage />)

    await waitFor(() => expect(screen.getByTestId('routings-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('routing-布帘-韩褶')).toHaveTextContent('3 道工序')
    expect(screen.getByTestId('routing-step-布帘-韩褶-2')).toHaveTextContent('韩褶-布')
    expect(screen.getByTestId('routing-step-布帘-韩褶-2')).toHaveTextContent('¥1.20')
    expect(screen.getByTestId('routing-布帘-打孔')).toHaveTextContent('打孔-布')
  })

  it('必完开关按库口径渲染，且不误导（is_start_marker 不显示为「必完」）', async () => {
    render(<OperationsCatalogPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-301')).toBeInTheDocument())
    expect(within(screen.getByTestId('operation-row-301')).getByTestId('operation-must-finish-301')).toBeChecked()
    expect(within(screen.getByTestId('operation-row-101')).getByTestId('operation-must-finish-101')).not.toBeChecked()
    // 首工序标记（精裁-布 is_start_marker=true）不得被渲染成「必完」
    expect(within(screen.getByTestId('operation-row-101')).queryByText('必完')).not.toBeInTheDocument()
  })

  it('改单价：编辑单价 → 保存 → 调 PUT 只提交 unit_price 并刷新列表', async () => {
    render(<OperationsCatalogPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-201')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('operation-price-edit-201'))
    const input = screen.getByTestId('operation-price-input-201')
    await userEvent.clear(input)
    await userEvent.type(input, '2.5')
    await userEvent.click(screen.getByTestId('operation-price-save-201'))

    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith(201, { unit_price: 2.5 }))
    await waitFor(() => expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(2))
  })

  it('切必完开关：调 PUT 提交 is_must_finish 布尔值', async () => {
    render(<OperationsCatalogPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-201')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('operation-must-finish-201'))

    await waitFor(() => expect(mockUpdateOperation).toHaveBeenCalledWith(201, { is_must_finish: true }))
  })

  it('改单价失败：报错提示且不静默（toast.error）', async () => {
    mockUpdateOperation.mockRejectedValueOnce(new Error('403 forbidden'))
    render(<OperationsCatalogPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-201')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('operation-price-edit-201'))
    const input = screen.getByTestId('operation-price-input-201')
    await userEvent.clear(input)
    await userEvent.type(input, '9.9')
    await userEvent.click(screen.getByTestId('operation-price-save-201'))

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalled())
    // 失败不刷新（避免把失败伪装成成功）
    expect(mockGetOperationsCatalog).toHaveBeenCalledTimes(1)
  })
})
