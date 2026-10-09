/**
 * B 端底栏的**静态清单与图标表**（issue #6574）
 *
 * 🔴 这里**不是**可见性口径（那是服务端的事：`GET /api/auth/me` 的 `mobileTabs`，
 * 服务端 `MobileSurfaces.visibleTabsFor`）。本文件只有两件事：
 * ① `ALL_MERCHANT_TABS` = **全量 4 项**的镜像，用途只有一个：**拿不到菜单时照显全部**
 *    （tab 是功能入口，藏掉用户有的功能比露出一个点进去 403 的入口更糟 —— 与「数据」页待办块
 *    `error ⇒ 照渲染` 同一条规则）；它与服务端清单 / `app.config.ts` 的 tabBar 逐值相等，
 *    由 `tests/merchant-tabbar.test.tsx` 的类级守卫钉住（改一处不改另一处即红）。
 * ② 图标表：按 `key` 取（**不按中文标题** —— 标题可能被改文案，key 是稳定键）。
 */
export interface MerchantTab {
  /** 稳定键（服务端 `Surface.key` 同值） */
  key: string
  /** 中文名（拿不到菜单时的兜底文案；正常情况下用服务端下发的 title） */
  title: string
  /** bmini 页面路由（= `app.config.ts` tabBar.list[].pagePath 加前导 `/`） */
  route: string
}

import chatIcon from '../assets/tabbar/chat.png'
import chatActiveIcon from '../assets/tabbar/chat-active.png'
import dashboardIcon from '../assets/tabbar/dashboard.png'
import dashboardActiveIcon from '../assets/tabbar/dashboard-active.png'
import sessionsIcon from '../assets/tabbar/sessions.png'
import sessionsActiveIcon from '../assets/tabbar/sessions-active.png'
import profileIcon from '../assets/tabbar/profile.png'
import profileActiveIcon from '../assets/tabbar/profile-active.png'

/** 全量 4 项（顺序 = 服务端 `MobileSurfaces.TABS` = `app.config.ts` tabBar.list 的顺序） */
export const ALL_MERCHANT_TABS: MerchantTab[] = [
  { key: 'chat', title: '问黄金策', route: '/pages/chat/index/index' },
  { key: 'dashboard', title: '数据', route: '/pages/dashboard/index/index' },
  { key: 'sessions', title: '坐席', route: '/pages/sessions/index/index' },
  { key: 'profile', title: '我的', route: '/pages/profile/index/index' },
]

/** key → 图标（选中态另有一张；未登记的 key ⇒ 不渲染图标，仍渲染文字） */
export const TAB_ICONS: Record<string, { normal: string; active: string }> = {
  chat: { normal: chatIcon, active: chatActiveIcon },
  dashboard: { normal: dashboardIcon, active: dashboardActiveIcon },
  sessions: { normal: sessionsIcon, active: sessionsActiveIcon },
  profile: { normal: profileIcon, active: profileActiveIcon },
}