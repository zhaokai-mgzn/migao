import { cn } from '@/lib/utils'
import { ReactNode } from 'react'

interface PageHeaderProps {
  /** 页面名。**必须与侧边栏菜单名 / 顶栏面包屑同名**（issue #5877 的口径：一页不许三名） */
  title: ReactNode
  /** 一句话副标题（可省）。只写**这一页能做什么**，不重复标题、不摆内部标识 */
  subtitle?: ReactNode
  /** 右侧动作区（主操作在最右）。**`canWrite` 类权限门仍在调用方**，原语不判权限 */
  actions?: ReactNode
  className?: string
}

/**
 * 页面头（标题 + 可选副标题 + 右侧动作区）。
 *
 * ## 为什么要有这个原语（issue #7007）
 *
 * 用户 2026-10-16 反馈「只有订单管理的设计精美」。诊断到的可归因差异之一：全仓**没有**页面头共享件，
 * **26 处 `h1` 手写**，长出三种形态 ——
 *
 * - 标题 + 右侧主按钮同一行（`flex items-center justify-between`）：订单 / 知识库 / 发货；
 * - 只有标题、主按钮掉到下面的工具栏行：商品 / 入库单 —— 同一屏里「新增」的位置换了地方；
 * - 字重两支：`font-bold`（分类）vs `font-semibold`（其余 25 处）。
 *
 * 而字号更根本：**26 处全写 `text-xl`（20px）**，而 `frontend/admin-web/src/lib/design-tokens.ts` 的
 * `TYPE_SCALE` **规定 `text-2xl`（24px）才是「页面标题（h1）」，`text-xl` 是「区块标题（h2）」**
 * ⇒ 页面标题与页内区块标题**同档**，层级读不出来。这正是「不够精美」最结构性的一处：
 * 不是缺装饰，是**视觉层级没有建立**。
 *
 * ## 用到哪些 token（真值源 = design-tokens.ts / tailwind.config.ts，不在这里复制值）
 *
 * - 标题：`text-2xl`（24px / 行高 36px / 600）= `TYPE_SCALE` 的 h1 档；色 `text-neutral-900`
 * - 副标题：`text-sm` `text-neutral-500`
 * - 动作区纵向对齐到标题**基线附近**（`items-start` + 标题行高对齐），避免动作按钮在有无副标题时上下跳
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 原语**不吃权限码**：`canWrite ? <Button/> : null` 留在调用方（与 `AccessDenied` 同族口径 ——
 *   原语结构上就没有回显权限码的入口）；
 * - 它不决定「这一页该不该有副标题」；副标题的文案口径见
 *   `docs/design/user-facing-copy-standard.md` 与 `frontend/admin-web/tests/unit/user-copy-jargon-guard.test.ts`；
 * - 纯展示、无状态 ⇒ 非 `'use client'`。
 */
export default function PageHeader({ title, subtitle, actions, className }: PageHeaderProps) {
  return (
    <div className={cn('flex items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold text-neutral-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-neutral-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  )
}
