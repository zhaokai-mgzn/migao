'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Layers, RefreshCw, XCircle, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { poolBoardApi } from '@/lib/api'
import { Badge, Button, Card } from '@/components/ui'
import { cn } from '@/lib/utils'
import {
  batchGroups,
  buildPoolRequest,
  formatDeliveryDaysLeft,
  formatMeters,
  formatRequiredDeliveryDate,
  formatWaitHours,
  mustSurfaceDispatchError,
  previewSummaryRows,
} from '@/lib/pool-board'
import { isUrgentFlag, urgentBadgeText } from '@/lib/order-urgency'
import type { PoolBoard, PoolDispatchResult, PoolLine, PoolPreview } from '@/types'

/** 池化的等待阈值（小时）—— 传给服务端，服务端回显在 `maxWaitHours` */
const MAX_WAIT_HOURS = 24

/**
 * 池看板 `/production/pool`（issue #5177）—— 消费 #5169 已交付的三个端点：
 *
 * ```
 * GET  /api/admin/production/pool            读面（含加急插队区 + 物料分组）
 * POST /api/admin/production/pool/preview    成批预览（服务端算米数）
 * POST /api/admin/production/pool/dispatch   派单
 * ```
 *
 * ## 🔴 排序：服务端唯一口径，本页**一处都不重排**
 *
 * 服务端排序键 = 到货日升序（`null` 最后）→ `waitHours` 降序 → `waitingSince` 升序 → `orderId` 升序。
 * 「加急优先」是**结构性**的：整段 `urgentLines` 渲染在 `groups` 之前 —— 它不是排序键，
 * 前端也**不得**再加一个 `.sort()`（那是第二份会漂的口径，`migao-dev-flow` §15 点名的 bug 类）。
 *
 * ## 🔴 米数：全部原样渲染服务端值（**五个都是服务端聚合**）
 *
 * `formulaMeters` / `pooledPlannedMeters` / `savedMeters` / `perOrderPlannedMeters` /
 * `poolingGainMeters` 一个都不在浏览器里重算 —— 要求是「口径必须与落账逐值相等」。
 * ⚠️ `perOrderPlannedMeters` 是**一个数**（**逐单派**的应领**合计**，对照读数），
 * **不是** orderId → 米数 的映射 ⇒ 预览区**没有**逐单明细表（预览 API 不下发逐单明细）。
 *
 * ## 加急插队 = 同一个端点 + 单订单 + `pooled:false`（一个动作）
 *
 * 加急单**不进池**（不是成批候选）⇒ 混进 `pooled:true` 的批会被整批拒绝（422，不静默少派），
 * 该拒绝文案必须**看得见**（本页把它渲染在红色错误条里，不只靠一次 toast）。
 */
export default function ProductionPoolPage() {
  const [board, setBoard] = useState<PoolBoard | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [preview, setPreview] = useState<PoolPreview | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [results, setResults] = useState<PoolDispatchResult[] | null>(null)
  const [dispatchError, setDispatchError] = useState('')
  const [dispatching, setDispatching] = useState(false)
  /** 正在单派的订单 id（按钮级 loading，避免连点重复派单） */
  const [singlePending, setSinglePending] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await poolBoardApi.getBoard({ maxWaitHours: MAX_WAIT_HOURS })
      setBoard(res.data?.data ?? null)
    } catch (e) {
      toastRequestError(e, '加载池看板失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // 勾选订单 ⇒ 调 /preview（预览是「这批派下去会领多少料」的唯一真值来源）
  useEffect(() => {
    if (selectedIds.length === 0) {
      setPreview(null)
      setPreviewError('')
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const res = await poolBoardApi.preview(buildPoolRequest(selectedIds, true))
        if (cancelled) return
        setPreview(res.data?.data ?? null)
        setPreviewError('')
      } catch (e) {
        if (cancelled) return
        setPreview(null)
        setPreviewError(dispatchErrorText(e, '成批预览失败'))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedIds])

  const toggleOrder = (orderId: string) => {
    setSelectedIds((prev) =>
      prev.includes(orderId) ? prev.filter((id) => id !== orderId) : [...prev, orderId]
    )
  }

  const reloadAfterDispatch = async () => {
    setSelectedIds([])
    setPreview(null)
    await load()
  }

  /** 加急插队派单（单订单 + `pooled:false`）—— 一个动作，不批 */
  const dispatchSingle = async (line: PoolLine) => {
    setSinglePending(line.orderId)
    setDispatchError('')
    try {
      const res = await poolBoardApi.dispatch(buildPoolRequest([line.orderId], false))
      const rows = res.data?.data ?? []
      setResults(rows)
      const done = rows.find((r) => r.success)
      if (done) {
        // **结果可见**：toast 里带加工单号（不是只说一句「成功」）
        toast.success(`加急插队派单成功：${done.processingOrderNo ?? '-'}`)
        await reloadAfterDispatch()
      } else {
        toast.error(rows[0]?.message || '加急插队派单失败')
      }
    } catch (e) {
      const text = dispatchErrorText(e, '加急插队派单失败')
      setDispatchError(text)
      setResults(null)
      toastRequestError(e, text)
    } finally {
      setSinglePending(null)
    }
  }

  /** 一键成批派单（`pooled:true`）—— 加急单混进来会被**整批拒绝**（422） */
  const dispatchBatch = async () => {
    if (selectedIds.length === 0) return
    setDispatching(true)
    setDispatchError('')
    try {
      const res = await poolBoardApi.dispatch(buildPoolRequest(selectedIds, true))
      const rows = res.data?.data ?? []
      setResults(rows)
      const okCount = rows.filter((r) => r.success).length
      if (okCount > 0) {
        toast.success(`成批派单完成：${okCount} 单`)
        await reloadAfterDispatch()
      } else {
        toast.error('成批派单失败')
      }
    } catch (e) {
      // 加急单混进池化批 ⇒ 422 VALIDATION_ERROR（整批拒绝）—— 文案必须看得见
      const text = dispatchErrorText(e, '成批派单失败')
      setDispatchError(text)
      setResults(null)
      toastRequestError(e, text)
    } finally {
      setDispatching(false)
    }
  }

  const urgentLines = board?.urgentLines ?? []
  const groups = batchGroups(board)
  const warnings = board?.warnings ?? []

  /**
   * 订单 id → 单号（**纯展示映射**，只做「键 → 单号」，不重算任何业务数）。
   *
   * <p>🔴 必须**跨看板刷新累积**，不能每次渲染从当前看板派生：派单成功后那一单就**离开看板**了
   * （它已有加工单 ⇒ 不再进池），而派单**结果行**恰恰要显示「你刚派走的是哪一单」——
   * 从当前看板派生 ⇒ 那几行的单号正好查不到、回落成订单 id（实测被
   * `production-pool-urgent.test.tsx` 抓到：结果行渲染成 `u1`）。累积后刷新不会抹掉历史。</p>
   */
  const [orderNoById, setOrderNoById] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!board) return
    const lines = [...(board.urgentLines ?? []), ...(board.groups ?? []).flatMap((g) => g.lines ?? [])]
    setOrderNoById((prev) => {
      const next = { ...prev }
      let changed = false
      for (const l of lines) {
        if (next[l.orderId] !== l.orderNo) {
          next[l.orderId] = l.orderNo
          changed = true
        }
      }
      // 无变化 ⇒ 返回同一引用，避免无谓重渲染（本 effect 依赖 board，刷新频繁）
      return changed ? next : prev
    })
  }, [board])

  return (
    <div className="p-6 space-y-4">
      {/* 页头 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900 flex items-center gap-2">
            <Layers className="w-5 h-5 text-primary-600" />
            池看板
          </h1>
          <p className="text-sm text-neutral-500 mt-1">
            待派订单按物料（商品 × 颜色 × 门幅）成组 —— 同料合并领料以减少接头损耗；
            <strong>加急单不进池</strong>，要立刻单派
          </p>
        </div>
        <Button variant="secondary" onClick={() => void load()} loading={loading}>
          <RefreshCw className="w-4 h-4 mr-1.5" />
          刷新
        </Button>
      </div>

      {/* 顶部状态条：池化开关 / 最长等待 / 池内订单 / 加急 / 超时未派 */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 bg-white border border-neutral-200 rounded-lg p-3 text-sm">
        <span data-testid="pool-status-pooling" className="inline-flex items-center gap-2">
          <span className="text-neutral-500">池化开关</span>
          {board?.poolingEnabled ? (
            <Badge variant="success">已开启</Badge>
          ) : (
            <Badge variant="default">未开启</Badge>
          )}
        </span>
        <span data-testid="pool-status-max-wait" className="text-neutral-600">
          最长等待 <span className="font-mono text-neutral-900">{board?.maxWaitHours ?? MAX_WAIT_HOURS}</span> 小时
        </span>
        <span data-testid="pool-status-order-count" className="text-neutral-600">
          池内订单 <span className="font-mono text-neutral-900">{board?.orderCount ?? 0}</span> 单
        </span>
        <span data-testid="pool-status-line-count" className="text-neutral-600">
          明细 <span className="font-mono text-neutral-900">{board?.lineCount ?? 0}</span> 行
        </span>
        <span data-testid="pool-status-urgent-count" className="text-neutral-600">
          加急 <span className="font-mono text-neutral-900">{board?.urgentCount ?? 0}</span> 单
        </span>
        <span
          data-testid="pool-status-overdue-count"
          className={cn('font-medium', (board?.overdueCount ?? 0) > 0 ? 'text-red-600' : 'text-neutral-600')}
        >
          超时未派 <span className="font-mono">{board?.overdueCount ?? 0}</span> 单
        </span>
      </div>

      {/* 超时未派告警（overdueCount > 0 ⇒ 必须有可行动文案） */}
      {(board?.overdueCount ?? 0) > 0 && warnings.length > 0 && (
        <div
          data-testid="pool-warnings"
          className="bg-red-50 border border-red-200 rounded-lg p-3 space-y-1.5"
        >
          {warnings.map((w) => (
            <div
              key={w.orderId}
              data-testid={`pool-warning-${w.orderId}`}
              className="flex items-start gap-2 text-sm text-red-700"
            >
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>
                <span className="font-mono font-medium">{w.orderNo}</span>
                {' 已等待 '}
                <span className="font-mono">{formatWaitHours(w.waitHours)}</span>
                {' —— '}
                {w.message}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 全量请求失败（403 / 422 等）的文案（不只靠 toast） */}
      {mustSurfaceDispatchError(dispatchError) && (
        <div
          data-testid="pool-dispatch-error"
          className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700"
        >
          派单被拒绝：{dispatchError}
        </div>
      )}

      {loading && !board ? (
        <div className="bg-white border border-neutral-200 rounded-lg px-4 py-16 text-center text-neutral-400">
          加载中…
        </div>
      ) : (
        <>
          {/*
            ── 加急插队区 ──────────────────────────────────────────────────────────
            结构性优先：**整段**渲染在成批区之前（不是前端排序的结果）。
            这些单**不进池**（不是成批候选）⇒ 每行一个「加急插队派单」（单订单 + pooled:false）。
          */}
          <Card>
            <div className="p-5">
              <div className="flex items-center gap-2 mb-3">
                <Zap className="w-4 h-4 text-amber-600" />
                <h2 className="text-sm font-medium text-neutral-900">加急插队区</h2>
                <span className="text-xs text-neutral-500">
                  {urgentLines.length} 行 / {board?.urgentCount ?? 0} 单 —— 不进池，立即单派
                </span>
              </div>
              {urgentLines.length === 0 ? (
                <div className="px-4 py-8 text-center text-neutral-400 text-sm">当前没有加急待派订单</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" data-testid="pool-urgent-table">
                    <thead className="bg-neutral-50 text-neutral-600">
                      <tr>
                        <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">单号</th>
                        <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">物料（商品 × 颜色 × 门幅）</th>
                        <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">需求米数</th>
                        <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">等待时长</th>
                        <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">加急标记</th>
                        <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">到货日</th>
                        <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* ⚠️ 顺序 = 接口给的数组顺序，不重排 */}
                      {urgentLines.map((line) => (
                        <tr
                          key={`${line.orderId}-${line.itemId}`}
                          data-testid={`pool-line-${line.orderId}`}
                          className="border-t border-neutral-100 hover:bg-neutral-50"
                        >
                          <td className="px-4 py-2.5 font-mono text-neutral-900">{line.orderNo}</td>
                          <td className="px-4 py-2.5 text-neutral-700">
                            {line.productName}
                            <span className="text-neutral-400 ml-1.5">{line.skuCode || '-'}</span>
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-neutral-900">
                            {formatMeters(line.requiredMeters)}
                          </td>
                          <td className="px-4 py-2.5 text-right text-neutral-600">
                            {formatWaitHours(line.waitHours)}
                          </td>
                          <td className="px-4 py-2.5">
                            {isUrgentFlag(line) ? <Badge variant="warning">{urgentBadgeText(line)}</Badge> : (
                              <span className="text-xs text-neutral-400">{urgentBadgeText(line)}</span>
                            )}
                          </td>
                          <td
                            className={cn(
                              'px-4 py-2.5 whitespace-nowrap',
                              line.overdue ? 'text-red-600' : 'text-neutral-600'
                            )}
                          >
                            {formatRequiredDeliveryDate(line.requiredDeliveryDate)}
                            {line.requiredDeliveryDate && (
                              <span className="text-xs text-neutral-400 ml-1.5">
                                {formatDeliveryDaysLeft(line.deliveryDaysLeft)}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <Button
                              size="sm"
                              onClick={() => void dispatchSingle(line)}
                              loading={singlePending === line.orderId}
                              data-testid={`pool-dispatch-single-${line.orderId}`}
                            >
                              加急插队派单
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </Card>

          {/*
            ── 成批区 ─────────────────────────────────────────────────────────────
            按 `groups` 渲染物料分组（服务端已排好序）；组内 `lines` 同样按接口顺序。
          */}
          <Card>
            <div className="p-5" data-testid="pool-groups-section">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Layers className="w-4 h-4 text-primary-600" />
                  <h2 className="text-sm font-medium text-neutral-900">成批区（按物料分组）</h2>
                  <span className="text-xs text-neutral-500">
                    {groups.length} 个物料组 / 已选 {selectedIds.length} 单
                  </span>
                </div>
                <Button
                  onClick={() => void dispatchBatch()}
                  disabled={selectedIds.length === 0}
                  loading={dispatching}
                  data-testid="pool-dispatch-batch"
                >
                  一键成批派单
                </Button>
              </div>

              {groups.length === 0 ? (
                <div className="px-4 py-10 text-center text-neutral-400 text-sm">池内没有待派订单</div>
              ) : (
                <div className="space-y-4">
                  {groups.map((group, gi) => (
                    <div
                      key={group.materialKey}
                      data-testid={`pool-group-${gi}`}
                      className="border border-neutral-200 rounded-lg overflow-hidden"
                    >
                      <div className="flex items-center justify-between bg-neutral-50 px-4 py-2 text-sm">
                        <span className="font-medium text-neutral-800">{group.materialKey}</span>
                        <span className="text-neutral-500">
                          {group.orderCount} 单 / 需求 <span className="font-mono">{formatMeters(group.requiredMeters)}</span> 米
                        </span>
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead className="text-neutral-500">
                            <tr>
                              <th className="w-10 px-3 py-2" />
                              <th className="text-left px-3 py-2 font-medium whitespace-nowrap">单号</th>
                              <th className="text-left px-3 py-2 font-medium whitespace-nowrap">物料（商品 × 颜色 × 门幅）</th>
                              <th className="text-right px-3 py-2 font-medium whitespace-nowrap">需求米数</th>
                              <th className="text-right px-3 py-2 font-medium whitespace-nowrap">等待时长</th>
                              <th className="text-left px-3 py-2 font-medium whitespace-nowrap">加急标记</th>
                              <th className="text-left px-3 py-2 font-medium whitespace-nowrap">到货日</th>
                            </tr>
                          </thead>
                          <tbody>
                            {/* ⚠️ 顺序 = 接口给的数组顺序，不重排 */}
                            {group.lines.map((line) => (
                              <tr
                                key={`${line.orderId}-${line.itemId}`}
                                data-testid={`pool-line-${line.orderId}`}
                                className={cn(
                                  'border-t border-neutral-100',
                                  selectedIds.includes(line.orderId) ? 'bg-primary-50/40' : 'hover:bg-neutral-50'
                                )}
                              >
                                <td className="px-3 py-2">
                                  <input
                                    type="checkbox"
                                    aria-label={`选择订单 ${line.orderNo}`}
                                    checked={selectedIds.includes(line.orderId)}
                                    onChange={() => toggleOrder(line.orderId)}
                                    className="w-4 h-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500"
                                  />
                                </td>
                                <td className="px-3 py-2 font-mono text-neutral-900">{line.orderNo}</td>
                                <td className="px-3 py-2 text-neutral-700">
                                  {line.productName}
                                  <span className="text-neutral-400 ml-1.5">{line.skuCode || '-'}</span>
                                </td>
                                <td className="px-3 py-2 text-right font-mono text-neutral-900">
                                  {formatMeters(line.requiredMeters)}
                                </td>
                                <td className="px-3 py-2 text-right text-neutral-600">
                                  {formatWaitHours(line.waitHours)}
                                </td>
                                <td className="px-3 py-2">
                                  {isUrgentFlag(line) ? <Badge variant="warning">{urgentBadgeText(line)}</Badge> : (
                                    <span className="text-xs text-neutral-400">{urgentBadgeText(line)}</span>
                                  )}
                                </td>
                                <td
                                  className={cn(
                                    'px-3 py-2 whitespace-nowrap',
                                    line.overdue ? 'text-red-600' : 'text-neutral-600'
                                  )}
                                >
                                  {formatRequiredDeliveryDate(line.requiredDeliveryDate)}
                                  {line.requiredDeliveryDate && (
                                    <span className="text-xs text-neutral-400 ml-1.5">
                                      {formatDeliveryDaysLeft(line.deliveryDaysLeft)}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* 成批预览（勾选后自动调 /preview）：**服务端算**，前端只渲染 */}
              {selectedIds.length > 0 && (
                <div
                  data-testid="pool-preview"
                  className="mt-4 border border-primary-200 bg-primary-50/40 rounded-lg p-4"
                >
                  {previewError ? (
                    <p className="text-sm text-red-600" data-testid="pool-preview-error">
                      成批预览失败：{previewError}
                    </p>
                  ) : !preview ? (
                    <p className="text-sm text-neutral-400">正在预览…</p>
                  ) : (
                    <>
                      <div className="text-sm font-medium text-neutral-900 mb-2">
                        成批预览（{preview.orderCount} 单 · 指派规则 {preview.assignmentRule}）
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {previewSummaryRows(preview).map((row) => (
                          <div key={row.label} className="bg-white rounded border border-neutral-200 p-2.5">
                            <div className="text-xs text-neutral-500">{row.label}</div>
                            <div className="font-mono text-neutral-900 mt-0.5">{row.value} 米</div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </Card>
        </>
      )}

      {/* 派单逐单结果 —— **结果可见**：成功显示加工单号，失败显示 message */}
      {results && results.length > 0 && (
        <Card>
          <div className="p-5" data-testid="pool-dispatch-results">
            <h2 className="text-sm font-medium text-neutral-900 mb-3">派单结果</h2>
            <div className="space-y-2">
              {results.map((r) => (
                <div
                  key={r.orderRef}
                  data-testid={`pool-result-${r.orderRef}`}
                  className={cn(
                    'flex items-start gap-2 text-sm rounded border px-3 py-2',
                    r.success
                      ? 'bg-green-50 border-green-200 text-green-800'
                      : 'bg-red-50 border-red-200 text-red-700'
                  )}
                >
                  {r.success ? (
                    <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
                  ) : (
                    <XCircle className="w-4 h-4 mt-0.5 shrink-0" />
                  )}
                  <span>
                    <span className="font-mono font-medium">
                      {orderNoById[r.orderRef] ?? r.orderRef}
                    </span>
                    {r.success ? (
                      <>
                        {' 已派单，加工单号 '}
                        <span className="font-mono font-medium">{r.processingOrderNo ?? '-'}</span>
                      </>
                    ) : (
                      <>
                        {' 派单失败：'}
                        {r.message || '未知原因'}
                        {r.suggestion ? <span className="text-neutral-500">（{r.suggestion}）</span> : null}
                      </>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}

/**
 * 请求级失败的文案（拦截器已把服务端 message 装进 Error；这里再兜一层）。
 *
 * 🔴 与 `src/lib/pool-board.ts` 的 `mustSurfaceDispatchError` 是**同一格的另一半**：
 * 本函数负责「拿到文案」，那个函数负责「非空就必须上屏」。两者都不得被静默吞掉
 * （「整批显式拒绝，不静默少派」—— PR-080 判据 3）。
 */
function dispatchErrorText(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message) return e.message
  if (typeof e === 'string' && e) return e
  return fallback
}
