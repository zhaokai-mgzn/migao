'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui'
import { productionApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { PieceworkReport } from '@/types'

/**
 * 计件工资 /production/piecework（issue #4205 前端半边）
 *
 * 数据源：GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]
 * —— 报工事件聚合（按人 / 按工序两档；按单下钻的多级联动 UI 不在本单范围）。
 * 口径与生产明细页的 per-order 汇总**同一份逻辑**（后端同一聚合，前端不重算）。
 * 真值源：docs/curtain-production-rules.md §4「工资报表 = 报工事件聚合（按人/按期/按单下钻）」。
 * 返工/报废不计件由后端聚合时排除，本页只做展示。
 */
function currentPeriod(): string {
  return new Date().toISOString().slice(0, 7)
}

function formatMoney(value?: number): string {
  return `¥${Number(value ?? 0).toFixed(2)}`
}

function formatQty(value?: number): string {
  return String(Number(value ?? 0))
}

export default function PieceworkReportPage() {
  const [period, setPeriod] = useState(currentPeriod)
  const [workerName, setWorkerName] = useState('')
  const [tab, setTab] = useState<'worker' | 'operation'>('worker')

  const [report, setReport] = useState<PieceworkReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await productionApi.getPieceworkSummary({
        period,
        worker_name: workerName.trim() || undefined,
      })
      setReport(res.data?.data ?? null)
    } catch (e) {
      console.error(e)
      setReport(null)
      setError('计件工资加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [period, workerName])

  useEffect(() => {
    load()
  }, [load])

  const perWorker = report?.per_worker ?? []
  const perOperation = report?.per_operation ?? []
  const isEmpty = !loading && !error && (report?.total ?? 0) === 0 && perWorker.length === 0 && perOperation.length === 0

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">计件工资</h1>
          <p className="mt-0.5 text-sm text-neutral-500">按期间汇总报工（合格数量 × 工序单价；返工/报废不计件）</p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
          刷新
        </Button>
      </div>

      {/* 查询条件：期间（月份）+ 工人 */}
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex items-center gap-2">
            <label htmlFor="piecework-period" className="text-sm text-neutral-600 whitespace-nowrap">
              期间
            </label>
            <input
              id="piecework-period"
              type="month"
              value={period}
              data-testid="piecework-period"
              onChange={(e) => setPeriod(e.target.value)}
              className="h-9 min-w-[150px] rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="piecework-worker" className="text-sm text-neutral-600 whitespace-nowrap">
              工人
            </label>
            <input
              id="piecework-worker"
              placeholder="按工人筛选（可留空）"
              value={workerName}
              data-testid="piecework-worker-input"
              onChange={(e) => setWorkerName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && load()}
              className="h-9 min-w-[180px] rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400"
            />
          </div>
          <Button size="sm" data-testid="piecework-search" onClick={load} disabled={loading}>
            <Search className="w-4 h-4 mr-1.5" />
            查询
          </Button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500" data-testid="piecework-loading">
          <RefreshCw className="w-4 h-4 animate-spin" />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-neutral-200 bg-white py-10"
          data-testid="piecework-error"
        >
          <AlertCircle className="w-6 h-6 text-red-500" />
          <p className="text-sm text-neutral-600">{error}</p>
          <Button size="sm" data-testid="piecework-retry" onClick={load}>
            重试
          </Button>
        </div>
      )}

      {isEmpty && (
        <div className="rounded-lg border border-neutral-200 bg-white py-10 text-center" data-testid="piecework-empty">
          <p className="text-sm text-neutral-400">该期间暂无计件数据</p>
        </div>
      )}

      {!loading && !error && !isEmpty && (
        <>
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-sm text-neutral-500">期间合计</span>
              <span className="text-2xl font-semibold text-neutral-900" data-testid="piecework-report-total">
                {formatMoney(report?.total)}
              </span>
              <span className="text-sm text-neutral-400">
                {report?.period ?? period} · 共 {perWorker.length} 人
              </span>
            </div>
          </div>

          {/* 按工人 / 按工序 两档 */}
          <div className="rounded-lg border border-neutral-200 bg-white">
            <div className="flex gap-1 border-b border-neutral-200 px-4 pt-3">
              <button
                type="button"
                data-testid="piecework-tab-worker"
                onClick={() => setTab('worker')}
                className={cn(
                  'rounded-t px-4 py-2 text-sm transition-colors',
                  tab === 'worker'
                    ? 'border-b-2 border-primary-600 font-medium text-primary-700'
                    : 'text-neutral-500 hover:text-neutral-800',
                )}
              >
                按工人
              </button>
              <button
                type="button"
                data-testid="piecework-tab-operation"
                onClick={() => setTab('operation')}
                className={cn(
                  'rounded-t px-4 py-2 text-sm transition-colors',
                  tab === 'operation'
                    ? 'border-b-2 border-primary-600 font-medium text-primary-700'
                    : 'text-neutral-500 hover:text-neutral-800',
                )}
              >
                按工序
              </button>
            </div>

            {tab === 'worker' ? (
              <div className="overflow-x-auto" data-testid="piecework-by-worker">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                      <th className="pl-5 pr-4 py-3 font-medium">工人</th>
                      <th className="px-4 py-3 font-medium">计件数量</th>
                      <th className="px-4 py-3 font-medium">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perWorker.map((w) => (
                      <tr
                        key={w.worker_name}
                        className="border-b border-neutral-100 last:border-0"
                        data-testid={`worker-row-${w.worker_name}`}
                      >
                        <td className="pl-5 pr-4 py-3.5 text-neutral-900">{w.worker_name}</td>
                        <td className="px-4 py-3.5 text-neutral-600">{formatQty(w.qty)}</td>
                        <td className="px-4 py-3.5 font-medium text-neutral-900">{formatMoney(w.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {perWorker.length === 0 && <p className="py-8 text-center text-sm text-neutral-400">无数据</p>}
              </div>
            ) : (
              <div className="overflow-x-auto" data-testid="piecework-by-operation">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                      <th className="pl-5 pr-4 py-3 font-medium">工序</th>
                      <th className="px-4 py-3 font-medium">计件数量</th>
                      <th className="px-4 py-3 font-medium">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perOperation.map((o) => (
                      <tr
                        key={o.operation}
                        className="border-b border-neutral-100 last:border-0"
                        data-testid={`operation-row-${o.operation}`}
                      >
                        <td className="pl-5 pr-4 py-3.5 text-neutral-900">{o.operation}</td>
                        <td className="px-4 py-3.5 text-neutral-600">{formatQty(o.qty)}</td>
                        <td className="px-4 py-3.5 font-medium text-neutral-900">{formatMoney(o.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {perOperation.length === 0 && <p className="py-8 text-center text-sm text-neutral-400">无数据</p>}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
