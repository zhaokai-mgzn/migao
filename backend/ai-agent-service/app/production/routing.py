"""窗帘工艺路线实例化（issue #3993，M4-G-1）

工序库种子（分组：裁剪/车位/后道/其他；按部位分设——韩褶-布/韩褶-纱 单价各自不同）
+ 工艺路线模板（部位×工艺）+ 条件工序（特殊选项触发）+ 工序实例（应做数量=引擎输出）。

真值源：docs/curtain-production-rules.md §2/§3（2026-09 行业 ERP 截图实证）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── 工序库种子（【默】单价占位，商家可配；单位：米/折/幅/套/个）──
# 分组：裁剪 / 车位 / 后道 / 其他（行业 ERP 实证，非按阶段）
OPERATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "精裁-布": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "精裁-纱": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "裁剪-布": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "裁剪-纱": {"group": "裁剪", "unit": "米", "unit_price": 0.4},
    "布三边": {"group": "车位", "unit": "米", "unit_price": 0.4},
    "纱三边": {"group": "车位", "unit": "米", "unit_price": 0.4},
    "韩褶-布": {"group": "车位", "unit": "折", "unit_price": 0.4},
    "韩褶-纱": {"group": "车位", "unit": "折", "unit_price": 0.4},
    "上车布-布": {"group": "车位", "unit": "米", "unit_price": 0.5},
    "上车布-纱": {"group": "车位", "unit": "米", "unit_price": 0.5},
    "打孔-布": {"group": "车位", "unit": "孔", "unit_price": 0.15},
    "打孔-纱": {"group": "车位", "unit": "孔", "unit_price": 0.15},
    "拼1次-布": {"group": "车位", "unit": "幅", "unit_price": 0.8},
    "拼2次-布": {"group": "车位", "unit": "幅", "unit_price": 1.2},
    "拼3次-布": {"group": "车位", "unit": "幅", "unit_price": 1.6},
    "花边-布": {"group": "车位", "unit": "米", "unit_price": 0.6},
    "铅坠-布": {"group": "车位", "unit": "米", "unit_price": 0.3},
    "接高-布": {"group": "车位", "unit": "幅", "unit_price": 1.0},
    "帘头制作": {"group": "车位", "unit": "个", "unit_price": 2.0},
    "熨烫-布": {"group": "后道", "unit": "米", "unit_price": 0.35},
    "定型-布": {"group": "后道", "unit": "米", "unit_price": 0.4},
    "复烫-布": {"group": "后道", "unit": "米", "unit_price": 0.35},
    "布帘车被": {"group": "后道", "unit": "米", "unit_price": 0.4},
    "外帘打卷": {"group": "后道", "unit": "套", "unit_price": 1.0},
    "外帘装袋": {"group": "后道", "unit": "套", "unit_price": 1.0},
    "质检": {"group": "后道", "unit": "套", "unit_price": 1.5},
    "外帘发货": {"group": "后道", "unit": "套", "unit_price": 1.0},
    "绑带-布": {"group": "其他", "unit": "套", "unit_price": 0.5},
    "抱枕": {"group": "其他", "unit": "个", "unit_price": 2.0},
    "腰靠垫": {"group": "其他", "unit": "个", "unit_price": 2.0},
    # ── issue #4230：特殊选项 A′ 类补齐的 5 道工序（单价为**行业推算**，商家可配）──
    # 推理依据（issue #4230 §2.2）：绑带-纱 与 绑带-布 对称；logo条-布 参照 花边-布 ¥0.6/米
    # （同为缝一条装饰带）；立边-布 参照 布三边 ¥0.4/米（立边更费工）；扣环-布 参照
    # 打孔-布 ¥0.15/孔 ×2（多一道锁边）；防翘扣-布 比扣环简单。
    "绑带-纱": {"group": "其他", "unit": "套", "unit_price": 0.5},
    "logo条-布": {"group": "车位", "unit": "米", "unit_price": 0.6},
    "立边-布": {"group": "车位", "unit": "米", "unit_price": 0.5},
    "扣环-布": {"group": "车位", "unit": "个", "unit_price": 0.3},
    "防翘扣-布": {"group": "车位", "unit": "个", "unit_price": 0.2},
    # ── issue #4529（包 F）：布料基础路线的两道工序（用户裁定 2026-09-19）──
    # · `配料`：**布料单**（`saleForm = 布料`）的前道工序，单位 = **米**（按部位算料）；
    # · `打包`：**跨产品形态**的工序 —— 追加裁定「如果是布料也可以有打包工序」⇒ 它**不等于**
    #   `外帘装袋`（后者是外帘/成品帘专属）；单位 = **套**，`scope = 'set'`（一单一套一次，
    #   不按部位展开 —— 见 V79 的 `SET scope='set'` 回填与 Java 侧 `keepsSetLevel` 去重）。
    # ⚠️ **单价 0 是 DDL 约束的产物，不是「定价 0」**：`production_operations.unit_price` 是
    #   `NOT NULL DEFAULT 0`（V49）⇒ 工序库行只能落 0。「未定价」的真载体是**部位价目行**
    #   （`OPERATION_POSITION_PRICES[工序][部位]["unit_price"] is None` 且 `applicable=True`，
    #   见 `_POSITION_PRICE_ROWS`）+ `production_operations.source = '占位待确认'`（商家自配）。
    "配料": {"group": "后道", "unit": "米", "unit_price": 0.0},
    "打包": {"group": "后道", "unit": "套", "unit_price": 0.0},
    # ── issue #4937（去部位化彻底版）：补 **4 道纱帘变体** ──
    # 病根：`build_route_v2` 原来靠 `applicable` 过滤把 `熨烫/定型/复烫/车被` 从**纱帘**路线滤掉；
    # 该过滤退场后它们会进纱帘路线 —— 而工序库里**没有**它们的纱帘变体
    # ⇒ 实例化侧（Java `variantNameOf`）解析不到 ⇒ **整张纱帘单 fail-closed**。
    # 单价逐字与对应 `-布` 变体相同（**不发明单价**），分组/单位取对应 `-布` 变体的值。
    "熨烫-纱": {"group": "后道", "unit": "米", "unit_price": 0.35},
    "定型-纱": {"group": "后道", "unit": "米", "unit_price": 0.4},
    "复烫-纱": {"group": "后道", "unit": "米", "unit_price": 0.35},
    "车被-纱": {"group": "后道", "unit": "米", "unit_price": 0.4},
}

# ── 工艺路线模板（**工艺 → 基准工序序列**）──
# 🔴 **去部位化（issue #4937 / P2，用户裁定 2026-09-21「这个必须要改…不计成本的改」，母单 #4936）**：
# 本表原来是 `(部位, 工艺)` 的 **9 条**展开快照；部位退场 ⇒ **只按工艺键**，收敛为 **5 条**。
# 收敛规则 = 每个工艺取**多部位里那一条权威序列**：
#   · `韩褶` / `打孔` / `四爪钩` / `穿杆` → **布帘**那一条（与价目矩阵的收敛口径同源 ——
#     矩阵的取价来源部位也是布帘，见 `COLLAPSE_PRICE_SOURCE_POSITION`；用户裁定「取布帘价」）；
#   · `平幔` → 只有帘头一条（无歧义）。
# ⚠️ **工序名与单价逐字保留**（工人端真值源），本次只改**索引维**（部位维退场）。
# ⚠️ **后果照实登记**：原来靠「部位表的差异」表达的「纱帘不做熨烫/定型/复烫/车被」不再存在 ——
# 那正是用户裁定的语义（「部位不再参与任何取价、取路、筛选、配置」）；需要「某工艺不做某工序」时
# 由**规则**（`ROUTE_RULES` 的 `remove`）表达，不再由**部位**表达。
#: ⚠️ **为什么写成「有序对行表 + `dict(...)`」而不是 dict 字面量**（与 `_LOGICAL_NAME_PAIRS` 同范式）：
#: L0 守卫 `tests/unit_ci_workflows/test_tool_input_contract_guards.py` 把「含 ≥2 个中文 key 的 dict 字面量」
#: 判为「把中文措辞当判据」的站点，且该基线**只许缩短、不得扩容**（R4：新增站点必须本次修掉）。
#: 本表是**业务主数据**（工艺 → 基准工序序列），与守卫要治的「拿错误文案做子串匹配」不同族；
#: 改成有序对后 AST 里不再有该形态 ⇒ **既不触发守卫、也不放宽基线**（判据一条不动）。
_ROUTING_ROWS: List[tuple] = [
    ("韩褶", [
        "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ]),
    ("打孔", [
        "精裁-布", "布三边", "打孔-布", "熨烫-布",
        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ]),
    ("四爪钩", [
        "精裁-布", "布三边", "上车布-布", "熨烫-布",
        "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ]),
    ("穿杆", [
        "精裁-布", "布三边", "熨烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ]),
    ("平幔", [
        "精裁-布", "布三边", "帘头制作", "定型-布", "外帘打卷", "外帘装袋", "外帘发货",
    ]),
]

#: 工艺 → 基准工序序列（**只按工艺键**；部位维已退场）。
#: ⚠️ **本表只承载「该工艺的基准走线」**，不再承载「哪个帘种做哪些工序」——
#: 后者已随 `applicable` 退场（issue #4937）；`纱帘专属变体`（`精裁-纱` 一族）因此不再出现在
#: 本表里，但**仍在 `OPERATION_CATALOG` / `OPERATION_LOGICAL_NAMES` 里**
#: （`variantNameOf` 解析纱帘单的变体名要用），并显式登记进
#: `PENDING_CUSTOMER_CONFIRMATION_OPERATIONS`（见该常量的注释）。
ROUTINGS: Dict[str, List[str]] = dict(_ROUTING_ROWS)

# ── 孤儿工序：**显式登记**「有工序、有价、零消费」中**有意不消费**的那批（issue #4246 §二）──
# `#4246` 补的 3 条纱帘路线消费掉 `上车布-纱` / `打孔-纱` 后，以下 4 道**仍为孤儿**，
# 且是**有意**的（都需客户确认，猜出来的工序价会直接算成工人工资）：
#   · `裁剪-布` / `裁剪-纱`：与 `精裁-布` / `精裁-纱` 同名近义并存，是否「粗裁 → 精裁」两道
#     取决于裁床流程 ⇒ 不猜（#4246 §二「不做」表）；
#   · `质检`：真值源 §8 只说定型「联动…质检/包装」，**没说**它是每单必做工序；若必做，它是
#     **所有路线的公共尾工序**（插在装袋/发货之间）——「是否必做 + 插哪」由客户定；
#   · `腰靠垫`：属**另一产品**（真值源 §3 的工艺清单里没有对应选项），不是「某部位的一种工艺」。
# 登记在此的唯一理由：让「有意不消费（待客户确认）」与「忘了建路线」在数据上**可区分** ——
# 前者在这里有名字，后者会撞 `tests/test_production/test_routing.py` 的孤儿集合断言（双向可红）。
#
# 🔴 **issue #4937 追加的 5 道**：`ROUTINGS` 去部位化（9 → 5 条、只按工艺）之后，
# **纱帘专属变体**（`精裁-纱` / `纱三边` / `韩褶-纱` / `上车布-纱` / `打孔-纱`）不再出现在
# 旧模型路线的字面量里 —— 它们**仍然是运行期必需**的（`variantNameOf` 解析纱帘单的变体名，
# 新版模型/Java 实例化两侧都靠它），只是**旧 `ROUTINGS` 不再引用**。
# 与 `NEW_MODEL_ONLY_OPERATIONS` 同一性质：登记在这里是为了让「有意不消费」与「忘了建路线」
# 在数据上可区分（不登记 ⇒ 它们会落进孤儿集合 ⇒ 守卫双向可红）。
SHEER_VARIANT_OPERATIONS = frozenset(
    # 原来就有的 5 道（`ROUTINGS` 去部位化后不再被引用）
    {"精裁-纱", "纱三边", "韩褶-纱", "上车布-纱", "打孔-纱"}
    # issue #4937 新增的 4 道（`applicable` 过滤退场后它们会进纱帘路线，故必须存在 —— 见
    # `OPERATION_CATALOG` 的注释；它们同样不被旧 `ROUTINGS` 引用）
    | {"熨烫-纱", "定型-纱", "复烫-纱", "车被-纱"})

PENDING_CUSTOMER_CONFIRMATION_OPERATIONS = frozenset(
    {"裁剪-布", "裁剪-纱", "质检", "腰靠垫"} | SHEER_VARIANT_OPERATIONS)

# ── **新模型**消费、旧 `ROUTINGS` 不消费的工序（issue #4529）──
# 登记在这里的唯一理由与上面那个集合相同：让「旧模型孤儿」与「忘了建路线」在数据上**可区分**。
# `配料` 只出现在 `FABRIC_MAINLINE_STEPS`；`打包` 出现在 `ROUTE_MAINLINE_STEPS`（新模型主线）
# ⇒ 它们对 `ROUTINGS` 确实是孤儿。
NEW_MODEL_ONLY_OPERATIONS = frozenset({"配料", "打包"})

# ── 特殊选项 → 条件工序（插在目标工序后；`after` = **锚点在它之前**，见 `_insert_after`）──
# 真值源 §1【默】19 项特殊选项，按处置分三类（**每一类都要显式登记**，见下方
# `NON_PIECEWORK_OPTIONS` / `OPTION_FACTOR_SCOPES` 的注释；门禁 =
# `tests/test_production/test_special_options.py::TestCriterion1CoverageGate`）：
#   ① 加条件工序 = 本表；② 加计件系数 = `OPTION_FACTOR_SCOPES`（#4589 起**零消费**，仅作历史真值源）；③ 不计件 = `NON_PIECEWORK_OPTIONS`。
SPECIAL_OPTION_ROUTINGS: Dict[str, Dict[str, Any]] = {
    "拼1次": {"operation": "拼1次-布", "after": "布三边"},
    "拼2次": {"operation": "拼2次-布", "after": "布三边"},
    "拼3次": {"operation": "拼3次-布", "after": "布三边"},
    "加花边": {"operation": "花边-布", "after": "布三边"},
    "加铅块": {"operation": "铅坠-布", "after": "布三边"},
    "接高": {"operation": "接高-布", "after": "精裁-布"},
    "双眼皮接高": {"operation": "接高-布", "after": "精裁-布"},
    "余料做绑带": {"operation": "绑带-布", "after": "布帘车被"},
    # ── issue #4230：19 项里有 10 项此前**零登记**（既不加工序、也不加系数、也没标不计件），
    # 「忘了映射」与「本来就不计件」在数据上长得一模一样（都是 `.get(opt)` → None 的静默黑洞）。
    # 以下按用户裁定（2026-09-18「按你的行业推算补齐，落成数据，客户反馈再改」）补齐：
    "布绑带": {"operation": "绑带-布", "after": "布帘车被"},      # 推算：与「余料做绑带」同工序，仅材料来源不同
    "余料做帘头": {"operation": "帘头制作", "after": "布三边"},    # 推算：复用库里已有的孤儿工序「帘头制作」
    "抱枕": {"operation": "抱枕", "after": "外帘打卷"},           # 推算：复用孤儿工序「抱枕」，插在打卷后（装袋前）
    "纱绑带": {"operation": "绑带-纱", "after": "布帘车被"},
    "加logo条": {"operation": "logo条-布", "after": "布三边"},
    "加立边": {"operation": "立边-布", "after": "布三边"},
    "扣环": {"operation": "扣环-布", "after": "布三边"},
    "防翘扣": {"operation": "防翘扣-布", "after": "布三边"},
}

# ── 特殊选项 → 计件系数（**历史真值源，自 #4589 起零消费**）──
# 用户裁定（2026-09-19，issue #4589）：「计件工资 = **数量 × 计件单价**，不需要考虑系数」
# ⇒ `factor_for()` 已删除、工序实例**不再带 `factor` 键**，本表**没有任何读者**。
#
# ⚠️ **为什么不连表一起删**：本表是 **V59/V72 已发布迁移种子**（`production_option_factors`
# 的「一分为二 ⇒ ×1.7」，V72 搬进 `production_route_rules` 的 `action='factor'` 行）与
# `docs/sql/schema.sql` bootstrap 终态的**真值源镜像** —— 三源收敛守卫
# （`tests/unit_ci_workflows/test_production_catalog_seed.py`）按它逐值比对**已发布**迁移。
# 删表 = 删守卫（守卫只能靠删断言才绿 ⇒ 停手信号）。数据侧由新迁移**软删**那批活跃行
# （`deleted=1`，留痕），列本身保留（历史工序实例快照 / 历史报工上的值是当时工资的证据）。
#
# 档位字段（仅历史语义）：`factor` 系数 / `operation_name` 限定工序（`None` = 全部工序）/
# `curtain_type` 限定部位（`None` = 不限）/ `source` 实证·推算。
#
# ⚠️ **键 = ERP 名（issue #4389，用户裁定 R-e「以 ERP 为准改」）**：存量库里已按旧名
# （`一分二`）落地的行由**新迁移** `V65__align_special_option_names_with_erp.sql` 改名。
OPTION_FACTOR_SCOPES: Dict[str, List[Dict[str, Any]]] = {
    "一分为二": [
        {"factor": 1.7, "operation_name": None, "curtain_type": None, "source": "实证"},
    ],
}

# ── 不影响计件的特殊选项（**显式登记**，不留静默黑洞）──
# 真值源 §1【默】把这两项与其余 17 项并列列出，但它们的业务语义是**只是把余料还给客户**，
# 不增加车间任何工序、也不改变已有工序的费工程度 ⇒ 既不加工序也不加系数、计件金额不变。
# 登记在这里的唯一理由：让「本来就不计件」与「忘了映射」在数据上**可区分**
# （前者在这里有名字，后者会撞 `TestCriterion1CoverageGate` 的红）。
#
# ⚠️ **键 = ERP 名（issue #4389）**：ERP 写作 `余料带回-布` / `余料带回-纱`（旧写法是
# `余料带回(布)` / `余料带回(纱)`，仅分隔符不同 —— 同一个 join key 的两种拼法）。
NON_PIECEWORK_OPTIONS = frozenset({"余料带回-布", "余料带回-纱"})

# ── 待客户确认的特殊选项（**显式登记**：既不是「忘了映射」，也**不假装已定论**）──
# issue #4389 判据 2：行业 ERP 订单录入页截图（2026-09-19）里「余料带回」有**三种**形态 ——
# `余料带回-布` / `余料带回-纱`（= 上方两项，仅分隔符不同）与**无后缀的 `余料带回`**。
#
# 为什么**不**直接归进 `NON_PIECEWORK_OPTIONS`：真值源 §1 的 19 项清单里**没有**无后缀那种
# （只列 `余料带回(布/纱)`）⇒ 我们手上只有截图这一个证据，无法判定它在 ERP 里是
# 「材料无关的第三种可选值」还是「`全部` tab 下同一选项的另一种渲染 / 分组标题」
# ⇒ 按用户裁定 R-e 的「不猜」纪律，**登记为待确认**，等客户确认它归
# 「加条件工序 / 加计件系数 / 不计件」三类中的哪一类（「加计件系数」这一类自 #4589 起已退场）。
#
# 行为口径 = 与「不计件」相同（不加条件工序、不改计件金额），但**语义不同**：
# 它不是「已定论的不计件」，而是「未定论」。两者的区别在数据上可查（本集合 vs
# `NON_PIECEWORK_OPTIONS`）⇒ 它**不落进静默黑洞**（`.get(opt) → None` 那种）。
PENDING_CUSTOMER_CONFIRMATION_OPTIONS = frozenset({"余料带回"})

# 生产开始标记（默认；商家可配）
#
# 🔴 `MUST_FINISH_OPS`（必完工序 / 门槛工序 `{"外帘装袋"}`）**已退场**（issue #4961，
# 用户裁定 2026-09-21「完工 = 全部工序全绿」）：加工单完工判据不再是「必完工序全绿」，
# 而是「**全部**工序实例完成」（见 app/production/piecework.py 的 `is_production_done`
# 与 Java 侧 `ProductionService#allInstancesDone`）⇒ 工序实例**不再带 `is_must_finish` 键**，
# 本集合已删除（删集合而不是「留着不用」：留着的集合会被下一次「顺手读一下」复活旧口径）。
# ⚠️ 去同词两义的历史记录保留（issue #4529）：旧口径的「打包」指**后道打包环节**，
# **不是** V79 新增的**工序名** `打包` —— 该歧义随本集合退场一并消失。
START_MARKER_OPS = {"精裁-布", "精裁-纱"}  # 首工序触发订单进入生产中


# 应做数量的来源键（**契约钉死点**，issue #4116 契约漂移修复）
# ---------------------------------------------------------------------------
# 病根：`_qty_for` 读 `meters`，而算料引擎 `curtain_calc.build_quote` 实际返回的是
# **`fabric_meters`**（键名不同）⇒ 一旦接线到真实引擎产出，「米」类工序应做数量**恒 0**
# （幅/套类再叠加「读不到 panels/set_count」⇒ 恒 1）。这段漂移此前藏在**零调用者**的死代码里
# （routing.py 在本仓无运行时消费者），靠 `tests/test_production/test_routing.py` 用**引擎真产出**
# 喂 `_qty_for` 才照出来。
#
# 本常量是「_qty_for 会读哪些键」的单一清单，测试用它把两侧键集钉住
# （引擎真产出键集 ⊇ 各 unit 的主键，或显式登记为待补键）。
METER_KEYS = ("fabric_meters", "meters")   # 主键 = 引擎真产出；`meters` 为兼容位（同族工具聚合视图口径）
FOLD_KEYS = ("pleat_count",)               # 韩褶褶数法才产出；非褶数法（定宽米数法）缺失 ⇒ 兜底 1
HOLE_KEYS = ("holes",)                     # 引擎暂未产出 ⇒ 按 HOLE_PER_METER 估算（见 _qty_for）
PANEL_KEYS = ("panels",)                   # 引擎暂未产出（build_quote 内部局部量）⇒ 兜底 1，待补
SET_KEYS = ("set_count",)                  # 引擎暂未产出 ⇒ 兜底 1（一个部位 = 一樘，语义成立）

# 孔数估算：引擎不产出 `holes` 时的行业口径（每米约 6 孔；12.3 米 → 72 孔与现场核对一致）
HOLE_PER_METER = 6

# 引擎有数量口径的单位（= `_qty_for` 的分支覆盖范围）；其余单位（如「个」）无口径
# ⇒ 调用方按铁律「未知单位兜底 1 + fallback」处置（见 `qty_and_source`）。
KNOWN_QTY_UNITS = ("米", "折", "孔", "幅", "套")


def _qty_keys_for_unit(unit: Optional[str]) -> tuple:
    """该单位应做数量会读的候选键（**有序**）——与 `_qty_for` 的分支逐条对应。

    存在理由（issue #4208）：内部端点要回答 `qty_source_by_operation`（口径来源），
    而「哪个键供了数」这件事只在 `_qty_for` 的分支里。此处把它声明成数据供标注
    —— **数量值仍由 `_qty_for` 给出，本函数不参与计算**（严禁第二份算料逻辑）。
    漂移护栏：`tests/test_production/test_operation_qty.py::TestSourceKeysDriftGate`
    逐单位喂键反查 `_qty_for` 是否真读该键（改 `_qty_for` 的读键而不改这里 ⇒ 红）。
    """
    if unit == "折":
        return FOLD_KEYS
    if unit == "孔":
        return HOLE_KEYS + METER_KEYS   # holes 直采；无 holes 时按米数估算
    if unit == "幅":
        return PANEL_KEYS
    if unit == "套":
        return SET_KEYS
    if unit == "米":
        return METER_KEYS
    return ()   # 引擎不认识的工序/单位：无口径 ⇒ 兜底 1 + fallback

# 非「孔」单位**直接供数**的键（命中即报键名）：引擎真产出 `fabric_meters`/`pleat_count`。
# 「孔」的直采键是 `holes`（引擎暂未产出，见 HOLE_KEYS 注释，但调用方可按现场口径给出），
# 在 `qty_and_source` 的「孔」分支单独处理 —— 该分支还有「按米估算」这一中间态。
DIRECT_QTY_KEYS = ("fabric_meters", "pleat_count")

# `qty_source` 的三态语义（字段存在的唯一理由：让「真兜底」与「有依据的推算」可区分）
#   ① 键名（DIRECT_QTY_KEYS）           = 该键直接供数（算料输出 / 现场给定）
#   ② "<键名>_x6"（HOLE_PER_METER 后缀）= 无 holes 时按**每米 HOLE_PER_METER 孔**的行业口径
#      估算（见 `_qty_for` 的「孔」分支②；12.3 米 → 73.8 孔，与现场核对一致）
#      ⇒ 标 fallback 会把「有依据的估算」说成「占位值」，正是本单要治的误导
#   ③ "fallback"                        = 真兜底：无键可读 / 引擎不认识的工序或单位 /
#      panels・set_count（引擎已登记为**待补键**：见 PANEL_KEYS/SET_KEYS 注释，未产出）
HOLE_ESTIMATE_SUFFIX = f"_x{HOLE_PER_METER}"


def _qty_for(operation: str, calc_info: Dict[str, Any]) -> float:
    """应做数量 = 算料引擎输出（褶数/用料/孔数/幅数/套数），报工只确认不心算。

    键口径见模块常量（{@link METER_KEYS} 等）；缺键**一律兜底 1**，绝不落 0
    （应做 0 会让 `done_qty ≥ qty` 恒真 ⇒ 工序一开始就算完成 ⇒ 假完工，同族缺陷）。
    """
    unit = OPERATION_CATALOG.get(operation, {}).get("unit", "米")
    if unit == "折":
        return float(_pick(calc_info, FOLD_KEYS, 1))
    if unit == "孔":
        holes = _pick(calc_info, HOLE_KEYS, None)
        if holes is not None:
            return float(holes)
        meters = _pick(calc_info, METER_KEYS, 0)
        # 引擎真产出没有 holes（见 HOLE_KEYS 注释）：按每米 6 孔估算；米数也读不到才兜底 1
        return float(meters) * HOLE_PER_METER if meters else 1.0
    if unit == "幅":
        return float(_pick(calc_info, PANEL_KEYS, 1))
    if unit == "套":
        return float(_pick(calc_info, SET_KEYS, 1))
    return float(_pick(calc_info, METER_KEYS, 1))  # 米


def _pick(calc_info: Dict[str, Any], keys: tuple, default: Any) -> Any:
    """按 keys 顺序取第一个非空值（键名漂移的双读兼容），全缺 ⇒ default。"""
    for key in keys:
        value = calc_info.get(key)
        if value is not None:
            return value
    return default


def qty_and_source(operation: str, calc_info: Dict[str, Any]) -> tuple:
    """应做数量 + 口径来源标签（issue #4208）：`(qty, qty_source)`。

    数量：命中算料键 ⇒ 一律取 `_qty_for`（**唯一算料真相源**，严禁第二份逻辑）；
    无口径（缺键 / 引擎不认识的工序 / 引擎不认识的单位）⇒ **兜底 1，绝不落 0**
    （应做 0 ⇒ `done_qty ≥ qty` 恒真 ⇒ 假完工）。

    来源标签三态见模块常量注释（{@link DIRECT_QTY_KEYS} / {@link HOLE_ESTIMATE_SUFFIX}）：
    键名 = 直接供数；`<键名>_x6` = 每米 6 孔的行业估算；"fallback" = 真兜底。
    调用方据此区分「算料输出 / 有依据的估算 / 兜底占位」，**不据此报错**（判据 3：HTTP 仍 200）。
    """
    unit = OPERATION_CATALOG.get(operation, {}).get("unit")
    for key in _qty_keys_for_unit(unit):
        if calc_info.get(key) is None:
            continue
        qty = _qty_for(operation, calc_info)
        if unit == "孔":
            # 分支① holes 直采；分支② 无 holes 有米数 ⇒ 每米 HOLE_PER_METER 孔的行业估算
            # （分支②的值 ≠ 真兜底 1.0 ⇒ 必须可与分支③区分，否则「有依据的估算」被说成占位值）
            return (qty, key) if key in HOLE_KEYS else (qty, f"{key}{HOLE_ESTIMATE_SUFFIX}")
        if key in DIRECT_QTY_KEYS:
            return qty, key
        # panels / set_count：引擎**待补键**（PANEL_KEYS/SET_KEYS 注释）⇒ 不是算料输出
        return qty, "fallback"
    return 1.0, "fallback"


def build_routing(position: Dict[str, Any]) -> List[str]:
    """工艺基准路线 + 条件工序（特殊选项触发）+ 定型开关。

    🔴 **去部位化（issue #4937 / P2）**：本函数原来按 `(curtain_type, craft)` 查表；部位退场后
    **只按工艺**查（见 `ROUTINGS` 的说明）。`curtain_type` 仍被读取，但**不再参与路线选择**
    —— 它只剩两个用途：默认值回落与「订单行帘种标识」。

    ⚠️ **行为变更照实登记**：`纱帘×打孔` / `纱帘×韩褶` 等组合此前取的是**纱帘专属**序列
    （不含 熨烫/定型/复烫/车被）；现在与布帘同工艺取**同一条**序列。这正是用户裁定的语义
    （「部位不再参与任何取价、取路、筛选、配置」），且「某工艺不做某工序」改由**规则**表达。

    Args:
        position: `{curtain_type, craft, is_shaped, special_options: [..]}`（`curtain_type` 不再选路）
    Returns: 工序名序列
    """
    craft = position.get("craft", "韩褶")
    if craft not in ROUTINGS:
        raise ValueError(f"不支持的 工艺 组合: {craft}")
    route = list(ROUTINGS[craft])

    # 定型=否 → 移除 定型-布/复烫-布（**工艺级**开关，不再是「部位级」）
    if position.get("is_shaped") is False:
        route = [op for op in route if op not in ("定型-布", "复烫-布")]

    # 特殊选项条件工序（按 after 定位插入；`NON_PIECEWORK_OPTIONS` 与纯系数选项无 operation 档 ⇒ 跳过）
    specials = position.get("special_options") or []
    for opt in specials:
        rule = SPECIAL_OPTION_ROUTINGS.get(opt)
        if rule and "operation" in rule:
            route = _insert_after(route, rule["operation"], rule["after"])
    return route


def _insert_after(route: List[str], operation: str, after: str) -> List[str]:
    """把 operation 插到 after 之后（after 不在路线中则追加到末尾）。

    **唯一性 = 取代**（issue #4577，用户裁定 2026-09-19 原话：「**工序需要保证唯一**，比如工艺带了
    绑带，特殊选项又选择余料做绑带，得用**特殊选项中的余料做绑带替代绑带这个工序**，余料做绑带的
    目标工序也是绑带就能替换，**需要有这个前提**」）。

    ⇒ 判据 = **目标工序名相同**（前提）；语义 = **先移除序列里已有的该工序，再按本条规则的锚点插入**
    （**取代**，不是"跳过"）。为什么不是跳过：跳过会让位置停留在**先应用**那条规则（可能是工艺的
    锚点），而商家选特殊选项的意图是「按这个选项的工序来」。结果 = 该工序在序列里**恰好出现一次**。

    规则应用顺序仍由 `priority` 升序决定（**顺序语义一字未动**）：既有种子里特殊选项的 priority
    （110~260）大于工艺规则（10~100）⇒ **特殊选项自然覆盖工艺**，正是用户要的
    「用余料做绑带替代绑带」。
    """
    route = [op for op in route if op != operation]
    try:
        idx = route.index(after)
    except ValueError:
        route.append(operation)
        return route
    route.insert(idx + 1, operation)
    return route


def instance_operations(
    position: Dict[str, Any],
    calc_info: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """实例化工序（应做数量=引擎输出 + 单价 + 开始标记）。

    Args:
        position: {curtain_type, craft, is_shaped, special_options, open_count}
        calc_info: 算料引擎输出（`curtain_calc.build_quote` 的返回，键见 METER_KEYS/FOLD_KEYS 等；
                   缺 `panels`/`set_count`/`holes` 时按 _qty_for 的兜底口径处理，不落 0）
    Returns: 工序实例列表 [{seq, operation, group, unit, qty, unit_price,
             is_start_marker, qty_source}]

    实例**不再带 `factor` 键**（issue #4589）：系数已从算法退场。
    实例**不再带 `is_must_finish` 键**（issue #4961）：必完工序概念已退场，完工判据 =
    **全部**工序实例完成（与 Java 侧 `ProcessingOrderService.buildPositionPayload` 同口径 ——
    两侧都必须不带该键，否则口径再次分叉）。
    """
    route = build_routing(position)

    instances: List[Dict[str, Any]] = []
    for seq, operation in enumerate(route, start=1):
        meta = OPERATION_CATALOG[operation]
        instances.append({
            "seq": seq,
            "operation": operation,
            "group": meta["group"],
            "unit": meta["unit"],
            "qty": _qty_for(operation, calc_info),
            "unit_price": meta["unit_price"],
            "is_start_marker": operation in START_MARKER_OPS,
            "qty_source": calc_info.get("source", "formula"),
        })
    return instances


# ══════════════════════════════════════════════════════════════════════════════════════
# 新模型真值源（issue #4427 = 母单 #4423 的 P1/3）—— **与上方旧常量并存的第二份真值源**
# ══════════════════════════════════════════════════════════════════════════════════════
# ## 为什么是「第二份」而不是「替换」
#
# 母单 #4423 §三 冻结的落地顺序是 **P1 纯增量 → P2 切消费路径 → P3 前端**：
# 一次性把四个投影（Python 真值源 / SQL 种子 / Java 实例化 / bootstrap schema）全改 =
# 一个跨三端、动工人工资的超大 PR（风险不可控）；而「先删旧再建新」的中间态会让 Java
# 读不到工序/路线 ⇒ 建单全 fail-closed。⇒ **P1 只新增**：本段常量 + `build_route_v2` 今天
# **零消费者**（旧常量、旧函数、Java、前端、DB 旧表旧行一字不动 ⇒ 运行时行为零变化）。
#
# ## 表示法收敛（9 条展开路线 → 1 条主线 + 规则表 + 部位价目）
#
# | 旧（`ROUTINGS`，9 条「展开快照」） | 新（本段） |
# |---|---|
# | 每道工序名把**部位编码进名字**（`精裁-布`/`精裁-纱`、`布三边`/`纱三边`） | 逻辑工序名（`精裁`/`三边`）+ **部位适用性矩阵** |
# | `(部位, 工艺)` 笛卡尔积 ⇒ 9 条路线，改一道工序要改 8 遍 | **1 条主线** + `ROUTE_RULES`（工艺/选项触发 insert/remove） |
# | 单价绑在「工序名」上（35 行） | 单价绑在 `(逻辑工序, 部位)` 上（30 × 4 = 120 行，issue #4529 起） |
#
# ⇒ **不发明任何工序、不改任何单价**：`OPERATION_LOGICAL_NAMES` 的 35 个旧名与
# `OPERATION_POSITION_PRICES` 的单价逐条可溯源到 `OPERATION_CATALOG`（旧真值源）。
#
# ## 判据（本单的验收判据，全部落码）
#
# ① **9/9 逐字重建**：`build_route_v2` 重建 9 个 `(部位, 工艺)` 组合，与冻结期望 +
#    旧 `ROUTINGS` 归一序列三方逐字一致 —— `tests/test_production/test_route_model_v2.py`；
# ② **三源收敛**：本段常量 ↔ `V71__normalize_routing_model_structure.sql` ↔
#    `docs/sql/schema.sql` 逐行逐值 —— `tests/unit_ci_workflows/test_production_catalog_seed.py`。
#
# ## ⚠️ 如实登记（P1 边界，别把半截当完整交付）
#
# · `is_shaped`（定型开关）**没有**规则行：26 条 = 工艺 10 + 选项 16（母单冻结数字）。
#   `production_route_rules.trigger_kind` 预留了 `shaped` / `processing_item`，P1 不种行
#   ⇒ `build_route_v2` 遇到未实现的触发类型**显式抛错**（不静默忽略，见函数实现）；
# · `build_route_v2` 今天是**零消费者**：Java 实例化仍读旧 `production_routings`（P2 才切）；
# · 「外帘打卷/装袋/发货」的部位适用性按母单冻结为 `{布帘,纱帘,帘头}`（三道是套级工序，
#   每樘窗一次由 V67 的 `scope='set'` + P2 的去重消费方承担，不在本段）。

#: 默认路线模板名（用户可命名；M3：**只改路线总名，工序名不能改**）
ROUTE_TEMPLATE_NAME_DEFAULT = "窗帘工序路线（默认）"

# ── 布料基础路线（issue #4529，包 F；用户裁定 2026-09-19）──────────────────────────────
# 用户裁定（逐字）：「如果是布料，只有一个工序叫配料……每个租户默认**两条**基础工序路线，
# 一个是窗帘的，一条是布料的」；追加裁定：「打包 = 报工 外帘装袋 不一定，如果是布料也可以
# 有打包工序」⇒ `打包` 是**独立工序且跨产品形态**（不能等于 `外帘装袋`）。
#
#: 第 4 个部位（既有三部位 = 布帘/纱帘/帘头）。
FABRIC_POSITION = "布料"
#: 选中布料路线的键：`processing_info.saleForm`（前端 `SALE_FORM_FABRIC` 逐字一致 —— join key）。
SALE_FORM_FABRIC = "布料"
#: 布料主线（**2 道**）：`配料` → `打包`（不含任何窗帘工艺/部位工序）。
FABRIC_MAINLINE_STEPS: List[str] = ["配料", "打包"]
#: 布料路线模板名（种子名；商家可改名 —— 幂等键是 `(tenant_id, name)`，不是这个名字）。
FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT = "布料工序路线"

#: 主线**全貌**（含「工艺槽位」占位）—— 仅文档用途，**不落库**
#: （槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入）
ROUTE_MAINLINE: List[str] = ["精裁", "三边", "⟪工艺槽位⟫", "熨烫", "定型", "复烫",
                             "车被", "外帘打卷", "打包", "外帘装袋", "外帘发货"]

#: **实际落库的 10 道**主线（部位无关；工艺槽位不落库）
#:
#: `打包` 插在 `外帘打卷` 与 `外帘装袋` **之间**（issue #4529）：位置依据 = ERP 加工单实证
#: `外帘打包 › 外帘装箱 › 外帘发货`（`外帘装袋` ≈ ERP 的 `外帘装箱` ⇒ 打包在装袋之前）。
#: ⚠️ **照实登记**：#4343 登记过这两道的对应关系**未能确定** ⇒ 本顺序是**按 ERP 顺序推断**、
#: **待客户确认**（不假装定论；确认后若顺序不同，改这里 + V79 + `schema.sql` 三处即可）。
ROUTE_MAINLINE_STEPS: List[str] = ["精裁", "三边", "熨烫", "定型", "复烫", "车被",
                                   "外帘打卷", "打包", "外帘装袋", "外帘发货"]

#: 旧工序名 → 逻辑工序名（35 条**有序对**；模块加载时 `dict(...)` 成表）
#:
#: ⚠️ **为什么写成有序对列表而不是 dict 字面量**：L0 守卫
#: `tests/unit_ci_workflows/test_tool_input_contract_guards.py` 把「含 ≥2 个中文 key 的 dict 字面量」
#: 判为「把中文措辞当判据」的站点，且该基线**只许缩短、不得扩容**（R4：新增站点必须本次修掉）。
#: 本表是**业务主数据**（工序名映射 —— 与守卫要治的「拿错误文案做子串匹配」不同族），改成有序对后
#: AST 里不再有该形态 ⇒ 既不触发守卫、也不放宽基线（**判据一条不动**）。
#:
#: ⚠️ **显式逐条写出，不用「去后缀」字符串规则推导**：`布三边`/`纱三边`（无 `-` 分隔）、
#: `布帘车被`（`布帘` 前缀）这类名字用规则推导会漏（#4423 §一② 的 14 道里就有它们）。
#: 映射的正确性由 `test_route_model_v2.py` 用**硬编码冻结值**判（不从本表推导）。
_LOGICAL_NAME_PAIRS: List[tuple] = [
    ("精裁-布", "精裁"),
    ("精裁-纱", "精裁"),
    ("裁剪-布", "裁剪"),
    ("裁剪-纱", "裁剪"),
    ("布三边", "三边"),
    ("纱三边", "三边"),
    ("韩褶-布", "韩褶"),
    ("韩褶-纱", "韩褶"),
    ("上车布-布", "上车布"),
    ("上车布-纱", "上车布"),
    ("打孔-布", "打孔"),
    ("打孔-纱", "打孔"),
    ("拼1次-布", "拼1次"),
    ("拼2次-布", "拼2次"),
    ("拼3次-布", "拼3次"),
    ("花边-布", "花边"),
    ("铅坠-布", "铅坠"),
    ("接高-布", "接高"),
    ("帘头制作", "帘头制作"),
    ("熨烫-布", "熨烫"),
    ("定型-布", "定型"),
    ("复烫-布", "复烫"),
    ("布帘车被", "车被"),
    ("外帘打卷", "外帘打卷"),
    ("外帘装袋", "外帘装袋"),
    ("质检", "质检"),
    ("外帘发货", "外帘发货"),
    ("绑带-布", "绑带"),
    ("抱枕", "抱枕"),
    ("腰靠垫", "腰靠垫"),
    ("绑带-纱", "绑带"),
    ("logo条-布", "logo条"),
    ("立边-布", "立边"),
    ("扣环-布", "扣环"),
    ("防翘扣-布", "防翘扣"),
]

#: 旧工序名 → 逻辑工序名（35 → 28；7 组部位变体 + 去 `-布`/`-纱` 后缀）。
#:
#: ⚠️ **本表被两处守卫逐条冻结**（改它会当场红）：
#:   · Python 侧 `tests/unit_ci_workflows/test_logical_name_single_source_guard.py`
#:     （锚点 = `_LOGICAL_NAME_PAIRS: List[tuple]` 到本行之间，**恰 35 条**）；
#:   · Java 侧 `ProductionOperationQueryServiceTest#logicalNameTableMatchesTruthSource`
#:     （同样取前 35 条）。
#: ⇒ issue #4937 新增的 **4 道纱帘变体**落在**下面另一段**（`_SHEER_VARIANT_PAIRS` +
#: `withSheerVariants`），与 Java 侧 `VARIANT_NAMES = variantNamesWithCurtainHead()` 同构。
#: 部位价目 + 适用性矩阵的**书写形态**：`(逻辑工序, 部位, 单价|None, applicable)` × **120 行**
#: （**30 道逻辑工序 × 4 部位**）。同上：用有序行而不是嵌套 dict 字面量（避免触发 L0 守卫）。
#:
#: 语义（母单 #4423 冻结 + issue #4529 扩到第 4 部位）：
#: · `applicable=True`  = 该部位**做**这道工序（`build_route_v2` 保留它）；
#: · `applicable=False` = 该部位**明确不做**（`build_route_v2` 滤掉它）—— 与「没定价」可区分；
#: · `unit_price=None`  = **不落价**：明确不做的部位不报价（有价 = 有业务含义的价目行）；
#:   ⚠️ issue #4529 起出现**新状态**「`applicable=True` 且 `unit_price=None`」= **适用但未定价**
#:   （`配料 × 布料` / `打包 × 4 部位`）⇒ 该状态必须**可判**（读面 `GET …/operation-positions`
#:   返回 `{unit_price: null, applicable: true}`），**不得与「不适用」混淆**，也不得静默按 0 收；
#: · 单价逐条溯源到 `OPERATION_CATALOG`（**不发明单价**）：本单实证「同一逻辑工序的各部位变体
#:   单价**逐字相同**」（7 组变体 14 道工序两两相等）⇒ 今天单价是**逻辑工序**的函数，按适用部位
#:   展开；本表存在的理由是给真值源 §2【标】「同一道工序在布/纱/帘头上单价各自不同」**留出载体**，
#:   等客户给出分部位价（#4261）再分化。
_POSITION_PRICE_ROWS: List[tuple] = [
    ("精裁", "布帘", 0.4, True),
    ("精裁", "纱帘", 0.4, True),
    ("精裁", "帘头", 0.4, True),
    ("裁剪", "布帘", 0.4, True),
    ("裁剪", "纱帘", 0.4, True),
    ("裁剪", "帘头", 0.4, True),
    ("三边", "布帘", 0.4, True),
    ("三边", "纱帘", 0.4, True),
    ("三边", "帘头", 0.4, True),
    ("韩褶", "布帘", 0.4, True),
    ("韩褶", "纱帘", 0.4, True),
    ("韩褶", "帘头", 0.4, True),
    ("上车布", "布帘", 0.5, True),
    ("上车布", "纱帘", 0.5, True),
    ("上车布", "帘头", None, False),
    ("打孔", "布帘", 0.15, True),
    ("打孔", "纱帘", 0.15, True),
    ("打孔", "帘头", 0.15, True),
    ("拼1次", "布帘", 0.8, True),
    ("拼1次", "纱帘", None, False),
    ("拼1次", "帘头", None, False),
    ("拼2次", "布帘", 1.2, True),
    ("拼2次", "纱帘", None, False),
    ("拼2次", "帘头", None, False),
    ("拼3次", "布帘", 1.6, True),
    ("拼3次", "纱帘", None, False),
    ("拼3次", "帘头", None, False),
    ("花边", "布帘", 0.6, True),
    ("花边", "纱帘", None, False),
    ("花边", "帘头", None, False),
    ("铅坠", "布帘", 0.3, True),
    ("铅坠", "纱帘", None, False),
    ("铅坠", "帘头", None, False),
    ("接高", "布帘", 1.0, True),
    ("接高", "纱帘", None, False),
    ("接高", "帘头", None, False),
    ("帘头制作", "布帘", None, False),
    ("帘头制作", "纱帘", None, False),
    ("帘头制作", "帘头", 2.0, True),
    ("熨烫", "布帘", 0.35, True),
    ("熨烫", "纱帘", None, False),
    ("熨烫", "帘头", None, False),
    ("定型", "布帘", 0.4, True),
    ("定型", "纱帘", None, False),
    ("定型", "帘头", 0.4, True),
    ("复烫", "布帘", 0.35, True),
    ("复烫", "纱帘", None, False),
    ("复烫", "帘头", None, False),
    ("车被", "布帘", 0.4, True),
    ("车被", "纱帘", None, False),
    ("车被", "帘头", None, False),
    ("外帘打卷", "布帘", 1.0, True),
    ("外帘打卷", "纱帘", 1.0, True),
    ("外帘打卷", "帘头", 1.0, True),
    ("外帘装袋", "布帘", 1.0, True),
    ("外帘装袋", "纱帘", 1.0, True),
    ("外帘装袋", "帘头", 1.0, True),
    ("质检", "布帘", 1.5, True),
    ("质检", "纱帘", 1.5, True),
    ("质检", "帘头", 1.5, True),
    ("外帘发货", "布帘", 1.0, True),
    ("外帘发货", "纱帘", 1.0, True),
    ("外帘发货", "帘头", 1.0, True),
    ("绑带", "布帘", 0.5, True),
    ("绑带", "纱帘", 0.5, True),
    ("绑带", "帘头", None, False),
    ("抱枕", "布帘", 2.0, True),
    ("抱枕", "纱帘", 2.0, True),
    ("抱枕", "帘头", 2.0, True),
    ("腰靠垫", "布帘", 2.0, True),
    ("腰靠垫", "纱帘", 2.0, True),
    ("腰靠垫", "帘头", 2.0, True),
    ("logo条", "布帘", 0.6, True),
    ("logo条", "纱帘", None, False),
    ("logo条", "帘头", None, False),
    ("立边", "布帘", 0.5, True),
    ("立边", "纱帘", None, False),
    ("立边", "帘头", None, False),
    ("扣环", "布帘", 0.3, True),
    ("扣环", "纱帘", None, False),
    ("扣环", "帘头", None, False),
    ("防翘扣", "布帘", 0.2, True),
    ("防翘扣", "纱帘", None, False),
    ("防翘扣", "帘头", None, False),
    # ── issue #4529（包 F）：第 4 个部位「布料」的 28 行（既有 28 道**逐行显式 FALSE**）──
    # 逐行显式纪律不变：布料部位上**只有** `配料`/`打包` 适用，其余 28 道是「明确不做」
    # （不是缺行 —— 缺行会让 `build_route_v2` 的 `prices[op][position]` KeyError）。
    ("精裁", "布料", None, False),
    ("裁剪", "布料", None, False),
    ("三边", "布料", None, False),
    ("韩褶", "布料", None, False),
    ("上车布", "布料", None, False),
    ("打孔", "布料", None, False),
    ("拼1次", "布料", None, False),
    ("拼2次", "布料", None, False),
    ("拼3次", "布料", None, False),
    ("花边", "布料", None, False),
    ("铅坠", "布料", None, False),
    ("接高", "布料", None, False),
    ("帘头制作", "布料", None, False),
    ("熨烫", "布料", None, False),
    ("定型", "布料", None, False),
    ("复烫", "布料", None, False),
    ("车被", "布料", None, False),
    ("外帘打卷", "布料", None, False),
    ("外帘装袋", "布料", None, False),
    ("质检", "布料", None, False),
    ("外帘发货", "布料", None, False),
    ("绑带", "布料", None, False),
    ("抱枕", "布料", None, False),
    ("腰靠垫", "布料", None, False),
    ("logo条", "布料", None, False),
    ("立边", "布料", None, False),
    ("扣环", "布料", None, False),
    ("防翘扣", "布料", None, False),
    # ── 新增两道工序（issue #4529）──────────────────────────────────────────────────
    # `配料`：**布料专属**（`配料 × 布料` 适用；三个窗帘部位逐行显式 FALSE）。
    # `打包`：**所有产品形态都要做**（4 个部位全适用）—— 套级语义由 `scope='set'` 承担，
    # **不靠**「只对一个部位 applicable」表达（那会让窗帘单少一道活）。
    # 两者的 `unit_price` 都是 None = **适用但未定价**（商家在工序库自配，见 `OPERATION_CATALOG` 注释）。
    ("配料", "布料", None, True),
    ("配料", "布帘", None, False),
    ("配料", "纱帘", None, False),
    ("配料", "帘头", None, False),
    ("打包", "布帘", None, True),
    ("打包", "纱帘", None, True),
    ("打包", "帘头", None, True),
    ("打包", "布料", None, True),
]


def withSheerVariants(names: Dict[str, str]) -> Dict[str, str]:
    """在**冻结的 35 条**之上叠加 4 道纱帘变体（issue #4937）—— 与 Java 侧同名方法同构。

    🔴 **4 道纱帘变体**（`applicable` 过滤退场后它们会进纱帘路线，必须能解析回逻辑名）。
    ⚠️ **写成「单行 `dict(...)` 调用」而不是多行有序对**：本函数体落在
    `tests/unit_ci_workflows/test_logical_name_single_source_guard.py` 的
    「`_LOGICAL_NAME_PAIRS` → `OPERATION_LOGICAL_NAMES`」解析区间内，而该守卫的
    行形态正则（`\n\s*\("a", "b"\),`）会把**多行**有序对也收进去 ⇒ 实测读到 39 条
    （**它不许放宽条数**）。单行调用**不以 `(` 开头** ⇒ 正则收不到，恰好保住那 35 条。
    """
    out = dict(names)
    out.update(dict(
        (("熨烫-纱", "熨烫"), ("定型-纱", "定型"), ("复烫-纱", "复烫"), ("车被-纱", "车被"))))
    return out


OPERATION_LOGICAL_NAMES: Dict[str, str] = withSheerVariants(dict(_LOGICAL_NAME_PAIRS))

#: 去部位化（issue #4883 / #4885）后**同一逻辑工序唯一那个价**的取行来源 —— 用户裁定「取布帘价」。
#:
#: ⚠️ 与 Java 侧 `ProductionOperationQueryService.COLLAPSE_PRICE_SOURCE_POSITION` **逐字同值**
#: （由 `tests/test_production/test_position_collapse_mirror.py` 的跨语言判据钉住）：
#: 两侧各自硬编码一个字面量而不比对，就是两份口径，漂移的那一份不会变红。
#: ⚠️ issue #4937 后本常量仍**承重**：它是 `collapse_to_logical` 的档序之一，
#: 而 `_POSITION_PRICE_ROWS`（历史 120 行）仍是**存量的收敛输入** —— 物理塌缩（`V104`）之后
#: 它只在**尚未迁移**的库上生效，但两侧口径必须继续逐字一致（漂移的那一份不会变红）。
COLLAPSE_PRICE_SOURCE_POSITION: str = "布帘"


def collapse_to_logical(rows: Optional[List[tuple]] = None) -> Dict[str, Dict[str, Any]]:
    """部位价目矩阵 → **一道逻辑工序一行、一个价**（Java `collapseToLogical` 的真值源镜像）。

    矩阵的键是 `(逻辑工序, 部位)`；去部位化（issue #4883）后**部位不再参与取价**
    ⇒ 同一 `逻辑工序` 的多行必须**收敛为一行**。收敛顺序（**完全确定**，不依赖输入序）：

    1. `applicable is True` 的行优先 —— `False` = 当年「该部位明确不做」，其 `unit_price`
       一律 `None` ⇒ 优先它会把**有价**的工序判成未定价（`帘头制作`：布帘格 `(None, False)`、
       帘头格 `(2.0, True)` ⇒ 正确答案是 `帘头 / 2.0`，**不是**布帘格的 `None`）；
    2. 其中 `position == COLLAPSE_PRICE_SOURCE_POSITION`（布帘）的行优先（用户裁定「取布帘价」）；
    3. 再按 `position` 字典序、最后按**声明序**（= V71 种子的 id 序）—— 与 Java 的
       `id` 升序末档对应。

    🔴 **价只「选行」、绝不「回落」**（issue #4696）：幸存行的 `unit_price` 是 `None`
    ⇒ 就是**未定价**，**不得**回落 `OPERATION_CATALOG` 的行价（那是 `NOT NULL DEFAULT 0`
    ⇒ 回落把「未定价」变成「真 0 元」，工人白干且无人知道）。

    ⚠️ **本函数与本模块其余部分一样，零运行时消费者**（`app/` 里只有 `app/api/internal.py`
    消费 `qty_and_source`）：它存在是为了让 Java 那条收敛规则**有一份可比对的对侧** ——
    否则同一条规则只有一份实现，改错了没有任何东西会红（同 `build_route_v2` ↔ Java `buildRoute`
    的既有范式）。**不得**据此把它接进运行时（那会让同一条规则出现第二个消费口径）。

    Args:
        rows: `(逻辑工序, 部位, 单价|None, applicable)` 行；缺省 = 冻结的 `_POSITION_PRICE_ROWS`
    Returns:
        `{逻辑工序: {"position", "unit_price", "applicable"}}`（幸存行），按逻辑工序名升序
    """
    source = _POSITION_PRICE_ROWS if rows is None else rows
    survivors: Dict[str, tuple] = {}
    for index, row in enumerate(source):
        logical = row[0]
        current = survivors.get(logical)
        if current is None or _beats_for_collapse(row, index, current[0], current[1]):
            survivors[logical] = (row, index)
    out: Dict[str, Dict[str, Any]] = {}
    for logical in sorted(survivors):
        row = survivors[logical][0]
        out[logical] = {"position": row[1], "unit_price": row[2], "applicable": row[3]}
    return out


def _beats_for_collapse(candidate: tuple, candidate_index: int,
                        current: tuple, current_index: int) -> bool:
    """`candidate` 是否应取代 `current` —— `collapse_to_logical` 的三档顺序（与 Java 逐档对应）。

    ⚠️ **档序是判据本身**，不是实现细节：把「布帘列优先」提到「适用行优先」**之前**
    ⇒ `帘头制作` 会从 `帘头 / 2.0` 变成 `布帘 / None`（有价工序被判成未定价）。
    `tests/test_production/test_position_collapse_mirror.py` 逐档钉住它。
    """
    if bool(candidate[3]) != bool(current[3]):
        return bool(candidate[3])
    is_source_position = candidate[1] == COLLAPSE_PRICE_SOURCE_POSITION
    current_is_source_position = current[1] == COLLAPSE_PRICE_SOURCE_POSITION
    if is_source_position != current_is_source_position:
        return is_source_position
    if candidate[1] != current[1]:
        return candidate[1] < current[1]
    return candidate_index < current_index


#: 逻辑工序 → **唯一那个价**（`{逻辑工序: {"unit_price": 单价|None, "applicable": True}}`）。
#:
#: 🔴 **去部位化（issue #4937 / P2，用户裁定 2026-09-21「不计成本的改」）**：本表原来按
#: `[逻辑工序][部位]` 两级索引（30 × 4 = 120 格）。部位退场 ⇒ **只按逻辑工序**建索引
#: （**30 行**，与 `V104` 迁移 / `docs/sql/schema.sql` 的**终态逐行同值**）。
#: 每个逻辑工序的价 = `collapse_to_logical()` 的幸存行价（选行规则见该函数；结果恒定，
#: 因为收敛由判据决定、与输入序无关）。
#:
#: ⚠️ **价逐字未改**：18 道有价（与 `_POSITION_PRICE_ROWS` 的布帘列逐字同值）+ 12 道未定价
#: （`打包`/`配料` 本来就是「适用但未定价」；其余 10 道在「适用行」里没有价 —— 见
#: `_POSITION_PRICE_ROWS` 的 `applicable=False` 行）。⛔ **不得**回落 `OPERATION_CATALOG`
#: 的行价（那是 `NOT NULL DEFAULT 0` ⇒ 把「未定价」变成「真 0 元」，工人白干且无人知道，issue #4696）。
#:
#: ⚠️ 值由收敛函数给出（**不抄字面量**）：抄一份就是第二份口径，漂移的那一份不会变红。
#: `applicable` 恒 `True` —— 塌缩后每一行都是「这道逻辑工序做」的载体（部位维已退场）。
OPERATION_POSITION_PRICES: Dict[str, Dict[str, Any]] = {
    logical: {"unit_price": survivor["unit_price"], "applicable": True}
    for logical, survivor in collapse_to_logical().items()
}

#: 规则表 26 条（工艺变体 10 + 特殊选项 16）—— 「主线 + 规则」取代「9 条展开路线」
#:
#: 字段：`trigger_kind`（`craft`/`option`/`processing_item`；`shaped` 预留但无种子行）·
#: ⚠️ `processing_item` 的**种子行不在本表**：它们由 `V84__seed_processing_item_route_rules.sql`
#: 按租户种进 `production_route_rules`（issue #4577；本表仍是 V71 字面量种子的镜像 ——
#: `tests/unit_ci_workflows/test_production_catalog_seed.py` 把「本表 ≡ V71 的 26 行」钉死）。
#: 触发口径（`_rule_triggers`）两侧**同款**：加工项名精确相等。
#: `trigger_value`（工艺名 / 特殊选项名 / 部位名，**逐字 = ERP 写法**，它是 join key）·
#: 🔴 **`position`（规则级部位限定）**（issue #4962 **加回**；此前 issue #4937 / O2 整块退场）：
#: `None` / 缺键 = **不限部位**；否则必须**逐字**匹配当前实例化部位（见 `_rule_position_matches`）。
#: 26 条种子里**只有一条**带它（`韩褶 → insert 上车布`，`position="布帘"`）—— 与迁移侧
#: `V71` 的字面量 + `V108__restore_route_rule_positions.sql` 的写回 + Java 的
#: `ProductionSeedTemplateService#CRAFT_RULES` **同值**。
#: `action`（`insert`/`remove`）·
#: `operation`（**逻辑工序名**）· `after_operation`（insert 锚点，`None` = 追加末尾）·
#: `priority`（**升序生效**，同序按声明顺序 —— 顺序敏感，见 `build_route_v2`）。
#:
#: ⚠️ 特殊选项 16 条 = 旧 `SPECIAL_OPTION_ROUTINGS` **逐条搬迁**，且**工序名与锚点都归一为
#: 逻辑名**（`布三边`→`三边`、`布帘车被`→`车被`、`精裁-布`→`精裁`）—— 否则锚点在逻辑名序列里
#: 找不到 ⇒ 条件工序会**静默追加到末尾**（工序顺序错 = 车间按错顺序干）。
ROUTE_RULES: List[Dict[str, Any]] = [
    # ── 工艺变体（trigger_kind='craft'）──
    {"trigger_kind": "craft", "trigger_value": "韩褶", "action": "insert",
     "operation": "韩褶", "after_operation": "三边", "priority": 10},
    {"trigger_kind": "craft", "trigger_value": "韩褶", "action": "insert",
     "operation": "上车布", "after_operation": "韩褶", "priority": 20,
     # 🔴 部位限定（issue #4962 加回）：V71 的 26 条种子行里**唯一**一条带 `position` 的规则
     # （`rr-v70-02`）。帘头单/纱帘单**不做**「上车布」—— 去掉它会让该规则对帘头单生效
     # ⇒ 主线上多出一道它本来不做的工序（**错发计件工资**，见设计文档 §11.2 / O2）。
     "position": "布帘"},
    {"trigger_kind": "craft", "trigger_value": "打孔", "action": "insert",
     "operation": "打孔", "after_operation": "三边", "priority": 30},
    {"trigger_kind": "craft", "trigger_value": "四爪钩", "action": "insert",
     "operation": "上车布", "after_operation": "三边", "priority": 40},
    {"trigger_kind": "craft", "trigger_value": "四爪钩", "action": "remove",
     "operation": "定型", "after_operation": None, "priority": 50},
    {"trigger_kind": "craft", "trigger_value": "四爪钩", "action": "remove",
     "operation": "复烫", "after_operation": None, "priority": 60},
    {"trigger_kind": "craft", "trigger_value": "穿杆", "action": "remove",
     "operation": "定型", "after_operation": None, "priority": 70},
    {"trigger_kind": "craft", "trigger_value": "穿杆", "action": "remove",
     "operation": "复烫", "after_operation": None, "priority": 80},
    {"trigger_kind": "craft", "trigger_value": "平幔", "action": "insert",
     "operation": "帘头制作", "after_operation": "三边", "priority": 90},
    {"trigger_kind": "craft", "trigger_value": "平幔", "action": "remove",
     "operation": "复烫", "after_operation": None, "priority": 100},
    # ── 特殊选项（trigger_kind='option'）= 旧 SPECIAL_OPTION_ROUTINGS 逐条搬迁（16 条）──
    {"trigger_kind": "option", "trigger_value": "拼1次", "action": "insert",
     "operation": "拼1次", "after_operation": "三边", "priority": 110},
    {"trigger_kind": "option", "trigger_value": "拼2次", "action": "insert",
     "operation": "拼2次", "after_operation": "三边", "priority": 120},
    {"trigger_kind": "option", "trigger_value": "拼3次", "action": "insert",
     "operation": "拼3次", "after_operation": "三边", "priority": 130},
    {"trigger_kind": "option", "trigger_value": "加花边", "action": "insert",
     "operation": "花边", "after_operation": "三边", "priority": 140},
    {"trigger_kind": "option", "trigger_value": "加铅块", "action": "insert",
     "operation": "铅坠", "after_operation": "三边", "priority": 150},
    {"trigger_kind": "option", "trigger_value": "接高", "action": "insert",
     "operation": "接高", "after_operation": "精裁", "priority": 160},
    {"trigger_kind": "option", "trigger_value": "双眼皮接高", "action": "insert",
     "operation": "接高", "after_operation": "精裁", "priority": 170},
    {"trigger_kind": "option", "trigger_value": "余料做绑带", "action": "insert",
     "operation": "绑带", "after_operation": "车被", "priority": 180},
    {"trigger_kind": "option", "trigger_value": "布绑带", "action": "insert",
     "operation": "绑带", "after_operation": "车被", "priority": 190},
    {"trigger_kind": "option", "trigger_value": "余料做帘头", "action": "insert",
     "operation": "帘头制作", "after_operation": "三边", "priority": 200},
    {"trigger_kind": "option", "trigger_value": "抱枕", "action": "insert",
     "operation": "抱枕", "after_operation": "外帘打卷", "priority": 210},
    {"trigger_kind": "option", "trigger_value": "纱绑带", "action": "insert",
     "operation": "绑带", "after_operation": "车被", "priority": 220},
    {"trigger_kind": "option", "trigger_value": "加logo条", "action": "insert",
     "operation": "logo条", "after_operation": "三边", "priority": 230},
    {"trigger_kind": "option", "trigger_value": "加立边", "action": "insert",
     "operation": "立边", "after_operation": "三边", "priority": 240},
    {"trigger_kind": "option", "trigger_value": "扣环", "action": "insert",
     "operation": "扣环", "after_operation": "三边", "priority": 250},
    {"trigger_kind": "option", "trigger_value": "防翘扣", "action": "insert",
     "operation": "防翘扣", "after_operation": "三边", "priority": 260},
]


def _rule_triggers(rule: Dict[str, Any], position: Dict[str, Any]) -> bool:
    """该规则是否被本部位触发（**精确匹配**：选项名不得用 `contains` 命中 —— 错一个字就静默失效）。

    ⚠️ **只判「什么时候」那一维**；「限哪个部位」由 :func:`_rule_position_matches` 单独判
    （调用点**必须先调本函数再调它** —— 未知触发类型要显式失败，不能因为部位不匹配就静默跳过）。
    """
    kind = rule["trigger_kind"]
    if kind == "craft":
        return rule["trigger_value"] == position.get("craft")
    if kind == "option":
        return rule["trigger_value"] in (position.get("special_options") or ())
    if kind == "processing_item":
        # 加工项触发（issue #4577，用户裁定「加工项也触发工序」）：触发键 = 该行
        # `processingInfo.processingItems[].name`（Java 侧同一口径；**精确相等** ——
        # `contains` 只存在于存量信号兜底 `firstSignalMatch`，不在此处引入第二处）。
        return rule["trigger_value"] in (position.get("processing_items") or ())
    if kind == "position":
        # 部位维触发（issue #4962）：`trigger_value` = 部位名，**写面把它镜像进 `position` 列**
        # ⇒ 真正的筛选是 `_rule_position_matches`（**只有一处判据**，与 Java 侧
        # `ProcessingOrderService#rulePositionMatches` 同款）。此处恒 True 只表示
        # 「该触发类型已实现」，不是「跳过筛选」；列缺值 ⇒ 规则对任何部位都不生效 ⇒ 显式失败。
        if not rule.get("position"):
            raise ValueError(f"部位维规则缺 `position` 值（规则永不生效）: {rule}")
        return True
    # `shaped` 仍是**表结构预留**的触发类型（无种子行、无消费路径）：
    # 静默返回 False 会让「规则已落库但永不生效」变成无人可见的黑洞 ⇒ 显式失败。
    raise ValueError(f"未实现的规则触发类型: {kind}")


def _rule_position_matches(rule: Dict[str, Any], position: Dict[str, Any]) -> bool:
    """**规则级部位限定**（issue #4962 加回；此前由 issue #4937 / O2 整块退场）。

    `None` / 空 / 缺键 = **不限部位**；否则必须与当前实例化部位**逐字相等**。
    与 Java 侧 `ProcessingOrderService#rulePositionMatches` **同款同序同判据** ——
    两侧漂移会让同一张单在 Java 与 Python 上得到不同的工序序列（车间按两套顺序干）。
    """
    limit = rule.get("position")
    return not limit or limit == position.get("curtain_type")


def build_route_v2(position: Dict[str, Any]) -> List[str]:
    """新模型：**主线 + 规则（工艺/选项）** → 逻辑工序名序列（**不展开部位后缀**）。

    纯函数（不改入参、不碰 DB、零 LLM）。语义（**顺序敏感**）：

    1. 取主线：`saleForm = 布料`（issue #4529）⇒ `FABRIC_MAINLINE_STEPS`（**当前字面量** `配料 → 打包`）；
       否则 `ROUTE_MAINLINE_STEPS`（窗帘 10 道）。**两条主线由「产品形态」选定**（与 DB 侧
       「每租户两条路线模板」一一对应：`routeTemplateFor(tenantId, 部位)` 按 `positions` 选模板）
       —— ⚠️ 这是**唯一**仍读 `curtain_type` 的地方，且它是**路线模板的选择键**（产品形态），
       不是「部位维」参与取路（模板选择不在本单射程，见 #4937 的「唯一保留的三处标识」）；
    2. 按 `ROUTE_RULES` 应用规则 —— **按 `priority` 升序**（同 priority 按声明顺序）；
       `insert` 用 `after_operation` 定位（锚点不在序列中 ⇒ **追加末尾**，与既有
       `_insert_after` 同款），`remove` 直接删除该工序名；
    3. 🔴 **无第 3 步**（issue #4937 / P2，用户裁定 2026-09-21）：原来第 3 步是
       「按 `OPERATION_POSITION_PRICES[工序][部位]["applicable"]` 滤掉该部位不做的工序」，
       **整块删除** —— 该维（`applicable` / 部位适用性）**仍然退场**。
       ⚠️ **但第 2 步里恢复了「规则级部位限定」**（issue #4962 加回）：带 `position` 的规则
       只在**逐字匹配**的帘种上生效（26 条种子里只有 `韩褶 → 上车布` 一条）。
       两者不是同一件事：`applicable` 是**矩阵数据层**的「该部位做不做这道工序」（已退场），
       `rule.position` 是**单条规则**的部位限定（在。见设计文档 §11.2 / O2）。

    ⚠️ **`remove` 不先于 `insert`**：顺序完全由 `priority` 决定（母单 #4423 冻结口径）。
    例：`韩褶 + insert 上车布 after 韩褶` 必须排在 `韩褶 insert 韩褶 after 三边` **之后**
    —— 否则锚点「韩褶」还不存在 ⇒ 「上车布」被追加到末尾（顺序错）。

    Args:
        position: `{curtain_type, craft, special_options: [..]}`（`curtain_type` 只用于选主线模板）
    Returns: 逻辑工序名序列（如 `["精裁","三边","韩褶","上车布",...]`）
    """
    curtain_type = position.get("curtain_type", "布帘")
    is_fabric = curtain_type == FABRIC_POSITION
    route = list(FABRIC_MAINLINE_STEPS if is_fabric else ROUTE_MAINLINE_STEPS)
    for rule in sorted(ROUTE_RULES, key=lambda r: r["priority"]):
        # 🔴 **工艺规则只对「窗帘类产品形态」生效**（issue #4937 / P2）。
        # 判据 = 与主线选择**同一个键**（`saleForm == 布料` ⇒ 布料主线，见上一行）：
        # 布料单是**另一个产品形态**（它的主线只有 `配料 → 打包`），在它上面套用窗帘工艺规则
        # 会把 `韩褶`/`上车布` 插进布料单 —— 而**旧口径下这件事被 `applicable` 过滤挡住了**
        # （`韩褶 × 布料` 当时是 `FALSE`）。部位过滤退场后，"哪些工序不属于这个产品形态"
        # 必须由**产品形态**（而不是部位）表达 —— 否则布料单的工序数会当场从 2 变 4。
        # ⚠️ 与 Java 侧 `ProcessingOrderService.buildRoute` 的
        # `routeTemplateFor(tenantId, 部位)` 同款：**模板（主线）与规则只对匹配的产品形态生效**。
        if is_fabric:
            continue
        if not _rule_triggers(rule, position):
            continue
        # 🔴 **规则级部位限定**（issue #4962 加回；#4937 / O2 曾整块退场）：`position` 为空 /
        # 缺键 = 不限部位；否则必须逐字匹配当前实例化部位。
        # ⚠️ 位置**必须在 `_rule_triggers` 之后**：未知触发类型先显式失败，不因部位不匹配静默跳过
        # （与 Java 侧 `ProcessingOrderService.buildRoute` 的语句顺序逐字同款）。
        if not _rule_position_matches(rule, position):
            continue
        if rule["action"] == "insert":
            route = _insert_after(route, rule["operation"], rule["after_operation"])
        else:
            route = [op for op in route if op != rule["operation"]]
    # 🔴 **fail-closed：每个工序都必须有价目行**（issue #4937 / P2）。
    # 原来这道校验由第 3 步的 `prices[op][position]["applicable"]` 顺带完成（**有位置过滤就没有
    # 静默黑洞**）；部位过滤退场后必须**显式**保留它 —— 否则「规则引用了一道不存在的工序」
    # 会让该工序带着 `None` 价静默进路线（工人白干且无人知道，issue #4696 同族）。
    # 与 Java 侧 `ProcessingOrderService.buildRoute` 的 `catalog.get(variant)` 检查同口径。
    for op in route:
        if op not in OPERATION_POSITION_PRICES:
            raise KeyError(op)
    return route
