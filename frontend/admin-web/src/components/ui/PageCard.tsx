import { cn } from '@/lib/utils'
import { ReactNode } from 'react'

interface PageCardProps {
  /** 内容。**可选** —— 容器本就允许为空（如「加载中」「空态」由内部条件渲染时，
   *  外层在首帧可能没有子节点）。标成必填会让 `React.createElement(PageCard, { padded: false })`
   *  这种**合法**用法报 TS2769（issue #7007 的本包实测踩到）。 */
  children?: ReactNode
  className?: string
  /** 内边距档位：`true` = 自带 `p-5`（默认）；`false` = 由调用方自己管（如内部是整宽表格 + 分页脚） */
  padded?: boolean
  /**
   * 透传 `data-testid`。**必须能透传** ——
   * `frontend/admin-web/src/app/(dashboard)/**` 的页面级判据大量以
   * `data-testid="search-area"` / `"*-empty"` 定位容器；原语不透传就只能退回手写 div。
   */
  testId?: string
}

/**
 * 页内**一级容器**（「整页卡片 → 页内区块」里的后一半）。
 *
 * ## 为什么要有这个原语（issue #7007）
 *
 * 用户 2026-10-16 反馈「只有订单管理的设计精美，其它页面没有这种感觉」。诊断发现外层其实已统一
 * —— `frontend/admin-web/src/app/(dashboard)/layout.tsx` 给所有页面套了同一张整页卡片
 * （`rounded-2xl border shadow-card`）—— 差距全在**卡片内部**：
 *
 * - 内层容器**缺 `shadow-card`**（全仓 15 处只有 `border`）⇒ 与整页卡片同为「白底 + 边框」，
 *   两层视觉权重相同、层级分不开，页面读起来「边框套边框」。订单页之所以清透，正因为它把层级
 *   放在了**阴影**上（外层阴影 / 内层边框）；
 * - 圆角三种写法混用（`rounded` / `rounded-lg` / `rounded-xl`）、内边距两种（`p-5` / `p-6`）
 *   ⇒ 同一屏内区块起点参差。
 *
 * ⇒ 把「页内一级容器」收敛成一个原语：**值只来自 `frontend/admin-web/tailwind.config.ts` 的 token**，
 * 不写任意值、不新造色阶。
 *
 * ## 用到哪些 token（真值源 = tailwind.config.ts，不在这里复制色值）
 *
 * - `bg-white` · `border-neutral-200`（暖亚麻族的中性边框）
 * - `rounded-lg`（= 8px；`design-baseline.md` §1 的圆角基数阶）
 * - `shadow-card`（软分层阴影 `0 1px 2px rgba(36,31,24,.04), 0 4px 16px rgba(36,31,24,.06)`，暖中性色相）
 * - `p-5`（容器内边距统一档）
 *
 * ## 边界（照实登记）
 *
 * - 原语只保证**形态一致**，不保证「好不好看」—— 审美仍由 `migao-dev-flow` §15.7 读图 + 人裁定；
 * - 它**不碰**布局语义：栅格列数、区块顺序、留白大小仍由页面自己定（改原语不该改变任何页面的信息结构）；
 * - 纯展示、**无状态、无事件** ⇒ 不是 `'use client'`（可被服务端组件直接引用）。
 */
export default function PageCard({ children, className, padded = true, testId }: PageCardProps) {
  return (
    <div
      data-testid={testId}
      className={cn(
        'bg-white rounded-lg border border-neutral-200 shadow-card',
        padded && 'p-5',
        className
      )}
    >
      {children}
    </div>
  )
}
