'use client'

import type { CutPlanRow, ProcessingOrderSetRow } from '@/types'

/**
 * 精裁输出清单（issue #5693）—— 给裁床的「**裁多长（米）× 几片**」。
 *
 * <h2>数据从哪来（前端不算第二份）</h2>
 * 只渲染服务端给的 `cut_plan`（取数唯一实现在后端 `ProcessingSetReadService`，
 * 与工人端扫码详情**同一份** `set_overview.cut_plan`）。本组件**不**按 `fabric_meters` 除幅数、
 * 不做单位换算、不把 `null` 折成 0 —— 那就是第二份会漂移的口径。
 *
 * <h2>缺值不渲染假数据（issue #5693 验收）</h2>
 * 三项算不出来时服务端给 `null`（**不用 0 / 1 冒充**）并附 `missing_reason`：
 * 界面按「显式留空」渲染 `—`，并把原因放在同一格的小字里（商家据此知道去补什么）。
 * 整块在「本单一套都不存在 / 清单全空」时不出现假表格，只给一句可行动的空态文案。
 *
 * <h2>行粒度</h2>
 * 行 = **套 × 部位**（服务端的清单就是按套给的）⇒ 本表按套平铺并保留「套号」列，
 * 表头顺序照 issue 正文的字段面：`部位 | 组件/货号 | 用料（米） | 裁多长（米） × 几片 | 备注`。
 * 数量显示口径与工人端 `render.mjs` 的 `fmtQty` 一致（`toFixed(2)`）——两边同一份清单，
 * 不该出现「商家看 12.3 / 工人看 12.30」这种差。
 */
export default function CutPlanTable({ sets }: { sets?: ProcessingOrderSetRow[] }) {
  const rows = (sets ?? []).flatMap((set) =>
    (set?.cut_plan ?? [])
      .filter((row) => row != null)
      .map((row) => ({ setNo: set?.set_no ?? '—', row })),
  )

  if (rows.length === 0) {
    return (
      <p className="text-sm text-neutral-500" data-testid="cut-plan-empty">
        本单还裁不出尺寸：算料没给「用料米数」或「幅数」（清单在服务端算不出来时**不造数**）
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="cut-plan-table">
        <thead>
          <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
            <th className="py-2 pr-3 font-normal">套号</th>
            <th className="py-2 pr-3 font-normal">部位</th>
            <th className="py-2 pr-3 font-normal">组件 / 货号</th>
            <th className="py-2 pr-3 font-normal">用料（米）</th>
            <th className="py-2 pr-3 font-normal">裁多长（米） × 几片</th>
            <th className="py-2 font-normal">备注</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ setNo, row }) => {
            const size = cutSizeOf(row)
            return (
              <tr
                key={`${setNo}-${row.order_item_id}`}
                className="border-b border-neutral-100 align-top"
                data-testid={`cut-plan-row-${setNo}-${row.order_item_id}`}
              >
                <td className="py-2 pr-3 whitespace-nowrap text-neutral-500">{setNo}</td>
                <td className="py-2 pr-3 whitespace-nowrap text-neutral-900">
                  {row.position_kind ?? '—'}
                </td>
                <td className="py-2 pr-3 text-neutral-700">
                  <span>{row.component ?? '—'}</span>
                  <span className="ml-1 text-neutral-500">{row.position_name ?? ''}</span>
                </td>
                <td
                  className="py-2 pr-3 whitespace-nowrap text-neutral-900"
                  data-testid={`cut-plan-meters-${setNo}-${row.order_item_id}`}
                >
                  {fmtMeters(row.fabric_meters, '米')}
                </td>
                <td
                  className="py-2 pr-3 whitespace-nowrap text-neutral-900"
                  data-testid={`cut-plan-size-${setNo}-${row.order_item_id}`}
                >
                  {size}
                  {/* 缺值原因：只在真缺时出现（显式留空 + 标注原因，二者都给） */}
                  {row.missing_reason ? (
                    <span className="mt-0.5 block text-xs text-neutral-500">{row.missing_reason}</span>
                  ) : null}
                </td>
                <td className="py-2 text-neutral-500">{row.remark ?? '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/**
 * 「裁多长 × 几片」一格。
 *
 * 🔴 两项**同生同灭**（服务端同一份分解）：任一项为 `null` ⇒ 整格 `—`，
 * **不**半截渲染「— 米 × 2 片」（那会让人以为片数是确定的）。
 */
function cutSizeOf(row: CutPlanRow) {
  if (row?.panel_count == null || row?.panel_length_m == null) {
    return '—'
  }
  return `${fmtNum(row.panel_length_m)} 米 × ${row.panel_count} 片`
}

/** 数量显示口径与工人端 `render.mjs` 的 `fmtQty` 一致；缺值 ⇒ `—`（**不**折 0）。 */
function fmtMeters(value: number | null | undefined, unit: string) {
  return value == null ? '—' : `${fmtNum(value)} ${unit}`
}

function fmtNum(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : String(value)
}
