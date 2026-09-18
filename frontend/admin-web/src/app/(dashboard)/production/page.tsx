'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertCircle, RefreshCw, Search } from 'lucide-react'
import { Button, Pagination } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses } from '@/lib/status-chip'
import {
  PROCESSING_ORDER_STATUS_LABELS,
  processingOrderStatusChipFor,
} from '@/lib/processing-order'
import { processingOrderApi, productionApi } from '@/lib/api'
import type { PieceworkSummary, ProcessingOrder, ProductionProgress } from '@/types'

/**
 * 生产看板 /production（issue #4203；分页 + 懒加载 issue #4360；**加工单唯一入口** issue #4357）
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
 *
 * issue #4357：原「加工单」菜单项（订单管理组）与本页是**同一实体、同一端点**
 * （processingOrderApi.list）的两份渲染 ⇒ 合并为单一入口，本页即加工单唯一入口。
 * 原加工单列表页的能力**一条不丢**地并入本页：关键词/状态筛选、重置、商品与数量快照摘要、
 * 「查看」跳订单详情、筛选空态；其请求时序保护（issue #4303）随搜索能力一并迁入（`reqSeq`）。
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

/** 状态下拉选项（含「全部」）——合并自加工单列表页（issue #4357） */
const STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '全部状态' },
  ...Object.entries(PROCESSING_ORDER_STATUS_LABELS).map(([value, label]) => ({ value, label })),
]

const EMPTY_PROGRESS: ProductionProgress = { total: 0, done: 0, percent: 0 }
const PAGE_SIZE_OPTIONS = [20, 50, 100]

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
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])
  const [reloadKey, setReloadKey] = useState(0)
  // 已加载详情的行缓存（键 = processing order id）：切页回来命中缓存 ⇒ 零请求
  const detailCache = useRef(new Map<string, BoardRow>())

  // 筛选（合并自加工单列表页，issue #4357）：输入态与已提交态分离 —— 回车/点「查询」才发请求
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
      setRows((res.data?.data ?? []).map((po) => ({ po })))
      setPage(1)
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
        // ⚠️ 下面这个 `d.status === 'fulfilled'` 只是 **TS 类型收窄**（`allSettled` 返回联合类型，
        // 取 `d.value` 必须先收窄），**不是**「失败行不写缓存」的语义守卫：
        // 内层 `allSettled` 已经吞掉单行失败，上面的 async mapper **永不 reject**
        // ⇒ `details` 恒为 fulfilled ⇒ **两个接口都失败的行同样进缓存**（progress/total 为 undefined），
        // 该行保持「—」且**本会话不重试**；重试靠「刷新」（清缓存）或整页重载。
        //
        // 🔴 不要"照字面"改成「失败不写缓存」：那会让 `pending` **永不收敛**
        //    ⇒ 每次 `setRows(prev.map(...))` 都产生**新数组** ⇒ `rows` 身份变化
        //    ⇒ 本 effect（依赖 `[rows, page, pageSize, loading, error]`）被重新触发
        //    ⇒ **无限请求循环**。当前语义（失败也缓存）正是为避免它，已被
        //    `production-board.test.tsx` 的「失败行切页来回不重发」断言钉住（issue #4372）。
        if (d.status === 'fulfilled') {
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
        <Button variant="secondary" size="sm" onClick={refresh} disabled={loading}>
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
              aria-label="状态筛选"
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
              pageRows.map(({ po, progress, total }) => {
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
                        「操作」列挤出容器右缘（§15.3：vitest 看不见，几何探针实测 1440px 视口
                        横向溢出 100px、末行「生产明细」按钮被裁）。收紧后实测无横向溢出。 */}
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
                        {/* w-12（原 w-24，经 w-16 再收紧）：#4357 为容纳第 8 列而收窄。
                            ⚠️ 本表是**内容驱动**（`table-layout: auto`，与全仓其余 18 处密集表格
                            同一约定，不引入 `table-fixed`）⇒ 列宽随数据浮动。实测：3 行数据
                            （客户名 2 字）下 8 列合计 1100 = 容器宽（无横向滚动）；客户名 3~4 字时
                            曾溢出 12px —— 收窄进度条后复测为 0。数据再宽时容器横向滚动（by design），
                            「操作」列不会画在可视区外——这正是本节段要防的形态（§15.3 几何探针）。 */}
                        <div className="h-2 w-12 overflow-hidden rounded-full bg-neutral-100">
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
