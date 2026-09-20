// case_ids: PP-011
// PP-011（issue #4000，M4-H 按需单据渲染）：加工单生产明细 —— 工序进度表按部位分组渲染、
// 必完工序标记（is_must_finish）、状态（待做/已完成）与空态。
// 真值源：docs/curtain-production-rules.md §2 工序库（必完工序=打包前置）/ §5 扫码报工闭环。
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import ProductionProgressTable from '@/components/production/ProductionProgressTable'
import type { ProductionPosition } from '@/types'

/** GET /api/admin/production/orders/{orderId}/operations 的 positions 段（后端 Map → snake_case 键） */
const positions: ProductionPosition[] = [
  {
    position_name: '布帘',
    operations: [
      {
        id: 'op-1',
        seq: 1,
        operation: '精裁-布',
        // issue #4621：后端读面补的**显示名派生键**（读时派生、不写库）；
        // `operation` 是**工人端快照名**（变体名），界面不得渲染它
        logical_name: '精裁',
        position: '布帘',
        group: '裁剪',
        unit: '套',
        qty: 2,
        unit_price: 8.5,
        is_must_finish: false,
        is_start_marker: true,
        status: 'done',
        done_qty: 2,
      },
      {
        id: 'op-2',
        seq: 2,
        operation: '外帘装袋',
        // 部位无关工序：后端 `position` 为空 ⇒ 界面只显示逻辑名（不拼空部位）
        logical_name: '外帘装袋',
        group: '后道',
        unit: '件',
        qty: 2,
        unit_price: 3,
        is_must_finish: true,
        is_start_marker: false,
        status: 'pending',
        done_qty: 0,
      },
    ],
  },
  {
    position_name: '纱帘',
    operations: [
      {
        id: 'op-3',
        seq: 1,
        operation: '韩褶-纱',
        logical_name: '韩褶',
        position: '纱帘',
        group: '车位',
        unit: '折',
        qty: 24,
        unit_price: 1.2,
        is_must_finish: false,
        status: 'pending',
        done_qty: 0,
      },
    ],
  },
]

describe('ProductionProgressTable', () => {
  it('按部位分组渲染工序行：工序名/分组/应做数量+单位/单价/状态/已完成数量', () => {
    render(<ProductionProgressTable positions={positions} />)

    // 部位分组标题（布帘 / 纱帘）
    expect(screen.getByTestId('position-group-布帘')).toBeInTheDocument()
    expect(screen.getByTestId('position-group-纱帘')).toBeInTheDocument()

    const row = screen.getByTestId('operation-row-op-1')
    // issue #4621：工序名只显示「逻辑名 · 部位」—— 变体名（`精裁-布`）不得出现在界面
    expect(within(row).getByText('精裁 · 布帘')).toBeInTheDocument()
    expect(within(row).queryByText('精裁-布')).toBeNull()
    expect(within(row).getByTestId('op-group')).toHaveTextContent('裁剪')
    expect(within(row).getByTestId('op-qty')).toHaveTextContent('2 套')
    expect(within(row).getByTestId('op-unit-price')).toHaveTextContent('¥8.50')
    expect(within(row).getByTestId('op-status')).toHaveTextContent('已完成')
    expect(within(row).getByTestId('op-done')).toHaveTextContent('2 套')

    // 第二个部位的行也必须渲染（分组不吞数据）
    expect(screen.getByTestId('operation-row-op-3')).toBeInTheDocument()
  })

  // ── 工序显示名统一（issue #4621）：只显示「逻辑名 · 部位」，变体名不得出现在界面 ──
  // 口径（冻结）：显示名 = 逻辑工序名；该实例有部位 ⇒ `逻辑名 · 部位`（如 `三边 · 布帘`）；
  // 部位无关工序（外帘装袋）⇒ 只显示逻辑名。派生是**后端读时**做的（`logical_name` / `position`
  // 两个新键），前端只拼装、**不写库**；`operation` 是工人端快照名，只作老数据兜底。

  it('工序列只显示「逻辑名 · 部位」，变体名（精裁-布 / 韩褶-纱）不出现', () => {
    render(<ProductionProgressTable positions={positions} />)

    expect(within(screen.getByTestId('operation-row-op-1')).getByText('精裁 · 布帘')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-op-3')).getByText('韩褶 · 纱帘')).toBeInTheDocument()
    // 全表都不得出现变体名（那是工人端快照名，不是界面文案）
    expect(screen.queryByText('精裁-布')).toBeNull()
    expect(screen.queryByText('韩褶-纱')).toBeNull()
  })

  it('部位无关工序（外帘装袋）只显示逻辑名，不拼空部位', () => {
    render(<ProductionProgressTable positions={positions} />)

    const row = within(screen.getByTestId('operation-row-op-2'))
    expect(row.getByText('外帘装袋')).toBeInTheDocument()
    expect(row.queryByText(/·/)).toBeNull()
  })

  it('老数据缺 logical_name ⇒ 退回 operation 原文（不显示空白）', () => {
    render(
      <ProductionProgressTable
        positions={[
          {
            position_name: '布帘',
            operations: [
              { id: 'legacy-1', seq: 1, operation: '定型-布', status: 'pending', done_qty: 0 },
            ],
          },
        ]}
      />,
    )

    expect(within(screen.getByTestId('operation-row-legacy-1')).getByText('定型-布')).toBeInTheDocument()
  })

  it('必完工序（is_must_finish）加「必完」标记，非必完工序不加', () => {
    render(<ProductionProgressTable positions={positions} />)

    const badges = screen.getAllByText('必完')
    expect(badges).toHaveLength(1)
    expect(within(screen.getByTestId('operation-row-op-2')).getByText('必完')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-op-1')).queryByText('必完')).toBeNull()
  })

  it('状态列区分「待做 / 已完成」（未报工的工序显示待做）', () => {
    render(<ProductionProgressTable positions={positions} />)

    expect(within(screen.getByTestId('operation-row-op-2')).getByTestId('op-status')).toHaveTextContent('待做')
    expect(within(screen.getByTestId('operation-row-op-3')).getByTestId('op-status')).toHaveTextContent('待做')
    expect(within(screen.getByTestId('operation-row-op-3')).getByTestId('op-done')).toHaveTextContent('0 折')
  })

  it('无工序数据渲染空态（不白屏）', () => {
    render(<ProductionProgressTable positions={[]} />)

    expect(screen.getByText('暂无工序数据')).toBeInTheDocument()
    expect(screen.queryByTestId('operation-row-op-1')).toBeNull()
  })

  it('positions 缺省（接口未返回）同样走空态', () => {
    render(<ProductionProgressTable />)

    expect(screen.getByText('暂无工序数据')).toBeInTheDocument()
  })

  // ── 报工人列（issue #4309：跟进人 = 只加「报工人」，零新字段，读报工记录）──
  // 口径：报工人 = 该工序实例下报过工的人（后端 workers，按首次报工时间升序去重、
  // 只取 work_type='normal'、空名折「未署名」）；无报工 = 空数组 ⇒ 渲染「—」。

  /** 后端 positions 段 + workers（报工人）——op-1 一人 / op-2 两人 / op-3 无报工 */
  const positionsWithWorkers: ProductionPosition[] = [
    {
      position_name: '布帘',
      operations: [
        { ...positions[0].operations![0], workers: ['张三'] },
        { ...positions[0].operations![1], workers: ['张三', '李四'] },
      ],
    },
    {
      position_name: '纱帘',
      operations: [{ ...positions[1].operations![0], workers: [] }],
    },
  ]

  it('报工人列渲染 workers（多人用「、」连接）', () => {
    render(<ProductionProgressTable positions={positionsWithWorkers} />)

    expect(within(screen.getByTestId('operation-row-op-1')).getByTestId('op-workers')).toHaveTextContent('张三')
    expect(within(screen.getByTestId('operation-row-op-2')).getByTestId('op-workers')).toHaveTextContent('张三、李四')
  })

  it('无报工人渲染「—」（空数组与键缺省同）', () => {
    render(
      <ProductionProgressTable
        positions={[
          {
            position_name: '布帘',
            operations: [
              { ...positions[0].operations![0], workers: [] },
              { ...positions[0].operations![1], workers: undefined },
            ],
          },
        ]}
      />,
    )

    expect(within(screen.getByTestId('operation-row-op-1')).getByTestId('op-workers')).toHaveTextContent('—')
    expect(within(screen.getByTestId('operation-row-op-2')).getByTestId('op-workers')).toHaveTextContent('—')
  })

  it('既有 6 列顺序不变，「报工人」追加在表尾', () => {
    render(<ProductionProgressTable positions={positions} />)

    const headers = within(screen.getByTestId('position-group-布帘'))
      .getAllByRole('columnheader')
      .map((th) => th.textContent)
    expect(headers).toEqual(['工序', '分组', '应做数量', '单价', '状态', '已完成数量', '报工人'])
  })
})

/**
 * 未定价显式可见（issue #4696，P1）—— 加工单**工序进度**面的红证。
 *
 * 缺陷原形：后端把 `unit_price` 用 `nz()` 折成 0 ⇒ 界面显示「¥0.00」，
 * 与「定价为 0 元」同形 ⇒ 商家看不出「这道工序还没定价、工人干了拿不到钱」。
 */
describe('ProductionProgressTable 未定价（issue #4696）', () => {
  const unpricedPositions: ProductionPosition[] = [
    {
      position_name: '布料',
      operations: [
        {
          id: 'op-unpriced',
          seq: 1,
          operation: '配料',
          logical_name: '配料',
          position: '布料',
          group: '后道',
          unit: '米',
          qty: 10,
          unit_price: null,
          price_state: 'unpriced',
          status: 'pending',
          done_qty: 0,
        },
        {
          id: 'op-zero',
          seq: 2,
          operation: '打包',
          logical_name: '打包',
          position: '布料',
          group: '后道',
          unit: '套',
          qty: 2,
          unit_price: 0,
          price_state: 'priced',
          status: 'pending',
          done_qty: 0,
        },
      ],
    },
  ]

  it('🔴 未定价 ⇒ 显示「未定价」+ 定价入口，**不得**折成 ¥0.00', () => {
    render(<ProductionProgressTable positions={unpricedPositions} />)

    const row = screen.getByTestId('operation-row-op-unpriced')
    expect(within(row).getByTestId('op-unit-price-unpriced')).toHaveTextContent('未定价')
    expect(within(row).getByTestId('op-unit-price')).not.toHaveTextContent('¥0.00')
    expect(within(row).getByTestId('op-unit-price-pricing-link')).toHaveAttribute(
      'href',
      '/production/routings',
    )
  })

  it('反向护栏：显式**定价 0 元** ⇒ 渲染 ¥0.00（**不是**「未定价」，两态可区分）', () => {
    render(<ProductionProgressTable positions={unpricedPositions} />)

    const zeroRow = screen.getByTestId('operation-row-op-zero')
    expect(within(zeroRow).queryByTestId('op-unit-price-unpriced')).not.toBeInTheDocument()
    expect(within(zeroRow).getByTestId('op-unit-price')).toHaveTextContent('¥0.00')
  })
})
