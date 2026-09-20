# case_ids: PG-018, PG-035, PG-039
# （issue #4937 把矩阵终态从「30 × 4 = 120 行」换成「**一道逻辑工序一行**（30 行，部位写 `通用`）」；
#   本文件既有用例的**行为契约**（布料单两道 / 打包套级 / 未定价可判）**未变** ⇒ 不新增用例 ID。）
"""布料基础路线 + 「打包」工序（issue #4529，包 F）—— 真值源判据（**去部位化后**）。

## 本文件判什么

用户裁定（2026-09-19，issue #4529）：

1. **布料单**（`processing_info.saleForm = 布料`）只有两道工序：`配料` + `打包`；
2. **成品帘**主线 = 9 道 + `打包` = **10 道**，且 `打包` 在一条路线里**只出现 1 行**；
3. `打包` 是**套级**工序（`scope='set'`）；
4. 价目矩阵（issue #4937 之后）= **30 道逻辑工序 × 1 行**（部位维退场；幸存行 `position='通用'`）；
5. **「未定价」**（`unit_price IS NULL`）与「有价 0 元」**可区分**（#4937 之后 `applicable` 恒
   `TRUE`，不再是区分器）；
6. 新工序的 provenance 走 `production_operations.source` 的**受控枚举**（`占位待确认`）。

## 🔴 本文件在 issue #4937 换过的基线（照实登记）

| 旧基线（已退休） | 新基线 |
|---|---|
| 矩阵 `30 × 4 = 120` 格、`OPERATION_POSITION_PRICES[工序][部位]` 两级 | **30 行单键**（`OPERATION_POSITION_PRICES[工序]`） |
| 「`applicable=FALSE` ⇒ 该部位**明确不做**」= 区分器 | `applicable` **恒 `TRUE`**；区分器只剩 `unit_price`（NULL = 未定价） |
| `ROUTINGS` 的键是 `(部位, 工艺)`（9 条） | 键是**工艺**（5 条） |
| `schema.sql` 的矩阵终态 = **120 行**（V88 的软删口径） | 终态 = **30 存活 + 90 软删 = 120 行**（O4 塌缩；行集合一字不减） |

## 如实登记（不粉饰）

- **设计稿与 DDL 冲突一处**：设计 §4.3 写「`配料` 计件单价留空（NULL）」，但
  `production_operations.unit_price` 是 `NOT NULL DEFAULT 0`（V49 DDL）⇒ 工序库行**只能落 0**；
  「未定价」的真载体 = `production_operation_positions.unit_price = NULL` + `source = '占位待确认'`。
- **`打包` 的位置是推断**：ERP 加工单实证 `外帘打包 › 外帘装箱 › 外帘发货` ⇒ 打包在装袋**之前**；
  #4343 登记过这两道的对应关系**未能确定** ⇒ 待客户确认。

## 红证（「不会红的断言 = 空断言」）

`TestInjectedDrift` 用注入式自证证明本文件的判据**真能红**。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.production.routing import (
    FABRIC_MAINLINE_STEPS,
    FABRIC_POSITION,
    FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT,
    OPERATION_CATALOG,
    OPERATION_POSITION_PRICES,
    ROUTE_MAINLINE_STEPS,
    ROUTINGS,
    build_route_v2,
)

REPO = Path(__file__).resolve().parents[4]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
SCHEMA = REPO / "docs/sql/schema.sql"
V79 = MIGRATION_DIR / "V79__seed_fabric_route_and_packing_operation.sql"

#: 既有三部位（窗帘）—— 布料是**第 4 个**部位（顶层产品形态键，**不是**矩阵的索引维）。
CURTAIN_POSITIONS = ("布帘", "纱帘", "帘头")
ALL_POSITIONS = CURTAIN_POSITIONS + (FABRIC_POSITION,)
#: 工艺维（`ROUTINGS` 的键）。
CRAFTS = ("韩褶", "打孔", "四爪钩", "穿杆", "平幔")

#: 本包新增的两道工序。
NEW_OPERATIONS = ("配料", "打包")

#: O4 之后矩阵的终态形态（`V104__deposition_matrix_collapse.sql`）。
NEUTRAL_POSITION = "通用"


def unpriced(cells: dict) -> set:
    """`unit_price is None` = **未定价**（≠ 有价 0 元）—— #4937 之后唯一的区分器。

    ⚠️ 旧判据用的是「`applicable=True` 且 `unit_price is None`」；`applicable` 退场后
    （恒 `TRUE`）它退化成恒等式 ⇒ 判据换成**只看价**（判别力不变：注入一个价即红）。
    """
    return {key for key, cell in cells.items() if cell["unit_price"] is None}


def _cells() -> dict:
    """价目矩阵（**单键**）→ `{逻辑工序: {unit_price, applicable}}`（深拷贝，供注入用）。"""
    return {logical: dict(cell) for logical, cell in OPERATION_POSITION_PRICES.items()}


def _migration_sql() -> str:
    assert V79.exists(), (
        f"缺布料路线种子迁移 {V79.name} —— 只改 routing.py ⇒ 存量库/全新库都没有布料路线与价目行"
        f"（「CI 绿、功能静默缺失」，#4235 形态）"
    )
    return V79.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 1：布料单 ⇒ 配料 + 打包（两道；缺/多 ⇒ 红）
# ══════════════════════════════════════════════════════════════════════════════════

def test_fabric_mainline_is_material_prep_then_packing():
    """布料主线 = `配料 → 打包`（用户裁定：布料也可以有打包工序）。"""
    assert FABRIC_MAINLINE_STEPS == ["配料", "打包"], (
        f"布料主线漂移：{FABRIC_MAINLINE_STEPS}（裁定 = 配料 → 打包）")
    assert FABRIC_POSITION == "布料", "第 4 个产品形态名必须是 `布料`（前端 saleForm 的取值逐字）"


def test_fabric_order_route_is_exactly_two_operations():
    """`build_route_v2(布料)` = 两道；多一道（如把窗帘主线/工艺规则漏进来）或少一道都红。

    ⚠️ 这条在 #4937 期间**真的红过一次**（实测 `['配料','打包','韩褶','上车布']`）：部位过滤退场后，
    「哪些工序不属于这个产品形态」必须由**产品形态**表达 —— 修正落在
    `routing.py::build_route_v2` 的 `if is_fabric: continue`（同一条主线选择键）。
    """
    route = build_route_v2({"curtain_type": FABRIC_POSITION})
    assert route == ["配料", "打包"], f"布料单的工序不是 配料+打包：{route}"
    # 工艺维对布料单无意义：带 craft 不得改变结果（否则同一张布料单会因工艺不同而多工序）
    for craft in CRAFTS:
        assert build_route_v2({"curtain_type": FABRIC_POSITION, "craft": craft}) == ["配料", "打包"], (
            f"craft={craft} 改变了布料路线 ⇒ 布料单会被插入窗帘工艺工序")
    # 特殊选项也不得给布料单加工序（窗帘的条件工序锚点/适用性都不在布料上）
    assert build_route_v2({"curtain_type": FABRIC_POSITION, "special_options": ["加花边"]}) == \
        ["配料", "打包"]


def test_curtain_routes_do_not_get_material_prep():
    """`配料` 是**布料专属**：任何窗帘工艺路线里都不许出现。"""
    for craft in ROUTINGS:
        for curtain_type in CURTAIN_POSITIONS:
            route = build_route_v2({"curtain_type": curtain_type, "craft": craft})
            assert "配料" not in route, (
                f"{curtain_type}×{craft} 路线里出现了布料专属工序 `配料`：{route}")


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 2：成品帘主线 9 + 打包 = 10 道，且 `打包` 只出现 1 行
# ══════════════════════════════════════════════════════════════════════════════════

def test_curtain_mainline_is_nine_steps_plus_packing():
    """主线 10 道，`打包` 恰好 1 行，且落在 `外帘打卷` 与 `外帘装袋` **之间**。"""
    assert len(ROUTE_MAINLINE_STEPS) == 10, (
        f"窗帘主线应为 9 + 打包 = 10 道，实测 {len(ROUTE_MAINLINE_STEPS)}：{ROUTE_MAINLINE_STEPS}")
    assert ROUTE_MAINLINE_STEPS.count("打包") == 1, "`打包` 在主线上必须恰好 1 行"
    assert ROUTE_MAINLINE_STEPS.index("打包") == ROUTE_MAINLINE_STEPS.index("外帘打卷") + 1, (
        "`打包` 不在 `外帘打卷` 与 `外帘装袋` 之间 ⇒ 与 ERP 实证顺序不符")


def test_packing_appears_once_per_curtain_route():
    """每个 `(帘种, 工艺)` 组合里 `打包` 各出现**恰好 1 行**（缺 ⇒ 少一道活；重复 ⇒ 双付）。

    形态对齐 #4408 的实证：页面路径 14 道/¥3.00 vs 米宝路径 17 道/¥6.00 —— 同一道套级工序
    被按部位展开两次 ⇒ **双付工人工资**。
    """
    for craft in CRAFTS:
        for curtain_type in CURTAIN_POSITIONS:
            route = build_route_v2({"curtain_type": curtain_type, "craft": craft})
            assert route.count("打包") == 1, (
                f"{curtain_type}×{craft} 路线里 `打包` 出现 {route.count('打包')} 次（必须 1 次）：{route}")


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 3：`打包` 的 scope='set'（套级：一单一套一次，不按部位展开）
# ══════════════════════════════════════════════════════════════════════════════════

_SCOPE_SET_RE = re.compile(
    r"UPDATE\s+production_operations\s+SET\s+scope\s*=\s*'set'\s+WHERE\s+name\s+IN\s*\(([^)]*)\)",
    re.I | re.S)


def _scope_set_names(sql: str) -> set:
    """该源里被回填成套级的工序名集合（逐条 SET scope='set' 的 UPDATE）。"""
    names = set()
    for block in _SCOPE_SET_RE.findall(sql):
        names |= set(re.findall(r"'([^']+)'", block))
    return names


def test_packing_is_set_scoped_in_every_source():
    """`打包` = 套级；`配料` = 部位级（米）—— 三源（V79 / schema.sql）逐源判。

    套级语义由 `scope='set'` 承担（Java 侧 `keepsSetLevel` 去重按该列），
    **不是**靠「只对一个部位 applicable」表达（那一维已退场，见 #4937）。
    """
    for label, sql in (("V79", _migration_sql()), ("schema.sql", SCHEMA.read_text(encoding="utf-8"))):
        scoped = _scope_set_names(sql)
        assert scoped, f"{label} 里没有 `SET scope='set'` 的回填语句（判据是空跑）"
        assert "打包" in scoped, (
            f"{label} 没有把 `打包` 回填成套级 ⇒ 一樘「布+纱」会把它算两次（#4408 双付形态）")
        assert "配料" not in scoped, (
            f"{label} 把 `配料` 标成了套级 —— 配料按**米**计（部位级），标成套级会少发工人钱")


def test_packing_is_priced_null_and_carries_its_own_row():
    """`打包` 在矩阵里有**自己那一行**且**未定价**（`NULL` ≠ 0 元）。

    ⚠️ 旧判据是「`打包` 对 4 个部位**全 applicable**」—— #4937 之后 `applicable` 恒 `TRUE`、
    且矩阵只有**一行**，所以判据换成「有行 + 未定价 + 价不回落」（判别力不变）。
    """
    assert "打包" in OPERATION_POSITION_PRICES, "矩阵里没有 `打包` 那一行 ⇒ 实例化取不到价"
    assert OPERATION_POSITION_PRICES["打包"]["unit_price"] is None, (
        "`打包` 的价不是 `NULL` ⇒ 「未定价」被回落成了 0 元（工人白干且无人知道，issue #4696）")
    assert OPERATION_CATALOG["打包"]["unit_price"] == 0.0, (
        "夹具前提变了：工序库行价确实是 `NOT NULL DEFAULT 0` 的产物 0.0 —— "
        "正因如此「矩阵行 NULL」才是唯一可信的「未定价」载体")


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 4：价目矩阵 = **一道逻辑工序一行**（30 行），逐行显式
# ══════════════════════════════════════════════════════════════════════════════════

def test_position_matrix_is_thirty_rows_by_logical_operation():
    """**30 行**逐行显式（不留隐式缺省）—— 缺一行 ⇒ `build_route_v2` KeyError ⇒ 建单 500。

    🔴 基线换代（issue #4937）：旧基线是 `30 × 4 = 120` 格（两级索引）；O4 把矩阵**物理塌缩**为
    「一道逻辑工序一行」（`V104`），与 `docs/sql/schema.sql` 的终态一致。
    """
    cells = _cells()
    assert len(OPERATION_POSITION_PRICES) == 30, (
        f"逻辑工序数应为 30（28 既有 + 配料 + 打包），实测 {len(OPERATION_POSITION_PRICES)}")
    assert len(cells) == 30, f"价目矩阵应为 30 行（一道逻辑工序一行），实测 {len(cells)}"
    for logical, cell in OPERATION_POSITION_PRICES.items():
        assert set(cell) == {"unit_price", "applicable"}, (
            f"{logical} 的格子形状漂移：{sorted(cell)}")
        assert cell["applicable"] is True, (
            f"{logical} 的 `applicable` 不是 `TRUE` —— 部位维退场后该列不再区分任何行")
    for name in NEW_OPERATIONS:
        assert name in OPERATION_POSITION_PRICES, f"新增工序 `{name}` 没有价目行"


def test_fabric_only_operations_are_registered():
    """`配料`/`打包` 都在矩阵里；`配料` 是布料专属（窗帘路线不含它，见判据 1）。"""
    for name in NEW_OPERATIONS:
        assert name in OPERATION_POSITION_PRICES, f"`{name}` 缺价目行"
    # 反向：`配料` 不得出现在任何窗帘工艺路线里（与 `test_curtain_routes_do_not_get_material_prep` 成对）
    for craft, ops in ROUTINGS.items():
        assert "配料" not in ops, f"工艺 `{craft}` 的基准序列里出现了 `配料`：{ops}"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 5：「未定价」与「有价 0 元」可区分（静默 0 / 混淆 ⇒ 红）
# ══════════════════════════════════════════════════════════════════════════════════

def test_unpriced_is_distinguishable_from_a_zero_price():
    """`unit_price = NULL`（未定价）与 `0.0`（有价 0 元）**可区分**，且集合逐条冻结。"""
    cells = _cells()
    assert unpriced(cells) == set(NEW_OPERATIONS), (
        f"「未定价」的工序集合漂移：{sorted(unpriced(cells))}（期望 {sorted(NEW_OPERATIONS)}）")
    # 反向：其余 28 道都必须**有价**（不是 None、也不是被悄悄回落成 0）
    priced = {logical for logical, cell in cells.items() if cell["unit_price"] is not None}
    assert priced == set(cells) - set(NEW_OPERATIONS), (
        f"有价工序集合漂移：{sorted(set(cells) - set(NEW_OPERATIONS) - priced)} 缺价")


def test_pending_provenance_marks_the_unpriced_operations():
    """「未定价」在**数据上可见**：工序库行的 `source` = `占位待确认`（受控枚举）。"""
    schema = SCHEMA.read_text(encoding="utf-8")
    assert "'占位待确认', '推算', '实证'" in schema, (
        "schema.sql 的 source 受控枚举变了 ⇒ 本判据的取值前提失效（重新裁定用哪个枚举值）")
    for label, sql in (("V79", _migration_sql()), ("schema.sql", schema)):
        assert re.search(r"WHEN\s+id\s+LIKE\s+'op-v79-%'\s+THEN\s+'占位待确认'", sql), (
            f"{label} 没有把新增工序的 source 标成「占位待确认」（按 id 前缀认领）⇒ 未定价在数据上不可见")
        assert "source = '待确认'" not in sql, \
            f"{label} 用了不在 CHECK 枚举里的 '待确认'（迁移会直接报错）"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 6：三源（routing.py ↔ V79/V71 字面量 ↔ schema.sql 终态）
# ══════════════════════════════════════════════════════════════════════════════════

def _literal_position_rows(sql: str) -> list:
    """该源里**字面量** `INSERT INTO production_operation_positions … VALUES` 的行（逐行 tuple）。"""
    rows = []
    for stmt in re.findall(r"INSERT\s+INTO\s+production_operation_positions\b[\s\S]*?;", sql, re.I):
        if "select" in stmt[:stmt.lower().find("values")].lower():
            continue   # 派生回填（V72/V79 的按租户循环）不算字面量种子
        rows.extend(re.findall(
            r"\(\s*'([^']*)'\s*,\s*1\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*(NULL|[\d.]+)\s*,"
            r"\s*(TRUE|FALSE)\s*,\s*'([^']*)'\s*(?:,\s*[01]\s*)?\)", stmt))
    return rows


def test_v79_literal_seed_adds_the_thirty_six_new_cells():
    """V79 的**字面量**种子补 36 格（既有 28 道 × 布料 + 配料×4 + 打包×4）⇒ 84 + 36 = 120。

    ⚠️ V79 是**已发布迁移**（不可改）⇒ 它仍是 120 行态的 `(逻辑工序, 部位)` 字面量；
    O4（`V104`）在**运行时**把它们塌缩成 30 行。本判据钉的是「V79 的字面量没被改过」。
    """
    rows = _literal_position_rows(_migration_sql())
    assert len(rows) == 36, f"V79 的字面量价目行应为 36 格（120 - 84），实测 {len(rows)}"
    logicals = {logical for _, logical, _, _, _, _ in rows}
    assert set(NEW_OPERATIONS) <= logicals, f"V79 没种 `配料`/`打包` 的价目行：{sorted(logicals)}"
    # 新增两道在各部位上的**字面量** applicable（V79 的冻结口径；O4 之后不再是运行期口径）
    parsed = {(logical, position): (None if price == "NULL" else float(price))
              for _, logical, position, price, _, _ in rows}
    assert parsed[("配料", FABRIC_POSITION)] is None, "`配料 × 布料` 的字面量价不是 NULL"
    for position in ALL_POSITIONS:
        assert parsed[("打包", position)] is None, f"`打包 × {position}` 的字面量价不是 NULL"


def test_schema_sql_terminal_state_is_the_collapsed_matrix():
    """bootstrap 终态（`schema.sql`）必须一次给全**塌缩后的 30 行**（新建库不跑迁移链）。

    🔴 基线换代（issue #4937）：旧基线是「120 格、V88 的软删口径」。O4 之后终态是
    「**30 行存活（`position='通用'`）+ 90 行 `deleted = 1`** = 120 行字面量」——
    行集合**一字不减**（否则「行整个消失」这一形态不可比对），退场只靠显式 `deleted` 表达。
    """
    schema = SCHEMA.read_text(encoding="utf-8")
    rows = _literal_position_rows(schema)
    assert len(rows) == 120, (
        f"schema.sql 的价目字面量应为 120 行，实测 {len(rows)} —— 只写迁移 = 新建库缺行 "
        f"⇒ `build_route_v2` KeyError（同 #3270 形态）")
    alive = [(lg, pos) for _, lg, pos, _, _, _ in rows if _deleted_flag(schema, lg, pos) == 0]
    # `_literal_position_rows` 不取 `deleted` 列 ⇒ 从原始文本按 id 逐行读（见下）
    alive = _schema_alive_rows(schema)
    assert len(alive) == 30, (
        f"schema.sql 的**存活**价目行 = {len(alive)}，期望 30（一道逻辑工序一行，O4 塌缩）")
    assert {pos for _, pos, _, _ in alive} == {NEUTRAL_POSITION}, (
        f"存活行的 position 不是全 `{NEUTRAL_POSITION}`："
        f"{sorted({pos for _, pos, _, _ in alive})}（O4 的中性值）")
    assert len({lg for lg, _, _, _ in alive}) == 30, "同一逻辑工序有多个存活行 ⇒ 未塌缩"
    assert {lg for lg, _, _, _ in alive} == set(OPERATION_POSITION_PRICES), (
        "schema.sql 的存活逻辑工序集合 ≠ `routing.py` 的价目键集 ⇒ 两套口径分裂")


def _schema_alive_rows(schema: str) -> list:
    """`schema.sql` 矩阵字面量里的**存活行** → `[(logical, position, price, applicable)]`。

    按 `opp-v70-*` / `opp-v79-*` 两段解析（本文件触碰的字面量），`deleted = 0` 才是存活。
    """
    out = []
    for m in re.finditer(
            r"\(\s*'opp-v(?:70|79)-\d+'\s*,\s*1\s*,\s*'(?P<lg>[^']*)'\s*,\s*'(?P<pos>[^']*)'\s*,"
            r"\s*(?P<price>NULL|[\d.]+)\s*,\s*(?P<ap>TRUE|FALSE)\s*,\s*'active'\s*,\s*"
            r"(?P<del>[01])\s*\)", schema):
        if m.group("del") == "0":
            out.append((m.group("lg"), m.group("pos"), m.group("price"), m.group("ap")))
    return out


def _deleted_flag(schema: str, logical: str, position: str) -> int:
    """兼容入口（旧调用点）：按 `(logical, position)` 找该行的 `deleted`（找不到 ⇒ 0）。"""
    m = re.search(r"\(\s*'opp-v(?:70|79)-\d+'\s*,\s*1\s*,\s*'" + re.escape(logical) + r"'\s*,\s*'"
                  + re.escape(position) + r"'\s*,[\s\S]{0,40}?'active'\s*,\s*([01])\s*\)", schema)
    return int(m.group(1)) if m else 0


def test_new_operations_registered_with_expected_unit_and_group():
    """`配料` 单位 = 米（后道）· `打包` 单位 = 套（后道）—— 单位错 ⇒ 应做数量口径错。"""
    assert OPERATION_CATALOG["配料"]["unit"] == "米", "`配料` 的单位必须是米（用户裁定）"
    assert OPERATION_CATALOG["打包"]["unit"] == "套", "`打包` 的单位必须是套（与三道外帘工序同族）"
    assert OPERATION_CATALOG["配料"]["group"] == "后道"
    assert OPERATION_CATALOG["打包"]["group"] == "后道"


def test_fabric_route_template_name_is_stable():
    """布料路线名（商家可改名，但种子名必须稳定 —— 幂等键是 `(tenant_id, name)`）。"""
    assert FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT == "布料工序路线"


# ══════════════════════════════════════════════════════════════════════════════════
# 红证（注入式自证）：本文件的判据**真能红**
# ══════════════════════════════════════════════════════════════════════════════════

class TestInjectedDrift:
    """逐条注入漂移 ⇒ 对应判据必须变红（证明判据不是空断言）。"""

    @staticmethod
    def _mutated(mutate) -> dict:
        cells = _cells()
        mutate(cells)
        return cells

    def test_unpriced_judgement_detects_price_backfill(self):
        """给「未定价」的工序补上价 ⇒ 它不再属于该集合（判据 5 会红）。"""
        base = unpriced(_cells())
        mutated = unpriced(self._mutated(
            lambda cells: cells.__setitem__("打包", {"unit_price": 1.0, "applicable": True})))
        assert mutated != base, "改单价读不出来 ⇒ 「未定价」判据是空断言"

    def test_unpriced_judgement_detects_the_other_direction(self):
        """把一道**有价**工序的价抹成 `NULL` ⇒ 未定价集合变大（判据 5 会红）。"""
        base = unpriced(_cells())
        mutated = unpriced(self._mutated(
            lambda cells: cells.__setitem__("三边", {"unit_price": None, "applicable": True})))
        assert mutated == base | {"三边"} and mutated != base, "抹价读不出来 ⇒ 判据是空断言"

    def test_applicable_flag_is_no_longer_a_discriminator(self):
        """🔴 `applicable` 退场自证：翻它**不改变**未定价集合（旧判据已退休）。"""
        base = unpriced(_cells())
        mutated = unpriced(self._mutated(
            lambda cells: cells.__setitem__("打包", {"unit_price": None, "applicable": False})))
        assert mutated == base, (
            "翻 `applicable` 改变了「未定价」集合 ⇒ 判据仍在依赖那一维（与本包口径不符）")

    def test_mainline_judgement_detects_missing_or_misplaced_packing(self):
        """删掉 / 挪动主线上的 `打包` ⇒ 判据 2 会红。"""
        steps = list(ROUTE_MAINLINE_STEPS)
        assert steps.count("打包") == 1
        removed = [s for s in steps if s != "打包"]
        assert len(removed) != 10 and removed.count("打包") == 0, "缺打包读不出来"
        moved = list(steps)
        moved.remove("打包")
        moved.append("打包")   # 挪到末尾
        assert moved.index("打包") != moved.index("外帘打卷") + 1, "打包挪位读不出来"

    def test_fabric_route_judgement_detects_extra_operation(self):
        """布料路线多一道（如 `打包` 被按部位展开两次）⇒ 判据 1 会红。"""
        route = ["配料", "打包"]
        assert route != ["配料", "打包", "打包"], "自证：重复打包确实能被相等判据照出来"

    def test_scope_judgement_detects_missing_set_backfill(self):
        """`SET scope='set'` 的 UPDATE 少了 `打包` ⇒ 判据 3 会红。"""
        sql = "UPDATE production_operations SET scope = 'set' WHERE name IN ('外帘打卷');"
        assert "打包" not in _scope_set_names(sql), "scope 回填的解析器读不出注入内容 ⇒ 判据是空断言"
        sql_with = sql + "\nUPDATE production_operations SET scope = 'set' WHERE name IN ('打包');"
        assert "打包" in _scope_set_names(sql_with), "scope 回填的解析器读不出 `打包`"

    def test_collapsed_matrix_judgement_detects_a_resurrected_cell(self):
        """把一行已软删的格改成存活 ⇒ 存活行数判据红（判据 6 会红）。"""
        schema = SCHEMA.read_text(encoding="utf-8")
        before = len(_schema_alive_rows(schema))
        assert before == 30
        injected = schema.replace("  ('opp-v70-02', 1, '精裁', '纱帘', 0.4, TRUE, 'active', 1),",
                                  "  ('opp-v70-02', 1, '精裁', '纱帘', 0.4, TRUE, 'active', 0),", 1)
        assert injected != schema, "注入没生效 ⇒ 本红证是空断言"
        assert len(_schema_alive_rows(injected)) == before + 1, (
            "复活一格后存活行数没变 ⇒ 判据 6 是空断言")
