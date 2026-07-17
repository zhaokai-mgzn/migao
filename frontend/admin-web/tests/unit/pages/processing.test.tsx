import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock APIs
const mockGetProcessingItems = vi.fn()
const mockGetProcessingCategories = vi.fn()
const mockGetCategories = vi.fn()

vi.mock('@/lib/api', () => ({
  processingItemApi: {
    getProcessingItems: (...args: any[]) => mockGetProcessingItems(...args),
    createProcessingItem: vi.fn(),
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
  { id: '1', name: '打孔加工', unitPrice: 5, pricingMethod: 'per_piece', applicableProductCategories: [] },
  { id: '2', name: '挂钩加工', unitPrice: 3, pricingMethod: 'per_piece', applicableProductCategories: [] },
]

const mockCategories = [{ id: 'cat1', name: '通用加工' }]

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
      data: { data: [] },
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
      expect(screen.getByText('添加加工项')).toBeInTheDocument()
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
      expect(screen.getByText('添加加工项')).toBeInTheDocument()
    })
    await user.click(screen.getByText('添加加工项'))
    await waitFor(() => {
      expect(screen.getByText('新增加工项')).toBeInTheDocument()
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
})
