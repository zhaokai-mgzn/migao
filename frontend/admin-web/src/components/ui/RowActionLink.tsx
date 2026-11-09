'use client'

/**
 * 「单据列表」**行内动作**的唯一形态（链接式按钮）—— `Button` 的姊妹件。
 *
 * ## 为什么有它（2026-10-17 用户裁定）
 *
 * 用户逐字：「这里的操作行内的按钮样式能否保持让全部单据统一向订单保持一致，
 * 不要有多种风格设计」。当时销售订单（`OrderTable`）的行内动作是**文字链接**，
 * 而作业看板用的是 `Button variant="secondary" size="sm"` 的**描边按钮** ——
 * 同一件事（行内跳转）两种长相，还各占一行高度把「操作」列撑宽。
 *
 * ⇒ 样式收成**一处定义**：形态 = 销售订单那一版（主题色文字 + hover 下划线），
 * 各列表页引用本组件，不再各抄一份 class 串（抄一份就是第二份会漂的口径）。
 * `OrderTable` 原先的本地 `ActionLink`、作业看板的两个 `Button` 均并入这里。
 *
 * ## 与 `Button` 的分工（写新页面时的取值口径）
 *
 * - **页面级动作**（保存 / 查询 / 新建 / 刷新）⇒ `Button`；
 * - **行内动作**（跳到该行的详情 / 明细 / 次要写操作）⇒ 本组件。
 *
 * ⚠️ **2026-11-09 起全站列表页平铺**：用户逐字「操作一列：把商品对应的可操作按钮直接展示出来，
 * 不要收在“...”里面」「检查一下观星台的其他所有列表页，操作列按钮逐条平铺、不再收进「⋯」」
 * ⇒ 主行动 = `Button variant="ghost" size="sm"`，**其余动作逐条本组件同屏**。
 * 「主行动 + ⋯ 菜单」原语已退役；判据 = `scripts/row-action-flat-scan.mjs` +
 * `tests/unit/row-action-flat-ledger.json`（`flat_surfaces` 正向锚）。
 *
 * ## 变体（issue #7082 收口时扩展：每个变体都对应一个**真实**消费点，不留投机 API）
 *
 * | prop | 取值 | 为什么需要（消费点） |
 * |---|---|---|
 * | `size` | `xs` / `sm` / `md`(默认) | 行内常见 `text-sm`（售后列表）、`text-xs`（员工资料面板）—— 硬并会改字号 |
 * | `emphasis` | `true` | 行**标识列**（员工「姓名」那一格）改前是 `font-medium` |
 * | `tone` | `primary`(默认) / `danger` | 加工项面板的行内「删除」是红字（改前 `text-red-500 hover:text-red-600`） |
 * | `disabledStyle` | `faint`(默认) / `keep` | 员工「姓名」在无写权限时改前**保持字色**、只是不响应（`disabled:cursor-default`）；`faint` = 淡色 + 禁止光标 |
 *
 * 🔴 **不许在调用点写 `className` 覆盖**（本组件故意**不暴露** `className`）：绕过变体就等于没收口，
 * 第二份会漂的口径又回来了。
 *
 * ## 类级判据（issue #7082）
 *
 * 本组件的视觉规格（`text-primary-600` + `hover:text-primary-700` + `hover:underline`）在
 * `frontend/admin-web/src/**` 里**只许出现这一处**，副本（带 `text-sm` / `text-xs` / 禁用态变体都算）
 * ⇒ 具名判红。判据本体 = `frontend/admin-web/scripts/row-action-link-scan.mjs`，
 * 台账 = `frontend/admin-web/tests/unit/row-action-link-ledger.json`，
 * 守卫 = `frontend/admin-web/tests/unit/row-action-link-single-source-guard.test.ts`。
 */

/** 字号变体：`md` = 跟随容器（表格自带 `text-sm`），`sm` / `xs` = 显式覆盖 */
export type RowActionLinkSize = 'xs' | 'sm' | 'md'

export default function RowActionLink({
  children,
  onClick,
  disabled,
  size = 'md',
  emphasis = false,
  tone = 'primary',
  disabledStyle = 'faint',
  title,
  'data-testid': testId,
}: {
  children: React.ReactNode
  onClick: () => void
  /** 不可用时不响应（观感见 `disabledStyle`） */
  disabled?: boolean
  /** 字号：`sm` = `text-sm`（表格行内）、`xs` = `text-xs`（面板小动作）、`md` = 跟随容器 */
  size?: RowActionLinkSize
  /** 行标识列（如员工姓名）用强调字重（`font-medium`） */
  emphasis?: boolean
  /** 色族：`primary`（默认）/ `danger`（行内删除这类破坏性动作，红字） */
  tone?: 'primary' | 'danger'
  /**
   * 禁用态观感（只影响**已被禁用**时；不影响可用态）：
   * - `faint`（默认）= 淡色 + 禁止光标 —— 表达「这个动作现在不可用」；
   * - `keep` = 保持可用态字色、仅不响应 + 默认光标 —— 用于**行标识**（员工姓名）：
   *   无写权限时姓名照旧是姓名，不能变成灰色占位。
   */
  disabledStyle?: 'faint' | 'keep'
  /** 禁用时的原因（原生 `title`，悬停可见）—— 平铺后与旧的 ⋯ 菜单项同一口径 */
  title?: string
  'data-testid'?: string
}) {
  const sizes: Record<RowActionLinkSize, string> = { xs: 'text-xs', sm: 'text-sm', md: '' }
  const tones = {
    primary: 'text-primary-600 hover:text-primary-700',
    danger: 'text-red-500 hover:text-red-600',
  } as const
  // ⚠️ 下面这一串是本组件的**视觉规格**，也是类级扫描判据比对的那一串（见头注释）
  const enabled = `${tones[tone]} hover:underline transition-colors ${sizes[size]}`.trim()
  const disabledClass =
    disabledStyle === 'keep'
      ? `${tones[tone]} hover:underline transition-colors cursor-default ${sizes[size]}`.trim()
      : 'text-neutral-400 cursor-not-allowed'

  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      title={title}
      // 行内动作不得触发行点击（列表行将来若加整行点击，这里不会误触）
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={[disabled ? disabledClass : enabled, emphasis ? 'font-medium' : '']
        .filter(Boolean)
        .join(' ')}
    >
      {children}
    </button>
  )
}
