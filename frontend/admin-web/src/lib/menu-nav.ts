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

// ══════════════════════════════════════════════════════════════════════════════
// 「常用（收藏）」—— 用户自选钉在侧边栏顶部的快捷入口
// ══════════════════════════════════════════════════════════════════════════════
//
// ## 它是什么，不是什么
//
//   · ✅ 它是**用户偏好**（一份有序的菜单项 `key` 清单），不是第四处菜单源 ——
//     渲染时经**同一套**权限过滤（`visibleMenuGroups` / `filterMenuItems`）解析 ⇒ **权限被收回，
//     该项自动从「常用」消失**，结构上不可能出现「收藏了一个不该看的东西」；
//   · ❌ 它**不重排**任何菜单项：钉住的项在它原本的组里**照旧出现**（「常用」是**快捷方式**，
//     不是「搬家」）—— 这样「在域内找它」与「一键直达」两条动线都在，且被钉页面仍是域内高亮项。
//
// ## 两道护栏（消除脏数据）
//
//   · 上限 `PINNED_MAX`（6）—— 超出**拒绝**（不是静默截断），调用方据此给用户可行动提示；
//   · `key` 已不存在（菜单项被删/改名）⇒ 解析时**静默丢弃**，侧边栏不出现死链、不抛错。
//
// ## 边界（如实登记）
//
//   持久化在 `localStorage`（与既有的折叠态 / 浮窗位置同一模式）⇒ **换浏览器 / 换设备不同步**；
//   同步需新建服务端偏好表 + 迁移 + 端点，本轮**有意不做**。

/** 「常用」最多钉几项（超过 ⇒ `togglePinned` 拒绝） */
export const PINNED_MAX = 6

/** localStorage 键（带版本号 ⇒ 将来改格式时可安全换键，不会读到旧形状） */
export const PINNED_STORAGE_KEY = 'migao.sidebar.pinned.v1'

/** 「常用」区在侧边栏里的合成分组 key —— **不是** `menu.ts` 的组，不得与任何组 key 重名 */
export const PINNED_GROUP_KEY = 'pinned'
export const PINNED_GROUP_NAME = '常用'

/** 解析持久化值：只接受「字符串数组」，去重、去空、按首次出现顺序、**截断到上限** */
function parsePinned(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  const out: string[] = []
  for (const v of raw) {
    if (typeof v !== 'string') continue
    const k = v.trim()
    if (!k || out.includes(k)) continue
    out.push(k)
    if (out.length >= PINNED_MAX) break
  }
  return out
}

/**
 * 读取「常用」清单（SSR 安全 + 静默降级）。
 *
 * 读不到（无 localStorage / 被禁 / JSON 坏 / 形状不对）⇒ 一律回**空表**，绝不抛错 ——
 * 一个个性化偏好不该让整个侧边栏白屏。
 */
export function loadPinned(storageKey: string = PINNED_STORAGE_KEY): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return []
    return parsePinned(JSON.parse(raw))
  } catch {
    return []
  }
}

/** 写入「常用」清单（失败静默 —— 隐私模式/配额满时按「本次不生效」处理，不改内存态） */
export function savePinned(keys: string[], storageKey: string = PINNED_STORAGE_KEY): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(parsePinned(keys)))
  } catch {
    /* 静默：偏好写不进去不影响可用性 */
  }
}

/**
 * 切换收藏：**纯函数**（给定现值 + 目标 key ⇒ 新值），I/O 留给调用方。
 *
 * 三态：已钉 ⇒ 取消；未钉且未满 ⇒ 追加到**末尾**（「常用」内顺序 = 用户钉的顺序）；
 * 未钉且已满 ⇒ **原样返回**（调用方据此提示「最多 6 项」；不静默顶掉别人的位置）。
 */
export function togglePinned(current: string[], key: string): string[] {
  const cur = parsePinned(current)
  if (cur.includes(key)) return cur.filter((k) => k !== key)
  if (cur.length >= PINNED_MAX) return cur
  return [...cur, key]
}

/** 该项是否已钉（视图用） */
export function isPinned(pinned: string[], key: string): boolean {
  return pinned.includes(key)
}

/**
 * 按「常用」清单解析出**当前用户真的看得到**的项（顺序 = 用户钉的顺序）。
 *
 * 🔴 两条过滤**必须**都在：① key 已在菜单里不存在（改名/删除）⇒ 丢；② 存在但**当前无权**
 * （或企业开关关掉了「每日简报」）⇒ 丢。漏掉 ② 就是「收藏可以绕过菜单权限」的漏洞。
 */
export function resolvePinnedItems(
  groups: MenuGroup[],
  standaloneTop: MenuItem[],
  standaloneBottom: MenuItem[],
  pinned: string[],
  opts: MenuFilterOptions,
): MenuItem[] {
  const visibleAll = [
    ...groups.flatMap((g) => filterMenuItems(g.children, opts)),
    ...filterMenuItems(standaloneTop, opts),
    ...filterMenuItems(standaloneBottom, opts),
  ]
  const byKey = new Map(visibleAll.map((i) => [i.key, i]))
  return parsePinned(pinned)
    .map((k) => byKey.get(k))
    .filter((i): i is MenuItem => !!i)
}

/**
 * 「常用」合成分组（侧边栏渲染用）。
 *
 * 返回 `null` 表示**整区不渲染**（清单为空，或钉住的项**一项都不可见**）——
 * 空标题比没有标题更糟（用户会以为功能坏了）。
 */
export function pinnedGroup(
  groups: MenuGroup[],
  standaloneTop: MenuItem[],
  standaloneBottom: MenuItem[],
  pinned: string[],
  opts: MenuFilterOptions,
): { key: string; name: string; items: MenuItem[] } | null {
  const items = resolvePinnedItems(groups, standaloneTop, standaloneBottom, pinned, opts)
  return items.length > 0 ? { key: PINNED_GROUP_KEY, name: PINNED_GROUP_NAME, items } : null
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
  /** 所属组 key（一级独立项为空串） */
  groupKey: string
  /** 所属组名（一级独立项为空串） */
  groupName: string
}

/**
 * 拍平（命令面板 ⌘K 用）：**顶部一级项 → 分组项（按组顺序）→ 尾部独立项**。
 *
 * 顺序 == 侧边栏渲染顺序 ⇒ ⌘K 空查询时的「全量索引」与侧边栏逐项对齐（不同源会让用户
 * 在面板里看到的顺序与菜单对不上）。
 *
 * 两级独立项（本轮 2026-09-29 引入）：`standaloneTop` = 渲染在**分组之前**的一级项
 * （如「商品管理」）；`standaloneBottom` = 渲染在**分组之后**的独立项（如「通知中心」）。
 * 两者都**不是**分组，`groupKey`/`groupName` 留空（面板上不显示「组名」标签）。
 */
export function flattenMenu(
  groups: MenuGroup[],
  standaloneTop: MenuItem[] = [],
  standaloneBottom: MenuItem[] = [],
): FlatMenuItem[] {
  const fromGroups = groups.flatMap((g) =>
    g.children.map((c) => ({ ...c, groupKey: g.key, groupName: g.name })),
  )
  const flat = (items: MenuItem[]) => items.map((c) => ({ ...c, groupKey: '', groupName: '' }))
  return [...flat(standaloneTop), ...fromGroups, ...flat(standaloneBottom)]
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