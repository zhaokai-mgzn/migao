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

  // ── 套口径（issue #4686，用户裁定 2026-09-20「一樘窗 = 一套」）──
  // 分组粒度 = 一樘窗 = 一套；组头按行业口径显示「第 N 套 / 共 M 套」
  // （真值源 `docs/curtain-production-rules.md` 的「第 N 套/共 M 套」口径 —— 按该文本检索，不写行号）。
  // 套号来源（issue #4784 改判）：读面**追加**的 `set_no`（= 计件报表 `per_set` **同一份口径**）
  // ⇒ N = 该套的序号、M = 套数；缺键 ⇒ 退回「每个部位自成一套」（= 改前行为，不猜）。
  // ⚠️ 下面这组夹具**刻意不带** `set_no` ⇒ 钉的正是那条退回路径（既有判据一字未动）。

  it('多窗订单：组头显示「第 N 套 / 共 M 套」，序号稳定唯一', () => {
    render(<ProductionProgressTable positions={positions} />)

    const first = screen.getByTestId('position-group-布帘')
    const second = screen.getByTestId('position-group-纱帘')
    expect(within(first).getByText('第 1 套 / 共 2 套')).toBeInTheDocument()
    expect(within(second).getByText('第 2 套 / 共 2 套')).toBeInTheDocument()
  })

  it('单窗订单：组头显示「第 1 套 / 共 1 套」', () => {
    render(<ProductionProgressTable positions={[positions[0]]} />)

    expect(screen.getByText('第 1 套 / 共 1 套')).toBeInTheDocument()
  })

  it('组头不再把一樘窗称作「部位」，但仍保留「这是哪一樘窗」的副标题', () => {
    render(<ProductionProgressTable positions={positions} />)

    // 红证（改前实测）：组头逐字为「部位：布帘」/「部位：纱帘」⇒ 下一条改前必红
    expect(screen.queryByText(/部位/)).toBeNull()
    // position_name（加工产物名[+色号]）降为副标题 —— 它是**这一套是哪一樘窗**，不是「部位」
    expect(within(screen.getByTestId('position-group-布帘')).getByText('布帘')).toBeInTheDocument()
    expect(within(screen.getByTestId('position-group-纱帘')).getByText('纱帘')).toBeInTheDocument()
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

/**
 * 套维口径分裂修复（issue #4784）—— 工序进度表与计件报表必须给**同一个**套数。
 *
 * 缺陷原形：读面 `ProductionService.buildPositions` 按 `order_item_id` 分组（= **部位**级，
 * #4388 冻结契约），而本表把**每个分组**当「一套」渲染 ⇒ 一樘「布 + 纱 + 帘头」在工序进度表上
 * 显示 **3 套**；而 #4725 已把套维统一为「一樘窗 = 一套」（`craftLineId` 组）⇒
 * **同一张单：计件报表说 1 套、工序进度表说 3 套**（静默不一致，没有任何东西会因此变红）。
 *
 * 修法（**只加不改**）：读面**追加** `set_no` 键（= #4725 的 `setKey`：V92 套号优先、
 * 无号回落樘窗组键 `craftLineId ?? itemId`），本表按它分组渲染「第 N 套 / 共 M 套」；
 * 部位级信息（`position-group-<position_name>` 分组块 + 行内「逻辑名 · 部位」）一字不丢。
 */
describe('ProductionProgressTable 套维（issue #4784）', () => {
  /** 一樘窗的三个部位（布帘 + 纱帘 + 帘头）—— 同一樘窗 ⇒ **同一个** `set_no`。 */
  const oneWindowThreePositions: ProductionPosition[] = [
    {
      position_name: '布艺遮光帘A 米白',
      set_no: 'win-1',
      operations: [
        {
          id: 'w-1',
          seq: 1,
          operation: '精裁-布',
          logical_name: '精裁',
          position: '布帘',
          group: '裁剪',
          unit: '米',
          qty: 12.3,
          unit_price: 3,
          status: 'pending',
          done_qty: 0,
        },
      ],
    },
    {
      position_name: '纱帘A 米白',
      set_no: 'win-1',
      operations: [
        {
          id: 'w-2',
          seq: 1,
          operation: '打孔-纱',
          logical_name: '打孔',
          position: '纱帘',
          group: '车位',
          unit: '孔',
          qty: 24,
          unit_price: 1.2,
          status: 'pending',
          done_qty: 0,
        },
      ],
    },
    {
      position_name: '帘头A 米白',
      set_no: 'win-1',
      operations: [
        {
          id: 'w-3',
          seq: 1,
          operation: '帘头制作',
          logical_name: '帘头制作',
          position: '帘头',
          group: '后道',
          unit: '个',
          qty: 1,
          unit_price: 2,
          status: 'pending',
          done_qty: 0,
        },
      ],
    },
  ]

  it('🔴 一樘「布+纱+帘头」（同一 set_no）⇒ 「第 1 套 / 共 1 套」（改前 = 第 N 套 / 共 **3** 套）', () => {
    render(<ProductionProgressTable positions={oneWindowThreePositions} />)

    // 改前实测：三个部位各得「第 1/2/3 套 / 共 3 套」⇒ 本断言必红（找不到「共 1 套」）
    expect(screen.getByText('第 1 套 / 共 1 套')).toBeInTheDocument()
    expect(screen.queryByText(/共 3 套/)).toBeNull()
    // 套头**只渲染一次**（不是每个部位重复一遍 —— 那会读成「三套都叫第 1 套」）
    expect(screen.getAllByText(/第 \d+ 套 \/ 共 \d+ 套/)).toHaveLength(1)
  })

  it('反向护栏：部位级信息不丢 —— 三个部位各自成块（position-group）且行内仍是「逻辑名 · 部位」', () => {
    render(<ProductionProgressTable positions={oneWindowThreePositions} />)

    expect(screen.getByTestId('position-group-布艺遮光帘A 米白')).toBeInTheDocument()
    expect(screen.getByTestId('position-group-纱帘A 米白')).toBeInTheDocument()
    expect(screen.getByTestId('position-group-帘头A 米白')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-w-1')).getByText('精裁 · 布帘')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-w-2')).getByText('打孔 · 纱帘')).toBeInTheDocument()
    expect(within(screen.getByTestId('operation-row-w-3')).getByText('帘头制作 · 帘头')).toBeInTheDocument()
  })

  it('两樘窗（各含布 + 纱）⇒ 「第 1 套 / 共 2 套」+「第 2 套 / 共 2 套」（不并成 1 套、也不按部位拆成 4 套）', () => {
    const [cloth, sheer] = oneWindowThreePositions
    render(
      <ProductionProgressTable
        positions={[
          cloth,
          sheer,
          {
            ...cloth,
            position_name: '布艺遮光帘B 米白',
            set_no: 'win-2',
            operations: [{ ...cloth.operations![0], id: 'w-4' }],
          },
          {
            ...sheer,
            position_name: '纱帘B 米白',
            set_no: 'win-2',
            operations: [{ ...sheer.operations![0], id: 'w-5' }],
          },
        ]}
      />,
    )

    expect(screen.getByText('第 1 套 / 共 2 套')).toBeInTheDocument()
    expect(screen.getByText('第 2 套 / 共 2 套')).toBeInTheDocument()
    expect(screen.getAllByText(/第 \d+ 套 \/ 共 \d+ 套/)).toHaveLength(2)
  })

  it('读面缺 set_no（老数据 / 读面未升级）⇒ 退回「每个部位自成一套」（= 改前行为，不猜）', () => {
    render(
      <ProductionProgressTable
        positions={[
          { ...oneWindowThreePositions[0], set_no: undefined },
          { ...oneWindowThreePositions[1], set_no: undefined },
        ]}
      />,
    )

    expect(screen.getByText('第 1 套 / 共 2 套')).toBeInTheDocument()
    expect(screen.getByText('第 2 套 / 共 2 套')).toBeInTheDocument()
  })

  it('某套的第一个部位块无工序 ⇒ 套头不随之消失（套头挂在**非空块**上）', () => {
    render(
      <ProductionProgressTable
        positions={[
          { position_name: '空块', set_no: 'win-1', operations: [] },
          oneWindowThreePositions[0],
        ]}
      />,
    )

    expect(screen.getByText('第 1 套 / 共 1 套')).toBeInTheDocument()
    expect(screen.queryByTestId('position-group-空块')).toBeNull()
    expect(screen.getByTestId('position-group-布艺遮光帘A 米白')).toBeInTheDocument()
  })
})
