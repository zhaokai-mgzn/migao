# 观星台左侧大菜单（Sidebar IA）审计 — 2026-10-29

> **审计问题**：观星台左侧大菜单设计是否合理？参照主流 ERP 审计一次。
> **方法**：只读审计。① 读真值源（`frontend/admin-web/src/config/menu.ts` 等 5 个文件）；
> ② 用**真实代码**（esbuild 打包 `menu-nav.ts`，非手抄）把 8 个岗位的菜单投影、路由高亮、
> 命令面板顺序复算一遍；③ 与主流 ERP / SaaS 后台的公开形态对照；④ 看一张真实渲染截图。
> **没改任何代码**（IA 属业务口径，需用户裁定；见 §5）。
> **证据等级**：所有「现象」都带 `文件:行` 或复算读数；复算脚本见 §6，可一键重跑。
> **基线校正（2026-10-29 开工时）**：本报告初稿读的是 10-25 的工作树；正式开工时已按 `origin/main`（2523ac68）
> 复算 —— 菜单为 **28 项**（10-28 新增「出库单」），且 #8031（10-28）已把视觉层次拉正（组标题/一级项 14px/600、
> 36px 行、一级项**已去掉 chevron**、叶子项缩进三级）⇒ §0 的 P1-2 收敛为**纯 a11y 两项**（星标嵌在链接里、
> 无 `aria-current`）。§1 的节点数与 §3.2 已按新基线改正；§1.3 的截图是 10-22 的（早于 #8031），仅作历史形态参考。

---

## 0. 一页结论

**方向是对的，但 4 处不合理，其中 3 处会真实伤到人。**

对 20~50 人的布艺定制商家，「**2 层 + 按业务动线分组 + ⌘K 搜索 + 权限过滤**」这个骨架
比传统 ERP（金蝶/用友那种 3~4 级树）更适合；深度、广度、检索、空组剔除都达标，
三源同构守卫（菜单 / `MenuController` / `AuthService`）在中小 SaaS 里属于**超配**水平。

不合理集中在四点：

| # | 问题 | 严重度 | 一句话后果 |
|---|---|---|---|
| 1 | **授权粒度粗于菜单粒度**（一码管多菜单项） | **P1** | 客服看得见「供应商 / 采购单」（采购价）；质检员看得见「计件工资」（全员工资） |
| 2 | **a11y：星标按钮嵌在 `<a>` 里 + 当前项无 `aria-current`** | **P1** | `<a>` 内嵌 `<button>` = 无效 HTML，键盘会在链接里再落一次焦点；读屏拿不到「我在哪一页」（视觉层的同形问题已由 #8031 在 10-28 修掉） |
| 3 | **权限过滤后出现「单成员组」** | **P1** | 最常用的运营岗看到「组织管理 ① 员工管理」；财务/销售各看到 2 个只剩 1 项的组 —— 像没做完 |
| 4 | **自造「三个席位」把主数据 / 设置 / 通知堆在底部** | P2 | 「商品管理」（业务主数据）与「企业基础设置」（工具）并排紧贴「通知中心」，语义不互斥 |

**建议**：不推倒重来。先做一批**纯前端、零授权 delta** 的定点修正（§4 Batch A，1 个 PR），
其余 3 项涉及权限码 / 业务口径，按 §5 由你裁定。

---

## 1. 现状（复算读数，不是转述注释）

### 1.1 规模

- **28 个导航节点 = 6 组 23 项 + 5 个独立项**（最前席位 2：经营看板 / 报表中心；尾席位 2：商品管理 / 企业基础设置；尾部 1：通知中心）。
  ⚠️ `frontend/admin-web/src/config/menu.ts:13-14` 的文件头仍写「**5 组** 22 项（现取 2026-10-24）」—— 实为 6 组、且 10-28 又加了「出库单」；
  即文件头同时**漏了两轮**（见 §3 末尾 P3 第 1 条）。
  实际组：客户服务(4) · 交易管理(3) · 生产管理(5) · 供应链(3) · **仓储与物料(6)** · 组织管理(2)。
- **层级 = 2 层**（组 → 项），无三级；组内最多 5 项。
- **6 个渲染区**（从上到下）：`常用(收藏)` → `最前席位一级项` → `head 组` → `尾席位一级项` → `tail 组` → `尾部独立项` → 页脚
  （语义与实现：`frontend/admin-web/src/config/menu.ts:32-38`、`frontend/admin-web/src/components/layout/Sidebar.tsx:394-463`、`frontend/admin-web/src/lib/menu-nav.ts:288-296`）。

### 1.2 八个岗位看到的菜单（真实代码复算）

> 数据源：`rbac/manifest.json` 的 `roles.seed`（7 个种子岗位）+ admin。

| 岗位 | 项数 | 组数 | 登录落点 | 单成员组 |
|---|---|---|---|---|
| admin | 28 | 6 | /dashboard | — |
| operator（运营，最常见） | 26 | 6 | /dashboard | **组织管理→员工管理** |
| customer_service（客服） | 17 | 5 | /dashboard | — |
| sales（销售） | 16 | 5 | /dashboard | **客户服务→客户列表**、**生产管理→智能派单** |
| finance（财务） | 14 | 5 | /dashboard | **客户服务→客户列表**、**生产管理→智能派单** |
| product_manager（商品） | 11 | 2 | /dashboard | — |
| knowledge_editor（知识编辑） | 7 | 2 | /dashboard | **客户服务→知识库** |
| inspector（质检） | 5 | 1 | **/production** | — |

读数要点：
- **4 / 8 岗位命中单成员组**，共 6 处（operator 1、finance 2、sales 2、knowledge_editor 1）——
  而 `frontend/admin-web/src/config/menu.ts:386-388` 恰恰把「唯一成员的组会退化成一个没有分组的名字」写成过设计原则，
  但那条原则只在**静态菜单**上执行过（商品管理升为一级项），**没有对权限过滤后的结果执行**。
- **质检员没有「经营看板 / 报表中心」**（`dashboard:view` 不持有），落点是 `/production`；
  它看不到与质检最有关的「质量成本」报表（`报表中心` 的关键词里就有它，但整项被 `dashboard:view` 门控）。
- **客服看不到「商品管理」「企业基础设置」**（未持 `product:list` / `production:view`），
  却能看到 `供应链` 整组 3 项 —— 见 P1-1。

### 1.3 真实渲染（视觉证据）

`acceptance/2026-10-22-7476-sidebar-brand/01-full.png`（2026-10-22 截图；**早于 10-28 的 #8031**，
只作历史形态参考 —— 当时一级项还挂 chevron、字号还与组头同档）：
首屏一列读下来是 `经营看板` / `客户服务 (4)` / `交易管理 (2)` / `生产管理 (3)` / `供应链 (3)` /
`仓储与物料 (4)` / `组织管理 (2)` / `商品管理` / `企业基础设置` / `通知中心`。
当时 **`经营看板`、`商品管理`、`企业基础设置` 与 6 个分组头在字号（12px）、图标（14px）、
chevron、灰度上完全同级**，只有「有没有项数徽标」这一处差别 —— 这一形态已被 #8031 修掉（见 §2 对照表）。

---

## 2. 与主流做法的对照

主流 ERP 今天基本收敛到「**浅层 + 按角色 + 靠搜索**」，深树是上一代形态：

| 维度 | 主流做法（例） | 本案 | 判定 |
|---|---|---|---|
| **层级深度** | NetSuite 中心标签 → 分类 → 菜单链接（≤3）；Dynamics 365 Business Central 角色中心 + Departments（2）+ “Tell me” 搜索；SAP S/4HANA Fiori 用按角色的 launchpad（space/page）；Odoo 顶部 app + 二级菜单 | **2 层**，无三级 | ✅ 合格（优于传统 3~4 级树） |
| **组内广度** | 5±2 项为舒适区，超过就拆组或交给搜索 | 3 / 4 / 5 项 | ✅ 合格 |
| **分组语义互斥（MECE）** | 一个组 = 一个职能域（NetSuite：Financials / Inventory / CRM 各成中心） | 生产管理混「计划派单 + 计件工资 + 质检 + 返工」；交易管理混「价格主数据 + 订单 + 对账」 | ⚠️ 部分 |
| **一级项 vs 分组头** | 组头是**不可跳转**的 section label（或点击只折叠），一级项走 item 规格；两者视觉必须可分 | **已修（#8031，2026-10-28）**：组标题 14px/600（无图标、28px 行，纯标签）vs 一级项 14px/600 + 18px 图标 + **36px 行、无 chevron**；叶子项缩进 `pl-7` | ✅ 合格（同类修复**不必重做**） |
| **角色适配** | Fiori launchpad / BC Role Center / NetSuite 角色中心：**不同岗位首页与菜单不同** | 8 个岗位共用一套树 + 按码过滤；除质检员外全落 `/dashboard`（看板是「看」不是「做」） | ⚠️ 部分 |
| **授权粒度 ≡ 导航粒度** | 每个菜单项对应一个可授予能力/记录类型，勾 A 不带出 B | 1 个码管 2~4 个菜单项（`inbound:view` → 入库单/供应商/采购单/盘点单；`product:list` → 商品管理/库存明细/省料看板；`production:view` → 作业看板/计件工资/企业基础设置） | ❌ 不合格 |
| **主数据 vs 设置的位置** | 主数据集中在「基础资料」或归入所属域；**设置沉底**或进用户菜单（Shopify 的 Settings、NetSuite 的 Setup） | 商品管理（主数据）沉底，与企业基础设置（工具）并排；客户/供应商/价格本按域归属（Odoo 式，合理） | ⚠️ 混排 |
| **检索与快捷** | 全局搜索（⌘K / Tell me / 统一搜索）+ 收藏夹 + 最近访问 | ⌘K 有（全量索引、拼音首字母、组名命中）；收藏有（上限 6）；**无「最近访问」**，收藏**不可排序** | ✅ / ⚠️ |
| **「我在哪」** | 当前项高亮 + 面包屑；**非菜单页面也保留父级高亮**（进设置子页，Settings 仍亮） | 高亮 + 面包屑有；**3 个功能页侧边栏零高亮**（P2-1） | ⚠️ 部分 |
| **折叠态（rail）** | 折叠后 **hover 飞出二级菜单**，图标带分组提示（NetSuite / Fiori / Odoo） | 折叠 = 28 个图标竖排，组锚不可点、无飞出，需 ~1260px 才不滚动 | ❌ 不合格 |
| **术语一致性** | 一个词一个意思 | 「看板」三处三义；「客户列表」vs「商品管理」（列表 vs 管理，同一层级两种命名范式） | ⚠️ 部分 |
| **结构可维护性** | 一棵有序树，位置即顺序 | 位置由 **3 个席位数组 + 1 个常量 + 服务端顺序**共同表达（三源同构守住），改一个位置要动 3~5 处 | ⚠️ 复杂度税 |
| **稳定性** | 菜单是肌肉记忆的载体，改版以季度/年计 | `menu.ts` 近 40 次提交、**一个月内 8 轮重排**（09-23 / 09-29 / 10-01 / 10-06 / 10-09 / 10-17 / 10-20 / 10-24） | ⚠️ 观察项 |

> 参考：Business Central 的 role center 形态（[MS Learn](https://learn.microsoft.com/zh-tw/dynamics365/business-central/dev-itpro/developer/devenv-designing-role-centers)）、
> NetSuite 的 centers 导航（[Anchor Group](https://www.anchorgroup.tech/blog/create-navigation-dropdown-tabs-in-netsuite)）、
> Odoo 的 app → 子菜单结构（[ivy-framework 参考](https://github.com/ivy-interactive/ivy-framework/blob/f6b1d065f725d4fc27ec99b69e773750920f4145/src/claude-plugin/skills/ivy-convert-odoo/references/menu-navigation.md)）、
> Shopify admin 的新版导航（[Makro](https://www.makroagency.com/shopify-updates/a-new-look-for-the-shopify-admin)）。

---

## 3. 问题清单

### P1-1 授权粒度粗于菜单粒度 —— 菜单把人带到他职责之外的地方

**现象（复算）**
- `customer_service`（客服，`roles.seed` 里持 `inbound:view`）→ 侧边栏出现 **供应链 3 项：入库单 / 供应商 / 采购单**；
  而它的 `product:list` 是**没有**的 ⇒ 看不到商品管理，却看得到供应商档案与采购单（含采购价）。
- `inspector`（质检，持 `production:view`）→ 出现 **计件工资**（全员计件工资页）与 **企业基础设置**。
- `knowledge_editor`（持 `product:list`）→ 出现 **库存明细 / 省料看板**（商品目录的码顺带放出了仓库流水）。

**根因**：菜单节点码是**域读码**而不是**对象/菜单码**（历史选择：不新造码是为了避免 #4203 那类「新码今天没人持有 ⇒ 菜单对所有人不可见」）。
代价是「想给 A，必须同时给 B」：

| 码 | 顺带打开 | 文件:行 |
|---|---|---|
| `inbound:view` | 入库单 + **供应商** + **采购单** + 盘点单 | `frontend/admin-web/src/config/menu.ts:335/339/342/358` |
| `product:list` | 商品管理 + **库存明细** + **省料看板** | `frontend/admin-web/src/config/menu.ts:354/365/435` |
| `production:view` | 作业看板 + **计件工资** + **企业基础设置** | `frontend/admin-web/src/config/menu.ts:294/300/465` |
| `after_sales:view` | 售后工单 + 返工单 | `frontend/admin-web/src/config/menu.ts:219/312` |

**反向代价**（同样真实）：想配一个「仓管」岗位看到仓储与物料 5 项，得勾 **4 个码**
（`product:list` + `inbound:view` + `order:list` + `processing:manage`），其中 `product:list`
还会把「商品管理」带出来 —— 而 `roles.seed` 里**根本没有仓管岗位**（7 个种子岗位里没有仓库角色），
所以仓管职责今天是靠 operator/客服/财务的码「顺手覆盖」的。

**主流做法**：NetSuite/Fiori 的菜单可见性按**对象/记录类型**授权，给「收货」不会自动给「供应商档案 + 采购价」。

**修法（需裁定，见 §5-Q1）**
- A（推荐，干净）：拆 3 个码 —— `supplier:view` / `purchase:view`（供应链两项）、`stock:view`（库存明细 + 省料看板）；
  `inbound:view` 只留入库单/盘点单。代价：`rbac/manifest.json` 单一源 + 两处 Java 目录 + 迁移 + 岗位矩阵 +
  手机端 `MobileSurfaces` 投影 + `test_agent_permission_parity` 同批（**跨 5 处真值，1 个 PR 做完**）。
- B（最小、只堵最有感的一条）：只拆 `supplier:view` + `purchase:view`，先解决「客服看见采购价」。
- C（不拆码，只改菜单）：把供应商/采购单挂 `inbound:create` —— **不建议**：又造出一个「能建单才能看档案」的错配。

---

### P1-2 a11y：星标按钮嵌在链接里 + 当前项无 `aria-current`（视觉层那一半已由 #8031 修掉）

**现象（按 10-29 origin/main 复核）**
- 星标按钮是 `<Link>` 的**子元素**（`Sidebar.tsx` 的 `renderItem` / `renderStandaloneItem`）——
  `<a>` 内嵌 `<button>` 是无效 HTML，键盘 Tab 会在链接里再落一次焦点，读屏会把
  「加入常用：在线接待」读成链接的一部分（按钮的 `aria-pressed` 也会挂进链接的可访问名）。
- 全仓 `aria-current` **零使用**（`grep -r aria-current frontend/admin-web/src` = 0）⇒ 当前页对读屏用户不可知。
- ⚠️ **「一级项与分组头同形」那一半已于 2026-10-28 被 #8031 修掉**（组标题 14px/600 纯标签 + 28px 行；
  一级项 14px/600 + 18px 图标 + 36px 行 + **无 chevron**；叶子项 `pl-7` 缩进）——
  **本轮不要重做这一半**（重做会推翻用户 10-28 的裁定）。

**修法（纯前端，Batch A —— issue #8085 已落地）**
- 星标搬到 `<a>` 的**兄弟**位置（绝对定位盖在行尾，链接右侧 `pr-9` 让位）；
- 当前项补 `aria-current="page"`；
- 组头折叠仍靠 `aria-expanded`（既有，不动）。

---

### P1-3 过滤后出现「单成员组」（4/8 岗位命中）

**现象（真实复算）**
- operator（最常见）：`组织管理 ① 员工管理`
- finance / sales：`客户服务 ① 客户列表`、`生产管理 ① 智能派单`
- knowledge_editor：`客户服务 ① 知识库`

**为什么是问题**：仓里自己的原则（`frontend/admin-web/src/config/menu.ts:386-388`）写着「『唯一成员』的组会退化成一个没有分组的名字
（点开只为看一项）⇒ 改为一**级项平铺**」—— 但那只对静态菜单执行过；**权限过滤是运行时的**，
过滤后的单成员组没有同样处理。视觉上等于「一个父子关系不成立的空壳标题」，
而它恰好出现在**最常见岗位**身上。

**主流做法**：菜单由「角色 × 可用模块」生成时，单子项的分组直接提升为该层的条目（NetSuite 中心不显示只有一个链接的分类）。

**修法（纯前端，Batch A）**：在 `visibleMenuGroups` 之后加一个纯函数
`promoteSingleItemGroups(groups)`（组内 1 项 ⇒ 渲染成一级项，**位置不变**、⌘K 顺序不变、权限树不变），
补表驱动判据（8 岗位 × 「不存在单成员组」）即可，零授权 delta。

---

### P2-1 非菜单页面的「我在哪」失效

**现象（对 43 个后台静态路由穷举）**：**3 个功能页侧边栏零高亮**：
`/approvals`（审批中心，入口在顶栏铃铛）、`/categories`（商品分类，入口在商品编辑页）、
`/agent-workspace/sessions`（会话监控，入口在客服工作台）。
另有 4 个同象但不必修的：`/chat`（黄金策·在线对话，**有意**不进菜单、走右下角 FAB）
与 3 个重定向壳（`/briefing` → `/dashboard`、`/agent-workspace` → `human-sessions`、`/processing` → `/production/processing`）。
（`/production/processing` 这类被移除菜单项的旧页会**错误地**高亮到「作业看板」—— 前缀同源）
`/processing-orders/{id}/production` 靠 `LEGACY_PATH_ALIASES` 已经正确高亮到「作业看板」（`frontend/admin-web/src/lib/menu-nav.ts:206-208`）。

**后果**：从顶栏点进审批中心，侧边栏 28 项**全灭** —— 用户失去「我在哪个域」的锚点（面包屑只给了页面名）。
审批中心是 2026-10-24 主动撤掉菜单项的（#7593），撤得对（静态菜单没有信号），但**归属高亮没跟着补**。

**主流做法**：子页/工具页保留父级高亮（Shopify 进 Settings 子页时 Settings 仍亮；NetSuite 中心标签常驻）。

**修法（纯前端，Batch A）**：把 `LEGACY_PATH_ALIASES` 升级为「页面 → 归属菜单项」的 `PARENT_HINTS`
（`/approvals → 交易管理/财务对账`、`/categories → 商品管理`、`/agent-workspace* → 在线接待`），
高亮解析时用它兜底；判据 = 表驱动穷举全部静态路由「至少一个高亮」（把这次穷举变成测试）。

---

### P2-2 折叠态（rail）不可用

**现象**：折叠后 `collapsed || isExpanded` ⇒ **28 项图标全部常显**（`frontend/admin-web/src/components/layout/Sidebar.tsx:267`），
组锚是**不可点的 `div`**（`:232-241`，只有 `title`）。实测纵向需求 ≈ **1260px**（28 项×36 + 6 组锚×28 + 搜索/页脚余量），
在 900px 高的屏上要滚动，且**滚动区里没有任何分组文字**，只能靠 hover title 猜。
主流：折叠后 hover 图标 → 飞出该组项（NetSuite / Fiori / Odoo 都是这个形态）。

**修法（Batch A'，中等成本）**：折叠态改为「组图标 + hover/focus 飞出面板」；无权限项的组不出现在 rail。
若短期不做，至少让组锚可点（点一下 → 临时展开成浮层）。

---

### P2-3 生产管理组混了三种角色的活

`作业看板 / 智能派单`（计划员）、`计件工资`（班组长/财务）、`质检记录 / 返工单`（质检员）同组。
后果：质检员进组看到计件工资；operator 的组里 4 项分属 3 种工作节奏。
主流：生产中执行/质量分模块（NetSuite 有独立的 Quality Management；Odoo 有 Quality 子模块）。
**建议**（需裁定）：把「质检记录 + 返工单」提为「质量管理」组（或至少在组内加子分区），
顺带解决 P1-1 的质检员越权可见（拆组时天然可以给不同码）。

### P2-4 主数据与设置混排（尾席位）

`商品管理`（业务主数据，产品生命周期最长、被所有人引用）沉在**所有分组之后**，
紧挨 `企业基础设置`（工具页）与 `通知中心`（全局广播）。三者性质不同却连成一片：
- 主流：主数据进「基础资料」或归域；**设置沉底/进用户菜单**；通知是常驻徽标不是导航项。
- 本案的问题不是「谁在哪一行」，而是**这一行同时承担了三种语义**，用户无法从位置推断性质。
  （注：这是 2026-10-06「11 个大菜单项并列」+ 2026-10-09「与企业基础设置一起沉底」两次裁定的累积结果，
  单独看每条都成立，叠起来才露出语义冲突。）
**建议**（需裁定）：只动一处即可缓解 —— 给 `商品管理` 找一个**有语义的邻居**（如与「客户列表/供应商」组成
「基础资料」）或在它上面加一条更粗的分隔；`企业基础设置 + 通知中心` 保持沉底。

### P2-5 供应链 / 仓储把「入库」从「库存与盘点」切开

物流动线是「采购 → 到货 → **入库** → 库存/盘点 → 发货」。
今天 `入库单` 在 `供应链`，`库存明细 / 盘点单 / 发货单` 在 `仓储与物料` ⇒ 仓管要跨两个组完成一次「到货→过账→对账」。
（这是 2026-10-20「入库单是采购到货的登记面，随供应链走」的裁定结果。）
主流：NetSuite 把 收货/入库/库存/发货 都放在 Inventory 中心，采购单在 Purchasing。
**建议**（需裁定，低优先）：`入库单` 移回仓储组，供应链只留 供应商 / 采购单；或反向把「盘点单」提上去。二者选一，别两边都有单据。

### P2-6 术语过载：「看板」三义

`经营看板`（dashboard）、`作业看板`（作业单列表）、`省料看板`（分析视图）。
在 ERP 语境里「看板（Kanban）」特指**拉动式看板**，三处用法各不相同（一处是 BI、一处是单据列表、一处是分析）。
主流命名：Dashboard / Work Orders / Analytics。
**建议**（需裁定，改名成本高：三源 + 面包屑 + 手机端投影 + 评测 cases）：优先改 `省料看板 → 省料分析`
（语义最偏），`作业看板` 保留（它确实是列表面包屑的历史裁定）。

### P3 其它（登记，不单独成单）

1. **陈旧数字**：`frontend/admin-web/src/config/menu.ts:13` 写「5 组 22 项」实为 **6 组**；`Sidebar.tsx` 仍写「21 项」实为 **28 项**。
   （判据不会红 —— 测试里钉的是 27。）
2. **设计规范脱节**：`docs/design/ui-design-spec.md:363-371` 仍是「三级缩进菜单」+ `:597-601` 「220px / 64px」，
   与实现的 2 层 / 240px / 6 渲染区不符。
3. **展开态不持久化**：刷新后回到「只展开当前组」（`frontend/admin-web/src/lib/menu-nav.ts:257-259`），用户手动展开的组会缩回。
4. **收藏不可排序**：顺序 = 钉的顺序（`frontend/admin-web/src/lib/menu-nav.ts:140-145`），主流收藏可拖拽。
5. **无「最近访问」**：28 项里高频只有 3~5 项，⌘K 已缓解，但「最近」是零成本的高频补偿。
6. **「价格本」** 非行业通用词（主流：价目表 / 价格政策 / Price List），⌘K 已收录「价目表」别名。

---

## 4. 建议的落地顺序

> 所有改动都受三源同构守卫约束（`menu.ts` / `MenuController.MENU_TREE` /
> `AuthService.buildMenusByPermissions`）+ 面包屑末项 == 菜单名（PG-038）+ `Sidebar.test.tsx` 里
> **`toHaveLength(27)`** 的钉子 ×4 处 —— 改结构时这些都同批。

**Batch A（纯前端，零授权 delta —— issue #8085 已落地）**
1. P1-2 星标移出 `<a>` + `aria-current="page"`（**不动** #8031 定下的视觉层次）；
2. P1-3 `promoteSingleItemGroups` 纯函数 + 8 岗位判据；
3. P2-1 `PARENT_HINTS` 兜底高亮 + 「全部静态路由至少一亮」的穷举判据。
   → 预期收益：最常见岗位（operator/财务/销售/知识编辑）的视觉完整度、读屏可用性、审批中心归属。
   → 回归面：`Sidebar.test.tsx`、`SidebarRedesign.test.tsx`、`menu-nav.test.ts`、`menu-pinned.test.ts`、九宫格截图回归。

**Batch B（位置/命名，需裁定）**：P2-3 质量独立组 → P2-4 商品管理的邻居 → P2-5 入库单归位 → P2-6 改名。
（按「一次只动一处位置」推进，每步单独 PR，避免又制造一轮「§2 稳定性」里那种一个月 8 次的重排。）

**Batch C（RBAC，需裁定 + 跨 5 处真值）**：P1-1 拆码（方案 A/B）。

**不建议改**（这次审计确认它是对的）：
2 层深度、⌘K 全量索引（含拼音首字母与组名命中）、收藏夹与权限的双重过滤、
空组剔除、折叠态保留分组锚点、「当前位置自动展开所在组」、三源同构守卫、图标两两不同。

---

## 5. 需要你裁定的 4 个问题（带选项与代价）

| # | 问题 | 选项 | 代价 / 不裁的安全默认 |
|---|---|---|---|
| Q1 | **是否拆权限码**（客服不该看见供应商/采购单；质检员不该看见计件工资） | A 全拆 3 个码 / B 只拆供应商+采购单 / C 不拆，只记录为已知可见面 | A/B 跨 5 处真值 + 迁移；不裁 ⇒ 保持现状（信息面维持今天的样子），但**记入风险台账** |
| Q2 | **商品管理怎么摆** | ① 保持沉底（现状）② 与客户/供应商组成「基础资料」③ 移到交易管理之前作独立项 | ②③ 要改三源 + 面包屑；不裁 ⇒ 保持现状 |
| Q3 | **是否给「质量」独立组**（质检记录 + 返工单） | ① 独立成组 ② 留在生产管理但排到末尾 ③ 不动 | ① 多一个组（7 组），但质检员/运营的动线更清楚；不裁 ⇒ 保持现状 |
| Q4 | **「省料看板」是否改名「省料分析」** | ① 改 ② 不改 | 改名牵连三源 + 手机端投影 + 评测 cases（`keywords` 可保旧名可搜） |

> 说明：Q1 涉及权限（铁律 §12「权限」五类之一）必须人工裁定；Q2/Q3 是业务口径；
> Q4 是用户可见文案。其余 P3 项我可以直接排期，不需要裁定。

---

## 6. 附录：复算命令（可一键重跑）

```bash
cd frontend/admin-web
# 把真实菜单模块 + 纯函数打包成 CJS（不手抄菜单，避免转述误差）
cat > /tmp/audit-entry.ts <<'EOF'
import { menuGroups, standaloneHeadItems, standaloneTopItems, standaloneItems, STANDALONE_TOP_AFTER_GROUP_KEY } from '@/config/menu'
import { visibleMenuGroups, filterMenuItems, splitGroupsAtTopItemSlot, flattenMenu, landingPath, resolveActivePath } from '@/lib/menu-nav'
const roles: Record<string,string[]> = { admin:['*'] /* 其余见 rbac/manifest.json roles.seed */ }
for (const [role, perms] of Object.entries(roles)) {
  const opts = { permissions: perms, roles: [role] }
  const groups = visibleMenuGroups(menuGroups, opts)
  console.log(role, flattenMenu(groups, filterMenuItems(standaloneHeadItems,opts), filterMenuItems(standaloneTopItems,opts), filterMenuItems(standaloneItems,opts)).length,
    'landing=', landingPath(opts), '单成员组=', groups.filter(g=>g.children.length===1).map(g=>`${g.name}→${g.children[0].name}`))
}
EOF
./node_modules/.bin/esbuild /tmp/audit-entry.ts --bundle --platform=node --format=cjs \
  --outfile=/tmp/audit.cjs --alias:@=./src --log-level=error && node /tmp/audit.cjs
```

本次审计的实测读数（可在 PR/issue 里复核）：
`28 项 / 6 组 / 23 组内项`；`operator 26 项·1 个单成员组`；`finance 14 项·2 个单成员组`；
`sales 16 项·2 个单成员组`；`knowledge_editor 7 项·1 个单成员组`；`inspector 5 项·落点 /production`；
`43 个后台静态路由中 3 个功能页侧边栏零高亮`；`折叠态纵向 ≈ 1260px（含搜索/页脚余量）`。
（复核口径：把 §6 的脚本换上当前 `menu.ts` 即可；#8085 起这条穷举已变成常驻判据
`menu-nav.test.ts` 的「每个后台静态路由至少一个锚点」。）
