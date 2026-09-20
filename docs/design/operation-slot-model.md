# 工序槽位模型 + 锚点派生 —— 把「顺序」还给模型

> 状态：**设计 · 待裁定** ｜ 日期：2026-09-20 ｜ issue #4653（母单 #4650 阶段 4 的设计依据）
> **本文是 docs-only**：不改任何生产代码、不改数据、不碰 ai-agent、不改 `.github/workflows/**` 与 `.agent-presets/**`。
>
> ## 用户裁定（逐字，本文的立论依据）
> > 「这个知识来源于我的截图，这个截图来自**旧时代的 ERP 系统设计**，你根据 llm 行业知识背景再深挖一下**是否需要固化工艺流程**？」
> > 「我还有个问题：**为什么工序路线已经定义了顺序，单个工序仍然要配置锚点？**」
> > 「**设计进去开干吧**」
>
> ⇒ 本文据此得出两条结论，全文围绕它们展开：
> **① 固化的是「模型与物理约束」，不是「那 29 行清单」**；**② 锚点应当「派生」，不是「搬运」。**
>
> ## 引用约定
> 代码/迁移引用一律用**符号锚点**（常量名 / 函数名 / 表名 / 列名）；确需给行号处**写仓库相对全路径 + `path:NNN`**。
> 本文基准：`origin/main` @ `4a8e23bf4`（`git rev-parse origin/main`）—— **行号是这一刻的读数**，`origin/main` 前移后会漂。
> 两条**本文件实际遵守**的引用纪律：
> ① ⚠️ **禁用裸文件名引用**（即只写 `routing.py` 这种 basename 再跟行号）：CI 的 `Case Trust Gate` 的 `path` 解析器对
> 「同名多副本」解析失败并判 **`CASE-TRUST-STALE-LINE-REF`（阻塞）** —— 本文件第一版就踩过（3 条红）；
> ② 引用**旁边**不要紧跟反引号包裹的符号名（会被判「行号漂移」，非阻塞但会留噪音）——
> 要写符号就让它真的在那一行附近。
> ℹ️ `docs/design/**` 在 `scripts/drift_audit.py` 里属 **`REF_SURFACE_EXEMPT`**（设计调研类，
> 行号本来就该陈旧）⇒ 本文件**不受** drift-audit 的 `path:NNN` 新鲜度判定；但**仍受** Case Trust Gate 的规则 G。
>
> ## 范围（不做的事，先划清）
> - 本单**不实施**：没有迁移、没有新表、没有引擎代码、没有 AI 改动；阶段 2/3（AI 说一句 / AI 解释）已登记 #4652，本单只写「它们必须建立在什么语义上」；
> - 本单**不发明业务**：凡模型推不出来的，一律进「待裁定项」（§5.3 / §8），**不猜、不静默丢**。

---

## 0.1 ⚠️ 现状真值源的**三条实测事实**（本设计的**前提**，先立住再谈设计）

> 这三条**改变「现状真值源」的口径**，因此放在 §0 之前。全部**自己复现**（命令 + 输出 + 行号见下）。

### F4 · `routing.py::ROUTE_RULES` **不是运行时真值源**（它是设计真值源 / 种子）

```bash
git grep -n "ROUTE_RULES" origin/main -- backend/admin-api/src/main/java
# → 4 处命中，**全是注释**：
#   ProcessingOrderService.java:1198        // `sorted(ROUTE_RULES, key=priority)` 逐字同口径
#   ProductionSeedTemplateService.java:114  「与 {@code routing.py::ROUTE_RULES} 的 craft 部分逐条同源」
#   ProductionSeedTemplateService.java:134  「被守卫钉为「≡ V71 的 26 行字面量种子」」
#   ProductionSeedTemplateService.java:583  「与 routing.py::ROUTE_RULES 的 craft 部分逐条同源」
# ⇒ **没有一处是代码**
```

**运行时真正生效的**是**库表** `production_route_rules`，读它的是
`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:796` `insertConditionalOperations`
（调用点 `:556`）：

```bash
git grep -n "insertConditionalOperations" origin/main -- backend/admin-api/src/main/java
# → ProcessingOrderService.java:556（调用）/ :796（定义）
```

| 概念 | 载体 | 角色 |
|---|---|---|
| **设计真值源 / 种子** | `backend/ai-agent-service/app/production/routing.py:708` `ROUTE_RULES` | 被守卫钉为「≡ V71 的 26 行字面量种子」；`build_route_v2` **零生产消费者** |
| **运行时真值源** | 库表 `production_route_rules`（`docs/sql/schema.sql:910` `production_route_rules`） | `insertConditionalOperations` 读它 ⇒ **真正决定工序清单的是它** |

⇒ **准确表述**：`routing.py::ROUTE_RULES` 是**设计真值源 / 种子**；**运行时真值源是库表**。
**两者不可混为一谈** —— 本文 §5 的「逐条映射」映射的是**两份的并集**
（`ROUTE_RULES` 26 条 ≡ V71 种子 ≡ 1 号租户的 `production_route_rules` 行；`V84` 3 条**只在库表**，
`ROUTE_RULES` 里**没有**）⇒ §5 的 29 条**同时覆盖**设计真值源与运行时真值源。

### F5 · 规则语义有**三份实现**（但**去重语义并非三份不同** —— 见反证）

| # | 实现 | 位置 | 生产消费者 | 载体 / 触发键 |
|---|---|---|---|---|
| 1 | `build_route_v2`（Python） | `backend/ai-agent-service/app/production/routing.py:783` `build_route_v2` | **零**（`git grep -n "build_route_v2" origin/main -- backend/ai-agent-service/app` 只命中 `routing.py` 自己的注释与定义） | `list[str]` / `craft` + `options` |
| 2 | `buildRoute`（Java） | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1175` `buildRoute` | **有**（`:1125` 调用） | `list[str]`（逻辑名）/ `craft` + `options` |
| 3 | `insertConditionalOperations`（Java） | 同文件 `:796` | **有**（`:556` 调用） | `list[Map]`（工序对象）/ `craft` + `options` + **`processingItems`** |

#### ⚠️ **反证（照实登记，不迁就转述）**

转述称「`buildRoute`（**不去重**）」——**实测不符**：

```bash
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java | grep -n "removeIf"
# → 544（定型开关）/ 842（insertConditionalOperations 的取代）/ 1237（remove 动作）/ 1325（insertAfterLogical 的取代）
```

`buildRoute` 的 `insert` 路径走 `insertAfterLogical`（`:1324`），其**第一行**就是
`route.removeIf(op -> Objects.equals(op, operation))`（`:1325`）⇒ **它去重**。
同族地，`build_route_v2` 的 `_insert_after`（`backend/ai-agent-service/app/production/routing.py:355` `_insert_after`）
第一行也是 `route = [op for op in route if op != operation]` ⇒ **它也去重**。

⇒ **实测结论（与转述不同）**：**三份实现都做「取代」去重**。真正的差异**不在去重**，而在：

| 真实差异 | 证据 |
|---|---|
| **① 载体不同**：Python `list[str]` / `buildRoute` `list[str]`（逻辑名）/ `insertConditionalOperations` `list[Map]`（工序对象） | `:1175` vs `:796` 的签名 |
| **② 触发键来源不同**：`insertConditionalOperations` 多一条 `processingItems` | `:556` 传参 vs `build_route_v2` 入参 |
| **③ 过滤时机不同**：`insertConditionalOperations` 插入时同时判部位限定与锚点可用性；`buildRoute` 先构造 `sequence` 再统一滤适用性 | `:808` 附近 vs `:1234` 附近 |
| **④ `buildRoute` 的 docstring 自称「唯一 Java 实现」—— 与实测不符**（还有 `insertConditionalOperations` 在做同类事） | `:1149` 逐字「本方法是「怎么展开路线」的**唯一** Java 实现」 |

⇒ **对槽位模型的意义（阶段 4 的**第一步**，不是迁移）**：**先把三份语义收敛成一份**（§7.4）。
理由：槽位模型的派生算法只能对齐**一个**运行时行为；今天有**两份 Java 实现**在生产路径上
（`:1125` 的 `buildRoute` 与 `:556` 的 `insertConditionalOperations`），
**收敛前做迁移 = 迁移到一个没有唯一基准的目标**。

### F6 · `production_route_rules` **零版本账**

```bash
git grep -n "production_route_rules" origin/main -- docs/sql/schema.sql | grep -i version
# → 无命中（只有列定义与约束）
git grep -n "production_routing_versions" origin/main -- docs/sql/schema.sql
# → docs/sql/schema.sql:1239（挂 routing_id → production_route_templates，**不是规则表**）
```

⇒ **回滚方案不能假设"能回到某个历史版本的规则表"**（§5.5 R1 已据此改写）。

### F4/F5/F6 的**同族文档**（避免重复造轮子）

`docs/design/ai-craft-config.md`（已合入 main，issue #4650 的 AI 层设计）**已经登记过**同族的 F4/F5
（该文件 §8.3 的事实表）。**本文与它的分工**：

| 文档 | 负责 |
|---|---|
| `docs/design/ai-craft-config.md` | **AI 层**（概念移除 / 对话式改条件 / 可解释 / 承载收敛的阶段编排） |
| **本文** | **槽位模型 + 锚点派生**（L1 物理偏序 / L2 映射 / 派生算法 / 29 条逐条映射 / 版本化 / 报工校验） |

⇒ **本文不重复它的阶段编排**；两处若冲突，**以本文 §7 的判据为准并回改它**（§7.4 已给出改判点）。

---

## 0. 大白话：今天商家要理解什么 → 改完商家要理解什么

| | 今天 | 改完 |
|---|---|---|
| 商家要理解的东西 | ① 一条「主线」（9 道，**看不见工艺那一道在哪**）；② 一张「条件工序规则」表（26 条 + 加工项 3 条），每条自带 `trigger_kind` / `trigger_value` / `action` / `operation` / **`after_operation`（锚点）** / `priority` 六个字段 | ① 一条主线；② **每个工艺/选项「占哪个槽」**（一句话）；③ 极少数**租户例外** |
| 「上车布排在哪」怎么回答 | 要看**别的规则有没有命中**：选 `韩褶` ⇒ 它锚在 `韩褶` 之后；选 `四爪钩` ⇒ 它锚在 `三边` 之后（同一道工序两个锚点） | **一句话**：「`上车布` 在**打褶槽之后**」—— 选什么工艺，位置自动正确 |
| 换工艺要改什么 | 改规则的锚点（`上车布` 的两个锚点要**同步改**，漏一个 ⇒ 静默排到末尾） | **不用改**：换工艺 = 换占打褶槽的工序，位置由槽序推出 |
| 加新工艺要说什么 | 写一条规则，还要**替它想好锚点** | 「它**占打褶槽**」（锚点由模型推出） |
| 加新工序（如「烫钻」） | 写规则 + 想锚点 + 排 priority | 「它属于**蒸烫槽**」（槽位内的顺序仍需给，见 §2.2 的诚实边界） |
| 商家看到几张表 | 工序库 + 路线模板 + **条件工序规则表** | 工序库 + 路线模板（条件变成工序/工艺的**属性**，见 #4650 阶段 1） |

**一句话**：今天商家要理解「一张规则表 + 每条规则一个锚点」；改完商家只理解「**工序按物理工艺分槽，锚点由槽序推出**」。

---

## 1. 病根（用实测数据说话）

### 1.0 **前置事实：槽位不是新造的概念 —— 真值源里本来就有，只是落库时被扁平化掉了**

> **这一节是全文的语义依据**。它把本设计的性质从「引入一个新抽象」改写为
> **「把已被扁平化掉的既有语义恢复出来」** —— 后者让迁移与回滚的论证强得多（§5.5）。

#### 实测证据（三处，逐字 + 行号）

**① 真值源里**有**字面量槽位占位**，且它在**第 3 位**：

```bash
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '469,472p'
# → #: 主线**全貌**（含「工艺槽位」占位）—— 仅文档用途，**不落库**
# → #: （槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入）
# → ROUTE_MAINLINE: List[str] = ["精裁", "三边", "⟪工艺槽位⟫", "熨烫", "定型", "复烫",
# →                              "车被", "外帘打卷", "打包", "外帘装袋", "外帘发货"]
```

**② 而实际落库的**主线**不含它**（同一文件紧邻的下一段）：

```bash
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '474,481p'   # ROUTE_MAINLINE_STEPS 在 :480
# → #: **实际落库的 10 道**主线（部位无关；工艺槽位不落库）
# → ROUTE_MAINLINE_STEPS: List[str] = ["精裁", "三边", "熨烫", "定型", "复烫", "车被",
# →                                    "外帘打卷", "打包", "外帘装袋", "外帘发货"]
```

**③ 落库侧的注释把「槽位是什么」写成了明文**（V71 的列注释）：

```bash
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | sed -n '228p'
# → '「工艺槽位」不落库（它只表示「打褶那一道插在这里」，由规则表按工艺插入）。';
```

#### 结论（本设计的定性）

| 命题 | 证据 |
|---|---|
| 「槽位」**不是本设计发明的抽象** | 真值源 `ROUTE_MAINLINE` 第 3 位是**字面量** `⟪工艺槽位⟫`（`:471`） |
| 槽位的**语义已被冻结为「打褶那一道」** | `:470` 逐字「槽位 = 打褶那一道」；`V71:228` 逐字「它只表示「打褶那一道插在这里」」 |
| 它在落库时被**扁平化掉了** | `ROUTE_MAINLINE_STEPS`（落库的 10 道）**不含**槽位（`:474` 逐字「工艺槽位不落库」） |
| ⇒ 规则表的 `after_operation` 是它的**近似表达** | `:470` 逐字「…由 `ROUTE_RULES` 按工艺插入」⇒ 用「锚点」近似「槽位被谁占据 + 插在它之后」 |

⇒ **本设计的性质**：**不是引入新概念，而是把已被扁平化掉的槽位语义恢复出来**。
`after_operation` 是**当时可用的近似**（一个字段表达"插在谁之后"），
但它**丢失了"槽"这层**（槽的偏序、槽的互斥、槽的成立/不成立）⇒ §1.3 的三条代价正是这层丢失的后果。

#### ⚠️ 与转述的一处不符（照实登记，不迁就）

| 转述 | 实测 | 差异 |
|---|---|---|
| 「`backend/ai-agent-service/app/production/routing.py:470` 附近的 `ROUTE_MAINLINE`，**第 3 位是字面量 `⟪工艺槽位⟫`**」 | ✅ **逐字一致** —— `ROUTE_MAINLINE` 在 `backend/ai-agent-service/app/production/routing.py:471`，第 3 位（下标 2）正是 `⟪工艺槽位⟫`；「槽位 = 打褶那一道」在 `backend/ai-agent-service/app/production/routing.py:470` | 无 |
| 「**实际落库的** `ROUTE_MAINLINE_STEPS`（10 道）**不含槽位**」 | ✅ 一致（`:480`） | 无 |
| — | ⚠️ **补充一处**：`ROUTE_MAINLINE`（含槽位的那份）**全仓只有 1 处引用**（就是它自己的定义）—— 实测 `git grep -n "ROUTE_MAINLINE\b" origin/main` 只返回 `:471` 一行 ⇒ 它**没有消费方**（"仅文档用途"是**事实**，不是谦辞） | 转述未提；**这是"槽位语义只活在注释里"的加强证据** |
| — | ⚠️ **补充一处**：`backend/admin-api/src/test/java/com/migao/admin/service/RoutingModelFixture.java:48` 的注释写「规范主线（**9 道**，不含工艺槽位）」，而它返回的 `mainline()` 实际是 **10 道**（含 `打包`） | 同族数字腐烂（§8 F1）；**不在本单修**（测试文件，docs-only 单） |

#### `⟪工艺槽位⟫` 字面量在**全仓**的引用（12 处，逐条判定）

```bash
git grep -n "工艺槽位" origin/main | wc -l    # → 12
```

| # | 位置（仓库相对全路径） | 今天的用途 | 槽位模型落地后**该变成什么** |
|---|---|---|---|
| 1 | `backend/ai-agent-service/app/production/routing.py:469` `ROUTE_MAINLINE` | 「仅文档用途」的**全貌示意**（含占位） | **升级为一等公民**：`SLOTS` 常量（§3.2）取代这条示意；`⟪工艺槽位⟫` 这个**单一占位**拆成 9 个具名槽 |
| 2 | `backend/ai-agent-service/app/production/routing.py:470` `ROUTE_MAINLINE` | 定义「槽位 = 打褶那一道」（**语义冻结处**） | **成为设计依据**：`CRAFT_SLOT` 的取值域（`韩褶`/`打孔`/`穿杆` 占打褶槽）；注释里的「四爪钩」按 §5.3 P1 改判为 legacy |
| 3 | `backend/ai-agent-service/app/production/routing.py:471` `ROUTE_MAINLINE` | **字面量** `⟪工艺槽位⟫`（第 3 位） | **消失** —— 由 `SLOTS` 的槽序取代（不再是"序列里的一个假工序名"） |
| 4 | `backend/ai-agent-service/app/production/routing.py:480` `ROUTE_MAINLINE_STEPS` | 「落库的 10 道**不含**槽位」 | **改口径**：「槽位由 `SLOTS` 承载；`mainline` 不再是唯一的顺序载体」 |
| 5 | `backend/admin-api/src/main/java/com/migao/admin/entity/ProductionRouteTemplate.java:26` `mainline` | 实体字段注释：「『工艺槽位』不落库」 | **改口径**：加一句「槽位由 `production_operation_slots` 承载（阶段 4）」；**保留**"不落库进 mainline"这一条 |
| 6 | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java:89` `ROUTE_MAINLINE_STEPS` | 模板套用的**主线常量**（10 道，**不含**槽位） | **保留**（种子仍需主线）；但「不含槽位」的理由从"不落库"变成"槽位另有载体" |
| 7 | `backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:34` `mainline` | 迁移头注释：落库 9 道不含槽位 | **一字不改**（已发布迁移**不可变** —— `MigrationRunner` 按**文件名**记账，改它 = 存量环境静默缺失；issue #4235） |
| 8 | `backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:228` `mainline` | **列注释**：逐字定义「槽位 = 打褶那一道插在这里」 | **一字不改**（同 #7）；阶段 4 用**新迁移**加一条新注释（`COMMENT ON` 是覆盖写 ⇒ 只能新迁移覆盖） |
| 9 | `backend/admin-api/src/main/resources/db/migration/V72__switch_routing_model_consumers.sql:208` `ROUTE_MAINLINE_STEPS` | 回填口径：9 道不含槽位 | **一字不改**（同 #7） |
| 10 | `backend/admin-api/src/main/resources/db/migration/V76__redo_v72_with_sort_order_fix.sql:179` `ROUTE_MAINLINE_STEPS` | 同上（V72 重做版） | **一字不改**（同 #7） |
| 11 | `backend/admin-api/src/test/java/com/migao/admin/service/RoutingModelFixture.java:48` `mainline` | 测试夹具：「9 道，不含工艺槽位」 | **改判**：注释的「9 道」改「10 道」（数字腐烂）；断言**新增**「槽位表与 `SLOTS` 逐条一致」（阶段 4） |
| 12 | `backend/ai-agent-service/tests/test_production/test_route_model_v2.py:64` `MAINLINE` | 测试分组注释：「『工艺槽位』不落库，只在文档里」 | **改判**：阶段 4 新增「槽序偏序 + 槽内次序」的 L0 断言（§3.6 S1~S10 落码） |

**判定汇总（12 处）**：

| 判定 | 条数 | 说明 |
|---|---|---|
| **一字不改**（已发布迁移，不可变） | **4** | #7 / #8 / #9 / #10 —— 改它们 = 存量环境永远拿不到（issue #4235 的静默缺失形态） |
| **改口径**（生产代码注释/常量） | **4** | #4 / #5 / #6 + #1（#1 是"升级为一等公民"） |
| **改判/新增断言**（测试夹具与守卫） | **2** | #11 / #12 |
| **消失**（字面量本身退场） | **1** | #3 —— `⟪工艺槽位⟫` 这个假工序名不再需要（槽有了真载体） |
| **成为设计依据**（语义冻结处） | **1** | #2 |

⇒ **槽位模型落地要动的"槽位语义引用面"只有 6 处**（4 改口径 + 2 改判），**4 处迁移一字不改**，
**1 处字面量退场**。**这是一个可枚举的小面**（不是"全仓重构"）—— 这也是"恢复既有语义"比"引入新抽象"更省成本的直接体现。

### 1.1 主线是 9 道扁平骨架，**故意不含工艺槽位**

落库值（**不是**文档里的示意）：

```bash
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql \
  | sed -n '234,235p'
# → '["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"]'::jsonb,
```

出处与口径（三处逐字）：

| 出处 | 逐字 | 读数命令 |
|---|---|---|
| `backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:34` `mainline` | 「`mainline` = 落库的 **9 道**（**不含**「工艺槽位」）」 | `git show origin/main:<path> \| sed -n '34p'` |
| `backend/admin-api/src/main/resources/db/migration/V76__redo_v72_with_sort_order_fix.sql:179` `mainline` | 「⚠️ 规范主线顺序（9 道，不含「工艺槽位」）」 | `git show origin/main:<path> \| sed -n '179p'` |
| `backend/ai-agent-service/app/production/routing.py:480` `ROUTE_MAINLINE_STEPS` | 落库 **10 道**（9 道 + `打包`，issue #4529），与 `ROUTE_MAINLINE`（含「⟪工艺槽位⟫」）**不同** | `git show origin/main:<path> \| sed -n '475,483p'` |

> ⚠️ **与 issue #4650 原文的一处差异（照实登记）**：母单写「9 道」，那是 **V71/V76 的落库快照**；
> 今天 `routing.py::ROUTE_MAINLINE_STEPS` 是 **10 道**（V79 把 `打包` 插在 `外帘打卷` 与 `外帘装袋` 之间）。
> 「不含工艺槽位」这条**结论不变**，数字按 **10** 读。

### 1.2 ⇒ 工艺工序只能靠「规则 insert + 锚点」插进去

```bash
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '708p;783,800p'
# 708: ROUTE_RULES: List[Dict[str, Any]] = [        ← 26 条（工艺 10 + 特殊选项 16）
# 783: def build_route_v2(position: Dict[str, Any]) -> List[str]:
# 792:       `insert` 用 `after_operation` 定位（锚点不在序列中 ⇒ **追加末尾** …）
```

实测条数（**自己复现，不抄二手数**）：

```bash
python3 - <<'PY'
import re, collections
src = open('backend/ai-agent-service/app/production/routing.py', encoding='utf-8').read()
i = src.index('ROUTE_RULES: List'); seg = src[i:]; seg = seg[:seg.index('\n]')+2]
rows = re.findall(r'"trigger_kind":\s*"([^"]+)".*?"action":\s*"([^"]+)"', seg, re.S)
print("total:", len(rows), dict(collections.Counter(k for k,_ in rows)), dict(collections.Counter(a for _,a in rows)))
PY
# → total: 26 {'craft': 10, 'option': 16} {'insert': 21, 'remove': 5}
```

### 1.3 锚点是设计味道：三条代价，各给证据

#### 代价 ①：商家不可理解 —— 锚点的含义**依赖别的规则是否命中**

`build_route_v2` 的 `insert` 分支用 `_insert_after`（`backend/ai-agent-service/app/production/routing.py:355` `_insert_after`）定位；
它的语义是「锚点在序列里**已经存在**才插得进去，否则追加末尾」（docstring 逐字，`:792`）。
⇒ 同一行规则（`insert 上车布 after 韩褶`）的**实际位置取决于「`韩褶` 那条规则有没有先命中」**：

```bash
git show origin/main:backend/ai-agent-service/tests/test_production/test_route_model_v2.py \
  | sed -n '439,442p'
# → test_hanzhe_rules_order_is_load_bearing：
#    "`insert 上车布 after 韩褶` 必须先落锚点「韩褶」再插「上车布」，否则会追加到末尾"
```

**这不是"优先级"问题，是"位置"问题**：规则的**顺序语义**（`priority`）与**位置语义**（`after_operation`）耦合在一起，
而耦合点（「锚点当时在不在」）**不在那一行规则里**，在**别的规则里**。商家读一行规则读不出位置。

#### 代价 ②：同一工序在不同条件下锚点不同 ⇒ 重复、易漂移

实测（`ROUTE_RULES` 逐条）：

| 触发条件 | 工序 | `after_operation` | `priority` |
|---|---|---|---|
| `craft=韩褶` | `上车布` | `韩褶` | 20 |
| `craft=四爪钩` | `上车布` | `三边` | 40 |

⇒ **同一道工序两个锚点**。改一次位置要改**两行**，漏一行 ⇒ 位置错且**不报错**（见代价 ③）。
（同族事实：`接高` 两行都锚 `精裁`、`绑带` 三行都锚 `车被`、`帘头制作` 两行都锚 `三边` —— 这三组**一致**，
所以"锚点重复"的危害是**分布式的**：只有不一致的那一组会漂，而没有任何东西会因此变红。）

#### 代价 ③：写错**静默出错** —— 锚点找不到 ⇒ 条件工序**静默追加到末尾**

两处独立实现**都**是这个语义（Python 真值源 + Java 实例化端）：

| 端 | 出处 | 逐字 |
|---|---|---|
| Python | `backend/ai-agent-service/app/production/routing.py:792` `build_route_v2` | 「`insert` 用 `after_operation` 定位（锚点不在序列中 ⇒ **追加末尾**…）」 |
| Python | `backend/ai-agent-service/app/production/routing.py:355` `_insert_after` | 「把 operation 插到 after 之后（**after 不在路线中则追加到末尾**）」 |
| Java | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1155` `buildRoute` | 「`insert` 用 `after_operation` 定位（锚点不在序列中 ⇒ **追加末尾**…）」 |
| Java | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1315` `insertAfterLogical` | 「把 `operation` 插到 `after` 之后（**锚点不在序列中 ⇒ 追加末尾**…）」 |
V71 的注释把这个后果写成了迁移纪律（逐字）：

> 「不归一 ⇒ 锚点在逻辑名序列里找不到 ⇒ 条件工序会**静默追加到末尾**，工序顺序错」
> —— `backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:37` 的 **ROUTE_RULES** 段（该常量本身在 `backend/ai-agent-service/app/production/routing.py:708`）

**代价的形态**：车间按错顺序干（例：`上车布` 排到 `外帘发货` 之后）⇒ 工人要么返工、要么跳过，
而**系统不报错、无告警、无数据可查**。这与 #4609「静默丢工序」同族（都是「工序清单静默偏离模型」）。

### 1.4 为什么不退回「每条路线一条」

旧模型的事实（`routing.py` 新模型真值源 header 的对照表，`:428` 起）：

| 旧（`ROUTINGS`，9 条「展开快照」） | 新（`ROUTE_MAINLINE_STEPS` + `ROUTE_RULES`） |
|---|---|
| 每道工序名把**部位编码进名字**（`精裁-布`/`精裁-纱`、`布三边`/`纱三边`） | 逻辑工序名（`精裁`/`三边`）+ **部位适用性矩阵** |
| `(部位, 工艺)` 笛卡尔积 ⇒ 9 条路线，**改一道工序要改 8 遍** | **1 条主线** + `ROUTE_RULES`（工艺/选项触发 insert/remove） |

实测 9 条路线（`backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql:73` `production_routings` 6 行 + `backend/admin-api/src/main/resources/db/migration/V58__seed_sheer_curtain_routings.sql:38` 3 行）：

```bash
git show origin/main:backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql | grep -cE "^\s*\('rt-v54-"
# → 6
git show origin/main:backend/admin-api/src/main/resources/db/migration/V58__seed_sheer_curtain_routings.sql | grep -cE "^\s*\('rt-v58-"
# → 3   ⇒ 9 条
```

**两头都不对**：

- **旧头**（9 条展开路线）：**重复 8 遍** ⇒ 改一道工序要改 8 处，必漂移；
- **现头**（1 主线 + 规则）：消掉了重复，**但把「顺序」降级成了每条规则自带的一个字段**（`after_operation`）
  ⇒ 顺序不再由模型持有，而是散在 29 行里，**每行各自正确、合起来才正确**（且合起来不正确时不报错，§1.3③）。

⇒ 本文要的是**第三种**：**顺序由模型持有（槽位偏序），配置只声明「谁属于哪个槽」**。

### 1.5 附带实测：`四爪钩` 是**过时形态**（本文必须显式处置，§5.3 P1）

| 事实 | 证据（逐字） |
|---|---|
| 「`四爪钩/四叉钩`」是**加工项（配件）不是工艺** | `backend/admin-api/src/main/resources/db/migration/V63__structure_order_line_craft_spec.sql:59` `craft` 列注释 |
| 信号层已把它改指主线工艺（`韩褶`） | 同文件 `:82` 的 `UPDATE production_route_signals SET craft = '韩褶' WHERE signal IN ('四爪钩','四叉钩')` |
| 加工项目录里**没有** `四爪钩` 行（本迁移**不发明**） | `backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql:28` `craft` 「**四爪钩 / 四叉钩**是**加工项（配件）**」（标题在 `:27`） |
| 但那 3 条 `craft` 规则**保持 active、不得停用** | 同文件 `:32` 「存量单不受影响（`order_items.craft='四爪钩'` 照旧派生，其 3 条 `craft` 规则**保持 active**，不得停用）」 |

⇒ **今天 `四爪钩` 在三个地方同时存在三种身份**：① `order_items.craft` 列里是**历史值**；
② `production_route_rules` 里是**活跃规则键**；③ `processing_items` 目录里**没有它**。
**任何"把规则搬到槽位"的方案都必须显式处置这三条**，否则要么丢存量单的处理（停用规则），
要么把「配件」固化成「工艺」（发明）。

---

## 2. 目标模型：槽位序列

### 2.0 三条层次（本文的核心分层，也是 #4650 阶段 4 的口径）

| 层 | 内容 | 谁定 | 可变性 |
|---|---|---|---|
| **L1 物理约束** | **槽位偏序**（谁必须在前、谁必须在后） | 物理事实（§2.1 论证） | **不可变**（改它 = 改物理） |
| **L2 领域模型** | 工艺→槽、选项→加法、否定→去槽、部位适用性 | 领域知识（本文 §2.3~§2.5） | 出厂默认，可版本化 |
| **L3 出厂知识** | 槽位内的**内部顺序** + 具体工序名 + 锚位 | 行业惯例（**可版本化升级**） | 出厂知识，租户可覆盖 |
| **L4 租户例外** | 商家说一句改一处 | 商家 | 租户级，可撤销 |
| **L5 实例快照** | 加工单里那一份工序清单 | 生成时刻冻结 | **一字不动**（红线） |

**关键区分（今天混在一起）**：L1 是**偏序**（只有"在...之后"），L3 是**全序**（槽位内的具体次序）。
今天 `after_operation` 把两者压成了一个字段 ⇒ 改一个锚点就可能**违反物理约束而不报错**（§1.3③）。

### 2.1 槽位清单 + 「为什么这个顺序是物理事实」

> ⚠️ **槽名的来源分层（issue #4678，2026-09-20 追加）—— 别把这些槽名当行业术语用**：
>
> | 分类 | 槽名 | 依据 |
> |---|---|---|
> | ✅ **有真值源逐字依据** | **`打褶槽`**（**全仓唯一**） | `backend/ai-agent-service/app/production/routing.py:470` 逐字「槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入」；字面量 `⟪工艺槽位⟫` 在 `backend/ai-agent-service/app/production/routing.py:471` 的 `ROUTE_MAINLINE` 第 3 位 |
> | ⚠️ **本设计推导**（**不是**真值源逐字） | `裁剪槽` / `边缘槽` / `挂钩槽` / `蒸烫槽` / `复烫槽` / `车底槽` / `包装槽` / `发货槽` / `质检槽` / `加法槽` | 本节 §2.1 的「物理论证」列 —— 是**本文的推理**，**未**从行业文档或 ERP 逐字取得 |
>
> ⇒ 表内**只有 `打褶槽` 标了「✅有真值源逐字依据」**，**未标注者一律视为本设计推导**。
> ⇒ **商家可见的分组/分区不许用这些槽名**（用户裁定：界面第一层用行业术语 —— 裁剪 / 车位 / 后整 / 质检 / 包装；
> 见 `docs/design/ai-craft-config.md` §2.5 的口径收窄）；槽名只作**主线内部顺序**的建模用语。
> 术语真值源：`docs/curtain-production-process-standard.md`。

| # | 槽位 | 一句话职责 | 必须晚于 | 物理论证 |
|---|---|---|---|---|
| 1 | **裁剪槽** | 按尺寸裁片（`精裁`/`裁剪`/`配料`） | —（起点） | 一切缝制的前置：没有裁片就没有后续 |
| 2 | **边缘槽** | 缝合边缘（`三边`） | 裁剪槽 | 缝合需要**已裁好的片**；反过来不可能 |
| 3 | **打褶槽** ✅**有真值源逐字依据**（全仓唯一） | 产生褶/孔几何（`韩褶`/`打孔`/`穿杆`） | 边缘槽 | **褶型是缝在成品边缘上的** ⇒ 必须先有边；且褶一旦压出来，**再修边会把褶拆掉**（不可逆） |
| 4 | **挂钩槽** | 挂布/穿钩（`上车布`） | 打褶槽 | 「上布」= 把布挂到轨道/钩上 —— 需要**已有褶或孔**；无褶工艺下它只是挂在边缘槽之后（§5.3 P1 的推导） |
| 5 | **蒸烫槽** | 熨烫 + 热定型（`熨烫`/`定型`） | 打褶槽 + 挂钩槽 | **定型 = 把褶型热固定**（不可逆的形态固定）⇒ 褶/挂钩必须**已经存在**；在打褶前烫，烫完再压褶 ⇒ 定型白做 |
| 6 | **复烫槽** | 冷却后复整/回修（`复烫`） | 蒸烫槽 | 「复」= 第二次 ⇒ 语义上必然在定型之后；且它是**修**（把定型后产生的轻微变形整回） |
| 7 | **车底槽** | 缝制底边/衬（`车被`） | 复烫槽 | 底缝在**定型面上**作业；先车底再定型 ⇒ 定型会破坏底缝线；先定型再车底 ⇒ 底缝只影响底边、不影响褶型 |
| 8 | **包装槽** | 打卷/装袋/打包（`外帘打卷`/`打包`/`外帘装袋`） | 车底槽 | 包装是**成品封装** ⇒ 必须在所有加工之后（含全部加法项） |
| 9 | **发货槽** | 外帘发货（`外帘发货`） | 包装槽 | 发货必然在包装之后 |
| ★ | **质检槽** | 质检（`质检`） | **可移动** | **不是一道固定位置的工序，而是"检验点"** —— 检验可以发生在边缘槽后 / 定型后 / 发货前。今天它是 `ROUTE_MAINLINE` 的**占位**（不落库、无规则行）⇒ 归入「可移动槽」（§8 待裁定 A5） |
| ★ | **加法槽** | 独立加法项（`抱枕`/`腰靠垫`/`绑带`…） | **按项定** | 这些是**另一件产品/配件**（抱枕、腰靠垫）或**可挂载的附件**（绑带），**没有共同的物理位置** ⇒ 建模为「带 `after_slot` 的加法项」而非硬塞进某个固定槽（§2.4） |

> **与真值源的关系（§1.0）**：真值源 `ROUTE_MAINLINE` 里**只有 1 个**占位槽（`⟪工艺槽位⟫`，第 3 位，
> 语义 = 「打褶那一道」）。本文的 **9 槽**是它的**推广** —— 把「只有打褶那一道需要占位」扩展为
> 「**所有有物理位置约束的工序族都需要占位**」。**这不是发明新维度**：它用的是同一个概念（槽），
> 只是把真值源里"只给打褶那一道留了位"的**不完整占位**补齐（§2.2 已诚实登记：槽内次序仍需要一个显式载体）。

**结论**：主链 **9 槽** + 2 个特殊槽（可移动质检槽 / 按项定加法槽）。
`打包` 的槽内位置（`外帘打卷` 与 `外帘装袋` 之间）**保持 V79 现状**（`backend/admin-api/src/main/resources/db/migration/V79__seed_fabric_route_and_packing_operation.sql:264` `mainline` 起的插行逻辑（`:262` 是幂等口径注释）），
**不借本单改顺序**（V79 自己登记为「按 ERP 顺序推断、**待客户确认**」⇒ 见 §8 A8）。

### 2.2 槽位的偏序 ≠ 全序（**诚实边界**）

**槽位只给偏序**（§2.1 的「必须晚于」），**槽位内的次序是 L3 出厂知识**，仍需要一个显式载体。三个真实例子：

| 槽位 | 槽内工序 | 今天的次序来自哪 | 模型能否推出 |
|---|---|---|---|
| 蒸烫槽 | `熨烫` → `定型` → `复烫`？ | **主线声明顺序**（`ROUTE_MAINLINE_STEPS` 数组次序） | ❌ 推不出 —— 「定型必须在熨烫后」是物理事实，但「复烫在定型后」是**流程惯例**；且 `定型`/`复烫` 是**可被否定掉**的（`四爪钩`/`穿杆`/`平幔` 的 5 条 `remove`）⇒ 三道的相对次序不能靠"槽内就按主线顺序"含糊带过 |
| 边缘槽 | `三边`（1 道）+ `花边`/`铅坠`/`logo条`/`立边`/`扣环`/`防翘扣` | 各规则**锚点都是 `三边`** ⇒ 今天全部排在 `三边` 之后，**彼此之间的次序由 priority 决定** | ❌ 推不出（今天的次序是 priority 的副产物） |
| 包装槽 | `外帘打卷` → `打包` → `外帘装袋` | V79 的插行位置 | ❌ 推不出（V79 自陈「待客户确认」） |

⇒ **诚实结论**：本模型**消灭的是"跨槽的锚点字段"**（29 行里的 `after_operation`），
**不能消灭"槽内次序"**。槽内次序必须落成**显式的一列**（`slot_order`，见 §3 的 `SLOT_MEMBERS` 形状），
**否则就是"把锚点藏进数组下标"**（同一类味道换个地方）。本文**不假装**这一点已解决。

### 2.3 工艺 → 槽位映射（互斥）

| 工艺（`craft`，真值源 §8 冻结为「打褶/悬挂方式」**单值**） | 占哪个槽 | 备注 |
|---|---|---|
| `韩褶` | **打褶槽** | 生成褶 |
| `打孔` | **打褶槽** | 生成孔；与 `韩褶` **互斥**（工艺单值 ⇒ 天然互斥）。孔位与褶位是**同一几何位**的两种形态 ⇒ 同槽 |
| `穿杆` | **打褶槽** | 直接穿杆（无褶无孔）⇒ 占槽但**不产褶** ⇒ 其后的挂钩槽按 §5.3 P1 推导 |
| `平幔` | **边缘槽**（`帘头制作`）+ 否定蒸烫/复烫 | 平幔是**帘头形态**（罗马帘），不是打褶方式 ⇒ 它不占打褶槽，而是加一道 `帘头制作`（今天锚 `三边` ⇒ 边缘槽内） |
| `四爪钩` ⚠️ | **过时形态，见 §5.3 P1** | V63 起是**加工项**、不是工艺；规则**保持 active** 只为存量单 |

**互斥的实现**：打褶槽是**单占槽**（`capacity=1`）⇒ 工艺单值天然保证"只有一个占槽者"。
今天靠"工艺是单值"这件事**隐式**保证；模型里显式化成 `capacity`，这样「加第 6 个工艺」时
「它占哪个槽」成为**必答项**（不答 ⇒ 占不到槽 ⇒ 可见）。

### 2.4 选项 → 加法（占槽 / 加法项）

| 选项（`special_options` / `processing_items`，逐字 = ERP 写法） | 目标工序 | 落点 | 类型 |
|---|---|---|---|
| `拼1次` / `拼2次` / `拼3次` | `拼1次` / `拼2次` / `拼3次` | 边缘槽（今天锚 `三边`） | 占槽 |
| `加花边` / `花边`（加工项） | `花边` | **待裁定 A2**（今天锚 `三边` ⇒ 表面在边缘槽，但"花边"是**加法装饰**） | 待裁定 |
| `加铅块` | `铅坠` | 边缘槽（今天锚 `三边`） | 占槽 |
| `加logo条` | `logo条` | 边缘槽 | 占槽 |
| `加立边` | `立边` | 边缘槽 | 占槽 |
| `扣环` / `扣环`（加工项） | `扣环` | 边缘槽 | 占槽 |
| `防翘扣` | `防翘扣` | 边缘槽 | 占槽 |
| `接高` / `双眼皮接高` / `接高`（加工项） | `接高` | **裁剪槽**（今天锚 `精裁`） | 占槽 |
| `余料做绑带` / `布绑带` / `纱绑带` | `绑带` | **车底槽**（今天锚 `车被`） | 占槽 |
| `余料做帘头` | `帘头制作` | 边缘槽（今天锚 `三边`） | 占槽 |
| `抱枕` | `抱枕` | **加法槽**（今天锚 `外帘打卷`） | 加法项（另一件产品） |
| `腰靠垫` | `腰靠垫` | **加法槽** | 加法项（今天**无规则行** ⇒ §8 A6） |

**⚠️ 「占槽」与「加法项」的区别**（这是"槽位"这个词的唯一含混点，本文显式定名）：

- **占槽**：该工序**占据**槽位的一个位置 ⇒ 参与该槽的**偏序**（例：`花边` 若占边缘槽，它就受"边缘槽 → 打褶槽"约束）；
- **加法项**：该工序**不参与**任何槽的偏序 ⇒ 它自带 `after_slot`（挂到某个槽之后）。例：`抱枕` 是另一件产品，
  它的位置与窗帘主链**无物理耦合**，硬塞进"包装槽"是假耦合。

### 2.5 否定（去掉某槽里的工序）

今天的 5 条 `remove`（全部是**工艺**触发，全部只涉及 `定型`/`复烫` 两道）：

| 触发 | 去掉 | 出处 |
|---|---|---|
| `craft=四爪钩` | `定型`、`复烫` | `ROUTE_RULES` `priority` 50/60 |
| `craft=穿杆` | `定型`、`复烫` | 同 `priority` 70/80 |
| `craft=平幔` | `复烫` | 同 `priority` 100 |

**槽位语义下的读法**（不是"删一道工序"，而是"该槽对该工艺**不成立**"）：

| 工艺 | 蒸烫槽 | 复烫槽 | 为什么（物理论证） |
|---|---|---|---|
| `韩褶` / `打孔` | 成立（`熨烫`+`定型`） | 成立 | 有褶/孔 ⇒ 需要热定型固定 |
| `穿杆` | **不成立** | **不成立** | 无褶无孔（直接穿杆）⇒ 没有需要定型的形态；定型无对象 |
| `四爪钩` | **不成立** | **不成立** | 同「无褶」（它是配件）⇒ 见 §5.3 P1 |
| `平幔` | 成立（`定型`） | **不成立** | 帘头要定型（`定型 × 帘头 applicable=True`），但不复烫 |

⇒ **否定的载体**：从「一条 `remove` 规则」变成「工艺 → 该槽是否成立」的**一格布尔**。
这格布尔**今天散在 5 行规则里**（含 `after_operation=NULL` 这种"无锚点"的特殊形态）。

### 2.6 部位适用性（沿用今天的矩阵，不改口径）

今天已有的矩阵：`backend/ai-agent-service/app/production/routing.py:549` `_POSITION_PRICE_ROWS`
（**30 道逻辑工序 × 4 部位 = 120 行**，逐行显式，`applicable` 与 `unit_price` 分离）。
**槽位模型不改这一层** —— 它是**已经正确的目标形态**（`docs/design/operation-name-unification.md` §6 N5 同款判断）。

实例（本单实测的、与直觉不符的两处）：

| 工序 | 布帘 | 纱帘 | 帘头 | 布料 | 与直觉不符处 |
|---|---|---|---|---|---|
| `定型` | ✅ 0.4 | ❌ | ✅ 0.4 | ❌ | **帘头做定型**（纱帘不做） |
| `熨烫` | ✅ 0.35 | ❌ | ❌ | ❌ | **帘头不做熨烫**（但做定型）⇒ §8 A1 |
| `车被` | ✅ 0.4 | ❌ | ❌ | ❌ | 只有布帘有底 |
| `配料` | ❌ | ❌ | ❌ | ✅（未定价） | **布料专属** |
| `打包` | ✅（未定价） | ✅ | ✅ | ✅ | **跨产品形态**（不等于 `外帘装袋`） |

```bash
# 复现上表（任一行）
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -nE '\("(定型|熨烫|车被|配料|打包)", "(布帘|纱帘|帘头|布料)"'
```

### 2.7 锚位派生规则（**锚点字段消失**）

| 今天的锚点 | 槽位模型的推导 | 推导路径 |
|---|---|---|
| `韩褶` after `三边` | 打褶槽（首工序） | 工艺 `韩褶` 占打褶槽 ⇒ 槽内第 1 位 |
| `打孔` after `三边` | 打褶槽 | 同上（`打孔` 占打褶槽） |
| `上车布` after `韩褶`（韩褶下） | **挂钩槽**（第 1 位） | 槽序：打褶槽 < 挂钩槽 ⇒ 自动在 `韩褶` 之后 |
| `上车布` after `三边`（四爪钩下） | **挂钩槽**（第 1 位） | 同上 ⇒ **两个锚点塌成一个位置**（这正是"派生"要的效果） |
| `帘头制作` after `三边` | 边缘槽 | 工艺 `平幔` / 选项 `余料做帘头` ⇒ 边缘槽成员 |
| `接高` after `精裁` | 裁剪槽 | 选项 `接高`/`双眼皮接高`/加工项 `接高` ⇒ 裁剪槽成员 |
| `绑带` after `车被` | 车底槽 | 选项 `余料做绑带`/`布绑带`/`纱绑带` ⇒ 车底槽成员 |
| `抱枕` after `外帘打卷` | 加法槽（`after_slot=包装槽`） | 加法项自带 `after_slot` |
| `拼N次`/`花边`/`铅坠`/`logo条`/`立边`/`扣环`/`防翘扣` after `三边` | 边缘槽 | 各选项 ⇒ 边缘槽成员 |
| `定型`/`复烫`（被 remove） | **槽不成立** | 工艺 → 槽的布尔（§2.5） |

⇒ **`after_operation` 列从 29 行里彻底消失**；位置由 `槽序 × 槽内位次 × after_slot` 推出。
**唯一保留"锚点"概念的地方** = 加法项的 `after_slot`（且它指向**槽**，不是指向**工序**）。

### 2.8 例外覆盖（**只有当模型推不出时才允许，且是例外不是必填字段**）

| 例外形态 | 载体 | 例子 |
|---|---|---|
| 槽内次序与我厂不同 | 租户级 `slot_member_order` 覆盖 | 「我们家的 `复烫` 排在 `定型` 前」 |
| 某个槽对我厂不成立 | 租户级 `slot_disabled` | 「我们家不做质检」 |
| 某工艺多一道活 | 租户级 `extra_member` | 「打孔还要加一道 `烫孔`」 |
| 某工序挂到别处 | 租户级 `after_slot` 覆盖 | 「我们的 `抱枕` 在发货后单独做」 |

**四条纪律**：
1. **例外必须可枚举**（能列出"这家租户偏离了出厂默认的哪几格"）⇒ 否则就是第二张规则表；
2. **例外不能违反 L1 偏序**（例：不能让 `三边` 排到 `精裁` 前）⇒ 违反 ⇒ **fail-closed 拒绝并报错**（不静默）；
3. **例外不是必填**（商家零配置即正确 —— 这是 #4650「出厂知识默认正确、商家零配置」的落地形态）；
4. **例外要能撤销**（回到出厂默认 = 删掉例外行）。

---

## 3. 派生算法（伪代码 + 接口形状）

### 3.1 接口形状

```python
# 输入（与今天 build_route_v2 的入参同族，扩两处：processing_items / knowledge_version 固定）
Position = {
    "curtain_type": str,        # 部位：布帘 / 纱帘 / 帘头 / 布料
    "craft": str | None,        # 工艺：韩褶 / 打孔 / 穿杆 / 平幔（单值）
    "special_options": list[str],   # 特殊选项（逐字 = ERP 写法）
    "processing_items": list[str],  # 加工项名（issue #4577 起也是触发键）
}

# 输出
DerivedRoute = {
    "operations": list[str],     # 逻辑工序名，**有序**（= 今天的 build_route_v2 返回值）
    "reasons": list[Reason],     # 每条工序的来源（供 #4650 阶段 3 的"解释"用，AI 只措辞）
    "knowledge_version": int,    # 本次派生用的出厂知识版本
    "warnings": list[str],       # 推不出 / 例外违反偏序 / 未知工艺 ⇒ 显式（**不静默**）
}

Reason = {
    "operation": str,
    "slot": str,                 # 落在哪个槽
    "because": {"kind": "craft"|"option"|"processing_item"|"mainline",
                "value": str},
    "position_in_slot": int,
}
```

**形状说明**：`DerivedRoute` 是 `build_route_v2` 的**超集** —— 今天调用方只要 `list[str]`，
所以**今天就能零成本对齐**（把 `operations` 当返回值用，其余键是新增的可选面）。

### 3.2 知识常量形状（取代 `ROUTE_RULES`）

```python
SLOTS = [                       # L1：物理偏序（**不可变**）
    ("裁剪槽", ["精裁", "裁剪", "配料"]),
    ("边缘槽", ["三边"]),
    ("打褶槽", ["韩褶", "打孔", "穿杆"]),      # capacity=1（互斥）
    ("挂钩槽", ["上车布"]),
    ("蒸烫槽", ["熨烫", "定型"]),
    ("复烫槽", ["复烫"]),
    ("车底槽", ["车被"]),
    ("包装槽", ["外帘打卷", "打包", "外帘装袋"]),
    ("发货槽", ["外帘发货"]),
]
MOVABLE_SLOTS = {"质检槽": ["质检"]}          # 不参与主链偏序（挂载式）
ADDITIVE = {                                  # 加法项：自带 after_slot
    "抱枕":   "包装槽",
    "腰靠垫": "包装槽",
    "绑带":   "车底槽",
}

CRAFT_SLOT = {"韩褶": "打褶槽", "打孔": "打褶槽", "穿杆": "打褶槽"}   # L2
CRAFT_EXTRA = {"平幔": [("帘头制作", "边缘槽")]}                     # 工艺带来的额外成员
CRAFT_NEGATES = {"穿杆": ["蒸烫槽", "复烫槽"],                       # 槽不成立
                 "四爪钩": ["蒸烫槽", "复烫槽"],                     # ⚠️ 过时形态，见 §5.3 P1
                 "平幔": ["复烫槽"]}

OPTION_SLOT = {                                                      # 选项 → 槽成员
    "拼1次": ("拼1次", "边缘槽"), "拼2次": ("拼2次", "边缘槽"), "拼3次": ("拼3次", "边缘槽"),
    "加花边": ("花边", "边缘槽"), "加铅块": ("铅坠", "边缘槽"),
    "接高": ("接高", "裁剪槽"), "双眼皮接高": ("接高", "裁剪槽"),
    "余料做绑带": ("绑带", "车底槽"), "布绑带": ("绑带", "车底槽"), "纱绑带": ("绑带", "车底槽"),
    "余料做帘头": ("帘头制作", "边缘槽"),
    "抱枕": ("抱枕", "包装槽"),
    "加logo条": ("logo条", "边缘槽"), "加立边": ("立边", "边缘槽"),
    "扣环": ("扣环", "边缘槽"), "防翘扣": ("防翘扣", "边缘槽"),
}
PROCESSING_ITEM_SLOT = {"花边": ("花边", "边缘槽"), "扣环": ("扣环", "边缘槽"),
                        "接高": ("接高", "裁剪槽")}                   # V84 三条

SLOT_MEMBER_ORDER = {  # L3：槽内次序（**显式一列**，不靠 priority、不靠数组下标）
    "蒸烫槽": ["熨烫", "定型"],
    "边缘槽": ["三边", "帘头制作", "拼1次", "拼2次", "拼3次", "花边", "铅坠",
              "logo条", "立边", "扣环", "防翘扣"],
    "包装槽": ["外帘打卷", "打包", "外帘装袋"],
    "裁剪槽": ["精裁", "裁剪", "配料", "接高"],
    "车底槽": ["车被", "绑带"],
}
```

### 3.3 算法（伪代码）

```
derive(position, craft, options, items, tenant_exceptions, knowledge_version):
    # ① 部位适用性**先算成一张表**（不改判定，只改时机 —— 见 §3.4 的顺序说明）
    #    真值源：routing.py::OPERATION_POSITION_PRICES（120 行 = 30 逻辑工序 × 4 部位）
    applicable(op) = OPERATION_POSITION_PRICES[op][position]["applicable"]

    # ② 选骨架：**两条主线由部位选定**（沿用 build_route_v2 的既有分支）
    #    布料（第 4 部位，issue #4529）= 2 道 ⇒ 只有两个槽
    FABRIC_SLOTS = [("裁剪槽", ["配料"]), ("包装槽", ["打包"])]
    slots = SLOTS if position != "布料" else FABRIC_SLOTS

    # ③ 定"槽是否成立"（否定）—— **先于加法**
    for slot in CRAFT_NEGATES.get(craft, []):
        if slot not in tenant_exceptions.revive_slots:      # 例外可复活
            slots.disable(slot)

    # ④ 占槽（工艺，互斥）
    occupied = {}                       # slot -> operation
    if craft in CRAFT_SLOT:
        occupied[CRAFT_SLOT[craft]] = craft
    for (op, slot) in CRAFT_EXTRA.get(craft, []):
        slots.add_member(slot, op)

    # ⑤ 加法（选项 + 加工项）—— **后于否定**
    for opt in options:
        if opt in OPTION_SLOT: slots.add_member(*OPTION_SLOT[opt])
    for it in items:
        if it in PROCESSING_ITEM_SLOT: slots.add_member(*PROCESSING_ITEM_SLOT[it])

    # ⑥ 租户例外（覆盖槽内次序 / 增删成员 / 改 after_slot）
    slots.apply(tenant_exceptions)
    if slots.violates_l1_ordering():                        # 违反物理偏序 ⇒ fail-closed
        raise L1Violation(...)                              # **不静默降级**

    # ⑦ 展开：按槽序 → 槽内 SLOT_MEMBER_ORDER → 逐成员取"是否成立/是否适用"
    out = []
    for slot in slots.in_order():
        if not slot.enabled: continue
        for op in slot.members_in_order():
            if op == occupied.get(slot.name): pass          # 占槽者优先
            if not applicable(op):  warnings.add(f"{op} 在 {position} 不适用 ⇒ 滤掉"); continue
            out.append(op)

    # ⑧ 加法项（按 after_slot 挂到槽后）
    for (op, after_slot) in ADDITIVE.items():
        if op in triggered: out.insert_after_slot(after_slot, op)

    # ⑨ 幂等收口：同一工序**恰好出现一次**（**取代**语义，沿用 issue #4577 的用户裁定）
    #    判据 = 目标工序名相同 ⇒ 先移除序列里已有的该工序，再按本条的槽位插入
    #    （真值源同款：routing.py::_insert_after 的 docstring「唯一性 = 取代」）
    out = dedupe_by_slot_order(out)      # 后到者按其槽位落位，前一处被移除

    return DerivedRoute(operations=out, reasons=..., knowledge_version=..., warnings=...)
```

### 3.4 过滤顺序与优先级语义

**明确的过滤顺序**（每一步的理由）：

| 序 | 步骤 | 为什么在这个位置 |
|---|---|---|
| 1 | **否定（槽不成立）** | 必须**先于加法**：否则「`穿杆` 去蒸烫槽」与「某选项加蒸烫槽成员」的胜负取决于声明顺序（今天的 `priority` 就是这种隐式胜负） |
| 2 | **占槽（工艺）** | 工艺决定"哪些槽有内容" ⇒ 加法是往已有的槽里加东西 |
| 3 | **加法（选项 / 加工项）** | 今天 `option` 的 priority（110~260）**全部大于** `craft`（10~100）⇒ 顺序与今天**一致**（这是"零行为变化"的一部分） |
| 4 | **租户例外** | 例外是**最后一层覆盖**（出厂默认先算出正确结果，例外只改偏离处） |
| 5 | **部位适用性（滤）** | **放最后**：先算"该做哪些工序"，再按部位滤 ⇒ 这样 `applicable` 与 `unit_price` 的语义分离（`applicable=True` 且 `unit_price=None` = **适用但未定价**，与"不适用"可区分 —— 沿用 issue #4529 冻结口径） |

**今天的 `priority` 怎么被槽位取代**：

| `priority` 今天承担的两件事 | 槽位模型里谁承担 |
|---|---|
| ① **规则应用顺序**（`remove` 不先于 `insert`；锚点可用性） | **消失** —— 位置由槽序推出，没有"锚点可用性"这回事（§3.4 步骤 1→3 的固定顺序取代它） |
| ② **同槽内成员的相对次序** | `SLOT_MEMBER_ORDER`（**显式一列**，不是隐式数组下标） |

⇒ **`priority` 字段整体退场**。**注意**：今天 `priority` 在两端的实现是
「`sorted(ROUTE_RULES, key=priority)`（Python，`backend/ai-agent-service/app/production/routing.py:806` `ROUTE_RULES`）+ `priority` 升序再按 `id` 兜底（Java，`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1199` `ordered`）」⇒ 两端的 tie-break **不同**（Python 靠声明顺序稳定排序，
Java 靠 `id`）。**这是今天的一处双源裂缝**（同 priority 时两端可能不一致）；
槽位模型用 `SLOT_MEMBER_ORDER` 显式排序 ⇒ **顺带消掉这处裂缝**（§8 A9 登记为"待确认是否为实际缺陷"）。

### 3.5 幂等与确定性

| 要求 | 怎么保证 |
|---|---|
| **纯函数** | 输入 `(部位, 工艺, 选项[], 加工项[], 例外, 版本)` 决定输出；不读时钟、不读 DB 之外的状态（沿用 `build_route_v2` 的"纯函数、零 LLM"口径） |
| **确定性** | 所有遍历都有**显式全序**：槽序（数组）+ 槽内次序（`SLOT_MEMBER_ORDER`）+ 加法项（`ADDITIVE` 有序表）；**禁止**依赖 `set` / `dict` 的迭代顺序（今天 `special_options` 用 `in` 判定，天然无序 ⇒ 模型里必须显式排序） |
| **幂等** | 同一输入连续派生 N 次结果逐字相同；派生**不写任何状态**（例外只读） |
| **唯一性** | 同一工序**恰好出现一次**（沿用 issue #4577 用户裁定「工序需要保证唯一」的**取代**语义：后到者替换前者的位置） |
| **可解释** | 每条工序带 `Reason`（§3.1）⇒ #4650 阶段 3 的解释**来自结构化理由**，AI 只措辞 |

### 3.6 顺序敏感点（**哪些相邻关系不能变**）

| # | 不能变的相邻关系 | 为什么 | 判据 |
|---|---|---|---|
| S1 | `精裁` < `三边` | 物理（§2.1） | 偏序断言 |
| S2 | `三边` < `韩褶`/`打孔`/`穿杆` | 物理（§2.1） | 偏序断言 |
| S3 | `韩褶`/`打孔` < `上车布` | 物理（§2.1） | 偏序断言 |
| S4 | `上车布` < `熨烫`/`定型` | 物理（§2.1） | 偏序断言 |
| S5 | `定型` < `复烫` | 流程（§2.2） | 槽内次序断言 |
| S6 | `复烫` < `车被` | 物理（§2.1） | 偏序断言 |
| S7 | `车被` < `外帘打卷` < `打包` < `外帘装袋` < `外帘发货` | 物理 + V79 现状 | 偏序 + 槽内次序断言 |
| S8 | `接高` 在 `精裁` 之后、`三边` 之前 | 今天锚 `精裁` ⇒ 位置固定 | 槽内次序断言（裁剪槽） |
| S9 | `绑带` 在 `车被` 之后 | 今天锚 `车被` | 槽内次序断言（车底槽） |
| S10 | `抱枕` 在 `外帘打卷` 之后 | 今天锚 `外帘打卷` | 加法项 `after_slot` 断言 |

**⚠️ 一处会**变**的顺序（必须显式裁定，不许静默改）**：
今天 `打孔`（priority 30）**早于** `上车布`（priority 40）⇒ 序列是 `三边 → 打孔 → 上车布`；
槽位模型里 `上车布` 在**挂钩槽**（第 4 槽）而 `打孔` 在**打褶槽**（第 3 槽）⇒ 也是 `打孔 → 上车布` ✅ **一致**。
但 `四爪钩` 下今天 `上车布` 锚 `三边`（priority 40，而 `三边` 是主线第 2 道）⇒ 序列是 `三边 → 上车布 → … → 韩褶`（若有）；
槽位模型把它放在**挂钩槽** ⇒ `三边 → [打褶槽] → 上车布`。**两者在"无打褶工艺"时位置相同**（`三边` 后紧接 `上车布`）✅；
**在有打褶工艺时不同**（今天 `四爪钩` 与 `韩褶` 不同时出现，因为工艺单值 ⇒ **实际不可达**）。
⇒ 结论：**该差异不可达**（工艺单值）⇒ **不构成行为变化**（登记为 §8 A10 供复核）。

---

## 4. 版本化与「历史不动」（红线）

### 4.1 出厂知识版本化

| 对象 | 载体 | 版本语义 |
|---|---|---|
| 出厂知识（L1 槽序 + L2 映射 + L3 槽内次序） | 一张**版本化的知识表**（或代码常量 + `knowledge_version` 整数） | **整数单调递增**；每次改出厂默认 ⇒ +1 |
| 租户例外（L4） | 租户级覆盖行 | 无版本（是"偏离量"，不是"知识"） |
| 实例快照（L5） | `processing_position_operations` 的现有行 | **无版本、永不回填** |

**升级只影响新单**的机制（结构性论证，不靠纪律）：

1. 派生**只在实例化时**发生一次（生成加工单 ⇒ 写 `processing_position_operations` 行）；
2. 实例行里已有 `unit_price`（快照价）、`qty`（算料输出）、`operation_name`、`seq` ⇒ **历史单的工序清单与工资口径不依赖知识表**；
3. 报工/计件读的是**实例行**（`production_work_logs` 指向 `operation_id` = 实例 id），**不重放派生**；
4. ⇒ 改出厂知识**物理上无法**影响历史单（没有读路径）。**这是"历史不动"的机制，不是承诺。**

**⚠️ 与 `docs/design/operation-name-unification.md` §3 红线的口径一致**：那条红线禁的是
「回溯改 `processing_position_operations.operation_name` / `production_work_logs.operation_name`」——
**本文不碰**（不写回填、不做名字统一；名字统一是另一单的事）。

### 4.2 加工单要不要记「当时用的知识版本」？

**结论：要记，且是"只加一列"，不是"重放机制"。**

| 问题 | 结论 |
|---|---|
| 记什么 | 加工单上记 **①知识版本号 + ②路线模板 id**（`route_template_id` 今天只在**返回体**里，**没落库**：`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1290` `route_template_id` 只在返回体里（`route.put("route_template_id", …)`）；而 `processing_orders` 表只有 `route_key`/`route_requested_key`/`route_source` 三列 —— 见 `backend/admin-api/src/main/resources/db/migration/V60__create_routing_customization_tables.sql:118` `route_key`（**实测无 `route_template_id` 列**）） |
| 为什么记 | ① **诊断**：商家问「这张单为什么没有定型」时，必须知道**当时**的出厂知识（否则今天改了知识就解释不了昨天）；② **#4650 阶段 3** 的"解释"要引真值源（**不许编造**）—— 没有版本号就只能用今天的知识解释昨天的单（**错**）；③ **审计**：加工单是工资凭证 |
| 与快照的关系 | **互补，不是替代**。快照（实例行）= **结果**（当时排了什么、什么价、多少量）；版本号 = **依据**（当时的知识长什么样）。**只有快照没有版本号** ⇒ 知道"排了 A 没排 B"但说不出"为什么"；**只有版本号没有快照** ⇒ 要重放才能知道结果（**危险**：重放可能因例外/数据变化而与当时不同） |
| **不做什么** | **不**用版本号做"重放/重算"（历史单**不重放**）；**不**给历史单回填版本号（回填 = 猜测，`NULL` 是诚实值）；**不**把版本号写进 `production_work_logs`（报工明细不可变，见 `backend/admin-api/src/main/resources/db/migration/V49__create_production_operations_and_work_logs.sql:100` `production_work_logs` 的表注释「报工记录（明细不可变）」） |

⇒ **实现口径**：`processing_orders` 加 `knowledge_version INT`（**可空**，历史行为 `NULL`）
+ `route_template_id VARCHAR(64)`（**可空**，历史行为 `NULL`）。**两列都是"新单才有值"**，
`NULL` 的语义 = 「该单生成时本列还不存在」——**如实登记，不猜**。

---

## 5. 迁移映射（逐条，不猜）

### 5.1 映射口径

把今天**全部 29 条**（`ROUTE_RULES` 26 + `V84` 3）逐条映射到槽位模型。**判定三态**：

- **✅ 可映射**：槽位模型能推出同一位置（或位置差异**实际不可达**）；
- **⚠️ 待裁定**：模型推不出 / 需要业务裁定 / 涉及过时形态的处置选择 —— **列出，不猜、不静默丢**。

### 5.2 `ROUTE_RULES` 26 条（21 `insert` + 5 `remove`）

| # | `trigger_kind` | `trigger_value` | `action` | `operation` | `after_operation` | `priority` | 槽位模型映射 | 判定 |
|---|---|---|---|---|---|---|---|---|
| 1 | craft | 韩褶 | insert | 韩褶 | 三边 | 10 | 打褶槽（占槽） | ✅ |
| 2 | craft | 韩褶 | insert | 上车布 | 韩褶 | 20 | 挂钩槽 | ✅ |
| 3 | craft | 打孔 | insert | 打孔 | 三边 | 30 | 打褶槽（占槽） | ✅ |
| 4 | craft | 四爪钩 | insert | 上车布 | 三边 | 40 | 挂钩槽 | ✅（过时形态，§5.3 P1） |
| 5 | craft | 四爪钩 | remove | 定型 | — | 50 | 蒸烫槽**不成立** | ✅（同上） |
| 6 | craft | 四爪钩 | remove | 复烫 | — | 60 | 复烫槽**不成立** | ✅（同上） |
| 7 | craft | 穿杆 | remove | 定型 | — | 70 | 蒸烫槽**不成立** | ✅ |
| 8 | craft | 穿杆 | remove | 复烫 | — | 80 | 复烫槽**不成立** | ✅ |
| 9 | craft | 平幔 | insert | 帘头制作 | 三边 | 90 | 边缘槽 | ✅ |
| 10 | craft | 平幔 | remove | 复烫 | — | 100 | 复烫槽**不成立** | ✅ |
| 11 | option | 拼1次 | insert | 拼1次 | 三边 | 110 | 边缘槽 | ✅ |
| 12 | option | 拼2次 | insert | 拼2次 | 三边 | 120 | 边缘槽 | ✅ |
| 13 | option | 拼3次 | insert | 拼3次 | 三边 | 130 | 边缘槽 | ✅ |
| 14 | option | 加花边 | insert | 花边 | 三边 | 140 | 边缘槽（**装饰加法**，归属待裁定） | ⚠️ **A2** |
| 15 | option | 加铅块 | insert | 铅坠 | 三边 | 150 | 边缘槽 | ✅ |
| 16 | option | 接高 | insert | 接高 | 精裁 | 160 | 裁剪槽 | ✅ |
| 17 | option | 双眼皮接高 | insert | 接高 | 精裁 | 170 | 裁剪槽 | ✅ |
| 18 | option | 余料做绑带 | insert | 绑带 | 车被 | 180 | 车底槽 | ✅ |
| 19 | option | 布绑带 | insert | 绑带 | 车被 | 190 | 车底槽 | ✅ |
| 20 | option | 余料做帘头 | insert | 帘头制作 | 三边 | 200 | 边缘槽 | ✅ |
| 21 | option | 抱枕 | insert | 抱枕 | 外帘打卷 | 210 | 加法槽（`after_slot=包装槽`） | ✅ |
| 22 | option | 纱绑带 | insert | 绑带 | 车被 | 220 | 车底槽 | ✅ |
| 23 | option | 加logo条 | insert | logo条 | 三边 | 230 | 边缘槽 | ✅ |
| 24 | option | 加立边 | insert | 立边 | 三边 | 240 | 边缘槽 | ✅ |
| 25 | option | 扣环 | insert | 扣环 | 三边 | 250 | 边缘槽 | ✅ |
| 26 | option | 防翘扣 | insert | 防翘扣 | 三边 | 260 | 边缘槽 | ✅ |

**复现这张表的读数**：

```bash
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '708,763p'
# → 26 行（工艺 10 + 选项 16），字段顺序 trigger_kind/trigger_value/position/action/operation/after_operation/priority
```

### 5.3 `V84` 3 条（`processing_item`）+ 过时形态的显式处置

| # | `trigger_kind` | `trigger_value` | `action` | `operation` | `after_operation` | `priority` | 槽位模型映射 | 判定 |
|---|---|---|---|---|---|---|---|---|
| 27 | processing_item | 花边 | insert | 花边 | 三边 | 270 | 边缘槽（同 #14，**与选项 `加花边` 同落点**） | ⚠️ **A2** |
| 28 | processing_item | 扣环 | insert | 扣环 | 三边 | 280 | 边缘槽 | ✅ |
| 29 | processing_item | 接高 | insert | 接高 | 精裁 | 290 | 裁剪槽 | ✅ |

```bash
git show origin/main:backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql \
  | grep -nE "^\s*\('0[0-9]', 'processing_item'"
# → 3 行（花边/扣环/接高，priority 270/280/290）
```

#### ⚠️ 过时形态的**显式处置**（不许猜、不许静默丢）

`四爪钩` 今天有**三个身份**（§1.5 实测），槽位模型必须**逐条处置**：

| 身份 | 今天的载体 | 槽位模型里的处置 | 理由 |
|---|---|---|---|
| ① `order_items.craft='四爪钩'`（**历史值**） | 订单行 | **不动** | 历史数据；V63 已把**信号层**改指 `韩褶`（新单不再产生该值） |
| ② `production_route_rules` 的 3 条 `craft` 规则（**active**） | 规则表 | **映射成 `CRAFT_SLOT`/`CRAFT_NEGATES` 的"历史工艺"条目**（与 `穿杆` 同形：占打褶槽？**否** —— 它不占打褶槽，只是**挂钩槽成员** + 否定蒸烫/复烫） | `backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql:32` 明写「**保持 active，不得停用** —— 停用会让存量单重放时丢掉 上车布/定型/复烫 的处理」 |
| ③ `processing_items` 目录（**无 `四爪钩` 行**） | 加工项目录 | **不发明**（不加目录行） | `backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql:29` 明写「本迁移**不发明**它的目录行与路线行为（发明 = 把错误结构化）」 |

⇒ **结论（本文的处置建议，供裁定）**：
**`四爪钩` 在槽位模型里以「历史工艺（legacy craft）」身份保留一格**，与 `穿杆` 同形但**不占打褶槽**：

```
LEGACY_CRAFT = {
    "四爪钩": {"occupies": None,        # 不占打褶槽（它是配件，不是打褶方式）
               "extra_members": [("上车布", "挂钩槽")],
               "negates": ["蒸烫槽", "复烫槽"]},
}
```

**三条纪律**：① 该条目**只对 `craft='四爪钩'` 的历史单可达**（新单不产生该值 ⇒ 自然退场）；
② **不删**（删了存量单重放会丢工序，违反 V83 的明文纪律）；③ **不推广**（不把它写进「工艺清单」的
展示面，否则等于把配件当工艺）。

### 5.4 计数（本文的交付读数）

| 判定 | 条数 | 明细 |
|---|---|---|
| **✅ 可映射** | **25 / 29** | 26 条中 25 条 + V84 的 `扣环`/`接高` 2 条（其中 `四爪钩` 3 条按 §5.3 的 legacy 处置算可映射） |
| **⚠️ 待裁定** | **4 / 29** | **A2**（`花边` 的槽归属，含选项 `加花边` 与加工项 `花边` **两条**，因为落点必须一致）· **A4**（`四爪钩` 的 legacy 处置**选择**：保留 legacy 格 vs 别的形态）· **A3**（加工项目录缺 `四爪钩` 行 ⇒ 阶段 4 删表后"四爪钩"这条条件**没有落点**） |

> **⚠️ 计数口径（避免被读成"只剩 4 条就完事"）**：这里的 29 条**只是规则表**。
> 模型还欠 **4 处槽内次序**（§2.2）与 **1 处"移动槽"**（质检）—— 这些**不在 29 条里**
> （今天靠主线数组/priority 隐式承担），见 §8 A1/A5/A7/A8。

### 5.5 迁移与回滚草案

**迁移（阶段 4，本文只给草案）**：

> **⚠️ 第 0 步不是迁移**：见 §0.1 F5 / §7.4 —— **先把三份规则语义收敛成一份**，
> 否则「迁移到什么」没有唯一基准。

| 步 | 动作 | 幂等要求 |
|---|---|---|
| **M0** | **语义收敛**：三份实现（§0.1 F5）收敛成**一份**运行时语义（**独立可合并**，不动数据） | 收敛后两端对同一配置**逐字同结果**（§3.6 S1~S10） |
| M1 | 新增**槽位定义表**（`production_operation_slots`：`slot_key` / `slot_order` / `capacity` / `tenant_id`） | `CREATE TABLE IF NOT EXISTS` + `ON CONFLICT (id) DO NOTHING`（`MigrationRunner` 要求所有迁移可重复执行） |
| M2 | 新增**槽成员表**（`production_slot_members`：`slot_key` / `operation` / `member_order` / `source`） | 同上 |
| M3 | 新增**租户例外表**（`production_slot_overrides`） | 同上 |
| M4 | `processing_orders` 加 `knowledge_version` + `route_template_id`（**可空**，历史行 `NULL`） | `ADD COLUMN IF NOT EXISTS` |
| M5 | **规则表保留为只读投影**（不删表、不删行），标记 `deprecated`；派生引擎改读槽位表 | **不改行**（删表是阶段 4 的最后一步，见下） |
| M6 | 全量回归：对**全部存量加工单**用槽位引擎重放，与实例快照逐项比对 | 差异 ⇒ **停止**（见下） |

**回滚（草案）**：

| 步 | 动作 |
|---|---|
| R1 | 派生引擎切回读 `production_route_rules`（**规则表一字未动** ⇒ 切回即回滚） |
| **R1′** | ⚠️ **但"切回"≠"回到某个历史版本"** —— `production_route_rules` **零版本账**（§0.1 F6：`docs/sql/schema.sql:1239` 的 `production_routing_versions` 挂在**模板**上，不挂规则表）。⇒ 回滚的**唯一可用基准 = V71/V76/V84 的种子字面量**（`ROUTE_RULES` ≡ V71 的 26 行；V84 的 3 行在 `backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql`）＋**商家自建行的现值**（无历史，只能取当下）。**两条可选**：① 阶段 4 之前**先补规则版本账**（新迁移）；② 接受"回滚 = 用种子重建 + 商家自建行按当下值保留"，并把该限制**写进回滚演练的验收判据**（**本文推荐 ②**，因为 ① 会把本单范围扩到"给规则表加版本账"） |
| R2 | 新表**保留但不读**（`DROP` 留待确认零消费者后独立迁移 —— 与 `docs/design/operation-name-unification.md` §6 N2「软删不 DROP」同口径） |
| R3 | `processing_orders` 的两列**保留**（`NULL` 无害；`DROP COLUMN` 会挡住再回滚） |

**停止条件（出现任一条立即停并回滚）**：

| # | 停止条件 | 为什么是硬停 |
|---|---|---|
| H1 | M6 重放出现**任一**存量加工单的工序清单与实例快照**不一致**（除已裁定的例外） | 说明模型与今天不等价 ⇒ 继续 = 改历史工资口径 |
| H2 | 任一工序在重放里**出现两次**（唯一性破） | 违反 issue #4577 用户裁定「工序需要保证唯一」 |
| H3 | 出现**静默**行为（警告列表非空但流程继续） | 本文的立论就是"不许静默"（§1.3③）⇒ 静默 = 本单失败 |
| H4 | 租户例外**违反 L1 偏序**且未被 fail-closed 拒绝 | 例外机制失控 ⇒ 等于造了第二张规则表 |
| H5 | 两端（Python 真值源 / Java 实例化）派生结果**不一致** | 今天的双源裂缝（§3.4）不得被放大 |
| **H7** | **M0 未完成就进 M1** | 三份语义（§0.1 F5）没收敛 ⇒ 迁移到没有唯一基准的目标（**本单最硬的前置**） |
| **H8** | 回滚演练**假设**「能取回规则表的历史版本」 | 该能力**不存在**（§0.1 F6 / R1′）⇒ 演练必须在**没有历史版本**的前提下走通 |
| H6 | 商家面出现「原来能存的规则现在存不了」（回归） | 同 `docs/design/operation-name-unification.md` §5 P1 停止条件同款 |

---

## 6. 用**真实报工数据**校验（智能化闭环）

### 6.1 为什么报工数据能校验模型

报工数据是**唯一由车间实际行为产生的信号**（其余数据都是研发/商家配置的投影）。
模型错（多排/少排/排错位置）⇒ 车间会用**跳过、补做、乱序报工**来"纠正"它，而纠正的痕迹**留在报工表里**。

可用的两张表（实测列名）：

| 表 | 关键列 | 出处 |
|---|---|---|
| `processing_position_operations`（工序实例） | `processing_order_id` / `position_name` / `seq` / `operation_name` / `qty` / `status` / `done_qty` | `backend/admin-api/src/main/resources/db/migration/V49__create_production_operations_and_work_logs.sql:48` |
| `production_work_logs`（报工明细） | `processing_order_id` / `operation_id`（→ 实例 id） / `operation_name` / `qty` / `qualified_qty` / `work_type`（normal/rework/scrap） / `work_date` | 同文件 `:88` |

### 6.2 四个口径（**写口径，不写死 SQL**）

| # | 要什么 | 口径（判据） | 读数形态 |
|---|---|---|---|
| **Q1 跳过** | 哪些**应做**的工序**零报工** | `实例.status='pending'` ∧ `done_qty=0` ∧ 该实例**无** `production_work_logs` 行 ∧ 该加工单**已 `completed`** | 按 `(tenant_id, position_name, operation_name)` 聚合计数 |
| **Q2 额外加** | 哪些工序**有报工**但**派生不出** | 实例里存在的 `operation_name` ∉ 该单配置的派生结果（按 `route_key`/快照反推配置） | 逐单差异清单 |
| **Q3 顺序倒置** | 哪些相邻工序的**首次报工时间**与模型顺序相反 | 同一 `processing_order_id` + `position_name` 内，按 `min(work_logs.created_at)` 排序，与实例 `seq` 比较 ⇒ 逆序对 | 逆序对计数 + Top N 例 |
| **Q4 返工热点** | 哪些工序 `work_type='rework'` 占比高 | `rework 数 / 该工序总报工数`，按工序聚合 | 占比排名 |

**口径纪律（三条）**：
1. **Q1 的"已完工"过滤不可省** —— 在产单的 `pending` 是**正常**的，把它算成"跳过"会得到假信号；
2. **Q3 只看"首次报工"**（`min(created_at)`）—— 返工/补报会打乱时序，用"最后一次"会把返工读成倒置；
3. **分母要写清**（按"加工单×部位×工序"还是按"加工单×工序"）—— 两者结论不同，**不许混用**。

### 6.3 发现偏差后怎么办（谁裁定、如何版本化）

| 偏差形态 | 候选归因 | 处置 |
|---|---|---|
| **Q1** 某工序在**多租户**都零报工 | 模型**多排**了（或该工序在行业里已被淘汰） | 进**待裁定清单**（业务裁定）⇒ 裁"改出厂知识"（L3，版本 +1）或"该租户例外"（L4） |
| **Q1** 某工序在**单租户**零报工 | 该租户**不做**这道活 | **租户例外**（L4：`slot_disabled`），**不改出厂知识** |
| **Q2** 额外加的工序集中在某租户 | 商家自建工序（**正常**，不是缺陷） | 建成**该租户的槽成员**（L4）；**不**提升为出厂默认 |
| **Q2** 额外加的工序**跨多租户** | 出厂知识**缺**一道 | 业务裁定 ⇒ 改出厂知识（L3，版本 +1） |
| **Q3** 逆序对集中在某**相邻对** | 模型的**槽内次序**错（L3） | 业务裁定 ⇒ 改 `SLOT_MEMBER_ORDER`（版本 +1）；**若涉及 L1 偏序 ⇒ 先复核物理论证**（§2.1） |
| **Q4** 某工序返工率异常高 | 可能**顺序**问题（前道没干完就报后道） | 先查 Q3；顺序正常 ⇒ 归因**工艺/设备**，**不改模型**（如实登记，不硬塞进模型） |

**谁裁定**：业务/客户（用户裁定，逐字 = #4650 的用户原话「**AI 只建议、不静默改**」）
⇒ 研发**不猜**；系统只产出**候选清单 + 证据**。

**如何版本化**：

```
Q1/Q2/Q3 发现偏差
  → 生成「模型修正候选」（含证据：租户/部位/工序/计数/时间窗）
  → 业务裁定（三选一）：改出厂知识 / 建租户例外 / 不改（登记理由）
  → 改出厂知识 ⇒ knowledge_version + 1（**只影响新单**，§4.1）
  → 建租户例外 ⇒ 写 L4 行（**不动**版本号）
  → 复查：下一周期的 Q1~Q4 指标应改善（**否则该次修正无效 ⇒ 回滚该次版本**）
```

**闭环频率（建议）**：**按周**跑一次（不接定时 LLM；Q1~Q4 是**确定性 SQL**，零 token）；
**每次出厂知识版本变更后**必跑一次（判据：偏差**只减不增**）。

---

## 7. 与 #4650 四阶段的关系（把本模型嵌进去）

| 阶段 | 内容 | 与本模型的关系 | 本单动工？ |
|---|---|---|---|
| **1** | 概念从界面消失：删独立规则表；条件**呈现 + 编辑**挂到**工序**；底层仍读同一张 `production_route_rules` | **不受影响**（零迁移、零数据变化）—— 阶段 1 只是把**同一张表的投影**换个挂载点 | ❌（#4650 的事） |
| **2** | AI 对话式改条件：说一句 → AI 结构化建议 + 人话解释 → 确认卡 → 复用现有规则写面落库 | **语义必须建立在槽位/派生上**（见下） | ❌（已登记 **#4652**） |
| **3** | AI 解释：工序清单可展开「为什么」（解释来自**后端结构化理由**，AI 只措辞） | **解释文案的语义必须换**（见下） | ❌（已登记 **#4652**） |
| **4** | 承载收敛：条件落到工序侧 + 迁移与回滚 + 删表/删端点/删守卫 | **按本模型改**（见下） | 本文 = 阶段 4 的设计依据 |

### 7.1 阶段 2/3 的语义要求（**不许用锚点语义解释**）

| 场景 | ❌ 错（今天能写出来的） | ✅ 对（槽位语义） |
|---|---|---|
| 解释「为什么加了 `上车布`」 | 「锚点在 `韩褶` 之后」 | 「因为选了**韩褶** ⇒ **打褶槽**由 `韩褶` 占据 ⇒ `上车布` 排在**它之后**」 |
| 解释「为什么没有 `定型`」 | 「`四爪钩` 规则 remove 了定型」 | 「因为选了**穿杆** ⇒ **蒸烫槽不成立** ⇒ `定型` 不排」 |
| 解释「为什么 `抱枕` 在最后」 | 「锚点在 `外帘打卷` 之后」 | 「`抱枕` 是**加法项**，挂在**包装槽之后**」 |
| AI 建议「我们家的四爪钩不做复烫」 | 生成一条 `remove` 规则（带锚点？没有锚点） | 生成**租户例外**：`{槽: 复烫槽, 工艺: 四爪钩, 成立: false}` |

**为什么这不只是措辞问题**：阶段 2 的 AI 要**生成结构化建议**（不是只生成文案）。
若建议的载体是"规则 + 锚点"，AI 就必须**替商家想锚点** ⇒ 把 §1.3 的三条代价**交给 LLM 承担**
（LLM 会猜、会漂、错了不报错）。若载体是"槽 + 布尔"，AI 只需回答**一个封闭问题**
（"占哪个槽 / 该槽成立吗"）⇒ **可校验、可确认卡、可撤销**。

### 7.2 阶段 4 要改什么（**不是把 29 行搬到工序上**）

| ❌ 不是 | ✅ 是 |
|---|---|
| 把 26+3 行规则**搬到工序表**（每道工序带 `trigger_kind/trigger_value/action/after_operation`） | **槽位模型（L1/L2）+ 派生引擎 + 出厂默认（版本化）+ 租户例外（L4）** |
| 保留 `after_operation` 列（#4650 原文「必须多带一列「插入锚点」」） | **`after_operation` 消失**；位置由槽序推出；**只有加法项保留 `after_slot`**（指向**槽**，不是工序） |
| 每道工序各自声明条件（N 道工序 = N 份配置） | **工艺/选项声明占哪个槽**（29 行 ⇒ 约 20 条映射 + 4 处槽内次序 + 9 槽偏序） |

**#4650 原文「锚点随条件一起搬（技术必需项）」的处置**：
那条结论建立在「**载体 = 工序侧的条件**」这个前提上（`docs/design/operation-name-unification.md` §7.3 的实测：
「`上车布` 在 `韩褶` 下锚在 `韩褶` 后、在 `四爪钩` 下锚在 `三边` 后」⇒ 必须多带一列锚点）。
**本模型换掉了那个前提**：位置不再由"条件的载体"携带，而由**槽序**推出 ⇒
**锚点不是"搬"，是"派生"**（这正是用户裁定的第 2 条）。
⇒ 阶段 4 的验收判据应改为「**同一配置下派生结果与今天逐项一致**（§5.5 M6 / §3.6 的 S1~S10）」，
而不是「锚点列已搬迁」。

### 7.3 阶段 4 里**未定义**的一件事（待裁定 A11）

今天 `production_route_rules` 里**既有出厂种子（26+3 条）**，也可能有**商家自建规则**
（写面 = `ProductionRoutingCommandService`，`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java:386` 起 `action` ∈ `insert`/`remove` 的校验）。
**出厂种子可以迁到槽位模型；商家自建规则迁到哪？**（它们是"例外"，但形态是 `(trigger, operation, anchor)` 三元组，
与 L4 的"槽覆盖"不同构）⇒ **本文列为待裁定 A11**，阶段 4 开工前必须裁掉。

### 7.4 阶段 4 的**第一步**是「语义收敛」，不是迁移（本文的判断与理由）

另一份设计（`docs/design/ai-craft-config.md`）建议的编排是
**阶段 1（已合并）→ 阶段 3（可解释，含 `reason`）→ 阶段 2（AI 对话式）→ 阶段 4（承载收敛）**，
并主张「阶段 4 第一步不是迁移，而是**把三份规则语义收敛成一份**」。

**本文的判断（逐分项）**：

| 分项 | 本文结论 | 理由 |
|---|---|---|
| **阶段 3 先于阶段 2** | ✅ **同意** | 确认卡要显示「将发生的变化」，其**可信来源**只能是**后端结构化理由**（#4650 明文「解释必须来自真值源…AI 不许编造」）。阶段 2 若先落地，确认卡只能显示 AI 自己生成的文案 ⇒ **自己给自己出题**（无可校验的真值）。本文 §3.1 的 `Reason` 就是给阶段 3 用的载体 |
| **阶段 4 第一步 = 语义收敛** | ✅ **同意，且本文给出更硬的理由** | §0.1 F5：今天有**两份 Java 实现**在生产路径上（`:1125` 的 `buildRoute` 与 `:556` 的 `insertConditionalOperations`）。派生算法只能对齐**一个**运行时行为 ⇒ **收敛前迁移 = 迁移到没有唯一基准的目标**。本文 §5.5 已落成 **M0**，并加停止条件 **H7**（M0 未完成就进 M1 ⇒ 停） |
| 「阶段 4 必须多带一列「插入锚点」」（#4650 原文） | ❌ **不同意**（§7.2 已论证） | 该结论建立在「载体 = 工序侧的条件」这个前提上；本模型换掉了那个前提（位置由**槽序**推出）⇒ 锚点**派生**而非搬运。**前提变了，结论随之改判** |
| 阶段 2/3 的**语义** | ⚠️ **本文补充一条硬要求** | 解释/建议**必须建立在槽位/派生语义上**（§7.1 的四行对照）—— 沿用锚点语义等于把 §1.3 的三条代价**交给 LLM 承担** |

**分工与冲突处理**：**阶段编排的权威在 `docs/design/ai-craft-config.md`**（AI 层设计）；
本文只对「槽位/派生语义」这一层给判据。**两者冲突时以本文 §7.1/§7.2 的语义要求为准**，
并回改 `ai-craft-config.md`（**本文不代改**：它是另一单的交付物；本单 docs-only、只新增 1 个文件）。

---

## 8. 不做什么 / 无法判定项 / 与假设不符的事实

### 8.1 明确**不做**（以及为什么）

| # | 不做 | 为什么 |
|---|---|---|
| N1 | **不改任何生产代码/数据/迁移/守卫** | 本单是**设计单**（issue 交付物只有 1 个 md） |
| N2 | **不碰 ai-agent**（不改 prompt/Tool/交互卡/评测用例） | 用户裁定：本会话不动 agent（阶段 2/3 已登记 #4652） |
| N3 | **不改 `.github/workflows/**` 与 `.agent-presets/**`** | 仓库红线（本机 token 无 `workflow` scope） |
| N4 | **不跑真实 LLM 评测、不派发 workflow** | 用户裁定 #4262（「不要自动进行验证」） |
| N5 | **不回溯历史快照**（不改 `processing_position_operations.operation_name` / `production_work_logs.*`） | 工资凭证（`V49` 表注释「报工记录（明细不可变）」；`docs/design/operation-name-unification.md` §3 红线） |
| N6 | **不发明业务**（不给"花边占哪槽"下结论、不给"质检是否必做"下结论） | 与「不发明单价」（`backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:228` 列注释）同一条纪律 |
| N7 | **不物理删 `production_route_rules`** | 它是回滚路径（§5.5 R1）；删表是阶段 4 的最后一步 |
| N8 | **不在 `docs/wiki/INDEX.md` 加索引行** | 实测该索引 `docs/design/` 条目数 = **0**（`git show origin/main:docs/wiki/INDEX.md \| grep -c "docs/design/"` → `0`）⇒ 加一行是**新造约定**（与 `docs/design/operation-name-unification.md` §6 N9 同款判断） |
| N9 | **不改主线的槽内顺序**（含 `打包` 位置） | `V79` 自陈「按 ERP 顺序推断、**待客户确认**」⇒ 借本单改顺序 = 静默改工资 |
| N10 | **不做"每道工序一个槽"的细粒度建模** | 槽位是**物理阶段**（9 个），不是工序的别名；细到工序 = 把锚点藏进数组下标（§2.2） |

### 8.2 无法判定项（**不许猜**）

| # | 项 | 为什么判不了 | 需要谁 |
|---|---|---|---|
| **A1** | `熨烫` 与 `定型` 的**先后**、以及 `定型` 是否**必做** | 矩阵里 `熨烫 × 帘头 = 不适用` 而 `定型 × 帘头 = 适用` ⇒ 帘头**只定型不熨烫**，但「定型前要不要先熨烫」在库里**无数据** | 业务（真值源 §3 只说定型「联动…质检/包装」） |
| **A2** | `花边`（选项 `加花边` + 加工项 `花边`）**占哪个槽** | 今天锚 `三边`（表面在边缘槽），但"花边"是**装饰加法**（不是边缘处理）⇒ 边缘槽 vs 独立加法槽 | 业务 |
| **A3** | 阶段 4 删表后，「`四爪钩`」这条**条件**落在哪（目录里没有它、工艺清单里也不该有它） | 它今天靠"规则表里一个 key"活着；表没了，key 就没有载体 | 业务 + #4365 阶段 2 |
| **A4** | `四爪钩` 的 legacy 处置**形态**（本文建议"保留 legacy craft 格"，但是否接受） | 三种身份并存（§1.5），选哪种是产品决定 | 业务 |
| **A5** | `质检` 是否**每单必做**、挂在哪 | `routing.py::PENDING_CUSTOMER_CONFIRMATION_OPERATIONS` 已挂起它；真值源 §8 只说定型「联动…质检/包装」 | 客户（#4261 同族） |
| **A6** | `腰靠垫` 属**另一产品**还是**某选项的产物** | 同 `PENDING_CUSTOMER_CONFIRMATION_OPERATIONS`；且今天**无规则行**（只有 `_POSITION_PRICE_ROWS` 里的价目行） | 客户（#4261 同族） |
| **A7** | `平幔` 与 `帘头制作` 的**关系** | `平幔` 是工艺（占边缘槽的 `帘头制作`），但 `帘头制作` 也可由选项 `余料做帘头` 触发 ⇒ 两者是否**同一道活**、`平幔` 单是否**额外**做 | 业务 |
| **A8** | `打包` 与 `外帘打卷`/`外帘装袋` 的**顺序** | `V79` 自陈「#4343 登记过这两道的对应关系**未能确定**」⇒ 按 ERP 推断 | 客户 |
| **A9** | 两端 tie-break 不一致（Python 声明顺序 vs Java `id`）**是否构成实际缺陷** | 静态可判"实现不同"，但**是否有实际输入触发**需要真库数据 | 真库（§6 的 Q1~Q4 可覆盖） |
| **A10** | §3.6 登记的"`四爪钩` 下位置差异"**是否真的不可达** | 依赖"工艺单值"这一前提；若商家面出现多工艺（今天没有），结论翻转 | 复核（阶段 4 开工前） |
| **A11** | **商家自建规则**（非出厂种子）迁到槽位模型的哪一层 | 形态是 `(trigger, operation, anchor)`，与 L4 的"槽覆盖"不同构 | 产品 + 阶段 4 设计 |
| **A12** | 布料（`配料`/`打包`）的**槽归属**（`配料` 在裁剪槽？`打包` 在包装槽？） | 布料是**第 4 部位**（issue #4529），其槽位语义**从未定义**（只定义了主线 2 道） | 业务 |
| **A13** | **罗马帘**整套工序（真值源 §3 列了它，工序库里一道都没有） | 能力缺口（`docs/design/craft-routing-customization.md` §2 已登记） | 客户 |

### 8.3 与假设不符的事实（逐条照实登记）

| # | 假设（issue #4653 原文 / 母单 #4650） | 实测 | 处置 |
|---|---|---|---|
| **F1** | 主线是 **9 道**扁平骨架 | V71/V76 落库 **9 道**，但 `routing.py::ROUTE_MAINLINE_STEPS` 今天是 **10 道**（V79 加了 `打包`） | §1.1 按 10 读；「不含工艺槽位」结论不变 |
| **F2** | 「29 行清单」= 26 + 3 | ✅ 一致（`ROUTE_RULES` 26 + `V84` 3 = 29）；`docs/sql/schema.sql` 里同名种子行数也是 **29** | 无差异 |
| **F3** | `四爪钩` V63 起**不再作独立路线键** | ✅ 一致（`V63` 改信号指向；`V83` 不发明目录行）；**但**规则表里那 3 条 `craft` 规则**仍 active**（`V83:32` 明文要求不得停用） | §5.3 P1 显式处置 |
| **F4** | 「锚点随条件一起搬」是阶段 4 的**技术必需项** | ⚠️ **前提已被本模型换掉**：位置可由槽序推出 ⇒ 锚点**派生**而非搬运（用户裁定第 2 条） | §7.2 改判 |
| **F5** | 同一工序在不同条件下锚点不同（`上车布`：`韩褶` 后 / `三边` 后） | ✅ 一致（`ROUTE_RULES` priority 20 vs 40） | §1.3 代价② |
| **F6** | 锚点写错会**静默**出错 | ✅ 一致，且**两端各自独立实现同一静默语义**（Python `_insert_after` + Java `insertAfterLogical`） | §1.3 代价③ |
| **F7** | — | ⚠️ `priority` 的两端 tie-break **不同**（Python 稳定排序靠声明顺序 / Java 按 `id` 兜底）⇒ 双源裂缝 | §3.4 + §8 A9 |
| **F8** | — | ⚠️ 加工单**不记** `route_template_id`（只在返回体里，`processing_orders` 无该列）⇒ "这张单走了哪条模板"**无数据可查** | §4.2（本文建议加列） |
| **F9** | — | ⚠️ `production_route_rules` 里还有 **`action='factor'`** 档（V72/V76 从 `production_option_factors` 搬入），#4589 起已软删、零消费者 | **不在 29 条内**（29 条 = `insert`/`remove`）；阶段 4 删表时要**一并确认**它已零消费者 |
| **F10** | — | ⚠️ `质检` 是 `ROUTE_MAINLINE`（**仅文档用途、不落库**）的占位，**无规则行、无矩阵价**以外的载体 | §2.1 ★ / A5 |
| **F11** | — | ⚠️ 真值源里**已有**槽位语义（`ROUTE_MAINLINE` 第 3 位字面量 `⟪工艺槽位⟫` + `V71:228` 的列注释定义），但它**没有消费方**（`git grep "ROUTE_MAINLINE\b"` 只命中定义行）⇒ **槽位语义只活在注释里**，落库时被扁平化掉 | **§1.0**：本设计的定性 = **恢复**而非引入；引用面 **12 处**、可枚举 |
| **F12** | — | ⚠️ `backend/admin-api/src/test/java/com/migao/admin/service/RoutingModelFixture.java:48` `mainline` 注释写「9 道」，其 `mainline()` 实际返回 **10 道** | 同族数字腐烂；**不在本单修**（测试文件） |
| **F13** | （隐含）`routing.py::ROUTE_RULES` 是**运行时**真值源 | ⚠️ **它是设计真值源 / 种子**；Java 侧 4 处 `ROUTE_RULES` 命中**全是注释**，运行时读的是**库表** `production_route_rules`（`ProcessingOrderService.java:796` `insertConditionalOperations`） | **§0.1 F4**：本文 §5 的 29 条**同时覆盖**两份（`V84` 3 条只在库表） |
| **F14** | （隐含）规则语义只有一份实现；且「`buildRoute` 不去重」 | ⚠️ **三份实现**（`build_route_v2` / `buildRoute` / `insertConditionalOperations`）；**但「不去重」不成立** —— `buildRoute` 经 `insertAfterLogical` 的 `route.removeIf`（`:1325`）**去重**，`build_route_v2` 的 `_insert_after` **也去重**（`backend/ai-agent-service/app/production/routing.py` 的 `_insert_after`）⇒ **三份都做「取代」**；真实差异在**载体 / 触发键 / 过滤时机**，外加 `buildRoute` docstring 自称「唯一 Java 实现」**与实测不符** | **§0.1 F5**（含反证）；阶段 4 **M0 = 语义收敛**、停止条件 **H7** |
| **F15** | （隐含）回滚能回到某个历史版本的规则表 | ⚠️ `production_route_rules` **零版本账**（`production_routing_versions` 挂在**模板**上，`docs/sql/schema.sql:1239`） | **§0.1 F6 / §5.5 R1′**：回滚基准 = V71/V76/V84 的**种子字面量** + 商家自建行的**当下值**；停止条件 **H8** |

---

## 附录 A：所有实测命令与数字（可复现）

> 基准：`origin/main` @ `4a8e23bf4`（`git rev-parse origin/main`）。所有命令在仓库根执行，
> 一律用 `git show origin/main:<path>` / `git grep … origin/main`（**不读本地工作区**）。

### A.1 主线与骨架

```bash
# ① 落库主线（V71 种子，9 道）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | sed -n '234,235p'
# → '["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"]'::jsonb,

# ② 「不含工艺槽位」两处逐字
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | sed -n '34p'
git show origin/main:backend/admin-api/src/main/resources/db/migration/V76__redo_v72_with_sort_order_fix.sql | sed -n '179p'

# ③ 今天代码里的主线（10 道，含 打包）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '470,483p'

# ④ 「工艺槽位」占位（仅文档用途、不落库）
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -n "工艺槽位"
```

### A.1b **§1.0 的既有语义证据**（槽位不是新概念）

```bash
# ① 真值源里的字面量槽位（第 3 位）+ 它的语义定义
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '469,472p'
# → #: 主线**全貌**（含「工艺槽位」占位）—— 仅文档用途，**不落库**
# → #: （槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入）
# → ROUTE_MAINLINE: List[str] = ["精裁", "三边", "⟪工艺槽位⟫", "熨烫", "定型", "复烫",
# →                              "车被", "外帘打卷", "打包", "外帘装袋", "外帘发货"]

# ② 落库的主线不含槽位（紧邻下一段）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '474,481p'   # ROUTE_MAINLINE_STEPS 在 :480

# ③ 落库侧的列注释把槽位定义写成了明文
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | sed -n '228p'
# → '「工艺槽位」不落库（它只表示「打褶那一道插在这里」，由规则表按工艺插入）。';

# ④ ROUTE_MAINLINE（含槽位的那份）**无消费方** —— 只命中它自己的定义行
git grep -n "ROUTE_MAINLINE\b" origin/main
# → 1 行（backend/ai-agent-service/app/production/routing.py:471）

# ⑤ 「工艺槽位」字面量全仓 12 处（§1.0 的表逐条判定）
git grep -n "工艺槽位" origin/main | wc -l
# → 12
git grep -n "工艺槽位" origin/main
```

### A.2 规则表 29 条

```bash
# ① ROUTE_RULES 26 条（工艺 10 + 选项 16；insert 21 / remove 5）
python3 - <<'PY'
import re, collections
src = open('backend/ai-agent-service/app/production/routing.py', encoding='utf-8').read()
i = src.index('ROUTE_RULES: List'); seg = src[i:]; seg = seg[:seg.index('\n]')+2]
rows = re.findall(r'"trigger_kind":\s*"([^"]+)".*?"action":\s*"([^"]+)"', seg, re.S)
print(len(rows), dict(collections.Counter(k for k,_ in rows)), dict(collections.Counter(a for _,a in rows)))
PY
# → 26 {'craft': 10, 'option': 16} {'insert': 21, 'remove': 5}

# ② V71 种子 26 行 / V76 回填 26 行 / V84 加工项 3 行
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | grep -cE "^\s*\('rr-v70-"
git show origin/main:backend/admin-api/src/main/resources/db/migration/V76__redo_v72_with_sort_order_fix.sql | sed -n '220,256p' | grep -cE "^\s*\('[0-9]{2}', '"
git show origin/main:backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql | grep -cE "^\s*\('0[0-9]', 'processing_item'"
# → 26 / 26 / 3

# ③ bootstrap 同步（schema.sql 里同名种子 29 行）
git show origin/main:docs/sql/schema.sql | grep -cE "'rr-v7[0-9]|'rr-v84"
# → 29
```

### A.3 锚点的三代价

```bash
# ① 上车布两个锚点
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -n '"operation": "上车布"'
# → priority 20（after 韩褶）与 priority 40（after 三边）

# ② 「锚点找不到 ⇒ 追加末尾」四处（Python ×2 / Java ×2）
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -n "追加末尾"
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java | grep -n "追加末尾"
# → backend/ai-agent-service/app/production/routing.py:355,792 / backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1155,1315

# ③ 顺序敏感的判据（测试）
git show origin/main:backend/ai-agent-service/tests/test_production/test_route_model_v2.py | sed -n '439,442p'
```

### A.4 部位矩阵与适用性

```bash
# ① 矩阵 120 行（30 逻辑工序 × 4 部位）
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -cE '^\s+\("(精裁|裁剪|三边|韩褶|上车布|打孔|拼1次|拼2次|拼3次|花边|铅坠|接高|帘头制作|熨烫|定型|复烫|车被|外帘打卷|外帘装袋|质检|外帘发货|绑带|抱枕|腰靠垫|logo条|立边|扣环|防翘扣|配料|打包)", "(布帘|纱帘|帘头|布料)",'
# → 120

# ② 与直觉不符的两处（定型 × 帘头 适用 / 熨烫 × 帘头 不适用）
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -nE '\("(定型|熨烫)", "帘头"'
```

### A.5 旧模型与过时形态

```bash
# ① 旧模型 9 条路线（V54 6 条 + V58 3 条）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql | grep -cE "^\s*\('rt-v54-"
git show origin/main:backend/admin-api/src/main/resources/db/migration/V58__seed_sheer_curtain_routings.sql | grep -cE "^\s*\('rt-v58-"
# → 6 / 3

# ② 笛卡尔积 ⇒ 改一道工序要改 8 遍（真值源 header 自陈）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '428,432p'

# ③ 四爪钩三身份
git show origin/main:backend/admin-api/src/main/resources/db/migration/V63__structure_order_line_craft_spec.sql | sed -n '24,27p;59p'
git show origin/main:backend/admin-api/src/main/resources/db/migration/V83__seed_processing_item_catalog.sql | sed -n '27,32p'
git show origin/main:backend/admin-api/src/main/resources/db/migration/V60__create_routing_customization_tables.sql | grep -n "四爪钩"
```

### A.6 版本化与历史不动

```bash
# ① 实例快照表（工序实例 + 报工明细，列名与"不可变"注释）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V49__create_production_operations_and_work_logs.sql | sed -n '48,88p'

# ② 加工单表无 route_template_id（只有 route_key/route_requested_key/route_source）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V60__create_routing_customization_tables.sql | sed -n '118,126p'
git grep -n "route_template_id" origin/main -- 'backend/admin-api/src/main/resources/db/migration/' 'docs/sql/schema.sql'
# → 无输出（只在返回体里：backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1290）

# ③ 路线变更账（V85 起挂到新模板表）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V85__fix_routing_version_ledger_shape.sql | sed -n '1,12p'

# ④ 已挂起项（质检/腰靠垫/裁剪-布/裁剪-纱）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '119p;199p'
```

### A.7 环境与基线

```bash
git rev-parse origin/main                      # 4a8e23bf4
git show origin/main:docs/wiki/INDEX.md | grep -c "docs/design/"   # 0 ⇒ 不加索引行
ls backend/admin-api/src/main/resources/db/migration/ | sort -V | tail -1   # 最大迁移号（新迁移从它 +1）
```

### A.8 **§0.1 的三条现状事实**（F4 / F5 / F6）

```bash
# ── F4：ROUTE_RULES 不是运行时真值源（Java 侧 4 处全是注释）──
git grep -n "ROUTE_RULES" origin/main -- backend/admin-api/src/main/java
# → ProcessingOrderService.java:1198 / ProductionSeedTemplateService.java:114 / :134 / :583（全注释）
git grep -n "insertConditionalOperations" origin/main -- backend/admin-api/src/main/java
# → ProcessingOrderService.java:556（调用）/ :796（定义）—— 它读的是**库表** production_route_rules
git grep -n "build_route_v2" origin/main -- backend/ai-agent-service/app
# → 只命中 routing.py 自己的注释与 :783 定义 ⇒ **零生产消费者**

# ── F5：三份实现 + 「不去重」的反证 ──
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java | grep -n "removeIf"
# → 544 / 842 / 1237 / 1325（:1325 是 insertAfterLogical 的「取代」；:842 是 insertConditionalOperations 的「取代」）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java | sed -n '1149p'
# → * <p>⚠️ <b>本方法是「怎么展开路线」的**唯一** Java 实现</b>，且必须与真值源
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '355p'
# → def _insert_after(route: List[str], operation: str, after: str) -> List[str]:   （其首行即 removeIf 等价物）

# ── F6：规则表零版本账 ──
git grep -n "production_route_rules" origin/main -- docs/sql/schema.sql | grep -i version   # → 无命中
git grep -n "production_routing_versions" origin/main -- docs/sql/schema.sql
# → docs/sql/schema.sql:1239（挂 routing_id → production_route_templates，**不是规则表**）

# ── 同族文档（AI 层）──
git log --oneline -2 origin/main -- docs/design/ai-craft-config.md
# → ca8b7cdfe（#4655 跟随 PR）/ 0d0562cd3（#4650 AI 化工艺配置实施设计）
```

---

## 附录 B：待裁定项汇总（**一页交裁定**）

| # | 待裁定项 | 影响面 | 建议（**不替业务决定**） |
|---|---|---|---|
| A1 | `熨烫`/`定型` 的先后 + `定型` 是否必做 | 蒸烫槽的槽内次序 | 需业务给「帘头只定型不熨烫」的工艺解释 |
| A2 | `花边` 的槽归属（选项 + 加工项两条） | 边缘槽 vs 加法槽 | 若"花边"是装饰加法 ⇒ 加法槽（`after_slot=边缘槽`） |
| A3 | 阶段 4 删表后「四爪钩」条件的落点 | 阶段 4 迁移 | 建议：随 #4365 阶段 2（`穿钩-*` 工序）一起定 |
| A4 | `四爪钩` 的 legacy 处置形态 | 3 条规则 | 建议：保留 legacy craft 格（§5.3） |
| A5 | `质检` 是否必做、挂哪 | 可移动槽 | 已挂起（`PENDING_CUSTOMER_CONFIRMATION_OPERATIONS`） |
| A6 | `腰靠垫` 的产品归属 | 加法槽 | 同上（且今天无规则行） |
| A7 | `平幔` 与 `帘头制作` 是否同一道活 | 边缘槽 | 需业务 |
| A8 | `打包` / `外帘打卷` / `外帘装袋` 的顺序 | 包装槽槽内次序 | 已登记（#4343 / V79 自陈待确认） |
| A9 | 两端 tie-break 不一致是否实际触发 | 确定性 | 用 §6 的 Q1~Q4 在真库上判 |
| A10 | §3.6 的位置差异是否真的不可达 | 零行为变化 | 阶段 4 开工前复核 |
| A11 | 商家自建规则迁到哪一层 | 阶段 4 迁移 | 需产品裁定 |
| A12 | 布料（`配料`/`打包`）的槽归属 | 第 4 部位 | 需业务 |
| A13 | 罗马帘整套工序 | 能力缺口 | 已登记（`docs/design/craft-routing-customization.md` §2） |
