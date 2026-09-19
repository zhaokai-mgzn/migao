# 工艺配置「智能化」实施设计（服务 #4652，母单 #4650）

> **实现状态：本文件只是设计。本会话不动 ai-agent，实现待排期（#4652）。**
> 本文件**不含**任何 agent 代码改动的实施步骤为「本次已做」—— §3/§4 全部是**待排期的设计**，
> §6.2 的用例清单也**尚未落地**（本 PR 不改 `.github/cases/**`）。

> 用户裁定（2026-09-20，逐字）：
> > 「**我要求移除条件工序规则**，这个概念我都难以理解，用户如何去理解？我们要做到**智能化的产品**，而不是旧时代配置化的产品」
> > 「你可以考虑下能否**借助 AI 来提升用户体验**」

**本文件是设计文档（docs-only），不含生产代码改动。** 所有「现状」结论均以
`git show origin/main:<path>` / `git grep … origin/main` 取得（**不读本地工作区**，避免读到旧快照）；
每条都附可复现命令，附录 A 是汇总。

相关：**#4652（agent 侧实现单，本文件的直接服务对象）** · #4650（initiative / 母单，覆盖 4 个阶段）·
#4620（命名统一评估，其 §7 是本文件的直接上游）· #4423（母单）· #4577（加工项触发）·
#4616（规则创建入口）· #4587 / #4588（规则软删）· #4609（静默丢工序）· #4621 / #4622（显示名口径）·
#4261（待客户确认项）· #4235（迁移不可变）· #4262（评测成本裁定）。

---

## 0. 大白话：今天商家要填什么 vs 改完商家要做什么

### 今天（配置化）

商家打开「加工管理 → 工艺配置 → 工艺路线」页，看到**两张表**：

1. **工艺路线**（具名路线：主线序列 + 适用帘种 + 默认标记）；
2. **条件工序规则**（26 条常驻展开，`data-testid="route-rules"`）。

第二张表要求商家理解并手工填写**五个字段**（`trigger_kind` / `trigger_value` / `action` /
`operation` / `after_operation` / `position`），其中：

- `trigger_kind` 是 `craft` / `option` / `processing_item` 的英文闭词表；
- `after_operation` 是「**插入锚点**」—— 商家得知道「上车布要插在韩褶之后」；
- `priority` 决定生效顺序，且**顺序敏感**（`remove` 不先于 `insert`，锚点可用性由 priority 决定）。

**一句话**：商家要先学会研发的数据模型，才能让「四爪钩不做复烫」这件事生效。

### 改完（智能化）

| | 今天 | 改完 |
|---|---|---|
| 商家看到几张表 | **2 张**（路线 + 条件工序规则） | **1 张**（工艺路线）；条件挂在**工序自己身上** |
| 默认状态 | 29 条内置条件**已存在**，但商家不知道它们是"出厂知识"还是"别人配的" | **出厂知识**：默认正确、商家**零配置** |
| 想改「四爪钩不做复烫」 | 打开规则表 → 新建 → 选 `craft` → 填 `四爪钩` → 选 `remove` → 填 `复烫` → 存 | **说一句**「我们家的四爪钩不做复烫」→ AI 解析 → **确认卡**（人话解释 + 将发生的变化 + 影响面）→ 点确认 |
| 想知道"为什么这单有上车布" | 自己去规则表里翻，把 priority 排序在脑子里跑一遍 | 加工单/订单的工序清单**可展开「为什么」**：「因为选了韩褶 ⇒ 加了上车布（插在韩褶之后）」 |
| AI 不可用时 | —— | **工序抽屉里仍可手动增删条件**（AI 不是唯一路径） |

---

## 1. 目标形态（四句话）

① **界面不再有**独立「条件工序规则」表 —— 条件**呈现 + 编辑**都挂到**工序**上（抽屉里一句「适用条件」）。
② **29 条内置条件成为出厂知识**，默认正确、商家**零配置**。
③ 想改**说一句**（「我们家的四爪钩不做复烫」）→ AI 解析 → **确认卡** → 落到**工序**。
④ 订单/加工单**看得懂为什么**（"因为选了韩褶 ⇒ 加了上车布（插在韩褶之后）"）。

**「出厂知识」的准确含义（不许过度解读）**：指 29 条内置条件**默认存在且默认正确**，
商家**不需要配置任何东西**就能得到今天的行为（行为零变化）。它**不是**「AI 自动生成新条件」，
也不是「AI 自动改配置」—— 见 §7。

**「移除」的两种读法（沿用 #4620 §7.1 的拆法，本文件不重开）**：
- **A. 移除「产品概念」** = 那张表从商家视野消失、条件收归工序 —— **本单目标，可行**；
- **B. 移除「能力」** = 彻底不要「按工艺/选项增删工序」这件事 —— **不可行**（工艺差异确实改变工序清单，
  没有别的载体）。本单做的是 A，**不是** B。

---

## 2. 现状真值源（逐个实测，给命令与读数）

### 2.1 `production_route_rules` 表（Java 侧）

**建表**（`backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:242` 的 `production_route_rules`）：

```sql
trigger_kind VARCHAR(24) NOT NULL CHECK (trigger_kind IN ('craft','option','shaped','processing_item')),
trigger_value VARCHAR(64) NOT NULL,   -- 逐字 = ERP 写法；它是 join key
position      VARCHAR(16),            -- 部位限定；NULL = 不限
action        VARCHAR(16) NOT NULL CHECK (action IN ('insert','remove')),
operation     VARCHAR(64) NOT NULL,   -- 逻辑工序名（增/删的那一道）
after_operation VARCHAR(64),          -- insert 锚点（逻辑工序名）；NULL = 追加末尾
priority      INTEGER NOT NULL DEFAULT 100,  -- 升序生效（同序按 id）
```

**与 issue 原文的两处不符（照实登记，见 §8）**：

| issue 原文假设 | 实测 | 处置 |
|---|---|---|
| `action ∈ {insert, remove, factor}` | CHECK 只有 **`insert` / `remove`** 两值（`backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:242` 的建表语句里 `production_route_rules` 那一行；`factor` 不在 CHECK 里）。`factor` 档存在过（V59/V72 种子），但 **V87 已把活跃行软删**（`backend/admin-api/src/main/resources/db/migration/V87__retire_factor_route_rules.sql`），Java 实例化的分支注释明确「`action='factor'` 不参与序列构造」 | 本文件按**两值**写 |
| `trigger_kind ∈ {craft, option, processing_item, shaped}` 四种都有种子 | **只有三种有种子**。`shaped` 是**表结构预留**：零种子行、零消费路径，且**两侧都显式抛错**（`backend/ai-agent-service/app/production/routing.py:780` 的 `_rule_triggers` 里 `raise ValueError`；`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1224` 的 `_rule_triggers` 同款显式失败）。写面也拒收（`craft`/`option`/`processing_item` 三值闭词表） | 本文件按**三种**写；`shaped` 单列为"预留未接线" |

**实测活跃规则行数（种子三源）**：

```bash
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | grep -cE "^\s*\('rr-v70-"   # 26
git show origin/main:backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql | grep -cE "^\s*\('0[0-9]', 'processing_item'"  # 3
# ⇒ 26 + 3 = 29
```

⇒ **「29 条内置条件」= V71 的 26 条 + V84 的 3 条**。issue 的数字与实测**一致**。

**写面**（`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java`）：
`GET /route-rules`（:574）· `GET /route-rule-options`（:588）· `POST /route-rules`（:622）·
`DELETE /route-rules/{id}`（:637）· `PUT /route-rules/{id}/customer-unit-price`（:392）。

**写面已有的护栏（阶段 2 直接复用，不新造）** —— 全部在
`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java:399`：

- `trigger_kind` 闭词表（三值），`shaped` 收到即 422；
- `trigger_value` **必须存在于对应词表**（craft ⇒ 活跃工艺词表；processing_item ⇒ 加工项目录；
  option ⇒ 可新建）⇒ 不存在/已停用 ⇒ **422 逐条理由**；
- `operation` / `after_operation` 用逻辑工序名且**必须在该租户工序库里存在**（否则规则永远插不进来 = 黑洞）；
- `remove` **不接受锚点**（`:470` 的 `after_operation` 校验）；
- 同一条「kind + 触发值 + 动作 + 目标工序」已存在 ⇒ **409**（对齐 DB 唯一索引
  `uk_production_route_rules_tenant_trigger_operation`，`backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:258` 的 `uk_production_route_rules_tenant_trigger_operation`）。

### 2.2 第三条路：`processing_item` 的种子在 V84，**不在** `routing.py::ROUTE_RULES`

**实测**（这是 #4620 §7.6 / F14 已登记的事实，本文件复现确认）：

```bash
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -n "processing_item" | wc -l   # 5（全是注释/分支，非种子行）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '708p'                       # ROUTE_RULES: List[Dict[str, Any]] = [
```

`ROUTE_RULES` 的字面量只有 **26 行**（craft 10 + option 16）。`processing_item` 的 **3 行**
在 `V84__seed_processing_item_route_rules.sql`（`:54` 的 `INSERT INTO production_route_rules`）：

| trigger_value | action | operation | after_operation | priority |
|---|---|---|---|---|
| `花边` | insert | `花边` | `三边` | 270 |
| `扣环` | insert | `扣环` | `三边` | 280 |
| `接高` | insert | `接高` | `精裁` | 290 |

⇒ **任何「把条件收归工序」的方案必须同时覆盖第三条路**，否则会漏掉加工项触发的 3 条。

### 2.3 `routing.py::ROUTE_RULES`（26 条 = 21 insert + 5 remove）与 `_LOGICAL_NAME_PAIRS`

**实测（AST 解析，不靠正则）**：

```bash
# ROUTE_RULES 在 backend/ai-agent-service/app/production/routing.py:708；AST 取出字面量后统计
# total = 26 ; by action = {insert: 21, remove: 5} ; by trigger_kind = {option: 16, craft: 10}
# insert 目标工序 distinct = 16 ; remove 目标工序 = {定型, 复烫} ; insert ∩ remove = ∅
```

- **21 条 insert 落在 16 道逻辑工序上**（`上车布` 2 条、`帘头制作` 2 条、`接高` 2 条、`绑带` 3 条，其余各 1 条）；
- **5 条 remove 全部是工艺触发**，只涉及 **2 道**工序（`定型` / `复烫`）；
- `_LOGICAL_NAME_PAIRS`（`backend/ai-agent-service/app/production/routing.py:494` 的 `ROUTE_RULES` / `_LOGICAL_NAME_PAIRS`）= **35 条有序对**
  （35 旧名 → 30 逻辑名）。

**⚠️ 关键事实（issue 未提，但决定阶段 4 的难度）**：`ROUTE_RULES` 是**测试真值源镜像**，
**不是运行时消费者**。`build_route_v2`（`backend/ai-agent-service/app/production/routing.py:783`）
的 `build_route_v2` 注释自陈「今天是**零消费者**：Java 实例化仍读旧 `production_routings`（P2 才切）」；
实测全仓无生产调用方：

```bash
git grep -rn "build_route_v2" origin/main -- backend/ai-agent-service | grep -v "^.*routing.py:" | grep -v tests
# ⇒ 只有 tests/（test_production/test_fabric_route.py 等）
```

⇒ **规则语义在仓库里有三份实现**（见 §5.4），且**彼此语义不完全一致**。这是阶段 4 的头号风险，
不是「加一列锚点」就能解决的。

### 2.4 锚点差异实测（技术必需项）

**命令**（把 `origin/main` 的 `routing.py` 取出后直接跑真值源函数）：

```bash
git show origin/main:backend/ai-agent-service/app/production/routing.py > /tmp/routing_4650_mod.py
backend/ai-agent-service/.venv/bin/python - <<'PYEOF'
import importlib.util
spec = importlib.util.spec_from_file_location("r", "/tmp/routing_4650_mod.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for label, pos in [("韩褶·布帘", {"curtain_type":"布帘","craft":"韩褶","special_options":[]}),
                   ("四爪钩·布帘", {"curtain_type":"布帘","craft":"四爪钩","special_options":[]})]:
    r = m.build_route_v2(pos)
    print(label, len(r), "→", " → ".join(r))
    print("   上车布 index =", r.index("上车布"), "前一道 =", r[r.index("上车布")-1])
PYEOF
```

**实测输出**：

```
韩褶·布帘   12 道 → 精裁 → 三边 → 韩褶 → 上车布 → 熨烫 → 定型 → 复烫 → 车被 → 外帘打卷 → 打包 → 外帘装袋 → 外帘发货
   上车布 index = 3  前一道 = 韩褶
四爪钩·布帘  9 道 → 精裁 → 三边 → 上车布 → 熨烫 → 车被 → 外帘打卷 → 打包 → 外帘装袋 → 外帘发货
   上车布 index = 2  前一道 = 三边
```

⇒ **同一道工序 `上车布` 在两条规则下锚点不同**（`韩褶` 条件下插在 `韩褶` 之后；
`四爪钩` 条件下插在 `三边` 之后）。

**同批实测的其它部位（作为阶段 1 回归锁的基线）**：

| 输入 | 道数 | 序列 |
|---|---|---|
| `韩褶·布帘` | 12 | 精裁→三边→**韩褶→上车布**→熨烫→定型→复烫→车被→外帘打卷→打包→外帘装袋→外帘发货 |
| `四爪钩·布帘` | 9 | 精裁→三边→**上车布**→熨烫→车被→外帘打卷→打包→外帘装袋→外帘发货（无 定型/复烫） |
| `穿杆·布帘` | 8 | 精裁→三边→熨烫→车被→外帘打卷→打包→外帘装袋→外帘发货（无 定型/复烫） |
| `平幔·布帘` | 9 | 精裁→三边→熨烫→**定型**→车被→外帘打卷→打包→外帘装袋→外帘发货（无 复烫，有 帘头制作） |
| `打孔·布帘` | 11 | 精裁→三边→**打孔**→熨烫→定型→复烫→车被→外帘打卷→打包→外帘装袋→外帘发货 |
| `韩褶·纱帘` | 7 | 精裁→三边→韩褶→外帘打卷→打包→外帘装袋→外帘发货（**无 上车布** —— 该规则 `position='布帘'`） |

### 2.5 术语口径：本文件凡说「锚点 / 顺序」的地方，**一律按槽位口径表述**

> 父 agent 同步信息（2026-09-20）：AI 的**解析与解释**要建立在「**槽位 / 派生**」语义上，
> 而不是旧的「锚点」字段 —— 解释文案应是「因为选了韩褶 ⇒ **打褶槽**由韩褶占据 ⇒
> 上车布排在它之后」，**不是**「锚点在韩褶之后」。槽位模型由另一份设计
> `docs/design/operation-slot-model.md` 定义（**本文件写就时该文件尚未在 `origin/main` 上** ——
> `git show origin/main:docs/design/operation-slot-model.md` ⇒ path does not exist ⇒ 本文按父 agent
> 给出的口径表述，**不替它定义模型**）。

**本文的三层表述分工（不许混用）**：

| 层 | 口径 | 例子 |
|---|---|---|
| **商家可见（人话）** | **槽位** | 「打褶槽由韩褶占据 ⇒ 上车布排在它之后」 |
| **AI 意图 / 解释对象（结构化）** | **槽位**（`slot` + 关系），**不是裸锚点** | `{"slot": "打褶槽", "slot_holder": "韩褶", "relation": "after_slot"}` |
| **今天的实现细节（列名）** | 仍是 `after_operation` | `production_route_rules.after_operation = '韩褶'` |

**为什么保留第三层**：本文是**现状实测 + 迁移设计**，必须能指到**今天真实存在的列**
（`backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:242`
的 `production_route_rules` 建表段里的 `after_operation`）。⇒ 凡引用**列名/代码**处写
`after_operation`；凡写**解释文案 / 意图对象 / 呈现**处写**槽位**。**阶段 4 的承载收敛
正是把第三层也换成槽位口径**（见 §5.1 的 `slot` / `slot_holder` 列）。

**实测依据（槽位口径不是新发明的概念）**：真值源里**本来就有槽位** ——
`backend/ai-agent-service/app/production/routing.py:470` 的 `ROUTE_MAINLINE` 第 3 位是字面量
`⟪工艺槽位⟫`，注释写「槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入」。
而 `ROUTE_MAINLINE_STEPS`（实际落库的 10 道）**不含槽位** ⇒ 今天的规则表是**用
`after_operation` 近似表达"槽位被谁占据 + 插在它之后"**。槽位模型是把这层**显式化**。

---

## 3. 阶段 2 设计：**AI 对话式改条件**（核心）**（实现待排期，见 #4652）**

### 3.0 阶段 2 的前提：阶段 1 必须先落地

阶段 2 的**落点**是「工序自己身上的条件」，阶段 1 必须先让这个落点存在（呈现 + 编辑挂到工序）。
阶段 2 本身**零迁移**（只加 AI 入口 + 只读工具），但它依赖阶段 1 的呈现层。

### 3.1 意图模型：把「四爪钩不做复烫」解析成什么

**目标结构化对象**（`RouteRuleIntent`）—— **刻意与 `POST /route-rules` 的 body 同形**，
这样「确认卡 → 落库」是一步直译，不需要中间再翻译一层（少一层 = 少一个漂移点）：

```jsonc
{
  "trigger_kind":  "craft",        // craft | option | processing_item
  "trigger_value": "四爪钩",        // 必须是该租户对应词表里的值（逐字）
  "action":        "remove",       // insert | remove
  "operation":     "复烫",          // 逻辑工序名
  "after_operation": null,          // insert 必填（锚点）；remove 必须为 null
  "position":      null,            // 部位限定；null = 不限
  "priority":      null,            // 缺省由后端分配（见 §3.3）
  "slot":          "打褶槽",         // ★ 槽位口径（§2.5）：这道工序被哪个槽位决定；null = 不在槽位上
  "slot_holder":   "韩褶"            // ★ 该槽位今天由谁占据（槽位模型的派生结果）
}
```

**⚠️ `slot` / `slot_holder` 与 `after_operation` 的关系（不许混用，见 §2.5）**：
- **`slot` / `slot_holder` = 给商家看的、AI 解释用的口径**（「打褶槽由韩褶占据」）；
- **`after_operation` = 今天真实存在的落库列**（`POST /route-rules` 收的就是它）；
- 二者**必须同时存在**：前者用于**呈现与解释**，后者用于**落库**。
  **只给 `slot` 不给 `after_operation` ⇒ 落库时还得反推一次（多一层漂移点）；
  只给 `after_operation` 不给 `slot` ⇒ 解释文案会退化成"锚点在韩褶之后"**（正是父 agent 要避免的形态）。
- 阶段 4 承载收敛后（§5.1），`after_operation` 由 `slot` + `slot_holder` 派生 ⇒ 那时
  **AI 侧可以只产出槽位口径**。

**AI 侧的产出是「候选 + 依据」，不是「已定稿」**：

```jsonc
{
  "intent": { /* 上面的对象 */ },
  "confidence": "high",                      // high | medium | low
  "evidence": [                              // 每一条都必须能在只读工具返回里找到出处
    {"field": "operation", "source": "operation_catalog", "value": "复烫"},
    {"field": "trigger_value", "source": "craft_vocabulary", "value": "四爪钩"}
  ],
  "alternatives": [ /* 歧义时的其它候选（0~n 条） */ ],
  "unresolved": []                           // 无法判定的字段名列表（非空 ⇒ 不许出确认卡，改出追问）
}
```

### 3.2 歧义处理（三条硬规则）

| 歧义形态 | 例子 | 处置 |
|---|---|---|
| **「不做复烫」指哪道工序？** | 词表里同时有 `复烫` 与（假设的）`复烫-纱`；或用户说的是模糊说法「那个烫的」 | 用 `operation_catalog` 做**精确/前缀匹配**：唯一命中 ⇒ 填入 `intent`；多命中 ⇒ `alternatives` 给候选、**不出确认卡**、改出 `interact(choice)` 让用户点；零命中 ⇒ `unresolved=["operation"]`，回落到**工序抽屉的手动编辑**（§3.6） |
| **「我们家」指哪个租户？** | 多租户系统里"我们家"是口语 | **不由 AI 解析租户**。租户恒取 `ToolContext.tenant_id`（`backend/ai-agent-service/app/tools/base.py:242` 的 `tenant_id` 字段）；下发时由 `backend/ai-agent-service/app/utils/http_client.py:95` 的 `_get_headers` 拼 `X-Tenant-Id` 头。**AI 输出的对象里没有租户字段** —— 没有字段就无从越权 |
| **「四爪钩」不在工艺词表里** | 商家说了个错别字 / 停用的工艺 | `trigger_value` 校验失败 ⇒ **不出确认卡**，直接回答「工艺库里没有『四爪钩』，当前活跃工艺是 …」，并给 `route-rule-options` 的真实读数 |

**通用规则**：**`unresolved` 非空 ⇒ 一律不出确认卡**（宁可不做，不可做错）。

### 3.3 工具 / 端点

#### 3.3.1 只读查询工具（AI 侧新增，**零写面**）

**设计原则：工具的每个字段都必须有既有的 admin-api 端点做来源。** 不新造读端点，
更不新造写端点。实测现状：ai-agent 侧**今天完全没有** route-rules / operation-positions 相关的
工具（`git grep -ln "route-rules\|operation-positions" origin/main -- backend/ai-agent-service` ⇒ 只命中
`backend/ai-agent-service/app/production/routing.py` 的注释）。

| 新工具 | 聚合的既有端点 | 回答什么 |
|---|---|---|
| `craft_route_rule_query` | `GET /api/admin/production/route-rules` · `GET /api/admin/production/route-rule-options` | 「现在有哪些条件」+「工艺/加工项词表里有什么」 |
| `craft_operation_query` | `GET /api/admin/production/operations-catalog` · `GET /api/admin/production/operation-positions` | 「工序库有哪些逻辑工序」+「哪道工序在哪个部位适用」 |
| `craft_processing_item_query` | 复用**既有** `processing_item_query`（`backend/ai-agent-service/app/tools/processing_item_query.py`） | 加工项目录（`processing_item` 触发的取值域）—— **不新增**，直接复用 |

**为什么是两个新工具而不是五个**：五个细粒度工具（查工序清单 / 查工艺词表 / 查特殊选项 /
查加工项目录 / 查现有条件）会让模型在每轮多选 2~3 次；而它们**都只读、都无副作用、都被同一批
prompt 消费**。两个工具 + 一个复用 = 3 个工具面，够用且可测（`mibao_coverage.py` 要求每个工具
至少 1 条正向用例，工具越少越好养）。

**权限口径**：三个只读工具都挂 `allowed_roles` 排除 C 端（顾客不该看商家工艺配置），
与 `piecework_query` 同款（见 `backend/ai-agent-service/app/graph/skills/data_skill.py` 里 `piecework_query` 的绑定注释）。

**接线的位置**：`craft_route_rule_query` / `craft_operation_query` 绑定到**订单/生产域**的 skill
工具集（`backend/ai-agent-service/app/graph/skills/order_skill.py` 的 `ORDER_TOOLS`，
那里已有 `processing_order_query` / `processing_item_query`）—— 因为"改工艺条件"是商家在生产域
提出的诉求。**不新增 skill**（YAGNI）。

#### 3.3.2 落库：走**现有**写面（**不新造第二套写面**）

| 动作 | 端点 | 说明 |
|---|---|---|
| 加一条条件 | `POST /api/admin/production/route-rules` | 复用；body = §3.1 的 `intent` |
| 删一条条件 | `DELETE /api/admin/production/route-rules/{id}` | 复用；`id` 来自 `craft_route_rule_query` |
| 改对客单价 | `PUT /api/admin/production/route-rules/{id}/customer-unit-price` | 复用（**不在本阶段**，见 §7） |

**AI 侧不新增写工具**：写动作由**确认卡点击**触发，走既有的 `validate_input` → 写工具链路，
或由前端在确认卡回调里直调既有端点。**二选一必须在实现前裁定**（见 §8 的「待裁定」表）——
本文件给出推荐：**走既有 `validate_input` + 写工具链路**，理由是「同一套确认卡/权限/审计口径」，
新增一条前端直调路径会造出**第二套写面**（正是 issue 验收判据里明令禁止的）。

### 3.4 确认卡契约

复用既有 `interact` 工具的 `confirm` 组件（`backend/ai-agent-service/app/tools/interact.py`
的 `component: confirm` + `fields[{label,value}]`）。**不新增卡片类型**。

**卡片必须显示三块**（缺任一块 ⇒ 不许出卡）：

| 块 | 内容 | 例子 |
|---|---|---|
| **① 人话解释** | 一句话，主语是工序不是字段 | 「**四爪钩 时不做 复烫**」 |
| **② 将发生的变化** | 差异式，不是终态式 | 「工序清单会**少一道** `复烫`（当前 9 道 → 8 道）」 |
| **③ 影响面** | **必须给数字**，数字来自 `craft_operation_query` / `craft_route_rule_query` 的实测读数 | 「会影响 **N 个部位**的工序清单与计件工资」 |

`fields` 建议形态（`label` / `value` 都是字符串，符合既有 schema）：

```jsonc
{"component":"confirm","title":"确认修改工艺条件",
 "fields":[
   {"label":"条件","value":"工艺 = 四爪钩"},
   {"label":"结果","value":"不做「复烫」这道工序（复烫不在槽位上，是主线自带 ⇒ 直接移除）"},
   {"label":"影响面","value":"四爪钩 目前命中 2 个部位（布帘/纱帘）；改后这些部位的工序清单各少 1 道，计件工资相应减少"},
   {"label":"来源","value":"出厂知识（内置 29 条条件）"}
 ],
 "confirmValue":"确认修改工艺条件：四爪钩不做复烫",
 "cancelValue":"取消"}
```

**🔴 影响面数字必须是实测值，不许 AI 现算**：AI 只做**措辞**，「N 个部位」由
`craft_route_rule_query` / `craft_operation_query` 的返回直接填。理由与阶段 3 同源（§4.1）：
**AI 算出来的数字是不可验证的**。

**必须可撤销**：撤销 = 对**同一份差异**的反向操作，不引入新概念：

| 确认的动作 | 撤销动作 |
|---|---|
| `POST /route-rules`（新建） | `DELETE /route-rules/{新建返回的 id}` |
| `DELETE /route-rules/{id}`（删除） | `POST /route-rules`（body = 删除前 `craft_route_rule_query` 读到的**原行逐字**） |

⇒ **确认卡落库前必须先记录「撤销所需的最小信息」**（新建 ⇒ 记录将返回的 id 占位；
删除 ⇒ 记录整行原文）。这张「撤销记录」**建议落在会话侧**（session metadata），
**不落库、不建新表** —— 它是**会话内的短期凭据**，不是业务数据。

**撤销入口**：确认卡执行后，AI 回一条**带「撤销」按钮**的消息（`interact(confirm)`，
`confirmValue="撤销刚才的修改：…"`）。**不做自动过期清理表**（YAGNI）；会话结束即失效，
并如实告知用户「撤销只在本次会话内有效」。

### 3.5 安全（四条硬约束）

| # | 约束 | 判据形态（可测，见 §6.3） |
|---|---|---|
| 1 | **AI 只建议、绝不静默改** | AI 的工具集里**没有任何写工具**（`craft_route_rule_query` / `craft_operation_query` 是只读）。落库**只能**由确认卡点击触发 ⇒ 「模型幻觉出一个改动」在结构上不可能落库 |
| 2 | **越权 / 跨租户一律拒** | 租户来自 `ToolContext.tenant_id`，**不在 AI 输出的对象里**；admin-api 侧既有 404（跨租户）/ 422（词表外）已覆盖（`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java:297` 的 `deleteRouteRule` 注释：不存在 / 跨租户 / 已软删 ⇒ 404） |
| 3 | **词表外取值一律拒** | `trigger_value` 必须过 admin-api 的 `triggerValueExists`（`:427`）；`operation` / `after_operation` 必须过 `logicalOperationExists`（`:441`）。**AI 侧不重复实现校验**（两处各写一份必然漂移），AI 侧只做「**提前查一遍、提前说不**」以提升体验 |
| 4 | **不依赖 AI 也能用** | 阶段 1 的工序抽屉里，条件**仍可手动增删**，走同一组既有端点。**AI 是加速器，不是唯一路径** |

**「AI 只建议」的机械判据（这条必须可测）**：在 ai-agent 的工具注册表里，
`craft_route_rule_query` / `craft_operation_query` 的类属性必须声明只读；
且**断言这两个工具的实现里不存在 `admin_api_client.post` / `.put` / `.delete` 调用**
（L0 静态守卫，见 §6.3）。

### 3.6 失败降级（AI 不可用 / 解析不出来）

| 失败形态 | 降级路径 | 用户体验 |
|---|---|---|
| AI 服务不可用（LLM 超时 / 限流） | 引导到**工序抽屉**手动编辑 | 「AI 暂时不可用，你可以在『工艺配置 → 工序 → 适用条件』里直接改」 |
| AI 解析不出（`unresolved` 非空 / 零命中） | 同上，但**给出已确定的部分** | 「我没听懂『那个烫的』指哪道工序 —— 你是指 `复烫` 吗？也可以直接在工序上改」 |
| AI 解析出多个候选 | `interact(choice)` 出候选 | 点一下即定 |
| 确认卡被点取消 | **什么都不做**，回一句「已取消，没有做任何修改」 | —— |
| 落库被 admin-api 拒（422/409） | **把 admin-api 的 `error.details[]` 逐条原样展示**（既有信封），**不许 AI 改写措辞** | 「工序库里没有『复烫』—— …」 |

⇒ **降级的共同要求：降级路径本身必须是一等公民**（阶段 1 的工序抽屉），
不是「AI 挂了就什么都做不了」。这也是阶段 1 必须先落地的一个理由。

---

## 4. 阶段 3 设计：**AI 解释工序清单由来**（实现待排期，见 #4652）

### 4.1 核心口径：后端给结构化理由，AI 只做措辞（**不许编造**）

**响应形状**（在既有工序清单读面上**只加不改**地追加一个键 —— 与 #4621 / #4622 的
「只加不改」裁定同款）：

```jsonc
{
  "seq": 4,
  "operation": "上车布-布",         // 工人端快照名（既有键，一字不动）
  "logical_name": "上车布",          // 既有键（issue #4621）
  "position": "布帘",                // 既有键（issue #4621）
  "reason": {                        // ★ 新增键（唯一新增面）
    "kind": "craft",                 // 与 production_route_rules.trigger_kind 同值域
    "value": "韩褶",                  // 触发值（逐字）
    "result": "added",               // added | removed | mainline
    "slot": "打褶槽",                 // ★ 槽位（§2.5）：这道工序由哪个槽位决定；null = 不在槽位上
    "slot_holder": "韩褶",            // ★ 该槽位今天由谁占据（"打褶槽由韩褶占据"）
    "after_operation": "韩褶"         // 今天真实存在的锚点列值（落库口径，§2.5 第三层）
  }
}
```

**「结构化理由」的四条纪律**：

1. **`kind` / `value` / `slot` / `slot_holder` / `after_operation` 逐字取自真值源**（规则行 / 主线），**不是 AI 生成的**；
2. **`result` 是三值枚举**，不是自由文本：`added`（被规则插入）/ `removed`（被规则移除，
   这类工序**不在**清单里，只在「被滤掉」视图出现）/ `mainline`（主线自带，无条件）；
3. **AI 只把 `reason` 措辞成人话**，且**必须逐字包含 `value` 与 `slot_holder`**（可测断言，§6.3）；
4. **`reason` 缺失（`null`）⇒ AI 必须说「这单是历史数据，没有记录原因」，不许推断**
   （见 §4.3）。

**人话模板（AI 的措辞约束）**：

```
kind=craft   + value=韩褶   + result=added + slot=打褶槽 + slot_holder=韩褶
  → 「因为选了韩褶 ⇒ **打褶槽由韩褶占据** ⇒ 上车布排在它之后」
kind=craft   + value=四爪钩 + result=removed
  → 「因为选了四爪钩 ⇒ 不做定型」（定型不在槽位上 ⇒ 直接移除）
kind=option  + value=拼2次  + result=added + after_operation=三边
  → 「因为勾了『拼2次』⇒ 拼1次/2次/3次 这一族排在 三边 之后」
kind=processing_item + value=花边 + result=added + after_operation=三边
  → 「因为这单带了加工项『花边』⇒ 花边排在 三边 之后」
result=mainline
  → 「这是工艺路线的主线工序，不需要条件」
```

> ⚠️ **表述纪律（父 agent 同步信息 1）**：凡解释**「为什么排在这里」**，一律说
> 「**〈槽位〉由〈触发值〉占据 ⇒ 〈工序〉排在它之后**」；**不许**写成「锚点在韩褶之后」。
> 锚点（`after_operation`）是**落库列名**，不是给商家看的语言。

### 4.2 落在哪：前端落点

| 落点 | 页面 | 展开形态 |
|---|---|---|
| **加工单详情 → 生产明细**（工序进度表） | `frontend/admin-web` 的加工单生产页 | 每行工序可展开「为什么」 |
| **订单详情 → 工序清单** | 订单详情 | 同上（数据同源） |

**前端实现口径**：沿用 #4621 的显示名 helper（`operationDisplayName()`）同一范式 ——
理由文案的**数据**来自后端 `reason` 键，前端**只做渲染**，**不在前端拼中文**。

**「被滤掉的工序」也要能看**（这是解释能力的另一半，且是**价值最高**的一半）：
今天商家问「为什么这单没有复烫」只能靠猜。建议在展开区给一个**「被条件滤掉的工序」**小节，
数据来自同一份 `reason`（`result="removed"`）。**它不进工序清单**（清单不变），只在展开区出现。

### 4.3 与「快照名」红线的关系（历史加工单的解释必须对上**当时的**快照）

> **槽位口径同样受本条约束**：`reason.slot` / `reason.slot_holder` 与 `reason.after_operation`
> 一样是**当时**的证据，必须**落库时冻结**（见下）。

**两条既有的、不得违反的裁定**：

- **#4621**：工序实例的 `operation` / `operation_name` 是**工人端当时的快照名**，
  历史读面**必须保留**，web 界面**不得渲染**（web 只渲染 `logical_name` + `position`）；
- **#4622**：`variant_name` 是**当前**库口径的名字，会随库改名而变 ⇒ 已从读面**删除**。

⇒ **`reason` 键属于哪一类？** 它是「**当时**为什么加这道工序」的证据 ⇒ **属于快照类**，
必须满足：

1. **落库时冻结**，不随规则表后续变更而变（否则商家改了规则，历史加工单的解释会跟着变 = 编造）；
2. 键名与值域**不得**引用"当前库"的名字（`reason.value` 是**当时的**触发值，
   `reason.anchor` 是**当时的**逻辑工序名）。

**历史数据的处置（零回填，如实告知）**：

`processing_position_operations`（`docs/sql/schema.sql:1054` 的 `processing_position_operations` 建表）**今天没有**任何 `reason` 列 ⇒
阶段 3 之前生成的加工单**没有**这个证据。三条可选路径：

| # | 路径 | 代价 | 本文件推荐 |
|---|---|---|---|
| a | **零回填**：`reason` 为 `null` ⇒ 界面显示「历史加工单，没有记录原因」 | 最诚实；老单解释不可用 | ✅ **推荐**（与 #4604「不追溯」同族口径：历史不回溯、不写回填脚本） |
| b | 从 `processing_orders.items_snapshot`（JSONB）**重放**当时的 `craft` / `specialOptions` / `processingItems` + **当时**的规则行推导 | 需要"当时的规则行" —— 而规则行**今天只存当前态**（无版本账，见下），拿今天的规则重放 = **编造** | ❌ 不做（除非先给规则表补版本账） |
| c | 按当前规则反推 | **最危险**：规则已改 ⇒ 解释与当时不符 ⇒ 直接违反「不许编造」 | ❌ **明令禁止** |

**🔴 一个必须登记的缺口（本文件实测发现）**：`production_route_rules` **没有版本账**。
既有版本账覆盖 `production_operation_price_versions`（V55）、`production_routing_versions`（V60/V85，
只记**路线序列**变更）、`production_operation_position_price_versions`（V86）、
`production_route_rules.customer_unit_price`（V77 只记**对客单价**）——
**规则行的增删改（含 `after_operation` / `priority`）本身不留痕**。
⇒ 「当时的规则长什么样」**今天答不出来**。这不是阶段 3 的阻塞项（阶段 3 走路径 a），
但它是**阶段 4 迁移回滚**的硬依赖（见 §5.5）。

---

## 5. 阶段 4 设计：**承载收敛**（条件真正落到工序）**（实现待排期；§5.4 的语义收敛是它的前置）**

### 5.1 工序侧需要哪些列

**结论：条件不是「一列」，是「一组条件行」。** 因此正确形态**不是**给工序表加列，
而是**新建一张「工序的适用条件」表**，把 `production_route_rules` 的语义**换一个主语**：

```sql
CREATE TABLE production_operation_conditions (
    id              VARCHAR(64) PRIMARY KEY,
    tenant_id       BIGINT NOT NULL REFERENCES tenants(id),
    logical_name    VARCHAR(64) NOT NULL,   -- ★ 主语：这道工序（逻辑工序名）
    position        VARCHAR(16),            -- 部位限定；NULL = 不限
    trigger_kind    VARCHAR(24) NOT NULL CHECK (trigger_kind IN ('craft','option','processing_item')),
    trigger_value   VARCHAR(64) NOT NULL,
    action          VARCHAR(16) NOT NULL CHECK (action IN ('insert','remove')),
    after_operation VARCHAR(64),            -- ★★ 必须含「插入锚点」（技术必需项，见 §2.4）
    slot            VARCHAR(32),            -- ★ 槽位名（§2.5 槽位口径）；null = 不在槽位上
    slot_holder     VARCHAR(64),            -- ★ 该槽位由谁占据（派生结果，槽位模型定义）
    priority        INTEGER NOT NULL DEFAULT 100,
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    ...
);
```

**与 `production_route_rules` 的唯一结构差异 = 列的角色互换**：

| | `production_route_rules`（今天） | `production_operation_conditions`（目标） |
|---|---|---|
| 主语 | `operation`（触发命中的**结果**） | `logical_name`（**工序自己**） |
| 条件 | `trigger_kind` + `trigger_value` | 同名同值域（**不换概念**） |
| 锚点 | `after_operation` | `after_operation`（**必须保留**） |

⇒ **「条件挂到工序上」在数据上 = 把 `operation` 列改名为 `logical_name` 并把它挪到主语句法位置。**
唯一键相应变成 `(tenant_id, logical_name, COALESCE(position,''), trigger_kind, trigger_value, action)`。

**🔴 为什么不给 `production_operations` 加列**：一道工序可以有**多条**条件
（`上车布` 有 2 条、`绑带` 有 3 条、`接高` 有 2 条、`帘头制作` 有 2 条 —— 实测见 §2.3）。
加列必然要存 JSON 数组 ⇒ 失去唯一键约束、失去 `priority` 的可排序性、
失去「同一条规则只允许一行」的 DB 级护栏（`uk_production_route_rules_tenant_trigger_operation`）。
**用 JSON 数组换掉一张有唯一键的表 = 用约束换便利，方向反了。**

**🔴 `after_operation` 必须随条件一起搬**（技术必需项，不是可选项）：
实测（§2.4）`上车布` 在 `韩褶` 条件下插在 `韩褶` 之后、在 `四爪钩` 条件下插在 `三边` 之后。
**若把两条条件合并成"上车布的适用条件"而丢掉锚点 ⇒ 两条条件落到同一位置 ⇒ 车间按错顺序干。**

**🔴 并且阶段 4 要把这层锚点「槽位化」**（§2.5）：`after_operation` 是**今天的近似表达**
（「插在谁之后」），而真值源里本来就有槽位（`backend/ai-agent-service/app/production/routing.py:470`
的 `ROUTE_MAINLINE` 第 3 位 `⟪工艺槽位⟫`）⇒ 新表**同时**带 `slot` / `slot_holder`
（**呈现与解释口径**）与 `after_operation`（**落库与兼容口径**），二者由槽位模型定义派生关系。
**槽位模型由 `docs/design/operation-slot-model.md` 定义（本文件写就时该文件尚未在 `origin/main` 上）；
本文不替它定义，只登记"新表必须能承载槽位"这一约束。**

### 5.2 `processing_item` 第三条路怎么收

**做法：`trigger_kind` 保持三值不变，把 V84 的 3 行一起搬进新表。**
新表**本身就是**第三条路的载体（`trigger_kind='processing_item'` 是新表的一个取值），
不需要为它单开一条路径。

**收的判据（实测，可复现）**：

```bash
# V84 的 3 行必须逐值出现在新表里（花边/扣环/接高，action=insert，锚点 三边/三边/精裁）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql | sed -n '60,63p'
#   ('01','processing_item','花边','insert','花边','三边',270)
#   ('02','processing_item','扣环','insert','扣环','三边',280)
#   ('03','processing_item','接高','insert','接高','精裁',290)
```

**必须同时改的三处镜像**（今天它们是同一份真值源的四个投影，漏一处就漂移）：

1. `backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql`（26 行，**不可改**，走新迁移）；
2. `backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql`（3 行，**不可改**，走新迁移）；
3. `backend/ai-agent-service/app/production/routing.py:708` 的 `ROUTE_RULES`（26 行，**测试真值源**）；
4. `docs/sql/schema.sql`（bootstrap 终态镜像，该路径不跑迁移链）。

防漂移守卫已存在：`tests/unit_ci_workflows/test_production_catalog_seed.py`（三源逐值比对）+
`tests/unit_ci_workflows/test_processing_item_route_rules_seed.py`（V84 三源 + 真库可执行）。

### 5.3 默认值裁定：新增工艺时 `定型` / `复烫` **默认做**（黑名单口径）

**裁定：黑名单口径（默认做，被 `remove` 命中才不做）。**

**论证（为什么不是白名单）** —— 这是本阶段唯一必须业务裁定的项（#4620 §7.5 已列为前置）：

| 口径 | 语义 | 新工艺（第 6 个工艺词）拿到什么 | 失效形态 |
|---|---|---|---|
| **黑名单（默认做）** ✅ | 主线里有 ⇒ 默认做；被 `remove` 命中才不做 | **完整工序**（含 `定型`/`复烫`） | 漏配 ⇒ **多**两道 ⇒ **可发现**（加工单上看得见）、可报工、工资**多**给一点 |
| **白名单（默认不做）** ❌ | 没被条件显式命中就不做 | **少两道** | 漏配 ⇒ **静默少两道工序** ⇒ 工人少干、**工资少发**、**且不报错** |

**白名单的失效形态与 #4609 同族**（`ProcessingOrderService.buildRoute` 的注释自陈：
「商家加了工序、路线卡片上也看得见，但加工单里根本没有它，**没有任何报错**（工人少一道活、
少拿一笔计件钱）」）。⇒ **用"静默少两道工序"换掉一张表，方向反了。**

**并且黑名单口径 = 今天 `build_route_v2` 的实际语义**（`ROUTE_MAINLINE_STEPS` 全做 → 按规则 `remove` 过滤），
⇒ **行为零变化**（这是"不变差"方向的直接推论，不是新裁定）。

**白名单口径的补偿方案（若业务坚持要白名单，必须同时做）**：新工艺入库时**自动补 5 条
"默认做"规则行**（对 `四爪钩`/`穿杆`/`平幔` 之外的每个工艺各一条 `insert`）。代价 = 工艺词表增长
与规则行增长**耦合**（新增一个工艺 = 自动 +N 行规则）—— 本文件**不推荐**，因为「规则表行数
随工艺数增长」正是"配置化"的形态，与本次"智能化"的目标相反。

### 5.4 迁移方案

**⚠️ 阶段 4 的最大风险不是迁移，是「规则语义有三份实现」。** 实测：

| # | 实现 | 位置 | 语义 |
|---|---|---|---|
| 1 | `build_route_v2` | `backend/ai-agent-service/app/production/routing.py:783` | `build_route_v2` **零生产消费者**（只被 tests 调）；`insert` 用 `_insert_after`，**不去重** |
| 2 | `buildRoute` | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1175` | `buildRoute` 序列构造；`insert` 用 `insertAfterLogical`（`:1324`），**不去重** |
| 3 | `insertConditionalOperations` | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:796` | `insertConditionalOperations` **运行时实际生效的那条**（`:549` 调用）；**唯一性 = 取代**（`:842` 的 `removeIf` 先移除旧位置再插） |

⇒ **实现 2 与 3 的语义不同**（2 不去重、3 取代）。`buildRoute` 的 docstring 说「本方法是
『怎么展开路线』的**唯一** Java 实现」—— **这句话与实测不符**（`:799` 还有一份，
且它才是运行时生效的那份）。**这是本文件实测发现的、issue 未提的事实（见 §8）。**

⇒ **阶段 4 的第一步不是迁移，是把这三份语义收敛成一份**（否则搬完条件后，
三份实现会各自解释新表，行为分裂）。**这一步本身就是一次独立可合并的改动**，
且它**必须在阶段 4 的迁移之前**。

**迁移步骤（在语义收敛之后）**：

| 步 | 动作 | 可回滚 |
|---|---|---|
| M1 | 新建 `production_operation_conditions` + 唯一键（**纯增量，零消费**，与 V71 的 P1 同范式） | 是（DROP 表） |
| M2 | 把 29 行按 `operation → logical_name` 逐值搬进新表（**双写**：旧表仍写，新表也写） | 是 |
| M3 | 读面切到新表（`GET /route-rules` 改为投影新表，**响应键集一字不变** ⇒ 前端零改动） | 是（切回旧表） |
| M4 | 实例化切到新表（`ProcessingOrderService` 读新表） | 是 |
| M5 | **停写旧表**（`POST/DELETE` 改双写 → 只写新表） | 是 |
| M6 | **退场**（见 §5.6 的退场判据） | —— |

**「两阶段改名避唯一键」的坑（若适用）**：**本方案不适用** —— 因为不 `ALTER TABLE ... RENAME COLUMN`，
而是新建表 + 搬行（新表的唯一键**从一开始就是目标形态**，不需要中途改名）。
**若实现时选择 `ALTER TABLE` 路线，则必须两阶段**：先加新列 + 回填 + 建新唯一索引，
再删旧列 + 删旧唯一索引 —— 直接改名会让既有唯一索引 `uk_production_route_rules_tenant_trigger_operation`
在新列组合下**语义改变**（旧键含 `operation`，改名后含 `logical_name`，
但 `logical_name` 的语义与 `operation` **相同** ⇒ 其实不冲突；**真正会冲突的是把 `operation`
挪进主语后与 `trigger_value` 的组合**）。**本文件推荐新建表路线，规避这个坑。**

### 5.5 回滚方案

| 步 | 回滚 |
|---|---|
| M1 | `DROP TABLE production_operation_conditions`（零消费，无副作用） |
| M2~M4 | 双写期：切回旧表读 + 旧表写（**数据一致**，因为双写） |
| M5 | 恢复双写；新表数据与旧表比对（**必须有比对工具**，见下） |
| M6 之后 | **不可原地回滚** ⇒ 必须保留旧表**至少一个观察期**（见 §5.6） |

**🔴 回滚的硬依赖：`production_route_rules` 今天没有版本账（§4.3 实测）。**
⇒ 「回滚到某时刻的规则集合」**答不出来**。**因此 M1 必须同时补规则表的版本账**
（新表 `production_operation_condition_versions`，与 V55/V86 同范式：**真的变了才追加一行**）——
它同时解决两个问题：① 阶段 3 的历史解释（路径 b 变得可行）；② 阶段 4 的回滚。
**这不是范围蔓延，是回滚可行性的前置条件。**

### 5.6 退场判据（删表 / 删端点 / 删守卫）

**「停止条件」与「退场判据」必须分开**（前者是"立刻停"，后者是"可以删"）。

**退场判据（全部满足才允许删）**：

| 对象 | 判据 |
|---|---|
| 删 `production_route_rules` 表 | ① M5 之后**连续 ≥ 1 个完整计费周期**（建议 30 天）旧表零写入（`SELECT count(*) FROM production_route_rules WHERE updated_at > <M5 时刻>` = 0）；② 新表行数 = 旧表活跃行数（29 + 商家自建）；③ 历史加工单的解释路径已切到**快照**（不读旧表）；④ 一个完整观察期内零 `[INCIDENT]` 级告警（`INCIDENT_ROUTING_UNRESOLVED` 一族） |
| 删 `POST /route-rules` 端点 | 前端**零调用**（`grep -rn "route-rules" frontend/admin-web/src` 只剩新表端点）+ 服务端访问日志一个观察期零 200 响应 |
| 删 `DELETE /route-rules/{id}` 端点 | 同上 |
| 删守卫（`test_production_catalog_seed.py` 等） | **不删**。三源收敛守卫要**改判**成"新表 ≡ `routing.py`"，**不是退场**（守卫守的是"真值源不漂移"，与载体是哪张表无关） |

**停止条件（出现任一条 ⇒ 立刻停 + 回滚）**：

| # | 停止条件 | 为什么 |
|---|---|---|
| S1 | 同一订单配置在改前/改后产出**不同的工序序列** | 直接错工资（与 #4609 同族） |
| S2 | 任一租户的工序清单出现**静默少工序**（清单变短且无 `missing_operations` 报告） | 静默失效 = 工人少拿钱 |
| S3 | 新表行数 ≠ 旧表活跃行数（含**商家自建**的行，不只是 29 条种子） | 迁移丢数据 |
| S4 | 历史加工单的解释发生变化（同一个老单两次查询给出不同 `reason`） | 违反"不许编造" |
| S5 | 语义收敛后 `buildRoute` / `insertConditionalOperations` 对**同一输入**给出不同序列 | §5.4 的收敛没做完 |
| S6 | 任一写入路径出现跨租户可见（A 租户看到 B 租户的条件） | 越权 |

---

## 6. 与 AI 相关的评测与纪律（**本 PR 未落地任何用例**；清单见 §6.2，实现待排期 #4652）

### 6.1 默认不跑真实 LLM 评测（#4262 裁定，**本条优先于 §14**）

> 用户裁定（2026-09-18，逐字）：「**不要自动进行验证，都是重复的验证，白白消耗成本**」
> 「**手动集中跑一次即可**」。

⇒ **本单及后续实现单，一律默认不跑真实 LLM 评测、不派发任何评测 workflow。**
按 `migao-dev-flow` §13 的零成本动作：**算出该跑哪几条用例、把清单写进 PR body**；
**只有用户显式要求时**才**一次集中跑**（禁止逐条/逐轮派发）。

**派发命令（仅用户显式要求时）**：

```bash
cd /Users/guangzhen.zk/ai native/migao
backend/ai-agent-service/.venv/bin/python tests/agent_eval/local_runner.py smoke --cases .github/cases
```

### 6.2 需要新增 / 改判的评测用例（**先列清单，别跑**）

按 §14.1 / §14.2 的触发条件逐条映射（阶段 2/3 落地时执行；**本单是设计文档，不改用例**）：

| # | 触发条件（§14.1/§14.2） | 用例动作 | 建议 ID | 域文件 | 断言形态 |
|---|---|---|---|---|---|
| 1 | 新工具落地（`craft_route_rule_query`） | **新增**正向用例 | 新 `PP-0xx` | `.github/cases/processing.yml` | `tool: craft_route_rule_query` + `required_args` |
| 2 | 新工具落地（`craft_operation_query`） | **新增**正向用例 | 新 `PP-0xx` | `.github/cases/processing.yml` | 同上 |
| 3 | 新行为：对话式改条件（正向） | **新增**：说一句 → 出确认卡 → 落库 | 新 `PP-0xx` | `.github/cases/processing.yml` | `order_before: [craft_route_rule_query, interact, <写工具>]` + `db_verify` |
| 4 | 新行为：**AI 只建议不静默改** | **新增**（关键安全用例） | 新 `PP-0xx` | `.github/cases/processing.yml` | `order_before` 断言 `interact` **早于**写工具；`forbidden_text` 禁止"已为你修改" |
| 5 | 新行为：**越权/跨租户拒绝** | **新增** | 新 `PP-0xx` | `.github/cases/defense.yml` | `forbidden_text` + 断言无写工具调用 |
| 6 | 新行为：**词表外取值拒绝** | **新增** | 新 `PP-0xx` | `.github/cases/processing.yml` | `forbidden_text`（不得出现确认卡）+ 断言 `interact` 未被调用 |
| 7 | 新行为：**降级路径**（AI 不可用/解析不出） | **新增** | 新 `PP-0xx` | `.github/cases/processing.yml` | `forbidden_text`（不得编造）+ 断言引导到手动编辑 |
| 8 | 新行为：**解释不编造**（阶段 3） | **新增** | 新 `PP-0xx` | `.github/cases/processing.yml` | 断言输出**逐字包含** `reason.value` 与 `reason.anchor` |
| 9 | 交互卡渲染/前端（§13.2 已有映射行） | **前端抽验剧本** | —— | `docs/testing/frontend-acceptance-checklist.md` | UI 旅程（§15） |
| 10 | 行为契约变更（规则表 → 条件表） | **改判**存量 `PP-010` / `PP-013` 的锚点断言 | 改判 | `.github/cases/processing.yml` | 锚点位置断言（前后相邻工序）需按新载体改判 |

**同时必须补的两条「覆盖厚度」用例**（§14.5，`mibao_coverage.py --check` 会拦）：
两个新工具各自**至少 1 条正向用例**（只有拒绝式断言 = ❌ 阻塞）。

**生成物纪律（§14.2）**：改了 `.github/cases/*.yml` ⇒ 必须跑 `render_cases.py` 并提交生成物
（否则 CI「生成物新鲜度校验」红）。

### 6.3 AI 输出的可测断言形态（每条带**红证**思路）

> 铁律（`migao-acceptance`）：**不会红的断言 = 空断言**。下面每条都给出"改前实测会红成什么样"。

| # | 断言 | 形态 | **红证思路** |
|---|---|---|---|
| A1 | **意图解析正确性**：输入「我们家的四爪钩不做复烫」⇒ `intent = {trigger_kind:"craft", trigger_value:"四爪钩", action:"remove", operation:"复烫", after_operation:null}` | 结构化 `output_verify`（逐字段比对） | 改前：把 `remove` 的 `after_operation` 填成 `"复烫"`（模型常见错）⇒ 字段比对红；或把 `operation` 填成 `四爪钩` ⇒ 红 |
| A2 | **槽位不丢**：输入「韩褶的时候加一道上车布」⇒ `slot == "打褶槽"` ∧ `slot_holder == "韩褶"` ∧ `after_operation == "韩褶"` | 结构化 `output_verify` | 改前：模型给 `after_operation: null`（"追加末尾"）⇒ 红。**这条是 §2.4 的锚点差异在 AI 侧的直接投影，也是 §2.5 槽位口径的落点** |
| A3 | **歧义不出卡**：输入「那个烫的别做了」⇒ `interact` **未被调用** + 输出含追问 | `order_before` + `forbidden_text` | 改前：模型猜一个工序直接出确认卡 ⇒ `interact` 被调用 ⇒ 红 |
| A4 | **越权拒绝**：C 端会话（`role=customer`）请求改工艺条件 ⇒ 无写工具调用 + 拒绝话术 | `forbidden_text` + 工具调用断言 | 改前：工具 `allowed_roles` 没排除 customer ⇒ 工具被调用 ⇒ 红 |
| A5 | **跨租户拒绝**：租户 A 的会话请求删租户 B 的规则 id ⇒ admin-api 404 + AI 如实转述 | `db_verify`（B 的规则仍在）+ `forbidden_text` | 改前：若 AI 侧自己按 id 查而不带租户 ⇒ 可能命中 B ⇒ `db_verify` 红 |
| A6 | **只建议不静默改**：输入「四爪钩不做复烫」+ 用户**不点确认** ⇒ 规则表**一行未变** | `db_verify`（规则表快照前后逐行相等） | 改前：若存在任何"AI 直接写"的路径 ⇒ 规则表变了 ⇒ 红 |
| A7 | **降级不编造**：AI 服务不可用时 ⇒ 输出**不含**任何具体工序名结论 + 给出手动编辑入口 | `forbidden_text`（禁止出现未由工具返回的工序名） | 改前：模型硬编一段"已为你设置…" ⇒ 红 |
| A8 | **解释逐字可溯**（阶段 3）：工序 `上车布` 的解释必须**逐字包含** `reason.value="韩褶"` 与 `reason.anchor="韩褶"` | `output_verify`（子串包含） | 改前：模型说"因为选了四爪钩"（与实际 `reason` 不符）⇒ 红 |
| A9 | **只读工具零写面**（L0 静态守卫） | 静态断言 | 改前：往 `craft_route_rule_query` 实现里加一行 `admin_api_client.post(...)` ⇒ 红 |
| A10 | **意图对象无租户字段**（L0 静态守卫） | 静态断言：`RouteRuleIntent` 的 schema 里**不得**有 `tenant_id` / `tenantId` 键 | 改前：加了 `tenant_id` 键 ⇒ 红（这条守的是"没有字段就无从越权"） |

**红证的卫生要求（§19.1 元规则③）**：注入前后**清缓存** + **内容指纹**自证（**禁 mtime/size**）；
macOS 上 `.pyc` 可落 `~/Library/Caches/com.apple.python` ⇒ 仓库内 `rm -rf __pycache__` **可能是空操作**。

### 6.4 LLM 红例的确定性下沉（§13.3 红线）

任何由真实 LLM 评测发现的红例，**必须下沉为 ≥1 条确定性断言**
（`must_succeed` / `db_verify` / `amount_verify` / `output_verify` / L0 不变式），否则**不算闭环**；
登记进 `.github/llm-finding-ledger.json`，机械检查：

```bash
python3 .github/llm_sink_check.py --issue <红例 issue 号>   # 0 = 已下沉 / 1 = 未登记或空壳 / 3 = 无法判定
```

**为什么这条对本单特别要紧**：PR 层真实 LLM 已停跑（#4034 裁定 2′）⇒
**确定性层是唯一的拦截面**。A1~A10 里凡是能落成 L0/`db_verify` 的，**优先落确定性形态**，
`output_verify` 只用于「必须由 LLM 措辞」的那几条（A7 / A8）。

---

## 7. 不做什么（范围边界）

| # | 不做 | 为什么 |
|---|---|---|
| N1 | **不做「AI 自动改配置」** | 用户裁定「AI 只建议、不静默改」（issue 纪律段）。AI 的工具集里**没有任何写工具**（§3.5 约束 1） |
| N1′ | **本会话不做任何 agent 实现** | 用户裁定「**agent 的改动先记成 issue，本会话先不动工**」（2026-09-20）⇒ 实现登记在 **#4652**，本文件只交设计 |
| N2 | **不含 agent 的其它行为改造** | 本单只做「工艺配置」这一件事。prompt 的其它段落、其它工具、引导流程**一律不动** |
| N3 | **不含与本次无关的重构** | 例：`buildRoute` 与 `insertConditionalOperations` 的语义收敛（§5.4）**是阶段 4 的前置**，属阶段 4，**不在阶段 1/2/3 里顺手做** |
| N4 | **不改对客单价链路**（`PUT /route-rules/{id}/customer-unit-price`） | 「两套账不互读」是既有硬边界（`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java:436` 的 `TRIGGER_KINDS` 校验：非 `option` 带价 ⇒ 422）；本单只碰**工序编排**那一套账 |
| N5 | **不新造第二套写面** | issue 验收判据明令：「落库走**现有**规则写面（**不新增第二套写面**）」 |
| N6 | **不新增 skill** | 两个只读工具绑进既有 `order_skill`（`ORDER_TOOLS`）；新建 skill = 多一个入口、多一份 prompt 维护面 |
| N7 | **不给规则表补版本账之外的"配置历史"** | §5.5 的版本账是**回滚前置条件**，不是"配置历史"功能；不做 diff 查看器 / 不做回滚 UI |
| N8 | **不改 `.github/workflows/**` 与 `.agent-presets/**`** | 本单纪律红线（且本机 token 无 `workflow` scope） |
| N9 | **不加 `docs/wiki/INDEX.md` 条目** | #4620 §6 N9 已裁定：该索引 `design/` 条目数 = **0** ⇒ 加行是新造约定 |
| N10 | **不改 `production_route_rules` 的任何一行**（阶段 1/2/3） | 阶段 1 验收判据：「**零迁移**：`production_route_rules` 一行未动」 |

---

## 8. 与 issue #4650 假设**不符**的事实 / 无法判定项

### 8.1 与 issue 假设不符（照实写，不迁就）

| # | issue 原文 | 实测 | 处置 |
|---|---|---|---|
| F1 | `trigger_kind ∈ {craft, option, processing_item, shaped}`（读起来像四种都有种子） | **只有三种有种子**；`shaped` 零种子行、零消费路径，两侧**显式抛错**（`backend/ai-agent-service/app/production/routing.py:780` 的 `_rule_triggers` / `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1224` 的 `_rule_triggers`），写面拒收 | §2.1 单列「预留未接线」 |
| F2 | `action ∈ {insert, remove, factor}` | CHECK **只有两值**（`backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql:242` 的 `production_route_rules` 建表段）；`factor` 活跃行已由 **V87 软删**（`backend/admin-api/src/main/resources/db/migration/V87__retire_factor_route_rules.sql`） | §2.1 按两值写 |
| F3 | 「29 条内置条件」 | ✅ **一致**（V71 26 + V84 3）。但**分布不等于 ROUTE_RULES**：`routing.py::ROUTE_RULES` 只有 **26** 条，V84 的 **3** 条**不在**其中 | §2.2 / §2.3 分开写 |
| F4 | （隐含）`routing.py::ROUTE_RULES` 是运行时真值源 | **它是测试真值源镜像，零生产消费者**（`build_route_v2` 只被 tests 调）。**运行时实际生效的是** `ProcessingOrderService.insertConditionalOperations`（`:799`，由 `:549` 调用） | §2.3 / §5.4；**这是阶段 4 的头号风险** |
| F5 | （隐含）规则语义只有一份实现 | **三份**，且**语义不同**：`build_route_v2`（不去重）/ `buildRoute`（不去重）/ `insertConditionalOperations`（**唯一性 = 取代**，`:842` 的 `removeIf`）。而 `buildRoute` 的 docstring 自称「本方法是『怎么展开路线』的**唯一** Java 实现」—— **与实测不符** | §5.4：阶段 4 第一步 = 语义收敛（独立可合并） |
| F6 | （隐含）规则表有变更留痕 | **没有**。既有版本账覆盖工序价（V55）/ 路线序列（V60/V85）/ 矩阵格价（V86）/ 对客单价（V77），**规则行的增删改本身零留痕** | §4.3 / §5.5：阶段 4 迁移**必须先补版本账**（回滚硬依赖） |
| F7 | 「阶段 4 需迁移（含"两阶段改名避唯一键"之类的坑）」 | **本方案（新建表 + 搬行）不适用**该坑；`ALTER TABLE` 路线才有 | §5.4 明写推荐路线与规避方式 |
| F8 | 「阶段 3 零迁移」 | ⚠️ **严格说不是零**：要让 `reason` **落库并冻结**（否则历史解释会随规则变），需要给 `processing_position_operations`（`docs/sql/schema.sql:1054` 的 `processing_position_operations`）**加列** ⇒ 是一次迁移。**若接受"历史单解释不可用"（路径 a），则确实零迁移** | §4.3 给出两条路径与推荐 |
| F9 | （隐含）「AI 侧已有工艺相关工具可复用」 | **没有**。ai-agent 侧今天**零** route-rules / operation-positions 工具（`git grep -ln "route-rules\|operation-positions" origin/main -- backend/ai-agent-service` ⇒ 只命中 `routing.py` 的注释） | §3.3.1 全部新建 |
| F10 | （隐含）「默认做」是新增裁定 | **它 = 今天的实际语义**（`ROUTE_MAINLINE_STEPS` 全做 → 按规则 `remove` 过滤）⇒ 选黑名单是**行为零变化**，不是新行为 | §5.3 论证 |
| F11 | issue 验收判据「条件仍可编辑（增/删），落库走现有规则写面」 | ✅ 可行，但**「增」有一个既有护栏要注意**：`remove` 不接受锚点（`backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java:471` 的 `after_operation` 校验）⇒ AI 的意图对象在 `action=remove` 时 `after_operation` 必须为 `null`，否则 422 | §3.1 / §3.2 |
| F12 | issue 说「29 条内置条件成为出厂知识，默认正确、商家零配置」 | ⚠️ 措辞要收窄：**「默认存在且默认正确」成立**（29 行已在种子/DB 里）；但「出厂知识」若被读成「AI 自动生成新条件」则**不成立**（§7 N1 不做） | §1 已加限定段 |

| F13 | issue #4652 给的解释形状是 `{因为:{kind:'craft', value:'韩褶'}, 结果:'加了 上车布', 位置:'**打褶槽之后**'}` | 今天 `production_route_rules` **没有槽位列**（只有 `after_operation` 锚点列）；真值源 `ROUTE_MAINLINE` 里**有** `⟪工艺槽位⟫` 占位但**不落库**（`ROUTE_MAINLINE_STEPS` 不含它） | §2.5 定三层口径；§5.1 新表**必须**同时带 `slot` / `slot_holder` 与 `after_operation` |

### 8.2 无法判定（**不猜**）

| # | 事项 | 为什么无法判定 | 谁/什么能判定 |
|---|---|---|---|
| U1 | **商家自建的规则行有多少** | 静态只能读**种子**（29 行）；真实库里商家可能已自建行（`POST /route-rules` 自 #4616 起可用）。本文件**未连真库** | 真库读数：`SELECT tenant_id, count(*) FROM production_route_rules WHERE deleted=0 AND status='active' GROUP BY tenant_id`（需真库访问） |
| U2 | **`shaped` 是否该真正接线** | 今天 `isShaped=false` 由**代码侧硬接线**（`backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:541` 的 `removeIf`）实现，**不走规则表**。是否该收归规则表 = **业务裁定**，不是技术事实 | 用户裁定 |
| U3 | **「影响面 N 个部位」的口径** | 「N 个部位」依赖「该工艺实际被哪些部位用到」，而这取决于**订单/商品数据**（不是配置）。本文件只给**形态**（数字必须来自工具读数），不给具体口径 | 实现时由 `craft_operation_query` 的返回定义 |
| U4 | **撤销记录的落点**（会话 metadata vs 独立表） | 本文件推荐会话侧（§3.4），但**会话 metadata 的既有结构本单未逐字段核对** | 实现前读 `backend/ai-agent-service/app/memory/` 与会话模型 |
| U5 | **阶段 2 落库走 `validate_input`+写工具 还是前端直调** | 两条路都可行，各有代价（§3.3.2）。**必须实现前裁定**，本文件给推荐但**不替业务/架构定** | 架构裁定（本文件的推荐 = 前者） |
| U6 | **「一个完整计费周期」的确切长度**（§5.6 退场判据） | 「30 天」是本文件的**建议值**，不是实测约束 | 运营裁定 |
| U7 | **`buildRoute` docstring 的「唯一 Java 实现」是笔误还是设计意图** | 静态可判「与实测不符」（F5），但**无法判定作者本意** | 作者 / issue 回溯 |
| U8 | **AI 侧 `confidence` 的判定标准** | 本文件给了三值枚举（high/medium/low），但**阈值口径**依赖模型能力实测 | 实现后实测（**且默认不跑 LLM，需用户显式要求**） |
| U9 | **槽位模型的确切定义**（有哪些槽、`slot_holder` 如何派生、与 `after_operation` 的换算规则） | 定义权在 `docs/design/operation-slot-model.md`（**本文件写就时尚未在 `origin/main` 上** ⇒ 无法引用其内容）。本文只按父 agent 给出的口径**表述**，**不替它定义** | 该设计落地后，§4.1 / §5.1 的 `slot` / `slot_holder` 需按它**回填确切值域** |

---

## 附录 A：所有实测命令与数字（可复现）

**所有命令均以 `origin/main` 为真值源**（不读本地工作区）。

```bash
cd "/Users/guangzhen.zk/ai native/migao"
git fetch origin main -q

# ── ① 表结构（V71）──────────────────────────────────────────────
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | sed -n '242,262p'
#   → trigger_kind CHECK 四值（craft/option/shaped/processing_item）；action CHECK 两值（insert/remove）
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | grep -n "CHECK (action"   # :248
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | grep -n "uk_production_route_rules_tenant_trigger_operation"  # :258

# ── ② 种子三源行数 ──────────────────────────────────────────────
git show origin/main:backend/admin-api/src/main/resources/db/migration/V71__normalize_routing_model_structure.sql | grep -cE "^\s*\('rr-v70-"   # 26
git show origin/main:backend/admin-api/src/main/resources/db/migration/V84__seed_processing_item_route_rules.sql | grep -cE "^\s*\('0[0-9]', 'processing_item'"  # 3
#   ⇒ 26 + 3 = 29

# ── ③ ROUTE_RULES 分布（AST，不靠正则）──────────────────────────
git show origin/main:backend/ai-agent-service/app/production/routing.py > /tmp/rt_4650.py
python3 - <<'PYEOF'
import ast, collections
t = ast.parse(open('/tmp/rt_4650.py').read())
rows = next(ast.literal_eval(n.value) for n in t.body
            if isinstance(n, ast.AnnAssign) and getattr(n.target, 'id', '') == 'ROUTE_RULES')
print('total', len(rows), '| action', dict(collections.Counter(r['action'] for r in rows)),
      '| kind', dict(collections.Counter(r['trigger_kind'] for r in rows)))
ins = [r for r in rows if r['action'] == 'insert']; rem = [r for r in rows if r['action'] == 'remove']
d = collections.defaultdict(list)
for r in ins: d[r['operation']].append((r['trigger_kind'], r['trigger_value'], r['position'], r['after_operation']))
print('insert targets', len(d), '| remove targets', sorted({r['operation'] for r in rem}),
      '| insert∩remove', sorted(set(d) & {r['operation'] for r in rem}))
for k, v in sorted(d.items()): print(' ', k, '←', v)
PYEOF
#   → total 26 | action {'insert': 21, 'remove': 5} | kind {'option': 16, 'craft': 10}
#   → insert targets 16 | remove targets ['复烫','定型'] | insert∩remove []

# ── ④ processing_item 不在 ROUTE_RULES ─────────────────────────
git show origin/main:backend/ai-agent-service/app/production/routing.py | grep -c "processing_item"   # 5（全为注释/分支）
git show origin/main:backend/ai-agent-service/app/production/routing.py | sed -n '708p'               # ROUTE_RULES: List[Dict[str, Any]] = [

# ── ⑤ 锚点差异（真值源函数实跑）────────────────────────────────
git show origin/main:backend/ai-agent-service/app/production/routing.py > /tmp/routing_4650_mod.py
backend/ai-agent-service/.venv/bin/python - <<'PYEOF'
import importlib.util
spec = importlib.util.spec_from_file_location("r", "/tmp/routing_4650_mod.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for label, pos in [("韩褶·布帘", {"curtain_type":"布帘","craft":"韩褶","special_options":[]}),
                   ("四爪钩·布帘", {"curtain_type":"布帘","craft":"四爪钩","special_options":[]}),
                   ("穿杆·布帘", {"curtain_type":"布帘","craft":"穿杆","special_options":[]}),
                   ("平幔·布帘", {"curtain_type":"布帘","craft":"平幔","special_options":[]}),
                   ("打孔·布帘", {"curtain_type":"布帘","craft":"打孔","special_options":[]}),
                   ("韩褶·纱帘", {"curtain_type":"纱帘","craft":"韩褶","special_options":[]})]:
    r = m.build_route_v2(pos)
    print(f"{label:12s} {len(r):2d} →", " → ".join(r))
PYEOF
#   → 韩褶·布帘   12 → 精裁→三边→韩褶→上车布→熨烫→定型→复烫→车被→外帘打卷→打包→外帘装袋→外帘发货
#   → 四爪钩·布帘  9 → 精裁→三边→上车布→熨烫→车被→外帘打卷→打包→外帘装袋→外帘发货
#   → 穿杆·布帘    8 → 精裁→三边→熨烫→车被→外帘打卷→打包→外帘装袋→外帘发货
#   → 平幔·布帘    9 → 精裁→三边→熨烫→定型→车被→外帘打卷→打包→外帘装袋→外帘发货
#   → 打孔·布帘   11 → 精裁→三边→打孔→熨烫→定型→复烫→车被→外帘打卷→打包→外帘装袋→外帘发货
#   → 韩褶·纱帘    7 → 精裁→三边→韩褶→外帘打卷→打包→外帘装袋→外帘发货
#   ⇒ 上车布：韩褶 下 index=3（前一道=韩褶）；四爪钩 下 index=2（前一道=三边）

# ── ⑥ 写面端点与护栏 ───────────────────────────────────────────
git grep -n "route-rules" origin/main -- backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java
#   → GET :574 · GET /route-rule-options :588 · POST :622 · DELETE :637 · PUT .../customer-unit-price :392
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java | sed -n '399,480p'
#   → trigger_kind 闭词表 / trigger_value 词表校验 / operation+after_operation 工序库存在 / remove 不收锚点 / 409

# ── ⑦ 运行时插入路径（Java，唯一性=取代）──────────────────────
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java | sed -n '799,845p'
#   → insertConditionalOperations：唯一性 = 取代（removeIf 先移除旧位置再插）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java | grep -n "insertConditionalOperations(operations"   # :549 调用点

# ── ⑧ 快照表无 reason 列 ───────────────────────────────────────
git show origin/main:docs/sql/schema.sql | sed -n '1054,1075p'
#   → processing_position_operations 列：id/tenant_id/processing_order_id/position_name/order_item_id/
#     position_kind/seq/operation_name/group_name/unit/qty/qty_source/unit_price/factor/
#     is_must_finish/is_start_marker/status/done_qty/created_at/updated_at/deleted
#     ⇒ 无任何 reason* 列

# ── ⑨ 规则表无版本账 ───────────────────────────────────────────
git grep -n "CREATE TABLE IF NOT EXISTS production_routing_versions" origin/main -- docs/sql/schema.sql   # :1239（只记路线序列）
git grep -n "版本账" origin/main -- backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java
#   → :49「序列**真的变了**才追加 production_routing_versions 一行」⇒ 规则行本身零留痕

# ── ⑩ ai-agent 侧零工艺工具 ────────────────────────────────────
git grep -ln "route-rules\|operation-positions" origin/main -- backend/ai-agent-service
#   → 只命中 backend/ai-agent-service/app/production/routing.py（注释）

# ── ⑪ 前端落点 ─────────────────────────────────────────────────
git show origin/main:frontend/admin-web/src/app/\(dashboard\)/production/routings/page.tsx | grep -n "data-testid=\"route-rules\"\|data-testid=\"route-rules-new\"\|data-testid=\"route-rules-total\""
#   → :2583 route-rules · :2591 route-rules-new · :2586 route-rules-total

# ── ⑫ 最大迁移号（阶段 4 新迁移 = V88）──────────────────────────
git ls-tree -r --name-only origin/main -- backend/admin-api/src/main/resources/db/migration | sort -V | tail -1
#   → V87__retire_factor_route_rules.sql

# ── ⑬ 覆盖体检（零 LLM，秒级）──────────────────────────────────
python3 scripts/mibao_coverage.py --check
#   → ✅ B 端覆盖体检通过；薄覆盖（只报告）5 个：piecework_query, processing_order_update,
#     production_progress_query, session_manage, sku_update
```

---

## 附录 B：建议的实施顺序（一句话理由）

**阶段 1（呈现收敛，零迁移）→ 阶段 3（可解释，含 `reason` 落库）→ 阶段 2（AI 对话式改条件）→
阶段 4（承载收敛）。**

理由：① **阶段 1 是零迁移的、收益立刻可见的、且是阶段 2 降级路径的前置**（AI 挂了也得能在工序上手动改）；
② **阶段 3 必须在阶段 2 之前** —— 确认卡要显示"将发生的变化"，而"变化"的可信来源就是阶段 3 的
结构化理由（先有"看得懂"，才有"敢改"）；③ **阶段 2 在阶段 1/3 之上才有落点**（条件已在工序上 + 理由已结构化）；
④ **阶段 4 放最后且风险最高**：它的第一步不是迁移，而是**把三份规则语义收敛成一份**（§5.4 / F5），
这一步本身就该是一次独立可合并、可回滚的改动。
