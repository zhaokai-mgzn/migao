'use client'

/**
 * 工艺配置 `/production/routings` —— **薄壳**（功能体 = {@link ProcessConfigBoard}）。
 *
 * ## 本页今天只做两件事
 *
 * 1. **渲染功能体**（无 `tab` 参数 / `tab=process` / `tab=cut`）：行为**一字不变**；
 * 2. **旧深链 `?tab=calc` 重定向**到 `/settings?domain=calc`（issue #6825）。
 *
 * 为什么第 2 条必须是重定向：板子的「算料配置」tab 是**算料配置的第二个写面** ——
 * 同一份配置（`GET/PUT /api/admin/production/craft-calc-config`）两个入口，正是设计真值源
 * （`docs/design/enterprise-settings-redesign.md`）写死的**判死线第 1 条**，也正是用户
 * 2026-10-09 说的「散乱的配置乱放」。issue #6825 把写面收敛进 `/settings` 的「算料口径」域
 * ⇒ 板子那个 tab 退役、旧深链改为重定向（仓内口径：**旧深链不 404、不落空白**）。
 *
 * ⚠️ 其余 tab（`process` / `cut`）与无参数形态**不做任何跳转** —— 那些功能体仍在这条路由上。
 *
 * ## 历史（保留它的原因见 `docs/design/enterprise-settings-redesign.md` §6 债务）
 *
 * 本页原先自带 180 余行未使用的旧实现 import 与设计注释（issue #6585 把功能体抽成板子后遗留的
 * 死代码）。issue #6825 顺手清掉 —— 它没有任何消费点（页面只 `default export` 板子），
 * 留着只会让「真值源在哪」更难读。旧实现的文档口径已迁到
 * `frontend/admin-web/src/components/production-config/ProcessConfigBoard.tsx` 与
 * `docs/design/position-instance-routing-model.md`。
 */
import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import ProcessConfigBoard from '@/components/production-config/ProcessConfigBoard'

/** 算料口径的**唯一写面**（`frontend/admin-web/src/lib/config-center-domains.ts` 的 `calc` 域） */
const CALC_DOMAIN_HREF = '/settings?domain=calc'

/**
 * 旧深链落点：`?tab=calc` ⇒ 新写面。**不渲染任何东西**（跳两次 = 闪烁；这里恰好一次）。
 *
 * 用 `router.replace`（不是 `push`）：旧链不该留在浏览历史里（回退会把商家弹回一个已退役的 tab）。
 */
function CalcTabRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace(CALC_DOMAIN_HREF)
  }, [router])
  return null
}

/** 板子需要 `useSearchParams` 的 Suspense 边界（Next 静态预渲染要求；形态照本页既有写法） */
function RoutingsRoute() {
  const searchParams = useSearchParams()
  if (searchParams?.get('tab') === 'calc') return <CalcTabRedirect />
  return <ProcessConfigBoard />
}

export default function ProcessConfigPage() {
  return (
    <Suspense fallback={null}>
      <RoutingsRoute />
    </Suspense>
  )
}
