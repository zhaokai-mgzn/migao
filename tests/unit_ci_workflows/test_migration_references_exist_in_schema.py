# case_ids: PG-020
"""数据迁移引用的**表/列必须真实存在于 `docs/sql/schema.sql`**（issue #4402）。

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
以及 `x.列` 形式的列引用 ⇒ 断言二者都在 `docs/sql/schema.sql` 里存在。

**红证**：把任一条迁移的 `UPDATE order_items` 改成 `UPDATE orders`（无该列的表）⇒ 本判据红。

⚠️ 边界（如实登记）：本守卫只做**静态存在性**校验，**不能**替代真库执行
（类型不匹配、约束冲突、JSONB 形状错等仍要真库才暴露）。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
SCHEMA = REPO / "docs/sql/schema.sql"

# 这些是**故意**指向历史/临时对象的引用，不在终态 schema 里（逐条给理由）
ALLOWLIST_TABLES = {
    # 迁移会改「历史上存在、后来被 DROP / 改名」的表 ⇒ 终态 schema 里没有，属正常
    "schema_migrations",           # 迁移台账本身（由 MigrationRunner 建，不在 schema.sql）
    "product_processing_items",    # V33/V34/V41 用；V66（#4371）已把它彻底解耦/删除 ⇒ 终态无
    "knowledge_entries",           # V37/V42 用；V37 已改名 knowledge_cards ⇒ 终态无
}


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
    for p in sorted(MIGRATION_DIR.glob("V*.sql")):
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


def test_migration_referenced_columns_exist():
    """判据 2：迁移里 `表.列` 的列必须在该表里存在（**这条正是 V74 首版漏掉的检查**）。"""
    schema = _schema_text()
    tables = _tables_in_schema(schema)
    missing = []
    for p in sorted(MIGRATION_DIR.glob("V*.sql")):
        for t, c in _referenced_columns(p.read_text(encoding="utf-8")):
            if t in ALLOWLIST_TABLES or t not in tables:
                continue          # 表不存在由判据 1 负责报
            if c not in _columns_of(schema, t):
                missing.append(f"{p.name}: `{t}.{c}` —— `{t}` 表没有列 `{c}`")
    assert not missing, (
        "这些迁移引用了**不存在的列**：\n  " + "\n  ".join(sorted(set(missing)))
        + "\n⇒ 与 V74 首版同款：SQL 失败 → 被跳过 → 部署 success 但数据没改（issue #4402）。"
    )

# 「已知损坏、但**不可修**」的已发布迁移（逐条给理由 + 补偿迁移）。
# ⚠️ 不是「网开一面」：`.github/danger_scan.py` **机械阻塞**改已发布迁移，且确认通道只对
# workflow 删除开放 ⇒ 这类文件只能靠**新增补偿迁移**修，静态守卫对它们**必须**放行，
# 否则守卫会永久红（= 被人直接关掉）。
KNOWN_BROKEN_PUBLISHED = {
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
    for p in sorted(MIGRATION_DIR.glob("V*.sql")):
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
