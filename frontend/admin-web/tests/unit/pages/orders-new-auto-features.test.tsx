// case_ids: OR-040
// @vitest-environment jsdom
/**
 * 下单页「自动识别」只读展示（issue #4526 包 B · 设计文档 §5.1/§5.2 / §9 判据 8）。
 *
 * 用户 2026-09-19：「超高 / 超宽是和门幅标准比较的，客户报的数据和门幅对比后能自动区分出来
 * 是超高还是超宽，**这个要求做到自动识别**」。
 *
 * 判据：③加工项步骤里出现**只读**的「自动识别」块（标来源「推算」），内容随宽/高/门幅/cuttingMode
 * 变化；且**不是**可勾选项（没有自动识别的 checkbox），`已选 N 项` 只数商家手选的加工项。
 *
 * 红证（实现前）：页面无「自动识别」块 ⇒ `findByTestId('auto-detected-features')` 超时即红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: () => new Promise(() => {}) },
  feePreviewApi: {
    preview: () =>
      Promise.resolve({
        data: {
          data: {
            items: [
              {
                processingFee: 0,
                processingFeeDetail: { fee_source: 'unpriced', amount: 0, hint: '去定价' },
              },
            ],
            processingFeeTotal: 0,
          },
        },
      }),
  },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

const openStep = (title: string) => {
  const btn = screen.getAllByRole('button', { name: new RegExp(`^\\d+ ${title}`) })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

/** 选商品（SKU 可带门幅）→ 填宽高 */
async function setupLine(opts: { doorWidth?: string; width?: string; height?: string } = {}) {
  const { doorWidth, width = '6.6', height = '2.6' } = opts
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({
    data: {
      data: {
        id: 'p1',
        name: '遮光窗帘',
        price: 100,
        skus: [
          {
            id: 'sku1',
            colorId: 'c1',
            colorName: '米白',
            doorWidth,
            price: 100,
            sellingMethod: 'bulk_cut',
          },
        ],
      },
    },
  })

  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('宽 (米)')
  // 有 SKU 时必须先选颜色 + 门幅（都是 chips 按钮），宽高输入才跟着该 SKU 走
  if (doorWidth) {
    fireEvent.click(await screen.findByRole('button', { name: '米白' }))
    fireEvent.click(await screen.findByText(doorWidth))
  }
  openStep('尺寸与数量')
  fireEvent.change(inputOf('宽 (米)'), { target: { value: width } })
  fireEvent.change(inputOf('高 (米)'), { target: { value: height } })
  openStep('加工项')
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetProcessingItems.mockResolvedValue({
    data: {
      data: {
        items: [
          { id: 'pi1', name: '打孔加工', pricingMethod: 'per_meter', unitPrice: 5, unit: '米' },
        ],
      },
    },
  })
  mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
})

describe('D6：自动识别结果只读可见（判据 8）', () => {
  it('6.6×2.6 对缺省门幅 2.8 ⇒ 自动识别出「超宽 + 超高」，并标来源「推算」', async () => {
    await setupLine()

    const block = await screen.findByTestId('auto-detected-features')
    expect(within(block).getByText('超宽')).toBeInTheDocument()
    expect(within(block).getByText('超高')).toBeInTheDocument()
    // 照实标注：推理非实证（设计 §5.2）—— **每条**特征都带来源标注
    const chips = block.querySelectorAll('span[title]')
    expect(chips.length).toBeGreaterThanOrEqual(2)
    for (const chip of Array.from(chips)) {
      expect(chip.textContent).toContain('（推算）')
      expect(chip.getAttribute('title')).toBeTruthy()
    }
  })

  it('改宽高 ⇒ 识别结果跟着变（不是写死的展示文案）', async () => {
    await setupLine()
    await screen.findByTestId('auto-detected-features')

    openStep('尺寸与数量')
    fireEvent.change(inputOf('宽 (米)'), { target: { value: '1.5' } })
    fireEvent.change(inputOf('高 (米)'), { target: { value: '1.5' } })
    openStep('加工项')

    await waitFor(() => {
      expect(screen.queryByText('超宽')).toBeNull()
      expect(screen.queryByText('超高')).toBeNull()
    })
    // 缺省 cuttingMode = 定高买宽（= 正幅）⇒ #4592 起**不推导任何特征** ⇒ 只读块整块不渲染。
    // 红证（修复前必红）：修复前这里恒有「正幅」，而「正幅」不在加工项目录里 ⇒
    // 默认订单的组合键永远匹配不到价 ⇒ 加工费恒 ¥0.00。
    expect(screen.queryByText('正幅')).toBeNull()
    expect(screen.queryByTestId('auto-detected-features')).toBeNull()
  })

  it('门幅 = SKU.doorWidth：1.5 高 × 1.0 宽 对 2.8 门幅不超，对 1.4 窄幅门幅判超高', async () => {
    await setupLine({ doorWidth: '1.4米', width: '1.0', height: '1.5' })

    const block = await screen.findByTestId('auto-detected-features')
    expect(within(block).getByText('超高')).toBeInTheDocument()
    expect(within(block).queryByText('超宽')).toBeNull()
  })

  it('自动识别结果**不是**可勾选项（没有它的 checkbox），也不计入「已选 N 项」', async () => {
    await setupLine()

    const block = await screen.findByTestId('auto-detected-features')
    expect(block.querySelectorAll('input')).toHaveLength(0)
    // 一个手选加工项都没勾 ⇒ 摘要必须是「未选」（自动特征不算手选）
    expect(screen.getByText('未选')).toBeInTheDocument()
  })

  // issue #4566（用户 2026-09-19 裁定「工艺规格中的**工艺，定型**……直接通过加工项来勾选」）：
  // 加工项目录里的**自动推导特征**（超高/超宽/倒幅）**必须存在**（商家配「加工费组合」时要能选到
  // `韩折+超高+定型` 这种名字），但**下单页的手选控件必须没有它们**（判据 8：手选项 ⇒ 红）。
  // 单一真值 = `lib/craft-auto-features.ts` 的 `AUTO_FEATURE_NAMES`（页面不抄第二份名字数组）。
  it('#4566 目录里的「超高/超宽/倒幅」**不出手选控件**（只出现在只读的自动识别块里）', async () => {
    mockGetProcessingItems.mockResolvedValue({
      data: {
        data: {
          items: [
            { id: 'pi-02', name: '韩折', craftHint: '韩褶', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-06', name: '定型', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-14', name: '超高', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-15', name: '超宽', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
            { id: 'pi-16', name: '倒幅', pricingMethod: 'per_meter', unitPrice: 0, unit: '米' },
          ],
        },
      },
    })
    await setupLine()

    // 手选列表 = 目录 − 自动推导特征（红证：修复前这里会出现 5 个 checkbox）
    expect(screen.getAllByRole('checkbox').map((b) => b.getAttribute('aria-label'))).toEqual([
      '韩折',
      '定型',
    ])
    for (const auto of ['超高', '超宽', '倒幅']) {
      expect(screen.queryByRole('checkbox', { name: auto })).toBeNull()
    }
    // 推导结果照旧**只读可见**（6.6×2.6 对缺省门幅 2.8 ⇒ 超宽 + 超高），块内无任何输入控件
    const block = await screen.findByTestId('auto-detected-features')
    expect(within(block).getByText('超宽')).toBeInTheDocument()
    expect(within(block).getByText('超高')).toBeInTheDocument()
    expect(block.querySelectorAll('input')).toHaveLength(0)
  })

  /**
   * 🔴 issue #4592（P0）的用户可见症状的**落库面**判据：默认「定高买宽」订单的组合键
   * （= `processingInfo.processingItems[].name`，服务端 `featureNames()` 的唯一来源）
   * **不得**含 `正幅` —— 它不在 `processing_items` 目录（V83）里 ⇒ 商家配不出含它的组合
   * ⇒ 组合价永远匹配不到 ⇒ 加工费恒 ¥0.00。
   *
   * 红证（修复前必红）：修复前这里得到 `['超宽','超高','正幅']`（默认档 = 定高买宽）。
   */
  it('#4592 默认「定高买宽」订单落库的组合加项 = {超宽, 超高}，**不含「正幅」**', async () => {
    // 带门幅 ⇒ setupLine 会连颜色 + 规格一起选上（缺颜色会被页面校验拦在提交前）
    await setupLine({ doorWidth: '2.8米' })

    fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
      target: { value: '13800138000' },
    })
    fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), {
      target: { value: '杭州市' },
    })
    // 加工费计价闸门（#4450）：未就绪时提交会被拦 ⇒ 先等计价落地（真实商家也是看到金额才提交）
    await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
    fireEvent.click(screen.getByText('提交订单'))
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())

    const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo as {
      processingItems: Array<{ name: string }>
    }
    expect(info.processingItems.map((i) => i.name)).toEqual(['超宽', '超高'])
    expect(info.processingItems.map((i) => i.name)).not.toContain('正幅')
  })
})
