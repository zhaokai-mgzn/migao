// case_ids: PP-011
// PP-011（issue #4946，用户裁定 2026-09-21）：**洗水码取代 A4 任务卡** —— 加工单按**商品行 = 部位**
// 打印 N 张 **60mm × 30mm** 洗水码（N = positions.length），每张带**该部位自己的二维码**
// （value = `scan_url ?? part_token`）；**加工单公共属性（加工单号/订单号/客户名/交期/套号）逐张都在**。
// 旧 A4 版式（宽表 + 大工艺块 + 计件口径页脚）整体删除：纸面只有 60×30mm，只承载**摘要**。
//
// 逐条判据（都能判红）：
// ① 3 个部位 ⇒ 恰 3 张（`task-card-label-0..2`），公共属性**逐张**都在；
// ② 三张码三个值（= 各部位的 `scan_url`）—— 这是本单的**核心判据**（改回单张/单值 ⇒ 必红）；
// ③ 缺码部位 ⇒ 该张出占位（不画假码），其余张仍出真码；
// ④ 人可读短码（`part_short_code`）逐张渲染，缺码位如实「—」；
// ⑤ 打印样式：`@page { size: 60mm 30mm; margin: 0 }` + 标签 60mm×30mm + 逐张分页（最后一张不分页）；
// ⑥ 工序摘要 = 道数 + **显示名**（`operationDisplayName`），且**不得**渲染工人端快照名（issue #4621 回归守卫）；
// ⑦ 0 个部位 ⇒ 一张显式占位（不是空白）。
// 工艺摘要（issue #4355 的摘要形态）：按 `position.order_item_id` ↔ 快照 `itemId` 对齐**逐张**渲染，
// 缺值/无对应快照行 ⇒ 该行不出现；单行截断（clamp）。
import type { ComponentProps } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

const PROCESSING_ORDER_NO = 'JG-20260921-8237'
const ORDER_NO = 'MG20260921001'
const CUSTOMER = '李四'
const DELIVERY = '2026-09-25'

const SCAN_BL = 'https://app.migaozn.com/s/7K3M9QP2'
const SCAN_SHA = 'https://app.migaozn.com/s/QW8Z2N4B'
const SCAN_LT = 'https://app.migaozn.com/s/ZX5C7V1N'
const SHORT_BL = '7K3M9QP2'
const SHORT_SHA = 'QW8Z2N4B'
const SHORT_LT = 'ZX5C7V1N'

/**
 * 三个部位（= 三个商品行）分属**两套**（布帘+纱帘 = 第 1 套；帘头 = 第 2 套）——
 * 「第 N 套 / 共 M 套」由 `set_no` 去重派生（不发明后端键）。
 */
const positions: ProductionPosition[] = [
  {
    position_name: '布艺遮光帘A（米白）',
    order_item_id: 'item-1',
    position_kind: '布帘',
    set_no: `${PROCESSING_ORDER_NO}-001`,
    product_name: '布艺遮光帘A',
    width: 2.4,
    height: 2.6,
    part_token: 'part-token-bu-1',
    part_short_code: SHORT_BL,
    scan_url: SCAN_BL,
    operations: [
      // `operation` = 工人端快照名（变体名，如 `精裁-布`）：界面**不得**渲染（issue #4621）
      { id: 'op-1', seq: 1, operation: '精裁-布', logical_name: '精裁', position: '布帘', unit: '套', qty: 2, status: 'pending', done_qty: 0 },
      { id: 'op-2', seq: 2, operation: '外帘装袋', logical_name: '外帘装袋', unit: '件', qty: 2, is_must_finish: true, status: 'pending', done_qty: 0 },
    ],
  },
  {
    position_name: '纱帘',
    order_item_id: 'item-2',
    position_kind: '纱帘',
    set_no: `${PROCESSING_ORDER_NO}-001`,
    product_name: '纱帘B',
    part_token: 'part-token-sha-1',
    part_short_code: SHORT_SHA,
    scan_url: SCAN_SHA,
    operations: [
      { id: 'op-3', seq: 1, operation: '韩褶-纱', logical_name: '韩褶', position: '纱帘', unit: '折', qty: 24, status: 'pending', done_qty: 0 },
    ],
  },
  {
    position_name: '帘头',
    order_item_id: 'item-3',
    position_kind: '帘头',
    set_no: `${PROCESSING_ORDER_NO}-002`,
    product_name: '帘头C',
    part_token: 'part-token-lt-1',
    part_short_code: SHORT_LT,
    scan_url: SCAN_LT,
    // 5 道工序 ⇒ 摘要只渲染前几道 + 「…」（不得溢出 60×30 纸面）
    operations: [
      { id: 'op-4', seq: 1, operation: '精裁-帘头', logical_name: '精裁', position: '帘头', unit: '套', qty: 1, status: 'pending', done_qty: 0 },
      { id: 'op-5', seq: 2, operation: '三边-帘头', logical_name: '三边', position: '帘头', unit: '套', qty: 1, status: 'pending', done_qty: 0 },
      { id: 'op-6', seq: 3, operation: '韩褶-帘头', logical_name: '韩褶', position: '帘头', unit: '折', qty: 12, status: 'pending', done_qty: 0 },
      { id: 'op-7', seq: 4, operation: '熨烫-帘头', logical_name: '熨烫', position: '帘头', unit: '套', qty: 1, status: 'pending', done_qty: 0 },
      { id: 'op-8', seq: 5, operation: '包装-帘头', logical_name: '包装', position: '帘头', unit: '件', qty: 1, status: 'pending', done_qty: 0 },
    ],
  },
]

/** 公共属性（每张都必须呈现） */
const printCard = (overrides: Partial<ComponentProps<typeof TaskCardPrint>> = {}) =>
  render(
    <TaskCardPrint
      processingOrderNo={PROCESSING_ORDER_NO}
      orderNo={ORDER_NO}
      customerName={CUSTOMER}
      expectedDeliveryDate={DELIVERY}
      positions={positions}
      {...overrides}
    />,
  )

const printArea = () => document.querySelector('.task-card-print-area') as HTMLElement

describe('TaskCardPrint（洗水码 60mm×30mm，issue #4946）', () => {
  it('3 个部位 ⇒ 恰 3 张洗水码，且加工单公共属性**逐张**都在（加工单号/订单号/客户名/交期/套号）', () => {
    printCard()

    const labels = [0, 1, 2].map((i) => screen.getByTestId(`task-card-label-${i}`))
    // 粒度 = 商品行 = 部位（每行一张），第 4 张不存在
    expect(screen.queryByTestId('task-card-label-3')).toBeNull()

    labels.forEach((label) => {
      expect(within(label).getByTestId('task-card-no')).toHaveTextContent(PROCESSING_ORDER_NO)
      expect(within(label).getByTestId('task-card-order-no')).toHaveTextContent(ORDER_NO)
      expect(label).toHaveTextContent(CUSTOMER)
      expect(label).toHaveTextContent(DELIVERY)
    })

    // 套号（set_no）+「第 N 套 / 共 M 套」由**去重 set_no** 派生（布帘/纱帘同套、帘头第 2 套）
    expect(screen.getByTestId('task-card-label-set-no-0')).toHaveTextContent(`${PROCESSING_ORDER_NO}-001`)
    expect(screen.getByTestId('task-card-label-set-no-0')).toHaveTextContent('第 1 套 / 共 2 套')
    expect(screen.getByTestId('task-card-label-set-no-1')).toHaveTextContent('第 1 套 / 共 2 套')
    expect(screen.getByTestId('task-card-label-set-no-2')).toHaveTextContent(`${PROCESSING_ORDER_NO}-002`)
    expect(screen.getByTestId('task-card-label-set-no-2')).toHaveTextContent('第 2 套 / 共 2 套')

    // 每张自己的部位/商品名（这一张是给哪一件的纸面凭证）
    expect(screen.getByTestId('task-card-label-position-0')).toHaveTextContent('布艺遮光帘A（米白）')
    expect(screen.getByTestId('task-card-label-position-1')).toHaveTextContent('纱帘')
    expect(screen.getByTestId('task-card-label-position-2')).toHaveTextContent('帘头')
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
    const values = codes.map((qr) => qr.querySelector('title')?.textContent)
    expect(values).toEqual(expected)
    expect(new Set(values).size).toBe(3)
  })

  it('缺码部位 ⇒ 该张出占位（不画假码），其余张仍出真码', () => {
    const mixed: ProductionPosition[] = [
      { ...positions[0] },
      // 该部位没有码（未生成 / 已撤销）：读面三键全空
      { position_name: '纱帘', order_item_id: 'item-2', set_no: `${PROCESSING_ORDER_NO}-001`, part_token: null, part_short_code: null, scan_url: null, operations: [] },
      // 只有 part_token（`scan_url` 缺席）⇒ 仍按回退口径出真码
      { ...positions[2], scan_url: null },
    ]
    printCard({ positions: mixed, qrPlaceholderHint: '二维码已撤销（旧码已失效）' })

    const emptyLabel = screen.getByTestId('task-card-label-1')
    const placeholder = within(emptyLabel).getByTestId('task-card-qr-placeholder')
    expect(placeholder).toHaveTextContent('二维码已撤销（旧码已失效）')
    // 不画假码：该张里连一个 svg 都没有
    expect(emptyLabel.querySelector('svg')).toBeNull()
    expect(within(emptyLabel).queryByTestId('task-card-qr')).toBeNull()
    expect(screen.getAllByTestId('task-card-qr-placeholder')).toHaveLength(1)

    // 其余张不受影响：真码照出（第 3 张回退到 part_token）
    expect(within(screen.getByTestId('task-card-label-0')).getByTestId('task-card-qr').querySelector('title')?.textContent).toBe(SCAN_BL)
    expect(within(screen.getByTestId('task-card-label-2')).getByTestId('task-card-qr').querySelector('title')?.textContent).toBe('part-token-lt-1')
  })

  it('缺省占位文案 = 待生成（缺码但不撤销时不得谎称「已撤销」）', () => {
    const noCode: ProductionPosition[] = [
      { position_name: '纱帘', order_item_id: 'item-2', part_token: null, part_short_code: null, scan_url: null, operations: [] },
    ]
    printCard({ positions: noCode })

    const placeholder = screen.getByTestId('task-card-qr-placeholder')
    expect(placeholder).toHaveTextContent('待生成')
    expect(placeholder.textContent).not.toContain('已撤销')
    expect(screen.queryByTestId('task-card-qr')).toBeNull()
    // 公共属性仍在（纸面能认出是哪张单的哪一件）
    expect(screen.getByTestId('task-card-label-0')).toHaveTextContent(PROCESSING_ORDER_NO)
  })

  it('人可读短码逐张渲染（工人可手输），缺短码如实「—」', () => {
    printCard()
    expect(screen.getByTestId('task-card-label-short-code-0')).toHaveTextContent(SHORT_BL)
    expect(screen.getByTestId('task-card-label-short-code-1')).toHaveTextContent(SHORT_SHA)
    expect(screen.getByTestId('task-card-label-short-code-2')).toHaveTextContent(SHORT_LT)
  })

  it('缺短码的序号仍保留该行（不得与人可读短码一起消失）', () => {
    const noShort: ProductionPosition[] = [
      { position_name: '纱帘', order_item_id: 'item-2', part_token: 'part-token-x', part_short_code: null, scan_url: null, operations: [] },
    ]
    printCard({ positions: noShort })

    const shortCode = screen.getByTestId('task-card-label-short-code-0')
    expect(shortCode).toHaveTextContent('—')
    // 码还在（`part_token` 回退）—— 短码缺失不得把码也吞掉
    expect(screen.getByTestId('task-card-qr').querySelector('title')?.textContent).toBe('part-token-x')
  })

  it('打印样式：@page 60mm×30mm + 标签本体 60mm×30mm 且逐张分页（最后一张不分页）', () => {
    printCard()

    // portal 到 body 的直接子级（打印隔离的第 2 条约束：容器自身的 class 才能被选择器选中）
    const area = printArea()
    expect(area).not.toBeNull()
    expect(area.parentElement).toBe(document.body)

    const css = area.querySelector('style')?.textContent ?? ''
    expect(css).toContain('@page { size: 60mm 30mm; margin: 0; }')
    expect(css).toContain('.task-card-label { width: 60mm; height: 30mm; overflow: hidden;')
    expect(css).toContain('break-after: page')
    // 最后一张不分页（否则末尾多吐一张空白）
    expect(css).toMatch(/\.task-card-label:last-child \{[^}]*break-after: auto/)
    // 屏幕隐藏、打印显形 + visibility 防御（ShipmentDoc 6 条约束，勿随手改）
    expect(css).toContain('.task-card-print-area { display: none; }')
    expect(css).toContain('body > *:not(.task-card-print-area) { display: none !important; }')
    expect(css).toContain('.task-card-print-area, .task-card-print-area * { visibility: visible; }')

    // 标签本体的类契约（尺寸/分页都挂在它身上）
    ;[0, 1, 2].forEach((i) => expect(screen.getByTestId(`task-card-label-${i}`).className).toContain('task-card-label'))
  })

  it('工序摘要 = 道数 + 显示名（截断不溢出），且**不得**渲染工人端快照名（#4621 回归守卫）', () => {
    printCard()

    const ops0 = screen.getByTestId('task-card-label-ops-0')
    expect(ops0).toHaveTextContent('工序 2 道')
    // 显示名口径 = `逻辑名 · 部位`（唯一实现 operation-display.ts）
    expect(ops0).toHaveTextContent('精裁 · 布帘')
    expect(ops0).toHaveTextContent('外帘装袋')

    // 道数如实（5 道）且只列前几道 + 「…」（60×30mm 装不下全部）
    const ops2 = screen.getByTestId('task-card-label-ops-2')
    expect(ops2).toHaveTextContent('工序 5 道')
    expect(ops2.textContent).toContain('…')

    // 变体名（工人端快照名）一个都不许上纸面
    expect(document.body.textContent).not.toContain('精裁-布')
    expect(document.body.textContent).not.toContain('韩褶-纱')
    expect(document.body.textContent).not.toContain('熨烫-帘头')
  })

  it('0 个部位 ⇒ 一张显式占位（不是空白），且不画任何码', () => {
    const { unmount } = printCard({ positions: [] })

    // 显式说清「无商品/无码可打印」——不是静默什么都不打
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

  // ── 工艺摘要（issue #4355 的摘要形态：车间按工艺生产，缺一字段 = 少一道活）──────────

  /** `items_snapshot` 口径（与 order_items.processing_info 同键名，§4.5）；`itemId` = 行主键 */
  const craftItems = [
    {
      itemId: 'item-1',
      productName: '布艺遮光帘A',
      colorName: '米白',
      curtainType: '布帘',
      craft: '韩褶',
      cuttingMode: '定高买宽',
      openCount: 2,
      panels: 4,
      fabric_meters: 13.3,
      // #4876：该键仍在载荷里，但它的展示行已从 craft-display 删除 ⇒ 摘要里不得出现
      pleatSpacing: 0.1,
    },
    { itemId: 'item-3', productName: '帘头C', craft: '平板' },
  ] as unknown as ProcessingOrderItem[]

  it('工艺摘要按 order_item_id ↔ 快照 itemId 对齐**逐张**渲染，且单行截断', () => {
    printCard({ items: craftItems })

    const craft0 = screen.getByTestId('task-card-label-craft-0')
    expect(craft0).toHaveTextContent('韩褶')
    expect(craft0).toHaveTextContent('定高买宽')
    // 单行 clamp 契约（纸面 60×30mm，不能溢出）
    expect(craft0.className).toContain('truncate')
    // ⚠️ #4876：任务卡载荷里仍带 `pleatSpacing: 0.1`，而 `craft-display` 的「褶距」行已整体删除
    // ⇒ 摘要里**不得**再出现它（回归守卫，勿删）
    expect(craft0).not.toHaveTextContent('褶距')
    expect(craft0).not.toHaveTextContent('0.1米')

    // 逐张：第 3 张只出自己的工艺（错配 = 车间按错工艺干活）
    const craft2 = screen.getByTestId('task-card-label-craft-2')
    expect(craft2).toHaveTextContent('平板')
    expect(craft2).not.toHaveTextContent('韩褶')

    // 无对应快照行（item-2）⇒ 该张不出工艺行（缺值不渲染，不猜）
    expect(screen.queryByTestId('task-card-label-craft-1')).toBeNull()
  })

  it('无 items / 无工艺键 ⇒ 不出工艺行，纸面也不出现 undefined/null/NaN（#4355 缺值不渲染）', () => {
    const { unmount } = printCard()
    expect(screen.queryByTestId('task-card-label-craft-0')).toBeNull()
    expect(document.body.textContent).not.toMatch(/undefined|null|NaN/)
    unmount()

    // 存量加工单：快照里只有销售信息、没有任何工艺键
    const legacyItems = [
      { itemId: 'item-1', productName: '布艺遮光帘A', colorName: '米白', craft: null, openCount: null, style: '' },
    ] as unknown as ProcessingOrderItem[]
    printCard({ items: legacyItems })
    expect(screen.queryByTestId('task-card-label-craft-0')).toBeNull()
    expect(document.body.textContent).not.toMatch(/undefined|null|NaN/)
  })

  it('#4555 回归：算料公式（formula_text）以摘要形态逐张上纸面，存量无该键则不出现', () => {
    const withFormula = [
      { ...craftItems[0], formula_text: '韩折公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米' },
    ] as unknown as ProcessingOrderItem[]
    const { unmount } = printCard({ items: withFormula })
    expect(screen.getByTestId('task-card-label-craft-0')).toHaveTextContent(
      '韩折公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米',
    )
    unmount()

    // 存量加工单无 formula_text 键 ⇒ 摘要里无「算料公式」字样
    printCard({ items: craftItems })
    expect(screen.getByTestId('task-card-label-craft-0')).not.toHaveTextContent('算料公式')
  })
})
