# case_ids: PG-020
"""数据迁移引用的**表/列必须真实存在于 `backend/admin-api/src/main/resources/db/init/schema.sql`**（issue #4402）。

## 为什么需要这条（一次真实事故）

V74（#4399 特殊选项旧名回填）首版把载体①误写成 **`orders.processing_info`** ——
而 **`orders` 表根本没有 `processing_info` 列**（`order_items` 才有）。

后果链（**每一环都不报错**）：

1. 该条 SQL 失败；
2. `MigrationRunner` 对**非连接类**失败是「**跳过这一条、继续跑后面的**」
   （`MigrationRunner:185`，issue #3270 的刻意权衡：一条坏迁移不该冻结整个 schema）；
3. ⇒ **部署显示 `success`、服务照常 UP、探活 200**；
4. ⇒ **回填从未发生**，而云测试环境实测（781 张订单）：旧名仍 **3** 处、新名仍 **0** 处。

⇒ 「迁移写错了」在本仓**不会让任何门禁变红**。这条守卫补上那个洞：
**静态校验迁移里出现的 `表.列` / `UPDATE 表` / `ALTER TABLE 表` 引用在 schema 里真实存在**。

## 判据

对每条迁移：抽出它引用的表名（`UPDATE x` / `INSERT INTO x` / `ALTER TABLE x` / `DELETE FROM x`），
以及 `x.列` 形式的列引用 ⇒ 断言二者都在 `backend/admin-api/src/main/resources/db/init/schema.sql` 里存在。

**红证**：把任一条迁移的 `UPDATE order_items` 改成 `UPDATE orders`（无该列的表）⇒ 本判据红。

⚠️ 边界（如实登记）：本守卫只做**静态存在性**校验，**不能**替代真库执行
（类型不匹配、约束冲突、JSONB 形状错等仍要真库才暴露）。

## 判据 5（issue #4543）：迁移**必须至少含一条可执行语句**

判据 1~4 全都**遍历「已出现的引用」** ⇒ **引用集为空 ⇒ 循环体不执行 ⇒ 恒真（vacuous）**
⇒ 「一份**只有注释**的迁移」完全合法地通过（实证：PR #4532 的 V78 被脚本截掉两段 SQL 后**判绿**，
靠 sha 校验 + 人工 diff 才发现）。判据 5 补上那个洞，且**只判「有没有语句」、不判语义**。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration-archive"

# ── 迁移文件的**两个**载体目录（issue #5243）—— 单一事实源 = `_migration_paths.py`
# 共享件（issue #5243）：`tests/` 上 sys.path 才能按**包名**导入；直接以脚本运行时
#（如 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`）
# 包不在路径上，故显式补一次 —— 两种入口都要能跑。
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from unit_ci_workflows._migration_paths import LIVE_DIR as _LIVE_MIGRATION_DIR, migration_files as _migration_files



SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"

# 这些是**故意**指向历史/临时对象的引用，不在终态 schema 里（逐条给理由）
ALLOWLIST_TABLES = {
    # 迁移会改「历史上存在、后来被 DROP / 改名」的表 ⇒ 终态 schema 里没有，属正常
    "schema_migrations",           # 迁移台账本身（由 MigrationRunner 建，不在 schema.sql）
    "product_processing_items",    # V33/V34/V41 用；V66（#4371）已把它彻底解耦/删除 ⇒ 终态无
    "knowledge_entries",           # V37/V42 用；V37 已改名 knowledge_cards ⇒ 终态无
    # ⚠️ **不是「豁免一条真缺陷」，而是判据的**已知假阳性形态**（issue #4937 实测）：
    # 合并后的 `V102__retire_applicability_flag.sql` 里
    # `CREATE TEMP TABLE _v102_survivors ON COMMIT DROP AS …` 是**会话级临时表**
    # —— 由**同一个迁移文件**建、用完随事务消失，**结构上不可能**出现在 bootstrap
    # `backend/admin-api/src/main/resources/db/init/schema.sql` 里（该文件不跑迁移链）。判据 `_referenced_tables` 读 `FROM <标识符>`，
    # 它天然分不清「临时表」与「终态表」。
    # ⇒ 登记在此的**理由与作用域都写清楚**：只允许这一个名字（**不做前缀通配**），
    # 且本条目**必须**被 `test_temp_table_allowlist_entry_is_load_bearing` 的反向断言证明在承重。
    # ⚠️ **判据数量与强度与改判前逐字相同**：改判只是把对象从 `V104` 的 `_v104_survivors`
    # 换到 `V102` 的 `_v102_survivors`（那两条迁移已合并为一条，`V104` 文件已删除）。
    "_v102_survivors",
}


def test_temp_table_allowlist_entry_is_load_bearing():
    """上一条 `_v102_survivors` 的**死亡条件**（豁免不许变成永久条目）。

    反向断言：合并后的 `V102` **真的**建了这张临时表、且**真的**在写语句与对账里引用它；
    一旦 `V102` 不再用临时表（改写成 CTE / 子查询）⇒ 该条目就是死条目 ⇒ 本条判红，
    要求把它从 `ALLOWLIST_TABLES` 删掉（本仓口径：豁免必须有死亡条件）。
    """
    v102 = MIGRATION_DIR / "V102__retire_applicability_flag.sql"
    assert v102.exists(), "V102 不见了 ⇒ 上面的 allowlist 条目已成死条目，删掉它"
    body = v102.read_text(encoding="utf-8")
    assert "CREATE TEMP TABLE _v102_survivors" in body, (
        "V102 不再建 `_v102_survivors` 临时表 ⇒ 请把 `ALLOWLIST_TABLES` 里的该条目删掉"
        "（豁免没有对象就是死条目）")
    assert body.count("_v102_survivors") >= 3, (
        "`_v102_survivors` 只被建、没有被引用 ⇒ 它是装饰（豁免对象不存在）")


def _schema_text() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def _tables_in_schema(schema: str) -> set:
    return {m.lower() for m in re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+([a-z_][a-z0-9_]*)", schema, re.I)}


def _columns_of(schema: str, table: str) -> set:
    """取某张表的列名（从它的 `CREATE TABLE` 块里；块内的 ALTER 另行叠加）。"""
    m = re.search(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+" + re.escape(table) + r"\s*\(([\s\S]*?)\n\);", schema, re.I)
    cols = set()
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip()
            cm = re.match(r"([a-z_][a-z0-9_]*)\s+", line, re.I)
            if cm and cm.group(1).lower() not in ("primary", "unique", "constraint", "foreign", "check", "index", "key"):
                cols.add(cm.group(1).lower())
    # 该表的 ALTER ... ADD COLUMN 也算
    for am in re.finditer(r"ALTER TABLE\s+" + re.escape(table) + r"\b([\s\S]*?);", schema, re.I):
        for cm in re.finditer(r"ADD COLUMN(?:\s+IF NOT EXISTS)?\s+([a-z_][a-z0-9_]*)", am.group(1), re.I):
            cols.add(cm.group(1).lower())
    return cols


def _strip_comments(sql: str) -> str:
    """剥掉 SQL 注释。

    ⚠️ **必须剥**：迁移的头注释里常**描述**被改/被删的列（如 V66 的注释写
    `products.has_processing`、`processing_items.applicable_product_categories` ——
    那两列正是**它要 DROP 的**）⇒ 不剥注释会把说明文字当成真实引用，产生**假红**。
    （本守卫首版就栽在这里 —— 假红比没有守卫更糟：会被人直接关掉。）
    """
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return re.sub(r"--[^\n]*", " ", sql)


# 合法的**非表**引用：系统目录、集合返回函数、SQL 关键字/别名
NON_TABLE = {
    "pg_constraint", "pg_class", "pg_attribute", "pg_indexes", "pg_tables",
    "information_schema", "pg_catalog", "dual",
    "select", "where", "set", "values", "if", "case", "agg", "unnest",
    "generate_series", "jsonb_array_elements", "jsonb_array_elements_text",
    "jsonb_object_keys", "regexp_split_to_table",
}


def _referenced_tables(sql: str) -> set:
    sql = _strip_comments(sql)
    # ⚠️ `IS [NOT] DISTINCT FROM` 是**比较运算符**，不是 `FROM` 子句（issue #4676 实测：
    # `applicable IS DISTINCT FROM TRUE` 被下面的 `FROM` 正则读成「表 `true`」⇒ 对**合规迁移**
    # 判红 = 假红，而假红比没有守卫更糟 —— 会被人直接关掉）。先把它整体抹平再扫描。
    sql = re.sub(r"\bIS\s+(?:NOT\s+)?DISTINCT\s+FROM\b", " ", sql, flags=re.I)
    pats = [
        r"\bUPDATE\s+([a-z_][a-z0-9_]*)",
        r"\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)",
        r"\bALTER\s+TABLE\s+([a-z_][a-z0-9_]*)",
        r"\bDELETE\s+FROM\s+([a-z_][a-z0-9_]*)",
        r"\bFROM\s+([a-z_][a-z0-9_]*)\b(?!\s*\()",   # 后面紧跟 `(` ⇒ 是函数调用，不是表
    ]
    out = set()
    for p in pats:
        for m in re.finditer(p, sql, re.I):
            t = m.group(1).lower()
            if t not in NON_TABLE and not t.startswith("pg_") and not t.startswith("information_schema"):
                out.add(t)
    return out


def _referenced_columns(sql: str) -> set:
    """`表.列` 形式的引用（排除 `NEW.`/`OLD.`/`excluded.` 等伪记录；**先剥注释**）。"""
    sql = _strip_comments(sql)
    out = set()
    for m in re.finditer(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b", sql, re.I):
        t, c = m.group(1).lower(), m.group(2).lower()
        if t in ("new", "old", "excluded"):
            continue
        out.add((t, c))
    return out


def _update_set_columns(sql: str) -> set:
    """`UPDATE <表> SET <列> = …` 里被赋值的列（**非限定**写法）。

    ⚠️ **这条才是能抓住 V74 首版那个 bug 的检查**：迁移里写的是
    `UPDATE orders SET processing_info = …` —— 列名**不带表前缀** ⇒
    只查 `表.列` 限定引用会**漏掉**它（实测：把 V74 改回 `UPDATE orders` 时，
    只查限定引用的版本**仍然全绿** = 空守卫）。
    """
    sql = _strip_comments(sql)
    out = set()
    for m in re.finditer(r"\bUPDATE\s+([a-z_][a-z0-9_]*)\s+SET\s+([\s\S]*?)(?:\bWHERE\b|;)", sql, re.I):
        table, assignments = m.group(1).lower(), m.group(2)
        # 只取赋值号左侧的列名（跳过 `jsonb_set(x, '{k}', …)` 这类函数调用内部的参数）
        for a in re.split(r",(?![^()]*\))", assignments):
            cm = re.match(r"\s*([a-z_][a-z0-9_]*)\s*=", a, re.I)
            if cm:
                out.add((table, cm.group(1).lower()))
    return out


def test_schema_is_parseable():
    """自证：schema 解析出了足够多的表（否则本文件空转 = 假绿）。"""
    tables = _tables_in_schema(_schema_text())
    assert len(tables) > 50, f"schema 里只解析出 {len(tables)} 张表 —— 解析疑似失效"


def test_migration_referenced_tables_exist():
    """判据 1：迁移里 `UPDATE/INSERT INTO/ALTER TABLE/DELETE FROM/FROM` 的表必须在 schema 里存在。"""
    schema = _schema_text()
    tables = _tables_in_schema(schema)
    missing = []
    for p in sorted(_migration_files("V*.sql")):
        for t in _referenced_tables(p.read_text(encoding="utf-8")):
            if t in ALLOWLIST_TABLES or t in tables:
                continue
            missing.append(f"{p.name}: 表 `{t}` 在 schema.sql 里不存在")
    assert not missing, (
        "这些迁移引用了 schema 里**不存在**的表：\n  " + "\n  ".join(sorted(set(missing)))
        + "\n⇒ 该迁移会**失败**，而 `MigrationRunner` 对非连接类失败是「跳过并继续」"
          "（`MigrationRunner:185`）⇒ **部署 success、回填从未发生**（issue #4402 的实证形态）。\n"
          "修法：改成正确的表名，或（若确属历史对象）加进本文件的 ALLOWLIST_TABLES 并写理由。"
    )


def _columns_added_by(sql: str) -> set:
    """**本条迁移自己 `ADD COLUMN` 出来的列**（`(表, 列)`）。

    ⚠️ **为什么必须排除它们**（否则守卫会永久假红、被人直接关掉）：新增列的正确写法是
    「同一文件里 `ALTER TABLE t ADD COLUMN IF NOT EXISTS c` + `COMMENT ON COLUMN t.c`」
    —— 而 `COMMENT ON COLUMN t.c` 是**合法的自引用**（该列由本文件刚建出来），
    终态 `backend/admin-api/src/main/resources/db/init/schema.sql` 里当然还没有它。不排除就会把「按规范写注释」判成缺陷。
    （实证：V78 `craft_hint` 首版即命中此假红；而**真正的**缺陷形态 —— 引用**别人**的、
    或**根本不存在**的列 —— 仍会被抓住。）
    """
    sql = _strip_comments(sql)
    out = set()
    for m in re.finditer(r"\bALTER\s+TABLE\s+([a-z_][a-z0-9_]*)([\s\S]*?);", sql, re.I):
        table = m.group(1).lower()
        for cm in re.finditer(r"ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+([a-z_][a-z0-9_]*)", m.group(2), re.I):
            out.add((table, cm.group(1).lower()))
    return out


def test_migration_referenced_columns_exist():
    """判据 2：迁移里 `表.列` 的列必须在该表里存在（**这条正是 V74 首版漏掉的检查**）。

    ⚠️ 排除**本迁移自己 ADD COLUMN 出来的列**（见 {@link _columns_added_by}）——
    那是合法的自引用（典型形态 = `ADD COLUMN` + `COMMENT ON COLUMN` 同一文件）。
    """
    schema = _schema_text()
    tables = _tables_in_schema(schema)
    missing = []
    for p in sorted(_migration_files("V*.sql")):
        sql = p.read_text(encoding="utf-8")
        self_added = _columns_added_by(sql)
        for t, c in _referenced_columns(sql):
            if t in ALLOWLIST_TABLES or t not in tables:
                continue          # 表不存在由判据 1 负责报
            if (t, c) in self_added:
                continue          # 本迁移自己建的列（ADD COLUMN + COMMENT ON 同文件）
            if (t, c) in ALLOWLIST_DROPPED_COLUMNS:
                continue          # 本迁移自己 DROP 的列（先回填再删；见该集合的说明与死亡条件）
            if c not in _columns_of(schema, t):
                missing.append(f"{p.name}: `{t}.{c}` —— `{t}` 表没有列 `{c}`")
    assert not missing, (
        "这些迁移引用了**不存在的列**：\n  " + "\n  ".join(sorted(set(missing)))
        + "\n⇒ 与 V74 首版同款：SQL 失败 → 被跳过 → 部署 success 但数据没改（issue #4402）。"
    )


# ── 判据 2 的自证（**防「把守卫写弱成永远绿」**）───────────────────────────────
# 实证（issue #4452）：V78 `craft_hint` 首版把守卫判红 —— 命中的是 `COMMENT ON COLUMN
# processing_items.craft_hint`（**合法的自引用**：该列由同一文件刚 ADD COLUMN 出来，
# 终态 schema.sql 里当然还没有）。修法 = 排除「本迁移自己 ADD COLUMN 出来的列」。
# ⇒ 必须同时钉住两件事：① 自引用放行；② **真缺陷仍被抓住**（否则守卫就成了摆设）。

#: 判据 2 的第二类合法自引用：**本条迁移自己 DROP 掉的列**。
#:
#: 形态（V113 / 用户裁定 2026-09-21）：迁移要把 `product_skus.selling_method` 上移为
#: 商品级基础属性 ⇒ 必须**先回填**（从旧 SKU 列取真值）**再 DROP**。
#: 回填那一句读的就是本文件随后要删的列 ⇒ 终态 schema 里当然没有它 ⇒ 守卫判红。
#:
#: ⚠️ 这条**不是**「豁免一个真缺陷」：判据要防的是 V74 那种「引用**别人**的、根本不存在的列」
#: （SQL 失败 → 被跳过 → 部署 success 但回填从未发生）。「本文件自己 DROP 的列」与那种缺陷
#: **静态不可区分**（都表现为「schema 里没有该列」）⇒ 只能登记，且**必须有死亡条件**：
#: 一旦 V113 不再引用它（改写成 CTE / 不再回填）⇒ 该条目就是死条目 ⇒ 下面那条反向断言判红。
ALLOWLIST_DROPPED_COLUMNS = {
    ("product_skus", "selling_method"),
}


def test_dropped_column_allowlist_entry_is_load_bearing():
    """上一条豁免的**死亡条件**（豁免不许变成永久条目）。

    反向断言：V113 **真的**既引用 `product_skus.selling_method`（回填读它）
    又 DROP 它（同一文件）；一旦它不再这么做 ⇒ 该条目已死 ⇒ 本条判红，要求删掉豁免。
    """
    v113 = MIGRATION_DIR / "V113__product_roll_length_and_selling_method_base_attribute.sql"
    assert v113.exists(), "V113 不见了 ⇒ 上面的 allowlist 条目已成死条目，删掉它"
    body = v113.read_text(encoding="utf-8")
    assert ("product_skus", "selling_method") in _referenced_columns(body), (
        "V113 不再引用 `product_skus.selling_method` ⇒ 请把 ALLOWLIST_DROPPED_COLUMNS 里的该条目删掉")
    assert re.search(r"ALTER TABLE product_skus\s+DROP COLUMN IF EXISTS selling_method", body), (
        "V113 不再 DROP 该列 ⇒ 该条目已不是「自己 DROP 的列」这一形态 ⇒ 删掉豁免")


def test_self_added_columns_are_excluded():
    """① 自引用放行：`ADD COLUMN c` + `COMMENT ON COLUMN t.c` 同一文件 ⇒ 不算「引用了不存在的列」。"""
    sql = ("ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS craft_hint VARCHAR(16);\n"
           "COMMENT ON COLUMN processing_items.craft_hint IS '显式声明的工艺';\n")
    assert ("processing_items", "craft_hint") in _columns_added_by(sql)
    assert ("processing_items", "craft_hint") in _referenced_columns(sql)
    # 逐条走一遍判据 2 的过滤逻辑（不改磁盘文件，直接验过滤条件）
    schema = _schema_text()
    tables = _tables_in_schema(schema)
    self_added = _columns_added_by(sql)
    missing = [
        f"{t}.{c}" for t, c in _referenced_columns(sql)
        if t in tables and (t, c) not in self_added and c not in _columns_of(schema, t)
    ]
    assert missing == [], "自引用（ADD COLUMN + COMMENT ON 同文件）不得被判成缺陷"


def test_genuinely_missing_column_is_still_caught():
    """② **真缺陷仍被抓住**（守卫没被写弱）：`COMMENT ON COLUMN` 一个**没被本文件 ADD** 的列 ⇒ 命中。"""
    sql = "COMMENT ON COLUMN processing_items.craft_hint_not_added IS '凭空引用';\n"
    schema = _schema_text()
    tables = _tables_in_schema(schema)
    self_added = _columns_added_by(sql)
    missing = [
        f"{t}.{c}" for t, c in _referenced_columns(sql)
        if t in tables and (t, c) not in self_added and c not in _columns_of(schema, t)
    ]
    assert missing == ["processing_items.craft_hint_not_added"], (
        "引用了既不在终态 schema、也不是本文件 ADD 出来的列 ⇒ 必须判红"
        "（否则这条守卫就是摆设 —— V74 首版那个缺陷会静默通过）"
    )


def test_distinct_from_operator_is_not_read_as_a_table():
    """③ **比较运算符不得被读成 `FROM` 子句**（issue #4676 实测的假红形态）。

    `applicable IS DISTINCT FROM TRUE` 是**幂等守卫**的常用写法（「与目标值不同才写」），
    而 `_referenced_tables` 的 `FROM\\s+(\\w+)` 正则会把它读成「表 `true`」⇒ 对**合规迁移**判红。
    假红比没有守卫更糟（本文件自己的口径：会被人直接关掉）⇒ 先抹平 `IS [NOT] DISTINCT FROM` 再扫描。

    自证（红证形态）：去掉那条 `re.sub` ⇒ 本用例立刻变红（`true` 出现在结果里）。
    """
    assert _referenced_tables(
        "UPDATE production_operation_positions p SET applicable = TRUE "
        "WHERE p.applicable IS DISTINCT FROM TRUE;") == {"production_operation_positions"}, (
        "`IS DISTINCT FROM TRUE` 被读成了表 `true` ⇒ 合规迁移会被误判"
    )
    assert _referenced_tables("SELECT 1 FROM t WHERE a IS NOT DISTINCT FROM NULL") == {"t"}, \
        "`IS NOT DISTINCT FROM` 同样必须被抹平"


# ── 判据 5：迁移**必须至少含一条可执行语句**（issue #4543）─────────────────────
# 病根：判据 1~4 全都**遍历「已出现的引用」** ⇒ 引用集为空时循环体不执行 ⇒ **恒真（vacuous）**
# ⇒ 「一份只有注释的迁移」完全合法地通过。而它的后果是**真实故障**：
# `MigrationRunner` 把它记进 `schema_migrations`（按文件名）⇒ **该迁移永不生效**，
# 而 `backend/admin-api/src/main/resources/db/init/schema.sql` 是手写终态、看起来「列在」⇒ **bootstrap 库有列、存量库没有**
# ⇒ 存量环境查询 500（#3270 同族）。实证：PR #4532 用脚本改写 V78 文件尾注释时
# 截掉了 `ALTER TABLE … ADD COLUMN` 与 `COMMENT ON COLUMN` 两段 SQL，守卫**判绿**，
# 最后靠 `test_migration_immutability` 的 sha 校验 + 人工 diff 才发现
# （那个 sha 校验验的是「文件没被改」，**不是**「文件里有东西」）。

# 一条**可执行语句**的形态：`DDL/DML 关键字 + 操作对象`。
# ⚠️ 关键字**必须带对象**（`ALTER TABLE` / `SET <标识符> =` 这种），否则：
#   ① 裸 `SET`（`SET search_path = …`）会把**会话元数据设置**误判成数据改动；
#   ② 裸 `CREATE`/`ALTER` 会把注释残留或半截 SQL 误判成有效语句。
# ⇒ 本判据只判「**有没有语句**」，**不判语义**（语义是判据 1~4 的射程，见文件头边界）。
_DDL_DML = re.compile(
    r"\b(?:ALTER\s+(?:TABLE|INDEX|SEQUENCE|VIEW|SCHEMA)"
    r"|CREATE\s+(?:TABLE|INDEX|UNIQUE\s+INDEX|SEQUENCE|VIEW|SCHEMA|TYPE|EXTENSION)"
    r"|INSERT\s+INTO|UPDATE\s+[a-z_]|DELETE\s+FROM|DROP\s+(?:TABLE|INDEX|VIEW|COLUMN|CONSTRAINT|SEQUENCE)"
    r"|COMMENT\s+ON|GRANT\b|REVOKE\b"
    r"|SET\s+[a-z_][a-z0-9_]*\s*(?:=|TO\b))", re.I)

# 「**只有注释、零语句**」的**存量**迁移（逐条给理由；**只许缩短**，见下面的自证测试）。
# ⚠️ 为什么必须豁免而不是「顺手补上一条语句」：这三个文件**已被
# `test_migration_immutability` 的账本 `migration_fingerprints.json` 冻结**
# （`danger_scan` 机械阻塞改已发布迁移）⇒ 改/删它们都会让那条守卫红。
# 不豁免 ⇒ 本判据在**存量仓库**上永久红 ⇒ 只能被人关掉（假红比没有守卫更糟）。
#
# ✅ **来历已核实（不是「疑似缺陷」，是「有意留空」）**：这三个文件由
# `b11c172ad`（「极简 DB 迁移器替代 Flyway」）**以只有注释的形态新建**，用途 = 占住 Flyway
# 时代的迁移号（旧 Flyway 已把它们跑过）⇒ 对新 MigrationRunner 是**刻意的 no-op**
# （`git show b11c172ad -- <路径>` 的 diff 形态 = `new file` + 仅注释行；V2 更早的
# `e7dcf7096`/`e7dcf4735` 版本才含 27~29 行 `INSERT`，那属于**旧 Flyway 目录**，不是本目录）。
# ⇒ 它们**没有**「本应生效却空跑」的缺陷；本条豁免是**语义正确**的，不是「网开一面」。
# ⚠️ 但本判据对**任何新增**迁移都会拦住同一形态（新增的「只有注释」迁移 = 真缺陷，
# 因为新号在存量库**没有**已应用记录 ⇒ 它本该做的那件事永远不会发生）。
VACUOUS_PLACEHOLDER_MIGRATIONS = {
    "V2__init_rbac_data.sql":
        "b11c172ad 新建的**占号**文件，全文 2 行注释（`-- RBAC 种子数据（幂等: ON CONFLICT DO NOTHING）`"
        " + `-- 此文件仅作记录，实际数据由应用层初始化`）⇒ 有意 no-op（种子数据由应用层初始化）。",
    "V3__backfill_position_from_role.sql":
        "b11c172ad 新建的**占号**文件，全文 1 行注释（`-- 从角色表回填职位字段（历史数据迁移，已完成）`）"
        "⇒ 有意 no-op（回填在 Flyway 时代已完成）。",
    "V4__migrate_in_warehouse_to_on_sale.sql":
        "b11c172ad 新建的**占号**文件，全文 1 行注释（`-- 在仓 → 在售状态迁移（历史数据迁移，已完成）`）"
        "⇒ 有意 no-op（状态迁移在 Flyway 时代已完成）。",
}


def _statements_without_executable_sql(sql: str) -> bool:
    """该迁移文本是否**一条可执行语句都没有**（= 剥注释后没有任何 DDL/DML 关键字 + 对象）。"""
    return not _DDL_DML.search(_strip_comments(sql))


def test_migration_must_contain_at_least_one_statement():
    """判据 5（**承重**）：每个 `V*__*.sql` 迁移必须**至少含一条可执行语句**。

    判据 1~4 全部只校验「**已出现**的引用」⇒ 引用集为空 ⇒ 循环体不执行 ⇒ 恒真（vacuous）。
    本条补上那个洞：**只有注释的迁移**必须报出（issue #4543；实证 PR #4532 的 V78 事故）。

    ⚠️ 只判「有没有语句」，**不判语句语义**（那是判据 1~4 的射程）。
    """
    files = sorted(_migration_files("V*.sql"))
    assert files, f"{MIGRATION_DIR} 下一条迁移都没找到 —— 本判据空转（假绿）"
    vacuous = [
        p.name for p in files
        if p.name not in VACUOUS_PLACEHOLDER_MIGRATIONS
        and _statements_without_executable_sql(p.read_text(encoding="utf-8"))
    ]
    assert not vacuous, (
        "这些迁移**一条可执行语句都没有**（只有注释）：\n  " + "\n  ".join(vacuous)
        + "\n⇒ `MigrationRunner` 会把它记进 `schema_migrations`（按文件名）⇒ **该迁移永不生效**，"
          "而 `backend/admin-api/src/main/resources/db/init/schema.sql`（手写终态）看起来「列在」⇒ **bootstrap 库有列、存量库没有**"
          "⇒ 存量环境查询 500（issue #4543；实证 PR #4532 的 V78：脚本改写注释时截掉了两段 SQL，"
          "守卫判绿，靠 sha 校验 + 人工 diff 才发现）。\n"
          "修法：把被截掉的 SQL 补回去（**新增**迁移走新文件；已发布迁移不可改）。"
    )


def test_comment_only_migration_is_reported():
    """**红证（注入式）**：测试内构造一份**只有注释**的迁移 ⇒ 判据**必报出**。

    ⚠️ 形态要求（issue #4543）：这里**不得**写成「仓库当下恰有该缺陷」的真值主张 ——
    那种断言**修好即红**、报错指向错误方向（本仓 `migao-acceptance`「断言形态」节明令）。
    """
    injected = (
        "-- V999__only_comments.sql\n"
        "-- 本迁移把 processing_items.craft_hint 改成显式声明口径。\n"
        "-- 脚本改写文件尾注释时，下面两段 SQL 被截掉了：\n"
        "-- ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS craft_hint VARCHAR(16);\n"
        "-- COMMENT ON COLUMN processing_items.craft_hint IS '显式声明的工艺';\n"
    )
    assert _statements_without_executable_sql(injected), (
        "只有注释的迁移**必须**被判据 5 报出（否则本守卫是摆设 —— PR #4532 的 V78 事故原样复发）"
    )
    # 与判据 1~4 对照：同一条文本在「引用」口径下**一条引用都抽不出来** ⇒ 那四条恒真放行
    assert _referenced_tables(injected) == set() and _referenced_columns(injected) == set(), (
        "注入样例必须复现「引用集为空」这一前提（否则证明不了判据 1~4 的空断言形态）"
    )


def test_normal_migration_is_not_reported():
    """**红证的对照面**：正常迁移（含真语句）⇒ 判据**不报**（防「一律报红」的假守卫）。"""
    normal = (
        "-- V999__add_craft_hint.sql\n"
        "ALTER TABLE processing_items ADD COLUMN IF NOT EXISTS craft_hint VARCHAR(16);\n"
        "COMMENT ON COLUMN processing_items.craft_hint IS '显式声明的工艺';\n"
    )
    assert not _statements_without_executable_sql(normal)
    # 边界（如实登记）：`SET <标识符> = …` 形态**算**一条语句（issue #4543 建议口径里含 `SET`）。
    # 本判据只判「有没有语句」，**不判**「这条语句有没有实际效果」—— 后者是语义问题
    # （例如整份迁移只写 `SET search_path`），不在本判据射程内。
    assert not _statements_without_executable_sql("SET search_path = public;\n")
    # 而**只有注释**的文本仍然报出（与上面两条对照，证明判据有区分力）
    assert _statements_without_executable_sql("-- SET search_path = public;\n")


def test_vacuous_placeholder_exemptions_are_still_vacuous():
    """**防豁免腐烂**：豁免清单**只许缩短** —— 清单里的文件若已含真语句 ⇒ 红，逼人删掉该条。

    没有这条，豁免会永久留在文件里（将来有人给 V3 补上语句、或清单被复制粘贴扩大）。
    """
    actual = {
        p.name for p in sorted(_migration_files("V*.sql"))
        if _statements_without_executable_sql(p.read_text(encoding="utf-8"))
    }
    assert actual == set(VACUOUS_PLACEHOLDER_MIGRATIONS), (
        f"豁免清单与磁盘实际不符：\n  磁盘上零语句的迁移 = {sorted(actual)}\n"
        f"  清单 = {sorted(VACUOUS_PLACEHOLDER_MIGRATIONS)}\n"
        "⇒ 清单里多出来的条目已被修好/消失 ⇒ **删掉它**（只许缩短）；"
        "磁盘上多出来的 ⇒ 是**新**缺陷 ⇒ 修迁移，不要加豁免。"
    )


# 「已知损坏、但**不可修**」的已发布迁移（逐条给理由 + 补偿迁移）。
# ⚠️ 不是「网开一面」：`.github/danger_scan.py` **机械阻塞**改已发布迁移，且确认通道只对
# workflow 删除开放 ⇒ 这类文件只能靠**新增补偿迁移**修，静态守卫对它们**必须**放行，
# 否则守卫会永久红（= 被人直接关掉）。
KNOWN_BROKEN_PUBLISHED = {
    "V72__switch_routing_model_consumers.sql": (
        "第 349 行 `COALESCE(f.sort_order, 100)`，而 `production_option_factors` **没有 sort_order 列** "
        "⇒ SQL 失败 ⇒ **整份回滚**（jdbc.execute 是一个隐式事务）⇒ V72 的全部改动都没落地："
        "`factor` 列、`production_crafts` 表、按租户回填 —— 线上表现为 "
        "`GET /production/route-rules` 500 与 `POST /orders/{id}/instantiate` 500（issue #4514）。"
        "**补偿迁移 = V76**（= V72 逐字 + 该行修正）；V72 保持原样（不可变），代价是每次启动一条 ERROR。"
    ),
    "V74__backfill_legacy_special_option_names.sql": (
        "载体①写成 `UPDATE orders SET processing_info = …`，而 `orders` 无该列 ⇒ SQL 失败、"
        "被 MigrationRunner 跳过、部署仍 success（issue #4501 实证）。"
        "**补偿迁移 = V75**（正确的 `order_items`）；V74 保持原样（不可变），代价是每次启动一条 ERROR。"
    ),
}


def test_update_set_columns_exist_on_their_table():
    """判据 3（**承重**）：`UPDATE 表 SET 列` 的列必须属于该表。

    这正是 V74 首版的形态：`UPDATE orders SET processing_info = …` 而 `orders` 没有该列
    ⇒ SQL 失败 → `MigrationRunner` 跳过 → **部署 success 但回填从未发生**（issue #4402）。
    """
    schema = _schema_text()
    tables = _tables_in_schema(schema)
    missing = []
    for p in sorted(_migration_files("V*.sql")):
        for t, c in _update_set_columns(p.read_text(encoding="utf-8")):
            if t in ALLOWLIST_TABLES or t not in tables:
                continue
            if p.name in KNOWN_BROKEN_PUBLISHED:
                continue          # 已知损坏且不可修（见常量里的理由与补偿迁移）
            if c not in _columns_of(schema, t):
                missing.append(f"{p.name}: `UPDATE {t} SET {c} = …` —— `{t}` 表没有列 `{c}`")
    assert not missing, (
        "这些迁移 `UPDATE 表 SET 列` 的列**不属于该表**：\n  " + "\n  ".join(sorted(set(missing)))
        + "\n⇒ SQL 会失败，而 `MigrationRunner` 对非连接类失败是「跳过并继续」（`MigrationRunner:185`）"
          "⇒ **部署 success、服务 UP、探活 200，但数据一个字没改**（issue #4402 实证）。"
    )

def _aliases(sql: str) -> dict:
    """表别名 → 真表名（`FROM t a` / `JOIN t AS a`）。

    ⚠️ **这正是让 V72 溜过去的那一层**：它写的是 `COALESCE(f.sort_order, 100)`，
    而 `f` 是 `production_option_factors` 的**别名** ⇒ 只查「真表名.列」的版本**看不到**这一条。
    （issue #4514 实测：本守卫首版**全绿**，而 V72 在真库上直接报 `字段 f.sort_order 不存在`。）
    """
    sql = _strip_comments(sql)
    out = {}
    for m in re.finditer(
        r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)\s+(?:AS\s+)?([a-z_][a-z0-9_]*)\b",
        sql, re.I):
        table, alias = m.group(1).lower(), m.group(2).lower()
        if alias in ("on", "where", "set", "using", "inner", "left", "right", "full",
                     "cross", "join", "group", "order", "limit", "union", "select"):
            continue
        out[alias] = table
    return out


def _statements(sql: str) -> list:
    """按 `;` 粗切语句（够用：本仓迁移没有存储过程/函数体）。"""
    return [x for x in _strip_comments(sql).split(";") if x.strip()]


def test_alias_qualified_columns_exist():
    """判据 4（**承重**）：`别名.列` 的列必须存在于**该语句内**别名指向的那张表。

    ⚠️ 这条是 **issue #4514 的直接产物**：V72 的 `f.sort_order` 让整份迁移回滚，
    而当时本守卫（只覆盖「真表名.列」与「`UPDATE … SET` 的裸列」）**全绿放行**。
    ⇒ 不补这一条，同一个坑会来第三次。

    ⚠️ **别名必须按语句作用域解析**：同一文件里 `e` 可能在 A 语句指 `production_route_rules`、
    在 B 语句指 `production_operation_positions` ⇒ 整文件一张映射表会产出**假阳性**
    （本判据首版就栽在这里，实测报出 `e.logical_name` / `e.name` 两条假红）。
    假红比没有守卫更糟 —— 会被人直接关掉。
    """
    schema = _schema_text()
    tables = _tables_in_schema(schema)
    missing = []
    for p in sorted(_migration_files("V*.sql")):
        if p.name in KNOWN_BROKEN_PUBLISHED:
            continue          # 已知损坏且不可修（见常量里的理由与补偿迁移）
        for stmt in _statements(p.read_text(encoding="utf-8")):
            aliases = _aliases(stmt)          # ← 逐语句
            if not aliases:
                continue
            for alias, col in _referenced_columns(stmt):
                table = aliases.get(alias)
                if table is None or table in ALLOWLIST_TABLES or table not in tables:
                    continue      # 不是别名（可能是真表名，由判据 2 负责）
                if col not in _columns_of(schema, table):
                    missing.append(
                        f"{p.name}: `{alias}.{col}` —— 别名 `{alias}` = `{table}`，而该表没有列 `{col}`")
    assert not missing, (
        "这些迁移引用了**别名限定但不存在的列**：\n  " + "\n  ".join(sorted(set(missing)))
        + "\n⇒ 与 V72 同款（`f.sort_order`）：SQL 失败 → **整份迁移回滚**"
          "（`jdbc.execute(整个文件)` 是一个隐式事务）→ 部署 success 但**该迁移的全部改动都没落地**"
          "（issue #4514 实证）。"
    )
