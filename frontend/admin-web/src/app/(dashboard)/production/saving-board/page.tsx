'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { BarChart3, ChevronDown, Info, Layers, RefreshCw } from 'lucide-react'
import { toastRequestError } from '@/lib/api-error'
import { savingBoardApi } from '@/lib/api'
import { Badge, Button, Card } from '@/components/ui'
import { cn } from '@/lib/utils'
import {
  NO_DATA,
  causalChain,
  cohortBadge,
  coexistenceNote,
  comparisonText,
  footnotes,
  formatMeters,
  formatMetric,
  formatPeriod,
  formatShare,
  headline,
  metricCards,
  periodAxisNote,
  savedTerms,
  sortByRemainingDesc,
  trendCaveat,
  unknownCostHint,
} from '@/lib/saving-board'
import type { SavingBoard, SavingTrend } from '@/types'

/** 时间粒度（服务端**显式拒绝**未知取值 ⇒ 不静默回落，见 `StockBatchConsumptionService`） */
const GRANULARITIES = [
  { value: 'month', label: '按月' },
  { value: 'week', label: '按周（ISO 周）' },
] as const

/** 「布剩在哪」首屏先给几行（异常优先），其余折叠 —— 异常优先 + 渐进披露（issue #6430） */
const BATCH_GROUP_PREVIEW = 8

/**
 * 省料看板 `/production/saving-board`（issue #5159 剩余范围；**issue #6430 重设计**）。
 *
 * ## 页面讲的故事（一句话主张）
 * 「我买的布，到底有没有被用干净？」——**一条布的生命周期体检**，分三幕：
 * ① **省了多少**（结论条 + 第三张卡：排料比公式少领的米数/金额）
 * ② **剩在哪**（批次余量分档：异常优先 + 展开全部 + 下钻到批次）
 * ③ **在变好还是变坏**（单位产出的面料消耗趋势 + 服务端环比）
 *
 * ## 🔴 两条指标**并用**（#5144 已锁），页面上必须同时看得见
 * ①「剩余最小档的批次占比 ↑」治「用不尽」；②「入库/采购总米数 ↓」治「买太多」。
 * **单看①会被排料省料误导**：排料省料 ⇒ 批次**剩得更多** ⇒ 只留①会把效率提升**显示成变差**。
 * 门道卡（含**因果链**）与指标卡都在页面上（不是只写进文档）。
 *
 * ## 🔴 存量导入**单列**（判据 2）
 * `source='opening'` 的那批 = 切换前的历史包袱。它**恒有自己的来源组行**（哪怕为空），
 * 与「切换后」**并列而不是相加** —— 混进切换后的分子分母 ⇒ 历史包袱把改善吃掉，看板永远看不出变化。
 *
 * ## 🔴 无数据**不冒充 0**（判据 4）
 * 占比 / 合计 / 比率 / 单位产出消耗在无数据时服务端回 `null`，本页渲染成「无数据」；
 * **不回落成 0**（0 会被读成「没有浪费」）。计数类（批次数 / 行数）照实显示 —— 计数为 0 是事实。
 *
 * ## 🔴 米数 / 占比 / 金额 / 环比**一律原样渲染服务端值**，**好坏词也只来自服务端**
 * 页面与 `lib/saving-board.ts` 都不做任何四则运算、也不判「变好/变差」
 * （要求是「看板汇总 == Σ 逐单」逐值相等；在浏览器里再算一遍就是第二份会漂的口径）。
 * 结论条只做**字符串拼装**；`合计` 行取服务端 `total`；环比取服务端 `comparison`（含 `verdict`）。
 *
 * ## 🔴 两条腿**同一个筛选对象**（#6430 的耦合陷阱）
 * `saving-board` 与 `saving-trend` 必须同参 —— 只给一条腿加筛选（例如只加 `productId`）
 * 会让结论卡①与②**分属两个域**（单商品 vs 全店）而账面上看不出来。见 `lib` 的注释与用例「两腿同参」。
 */
export default function SavingBoardPage() {
  const [granularity, setGranularity] = useState<string>('month')
  const [board, setBoard] = useState<SavingBoard | null>(null)
  const [trend, setTrend] = useState<SavingTrend | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedBatchGroups, setExpandedBatchGroups] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      // 🔴 两条腿**按同一个对象**传参（见文件头「两条腿同一个筛选对象」）
      const params = { granularity }
      const [b, t] = await Promise.all([
        savingBoardApi.board(params),
        savingBoardApi.trend(params),
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

  const cards = metricCards({ cohorts: board?.cohorts, total: board?.total, trend })
  const cohorts = board?.cohorts ?? []
  const savedGroups = board?.savedGroups ?? []
  const total = board?.total
  const points = trend?.points ?? []

  // 异常优先：余量大的在前（**纯排序**，不改数值）；默认只给前 N 行，其余「展开全部」
  const sortedBatchGroups = sortByRemainingDesc(board?.batchGroups ?? [])
  const visibleBatchGroups = expandedBatchGroups
    ? sortedBatchGroups
    : sortedBatchGroups.slice(0, BATCH_GROUP_PREVIEW)

  const comparisonSaved = comparisonText(board?.comparison?.savedMeters, 'meters')
  const comparisonLeShare = comparisonText(board?.comparison?.le0_2Share, 'share')
  const comparisonPurchased = comparisonText(trend?.comparison?.purchasedMeters, 'meters')
  const comparisonPerM2 = comparisonText(trend?.comparison?.metersPerM2, 'perM2')

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

      {/* ① 结论条：先把「所以呢」说清楚（数值全部原样来自服务端，只做拼装） */}
      <div
        data-testid="saving-headline"
        className="rounded-lg border border-neutral-200 bg-white p-4 text-sm text-neutral-800"
      >
        {headline({ cohorts: board?.cohorts, total: board?.total }, trend)}
      </div>

      {/* ② 门道卡：为什么一次给两个数（因果链）+ 术语词典 */}
      <div
        data-testid="saving-metric-coexistence-note"
        className="flex items-start gap-2 bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-900"
      >
        <Info className="w-4 h-4 mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p className="font-medium">为什么一次给你两个数？</p>
          <p data-testid="saving-causal-chain">{causalChain()}</p>
          <p>{coexistenceNote({ cohorts: board?.cohorts })}</p>
          <details data-testid="saving-terms" className="pt-1">
            <summary className="cursor-pointer text-xs text-blue-800">这些词是什么意思（点开看）</summary>
            <dl className="mt-1 space-y-0.5 text-xs text-blue-900">
              {savedTerms(cohorts[0]?.buckets?.map((b) => b.label)).map((t) => (
                <div key={t.term}>
                  <dt className="inline font-medium">{t.term}</dt>
                  <dd className="inline">：{t.meaning}</dd>
                </div>
              ))}
            </dl>
          </details>
        </div>
      </div>

      {/* ③ 三张结论卡（前两张 = 两条指标，判据 3 **一条不少**；第三张 = 省了多少） */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
              {card.secondary && <div className="mt-0.5 text-xs text-neutral-500">{card.secondary}</div>}
              <div className="mt-1 text-xs text-neutral-500">{card.hint}</div>
              {card.key === 'le_0_2' && comparisonLeShare && (
                <div data-testid="saving-comparison-le-share" className="mt-1 text-xs text-neutral-500">
                  {comparisonLeShare}
                </div>
              )}
              {card.key === 'saved' && comparisonSaved && (
                <div data-testid="saving-comparison-saved" className="mt-1 text-xs text-neutral-500">
                  {comparisonSaved}
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>

      {/* ④ 来源组对照：存量导入**单列**（判据 2 —— 并列，不相加） */}
      <Card>
        <div className="p-5" data-testid="saving-cohorts">
          <h2 className="text-sm font-medium text-neutral-900 mb-1">来源组对照（三行并列，**不相加**）</h2>
          <p className="text-xs text-neutral-500 mb-3">
            「存量导入」是上系统前的历史包袱，永远单列 —— 混进「切换后」算，改善就永远看不出来。
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-neutral-600">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">来源组</th>
                  <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">批次数</th>
                  <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">剩余最小档占比</th>
                  <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">余量合计</th>
                  <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">省料</th>
                  <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">四档明细</th>
                </tr>
              </thead>
              <tbody>
                {cohorts.map((c) => (
                  <tr
                    key={c.cohort}
                    data-testid={`saving-cohort-${c.cohort}`}
                    className="border-t border-neutral-100 align-top"
                  >
                    <td className="px-4 py-2.5">
                      <span className="text-neutral-900">{c.cohortLabel}</span>
                      {cohortBadge(c.cohort) && (
                        <Badge variant={c.opening ? 'warning' : 'default'}>{cohortBadge(c.cohort)}</Badge>
                      )}
                    </td>
                    <td
                      className="px-4 py-2.5 text-right font-mono text-neutral-900"
                      data-testid={`saving-cohort-${c.cohort}-batch-count`}
                    >
                      {formatMetric(c.batchCount, 0)}
                    </td>
                    <td
                      className="px-4 py-2.5 text-right font-mono text-neutral-900"
                      data-testid={`saving-cohort-${c.cohort}-le-share`}
                    >
                      {formatShare(c.le0_2Share)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                      {formatMeters(c.remainingMeters)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                      {formatMeters(c.savedMeters)} / {formatMetric(c.savedAmount)} 元
                      {unknownCostHint(c.unknownCostLines) && (
                        <span className="block text-xs text-amber-700">{unknownCostHint(c.unknownCostLines)}</span>
                      )}
                    </td>
                    {/* 恒四档（空档也回 0 —— 计数为 0 是事实；**占比**才是「无数据」） */}
                    <td className="px-4 py-2.5 text-xs text-neutral-500">
                      {(c.buckets ?? []).map((b) => (
                        <div key={b.key} data-testid={`saving-cohort-${c.cohort}-bucket-${b.key}`}>
                          {b.label}：{formatMetric(b.batchCount, 0)} 批 / {formatShare(b.share)}
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      {/* ⑤ 布剩在哪：批次余量分档（异常优先 + 展开全部 + 下钻） */}
      <Card>
        <div className="p-5" data-testid="saving-batch-groups">
          <h2 className="text-sm font-medium text-neutral-900 mb-1">
            布剩在哪 · 批次余量分档（每批布用剩多少 · 按物料 × 时间 × 来源分组）
          </h2>
          <p data-testid="saving-period-axis-note" className="text-xs text-neutral-500 mb-3">
            {periodAxisNote()}
          </p>
          {sortedBatchGroups.length === 0 ? (
            <div className="px-4 py-10 text-center text-neutral-400 text-sm" data-testid="saving-batch-groups-empty">
              {NO_DATA}
            </div>
          ) : (
            <>
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
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">动作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleBatchGroups.map((g) => (
                      <tr
                        key={`${g.period}-${g.cohort}-${g.materialKey}`}
                        data-testid={`saving-batch-group-${g.cohort}-${g.period ?? 'nodate'}-${g.skuCode || g.productId}`}
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
                        <td className="px-4 py-2.5 text-right whitespace-nowrap">
                          <Link href={`/products/${g.productId}`} className="text-primary-600 hover:underline">
                            看批次
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {sortedBatchGroups.length > BATCH_GROUP_PREVIEW && (
                <button
                  type="button"
                  data-testid="saving-batch-groups-toggle"
                  onClick={() => setExpandedBatchGroups((v) => !v)}
                  className="mt-3 inline-flex items-center gap-1 text-sm text-primary-600 hover:underline"
                >
                  {expandedBatchGroups ? '收起，只看最需要看的几组' : `展开全部 ${sortedBatchGroups.length} 组`}
                  <ChevronDown className={cn('w-4 h-4 transition-transform', expandedBatchGroups && 'rotate-180')} />
                </button>
              )}
            </>
          )}
        </div>
      </Card>

      {/* ⑥ 省在哪：逐单省料汇总（与逐单明细逐值相等）+ 合计行（服务端 total） */}
      <Card>
        <div className="p-5" data-testid="saving-saved-groups">
          <div className="flex items-center gap-2 mb-3">
            <BarChart3 className="w-4 h-4 text-primary-600" />
            <h2 className="text-sm font-medium text-neutral-900">省在哪 · 逐单省料汇总（与逐单明细逐值相等）</h2>
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
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">物料</th>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">来源组</th>
                    <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">消耗月</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">公式米数</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">− 排料米数</th>
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">= 省料米数</th>
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
                      <td className="px-4 py-2.5 text-neutral-700">{g.materialKey}</td>
                      <td className="px-4 py-2.5 text-neutral-800">{g.cohortLabel}</td>
                      <td className="px-4 py-2.5 text-neutral-600 whitespace-nowrap">{g.period}</td>
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
                    <td className="px-4 py-2.5 text-neutral-700" colSpan={3}>
                      合计（服务端给的合计腿）
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
      </Card>

      {/* ⑦ 在变好还是变坏：单位产出的面料消耗（采购/财务口径，不逐单） */}
      <Card>
        <div className="p-5" data-testid="saving-trend">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-medium text-neutral-900">
              在变好还是变坏 · 单位产出的面料消耗（每平方米成品用掉多少米布 · {granularity === 'week' ? '按 ISO 周' : '按月'}）
            </h2>
            <span className="text-xs text-neutral-500">时区 {trend?.timezone ?? '-'}</span>
          </div>
          <p data-testid="saving-trend-caveat" className="text-xs text-neutral-500 mb-2">
            {trendCaveat()}
          </p>
          {(comparisonPurchased || comparisonPerM2) && (
            <div className="mb-2 space-y-0.5 text-xs text-neutral-600">
              {comparisonPurchased && <div data-testid="saving-comparison-purchased">{comparisonPurchased}</div>}
              {comparisonPerM2 && <div data-testid="saving-comparison-per-m2">单位产出：{comparisonPerM2}</div>}
            </div>
          )}
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
                    <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">采购入库（不含存量导入）</th>
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

      {/* ⑧ 口径与边界（折叠）：把散落的口径说明集中收纳，一次说完 */}
      <details
        data-testid="saving-footnotes"
        className="rounded-lg border border-neutral-200 bg-white p-4 text-xs text-neutral-600"
      >
        <summary className="cursor-pointer text-sm font-medium text-neutral-800">口径与边界（点开看）</summary>
        <ul className="mt-2 list-disc pl-4 space-y-0.5">
          {footnotes(trend?.timezone).map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}
