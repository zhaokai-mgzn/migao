'use client'

/**
 * 旧链 `/settings/params` → **重定向**到「企业基础设置」页的「算料口径」域（issue #6580）。
 *
 * 为什么保留这条路由：仓内口径是「**旧深链不 404**」—— 下单页的「参数说明」等地方曾直接深链到这里。
 *
 * 🔴 为什么**必须**是重定向、而不是继续渲染那份参数面板：`/settings/params` 与 `/settings` 的
 * 「算料口径」域编辑的是**同一份配置**（`GET/PUT /api/admin/production/craft-calc-config`）——
 * 两处各挂一个可编辑面就是设计真值源里写死的**判死线第 1 条**（同一配置两个入口），
 * 也正是用户 2026-10-09 说的「散乱的配置乱放」。
 *
 * 🔴 取数为什么**一个都没有**：本页只做跳转 ⇒ 它不该出现在任何「第一屏读端点」台账里
 * （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `ROUTE_WITHOUT_MENU_NODE` 已登记它）。
 */
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function SettingsParamsRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace('/settings?domain=calc')
  }, [router])
  return null
}
