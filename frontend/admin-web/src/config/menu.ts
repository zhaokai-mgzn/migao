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
// issue #5271 菜单重设计 + **本轮（用户 2026-09-29 裁定）再重排**：
// 信息架构**7 组 → 6 组**，仍 **21 项，一项不少不减**
// ══════════════════════════════════════════════════════════════════════════════
//
// ## 本轮（用户 2026-09-29 逐条裁定）改了什么 —— 四条
//
//   ① **加工项归生产管理**：`processing`（加工项管理 `/production/processing`）由
//      「商品与加工项」组移入「生产管理」组 —— 它本质是**加工定价资料**（加工费组合的
//      `items[]` 取自加工项目录），与「生产看板 / 工艺配置 / 计件工资」同域；
//      用户原话：「加工项应该属于生产管理」。
//   ② **客户侧独立成组**：「客户列表」+「售后工单」由「交易管理」移出，
//      与**原「智能客服」组**（在线接待 / 知识库）合并为**「客户服务」组**
//      （key = `customer-service`）—— 用户原话：「客户管理也不属于交易管理」
//      「收购（=售后）和客户管理应该属于一类？都属于服务客户的功能」。
//   ③ **交易管理只留「下单 → 收款」**：订单列表 + 财务对账（两项）。
//   ④ **「商品与加工项」→「商品」**：加工项搬走后原组名不再成立（组内只剩商品列表）。
//
// ## 为什么①②是本次的核心口径（证据 = 岗位权限矩阵，**零可见性 delta**）
//
// `RegistrationService` 的种子矩阵里，岗位 `customer_service` 的权限集**恰好 100% 覆盖**
// 「智能客服」组（`agent:session` / `knowledge:view`）与「客户列表 / 售后工单」
// （`customer:view` / `after_sales:view`）的全部 6 个码，而持这 6 个码的岗位只有
// 客服 / 运营 / admin ⇒ **这两个组今天就是同一批人在用**，分组却把它们切成两块。
// 合并对**所有**岗位的可见项**零变化**（纯分组归属）：码不动、路径不动、门控不动。
//
// ## 本轮**没改**的（有意）
//
//   · **不做第 4 处菜单源**：本文件仍是唯一前端真值源（判据见三源同构守卫）；
//   · **知识库仍留在「客户服务」组内**（用户 2026-09-29 裁定：不单独成项、不沉底）——
//     通知中心是**全局项**（无权限码、另有顶栏铃铛入口）故可沉底；知识库是**功能域模块**
//     （需 `knowledge:view`、且侧边栏是它**唯一**入口）⇒ 沉底代价不对称；
//   · **通知中心维持现状**（仍在可滚动 `nav` 尾部，本轮不做固定底栏）。
//
// ## 上一轮（issue #5271，用户 2026-09-23 裁定 = 方案 A「按业务动线重排」）的遗产
//
//   · 生产管理组按「加工执行 / 面料进出」**拆**出「仓储与物料」组（本轮保留）；
//   · 原「客户管理」组（`customer-center`）**已不存在**且**不得长回来**
//     —— 本轮新建的是 `customer-service`（新语义），不是它的复活；
//   · 组 key `production` → `production-center`（三源统一）。
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

// 带子级的菜单组（本轮 2026-09-29 重排：**六大组**；顺序即渲染顺序与三源比对顺序）
export const menuGroups: MenuGroup[] = [
  {
    key: 'workspace',
    name: '工作台',
    icon: 'LayoutDashboard',
    children: [
      // issue #5699（P4）：节点码 = 该页第一屏读码 `dashboard:view`（5 个读端点与前端路由守卫同码）。
      // 此前本节点**无码**（全员可见）而页面/守卫都要码 ⇒ 判据 12 的残留 + 零权限自建岗位点进去 403。
      { key: 'dashboard', name: '经营看板', icon: 'BarChart3', path: '/dashboard', permissionCode: 'dashboard:view', keywords: ['jycb', 'kanban', '看板'] },
      // 智能每日经营简报：企业开关开启才显示（sidebar 按 briefingEnabled 过滤，红线 3）
      { key: 'briefing', name: '每日简报', icon: 'Newspaper', path: '/briefing', permissionCode: 'dashboard:view', briefingToggle: true, keywords: ['mrjb', 'jianbao', '简报', '日报'] },
    ],
  },
  // 客户服务（本轮 2026-09-29 用户裁定**新建**）：原「智能客服」组（在线接待 / 知识库）
  // + 原「交易管理」组的客户侧两项（客户列表 / 售后工单）**合并为一个组**。
  //
  // ## 为什么合并（用户原话 + 零 delta 证据）
  //
  // 用户：「收购（售后）和客户管理应该属于一类？都属于服务客户的功能」
  //      「智能客服和客户管理是否应该合并到一个大菜单下？」⇒ 裁定合并。
  // 证据（岗位权限矩阵，`RegistrationService` 种子表）：`customer_service` 岗位权限集**恰好
  // 100% 覆盖**本组 4 项的全部码（`agent:session` / `knowledge:view` / `customer:view` /
  // `after_sales:view`），持这批码的岗位只有 客服 / 运营 / admin ⇒ 这 4 项**本就是同一批人在用**。
  // 合并**所有岗位可见项零变化**（纯分组归属：码 / 路径 / 门控一字不动）。
  //
  // ## 组名为什么叫「客户服务」而不是沿用「智能客服」
  //
  // 组内除「在线接待」外都是**客户侧业务项**（客户列表 / 售后工单）—— 沿用「智能客服」会让
  // 后两项名不副实（正是用户指出的「交易管理装不下客户管理」的同型问题）。
  //
  // ## 保留项（漏带 = 静默回退别人刚修的授权口径）
  //
  //   · `knowledge:view`（issue #5246）：知识库用**读**码 —— 「看知识库」与「改知识库」是两件事；
  //   · 知识库**仍留在本组内**（用户 2026-09-29 裁定：不单独成项、不沉底 —— 通知中心是全局项
  //     （无码 + 另有顶栏铃铛入口）故可沉底，知识库是功能域模块且侧边栏是它**唯一**入口）。
  //   · 已删除的 `chat`「米宝 · 在线对话」节点**不得长回来**（#3094 从侧边栏移除，走右下角 FAB）。
  {
    key: 'customer-service',
    name: '客户服务',
    icon: 'Headphones',
    children: [
      { key: 'human-sessions', name: '在线接待', icon: 'Headphones', path: '/agent-workspace/human-sessions', permissionCode: 'agent:session', keywords: ['zxjd', 'jiedai', 'kefu', '客服', '人工'] },
      // #2969：客户列表原在「客户管理」组；#5271 曾并入交易管理组；本轮移入本组（服务客户动线）
      { key: 'customers', name: '客户列表', icon: 'UserCircle', path: '/customers', permissionCode: 'customer:view', keywords: ['khlb', 'kehu'] },
      { key: 'knowledge', name: '知识库', icon: 'BookOpen', path: '/knowledge', permissionCode: 'knowledge:view', keywords: ['zsk', 'zhishi', 'qa'] },
      // issue #5246（已合入 main）：售后工单节点用**读**码 `after_sales:view` —— `order:refund`
      // 是「处理退款」的写码，节点挂在它上面 = 「能看工单」必须连写权一起给。**必须保留**该码。
      { key: 'after-sales', name: '售后工单', icon: 'LifeBuoy', path: '/after-sales', permissionCode: 'after_sales:view', keywords: ['shgd', 'shouhou', 'tuihuan', '退换货'] },
    ],
  },
  // 交易管理（本轮 2026-09-29 收窄为**「下单 → 收款」两项**）：客户列表 / 售后工单是**服务客户**
  // 的动作，已移入「客户服务」组（用户原话：「客户管理也不属于交易管理」）。
  // 保留的这两项是同一动线：谁下单 → 收款对账。
  {
    key: 'trade-center',
    name: '交易管理',
    icon: 'ShoppingCart',
    children: [
      { key: 'orders', name: '订单列表', icon: 'ClipboardList', path: '/orders', permissionCode: 'order:list', keywords: ['ddlb', 'dingdan'] },
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
  // 判据：tests/unit_ci_workflows/test_agent_permission_parity.py（判据 3/4/10/12）。
  // 🔴 issue #5675：本组「计件工资」节点码与它页面**第一屏读端点**的码现已逐字同码
  // （读端点 `GET /api/admin/production/piecework/summary` 由 processing:manage 补齐到本读码
  //  —— #5291 漏改的第三个只读端点）；「智能派单」那处不一致**有意保留**并在判据 12 的
  // 残留台账里具名登记（两个方向的对齐都会改变某个岗位集合的可见性或可做性）。
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
      // issue #5699（P4）：节点码 = 该页第一屏读码 `processing:view`（此前挂 processing:manage ⇒ 节点码 ≠ 页面读码），
      // 路由守卫同批改挂读码（`app/(dashboard)/layout.tsx`）。
      { key: 'production-pool', name: '智能派单', icon: 'Layers', path: '/production/pool', permissionCode: 'processing:view', keywords: ['zndp', 'zhineng', 'paidan', '派单', 'ckb'] },
      // 加工项管理（本轮 2026-09-29 用户裁定：**由「商品与加工项」组移入本组**，原话
      // 「加工项应该属于生产管理」）—— 它是**加工定价资料**（加工费组合的 `items[]` 必须取自
      // 加工项目录的活跃加工项），与「生产看板 / 工艺配置 / 计件工资」同域
      //（同组内「建组合发现缺加工项要跳到另一个菜单组去建」的割裂就此消除）。
      //
      // 沿革（**一字不动地保留**，只改归属）：
      //   · issue #4490（用户裁定 2026-09-19；同日规格修订「合并后的菜单放入到商品管理大菜单下」）：
      //     「加工项管理」(/production/processing) 与「加工费管理」(/production/processing-fees)
      //     **合并为单一入口**；本次移组**不撤销该合并**（仍是同一入口、同一页）；
      //   · issue #4542（用户裁定 2026-09-19）：菜单名 = **「加工项管理」**（与服务端同名）；
      //   · ⚠️ **名字不再提「加工费」，但功能一个没减**：本页仍是**两个 tab**（`加工项` / `加工费组合`，
      //     沿用 #4482 在工艺配置确立的范式）——「加工费组合」定价面**原样保留**，改的只是**菜单名**；
      //     读到这里请勿以为加工费管理被删（能力断言在 processing-fees.test.tsx，一条不少）；
      //   · 节点码自 issue #5291 起 = 生产域**读**码 `production:view`（页内写动作仍 `processing:manage`）；
      //   · 两个旧路径都保留为重定向（/processing、/production/processing-fees → 本路径），旧深链不 404。
      { key: 'processing', name: '加工项管理', icon: 'Scissors', path: '/production/processing', permissionCode: 'production:view', keywords: ['jgx', 'jiagong', 'jiagongfei', '加工费'] },
      // issue #4416：「工序库」与「工艺路线」合并为单一入口「工艺配置」——
      // 工序是**原子词汇**、路线是**用工序名拼出的有序序列**（后端护栏：序列引用的工序必须存在于
      // 工序库活跃行），拆成两个菜单时建路线发现缺工序要跳到另一个菜单去建。
      // 工序库半边 = 该页**左栏**；旧路径 /production/operations 保留为重定向（旧深链不 404）。
      // issue #5699（P4）：该页第一屏 6 个读端点此前跨两个码（路线规则族 4 个是 processing:manage）
      // ⇒ 按子菜单粒度整页收敛到**页面码** production:view（两码持有岗位集合逐值相同 ⇒ 零 delta；
      // 写面 POST/DELETE 路线规则、PUT 工序部位仍由 processing:manage 拦）。
      { key: 'production-process', name: '工艺配置', icon: 'Route', path: '/production/routings', permissionCode: 'production:view', keywords: ['gypz', 'gongyi', 'gongxu', 'luxian'] },
      { key: 'production-piecework', name: '计件工资', icon: 'Coins', path: '/production/piecework', permissionCode: 'production:view', keywords: ['jjgz', 'jijian', 'gongzi'] },
    ],
  },
  // issue #5271 **新组**：面料进出与消耗 —— 入库 → 批次 → 余料 → 省料，是**同一条物流动线**，
  // 原散在「生产管理」组里与加工执行混编（一个仓管找「入库单」时不该在「生产看板」旁边找）。
  // 权限码**不统一**且有意如此：入库单 = `inbound:view`（仓储动作，仓管/财务要看入库单，
  // 却不需要 processing:manage）；余料台账 = `processing:manage`（与 `RemnantController` 的
  // 类级码逐字同码）。⚠️ **省料看板不是同码**（issue #5675 的判据 12 首次发现并登记）：它的
  // 读端点在 `StockBatchController` 上沿用 `product:list` ⇒ 节点码与该页**第一屏读端点码**不一致，
  // 已具名登记在判据 12 的残留台账（本组旧注记「另两项与各自页面的类级码同码」对省料看板不成立）。
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
      // issue #5699（P4）：节点码 = 该页第一屏读码 `product:list`（StockBatchController 方法级注解），路由守卫同批同码。
      { key: 'production-saving-board', name: '省料看板', icon: 'TrendingDown', path: '/production/saving-board', permissionCode: 'product:list', keywords: ['slkb', 'shengliao', 'haoliao'] },
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
      { key: 'settings', name: '企业基础信息', icon: 'Settings', path: '/settings', permissionCode: 'system:manage', keywords: ['qyxx', 'shezhi', 'qiye'] },
    ],
  },
]

// 一级独立菜单项（无子级，**直接跳转**）
//
// ## 两个位置，语义不同（本轮 2026-09-29 定型）
//
//   · `standaloneTopItems` —— **顶部一级项**，渲染在**所有分组之前**：
//     「商品管理」。用户 2026-09-29 裁定「商品列表改成商品管理，直接作为一级菜单使用」——
//     它是**唯一成员**的组会退化成一个没有分组的名字（点开只为看一项），故**不做单成员组**，
//     改为一级项平铺。**它是「分组」之外的第一梯队**：与分组同级、一眼可见、无需展开。
//   · `standaloneItems` —— **尾部项**，渲染在**所有分组之后**：
//     「通知中心」（全员可见，与顶栏铃铛一致，无需权限码）。
//
// 🔴 两个数组**都是导航**：进 ⌘K 索引（`flattenMenu` 的 `top` + `bottom`）、进三源同构守卫、
//    进面包屑覆盖判据（PG-038 按菜单项 `path` 穷举，本文件是它的输入面）。
export const standaloneTopItems: MenuItem[] = [
  // 商品管理（本轮 2026-09-29 用户裁定：**由「商品与加工项」组升为一级菜单项**，原话
  // 「商品列表改成商品管理，直接作为一级菜单使用」）。
  // · 组名/菜单名取值：用户原话是「商品列表改成商品管理」⇒ 菜单名 = **「商品管理」**；
  // · 路径与权限码一字不动（`/products`、`product:list`）⇒ 纯信息架构调整，零授权 delta；
  // · 与它同动线的「加工项管理」已移入「生产管理」组 ⇒ 原「商品与加工项」组（`product-center`）
  //   **不再存在**（组内已空）。原组里的两个动作码节点（`product:create` / `product:category`）
  //   由服务端权限树承载（判据里的 `ACTION_NODES` 按**节点归属组**登记）。
  { key: 'products', name: '商品管理', icon: 'Package', path: '/products', permissionCode: 'product:list', keywords: ['splb', 'spgl', 'shangpin', '商品'] },
]

export const standaloneItems: MenuItem[] = [
  // 通知中心：全员可见（与顶栏铃铛一致，无需权限码）
  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications', keywords: ['tzx', 'tongzhi', 'xiaoxi'] },
]