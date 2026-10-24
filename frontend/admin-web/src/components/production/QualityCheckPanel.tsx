'use client'

import { useCallback, useEffect, useState } from 'react'
import { BadgeCheck } from 'lucide-react'
import ListLoadError from '@/components/common/ListLoadError'
import QualityCheckForm from '@/components/production/QualityCheckForm'
import { qualityInspectionApi } from '@/lib/api'
import {
  formatMoment,
  latestByItem,
  qualityStateChipClass,
  qualityStateLabel,
} from '@/lib/quality-check'
import type { ProductionPosition, QualityInspectionRecord, QualityTargetState } from '@/types'

/**
 * 作业单生产明细里的**质检区**（issue #7140 = #5652 的商家面）。
 *
 * 一行 = **一件成品帘**（读面的「部位」块 = 一个 `order_item_id` = 商品行，与质检的颗粒度
 * **同一把尺子**）：最新判定 / 不合格原因 / 检验人 / 检验时刻 + 「录入判定」入口。
 *
 * ## 口径
 *
 * - 「最新判定」= 该成品帘在本单记录里的**第一条**（读面已按时间倒序 —— 排序口径在服务端，
 *   本组件只取第一条，见 `latestByItem`）；
 * - **未检 ≠ 合格**：没有记录 ⇒ 显示「未检」，不得显示「合格」（两句话语义不同）；
 * - 本组件**只在调用方已确认 `production:inspect`** 时渲染（判定是独立质检员岗位的动作，
 *   见 `QualityCheckController` 的权限声明）—— 本组件不自己判权限，避免两处口径。
 *
 * ## 为什么数据来自「记录读面」而不是清单读面
 *
 * 本区只关心**这一张单**：`GET /api/admin/quality-inspections?processing_order_id=…` 是为此设计的
 * 既有读面（服务端 javadoc 逐字说明「同一件成品帘允许多条（返工后重检）⇒ 读面把逐条给出，
 * 由前端取第一条」）。走清单读面会多一次全租户扫描，且拿到的是别单的数据。
 *
 * ## 边界（如实登记）
 *
 * - 只读**已录判定**：质检与报工是两套口径（报工 = 数量事实，质检 = 判定），本区不显示也不改写报工数量；
 * - 不提供「撤销判定」：判定是责任凭证（谁检的、何时检的），服务端读面也没有删除端点。
 */
interface QualityCheckPanelProps {
  processingOrderId: string
  /** 本单的成品帘（读面 `positions`）—— 缺 `order_item_id` 的存量行**不列出**（指不出是哪一件） */
  positions?: ProductionPosition[]
  className?: string
}

export default function QualityCheckPanel({
  processingOrderId,
  positions,
  className,
}: QualityCheckPanelProps) {
  const [records, setRecords] = useState<QualityInspectionRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!processingOrderId) return
    setLoading(true)
    setError('')
    try {
      const res = await qualityInspectionApi.list({ processingOrderId })
      setRecords(res.data?.data ?? [])
    } catch {
      setRecords([])
      setError('质检记录加载失败 —— 这不是「没有质检」，是这次没读到。请点「重新加载」再试一次。')
    }
    setLoading(false)
  }, [processingOrderId])

  useEffect(() => {
    void load()
  }, [load])

  const rows = (positions ?? []).filter((position) => Boolean(position.order_item_id))
  const latest = latestByItem(records)

  return (
    <div className={className} data-testid="quality-inspection-panel">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h2 className="flex items-center gap-2 text-base font-medium text-neutral-900">
          <BadgeCheck className="h-4 w-4 text-primary-600" />
          质检
        </h2>
        <span className="text-xs text-neutral-400">
          按成品帘记录：谁检的、什么时候检的、判了合格 / 返工 / 报废
        </span>
      </div>

      {error && (
        <ListLoadError
          testId="quality-inspection-load-error"
          message={error}
          onRetry={() => void load()}
          retrying={loading}
        />
      )}

      {!error && rows.length === 0 && (
        <p className="py-6 text-center text-sm text-neutral-400" data-testid="quality-inspection-empty">
          本单还没有可分部位质检的成品帘（成品帘按商品行区分）
        </p>
      )}

      {!error && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-neutral-200">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-xs text-neutral-500">
              <tr>
                <th className="px-3 py-2 text-left font-medium whitespace-nowrap">成品帘</th>
                <th className="px-3 py-2 text-left font-medium whitespace-nowrap">最新判定</th>
                <th className="px-3 py-2 text-left font-medium whitespace-nowrap">不合格原因</th>
                <th className="px-3 py-2 text-left font-medium whitespace-nowrap">检验人</th>
                <th className="px-3 py-2 text-left font-medium whitespace-nowrap">检验时刻</th>
                <th className="px-3 py-2 text-right font-medium whitespace-nowrap sticky right-0 bg-neutral-50">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {rows.map((position) => {
                const itemId = position.order_item_id as string
                const record = latest.get(itemId) ?? null
                const state: QualityTargetState = record ? record.result : 'pending'
                const name = position.product_name || position.position_name || ''
                return (
                  <tr key={itemId} data-testid={`quality-row-${itemId}`}>
                    <td className="px-3 py-2 text-neutral-900">{name || '—'}</td>
                    <td className="px-3 py-2">
                      <span
                        className={
                          'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ' +
                          qualityStateChipClass(state)
                        }
                        data-testid={`quality-state-${itemId}`}
                      >
                        {qualityStateLabel(state)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-neutral-600">{record?.reason || '—'}</td>
                    <td className="px-3 py-2 text-neutral-600">{record?.inspector_name || '—'}</td>
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-600">
                      {formatMoment(record?.inspected_at)}
                    </td>
                    <td className="px-3 py-2 text-right sticky right-0 bg-white">
                      <button
                        type="button"
                        className="text-sm text-primary-600 hover:text-primary-700"
                        data-testid={`quality-record-${itemId}`}
                        onClick={() => setEditing(editing === itemId ? null : itemId)}
                      >
                        {record ? '复检' : '录入判定'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 录入 = 弹窗（`QualityCheckForm` 内置 `Modal`；issue #7160：行内展开会撑高表格、且点击像没反应） */}
      {editing && (
        <QualityCheckForm
          orderItemId={editing}
          subject={
            rows.find((position) => position.order_item_id === editing)?.product_name ?? null
          }
          onDone={() => {
            setEditing(null)
            void load()
          }}
          onCancel={() => setEditing(null)}
        />
      )}

      {!error && rows.length > 0 && (
        <p className="mt-2 text-xs text-neutral-400">
          质检判定与报工数量是两本账：报工记的是做了多少，质检判的是这一件能不能用。
        </p>
      )}
    </div>
  )
}
