// case_ids: PP-011
// PP-011（issue #4964 立版式 → #5646 纸宽 → #7776 字号/字段 → #7816 固定 50×150 → #7833 纸面改版
// → #7948：50×150 → 50×110 → #7960：50×110 → 50×119 → **issue #7979（2026-10-28）：50×119 → 50×140、上下各留白 15mm、二维码紧挨正文**）：
// 水洗唛 = **竖版 50mm × 140mm 单列**，字段面 = 纸面抬头（企业名 / 成品定制）+ **单号（加工单号，第一行）** /
// 客户 / 第 N 套共 M 套 / **帘种** / **货号（值 = 颜色内容；issue #7872 起文案由「颜色」改「货号」）** /
// 安装小区 / 安装位置 / 门幅 / 用料 / 宽高 / **加工方式（含加工费组合项、无前缀）** /
// **褶法** / 特殊选项 / 备注 / **布料批次（末行，值 = 快照 `batchNo`，issue #7872）** + 底部**居中**二维码。
// 一行粒度 = 一部位（商品行）**一张 × 开数份**。
//
// 用户 2026-10-26 逐字（issue #7833，逐条都能判红）：
// ① 「JG-…-8172 这个加工单有超高倒幅，但是在加工单的各个环节都没有体现出来，打印的洗水唛中也需要
//    体现加工费组合中的信息」⇒ 加工方式行**并入** `processingItems[].name`（超高 / 倒幅 …）；
// ② 「加工方式这几个字可以移除」⇒ 该行**只印值**（纸面不得出现「加工方式」四字）；
// ③ 「把定高买宽和定宽买高的工艺规格信息不要展示在洗水唛上」⇒ 不印加工类型；
// ④ 「订单号是否可以短一些…只留加工单号，删掉订单行」⇒ 第一行 `单号 JG-…`，17 位订单号不上纸；
// ⑤ 「打印后的结果出现了文字缩写…自动去换行打印」⇒ 行样式里**没有** truncate / line-clamp（折行印全文）；
// ⑥ 「头尾加下虚线，这样能清晰知道界线」⇒ `.task-card-label` 一条 `1px dashed`；
//    issue #7839 后续裁定「水洗唛的顶部虚线移除掉」⇒ **只留底部**（顶部再画 ⇒ 必红）。
//
// 沿用 #7816 且后经 #7960 调整的判据：正文 11pt / 张数 = Σ 开数 / 褶法 / 二维码底部居中
// / 打印隔离 6 条 / 缺码不画假码 / 退场项（工序摘要 / 完整套号 / 交期 / 短码 / 扫码报工）。
// 2026-10-27（issue #7948）：「把水洗唛的尺寸改成50*110，现在偏长了」「二维码不能直接沉底，
// 务必和底部留点距离」⇒ 纸型 140mm、`padding-bottom: 6mm`（二维码下沿与底部虚线恒 ≥ 6mm）。
//
// 其余沿用既有契约（改回来 ⇒ 必红）：打印隔离 6 条、一部位一码 / 缺码不画假码、纸面内容 = `washLabelRows`、
// 退场两项（工序摘要 / 完整套号）、变体名不上纸面、缺值不渲染。
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import { washLabelRows } from '@/lib/wash-label-content'
import {
  WASH_LABEL_BOTTOM_CLEARANCE_MM,
  WASH_LABEL_PADDING_MM,
  WASH_LABEL_EMPHASIS_ROW_KEYS,
  WASH_LABEL_TOP_BLANK_MM,
} from '@/lib/label-print/wash-label-metrics'
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
const source = readFileSync(join(process.cwd(), 'src/components/production/TaskCardPrint.tsx'), 'utf-8')
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
    sku: '0012',
    colorName: '米白',
    // 布料批次（快照键 `batchNo`）：纸面**末行**（issue #7872）
    batchNo: 'PC-20261026-0001',
    // 安装去向（issue #7856）：小区 = 订单级（随快照逐行固化）、位置 = 件级
    installCommunity: '春江花园 3栋2单元',
    installRoom: '主卧',
    doorWidth: '2.8米',
    curtainType: '布帘',
    craft: '韩褶',
    cuttingMode: '定高买宽',
    openCount: 2,
    isShaped: true,
    // 加工费组合键（issue #7833）：超高 / 倒幅 就在这个数组里 —— 纸面必须体现出来
    processingItems: [
      { id: 'pi-1', name: '韩褶', quantity: 1 },
      { id: 'pi-14', name: '超高', quantity: 1 },
      { id: 'pi-16', name: '倒幅', quantity: 1 },
      { id: 'pi-3', name: '定型', quantity: 1 },
    ],
    specialOptions: ['加logo条', '防翘扣'],
    remark: '加铅块',
    fabric_meters: 6.3,
    pleat_count: 52,
    formula_text: '韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米',
  },
  {
    itemId: 'item-3',
    productName: '帘头布',
    sku: '0031',
    colorName: '米灰',
    // 布料批次（逐张跟着快照行走：第 4/5/6 张 = 帘头那 3 份）
    batchNo: 'PC-20261025-0007',
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
      processingOrderNo={PROCESSING_ORDER_NO}
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

describe('TaskCardPrint（水洗唛 竖版 50mm×140mm 单列，issue #7979）', () => {
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

  it('🔴 加工项（加工方式行）= **加黑加粗**，其余行不加粗（用户 2026-10-28「把加工项信息加黑加粗」，issue #7987）', () => {
    printCard()

    const craft = screen.getByTestId('task-card-label-craft-0')
    expect(craft.className).toContain('font-bold')
    // 反向对照：同一张纸上别的行**不得**加粗（全纸加粗 = 没有重点，等于没做）
    for (const other of ['customer', 'color', 'remark', 'door-width']) {
      const row = screen.queryByTestId(`task-card-label-${other}-0`)
      if (!row) continue
      expect(row.className).not.toContain('font-bold')
    }
    // 🔴 单一真值：加粗行由 metrics 的一份常量决定（两条通道同源），组件里不许另写死行名
    expect(WASH_LABEL_EMPHASIS_ROW_KEYS).toContain('craft')
    expect(source).toContain('WASH_LABEL_EMPHASIS_ROW_KEYS.includes(row.key)')
  })

  it('🔴 单号 = **加工单号（去 `JG-` 前缀）**（第一行、客户之上）；17 位订单号不上纸（issue #7833 / #7839）', () => {
    printCard()

    const rowsBlock = screen.getByTestId('task-card-label-rows-0')
    expect(rowsBlock.firstElementChild?.getAttribute('data-testid')).toBe('task-card-label-doc-no-0')
    expect(screen.getByTestId('task-card-label-doc-no-0')).toHaveTextContent('单号: 20260921-8237')
    expect(rowsBlock.children[1]?.getAttribute('data-testid')).toBe('task-card-label-customer-0')
    // 🔴 issue #7986（2026-10-28「把安装小区和安装位置放置到客户那一行下面」）：
    //    第 3、4 行 = 安装小区 / 安装位置（改回「帘种之后」⇒ 必红）
    expect(rowsBlock.children[2]?.getAttribute('data-testid')).toBe('task-card-label-install-community-0')
    expect(rowsBlock.children[3]?.getAttribute('data-testid')).toBe('task-card-label-install-room-0')

    const paper = paperTextOf(printArea())
    // 🔴 退场：17 位订单号（用户 2026-10-26「订单号是否可以短一些…只留加工单号，删掉订单行」）
    expect(paper).not.toContain(ORDER_NO)
    expect(paper).not.toContain('订单 ')
    // 🔴 纸面不出现 `JG-` 前缀（issue #7839 用户「加工单号不要带 JG- 了，简约点」）
    expect(paper).not.toContain('JG-')
    // 人可读短码 / 「扫码报工」仍不在纸面上（#7816 的退场项，本次未改）
    expect(document.querySelector('[data-testid^="task-card-label-short-code-"]')).toBeNull()
    expect(paper).not.toContain('扫码报工')
    // 🔴 退场：交期（2026-10-26「移除交期字段」）
    expect(paper).not.toContain('交期')
    expect(paper).not.toContain(DELIVERY)
  })

  it('🔴 加工方式行 = 加工费组合项 + 打开方式 + 定型（**无前缀**、**不印加工类型**）', () => {
    printCard()

    const craft = screen.getByTestId('task-card-label-craft-0')
    // 组合项（超高 / 倒幅）必须出现在纸上 —— 这正是用户「加工单有超高倒幅…没有体现出来」的落点
    expect(craft).toHaveTextContent('韩褶')
    expect(craft).toHaveTextContent('超高')
    expect(craft).toHaveTextContent('倒幅')
    expect(craft).toHaveTextContent('双开')
    expect(craft).toHaveTextContent('定型')
    // 🔴 去前缀：纸面不得出现「加工方式」四字
    expect(craft.textContent).not.toContain('加工方式')
    // 🔴 不印加工类型（「定高买宽 / 定宽买高」都不上纸）
    expect(craft.textContent).not.toContain('定高买宽')
    expect(craft.textContent).not.toContain('定宽买高')
    expect(paperTextOf(printArea())).not.toContain('加工类型')
    // 定型不重复：组合项里的「定型」不与该行的定型措辞印两遍
    expect((craft.textContent || '').split('定型').length - 1).toBe(1)
  })

  it('纸面内容与行序 = `washLabelRows`（单一真值；两条通道读同一份）', () => {
    printCard()

    const expected = washLabelRows({
      position: positions[0],
      item: items[0],
      setNo: 1,
      setCount: 2,
      customerName: CUSTOMER,
      processingOrderNo: PROCESSING_ORDER_NO,
    })
    const rowsBlock = screen.getByTestId('task-card-label-rows-0')
    const painted = Array.from(rowsBlock.children).map((el) => (el.textContent || '').trim())
    expect(painted).toEqual(expected.map((row) => row.text))
    // 正向锚：确实印了足够多的行（不是空清单）
    expect(painted.length).toBeGreaterThanOrEqual(10)
  })

  it('单列字段逐张渲染：帘种 / 货号 / 安装信息 / 门幅 / 用料 / 宽高 / 加工方式 / 布料批次（照真实工单信息顺序）', () => {
    printCard()

    // 第 1 张（布帘）：帘种 / 颜色 / 安装小区 / 安装位置 / 门幅 / 用料 / 宽高 / 加工方式
    expect(screen.getByTestId('task-card-label-kind-0')).toHaveTextContent('帘种: 布帘')
    // issue #7872（用户 2026-10-26 逐字「这里的颜色文案改成货号，右侧的内容不要变化了」）：
    // 文案 = `货号`、值 = `colorName` 原样（一字不动）
    expect(screen.getByTestId('task-card-label-color-0')).toHaveTextContent('货号: 米白')
    expect(screen.getByTestId('task-card-label-color-0')).not.toHaveTextContent('颜色')
    expect(screen.getByTestId('task-card-label-install-community-0')).toHaveTextContent(
      '安装小区: 春江花园 3栋2单元',
    )
    expect(screen.getByTestId('task-card-label-install-room-0')).toHaveTextContent('安装位置: 主卧')
    expect(screen.getByTestId('task-card-label-door-width-0')).toHaveTextContent('门幅: 2.8米')
    expect(screen.getByTestId('task-card-label-meters-0')).toHaveTextContent('用料: 6.3米')
    expect(screen.getByTestId('task-card-label-size-0')).toHaveTextContent('宽高: 3×2.75米')
    // 🔴 布料批次 = 纸面**末行**（issue #7872 用户逐字「放在最下面，布料批次：xxx」）
    expect(screen.getByTestId('task-card-label-batch-no-0')).toHaveTextContent('布料批次: PC-20261026-0001')
    // 位置判据：它在整块行清单的**最后一条**（插到别处 ⇒ 必红）
    const rowsBlock0 = screen.getByTestId('task-card-label-rows-0')
    expect(rowsBlock0.lastElementChild).toBe(screen.getByTestId('task-card-label-batch-no-0'))
    // 加工方式 = craft-display + processing-combo 的单一真值（工艺 / 组合项 / 打开方式 / 定型），不另写推导
    const craft0 = screen.getByTestId('task-card-label-craft-0')
    expect(craft0).toHaveTextContent('韩褶')
    expect(craft0).toHaveTextContent('超高')
    expect(craft0).toHaveTextContent('倒幅')
    expect(craft0).toHaveTextContent('双开')
    expect(craft0).toHaveTextContent('定型')
    expect(craft0.textContent).not.toContain('定高买宽')

    // 逐张对齐（错配 = 车间按错件干活）：第 2 张仍是布帘（双开第 2 份），第 3 张才是纱帘
    expect(screen.getByTestId('task-card-label-kind-1')).toHaveTextContent('帘种: 布帘')
    expect(screen.getByTestId('task-card-label-kind-2')).toHaveTextContent('帘种: 纱帘')
    expect(screen.getByTestId('task-card-label-kind-3')).toHaveTextContent('帘种: 帘头')
    const craft3 = screen.getByTestId('task-card-label-craft-3')
    expect(craft3).toHaveTextContent('平板')
    expect(craft3).not.toHaveTextContent('韩褶')
  })

  it('🔴 褶法 = 是否韩褶公式 + 折数（一个字段，2026-10-26 用户裁定）', () => {
    printCard()

    // item-1：韩褶公式 + pleat_count 52 ⇒ 「韩褶公式 52折」**无前缀**（issue #7856）
    // （用户逐字「褶法：去掉，只保留后面的文字，和工艺一样」）
    expect(screen.getByTestId('task-card-label-pleats-0')).toHaveTextContent('韩褶公式 52折')
    expect(screen.getByTestId('task-card-label-pleats-0')).not.toHaveTextContent('褶法')
    expect(screen.getByTestId('task-card-label-pleats-1')).toHaveTextContent('韩褶公式 52折')
    // item-2 没有快照行 ⇒ 判不出公式 ⇒ 该行**不印**（不猜）
    expect(screen.queryByTestId('task-card-label-pleats-2')).toBeNull()
  })

  it('🔴 褶法（反面对照）：倍数法 ⇒ 同一个字段印「倍数法」；无公式 ⇒ 该行不印', () => {
    // 换一份快照：公式串 = 褶倍数公式（倍数法）⇒ 不是韩褶公式，同一个字段就要如实说「倍数法」
    const multiple = [
      { ...items[0], formula_text: '褶倍数公式：(5.5÷2)×2 → 11.0米' },
    ] as unknown as ProcessingOrderItem[]
    printCard({ positions: [positions[0]], items: multiple })
    expect(screen.getByTestId('task-card-label-pleats-0')).toHaveTextContent('倍数法')
    expect(screen.getByTestId('task-card-label-pleats-0')).not.toHaveTextContent('韩褶')
  })

  it('特殊选项与备注**各成一行**；无对应快照行 ⇒ 该行不出现（不猜）', () => {
    printCard()

    expect(screen.getByTestId('task-card-label-special-options-0')).toHaveTextContent('特殊选项: 加logo条、防翘扣')
    expect(screen.getByTestId('task-card-label-remark-0')).toHaveTextContent('备注: 加铅块')
    expect(screen.getByTestId('task-card-label-remark-0')).not.toHaveTextContent('加logo条')

    // item-2 没有快照行 ⇒ 第 3 张（纱帘）不出货号/安装信息/用料/加工方式/特殊选项/备注/门幅/布料批次
    // （缺值不渲染，不猜）
    expect(screen.queryByTestId('task-card-label-color-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-install-community-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-install-room-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-meters-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-craft-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-special-options-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-remark-2')).toBeNull()
    expect(screen.queryByTestId('task-card-label-door-width-2')).toBeNull()
    // 无快照行 ⇒ 布料批次整行不出现（不印「布料批次: —」冒充「未指派」）
    expect(screen.queryByTestId('task-card-label-batch-no-2')).toBeNull()
  })

  it('🔴 布料批次（issue #7872）：有 `batchNo` 印真值；未指派批次如实 `—`；无快照行整行不出现', () => {
    // 有批次 ⇒ 真值原样（不缩写、不加字）
    const first = printCard()
    expect(screen.getByTestId('task-card-label-batch-no-0')).toHaveTextContent('布料批次: PC-20261026-0001')
    // 逐张跟着快照行走：第 4 张 = 帘头第 1 份
    expect(screen.getByTestId('task-card-label-batch-no-3')).toHaveTextContent('布料批次: PC-20261025-0007')
    first.unmount()
    // 未指派批次（快照行在、`batchNo` 缺）= 「未指派」≠「本系统没有这个字段」⇒ 如实 `—`
    const unassigned = [{ ...items[0], batchNo: undefined }] as unknown as ProcessingOrderItem[]
    printCard({ items: unassigned })
    expect(screen.getByTestId('task-card-label-batch-no-0')).toHaveTextContent('布料批次: —')
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
    // 单号仍是第一行（抬头块与单号互不依赖；issue #7839 起不带 `JG-`）
    expect(screen.getByTestId('task-card-label-doc-no-0')).toHaveTextContent('单号: 20260921-8237')
  })

  it('🔴 专属唛（issue #8002 / #8074）：勾了余料带回 / 绑带 ⇒ 每套每类别 1 张、紧跟本套常规唛（每套连续），副标题 = 成品定制 · 类别（12pt 加粗）', () => {
    companyNameStub.value = '亿家纺织'
    const optionItems = [
      { ...items[0], specialOptions: ['余料带回-布', '布绑带'] },
      items[1],
    ] as unknown as ProcessingOrderItem[]
    printCard({ items: optionItems })

    // 常规 6 张（2 + 1 + 3）+ 专属 2 张（余料带回 / 绑带 各 1 张，**不乘开数**）
    const labels = screen.getAllByTestId(/^task-card-label-\d+$/)
    expect(labels).toHaveLength(8)

    // 常规唛副标题仍是「成品定制」（10pt，无标记 testid）；专属唛才有标记
    expect(screen.getAllByText('成品定制')).toHaveLength(6)
    const markers = screen.getAllByTestId('task-card-option-label')
    expect(markers).toHaveLength(2)
    expect(markers[0]).toHaveTextContent('成品定制 · 余料带回')
    expect(markers[1]).toHaveTextContent('成品定制 · 绑带')
    expect(markers[0].className).toContain('text-[12pt]')
    expect(markers[0].className).toContain('font-bold')

    // 专属唛 = 该部位自己的码与行清单（内容同源，不另造）
    // 张序（issue #8074，用户 2026-10-29「每套连续排版，不要拆开」）：
    // 第 1 套 = 布 ×2 + 纱 ×1 → 余料 / 绑带；第 2 套 = 帘头 ×3（改前：专属唛整体追加到最后）
    const extra = labels[3]
    expect(within(extra).getByTestId('task-card-label-special-options-3')).toHaveTextContent(
      '特殊选项: 余料带回-布、布绑带',
    )
    expect(within(extra).getByTestId('task-card-qr').querySelector('title')?.textContent).toBe(SCAN_BL)
    expect(within(labels[4]).getByTestId('task-card-option-label')).toHaveTextContent('成品定制 · 绑带')
    // 第 2 套从第 6 张开始 —— 专属唛不得再被排到它之后
    expect(within(labels[5]).getByTestId('task-card-label-set-no-5')).toHaveTextContent('第 2 套 / 共 2 套')
    companyNameStub.value = ''
  })

  it('🔴 缺企业名：常规唛不出抬头块，专属唛的标记照印（标记不依赖企业名是否设置）', () => {
    companyNameStub.value = ''
    const optionItems = [
      { ...items[0], specialOptions: ['余料带回-布'] },
      items[1],
    ] as unknown as ProcessingOrderItem[]
    printCard({ items: optionItems })

    const headers = screen.getAllByTestId('task-card-company')
    expect(headers).toHaveLength(1)
    expect(headers[0]).toHaveTextContent('成品定制 · 余料带回')
    expect(within(headers[0]).queryByText('亿家纺织')).toBeNull()
    // 专属唛也带本部位的码（与常规唛同一个码，不做第二套码）；第 1 套专属唛紧跟本套常规唛（#8074）
    expect(within(screen.getByTestId('task-card-label-3')).getByTestId('task-card-qr')).toBeTruthy()
  })

  it('打印样式：@page 50mm×140mm（竖版）+ 标签本体 50mm×140mm + 上下各留白 15mm（码距底虚线 15mm）+ 正文 11pt + 逐张分页（最后一张不分页）', () => {
    printCard()

    // portal 到 body 的直接子级（打印隔离：容器自身的 class 才能被选择器选中）
    const area = printArea()
    expect(area.parentElement).toBe(document.body)

    const css = Array.from(area.querySelectorAll('style'))
      .map((el) => el.textContent || '')
      .join('\n')
    // 🔴 2026-10-28 用户逐字「这样尺寸就能缩小到50*140」⇒ 固定 50mm × 140mm / 正文 11pt；旧值一律不得残留
    expect(css).toContain('@page { size: 50mm 140mm; margin: 0; }')
    expect(css).not.toContain('50mm 150mm')
    expect(css).not.toContain('50mm 70mm')
    expect(css).not.toContain('50mm 60mm')
    expect(css).not.toContain('30mm 60mm')
    expect(css).toContain('.task-card-label { width: 50mm; height: 140mm; overflow: hidden;')
    // 🔴 2026-10-28 用户逐字「多的30要添加到顶部和底部虚线下处各15，顶部需要让最顶端的字体上面留白15」
    //    ⇒ 上内边距 = 顶部留白 15mm、下内边距 = 码与底部虚线的净空 15mm
    //    （与画布通道读**同一组**常量，两条通道不会各写一份）
    expect(css).toContain(
      `padding: ${WASH_LABEL_TOP_BLANK_MM}mm ${WASH_LABEL_PADDING_MM}mm ${WASH_LABEL_BOTTOM_CLEARANCE_MM}mm;`,
    )
    // 🔴 字号 9pt → 11pt（用户「字体还是太小，可以再大一点」）
    expect(css).toContain('font-size: 11pt')
    // 🔴 头尾虚线（issue #7833「头尾加下虚线，这样能清晰知道界线」）
    expect(css).toContain('border-bottom: 1px dashed #000')
    // 🔴 issue #7839：顶部那条虚线**已移除**（用户逐字「水洗唛的顶部虚线移除掉」）
    expect(css).not.toContain('border-top: 1px dashed')
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

  it('🔴 折行印全文：每一行**没有** truncate / line-clamp（省略号 = 静默吃掉半截字）', () => {
    printCard()

    const paper = paperTextOf(printArea())
    // 长值真的渲染出来（不是被裁掉的空壳）：客户 / 特殊选项 / 备注 逐字在纸上
    expect(paper).toContain(`客户: ${CUSTOMER}`)
    expect(paper).toContain('特殊选项: 加logo条、防翘扣')
    expect(paper).toContain('备注: 加铅块')
    const rowsBlock = screen.getByTestId('task-card-label-rows-0')
    for (const row of Array.from(rowsBlock.children)) {
      const cls = row.className
      expect(cls).not.toContain('truncate')
      expect(cls).not.toMatch(/line-clamp-\d/)
      expect(cls).not.toContain('text-ellipsis')
    }
    // 至少一行声明了折行（否则「去裁切」只是把字挤出纸外）
    expect(Array.from(rowsBlock.children).some((row) => row.className.includes('break-words') || row.className.includes('break-all'))).toBe(true)
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
