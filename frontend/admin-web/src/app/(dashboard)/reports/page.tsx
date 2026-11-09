import { redirect } from 'next/navigation'

/**
 * 旧「报表中心」入口 → `/dashboard`「经营报表」（issue #8852，用户 2026-11-09 钉钉要求）。
 *
 * 用户逐字：「把『经营概览』和『报表中心』两个页面整合为一个页面『经营报表』。整合后的页面展示
 * 要符合用户查看、分析、管理逻辑，不要把数据乱七八糟的杂揉在一起。」
 *
 * ⇒ 两张页面合成**一个** `/dashboard`「经营报表」：报表五张卡由
 * `components/reports/BusinessReportsSection` 承载，按「查看 → 分析 → 管理」分区挂在合并页的
 * 「经营分析」段里。菜单项只剩 `/dashboard` 一个（权限码 `dashboard:view` 一字不动）。
 *
 * 本页因此不再渲染任何内容，直接重定向（旧书签 / 外部深链 / AI 导航里历史说法不 404）——
 * 先例 = `/briefing`（每日简报）、`/processing`（加工项管理）、`/settings/params`（参数总览）
 * 三个被移除菜单项各自保留的重定向薄壳。
 *
 * ⚠️ 路由守卫（`(dashboard)/layout.tsx` 的 `/reports` → `dashboard:view`）**保留**：
 * 无该码者地址栏直达 `/reports` 仍被拦，不能只靠菜单一道防线。
 */
export default function ReportsRedirectPage() {
  redirect('/dashboard')
}
