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

`production_operation_positions`（部位价目 120 行）/ `production_route_templates`（2 条基础路线）/
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


def declared_columns(sql: str, table: str) -> tuple:
    """从 `INSERT INTO <table> (列清单) …` **读出**该源声明的列序（读不到 ⇒ 返回 `()`）。

    为什么读而不是写死（issue #4690）：`docs/sql/schema.sql`（bootstrap）是**终态**种子，它对
    「V88 退场」的表达是**显式写 `deleted` 列**（行保留、翻标记）⇒ 列数比迁移侧多一列。
    把列清单写死会让「bootstrap 多写一列」被读成「列序漂移」（**假红**），而把 `deleted` 从
    两侧都删掉又会丢掉「bootstrap 到底种成什么态」的可判性 ⇒ 只能按源文本取值。
    """
    match = re.search(r"INSERT\s+INTO\s+" + table + r"\s*\(([^)]*)\)", sql, re.I)
    if not match:
        return ()
    return tuple(c.strip() for c in match.group(1).split(",") if c.strip())


def parse_seed(sql: str, table: str, columns):
    """解析 `INSERT INTO <table> ... VALUES ...` 段 → [{列: 原始字面量}]。

    只认**第一条**该表的 INSERT（每个源文件各只有一条种子语句）。
    列清单优先取源文本里声明的（`declared_columns`），读不到才回落调用方给的 `columns`
    —— 回落是给**注入式夹具**（临时字符串，没有列清单）用的。
    """
    match = re.search(
        r"INSERT\s+INTO\s+" + table + r"\b[^;]*?VALUES(.*?)(?:ON\s+CONFLICT|;)",
        sql, re.S | re.I)
    if not match:
        return []
    columns = declared_columns(sql, table) or columns
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


#: 🔴 **已退场列**（issue #4961「必完（`is_must_finish`）概念整体退场」）：**不参与跨源逐值比对**。
#
# 为什么必须排除（不是放宽，是**两侧合法地不同**）：唯一的真相是——
#   · 迁移链侧的 V54 是**已发布迁移**（内容被 `migration_fingerprints.json` 逐字节冻结）⇒
#     它仍留着历史的 `外帘装袋 = TRUE`，**不可改**；
#   · bootstrap 侧 `docs/sql/schema.sql` 是**终态** ⇒ 该列一律 `FALSE` 才算对
#     （存量库由 `backend/admin-api/src/main/resources/db/migration/V107__retire_must_finish_flag.sql` 收敛）。
# ⇒ 若继续把该列放进 `by_name` / `by_name_ident`，只有两个结局：**永久假红**，
#   或把判据改成恒真（恒真 = 空断言，比假红更糟）。
#
# 替代判据（**更强**，两条各自独立、都可红，见下方）：
#   ① `test_frozen_seed_must_finish_is_the_recorded_history`：冻结种子的**历史值**逐行等于
#      记录在案的字面量（原判据从 `routing.py::MUST_FINISH_OPS` **派生**期望值 —— 而那个集合
#      已随本单删除 ⇒ 判据会随被测对象一起漂移；改成字面量后钉的是**文件里真实的字节**）；
#   ② `test_must_finish_is_false_in_every_terminal_source`：bootstrap 种子 / 模板 JSON
#      两个**终态**源一律 `FALSE`（模板**带**该键即红）。
_RETIRED_COLUMNS = ("is_must_finish",)


def op_values(operation_row: dict) -> dict:
    """工序行的**逐值**口径（不含 id/sort_order：id 是各迁移自有的确定性命名、sort_order 是排序位）。

    含 `deleted` 之外的全部业务列 ⇒ 「改名/改价/改分组/改单位/改标记」任一都逃不掉。
    ⚠️ 例外 = `_RETIRED_COLUMNS`（已退场列，两侧合法地不同，见该常量的说明与替代判据）。
    """
    return {col: normalize_value(operation_row[col])
            for col in ("group_name", "position", "unit", "unit_price",
                        "is_start_marker", "status")}


def by_name(rows):
    """[{列: 值}] → {工序名: 逐值 dict}（多源聚合的比对口径，不依赖跨文件行序）。"""
    return {key_of(r): op_values(r) for r in rows}


#: `op_values` 的**标识符安全**版要覆盖的列（与 `op_values` 同一组，口径只差归一函数）
#: ⚠️ 同样不含 `_RETIRED_COLUMNS`（已退场列，见该常量）。
_OP_COLUMNS = ("group_name", "position", "unit", "unit_price",
               "is_start_marker", "status")


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
    """模板工序 → 种子行形态（列名与 `OP_COLUMNS` 对齐，供 `by_name` 直接复用）。

    ⚠️ **不带已退场列** `is_must_finish`（issue #4961）：模板是**开租播种**的输入，
    它带该键 = 把退场键又播进每个新租户（写面已 422、实例化侧也不再读它）。
    「模板不得带该键」由 `test_must_finish_is_false_in_every_terminal_source` 判（带即红）。
    """
    return [{"id": o["id"], "name": o["name"], "group_name": o["group"],
             "position": "NULL" if o.get("position") is None else o["position"],
             "unit": o["unit"], "unit_price": str(o["unit_price"]),
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

    from app.production.routing import START_MARKER_OPS
    for row in catalog_rows:
        name = key_of(row)
        meta = catalog[name]
        assert normalize_value(row["group_name"]) == meta["group"], f"{name} 分组漂移"
        assert normalize_value(row["unit"]) == meta["unit"], f"{name} 单位漂移"
        assert float(normalize_value(row["unit_price"])) == float(meta["unit_price"]), f"{name} 单价漂移"
        # 🔴 `is_must_finish` 的期望值**不再**从 `routing.py::MUST_FINISH_OPS` 派生
        #    （该集合已随 issue #4961 删除）—— 它的判据搬去了
        #    `test_frozen_seed_must_finish_is_the_recorded_history`（冻结种子的历史字面量）。
        assert normalize_value(row["is_start_marker"]) == ("TRUE" if name in START_MARKER_OPS else "FALSE"), \
            f"{name} 开始标记漂移"
        assert normalize_value(row["status"]) == "active"


# ── ①′ 已退场列（`is_must_finish`）的替代判据（#4961）──
#
# 为什么单独立判据：该列在**冻结的**迁移种子（历史）与**终态源**（bootstrap / 模板）之间
# 合法地不同 ⇒ 它退出了 `op_values` / `op_values_ident` 的跨源逐值比对（见 `_RETIRED_COLUMNS`）。
# 下面两条把这个空缺补成**更强**的判据（纯函数化 ⇒ 可用注入式夹具证明会红）。

def _live_seed_true_names(rows) -> list:
    """种子行里 `is_must_finish = TRUE` 的**存活行**工序名（升序）。纯函数（供注入自证）。"""
    out = []
    for row in rows:
        deleted = row.get("deleted")
        live = deleted is None or normalize_value(str(deleted)) in ("0", "NULL")
        if live and normalize_value(row["is_must_finish"]) == "TRUE":
            out.append(key_of(row))
    return sorted(out)


def _template_retired_key_carriers(template: dict) -> list:
    """模板里**仍带**已退场键 `is_must_finish` 的工序名（升序）。纯函数（供注入自证）。"""
    return sorted(o["name"] for o in template["operations"] if "is_must_finish" in o)


def test_frozen_seed_must_finish_is_the_recorded_history(catalog_rows):
    """冻结迁移种子的 `is_must_finish` 历史值 = 记录在案的字面量（改动即红）。

    期望值是**字面量**而不是从 `routing.py` 派生的集合：本单把 `MUST_FINISH_OPS` 删了 ——
    若期望值仍从它派生，判据就会**随被测对象一起漂移**（删集合 ⇒ 期望值跟着变空 ⇒ 判据恒真）。
    钉字面量反而更严：它约束的是 V54/V56 这两个**已发布文件里真实的字节**
    （另有 `migration_fingerprints.json` 的 sha256 逐字节冻结兜底）。
    """
    got = _live_seed_true_names(catalog_rows)
    assert got == ["外帘装袋"], (
        f"冻结迁移种子里 `is_must_finish = TRUE` 的存活工序 = {got}，期望恰好 `外帘装袋`"
        f"（V54 的历史口径；已发布迁移不可改 ⇒ 改了这个值必须解释）")
    assert len(catalog_rows) == 41, (
        f"迁移侧工序库种子解析出 {len(catalog_rows)} 行，期望 41 ⇒ 解析失效或种子被改")
    values = {normalize_value(r["is_must_finish"]) for r in catalog_rows}
    assert values <= {"TRUE", "FALSE"}, f"该列出现了 TRUE/FALSE 之外的值：{values}"


def test_must_finish_is_false_in_every_terminal_source(schema_sql, template_json):
    """两个**终态源**的 `is_must_finish` 一律 `FALSE`（bootstrap 种子 / 模板 JSON）。

    · bootstrap（`docs/sql/schema.sql`，**不跑迁移链**）⇒ 必须自己就是终态，否则新建库落在旧口径；
    · 模板（`production-templates/curtain/seed.json`，**开租播种**）⇒ **不得带**该键
      （带 = 把已退场的键又播进每个新租户；写面收到该字段已 422）。
    迁移链侧的终态由 V107 承担，真库判据见
    `tests/unit_ci_workflows/test_must_finish_retire_migration.py`。
    """
    schema_ops = parse_seed(schema_sql, "production_operations", OP_COLUMNS)
    assert len(schema_ops) == 41, (
        f"schema.sql 的工序库种子解析出 {len(schema_ops)} 行，期望 41 ⇒ 解析失效或种子被改")
    boot_true = _live_seed_true_names(schema_ops)
    assert boot_true == [], (
        f"bootstrap（schema.sql）仍有存活工序 `is_must_finish = TRUE`：{boot_true} —— "
        f"它不跑迁移链 ⇒ 必须自己就是终态（#4961）")
    carriers = _template_retired_key_carriers(template_json)
    assert carriers == [], (
        f"模板 JSON 仍带已退场键 `is_must_finish`：{carriers} —— 开租播种会把该键播进新租户"
        f"（#4961：写面已 422、实例化侧不再读它）")


def test_retired_column_judgements_detect_injected_drift():
    """注入式自证：上面两条判据**都能红**（否则它们只是恒真的装饰）。

    ① 冻结种子里**别的**工序被标 `TRUE` ⇒「只有 `外帘装袋`」当场红；
    ② 终态源仍有 `TRUE` 行 ⇒「终态一律 FALSE」当场红；
    ③ 模板带该键 ⇒ 「模板不得带该键」当场红。
    """
    frozen = [{"name": "外帘装袋", "is_must_finish": "TRUE", "deleted": "0"},
              {"name": "精裁-布", "is_must_finish": "FALSE", "deleted": "0"},
              {"name": "配料", "is_must_finish": "TRUE", "deleted": "1"}]
    assert _live_seed_true_names(frozen) == ["外帘装袋"], (
        "纯函数口径与真实种子不一致（软删的 TRUE 行不得计入）⇒ 下面两条注入证不成立")

    # ① 历史值被改（多一道工序被标必完）⇒ 判据红
    drifted = frozen[:2] + [{"name": "韩褶-布", "is_must_finish": "TRUE", "deleted": "0"}]
    assert _live_seed_true_names(drifted) == ["外帘装袋", "韩褶-布"], (
        "「冻结种子的历史值」判据读不出注入的 TRUE ⇒ 它是空断言")

    # ② 终态源仍有 TRUE 行 ⇒ 判据红
    assert _live_seed_true_names([{"name": "外帘装袋", "is_must_finish": "TRUE", "deleted": "0"}]) != [], (
        "「终态源一律 FALSE」判据对注入的 TRUE 行无判别力 ⇒ 它是空断言")

    # ③ 模板带已退场键 ⇒ 判据红
    assert _template_retired_key_carriers(
        {"operations": [{"name": "外帘装袋", "is_must_finish": True},
                        {"name": "精裁-布"}]}) == ["外帘装袋"], (
        "「模板不得带该键」判据读不出注入的键 ⇒ 它是空断言")


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
    """`(部位, 工艺)` 的 9 条**字面量**种子 → **工艺维**投影 == `ROUTINGS`（**5 条**，issue #4937）。

    🔴 **去部位化（#4937）后的口径**：`routing.py::ROUTINGS` 只按**工艺**建键（9 → 5 条）。
    已发布迁移的字面量（V54 ∪ V58）仍是 `(部位, 工艺)` 的 9 行（**不可改**）⇒
    比对口径 = **投影**：每个工艺取**布帘**那一行（与价目矩阵的取价来源部位同源 ——
    用户裁定「取布帘价」；`平幔` 只有帘头一行，无歧义）。

    ⚠️ **守卫强度未降**（逐项可红）：
      · ① 9 行字面量**一条不许少**（`len(rows) == 9`，少一条即红 —— 否则投影会静默变空）；
      · ② 5 个工艺键**逐条相等**（改名 / 少一个工艺即红）；
      · ③ 每个工艺的工序序列**逐字相等**（含顺序；改一道即红）；
      · ④ 布帘行的 11 道回归锚点仍在（防整条路线被误删）。
    """
    _, routings = python_catalog
    rows = routing_rows
    assert len(rows) == 9, (
        f"V54 ∪ V58 的路线字面量应为 9 条 `(部位, 工艺)`（实际 {len(rows)}）—— "
        f"已发布迁移不可改；少一条会让下面的投影静默变空")

    parsed = {(normalize_value(r["curtain_type"]), normalize_value(r["craft"])):
              normalize_routing_operations(r["operations"]) for r in rows}
    expected = {key: tuple(ops) for key, ops in routings.items()}
    # 投影：每工艺取「布帘」行；无布帘行（`平幔`）⇒ 取该工艺唯一那一行
    projected = {}
    for (curtain_type, craft), ops in parsed.items():
        if curtain_type == "布帘" or craft not in {c for (ct, c) in parsed if ct == "布帘"}:
            projected.setdefault(craft, ops)
    assert set(projected) == set(expected), (
        f"路线**工艺键**漂移：投影得到 {sorted(projected)}，真值源 {sorted(expected)}")
    assert projected == expected, (
        f"路线内容漂移（逐条比对 **工艺** → 工序序列）："
        f"{_diff_keys(projected, expected)}")
    # 布帘·韩褶 = 11 道实证走线（回归锚点，防整条路线被误删）
    assert len(parsed[("布帘", "韩褶")]) == 11
    # 纱帘行仍在（它们是 V54 ∪ V58 的字面量；部位维**只**从 `routing.py` 的键里退场）
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
    """模板路线（`(部位, 工艺)` **9 行**）→ **工艺维**投影 == `ROUTINGS`（5 条），且逐行等于迁移聚合。

    ⚠️ 模板 JSON 与迁移 SQL 都是**字面量**（9 行，`(部位, 工艺)` 键）⇒ 它们之间仍**逐行**比对
    （两侧同构，不改口径）；只有与 `routing.py::ROUTINGS` 的比对走**投影**（见
    `test_routings_match_python` 的口径说明）。
    """
    _, routings = python_catalog
    rows = template_routings(template_json)
    parsed = {(normalize_value(r["curtain_type"]), normalize_value(r["craft"])):
              normalize_routing_operations(r["operations"]) for r in rows}
    expected = {key: tuple(ops) for key, ops in routings.items()}
    assert len(parsed) == 9, f"模板路线字面量应为 9 行（实际 {len(parsed)}）"
    projected = {}
    cloth_crafts = {ct for (ct, c) in parsed}
    for (curtain_type, craft), ops in parsed.items():
        if curtain_type == "布帘" or craft not in {c for (ct, c) in parsed if ct == "布帘"}:
            projected.setdefault(craft, ops)
    assert projected == expected, (
        f"模板路线**工艺维**投影漂移：{_diff_keys(projected, expected)}")
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
    `op-v79-*`（issue #4529 的 `配料`/`打包`）= `占位待确认`（单价留空待商家配）；
    `实证` = **空集**（客户确认 #4261/#4343 后才会有 —— 这是诚实结论，不是遗漏）。

    双向：漏标（某行 source 缺失/为空）与多标（出现 `实证`）**都红**。
    与 V62/V79 迁移的回填同口径由 `ProductionSourceProvenanceMigrationTest` 另行钉（Java 侧）。
    """
    def expected_source(op_id: str) -> str:
        if op_id.startswith("op-v54-") or op_id.startswith("op-v79-") or op_id.startswith("rt-v54-"):
            return "占位待确认"
        return "推算"

    for entry in template_json["operations"]:
        expected = expected_source(entry["id"])
        assert entry.get("source") == expected, (
            f"工序 {entry['name']} 的 source={entry.get('source')!r}，冻结映射要求 {expected!r}")
    for entry in template_json["routings"]:
        expected = expected_source(entry["id"])
        assert entry.get("source") == expected, (
            f"路线 {entry['curtain_type']}×{entry['craft']} 的 source={entry.get('source')!r}，"
            f"冻结映射要求 {expected!r}")

    sources = {e["source"] for e in template_json["operations"]} \
        | {e["source"] for e in template_json["routings"]}
    assert sources == {"占位待确认", "推算"}, (
        f"模板 source 取值集合 = {sorted(sources)}，冻结映射要求恰好 {{占位待确认, 推算}}"
        "（出现「实证」= 多标：今天没有任何工序/路线够得上实证，#4343 已证明 布帘×韩褶 与客户真实加工单不符）")
    # 🔴 issue #4937：`推算` 档 5 → **9**（新增 4 道纱帘变体，id = `op-v56-06..09` ——
    # 与 V56 同族「行业推算」档；`占位待确认` 仍是 32）
    assert sum(1 for e in template_json["operations"] if e["source"] == "占位待确认") == 32
    assert sum(1 for e in template_json["operations"] if e["source"] == "推算") == 9
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
    # 🔴 issue #4937：37 → **41**（补 4 道纱帘变体 —— `applicable` 过滤退场后它们会进纱帘路线）
    assert len(template_json["operations"]) == 41, (
        "模板工序数不是 41（35 + #4529 的 配料/打包 + issue #4937 的 4 道纱帘变体）")
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
    """多源自证：**每个**种子源的工序都被聚合读到（含 V56 的 5 道新工序 / V89 的按租户回填）。

    反例（本测试要挡的形态）：聚合退化成只读 V54 ⇒ V56 从未被行使 ⇒ #4230 的新工序
    既不在守卫射程内、又不会被任何断言照出来。

    ⚠️ **两种源形态分流**（issue #4685；与 `values_sources_for` 对 P2/V72 的分流同口径）：
    · **字面量源**（语句里有 `VALUES`）⇒ 必须 `parse_seed` 出行（原判据**不变**）；
    · **派生回填源**（`INSERT INTO production_operations … SELECT … FROM tenants`，无 `VALUES`）
      —— 行不在字面量里，它的贡献在「**按租户循环 + 幂等去重**」这个**形态**里 ⇒ 判据落在形态上。
      不给这条分流，会把合规的派生迁移判「未解析到任何工序行」（**假红**）—— 而假红比没有守卫更糟
      （会被人直接关掉，本文件自己的口径）。判据**不是放宽**：派生源多背两条形态断言，而
      `catalog_rows`（三源收敛的比对射程）本来就 `parse_seed` 不出派生源的行、不受影响。
    """
    per_source = {name: {key_of(r) for r in parse_seed(sql, "production_operations", OP_COLUMNS)}
                  for name, sql in seed_sqls}
    for name, names in per_source.items():
        if names:
            continue                      # 字面量源：原判据（必须解析出行）
        stmt = re.search(r"INSERT\s+INTO\s+production_operations\b[\s\S]*?;",
                         dict(seed_sqls)[name], re.I)
        assert stmt, (
            f"{name} 既没解析到任何工序行（无 `VALUES`）、又找不到工序 INSERT 语句 ⇒ 该源等于没被读")
        violations = derived_operation_source_violations(stmt.group(0))
        assert violations == [], f"{name} 的派生回填形态违规：{violations}"
    assert len(per_source) >= 2, "工序库种子只剩一个源（#4230 的多源口径失效）"
    assert {"绑带-纱", "logo条-布", "立边-布", "扣环-布", "防翘扣-布"} <= \
        per_source["V56__seed_special_option_operations.sql"], (
        "#4230 的 5 道新工序必须由 V56 贡献（少一个 ⇒ 实例化取不到工序 ⇒ fail-closed）")


def derived_operation_source_violations(stmt: str) -> list:
    """**派生回填源**（`INSERT INTO production_operations … SELECT … FROM tenants`，无 `VALUES`）
    的形态违规清单 —— 空 = 合规。

    为什么判「形态」而不是「行」：派生源的行由**运行时**的 `tenants` 表决定，静态文本里没有行
    （`parse_seed` 只吃 `VALUES`）。它的贡献全在「按租户循环 + 幂等去重」这个形态里
    ⇒ 判据只能落在形态上（issue #4685）。纯函数 ⇒ 注入式自证见
    `test_derived_operation_source_guard_is_load_bearing`。
    """
    out = []
    if not re.search(r"\bFROM\s+tenants\b", stmt, re.I):
        out.append("没有按租户循环（缺 `FROM tenants`）⇒ 存量租户拿不到工序 ⇒ 全量建单 422")
    if not re.search(r"\bNOT\s+EXISTS\b", stmt, re.I):
        out.append("没有按业务唯一键 `NOT EXISTS` 去重 ⇒ 不幂等（`MigrationRunner` 要求可重复执行）")
    return out


def test_derived_operation_source_guard_is_load_bearing():
    """自证（issue #4685）：派生回填源的**形态**判据真会红（两向各一例）—— 不是空断言。"""
    good = ("INSERT INTO production_operations (id, tenant_id, name)\n"
            "SELECT 'op-x-' || t.id, t.id, '打包'\n"
            "  FROM tenants t\n"
            " WHERE t.deleted = 0\n"
            "   AND NOT EXISTS (SELECT 1 FROM production_operations e WHERE e.tenant_id = t.id)\n"
            "ON CONFLICT (id) DO NOTHING")
    assert derived_operation_source_violations(good) == [], "合规形态读不出来 ⇒ 判据是空跑"
    without_loop = good.replace("FROM tenants t", "FROM (SELECT 1 AS id) t")
    assert without_loop != good, "注入未生效（`FROM tenants` 没命中）"
    assert derived_operation_source_violations(without_loop) == [
        "没有按租户循环（缺 `FROM tenants`）⇒ 存量租户拿不到工序 ⇒ 全量建单 422"]
    without_guard = good.replace("NOT EXISTS", "TRUE OR EXISTS")
    assert without_guard != good, "注入未生效（`NOT EXISTS` 没命中）"
    assert derived_operation_source_violations(without_guard) == [
        "没有按业务唯一键 `NOT EXISTS` 去重 ⇒ 不幂等（`MigrationRunner` 要求可重复执行）"]


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


def _price_rows(rows) -> dict:
    """价目行（已解析）→ `{逻辑工序: (单价|None, applicable, status)}`（**逐值**口径）。

    🔴 **键 = 逻辑工序（不是 `(逻辑工序, 部位)`）**（issue #4937）：部位退场后，矩阵的
    **终态**是「一道逻辑工序一行」⇒ 三源比对的口径随之收敛。⚠️ 若某一源里**同一逻辑工序
    出现多行**（例如只改迁移没改 schema ⇒ 120 行态），`dict` 会**静默只留最后一行**
    ⇒ 判据退化成「只要最后一行对上就算过」。为此本函数**fail-closed**：多行即抛。
    ⚠️ 已发布迁移的字面量（V71/V79/V89）**仍是 120 行态** ⇒ 必须先用
    `collapse_position_rows` 收敛（见 `position_price_rows_multi`）；`schema.sql` 的
    **终态**入口是 `schema_terminal_price_rows`。
    """
    out: dict = {}
    for r in rows:
        logical = normalize_value(r["logical_name"])
        if logical in out:
            raise AssertionError(
                f"同一逻辑工序 `{logical}` 在价目源里出现多行 —— 终态要求「一道逻辑工序一行」；"
                f"单键 dict 会静默丢掉其中一行 ⇒ 判据退化成空断言。请先核该源是否还在 120 行态")
        out[logical] = (_num_or_none(r["unit_price"]),
                        normalize_value(r["applicable"]) == "TRUE",
                        normalize_value(r["status"]))
    return out


def position_price_rows(sql: str) -> dict:
    """价目行 → `{逻辑工序: (单价|None, applicable, status)}`（**逐值**口径）。

    ⚠️ **要求输入已在终态**（一道逻辑工序一行）—— 120 行态会 fail-closed 抛错（见 `_price_rows`）。
    `docs/sql/schema.sql` 的矩阵段是 **120 行字面量**（已发布迁移的行集合必须可比对）⇒
    读 bootstrap **终态**请用 `schema_terminal_price_rows()`。
    """
    return _price_rows(parse_seed(sql, "production_operation_positions", POSITION_PRICE_COLUMNS))


def schema_terminal_price_rows(sql: str) -> dict:
    """`docs/sql/schema.sql` 的矩阵段 → **bootstrap 终态**的 `{逻辑工序: (价, 适用, status)}`。

    终态 = 「按显式 `deleted` 分流 ⇒ 存活行」+「按四档选行收敛为一道逻辑工序一行」
    （issue #4937 / **合并后的 V102**；两份判据都与生产代码同源，见 `collapse_position_rows`）。
    """
    rows = parse_seed(sql, "production_operation_positions", POSITION_PRICE_COLUMNS)
    alive = [r for r in rows if normalize_value(r.get("deleted", "0")) != "1"]
    return _price_rows(collapse_position_rows(alive))


def position_pair_rows(sql: str) -> dict:
    """价目行 → `{(逻辑工序, 部位): (单价|None, applicable, status)}`（**历史 120 行态**的入口）。

    ⚠️ 只给「必须看部位维」的判据用（如本文件 `_position_seed_drift_is_detected` 的历史解析自证）；
    **终态口径一律用 `position_price_rows`**（单键）。
    """
    return {(normalize_value(r["logical_name"]), normalize_value(r["position"])):
            (_num_or_none(r["unit_price"]), normalize_value(r["applicable"]) == "TRUE",
             normalize_value(r["status"]))
            for r in parse_seed(sql, "production_operation_positions", POSITION_PRICE_COLUMNS)}


def _template_rows(rows) -> list:
    """具名路线行（已解析）→ `[{name, is_default, positions, mainline, status}]`。"""
    return [{"name": normalize_value(r["name"]),
             "is_default": normalize_value(r["is_default"]) == "TRUE",
             "positions": normalize_routing_operations(r["positions"]),
             "mainline": normalize_routing_operations(r["mainline"]),
             "status": normalize_value(r["status"])}
            for r in rows]


def route_template_rows(sql: str) -> list:
    """具名路线行 → `[{name, is_default, positions, mainline, status}]`（有序序列 = tuple）。"""
    return _template_rows(parse_seed(sql, "production_route_templates", ROUTE_TEMPLATE_COLUMNS))


def _rule_rows(rows) -> dict:
    """规则行（已解析）→ `{(触发类型, 触发值, 部位, 动作, 工序, 锚点): priority}`。"""
    return {(normalize_value(r["trigger_kind"]), normalize_value(r["trigger_value"]),
             _text_or_none(r["position"]), normalize_value(r["action"]),
             normalize_value(r["operation"]), _text_or_none(r["after_operation"])):
            int(normalize_value(r["priority"]))
            for r in rows}


def route_rule_rows(sql: str) -> dict:
    """规则行 → `{(触发类型, 触发值, 部位, 动作, 工序, 锚点): priority}`（`NULL` → `None`）。"""
    return _rule_rows(parse_seed(sql, "production_route_rules", ROUTE_RULE_COLUMNS))


def _aggregate_text(seed_paths) -> str:
    """把按内容发现的一组种子迁移**拼成一份文本**（多源聚合，版本号序）。"""
    return "\n".join(path.read_text(encoding="utf-8") for path in seed_paths)


def _parse_each(seed_paths, table: str, columns) -> list:
    """**逐源**解析后合并（多源聚合的唯一正确形态，issue #4529）。

    ⚠️ 不能先 `_aggregate_text` 再 `parse_seed`：`parse_seed` 只认**第一条**
    `INSERT INTO <table> … VALUES`（按 `;` 截断）⇒ 拼接后的文本只解析出**第一个源**的行
    （V79 的 36 格价目 / 布料路线会被**静默漏掉** ⇒ 「绿了但没跑」，同族形态见 #4235）。
    自证 = `test_new_route_seed_sources_are_discovered_and_nonempty`（逐源断言非空）。
    """
    rows = []
    for path in seed_paths:
        rows += parse_seed(path.read_text(encoding="utf-8"), table, columns)
    return rows


#: 四档选行规则的「布帘列」字面量（与 `routing.py::COLLAPSE_PRICE_SOURCE_POSITION` /
#: Java `ProductionOperationQueryService.COLLAPSE_PRICE_SOURCE_POSITION` / 合并后的 `V102` 的 SQL **同值**；
#: 跨语言/跨文件同值由 `test_deposition_total_migration.py` 的
#: `test_java_collapse_source_position_matches_the_sql_literal` 与
#: `tests/test_production/test_position_collapse_mirror.py` 钉）。
COLLAPSE_PRICE_SOURCE_POSITION = "布帘"


def collapse_position_rows(rows: list) -> list:
    """**四档选行**：`(逻辑工序, 部位)` 多行 → 每逻辑工序一行（issue #4937 的终态口径）。

    档序 = ① `applicable IS TRUE` 优先 ② `position = '布帘'` 优先 ③ `position` 字典序
    ④ `id` 升序 —— **与 `ProductionOperationQueryService#collapseToLogical` / 合并后的 `V102` 的
    SQL 逐档同序**（三处同序由各自的守卫钉；这里**不另发明一套**）。

    ⚠️ 迁移侧的字面量（V71/V79/V89）是**已发布迁移**、仍是 120 行态 ⇒ 必须先在测试侧按
    同一规则收敛到 30 行，才能与 `routing.py` / `schema.sql` 的终态逐值比对。
    """
    grouped: dict = {}
    for row in rows:
        logical = normalize_value(row["logical_name"])
        grouped.setdefault(logical, []).append(row)

    def rank(row):
        return (0 if normalize_value(row["applicable"]) == "TRUE" else 1,
                0 if normalize_value(row["position"]) == COLLAPSE_PRICE_SOURCE_POSITION else 1,
                normalize_value(row["position"]), normalize_value(row["id"]))

    out = []
    for logical in sorted(grouped):
        out.append(sorted(grouped[logical], key=rank)[0])
    return out


def position_price_rows_multi(seed_paths) -> dict:
    """多源（逐源解析 + 拼接）→ **收敛后**的 `{逻辑工序: (价, 适用, status)}`（30 行）。"""
    rows = _parse_each(seed_paths, "production_operation_positions", POSITION_PRICE_COLUMNS)
    return _price_rows(collapse_position_rows(rows))


def position_pair_rows_multi(seed_paths) -> dict:
    """`position_pair_rows` 的**多源逐源解析**版（历史 120 行态；见该函数的说明）。"""
    out: dict = {}
    for path in seed_paths:
        out.update(position_pair_rows(path.read_text(encoding="utf-8")))
    return out


def route_template_rows_multi(seed_paths) -> list:
    return _template_rows(_parse_each(seed_paths, "production_route_templates",
                                      ROUTE_TEMPLATE_COLUMNS))


def route_rule_rows_multi(seed_paths) -> dict:
    return _rule_rows(_parse_each(seed_paths, "production_route_rules", ROUTE_RULE_COLUMNS))


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


def _fabric_truth() -> tuple:
    """布料路线的真值源（issue #4529）→ `(部位, 主线, 模板名)`。"""
    sys.path.insert(0, str(ROUTING_PY_DIR))
    try:
        from app.production.routing import (
            FABRIC_MAINLINE_STEPS, FABRIC_POSITION, FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT,
        )
        return FABRIC_POSITION, FABRIC_MAINLINE_STEPS, FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT
    finally:
        sys.path.pop(0)


def _truth_price_rows() -> dict:
    """真值源 `OPERATION_POSITION_PRICES` → `{逻辑工序: (价, 适用, status)}`（**单键**，issue #4937）。

    ⚠️ 本表原来是 `[逻辑工序][部位]` 两级；部位退场后只按逻辑工序建键 —— 三源比对的键随之收敛。
    """
    prices, _, _, _ = _route_v2_truth()
    return {logical: (None if cell["unit_price"] is None else float(cell["unit_price"]),
                      bool(cell["applicable"]), "active")
            for logical, cell in prices.items()}


def _truth_rule_rows() -> dict:
    """真值源 `ROUTE_RULES` → `{(触发类型, 触发值, 动作, 工序, 锚点): priority}`。

    🔴 **`position` 维已退场**（issue #4937 / O2）：`routing.py` 的规则字典**不再有该键**，
    终态 SQL 侧一律 `NULL` ⇒ 本键元组随之收敛（三源都按同一口径比对）。
    """
    _, _, rules, _ = _route_v2_truth()
    return {(r["trigger_kind"], r["trigger_value"], r["action"],
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
    """价目**三源逐值一致**：`routing.py` ↔ V71 ∪ V79 ∪ V89（+ 合并后的 `V102` 的终态改写）↔ `schema.sql`。

    🔴 **issue #4937（去部位化彻底版）之后的键 = 逻辑工序**（一道一行，**30 行**）：
    部位退场 ⇒ 三源比对的口径从 `(逻辑工序, 部位)` 收敛为 `逻辑工序`。
    ⚠️ 所有三源**此刻都是 120 行态**（V71/V79/V89 的字面量是已发布迁移、不可改），
    而**终态**（`ProductionOperationQueryService#collapseToLogical` 的四档选行）把 120 行收敛成 30 行
    ⇒ 本判据比对的是**收敛后**的 30 行：`{逻辑工序: (价, 适用, status)}`。

    **守卫强度未降**（逐项可红）：
      · ① **改名**：`routing.py` 的键与 SQL 的 `logical_name` 逐条相等 ⇒ 改任一侧即红；
      · ② **改价**：`_num_or_none` 逐值比 ⇒ 价漂移即红（含「有价 → 未定价」）；
      · ③ **翻适用**：`applicable` 逐值比 ⇒ 即红；
      · ④ **加减行**：三源行数**都**必须恰好 30（`len(...) == 30` 三条断言）⇒ 少一道/多一道即红；
      · ⑤ **多行不静默**：`_price_rows` 对「同一逻辑工序多行」**fail-closed 抛错** ⇒
        「只改一处、另一处还在旧口径」不可能被静默吞掉。

    ⚠️ 多源必须**逐源解析**：先拼接再解析只会读到第一个源（V79 的 36 行被静默漏掉，「绿了但没跑」）。
    """
    truth = _truth_price_rows()
    migration = position_price_rows_multi(POSITION_SEED_SQLS)
    bootstrap = schema_terminal_price_rows(schema_sql)
    assert len(truth) == 30, f"真值源的价目不是 30 行（一道逻辑工序一行）：{len(truth)}"
    assert len(migration) == 30, f"迁移侧的价目不是 30 行：{len(migration)}"
    assert len(bootstrap) == 30, f"bootstrap 的价目不是 30 行：{len(bootstrap)}"
    assert migration == truth, f"价目：迁移侧 ≠ routing.py：{_diff_keys(migration, truth)}"
    assert bootstrap == truth, (
        f"价目：schema.sql 终态 ≠ routing.py：{_diff_keys(bootstrap, truth)} —— "
        f"价/适用性/状态任一漂移即红")
    # 自证（防空跑）：真值源里**既有有价行也有未定价行**，否则「价逐值比」这一半可能空转
    assert any(v[0] is not None for v in truth.values()), "真值源全是未定价 ⇒ 价判据空跑"
    assert any(v[0] is None for v in truth.values()), "真值源全是定价 ⇒ 「未定价」判据空跑"
    assert {v[1] for v in truth.values()} == {True}, (
        "终态要求**每一行都适用**（部位维退场后 applicable 不再是筛选器）："
        f"{sorted({v[1] for v in truth.values()})}")


def _position_seed_drift_is_detected():
    """自证（供 `test_price_row_parser_detects_injected_drift` 复用）：键/值任一漂移都读得出来。

    这里用的是**单键**口径（终态口径）—— 与三源比对同源，避免「自证用一套口径、比对用另一套」。
    """
    good = (
        "INSERT INTO production_operation_positions "
        "(id, tenant_id, logical_name, position, unit_price, applicable, status) VALUES\n"
        "  ('opp-1', 1, '熨烫', '通用', 0.35, TRUE, 'active'),\n"
        "  ('opp-2', 1, '打包', '通用', NULL, TRUE, 'active')\n"
        "ON CONFLICT (id) DO NOTHING;")
    base = position_price_rows(good)
    assert base["熨烫"] == (0.35, True, "active"), "价目解析器没读出合法行"
    assert base["打包"][0] is None, "价目解析器没读出 NULL 价（未定价）"
    assert position_price_rows(good.replace("0.35", "0.99")) != base, \
        "改单价读不出来 ⇒ 三源比对是空断言"
    assert position_price_rows(good.replace("'打包', '通用', NULL, TRUE", "'打包', '通用', NULL, FALSE")) != base, \
        "翻 applicable 读不出来 ⇒ 适用性比对是空断言"
    assert position_price_rows(good.replace("'熨烫', '通用', 0.35, TRUE", "'三边', '通用', 0.35, TRUE")) != base, \
        "改逻辑工序名读不出来 ⇒ 键比对是空断言"
    # 多行刻意 fail-closed（不许静默只留最后一行）
    import pytest as _pytest
    with _pytest.raises(AssertionError, match="出现多行"):
        position_price_rows(good.replace(
            "  ('opp-2', 1, '打包', '通用', NULL, TRUE, 'active')",
            "  ('opp-2', 1, '打包', '通用', NULL, TRUE, 'active'),\n"
            "  ('opp-3', 1, '熨烫', '布帘', 0.99, TRUE, 'active')"))


def test_route_template_converges_across_three_sources(schema_sql):
    """具名路线三源逐值一致（**2 行**：窗帘默认 + 布料，issue #4529）。"""
    _, mainline, _, name = _route_v2_truth()
    fabric_position, fabric_mainline, fabric_name = _fabric_truth()
    truth = [
        {"name": name, "is_default": True,
         "positions": ("布帘", "纱帘", "帘头"), "mainline": tuple(mainline), "status": "active"},
        {"name": fabric_name, "is_default": False,
         "positions": (fabric_position,), "mainline": tuple(fabric_mainline), "status": "active"},
    ]
    migration = route_template_rows_multi(TEMPLATE_SEED_SQLS)
    assert len(migration) == 2, (
        f"迁移侧的具名路线不是 2 行（窗帘默认 + 布料）：{len(migration)} —— "
        f"每租户恰好两条基础路线（issue #4529）"
    )
    # ⚠️ 迁移链的**终态** = 字面量种子 + V79 的手术式 `打包` 插入（V71 已发布 ⇒ 不可改，
    #    窗帘路线的 10 道只能由新迁移补）。这里按 V79 的语义把字面量升到终态再比对真值源。
    assert [r for r in migration if r["is_default"]][0]["mainline"] == \
        tuple(s for s in mainline if s != "打包"), (
        "窗帘路线的**字面量**种子漂移（V71 的 9 道）—— 第 10 道 `打包` 由 V79 的 UPDATE 追加，"
        "两处都要与真值源一致"
    )
    terminal = _with_v88_fabric_mainline_rewrite(_with_packing_on_default_route(migration))
    assert terminal == truth, (
        f"具名路线（迁移链终态 = V71 字面量 + V79 的打包插入 + V88 ③ 的 `配料` → `裁剪`）"
        f"≠ routing.py：{terminal} ≠ {truth}"
    )
    # 🔴 **口径折算已撤（issue #4952）**：真值源 `routing.py::FABRIC_MAINLINE_STEPS` 已改判为
    # `裁剪 → 打包`（= V88 ③ 之后的终态）⇒ bootstrap 与真值源**逐字直比**，不再有「把 bootstrap
    # 折回旧口径」这一步（那套折算机制一旦不再需要就是死账）。任何一侧漂移即红 —— 含真值源
    # 回退成 `配料`（本单的红证形态）。
    assert route_template_rows(schema_sql) == truth, (
        f"具名路线：schema.sql 终态 ≠ routing.py（bootstrap 库与迁移库路线不同）："
        f"{route_template_rows(schema_sql)} ≠ {truth}")


def _with_v88_fabric_mainline_rewrite(rows: list) -> list:
    """把**字面量**种子升到迁移链终态：套用 `V88` ③ 的 `配料` → `裁剪` 元素替换。

    ⚠️ **这不是「口径折算」**（那种「把终态折回真值源旧口径」的机制已随 issue #4952 删除）——
    它是**读被测实现**：迁移链的终态 = 字面量种子 + V88 ③ 的 `UPDATE … jsonb_agg(CASE WHEN
    elem = '"配料"' THEN '"裁剪"')`（V79 是**已发布迁移**、不可改 ⇒ 第 2 道只能由 V88 补）。
    替换表从 `V88` 正文里读（同 `test_fabric_route_seed.py::_v88_fabric_mainline_rewrite` 口径），
    不写死；V88 缺席 ⇒ 空表 ⇒ 布料主线退回 `配料 → 打包` ⇒ 本判据红。
    """
    rewrite = _v88_fabric_mainline_rewrite()
    out = []
    for row in rows:
        if row["is_default"] or row["positions"] != ("布料",):
            out.append(row)
            continue
        out.append({**row, "mainline": tuple(rewrite.get(s, s) for s in row["mainline"])})
    return out


def _v88_fabric_mainline_rewrite() -> dict:
    """`V88` ③ 的**元素替换表**（`配料` → `裁剪`）；V88 缺席 / 没有该替换 ⇒ 空表（⇒ 判据红）。"""
    path = MIGRATION_DIR / "V88__retire_material_prep_and_fabric_position.sql"
    if not path.exists():
        return {}
    body = "\n".join(line for line in path.read_text(encoding="utf-8").split("\n")
                     if not line.lstrip().startswith("--"))
    if not re.search(r"""elem\s*=\s*'"配料"'\s*::jsonb\s+THEN\s+'"裁剪"'""", body):
        return {}
    return {"配料": "裁剪"}


def _with_packing_on_default_route(rows: list) -> list:
    """把真值源升到**迁移链终态**：默认路线的 9 道 + V79 插入的 `打包`（插在 `外帘装袋` 之前）。

    V71 已发布（不可改）⇒ 窗帘路线的第 10 道只能由 V79 的 UPDATE 补；本函数复刻那一行的语义，
    使「迁移链终态」可与字面量种子逐值比对（V79 侧的实际写法由
    `test_fabric_route_seed.py::test_curtain_mainline_carries_packing_in_every_source` 另钉）。
    """
    out = []
    for row in rows:
        if not row["is_default"] or "打包" in row["mainline"]:
            out.append(row)
            continue
        steps = list(row["mainline"])
        idx = steps.index("外帘装袋")
        out.append({**row, "mainline": tuple(steps[:idx] + ["打包"] + steps[idx:])})
    return out


def test_route_rules_converge_across_three_sources(schema_sql):
    """规则表三源**逐行逐值**一致（26 行：工艺 10 + 特殊选项 16，含 priority）。

    🔴 **本判据的比对键不含 `position`**（2026-09-21 / #4962 口径改判）：部位维**保留**在
    `production_route_rules.position` 上（#4962 要用它做「适用条件 = 部位」的筛选），
    但**真值源** `routing.py` 的规则字典里**没有**该键（`backend/ai-agent-service` 不在本单射程）
    ⇒ 三源比对只能按「去掉该维」的键做；`position` 那一维的终态由
    `test_rule_positions_are_kept_across_seed_and_bootstrap` **单独**钉
    （迁移字面量 ↔ bootstrap 镜像逐条逐值一致 + 唯一那条部位限定必须是 `布帘`）。
    """
    truth = _truth_rule_rows()
    migration = route_rule_rows_multi(RULE_SEED_SQLS)
    bootstrap = route_rule_rows(schema_sql)
    # 比对键统一去掉 `position` 维（真值源没有该键 —— 它不在本单射程内）
    migration = {(k[0], k[1], k[3], k[4], k[5]): v for k, v in migration.items()}
    bootstrap = {(k[0], k[1], k[3], k[4], k[5]): v for k, v in bootstrap.items()}
    assert len(truth) == 26, f"真值源的规则不是 26 条：{len(truth)}"
    assert len(migration) == 26, f"迁移侧的规则不是 26 条：{len(migration)}"
    assert len(bootstrap) == 26, f"bootstrap 的规则不是 26 条：{len(bootstrap)}"
    assert migration == truth, f"规则表：迁移侧 ≠ routing.py：{_diff_keys(migration, truth)}"
    assert bootstrap == truth, f"规则表：schema.sql 终态 ≠ routing.py：{_diff_keys(bootstrap, truth)}"
    # 自证：真值源里**确实没有** position 键（O2 的判据落点），且迁移侧的原始字面量里**有**一条
    # （否则上面的「去掉该维」是空操作 ⇒ 判据可能空跑）
    py_rules, _, _, _ = _route_v2_truth()
    assert not any("position" in r for r in py_rules), "routing.py 的规则仍有 `position` 键（O2 未完成）"
    raw_migration = route_rule_rows_multi(RULE_SEED_SQLS)
    assert any(k[2] is not None for k in raw_migration), (
        "迁移侧的字面量里没有任何 `position` 非 NULL 的规则 ⇒ 本判据的「归一」是空操作")


def test_rule_positions_are_kept_across_seed_and_bootstrap(schema_sql):
    """🔴 **#4962 口径改判**：部位维**保留**在 `production_route_rules.position` 上，且两源逐字一致。

    **改判要点（换对象，不削弱）**：原判据要求「`routing.py` 无该键 / `schema.sql` 字面量清空 /
    `V103` 把 `position` 置 `NULL`」三件事同时成立 —— 那是「部位维**退场**」的口径。
    用户 2026-09-21 裁定「结合新的需求（**#4962 适用条件加回部位维**）统一考量」⇒ 部位维
    **只允许活在一个地方** = `production_route_rules.position`；`V103`（清空 `position`）的意图
    **已作废** ⇒ 该迁移文件被删除（**删除即撤销**），bootstrap 镜像也要**恢复**成 `'布帘'`。
    ⇒ 本判据改钉**保留侧的终态**，三条都**可红**：
      ① `V103__clear_route_rule_positions.sql` **不存在**（谁把清空意图加回来即红）；
      ② 迁移侧字面量（`V71`）与 bootstrap 镜像（`docs/sql/schema.sql`）的 `position`
         **逐条逐值一致**（改任一侧即红）；
      ③ 唯一那条部位限定的种子规则 `韩褶 → insert 上车布` 的 `position` **逐字 = `'布帘'`**
         （改成 `NULL` 或别的部位即红 —— 上一版当时按已删除的 `V103` 把它镜像成了 `NULL`）。

    **自证（防空跑）**：迁移侧至少有一条 `position` 非 `NULL`（否则「逐条比对」恒真）。
    """
    assert not (MIGRATION_DIR / "V103__clear_route_rule_positions.sql").exists(), (
        "`V103__clear_route_rule_positions.sql` 又出现了 —— 它「清空 "
        "`production_route_rules.position`」的意图**已作废**（#4962 要把部位维加回来，"
        "见 issue #4936 / #4962 的裁定）⇒ 不得复活；部位维的唯一载体就是这一列")

    migration = {(k[0], k[1], k[3], k[4], k[5]): k[2]
                 for k in route_rule_rows_multi(RULE_SEED_SQLS)}
    bootstrap = {(k[0], k[1], k[3], k[4], k[5]): k[2] for k in route_rule_rows(schema_sql)}
    assert migration, "迁移侧的规则字面量一行都没解析出来 ⇒ 本判据会空跑"
    assert any(pos is not None for pos in migration.values()), (
        "迁移侧没有任何 `position` 非 NULL 的规则 ⇒ 「逐条比对」是空操作（红证前提不成立）")
    assert len(migration) == 26, f"迁移侧的规则键数 = {len(migration)}，期望 26（判据会空跑？）"
    assert len(bootstrap) == 26, f"bootstrap 的规则键数 = {len(bootstrap)}，期望 26"

    drifted = {k: (migration.get(k), bootstrap.get(k)) for k in set(migration) | set(bootstrap)
               if migration.get(k) != bootstrap.get(k)}
    assert drifted == {}, (
        f"`production_route_rules.position` 在「迁移字面量」与「bootstrap 镜像」之间漂移"
        f"（前 = 迁移侧，后 = bootstrap）：{drifted} —— 部位维是 #4962 的唯一载体，两源必须逐字一致")

    # ⚠️ `migration` 的键已**去掉 position 维** ⇒ 五元组 = (触发类型, 触发值, 动作, 工序, 锚点)
    hz = [k for k in migration
          if k[0] == "craft" and k[1] == "韩褶" and k[2] == "insert" and k[3] == "上车布"]
    assert len(hz) == 1, f"找不到唯一的「韩褶 → insert 上车布」种子规则（判据会空跑）：{hz}"
    assert migration[hz[0]] == "布帘", (
        f"`韩褶 → insert 上车布` 的 `position` = `{migration[hz[0]]}`，期望 `布帘` —— "
        f"它是**唯一**那条部位限定的种子规则（`V71` 的终态）")
    assert bootstrap[hz[0]] == "布帘", (
        f"bootstrap 镜像里那条规则的 `position` = `{bootstrap[hz[0]]}`，期望 `布帘`"
        f"（上一版当时按已被删除的 `V103` 把它镜像成了 NULL ⇒ 新建库与存量库口径分裂）")

    # 🔴 **#4962 新增（存量库路径）**：部位限定必须由**新增**迁移写回。
    # ⚠️ `V103`（清空 `position`）已随 **#4936 的重写**被删除（其意图作废）⇒ 这里**不得**再断言它存在；
    # 但「跑过迁移链的存量库」与「bootstrap 新建库」必须同终态 ⇒ 由 `V108` 幂等写回（`position IS NULL` 才写）。
    v108 = MIGRATION_DIR / "V108__restore_route_rule_positions.sql"
    assert v108.exists(), (
        "缺 `V108__restore_route_rule_positions.sql` ⇒ 存量库里那条部位限定永远是 NULL = "
        "「规则已落库但永不生效」，而只有全新库才对（#4235 同族：CI 全绿、功能静默缺失）")
    v108_body = sql_code(v108.read_text(encoding="utf-8"))
    assert re.search(r"SET\s+position\s*=\s*'布帘'", v108_body), (
        "V108 没有把那条规则的 `position` 写回 `布帘`")
    assert re.search(r"position\s+IS\s+NULL", v108_body), (
        "V108 缺幂等谓词（`position IS NULL` 才写）⇒ 重跑会覆盖商家改过的值")


def test_new_route_operations_all_have_a_price_row(schema_sql):
    """主线与规则引用的工序名都必须落在**已落库的逻辑工序集合**里（否则实例化无价可依）。

    双向：`mainline` / `operation` / `after_operation` 逐条点名，缺一个即红（点名到工序名，
    不是只给一句 assert）。
    """
    _, mainline, rules, _ = _route_v2_truth()
    _, fabric_mainline, _ = _fabric_truth()
    seeded = set(position_price_rows_multi(POSITION_SEED_SQLS))
    for label, steps in (("窗帘主线", mainline), ("布料主线", fabric_mainline)):
        assert set(steps) <= seeded, \
            f"{label}引用了没有价目行的工序：{sorted(set(steps) - seeded)}"
    for rule in rules:
        assert rule["operation"] in seeded, \
            f"规则 {rule['trigger_value']} 引用了没有价目行的工序：{rule['operation']}"
        if rule["after_operation"] is not None:
            assert rule["after_operation"] in seeded, \
                f"规则 {rule['trigger_value']} 的锚点没有价目行：{rule['after_operation']}"
    # schema.sql 侧同样钉（bootstrap 库的价目行集合必须覆盖两条主线）
    bootstrap_seeded = set(schema_terminal_price_rows(schema_sql))
    assert set(mainline) <= bootstrap_seeded
    assert set(fabric_mainline) <= bootstrap_seeded


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
    # ⚠️ #4937 之后**终态是一道逻辑工序一行** ⇒ 夹具随之改成两行两个工序（不再是同工序两部位）
    good_positions = (
        "INSERT INTO production_operation_positions "
        "(id, tenant_id, logical_name, position, unit_price, applicable, status) VALUES\n"
        "  ('opp-1', 1, '熨烫', '通用', 0.35, TRUE, 'active'),\n"
        "  ('opp-2', 1, '打包', '通用', NULL, TRUE, 'active')\n"
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
    assert base_prices["熨烫"] == (0.35, True, "active"), "价目解析器没读出合法行"
    assert base_prices["打包"][0] is None, "价目解析器没读出 NULL 价（未定价）"
    assert position_price_rows(good_positions.replace("0.35", "0.99")) != base_prices, \
        "改单价读不出来 ⇒ 价目三源比对是空断言"
    assert position_price_rows(good_positions.replace(
        "'打包', '通用', NULL, TRUE", "'打包', '通用', NULL, FALSE")) != base_prices, \
        "翻 applicable 读不出来 ⇒ 适用性比对是空断言"
    assert position_price_rows(good_positions.replace(
        "'熨烫', '通用', 0.35, TRUE", "'三边', '通用', 0.35, TRUE")) != base_prices, \
        "改逻辑工序名读不出来 ⇒ 键比对是空断言"

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


# ── ⑧ D5 豁免（issue #4525）：`customer_unit_price` 不进 `routing.py::ROUTE_RULES` ──
#
# 用户裁定 2026-09-19：「Agent 的暂时都先豁免，等后面统一来重构 agent」（设计 §2 的 D5）
# ⇒ 本方案的**对客按套单价**（V77 的 `production_route_rules.customer_unit_price`）**不**进
# `app/production/routing.py` 的 `ROUTE_RULES`（agent 侧真值源）。
#
# ⚠️ **这是债务，不是终态**（`migao-dev-flow` §19.1：豁免登记为**债务类**，只许缩短）。
# 代价：三源收敛守卫（`routing.py` ↔ 迁移 ↔ `schema.sql`）对本列**无覆盖** —— 本列的值
# 目前只有 V77 一个来源，`routing.py` 若将来也要用对客价，必须走「改 `ROUTE_RULES` + 新迁移」
# 的正常路径，而不是在这里追加豁免。销账时机 = agent 侧统一重构（#4525 的 D5 边界）。

#: D5 豁免登记（**列名 → 销账条件**）。新增条目必须同时给出销账条件，否则豁免会变成永久黑洞。
D5_DEBT_EXEMPTIONS = {
    "customer_unit_price": "待 agent 侧统一重构时把对客单价并入 routing.py::ROUTE_RULES 并销账（#4525 D5）",
}


def test_customer_unit_price_is_an_explicit_debt_exemption():
    """V77 的对客单价列必须在**这里显式登记豁免**，且 `routing.py` 侧确实还没有它。

    双向：
    ① 若 `routing.py` 的 `ROUTE_RULES` 已带上 `customer_unit_price`（agent 重构落地）⇒
       **豁免必须销账**（本断言红，提示删掉 `D5_DEBT_EXEMPTIONS` 里的条目）——
       否则豁免会静默变成「永久无视收敛漂移」；
    ② 若迁移侧压根没有该列（V77 丢了）⇒ 豁免成了无对象的空登记（红）。
    """
    rule_columns = set(ROUTE_RULE_COLUMNS)
    assert "customer_unit_price" in D5_DEBT_EXEMPTIONS, "D5 豁免未登记"
    assert all(reason.strip() for reason in D5_DEBT_EXEMPTIONS.values()), \
        "D5 豁免必须写清**销账条件**（按 §19.1 记为债务类，不是永久豁免）"

    # ② 迁移侧真有该列（否则豁免无对象）
    migration_sql = _aggregate_text(RULE_SEED_SQLS)
    ddl = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(MIGRATION_DIR.glob(MIGRATION_GLOB),
                                                     key=lambda p: version_key(p.name))
        if "customer_unit_price" in p.read_text(encoding="utf-8"))
    assert re.search(r"customer_unit_price\s+NUMERIC\(12,\s*2\)", ddl, re.I), \
        "迁移侧没有 customer_unit_price 列 ⇒ D5 豁免是无对象的空登记（V77 丢了？）"
    assert "customer_unit_price" not in rule_columns, (
        "ROUTE_RULE_COLUMNS 里出现了 customer_unit_price —— 若这是 agent 重构落地，"
        "请**销账** D5_DEBT_EXEMPTIONS 条目并同步 routing.py 真值源（不要留着豁免）")

    # ① `routing.py::ROUTE_RULES` 侧确实还没有该键（豁免成立的前提）
    _, _, rules, _ = _route_v2_truth()
    assert rules, "routing.py 的 ROUTE_RULES 读不到（豁免判据是空跑）"
    assert all("customer_unit_price" not in rule for rule in rules), (
        "routing.py::ROUTE_RULES 已带上 customer_unit_price ⇒ D5 豁免必须销账"
        "（删掉 D5_DEBT_EXEMPTIONS 的条目，让三源收敛守卫接管本列）")
    # 自证：本判据读的确实是迁移文本（注入法 —— 换一段不含该列的文本 ⇒ 上面的正则断言会红）
    assert "customer_unit_price" in ddl and migration_sql  # 非空自证（避免空跑）


def test_d5_exemption_guard_detects_injected_regression(tmp_path):
    """注入式自证：给一个**假的**迁移目录（含该列）⇒ ① 的判据仍然成立且能读出来。

    本测试要挡的形态：`ddl` 的发现逻辑退化成「扫不到任何文件 ⇒ 空串 ⇒ 断言恒真」。
    """
    (tmp_path / "V99__x.sql").write_text(
        "ALTER TABLE production_route_rules ADD COLUMN IF NOT EXISTS "
        "customer_unit_price NUMERIC(12,2);", encoding="utf-8")
    ddl = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(tmp_path.glob(MIGRATION_GLOB),
                                                     key=lambda p: version_key(p.name))
        if "customer_unit_price" in p.read_text(encoding="utf-8"))
    assert re.search(r"customer_unit_price\s+NUMERIC\(12,\s*2\)", ddl, re.I), \
        "按内容发现迁移的判据读不出注入的列 ⇒ 它是空断言"
    # 反向：不含该列的迁移**不得**被收进来（否则「发现逻辑」会把所有迁移都算成 DDL 来源）
    (tmp_path / "V98__y.sql").write_text(
        "ALTER TABLE production_route_rules ADD COLUMN IF NOT EXISTS factor NUMERIC(6,3);",
        encoding="utf-8")
    ddl2 = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(tmp_path.glob(MIGRATION_GLOB),
                                                     key=lambda p: version_key(p.name))
        if "customer_unit_price" in p.read_text(encoding="utf-8"))
    assert "factor NUMERIC(6,3)" not in ddl2, "按内容发现的过滤条件失效（收了不含该列的文件）"


# ══════════════════════════════════════════════════════════════════════════════════
# 计件系数档**退场**（issue #4589，用户裁定 2026-09-19）
#
# 用户原话：「工序项当前的计件单价就是满足的，包工工资在计件工资体现，算法是
# **数量 × 计件单价**，不需要考虑系数」⇒ 系数从算法与数据里退场。
#
# 数据侧 = 新迁移把 `production_route_rules` 里 `action='factor'` 的**活跃行软删**
# （`deleted=1`，留痕不物理删）；列 `factor` 与历史快照列**保留**（当时工资的证据）。
# ⚠️ 本判据是 **L0 静态**判据（admin-api 无 testcontainers ⇒ 表内容判据落不到真库上）；
#    「真库里活跃行 = 0」由迁移语句本身保证（`WHERE action='factor' AND deleted=0`），
#    本判据钉住该语句的**形态**（少任一条件就会误伤别的行 / 变成非幂等）。
# ══════════════════════════════════════════════════════════════════════════════════

_SQL_COMMENT_RE = re.compile(r"--[^\n]*")


def sql_code(text: str) -> str:
    """剥掉 `--` 行注释后的 SQL 正文。

    🔴 **必须剥**：本仓迁移的**回滚 SQL 就写在注释里**（如 V72 的
    `-- ALTER TABLE production_route_rules DROP COLUMN IF EXISTS factor;`）⇒ 不剥会把
    回滚注释读成"真的删了列"（假红）。本函数自身由注入式用例自证（见文件末）。
    """
    return _SQL_COMMENT_RE.sub("", text)


def factor_retire_statements(migration_dir: Path = MIGRATION_DIR) -> list:
    """按**内容**发现「软删系数档」语句（新增迁移无需改本文件）→ [(路径, 语句正文)]。"""
    directory = Path(migration_dir)
    pattern = re.compile(
        r"UPDATE\s+production_route_rules\b(?P<body>[\s\S]*?);", re.I)
    out = []
    for path in sorted(directory.glob(MIGRATION_GLOB), key=lambda p: version_key(p.name)):
        for match in pattern.finditer(sql_code(path.read_text(encoding="utf-8"))):
            body = match.group("body")
            if re.search(r"\bdeleted\s*=\s*1", body, re.I) and \
                    re.search(r"action\s*=\s*'factor'", body, re.I):
                out.append((path, body))
    return out


def factor_retire_shape_errors(path_name: str, body: str) -> list:
    """软删语句的**形态判据** → 违规原因列表（空 = 合规）。抽成函数是为了让注入式用例复用。"""
    errors = []
    if re.search(r"DELETE\s+FROM\s+production_route_rules", body, re.I):
        errors.append("物理删了规则行 —— 本单要求**软删**（`SET deleted = 1`，留痕可回滚/可审计）")
    if not re.search(r"\bdeleted\s*=\s*1", body, re.I):
        errors.append("没有把 deleted 置 1")
    if not re.search(r"action\s*=\s*'factor'", body, re.I):
        errors.append("没有限定 `action = 'factor'` ⇒ 会把 insert/remove 的路线规则也软删（路线消失）")
    if not re.search(r"\bdeleted\s*=\s*0", body, re.I):
        errors.append("没有限定 `deleted = 0` ⇒ 非幂等（重复执行会刷新已软删行）")
    if not re.search(r"updated_at\s*=\s*NOW\(\)", body, re.I):
        errors.append("没有同步 `updated_at`（本仓迁移的既有口径）")
    return [f"{path_name}: {e}" for e in errors]


def test_factor_retire_migration_is_discovered_and_nonempty():
    """自证（fail-closed）：软删语句必须**被读到**（空集 ⇒ 下面的形态判据全部空转）。"""
    found = factor_retire_statements()
    assert found, (
        "未发现任何「软删 production_route_rules 里 action='factor' 活跃行」的迁移语句"
        "（`UPDATE … SET deleted = 1 … WHERE action = 'factor'`）⇒ 本段判据退化成空跑")


def test_factor_rules_are_soft_deleted_not_dropped():
    """判据 1（#4589）：系数档**软删**（`deleted = 1`）—— 不物理删，且只碰活跃的 factor 行。

    四个条件各挡一种误伤：① `DELETE FROM` ⇒ 丢留痕（不可回滚、不可审计）；
    ② 少 `action='factor'` ⇒ 把 insert/remove 的路线规则也软删（**路线消失**，工序全没了）；
    ③ 少 `deleted = 0` ⇒ 非幂等；④ 漏 `updated_at` ⇒ 与既有迁移口径不一致。
    """
    errors = []
    for path, body in factor_retire_statements():
        errors += factor_retire_shape_errors(path.name, body)
    assert errors == [], "软删语句形态不合规：\n" + "\n".join(errors)


def test_factor_retire_keeps_the_column_and_history():
    """判据 2（#4589）：**列保留** —— 退场迁移里不得出现 `DROP COLUMN …factor` / `DROP TABLE`。

    理由：`production_route_rules.factor`（历史系数档）与
    `processing_position_operations.factor` / `production_work_logs.factor`（历史快照/报工）
    上的值是**当时工资的证据**（真值源 §4「逐笔可追溯」）⇒ 历史不回溯、不重算、不写回填脚本。
    ⚠️ 只看**退场迁移自己**（按内容发现）+ **剥掉行注释**：V72 的回滚 SQL 注释里就有
    `DROP COLUMN IF EXISTS factor`，不剥注释会假红。
    """
    for path, _ in factor_retire_statements():
        code = sql_code(path.read_text(encoding="utf-8"))
        assert not re.search(r"DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?factor\b", code, re.I), (
            f"{path.name} 删掉了 factor 列 —— 历史快照/报工上的值是当时工资的证据，列必须保留")
        assert not re.search(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?production_route_rules\b",
                             code, re.I), f"{path.name} 删掉了规则表"


def test_bootstrap_schema_also_retires_factor_rows(schema_sql):
    """判据 3（#4589）：bootstrap（`docs/sql/schema.sql`）**同样**软删 —— 两条路径终态一致。

    bootstrap 路径（docker-entrypoint-initdb.d）**不跑迁移链** ⇒ 只写迁移 = 新建库仍留着
    活跃系数档（形状同 #3270：迁移链不在该栈运行）。本判据钉住该同步。
    """
    assert factor_retire_statements(), "迁移侧没有软删语句（本判据的前提不成立）"
    code = sql_code(schema_sql)
    assert re.search(r"UPDATE\s+production_route_rules[\s\S]{0,200}?\bdeleted\s*=\s*1", code, re.I), (
        "docs/sql/schema.sql 没有同步「软删 action='factor' 活跃行」—— "
        "bootstrap 路径不跑迁移链 ⇒ 新建库会留着活跃系数档")
    assert re.search(r"action\s*=\s*'factor'", code, re.I), (
        "schema.sql 的软删语句没有限定 action='factor'")


def test_factor_retire_guard_detects_injected_regression(tmp_path):
    """注入式自证（三段，各挡一种「守卫自己失效」的形态）。

    ① 形态判据**会红**：把 `action='factor'` 换成 `action='insert'` / 改成 `DELETE FROM`
       ⇒ `factor_retire_shape_errors` 必须点名（否则它是空断言）；
    ② 发现逻辑**按内容**：合法的软删语句放进临时目录也能被读到（不是写死文件名）；
    ③ `sql_code` **真的剥注释**：只写在注释里的 `DROP COLUMN factor` 不得命中。
    """
    bad_scope = "SET deleted = 1, updated_at = NOW() WHERE action = 'insert' AND deleted = 0"
    errs = factor_retire_shape_errors("V99__bad.sql", bad_scope)
    assert any("action = 'factor'" in e for e in errs), "漏 action 限定的形态没被照出来"

    physical = "DELETE FROM production_route_rules WHERE action = 'factor' AND deleted = 0"
    errs = factor_retire_shape_errors("V99__bad.sql", physical)
    assert any("物理删" in e for e in errs), "物理删的形态没被照出来"

    (tmp_path / "V99__good.sql").write_text(
        "UPDATE production_route_rules\n   SET deleted = 1, updated_at = NOW()\n"
        " WHERE action = 'factor' AND deleted = 0;\n", encoding="utf-8")
    found = factor_retire_statements(tmp_path)
    assert len(found) == 1, "合法的软删语句没被按内容发现（发现逻辑写死了文件名？）"
    assert factor_retire_shape_errors(found[0][0].name, found[0][1]) == []

    commented = "-- ALTER TABLE production_route_rules DROP COLUMN IF EXISTS factor;\nSELECT 1;\n"
    assert "DROP COLUMN" not in sql_code(commented), "sql_code 没有剥掉行注释 ⇒ 回滚注释会被读成真删列"
