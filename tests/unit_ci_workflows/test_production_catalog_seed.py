# case_ids: PG-018
"""工序库 / 工艺路线种子三源收敛守卫（issue #4116 P0-2）。

## 背景（取证事实）

`production_operations` / `production_routings` 自 V49 建表起**零种子、零消费者**
⇒ 商家无配置入口、库里无数据、§3 工艺路线在 DB 层不可查不可展示。
本包落 **V54 种子**（把 `app/production/routing.py` 的既有确定性常量作为**初始种子**）
+ 只读消费者，并同步 `docs/sql/schema.sql`（bootstrap 路径不跑迁移链 ⇒ 不同步就是
「全新库无工序库」的静默缺口）。

## 本测试守什么（三源 + 两条形态）

同一份工序事实存在**三个**载体，任一漂移都会造成「展示的口径 ≠ 实例化的口径」：

| 源 | 角色 |
|---|---|
| `app/production/routing.py` `OPERATION_CATALOG` / `ROUTINGS` | **真值源**（确定性核心，M4-G-1） |
| `db/migration/V54__seed_production_operations.sql` | 存量库的种子（迁移链） |
| `docs/sql/schema.sql` | 全新库 bootstrap 的种子（CI/本地 docker 栈**不跑迁移链**） |

漂移形态（本测试会让它变红）：
① 改了 Python 目录（改名/改价/加减工序）却没改种子；② 两个 SQL 源的种子不一致
（bootstrap 库与迁移库工序库不同）；③ 路线里引用了工序库里不存在的工序名
（实例化时该道工序无单价/单位可依）；④ 种子 SQL 不再幂等（`ON CONFLICT` 丢失）。

## 红证

把 V54 里 `韩褶-布` 的单价由 `0.4` 改成 `0.5` ⇒ `test_v54_matches_python_catalog` 必红；
删掉 schema.sql 的工序库种子 ⇒ `test_schema_sql_matches_v54` 必红；
把 V54 的 `ON CONFLICT` 去掉 ⇒ `test_seed_sql_is_idempotent` 必红。
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
V54 = REPO / "backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql"
SCHEMA = REPO / "docs/sql/schema.sql"
ROUTING_PY_DIR = REPO / "backend/ai-agent-service"

# 列序 = V54/schema.sql 里 INSERT ... VALUES 的书写顺序（解析器按位取值）
OP_COLUMNS = ("id", "tenant_id", "name", "group_name", "position", "unit", "unit_price",
              "is_must_finish", "is_start_marker", "sort_order", "status")
ROUTING_COLUMNS = ("id", "tenant_id", "curtain_type", "craft", "operations", "status")


# ── 解析器（纯函数，便于用注入式夹具证明会红）──

def _split_rows(values_block: str):
    """把 `VALUES (...), (...)` 拆成行列表（尊重单引号内的逗号与括号）。"""
    rows, depth, current, in_quote = [], 0, "", False
    for ch in values_block:
        if ch == "'":
            in_quote = not in_quote
            current += ch
            continue
        if not in_quote:
            if ch == "(":
                depth += 1
                if depth == 1:
                    current = ""
                    continue
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    rows.append(current)
                    current = ""
                    continue
        if depth >= 1:
            current += ch
    return [r for r in (row.strip() for row in rows) if r]


def _split_fields(row: str):
    """按顶层逗号切字段（尊重单引号与 `[...]::jsonb` 里的逗号）。"""
    fields, current, in_quote, depth = [], "", False, 0
    for ch in row:
        if ch == "'":
            in_quote = not in_quote
        if not in_quote:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "," and depth == 0:
                fields.append(current.strip())
                current = ""
                continue
        current += ch
    fields.append(current.strip())
    return fields


def parse_seed(sql: str, table: str, columns):
    """解析 `INSERT INTO <table> ... VALUES ...` 段 → [{列: 原始字面量}]。

    只认**第一条**该表的 INSERT（两源各只有一条种子语句）。
    """
    match = re.search(
        r"INSERT\s+INTO\s+" + table + r"\b[^;]*?VALUES(.*?)(?:ON\s+CONFLICT|;)",
        sql, re.S | re.I)
    if not match:
        return []
    rows = []
    for raw in _split_rows(match.group(1)):
        fields = _split_fields(raw)
        assert len(fields) == len(columns), (
            f"{table} 种子行字段数 {len(fields)} ≠ 列数 {len(columns)}（列序漂移即解析错位）: {raw[:120]}")
        rows.append(dict(zip(columns, fields)))
    return rows


def normalize_value(raw: str) -> str:
    """字面量归一化：去引号/去 jsonb 转型/布尔与 null 统一大写/数字去尾零。"""
    value = raw.strip()
    value = re.sub(r"::jsonb$", "", value, flags=re.I).strip()
    if value.upper() == "NULL":
        return "NULL"
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return str(float(value)).rstrip("0").rstrip(".") if "." in value else value
    return value.upper()


def normalize_routing_operations(raw: str) -> tuple:
    """`'["a","b"]'::jsonb` → ("a", "b")（顺序敏感：路线是有序序列）。"""
    inner = normalize_value(raw)
    return tuple(re.findall(r'"([^"]+)"', inner))


def key_of(operation_row: dict) -> str:
    return normalize_value(operation_row["name"])


# ── 夹具：Python 真值源 ──

@pytest.fixture(scope="module")
def python_catalog():
    sys.path.insert(0, str(ROUTING_PY_DIR))
    try:
        from app.production.routing import OPERATION_CATALOG, ROUTINGS
        return OPERATION_CATALOG, ROUTINGS
    finally:
        sys.path.pop(0)


@pytest.fixture(scope="module")
def v54_sql():
    assert V54.exists(), f"V54 种子迁移缺失：{V54}"
    return V54.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def schema_sql():
    return SCHEMA.read_text(encoding="utf-8")


# ── ① 迁移 ↔ Python 真值源 ──

def test_v54_matches_python_catalog(v54_sql, python_catalog):
    """V54 工序库种子逐行等于 routing.py OPERATION_CATALOG（名称/分组/单位/单价/标记）"""
    catalog, routings = python_catalog
    rows = parse_seed(v54_sql, "production_operations", OP_COLUMNS)
    assert rows, "V54 未解析到工序库种子行"

    assert [key_of(r) for r in rows] == list(catalog.keys()), (
        "工序名集合/顺序与 OPERATION_CATALOG 不一致（改名或加减工序必须同步 V54）")

    from app.production.routing import MUST_FINISH_OPS, START_MARKER_OPS
    for row in rows:
        name = key_of(row)
        meta = catalog[name]
        assert normalize_value(row["group_name"]) == meta["group"], f"{name} 分组漂移"
        assert normalize_value(row["unit"]) == meta["unit"], f"{name} 单位漂移"
        assert float(normalize_value(row["unit_price"])) == float(meta["unit_price"]), f"{name} 单价漂移"
        assert normalize_value(row["is_must_finish"]) == ("TRUE" if name in MUST_FINISH_OPS else "FALSE"), \
            f"{name} 必完标记漂移"
        assert normalize_value(row["is_start_marker"]) == ("TRUE" if name in START_MARKER_OPS else "FALSE"), \
            f"{name} 开始标记漂移"
        assert normalize_value(row["status"]) == "active"


def test_v54_routings_match_python(v54_sql, python_catalog):
    """V54 工艺路线种子逐条等于 ROUTINGS（部位×工艺 → 有序工序序列）"""
    catalog, routings = python_catalog
    rows = parse_seed(v54_sql, "production_routings", ROUTING_COLUMNS)
    assert len(rows) == len(routings), "路线条数与 ROUTINGS 不一致"

    parsed = {(normalize_value(r["curtain_type"]), normalize_value(r["craft"])):
              normalize_routing_operations(r["operations"]) for r in rows}
    expected = {key: tuple(ops) for key, ops in routings.items()}
    assert parsed == expected, "路线内容漂移（逐条比对 部位×工艺 → 工序序列）"
    # 布帘·韩褶 = 11 道实证走线（回归锚点，防整条路线被误删）
    assert len(parsed[("布帘", "韩褶")]) == 11


def test_routing_operations_exist_in_catalog(v54_sql):
    """路线里引用的每道工序都必须在工序库种子中（否则实例化时无单价/单位可依）"""
    catalog_names = {key_of(r) for r in parse_seed(v54_sql, "production_operations", OP_COLUMNS)}
    missing = []
    for row in parse_seed(v54_sql, "production_routings", ROUTING_COLUMNS):
        for operation in normalize_routing_operations(row["operations"]):
            if operation not in catalog_names:
                missing.append(operation)
    assert not missing, f"路线引用了工序库中不存在的工序：{sorted(set(missing))}"


# ── ② bootstrap（schema.sql）↔ 迁移 ──

def test_schema_sql_matches_v54(v54_sql, schema_sql):
    """docs/sql/schema.sql 的种子与 V54 逐行一致（bootstrap 路径不跑迁移链）"""
    for table, columns in (("production_operations", OP_COLUMNS),
                           ("production_routings", ROUTING_COLUMNS)):
        migration_rows = parse_seed(v54_sql, table, columns)
        schema_rows = parse_seed(schema_sql, table, columns)
        assert schema_rows, f"schema.sql 缺少 {table} 种子（全新库将无工序库，同 #3270 形态）"
        assert schema_rows == migration_rows, (
            f"{table} 种子在两源间漂移：schema.sql 与 V54 必须逐行一致")


# ── ③ 幂等性（MigrationRunner 约定：所有迁移可重复执行）──

def test_seed_sql_is_idempotent(v54_sql, schema_sql):
    """两条种子语句都必须带 ON CONFLICT DO NOTHING（冲突目标 = V49 部分唯一索引）"""
    for label, sql in (("V54", v54_sql), ("schema.sql", schema_sql)):
        for table in ("production_operations", "production_routings"):
            stmt = re.search(
                r"INSERT\s+INTO\s+" + table + r"\b.*?;", sql, re.S | re.I)
            assert stmt, f"{label} 缺少 {table} 的 INSERT 语句"
            body = stmt.group(0)
            assert re.search(r"ON\s+CONFLICT\s*\([^)]*\)\s*WHERE\s+deleted\s*=\s*0\s+DO\s+NOTHING",
                             body, re.I), (
                f"{label} 的 {table} 种子不再幂等（MigrationRunner 要求可重复执行）："
                f"需 `ON CONFLICT (...) WHERE deleted = 0 DO NOTHING`")


# ── ④ 解析器自证（防「仓库绿只是空跑」）──

def test_parser_detects_injected_drift():
    """注入式夹具：解析器必须**能**照出漂移（否则上面的绿是空断言）"""
    good = """
    INSERT INTO production_operations (id, tenant_id, name, group_name, position, unit, unit_price,
        is_must_finish, is_start_marker, sort_order, status) VALUES
      ('op-v54-01', 1, '精裁-布', '裁剪', '布帘', '米', 0.4, FALSE, TRUE, 1, 'active')
    ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;
    """
    bad = good.replace("0.4", "0.5")
    parsed_good = parse_seed(good, "production_operations", OP_COLUMNS)
    parsed_bad = parse_seed(bad, "production_operations", OP_COLUMNS)
    assert parsed_good and parsed_bad
    assert parsed_good != parsed_bad, "解析器读不出单价变化 ⇒ 本文件的比对是空断言"
    assert normalize_value(parsed_good[0]["unit_price"]) == "0.4"
    assert normalize_value(parsed_bad[0]["unit_price"]) == "0.5"
    # 幂等判据同样要能红
    assert re.search(r"ON\s+CONFLICT.*DO\s+NOTHING", good, re.I | re.S)
    assert not re.search(r"ON\s+CONFLICT.*DO\s+NOTHING", bad.replace(
        "ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;", ";"), re.I | re.S)