'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
import {
  PROCESSING_ORDER_STATUS_LABELS,
  processingOrderStatusChipFor,
} from '@/lib/processing-order'
import { processingOrderApi, productionApi } from '@/lib/api'
import type { PieceworkSummary, ProcessingOrder, ProductionProgress } from '@/types'

/**
 * 生产看板 /production（issue #4203）——**加工单唯一入口**（issue #4357 合并）。
 *
 * 一屏回答「今天有多少加工单在产、各做到哪一道、各单计件多少钱」：
 * 加工单列表（复用 GET /api/admin/processing-orders）+ 每单工序进度与计件合计
 * （复用既有 per-order 端点 /production/orders/{orderId}/operations、/piecework，
 * 与生产明细页同一份口径，不新造聚合端点）。
 * 真值源：docs/curtain-production-rules.md §4 计件 / §5 扫码报工闭环。
 *
 * issue #4357：原「加工单」菜单项（订单管理组）与本页是**同一实体、同一端点**的两份渲染
 * ⇒ 合并为单一入口。原加工单列表页的能力**一条不丢**地并入本页：
 * 关键词/状态筛选、重置、商品与数量快照摘要、「查看」跳订单详情、加载失败重试与筛选空态；
 * 其请求时序保护（issue #4303）随搜索能力一并迁入（`reqSeq`）。
 * 旧路径 /processing-orders 保留为重定向（旧深链不 404）；子路由
 * /processing-orders/{id}/production（生产明细）**不变**。
 * #4305 的入口收敛不回归：本页**不渲染**发加工/开始加工/加工完成/取消四个按钮。
 */
interface BoardRow {
  po: ProcessingOrder
  progress?: ProductionProgress
  total?: number
}

interface SearchParams {
  keyword: string
  status: string
}

const EMPTY_SEARCH: SearchParams = { keyword: '', status: '' }

/** 状态下拉选项（含「全部」）——合并自加工单列表页 */
const STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '全部状态' },
  ...Object.entries(PROCESSING_ORDER_STATUS_LABELS).map(([value, label]) => ({ value, label })),
]

const EMPTY_PROGRESS: ProductionProgress = { total: 0, done: 0, percent: 0 }

function formatMoney(value?: number): string {
  return `¥${Number(value ?? 0).toFixed(2)}`
}

/** 商品与数量列：快照明细摘要（productName（颜色）× 数量单位），最多 2 行 + 溢出计数 */
function renderItemsSummary(po: ProcessingOrder): string[] {
  const lines = (po.items ?? []).map((it) => {
    const name = it.productName ?? ''
    const color = it.colorName ? `（${it.colorName}）` : ''
    const qty = it.quantity != null ? `× ${it.quantity}${it.unit ?? ''}` : ''
    return `${name}${color}${qty}`
  })
  return lines.filter(Boolean)
}

export default function ProductionBoardPage() {
  const router = useRouter()
  const [rows, setRows] = useState<BoardRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 筛选（合并自加工单列表页）：输入态与已提交态分离 —— 回车/点「查询」才发请求
  const [keywordInput, setKeywordInput] = useState('')
  const [statusInput, setStatusInput] = useState('')
  const [search, setSearch] = useState<SearchParams>(EMPTY_SEARCH)

  /** 列表请求序号（issue #4303）：只认最新一次请求的响应，旧的在飞响应一律丢弃 */
  const reqSeq = useRef(0)

  const load = useCallback(async () => {
    const seq = ++reqSeq.current
    setLoading(true)
    setError('')
    try {
      const res = await processingOrderApi.list({
        keyword: search.keyword || undefined,
        status: search.status || undefined,
      })
      // 时序保护（issue #4303）：旧响应晚到不得覆盖新数据，也不得由它收尾 loading
      if (seq !== reqSeq.current) return
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
      if (seq !== reqSeq.current) return
      setRows(
        details.map((d, i) => (d.status === 'fulfilled' ? d.value : { po: orders[i] })),
      )
    } catch (e) {
      if (seq !== reqSeq.current) return
      console.error(e)
      setRows([])
      setError('加载加工单失败，请稍后重试')
    } finally {
      if (seq === reqSeq.current) setLoading(false)
    }
  }, [search])

  useEffect(() => {
    load()
  }, [load])

  const handleSearch = () => {
    setSearch({ keyword: keywordInput.trim(), status: statusInput })
  }

  const handleReset = () => {
    setKeywordInput('')
    setStatusInput('')
    setSearch(EMPTY_SEARCH)
  }

  const filtered = !!(search.keyword || search.status)

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

      {/* 查询区域（issue #4357：合并自加工单列表页，能力原样保留） */}
      <div className="bg-white rounded-lg border border-neutral-200 p-5">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex items-center gap-2">
            <label className="text-sm text-neutral-600 whitespace-nowrap shrink-0 text-right min-w-[4.5em]">
              关键词
            </label>
            <input
              placeholder="请输入加工单号或订单号"
              value={keywordInput}
              onChange={(e) => setKeywordInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              className="flex-1 min-w-[220px] h-9 px-3 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm text-neutral-600 whitespace-nowrap shrink-0 text-right min-w-[4.5em]">
              状态
            </label>
            <select
              value={statusInput}
              onChange={(e) => setStatusInput(e.target.value)}
              className="min-w-[140px] h-9 px-3 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            >
              {STATUS_FILTER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={handleSearch} disabled={loading}>
              <Search className="w-4 h-4 mr-1.5" />
              查询
            </Button>
            <Button variant="secondary" size="sm" onClick={handleReset} disabled={loading}>
              重置
            </Button>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
              <th className="pl-5 pr-4 py-3 font-medium whitespace-nowrap">加工单号</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">订单号</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">客户</th>
              <th className="px-4 py-3 font-medium">商品与数量</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">状态</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">工序进度</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">计件合计</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-neutral-400" data-testid="production-board-loading">
                  加载中…
                </td>
              </tr>
            )}

            {!loading && error && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center" data-testid="production-board-error">
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
                <td colSpan={8} className="px-4 py-10 text-center text-neutral-400" data-testid="production-board-empty">
                  暂无加工单{filtered ? '（当前筛选条件下）' : ''}
                </td>
              </tr>
            )}

            {!loading &&
              !error &&
              rows.map(({ po, progress, total }) => {
                const chip = processingOrderStatusChipFor(po.status)
                const percent = Math.min(100, Math.max(0, Math.round(Number(progress?.percent ?? 0))))
                const p = progress ?? EMPTY_PROGRESS
                const summary = renderItemsSummary(po)
                return (
                  <tr
                    key={po.id}
                    className="border-b border-neutral-100 last:border-0 align-top transition-colors hover:bg-neutral-50/60"
                    data-testid={`production-row-${po.id}`}
                  >
                    <td className="pl-5 pr-4 py-4 whitespace-nowrap font-medium text-neutral-900">{po.processingOrderNo}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-neutral-600">{po.orderNo ?? '—'}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-neutral-900">{po.customerName ?? '—'}</td>
                    {/* 商品与数量：宽度必须收紧 —— 本列是 #4357 合并时新增的第 8 列，过宽会把
                        「操作」列挤出容器右缘（§15.3：vitest 看不见，几何探针实测溢出 100px、
                        末行「生产明细」按钮被裁）。收紧后 1440px 视口无横向溢出。 */}
                    <td className="px-4 py-4 min-w-[120px]">
                      {summary.length === 0 ? (
                        <span className="text-neutral-400">—</span>
                      ) : (
                        <div className="space-y-0.5 text-neutral-700">
                          {summary.slice(0, 2).map((line, i) => (
                            <div key={i} className="truncate max-w-[130px]">
                              {line}
                            </div>
                          ))}
                          {summary.length > 2 && (
                            <div className="text-xs text-neutral-400">+{summary.length - 2} 项</div>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <StatusBadge label={chip.label} color={chipToneClasses[chip.tone]} dot />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-16 overflow-hidden rounded-full bg-neutral-100">
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
                      <div className="flex flex-wrap items-center gap-2">
                        {/* 查看 → 订单详情（订单详情已含加工单块：快照 + 状态流转 + 打印） */}
                        <Button variant="secondary" size="sm" onClick={() => router.push(`/orders/${po.orderId}`)}>
                          查看
                        </Button>
                        {/* 生产明细（issue #4000）：工序进度 + 计件汇总 + 可打印任务卡（含二维码） */}
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => router.push(`/processing-orders/${po.processingOrderNo}/production`)}
                        >
                          生产明细
                        </Button>
                        {/* 状态流转入口收敛到订单详情页（issue #4305：用户裁定「从订单作为发加工的唯一入口」） */}
                        <span className="text-xs text-neutral-400">状态流转请在订单详情操作</span>
                      </div>
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
