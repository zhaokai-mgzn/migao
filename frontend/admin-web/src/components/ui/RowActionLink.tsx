'use client'

/**
 * 「单据列表」**行内动作**的唯一形态（链接式按钮）—— `Button` 的姊妹件。
 *
 * ## 为什么有它（2026-10-17 用户裁定）
 *
 * 用户逐字：「这里的操作行内的按钮样式能否保持让全部单据统一向订单保持一致，
 * 不要有多种风格设计」。当时订单列表（`OrderTable`）的行内动作是**文字链接**，
 * 而作业看板用的是 `Button variant="secondary" size="sm"` 的**描边按钮** ——
 * 同一件事（行内跳转）两种长相，还各占一行高度把「操作」列撑宽。
 *
 * ⇒ 样式收成**一处定义**：形态 = 订单列表那一版（主题色文字 + hover 下划线），
 * 各列表页引用本组件，不再各抄一份 class 串（抄一份就是第二份会漂的口径）。
 * `OrderTable` 原先的本地 `ActionLink`、作业看板的两个 `Button` 均并入这里。
 *
 * ## 与 `Button` 的分工（写新页面时的取值口径）
 *
 * - **页面级动作**（保存 / 查询 / 新建 / 刷新）⇒ `Button`；
 * - **行内动作**（跳到该行的详情 / 明细）⇒ 本组件。
 *
 * ⚠️ **边界（照实登记）**：全仓还有几处**同款字面量**的链接（`ProductTable` /
 * 员工 / 售后等，各自带 `text-sm` 或 `disabled:` 变体）—— 本次**有意不并入**
 * （它们有各自的禁用态与字号，硬并会改变观感），未迁移项另单跟踪。
 */
export default function RowActionLink({
  children,
  onClick,
  disabled,
  'data-testid': testId,
}: {
  children: React.ReactNode
  onClick: () => void
  /** 不可用时的形态（淡色 + 不响应；默认可用） */
  disabled?: boolean
  'data-testid'?: string
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      // 行内动作不得触发行点击（列表行将来若加整行点击，这里不会误触）
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
      className={
        disabled
          ? 'text-neutral-400 cursor-not-allowed'
          : 'text-primary-600 hover:text-primary-700 hover:underline transition-colors'
      }
    >
      {children}
    </button>
  )
}
