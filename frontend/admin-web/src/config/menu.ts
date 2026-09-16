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
  /** 企业开关控制显隐（智能每日经营简报：开关 ∧ 角色，issue #3468） */
  briefingToggle?: boolean
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
      // 智能每日经营简报：企业开关开启才显示（sidebar 按 briefingEnabled 过滤，红线 3）
      { key: 'briefing', name: '每日简报', icon: 'Newspaper', path: '/briefing', permissionCode: 'dashboard:view', briefingToggle: true },
    ],
  },
  // UI-005/UI-011: 智能客服大类（#3094 米宝·在线对话 菜单入口已移除，智能体对话经右下角 FAB；均不可见时整组隐藏）
  // #2969: 知识库归入智能客服组
  {
    key: 'smart-customer-service',
    name: '智能客服',
    icon: 'MessageSquare',
    children: [
      { key: 'human-sessions', name: '在线接待', icon: 'Headphones', path: '/agent-workspace/human-sessions', permissionCode: 'agent:session' },
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
      // 加工单列表（issue #3340 加工单状态机）：用户要求置于订单列表正下方；复用 processing:manage ——
      // operator 已持有该码且同时具备 processing:view/update（API 权限），
      // 而 processing:view 的其它角色（客服/销售/财务）无 update，会看到按钮但 403。
      { key: 'processing-orders', name: '加工单', icon: 'FileText', path: '/processing-orders', permissionCode: 'processing:manage' },
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