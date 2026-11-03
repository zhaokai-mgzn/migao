'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { extractApiErrorMessage, toastRequestError } from '@/lib/api-error'
import { materialShortageApi } from '@/lib/api'
import { Button, Card, Loading, PageHeader } from '@/components/ui'
import {
  DEADLINE_UNKNOWN,
  NO_SHORTAGE,
  UNKNOWN,
  bandCountsText,
  bandLabel,
  deadlineText,
  formatMeters,
  historyDepthNote,
  nonComparableNote,
  ordersText,
  shortageCount,
  shortageRows,
  truncationNote,
} from '@/lib/material-shortage'
import type { MaterialShortageRow, MaterialShortageView } from '@/types'

/** 与后端缺省一致（`MaterialShortageService.DEFAULT_LIMIT`）；非法值由服务端显式拒绝，前端不夹取 */
const LIMIT = 50

/**
 * 缺料风险 `/production/material-shortage`（issue #6282；数据源 = 具名跨域视图
 * `material_shortage`，契约真值源 = issue #6280 的「冻结契约 v1」）。
 *
 * ## 这一页回答的问题
 * **哪些成品会因为用料不够而交不了货**，以及**每一行该去哪儿处置**。
 * 数字全部来自 `GET /api/admin/materials/shortage`（权限码 `product:list`），
 * 页面**不做**任何四则运算、**不做**任何重排（行序 = 服务端分层降序 → 缺口降序）。
 *
 * ## §31 产品设计原则的四问
 * - **P1 常驻面克制**：默认面只列**真正缺的**（缺口 > 0）⇒ 一屏之内；摘要固定一行
 *   （缺料条数 + 六档非空档计数），不随条数增长。行数上限由服务端 `limit` 兜住。
 * - **P2 信息不重复**：缺口数字只在「缺口」列出现一次；滴告警 / 摘要不重念任何表的列。
 * - **P3 不摆内部标识**：`productId` 只进 `href`（`/products/<id>`）；`fields` 的字段名 /
 *   `basis` 的内部键不上屏；档名渲染成商家话（`交期已过 / 交期紧张 / …`）。
 * - **P4 语调**：空态是**事实陈述**「当前没有缺料」；披露只说事实与归因，不催促、不惊叹。
 *
 * ## 🔴 未知 ≠ 0（三处，都是「最容易做成假绿」的地方）
 * - 缺口 / 需求 / 影响订单缺键 ⇒ 渲染「未知」（单位不可比时服务端**不下发**这些键）；
 * - `daysToDeadline` 缺键 ⇒ 交期列渲染「紧迫性未知」（实测 dev 库交期填充率为 0）；
 * - 周消耗速率 / 预计耗尽日（v1 未接线）**不渲染成 0 或空格**，由历史深度披露统一说明。
 */
export default function MaterialShortagePage() {
  const [view, setView] = useState<MaterialShortageView | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  /** 默认**只**列真正缺的（§31 P1）；勾选后连同有余量 / 单位不可比一起看（负控出口） */
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await materialShortageApi.shortage({ limit: LIMIT })
      setView(res.data?.data ?? null)
      setError('')
    } catch (e) {
      // 服务端业务文案优先（`e.message` 在 axios 错误上是传输层读数，不许当失败原因上屏）
      setError(extractApiErrorMessage(e, '加载缺料风险失败'))
      toastRequestError(e, '加载缺料风险失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const rows = view?.rows ?? []
  const shown = showAll ? rows : shortageRows(rows)
  /** 首屏在途：读数还没回来 ≠ 「当前没有缺料」（四态①，不印空态） */
  const pending = loading && view === null
  /** 🔴 读失败且没有旧读数 ⇒ **不印空态**（读不到 ≠ 没有缺料；同族：余料台账 #6702） */
  const failed = error !== '' && view === null
  const bands = bandCountsText(view?.bandCounts)
  const comparable = nonComparableNote(view)
  const historyNote = historyDepthNote(view?.historyDepth)
  const truncated = truncationNote(view)
  const missing = shortageCount(view?.bandCounts)

  return (
    <div className="p-6 space-y-4">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-primary-600" />
            缺料风险
          </span>
        }
        subtitle="看看哪些成品会因为布料不够而交不了货；每一行都能直接去处置"
        actions={
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-sm text-neutral-600">
              <input
                type="checkbox"
                data-testid="shortage-show-all"
                checked={showAll}
                onChange={(e) => setShowAll(e.target.checked)}
                className="h-4 w-4 rounded border-neutral-300"
              />
              显示全部（含有余量 / 单位不可比）
            </label>
            <Button variant="secondary" onClick={() => void load()} loading={loading}>
              <RefreshCw className="w-4 h-4 mr-1.5" />
              刷新
            </Button>
          </div>
        }
      />

      {error && (
        <div
          data-testid="shortage-error"
          className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700"
        >
          加载失败：{error}
        </div>
      )}

      {failed ? null : pending ? (
        <Card>
          <div className="p-10" data-testid="shortage-loading">
            <Loading text="加载中…" />
          </div>
        </Card>
      ) : (
        <>
          {/* 常驻面 = **一行**摘要（条数 + 六档非空档计数）——不随条数增长（§31 P1） */}
          <p data-testid="shortage-summary" className="text-sm text-neutral-700">
            {missing > 0 ? `共 ${missing} 个成品缺料` : NO_SHORTAGE}
            {missing > 0 && bands && (
              <span data-testid="shortage-bands" className="ml-2 text-xs text-neutral-500">
                {' '}
                {bands}
              </span>
            )}
          </p>

          {/* 单位不可比披露（issue #6282 要求 3）：必须看得见，不许渲染成 0 或缺省行 */}
          {comparable && (
            <p data-testid="shortage-non-comparable" className="text-xs text-amber-700">
              {comparable}
            </p>
          )}

          {/* 历史深度披露（要求 4）：sufficient=false ⇒ 明说预测层未启用 + 真实深度 */}
          {historyNote && (
            <p data-testid="shortage-history-depth" className="text-xs text-neutral-500">
              {historyNote}
            </p>
          )}

          {truncated && (
            <p data-testid="shortage-truncated" className="text-xs text-neutral-500">
              {truncated}
            </p>
          )}

          <Card>
            {shown.length === 0 ? (
              <>
                <div data-testid="shortage-empty" className="px-4 py-10 text-center text-sm text-neutral-500">
                  {NO_SHORTAGE}
                </div>
                {!showAll && rows.length > 0 && (
                  <p data-testid="shortage-empty-hint" className="pb-6 -mt-4 text-center text-xs text-neutral-400">
                    勾选「显示全部」可以看到有余量 / 单位不可比的成品
                  </p>
                )}
              </>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="shortage-table">
                  <thead className="bg-neutral-50 text-neutral-600">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">成品</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">需要（米）</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">现有库存（米）</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">缺口（米）</th>
                      <th className="text-right px-4 py-2.5 font-medium whitespace-nowrap">影响订单</th>
                      <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">紧迫度</th>
                      <th className="text-left px-4 py-2.5 font-medium whitespace-nowrap">处置</th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* 行序 = 服务端行序（分层降序 → 缺口降序），页面**不重排** */}
                    {shown.map((row) => (
                      <ShortageRow key={row.productId} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* 口径与边界：首屏之外一次说完，默认收起 */}
          <details
            data-testid="shortage-footnotes"
            className="rounded-lg border border-neutral-200 bg-white p-4 text-xs text-neutral-600"
          >
            <summary className="cursor-pointer text-sm font-medium text-neutral-800">口径与边界</summary>
            <ul className="mt-2 list-disc pl-4 space-y-0.5">
              <li>缺口 = 未完成订单（已确认 / 生产中）的用量合计 − SKU 库存合计；需求为 0 且无库存的成品不在列表里。</li>
              <li>只有单位是「米」的成品能相减；单位不可比的成品记为「单位不可比」，不按 0 计。</li>
              <li>缺口为负表示还有余量；交期没填的成品归到「有缺口」，交期显示为「{DEADLINE_UNKNOWN}」。</li>
              <li>周消耗速率与预计耗尽日要有足够的历史台账深度才给；未达标时一律显示「{UNKNOWN}」。</li>
            </ul>
          </details>
        </>
      )}
    </div>
  )
}

/** 一行 = 一个成品；缺口数字**只**在「缺口」列出现一次（§31 P2） */
function ShortageRow({ row }: { row: MaterialShortageRow }) {
  const gap = row.gapMeters
  return (
    <tr data-testid="shortage-row" className="border-t border-neutral-100">
      {/* 展示名只有服务端的 `productName`；`productId` 只进 href（§31 P3） */}
      <td data-testid="shortage-name" className="px-4 py-2.5 text-neutral-700">
        {row.productName}
      </td>
      <td data-testid="shortage-demand" className="px-4 py-2.5 text-right font-mono whitespace-nowrap text-neutral-900">
        {formatMeters(row.demandQty)}
      </td>
      <td data-testid="shortage-stock" className="px-4 py-2.5 text-right font-mono whitespace-nowrap text-neutral-900">
        {formatMeters(row.stockMeters)}
      </td>
      <td
        data-testid="shortage-gap"
        className={
          'px-4 py-2.5 text-right font-mono whitespace-nowrap '
          + (typeof gap === 'number' && gap > 0 ? 'text-red-700' : 'text-neutral-900')
        }
      >
        {formatMeters(gap)}
      </td>
      <td data-testid="shortage-orders" className="px-4 py-2.5 text-right whitespace-nowrap text-neutral-700">
        {ordersText(row)}
      </td>
      <td data-testid="shortage-band" className="px-4 py-2.5 whitespace-nowrap">
        <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-700">{bandLabel(row.riskBand)}</span>
        <span data-testid="shortage-deadline" className="ml-2 text-xs text-neutral-500">
          {deadlineText(row.earliestRequiredDeliveryDate, row.daysToDeadline)}
        </span>
      </td>
      {/* 处置入口：三条都是仓内**真实**路由（没有入口就如实标注，不给死链） */}
      <td data-testid="shortage-actions" className="px-4 py-2.5 whitespace-nowrap">
        <div className="flex items-center gap-3 text-xs">
          <Link
            data-testid="shortage-product-link"
            href={`/products/${row.productId}`}
            className="text-primary-600 hover:underline"
          >
            商品详情
          </Link>
          <Link data-testid="shortage-ledger-link" href="/stock-ledger" className="text-primary-600 hover:underline">
            库存台账
          </Link>
          <Link
            data-testid="shortage-inbound-link"
            href="/inbound-orders/new"
            className="text-primary-600 hover:underline"
          >
            去入库
          </Link>
        </div>
      </td>
    </tr>
  )
}
