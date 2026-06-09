'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import Sidebar from '@/components/layout/Sidebar'
import Header from '@/components/layout/Header'
import { cn } from '@/lib/utils'
import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)
  const manualToggle = useRef(false)

  // 进入 /chat 时自动收拢侧边栏，离开时自动恢复
  useEffect(() => {
    const isChat = pathname.startsWith('/chat')
    if (isChat) {
      manualToggle.current = false
      setCollapsed(true)
    } else if (!manualToggle.current) {
      setCollapsed(false)
    }
  }, [pathname])

  const handleToggle = () => {
    manualToggle.current = true
    setCollapsed(prev => !prev)
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 侧边栏 */}
      <Sidebar collapsed={collapsed} onToggle={handleToggle} />

      {/* 主内容区 */}
      <div
        className={cn(
          'transition-all duration-300 min-h-screen flex flex-col',
          collapsed ? 'ml-16' : 'ml-60'
        )}
      >
        {/* 顶部 Header */}
        <Header />

        {/* 页面内容 */}
        <main className="flex-1 p-6">
          <div className="bg-white rounded-lg shadow-card min-h-[calc(100vh-120px)]">
            {children}
          </div>
        </main>
      </div>

      {/* AI 助手悬浮组件 — 聊天页面不显示（已有完整对话界面） */}
      {pathname !== '/chat' && <FloatingAssistant />}
    </div>
  )
}
