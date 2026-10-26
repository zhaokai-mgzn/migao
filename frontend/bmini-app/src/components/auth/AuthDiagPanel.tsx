/**
 * 登录自检面板（issue #7825）—— **只在 `?diag=1` 时渲染**。
 *
 * 为什么放在登录页：掉线的人**一定**会经过这里；而正常情况下它一行 DOM 都不渲染
 * （常驻面克制，§31 P1 —— 探针不是产品功能，不该占用商家视线）。
 *
 * 判据（见 `tests/auth-diag.test.ts`）：默认 `?diag=1` 之外**取不到** `auth-diag-panel`；
 * 打开后逐条列出 kind / 时间，且**不含**任何凭据字段（面板只读 `readAuthDiag()` 的 kind+detail，
 * 而 detail 的写入侧由 `authDiag.ts` 的口径约束为「不含 token / 票据 / 密码」）。
 */

import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { formatAuthDiagTime, readAuthDiag } from '../../utils/authDiag'

/** 面板最多显示几条（older 的留在存储里，不删） */
export const AUTH_DIAG_VISIBLE = 8

/**
 * 本次页面是否要显示自检面板：`?diag=1`（或 hash 里的 `?diag=1`）。
 *
 * 两个入口都认，是因为 H5 有两种打开形态：直链 `/b/?diag=1` 与带 hash 路由的
 * `/b/#/pages/auth/login/index?diag=1`（Taro 会把它塞进 `router.params`）。
 */
export function shouldShowAuthDiag(): boolean {
  try {
    const instance = Taro.getCurrentInstance?.() as { router?: { params?: Record<string, string> } } | undefined
    if (instance?.router?.params?.diag === '1') return true
    if (typeof window === 'undefined') return false
    const href = String(window.location?.href || '')
    return /[?&]diag=1(?:&|#|$)/.test(href)
  } catch {
    return false
  }
}

/** 环形缓冲 → 面板（最新在上；坏数据已在 `readAuthDiag` 里过滤） */
export default function AuthDiagPanel() {
  const entries = readAuthDiag().slice(-AUTH_DIAG_VISIBLE).reverse()

  return (
    <View className='auth-diag' data-testid='auth-diag-panel'>
      <Text className='auth-diag__title'>登录自检 · 最近 {entries.length} 条</Text>
      {entries.length === 0 ? (
        <Text className='auth-diag__empty'>本机还没有登录事件记录</Text>
      ) : (
        entries.map((entry, index) => (
          <Text key={`${entry.at}-${index}`} className='auth-diag__row' data-testid='auth-diag-row'>
            {formatAuthDiagTime(entry.at)} · {entry.kind}
            {entry.detail ? ` · ${entry.detail}` : ''}
          </Text>
        ))
      )}
      <Text className='auth-diag__hint'>仅记录登录方式与结果，不含密码 / 令牌 / 票据</Text>
    </View>
  )
}
