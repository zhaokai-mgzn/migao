// @vitest-environment jsdom
// case_ids: PG-001, PG-005, PG-019, PG-090, PG-092, UI-019, UI-030, UI-094, PR-065, UI-115

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

// issue #7507：非加急单的出口是**跳转**智能派单页 ⇒ 导航必须可断言（setup.ts 的全局桩每次返回
// 新的 `vi.fn()`，断言不到调用；这里换成同一实例）。
const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: routerPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}))

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
 * 卖布单的**出库作业单**（issue #7079）：`order_kind='outbound'` ⇒ **没有加工方、没有交期**。
 *
 * `order_kind` 是**读面机器键**（键名冻结，与同 DTO 上的 `short_code` / `scan_url` 同族）：
 * 上屏一律是中文业务名「出库作业单」，`processing` / `outbound` / `order_kind` 不得出现。
 */
const poOutbound = {
  id: 'po-out',
  orderId: 'order-002',
  orderNo: 'ORD-2',
  customerName: '王五',
  processingOrderNo: 'CK-20261017-0001',
  order_kind: 'outbound',
  status: 'issued',
  items: [
    {
      productName: '雪尼尔遮光布',
      colorName: '灰蓝',
      sellingMethod: '散剪',
      quantity: 12,
      unit: '米',
      processingItems: [{ id: 'p1', name: '裁剪', quantity: 12, unit: '米' }],
    },
  ],
}

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




  // ── issue #7079：作业单两型（加工单 / 出库作业单）在订单详情块的可见面 ──────────────

  it('#7079 缺键 = 存量单 ⇒ 按加工单渲染（不把存量单读成出库，加工方/交期照旧可见）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

    await screen.findByText('JG-20260912-0001')
    expect(screen.getByTestId('processing-order-kind')).toHaveTextContent('加工单')
    expect(screen.getByText(/朝阳加工厂/)).toBeInTheDocument()
    expect(screen.getByText(/2026-09-20/)).toBeInTheDocument()
    expect(screen.queryByTestId('processing-order-outbound-note')).toBeNull()
  })

  it('#7079 出库作业单：类型显示中文业务名，且**不渲染**加工方/交期（含「发加工」写面）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poOutbound } })
    render(<ProcessingOrderBlock orderId="order-002" orderStatus="producing" workOrderKind="processing" />)

    await screen.findByText('CK-20261017-0001')
    // ① 类型可见 = 中文业务名（不是机器键）
    expect(screen.getByTestId('processing-order-kind')).toHaveTextContent('出库作业单')
    // ② 无加工方 / 无交期：写面与展示都不出现，改为如实说明原因
    expect(screen.getByTestId('processing-order-outbound-note')).toBeInTheDocument()
    expect(screen.queryByText(/加工方：/)).toBeNull()
    expect(screen.queryByPlaceholderText('加工方（如：朝阳加工厂）')).toBeNull()
    expect(screen.queryByPlaceholderText('交期 yyyy-MM-dd')).toBeNull()
    // ③ 本块**只读**（issue #7634）：发加工 / 开始加工 / 加工完成 / 取消 四个写动作一个都不渲染
    for (const label of ['发加工', '开始加工', '加工完成', '取消加工单', '取消作业单']) {
      expect(screen.queryByRole('button', { name: label })).toBeNull()
    }
    // ④ 只给去处：生产明细页（状态流转在那里做）
    expect(screen.getByTestId('po-go-production')).toBeInTheDocument()
    // ⑤ 🔴 机器键绝不上屏
    expect(document.body.textContent ?? '').not.toContain('outbound')
    expect(document.body.textContent ?? '').not.toContain('order_kind')
  })

  it('#7079 出库作业单「复制全部」：抬头用中文业务名，且不出现加工方/交期行', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poOutbound } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-002" orderStatus="producing" workOrderKind="processing" />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain('出库作业单：CK-20261017-0001')
    expect(text).not.toContain('加工方')
    expect(text).not.toContain('交期')
    expect(text).not.toContain('outbound')
  })

  it('复制全部 → 剪贴板文本含加工单号与加工项 options（PG-005）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)
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
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

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
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

    const plan = await screen.findByTestId('po-item-cutting-plan-0')
    expect(plan.textContent).toContain('应领 2.7 米')
    expect(plan.textContent).toContain('公式 2.7 米')
    expect(plan.textContent).not.toContain('省')
  })

  it('PR-065 未指派批次 / 排不了料（无排料键）⇒ 整块不渲染（缺值不渲染，也不画成「省 0 米」）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

    expect(await screen.findByText('布艺遮光帘A')).toBeInTheDocument()
    expect(screen.queryByTestId('po-item-cutting-plan-0')).toBeNull()
  })
})

// ── issue #4355：加工单展示工艺规格（设计文档 §4.9 ③）─────────────────

  it('快照明细展示工艺规格：部位/工艺/加工类型/打开方式/是否定型/款式/特殊选项（PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

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
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

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

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain('工艺：韩褶')
    expect(text).toContain('加工类型：定高买宽')
    // 门幅（issue #5022 的意图）：SKU 原串 '2.8米' 走同一份解析 ⇒ 复制文本里**仍然**带上（贴 Excel 不丢）。
    // 🔴 issue #6893：只印**一处** —— 属性行 `门幅:2.8米`（紧邻的「工艺规格」那行不再重复同一真值）。
    expect(text).toContain('门幅:2.8米')
    expect((text.match(/门幅/g) ?? []).length).toBe(1)
    expect(text).toContain('打开方式：双开')
    expect(text).toContain('总褶数：52')
    expect(text).toContain('是否对花：是')
    expect(text).not.toMatch(/undefined|null|NaN/)
  })

  it('#5022 + #6893：加工单上看得到「门幅」（属性行承担），规格块不再重复同一行', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    const { container } = render(
      <ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />
    )

    // #5022 的意图**不砍**：门幅在加工单上看得见（`加工单纸面看得到系统按几米算的`）
    await screen.findByTestId('po-item-craft-spec')
    expect(container.textContent).toContain('门幅 2.8米')
    // #6893：同一块里**只印一处** —— 规格块不再重复「门幅」行（改前这里有一行，判据恒绿）
    expect(within(screen.getByTestId('po-item-craft-spec')).queryByText('门幅')).toBeNull()
    expect((container.textContent?.match(/门幅/g) ?? []).length).toBe(1)
  })

  it('缺值不渲染：存量单无工艺键 ⇒ 无规格块，复制文本也不出现 undefined/null/NaN（PG-019）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)
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
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

    const spec = await screen.findByTestId('po-item-craft-spec')
    expect(within(spec).getByText('算料公式')).toBeInTheDocument()
    expect(within(spec).getByText(FORMULA_TEXT)).toBeInTheDocument()
  })

  it('#4555 判据 3：「复制全部」文本含「算料公式：…」（发给加工方/贴 Excel 也不丢）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithFormula } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)
    await userEvent.click(await screen.findByText('复制全部'))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const text = writeText.mock.calls[0][0] as string
    expect(text).toContain(`算料公式：${FORMULA_TEXT}`)
  })

  it('#4555 判据 2（回归）：存量加工单无 formula_text 键 ⇒ 无「算料公式」行、复制文本不出现该行', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)
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
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" onStatusChange={onStatusChange} />)

    await screen.findByText('JG-20260912-0001')
    expect(onStatusChange).toHaveBeenCalledWith(expect.objectContaining({ status: 'issued' }))
  })

  it('onStatusChange 查询失败时上报 null', async () => {
    const onStatusChange = vi.fn()
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" workOrderKind="processing" onStatusChange={onStatusChange} />)

    await screen.findByTestId('po-go-pool')
    expect(onStatusChange).toHaveBeenCalledWith(null)
  })



})


// ══════════════════════════════════════════════════════════════════════════════════════════════
// issue #7079 第 5 包（UI-115）：**卖布单的生成出口** —— 判据 = 订单详情读面键 `work_order_kind`
//
// 病根：本块原先的门是 `hasProcessing`（= `order.processingItems.length > 0`）这**单侧**信号。
// 卖布单（按米卖布、行上**没有加工项**）在那一侧恒为 false ⇒ **没有「生成」按钮**，并落到一句
// 对卖布单**不实**的空态文案「无加工项订单无需加工环节」；而它其实必须生成**出库作业单**、
// 做完裁剪 + 打包报工才能发货（后端 `OrderShipGuard.needsWork` = 含加工项 **或** 有卖布行）。
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe('ProcessingOrderBlock 卖布单的生成出口（issue #7079 第 5 包）', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW)
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })





  it('UI-115 判据 4（反向护栏）：无作业的订单（work_order_kind 缺键）⇒ 不出现生成入口，空态说「无需作业单」', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-plain" orderStatus="confirmed" workOrderKind={null} />)

    expect(await screen.findByText(/该订单无需作业单（没有加工项，也不是卖布单）/)).toBeInTheDocument()
    // issue #7222：只宣判不够 —— 必须给可行动出口（没标售卖形态的卖布单该去哪儿补）
    expect(document.body.textContent ?? '').toContain('售卖形态')
    expect(screen.queryByText(/^生成/)).toBeNull()
    expect(document.body.textContent ?? '').not.toContain('无加工项订单无需加工环节')
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
      skuId: '2097126615461462018',
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
      skuId: '2098712345678901234',
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

/** item-a（skuId=`2097126615461462018`）有候选、item-b（skuId=`2098712345678901234`）无候选 —— 混排：弹框里一行可选、一行不可选
 * 🔴 issue #5904：id 用**真实量级的雪花号字符串**（≈2.1e18）—— 玩具 id（`11`）测不出 `Number()` 截断。
 */
const mixedCandidates = (params: { skuId?: string }) =>
  Promise.resolve(
    params.skuId === '2097126615461462018'
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


// ═══════════════════════════════════════════════════════════════════════════════════════════════
// issue #7507：**直派收敛** —— 非加急订单默认走智能派单（订单详情页不再直派）
//
// 用户 2026-10-23：「为什么从订单可以直接生成加工单，而不是默认走智能派单流程？这里得限制下」。
// 口径（用户裁定 = 选项 A）：非加急单在详情页只给「去智能派单」入口；**加急单保留直派**
// （既有裁定「允许加急的订单直接派」）。默认（漏传 `isUrgent`）必须落在**受限**一侧 ——
// 新调用方不许靠漏传属性绕过限制。
// ═══════════════════════════════════════════════════════════════════════════════════════════════


// ═══════════════════════════════════════════════════════════════════════════════════════════════
// issue #5685：物品行（部位行）的**部位备注** —— 快照行键 `remark`
//
// 来源 = 生成加工单那一刻从 `order_items.processing_info.remark` **逐字固化**（下单页写侧单点
// 构造 `buildLineProcessingInfo`）；DTO `ProcessingOrderItemBrief.remark` 已声明该键。
// 口径与订单详情一致：**有值才渲染**（缺键 / 空串 / 纯空白 ⇒ 该行不出现，不显示空行）。
// ═══════════════════════════════════════════════════════════════════════════════════════════════

describe('ProcessingOrderBlock 部位备注（issue #5685）', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW)
    vi.clearAllMocks()
  })

  it('#5685 判据 1（红证）：快照行带 remark ⇒ 物品行显示备注，且「复制全部」的纯文本同源带上', async () => {
    const remark = '公式--48个折'
    mockedDetail.mockResolvedValueOnce({
      data: { data: { ...poIssued, items: [{ ...poIssued.items[0], remark }] } },
    })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)
    await screen.findByText('JG-20260912-0001')

    // ① 屏幕上（物品行 = 部位行）
    expect(screen.getByText(`备注：${remark}`)).toBeInTheDocument()
    // ② 复制给加工方 / 车间的纯文本也要带（车间据此知道「这个数字怎么来的」—— 两个面同源）
    await userEvent.click(screen.getByText('复制全部'))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(writeText.mock.calls[0][0] as string).toContain(`备注：${remark}`)
  })

  it('#5685 判据 2（红证）：缺键 / 空串 / 纯空白 ⇒ 不出现备注行（缺值不渲染）', async () => {
    const states: Array<[string, string | undefined]> = [
      ['缺键', undefined],
      ['空串', ''],
      ['纯空白', '   '],
    ]
    for (const [label, remark] of states) {
      mockedDetail.mockResolvedValueOnce({
        data: { data: { ...poIssued, items: [{ ...poIssued.items[0], remark }] } },
      })
      const { unmount } = render(
        <ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />
      )
      await screen.findByText('JG-20260912-0001')
      // 前提自证：本态下既有内容照常渲染（防「整块没渲染 ⇒ 假绿」）
      expect(screen.getByText(/打孔/), label).toBeInTheDocument()
      expect(screen.queryAllByText(/^备注：/), label).toHaveLength(0)
      unmount()
    }
  })
})

/**
 * issue #6893：加工单里「门幅」在**同一块文本**里只许出现一次。改前快照块既印属性行
 * `门幅 2.8米`，又印 `craftSpecRows()` 的「门幅」行；「复制全部」的文本同理（同一份拼装）。
 */
describe('加工单门幅不重复（issue #6893）', () => {
  it('快照块与「复制全部」文本里「门幅」各只出现一次', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithCraft } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    const { container } = render(
      <ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />
    )
    await screen.findByText('JG-20260912-0001')
    await userEvent.click(screen.getByText('复制全部'))
    await waitFor(() => expect(writeText).toHaveBeenCalled())

    const text = writeText.mock.calls[0][0] as string
    expect((text.match(/门幅/g) ?? []).length).toBe(1)
    expect((container.textContent?.match(/门幅/g) ?? []).length).toBe(1)
  })
})

/**
 * issue #6901：加工单块缺**货号**（快照键 `sku`）与**工序清单**（既有读面 `positions[]`）。
 *
 * 「屏幕明细块」与「复制全部」文本（`toPlainText`）是**同一条事实的两个渲染面** ⇒ 两处都补，
 * 且共用同一份取值/片段生成器（`snapshotAttrParts` / `operationParts` / `operationsByItem`）
 * —— 只补一处 ⇒ 复制出去的文本仍是旧的，车间照旧按老习惯做（`toPlainText` 的注释在防的正是这个）。
 */
describe('加工单块补货号与工序清单（issue #6901）', () => {
  const SKU = '0012'
  const poWithSku = {
    ...poIssued,
    items: [
      { ...poIssued.items[0], itemId: 'item-1', sku: SKU, doorWidth: '2.8米', sellingMethod: 'per_meter' },
    ],
  }

  /** 工序实例（读面形状 = `ProductionPosition`；按 `order_item_id` 对齐快照行 `itemId`） */
  const operationsFixture = [
    {
      order_item_id: 'item-1',
      position_name: '布帘',
      operations: [
        { id: 'op-1', operation: '精裁-布', logical_name: '精裁', unit: '米', qty: 2.5, status: 'pending' },
        { id: 'op-2', operation: '韩褶-布', logical_name: '韩褶', unit: '折', qty: 52, status: 'done' },
      ],
    },
  ]

  it('🔴 屏幕明细块印出货号（快照键 `sku`，同一行属性里，**只印一处**）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithSku } })
    const { container } = render(
      <ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />
    )
    await screen.findByText('JG-20260912-0001')
    const text = container.textContent ?? ''
    expect(text).toContain('货号 0012')
    // P2 信息不重复：同一真值（货号）不许印两处
    expect((text.match(/货号/g) ?? []).length).toBe(1)
    // 同块既有内容照常（防「整块没渲染 ⇒ 假绿」）
    expect(screen.getByText('布艺遮光帘A')).toBeInTheDocument()
    expect(screen.getByText('米白')).toBeInTheDocument()
  })

  it('🔴 缺货号 ⇒ 不渲染（不印空标签 —— 与同块 `colorName` 缺值口径一致）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    const { container } = render(
      <ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />
    )
    await screen.findByText('JG-20260912-0001')
    // 前提自证：本态确实渲染了快照块
    expect(container.textContent).toContain('布艺遮光帘A')
    expect(container.textContent).not.toContain('货号')
  })

  it('🔴 「复制全部」文本**同批**带出货号 + 工序清单（两处一个口径）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithSku } })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    render(
      <ProcessingOrderBlock
        orderId="order-001"
        orderStatus="producing"
        workOrderKind="processing"
        operations={operationsFixture}
      />
    )
    await screen.findByText('JG-20260912-0001')
    await userEvent.click(screen.getByText('复制全部'))
    await waitFor(() => expect(writeText).toHaveBeenCalled())

    const text = writeText.mock.calls[0][0] as string
    // 货号在标题行（`【N】品名（颜色）【货号】`）——贴 Excel 时一眼认得出是哪一件
    expect(text).toContain(`【${SKU}】`)
    // 工序清单：逐道逻辑名 + 应做（数量+单位）+ 状态
    expect(text).toContain('工序：')
    expect(text).toContain('精裁：2.5 米  待做')
    expect(text).toContain('韩褶：52 折  已完成')
    // 🔴 工人端快照名（读面键 `operation`）**不得**进文本
    expect(text).not.toContain('精裁-布')
    expect(text).not.toMatch(/undefined|null|NaN/)
  })

  it('🔴 屏幕块印工序清单（逐道逻辑名 + 应做 + 状态）；无工序 ⇒ 整块不出现', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithSku } })
    const { unmount, container } = render(
      <ProcessingOrderBlock
        orderId="order-001"
        orderStatus="producing"
        workOrderKind="processing"
        operations={operationsFixture}
      />
    )
    await screen.findByText('JG-20260912-0001')
    const rows = container.querySelectorAll('[data-testid="po-item-operation"]')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('精裁')
    expect(rows[0].textContent).toContain('2.5 米')
    expect(rows[0].textContent).toContain('待做')
    expect(rows[1].textContent).toContain('韩褶')
    expect(rows[1].textContent).toContain('已完成')
    expect(container.textContent).not.toContain('精裁-布')
    unmount()

    // 没传读面（订单还没生成加工单）⇒ 不出现工序块，也不印空标题
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithSku } })
    const second = render(
      <ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />
    )
    await screen.findByText('JG-20260912-0001')
    expect(second.container.querySelectorAll('[data-testid="po-item-operation"]')).toHaveLength(0)
    expect(second.container.textContent).not.toContain('工序')
  })

  it('🔴 负控：补了货号与工序行后，既有属性行逐字不变（门幅/方式/宽/高/数量 各只一处）', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poWithSku } })
    const { container } = render(
      <ProcessingOrderBlock
        orderId="order-001"
        orderStatus="producing"
        workOrderKind="processing"
        operations={operationsFixture}
      />
    )
    await screen.findByText('JG-20260912-0001')
    const text = container.textContent ?? ''
    expect(text).toContain('门幅 2.8米')
    expect(text).toContain('方式 按米')
    expect(text).toContain('宽 2.5m')
    expect(text).toContain('高 2.8m')
    expect(text).toContain('数量 2 米')
    // 每一个真值仍只印一处（新增片段不许把既有片段复制一遍）
    expect((text.match(/门幅/g) ?? []).length).toBe(1)
    expect((text.match(/货号/g) ?? []).length).toBe(1)
    expect((text.match(/数量/g) ?? []).length).toBe(1)
  })
})

// ══════════════════════════════════════════════════════════════════════════════
// issue #7634：销售订单「作业单」块**只读**（用户 2026-10-24 裁定 A）
//   「销售订单为什么还是可以直接加工，让你改成统一走智能派单，为什么还是老样子」
//   ⇒ 派单只在「智能派单」页；状态流转只在生产明细页。红证 = 把任一写动作按钮加回块里 ⇒ 判据 1 红。
// ══════════════════════════════════════════════════════════════════════════════

describe('ProcessingOrderBlock 只读（issue #7634）', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW)
    vi.clearAllMocks()
    routerPush.mockClear()
  })

  /** 五个写动作的商家可见文案 —— 一个都不许出现在销售订单块里 */
  const WRITE_ACTIONS = [
    '生成加工单',
    '生成作业单',
    '发加工',
    '开始加工',
    '加工完成',
    '取消加工单',
    '取消作业单',
  ]

  function expectNoWriteActions() {
    for (const label of WRITE_ACTIONS) {
      // 按**按钮**判（`加工完成` 也是状态时间线上的文字，那一步是只读的）
      expect(screen.queryByRole('button', { name: label }), `销售订单块不得再渲染「${label}」按钮（issue #7634）`).toBeNull()
    }
  }

  it('PG-092 判据 1（红证）：销售订单块只读 —— 五个写动作一个都不渲染', async () => {
    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)

    expect(await screen.findByText('JG-20260912-0001')).toBeInTheDocument()
    expectNoWriteActions()
  })

  it('PG-092 判据 2：无作业单 ⇒ 「去智能派单」；有作业单 ⇒ 「去生产明细」', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    const first = render(
      <ProcessingOrderBlock orderId="order-001" orderStatus="confirmed" workOrderKind="processing" />,
    )
    await userEvent.click(await screen.findByTestId('po-go-pool'))
    expect(routerPush).toHaveBeenCalledWith('/production/pool')
    first.unmount()

    mockedDetail.mockResolvedValueOnce({ data: { data: poIssued } })
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="producing" workOrderKind="processing" />)
    await userEvent.click(await screen.findByTestId('po-go-production'))
    expect(routerPush).toHaveBeenCalledWith('/processing-orders/JG-20260912-0001/production')
    expectNoWriteActions()
  })

  it('🔴 待付款单也走智能派单：直派生成入口已收走（#7626 的入口不再出现在订单页）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="pending" workOrderKind="processing" />)

    expect(await screen.findByTestId('po-go-pool')).toBeInTheDocument()
    expect(screen.queryByText('生成作业单')).toBeNull()
    expectNoWriteActions()
  })

  it('不可派单的状态（已关闭）⇒ 只给「当前状态还不能派单」空态，不给入口', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-001" orderStatus="cancelled" workOrderKind="processing" />)

    expect(await screen.findByTestId('processing-order-generate-not-yet')).toBeInTheDocument()
    expect(screen.queryByTestId('po-go-pool')).toBeNull()
  })

  it('UI-115 判据 1（红证）：卖布单无作业单 ⇒ 「去智能派单」+ 按型业务名（机器键不上屏）', async () => {
    mockedDetail.mockRejectedValueOnce(new Error('404'))
    render(<ProcessingOrderBlock orderId="order-002" orderStatus="confirmed" workOrderKind="outbound" />)

    expect(await screen.findByText(/该订单需要出库作业单/)).toBeInTheDocument()
    expect(screen.getByTestId('po-go-pool')).toBeInTheDocument()
    expect(document.body.textContent ?? '').not.toContain('outbound')
    expectNoWriteActions()
  })
})
