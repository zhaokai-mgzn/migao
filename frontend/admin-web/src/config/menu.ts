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
// issue #5271 菜单重设计 + 用户 **2026-09-29** 再重排 + 用户 **2026-10-06** 顺序重设计
// + 用户 **2026-10-17**（issue #7087）信息架构改判 + 用户 **2026-10-29**（issue #8086）第二轮：
// 现为 **28 个导航节点**（现取 2026-10-29）= **8 组 24 项** + 一级独立项 4（最前席位：经营看板 /
// 报表中心；尾席位：企业基础设置；尾部项：通知中心）
// （2026-10-24 issue #7593：「审批中心」菜单项撤除、入口改到顶栏 `ApprovalBell` —— 见交易管理组内注释）
// （2026-10-29 issue #8086：新增「基础资料」（商品管理 / 客户列表 / 供应商 / 价格本）与「质量」
//  （质检记录 / 返工单）两组 —— 商品管理由一级项降入组内，尾席位只剩「企业基础设置」）
// ══════════════════════════════════════════════════════════════════════════════
//
// ## 本轮（用户 2026-10-17 逐字两条裁定，issue #7087）
//
//   ① 「**经营看板直接作为一级菜单，移除工作台**，这样用户一进来就很直观的看到经营看板了」
//      ⇒「工作台」组（组 key `workspace`）**整组撤销**；「经营看板」升为一级项，落在**最前席位**
//      （`standaloneHeadItems`，渲染在**所有分组之前**）。为什么必须最前、而不是与「商品管理」
//      并列的尾席位：`lib/menu-nav.ts` 的 `landingPath()` = **第一个可见菜单项**（issue #6758）
//      ⇒ 尾席位会让登录落点变成「在线接待」；放最前才逐字满足「一进来就直观看到经营看板」。
//      权限码一字不动（`dashboard:view`）⇒ **零授权 delta**。
//   ② 「**不要新增每日简报的菜单**……那一行分析结论本来就在经营看板上了，不需要额外一个菜单，移除掉」
//      ⇒「每日简报」菜单项删除（连同 `briefingToggle` 这一菜单级过滤机制）—— 企业开关继续只驱动
//      **经营看板上的结论卡**（`BriefingCard`）：开关关 = 看板无结论文字；开关开 = 有结论文字。
//      路由 `/briefing` 保留为重定向薄壳 → `/dashboard`（旧深链不 404；仓内先例 = 加工项管理 /
//      工艺配置 / 参数总览三个被移除的菜单项）。
//
// ## 三个席位（`standalone*` 三个数组，**位置语义各不相同**，别按名字猜）
//
//   · `standaloneHeadItems` —— **最前席位**：渲染在**所有分组之前**（本轮新增，用户 2026-10-17 裁定
//     给「经营看板」）；
//   · `standaloneTopItems`  —— **尾席位**：渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY` 那个组**之后**
//     （用户 2026-10-06 裁定；名字里的 `Top` 是「**升为顶层一级项**」的历史叫法，**与渲染位无关**）；
//   · `standaloneItems`     —— **尾部独立项**：渲染在**所有分组之后**（「通知中心」）。
//
//   三个数组**都是导航**：进 ⌘K 索引（`flattenMenu` 的 `head` / `top` / `bottom`）、进三源同构守卫、
//   进面包屑覆盖判据（PG-038 按菜单项 `path` 穷举，本文件是它的输入面）。
//
// ## 本轮（用户 2026-10-06 直接要求「子菜单顺序要重新设计下，让整个产品的菜单顺序也自洽」）
//
// 用户逐字裁定 = **方案 A1**：**组名 / 组归属 / 权限码 / 路径一字不动**，只改**渲染顺序**
// （组顺序不动）+ 一级项落位 ⇒ **对所有岗位的可见项集合零 delta**（纯顺序）。
//
//   ① **「商品管理」一级项沉底**：原插在「工作台」组之后（用户 2026-10-01 裁定），现改为
//      **排在所有分组之后**（仍是一级项、不进任何组，键不变 `products`）—— 组名即「分组」，
//      渲染在组与组**之间**让「大菜单」这个概念自相矛盾（它没有任何兄弟项，孤零零卡在
//      工作台与客户服务之间）。用户本轮口径：**11 个大菜单项之间并列**；
//      实现 = `STANDALONE_TOP_AFTER_GROUP_KEY` = **最后一个组**（`org-center`）
//      ⇒ head = 全部 6 组、tail = 空（渲染位仍由 `splitGroupsAtTopItemSlot` 单点决定）。
//   ② **客户服务**：`在线接待 → 知识库 → 售后工单 → 客户列表`
//      —— 原「客户列表」把「在线接待 / 知识库」这对**接待时并用**的项隔开（客服边接待边查知识库）；
//      改为「① 接待与工具 → ② 售后（工单，接待的第二出口） → ③ 客户档案（查档/建档，最低频）」。
//      ⚠️ 该轮的组内顺序（`加工项管理 → 工艺配置 → 生产看板 → 智能派单 → 计件工资`）已被 **#6580**
//      （2026-10-09）覆盖：前两项菜单项**已移除**，本组现为 `生产看板 → 智能派单 → 计件工资`。
//      （保留原记载的理由：它是「加工项是派单机的输入」这一判断的历史依据。）
//   ④ **仓储与物料**：`入库单 → 库存明细 → 发货单 → 余料台账 → 省料看板`
//      —— 原序把「发货单」（出库）夹在入库单之后、把「库存明细」甩到组末并被「省料看板」隔开；
//      改为「**单据（进 → 账 → 出）→ 账（余料）→ 分析（省料）**」：
//      进仓（入库单）之后第一件要看的就是**账**（库存明细 = SKU 变化流水，issue #6404），
//      再是出口单据（发货单），然后才是两类**分析/台账**面（余料台账是裁下的小件、省料看板是聚合视图）。
//
// ## 本轮**不动**的（有意）
//
//   · **组顺序不动**（工作台 → 客户服务 → 交易管理 → 生产管理 → 仓储与物料 → 组织管理）——
//     它按「我的 → 客户 → 交易 → 生产 → 物料 → 组织」动线已自洽，本轮只治**组内顺序**与一级项落位；
//   · **组名一律不改**（用户 2026-10-06 裁定「只动顺序」）⇒ 面包屑 `ROUTE_BREADCRUMB_MAP` 无需改；
//   · **权限码 / 路径 / 门控一字不动** ⇒ 零授权 delta（判据面：岗位矩阵用例 UI-085）。
//
// ## 历史锚点（用户 2026-09-29 逐条裁定）改了什么 —— 四条
//
//   ① **加工项归生产管理**：`processing`（加工项管理 `/production/processing`）由
//      「商品与加工项」组移入「生产管理」组 —— 它本质是**加工定价资料**（加工费组合的
//      `items[]` 取自加工项目录），与「生产看板 / 工艺配置 / 计件工资」同域；
//      用户原话：「加工项应该属于生产管理」。
//   ② **客户侧独立成组**：「客户列表」+「售后工单」由「交易管理」移出，
//      与**原「智能客服」组**（在线接待 / 知识库）合并为**「客户服务」组**
//      （key = `customer-service`）—— 用户原话：「客户管理也不属于交易管理」
//      「收购（=售后）和客户管理应该属于一类？都属于服务客户的功能」。
//   ③ **交易管理只留「下单 → 收款」**：销售订单 + 财务对账（两项）。
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
//   🔴 **改了一级项的位置 ⇒ 三源同批**：本文件的 `STANDALONE_TOP_AFTER_GROUP_KEY` +
//      `MenuController.MENU_TREE` 的顶层节点顺序 + `AuthService` 顶层 `menus.add` 的文档位置
//      （#5877；只改一处 ⇒ 三源同构守卫的「顶层布局序列」判红）。
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

// ⚠️ **声明位置 = 最前**（在 `menuGroups` 之前），与它的**渲染位**（所有分组之前）同序：
//    menu.ts 的**声明顺序**是若干解析器（`parse_menu_ts_nodes` / rbac derive / 三源同构守卫的
//    `_parse_frontend`）读「顶层导航顺序」的口径 ⇒ 声明在最前，才不会让「经营看板」在解析面
//    落到所有组之后（那样三源同构与岗位矩阵都会假红）。渲染位另由 `Sidebar.tsx` / `flattenMenu`
//    显式拼装（head → 各组 → 尾席位 → 尾部项），**不依赖本文件的声明先后**。

/**
 * **最前席位**的一级项（`standaloneHeadItems`）：渲染在**所有分组之前**。
 *
 * 用户 2026-10-17 逐字（issue #7087）：「**经营看板直接作为一级菜单，移除工作台**，这样用户一进来
 * 就很直观的看到经营看板了」。席位为什么必须是「所有分组之前」而不是 `standaloneTopItems` 的尾席位：
 * `lib/menu-nav.ts` 的 `landingPath()`（登录落点 = **第一个可见菜单项**，issue #6758）——
 * 放尾席位 ⇒ 登录落点会变成首个分组的第一项（「在线接待」），与用户要的形态正好相反。
 *
 * 三源同批表达同一位置：本数组的第 1 项 ⇄ `MenuController.MENU_TREE` 顶层**首个**节点 ⇄
 * `AuthService.buildMenusByPermissions` **首个**顶层 `menus.add`（判据 = 三源同构守卫的顶层布局序列）。
 * 旧深链与路由守卫一字不动（`/dashboard`、`dashboard:view`）⇒ 纯信息架构调整，零授权 delta。
 */
export const standaloneHeadItems: MenuItem[] = [
  // 经营看板（原「工作台」组的首项）：issue #5699（P4）节点码 = 该页第一屏读码 `dashboard:view`
  //（5 个读端点与前端路由守卫同码）—— 「菜单看得见」与「点进去进得去」必须同一把尺子。
  { key: 'dashboard', name: '经营看板', icon: 'BarChart3', path: '/dashboard', permissionCode: 'dashboard:view', keywords: ['jycb', 'kanban', '看板', '经营看板', '工作台'] },
  // 报表中心（issue #7376 / #7377）：与「经营看板」同属**经营数据面**，所以紧跟其后、同为最前席位
  // 一级项（而不是塞进「交易管理」——报表不是交易操作）。码取**同一把尺子** `dashboard:view`
  // （报表就是看板的下钻，零授权 delta）；`/dashboard` 仍是登录落点（= 第一个可见项，未变）。
  { key: 'reports', name: '报表中心', icon: 'FileSpreadsheet', path: '/reports', permissionCode: 'dashboard:view', keywords: ['bb', 'baobiao', 'report', '报表', '毛利', '滞销', '业绩', '质量成本'] },
]

// 带子级的菜单组（本轮 2026-10-17 改判：**五大组**；顺序即渲染顺序与三源比对顺序）
export const menuGroups: MenuGroup[] = [
  // 🔴 2026-10-17（issue #7087，用户裁定）：「**工作台**」组**整组撤销** —— 原组内两项：
  //   · 「经营看板」升为**一级项**、落**最前席位**（见 `standaloneHeadItems`）；
  //   · 「每日简报」菜单项**删除**（结论已在经营看板上，企业开关驱动那张卡即可）。
  // ⇒ 「工作台」这个**组名**从此不再出现在任何商家可见面（侧边栏 / 面包屑 / 权限勾选树）。
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
  //   · 已删除的 `chat`「黄金策 · 在线对话」节点**不得长回来**（#3094 从侧边栏移除，走右下角 FAB）。
  {
    key: 'customer-service',
    name: '客户服务',
    // 🔴 组图标必须与该组**任一项**的图标不同（判据 = 图标两两不同，issue #5582 的渲染面）。
    // 曾用 `Headphones` ⇒ 与组内「在线接待」同图（紧挨着出现 = 视觉上没有区分度，实测已判红）⇒
    // 改用 `MessageSquare`（原「智能客服」组的图标，正好空闲；语义仍是「客户对话/服务」）。
    icon: 'MessageSquare',
    children: [
      // ⚠️ 组内顺序（用户 2026-10-06 方案 A1）：接待与工具 → 售后出口 → 客户档案。
      { key: 'human-sessions', name: '在线接待', icon: 'Headphones', path: '/agent-workspace/human-sessions', permissionCode: 'agent:session', keywords: ['zxjd', 'jiedai', 'kefu', '客服', '人工'] },
      // 知识库（2026-10-06 上移）：紧挨「在线接待」—— 客服**边接待边查**知识库（同一动作的两半），
      // 原序里被「客户列表」隔开 ⇒ 动线被打断。
      { key: 'knowledge', name: '知识库', icon: 'BookOpen', path: '/knowledge', permissionCode: 'knowledge:view', keywords: ['zsk', 'zhishi', 'qa'] },
      // issue #5246（已合入 main）：售后工单节点用**读**码 `after_sales:view` —— `order:refund`
      // 是「处理退款」的写码，节点挂在它上面 = 「能看工单」必须连写权一起给。**必须保留**该码。
      { key: 'after-sales', name: '售后工单', icon: 'LifeBuoy', path: '/after-sales', permissionCode: 'after_sales:view', keywords: ['shgd', 'shouhou', 'tuihuan', '退换货'] },
    ],
  },
  // 基础资料（2026-10-29 issue #8086，用户裁定 Q2/Q5/Q6）：商品管理 + 客户列表 + 供应商 + 价格本。
  // 位置 = **客户服务之后、交易管理之前**（用户 Q5 逐字）：「服务动线在最前，主数据紧跟其后作为交易的前置」。
  // 为什么收这四项：它们都是**被所有动线引用的档案/条件**（商品 = 生产与发货的输入，客户 = 下单与售后的对象，
  // 供应商 = 采购的对手方，价格本 = 开单前必须先定下来的价）。⚠️ 本组**推翻**了两条旧裁定：
  //   · 2026-09-29「客户管理属于服务客户」⇒ 客户列表移出「客户服务」；
  //   · 2026-10-06「商品管理作为一级项沉底」⇒ 商品管理进组（不再占尾席位）。两者都是用户 2026-10-29 的明确改判。
  {
    key: 'basic-data',
    name: '基础资料',
    // 组图标 `Library`：与组内四项（Package / UserCircle / Handshake / Tags）及所有其它组图标两两不同（#5582）。
    icon: 'Library',
    children: [
      // 商品管理（本轮 2026-09-29 用户裁定：**由「商品与加工项」组升为一级菜单项**，原话
      // 🔴 2026-10-29（issue #8086，用户裁定）：随「基础资料」组新建迁入本组（原属：尾席位（standaloneTopItems））。
      { key: 'products', name: '商品管理', icon: 'Package', path: '/products', permissionCode: 'product:list', keywords: ['splb', 'spgl', 'shangpin', '商品'] },
      // 🔴 2026-10-29（issue #8086，用户裁定）：随「基础资料」组新建迁入本组（原属：客户服务组）。
      // #2969：客户列表原在「客户管理」组；#5271 曾并入交易管理组；#5778 移入本组（服务客户动线）。
      // 2026-10-06 沉到本组末：它是**档案面**（查档 / 建档），不是每次接待都会走的一步。
      { key: 'customers', name: '客户列表', icon: 'UserCircle', path: '/customers', permissionCode: 'customer:view', keywords: ['khlb', 'kehu'] },
      // 🔴 2026-10-29（issue #8086，用户裁定）：随「基础资料」组新建迁入本组（原属：供应链组）。
      // 供应商（issue #7369，P0-1 段 1）：进货**之前**的主数据（谁供货、账期几天、停没停）。
      // ⚠️ 必须排在「入库单」之后：手机端标注取该码树序首个承载节点（#6781）。
      // 停用后仍要能看见（档案要能改回来）⇒ 不按状态门控。
      { key: 'suppliers', name: '供应商', icon: 'Handshake', path: '/suppliers', permissionCode: 'inbound:view', keywords: ['gys', 'gongyingshang', 'caigou', 'supplier'] },
      // 🔴 2026-10-29（issue #8086，用户裁定）：随「基础资料」组新建迁入本组（原属：交易管理组）。
      // 🔴 2026-10-20（issue #7354，用户逐字「把菜单订单列表改成销售订单」）：菜单正名「销售订单」。
      // 旧名「订单列表」保留为关键词（⌘K 按老叫法仍能搜到）；权限码 `order:list` / 路径 `/orders` 一字不动。
      // 价格本（issue #7375 段 3）：**交易前置** —— 先把价定下来，才谈得上开单与收款，
      // 所以排在「销售订单」之前。节点码 `order:list` = 该页第一屏读码（`GET /api/admin/pricing/books`
      // 的类级码）—— 与「每页恰好一个码」的既有口径一致（#7087 / #6580）。
      { key: 'price-books', name: '价格本', icon: 'Tags', path: '/price-books', permissionCode: 'order:list', keywords: ['jgb', 'jiage', 'price', '价格', '协议价', '等级价', '阶梯价'] },
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
      { key: 'orders', name: '销售订单', icon: 'ClipboardList', path: '/orders', permissionCode: 'order:list', keywords: ['xsdd', 'xiaoshou', 'ddlb', 'dingdan', '订单列表'] },
      // #2969：财务对账原在「客户管理」组；#5271 并入交易管理组（订单 → 收款 → 对账）
      { key: 'finance', name: '财务对账', icon: 'Calculator', path: '/finance', permissionCode: 'finance:view', keywords: ['cw', 'caiwu', 'duizhang', '对账'] },
      // 🔴 2026-10-24（issue #7593，用户裁定「审批中心菜单放置到右上角……不要单独搞个菜单」）：
      // 「审批中心」**菜单项已撤除**（`/approvals` 页面保留、路由守卫不动）—— 它是五类业务闸门共用的
      // 裁决屏（改价 / 超授信 / 退款 / 采购超量 / 盘点差异），跨交易 / 供应链 / 仓储三域，挂在某一个域的
      // 分组下会让仓库的人找不到「盘点差异」；且静态菜单项**没有信号**（待审 0 条与 12 条长得一样）。
      // 入口 = 顶栏 `components/layout/ApprovalBell.tsx`（图标 + 待审数徽标 + 面板 → 「去审批中心」）。
      // 权限码未变：读 `finance:view`（= 财务对账同码）、写 `finance:create` ⇒ **零授权 delta**。
    ],
  },
  // 🔴 2026-10-09（issue #6580）：本组现为 **3 项**（加工项管理 / 工艺配置已移除 —— 见下方 children 前的注释）。
  // 沿革：issue #5271 时**由 7 项降到 4 项** —— 只留「加工执行 + 工艺配置 + 结算」；
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
      // 🔴 2026-10-09（issue #6580，用户裁定）：本组由 5 项收拢为 **3 项** ——
      // 「加工项管理」`/production/processing` 与「工艺配置」`/production/routings` 两个**菜单项已移除**
      //（用户逐字：「我的目的是要能移除加工项管理和工艺配置这两个菜单」），功能体并入
      // `/settings`（企业基础设置）页内的配置域（设计真值源：`docs/design/enterprise-settings-redesign.md`）；
      // 两个旧路径保留为重定向（旧深链不 404）⇒ 本组现为「作业看板 → 智能派单 → 计件工资」。
      // ⚠️ 被移除的两项从此**没有菜单节点**，其旧路由登记在
      // `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `ROUTE_WITHOUT_MENU_NODE`。
      //
      // 沿革（**一字不动地保留**，它们是历史事实）：
      //   · 加工项管理（2026-09-29 用户裁定「加工项应该属于生产管理」）：由「商品与加工项」组移入本组
      //     —— 它是**加工定价资料**（加工费组合的 `items[]` 必须取自加工项目录的活跃加工项）；
      //   · issue #4490（用户裁定 2026-09-19）：「加工项管理」`/production/processing` 与
      //     「加工费管理」`/production/processing-fees` **合并为单一入口**（本次移除菜单项**不撤销该合并**）；
      //   · issue #4542：菜单名 = **「加工项管理」**（与服务端同名）；
      //   · issue #4416：「工序库」与「工艺路线」合并为单一入口「工艺配置」（工序是**原子词汇**、
      //     路线是**用工序名拼出的有序序列**）；工序库半边 = 该页**左栏**；
      //   · 节点码（两者）自 issue #5291 起 = 生产域**读**码 `production:view`；
      //   · issue #5699（P4）：工艺配置页第一屏 6 个读端点整页收敛到**页面码** production:view。
      // /production = 作业看板唯一入口（issue #4357 与原「加工单」菜单合并；#7079 起上位概念 = 作业看板）
      // 2026-10-19（issue #7332）：菜单正名「作业看板」；旧名「生产看板」保留为**关键词**（⌘K 按老叫法仍能搜到）。
      { key: 'production-board', name: '作业看板', icon: 'ClipboardCheck', path: '/production', permissionCode: 'production:view', keywords: ['sckb', 'shengchan', 'jiagongdan', '加工单', '作业', '作业看板', '作业看板', 'zuoye', 'zykb', '生产看板', '生产'] },
      // 智能派单（issue #5177）：池化派单的**决策屏** —— 加急插队区（不进池、立即单派）
      // + 物料分组成批区（勾选 → 预览 → 一键成批派单）+ 超时未派告警。
      // issue #5699（P4）：节点码 = 该页第一屏读码 `processing:view`（此前挂 processing:manage ⇒ 节点码 ≠ 页面读码），
      // 路由守卫同批改挂读码（`app/(dashboard)/layout.tsx`）。
      { key: 'production-pool', name: '智能派单', icon: 'Layers', path: '/production/pool', permissionCode: 'processing:view', keywords: ['zndp', 'zhineng', 'paidan', '派单', 'ckb'] },
      { key: 'production-piecework', name: '计件工资', icon: 'Coins', path: '/production/piecework', permissionCode: 'production:view', keywords: ['jjgz', 'jijian', 'gongzi'] },
    ],
  },
  // 质量（2026-10-29 issue #8086，用户裁定 Q3）：质检记录 + 返工单从「生产管理」拆出，独立成组。
  // 理由：这三件事是**三种角色的活**（计划派单 / 计件工资 / 质检返工）塞在同一个组里，质检员进组还会看到
  // 计件工资；拆开后生产管理回到「作业 → 派单 → 计件」，质量成为质检员自己的域。
  // ⚠️ 权限码本组不动（质检记录 = production:inspect、返工单 = after_sales:view），拆码见 issue #8087。
  {
    key: 'quality',
    name: '质量',
    // 组图标 `ShieldAlert`：与组内「质检记录 BadgeCheck / 返工单 Wrench」及「岗位权限 ShieldCheck」两两不同（#5582）。
    icon: 'ShieldAlert',
    children: [
      // 质检记录（issue #7140 = #5652 的**商家面**）：成品帘级三态判定（合格 / 返工 / 报废 + 原因）。
      // 🔴 为什么要补这条菜单：质检端点与工人端三态**早就在**，但 admin-web 里**0 处消费**
      // ⇒ 质检员登录观星台没有工作台、商家查不到任何质检读数（用户 2026-10-17 实测原话：
      // 「之前让你做过质检流程，我看在观星台上没有任何地方体现出来了」）。
      // 🔴 节点码 = 该页第一屏读端点码 = 写端点码 `production:inspect`（三处逐字同码）：
      // 该码只授给独立质检员 + 管理员 ⇒ **零权限放宽**（用户 2026-10-17 三个选项里选了「保持现状」）。
      { key: 'quality-inspections', name: '质检记录', icon: 'BadgeCheck', path: '/quality-inspections', permissionCode: 'production:inspect', keywords: ['zjjl', 'zhijian', 'quality', 'jiance', 'hege'] },
      // 返工单（issue #7377，P1-5 质量闭环的商家面）：售后判定要返工 ⇒ 开单 → 开工 → 完工。
      // 🔴 节点码 = 该页第一屏读端点码 `after_sales:view`（＝路由守卫码，三处逐字同码）：
      // 与售后工单同域复用既有码 ⇒ **零授权 delta**；写动作走 `order:refund`（与售后改状态同码）。
      // 为什么不新造 `rework:*`：今天没有任何角色持有它 ⇒ 节点与页面会对所有人不可见（#4203 同族坑）。
      { key: 'rework-orders', name: '返工单', icon: 'Wrench', path: '/rework-orders', permissionCode: 'after_sales:view', keywords: ['fgd', 'fangong', 'rework', '返工', '返修', 'rework-order', '返工单'] },
    ],
  },
  // issue #5271 **新组**：面料进出与消耗 —— 入库 → 批次 → 余料 → 省料，是**同一条物流动线**，
  // 原散在「生产管理」组里与加工执行混编（一个仓管找「入库单」时不该在「生产看板」旁边找）。
  // 权限码**不统一**且有意如此：入库单 = `inbound:view`（仓储动作，仓管/财务要看入库单，
  // 却不需要 processing:manage）；余料台账 = `processing:manage`（与 `RemnantController` 的
  // 类级码逐字同码）。⚠️ **省料看板不是同码**（issue #5675 的判据 12 首次发现并登记）：它的
  // 读端点在 `StockBatchController` 上沿用 `product:list` ⇒ 节点码与该页**第一屏读端点码**不一致，
  // 已具名登记在判据 12 的残留台账（本组旧注记「另两项与各自页面的类级码同码」对省料看板不成立）。
  // 供应链（issue #7369，用户 2026-10-20 裁定「新增的菜单不能放到仓储与物料下，得加个新大菜单」）：
  // 这条链是「谁供货 → 买什么 → 到货登记」—— 三个节点同码 `inbound:view`（采购与收货同岗位，
  // 零授权 delta；不新造 supplier:*/purchase:* —— 新码今天没人持有 ⇒ 菜单对所有人不可见，#4203 同族坑）。
  // ⚠️「入库单」必须排在本组**第一个**：手机端可见面标注取该码树序**首个**承载节点（#6781），
  // 而入库单是三者里唯一有移动端页面的（过账）。
  {
    key: 'supply-chain',
    name: '供应链',
    icon: 'Route',
    children: [
      // 入库单（V111，issue #5034）：商品布料入库 —— 建单（草稿）/ 过账（自动生成批次号 +
      // 自动加库存 + 移动加权平均成本）/ 作废（仅草稿）；批次与库存台账可查。
      // 用户 2026-10-20 裁定：它是**采购到货**的登记面，随供应链走（不在仓储与物料里）。
      { key: 'inbound-orders', name: '入库单', icon: 'PackageOpen', path: '/inbound-orders', permissionCode: 'inbound:view', keywords: ['rkd', 'ruku', 'caigou'] },
      // 采购单（issue #7369，P0-1 段 4）：下单（买什么/多少钱/什么时候到）→ 分次收货 → 关闭。
      // 与入库单**一对多**（支持部分收货）；状态由后端按 Σ收货派生。
      { key: 'purchase-orders', name: '采购单', icon: 'ShoppingBag', path: '/purchase-orders', permissionCode: 'inbound:view', keywords: ['cgd', 'caigou', 'caigoudan', 'purchase', 'po'] },
    ],
  },
  // 仓储与物料（用户 2026-10-20 裁定：本组不再含单据类节点，只留**库存与出库**）
  {
    key: 'inventory-center',
    name: '仓储与物料',
    icon: 'Boxes',
    children: [
      // 库存明细（issue #6404）：SKU 级库存**变化流水**的读面（「为什么系统说还有 30 米、实际只剩 12 米」）。
      // 节点码 = 该页第一屏读端点（`GET /api/admin/stock-ledger`）的方法级 `product:list`（逐字同码）。
      // 先例 = 「省料看板」同取 `product:list`（issue #5699 P4）。
      { key: 'stock-ledger', name: '库存明细', icon: 'ScrollText', path: '/stock-ledger', permissionCode: 'product:list', keywords: ['kcmx', 'kucun', 'mingxi', 'liushui', 'taizhang', '台账'] },
      // 盘点单（issue #7373 段 2 后端 / 本项 = 商家面）：账面快照 → 逐批次录实盘 → 有差异先审批再完成。
      // 节点码 = 该页第一屏读端点码（`GET /api/admin/stocktakes` 的**方法级** `inbound:view`）—— 逐字同码
      //（repo 规则「每页恰好一个码」）。紧跟「库存明细」：先看账，再对账。
      { key: 'stocktakes', name: '盘点单', icon: 'ScanLine', path: '/stocktakes', permissionCode: 'inbound:view', keywords: ['pdb', 'pandian', 'kucunpandian', 'pandian', '盘点', '盘点单', '盘库', '盘亏', '盘盈'] },
      // 出库单（V194 / issue #7750）：与「入库单」对称的**出口**单据 —— 布料手工出库 + 成品发货出库
      // 共用一套单据形状（单号 CK-…、建单即过账）。节点码复用 `inbound:view`（收发同岗位，零授权 delta）。
      { key: 'outbound-orders', name: '出库单', icon: 'PackageMinus', path: '/outbound-orders', permissionCode: 'inbound:view', keywords: ['ckd', 'chuku', 'outbound', '出库单', '出库'] },
      // 发货单（issue #5939，用户 2026-10-02 裁定）：与「入库单」对称的**出口**单据；
      // 取**既有** `order:list`（与销售订单同码、零授权 delta）。
      { key: 'shipments', name: '发货单', icon: 'Truck', path: '/shipments', permissionCode: 'order:list', keywords: ['fhd', 'fahuo', 'shipment', 'chuku', '出库', '发货'] },
      // 余料台账（PR-106 / issue #5191）：码 = `processing:manage`（`RemnantController` 类级码逐字同码）
      { key: 'production-remnants', name: '余料台账', icon: 'Recycle', path: '/production/remnants', permissionCode: 'processing:manage', keywords: ['yltz', 'yuliao', 'huishou'] },
      // 省料看板（issue #5699 P4）：两个读端点在 `StockBatchController` 上是方法级 `product:list`
      { key: 'production-saving-board', name: '省料看板', icon: 'TrendingDown', path: '/production/saving-board', permissionCode: 'product:list', keywords: ['slkb', 'shengliao', 'haoliao', '省料看板'] },
    ],
  },
  {
    key: 'org-center',
    name: '组织管理',
    icon: 'Building2',
    children: [
      { key: 'employees', name: '员工管理', icon: 'Users', path: '/employees', permissionCode: 'employee:list', keywords: ['yggl', 'yuangong'] },
      // issue #5291：岗位权限节点改挂**读**码 `system:view`。
      // 🔴 2026-10-09（issue #6580）：「企业基础信息」已由本组**移出**（→ 尾部独立项，并改名为
      // 「企业基础设置」）—— 本组从此只有「人与权限」两件事（员工管理 / 岗位权限）。
      { key: 'roles', name: '岗位权限', icon: 'ShieldCheck', path: '/roles', permissionCode: 'system:view', keywords: ['gwqx', 'jiaose', 'quanxian'] },
    ],
  },
]

// 一级独立菜单项（无子级，**直接跳转**）—— **三个席位**，位置语义各不相同（见文件头「三个席位」节）
//
// ## 为什么这些项不做「单成员组」
//
// 用户 2026-09-29 裁定（「商品列表改成商品管理，**直接作为一级菜单使用**」）：「唯一成员」的组会退化成
// 一个没有分组的名字（点开只为看一项）⇒ 改为一**级项平铺**：保留为一级菜单、一屏直达、不折叠。
// 本轮（2026-10-17）「经营看板」同款：撤掉「工作台」组后，它就是**最前的一级项**。
//
// ## 三个数组
//
//   · `standaloneHeadItems` —— **最前席位**（渲染在**所有分组之前**）：本轮新增，只有「经营看板」；
//   · `standaloneTopItems`  —— **尾席位**（渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY` 那个组之后）：
//     「商品管理」「企业基础设置」。席位组**不可见**时（权限把它整组过滤掉 / 常量写错）⇒ 回落到
//     **当前可见分组的末尾**：一级项**绝不允许跟着消失**（最坏退回旧位置，也不能没有入口）；
//     口径的**唯一实现** = `frontend/admin-web/src/lib/menu-nav.ts` 的 `splitGroupsAtTopItemSlot`
//     （`Sidebar.tsx` 与 `flattenMenu` 都调它，不各写一份 slice）。
//   · `standaloneItems`     —— **尾部项**（渲染在**所有分组之后**）：「通知中心」
//     （全员可见，与顶栏铃铛一致，无需权限码）。
//
// 🔴 **一级项不进「常用」**（#5877，用户 2026-10-01 裁定）：它已一屏可见、且**不再有星标** ⇒
//     可收藏面只含组内项 + 尾部独立项（否则同一屏会出现两条一模一样的入口）；
//     用户 localStorage 里残留的 `products` key 按既有「无效 key 静默丢弃」口径处理。
//     判据：`frontend/admin-web/tests/unit/lib/menu-pinned.test.ts`。


/**
 * 一级项（`standaloneTopItems`）的**插入位**：渲染在**这个组之后**（用户 2026-10-06 裁定 = 最后一个组）。
 *
 * ## 为什么是一个常量，以及为什么三源必须**同批**表达同一位置
 *
 * 「商品管理排在哪」这件事在**三处**各有表达，缺一处就是「岗位权限页勾得动、侧边栏看不到」的同族坑：
 *   ① **前端渲染位** —— 本常量（`Sidebar.tsx` 经 `splitGroupsAtTopItemSlot` 使用）；
 *   ② `MenuController.MENU_TREE` 的**顶层节点顺序**（`GET /api/admin/menus`，员工管理页的权限树）；
 *   ③ `AuthService.buildMenusByPermissions` 里顶层 `menus.add(...)` 的**文档位置**（登录下发的菜单）。
 *
 * 判据 = `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的**顶层布局序列**比对
 * （#5877 起含**位置**：只改本常量而不改服务端 ⇒ 当场判红）。
 * ⚠️ 取值必须是 `menuGroups` 里**真实存在**的组 key —— 写错 ⇒ 前端回落（一级项回到最前）
 *    而服务端不动 ⇒ 判据红（这是**有意**的：静默漂移比直接红更难查）。
 *
 * 🔴 本常量**只管尾席位**（`standaloneTopItems`）。**最前席位**（`standaloneHeadItems`，2026-10-17
 *    新增）**不需要常量** —— 它的位置由「数组第 1 项」与渲染顺序（`flattenMenu` 把 head 放在最前）
 *    直接表达；两个席位的相对顺序在 `flattenMenu` 的拼装里写死，`Sidebar.tsx` 与之同源。
 */
export const STANDALONE_TOP_AFTER_GROUP_KEY = 'org-center'
export const standaloneTopItems: MenuItem[] = [
  // 🔴 2026-10-09（issue #6580，用户裁定 —— **同一天的第三次改判**）：原 #6573 在这里新增的
  // 「参数总览」一级项**已撤掉**。用户逐字：「参数总揽不要单独搞个菜单，这些信息都**直接做到
  // 企业基础信息中**」「我的目的是要能**移除加工项管理和工艺配置这两个菜单**」。
  // ⇒ 配置面的落点是**企业基础设置页内**的配置域（设计真值源：
  //   `docs/design/enterprise-settings-redesign.md`），不是一条并列的一级项。
  // 旧链 `/settings/params` 保留为重定向（仓内口径：旧深链不 404）。
  // 🔴 2026-10-09（issue #6580）：**企业基础设置**（原「企业基础信息」）由「组织管理」组移出，
  // 成为**尾部独立项**、排在「通知中心」**上面** —— 用户逐字：「这个菜单和通知中心是一个类型的
  // 放到通知中心的上面，并且和通知中心一起沉底」。
  // · 改名：企业基础信息 → **企业基础设置**；路径一字不动（`/settings`）；
  // · 🔴 **节点码 `system:manage` → `production:view`**（用户 2026-10-09 裁定，选项 A）：
  //   合并加工项管理 / 工艺配置之后，它是生产配置面**唯一的入口**，而真实配置者
  //   `operator` / `product_manager`（见 `rbac/manifest.json` 的 `roles.seed`）持
  //   `production:view`、**不持** `system:manage` ⇒ 不换码 = 菜单对他们恒不可见（#4203 同族坑）。
  //   复算：seed 里唯一天然持全码的是 `admin: ["*"]` ⇒ **改码对现有角色零损失**（既无人掉码、
  //   也没有人凭空多出写面）；页内**经营域**（企业信息 / AI 客服 / 通知设置）仍按
  //   各自的 `system:manage` 域级显隐 ⇒ 该码的**可授予面**不缩水（由 `MenuController` 的
  //   org-center 组承载那一个权限码节点，见 `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`
  //   的 `ACTION_NODES['org-center']` 登记）。
  //   ⚠️ 本页经营域读面是 `system:manage` ⇒ 守卫码与首屏读码的**有意不一致**已在
  //   `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_PARITY_RESIDUALS`
  //   具名登记（含 403 受害者认领）—— 判据 12 **只许登记、不许放宽**。
  // · 席位：它与「商品管理」同用**尾席位**（`standaloneTopItems`，2026-10-06 裁定：排在所有分组之后）。
  //   ⚠️ 这不改变用户要的形态 —— 本仓最后一个组就是 `org-center`（`STANDALONE_TOP_AFTER_GROUP_KEY`），
  //   所以两个尾部席位的渲染结果连成一片：`商品管理 → 企业基础设置 → 通知中心`（尾部项在最后）
  //   ⇒ 「企业基础设置在通知中心上面、两者一起沉底」**逐字成立**。
  //   （2026-10-17 issue #7087 新增的「经营看板」在最前席位，**不影响**这条沉底口径。）
  // · 它是**配置指挥台**的宿主页（配置主线 + 配置域），设计真值源：
  //   `docs/design/enterprise-settings-redesign.md`。
  { key: 'settings', name: '企业基础设置', icon: 'Settings', path: '/settings', permissionCode: 'production:view', keywords: ['qyxx', 'shezhi', 'qiye', 'jichu', '配置'] },
]

export const standaloneItems: MenuItem[] = [
  // 通知中心：全员可见（与顶栏铃铛一致，无需权限码）
  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications', keywords: ['tzx', 'tongzhi', 'xiaoxi'] },
]