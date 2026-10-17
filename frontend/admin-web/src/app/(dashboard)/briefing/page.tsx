import { redirect } from 'next/navigation'

/**
 * 旧「每日简报」入口 → /dashboard（2026-10-17，issue #7087）。
 *
 * 用户逐字：「**不要新增每日简报的菜单了**，每日简报开关开启后，那一行分析结论本来就在经营看板上了，
 * 不需要额外一个菜单，移除掉，用户不开启简报开关那么经营看板就没结论文字，开启后就有结论文字，
 * 这样的形态就很好了」。
 *
 * ⇒ `config/menu.ts` 的「每日简报」菜单项**已删除**（连同 `briefingToggle` 这一菜单级过滤机制）；
 * 企业开关（`GET/PUT /api/admin/briefing/config`）继续只驱动**经营看板上的结论卡**
 * （`app/(dashboard)/dashboard/page.tsx` 的 `<BriefingCard enabled={briefingEnabled} />`）：
 * 开关关 = 看板无结论文字；开关开 = 有结论文字。
 *
 * 本页因此不再渲染任何内容，直接重定向到经营看板（旧书签 / 外部深链不 404）——
 * 先例 = `/processing`（加工项管理）、`/production/routings`（工艺配置）、`/settings/params`（参数总览）
 * 三个被移除的菜单项各自保留的重定向薄壳。
 *
 * ⚠️ `BriefingCard` / `ProactiveStatusPanel` 的 `variant="page"`（逐规则展开原因，issue #5955）
 * 随之在生产面**不再被调用**（组件与其既有单测保留，不在本单射程 —— 已登记在 PR body 的边界）。
 */
export default function BriefingRedirectPage() {
  redirect('/dashboard')
}
