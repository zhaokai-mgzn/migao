'use client'

import { useEffect, useRef, useState } from 'react'
import { MoreHorizontal } from 'lucide-react'
import Button from './Button'

/**
 * 表格**行内动作**的唯一形态：`1 个主行动 + 1 个「⋯」菜单`（issue #8011 → #8038 收成共享原语）。
 *
 * ## 为什么必须是原语（而不是每个列表各写一遍）
 *
 * `/orders`（#8011）把行内 4 个同名级文字链收成一个主行动 + ⋯ 菜单之后，形态是对的，
 * 但实现留在 `components/orders/OrderTable.tsx` 里 —— `products`（每行 5 个）与
 * `knowledge`（每行 4 个）仍是平铺文字链（#8035 审计：`≥3 个同级可点` 共 5 页）。
 * 「再抄一份」= 第二份会漂的口径（`RowActionLink` 头注释已登记过同款教训）⇒ 本组件是
 * **那一份实现**：`OrderTable` 也改用它，三个列表从此只有一处菜单行为。
 *
 * ## 判据（会红，见 `tests/unit/components/RowActions.test.tsx`）
 *
 * ① 收起态**菜单项不进 DOM**（`{open && …}`，不是 CSS 隐藏 —— 否则「单屏 80 个可点文本」
 *    只换了长相，`migao-dev-flow` §31 P1 的机器读数会读成没改）；
 * ② `aria-haspopup="menu"` / `aria-expanded` / `role="menu"` / `role="menuitem"` ——
 *    收敛**不得**把动作藏成键盘不可达；
 * ③ `Escape` 与「点外部」都收起；滚动 / 缩放也收起（面板 `fixed` 定位，不收起就与行脱位）；
 * ④ `items` 为空 ⇒ **不渲染触发器**（不摆一个点开是空盒子的「⋯」）。
 *
 * ## 与「主行动」的分工
 *
 * 主行动由调用方经 `children` 传入（它随业务状态派生：订单待付款→收款、商品在架→编辑…），
 * 本组件只管**容器 + 菜单**，绝不猜业务语义。⚠️ `children` 只放**一个**可点元素 ——
 * 类级扫描器 `scripts/row-action-density-scan.mjs` 把「主行动 + 触发器」算作 2 个可点元素，
 * 多传一个就超 `≤2` 的红线。
 *
 * ## 边界（照实登记）
 *
 * - **不接管二次确认**：危险动作（删除 / 下架）只是进菜单，`danger` 只影响文字色 ——
 *   确认弹框仍由页面既有 `Modal` 承担（改容器不改语义，issue #8038 的硬边界）；
 * - 面板 `position: fixed`：本仓的宽表在 `overflow-x-auto` 里（#6717/#6728），绝对定位的子面板
 *   会被横向滚动容器**纵向裁掉**（最后一行的菜单点开就没了）⇒ 用 fixed 脱离裁切；
 * - jsdom 只证**开合与可达性**；菜单的落点 / 遮挡属真机视觉，由集成侧截图复核。
 */
export interface RowActionItem {
  key: string
  /** 菜单项文字（动词开头，§32.2） */
  label: string
  onClick: () => void
  /** 破坏性动作（删除 / 下架…）：红字。**不改变**调用方已有的二次确认 */
  danger?: boolean
}

export interface RowActionsProps {
  items: RowActionItem[]
  /** 主行动（**至多一个**可点元素；不传 = 该行只有 ⋯ 菜单） */
  children?: React.ReactNode
  /** 菜单容器（含触发器）的 `data-testid`；收起态下它仍在 DOM（触发器要在） */
  menuTestId: string
  /** 整格 `data-testid`（页面级判据按行取用） */
  testId?: string
  className?: string
}

export default function RowActions({
  items,
  children,
  menuTestId,
  testId,
  className = 'flex items-center gap-1 whitespace-nowrap',
}: RowActionsProps) {
  /** `null` = 收起；有坐标 = 展开（坐标在**点开的那一刻**量，避免与行脱位） */
  const [anchor, setAnchor] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const open = anchor !== null

  useEffect(() => {
    if (!open) return
    const close = () => setAnchor(null)
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null
      // 触发器自己交给 onClick 处理（否则一次点击会先关后开）
      if (triggerRef.current?.contains(target as Node)) return
      // 面板里的动作同样不在这里关（它的 onClick 自己关，保证动作先执行）
      if (target?.closest?.(`[data-row-menu="${menuTestId}"]`)) return
      close()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    // 表格容器可横滚、页面可竖滚 ⇒ 面板会与行脱位，直接收起（比假装还在正确位置诚实）
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [open, menuTestId])

  const toggle = () => {
    if (open) {
      setAnchor(null)
      return
    }
    const rect = triggerRef.current?.getBoundingClientRect()
    if (!rect) return
    setAnchor({ top: rect.bottom + 4, left: rect.right })
  }

  return (
    <div className={className} data-testid={testId}>
      {children}
      {/* `items` 为空 ⇒ 没有可展开的东西 ⇒ 不渲染触发器（不摆空盒子） */}
      {items.length > 0 && (
        <span className="relative inline-flex" data-testid={menuTestId}>
          {/* 纯图标按钮必须 `aria-label`（§32.2 第 5 条）；行内层级一律 ghost（不用实心主色） */}
          <Button
            ref={triggerRef}
            type="button"
            variant="ghost"
            size="sm"
            className="px-1.5"
            aria-label="更多操作"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={(e) => {
              e.stopPropagation()
              toggle()
            }}
            icon={<MoreHorizontal className="h-4 w-4" />}
          />
          {open && (
            <div
              role="menu"
              data-row-menu={menuTestId}
              style={{ top: anchor.top, left: anchor.left, transform: 'translateX(-100%)' }}
              className="fixed z-50 min-w-[9rem] rounded-lg border border-neutral-200 bg-white py-1 shadow-lg"
            >
              {items.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="menuitem"
                  onClick={(e) => {
                    // 行内动作不得触发行点击（`ui/Table` 支持 `onRowClick`）
                    e.stopPropagation()
                    setAnchor(null)
                    item.onClick()
                  }}
                  className={
                    item.danger
                      ? 'flex w-full items-center px-3 py-1.5 text-left text-sm text-red-600 hover:bg-red-50'
                      : 'flex w-full items-center px-3 py-1.5 text-left text-sm text-neutral-700 hover:bg-neutral-50'
                  }
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </span>
      )}
    </div>
  )
}
