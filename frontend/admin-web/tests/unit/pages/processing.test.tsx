// case_ids: PP-006
// PP-006（issue #3005 回滚 #2986）：加工项无「每米数量」——计价方式仅 per_meter/per_set/fixed/per_area，
// 表单与列表均无每米数量输入/列，保存 payload 不带 perMeterQuantity
// ⚠️ 2026-09-19（issue #4490 合并）：本文件断言的对象从 `/processing`（旧「加工项管理」页）改为
// **合并后的唯一入口** `/production/processing` 的**第一个 tab「加工项」** —— 加工项半边的能力
// （列表 / 新增 / 编辑 / 删除 / 分类 / 计价方式 / 优惠）一条不少，只是换了页面与归属菜单组。
// 合并本身的判据（菜单结构 / 两个旧路径重定向 / 两个 tab / 切 tab 不丢状态）在
// tests/unit/pages/processing-merged.test.tsx。
// ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：原 `UI-026`（加工项列表展示「适用商品分类」列）
// 断言**已删除** —— `applicable_product_categories` 列与过滤链路随解耦整体退场（V66 迁移 DROP），
// 该列不再渲染，用例对象已不存在（用例 UI-026 亦同步从 .github/cases/ui.yml 删除）。
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock APIs
const mockGetProcessingItems = vi.fn()
const mockGetProcessingCategories = vi.fn()
const mockGetCategories = vi.fn()
const mockCreateProcessingItem = vi.fn()

vi.mock('@/lib/api', () => ({
  processingItemApi: {
    getProcessingItems: (...args: any[]) => mockGetProcessingItems(...args),
    createProcessingItem: (...args: any[]) => mockCreateProcessingItem(...args),
    updateProcessingItem: vi.fn(),
    deleteProcessingItem: vi.fn(),
  },
  processingCategoryApi: {
    getProcessingCategories: (...args: any[]) => mockGetProcessingCategories(...args),
  },
  categoryApi: {
    getCategories: (...args: any[]) => mockGetCategories(...args),
  },
  // issue #4490：合并页同一组件里还有加工费组合半边（本文件不测它，但它在挂载时会拉数据）
  productionApi: {
    getFeeCombinations: vi.fn().mockResolvedValue({ data: { data: { combinations: [] } } }),
    getFeeGaps: vi.fn().mockResolvedValue({ data: { data: { unpriced_combinations: [] } } }),
  },
}))

// issue #4490：合并页用 `?tab=` 支持旧路径直达（Suspense + useSearchParams），测试里给个空参
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Mock UI components
vi.mock('@/components/ui', () => ({
  Modal: ({ open, title, children, footer }: any) =>
    open ? (
      <div data-testid="modal" role="dialog">
        <h2>{title}</h2>
        {children}
        <div data-testid="modal-footer">{footer}</div>
      </div>
    ) : null,
  Button: ({ children, onClick, ...props }: any) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
}))

import ProcessingPage from '@/app/(dashboard)/production/processing/page'

// ⚠️ 2026-09-21（#4882 用户裁定）：**加工项单价 / 加工项计价方式整体退场** —— 列表两列
// （`加工项价格` / `加工项计价方式`）、表格上方价格说明、弹窗两个输入项、以及
// `validate()` 的 unitPrice 三段校验与 pricingMethod 必选校验全部删除；提交 payload 不再带
// `unitPrice` / `pricingMethod`，`unit` 恒为 `'米'`（加工费按米计价，#3005 行业口径）。
// 本文件相应判据已改判为**反向断言 + payload 逐字相等**（旧形态加回来即红）。
const mockItems = [
  { id: '1', name: '打孔加工', unit: '米' },
  { id: '2', name: '挂钩加工', unit: '米' },
  { id: '3', name: '韩式定型', unit: '米' },
]

const mockCategories = [{ id: 'cat1', name: '通用加工' }]

describe('ProcessingPage（issue #4490 合并后：/production/processing 的「加工项」tab）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProcessingItems.mockResolvedValue({
      data: { data: { items: mockItems } },
    })
    mockGetProcessingCategories.mockResolvedValue({
      data: { data: mockCategories },
    })
  })

  it('should render page title', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项管理')).toBeInTheDocument()
    })
  })

  it('should render page description', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText(/加工项是下单时客户可选的加工服务/)).toBeInTheDocument()
    })
  })

  it('should render add processing item button', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '新增加工项' })).toBeInTheDocument()
    })
  })

  it('should display processing items after loading', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('打孔加工')).toBeInTheDocument()
      expect(screen.getByText('挂钩加工')).toBeInTheDocument()
    })
  })

  it('should show empty state when no items', async () => {
    mockGetProcessingItems.mockResolvedValue({
      data: { data: { items: [] } },
    })
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText(/暂无加工项/)).toBeInTheDocument()
    })
  })

  it('should open create form modal when add button clicked', async () => {
    const user = userEvent.setup()
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '新增加工项' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '新增加工项' }))
    await waitFor(() => {
      // 弹窗标题为 "新增加工项"
      const headings = screen.getAllByText('新增加工项')
      expect(headings.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('should render table headers（#4882：价格 / 计价方式两列已退场）', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项名称')).toBeInTheDocument()
      expect(screen.getByText('加工分类')).toBeInTheDocument()
    })
    // 红证：把任一列加回表格即红（旧形态 = 5 列，含「加工项价格」「加工项计价方式」）
    expect(screen.queryByText('加工项价格')).not.toBeInTheDocument()
    expect(screen.queryByText('加工项计价方式')).not.toBeInTheDocument()
    // 表格上方的价格说明句也整体删除
    expect(
      screen.queryByText(/加工项价格是下单时的加工费参考价/)
    ).not.toBeInTheDocument()
  })

  it('should not show applicable product categories column (UI-026 已随 #4371 解耦退场)', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项名称')).toBeInTheDocument()
    })
    // 解耦后该列不再渲染（applicable_product_categories 已从 schema/接口/表单退场）——
    // 反向断言：列标题与「适用所有分类」占位都不应出现，防止旧列被静默加回。
    expect(screen.queryByText('适用商品分类')).not.toBeInTheDocument()
    expect(screen.queryByText('适用所有分类')).not.toBeInTheDocument()
  })

  it('#4882：弹窗无价格 / 计价方式输入项，提交 payload 无 unitPrice/pricingMethod（PP-006 口径延伸）', async () => {
    const user = userEvent.setup()
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '新增加工项' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '新增加工项' }))

    // ① 表单：价格输入项与计价方式下拉整体退场（红证：把控件加回来即红）
    expect(screen.queryByText('加工项价格')).not.toBeInTheDocument()
    expect(screen.queryByText('加工项计价方式')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('请输入价格（0.10 ~ 999.99）')).not.toBeInTheDocument()
    // 计价方式下拉退场 ⇒ 弹窗内只剩「加工分类」与「设置优惠」两个 select
    const dialog = screen.getByRole('dialog')
    expect(dialog.querySelectorAll('select')).toHaveLength(2)

    // ② PP-006 原判据（无「每米数量」输入）仍成立
    expect(screen.queryByPlaceholderText('请输入每米数量（如 6）')).not.toBeInTheDocument()
    expect(screen.queryByText('每米数量（个/米）')).not.toBeInTheDocument()

    // ③ 提交 payload：单价 / 计价方式键整体不落，单位恒为「米」
    await user.type(screen.getByPlaceholderText('请输入加工项名称（最多20个字符）'), '测试打孔')
    await user.click(screen.getByText('保存'))
    await waitFor(() => {
      expect(mockCreateProcessingItem).toHaveBeenCalledTimes(1)
    })
    const payload = mockCreateProcessingItem.mock.calls[0][0]
    expect(payload).toEqual({
      name: '测试打孔',
      categoryId: 'cat1',
      unit: '米',
      status: 'active',
    })
    expect(payload).not.toHaveProperty('unitPrice')
    expect(payload).not.toHaveProperty('pricingMethod')
    expect(payload).not.toHaveProperty('perMeterQuantity')
  })

  it('should not render per meter quantity column in list (PP-006 回滚)', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项名称')).toBeInTheDocument()
    })
    // 列表无「每米数量」列，也无「6 个/米」密度文本
    expect(screen.queryByText('每米数量')).not.toBeInTheDocument()
    expect(screen.queryByText('6 个/米')).not.toBeInTheDocument()
    // #4882：计价方式文案整体退场（旧形态下这两句分别由两列渲染）
    expect(screen.queryByText(/按购买米数计价/)).not.toBeInTheDocument()
    expect(screen.queryByText(/按套计价/)).not.toBeInTheDocument()
  })
})
