// case_ids: OR-008, OR-036
/**
 * 订单侧「明细 → 匹配候选 → 选品 → 建订单行」的**页面接线**（issue #5345）。
 *
 * 纯函数半边见 `tests/unit/lib/order-line-match.test.ts`；本文件只钉**用户看得见的那一段**：
 *
 * | 判据 | 页面断言 |
 * |---|---|
 * | 1 不猜商品 | 识别到明细 ⇒ 先出**选品面板**（不是直接建行）；匹配不到 ⇒ 只有「都不是」+ **0 行** |
 * | 2 候选可解释 | 每个候选旁边**读得到理由**（相似度 / 规格命中） |
 * | 3 来源可区分 | 建出来的行带 `[图片识别]` 徽标（`recognized-marker-line-*`） |
 * | 4 不落库 | 本文件**任何一步都不触发**建单端点（全程 `mockCreateOrder` 零调用） |
 * | 6 单价来自 SKU | 单价框 = SKU 价 88（图上写的「120元」不作数） |
 * | 7 用户复核 | 选品前无行；选品后可**就地改**数量 / 单价（改完仍是我的值） |
 *
 * ⚠️ 触发通道取**深通道**（`mibao:page-fill` 内存事件）而不是上传按钮：两者最终都进
 * `handleRecognized`（同一条映射），但前者不需要替身上传端点 —— 判据不变、夹具更短。
 * 快通道的字段来源口径由 `image-recognize.test.ts` / `agent-page-fill.test.ts` 各自钉住。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'

// Mock API —— 与 `orders-new-decoupled.test.tsx` 同一套替身（本文件再补选品要用的两个端点）
const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...args: any[]) => mockCreateOrder(...args) },
  productApi: {
    getProducts: (...args: any[]) => mockGetProducts(...args),
    getProduct: (...args: any[]) => mockGetProduct(...args),
  },
  processingItemApi: { getProcessingItems: (...args: any[]) => mockGetProcessingItems(...args) },
  customerApi: { getCustomers: () => Promise.resolve({ data: { data: { items: [], total: 0 } } }) },
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
              meters_rounding_step: 0.1,
            },
          },
        },
      }),
  },
  craftCalcApi: { preview: () => new Promise(() => {}) },
  autoFeaturesApi: {
    preview: () =>
      Promise.resolve({
        data: {
          data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' },
        },
      }),
  },
  // 门幅规则（issue #5043 包 2b，服务端）：本文件的商品只有一个规格 ⇒ 规则面不参与判据
  doorWidthPlanApi: {
    preview: () =>
      Promise.resolve({
        data: {
          data: {
            state: 'undecidable',
            code: 'missing-size',
            effective_cutting_mode: null,
            door_width: null,
            panels: null,
            splice: false,
            verdict: 'unknown',
            suggestion: null,
            reason: '',
          },
        },
      }),
  },
  feePreviewApi: { preview: () => Promise.resolve({ data: { data: { items: [], processingFeeTotal: 0 } } }) },
  // 识别端点（本文件不经上传按钮，替身只为模块可解析）
  imageRecognizeApi: { recognize: () => Promise.resolve({ data: { data: { fields: [] } } }) },
  uploadApi: { uploadImage: () => Promise.resolve({ data: { data: { url: '' } } }) },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'
import { PAGE_FILL_EVENT, PAGE_FILL_COMPONENT, PAGE_FILL_SOURCE_RECOGNIZED } from '@/lib/agent-page-fill'
import { NO_MATCH_CHOICE } from '@/lib/order-line-match'

/** 「都不是」选项的 testid（**从常量拼**，不写死 `__none__` 字面量 —— 免得口径漂移） */
const noneOption = (index: number) => `order-line-picker-option-${index}-${NO_MATCH_CHOICE}`

/** 识别内核订单侧的**真实产出形态**：`items` 是顿号分隔的名称清单 */
const ITEMS_TEXT = '雪尼尔遮光窗帘、棉麻窗帘'

const CATALOG = [
  {
    id: 'p1',
    name: '雪尼尔遮光窗帘',
    categoryId: 'c1',
    categoryName: '成品帘',
    price: 88,
    unit: '米',
    status: 'on_sale',
    images: [],
    specifications: { 材质: '雪尼尔' },
  },
]

const PRODUCT_DETAIL = { ...CATALOG[0], skus: [{ id: 's1', colorId: 'col1', colorName: '藏青', doorWidth: '2.8', price: 88, stock: 10 }] }

function pageFillPlan() {
  return {
    component: PAGE_FILL_COMPONENT,
    target_type: 'order',
    fields: [
      { key: 'items', label: '商品明细', value: ITEMS_TEXT, source: PAGE_FILL_SOURCE_RECOGNIZED, reason: null, candidates: [], note: null, note_source: null },
      { key: 'quantity', label: '数量', value: '8米', source: PAGE_FILL_SOURCE_RECOGNIZED, reason: null, candidates: [], note: null, note_source: null },
    ],
  }
}

/** 把识别计划推给**当前页面**（深通道 = 内存事件；`emitPageFill` 的同一条路径） */
async function recognize() {
  await act(async () => {
    window.dispatchEvent(new CustomEvent(PAGE_FILL_EVENT, { detail: pageFillPlan() }))
  })
}

const priceInputs = () => screen.queryAllByLabelText('单价 (¥/米)') as HTMLInputElement[]

describe('NewOrderPage — 明细 → 候选 → 选品 → 建订单行（#5345）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({ data: { data: { items: CATALOG, total: 1 } } })
    mockGetProduct.mockResolvedValue({ data: { data: PRODUCT_DETAIL } })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
  })

  it('判据 1/2/7：识别到明细先出**选品面板**（候选 + 理由 + 「都不是」），选品前一行都不建', async () => {
    render(<NewOrderPage />)
    await recognize()

    const panel = await screen.findByTestId('order-line-picker')
    // 两条明细 ⇒ 两条待选（N 条明细 ⇒ N 个候选，不是直接建 N 行）
    expect(screen.getByTestId('order-line-picker-entry-0')).toBeInTheDocument()
    expect(screen.getByTestId('order-line-picker-entry-1')).toBeInTheDocument()
    // 判据 2：理由**用户读得到**（相似度 / 规格命中），不是黑箱
    const reason = screen.getByTestId('order-line-picker-reason-0-p1')
    expect(reason.textContent || '').toMatch(/相似|重合|包含/)
    expect(reason.textContent || '').toMatch(/雪尼尔/)
    // 判据 1：「都不是」恒在
    expect(screen.getByTestId(noneOption(0))).toBeInTheDocument()
    // 判据 7：这一刻**还没有**任何识别建的行（单价框一个都没有 = 新行还没建）
    expect(priceInputs()).toHaveLength(0)
    expect(screen.queryAllByTestId(/^recognized-marker-line-/)).toHaveLength(0)
    // 判据 4：全程不落库
    expect(mockCreateOrder).not.toHaveBeenCalled()
    expect(panel).toBeInTheDocument()
  })

  it('判据 3/6/7：选品 ⇒ 建行（带 [图片识别] 徽标 + 单价取 SKU 价）且可就地改', async () => {
    render(<NewOrderPage />)
    await recognize()

    fireEvent.click(await screen.findByTestId('order-line-picker-option-0-p1'))

    // 建行：识别来源徽标挂在**那一行**上
    await waitFor(() => {
      expect(screen.getAllByTestId(/^recognized-marker-line-/).length).toBeGreaterThan(0)
    })
    // 判据 6：单价 = SKU 价 88（图上/备注里的数不作数）
    const [price] = priceInputs()
    expect(price).toBeTruthy()
    expect(Number(price.value)).toBe(88)
    // 判据 7：可就地改（改完仍是我的值 —— 不被任何推导静默改回）
    fireEvent.change(price, { target: { value: '99' } })
    expect(Number(priceInputs()[0].value)).toBe(99)
    // 判据 4：建行 ≠ 落库 —— 建单端点一次都没被调用
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('判据 1/4：「都不是」⇒ **不建行**，明细留在备注（原行为不变）', async () => {
    render(<NewOrderPage />)
    await recognize()

    fireEvent.click(await screen.findByTestId(noneOption(0)))

    // 第 1 条已跳过（该条不建行），但第 2 条**还在等商家选** ⇒ 面板留着
    expect(await screen.findByTestId('order-line-picker-resolved-0')).toBeInTheDocument()
    expect(screen.getByTestId('order-line-picker-entry-1')).toBeInTheDocument()
    // 「都不建行（跳过剩余）」⇒ 面板关闭，全程 0 行
    fireEvent.click(screen.getByTestId('order-line-picker-skip-all'))
    await waitFor(() => {
      expect(screen.queryByTestId('order-line-picker')).not.toBeInTheDocument()
    })
    // 不建行：依然没有识别建的行
    expect(priceInputs()).toHaveLength(0)
    expect(screen.queryAllByTestId(/^recognized-marker-line-/)).toHaveLength(0)
    // 「留在备注」：明细原文仍在备注里（不因为"跳过"就丢掉图上的信息）
    const remark = screen.getByPlaceholderText(/可填写发货要求/) as HTMLTextAreaElement
    expect(remark.value).toContain('雪尼尔遮光窗帘')
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('候选查询失败 ⇒ fail-closed：仍给「都不是」，仍然**不建行**（不猜）', async () => {
    mockGetProducts.mockRejectedValue(new Error('网络错误'))
    render(<NewOrderPage />)
    await recognize()

    // 面板照旧打开（商家要有"都不是"这个出口），只是没有候选
    expect(await screen.findByTestId(noneOption(0))).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('order-line-picker-skip-all'))
    await waitFor(() => {
      expect(screen.queryByTestId('order-line-picker')).not.toBeInTheDocument()
    })
    expect(priceInputs()).toHaveLength(0)
    expect(mockGetProduct).not.toHaveBeenCalled() // 没选品 ⇒ 连详情都不取
  })
})