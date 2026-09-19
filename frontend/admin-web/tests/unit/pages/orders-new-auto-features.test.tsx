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
      const block = screen.getByTestId('auto-detected-features')
      expect(within(block).queryByText('超宽')).toBeNull()
      expect(within(block).queryByText('超高')).toBeNull()
      // 缺省 cuttingMode = 定高买宽 ⇒ 正幅
      expect(within(block).getByText('正幅')).toBeInTheDocument()
    })
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
})
