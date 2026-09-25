'use client'

import { useCallback, useEffect, useState } from 'react'
import { BarChart3, Info, Layers, RefreshCw } from 'lucide-react'
import { toastRequestError } from '@/lib/api-error'
import { savingBoardApi } from '@/lib/api'
import { Badge, Button, Card } from '@/components/ui'
import { cn } from '@/lib/utils'
import {
  NO_DATA,
  cohortBadge,
  coexistenceNote,
  formatMeters,
  formatMetric,
  formatPeriod,
  formatShare,
  metricCards,
  unknownCostHint,
} from '@/lib/saving-board'
import type { SavingBoard, SavingTrend } from '@/types'

/** 时间粒度（服务端**显式拒绝**未知取值 ⇒ 不静默回落，见 `StockBatchConsumptionService`） */
const GRANULARITIES = [
  { value: 'month', label: '按月' },
  { value: 'week', label: '按周（ISO 周）' },
] as const

/**
 * 省料看板 `/production/saving-board`（issue #5159 剩余范围）—— L2 批次结构性 + L3 采购/财务口径。
 *
 * ## 🔴 两条指标**并用**（#5144 已锁），页面上必须同时看得见
 * ①「剩余 ≤0.2m 的批次占比 ↑」治「用不尽」；②「入库/采购总米数 ↓」治「买太多」。
 * **单看①会被排料省料误导**：排料省料 ⇒ 批次**剩得更多** ⇒ 只留①会把效率提升**显示成变差**。
 * 两段文案都在页面上（指标卡 + 说明条），不是只写进文档。
 *
 * ## 🔴 存量导入**单列**（判据 2）
 * `source='opening'` 的那批 = 切换前的历史包袱。它**恒有自己的来源组卡**（哪怕为空），
 * 与「切换后」**并列而不是相加** —— 混进切换后的分子分母 ⇒ 历史包袱把改善吃掉，看板永远看不出变化。
 *
 * ## 🔴 无数据**不冒充 0**（判据 4）
 * 占比 / 合计 / 比率 / 单位产出消耗在无数据时服务端回 `null`，本页渲染成「无数据」；
 * **不回落成 0**（0 会被读成「没有浪费」）。计数类（批次数 / 行数）照实显示 —— 计数为 0 是事实。
 *
 * ## 米数 / 占比 / 金额**一律原样渲染服务端值**
 * 页面与 `lib/saving-board.ts` 都不做任何四则运算（要求是「看板汇总 == Σ 逐单」逐值相等；
 * 在浏览器里再算一遍就是第二份会漂的口径）。
 */
export default function SavingBoardPage() {
  const [granularity, setGranularity] = useState<string>('month')
  const [board, setBoard] = useState<SavingBoard | null>(null)
  const [trend, setTrend] = useState<SavingTrend | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [b, t] = await Promise.all([
        savingBoardApi.board({ granularity }),
        savingBoardApi.trend({ granularity }),
      ])
      setBoard(b.data?.data ?? null)
      setTrend(t.data?.data ?? null)
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

  const cards = metricCards({ cohorts: board?.cohorts, trend })
  const cohorts = board?.cohorts ?? []
  const batchGroups = board?.batchGroups ?? []
  const savedGroups = board?.savedGroups ?? []
  const points = trend?.points ?? []

  return (
    <div className="p-6 space-y-4">
      {/* 页头 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900 flex items-center gap-2">
            <Layers className="w-5 h-5 text-primary-600" />
            省料看板
          </h1>
          <p className="text-sm text-neutral-500 mt-1">
            省了多少料，看两件事：① 每批布用剩多少 ② 每平方米成品用掉多少米布；
            <strong>存量导入批次单独成组</strong>，不与切换后混算
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

      {/* 🔴 两条指标（恒两条 —— 缺任一条 ⇒ 判据红） */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {cards.map((card) => (
          <Card key={card.key}>
            <div className="p-5" data-testid={card.testId}>
              <div className="text-sm text-neutral-500">{card.label}</div>
              <div
                className={cn(
                  'mt-1 font-mono text-2xl',
                  card.value === NO_DATA ? 'text-neutral-400 text-lg' : 'text-neutral-900'
                )}
              >
                {card.value}
              </div>
              <div className="mt-1 text-xs text-neutral-500">{card.hint}</div>
            </div>
          </Card>
        ))}
      </div>

      {/* 🔴 「单看①会误导」—— 必须写在**页面**上（不是只写进文档） */}
      <div
        data-testid="saving-metric-coexistence-note"
        className="flex items-start gap-2 bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-900"
      >
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <span>{coexistenceNote({ cohorts: board?.cohorts, trend })}</span>
      </div>

      {/* 来源组合计（存量导入**单列**一张卡；判据 2） */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-testid="saving-cohorts">
        {cohorts.map((c) => (
          <Card key={c.cohort}>
            <div className="p-5" data-testid={`saving-cohort-${c.cohort}`}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-neutral-900">{c.cohortLabel}</span>
                {cohortBadge(c.cohort) && <Badge variant={c.opening ? 'warning' : 'default'}>{cohortBadge(c.cohort)}</Badge>}
              </div>
              <dl className="mt-3 space-y-1 text-sm">
                <div className="flex justify-between">
                  <dt className="text-neutral-500">批次数</dt>
                  <dd className="font-mono text-neutral-900" data-testid={`saving-cohort-${c.cohort}-batch-count`}>
                    {formatMetric(c.batchCount, 0)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-neutral-500">{c.buckets?.[0]?.label ?? '剩余最小档'}占比</dt>
                  <dd className="font-mono text-neutral-900" data-testid={`saving-cohort-${c.cohort}-le-share`}>
                    {formatShare(c.le0_2Share)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-neutral-500">余量合计</dt>
                  <dd className="font-mono text-neutral-900">{formatMeters(c.remainingMeters)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-neutral-500">省料</dt>
                  <dd className="font-mono text-neutral-900">
                    {formatMeters(c.savedMeters)} / {formatMetric(c.savedAmount)} 元
                  </dd>
                </div>
              </dl>
              {/* 恒四档（空档也回 0 —— 计数为 0 是事实；**占比**才是「无数据」） */}
              <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-neutral-500">
                {(c.buckets ?? []).map((b) => (
                  <span key={b.key} data-testid={`saving-cohort-${c.cohort}-bucket-${b.key}`}>
                    {b.label}：{formatMetric(b.batchCount, 0)} 批 / {formatShare(b.share)}
                  </span>
                ))}
              </div>
              {unknownCostHint(c.unknownCostLines) && (
                <p className="mt-2 text-xs text-amber-700">{unknownCostHint(c.unknownCostLines)}</p>
              )}
            </div>
          </Card>
        ))}
      </div>

      {/* L2 分档聚合：物料（商品 × 颜色 × 门幅）× 时间 × 来源组 */}
      <Card>
        <div className="p-5" data-testid="saving-batch-groups">
          <h2 className="text-sm font-medium text-neutral-900 mb-3">
            批次余量分档（每批布用剩多少 · 按物料 × 时间 × 来源分组）
          </h2>
          {batchGroups.length === 0 ? (
            <div className="px-4 py-10 text-center text-neutral-400 text-sm" data-testid="saving-batch-groups-empty">
              {NO_DATA}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-neutral-600">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">时间</th>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">来源组</th>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">物料（商品 × 颜色 × 门幅）</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">批次数</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">剩余最小档</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">占比</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">余量合计</th>
                  </tr>
                </thead>
                <tbody>
                  {batchGroups.map((g) => (
                    <tr
                      key={`${g.period}-${g.cohort}-${g.materialKey}`}
                      data-testid={`saving-batch-group-${g.cohort}-${g.period ?? 'nodate'}`}
                      className="border-t border-neutral-100"
                    >
                      <td className="px-4 py-2.5 text-neutral-600 whitespace-nowrap">{formatPeriod(g.period)}</td>
                      <td className="px-4 py-2.5">
                        <span className="text-neutral-800">{g.cohortLabel}</span>
                        {cohortBadge(g.cohort) && (
                          <Badge variant={g.opening ? 'warning' : 'default'}>{cohortBadge(g.cohort)}</Badge>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-neutral-700">
                        {g.productId}
                        <span className="text-neutral-400 ml-1.5">{g.skuCode || '-'}</span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMetric(g.batchCount, 0)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                        {formatMetric(g.le0_2Count, 0)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatShare(g.le0_2Share)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(g.remainingMeters)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      {/* L1 汇总：逐单省料按（时间 × 来源 × 物料）聚合 —— 与逐单读面逐值相等 */}
      <Card>
        <div className="p-5" data-testid="saving-saved-groups">
          <div className="flex items-center gap-2 mb-3">
            <BarChart3 className="w-4 h-4 text-primary-600" />
            <h2 className="text-sm font-medium text-neutral-900">逐单省料汇总（与逐单明细逐值相等）</h2>
          </div>
          {savedGroups.length === 0 ? (
            <div className="px-4 py-10 text-center text-neutral-400 text-sm" data-testid="saving-saved-groups-empty">
              {NO_DATA}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-neutral-600">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">时间</th>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">来源组</th>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">物料</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">公式米数</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">排料米数</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">省料米数</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">省料金额</th>
                  </tr>
                </thead>
                <tbody>
                  {savedGroups.map((g) => (
                    <tr
                      key={`${g.period}-${g.cohort}-${g.materialKey}`}
                      data-testid={`saving-saved-group-${g.cohort}-${g.period}`}
                      className="border-t border-neutral-100"
                    >
                      <td className="px-4 py-2.5 text-neutral-600 whitespace-nowrap">{g.period}</td>
                      <td className="px-4 py-2.5 text-neutral-800">{g.cohortLabel}</td>
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
              </table>
            </div>
          )}
        </div>
      </Card>

      {/* L3 趋势（采购/财务口径，不逐单） */}
      <Card>
        <div className="p-5" data-testid="saving-trend">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-neutral-900">
              单位产出的面料消耗（每平方米成品用掉多少米布 · {granularity === 'week' ? '按 ISO 周' : '按月'}）
            </h2>
            <span className="text-xs text-neutral-500">时区 {trend?.timezone ?? '-'}</span>
          </div>
          {points.length === 0 ? (
            <div className="px-4 py-10 text-center text-neutral-400 text-sm" data-testid="saving-trend-empty">
              {NO_DATA}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-neutral-600">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">时间</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">入库/采购米数 ②</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">存量导入米数（单列）</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">消耗米数</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">产出面积（㎡）</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">单位产出（米/㎡）</th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((p) => (
                    <tr key={p.period} data-testid={`saving-trend-${p.period}`} className="border-t border-neutral-100">
                      <td className="px-4 py-2.5 text-neutral-600 whitespace-nowrap">{p.period}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(p.purchasedMeters)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-500">{formatMeters(p.openingMeters)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">{formatMeters(p.consumedMeters)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-500">{formatMetric(p.outputAreaM2)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                        {formatMetric(p.metersPerM2, 4)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}
