// case_ids: UI-054
/**
 * `OperationPricePanel` 的**两种挂载形态**判据（issue #6585 P1）。
 *
 * ① **自包含**：单独 `render(<OperationPricePanel />)` 即发起它自己的读面 —— 面板不依赖父组件传数据
 *    （这是「域可独立挂载」的机制本身）。
 * ② **embedded 形态**：本层区块标题不渲染，但关键功能面（**用 testid 判**，不靠文案）仍在。
 *
 * ⚠️ mock 一律**显式具名导出**（不用 Proxy 兜底）：vitest 的 ESM mock 兜不住 Proxy，
 * 兜不住会让组件在「一切报错」的状态下渲染，那种断言是弱断言。
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
        ok({
          total: 1,
          groups: [
            {
              group: '裁剪',
              operations: [{ id: 'op-1', name: '精裁', group: '裁剪', unit: '米', qty_rule_missing: false }],
            },
          ],
        }),
      ),
      getOperationPositions: vi.fn(() =>
        ok([
          { id: 'cell-1', operation: '精裁', position: '通用', unit_price: 2.5, variant_operation_id: 'op-1' },
        ]),
      ),
      getRouteRules: f(),
      getRouteRuleOptions: vi.fn(() => ok({ crafts: [], processing_items: [], positions: [] })),
      updateOperationPosition: f(),
      updateOperation: f(),
      deleteOperation: f(),
      createOperation: f(),
      createOptionRule: f(),
      deleteRouteRule: f(),
      updateRuleCustomerUnitPrice: f(),
    },
    cuttingHeightApi: { get: f(), update: f(), preview: f() },
  }
})
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { OperationPricePanel } from '@/components/production-config/OperationPricePanel'
import { productionApi } from '@/lib/api'

describe('OperationPricePanel（工序与部位单价域，issue #6585）', () => {
  it('① 自包含：单独挂载即发起自己的读面，并渲染价目矩阵', async () => {
    render(<OperationPricePanel />)
    // 它自己发起的读面（**不靠父组件传数据**）
    await waitFor(() => expect(productionApi.getOperationsCatalog).toHaveBeenCalled())
    expect(productionApi.getOperationPositions).toHaveBeenCalled()
    expect(productionApi.getRouteRules).toHaveBeenCalled()
    // 关键功能面在（用 testid 判）
    expect(await screen.findByTestId('operation-price-matrix')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument())
    expect(screen.getByTestId('operation-price-matrix-total')).toHaveTextContent('1')
    expect(screen.getByTestId('operations-search')).toBeInTheDocument()
    expect(screen.getByTestId('routings-new-operation')).toBeInTheDocument()
  })

  it('② embedded：区块标题不渲染，但矩阵 / 搜索 / 新增入口仍在', async () => {
    render(<OperationPricePanel embedded />)
    await waitFor(() => expect(screen.getByTestId('operation-price-matrix')).toBeInTheDocument())
    // 本层面板标题不渲染（域标题由指挥台给）
    expect(screen.queryByText('工序库 · 计件单价')).toBeNull()
    // 关键功能面仍在
    expect(screen.getByTestId('operations-search')).toBeInTheDocument()
    expect(screen.getByTestId('routings-new-operation')).toBeInTheDocument()
    expect(screen.getByTestId('matrix-row-精裁')).toBeInTheDocument()
  })
})
