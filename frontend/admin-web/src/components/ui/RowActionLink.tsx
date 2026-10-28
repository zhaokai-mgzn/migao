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
 * - **行内动作**（跳到该行的详情 / 明细）⇒ 本组件。
 *
 * ⚠️ **销售订单列表的行内动作已不再是本组件**（issue #8011，2026-10-28）：那张表的行内收成
 * 「1 个主行动按钮 + 1 个「⋯」菜单」，菜单项另用菜单语义（`role="menuitem"`）。本组件仍是
 * 「行内**文字**动作」的单一形态 —— 现有消费点 = 作业看板（`src/app/(dashboard)/production/page.tsx`）。
 * ⚠️ 库位面板（`src/components/stock/WarehouseLocationPanel.tsx`）在 issue #8038 已改走
 * `RowActions`（1 主行动 + ⋯ 菜单），**不再是**本组件的消费点。
 *
 * ⚠️ **边界（照实登记）**：全仓还有几处**同款字面量**的链接（员工 / 售后等，各自带 `text-sm`
 * 或 `disabled:` 变体）。`ProductTable` 与库位面板已在 issue #8038 改走 `RowActions`；
 * 余下几处仍是「行内文字动作」的**待迁移项**（另单跟踪），本组件暂不改它们。
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
