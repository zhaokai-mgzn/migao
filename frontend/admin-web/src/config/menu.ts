// 侧边栏菜单配置单一来源（#3002 与岗位权限弹窗共用）
// Sidebar.tsx 渲染用；roles 页「权限分配」按同一份配置渲染菜单化权限树，
// 保证「权限分配里看到的菜单」与「真实侧边栏菜单」始终一致（不再各自漂移）。
// 注意：与后端 AuthService.buildMenusByPermissions 保持同构 ——
// permissionCode 即 DB permissions.code（agent:session 等）。
// 🔴 issue #5217 裁决：**图标是前端专属**（服务端不下发 icon，同构判据**不比这一维**）——
// 本文件的 `icon` 即图标的唯一真值源，改它不会与服务端漂移；
// 判据：tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py。
//
// ══════════════════════════════════════════════════════════════════════════════
// issue #5271 菜单重设计：信息架构按**业务动线**重排（7 组 / 21 项，一项不少不减）
// ══════════════════════════════════════════════════════════════════════════════
//
// ## 为什么重排（现状诊断，证据见 issue #5271）
//
// 重设计前「生产管理」是 **7 项的杂物抽屉**，把四种不同使用场景混编在一起：
// 决策屏（生产看板 / 智能派单 / 省料看板）+ 台账（余料台账 / 入库单）
// + 基础配置（工艺配置）+ 结算（计件工资）—— 一个生产主管找「入库单」与找「省料看板」
// 是两件事，却挤在同一个折叠组里；而「商品管理」只有 2 项。
//
// ## 重排口径（用户 2026-09-23 裁定 = 方案 A「按业务动线重排」）
//
//   · **拆的是语义不是数量**：生产管理组按「加工执行 / 面料进出」拆成两组；
//   · **并的是动线**：客户列表与财务对账并入交易组（谁下单 → 单到哪 → 售后 → 收款对账），
//     原「客户管理」组（`customer-center`）因此**不再存在**；
//   · **不动的**：工作台、智能客服、组织管理三组的成员与名称（无证据支持改动）。
//
// ## 硬约束（改动本文件前必读）
//
//   🔴 本文件与 **两处服务端**必须**同批**改，否则「岗位权限页勾得动、侧边栏看不到」
//      （或反过来）：
//        ① `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE`
//        ② `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `buildMenusByPermissions`
//      判据：`tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`（#5271 起比对**全树**：
//      组 key + 组名 + 组顺序，以及导航型节点名）。
//   🔴 **改了组名或菜单名 ⇒ 必须同批改 `frontend/admin-web/src/components/layout/Header.tsx` 的
//      `ROUTE_BREADCRUMB_MAP`**（面包屑末项必须逐字 == 菜单名）。
//      判据：`frontend/admin-web/tests/unit/lib/menu-breadcrumb-coverage.test.tsx`（PG-038）。
//   ⚠️ 新增图标必须同时登记进 `frontend/admin-web/tests/setup.ts` 的 lucide 白名单，
//      否则任何渲染 Sidebar 的用例会**当场抛错**（不是静默）。

export interface MenuItem {
  key: string
  name: string
  icon: string
  path: string
  adminOnly?: boolean
  permissionCode?: string
  /** 企业开关控制显隐（智能每日经营简报：开关 ∧ 角色，issue #3468） */
  briefingToggle?: boolean
  /**
   * 命令面板（⌘K，issue #5271）检索用的**别名**：拼音首字母 / 常见叫法。
   * 只影响「搜得到」，不影响渲染与权限 —— 漏写只会让该项搜不到，不会有东西变红。
   */
  keywords?: string[]
}

export interface MenuGroup {
  key: string
  name: string
  icon: string
  children: MenuItem[]
}

// 带子级的菜单组（issue #5271 重设计：七大组按业务动线重排）
export const menuGroups: MenuGroup[] = [
  {
    key: 'workspace',
    name: '工作台',
    icon: 'LayoutDashboard',
    children: [
      { key: 'dashboard', name: '经营看板', icon: 'BarChart3', path: '/dashboard', keywords: ['jycb', 'kanban', '看板'] },
      // 智能每日经营简报：企业开关开启才显示（sidebar 按 briefingEnabled 过滤，红线 3）
      { key: 'briefing', name: '每日简报', icon: 'Newspaper', path: '/briefing', permissionCode: 'dashboard:view', briefingToggle: true, keywords: ['mrjb', 'jianbao', '简报', '日报'] },
    ],
  },
  // UI-005/UI-011: 智能客服大类（#3094 米宝·在线对话 菜单入口已移除，智能体对话经右下角 FAB；均不可见时整组隐藏）
  // #2969: 知识库归入智能客服组
  // 🔴 #5271 收口：本组在 `AuthService.buildMenusByPermissions` 里**多一个** `chat`「米宝 · 在线对话」
  // 节点（#3094 从侧边栏移除后服务端没跟）—— 属守卫当时**看不到**的漂移（它只比生产管理组）。
  // 现状：三源均为 2 项（在线接待 / 知识库），判据见三源同构守卫（#5271 起比对全树）。
  {
    key: 'smart-customer-service',
    name: '智能客服',
    icon: 'MessageSquare',
    children: [
      { key: 'human-sessions', name: '在线接待', icon: 'Headphones', path: '/agent-workspace/human-sessions', permissionCode: 'agent:session', keywords: ['zxjd', 'jiedai', 'kefu', '客服', '人工'] },
      // issue #5246（已合入 main）：知识库节点用**读**码 `knowledge:view` —— 读写拆码后
      // 「看知识库」与「改知识库」是两件事；节点挂写码会让只读角色（客服/运营）看不到菜单。
      // #5271 重排本组时**必须保留**该码（漏带 = 静默回退别人刚修的授权口径）。
      { key: 'knowledge', name: '知识库', icon: 'BookOpen', path: '/knowledge', permissionCode: 'knowledge:view', keywords: ['zsk', 'zhishi', 'qa'] },
    ],
  },
  // issue #5271：「商品管理」→「商品与加工项」——组内第二项（加工项管理）本身是**加工定价资料**，
  // 组名带上它，商家才知道「加工费组合去哪配」。
  {
    key: 'product-center',
    name: '商品与加工项',
    icon: 'Store',
    children: [
      { key: 'products', name: '商品列表', icon: 'Package', path: '/products', permissionCode: 'product:list', keywords: ['splb', 'shangpin'] },
      // issue #4490（用户裁定 2026-09-19；同日**规格修订**：「加工项管理和加工费管理**合并后的菜单
      // 放入到商品管理大菜单下**」）：「加工项管理」(/production/processing) 与「加工费管理」
      // (/production/processing-fees) **合并为单一入口** —— 两者是同一业务域、同一入口
      //（节点码自 issue #5291 起 = 生产域**读**码 production:view；页内写动作仍 processing:manage）、
      // 同一业务域（加工费组合的 items[] 必须取自加工项目录的活跃加工项），拆开意味着
      // 「建组合发现缺加工项要跳到另一个菜单组去建」。
      // issue #4542（用户裁定 2026-09-19：把菜单名从 #4490 的合并名改回「加工项管理」）：
      // 菜单名 = **「加工项管理」** —— 与**服务端既有菜单名同名**（`MenuController.java` 与
      // `AuthService.java` 的菜单表一直叫「加工项管理」），本次改名顺带消掉这条**前端漂移**
      // （#4440「菜单三处同构实为漂移」登记的同款形态）。
      // ⚠️ **名字不再提「加工费」，但功能一个没减**：本页仍是**两个 tab**（`加工项` / `加工费组合`，
      // 沿用 #4482 在工艺配置确立的范式，不平铺）——「加工费组合」定价面**原样保留**，改的只是**菜单名**；
      // 读到这里请勿以为加工费管理被删（它的能力断言在 processing-fees.test.tsx，一条不少）。
      // 两个旧路径都保留为重定向（/processing、/production/processing-fees → 本路径），旧深链不 404。
      // 图标沿用原「加工项管理」的 Scissors（本项默认 tab 就是「加工项」）。
      // ⚠️ **路径有意不改**：改路径会让刚上线的两条旧路径重定向再叠一层。
      { key: 'processing', name: '加工项管理', icon: 'Scissors', path: '/production/processing', permissionCode: 'production:view', keywords: ['jgx', 'jiagong', 'jiagongfei', '加工费'] },
    ],
  },
  // issue #5271：原「订单管理」+ 原「客户管理」组的两个项 → **交易管理**（一条动线：
  // 谁下单 → 单到哪 → 售后 → 收款对账）。客户列表与财务对账原本各自挂在「客户管理」组，
  // 商家真实动线却要跨组反复横跳。
  {
    key: 'trade-center',
    name: '交易管理',
    icon: 'ShoppingCart',
    children: [
      { key: 'orders', name: '订单列表', icon: 'ClipboardList', path: '/orders', permissionCode: 'order:list', keywords: ['ddlb', 'dingdan'] },
      // issue #5246（已合入 main）：售后工单节点用**读**码 `after_sales:view` —— `order:refund`
      // 是「处理退款」的写码，节点挂在它上面 = 「能看工单」必须连写权一起给。
      // #5271 重排本组时**必须保留**该码。
      { key: 'after-sales', name: '售后工单', icon: 'ShieldCheck', path: '/after-sales', permissionCode: 'after_sales:view', keywords: ['shgd', 'shouhou', 'tuihuan', '退换货'] },
      // #2969：客户列表原在「客户管理」组；#5271 并入交易管理组（动线合并，见上）
      { key: 'customers', name: '客户列表', icon: 'UserCircle', path: '/customers', permissionCode: 'customer:view', keywords: ['khlb', 'kehu'] },
      // #2969：财务对账原在「客户管理」组；#5271 并入交易管理组（订单 → 收款 → 对账）
      { key: 'finance', name: '财务对账', icon: 'Calculator', path: '/finance', permissionCode: 'finance:view', keywords: ['cw', 'caiwu', 'duizhang', '对账'] },
    ],
  },
  // issue #5271：生产管理组**由 7 项降到 4 项** —— 只留「加工执行 + 工艺配置 + 结算」；
  // 面料进出与消耗（入库单 / 余料台账 / 省料看板）拆到「仓储与物料」组。
  // issue #4203/#4205 后端半边：本组节点权限码原统一 processing:manage（operator 已持有该码）。
  // 🔴 issue #5291：生产域新增**读**码 `production:view` —— 「生产看板 / 工艺配置 / 计件工资」
  // 三个节点改用读码（「看得见这一页」与「改得动生产数据」就此分开）；「智能派单」仍按
  // processing:manage（其读端点用 processing:view、且无 Agent 工具调用，不在本单射程）。
  // 判据：tests/unit_ci_workflows/test_agent_permission_parity.py（判据 3/4/10）。
  // issue #4357：「加工单」并入本组 —— 但它**不新增菜单项**：加工单列表页与「生产看板」
  // 是同一实体、同一端点（processingOrderApi.list）的两份渲染 ⇒ 合并为单一入口「生产看板」
  //（列表页能力：关键词/状态筛选、重置、刷新、商品与数量快照摘要、查看跳订单详情 全部并入看板）。
  // 旧路径 /processing-orders 保留为重定向；子路由 /processing-orders/{id}/production（生产明细）不变。
  // ⚠️ 组 key 三源必须一致：本组 `production` → #5271 统一为 **`production-center`**
  //（重设计前 `AuthService` 用 `production-center` 而本文件与 `MenuController` 用 `production`
  // —— 属守卫当时**看不到**的 key 漂移，本次一并收口）。
  {
    key: 'production-center',
    name: '生产管理',
    icon: 'Factory',
    children: [
      // /production = 加工单唯一入口（issue #4357 与原「加工单」菜单合并）
      { key: 'production-board', name: '生产看板', icon: 'ClipboardCheck', path: '/production', permissionCode: 'production:view', keywords: ['sckb', 'shengchan', 'jiagongdan', '加工单'] },
      // 智能派单（issue #5177）：池化派单的**决策屏** —— 加急插队区（不进池、立即单派）
      // + 物料分组成批区（勾选 → 预览 → 一键成批派单）+ 超时未派告警。
      { key: 'production-pool', name: '智能派单', icon: 'Layers', path: '/production/pool', permissionCode: 'processing:manage', keywords: ['zndp', 'zhineng', 'paidan', '派单', 'ckb'] },
      // issue #4416：「工序库」与「工艺路线」合并为单一入口「工艺配置」——
      // 工序是**原子词汇**、路线是**用工序名拼出的有序序列**（后端护栏：序列引用的工序必须存在于
      // 工序库活跃行），拆成两个菜单时建路线发现缺工序要跳到另一个菜单去建。
      // 工序库半边 = 该页**左栏**；旧路径 /production/operations 保留为重定向（旧深链不 404）。
      { key: 'production-process', name: '工艺配置', icon: 'Route', path: '/production/routings', permissionCode: 'production:view', keywords: ['gypz', 'gongyi', 'gongxu', 'luxian'] },
      { key: 'production-piecework', name: '计件工资', icon: 'Calculator', path: '/production/piecework', permissionCode: 'production:view', keywords: ['jjgz', 'jijian', 'gongzi'] },
    ],
  },
  // issue #5271 **新组**：面料进出与消耗 —— 入库 → 批次 → 余料 → 省料，是**同一条物流动线**，
  // 原散在「生产管理」组里与加工执行混编（一个仓管找「入库单」时不该在「生产看板」旁边找）。
  // 权限码**不统一**且有意如此：入库单 = `inbound:view`（仓储动作，仓管/财务要看入库单，
  // 却不需要 processing:manage），另两项 = `processing:manage`（与各自页面的
  // `@RequirePermission` 类级码同码）。
  {
    key: 'inventory-center',
    name: '仓储与物料',
    icon: 'Boxes',
    children: [
      // 入库单（V111，issue #5034）：商品布料入库 —— 建单（草稿）/ 过账（自动生成批次号 +
      // 自动加库存 + 移动加权平均成本）/ 作废（仅草稿）；批次与库存台账可查。
      // ⚠️ 权限码独立（inbound:view）—— 塞进 processing:manage 的判定里会让
      // 「有 inbound:view、没有 processing:manage」的人看不到菜单（#4203 点名的同族坑）。
      { key: 'inbound-orders', name: '入库单', icon: 'PackageOpen', path: '/inbound-orders', permissionCode: 'inbound:view', keywords: ['rkd', 'ruku', 'caigou'] },
      // 余料台账（issue #5146 建页 / issue #5191 进侧边栏）：L2 批次余量的台账面。
      // 权限码沿用 processing:manage —— 与 `RemnantController` 的类级 `@RequirePermission("processing:manage")`
      // 逐字同码（**不放宽也不收紧**既有门禁；新开权限码反而会让既有 operator 岗位凭空多一处授权缺口）。
      { key: 'production-remnants', name: '余料台账', icon: 'Recycle', path: '/production/remnants', permissionCode: 'processing:manage', keywords: ['yltz', 'yuliao', 'huishou'] },
      // 省料看板（issue #5159）：L2 批次余量分档聚合 + L3 单位产出的面料消耗。
      // 一屏同时给两条指标（①「剩余 ≤0.2m 的批次占比」②「入库/采购总米数」）并把
      // 「单看①会被排料省料误导」写在页面上；存量导入批次单独成组、不与切换后混算。
      { key: 'production-saving-board', name: '省料看板', icon: 'BarChart3', path: '/production/saving-board', permissionCode: 'processing:manage', keywords: ['slkb', 'shengliao', 'haoliao'] },
    ],
  },
  // #2969: 组织管理组（员工管理 + 岗位权限 + 企业基础信息）
  {
    key: 'org-center',
    name: '组织管理',
    icon: 'Building2',
    children: [
      { key: 'employees', name: '员工管理', icon: 'Users', path: '/employees', permissionCode: 'employee:list', keywords: ['yggl', 'yuangong'] },
      // issue #5291：岗位权限节点改挂**读**码 `system:view`（企业基础信息仍是 system:manage）。
      { key: 'roles', name: '岗位权限', icon: 'ShieldCheck', path: '/roles', permissionCode: 'system:view', keywords: ['gwqx', 'jiaose', 'quanxian'] },
      { key: 'settings', name: '企业基础信息', icon: 'Building2', path: '/settings', permissionCode: 'system:manage', keywords: ['qyxx', 'shezhi', 'qiye'] },
    ],
  },
]

// 一级独立菜单项（无子级，直接跳转，排在分组后面）
export const standaloneItems: MenuItem[] = [
  // 通知中心：全员可见（与顶栏铃铛一致，无需权限码）
  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications', keywords: ['tzx', 'tongzhi', 'xiaoxi'] },
]