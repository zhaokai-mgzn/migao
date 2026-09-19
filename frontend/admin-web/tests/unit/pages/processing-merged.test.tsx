// case_ids: PP-006, PG-040
// PP-006（加工项目录 CRUD / 计价方式）+ PG-040（加工费**组合**定价）在 issue #4490 合并后的**单页形态**：
// 「加工项管理」(/processing，原**商品管理**组) 与「加工费管理」(/production/processing-fees) 合并为
// 单一菜单入口「加工项与加工费」/production/processing（**生产管理**组）。
//
// 本文件钉的是**合并本身的判据**（两半能力各自的断言在 processing.test.tsx / processing-fees.test.tsx）：
// ① 菜单结构：生产管理组含合并项且路径/权限码正确；**商品管理组不再有「加工项管理」**；
//    全站不再有指向 /processing 或 /production/processing-fees 的菜单项；
// ② 两个旧路径都**重定向**到新入口（旧深链不 404）；加工费旧路径带 `?tab=fees` 直达第二栏；
// ③ 页面**两个 tab**（加工项 / 加工费组合），默认落在「加工项」，切换后内容**互斥**（不平铺）；
// ④ **切 tab 不丢状态**（两栏 state 挂在同一组件上：加工项表单草稿 / 加工费就地改价草稿）；
// ⑤ `?tab=fees` 直达（后端未定价提示里的旧链接走这条）。
// 反 placeholder：断言落**真实数据行**、**重定向目标**与**互斥的 DOM 形态**，不断言「页面存在」。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetProcessingItems = vi.fn()
const mockGetProcessingCategories = vi.fn()
const mockGetFeeCombinations = vi.fn()
const mockGetFeeGaps = vi.fn()
const mockRedirect = vi.fn()
/** `?tab=` 直达（默认无参 ⇒ 落在「加工项」） */
let mockSearch = ''

vi.mock('@/lib/api', () => ({
  processingItemApi: {
    getProcessingItems: (...args: unknown[]) => mockGetProcessingItems(...args),
    createProcessingItem: vi.fn(),
    updateProcessingItem: vi.fn(),
    deleteProcessingItem: vi.fn(),
    calculatePrice: vi.fn(),
  },
  processingCategoryApi: {
    getProcessingCategories: (...args: unknown[]) => mockGetProcessingCategories(...args),
    createProcessingCategory: vi.fn(),
  },
  productionApi: {
    getFeeCombinations: (...args: unknown[]) => mockGetFeeCombinations(...args),
    getFeeGaps: (...args: unknown[]) => mockGetFeeGaps(...args),
    createFeeCombination: vi.fn(),
    updateFeeCombination: vi.fn(),
    disableFeeCombination: vi.fn(),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('next/navigation', () => ({
  redirect: (...args: unknown[]) => mockRedirect(...args),
  useSearchParams: () => new URLSearchParams(mockSearch),
}))

import ProcessingPage from '@/app/(dashboard)/production/processing/page'
import ProcessingRedirectPage from '@/app/(dashboard)/processing/page'
import ProcessingFeesRedirectPage from '@/app/(dashboard)/production/processing-fees/page'
import { menuGroups } from '@/config/menu'

const ok = (data: unknown) => ({ data: { success: true, data } })

const ITEMS = {
  total: 2,
  items: [
    { id: 'pi-1', name: '韩褶', categoryId: 'cat-1', categoryName: '窗帘加工', pricingMethod: 'per_meter', unitPrice: 1.2, unit: '米', status: 'active' },
    { id: 'pi-2', name: '打孔', categoryId: 'cat-1', categoryName: '窗帘加工', pricingMethod: 'per_meter', unitPrice: 8, unit: '米', status: 'active' },
  ],
}

const COMBINATIONS = {
  total: 1,
  combinations: [
    { id: 'fc-1', composition_key: '打孔+韩褶', items: ['韩褶', '打孔'], unit_price: 12, unit: '元/米', status: 'active', source: '实证' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockSearch = ''
  mockGetProcessingItems.mockResolvedValue(ok(ITEMS))
  mockGetProcessingCategories.mockResolvedValue(ok([{ id: 'cat-1', name: '窗帘加工' }]))
  mockGetFeeCombinations.mockResolvedValue(ok(COMBINATIONS))
  mockGetFeeGaps.mockResolvedValue(ok({ unpriced_combinations: [], unpriced_combination_total: 0 }))
})

const productionGroup = () => menuGroups.find((g) => g.key === 'production')
const productGroup = () => menuGroups.find((g) => g.key === 'product-center')

// ────────────────────────── ① 菜单结构（侧边栏 IA） ──────────────────────────

describe('菜单结构（issue #4490：合并进生产管理组，商品管理组不再有加工项管理）', () => {
  it('生产管理组含合并项「加工项与加工费」→ /production/processing（权限码 processing:manage）', () => {
    const entry = productionGroup()?.children.find((c) => c.key === 'production-processing')
    expect(entry).toBeDefined()
    expect(entry!.name).toBe('加工项与加工费')
    expect(entry!.path).toBe('/production/processing')
    expect(entry!.permissionCode).toBe('processing:manage')
    // 与「工艺配置」「计件工资」同组（用户裁定：放到生产管理菜单下）
    const paths = productionGroup()!.children.map((c) => c.path)
    expect(paths).toContain('/production/routings')
    expect(paths).toContain('/production/piecework')
  })

  it('商品管理组不再有「加工项管理」；全站不再有指向两个旧路径的菜单项', () => {
    expect(productGroup()?.children.map((c) => c.name)).toEqual(['商品列表'])
    const allPaths = menuGroups.flatMap((g) => g.children.map((c) => c.path))
    expect(allPaths).not.toContain('/processing')
    expect(allPaths).not.toContain('/production/processing-fees')
    const allNames = menuGroups.flatMap((g) => g.children.map((c) => c.name))
    expect(allNames).not.toContain('加工项管理')
    expect(allNames).not.toContain('加工费管理')
  })

  it('生产管理组四项权限码统一 processing:manage（组内一致，无分叉）', () => {
    const codes = productionGroup()!.children.map((c) => c.permissionCode)
    expect(codes).toEqual(['processing:manage', 'processing:manage', 'processing:manage', 'processing:manage'])
  })
})

// ────────────────────────── ② 旧路径重定向 ──────────────────────────

describe('两个旧路径都重定向到新入口（旧深链不 404）', () => {
  it('旧「加工项管理」/processing → /production/processing', () => {
    ProcessingRedirectPage()
    expect(mockRedirect).toHaveBeenCalledTimes(1)
    expect(mockRedirect).toHaveBeenCalledWith('/production/processing')
  })

  it('旧「加工费管理」/production/processing-fees → /production/processing?tab=fees（直达定价面）', () => {
    ProcessingFeesRedirectPage()
    expect(mockRedirect).toHaveBeenCalledTimes(1)
    expect(mockRedirect).toHaveBeenCalledWith('/production/processing?tab=fees')
  })
})

// ────────────────────────── ③④⑤ 两个 tab ──────────────────────────

describe('合并页 /production/processing（两个 tab，不平铺）', () => {
  it('两个 tab 存在且默认落在「加工项」；切换后内容互斥（不是两个域堆在一屏）', async () => {
    render(<ProcessingPage />)
    await waitFor(() => expect(screen.getByTestId('processing-tabs')).toBeInTheDocument())

    const itemsTab = screen.getByTestId('processing-tab-items')
    const feesTab = screen.getByTestId('processing-tab-fees')
    // tab 标题是**用户能一眼懂的业务名**（不是技术名）
    expect(itemsTab).toHaveTextContent('加工项')
    expect(feesTab).toHaveTextContent('加工费组合')
    expect(itemsTab).toHaveAttribute('data-state', 'active')
    expect(feesTab).toHaveAttribute('data-state', 'inactive')

    // 默认：加工项列表在、「加工费组合」面不在
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))
    expect(screen.getByTestId('processing-item-pi-1')).toHaveTextContent('韩褶')
    expect(screen.queryByTestId('fee-combinations')).not.toBeInTheDocument()
    expect(screen.queryByTestId('fee-gaps')).not.toBeInTheDocument()

    await userEvent.click(feesTab)
    expect(feesTab).toHaveAttribute('data-state', 'active')
    expect(screen.queryByTestId('processing-items')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('1'))
    expect(screen.getByTestId('fee-combination-fc-1')).toHaveTextContent('¥12.00')
    // 未定价缺口仍在（#4386 交付物不退化）
    expect(screen.getByTestId('fee-gaps')).toBeInTheDocument()
  })

  it('切 tab **不丢状态**：加工项表单草稿与加工费就地改价草稿，切走再切回都还在', async () => {
    render(<ProcessingPage />)
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))

    // ① 加工项：打开新增弹窗并填名称
    await userEvent.click(screen.getByTestId('processing-item-new'))
    const nameInput = screen.getByPlaceholderText('请输入加工项名称（最多20个字符）')
    await userEvent.type(nameInput, '定型')

    // ② 切到加工费组合：进入 fc-1 的就地改价
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    await waitFor(() => expect(screen.getByTestId('fee-combination-fc-1')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('fee-combination-edit-fc-1'))
    const priceInput = screen.getByTestId('fee-combination-edit-price-fc-1')
    await userEvent.clear(priceInput)
    await userEvent.type(priceInput, '13.5')

    // ③ 切回加工项：表单草稿仍在
    await userEvent.click(screen.getByTestId('processing-tab-items'))
    expect(screen.getByPlaceholderText('请输入加工项名称（最多20个字符）')).toHaveValue('定型')

    // ④ 再切回加工费组合：改价草稿仍在（两栏 state 挂在同一组件上，不随 tab 重置）
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    expect(screen.getByTestId('fee-combination-edit-price-fc-1')).toHaveValue('13.5')
  })

  it('`?tab=fees` 直达「加工费组合」（旧 /production/processing-fees 的深链意图不丢）', async () => {
    mockSearch = 'tab=fees'
    render(<ProcessingPage />)

    await waitFor(() => expect(screen.getByTestId('processing-tab-fees')).toHaveAttribute('data-state', 'active'))
    expect(screen.getByTestId('fee-combinations')).toBeInTheDocument()
    expect(screen.queryByTestId('processing-items')).not.toBeInTheDocument()
  })

  it('加工项加载失败：只在「加工项」tab 给可读提示 + 重试，另一栏照常渲染（不整页白屏）', async () => {
    mockGetProcessingItems.mockRejectedValueOnce(new Error('500'))
    render(<ProcessingPage />)

    await waitFor(() => expect(screen.getByTestId('processing-items-error')).toHaveTextContent('加工项加载失败'))
    // 加工费半边不受影响（各拉各的，一条失败不吞整页）
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    await waitFor(() => expect(screen.getByTestId('fee-combinations-total')).toHaveTextContent('1'))
    // 勾选源与「加工项」tab 是同一份数据 ⇒ 加载失败**不得**说成「目录为空」
    // （说成空会让商家去建一个其实已存在的加工项 —— 合并后新引入的形态）
    await userEvent.click(screen.getByTestId('fee-combination-new'))
    expect(screen.getByTestId('fee-combination-catalog-empty')).toHaveTextContent('加工项目录加载失败')
    await userEvent.click(screen.getByRole('button', { name: '取消' }))

    // 重试后渲染出真实数据（错误态消失）
    await userEvent.click(screen.getByTestId('processing-tab-items'))
    await userEvent.click(screen.getByTestId('processing-items-retry'))
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))
    expect(screen.queryByTestId('processing-items-error')).not.toBeInTheDocument()
    expect(screen.getByTestId('processing-item-pi-2')).toHaveTextContent('打孔')
  })

  it('两半能力**同页都在**：加工项 CRUD 入口 + 加工分类抽屉 + 加工费组合定价与缺口', async () => {
    render(<ProcessingPage />)
    await waitFor(() => expect(screen.getByTestId('processing-items-total')).toHaveTextContent('2'))

    // 加工项半边：新增入口 + 行内编辑/删除（CRUD）+ 分类抽屉
    expect(screen.getByTestId('processing-item-new')).toHaveTextContent('新增加工项')
    const row = screen.getByTestId('processing-item-pi-1')
    expect(within(row).getByText('编辑')).toBeInTheDocument()
    expect(within(row).getByText('删除')).toBeInTheDocument()
    // 加工分类（次区走抽屉，不占主列表）
    expect(screen.queryByTestId('processing-categories-list')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('processing-categories-open'))
    expect(await screen.findByTestId('processing-categories-list')).toHaveTextContent('窗帘加工')

    // 加工费半边：新建组合入口 + 缺口区（辅助告警）
    await userEvent.click(screen.getByTestId('processing-tab-fees'))
    expect(screen.getByTestId('fee-combination-new')).toHaveTextContent('新建组合')
    expect(screen.getByTestId('fee-gaps-total')).toBeInTheDocument()
  })
})
