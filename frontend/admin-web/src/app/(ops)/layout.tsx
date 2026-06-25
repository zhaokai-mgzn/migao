'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import CorporateNav from '@/components/corporate/CorporateNav'
import OpsSidebar from '@/components/ops/OpsSidebar'
import { useAuthStore } from '@/store/auth'

export default function PlatformLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const { user, isAuthenticated, _hasHydrated } = useAuthStore()
  const [authorized, setAuthorized] = useState(false)

  useEffect(() => {
    if (!_hasHydrated) return

    // 未登录 → 跳转登录页
    if (!isAuthenticated || !user) {
      router.replace('/login')
      return
    }

    // 非管理员 → 跳转登录页
    const isAdmin = user.roles?.includes('super_admin')
    if (!isAdmin) {
      router.replace('/login')
      return
    }

    setAuthorized(true)
  }, [_hasHydrated, isAuthenticated, user, router])

  // 等待 hydration 和鉴权
  if (!_hasHydrated || !authorized) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-3 border-blue-600 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-gray-500">验证权限中...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航 */}
      <CorporateNav />

      {/* 侧边栏 */}
      <OpsSidebar />

      {/* 主内容区域 —— 右侧自适应 */}
      <main className="ml-60 pt-16 min-h-screen">
        <div className="p-6">
          {children}
        </div>
      </main>
    </div>
  )
}
