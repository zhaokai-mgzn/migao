'use client'

import { useCallback, useMemo, useRef, useState } from 'react'
import { batchStockApi } from '@/lib/api'
import { formatStockQuantity } from '@/lib/stock-quantity'
import type { BatchRemaining, BatchStocktakeResult } from '@/types'

/**
 * 按批次库存盘点录入（V143 / issue #5865）——**最小录入式**：按货号列批次与当前余量 → 填实盘米数 →
 * **差异预览（± 与合计）** → 一次提交。
 *
 * 口径纪律（后端 `BatchStockViews` / `BatchStocktakeService` 的 javadoc 是单一真值，本组件只渲染与录值）：
 * - **余量是派生值**：盘前余量直接取 `remainingMeters`（入库量 + Σ分录 delta），页面**不重算**；
 * - **差异 = 实盘 − 余量**（正 = 盘盈、负 = 盘亏），按 0.1 米刻度做整数运算（避免 0.1+0.2 这类
 *   浮点误差把「没变」显示成 ±0.0000001）；提交后以**后端回执**为准（四数一起回）；
 * - **零差异不发请求**：实盘 == 余量 ⇒ 按钮禁用（后端也保证零写入）；
 * - **不静默取整**：只接受 0.1 米粒度、非负；输错就在行内说明并**拦住提交**，不四舍五入、不截断。
 *
 * `runId` 是幂等键：本组件在挂载时生成一次，**提交成功后换新值**（下一笔 = 新的一次盘点），
 * 提交失败则复用同一个值（重试不双记）。
 */
interface Props {
  productId: string
  batches: BatchRemaining[]
  /** 提交成功后回调（宿主组件据此刷新批次余量列表 —— 「差异已落账」必须看得见） */
  onApplied?: (result: BatchStocktakeResult) => void
}

/** 0.1 米刻度的整数（27 ⇒ 2.7 米）：预览与合计全程整数运算，不碰浮点 */
const tenths = (v: string | number) => Math.round(Number(v) * 10)

const meters = (t: number) => (t / 10).toFixed(1).replace(/\.0$/, '')

/** 实盘输入 → 0.1 米刻度整数；`null` = 解析不出/不合法（空串 = 还没填，单独区分） */
function parseActual(raw: string): number | null {
  const text = raw.trim()
  if (text === '') return null
  if (!/^\d+(\.\d)?$/.test(text)) return null
  const value = Number(text)
  if (!Number.isFinite(value)) return null
  return Math.round(value * 10)
}

function newRunId(): string {
  const rand = Math.random().toString(36).slice(2, 8)
  return `PD-${Date.now().toString(36)}-${rand}`
}

export default function BatchStocktakeForm({ productId, batches, onApplied }: Props) {
  const [actuals, setActuals] = useState<Record<number, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<BatchStocktakeResult | null>(null)
  const runIdRef = useRef<string>(newRunId())

  /** 逐行预览：`delta`（0.1 米刻度）与「输入非法」标记 */
  const rows = useMemo(() => batches.map((b) => {
    const raw = actuals[b.batchId] ?? ''
    const parsed = parseActual(raw)
    const invalid = raw.trim() !== '' && parsed === null
    const before = tenths(b.remainingMeters)
    return {
      batch: b,
      raw,
      invalid,
      before,
      actual: parsed,
      delta: parsed === null ? null : parsed - before,
    }
  }), [batches, actuals])

  const changed = rows.filter((r) => r.delta !== null && r.delta !== 0)
  const totalDelta = changed.reduce((sum, r) => sum + (r.delta ?? 0), 0)
  const hasInvalid = rows.some((r) => r.invalid)
  const canSubmit = !submitting && !hasInvalid && changed.length > 0

  const setActual = useCallback((batchId: number, value: string) => {
    setActuals((prev) => ({ ...prev, [batchId]: value }))
    setResult(null)
    setError(null)
  }, [])

  const submit = useCallback(async () => {
    if (changed.length === 0) return
    setSubmitting(true)
    setError(null)
    try {
      const res = await batchStockApi.stocktake({
        productId,
        runId: runIdRef.current,
        lines: changed.map((r) => ({ batchId: r.batch.batchId, actualMeters: (r.actual ?? 0) / 10 })),
      })
      const data = res.data?.data ?? null
      setResult(data)
      setActuals({})
      // 成功 ⇒ 换新 run id：下一次提交是**新的一次盘点**（幂等只覆盖同一次提交的重试）
      runIdRef.current = newRunId()
      if (data) onApplied?.(data)
    } catch (e) {
      // 失败**不换** run id（重试复用同一个键 ⇒ 不双记）；错误原文照实显示（后端 4xx 文案是可行动的）
      const message = (e as { response?: { data?: { message?: string } } })?.response?.data?.message
      setError(message || '盘点提交失败，请稍后重试（本次未写入）')
    } finally {
      setSubmitting(false)
    }
  }, [changed, onApplied, productId])

  return (
    <div className="mt-4 rounded-md border border-neutral-200 bg-white" data-testid="batch-stocktake">
      <div className="border-b border-neutral-100 px-3 py-2">
        <h3 className="text-sm font-semibold text-neutral-700">按批次盘点（实盘录入）</h3>
        <p className="mt-1 text-xs text-neutral-500">
          录「这一批现在实际还剩多少米」⇒ 差异 = 实盘 − 余量（正 = 盘盈、负 = 盘亏）。
          提交后：差异落一条盘点分录（入库量不动），SKU 库存按合计差异对齐 —— 两本账一起变，
          「这批为什么少了 1.5 米」在批次台账里查得到。实盘与余量相同 ⇒ 不写任何东西。
        </p>
      </div>

      {batches.length === 0 ? (
        <p className="px-3 py-3 text-xs text-neutral-400">暂无批次可盘（批次由入库单过账产生）</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm" data-testid="stocktake-table">
            <thead className="bg-neutral-50 text-neutral-600">
              <tr>
                <th className="px-3 py-2 text-left font-medium">批次号</th>
                <th className="px-3 py-2 text-left font-medium">货号</th>
                <th className="px-3 py-2 text-right font-medium">当前余量</th>
                <th className="px-3 py-2 text-right font-medium">实盘米数</th>
                <th className="px-3 py-2 text-right font-medium">差异</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100">
              {rows.map((r) => (
                <tr key={r.batch.batchId} className="text-neutral-900">
                  <td className="px-3 py-2 font-mono text-xs">{r.batch.batchNo}</td>
                  <td className="px-3 py-2 font-mono text-xs">{r.batch.skuCode || '-'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatStockQuantity(r.batch.remainingMeters)}</td>
                  <td className="px-3 py-2 text-right">
                    <input
                      type="number"
                      min={0}
                      step={0.1}
                      inputMode="decimal"
                      className="w-28 rounded-md border border-neutral-300 px-2 py-1 text-right tabular-nums focus:border-primary-500 focus:outline-none"
                      data-testid={`stocktake-input-${r.batch.batchId}`}
                      aria-label={`${r.batch.batchNo} 实盘米数`}
                      value={r.raw}
                      onChange={(e) => setActual(r.batch.batchId, e.target.value)}
                    />
                    {r.invalid && (
                      <p className="mt-1 text-xs text-red-600" data-testid={`stocktake-input-error-${r.batch.batchId}`}>
                        只能填 ≥0 且最多 1 位小数（0.1 米粒度，服务端不取整）
                      </p>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums" data-testid={`stocktake-diff-${r.batch.batchId}`}>
                    {r.delta === null ? '—' : (r.delta > 0 ? `+${meters(r.delta)}` : meters(r.delta))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-neutral-100 px-3 py-2">
        <p className="text-xs text-neutral-600">
          合计差异：
          <span className="mx-1 font-medium tabular-nums" data-testid="stocktake-total">
            {totalDelta > 0 ? `+${meters(totalDelta)}` : meters(totalDelta)}
          </span>
          米（{changed.length} 个批次会落账）
        </p>
        <button
          type="button"
          className="rounded-md bg-primary-600 px-3 py-1.5 text-sm text-white disabled:cursor-not-allowed disabled:bg-neutral-300"
          data-testid="stocktake-submit"
          disabled={!canSubmit}
          onClick={submit}
        >
          {submitting ? '提交中…' : '提交盘点'}
        </button>
      </div>

      {error && (
        <p className="border-t border-neutral-100 px-3 py-2 text-xs text-red-600" data-testid="stocktake-error">
          {error}
        </p>
      )}

      {result && (
        <div className="border-t border-neutral-100 px-3 py-2 text-xs text-neutral-600" data-testid="stocktake-result">
          上次提交：{result.changedCount} 个批次已落账（合计差异 {result.totalDelta} 米）
          {result.unchangedCount > 0 && `，${result.unchangedCount} 个与余量相同（未写入）`}
          {result.replayedCount > 0 && `，${result.replayedCount} 个本次已记过（跳过）`}
        </div>
      )}
    </div>
  )
}
