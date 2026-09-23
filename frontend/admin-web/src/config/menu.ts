// 侧边栏菜单配置单一来源（#3002 与岗位权限弹窗共用）
// Sidebar.tsx 渲染用；roles 页「权限分配」按同一份配置渲染菜单化权限树，
// 保证「权限分配里看到的菜单」与「真实侧边栏菜单」始终一致（不再各自漂移）。
// 注意：与后端 AuthService.buildMenusByPermissions 保持同构 ——
// permissionCode 即 DB permissions.code（agent:session 等）。
// 🔴 issue #5217 裁决：**图标是前端专属**（服务端不下发 icon，同构判据**不比这一维**）——
// 本文件的 `icon` 即图标的唯一真值源，改它不会与服务端漂移；
// 判据：tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py。

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
export const menuGroups: MenuGroup[] = [{
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
      // issue #5246：知识库节点由 knowledge:manage 改为**读**码 knowledge:view ——
      // 读写拆码后「看知识库」与「改知识库」是两件事；节点仍用写码会让只读角色
      // （客服/运营）看不到菜单。后端已同源改码（AuthService.buildMenusByPermissions /
      // MenuController.MENU_TREE），页面侧守卫见 app/(dashboard)/layout.tsx。
      { key: 'knowledge', name: '知识库', icon: 'BookOpen', path: '/knowledge', permissionCode: 'knowledge:view' },
    ],
  },
  
{
    key: 'product-center',
    name: '商品管理',
    icon: 'Store',
    children: [
      { key: 'products', name: '商品列表', icon: 'Package', path: '/products', permissionCode: 'product:list' },
      // issue #4490（用户裁定 2026-09-19；同日**规格修订**：「加工项管理和加工费管理**合并后的菜单
      // 放入到商品管理大菜单下**」）：「加工项管理」(/processing) 与「加工费管理」
      // (/production/processing-fees) **合并为单一入口**，**取代本组原「加工项管理」的位置**
      // —— 两者是同一权限码（processing:manage）、同一业务域（加工费组合的 items[] 必须取自
      // 加工项目录的活跃加工项），拆开意味着「建组合发现缺加工项要跳到另一个菜单组去建」。
      // issue #4542（用户裁定 2026-09-19：把菜单名从 #4490 的合并名改回「加工项管理」）：
      // 菜单名 = **「加工项管理」** —— 与**服务端既有菜单名同名**（`MenuController.java` 与
      // `AuthService.java` 的菜单表一直叫「加工项管理」），本次改名顺带消掉这条**前端漂移**
      // （#4440「菜单三处同构实为漂移」登记的同款形态）。
      // ⚠️ **名字不再提「加工费」，但功能一个没减**：本页仍是**两个 tab**（`加工项` / `加工费组合`，
      // 沿用 #4482 在工艺配置确立的范式，不平铺）—— 「加工费组合」定价面**原样保留**，改的只是**菜单名**；
      // 读到这里请勿以为加工费管理被删（它的能力断言在 processing-fees.test.tsx，一条不少）。
      // 两个旧路径都保留为重定向（/processing、/production/processing-fees → 本路径），旧深链不 404。
      // 图标沿用原「加工项管理」的 Scissors（本项默认 tab 就是「加工项」）。
      // ⚠️ **路径有意不改**：改路径会让刚上线的两条旧路径重定向再叠一层。
      { key: 'processing', name: '加工项管理', icon: 'Scissors', path: '/production/processing', permissionCode: 'processing:manage' },
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
      // issue #5246：售后工单节点由 order:refund 改为**读**码 after_sales:view ——
      // order:refund 是「处理退款」的写码，节点挂在它上面 = 「能看工单」必须连写权一起给。
      // 后端两处菜单源已同源改码（AuthService / MenuController），页面守卫见 layout.tsx。
      { key: 'after-sales', name: '售后工单', icon: 'ShieldCheck', path: '/after-sales', permissionCode: 'after_sales:view' },
    ],
  },
  // #2969: 客户管理组（客户列表 + 财务对账，财务由独立菜单并入）
  
{
    key: 'production',
    name: '生产管理',
    icon: 'Factory',
    children: [
      { key: 'production-board', name: '生产看板', icon: 'ClipboardCheck', path: '/production', permissionCode: 'processing:manage' },
      // 池看板（issue #5177）：池化派单的**决策屏** —— 加急插队区（不进池、立即单派）
      // + 物料分组成批区（勾选 → 预览 → 一键成批派单）+ 超时未派告警。
      // 权限码沿用 processing:manage（与「生产看板」同权：都是加工/生产管理动作），
      // 且必须与 MenuController 的静态权限树、AuthService.buildMenusByPermissions
      // **三处同构**（漏一处 = 「岗位权限页勾得动、侧边栏看不到」）。
      { key: 'production-pool', name: '池看板', icon: 'Layers', path: '/production/pool', permissionCode: 'processing:manage' },
      // 省料看板（issue #5159）：L2 批次余量分档聚合 + L3 单位产出的面料消耗。
      // 一屏同时给两条指标（①「剩余 ≤0.2m 的批次占比」②「入库/采购总米数」）并把
      // 「单看①会被排料省料误导」写在页面上；存量导入批次单独成组、不与切换后混算。
      // 权限码沿用 processing:manage（与「生产看板」「池看板」同权），且必须与 MenuController 的
      // 静态权限树、AuthService.buildMenusByPermissions **三处同构**
      // （漏一处 = 「岗位权限页勾得动、侧边栏看不到」）。
      { key: 'production-saving-board', name: '省料看板', icon: 'BarChart3', path: '/production/saving-board', permissionCode: 'processing:manage' },
      // 余料台账（issue #5146 建页 / issue #5191 进侧边栏）：原先是「企业参数中心 → 余料回收」域的
      // **域内下钻页**，而同期新增的「池看板」「省料看板」都有菜单项 ⇒ 同批新页入口口径不一致
      // （用户裁定：补菜单，不登记成「有意不进侧边栏」）。
      // 权限码沿用 processing:manage —— 与 `RemnantController` 的类级 `@RequirePermission("processing:manage")`
      // 逐字同码（**不放宽也不收紧**既有门禁；新开权限码反而会让既有 operator 岗位凭空多一处授权缺口）。
      // 必须与 `MenuController` 的静态权限树、`AuthService.buildMenusByPermissions` **三处同构**
      // （漏一处 = 「岗位权限页勾得动、侧边栏看不到」）。
      { key: 'production-remnants', name: '余料台账', icon: 'Recycle', path: '/production/remnants', permissionCode: 'processing:manage' },
      // issue #4416：「工序库」与「工艺路线」合并为单一入口「工艺配置」——
      // 工序是**原子词汇**、路线是**用工序名拼出的有序序列**（后端护栏：序列引用的工序必须存在于
      // 工序库活跃行），拆成两个菜单时建路线发现缺工序要跳到另一个菜单去建。
      // 工序库半边 = 该页**左栏**；旧路径 /production/operations 保留为重定向（旧深链不 404）。
      { key: 'production-process', name: '工艺配置', icon: 'Route', path: '/production/routings', permissionCode: 'processing:manage' },
      // issue #4490 规格修订（用户 2026-09-19）：合并后的加工项入口（#4542 起菜单名「加工项管理」）**已移出本组**，归入
      // **商品管理**组（见 product-center 组内注释）—— 本组因此回到三项。
      { key: 'production-piecework', name: '计件工资', icon: 'Calculator', path: '/production/piecework', permissionCode: 'processing:manage' },
      // 入库单（V111，issue #5034）：商品布料入库 —— 建单（草稿）/ 过账（自动生成批次号 +
      // 自动加库存 + 移动加权平均成本）/ 作废（仅草稿）；批次与库存台账可查。
      // 权限码 inbound:view —— 与后端 @RequirePermission("inbound:view") 及
      // MenuController / AuthService.buildMenusByPermissions 的节点同构（三处同构，漏一处 =
      // 「岗位权限页勾得动、侧边栏看不到」）。
      { key: 'inbound-orders', name: '入库单', icon: 'PackageOpen', path: '/inbound-orders', permissionCode: 'inbound:view' },
    ],
  },

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
  // issue #4203：生产管理组（生产看板 / 工艺配置 / 计件工资）。
  // 权限码统一 processing:manage —— 本组三项同码（operator 已持有该码，
  // 且同时具备 processing:view/update 的 API 权限）。
  // issue #4490（含同日规格修订）：「加工项管理」+「加工费管理」合并后的入口（#4542 起菜单名
  // 回到「加工项管理」，与服务端同名）**不在本组**，在**商品管理**组
  // （用户裁定：「合并后的菜单放入到商品管理大菜单下」）。
  // issue #4357：「加工单」并入本组 —— 但它**不新增菜单项**：加工单列表页与「生产看板」
  // 是同一实体、同一端点（processingOrderApi.list）的两份渲染 ⇒ 合并为单一入口「生产看板」
  // （列表页能力：关键词/状态筛选、重置、刷新、商品与数量快照摘要、查看跳订单详情 全部并入看板）。
  // 旧路径 /processing-orders 保留为重定向；子路由 /processing-orders/{id}/production（生产明细）不变。
]

// 一级独立菜单项（无子级，直接跳转，排在分组后面）
export const standaloneItems: MenuItem[] = [
  // 通知中心：全员可见（与顶栏铃铛一致，无需权限码）
  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications' },
]