'use client'

import { useCallback, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { Button } from '@/components/ui'
import { cn } from '@/lib/utils'
import FeeCombinationsPanel from './FeeCombinationsPanel'
import ProcessingItemsPanel from './ProcessingItemsPanel'

/**
 * 加工项管理 /production/processing（issue #4490）
 *
 * **用户裁定（2026-09-19）**：「**加工项**和**加工项费用**这两个我建议**合并成一个菜单**，
 * 也**放到生产管理菜单下**」。
 *
 * 为什么合并：两者是**同一业务域**（加工项及其定价）且共用**同一菜单入口**（节点码自 issue #5291 起 = 读码
 * `production:view`；页内写动作仍是 `processing:manage`），
 * 却被拆在两个菜单组里 —— 「加工项管理」在**商品管理**组、「加工费管理」在**生产管理**组。
 * 加工费组合的定价对象就是加工项本身（`POST /processing-fee-combinations` 的 `items[]` 必须
 * 是加工项目录里活跃的**加工项名**，后端护栏逐条校验），拆开意味着「建组合发现缺加工项要跳到
 * 另一个菜单组去建」——与 #4416（工序库 + 工艺路线）合并的动因同型。
 *
 * 页面形态（**用户总要求**：「别把功能直接平铺到一个页面上，还是需要保证 UI 设计质量的」）：
 * - **两个 tab**（沿用 #4482 在 `/production/routings` 确立的 tab 范式与类名）：
 *   `加工项`（列表 + CRUD + 分类）与 `加工费组合`（选配组合 → 单价 元/米 + 未定价缺口）。
 *   合并仍是**一个菜单入口、一个页面**，只改**内部组织** —— 不是把两个域依次堆进一屏。
 * - **每个 tab 只回答一个问题**：①「我有哪些加工项？」②「哪几个加工项一起用时收多少？」
 * - **一屏一件事**：单 tab 内分主次 —— 主区是列表与主操作（新增加工项 / 新建组合），
 *   次区是只读/低频面（加工分类走**抽屉**、未定价缺口是**辅助告警条**），不做「三块大卡片平铺」。
 * - **空态即引导**（列表空态直接给下一步）、**危险操作二次确认**（删加工项走确认弹窗、
 *   停用组合走 `window.confirm`）、**护栏理由就地展示**（后端 `error.details[].message` 逐条）。
 * - **切 tab 不丢状态**：两栏的 state 都挂在**同一组件**上，条件渲染不重置它们
 *   （形态同 #4482：编辑中的表单 / 勾选中的组合在切走再切回后仍在）。
 *   ⚠️ issue #6585：两栏的功能体已各自抽成独立面板（`ProcessingItemsPanel` / `FeeCombinationsPanel`），
 *   但**本页仍同时挂着两个面板**（非激活那个 `hidden`）⇒ 「切 tab 不丢状态」这条口径**不变**。
 *
 * 契约（冻结，**不得自行发明端点/字段名**）：
 *   GET|POST /api/admin/processing-items            PUT|DELETE /processing-items/{id}
 *   GET|POST /api/admin/processing-categories
 *   GET|POST /api/admin/production/processing-fee-combinations
 *   PUT|DELETE /api/admin/production/processing-fee-combinations/{id}
 *   GET  /api/admin/production/processing-fee-gaps
 *   —— 写端点权限统一 `processing:manage`（以拦截器/后端为准，本页不做显隐分叉）。
 *
 * 两处**故意**不做（沿 #4386 的口径，本单不推翻）：
 * ① **不在前端拼 composition_key**：归一化（与书写顺序无关）是服务端的事 —— 前端自己拼会变成
 *    第二份口径，两边一旦漂移就会出现「页面显示一个组合、库里是另一个」的静默错配。
 * ② **不接线计价**：本页只管配置；下单侧取价（`OrderService.sumProcessingFee` / 下单页 /
 *    ai-agent）不在本包。
 *
 * 旧路径：`/processing` 与 `/production/processing-fees` 都改为重定向到本页
 * （照 #4357 的 `/processing-orders` → `/production`、#4416 的 `/production/operations` →
 * `/production/routings` 先例，旧书签/外部深链不 404）。其中加工费那一条带上 `?tab=fees`
 * 直达「加工费组合」—— 后端未定价提示里的链接（`ProcessingFeeCalculator`）指向的就是旧路径。
 *
 * 🔴 issue #6585（域拆到功能粒度）：本页的**两个 tab 不再是域的导航层**，而只是**同一份功能体的
 * 两种挂载形态**之一 —— 另一个形态是配置指挥台 `/settings`（`<ProcessingBoard embedded />`），
 * 那里域面板**只挂当前域**、**域内不许再套一层导航**。为此功能体已拆成两个可独立挂载的面板，
 * 本页照旧把两个面板都挂上（tab 与 `hidden` 切换），**旧路由行为一字不变**。
 */

/** 两个 tab（用户裁定 2026-09-19）：`items` 加工项 / `fees` 加工费组合 */
const TABS = [
  { key: 'items', label: '加工项' },
  { key: 'fees', label: '加工费组合' },
] as const
type TabKey = (typeof TABS)[number]['key']

/**
 * 挂载形态（issue #6580）：`embedded` = 被配置指挥台（`/settings` 的「加工项与加工费」域）挂载 ——
 * 那种形态下页头标题/副标题不渲染（域面板已给标题与一句话）。独立路由仍按 `embedded=false` 原样渲染。
 *
 * ⚠️ issue #6585：面板的 `embedded` 只关**面板自己那一层区块标题**（「加工项」/「加工费组合」）——
 * 本页把它**原样透传**给两个面板：独立路由（默认）两栏的区块标题照旧在（与拆分前一字不差），
 * 被配置指挥台挂载时去掉（域面板已给「加工项与加工费」标题与一句话，两层标题 = 用户说的「散乱」）。
 */
export default function ProcessingBoard({ embedded = false }: { embedded?: boolean } = {}) {
  const searchParams = useSearchParams()
  /** 默认落在「加工项」（依赖顺序上在前：先有加工项，才能给它组价）；`?tab=fees` 直达第二栏 */
  const [tab, setTab] = useState<TabKey>(searchParams?.get('tab') === 'fees' ? 'fees' : 'items')

  // ── 刷新按钮的两个判据（issue #6585：加载态由面板上报，本页只合并）──
  const [itemsLoading, setItemsLoading] = useState(true)
  const [feesLoading, setFeesLoading] = useState(true)
  const [loadItems, setLoadItems] = useState<() => void>(() => () => {})
  const [loadFees, setLoadFees] = useState<() => void>(() => () => {})

  /**
   * 面板挂载时把自己的取数入口 + 加载态交上来（`useState` 存回调而**不是** `useRef`
   * —— 渲染期读 ref 是 React 的反模式；这里只在点「刷新」/回调触发时读）。
   */
  const registerItems = useCallback((reload: () => void) => setLoadItems(() => reload), [])
  const registerFees = useCallback((reload: () => void) => setLoadFees(() => reload), [])
  const reportItemsLoading = useCallback((loading: boolean) => setItemsLoading(loading), [])
  const reportFeesLoading = useCallback((loading: boolean) => setFeesLoading(loading), [])

  const refreshAll = useCallback(() => {
    loadItems()
    loadFees()
  }, [loadItems, loadFees])

  return (
    <div className="space-y-5 p-6" data-testid="processing-page">
      {/* ── 页头：一件事（这个页面管「加工项」和它的「加工费组合」）── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        {!embedded && (
          <div>
            <h1 className="text-xl font-semibold text-neutral-900">加工项管理</h1>
            <p className="mt-1 text-sm text-neutral-500">管理下单时客户可选的加工服务与加工费 —— <strong>顾客只选配、不报价</strong></p>
          </div>
        )}
        <Button
          variant="secondary"
          size="sm"
          onClick={refreshAll}
          disabled={itemsLoading || feesLoading}
          data-testid="processing-refresh"
        >
          <RefreshCw className={cn('mr-1.5 h-4 w-4', (itemsLoading || feesLoading) && 'animate-spin')} />
          刷新
        </Button>
      </div>

      {/* ── 两个 tab（沿用 #4482 的 tab 范式与类名）── */}
      <div className="flex items-center gap-1 border-b border-neutral-200" role="tablist" data-testid="processing-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            data-testid={`processing-tab-${t.key}`}
            data-state={tab === t.key ? 'active' : 'inactive'}
            onClick={() => setTab(t.key)}
            className={cn(
              '-mb-px border-b-2 px-4 py-2 text-sm transition-colors',
              tab === t.key
                ? 'border-primary-600 font-medium text-primary-700'
                : 'border-transparent text-neutral-500 hover:text-neutral-800',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ══════════════ tab「加工项」：有哪些加工项（CRUD / 分类） ══════════════ */}
      {/* #6585：两栏的功能体各成独立面板，但**都保持挂载**（非激活那个 `hidden`）——
          「切 tab 不丢状态」靠的就是这一点（两个面板的 state 不随切栏重置，形态同 #4482）。 */}
      <div hidden={tab !== 'items'} data-testid="processing-tab-panel-items">
        <ProcessingItemsPanel
          embedded={embedded}
          onLoadingChange={reportItemsLoading}
          onReloadReady={registerItems}
        />
      </div>

      {/* ══════════════ tab「加工费组合」：哪几个加工项一起用时收多少 ══════════════ */}
      <div hidden={tab !== 'fees'} data-testid="processing-tab-panel-fees">
        <FeeCombinationsPanel
          embedded={embedded}
          onLoadingChange={reportFeesLoading}
          onReloadReady={registerFees}
        />
      </div>
    </div>
  )
}
