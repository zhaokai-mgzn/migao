'use client'

import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth'

const publicRoutes = ['/login', '/register', '/about', '/services', '/contact']
const protectedRoutePrefixes = [
  '/dashboard', '/products', '/processing', '/knowledge', '/settings',
  '/orders', '/chat', '/customers', '/employees', '/roles',
  '/registrations', '/agent-workspace', '/after-sales', '/notifications', '/categories',
]

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined
  const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'))
  return match ? match[2] : undefined
}

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
    // 等待 Zustand 水合完成再做认证检查
    if (!_hasHydrated) return

    const accessToken = getCookie('access_token')
    const isLoggedIn = isAuthenticated || !!accessToken

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
