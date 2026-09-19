// case_ids: OR-009, OR-014, UI-038, CU-009
// OR-014（issue #3005 回滚 #2986）：下单加工项数量规则——per_meter→面料米数；per_set/fixed/per_area→1，
// 商品数量变化联动重算；加工项行显示「名称+数量+金额」供对账，无数量输入框（数量由计价方式派生）
// ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：加工项改为**店铺级目录**（processingItemApi.getProcessingItems
// 只加载一次），不再按商品过滤；解耦钉死断言见 orders-new-decoupled.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

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
  // 算料试算（issue #4434）：本文件验的是樘窗绑组 / 配布边 / 加工项数量，与试算**正交**
  // ⇒ 让试算停在「进行中」（永不 resolve），避免它改写「数量」污染这些判据。
  // 试算自身的判据在 `orders-new-craft-calc.test.tsx`。
  craftCalcApi: { preview: () => new Promise(() => {}) },
  // 加工费计价预览（issue #4450）：本文件验的是樘窗绑组 / 配布边 / 加工项数量口径，
  // 与「组合取价」正交 ⇒ 桩成一个**组合价 == Σ 加工项**的服务端
  // （数值与旧口径逐值一致 ⇒ 这些判据的断言一字不用改；组合取价本身的判据在
  //  `orders-new-fee-preview.test.tsx`）。**必须 resolve**：预览未就绪时页面会拦住提交。
  feePreviewApi: {
    preview: (payload: any) => {
      const items = (payload?.items ?? []).map((it: any) => {
        const details = it?.processingInfo?.processingItems ?? []
        const fee = details.reduce(
          (s: number, d: any) => s + (Number(d.unitPrice) || 0) * (Number(d.quantity) || 0),
          0
        )
        return {
          processingFee: fee,
          processingFeeDetail: { fee_source: 'matched', unit_price: 0, meters: 0, amount: fee },
        }
      })
      const processingFeeTotal = items.reduce((s: number, r: any) => s + r.processingFee, 0)
      return Promise.resolve({ data: { data: { items, processingFeeTotal } } })
    },
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
    // 宽 / 高必填（issue #4420）：选完商品即补齐，让各用例回到「只验它自己那条判据」的状态
    await screen.findByText('宽 (米)')
    fillSize()
  }

  /**
   * 宽 / 高必填（issue #4420，用户 2026-09-19 裁定）。
   * `Label` 无 `htmlFor` 关联 ⇒ 按 label 文本定位其所在容器里的 input。
   */
  const fillSize = (idx = 0, w = '6.6', h = '2.6') => {
    const pick = (label: string) =>
      screen
        .getAllByText(label)
        .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)
    fireEvent.change(pick('宽 (米)')[idx], { target: { value: w } })
    fireEvent.change(pick('高 (米)')[idx], { target: { value: h } })
  }

  /** 展开工艺规格里的「特殊选项」区（issue #4420：默认收起） */
  /** 展开某一行（第 idx 个部位行）的「工艺规格」折叠区（issue #4493 三层体验②：默认收起） */
  const expandCraft = (idx = 0) => {
    const btn = screen.getAllByRole('button', { name: /工艺规格/ })[idx]
    // 幂等：已展开就不动（同一用例里会被调用多次）
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  }

  /** 展开某一行（第 idx 个部位行）的「加工选项」折叠区（issue #4489 判据 3：默认折叠） */
  const expandProcessing = (idx = 0) => {
    const btn = screen.getAllByRole('button', { name: /加工选项/ })[idx]
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  }

  /**
   * chips 字段一击即中（issue #4489 判据 1）：按 `radiogroup` 名 + 选项名点击。
   * 旧写法 `getByLabelText(name)` + `fireEvent.change(<select>)` 在 chips 下已不成立。
   */
  const pickChip = (group: string, option: string, idx = 0) => {
    const groups = screen.getAllByRole('radiogroup', { name: group })
    fireEvent.click(within(groups[idx]).getByRole('radio', { name: option }))
  }

  const expandSpecial = (idx = 0) => {
    const toggles = screen.getAllByRole('button', { name: /特殊选项/ })
    fireEvent.click(toggles[idx])
  }

  const fillCustomerAndSubmit = async () => {
    fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
    // 加工费计价闸门（issue #4450）：**页面总额必须就是服务端将算出的总额**，未就绪时提交会被拦
    // ⇒ 提交前等计价落地（真实商家也是看到金额才提交）。判据本身在 orders-new-fee-preview.test.tsx。
    await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
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
    expandProcessing()
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
    await fillCustomerAndSubmit()
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
    expandProcessing()
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
    await fillCustomerAndSubmit()
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
    expandProcessing()
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
    await fillCustomerAndSubmit()
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

    await fillCustomerAndSubmit()
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

    // issue #4419：客户档案录了默认收货地址/常用物流时，**优先**用档案值（逐字带出，
    // 不拼接省市区、不用昵称顶替收货人姓名），并提示常用物流。
    it('客户档案有默认收货信息时优先带出（逐字），并提示常用物流（#4419）', async () => {
      mockGetCustomers.mockResolvedValue({
        data: {
          data: {
            items: [
              {
                id: 'c3',
                wechatNickname: '王老板',
                phone: '13700137000',
                sourceChannel: 'wechat_mini',
                regionProvince: '浙江省', regionCity: '杭州市', regionDistrict: '西湖区',
                defaultReceiverName: '王老板（仓库）',
                defaultReceiverPhone: '13600136000',
                defaultReceiverAddress: '浙江省杭州市余杭区文一西路969号3号仓',
                defaultLogisticsType: 'logistics',
                defaultLogisticsCompany: '四季安物流',
              },
            ],
            total: 1,
          },
        },
      })
      render(<NewOrderPage />)
      fireEvent.click(await screen.findByRole('button', { name: /选择客户/ }))
      fireEvent.click(await screen.findByText('王老板'))
      await waitFor(() => {
        expect(screen.getByPlaceholderText('请输入收货人姓名')).toHaveValue('王老板（仓库）')
        expect(screen.getByPlaceholderText('请输入 11 位手机号')).toHaveValue('13600136000')
        expect(screen.getByPlaceholderText('请输入详细收货地址')).toHaveValue('浙江省杭州市余杭区文一西路969号3号仓')
      })
      expect(screen.getByTestId('picked-logistics-hint')).toHaveTextContent('常用物流：物流/专线 · 四季安物流')
    })

    it('客户档案没录常用物流时不显示提示（不得编造「快递」默认值，#4419）', async () => {
      render(<NewOrderPage />)
      fireEvent.click(await screen.findByRole('button', { name: /选择客户/ }))
      fireEvent.click(await screen.findByText('张老板'))
      await waitFor(() => {
        expect(screen.getByPlaceholderText('请输入收货人姓名')).toHaveValue('张老板')
      })
      expect(screen.queryByTestId('picked-logistics-hint')).not.toBeInTheDocument()
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
      await screen.findByText('宽 (米)')
      expandCraft()
    }

    const field = (name: string) => screen.getByLabelText(name)

    const craftInfo = () => {
      const payload = mockCreateOrder.mock.calls[0][0]
      return payload.items[0].processingInfo as Record<string, unknown>
    }

    it('填了工艺规格 ⇒ 提交 payload 的 processingInfo 含全部 camelCase 工艺键（判据 F·B 端半边）', async () => {
      await setupCurtain()

      expandCraft()

      pickChip('部位', '纱帘')
      expandCraft()
      pickChip('工艺', '打孔')
      expandCraft()
      pickChip('加工类型', '定高买宽')
      expandCraft()
      pickChip('打开方式', '双开')
      expandCraft()
      pickChip('是否定型', '否')
      expandCraft()
      pickChip('款式', '单色')
      fireEvent.change(field('褶距'), { target: { value: '0.1' } })
      expandCraft()
      pickChip('是否对花', '是')
      fireEvent.change(field('花距'), { target: { value: '0.6' } })
      expandSpecial()
      fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
      fireEvent.click(screen.getByRole('button', { name: '拼2次' }))

      await fillCustomerAndSubmit()
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

      await fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      const info = (payload.items[0].processingInfo ?? {}) as Record<string, unknown>

      // issue #4420 口径变更（用户 2026-09-19 裁定）：三条**默认档**是真值 ⇒ **必须写**。
      // 「缺值不写」管的是「既没填也没默认」的键 —— 不是把默认值也一起吞掉。
      // issue #4493：默认档扩到 8 项全覆盖 ⇒ 这几项**必须写**（商家看得见的真值）
      expect(info).toMatchObject({
        saleForm: '成品帘',
        curtainType: '布帘',
        craft: '韩褶',
        cuttingMode: '定高买宽',
        style: '单色',
        pleatSpacing: 0.125,
        hasPattern: false,
        // **宽 → 打开方式**联动（真值源 §10 的启发式）：6.6m > 5m ⇒ 四开
        openCount: 4,
      })

      // 其余键仍然「缺值不写」（不写空串 / 0 / false 占位）
      for (const key of [
        'isShaped',
        'patternRepeat',
        'specialOptions',
        'componentRole',
        'craftLineId',
        'metersSource',
      ]) {
        expect(info).not.toHaveProperty(key)
      }
    })

    it('单色单不写 componentRole / craftLineId（缺省即主布，存量语义不动）', async () => {
      await setupCurtain()
      expandCraft()
      pickChip('款式', '单色')

      await fillCustomerAndSubmit()
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
      expandCraft()
      pickChip('款式', '拼色')
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      await fillCustomerAndSubmit()
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
      expandCraft()
      pickChip('款式', '拼色')
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      // 未改过 ⇒ 默认跟主布
      expect((field('配布边米数') as HTMLInputElement).value).toBe('3')

      fireEvent.change(field('配布边米数'), { target: { value: '2.5' } })

      await fillCustomerAndSubmit()
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
      expandProcessing()
    fireEvent.click(await screen.findByRole('checkbox'))
      expandCraft()
      pickChip('款式', '拼色')
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      await fillCustomerAndSubmit()
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
      expandCraft()
      pickChip('款式', '拼色')
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      await fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.items[1].productName).toBe('配布边')
      expect(payload.items[1].productId).toBeUndefined()
    })

    it('不填配布边单价 ⇒ 不生成配布边行（后端 unitPrice 必须 > 0，不得凭空造价）', async () => {
      await setupCurtain()
      expandCraft()
      pickChip('款式', '拼色')

      await fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      expect(payload.items).toHaveLength(1)
      expect((payload.items[0].processingInfo as Record<string, unknown>).style).toBe('拼色')
    })

    it('双拼：配布边金额计入订单总额（否则后端「应收 - 优惠 ≈ 实收」校验会拒单）', async () => {
      await setupCurtain()
      expandCraft()
      pickChip('款式', '拼色')
      fireEvent.change(field('配布边单价'), { target: { value: '40' } })

      // 主布 100 × 1 米 + 配布边 40 × 1 米 = 140
      await waitFor(() => {
        expect(screen.getByText('订单金额').closest('div')!.textContent).toContain('¥140.00')
      })

      await fillCustomerAndSubmit()
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
  // issue #4486：**「樘窗」字段已按用户裁定移除** ⇒ 原「樘窗绑组写侧」判据整体作废，
  // 换成「字段已移除」的红证（能力收窄的代价已登记在该 issue：布+纱 会算成 2 樘窗，
  // 套级工序各实例化 2 次 ⇒ 计件工资双付约 ¥3/樘）。
  describe('#4486 樘窗字段已移除', () => {
    beforeEach(() => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
      })
    })

    it('下单页**不再出现**「樘窗」输入框（红证：修复前存在）', async () => {
      render(<NewOrderPage />)
      await pickProduct('遮光窗帘')
      await screen.findByText('宽 (米)')
      expect(screen.queryByLabelText('樘窗')).toBeNull()
      expect(screen.queryByText('樘窗')).toBeNull()
    })

    it('提交 payload **不再写** craftLineId（跨行分组已去掉；配布边配对键另见 §4.8 判据）', async () => {
      render(<NewOrderPage />)
      await pickProduct('遮光窗帘')
      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
      const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo
      expect(info.craftLineId).toBeUndefined()
    })
  })

  describe('#4420 尺寸必填 · 默认档 · 新增部位 · 展示折叠', () => {
    const setupCurtain = async () => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
      })
      render(<NewOrderPage />)
      await pickProduct('遮光窗帘')
      await screen.findByText('宽 (米)')
      expandCraft()
    }

    it('判据 1（红证）：宽/高不填 ⇒ 提交被拦且报出是第几行（修复前可提交）', async () => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
      })
      render(<NewOrderPage />)
      fireEvent.click(await screen.findByText('点击搜索并选择商品'))
      fireEvent.click(await screen.findByText('遮光窗帘'))
      await screen.findByText('宽 (米)')
      // 刻意**不走** pickProduct（它会补齐宽高）——这里要的就是「没填」的形态
      await fillCustomerAndSubmit()

      await waitFor(() => {
        expect(screen.getByText('第 1 个商品未填宽（米）')).toBeInTheDocument()
      })
      expect(screen.getByText('第 1 个商品未填高（米）')).toBeInTheDocument()
      expect(mockCreateOrder).not.toHaveBeenCalled()
    })

    it('判据 2（红证）：填了宽/高 ⇒ payload 的 items[].width/height 是数值（修复前这两个键根本不出现）', async () => {
      await setupCurtain()
      fillSize(0, '6.6', '2.6')
      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

      const item = mockCreateOrder.mock.calls[0][0].items[0]
      expect(item.width).toBe(6.6)
      expect(item.height).toBe(2.6)
    })

    it('判据 3：三条默认档随单落库（加工类型定高买宽 / 款式单色 / 褶距 0.125）', async () => {
      await setupCurtain()
      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

      expect(mockCreateOrder.mock.calls[0][0].items[0].processingInfo).toMatchObject({
        cuttingMode: '定高买宽',
        style: '单色',
        pleatSpacing: 0.125,
      })
    })

    it('判据 4：默认档在界面上**可见可改**（不是藏起来的隐式默认）', async () => {
      await setupCurtain()
      expandCraft()
      const checked = (group: string) =>
        within(screen.getAllByRole('radiogroup', { name: group })[0])
          .getAllByRole('radio')
          .filter((r) => r.getAttribute('aria-checked') === 'true')
          .map((r) => r.textContent)
      expect(checked('加工类型')).toEqual(['定高买宽'])
      expect(checked('款式')).toEqual(['单色'])
      expect((screen.getByLabelText('褶距') as HTMLInputElement).value).toBe('0.125')
      // issue #4493 三层体验①：默认档扩到 8 项全覆盖（用户「太多点选了」）
      expect(checked('部位')).toEqual(['布帘'])
      expect(checked('工艺')).toEqual(['韩褶'])
      expect(checked('是否对花')).toEqual(['否'])
    })

    it('判据 5（#4485 红证）：「新增部位」⇒ 行数 +1、**同一张商品卡**、部位清空', async () => {
      await setupCurtain()
      fireEvent.click(screen.getByRole('button', { name: /新增部位/ }))

      await waitFor(() =>
        expect(screen.getAllByRole('button', { name: /工艺规格/ })).toHaveLength(2)
      )
      // ⭐ issue #4485：新部位嵌在**同一个商品组**里 —— 「选择商品」只出现一次
      // （修复前是复制出第二张完整商品卡 ⇒ 看起来像两个商品）
      expect(screen.getAllByText('选择商品')).toHaveLength(1)
      // 新行部位**必须清空**：继承会让商家以为已选好 ⇒ 两行同部位 ⇒ 加工单长出两套同部位工序
      expandCraft(1)
      const groups = screen.getAllByRole('radiogroup', { name: '部位' })
      expect(groups).toHaveLength(2)
      const checkedText = (g: HTMLElement) =>
        within(g)
          .getAllByRole('radio')
          .filter((r) => r.getAttribute('aria-checked') === 'true')
          .map((r) => r.textContent)
      expect(checkedText(groups[0])).toEqual(['布帘'])
      // 新行**不得**继承成同部位（两行同部位 ⇒ 加工单长出两套同部位工序）
      expect(checkedText(groups[1])).not.toEqual(['布帘'])
    })

    it('判据 6：同一商品两个部位（布 + 纱）⇒ 两条 order_items 各带**自己的**宽高', async () => {
      await setupCurtain()
      fireEvent.click(screen.getByRole('button', { name: /新增部位/ }))
      await waitFor(() =>
        expect(screen.getAllByRole('button', { name: /工艺规格/ })).toHaveLength(2)
      )
      expandCraft(0)
      expandCraft(1)
      pickChip('部位', '布帘', 0)
      pickChip('部位', '纱帘', 1)
      fillSize(0, '6.6', '2.6')
      fillSize(1, '6.6', '1.6')

      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

      const items = mockCreateOrder.mock.calls[0][0].items
      expect(items).toHaveLength(2)
      expect(items[0].height).toBe(2.6)
      // 纱帘常做半帘 —— 宽高是**部位级**（§5.9.2），共用行级宽高必有一件算错用料
      expect(items[1].height).toBe(1.6)
    })

    it('判据 7（展示）：部位行可收起为摘要 —— 录入项隐藏、结论常显', async () => {
      await setupCurtain()
      fillSize(0, '6.6', '2.6')
      // 行头 = 含摘要尺寸的那个按钮
      const header = screen.getByText(/6\.6 × 2\.6 m/).closest('button') as HTMLElement
      expect(header).toBeTruthy()
      fireEvent.click(header)

      // 收起 = **CSS 隐藏而非卸载**（issue #4489 的组件包发现：卸载会丢「手改留痕」标志）
      const craftToggle = screen.getAllByRole('button', { name: /工艺规格/ })[0]
      expect(craftToggle.closest('.hidden')).not.toBeNull()
      // 摘要仍报出尺寸（收起 ≠ 信息消失）
      expect(screen.getByText(/6\.6 × 2\.6 m/)).toBeInTheDocument()
    })
  })
})
