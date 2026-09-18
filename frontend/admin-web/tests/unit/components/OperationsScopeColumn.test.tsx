// case_ids: PG-039
// PG-039（issue #4384 A1，前端半边）：工序库页 /production/operations 的「作用域」列 ——
// 列表逐行展示 部位级 / 套级，且可就地改档（PUT /api/admin/production/operations/{id} body 带 scope）。
//
// 为什么这条判据承重（真值源 docs/curtain-production-rules.md §8）：**外帘**是加工单打印行部位、
// **不是**路线键，但 V54/V58 种子把 外帘打卷/外帘装袋/外帘发货 逐条写进每一条部位路线（含纱帘）
// ⇒ 一樘「布 + 纱」时这 3 道各实例化 2 次 ⇒ 各 ¥1.0 双付。用户裁定（2026-09-19）：
// 「套级工序先按**每樘窗一次**实现，打卷是否每帘一次**留成可配**」
// ⇒ 「留成可配」的落码形态就是本页这一列：商家能看见、能改。
//
// 反 placeholder：断言渲染出**库里的真实取值**（套级/部位级逐行不同），不是只断言列存在；
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

/** 库口径：后道那三道外帘工序是**套级**（每樘窗一次），裁剪/车位是部位级。 */
const CATALOG = {
  total: 4,
  groups: [
    {
      group: '裁剪',
      operations: [
        {
          id: 'op-v54-01',
          name: '精裁-布',
          group: '裁剪',
          position: '布帘',
          unit: '米',
          unit_price: 0.4,
          is_must_finish: false,
          is_start_marker: true,
          scope: 'position',
        },
      ],
    },
    {
      group: '后道',
      operations: [
        {
          id: 'op-v54-24',
          name: '外帘打卷',
          group: '后道',
          position: '外帘',
          unit: '套',
          unit_price: 1,
          is_must_finish: false,
          is_start_marker: false,
          scope: 'set',
        },
        {
          id: 'op-v54-25',
          name: '外帘装袋',
          group: '后道',
          position: '外帘',
          unit: '套',
          unit_price: 1,
          is_must_finish: true,
          is_start_marker: false,
          scope: 'set',
        },
        {
          id: 'op-v54-27',
          name: '外帘发货',
          group: '后道',
          position: '外帘',
          unit: '套',
          unit_price: 1,
          is_must_finish: false,
          is_start_marker: false,
          scope: 'set',
        },
      ],
    },
  ],
}

const ROUTINGS = { total: 0, routings: [] }

const ok = (data: unknown) => ({ data: { success: true, data } })

/** 某行「作用域」控件（select）—— 当前值即库里那一档，改它就是改档。 */
const scopeControl = (id: string | number) =>
  screen.getByTestId(`operation-scope-${id}`) as HTMLSelectElement

describe('工序库页「作用域」列（issue #4384 A1）', () => {
  beforeEach(() => {
    mockGetOperationsCatalog.mockReset().mockResolvedValue(ok(CATALOG))
    mockGetRoutings.mockReset().mockResolvedValue(ok(ROUTINGS))
    mockUpdateOperation.mockReset().mockResolvedValue(ok({ id: 'op-v54-24', scope: 'position' }))
    mockGetSeedTemplates.mockReset().mockResolvedValue(ok([]))
    mockApplySeedTemplate.mockReset()
    mockGetRoutingGaps.mockReset().mockResolvedValue(ok({ unrouted_operations: [], signal_keys_without_route: [] }))
    mockGetRouteSignals.mockReset().mockResolvedValue(ok({ total: 0, signals: [] }))
    vi.mocked(toast.success).mockClear()
    vi.mocked(toast.error).mockClear()
  })

  it('判据 4a：工序目录渲染「作用域」列（列头存在）', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-24')).toBeInTheDocument())
    // 红证（实现前实测）：列头不存在 ⇒ getByRole('columnheader', { name: '作用域' }) 抛
    // 「Unable to find an accessible element with the role "columnheader" and name "作用域"」
    expect(
      within(screen.getByTestId('operation-group-后道')).getByRole('columnheader', { name: '作用域' }),
    ).toBeInTheDocument()
    expect(
      within(screen.getByTestId('operation-group-裁剪')).getByRole('columnheader', { name: '作用域' }),
    ).toBeInTheDocument()
  })

  it('判据 4b：逐行渲染**库里的真实取值**（外帘三道 = 套级；精裁-布 = 部位级）', async () => {
    render(<ProcessConfigPage />)

    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-24')).toBeInTheDocument())

    // 套级三道：显示文案必须是「套级」（不是只显示英文码、也不是一律显示部位级）
    for (const id of ['op-v54-24', 'op-v54-25', 'op-v54-27']) {
      expect(scopeControl(id)).toHaveValue('set')
      expect(scopeControl(id).selectedOptions[0]).toHaveTextContent('套级')
    }
    // 部位级：同一页里必须与套级**区分开**（一律渲染成同一档 = 这一列没有信息量）
    expect(scopeControl('op-v54-01')).toHaveValue('position')
    expect(scopeControl('op-v54-01').selectedOptions[0]).toHaveTextContent('部位级')
  })

  it('判据 4c：可就地改档 —— 套级改回部位级 ⇒ PUT 只提交 { scope }（不带单价等无关字段）', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-24')).toBeInTheDocument())

    await userEvent.selectOptions(scopeControl('op-v54-24'), 'position')

    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-24', { scope: 'position' }),
    )
    // 只提交 scope（部分更新口径）：顺手带上 unit_price 会把并发改动覆盖回去
    expect(mockUpdateOperation.mock.calls[0][1]).toEqual({ scope: 'position' })
    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalled())
  })

  it('判据 4d：可双向改 —— 部位级改成套级 ⇒ PUT { scope: "set" }', async () => {
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-01')).toBeInTheDocument())

    await userEvent.selectOptions(scopeControl('op-v54-01'), 'set')

    await waitFor(() =>
      expect(mockUpdateOperation).toHaveBeenCalledWith('op-v54-01', { scope: 'set' }),
    )
  })

  it('判据 4e：写失败不假装成功（报错且不弹成功 toast）', async () => {
    mockUpdateOperation.mockRejectedValueOnce(new Error('boom'))
    render(<ProcessConfigPage />)
    await waitFor(() => expect(screen.getByTestId('operation-row-op-v54-24')).toBeInTheDocument())

    await userEvent.selectOptions(scopeControl('op-v54-24'), 'position')

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalled())
    expect(vi.mocked(toast.success)).not.toHaveBeenCalled()
  })
})
