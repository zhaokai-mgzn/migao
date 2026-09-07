// case_ids: OR-009
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock API
const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProductProcessingItems = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    createOrder: (...args: any[]) => mockCreateOrder(...args),
  },
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    getProduct: (...args: any[]) => mockGetProduct(...args),
    getProductProcessingItems: (...args: any[]) => mockGetProductProcessingItems(...args),
  },
}))

// Mock useOrderAmounts hook
vi.mock('@/hooks/useOrderAmounts', () => ({
  useOrderAmounts: (total: number) => ({
    discountAmount: '0.00',
    setDiscountAmount: vi.fn(),
    actualAmount: total.toFixed(2),
    setActualAmount: vi.fn(),
    actualTouched: false,
  }),
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock sonner (re-mock for file-level)
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

describe('NewOrderPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [] } },
    })
  })

  it('should render page title', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('新增订单')).toBeInTheDocument()
    })
  })

  it('should render product section header', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
  })

  it('should render customer info section header', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('收货信息')).toBeInTheDocument()
    })
  })

  it('should render fee detail section header', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('费用明细')).toBeInTheDocument()
    })
  })

  it('should render submit button', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('提交订单')).toBeInTheDocument()
    })
  })

  it('should render cancel button', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('取消')).toBeInTheDocument()
    })
  })

  it('should render customer name input', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByPlaceholderText('请输入收货人姓名')).toBeInTheDocument()
    })
  })

  it('should show amount summary rows', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('商品小计')).toBeInTheDocument()
      expect(screen.getByText('加工费')).toBeInTheDocument()
      expect(screen.getByText('订单金额')).toBeInTheDocument()
    })
  })

  it('should show discount and actual amount fields', async () => {
    render(<NewOrderPage />)
    await waitFor(() => {
      expect(screen.getByText('优惠金额 (¥)')).toBeInTheDocument()
      expect(screen.getByText('实收款 (¥)')).toBeInTheDocument()
    })
  })

  // #2987：数量输入框默认 1，清空不得被强制弹回（旧 onChange 用 Math.max(1, Number('')) 把空值改回 1）
  it('商品数量输入框可清空默认值 1 并自由输入（整数与按米小数）', async () => {
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '测试窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p1', name: '测试窗帘', skus: [], supportsProcessing: false, price: 100 } },
    })
    mockGetProductProcessingItems.mockResolvedValue({ data: { data: [] } })

    render(<NewOrderPage />)

    // 走「点击搜索并选择商品」→ 弹窗选择「测试窗帘」→ 展开数量/单价区域
    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText('测试窗帘'))

    // Label 无 htmlFor 关联，按「数量」label 所在容器定位输入框
    const qtyLabel = await screen.findByText('数量')
    const qtyInput = qtyLabel.closest('div')!.querySelector('input') as HTMLInputElement
    expect(qtyInput).toHaveValue(1)

    // 清空 → 输入框为空（不再被强改回 1）
    fireEvent.change(qtyInput, { target: { value: '' } })
    expect(qtyInput.value).toBe('')

    // 重新输入整数
    fireEvent.change(qtyInput, { target: { value: '3' } })
    expect(qtyInput).toHaveValue(3)

    // 按米销售支持小数（2.5 米）
    fireEvent.change(qtyInput, { target: { value: '2.5' } })
    expect(qtyInput).toHaveValue(2.5)
  })
})
