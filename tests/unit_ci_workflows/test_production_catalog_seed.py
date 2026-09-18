# case_ids: PG-018
"""工序库 / 工艺路线种子**多源**收敛守卫（issue #4116 P0-2；#4230 扩为多源）。

⚠️ 本文件的用例声明行**必须**在文件前 50 行内（`.github/growth_gate.py` 的
`extract_case_ids()` 只扫前 50 行），故它放在本 docstring **之前**（本 docstring 较长）。
✅ 正文里出现「`case_ids` + 冒号」这种字面形态**已无害**（#4239 起 `extract_case_ids()` 只认
注释起始的声明行、且取首个命中即停）。旧实现是全局 `search` 累积，本文件曾因此报「声明了不存在的用例 ID」。

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
| `db/migration/V58__seed_sheer_curtain_routings.sql` | 存量库的**增量**路线种子（#4246 的 3 条纱帘路线，**零新造工序** ⇒ 只种路线） |
| `docs/sql/schema.sql` | 全新库 bootstrap 的**终态**种子（CI/本地 docker 栈**不跑迁移链**） |

## 判据 1（issue #4235）：种子源**按集合聚合**，不再写死文件名

上面那张表里的文件名**不再出现在「种子源集合」的定义里** —— `SEED_OPERATION_SQLS` /
`ROUTING_SEED_SQLS` 由 `seed_sources_for(table)` **按内容发现**：凡含
`INSERT INTO <table>` 的 `db/migration/V*.sql` 即被纳入（按版本号数值序）。

⇒ 新增种子迁移（`V<下一个空闲号>__...sql`）**无需改本文件**即进入比对射程
（此前必须改 `V54 = REPO / ".../V54__seed_production_operations.sql"` 这类写死的单源，
而"改 V54"正是那个静默失效）。**为什么不按命名约定 `V*__seed_*.sql`**：`V28` / `V30` / `V40`
也是 `__seed_` 但对工序库零贡献（按名取集合会把它们收进来 ⇒ 下方「每个源都必须有行」的
自证断言恒红），域过滤最终仍得回到**内容**。自证见
`test_seed_source_discovery_is_by_content`（临时目录夹具，不依赖仓库当下恰好有什么）。

⚠️ **不是「包含即可」**：聚合后仍是**逐行逐值**比对（下方四条红线全部保留、逐个有红证）。

⇒ 收敛判据 = **`V54 ∪ V56`（按名称取键）== `OPERATION_CATALOG`（逐行逐值）**，且
**`V54 ∪ V58`（按 部位×工艺 取键）== `ROUTINGS`（逐条有序序列）**；`schema.sql` 的工序集合与
`V54 ∪ V56` 的**名称 → 值**映射相等、路线集合与 `V54 ∪ V58` **逐行**相等（`schema.sql` 是终态，
工序行内顺序按 `sort_order` 连续，与迁移侧「两段拼接」的行序天然不同 ⇒ 工序按名称键比对、
不依赖行序；路线侧 schema.sql 里同一条 INSERT 按 `V54 行 → V58 行` 顺序书写 ⇒ 行序可比）。

## 漂移形态（本测试会让它变红；红证见文件尾 `test_parser_detects_injected_drift` /
`test_routing_parser_detects_injected_drift`，注入式自证）

① 改了 Python 目录（改名/改价/加减工序）却没同步种子；② 迁移源与 bootstrap 源不一致
（bootstrap 库与迁移库工序库不同）；③ 路线里引用了工序库里不存在的工序名
（实例化时该道工序无单价/单位可依）；④ 种子 SQL 不再幂等（`ON CONFLICT` 丢失）。

⚠️ **可红性是底线**：下列比对一律**逐行逐值**（不是「包含即可」），故「改名/改价」仍能红。
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
MIGRATION_GLOB = "V*.sql"
_VERSION_RE = re.compile(r"^V(\d+)__")
# 第五源（issue #4361）：开租自动套用的生产模板目录（jar 内资产，Java 侧真会读它）
TEMPLATES_ROOT = REPO / "backend/admin-api/src/main/resources/production-templates"
TEMPLATE_INDEX = TEMPLATES_ROOT / "index.json"
TEMPLATE_SEED = TEMPLATES_ROOT / "curtain/seed.json"


def version_key(name: str):
    """迁移文件名 → 排序键（`MigrationRunner` 同款：版本号**数值**序，不是字典序）。"""
    base = Path(name).name
    match = _VERSION_RE.match(base)
    return (int(match.group(1)) if match else 1 << 30, base)


def seed_sources_for(table: str, migration_dir: Path = MIGRATION_DIR) -> tuple:
    """**按内容**发现某个表的种子源迁移（判据 1，issue #4235）。

    判据 = 「文件里有 `INSERT INTO <table>`」⇒ 新增种子迁移**无需改本文件**即被纳入；
    取 `(路径,)` 时按版本号**数值序**（先初始、后增量 ⇒ 聚合行序 = 序号顺序，与真值源字典序可比）。
    空集不是合法的"恰好没有" —— 由 `seed_sqls` / `routing_sqls` 夹具 fail-closed 拦下。
    """
    directory = Path(migration_dir)
    pattern = re.compile(r"INSERT\s+INTO\s+" + table + r"\b", re.I)
    found = [p for p in sorted(directory.glob(MIGRATION_GLOB), key=lambda p: version_key(p.name))
             if pattern.search(p.read_text(encoding="utf-8"))]
    return tuple(found)


# 工序库 / 路线种子源：**按集合聚合**（判据 1）——新增种子迁移无需在此追加任何东西。
SEED_OPERATION_SQLS = seed_sources_for("production_operations")
ROUTING_SEED_SQLS = seed_sources_for("production_routings")
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
    """[(路径名, 文本)]——按内容发现的工序库种子源（版本号序）；空集/文件缺失 **fail-closed**。"""
    assert SEED_OPERATION_SQLS, (
        "未发现任何工序库种子源（`INSERT INTO production_operations` 一个都扫不到）"
        "⇒ 本守卫会退化成空跑；判据 1 的按集合聚合失效")
    out = []
    for path in SEED_OPERATION_SQLS:
        assert path.exists(), f"工序库种子迁移缺失：{path}（多源聚合少了它 = 守卫空跑一半）"
        out.append((path.name, path.read_text(encoding="utf-8")))
    return out


@pytest.fixture(scope="module")
def routing_sqls():
    """[(路径名, 文本)]——按内容发现的路线种子源（版本号序）；空集/文件缺失 **fail-closed**。"""
    assert ROUTING_SEED_SQLS, (
        "未发现任何路线种子源（`INSERT INTO production_routings` 一个都扫不到）"
        "⇒ 本守卫会退化成空跑；判据 1 的按集合聚合失效")
    out = []
    for path in ROUTING_SEED_SQLS:
        assert path.exists(), f"路线种子迁移缺失：{path}（多源聚合少了它 = 守卫空跑一半）"
        out.append((path.name, path.read_text(encoding="utf-8")))
    return out


@pytest.fixture(scope="module")
def schema_sql():
    return SCHEMA.read_text(encoding="utf-8")


# ── 第五源（issue #4361）：生产模板目录 ──

@pytest.fixture(scope="module")
def template_json():
    """`production-templates/curtain/seed.json` 的解析结果；**文件/索引缺席即 fail-closed**。

    自证（本单验收判据「守卫要自证每个源都真被读到」）：源文件不存在时**报红**，
    不是静默跳过 —— 静默跳过会让「模板漂移」这个新面在守卫里等于不存在（正是 #4235 的形态）。
    """
    assert TEMPLATE_INDEX.exists(), f"生产模板索引缺失：{TEMPLATE_INDEX}"
    assert TEMPLATE_SEED.exists(), (
        f"生产种子模板缺失：{TEMPLATE_SEED}"
        "⇒ 开租自动套用会静默空库；本守卫的第五源退化成空跑")
    index = json.loads(TEMPLATE_INDEX.read_text(encoding="utf-8"))
    entries = index.get("templates", [])
    assert entries, "生产模板索引为空（`templates` 数组一个都没有）"
    entry = next((t for t in entries if t.get("templateId") == "curtain"), None)
    assert entry is not None, "生产模板索引缺少 curtain 条目"
    # 索引里的 file 必须真的指向本夹具读的那个文件（防索引指东、守卫读西）
    assert (TEMPLATES_ROOT / entry["file"]).resolve() == TEMPLATE_SEED.resolve(), (
        f"索引指向 {entry['file']}，而守卫读的是 {TEMPLATE_SEED.name} ⇒ 两个源不是同一个")
    return json.loads(TEMPLATE_SEED.read_text(encoding="utf-8"))


def template_operations(template: dict) -> list:
    """模板工序 → 种子行形态（列名与 `OP_COLUMNS` 对齐，供 `by_name` 直接复用）。"""
    return [{"id": o["id"], "name": o["name"], "group_name": o["group"],
             "position": "NULL" if o.get("position") is None else o["position"],
             "unit": o["unit"], "unit_price": str(o["unit_price"]),
             "is_must_finish": "TRUE" if o["is_must_finish"] else "FALSE",
             "is_start_marker": "TRUE" if o["is_start_marker"] else "FALSE",
             "sort_order": str(o["sort_order"]), "status": o["status"]}
            for o in template["operations"]]


def template_routings(template: dict) -> list:
    """模板路线 → 种子行形态（列名与 `ROUTING_COLUMNS` 对齐，供逐行比对复用）。"""
    return [{"id": r["id"], "curtain_type": r["curtain_type"], "craft": r["craft"],
             "operations": json.dumps(r["operations"], ensure_ascii=False), "status": r["status"]}
            for r in template["routings"]]


@pytest.fixture(scope="module")
def catalog_rows(seed_sqls):
    """工序库种子的**聚合**行（V54 → V56 顺序拼接，不去重：重名本身就该被下方判据照出来）。"""
    rows = []
    for name, sql in seed_sqls:
        rows += parse_seed(sql, "production_operations", OP_COLUMNS)
    return rows


@pytest.fixture(scope="module")
def routing_rows(routing_sqls):
    """路线种子的**聚合**行（V54 → V58 顺序拼接；行序即「既有 6 条 + 新增 3 条」）。"""
    rows = []
    for name, sql in routing_sqls:
        rows += parse_seed(sql, "production_routings", ROUTING_COLUMNS)
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


def test_routing_operations_exist_in_seed(catalog_rows, routing_rows):
    """路线里引用的每道工序都必须在**聚合后的**工序库种子中（否则实例化时无单价/单位可依）"""
    catalog_names = {key_of(r) for r in catalog_rows}
    missing = []
    for row in routing_rows:
        for operation in normalize_routing_operations(row["operations"]):
            if operation not in catalog_names:
                missing.append(operation)
    assert not missing, f"路线引用了工序库中不存在的工序：{sorted(set(missing))}"


def test_routings_match_python(routing_rows, python_catalog):
    """V54 ∪ V58 工艺路线种子逐条等于 ROUTINGS（部位×工艺 → 有序工序序列）"""
    _, routings = python_catalog
    rows = routing_rows
    assert len(rows) == len(routings), "路线条数与 ROUTINGS 不一致"

    parsed = {(normalize_value(r["curtain_type"]), normalize_value(r["craft"])):
              normalize_routing_operations(r["operations"]) for r in rows}
    expected = {key: tuple(ops) for key, ops in routings.items()}
    assert parsed == expected, "路线内容漂移（逐条比对 部位×工艺 → 工序序列）"
    # 布帘·韩褶 = 11 道实证走线（回归锚点，防整条路线被误删）
    assert len(parsed[("布帘", "韩褶")]) == 11
    # #4246 新增的 3 条纱帘路线（逐字钉死 —— 它们此前**不存在** ⇒ 派生键回落布帘路线）
    assert parsed[("纱帘", "打孔")] == ("精裁-纱", "纱三边", "打孔-纱",
                                        "外帘打卷", "外帘装袋", "外帘发货")
    assert parsed[("纱帘", "四爪钩")] == ("精裁-纱", "纱三边", "上车布-纱",
                                          "外帘打卷", "外帘装袋", "外帘发货")
    assert parsed[("纱帘", "穿杆")] == ("精裁-纱", "纱三边",
                                        "外帘打卷", "外帘装袋", "外帘发货")


# ── ② bootstrap（schema.sql）↔ 迁移源聚合 ──

def test_schema_sql_matches_seed_sources(catalog_rows, routing_rows, schema_sql):
    """docs/sql/schema.sql 的种子与 V54 ∪ V56（工序）/ V54 ∪ V58（路线）一致。

    比对口径 = **名称 → 逐值**（`schema.sql` 是终态、工序行内按 sort_order 连续；迁移侧是两段拼接
    ⇒ 跨文件行序本来不同，故工序不比对行序，但**每个值逐个比** —— 改名/改价/改标记照样红）。
    另比对 `sort_order`：bootstrap 的连续序号必须是 `1..N` 的**严格递增**序列（漏排/重排即红）。
    """
    schema_ops = parse_seed(schema_sql, "production_operations", OP_COLUMNS)
    assert schema_ops, "schema.sql 缺少 production_operations 种子（全新库将无工序库，同 #3270 形态）"
    assert by_name(schema_ops) == by_name(catalog_rows), (
        f"production_operations 种子在迁移源与 bootstrap 源间漂移："
        f"{_diff_keys(by_name(schema_ops), by_name(catalog_rows))}")
    assert [int(normalize_value(r["sort_order"])) for r in schema_ops] == \
        list(range(1, len(schema_ops) + 1)), "schema.sql 的 sort_order 不是 1..N 连续序列"

    # 路线种子：bootstrap 的**同一条 INSERT** 里按 V54 行 → V58 行顺序书写 ⇒ 与聚合行序可比、逐行一致
    assert parse_seed(schema_sql, "production_routings", ROUTING_COLUMNS) == routing_rows, \
        "production_routings 种子在两源间漂移：schema.sql 必须逐行等于 V54 ∪ V58（含 #4246 的 3 条纱帘路线）"


def _diff_keys(left: dict, right: dict) -> str:
    """两侧 dict 的差异摘要（红的时候点名，别只给一句 assert）。"""
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    changed = sorted(k for k in set(left) & set(right) if left[k] != right[k])
    return f"仅 bootstrap 有={only_left} 仅迁移源有={only_right} 值不同={changed}"


# ── ⑤ 第五源（issue #4361）：生产模板目录 ↔ Python 真值源 / 迁移源 / bootstrap ──
#
# 为什么必须扩源：模板 JSON 是**开租自动套用**的唯一输入（新租户的工序库/路线库由它生成）
# ⇒ 它一旦与真值源漂移，**每个新租户**都拿到错的工序与单价，而旧租户看不出来
# ⇒ 新增一个静默漂移面（#4235 的形态）。四源变五源，逐行逐值比对。

def test_template_matches_python_catalog(template_json, catalog_rows, python_catalog):
    """模板工序 ↔ `OPERATION_CATALOG`（名称/分组/单位/单价/必完/开始标记）逐值相等。

    行序也钉：模板的 `sort_order` 必须是 1..N 连续，且名称序 == 真值源字典序
    （模板就是按真值源字典序写的，漂移即红）。
    """
    catalog, _ = python_catalog
    rows = template_operations(template_json)
    assert rows, "模板未解析到任何工序"

    assert [key_of(r) for r in rows] == list(catalog.keys()), (
        "模板工序名集合/顺序与 OPERATION_CATALOG 不一致（改名或加减工序必须同步模板）")
    assert by_name(rows) == by_name(catalog_rows), (
        f"模板工序与迁移种子漂移：{_diff_keys(by_name(rows), by_name(catalog_rows))}")
    assert [int(normalize_value(r["sort_order"])) for r in rows] == list(range(1, len(rows) + 1)), \
        "模板的 sort_order 不是 1..N 连续序列"


def test_template_matches_python_routings(template_json, routing_rows, python_catalog):
    """模板路线 ↔ `ROUTINGS`（部位×工艺 → 有序工序序列）逐条相等，且逐行等于迁移聚合。"""
    _, routings = python_catalog
    rows = template_routings(template_json)
    parsed = {(normalize_value(r["curtain_type"]), normalize_value(r["craft"])):
              normalize_routing_operations(r["operations"]) for r in rows}
    expected = {key: tuple(ops) for key, ops in routings.items()}
    assert parsed == expected, "模板路线内容漂移（逐条比对 部位×工艺 → 工序序列）"
    assert rows == routing_rows, (
        f"模板路线与迁移种子漂移（逐行，含 id/status）：{_diff_keys(parsed, expected)}")


def test_template_operations_and_routings_exist_in_catalog(template_json, catalog_rows):
    """模板路线引用的每道工序都必须在**聚合后的**工序库种子中（否则套用后实例化无单价可依）。"""
    catalog_names = {key_of(r) for r in catalog_rows}
    missing = [op for r in template_routings(template_json)
               for op in normalize_routing_operations(r["operations"]) if op not in catalog_names]
    assert not missing, f"模板路线引用了工序库中不存在的工序：{sorted(set(missing))}"


def test_template_sources_are_the_frozen_provenance_mapping(template_json, catalog_rows, routing_rows):
    """模板每行的 `source` 必须逐条等于**冻结映射**（issue #4361 交付物 4，双向断言）。

    冻结映射：`op-v54-*`/`rt-v54-*` = `占位待确认`；`op-v56-*`/`rt-v58-*` = `推算`；
    `实证` = **空集**（客户确认 #4261/#4343 后才会有 —— 这是诚实结论，不是遗漏）。

    双向：漏标（某行 source 缺失/为空）与多标（出现 `实证`）**都红**。
    与 V62 迁移的回填同口径由 `ProductionSourceProvenanceMigrationTest` 另行钉（Java 侧）。
    """
    for entry in template_json["operations"]:
        expected = "占位待确认" if entry["id"].startswith("op-v54-") else "推算"
        assert entry.get("source") == expected, (
            f"工序 {entry['name']} 的 source={entry.get('source')!r}，冻结映射要求 {expected!r}")
    for entry in template_json["routings"]:
        expected = "占位待确认" if entry["id"].startswith("rt-v54-") else "推算"
        assert entry.get("source") == expected, (
            f"路线 {entry['curtain_type']}×{entry['craft']} 的 source={entry.get('source')!r}，"
            f"冻结映射要求 {expected!r}")

    sources = {e["source"] for e in template_json["operations"]} \
        | {e["source"] for e in template_json["routings"]}
    assert sources == {"占位待确认", "推算"}, (
        f"模板 source 取值集合 = {sorted(sources)}，冻结映射要求恰好 {{占位待确认, 推算}}"
        "（出现「实证」= 多标：今天没有任何工序/路线够得上实证，#4343 已证明 布帘×韩褶 与客户真实加工单不符）")
    assert sum(1 for e in template_json["operations"] if e["source"] == "占位待确认") == 30
    assert sum(1 for e in template_json["operations"] if e["source"] == "推算") == 5
    assert sum(1 for e in template_json["routings"] if e["source"] == "占位待确认") == 6
    assert sum(1 for e in template_json["routings"] if e["source"] == "推算") == 3


def test_template_carries_special_option_mappings_and_factors(template_json):
    """模板必须自带「特殊选项 → 条件工序」16 项 + 「选项 → 计件系数」——逐条等于真值源。

    少了这两块，套用出来的租户**有工序没条件工序**（勾了「加花边」不加花边-布）⇒
    计件工资少算，而界面看不出缺什么。
    """
    sys.path.insert(0, str(ROUTING_PY_DIR))
    try:
        from app.production.routing import OPTION_FACTOR_SCOPES, SPECIAL_OPTION_ROUTINGS
    finally:
        sys.path.pop(0)

    got_routings = {e["option_name"]: (e["operation_name"], e["after_operation"])
                    for e in template_json["option_routings"]}
    want_routings = {opt: (spec["operation"], spec["after"])
                     for opt, spec in SPECIAL_OPTION_ROUTINGS.items()}
    assert got_routings == want_routings, (
        f"模板的条件工序映射与 SPECIAL_OPTION_ROUTINGS 漂移：{_diff_keys(got_routings, want_routings)}")
    assert len(template_json["option_routings"]) == 16

    got_factors = {(e["option_name"], e["operation_name"]): float(e["factor"])
                   for e in template_json["option_factors"]}
    want_factors = {(opt, sc["operation_name"]): float(sc["factor"])
                    for opt, scopes in OPTION_FACTOR_SCOPES.items() for sc in scopes}
    assert got_factors == want_factors, (
        f"模板的计件系数与 OPTION_FACTOR_SCOPES 漂移：{_diff_keys(got_factors, want_factors)}")


def test_every_template_source_is_really_read(template_json):
    """第五源自证（本单验收判据「守卫要自证每个源都真被读到」）：模板三块都非空且真被解析。

    反例（本测试要挡的形态）：`template_json` 夹具静默返回 `{}`（文件缺失时 except 掉）
    ⇒ 上面四条比对全部退化成空跑。**源缺席 ⇒ fail-closed** 由夹具的 assert 承担，
    本条再钉一次「解析出来确实有东西」。
    """
    assert template_json.get("templateId") == "curtain"
    assert len(template_json["operations"]) == 35, "模板工序数不是 35（漏读或漏写）"
    assert len(template_json["routings"]) == 9, "模板路线数不是 9"
    assert len(template_json["option_routings"]) == 16
    assert len(template_json["option_factors"]) >= 1
    # 每块都必须真带业务值（不是占位空壳）
    assert all(o["name"] and o["unit"] for o in template_json["operations"])
    assert all(r["operations"] for r in template_json["routings"])


def test_template_source_absent_fails_closed(tmp_path, monkeypatch):
    """注入式自证：**把模板文件挪走 ⇒ 守卫必须红**（不是静默跳过）。

    这是本单「五源自证」的机械判据：源缺席时若守卫仍然绿，说明它读的根本不是这个文件。
    """
    monkeypatch.setattr(
        sys.modules[__name__], "TEMPLATE_SEED", tmp_path / "curtain/seed.json")
    monkeypatch.setattr(
        sys.modules[__name__], "TEMPLATE_INDEX", tmp_path / "index.json")
    with pytest.raises(AssertionError):
        template_json.__wrapped__()


def test_template_drift_is_detected(template_json):
    """注入式自证：改模板里一个字（单价/工序名/source）⇒ 比对必须不等（否则五源守卫是空断言）。"""
    import copy
    drifted_price = copy.deepcopy(template_json)
    drifted_price["operations"][0]["unit_price"] = 9.99
    assert by_name(template_operations(drifted_price)) != by_name(template_operations(template_json)), \
        "改模板单价读不出来 ⇒ 模板↔迁移的比对是空断言"

    drifted_name = copy.deepcopy(template_json)
    drifted_name["routings"][0]["operations"][0] = "不存在的工序"
    assert normalize_routing_operations(
        template_routings(drifted_name)[0]["operations"]) != \
        normalize_routing_operations(template_routings(template_json)[0]["operations"]), \
        "改模板路线序列读不出来 ⇒ 路线比对是空断言"

    drifted_source = copy.deepcopy(template_json)
    drifted_source["operations"][0]["source"] = "实证"
    assert drifted_source["operations"][0]["source"] != template_json["operations"][0]["source"], \
        "改模板 source 读不出来 ⇒ provenance 比对是空断言"


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


def test_every_routing_source_contributes_to_the_aggregate(routing_sqls):
    """路线多源自证：**每个**路线源的路线都被聚合读到（含 V58 的 3 条纱帘路线）。

    反例（本测试要挡的形态）：聚合退化成只读 V54 ⇒ V58 从未被行使 ⇒ #4246 的 3 条纱帘路线
    既不在守卫射程内、又不会被任何断言照出来（「绿了但没生效」）。
    """
    per_source = {name: {(normalize_value(r["curtain_type"]), normalize_value(r["craft"]))
                         for r in parse_seed(sql, "production_routings", ROUTING_COLUMNS)}
                  for name, sql in routing_sqls}
    for name, keys in per_source.items():
        assert keys, f"{name} 未解析到任何路线行（该源等于没被读）"
    assert len(per_source) >= 2, "路线种子只剩一个源（#4246 的多源口径失效）"
    assert {("纱帘", "打孔"), ("纱帘", "四爪钩"), ("纱帘", "穿杆")} <= \
        per_source["V58__seed_sheer_curtain_routings.sql"], (
        "#4246 的 3 条纱帘路线必须由 V58 贡献（少一条 ⇒ 派生键回落布帘×韩褶 ⇒ 工序与工资全错）")
    assert ("纱帘", "韩褶") in per_source["V54__seed_production_operations.sql"], (
        "V54 的既有 6 条路线必须仍由 V54 贡献（V58 只做增量，不改 V54）")


# ── ③ 幂等性（MigrationRunner 约定：所有迁移可重复执行）──

def test_seed_sql_is_idempotent(seed_sqls, routing_sqls, schema_sql):
    """每条种子语句都必须带 ON CONFLICT DO NOTHING（冲突目标 = V49 部分唯一索引）"""
    sources = [(name, sql) for name, sql in seed_sqls] \
        + [(name, sql) for name, sql in routing_sqls if (name, sql) not in seed_sqls] \
        + [("schema.sql", schema_sql)]
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


# ── ④ 判据 1 自证：种子源发现**按内容**（新增迁移无需改本文件）──

def test_seed_source_discovery_is_by_content(tmp_path):
    """判据 1 自证：新种子文件**不改本文件**即被发现；无关 `__seed_` 文件不被误收。

    反例（本测试要挡的形态）：发现退化成**文件名白名单** ⇒ 新种子迁移永远不在射程内
    （"新增种子迁移 = 守卫红" 的老病，issue #4235 判据 1）；
    或按 `V*__seed_*.sql` 命名约定取集合 ⇒ `V28/V30/V40` 被误收 ⇒ 「每个源都必须有行」恒红。
    """
    (tmp_path / "V54__seed_production_operations.sql").write_text(
        "INSERT INTO production_operations (id) VALUES ('op-54');", encoding="utf-8")
    # 名字里**没有** seed（内容发现 vs 命名约定的差别）
    (tmp_path / "V60__whatever_new_ops.sql").write_text(
        "INSERT INTO production_operations (id) VALUES ('op-60');", encoding="utf-8")
    # 是 `__seed_` 但零贡献（按名取集合会误收）
    (tmp_path / "V28__seed_notification_templates_and_rules.sql").write_text(
        "INSERT INTO notification_templates (id) VALUES ('nt-28');", encoding="utf-8")
    # 只种路线的文件不该进工序库集合
    (tmp_path / "V58__seed_sheer_curtain_routings.sql").write_text(
        "INSERT INTO production_routings (id) VALUES ('rt-58');", encoding="utf-8")

    assert [p.name for p in seed_sources_for("production_operations", tmp_path)] == [
        "V54__seed_production_operations.sql", "V60__whatever_new_ops.sql"], \
        "工序库种子源发现不是「按内容 + 版本号数值序」⇒ 新增种子迁移不会被纳入比对"
    assert [p.name for p in seed_sources_for("production_routings", tmp_path)] == [
        "V58__seed_sheer_curtain_routings.sql"], "路线种子源发现把无贡献的文件收了进来"


# ── ⑤ 解析器自证（防「仓库绿只是空跑」）──

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


def test_routing_parser_detects_injected_drift():
    """路线侧注入式自证（#4246）：聚合比对必须照得出「路线序列被改」「引用不存在的工序」「不幂等」。

    否则 `test_routings_match_python` / `test_routing_operations_exist_in_seed` /
    `test_seed_sql_is_idempotent` 的绿就是**空跑**。
    """
    good = """
    INSERT INTO production_routings (id, tenant_id, curtain_type, craft, operations, status) VALUES
      ('rt-v58-01', 1, '纱帘', '打孔',
       '["精裁-纱","纱三边","打孔-纱","外帘打卷","外帘装袋","外帘发货"]'::jsonb, 'active')
    ON CONFLICT (tenant_id, curtain_type, craft) WHERE deleted = 0 DO NOTHING;
    """
    # ① 序列被改（打孔-纱 → 打孔-布）= 「改了 Python 目录却不同步种子」/「两源不一致」的形态
    drifted = good.replace("打孔-纱", "打孔-布")
    # ② 引用不存在的工序
    bogus = good.replace("打孔-纱", "打孔-不存在")
    # ③ 不幂等（ON CONFLICT 丢失）
    non_idempotent = good.replace(
        "ON CONFLICT (tenant_id, curtain_type, craft) WHERE deleted = 0 DO NOTHING;", ";")

    rows_good = parse_seed(good, "production_routings", ROUTING_COLUMNS)
    rows_drifted = parse_seed(drifted, "production_routings", ROUTING_COLUMNS)
    assert rows_good and rows_drifted
    assert normalize_routing_operations(rows_good[0]["operations"]) == \
        ("精裁-纱", "纱三边", "打孔-纱", "外帘打卷", "外帘装袋", "外帘发货")
    assert normalize_routing_operations(rows_drifted[0]["operations"]) != \
        normalize_routing_operations(rows_good[0]["operations"]), \
        "路线解析器读不出序列变化 ⇒ 路线比对是空断言"

    catalog_names = {"精裁-纱", "纱三边", "打孔-纱", "外帘打卷", "外帘装袋", "外帘发货"}
    assert not [op for op in normalize_routing_operations(rows_good[0]["operations"])
                if op not in catalog_names], "合法路线不应报缺工序"
    assert [op for op in normalize_routing_operations(
        parse_seed(bogus, "production_routings", ROUTING_COLUMNS)[0]["operations"])
        if op not in catalog_names] == ["打孔-不存在"], "缺工序判据读不出不存在的工序"

    assert re.search(r"ON\s+CONFLICT.*DO\s+NOTHING", good, re.I | re.S)
    assert not re.search(r"ON\s+CONFLICT.*DO\s+NOTHING", non_idempotent, re.I | re.S), \
        "幂等判据读不出丢失的 ON CONFLICT ⇒ 该断言是空断言"
