'use client'

import { useState } from 'react'
import { PageCard } from '@/components/ui'
import { formatHours, formatRate } from '@/lib/quality-check'
import type { QualityStats, QualityStatsGroup, QualityStatsWindow } from '@/types'

/**
 * 质检**指标**面板（P0 + P1，issue #7192）—— `/quality-inspections` 页顶部。
 *
 * ## 口径（🔴 全部来自服务端，本组件**不重算**任何率）
 *
 * - **首检合格率**（主位）= 该件**第一次**判定为合格的件数 ÷ 已检件数（复检合格不洗白）；
 * - **当前合格率 / 返工率 / 报废率** = 按**最新**判定计（与页面上方四态计数同源）；
 * - **未检不进分母**；0 样本 ⇒ 服务端给 `null` ⇒ 这里显示「—」（**不是** 0%，两句话语义不同）；
 * - 待检积压的「最久待检」是**近似**（没有「进入待检」时间戳，按加工单生成时刻起算）——
 *   界面必须带「近似」二字，不做假精确。
 *
 * ## 版面纪律（研发模式 §31 P1）
 *
 * 常驻面**不随数据增长**：趋势只画最近 14 个桶、分组每页 Top-5（服务端已封顶），
 * 固定高度、不出现整屏告警块。
 */
interface QualityMetricsPanelProps {
  stats: QualityStats | null
  loading: boolean
  error: string
  window: QualityStatsWindow
  onWindowChange: (next: QualityStatsWindow) => void
  onRetry: () => void
}

/** 时间窗选项（默认「本月」—— 老板最常问的是「这个月怎么样」）。 */
export const STATS_WINDOW_OPTIONS: { value: QualityStatsWindow; label: string }[] = [
  { value: 'today', label: '今日' },
  { value: 'week', label: '本周' },
  { value: 'month', label: '本月' },
  { value: 'all', label: '全部' },
]

/** 分组维度（标签 ⇄ 服务端键名一一对应）。 */
const GROUP_TABS: { key: 'by_processing_order' | 'by_product' | 'by_inspector'; label: string }[] = [
  { key: 'by_processing_order', label: '加工单' },
  { key: 'by_product', label: '商品' },
  { key: 'by_inspector', label: '检验人' },
]

/** 趋势最多画的桶数（常驻面克制：超出只画最近 N 个，不随月份数增长）。 */
const TREND_MAX_POINTS = 14

export default function QualityMetricsPanel({
  stats,
  loading,
  error,
  window: activeWindow,
  onWindowChange,
  onRetry,
}: QualityMetricsPanelProps) {
  const [groupKey, setGroupKey] = useState<'by_processing_order' | 'by_product' | 'by_inspector'>(
    'by_processing_order',
  )

  const groups: QualityStatsGroup[] = stats ? stats[groupKey] ?? [] : []
  const trend = stats ? stats.trend.slice(-TREND_MAX_POINTS) : []
  const inspected = stats?.counts.inspected ?? 0
  const lowSample = stats ? inspected > 0 && inspected < stats.min_sample : false

  return (
    <PageCard testId="quality-metrics-panel" padded={false}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-neutral-100 px-5 py-3">
        <h2 className="text-base font-medium text-neutral-900">质检指标</h2>
        <div className="flex items-center gap-1" role="group" aria-label="指标时间范围">
          {STATS_WINDOW_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              data-testid={`quality-metrics-window-${option.value}`}
              aria-pressed={activeWindow === option.value}
              onClick={() => onWindowChange(option.value)}
              className={
                activeWindow === option.value
                  ? 'rounded-md bg-neutral-900 px-2.5 py-1 text-xs text-white'
                  : 'rounded-md px-2.5 py-1 text-xs text-neutral-500 hover:bg-neutral-50'
              }
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <div className="px-5 py-4">
          <p className="text-sm text-neutral-600" data-testid="quality-metrics-error">
            {error}
          </p>
          <button
            type="button"
            className="mt-2 text-xs text-primary-600 hover:text-primary-700"
            onClick={onRetry}
          >
            重新加载
          </button>
        </div>
      ) : loading && !stats ? (
        <p className="px-5 py-6 text-sm text-neutral-400" data-testid="quality-metrics-loading">
          加载中…
        </p>
      ) : stats ? (
        <div className="px-5 py-4">
          {/* 主位：首检合格率 + 样本量 */}
          <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
            <div data-testid="quality-metric-first-pass">
              <div className="text-xs text-neutral-500">首检合格率</div>
              <div className="text-2xl font-semibold text-neutral-900">
                {formatRate(stats.rates.first_pass_rate)}
              </div>
            </div>
            <div data-testid="quality-metric-current-pass">
              <div className="text-xs text-neutral-500">当前合格率</div>
              <div className="text-base font-medium text-neutral-900">
                {formatRate(stats.rates.current_pass_rate)}
              </div>
            </div>
            <div data-testid="quality-metric-rework">
              <div className="text-xs text-neutral-500">返工率</div>
              <div className="text-base font-medium text-neutral-900">
                {formatRate(stats.rates.rework_rate)}
              </div>
            </div>
            <div data-testid="quality-metric-scrap">
              <div className="text-xs text-neutral-500">报废率</div>
              <div className="text-base font-medium text-neutral-900">
                {formatRate(stats.rates.scrap_rate)}
              </div>
            </div>
          </div>

          <p className="mt-2 text-xs text-neutral-500" data-testid="quality-metric-sample">
            已检 {inspected} 件
            {lowSample ? ` · 样本偏少（不足 ${stats.min_sample} 件），率仅供参考` : ''}
          </p>

          {/* 待检积压（近似口径：必须标注「近似」） */}
          <p className="mt-1 text-xs text-neutral-500" data-testid="quality-backlog">
            待检积压 {stats.backlog.pending} 件 · 最久待检{' '}
            {formatHours(stats.backlog.oldest_pending_hours)}（近似：按加工单生成时刻起算）
          </p>

          {/* 趋势（最近 N 个桶；固定高度） */}
          <div className="mt-4" data-testid="quality-trend">
            <div className="text-xs text-neutral-500">首检合格率趋势</div>
            {trend.length === 0 ? (
              <p className="mt-1 text-xs text-neutral-400" data-testid="quality-trend-empty">
                本时段没有已检记录
              </p>
            ) : (
              <ul className="mt-2 flex flex-wrap gap-2">
                {trend.map((point) => (
                  <li
                    key={point.bucket}
                    data-testid="quality-trend-point"
                    className="w-16 text-center"
                    title={`${point.bucket} · 已检 ${point.inspected} 件`}
                  >
                    <div className="h-16 flex items-end justify-center">
                      <div
                        className="w-4 rounded-t bg-primary-500"
                        style={{ height: `${Math.max(2, (point.first_pass_rate ?? 0) * 64)}px` }}
                      />
                    </div>
                    <div className="mt-1 text-[10px] text-neutral-500">
                      {formatRate(point.first_pass_rate)}
                    </div>
                    <div className="text-[10px] text-neutral-400">{point.bucket}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* 分组 Top-5（按已检件数；率 = 首检合格率） */}
          <div className="mt-4" data-testid="quality-groups">
            <div className="flex items-center gap-1" role="group" aria-label="分组维度">
              {GROUP_TABS.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  data-testid={`quality-group-tab-${tab.key}`}
                  aria-pressed={groupKey === tab.key}
                  onClick={() => setGroupKey(tab.key)}
                  className={
                    groupKey === tab.key
                      ? 'rounded-md bg-neutral-100 px-2.5 py-1 text-xs font-medium text-neutral-900'
                      : 'rounded-md px-2.5 py-1 text-xs text-neutral-500 hover:bg-neutral-50'
                  }
                >
                  {tab.label}
                </button>
              ))}
            </div>
            {groups.length === 0 ? (
              <p className="mt-2 text-xs text-neutral-400" data-testid="quality-groups-empty">
                该维度没有已检记录
              </p>
            ) : (
              <table className="mt-2 w-full text-xs">
                <thead className="text-neutral-500">
                  <tr>
                    <th className="py-1 text-left font-medium">名称</th>
                    <th className="py-1 text-right font-medium whitespace-nowrap">已检</th>
                    <th className="py-1 text-right font-medium whitespace-nowrap">首检合格率</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100">
                  {groups.map((group) => (
                    <tr key={group.name} data-testid="quality-group-row">
                      <td className="py-1 text-neutral-900">{group.name}</td>
                      <td className="py-1 text-right text-neutral-600">{group.inspected}</td>
                      <td className="py-1 text-right text-neutral-900">
                        {formatRate(group.first_pass_rate)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      ) : null}
    </PageCard>
  )
}
