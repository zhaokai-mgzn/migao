'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import Sidebar from '@/components/layout/Sidebar'
import Header from '@/components/layout/Header'
import CommandPalette from '@/components/layout/CommandPalette'
import { usePermission } from '@/lib/permission'
import { cn } from '@/lib/utils'
import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'

// 路由 → 所需权限码映射（与后端 @RequirePermission 口径一致，前端作为第二道防线；
// 后端仍会 403 拒绝无权限请求，此处仅优化体验避免空白/报错页）。
// 顺序敏感：更具体的子路径放在前面。
const ROUTE_PERMISSION_MAP: Array<{ prefix: string; code: string }> = [
  { prefix: '/chat', code: 'agent:session' },
  // issue #5246：售后工单页是**读**页（建单/改状态是页内动作，后端按写码 order:refund 拦截）
  // ⇒ 页面守卫改用读码 after_sales:view，与 config/menu.ts 的节点码、后端 @RequirePermission 同源。
  { prefix: '/after-sales', code: 'after_sales:view' },
  { prefix: '/orders', code: 'order:list' },
  { prefix: '/products', code: 'product:list' },
  // issue #5291：分类读端点改挂读码 `product:category:view` ⇒ 页面守卫同码
  //（增删改分类仍由后端 `product:category` 拦，前端不重复表达写权限）。
  { prefix: '/categories', code: 'product:category:view' },
  // 顺序敏感：必须在 /processing 之前（前缀匹配会先命中 /processing）
  { prefix: '/processing-orders', code: 'production:view' },
  { prefix: '/processing', code: 'production:view' },
  // issue #4357：加工单唯一入口（生产看板）此前**没有**前端权限守卫，而它承接的
  // 原 /processing-orders 是有的 ⇒ 合并后守卫必须跟着入口走，否则等于砍掉既有护栏。
  // 🔴 issue #5291：生产域拆出**读**码 `production:view` ⇒ 生产看板 / 工艺配置 / 计件工资按读码；
  // **池看板 / 余料台账 / 省料看板仍是 `processing:manage`**（同组不同权）⇒ 更具体的子路径
  // 必须排在 `/production` 之前（前缀匹配先命中），否则会把它们一起收权。
  { prefix: '/production/pool', code: 'processing:manage' },
  { prefix: '/production/remnants', code: 'processing:manage' },
  { prefix: '/production/saving-board', code: 'processing:manage' },
  { prefix: '/production', code: 'production:view' },
  { prefix: '/customers', code: 'customer:view' },
  { prefix: '/finance', code: 'finance:view' },
  { prefix: '/employees', code: 'employee:list' },
  { prefix: '/settings', code: 'system:manage' },
  // issue #5246：知识库页同理 —— 页面本身的守卫用读码 knowledge:view
  //（增删改/发布/归档等写动作由后端 knowledge:manage 拦截，前端不重复表达写权限）。
  { prefix: '/knowledge', code: 'knowledge:view' },
  // issue #5291：岗位权限节点/页面按**读**码 `system:view`（改岗位仍由后端 system:manage 拦）。
  { prefix: '/roles', code: 'system:view' },
  { prefix: '/briefing', code: 'dashboard:view' },
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
  // 移动端抽屉（issue #5271）：小屏下侧边栏是浮层，默认收起
  const [mobileOpen, setMobileOpen] = useState(false)
  // 命令面板（⌘K，issue #5271）
  const [paletteOpen, setPaletteOpen] = useState(false)

  // 路由权限校验：无权限时展示 403 提示（不重定向，避免无 dashboard 权限时循环跳转）
  const requiredPermission = ROUTE_PERMISSION_MAP.find((r) => pathname.startsWith(r.prefix))?.code
  const permissionDenied = requiredPermission ? !hasPermission(requiredPermission) : false

  // 进入 /chat（会话页面）时自动收拢侧边栏，离开时自动恢复
  useEffect(() => {
    const isChatConversation = pathname.startsWith('/chat')
    if (isChatConversation) {
      manualToggle.current = false
      setCollapsed(true)
    } else if (!manualToggle.current) {
      setCollapsed(false)
    }
  }, [pathname])

  // 命令面板快捷键：⌘K / Ctrl+K（issue #5271）
  // 用 window 级监听（不是输入框内）—— 侧边栏与 Header 都可能不在视口内（移动端抽屉收起时）。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 跳页后收掉浮层（移动端抽屉 / 命令面板），否则新页面顶上还挂着旧浮层
  useEffect(() => {
    setMobileOpen(false)
    setPaletteOpen(false)
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
      {/* 侧边栏（issue #5271：桌面端常驻栏 / 移动端抽屉） */}
      <Sidebar
        collapsed={collapsed}
        onToggle={handleToggle}
        mobileOpen={mobileOpen}
        onMobileClose={() => setMobileOpen(false)}
        onOpenSearch={() => setPaletteOpen(true)}
      />

      {/* 移动端抽屉遮罩：点击关闭（z 低于侧边栏、高于内容与 Header） */}
      {mobileOpen && (
        <div
          data-testid="sidebar-mask"
          className="fixed inset-0 z-[45] bg-black/45 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* 主内容区 —— ⚠️ 边距只在 lg+ 生效：小屏侧边栏是浮层，不占内容宽度（issue #5271） */}
      <div
        className={cn(
          'transition-all duration-300 min-h-screen flex flex-col',
          collapsed ? 'lg:ml-16' : 'lg:ml-60'
        )}
      >
        {/* 顶部 Header */}
        <Header onOpenMobileNav={() => setMobileOpen(true)} />

        {/* 页面内容 — pb-24 底部预留空间，卡片 min-h 联动：内容不足一屏时
            底部锚定内容（如分页）不被右下角米宝浮动按钮（FAB）遮挡（#3070）。
            ⚠️ 勿改回 p-4 sm:p-6：Tailwind 中 padding 简写会覆盖 padding-bottom，pb-24 失效 */}
        <main className="flex-1 px-4 sm:px-6 pt-4 sm:pt-6 pb-24">
          <div className="min-h-[calc(100vh-184px)] rounded-2xl border border-neutral-200/80 bg-white shadow-card">
            {children}
          </div>
        </main>
      </div>

      {/* 菜单命令面板（⌘K，issue #5271） */}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />

      {/* AI 助手悬浮组件 — 聊天相关页面不显示（已有完整对话界面） */}
      {!pathname.startsWith('/chat') && <FloatingAssistant />}
    </div>
  )
}