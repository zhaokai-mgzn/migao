# 工序模型收敛 + 工艺项界面改造（公共工序两层模型）

> 状态：**设计 · 待实施** ｜ 日期：2026-09-20 ｜ issue **#4673**（用户裁定「把 UI 改造作为 #4673 的一部分，直接开干」）
> **本文是 docs-only**：不改任何生产代码、不改数据、不碰 ai-agent、不改 `.github/workflows/**` 与 `.agent-presets/**`。
> 本单交付 = **设计**（模型 + 界面 + 迁移方案）。落码是后续独立单。
>
> ## 引用约定（本文件实际遵守）
> ① 代码/迁移引用**一律写仓库相对全路径 + `path:NNN`**（如 `backend/ai-agent-service/app/production/routing.py:461`）——
> CI 的 `Case Trust Gate` 规则 G 对**裸文件名**引用判 `CASE-TRUST-STALE-LINE-REF`（**阻塞**，见 #4668）。
> ② 行号是 **`origin/main` @ `06f0126a5`**（`git rev-parse origin/main`）这一刻的读数；`origin/main` 前移后会漂。
> ③ 凡**没实测到**的一律进 §8「无法判定」，**不把「应该/大概」写成事实**。
>
> ## 用户裁定（逐字，本文的立论依据，全部来自 #4673 的评论）
> > 「布料单该用 **裁剪**」
> > 「我的建议：**把 UI 改造作为 #4673 的一部分** 直接开干」
> > 「**打包需要计件**」
> > 「第二个问题，**是裁剪**」

---

## 0. 大白话：今天商家看到什么 / 改完看到什么

### 今天（`origin/main` @ `06f6a12` 实测）

打开「工艺配置 → 工艺项」，商家看到的是一张**平铺大表**：

```
工艺项 · 计件单价（给工人）          30 道工序 × 4 个部位 = 120 格
┌──────────┬────────┬────────┬────────┬────────┬──────────────────┐
│ 工序      │ 布帘    │ 纱帘    │ 帘头    │ 布料 ←  │ 元数据 / 操作      │
├──────────┼────────┼────────┼────────┼────────┼──────────────────┤
│ 精裁      │ ¥0.40  │ ¥0.40  │ ¥0.40  │ 不做    │ 裁剪 · 米  管理▸  │
│ 三边      │ ¥0.40  │ ¥0.40  │ ¥0.40  │ 不做    │ 车位 · 米  管理▸  │
│ …（26 道同理，布料列一律「不做」）              │                  │
│ 配料      │ 不做    │ 不做    │ 不做    │ 未定价  │ 后道 · 米  管理▸  │
│ 打包      │ 未定价  │ 未定价  │ 未定价  │ 未定价  │ 后道 · 套  管理▸  │
└──────────┴────────┴────────┴────────┴────────┴──────────────────┘
```

三个问题（都是用户实测踩到的）：

1. **`布料` 被当成「第 4 个部位」列出来** —— 它是**销售形态**（卖布按米），不是窗帘的部位。它的存在只为了让「布料单」能在部位矩阵里有一格价 ⇒ 代价是 **36 格价目**（V79 实测：28 道既有工序 × 布料 + 配料 × 4 + 打包 × 4 = 36 行），其中 **28 格是逐行显式「不做」**（噪音）。
2. **「打包」这类「所有形态都做、不按部位」的活被按 4 个部位重复渲染成 4 格** —— 商家要改一次价，得改 4 个格（或看到 4 个「未定价」）。
3. **`配料` 是行业里不存在的工序** —— 行业文档里它对应的是「**物料分配**」（收发人员的活），**不在车间三段（裁床 / 车位 / 烫工及后整）里**。

### 改完（本设计的目标形态）

```
工艺项 · 计件单价（给工人）
├ 配置就绪度：① 工序库 → ② 工艺路线 → ③ 默认路线 → ④ 算料配置
│
├ 【工序】按车间分组可折叠（行业术语）
│   ▾ 裁剪（裁床）
│       精裁      ¥0.40 │ ¥0.40 │ ¥0.40    裁剪 · 米   必完  管理▸
│   ▾ 车位（缝制）
│       三边      ¥0.40 │ ¥0.40 │ ¥0.40    车位 · 米   必完  管理▸
│       韩褶      ¥0.40 │ ¥0.40 │ ¥0.40    车位 · 折   必完  管理▸
│       …（略）
│   ▸ 后整（烫工及后整）  （可折叠）
│   ▸ 其他                （可折叠）
│
└ 【打包发货】★ 一列价（不按部位）   行 = 打包 / 打卷 / 装袋 / 发货
        打包      ¥x.xx /套   必完  管理▸
        外帘打卷   ¥1.00 /套   必完  管理▸
        外帘装袋   ¥1.00 /套   必完  管理▸
        外帘发货   ¥1.00 /套   必完  管理▸
```

- **列 = 布帘 / 纱帘 / 帘头**（3 列）—— **`布料` 不再出现为列**；
- **三态语义一字不变**：`不做` / `未定价`（= 做但没价，**≠ ¥0.00**）/ `¥x.xx`；
- **交付环节一列价**：不再按部位重复 4 格。

> ⚠️ 「一列价」在本设计里有**两层含义**，必须分清（详见 §3.4 与 §7.1 的实测冲突）：
> **界面层**（本单交付）= 一个价格单元；
> **数据层**（现状）= 仍是矩阵格（`scope='set'` 的格），**不是**「工序库行价」。
> 用户描述里的「走既有 `矩阵价 ?? 工序库价` 兜底」在**代码里只对「矩阵里没有这一格」成立**，
> 对「格存在但价为 NULL」**不成立** —— 实测见 §3.4。

---

## 1. 术语（**行业文档为准**，不是我们发明的）

### 1.1 仓库内的真值源（逐字）

`docs/curtain-production-rules.md:26`【标】：

> **工序分组**：`裁剪 / 车位 / 后道 / 其他`（**不是按阶段，是车间工位分组**）。

`docs/curtain-production-rules.md:27`【标】：

> **工序按部位分设**：同一道工序在布/纱/帘头上单价各自不同（韩褶-布、韩褶-纱…）。

⇒ 这两条是**本设计的行业依据**：分组 = **车间工位**（不是流程阶段）；价 = **按部位分设**。

### 1.2 行业正名（来源：《成品窗帘生产流程及工作规范》，**用户提供的外部文档**）

> ⚠️ **如实登记**：该文档**不在本仓库内**（实测 `git ls-tree -r --name-only origin/main | grep -i "生产流程\|工作规范\|成品窗帘"` ⇒ **零命中**）。
> 下面这张对照表引自用户在本单评论里给出的逐字引文 + 仓库内既有登记，**我无法在仓库内逐字复核**（进 §8「无法判定」U1）。

| 仓库分组（`production_operations.group_name`） | 行业正名 | 行业职责（用户引文） |
|---|---|---|
| **裁剪** | **裁床** | 复核收到的布料 → 裁剪 → **按套件打捆** → 发放给车位 |
| **车位** | **车位** | 负责布艺产品的**缝制**；缝制中如需**中烫** ⇒ 找烫工处理**再取回继续缝** |
| **后道** | **烫工及后整**（+ 质检 + 包装） | 「**不可缺少的辅助工序**」；**质检贯穿全过程**；**包装是最后一道工序** |
| **其他** | （无对应） | 配套软装件（绑带 / 抱枕 / 腰靠垫）—— `backend/ai-agent-service/app/production/routing.py:43-51` 实测：绑带-布/绑带-纱/抱枕/腰靠垫 = `其他` |

⇒ **结论（术语收敛）**：

- **「后道」是 ERP 简称**，行业正名是「**烫工及后整**」（+ 质检 + 包装）；
- **界面第一层用行业术语**（裁剪 / 车位 / 后整 / 质检），**不许**用「槽位」这类我们发明的词
  （另一份设计 `docs/design/operation-slot-model.md` 的「槽位」只作**主线内部细分**，见 §7.1）；
- 另有一处**仓库外**权威定义（用户引百度百科「车位工」）：车位工 = 「熟悉各种**车缝制作工艺**、能熟练操作**衣车**的操作工，主要工作是**缝纫和熨烫**……**计件**」
  —— 同样**不在仓库内**，同入 U1。

### 1.3 「打褶槽」是全仓唯一有真值源依据的「槽」

实测（`git grep -n "槽位" origin/main -- backend/ai-agent-service/app/production/routing.py`）：

```
backend/ai-agent-service/app/production/routing.py:470: #: （槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入）
backend/ai-agent-service/app/production/routing.py:471: ROUTE_MAINLINE: List[str] = ["精裁", "三边", "⟪工艺槽位⟫", "熨烫", "定型", "复烫",
```

⇒ **如实写**：真值源里**只有「打褶那一道」这一个槽位**有逐字依据（`ROUTE_MAINLINE` 第 3 位字面量 `⟪工艺槽位⟫`，注释冻结其语义 = 打褶那一道）。
`docs/design/operation-slot-model.md:389-391` 另外定义了「边缘槽 / 挂钩槽 / 蒸烫槽」等 —— 那是**该设计的推导**（它自己在 `docs/design/operation-slot-model.md:194` 登记「语义冻结处 = 打褶那一道」），**不是**真值源逐字。
⇒ 本设计**不引用**任何槽位名做界面分区（§7.1）。

---

## 2. 现状（实测）

> 全部命令见 §附录 A。行号 = `origin/main` @ `06f6a12`。

### 2.1 工艺项表结构

| 维度 | 现状 | 证据 |
|---|---|---|
| **行** | 逻辑工序（`logical_name`） | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1061`（`matrixRows`：按 `cell.operation` 分组成行） |
| **列** | 部位 —— **闭词表基线 3 部位 ∪ 矩阵里出现的其它部位（追加在后）** | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1020`（`positionColumns`）；基线常量在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:135`（`POSITION_DOMAIN = ['布帘','纱帘','帘头']`） |
| **格** | **三态**：`不做` / `未定价` / `¥x.xx` | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1099`（`cellState`） |
| **行尾** | `分组 · 单位`（各格不一致时逐个列出）+ **必完**标记 + `管理▸` | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2290`（`matrix-meta-*` 单元格） |
| **抽屉** | 逐部位 `做/不做` + 价 + 分组/单位/作用域/必完/停用/删除 + 适用条件 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3078`（抽屉主体）；`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3130`（`drawer-applicable-*`）；`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3245`（`variant-disable-*` / `variant-delete-*`） |

### 2.2 `布料` 被当「第 4 个部位」：**同串两义**

```java
backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:164:    public static final String SALE_FORM_FABRIC = "布料";   // ① 销售形态
backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:166:    public static final String FABRIC_POSITION  = "布料";   // ② 「第 4 个部位」
```

- **路线真正由形态驱动**：`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1415`（`if (SALE_FORM_FABRIC.equals(str(entry.get("saleForm"))))`）⇒ `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1418` `return new RouteKey(FABRIC_POSITION, fabricCraft, "direct")`；
- 同款两义在种子侧：`backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:99`（`FABRIC_POSITION = "布料"`）与 `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:101`（`FABRIC_MAINLINE_STEPS = List.of("配料","打包")`）；
- Python 侧同款：`backend/ai-agent-service/app/production/routing.py:461`（`FABRIC_POSITION = "布料"`）与 `backend/ai-agent-service/app/production/routing.py:463`（`SALE_FORM_FABRIC = "布料"`）。

**代价（实测数字）**：`36 格价目`（见 §2.4）+ 一个「布料列」。
**派生缺陷**：`#4670` 用户实测「**建不出纯布料路线**」——「新建路线」的「适用帘种」取值域 = `positionColumns`（同源带出），矩阵无 `布料` 列 ⇒ 选项里没有它（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1029`）。

### 2.3 `配料` / `打包` 的现状（逐字）

| 项 | `配料` | `打包` |
|---|---|---|
| 分组 / 单位 | `后道` / **米** | `后道` / **套** |
| 工序库行价 | `0`（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:52`） | `0`（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:53`） |
| 适用性 | **仅 `布料`**（`applicable=TRUE`）；`布帘/纱帘/帘头` **逐行显式 FALSE** | **4 部位全适用**（全 `TRUE`） |
| 适用性证据 | `backend/ai-agent-service/app/production/routing.py:666-670`（`("配料","布料",None,True)` + 三条 `False`）；V79 的 36 格：`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:119-122`（1 号租户）+ `backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:165-168`（按租户循环） | `backend/ai-agent-service/app/production/routing.py:671-674`；`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:123-126` + `backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:169-172` |
| 主线归属 | **只在** `FABRIC_MAINLINE_STEPS`（`["配料","打包"]`，`backend/ai-agent-service/app/production/routing.py:465`） | **已在窗帘主线** `ROUTE_MAINLINE_STEPS`（10 道，`backend/ai-agent-service/app/production/routing.py:480`） |
| `scope` | **不是**套级（V79 逐字警告「标成套级会少发工人钱」，`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:202`） | **套级** `scope='set'`（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:204`，口径同 V67） |
| 未定价载体 | 矩阵格 `unit_price=NULL` + `applicable=TRUE` | 同左 |

⚠️ **工序库行价恒为 `0` 是 DDL 的产物，不是「定价 0」**（V79 逐字：`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:47-50`：`production_operations.unit_price` 是 `NOT NULL DEFAULT 0`）。

### 2.4 36 格价目（V79 实测）

`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:81` 逐字：`-- ② 部位价目：补 36 格 ⇒ 84 + 36 = 120 格（30 逻辑工序 × 4 部位）`

36 行的构成（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:91-126`）：

| 组 | 行数 | 内容 |
|---|---|---|
| 既有 28 道逻辑工序 × `布料` | **28** | **逐行显式 `applicable=FALSE`**（明确不做，不是缺行） |
| `配料` × 4 部位 | **4** | 布料 TRUE / 其余三部位 FALSE |
| `打包` × 4 部位 | **4** | 全 TRUE |
| **合计** | **36** | |

⇒ 全部 120 行的真值源镜像 = `backend/ai-agent-service/app/production/routing.py:549`（`_POSITION_PRICE_ROWS`，164 行元组；扣掉注释共 **120** 条数据行）。

### 2.5 布料路线现状

```
positions = ["布料"]            （backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:216；backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:542）
mainline  = ["配料", "打包"]     （backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:217；backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:543）
is_default = FALSE
name       = 布料工序路线        （backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:216；backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:105）
```

### 2.6 套级（`scope='set'`）在界面被按部位渲染成多格

**代码证据（实测）**：读面 `backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java:129`（`operationPositions`）**逐行返回矩阵行**，每行带 `scope`（`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java:227`）；前端**不按 `scope` 聚合列/格**，只按 `position` 铺列（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1061` 与 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1020`）。

**数据证据**：`打包` 有 4 格（§2.3）⇒ 界面渲染 4 个格。
**用户截图形态**：`打包 │ 未定价 │ 未定价 │ 未定价 │ 未定价 │ 后道 · 套  管理▸`（与 V79 的 4 格 + `unit_price=NULL` 逐字吻合）。
⇒ **本设计 §4 要解决的就是它**。

### 2.7 与「计件」相关的既有机制（本设计要保住的）

| 机制 | 载体 | 证据 |
|---|---|---|
| **套级去重**（一樘「布+纱」只落一次，不双付） | `keepsSetLevel` + `SCOPE_SET` | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:506` / `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:515` / `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:267` |
| **报工单价快照**（历史工资不漂移） | `production_work_logs.unit_price` / `factor` | `docs/sql/schema.sql:1086`（表）；`docs/sql/schema.sql:1105-1106`（列 + 注释「报工那一刻从工序实例写入；聚合只读本列」） |
| **工序实例快照** | `processing_position_operations` | `docs/sql/schema.sql:1054`（表）；`docs/sql/schema.sql:1067`（`unit_price` = 实例快照单价） |
| **加工单快照** | `processing_orders.items_snapshot` | `docs/sql/schema.sql:756`；写入点 `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:375` |

---

## 3. 目标模型（用户四条裁定 + 两层）

### 3.1 四条裁定 → 模型结论

| # | 用户裁定（逐字） | 模型结论 |
|---|---|---|
| 1 | 「布料单该用 **裁剪**」 | **`配料` 退场**（软删）；布料主线 `["配料","打包"]` → **`["裁剪","打包"]`** |
| 2 | 「**打包需要计件**」 | `打包` **留在表里**（可报工、可计件），但归**第二层**（不改变产品） |
| 3 | 「`布料` 是销售形态，不是部位」 | **`布料` 降为形态**（`saleForm` 驱动）；**不再出现为界面列** |
| 4 | 「把 UI 改造作为 #4673 的一部分」 | 界面改造 = **本单交付的一部分**（§4） |

### 3.2 两层模型（一屏）

| 层 | 成员 | 判据 | 价来源 | 界面 |
|---|---|---|---|---|
| **工序**（改变产品） | **裁剪 / 车位 / 后整 / 质检** | 按部位区分（`scope='position'`） | **矩阵格价**（按部位不同价，行业标准 `docs/curtain-production-rules.md:27`） | 列 = 布帘 / 纱帘 / 帘头；按车间分组可折叠 |
| **打包发货**（不改变产品） | **打包 / 打卷 / 装袋 / 发货** | 所有形态（`scope='set'` 已成立） | **一列价** | 行 = 4 道；格 = 单价（元/套）+ 必完 |

**两层命名用商家语言**：界面写「**工序**」/「**打包发货**」，**不写**「加工工序 / 交付环节」（那是我们推的术语，用户明确不要）。

### 3.3 `配料` 退场

**依据**：行业里 `配料` 对应「**物料分配**」（收发人员的活），**不在车间三段（裁床/车位/烫工及后整）里** ⇒ 不是工序。
**动作**：`production_operations` 里 `配料` 行 **软删**（`deleted=1`）；矩阵里 `配料 × 4 部位` **软删**；布料主线改成 `["裁剪","打包"]`。
⚠️ 用户 2026-09-20 **00:35 之前**说过「配料是公共工序」，**00:35 的评论已明确更正**（「用户先前说的『配料是公共工序』是**不精确的叫法**，**现更正为 `裁剪`**」）⇒ **以后者为准**。

### 3.4 ⚠️ 关键实测冲突：`矩阵价 ?? 工序库价` 兜底**只在「格不存在」时成立**

用户在设计输入里写「交付环节走**既有**兜底 `矩阵价 ?? 工序库价`」。**实测（读码）结论：该兜底不是「格存在但价为 NULL」时的兜底** —— 两件事必须拆开：

`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1240` 附近的 `buildRoute` 主循环：

| 情形 | 代码路径 | 实测结果 |
|---|---|---|
| 矩阵里**没有**这一格（`applicable == null`） | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1242` | **静默 `continue`**（滤掉该工序）—— **不**回落工序库价 |
| 矩阵里有格且 `applicable=TRUE`、`unit_price=NULL` | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1268` | `step.put("unit_price", price == null ? meta.get("unit_price") : price)` ⇒ **取工序库行价** |
| 矩阵里有格但 `applicable=FALSE` | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1263` | 静默滤掉（既有语义） |

⇒ **准确表述**：
① 「兜底」**确实存在**，但它的触发条件是「**矩阵价那一列的值是 `NULL`**」（格存在、`applicable=TRUE`、价 NULL）；
② 触发时回落的是 **`production_operations.unit_price`**，而该列**恒为 `0`**（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:47-50` 逐字）⇒ **回落 = 0 元**，**不是**「未定价」；
③ 「矩阵里没有这一格」**不是兜底，是滤掉**（`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1242`）。

**⇒ 对设计的影响（必须显式登记）**：
- 「交付环节一列价」**可以**用既有机制实现，但**代价**是「那道工序在该部位变成 0 元」；
- 今天 `打包` 的 4 格**都显式存在**（`applicable=TRUE`、价 NULL）⇒ 走的是「②」⇒ 4 个部位都是「未定价」；
- 若为了「一列价」而删掉其中 3 格 ⇒ 那 3 个部位变成「① 滤掉」⇒ **打包在纱帘/帘头单里直接消失**（少一道活、少一笔计件钱）——**这是不可接受的红线**。

### 3.5 「未定价告警」的现状（实测：**不存在**）

用户验收判据写「未定价时按既有口径走「未定价」告警（不是静默 0 元）」。**实测：后端没有这条告警**：

- `git grep -n "未定价\|unpriced\|UNPRICED" origin/main -- backend/admin-api/src/main/java` ⇒ 命中处**全是注释 / 其它域**（`processing_fee_combinations` 的 `fee_source=unpriced`、`production_route_rules.customer_unit_price` 的 NULL 语义），**没有一处是「工序实例单价为 NULL ⇒ 告警/拦单」**；
- 唯一「看得见」的载体是**前端徽标**：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1106`（`unpricedCount`）→ `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2165`（`未定价 N 项`）；
- 实例化侧 `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1268` 把 NULL 直接写进 `unit_price`，落库到 `processing_position_operations.unit_price`（`docs/sql/schema.sql:1067` 是 `NOT NULL DEFAULT 0`）⇒ **静默 0 元**。

⇒ **如实登记**：验收判据「未定价走告警、不得静默 ¥0.00」**今天不成立**，需要**新落码**（不在本单）。进 §5.5 与 §8 U2。

### 3.6 ⚠️ 待核项：工序库里同时有 `精裁` 与 `裁剪`

**实测（逐字，不猜）**：

| 事实 | 证据 |
|---|---|
| 工序库**同时有** `精裁-布` / `精裁-纱` / `裁剪-布` / `裁剪-纱`（**裁剪组 4 道**） | `backend/ai-agent-service/app/production/routing.py:15-18` |
| 两者**都是独立逻辑工序**（不是同工位别名） | `backend/ai-agent-service/app/production/routing.py:495-498`（`_LOGICAL_NAME_PAIRS`：`("精裁-布","精裁")` / `("裁剪-布","裁剪")`） |
| 两者**各自有独立矩阵行**（各 4 部位） | `backend/ai-agent-service/app/production/routing.py:550-555`（精裁×3 部位 0.4）+ `backend/ai-agent-service/app/production/routing.py:553-555`（裁剪×3 部位 0.4）+ `backend/ai-agent-service/app/production/routing.py:638`（裁剪×布料 `None,False`） |
| 窗帘主线用的是 **`精裁`** | `backend/ai-agent-service/app/production/routing.py:480`（`ROUTE_MAINLINE_STEPS[0] == "精裁"`） |
| `裁剪-布` / `裁剪-纱` 是 **`PENDING_CUSTOMER_CONFIRMATION_OPERATIONS` 成员**（**有意不消费**，待客户确认） | `backend/ai-agent-service/app/production/routing.py:119`；理由逐字在 `backend/ai-agent-service/app/production/routing.py:112-114`：「与 `精裁-布` / `精裁-纱` **同名近义并存**，是否「粗裁 → 精裁」两道**取决于裁床流程** ⇒ **不猜**」 |
| 该问题**已被登记为「企业差异」** | `docs/design/craft-routing-customization.md:20` |

⇒ **两者关系 = 「无法判定」**（**不是我查漏了，是仓库里明确挂着「待客户确认」**）。
**用户已裁定**：布料单用 **`裁剪`**。⇒ 本设计**照此落**（`裁剪 × 布料` 一格价），并把「精裁 / 裁剪 是否两道活」**原样留在待确认**（§8 U3）——
**不发明**「粗裁 → 精裁」的先后关系，**不改**窗帘主线的 `精裁`。

---

## 4. 界面改造（**本单交付的一部分**）

### 4.1 布局

```
工艺项 · 计件单价（给工人）                            未定价 N 项   [搜索]
┌─ 【工序】 ─────────────────────────────────────────────────────────┐
│ ▾ 裁剪（裁床）                                                      │
│     精裁         ¥0.40 │ ¥0.40 │ ¥0.40    裁剪 · 米  必完  管理▸   │
│ ▾ 车位（缝制）                                                      │
│     三边         ¥0.40 │ ¥0.40 │ ¥0.40    车位 · 米  必完  管理▸   │
│     …                                                               │
│ ▸ 后整（烫工及后整）                                                │
│ ▸ 其他                                                              │
├─ 【打包发货】★ 一列价 ─────────────────────────────────────────────┤
│     打包         未定价 /套               后道 · 套  必完  管理▸    │
│     外帘打卷     ¥1.00 /套                后道 · 套  必完  管理▸    │
│     外帘装袋     ¥1.00 /套                后道 · 套  必完  管理▸    │
│     外帘发货     ¥1.00 /套                后道 · 套  必完  管理▸    │
└────────────────────────────────────────────────────────────────────┘
```

**元素**：
1. **两个分区**：「工序」（第一层）/「打包发货」（第二层），各自一个可折叠容器；
2. **第一层按车间分组可折叠**（`裁剪 / 车位 / 后整 / 其他`），分组名取**行尾元数据**的 `group`（已存在，`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2294`）；
3. **列 = 3 部位**（`布帘 / 纱帘 / 帘头`）；
4. **第二层 = 一列价** + 单位（`元/套`）+ 必完；
5. **行尾元数据保留**：`分组 · 单位`（不一致时逐个列出）+ 必完 + `管理▸`；
6. **三态语义不变**：`不做` / `未定价` / `¥x.xx`。

### 4.2 分区判据（**用既有字段，不新造概念**）

| 分区 | 判据 | 依据 |
|---|---|---|
| **打包发货** | `scope === 'set'` | 实测：`打包` 已是 `scope='set'`（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:204`）；`外帘打卷` / `外帘装袋` / `外帘发货` 也是（V67，`docs/design/position-instance-routing-model.md:249`）。读面已带该键（`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java:227`） |
| **工序** | 其余（`scope === 'position'` 或 `scope` 为 `null`） | 前端已有同一份两档归一：`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1179`（`c.scope === 'set' ? 'set' : 'position'`，缺省按 `position` = 安全方向） |

⚠️ **必须显式说清的两点**：
1. **`scope='set'` 恰好等价于「交付环节」**——这是**实测巧合，不是定义**。本设计**不把 `scope` 改名成 `layer`**（那会动 `production_operations` 的闭词表与 V67 契约）。⇒ **登记风险**：将来若有「不改变产品但必须按部位算」的活，它会落错层；反之若有「改变产品但每樘窗一次」的活，也会落错层。**缓解**：分区容器标题下加一句口径说明（「打包发货 = 每樘窗一次的交付活」），并在 §8 U4 登记为**待观察**。
2. **第一层的 4 个成员里，`质检` 今天不在任何主线**（`backend/ai-agent-service/app/production/routing.py:119` 的 `PENDING_CUSTOMER_CONFIRMATION_OPERATIONS` 含 `质检`；`backend/ai-agent-service/app/production/routing.py:480` 的 10 道主线不含它）。
   ⇒ 界面上它会**出现在「后整」组**（它有矩阵行：`backend/ai-agent-service/app/production/routing.py:607-609`），但**没有任何订单会做它**。
   **本设计不替用户决定「质检是否每单必做」**（那是 #4673 里的既有待确认项）⇒ 只**如实呈现**，并在 §8 U5 登记。

### 4.3 `布料` 不再出现为列（**实现口径**）

**问题**：`positionColumns` 由**矩阵数据**带出（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1020`），而迁移后矩阵里**仍必须有** `裁剪 × 布料` 一格（否则 §5.3 的既有布料单补生成会丢工序）⇒ 不处理的话「布料」列**会继续出现**。

**实现口径（本设计选定）**：
- **列取值域收窄到「部位词表」**：`positionColumns = 矩阵里出现的部位 ∩ POSITION_DOMAIN`（基线 3 部位），**追加未知部位**的行为**取消**；
- ⚠️ **不得**把 `布料` 从读面响应里删掉 —— 它是 `variant_operation_id` 的载体，也是 §5.3 的保命格；
- ⚠️ **`orphanOps` 判据不受影响**（它数的是 `variant_operation_id` 是否在**任一**格里被引用，`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1005`）—— 但**必须**在实现时逐条回归（否则会出假「孤儿」提示）；
- ⚠️ **「新建路线」的「适用帘种」取值域 = `positionColumns`**（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1029`）⇒ 收窄后**商家无法再手建 `positions=["布料"]` 的路线**。这是**有意**的：布料路线由种子提供、且**不该**由商家手工造第二条（跨形态勾选会顶掉种子路线，`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1048` 已登记该机制）。
  ⇒ **必须**在「新建路线」对话框里给一句提示：「布料路线已内置，不需手建」。

### 4.4 与既有交互的关系（**逐个核**，别踩坏）

| # | 既有交互 | 现状载体（实测） | 新布局下的处置 | 为什么 |
|---|---|---|---|---|
| 1 | **`管理▸` 抽屉**（#4665 刚加） | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3078`（抽屉）；逐部位 `做/不做` 在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3130`（`drawer-applicable-*`）；价在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3148`（`drawer-price-*`） | **原样保留**（两个分区共用同一个抽屉组件） | 抽屉的判据是 `manageOp`（逻辑工序名），与「哪个分区」无关 |
| 2 | **#4674 死路**（工序无矩阵格 ⇒ 抽屉里**没有删除入口**） | 根因：停用/删除渲染在 `manageVariants.map(...)` **循环体内**（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3245`），空态只给一句话（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3098`） | **本设计从根上避免它**（见下） | —— |
| 3 | **`适用条件`**（#4650 阶段 1） | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:3249`（`operation-conditions` 区块，在抽屉内、**循环体外**） | **原样保留**，两个分区共用 | 条件归属判据 = `production_route_rules.operation === 逻辑工序名`（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1240`），与分区无关 |
| 4 | **矩阵格的 `⇄` / `[做]` / `[不做]`**（#4671 已换成有文字） | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:491`（`ApplicableToggle`，主表格与抽屉**共用**） | **原样保留**；仅列可见性变化 | 三态语义不变（#4665 验收判据） |
| 5 | **孤儿提示 / 接入**（#4614） | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1005`（判据）/ `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2172`（提示）/ `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1553`（接入流程） | **原样保留**；**必须**回归验证（见 §4.3 第 3 条） | 判据是 `variant_operation_id`，与列可见性正交 |
| 6 | **就绪度四步** | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2014`（`process-readiness`） | **原样保留**；#4670 的两条修法见 §6 | —— |
| 7 | **补套行业模板入口** | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2064`（`!operationsReady &&`） | **#4670 修法 A**（§6） | —— |

#### #4674 为什么**从根上**避免（本设计的直接结论）

#4674 的形态是「**表格里有这一行 · 抽屉里空 · 无处可删**」，根因是**两把尺不一致**：
- 表格成行按 **`logical_name`**（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1061`）；
- 抽屉按 **`variant_operation_id`** 去重成 `manageVariants`（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1170`，`variantsOf`）；
- 两者不一致（`variant_operation_id` 为 NULL / 指向别处）⇒ `manageVariants.length === 0` ⇒ 抽屉只剩一句话。

**新布局如何避免**：
1. **第二层（打包发货）的行是独立渲染的** —— 它**不依赖 `manageVariants` 非空**（§4.2 判据是 `scope`，不是矩阵格）。⇒ 即使某道交付工序**一个格都没有**，它在第二层仍有一行 + `管理▸`；
2. **`管理▸` 入口必须移到「行」上、与格无关** —— 这是**本设计对 #4674 的显式要求**（实现单的验收判据）；
3. **抽屉层的「停用 / 删除」必须渲染在 `manageVariants.map(...)` 循环体之外**（与 `适用条件` 区块同级）；
4. **空态必须给出路**（复用 #4614 的孤儿接入流程 + 直接删除），**不许**再写「请核对各部位的适用性配置」。
> ⚠️ **本设计不声称 #4674 已解决** —— 本单是 docs-only。上述 4 条是**交给实现单的约束**；#4674 的关闭条件是它自己的验收判据（含红证）。

### 4.5 第二层「一列价」的**数据落点**（三选一，本设计选定 A）

| 方案 | 做法 | 零改 Java | 零改 DDL | 代价 | 结论 |
|---|---|---|---|---|---|
| **A**（**选定**） | **保留矩阵格**（交付工序 4 格 `applicable=TRUE`、**4 格价一致**），界面**按 `scope='set'` 聚合成一列**；4 格价**不一致**时**显式提示**「各部位不同价（N 处）」并给抽屉入口 | ✅ | ✅ | 改一次价要落 4 格（后端一次性写 4 格即可，前端只发一次） | **本单交付** |
| B | 真正「工序库行价」：`buildRoute` 在「矩阵无格」时回落 `production_operations.unit_price` | ❌（要改 `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1242`） | ✅ | 需先给工序库行价补「未定价 ≠ 0」语义（今天是 `NOT NULL DEFAULT 0`） | **前置单**，见 §8 U6 |
| C | 把交付工序的矩阵格**减到 1 格** | ✅ | ✅ | 其余 3 部位走「格不存在 ⇒ 滤掉」（§3.4）⇒ **交付工序在那些部位消失** | **❌ 不可接受**（红线） |

⇒ **方案 A 的界面聚合规则（必须逐条落）**：
1. 第二层**每道工序一行**（不是每格一行）；
2. 价格单元取值：该工序**所有 `applicable=TRUE` 格的价**——
   - 全部相同 ⇒ 显示该价；
   - 有 `NULL` ⇒ 显示 `未定价`（**≠ ¥0.00**）；
   - 不相同 ⇒ 显示 `各部位不同价（N 处）` + `管理▸` 引导；
3. **单位取行尾元数据的 `unit`**（已存在）；
4. **必完**照旧（读 `is_must_finish`）。

---

## 5. 迁移（**重点**）

### 5.1 迁移号（**实测取当前最大号**）

```bash
git ls-tree --name-only origin/main backend/admin-api/src/main/resources/db/migration/ | grep -o 'V[0-9]*' | sort -t V -k2 -n | tail -3
# → V85 / V86 / V87
git ls-tree --name-only origin/main backend/admin-api/src/main/resources/db/migration/ | grep -c "V88"
# → 0
```

⇒ **当前最大号 = `V87`**（`V87__retire_factor_route_rules.sql`），**本次迁移 = `V88`**（新文件，例 `V88__retire_material_prep_and_fabric_position.sql`）。

⚠️ **已发布迁移不可改**（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:12-15` 逐字：`MigrationRunner` 按**文件名**记台账，已应用的文件整份跳过 ⇒ 改旧迁移只对全新库生效，存量环境永远拿不到 = 「CI 绿、功能静默缺失」，issue #4235）。
⚠️ 另有**指纹守卫**：`tests/unit_ci_workflows/migration_fingerprints.json` 对每个已发布迁移钉 `sha256`（实测 85 条，含 V79）⇒ **改 V79 = 红**。必须**新增 V88**。

### 5.2 V88 改什么（逐条）

| # | 动作 | 目标 | 幂等要求 |
|---|---|---|---|
| ① | `配料` 工序行 **软删** | `production_operations`（`name='配料' AND deleted=0`） | `UPDATE … WHERE …` 天然幂等 |
| ② | `配料 × 4 部位` 矩阵行 **软删** | `production_operation_positions`（`logical_name='配料'`） | 同上 |
| ③ | **布料主线改** `["配料","打包"]` → `["裁剪","打包"]` | `production_route_templates.mainline`（`name='布料工序路线'`，**按租户**） | 手术式替换（同 V79 ⑥ 的 `jsonb` 形态）；`NOT (mainline @> '["裁剪"]')` 判重 |
| ④ | **`裁剪 × 布料` 格**：`applicable` **TRUE** | `production_operation_positions`（V79 已种该行：`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:92` / `backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:141`，`applicable=FALSE`） | `UPDATE … WHERE logical_name='裁剪' AND position='布料'` |
| ⑤ | **其余 35 格软删**（§2.4 的 36 − 1） | `production_operation_positions`（`position='布料' AND logical_name <> '裁剪'`） | 同上 |
| ⑥ | **按租户循环**（存量租户） | ①②③④⑤ 全部要覆盖**每个活跃租户**（`FROM tenants WHERE deleted=0`） | 与 V79 同款（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:56-68`）；只种 1 号租户 ⇒ 非 1 号租户全量 422（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:17-21` 逐字警告） |
| ⑦ | **不动** `打包` 的 4 格 + `scope='set'` | —— | 见 §5.4 红线 |

### 5.3 🔴 为什么 `裁剪 × 布料` 这一格**必须留**（不是可选项）

**实测证据链**（这是本设计最重要的一条）：

1. `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1415` ⇒ 布料单的 `RouteKey.curtainType()` = `"布料"`（`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1418`）；
2. `resolveRoute` 用 `key.curtainType()` 去 `routeTemplateFor` 选模板 ⇒ 命中 `布料工序路线`（`backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java:283`：`positions.contains(position)`）；
3. `buildRoute` 的**适用性矩阵**按 `position`（= `"布料"`）建键（`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1181-1187`）；
4. 主线里 `裁剪` 若在 `position="布料"` 下**查不到格** ⇒ 走 `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1242` 的 `continue` ⇒ **被静默滤掉**（`裁剪` 是逻辑名，`normalizeOperationName("裁剪") == "裁剪"` ⇒ **不进 `missing_operations`**，**不报错**）；
5. ⇒ 结果：**布料单只剩 `打包` 一道**（少一道活、少一笔计件钱、**没有任何报错**）。

⚠️ **并且这条路径对「存量单」是活的**（推翻「只影响新单」的直觉）：

- `POST /api/admin/production/orders/{orderId}/instantiate`（`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:106`）的 **body 为空时按订单重新派生**：
  `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:117`（`withDerivedPositions`）⇒ `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:123` `processingOrderService.derivePositionPayload(...)`；
- 前端入口 = 加工单生产页的「**补生成工序**」按钮（`frontend/admin-web/src/app/(dashboard)/processing-orders/[id]/production/page.tsx:318`），发的是**空 body**（`frontend/admin-web/src/lib/api.ts:630`）；
- ⇒ **存量布料加工单**若「工序实例与 qr_token 双空」（存量单补工序路径），**今天仍会走这条派生链**（用的是**当前**的路线模板与矩阵）。

**⇒ 结论（红线）**：
- ① **`裁剪 × 布料` 格必须保留**（`applicable=TRUE`），否则存量布料单补生成会**静默少一道工序**；
- ② **`布料工序路线` 模板必须保留**（`positions=["布料"]`），否则 `routeTemplateFor` 返回 `null` ⇒ **T2 回落默认路线**（窗帘 10 道）⇒ 布料单会**多出** 三边/熨烫/定型… 一堆窗帘工序（更糟）；
- ③ 因此「`布料` 不再作为部位」**只能**是**界面口径**（§4.3），**不是**数据/路线口径的删除。

### 5.4 存量加工单 / 报工快照一字不动（红线，给论证）

**论证（实测三层快照 + 一层幂等）**：

| 层 | 表 / 载体 | 为什么不动 |
|---|---|---|
| **加工单快照** | `processing_orders.items_snapshot`（`docs/sql/schema.sql:756`；写入点 `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:375`） | 生成时**固化**；V88 **不写**该列 |
| **工序实例快照** | `processing_position_operations`（`docs/sql/schema.sql:1054`） | 实例行在**生成/实例化时**落库；V88 **不写**该表**已存在**的行（只软删 `position='布料'` 的**矩阵**行，那是 `production_operation_positions`，**不是** `processing_position_operations`）——⚠️ **两张表名字极像，迁移里必须写全名，不许简写** |
| **报工快照** | `production_work_logs.unit_price` / `factor`（`docs/sql/schema.sql:1105-1106`，V61） | 逐字注释：「报工那一刻从工序实例写入；聚合只读本列 ⇒ 重新实例化软删旧实例不影响历史报工的钱」 |
| **幂等保证** | `instantiate` 的签名比较（`backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java:128`） | 配置与已有实例**一致** ⇒ 一行都不碰（不重插、不清零 `done_qty`） |

⇒ **「只影响新单」的准确边界（必须写清，别扩大）**：
- ✅ **已实例化的存量单**：一字不动（签名一致 ⇒ 幂等空操作）；
- ⚠️ **未实例化的存量单**（工序实例与 qr_token 双空）：**会**按**当前**配置派生 ⇒ 这正是 §5.3 要保 `裁剪 × 布料` 格的原因；
- ⚠️ **`配料` 从主线移除后**，存量布料单补生成会**少**一道 `配料`（**有意**，因为它是用户裁定退场的工序）——**如实登记**为**已知行为变化**（不是 bug）。

### 5.5 未定价的处置（**本单不解决，登记**）

- 现状：`打包` 4 格 + `裁剪 × 布料` 格的 `unit_price` 都是 `NULL` ⇒ 实例化后 `processing_position_operations.unit_price = 0`（§3.5）；
- 商家侧**唯一**可见提示 = 前端徽标 `未定价 N 项`（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2165`）；
- ⇒ **本设计登记**：验收判据「未定价走告警、不得静默 ¥0.00」需要**独立落码单**（进 §8 U2）；
- ⚠️ **不得**用「给这些格填 0.00」来消掉徽标（那会把「未定价」变成「真 0 元」，工人白干）。

### 5.6 回滚

**回滚 = 新迁移 `V89__rollback_…`（不删 V88）** —— 已发布迁移不可改（§5.1）。

| # | 回滚动作 |
|---|---|
| ① | `配料` 工序行 `deleted=0` 复原（按 id 前缀 `op-v79-%` 认领，**不按名字** —— 名字会随商家改名漂移，V79 的 provenance 用 id 前缀正是这个理由：`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:172-176`） |
| ② | `配料 × 4 部位` 矩阵行 `deleted=0` 复原（按 id 前缀 `opp-v79-%`，V79 回滚 SQL 同款：`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:30`） |
| ③ | 布料主线改回 `["配料","打包"]` |
| ④ | `裁剪 × 布料` 格 `applicable` 改回 `FALSE` |
| ⑤ | 其余 35 格 `deleted=0` 复原 |

⚠️ **回滚不能复原的东西（如实登记）**：V88 生效期间**新建**的布料单已经按 `["裁剪","打包"]` 实例化 ⇒ 回滚后这些单的实例**不会**自动变回 `配料`（实例是快照）。回滚的语义是「**让新单回到旧行为**」，**不是**「让历史单回到旧行为」。

### 5.7 停止条件（**出现什么立刻停并回滚**）

| # | 停止条件 | 核验方式 |
|---|---|---|
| S1 | **任一租户出现「布料单实例化工序数 ≠ 2」** | 实例化后查 `processing_position_operations`：`SELECT processing_order_id, count(*) FROM processing_position_operations WHERE deleted=0 AND processing_order_id IN (…布料单…) GROUP BY 1` ⇒ 期望 **2**（裁剪 + 打包） |
| S2 | **任一租户布料单实例化 422** | 观察 `ERR_ROUTING_NOT_FOUND` / `ERR_OPERATION_NOT_FOUND` 日志（`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1104` / `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1125`） |
| S3 | **`裁剪` 在任何非布料单里消失** | 窗帘单实例化后核对工序清单含 `裁剪` 或 `精裁`（**两者都算合格**，见 §3.6） |
| S4 | **`打包` 在某部位单里消失** | 一樘「布+纱」单 ⇒ `打包` 应**恰好 1 行**（套级去重，`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:506`） |
| S5 | **报工金额变化** | 对比 V88 前后同一期间的计件报表（`GET /api/admin/production/piecework/summary`）；**任何历史期间金额变化 = 立刻停** |
| S6 | **`配料` 出现在任何新单的实例里** | `SELECT DISTINCT operation_name FROM processing_position_operations WHERE deleted=0 AND created_at > <V88 时间>` ⇒ 不得含 `配料` |

### 5.8 迁移影响面（**除 V88 之外还要改的东西**，实测）

| 载体 | 现状 | 影响 |
|---|---|---|
| `tests/unit_ci_workflows/test_fabric_route_seed.py` | 判据 4 钉死 `mainline=("配料","打包")`（`tests/unit_ci_workflows/test_fabric_route_seed.py:50`） | **必须**同步改判（`配料` → `裁剪`）；判据 6 的「每租户两道工序行」也要改 |
| `tests/unit_ci_workflows/test_production_catalog_seed.py` | 钉「`routing.py` 常量 ≡ V71/V79 字面量种子」 | **必须**同步（种子字面量变了） |
| `tests/unit_ci_workflows/migration_fingerprints.json` | 85 条 `sha256` | **新增 V88 一条**（V79 的指纹**不动**） |
| `backend/admin-api/src/main/resources/production-templates/curtain/seed.json` | 描述里逐字写「37 道工序（含 #4529 的 配料/打包）」 | **必须**同步（`配料` 退场后是 36 道） |
| `backend/admin-api/src/main/resources/db/migration/V79__….sql` | —— | **一个字不动**（§5.1 红线） |

⚠️ **本单（docs-only）不改上述任何文件** —— 它们是**实现单**的改动面，登记在此以免漏。

---

## 6. 种子自愈（#4670 的两条）

**#4670 现状**（该单已并入 #4673，实测复核如下）：

| # | 病根 | 实测证据 | 本设计的取舍 |
|---|---|---|---|
| ① | 「补套行业模板」入口**只在工序库为空时显示** ⇒ 种子缺失（工序库非空但缺布料路线）**没有自愈路径** | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2064`（`{!operationsReady && (`）；`operationsReady` 定义在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1228`（`(catalog?.total ?? 0) > 0`） | **纳入**（修法 A，见下）—— 与 §4 的界面改造**同一批**（都在工艺项页） |
| ② | **就绪度② 只数条数**、不校验两条基础路线是否齐 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2035`（`label={\`工艺路线 ${routeList.length} 条\`}`）；`routingsReady` 在 `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:1233`（`routeList.length > 0 && emptyShells.length === 0`） | **纳入**（修法 B）—— 与 ① 同批 |

### 修法 A：补套入口改成「**缺失即显示**」（幂等）

- 显示条件从 `!operationsReady` 改成「**存在可补齐的缺失项**」（至少覆盖：**缺基础路线** / 缺基线工序 / 缺部位价目行）；
- 文案说清**将补齐什么**，并保留「已存在的条目自动跳过」的既有幂等语义；
- ⚠️ **不得**因为「工序库非空」就整体隐藏 —— 那正是 #4670 的 bug。

### 修法 B：就绪度② 改判

- 从「数条数」改成「**两条基础路线是否齐**」（按**名字**判，与种子逐字一致：`窗帘工序路线（默认）` + `布料工序路线`）；
- 缺哪条**点名**，并给**指向 A 的补齐入口**的引导；
- ⚠️ **不许**把「商家自己删了某条路线」当成错误状态（商家可删）；文案应是「基础路线缺失，可一键补齐」。

### ⚠️ 与 §5 的**联动**（本设计新增的一条）

`布料工序路线` 在 V88 后**仍然存在**（只改主线）⇒ 就绪度② 的「两条基础路线」判据**不变**。
**但**：§4.3 收窄了「适用帘种」取值域（商家无法再手建布料路线）⇒ 若商家删了它，**只能**靠修法 A 补回。⇒ **修法 A 是修法 B 的前置**（B 的引导指向 A）。

---

## 7. 与既有设计的**冲突点**（照实写，别迁就）

### 7.1 vs `docs/design/operation-slot-model.md`（槽位模型）

| # | 该设计的立场 | 本设计的立场 | 谁为准 / 为什么 |
|---|---|---|---|
| C1 | 槽位是**主线内部**的**顺序**模型（`docs/design/operation-slot-model.md:389-391`：边缘槽 / 打褶槽 / 挂钩槽 / 蒸烫槽…），用于**派生锚点** | 本设计的两层是**工艺项表格的分区**（按 `scope`），与「顺序」正交 | **不冲突** —— 两个问题域不同（一个是「工序排第几」，一个是「这道工序属哪个区」）。**但**：`docs/design/ai-craft-config.md:223-224` 要求「商家可见（人话）一律用**槽位**」⇒ 与用户裁定「界面用行业术语、不许用我们发明的词」**冲突**（见 C3） |
| C2 | `docs/design/operation-slot-model.md:881` 计划**新增槽位定义表** `production_operation_slots` | 本设计**不引入**任何槽位表；分区判据用**既有** `scope` | **本设计不依赖它**（#4650 阶段 4 的产物）。若阶段 4 落地后槽位成为真值源，**本设计的 §4.2 分区判据不受影响**（`scope` 与槽位是两把尺） |
| C3 | `docs/design/ai-craft-config.md:208` 逐字：「术语口径：**商家可见与 AI 解释**一律按槽位口径表述；「锚点」只作**实现列名**保留」；`docs/design/ai-craft-config.md:223` 把「槽位」列为**商家可见（人话）** | 用户 2026-09-20 裁定（#4673 评论）：「**界面第一层用行业术语**（裁剪/车位/后整/质检），**不许**用"槽位"这类我们发明的词」 | **用户裁定为准**。⇒ `docs/design/ai-craft-config.md` 的 §2.5 需要**回改**（把「商家可见一律用槽位」收窄为「**仅主线顺序解释**可用槽位；**工艺项分区/命名**用行业术语」）。**本单不改它**（docs-only 单只产出一份文件），**登记为实现单/后续单的动作** |
| C4 | `docs/design/operation-slot-model.md:182` 逐字：「槽位的**语义已被冻结为「打褶那一道」**」（依据 `backend/ai-agent-service/app/production/routing.py:470`） | 本设计 §1.3 **采纳**这条：全仓只有「打褶槽」有真值源逐字依据；其余槽名是该设计的推导 | **一致**（本设计不引用任何槽名做界面分区） |

### 7.2 vs `docs/design/ai-craft-config.md`（AI 层）

| # | 该设计的内容 | 与本设计的关系 | 谁为准 |
|---|---|---|---|
| D1 | `docs/design/ai-craft-config.md:539-540` 计划给 `production_route_rules` 加 `slot` / `slot_holder` 列（**阶段 4**） | 本设计**不涉及**规则表结构 | **不冲突**（阶段 4 的承载收敛是独立单） |
| D2 | `docs/design/ai-craft-config.md:838` U9 登记：「槽位模型的确切定义…**待 #4653 合入后对齐**」 | 该设计的「商家可见用槽位」口径**以 #4653 为准**（它自己逐字写了） | ⇒ **本设计对 C3 的裁定与 D2 同向**：口径待 #4653 定稿后再统一；本设计只**登记冲突**、**不改它** |
| D3 | `docs/design/ai-craft-config.md:750` A2 判据「输入『韩褶的时候加一道上车布』⇒ `slot == "打褶槽"`」 | 本设计**不影响**该判据（规则/条件不分区） | **不冲突** |

### 7.3 与 `docs/design/craft-routing-customization.md` 的**依赖**

`docs/design/craft-routing-customization.md:20` 把「`裁剪-布/裁剪-纱` 与 `精裁-布/精裁-纱` 是一道还是两道」登记为「**设备差异 → 企业差异**」。
⇒ 本设计 §3.6 **依赖**该判定；用户已裁定布料单用 `裁剪`，**但两者关系仍未定**（§8 U3）。

### 7.4 与 `docs/design/craft-calc-and-fabric-routing.md` 的**冲突**（**必须登记**）

`docs/design/craft-calc-and-fabric-routing.md:179` 逐字钉死：

> | 10 | **布料单 = `配料` + `打包` 两道**；成品帘单主线 **9 + 打包 = 10 道**，且 `打包` 只出现 1 行（套级，不按部位展开） | 多/少/重复 ⇒ 红 |

⇒ V88 生效后**这条判据会变红**（布料单变成 `裁剪` + `打包`）。
⇒ **该文档需要回改**（`配料` → `裁剪`），**本单不改**（docs-only，只产出一份文件）⇒ **登记为实现单的动作**。

---

## 8. 不做什么 / 无法判定项 / 与假设不符的事实

### 8.1 本单（docs-only）**不做**

- ❌ 不改任何生产代码（Java / TypeScript / Python）
- ❌ 不碰 ai-agent（`backend/ai-agent-service/**`）
- ❌ 不写任何迁移（V88 只是**设计**）
- ❌ 不改 `.github/workflows/**` 与 `.agent-presets/**`
- ❌ 不改 `docs/design/operation-slot-model.md` / `docs/design/ai-craft-config.md` / `docs/design/craft-calc-and-fabric-routing.md`（§7 登记的冲突**留给实现单**）
- ❌ 不跑真实 LLM 评测

### 8.2 无法判定项（**不是我查漏了**）

| # | 项 | 为什么无法判定 |
|---|---|---|
| **U1** | 《成品窗帘生产流程及工作规范》的**逐字原文** | 该文档**不在仓库内**（实测 `git ls-tree -r --name-only origin/main \| grep -i "生产流程\|工作规范\|成品窗帘"` ⇒ 零命中）。§1.2 的对照表引自用户在 #4673 评论里给出的引文 ⇒ **无法在仓库内逐字复核**。**建议**：实现单把该文档（或引文摘录）**入库**，让术语有可复核的真值源 |
| **U2** | 「未定价 ⇒ 告警、不得静默 ¥0.00」的**既有机制** | **实测不存在**（§3.5）：后端零命中，唯一载体是前端徽标。⇒ 该验收判据需要**新落码**，不在本单 |
| **U3** | `精裁` 与 `裁剪` 是**同工位两种叫法**还是**两道活**（粗裁 → 精裁） | 仓库**明确挂着待确认**：`backend/ai-agent-service/app/production/routing.py:119`（`PENDING_CUSTOMER_CONFIRMATION_OPERATIONS`）+ `backend/ai-agent-service/app/production/routing.py:112-114` 逐字「**不猜**」+ `docs/design/craft-routing-customization.md:20`（登记为「企业差异」）。**用户只裁定了布料单用 `裁剪`，没裁定两者关系** |
| **U4** | `scope='set'` 是否**长期**等价于「交付环节」 | 这是**实测巧合**（§4.2）：今天的 4 道交付工序恰好都是 `scope='set'`。**没有**任何真值源说「不改变产品 ⇔ 套级」。⇒ 需**待观察**（出现反例时分区判据要换） |
| **U5** | `质检` 是否**每单必做**、插在哪 | 真值源只说定型「联动…质检/包装」，**没说**它必做（`backend/ai-agent-service/app/production/routing.py:114-116` 逐字）。⇒ 本设计把它**列在「后整」组**（它有矩阵行），但**不**声称任何订单会做它 |
| **U6** | 「交付环节走**工序库行价**」能否落地 | **实测：不能直接用**（§3.4）—— 「格不存在 ⇒ 滤掉」（不回落）、「格存在但价 NULL ⇒ 回落工序库价 = 0」。⇒ 要真做「工序库行价」，需先给 `production_operations.unit_price` 补「未定价 ≠ 0」语义（今天是 `NOT NULL DEFAULT 0`，`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:47-50`）⇒ **前置单** |
| **U7** | 布料单的**加工工序是否需要按部位分价** | 用户裁定「布料单用 `裁剪`」，但**没说**卖布是否只有一种价。本设计按**一格价**（`裁剪 × 布料`）落 —— 若将来要按米数/幅宽分价，需另开单 |
| **U8** | 「打卷 / 装袋 / 发货」对**布料单**是否适用 | 实测：这三道在矩阵里对 `布料` **显式 FALSE**（V79 的 28 格之一）⇒ 布料单**不做**它们。用户裁定「打包需要计件」**只点名 `打包`**，**没提**这三道对布料的适用性 ⇒ **保持现状**（不改），登记为待确认 |

### 8.3 与假设不符的事实（**实测推翻转述**）

| # | 转述 / 假设 | 实测 | 影响 |
|---|---|---|---|
| **F1** | 「交付环节走**既有**兜底 `矩阵价 ?? 工序库价`」 | 兜底**存在但触发条件不同**：只在「格存在 + `applicable=TRUE` + 价 NULL」时回落；「**格不存在 ⇒ 静默滤掉**」不回落（`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1242`） | ⇒ §3.4：**不能**用「删格」实现一列价（会丢工序） |
| **F2** | 「未定价时按既有口径走「未定价」告警」 | 后端**零**告警；唯一载体 = 前端徽标（`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx:2165`）；实例化后落库 `0` | ⇒ §3.5：验收判据需要新落码 |
| **F3** | 「**只影响新单**」（直觉：快照保护存量单） | **对已实例化的存量单成立**；但**未实例化的存量单**（「补生成工序」路径）**会**按当前配置重新派生（`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:117` + `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:123`） | ⇒ §5.3：`裁剪 × 布料` 格**必须留**；§5.4 给出准确边界 |
| **F4** | 「工序库行价可以当兜底价」 | `production_operations.unit_price` 是 `NOT NULL DEFAULT 0`，种子里恒为 `0`（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:47-50`）⇒ 回落 = **0 元**，不是「未定价」 | ⇒ §3.4 ③ + U6 |
| **F5** | 「`配料` 是公共工序（用户早期口径）」 | 用户 **00:35 的评论已明确更正**为 `裁剪`（「先前说的『配料是公共工序』是**不精确的叫法**」） | ⇒ 以 `裁剪` 为准（§3.3） |
| **F6** | 「`布料` 降为形态 ⇒ 36 格价目**全部**退场」 | 若**全部**退场，存量布料单补生成会**静默丢 `裁剪`**（§5.3）⇒ 必须**留 1 格**（`裁剪 × 布料`），实际退场 **35 格** | ⇒ §5.2 ⑤ |
| **F7** | 「`质检` 是「工序」层成员」（用户设计输入里的两层表） | `质检` **不在任何主线**（`backend/ai-agent-service/app/production/routing.py:480` 的 10 道不含它），且被登记为 `PENDING_CUSTOMER_CONFIRMATION_OPERATIONS` | ⇒ §4.2 第 2 条 + U5：界面呈现，但**不声称**它会执行 |
| **F8** | 「改 V79 即可」 | V79 是**已发布迁移**（不可改）+ 有 `sha256` 指纹守卫（`tests/unit_ci_workflows/migration_fingerprints.json`，85 条含 V79） | ⇒ 必须**新增 V88**（§5.1） |

---

## 附录 A：所有实测命令与数字

> 全部命令在**只读**主仓库（`/Users/guangzhen.zk/ai native/migao`）上执行，读的是 `origin/main`。
> 基准：`origin/main` @ **`06f0126a5`**（`git rev-parse origin/main`）。

### A.1 真值源与术语

```bash
# 工序分组 = 车间工位分组（不是阶段）
git show origin/main:docs/curtain-production-rules.md | sed -n '24,30p'
# → :26 【标】工序分组：裁剪 / 车位 / 后道 / 其他（不是按阶段，是车间工位分组）
# → :27 【标】工序按部位分设：同一道工序在布/纱/帘头上单价各自不同

# 槽位语义冻结处（全仓唯一有逐字依据的槽）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '468,472p'
# → :470 （槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入）
# → :471 ROUTE_MAINLINE: List[str] = ["精裁", "三边", "⟪工艺槽位⟫", "熨烫", "定型", "复烫",

# 行业文档是否在仓库内
git ls-tree -r --name-only origin/main | grep -i "生产流程\|工作规范\|成品窗帘"
# → （零命中）⇒ 该文档在仓库外（U1）
```

### A.2 同串两义（`布料`）

```bash
git grep -n "SALE_FORM_FABRIC\|FABRIC_POSITION" origin/main -- '*.java'
# → backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:164  public static final String SALE_FORM_FABRIC = "布料";
# → backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:166  public static final String FABRIC_POSITION  = "布料";
# → backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1415 if (SALE_FORM_FABRIC.equals(str(entry.get("saleForm")))) {
# → backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1418     return new RouteKey(FABRIC_POSITION, fabricCraft, "direct");
# → backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:99  FABRIC_POSITION = "布料"
# → backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:101 FABRIC_MAINLINE_STEPS = List.of("配料", "打包")
# → backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:542 .positions(List.of(FABRIC_POSITION))
```

### A.3 36 格价目 / 120 格

```bash
git show origin/main:backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql \
  | grep -n "36 格\|120 格"
# → :81  -- ② 部位价目：补 36 格 ⇒ 84 + 36 = 120 格（30 逻辑工序 × 4 部位）
# → :21  -- ⇒ 本迁移必须为每个活跃租户补：两道工序 + 36 格价目 + 布料路线 + 窗帘主线重建

# 36 行的逐行字面量（1 号租户）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql \
  | sed -n '91,126p' | grep -c "^  ('opp-v79-"
# → 36

# 真值源镜像（120 条数据行）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '549,678p' | grep -c '^\s*("'
# → 120
```

### A.4 配料 / 打包 的适用性（逐字）

```bash
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '664,678p'
# → ("配料", "布料", None, True),
# → ("配料", "布帘", None, False), ("配料", "纱帘", None, False), ("配料", "帘头", None, False),
# → ("打包", "布帘", None, True), ("打包", "纱帘", None, True),
# → ("打包", "帘头", None, True), ("打包", "布料", None, True),

# scope='set' 只给了打包
git show origin/main:backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql \
  | sed -n '198,206p'
# → :202 ⚠️ `配料` 不是套级（它按米计、按部位算料）—— 标成套级会少发工人钱。
# → :204 UPDATE production_operations SET scope = 'set' WHERE name IN ('打包');

# 工序库行价 = NOT NULL DEFAULT 0（不是「未定价」）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql \
  | sed -n '47,53p'
# → :47 ⚠️ `unit_price` 落 0 不是「定价 0」：production_operations.unit_price 是
# → :48    `NOT NULL DEFAULT 0`（V49 DDL）⇒ 工序库行只能落 0。
```

### A.5 兜底 / 滤掉的真实语义（F1）

```bash
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java \
  | sed -n '1181,1188p'     # 适用性/价按键建表（position 维）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java \
  | sed -n '1240,1272p'
# → :1242 if (applicable == null) { … continue; }          ← 格不存在 ⇒ 滤掉（不回落）
# → :1263 if (!applicable) { continue; }                   ← 明确不做 ⇒ 滤掉
# → :1268 step.put("unit_price", price == null ? meta.get("unit_price") : price);  ← 价 NULL ⇒ 回落工序库行价
```

### A.6 存量单的活路径（F3）

```bash
# 空 body ⇒ 按订单重新派生
git grep -n "withDerivedPositions\|derivePositionPayload" origin/main -- backend/admin-api/src/main/java
# → backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:110 orderId, withDerivedPositions(orderId, body), …
# → backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:117 private Map<String, Object> withDerivedPositions(…)
# → backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java:123 processingOrderService.derivePositionPayload(orderId, …)

# 前端入口 = 「补生成工序」（空 body）
git show origin/main:frontend/admin-web/src/lib/api.ts | sed -n '629,634p'
# → instantiate: (orderId: string) => request.post(…/instantiate, {})

# 幂等签名（配置一致 ⇒ 一行不碰）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java | sed -n '126,140p'
```

### A.7 界面（实测符号与行号）

```bash
F='frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx'
git show "origin/main:$F" | wc -l                    # → 3917
git show "origin/main:$F" | grep -n "POSITION_DOMAIN\|positionColumns\|matrixRows\|unpricedCount\|operationsReady\|readiness-step-routings\|seed-templates\|operation-conditions\|variant-disable-\|matrix-manage-"
# → :135   const POSITION_DOMAIN = ['布帘', '纱帘', '帘头']
# → :1005  const orphanOps = useMemo(…)
# → :1020  const positionColumns = useMemo(…)
# → :1029  「新建路线」的部位勾选项 = positionColumns
# → :1061  const matrixRows = useMemo(…)
# → :1099  const cellState = …
# → :1106  const unpricedCount = useMemo(…)
# → :1228  const operationsReady = (catalog?.total ?? 0) > 0
# → :1233  const routingsReady = routeList.length > 0 && emptyShells.length === 0
# → :1553  const openOrphanAttach = () => {
# → :2014  data-testid="process-readiness"
# → :2035  label={`工艺路线 ${routeList.length} 条`}
# → :2064  {!operationsReady && (   ← 补套入口只在工序库为空时显示（#4670 ①）
# → :2165  data-testid="matrix-unpriced-count"
# → :2290  data-testid={`matrix-meta-${row.operation}`}
# → :2310  data-testid={`matrix-manage-${row.operation}`}
# → :3078  抽屉「在各部位的设置」
# → :3130  data-testid={`drawer-applicable-${manageOp}-${position}`}
# → :3245  data-testid={`variant-disable-${v.id}`}   ← 在 manageVariants.map 循环体内（#4674 根因）
# → :3249  data-testid="operation-conditions"        ← 在循环体外
```

### A.8 迁移号 / 指纹

```bash
git ls-tree --name-only origin/main backend/admin-api/src/main/resources/db/migration/ \
  | grep -o 'V[0-9]*' | sort -t V -k2 -n | tail -3
# → V85 / V86 / V87          ⇒ 本次 = V88

git ls-tree --name-only origin/main backend/admin-api/src/main/resources/db/migration/ | wc -l
# → 85（V1…V87，中间有跳号）

git show origin/main:tests/unit_ci_workflows/migration_fingerprints.json \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['migrations']))"
# → 85（每个已发布迁移一条 sha256 ⇒ 改 V79 = 红）
```

### A.9 既有守卫（V88 的改动面）

```bash
git show origin/main:tests/unit_ci_workflows/test_fabric_route_seed.py | grep -n "FABRIC_MAINLINE\|DEFAULT_TEMPLATE_NAME\|FABRIC_TEMPLATE_NAME"
# → :48 FABRIC_MAINLINE = ("配料", "打包")
# → :49 CURTAIN_MAINLINE = ("精裁", "三边", "熨烫", "定型", "复烫", "车被",
#                          "外帘打卷", "打包", "外帘装袋", "外帘发货")
# → :46 DEFAULT_TEMPLATE_NAME = "窗帘工序路线（默认）"
# → :47 FABRIC_TEMPLATE_NAME  = "布料工序路线"
```

### A.10 既有设计的冲突点（§7）

```bash
git show origin/main:docs/design/craft-calc-and-fabric-routing.md | sed -n '179p'
# → | 10 | **布料单 = `配料` + `打包` 两道**；… | 多/少/重复 ⇒ 红 |   ← V88 后这条会变红（§7.4）

git show origin/main:docs/design/ai-craft-config.md | sed -n '208p'
# → ### 2.5 术语口径：**商家可见与 AI 解释**一律按槽位口径表述；「锚点」只作**实现列名**保留

git show origin/main:docs/design/operation-slot-model.md | sed -n '182p'
# → | 槽位的**语义已被冻结为「打褶那一道」** | `:470` 逐字「槽位 = 打褶那一道」…
```

### A.11 本单自查

```bash
# 工作区：/Users/guangzhen.zk/ai native/migao-wt/public-ops-model-4673
python3 .github/case_trust_gate.py --base origin/main
# → ✅ 通过（exit 0）
```

---

## 附录 B：交实现单的**验收判据**（本设计对落码单的约束，**含红证**）

> 每条都写**红证**（改前会红的形态）——否则是空断言（`migao-acceptance` 口径）。

| # | 判据 | 红证（改前形态） |
|---|---|---|
| B1 | 工艺项页**分两区**：「工序」（列 = 布帘/纱帘/帘头）+「打包发货」（一列价） | 改前：一张平铺表、4 列（含「布料」） |
| B2 | 「工序」区**按车间分组可折叠**（裁剪 / 车位 / 后整 / 其他，**行业术语**） | 改前：无分组、无折叠；且**不得**出现「槽位」字样 |
| B3 | 「打包发货」区：`打包 / 外帘打卷 / 外帘装袋 / 外帘发货` **各一行、一列价**（不是 4 格） | 改前：`打包 │ 未定价 │ 未定价 │ 未定价 │ 未定价`（用户截图形态） |
| B4 | `布料` **不出现在列头** | 改前：第 4 列 = `布料` |
| B5 | 三态语义**不变**（`不做` / `未定价` / `¥x.xx`），且 `未定价 ≠ ¥0.00` | 既有断言 `frontend/admin-web/tests/unit/pages/production-routings.test.tsx:1097`（⑰-④）**不得放宽** |
| B6 | `管理▸` **行上**恒有（与矩阵格无关）；抽屉层「停用 / 删除」在 `manageVariants` 循环体**外** | 改前：`manageVariants.length === 0` ⇒ 抽屉只有一句话（#4674 形态） |
| B7 | 第二层「一列价」在**各部位价不一致**时**显式提示**（不静默取第一个） | 改前：无第二层概念 |
| B8 | V88 后**新布料单**实例化 = **2 道**（`裁剪` + `打包`） | 改前：`配料` + `打包` |
| B9 | V88 后**存量已实例化**布料单的 `processing_position_operations` **一字不动**（行数/`unit_price`/`done_qty` 全等） | 核验：V88 前后 `SELECT … FROM processing_position_operations WHERE deleted=0` 逐行 diff |
| B10 | V88 后**存量未实例化**布料单「补生成工序」**不丢** `裁剪` | 红证：若删掉 `裁剪 × 布料` 格 ⇒ 只剩 `打包` 1 道（§5.3） |
| B11 | `打包` 在**任一**部位单里**不消失**（一樘「布+纱」⇒ 恰好 1 行，套级去重） | 红证：删掉 `打包` 的非布帘格 ⇒ 纱帘/帘头单丢工序（§3.4） |
| B12 | `#4670` ① 补套入口在**工序库非空但缺基础路线**时**可见** | 改前：`!operationsReady` 才显示 ⇒ 不可见 |
| B13 | `#4670` ② 就绪度② 缺基础路线时**点名** | 改前：只显示条数、仍「已完成」 |
| B14 | 迁移**可回滚**（V89）+ §5.7 的 6 条停止条件**可执行** | —— |
| B15 | `./verify-all.sh gate` / `./check-ui-regression.sh` 通过（跨模块加 `./contract-check.sh`） | —— |
| B16 | 新增/修改的测试文件头部有 `# case_ids:` | 否则 `QA Growth Gate` block |

---

## 附录 C：给实现单的**改动面清单**（实测）

| 层 | 文件 | 改什么 |
|---|---|---|
| 迁移 | `backend/admin-api/src/main/resources/db/migration/V88__*.sql`（**新增**） | §5.2 的 7 条 |
| 种子 | `backend/ai-agent-service/app/production/routing.py` | `FABRIC_MAINLINE_STEPS`（`:465`）；`_POSITION_PRICE_ROWS` 的布料行（`:638` 起）；`NEW_MODEL_ONLY_OPERATIONS`（`:125`）；`PENDING_CUSTOMER_CONFIRMATION_OPERATIONS`（`:119`，`裁剪-*` 若被消费则移出） |
| 种子 | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java` | `FABRIC_MAINLINE_STEPS`（`:101`）；`:272-275` 的配料格 |
| 种子 | `backend/admin-api/src/main/resources/production-templates/curtain/seed.json` | 描述（「37 道工序」）与配料/裁剪行 |
| 种子 | `docs/sql/schema.sql` | 若含 V79 终态镜像则同步（实测 `docs/sql/schema.sql:874` 是 `production_operation_positions` 的 DDL，**不含数据行** ⇒ 可能无需改；实现时**核**） |
| 前端 | `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` | §4 全部（分区、折叠、列收窄、第二层聚合、`管理▸` 上移、补套入口条件、就绪度②判据） |
| 守卫 | `tests/unit_ci_workflows/test_fabric_route_seed.py` | `:48` 的 `FABRIC_MAINLINE`；判据 6 |
| 守卫 | `tests/unit_ci_workflows/test_production_catalog_seed.py` | 三源收敛的字面量 |
| 守卫 | `tests/unit_ci_workflows/migration_fingerprints.json` | 新增 V88 一条 |
| 用例 | `frontend/admin-web/tests/unit/pages/production-routings.test.tsx` | 新增 B1-B7 的断言；既有 ⑰-④ / #4665-D 断言**不得放宽** |
| 文档 | `docs/design/craft-calc-and-fabric-routing.md:179` | `配料` → `裁剪`（§7.4） |
| 文档 | `docs/design/ai-craft-config.md:208` | 收窄「商家可见一律用槽位」口径（§7.1 C3） |
| 用例库 | `.github/cases/**` | 按 `migao-dev-flow` §14 补/改（新功能合入必须喂用例库） |
