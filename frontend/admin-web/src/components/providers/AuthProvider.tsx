'use client'

import { useEffect, useState } from 'react'
import { useAuthStore } from '@/store/auth'

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const { initialize, _hasHydrated } = useAuthStore()
  const [isReady, setIsReady] = useState(false)

  useEffect(() => {
    if (!_hasHydrated) return

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
  }, [_hasHydrated, initialize])

  // 等待 zustand persist 恢复 + 初始化完成
  if (!isReady) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex items-center gap-3 text-gray-500">
          <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">加载中...</span>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
