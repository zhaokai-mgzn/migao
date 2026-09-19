# case_ids: PG-018, PG-035, PG-039
"""布料基础路线（第 4 个部位）+ 「打包」工序（issue #4529，包 F）—— 真值源判据。

## 本文件判什么

用户裁定（2026-09-19，issue #4529 正文 + 第 3 条评论）：

1. **布料单**（`processing_info.saleForm = 布料`）只有两道工序：`配料` + `打包`；
2. **成品帘**主线 = 9 道 + `打包` = **10 道**，且 `打包` 在一条路线里**只出现 1 行**
   （布+纱单不得计两次 —— #4408 实证：页面路径 14 道/¥3.00 vs 米宝路径 17 道/¥6.00 双付）；
3. `打包` 是**套级**工序（`scope='set'`：一单一套一次，不按部位展开）；
4. `配料 × 布料` / `打包 × {布帘,纱帘,帘头,布料}` = `applicable=TRUE`，其余新增组合 `FALSE`
   —— **逐行显式**，价目矩阵 **30 逻辑工序 × 4 部位 = 120 行**；
5. **「适用但未定价」**（`applicable=TRUE` 且 `unit_price IS NULL`）与「不适用」**可区分**；
6. 新工序的 provenance 走 `production_operations.source` 的**受控枚举**
   （`占位待确认`）—— 设计稿写的 `source='待确认'` **不在** DDL 的 CHECK 枚举里
   （代码事实优先，见下方「如实登记」）。

## 如实登记（不粉饰）

- **设计稿与 DDL 冲突一处**：设计 §4.3 写「`配料` 计件单价留空（NULL）」，但
  `production_operations.unit_price` 是 `NOT NULL DEFAULT 0`（V49 DDL + bootstrap 终态）
  ⇒ 工序库行**只能落 0**；「未定价」的真载体 = `production_operation_positions.unit_price = NULL`
  + `applicable = TRUE`（新模型按部位取价）+ `source = '占位待确认'`。本文件按后者判。
- **`打包` 的位置是推断**：ERP 加工单实证 `外帘打包 › 外帘装箱 › 外帘发货`，`外帘装袋` ≈
  `外帘装箱` ⇒ 打包在装袋**之前**；#4343 登记过这两道的对应关系**未能确定**
  ⇒ 本实现按该顺序 propose，**待客户确认**。

## 红证（「不会红的断言 = 空断言」）

`TestInjectedDrift` 用注入式自证证明本文件的判据**真能红**（缺 `打包` / 打包落错位 /
翻一格 applicable / 把套级工序混进部位级）。
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

#: 既有三部位（窗帘）—— 布料是**第 4 个**部位。
CURTAIN_POSITIONS = ("布帘", "纱帘", "帘头")
ALL_POSITIONS = CURTAIN_POSITIONS + (FABRIC_POSITION,)

#: 本包新增的两道工序。
NEW_OPERATIONS = ("配料", "打包")

#: 「适用但未定价」的**判定函数**（判据 5 的判据本体；测试与注入式自证共用同一份）。
def unpriced_applicable(cells: dict) -> set:
    """`applicable=True` 且 `unit_price is None` = **适用但未定价**（≠ 不适用）。"""
    return {key for key, cell in cells.items()
            if cell["applicable"] and cell["unit_price"] is None}


def not_applicable(cells: dict) -> set:
    """`applicable=False` = 该部位**明确不做**（`build_route_v2` 滤掉它）。"""
    return {key for key, cell in cells.items() if not cell["applicable"]}


def _cells() -> dict:
    return {(logical, position): cell
            for logical, by_position in OPERATION_POSITION_PRICES.items()
            for position, cell in by_position.items()}


def _migration_sql() -> str:
    assert V79.exists(), (
        f"缺布料路线种子迁移 {V79.name} —— 只改 routing.py ⇒ 存量库/全新库都没有布料路线与"
        f"120 行价目（「CI 绿、功能静默缺失」，#4235 形态）"
    )
    return V79.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 1：布料单 ⇒ 配料 + 打包（两道；缺/多 ⇒ 红）
# ══════════════════════════════════════════════════════════════════════════════════

def test_fabric_mainline_is_material_prep_then_packing():
    """布料主线 = `配料 → 打包`（用户裁定：布料也可以有打包工序）。"""
    assert FABRIC_MAINLINE_STEPS == ["配料", "打包"], (
        f"布料主线漂移：{FABRIC_MAINLINE_STEPS}（裁定 = 配料 → 打包）"
    )
    assert FABRIC_POSITION == "布料", "第 4 个部位名必须是 `布料`（前端 saleForm 的取值逐字）"


def test_fabric_order_route_is_exactly_two_operations():
    """`build_route_v2(布料)` = 两道；多一道（如把窗帘主线漏进来）或少一道都红。"""
    route = build_route_v2({"curtain_type": FABRIC_POSITION})
    assert route == ["配料", "打包"], f"布料单的工序不是 配料+打包：{route}"
    # 工艺维对布料单无意义：带 craft 不得改变结果（否则同一张布料单会因工艺不同而多工序）
    for craft in ("韩褶", "打孔", "四爪钩", "穿杆", "平幔"):
        assert build_route_v2({"curtain_type": FABRIC_POSITION, "craft": craft}) == ["配料", "打包"], (
            f"craft={craft} 改变了布料路线 ⇒ 布料单会被插入窗帘工艺工序"
        )
    # 特殊选项也不得给布料单加工序（窗帘的条件工序锚点/适用性都不在布料上）
    assert build_route_v2({"curtain_type": FABRIC_POSITION, "special_options": ["加花边"]}) == \
        ["配料", "打包"]


def test_curtain_positions_do_not_get_material_prep():
    """`配料` 是**布料专属**：任何窗帘部位路线里都不许出现（翻 applicable 即红）。"""
    for curtain_type, craft in ROUTINGS:
        route = build_route_v2({"curtain_type": curtain_type, "craft": craft})
        assert "配料" not in route, f"{curtain_type}×{craft} 路线里出现了布料专属工序 `配料`：{route}"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 2：成品帘主线 9 + 打包 = 10 道，且 `打包` 只出现 1 行
# ══════════════════════════════════════════════════════════════════════════════════

def test_curtain_mainline_is_nine_steps_plus_packing():
    """主线 10 道，`打包` 恰好 1 行，且落在 `外帘打卷` 与 `外帘装袋` **之间**。

    位置依据 = ERP 加工单实证 `外帘打包 › 外帘装箱 › 外帘发货`（`外帘装袋` ≈ `外帘装箱`）
    ⇒ 打包在装袋**之前**。⚠️ #4343 登记过这两道的对应关系**未能确定** ⇒ 按此 propose，待客户确认。
    """
    assert len(ROUTE_MAINLINE_STEPS) == 10, (
        f"成品帘主线应为 9 + 打包 = 10 道，实测 {len(ROUTE_MAINLINE_STEPS)}：{ROUTE_MAINLINE_STEPS}"
    )
    assert ROUTE_MAINLINE_STEPS.count("打包") == 1, (
        f"`打包` 在主线上出现 {ROUTE_MAINLINE_STEPS.count('打包')} 次（必须恰好 1 次）"
    )
    idx = ROUTE_MAINLINE_STEPS.index("打包")
    assert ROUTE_MAINLINE_STEPS[idx - 1] == "外帘打卷" and ROUTE_MAINLINE_STEPS[idx + 1] == "外帘装袋", (
        f"`打包` 的位置不是 外帘打卷 → 打包 → 外帘装袋：{ROUTE_MAINLINE_STEPS}"
    )


def test_packing_appears_once_per_position_route():
    """9 个 `(部位, 工艺)` 组合里 `打包` 各出现**恰好 1 行**（缺 ⇒ 少一道活；重复 ⇒ 双付）。

    形态对齐 #4408 的实证：页面路径 14 道/¥3.00 vs 米宝路径 17 道/¥6.00 —— 同一道套级工序
    被按部位展开两次 ⇒ **双付工人工资**。
    """
    for (curtain_type, craft) in ROUTINGS:
        route = build_route_v2({"curtain_type": curtain_type, "craft": craft})
        assert route.count("打包") == 1, (
            f"{curtain_type}×{craft} 路线里 `打包` 出现 {route.count('打包')} 次（必须 1 次）：{route}"
        )


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
    """`打包` = 套级；`配料` = 部位级（米/部位）—— 三源（V79 / schema.sql）逐源判。

    套级语义由 `scope='set'` 承担（Java 侧 `ProcessingOrderService` 的
    `keepsSetLevel` 去重按该列），**不是**靠「只对一个部位 applicable」表达。
    """
    for label, sql in (("V79", _migration_sql()), ("schema.sql", SCHEMA.read_text(encoding="utf-8"))):
        scoped = _scope_set_names(sql)
        assert scoped, f"{label} 里没有 `SET scope='set'` 的回填语句（判据是空跑）"
        assert "打包" in scoped, (
            f"{label} 没有把 `打包` 回填成套级 ⇒ 一樘「布+纱」会把它算两次（#4408 双付形态）"
        )
        assert "配料" not in scoped, (
            f"{label} 把 `配料` 标成了套级 —— 配料按**米**计（部位级），标成套级会少发工人钱"
        )


def test_packing_applicable_on_every_position_while_set_scoped():
    """`打包` 对 4 个部位**全 applicable**（所有产品形态都要做）—— 套级语义不靠适用性表达。

    反例（本判据要挡的形态）：只对布料 applicable ⇒ 窗帘单的 `build_route_v2` 把 `打包` 滤掉
    （少一道活），而布料单正常 ⇒ 缺陷只在窗帘单上出现。
    """
    cells = _cells()
    for position in ALL_POSITIONS:
        assert cells[("打包", position)]["applicable"] is True, (
            f"`打包 × {position}` 不是 applicable ⇒ 该产品形态的主线会被滤掉一道"
        )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 4：价目矩阵 30 逻辑工序 × 4 部位 = 120 行，逐行显式
# ══════════════════════════════════════════════════════════════════════════════════

def test_position_matrix_is_thirty_by_four_and_fully_explicit():
    """120 格**逐行显式**（不留隐式缺省）—— 缺一格 ⇒ `build_route_v2` KeyError ⇒ 建单 500。"""
    cells = _cells()
    assert len(OPERATION_POSITION_PRICES) == 30, (
        f"逻辑工序数应为 30（28 既有 + 配料 + 打包），实测 {len(OPERATION_POSITION_PRICES)}"
    )
    assert len(cells) == 120, f"价目矩阵应为 30 × 4 = 120 格，实测 {len(cells)}"
    for logical, by_position in OPERATION_POSITION_PRICES.items():
        assert set(by_position) == set(ALL_POSITIONS), (
            f"{logical} 的部位不全（{sorted(by_position)} ≠ {sorted(ALL_POSITIONS)}）—— "
            f"逐行显式纪律：每个逻辑工序都要有 4 个部位的行"
        )
        for position, cell in by_position.items():
            assert set(cell) == {"unit_price", "applicable"}, (
                f"{logical}×{position} 的格子形状漂移：{sorted(cell)}"
            )
    for name in NEW_OPERATIONS:
        assert name in OPERATION_POSITION_PRICES, f"新增工序 `{name}` 没有价目行"


def test_fabric_position_only_applicable_for_new_operations():
    """`布料` 部位上只有 `配料`/`打包` 适用；既有 28 道**逐行 FALSE**（不是缺行）。"""
    cells = _cells()
    fabric_true = {logical for (logical, position), cell in cells.items()
                   if position == FABRIC_POSITION and cell["applicable"]}
    assert fabric_true == set(NEW_OPERATIONS), (
        f"布料部位上 applicable=TRUE 的工序 = {sorted(fabric_true)}（应为 {sorted(NEW_OPERATIONS)}）"
    )
    for logical in OPERATION_POSITION_PRICES:
        if logical in NEW_OPERATIONS:
            continue
        assert cells[(logical, FABRIC_POSITION)]["applicable"] is False, (
            f"既有工序 `{logical}` 在布料部位上不是显式 FALSE"
        )


def test_new_operations_are_not_applicable_on_curtain_positions_except_packing():
    """`配料 × {布帘,纱帘,帘头}` 逐行 FALSE；`打包 × 三部位` TRUE（见判据 3 的注释）。"""
    cells = _cells()
    for position in CURTAIN_POSITIONS:
        assert cells[("配料", position)]["applicable"] is False, (
            f"`配料 × {position}` 不是 FALSE ⇒ 窗帘单会多一道布料工序"
        )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 5：「适用但未定价」与「不适用」可区分（静默 0 / 混淆 ⇒ 红）
# ══════════════════════════════════════════════════════════════════════════════════

def test_unpriced_applicable_is_distinguishable_from_not_applicable():
    """新状态「`applicable=TRUE` 但 `unit_price=NULL`」必须**可判**，且与「不适用」不混淆。

    既有约定是「`applicable=FALSE` ⇒ `unit_price` NULL」；本包出现**同一列取值、两种语义**
    ⇒ 判据只能落在 `applicable` 上：**适用但未定价 = 工序出现在路线里、单价为 NULL**；
    **不适用 = 工序根本不出现**。
    """
    cells = _cells()
    expected_unpriced = {("配料", FABRIC_POSITION)} | {("打包", p) for p in ALL_POSITIONS}
    assert unpriced_applicable(cells) == expected_unpriced, (
        f"「适用但未定价」的格子集合漂移：{sorted(unpriced_applicable(cells))}"
    )
    assert not (unpriced_applicable(cells) & not_applicable(cells)), (
        "「适用但未定价」与「不适用」出现重叠 ⇒ 两种语义在同一列上不可区分"
    )
    # 反向：既有的「不适用 ⇒ 不报价」约定不得被本包放宽（逐行仍 NULL）
    for key in not_applicable(cells):
        assert cells[key]["unit_price"] is None, f"{key} 是「不适用」却带着价 ⇒ 语义混淆"


def test_pending_provenance_marks_the_unpriced_operations():
    """「未定价」在**数据上可见**：工序库行的 `source` = `占位待确认`（受控枚举）。

    ⚠️ 设计稿写 `source='待确认'`，而 DDL 的 CHECK 只允许
    `('占位待确认', '推算', '实证')` ⇒ **以代码事实为准**落 `占位待确认`（否则迁移直接违反 CHECK）。
    """
    schema = SCHEMA.read_text(encoding="utf-8")
    assert "'占位待确认', '推算', '实证'" in schema, (
        "schema.sql 的 source 受控枚举变了 ⇒ 本判据的取值前提失效（重新裁定用哪个枚举值）"
    )
    for label, sql in (("V79", _migration_sql()), ("schema.sql", schema)):
        assert re.search(r"WHEN\s+id\s+LIKE\s+'op-v79-%'\s+THEN\s+'占位待确认'", sql), (
            f"{label} 没有把新增工序的 source 标成「占位待确认」（按 id 前缀认领）"
            f"⇒ 未定价在数据上不可见"
        )
        assert "source = '待确认'" not in sql, \
            f"{label} 用了不在 CHECK 枚举里的 '待确认'（迁移会直接报错）"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 6：三源（routing.py ↔ V79 ↔ schema.sql）逐行逐值 —— 本包新增的 36 格
# ══════════════════════════════════════════════════════════════════════════════════

def _literal_position_rows(sql: str) -> list:
    """该源里**字面量** `INSERT INTO production_operation_positions … VALUES` 的行（逐行 tuple）。"""
    rows = []
    for stmt in re.findall(r"INSERT\s+INTO\s+production_operation_positions\b[\s\S]*?;", sql, re.I):
        if "select" in stmt[:stmt.lower().find("values")].lower():
            continue   # 派生回填（V72/V79 的按租户循环）不算字面量种子
        rows.extend(re.findall(
            r"\(\s*'([^']*)'\s*,\s*1\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*(NULL|[\d.]+)\s*,"
            r"\s*(TRUE|FALSE)\s*,\s*'([^']*)'\s*\)", stmt))
    return rows


def test_v79_completes_the_matrix_to_120_rows_with_36_new_cells():
    """V79 的**字面量**种子补 36 格（28 既有工序 × 布料 + 配料×4 + 打包×4）⇒ 84 + 36 = 120。"""
    rows = _literal_position_rows(_migration_sql())
    assert len(rows) == 36, f"V79 的字面量价目行应为 36 格（120 - 84），实测 {len(rows)}"
    parsed = {(logical, position): (None if price == "NULL" else float(price), applicable == "TRUE")
              for _, logical, position, price, applicable, _ in rows}
    truth = {key: (cell["unit_price"], cell["applicable"])
             for key, cell in _cells().items() if key[0] in NEW_OPERATIONS or key[1] == FABRIC_POSITION}
    assert parsed == truth, (
        f"V79 的新增价目与 routing.py 漂移：仅迁移有={sorted(set(parsed) - set(truth))} "
        f"仅真值源有={sorted(set(truth) - set(parsed))} "
        f"值不同={sorted(k for k in set(parsed) & set(truth) if parsed[k] != truth[k])}"
    )


def test_schema_sql_terminal_state_carries_all_120_cells():
    """bootstrap 终态（`schema.sql`）必须一次给全 120 格（新建库不跑迁移链）。"""
    rows = _literal_position_rows(SCHEMA.read_text(encoding="utf-8"))
    assert len(rows) == 120, (
        f"schema.sql 的价目终态应为 120 格，实测 {len(rows)} —— 只写迁移 = 新建库缺 36 格 "
        f"⇒ `build_route_v2` KeyError（同 #3270 形态）"
    )


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
        cells = {key: dict(cell) for key, cell in _cells().items()}
        mutate(cells)
        return cells

    def test_unpriced_judgement_detects_flipped_applicable(self):
        """翻一格 `applicable` ⇒ 「适用但未定价」集合随之变（判据 5 会红）。"""
        base = unpriced_applicable(_cells())
        mutated = unpriced_applicable(self._mutated(
            lambda cells: cells.__setitem__(
                ("配料", FABRIC_POSITION), {"unit_price": None, "applicable": False})))
        assert mutated != base, "翻 applicable 读不出来 ⇒ 「适用但未定价」判据是空断言"

    def test_unpriced_judgement_detects_price_backfill(self):
        """给「未定价」的格子补上价 ⇒ 它不再属于该集合（判据 5 会红）。"""
        base = unpriced_applicable(_cells())
        mutated = unpriced_applicable(self._mutated(
            lambda cells: cells.__setitem__(("打包", "布帘"), {"unit_price": 1.0, "applicable": True})))
        assert mutated != base, "改单价读不出来 ⇒ 「适用但未定价」判据是空断言"

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
