'use client'

import { useCallback, useEffect, useState } from 'react'
import { BadgeCheck, RefreshCw } from 'lucide-react'
import { Button, EmptyState, Loading, PageCard, PageHeader, Pagination } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import QualityMetricsPanel from '@/components/production/QualityMetricsPanel'
import { qualityInspectionApi } from '@/lib/api'
import { formatMoment, qualityResultLabel, qualityStateChipClass } from '@/lib/quality-check'
import type { QualityInspectionRecord, QualityStats, QualityStatsWindow } from '@/types'

/**
 * 质检记录 `/quality-inspections`（issue #7140 = #5652 的**商家面**）—— 大菜单「生产管理 ▸ 质检记录」。
 *
 * ## 2026-10-27 改判（issue #7945，用户逐字「质检单的这个区域都可以移除了，应该从手机端去判定」）
 *
 * 本页**不再**提供「待检成品帘 + 录入判定」：判定入口只在**工人端**（质检员扫码 → 做工判定）。
 * 本页只保留两个**读面**：① 质检指标（服务端算率）；② 质检流水（谁、何时、判了什么、为什么）。
 * 「待检」是派生读面（没有记录 = 未检），继续由 `/api/admin/quality-inspections/targets` 提供，
 * 供后续手机端队列复用；PC 不再渲染它 —— 两个端各录一半必然出现第二份口径。
 *
 * ## 口径（不重算）
 *
 * 判定名、计数、率全部取服务端值；本页只格式化。**未检 ≠ 合格**：读失败时不印「0 条」，
 * 如实说「读不到」（#6691 / #6703 同族）。
 *
 * ## 边界（如实登记，`migao-dev-flow` §19.1）
 *
 * - **流水是客户端分页**（issue #7217）：记录读面只有加工单 / 成品帘两个过滤，没有 `page`/`size`
 *   ⇒ 前端按页切分已读到的全量列表（页大小 10/20/50）；重启条件 = 该读面加服务端分页；
 * - 判定录入后的**责任凭证不可改**：没有撤销入口（服务端也没有删除端点）；
 * - 判定的**套号（件）**由手机端随扫码带上；PC 流水当前只显示成品帘名，套号列随后续演进再补。
 */
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

function readErrorCopy(subject: string): string {
  return `${subject}加载失败 —— 这不是「没有数据」，是这次没读到。请点「重新加载」再试一次。`
}

export default function QualityInspectionsPage() {
  const [records, setRecords] = useState<QualityInspectionRecord[]>([])
  const [recordsLoading, setRecordsLoading] = useState(false)
  const [recordsError, setRecordsError] = useState('')
  const [recordsPage, setRecordsPage] = useState(1)
  const [recordsPageSize, setRecordsPageSize] = useState(RECORDS_PAGE_SIZE)

  // 指标（P0+P1，issue #7192）：默认「本月」
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
    void loadRecords()
  }, [loadRecords])

  const refresh = useCallback(() => {
    void loadRecords()
    void loadStats()
  }, [loadRecords, loadStats])

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
        subtitle="质检判定由质检员在手机端扫码录入（做工问题）；这里看质检流水与合格率读数。报工记的是做了多少，这里判的是这一件的做工能不能过。"
        actions={
          <Button variant="secondary" onClick={refresh} aria-label="刷新质检记录">
            <RefreshCw className="mr-1 h-4 w-4" />
            刷新
          </Button>
        }
      />

      <QualityMetricsPanel
        stats={stats}
        loading={statsLoading}
        error={statsError}
        window={statsWindow}
        onWindowChange={setStatsWindow}
        onRetry={() => void loadStats()}
      />

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

        {/*
          issue #8041：读流水期间卡片体曾经是**完全空白**（四态契约 ① 加载中，见
          docs/design/design-baseline.md 的「四态契约」节）。用**既有** `Loading` 原语补占位；
          刷新时若已有流水（`pagedRecords.length > 0`）⇒ 表格照旧在场，不把它换成转圈。
        */}
        {!recordsError && recordsLoading && pagedRecords.length === 0 && (
          <div data-testid="quality-records-loading" className="p-4">
            <Loading size="sm" text="加载中…" />
          </div>
        )}

        {!recordsError && !recordsLoading && pagedRecords.length === 0 && (
          <EmptyState
            testId="quality-records-empty"
            icon="file"
            title="还没有质检记录"
            description="质检员在手机端扫码判定后，这里会出现记录。"
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

      <p className="text-xs text-neutral-400">
        判定入口只在手机端：质检员扫码进入这一件 →「做工有问题，记返工」。PC 不提供录入（避免同一条判定两个录入口）。
      </p>
    </div>
  )
}
