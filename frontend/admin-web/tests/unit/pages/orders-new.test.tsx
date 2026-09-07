// case_ids: OR-009, OR-014
// OR-014（issue #2986）：下单加工项数量系统自动推导（per_meter→面料米数；per_piece+密度→ceil(面料×密度)；无密度→1），
// 商品数量变化联动重算；加工项行不显示数量输入框，用户不感知数量
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

  // ===== OR-014：加工项数量自动推导 =====

  const pickProduct = async (productName: string) => {
    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText(productName))
  }

  const fillCustomerAndSubmit = () => {
    fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
    fireEvent.click(screen.getByText('提交订单'))
  }

  const feeRowText = () => screen.getByText('加工费').closest('div')!.textContent || ''

  it('per_piece+密度：数量=ceil(面料米数×密度)，改商品数量联动重算，行内无数量输入框 (OR-014)', async () => {
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p1', name: '遮光窗帘', skus: [], supportsProcessing: true, price: 100 } },
    })
    mockGetProductProcessingItems.mockResolvedValue({
      data: {
        data: [
          {
            id: 'pi1',
            name: '打孔加工',
            pricingMethod: 'per_piece',
            unitPrice: 5,
            customPrice: null,
            finalPrice: 5,
            unit: '个',
            perMeterQuantity: 6,
          },
        ],
      },
    })

    render(<NewOrderPage />)
    await pickProduct('遮光窗帘')

    // 勾选加工项：面料默认 1 米 → 数量 = ceil(1×6) = 6 → 加工费 5×6 = 30
    fireEvent.click(await screen.findByRole('checkbox'))
    await waitFor(() => {
      expect(feeRowText()).toContain('¥30.00')
    })

    // 加工项行内不出现数量输入框（该行只含 checkbox 输入，无 number 输入）
    const procRow = screen.getByRole('checkbox').closest('div')!
    expect(procRow.querySelectorAll('input[type="number"]')).toHaveLength(0)
    expect(procRow.querySelectorAll('input')).toHaveLength(1)

    // 面料米数 3 → 数量 = ceil(3×6) = 18 → 加工费 5×18 = 90（数量联动重算）
    const qtyInput = (await screen.findByText('数量')).closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(qtyInput, { target: { value: '3' } })
    await waitFor(() => {
      expect(feeRowText()).toContain('¥90.00')
    })

    // 提交时 processingItems.quantity 使用推导数量 18
    fillCustomerAndSubmit()
    await waitFor(() => {
      expect(mockCreateOrder).toHaveBeenCalled()
    })
    const payload = mockCreateOrder.mock.calls[0][0]
    const detail = payload.items[0].processingInfo.processingItems[0]
    expect(detail.quantity).toBe(18)
    expect(detail.unitPrice).toBe(5)
    expect(detail.subtotal).toBe(90)
  })

  it('per_meter：数量=面料米数，单价×米数计加工费 (OR-014)', async () => {
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p2', name: '雪纺纱', price: 80 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p2', name: '雪纺纱', skus: [], supportsProcessing: true, price: 80 } },
    })
    mockGetProductProcessingItems.mockResolvedValue({
      data: {
        data: [
          {
            id: 'pi2',
            name: '韩式定型',
            pricingMethod: 'per_meter',
            unitPrice: 3,
            customPrice: null,
            finalPrice: 3,
            unit: '米',
            perMeterQuantity: 2,
          },
        ],
      },
    })

    render(<NewOrderPage />)
    await pickProduct('雪纺纱')
    fireEvent.click(await screen.findByRole('checkbox'))

    // 面料 1 米 → 数量 1 → 加工费 3
    await waitFor(() => {
      expect(feeRowText()).toContain('¥3.00')
    })

    // 面料 2.5 米 → 数量 2.5 → 加工费 3×2.5 = 7.5
    const qtyInput = (await screen.findByText('数量')).closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(qtyInput, { target: { value: '2.5' } })
    await waitFor(() => {
      expect(feeRowText()).toContain('¥7.50')
    })

    // 提交时 quantity = 面料米数
    fillCustomerAndSubmit()
    await waitFor(() => {
      expect(mockCreateOrder).toHaveBeenCalled()
    })
    const payload = mockCreateOrder.mock.calls[0][0]
    expect(payload.items[0].processingInfo.processingItems[0].quantity).toBe(2.5)
  })

  it('per_piece 无密度：数量=1，改面料米数也不变 (OR-014)', async () => {
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p3', name: '棉麻布', price: 60 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p3', name: '棉麻布', skus: [], supportsProcessing: true, price: 60 } },
    })
    mockGetProductProcessingItems.mockResolvedValue({
      data: {
        data: [
          {
            id: 'pi3',
            name: '手工裁剪',
            pricingMethod: 'per_piece',
            unitPrice: 8,
            customPrice: null,
            finalPrice: 8,
            unit: '件',
          },
        ],
      },
    })

    render(<NewOrderPage />)
    await pickProduct('棉麻布')
    fireEvent.click(await screen.findByRole('checkbox'))

    // 无密度 → 数量恒为 1 → 加工费 8
    await waitFor(() => {
      expect(feeRowText()).toContain('¥8.00')
    })

    const qtyInput = (await screen.findByText('数量')).closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(qtyInput, { target: { value: '10' } })
    await waitFor(() => {
      expect(feeRowText()).toContain('¥8.00')
    })

    // 提交时 quantity = 1
    fillCustomerAndSubmit()
    await waitFor(() => {
      expect(mockCreateOrder).toHaveBeenCalled()
    })
    const payload = mockCreateOrder.mock.calls[0][0]
    expect(payload.items[0].processingInfo.processingItems[0].quantity).toBe(1)
  })
})
