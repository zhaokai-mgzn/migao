// case_ids: UI-026, PP-006
// UI-026（issue #2964）：加工项列表展示「适用商品分类」列——applicableProductCategories ID→名称映射，空=「适用所有分类」
// PP-006（issue #3005 回滚 #2986）：加工项无「每米数量」——计价方式仅 per_meter/per_set/fixed/per_area，
// 表单与列表均无每米数量输入/列，保存 payload 不带 perMeterQuantity
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
    calculatePrice: vi.fn(),
  },
  processingCategoryApi: {
    getProcessingCategories: (...args: any[]) => mockGetProcessingCategories(...args),
  },
  categoryApi: {
    getCategories: (...args: any[]) => mockGetCategories(...args),
  },
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

import ProcessingPage from '@/app/(dashboard)/processing/page'

const mockItems = [
  {
    id: '1',
    name: '打孔加工',
    unitPrice: 5,
    pricingMethod: 'per_meter',
    applicableProductCategories: ['pc1'],
  },
  { id: '2', name: '挂钩加工', unitPrice: 3, pricingMethod: 'per_set', applicableProductCategories: [] },
  { id: '3', name: '韩式定型', unitPrice: 8, pricingMethod: 'per_meter', applicableProductCategories: ['pc2'] },
]

const mockCategories = [{ id: 'cat1', name: '通用加工' }]

// 商品分类树（适用商品分类列的 ID→名称 映射来源）
const mockProductCategories = [
  { id: 'pc1', name: '窗帘', children: [] },
  { id: 'pc2', name: '纱帘', children: [] },
]

describe('ProcessingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProcessingItems.mockResolvedValue({
      data: { data: { items: mockItems } },
    })
    mockGetProcessingCategories.mockResolvedValue({
      data: { data: mockCategories },
    })
    mockGetCategories.mockResolvedValue({
      data: { data: mockProductCategories },
    })
  })

  it('should render page title', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项配置')).toBeInTheDocument()
    })
  })

  it('should render page description', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText(/加工项是指为特定订单定制的产品修改服务/)).toBeInTheDocument()
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

  it('should render table headers', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项名称')).toBeInTheDocument()
      expect(screen.getByText('加工项价格')).toBeInTheDocument()
      expect(screen.getByText('加工项计价方式')).toBeInTheDocument()
    })
  })

  it('should show applicable product categories column (UI-026)', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      // 表头新增「适用商品分类」列
      expect(screen.getByText('适用商品分类')).toBeInTheDocument()
    })
    await waitFor(() => {
      // ID→名称 映射：打孔加工 适用分类「窗帘」
      expect(screen.getByText('窗帘')).toBeInTheDocument()
      // 未配置适用分类（空数组）= 适用所有分类
      expect(screen.getByText('适用所有分类')).toBeInTheDocument()
    })
  })

  it('should not show per meter quantity input for any pricing method (PP-006 回滚)', async () => {
    const user = userEvent.setup()
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '新增加工项' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '新增加工项' }))

    // 计价方式选项无 per_piece，仅 per_meter/per_set/fixed/per_area
    const methodSelect = screen
      .getAllByText('加工项计价方式')
      .map((el) => el.closest('div')!.querySelector('select'))
      .find(Boolean) as HTMLSelectElement
    const optionValues = Array.from(methodSelect.querySelectorAll('option')).map((o) => o.value)
    expect(optionValues).toContain('per_meter')
    expect(optionValues).toContain('per_set')
    expect(optionValues).toContain('fixed')
    expect(optionValues).toContain('per_area')
    expect(optionValues).not.toContain('per_piece')

    // 任意计价方式下都不出现「每米数量」输入
    await user.selectOptions(methodSelect, 'per_meter')
    expect(screen.queryByPlaceholderText('请输入每米数量（如 6）')).not.toBeInTheDocument()
    expect(screen.queryByText('每米数量（个/米）')).not.toBeInTheDocument()
    await user.selectOptions(methodSelect, 'per_set')
    expect(screen.queryByPlaceholderText('请输入每米数量（如 6）')).not.toBeInTheDocument()

    // 填写表单并保存 → payload 不带 perMeterQuantity
    await user.type(screen.getByPlaceholderText('请输入加工项名称（最多20个字符）'), '测试打孔')
    await user.type(screen.getByPlaceholderText('请输入价格（0.10 ~ 999.99）'), '5')
    await user.click(screen.getByText('保存'))
    await waitFor(() => {
      expect(mockCreateProcessingItem).toHaveBeenCalledTimes(1)
    })
    const payload = mockCreateProcessingItem.mock.calls[0][0]
    expect(payload.pricingMethod).toBe('per_set')
    expect(payload.perMeterQuantity).toBeUndefined()
  })

  it('should not render per meter quantity column in list (PP-006 回滚)', async () => {
    render(<ProcessingPage />)
    await waitFor(() => {
      expect(screen.getByText('加工项名称')).toBeInTheDocument()
    })
    // 列表无「每米数量」列，也无「6 个/米」密度文本
    expect(screen.queryByText('每米数量')).not.toBeInTheDocument()
    expect(screen.queryByText('6 个/米')).not.toBeInTheDocument()
    // 计价方式文本仍在（per_meter / per_set）
    expect(screen.getAllByText(/按购买米数计价/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/按套计价/)).toBeInTheDocument()
  })
})
