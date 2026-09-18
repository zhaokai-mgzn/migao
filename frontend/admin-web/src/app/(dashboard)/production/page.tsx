'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { Button, Pagination } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
import { processingOrderStatusChipFor } from '@/lib/processing-order'
import { processingOrderApi, productionApi } from '@/lib/api'
import type { PieceworkSummary, ProcessingOrder, ProductionProgress } from '@/types'

/**
 * 生产看板 /production（issue #4203；分页 + 懒加载 issue #4360）
 *
 * 一屏回答「今天有多少加工单在产、各做到哪一道、各单计件多少钱」：
 * 加工单列表（复用 GET /api/admin/processing-orders）+ 每单工序进度与计件合计
 * （复用既有 per-order 端点 /production/orders/{orderId}/operations、/piecework，
 * 与生产明细页同一份口径，不新造聚合端点）。
 *
 * 列表一次取回后在**前端分页**（默认 20 条/页），详情只对**当前页**懒加载并按
 * processing order id 缓存：切页回来不重复请求，「刷新」显式清缓存。
 * 原先对全部 100 行一次性扇出 ⇒ 1 + 2N 次 HTTP（100 单 = 201 请求）。
 *
 * ⚠️ **已知取舍（缓存带来的语义变化，issue #4360 显式登记）**：
 * 缓存把「每次进页都重取进度」变成「**进页命中缓存就不再取**」⇒ 车间报工后切页再切回，
 * 看到的是**本会话首次加载时的旧进度/旧计件**，需点「刷新」才更新。
 * 选它是因为用户裁定「切页回来不重复请求」；看板是**概览**（精确进度看生产明细页）。
 * 真值源：docs/curtain-production-rules.md §4 计件 / §5 扫码报工闭环。
 */
interface BoardRow {
  po: ProcessingOrder
  progress?: ProductionProgress
  total?: number
}

const EMPTY_PROGRESS: ProductionProgress = { total: 0, done: 0, percent: 0 }
const PAGE_SIZE_OPTIONS = [20, 50, 100]

function formatMoney(value?: number): string {
  return `¥${Number(value ?? 0).toFixed(2)}`
}

export default function ProductionBoardPage() {
  const router = useRouter()
  const [rows, setRows] = useState<BoardRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])
  const [reloadKey, setReloadKey] = useState(0)
  // 已加载详情的行缓存（键 = processing order id）：切页回来命中缓存 ⇒ 零请求
  const detailCache = useRef(new Map<string, BoardRow>())

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await processingOrderApi.list()
      setRows((res.data?.data ?? []).map((po) => ({ po })))
      setPage(1)
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
  }, [load, reloadKey])

  // 懒加载：只为**当前页**尚未缓存的行取详情（单行失败只让该行显示「—」，不影响其它行）
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const pageRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  useEffect(() => {
    if (loading || error) return
    const pending = pageRows.filter((r) => !detailCache.current.has(r.po.id))
    if (pending.length === 0) return
    let cancelled = false
    Promise.allSettled(
      pending.map(async (row): Promise<BoardRow> => {
        const [opsRes, pieceRes] = await Promise.allSettled([
          productionApi.getOrderOperations(row.po.orderId),
          productionApi.getPiecework(row.po.orderId),
        ])
        return {
          po: row.po,
          progress: opsRes.status === 'fulfilled' ? opsRes.value.data?.data?.progress : undefined,
          total: pieceRes.status === 'fulfilled' ? (pieceRes.value.data?.data as PieceworkSummary | null)?.total : undefined,
        }
      }),
    ).then((details) => {
      if (cancelled) return
      const loaded = new Map<string, BoardRow>()
      for (const d of details) {
        if (d.status === 'fulfilled') {
          // 单行失败不写缓存（下次进页可重试），该行保持「—」
          loaded.set(d.value.po.orderId, d.value)
          detailCache.current.set(d.value.po.id, d.value)
        }
      }
      setRows((prev) => prev.map((row) => loaded.get(row.po.orderId) ?? row))
    })
    return () => {
      cancelled = true
    }
    // pageRows 由 rows/page/pageSize 派生，故只需跟踪这三者
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, page, pageSize, loading, error])

  // 「刷新」= 清详情缓存 + 重取列表（load 内会把页码重置回第 1 页）
  const refresh = () => {
    detailCache.current.clear()
    setReloadKey((k) => k + 1)
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">生产看板</h1>
          <p className="mt-0.5 text-sm text-neutral-500">加工单在产进度与计件合计</p>
        </div>
        <Button variant="secondary" size="sm" onClick={refresh} disabled={loading}>
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
              pageRows.map(({ po, progress, total }) => {
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

      {!loading && !error && rows.length > 0 && (
        <div className="rounded-lg border border-neutral-200 bg-white">
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={rows.length}
            onChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size)
              setPage(1)
            }}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
          />
        </div>
      )}
    </div>
  )
}
