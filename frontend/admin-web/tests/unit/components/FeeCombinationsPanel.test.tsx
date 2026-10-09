// case_ids: UI-054
/**
 * `FeeCombinationsPanel`（issue #6585 从 `ProcessingBoard` 拆出的**加工费组合面板**）判据两条。
 *
 * 与 `ProcessingItemsPanel.test.tsx` 同源的两个**新**判据（拆分前不可能成立）：
 * ① 单独 `render` 即自取数据 —— 三个读面自己发：组合（`productionApi.getFeeCombinations`）、
 *    未定价缺口（`getFeeGaps`）、勾选源目录（`processingItemApi.getProcessingItems`）；
 * ② `embedded` 只关标题那一层，testid 判的功能面（组合表 / 缺口区 / 新建入口）一个不少。
 *
 * ⚠️ 替身必须**显式具名导出**（不是 Proxy 兜底）：ESM mock 兜不住 Proxy ⇒ 组件会在「一切报错」状态下
 * 渲染，那时断言「面板发起了自己的请求」会变成弱断言（任何调用都成立）。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const mockGetFeeCombinations = vi.fn()
const mockGetFeeGaps = vi.fn()
const mockGetProcessingItems = vi.fn()

vi.mock('@/lib/api', () => ({
  processingItemApi: {
    getProcessingItems: (...args: unknown[]) => mockGetProcessingItems(...args),
    createProcessingItem: vi.fn(),
    updateProcessingItem: vi.fn(),
    deleteProcessingItem: vi.fn(),
  },
  productionApi: {
    getFeeCombinations: (...args: unknown[]) => mockGetFeeCombinations(...args),
    getFeeGaps: (...args: unknown[]) => mockGetFeeGaps(...args),
    createFeeCombination: vi.fn(),
    updateFeeCombination: vi.fn(),
    disableFeeCombination: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import FeeCombinationsPanel from '@/components/production-config/FeeCombinationsPanel'

const ok = (data: unknown) => ({ data: { success: true, data } })

const COMBINATIONS = {
  total: 1,
  combinations: [
    { id: 'fc-1', composition_key: '打孔+韩褶', items: ['韩褶', '打孔'], unit_price: 12, unit: '元/米', status: 'active', source: '实证' },
  ],
}

const GAPS = {
  unpriced_combinations: [
    { composition_key: '定型+韩褶', items: ['定型', '韩褶'], order_count: 3, note: '' },
  ],
  unpriced_combination_total: 1,
}

const ITEMS = {
  total: 2,
  items: [
    { id: 'pi-1', name: '韩褶', categoryId: 'cat-1', categoryName: '窗帘加工', unit: '米', status: 'active' },
    { id: 'pi-2', name: '打孔', categoryId: 'cat-1', categoryName: '窗帘加工', unit: '米', status: 'active' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetFeeCombinations.mockResolvedValue(ok(COMBINATIONS))
  mockGetFeeGaps.mockResolvedValue(ok(GAPS))
  mockGetProcessingItems.mockResolvedValue(ok(ITEMS))
})

describe('FeeCombinationsPanel —— 自包含挂载（issue #6585）', () => {
  it('单独 render 即发起本面板三个读面，并把组合行 / 单价 / 来源 / 缺口计数渲染出来', async () => {
    render(<FeeCombinationsPanel />)

    // ① 自包含的**唯一**判据：三个读请求都由面板自己发出
    await waitFor(() => expect(mockGetFeeCombinations).toHaveBeenCalledTimes(1))
    expect(mockGetFeeGaps).toHaveBeenCalledTimes(1)
    expect(mockGetProcessingItems).toHaveBeenCalledWith({ page: 1, size: 999 })

    // ② 反 placeholder：真实数据行（组合 = 选配组合 + 元/米单价 + 来源徽标）
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('1'))
    expect(screen.getByTestId('fee-combination-items-fc-1')).toHaveTextContent('韩褶 + 打孔')
    expect(screen.getByTestId('fee-combination-price-fc-1')).toHaveTextContent('¥12.00')
    expect(screen.getByTestId('fee-combination-fc-1')).toHaveTextContent('实证')
    // 缺口常驻面 = 一行计数（#6532：明细默认折叠）
    expect(screen.getByTestId('fee-gaps-total')).toHaveTextContent('1')
  })
})

describe('FeeCombinationsPanel —— embedded 形态（issue #6585 / #6580）', () => {
  it('区块标题「加工费组合」不渲染，但功能面（testid 判）一个不少', async () => {
    render(<FeeCombinationsPanel embedded />)

    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('1'))

    // ① 自己那一层区块标题**不渲染**（域面板已给「加工项与加工费」标题与一句话）
    expect(screen.queryByTestId('fee-combinations-title')).toBeNull()

    // ② 功能面照旧：组合表 / 新建入口 / 未定价缺口区都在
    expect(screen.getByTestId('fee-combinations')).toBeInTheDocument()
    expect(screen.getByTestId('fee-combination-new')).toBeInTheDocument()
    expect(screen.getByTestId('fee-gaps')).toBeInTheDocument()
    expect(screen.getByTestId('fee-combination-fc-1')).toBeInTheDocument()
  })

  it('对照：独立形态（默认）标题在 —— 两条判据互斥，不是恒真断言', async () => {
    render(<FeeCombinationsPanel />)

    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('1'))
    expect(screen.getByTestId('fee-combinations-title')).toHaveTextContent('加工费组合')
  })
})
