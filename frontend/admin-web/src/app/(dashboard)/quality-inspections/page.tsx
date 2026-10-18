'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { BadgeCheck, RefreshCw } from 'lucide-react'
import {
  Button,
  EmptyState,
  PageCard,
  PageHeader,
  Pagination,
  SearchPanel,
} from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import QualityCheckForm from '@/components/production/QualityCheckForm'
import QualityMetricsPanel from '@/components/production/QualityMetricsPanel'
import { qualityInspectionApi } from '@/lib/api'
import { usePermission } from '@/lib/permission'
import {
  formatMoment,
  qualityItemName,
  qualityResultLabel,
  qualityStateChipClass,
  qualityStateLabel,
} from '@/lib/quality-check'
import type {
  QualityInspectionRecord,
  QualityStats,
  QualityStatsWindow,
  QualityTarget,
  QualityTargetState,
} from '@/types'

/**
 * 质检记录 `/quality-inspections`（issue #7140 = #5652 的**商家面**）—— 大菜单「生产管理 ▸ 质检记录」。
 *
 * ## 这一页补的是什么缺口
 *
 * 质检的**载体**（`quality_inspections` 表 + 成品帘级三态判定 + 原因必填 + 独立质检员岗位）与
 * **工人端报工三态**早在 issue #5652 就落了，但 `frontend/admin-web` 里**一处消费都没有**
 * ⇒ 质检员登录观星台没有工作台、商家在任何页面都看不到质检读数（用户 2026-10-17 实测原话：
 * 「之前让你做过质检流程，我看在观星台上没有任何地方体现出来了」）。本页 + 作业单明细里的
 * 质检区 + 生产明细的「合格/返工/报废」三列，把这条链的两端接上。
 *
 * ## 两个面（同一页、同一权限码 `production:inspect`）
 *
 * ① **待检成品帘**：一条 = **一件成品帘**（与录入的颗粒度**同一份**）—— 加工单号 / 订单号 /
 *    成品帘 / 最新判定 + 「录入判定」；② **质检流水**：最近若干条记录（谁、何时、判了什么、为什么）。
 * 两个读面都来自 `QualityCheckController`，本页**不重算任何口径**（判定名、计数都取服务端值）。
 *
 * ## 🔴 未检 ≠ 合格
 *
 * 没有记录 ⇒ 「未检」（`pending`），不是「合格」，也不是「0 条」。读面失败时**不印计数**
 * （见下方 `countsReliable`）—— 拿 0 冒充「今天没有要检的」是同族实证过的事故形态（#6691 / #6703）。
 *
 * ## 边界（如实登记，`migao-dev-flow` §19.1）
 *
 * - **流水是客户端分页**（issue #7217）：记录读面（`GET /api/admin/quality-inspections`）只有加工单 /
 *   成品帘两个过滤，没有 `page`/`size` ⇒ 前端按页切分已读到的全量列表（页大小 10/20/50），
 *   不再硬截断到 20 条；重启条件 = 该读面加服务端分页（那时改成分页档，前端不再持全量）；
 * - **清单没有时间范围筛选**：清单读面没有时间入参，前端也不过滤（前端过滤 = 第二份口径）；
 *   指标面板的「今日 / 本周 / 本月 / 全部」是**服务端**按首检时刻算的窗口（issue #7192，
 *   见 `QualityMetricsPanel`）—— 两者的总体不同（队列 vs 周期读数），页面上各自标注，不混用；
 * - 判定录入后的**责任凭证不可改**：没有撤销入口（服务端也没有删除端点）。
 */
const PAGE_SIZE = 20
/** 流水每页条数（读面没有服务端分页 ⇒ 前端切页；issue #7217） */
const RECORDS_PAGE_SIZE = 10

/**
 * 指标时间窗 ⇒ 服务端入参（左闭右开 {@code [from, to)}）。
 *
 * 🔴 前端**只**把「今日 / 本周 / 本月 / 全部」翻成日期串；率的分子分母与分桶全在服务端算
 * （同一份口径）。`全部` ⇒ 不传窗口（服务端按数据范围给出趋势）。
 */
function statsWindowRange(window: QualityStatsWindow): { from?: string; to?: string } {
  if (window === 'all') return {}
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (window === 'week') {
    const offset = (start.getDay() + 6) % 7 // 周一 = 0
    start.setDate(start.getDate() - offset)
  } else if (window === 'month') {
    start.setDate(1)
  }
  const end = new Date(start)
  if (window === 'week') end.setDate(end.getDate() + 7)
  else if (window === 'month') end.setMonth(end.getMonth() + 1)
  else end.setDate(end.getDate() + 1)
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return { from: iso(start), to: iso(end) }
}

const STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '未检' },
  { value: 'pass', label: '合格' },
  { value: 'rework', label: '返工' },
  { value: 'scrap', label: '报废' },
]

const EMPTY_COUNTS: Record<QualityTargetState, number> = { pending: 0, pass: 0, rework: 0, scrap: 0 }

function readErrorCopy(subject: string): string {
  return `${subject}加载失败 —— 这不是「没有数据」，是这次没读到。请点「重新加载」再试一次。`
}

export default function QualityInspectionsPage() {
  const { has } = usePermission()
  const canOpenOrder = has('production:view')

  const [keyword, setKeyword] = useState('')
  const [appliedKeyword, setAppliedKeyword] = useState('')
  const [status, setStatus] = useState('all')
  const [appliedStatus, setAppliedStatus] = useState('all')
  const [page, setPage] = useState(1)

  const [targets, setTargets] = useState<QualityTarget[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Record<QualityTargetState, number>>(EMPTY_COUNTS)
  const [countsReliable, setCountsReliable] = useState(true)
  const [targetsLoading, setTargetsLoading] = useState(false)
  const [targetsError, setTargetsError] = useState('')

  const [records, setRecords] = useState<QualityInspectionRecord[]>([])
  const [recordsLoading, setRecordsLoading] = useState(false)
  const [recordsError, setRecordsError] = useState('')
  const [recordsPage, setRecordsPage] = useState(1)
  const [recordsPageSize, setRecordsPageSize] = useState(RECORDS_PAGE_SIZE)

  const [editing, setEditing] = useState<QualityTarget | null>(null)

  // 指标（P0+P1，issue #7192）：默认「本月」；时间窗与清单**互不影响**（清单是队列，指标是周期读数）
  const [statsWindow, setStatsWindow] = useState<QualityStatsWindow>('month')
  const [stats, setStats] = useState<QualityStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsError, setStatsError] = useState('')

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    setStatsError('')
    try {
      const res = await qualityInspectionApi.stats({
        ...statsWindowRange(statsWindow),
        bucket: statsWindow === 'all' ? 'month' : 'day',
      })
      setStats(res.data?.data ?? null)
    } catch {
      setStats(null)
      setStatsError('指标加载失败 —— 这不是「没有数据」，是这次没读到。请点「重新加载」再试一次。')
    }
    setStatsLoading(false)
  }, [statsWindow])

  useEffect(() => {
    void loadStats()
  }, [loadStats])

  const loadTargets = useCallback(async () => {
    setTargetsLoading(true)
    setTargetsError('')
    try {
      const res = await qualityInspectionApi.targets({
        keyword: appliedKeyword || undefined,
        status: appliedStatus,
        page,
        size: PAGE_SIZE,
      })
      const data = res.data?.data
      setTargets(data?.items ?? [])
      setTotal(data?.total ?? 0)
      setCounts(data?.counts ?? EMPTY_COUNTS)
      setCountsReliable(true)
    } catch {
      setTargets([])
      setCounts(EMPTY_COUNTS)
      // 读失败 ⇒ 计数位必须不可信（否则「未检 0 件」会被读成「今天没有要检的」）
      setCountsReliable(false)
      setTargetsError(readErrorCopy('待检成品帘'))
    }
    setTargetsLoading(false)
  }, [appliedKeyword, appliedStatus, page])

  const loadRecords = useCallback(async () => {
    setRecordsLoading(true)
    setRecordsError('')
    try {
      const res = await qualityInspectionApi.list()
      setRecords(res.data?.data ?? [])
      setRecordsPage(1)
    } catch {
      setRecords([])
      setRecordsError(readErrorCopy('质检流水'))
    }
    setRecordsLoading(false)
  }, [])

  useEffect(() => {
    void loadTargets()
  }, [loadTargets])

  useEffect(() => {
    void loadRecords()
  }, [loadRecords])

  const applyQuery = useCallback(() => {
    setAppliedKeyword(keyword.trim())
    setAppliedStatus(status)
    setPage(1)
  }, [keyword, status])

  const reset = useCallback(() => {
    setKeyword('')
    setAppliedKeyword('')
    setStatus('all')
    setAppliedStatus('all')
    setPage(1)
  }, [])

  const refresh = useCallback(() => {
    void loadTargets()
    void loadRecords()
    void loadStats()
  }, [loadTargets, loadRecords, loadStats])

  // 客户端分页（issue #7217）：读面一次返回全量（无 page/size）⇒ 前端切页，不再截断
  const pagedRecords = records.slice(
    (recordsPage - 1) * recordsPageSize,
    recordsPage * recordsPageSize,
  )

  return (
    <div data-testid="quality-inspections-page" className="space-y-4 p-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <BadgeCheck className="h-5 w-5 text-primary-600" />
            质检记录
          </span>
        }
        subtitle="按成品帘记录质检判定：谁检的、什么时候检的、判了合格 / 返工 / 报废，以及不合格的原因。报工记的是做了多少，这里判的是这一件能不能用。"
        actions={
          <Button variant="secondary" onClick={refresh} aria-label="刷新质检记录">
            <RefreshCw className="mr-1 h-4 w-4" />
            刷新
          </Button>
        }
      />

      {/* 常驻面 = **一行摘要**（不随条数增长）：读失败时这一行改为如实说「读不到」 */}
      <div className="text-sm text-neutral-600" data-testid="quality-state-summary">
        {countsReliable ? (
          <>
            未检 {counts.pending} 件 · 合格 {counts.pass} 件 · 返工 {counts.rework} 件 · 报废{' '}
            {counts.scrap} 件
          </>
        ) : (
          <>数量读不到 —— 见下方失败提示（这不是「一件都没有」）</>
        )}
      </div>

      <QualityMetricsPanel
        stats={stats}
        loading={statsLoading}
        error={statsError}
        window={statsWindow}
        onWindowChange={setStatsWindow}
        onRetry={() => void loadStats()}
      />

      <SearchPanel
        fields={[
          {
            key: 'keyword',
            label: '加工单号',
            control: (
              <input
                id="quality-keyword"
                aria-label="按加工单号查找"
                className="h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/15"
                placeholder="加工单号（可留空）"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') applyQuery()
                }}
              />
            ),
          },
          {
            key: 'status',
            label: '判定状态',
            control: (
              <select
                id="quality-status"
                aria-label="按判定状态筛选"
                className="h-9 w-full rounded border border-neutral-300 bg-white px-3 text-sm text-neutral-900 focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/15"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                {STATUS_FILTER_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ),
          },
        ]}
        onSearch={applyQuery}
        onReset={reset}
        onRefresh={refresh}
        loading={targetsLoading || recordsLoading}
      />

      <PageCard testId="quality-targets-card" padded={false}>
        <div className="flex items-baseline justify-between border-b border-neutral-100 px-5 py-3">
          <h2 className="text-base font-medium text-neutral-900">待检成品帘</h2>
          <span className="text-xs text-neutral-400">
            按成品帘逐件判定；返工后可以再检一次
          </span>
        </div>

        {targetsError && (
          <div className="p-4">
            <ListLoadError
              testId="quality-targets-load-error"
              message={targetsError}
              onRetry={() => void loadTargets()}
              retrying={targetsLoading}
            />
          </div>
        )}

        {!targetsError && targetsLoading && targets.length === 0 && (
          <p className="py-8 text-center text-sm text-neutral-400">加载中…</p>
        )}

        {!targetsError && !targetsLoading && targets.length === 0 && (
          <EmptyState
            testId="quality-targets-empty"
            icon="inbox"
            title="没有符合条件的成品帘"
            description="换个加工单号或判定状态试试；也可能确实没有在产的成品帘。"
          />
        )}

        {targets.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-xs text-neutral-500">
                <tr>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">加工单号</th>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">订单号</th>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">成品帘</th>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">最新判定</th>
                  <th className="px-4 py-2 text-right font-medium whitespace-nowrap sticky right-0 bg-neutral-50">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {targets.map((target) => {
                  const name = qualityItemName(target.product_name, target.color_name)
                  return (
                    <tr key={target.order_item_id} data-testid={`quality-target-${target.order_item_id}`}>
                      <td className="px-4 py-2 whitespace-nowrap text-neutral-900">
                        {target.processing_order_no && canOpenOrder ? (
                          <Link
                            className="text-primary-600 hover:text-primary-700"
                            href={`/processing-orders/${target.processing_order_no}/production`}
                          >
                            {target.processing_order_no}
                          </Link>
                        ) : (
                          target.processing_order_no || '—'
                        )}
                      </td>
                      <td className="px-4 py-2 whitespace-nowrap text-neutral-600">
                        {target.order_no || '—'}
                      </td>
                      <td className="px-4 py-2 text-neutral-900">{name}</td>
                      <td className="px-4 py-2">
                        <span
                          className={
                            'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ' +
                            qualityStateChipClass(target.state)
                          }
                          data-testid={`quality-target-state-${target.order_item_id}`}
                        >
                          {qualityStateLabel(target.state)}
                        </span>
                        {target.latest?.reason && (
                          <span className="ml-2 text-xs text-neutral-500">{target.latest.reason}</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button
                          type="button"
                          className="text-sm text-primary-600 hover:text-primary-700"
                          data-testid={`quality-target-record-${target.order_item_id}`}
                          onClick={() =>
                            setEditing(editing?.order_item_id === target.order_item_id ? null : target)
                          }
                        >
                          {target.state === 'pending' ? '录入判定' : '复检'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={total}
              onChange={setPage}
              totalReliable={!targetsError}
            />
          </div>
        )}

        {editing && (
          <QualityCheckForm
            orderItemId={editing.order_item_id}
            subject={qualityItemName(editing.product_name, editing.color_name)}
            onDone={() => {
              setEditing(null)
              void loadTargets()
              void loadRecords()
            }}
            onCancel={() => setEditing(null)}
          />
        )}
      </PageCard>

      <PageCard testId="quality-records-card" padded={false}>
        <div className="flex items-baseline justify-between border-b border-neutral-100 px-5 py-3">
          <h2 className="text-base font-medium text-neutral-900">质检流水</h2>
          <span className="text-xs text-neutral-400">按时间倒序</span>
        </div>

        {recordsError && (
          <div className="p-4">
            <ListLoadError
              testId="quality-records-load-error"
              message={recordsError}
              onRetry={() => void loadRecords()}
              retrying={recordsLoading}
            />
          </div>
        )}

        {!recordsError && !recordsLoading && pagedRecords.length === 0 && (
          <EmptyState
            testId="quality-records-empty"
            icon="file"
            title="还没有质检记录"
            description="在上面的待检清单里对某件成品帘录入判定后，这里会出现记录。"
          />
        )}

        {pagedRecords.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-xs text-neutral-500">
                <tr>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">检验时刻</th>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">成品帘</th>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">判定</th>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">不合格原因</th>
                  <th className="px-4 py-2 text-left font-medium whitespace-nowrap">检验人</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {pagedRecords.map((record) => (
                  <tr key={record.id} data-testid={`quality-record-row-${record.id}`}>
                    <td className="px-4 py-2 whitespace-nowrap text-neutral-600">
                      {formatMoment(record.inspected_at)}
                    </td>
                    <td className="px-4 py-2 text-neutral-900">{record.position_name || '—'}</td>
                    <td className="px-4 py-2">
                      <span
                        className={
                          'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ' +
                          qualityStateChipClass(record.result)
                        }
                      >
                        {qualityResultLabel(record.result, record.result_label)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-neutral-600">{record.reason || '—'}</td>
                    <td className="px-4 py-2 text-neutral-600">{record.inspector_name || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {records.length > 0 && (
          <Pagination
            current={recordsPage}
            pageSize={recordsPageSize}
            total={records.length}
            onChange={setRecordsPage}
            onPageSizeChange={(size) => {
              setRecordsPageSize(size)
              setRecordsPage(1)
            }}
            /* 读失败 / 读中 ⇒ 计数位印「—」，不把「读不到」印成「共 0 条」（issue #6703 同族） */
            totalReliable={!recordsLoading && !recordsError}
          />
        )}
      </PageCard>
    </div>
  )
}
