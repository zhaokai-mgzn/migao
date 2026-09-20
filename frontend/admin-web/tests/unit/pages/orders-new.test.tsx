// case_ids: OR-009, OR-014, UI-038, CU-009, OR-038, OR-035
// OR-014（issue #3005 回滚 #2986）：下单加工项数量规则——per_meter→面料米数；per_set/fixed/per_area→1，
// 商品数量变化联动重算；加工项行显示「名称+数量+金额」供对账，无数量输入框（数量由计价方式派生）
// OR-035（工艺规格写侧录入）：#4566 起 `craft` / `isShaped` 的写侧真值来源搬到**加工项**
// （工艺 = 勾选的工艺项的 `craftHint`；定型 = 「定型」加工项的勾选态）⇒ 本文件的 #4566 组
// 即该用例「写侧录入」判据的新承载（原「工艺 / 是否定型 chips」判据随控件退场改判）。
// ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：加工项改为**店铺级目录**（processingItemApi.getProcessingItems
// 只加载一次），不再按商品过滤；解耦钉死断言见 orders-new-decoupled.test.tsx
// ⚠️ 2026-09-19（issue #4598）：帘（成品）行的米数输入框 label「数量」→「用料米数」
// （它就是**加工费米数**：`info.processingMeters = line.quantity`）⇒ 本文件的定位锚点同步改；
// **布料行（`FabricRow`）仍是「数量」**（按米卖布，单位由 sellingMethod 决定）—— 反向断言见判据 11。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { toast } from 'sonner'

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
// `info` 为 #4566 的**工艺单值护栏**提示所需（「一张单只能有一个工艺：已把「X」换成「Y」」）
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
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
    await screen.findByText('帘体')   // #4508：等商品落地（空态没有组壳）

    // Label 无 htmlFor 关联，按「用料米数」label 所在容器定位输入框（#4598 改名前叫「数量」）
    openWizardStep('尺寸与数量')
    const qtyLabel = await screen.findByText('用料米数')
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
    // issue #4511：手风琴 ⇒ 展开②会收起①，取用①的输入前必须先把它展开
    openWizardStep('尺寸与数量', idx)
    const pick = (label: string) =>
      screen
        .getAllByText(label)
        .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)
    fireEvent.change(pick('宽 (米)')[idx], { target: { value: w } })
    fireEvent.change(pick('高 (米)')[idx], { target: { value: h } })
  }

  /** 展开工艺规格里的「特殊选项」区（issue #4420：默认收起） */
  /**
   * 展开向导某一步（issue #4511 手风琴：展开一步自动收起同级其它）。
   * 步骤标题：① 尺寸与数量 ② 工艺规格 ③ 加工项 ④ 特殊选项。
   */
  const openWizardStep = (title: string, idx = 0) => {
    const btns = screen.getAllByRole('button', { name: new RegExp(`^\\d+ ${title}`) })
    const btn = btns[idx]
    if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
  }
  const expandCraft = (idx = 0) => openWizardStep('工艺规格', idx)
  const expandProcessing = (idx = 0) => openWizardStep('加工项', idx)
  const expandSpecial = (idx = 0) => openWizardStep('特殊选项', idx)

  /**
   * chips 字段一击即中（issue #4489 判据 1）：按 `radiogroup` 名 + 选项名点击。
   * 旧写法 `getByLabelText(name)` + `fireEvent.change(<select>)` 在 chips 下已不成立。
   */
  const pickChip = (group: string, option: string, idx = 0) => {
    // issue #4511 手风琴：先展开**该行**的②工艺规格 —— 展开它会收起别行的②
    // ⇒ 此时 DOM 里只剩这一个 radiogroup（所以下面取 [0] 而不是 [idx]）。
    expandCraft(idx)
    const groups = screen.getAllByRole('radiogroup', { name: group })
    fireEvent.click(within(groups[0]).getByRole('radio', { name: option }))
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
    openWizardStep('尺寸与数量')
    const qtyInput = (await screen.findByText('用料米数')).closest('div')!.querySelector('input') as HTMLInputElement
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
    openWizardStep('尺寸与数量')
    const qtyInput = (await screen.findByText('用料米数')).closest('div')!.querySelector('input') as HTMLInputElement
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

    openWizardStep('尺寸与数量')
    const qtyInput = (await screen.findByText('用料米数')).closest('div')!.querySelector('input') as HTMLInputElement
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

    openWizardStep('尺寸与数量')
    const qtyInput = (await screen.findByText('用料米数')).closest('div')!.querySelector('input') as HTMLInputElement
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
      // ⚠️ #4566：目录按 V83 种子形状给 —— 工艺项带 `craftHint`（`打孔`→打孔），
      // 以及手选特征「定型」（勾选态 = `isShaped`）。名字/工艺逐字 = V83 迁移。
      mockGetProcessingItems.mockResolvedValue({
        data: {
          data: {
            items: [
              {
                id: 'pi1',
                name: '打孔',
                craftHint: '打孔',
                pricingMethod: 'per_meter',
                unitPrice: 5,
                unit: '米',
              },
              { id: 'pi2', name: '定型', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
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

    /**
     * 勾选 / 取消「加工项」步骤里名为 `name` 的项（issue #4566 起，工艺与定型都从这里录入）。
     * 加工项行 = checkbox（`aria-label` = 项名）+ 名称 + 已选时的数量。
     */
    const toggleProcessingItem = (name: string) => {
      expandProcessing()
      fireEvent.click(screen.getByRole('checkbox', { name }))
    }

    const craftInfo = () => {
      const payload = mockCreateOrder.mock.calls[0][0]
      return payload.items[0].processingInfo as Record<string, unknown>
    }

    it('填了工艺规格 ⇒ 提交 payload 的 processingInfo 含全部 camelCase 工艺键（判据 F·B 端半边）', async () => {
      await setupCurtain()

      expandCraft()

      pickChip('加工类型', '定高买宽')
      expandCraft()
      pickChip('打开方式', '双开')
      expandCraft()
      pickChip('款式', '单色')
      fireEvent.change(field('褶距'), { target: { value: '0.1' } })
      expandCraft()
      pickChip('是否对花', '是')
      fireEvent.change(field('花距'), { target: { value: '0.6' } })
      // #4566：工艺 / 定型从**加工项**录入 —— 勾「打孔」⇒ craft='打孔'（craftHint 派生）；
      // 取消默认勾选的「定型」⇒ isShaped=false（显式否是真值）
      toggleProcessingItem('打孔')
      toggleProcessingItem('定型')
      expandSpecial()
      fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
      fireEvent.click(screen.getByRole('button', { name: '拼2次' }))

      await fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      expect(craftInfo()).toMatchObject({
        // ⚠️ issue #4521：**部位不再由下单页写**（主帘缺省即布帘；只有纱帘行显式写）
        // ⚠️ issue #4566：`craft` = **加工项 `craftHint` 派生值**（页面里没有工艺选择器）
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
      expect(craftInfo()).not.toHaveProperty('curtainType')
    })

    it('不填工艺规格 ⇒ payload 里不出现这些键（缺值不写，不写空串/0/false）', async () => {
      await setupCurtain()

      await fillCustomerAndSubmit()
      await waitFor(() => {
        expect(mockCreateOrder).toHaveBeenCalled()
      })

      const payload = mockCreateOrder.mock.calls[0][0]
      const info = (payload.items[0].processingInfo ?? {}) as Record<string, unknown>

      // issue #4420 口径变更（用户 2026-09-19 裁定）：**默认档**是真值 ⇒ **必须写**。
      // 「缺值不写」管的是「既没填也没默认」的键 —— 不是把默认值也一起吞掉。
      expect(info).toMatchObject({
        saleForm: '成品帘',
        // issue #4521：部位默认 = 布帘 ⇒ **不写**（下游 `DEFAULT_CURTAIN_TYPE` 缺省即此值）
        cuttingMode: '定高买宽',
        style: '单色',
        pleatSpacing: 0.125,
        hasPattern: false,
        // issue #4521 + #4566：定型默认（布帘 ⇒ 是）现在体现在「定型」**加工项的勾选态**上
        // ⇒ 仍是商家看得见的真值，照旧落库
        isShaped: true,
        // **宽 → 打开方式**联动（真值源 §10 的启发式）：6.6m > 5m ⇒ 四开
        openCount: 4,
      })

      // 其余键仍然「缺值不写」（不写空串 / 0 / false 占位）
      for (const key of [
        // #4566：一个工艺项都没勾 ⇒ **不猜、不填默认韩褶**（后端走 craft_hint → 信号表 → 租户默认的降级链）
        'craft',
        'curtainType',
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
      openWizardStep('尺寸与数量')
    const qtyInput = (await screen.findByText('用料米数')).closest('div')!.querySelector('input') as HTMLInputElement
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
      // #4566：目录里有「打孔」（工艺项）与「定型」（手选特征，布帘默认已勾）
      // ⇒ 按名字勾选，不数 checkbox（按名字勾 = 与商家所见一致）
      toggleProcessingItem('打孔')
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
      // ⚠️ 2026-09-19（issue #4526 R9/D6）：`processingItems` 里除**手选**加工项外还有
      // **自动识别特征**（超高/超宽/倒幅 —— 它们进组合键，与 ERP `打孔+超高+定型`
      // 同构；#4592 起**不含**「正幅」—— 它不在加工项目录里）。本条判据守的是
      // 「配布边行**不重复**挂加工项」⇒ 按**手选项**断言，不数长度
      // （长度会被自动特征数撑大，与判据无关）。
      const handPicked = (mainInfo.processingItems as Array<{ name: string }>).filter(
        (item) => item.name === '打孔'
      )
      expect(handPicked).toHaveLength(1)
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
  // ===== issue #4508：空态不该有「默认商品 1」=====
  // ===== issue #4521：部位行**整体移除**（一个商品组 = 一樘帘）=====
  describe('#4508/#4521 空态不渲染组壳；选了商品也**没有部位行**', () => {
    it('刚进页面（未选商品）⇒ **不出现**「商品 1」等组壳元素（红证：修复前出现两次）', async () => {
      render(<NewOrderPage />)
      await screen.findByText('点击搜索并选择商品')
      expect(screen.queryByText('商品 1')).toBeNull()
      expect(screen.queryByText('帘体')).toBeNull()
    })

    it('#4521 选了商品 ⇒ 组头出现商品名 / 帘体；**不出现**「部位 N」行头、「N 个部位」、「新增部位」', async () => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
      })
      render(<NewOrderPage />)
      await pickProduct('遮光窗帘')
      await screen.findByText('帘体')
      expect(screen.queryByText('商品 1')).toBeNull()
      // 红证：修复前这里有「部位 1」行头 + 「1 个部位」计数 + 「新增部位」按钮
      expect(screen.queryByText(/^部位 \d+$/)).toBeNull()
      expect(screen.queryByText(/个部位/)).toBeNull()
      expect(screen.queryByRole('button', { name: /新增部位/ })).toBeNull()
    })
  })

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

  describe('#4420/#4521 尺寸必填 · 默认档 · 帘体与纱帘 · 平级向导', () => {
    const setupCurtain = async () => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
      })
      // #4566：目录按 V83 种子形状给 —— 工艺项「韩折」（名字按 ERP 写「韩折」、`craftHint` 用
      // MIGAO 工艺枚举「韩褶」）+ 手选特征「定型」（勾选态 = `isShaped`）。
      // ⚠️ 不给「超高/超宽/倒幅」以外的自动项：手选列表过滤判据在 `orders-new-auto-features.test.tsx`。
      mockGetProcessingItems.mockResolvedValue({
        data: {
          data: {
            items: [
              {
                id: 'pi1',
                name: '韩折',
                craftHint: '韩褶',
                pricingMethod: 'per_meter',
                unitPrice: 0,
                unit: '米',
              },
              { id: 'pi2', name: '定型', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            ],
          },
        },
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
      expect(checked('是否对花')).toEqual(['否'])
      // issue #4521：部位换成**帘体**（组级 chips），默认「布帘」
      expect(checked('帘体')).toEqual(['布帘'])
      // ⚠️ issue #4566：工艺 / 定型**不在工艺规格里**（红证：修复前这两个 radiogroup 存在）
      expect(screen.queryByRole('radiogroup', { name: '工艺' })).toBeNull()
      expect(screen.queryByRole('radiogroup', { name: '是否定型' })).toBeNull()
      // 它们的默认档改在**加工项**上「可见可改」：布帘 ⇒ 「定型」默认勾上（真值源 §10）
      openWizardStep('加工项')
      expect((screen.getByRole('checkbox', { name: '定型' }) as HTMLInputElement).checked).toBe(
        true
      )
      expect((screen.getByRole('checkbox', { name: '韩折' }) as HTMLInputElement).checked).toBe(
        false
      )
    })

    // ── issue #4521：四类购买情况（布帘 / 布帘+纱帘 / 只买纱帘 / 布料）──────────────
    //
    // 用户口径：「用户可能购买**带纱帘的窗帘，不带纱帘的窗帘和只买纱帘，还有布料**，这四种情况，
    // **布帘需要算用料米数，纱帘不需要算用料米数，买多少就是多少**，如果买带纱帘的窗帘就要把
    // 两种组合起来」+「**移除部位功能，其实完全不需要**」。
    const pickBody = (body: string) => {
      fireEvent.click(
        within(screen.getByRole('radiogroup', { name: '帘体' })).getByRole('radio', { name: body })
      )
    }
    /** 按 label 文本取输入框（纱帘米数 / 纱帘单价在工艺规格步骤里，标签与 input 有 htmlFor 关联） */
    const field = (name: string) => screen.getByLabelText(name)

    /** 勾选「加工项」步骤里名为 `name` 的项（#4566：工艺 / 定型都从这里录入） */
    const toggleProcessingItem = (name: string) => {
      openWizardStep('加工项')
      fireEvent.click(screen.getByRole('checkbox', { name }))
    }

    it('判据 5（#4521 红证）：**没有**「新增部位」入口；一个商品组只渲染**一份** ①~④', async () => {
      await setupCurtain()
      expect(screen.queryByRole('button', { name: /新增部位/ })).toBeNull()
      // 四个步骤各只有一份（红证：修复前「新增部位」会让它们翻倍）
      expect(screen.getAllByRole('button', { name: /^1 尺寸与数量/ })).toHaveLength(1)
      expect(screen.getAllByRole('button', { name: /^2 工艺规格/ })).toHaveLength(1)
      expect(screen.getAllByRole('button', { name: /^3 加工项/ })).toHaveLength(1)
      expect(screen.getAllByRole('button', { name: /^4 特殊选项/ })).toHaveLength(1)
      // 行头（「部位 N」+ 行内「删除」）整体移除：删除只保留在**组头**一处
      expect(screen.queryByText(/^部位 \d+$/)).toBeNull()
    })

    it('判据 6（#4521）：帘体 = 布帘+纱帘 ⇒ 出纱帘米数/单价，提交**两条**明细行（同樘帘）', async () => {
      await setupCurtain()
      fillSize(0, '6.6', '2.6')
      pickBody('布帘+纱帘')
      // #4566：工艺从加工项派生 ⇒ 勾「韩折」（ERP 名）⇒ 两行都落 `craft='韩褶'`（craftHint）
      toggleProcessingItem('韩折')
      expandCraft()
      // 米数默认 = 主布米数（1 米），可改
      expect((field('纱帘米数') as HTMLInputElement).value).toBe('1')
      fireEvent.change(field('纱帘米数'), { target: { value: '4' } })
      fireEvent.change(field('纱帘单价'), { target: { value: '30' } })

      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

      const items = mockCreateOrder.mock.calls[0][0].items
      expect(items).toHaveLength(2)
      const [main, sheer] = items
      // 主布行：部位缺省即布帘 ⇒ **不写** curtainType（下游 DEFAULT_CURTAIN_TYPE 兜底）
      expect(main.processingInfo.curtainType).toBeUndefined()
      expect(main.productName).toBe('遮光窗帘')
      // 纱帘行：显式写部位 + 与主布行同樘帘 + 不挂加工项 + 不关联主布商品
      expect(sheer.productName).toBe('纱帘')
      expect(sheer.quantity).toBe(4)
      expect(sheer.unitPrice).toBe(30)
      expect(sheer.processingInfo.curtainType).toBe('纱帘')
      // 纱帘是**另一个部位** ⇒ 必须带同一份工艺规格（否则取错路线）
      expect(sheer.processingInfo.craft).toBe('韩褶')
      expect(sheer.processingInfo.craftLineId).toBe(main.processingInfo.craftLineId)
      expect(main.processingInfo.craftLineId).toBeTruthy()
      expect(sheer.processingInfo.fabric_meters).toBe(4)
      expect(sheer.processingInfo.metersSource).toBe('人工指定')
      expect(sheer.processingInfo.processingItems).toBeUndefined()
      expect(sheer.processingInfo.processingFee).toBeUndefined()
      expect(sheer.productId).toBeUndefined()
      // 宽 / 高与主布行同一份（尺寸数量是商品组级属性）
      expect(sheer.width).toBe(6.6)
      expect(sheer.height).toBe(2.6)
    })

    it('判据 7（#4521）：纱帘金额计入订单总额（否则后端「应收 - 优惠 ≈ 实收」会拒单）', async () => {
      await setupCurtain() // 主布 ¥100/米 × 1 米
      pickBody('布帘+纱帘')
      expandCraft()
      fireEvent.change(field('纱帘单价'), { target: { value: '30' } }) // 米数默认 1
      await waitFor(() => {
        expect(screen.getByText('订单金额').closest('div')!.textContent).toContain('¥130.00')
      })
      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
      expect(mockCreateOrder.mock.calls[0][0].actualAmount).toBe(130)
    })

    it('判据 8（#4521）：带纱帘但没填纱帘单价 ⇒ **提交被拦**（不得静默丢掉纱帘行）', async () => {
      await setupCurtain()
      fillSize(0, '6.6', '2.6')
      pickBody('布帘+纱帘')
      await fillCustomerAndSubmit()
      await waitFor(() => {
        expect(screen.getByText(/纱帘单价须大于 0/)).toBeInTheDocument()
      })
      expect(mockCreateOrder).not.toHaveBeenCalled()
    })

    it('判据 9（#4521）：只买纱帘 ⇒ 一行且 `curtainType=纱帘`；用料**手填**（不算料、无公式）', async () => {
      await setupCurtain()
      pickBody('纱帘')
      fillSize(0, '6.6', '2.6')
      openWizardStep('尺寸与数量')
      expect(screen.getByText('纱帘按实际买多少填，不自动算料')).toBeInTheDocument()
      // 没有「恢复按公式计算」入口（纱帘根本没有公式可恢复）
      expect(screen.queryByText('恢复按公式计算')).toBeNull()
      const qtyInput = (await screen.findByText('用料米数'))
        .closest('div')!
        .querySelector('input') as HTMLInputElement
      fireEvent.change(qtyInput, { target: { value: '5' } })

      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
      const items = mockCreateOrder.mock.calls[0][0].items
      expect(items).toHaveLength(1)
      expect(items[0].processingInfo.curtainType).toBe('纱帘')
      expect(items[0].quantity).toBe(5)
      // 部位=纱帘 ⇒ 是否定型默认「否」（真值源 §10 布帘是 / 纱帘否）
      expect(items[0].processingInfo.isShaped).toBe(false)
    })

    it('判据 10（#4521）：售卖形态=布料 ⇒ 不出现帘体 / ①~④（布料单无加工）', async () => {
      await setupCurtain()
      fireEvent.click(
        within(screen.getByRole('radiogroup', { name: '售卖形态' })).getByRole('radio', {
          name: '布料',
        })
      )
      expect(screen.queryByRole('radiogroup', { name: '帘体' })).toBeNull()
      expect(screen.queryByRole('button', { name: /^1 尺寸与数量/ })).toBeNull()
      expect(screen.queryByRole('button', { name: /^2 工艺规格/ })).toBeNull()
    })

    it('判据 11（#4598）：帘行米数输入框 label = 「用料米数」（它就是加工费米数）；布料行仍是「数量」', async () => {
      await setupCurtain()
      openWizardStep('尺寸与数量')

      // 帘（成品）行：label = 「用料米数」—— 这个数就是**加工费米数**
      // （`info.processingMeters = line.quantity`，加工费 = 组合单价 × 它），且由算料写回。
      // 叫「数量」会被商家读成「买几樘 / 几件」，而这个数直接决定加工费。
      const curtainLabel = screen.getByText('用料米数')
      expect(curtainLabel.closest('div')!.querySelector('input')).toBeTruthy()
      // 旁注把口径写出来（商家一眼对得上加工费按哪个数算）
      expect(screen.getByText('= 加工费米数')).toBeInTheDocument()
      // 反向断言：帘行**不得**再留着旧文案「数量」
      expect(screen.queryByText('数量')).toBeNull()

      // 布料行：**按米卖布**（单位由 `sellingMethod` 决定）⇒ 文案保持「数量」，
      // 且**不得**出现「用料米数」—— 两个输入框不是同一个业务，禁止一起改。
      fireEvent.click(
        within(screen.getByRole('radiogroup', { name: '售卖形态' })).getByRole('radio', {
          name: '布料',
        })
      )
      expect(screen.getByText('数量')).toBeInTheDocument()
      expect(screen.queryByText('用料米数')).toBeNull()
      expect(screen.queryByText('= 加工费米数')).toBeNull()
    })
  })

  // ===== #4566：工艺 / 定型改由「加工项」勾选（用户 2026-09-19 裁定）====================
  //
  // 用户逐字：「工艺规格中的**工艺，定型**，对花我觉得**直接通过加工项来勾选**，其他保留，
  // 这样的区分和交互是否更合理？」（已确认采纳：工艺 + 定型 搬进加工项；对花保留）。
  //
  // 硬证据（为什么必须这么改）：加工费组合键的**唯一来源**是
  // `processingInfo.processingItems[].name`（服务端 `ProcessingFeeQueryService.featureNames()`
  // 只读这个数组，**不补工艺**），而 ERP 的 91 项加工费名字全是「工艺+特征」形态
  // （`韩折+超高+定型`）⇒ 只要工艺还留在「工艺规格」里，ERP 的名字一行都匹配不上。
  describe('#4566 工艺 / 定型从加工项派生', () => {
    /** 加工项目录（逐字 = `V83__seed_processing_item_catalog.sql` 的名字 / craftHint） */
    const V83_CATALOG = [
      { id: 'pi-01', name: '打孔', craftHint: '打孔', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      { id: 'pi-02', name: '韩折', craftHint: '韩褶', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      { id: 'pi-06', name: '定型', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      // 自动推导特征：**必须存在于目录**（商家配「加工费组合」要能选到），但不得出手选控件
      { id: 'pi-14', name: '超高', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      { id: 'pi-15', name: '超宽', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      { id: 'pi-16', name: '倒幅', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
    ]

    const setup = async (items: unknown[] = V83_CATALOG) => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
      })
      mockGetProcessingItems.mockResolvedValue({ data: { data: { items } } })
      render(<NewOrderPage />)
      await pickProduct('遮光窗帘')
      await screen.findByText('宽 (米)')
    }

    /** 勾选 / 取消加工项（按**商家所见的名字**定位，不数 checkbox） */
    const toggle = (name: string) => {
      expandProcessing()
      fireEvent.click(screen.getByRole('checkbox', { name }))
    }
    /** 当前**已勾选**的加工项名（目录顺序） */
    const checkedNames = () =>
      screen
        .getAllByRole('checkbox')
        .filter((b) => (b as HTMLInputElement).checked)
        .map((b) => b.getAttribute('aria-label'))
    const pickBody = (body: string) =>
      fireEvent.click(
        within(screen.getByRole('radiogroup', { name: '帘体' })).getByRole('radio', { name: body })
      )
    const submitAndGetInfo = async () => {
      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
      return mockCreateOrder.mock.calls[0][0].items[0].processingInfo as Record<string, unknown>
    }

    it('判据 1：手选列表**不含**自动推导特征（超高/超宽/倒幅）—— 它们仍在只读的自动识别块里', async () => {
      await setup()
      expandProcessing()
      expect(screen.getAllByRole('checkbox').map((b) => b.getAttribute('aria-label'))).toEqual([
        '打孔',
        '韩折',
        '定型',
      ])
      for (const auto of ['超高', '超宽', '倒幅']) {
        expect(screen.queryByRole('checkbox', { name: auto })).toBeNull()
      }
      // 推导结果照旧**只读可见**（来源「推算」），且块内没有任何输入控件
      // ⚠️ issue #4658：该块已从 ③加工项 移到 **②工艺规格** ⇒ 先展开②再断言（手风琴会卸载未展开步骤）
      expandCraft()
      const block = screen.getByTestId('auto-detected-features')
      expect(within(block).getByText('超宽')).toBeInTheDocument()
      expect(within(block).getByText('超高')).toBeInTheDocument()
      expect(block.querySelectorAll('input')).toHaveLength(0)
    })

    it('判据 2：勾「韩折」⇒ 落库 `processingItems[].name` 含「韩折」且 `craft=「韩褶」`（**派生**，不是页面选的）', async () => {
      await setup()
      toggle('韩折')
      const info = await submitAndGetInfo()

      const names = (info.processingItems as Array<{ name: string }>).map((i) => i.name)
      expect(names).toContain('韩折')
      // 名字按 **ERP 逐字**（组合键必须与 ERP 91 项一致）；craft 用 **MIGAO 工艺枚举**（路线键）
      expect(info.craft).toBe('韩褶')
      expect(info.craft).not.toBe('韩折')
    })

    it('判据 3：先勾「打孔」再勾「韩折」⇒ 只剩一个带工艺的项（旧的被自动取消 + toast 说明）', async () => {
      await setup()
      toggle('打孔')
      expect(checkedNames()).toEqual(['打孔', '定型'])

      toggle('韩折')
      // 单值护栏：新的工艺声明生效，旧的**自动取消**（工艺维是单值，两张声明 = 两套工序）
      expect(checkedNames()).toEqual(['韩折', '定型'])
      // **不静默**：必须让商家看见换了哪一个
      expect(toast.info).toHaveBeenCalledWith('一张单只能有一个工艺：已把「打孔」换成「韩折」')

      const info = await submitAndGetInfo()
      const names = (info.processingItems as Array<{ name: string }>).map((i) => i.name)
      expect(names).toContain('韩折')
      expect(names).not.toContain('打孔')
      expect(info.craft).toBe('韩褶')
    })

    it('判据 4：布帘 ⇒ 「定型」默认勾上、`isShaped=true`；纱帘 ⇒ 默认不勾、`isShaped=false`', async () => {
      await setup()
      expandProcessing()
      expect((screen.getByRole('checkbox', { name: '定型' }) as HTMLInputElement).checked).toBe(
        true
      )
      expect((await submitAndGetInfo()).isShaped).toBe(true)
    })

    it('判据 4b：纱帘 ⇒ 「定型」默认不勾、`isShaped=false`（真值源 §10 布帘是 / 纱帘否）', async () => {
      await setup()
      pickBody('纱帘')
      expandProcessing()
      expect((screen.getByRole('checkbox', { name: '定型' }) as HTMLInputElement).checked).toBe(
        false
      )
      expect((await submitAndGetInfo()).isShaped).toBe(false)
    })

    it('判据 4c：商家**手动取消**「定型」后，改帘体不得覆盖（手改留痕）', async () => {
      await setup()
      toggle('定型') // 取消默认勾选（布帘默认是勾上的）⇒ 记下「手动改过」
      pickBody('纱帘')
      pickBody('布帘')
      expandProcessing()
      expect((screen.getByRole('checkbox', { name: '定型' }) as HTMLInputElement).checked).toBe(
        false
      )
      expect((await submitAndGetInfo()).isShaped).toBe(false)
    })

    it('判据 5：工艺规格里**不再渲染**「工艺」「是否定型」控件（红证：修复前两个 radiogroup 存在）', async () => {
      await setup()
      expandCraft()
      expect(screen.queryByRole('radiogroup', { name: '工艺' })).toBeNull()
      expect(screen.queryByRole('radiogroup', { name: '是否定型' })).toBeNull()
      // 「对花」保留（它是**算料输入**：定宽买高时每幅加 1 个花距；ERP 91 项加工费里 0 行含对花）
      expect(screen.getByRole('radiogroup', { name: '是否对花' })).toBeInTheDocument()
    })

    it('判据 6：目录里**没有**「定型」项（老租户未重建目录）⇒ 不报错，且 `isShaped` **不写**', async () => {
      await setup(V83_CATALOG.filter((i) => i.name !== '定型'))
      expandProcessing()
      expect(screen.queryByRole('checkbox', { name: '定型' })).toBeNull()

      const info = await submitAndGetInfo()
      // 三态语义留在「键的缺席」上：后端按缺值处理（与今天「未指定」档同语义），页面**不报错**
      expect(Object.keys(info)).not.toContain('isShaped')
      // 其余链路照常
      expect(info.cuttingMode).toBe('定高买宽')
    })
  })

  // ===== #4576：加工项**一级分类导航 + 关键字搜索**（用户 2026-09-19 追加口径）==================
  //
  // 用户逐字：「加工项**有一级分类**，可以**先选一级分类再选具体加工项**，同时也加**关键字快速搜索**」。
  // 病根：③加工项把店铺级目录的**全部** active 项平铺成一个扁平 checkbox 列表（V83 重建后 16 项、
  // 商家还能继续自建）⇒ 项一多就逐行扫；且「带 craftHint 的工艺项（单选语义）」与其余项
  // 长得一模一样，商家不知道「点了会不会顶掉前面那个」。
  //
  // 复用文件头已声明的用例（**不新增声明**）：OR-035（工艺规格写侧录入 —— 工艺/定型从加工项派生）、
  // OR-014（下单加工项数量规则）。本组判据 = 分类导航 + 搜索 + 「单选」标记，均为这两条的交互承载。
  describe('#4576 加工项分类导航 + 关键字搜索', () => {
    /** 加工项目录：**两个分类**（`加工费` / `安装服务`），工艺项带 `craftHint` */
    const CATEGORIZED_CATALOG = [
      { id: 'pi-01', name: '打孔', craftHint: '打孔', categoryId: 'c1', categoryName: '加工费', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      { id: 'pi-02', name: '韩折', craftHint: '韩褶', categoryId: 'c1', categoryName: '加工费', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      { id: 'pi-06', name: '定型', categoryId: 'c1', categoryName: '加工费', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      { id: 'pi-20', name: '罗马杆安装', categoryId: 'c2', categoryName: '安装服务', pricingMethod: 'per_set', unitPrice: 0, unit: '套' },
    ]

    const setup = async (items: unknown[] = CATEGORIZED_CATALOG) => {
      mockGetProducts.mockResolvedValue({
        data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
      })
      mockGetProduct.mockResolvedValue({
        data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
      })
      mockGetProcessingItems.mockResolvedValue({ data: { data: { items } } })
      render(<NewOrderPage />)
      await pickProduct('遮光窗帘')
      await screen.findByText('宽 (米)')
      expandProcessing()
    }

    /** 第三个分类的填充项 —— 只用来把目录撑到 **> 8 项**（搜索框的出现阈值） */
    const FILLERS = Array.from({ length: 6 }, (_, i) => ({
      id: `pi-x${i}`,
      name: `辅料${i}`,
      categoryId: 'c3',
      categoryName: '辅料',
      pricingMethod: 'per_set',
      unitPrice: 0,
      unit: '套',
    }))
    const SEARCHABLE_CATALOG = [...CATEGORIZED_CATALOG, ...FILLERS]

    /** 当前**可见**的加工项名（DOM 顺序 = 目录顺序） */
    const visibleNames = () =>
      screen.getAllByRole('checkbox').map((b) => b.getAttribute('aria-label'))
    const searchBox = () => screen.getByTestId('processing-search')
    /** 收起③ ⇒ 摘要（`已选 N 项 · 工艺：X`）可见 */
    const collapseProcessing = () =>
      fireEvent.click(screen.getAllByRole('button', { name: /^3 加工项/ })[0])

    it('判据 1a：多分类 ⇒ 渲染分类选择器（每个分类一个 chip，带 data-testid）', async () => {
      await setup()
      expect(screen.getByTestId('processing-category-selector')).toBeInTheDocument()
      expect(screen.getByTestId('processing-category-c1')).toBeInTheDocument()
      expect(screen.getByTestId('processing-category-c2')).toBeInTheDocument()
      // 默认落在**第一类**（目录顺序），其项可见
      expect(visibleNames()).toEqual(['打孔', '韩折', '定型'])
    })

    it('判据 1b：**只有一类** ⇒ 不渲染分类选择器（一个 tab 是噪音），该类项照常平铺', async () => {
      await setup(CATEGORIZED_CATALOG.filter((i) => i.categoryId === 'c1'))
      expect(screen.queryByTestId('processing-category-selector')).toBeNull()
      expect(visibleNames()).toEqual(['打孔', '韩折', '定型'])
    })

    it('判据 1c：目录**没配分类** ⇒ 不渲染选择器、不报错，全部平铺（老租户目录）', async () => {
      await setup([
        { id: 'pi-01', name: '打孔', craftHint: '打孔', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
        { id: 'pi-06', name: '定型', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      ])
      expect(screen.queryByTestId('processing-category-selector')).toBeNull()
      expect(visibleNames()).toEqual(['打孔', '定型'])
    })

    it('判据 2：选分类 ⇒ 只显示该分类下的加工项', async () => {
      await setup()
      expect(visibleNames()).toEqual(['打孔', '韩折', '定型'])

      fireEvent.click(screen.getByTestId('processing-category-c2'))
      expect(visibleNames()).toEqual(['罗马杆安装'])

      fireEvent.click(screen.getByTestId('processing-category-c1'))
      expect(visibleNames()).toEqual(['打孔', '韩折', '定型'])
    })

    it('判据 3：搜索**跨分类**命中（并标出所属分类）；清空后回到当前选中的分类', async () => {
      await setup(SEARCHABLE_CATALOG)
      // 先停在第二类，再搜索第一类的项 ⇒ 命中即跨分类展示
      fireEvent.click(screen.getByTestId('processing-category-c2'))
      expect(visibleNames()).toEqual(['罗马杆安装'])

      fireEvent.change(searchBox(), { target: { value: '打孔' } })
      expect(visibleNames()).toEqual(['打孔'])
      // 结果里标出它属于哪个分类（「打孔」在 `加工费` 下）
      const chip = screen.getByRole('checkbox', { name: '打孔' }).closest('div')!
      expect(chip.textContent).toContain('加工费')

      // 清空 ⇒ 回到**当前选中的分类**（c2），而不是全部平铺
      fireEvent.change(searchBox(), { target: { value: '' } })
      expect(visibleNames()).toEqual(['罗马杆安装'])
    })

    it('判据 4：搜索过滤**不动**已选状态；被过滤掉但已选的项**仍在**提交 payload 里', async () => {
      await setup(SEARCHABLE_CATALOG)
      fireEvent.click(screen.getByRole('checkbox', { name: '打孔' }))

      // 过滤掉「打孔」⇒ 控件里没有它，但勾选态还在（过滤只影响渲染）
      fireEvent.change(searchBox(), { target: { value: '罗马' } })
      expect(screen.queryByRole('checkbox', { name: '打孔' })).toBeNull()
      fireEvent.change(searchBox(), { target: { value: '' } })
      expect((screen.getByRole('checkbox', { name: '打孔' }) as HTMLInputElement).checked).toBe(
        true
      )

      // 再把它过滤掉后提交 ⇒ payload 仍带着它（唯一构造点 `processingDetailsOf` 只读勾选态）
      fireEvent.change(searchBox(), { target: { value: '罗马' } })
      await fillCustomerAndSubmit()
      await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
      const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo as Record<
        string,
        unknown
      >
      const names = (info.processingItems as Array<{ name: string }>).map((i) => i.name)
      expect(names).toContain('打孔')
    })

    it('判据 5：「单选」标记**只**出现在带 `craftHint` 的工艺项上，且配一句换选提示', async () => {
      await setup()
      // 工艺项（打孔 / 韩折）有标记；手选特征（定型）没有
      expect(screen.getByTestId('processing-single-badge-pi-01')).toBeInTheDocument()
      expect(screen.getByTestId('processing-single-badge-pi-02')).toBeInTheDocument()
      expect(screen.queryByTestId('processing-single-badge-pi-06')).toBeNull()
      expect(screen.getByText(/换选会自动取消前一个/)).toBeInTheDocument()

      // 切到**没有工艺项**的分类 ⇒ 标记与提示句都不出现（不误导）
      fireEvent.click(screen.getByTestId('processing-category-c2'))
      expect(screen.queryByTestId('processing-single-badge-pi-20')).toBeNull()
      expect(screen.queryByText(/换选会自动取消前一个/)).toBeNull()
    })

    it('判据 6（回归）：工艺单值护栏不变 —— 勾第二个工艺项 ⇒ 自动取消前一个 + toast 说明', async () => {
      await setup()
      fireEvent.click(screen.getByRole('checkbox', { name: '打孔' }))
      fireEvent.click(screen.getByRole('checkbox', { name: '韩折' }))
      expect((screen.getByRole('checkbox', { name: '打孔' }) as HTMLInputElement).checked).toBe(
        false
      )
      expect((screen.getByRole('checkbox', { name: '韩折' }) as HTMLInputElement).checked).toBe(
        true
      )
      expect(toast.info).toHaveBeenCalledWith('一张单只能有一个工艺：已把「打孔」换成「韩折」')
    })

    it('判据 7（回归）：自动推导特征仍**不在**手选控件里（分类目录下也一样）', async () => {
      await setup([
        ...CATEGORIZED_CATALOG,
        { id: 'pi-14', name: '超高', categoryId: 'c1', categoryName: '加工费', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
        { id: 'pi-15', name: '超宽', categoryId: 'c1', categoryName: '加工费', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
        { id: 'pi-16', name: '倒幅', categoryId: 'c1', categoryName: '加工费', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
      ])
      expect(visibleNames()).toEqual(['打孔', '韩折', '定型'])
      for (const auto of ['超高', '超宽', '倒幅']) {
        expect(screen.queryByRole('checkbox', { name: auto })).toBeNull()
      }
      // 推导结果照旧**只读可见**，且块内无任何输入控件
      // ⚠️ issue #4658：该块已从 ③加工项 移到 **②工艺规格** ⇒ 先展开②再断言
      expandCraft()
      const block = screen.getByTestId('auto-detected-features')
      expect(within(block).getByText('超宽')).toBeInTheDocument()
      expect(block.querySelectorAll('input')).toHaveLength(0)
    })

    it('判据 8a：项数 ≤ 8 ⇒ **不出现**搜索框（项少时搜索是噪音）', async () => {
      await setup()
      expect(screen.queryByTestId('processing-search')).toBeNull()
    })

    it('判据 8b：项数 > 8 ⇒ 出现搜索框（带 data-testid + aria-label）', async () => {
      await setup(SEARCHABLE_CATALOG)
      const box = searchBox()
      expect(box).toHaveAttribute('aria-label', '搜索加工项')
      // 过滤即时生效（子串匹配）
      fireEvent.change(box, { target: { value: '辅料3' } })
      expect(visibleNames()).toEqual(['辅料3'])
      // 无命中 ⇒ 显式空态（不静默留白）
      fireEvent.change(box, { target: { value: '不存在的项' } })
      expect(screen.getByText('没有匹配的加工项')).toBeInTheDocument()
    })

    it('判据 9a：已选摘要带出**工艺名**（`已选 N 项 · 工艺：X`）', async () => {
      // 去掉「定型」⇒ 布帘默认勾选不会占一格，计数只反映手选的工艺项
      await setup(CATEGORIZED_CATALOG.filter((i) => i.name !== '定型'))
      fireEvent.click(screen.getByRole('checkbox', { name: '韩折' }))
      collapseProcessing()
      // 工艺取**派生值**（`craftHint`）—— 与②工艺规格摘要同一个取值点
      expect(screen.getByText('已选 1 项 · 工艺：韩褶')).toBeInTheDocument()
    })

    it('判据 9b：没选工艺项 ⇒ 摘要只写「已选 N 项」（不出现空的「工艺：」）', async () => {
      await setup()
      // 布帘 ⇒ 「定型」默认勾上（1 项，无 `craftHint`）
      collapseProcessing()
      expect(screen.getByText('已选 1 项')).toBeInTheDocument()
    })
  })
})
