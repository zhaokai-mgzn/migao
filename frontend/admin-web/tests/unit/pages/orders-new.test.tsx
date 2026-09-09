// case_ids: OR-009, OR-014, UI-038
// OR-014（issue #3005 回滚 #2986）：下单加工项数量规则——per_meter→面料米数；per_set/fixed/per_area→1，
// 商品数量变化联动重算；加工项行显示「名称+数量+金额」供对账，无数量输入框（数量由计价方式派生）
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock API
const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProductProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    createOrder: (...args: any[]) => mockCreateOrder(...args),
  },
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    getProduct: (...args: any[]) => mockGetProduct(...args),
    getProductProcessingItems: (...args: any[]) => mockGetProductProcessingItems(...args),
  },
  customerApi: {
    getCustomers: (...args: any[]) => mockGetCustomers(...args),
  },
}))

// useOrderAmounts 使用真实实现（纯状态 hook，无外部依赖）：
// 页面级集成验证「优惠金额不吞键 / 实收款反算优惠 / 提交 payload 携带 discountAmount」

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

  it('per_meter：数量=面料米数，单价×米数计加工费，行内无数量输入框 (OR-014)', async () => {
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
            pricingMethod: 'per_meter',
            unitPrice: 5,
            customPrice: null,
            finalPrice: 5,
            unit: '米',
          },
        ],
      },
    })

    render(<NewOrderPage />)
    await pickProduct('遮光窗帘')

    // 勾选加工项：面料默认 1 米 → 数量 1 → 加工费 5
    fireEvent.click(await screen.findByRole('checkbox'))
    await waitFor(() => {
      expect(feeRowText()).toContain('¥5.00')
    })

    // 加工项行内不出现数量输入框（该行只含 checkbox 输入，无 number 输入）
    const procRow = screen.getByRole('checkbox').closest('div')!
    expect(procRow.querySelectorAll('input[type="number"]')).toHaveLength(0)
    expect(procRow.querySelectorAll('input')).toHaveLength(1)

    // 面料米数 3 → 数量 3 → 加工费 5×3 = 15（数量联动重算）
    const qtyInput = (await screen.findByText('数量')).closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(qtyInput, { target: { value: '3' } })
    await waitFor(() => {
      expect(feeRowText()).toContain('¥15.00')
    })

    // 提交时 processingItems.quantity = 面料米数 3
    fillCustomerAndSubmit()
    await waitFor(() => {
      expect(mockCreateOrder).toHaveBeenCalled()
    })
    const payload = mockCreateOrder.mock.calls[0][0]
    const detail = payload.items[0].processingInfo.processingItems[0]
    expect(detail.quantity).toBe(3)
    expect(detail.unitPrice).toBe(5)
    expect(detail.subtotal).toBe(15)
  })

  it('per_meter：小数面料米数，单价×米数计加工费 (OR-014)', async () => {
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

  it('per_set：数量=1，改面料米数也不变 (OR-014)', async () => {
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
            name: '帘头加工',
            pricingMethod: 'per_set',
            unitPrice: 50,
            customPrice: null,
            finalPrice: 50,
            unit: '套',
          },
        ],
      },
    })

    render(<NewOrderPage />)
    await pickProduct('棉麻布')
    fireEvent.click(await screen.findByRole('checkbox'))

    // per_set → 数量恒为 1 → 加工费 50
    await waitFor(() => {
      expect(feeRowText()).toContain('¥50.00')
    })

    const qtyInput = (await screen.findByText('数量')).closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(qtyInput, { target: { value: '10' } })
    await waitFor(() => {
      expect(feeRowText()).toContain('¥50.00')
    })

    // 提交时 quantity = 1
    fillCustomerAndSubmit()
    await waitFor(() => {
      expect(mockCreateOrder).toHaveBeenCalled()
    })
    const payload = mockCreateOrder.mock.calls[0][0]
    expect(payload.items[0].processingInfo.processingItems[0].quantity).toBe(1)
  })

  // ===== 优惠金额/实收款 双向联动（页面级集成，真实 useOrderAmounts）=====

  // 场景复刻用户报障（化简）：测试9999 ¥9 × 20 = 订单 180；实收 165 → 优惠应为 15
  const setupOrder180 = async () => {
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p9', name: '测试9999', price: 9 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({
      data: { data: { id: 'p9', name: '测试9999', skus: [], supportsProcessing: false, price: 9 } },
    })
    mockGetProductProcessingItems.mockResolvedValue({ data: { data: [] } })

    render(<NewOrderPage />)
    await pickProduct('测试9999')

    const qtyInput = (await screen.findByText('数量')).closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(qtyInput, { target: { value: '20' } })

    const totalRow = await screen.findByText('订单金额')
    expect(totalRow.closest('div')!.textContent).toContain('¥180.00')
  }

  const discountInput = () => screen.getByLabelText('优惠金额 (¥)') as HTMLInputElement
  const actualInput = () => screen.getByLabelText('实收款 (¥)') as HTMLInputElement

  it('优惠金额输入框可自由键入，不被每键重格式化吞键（修复锁死）', async () => {
    await setupOrder180()

    // 键入 "1" → 输入框保持 "1"（旧实现立即重格式化为 "1.00"，后续键入被吞 → 视觉上锁死）
    fireEvent.change(discountInput(), { target: { value: '1' } })
    expect(discountInput().value).toBe('1')

    // 继续键入 "15" → 保持 "15"
    fireEvent.change(discountInput(), { target: { value: '15' } })
    expect(discountInput().value).toBe('15')

    // 实收款联动：180 - 15 = 165
    expect(actualInput().value).toBe('165.00')

    // blur 归一化为两位小数
    fireEvent.blur(discountInput())
    expect(discountInput().value).toBe('15.00')
  })

  it('输入实收款 → 优惠金额自动反算（双向联动）', async () => {
    await setupOrder180()

    // 实收 165 → 优惠 = 180 - 165 = 15.00（旧实现优惠恒为 0.00 不联动）
    fireEvent.change(actualInput(), { target: { value: '165' } })
    expect(discountInput().value).toBe('15.00')
    expect(actualInput().value).toBe('165')

    // blur 后实收归一为两位小数
    fireEvent.blur(actualInput())
    expect(actualInput().value).toBe('165.00')
    expect(discountInput().value).toBe('15.00')
  })

  it('提交订单 payload 携带 discountAmount（后端校验 应收-优惠≈实收 必需）', async () => {
    await setupOrder180()

    fireEvent.change(actualInput(), { target: { value: '165' } })
    fireEvent.blur(actualInput())

    fillCustomerAndSubmit()
    await waitFor(() => {
      expect(mockCreateOrder).toHaveBeenCalled()
    })
    const payload = mockCreateOrder.mock.calls[0][0]
    expect(payload.actualAmount).toBe(165)
    expect(payload.discountAmount).toBe(15)
  })

  // ── 客户选择（#3102）：选择已有客户自动回填收货信息，保留手动兜底 ──

  describe('客户选择（#3102）', () => {
    beforeEach(() => {
      mockGetCustomers.mockResolvedValue({
        data: {
          data: {
            items: [
              { id: 'c1', wechatNickname: '张老板', phone: '13800138001', sourceChannel: 'wechat_mini', regionProvince: '浙江省', regionCity: '杭州市', regionDistrict: '西湖区', vipLevel: 'vip1' },
              { id: 'c2', wechatNickname: '李经理', phone: '13900139002', sourceChannel: 'web', regionProvince: '江苏省', regionCity: '苏州市', regionDistrict: '姑苏区' },
            ],
            total: 2,
          },
        },
      })
    })

    it('收货信息区提供「选择客户」入口', async () => {
      render(<NewOrderPage />)
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /选择客户/ })).toBeInTheDocument()
      })
    })

    it('点击「选择客户」打开客户选择弹窗并加载客户列表', async () => {
      render(<NewOrderPage />)
      fireEvent.click(await screen.findByRole('button', { name: /选择客户/ }))
      // 弹窗内搜索框出现
      await waitFor(() => {
        expect(screen.getByPlaceholderText(/搜索客户/)).toBeInTheDocument()
      })
      // 加载客户列表（getCustomers 被调用，客户行渲染）
      expect(mockGetCustomers).toHaveBeenCalled()
      await waitFor(() => {
        expect(screen.getByText('张老板')).toBeInTheDocument()
        expect(screen.getByText('13800138001')).toBeInTheDocument()
      })
    })

    it('选中客户后自动回填 收货人姓名/手机号/地址（省市区拼接）', async () => {
      render(<NewOrderPage />)
      fireEvent.click(await screen.findByRole('button', { name: /选择客户/ }))
      fireEvent.click(await screen.findByText('张老板'))
      await waitFor(() => {
        expect(screen.getByPlaceholderText('请输入收货人姓名')).toHaveValue('张老板')
        expect(screen.getByPlaceholderText('请输入 11 位手机号')).toHaveValue('13800138001')
        expect(screen.getByPlaceholderText('请输入详细收货地址')).toHaveValue('浙江省 杭州市 西湖区')
      })
    })

    it('搜索关键词触发 getCustomers 携带 keyword', async () => {
      render(<NewOrderPage />)
      fireEvent.click(await screen.findByRole('button', { name: /选择客户/ }))
      const search = await screen.findByPlaceholderText(/搜索客户/)
      fireEvent.change(search, { target: { value: '张' } })
      fireEvent.keyDown(search, { key: 'Enter' })
      await waitFor(() => {
        expect(mockGetCustomers).toHaveBeenCalledWith(expect.objectContaining({ keyword: '张' }))
      })
    })
  })
})
