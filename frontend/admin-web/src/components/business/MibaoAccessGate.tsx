'use client'

import type { ReactNode } from 'react'

/**
 * 米宝唤出授权门（issue #5642 功能⑤，admin-web 侧）。
 *
 * 与小程序端（`frontend/bmini-app/src/components/chat/MibaoAccessGate.tsx`）**同源同口径**：
 * 两侧都**只消费服务端下发的 `capabilities.mibaoChat`**，不自己判权限码。
 *
 * ## 为什么是「页面内拒绝态」而不是路由级 403
 * 设计单 §8.1 逐字要求：未授权 ⇒「明确提示『需要管理员授权』+ 可行动引导
 * （**不是静默隐藏，也不是 403 白屏**）」。⇒ 入口可见、进来后给可读的授权缺失态。
 *
 * ⚠️ 与既有路由门的关系（**叠加，不是替代**）：`(dashboard)/layout.tsx` 的
 * `ROUTE_PERMISSION_MAP` 仍按既有节点码放行（那是「能不能进这一页」），
 * 本门判的是「能不能唤出米宝」（L1）。两者互不替代 —— 本组件**不改**路由门。
 */

/** 授权缺失态的**逐字**文案（判据 G3 断言它；改字即红）。 */
export const MIBAO_NEEDS_ADMIN_GRANT_TEXT = '需要管理员授权'

/** 可行动引导（判据 G4：不许只给一句「无权限」就完事）。 */
export const MIBAO_GRANT_GUIDE_TEXT = '请联系企业管理员在「员工管理」中为你开通米宝使用权限'

interface MibaoAccessGateProps {
  /**
   * 服务端下发的米宝唤出能力位（`GET /api/auth/me` ⇒ `data.capabilities.mibaoChat`）。
   * `null` / `undefined` = 尚未取到 ⇒ 不渲染拒绝态（避免把「还没拿到」误报成「没权限」）。
   */
  allowed: boolean | null | undefined
  children: ReactNode
}

export default function MibaoAccessGate({ allowed, children }: MibaoAccessGateProps) {
  if (allowed === null || allowed === undefined) {
    return null
  }

  if (!allowed) {
    return (
      <div
        data-testid='mibao-gate-denied'
        className='flex h-full flex-col items-center justify-center gap-4 p-8 text-center'
      >
        <h2 className='text-lg font-semibold text-gray-800'>{MIBAO_NEEDS_ADMIN_GRANT_TEXT}</h2>
        <p className='max-w-md text-sm text-gray-500'>{MIBAO_GRANT_GUIDE_TEXT}</p>
      </div>
    )
  }

  return <>{children}</>
}
