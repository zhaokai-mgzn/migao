'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ChevronLeft, ChevronRight, Search, Star, Pin } from 'lucide-react'
import { useAuthStore } from '@/store/auth'
import { cn } from '@/lib/utils'
import { gold } from '@/lib/brand-palette'
import Logo from '@/components/ui/Logo'
// #3002: 菜单配置单源化 —— menuGroups/standaloneItems 移至 @/config/menu，
// 与岗位权限弹窗共用，保证「权限分配」展示的菜单与真实侧边栏一致
// 🔴 2026-10-17（issue #7087）：一级项现有**三个席位**（语义见 `@/config/menu` 的三个 `standalone*` 数组）——
//   · `standaloneHeadItems`（**最前席位**，本轮新增的「经营看板」）：渲染在**所有分组之前**，
//     因此它也是**登录落点**（`landingPath()` = 第一个可见菜单项，issue #6758）；
//   · `standaloneTopItems`（**尾席位**，「商品管理」「企业基础设置」）：渲染在
//     `STANDALONE_TOP_AFTER_GROUP_KEY` 那个组之后（用户 2026-10-06 裁定：大菜单项并列）；
//     席位组不可见时**不跳到最前**，而是挂在「当前可见分组」的末尾
//     （口径的唯一实现 = `splitGroupsAtTopItemSlot`）—— 一级项绝不跟着消失；
//   · `standaloneItems`（**尾部独立项**，「通知中心」）：渲染在所有分组之后。
// 三个席位都**不进「常用（收藏）」**（一级项没有星标、已一屏可见）。
import {
  menuGroups,
  standaloneHeadItems,
  standaloneTopItems,
  standaloneItems,
  STANDALONE_TOP_AFTER_GROUP_KEY,
  type MenuItem,
  type MenuGroup,
} from '@/config/menu'
// issue #5271: 图标注册表独立成模块 —— 原内联 `iconMap[...] || BarChart3` 的静默回落
// 现在有判据（tests/unit/lib/menu-icons.test.ts）
import { resolveMenuIcon } from '@/config/menu-icons'
// issue #5271: 过滤/高亮/搜索/展开判定抽成纯函数（可对「全部菜单项 × 全部路由」穷举断言）
// 本轮新增「常用（收藏）」一族纯函数（持久化 + 上限 + 无效 key 丢弃 + 权限过滤都在那边）
import {
  filterMenuItems,
  visibleMenuGroups,
  splitGroupsAtTopItemSlot,
  resolveActivePath,
  resolveActiveGroupKey,
  initialExpandedGroups,
  loadPinned,
  savePinned,
  togglePinned,
  isPinned,
  pinnedGroup,
  PINNED_GROUP_KEY,
  PINNED_MAX,
} from '@/lib/menu-nav'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
  /** 移动端抽屉是否展开（issue #5271）；桌面端忽略此值 */
  mobileOpen?: boolean
  /** 移动端点击遮罩/菜单项后关闭抽屉（issue #5271） */
  onMobileClose?: () => void
  /** 打开命令面板（⌘K，issue #5271） */
  onOpenSearch?: () => void
}

/**
 * 侧边栏（issue #5271 重设计）。
 *
 * ## 四项交互（用户 2026-09-23 裁定）
 *
 *   ① **分组默认只展开「当前路由所在组」** —— 21 项不再一次全摊开；组标题带项数徽标，
 *      「东西没丢」一眼可见；找不到就用 ⌘K；
 *   ② **高亮自动展开所在组** —— 路由变化 ⇒ 自动展开该组（用户手动展开的其它组不受影响；
 *      手动**收起**当前组后不会被立刻顶开，见下方 effect 的收敛条件）；
 *   ③ **折叠态分组可见** —— 图标栏仍按组渲染「组图标 + 分隔线」锚点（`title` = 组名），
 *      不再是重设计前那种「一根分隔线、分组信息全丢」；
 *   ④ **移动端抽屉** —— 小屏是浮层（`-translate-x-full` / `translate-x-0`）+ 遮罩，
 *      桌面端才是常驻栏（`lg:translate-x-0`）⇒ 不再恒宽挤压内容区。
 *
 * ## 视觉
 *
 *   组标题去掉 `uppercase`（对中文完全无效）与叠在标题上的第二个图标；
 *   折叠指示由「换图标」改为**同一 chevron 旋转**（状态变化更连续）。
 */
export default function Sidebar({
  collapsed,
  onToggle,
  mobileOpen = false,
  onMobileClose,
  onOpenSearch,
}: SidebarProps) {
  const pathname = usePathname()
  const { user } = useAuthStore()

  // 企业 Logo 加载失败标记：URL 失效/过期时回退到观星台默认 Logo，避免空白
  const [logoFailed, setLogoFailed] = useState(false)

  // 企业 Logo 变化时重置失败标记
  useEffect(() => {
    setLogoFailed(false)
  }, [user?.tenantLogo])

  // ── 权限过滤（纯函数，issue #5271）──
  // 🔴 2026-10-17（issue #7087）：过滤条件由三条降为两条 —— `briefingToggle` 随「每日简报」菜单项
  // 一起撤掉（企业开关从此只驱动经营看板上的结论卡），**侧边栏不再为此发一次配置请求**。
  const filterOpts = { permissions: user?.permissions || [], roles: user?.roles }
  const groups = visibleMenuGroups(menuGroups, filterOpts)
  const standalone = filterMenuItems(standaloneItems, filterOpts)
  // 最前席位一级项（「经营看板」，渲染在**所有分组之前** —— 用户 2026-10-17 裁定）
  const standaloneHead = filterMenuItems(standaloneHeadItems, filterOpts)
  // 尾席位一级项（「商品管理」「企业基础设置」）；`filterMenuItems` 对空数组安全（返回空表）
  const standaloneTop = filterMenuItems(standaloneTopItems, filterOpts)

  // ── 高亮：最长前缀胜出（沿用重设计前的口径）──
  const activePath = resolveActivePath(
    [
      ...groups.flatMap((g) => g.children.map((i) => i.path)),
      ...standaloneHead.map((i) => i.path),
      ...standaloneTop.map((i) => i.path),
      ...standalone.map((i) => i.path),
    ],
    pathname,
  )
  const isActive = (path: string) => activePath === path

  const activeGroupKey = resolveActiveGroupKey(groups, pathname)

  // ── 「常用（收藏）」──
  // 初值恒为空表：**首帧与 SSR 一致**，读 localStorage 放到 useEffect（避免 hydration 不一致）。
  const [pinned, setPinned] = useState<string[]>([])
  useEffect(() => {
    setPinned(loadPinned())
  }, [])

  const onTogglePin = (key: string) => {
    setPinned((prev) => {
      const next = togglePinned(prev, key)
      // 满额时 `togglePinned` 原样返回（不静默顶掉已有项）⇒ 这里就不落盘、不改态，
      // 由标题上的 `n/6` 计数向用户说明「已经满了」。
      if (next.length === prev.length && !prev.includes(key)) return prev
      savePinned(next)
      return next
    })
  }

  // 「常用」区（`null` ⇒ 整区不渲染：清单为空，或钉住的项一项都不可见）
  // 🔴 #5877：**一级项不进「常用」**（它没有星标、一屏可见）⇒ 解析面只含组内项 + 尾部独立项
  const favorites = pinnedGroup(groups, standalone, pinned, filterOpts)

  // 🔴 pinned 与普通分组**分开渲染**（不是往 groups 里塞一个合成组）：
  // `resolveActiveGroupKey` / `initialExpandedGroups` 都按「分组」语义工作，
  // 把「常用」混进 groups 会让它把当前路由的所在组抢走（被钉项在「常用」与域内各有一份）。
  const renderItem = (item: MenuItem, opts: { alwaysShowPin: boolean }) => {
    const Icon = resolveMenuIcon(item.icon)
    const active = isActive(item.path)
    const pinnedNow = isPinned(pinned, item.key)
    // 星标：常态隐藏（`opacity-0`）以免 21 项每行都多一个图标；当前项与 hover 时可见。
    // iOS 无 hover ⇒ 当前项那一枚恒显（「想钉的大多是自己现在在用的」）。
    // 「常用」区里**恒显**（否则没法取消）。
    const showPin = !collapsed && (opts.alwaysShowPin || active || pinnedNow)
    return (
      <Link
        key={item.key}
        href={item.path}
        onClick={onMobileClose}
        data-menu-key={item.key}
        className={cn(
          'group/item relative flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors',
          active
            ? 'bg-primary-600 text-white shadow-sm'
            : 'text-neutral-300 hover:bg-white/5 hover:text-white',
          collapsed && 'justify-center px-2',
        )}
        title={collapsed ? item.name : undefined}
      >
        {active && (
          <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
        )}
        <Icon className="h-5 w-5 flex-shrink-0" />
        {!collapsed && <span className="flex-1 truncate">{item.name}</span>}
        {!collapsed && (
          <button
            type="button"
            data-testid={`sidebar-pin-${item.key}`}
            data-pinned={pinnedNow ? 'true' : 'false'}
            aria-label={pinnedNow ? `取消常用：${item.name}` : `加入常用：${item.name}`}
            aria-pressed={pinnedNow}
            title={pinnedNow ? '取消常用' : '加入常用'}
            onClick={(e) => {
              // 星标是 Link 内的按钮 ⇒ 必须阻止跳转（点它只钉、不导航）
              e.preventDefault()
              e.stopPropagation()
              onTogglePin(item.key)
            }}
            className={cn(
              'flex-shrink-0 rounded p-0.5 transition-opacity',
              'text-neutral-300 hover:bg-white/10 hover:text-white',
              active && 'text-white',
              showPin ? 'opacity-100' : 'opacity-0 group-hover/item:opacity-100',
            )}
          >
            <Star className={cn('h-3.5 w-3.5', pinnedNow && 'fill-current')} />
          </button>
        )}
      </Link>
    )
  }

  // ── 分组展开态：初值 = 只展开当前所在组；路由变化 ⇒ 自动展开新所在组 ──
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() =>
    initialExpandedGroups(groups, activeGroupKey),
  )

  useEffect(() => {
    if (!activeGroupKey) return
    // 收敛条件：已展开则该引用原样返回（不触发重渲染）；用户手动收起后不会被反复顶开
    setExpandedGroups((prev) => (prev[activeGroupKey] ? prev : { ...prev, [activeGroupKey]: true }))
  }, [activeGroupKey])

  const toggleGroup = (key: string) => {
    setExpandedGroups((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  // ── 一级项的插入位（#5877）：head 含席位组（含）及其之前，tail 是其余组 ──
  // ⚠️ 切分口径的**唯一实现**在 `menu-nav.splitGroupsAtTopItemSlot`（与 `flattenMenu` 同源，
  // 保证「侧边栏渲染顺序」与「⌘K 索引顺序」不会各漂各的）。
  const { head, tail } = splitGroupsAtTopItemSlot(groups, STANDALONE_TOP_AFTER_GROUP_KEY)

  const renderGroup = (group: MenuGroup) => {
    const GroupIcon = resolveMenuIcon(group.icon)
    const isExpanded = !!expandedGroups[group.key]

    return (
      <div key={group.key} data-group-key={group.key} className="mb-4">
        {collapsed ? (
          // 折叠态：分组信息**不再丢失** —— 组图标锚点（title = 组名）+ 细分割线
          <div
            data-testid={`sidebar-group-anchor-${group.key}`}
            title={group.name}
            className="mb-1 flex flex-col items-center gap-1 pt-2"
          >
            <span className="h-px w-6 bg-white/10" />
            <GroupIcon className="h-3.5 w-3.5 text-neutral-500" />
          </div>
        ) : (
          <button
            type="button"
            data-testid={`sidebar-group-toggle-${group.key}`}
            aria-expanded={isExpanded}
            onClick={() => toggleGroup(group.key)}
            className="group mb-1 flex w-full cursor-pointer items-center gap-2 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-white/5"
          >
            <GroupIcon className="h-3.5 w-3.5 flex-shrink-0 text-neutral-500 transition-colors group-hover:text-neutral-300" />
            <span className="flex-1 text-xs font-medium tracking-wide text-neutral-400 transition-colors group-hover:text-neutral-200">
              {group.name}
            </span>
            {/* 项数徽标：收起时也知道组里有几项（「东西没丢」） */}
            <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] leading-none text-neutral-500">
              {group.children.length}
            </span>
            <ChevronRight
              className={cn(
                'h-3.5 w-3.5 flex-shrink-0 text-neutral-600 transition-transform group-hover:text-neutral-300',
                isExpanded && 'rotate-90',
              )}
            />
          </button>
        )}

        {(collapsed || isExpanded) && (
          <div className="space-y-0.5">
            {group.children.map((item: MenuItem) =>
              // 星标常态隐藏（`opacity-0` + hover/当前项才显），避免每行都多一个图标
              renderItem(item, { alwaysShowPin: false }),
            )}
          </div>
        )}
      </div>
    )
  }

  // ── 一级项块（**直达**项，无分组语义）──
  // 席位语义见 `@/config/menu` 的三个 `standalone*` 数组（最前席位 / 尾席位 / 尾部独立项）。
  // 视觉 = **板块入口**规格（与组头同级：`text-xs font-medium tracking-wide` + `h-3.5 w-3.5` 图标），
  // **仍是**一整行可点的 `<Link>`（直达、无展开语义 ⇒ 右端那枚 ChevronRight **不旋转**）；
  // 🔴 **不渲染星标**：一级项不可收藏（否则「常用」里会出现第二条一模一样的入口）。
  // `separator`：块前要不要画分隔线 —— 最前席位在顶部（紧接「常用」）不画；尾席位画
  // （仓内既有同款 `border-t border-white/5`，与尾部独立项前那条一致）。
  const renderStandaloneBlock = (
    items: MenuItem[],
    testId: string,
    opts: { separator: boolean },
  ) => {
    if (items.length === 0) return null
    return (
      <div
        data-testid={testId}
        className={cn('my-2 space-y-0.5', opts.separator && 'border-t border-white/5 pt-1')}
      >
        {items.map((item) => {
          const Icon = resolveMenuIcon(item.icon)
          const active = isActive(item.path)
          return (
            <Link
              key={item.key}
              href={item.path}
              onClick={onMobileClose}
              data-menu-key={item.key}
              className={cn(
                'relative flex items-center gap-2 rounded-md px-3 py-1.5 transition-colors',
                active
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'text-neutral-400 hover:bg-white/5 hover:text-neutral-200',
                collapsed && 'justify-center px-2',
              )}
              title={collapsed ? item.name : undefined}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
              )}
              <Icon className="h-3.5 w-3.5 flex-shrink-0" />
              {!collapsed && (
                <span className="flex-1 text-xs font-medium tracking-wide">{item.name}</span>
              )}
              {/* 不旋转 = 「直达」；组头那枚会 `rotate-90`（可展开）—— 语义在此分叉 */}
              {!collapsed && (
                <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-neutral-600" />
              )}
            </Link>
          )
        })}
      </div>
    )
  }

  return (
    <aside
      data-testid="sidebar"
      className={cn(
        'fixed left-0 top-0 z-50 flex h-full w-60 flex-col bg-[#171e30] transition-transform duration-300',
        collapsed ? 'lg:w-16' : 'lg:w-60',
        // 移动端抽屉：默认藏在屏幕左侧外；桌面端恒在左侧
        mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
      )}
    >
      {/* Logo 区域 */}
      <div className={cn('flex items-center border-b border-white/5', collapsed ? 'h-14 justify-center' : 'h-16 py-3 px-4')}>
        <div className="flex items-center gap-3 overflow-hidden">
          {/* 企业 Logo（「企业基础信息」设置）优先，未设置或加载失败时回退观星台默认 Logo */}
          {user?.tenantLogo && !logoFailed ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={user.tenantLogo}
              alt="企业 Logo"
              className="h-8 w-8 flex-shrink-0 rounded-lg object-cover"
              onError={() => setLogoFailed(true)}
            />
          ) : (
            <Logo size="small" />
          )}
          {/* 企业身份块（issue #7476）：这里只回答「我在哪家企业」，平台品牌署名在侧边栏底部 */}
          {!collapsed && (
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold leading-tight text-white">
                {user?.tenantName || '观星台'}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 菜单搜索入口（⌘K，issue #5271）—— 21 项不再靠眼扫 */}
      {collapsed ? (
        <button
          type="button"
          data-testid="sidebar-search-trigger"
          onClick={onOpenSearch}
          title="搜索菜单"
          className="mx-auto my-2 flex h-9 w-9 items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-white/5 hover:text-white"
        >
          <Search className="h-4 w-4" />
        </button>
      ) : (
        <button
          type="button"
          data-testid="sidebar-search-trigger"
          onClick={onOpenSearch}
          className="mx-3 my-2 flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-xs text-neutral-400 transition-colors hover:bg-white/10 hover:text-white"
        >
          <Search className="h-3.5 w-3.5" />
          <span className="flex-1 text-left">搜索菜单</span>
          <kbd className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-neutral-500">⌘K</kbd>
        </button>
      )}

      {/* 导航菜单 */}
      <nav className="flex-1 overflow-y-auto px-2 py-1">
        {/* ── 「常用（收藏）」（本轮 2026-09-29）── 用户自选、钉在**最顶部** */}
        {favorites && (
          <div data-group-key={PINNED_GROUP_KEY} className="mb-4">
            {collapsed ? (
              <div
                data-testid={`sidebar-group-anchor-${PINNED_GROUP_KEY}`}
                title={favorites.name}
                className="mb-1 flex flex-col items-center gap-1 pt-2"
              >
                <Pin className="h-3.5 w-3.5 text-neutral-500" />
              </div>
            ) : (
              // 恒展开（不提供折叠）——「常用」一旦收起就失去它存在的意义
              <div
                data-testid={`sidebar-group-label-${PINNED_GROUP_KEY}`}
                className="mb-1 flex w-full items-center gap-2 rounded-md px-3 py-1.5"
              >
                <Pin className="h-3.5 w-3.5 flex-shrink-0 text-neutral-500" />
                <span className="flex-1 text-xs font-medium tracking-wide text-neutral-400">
                  {favorites.name}
                </span>
                {/* `n/上限`：满额时用户一眼知道为什么再钉不进去（`togglePinned` 是拒绝、不顶替） */}
                <span
                  data-testid="sidebar-pinned-count"
                  className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] leading-none text-neutral-500"
                >
                  {favorites.items.length}/{PINNED_MAX}
                </span>
              </div>
            )}
            <div className="space-y-0.5">
              {favorites.items.map((item) => renderItem(item, { alwaysShowPin: true }))}
            </div>
          </div>
        )}

        {/* ── 最前席位一级项（「经营看板」，2026-10-17 issue #7087）──
            用户逐字：「经营看板直接作为一级菜单，移除工作台，这样用户一进来就很直观的看到经营看板了」
            ⇒ 渲染在**所有分组之前**。为什么不与「商品管理」并列在尾席位：`landingPath()` = 第一个
            可见菜单项（issue #6758）—— 尾席位会让登录落点变成「在线接待」。
            ⚠️ 它同样**不进「常用」**（一级项没有星标、已一屏可见 —— #5877 口径对三个席位一致）。 */}
        {renderStandaloneBlock(standaloneHead, 'sidebar-standalone-head', { separator: false })}

        {/* ── head 组（含尾席位插入位那个组）── */}
        {head.map((group) => renderGroup(group))}

        {/* ── 尾席位一级项（「商品管理」「企业基础设置」）──
            位置 = **所有分组之后**（用户 2026-10-06 裁定：大菜单项并列；见 `STANDALONE_TOP_AFTER_GROUP_KEY`），
            分隔线**有两种情形**（不要只按一种理解）：
              · **常态**（席位组 `org-center` 可见：admin / 持 `system:view` 的岗位）⇒ 这条线是
                「**组织管理组 ↔ 一级项**」的分隔线；
              · **回落情形**（席位组被权限整组过滤掉 —— 实测七个种子岗位里只有 admin 持 `system:view`
                ⇒ 这是**多数岗位**看到的形态）⇒ 一级项挂在**当前可见分组的末尾**，
                这条线成为「**最后一个可见组 ↔ 一级项**」的分隔线。
              ⚠️ 回落方向是「挂到末尾」**不是**「跳到最前」：旧口径（席位组不可见 ⇒ 排到第一行）
                会让「商品管理」对多数岗位跑到菜单最上方，与「沉底」的裁定正好相反
                —— 口径的唯一实现 = `frontend/admin-web/src/lib/menu-nav.ts` 的 `splitGroupsAtTopItemSlot`。 */}
        {renderStandaloneBlock(standaloneTop, 'sidebar-standalone-top', { separator: true })}

        {/* ── tail 组（一级项之后的其余组）── */}
        {tail.map((group) => renderGroup(group))}

        {/* 一级独立菜单项 */}
        {standalone.length > 0 && !collapsed && (
          <div className="my-2 border-t border-white/5" />
        )}
        <div className="space-y-0.5">
          {standalone.map((item) => renderItem(item, { alwaysShowPin: false }))}
        </div>
      </nav>

      {/* 页脚（issue #7476 / #7480 / #7482 / #7487 / #7491）：**星标 + 品牌署名**。
          #7491 起公司法定名**撤出侧边栏**（用户 2026-10-22：「我们的公司名？放左下角用户会有想法的吧」
          —— 侧边栏是租户的地盘，不挂供应商名）⇒ 公司名改到顶栏用户菜单「关于观星台」按需查看。
          用户 2026-10-22：「移除米高的叫法，观星台=米高了，这样太丑了，你设计的好看些」
          ⇒ 去掉 MIGAO（同一个名字说两遍）与圆角小牌（方框把署名做成了「按钮」形状），
          上「观星台」、下「杭州词元通达科技有限公司」—— 公司名成为 lockup 的第二行。
          企业名缺失时品牌已占顶部主位 ⇒ 此处不渲染；折叠态只留展开图标（桌面端）。 */}
      <div data-testid="sidebar-footer" className="relative border-t border-white/5 px-3 py-2.5">
        {/* 页脚细线在品牌一侧透一层金（不是整条金线 —— 只是让署名有个「压印」的落点） */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 -top-px h-px bg-gradient-to-r from-gold-600/50 via-gold-600/10 to-transparent"
        />
        <div className={cn('flex items-center', collapsed && 'justify-center')}>
          {!collapsed && user?.tenantName && (
            <div
              data-testid="sidebar-brand"
              title="观星台 · AI 经营平台"
              className="flex items-center gap-2.5"
            >
              {/* 四角星 = 「观星」的星；刻意不用通用 sparkle 图标（那是 AI 语义，不是品牌语义） */}
              <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
                <path
                  d="M12 1.6c.72 5.34 4.34 8.96 9.68 9.68-5.34.72-8.96 4.34-9.68 9.68-.72-5.34-4.34-8.96-9.68-9.68C7.66 10.56 11.28 6.94 12 1.6Z"
                  fill={gold[400]}
                />
              </svg>
              <span
                data-testid="sidebar-brand-name"
                className="text-[13px] font-medium leading-none tracking-[0.2em] text-[#ded7c7]"
              >
                观星台
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              'hidden items-center justify-center rounded-md p-1.5 transition-colors lg:flex',
              'text-neutral-500 hover:bg-white/5 hover:text-white',
              collapsed ? 'mx-auto' : 'ml-auto',
            )}
            title={collapsed ? '展开侧边栏' : '收起侧边栏'}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <>
                <ChevronLeft className="h-4 w-4" />
                <span className="ml-1 text-[12px]">收起</span>
              </>
            )}
          </button>
        </div>
      </div>
    </aside>
  )
}