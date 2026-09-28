import type { ReactNode } from 'react'
import { View, Text } from '@tarojs/components'

/**
 * 米宝唤出授权门（issue #5642 功能⑤）。
 *
 * ## 判据（设计单 §8.1 / §8.5 G2~G4）
 * - 持管理员权限码（或 `"*"`）⇒ 默认可唤；员工被企业管理员勾了米宝唤出码 ⇒ 可唤；
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
export const MIBAO_GRANT_GUIDE_TEXT = '请联系企业管理员在「员工管理」中为你开通米宝使用权限'

interface MibaoAccessGateProps {
  /**
   * 服务端下发的米宝唤出能力位（`GET /api/auth/me` ⇒ `data.capabilities.mibaoChat`）。
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
    return (
      <View
        data-testid='mibao-gate-denied'
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '80px 32px',
          textAlign: 'center',
        }}
      >
        <Text style={{ fontSize: '32px', fontWeight: '600', color: '#1f2937' }}>
          {MIBAO_NEEDS_ADMIN_GRANT_TEXT}
        </Text>
        <Text style={{ marginTop: '16px', fontSize: '26px', color: '#6b7280', lineHeight: '1.6' }}>
          {MIBAO_GRANT_GUIDE_TEXT}
        </Text>
      </View>
    )
  }

  return <>{children}</>
}
