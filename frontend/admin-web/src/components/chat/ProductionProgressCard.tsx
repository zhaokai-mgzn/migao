'use client'

/**
 * 生产进度卡（米宝 B 端会话内）— issue #4016 P14（用户 2026-09-18 裁定「补发射点」）
 *
 * ## 为什么是「补发射点」而不是删卡
 *
 * `production_progress_query` 工具早已存在、返回的**正是**卡载荷
 * （`progress_percent` / `current_operation` / `expected_delivery_date` / `positions`），
 * M4-G-3（issue #3997）交付的顾客端卡片却**没有任何发射点** ⇒ 组件永不渲染
 * （「交付物在 main ≠ 能力可达」）。故补 `_detect_card_type` 映射让它真可达。
 *
 * ## 为什么 B 端桌面也要有这一端
 *
 * `production_progress_query` 同时绑在**两个 persona** 的 Skill 上（C 端小布 + B 端米宝，
 * 见评测用例 CH-039/CH-040）⇒ 契约不变式「后端能发到这一端的卡型 ⊆ 这一端能渲染的卡型」
 * 要求三端都有渲染分支（判据见 `backend/ai-agent-service/tests/test_card_type_cross_end_contract.py`，
 * 该判据在缺分支时**实测报红**：`B端桌面 admin-web ToolResultCard 缺 ['production_progress']`）。
 *
 * ## 展示口径（与 C 端 `mini-app/.../ProductionProgressCard.tsx` **逐字段一致**）
 *
 * 只给「进度 / 当前工序 / 待完工序数 / 预计交付」，兼容两种载荷：
 * 1. 工序树：`{positions[].operations[], progress:{total,done,percent}, expected_delivery_at}`
 * 2. 米宝精简进度：`{progress_percent, current_operation, pending_operations[],
 *    total_operations, done_operations, expected_delivery_date}`
 * 空态（两种载荷都没带工序信息）→「暂无生产进度」（不显示假进度、不空白）。
 *
 * ⚠️ 刻意**不复用**页面级 `components/production/ProductionProgressTable`：那是加工单页面的
 * 「按部位分组 + 应做数量 + **计件单价** + 必完 badge」表，面向车间看单、含内部计件账；
 * 会话卡是对外/对客口径的**摘要**，两者语义不同（真值源 docs/curtain-production-rules.md §4
 * 两套账分离）。故此处镜像 C 端摘要口径，不把页面表格搬进聊天流。
 */
interface ProductionCardOperation {
  id?: string
  operation: string
  status?: string
}

interface ProductionCardPosition {
  position_name: string
  operations?: ProductionCardOperation[]
}

export interface ProductionProgressCardData {
  order_id?: string
  order_no?: string
  status?: string
  status_text?: string
  positions?: ProductionCardPosition[]
  operations?: ProductionCardOperation[]
  progress?: { total?: number; done?: number; percent?: number }
  progress_percent?: number
  current_operation?: string
  pending_operations?: string[]
  total_operations?: number
  done_operations?: number
  expected_delivery_at?: string
  expected_delivery_date?: string
  delivery_date?: string
}

/** 取日期部分（后端可能下发 ISO 时间戳） */
function formatDate(value: string): string {
  return value.slice(0, 10)
}

/** 拍平工序列表（positions[].operations[] 优先，兼容扁平 operations[]） */
function flattenOperations(
  positions: ProductionCardPosition[],
  flat?: ProductionCardOperation[],
): ProductionCardOperation[] {
  if (flat && flat.length > 0) return flat
  const result: ProductionCardOperation[] = []
  positions.forEach((position) => {
    ;(position.operations || []).forEach((operation) => result.push(operation))
  })
  return result
}

export default function ProductionProgressCard({ data }: { data: ProductionProgressCardData }) {
  const positions = data?.positions || []
  const operations = flattenOperations(positions, data?.operations)

  const pendingList = data?.pending_operations
  const doneFromOps = operations.filter((operation) => operation.status === 'done').length
  const total = data?.progress?.total ?? data?.total_operations ?? operations.length
  const done = data?.progress?.done ?? data?.done_operations ?? doneFromOps
  const percent =
    data?.progress?.percent
    ?? data?.progress_percent
    ?? (total > 0 ? Math.round((done / total) * 100) : 0)

  const currentFromOps = operations.find((operation) => operation.status !== 'done')
  const current = data?.current_operation || currentFromOps?.operation
  const remaining = pendingList
    ? pendingList.length
    : operations.filter((operation) => operation.status !== 'done').length
  const delivery =
    data?.expected_delivery_at || data?.expected_delivery_date || data?.delivery_date

  // 两种载荷都没带工序信息才是空态（精简载荷没有工序树，但有 current/pending 计数）
  const hasDetail =
    operations.length > 0 || !!current || (pendingList?.length ?? 0) > 0 || total > 0

  return (
    <div
      data-testid="production-progress-card"
      className="bg-white border border-neutral-200 rounded-xl p-3 shadow-sm space-y-2"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-neutral-700">生产进度</span>
        <span className="text-sm font-bold text-neutral-900" data-testid="progress-percent">
          {`${percent}%`}
        </span>
      </div>

      <div className="h-1.5 w-full rounded-full bg-neutral-100 overflow-hidden">
        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${percent}%` }} />
      </div>

      {!hasDetail ? (
        <p className="text-xs text-neutral-400">暂无生产进度</p>
      ) : (
        <>
          <p className="text-xs text-neutral-500">{`已完 ${done}/${total} 道`}</p>
          {current && (
            <p className="text-xs text-neutral-700">{`当前工序：${current}`}</p>
          )}
          <p className="text-xs text-neutral-500">{`待完 ${remaining} 道工序`}</p>
        </>
      )}

      {delivery && (
        <p className="text-[11px] text-neutral-400">{`预计交付 ${formatDate(delivery)}`}</p>
      )}
    </div>
  )
}