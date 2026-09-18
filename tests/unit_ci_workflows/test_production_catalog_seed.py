# case_ids: PG-018
"""工序库 / 工艺路线种子**多源**收敛守卫（issue #4116 P0-2；#4230 扩为多源）。

⚠️ 本文件的用例声明行**必须**在文件前 50 行内（`.github/growth_gate.py` 的
`extract_case_ids()` 只扫前 50 行），故它放在本 docstring **之前**（本 docstring 较长）。
⚠️ 正文里**不要**再出现「`case_ids` + 冒号」这种字面形态：`CASE_IDS_RE` 是全局 `search`，
第二处命中会**覆盖**第一处（实测：本文件曾因此在 QA Growth Gate 报「声明了不存在的用例 ID」）。

## 背景（取证事实）

`production_operations` / `production_routings` 自 V49 建表起**零种子、零消费者**
⇒ 商家无配置入口、库里无数据、§3 工艺路线在 DB 层不可查不可展示。
V54 落**初始种子**（把 `app/production/routing.py` 的既有确定性常量作为种子）
+ 只读消费者，并同步 `docs/sql/schema.sql`（bootstrap 路径不跑迁移链 ⇒ 不同步就是
「全新库无工序库」的静默缺口）。

## 为什么是「多源」（issue #4230，2026-09-18）

`MigrationRunner` 的台账 `schema_migrations` 按**文件名**记，**已应用的迁移整份跳过**
（`applied.contains(filename)` ⇒ `continue`）⇒ **已执行过的 V54 不能再改**（改了只对全新库生效，
存量环境永远拿不到 —— 「CI 绿但没生效」）。因此新增工序只能走**新迁移 V56**，
工序库的种子事实从此有**三个载体**：

| 源 | 角色 |
|---|---|
| `app/production/routing.py` `OPERATION_CATALOG` / `ROUTINGS` | **真值源**（确定性核心，M4-G-1） |
| `db/migration/V54__seed_production_operations.sql` | 存量库的**初始**种子（已发布 ⇒ 只增不改） |
| `db/migration/V56__seed_special_option_operations.sql` | 存量库的**增量**种子（#4230 的 5 道新工序） |
| `docs/sql/schema.sql` | 全新库 bootstrap 的**终态**种子（CI/本地 docker 栈**不跑迁移链**） |

⇒ 收敛判据 = **`V54 ∪ V56`（按名称取键）== `OPERATION_CATALOG`（逐行逐值）**，且
`schema.sql` 的工序集合与 `V54 ∪ V56` 的**名称 → 值**映射相等（`schema.sql` 是终态，
行内顺序按 `sort_order` 连续，与迁移侧「两段拼接」的行序天然不同 ⇒ 名称键比对，不依赖行序）。

## 漂移形态（本测试会让它变红；红证见文件尾 `TestGuardSelfProof`）

① 改了 Python 目录（改名/改价/加减工序）却没同步种子；② 迁移源与 bootstrap 源不一致
（bootstrap 库与迁移库工序库不同）；③ 路线里引用了工序库里不存在的工序名
（实例化时该道工序无单价/单位可依）；④ 种子 SQL 不再幂等（`ON CONFLICT` 丢失）。

⚠️ **可红性是底线**：下列比对一律**逐行逐值**（不是「包含即可」），故「改名/改价」仍能红。
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
# 工序库种子**按序**聚合（先初始、后增量）；新增工序迁移在此追加，改这里 = 显式登记新源
SEED_OPERATION_SQLS = (
    MIGRATION_DIR / "V54__seed_production_operations.sql",
    MIGRATION_DIR / "V56__seed_special_option_operations.sql",
)
# 路线模板仍只由 V54 落（#4230 不新增路线）
ROUTING_SQL = MIGRATION_DIR / "V54__seed_production_operations.sql"
SCHEMA = REPO / "docs/sql/schema.sql"
ROUTING_PY_DIR = REPO / "backend/ai-agent-service"

# 列序 = 种子 SQL 里 INSERT ... VALUES 的书写顺序（解析器按位取值）
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

    只认**第一条**该表的 INSERT（每个源文件各只有一条种子语句）。
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


def op_values(operation_row: dict) -> dict:
    """工序行的**逐值**口径（不含 id/sort_order：id 是各迁移自有的确定性命名、sort_order 是排序位）。

    含 `deleted` 之外的全部业务列 ⇒ 「改名/改价/改分组/改单位/改标记」任一都逃不掉。
    """
    return {col: normalize_value(operation_row[col])
            for col in ("group_name", "position", "unit", "unit_price",
                        "is_must_finish", "is_start_marker", "status")}


def by_name(rows):
    """[{列: 值}] → {工序名: 逐值 dict}（多源聚合的比对口径，不依赖跨文件行序）。"""
    return {key_of(r): op_values(r) for r in rows}


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
def seed_sqls():
    """[{路径: 文本}]——按 SEED_OPERATION_SQLS 顺序；文件缺失 **fail-closed**（不许静默少读一个源）。"""
    out = []
    for path in SEED_OPERATION_SQLS:
        assert path.exists(), f"工序库种子迁移缺失：{path}（多源聚合少了它 = 守卫空跑一半）"
        out.append((path.name, path.read_text(encoding="utf-8")))
    return out


@pytest.fixture(scope="module")
def routing_sql():
    assert ROUTING_SQL.exists(), f"路线种子迁移缺失：{ROUTING_SQL}"
    return ROUTING_SQL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def schema_sql():
    return SCHEMA.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def catalog_rows(seed_sqls):
    """工序库种子的**聚合**行（V54 → V56 顺序拼接，不去重：重名本身就该被下方判据照出来）。"""
    rows = []
    for name, sql in seed_sqls:
        rows += parse_seed(sql, "production_operations", OP_COLUMNS)
    return rows


# ── ① 迁移源（V54 ∪ V56）↔ Python 真值源 ──

def test_seed_matches_python_catalog(catalog_rows, python_catalog):
    """V54 ∪ V56 的工序库种子**逐行**等于 routing.py OPERATION_CATALOG（名称/分组/单位/单价/标记）。

    行序判据：**必须**相等（真值源是字典序，增删工序要落在此序上）；多源 ⇒ 拼接顺序即序号顺序。
    """
    catalog, _ = python_catalog
    assert catalog_rows, "未解析到工序库种子行"

    assert [key_of(r) for r in catalog_rows] == list(catalog.keys()), (
        "工序名集合/顺序与 OPERATION_CATALOG 不一致（改名或加减工序必须同步 V54/V56 种子）")

    from app.production.routing import MUST_FINISH_OPS, START_MARKER_OPS
    for row in catalog_rows:
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


def test_seed_has_no_duplicate_operation_names(catalog_rows):
    """多源聚合不得出现重名工序（V56 与 V54 撞名 ⇒ 两条口径并存，比缺项更隐蔽）。"""
    names = [key_of(r) for r in catalog_rows]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    assert duplicates == [], f"种子重名工序（后一条会被 ON CONFLICT 静默吞掉）: {duplicates}"


def test_routing_operations_exist_in_seed(catalog_rows, routing_sql):
    """路线里引用的每道工序都必须在**聚合后的**工序库种子中（否则实例化时无单价/单位可依）"""
    catalog_names = {key_of(r) for r in catalog_rows}
    missing = []
    for row in parse_seed(routing_sql, "production_routings", ROUTING_COLUMNS):
        for operation in normalize_routing_operations(row["operations"]):
            if operation not in catalog_names:
                missing.append(operation)
    assert not missing, f"路线引用了工序库中不存在的工序：{sorted(set(missing))}"


def test_routings_match_python(routing_sql, python_catalog):
    """V54 工艺路线种子逐条等于 ROUTINGS（部位×工艺 → 有序工序序列）"""
    _, routings = python_catalog
    rows = parse_seed(routing_sql, "production_routings", ROUTING_COLUMNS)
    assert len(rows) == len(routings), "路线条数与 ROUTINGS 不一致"

    parsed = {(normalize_value(r["curtain_type"]), normalize_value(r["craft"])):
              normalize_routing_operations(r["operations"]) for r in rows}
    expected = {key: tuple(ops) for key, ops in routings.items()}
    assert parsed == expected, "路线内容漂移（逐条比对 部位×工艺 → 工序序列）"
    # 布帘·韩褶 = 11 道实证走线（回归锚点，防整条路线被误删）
    assert len(parsed[("布帘", "韩褶")]) == 11


# ── ② bootstrap（schema.sql）↔ 迁移源聚合 ──

def test_schema_sql_matches_seed_sources(catalog_rows, routing_sql, schema_sql):
    """docs/sql/schema.sql 的种子与 V54 ∪ V56 一致（bootstrap 路径不跑迁移链）。

    比对口径 = **名称 → 逐值**（`schema.sql` 是终态、行内按 sort_order 连续；迁移侧是两段拼接
    ⇒ 跨文件行序本来不同，故不比对行序，但**每个值逐个比** —— 改名/改价/改标记照样红）。
    另比对 `sort_order`：bootstrap 的连续序号必须是 `1..N` 的**严格递增**序列（漏排/重排即红）。
    """
    schema_ops = parse_seed(schema_sql, "production_operations", OP_COLUMNS)
    assert schema_ops, "schema.sql 缺少 production_operations 种子（全新库将无工序库，同 #3270 形态）"
    assert by_name(schema_ops) == by_name(catalog_rows), (
        f"production_operations 种子在迁移源与 bootstrap 源间漂移："
        f"{_diff_keys(by_name(schema_ops), by_name(catalog_rows))}")
    assert [int(normalize_value(r["sort_order"])) for r in schema_ops] == \
        list(range(1, len(schema_ops) + 1)), "schema.sql 的 sort_order 不是 1..N 连续序列"

    # 路线种子：两源逐行一致（schema.sql 与 V54 同款单条 INSERT，行序可比）
    assert parse_seed(schema_sql, "production_routings", ROUTING_COLUMNS) == \
        parse_seed(routing_sql, "production_routings", ROUTING_COLUMNS), \
        "production_routings 种子在两源间漂移：schema.sql 与 V54 必须逐行一致"


def _diff_keys(left: dict, right: dict) -> str:
    """两侧 dict 的差异摘要（红的时候点名，别只给一句 assert）。"""
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    changed = sorted(k for k in set(left) & set(right) if left[k] != right[k])
    return f"仅 bootstrap 有={only_left} 仅迁移源有={only_right} 值不同={changed}"


def test_every_seed_source_contributes_to_the_aggregate(seed_sqls):
    """多源自证：**每个**种子源的工序都被聚合读到（含 V56 的 5 道新工序）。

    反例（本测试要挡的形态）：聚合退化成只读 V54 ⇒ V56 从未被行使 ⇒ #4230 的新工序
    既不在守卫射程内、又不会被任何断言照出来。
    """
    per_source = {name: {key_of(r) for r in parse_seed(sql, "production_operations", OP_COLUMNS)}
                  for name, sql in seed_sqls}
    for name, names in per_source.items():
        assert names, f"{name} 未解析到任何工序行（该源等于没被读）"
    assert len(per_source) >= 2, "工序库种子只剩一个源（#4230 的多源口径失效）"
    assert {"绑带-纱", "logo条-布", "立边-布", "扣环-布", "防翘扣-布"} <= \
        per_source["V56__seed_special_option_operations.sql"], (
        "#4230 的 5 道新工序必须由 V56 贡献（少一个 ⇒ 实例化取不到工序 ⇒ fail-closed）")


# ── ③ 幂等性（MigrationRunner 约定：所有迁移可重复执行）──

def test_seed_sql_is_idempotent(seed_sqls, routing_sql, schema_sql):
    """每条种子语句都必须带 ON CONFLICT DO NOTHING（冲突目标 = V49 部分唯一索引）"""
    sources = [(name, sql) for name, sql in seed_sqls] + [("schema.sql", schema_sql)]
    for label, sql in sources:
        for table in ("production_operations", "production_routings"):
            stmt = re.search(
                r"INSERT\s+INTO\s+" + table + r"\b.*?;", sql, re.S | re.I)
            if not stmt:
                # 没有该表的 INSERT 是合法的（V56 只种工序、不种路线）——但**必须**真的没有
                assert table not in sql or "INSERT INTO " + table not in sql
                continue
            body = stmt.group(0)
            assert re.search(r"ON\s+CONFLICT\s*\([^)]*\)\s*WHERE\s+deleted\s*=\s*0\s+DO\s+NOTHING",
                             body, re.I), (
                f"{label} 的 {table} 种子不再幂等（MigrationRunner 要求可重复执行）："
                f"需 `ON CONFLICT (...) WHERE deleted = 0 DO NOTHING`")


def test_price_version_backfill_is_idempotent(seed_sqls):
    """#4230：V56 必须补新工序的单价版本行，且**重复执行不产生第二行**（V55 口径：当前价=最新版本行）。"""
    v56 = dict(seed_sqls).get("V56__seed_special_option_operations.sql")
    assert v56, "V56 迁移缺失（#4230 的新工序种子）"
    assert "production_operation_price_versions" in v56, (
        "V56 没补单价版本行 ⇒ 新工序在「当前价 = 最新版本行」口径下没有价")
    backfill = re.search(
        r"INSERT\s+INTO\s+production_operation_price_versions\b.*?;", v56, re.S | re.I)
    assert backfill, "V56 缺少单价版本回填语句"
    assert re.search(r"NOT\s+EXISTS", backfill.group(0), re.I), (
        "V56 的版本回填没有 NOT EXISTS 守卫 ⇒ 重复执行会插出第二行（最新版本歧义）")


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
    # 多源**聚合**口径同样要能红：注入一条与真值源不一致的行 ⇒ 键集/值比对必须不等
    assert by_name(parsed_good) != by_name(parsed_bad), "多源聚合比对读不出值漂移"
