'use client'

/**
 * 参数总览 `/settings/params`（issue #6573）—— 大菜单**一级项**「参数总览」的第一屏。
 *
 * ## 它是什么
 *
 * 配置面的**唯一入口 + 配置主线**：把散在 6 个页面的商家可配参数一处列出（§22 配置类页面规范），
 * 并带上「**还缺什么、下一步去哪**」（`frontend/admin-web/src/lib/config-readiness.ts` 的单一真值）。
 *
 * ## 为什么它是**独立菜单项**而不是 `/settings` 的一个 tab（本单的裁定，带 durable 证据）
 *
 * 「参数总览」原为 `企业基础信息`（节点码 `system:manage`）的一个 tab ⇒ 持 `production:view`
 * 的生产岗（operator / product_manager / sales / customer_service / finance，见
 * `rbac/manifest.json` 的 `roles.seed`）**根本进不来**，而「缺配置」的正是他们要配的东西。
 * 升为一级项后节点码取**既有**码 `production:view`（不新造 —— 新造码今天无人持有 = 菜单恒不可见，
 * #4203 同族坑）⇒ 本单**不改任何端点的权限码**，授权 delta = 仅「新增一个入口的可见面」。
 *
 * ## 🔴 取数为什么在**页面**、不在子组件（这不是风格偏好，是判据要求）
 *
 * 仓内口径 = 「**页面源码里由 `useEffect` 驱动的可执行面 = 该页第一屏读端点**」
 * （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `page_first_screen_text`，
 * 再由 `rbac/derive.py` 四跳现取端点码 ⇒ `rbac/manifest.json` 的 `pages[].units`）。
 * 把第一屏取数藏进子组件 ⇒ 那一跳**看不见它** ⇒ 「本页第一屏到底调了哪些码」变成一句没人能核的话。
 * ⇒ 本文件发起 5 个读面并把结果分发给两个受控子组件（`ConfigReadinessBar` / `TenantParamsPanel`）。
 *
 * ## 第一屏码集（判据口径）
 *
 * 5 个读面**全部**是 `production:view`（算料配置的方法级码、其余四个是该页既有读码）
 * ⇒ 第一屏码集**恰好** `{production:view}` = 菜单节点码 = 路由守卫码，
 * **不**触发 `MULTI_READ_ENDPOINT_PAGES` / `MENU_READ_PARITY_RESIDUALS` 登记。
 * 其余域按**域级权限**条件渲染（AI 客服 = `system:manage`、余料回收 = `processing:manage`）：
 * 不持该码 ⇒ 不渲染、不请求 —— 这是「看得见 ⇒ 打得开」在**域级**的落地。
 */
import { useCallback, useEffect, useState } from 'react'
import { productionApi } from '@/lib/api'
import { TenantParamsPanel } from '@/components/settings/TenantParamsPanel'
import { ConfigReadinessBar } from '@/components/settings/ConfigReadinessBar'
import {
  judgeBaseRoutesStep,
  judgeConfigSourceStep,
  judgeDefaultRouteStep,
  judgeFeeCombinationsStep,
  judgeOperationsStep,
  missingBaseRoutesOf,
  type ReadinessState,
} from '@/lib/config-readiness'
import type { CraftCalcConfigResponse } from '@/types'

/** `request.get` 的返回壳（`{ data: { data: 载荷 } }`）；取不到一律 `null`（**不区分失败与空**，两者都算 unknown） */
type Settled = PromiseSettledResult<{ data?: { data?: unknown } }>

function unwrap(res: Settled): unknown {
  return res.status === 'fulfilled' ? (res.value?.data?.data ?? null) : null
}

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : {}
}

function arr(v: unknown): unknown[] | null {
  return Array.isArray(v) ? v : null
}

export default function TenantParamsPage() {
  const [loading, setLoading] = useState(true)
  const [calc, setCalc] = useState<CraftCalcConfigResponse | null>(null)
  const [calcError, setCalcError] = useState('')
  const [states, setStates] = useState<Record<string, ReadinessState>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setCalcError('')
    // 五个读面**各自独立**：一个失败不该让整块空白（失败的那步走 `unknown`，如实说「读不到」）
    const [posRes, routingsRes, comboRes, gapRes, calcRes] = await Promise.allSettled([
      productionApi.getOperationPositions(),
      productionApi.getRoutings(),
      productionApi.getFeeCombinations(),
      productionApi.getFeeGaps(),
      productionApi.getCraftCalcConfig(true),
    ])

    // ── 算料域读面（面板要的值 + 主线的第 ⑤ 步判据同源于它）
    if (calcRes.status === 'fulfilled') {
      setCalc(calcRes.value.data?.data ?? null)
    } else {
      setCalc(null)
      // ⚠️ 读面受生产域读码 `production:view` 门控（issue #5291；写面 `PUT` 仍 `processing:manage`）：
      // **权限拒绝是终态**，不是「参数有问题」——
      // 给可行动话术，不让商家反复重试（同族实证：issue #4103 的 P0 形态）。
      setCalcError('算料口径读取失败（可能是当前岗位没有「工艺配置」权限）—— 请联系管理员开权限后重试')
    }

    // ── ① 工序与单价：孤儿工序跨页取不到 ⇒ 传 `null`（**不参与判定**，不是 0）
    const positions = arr(unwrap(posRes))
    const opsState = judgeOperationsStep({
      readFailed: positions === null,
      total: positions ? positions.length : 0,
      unpriced: positions ? positions.filter((p) => rec(p).unit_price == null).length : 0,
      orphans: null,
    })

    // ── ② 工艺路线 / ③ 默认路线：同一个读面
    const routeList = arr(rec(unwrap(routingsRes)).routings)
    const routesState =
      routeList === null
        ? 'unknown'
        : judgeBaseRoutesStep(missingBaseRoutesOf(routeList.map((r) => String(rec(r).name ?? ''))))
    const defaultState =
      routeList === null
        ? 'unknown'
        : judgeDefaultRouteStep(routeList.filter((r) => rec(r).is_default === true).length)

    // ── ④ 加工费组合：**缺口口径在服务端**（前端不重算组合命中）
    const comboPayload = rec(unwrap(comboRes))
    const comboCount =
      typeof comboPayload.total === 'number'
        ? comboPayload.total
        : (arr(comboPayload.combinations)?.length ?? null)
    const gapPayload = rec(unwrap(gapRes))
    const gapCount =
      typeof gapPayload.unpriced_combination_total === 'number'
        ? gapPayload.unpriced_combination_total
        : (arr(gapPayload.unpriced_combinations)?.length ?? null)

    // ── ⑤ 算料配置：`source` 三态（`stored` / `default` / 其余 ⇒ unknown）
    setStates({
      operations: opsState,
      routings: routesState,
      'default-route': defaultState,
      'fee-combinations': judgeFeeCombinationsStep(comboCount, gapCount),
      calc: judgeConfigSourceStep(
        calcRes.status === 'fulfilled'
          ? (rec(unwrap(calcRes)).source as string | undefined)
          : undefined,
      ),
    })
    setLoading(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="p-6">
      <TenantParamsPanel
        calc={calc}
        calcError={calcError}
        loading={loading}
        readiness={<ConfigReadinessBar states={states} loading={loading} />}
      />
    </div>
  )
}