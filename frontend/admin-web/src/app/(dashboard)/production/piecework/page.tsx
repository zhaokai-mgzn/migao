'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, Check, RefreshCw, Search, X } from 'lucide-react'
import { Button, PageHeader, SELECT_CONTROL } from '@/components/ui'
import { productionApi } from '@/lib/api'
import { isAxiosError } from 'axios'
// 工序显示名的**唯一**口径（issue #4621）：逻辑名 · 部位 —— 本页**不得**直接渲染变体名
import { operationDisplayName } from '@/lib/operation-display'
import UnpricedNotice from '@/components/production/UnpricedNotice'
import { cn } from '@/lib/utils'
// 🔴 issue #6669 第 7 条：涉钱读数的**唯一**展示口径（千分位 + 固定两位小数）——
// 修前本页是 `toFixed(2)`（`¥123456.78`，无千分位），财务域是 `toLocaleString('zh-CN')`
// （`¥123,456.78`）⇒ 同一笔钱两页长得不一样。现两页共用 `@/lib/money` 一处真值。
import { money } from '@/lib/money'
import type { ApiResponse, PieceworkReport, PieceworkSettlement, PieceworkSettlementList } from '@/types'

/**
 * 计件工资 /production/piecework（issue #4205 前端半边）
 *
 * 数据源：GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]
 * —— 报工事件聚合（按人 / 按工序 / **按部位** / **按套** 四档；下钻维度由后端同一份聚合产出）。
 * 口径与生产明细页的 per-order 汇总**同一份逻辑**（后端同一聚合，前端不重算）。
 * 真值源：docs/curtain-production-rules.md §4「工资报表 = 报工事件聚合（按人/按期/按单下钻）」。
 * 返工/报废不计件由后端聚合时排除，本页只做展示。
 */
/**
 * 默认期间 = **本地月**（issue #4772）。
 *
 * ⚠️ 不得写成 `new Date().toISOString().slice(0, 7)`（**UTC** 月）：在 UTC+8 的
 * 每月 1 日 00:00~08:00（CST）这 8 小时里 UTC 月 = 上一个月 ⇒ 页面默认查上一个月。
 * 口径证据（三条，来自 #4761 核清）：① 后端 `ProductionService.pieceworkSummary` 按
 * `work_date`（`LocalDate`，**无时区**）∈ `[atDay(1), atEndOfMonth()]` 过滤；
 * ② 后端 `application.yml` 的 `spring.jackson.time-zone: Asia/Shanghai`；
 * ③ 同域财务页 `getCurrentPeriod()` 用 `getFullYear()/getMonth()`（本地月）。
 */
function currentPeriod(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

// 缺失值 ⇒ `¥0.00`（本页是**报表读数**：合计为 0 与「没有数据」由空态分开表达，
// 见本页 `isEmpty` —— 故这里不为缺失值改印藏头，只是不许出现两份格式实现）。
function formatMoney(value?: number): string {
  return money(value ?? 0)
}

function formatQty(value?: number): string {
  return String(Number(value ?? 0))
}

export default function PieceworkReportPage() {
  const [period, setPeriod] = useState(currentPeriod)
  const [workerName, setWorkerName] = useState('')
  const [tab, setTab] = useState<'worker' | 'operation' | 'position' | 'set'>('worker')

  const [report, setReport] = useState<PieceworkReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await productionApi.getPieceworkSummary({
        period,
        worker_name: workerName.trim() || undefined,
      })
      setReport(res.data?.data ?? null)
    } catch (e) {
      console.error(e)
      setReport(null)
      setError('计件工资加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [period, workerName])

  useEffect(() => {
    load()
  }, [load])

  const perWorker = report?.per_worker ?? []
  const perOperation = report?.per_operation ?? []
  // 下钻两维（issue #4347 §3.2）：与按人/按工序**同一份后端聚合** ⇒ 各维合计 = total
  const perPosition = report?.per_position ?? []
  const perSet = report?.per_set ?? []
  // 未定价块（V90，issue #4696）：**必须参与空态判定** —— 只有未定价报工的期间里
  // total/per_worker/per_operation 全空，若只看它们就渲染「该期间暂无计件数据」，
  // 把「干了活但没定价、一分钱没有」藏起来（正是本 issue 要治的静默形态）。
  const hasUnpriced = (report?.unpriced?.operations ?? []).length > 0
  const isEmpty =
    !loading && !error && (report?.total ?? 0) === 0 && perWorker.length === 0 &&
    perOperation.length === 0 && !hasUnpriced

  return (
    <div className="p-6 space-y-4">
      <PageHeader
        title="计件工资"
        subtitle={<>按期间汇总报工并算计件工资 —— <strong>返工、报废不计件</strong></>}
        actions={
          <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={cn('w-4 h-4 mr-1.5', loading && 'animate-spin')} />
            刷新
          </Button>
        }
      />

      {/* 查询条件：期间（月份）+ 工人 */}
      <div className="rounded-lg border border-neutral-200 bg-white p-5">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex items-center gap-2">
            <label htmlFor="piecework-period" className="text-sm text-neutral-600 whitespace-nowrap">
              期间
            </label>
            <input
              id="piecework-period"
              type="month"
              value={period}
              data-testid="piecework-period"
              onChange={(e) => setPeriod(e.target.value)}
              className="h-9 min-w-[150px] rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="piecework-worker" className="text-sm text-neutral-600 whitespace-nowrap">
              工人
            </label>
            <input
              id="piecework-worker"
              placeholder="按工人筛选（可留空）"
              value={workerName}
              data-testid="piecework-worker-input"
              onChange={(e) => setWorkerName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && load()}
              className="h-9 min-w-[180px] rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 placeholder:text-neutral-400"
            />
          </div>
          <Button size="sm" data-testid="piecework-search" onClick={load} disabled={loading}>
            <Search className="w-4 h-4 mr-1.5" />
            查询
          </Button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500" data-testid="piecework-loading">
          <RefreshCw className="w-4 h-4 animate-spin" />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-neutral-200 bg-white py-10"
          data-testid="piecework-error"
        >
          <AlertCircle className="w-6 h-6 text-red-500" />
          <p className="text-sm text-neutral-600">{error}</p>
          <Button size="sm" data-testid="piecework-retry" onClick={load}>
            重试
          </Button>
        </div>
      )}

      {isEmpty && (
        <div className="rounded-lg border border-neutral-200 bg-white py-10 text-center" data-testid="piecework-empty">
          <p className="text-sm text-neutral-400">该期间暂无计件数据</p>
        </div>
      )}

      {!loading && !error && !isEmpty && (
        <>
          <div className="rounded-lg border border-neutral-200 bg-white p-5">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-sm text-neutral-500">期间合计</span>
              <span className="text-2xl font-semibold text-neutral-900" data-testid="piecework-report-total">
                {formatMoney(report?.total)}
              </span>
              <span className="text-sm text-neutral-400">
                {report?.period ?? period} · 共 {perWorker.length} 人
              </span>
            </div>
          </div>

          {/* 未定价显式可见（V90，issue #4696）：未定价的报工不进合计，必须在这里说清楚
              「哪道工序、干了多少、多少钱没算」并给出定价入口 —— 不能只在读面徽标上。 */}
          <UnpricedNotice unpriced={report?.unpriced} />

          {/* 按工人 / 按工序 两档 */}
          <div className="rounded-lg border border-neutral-200 bg-white">
            <div className="flex gap-1 border-b border-neutral-200 px-4 pt-3">
              <button
                type="button"
                data-testid="piecework-tab-worker"
                onClick={() => setTab('worker')}
                className={cn(
                  'rounded-t px-4 py-2 text-sm transition-colors',
                  tab === 'worker'
                    ? 'border-b-2 border-primary-600 font-medium text-primary-700'
                    : 'text-neutral-500 hover:text-neutral-800',
                )}
              >
                按工人
              </button>
              <button
                type="button"
                data-testid="piecework-tab-operation"
                onClick={() => setTab('operation')}
                className={cn(
                  'rounded-t px-4 py-2 text-sm transition-colors',
                  tab === 'operation'
                    ? 'border-b-2 border-primary-600 font-medium text-primary-700'
                    : 'text-neutral-500 hover:text-neutral-800',
                )}
              >
                按工序
              </button>
              <button
                type="button"
                data-testid="piecework-tab-position"
                onClick={() => setTab('position')}
                className={cn(
                  'rounded-t px-4 py-2 text-sm transition-colors',
                  tab === 'position'
                    ? 'border-b-2 border-primary-600 font-medium text-primary-700'
                    : 'text-neutral-500 hover:text-neutral-800',
                )}
              >
                按部位
              </button>
              <button
                type="button"
                data-testid="piecework-tab-set"
                onClick={() => setTab('set')}
                className={cn(
                  'rounded-t px-4 py-2 text-sm transition-colors',
                  tab === 'set'
                    ? 'border-b-2 border-primary-600 font-medium text-primary-700'
                    : 'text-neutral-500 hover:text-neutral-800',
                )}
              >
                按套
              </button>
            </div>

            {tab === 'position' || tab === 'set' ? (
              <div
                className="overflow-x-auto"
                data-testid={tab === 'position' ? 'piecework-by-position' : 'piecework-by-set'}
              >
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                      <th className="pl-5 pr-4 py-3 font-medium">{tab === 'position' ? '部位' : '套'}</th>
                      <th className="px-4 py-3 font-medium">计件数量</th>
                      <th className="px-4 py-3 font-medium">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(tab === 'position' ? perPosition : perSet).map((row) => {
                      // 键名两维不同：部位用 position_name，套用 set_no
                      // （#4725 用户裁定「一套窗 = 一套」：套 = 套窗（craftLineId 组），**不是**订单行）
                      const key = tab === 'position'
                        ? (row.position_name ?? '')
                        : (row.set_no ?? '')
                      return (
                        <tr
                          key={key}
                          className="border-b border-neutral-100 last:border-0"
                          data-testid={`${tab}-row-${key}`}
                        >
                          <td className="pl-5 pr-4 py-3.5 text-neutral-900">{key}</td>
                          <td className="px-4 py-3.5 text-neutral-600">{formatQty(row.qty)}</td>
                          <td className="px-4 py-3.5 font-medium text-neutral-900">{formatMoney(row.amount)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {(tab === 'position' ? perPosition : perSet).length === 0 && (
                  <p className="py-8 text-center text-sm text-neutral-400">无数据</p>
                )}
              </div>
            ) : tab === 'worker' ? (
              <div className="overflow-x-auto" data-testid="piecework-by-worker">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                      <th className="pl-5 pr-4 py-3 font-medium">工人</th>
                      <th className="px-4 py-3 font-medium">计件数量</th>
                      <th className="px-4 py-3 font-medium">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perWorker.map((w) => (
                      <tr
                        key={w.worker_name}
                        className="border-b border-neutral-100 last:border-0"
                        data-testid={`worker-row-${w.worker_name}`}
                      >
                        <td className="pl-5 pr-4 py-3.5 text-neutral-900">{w.worker_name}</td>
                        <td className="px-4 py-3.5 text-neutral-600">{formatQty(w.qty)}</td>
                        <td className="px-4 py-3.5 font-medium text-neutral-900">{formatMoney(w.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {perWorker.length === 0 && <p className="py-8 text-center text-sm text-neutral-400">无数据</p>}
              </div>
            ) : (
              <div className="overflow-x-auto" data-testid="piecework-by-operation">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                      <th className="pl-5 pr-4 py-3 font-medium">工序</th>
                      <th className="px-4 py-3 font-medium">计件数量</th>
                      <th className="px-4 py-3 font-medium">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perOperation.map((o, index) => (
                      <tr
                        key={`${operationDisplayName(o)}-${index}`}
                        className="border-b border-neutral-100 last:border-0"
                        data-testid={`operation-row-${operationDisplayName(o)}`}
                      >
                        <td className="pl-5 pr-4 py-3.5 text-neutral-900">{operationDisplayName(o)}</td>
                        <td className="px-4 py-3.5 text-neutral-600">{formatQty(o.qty)}</td>
                        <td className="px-4 py-3.5 font-medium text-neutral-900">{formatMoney(o.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {perOperation.length === 0 && <p className="py-8 text-center text-sm text-neutral-400">无数据</p>}
              </div>
            )}
          </div>
        </>
      )}

      {/* 结算单（issue #5653）：**生成即冻结**、要改就作废重开。放在报表之后 —— 商家先看数、再决定结。 */}
      <SettlementSection period={period} workers={perWorker} />
    </div>
  )
}

/**
 * 结算单区块（issue #5653）。
 *
 * 口径（用户 2026-10-16 裁定 A 快照式）：
 * ① **生成即冻结** —— 界面**没有**任何改写金额的入口（要改就作废 + 重开）；
 * ② **同一期间同一工人只能有一张生效单** —— 重复生成是**具名错误**，界面把服务端那句原话透出
 *    （不吞理由、也不在前端抄写第二份措辞 ⇒ 两处不会各自漂移）；
 * ③ **作废不删行** —— 作废后旧单仍在列表里（默认折叠，点「已作废 N 张」展开），能查到原因。
 *
 * ⚠️ 工人口径 = **同一份报表读数的按人行**（`per_worker`）：界面上选的就是报表里那几行，
 * 金额同屏可见 ⇒ 「结算金额与报表一致」在界面上直接可核（前端不重算、不拼金额）。
 */
function SettlementSection({ period, workers }: { period: string; workers: PieceworkWorkerOption[] }) {
  const [data, setData] = useState<PieceworkSettlementList | null>(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [showVoided, setShowVoided] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  const [pickedWorker, setPickedWorker] = useState('')
  const [busy, setBusy] = useState(false)
  const [voidingId, setVoidingId] = useState('')
  const [voidReason, setVoidReason] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      // 一次取全（含已作废）：条数是「已作废 N 张」入口的依据；**渲染**默认只给生效单
      // （常驻面不随已作废条数增长 —— 折叠态下那些行不进 DOM）。
      const res: { data: ApiResponse<PieceworkSettlementList> } =
        await productionApi.getPieceworkSettlements({ period, include_voided: true })
      setData(res.data?.data ?? null)
    } catch (e) {
      console.error(e)
      setData(null)
      setNotice('结算单加载失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [period])

  useEffect(() => {
    load()
  }, [load])

  // 生成：可选工人 = 本期报表里有金额的人（没有可结算的人 ⇒ 不给按钮，也不编造默认值）
  const canGenerate = workers.length > 0 && !busy
  const active = (data?.items ?? []).filter((row) => !row.voided)
  const voidedRows = (data?.items ?? []).filter((row) => row.voided)
  const visible = showVoided ? [...active, ...voidedRows] : active
  const activeAmount = active.reduce((sum, row) => sum + Number(row.total_amount || 0), 0)

  async function generate() {
    if (!pickedWorker) {
      setNotice('请先选择工人')
      return
    }
    setBusy(true)
    setNotice('')
    try {
      await productionApi.generatePieceworkSettlement({ period, worker_name: pickedWorker })
      setPanelOpen(false)
      setPickedWorker('')
      await load()
    } catch (e) {
      // 「绝不吞掉理由」：服务端那句（含 409 的「已有一张生效的结算单…先作废再重开」）原样上屏
      setNotice(settlementReason(e) ?? '生成失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  async function doVoid(id: string) {
    setBusy(true)
    setNotice('')
    try {
      await productionApi.voidPieceworkSettlement(id, { reason: voidReason })
      setVoidingId('')
      setVoidReason('')
      // 刚作废的那张要**留在眼前**（含状态与原因）——正是「作废不删行」在界面上的样子
      setShowVoided(true)
      await load()
    } catch (e) {
      setNotice(settlementReason(e) ?? '作废失败，请稍后重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-neutral-200 bg-white" data-testid="settlement-section">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-neutral-200 px-5 py-4">
        <div>
          <h2 className="text-base font-medium text-neutral-900">结算单</h2>
          <p className="mt-0.5 text-sm text-neutral-500">
            生成后金额固定不变；要改就先作废，再重新生成 —— 作废的单会留在下面，能查到原因
          </p>
        </div>
        <Button size="sm" data-testid="settlement-generate-open" onClick={() => { setPanelOpen(true); setNotice('') }} disabled={!canGenerate}>
          <Check className="w-4 h-4 mr-1.5" />
          生成结算单
        </Button>
      </div>

      {panelOpen && (
        <div className="flex flex-wrap items-end gap-3 border-b border-neutral-200 bg-neutral-50 px-5 py-4" data-testid="settlement-generate-panel">
          <div className="flex items-center gap-2">
            <label htmlFor="settlement-worker" className="text-sm text-neutral-600 whitespace-nowrap">
              工人
            </label>
            <select
              id="settlement-worker"
              data-testid="settlement-worker-select"
              value={pickedWorker}
              onChange={(e) => setPickedWorker(e.target.value)}
              className={cn(SELECT_CONTROL, 'min-w-[200px]')}
            >
              <option value="">请选择工人</option>
              {workers.map((w) => (
                <option key={w.worker_name} value={w.worker_name}>
                  {w.worker_name} · {money(w.amount)}
                </option>
              ))}
            </select>
          </div>
          <Button size="sm" data-testid="settlement-generate-confirm" onClick={generate} disabled={busy}>
            确认生成
          </Button>
          <Button
            size="sm"
            variant="secondary"
            data-testid="settlement-generate-cancel"
            onClick={() => { setPanelOpen(false); setPickedWorker(''); setNotice('') }}
            disabled={busy}
          >
            取消
          </Button>
          <span className="text-xs text-neutral-400">可选工人与金额来自上表本期读数</span>
        </div>
      )}

      {workers.length === 0 && (
        <p className="border-b border-neutral-200 px-5 py-3 text-sm text-neutral-400" data-testid="settlement-no-worker">
          本期没有可结算的工人 —— 有报工但未定价的分文不计（未定价不等于 0 元）
        </p>
      )}

      {notice && (
        <p className="border-b border-neutral-200 bg-neutral-50 px-5 py-2 text-sm text-neutral-700" data-testid="settlement-notice">
          {notice}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm text-neutral-600">
        {loading ? (
          <span data-testid="settlement-loading">加载中…</span>
        ) : active.length === 0 ? (
          <span data-testid="settlement-empty">本期还没有结算单</span>
        ) : (
          <span data-testid="settlement-summary">
            本期 {active.length} 张生效 · 合计 {money(activeAmount)}
          </span>
        )}
        {voidedRows.length > 0 && (
          <button
            type="button"
            data-testid="settlement-toggle-voided"
            aria-expanded={showVoided}
            onClick={() => setShowVoided((v) => !v)}
            className="text-sm text-primary-700 hover:underline"
          >
            已作废 {voidedRows.length} 张{showVoided ? '（收起）' : '（查看）'}
          </button>
        )}
      </div>

      {visible.length > 0 && (
        <div className="overflow-x-auto" data-testid="settlement-list">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-xs text-neutral-500">
                <th className="pl-5 pr-4 py-3 font-medium whitespace-nowrap">工人</th>
                <th className="px-4 py-3 font-medium whitespace-nowrap">金额</th>
                <th className="px-4 py-3 font-medium whitespace-nowrap">状态</th>
                {/* issue #6717：含「操作」列的表格，该列必须右缘冻结（sticky right-0 + 不透明背景）
                    或落在前 3 列内 —— 否则窄视口下它落在容器右缘之外，商家要横向滚动才够得到行操作 */}
                <th className="sticky right-0 z-20 border-l border-neutral-200 bg-white px-4 py-3 font-medium whitespace-nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.id} className="border-b border-neutral-100 last:border-0" data-testid={`settlement-row-${row.id}`}>
                  <td className="pl-5 pr-4 py-3.5 text-neutral-900 whitespace-nowrap">{row.worker_name}</td>
                  <td className="px-4 py-3.5 font-medium text-neutral-900 whitespace-nowrap" data-testid={`settlement-amount-${row.id}`}>
                    {money(row.total_amount)}
                  </td>
                  <td className="px-4 py-3.5 text-neutral-600 whitespace-nowrap" data-testid={`settlement-status-${row.id}`}>
                    {row.voided ? `已作废${row.void_reason ? ` · ${row.void_reason}` : ''}` : '生效中'}
                  </td>
                  <td className="sticky right-0 z-10 border-l border-neutral-100 bg-white px-4 py-3.5 whitespace-nowrap">
                    {row.voided ? (
                      <span className="text-neutral-300">—</span>
                    ) : voidingId === row.id ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <input
                          data-testid={`settlement-void-reason-${row.id}`}
                          placeholder="作废原因（例如：单价录错，重新结算）"
                          value={voidReason}
                          onChange={(e) => setVoidReason(e.target.value)}
                          className="h-8 min-w-[220px] rounded border border-neutral-300 px-2 text-sm"
                        />
                        <Button size="sm" data-testid={`settlement-void-confirm-${row.id}`} onClick={() => doVoid(row.id)} disabled={busy}>
                          确认作废
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          data-testid={`settlement-void-cancel-${row.id}`}
                          onClick={() => { setVoidingId(''); setVoidReason('') }}
                          disabled={busy}
                        >
                          取消
                        </Button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        data-testid={`settlement-void-open-${row.id}`}
                        onClick={() => { setVoidingId(row.id); setVoidReason(''); setNotice('') }}
                        className="inline-flex items-center gap-1 text-sm text-neutral-600 hover:text-neutral-900"
                      >
                        <X className="w-3.5 h-3.5" />
                        作废
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** 报表「按人」行的**最小**形状（本页只用到这两列 —— 不为一个下拉框引整个报表类型）。 */
type PieceworkWorkerOption = { worker_name: string; amount: number }

/**
 * 服务端失败理由 → 上屏文案（原样透出，**绝不吞**）。
 *
 * 后端信封 `{success:false, error:{code, message}}`（与 `production-guard-reasons.ts` 同口径）；
 * 取不到信封时退回 `Error.message`，最后由调用方给兜底句。
 */
function settlementReason(error: unknown): string | null {
  if (isAxiosError(error)) {
    const msg = error.response?.data?.error?.message
    if (typeof msg === 'string' && msg.trim()) return msg
  }
  const m = (error as Error | null)?.message
  return typeof m === 'string' && m.trim() ? m : null
}
