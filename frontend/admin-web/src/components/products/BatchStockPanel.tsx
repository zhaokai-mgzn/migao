'use client'

import { useCallback, useEffect, useState } from 'react'
import { batchStockApi } from '@/lib/api'
import { formatStockQuantity } from '@/lib/stock-quantity'
import type { BatchDistribution, BatchReconcile, BatchRemaining } from '@/types'

/**
 * 批次账读面（V116 / issue #5145 阶段 1）——**只读**，挂在商品详情的库存区。
 *
 * 三个读面：① 批次余量（**派生** = 入库量 − 已派工消耗）；② 剩余量分布（恒四档）；
 * ③ 对账（`product_skus.stock` vs Σ批次余量）。
 *
 * 口径单一真值 = 后端 `BatchStockViews` 的 javadoc；本组件只渲染、不重算：
 * - 余量**不是**另立一份库存数，而是「这批还有多少」的派生值；
 * - 对账差额**不是异常**——它等于「已售未派 + 台账外存量」（台账外存量 = 本功能上线前就有的库存）。
 */
interface Props {
  productId: string
  /** 缺省 = 整商品的批次账；给 skuId 则只看该 SKU */
  skuId?: number
}

/** 单值展示：0 值也照实显示（缺档 = 数据缺失还是 0，不能靠猜） */
const meters = (v?: string | null) => formatStockQuantity(v ?? null)

export default function BatchStockPanel({ productId, skuId }: Props) {
  const [batches, setBatches] = useState<BatchRemaining[]>([])
  const [distribution, setDistribution] = useState<BatchDistribution | null>(null)
  const [reconcile, setReconcile] = useState<BatchReconcile | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const load = useCallback(async () => {
    if (!productId) return
    setLoading(true)
    setFailed(false)
    try {
      const params = { productId, skuId }
      const [b, d, r] = await Promise.all([
        batchStockApi.batches({ ...params, onlyAvailable: false }),
        batchStockApi.distribution({ productId }),
        batchStockApi.reconcile(params),
      ])
      setBatches(b.data?.data ?? [])
      setDistribution(d.data?.data ?? null)
      setReconcile(r.data?.data ?? null)
    } catch {
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }, [productId, skuId])

  useEffect(() => { load() }, [load])

  if (loading) return <div className="bg-neutral-50 rounded-lg p-4 text-sm text-neutral-400">批次账加载中…</div>
  if (failed) return <div className="bg-neutral-50 rounded-lg p-4 text-sm text-neutral-400">批次账加载失败</div>

  return (
    <div className="bg-neutral-50 rounded-lg p-4 space-y-4" data-testid="batch-stock-panel">
      {/* ① 批次余量（派生） */}
      <div>
        <h3 className="text-sm font-semibold text-neutral-700">批次余量</h3>
        <p className="mt-1 text-xs text-neutral-500">
          这是派生余量（入库量 − 已派工消耗）：入库时按批次记账，生成加工单指定批次时扣减、作废回补。
          它不另立一份库存数 —— 与 SKU 库存的差额见下方对账。
        </p>
        {batches.length === 0 ? (
          <p className="mt-2 text-xs text-neutral-400">暂无批次（批次由入库单过账产生）</p>
        ) : (
          <div className="mt-2 overflow-x-auto rounded-md border border-neutral-200 bg-white">
            <table className="min-w-full text-sm" data-testid="batch-remaining-table">
              <thead className="bg-neutral-50 text-neutral-600">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">批次号</th>
                  <th className="px-3 py-2 text-left font-medium">货号</th>
                  <th className="px-3 py-2 text-right font-medium">入库量</th>
                  <th className="px-3 py-2 text-right font-medium">已消耗</th>
                  <th className="px-3 py-2 text-right font-medium">余量</th>
                  <th className="px-3 py-2 text-left font-medium">收货日期</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {batches.map((b) => (
                  <tr key={b.batchId} className="text-neutral-900">
                    <td className="px-3 py-2 font-mono text-xs">{b.batchNo}</td>
                    <td className="px-3 py-2 font-mono text-xs">{b.skuCode || '-'}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{meters(b.inboundMeters)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{meters(b.consumedMeters)}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">{meters(b.remainingMeters)}</td>
                    <td className="px-3 py-2 text-xs text-neutral-500">{b.receivedDate || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ② 剩余量分布（恒四档） */}
      {distribution && (
        <div>
          <h3 className="text-sm font-semibold text-neutral-700">剩余量分布</h3>
          <p className="mt-1 text-xs text-neutral-500">
            按余量分四档（恒四档，余量为 0 的档也列出来）：共
            <span data-testid="distribution-total" className="mx-1 tabular-nums text-neutral-700">
              {distribution.totalBatches}
            </span>
            个批次。余量小的批次越多，说明越需要用得更干净。
          </p>
          <div className="mt-2 overflow-x-auto rounded-md border border-neutral-200 bg-white">
            <table className="min-w-full text-sm" data-testid="batch-distribution">
              <thead className="bg-neutral-50 text-neutral-600">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">档位</th>
                  <th className="px-3 py-2 text-right font-medium">批次数</th>
                  <th className="px-3 py-2 text-right font-medium">占比</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {distribution.buckets.map((b) => (
                  <tr key={b.key} className="text-neutral-900">
                    <td className="px-3 py-2">{b.label}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{b.batchCount}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatStockQuantity(b.share)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ③ 对账（差额可读出、可解释） */}
      {reconcile && (
        <div>
          <h3 className="text-sm font-semibold text-neutral-700">库存对账（SKU 库存 vs 批次余量）</h3>
          <p data-testid="reconcile-legend" className="mt-1 text-xs text-neutral-500">
            差额 = 已售未派（顾客已付款、销售账已扣，加工单还没派，实物账还没动）+ 台账外存量（本功能上线前
            就有的库存 / 建品时直接写的库存）。差额是口径差异，不是异常；只有差额无法由这两项解释时才需排查。
          </p>
          {reconcile.unreconciledCount > 0 && (
            <p className="mt-1 text-xs text-red-600" data-testid="reconcile-unbalanced">
              有 {reconcile.unreconciledCount} 个 SKU 的差额无法由「已售未派 + 台账外存量」解释，需排查
            </p>
          )}
          {reconcile.rows.length === 0 ? (
            <p className="mt-2 text-xs text-neutral-400">暂无与批次账相关的 SKU（从未入库过的 SKU 无批次来源）</p>
          ) : (
            <div className="mt-2 overflow-x-auto rounded-md border border-neutral-200 bg-white">
              <table className="min-w-full text-sm" data-testid="reconcile-table">
                <thead className="bg-neutral-50 text-neutral-600">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">货号</th>
                    <th className="px-3 py-2 text-right font-medium">SKU 库存</th>
                    <th className="px-3 py-2 text-right font-medium">批次余量</th>
                    <th className="px-3 py-2 text-right font-medium">差额</th>
                    <th className="px-3 py-2 text-right font-medium">已售扣减</th>
                    <th className="px-3 py-2 text-right font-medium">已派工扣减</th>
                    <th className="px-3 py-2 text-right font-medium">其它台账</th>
                    <th className="px-3 py-2 text-right font-medium">台账外存量</th>
                    <th className="px-3 py-2 text-left font-medium">恒等式</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100">
                  {reconcile.rows.map((r) => (
                    <tr key={r.skuId} className="text-neutral-900">
                      <td className="px-3 py-2 font-mono text-xs">{r.skuCode || r.skuId}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{meters(r.skuStock)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{meters(r.batchRemaining)}</td>
                      <td className="px-3 py-2 text-right tabular-nums font-medium">{meters(r.diff)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{meters(r.soldDeductedMeters)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{meters(r.dispatchedMeters)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{meters(r.otherLedgerDeltaMeters)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{meters(r.unbatchedMeters)}</td>
                      <td className="px-3 py-2 text-xs">
                        {r.reconciled ? (
                          <span className="text-green-600">差额可解释</span>
                        ) : (
                          <span className="font-medium text-red-600" data-testid={`reconcile-row-bad-${r.skuId}`}>
                            差额解释不通，需排查
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
