// case_ids: OR-039
// @vitest-environment jsdom
/**
 * 下单页「费用明细」展示面（issue #4526 包 B · 设计文档 §4.3 / §9 判据 4·5）。
 *
 * 用户 2026-09-19：
 * ① 「订单上的**加工项选择控件不要展示加工项单价**」；
 * ② 「选择了特殊选项后，也要算入**费用明细**」。
 *
 * 判据：
 * - ③加工项控件里**没有任何单价文本**（`¥x.xx / 米`、`/ 套`、行金额都不出现）；
 * - ④费用明细出现**特殊选项行**，且逐行之和 **=== 订单金额**（同一真值，不双算）；
 * - ⑤`priced:false` 的选项显式标「未定价（按 0 计）」。
 *
 * 红证（实现前）：① 控件渲染 `¥5.00 / 米` 与选中后的 `3米 · ¥15.00` ⇒ 判据 ③ 红；
 * ② 页面不读 `special_options` ⇒ 特殊选项行不出现 ⇒ 判据 ④ 红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockFeePreview = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  // 算料试算与「费用明细展示」正交 ⇒ 停在进行中（避免改写数量污染判据）
  craftCalcApi: { preview: () => new Promise(() => {}) },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
  // **算料配置读面**（issue #4874）：公式缺省 + 档位 chips 的值域/文案都来自它 ⇒ 挂载即请求
  productionApi: {
    getCraftCalcConfig: () =>
      Promise.resolve({
        data: {
          data: {
            source: 'default',
            config: {
              per_fold_single: 0.25,
              per_fold_mixed_times: {},
              margin_single: 0.3,
              margin_multi: 0.3,
              min_fullness: 1.5,
              tiers: { standard: { fullness: 2.0, label: '标准档' } },
              default_formula: 'pleat',
              side_margin: 0.15,
              meters_rounding_step: 0.1,
            },
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

/** 服务端取价：组合 ¥10/米 × 1 米 = ¥10；特殊选项「加铅块」¥6/套 × 1 套 = ¥6 */
const feeWithSpecialOption = () => ({
  data: {
    data: {
      items: [
        {
          processingFee: 16,
          processingFeeDetail: {
            composition: '打孔加工',
            unit_price: 10,
            meters: 1,
            meters_source: 'processingMeters',
            fee_source: 'matched',
            amount: 10,
            hint: null,
            special_options: [
              { name: '加铅块', unit_price: 6, sets: 1, amount: 6, priced: true },
            ],
            special_options_total: 6,
          },
        },
      ],
      processingFeeTotal: 16,
    },
  },
})

/** 未定价的特殊选项（`priced:false`）—— 必须显式可见，不许静默按 0 收 */
const feeWithUnpricedOption = () => ({
  data: {
    data: {
      items: [
        {
          processingFee: 10,
          processingFeeDetail: {
            unit_price: 10,
            meters: 1,
            fee_source: 'matched',
            amount: 10,
            special_options: [
              { name: '加铅块', unit_price: null, sets: 1, amount: 0, priced: false },
            ],
            special_options_total: 0,
          },
        },
      ],
      processingFeeTotal: 10,
    },
  },
})

const expandProcessing = () => {
  const btn = screen.getAllByRole('button', { name: /^\d+ 加工项/ })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

/** 选商品 → 填宽高（默认门幅缺省 2.8 ⇒ 6.6×2.6 会自动识别出超宽 + 超高）→ 勾一个加工项 */
async function setupLine() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('宽 (米)')
  fireEvent.change(inputOf('宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('高 (米)'), { target: { value: '2.6' } })
  expandProcessing()
  fireEvent.click(await screen.findByRole('checkbox'))
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
}

/** 一行加工项的完整文本（含数量/金额，若还残留的话） */
const processingRowText = () => screen.getByRole('checkbox').closest('div')!.textContent || ''

/**
 * 订单金额那一行的数字。
 * ⚠️ 用 `parentElement`（= flex 行容器）而不是 `closest('div')`：后者会一路爬到
 * `<dl>`（整个费用汇总块），`lastElementChild` 就成了「实收款」块。
 */
const orderAmountText = () =>
  screen.getByText('订单金额').parentElement!.textContent || ''

/**
 * 从一段文本里取出**最后一个**金额（判据按**数**比，不按字符串比）。
 * 注意 `订单金额` 那一行是 `订单金额¥110.00`（标签 + 值）⇒ 必须剥掉非数字字符。
 */
const parseAmount = (text: string): number => {
  const matches = text.match(/-?[\d,]+(?:\.\d+)?/g)
  if (!matches) return Number.NaN
  return Number(matches[matches.length - 1].replace(/,/g, ''))
}

/**
 * 费用明细里某一行的金额。
 * CostRow 的 DOM：`<div flex>` → `<span>（<span>label</span><span>expr</span>）</span>` + `<span>金额</span>`
 * ⇒ 从 label 往上一层拿到「左侧 span」，再上一层才是含金额的行容器。
 */
/** 费用明细卡片（issue #4874：「特殊选项」选择器与「加工项」同处区块 2 ⇒ 同名文本会重名，
 * 断言必须限定在费用明细卡片内，否则会误命中**选择器**里的同名选项） */
const feeCard = (): HTMLElement =>
  screen.getByText('费用明细').closest('div')!.parentElement as HTMLElement

const costRowAmount = (label: string): number => {
  const row = within(feeCard()).getByText(label).parentElement!.parentElement!
  return parseAmount(row.lastElementChild!.textContent || '')
}

beforeEach(() => {
  vi.clearAllMocks()
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
          { id: 'pi1', name: '打孔加工', unit: '米' },
        ],
      },
    },
  })
  mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
  mockFeePreview.mockResolvedValue(feeWithSpecialOption())
})

describe('R10：加工项选择控件不出现任何单价文本（判据 4）', () => {
  it('未勾选时：控件里没有 `¥x.xx / 米`（价格只在组合上，逐项单价必然误导）', async () => {
    await setupLine()

    const rowText = processingRowText()
    expect(rowText).toContain('打孔加工')
    expect(rowText).not.toContain('¥')
    expect(rowText).not.toMatch(/\/\s*米/)
    expect(rowText).not.toMatch(/\/\s*套/)
  })

  it('勾选后：控件里仍没有金额，但**数量 + 单位**可对账（摘的是钱，不是数量）', async () => {
    await setupLine()

    const rowText = processingRowText()
    expect(rowText).toContain('打孔加工')
    expect(rowText).toContain('米') // 数量单位仍在（可核对勾了什么）
    expect(rowText).not.toContain('¥')
  })
})

describe('R2：费用明细出现特殊选项行，且合计 === 订单金额（判据 5）', () => {
  it('特殊选项逐项成行：`名称` + `单价/套 × 套数` + 金额', async () => {
    await setupLine()

    // 特殊选项行（label = 选项名，不是「加工」）：算式 + 金额
    const optionRow = within(feeCard()).getByText('加铅块').parentElement!.parentElement!
    expect(optionRow.textContent).toContain('¥6.00/套 × 1 套')
    expect(costRowAmount('加铅块')).toBe(6)
  })

  it('加工行金额 = 组合那半（¥10），不是整个 processingFee（¥16）—— 否则与特殊选项行双算', async () => {
    await setupLine()

    expect(costRowAmount('加工')).toBe(10)
  })

  it('费用明细逐行之和 === 订单金额（同一真值，不出现第二份口径）', async () => {
    await setupLine()

    // 商品（1 米 × ¥100/米 = 100）+ 加工（组合 10）+ 特殊选项（6）= 116
    const sum =
      costRowAmount('商品') + costRowAmount('加工') + costRowAmount('加铅块')
    expect(sum).toBe(116)
    expect(parseAmount(orderAmountText())).toBe(116)
  })

  it('`priced:false` 的选项显式标「未定价（按 0 计）」（不许静默）', async () => {
    mockFeePreview.mockResolvedValue(feeWithUnpricedOption())
    await setupLine()

    const optionRow = within(feeCard()).getByText('加铅块').parentElement!.parentElement!
    expect(optionRow.textContent).toContain('未定价（按 0 计）')
    // 未定价按 0 计 ⇒ 订单金额仍等于逐行之和（不静默改数）
    expect(parseAmount(orderAmountText())).toBe(
      costRowAmount('商品') + costRowAmount('加工')
    )
  })

  it('没选特殊选项（空数组）⇒ 不出现特殊选项块，加工行金额 = 整个 processingFee', async () => {
    mockFeePreview.mockResolvedValue({
      data: {
        data: {
          items: [
            {
              processingFee: 10,
              processingFeeDetail: {
                unit_price: 10,
                meters: 1,
                fee_source: 'matched',
                amount: 10,
                special_options: [],
                special_options_total: 0,
              },
            },
          ],
          processingFeeTotal: 10,
        },
      },
    })
    await setupLine()

    // ⚠️ 限定在费用明细卡片内：区块 2 的「特殊选项」选择器里**照常**有「加铅块」按钮（那是录入控件）
    expect(within(feeCard()).queryByText('加铅块')).toBeNull()
    expect(costRowAmount('加工')).toBe(10)
    expect(parseAmount(orderAmountText())).toBe(costRowAmount('商品') + 10)
  })
})
