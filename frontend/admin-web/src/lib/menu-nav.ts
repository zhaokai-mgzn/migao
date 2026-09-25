// 侧边栏导航的**纯函数**（issue #5271）
//
// ## 为什么把它们从 `Sidebar.tsx` 里抽出来
//
// 重设计前，「权限过滤 / 高亮选中 / 分组展开」三件事全部内联在组件里：
// 只能靠**渲染整个 Sidebar** 才能验证，而渲染又依赖 `useAuthStore`、`next/navigation`、
// lucide 白名单三个替身 ⇒ 判据脆、且无法对「同一路由下哪个项高亮」做表驱动穷举。
// 抽成纯函数后，判据可以直接对**全部菜单项 × 全部路由**跑（见 `tests/unit/lib/menu-nav.test.ts`）。
//
// 行为**逐字沿用**重设计前的实现（不是重写口径）：
//   · 过滤三条件 = `adminOnly` ∧ `briefingToggle` ∧ `permissionCode`；
//   · 高亮 = **最长前缀胜出**（`/dashboard` 同时命中 `/` 与 `/dashboard`）；
//   · 空组剔除（组内一项不剩 ⇒ 整组不渲染）。

import type { MenuGroup, MenuItem } from '@/config/menu'

export interface MenuFilterOptions {
  permissions: string[]
  roles?: string[]
  /** 智能每日经营简报的企业开关（issue #3468）；未传 = 关（与重设计前 Sidebar 的初值一致） */
  briefingEnabled?: boolean
}

/** 权限判定：无码 = 全员可见；`*` = 超管通配 */
export function hasPermission(code: string | undefined, permissions: string[]): boolean {
  if (!code) return true
  if (permissions.includes('*')) return true
  return permissions.includes(code)
}

/** 单个菜单项是否可见（三条件） */
export function isItemVisible(item: MenuItem, opts: MenuFilterOptions): boolean {
  if (item.adminOnly && !(opts.roles || []).includes('admin')) return false
  if (item.briefingToggle && !opts.briefingEnabled) return false
  return hasPermission(item.permissionCode, opts.permissions)
}

/** 过滤后的菜单项（保持原顺序） */
export function filterMenuItems(items: MenuItem[], opts: MenuFilterOptions): MenuItem[] {
  return items.filter((item) => isItemVisible(item, opts))
}

/** 过滤后的分组（**空组剔除** —— 组内一项不剩 ⇒ 整组不渲染） */
export function visibleMenuGroups(groups: MenuGroup[], opts: MenuFilterOptions): MenuGroup[] {
  return groups
    .map((g) => ({ ...g, children: filterMenuItems(g.children, opts) }))
    .filter((g) => g.children.length > 0)
}

/** 路由是否命中某菜单项（`/dashboard` 额外认 `/`；其余按「自身或子路径」前缀匹配） */
/**
 * **旧深链 → 菜单项 path** 的别名（issue #4439）。
 *
 * 为什么需要：路由迁移（#4357）把列表页从 `/processing-orders` 迁到 `/production`，
 * 但**生产明细子页的真实路径仍是旧深链** `/processing-orders/{id}/production`
 * ⇒ 只按「自身或子路径」匹配时 `activePath = null` ⇒ **侧边栏一项都不高亮**
 * （用户看到的是"不知道自己在哪一页"）。
 *
 * 口径：别名**只在匹配这一侧**生效（不进入 `resolveActivePath` 的「最长」比较集），
 * 因此不会改变既有「两项同时命中要取最长」的行为。
 */
const LEGACY_PATH_ALIASES: Record<string, readonly string[]> = {
  '/production': ['/processing-orders'],
}

export function matchesRoute(itemPath: string, current: string): boolean {
  if (itemPath === '/dashboard') {
    return current === '/dashboard' || current === '/'
  }
  if (current === itemPath || current.startsWith(itemPath + '/')) return true
  return (LEGACY_PATH_ALIASES[itemPath] ?? []).some(
    (alias) => current === alias || current.startsWith(alias + '/'),
  )
}

/**
 * 当前路由对应的**唯一**激活路径：所有命中项里取**最长**的一条。
 *
 * 为什么是「最长」而不是「首个命中」：`/production` 与 `/production/pool` 会同时命中
 * `/production/pool` ⇒ 不取最长会出现**两个项同时高亮**（重设计前就有的口径，此处沿用）。
 */
export function resolveActivePath(paths: string[], pathname: string | null): string | null {
  if (!pathname) return null
  const hits = paths.filter((p) => matchesRoute(p, pathname))
  if (hits.length === 0) return null
  return hits.reduce((a, b) => (b.length > a.length ? b : a))
}

/**
 * 当前路由落在哪个分组（用于「高亮自动展开所在组」，issue #5271）。
 *
 * 🔴 **必须与 `resolveActivePath` 同源**：先按「最长前缀」定出**唯一激活项**，再取它所属的组。
 * 曾经的实现是「取**首个**含命中项的组」，被实测证伪（issue #5271 的自动验收抓出）：
 * `/production/remnants`（余料台账，属**仓储与物料**组）会被**生产管理**组的 `/production`
 * （生产看板）**前缀命中**，而生产管理组在数组里更靠前 ⇒ 展开的是生产管理组、仓储与物料组收起，
 * **当前项被高亮却看不见**（违反交互契约②）。穷举 20 项实测：只有 `/production/remnants`
 * 与 `/production/saving-board` 两条命中该形态（`/production/processing-fees` 是同族但属重定向页）。
 */
export function resolveActiveGroupKey(groups: MenuGroup[], pathname: string | null): string | null {
  if (!pathname) return null
  const active = resolveActivePath(
    groups.flatMap((g) => g.children.map((c) => c.path)),
    pathname,
  )
  if (!active) return null
  for (const g of groups) {
    if (g.children.some((c) => c.path === active)) return g.key
  }
  return null
}

/** 展开态初值：**只展开当前路由所在组**（其余收起）——把 21 项从「一次全摊开」变成「一屏扫得完」 */
export function initialExpandedGroups(groups: MenuGroup[], activeGroupKey: string | null): Record<string, boolean> {
  return Object.fromEntries(groups.map((g) => [g.key, g.key === activeGroupKey]))
}

export interface FlatMenuItem extends MenuItem {
  /** 所属组 key（独立项为空串） */
  groupKey: string
  /** 所属组名（独立项为空串） */
  groupName: string
}

/** 拍平（命令面板 ⌘K 用）：分组项按组顺序在前，独立项在后 */
export function flattenMenu(groups: MenuGroup[], standalone: MenuItem[]): FlatMenuItem[] {
  const fromGroups = groups.flatMap((g) =>
    g.children.map((c) => ({ ...c, groupKey: g.key, groupName: g.name })),
  )
  const fromStandalone = standalone.map((c) => ({ ...c, groupKey: '', groupName: '' }))
  return [...fromGroups, ...fromStandalone]
}

/**
 * 命令面板检索（issue #5271）。
 *
 * 命中面 = 菜单名 ∪ 组名 ∪ `keywords`（拼音首字母 / 常见叫法），大小写不敏感。
 * 排序 = 「菜单名前缀命中」优先，其次「菜单名包含」，再次「别名/组名命中」，
 * 同档保持**菜单自身顺序**（稳定 ⇒ 结果可预期，也便于判据断言）。
 */
export function searchMenu(items: FlatMenuItem[], query: string): FlatMenuItem[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  const rank = (item: FlatMenuItem): number => {
    const name = item.name.toLowerCase()
    if (name.startsWith(q)) return 0
    if (name.includes(q)) return 1
    if ((item.keywords || []).some((k) => k.toLowerCase().includes(q))) return 2
    if (item.groupName.toLowerCase().includes(q)) return 3
    return -1
  }
  return items
    .map((item, index) => ({ item, index, r: rank(item) }))
    .filter((x) => x.r >= 0)
    .sort((a, b) => (a.r !== b.r ? a.r - b.r : a.index - b.index))
    .map((x) => x.item)
}