// case_ids: UI-054
/**
 * `RoutingsPanel` 的**两种挂载形态**判据（issue #6585 P1）。
 *
 * ① **自包含**：单独 `render(<RoutingsPanel />)` 即发起它自己的读面（路线 + 规则 + 取值域）。
 * ② **embedded 形态**：本层区块标题不渲染，但关键功能面（**用 testid 判**）仍在。
 *
 * ⚠️ mock 一律**显式具名导出**（不用 Proxy 兜底）。
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const ok = (data: unknown) => Promise.resolve({ data: { success: true, data } })

vi.mock('@/lib/api', () => {
  const f = () => vi.fn(() => ok([]))
  return {
    productionApi: {
      getRoutings: vi.fn(() =>
        ok({ total: 1, routings: [{ id: 7, name: '窗帘工序路线（默认）', is_default: true, mainline: ['精裁'] }] }),
      ),
      getOperationsCatalog: vi.fn(() =>
        ok({ total: 1, groups: [{ group: '裁剪', operations: [{ id: 'op-1', name: '精裁', group: '裁剪', unit: '米' }] }] }),
      ),
      getOperationPositions: vi.fn(() =>
        ok([{ id: 'cell-1', operation: '精裁', position: '通用', unit_price: 2.5, variant_operation_id: 'op-1' }]),
      ),
      getRouteRules: f(),
      getRouteRuleOptions: vi.fn(() => ok({ crafts: [], processing_items: [], positions: [] })),
      updateRouting: f(),
      createRouting: f(),
      deleteRouting: f(),
      createOptionRule: f(),
      deleteRouteRule: f(),
      updateRuleCustomerUnitPrice: f(),
    },
    cuttingHeightApi: { get: f(), update: f(), preview: f() },
  }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { RoutingsPanel } from '@/components/production-config/RoutingsPanel'
import { productionApi } from '@/lib/api'

describe('RoutingsPanel（工艺路线域，issue #6585）', () => {
  it('① 自包含：单独挂载即发起自己的读面，并渲染路线列表', async () => {
    render(<RoutingsPanel />)
    await waitFor(() => expect(productionApi.getRoutings).toHaveBeenCalled())
    expect(productionApi.getRouteRules).toHaveBeenCalled()
    expect(productionApi.getRouteRuleOptions).toHaveBeenCalled()
    // 关键功能面在（用 testid 判）
    expect(await screen.findByTestId('routings-list')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('routing-7')).toBeInTheDocument())
    expect(screen.getByTestId('routing-name-7')).toHaveTextContent('窗帘工序路线（默认）')
    expect(screen.getByTestId('routing-default-7')).toBeInTheDocument()
    expect(screen.getByTestId('routings-new-route')).toBeInTheDocument()
  })

  it('② embedded：区块标题不渲染，但路线列表 / 新建入口仍在', async () => {
    render(<RoutingsPanel embedded />)
    await waitFor(() => expect(screen.getByTestId('routings-list')).toBeInTheDocument())
    // 本层**面板标题**不渲染（域标题由指挥台给）；路线列表自己的区块标题「工艺路线」仍在
    expect(screen.queryByText('工艺路线（路线与规则）')).toBeNull()
    expect(screen.getByTestId('routings-new-route')).toBeInTheDocument()
    expect(screen.getByTestId('routing-7')).toBeInTheDocument()
  })
})
