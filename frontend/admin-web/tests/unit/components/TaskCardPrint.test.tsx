// case_ids: PP-011
// PP-011（issue #4964 立版式 / **issue #5646 改判纸宽 30mm → 50mm**，用户裁定 2026-09-26 逐字
// 「洗水码宽是50，长度根据我们实际需要来定」）：洗水码 = **竖版 50mm × 60mm 单列**，照**真实工单**
// （亿家纺织「成品定制」58mm 竖排小票：单号/客户/第N套共M套/宽高/加工方式/用料表/备注/QR）的信息顺序。
// 字段面 = 加工单号 / 客户 / 第N套共M套 / 部位 / 件名 / 色号 / 用料 / 宽高 / 加工方式 / 订单号 /
// 交期 / 备注 / 算料公式 + 二维码与**大字**人可读短码。
//
// 🔴 **退场两项**（用户 2026-09-21 字段裁定**未选**；改回来 ⇒ 本条必红）：
//   ① **工序摘要**（工人扫部位码后在 H5 看该部位工序清单，纸面不印）；
//   ② **完整套号**（`JG-…-001`，与行①的加工单号重复）。
//
// 🔴 **30mm → 50mm 时被推翻的三条「窄版心妥协」**（宽 30→50 把版心由 27.6mm 抬到 47.599mm，+72%）：
//   ① **件名不再 clamp 到 2 行**（该 clamp 当年只为 27.6mm 版心而设；本版**去掉 clamp**）；
//   ② **加工方式不再折 2 行**（实测最长形态在 47.599mm 下恰好 1 行，`line-clamp-2` 仅作预算上界）；
//   ③ **算料公式 clamp 3 行 → 2 行**（两条真公式串在 47.599mm 下都恰好 2 行；容量 2×22.5em=45em
//      反而 > 旧口径 3×13em=39em，且省下 2.538mm —— 最坏情况能收进 60mm 正是靠这一步）。
//   色号的**去重**（件名已含色号 ⇒ 不重复渲染）**保留**：50mm 下恢复独立渲染只是多印一遍同名信息。
//
// 逐条判据（都能判红）：
// ① 3 个部位 ⇒ 恰 3 张（`task-card-label-0..2`），加工单公共属性**逐张**都在；
// ② 三张码三个值（= 各部位自己的 `scan_url`）—— 本条**核心判据**（改回单张/单值 ⇒ 必红）；
// ③ 缺码部位 ⇒ 该张出占位（不画假码），其余张仍出真码；
// ④ 人可读短码逐张渲染且为**大字**（`text-[8pt]`），缺码位如实「—」；
// ⑤ 打印样式：`@page { size: 50mm 60mm; margin: 0 }` + 标签本体 50mm×60mm + 逐张分页（最后一张不分页）
//    —— **几何整版改判**（issue #5646 推翻 #4946 的 30mm 宽）；逐值实测读数见组件文件头第 5 条；
// ⑥ **工序摘要与完整套号不再出现**（防复发守卫）；
// ⑦ 主标识**不折行不省略**：加工单号 `shrink-0 whitespace-nowrap`、订单号 `whitespace-nowrap`
//    —— 60×30 横版时代的实测教训（issue #4949：折行吃 2.96mm ⇒ 纸面底部短码被裁 1.25mm）；
// ⑧ 0 个部位 ⇒ 一张显式占位（不是空白）；
// ⑨ 缺值不渲染：无对应快照行 / 无键 ⇒ 该行不出现，纸面不出现 `undefined` / `null` / `NaN`；
// ⑩ **重算后的字段折行预算**（issue #5646）：件名无 clamp / 加工方式与备注各 ≤2 行 / 算料公式 ≤2 行。
import type { ComponentProps } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

const PROCESSING_ORDER_NO = 'JG-20260921-8237'
/** 真实形态的 17 位订单号（真库实证 20260921973550001）—— 必须**不截断** */
const ORDER_NO = '20260921973550001'
const CUSTOMER = '赵凯'
const DELIVERY = '2026-09-28'

const SCAN_BL = 'https://app.migaozn.com/s/7K3M9QP2'
const SCAN_SHA = 'https://app.migaozn.com/s/QW8Z2N4B'
const SCAN_LT = 'https://app.migaozn.com/s/ZX5C7V1N'
const SHORT_BL = '7K3M9QP2'
const SHORT_SHA = 'QW8Z2N4B'
const SHORT_LT = 'ZX5C7V1N'

/**
 * 三个部位（= 三个商品行）分属**两套**（布帘+纱帘 = 第 1 套；帘头 = 第 2 套）——
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
    part_short_code: SHORT_BL,
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
    part_short_code: SHORT_SHA,
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
    part_short_code: SHORT_LT,
    scan_url: SCAN_LT,
    operations: [
      { id: 'op-4', seq: 1, operation: '精裁-帘头', logical_name: '精裁', position: '帘头', unit: '套', qty: 1, status: 'pending', done_qty: 0 },
    ],
  },
]

/** 加工单快照明细（`items_snapshot` 口径；`itemId` = 行主键，与 `position.order_item_id` 对齐） */
const items = [
  {
    itemId: 'item-1',
    productName: '2699系列雪尼尔窗帘面料',
    colorName: '米白',
    curtainType: '布帘',
    craft: '韩褶',
    cuttingMode: '定高买宽',
    openCount: 2,
    isShaped: true,
    specialOptions: ['加logo条', '防翘扣'],
    fabric_meters: 6.3,
    formula_text: '韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米',
  },
  {
    itemId: 'item-3',
    productName: '帘头布',
    colorName: '米灰',
    curtainType: '帘头',
    craft: '平板',
  },
] as unknown as ProcessingOrderItem[]

/** 公共属性（每张都必须呈现） */
const printCard = (overrides: Partial<ComponentProps<typeof TaskCardPrint>> = {}) =>
  render(
    <TaskCardPrint
      processingOrderNo={PROCESSING_ORDER_NO}
      orderNo={ORDER_NO}
      customerName={CUSTOMER}
      expectedDeliveryDate={DELIVERY}
      positions={positions}
      items={items}
      {...overrides}
    />,
  )

const printArea = () => document.querySelector('.task-card-print-area') as HTMLElement

describe('TaskCardPrint（洗水码 竖版 50mm×60mm 单列，issue #4964 → 纸宽改判 #5646）', () => {
  it('3 个部位 ⇒ 恰 3 张洗水码，加工单公共属性**逐张**都在（加工单号/客户/套序/订单号/交期）', () => {
    printCard()

    const labels = [0, 1, 2].map((i) => screen.getByTestId(`task-card-label-${i}`))
    // 粒度 = 商品行 = 部位（每行一张），第 4 张不存在
    expect(screen.queryByTestId('task-card-label-3')).toBeNull()

    labels.forEach((label, i) => {
      expect(within(label).getByTestId('task-card-no')).toHaveTextContent(PROCESSING_ORDER_NO)
      expect(within(label).getByTestId('task-card-order-no')).toHaveTextContent(ORDER_NO)
      expect(label).toHaveTextContent(CUSTOMER)
      expect(label).toHaveTextContent(DELIVERY)
      // 套序走 `groupBySet`（与进度表同一份实现）
      expect(within(label).getByTestId(`task-card-label-set-no-${i}`)).toBeInTheDocument()
    })

    // 布帘/纱帘同套、帘头第 2 套
    expect(screen.getByTestId('task-card-label-set-no-0')).toHaveTextContent('第 1 套 / 共 2 套')
    expect(screen.getByTestId('task-card-label-set-no-1')).toHaveTextContent('第 1 套 / 共 2 套')
    expect(screen.getByTestId('task-card-label-set-no-2')).toHaveTextContent('第 2 套 / 共 2 套')

    // 🔴 主标识不折行不省略（issue #4949 的实测教训：折行会把纸面底部内容挤出纸外）
    const label0 = screen.getByTestId('task-card-label-0')
    expect(within(label0).getByTestId('task-card-no').className).toContain('shrink-0')
    expect(within(label0).getByTestId('task-card-no').className).toContain('whitespace-nowrap')
    expect(within(label0).getByTestId('task-card-order-no').className).toContain('whitespace-nowrap')
  })

  it('三张码三个值：每张二维码内容 = 该部位自己的 scan_url（本单核心判据）', () => {
    printCard()

    const codes = screen.getAllByTestId('task-card-qr')
    expect(codes).toHaveLength(3)

    const expected = [SCAN_BL, SCAN_SHA, SCAN_LT]
    expected.forEach((value, i) => {
      const qr = within(screen.getByTestId(`task-card-label-${i}`)).getByTestId('task-card-qr')
      expect(qr.tagName.toLowerCase()).toBe('svg')
      expect(within(qr).getByTitle(value)).toBeInTheDocument()
      expect(qr.querySelectorAll('path').length).toBeGreaterThan(0)
    })
    // 逐张不同：三张码三个值（改回「一单一张/一张一值」⇒ 本条必红）
    expect(codes.map((qr) => qr.querySelector('title')?.textContent)).toEqual(expected)
    expect(new Set(expected).size).toBe(3)
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

    const emptyLabel = screen.getByTestId('task-card-label-1')
    expect(within(emptyLabel).getByTestId('task-card-qr-placeholder')).toHaveTextContent(
      '二维码已撤销（旧码已失效）',
    )
    // 不画假码：该张里连一个 svg 都没有
    expect(emptyLabel.querySelector('svg')).toBeNull()
    expect(within(emptyLabel).queryByTestId('task-card-qr')).toBeNull()
    expect(screen.getAllByTestId('task-card-qr-placeholder')).toHaveLength(1)

    // 其余张不受影响：真码照出（第 3 张回退到 part_token）
    expect(
      within(screen.getByTestId('task-card-label-0')).getByTestId('task-card-qr').querySelector('title')?.textContent,
    ).toBe(SCAN_BL)
    expect(
      within(screen.getByTestId('task-card-label-2')).getByTestId('task-card-qr').querySelector('title')?.textContent,
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
    // 公共属性仍在（纸面能认出是哪张单的哪一件）
    expect(screen.getByTestId('task-card-label-0')).toHaveTextContent(PROCESSING_ORDER_NO)
  })

  it('人可读短码逐张渲染且为**大字**（扫码枪/人眼读不出时的手输降级入口）', () => {
    printCard()

    const expected = [SHORT_BL, SHORT_SHA, SHORT_LT]
    expected.forEach((code, i) => {
      const el = screen.getByTestId(`task-card-label-short-code-${i}`)
      expect(el).toHaveTextContent(code)
      // 大字契约：≥8pt（小字会被车间灯光/磨损吃掉 —— 降级入口不可用就等于没有）
      expect(el.className).toContain('text-[8pt]')
      expect(el.className).toContain('font-bold')
    })
  })

  it('缺短码的序号仍保留该行（不得与人可读短码一起消失），且码仍出', () => {
    const noShort: ProductionPosition[] = [
      { position_name: '纱帘B', order_item_id: 'item-2', part_token: 'part-token-x', part_short_code: null, scan_url: null, operations: [] },
    ]
    printCard({ positions: noShort })

    expect(screen.getByTestId('task-card-label-short-code-0')).toHaveTextContent('—')
    expect(screen.getByTestId('task-card-qr').querySelector('title')?.textContent).toBe('part-token-x')
  })

  it('打印样式：@page 50mm×60mm（竖版）+ 标签本体 50mm×60mm 且逐张分页（最后一张不分页）', () => {
    printCard()

    // portal 到 body 的直接子级（打印隔离：容器自身的 class 才能被选择器选中）
    const area = printArea()
    expect(area).not.toBeNull()
    expect(area.parentElement).toBe(document.body)

    const css = area.querySelector('style')?.textContent ?? ''
    // 🔴 几何整版改判（issue #5646）：纸宽 30mm → **50mm**。旧值 30mm 一律不得残留（留一条即假绿）
    expect(css).toContain('@page { size: 50mm 60mm; margin: 0; }')
    expect(css).not.toContain('30mm 60mm')
    expect(css).toContain('.task-card-label { width: 50mm; height: 60mm; overflow: hidden;')
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

    ;[0, 1, 2].forEach((i) => expect(screen.getByTestId(`task-card-label-${i}`).className).toContain('task-card-label'))
  })

  it('🔴 工序摘要与完整套号**不再出现**（issue #4964 的退场两项；改回来 ⇒ 必红）', () => {
    printCard()

    // ① 工序摘要退场：连"工序"二字都不该在纸面上（工人扫部位码后在 H5 看工序清单）
    expect(screen.queryByTestId('task-card-label-ops-0')).toBeNull()
    expect(screen.queryByTestId('task-card-label-ops-1')).toBeNull()
    expect(screen.queryByTestId('task-card-label-ops-2')).toBeNull()
    expect(document.body.textContent).not.toContain('工序')

    // ② 完整套号退场（与行①的加工单号重复，纯占纸面）
    expect(screen.queryByTestId('task-card-label-set-code-0')).toBeNull()
    expect(screen.queryByTestId('task-card-label-set-code-2')).toBeNull()
    expect(document.body.textContent).not.toContain(`${PROCESSING_ORDER_NO}-001`)
    expect(document.body.textContent).not.toContain(`${PROCESSING_ORDER_NO}-002`)

    // ③ 变体名（工人端快照名）一个都不许上纸面（issue #4621 回归守卫）
    expect(document.body.textContent).not.toContain('精裁-布')
    expect(document.body.textContent).not.toContain('韩褶-纱')
    expect(document.body.textContent).not.toContain('精裁-帘头')
  })

  it('单列字段逐张渲染：部位 / 件名 / 色号 / 用料 / 宽高 / 加工方式（照真实工单信息顺序）', () => {
    printCard()

    // 第 1 张（布帘）：部位 / 件名 / 色号 / 用料 / 宽高 / 加工方式
    expect(screen.getByTestId('task-card-label-kind-0')).toHaveTextContent('布帘')
    expect(screen.getByTestId('task-card-label-position-0')).toHaveTextContent('布艺遮光帘A')
    expect(screen.getByTestId('task-card-label-color-0')).toHaveTextContent('米白')
    expect(screen.getByTestId('task-card-label-meters-0')).toHaveTextContent('6.3米')
    expect(screen.getByTestId('task-card-label-size-0')).toHaveTextContent('3×2.75米')
    // 加工方式 = craft-display 的单一真值（工艺/加工类型/打开方式/是否定型），不另写推导
    const craft0 = screen.getByTestId('task-card-label-craft-0')
    expect(craft0).toHaveTextContent('韩褶')
    expect(craft0).toHaveTextContent('定高买宽')
    expect(craft0).toHaveTextContent('双开')
    expect(craft0).toHaveTextContent('定型')

    // 逐张对齐（错配 = 车间按错件干活）
    expect(screen.getByTestId('task-card-label-kind-2')).toHaveTextContent('帘头')
    expect(screen.getByTestId('task-card-label-color-2')).toHaveTextContent('米灰')
    const craft2 = screen.getByTestId('task-card-label-craft-2')
    expect(craft2).toHaveTextContent('平板')
    expect(craft2).not.toHaveTextContent('韩褶')
  })

  it('备注（特殊选项 + 快照备注）与算料公式逐张渲染；无对应快照行 ⇒ 该行不出现（不猜）', () => {
    printCard()

    expect(screen.getByTestId('task-card-label-remark-0')).toHaveTextContent('加logo条')
    expect(screen.getByTestId('task-card-label-remark-0')).toHaveTextContent('防翘扣')
    expect(screen.getByTestId('task-card-label-formula-0')).toHaveTextContent('韩褶公式')
    // 🔴 算料公式 = **2 行**（issue #5646 实测改判；30mm 时代的 3 行口径作废）：
    // 两条真公式串（`韩褶公式：…` / `褶倍数公式：…`）在 47.599mm 版心（≈22.5em/行）下都**恰好 2 行**；
    // 容量 2×22.5em = 45em **反而大于**旧口径 3×13em = 39em ⇒ 不是放宽，是同一真值换了版心。
    // 改回 3 行 ⇒ 最坏构成（件名 2 + 加工方式 2 + 备注 2 + 公式 3 行）实测需 61.4mm > 60mm ⇒ 本条必红。
    expect(screen.getByTestId('task-card-label-formula-0').className).toContain('line-clamp-2')
    expect(screen.getByTestId('task-card-label-formula-0').className).not.toContain('line-clamp-3')

    // item-2 没有快照行 ⇒ 第 2 张不出色号/用料/宽高/加工方式/备注/公式（缺值不渲染，不猜）
    expect(screen.queryByTestId('task-card-label-color-1')).toBeNull()
    expect(screen.queryByTestId('task-card-label-meters-1')).toBeNull()
    expect(screen.queryByTestId('task-card-label-craft-1')).toBeNull()
    expect(screen.queryByTestId('task-card-label-remark-1')).toBeNull()
    expect(screen.queryByTestId('task-card-label-formula-1')).toBeNull()
  })

  it('🔴 版心 30→50mm 后重算的字段折行预算：件名去 clamp / 加工方式与备注 ≤2 行 / 公式 ≤2 行（issue #5646）', () => {
    printCard()

    // ① **件名不再 clamp**（推翻 #4946 为 27.6mm 版心设的 2 行妥协）：版心 47.599mm ≈ 22.5em/行
    //    ⇒ 2 行可容 ~45em，实测最长件名只折 2 行；留着 clamp 只会平白砍掉真名。
    //    正向锚点（避免"查不到元素"被读成"断言通过"的空跑）：该行确实渲染了件名正文。
    const name = screen.getByTestId('task-card-label-position-0')
    expect(name).toHaveTextContent('布艺遮光帘A')
    expect(name.className).not.toContain('line-clamp')

    // ② **加工方式**仍 `line-clamp-2` —— 只作**预算上界**：实测最长形态
    //    「加工方式 罗马帘 · 定宽买高 · 三开 · 定型」(≈21.5em) 在 47.599mm 下**恰好 1 行**。
    expect(screen.getByTestId('task-card-label-craft-0').className).toContain('line-clamp-2')

    // ③ **备注**仍 ≤2 行（issue #5646 的最坏口径明写「备注 2 行」）。
    expect(screen.getByTestId('task-card-label-remark-0').className).toContain('line-clamp-2')

    // ④ 主标识与底部码/短码的**不折行 + shrink-0** 契约一字未动（打印隔离与降级入口是红线）
    expect(within(screen.getByTestId('task-card-label-0')).getByTestId('task-card-no').className).toContain(
      'whitespace-nowrap',
    )
    const bottomRow = screen.getAllByTestId('task-card-qr')[0].parentElement as HTMLElement
    expect(bottomRow.className).toContain('shrink-0')
  })

  it('色号已包含在件名里 ⇒ 不重复渲染（信息重复问题不再带进 50×60）', () => {
    // 先钉**正向**：件名不含色号 ⇒ 色号行必须在（否则本条的"不出现"断言是空断言）
    const { unmount } = printCard()
    expect(screen.getByTestId('task-card-label-color-0')).toHaveTextContent('米白')
    unmount()

    const withColorInName: ProductionPosition[] = [{ ...positions[0], position_name: '布艺遮光帘A（米白）' }]
    printCard({ positions: withColorInName })

    expect(screen.getByTestId('task-card-label-position-0')).toHaveTextContent('米白')
    expect(screen.queryByTestId('task-card-label-color-0')).toBeNull()
  })

  it('是否定型按行业措辞收成「定型 / 不定型」（值仍来自 craft-display，不重算）', () => {
    // 是 ⇒ 定型
    const { unmount } = printCard()
    expect(screen.getByTestId('task-card-label-craft-0')).toHaveTextContent('定型')
    unmount()

    // 否 ⇒ 不定型（判据可判别：写死「定型」⇒ 本条必红）
    const unshaped = [{ itemId: 'item-1', craft: '韩褶', isShaped: false }] as unknown as ProcessingOrderItem[]
    printCard({ items: unshaped })
    const craft = screen.getByTestId('task-card-label-craft-0')
    expect(craft).toHaveTextContent('不定型')
    expect(craft).not.toHaveTextContent('是否定型：是')
  })

  it('缺值不渲染：无 items / 无工艺键 ⇒ 相关行不出现，纸面不出现 undefined/null/NaN', () => {
    const { unmount } = printCard({ items: [] })
    expect(screen.queryByTestId('task-card-label-color-0')).toBeNull()
    expect(screen.queryByTestId('task-card-label-meters-0')).toBeNull()
    expect(screen.queryByTestId('task-card-label-craft-0')).toBeNull()
    expect(screen.queryByTestId('task-card-label-formula-0')).toBeNull()
    expect(document.body.textContent).not.toMatch(/undefined|null|NaN/)
    unmount()

    // 存量加工单：快照里只有销售信息、没有任何工艺键
    const legacy = [
      { itemId: 'item-1', productName: '布艺遮光帘A', colorName: '米白', craft: null, openCount: null, style: '' },
    ] as unknown as ProcessingOrderItem[]
    printCard({ items: legacy })
    expect(screen.queryByTestId('task-card-label-craft-0')).toBeNull()
    expect(screen.queryByTestId('task-card-label-formula-0')).toBeNull()
    expect(document.body.textContent).not.toMatch(/undefined|null|NaN/)
  })

  it('缺宽高（只有一边 / 都没有）⇒ 不渲染宽高行（半个尺寸没有意义）', () => {
    const { unmount } = printCard({ positions: [{ ...positions[0], height: null }] })
    expect(screen.queryByTestId('task-card-label-size-0')).toBeNull()
    unmount()

    printCard({ positions: [{ ...positions[0], width: null, height: null }] })
    expect(screen.queryByTestId('task-card-label-size-0')).toBeNull()
  })

  it('0 个部位 ⇒ 一张显式占位（不是空白），且不画任何码', () => {
    const { unmount } = printCard({ positions: [] })

    expect(screen.getByTestId('task-card-label-0')).toHaveTextContent('暂无商品')
    expect(screen.getByTestId('task-card-label-0')).toHaveTextContent('无码可打印')
    expect(screen.getByTestId('task-card-qr-placeholder')).toHaveTextContent('待生成')
    expect(screen.queryByTestId('task-card-qr')).toBeNull()
    // 只有一张占位（不是 N 张），公共属性仍在
    expect(screen.queryByTestId('task-card-label-1')).toBeNull()
    expect(screen.getByTestId('task-card-no')).toHaveTextContent(PROCESSING_ORDER_NO)
    unmount()

    // positions 缺席（存量调用形态）⇒ 同一占位
    render(<TaskCardPrint processingOrderNo={PROCESSING_ORDER_NO} />)
    expect(screen.getByTestId('task-card-label-0')).toHaveTextContent('无码可打印')
    expect(screen.queryByTestId('task-card-qr')).toBeNull()
  })
})
