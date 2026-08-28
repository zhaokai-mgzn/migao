'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import Sidebar from '@/components/layout/Sidebar'
import Header from '@/components/layout/Header'
import { usePermission } from '@/lib/permission'
import { cn } from '@/lib/utils'
import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'

// 路由 → 所需权限码映射（与后端 @RequirePermission 口径一致，前端作为第二道防线；
// 后端仍会 403 拒绝无权限请求，此处仅优化体验避免空白/报错页）。
// 顺序敏感：更具体的子路径放在前面。
const ROUTE_PERMISSION_MAP: Array<{ prefix: string; code: string }> = [
  { prefix: '/chat/config', code: 'agent:quickreply' },
  { prefix: '/chat', code: 'agent:session' },
  { prefix: '/after-sales', code: 'order:refund' },
  { prefix: '/orders', code: 'order:list' },
  { prefix: '/products', code: 'product:list' },
  { prefix: '/categories', code: 'product:category' },
  { prefix: '/processing', code: 'processing:manage' },
  { prefix: '/customers', code: 'customer:view' },
  { prefix: '/finance', code: 'finance:view' },
  { prefix: '/employees', code: 'employee:list' },
  { prefix: '/settings', code: 'system:manage' },
  { prefix: '/knowledge', code: 'knowledge:manage' },
  { prefix: '/roles', code: 'system:manage' },
  { prefix: '/dashboard', code: 'dashboard:view' },
]

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const pathname = usePathname()
  const { has: hasPermission } = usePermission()
  const [collapsed, setCollapsed] = useState(false)
  const manualToggle = useRef(false)

  // 路由权限校验：无权限时展示 403 提示（不重定向，避免无 dashboard 权限时循环跳转）
  const requiredPermission = ROUTE_PERMISSION_MAP.find((r) => pathname.startsWith(r.prefix))?.code
  const permissionDenied = requiredPermission ? !hasPermission(requiredPermission) : false

  // 进入 /chat（会话页面）时自动收拢侧边栏，离开时自动恢复
  // /chat/config 是设置页面，侧边栏保持展开
  useEffect(() => {
    const isChatConversation = pathname.startsWith('/chat') && !pathname.startsWith('/chat/config')
    if (isChatConversation) {
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

  if (permissionDenied) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-neutral-50">
        <div className="rounded-2xl border border-neutral-200 bg-white p-10 text-center shadow-card max-w-md">
          <div className="text-4xl mb-3">🔒</div>
          <h1 className="text-lg font-semibold text-neutral-900">无权访问该页面</h1>
          <p className="mt-2 text-sm text-neutral-500">
            当前账号缺少权限 <code className="rounded bg-neutral-100 px-1.5 py-0.5 text-primary-600">{requiredPermission}</code>，
            如需开通请联系管理员在「员工管理」中调整权限。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-neutral-50">
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
        <main className="flex-1 p-4 sm:p-6">
          <div className="min-h-[calc(100vh-120px)] rounded-2xl border border-neutral-200/80 bg-white shadow-card">
            {children}
          </div>
        </main>
      </div>

      {/* AI 助手悬浮组件 — 聊天相关页面不显示（已有完整对话界面） */}
      {!pathname.startsWith('/chat') && <FloatingAssistant />}
    </div>
  )
}
