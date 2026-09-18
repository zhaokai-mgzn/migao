// case_ids: PP-011
// PP-011（issue #4000，M4-H 按需单据渲染）：可打印任务卡 —— 加工单号 + 二维码（内容 = qr_token，
// 工人扫码进小程序报工）+ 工序清单（工序名/应做数量/单位 + 手工勾选位）。
// 打印隔离走项目既有范式（ShipmentDoc：portal 到 body + 屏幕 display:none + @media print 显形）。
//
// issue #4355（设计文档 §4.9 ③ 加工单）：纸面同时展示工艺规格 —— 渲染 `items_snapshot`
// （与 order_items.processing_info 同键名），缺值不渲染。
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import TaskCardPrint from '@/components/production/TaskCardPrint'
import type { ProcessingOrderItem, ProductionPosition } from '@/types'

const QR_TOKEN = 'qr-token-abc123'

const positions: ProductionPosition[] = [
  {
    position_name: '布帘',
    operations: [
      { id: 'op-1', seq: 1, operation: '精裁-布', unit: '套', qty: 2, status: 'pending', done_qty: 0 },
      { id: 'op-2', seq: 2, operation: '外帘装袋', unit: '件', qty: 2, is_must_finish: true, status: 'pending', done_qty: 0 },
    ],
  },
  {
    position_name: '纱帘',
    operations: [
      { id: 'op-3', seq: 1, operation: '韩褶-纱', unit: '折', qty: 24, status: 'pending', done_qty: 0 },
    ],
  },
]

describe('TaskCardPrint', () => {
  it('渲染加工单号与扫码报工说明', () => {
    render(
      <TaskCardPrint processingOrderNo="JG-20260917-0001" orderNo="MG20260917001" qrToken={QR_TOKEN} positions={positions} />
    )

    expect(screen.getByTestId('task-card-no')).toHaveTextContent('JG-20260917-0001')
    expect(screen.getByTestId('task-card-order-no')).toHaveTextContent('MG20260917001')
    // 纸面必须说清「扫码后在小程序报工」（本卡勾选只是车间纸质标记）
    expect(screen.getByText(/小程序选本工序/)).toBeInTheDocument()
  })

  it('二维码以 qr_token 为内容渲染（svg 内 title = token）', () => {
    render(<TaskCardPrint processingOrderNo="JG-20260917-0001" qrToken={QR_TOKEN} positions={positions} />)

    const qr = screen.getByTestId('task-card-qr')
    expect(qr.tagName.toLowerCase()).toBe('svg')
    // qrcode.react 的 title prop → svg <title>；断言 token 真的传进了二维码组件
    expect(within(qr).getByTitle(QR_TOKEN)).toBeInTheDocument()
    expect(qr.querySelectorAll('path').length).toBeGreaterThan(0)
  })

  it('渲染工序清单：工序名 + 应做数量与单位 + 每行一个手工勾选位', () => {
    render(<TaskCardPrint processingOrderNo="JG-20260917-0001" qrToken={QR_TOKEN} positions={positions} />)

    const row = screen.getByTestId('task-card-op-0')
    expect(within(row).getByText('精裁-布')).toBeInTheDocument()
    expect(within(row).getByTestId('task-card-op-qty')).toHaveTextContent('2 套')
    expect(within(row).getByTestId('task-card-op-position')).toHaveTextContent('布帘')

    expect(screen.getByTestId('task-card-op-2')).toBeInTheDocument()
    // 3 道工序 ⇒ 3 个手工勾选位（纸质勾选，报工仍在小程序完成）
    expect(screen.getAllByTestId('task-card-check')).toHaveLength(3)
    // 必完工序在纸面也标出来（打包前置，工人不能漏）
    expect(within(screen.getByTestId('task-card-op-1')).getByText('必完')).toBeInTheDocument()
  })

  it('qr_token 缺失时给出占位提示而不是空二维码', () => {
    render(<TaskCardPrint processingOrderNo="JG-20260917-0001" qrToken={null} positions={positions} />)

    expect(screen.getByTestId('task-card-qr-placeholder')).toBeInTheDocument()
    expect(screen.queryByTestId('task-card-qr')).toBeNull()
  })

  // ── issue #4355：纸面展示工艺规格（设计文档 §4.9 ③）───────────────────

  /** `items_snapshot` 口径（与 order_items.processing_info 同键名，§4.5） */
  const craftItems: ProcessingOrderItem[] = [
    {
      productName: '布艺遮光帘A',
      colorName: '米白',
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
  ]

  it('纸面展示工艺规格（车间按工艺生产，缺一字段 = 少一道活，§4.9 ③）', () => {
    render(
      <TaskCardPrint
        processingOrderNo="JG-20260917-0001"
        qrToken={QR_TOKEN}
        positions={positions}
        items={craftItems}
      />
    )

    const spec = screen.getByTestId('task-card-craft-spec')
    expect(within(spec).getByText('工艺规格')).toBeInTheDocument()
    expect(within(spec).getByText('布帘')).toBeInTheDocument()
    expect(within(spec).getByText('韩褶')).toBeInTheDocument()
    expect(within(spec).getByText('定高买宽')).toBeInTheDocument()
    expect(within(spec).getByText('双开')).toBeInTheDocument()
    expect(within(spec).getByText('拼色')).toBeInTheDocument()
    expect(within(spec).getByText('加铅线、双褶')).toBeInTheDocument()
    expect(within(spec).getByText('52')).toBeInTheDocument()
    expect(within(spec).getByText('26')).toBeInTheDocument()
    expect(within(spec).getByText('0.1米')).toBeInTheDocument()
    expect(within(spec).getByText('4')).toBeInTheDocument()
    expect(within(spec).getByText('2 倍')).toBeInTheDocument()
    expect(within(spec).getByText('1.86 倍')).toBeInTheDocument()
    // 面料米数 / 加工费米数 = §4.9 要求的**两个字段**（§6.1 口径拆两值）⇒ 同值时出现两次
    expect(within(spec).getAllByText('13.3米')).toHaveLength(2)
    expect(within(spec).getByText('是否对花')).toBeInTheDocument()
    expect(within(spec).getByText('0.32米')).toBeInTheDocument()
    // 纸面同时标出是哪个部位的料（与工序表的「部位」列同源）
    expect(within(spec).getByText(/布艺遮光帘A/)).toBeInTheDocument()
  })

  it('无 items / 无工艺键 ⇒ 不渲染规格块，纸面也不出现 undefined/null/NaN（§4.9 缺值不渲染）', () => {
    const { unmount } = render(
      <TaskCardPrint processingOrderNo="JG-20260917-0001" qrToken={QR_TOKEN} positions={positions} />
    )
    expect(screen.queryByTestId('task-card-craft-spec')).toBeNull()
    expect(document.body.textContent).not.toMatch(/undefined|null|NaN/)
    unmount()

    // 存量加工单：items_snapshot 里只有销售信息、没有任何工艺键（键为 null 的 JSONB 形态）
    const legacyItems = [
      { productName: '布艺遮光帘A', colorName: '米白', craft: null, openCount: null, style: '' },
    ] as unknown as ProcessingOrderItem[]
    render(
      <TaskCardPrint
        processingOrderNo="JG-20260917-0001"
        qrToken={QR_TOKEN}
        positions={positions}
        items={legacyItems}
      />
    )
    expect(screen.queryByTestId('task-card-craft-spec')).toBeNull()
    expect(document.body.textContent).not.toMatch(/undefined|null|NaN/)
  })
})
