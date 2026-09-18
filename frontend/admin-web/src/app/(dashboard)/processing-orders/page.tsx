'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { toastRequestError } from '@/lib/api-error'
import { Search, RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { processingOrderApi } from '@/lib/api'
import { Button } from '@/components/ui'
import StatusBadge from '@/components/ui/StatusBadge'
import DateTimeCell from '@/components/common/DateTimeCell'
import { chipToneClasses } from '@/lib/status-chip'
import {
  PROCESSING_ORDER_STATUS_LABELS,
  processingOrderStatusChipFor,
} from '@/lib/processing-order'
import type { ProcessingOrder } from '@/types'

/** 状态下拉选项（含「全部」） */
const STATUS_FILTER_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '全部状态' },
  ...Object.entries(PROCESSING_ORDER_STATUS_LABELS).map(([value, label]) => ({ value, label })),
]

interface SearchParams {
  keyword: string
  status: string
}

const EMPTY_SEARCH: SearchParams = { keyword: '', status: '' }

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

export default function ProcessingOrdersPage() {
  const router = useRouter()

  // 表单输入（未提交）
  const [keywordInput, setKeywordInput] = useState('')
  const [statusInput, setStatusInput] = useState('')
  // 实际提交的查询参数
  const [search, setSearch] = useState<SearchParams>(EMPTY_SEARCH)

  const [list, setList] = useState<ProcessingOrder[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  /** 列表请求序号（issue #4303）：只认最新一次请求的响应 */
  const listReqSeq = useRef(0)

  /** 加载列表（issue #4303：请求时序保护 —— 只认最新一次请求的响应）。 */
  const loadList = useCallback(
    async () => {
      // 请求时序保护（issue #4303）：只认最新一次请求的响应，旧的在飞响应一律丢弃
      // （实测：4174ms 才返回的旧 GET 落在 PATCH 之后，把新数据覆盖回旧值）
      const seq = ++listReqSeq.current
      setLoading(true)
      setLoadError('')
      try {
        const res = await processingOrderApi.list({
          keyword: search.keyword || undefined,
          status: search.status || undefined,
        })
        if (seq !== listReqSeq.current) return
        setList(res.data?.data ?? [])
      } catch (e) {
        if (seq !== listReqSeq.current) return
        console.error(e)
        setLoadError('加载加工单失败，请稍后重试')
        toastRequestError(e, '加载加工单失败')
      } finally {
        if (seq === listReqSeq.current) setLoading(false)
      }
    },
    [search]
  )

  useEffect(() => {
    loadList()
  }, [loadList])

  const handleSearch = () => {
    setSearch({ keyword: keywordInput.trim(), status: statusInput })
  }

  const handleReset = () => {
    setKeywordInput('')
    setStatusInput('')
    setSearch(EMPTY_SEARCH)
  }

  const handleView = (po: ProcessingOrder) => {
    // 订单详情页已含加工单块（状态机操作与打印），列表页只负责跳转
    router.push(`/orders/${po.orderId}`)
  }

  return (
    <div className="p-6 space-y-4">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-neutral-900">加工单列表</h1>
      </div>

      {/* 查询区域 */}
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
            <button
              type="button"
              onClick={handleSearch}
              disabled={loading}
              className="h-9 px-5 rounded bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 active:bg-primary-800 disabled:opacity-50 transition-colors inline-flex items-center gap-1.5"
            >
              <Search className="w-4 h-4" />
              查询
            </button>
            <button
              type="button"
              onClick={handleReset}
              disabled={loading}
              className="h-9 px-5 rounded bg-white text-neutral-700 text-sm font-medium border border-neutral-300 hover:bg-neutral-50 active:bg-neutral-100 disabled:opacity-50 transition-colors inline-flex items-center gap-1.5"
            >
              重置
            </button>
            <button
              type="button"
              onClick={() => loadList()}
              disabled={loading}
              title="刷新加工单列表"
              aria-label="刷新"
              className="h-9 px-3 rounded bg-white text-neutral-700 text-sm font-medium border border-neutral-300 hover:bg-neutral-50 active:bg-neutral-100 disabled:opacity-50 transition-colors inline-flex items-center gap-1.5"
            >
              <RefreshCw className="w-4 h-4" />
              刷新
            </button>
          </div>
        </div>
      </div>

      {/* 表格 */}
      <div className="bg-white rounded-lg border border-neutral-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200">
              <th className="pl-5 pr-4 py-3 font-medium whitespace-nowrap text-left">加工单号</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap text-left">订单号</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap text-left">客户</th>
              <th className="px-4 py-3 font-medium text-left">商品与数量</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap text-left">状态</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap text-left">创建时间</th>
              <th className="px-4 py-3 font-medium whitespace-nowrap text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-neutral-400">
                  加载中…
                </td>
              </tr>
            )}

            {!loading && loadError && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center">
                  <p className="text-red-500 mb-2">{loadError}</p>
                  <Button variant="secondary" size="sm" onClick={() => loadList()}>
                    重试
                  </Button>
                </td>
              </tr>
            )}

            {!loading && !loadError && list.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-neutral-400">
                  暂无加工单{search.keyword || search.status ? '（当前筛选条件下）' : ''}
                </td>
              </tr>
            )}

            {!loading &&
              !loadError &&
              list.map((po) => {
                const chip = processingOrderStatusChipFor(po.status)
                const summary = renderItemsSummary(po)
                return (
                  <tr key={po.id} className="border-b border-neutral-100 align-top transition-colors hover:bg-neutral-50/60">
                    <td className="pl-5 pr-4 py-4 whitespace-nowrap">
                      <span className="font-medium text-neutral-900">{po.processingOrderNo}</span>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-neutral-600">{po.orderNo ?? '—'}</td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <div className="text-neutral-900">{po.customerName ?? '—'}</div>
                      {po.customerPhone && <div className="text-xs text-neutral-400">{po.customerPhone}</div>}
                    </td>
                    <td className="px-4 py-4 min-w-[220px]">
                      {summary.length === 0 ? (
                        <span className="text-neutral-400">—</span>
                      ) : (
                        <div className="space-y-0.5 text-neutral-700">
                          {summary.slice(0, 2).map((line, i) => (
                            <div key={i} className="truncate max-w-[320px]">
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
                      <DateTimeCell value={po.generatedAt} />
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <div className="flex flex-wrap items-center gap-2">
                        <Button variant="secondary" size="sm" onClick={() => handleView(po)}>
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
