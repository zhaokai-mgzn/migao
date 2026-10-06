'use client'

import { useCallback, useEffect, useState } from 'react'
import { ClipboardList, RefreshCw, Search, X } from 'lucide-react'
import { Button } from '@/components/ui'
import { productApi, stockLedgerApi } from '@/lib/api'
import { formatCost, formatDelta, formatQty, formatTime, reasonLabel } from '@/lib/stock-ledger'
import type { StockLedgerEntry } from '@/types'

/**
 * 库存明细 `/stock-ledger`（issue #6404）—— 大菜单「仓储与物料 ▸ 库存明细」的第一屏。
 *
 * ## 它是什么 / 不是什么
 *
 * ✅ **是**：SKU 级库存**变化流水**的读面（一行 = 一次变更，before → after 首尾相接可对账）。
 * ❌ **不是**批次余量（那在商品详情 → 批次账：`components/products/BatchStockPanel.tsx`），
 *    **不是**余料台账（那是裁下的小件：`/production/remnants`）。
 *    三者容易互相顶替着用，但对账场景（「为什么系统说还有 30 米、实际只剩 12 米」）
 *    **只有流水能回答**。
 *
 * ## 🔴 为什么这页必须有（而不是让米宝答就行）
 *
 * 后端端点（issue #4055）与 agent 工具（issue #5247）**早就有**，页面是 `StockLedgerController`
 * 的 javadoc 里逐字登记的**显式延后项**（「本轮只做只读端点，不做前端页面」）⇒
 * 后果是同一个问题 AI 答得出、商家在后台**点不出来**。
 *
 * ## 🔴 本页不判口径、不算数
 *
 * `delta` / `beforeQty` / `afterQty` / 金额一律**原样渲染服务端值**
 *（口径单一真值 = `StockLedgerController` 与 `StockLedger` 的 javadoc）；
 * 展示口径的纯函数在 `frontend/admin-web/src/lib/stock-ledger.ts`。
 *
 * ## 🔴 商品筛选为什么分两步
 *
 * `GET /api/admin/stock-ledger` **没有关键词参数**（`skuId` / `productId` / `refNo` 三个精确过滤）
 * ⇒ 传关键词会被服务端**静默丢弃** = 拿全量冒充过滤结果。所以商品侧必须先走**既有商品搜索**
 *（`productApi.getProducts`）拿到 `productId`，再按 id 查流水。
 *
 * ## 只读
 *
 * 本页**没有任何写操作**（库存流水的写入方在库存变更的既有实现点，不经过本页）。
 */
const PAGE_SIZE = 20

interface ProductOption {
  id: string
  name: string
}

export default function StockLedgerPage() {
  // ── 已生效的筛选（变它 ⇒ 重新取数）──
  const [product, setProduct] = useState<ProductOption | null>(null)
  const [appliedRefNo, setAppliedRefNo] = useState('')
  const [page, setPage] = useState(1)

  // ── 草稿态（用户正在敲，点「查询」才生效）──
  const [refNoInput, setRefNoInput] = useState('')

  // ── 商品搜索（两步走：先搜商品，再按 productId 查流水）──
  const [keyword, setKeyword] = useState('')
  const [options, setOptions] = useState<ProductOption[]>([])
  const [searching, setSearching] = useState(false)
  const [searchHint, setSearchHint] = useState('')

  const [rows, setRows] = useState<StockLedgerEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await stockLedgerApi.ledger({
        productId: product?.id,
        refNo: appliedRefNo.trim() || undefined,
        page,
        size: PAGE_SIZE,
      })
      const data = res.data?.data
      setRows(data?.items ?? [])
      setTotal(Number(data?.total ?? 0))
    } catch {
      setRows([])
      setTotal(0)
      setError('库存明细读取失败（可能是当前岗位没有「商品管理」权限）—— 请联系管理员开权限后重试')
    }
    setLoading(false)
  }, [product, appliedRefNo, page])

  useEffect(() => {
    void load()
  }, [load])

  const searchProducts = useCallback(async () => {
    const kw = keyword.trim()
    if (!kw) {
      setSearchHint('请先输入商品关键词（端点没有关键词参数，商品必须先选中才能按它查流水）')
      setOptions([])
      return
    }
    setSearching(true)
    setSearchHint('')
    try {
      const res = await productApi.getProducts({ keyword: kw, page: 1, size: 20 })
      const items = (res.data?.data?.items ?? []) as ProductOption[]
      setOptions(items)
      if (items.length === 0) setSearchHint('没有匹配的商品 —— 换个关键词试试')
    } catch {
      setOptions([])
      setSearchHint('商品搜索失败 —— 请稍后重试')
    }
    setSearching(false)
  }, [keyword])

  const pickProduct = useCallback((option: ProductOption) => {
    setProduct(option)
    setOptions([])
    setKeyword('')
    setSearchHint('')
    setPage(1)
  }, [])

  const clearProduct = useCallback(() => {
    setProduct(null)
    setPage(1)
  }, [])

  const applyQuery = useCallback(() => {
    setAppliedRefNo(refNoInput)
    setPage(1)
  }, [refNoInput])

  const reset = useCallback(() => {
    setRefNoInput('')
    setAppliedRefNo('')
    setProduct(null)
    setKeyword('')
    setOptions([])
    setSearchHint('')
    setPage(1)
  }, [])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div data-testid="stock-ledger-page" className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900 flex items-center gap-2">
            <ClipboardList className="w-5 h-5 text-primary-600" />
            库存明细
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            每一行 = 一次 SKU 级库存变更（变动前 → 变动后）；库存为什么从 X 变成 Y，靠这张表逐行回答。
          </p>
        </div>
        <Button variant="secondary" onClick={() => void load()} aria-label="刷新库存明细">
          <RefreshCw className="w-4 h-4 mr-1" />
          刷新
        </Button>
      </div>

      {/* 筛选：商品（两步走）+ 业务单据号 */}
      <div className="bg-neutral-50 rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="ledger-product" className="block text-xs text-neutral-500 mb-1">
              商品（按商品查某项货号的流水）
            </label>
            <div className="flex gap-2">
              <input
                id="ledger-product"
                aria-label="搜索商品"
                className="border border-neutral-300 rounded-md px-3 py-2 text-sm w-56"
                placeholder="商品标题关键词"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void searchProducts()
                }}
              />
              <Button variant="secondary" onClick={() => void searchProducts()} disabled={searching}>
                <Search className="w-4 h-4 mr-1" />
                搜索商品
              </Button>
            </div>
          </div>

          <div>
            <label htmlFor="ledger-refno" className="block text-xs text-neutral-500 mb-1">
              业务单据号（订单号 / 工单号 / 入库单号）
            </label>
            <input
              id="ledger-refno"
              aria-label="业务单据号"
              className="border border-neutral-300 rounded-md px-3 py-2 text-sm w-64"
              placeholder="如 RK-20261001-0001"
              value={refNoInput}
              onChange={(e) => setRefNoInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') applyQuery()
              }}
            />
          </div>

          <Button onClick={applyQuery}>查询</Button>
          <Button variant="secondary" onClick={reset}>
            重置
          </Button>
        </div>

        {/* 已选商品：显式可见 + 可清除（不然用户不知道当前过滤的是什么） */}
        {product && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-neutral-500">当前商品：</span>
            <span
              data-testid="selected-product"
              className="inline-flex items-center gap-1 rounded-md border border-primary-200 bg-primary-50 px-2 py-0.5 text-primary-700"
            >
              {product.name}
              <button type="button" aria-label="清除商品筛选" onClick={clearProduct}>
                <X className="w-3.5 h-3.5" />
              </button>
            </span>
          </div>
        )}

        {/* 商品候选：**必须点选**（端点没有关键词参数，绝不把关键词发下去） */}
        {options.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {options.map((o) => (
              <button
                key={o.id}
                type="button"
                data-testid="product-option"
                className="rounded-md border border-neutral-300 bg-white px-3 py-1 text-sm hover:border-primary-400"
                onClick={() => pickProduct(o)}
              >
                {o.name}
              </button>
            ))}
          </div>
        )}
        {searchHint && <p className="text-xs text-amber-600">{searchHint}</p>}
      </div>

      {error && (
        <div data-testid="stock-ledger-error" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* 流水表 */}
      <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-neutral-50 text-neutral-500">
            <tr>
              <th className="px-3 py-2 text-left font-medium whitespace-nowrap">时间</th>
              <th className="px-3 py-2 text-left font-medium whitespace-nowrap">货号 / SKU</th>
              <th className="px-3 py-2 text-right font-medium whitespace-nowrap">变动</th>
              <th className="px-3 py-2 text-right font-medium whitespace-nowrap">变动前</th>
              <th className="px-3 py-2 text-right font-medium whitespace-nowrap">变动后</th>
              <th className="px-3 py-2 text-left font-medium whitespace-nowrap">原因</th>
              <th className="px-3 py-2 text-left font-medium whitespace-nowrap">单据号</th>
              <th className="px-3 py-2 text-left font-medium whitespace-nowrap">操作人</th>
              <th className="px-3 py-2 text-right font-medium whitespace-nowrap">成本金额</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} data-testid="stock-ledger-row" className="border-t border-neutral-100">
                <td data-testid="ledger-time" className="px-3 py-2 whitespace-nowrap text-neutral-600">
                  {formatTime(r.createdAt)}
                </td>
                <td data-testid="ledger-sku" className="px-3 py-2 whitespace-nowrap">
                  {r.skuCode || '—'}
                </td>
                <td data-testid="ledger-delta" className="px-3 py-2 text-right tabular-nums font-medium">
                  {formatDelta(r.delta)}
                </td>
                <td data-testid="ledger-before" className="px-3 py-2 text-right tabular-nums text-neutral-600">
                  {formatQty(r.beforeQty)}
                </td>
                <td data-testid="ledger-after" className="px-3 py-2 text-right tabular-nums">
                  {formatQty(r.afterQty)}
                </td>
                <td data-testid="ledger-reason" className="px-3 py-2 whitespace-nowrap text-neutral-600">
                  {reasonLabel(r.reason)}
                </td>
                <td data-testid="ledger-refno" className="px-3 py-2 whitespace-nowrap text-neutral-600">
                  {r.refNo || '—'}
                </td>
                <td data-testid="ledger-operator" className="px-3 py-2 whitespace-nowrap text-neutral-600">
                  {r.operator || '—'}
                </td>
                {/* 🔴 NULL = 成本未知（不伪造 ¥0.00） */}
                <td data-testid="ledger-cost" className="px-3 py-2 text-right tabular-nums text-neutral-600">
                  {formatCost(r.costAmount)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {!loading && rows.length === 0 && !error && (
          <p className="px-4 py-8 text-center text-sm text-neutral-400">暂无库存流水</p>
        )}
        {loading && <p className="px-4 py-8 text-center text-sm text-neutral-400">库存明细加载中…</p>}
      </div>

      {/* 分页 */}
      <div className="flex items-center justify-between text-sm text-neutral-500">
        <span data-testid="ledger-total">共 {total} 条</span>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            aria-label="上一页"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </Button>
          <span>
            第 {page} / {totalPages} 页
          </span>
          <Button
            variant="secondary"
            aria-label="下一页"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </Button>
        </div>
      </div>
    </div>
  )
}
