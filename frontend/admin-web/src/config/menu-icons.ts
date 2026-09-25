// 菜单图标注册表（issue #5271 从 `Sidebar.tsx` 抽出的单源）
//
// ## 为什么单独成一个模块
//
// 原实现把 `iconMap` 内联在 `Sidebar.tsx` 里，后果是**漏注册不报错**：
// `iconMap[item.icon] || BarChart3` 会**静默回落**成柱状图 —— 菜单照常渲染、没有任何东西变红，
// 只是图标不对（`remnants-menu-isomorphic.test.tsx` 的注释里逐字记着这个形态）。
// 抽成模块后，「`menu.ts` 出现的每个图标名都在这里注册」是可判定的（纯数据 + 纯函数），
// 判据见 `frontend/admin-web/tests/unit/lib/menu-icons.test.ts`。
//
// ⚠️ **新增图标必须同时登记进 `frontend/admin-web/tests/setup.ts` 的 lucide 白名单** ——
// 该文件用显式白名单 mock 了 `lucide-react`，未登记的图标会让任何渲染 Sidebar 的用例
// **当场抛错**（`No "X" export is defined on the "lucide-react" mock`），不是静默。

import {
  BarChart3,
  Bell,
  Coins,
  BookOpen,
  Boxes,
  Building2,
  Calculator,
  ClipboardCheck,
  ClipboardList,
  Factory,
  Headphones,
  Layers,
  LayoutDashboard,
  MessageSquare,
  Newspaper,
  Package,
  PackageOpen,
  Recycle,
  Route,
  Scissors,
  ShieldCheck,
  ShoppingCart,
  Store,
  UserCircle,
  Users,
  LifeBuoy,
  Settings,
  TrendingDown,
  type LucideIcon,
} from 'lucide-react'

/** 图标名（`menu.ts` 里的字符串）→ lucide 组件 */
export const menuIconMap: Record<string, LucideIcon> = {
  BarChart3,
  Bell,
  Coins,
  BookOpen,
  Boxes,
  Building2,
  Calculator,
  ClipboardCheck,
  ClipboardList,
  Factory,
  Headphones,
  Layers,
  LayoutDashboard,
  MessageSquare,
  Newspaper,
  Package,
  PackageOpen,
  Recycle,
  Route,
  Scissors,
  ShieldCheck,
  ShoppingCart,
  Store,
  UserCircle,
  Users,
  LifeBuoy,
  Settings,
  TrendingDown,
}

/**
 * 取图标组件。
 *
 * `fallback` 默认 `LayoutDashboard`：**只为兜底不崩**，不代表「回落是对的」——
 * 注册缺失由 `menu-icons.test.ts` 判红（此处不做运行时告警，避免每次渲染都刷日志）。
 */
export function resolveMenuIcon(name: string, fallback: LucideIcon = LayoutDashboard): LucideIcon {
  return menuIconMap[name] || fallback
}

/** 已注册的图标名（判据用：`menu.ts` 的图标名集合 ⊆ 本集合） */
export function registeredIconNames(): string[] {
  return Object.keys(menuIconMap)
}