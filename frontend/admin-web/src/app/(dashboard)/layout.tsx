'use client'

import { useState } from 'react'
import Sidebar from '@/components/layout/Sidebar'
import Header from '@/components/layout/Header'
import { cn } from '@/lib/utils'
import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 侧边栏 */}
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />

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

      {/* AI 助手悬浮组件 */}
      <FloatingAssistant />
    </div>
  )
}
