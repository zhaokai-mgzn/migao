'use client'

/**
 * 余料台账 /production/remnants（V122，issue #5146）—— 「企业参数中心 → 余料回收」域的**下钻页**。
 *
 * ## 它是什么 / 不是什么
 *
 * ✅ **是**：余料**台账的读面**（尺寸 / 面积 / 来源订单 / 来源批次 / 缸号 / 状态）+
 * **回收记账**与**报废留痕**的操作台 + 小件优先匹配的查询入口。
 * ❌ **不是**省料看板（那是 issue #5159 的在飞件），**不是**第二个配置入口
 * （小件用料尺寸表配在「参数总览 → 余料回收」域里，本页不提供第二处编辑）。
 *
 * ## 🔴 本页不判口径、不算钱
 *
 * 「装不装得下」「同缸号优先」「回收额 = 用掉米数 × 该批次当时均价」「未配置 ⇒ 不推荐」
 * 全在服务端（`RemnantService`）。本页只渲染服务端回的结论 ——
 * **包括「为什么没有建议」那段说明**（判据 4「未配置不静默」的用户可见面）。
 *
 * ## 边界（照实登记）
 *
 * - 匹配入口要求填**明细行 id**：余料匹配是**逐明细行**的事（小件需求来自该行勾的特殊选项）。
 *   派工页内嵌匹配**不在本单范围**（登记为边界，见 PR 报告）；
 * - 回收 / 报废的**权限**与算料配置同码（`processing:manage`）—— 无权限时读面会失败，
 *   页面按「权限拒绝是终态」给可行动话术（同族实证：issue #4103）。
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui'
import { remnantApi } from '@/lib/api'
import type { RemnantLedgerView, RemnantMatchView } from '@/types'

const STATUS_LABEL: Record<string, string> = {
  available: '可用',
  used: '已用',
  scrapped: '已报废',
  customer_taken: '客户带走',
}

const STATUS_CLASS: Record<string, string> = {
  available: 'bg-green-50 text-green-700 border-green-200',
  used: 'bg-primary-50 text-primary-700 border-primary-200',
  scrapped: 'bg-neutral-100 text-neutral-600 border-neutral-200',
  customer_taken: 'bg-amber-50 text-amber-700 border-amber-200',
}

const KIND_LABEL: Record<string, string> = { width: '门幅余料', end: '端部余料' }

function num(value?: number | null, digits = 2): string {
  return value === undefined || value === null ? '—' : Number(value).toFixed(digits)
}

function money(value?: number | null): string {
  return value === undefined || value === null ? '—' : `¥${Number(value).toFixed(2)}`
}

function time(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN')
}

export default function RemnantLedgerPage() {
  const [data, setData] = useState<RemnantLedgerView | null>(null)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionMsg, setActionMsg] = useState('')

  // 小件优先匹配（只读查询）：明细行 id + 可选的该行实际领料批次号
  const [orderItemId, setOrderItemId] = useState('')
  const [batchNo, setBatchNo] = useState('')
  const [match, setMatch] = useState<RemnantMatchView | null>(null)
  const [matchError, setMatchError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await remnantApi.ledger({ status: status || undefined, page: 1, size: 100 })
      setData(res.data?.data ?? null)
    } catch {
      setData(null)
      setError('余料台账读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试')
    }
    setLoading(false)
  }, [status])

  useEffect(() => {
    void load()
  }, [load])

  const runMatch = useCallback(async () => {
    setMatchError('')
    setMatch(null)
    if (!orderItemId.trim()) {
      setMatchError('请先填订单明细行 id（小件需求来自该行勾选的特殊选项）')
      return
    }
    try {
      const res = await remnantApi.match({
        orderItemId: orderItemId.trim(),
        batchNo: batchNo.trim() || undefined,
      })
      setMatch(res.data?.data ?? null)
    } catch {
      setMatchError('匹配查询失败 —— 请确认该明细行 id 属于本企业')
    }
  }, [orderItemId, batchNo])

  const recover = useCallback(
    async (remnantId: number, itemKey: string) => {
      setBusyId(remnantId)
      setActionMsg('')
      try {
        await remnantApi.recover(remnantId, {
          orderItemId: orderItemId.trim() || undefined,
          itemKey,
        })
        setActionMsg('已记回收 —— 该小件不新领料（不新增批次消耗），回收额冲减用它的那张单的面料成本')
        await load()
        await runMatch()
      } catch (e) {
        const detail = (e as { response?: { data?: { error?: { message?: string } } } })?.response?.data
          ?.error?.message
        setActionMsg(detail || '回收失败 —— 请刷新后重试')
      }
      setBusyId(null)
    },
    [orderItemId, load, runMatch]
  )

  const scrap = useCallback(
    async (remnantId: number) => {
      const reason = window.prompt('报废原因（报废要留痕：谁、何时、为什么）')
      if (!reason || !reason.trim()) return
      setBusyId(remnantId)
      setActionMsg('')
      try {
        await remnantApi.scrap(remnantId, reason.trim())
        setActionMsg('已报废并留痕（状态 / 原因 / 操作人 / 时刻都可查）')
        await load()
      } catch (e) {
        const detail = (e as { response?: { data?: { error?: { message?: string } } } })?.response?.data
          ?.error?.message
        setActionMsg(detail || '报废失败 —— 请刷新后重试')
      }
      setBusyId(null)
    },
    [load]
  )

  const summary = data?.summary
  const rows = data?.page?.items ?? []

  return (
    <div data-testid="remnant-ledger-page" className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-neutral-900">余料台账</h1>
          <p className="text-sm text-neutral-500 mt-1">
            裁剪剩下的布：尺寸、来源订单与批次、缸号、状态。
            <span className="ml-1 text-neutral-600">
              余料**不是资产** —— 只记实物可用性，不计价、不进库存金额。
            </span>
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={() => void load()}>
          <RefreshCw className="w-4 h-4 mr-1" />
          刷新
        </Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* ── 度量（分子分母都由服务端给；分母为零 ⇒ 比率是「—」而不是 0）── */}
      {summary && (
        <div data-testid="remnant-summary" className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: '可用', value: `${summary.availableCount}`, sub: `${num(summary.availableMeters)} 米` },
            { label: '已用', value: `${summary.usedCount}`, sub: `${num(summary.recoveredMetersTotal)} 米` },
            { label: '已报废', value: `${summary.scrappedCount}`, sub: `${num(summary.scrappedMetersTotal)} 米` },
            { label: '客户带走', value: `${summary.customerTakenCount}`, sub: '不进可用池' },
          ].map((cell) => (
            <div key={cell.label} className="bg-white border border-neutral-200 rounded-lg p-3">
              <div className="text-xs text-neutral-500">{cell.label}</div>
              <div className="text-base font-semibold text-neutral-900">{cell.value}</div>
              <div className="text-[11px] text-neutral-400">{cell.sub}</div>
            </div>
          ))}
          <div className="col-span-2 sm:col-span-4 text-xs text-neutral-600 bg-white border border-neutral-200 rounded-lg p-3">
            余料回收额合计 {money(summary.recoveredAmountTotal)}（冲减**用它的那些单**的面料成本，
            只进内部成本口径 —— 对客售价与加工费一字不动）；领料成本合计 {money(summary.issuedCostTotal)}；
            余料回收率 {summary.recoveryRate === null || summary.recoveryRate === undefined
              ? '—（还没有可算的数据）'
              : `${(Number(summary.recoveryRate) * 100).toFixed(2)}%`}
            ；报废率 {summary.scrapRate === null || summary.scrapRate === undefined
              ? '—（还没有可算的数据）'
              : `${(Number(summary.scrapRate) * 100).toFixed(2)}%`}
          </div>
        </div>
      )}

      {/* ── 小件优先匹配（只读查询 + 一键回收）── */}
      <div className="bg-white border border-neutral-200 rounded-lg p-4 space-y-3">
        <div className="text-sm font-medium text-neutral-900">小件优先匹配</div>
        <p className="text-xs text-neutral-500">
          填订单明细行 id：系统按该行勾选的特殊选项（余料做绑带 / 余料做帘头 / 抱枕 …）算出小件需求，
          再从**可用池**里挑装得下的余料（同缸号优先、其次同色）；找到就不新领料。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={orderItemId}
            aria-label="订单明细行 id"
            placeholder="订单明细行 id"
            onChange={(e) => setOrderItemId(e.target.value)}
            className="w-64 px-2 py-1 text-xs border border-neutral-300 rounded"
          />
          <input
            value={batchNo}
            aria-label="批次号"
            placeholder="批次号（可空，空了从批次台账反查）"
            onChange={(e) => setBatchNo(e.target.value)}
            className="w-64 px-2 py-1 text-xs border border-neutral-300 rounded"
          />
          <Button type="button" size="sm" onClick={() => void runMatch()}>
            <Search className="w-4 h-4 mr-1" />
            查匹配
          </Button>
        </div>
        {matchError && <p className="text-xs text-red-700">{matchError}</p>}
        {match && (
          <div data-testid="remnant-match-result" className="space-y-2">
            {/* 🔴 判据 4「未配置不静默」的用户可见面：说明**原样**来自服务端 */}
            {match.notice && (
              <div
                data-testid="remnant-match-notice"
                className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2"
              >
                {match.notice}
              </div>
            )}
            {match.recommendations.map((rec) => (
              <div
                key={`${rec.itemKey}-${rec.remnantId}`}
                data-testid={`remnant-rec-${rec.remnantId}`}
                className="border border-neutral-200 rounded p-3 text-xs space-y-1"
              >
                <div className="font-medium text-neutral-900">
                  {rec.itemKey}
                  <span className="ml-2 text-neutral-500">（勾选：{rec.optionNames.join(' / ')}）</span>
                </div>
                <div className="text-neutral-600">
                  余料 #{rec.remnantId} · {num(rec.remnantLengthM)} × {num(rec.remnantWidthM)} 米 ·
                  来自批次 {rec.sourceBatchNo} · 缸号 {rec.dyeLot || '—'}
                  {rec.sameDyeLot ? '（同缸号）' : '（同色不同缸号 —— 有色差风险）'}
                </div>
                <div className="text-neutral-600">
                  回收额预计 {money(rec.recoverableAmount)}（= {num(rec.recoverableMeters)} 米 ×
                  该批次均价 {rec.unitCost === null || rec.unitCost === undefined ? '—' : num(rec.unitCost, 4)}）
                </div>
                <Button
                  type="button"
                  size="sm"
                  disabled={busyId === rec.remnantId}
                  data-testid={`remnant-use-${rec.remnantId}`}
                  onClick={() => void recover(rec.remnantId, rec.itemKey)}
                >
                  用它做这个小件（记回收）
                </Button>
              </div>
            ))}
            {match.unmatched.map((u) => (
              <div
                key={u.itemKey}
                data-testid={`remnant-unmatched-${u.itemKey}`}
                className="text-xs text-neutral-600 border border-dashed border-neutral-300 rounded p-2"
              >
                {u.itemKey}：{u.reason}
              </div>
            ))}
          </div>
        )}
      </div>

      {actionMsg && (
        <div data-testid="remnant-action-msg" className="text-xs text-neutral-700 bg-neutral-50 border border-neutral-200 rounded p-2">
          {actionMsg}
        </div>
      )}

      <div className="flex items-center gap-2">
        <select
          value={status}
          aria-label="按状态筛选"
          onChange={(e) => setStatus(e.target.value)}
          className="px-2 py-1 text-xs border border-neutral-300 rounded"
        >
          <option value="">全部状态</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <span className="text-xs text-neutral-500">共 {data?.page?.total ?? 0} 块</span>
      </div>

      <div className="bg-white border border-neutral-200 rounded-lg overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-neutral-50 text-neutral-500">
            <tr>
              {['尺寸（长×宽）', '面积', '形态', '来源订单', '来源批次', '缸号', '状态', '回收 / 报废', '操作'].map(
                (h) => (
                  <th key={h} className="text-left font-medium px-3 py-2 whitespace-nowrap">
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-neutral-400">
                  读取中…
                </td>
              </tr>
            )}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={9} data-testid="remnant-empty" className="px-3 py-6 text-center text-neutral-400">
                  还没有余料记录（派工生成排料结果时会自动产生）
                </td>
              </tr>
            )}
            {!loading &&
              rows.map((row) => (
                <tr key={row.id} data-testid={`remnant-row-${row.id}`} className="border-t border-neutral-100">
                  <td className="px-3 py-2 whitespace-nowrap">
                    {num(row.lengthM)} × {num(row.widthM)} 米
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{num(row.areaM2)} ㎡</td>
                  <td className="px-3 py-2 whitespace-nowrap">{KIND_LABEL[row.pieceKind] ?? row.pieceKind}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{row.sourceOrderNo}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{row.sourceBatchNo}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{row.dyeLot || '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span
                      data-testid={`remnant-status-${row.id}`}
                      className={`px-1.5 py-0.5 rounded border ${STATUS_CLASS[row.status] ?? ''}`}
                    >
                      {STATUS_LABEL[row.status] ?? row.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {row.status === 'used' && (
                      <span data-testid={`remnant-recovered-${row.id}`} className="text-neutral-600">
                        {money(row.recoveredAmount)}（{num(row.recoveredMeters)} 米 × {num(row.recoveredUnitCost, 4)}）
                        → 冲减 {row.usedByOrderNo || '—'} / {row.usedByItemKey || '—'}
                        <span className="block text-neutral-400">
                          {row.recoveredBy || '—'} · {time(row.recoveredAt)}
                        </span>
                      </span>
                    )}
                    {row.status === 'scrapped' && (
                      <span data-testid={`remnant-scrap-${row.id}`} className="text-neutral-600">
                        {row.scrapReason}
                        <span className="block text-neutral-400">
                          {row.scrappedBy || '—'} · {time(row.scrappedAt)}
                        </span>
                      </span>
                    )}
                    {(row.status === 'available' || row.status === 'customer_taken') && '—'}
                  </td>
                  <td className="px-3 py-2">
                    {row.status === 'available' && (
                      <button
                        type="button"
                        data-testid={`remnant-scrap-btn-${row.id}`}
                        disabled={busyId === row.id}
                        onClick={() => void scrap(row.id)}
                        className="text-primary-700 hover:underline"
                      >
                        报废
                      </button>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
