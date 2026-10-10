'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'
import Sidebar from '@/components/layout/Sidebar'
import Header from '@/components/layout/Header'
import CommandPalette from '@/components/layout/CommandPalette'
import { usePermission } from '@/lib/permission'
import { useChatStore } from '@/store/chat'
import { cn } from '@/lib/utils'
import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'
import AccessDenied from '@/components/common/AccessDenied'

// 路由 → 所需权限码映射（与后端 @RequirePermission 口径一致，前端作为第二道防线；
// 后端仍会 403 拒绝无权限请求，此处仅优化体验避免空白/报错页）。
// 顺序敏感：更具体的子路径放在前面。
const ROUTE_PERMISSION_MAP: Array<{ prefix: string; code: string }> = [
  { prefix: '/chat', code: 'agent:session' },
  // issue #5977：`/agent-workspace` 子树（根 = 重定向占位页 / `sessions` = 会话监控 / `human-sessions`
  // = 在线接待）**整棵同域同一码** —— 该域（含 `/chat`）唯一的权限码就是 `agent:session`
  //（菜单节点「在线接待」的码 = `AgentSessionController` 的类级码）⇒ 一条**父前缀**覆盖三个路径，
  // 不必逐条登记（子路径与父前缀**同码**，故不触发判据 11① 的遮蔽）。
  // 此前只有 `/chat` 一项 ⇒ 销售（无 `agent:session`）直达 `/agent-workspace/human-sessions`
  // 不被 403 拦截（#5977 的现场形态）。
  { prefix: '/agent-workspace', code: 'agent:session' },
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
  // **智能派单 / 余料台账 / 省料看板仍是 `processing:manage`**（同组不同权）⇒ 更具体的子路径
  // 必须排在 `/production` 之前（前缀匹配先命中），否则会把它们一起收权。
  // issue #5699（P4）：与 menu.ts 的节点码同批收敛到页面读码（节点码 ≠ 页面读码 = 判据 12 的残留）。
  { prefix: '/production/pool', code: 'processing:view' },
  { prefix: '/production/remnants', code: 'processing:manage' },
  // issue #5699（P4）：同上 —— 省料看板页面码 = product:list。
  { prefix: '/production/saving-board', code: 'product:list' },
  // 🔴 2026-10-09（issue #6580）：下面两条是**旧入口兼容**前缀（对应菜单项已移除）——
  // 「加工项管理」`/production/processing`、「工艺配置」`/production/routings` 的功能体已并入
  // `/settings` 企业基础设置页 ⇒ 路由保留（旧深链不 404）、守卫码取新入口的页面码 `production:view`。
  // ⚠️ 它们**必须排在父前缀 `/production` 之前**（本表用 `find()` + `startsWith`；更宽的父前缀在前会让
  // 子路径成为**永不命中的死条目** ⇒ 判据 11① 判红）。菜单项已移除 ⇒ 无节点可钉，
  // 故同批登记在 `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `ROUTE_WITHOUT_MENU_NODE`。
  { prefix: '/production/processing', code: 'production:view' },
  { prefix: '/production/routings', code: 'production:view' },
  { prefix: '/production', code: 'production:view' },
  { prefix: '/customers', code: 'customer:view' },
  { prefix: '/finance', code: 'finance:view' },
  // 发货单（issue #5939）：页面守卫码 = 菜单节点码 = 该页第一屏读端点码（GET /api/admin/shipments）
  // = `order:list` —— 取**既有**码，与 /orders 同一把尺子（#5699 判据 12 的口径）。
  { prefix: '/shipments', code: 'order:list' },
  // issue #5976：入库单（菜单节点码 `inbound:view` = 该页 `gate` = `InboundOrderController` 的读码）
  // 此前只有菜单一道防线 ⇒ 无 `inbound:view` 者地址栏直达 `/inbound-orders` 不被拦。
  // 一条前缀同时覆盖 `/inbound-orders/new`（**不单列** —— 更宽的父前缀排在前面会让子路径成为
  // `find()` 永不命中的死条目，判据 11① 判红）。
  { prefix: '/inbound-orders', code: 'inbound:view' },
  // 库存明细（issue #6404）：页面守卫码 = 菜单节点码 = 该页第一屏读端点码
  //（`StockLedgerController` 的**方法级** `product:list`）—— 取**既有**码，不新造。
  // 没有这一条就只有菜单一道防线：无 `product:list` 者地址栏直达 `/stock-ledger` 不被拦
  //（同 #5976 入库单的现场形态）。
  { prefix: '/stock-ledger', code: 'product:list' },
  { prefix: '/employees', code: 'employee:list' },
  // 🔴 2026-10-09（issue #6580）：`/settings/params`（原「参数总览」一级项）是**旧入口兼容**前缀
  // —— 该一级项已撤掉（内容回到 `/settings` 页内的配置域）⇒ 路由保留、守卫码取新入口的页面码。
  // ⚠️ 必须排在父前缀 `/settings` **之前**（`find()` + `startsWith`；否则它是永不命中的死条目 ⇒ 判据 11① 判红）。
  { prefix: '/settings/params', code: 'production:view' },
  // 🔴 2026-10-09（issue #6580）：`/settings` 的守卫码由 `system:manage` 改为 `production:view` ——
  // 与菜单节点码、该页第一屏生产域读码同源（合并后的入口必须对真实配置者可见：operator /
  // product_manager 持该读码、不持 `system:manage`）。经营域（企业信息 / AI 客服 / 工人端页面 /
  // 通知设置）仍由各自的 `system:manage` **域级**门控 —— 该有意不一致已具名登记在
  // `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_PARITY_RESIDUALS`。
  { prefix: '/settings', code: 'production:view' },
  // issue #5246：知识库页同理 —— 页面本身的守卫用读码 knowledge:view
  //（增删改/发布/归档等写动作由后端 knowledge:manage 拦截，前端不重复表达写权限）。
  { prefix: '/knowledge', code: 'knowledge:view' },
  // issue #5291：岗位权限节点/页面按**读**码 `system:view`（改岗位仍由后端 system:manage 拦）。
  { prefix: '/roles', code: 'system:view' },
  { prefix: '/briefing', code: 'dashboard:view' },
  { prefix: '/dashboard', code: 'dashboard:view' },
  // 🔴 `/notifications`（通知中心）**有意不登记**（issue #5977 点名的 6 条未覆盖路由里的第 6 条）：
  // 菜单节点**无 `permissionCode`**（全员可见，与顶栏铃铛同源）；单一真值源 `rbac/manifest.json` 的
  // `_note` 逐字登记「**顶层无码项**（通知中心，根本没有权限门控）……本清单照现值填写（**不补、不猜**）」
  //（该类项的真实性由 `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的
  // 「一级项层 / 独立项层」判据守着），且读端点无 `@RequirePermission`（只有「发送」挂 `system:manage`）
  // ⇒ **不凭空造码**。「它没有守卫码」这件事由 `tests/unit_ci_workflows/test_rbac_derived_pages.py`
  // 的 C5② 从**单一真值源**派生豁免（不是手写台账）；塞一个空码进来反而会让 C4（守卫码 == 该页 `gate`）判红。
  // 三层门控里它仍受「**登录即可见**」那一层保护 —— 未登录访问由 `components/auth-guard.tsx` 的
  // `protectedRoutePrefixes` 送回登录页（**不是**权限码那一层，两件事不混写）。
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

  // 主动新手引导（issue #5989 · P2）：**首次进入某个已登记页面** ⇒ 递一轮「进页」事件，
  // 黄金策在对话区主动发一条**导航提示**（在哪一页 / 这页能做什么）。
  // 前端**不做任何判定**（哪一页能推、推什么、推几次：唯一真值在服务端
  // `backend/ai-agent-service/app/context/menu_navigator.py` + `app/api/chat.py`）；
  // 服务端回静默流时这里什么都不渲染。`/chat` 是黄金策自己的会话页，不推。
  useEffect(() => {
    if (permissionDenied || pathname.startsWith('/chat')) return
    void useChatStore.getState().notifyPageEnter(pathname)
  }, [pathname, permissionDenied])

  const handleToggle = () => {
    manualToggle.current = true
    setCollapsed(prev => !prev)
  }

  if (permissionDenied) {
    // 🔴 issue #6669 第 6 条：403 终态面提到 `@/components/common/AccessDenied`（**纯展示、不吃权限码**
    // —— 结构上就没有回显内部标识的入口）。权限码仍在上面 `ROUTE_PERMISSION_MAP` 的判定里，
    // 那是它的正当用途；**不上商家屏**。
    return <AccessDenied />
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
            底部锚定内容（如分页）不被右下角黄金策浮动按钮（FAB）遮挡（#3070）。
            ⚠️ 勿改回 p-4 sm:p-6：Tailwind 中 padding 简写会覆盖 padding-bottom，pb-24 失效

            🔴 issue #6687：**右侧**同理 —— FAB 是 `fixed bottom-6 right-6 w-14 h-14`（56×56，
            见 frontend/admin-web/src/components/ai-assistant/FloatingAssistant.tsx），
            而满宽表格的「操作」列正好落在它那个矩形里（命中测试实测：点「推荐」被浮球吃掉）。
            `pr-20`（= 80px ≥ 56px FAB 宽 + 16px 余量）把内容右边界推到 FAB 左侧之外 —— 二者**不相交**。
            ⚠️ 判据钉的是「**FAB 宽度 + 16px 行业余量**」这个关系（见同页测试），别随手改小） */}
        <main className="flex-1 px-4 sm:px-6 pr-20 pt-4 sm:pt-6 pb-24">
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