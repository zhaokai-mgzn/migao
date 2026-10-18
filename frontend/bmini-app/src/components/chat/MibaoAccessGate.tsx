import type { ReactNode } from 'react'
import AdminGrantGate from '../admin/SurfaceAccessGate'

/**
 * 黄金策唤出授权门（issue #5642 功能⑤）。
 *
 * ## 判据（设计单 §8.1 / §8.5 G2~G4）
 * - 持管理员权限码（或 `"*"`）⇒ 默认可唤；员工被企业管理员勾了黄金策唤出码 ⇒ 可唤；
 * - 都未满足 ⇒ **入口可见、点击后给明确的授权缺失态**：
 *   ① 文案含**逐字**「需要管理员授权」（`MIBAO_NEEDS_ADMIN_GRANT_TEXT`）；
 *   ② 给出**可行动引导**（去哪授权、找谁）；
 *   ③ **不是静默隐藏入口**、**不是 403 白屏**。
 *
 * ## 🔴 前端零权限码（设计单 §2.4 判据②）
 * 本组件**只消费服务端下发的 `capabilities.mibaoChat` 布尔位**，不自己判任何权限码 ——
 * 「哪些码算管理员」是服务端 `AdminGate` 的单一真值，改一处即 h5 与 admin-web 两端同步。
 */

/** 授权缺失态的**逐字**文案（判据 G3 断言它；改字即红）。 */
export const MIBAO_NEEDS_ADMIN_GRANT_TEXT = '需要管理员授权'

/** 可行动引导（判据 G4：不许只给一句「无权限」就完事）。 */
export const MIBAO_GRANT_GUIDE_TEXT = '请联系企业管理员在「员工管理」中为你开通黄金策使用权限'

interface MibaoAccessGateProps {
  /**
   * 服务端下发的黄金策唤出能力位（`GET /api/auth/me` ⇒ `data.capabilities.mibaoChat`）。
   * `null` = 尚未取到 ⇒ **不渲染任何一侧**（避免闪一下拒绝态，那不是用户的真实状态）。
   */
  allowed: boolean | null
  children: ReactNode
}

export default function MibaoAccessGate({ allowed, children }: MibaoAccessGateProps) {
  if (allowed === null) {
    return null
  }

  if (!allowed) {
    // 呈现实现**只有一份**（`AdminGrantGate`）：底栏页（数据 / 坐席）在 2026-10-18 裁定后
    // 也用同一形态（「没权限就向问黄金策页面的做法」）⇒ 两处各抄一份样式必然漂。
    return <AdminGrantGate testid='mibao-gate-denied' guide={MIBAO_GRANT_GUIDE_TEXT} />
  }

  return <>{children}</>
}
