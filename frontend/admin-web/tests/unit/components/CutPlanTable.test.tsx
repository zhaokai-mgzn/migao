// case_ids: PP-011, PG-058
// PP-011（加工单生产明细页）：本页新增的「精裁输出清单」表格 —— 给裁床的「裁多长（米）× 几片」。
// PG-058（set_overview 读面）：本表消费的 `cut_plan` 就是该读面里的键，**与工人端扫码详情同一份**
// （服务端唯一实现，issue #5693）。
//
// 🔴 四条判据（每条都能红 —— 红证：把 `cutSizeOf` 的 null 分支删掉 ⇒ ② 红；
//    把批次号那一格删掉 ⇒ ④ 红）：
//   ① 有值 ⇒ 逐条落「6.15 米 × 2 片」+「12.30 米」，且带套号 / 部位 / 组件 / 备注；
//   ② **缺值不渲染假数据**：`null` ⇒ `—`（屏上**不得**出现 `0.00 米 × 0 片` / `× 1 片` 这类
//      由 null 折出来的假数字），缺值原因（`missing_reason`）必须可见；
//   ③ 清单全空 / 无套件 ⇒ 不渲染假表格，只给一句可行动的空态；
//   ④ **批次号列**（issue #6754）：派工指定批次上屏；未指派（服务端 `null`）⇒ `—`
//      （裁床必须看得到「去哪一批拿料」，所以这一列是**常驻列**，不是有值才出现）；
//   ⑤ **从该批裁（米）列**（issue #7722）：这一批裁多少布上屏；未指派 ⇒ `—`（不折 0 米）；
//   ⑥ **没有「帘种」列；「货号」列只印货号**（issue #7737）：帘种数据常缺、组件多为空 ⇒ 一并退场。
//
// ⚠️ 本组件**不重算**：不按 `fabric_meters` 除幅数、不把 `null` 折 0 —— 它只渲染服务端给的键。
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import CutPlanTable from '@/components/production/CutPlanTable'
import type { ProcessingOrderSetRow } from '@/types'

/** 逐字照后端 `set_overview.cut_plan` 的形状（十一键恒在，缺值 null；issue #5693 + #6754 + #7722）。 */
const SETS: ProcessingOrderSetRow[] = [
  {
    set_id: 'set-14',
    set_no: 'CSO260915-02615-014',
    cut_plan: [
      {
        order_item_id: 'oi-cloth',
        position_kind: '布帘',
        position_name: '布艺遮光帘A',
        component: '主布',
        batch_no: 'PC-20261008-0003',
        batch_meters: 12.3,
        fabric_meters: 12.3,
        panel_count: 2,
        panel_length_m: 6.15,
        remark: '公式--48个折',
        missing_reason: null,
      },
      {
        order_item_id: 'oi-gauze',
        position_kind: '纱帘',
        position_name: '纱帘-白',
        component: '纱',
        batch_no: null,
        batch_meters: null,
        fabric_meters: null,
        panel_count: null,
        panel_length_m: null,
        remark: null,
        missing_reason: '这行还没算出用料米数：先在订单行补上窗宽 / 窗高与加工类型，算料出数后这里就有了',
      },
    ],
  },
]

describe('CutPlanTable（issue #5693 精裁输出清单）', () => {
  it('① 逐条渲染「裁多长 × 几片」+ 用料 + 套号 / 货号 / 备注', () => {
    render(<CutPlanTable sets={SETS} />)

    const row = screen.getByTestId('cut-plan-row-CSO260915-02615-014-oi-cloth')
    expect(within(row).getByText('CSO260915-02615-014')).toBeInTheDocument()
    // 货号列（issue #7737）：只印货号 / 商品名 —— 帘种与组件不再上屏
    expect(within(row).getByText('布艺遮光帘A')).toBeInTheDocument()
    expect(within(row).queryByText('布帘')).toBeNull()
    expect(within(row).queryByText('主布')).toBeNull()
    // 用料（米）：唯一来源 = 服务端下发（订单行算料口径优先，#7722）
    // ⚠️ 用 testid 定位，不按文本找 —— 本行「用料 12.30 米」与「从该批裁 12.30 米」是**两个不同的数**
    // （公式口径 vs 批次净额），按文本查会同时命中两格（实测：getByText 报 multiple elements）。
    expect(screen.getByTestId('cut-plan-meters-CSO260915-02615-014-oi-cloth'))
      .toHaveTextContent('12.30 米')
    // 数量显示口径与工人端 `render.mjs` 的 `fmtQty` 一致（toFixed(2)）
    expect(within(row).getByText('6.15 米 × 2 片')).toBeInTheDocument()
    expect(within(row).getByText('公式--48个折')).toBeInTheDocument()
    // 派工指定批次（issue #6754）：裁床据此知道去哪一批拿料
    expect(within(row).getByText('PC-20261008-0003')).toBeInTheDocument()
    // 从该批裁多少布（issue #7722）：与批次号同一份取数（台账净额）
    expect(screen.getByTestId('cut-plan-batch-meters-CSO260915-02615-014-oi-cloth'))
      .toHaveTextContent('12.30 米')
    expect(screen.getAllByTestId(/^cut-plan-row-/)).toHaveLength(2)
  })

  it('🔴 ⑥ 没有「帘种」列；「货号」列只印货号、不拼组件（issue #7737）', () => {
    render(<CutPlanTable sets={SETS} />)

    // ① 帘种列整列删掉（真实数据常整列为空，留着只是空占位）
    expect(screen.queryByRole('columnheader', { name: '帘种' })).toBeNull()
    expect(screen.queryByRole('columnheader', { name: '部位' })).toBeNull()
    // ② 货号列常驻，且格内**只有**货号
    expect(screen.getByRole('columnheader', { name: '货号' })).toBeInTheDocument()
    const cloth = screen.getByTestId('cut-plan-row-CSO260915-02615-014-oi-cloth')
    expect(cloth).toHaveTextContent('布艺遮光帘A')
    // 🔴 反向：把 `component` 拼回格内 ⇒ 本断言红（用户逐字「移除组件」）
    expect(cloth.textContent).not.toContain('主布')
  })

  it('🔴 ② 缺值不渲染假数据：null ⇒ —（不出现 0.00 / 0 片 / 1 片）+ 原因可见', () => {
    render(<CutPlanTable sets={SETS} />)

    const size = screen.getByTestId('cut-plan-size-CSO260915-02615-014-oi-gauze')
    expect(size).toHaveTextContent('—')
    expect(size).toHaveTextContent('还没算出用料米数')
    // 🔴 反向：null **不得**被折成 0 / 1（那正是 issue #5693 验收点名要防的「用 0 冒充」）
    expect(size.textContent).not.toContain('0.00 米 × 0 片')
    expect(size.textContent).not.toContain('× 1 片')
    // 用料格同样留空（不是 0.00）
    const meters = screen.getByTestId('cut-plan-meters-CSO260915-02615-014-oi-gauze')
    expect(meters).toHaveTextContent('—')
    expect(meters.textContent).not.toContain('0.00')
  })

  it('🔴 ④ 批次号列（issue #6754）：常驻列；未指派 ⇒ —（不省格、不折出假批次号）', () => {
    render(<CutPlanTable sets={SETS} />)

    // 列头**常驻**：未指派的行也要有这一格 —— 否则「本系统没有这个概念」与「这一行没指派」分不开
    expect(screen.getByRole('columnheader', { name: '批次号' })).toBeInTheDocument()

    expect(screen.getByTestId('cut-plan-batch-CSO260915-02615-014-oi-cloth'))
      .toHaveTextContent('PC-20261008-0003')

    const gauze = screen.getByTestId('cut-plan-batch-CSO260915-02615-014-oi-gauze')
    expect(gauze).toHaveTextContent('—')
    expect(gauze.textContent).not.toContain('PC-')
  })

  it('🔴 ⑤ 从该批裁（米）列（issue #7722）：常驻列；未指派 ⇒ —（不折 0 米）', () => {
    render(<CutPlanTable sets={SETS} />)

    // 常驻列：未指派的行也有这一格 —— 「没指派」与「没有这个概念」必须分得开
    expect(screen.getByRole('columnheader', { name: '从该批裁（米）' })).toBeInTheDocument()
    expect(screen.getByTestId('cut-plan-batch-meters-CSO260915-02615-014-oi-cloth'))
      .toHaveTextContent('12.30 米')

    const gauze = screen.getByTestId('cut-plan-batch-meters-CSO260915-02615-014-oi-gauze')
    expect(gauze).toHaveTextContent('—')
    expect(gauze.textContent).not.toContain('0.00')
  })

  it('③ 清单全空 / 无套件 ⇒ 不渲染假表格，只给可行动空态', () => {
    for (const sets of [[], undefined, [{ set_id: 's1', set_no: 'S-1' }] as ProcessingOrderSetRow[]]) {
      const { container, unmount } = render(<CutPlanTable sets={sets} />)
      expect(container.querySelector('[data-testid="cut-plan-table"]')).toBeNull()
      expect(screen.getByTestId('cut-plan-empty')).toBeInTheDocument()
      unmount()
    }
  })
})
