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
//      （裁床必须看得到「去哪一批拿料」，所以这一列是**常驻列**，不是有值才出现）。
//
// ⚠️ 本组件**不重算**：不按 `fabric_meters` 除幅数、不把 `null` 折 0 —— 它只渲染服务端给的键。
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import CutPlanTable from '@/components/production/CutPlanTable'
import type { ProcessingOrderSetRow } from '@/types'

/** 逐字照后端 `set_overview.cut_plan` 的形状（十键恒在，缺值 null；issue #5693 + #6754）。 */
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
        fabric_meters: null,
        panel_count: null,
        panel_length_m: null,
        remark: null,
        missing_reason: '本套该部位没有「精裁」工序实例：用料米数无从取（不猜）',
      },
    ],
  },
]

describe('CutPlanTable（issue #5693 精裁输出清单）', () => {
  it('① 逐条渲染「裁多长 × 几片」+ 用料 + 套号 / 部位 / 组件 / 备注', () => {
    render(<CutPlanTable sets={SETS} />)

    const row = screen.getByTestId('cut-plan-row-CSO260915-02615-014-oi-cloth')
    expect(within(row).getByText('CSO260915-02615-014')).toBeInTheDocument()
    expect(within(row).getByText('布帘')).toBeInTheDocument()
    expect(within(row).getByText('主布')).toBeInTheDocument()
    expect(within(row).getByText('布艺遮光帘A')).toBeInTheDocument()
    expect(within(row).getByText('12.30 米')).toBeInTheDocument()
    // 数量显示口径与工人端 `render.mjs` 的 `fmtQty` 一致（toFixed(2)）
    expect(within(row).getByText('6.15 米 × 2 片')).toBeInTheDocument()
    expect(within(row).getByText('公式--48个折')).toBeInTheDocument()
    // 派工指定批次（issue #6754）：裁床据此知道去哪一批拿料
    expect(within(row).getByText('PC-20261008-0003')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^cut-plan-row-/)).toHaveLength(2)
  })

  it('🔴 ② 缺值不渲染假数据：null ⇒ —（不出现 0.00 / 0 片 / 1 片）+ 原因可见', () => {
    render(<CutPlanTable sets={SETS} />)

    const size = screen.getByTestId('cut-plan-size-CSO260915-02615-014-oi-gauze')
    expect(size).toHaveTextContent('—')
    expect(size).toHaveTextContent('没有「精裁」工序实例')
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

  it('③ 清单全空 / 无套件 ⇒ 不渲染假表格，只给可行动空态', () => {
    for (const sets of [[], undefined, [{ set_id: 's1', set_no: 'S-1' }] as ProcessingOrderSetRow[]]) {
      const { container, unmount } = render(<CutPlanTable sets={sets} />)
      expect(container.querySelector('[data-testid="cut-plan-table"]')).toBeNull()
      expect(screen.getByTestId('cut-plan-empty')).toBeInTheDocument()
      unmount()
    }
  })
})
