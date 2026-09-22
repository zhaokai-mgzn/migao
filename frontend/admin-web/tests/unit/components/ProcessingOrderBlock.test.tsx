// @vitest-environment jsdom
// case_ids: PG-001, PG-005, PG-019, UI-019, UI-030, PR-057, PR-065

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
// 冻结墙钟（issue #4761 第 3 条）：辅助函数 `todayLocal()` 用 `new Date()` 造「今天」，
// 组件在**渲染时刻**、断言在**断言时刻**各取一次 ⇒ 跨午夜必红。
// 修法：与页面**同一真值源**（冻结后的系统时钟）派生「今天」，两个时刻不可能跨日。
// ⚠️ 冻结走独立模块（`import` 声明会被提升 ⇒ 写在文件里「先冻结后导入」不成立）。
import { FROZEN_NOW } from '../helpers/frozen-clock'
import ProcessingOrderBlock from '@/components/orders/ProcessingOrderBlock'

vi.mock('@/lib/api', () => ({
  processingOrderApi: {
    detail: vi.fn(),
    generate: vi.fn(),
    update: vi.fn(),
  },
  batchStockApi: {
    candidates: vi.fn(),
  },
}))

import { processingOrderApi, batchStockApi } from '@/lib/api'

const mockedDetail = processingOrderApi.detail as unknown as ReturnType<typeof vi.fn>
const mockedGenerate = processingOrderApi.generate as unknown as ReturnType<typeof vi.fn>
const mockedUpdate = processingOrderApi.update as unknown as ReturnType<typeof vi.fn>
const mockedCandidates = batchStockApi.candidates as unknown as ReturnType<typeof vi.fn>

const poIssued = {
  id: 'po-1',
  orderId: 'order-001',
  orderNo: 'ORD-1',
  customerName: '张三',
  processingOrderNo: 'JG-20260912-0001',
  processor: '朝阳加工厂',
  expectedDeliveryDate: '2026-09-20',
  status: 'issued',
  items: [
    {
      productName: '布艺遮光帘A',
      colorName: '米白',
      sellingMethod: '散剪',
      width: 2.5,
      height: 2.8,
      quantity: 2,
      unit: '米',
      processingItems: [{ id: 'p1', name: '打孔', quantity: 2, unit: '米', options: ['四爪钩'] }],
    },
  ],
}

// 待发加工（generated）状态：展示「发加工」入口
const poGenerated = { ...poIssued, id: 'po-gen', status: 'generated', processor: undefined, expectedDeliveryDate: undefined }

/**
 * 快照携带工艺规格的加工单（issue #4355 / 设计文档 §4.9 ③）。
 * 键名与 `processing_info` / `items_snapshot` 同口径（camelCase + 算料 snake_case，§4.5）。
 */
const poWithCraft = {
  ...poIssued,
  items: [
    {
      ...poIssued.items[0],
      // 门幅（issue #5022）：快照/订单层落的是 SKU 的 `doorWidth` 原串（存量有 '2.8米' / '2.8' 两形态）
      doorWidth: '2.8米',
      curtainType: '布帘',
      craft: '韩褶',
      cuttingMode: '定高买宽',
      openCount: 2,
      isShaped: true,
      style: '拼色',
      specialOptions: ['加铅线', '双褶'],
      pleat_count: 52,
      per_panel_pleats: 26,
      pleatSpacing: 0.1,
      panels: 4,
      fullness: 2,
      fullness_actual: 1.86,
      fabric_meters: 13.3,
      processingMeters: 13.3,
      hasPattern: true,
      patternRepeat: 0.32,
    },
  ],
}

/**
 * issue #4555：快照补「算料公式」。
 * 键名口径（读码实测）：快照键族 = **snake_case** `formula_text`
 * （订单层 `processing_info` 落的是 camelCase `formulaText`，展示映射 `lib/craft-display.ts` 两别名同登记）。
 */
const FORMULA_TEXT = '韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米'

const poWithFormula = {
  ...poIssued,
  items: [{ ...poIssued.items[0], craft: '韩褶', formula_text: FORMULA_TEXT }],
}

/**
 * 本地时区「今天」（yyyy-MM-dd），与组件 min/防御校验同口径（issue #3901）。
 *
 * issue #4761：**不再**读墙钟 —— 改从冻结时刻 `FROZEN_NOW` 派生，与组件同刻。
 * 改前形态 `new Date()` 的隐患：组件在渲染时取「今天」、断言在断言时再取一次，
 * 两次调用之间跨过午夜 ⇒ `min` 是昨天、期望值是今天 ⇒ required job 里随机红。
 */
function todayLocal(): string {
  const d = FROZEN_NOW
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

describe('ProcessingOrderBlock', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW) // 组件与断言都读这一时刻
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('含加工项且无加工单 → 展示「生成加工单」入口（PG-001）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing />)
    expect(await screen.findByText('生成加工单')).toBeInTheDocument()
  })

  it('生成成功 → 结果可见：加工单号 + 状态时间线 + 快照明细 + 复制全部（PG-001）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    mockedGenerate.mockResolvedValueOnce({
      data: { data: [{ orderRef: 'order-001', success: true, processingOrderNo: 'JG-20260912-0001' }] },
    })
    // 生成后重新拉取详情 → 已生成状态
    mockedDetail.mockResolvedValueOnce({ data: { data: { ...poIssued, status: 'generated', processor: undefined, expectedDeliveryDate: undefined } } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing />)
    await userEvent.click(await screen.findByText('生成加工单'))

    expect(mockedGenerate).toHaveBeenCalledWith(['order-001'])
    expect(await screen.findByText('JG-20260912-0001')).toBeInTheDocument()
    expect(screen.getAllByText('已生成').length).toBeGreaterThan(0)
    expect(screen.getByText(/打孔/)).toBeInTheDocument()
    expect(screen.getByText(/四爪钩/)).toBeInTheDocument()
    expect(screen.getByText('复制全部')).toBeInTheDocument()
  })

  it('已有加工单 issued → 展示加工方/交期/状态 + 开始加工按钮（PG-005）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    expect(await screen.findByText('JG-20260912-0001')).toBeInTheDocument()
    expect(screen.getByText(/朝阳加工厂/)).toBeInTheDocument()
    expect(screen.getByText(/2026-09-20/)).toBeInTheDocument()
    expect(screen.getAllByText('已发加工').length).toBeGreaterThan(0)
    expect(screen.getByText('开始加工')).toBeInTheDocument()
  })

  it('复制全部 → 剪贴板文本含加工单号与加工项 options（PG-005）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain('JG-20260912-0001')
    expect(text).toContain('朝阳加工厂')
    expect(text).toContain('打孔（四爪钩）')
  })

  // ── V119 / issue #5158：快照里的**排料结果**（应领米数 / 公式口径 / 省下的米数）──────

/**
 * 指派了批次且排料成功的加工单：快照带 `formulaMeters` / `plannedMeters` / `savedMeters`
 * （生成加工单那一刻固化）。前端据此把「车间要领多少米」显示出来 —— 这是本单唯一的前端面。
 */
const poWithCuttingPlan = {
  ...poIssued,
  items: [
    { ...poIssued.items[0], quantity: 3, formulaMeters: 3, plannedMeters: 1.5, savedMeters: 1.5 },
  ],
}

describe('ProcessingOrderBlock 排料结果展示（V119 / issue #5158）', () => {
  beforeEach(() => {
    mockedDetail.mockReset()
    mockedGenerate.mockReset()
    mockedUpdate.mockReset()
    mockedCandidates.mockReset()
  })

  it('PR-065 快照带排料结果 ⇒ 显示「应领 X 米（公式 Y 米 · 省 Z 米）」（0.1 米粒度口径）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCuttingPlan } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const plan = await screen.findByTestId('po-item-cutting-plan-0')
    // 应领 1.5（排料口径）；公式 3；省 1.5 —— 三个数分列，读的人不会把公式米数当成要领的米数
    expect(plan.textContent).toContain('应领 1.5 米')
    expect(plan.textContent).toContain('公式 3 米')
    expect(plan.textContent).toContain('省 1.5 米')
  })

  it('PR-065 不可并排（saved = 0）⇒ 如实显示公式口径，**不冒功**说省了 0 米', async () => {
    mockedDetail.mockResolvedValueOnce({
      data: {
        data: {
          ...poIssued,
          items: [{ ...poIssued.items[0], formulaMeters: 2.7, plannedMeters: 2.7, savedMeters: 0 }],
        },
      },
    })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const plan = await screen.findByTestId('po-item-cutting-plan-0')
    expect(plan.textContent).toContain('应领 2.7 米')
    expect(plan.textContent).toContain('公式 2.7 米')
    expect(plan.textContent).not.toContain('省')
  })

  it('PR-065 未指派批次 / 排不了料（无排料键）⇒ 整块不渲染（缺值不渲染，也不画成「省 0 米」）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    expect(await screen.findByText('布艺遮光帘A')).toBeInTheDocument()
    expect(screen.queryByTestId('po-item-cutting-plan-0')).toBeNull()
  })
})

// ── issue #4355：加工单展示工艺规格（设计文档 §4.9 ③）─────────────────

  it('快照明细展示工艺规格：部位/工艺/加工类型/打开方式/是否定型/款式/特殊选项（PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const spec = await screen.findByTestId('po-item-craft-spec')
    expect(within(spec).getByText('工艺规格')).toBeInTheDocument()
    expect(within(spec).getByText('布帘')).toBeInTheDocument()
    expect(within(spec).getByText('韩褶')).toBeInTheDocument()
    expect(within(spec).getByText('定高买宽')).toBeInTheDocument()
    expect(within(spec).getByText('双开')).toBeInTheDocument()
    expect(within(spec).getByText('拼色')).toBeInTheDocument()
    expect(within(spec).getByText('加铅线、双褶')).toBeInTheDocument()
    expect(within(spec).getByText('是否定型').parentElement?.textContent).toContain('是')
  })

  it('快照明细展示算料口径：总褶数/褶数（每片）/幅数/褶倍/米数/是否对花/花距（PG-019）—— ⚠️ #4876 起**不再渲染「褶距」**', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const spec = await screen.findByTestId('po-item-craft-spec')
    expect(within(spec).getByText('52')).toBeInTheDocument()
    expect(within(spec).getByText('26')).toBeInTheDocument()
    // ⚠️ #4876：#4878 把 `formula`/`craftTier` 补进了**加工单快照白名单**；本条只锚「褶距」这一行的退场
    // （存量快照里仍有 `pleatSpacing` ⇒ 断言它**不再被渲染**）。
    expect(within(spec).queryByText('褶距')).toBeNull()
    expect(within(spec).queryByText('0.1米')).toBeNull()
    expect(within(spec).getByText('4')).toBeInTheDocument()
    expect(within(spec).getByText('2 倍')).toBeInTheDocument()
    expect(within(spec).getByText('1.86 倍')).toBeInTheDocument()
    // 面料米数 / 加工费米数 = §4.9 要求的**两个字段**（§6.1 口径拆两值）⇒ 同值时出现两次
    expect(within(spec).getAllByText('13.3米')).toHaveLength(2)
    expect(within(spec).getByText('是否对花')).toBeInTheDocument()
    expect(within(spec).getByText('0.32米')).toBeInTheDocument()
  })

  it('「复制全部」文本含工艺规格（发给加工方/贴 Excel 时不丢工艺，PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain('工艺：韩褶')
    expect(text).toContain('加工类型：定高买宽')
    // 门幅（issue #5022）：SKU 原串 '2.8米' 走同一份解析 ⇒ 复制文本里也带上（贴 Excel 不丢）
    expect(text).toContain('门幅：2.8米')
    expect(text).toContain('打开方式：双开')
    expect(text).toContain('总褶数：52')
    expect(text).toContain('是否对花：是')
    expect(text).not.toMatch(/undefined|null|NaN/)
  })

  it('#5022：快照带 SKU 门幅 ⇒ 规格块渲染「门幅」行（加工单纸面看得到系统按几米算的）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const spec = await screen.findByTestId('po-item-craft-spec')
    expect(within(spec).getByText('门幅')).toBeInTheDocument()
    expect(within(spec).getByText('2.8米')).toBeInTheDocument()
  })

  it('缺值不渲染：存量单无工艺键 ⇒ 无规格块，复制文本也不出现 undefined/null/NaN（PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(screen.queryByTestId('po-item-craft-spec')).toBeNull()
    const text = writeText.mock.calls[0][0] as string
    expect(text).not.toMatch(/undefined|null|NaN/)
    expect(text).not.toContain('工艺：')
  })

  // ── issue #4555：车间/任务卡纸面看到「用料是怎么算出来的」─────────────────

  it('#4555 判据 3（红证）：快照带 formula_text ⇒ 加工单区块渲染「算料公式」行（逐字）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithFormula } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)

    const spec = await screen.findByTestId('po-item-craft-spec')
    expect(within(spec).getByText('算料公式')).toBeInTheDocument()
    expect(within(spec).getByText(FORMULA_TEXT)).toBeInTheDocument()
  })

  it('#4555 判据 3：「复制全部」文本含「算料公式：…」（发给加工方/贴 Excel 也不丢）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithFormula } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain(`算料公式：${FORMULA_TEXT}`)
  })

  it('#4555 判据 2（回归）：存量加工单无 formula_text 键 ⇒ 无「算料公式」行、复制文本不出现该行', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(screen.queryByText('算料公式')).toBeNull()
    const text = writeText.mock.calls[0][0] as string
    expect(text).not.toContain('算料公式')
    expect(text).not.toMatch(/undefined|null|NaN/)
  })

  // issue #3889：onStatusChange 上报加工单状态（详情页据此守卫发货入口）；查询失败上报 null
  it('onStatusChange 携带加载到的加工单状态', async () => {
    const onStatusChange = vi.fn()
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing onStatusChange={onStatusChange} />)

    await screen.findByText('JG-20260912-0001')
    expect(onStatusChange).toHaveBeenCalledWith(expect.objectContaining({ status: 'issued' }))
  })

  it('onStatusChange 查询失败时上报 null', async () => {
    const onStatusChange = vi.fn()
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing onStatusChange={onStatusChange} />)

    await screen.findByText('生成加工单')
    expect(onStatusChange).toHaveBeenCalledWith(null)
  })

  // ── issue #3901：发加工交期改日期控件且禁止过去日期 ──────────────

  it('发加工表单：交期为 date 控件且 min=今天（#3901）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('发加工'))

    const dateInput = screen.getByPlaceholderText('交期 yyyy-MM-dd')
    expect(dateInput).toHaveAttribute('type', 'date')
    expect(dateInput).toHaveAttribute('min', todayLocal())
  })

  it('发加工：过去交期提交被拦截（setError、不发请求）（#3901）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('发加工'))

    fireEvent.change(screen.getByPlaceholderText('交期 yyyy-MM-dd'), { target: { value: '2020-01-01' } })
    await userEvent.click(screen.getByText('确认发加工'))

    expect(await screen.findByText('交付日期不能早于今天')).toBeInTheDocument()
    expect(mockedUpdate).not.toHaveBeenCalled()
  })

  it('发加工：今天/未来交期放行并提交，结果可见状态更新（#3901）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    mockedUpdate.mockResolvedValueOnce({
      data: { data: { ...poGenerated, status: 'issued', processor: '朝阳加工厂', expectedDeliveryDate: todayLocal() } },
    })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" hasProcessing />)
    await userEvent.click(await screen.findByText('发加工'))

    fireEvent.change(screen.getByPlaceholderText('加工方（如：朝阳加工厂）'), { target: { value: '朝阳加工厂' } })
    fireEvent.change(screen.getByPlaceholderText('交期 yyyy-MM-dd'), { target: { value: todayLocal() } })
    await userEvent.click(screen.getByText('确认发加工'))

    await waitFor(() =>
      expect(mockedUpdate).toHaveBeenCalledWith('po-gen', {
        action: 'issue',
        processor: '朝阳加工厂',
        expectedDeliveryDate: todayLocal(),
        reason: undefined,
      }),
    )
    // 结果可见：提交成功后状态时间线/头部渲染「已发加工」，表单收起
    await waitFor(() => expect(screen.getAllByText('已发加工').length).toBeGreaterThan(0))
    expect(screen.queryByPlaceholderText('交期 yyyy-MM-dd')).not.toBeInTheDocument()
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// 生成加工单时由文员指定批次（V116 / issue #5145 阶段 1，PR-054）
//
// 契约（后端已落地）：`POST /api/admin/processing-orders/generate` 的 body = `{orderIds, batches?}`，
// `batches: [{orderId, itemId, batchNo}]`；**缺省/空 = 不指派**（行为与今天逐字相同）。
// 候选来自 `GET /api/admin/batch-stock/candidates?productId=&skuId=&meters=`（后端给建议值，人工可改）。
// ══════════════════════════════════════════════════════════════════════════════

/** 订单明细（`OrderItem`，订单详情页已有数据）：行身份 = `itemId` = `order_items.id` */
const orderItems = [
  {
    id: 'item-a',
    productId: 'prod-1',
    productName: '布艺遮光帘A',
    quantity: 2.7,
    unitPrice: 99,
    amount: 267.3,
    subtotal: 267.3,
    processingInfo: {
      saleForm: '成品帘',
      skuId: 11,
      skuCode: 'SKU-11',
      colorName: '米白',
      processingItems: [{ name: '打孔' }],
    },
  },
  {
    id: 'item-b',
    productId: 'prod-1',
    productName: '布艺遮光帘A',
    quantity: 1.5,
    unitPrice: 99,
    amount: 148.5,
    subtotal: 148.5,
    processingInfo: {
      saleForm: '成品帘',
      skuId: 12,
      skuCode: 'SKU-12',
      colorName: '浅灰',
      processingItems: [{ name: '打孔' }],
    },
  },
] as never[]

/** 候选批次（`BatchStockViews.Candidate` 原形） */
const candidate = (over: Record<string, unknown> = {}) => ({
  batchNo: 'PC-20260901-0001',
  remainingMeters: '10',
  receivedDate: '2026-09-01',
  dyeLot: 'G1',
  inboundNo: 'RK-1',
  unitCost: '12',
  suggested: false,
  enough: true,
  ...over,
})

/** 候选响应（`BatchStockViews.Candidates` 原形） */
const candidatesPayload = (over: Record<string, unknown> = {}) => ({
  data: {
    data: {
      suggestionRule: 'FIFO_RECEIVED_DATE',
      suggestedBatchNo: null,
      requiredMeters: '2.7',
      candidates: [],
      ...over,
    },
  },
})

/** item-a（skuId=11）有候选、item-b（skuId=12）无候选 —— 混排：弹框里一行可选、一行不可选 */
const mixedCandidates = (params: { skuId?: number }) =>
  Promise.resolve(
    params.skuId === 11
      ? candidatesPayload({
          suggestedBatchNo: 'PC-20260901-0001',
          candidates: [
            candidate({ suggested: true }),
            candidate({ batchNo: 'PC-20260905-0002', remainingMeters: '5', receivedDate: '2026-09-05' }),
            candidate({ batchNo: 'PC-20260910-0009', remainingMeters: '1', receivedDate: '2026-09-10', enough: false }),
          ],
        })
      : candidatesPayload({ requiredMeters: '1.5' }),
  )

describe('ProcessingOrderBlock 派工指定批次（issue #5145 阶段 1）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('PR-054 判据①（红证）：本单所有行都没有可用批次 ⇒ 不弹空对话框、按原路径生成（请求只有 orderIds）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    mockedGenerate.mockResolvedValueOnce({
      data: { data: [{ orderRef: 'order-001', success: true, processingOrderNo: 'JG-20260912-0001' }] },
    })
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    // 两行都无候选（库存里没有批次可用）
    mockedCandidates.mockImplementation(() => Promise.resolve(candidatesPayload()))

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing items={orderItems} />)
    await userEvent.click(await screen.findByText('生成加工单'))

    await waitFor(() => expect(mockedGenerate).toHaveBeenCalled())
    // 候选确实按「行商品 + 行 SKU + 行米数」取过（不是跳过候选直接生成）
    expect(mockedCandidates).toHaveBeenCalledWith({ productId: 'prod-1', skuId: 11, meters: 2.7 })
    // 单参调用 ⇒ 请求体只有 orderIds（不指派 ⇒ 与今天逐字相同）
    expect(mockedGenerate.mock.calls[0]).toHaveLength(1)
    expect(mockedGenerate).toHaveBeenCalledWith(['order-001'])
    // 不弹空对话框挡路
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('PR-054 判据②③：弹框逐行列候选（建议值默认选中、可改、不足本行的不可选），确认后 batches 逐字正确', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    mockedGenerate.mockResolvedValueOnce({
      data: { data: [{ orderRef: 'order-001', success: true, processingOrderNo: 'JG-20260912-0001' }] },
    })
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    mockedCandidates.mockImplementation(mixedCandidates as never)

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing items={orderItems} />)
    await userEvent.click(await screen.findByText('生成加工单'))

    // 判据③：后端建议值默认选中；候选文案 = 批次号 + 剩余米数 + 收货日期
    const selectA = await screen.findByTestId('batch-select-item-a')
    expect(selectA).toHaveValue('PC-20260901-0001')
    expect(screen.getByText('PC-20260901-0001（余 10 米 · 收货 2026-09-01）')).toBeInTheDocument()
    // 余量不够本行的候选在列表里但**不可选**（选了必被后端 409 拒 ⇒ 提前挡住）
    expect(screen.getByText(/PC-20260910-0009/)).toBeDisabled()
    // item-b 没有可用批次 ⇒ 显式标注「无可用批次」且**不给下拉**（该行不指派）
    expect(screen.getByTestId('batch-unavailable-item-b')).toHaveTextContent('无可用批次')
    expect(screen.queryByTestId('batch-select-item-b')).toBeNull()

    // 文员可改：换成另一个够用的批次
    fireEvent.change(selectA, { target: { value: 'PC-20260905-0002' } })
    await userEvent.click(screen.getByText('确认生成'))

    // 判据②：指派 ⇒ batches 内容逐字正确；不可指派的行**不进** batches
    await waitFor(() =>
      expect(mockedGenerate).toHaveBeenCalledWith(['order-001'], [
        { orderId: 'order-001', itemId: 'item-a', batchNo: 'PC-20260905-0002' },
      ]),
    )
  })

  it('PR-054 判据④（红证）：生成失败 ⇒ message 与 suggestion 原样展示（不吞可行动建议）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    mockedCandidates.mockImplementation(mixedCandidates as never)
    mockedGenerate.mockResolvedValueOnce({
      data: {
        data: [
          {
            orderRef: 'order-001',
            success: false,
            code: 'BATCH_STOCK_INSUFFICIENT',
            message: '批次 PC-20260901-0001 余量不足：可用 0.5 米，本行需要 2.7 米',
            suggestion: '可改用批次 PC-20260905-0002（余 5 米）',
          },
        ],
      },
    })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing items={orderItems} />)
    await userEvent.click(await screen.findByText('生成加工单'))
    expect(await screen.findByTestId('batch-select-item-a')).toBeInTheDocument()
    await userEvent.click(screen.getByText('确认生成'))

    // 后端 message 逐字
    expect(
      await screen.findByText('批次 PC-20260901-0001 余量不足：可用 0.5 米，本行需要 2.7 米'),
    ).toBeInTheDocument()
    // 后端 suggestion 逐字（缺料 fail-closed 的落点：文员据此改选，不被吞掉）
    expect(screen.getByText('可改用批次 PC-20260905-0002（余 5 米）')).toBeInTheDocument()
  })

  it('PR-054 回归：下单明细行没带 SKU 标识 ⇒ 该行「无可用批次」（不猜 SKU，避免串色/串门幅）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    mockedGenerate.mockResolvedValueOnce({
      data: { data: [{ orderRef: 'order-001', success: true, processingOrderNo: 'JG-20260912-0001' }] },
    })
    mockedDetail.mockResolvedValueOnce({ data: { data: poGenerated } })
    mockedCandidates.mockImplementation(mixedCandidates as never)

    const legacyItems = [
      { ...(orderItems[0] as Record<string, unknown>), processingInfo: { saleForm: '成品帘', processingItems: [{ name: '打孔' }] } },
      orderItems[1],
    ] as never[]

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" hasProcessing items={legacyItems} />)
    await userEvent.click(await screen.findByText('生成加工单'))

    // 无 SKU 标识的行不查候选（无从核对批次归属）
    expect(mockedCandidates).toHaveBeenCalledTimes(1)
    expect(mockedCandidates).toHaveBeenCalledWith({ productId: 'prod-1', skuId: 12, meters: 1.5 })
  })
})
