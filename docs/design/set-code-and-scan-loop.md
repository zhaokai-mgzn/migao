# 套号落库 + 二维码粒度（套 × 部位）+ 扫码报工闭环（一次扫码 ⇒ 进度 / 计件 / 卡点）

> **状态**：**设计单**（docs-only，**不改生产代码、不碰 ai-agent**）。issue **#4687**。
>
> ## 用户裁定（**硬约束，本文不得自行改判**）
>
> **裁定①（2026-09-20）**：「**套号要落库**（建议）」⇒ 落库，**不是**只在前端派生；目的 = **稳定可追溯**。
>
> **裁定②（2026-09-20，三条）**：
> | # | 裁定 | 落法 |
> |---|---|---|
> | ②-1 | **码粒度 = 一部位一码**（一樘窗 ≤3 码：布帘 / 纱帘 / 帘头）。码内容 = `单号 + 套号 + 部位`（真值源【标】逐字）。**工序不进码**。 | §2.3 |
> | ②-2 | **不拦生产顺序** —— 逐字：「这个不需要管理，因为现实生产过程中工人会自动推进，系统就无需管理生产顺序」⇒ **不做「必须按序」的拦截**（不出现「你必须先做 A 才能做 B」这类阻断）。<br>🔴 **但有一条硬约束**：**「这次扫的是哪道工序」必须确定** —— 否则**计件会记错工序 ⇒ 发错工资**（本仓最忌的静默错误）。⇒ 默认 = 该套该部位的「**下一道待做**」+ **一键改**（极小确认交互）；**绝不允许**在不知道「哪道工序」的情况下直接记账（**有红证**）。 | §3、§4.1、§5.3 |
> | ②-3 | **走 A 模式** —— 逐字：「A」= **先生产 → 做完扫一次**（报工 = 完工），**零额外交互**，与真值源【标】「**一次扫码同时干两件事：推进工序进度 + 记录个人计件**」一致。⇒ **完工必扫、开工不扫**；`started_at`/`worker_id` **不是 A 模式的必需项**（只作 **C 模式预留**，**不许**为它阻断 A 的落地）。 | §4、§6、§4.4 |
>
> **用户提问（逐字）**：「另外我们是否应该设计一些**套的编码信息**来**方便生产环节跟踪和方便管理**？」·
> 「你要思考一个**很重要的问题**：如何让工人**只扫一次码**即可**自动更新进度**、**自动计件**，并且能**正确地追踪进度卡在哪**」
>
> **本单只出设计**：先设计，再动数据。所有「现状」结论均为**实测**（复算命令见 §15）；
> 无法判定的进 §9，不替业务决定的进 §8。
>
> 🔴 **口径订正（issue #4731，2026-09-20）**：本文的**数据层已由 #4698 切片⓪ 落码**（`V92`），
> 故 **§1.2 的 F1 / F16 / F17、§4.4、§8 A3 / A9、§11.1 / §11.2 / §11.4、§13、§14、§15**
> 的对应结论已**逐处改判**（**原文措辞一律保留为历史留档**）—— 逐处说明见 **§1.2 表后注**
> 与 **§11.1 / §11.4 的「口径订正」注**。
> ⚠️ **仍然成立**：A 模式的**功能面**（扫码解析 / 工序推断 / 完成主闭环 / 卡点报表 / 防呆④⑤）**尚未落码** ——
> 切片⓪ 只落**数据层**（边界逐条登记在 `tests/unit_ci_workflows/test_set_code_storage_v92_migration.py`）。
>
> 🔴 **口径订正（issue #4791，2026-09-20；来源 = #4698 切片④ 核清，主会话已裁定）**：
> 本单改**两处措辞**（**纯文档，零代码/零契约账本改动**）——
> ① §5.3 ④ 的判据名统一为**代码实际的** `OPERATION_NOT_IN_SCAN_TARGET`（`CODE_POSITION_MISMATCH` 留档为**曾用名**）；
> ② §5.3 ④ 的判据形态从「`order_item_id` 字面等式」改为「**候选集成员资格**」，并显式写明与 §3.2 ② 套级回落的关系。
> 逐处说明见 **§5.3 ④ 表后注**；**全文「设计写了但代码没有」的清单（只登记、不改判）见 §16**。
>
> **配套真值源**：[curtain-production-rules.md](../curtain-production-rules.md) ·
> [curtain-production-process-standard.md](../curtain-production-process-standard.md) ·
> [worker-scan-terminal.md](worker-scan-terminal.md) ·
> [position-instance-routing-model.md](position-instance-routing-model.md) ·
> [public-operations-and-craft-ui.md](public-operations-and-craft-ui.md) ·
> [operation-slot-model.md](operation-slot-model.md)。

---

## 0. 一句话结论

「**只扫一次码**」在今天的模型里**做不到**，原因**不是**码不够聪明，而是**三件事同时缺**：

| # | 缺什么 | 后果（工人视角） | 本设计的解 |
|---|---|---|---|
| 1 | 码里**没有「哪一套 × 哪个部位」** | 扫完还得手选哪樘窗 / 哪个部位 ⇒ 选错就把进度和钱记到别人身上 | 码粒度升到 **套 × 部位**（**一部位一码**，裁定②-1）§2 |
| 2 | 报工端点**必须显式给 `operationId`** | 工人 / 前端得先知道该报哪一道 ⇒ 「扫一次就自动推进」不成立 | **工序由系统推断**（默认「下一道待做」+ 一键改）§3 |
| 3 | **`done_at` 不存在** ⇒ 「上道几点完成」不可知 | 「**进度卡在哪**」**无判据**（今天只有 `pending`/`done` 两态 + 会被任何更新污染的 `updated_at`） | **完成时写 `done_at`** ⇒ A 模式的卡点判据成立 §6 |

⇒ 本设计给出：**套号落库**（`processing_order_sets`，§2）+ **一部位一码**（§2.3）+
**A 模式一次扫码闭环**（扫 ⇒ 推断 ⇒ 完成 ⇒ 计件，§4）+ **「卡在哪」的判据**（§6）。

**净效果**：工人端从「扫码 → 手选部位 → 手选工序 → 填数量 → 提交」变成
**「扫码 → 看一屏 → 点一次」**（**零额外交互**，裁定②-3）；
管理端从「只有 done/pending 两态」变成**「能回答『第 14 套的定型等上道等了 6 小时』」**。

---

## 1. 真值源与现状（实测）

### 1.1 真值源（**逐字**，不改写）

`docs/curtain-production-rules.md`：

| 行 | 逐字原文 | 对本设计的约束 |
|---|---|---|
| `:9` | 「【标】已确认（含加工项）订单生成加工单，可**一套一单或一单多套**（第 N 套/共 M 套，工程单按楼层/项目拆套）。」 | 套是**订单内的次序**，不是全局计数 |
| `:11` | 「【标】加工单**打印物含二维码**（单号+套号+部位，token 化、可撤销、记录打印次数）——二维码是扫码报工的入口。」 | 码内容 = **单号 + 套号 + 部位**；码是**入口** |
| `:29` | 「【标】工序开关：**此工序必须完成才可打包**（完工门槛）、标记生产开始（首工序触发订单进入生产中）、…」 | 首工序 ⇒ **进入生产** |
| `:38` | 「【默】工序实例的**应做数量 = 算料引擎输出**（折数/孔数/用料米数/幅数），报工只确认，不手工心算。」 | 报工**只确认**；数量默认取 `qty` |
| `:56` | 「【标】防呆：幂等（重复扫提示已报）、越站提示（非本工序）、数量上限校验（≤应做数量+合理损耗）、非本部位码提示。」 | 防呆**四条**（**注意**：`越站提示` 在本设计中**降级为提示**，见 §5.3 ②） |
| `:57` | 「【标】一次扫码同时干两件事：**推进工序进度 + 记录个人计件**。」 | 闭环的**定义句**，A 模式的依据 |
| `:42` | 「【标】**计件工资 = Σ(报工数量 × 工序单价)**；**单工序一人制**（2026-09 客户确认，无计件人数分摊）。」 | 计件口径 |
| `:45` | 「【标】**两套账分离**：内部计件（per 工序，给工人）vs 对外加工费…——互不污染。」 | 只写内部计件侧 |
| `:46` | 「【默】工资报表 = 报工事件聚合（按人/按期/按单下钻：报工 → 工序实例 → 部位 → **套** → 加工单 → 订单）。」 | 按套下钻是**真值源要求** |

`docs/curtain-production-process-standard.md`（**术语真值源**，行业正名）：

| 仓库分组 | 行业正名 | 逐字依据 |
|---|---|---|
| 裁剪 | **裁床** | 「**裁床**…**复核收到的布料**，确认无误后方能进行**裁剪**」「…**按套件打捆**…**发放给车位**缝制」 |
| 车位 | **车位** | 「**车间车位**负责布艺产品的**缝制**」 |
| 后道 | **烫工及后整**（+ 质检 + 包装） | 「**不可缺少的辅助工序**」「**质检贯穿全过程**」「**包装是最后一道工序**」 |
| 其他 | （无对应） | 配套软装件 |

### 1.2 现状（**全部实测**，命令见 §15；⚠️ **F1 / F16 / F17 已因 `V92` 落码过期 ⇒ 见表后「口径订正」**）

| # | 事实 | 读数 |
|---|---|---|
| F1 | ~~**`set_no` / `套号` 在代码侧零命中**~~ ⇒ ✅ **已落码**（**口径订正**，见表后注） | **基线读数**：`git grep -n "set_no\|套号" origin/main` ⇒ 命中全在 `docs/`（`curtain-production-rules.md` / `domain-model-review-sales-production-finance.md` / `order-craft-spec-design.md` / `worker-scan-terminal.md`）⇒ **代码 / 迁移零命中**。<br>✅ **现读数**：#4698 切片⓪（PR #4722，2026-09-20）落 `backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql` ⇒ `processing_order_sets.set_no` 与 `processing_position_operations.set_no` **均已建**（复算命令见 §15）⇒ **代码侧不再零命中** |
| F2 | **码粒度 = 加工单级** | `V49__create_production_operations_and_work_logs.sql`：`ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS qr_token VARCHAR(64)` + 唯一索引 `uk_processing_orders_qr_token` ⇒ **一单一个 token** |
| F3 | **撤销 = 置空 `qr_token`** | `backend/admin-api/src/main/java/com/migao/admin/mapper/ProcessingOrderMapper.java` 的 `revokeQrToken`：`UPDATE processing_orders SET qr_token = NULL …`；注释逐字「置 NULL 而不是换一个新 token：撤销的语义是「这张纸作废」」 |
| F4 | **报工端点必须显式给 `operationId`** | `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java` 的 `report`：`@PostMapping("/orders/{orderId}/operations/{operationId}/report")` ⇒ **工序在 URL 路径里**，系统不推断 |
| F5 | **工序实例无 `started_at` / `worker_id` / `done_at`** | `docs/sql/schema.sql` 的 `processing_position_operations`：列只有 `id/tenant_id/processing_order_id/position_name/order_item_id/position_kind/seq/operation_name/group_name/unit/qty/qty_source/unit_price/factor/is_must_finish/is_start_marker/status/done_qty/created_at/updated_at/deleted` |
| F6 | **`status` 只有两态** | V49 列注释逐字：「`pending` 待做 / `done` 已报工」⇒ **没有「在做」这一态**，**也没有「完成时刻」** |
| F7 | **「谁做过」只能从报工流水反推** | `git grep -n "worker_id" origin/main -- '*.sql' '*.java'` ⇒ 只有 `production_work_logs.worker_id/worker_name`；`ProductionService.workersByOperation(logs)` 聚合流水 ⇒ 是「谁报过」，**不是**「谁正在做」 |
| F8 | **⚠️ 全仓没有「标准工时」** | `git grep -niE "标准工时\|standard_hours\|std_hours" origin/main` ⇒ **零命中**（含 `docs/`、`*.sql`、`*.py`、`*.java`）⇒ 见 §6.4 |
| F9 | **`is_start_marker` 无消费者 ⇒ 首工序**不会**触发生产开始** | `git grep -n "isStartMarker" origin/main -- '*.java'` ⇒ 命中全部是**读面 / 写面 / 快照**；**没有任何一处把加工单置 `in_processing`**。`ProcessingOrderService.updateStatus` 的 `case "start": target = "in_processing"` 是**手工端点** |
| F10 | **加工单状态机 = `generated→issued→in_processing→completed \| cancelled`** | `ProcessingOrderService.STATUS_TRANSITIONS`：`"issued", Set.of("in_processing","cancelled")` / `"in_processing", Set.of("completed","cancelled")` ⇒ **`generated` 不能直达 `in_processing`** |
| F11 | **樘窗组 = `craftLineId`；套级工序每组只落一行** | `git grep -n "craftLineId" origin/main -- '*.java'` + `ProcessingOrderService.setLevelKeeperItemIds`：组键 = `craftLineId`（缺省回落本行 `itemId`）；套级工序（`scope='set'`）**承载体 = 组内第一条 `curtainType=布帘` 的行**，无布帘则取组内首行 |
| F12 | **`order_items` 与部位是 1:1** | `docs/design/position-instance-routing-model.md` §2.1 + `ProcessingOrderService.buildPositionPayload`：「一行 = 一个部位」，只有 `componentRole=配布边` 的行被吸收 ⇒ **一樘窗（布+纱+帘头）= 多行 = 多部位** |
| F13 | **计件快照在报工行** | `docs/sql/schema.sql` 的 `production_work_logs.unit_price` / `factor`（V61）注释逐字：「报工那一刻从工序实例写入 ⇒ 聚合只读本行，**永不回查实例**」 |
| F14 | **报工推进是 CAS 原子** | `backend/admin-api/src/main/java/com/migao/admin/mapper/ProcessingPositionOperationMapper.java` 的 `advanceDoneQtyIfUnchanged`：`UPDATE … SET done_qty=#{doneQty}, status='done' WHERE … AND done_qty=#{expectedDoneQty} AND status=#{expectedStatus} AND done_qty < #{doneQty}` ⇒ 影响行数 0 = 被并发推进 ⇒ fail-closed |
| F15 | **幂等键 = `X-Client-Request-Id`** | `ProductionService.report`：「先占位 → 执行 → 落快照」；失败释放占位 ⇒ 同键重试可进 |
| F16 | ~~**迁移头号 = V88（已占用）** ⇒ 本设计的迁移号 = `V89`~~ ⇒ ✅ **本设计的数据层已落码（= `V92`）**（**口径订正**，见表后注） | **基线读数**：`…/db/migration/` 取最大号 ⇒ `V88`（`V88__retire_material_prep_and_fabric_position.sql`）；`grep -c V89` ⇒ **0** ⇒ 当时判「本设计的迁移号 = `V89`」。<br>✅ **现读数**：`V89` 已被 `V89__backfill_fabric_seed_for_existing_tenants.sql` 占用、`V90` 已被 `V90__unpriced_is_not_zero.sql` 占用；本设计的数据层由 **#4698 切片⓪** 落在 `backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql`（PR #4722，merge `d295097bb`，2026-09-20）。⇒ **「迁移号现取、不写死」原则保留**：后续切片的新迁移号一律落码时现取（复算命令见 §11.1 / §15） |
| F17 | **迁移指纹守卫覆盖全部已发布迁移**（⚠️ **条数现取，本文不写死**） | **基线读数**：`tests/unit_ci_workflows/migration_fingerprints.json` 的 `migrations` 键 **86 条**，末三条 `V86__…` / `V87__…` / `V88__…`。<br>⚠️ **该计数会随每次新增迁移漂移**（照 issue #4701 的纪律：注释 / 文档里**不得写会漂移的硬编码计数**）⇒ **现读数用命令取**（见 §15）：`git show origin/main:tests/unit_ci_workflows/migration_fingerprints.json \| python3 -c "import json,sys; print(len(json.load(sys.stdin)['migrations']))"`。<br>**结论不变**：**已发布迁移不可改**（改旧迁移 = 指纹红 + 只对全新库生效 ⇒ 存量环境「CI 绿、功能静默缺失」，issue #4235） |
| F18 | **报工推进**不校验**部位归属**（防呆④今天形式上是空的） | `ProductionService.doReport` 的活跃性判据只校验「租户 / `deleted=0` / 归属加工单」三重 ⇒ 传**别的部位**的 `operationId` + 本单 `orderId` 会被**放行**（因为**码里没有部位**）⇒ §5.3 ④ |

> 🔴 **口径订正（issue #4731，2026-09-20）：F1 / F16 / F17 三条的结论已过期 —— 原因是「迁移头前进」+「切片⓪ 落码」。**
> **① 当时基线**（本文定稿时）：`origin/main` 迁移头 = **`V88`**、`grep -c V89` = **0**、
> `set_no` / `套号` 在 `backend/**` `tests/**` **零命中**、`migration_fingerprints.json` **86 条**（末三条 V86/V87/V88）。
> **② 后来变了**：`#4698 切片⓪`（PR #4722，merge `d295097bb`，2026-09-20）落
> `backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql`
> —— 建 `processing_order_sets` + `processing_set_part_tokens`（含 `uk_set_part_tokens_token` / `uk_set_part_tokens_part`）
> + 给 `processing_position_operations` 加 **6 列**（`set_id` / `set_no` / **`done_at`** / `worker_id` / `worker_name` / `started_at`），
> **与 §11.2 逐条一致**；同时 `V89` 被 `V89__backfill_fabric_seed_for_existing_tenants.sql` 占用、
> `V90` 被 `V90__unpriced_is_not_zero.sql` 占用 ⇒ **本文原推的 `V89` 号已不属于本设计**。
> **③ 故结论改为**：F1 = ✅ **已落码**；F16 = ✅ **数据层已落（`V92`）**，后续迁移号**现取、不写死**；
> F17 = **条数改为「现取」**（**不写死**），结论「已发布迁移不可改」**不变**。
> ⚠️ **原文措辞一字未删**（上表 F1 / F16 / F17 的原判断保留在 ~~删除线~~ 与「基线读数」里）——
> 这是 `docs/design/public-operations-and-craft-ui.md` §5.2 表后「口径订正」注的**同款写法**。
> 判据锚点（已落码的机械钉死）= `tests/unit_ci_workflows/test_set_code_storage_v92_migration.py`。

### 1.3 现状 ⇒ 用户问题的直接回答

```
今天的链路： 扫码(qr_token) → 解析出【加工单】→ 前端拉工序树 → 工人肉眼找部位
             → 肉眼找「该做哪一道」→ 点它 → 填数量 → 提交 → report(orderId, operationId, qty)
                        ↑ 这三步全是人在做系统该做的事
```

⇒ **「只扫一次」的真实含义 = 把「找部位 + 找工序 + 填数量」三步从工人手里拿走**，
而不是「少点一次按钮」。这正是本设计的三根支柱（§2 / §3 / §4）。
⚠️ **「卡在哪」今天无解**，不是因为判据不够好，而是**判据所需的两个时刻都不存在**
（F5/F6：没有 `done_at`，也没有 `started_at`）—— 见 §6.2。

---

## 2. 套号：格式、落库载体、二维码粒度

### 2.1 套号格式与序号口径

**格式**：`{processing_order_no}-{set_index}`，`set_index` **3 位零填充**。

```
CSO260915-02615-014      ← 加工单号 CSO260915-02615 的第 14 套
```

| # | 理由 |
|---|---|
| 1 | **单号已唯一**（`processing_orders.processing_order_no` 是打印给车间的对外单号，真值源 `:10`）⇒ 拼接天然唯一，**不新造第二套编号** |
| 2 | **车间能念**：工人对单靠嘴念「CSO260915-02615 第 14 套」，比 UUID / 内部 id 可操作 |
| 3 | **3 位零填充**：与真值源实证的「第 14 套/共 22 套」同形；`014` 与 `14` 排序对齐稳定（1~999 覆盖工程单；>999 由分配器**显式拒绝**，不静默截断） |
| 4 | **不含部位、不含工序**：部位进**码**不进**号**（§2.3）；工序**两处都不进**（码量论证见 §2.3） |

**序号口径（用户裁定，2026-09-20）**：`set_index` = **一樘窗在订单里的次序**。

⚠️ **「一樘窗」必须落到既有载体上，否则会算错**：实测 F11/F12 —— 一樘窗（布 + 纱 + 帘头）是
**多条 `order_items` 行**，靠 `craftLineId` 绑成**一组**（issue #4354 / #4387）。
⇒ **`set_index` 的分配单位 = 樘窗组（`craftLineId` 组），不是 `order_items` 行**。

> 反例（不做这一步的后果）：一樘「布 + 纱」的窗会被算成 **2 套**，而真值源 `:9` 说的是
> 「第 N 套/共 M 套」的**套** ⇒ 「共 M 套」虚高一倍，且与 #4384 的套级工序口径（每樘窗一次）**互相矛盾**。
> ⚠️ 这与 #4373 的旧口径「一个窗帘商品 = 1 套」**不一致** ⇒ 登记为口径升级（§10 C4）。
> ✅ **该改判已交付**（**issue #4693**，2026-09-20）：旧口径已在
> `docs/design/position-instance-routing-model.md` **§2.1.1** 就地改判 + 注明依据 + 历史留档，
> 并配了可执行断言（「一樘窗（布+纱+帘头）= 1 套」）。

### 2.2 落库载体（**用户裁定①：落库**）

**新增表 `processing_order_sets`**（一个加工单 × 一套 = 一行）：

| 列 | 类型 | 约束 / 语义 |
|---|---|---|
| `id` | `VARCHAR(64) PK` | 套的内部主键（`ASSIGN_UUID`，与全仓一致） |
| `tenant_id` | `BIGINT NOT NULL REFERENCES tenants(id)` | 租户隔离 |
| `processing_order_id` | `VARCHAR(64) NOT NULL REFERENCES processing_orders(id)` | 归属加工单 |
| `set_index` | `INT NOT NULL` | 一樘窗在**本加工单**里的次序（1 起） |
| `set_no` | `VARCHAR(64) NOT NULL` | `{processing_order_no}-{set_index}`（**落库冗余**，理由见下） |
| `craft_line_id` | `VARCHAR(64)` | 樘窗组键（= 快照 `craftLineId`，缺省 = 该组主布行的 `itemId`）；**可空**（存量 / 脏快照） |
| `position_item_ids` | `JSONB NOT NULL DEFAULT '[]'` | 本套包含的**部位行** `order_items.id` 数组（有序）⇒ 「这套有哪几个部位」**不靠反查** |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | 与全仓同款 |
| `deleted` | `INTEGER NOT NULL DEFAULT 0` | 软删（**软删 ≠ 释放号**，§2.4） |

**唯一键（两个，各给理由）**：

| 索引 | 定义 | 理由 |
|---|---|---|
| `uk_processing_order_sets_index` | `(tenant_id, processing_order_id, set_index) WHERE deleted = 0` | **分配器的正确性依赖**：并发建套时靠它把「同号两套」挡在库层（§2.4 规则 3） |
| `uk_processing_order_sets_no` | `(tenant_id, set_no) WHERE deleted = 0` | **可读号的唯一性**：**码里印的是它，扫码解析靠它** ⇒ 若它可重，扫码会解析到两套。`tenant_id` 入键 = 跨租户不互撞（多租户同形单号合法） |

**为什么 `set_no` 落库冗余（而不是读时拼）**：
① **码里印的是它** ⇒ 扫码解析是**按文本查唯一索引**，不该在热路径上做拼接 + 解析；
② `processing_order_no` 一经生成**不变**（真值源 `:10`），`set_index` 一经分配**不变**（§2.4）
⇒ 冗余**不会漂移**（这是冗余能成立的唯一条件，**必须写进列注释**）。

**为什么用新表而不是在 `processing_orders` 加列**：
① 一单多套（真值源 `:9`）⇒ 一个加工单对**多**套 ⇒ **1:N，加列表达不了**；
② 若改挂在 `order_items` 上：一樘窗多行 ⇒ 同一 `set_no` 在多行重复 ⇒ 唯一键失效 + 删一行就丢套；
③ 新表让「套」成为**独立于订单行生命周期的生产凭据**（与 V69「工序实例是生产凭据」同族理由）。

**`processing_position_operations` 增两列**（**实例快照，不靠 join**）：

| 列 | 类型 | 语义 |
|---|---|---|
| `set_id` | `VARCHAR(64)` | 指向 `processing_order_sets.id`；**可空**（存量行） |
| `set_no` | `VARCHAR(64)` | 套号快照；**可空**（存量行）。用途：扫码归属校验 + 计件按套下钻（**零改动 `production_work_logs`**，§5.4） |

**为什么可空 + 不猜（存量行）**：与 `V69`（`order_item_id`）**逐字同款理由** ——
存量行没有该值且**无法可靠回填**（§2.5）；「猜错比留空更糟」（会把工序/计件归属到错的行）。
读面按「无 `set_no` ⇒ 显示加工单号（旧形态）」兜底 ⇒ **存量单行为逐字不变**。

### 2.3 二维码：内容、粒度、与既有 `qr_token` 的关系

**内容 = 单号 + 套号 + 部位**（真值源 `:11` 逐字）；**粒度 = 一部位一码**（**裁定②-1**）。
**载体 = token（不是明文拼接）**：

| 项 | 设计 |
|---|---|
| 载体 | **新表 `processing_set_part_tokens`**：`id` / `tenant_id` / `processing_order_id` / `set_id` / `order_item_id`（部位）/ `position_kind` / `token`（`VARCHAR(64)`，32 位 UUID 去横线，**与既有 `qr_token` 同格式**）/ `print_count` / `created_at` / `updated_at` / `deleted` |
| 唯一键 | `uk_set_part_tokens_token (token) WHERE deleted = 0`（**与既有 `uk_processing_orders_qr_token` 逐字同款**） |
| 唯一键 | `uk_set_part_tokens_part (tenant_id, set_id, order_item_id) WHERE deleted = 0` ⇒ **一部位一码**；同一部位重复打印 = **复用同一 token**（不换码） |
| 撤销 | **同 F3 语义**：`UPDATE … SET token = NULL WHERE …` ⇒ 已打印的码立即失效；**不换新 token**（理由与 F3 注释逐字同款：「撤销的语义是「这张纸作废」，不是「静默换一张纸」」） |
| 打印次数 | `print_count`，原子自增（与 `ProcessingOrderMapper.incrementPrintCount` 同款 `COALESCE(print_count,0)+1`；理由：多人同时打印不丢计数） |
| **工序** | **不进码**（裁定②-1 + 真值源 `:11` 逐字只写「单号+套号+部位」）—— 码量论证见下 |

**为什么工序不进码（码量论证）**：

```
一樘窗（布帘 + 纱帘 + 帘头）= 3 个部位；每部位 ~10 道工序（真值源 §3 行业实证 11 道）
若工序进码 ⇒ 一樘窗 3 × 10 = 30 个码；工程单 22 套 ⇒ 22 × 30 = 660 个码
若部位进码 ⇒ 一樘窗 3 个码；         22 套 ⇒ 66 个码
```

差 10 倍。且工序码有个**致命**问题：工序在实例化后**还会变**
（`instantiate` 的签名比较会软删重插；条件工序按特殊选项插入）
⇒ 工序进码 = 「**改一次工艺，全车间已打印的码全部作废重打**」——不可接受。

**为什么部位进码、不「一码多部位 + 扫后选」**（裁定②-1 已定，此处给依据）：
① 真值源 `:11` 逐字要求「单号+套号+**部位**」；
② 行业实证（`docs/design/worker-scan-terminal.md` §3.4 逐字）：「标签内容 = 单号 + 套号 + 部位 + 客户 + 收货信息 + 条码（**条码即扫码报工的入口**）」⇒ 打印物**本来就按部位出**；
③ **部位数量有上界**：真值源 `:12` 的部位是**布帘 / 纱帘 / 帘头**（+ 布料形态）⇒ 一樘窗 **≤ 4 码**，不是无界。

⚠️ 但**部位选择能力仍必须实现**（**降级形态**）：**存量旧码只到加工单级**（F2）⇒
旧码命中时**必须**让工人选部位（§2.6）。这是「兼容」不是「默认形态」。

**与既有 `qr_token` 的关系（**不新造第二套机制**）**：

| 既有机制 | 处置 | 理由 |
|---|---|---|
| `processing_orders.qr_token` 列 | **保留，不改不删** | ① 存量单的旧码解析靠它；② `resolveOrder` 的「③ qr_token」形态是**既有冻结契约**（issue #4005 / #4222 四形态） |
| `ProcessingOrderMapper.revokeQrToken` | **保留**（加工单级撤销仍有意义：整张单作废） | 撤销语义**逐字复用**：置 NULL |
| 新 `processing_set_part_tokens` | **同款形态**（同 token 格式、同唯一索引形态、同撤销语义、同打印计数） | 「不新造第二套」= **同款语义的可撤销 token**，不是「复用一个列」—— **一个列装不下 1:N 的码** |
| 扫码解析优先级 | 新 token **先查**，未命中回落 `qr_token`（§2.6） | 新旧共存期的唯一正确顺序：新码精确（带套带部位），旧码粗（只到单） |

**⇒ 冻结的三条性质**：

| 性质 | 成立条件（必须同时成立） |
|---|---|
| **稳定** | `set_no` 落库 + `set_index` **只增不复用**（§2.4）+ `processing_order_no` 不变 ⇒ 重排 / 改名 / 删窗**都不改已有套号** |
| **唯一** | `uk_processing_order_sets_no (tenant_id, set_no)`（跨租户不互撞）+ `uk_set_part_tokens_token` |
| **可撤销** | 复用 F3 的「置 NULL」语义（**不换新 token**） |

### 2.4 序号分配规则（**不复用已删号**）

```
allocate_set_index(processing_order_id):
    SELECT COALESCE(MAX(set_index), 0) FROM processing_order_sets
      WHERE processing_order_id = ? AND tenant_id = ?      -- ⚠️ 不带 deleted = 0
    ⇒ next = MAX + 1
```

| # | 规则 | 为什么 |
|---|---|---|
| 1 | **`MAX` 的查询不带 `deleted = 0`** | 「不复用已删号」的**唯一实现方式**：软删的行仍占号 ⇒ 号池单调 |
| 2 | **分配是「写一次」不是「算一次」** | 用户裁定①「落库」的直接含义；重排/删窗后重新计算 = 换号 ⇒ 已打印的码对不上 |
| 3 | **并发靠库层唯一键兜底** | 两个请求同时读到 `MAX=13` ⇒ 都插 `14` ⇒ 第二个撞 `uk_processing_order_sets_index` ⇒ `ON CONFLICT DO NOTHING` + **重读**（重读到的就是赢家那行）⇒ 幂等，不静默造重号 |

**重排 / 改单 / 删窗的逐条处置**：

| 事件 | 处置 |
|---|---|
| 订单行**重排** | **不动**任何已有 `set_index`（号是分配出来的，不是算出来的） |
| 商品名 / 色号**改名** | **不动** `set_no`（它只由单号 + 序号构成，**不含名字** —— 这是格式设计的收益） |
| 某套**被删**（行软删） | 该套行 `deleted = 1`；**号不释放**；新窗取 `MAX+1` |
| **新增**一套 | `MAX+1`（**不复用**被删的号） |
| 加工单**作废 / 重开** | 新加工单 = 新 `processing_order_no` ⇒ 全新号段；旧套号随旧单一起失效（**天然不撞**） |

### 2.5 存量单回填（**能做与不能做，分开说**）

| 存量形态 | 能否回填 | 处置 |
|---|---|---|
| **已实例化**且 `processing_position_operations.order_item_id` **非空**的单 | ✅ **能** | 按 `items_snapshot` 行序 + `craftLineId` 分组，**按行序分配** `set_index = 1..M`，回填 `set_id` / `set_no` 到实例行 |
| **已实例化**但 `order_item_id` **为 NULL** 的单（V69 之前的存量行） | ❌ **不能** | **不猜**（V69 逐字：「`position_name` 是可读名，按它反查 `order_items` 只能靠猜 ⇒ **猜错比留空更糟**」）⇒ 套行照建（数据来自 `items_snapshot`，它是固化真相），但**实例行留空** |
| **未实例化**（工序实例与 `qr_token` 双空） | ✅ 能 | 在**下次实例化时**按快照行序分配（不预先回填） |
| `items_snapshot` 里 **`craftLineId` 缺失**的行 | ✅ 能（**各自成组**） | 与既有 `craftGroupKey` 逐字同口径：缺 `craftLineId` ⇒ 回落本行 `itemId` ⇒ **各自成一樘窗**（不静默并组） |

**回填的确定性要求**：回填必须**只读 `items_snapshot`**（固化真相），**不读 `order_items` 现值** ——
后者会被改名 / 改行序影响 ⇒ 回填结果不可复现。（与 #4459「算料单一真值」同族纪律。）

**>999 套**：分配器**显式拒绝**（`BusinessException` + 建议），**不静默截断**（截断 = 两套同号）。

### 2.6 ⚠️ 存量已打印旧码怎么办（**必须显式回答**）

**结论：旧码继续有效，走「降级形态」—— 不清空、不双写、不重打。**

| 问题 | 回答 |
|---|---|
| **兼容 / 失效 / 双读？** | **双读（新码优先）**，**不是**失效。`V92`（#4698 切片⓪，**已落码**）**不碰** `processing_orders.qr_token`（已有打印件不作废 —— 作废会让车间手里的纸全部变废纸，代价不可接受）〔原写 `V89` ⇒ **口径订正**见 §11.1〕 |
| **解析顺序** | **① 新 token（`processing_set_part_tokens.token`，带套带部位）→ ② 旧 `qr_token`（加工单级）→ ③ `processing_order_no`（手输）→ ④ `order_no` → ⑤ 内部 `order_id`**；②~⑤ 是 `resolveOrder` 的**既有四形态，一字不动** |
| **旧码命中后的行为** | 返回**降级形态**：`{granularity: "order", set_no: null, position: null, …}` + `needs_selection: ["set", "position"]` + **可选清单**（该单的套 × 部位）⇒ 工人**选一次**部位（比今天「选部位 + 选工序 + 填数量」少两步） |
| **旧码何时自然退场** | ① 撤销（`revokeQrToken`，既有端点）⇒ 置 NULL ⇒ 立即失效；② 重新打印（打印入口按新形态出码）；③ **不设截止日强制失效**（强制失效会打断在产单） |
| **旧码会不会「扫错套」** | **不会**：旧码 `granularity="order"` ⇒ **系统明确知道它不知道是哪套** ⇒ 强制选择（`needs_selection`），**绝不默认取第 1 套**（默认 = 静默把进度记到错的套上，正是要治的病） |
| **双读的一致性风险** | 低：两条解析路径**共用**同一份租户 / 软删 fail-closed 判据；新 token 未命中**只回落**，不并行写 |

---

## 3. 工序由系统推断（扫一次 ⇒ 知道该做哪一道）

> **裁定②-2**：**不拦生产顺序**，但**「这次扫的是哪道工序」必须确定** —— 否则计件记错工序 ⇒ 发错工资。

### 3.1 扫描的输入与输出

**输入**：一个 token（来自二维码）或 `(set_no, 部位)`（手输兜底）。
**输出（一屏）**：

```jsonc
{
  "granularity": "set_position",        // 或 "order"（旧码降级，§2.6）
  "processing_order_no": "CSO260915-02615",
  "set_no": "CSO260915-02615-014",
  "set_index": 14,
  "position": { "order_item_id": "oi-…", "position_kind": "布帘", "position_name": "布艺遮光帘A 米白" },
  "operation": {                        // ← 系统推断出的「下一道待做」，工人不用找
    "operation_id": "op-…",
    "logical_name": "定型",             // 读时派生（既有 logicalOperationName 口径）
    "display_name": "定型 · 布帘",
    "group_name": "后道",
    "unit": "米",
    "qty": 11.00,                       // 应做数量 = 算料引擎输出（真值源 :38）⇒ 报工只确认
    "qty_source": "fabric_meters",
    "unit_price": 3.50,
    "seq": 6,
    "status": "pending",
    "determined_by": "inferred"         // inferred = 系统推断；picked = 工人一键改（§3.3）
  },
  "alternatives": [                     // 一键改的候选（同套同部位的其他未完成工序）
    { "operation_id": "op-…", "display_name": "复烫 · 布帘", "seq": 7, "qty": 11.00, "unit": "米" }
  ],
  "set_progress": { "done": 7, "total": 14, "percent": 50 },
  "stalled": { "kind": null }           // §6：非空 = 这道卡住了，附判据与阈值来源
}
```

### 3.2 推断算法（**默认 = 下一道待做**）

> 记号：`OPS(set)` = 该套的全部活跃工序实例（`deleted=0`，含 `scope='position'` 与 `scope='set'` 两类）。
> `PENDING(op)` ⇔ `op.status <> 'done'`。

```
infer_next(set, scanned_order_item_id):
  # ── ① 部位级：优先「扫到的那个部位」的未完成工序 ──────────────────
  ops = [op for op in OPS(set)
         if op.order_item_id == scanned_order_item_id and PENDING(op)]
  if ops:
      return min(ops, key=op.seq)                    # 部位内 seq 最小的未完成者

  # ── ② 套级回落：本部位的活干完了，但整樘窗还有套级活（打卷/装袋/发货）──
  #    既有语义：套级工序（scope='set'）挂在「樘窗组主布行」这一个部位上（F11）
  set_ops = [op for op in OPS(set) if op.scope == 'set' and PENDING(op)]
  if set_ops:
      return min(set_ops, key=op.seq)                # 返回时带 rerouted=true

  # ── ③ 本套无活可做 ────────────────────────────────────────────────
  return NONE   # ⇒ 响应 "本套已完成"（含完成时间），不报错
```

**为什么必须有 ②（否则闭环会死锁）**：实测 F11/F12 —— 一樘窗「布 + 纱」时，
`外帘打卷 / 装袋 / 发货` 只落在**主布行**那一个部位上。
工人做完**纱帘**部位的所有活，拿纱帘的码再扫 ⇒ 按 ① 会得到「无工序可做」，
而**整樘窗其实还没做完**（套级活没干）⇒ 闭环断在这里。
② 把「扫纱帘的码 ⇒ 系统告诉你『去打卷 / 装袋（套级）』」变成正常路径。

**`rerouted=true` 的界面口径**：明确显示「本部位已完成；本套还有**套级工序**：外帘打卷」
+ 提供**去向**（该工序的承载部位）。**不静默换工序**（工人必须知道系统为什么换了）。

**⚠️ 本算法**不做**顺序拦截**（裁定②-2）：它**只决定「默认报哪一道」**，
**不校验**前道是否完成、**不拒绝**任何报工。顺序的现实约束由工人自己维持
（逐字：「现实生产过程中工人会自动推进，系统就无需管理生产顺序」）。

### 3.3 「一键改」（极小确认交互）与**硬约束：工序必须确定**

| 场景 | 行为 |
|---|---|
| **默认路径**（绝大多数） | 系统推断的「下一道待做」直接作为待报工序 ⇒ **零额外交互**（裁定②-3） |
| **工人要报的不是它** | 一屏内提供 `alternatives`（同套同部位的其他未完成工序，按 `seq` 排）⇒ **一键改**（一次点选） |
| **接口层** | 完成端点接受**可选** `operation_id`：<br>· 省略 ⇒ 服务端用 §3.2 推断；<br>· 给出 ⇒ **必须属于本次扫码的候选集**（该套该部位 **∪** 套级回落候选；否则 422 `OPERATION_NOT_IN_SCAN_TARGET`，§5.3 ④；<s>原写「必须属于该套该部位」</s> —— 措辞已按 §5.3 ④ 的口径订正对齐） |
| 🔴 **硬约束（裁定②-2）** | **绝不允许**在「工序未确定」的情况下直接记账 ⇒ 服务端**必须**在写 `production_work_logs` 前解析出**唯一确定的 `operation_id`**：<br>· 推断出唯一一道 ⇒ 用推断值；<br>· 推断出**零道**（该部位无未完成工序）⇒ **拒绝**（`NO_PENDING_OPERATION`，不记账）；<br>· 推断出**多道**（理论上不会：`min(seq)` 唯一；仅当 `seq` 重复的脏数据）⇒ **拒绝并要求显式 `operation_id`**（`OPERATION_AMBIGUOUS`，不记账） |
| **红证（必须有）** | 注入「`operation_id` 未确定却写了 `production_work_logs`」⇒ **必红**。形态：mock 掉推断使返回值集合 >1 且不传 `operation_id` ⇒ 断言**没有** `workLogMapper.insert` 调用 + 返回 `OPERATION_AMBIGUOUS`。**反向**：删掉该断言 ⇒ 该测试必须变红（不会红的断言 = 空断言） |

**为什么这条硬约束与「不拦生产顺序」不矛盾**：
「不拦顺序」= **不校验前道**（工人爱做哪道做哪道）；
「工序必须确定」= **记哪道必须明确**（工资不能记到猜的那道）。
两者**正交**：前者管**准入**，后者管**记账的确定性**。

### 3.4 与「数量」的关系（真值源 `:38`：报工只确认，不手工心算）

**数量默认 = `op.qty`**（应做数量 = 算料引擎输出，裁定②-3 逐字确认）。
工人**可以改**，但：
① 上限受既有 `assertWithinPlannedQty`（**拒绝**，不 clamp —— 该 javadoc 已给三条理由：明细不可变 ⇒ clamp 会让台账自相矛盾）；
② 改过的数量**必须留痕**（`qty_override` 标记 + 原值），因为「应做数量填错」与「工人多做了」是**两种病**，
台账要能分辨（与既有 `qty_source`「兜底不静默」同族纪律）。

---

## 4. A 模式闭环：完工必扫、开工不扫

> **裁定②-3**：走 **A 模式** —— 「先生产 → 做完扫一次」（报工 = 完工），**零额外交互**，
> 与真值源 `:57`「一次扫码同时干两件事：**推进工序进度 + 记录个人计件**」一致。

### 4.1 A 模式的闭环一屏

```
① 扫「第 14 套 · 布帘」的码
      ↓  token → (set_id, order_item_id)          ← 部位由【码】给出，工人不选（裁定②-1）
② 系统推断下一道待做工序                          ← §3.2（含套级回落；不做顺序拦截）
      ↓  返回 operation{qty=11.00 米, unit_price=3.50, seq=6}
③ 显示一屏：「定型 · 布帘 · 应做 11.00 米」+ 一个大按钮【完成】+ 一行小字「不是这道？改」
      ↓
④ 点【完成】                                      ← 数量默认 = qty（真值源 :38「报工只确认」）
      ↓
⑤ 服务端一次事务做四件事（§4.2）：
      a. 防呆四条全过（§5.3）+ **工序确定性硬约束**（§3.3）
      b. 写 production_work_logs（数量 × 快照单价）      ← 真值源 :57「记录个人计件」
      c. CAS 推进 done_qty + status='done' + **done_at**  ← 真值源 :57「推进工序进度」
      d. 必完工序全绿 ⇒ 加工单 completed；首工序 ⇒ in_processing（§7.3）
      ↓
⑥ 返回：本道完成 + 本套进度 + 本单累计计件 + **下一道是什么**（工人接着扫下一个码 / 同一部位继续）
      ↓
⑦ 「卡在哪」随时可查（§6）：A 模式只查**「没开工」**那一种
```

**「只扫一次」的账**（今天 vs A 模式）：

| 步骤 | 今天 | A 模式 |
|---|---|---|
| 找到「哪一樘窗」 | 手选 | **码里带着**（0 步） |
| 找到「哪个部位」 | 手选 | **码里带着**（0 步） |
| 找到「该做哪一道」 | 肉眼在 11~14 道里找 | **系统推断**（0 步；改道才 +1 步） |
| 填「做多少」 | 心算 / 手输 | **默认 = 算料输出**，可改（0~1 步） |
| 点提交 | 1 步 | 1 步 |
| **合计** | **≥ 4 步** | **1 步** |

**A 模式刻意不做的事**（裁定②-3 逐字「零额外交互」）：
❌ 不要求点「开始」❌ 不要求确认「我要做这道」❌ 不要求选部位 ❌ 不要求填数量。
**唯一的额外交互**是「不是这道？改」—— **只在工人需要时才点**。

### 4.2 完成动作的事务边界

**必须一次事务**（与既有 `report` 的接线差异要显式说明）：

⚠️ 实测：既有 `ProductionService.report` **刻意不加 `@Transactional`**
（javadoc 逐字：「本方法**不加** `@Transactional`，占位与快照的提交边界才是既有的「先占位 → 执行 → 落快照」同款」）。
本设计的「完成」动作**要落三处**（`work_logs` + 实例行 + 加工单状态）⇒ **必须**明确事务边界：

| 方案 | 取舍 |
|---|---|
| **A（推荐）**：新增一个 `@Transactional` 的 `completeByScan(...)`，**幂等占位仍在外层**（复用 F15 的 `ClientRequestIdService`：占位 → 调事务方法 → 落快照） | 与既有 `instantiate`（`@Transactional`）+ `report`（占位在外）的**两种既有形态各取所长**；三处写入同生共死 |
| B：在 `report` 里加 `@Transactional` | ❌ **不动既有方法**（它的边界是被实证设计过的，改动会波及 bmini 扫工页的幂等语义） |

**⇒ 选 A**：**不修改** `report`，**新增**扫码完成入口，幂等键与占位 / 回放机制**逐字复用**。

### 4.3 数据落点（A 模式的必需列）

| 列（`processing_position_operations` 新增） | A 模式必需？ | 语义 |
|---|---|---|
| **`done_at`** | ✅ **必需** | 完成时刻 ⇒ **A 模式卡点判据的唯一来源**（§6） |
| `set_id` / `set_no` | ✅ 必需 | 套号快照（§2.2） |
| `worker_id` / `worker_name` | ⚠️ **A 模式非必需**（可选写入 = 「完成人」） | 完成时**可以**带上报工人（报工流水已有 `worker_id`/`worker_name`）⇒ 实例列只是**读面便利**，**不是** A 的前置 |
| `started_at` / `in_progress` 态 | ⛔ **A 模式不用** | **C 模式预留**（§4.4）；**不许**为它阻断 A 的落地（裁定②-3） |

⚠️ **诚实登记**：A 模式下**没有「开工事件」** ⇒ 卡点只能判**「没开工」**（§6.1 ①）。
「开了没完」（在制卡住）**在 A 模式下不可判** —— 这不是缺陷，是 A 模式的**定义后果**
（不记录开工就无从知道开工）。⇒ 需要它才上 C 模式（§4.4）。

### 4.4 C 模式（开工选扫）= **可选增强**，不是 A 的前置

> **裁定②-3**：C 模式**写成可选增强**（列 + 开关 + 与 A 共存的口径），**不要**作为 A 的前置。

| 项 | 设计 |
|---|---|
| **形态** | 工人在扫码页可选点一次「**开始**」⇒ 该工序 `status='in_progress'`，写 `worker_id` / `worker_name` / `started_at` |
| **开关** | **按租户**配置（`tenants` 级或配置项；**默认关**）⇒ 默认行为 = A 模式，**逐字不变** |
| **与 A 共存的口径（三条，必须写清）** | ① **`done` 的准入判据是「未完成」，不是「已认领」** ⇒ 未认领直接完成**始终合法**（C 模式下也一样，否则 C 会变成 A 的前置，违反裁定）；<br>② 认领**不改变**推断结果（推断只看 `status <> 'done'`）；<br>③ 认领**不阻断**任何工序（**与「不拦生产顺序」一致**：`in_progress` 不构成对他人的锁定 ⇒ 别人扫同一道码**照样能完成**，不返回 409） |
| **`in_progress` 的语义（C 模式）** | **纯观测**（「谁在做」），**不是**互斥锁 ⇒ 不引入「已被别人认领 ⇒ 两条出路（接替 / 跳站）」那套交互（**与裁定②-2 的「不拦」冲突，故不采纳**） |
| **数据落点** | `status` 取值域扩一条 `in_progress`；列 `worker_id` / `worker_name` / `started_at`（**全部可空**） |
| **C 模式解锁的判据** | §6.1 **②「开了没完」**（`in_progress` + `started_at` 距今 > 阈值）⇒ 「谁在做、卡了多久」 |
| **落地顺序** | **A 先落、C 后加**；C 的列在 `V92` 一次性建好（**建列 ≠ 建功能**：不写消费者 = 零行为变化），开关与交互**另单**〔原写 `V89` ⇒ **口径订正**见 §11.1〕 |
| **事件留痕（可选）** | `processing_operation_claims`（只追加：`claim` / `release` / `complete`）—— **仅 C 模式需要**；A 模式**不写**。⚠️ 本设计**建议 `V92` 不建这张表**（YAGNI：A 模式零消费者），C 模式另立迁移。✅ **已按建议落地**：`V92` **未建**该表〔原写 `V89` ⇒ **口径订正**见 §11.1〕 |

---

## 5. 防呆与自动计件

### 5.1 一次扫码 ⇒ 两件事（真值源 `:57`）

| 事 | 落点 | 判据 |
|---|---|---|
| **推进工序进度** | `processing_position_operations.done_qty` + `status='done'` + **`done_at`** | CAS 原子（F14 逐字复用） |
| **记录个人计件** | `production_work_logs`（数量 × 快照单价） | F13 口径逐字复用 |

### 5.2 完成动作的四步（同事务，§4.2 方案 A）

```
complete(set_no, order_item_id, [operation_id], [qty], worker, clientRequestId):
  ⓪ 幂等占位（X-Client-Request-Id，F15 逐字复用）⇒ 同键直接回放，不执行
  ① 解析 token / set_no ⇒ (set_id, order_item_id)，并校验工序归属（防呆④：**候选集成员资格**，§5.3 ④）
  ② 定工序：operation_id 显式给出则校验归属；否则 §3.2 推断
     ⇒ 推断出零道 / 多道 ⇒ 拒绝（§3.3 硬约束，不记账）
  ③ 防呆：幂等 / 数量上限（拒绝不 clamp）/ 非本部位码（§5.3）
     ⚠️ 不校验前道（裁定②-2「不拦生产顺序」）
  ④ 事务：insert work_logs → CAS 推进 done_qty + done_at → 必完全绿则 completed → 首工序则 in_processing
```

### 5.3 防呆四条 ⇒ **可执行断言**（真值源 `:56` 逐条，**含本设计的改判**）

| # | 真值源原文 | 断言形态（可执行） | 现状 | 本设计处置 |
|---|---|---|---|---|
| ① | 「**幂等**（重复扫提示已报）」 | `X-Client-Request-Id` 同键 ⇒ 不执行 + 回放首次结果 + `replayed=true`（F15 逐字复用）。**扫描**是只读 ⇒ 天然幂等 | ✅ 已落码（`report`） | **新端点复用同一机制**（不新造） |
| ② | 「**越站提示**（非本工序）」 | ⚠️ **改判**：**不再拦截**，改为**推断时自然避开**（默认给「下一道待做」）+ 改道时**只提示不阻断** | ✅ **闸门已删除**（issue #4694，2026-09-20）：原「422 拒绝」（`assertPredecessorsDone`）整条删除 ⇒ 顺序**不拦**（跳站按实际工序正常记账） | ✅ **已落码**（#4694）：删除该闸门 + 既有 422 断言**改钉**为「放行」+ 登记为放宽（§10 C9）。**本设计只剩增量**：推断时自然避开 + 只提示不阻断 |
| ③ | 「**数量上限校验**（≤应做数量+合理损耗）」 | `done_qty + 本次合格数 <= qty`，否则 422 `REPORT_QTY_EXCEEDS_PLANNED`（**拒绝不 clamp**） | ✅ 已落码（`assertWithinPlannedQty`） | 无（**「合理损耗」当前实现为 0 容差** ⇒ 待裁定 §8 A4） |
| ④ | 「**非本部位码提示**」 | **断言（候选集成员资格，不是字面等式）**：显式给出的 `operation_id` **必须属于本次扫码的候选集** —— ① 部位级候选（该套该部位）**∪** ② §3.2② 的**套级回落候选**（本部位无待做 ⇒ 套级工序）；不在其中 ⇒ 422 `OPERATION_NOT_IN_SCAN_TARGET` + 指名（<s>**原写**：`op.order_item_id == token.order_item_id`，不等 ⇒ 422 `CODE_POSITION_MISMATCH`</s> ⇒ **口径订正见本条注**） | ⚠️ **F18：今天形式上是空的**（码无部位 ⇒ 只能校验「属于本加工单」） | ✅ **本设计的核心增量**：码带部位 ⇒ 这条防呆**才真正成立** |
| **⑤（本设计新增）** | **裁定②-2 的硬约束** | **断言**：写 `production_work_logs` 前 `operation_id` **唯一确定**；否则 422 `OPERATION_AMBIGUOUS` / `NO_PENDING_OPERATION` 且**不记账**（红证见 §3.3） | ❌ **今天不存在**（端点在 URL 里强制给了 `operationId`，**没有「不确定」这个态**） | ✅ 新增（**因为 A 模式把「选工序」交给了系统**） |

> 🔴 **④ 的口径订正（issue #4791，2026-09-20；来自 #4698 切片④ 核清，主会话已裁定）—— 两处，原文措辞一律保留为历史留档**：
> **① 判据名统一（同一判据曾有两个名字）**：本文原写 `CODE_POSITION_MISMATCH`，但**代码从未实现该名**
> （`origin/main` 全仓只有本文 1 处、代码 0 处）—— 落码实际用的是 **`OPERATION_NOT_IN_SCAN_TARGET`**
> （已进 `CONTRACT-LEDGER.md`）⇒ **保留代码名**，本文统一指向它。
> **`CODE_POSITION_MISMATCH` = 曾用名（已废，勿再引用）**。
> **② 判据形态从「字面等式」改为「候选集成员资格」**：原写 `op.order_item_id == token.order_item_id` ——
> **与 §3.2② 套级回落直接冲突**：扫**纱帘**的码、本部位干完 ⇒ 系统给**套级工序**，
> 其 `order_item_id` 是**承载部位（布帘）** ⇒ **字面等式必然不等** ⇒ 照字面实现会**拒掉套级回落**，
> 打断 D4（防死锁）。⇒ 现实现按**候选集成员资格**判定（已落码 + 有承重红证：去掉部位过滤 ⇒
> 跨部位报工被接受、真写了 `work_logs`）；**「回落时按套级候选集判定，不是 `order_item_id` 等式」**。
>
> 🔴 **两条必须登记的行为变化**：
> **②放宽**（越站不再拦截）与 **④收紧**（越部位报工被拒）。
> 两者都是**用户裁定 / 真值源的直接结果**，但**必须显式写进落码单的验收判据**，
> 否则既有测试（断言 422 `OPERATION_SEQUENCE_VIOLATION`）会红而无人知道原因。

### 5.4 自动计件（真值源 `:57` 后半句）

| 项 | 设计 |
|---|---|
| 写入时机 | **完成的那一刻**（同事务，§4.2） |
| 金额口径 | `Σ(qualified_qty × unit_price)`；**单价从工序实例快照进报工行**（F13 逐字复用：「聚合只读本行，永不回查实例」） |
| 系数 | **不写**（`factor` 自 #4589 退场，`parseSpecs` 注释逐字：「`factor` 列**保留**但自 #4589 起无人写它」） |
| 返工 / 报废 | `work_type ∈ {rework, scrap}` ⇒ **不计件、不累加**（V49 注释逐字） |
| 单工序一人制 | 无分摊（真值源 `:42`） |
| **按套下钻** | 读 `production_work_logs` → `operation_id` → **工序实例的 `set_no` 快照**（§2.2）⇒ **零改动 `production_work_logs`** |
| 两套账分离 | **不碰**对外加工费（真值源 `:45`）；本设计只写**内部计件**侧 |

**为什么不在 `production_work_logs` 加 `set_no` 列**：
① 该表的红线是「**明细不可变**」+ `docs/design/worker-scan-terminal.md` §7 逐字「**不改** `production_work_logs`」；
② 套号**不在报工那一刻产生**（它在实例化时产生）⇒ 写进报工行是**冗余的第二次快照**，
而经由 `operation_id` 取实例快照**同粒度、零漂移**（实例行的 `set_no` 是实例化时的固化值）。

---

## 6. 「卡在哪」：判据、所需数据、阈值来源

> **裁定②-3**：「卡在哪」**在 A 模式下的口径 = 只有「没开工」那一种**：
> `pending` + **上道已完成** + **超过阈值仍未扫** ⇒ 卡住（**不需要** `started_at` 就能判）。
> **C 模式（开工选扫）** 解锁第二种（「开了没完」）—— 见 §4.4。

### 6.1 判据总表

| 卡法 | 判据（**列来源**） | 语义 | 处置 | 模式 |
|---|---|---|---|---|
| **① 没开工**（**A 模式唯一**） | `status = 'pending'` **AND** 立即前道（同部位 `seq` 最大的更小 `seq`）`status = 'done'` **AND** `now - predecessor.done_at > T_wait` | **上道已交，这道没人扫** ⇒ 等料 / 等人 / 派工漏了 / 工件躺在角落 | 催料 / 派工（通知班组长；大屏标红） | **A** |
| **② 开了没完** | `status = 'in_progress'` **AND** `now - started_at > T_work(工序)` | **有人拿了超时未完成** | 看「谁在做、卡了多久」（`worker_name` + `started_at`） | **仅 C**（§4.4） |
| ③（附加，免费） | 某套全部 `done` 但加工单非 `completed` | 必完口径不一致（异常） | 登记告警（§7.3 的判据保证不该出现） | A + C |
| ④（附加，免费） | `status = 'done'` 且本套还有 `pending` | 正常在产 | —— | A + C |

**关键**：A 模式的 ① **只需要 `done_at`**（本设计新增的**唯一**必需时序列）。
今天的替代品是 `updated_at` —— ⚠️ **不可用**：它会被**任何**更新污染
（改名、改单价、重新实例化、其他字段的任何写入）⇒ 用它算「等了多久」会**静默给出错数**。

### 6.2 所需数据（逐项，标注来源与今天有没有）

| 数据 | 来源 | 今天有吗 |
|---|---|---|
| 工序的「未完成」态 | `processing_position_operations.status` | ✅ 有（但只有两态） |
| **前道完成时刻**（① 的唯一必需输入） | **新增** `done_at` | ❌ **无**（本设计新增，**A 模式必需**） |
| 套号 | **新增** `set_no`（实例快照） | ❌ **无**（本设计新增） |
| **认领人 / 认领时刻**（② 的输入） | **新增** `worker_id` / `worker_name` / `started_at` | ❌ **无**（**仅 C 模式需要**） |
| **阈值 `T_wait`（等开工多久算卡）** | ❌ **全仓无**（F8） | ❌ **无**（§6.4） |
| **阈值 `T_work(工序)`（标准工时）** | ❌ **全仓无**（F8） | ❌ **无**（**仅 C 模式需要**，§6.4） |

### 6.3 一条可执行判据（供落码时直接用）

```sql
-- A 模式卡点报表：按套 × 工序列出「没开工」
SELECT s.set_no, o.operation_name, o.seq, o.status,
       p.done_at,
       EXTRACT(EPOCH FROM (NOW() - p.done_at)) / 3600.0 AS stalled_hours   -- 等了多久（小时）
FROM processing_position_operations o
JOIN processing_order_sets s ON s.id = o.set_id AND s.deleted = 0
LEFT JOIN processing_position_operations p                          -- 立即前道（同部位、seq 最大且更小）
       ON p.processing_order_id = o.processing_order_id
      AND p.order_item_id IS NOT DISTINCT FROM o.order_item_id
      AND p.seq = (SELECT MAX(p2.seq) FROM processing_position_operations p2
                    WHERE p2.processing_order_id = o.processing_order_id
                      AND p2.order_item_id IS NOT DISTINCT FROM o.order_item_id
                      AND p2.seq < o.seq AND p2.deleted = 0)
      AND p.deleted = 0
WHERE o.tenant_id = ? AND o.deleted = 0
  AND o.status = 'pending'
  AND p.done_at IS NOT NULL
  AND NOW() - p.done_at > T_wait_interval
ORDER BY stalled_hours DESC;
```

⚠️ **`IS NOT DISTINCT FROM`** 不是装饰：存量行的 `order_item_id` 为 NULL（V69 逐字），
普通 `=` 会让存量行的「前道」永远匹配不到 ⇒ **存量单的 ① 判据静默失效**（该红不红）。
⚠️ **首道工序（`seq` 最小）没有前道** ⇒ `p.done_at IS NULL` ⇒ **不进卡点表**。
这是**正确的**（首道工序的「等」是「等派工」，判据应另立 —— 见 §9 U7）。

### 6.4 ⚠️ 阈值从哪来：**实测全仓没有「标准工时」**（列为待裁定）

**实测命令与读数**（F8 复算）：

```bash
git grep -niE "标准工时|standard_hours|std_hours" origin/main
# → 零命中（含 docs/ / *.sql / *.py / *.java）
```

⇒ **如实说：仓库里没有任何「标准工时」数据、字段、常量或真值源**。
**「卡了多久」的阈值没有现成来源** —— 这是**待裁定**项（§8 A3），本设计**不替业务决定、不编数值**，
但给出**三条可选来源**（按「最少代码 + 可解释」排序）：

| 方案 | 阈值来源 | 代价 | 评价 |
|---|---|---|---|
| **S1（推荐）** | **同租户历史中位数**：`median(now - started_at)` over 已完成的同 `(operation_name, unit)` 实例（滚动 90 天；样本 < N 时回落 S3） | **零业务填数**；随生产自然收敛；可解释（「这道活通常 2 小时，现在 6 小时」） | 冷启动期不准 ⇒ 「样本不足」时**显式标注**（不静默用中位数） |
| S2 | 工序库新增列 `standard_hours NUMERIC(6,2)`（`production_operations`），商家可填 | 要商家填数（不填 = 空 ⇒ 仍需回落） | 最准，但要**新增主数据字段 + 界面**（与「最少代码」冲突，除非客户要求） |
| S3 | **全局默认常量**（如 `T_wait = 4h`；C 模式 `T_work = 8h`），可配 | 最省；「一刀切」会误报 | **只能当兜底**，不能当唯一口径 |

**本设计建议**：`T = S1 ?? S3`，且**响应里带 `threshold_source`**（`history` / `default`）——
**「阈值从哪来」必须可解释**（与既有 `qty_source`「兜底不静默」同族纪律）。

⚠️ **两条诚实边界**：
① **A 模式的 S1 不能用 `started_at`**（A 模式没有开工事件）⇒ A 模式的 S1 只能退化为
**「同一工序在别的套/单上的报工间隔中位数」**（口径更粗，需在落码时**显式标注**），
或直接用 S3。**C 模式才真正有 `started_at`** ⇒ S1 在 C 模式下最准。
② 「标准工时」在行业里通常是**按部位 × 工序**分设的（真值源 `:27` 逐字：「工序按部位分设：同一道工序在布/纱/帘头上单价各自不同」）⇒ 若走 S2，键必须是 `(工序, 部位)`，**不是**工序单键。

---

## 7. 联动与口径

### 7.1 术语：一樘窗 vs 套（界面用词落点）

| 术语 | 对谁 | 界面落点 | 逐字依据 |
|---|---|---|---|
| **一樘窗** | 客户 / 设计 / 施工 / 售后 | **客户侧与销售侧**（报价单、订单确认、施工单、售后工单）：写「一樘窗」 | 用户裁定（2026-09-20）「一樘窗 = 一套」；「樘」是门窗行业标准量词；本仓 javadoc 已在用「一樘窗的一行」 |
| **套** | 车间 / 生产 / 交付 | **车间侧全部界面**（工人扫码端、加工单、工序进度、计件、打包、发货、大屏）：**只写「套」** | 与 ERP、与工人一致（真值源 `:9`「第 N 套/共 M 套」） |
| **部位** | 车间 | 「布帘 / 纱帘 / 帘头」（`position_kind`）；**展示名**另给（`position_name`） | 实测：`position_name` 是**展示名**不是帘种（`ProcessingPositionOperation` javadoc 逐字警告） |
| **车间分组** | 车间 | 第一层用行业正名：**裁床 / 车位 / 烫工及后整 / 质检 / 包装** | `docs/curtain-production-process-standard.md` §1（用户裁定，2026-09-20） |

**两条硬约束**：
① **同一处不混用**：「一樘窗」与「套」不得在同一句 / 同一卡片里指同一件事；
② **面向车间的界面用「套」**（「樘」是生僻字，工人念不出、打不出）。

**术语在数据上的对应（**不新造**）**：
`一樘窗` = `套` = `processing_order_sets` 的一行 = 一个 `craftLineId` 组；
`部位` = `order_items` 的一行 = `processing_position_operations.order_item_id`。

### 7.2 与报工 / 计件 / 打包 / 发货的接口口径（谁读套号、怎么用）

| 消费方 | 读什么 | 怎么用 | 现状 |
|---|---|---|---|
| **扫码报工** | `processing_set_part_tokens.token` → `(set_id, order_item_id)` | 定位 + 防呆④（§5.3） | 新增 |
| **工序进度读面** | `processing_position_operations.set_no` | 「按套进度」（`set_progress`） | 新增（**不破坏**既有 `current_operation` / `pending_operations` / `done_operations`，只**加键**） |
| **计件** | 报工行 → `operation_id` → 实例行 `set_no` | 按套下钻（真值源 `:46` 的下钻链「报工 → 工序实例 → 部位 → **套** → 加工单 → 订单」） | 新增（**零改动** `production_work_logs`） |
| **打包** | `processing_order_sets.set_no` | 打包标签 = 单号 + **套号** + 部位（`docs/design/worker-scan-terminal.md` §3.4 逐字要求「单号 + 套号 + 部位 + …」） | 新增（**打包本身无需代码**：`外帘装袋` 报工即完工，既有裁定） |
| **发货** | `processing_order_sets.set_no` | 按套发货 / 点交（「10 楼第 14 套」） | **本设计不落码**，只保证**套号可被引用**（§8 A5 待裁定） |
| **售后** | `set_no` | 「10 楼第 14 套」可定位（issue #4687 目标之一） | 新增（可查即可） |

### 7.3 加工单状态机联动（真值源 `:29`）

**今天实测（F9）：`is_start_marker` 无消费者 ⇒ 首工序报工**不会**让加工单进入生产中。**

| 事件 | 动作 | 状态机合法性（F10 实测） |
|---|---|---|
| **首工序完成**（完成 `is_start_marker = TRUE` 的工序） | 加工单 `generated/issued → in_processing` + 写 `in_processing_at` | ⚠️ **`generated` 不能直达 `in_processing`**（`STATUS_TRANSITIONS` 只允许 `generated → issued`）⇒ 若当前是 `generated`，**必须先 `issued`**（或明确裁定允许 `generated → in_processing`，见 §8 A6）。**不得**用裸 UPDATE 绕过状态机（#4117 的教训：绕过状态机 ⇒ 订单既发不了货也回不去） |
| **必完工序全绿** | 加工单 `→ completed`（`markCompletedIfActive`，**逐字复用**） | ✅ 已落码（issue #4117 口径） |

⚠️ **与真值源 `:29` 的一处不一致，如实登记**：真值源写「首工序触发**订单**进入生产中」，
而 issue #4687 的评论写「首工序开始 ⇒ **加工单** `producing`」。**两者不是一回事**：
实测（`ProcessingOrderMapper.markCompletedIfActive` javadoc 逐字）——「订单状态机不设 producing→completed…
⇒ 把加工单置 completed、订单留在 producing，发货链才通」。
⇒ **本设计按「加工单置 `in_processing`」落**（与 #4117 同族）；
**订单**是否同步进 `producing` **另议**（§8 A6）。
⚠️ **A 模式下「首工序完成」即「首工序开始」**（没有开工事件，报工就是完工）⇒ 触发点 = **完成**，不是认领。

---

## 8. 待用户裁定（**集中列出，不替业务决定**）

| # | 问题 | 选项 | 设计建议（**仅供参考，不是决定**） |
|---|---|---|---|
| **A1** | **旧码的降级交互**（裁定②-1 已定「一部位一码」，但**存量旧码只到加工单级**） | ① 扫旧码 ⇒ 强制选部位（§2.6）② 旧码直接失效要求重打 | **①**：强制失效会打断在产单（§2.6） |
| **A2** | **A 模式的卡点阈值 `T_wait` 从哪来**（**标准工时全仓没有**，F8） | S1 历史中位数 / S2 工序库填 `standard_hours` / S3 全局默认常量 | **S1 ?? S3**，响应带 `threshold_source`；⚠️ A 模式无 `started_at` ⇒ S1 口径更粗（§6.4 边界①） |
| **A3** | **C 模式（开工选扫）是否要做、何时做** | ① 不做 ② 现在做（可选开关）③ 将来做 | **③ 将来做**（裁定②-3：C 只作**预留**）。`V92`（**已落码**）建列（**零行为变化**），开关与交互**另单**〔原写 `V89` ⇒ **口径订正**见 §11.1〕 |
| **A4** | **数量上限的「合理损耗」** | ① 0 容差（现状）② 允许配置损耗率 | **②**（真值源 `:56` 逐字写了「+合理损耗」，现状是 0 ⇒ 与真值源有差）；但**不得**静默 clamp |
| **A5** | **发货 / 点交是否按套** | ① 按单（现状）② 按套 | 需业务：工程单「22 套分 3 车发」是真实场景；本设计**只保证套号可被引用** |
| **A6** | **首工序触发的是「加工单」还是「订单」进生产中**；`generated` 能否直达 `in_processing` | 见 §7.3 | 按 #4117 同族落**加工单** `in_processing`；`generated` 直达需裁定 |
| **A7** | **一樘窗 = 一套 与 #4373「一个窗帘商品 = 1 套」冲突** | 见 §10 C4 | **以本单（#4687）为准**（用户 2026-09-20 裁定「一樘窗 = 一套」）；~~**需要一份显式改判**（否则 #4373 的验收判据仍按旧口径）~~ ⇒ ✅ **已交付：issue #4693** —— 改判落在 `docs/design/position-instance-routing-model.md` **§2.1.1**（就地改判 + 依据三样齐全 + 历史留档 + 可执行断言） |
| **A8** | **旧码是否设强制失效日** | ① 不设（自然退场）② 设截止日 | **①**：强制失效会打断在产单；撤销端点（既有）已提供「立即作废」的手动出路 |
| **A9** | **`processing_operation_claims`（认领事件表）现在建不建** | ① 不建（C 模式另立迁移）② `V92` 一起建〔原写 `V89`〕 | **①**（YAGNI：A 模式零消费者；「最少代码」阶梯）⇒ ✅ **已按 ① 落地**：`V92` **未建**该表 |

---

## 9. 无法判定（**如实登记，不猜**）

| # | 无法判定的事 | 为什么判不了 | 需要什么才能判 |
|---|---|---|---|
| U1 | **存量已实例化单的套归属** | `processing_position_operations.order_item_id` 为 NULL 的存量行**无法可靠回填**（V69 逐字裁定：「猜错比留空更糟」）⇒ 这些行的 `set_no` **只能留空** | 无需判：留空 + 读面兜底（与 V69 同款处置） |
| U2 | **「合理损耗」的业务值** | 真值源 `:56` 写了「+合理损耗」但**没给数值**；行业实证（ERP 截图）也没有 | 客户确认（§8 A4） |
| U3 | **标准工时** | F8 实测全仓零命中 | §6.4 的 S1/S2/S3 三选一（§8 A2） |
| U4 | **`外帘打卷/装袋/发货` 是否真的每樘窗一次** | 既有登记：#4384 逐字「套级工序先按**每樘窗一次**实现，打卷是否**每帘**一次**留成可配**」 | 客户确认；本设计**沿用**既有口径（每樘窗一次），不新增判断 |
| U5 | **`generated` 能否直达 `in_processing`** | 真值源 `:29` 只说「标记生产开始」，没说从哪个状态起算 | §8 A6 裁定 |
| U6 | **「一樘窗」在客户侧是否等同「一个窗户」的全部部位** | 用户裁定「一樘窗 = 一套」已定**量词**；但**一樘窗含哪些部位**由 `craftLineId` 决定，而 `craftLineId` 由**下单侧**填写 | 下单侧口径（#4395 写侧）；本设计**逐字沿用** `craftLineId` 语义，不另立判据 |
| U7 | **首道工序（`seq` 最小）的「卡」怎么判** | 它没有前道 ⇒ §6.3 的 `p.done_at` 判据**不适用**；而「等派工」的起点（加工单下发？上料？）在数据上**没有事件** | 需业务定义「首道工序的等待起点」（可能是加工单 `issued_at`）；本设计**不猜** |

---

## 10. 与既有设计的冲突点（**逐条登记**）

| # | 冲突 | 涉及文档 / 代码 | 处置 |
|---|---|---|---|
| **C1** | **`worker-scan-terminal.md` 的「条码」章节要求「单号 + 套号 + 部位」**，但当时套号不存在 | `docs/design/worker-scan-terminal.md` §3.4 | **本设计补齐**：套号落库（§2.2）+ 一部位一码（§2.3）⇒ 该节从「要求」变成「可落」 |
| **C2** | **`public-operations-and-craft-ui.md` 的两层模型**（工序 / 打包发货）**不涉及扫码闭环**，但「打包发货」层的成员（`打包` / `打卷` / `装袋` / `发货`）正是套级工序 ⇒ 推断算法必须处理「扫部位码却要做套级活」 | `docs/design/public-operations-and-craft-ui.md` §3.2 | **本设计 §3.2② 显式处理**（套级回落 + `rerouted`），**不改**两层模型的判据 |
| **C3** | **`operation-slot-model.md` 要改的是「工序序列」的推导（槽位 + 锚位派生）**；本设计的推断算法**假定序列已定** | `docs/design/operation-slot-model.md` | **不冲突，但有依赖**：槽位模型落地后实例化序列会变 ⇒ 本设计**读实例**（`seq`），**不读路线模板** ⇒ **自动跟随**，无需改 |
| **C4** | 🔴 **「一樘窗 = 一套」vs #4373「一个窗帘商品 = 1 套」** | `docs/design/position-instance-routing-model.md` §2.1 逐字：「#4373 的用户裁定是「**我觉得就是 1 个窗帘商品 = 1 套**」⇒ 套 ≡ 明细行」+「一个窗户要布帘 + 纱帘 + 帘头」在这种口径下会算成 **3 套**（而不是 1 套 3 部位）」 | **以 #4687（用户 2026-09-20）为准**：套 = **樘窗组**（`craftLineId`），不是明细行。✅ **已改判（issue #4693，2026-09-20）**：§2.1 就地改判为 **§2.1.1**（用户裁定逐字 + 日期 + 单号 + 本冲突 C4 + 历史留档 + 可执行断言）⇒ 旧口径**不再作为现行口径**出现。✅ **代码读数也已改判（issue #4725，2026-09-20）**：`ProductionService` 计件「按套下钻」由 `order_item_id`（= 部位行）改为 **V92 套号 / 樘窗组键**、`ProcessingFeeCalculator` 的「套数恒 1（1 套 = 1 个订单行）」改为**同一樘窗内同名选项只收一次** ⇒ §2.1.1 的「已登记的偏离」**已销账**（该处只许缩短） |
| **C5** | **`domain-model-review-…md` 的 S3**「套成为一等公民」还包含「**组合单**（跨套视图）」 | `docs/design/domain-model-review-sales-production-finance.md` §2.2 | **本设计只满足「套号落库 + 按套下钻」，不落「组合单」** ⇒ S3 **部分满足**，组合单**另立单**（如实登记，不假装已解决） |
| **C6** | **`worker-scan-terminal.md` §7 红线「不改 `production_work_logs`」** | 同上 §7 | **本设计遵守**（按套下钻走实例快照，§5.4） |
| **C7** | **V69 的「存量行留空」策略**被本设计**第二次复用**（`set_id` / `set_no` 可空） | `backend/admin-api/src/main/resources/db/migration/V69__add_position_identity_to_position_operations.sql` | **同款处置**（留空 + 读面兜底）⇒ 一致性保持；**不**引入第二种存量兼容范式 |
| **C8** | **`report` 端点刻意不加 `@Transactional`**，而「完成」要落三处 | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java` 的 `report` javadoc | **不改 `report`**；**新增**事务化的扫码完成入口，幂等占位在外层（§4.2 方案 A） |
| **C9** | 🔴 **越站防呆原为 422 拒绝**（`assertPredecessorsDone`），与**裁定②-2「不拦生产顺序」直接冲突** | 同上 | ✅ **已落码**（issue #4694，2026-09-20）：闸门**已删除**（`assertPredecessorsDone` 整条删除，不留死代码），既有 422 `OPERATION_SEQUENCE_VIOLATION` 断言**已改钉**为「越站 ⇒ 放行」，并登记为**放宽型行为变化**（§5.3 ②）。本设计继承该口径，**不得**再加回顺序闸门 |
| **C10** | **防呆④「非本部位码」今天形式上是空的**（F18：码无部位 ⇒ 只能校验「属于本加工单」） | 同上 `doReport` 的三重校验 | **本设计补全**（码带部位 ⇒ **候选集成员资格断言**〔<s>原写「相等断言」</s> ⇒ 口径订正见 §5.3 ④ 表后注〕）；登记为**收紧型行为变化**（§5.3 ④） |
| **C11** | **本设计**新增**一条防呆（⑤ 工序必须确定）**，真值源 `:56` 只写了四条 | 真值源 `docs/curtain-production-rules.md` `:56` | **显式登记为「真值源四条 + 裁定②-2 的硬约束」**，不假装它是真值源原文 |
| **C12** | 🔴 **布料主线真值源仍是旧口径**：`routing.py` 的 `FABRIC_MAINLINE_STEPS` = `["配料","打包"]`，而 #4673 已**改判**为 `裁剪`、V88 已按裁定落码；**钉住它的测试文案还把 `配料` 称「裁定」= 过期裁定** | `backend/ai-agent-service/app/production/routing.py` 的 `FABRIC_MAINLINE_STEPS`；`backend/ai-agent-service/tests/test_production/test_fabric_route.py`；口径真值源 `docs/design/craft-calc-and-fabric-routing.md` §6 判据 #10 | **只登记，不修**（issue #4701 的 P1）：ai-agent 属用户裁定「本会话不动工」（#4652）⇒ 等 ai-agent 排期时**连同其钉住测试一起改判**（文案的「裁定」必须改成「已被 #4673 改判为 `裁剪`」）并同步 `seed.json`。⚠️ **当前零影响**（`build_route_v2` 生产代码**零消费方**，`routing.py` 自述）⇒ **未来一改即假红** |

---

## 11. 迁移、回滚、停止条件

### 11.1 迁移号（**实测现取，不凭记忆**）

```bash
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ \
  | grep -o 'V[0-9]*' | sort -t V -k2 -n | tail -1     # → 迁移头号（**现取**，本文不写死）
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ | grep -E 'V89|V90|V92'
```

⇒ ~~**本次迁移 = `V89__add_processing_order_sets_and_scan_loop.sql`**（新文件）。~~
✅ **本设计的数据层已落码**：**#4698 切片⓪**（PR #4722，merge `d295097bb`，2026-09-20）落
`backend/admin-api/src/main/resources/db/migration/V92__add_processing_order_sets_and_scan_loop.sql`
—— 与 §11.2 逐条一致（2 表 + 4 唯一键 + 实例 6 列含 `done_at`）。
⚠️ **后续切片（§14 的 ①~⑤）的新迁移号一律「落码时现取、不写死」** —— 迁移头会随任何人的 PR 前进。

> 🔴 **口径订正（issue #4731，2026-09-20）：本文原写「本次迁移 = `V89`」，现改为「数据层已落 `V92`」。**
> **① 当时基线**：`origin/main` 迁移头 = `V88`、`grep -c V89` = **0** ⇒ 顺推「本设计的迁移号 = `V89`」
> （**原措辞保留在上一段删除线里**）。
> **② 后来变了**：`V89` 被 `V89__backfill_fabric_seed_for_existing_tenants.sql` 占用、
> `V90` 被 `V90__unpriced_is_not_zero.sql` 占用；本设计的数据层由 #4698 切片⓪ 落在 **`V92`**。
> **③ 故结论改为**：本设计数据层 = **`V92`（已落码）**，后续切片**落码时现取**。
> ⚠️ **仍然成立**：**已发布迁移不可改** —— F17 的指纹守卫（条数**现取，不写死**）；
> 改旧迁移 = 指纹红 + 只对全新库生效 ⇒ 存量环境「CI 绿、功能静默缺失」，issue #4235。
> 落码判据锚点 = `tests/unit_ci_workflows/test_set_code_storage_v92_migration.py`。

### 11.2 `V92` 改了什么（**已落码**；逐条 + 幂等要求）

| # | 动作 | 目标 | 幂等要求 |
|---|---|---|---|
| ① | 建表 `processing_order_sets` | 新表 | `CREATE TABLE IF NOT EXISTS` |
| ② | 建两个唯一索引 | `uk_processing_order_sets_index` / `uk_processing_order_sets_no` | `CREATE UNIQUE INDEX IF NOT EXISTS` |
| ③ | 建表 `processing_set_part_tokens` + 两个唯一索引 | 新表 | 同上 |
| ④ | `processing_position_operations` 增 **6 列**：`set_id` / `set_no` / **`done_at`** / `worker_id` / `worker_name` / `started_at` | 既有表 | `ADD COLUMN IF NOT EXISTS`（**全部可空**，存量行留空） |
| ⑤ | `status` 取值域**扩一条**：`pending` / **`in_progress`**（**C 模式预留**）/ `done` | 列注释 | `COMMENT ON COLUMN`（**不改列定义**：`VARCHAR(16)` 装得下） |
| ⑥ | 索引：`(tenant_id, status, done_at)`（A 模式卡点报表用） | 新索引 | `CREATE INDEX IF NOT EXISTS` |
| ⑦ | **回填**：为**每个租户**的每个活跃加工单建套行 + 分配 `set_index` + 回填实例行 | `processing_order_sets` / `processing_position_operations` | 见 §11.3（**按 `items_snapshot` 行序 + `craftLineId` 分组**，确定性可复现） |
| ⑧ | **不建** `processing_operation_claims`（§8 A9 建议 ①，YAGNI） | —— | C 模式另立迁移 |
| ⑨ | **不碰** `processing_orders.qr_token` / `production_work_logs` | —— | **红线**（§2.6 / C6） |
| ⑩ | **同步 bootstrap 终态** `docs/sql/schema.sql` | 新建库路径**不跑迁移链**（既有逐字警告：「只写迁移 = 新建库无该列」，同 #3270 形态） | 手工同步终态 |
| ⑪ | 登记迁移指纹 | `tests/unit_ci_workflows/migration_fingerprints.json` | 追加 `V92__…` 的 `sha256`〔原写 `V89__…` ⇒ **口径订正**见 §11.1〕 |

> ✅ **落码核对（2026-09-20，#4698 切片⓪ / PR #4722）**：上表 ①~⑪ **逐条已落** ——
> 其中 ⑧「**不建** `processing_operation_claims`」= 按 §8 A9 建议 ① 落地。
> 机械判据（六件事逐条 + 注入式红证）= `tests/unit_ci_workflows/test_set_code_storage_v92_migration.py`。
> ⚠️ **本表描述的是「数据层」**：⑨ 的两条红线（**不碰** `processing_orders.qr_token` /
> `production_work_logs`）与「C 模式三列零消费者」都在该测试里**双向钉死**（该出现的出现、不该出现的零命中）。

### 11.3 回填的确定性与边界

```
for each tenant (FROM tenants WHERE deleted = 0):          -- 既有 V79 同款按租户循环
  for each processing_order (deleted = 0):
     snapshot = processing_orders.items_snapshot           -- 固化真相（唯一输入）
     groups   = 按 craftGroupKey(entry) 分组，顺序 = 快照中出现次序
                 craftGroupKey = craftLineId ?? itemId     -- 与 ProcessingOrderService 逐字同口径
     过滤：跳过「被吸收的配布边行」与「无 processingItems 的行」  -- 与实例化循环同口径
     for i, group in enumerate(groups, start=1):
        INSERT processing_order_sets(set_index=i, set_no=po_no + '-' + pad3(i),
                                     craft_line_id=group.key,
                                     position_item_ids=group.itemIds)
        ON CONFLICT (tenant_id, processing_order_id, set_index) DO NOTHING
     # 实例行回填：只回填 order_item_id 非空的行（§2.5）
     UPDATE processing_position_operations o
        SET set_id = s.id, set_no = s.set_no
       FROM processing_order_sets s
      WHERE s.processing_order_id = o.processing_order_id
        AND o.order_item_id IS NOT NULL
        AND o.order_item_id = ANY (s.position_item_ids::text[])   -- 只在行标识可信时归属
        AND o.deleted = 0
```

**停止条件（回填必须在这些条件下中止该单 / 该步，而不是硬跑）**：

| # | 停止条件 | 动作 |
|---|---|---|
| 1 | 某加工单的 `items_snapshot` **解析失败**（非法 JSON / 非数组） | **跳过该单 + 记日志**（不中止整个迁移 —— 一条脏数据不该挡住全量） |
| 2 | 某加工单分组数 **> 999** | **中止该单**（套号会溢出 3 位填充）⇒ 记日志 + 该单需人工裁定（**不静默截断**） |
| 3 | 唯一键冲突（并发 / 重复执行） | `ON CONFLICT DO NOTHING` ⇒ 幂等，**不中止** |
| 4 | `processing_position_operations.order_item_id` 为 NULL 的行 | **跳过回填**（§2.5 / U1），**不中止**、**不猜** |
| 5 | 回填行数与「按快照预期行数」**不一致** | **记 ERROR 日志**（不中止）：这是**可观测的**对账读数，供人工复核 |

**回填是「一次性、只增」**：迁移执行后**不再重算**任何 `set_index`（§2.4 规则 2）。

### 11.4 回滚

**回滚 = 新迁移 `<落码时现取的自由号>__rollback_processing_order_sets_and_scan_loop.sql`（不删 `V92`）**
—— 已发布迁移不可改（§11.1）。⚠️ **迁移号一律现取、不写死**（原写 `V90` ⇒ **该号已被占用**；**口径订正**见下）。

```bash
# 复算「下一个自由号」（**本文不写死任何号**）
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ \
  | grep -oE 'V[0-9]+' | sort -t V -k2 -n -u | tail -1    # → 当前迁移头号（现读数：V94）
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ | grep -c 'V93'   # → 0 ⇒ 该号当前空闲
```

⚠️ **落码单已把该号钉成常量**（**符号锚点，不写死数字**）：
`tests/unit_ci_workflows/test_set_code_storage_v92_migration.py` 的 `ROLLBACK_NAME`
（**只登记、不落码** —— 落码即会被 `MigrationRunner` 当场执行 ⇒ 把本迁移立刻撤销；与 V88 / V89 同款处置）。
⚠️ **取号前必须重跑上面的命令**：空号会被任何人的 PR 占掉 —— **本设计自己的 `V89` 就是这么丢的**。

> 🔴 **口径订正（issue #4731，2026-09-20）：本文原写回滚 = `V90__rollback_…`，现改为「现取、不写死」。**
> **① 当时基线**：迁移头 = `V88` ⇒ 顺推「本设计 = `V89`、回滚 = `V90`」（**原措辞保留在上一段**）。
> **② 后来变了**：`V89` 被 `V89__backfill_fabric_seed_for_existing_tenants.sql` 占用、
> `V90` 被 `V90__unpriced_is_not_zero.sql` 占用 —— **两个号都不再属于本设计**（本设计的迁移号最终是 `V92`）。
> **③ 故结论改为**：回滚迁移号**落码时现取**（复算命令见上），**不写死**。
> ⚠️ **事故现场后果（为什么这不是洁癖）**：写死一个**别人的**迁移号 ⇒ 出事时按文档**找不到回滚脚本**。

| # | 回滚动作 | 说明 |
|---|---|---|
| ① | 删两张新表 | `DROP TABLE IF EXISTS processing_set_part_tokens / processing_order_sets` |
| ② | 删 6 列 | `ALTER TABLE processing_position_operations DROP COLUMN IF EXISTS …`（6 个） |
| ③ | 删索引 | `DROP INDEX IF EXISTS …` |
| ④ | **不恢复**任何旧码 / 不改 `qr_token` | 回滚**不触碰**既有列（它们从未被改）⇒ 旧码路径**始终可用** |
| ⑤ | ⚠️ **回滚会丢什么（必须写明）** | 套号与（将来 C 模式的）认领记录**不可恢复** ⇒ 回滚前必须**导出**这些表。**报工明细与计件金额不受影响**（`production_work_logs` 未被改）⇒ **工人已做的活的钱不会丢**（这是把套号放实例快照而不是报工行的第二个收益） |

---

## 12. 验收判据（设计阶段）与逐条自检

issue #4687 的 10 条要求 ⇒ 本文落点：

| # | issue 要求 | 本文落点 |
|---|---|---|
| 1 | 套号：格式 / 落库 / 序号口径 / 不复用 / 唯一键（给理由） | §2.1 / §2.2 / §2.4 |
| 2 | 二维码：内容 / 工序不进码（码量论证）/ 与 `qr_token` 关系 / **存量旧码** | §2.3 / §2.6 |
| 3 | 工序由系统推断：算法 + **一键改** + **硬约束（工序必须确定）** | §3.2 / §3.3 |
| 4 | 数据落点（A 模式必需 vs C 模式预留） | §4.3 |
| 5 | 「卡在哪」：A 模式口径 + 判据 + **阈值来源**（标准工时实测） | §6.1~§6.4 |
| 6 | 防呆四条 ⇒ 可执行断言（**含两条改判 + 一条新增**） | §5.3 |
| 7 | 自动计件：完成 ⇒ 记 `production_work_logs` + 两套账分离 | §5.4 |
| 8 | 加工单状态机联动（首工序 / 必完全绿） | §7.3 |
| 9 | 迁移：回填 + 存量旧码 + 回滚 + 停止条件（迁移号现取） | §11 |
| 10 | 术语：一樘窗 vs 套 —— 界面用词落点 | §7.1 |

**落码阶段的可执行判据（供下一单直接用，每条必须能红）**：

| # | 判据 | 红证形态 |
|---|---|---|
| D1 | 同一加工单内 `set_index` **不重复**且**不复用已删号** | 软删第 2 套后新建套 ⇒ 新套必须是 `MAX+1`（若得 2 ⇒ 红） |
| D2 | `set_no` = `{processing_order_no}-{pad3(set_index)}` | 任一套号格式不符 ⇒ 红 |
| D3 | 扫「第 N 套 · 部位」的码 ⇒ 返回该套**该部位**的下一道未完成工序，**不需要 `operationId`** | 需要客户端传 `operationId` ⇒ 红 |
| D4 | 扫**纱帘**的码、而套级活未完成 ⇒ 返回**套级工序** + `rerouted=true` | 返回「无工序可做」⇒ 红（§3.2 死锁） |
| **D5** | 🔴 **工序必须确定**：`operation_id` 未定（推断零道 / 多道且未显式给）⇒ **拒绝且不记账** | 注入了「未确定却写 `production_work_logs`」⇒ **必红**（§3.3 红证）；**删掉断言后该测试必须变红** |
| **D6** | 🔴 **不拦生产顺序**：前道未完成时，报**后续**工序**成功**（不再 422） | 仍返回 422 `OPERATION_SEQUENCE_VIOLATION` ⇒ 红（裁定②-2） |
| D7 | 完成 ⇒ **同事务**落 `production_work_logs` + `done_qty` + **`done_at`** | 任一处缺 ⇒ 红 |
| D8 | A 模式卡点可答「上道几点完成、等了多久」 | 用 `updated_at` 冒充 `done_at` ⇒ 红（会被任何更新污染） |
| D9 | 传**别的部位**的码报本部位的工序 ⇒ **422**（判据 = **非候选集成员**，§5.3 ④；判据名 `OPERATION_NOT_IN_SCAN_TARGET`，<s>曾用名 `CODE_POSITION_MISMATCH`</s>） | 放行 ⇒ 红（§5.3 ④） |
| D10 | **旧码**（加工单级）仍可解析 ⇒ 返回 `granularity="order"` + **强制选部位** | 旧码 404 ⇒ 红；旧码**默认取第 1 套** ⇒ 红 |
| D11 | 报工金额**逐字不变**（本设计不改既有金额口径） | 任一历史金额变化 ⇒ 红 |
| D12 | 存量单（`order_item_id` 为 NULL 的行）**行为逐字不变** | 读面报错 / 归错套 ⇒ 红 |
| D13 | 首工序**完成** ⇒ 加工单进 `in_processing`（**走状态机，不裸 UPDATE**） | 裸 UPDATE 绕过 ⇒ 红 |
| D14 | 必完工序全绿 ⇒ 加工单 `completed`（**复用 `markCompletedIfActive`**） | 各写一份 ⇒ 红 |
| D15 | **C 模式默认关** ⇒ 默认路径**不要求**任何认领 / 开始交互 | 默认要求点「开始」⇒ 红（裁定②-3） |
| D16 | C 模式开启时，**未认领直接完成**仍合法（认领不是完成的前置） | 未认领被拒 ⇒ 红（§4.4 共存口径①） |

---

## 13. 明确不做（本设计边界）

- ❌ **不改 `production_work_logs`**（C6 红线）。
- ❌ **不改 `processing_orders.qr_token` 的既有语义**（撤销 = 置 NULL，逐字保留）。
- ❌ **不改 `report` 端点**（含**不加** `@Transactional` —— §4.2）。
- ❌ **不做「必须按序」的拦截**（**裁定②-2**；含**删除**既有越站闸门，§5.3 ② / C9）。
- ❌ **不为 C 模式阻断 A 的落地**（**裁定②-3**；`V92` 只建列，零行为变化〔原写 `V89` ⇒ **口径订正**见 §11.1〕）。
- ❌ **不做「一码多部位」为默认形态**（**裁定②-1**；只保留旧码降级时的**选择**能力，§2.6）。
- ❌ **不落「组合单」跨套视图**（C5，另立单）。
- ❌ **不落按套发货单**（§8 A5 待裁定）。
- ❌ **不发明工序 / 单价 / 标准工时数值**（真值源纪律；§6.4 只给来源方案）。
- ❌ **不新造第二套编号**（套号 = 加工单号 + 序号，§2.1）。
- ❌ **不做「一码一工序」**（码量爆炸 + 工艺一改全作废，§2.3）。
- ❌ **不引入第二套存量兼容范式**（复用 V69 的「留空 + 读面兜底」，C7）。
- ❌ **不建 `processing_operation_claims`**（§8 A9 建议 ①，YAGNI）。
- ❌ **不替业务决定** §8 的 9 项。

---

## 14. 落地顺序（建议，供下一单切分）

```
V92（数据层：两张新表 + 六列 + 回填；C 模式列一并建好但零消费者）  ✅ **已落码**
     （#4698 切片⓪ / PR #4722，merge `d295097bb`，2026-09-20；原写 `V89` ⇒ **口径订正**见 §11.1）
   │
   ├─① 扫码解析 + 推断算法（§3）          ← 只读面，可独立验收（D3/D4）
   ├─② 完成（§4.2 事务入口 + 防呆④补全 + 删越站闸门）← **主闭环**（D5/D6/D7/D9）
   ├─③ 卡点报表（§6.3）                    ← 只读面（D8）
   ├─④ 状态机联动（§7.3）                  ← D13/D14
   └─⑤ 旧码降级形态（§2.6）                ← D10（**建议尽早**：存量车间在产）
```

**并行安全边界**：①②④ 同改 `ProductionService` ⇒ **同包**；
③ 只加读面 + 报表 ⇒ 可与 ①②④ 并行（**新文件**）；
⑤ 改解析入口（与 ① 同文件）⇒ 与 ① **同包**。

---

## 15. 复算命令汇总（**本文件所有「实测」结论的一条命令复现**）

```bash
cd <migao repo>
git fetch origin main -q

# F1 套号零命中（代码侧）—— ⚠️ **基线读数**；**现读数已非零**（`V92` 已落码 ⇒ 见 §1.2 F1）
git grep -n "set_no\|套号" origin/main -- 'backend/**' 'tests/**'
# F2 码粒度 = 加工单级
git grep -n "qr_token" origin/main -- '*.java' '*.sql'
# F5/F6 工序实例无 started_at / worker_id / done_at，status 只有两态
git show origin/main:docs/sql/schema.sql | awk '/CREATE TABLE IF NOT EXISTS processing_position_operations/,/^\);/'
# F8 标准工时零命中
git grep -niE "标准工时|standard_hours|std_hours" origin/main
# F9 is_start_marker 无「置 in_processing」消费者
git grep -n "isStartMarker" origin/main -- '*.java'
# F11 樘窗组 = craftLineId；套级工序每组一行
git grep -n "craftLineId" origin/main -- '*.java'
# F18 防呆④今天形式上是空的（只校验租户/软删/归属加工单）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java | grep -n "doReport" -A 20
# F16/F17 迁移头号与指纹覆盖 —— ⚠️ 两者都是「**现取**」读数：迁移头号与指纹条数
#   都会随新增迁移前进 ⇒ 本文**不写死**（F17 的原写「86 条」只作基线留档）
git ls-tree -r --name-only origin/main backend/admin-api/src/main/resources/db/migration/ | grep -o 'V[0-9]*' | sort -t V -k2 -n | tail -1
git show origin/main:tests/unit_ci_workflows/migration_fingerprints.json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['migrations']))"
```

---

## 16. 全文扫描：「设计写了但代码没有」的判据名 / 口径（**只登记，不改判**）

> **来源**：issue #4791（#4698 切片④ 核清）第 2 项要求 —— 顺带全文扫一遍本文的判据名 / 口径，
> 与 `origin/main` 的**实际代码**对照，**给清单**。
> 🔴 **本节的纪律**：**只登记，不裁定谁对** —— 每条只写「设计写了什么 / 代码里是什么 / 差在哪」，
> **处置留给主会话**。本单**只改了 §5.3 ④ 的两处措辞**（主会话已裁定的那两处），其余**一律不动**。
> 复算口径 = `grep` 本文的 `SCREAMING_CASE` 标识符 × `grep` 代码里的实际错误码（双向）。

### 16.1 错误码 / 判据名对照（本文写到的每一个）

| 本文判据名 | 本文落点 | 代码实际（`origin/main` 实测） | 状态 |
|---|---|---|---|
| `OPERATION_NOT_IN_SCAN_TARGET` | §3.3 / §5.3 ④ / §12 D9 | `ProductionScanService` 抛 422；`CONTRACT-LEDGER.md` 已登记；`ProductionScanServiceTest` 钉住 | ✅ **一致**（**曾用名 `CODE_POSITION_MISMATCH`** ⇒ 本单已统一，见 §5.3 ④ 表后注） |
| `OPERATION_AMBIGUOUS` | §3.3 / §5.2 / §5.3 ⑤ | `ProductionScanService` 抛 422；账本已登记 | ✅ 一致 |
| `NO_PENDING_OPERATION` | §3.3 / §5.3 ⑤ | `ProductionScanCompleteService` 抛 422 | ✅ 一致 |
| `REPORT_QTY_EXCEEDS_PLANNED` | §5.3 ③ | `ProductionService.assertWithinPlannedQty` 抛 422 | ✅ 一致 |
| `OPERATION_SEQUENCE_VIOLATION` | §5.3 ② / §10 C9 / §12 D6 | **代码已删除**（#4694 删 `assertPredecessorsDone`）；仅剩测试注释里的历史引用 | ✅ **一致**（本文已按 #4694 改判为「越站 ⇒ 放行」） |
| `CODE_POSITION_MISMATCH` | ~~§5.3 ④~~ | **代码 0 处**（全仓仅本文 1 处） | 🔴 **设计写了、代码从未实现** ⇒ **本单已统一到 `OPERATION_NOT_IN_SCAN_TARGET`** |

### 16.2 反向差异（**代码已落码、本文未登记** —— 如实登记，本单不改）

| 代码实际 | 落点 | 本文状态 |
|---|---|---|
| `SCAN_NEEDS_SELECTION`（422） | `ProductionScanCompleteService`（旧码降级 ⇒ 不默认取第 1 套） | ❌ **本文零提及**（§2.6 只写了「必须让工人选部位」，**没给判据名**） |
| `SET_ALREADY_COMPLETED`（409） | 同上（本套工序都已完成 ⇒ 零写入） | ❌ **本文零提及**（§3.2 ③ 只写「返回『本套已完成』，不报错」——**与「409 拒绝」是两种口径**） |
| `OPERATION_ALREADY_ADVANCED`（409） | 同上 + `ProductionService`（CAS 影响行数 0 ⇒ fail-closed） | ❌ **本文零提及**（F14 只写「影响行数 0 = 被并发推进 ⇒ fail-closed」，**没给判据名**；`worker-h5-scan-and-report.md` 有登记） |

### 16.3 非错误码的判据 / 口径（**SCREAMING_CASE 全量扫描的其余命中，逐条交代**）

> 扫法：`grep -oE '\b[A-Z][A-Z0-9_]{4,}\b' docs/design/set-code-and-scan-loop.md | sort | uniq -c`。
> 其余命中**不是判据名**，逐类交代（**避免"扫出来的东西"被当成"没实现的判据"**）：

| 命中 | 类别 | 判定 |
|---|---|---|
| `SELECT` / `UPDATE` / `INSERT` / `CREATE` / `ALTER` / `TABLE` / `COLUMN` / `INDEX` / `REFERENCES` / `UNIQUE` / `DEFAULT` / `EXISTS` / `COALESCE` / `DISTINCT` / `WHERE` / `ORDER` / `NOTHING` / `CONFLICT` / `NUMERIC` / `JSONB` / `INTEGER` / `BIGINT` / `VARCHAR` / `TIMESTAMPTZ` / `EPOCH` / `EXTRACT` / `COMMENT` / `ASSIGN_UUID` / `ERROR` | SQL 关键字 / 类型 / 函数名 | **不是判据名**（本文 §6.3 / §11 的 SQL 片段） |
| `V92__` / `V89__` / `V88__` / `V87__` / `V86__` | 迁移文件名前缀 | 迁移号**现取**（§11.1 / §15） |
| `CSO260915` | 示例单号 | 示例数据（§2.1） |
| `YAGNI` | 方法论名 | 不是判据 |
| `PENDING` | §3.2 伪码**谓词** | ✅ **已落码**：`ProductionService.isDone`（`done_qty ≥ qty`），`ProductionScanService` 逐字复用 |
| `STATUS_TRANSITIONS` | Java **符号常量名**（F10） | ✅ 存在（`ProcessingOrderService`） |
| `FABRIC_MAINLINE_STEPS` | Python **符号常量名**（§10 C12） | ✅ 存在（`routing.py`）—— **但口径已过期**（登记在 C12，**本单不改**） |
| `ROLLBACK_NAME` | 测试里的**符号锚点**（§11.4） | ✅ 存在（`test_set_code_storage_v92_migration.py`） |

### 16.4 其它「设计写了、代码没有」的口径（非错误码）

| # | 本文写的 | 代码实际 | 状态 |
|---|---|---|---|
| 1 | §5.3 ④：`op.order_item_id == token.order_item_id`（**字面等式**） | **候选集成员资格**（部位级 ∪ 套级回落） | 🔴 **字面实现会打断 §3.2 ② 套级回落（D4 防死锁）** ⇒ **本单已改为「候选集成员资格」** |
| 2 | §6.4 / §8 A2：`threshold_source ∈ {history, default}`（`T = S1 ?? S3`） | **恒为 `default`**（S3）—— `history` 只出现在注释里，**S1 未落码** | ⚠️ **设计写了、代码没有**（代码自述「S1 落码后才会出现 `history`」）⇒ **只登记** |
| 3 | §6.1 ②：「开了没完」（`in_progress` + `started_at`） | **未落码**（仅 C 模式，`V92` 只建列） | ✅ **设计已自述为「C 模式预留」**（§4.4 / §8 A3）—— 非缺陷 |
| 4 | §6.1 ③ / ④：附加两种卡法（「必完不一致」「正常在产」） | 落码的 `stalled.kind` 只有 `not_started` 一种 | ⚠️ **设计写了、代码没有**（③④ 原文标为「附加，免费」）⇒ **只登记** |
| 5 | §12 D9 的 422 判据 | ✅ 已落码（`OPERATION_NOT_IN_SCAN_TARGET`，含测试） | ✅ 一致（判据名见 §16.1） |

> 🔴 **本节不含裁定**：上表 ⚠️ / 🔴 各行**都未在本单修改**（本单只动 §5.3 ④ 的两处，即 16.1 的 `CODE_POSITION_MISMATCH` 行与 16.4 的第 1 行）。
