'use client'

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useAuthStore } from '@/store/auth'
import { isPublicRoute } from '@/lib/auth-redirect'

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const { initialize, _hasHydrated } = useAuthStore()
  const [isReady, setIsReady] = useState(false)
  const pathname = usePathname() ?? ''

  useEffect(() => {
    if (!_hasHydrated) return

    // 公开路由（登录/注册等）无需恢复会话：跳过 initialize，直接渲染。
    // 否则无 cookie 访问 /login → /api/auth/me 401 → 拦截器强制跳 /login → 死循环（issue #2757）
    if (isPublicRoute(pathname)) {
      setIsReady(true)
      return
    }

    const init = async () => {
      try {
        await initialize()
      } catch (e) {
        // 初始化失败不阻塞渲染
      } finally {
        setIsReady(true)
      }
    }

    init()
  }, [_hasHydrated, initialize, pathname])

  // 等待 zustand persist 恢复 + 初始化完成
  if (!isReady) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-neutral-50">
        <div className="flex items-center gap-3 text-neutral-500">
          <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">加载中...</span>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
