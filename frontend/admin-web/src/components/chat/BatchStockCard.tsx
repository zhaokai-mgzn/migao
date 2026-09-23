'use client'

/**
 * 批次账 / 省料度量卡（米宝 B 端会话内）— issue #5188
 *
 * ## 为什么按 `action` 分支
 *
 * `batch_stock_query` 一个工具覆盖四个只读读面（批次余量 / 剩余量分布 / 省料汇总 /
 * 省料趋势），工具返回的 `data` 除**服务端读面原样透传**外只多一个 `action` 判别键
 * （见 `backend/ai-agent-service/app/tools/batch_stock_query.py`）——本卡照它分支。
 *
 * ## 🔴 口径纪律（本仓红线，与 `lib/saving-board.ts` 同源）
 *
 * - **不算数**：`remainingMeters` / `savedMeters` / `savedAmount` / `le0_2Share` / `share`
 *   全部**原样渲染服务端值**（显示格式化复用 `lib/saving-board.ts` 的
 *   `formatMeters` / `formatShare` / `formatMetric`）。在浏览器里再算一遍 = 第二份会漂的口径。
 * - **不写死档位文案**：分布四档的「≤0.2 米 / 0.2~0.5 米 / …」一律取自服务端
 *   `buckets[].label`（§22 基线纪律①：文案里不出现数字，数值由真值渲染）。
 *   「快用尽」的阈值也取工具回的 `filters.nearly_used_up_threshold_meters`，不自编。
 * - **空数据不冒充 0**：`null` ⇒ 「无数据」（`NO_DATA`），`0` 才显示 `0`。
 *
 * ## 三端契约
 *
 * 契约不变式「后端能发到这一端的卡型 ⊆ 这一端能渲染的卡型」
 * （`backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`）。
 * 该工具只绑米宝的 Skill（`product:list` 门禁 ⇒ C 端恒不可达）⇒ 按 persona 推导，
 * 需要渲染本卡的是 **B 端桌面（本文件）+ B 端移动（bmini-app）** 两端；
 * C 端 `mini-app` **有意不加**分支（加了就是永不命中的死 UI，反向契约判据专门拦这种）。
 */
import { NO_DATA, formatMeters, formatMetric, formatShare } from '@/lib/saving-board'

interface BatchStockBucket {
  key?: string
  /** 档位文案**取自服务端**（本卡不写数字） */
  label?: string
  batchCount?: number
  share?: number | string | null
}

interface BatchStockRow {
  batchNo?: string
  dyeLot?: string | null
  skuCode?: string | null
  receivedDate?: string | null
  unitCost?: number | string | null
  remainingMeters?: number | string | null
}

interface BatchStockCohort {
  cohort?: string
  cohortLabel?: string
  opening?: boolean
  batchCount?: number
  le0_2Count?: number
  le0_2Share?: number | string | null
  remainingMeters?: number | string | null
  savedMeters?: number | string | null
  savedAmount?: number | string | null
  lineCount?: number
  unknownCostLines?: number
  buckets?: BatchStockBucket[]
}

export interface BatchStockCardData {
  action?: string
  granularity?: string
  timezone?: string
  // batches
  batches?: BatchStockRow[]
  batch_count?: number
  matched_count?: number
  truncated?: boolean
  filters?: { nearly_used_up?: boolean; nearly_used_up_threshold_meters?: string | null }
  // distribution
  totalBatches?: number
  buckets?: BatchStockBucket[]
  // saving_board
  cohorts?: BatchStockCohort[]
  total?: {
    savedMeters?: number | string | null
    savedAmount?: number | string | null
    le0_2Share?: number | string | null
    batchCount?: number
    lineCount?: number
    unknownCostLines?: number
  }
  // saving_trend
  points?: unknown[]
  purchasedTotalMeters?: number | string | null
  consumedTotalMeters?: number | string | null
  openingTotalMeters?: number | string | null
}

const CARD_CLASS =
  'bg-white border border-neutral-200 rounded-xl p-3 shadow-sm space-y-2'
const ROW_CLASS = 'flex items-center justify-between text-xs'

function Shell({ title, hint, children }: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div data-testid="batch-stock-card" className={CARD_CLASS}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-neutral-700">{title}</span>
        {hint && <span className="text-[11px] text-neutral-400">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

export default function BatchStockCard({ data }: { data: BatchStockCardData }) {
  const action = data?.action

  if (action === 'batches') {
    const rows = data.batches || []
    const filters = data.filters || {}
    const hint = filters.nearly_used_up
      ? `快用尽（剩余 ≤ ${filters.nearly_used_up_threshold_meters ?? ''} 米）`
      : undefined
    return (
      <Shell title="批次余量" hint={hint}>
        {rows.length === 0 ? (
          <p className="text-xs text-neutral-400" data-testid="batch-stock-empty">{NO_DATA}</p>
        ) : (
          <>
            {rows.map((row, index) => (
              <div key={row.batchNo || index} className={ROW_CLASS}>
                <span className="text-neutral-700">
                  {row.batchNo || NO_DATA}
                  {row.dyeLot ? `（缸号 ${row.dyeLot}）` : ''}
                </span>
                <span className="font-medium text-neutral-900">
                  {`剩 ${formatMeters(row.remainingMeters)}`}
                </span>
              </div>
            ))}
            {data.truncated && (
              <p className="text-[11px] text-neutral-400">
                {`共 ${data.matched_count ?? rows.length} 个批次，仅展示前 ${rows.length} 个`}
              </p>
            )}
          </>
        )}
      </Shell>
    )
  }

  if (action === 'distribution') {
    const buckets = data.buckets || []
    return (
      <Shell title="剩余量分布" hint={data.totalBatches ? `共 ${data.totalBatches} 个批次` : undefined}>
        {!data.totalBatches ? (
          <p className="text-xs text-neutral-400" data-testid="batch-stock-empty">{NO_DATA}</p>
        ) : (
          buckets.map((bucket, index) => (
            <div key={bucket.key || index} className={ROW_CLASS}>
              {/* 档位文案取自服务端 label（不自己写数字） */}
              <span className="text-neutral-600">{bucket.label || NO_DATA}</span>
              <span className="text-neutral-900">
                {`${bucket.batchCount ?? 0} 个 · ${formatShare(bucket.share)}`}
              </span>
            </div>
          ))
        )}
      </Shell>
    )
  }

  if (action === 'saving_board') {
    const cohorts = data.cohorts || []
    const total = data.total || {}
    return (
      <Shell title="省料度量" hint={data.granularity ? `按${data.granularity === 'week' ? '周' : '月'}` : undefined}>
        {cohorts.map((cohort, index) => {
          const bucketLabel = cohort.buckets?.[0]?.label
          return (
            <div key={cohort.cohort || index} className="space-y-0.5">
              <p className="text-xs text-neutral-700">{cohort.cohortLabel || cohort.cohort || NO_DATA}</p>
              <div className={ROW_CLASS}>
                <span className="text-neutral-500">省料</span>
                <span className="font-medium text-neutral-900">
                  {cohort.savedMeters === null || cohort.savedMeters === undefined
                    ? NO_DATA
                    : `${formatMeters(cohort.savedMeters)} / ${formatMetric(cohort.savedAmount)} 元`}
                </span>
              </div>
              <div className={ROW_CLASS}>
                <span className="text-neutral-500">
                  {bucketLabel ? `剩余 ${bucketLabel} 的批次占比` : '剩余最小档的批次占比'}
                </span>
                <span className="text-neutral-900">{formatShare(cohort.le0_2Share)}</span>
              </div>
              {(cohort.unknownCostLines ?? 0) > 0 && (
                <p className="text-[11px] text-neutral-400">
                  {`其中 ${cohort.unknownCostLines} 行没有均价，金额不含这些行`}
                </p>
              )}
            </div>
          )
        })}
        <p className="text-[11px] text-neutral-400" data-testid="batch-stock-total">
          {`合计省 ${formatMeters(total.savedMeters)} / ${formatMetric(total.savedAmount)} 元`}
        </p>
      </Shell>
    )
  }

  if (action === 'saving_trend') {
    return (
      <Shell title="省料趋势" hint={data.granularity ? `按${data.granularity === 'week' ? '周' : '月'}` : undefined}>
        <div className={ROW_CLASS}>
          <span className="text-neutral-500">采购入库</span>
          <span className="text-neutral-900">{formatMeters(data.purchasedTotalMeters)}</span>
        </div>
        <div className={ROW_CLASS}>
          <span className="text-neutral-500">消耗</span>
          <span className="text-neutral-900">{formatMeters(data.consumedTotalMeters)}</span>
        </div>
        <div className={ROW_CLASS}>
          {/* 存量导入单列（口径：它不是「这个月的采购」） */}
          <span className="text-neutral-500">存量导入入库（单列）</span>
          <span className="text-neutral-900">{formatMeters(data.openingTotalMeters)}</span>
        </div>
      </Shell>
    )
  }

  return (
    <Shell title="批次 / 省料">
      <p className="text-xs text-neutral-400" data-testid="batch-stock-empty">{NO_DATA}</p>
    </Shell>
  )
}
