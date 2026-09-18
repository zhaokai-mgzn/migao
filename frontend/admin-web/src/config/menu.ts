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
      // 「加工单」已迁出本组（issue #4357）：它是 producing 阶段的**生产**单据
      // （docs/design/processing-order-design.md「不是平行单据」），权限码也一直是 processing:manage
      // ⇒ 留在订单管理组会让「分组」与「权限边界」错位。现并入生产管理组，
      // 且与「生产看板」**合并为单一入口**（原列表页 /processing-orders 改为重定向）。
      // #3340 的「置于订单列表正下方」与 #4305 的「发加工唯一入口 = 订单详情页」约束的是**动作入口**，
      // 不约束**台账归属** —— 从订单发起加工、到生产管理看进度与计件，本来就是两条动线。
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
  // issue #4203：生产管理组（生产看板 / 工序库 / 工艺路线 / 计件工资）。
  // 权限码统一 processing:manage —— 与既有「加工项管理」同一口径（operator 已持有该码，
  // 且同时具备 processing:view/update 的 API 权限）。
  // issue #4357：「加工单」并入本组 —— 但它**不新增菜单项**：加工单列表页与「生产看板」
  // 是同一实体、同一端点（processingOrderApi.list）的两份渲染 ⇒ 合并为单一入口「生产看板」
  // （列表页能力：关键词/状态筛选、重置、刷新、商品与数量快照摘要、查看跳订单详情 全部并入看板）。
  // 旧路径 /processing-orders 保留为重定向；子路由 /processing-orders/{id}/production（生产明细）不变。
  {
    key: 'production',
    name: '生产管理',
    icon: 'Factory',
    children: [
      { key: 'production-board', name: '生产看板', icon: 'ClipboardCheck', path: '/production', permissionCode: 'processing:manage' },
      // issue #4416：「工序库」与「工艺路线」合并为单一入口「工艺配置」——
      // 工序是**原子词汇**、路线是**用工序名拼出的有序序列**（后端护栏：序列引用的工序必须存在于
      // 工序库活跃行），拆成两个菜单时建路线发现缺工序要跳到另一个菜单去建。
      // 工序库半边 = 该页**左栏**；旧路径 /production/operations 保留为重定向（旧深链不 404）。
      { key: 'production-process', name: '工艺配置', icon: 'Route', path: '/production/routings', permissionCode: 'processing:manage' },
      // issue #4386：加工费**组合**定价（不是每个加工项一个价）—— 商家配置面，下单时由系统按选配匹配
      { key: 'production-processing-fees', name: '加工费管理', icon: 'BadgeDollarSign', path: '/production/processing-fees', permissionCode: 'processing:manage' },
      { key: 'production-piecework', name: '计件工资', icon: 'Calculator', path: '/production/piecework', permissionCode: 'processing:manage' },
    ],
  },
]

// 一级独立菜单项（无子级，直接跳转，排在分组后面）
export const standaloneItems: MenuItem[] = [
  // 通知中心：全员可见（与顶栏铃铛一致，无需权限码）
  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications' },
]