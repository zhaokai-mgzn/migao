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

## 第六源（issue #4427 = 母单 #4423 的 P1/3）：新路线模型的三张表（V71）

`production_operation_positions`（部位价目 84 行）/ `production_route_templates`（1 条具名默认路线）/
`production_route_rules`（26 条规则）—— 由 `V71__normalize_routing_model_structure.sql` 落库，
与 `app/production/routing.py` 的**新真值源**（`ROUTE_MAINLINE_STEPS` / `OPERATION_POSITION_PRICES` /
`ROUTE_RULES`）逐行逐值收敛（三源：`routing.py` ↔ V71 ↔ 本文件）。源同样**按内容发现**
（`seed_sources_for(table)`）⇒ 将来的增量迁移无需改本文件。

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


def values_sources_for(table: str, migration_dir: Path = MIGRATION_DIR) -> tuple:
    """`seed_sources_for` 的**只认 `VALUES` 形态**变体（issue #4432 = 母单 #4423 P2）。

    ## 为什么必须分流（否则守卫自己会假红）

    P2（V72）的**存量租户回填**是 `INSERT INTO <table> SELECT … FROM tenants t JOIN …`
    —— 它是**派生**语句（按租户循环从该租户的 `production_operations` 归一后生成），
    **不是** `VALUES` 字面量种子。本文件的解析器 `parse_seed` 只吃 `VALUES (...)` 形态
    ⇒ 若把 V72 纳入「种子源」，`test_new_route_seed_sources_are_discovered_and_nonempty`
    会判「V72 未解析到任何行 ⇒ 该源等于没被读」（**假红**：V72 的贡献不在字面量里，
    而在「按租户循环」这个形态里，由 `test_routing_model_p2_consumers.py` 的 A 组判据守）。

    ⇒ 判据分流：**字面量种子源**（三源收敛比对射程）= 含 `VALUES` 的那些；
    **派生回填源** = 只有 `SELECT` 的那些（另守）。
    """
    directory = Path(migration_dir)
    # ⚠️ 只认 `INSERT INTO <table> … VALUES`（`VALUES` 必须出现在该语句的 **FROM 之前**）。
    # 不能只看「语句里有没有 VALUES 这个词」：V72 的规则回填是
    # `INSERT INTO production_route_rules … SELECT … JOIN (VALUES …) AS r(...)` ——
    # 那个 `VALUES` 在 JOIN 里、**不是**种子行（列数 8 ≠ 表列数 10），
    # 误判会让 `parse_seed` 解析错位并假红。
    literal_pattern = re.compile(
        r"INSERT\s+INTO\s+" + table + r"\b(?:(?!\bFROM\b)[\s\S])*?\bVALUES\b", re.I)
    found = []
    for p in sorted(directory.glob(MIGRATION_GLOB), key=lambda p: version_key(p.name)):
        if literal_pattern.search(p.read_text(encoding="utf-8")):
            found.append(p)
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


def ident(raw) -> str:
    """**标识符**归一：只去引号/空白，**不做大小写折叠**。

    ⚠️ 为什么不复用 `normalize_value`：它的兜底 `return value.upper()` 是给 **SQL 字面量**
    （`TRUE` / `FALSE` / 未加引号的枚举）准备的；而**标识符大小写敏感** —— 用在工序名/路线 id 上
    会把 `logo条-布` 变成 `LOGO条-布`。实测本文件初版即在此处**假红**
    （`test_template_matches_python_catalog`：`At index 31 diff: 'LOGO条-布' != 'logo条-布'`，
    而四个源里的真值**全是小写** `logo条-布`）。
    另：SQL 侧的值带外层单引号（`'rt-v54-01'`），模板 JSON 侧不带 ⇒ 必须走**同一个**归一函数，
    否则两侧口径不同（苹果比橘子）。
    """
    s = str(raw).strip()
    if len(s) >= 2 and s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    return s


def routing_row_of(row: dict) -> dict:
    """路线行的**两侧同构**归一（模板 JSON 行 与 迁移 SQL 行 都走这里）。

    只取两侧共有的业务列（`tenant_id` 是迁移侧的种子列，模板里没有、也不该有）；
    `operations` 统一成**有序 tuple**（路线是有序序列，顺序敏感）。
    """
    ops = row.get("operations")
    if isinstance(ops, (list, tuple)):
        ops_norm = tuple(str(o) for o in ops)
    else:
        ops_norm = normalize_routing_operations(str(ops))
    return {
        "id": ident(row.get("id")),
        "curtain_type": ident(row.get("curtain_type")),
        "craft": ident(row.get("craft")),
        "operations": ops_norm,
        "status": ident(row.get("status")),
    }


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


#: `op_values` 的**标识符安全**版要覆盖的列（与 `op_values` 同一组，口径只差归一函数）
_OP_COLUMNS = ("group_name", "position", "unit", "unit_price",
               "is_must_finish", "is_start_marker", "status")


def op_values_ident(operation_row: dict) -> dict:
    """`op_values` 的**标识符安全**版：全部列走 `ident`（**不折叠大小写**）。

    为什么需要它（实测 issue #4361 的模板守卫初版即在此处假红）：模板 JSON 侧的值**不带引号**
    ⇒ 走 `normalize_value` 会落到 `.upper()` 兜底（`active` → `ACTIVE`）；而 SQL 侧的值**带引号**
    ⇒ `normalize_value` 在引号分支就原样返回（`'active'` → `active`）⇒ 两侧同为 `active` 却比出
    `ACTIVE != active`。**不动 `op_values`**：它同时服务四源守卫（SQL↔Python），那两侧都是 SQL
    字面量口径，改动无收益且会牵动已在绿的判据。
    """
    # 文本列走 `ident`（不折叠大小写）；**数值列走 `normalize_value`** —— 模板 JSON 里写的
    # 可能是 `1` / `2`（整数），而迁移 SQL 里是 `1.0` / `2.0` ⇒ 只有数字归一分支能对齐
    # （实测：全用 `ident` 时恰有 7 条数值列不同的工序假红：外帘发货/外帘打卷/外帘装袋/
    # 帘头制作/抱枕/接高-布/腰靠垫）。
    return {col: (normalize_value(operation_row[col]) if col == "unit_price"
                  else ident(operation_row[col]))
            for col in _OP_COLUMNS}


def by_name_ident(rows):
    """同 `by_name`，但走 `op_values_ident`（跨**格式**比对专用：模板 JSON ↔ 迁移 SQL）。"""
    return {ident(r["name"]): op_values_ident(r) for r in rows}


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

    # 两侧都走 `ident`（**不折叠大小写**）：模板 JSON 侧的值不带引号、SQL 侧带引号，
    # 只有同一个归一函数才能可比（`key_of` 走 `normalize_value`，其 `.upper()` 兜底会把
    # `logo条-布` 变成 `LOGO条-布` ⇒ 假红，实测本文件初版即踩）。
    assert [ident(r["name"]) for r in rows] == [ident(k) for k in catalog.keys()], (
        "模板工序名集合/顺序与 OPERATION_CATALOG 不一致（改名或加减工序必须同步模板）")
    # 跨**格式**比对（模板 JSON ↔ 迁移 SQL）走标识符安全口径 —— 两侧引号形态不同，
    # 只有同一个不折叠大小写的归一函数才可比（见 `op_values_ident` 的实测说明）。
    assert by_name_ident(rows) == by_name_ident(catalog_rows), (
        f"模板工序与迁移种子漂移：{_diff_keys(by_name_ident(rows), by_name_ident(catalog_rows))}")
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
    # 两侧**同构**归一后逐行比对（模板 JSON 行 vs 迁移 SQL 行）：SQL 侧的值带外层引号且多
    # `tenant_id` 列 ⇒ 直接 `rows == routing_rows` 是苹果比橘子（实测初版即假红）。
    template_rows_norm = [routing_row_of(r) for r in rows]
    migration_rows_norm = [routing_row_of(r) for r in routing_rows]
    assert template_rows_norm == migration_rows_norm, (
        f"模板路线与迁移种子漂移（逐行，含 id/status）："
        f"{_diff_keys({r['id']: r for r in template_rows_norm}, {r['id']: r for r in migration_rows_norm})}")


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


# ── ⑥ 特殊选项名（join key）三源收敛（issue #4389）──
#
# 为什么单列一段：`SPECIAL_OPTION_ROUTINGS` / `OPTION_FACTOR_SCOPES` / `NON_PIECEWORK_OPTIONS`
# 的**键**是「订单选配 → 车间工序 / 计件系数」的 **join key** —— 错一个字 ⇒
# `.get(opt) → None` ⇒ 条件工序不加、计件系数静默退回 1.0 ⇒ **少发工人钱**（无任何东西变红）。
# 用户裁定 R-e「以 ERP 为准改」⇒ 三张表的键、V59 种子、`schema.sql` 终态必须**逐字**一致。
#
# ⚠️ **V59 是已发布迁移，一个字都不许改**（`MigrationRunner` 按文件名整份 skip ⇒ 改它只对全新库
# 生效，存量环境永远拿不到 —— 「CI 全绿、功能静默缺失」）。改名只能走**新迁移**
# （本单 = `V65__align_special_option_names_with_erp.sql`，`UPDATE ... SET option_name = '新'
# WHERE option_name = '旧'`）。故「迁移侧」= **V59 的 INSERT ∪ 改名迁移的 UPDATE**，
# 而改名迁移按**内容**发现（含 `UPDATE production_option_* SET option_name` 的 `V*.sql`）
# ⇒ 将来的改名迁移无需改本文件。

OPTION_FACTOR_COLUMNS = ("id", "tenant_id", "option_name", "operation_name", "factor", "source")
OPTION_ROUTING_COLUMNS = ("id", "tenant_id", "option_name", "operation_name",
                          "after_operation", "sort_order", "status")

_RENAME_STMT_RE = re.compile(
    r"UPDATE\s+(production_option_\w+)\s+SET\s+option_name\s*=\s*'([^']*)'"
    r".*?WHERE\s+option_name\s*=\s*'([^']*)'", re.I | re.S)
_RENAME_FILE_RE = re.compile(r"UPDATE\s+production_option_\w+\s+SET\s+option_name", re.I)


def option_rename_sources(migration_dir: Path = MIGRATION_DIR) -> tuple:
    """按**内容**发现「选项改名」迁移（版本号数值序）；空集由下方自证拦下（fail-closed）。"""
    directory = Path(migration_dir)
    return tuple(p for p in sorted(directory.glob(MIGRATION_GLOB),
                                   key=lambda p: version_key(p.name))
                 if _RENAME_FILE_RE.search(p.read_text(encoding="utf-8")))


def option_renames(migration_dir: Path = MIGRATION_DIR) -> dict:
    """{表: {旧名: 新名}} —— 聚合全部改名迁移（版本号序，后写覆盖先写）。"""
    renames: dict = {}
    for path in option_rename_sources(migration_dir):
        for table, new_name, old_name in _RENAME_STMT_RE.findall(path.read_text(encoding="utf-8")):
            renames.setdefault(table.lower(), {})[old_name] = new_name
    return renames


def effective_option_rows(table: str, columns, migration_dir: Path = MIGRATION_DIR) -> list:
    """**有效**选项行（`V59 的 INSERT` ∪ `改名迁移的 UPDATE` 已应用）→ [{列: 归一化字面量}]。

    归一化口径与 `by_name` 同源（`normalize_value`）⇒ 可与 `schema.sql` 侧直接比 dict。
    """
    rows = []
    for path in seed_sources_for(table, migration_dir):
        rows += parse_seed(path.read_text(encoding="utf-8"), table, columns)
    renames = option_renames(migration_dir).get(table, {})
    out = []
    for row in rows:
        normalized = {col: normalize_value(row[col]) for col in columns}
        name = normalized["option_name"]
        normalized["option_name"] = renames.get(name, name)
        out.append(normalized)
    return out


def _routing_py_option_registries():
    """routing.py 的三张特殊选项表 + 待确认集合（**真值源**，单一 import 点）。"""
    sys.path.insert(0, str(ROUTING_PY_DIR))
    try:
        from app.production.routing import (
            NON_PIECEWORK_OPTIONS, OPTION_FACTOR_SCOPES,
            PENDING_CUSTOMER_CONFIRMATION_OPTIONS, SPECIAL_OPTION_ROUTINGS,
        )
        return (SPECIAL_OPTION_ROUTINGS, OPTION_FACTOR_SCOPES,
                NON_PIECEWORK_OPTIONS, PENDING_CUSTOMER_CONFIRMATION_OPTIONS)
    finally:
        sys.path.pop(0)


def _normalized(rows, columns) -> list:
    """`parse_seed` 的**原始字面量**行 → 归一化行（与 `effective_option_rows` 同口径，可比 dict）。"""
    return [{col: normalize_value(row[col]) for col in columns} for row in rows]


def _factor_map(rows) -> dict:
    """选项行（已归一化）→ {(选项, 工序限定): 系数}（工序限定 `NULL` ⇒ None = 平摊档）。"""
    return {(r["option_name"], None if r["operation_name"] == "NULL" else r["operation_name"]):
            float(r["factor"]) for r in rows}


def _routing_map(rows) -> dict:
    """选项行（已归一化）→ {选项: (条件工序, 锚点)}。"""
    return {r["option_name"]: (r["operation_name"], r["after_operation"]) for r in rows}


def test_option_rename_sources_are_discovered_and_nonempty():
    """自证：改名迁移必须**被读到**（空集 ⇒ 迁移侧退化成直读 V59 ⇒ 三源比对假绿）。"""
    sources = option_rename_sources()
    assert sources, (
        "未发现任何「选项改名」迁移（含 `UPDATE production_option_* SET option_name` 的 V*.sql）"
        "⇒ 迁移侧退化成直读 V59（= 修复前形态），本段判据全部空转")
    renames = option_renames()
    assert renames, "改名迁移存在但解析不出任何改名语句（解析器与迁移写法脱节）"


def test_option_factor_names_converge_across_three_sources(schema_sql):
    """判据 3（红证）：系数表三源**逐行逐字**一致 —— V59 ∪ 改名迁移 ↔ routing.py ↔ schema.sql。

    改一处不改另两处即红：① 只改 `routing.py` 的键 ⇒ 迁移/bootstrap 两侧名字对不上；
    ② 只改 `schema.sql` ⇒ 与迁移侧对不上；③ 只改迁移（含漏掉改名）⇒ 与真值源对不上。
    """
    _, factor_scopes, _, _ = _routing_py_option_registries()
    truth = {(opt, sc["operation_name"]): float(sc["factor"])
             for opt, scopes in factor_scopes.items() for sc in scopes}
    migration = _factor_map(effective_option_rows("production_option_factors", OPTION_FACTOR_COLUMNS))
    bootstrap = _factor_map(_normalized(
        parse_seed(schema_sql, "production_option_factors", OPTION_FACTOR_COLUMNS),
        OPTION_FACTOR_COLUMNS))
    assert migration == truth, f"系数表：迁移侧（V59 ∪ 改名）≠ routing.py OPTION_FACTOR_SCOPES：{_diff_keys(migration, truth)}"
    assert bootstrap == truth, f"系数表：schema.sql 终态 ≠ routing.py：{_diff_keys(bootstrap, truth)}"


def test_option_routing_names_converge_across_three_sources(schema_sql):
    """判据 3（红证）：条件工序表三源**逐行逐字**一致（16 项 × 工序/锚点）。"""
    routings, _, _, _ = _routing_py_option_registries()
    truth = {opt: (spec["operation"], spec["after"]) for opt, spec in routings.items()}
    migration = _routing_map(effective_option_rows("production_option_routings",
                                                   OPTION_ROUTING_COLUMNS))
    bootstrap = _routing_map(_normalized(
        parse_seed(schema_sql, "production_option_routings", OPTION_ROUTING_COLUMNS),
        OPTION_ROUTING_COLUMNS))
    assert migration == truth, f"条件工序表：迁移侧 ≠ routing.py SPECIAL_OPTION_ROUTINGS：{_diff_keys(migration, truth)}"
    assert bootstrap == truth, f"条件工序表：schema.sql 终态 ≠ routing.py：{_diff_keys(bootstrap, truth)}"


def test_option_names_carry_no_stale_spelling_anywhere():
    """判据 1/2（红证）：三源里**都不得**残留 ERP 名对齐之前的写法。

    旧写法（`一分二` / `余料带回(布)` / `余料带回(纱)`）一旦残留在任一源里，那条链就是
    「按 ERP 说法选 ⇒ 查不到 ⇒ 静默失效」—— 故三个源逐个点名比对。
    """
    stale = {"一分二", "余料带回(布)", "余料带回(纱)"}
    routings, factor_scopes, non_piecework, _ = _routing_py_option_registries()
    registries = set(routings) | set(factor_scopes) | set(non_piecework)
    assert registries & stale == set(), f"routing.py 注册表键残留旧写法: {sorted(registries & stale)}"
    for table, columns in (("production_option_factors", OPTION_FACTOR_COLUMNS),
                           ("production_option_routings", OPTION_ROUTING_COLUMNS)):
        names = {r["option_name"] for r in effective_option_rows(table, columns)}
        assert names & stale == set(), f"{table}（迁移侧有效状态）残留旧写法: {sorted(names & stale)}"
    assert not (stale & {r["option_name"] for r in _normalized(
        parse_seed(SCHEMA.read_text(encoding="utf-8"), "production_option_factors",
                   OPTION_FACTOR_COLUMNS), OPTION_FACTOR_COLUMNS)}), \
        "schema.sql 的系数种子残留旧写法"


def test_erp_leftover_return_forms_are_all_explicitly_registered():
    """判据 2（红证）：ERP 的**三种**「余料带回」形态都被显式登记（既不漏、也不落静默黑洞）。

    `余料带回-布` / `余料带回-纱` = 显式登记的**不计件**；`余料带回`（无后缀）不在真值源 §1 的
    19 项清单里 ⇒ 登记为**待客户确认**（`PENDING_CUSTOMER_CONFIRMATION_OPTIONS`），
    不猜它归哪一类、也不让它变成「忘了映射」。
    """
    _, _, non_piecework, pending = _routing_py_option_registries()
    assert {"余料带回-布", "余料带回-纱"} <= non_piecework, \
        f"ERP 名的不计件项未登记: {sorted({'余料带回-布', '余料带回-纱'} - non_piecework)}"
    assert "余料带回" in pending, "ERP 第三种形态（无后缀 `余料带回`）零登记 = 静默黑洞"
    # 三形态都不得落表（「不计件」与「待确认」都**不是**「有映射」）
    for table, columns in (("production_option_factors", OPTION_FACTOR_COLUMNS),
                           ("production_option_routings", OPTION_ROUTING_COLUMNS)):
        names = {r["option_name"] for r in effective_option_rows(table, columns)}
        assert names & {"余料带回-布", "余料带回-纱", "余料带回"} == set(), \
            f"{table} 里落了不计件/待确认选项（会把「不计件」变成「有映射但系数 1」）"


def test_option_rename_application_is_load_bearing(tmp_path):
    """注入式自证（判据 3 的「能红」）：改名**真被应用**，撤掉即回旧名（否则比对是空断言）。

    反例（本测试要挡的形态）：`effective_option_rows` 只读 V59、把改名当装饰 ⇒
    「改了 V65 但守卫照绿」（= issue #4235 的「CI 全绿、功能静默缺失」）。
    """
    (tmp_path / "V59__create_production_option_tables.sql").write_text(
        "INSERT INTO production_option_factors (id, tenant_id, option_name, operation_name, factor, source) "
        "VALUES ('opt-fa-01', 1, '旧名', NULL, 1.7, '实证') ON CONFLICT (id) DO NOTHING;",
        encoding="utf-8")
    rename = tmp_path / "V65__align.sql"
    rename.write_text(
        "UPDATE production_option_factors SET option_name = '新名', updated_at = NOW() "
        "WHERE option_name = '旧名';", encoding="utf-8")

    assert [p.name for p in option_rename_sources(tmp_path)] == ["V65__align.sql"], \
        "改名迁移发现不是「按内容 + 版本号数值序」"
    assert option_renames(tmp_path) == {"production_option_factors": {"旧名": "新名"}}
    assert effective_option_rows("production_option_factors", OPTION_FACTOR_COLUMNS,
                                 tmp_path)[0]["option_name"] == "新名", \
        "改名没有被应用到有效状态 ⇒ 三源比对读的还是旧名（空判据）"

    # 撤掉改名源 ⇒ 必须回到旧名（证明「新名」确实来自那条 UPDATE，而不是别处恰好写着新名）
    rename.unlink()
    assert effective_option_rows("production_option_factors", OPTION_FACTOR_COLUMNS,
                                 tmp_path)[0]["option_name"] == "旧名", \
        "撤掉改名迁移后仍读出「新名」⇒ 该断言与改名迁移无关（假绿）"


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


# ── ⑦ 新路线模型（issue #4427 = 母单 #4423 的 P1/3）：新真值源 ↔ V71 ↔ schema.sql 三源收敛 ──
#
# 为什么必须扩源：V71 新增三张表（部位价目 / 具名路线 / 规则表）—— 它们是**新模型的三个投影**
# 里的两个（第三个 = `app/production/routing.py` 的 `ROUTE_MAINLINE_STEPS` /
# `OPERATION_POSITION_PRICES` / `ROUTE_RULES`）。任一漂移 ⇒ P2 切换消费路径后「同一道工序在
# 三个地方三个价」或「规则在库里、代码里没有」—— 与工序库/路线种子同族的**静默漂移面**。
#
# ⚠️ 判据 1（按内容发现源）同样适用：三张新表的种子源由 `seed_sources_for(table)` 发现，
# 将来的增量迁移无需改本文件。

POSITION_PRICE_COLUMNS = ("id", "tenant_id", "logical_name", "position", "unit_price",
                          "applicable", "status")
ROUTE_TEMPLATE_COLUMNS = ("id", "tenant_id", "name", "is_default", "positions", "mainline", "status")
ROUTE_RULE_COLUMNS = ("id", "tenant_id", "trigger_kind", "trigger_value", "position", "action",
                      "operation", "after_operation", "priority", "status")

# 新表种子源：**按集合聚合**（判据 1）—— 新增**字面量**种子迁移无需在此追加任何东西。
# ⚠️ 用 `values_sources_for` 而不是 `seed_sources_for`：P2（V72）的存量租户回填是
# `INSERT INTO <table> SELECT … FROM tenants t JOIN …`（**派生**语句、无 VALUES），
# 不属「字面量种子源」的比对射程 —— 把它算进来会让本段判据对 V72 假红（见函数 docstring）。
POSITION_SEED_SQLS = values_sources_for("production_operation_positions")
TEMPLATE_SEED_SQLS = values_sources_for("production_route_templates")
RULE_SEED_SQLS = values_sources_for("production_route_rules")

#: 7 组「部位变体」（旧工序名 → 同一道逻辑工序）—— 同组内 group_name / unit / scope 必须一致
VARIANT_GROUPS = {
    "精裁": ("精裁-布", "精裁-纱"),
    "裁剪": ("裁剪-布", "裁剪-纱"),
    "三边": ("布三边", "纱三边"),
    "韩褶": ("韩褶-布", "韩褶-纱"),
    "上车布": ("上车布-布", "上车布-纱"),
    "打孔": ("打孔-布", "打孔-纱"),
    "绑带": ("绑带-布", "绑带-纱"),
}


def _num_or_none(raw):
    """SQL 字面量 → 数字或 `None`（`NULL` = 该部位不报价，与 0 是两回事）。"""
    value = normalize_value(raw)
    return None if value == "NULL" else float(value)


def _text_or_none(raw):
    """SQL 字面量 → 文本或 `None`（`NULL` = 不限部位 / 追加末尾）。"""
    value = normalize_value(raw)
    return None if value == "NULL" else value


def position_price_rows(sql: str) -> dict:
    """部位价目行 → `{(逻辑工序, 部位): (单价|None, applicable, status)}`（**逐值**口径）。"""
    return {(normalize_value(r["logical_name"]), normalize_value(r["position"])):
            (_num_or_none(r["unit_price"]), normalize_value(r["applicable"]) == "TRUE",
             normalize_value(r["status"]))
            for r in parse_seed(sql, "production_operation_positions", POSITION_PRICE_COLUMNS)}


def route_template_rows(sql: str) -> list:
    """具名路线行 → `[{name, is_default, positions, mainline, status}]`（有序序列 = tuple）。"""
    return [{"name": normalize_value(r["name"]),
             "is_default": normalize_value(r["is_default"]) == "TRUE",
             "positions": normalize_routing_operations(r["positions"]),
             "mainline": normalize_routing_operations(r["mainline"]),
             "status": normalize_value(r["status"])}
            for r in parse_seed(sql, "production_route_templates", ROUTE_TEMPLATE_COLUMNS)]


def route_rule_rows(sql: str) -> dict:
    """规则行 → `{(触发类型, 触发值, 部位, 动作, 工序, 锚点): priority}`（`NULL` → `None`）。"""
    return {(normalize_value(r["trigger_kind"]), normalize_value(r["trigger_value"]),
             _text_or_none(r["position"]), normalize_value(r["action"]),
             normalize_value(r["operation"]), _text_or_none(r["after_operation"])):
            int(normalize_value(r["priority"]))
            for r in parse_seed(sql, "production_route_rules", ROUTE_RULE_COLUMNS)}


def _aggregate_text(seed_paths) -> str:
    """把按内容发现的一组种子迁移**拼成一份文本**（多源聚合，版本号序）。"""
    return "\n".join(path.read_text(encoding="utf-8") for path in seed_paths)


def _route_v2_truth() -> tuple:
    """`routing.py` 的新真值源（单一 import 点）→ `(部位价目, 主线, 规则, 默认路线名)`。"""
    sys.path.insert(0, str(ROUTING_PY_DIR))
    try:
        from app.production.routing import (
            OPERATION_POSITION_PRICES, ROUTE_MAINLINE_STEPS, ROUTE_RULES,
            ROUTE_TEMPLATE_NAME_DEFAULT,
        )
        return (OPERATION_POSITION_PRICES, ROUTE_MAINLINE_STEPS, ROUTE_RULES,
                ROUTE_TEMPLATE_NAME_DEFAULT)
    finally:
        sys.path.pop(0)


def _truth_price_rows() -> dict:
    prices, _, _, _ = _route_v2_truth()
    return {(logical, pos): (
                None if cell["unit_price"] is None else float(cell["unit_price"]),
                bool(cell["applicable"]), "active")
            for logical, by_position in prices.items()
            for pos, cell in by_position.items()}


def _truth_rule_rows() -> dict:
    _, _, rules, _ = _route_v2_truth()
    return {(r["trigger_kind"], r["trigger_value"], r["position"], r["action"],
             r["operation"], r["after_operation"]): int(r["priority"]) for r in rules}


def test_new_route_seed_sources_are_discovered_and_nonempty():
    """自证（fail-closed）：三张新表的种子源都被**按内容**发现且每个源都真解析出行。

    反例（本测试要挡的形态）：源发现退化成空集或只读到其中一个 ⇒ 下面三条三源收敛判据
    全部空转（「绿了但没跑」）。
    """
    cases = (
        ("部位价目", POSITION_SEED_SQLS, "production_operation_positions", POSITION_PRICE_COLUMNS),
        ("具名路线", TEMPLATE_SEED_SQLS, "production_route_templates", ROUTE_TEMPLATE_COLUMNS),
        ("规则", RULE_SEED_SQLS, "production_route_rules", ROUTE_RULE_COLUMNS),
    )
    for label, sources, table, columns in cases:
        assert sources, (
            f"未发现任何{label}种子源（`INSERT INTO {table}` 一个都扫不到）⇒ 本段判据退化成空跑")
        for path in sources:
            assert path.exists(), f"{label}种子迁移缺失：{path}"
            assert parse_seed(path.read_text(encoding="utf-8"), table, columns), \
                f"{path} 未解析到任何{label}行（该源等于没被读）"


def test_position_prices_converge_across_three_sources(schema_sql):
    """部位价目三源**逐行逐值**一致：`routing.py` ↔ V71 ↔ `schema.sql`（28 × 3 = 84 行）。

    改一处不改另两处即红：① 只改 Python（改价/翻 applicable）⇒ 迁移与 bootstrap 对不上；
    ② 只改 V71 ⇒ 与真值源对不上；③ 只改 schema.sql ⇒ 与迁移侧对不上。
    """
    truth = _truth_price_rows()
    migration = position_price_rows(_aggregate_text(POSITION_SEED_SQLS))
    bootstrap = position_price_rows(schema_sql)
    assert len(truth) == 84, f"真值源的部位价目不是 84 行（28 × 3）：{len(truth)}"
    assert len(migration) == 84, f"迁移侧的部位价目不是 84 行：{len(migration)}"
    assert migration == truth, f"部位价目：迁移侧 ≠ routing.py：{_diff_keys(migration, truth)}"
    assert bootstrap == truth, f"部位价目：schema.sql 终态 ≠ routing.py：{_diff_keys(bootstrap, truth)}"


def test_route_template_converges_across_three_sources(schema_sql):
    """具名路线三源逐值一致（**1 行**：名字 / 默认标记 / 适用帘种 / 主线序列 / 状态）。"""
    _, mainline, _, name = _route_v2_truth()
    truth = {"name": name, "is_default": True,
             "positions": ("布帘", "纱帘", "帘头"), "mainline": tuple(mainline), "status": "active"}
    migration = route_template_rows(_aggregate_text(TEMPLATE_SEED_SQLS))
    assert len(migration) == 1, f"迁移侧的具名路线不是 1 行：{len(migration)}"
    assert migration[0] == truth, f"具名路线：迁移侧 ≠ routing.py：{migration[0]} ≠ {truth}"
    assert route_template_rows(schema_sql) == migration, \
        "具名路线：schema.sql 终态 ≠ 迁移侧（bootstrap 库与迁移库路线不同）"


def test_route_rules_converge_across_three_sources(schema_sql):
    """规则表三源**逐行逐值**一致（26 行：工艺 10 + 特殊选项 16，含 priority）。"""
    truth = _truth_rule_rows()
    migration = route_rule_rows(_aggregate_text(RULE_SEED_SQLS))
    bootstrap = route_rule_rows(schema_sql)
    assert len(truth) == 26, f"真值源的规则不是 26 条：{len(truth)}"
    assert len(migration) == 26, f"迁移侧的规则不是 26 条：{len(migration)}"
    assert migration == truth, f"规则表：迁移侧 ≠ routing.py：{_diff_keys(migration, truth)}"
    assert bootstrap == truth, f"规则表：schema.sql 终态 ≠ routing.py：{_diff_keys(bootstrap, truth)}"


def test_new_route_operations_all_have_a_price_row(schema_sql):
    """主线与规则引用的工序名都必须落在**已落库的逻辑工序集合**里（否则实例化无价可依）。

    双向：`mainline` / `operation` / `after_operation` 逐条点名，缺一个即红（点名到工序名，
    不是只给一句 assert）。
    """
    _, mainline, rules, _ = _route_v2_truth()
    seeded = {key[0] for key in position_price_rows(_aggregate_text(POSITION_SEED_SQLS))}
    assert set(mainline) <= seeded, \
        f"主线引用了没有价目行的工序：{sorted(set(mainline) - seeded)}"
    for rule in rules:
        assert rule["operation"] in seeded, \
            f"规则 {rule['trigger_value']} 引用了没有价目行的工序：{rule['operation']}"
        if rule["after_operation"] is not None:
            assert rule["after_operation"] in seeded, \
                f"规则 {rule['trigger_value']} 的锚点没有价目行：{rule['after_operation']}"
    # schema.sql 侧同样钉（bootstrap 库的价目行集合必须覆盖主线）
    assert set(mainline) <= {key[0] for key in position_price_rows(schema_sql)}


def test_position_variant_groups_share_group_unit_and_scope(catalog_rows):
    """7 组部位变体的 `group_name` / `unit` / `scope` **同组内一致**（否则「同一道工序」不成立）。

    合并成一行逻辑工序的前提 = 「它们只是同一道工序的两种部位写法」。分组/单位/作用域不同
    意味着两个不同的车间口径被压成一行（单价与计件都会错）⇒ 本判据逐个点名不一致的那一组。
    """
    scopes = effective_scopes()
    rows_by_name = {key_of(r): r for r in catalog_rows}
    for logical, olds in sorted(VARIANT_GROUPS.items()):
        missing = sorted(set(olds) - set(rows_by_name))
        assert not missing, f"{logical} 组内有变体不在工序库种子里：{missing}"
        groups = {normalize_value(rows_by_name[o]["group_name"]) for o in olds}
        units = {normalize_value(rows_by_name[o]["unit"]) for o in olds}
        group_scopes = {scopes.get(o) for o in olds}
        assert len(groups) == 1, f"{logical} 组内 group_name 不一致：{sorted(groups)}"
        assert len(units) == 1, f"{logical} 组内 unit 不一致：{sorted(units)}"
        assert len(group_scopes) == 1, f"{logical} 组内 scope 不一致：{sorted(group_scopes)}"


_SCOPE_SET_RE = re.compile(
    r"UPDATE\s+production_operations\s+SET\s+scope\s*=\s*'([^']+)'\s*WHERE\s+name\s+IN\s*\(([^)]*)\)",
    re.I | re.S)


def scope_update_sources(migration_dir: Path = MIGRATION_DIR) -> tuple:
    """按**内容**发现「工序作用域」回填迁移（版本号数值序）——不写死 V67。"""
    directory = Path(migration_dir)
    return tuple(p for p in sorted(directory.glob(MIGRATION_GLOB), key=lambda p: version_key(p.name))
                 if re.search(r"UPDATE\s+production_operations\s+SET\s+scope\s*=",
                              p.read_text(encoding="utf-8"), re.I))


def effective_scopes(migration_dir: Path = MIGRATION_DIR) -> dict:
    """旧工序名 → `scope` 的**有效状态**：列默认值 `'position'` ∪ 作用域回填迁移的 UPDATE。"""
    scopes = {}
    for path in seed_sources_for("production_operations", migration_dir):
        for row in parse_seed(path.read_text(encoding="utf-8"), "production_operations", OP_COLUMNS):
            scopes[ident(row["name"])] = "position"   # = production_operations.scope 的列默认值
    for path in scope_update_sources(migration_dir):
        for scope, names in _SCOPE_SET_RE.findall(path.read_text(encoding="utf-8")):
            for name in re.findall(r"'([^']+)'", names):
                scopes[name] = scope
    return scopes


def test_effective_scope_resolution_is_load_bearing():
    """自证：作用域回填迁移**真被应用**（V67 的三道外帘工序 = 套级），且 7 组变体都是部位级。

    反例（本测试要挡的形态）：`effective_scopes` 只读种子 INSERT（拿不到 scope）⇒
    上一条「同组 scope 一致」退化成恒真（每组都是同一个默认值，判据永远绿）。
    """
    scopes = effective_scopes()
    set_scope = {name for name, scope in scopes.items() if scope == "set"}
    assert {"外帘打卷", "外帘装袋", "外帘发货"} <= set_scope, (
        "作用域回填迁移没被读到 ⇒ scope 判据是空断言（该源按内容发现，不写死 V67）")
    variant_names = {old for olds in VARIANT_GROUPS.values() for old in olds}
    assert not (variant_names & set_scope), \
        f"7 组部位变体里出现了套级工序：{sorted(variant_names & set_scope)}（与「同一道工序」前提冲突）"


def test_variant_group_scope_mismatch_is_detected(tmp_path):
    """注入式自证：给组内**一个**变体标成套级 ⇒ 同组 scope 不再一致（判据真能红）。"""
    (tmp_path / "V54__seed_production_operations.sql").write_text(
        "INSERT INTO production_operations (id, tenant_id, name, group_name, position, unit, "
        "unit_price, is_must_finish, is_start_marker, sort_order, status) VALUES\n"
        "  ('op-1', 1, '韩褶-布', '车位', '布帘', '折', 0.4, FALSE, FALSE, 1, 'active'),\n"
        "  ('op-2', 1, '韩褶-纱', '车位', '纱帘', '折', 0.4, FALSE, FALSE, 2, 'active')\n"
        "ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;", encoding="utf-8")
    (tmp_path / "V99__scope.sql").write_text(
        "UPDATE production_operations SET scope = 'set' WHERE name IN ('韩褶-纱');", encoding="utf-8")
    scopes = effective_scopes(tmp_path)
    assert scopes["韩褶-布"] == "position", "注入夹具的默认作用域没被读到"
    assert scopes["韩褶-纱"] == "set", "注入夹具的作用域回填没被读到"
    assert len({scopes["韩褶-布"], scopes["韩褶-纱"]}) == 2, \
        "同组 scope 不一致读不出来 ⇒ 「同组 scope 一致」判据是空断言"


def test_new_route_parsers_detect_injected_drift():
    """注入式自证：三张新表的解析器必须**能**照出漂移（改价/翻适用性/改主线/改优先级）。"""
    good_positions = (
        "INSERT INTO production_operation_positions "
        "(id, tenant_id, logical_name, position, unit_price, applicable, status) VALUES\n"
        "  ('opp-1', 1, '熨烫', '布帘', 0.35, TRUE, 'active'),\n"
        "  ('opp-2', 1, '熨烫', '纱帘', NULL, FALSE, 'active')\n"
        "ON CONFLICT (id) DO NOTHING;")
    good_templates = (
        "INSERT INTO production_route_templates "
        "(id, tenant_id, name, is_default, positions, mainline, status) VALUES\n"
        "  ('rt-1', 1, '窗帘工序路线（默认）', TRUE, '[\"布帘\", \"纱帘\", \"帘头\"]'::jsonb,\n"
        "   '[\"精裁\", \"三边\"]'::jsonb, 'active')\n"
        "ON CONFLICT (id) DO NOTHING;")
    good_rules = (
        "INSERT INTO production_route_rules "
        "(id, tenant_id, trigger_kind, trigger_value, position, action, operation, "
        "after_operation, priority, status) VALUES\n"
        "  ('rr-1', 1, 'craft', '韩褶', NULL, 'insert', '韩褶', '三边', 10, 'active')\n"
        "ON CONFLICT (id) DO NOTHING;")

    base_prices = position_price_rows(good_positions)
    assert base_prices[("熨烫", "布帘")] == (0.35, True, "active"), "部位价目解析器没读出合法行"
    assert base_prices[("熨烫", "纱帘")][0] is None, "部位价目解析器没读出 NULL 价（明确不做）"
    assert position_price_rows(good_positions.replace("0.35", "0.99")) != base_prices, \
        "改单价读不出来 ⇒ 部位价目三源比对是空断言"
    assert position_price_rows(good_positions.replace(
        "'纱帘', NULL, FALSE", "'纱帘', NULL, TRUE")) != base_prices, \
        "翻 applicable 读不出来 ⇒ 适用性比对是空断言"

    base_templates = route_template_rows(good_templates)
    assert base_templates[0]["mainline"] == ("精裁", "三边"), "具名路线解析器没读出主线序列"
    assert route_template_rows(good_templates.replace('"三边"', '"打孔"')) != base_templates, \
        "改主线序列读不出来 ⇒ 具名路线比对是空断言"

    base_rules = route_rule_rows(good_rules)
    assert base_rules[("craft", "韩褶", None, "insert", "韩褶", "三边")] == 10, \
        "规则解析器没读出合法行（含 NULL 部位）"
    assert route_rule_rows(good_rules.replace("10, 'active'", "99, 'active'")) != base_rules, \
        "改 priority 读不出来 ⇒ 规则顺序比对是空断言"
    assert route_rule_rows(good_rules.replace("'三边', 10", "NULL, 10")) != base_rules, \
        "改锚点读不出来 ⇒ 规则比对是空断言"
