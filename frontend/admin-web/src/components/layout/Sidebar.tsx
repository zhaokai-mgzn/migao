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
  // issue #8085：过滤后的单成员组按一级项渲染（组名退化后不再画空壳标题）
  promoteSingleItemGroups,
  type MenuRenderBlock,
} from '@/lib/menu-nav'

// ══════════════════════════════════════════════════════════════════════════════
// 三级视觉层次（2026-10-28 用户裁定：「左侧菜单…我感觉不太协调，大菜单字小，叶子菜单字大」）
//
// 修前是**倒过来**的：组标题（「大菜单」）`text-xs` 12px，而组内叶子项 `text-sm` 14px
// ⇒ 越该被看见的层级越小；且**同为一级项**的「商品管理」走组头规格（12px）、
// 「通知中心」走叶子规格（14px）—— 同一层级两种字号。
//
// 修后的口径（**不靠字号造层级**：字号阶梯只有 12/14 两档，且 12px 是文字下限，
// 叶子项不能为了「显小」再降一档）：
//
//   ① **组标题**（含「常用」）= 14px/600 亮色 **纯文字标签**（不再挂图标 —— 组图标与组内项
//      的领域图标本就重复，去掉后「标签 ↔ 条目」靠**缩进**一眼分开；折叠态仍用组图标做锚点）；
//   ② **一级项**（三个席位）= 14px/600 最亮 + 18px 图标 + **36px 行**（比组标题更高 ⇒
//      「可点的目的地」比「分类标签」重）；右端**不挂 chevron**（直达项没有展开语义）；
//   ③ **叶子项** = 14px/400 次级亮度 + 16px 图标（原 20px 偏重）+ **32px 行**，左内距
//      `pl-7`（28px）⇒ 三级缩进锚点：10（标签）/ 38（一级项）/ 56（叶子）。
//
// 判据（会红）：`tests/unit/components/Sidebar.test.tsx` 的「视觉层次」用例
// —— 组标题/一级项 `text-sm`（不再是 `text-xs`）+ 叶子项仍 `text-sm`；
// 一级项行高 `h-9` > 叶子 `h-8`；菜单标题面里只有序号徽标用 `text-xs`。
// ══════════════════════════════════════════════════════════════════════════════

/** 组标题 / 「常用」标签行（**无图标**；32px） */
const SECTION_ROW = 'flex h-8 w-full items-center gap-2 rounded-md px-2.5 text-left'
const SECTION_LABEL = 'flex-1 text-sm font-semibold transition-colors'
/** 计数徽标（组内项数 / 「常用」n/6）：**菜单标题面**里唯一的 `text-xs`（搜索框那枚属控件文案，不在菜单行） */
const SECTION_COUNT = 'text-xs leading-none text-neutral-600'
/** 一级项行（36px，比组标题更高 ⇒ 目的地重于标签） */
const TOP_ROW = 'group/item relative flex h-9 items-center gap-2.5 rounded-md px-2.5 transition-colors'
const TOP_LABEL = 'flex-1 truncate text-sm font-semibold'
/** 叶子项行（32px；`pl-7` = 三级缩进里的最内层） */
const LEAF_ROW =
  'group/item relative flex h-8 items-center gap-2 rounded-md pl-7 pr-2.5 transition-colors'

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
  // ── 星标按钮（叶子项与尾部独立项共用）──
  // 星标常态隐藏（`opacity-0`）以免每行都多一个图标；当前项与 hover 时可见。
  // iOS 无 hover ⇒ 当前项那一枚恒显（「想钉的大多是自己现在在用的」）。
  // 「常用」区里**恒显**（否则没法取消）。一级项（最前 / 尾席位）不可收藏 ⇒ 不渲染它。
  const renderPinButton = (item: MenuItem, opts: { alwaysShow: boolean; active: boolean }) => {
    const pinnedNow = isPinned(pinned, item.key)
    const visible = opts.alwaysShow || opts.active || pinnedNow
    return (
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
          // 🔴 issue #8085：星标是 `<a>` 的**兄弟**节点（原来是 `<a>` 的子元素 = 无效 HTML，
          // 键盘会在链接里再落一次焦点）⇒ 绝对定位盖在行尾，链接右侧留 `pr-9` 让位。
          'absolute right-2.5 top-1/2 -translate-y-1/2 flex-shrink-0 rounded p-0.5 transition-opacity',
          'text-neutral-400 hover:bg-white/10 hover:text-white',
          opts.active && 'text-white',
          visible ? 'opacity-100' : 'opacity-0 group-hover/item:opacity-100',
        )}
      >
        <Star className={cn('h-3.5 w-3.5', pinnedNow && 'fill-current')} />
      </button>
    )
  }

  // ── 叶子项（组内项 / 「常用」区）── 三级里最内层：32px 行、16px 图标、`pl-7` 缩进
  const renderItem = (item: MenuItem, opts: { alwaysShowPin: boolean }) => {
    const Icon = resolveMenuIcon(item.icon)
    const active = isActive(item.path)
    return (
      // wrapper 承载 hover 组与相对定位：星标是链接的**兄弟**（#8085 a11y），
      // 行内其它元素（图标 / 文字 / 当前项指示条）仍在链接里 ⇒ `nav a[data-menu-key]` 的既有判据不变。
      <div key={item.key} className="group/item relative">
        <Link
          href={item.path}
          onClick={onMobileClose}
          data-menu-key={item.key}
          aria-current={active ? 'page' : undefined}
          className={cn(
            LEAF_ROW,
            // 让位给绝对定位的星标（未折叠时才渲染星标）
            !collapsed && 'pr-9',
            active
              ? 'bg-primary-600 font-medium text-white shadow-sm'
              : 'text-neutral-300 hover:bg-white/5 hover:text-neutral-50',
            collapsed && 'justify-center px-2',
          )}
          title={collapsed ? item.name : undefined}
        >
          {active && (
            <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
          )}
          <Icon
            className={cn('h-4 w-4 flex-shrink-0', active ? 'text-white' : 'text-neutral-500')}
          />
          {!collapsed && <span className="flex-1 truncate text-sm">{item.name}</span>}
        </Link>
        {!collapsed && renderPinButton(item, { alwaysShow: opts.alwaysShowPin, active })}
      </div>
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

  // 🔴 issue #8085：**过滤后**只剩 1 项的组 ⇒ 渲染成一级项（不画空壳组标题）。
  // 只改形态：位置 / ⌘K 顺序 / 权限树都不动（判据 = `menu-nav.test.ts` 的 8 岗位投影）。
  const renderBlocks = (blocks: MenuRenderBlock[]) =>
    blocks.map((block) =>
      block.kind === 'group' ? (
        // `MenuRenderBlock` 的 `items` 与 `MenuGroup` 的 `children` 同构（一个纯数据的形状差异）
        renderGroup({ key: block.key, name: block.name, icon: block.icon, children: block.items })
      ) : (
        // 提升项自己是组内项 ⇒ **仍可收藏**（#5877 的「一级项不进常用」只约束三个席位）
        <div key={block.key} data-group-key={block.key} className="mb-1">
          {renderStandaloneItem(block.item, { withPin: true })}
        </div>
      ),
    )

  const renderGroup = (group: MenuGroup) => {
    const GroupIcon = resolveMenuIcon(group.icon)
    const isExpanded = !!expandedGroups[group.key]
    // 组内含当前路由 ⇒ 组标题提亮（收起时也知道「你在这一组」）
    const isActiveGroup = group.key === activeGroupKey

    return (
      <div key={group.key} data-group-key={group.key} className="mb-3">
        {collapsed ? (
          // 折叠态：分组信息**不再丢失** —— 组图标锚点（title = 组名）+ 细分割线
          // 🔴 组图标**只在这里**渲染（展开态是纯文字标签，见 SECTION_ROW 的注释）
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
            className={cn(SECTION_ROW, 'group mb-0.5 cursor-pointer hover:bg-white/5')}
          >
            <span
              className={cn(
                SECTION_LABEL,
                isActiveGroup ? 'text-neutral-100' : 'text-neutral-200',
                'group-hover:text-white',
              )}
            >
              {group.name}
            </span>
            {/* 项数徽标：收起时也知道组里有几项（「东西没丢」） */}
            <span className={SECTION_COUNT}>{group.children.length}</span>
            <ChevronRight
              className={cn(
                'h-3.5 w-3.5 flex-shrink-0 text-neutral-600 transition-transform group-hover:text-neutral-400',
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

  // ── 一级项（三个席位**同一套视觉**）──
  // 36px 行、18px 图标、14px/600 最亮，右端**不挂 chevron**（直达项没有展开语义，那枚符号留给「可展开的组」）。
  // 🔴 2026-10-28：修前「商品管理 / 企业基础设置」走组头规格（12px）、「通知中心」走叶子规格（14px）
  // —— 同一层级两种字号，正是用户所说「不协调」的来源之一。
  const renderStandaloneItem = (item: MenuItem, opts: { withPin: boolean }) => {
    const Icon = resolveMenuIcon(item.icon)
    const active = isActive(item.path)
    return (
      <div key={item.key} className="group/item relative">
        <Link
          href={item.path}
          onClick={onMobileClose}
          data-menu-key={item.key}
          aria-current={active ? 'page' : undefined}
          className={cn(
            TOP_ROW,
            opts.withPin && !collapsed && 'pr-9',
            active
              ? 'bg-primary-600 text-white shadow-sm'
              : 'text-neutral-50 hover:bg-white/5 hover:text-white',
            collapsed && 'justify-center px-2',
          )}
          title={collapsed ? item.name : undefined}
        >
          {active && (
            <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-white/90" />
          )}
          <Icon className="h-[18px] w-[18px] flex-shrink-0" />
          {!collapsed && <span className={TOP_LABEL}>{item.name}</span>}
        </Link>
        {/* 只有「尾部独立项」（通知中心）可收藏；最前 / 尾席位的一级项不进「常用」（#5877） */}
        {!collapsed && opts.withPin && renderPinButton(item, { alwaysShow: false, active })}
      </div>
    )
  }

  // ── 一级项块（**直达**项，无分组语义）──
  // 席位语义见 `@/config/menu` 的三个 `standalone*` 数组（最前席位 / 尾席位 / 尾部独立项）。
  // 视觉 = 一级项规格（见上）；`separator`：块前要不要画分隔线 —— 最前席位在顶部紧接「常用」
  // 不画；尾席位 / 尾部独立项画（仓内既有同款 `border-t border-white/5`）。
  // `withPin`：只有尾部独立项（通知中心）可收藏 —— 一级项不可收藏（否则「常用」里会出现
  // 第二条一模一样的入口）。
  const renderStandaloneBlock = (
    items: MenuItem[],
    testId: string,
    opts: { separator: boolean; withPin?: boolean },
  ) => {
    if (items.length === 0) return null
    return (
      <div
        data-testid={testId}
        className={cn('my-2 space-y-0.5', opts.separator && 'border-t border-white/5 pt-1')}
      >
        {items.map((item) => renderStandaloneItem(item, { withPin: !!opts.withPin }))}
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
                className={cn(SECTION_ROW, 'mb-0.5')}
              >
                <span className={cn(SECTION_LABEL, 'text-neutral-200')}>{favorites.name}</span>
                {/* `n/上限`：满额时用户一眼知道为什么再钉不进去（`togglePinned` 是拒绝、不顶替） */}
                <span data-testid="sidebar-pinned-count" className={SECTION_COUNT}>
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
        {renderBlocks(promoteSingleItemGroups(head))}

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
        {renderBlocks(promoteSingleItemGroups(tail))}

        {/* 尾部独立项（「通知中心」）：同属一级项 ⇒ 与两个席位**同一套视觉**（可收藏 ⇒ withPin） */}
        {renderStandaloneBlock(standalone, 'sidebar-standalone-tail', {
          separator: !collapsed,
          withPin: true,
        })}
      </nav>

      {/* 页脚（issue #7476 / #7480 / #7482 / #7487 / #7491）：**星标 + 品牌署名**。
          #7491 起公司法定名**撤出侧边栏**（用户 2026-10-22：「我们的公司名？放左下角用户会有想法的吧」
          —— 侧边栏是租户的地盘，不挂供应商名）⇒ 公司名改到顶栏用户菜单「关于观星台」按需查看。
          用户 2026-10-22：「移除米高的叫法，观星台=米高了，这样太丑了，你设计的好看些」
          ⇒ 去掉 MIGAO（同一个名字说两遍）与圆角小牌（方框把署名做成了「按钮」形状），
          上「观星台」、下「杭州词元通达科技有限公司」—— 公司名成为 lockup 的第二行。
          企业名缺失时品牌已占顶部主位 ⇒ 此处不渲染；折叠态只留展开图标（桌面端）。
          🔴 issue #8025（2026-10-28 真栈截图：左下角只剩「N 星台」）：本行是 flex，品牌块与收起按钮
          原先**两边都可压缩**（品牌无 `min-w-0`、名称无截断、按钮无 `shrink-0`）⇒ 窄侧栏里按钮把
          「观星台」压住。⇒ 品牌块 `min-w-0`（可收缩）+ 名称 `truncate`（超出走省略号）+ 按钮 `shrink-0`
          （永远完整可点）。只改可压缩性，折叠逻辑 / 文案 / 侧栏宽度都不动。 */}
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
              className="flex min-w-0 items-center gap-2.5"
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
                className="truncate text-[13px] font-medium leading-none tracking-[0.2em] text-[#ded7c7]"
              >
                观星台
              </span>
            </div>
          )}
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              'hidden shrink-0 items-center justify-center rounded-md p-1.5 transition-colors lg:flex',
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