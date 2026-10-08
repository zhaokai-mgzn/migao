'use client'

import { useCallback, useEffect, useState } from 'react'
import { Layers, RefreshCw } from 'lucide-react'
import { toastRequestError } from '@/lib/api-error'
import { savingBoardApi } from '@/lib/api'
import { Button, Card } from '@/components/ui'
import { cn } from '@/lib/utils'
import {
  NO_DATA,
  batchTrendNote,
  batchTrendTitle,
  comparisonText,
  footnotes,
  formatMeters,
  formatMetric,
  formatPeriod,
  formatShare,
  metricView,
  savedRule,
  unknownCostHint,
} from '@/lib/saving-board'
import type { SavingBoard } from '@/types'

/** 时间粒度（服务端**显式拒绝**未知取值 ⇒ 不静默回落，见 `StockBatchConsumptionService`） */
const GRANULARITIES = [
  { value: 'month', label: '按月' },
  { value: 'week', label: '按周（ISO 周）' },
] as const

/**
 * 省料看板 `/production/saving-board`（读面 issue #5159；**首屏形态 issue #6459 用户裁定重做**）。
 *
 * ## 页面只回答两个问题
 * ① **省了多少布**（服务端 `total.savedMeters` / `comparison.savedMeters`）
 * ② **省了多少钱**（服务端 `total.savedAmount` / `comparison.savedAmount`）
 * 外加一张「几乎用完的布 · 批数」趋势表（服务端 `batchTrend`）与一张默认收起的省料明细。
 *
 * ## 🔴 用户裁定（issue #6459，逐字）
 * 「这个功能只需要用数据和规则说清楚我们是如何省下多少布料，节省了多少成本即可」
 * 「这么多废话文字留在页面上只会干扰用户」。
 * ⇒ **删掉**：门道卡（因果链）、术语词典、逐卡 hint、「两条指标并用」说明条、
 * 来源组对照表（`切换后（采购入库）/ 存量导入（切换前历史包袱）/ 来源未知` 三行）、
 * 单位产出消耗趋势表。**有意改判** #5144「两条指标必须并用」—— 见用例 PR-096 的溯源。
 * 页面自带文案只剩：页头一句规则（`savedRule`）+ 趋势表一句（`batchTrendNote`）+ 折叠区口径。
 *
 * ## 🔴 口径**一字不放宽**（改的是呈现，不是口径）
 * - 历史导入（`source='opening'`）**不进**趋势的分子分母（服务端 `batchTrend` 只含采购腿）；
 * - 「无数据」**不冒充 0**：`null` 一律渲染成「无数据」，**不回落成 0**；
 * - 米数 / 金额 / 占比 / 环比**一律原样渲染服务端值**：本页与其助手**没有一处**四则运算，
 *   也没有一处自己的好坏判定（两处都只做字符串拼装与取值）；
 * - 一条读面：页面只调 `saving-board`（不再调 `saving-trend`）⇒ 不存在「两条腿不同参」的口径漂移面。
 *
 * ## 🔴 内部口径词不上屏
 * `切换后` / `存量导入` / `来源未知` 是服务端分组标签，**不渲染**（由
 * `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts` 的形态③ 逐行判红）。
 * 历史库存这件事用**商家的话**在折叠区说一次：「开业时导入的老库存不算」。
 */
export default function SavingBoardPage() {
  const [granularity, setGranularity] = useState<string>('month')
  const [board, setBoard] = useState<SavingBoard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const b = await savingBoardApi.board({ granularity })
      setBoard(b.data?.data ?? null)
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载省料看板失败')
      toastRequestError(e, '加载省料看板失败')
    } finally {
      setLoading(false)
    }
  }, [granularity])

  useEffect(() => {
    void load()
  }, [load])

  const total = board?.total
  const comparison = board?.comparison
  // 档位文案取自服务端四档的第一档（真值渲染，不写死数字 —— §22 基线纪律①）
  const bucketLabel = board?.cohorts?.[0]?.buckets?.[0]?.label
  const batchTrend = board?.batchTrend ?? []
  const savedGroups = board?.savedGroups ?? []

  // 首屏两个大数字：本期取服务端 `comparison`，读不出（含后端未部署）则退回服务端 `total`
  const meters = metricView(comparison?.savedMeters, total?.savedMeters)
  const amount = metricView(comparison?.savedAmount, total?.savedAmount)
  const metersComparison = comparisonText(comparison?.savedMeters, 'meters')
  const amountComparison = comparisonText(comparison?.savedAmount, 'amount')

  return (
    <div className="p-6 space-y-4">
      {/* 页头：标题 + **一句**规则（用户要求「用数据和规则说清楚」） */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900 flex items-center gap-2">
            <Layers className="w-5 h-5 text-primary-600" />
            省料看板
          </h1>
          <p data-testid="saving-rule" className="text-sm text-neutral-500 mt-1">
            {savedRule()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="时间粒度"
            data-testid="saving-granularity"
            value={granularity}
            onChange={(e) => setGranularity(e.target.value)}
            className="h-9 rounded-md border border-neutral-300 bg-white px-2 text-sm text-neutral-700"
          >
            {GRANULARITIES.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
          <Button variant="secondary" onClick={() => void load()} loading={loading}>
            <RefreshCw className="w-4 h-4 mr-1.5" />
            刷新
          </Button>
        </div>
      </div>

      {error && (
        <div data-testid="saving-error" className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          加载失败：{error}
        </div>
      )}

      {/* ① 结论：省了多少布 / 省了多少钱（数值全部原样来自服务端，只做取值与拼装） */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <div className="p-5" data-testid="saving-metric-saved-meters">
            <div className="text-sm text-neutral-500">
              {meters.period ? `省下的布 · ${meters.period}` : '省下的布'}
            </div>
            <div
              className={cn(
                'mt-1 font-mono text-3xl',
                meters.value === null || meters.value === undefined
                  ? 'text-neutral-400 text-xl'
                  : 'text-neutral-900'
              )}
            >
              {formatMeters(meters.value)}
            </div>
            {metersComparison && (
              <div data-testid="saving-comparison-saved-meters" className="mt-1 text-xs text-neutral-500">
                {metersComparison}
              </div>
            )}
            <div className="mt-1 text-xs text-neutral-500">累计 {formatMeters(meters.cumulative)}</div>
          </div>
        </Card>
        <Card>
          <div className="p-5" data-testid="saving-metric-saved-amount">
            <div className="text-sm text-neutral-500">
              {amount.period ? `省下的钱 · ${amount.period}` : '省下的钱'}
            </div>
            <div
              className={cn(
                'mt-1 font-mono text-3xl',
                amount.value === null || amount.value === undefined
                  ? 'text-neutral-400 text-xl'
                  : 'text-neutral-900'
              )}
            >
              {formatMetric(amount.value)} 元
            </div>
            {amountComparison && (
              <div data-testid="saving-comparison-saved-amount" className="mt-1 text-xs text-neutral-500">
                {amountComparison}
              </div>
            )}
            <div className="mt-1 text-xs text-neutral-500">累计 {formatMetric(amount.cumulative)} 元</div>
          </div>
        </Card>
      </div>

      {/* ② 趋势：几乎用完的布 · 批数（服务端 `batchTrend`，只含系统采购入库的批次） */}
      <Card>
        <div className="p-5" data-testid="saving-batch-trend">
          <h2 className="text-sm font-medium text-neutral-900 mb-1">{batchTrendTitle(bucketLabel)}</h2>
          <p className="text-xs text-neutral-500 mb-3">{batchTrendNote()}</p>
          {batchTrend.length === 0 ? (
            <div data-testid="saving-batch-trend-empty" className="px-4 py-10 text-center text-neutral-400 text-sm">
              {NO_DATA}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-neutral-600">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">时间</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">几乎用完的布（批）</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">当期收进的布（批）</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">占比</th>
                  </tr>
                </thead>
                <tbody>
                  {batchTrend.map((p) => (
                    <tr
                      key={p.period ?? 'nodate'}
                      data-testid={`saving-batch-trend-${p.period ?? 'nodate'}`}
                      className="border-t border-neutral-100"
                    >
                      <td className="px-4 py-2.5 text-neutral-600 whitespace-nowrap">{formatPeriod(p.period)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                        {formatMetric(p.le0_2Count, 0)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                        {formatMetric(p.batchCount, 0)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatShare(p.le0_2Share)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      {/* ③ 省在哪：逐单省料汇总（与逐单明细逐值相等）+ 合计行（服务端 total）；默认收起 */}
      <Card>
        <details className="p-5" data-testid="saving-saved-groups-details">
          <summary className="cursor-pointer text-sm font-medium text-neutral-900">省料明细（按月 × 物料）</summary>
          <div className="mt-3" data-testid="saving-saved-groups">
            {savedGroups.length === 0 ? (
              <div data-testid="saving-saved-groups-empty" className="px-4 py-10 text-center text-neutral-400 text-sm">
                {NO_DATA}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-neutral-50 text-neutral-600">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">时间</th>
                      <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">物料</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">该领（公式米数）</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">− 实领（排料米数）</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">= 省下</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">省下的钱</th>
                    </tr>
                  </thead>
                  <tbody>
                    {savedGroups.map((g) => (
                      <tr
                        key={`${g.period}-${g.cohort}-${g.materialKey}`}
                        data-testid={`saving-saved-group-${g.period}-${g.materialKey}`}
                        className="border-t border-neutral-100"
                      >
                        <td className="px-4 py-2.5 text-neutral-600 whitespace-nowrap">{g.period}</td>
                        <td className="px-4 py-2.5 text-neutral-700">{g.materialKey}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(g.formulaMeters)}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(g.plannedMeters)}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(g.savedMeters)}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                          {formatMetric(g.savedAmount)} 元
                          {unknownCostHint(g.unknownCostLines) && (
                            <span className="block text-xs text-amber-700">{unknownCostHint(g.unknownCostLines)}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {/* 合计腿：**原样渲染服务端 `total`**（前端不求和 —— 判据 1 的落点） */}
                  <tfoot>
                    <tr
                      data-testid="saving-saved-groups-total"
                      className="border-t-2 border-neutral-200 bg-neutral-50 font-medium"
                    >
                      <td className="px-4 py-2.5 text-neutral-700" colSpan={2}>
                        合计
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(total?.formulaMeters)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(total?.plannedMeters)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(total?.savedMeters)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                        {formatMetric(total?.savedAmount)} 元
                        {unknownCostHint(total?.unknownCostLines) && (
                          <span className="block text-xs text-amber-700">{unknownCostHint(total?.unknownCostLines)}</span>
                        )}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>
        </details>
      </Card>

      {/* ④ 口径与边界（折叠）：首屏之外的口径一次说完，默认收起 */}
      <details
        data-testid="saving-footnotes"
        className="rounded-lg border border-neutral-200 bg-white p-4 text-xs text-neutral-600"
      >
        <summary className="cursor-pointer text-sm font-medium text-neutral-800">口径与边界</summary>
        <ul className="mt-2 list-disc pl-4 space-y-0.5">
          {footnotes(board?.timezone).map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}
