'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
import { processingOrderStatusChipFor } from '@/lib/processing-order'
import { processingOrderApi, productionApi } from '@/lib/api'
import type { PieceworkSummary, ProcessingOrder, ProductionProgress } from '@/types'

/**
 * 生产看板 /production（issue #4203）
 *
 * 一屏回答「今天有多少加工单在产、各做到哪一道、各单计件多少钱」：
 * 加工单列表（复用 GET /api/admin/processing-orders）+ 每单工序进度与计件合计
 * （复用既有 per-order 端点 /production/orders/{orderId}/operations、/piecework，
 * 与生产明细页同一份口径，不新造聚合端点）。
 * 真值源：docs/curtain-production-rules.md §4 计件 / §5 扫码报工闭环。
 */
interface BoardRow {
  po: ProcessingOrder
  progress?: ProductionProgress
  total?: number
}

const EMPTY_PROGRESS: ProductionProgress = { total: 0, done: 0, percent: 0 }

function formatMoney(value?: number): string {
  return `¥${Number(value ?? 0).toFixed(2)}`
}

export default function ProductionBoardPage() {
  const router = useRouter()
  const [rows, setRows] = useState<BoardRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await processingOrderApi.list()
      const orders = res.data?.data ?? []
      setRows(orders.map((po) => ({ po })))
      // 每单的进度与计件互不依赖，也互不阻塞：单条失败只让该行显示「—」，不影响其它行
      const details = await Promise.allSettled(
        orders.map(async (po): Promise<BoardRow> => {
          const [opsRes, pieceRes] = await Promise.allSettled([
            productionApi.getOrderOperations(po.orderId),
            productionApi.getPiecework(po.orderId),
          ])
          return {
            po,
            progress: opsRes.status === 'fulfilled' ? opsRes.value.data?.data?.progress : undefined,
            total: pieceRes.status === 'fulfilled' ? (pieceRes.value.data?.data as PieceworkSummary | null)?.total : undefined,
          }
        }),
      )
      setRows(
        details.map((d, i) => (d.status === 'fulfilled' ? d.value : { po: orders[i] })),
      )
    } catch (e) {
      console.error(e)
      setRows([])
      setError('加载加工单失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">生产看板</h1>
          <p className="mt-0.5 text-sm text-neutral-500">加工单在产进度与计件合计</p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
              <th className="pl-5 pr-4 py-3 font-medium whitespace-nowrap">加工单号</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">订单号</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">客户</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">状态</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">工序进度</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">计件合计</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-neutral-400" data-testid="production-board-loading">
                  加载中…
                </td>
              </tr>
            )}

            {!loading && error && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center" data-testid="production-board-error">
                  <span className="mb-2 flex items-center justify-center gap-2 text-red-500">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                  </span>
                  <Button variant="secondary" size="sm" data-testid="production-board-retry" onClick={load}>
                    重试
                  </Button>
                </td>
              </tr>
            )}

            {!loading && !error && rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-neutral-400" data-testid="production-board-empty">
                  暂无加工单
                </td>
              </tr>
            )}

            {!loading &&
              !error &&
              rows.map(({ po, progress, total }) => {
                const chip = processingOrderStatusChipFor(po.status)
                const percent = Math.min(100, Math.max(0, Math.round(Number(progress?.percent ?? 0))))
                const p = progress ?? EMPTY_PROGRESS
                return (
                  <tr
                    key={po.id}
                    className="border-b border-neutral-100 last:border-0 transition-colors hover:bg-neutral-50/60"
                    data-testid={`production-row-${po.id}`}
                  >
                    <td className="pl-5 pr-4 py-4 whitespace-nowrap font-medium text-neutral-900">{po.processingOrderNo}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-neutral-600">{po.orderNo ?? '—'}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-neutral-900">{po.customerName ?? '—'}</td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <StatusBadge label={chip.label} color={chipToneClasses[chip.tone]} dot />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-24 overflow-hidden rounded-full bg-neutral-100">
                          <div className="h-full rounded-full bg-primary-600" style={{ width: `${percent}%` }} />
                        </div>
                        <span className="text-neutral-700" data-testid={`production-row-progress-${po.id}`}>
                          {percent}%（{p.done ?? 0}/{p.total ?? 0}）
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-neutral-900" data-testid={`production-row-piecework-${po.id}`}>
                      {formatMoney(total)}
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => router.push(`/processing-orders/${po.processingOrderNo}/production`)}
                      >
                        生产明细
                      </Button>
                    </td>
                  </tr>
                )
              })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
