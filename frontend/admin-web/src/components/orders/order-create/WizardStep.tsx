/**
 * 下单页的**折叠骨架**（可折叠头部 + 向导步骤）—— issue #8725 第一档切片产物。
 *
 * 单一职责：折叠/展开的**唯一实现**（`button` 语义 + `aria-expanded` + chevron）。
 * 两处使用者共用它：向导步骤（issue #4511）与商品卡组头（issue #4679）。
 */
import { ChevronDown, ChevronRight } from 'lucide-react'
import { FONT_PX_11 } from '@/lib/design-tokens'

/**
 * **可折叠头部**（issue #4679）—— 折叠开关的**唯一实现**：`button` 语义 + `aria-expanded`
 * + chevron（键盘可达：回车 / 空格都触发）。两处使用者共用它 —— **向导步骤**（#4511）与
 * **商品卡组头**（#4679）；用户口径「别新造一套折叠组件」。
 *
 * - `trailing`：**始终**渲染的右侧内容（组头的金额）；
 * - `summary`：**仅收起时**渲染的摘要（向导步骤的已选结果 / 组头的尺寸·米数）
 *   —— 收起 ≠ 看不出这是哪一行。
 */
export function CollapsibleHeader({
  open,
  onToggle,
  className = '',
  summary,
  trailing,
  children,
}: {
  open: boolean
  onToggle: () => void
  className?: string
  /** 收起时显示的摘要 */
  summary?: React.ReactNode
  /** 始终显示的右侧内容 */
  trailing?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className={`flex items-center gap-2 text-left ${className}`}
    >
      {children}
      <span className="ml-auto flex items-center gap-1.5 min-w-0">
        {!open && summary && (
          <span className="text-xs text-neutral-500 truncate">{summary}</span>
        )}
        {trailing}
        {open ? (
          <ChevronDown className="w-4 h-4 text-neutral-400 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-neutral-400 shrink-0" />
        )}
      </span>
    </button>
  )
}

/**
 * **向导步骤**（issue #4511，用户口径「加个由上到下的向导，参考苹果商店的购买商品选配」）。
 *
 * 三条形态约定：
 * - **平级**：每步是兄弟，不嵌套（特殊选项不再挂在工艺规格下面）；
 * - **编号 + 收起摘要**：收起时显示已选结果（一眼看到当前配置）；
 * - **手风琴**：由调用方持有「当前展开的是第几步」⇒ 展开一步自动收起同级其它。
 */
export function WizardStep({
  step,
  title,
  summary,
  badges,
  aside,
  open,
  onToggle,
  children,
}: {
  step: number
  title: string
  /** 收起时显示的已选摘要 */
  summary?: string
  /**
   * 标题旁的**就地徽标**（issue #4658）：① 尺寸与数量那行显示系统识别结果 ——
   * 商家**填尺寸时**就看得见提示（不必翻到②工艺规格才发现）。展开/收起都渲染。
   */
  badges?: React.ReactNode
  /**
   * **标题右侧的推导细节栏**（2026-09-30 第五批；用户逐字「这里的一整趴如何推算的细节，放到
   * 用料与规格（系统推导）这个标题的**右侧空白区域**，放哪里你自己决定」）——
   * 展开时与标题**同一行**、排在它右边（把标题行那块一直空着的横向空间用起来）。
   *
   * ⚠️ 它必须是标题按钮的**兄弟**、不能塞进 `<button>`：栏里有 `<details>`、深链与按钮，
   * 嵌进 button 就是**非法嵌套**（同 `CollapsibleHeader` 的既有约束 —— 那里也只为这个原因
   * 把「删除」放成了兄弟节点）。
   * ⚠️ 只在**展开**时渲染：收起 = 这一步的细节整体看不见（与改前一致；摘要在标题行照旧显示，
   * 且标题按钮此时是 `w-full` ⇒ 摘要不被挤成一条缝）。
   */
  aside?: React.ReactNode
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  const header = (
    <CollapsibleHeader
      open={open}
      onToggle={onToggle}
      // `shrink-0`：与右侧栏同处一行时按内容宽（标题不参与伸缩）；展开但无右侧栏时照旧 `w-full`
      className={open && aside ? 'shrink-0 py-2.5' : 'w-full py-2.5'}
      summary={summary}
    >
      <span
        className={
          `inline-flex items-center justify-center w-5 h-5 shrink-0 rounded-full ${FONT_PX_11} font-semibold ` +
          (open ? 'bg-primary-600 text-white' : 'bg-neutral-100 text-neutral-500')
        }
      >
        {step}
      </span>
      <span className="text-sm font-medium text-neutral-700 shrink-0">{title}</span>
      {badges}
    </CollapsibleHeader>
  )
  const withAside = open && aside
  return (
    <div
      // ⚠️ 展开且**带右侧栏**时，这一步的容器**自己**就是那一行（`flex-wrap` + 主体 `w-full` 换行）——
      // 页面既有助手 `stepSection()` 用 `btn.closest('div')` 取「这一步的容器」（断言它含**主体**），
      // 多套一层行容器 ⇒ 它只拿得到标题 ⇒ `orders-new-auto-features` 整片红（实测）。
      className={
        'border-t border-neutral-100 first:border-t-0' +
        (withAside ? ' flex flex-wrap items-start gap-x-6' : '')
      }
      data-testid={`wizard-step-${step}`}
    >
      {header}
      {withAside && (
        <div className="min-w-0 flex-1 pt-2.5" data-testid={`wizard-aside-${step}`}>
          {aside}
        </div>
      )}
      {open && <div className="w-full pb-4">{children}</div>}
    </div>
  )
}
