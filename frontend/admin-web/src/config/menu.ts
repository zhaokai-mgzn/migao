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
// 现为 **27 个导航节点**（issue #8852 合并经营数据面两页后，现取 2026-11-09）=
// **8 组 24 项** + 一级独立项 3（最前席位：经营报表；尾席位：企业基础设置；尾部项：通知中心）。
//
// ## 本轮（用户 2026-11-06 逐字给出的十二个一级菜单及组内顺序）
//
//   一 经营概览 │ 二 报表中心 │ 三 客户服务（在线接待、售后工单、知识库）
//   四 订单/商品（销售订单、商品管理、价格本、客户列表）│ 五 生产管理（作业单、智能派单）
//   六 质量管理（质检记录、返工单）
//   七 仓储/物料（入库单、盘点单、出库单、发货单、库存明细、余料台账、省料分析）
//   八 财务（财务对账、计件工资）│ 九 供应链（采购单、供应商）│ 十 企业基础设置
//   十一 组织管理（员工管理、岗位权限）│ 十二 通知中心
//
//   ⚠️ 2026-11-09（issue #8852）：「一 经营概览」+「二 报表中心」已**合并为一项**「经营报表」
//      （见本文件头「现为 27 个导航节点」与 `standaloneHeadItems`）—— 下面十二项的其余名字/顺序不变。
//   ⇒ **组变化**：旧「交易管理」+「基础资料」两组**合并为「订单/商品」**（`orders-products`）；
//     新增**「财务」**组（`finance-center`：财务对账 + 计件工资，后者由生产管理移出）；
//     「质量」正名**质量管理**（key `quality` 不动）、「仓储与物料」正名**仓储/物料**（key 不动）；
//     「入库单」由供应链移入仓储/物料且**排第一**；「供应商」由基础资料移入供应链（排采购单之后）。
//   ⇒ **席位**：最前席位不动（经营概览 / 报表中心，登录落点仍是经营概览）；**尾席位的插入点
//     由「最后一个组」改为「供应链之后」** —— 用户要求「企业基础设置」排在组织管理**之前**
//     （唯一表达 = `STANDALONE_TOP_AFTER_GROUP_KEY = 'supply-chain'`，见该常量的注释）。
//   ⇒ **权限码 / 路径 / 图标语义一字不动** ⇒ **零授权 delta**（纯信息架构重排：谁看得见什么没变）。
//     判据：三源同构守卫（组层 + 导航节点层 + 顶层布局序列）+ 岗位矩阵用例。
//
// ## 三个席位（`standalone*` 三个数组，**位置语义各不相同**，别按名字猜）
//
//   · `standaloneHeadItems` —— **最前席位**：渲染在**所有分组之前**（#7087 用户 2026-10-17 裁定：
//     「经营看板直接作为一级菜单，移除工作台」）；
//   · `standaloneTopItems`  —— **尾席位**：渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY` 那个组**之后**
//     （名字里的 `Top` 是「**升为顶层一级项**」的历史叫法，**与渲染位无关**）；
//   · `standaloneItems`     —— **尾部独立项**：渲染在**所有分组之后**（「通知中心」）。
//
//   三个数组**都是导航**：进 ⌘K 索引（`flattenMenu` 的 `head` / `top` / `bottom`）、进三源同构守卫、
//   进面包屑覆盖判据（PG-038 按菜单项 `path` 穷举，本文件是它的输入面）。
//
// ## 历史锚点（为什么是现在这个形态 —— 只留会改变判断的几条，全文见 git 历史）
//
//   · 2026-10-17（#7087）：「工作台」组整组撤销 —— 经营看板升为一级项、落最前席位（登录落点 =
//     第一个可见菜单项）；「每日简报」菜单项删除（结论已在看板上，企业开关驱动那张卡）。
//   · 2026-10-20（#7369）：供应链独立成组（用户逐字「新增的菜单不能放到仓储与物料下」）。
//   · 2026-10-24（#7593）：「审批中心」菜单项撤除，入口改顶栏 `ApprovalBell`（页面与码保留）。
//   · 2026-10-29（#8086）：新增「基础资料」「质量」两组；商品管理由一级项降入组内。
//     ⚠️ 那轮的「基础资料」组已被**本轮**的「订单/商品」取代（客户列表 / 商品管理 / 价格本进本组，
//     供应商移入供应链）—— 这是用户 2026-11-06 的明确改判，不是回退。
//   · 2026-11-06（本轮）：如上「组变化 / 席位」两条。
//
// ## 硬约束（改动本文件前必读）
//
//   🔴 本文件与 **两处服务端**必须**同批**改，否则「岗位权限页勾得动、侧边栏看不到」
//      （或反过来）：
//        ① `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE`
//        ② `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `buildMenusByPermissions`
//      判据：`tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py`（#5271 起比对**全树**：
//      组 key + 组名 + 组顺序，以及导航型节点名）。
//   🔴 另有**第四处**镜像必须同批：`backend/ai-agent-service/app/context/menu_navigator.py` 的
//      `MENU_GROUPS` / `MENU_TREE`（黄金策导航指引的结构层；判据 `tests/unit_ci_workflows/test_menu_navigator.py`
//      逐节点逐字段逐序核）。
//   🔴 **改了一级项的位置 ⇒ 三源同批**：本文件的 `STANDALONE_TOP_AFTER_GROUP_KEY` +
//      `MenuController.MENU_TREE` 的顶层节点顺序 + `AuthService` 顶层 `menus.add` 的文档位置
//      （#5877；只改一处 ⇒ 三源同构守卫的「顶层布局序列」判红）。
//   🔴 **改了组名或菜单名 ⇒ 必须同批改 `frontend/admin-web/src/components/layout/Header.tsx` 的
//      `ROUTE_BREADCRUMB_MAP`**（面包屑末项必须逐字 == 菜单名，首项 == 组名）。
//      判据：`frontend/admin-web/tests/unit/lib/menu-breadcrumb-coverage.test.tsx`（PG-038）。
//   ⚠️ 新增图标必须同时登记进 `frontend/admin-web/tests/setup.ts` 的 lucide 白名单，
//      否则任何渲染 Sidebar 的用例会**当场抛错**（不是静默）。
//   ⚠️ 企业能力地图 `components/corporate/capability-map.ts` 是同一 IA 的**对外叙述面**（企业介绍页）
//      ⇒ 组名 / 组顺序 / 成员变了要同批跟（它没有机械判据，只能靠这条纪律）。

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
//    `_parse_frontend`）读「顶层导航顺序」的口径 ⇒ 声明在最前，才不会让「经营概览」在解析面
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
  // 经营报表（issue #8852，用户 2026-11-09 钉钉：「经营概览」+「报表中心」合并为一个页面「经营报表」）：
  // 节点键 / 路径 / 权限码**一字不改**（`dashboard` / `/dashboard` / `dashboard:view`）—— 登录落点仍是
  // 第一个可见项、旧深链 `/dashboard` 与旧 `/reports`（重定向薄壳）都进得来 ⇒ **零授权 delta**。
  // 节点码 = 该页第一屏读码（dashboard:view）—— 「菜单看得见」与「点进去进得去」必须同一把尺子。
  // keywords 收两页的叫法：「经营概览/看板」是旧名，「毛利/滞销/业绩/质量成本/账龄」是原报表中心的分区词
  //（⌘K 里按业务词都能搜到这一页，不会因为合并而搜不到报表）。
  { key: 'dashboard', name: '经营报表', icon: 'BarChart3', path: '/dashboard', permissionCode: 'dashboard:view', keywords: ['jybb', 'jingyingbaobiao', 'bb', 'baobiao', 'report', '报表', '经营报表', '经营概览', '经营看板', '看板', '工作台', '毛利', '滞销', '业绩', '质量成本', '账龄'] },
]

// 带子级的菜单组（本轮 2026-11-06：**八大组**；顺序即渲染顺序与三源比对顺序）
//
// ⚠️ 组 key 是**内部标识**（不上屏：`menu_navigator.MENU_GROUP_LABELS` 只把组名给商家），
//    但它是三源同构 + rbac 清单 + ⌘K 分组的**共同键** ⇒ 改名要四处同批（本文件 / MenuController /
//    AuthService / menu_navigator）。
export const menuGroups: MenuGroup[] = [
  // 客户服务（2026-09-29 用户裁定**新建**）：原「智能客服」组（在线接待 / 知识库）
  // + 原「交易管理」组的客户侧两项（客户列表 / 售后工单）**合并为一个组**。
  // 证据（岗位权限矩阵 `RegistrationService` 种子表）：`customer_service` 岗位权限集**恰好
  // 100% 覆盖**本组三项的全部码 ⇒ 这三项**本就是同一批人在用**；分组变动对所有岗位的可见项零变化。
  // 🔴 2026-11-06（用户本轮裁定）组内顺序 = **在线接待 → 售后工单 → 知识库**：
  //    接待（主入口）→ 售后（接待的第二出口）→ 工具（边接待边查的知识库）。
  //    旧序「在线接待 → 知识库 → 售后工单」是 2026-10-06 的口径，本轮被用户明确改判。
  {
    key: 'customer-service',
    name: '客户服务',
    // 🔴 组图标必须与该组**任一项**的图标不同（判据 = 图标两两不同，issue #5582 的渲染面）。
    icon: 'MessageSquare',
    children: [
      { key: 'human-sessions', name: '在线接待', icon: 'Headphones', path: '/agent-workspace/human-sessions', permissionCode: 'agent:session', keywords: ['zxjd', 'jiedai', 'kefu', '客服', '人工'] },
      // issue #5246（已合入 main）：售后工单节点用**读**码 `after_sales:view` —— `order:refund`
      // 是「处理退款」的写码，节点挂在它上面 = 「能看工单」必须连写权一起给。**必须保留**该码。
      // ⚠️ 本项另有承载面：`/rework-orders`（质量管理组）与 `/after-sales` 同码（#7377 的有意设计）。
      { key: 'after-sales', name: '售后工单', icon: 'LifeBuoy', path: '/after-sales', permissionCode: 'after_sales:view', keywords: ['shgd', 'shouhou', 'tuihuan', '退换货'] },
      // 知识库（issue #5246）：知识库用**读**码 `knowledge:view` —— 「看知识库」与「改知识库」是两件事。
      // 用户 2026-09-29 裁定：知识库**仍留在本组内**（不单独成项、不沉底）——
      // 通知中心是**全局项**（无权限码、另有顶栏铃铛入口）故可沉底；知识库是功能域模块
      // （需 `knowledge:view`、且侧边栏是它**唯一**入口）⇒ 沉底代价不对称。
      { key: 'knowledge', name: '知识库', icon: 'BookOpen', path: '/knowledge', permissionCode: 'knowledge:view', keywords: ['zsk', 'zhishi', 'qa'] },
    ],
  },
  // 订单/商品（2026-11-06 用户本轮裁定**新建**）：旧「交易管理」（销售订单 / 财务对账）与
  // 旧「基础资料」（商品管理 / 客户列表 / 供应商 / 价格本）两组**合并**，再按用户给的顺序重排。
  // 为什么这四项同一组：它们是**开单链**上的四个环节 —— 卖什么（商品管理）→ 什么价（价格本）→
  // 卖给谁（客户列表）→ 成交（销售订单）。财务对账是**收款侧**、已移入新「财务」组。
  // ⚠️ 组内顺序 = 用户逐字「销售订单、商品管理、价格本、客户列表」（订单是入口，其余是它的三个输入）。
  {
    key: 'orders-products',
    name: '订单/商品',
    // 组图标 `ShoppingCart`（原「交易管理」组的图标，语义仍是「交易」）：
    // 与组内四项（ClipboardList / Package / Tags / UserCircle）及所有其它组图标两两不同（#5582）。
    icon: 'ShoppingCart',
    children: [
      // 销售订单（issue #7354，用户 2026-10-20 逐字「把菜单订单列表改成销售订单」）：菜单正名；
      // 旧名「订单列表」保留为关键词（⌘K 按老叫法仍能搜到）；权限码 `order:list` / 路径 `/orders` 不动。
      { key: 'orders', name: '销售订单', icon: 'ClipboardList', path: '/orders', permissionCode: 'order:list', keywords: ['xsdd', 'xiaoshou', 'ddlb', 'dingdan', '订单列表'] },
      // 商品管理（2026-09-29 用户裁定：由「商品列表」改名「商品管理」并升为一级菜单；
      // 2026-10-29 #8086 降入「基础资料」组；本轮随「基础资料」→「订单/商品」的改判迁入，仍是组内项）。
      { key: 'products', name: '商品管理', icon: 'Package', path: '/products', permissionCode: 'product:list', keywords: ['splb', 'spgl', 'shangpin', '商品'] },
      // 价格本（issue #7375 段 3）：**交易前置** —— 先把价定下来，才谈得上开单与收款。
      // 节点码 `order:list` = 该页第一屏读码（`GET /api/admin/pricing/books` 的类级码）。
      { key: 'price-books', name: '价格本', icon: 'Tags', path: '/price-books', permissionCode: 'order:list', keywords: ['jgb', 'jiage', 'price', '价格', '协议价', '等级价', '阶梯价'] },
      // 客户列表（#2969 原在「客户管理」组；#5778 并入交易管理；#8086 移入基础资料；
      // 本轮随组迁入「订单/商品」—— 它是**下单对象**的档案面（查档 / 建档）。
      { key: 'customers', name: '客户列表', icon: 'UserCircle', path: '/customers', permissionCode: 'customer:view', keywords: ['khlb', 'kehu'] },
    ],
  },
  // 生产管理（issue #6580 起「加工项管理 / 工艺配置」两个菜单项已移除、功能体并入 `/settings`）。
  // 🔴 2026-11-06（用户本轮裁定）：**计件工资移出本组**（→ 新「财务」组）⇒ 本组只剩
  //    「作业单 → 智能派单」：先有活（作业单），再有派工（派单）；计件是**结算**、归财务。
  {
    key: 'production-center',
    name: '生产管理',
    icon: 'Factory',
    children: [
      // /production = 作业单唯一入口（issue #4357 与原「加工单」菜单合并；#7079 上位概念 = 作业看板；
      // 2026-10-19 #7332 菜单正名「作业单」，旧名保留为关键词）。
      { key: 'production-board', name: '作业单', icon: 'ClipboardCheck', path: '/production', permissionCode: 'production:view', keywords: ['sckb', 'shengchan', 'jiagongdan', '加工单', '作业', '作业单', '作业看板', 'zuoye', 'zykb', '生产看板', '生产'] },
      // 智能派单（issue #5177）：池化派单的**决策屏** —— 加急插队区 + 物料分组成批区 + 超时未派告警。
      // issue #5699（P4）：节点码 = 该页第一屏读码 `processing:view`（路由守卫同批改挂读码）。
      { key: 'production-pool', name: '智能派单', icon: 'Layers', path: '/production/pool', permissionCode: 'processing:view', keywords: ['zndp', 'zhineng', 'paidan', '派单', 'ckb'] },
    ],
  },
  // 质量管理（2026-10-29 #8086 拆出独立组，组 key `quality`；本轮 2026-11-06 用户把组名正名为
  // **「质量管理」** —— 用户逐字给的一级菜单名就是这四个字）。
  // 理由不变：质检与返工是**质检员自己的域**，不该和计划派单 / 计件工资混在一组。
  // ⚠️ 权限码本组不动（质检记录 = production:inspect、返工单 = after_sales:view），拆码见 issue #8087。
  {
    key: 'quality',
    name: '质量管理',
    // 组图标 `ShieldAlert`：与组内「质检记录 BadgeCheck / 返工单 Wrench」及「岗位权限 ShieldCheck」两两不同（#5582）。
    icon: 'ShieldAlert',
    children: [
      // 质检记录（issue #7140 = #5652 的**商家面**）：成品帘级三态判定（合格 / 返工 / 报废 + 原因）。
      // 🔴 节点码 = 该页第一屏读端点码 = 写端点码 `production:inspect`（三处逐字同码）：
      // 该码只授给独立质检员 + 管理员 ⇒ **零权限放宽**（用户 2026-10-17 三个选项里选了「保持现状」）。
      { key: 'quality-inspections', name: '质检记录', icon: 'BadgeCheck', path: '/quality-inspections', permissionCode: 'production:inspect', keywords: ['zjjl', 'zhijian', 'quality', 'jiance', 'hege'] },
      // 返工单（issue #7377，P1-5 质量闭环的商家面）：售后判定要返工 ⇒ 开单 → 开工 → 完工。
      // 🔴 节点码 = 该页第一屏读端点码 `after_sales:view`（＝路由守卫码，三处逐字同码）：零授权 delta。
      { key: 'rework-orders', name: '返工单', icon: 'Wrench', path: '/rework-orders', permissionCode: 'after_sales:view', keywords: ['fgd', 'fangong', 'rework', '返工', '返修', 'rework-order', '返工单'] },
    ],
  },
  // 仓储/物料（#5271 **新组**；本轮 2026-11-06 用户把组名正名为**「仓储/物料」** —— 与「订单/商品」
  // 同一书写口径，组名即两块业务的合称；key `inventory-center` 不动）。
  // 组内顺序 = **单据（进 → 盘 → 出 → 发）→ 账（库存明细）→ 台账（余料）→ 分析（省料）**，
  // 与用户本轮逐字给出的七项顺序一致：把**同一张单据的形状**排在一起（进/盘/出/发），
  // 再是账、台账、分析三层。
  // 权限码**不统一**且有意如此（各页第一屏读码，见每一项的注释）。
  {
    key: 'inventory-center',
    name: '仓储/物料',
    icon: 'Boxes',
    children: [
      // 入库单（V111，issue #5034）：建单（草稿）/ 过账 / 作废；批次与库存台账可查。
      // 🔴 2026-11-06（用户本轮裁定）：**由「供应链」移入本组，且排本组第一** ——
      //    它是仓储这条动线的入口（收进来的布先落这里），采购是它的上游、归供应链。
      { key: 'inbound-orders', name: '入库单', icon: 'PackageOpen', path: '/inbound-orders', permissionCode: 'inbound:view', keywords: ['rkd', 'ruku', 'caigou'] },
      // 盘点单（issue #7373 段 2 后端 / 本项 = 商家面）：账面快照 → 逐批次录实盘 → 有差异先审批再完成。
      // 节点码 = 该页第一屏读端点码（`GET /api/admin/stocktakes` 的**方法级** `stock:view`）—— 逐字同码。
      { key: 'stocktakes', name: '盘点单', icon: 'ScanLine', path: '/stocktakes', permissionCode: 'stock:view', keywords: ['pdb', 'pandian', 'kucunpandian', 'pandian', '盘点', '盘点单', '盘库', '盘亏', '盘盈'] },
      // 出库单（V194 / issue #7750）：与「入库单」对称的**出口**单据 —— 布料手工出库 + 成品发货出库
      // 共用一套单据形状（单号 CK-…、建单即过账）。节点码复用 `stock:view`（收发同岗位，零授权 delta）。
      { key: 'outbound-orders', name: '出库单', icon: 'PackageMinus', path: '/outbound-orders', permissionCode: 'stock:view', keywords: ['ckd', 'chuku', 'outbound', '出库单', '出库'] },
      // 发货单（issue #5939，用户 2026-10-02 裁定）：与「入库单」对称的**出口**单据；
      // 取**既有** `order:list`（与销售订单同码、零授权 delta）。
      { key: 'shipments', name: '发货单', icon: 'Truck', path: '/shipments', permissionCode: 'order:list', keywords: ['fhd', 'fahuo', 'shipment', 'chuku', '出库', '发货'] },
      // 库存明细（issue #6404）：SKU 级库存**变化流水**的读面（「为什么系统说还有 30 米、实际只剩 12 米」）。
      // 节点码 = 该页第一屏读端点（`GET /api/admin/stock-ledger`）的方法级 `product:list`（逐字同码）。
      { key: 'stock-ledger', name: '库存明细', icon: 'ScrollText', path: '/stock-ledger', permissionCode: 'product:list', keywords: ['kcmx', 'kucun', 'mingxi', 'liushui', 'taizhang', '台账'] },
      // 余料台账（PR-106 / issue #5191）：码 = `processing:manage`（`RemnantController` 类级码逐字同码）。
      { key: 'production-remnants', name: '余料台账', icon: 'Recycle', path: '/production/remnants', permissionCode: 'processing:manage', keywords: ['yltz', 'yuliao', 'huishou'] },
      // 省料分析（issue #5699 P4）：两个读端点在 `StockBatchController` 上是方法级 `product:list`。
      // 2026-10-19 #7332 菜单正名「省料分析」；旧名「省料看板」保留为关键词。
      { key: 'production-saving-board', name: '省料分析', icon: 'TrendingDown', path: '/production/saving-board', permissionCode: 'product:list', keywords: ['slkb', 'shengliao', 'haoliao', '省料分析', '省料看板'] },
    ],
  },
  // 财务（2026-11-06 用户本轮裁定**新建**）：财务对账 + 计件工资。
  // 为什么这两项同一组：都是**结算面**（对客户收款 / 对工人计件），与「订单/商品」的**成交面**
  // 和「生产管理」的**执行面**分开 —— 一个财务/老板进这个组就能把两头钱看完。
  {
    key: 'finance-center',
    name: '财务',
    // 组图标 `Calculator`（原「财务对账」项的图标）：与组内两项（Banknote / Coins）及所有其它组图标
    // 两两不同（#5582）—— 原「交易管理」组撤销后该图标空闲，语义正好。
    icon: 'Calculator',
    children: [
      // 财务对账（#2969 原在「客户管理」组；#5271 并入交易管理；本轮随组迁入「财务」：
      // 对账是**收款侧**，不再与开单混在一组）。
      { key: 'finance', name: '财务对账', icon: 'Banknote', path: '/finance', permissionCode: 'finance:view', keywords: ['cw', 'caiwu', 'duizhang', '对账'] },
      // 计件工资（issue #5291 起节点码 = 生产域**读**码 `production:view`）：
      // 🔴 2026-11-06（用户本轮裁定）**由「生产管理」移入本组** —— 计件是**结算**（对工人算钱），
      //    不是生产执行；组内顺序 = 先对客户账、再对工人账。
      // issue #5675：本节点码与该页第一屏读端点码逐字同码（`GET /api/admin/production/piecework/summary`）。
      { key: 'production-piecework', name: '计件工资', icon: 'Coins', path: '/production/piecework', permissionCode: 'production:view', keywords: ['jjgz', 'jijian', 'gongzi'] },
    ],
  },
  // 供应链（issue #7369，用户 2026-10-20 裁定「新增的菜单不能放到仓储与物料下，得加个新大菜单」）：
  // 这条链是「买什么 → 谁供货」—— 用户 2026-11-06 的顺序 = **采购单 → 供应商**
  // （先有采购动作、再是主数据；与「订单/商品」组的「先操作后档案」同口径）。
  // ⚠️ 2026-11-06：「入库单」由本组移入「仓储/物料」（它是收货后的登记面，属仓）；本组只剩两项。
  {
    key: 'supply-chain',
    name: '供应链',
    icon: 'Route',
    children: [
      // 采购单（issue #7369，P0-1 段 4）：下单（买什么/多少钱/什么时候到）→ 分次收货 → 关闭。
      // 🔴 issue #8087：本节点改挂独立读码 `purchase:view`（原 `inbound:view`）。
      { key: 'purchase-orders', name: '采购单', icon: 'ShoppingBag', path: '/purchase-orders', permissionCode: 'purchase:view', keywords: ['cgd', 'caigou', 'caigoudan', 'purchase', 'po'] },
      // 供应商（issue #7369，P0-1 段 1）：进货**之前**的主数据（谁供货、账期几天、停没停）。
      // 🔴 issue #8087（用户 2026-10-29 裁定 C）：本节点改挂独立读码 `supplier:view`（原 `inbound:view`）。
      // 停用后仍要能看见（档案要能改回来）⇒ 不按状态门控。
      // ⚠️ 必须排在「入库单」**之后**：手机端可见面标注取该码树序首个承载节点（#6781）——
      //    「入库单」已在本组之前（仓储/物料）⇒ 满足。
      { key: 'suppliers', name: '供应商', icon: 'Handshake', path: '/suppliers', permissionCode: 'supplier:view', keywords: ['gys', 'gongyingshang', 'caigou', 'supplier'] },
    ],
  },
  // 组织管理（#6580 起「企业基础设置」已由本组移出 ⇒ 本组只有「人与权限」两件事）。
  {
    key: 'org-center',
    name: '组织管理',
    icon: 'Building2',
    children: [
      { key: 'employees', name: '员工管理', icon: 'Users', path: '/employees', permissionCode: 'employee:list', keywords: ['yggl', 'yuangong'] },
      // issue #5291：岗位权限节点改挂**读**码 `system:view`。
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
//
// ## 三个数组
//
//   · `standaloneHeadItems` —— **最前席位**（渲染在**所有分组之前**）：经营概览 / 报表中心；
//   · `standaloneTopItems`  —— **尾席位**（渲染在 `STANDALONE_TOP_AFTER_GROUP_KEY` 那个组之后）：
//     「企业基础设置」。席位组**不可见**时（权限把它整组过滤掉 / 常量写错）⇒ 回落到
//     **当前可见分组的末尾**：一级项**绝不允许跟着消失**（最坏退回旧位置，也不能没有入口）；
//     口径的**唯一实现** = `frontend/admin-web/src/lib/menu-nav.ts` 的 `splitGroupsAtTopItemSlot`
//     （`Sidebar.tsx` 与 `flattenMenu` 都调它，不各写一份 slice）。
//   · `standaloneItems`     —— **尾部项**（渲染在**所有分组之后**）：「通知中心」
//     （全员可见，与顶栏铃铛一致，无需权限码）。
//
// 🔴 **一级项不进「常用」**（#5877，用户 2026-10-01 裁定）：它已一屏可见、且**不再有星标** ⇒
//     可收藏面只含组内项 + 尾部独立项（否则同一屏会出现两条一模一样的入口）；
//     用户 localStorage 里残留的旧 key 按既有「无效 key 静默丢弃」口径处理。
//     判据：`frontend/admin-web/tests/unit/lib/menu-pinned.test.ts`。


/**
 * 一级项（`standaloneTopItems`）的**插入位**：渲染在**这个组之后**。
 *
 * ## 为什么是一个常量，以及为什么三源必须**同批**表达同一位置
 *
 * 「企业基础设置排在哪」这件事在**三处**各有表达，缺一处就是「岗位权限页勾得动、侧边栏看不到」的同族坑：
 *   ① **前端渲染位** —— 本常量（`Sidebar.tsx` 经 `splitGroupsAtTopItemSlot` 使用）；
 *   ② `MenuController.MENU_TREE` 的**顶层节点顺序**（`GET /api/admin/menus`，员工管理页的权限树）；
 *   ③ `AuthService.buildMenusByPermissions` 里顶层 `menus.add(...)` 的**文档位置**（登录下发的菜单）。
 *
 * 判据 = `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的**顶层布局序列**比对
 * （#5877 起含**位置**：只改本常量而不改服务端 ⇒ 当场判红）。
 * ⚠️ 取值必须是 `menuGroups` 里**真实存在**的组 key —— 写错 ⇒ 前端回落（一级项回到最前）
 *    而服务端不动 ⇒ 判据红（这是**有意**的：静默漂移比直接红更难查）。
 *
 * 🔴 2026-11-06（用户本轮裁定）：**由 `org-center` 改为 `supply-chain`** —— 用户给的十二项里
 *    「企业基础设置」排在**供应链之后、组织管理之前**（旧口径「排在所有分组之后 / 与通知中心一起
 *    沉底」是 2026-10-09 #6580 的裁定，本轮被明确改判）。它仍是**一级独立项**（不进任何组）。
 *
 * 🔴 本常量**只管尾席位**（`standaloneTopItems`）。**最前席位**（`standaloneHeadItems`，2026-10-17
 *    新增）**不需要常量** —— 它的位置由「数组第 1 项」与渲染顺序（`flattenMenu` 把 head 放在最前）
 *    直接表达；两个席位的相对顺序在 `flattenMenu` 的拼装里写死，`Sidebar.tsx` 与之同源。
 */
export const STANDALONE_TOP_AFTER_GROUP_KEY = 'supply-chain'
export const standaloneTopItems: MenuItem[] = [
  // 企业基础设置（2026-10-09 issue #6580 由「企业基础信息」改名、并从「组织管理」组移出；
  // 本轮 2026-11-06 用户把它排在**供应链之后、组织管理之前**）：
  // · 路径一字不动（`/settings`）；
  // · 🔴 **节点码 `system:manage` → `production:view`**（用户 2026-10-09 裁定，选项 A）：
  //   合并加工项管理 / 工艺配置之后，它是生产配置面**唯一的入口**，而真实配置者
  //   `operator` / `product_manager`（见 `rbac/manifest.json` 的 `roles.seed`）持
  //   `production:view`、**不持** `system:manage` ⇒ 不换码 = 菜单对他们恒不可见（#4203 同族坑）。
  //   页内**经营域**（企业信息 / AI 客服 / 通知设置）仍按各自的 `system:manage` 域级显隐 ⇒
  //   该码的**可授予面**不缩水（由 `MenuController` 的 org-center 组承载那一个权限码节点）。
  //   ⚠️ 守卫码与首屏读码的**有意不一致**已在
  //   `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_PARITY_RESIDUALS`
  //   具名登记（含 403 受害者认领）—— 判据 12 **只许登记、不许放宽**。
  // · 它是**配置指挥台**的宿主页（配置主线 + 配置域），设计真值源：
  //   `docs/design/enterprise-settings-redesign.md`。
  { key: 'settings', name: '企业基础设置', icon: 'Settings', path: '/settings', permissionCode: 'production:view', keywords: ['qyxx', 'shezhi', 'qiye', 'jichu', '配置'] },
]

export const standaloneItems: MenuItem[] = [
  // 通知中心：全员可见（与顶栏铃铛一致，无需权限码）
  { key: 'notifications', name: '通知中心', icon: 'Bell', path: '/notifications', keywords: ['tzx', 'tongzhi', 'xiaoxi'] },
]
