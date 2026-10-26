// case_ids: PP-011
// PP-011（issue #4964 立版式 → #5646 纸宽 → #7776 字号/字段 → **issue #7816 固定 50×150 + 份数 + 字段重排**）：
// 水洗唛 = **竖版 50mm × 150mm 单列**，字段面 = 纸面抬头（企业名 / 成品定制）+ **订单号（第一行）** / 客户 /
// 第 N 套共 M 套 / 部位 / 颜色 / 门幅 / 用料 / 宽高 / 加工方式 / **褶法** / 特殊选项 / 备注 + 底部**居中**二维码。
// 一行粒度 = 一部位（商品行）**一张 × 开数份**。
//
// 用户 2026-10-26 逐字（issue #7816，逐条都能判红）：
// ① 「水洗唛长度不足，设置为打印50*150」⇒ `@page` / 容器都是 50mm × 150mm；
// ② 「如果订单是双开的要打印两份，单开的要打印1份，三开打印3份，4开打印4份」⇒ **张数 = Σ 开数**；
// ③ 「字体还是太小，可以再大一点」⇒ 正文 12pt（旧 9pt）、抬头 14pt；
// ④ 「要体现出是否采用的韩褶公式以及韩褶的折数，用一个字段表示」⇒ `褶法 韩褶 52折` / `褶法 倍数法`；
// ⑤ 「把订单号放到第一行，客户那一行上面」「移除加工单号」「移除交期字段」「二维码放到底部居中」
//    「移除扫码报工和短码文字」「二维码可以放大一点」。
//
// 其余沿用既有契约（改回来 ⇒ 必红）：打印隔离 6 条、一部位一码 / 缺码不画假码、纸面内容 = `washLabelRows`、
// 退场两项（工序摘要 / 完整套号）、变体名不上纸面、缺值不渲染。
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import { washLabelRows } from '@/lib/wash-label-content'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { dataTables, collectTableIntegrity } from '@/components/orders/doc-tables'
import { assertNoPaperZeroFill, paperTextOf } from '@/lib/print-doc-paper'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

// 纸面抬头的企业名：替身可控（真实现读登录态 tenantName、无则回落设置读面 —— 异步，
// 判据里会变成时序相关的假红/假绿；这里只判「有没有抬头块、印的是什么」）
const companyNameStub = vi.hoisted(() => ({ value: '' }))
vi.mock('@/lib/use-company-name', () => ({ useCompanyName: () => companyNameStub.value }))

const PROCESSING_ORDER_NO = 'JG-20260921-8237'
/** 真实形态的 17 位订单号（真库实证 20260921973550001）—— 折行但**绝不截断** */
const ORDER_NO = '20260921973550001'
const CUSTOMER = '赵凯'
/** 已退场（2026-10-26 用户逐字「移除交期字段」）—— 纸面**不得**出现它 */
const DELIVERY = '2026-09-28'

const SCAN_BL = 'https://app.migaozn.com/s/7K3M9QP2'
const SCAN_SHA = 'https://app.migaozn.com/s/QW8Z2N4B'
const SCAN_LT = 'https://app.migaozn.com/s/ZX5C7V1N'

/**
 * 三个部位（= 三个商品行）分属**两套**（布帘 + 纱帘 = 第 1 套；帘头 = 第 2 套）——
 * 「第 N 套 / 共 M 套」由 `set_no` 去重派生（走 `groupBySet`，与进度表**同一份**口径）。
 */
const positions: ProductionPosition[] = [
  {
    position_name: '布艺遮光帘A',
    order_item_id: 'item-1',
    position_kind: '布帘',
    set_no: `${PROCESSING_ORDER_NO}-001`,
    product_name: '2699系列雪尼尔窗帘面料',
    width: 3,
    height: 2.75,
    part_token: 'part-token-bu-1',
    part_short_code: '7K3M9QP2',
    scan_url: SCAN_BL,
    // `operation` = 工人端快照名（变体名）：纸面**不得**渲染（issue #4621），且本版**不再印工序摘要**
    operations: [
      { id: 'op-1', seq: 1, operation: '精裁-布', logical_name: '精裁', position: '布帘', unit: '套', qty: 2, status: 'pending', done_qty: 0 },
      { id: 'op-2', seq: 2, operation: '外帘装袋', logical_name: '外帘装袋', unit: '件', qty: 2, status: 'pending', done_qty: 0 },
    ],
  },
  {
    position_name: '纱帘B',
    order_item_id: 'item-2',
    position_kind: '纱帘',
    set_no: `${PROCESSING_ORDER_NO}-001`,
    product_name: '金刚棉',
    width: 1.2,
    height: 2.75,
    part_token: 'part-token-sha-1',
    part_short_code: 'QW8Z2N4B',
    scan_url: SCAN_SHA,
    operations: [
      { id: 'op-3', seq: 1, operation: '韩褶-纱', logical_name: '韩褶', position: '纱帘', unit: '折', qty: 24, status: 'pending', done_qty: 0 },
    ],
  },
  {
    position_name: '帘头C',
    order_item_id: 'item-3',
    position_kind: '帘头',
    set_no: `${PROCESSING_ORDER_NO}-002`,
    product_name: '帘头布',
    width: 3,
    height: 0.3,
    part_token: 'part-token-lt-1',
    part_short_code: 'ZX5C7V1N',
    scan_url: SCAN_LT,
    operations: [
      { id: 'op-4', seq: 1, operation: '精裁-帘头', logical_name: '精裁', position: '帘头', unit: '套', qty: 1, status: 'pending', done_qty: 0 },
    ],
  },
]

/**
 * 加工单快照明细（`items_snapshot` 口径；`itemId` = 行主键，与 `position.order_item_id` 对齐）。
 *
 * 开数（issue #7816）：item-1 = **双开 2 份**、item-3 = **三开 3 份**、item-2 没有快照行 ⇒ 缺省 1 份
 * ⇒ 本单共 **2 + 1 + 3 = 6 张**。
 */
const items = [
  {
    itemId: 'item-1',
    productName: '2699系列雪尼尔窗帘面料',
    colorName: '米白',
    doorWidth: '2.8米',
    curtainType: '布帘',
    craft: '韩褶',
    cuttingMode: '定高买宽',
    openCount: 2,
    isShaped: true,
    specialOptions: ['加logo条', '防翘扣'],
    remark: '加铅块',
    fabric_meters: 6.3,
    pleat_count: 52,
    formula_text: '韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米',
  },
  {
    itemId: 'item-3',
    productName: '帘头布',
    colorName: '米灰',
    doorWidth: '2.8',
    curtainType: '帘头',
    craft: '平板',
    openCount: 3,
  },
] as unknown as ProcessingOrderItem[]

/** 公共属性（每张都必须呈现） */
const printCard = (overrides: Partial<ComponentProps<typeof TaskCardPrint>> = {}) =>
  render(
    <TaskCardPrint
      orderNo={ORDER_NO}
      customerName={CUSTOMER}
      positions={positions}
      items={items}
      printTarget="labels"
      {...overrides}
    />,
  )

const printArea = () => document.querySelector('.task-card-print-area') as HTMLElement

/** 张序 ⇒ 部位（开数展开后的映射；本单 = 2 + 1 + 3） */
const SHEET_SCANS = [SCAN_BL, SCAN_BL, SCAN_SHA, SCAN_LT, SCAN_LT, SCAN_LT]

describe('TaskCardPrint（水洗唛 竖版 50mm×150mm 单列，issue #7816）', () => {
  it('类级不变量（issue #6720）：本单据纸面不得出现「未知 ⇒ 0」的回退形态（今天它不印任何金额/数量）', () => {
    // 缺码部位**真的**渲染出来（否则下面的判据面可能是空的）：
    // 判据面 = **二维码占位**的取值（本单据唯一可能承载「缺值」的人可读位）
    printCard({
      positions: [
        { ...positions[0] },
        { position_name: '纱帘B', order_item_id: 'item-2', part_token: null, part_short_code: null, scan_url: null, operations: [] },
      ],
      qrPlaceholderHint: '二维码已撤销（旧码已失效）',
    })
    const placeholders = Array.from(
      printArea().querySelectorAll('[data-testid="task-card-qr-placeholder"]'),
    ).map((el) => (el.textContent || '').trim())
    // 单据：任务卡 TaskCardPrint
    assertNoPaperZeroFill(placeholders, {
      label: '任务卡 TaskCardPrint',
      presence: ['缺码部位（占位文案，不是假码，更不是 0）'],
    })
    // ✅ 正向证据锚：缺码位真的渲染了占位（否则上面的判据面可能是空的）
    expect(placeholders).toContain('二维码已撤销（旧码已失效）')
    // 纸面不得出现 `undefined` / `null` / `NaN`
    expect(paperTextOf(printArea())).not.toMatch(/undefined|null|NaN/)
  })

  it('「本单据不印数值」是**结构事实**而非漏判：纸面组件源码里没有任何数值格式化（一开印就红）', () => {
    // 这条钉住 SCOPE 里对洗水唛「天然免疫」的判断（见
    // frontend/admin-web/scripts/print-doc-zero-fallback-scan.mjs 的 SCOPE 注释与死亡条件）：
    // 一旦它开始把 amount / quantity 印上纸，本判据立刻红 ⇒ 必须同批登记进判据面。
    const src = readFileSync(join(process.cwd(), 'src/components/production/TaskCardPrint.tsx'), 'utf-8')
    for (const call of ['toLocaleString', 'toFixed', 'formatAmount', 'formatQty']) {
      expect(src, `水洗唛开始使用 ${call} ⇒ 它进了「印数值的纸面」判据面，请同步登记`).not.toContain(call)
    }
  })

  // 类级固化（issue #6595）：本单据的每一张表逐行自洽（Σ(colSpan) = 表头列数）。
  it('表格列数不变量：逐行 Σ(colSpan) 与表头列数一致（issue #6595）', () => {
    printCard()
    // 水洗唛是**单列**版式（`div` 承载，见 `TaskCardPrint.tsx` 的 `.task-card-label`）—— 面内 0 张表是**结构事实**，
    // 故这里只断言「若有表则必须自洽」（空集不再被当作判据空跑）。
    expect(
      dataTables(document.querySelector('.task-card-print-area'))
        .map((table) => collectTableIntegrity([table])) // 单据：任务卡 TaskCardPrint
        .every((tables) => tables.length === 1)
    ).toBe(true)
  })

  it('🔴 张数 = Σ 开数（双开 2 + 缺省 1 + 三开 3 = 6 张），张序 testid 连续', () => {
    printCard()

    const labels = SHEET_SCANS.map((_, index) => screen.getByTestId(`task-card-label-${index}`))
    expect(labels).toHaveLength(6)
    // 第 7 张不存在（多出一张 = 份数口径错）
    expect(screen.queryByTestId('task-card-label-6')).toBeNull()
    // 每张都带 `.task-card-label` 标记类（打印分页 / 纸型尺寸的落点）
    labels.forEach((label) => expect(label.className).toContain('task-card-label'))
  })

  it('🔴 每张的码 = 该**部位**自己的 scan_url（开数只是重复出纸，不改码）', () => {
    printCard()

    const codes = screen.getAllByTestId('task-card-qr')
    expect(codes).toHaveLength(6)
    expect(codes.map((qr) => qr.querySelector('title')?.textContent)).toEqual(SHEET_SCANS)
    // 逐张：SVG 真画了（不是空壳）
    codes.forEach((qr) => {
      expect(qr.tagName.toLowerCase()).toBe('svg')
      expect(qr.querySelectorAll('path').length).toBeGreaterThan(0)
    })
  })

  it('🔴 订单号 = **第一行**（客户之上）；加工单号与交期**不上纸**', () => {
    printCard()

    const rowsBlock = screen.getByTestId('task-card-label-rows-0')
    expect(rowsBlock.firstElementChild?.getAttribute('data-testid')).toBe('task-card-label-order-no-0')
    expect(screen.getByTestId('task-card-label-order-no-0')).toHaveTextContent(`订单 ${ORDER_NO}`)
    expect(rowsBlock.children[1]?.getAttribute('data-testid')).toBe('task-card-label-customer-0')

    // 🔴 退场：加工单号（2026-10-26「移除加工单号」）与人可读短码 / 「扫码报工」都不在纸面上
    const paper = paperTextOf(printArea())
    expect(paper).not.toContain(PROCESSING_ORDER_NO)
    expect(screen.queryByTestId('task-card-no')).toBeNull()
    expect(document.querySelector('[data-testid^="task-card-label-short-code-"]')).toBeNull()
    expect(paper).not.toContain('扫码报工')
    // 🔴 退场：交期（2026-10-26「移除交期字段」）
    expect(paper).not.toContain('交期')
    expect(paper).not.toContain(DELIVERY)
  })

  it('纸面内容与行序 = `washLabelRows`（单一真值；两条通道读同一份）', () => {
    printCard()

    const expected = washLabelRows({
      position: positions[0],
      item: items[0],
      setNo: 1,
      setCount: 2,
      customerName: CUSTOMER,
      orderNo: ORDER_NO,
    })
    const rowsBlock = screen.getByTestId('task-card-label-rows-0')
    const painted = Array.from(rowsBlock.children).map((el) => (el.textContent || '').trim())
    expect(painted).toEqual(expected.map((row) => row.text))
    // 正向锚：确实印了足够多的行（不是空清单）
    expect(painted.length).toBeGreaterThanOrEqual(10)
  })

  it('单列字段逐张渲染：部位 / 颜色 / 门幅 / 用料 / 宽高 / 加工方式（照真实工单信息顺序）', () => {
    printCard()

    // 第 1 张（布帘）：部位 / 颜色 / 门幅 / 用料 / 宽高 / 加工方式
    expect(screen.getByTestId('task-card-label-kind-0')).toHaveTextContent('部位 布帘')
    expect(screen.getByTestId('task-card-label-color-0')).toHaveTextContent('颜色 米白')
    expect(screen.getByTestId('task-card-label-door-width-0')).toHaveTextContent('门幅 2.8米')
    expect(screen.getByTestId('task-card-label-meters-0')).toHaveTextContent('用料 6.3米')
    expect(screen.getByTestId('task-card-label-size-0')).toHaveTextContent('宽高 3×2.75米')
    // 加工方式 = craft-display 的单一真值（工艺/加工类型/打开方式/是否定型），不另写推导
    const craft0 = screen.getByTestId('task-card-label-craft-0')
    expect(craft0).toHaveTextContent('韩褶')
    expect(craft0).toHaveTextContent('定高买宽')
    expect(craft0).toHaveTextContent('双开')
    expect(craft0).toHaveTextContent('定型')

    // 逐张对齐（错配 = 车间按错件干活）：第 2 张仍是布帘（双开第 2 份），第 3 张才是纱帘
    expect(screen.getByTestId('task-card-label-kind-1')).toHaveTextContent('部位 布帘')
    expect(screen.getByTestId('task-card-label-kind-2')).toHaveTextContent('部位 纱帘')
    expect(screen.getByTestId('task-card-label-kind-3')).toHaveTextContent('部位 帘头')
    const craft3 = screen.getByTestId('task-card-label-craft-3')
    expect(craft3).toHaveTextContent('平板')
    expect(craft3).not.toHaveTextContent('韩褶')
  })

  it('🔴 褶法 = 是否韩褶公式 + 折数（一个字段，2026-10-26 用户裁定）', () => {
    printCard()

    // item-1：韩褶公式 + pleat_count 52 ⇒ 「褶法 韩褶 52折」（双开的 2 张都一样）
    expect(screen.getByTestId('task-card-label-pleats-0')).toHaveTextContent('褶法 韩褶 52折')
    expect(screen.getByTestId('task-card-label-pleats-1')).toHaveTextContent('褶法 韩褶 52折')
    // item-2 没有快照行 ⇒ 判不出公式 ⇒ 该行**不印**（不猜）
    expect(screen.queryByTestId('task-card-label-pleats-2')).toBeNull()
  })

  it('🔴 褶法（反面对照）：倍数法 ⇒ 同一个字段印「倍数法」；无公式 ⇒ 该行不印', () => {
    // 换一份快照：公式串 = 褶倍数公式（倍数法）⇒ 不是韩褶公式，同一个字段就要如实说「倍数法」
    const multiple = [
      { ...items[0], formula_text: '褶倍数公式：(5.5÷2)×2 → 11.0米' },
    ] as unknown as ProcessingOrderItem[]
    printCard({ positions: [positions[0]], items: multiple })
    expect(screen.getByTestId('task-card-label-pleats-0')).toHaveTextContent('褶法 倍数法')
    expect(screen.getByTestId('task-card-label-pleats-0')).not.toHaveTextContent('韩褶')
  })

  it('特殊选项与备注**各成一行**；无对应快照行 ⇒ 该行不出现（不猜）', () => {
    printCard()

    expect(screen.getByTestId('task-card-label-special-options-0')).toHaveTextContent('特殊选项 加logo条、防翘扣')
    expect(screen.getByTestId('task-card-label-remark-0')).toHaveTextContent('备注 加铅块')
    expect(screen.getByTestId('task-card-label-remark-0')).not.toHaveTextContent('加logo条')

    // item-2 没有快照行 ⇒ 第 3 张（纱帘）不出颜色/用料/加工方式/特殊选项/备注/门幅（缺值不渲染，不猜）
    expect(screen.queryByTestId('task-card-label-color-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-meters-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-craft-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-special-options-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-remark-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-door-width-2')).toBeNull()
  })

  it('缺码部位 ⇒ 该张出占位（不画假码），其余张仍出真码', () => {
    const mixed: ProductionPosition[] = [
      { ...positions[0] },
      // 该部位没有码（未生成 / 已撤销）：读面三键全空
      { position_name: '纱帘B', order_item_id: 'item-2', part_token: null, part_short_code: null, scan_url: null, operations: [] },
      // 只有 part_token（`scan_url` 缺席）⇒ 仍按回退口径出真码
      { ...positions[2], scan_url: null },
    ]
    printCard({ positions: mixed, qrPlaceholderHint: '二维码已撤销（旧码已失效）' })

    // 张序：item-1 双开 = 0,1；item-2 = 2；item-3 三开 = 3,4,5
    const emptyLabel = screen.getByTestId('task-card-label-2')
    expect(within(emptyLabel).getByTestId('task-card-qr-placeholder')).toHaveTextContent(
      '二维码已撤销（旧码已失效）',
    )
    // 不画假码：该张里连一个 svg 都没有
    expect(emptyLabel.querySelector('svg')).toBeNull()
    expect(within(emptyLabel).queryByTestId('task-card-qr')).toBeNull()
    // 只有**那一个部位**的每一份都出占位（2 份三开 × 该部位 ⇒ 这里只 1 份缺码部位）
    expect(screen.getAllByTestId('task-card-qr-placeholder')).toHaveLength(1)

    // 其余张不受影响：真码照出（帘头那张回退到 part_token）
    expect(
      within(screen.getByTestId('task-card-label-0')).getByTestId('task-card-qr').querySelector('title')?.textContent,
    ).toBe(SCAN_BL)
    expect(
      within(screen.getByTestId('task-card-label-5')).getByTestId('task-card-qr').querySelector('title')?.textContent,
    ).toBe('part-token-lt-1')
  })

  it('缺省占位文案 = 待生成（缺码但不撤销时不得谎称「已撤销」）', () => {
    const noCode: ProductionPosition[] = [
      { position_name: '纱帘B', order_item_id: 'item-2', part_token: null, part_short_code: null, scan_url: null, operations: [] },
    ]
    printCard({ positions: noCode })

    const placeholder = screen.getByTestId('task-card-qr-placeholder')
    expect(placeholder).toHaveTextContent('待生成')
    expect(placeholder.textContent).not.toContain('已撤销')
    expect(screen.queryByTestId('task-card-qr')).toBeNull()
  })

  it('纸面抬头（2026-10-25）：企业名 + 「成品定制」**逐张**渲染，字号随正文一起抬（14pt / 10pt）', () => {
    companyNameStub.value = '亿家纺织'
    printCard()
    const headers = screen.getAllByTestId('task-card-company')
    // 「每张标签都要呈现」：6 张 ⇒ 6 个抬头块
    expect(headers).toHaveLength(6)
    expect(headers[0]).toHaveTextContent('亿家纺织')
    expect(headers[0]).toHaveTextContent('成品定制')
    // 字号口径：企业名 14pt 粗体 / 副标题 10pt（与 `wash-label-metrics` 同源）
    expect(within(headers[0]).getByText('亿家纺织').className).toContain('text-[14pt]')
    expect(within(headers[0]).getByText('成品定制').className).toContain('text-[10pt]')
    companyNameStub.value = ''
  })

  it('缺企业名 ⇒ 抬头块**整块不渲染**（不印空行、不印「未设置」）', () => {
    companyNameStub.value = ''
    printCard()
    expect(screen.queryByTestId('task-card-company')).toBeNull()
    // 订单号仍是第一行（抬头块与订单号互不依赖）
    expect(screen.getByTestId('task-card-label-order-no-0')).toHaveTextContent(`订单 ${ORDER_NO}`)
  })

  it('打印样式：@page 50mm×150mm（竖版）+ 标签本体 50mm×150mm + 正文 12pt + 逐张分页（最后一张不分页）', () => {
    printCard()

    // portal 到 body 的直接子级（打印隔离：容器自身的 class 才能被选择器选中）
    const area = printArea()
    expect(area.parentElement).toBe(document.body)

    const css = Array.from(area.querySelectorAll('style'))
      .map((el) => el.textContent || '')
      .join('\n')
    // 🔴 2026-10-26 用户逐字「长度不足，设置为打印50*150」⇒ 固定 50mm × 150mm；旧值一律不得残留
    expect(css).toContain('@page { size: 50mm 150mm; margin: 0; }')
    expect(css).not.toContain('50mm 70mm')
    expect(css).not.toContain('50mm 60mm')
    expect(css).not.toContain('30mm 60mm')
    expect(css).toContain('.task-card-label { width: 50mm; height: 150mm; overflow: hidden;')
    // 🔴 字号 9pt → 12pt（用户「字体还是太小，可以再大一点」）
    expect(css).toContain('font-size: 12pt')
    expect(css).toContain('break-after: page')
    // 最后一张不分页（否则末尾多吐一张空白）
    expect(css).toMatch(/\.task-card-label:last-child \{[^}]*break-after: auto/)
    // 屏幕隐藏、打印显形 + visibility 防御（ShipmentDoc 的 6 条约束，勿随手改）
    expect(css).toContain('.task-card-print-area { display: none; }')
    // 🔴 共享隔离选择器（issue #4983，来自 #4965 实测）：按「自己那一份」写会藏掉兄弟单据
    expect(css).toContain('body > *:not(.print-doc) { display: none !important; }')
    expect(css).not.toContain('body > *:not(.task-card-print-area)')
    // 容器必须带共享标记类（否则共享选择器选不到自己 ⇒ 打印整页空白）
    expect(area.className).toContain('print-doc')
    expect(css).toContain('.task-card-print-area, .task-card-print-area * { visibility: visible; }')
  })

  it('二维码：底部**居中**、尺寸放大到 80（用户 2026-10-26 三项裁定）', () => {
    printCard()

    const qr = screen.getAllByTestId('task-card-qr')[0]
    const bottomRow = qr.parentElement as HTMLElement
    expect(bottomRow.className).toContain('justify-center')
    expect(bottomRow.className).toContain('shrink-0')
    // qrcode.react 把 size 直接落到 svg 的 width/height 属性
    expect(qr.getAttribute('width')).toBe('80')
    // 正文块 → 底部码行的顺序：码在所有文字之后（DOM 序）
    const label = screen.getByTestId('task-card-label-0')
    const rowsBlock = within(label).getByTestId('task-card-label-rows-0')
    expect(rowsBlock.compareDocumentPosition(bottomRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('🔴 工序摘要与完整套号**不再出现**（退场项；改回来 ⇒ 必红）', () => {
    printCard()

    // ① 工序摘要退场：连"工序"二字都不该在纸面上（工人扫部位码后在 H5 看工序清单）
    expect(screen.queryByTestId('task-card-label-ops-0')).toBeNull()
    expect(paperTextOf(printArea())).not.toContain('工序')

    // ② 完整套号退场（与加工单号重复，纯占纸面）
    expect(screen.queryByTestId('task-card-label-set-code-0')).toBeNull()
    expect(paperTextOf(printArea())).not.toContain(`${PROCESSING_ORDER_NO}-001`)
    expect(paperTextOf(printArea())).not.toContain(`${PROCESSING_ORDER_NO}-002`)

    // ③ 变体名（工人端快照名）一个都不许上纸面（issue #4621 回归守卫）
    expect(paperTextOf(printArea())).not.toContain('精裁-布')
    expect(paperTextOf(printArea())).not.toContain('韩褶-纱')
    expect(paperTextOf(printArea())).not.toContain('精裁-帘头')
  })

  it('0 个部位 ⇒ 一张显式占位（不是空白、不造多张）', () => {
    printCard({ positions: [] })

    expect(screen.getAllByTestId('task-card-label-0')).toHaveLength(1)
    expect(screen.queryByTestId('task-card-label-1')).toBeNull()
    expect(screen.getByTestId('task-card-label-0')).toHaveTextContent('该加工单暂无商品/无码可打印')
    // 缺码 ⇒ 占位框（不画假码）
    expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument()
  })
})
