'use client'

import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth'

const publicRoutes = ['/login', '/register', '/about', '/services', '/contact']
const protectedRoutePrefixes = [
  '/dashboard', '/products', '/processing', '/knowledge', '/settings',
  '/orders', '/chat', '/customers', '/employees', '/roles',
  '/agent-workspace', '/after-sales', '/notifications', '/categories',
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

  useEffect(() => {
    if (!_hasHydrated) return

    const isLoggedIn = isAuthenticated

    const isProtectedRoute = protectedRoutePrefixes.some(prefix => pathname.startsWith(prefix))

    // 已登录用户访问登录页 -> 跳转 dashboard
    if (isLoggedIn && (pathname === '/login' || pathname === '/register')) {
      router.replace('/dashboard')
      return
    }

    // 未登录用户访问受保护路由 -> 跳转登录页
    if (!isLoggedIn && isProtectedRoute) {
      router.replace(`/login?callbackUrl=${encodeURIComponent(pathname)}`)
      return
    }

    setIsChecking(false)
  }, [pathname, router, isAuthenticated, _hasHydrated])

  // 检查中不渲染内容，避免闪烁
  if (isChecking) {
    return null
  }

  return <>{children}</>
}
