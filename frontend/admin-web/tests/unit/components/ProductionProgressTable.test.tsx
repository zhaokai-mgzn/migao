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
        group: '裁剪',
        unit: '套',
        qty: 2,
        unit_price: 8.5,
        factor: 1,
        is_must_finish: false,
        is_start_marker: true,
        status: 'done',
        done_qty: 2,
      },
      {
        id: 'op-2',
        seq: 2,
        operation: '外帘装袋',
        group: '后道',
        unit: '件',
        qty: 2,
        unit_price: 3,
        factor: 1,
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
        group: '车位',
        unit: '折',
        qty: 24,
        unit_price: 1.2,
        factor: 1,
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
    expect(within(row).getByText('精裁-布')).toBeInTheDocument()
    expect(within(row).getByTestId('op-group')).toHaveTextContent('裁剪')
    expect(within(row).getByTestId('op-qty')).toHaveTextContent('2 套')
    expect(within(row).getByTestId('op-unit-price')).toHaveTextContent('¥8.50')
    expect(within(row).getByTestId('op-status')).toHaveTextContent('已完成')
    expect(within(row).getByTestId('op-done')).toHaveTextContent('2 套')

    // 第二个部位的行也必须渲染（分组不吞数据）
    expect(screen.getByTestId('operation-row-op-3')).toBeInTheDocument()
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
