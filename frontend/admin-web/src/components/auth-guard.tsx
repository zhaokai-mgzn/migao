'use client'

import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth'

// 注：公开路由清单只在 lib/auth-redirect.ts 维护（PUBLIC_ROUTES 单一源）。
// 这里若再抄一份（历史上抄过一份且从未被使用），漏配时不会有任何东西变红 ——
// issue #4903 的「首页漏配」正是从这种双份清单里长出来的。
const protectedRoutePrefixes = [
  '/dashboard', '/products', '/processing', '/knowledge', '/settings',
  '/orders', '/chat', '/customers', '/employees', '/roles',
  '/agent-workspace', '/after-sales', '/notifications', '/categories',
  // 首登强制改密页（issue #5485）：未登录访问它同样该去登录页（页面本身依赖已认证会话）
  '/change-password',
]

// 审计 07 P1-F1：JWT 为 HttpOnly cookie，JS 无法读取——
// 登录态只以 store.isAuthenticated（由 /api/auth/me 验证后置位）为准，
// 不再依赖可读 cookie/本地存储。

/** 去掉尾部斜杠（根路径除外），兼容 trailingSlash: true */
function normalizePath(p: string): string {
  return p.length > 1 && p.endsWith('/') ? p.slice(0, -1) : p
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const rawPathname = usePathname()
  const pathname = normalizePath(rawPathname)
  const router = useRouter()
  const [isChecking, setIsChecking] = useState(true)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const _hasHydrated = useAuthStore((s) => s._hasHydrated)
  const mustChangePassword = useAuthStore((s) => s.user?.mustChangePassword)

  useEffect(() => {
    if (!_hasHydrated) return

    const isLoggedIn = isAuthenticated

    const isProtectedRoute = protectedRoutePrefixes.some(prefix => pathname.startsWith(prefix))

    // 已登录用户访问登录页 -> 跳转 dashboard
    if (isLoggedIn && (pathname === '/login' || pathname === '/register')) {
      router.replace('/dashboard')
      return
    }

    // #5485：首登未改密的会话，除改密/登出/读自己信息外服务端一律 403
    // （PASSWORD_CHANGE_REQUIRED，axios 层已全局兜底）。这里在路由层先兜一次，
    // 免得用户看到的是一屏业务页报错而不是「你先改密码」。
    if (isLoggedIn && mustChangePassword && pathname !== '/change-password') {
      router.replace('/change-password')
      return
    }

    // 未登录用户访问受保护路由 -> 跳转登录页
    if (!isLoggedIn && isProtectedRoute) {
      router.replace(`/login?callbackUrl=${encodeURIComponent(pathname)}`)
      return
    }

    setIsChecking(false)
  }, [pathname, router, isAuthenticated, _hasHydrated, mustChangePassword])

  // 检查中不渲染内容，避免闪烁
  if (isChecking) {
    return null
  }

  return <>{children}</>
}
