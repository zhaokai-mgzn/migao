'use client'

/**
 * 旧「工艺配置」路由 `/production/routings` —— **已下架**（issue #7182，2026-10-18）。
 *
 * ## 为什么下架
 *
 * 用户报障：「原工艺配置页面怎么未下架，从计件工资提示链接可以跳转到原页面，这里应该跳转到新页面了」。
 * 这个页的功能体（工序管理 / 裁高配置 / 工艺路线）早已并入**企业基础设置**的对应域
 * （`operation-prices` / `cutting-height` / `craft-route`，见 `config-center-domains.ts`），
 * `/settings` 页**已经**内嵌同一块 `ProcessConfigBoard` ⇒ 这条路由是**第二写面**，
 * 与设计真值源（`docs/design/enterprise-settings-redesign.md`）的「一个配置只有一个写面」直接冲突。
 *
 * ## 下架方式：**重定向，不是 404**
 *
 * 仓内口径（#6825 起）：旧深链不 404、不落空白。用 `router.replace`（不是 `push`）——
 * 旧地址不该留在浏览历史里（回退会把商家弹回一个已下架页）。
 *
 * 判据：`frontend/admin-web/tests/unit/pages/production-routings-legacy.test.tsx`
 * （渲染即 replace 到唯一写面 + 全仓不再有指向本路由的 `href`）。
 */
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/** 唯一写面 = 作业定价域（`frontend/admin-web/src/lib/config-center-domains.ts`） */
const SETTINGS_HREF = '/settings?domain=operation-prices'

export default function LegacyRoutingsPage() {
  const router = useRouter()
  useEffect(() => {
    router.replace(SETTINGS_HREF)
  }, [router])
  return null
}
