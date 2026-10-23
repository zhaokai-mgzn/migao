'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { PageCard, PageHeader } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { reportApi } from '@/lib/api'
import { downloadCsv, toCsv, type CsvCell } from '@/lib/csv'
import type {
  ReportInventoryAging,
  ReportOrderMargins,
  ReportQualityCost,
  ReportQualityCostBreakdown,
  ReportReceivableAging,
  ReportStaffPerformance,
} from '@/types/reports'

/** 金额展示：`null` ⇒ 「—」（**不是 ¥0.00**：空数据与零是两个结论）。 */
function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * 未知分项的**中文名**：拿 `components` 里同 code 的 label；查不到就退成「未采集项」——
 * 绝不把 `scrap_material` 这类内部码摆到商家面前（§31「不摆内部标识」）。
 */
function unknownLabels(quality: ReportQualityCost): string[] {
  return quality.unknownComponents.map(
    (code) => quality.components.find((c) => c.code === code)?.label ?? '未采集项',
  )
}

/**
 * 时间区间的**预设**（issue #7376 段 6）：本月 / 上月 / 近 90 天 / 全部。
 *
 * 🔴 只算**日期字符串**（`YYYY-MM-DD`），不碰时区：服务端把日期按业务时区（+08）解释，
 * 前端再换一次时区只会造出「月末少一天」这类错。`today` 可注入 ⇒ 判据能钉死结果。
 */
export function presetRange(
  preset: 'thisMonth' | 'lastMonth' | 'last90' | 'all',
  today: Date = new Date(),
): { from: string; to: string } {
  const pad = (n: number) => String(n).padStart(2, '0')
  const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  const y = today.getFullYear()
  const m = today.getMonth()
  if (preset === 'all') return { from: '', to: '' }
  if (preset === 'thisMonth') return { from: `${y}-${pad(m + 1)}-01`, to: fmt(today) }
  if (preset === 'lastMonth') {
    const first = new Date(y, m - 1, 1)
    const last = new Date(y, m, 0)
    return { from: fmt(first), to: fmt(last) }
  }
  const start = new Date(today)
  start.setDate(start.getDate() - 89)
  return { from: fmt(start), to: fmt(today) }
}

/** 「导出 CSV」小按钮：五张卡同一实现（`data-testid` 区分是第几张卡）。 */
function ExportButton({ testId, onClick }: { testId: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className="text-xs text-primary-600 hover:underline"
    >
      导出 CSV
    </button>
  )
}

function qty(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 米`
}

/**
 * 报表中心（issue #7376 / #7377）：四张只读报表。
 *
 * 🔴 三条展示纪律（与后端判据一一对应）：
 * 1. **「没有数据」不画成 0**：`hasData=false` / `totals=null` ⇒ 显示「暂无数据」，不显示 ¥0.00；
 * 2. **未知不填 0**：成本未知、未定价、未采集、未发生的分项显示「—」并说明原因；
 * 3. **合计不完整要标注**：质量成本 `complete=false` 时明写「这不是完整质量成本，还缺…」。
 */
export default function ReportsPage() {
  const [margins, setMargins] = useState<ReportOrderMargins | null>(null)
  const [inventory, setInventory] = useState<ReportInventoryAging | null>(null)
  const [staff, setStaff] = useState<ReportStaffPerformance | null>(null)
  const [quality, setQuality] = useState<ReportQualityCost | null>(null)
  const [aging, setAging] = useState<ReportReceivableAging | null>(null)
  // 质量成本的维度汇总（issue #7377 段 5）：默认按客户 —— 「贵在谁身上」比「贵在哪一步」更常问
  const [qcDim, setQcDim] = useState<'customer' | 'process'>('customer')
  const [qcBreakdown, setQcBreakdown] = useState<ReportQualityCostBreakdown | null>(null)
  const [qcBreakdownLoading, setQcBreakdownLoading] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  // 时间区间（issue #7376 段 6）：空串 = 该侧不设界；默认全部（不传参）
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const rangeParams = useMemo(
    () => ({ ...(from ? { startDate: from } : {}), ...(to ? { endDate: to } : {}) }),
    [from, to],
  )

  /**
   * 吃区间的三张表（毛利 / 业绩 / 质量成本）：换区间只重取这三张。
   *
   * 🔴 库存滞销与应收账龄是**此刻**读数（读面根本不收日期），换区间重取它们既是白跑，
   * 也会让商家以为「筛了 10 月，滞销数字该变」。
   */
  const loadDated = useCallback(async () => {
    const [m, s, q] = await Promise.all([
      reportApi.orderMargins(rangeParams),
      reportApi.staffPerformance(rangeParams),
      reportApi.qualityCost(rangeParams),
    ])
    setMargins(m.data.data || null)
    setStaff(s.data.data || null)
    setQuality(q.data.data || null)
  }, [rangeParams])

  /** 挂载与「失败重试」时把五张表都取一遍（重试要能救回任何一张）。 */
  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [m, i, s, q, a] = await Promise.all([
        reportApi.orderMargins(rangeParams),
        reportApi.inventoryAging(),
        reportApi.staffPerformance(rangeParams),
        reportApi.qualityCost(rangeParams),
        reportApi.receivableAging(),
      ])
      setMargins(m.data.data || null)
      setInventory(i.data.data || null)
      setStaff(s.data.data || null)
      setQuality(q.data.data || null)
      setAging(a.data.data || null)
    } catch (error) {
      console.error('加载报表失败:', error)
      setLoadError(loadErrorMessage(error, '报表加载失败'))
    } finally {
      setLoading(false)
    }
  }, [rangeParams])

  useEffect(() => {
    load()
    // ⚠️ 只在挂载时整页取一次；换区间走下面的 `loadDated`（见 `skipFirstRangeRun`）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 换区间：只重取吃区间的那三张（首次挂载已由上面的 `load()` 覆盖，跳过一跳）
  const skipFirstRangeRun = useRef(true)
  useEffect(() => {
    if (skipFirstRangeRun.current) {
      skipFirstRangeRun.current = false
      return
    }
    void loadDated().catch((error) => {
      console.error('加载报表失败:', error)
      setLoadError(loadErrorMessage(error, '报表加载失败'))
    })
  }, [loadDated])

  /**
   * 维度汇总单独取（不进 `load` 的 Promise.all）：切维度只该重取这一块，
   * 不该把另外五张表一起打一遍。
   */
  const loadBreakdown = useCallback(async (dim: 'customer' | 'process') => {
    setQcBreakdownLoading(true)
    try {
      const res = await reportApi.qualityCostBreakdown(dim, rangeParams)
      setQcBreakdown(res.data?.data || null)
    } catch (error) {
      console.error('加载质量成本维度失败:', error)
      setQcBreakdown(null)
    } finally {
      setQcBreakdownLoading(false)
    }
  }, [rangeParams])

  useEffect(() => {
    void loadBreakdown(qcDim)
  }, [loadBreakdown, qcDim])

  /**
   * 导出当前**已加载**的读数（不额外请求、不重算）：CSV 里的数与页面上的数必然同源。
   * 缺值留空（不是 0）；数值不加货币符号与千分位 —— 进 Excel 要能直接求和。
   */
  const exportCsv = useCallback((filename: string, headers: string[], rows: CsvCell[][]) => {
    downloadCsv(filename, toCsv(headers, rows))
  }, [])

  return (
    <div className="p-6">
      <PageHeader
        title="报表中心"
        subtitle="毛利、滞销、业绩、质量成本、应收账龄 —— 合计与明细对得上，没数据时留空而不是写 0"
      />

      {/*
        时间区间（issue #7376 段 6）：五张表不是同一条时间轴 —— 只给「按下单日 / 报工日」统计的三张表
        传区间，库存滞销与应收账龄是「此刻」读数。**这一点必须写在页面上**，否则商家会以为
        「我筛了 10 月，滞销数字怎么没变」。
      */}
      <PageCard className="mt-4">
        <div className="flex flex-wrap items-end gap-3" data-testid="reports-filter">
          <div>
            <label className="block text-xs text-neutral-500 mb-1" htmlFor="reports-filter-from">从</label>
            <input
              id="reports-filter-from"
              type="date"
              data-testid="reports-filter-from"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="border border-neutral-200 rounded px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-neutral-500 mb-1" htmlFor="reports-filter-to">到</label>
            <input
              id="reports-filter-to"
              type="date"
              data-testid="reports-filter-to"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="border border-neutral-200 rounded px-3 py-2 text-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            {([
              ['thisMonth', '本月', 'reports-filter-this-month'],
              ['lastMonth', '上月', 'reports-filter-last-month'],
              ['last90', '近 90 天', 'reports-filter-last90'],
              ['all', '全部', 'reports-filter-all'],
            ] as const).map(([preset, label, testId]) => (
              <button
                key={preset}
                type="button"
                data-testid={testId}
                onClick={() => {
                  const range = presetRange(preset)
                  setFrom(range.from)
                  setTo(range.to)
                }}
                className="text-xs px-2 py-1 rounded border border-neutral-200 text-neutral-600 hover:bg-neutral-50"
              >
                {label}
              </button>
            ))}
          </div>
          <p className="text-xs text-neutral-500" data-testid="reports-filter-note">
            区间只作用于「订单毛利 / 员工业绩（按下单日期）」与「质量成本（按返工报工日、退款发生日）」；
            库存滞销与应收账龄是「此刻」读数，不受区间影响。
          </p>
        </div>
      </PageCard>

      {loadError && <ListLoadError message={loadError} onRetry={load} testId="reports-load-error" />}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <PageCard>
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-medium text-neutral-800">订单毛利</h2>
            <div className="flex items-center gap-3">
              <span className="text-xs text-neutral-500">收入 − 退款 − 面料 − 加工</span>
              <ExportButton
                testId="reports-margin-export"
                onClick={() =>
                  exportCsv(
                    '订单毛利.csv',
                    ['指标', '金额'],
                    [
                      ['收入', margins?.totals?.revenue],
                      ['退款', margins?.totals?.refunded],
                      ['面料成本', margins?.totals?.fabricCost],
                      ['加工成本', margins?.totals?.laborCost],
                      ['毛利', margins?.totals?.grossMargin],
                    ],
                  )
                }
              />
            </div>
          </div>
          {loading ? (
            <p className="mt-3 text-sm text-neutral-500" data-testid="reports-margin-loading">加载中…</p>
          ) : !margins?.hasData ? (
            <p className="mt-3 text-sm text-neutral-500" data-testid="reports-margin-empty">
              暂无数据 —— 还没有已建单的订单
            </p>
          ) : (
            <div className="mt-3 space-y-2 text-sm" data-testid="reports-margin-body">
              <div className="flex justify-between">
                <span className="text-neutral-500">收入</span>
                <span data-testid="reports-margin-revenue">{money(margins.totals?.revenue)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">退款</span>
                <span>{money(margins.totals?.refunded)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">毛利</span>
                <span data-testid="reports-margin-gross">{money(margins.totals?.grossMargin)}</span>
              </div>
              {margins.unknownCostOrders > 0 && (
                <p className="text-xs text-amber-600" data-testid="reports-margin-unknown">
                  另有 {margins.unknownCostOrders} 单成本未知，未计入以上毛利（不是 0 元）
                </p>
              )}
            </div>
          )}
        </PageCard>

        <PageCard>
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-medium text-neutral-800">库存滞销</h2>
            <div className="flex items-center gap-3">
              <span className="text-xs text-neutral-500">
                满 {inventory?.slowMovingDays ?? 90} 天未出库
              </span>
              <ExportButton
                testId="reports-inventory-export"
                onClick={() =>
                  exportCsv(
                    '库存滞销.csv',
                    ['批次号', 'SKU', '仓库', '在库量', '最后变动日', '距今天数', '是否滞销'],
                    (inventory?.rows ?? []).map((row) => [
                      row.batchNo,
                      row.skuCode,
                      row.warehouse,
                      row.onHand,
                      row.lastMovementDate,
                      row.daysSinceMovement,
                      row.slowMoving ? '是' : '否',
                    ]),
                  )
                }
              />
            </div>
          </div>
          {loading ? (
            <p className="mt-3 text-sm text-neutral-500">加载中…</p>
          ) : !inventory?.hasData ? (
            <p className="mt-3 text-sm text-neutral-500" data-testid="reports-inventory-empty">
              暂无数据 —— 当前没有在库批次
            </p>
          ) : (
            <div className="mt-3 space-y-2 text-sm" data-testid="reports-inventory-body">
              <div className="flex justify-between">
                <span className="text-neutral-500">在库总量</span>
                <span data-testid="reports-inventory-onhand">{qty(inventory.totals?.onHand)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">其中滞销</span>
                <span data-testid="reports-inventory-slow">{qty(inventory.totals?.slowMovingOnHand)}</span>
              </div>
              <p className="text-xs text-neutral-500">
                滞销批次 {inventory.totals?.slowMovingBatches ?? 0} 个
                {inventory.undeterminedRows > 0 &&
                  `；另有 ${inventory.undeterminedRows} 个批次缺日期，未参与判定`}
              </p>
            </div>
          )}
        </PageCard>

        <PageCard>
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-medium text-neutral-800">员工业绩</h2>
            <div className="flex items-center gap-3">
              <span className="text-xs text-neutral-500">按制单人归集</span>
              <ExportButton
                testId="reports-staff-export"
                onClick={() =>
                  exportCsv(
                    '员工业绩.csv',
                    ['制单人', '单数', '收入', '客单价'],
                    (staff?.rows ?? []).map((row) => [
                      row.staffName || row.staffId,
                      row.orderCount,
                      row.revenue,
                      row.avgOrderValue,
                    ]),
                  )
                }
              />
            </div>
          </div>
          {loading ? (
            <p className="mt-3 text-sm text-neutral-500">加载中…</p>
          ) : !staff?.hasData ? (
            <p className="mt-3 text-sm text-neutral-500" data-testid="reports-staff-empty">
              暂无数据 —— 还没有带制单人的订单
            </p>
          ) : (
            <div className="mt-3 space-y-2 text-sm" data-testid="reports-staff-body">
              {staff.rows.slice(0, 5).map((row) => (
                <div key={row.staffId ?? row.staffName ?? 'unknown'} className="flex justify-between">
                  <span className="text-neutral-700">{row.staffName || row.staffId}</span>
                  <span>
                    {row.orderCount} 单 · {money(row.revenue)}
                    {row.avgOrderValue !== null && `（均 ${money(row.avgOrderValue)}）`}
                  </span>
                </div>
              ))}
              {staff.unattributedOrders > 0 && (
                <p className="text-xs text-neutral-500" data-testid="reports-staff-unattributed">
                  另有 {staff.unattributedOrders} 单没有制单人（不摊给任何人）
                </p>
              )}
            </div>
          )}
        </PageCard>

        <PageCard>
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-medium text-neutral-800">质量成本</h2>
            <div className="flex items-center gap-3">
              <span className="text-xs text-neutral-500">返工 + 报废 + 赔付</span>
              <ExportButton
                testId="reports-quality-export"
                onClick={() =>
                  exportCsv(
                    '质量成本.csv',
                    ['项目', '金额', '是否已采集', '说明'],
                    (quality?.components ?? []).map((component) => [
                      component.label,
                      component.known ? component.amount : null,
                      component.known ? '是' : '未采集',
                      component.note,
                    ]),
                  )
                }
              />
            </div>
          </div>
          {loading ? (
            <p className="mt-3 text-sm text-neutral-500">加载中…</p>
          ) : !quality || quality.components.length === 0 ? (
            <p className="mt-3 text-sm text-neutral-500" data-testid="reports-quality-empty">
              暂无数据
            </p>
          ) : (
            <div className="mt-3 space-y-2 text-sm" data-testid="reports-quality-body">
              {quality.components.map((component) => (
                <div key={component.code} className="flex justify-between gap-3">
                  <span className="text-neutral-500">{component.label}</span>
                  <span className={component.known ? '' : 'text-neutral-400'}>
                    {component.known ? money(component.amount) : '未采集 / 未知'}
                  </span>
                </div>
              ))}
              <div className="flex justify-between border-t border-neutral-100 pt-2">
                <span className="text-neutral-600">合计（可算部分）</span>
                <span data-testid="reports-quality-total">{money(quality.total)}</span>
              </div>
              {!quality.complete && (
                <p className="text-xs text-amber-600" data-testid="reports-quality-incomplete">
                  这不是完整质量成本：还缺 {quality.unknownComponents.length} 项（
                  {/* 用同一响应里的中文名，**不摆内部码**（`scrap_material` 这种商家读不懂，§31） */}
                  {unknownLabels(quality).join(' / ')}）
                </p>
              )}

            </div>
          )}
              {/*
                维度汇总（issue #7377 段 5）：回答「贵在谁身上 / 贵在哪一步」。
                🔴 「无法归属」必须单独露出来 —— 它是恒等式 `合计 = Σ行 + 无法归属` 的另一半，
                悄悄丢掉会让每一行看着都对、总额却对不上。
              */}
              <div className="mt-3 border-t border-neutral-100 pt-3" data-testid="reports-quality-breakdown">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-neutral-500">贵在哪：</span>
                    {(['customer', 'process'] as const).map((dim) => (
                      <button
                        key={dim}
                        type="button"
                        onClick={() => setQcDim(dim)}
                        data-testid={`reports-quality-dim-${dim}`}
                        className={`text-xs px-2 py-0.5 rounded-full border ${
                          qcDim === dim
                            ? 'border-primary-500 bg-primary-50 text-primary-700'
                            : 'border-neutral-200 text-neutral-600 hover:bg-neutral-50'
                        }`}
                      >
                        {dim === 'customer' ? '按客户' : '按工序'}
                      </button>
                    ))}
                  </div>
                  <ExportButton
                    testId="reports-quality-breakdown-export"
                    onClick={() =>
                      exportCsv(
                        `质量成本-${qcDim === 'customer' ? '按客户' : '按工序'}.csv`,
                        ['对象', '返工工时', '赔付', '合计', '返工行数', '退款笔数'],
                        (qcBreakdown?.rows ?? []).map((row) => [
                          row.label,
                          row.rework,
                          row.compensation,
                          row.total,
                          row.reworkLines,
                          row.compensationCount,
                        ]),
                      )
                    }
                  />
                </div>

                {qcBreakdownLoading ? (
                  <p className="mt-2 text-xs text-neutral-500" data-testid="reports-quality-breakdown-loading">
                    加载中…
                  </p>
                ) : !qcBreakdown?.hasData ? (
                  <p className="mt-2 text-xs text-neutral-500" data-testid="reports-quality-breakdown-empty">
                    暂无数据 —— 这个时间范围里没有返工报工或退款
                  </p>
                ) : (
                  <div className="mt-2 space-y-1">
                    {qcBreakdown.rows.slice(0, 5).map((row) => (
                      <div
                        key={row.key}
                        className="flex justify-between gap-3 text-xs"
                        data-testid="reports-quality-breakdown-row"
                      >
                        <span className="truncate text-neutral-700">{row.label}</span>
                        <span className="whitespace-nowrap text-neutral-600">
                          {money(row.total)}
                          <span className="ml-2 text-neutral-400">
                            返工 {money(row.rework)}
                            {row.compensationCount > 0 && ` · 赔付 ${money(row.compensation)}`}
                          </span>
                        </span>
                      </div>
                    ))}
                    {Number(qcBreakdown.unattributed?.total ?? 0) > 0 && (
                      <div
                        className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-700"
                        data-testid="reports-quality-breakdown-unattributed"
                      >
                        <div className="flex justify-between gap-3">
                          <span>无法归属</span>
                          <span className="whitespace-nowrap">{money(qcBreakdown.unattributed.total)}</span>
                        </div>
                        {/* 原因单独一行写全：塞进「对象」那一列的窄格里会被省略号切成半句话（实测截图） */}
                        <p className="mt-0.5 text-xs leading-snug text-amber-600">
                          {qcBreakdown.unattributed.reason}
                        </p>
                      </div>
                    )}
                    <p className="text-xs text-neutral-400" data-testid="reports-quality-breakdown-notes">
                      {(qcBreakdown.notes ?? []).join(' · ')}
                    </p>
                  </div>
                )}
              </div>
        </PageCard>

        <PageCard>
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-medium text-neutral-800">应收账龄</h2>
            <div className="flex items-center gap-3">
              <span className="text-xs text-neutral-500">按客户账期分档</span>
              <ExportButton
                testId="reports-aging-export"
                onClick={() =>
                  exportCsv(
                    `应收账龄-${aging?.asOf ?? ''}.csv`,
                    ['客户', '账期(天)', '应收', '逾期', '未到期', '逾期1-30', '逾期31-60', '逾期61-90', '逾期90+'],
                    (aging?.customers ?? []).map((customer) => [
                      customer.customerName,
                      customer.paymentTermsDays,
                      customer.total,
                      customer.overdue,
                      ...customer.buckets.map((bucket) => bucket.amount),
                    ]),
                  )
                }
              />
            </div>
          </div>
          {loading ? (
            <p className="mt-3 text-sm text-neutral-500" data-testid="reports-aging-loading">
              加载中…
            </p>
          ) : !aging?.hasData ? (
            <p className="mt-3 text-sm text-neutral-500" data-testid="reports-aging-empty">
              暂无数据 —— 没有未结清的应收
            </p>
          ) : (
            <div className="mt-3 space-y-2 text-sm" data-testid="reports-aging-body">
              <div className="flex justify-between">
                <span className="text-neutral-500">应收合计</span>
                <span data-testid="reports-aging-outstanding">{money(aging.totals?.outstanding)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">其中逾期</span>
                <span data-testid="reports-aging-overdue">{money(aging.totals?.overdue)}</span>
              </div>
              <p className="text-xs text-neutral-500" data-testid="reports-aging-counts">
                {aging.customerCount} 家客户 · {aging.totals?.orderCount ?? 0} 张单
                {aging.asOf ? ` · 截至 ${aging.asOf}` : ''}
              </p>
              {/* 五档是这张表的正文：合计只回答「欠多少」，分档才回答「欠了多久」 */}
              <div
                className="grid grid-cols-2 gap-x-4 gap-y-1 border-t border-neutral-100 pt-2 text-xs text-neutral-600"
                data-testid="reports-aging-buckets"
              >
                {aging.buckets.map((bucket) => (
                  <div
                    key={bucket.bucket}
                    className="flex justify-between gap-2"
                    data-testid={`reports-aging-bucket-${bucket.bucket}`}
                  >
                    <span className="text-neutral-500">{bucket.label}</span>
                    <span className="whitespace-nowrap">
                      {money(bucket.amount)}
                      {bucket.orderCount > 0 && ` · ${bucket.orderCount} 单`}
                    </span>
                  </div>
                ))}
              </div>
              <div className="space-y-1 border-t border-neutral-100 pt-2">
                {aging.customers.slice(0, 3).map((customer) => (
                  <div
                    key={`${customer.customerName ?? ''}-${customer.customerPhone ?? ''}`}
                    className="flex justify-between gap-3"
                    data-testid="reports-aging-customer"
                  >
                    <span className="truncate text-neutral-700">{customer.customerName || '（未留名）'}</span>
                    <span className="whitespace-nowrap">
                      {money(customer.total)}
                      {Number(customer.overdue ?? 0) > 0 && (
                        <span className="ml-2 text-amber-600">逾期 {money(customer.overdue)}</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </PageCard>
      </div>
    </div>
  )
}
