'use client'

import { cn } from '@/lib/utils'
import { Search, RotateCcw, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'
import { ReactNode, useState } from 'react'

/** 一格筛选：`label` 左置、控件右展（与「下单时间」那类**整体控件组**用 `span` 跨轨） */
export interface SearchFieldSpec {
  /** React key（同一面板内唯一；也是判据定位用的稳定锚） */
  key: string
  /** 字段名（左置标签；宽度统一 `w-[4.5em]` ⇒ 各行列起点对齐） */
  label: string
  /** 控件本体：`<input>` / `<select>` / 一个 `flex` 容器（如「起 至 止」日期区间） */
  control: ReactNode
  /** 跨轨数（如日期区间跨 2 轨）；默认 1 */
  span?: 1 | 2
}

interface SearchPanelProps {
  fields: SearchFieldSpec[]
  onSearch: () => void
  onReset?: () => void
  /** 「刷新」是**列表动作**、`onSearch`/`onReset` 是**筛选动作** ⇒ 有它时按钮行会插一条细分隔线 */
  onRefresh?: () => void
  loading?: boolean
  /** 透传 `data-testid`（默认 `search-area` —— 仓内页面级判据以它定位搜索区，见 PageCard 的同名说明） */
  testId?: string
  className?: string
  /**
   * **可折叠**（issue #7388；opt-in —— 不传 = 存量页面行为逐字不变）。
   *
   * 为什么需要：筛选字段一多（订单页 7 个 + 按钮行），常驻面板吃掉 3~4 行，
   * 把首屏真正要看的列表推到折叠线以下（`migao-dev-flow` §31 P1「常驻面克制」）。
   * 收起态 = **一行**：标题 + 摘要 + 展开入口。
   *
   * 🔴 折叠态下 `fields` 与按钮行**不渲染进 DOM**（不是 CSS 隐藏 / `hidden` 属性）——
   * 常驻面不得随字段数增长占高度，且看不见的东西不该留在无障碍树上。
   */
  collapsible?: boolean
  /** 初始收起态；仅 `collapsible` 时生效，默认 `true`（本仓口径：筛选区默认收起） */
  defaultCollapsed?: boolean
  /**
   * 收起态的一行摘要（当前**已生效**的筛选）：缺省不渲染摘要行。
   * 只在收起时渲染 —— 展开后字段本身就说明了在筛什么，再念一遍就是重复（§31 P2）。
   * 🔴 传**已提交**的筛选值，不要传表单草稿（草稿还没生效，写上去会骗人）。
   */
  summary?: ReactNode
}

const CONTROL_CLASS =
  'w-full h-9 px-3 rounded border border-neutral-300 bg-white text-sm text-neutral-900 ' +
  'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ' +
  'placeholder:text-neutral-400'

/**
 * 列表页**通用筛选卡片**。
 *
 * ## 为什么要有这个原语（issue #7007）
 *
 * 用户 2026-10-16 反馈「订单页精美、其它页平淡」。诊断到的可归因差异之一：
 * **同一个「筛选区」在仓里有三种互不相同的形态**，而共享件只有一个
 * （`frontend/admin-web/src/components/ui/SearchBar.tsx`，且只有 2 页在用）：
 *
 * | 形态 | 出现在 | 问题 |
 * |---|---|---|
 * | `SearchBar`（`bg-gray-50` + `flex flex-wrap items-end` + `min-w-[200px]`） | 客户 / 知识库 | **`gray` 不在 token 里**（本仓暖亚麻是 `neutral`）⇒ 冷灰底在全暖色界面里显脏；`flex-wrap` 的换行点与格宽随视口漂 |
 * | 手写 `grid-cols-1 md:grid-cols-2` | 商品 / 员工 | 标签**顶置**、列轨道 2 档 |
 * | 手写 `grid-cols-1 md:grid-cols-2 2xl:grid-cols-4` | 订单 | 标签**左置**、列轨道 3 档 —— 用户认为「精美」的正是这一版 |
 *
 * ⇒ 把订单页那一版（`issue #5880` 打磨出来的：**单一响应式 grid** ⇒ 行与行天然对齐；每格
 * `min-w-0` ⇒ 换行点与宽度由**轨道**给、不靠 `min-w-[…]` 撑，不会把控件压扁）抽成原语。
 *
 * ## 可折叠（issue #7388）
 *
 * 用户 2026-10-20 在订单页截图上圈出整块筛选区：「这里的查询区域默认折叠起来」。
 * 折叠做成**原语能力**（`collapsible`），不在页面里手拼一套 —— 否则「同一个筛选区多种形态」
 * 这条病根会沿着折叠再长出来一次。形态与 `ConfigReadinessBar` 的「常驻一行摘要」同族。
 *
 * ## 判据形态（会红）
 *
 * - 本文件用到的筛选控件一律 `h-9`（= 36px）：桌面后台主控件下限来自
 *   `frontend/admin-web/scripts/design-baseline-geometry-probe.mjs` 的 `GEOMETRY_LIMITS.minControlHeight`；
 * - 不得出现 Tailwind 默认冷灰族（`gray-*`）—— 由 `frontend/admin-web/tests/unit/warm-token-palette-guard.test.ts` 判红；
 * - 单元格高度不自撑：控件写 `w-full`，宽度由轨道给；
 * - 折叠态 `fields` / 按钮行在 DOM 里**取不到**；展开后逐个回来（`aria-expanded` 两态）。
 *
 * ## 边界（如实登记，§19.1）
 *
 * - 原语**不持有筛选状态**：`fields[].control` 由调用方渲染（受控 / 非受控、防抖、URL 同步都是页面的事）
 *   —— 原语只负责版式。这是**有意**的：把状态收进来会强迫所有页面改用同一套 state 形状，
 *   那是行为变更，不是视觉统一；
 * - `collapsible` 只多持有**展开/收起**这一个 UI 态（不落 URL、不持久化：刷新回到默认收起）；
 * - 「哪些字段该出现在第一行/跨轨」仍由页面定（`span` 只是版式提示）；
 * - 不判「该有几个筛选字段」—— 那是产品口径。
 */
export default function SearchPanel({
  fields,
  onSearch,
  onReset,
  onRefresh,
  loading,
  testId = 'search-area',
  className,
  collapsible = false,
  defaultCollapsed = true,
  summary,
}: SearchPanelProps) {
  // 只持有「展开/收起」这一个 UI 态；不传 `collapsible` 时恒展开（存量页面零变化）。
  const [expanded, setExpanded] = useState(!collapsible || !defaultCollapsed)

  const body = (
    <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-4 gap-x-6 gap-y-4">
      {fields.map((field) => (
        <div
          key={field.key}
          className={cn('flex items-center gap-3 min-w-0', field.span === 2 && 'md:col-span-2')}
        >
          {/* 定宽 + 右对齐（issue #5880 的口径）：`min-w` 只是下限、实际宽度仍随内容变
              ⇒ 各格 label 宽度不同、行间起点参差。4.5em 装得下最长 label「下单时间」（4 个中文字）。
              🔴 issue #7238（用户 2026-10-18 截图「这里太紧凑了」）：4.5em 只是**下限** ——
              「姓名/手机号」是 5 个字符，纯定宽 + `whitespace-nowrap` 会让文字**溢出**定宽盒、
              吃掉与控件之间的间隙 ⇒ 标签贴着输入框。`min-w-fit` 让长标签**把控件推远**，
              4 字标签仍按 4.5em 对齐（两个诉求同时成立）。 */}
          <label className="text-sm text-neutral-600 whitespace-nowrap shrink-0 text-right w-[4.5em] min-w-fit">
            {field.label}
          </label>
          <div className="flex-1 min-w-0">{field.control}</div>
        </div>
      ))}

      {/* 按钮行：`col-span-full` ⇒ 任何列数下都独占一行；`justify-end` ⇒ 主操作在右。
          「刷新」是列表动作、与筛选动作**分层**（细分隔线），相对顺序 = 查询 → 重置 ｜ 刷新。 */}
      <div className="col-span-full flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onSearch}
          disabled={loading}
          className="h-9 px-5 rounded bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 active:bg-primary-800 disabled:opacity-50 transition-colors inline-flex items-center gap-1.5 whitespace-nowrap"
        >
          <Search className="w-4 h-4" />
          查询
        </button>
        {onReset && (
          <button
            type="button"
            onClick={onReset}
            disabled={loading}
            className="h-9 px-5 rounded bg-white text-neutral-700 text-sm font-medium border border-neutral-300 hover:bg-neutral-50 active:bg-neutral-100 disabled:opacity-50 transition-colors inline-flex items-center gap-1 whitespace-nowrap"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            重置
          </button>
        )}
        {onRefresh && (
          <span className="flex items-center border-l border-neutral-200 pl-3 ml-1">
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              title="刷新列表"
              aria-label="刷新"
              className="h-9 px-3 rounded bg-white text-neutral-700 text-sm font-medium border border-neutral-300 hover:bg-neutral-50 active:bg-neutral-100 disabled:opacity-50 transition-colors inline-flex items-center gap-1.5 whitespace-nowrap"
            >
              <RefreshCw className="w-4 h-4" />
              刷新
            </button>
          </span>
        )}
      </div>
    </div>
  )

  if (!collapsible) {
    return (
      <div
        data-testid={testId}
        className={cn('bg-white rounded-lg border border-neutral-200 shadow-card p-5', className)}
      >
        {body}
      </div>
    )
  }

  return (
    <div
      data-testid={testId}
      className={cn('bg-white rounded-lg border border-neutral-200 shadow-card', className)}
    >
      {/* 常驻面 = **一行**（标题 + 摘要 + 入口）。`button` 语义 + `aria-expanded` ⇒ 键盘回车/空格可达
          （与 `ConfigReadinessBar` 同形态，不另造一套折叠）。 */}
      <button
        type="button"
        data-testid="search-panel-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        // 收起态必须**看得出还能查**（用户 2026-10-20：「折叠状态需要引导用户可以打开区域查询」）：
        // 右侧是描边按钮形态的「展开筛选」（不是一行弱文字），再补一条 title 给悬停/读屏。
        title={expanded ? '收起筛选区' : '展开筛选区，按字段组合查询'}
        className={cn(
          'w-full flex items-center gap-2 px-5 py-3 text-left hover:bg-neutral-50 rounded-lg',
          expanded && 'rounded-b-none'
        )}
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-neutral-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-neutral-400 shrink-0" />
        )}
        <span className="text-sm font-medium text-neutral-900 shrink-0">筛选</span>
        {!expanded && summary && (
          <span data-testid="search-panel-summary" className="text-sm text-neutral-500 truncate min-w-0">
            {summary}
          </span>
        )}
        {/* 收起 = **按钮形态**的入口（描边 + 放大镜）：收起态只有一行文字时，商家读不出「这里能点、
            点了能查」；展开后同一位置降级成弱文字「收起」（主操作是查询，不与它抢视觉）。 */}
        <span
          data-testid="search-panel-toggle-label"
          className={cn(
            'ml-auto shrink-0 inline-flex items-center gap-1.5',
            expanded
              ? 'text-sm text-primary-600'
              : 'h-8 px-3 rounded-lg border border-neutral-300 bg-white text-sm font-medium text-primary-700'
          )}
        >
          {expanded ? '收起' : <><Search className="w-4 h-4" />展开筛选</>}
        </span>
      </button>

      {/* 折叠态 body **不渲染**（不是 CSS 隐藏）⇒ 页面高度不随字段数增长 */}
      {expanded && <div className="px-5 pb-5">{body}</div>}
    </div>
  )
}

/** 与 `SearchPanel` 同源的控件类名（页面自渲染控件时写它，保证高度 / 焦点环 / 边框逐值一致） */
export { CONTROL_CLASS as SEARCH_CONTROL_CLASS }
