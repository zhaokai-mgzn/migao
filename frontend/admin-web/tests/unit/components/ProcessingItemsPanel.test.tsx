// case_ids: UI-054
/**
 * `ProcessingItemsPanel`（issue #6585 从 `ProcessingBoard` 拆出的**加工项面板**）判据两条。
 *
 * 为什么单独判这两个（而不是重跑 `production-board.test.tsx` 的数据面）：
 * #6585 的验收面 = 「**面板能单独挂载**」与「`embedded` 形态下**区块标题不渲染、功能面照旧**」——
 * 拆分前这两件事不可能成立（功能体长在 board 的 `tab === 'items'` 分支里），所以它们是**新判据**：
 * ① 单独 `render` 即自取数据（**不再**依赖 board 先拉一次喂进来）；
 * ② `embedded` 只关标题那一层，testid 判的功能面一个不少（`embedded` 不许顺手砍功能）。
 *
 * ⚠️ 替身必须**显式具名导出**（不是 Proxy 兜底）：ESM mock 兜不住 Proxy ⇒ 组件会在「一切报错」状态下
 * 渲染，那时断言「面板发起了自己的请求」会变成弱断言（任何调用都成立）。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const mockGetProcessingItems = vi.fn()
const mockGetProcessingCategories = vi.fn()

vi.mock('@/lib/api', () => ({
  processingItemApi: {
    getProcessingItems: (...args: unknown[]) => mockGetProcessingItems(...args),
    createProcessingItem: vi.fn(),
    updateProcessingItem: vi.fn(),
    deleteProcessingItem: vi.fn(),
  },
  processingCategoryApi: {
    getProcessingCategories: (...args: unknown[]) => mockGetProcessingCategories(...args),
    createProcessingCategory: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import ProcessingItemsPanel from '@/components/production-config/ProcessingItemsPanel'

const ok = (data: unknown) => ({ data: { success: true, data } })

const ITEMS = {
  total: 2,
  items: [
    { id: 'pi-1', name: '韩褶', categoryId: 'cat-1', categoryName: '窗帘加工', unit: '米', status: 'active' },
    { id: 'pi-2', name: '打孔', categoryId: 'cat-1', categoryName: '窗帘加工', unit: '米', status: 'active' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetProcessingItems.mockResolvedValue(ok(ITEMS))
  mockGetProcessingCategories.mockResolvedValue(ok([{ id: 'cat-1', name: '窗帘加工' }]))
})

describe('ProcessingItemsPanel —— 自包含挂载（issue #6585）', () => {
  it('单独 render 即发起本面板的读面（加工项 + 加工分类各一次），并把真实数据行渲染出来', async () => {
    render(<ProcessingItemsPanel />)

    // ① 自包含的**唯一**判据：面板自己发出了两个读请求（没有外层喂 props）
    await waitFor(() => expect(mockGetProcessingItems).toHaveBeenCalledTimes(1))
    expect(mockGetProcessingItems).toHaveBeenCalledWith({ page: 1, size: 999 })
    expect(mockGetProcessingCategories).toHaveBeenCalledTimes(1)

    // ② 反 placeholder：落到真实数据行 + 计数（不是「面板存在」）
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('processing-item-pi-1')).toHaveTextContent('韩褶')
    expect(screen.getByTestId('processing-item-pi-1')).toHaveTextContent('窗帘加工')
    expect(screen.getByTestId('processing-item-pi-2')).toHaveTextContent('打孔')
  })
})

describe('ProcessingItemsPanel —— embedded 形态（issue #6585 / #6580）', () => {
  it('区块标题「加工项」不渲染，但功能面（testid 判）一个不少', async () => {
    render(<ProcessingItemsPanel embedded />)

    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))

    // ① 自己那一层区块标题**不渲染**（域面板已给「加工项与加工费」标题与一句话）
    expect(screen.queryByTestId('processing-items-title')).toBeNull()

    // ② 功能面照旧：列表 / 新增 / 分类抽屉入口都在
    expect(screen.getByTestId('processing-items')).toBeInTheDocument()
    expect(screen.getByTestId('processing-item-new')).toBeInTheDocument()
    expect(screen.getByTestId('processing-categories-open')).toBeInTheDocument()
    expect(screen.getByTestId('processing-item-pi-1')).toBeInTheDocument()
  })

  it('对照：独立形态（默认）标题在 —— 两条判据互斥，不是恒真断言', async () => {
    render(<ProcessingItemsPanel />)

    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('processing-items-title')).toHaveTextContent('加工项')
  })
})
