import { cn } from '@/lib/utils'

export interface TableSkeletonProps {
  /** 占位行数 —— 列表页一般传当前 `pageSize`（给 0 / 负数会钳到 1，避免只剩一个表头空壳） */
  rows?: number
  /** 占位列数 —— 与真实表格的列数对齐 */
  columns?: number
  className?: string
}

/**
 * 通用表格骨架（issue #8036）：列表页**加载态**的占位形态。
 *
 * 病灶（2026-10-24 真栈截图 `acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/08-products-list.png`）：
 * 共享 `ui/Table` 的 loading 分支是「一行居中 spinner + 『加载中...』」⇒ 表体空白，
 * 首屏看起来像「这个店没有商品」，而不是「正在取数」。经营看板已在 #8012 改成骨架
 * （灰底 + 脉冲），本原语把同一口径抽成**可被 30+ 列表页复用**的布局件。
 *
 * 契约（判据见 `frontend/admin-web/tests/unit/components/TableSkeleton.test.tsx`）：
 * - `data-testid="table-skeleton"`（每行 = `table-skeleton-row`）；
 * - `rows` / `columns` 可配；
 * - **纯布局**：`textContent === ''` —— 骨架不冒充事实（不写「暂无数据」）、也不给读屏念占位；
 * - 灰底 + `animate-pulse`，零新增依赖（只用既有 `cn`）。
 *
 * ⚠️ 边界（照实登记）：jsdom 只能证「在场 + 无文案 + 行列数 + class 口径」；
 * **骨架行高与真实表格行是否对齐**（视觉）由真机截图复核，单测证不了。
 * 其它列表页本轮**不接线**（等 #8035 审计结果分批做）。
 */
export default function TableSkeleton({ rows = 8, columns = 6, className }: TableSkeletonProps) {
  const rowCount = Math.max(1, rows)
  const columnCount = Math.max(1, columns)

  return (
    <div
      data-testid="table-skeleton"
      // 骨架对读屏没有信息量（只有视觉占位）⇒ 显式隐藏，别念一串空 div
      aria-hidden="true"
      className={cn('w-full overflow-hidden', className)}
    >
      {/* 表头占位：与 `ui/Table` 的 thead 同口径（bg-neutral-50 / px-4 py-3 / 下边框） */}
      <div className="flex gap-4 border-b border-neutral-200 bg-neutral-50 px-4 py-3">
        {Array.from({ length: columnCount }).map((_, i) => (
          <div key={`head-${i}`} className="h-3 flex-1 animate-pulse rounded bg-neutral-200" />
        ))}
      </div>
      {Array.from({ length: rowCount }).map((_, r) => (
        <div
          key={`row-${r}`}
          data-testid="table-skeleton-row"
          className="flex gap-4 border-b border-neutral-100 px-4 py-4"
        >
          {Array.from({ length: columnCount }).map((_, c) => (
            <div key={`cell-${r}-${c}`} className="h-4 flex-1 animate-pulse rounded bg-neutral-100" />
          ))}
        </div>
      ))}
    </div>
  )
}
