'use client'

import { useCallback, useEffect, useState } from 'react'
import { PageCard, PageHeader } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { loadErrorMessage } from '@/lib/api-error'
import { reportApi } from '@/lib/api'
import type {
  ReportInventoryAging,
  ReportOrderMargins,
  ReportQualityCost,
  ReportStaffPerformance,
} from '@/types/reports'

/** 金额展示：`null` ⇒ 「—」（**不是 ¥0.00**：空数据与零是两个结论）。 */
function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
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
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [m, i, s, q] = await Promise.all([
        reportApi.orderMargins(),
        reportApi.inventoryAging(),
        reportApi.staffPerformance(),
        reportApi.qualityCost(),
      ])
      setMargins(m.data.data || null)
      setInventory(i.data.data || null)
      setStaff(s.data.data || null)
      setQuality(q.data.data || null)
    } catch (error) {
      console.error('加载报表失败:', error)
      setLoadError(loadErrorMessage(error, '报表加载失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="p-6">
      <PageHeader
        title="报表中心"
        subtitle="毛利、滞销、业绩、质量成本 —— 合计与明细对得上，没数据时留空而不是写 0"
      />

      {loadError && <ListLoadError message={loadError} onRetry={load} testId="reports-load-error" />}

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <PageCard>
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-medium text-neutral-800">订单毛利</h2>
            <span className="text-xs text-neutral-500">收入 − 退款 − 面料 − 加工</span>
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
            <span className="text-xs text-neutral-500">
              满 {inventory?.slowMovingDays ?? 90} 天未出库
            </span>
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
            <span className="text-xs text-neutral-500">按制单人归集</span>
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
            <span className="text-xs text-neutral-500">返工 + 报废 + 赔付</span>
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
                  {quality.unknownComponents.join(' / ')}）
                </p>
              )}
            </div>
          )}
        </PageCard>
      </div>
    </div>
  )
}
