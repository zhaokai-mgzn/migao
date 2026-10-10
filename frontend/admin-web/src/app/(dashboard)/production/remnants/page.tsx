'use client'

/**
 * 余料台账 /production/remnants（V122，issue #5146）—— 「企业参数中心 → 余料回收」域的**下钻页**，
 * 且自 issue #5191 起**同时是侧边栏入口**（生产管理组「余料台账」；同批新页口径对齐 —— 智能派单 /
 * 省料看板都有菜单项；权限码 processing:manage，与类级 `@RequirePermission` 同码）。
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
 * - 匹配入口要求选**订单明细行**：余料匹配是**逐明细行**的事（小件需求来自该行勾的特殊选项）。
 *   自 issue #6669 起商家**不必手输内部 id** —— 按订单号/客户搜索 → 选订单 → 点一行明细即可
 *   （id 只留在状态里，不上屏）。派工页内嵌匹配**不在本单范围**（登记为边界，见 PR 报告）；
 * - 回收 / 报废的**权限**与算料配置同码（`processing:manage`）—— 无权限时读面会失败，
 *   页面按「权限拒绝是终态」给可行动话术（同族实证：issue #4103）。
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, RefreshCw, Search } from 'lucide-react'
import { Button, Modal, Pagination } from '@/components/ui'
import { orderApi, remnantApi } from '@/lib/api'
import { InlineMarkdown } from '@/lib/inline-markdown'
// 🔴 issue #6669 第 7 条：涉钱读数口径收敛到一处真值（本页缺失值印 `—`，不是 `¥0.00`）
import { moneyOrDash } from '@/lib/money'
import type { Order, RemnantLedgerView, RemnantMatchView } from '@/types'

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

/** 每页条数选项（与共享 `Pagination` 的默认档一致；默认 100 = 本页修前的一次拉取量，不变差） */
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

/**
 * 选择器候选 = **订单的一行明细**（issue #6669 第 2 条）。
 *
 * `itemId`（= 后端要的 `order_items.id`）与 `orderId` 是**内部标识**：只在状态与请求里流转，
 * **不上屏**（商家看到的是订单号 / 商品 / 数量）。
 */
interface LineChoice {
  orderId: string
  orderNo: string
  customerName: string
  itemId: string
  productName: string
  color?: string
  specification?: string
  quantity: number
}

function num(value?: number | null, digits = 2): string {
  return value === undefined || value === null ? '—' : Number(value).toFixed(digits)
}

function money(value?: number | null): string {
  return moneyOrDash(value)
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

  // 小件优先匹配（只读查询）：**订单/明细行选择器** + 可选的该行实际领料批次号
  //
  // 🔴 issue #6669 第 2 条（P0）：修前这里是一个让商家**手输「订单明细行 id」**的输入框，
  // 而界面上**无处能看到/选到**这个 id（它是 order_items 的 UUID）⇒ 该功能对商家实际不可用。
  // 修后：按订单号/客户搜索 → 选中订单 → 列出该订单的明细行（商品名 / 颜色 / 规格 / 数量）→ 点一行。
  // id **只留在状态里**，不上屏（`aria-label` 只描述动作，不回显标识）。
  const [orderItemId, setOrderItemId] = useState('')
  const [lineQuery, setLineQuery] = useState('')
  const [lineCandidates, setLineCandidates] = useState<LineChoice[]>([])
  const [lineSearching, setLineSearching] = useState(false)
  const [linePickError, setLinePickError] = useState('')
  const [selectedLine, setSelectedLine] = useState<LineChoice | null>(null)
  const [batchNo, setBatchNo] = useState('')
  const [match, setMatch] = useState<RemnantMatchView | null>(null)
  const [matchError, setMatchError] = useState('')

  // 报废留痕：自研 Modal（不用 window.prompt —— 无上下文、无「不可撤销」说明、样式不可控）
  const [scrapTarget, setScrapTarget] = useState<number | null>(null)
  const [scrapReason, setScrapReason] = useState('')

  // ── 分页（issue #6697）──
  //
  // 🔴 修前：请求逐字硬编码 `page: 1, size: 100`，而屏上仍渲染服务端给的 `page.total`
  // （实测租户 25：`total = 332`）⇒ **232 条（70%）没有任何可达路径**，
  // 而「共 332 块」那句话让商家以为能数到全部 —— 界面承诺与可达集合不一致。
  // 修后：`page` / `pageSize` 进 state，页面真请求（复用共享 `Pagination`，不新造控件）；
  // 屏上「共 N 块」= 服务端 total，且 `Pagination` 会把「第 X-Y 条 / 共 N 条」一并说清。
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[3])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await remnantApi.ledger({ status: status || undefined, page, size: pageSize })
      setData(res.data?.data ?? null)
    } catch {
      setData(null)
      setError('余料台账读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试')
    }
    setLoading(false)
  }, [status, page, pageSize])

  useEffect(() => {
    void load()
  }, [load])

  /** 搜索订单，并把每个订单的明细行摊平成候选（明细 id 只在内部传递） */
  const searchLines = useCallback(async () => {
    const kw = lineQuery.trim()
    setLinePickError('')
    setLineCandidates([])
    if (!kw) {
      setLinePickError('请先填订单号或客户名（也可以直接搜「全部」看最近订单）')
      return
    }
    setLineSearching(true)
    try {
      const res = await orderApi.getOrders({ keyword: kw, page: 1, size: 20 })
      const orders = (res.data?.data?.items ?? []) as Order[]
      setLineCandidates(
        orders.flatMap((o) =>
          (o.items ?? [])
            .filter((it) => !!it.id)
            .map((it) => ({
              orderId: o.id,
              orderNo: o.orderNo,
              customerName: o.customerName,
              itemId: it.id,
              productName: it.productName,
              color: it.color,
              specification: it.specification,
              quantity: it.quantity,
            })),
        ),
      )
    } catch {
      setLinePickError('订单查询失败 —— 请稍后重试')
    }
    setLineSearching(false)
  }, [lineQuery])

  /** 选中一行 ⇒ 只把明细 id 记进状态（上屏的是「订单号 + 商品 + 数量」） */
  const pickLine = useCallback((c: LineChoice) => {
    setOrderItemId(c.itemId)
    setSelectedLine(c)
    setLinePickError('')
    setMatchError('')
    setMatch(null)
  }, [])

  const runMatch = useCallback(async () => {
    setMatchError('')
    setMatch(null)
    if (!orderItemId.trim()) {
      setMatchError('请先选一个订单明细行（小件需求来自该行勾选的特殊选项）')
      return
    }
    // 只对**选中的那一行**取详情（搜索面摊平出的行不带 id ⇒ 不能用它直接查匹配）
    if (!selectedLine) {
      setMatchError('该明细行已失效 —— 请重新搜索订单并选一行')
      return
    }
    try {
      const res = await orderApi.getOrder(selectedLine.orderId)
      const order = res.data?.data as Order | undefined
      const itemId = (order?.items ?? []).find(
        (it) =>
          it.productName === selectedLine.productName &&
          it.color === selectedLine.color &&
          it.specification === selectedLine.specification &&
          Number(it.quantity) === Number(selectedLine.quantity),
      )?.id
      if (!itemId) {
        setMatchError('这行已不在该订单里（订单可能被改过）—— 请重新搜索并选一行')
        return
      }
      const matchRes = await remnantApi.match({
        orderItemId: itemId,
        batchNo: batchNo.trim() || undefined,
      })
      setMatch(matchRes.data?.data ?? null)
    } catch {
      setMatchError('匹配查询失败 —— 请确认这一行属于本企业，或稍后重试')
    }
  }, [orderItemId, selectedLine, batchNo])

  const recover = useCallback(
    async (remnantId: number, itemKey: string) => {
      setBusyId(remnantId)
      setActionMsg('')
      try {
        await remnantApi.recover(remnantId, {
          orderItemId: orderItemId.trim() || undefined,
          orderNo: selectedLine?.orderNo,
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
    [orderItemId, selectedLine, load, runMatch]
  )

  /**
   * 报废留痕：**自研 Modal**（issue #6669 第 3 条）。
   *
   * 修前走 `window.prompt('报废原因…')` —— 原生弹层的代价：① 没有上下文（看不到要报废的是哪一块）；
   * ② 没有「不可撤销」说明（报废是不可逆的账）；③ 样式/可访问性不可控、且**不可测**。
   * 类级固化见 `tests/unit/lib/no-native-dialog-for-destructive-copy-guard.test.ts`（台账只许缩短）。
   */
  const confirmScrap = useCallback(async () => {
    const reason = scrapReason.trim()
    if (!scrapTarget || !reason) return
    const id = scrapTarget
    setBusyId(id)
    setActionMsg('')
    setScrapTarget(null)
    setScrapReason('')
    try {
      await remnantApi.scrap(id, reason)
      setActionMsg('已报废并留痕（状态 / 原因 / 操作人 / 时刻都可查）')
      await load()
    } catch (e) {
      const detail = (e as { response?: { data?: { error?: { message?: string } } } })?.response?.data
        ?.error?.message
      setActionMsg(detail || '报废失败 —— 请刷新后重试')
    }
    setBusyId(null)
  }, [scrapTarget, scrapReason, load])

  const summary = data?.summary
  const rows = data?.page?.items ?? []

  return (
    <div data-testid="remnant-ledger-page" className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-neutral-900">余料台账</h1>
          <p className="text-sm text-neutral-500 mt-1">管理裁剪剩下的余料：尺寸、来源订单与批次、缸号、状态</p>
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
            { label: '客户带走', value: `${summary.customerTakenCount}`, sub: '不计入可用余料' },
          ].map((cell) => (
            <div key={cell.label} className="bg-white border border-neutral-200 rounded-lg p-3">
              <div className="text-xs text-neutral-500">{cell.label}</div>
              <div className="text-base font-semibold text-neutral-900">{cell.value}</div>
              <div className="text-[11px] text-neutral-400">{cell.sub}</div>
            </div>
          ))}
          <div className="col-span-2 sm:col-span-4 text-xs text-neutral-600 bg-white border border-neutral-200 rounded-lg p-3">
            余料回收额合计 {money(summary.recoveredAmountTotal)}（
            <InlineMarkdown text="冲减**用它的那些单**的面料成本，只进内部成本口径 —— 对客售价与加工费一字不动" />
            ）；领料成本合计 {money(summary.issuedCostTotal)}；
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
          按订单号或客户搜出订单，再点一行明细：系统按该行勾选的特殊选项（余料做绑带 / 余料做帘头 / 抱枕 …）
          算出小件需求，再从<InlineMarkdown text="**可用余料**" />里挑装得下的余料（同缸号优先、其次同色）；
          找到就不新领料。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={lineQuery}
            aria-label="搜索订单或客户"
            placeholder="订单号 / 客户名"
            onChange={(e) => setLineQuery(e.target.value)}
            className="w-64 px-2 py-1 text-xs border border-neutral-300 rounded"
          />
          <Button
            type="button"
            size="sm"
            variant="secondary"
            data-testid="remnant-line-search"
            loading={lineSearching}
            onClick={() => void searchLines()}
          >
            <Search className="w-4 h-4 mr-1" />
            搜订单
          </Button>
          <input
            value={batchNo}
            aria-label="批次号"
            placeholder="批次号（可空，空了从批次台账反查）"
            onChange={(e) => setBatchNo(e.target.value)}
            className="w-64 px-2 py-1 text-xs border border-neutral-300 rounded"
          />
          <Button
            type="button"
            size="sm"
            data-testid="remnant-match-run"
            disabled={!selectedLine}
            onClick={() => void runMatch()}
          >
            查匹配
          </Button>
        </div>

        {/* 选中态：**上屏的是订单号 + 商品 + 数量**（明细 id 不上屏） */}
        {selectedLine && (
          <div
            data-testid="remnant-line-selected"
            className="flex items-center gap-2 text-xs text-neutral-700 bg-neutral-50 border border-neutral-200 rounded p-2"
          >
            <span>
              已选：{selectedLine.orderNo} · {selectedLine.productName}
              {selectedLine.color ? ` · ${selectedLine.color}` : ''}
              {selectedLine.specification ? ` · ${selectedLine.specification}` : ''} ·{' '}
              {selectedLine.quantity} 米
            </span>
            <button
              type="button"
              data-testid="remnant-line-clear"
              className="text-primary-700 hover:underline"
              onClick={() => {
                setSelectedLine(null)
                setOrderItemId('')
                setMatch(null)
                setMatchError('')
              }}
            >
              换一行
            </button>
          </div>
        )}

        {linePickError && <p className="text-xs text-red-700">{linePickError}</p>}

        {/* 候选明细行：折叠封顶 + 可滚动，**不随条数增长**占页面高度（§31 P1） */}
        {lineCandidates.length > 0 && !selectedLine && (
          <div
            data-testid="remnant-line-candidates"
            className="max-h-56 overflow-y-auto divide-y divide-neutral-100 border border-neutral-200 rounded"
          >
            {lineCandidates.map((c) => (
              <button
                key={`${c.orderNo}-${c.productName}-${c.color ?? ''}-${c.specification ?? ''}`}
                type="button"
                data-testid="remnant-line-option"
                className="w-full text-left px-3 py-2 text-xs hover:bg-neutral-50"
                onClick={() => pickLine(c)}
              >
                <span className="font-medium text-neutral-900">{c.orderNo}</span>
                <span className="ml-2 text-neutral-600">
                  {c.productName}
                  {c.color ? ` · ${c.color}` : ''}
                  {c.specification ? ` · ${c.specification}` : ''} · {c.quantity} 米
                </span>
                <span className="ml-2 text-neutral-400">{c.customerName}</span>
              </button>
            ))}
          </div>
        )}
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
          onChange={(e) => {
            setStatus(e.target.value)
            // 换筛选条件 ⇒ 回到第 1 页（否则停在第 N 页的筛选结果短于 N 页时 = 空表）
            setPage(1)
          }}
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
                        onClick={() => {
                          setScrapReason('')
                          setScrapTarget(row.id)
                        }}
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

      {/* ── 分页（issue #6697）：复用共享 `Pagination` —— 上面那行「共 N 块」= 服务端 total，
          这里给它的可达出口（第 X-Y 条 / 共 N 条 + 页码 + 每页条数）。total 为 0 时不显示。── */}
      {!loading && !error && (data?.page?.total ?? 0) > 0 && (
        <div data-testid="remnant-pagination" className="rounded-lg border border-neutral-200 bg-white">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={data?.page?.total ?? 0}
            onChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size)
              setPage(1)
            }}
            pageSizeOptions={PAGE_SIZE_OPTIONS}
          />
        </div>
      )}

      {/* 报废确认（issue #6669 第 3 条）：自研 Modal —— 带上下文（哪一块 / 尺寸 / 来源）+ 不可撤销说明 */}
      <Modal
        open={scrapTarget !== null}
        onClose={() => setScrapTarget(null)}
        title="报废留痕"
        footer={
          <>
            <Button variant="secondary" onClick={() => setScrapTarget(null)}>取消</Button>
            <Button
              variant="danger"
              data-testid="remnant-scrap-confirm"
              disabled={!scrapReason.trim()}
              onClick={() => void confirmScrap()}
            >
              确认报废
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm text-neutral-600">
          <p>
            把这一块余料标记为「已报废」：
            {(() => {
              const row = rows.find((r) => r.id === scrapTarget)
              return row
                ? ` ${row.sourceOrderNo} 的 ${num(row.lengthM)} × ${num(row.widthM)} 米（来源批次 ${row.sourceBatchNo} · 缸号 ${row.dyeLot || '—'}）。`
                : ''
            })()}
            报废后<strong className="font-medium text-neutral-900">无法撤销</strong>，
            状态 / 原因 / 操作人 / 时刻都会留下记录。
          </p>
          <label className="block">
            <span className="block text-xs font-medium text-neutral-700 mb-1">报废原因</span>
            <textarea
              value={scrapReason}
              aria-label="报废原因"
              rows={3}
              onChange={(e) => setScrapReason(e.target.value)}
              placeholder="例如：受潮发霉 / 尺寸不足无法再用"
              className="w-full px-2 py-1 text-sm border border-neutral-300 rounded resize-none"
            />
          </label>
        </div>
      </Modal>
    </div>
  )
}
