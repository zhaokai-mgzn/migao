// 侧边栏菜单配置单一来源（#3002 与岗位权限弹窗共用）
// Sidebar.tsx 渲染用；roles 页「权限分配」按同一份配置渲染菜单化权限树，
// 保证「权限分配里看到的菜单」与「真实侧边栏菜单」始终一致（不再各自漂移）。
// 注意：与后端 AuthService.buildMenusByPermissions 保持同构 ——
// permissionCode 即 DB permissions.code（agent:session 等）。

export interface MenuItem {
  key: string
  name: string
  icon: string
  path: string
  adminOnly?: boolean
  permissionCode?: string
}

export interface MenuGroup {
  key: string
  name: string
  icon: string
  children: MenuItem[]
}

// 带子级的菜单组（#2969 菜单重构：七大组）
export const menuGroups: MenuGroup[] = [
  {
    key: 'workspace',
    name: '工作台',
    icon: 'LayoutDashboard',
    children: [
      { key: 'dashboard', name: '经营看板', icon: 'BarChart3', path: '/dashboard' },
    ],
  },
  // UI-005/UI-011: 智能客服大类（米宝·在线对话 在前；均不可见时整组隐藏）
  // #2969: 知识库归入智能客服组
  {
    key: 'smart-customer-service',
    name: '智能客服',
    icon: 'MessageSquare',
    children: [
      { key: 'mibao-chat', name: '米宝 · 在线对话', icon: 'MessageCircle', path: '/chat', permissionCode: 'agent:session' },
      { key: 'human-sessions', name: '人工客服', icon: 'Headphones', path: '/agent-workspace/human-sessions', permissionCode: 'agent:session' },
      { key: 'knowledge', name: '知识库', icon: 'BookOpen', path: '/knowledge', permissionCode: 'knowledge:manage' },
    ],
  },
  {
    key: 'product-center',
    name: '商品管理',
    icon: 'Store',
    children: [
      { key: 'products', name: '商品列表', icon: 'Package', path: '/products', permissionCode: 'product:list' },
      { key: 'processing', name: '加工项管理', icon: 'Scissors', path: '/processing', permissionCode: 'processing:manage' },
    ],
  },
  {
    key: 'trade-center',
    name: '订单管理',
    icon: 'ShoppingCart',
    children: [
      { key: 'orders', name: '订单列表', icon: 'ClipboardList', path: '/orders', permissionCode: 'order:list' },
      { key: 'after-sales', name: '售后工单', icon: 'ShieldCheck', path: '/after-sales', permissionCode: 'order:refund' },
    ],
  },
  // #2969: 客户管理组（客户列表 + 财务对账，财务由独立菜单并入）
  {
    key: 'customer-center',
    name: '客户管理',
    icon: 'UserCircle',
    children: [
      { key: 'customers', name: '客户列表', icon: 'UserCircle', path: '/customers', permissionCode: 'customer:view' },
      { key: 'finance', name: '财务对账', icon: 'Calculator', path: '/finance', permissionCode: 'finance:view' },
    ],
  },
  // #2969: 组织管理组（员工管理 + 岗位权限 + 企业基础信息）
  {
    key: 'org-center',
    name: '组织管理',
    icon: 'Building2',
    children: [
      { key: 'employees', name: '员工管理', icon: 'Users', path: '/employees', permissionCode: 'employee:list' },
      { key: 'roles', name: '岗位权限', icon: 'ShieldCheck', path: '/roles', permissionCode: 'system:manage' },
      { key: 'settings', name: '企业基础信息', icon: 'Building2', path: '/settings', permissionCode: 'system:manage' },
    ],
  },
]

// 一级独立菜单项（无子级，直接跳转，排在分组后面）
export const standaloneItems: MenuItem[] = [
  // 通知中心：全员可见（与顶栏铃铛一致，无需权限码）
  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications' },
]