// case_ids: OR-009, OR-014, UI-038
// OR-014（issue #3005 回滚 #2986）：下单加工项数量规则——per_meter→面料米数；per_set/fixed/per_area→1，
// 商品数量变化联动重算；加工项行显示「名称+数量+金额」供对账，无数量输入框（数量由计价方式派生）
// ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：加工项改为**店铺级目录**（processingItemApi.getProcessingItems
// 只加载一次），不再按商品过滤；解耦钉死断言见 orders-new-decoupled.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// Mock API
const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    createOrder: (...args: any[]) => mockCreateOrder(...args),
  },
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    getProduct: (...args: any[]) => mockGetProduct(...args),
  },
  processingItemApi: {
    getProcessingItems: (...args: any[]) => mockGetProcessingItems(...args),
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
    // 加工项目录（店铺级）：默认空目录，需要加工项的用例自行覆盖
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
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
      data: { data: { id: 'p1', name: '测试窗帘', skus: [], price: 100 } },
    })

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
      data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
    })
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'pi1', name: '打孔加工', pricingMethod: 'per_meter', unitPrice: 5, unit: '米' },
          ],
        },
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
      data: { data: { id: 'p2', name: '雪纺纱', skus: [], price: 80 } },
    })
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'pi2', name: '韩式定型', pricingMethod: 'per_meter', unitPrice: 3, unit: '米' },
          ],
        },
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
      data: { data: { id: 'p3', name: '棉麻布', skus: [], price: 60 } },
    })
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'pi3', name: '帘头加工', pricingMethod: 'per_set', unitPrice: 50, unit: '套' },
          ],
        },
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
      data: { data: { id: 'p9', name: '测试9999', skus: [], price: 9 } },
    })

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

  // ===== 工艺规格写侧（issue #4375 包 4b · 设计文档 §4.2/§4.5/§4.6 入口 2/§4.8）=====
  //
  // 病根：下单页构造 processingInfo 时只写 6 个规格键 ⇒ 商家手工建的订单，订单/加工单面
  // 一个工艺字段都不显示。下面这组判据即「手工录单也要把工艺规格落库」。
  describe('工艺规格写侧（#4375）', () => {
    const setupCurtain = async (productName = '遮光窗帘') => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: productName, price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: {
          data: { id: 'p1', name: productName, skus: [], price: 100 },
        },
      })
      // ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：加工项不再随商品下发（商品 payload 已无
      // `supportsProcessing`/`processingItems`），改由**店铺级目录**提供 ⇒ 这里桩目录端点
      // （「双拼：加工项只挂主布行」那条判据需要一个可勾选的加工项）。
      // 目录条目形状 = `ProcessingItem`（`unitPrice`/`unit`，无 `customPrice`/`finalPrice`）。
      mockGetProcessingItems.mockResolvedValue({
        data: {
          data: {
            items: [
              { id: 'pi1', name: '打孔加工', pricingMethod: 'per_meter', unitPrice: 5, unit: '米' },
            ],
          },
        },
      })
      render(<NewOrderPage />)
      await pickProduct(productName)
      await screen.findByLabelText('部位')
    }

    const field = (name: string) => screen.getByLabelText(name)

    const craftInfo = () => {
      const payload = mockCreateOrder.mock.calls[0][0]
      return payload.items[0].processingInfo as Record<string, unknown>
    }

    it('填了工艺规格 ⇒ 提交 payload 的 processingInfo 含全部 camelCase 工艺键（判据 F·B 端半边）', async () => {
      await setupCurtain()

      fireEvent.change(field('部位'), { target: { value: '纱帘' } })
      fireEvent.change(field('工艺'), { target: { value: '打孔' } })
      fireEvent.change(field('加工类型'), { target: { value: '定高买宽' } })
      fireEvent.change(field('打开方式'), { target: { value: '2' } })
      fireEvent.change(field('是否定型'), { target: { value: 'false' } })
      fireEvent.change(field('款式'), { target: { value: '单色' } })
      fireEvent.change(field('褶距'), { target: { value: '0.1' } })
      fireEvent.change(field('是否对花'), { target: { value: 'true' } })
      fireEvent.change(field('花距'), { target: { value: '0.6' } })
      fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
      fireEvent.click(screen.getByRole('button', { name: '拼2次' }))

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      expect(craftInfo()).toMatchObject({
        curtainType: '纱帘',
        craft: '打孔',
        cuttingMode: '定高买宽',
        openCount: 2,
        isShaped: false,
        style: '单色',
        pleatSpacing: 0.1,
        hasPattern: true,
        patternRepeat: 0.6,
        specialOptions: ['加铅块', '拼2次'],
      })
    })

    it('不填工艺规格 ⇒ payload 里不出现这些键（缺值不写，不写空串/0/false）', async () => {
      await setupCurtain()

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      const info = (payload.items[0].processingInfo ?? {}) as Record<string, unknown>
      for (const key of [
        'curtainType',
        'craft',
        'cuttingMode',
        'openCount',
        'isShaped',
        'pleatSpacing',
        'hasPattern',
        'patternRepeat',
        'style',
        'specialOptions',
        'componentRole',
        'craftLineId',
        'metersSource',
      ]) {
        expect(info).not.toHaveProperty(key)
      }
      // 无规格、无加工项 ⇒ 连 processingInfo 本身都不写（比「写一堆空键」更保守）
      expect(payload.items[0].processingInfo).toBeUndefined()
    })

    it('单色单不写 componentRole / craftLineId（缺省即主布，存量语义不动）', async () => {
      await setupCurtain()
      fireEvent.change(field('款式'), { target: { value: '单色' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const info = craftInfo()
      expect(info.style).toBe('单色')
      expect(info).not.toHaveProperty('componentRole')
      expect(info).not.toHaveProperty('craftLineId')
    })

    it('双拼（拼色）⇒ 主布行 + 配布边行两行，craftLineId 绑成一组（§4.8）', async () => {
      await setupCurtain()
      fireEvent.change(field('款式'), { target: { value: '拼色' } })
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.items).toHaveLength(2)

      const mainInfo = payload.items[0].processingInfo as Record<string, unknown>
      const edgeInfo = payload.items[1].processingInfo as Record<string, unknown>

      expect(mainInfo.componentRole).toBe('主布')
      expect(edgeInfo.componentRole).toBe('配布边')
      // 两行同组键 ⇒ 消费端合并为一扇窗的一个部位（否则折数/开数/工序/计件全翻倍）
      expect(edgeInfo.craftLineId).toBe(mainInfo.craftLineId)
      expect(mainInfo.craftLineId).toBeTruthy()
      expect(edgeInfo.metersSource).toBe('跟随主布')
      // 配布边行不携带工艺规格（折数/开数/幅数是一扇窗的属性）
      expect(edgeInfo).not.toHaveProperty('craft')
      expect(edgeInfo).not.toHaveProperty('openCount')
    })

    it('双拼：配布边米数默认 = 主布米数；改过 ⇒ metersSource=人工指定', async () => {
      await setupCurtain()
      const qtyInput = (await screen.findByText('数量')).closest('div')!.querySelector('input') as HTMLInputElement
      fireEvent.change(qtyInput, { target: { value: '3' } })
      fireEvent.change(field('款式'), { target: { value: '拼色' } })
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      // 未改过 ⇒ 默认跟主布
      expect((field('配布边米数') as HTMLInputElement).value).toBe('3')

      fireEvent.change(field('配布边米数'), { target: { value: '2.5' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      const edgeInfo = payload.items[1].processingInfo as Record<string, unknown>
      expect(edgeInfo.metersSource).toBe('人工指定')
      expect(payload.items[1].quantity).toBe(2.5)
    })

    it('双拼：加工项只挂主布行，配布边行不重复计加工费（硬约束）', async () => {
      await setupCurtain()
      fireEvent.click(await screen.findByRole('checkbox'))
      fireEvent.change(field('款式'), { target: { value: '拼色' } })
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      const mainInfo = payload.items[0].processingInfo as Record<string, unknown>
      const edgeInfo = payload.items[1].processingInfo as Record<string, unknown>
      expect((mainInfo.processingItems as unknown[]).length).toBe(1)
      expect(Number(mainInfo.processingFee)).toBeGreaterThan(0)
      expect(edgeInfo).not.toHaveProperty('processingItems')
      expect(edgeInfo).not.toHaveProperty('processingFee')
    })

    it('双拼：配布边行不关联主布商品（不重复扣库存/不重复计销量）', async () => {
      await setupCurtain()
      fireEvent.change(field('款式'), { target: { value: '拼色' } })
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.items[1].productName).toBe('配布边')
      expect(payload.items[1].productId).toBeUndefined()
    })

    it('不填配布边单价 ⇒ 不生成配布边行（后端 unitPrice 必须 > 0，不得凭空造价）', async () => {
      await setupCurtain()
      fireEvent.change(field('款式'), { target: { value: '拼色' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.items).toHaveLength(1)
      expect((payload.items[0].processingInfo as Record<string, unknown>).style).toBe('拼色')
    })

    it('双拼：配布边金额计入订单总额（否则后端「应收 - 优惠 ≈ 实收」校验会拒单）', async () => {
      await setupCurtain()
      fireEvent.change(field('款式'), { target: { value: '拼色' } })
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      // 主布 100 × 1 米 + 配布边 40 × 1 米 = 140
      await waitFor(() => {
        expect(screen.getByText('订单金额').closest('div')!.textContent).toContain('¥140.00')
      })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.actualAmount).toBe(140)
    })
  })

  // ===== 樘窗绑组写侧（issue #4395 判据 1）=====
  //
  // 病根：下单页**只在拼色时**写 `craftLineId` ⇒ 顾客下「布 + 纱」（两条明细行、都不带该键）
  // ⇒ 消费端 `ProcessingOrderService.craftGroupKey` 回落到各自 `itemId` ⇒ **两行各成一樘窗**
  // ⇒ 套级工序（外帘打卷/装袋/发货）在加工单上出现 **2 次**（#4384 A2 的红证因此不会转绿）。
  describe('樘窗绑组写侧（#4395）', () => {
    /** 一樘「布 + 纱」：两行各选一个商品、各自填部位，同樘窗号 */
    const setupClothPlusSheer = async () => {
      mockGetProducts.mockResolvedValue({
        data: {
          data: {
            items: [
              { id: 'p1', name: '遮光窗帘', price: 100 },
              { id: 'p2', name: '配套纱帘', price: 60 },
            ],
            total: 2,
          },
        },
      })
      mockGetProduct.mockImplementation((id: string) =>
        Promise.resolve({
          data: {
            data: {
              id,
              name: id === 'p2' ? '配套纱帘' : '遮光窗帘',
              skus: [],
              price: id === 'p2' ? 60 : 100,
            },
          },
        })
      )
      // ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：商品 payload 已无 `supportsProcessing`/`processingItems`，
      // 加工项改由**店铺级目录**端点提供（本组樘窗判据不需要加工项 ⇒ 用 beforeEach 的空目录默认桩）。
      render(<NewOrderPage />)

      // 第一行：布帘商品
      fireEvent.click(await screen.findByText('点击搜索并选择商品'))
      fireEvent.click(await screen.findByText('遮光窗帘'))
      await screen.findAllByLabelText('部位')

      // 第二行：纱帘商品
      fireEvent.click(screen.getByText('添加商品'))
      const pickButtons = screen.getAllByText('点击搜索并选择商品')
      fireEvent.click(pickButtons[pickButtons.length - 1])
      fireEvent.click(await screen.findByText('配套纱帘'))
      await waitFor(() => expect(screen.getAllByLabelText('部位')).toHaveLength(2))

      const fields = (name: string) => screen.getAllByLabelText(name)
      fireEvent.change(fields('部位')[0], { target: { value: '布帘' } })
      fireEvent.change(fields('工艺')[0], { target: { value: '韩褶' } })
      fireEvent.change(fields('部位')[1], { target: { value: '纱帘' } })
      fireEvent.change(fields('工艺')[1], { target: { value: '打孔' } })
    }

    const infos = () => {
      const payload = mockCreateOrder.mock.calls[0][0]
      return payload.items.map((i: any) => (i.processingInfo ?? {}) as Record<string, unknown>)
    }

    // 判据 1（写侧）：两条部位行同樘窗 ⇒ craftLineId **相等且非空**
    it('#4395 判据 1：一樘「布 + 纱」两行同樘窗 ⇒ 两条 order_items 的 craftLineId 相等且非空', async () => {
      await setupClothPlusSheer()
      const windows = screen.getAllByLabelText('樘窗')
      fireEvent.change(windows[0], { target: { value: '客厅主窗' } })
      fireEvent.change(windows[1], { target: { value: '客厅主窗' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.items).toHaveLength(2)
      const [clothInfo, sheerInfo] = infos()
      expect(clothInfo.craftLineId).toBeTruthy()
      expect(sheerInfo.craftLineId).toBeTruthy()
      expect(sheerInfo.craftLineId).toBe(clothInfo.craftLineId)
      // 代表行 = 主布行（部位=布帘）：§4.8 的 craftLineId 口径就是「主布行的行标识」
      expect(clothInfo.curtainType).toBe('布帘')
      expect(sheerInfo.curtainType).toBe('纱帘')
    })

    it('#4395 不同樘窗（窗号不同）⇒ 两条 craftLineId **不相等**（不是把所有行并成一樘）', async () => {
      await setupClothPlusSheer()
      const windows = screen.getAllByLabelText('樘窗')
      fireEvent.change(windows[0], { target: { value: '客厅主窗' } })
      fireEvent.change(windows[1], { target: { value: '次卧窗' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const [clothInfo, sheerInfo] = infos()
      // 两樘窗各只有一行 ⇒ 不写该键（单行樘窗的组键本来就 = 本行 itemId）
      expect(clothInfo).not.toHaveProperty('craftLineId')
      expect(sheerInfo).not.toHaveProperty('craftLineId')
    })

    it('#4395 未填樘窗 ⇒ 两行都不写 craftLineId（**存量语义不变**：各自成组）', async () => {
      await setupClothPlusSheer()

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const [clothInfo, sheerInfo] = infos()
      expect(clothInfo).not.toHaveProperty('craftLineId')
      expect(sheerInfo).not.toHaveProperty('craftLineId')
      expect(clothInfo.curtainType).toBe('布帘')
      expect(sheerInfo.curtainType).toBe('纱帘')
    })

    it('#4395 同樘窗 + 拼色 ⇒ 配布边行的 craftLineId 与樘窗组键**同一个**（不是该行自指）', async () => {
      await setupClothPlusSheer()
      const fields = (name: string) => screen.getAllByLabelText(name)
      const windows = fields('樘窗')
      fireEvent.change(windows[0], { target: { value: '客厅主窗' } })
      fireEvent.change(windows[1], { target: { value: '客厅主窗' } })
      // 布行拼色 + 填配布边单价 ⇒ 该行再生成一条配布边行
      fireEvent.change(fields('款式')[0], { target: { value: '拼色' } })
      fireEvent.change(fields('配布边单价')[0], { target: { value: '40' } })

      fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.items).toHaveLength(3)
      const [clothInfo, edgeInfo, sheerInfo] = infos()
      expect(clothInfo.componentRole).toBe('主布')
      expect(edgeInfo.componentRole).toBe('配布边')
      // 三条（布行 + 配布边行 + 纱行）必须**同组**：一樘窗 = 一个窗户
      expect(edgeInfo.craftLineId).toBe(clothInfo.craftLineId)
      expect(sheerInfo.craftLineId).toBe(clothInfo.craftLineId)
    })
  })
})
