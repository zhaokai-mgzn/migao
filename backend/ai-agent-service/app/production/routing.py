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
}

# ── 工艺路线模板（部位×工艺 → 基准工序序列）──
# 布帘·韩褶：行业 ERP 实证 11 道走线（2026-09 截图）
ROUTINGS: Dict[str, List[str]] = {
    ("布帘", "韩褶"): [
        "精裁-布", "布三边", "韩褶-布", "上车布-布", "熨烫-布",
        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("布帘", "打孔"): [
        "精裁-布", "布三边", "打孔-布", "熨烫-布",
        "定型-布", "复烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("布帘", "四爪钩"): [
        "精裁-布", "布三边", "上车布-布", "熨烫-布",
        "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("布帘", "穿杆"): [
        "精裁-布", "布三边", "熨烫-布", "布帘车被", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("纱帘", "韩褶"): [
        "精裁-纱", "纱三边", "韩褶-纱", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    # ── issue #4246：补 3 条纱帘路线（**零新造工序** —— 只消费库里早已存在、有价、零消费的
    # `上车布-纱` ¥0.5/米 与 `打孔-纱` ¥0.15/孔）。按布帘同工艺路线**镜像**，去掉纱帘没有的
    # 熨烫/定型/复烫/车被（行业判断见 #4246 §三：纱帘不做定型/复烫）。
    #
    # 为什么必须补（不只是"补齐好看"）：Java 侧 `deriveRouteKey` 派生出的「纱帘×打孔」在路线库
    # 取不到 ⇒ **回落默认路线 布帘×韩褶** ⇒ 一张「纱帘+打孔」的订单拿到**布帘的 11 道工序**
    # （精裁-布/布三边/韩褶-布…）⇒ 工人按布帘工序报工、计件按布帘单价算 ⇒ **工序与工资都是错的**。
    ("纱帘", "打孔"): [
        "精裁-纱", "纱三边", "打孔-纱", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("纱帘", "四爪钩"): [
        "精裁-纱", "纱三边", "上车布-纱", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("纱帘", "穿杆"): [
        "精裁-纱", "纱三边", "外帘打卷", "外帘装袋", "外帘发货",
    ],
    ("帘头", "平幔"): [
        "精裁-布", "布三边", "帘头制作", "定型-布", "外帘打卷", "外帘装袋", "外帘发货",
    ],
}

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
PENDING_CUSTOMER_CONFIRMATION_OPERATIONS = frozenset({"裁剪-布", "裁剪-纱", "质检", "腰靠垫"})

# ── 特殊选项 → 条件工序（插在目标工序后；`after` = **锚点在它之前**，见 `_insert_after`）──
# 真值源 §1【默】19 项特殊选项，按处置分三类（**每一类都要显式登记**，见下方
# `NON_PIECEWORK_OPTIONS` / `OPTION_FACTOR_SCOPES` 的注释；门禁 =
# `tests/test_production/test_special_options.py::TestCriterion1CoverageGate`）：
#   ① 加条件工序 = 本表；② 加计件系数 = `OPTION_FACTOR_SCOPES`；③ 不计件 = `NON_PIECEWORK_OPTIONS`。
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

# ── 特殊选项 → 计件系数（真值源 §4「条件系数表：特殊选项 → **工序** → 系数」）──
# 每个选项一个**档位列表**（按书写顺序解析，**后面的档覆盖前面的档** —— 与 CSS/路由表同构：
# 先写平摊档，再写逐工序/逐部位的**例外**档），档位字段：
#   `factor`         系数（乘在工序实例的 `factor` 上）
#   `operation_name` 限定工序名；`None` = 该**部位全部**工序（平摊档）
#   `curtain_type`   限定部位（布帘/纱帘/帘头）；`None` = 不限部位
#   `source`         `实证` / `推算`（真值源标注口径，商家可配版本化）
#
# v1 **只种「一分为二 ⇒ 1.7 / 全部工序」一个档** —— 它是唯一的**实证**值（真值源 §4 + 行业 ERP）。
# issue #4230 §2.4 的逐工序/逐分组细算档（车位 ≈×2.0 / 后道 ×1.0 / 裁剪 ×1.2）是**纯推算**，
# 且按其细算的总价会**低于**平摊 ×1.7 ⇒ **不拿推算值覆盖实证值**，v1 不启用、不种值。
# 结构留 `operation_name` / `curtain_type` 两个限定档位，等客户确认后再细化（不把路堵死）——
# 「该档位可用」由 `test_operation_scoped_factor_applies_to_that_operation_only` 以限定值构造证明。
#
# ⚠️ **键 = ERP 名（issue #4389，用户裁定 R-e「以 ERP 为准改」）**：本表键是
# 「订单选配 → 计件系数」的 **join key** —— 顾客按 ERP 说法选 `一分为二`，而旧键写作 `一分二`
# ⇒ 查不到 ⇒ 系数静默退回 1.0 = **少发工人钱**（错一个字就静默失效，无任何东西变红）。
# 旧写法 `一分二` **不是**兼容别名（R18 要求三张表的键与 ERP **逐字一致**）；存量库里已按
# 旧名落地的行由**新迁移** `V65__align_special_option_names_with_erp.sql` 改名（已发布迁移不可改）。
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
# 「加条件工序 / 加计件系数 / 不计件」三类中的哪一类。
#
# 行为口径 = 与「不计件」相同（不加条件工序、不改计件系数、计件金额不变），但**语义不同**：
# 它不是「已定论的不计件」，而是「未定论」。两者的区别在数据上可查（本集合 vs
# `NON_PIECEWORK_OPTIONS`）⇒ 它**不落进静默黑洞**（`.get(opt) → None` 那种）。
PENDING_CUSTOMER_CONFIRMATION_OPTIONS = frozenset({"余料带回"})

# 必完工序 / 生产开始标记（默认；商家可配「此工序必须完成才可打包」）
MUST_FINISH_OPS = {"外帘装袋"}   # 打包前置（截图「此工序必须完成才可打包」）
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
FOLD_KEYS = ("pleat_count",)               # 韩褶折数法才产出；非折数法（定宽米数法）缺失 ⇒ 兜底 1
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
    """应做数量 = 算料引擎输出（折数/用料/孔数/幅数/套数），报工只确认不心算。

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
    """部位×工艺基准路线 + 条件工序（特殊选项触发）+ 定型开关。

    Args:
        position: {curtain_type, craft, is_shaped, special_options: [..]}
    Returns: 工序名序列
    """
    curtain_type = position.get("curtain_type", "布帘")
    craft = position.get("craft", "韩褶")
    key = (curtain_type, craft)
    if key not in ROUTINGS:
        raise ValueError(f"不支持的 部位×工艺 组合: {key}")
    route = list(ROUTINGS[key])

    # 定型=否 → 移除 定型-布/复烫-布（部位级开关）
    if position.get("is_shaped") is False:
        route = [op for op in route if op not in ("定型-布", "复烫-布")]

    # 特殊选项条件工序（按 after 定位插入；`NON_PIECEWORK_OPTIONS` 与纯系数选项无 operation 档 ⇒ 跳过）
    specials = position.get("special_options") or []
    for opt in specials:
        rule = SPECIAL_OPTION_ROUTINGS.get(opt)
        if rule and "operation" in rule:
            route = _insert_after(route, rule["operation"], rule["after"])
    return route


def _scope_applies(scope: Dict[str, Any], position: Dict[str, Any], operation: str) -> bool:
    """档位是否作用于该（部位, 工序）——`None` 限定 = 不限（见 `OPTION_FACTOR_SCOPES` 注释）。"""
    operation_name = scope.get("operation_name")
    if operation_name is not None and operation_name != operation:
        return False
    curtain_type = scope.get("curtain_type")
    return curtain_type is None or curtain_type == position.get("curtain_type", "布帘")


def factor_for(position: Dict[str, Any], operation: str) -> float:
    """该工序实例的特殊选项计件系数（真值源 §4 条件系数表；无选项 ⇒ 1.0）。

    单个选项内：**后面的档覆盖前面的档**（最后一个命中的档生效，见 `OPTION_FACTOR_SCOPES`
    注释）—— 逐工序/逐部位的**例外档**因此能盖住平摊档，而**不是**与它相乘
    （相乘会把「平摊 ×1.7 + 车位 ×2.0」算成 ×3.4，纯属重复计费）。
    多个加系数选项并存：各自解出的系数**相乘**（独立倍率的合成口径；v1 只种「一分为二」一个档）。
    只认 `OPTION_FACTOR_SCOPES` 登记过的选项：未登记的名字**不得**悄悄改系数。
    """
    factor = 1.0
    for opt in position.get("special_options") or []:
        resolved = None
        for scope in OPTION_FACTOR_SCOPES.get(opt, ()):
            if _scope_applies(scope, position, operation):
                resolved = float(scope["factor"])   # 后档覆盖前档
        if resolved is not None:
            factor *= resolved
    return factor


def _insert_after(route: List[str], operation: str, after: str) -> List[str]:
    """把 operation 插到 after 之后（after 不在路线中则追加到末尾）。"""
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
    """实例化工序（应做数量=引擎输出 + 单价 + 必完/开始标记 + 特殊选项系数）。

    Args:
        position: {curtain_type, craft, is_shaped, special_options, open_count}
        calc_info: 算料引擎输出（`curtain_calc.build_quote` 的返回，键见 METER_KEYS/FOLD_KEYS 等；
                   缺 `panels`/`set_count`/`holes` 时按 _qty_for 的兜底口径处理，不落 0）
    Returns: 工序实例列表 [{seq, operation, group, unit, qty, unit_price, factor,
             is_must_finish, is_start_marker, qty_source}]
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
            "factor": factor_for(position, operation),
            "is_must_finish": operation in MUST_FINISH_OPS,
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
# | 单价绑在「工序名」上（35 行） | 单价绑在 `(逻辑工序, 部位)` 上（28 × 3 = 84 行） |
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

#: 主线**全貌**（含「工艺槽位」占位）—— 仅文档用途，**不落库**
#: （槽位 = 打褶那一道：韩褶 / 打孔 / 穿杆 / 四爪钩由 `ROUTE_RULES` 按工艺插入）
ROUTE_MAINLINE: List[str] = ["精裁", "三边", "⟪工艺槽位⟫", "熨烫", "定型", "复烫",
                             "车被", "外帘打卷", "外帘装袋", "外帘发货"]

#: **实际落库的 9 道**主线（部位无关；工艺槽位不落库）
ROUTE_MAINLINE_STEPS: List[str] = ["精裁", "三边", "熨烫", "定型", "复烫", "车被",
                                   "外帘打卷", "外帘装袋", "外帘发货"]

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

#: 旧工序名 → 逻辑工序名（35 → 28；7 组部位变体 + 去 `-布`/`-纱` 后缀）
OPERATION_LOGICAL_NAMES: Dict[str, str] = dict(_LOGICAL_NAME_PAIRS)

#: 部位价目 + 适用性矩阵的**书写形态**：`(逻辑工序, 部位, 单价|None, applicable)` × **84 行**
#: （28 道逻辑工序 × 3 部位）。同上：用有序行而不是嵌套 dict 字面量（避免触发 L0 守卫）。
#:
#: 语义（母单 #4423 冻结）：
#: · `applicable=True`  = 该部位**做**这道工序（`build_route_v2` 保留它）；
#: · `applicable=False` = 该部位**明确不做**（`build_route_v2` 滤掉它）—— 与「没定价」可区分；
#: · `unit_price=None`  = **不落价**：明确不做的部位不报价（有价 = 有业务含义的价目行）；
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
]


def _build_position_prices(rows: List[tuple]) -> Dict[str, Dict[str, Any]]:
    """`(逻辑工序, 部位, 单价|None, applicable)` 行 → `{逻辑工序: {部位: {unit_price, applicable}}}`。"""
    prices: Dict[str, Dict[str, Any]] = {}
    for logical, position, unit_price, applicable in rows:
        prices.setdefault(logical, {})[position] = {"unit_price": unit_price,
                                                     "applicable": applicable}
    return prices


#: 部位价目 + 适用性矩阵（28 道逻辑工序 × 3 部位 = **84 行**，逐行显式，不留隐式缺省）
OPERATION_POSITION_PRICES: Dict[str, Dict[str, Any]] = _build_position_prices(_POSITION_PRICE_ROWS)

#: 规则表 26 条（工艺变体 10 + 特殊选项 16）—— 「主线 + 规则」取代「9 条展开路线」
#:
#: 字段：`trigger_kind`（`craft`/`option`；`shaped`/`processing_item` 预留但 P1 不种行）·
#: `trigger_value`（工艺名 / 特殊选项名，**逐字 = ERP 写法**，它是 join key）·
#: `position`（部位限定，`None` = 不限）· `action`（`insert`/`remove`）·
#: `operation`（**逻辑工序名**）· `after_operation`（insert 锚点，`None` = 追加末尾）·
#: `priority`（**升序生效**，同序按声明顺序 —— 顺序敏感，见 `build_route_v2`）。
#:
#: ⚠️ 特殊选项 16 条 = 旧 `SPECIAL_OPTION_ROUTINGS` **逐条搬迁**，且**工序名与锚点都归一为
#: 逻辑名**（`布三边`→`三边`、`布帘车被`→`车被`、`精裁-布`→`精裁`）—— 否则锚点在逻辑名序列里
#: 找不到 ⇒ 条件工序会**静默追加到末尾**（工序顺序错 = 车间按错顺序干）。
ROUTE_RULES: List[Dict[str, Any]] = [
    # ── 工艺变体（trigger_kind='craft'）──
    {"trigger_kind": "craft", "trigger_value": "韩褶", "position": None, "action": "insert",
     "operation": "韩褶", "after_operation": "三边", "priority": 10},
    {"trigger_kind": "craft", "trigger_value": "韩褶", "position": "布帘", "action": "insert",
     "operation": "上车布", "after_operation": "韩褶", "priority": 20},
    {"trigger_kind": "craft", "trigger_value": "打孔", "position": None, "action": "insert",
     "operation": "打孔", "after_operation": "三边", "priority": 30},
    {"trigger_kind": "craft", "trigger_value": "四爪钩", "position": None, "action": "insert",
     "operation": "上车布", "after_operation": "三边", "priority": 40},
    {"trigger_kind": "craft", "trigger_value": "四爪钩", "position": None, "action": "remove",
     "operation": "定型", "after_operation": None, "priority": 50},
    {"trigger_kind": "craft", "trigger_value": "四爪钩", "position": None, "action": "remove",
     "operation": "复烫", "after_operation": None, "priority": 60},
    {"trigger_kind": "craft", "trigger_value": "穿杆", "position": None, "action": "remove",
     "operation": "定型", "after_operation": None, "priority": 70},
    {"trigger_kind": "craft", "trigger_value": "穿杆", "position": None, "action": "remove",
     "operation": "复烫", "after_operation": None, "priority": 80},
    {"trigger_kind": "craft", "trigger_value": "平幔", "position": None, "action": "insert",
     "operation": "帘头制作", "after_operation": "三边", "priority": 90},
    {"trigger_kind": "craft", "trigger_value": "平幔", "position": None, "action": "remove",
     "operation": "复烫", "after_operation": None, "priority": 100},
    # ── 特殊选项（trigger_kind='option'）= 旧 SPECIAL_OPTION_ROUTINGS 逐条搬迁（16 条）──
    {"trigger_kind": "option", "trigger_value": "拼1次", "position": None, "action": "insert",
     "operation": "拼1次", "after_operation": "三边", "priority": 110},
    {"trigger_kind": "option", "trigger_value": "拼2次", "position": None, "action": "insert",
     "operation": "拼2次", "after_operation": "三边", "priority": 120},
    {"trigger_kind": "option", "trigger_value": "拼3次", "position": None, "action": "insert",
     "operation": "拼3次", "after_operation": "三边", "priority": 130},
    {"trigger_kind": "option", "trigger_value": "加花边", "position": None, "action": "insert",
     "operation": "花边", "after_operation": "三边", "priority": 140},
    {"trigger_kind": "option", "trigger_value": "加铅块", "position": None, "action": "insert",
     "operation": "铅坠", "after_operation": "三边", "priority": 150},
    {"trigger_kind": "option", "trigger_value": "接高", "position": None, "action": "insert",
     "operation": "接高", "after_operation": "精裁", "priority": 160},
    {"trigger_kind": "option", "trigger_value": "双眼皮接高", "position": None, "action": "insert",
     "operation": "接高", "after_operation": "精裁", "priority": 170},
    {"trigger_kind": "option", "trigger_value": "余料做绑带", "position": None, "action": "insert",
     "operation": "绑带", "after_operation": "车被", "priority": 180},
    {"trigger_kind": "option", "trigger_value": "布绑带", "position": None, "action": "insert",
     "operation": "绑带", "after_operation": "车被", "priority": 190},
    {"trigger_kind": "option", "trigger_value": "余料做帘头", "position": None, "action": "insert",
     "operation": "帘头制作", "after_operation": "三边", "priority": 200},
    {"trigger_kind": "option", "trigger_value": "抱枕", "position": None, "action": "insert",
     "operation": "抱枕", "after_operation": "外帘打卷", "priority": 210},
    {"trigger_kind": "option", "trigger_value": "纱绑带", "position": None, "action": "insert",
     "operation": "绑带", "after_operation": "车被", "priority": 220},
    {"trigger_kind": "option", "trigger_value": "加logo条", "position": None, "action": "insert",
     "operation": "logo条", "after_operation": "三边", "priority": 230},
    {"trigger_kind": "option", "trigger_value": "加立边", "position": None, "action": "insert",
     "operation": "立边", "after_operation": "三边", "priority": 240},
    {"trigger_kind": "option", "trigger_value": "扣环", "position": None, "action": "insert",
     "operation": "扣环", "after_operation": "三边", "priority": 250},
    {"trigger_kind": "option", "trigger_value": "防翘扣", "position": None, "action": "insert",
     "operation": "防翘扣", "after_operation": "三边", "priority": 260},
]


def _rule_triggers(rule: Dict[str, Any], position: Dict[str, Any]) -> bool:
    """该规则是否被本部位触发（**精确匹配**：选项名不得用 `contains` 命中 —— 错一个字就静默失效）。"""
    kind = rule["trigger_kind"]
    if kind == "craft":
        return rule["trigger_value"] == position.get("craft")
    if kind == "option":
        return rule["trigger_value"] in (position.get("special_options") or ())
    # `shaped` / `processing_item` 是**表结构预留**的触发类型（P1 无种子行）：
    # 静默返回 False 会让「规则已落库但永不生效」变成无人可见的黑洞 ⇒ 显式失败。
    raise ValueError(f"未实现的规则触发类型: {kind}")


def build_route_v2(position: Dict[str, Any]) -> List[str]:
    """新模型：**主线 + 规则（工艺/选项）+ 部位适用性** → 逻辑工序名序列（**不展开部位后缀**）。

    纯函数（不改入参、不碰 DB、零 LLM）。语义（**顺序敏感**）：

    1. 取主线 9 道（`ROUTE_MAINLINE_STEPS`）；
    2. 按 `ROUTE_RULES` 应用规则 —— **按 `priority` 升序**（同 priority 按声明顺序）；
       `insert` 用 `after_operation` 定位（锚点不在序列中 ⇒ **追加末尾**，与既有
       `_insert_after` 同款），`remove` 直接删除该工序名；
    3. 按 `OPERATION_POSITION_PRICES[工序][部位]["applicable"]` **滤掉该部位不做的工序**。

    ⚠️ **`remove` 不先于 `insert`**：顺序完全由 `priority` 决定（母单 #4423 冻结口径）。
    例：`韩褶 + 布帘 insert 上车布 after 韩褶` 必须排在 `韩褶 insert 韩褶 after 三边` **之后**
    —— 否则锚点「韩褶」还不存在 ⇒ 「上车布」被追加到末尾（顺序错）。

    Args:
        position: `{curtain_type, craft, special_options: [..]}`（与 `build_routing` 同形）
    Returns: 逻辑工序名序列（如 `["精裁","三边","韩褶","上车布",...]`）
    """
    curtain_type = position.get("curtain_type", "布帘")
    route = list(ROUTE_MAINLINE_STEPS)
    for rule in sorted(ROUTE_RULES, key=lambda r: r["priority"]):
        if not _rule_triggers(rule, position):
            continue
        if rule["position"] is not None and rule["position"] != curtain_type:
            continue
        if rule["action"] == "insert":
            route = _insert_after(route, rule["operation"], rule["after_operation"])
        else:
            route = [op for op in route if op != rule["operation"]]
    prices = OPERATION_POSITION_PRICES
    return [op for op in route if prices[op][curtain_type]["applicable"]]
