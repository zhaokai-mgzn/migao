'use client'

import type { PieceworkSummary } from '@/types'

/**
 * 计件汇总（issue #4000，M4-H 按需单据渲染）
 *
 * 内部计件（给工人）合计 + per_operation 明细 + per_worker 分人；与对外加工费（per_meter 收顾客）
 * **两套账分离**，此处只呈现内部计件（真值源：docs/curtain-production-rules.md §4）。
 * 返工/报废不计件由后端聚合时排除，本组件只做展示。
 */
interface PieceworkTableProps {
  /** 后端计件响应（snake_case 键）；缺省/null → 空态 */
  summary?: PieceworkSummary | null
  className?: string
}

function formatMoney(value?: number): string {
  return `¥${(value ?? 0).toFixed(2)}`
}

export default function PieceworkTable({ summary, className }: PieceworkTableProps) {
  const perOperation = summary?.per_operation ?? []
  const perWorker = Object.entries(summary?.per_worker ?? {})
  const total = summary?.total ?? 0

  if (perOperation.length === 0 && perWorker.length === 0 && !total) {
    return (
      <div className={className} data-testid="piecework-empty">
        <p className="py-8 text-center text-sm text-neutral-400">暂无计件数据</p>
      </div>
    )
  }

  return (
    <div className={className}>
      <div className="mb-4 flex items-baseline gap-2">
        <span className="text-sm text-neutral-500">计件合计</span>
        <span className="text-xl font-semibold text-neutral-900" data-testid="piecework-total">
          {formatMoney(total)}
        </span>
        <span className="text-xs text-neutral-400">（Σ 合格数量 × 工序单价 × 系数，不含返工/报废）</span>
      </div>

      {perOperation.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-neutral-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-200 bg-neutral-50/60">
                <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">工序</th>
                <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">计件金额</th>
              </tr>
            </thead>
            <tbody>
              {perOperation.map((item, index) => (
                <tr
                  key={`${item.operation}-${index}`}
                  data-testid={`piecework-operation-${index}`}
                  className="border-b border-neutral-100 last:border-b-0"
                >
                  <td className="px-4 py-3 text-neutral-900">{item.operation}</td>
                  <td
                    className="px-4 py-3 text-neutral-900 whitespace-nowrap"
                    data-testid="piecework-operation-amount"
                  >
                    {formatMoney(item.amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {perWorker.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-sm font-medium text-neutral-900">分人计件</div>
          <div className="overflow-x-auto rounded-lg border border-neutral-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50/60">
                  <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">工人</th>
                  <th className="px-4 py-2.5 text-left font-medium whitespace-nowrap">计件金额</th>
                </tr>
              </thead>
              <tbody>
                {perWorker.map(([worker, amount], index) => (
                  <tr
                    key={worker}
                    data-testid={`piecework-worker-${index}`}
                    className="border-b border-neutral-100 last:border-b-0"
                  >
                    <td className="px-4 py-3 text-neutral-900">{worker}</td>
                    <td className="px-4 py-3 text-neutral-900 whitespace-nowrap" data-testid="piecework-worker-amount">
                      {formatMoney(amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
