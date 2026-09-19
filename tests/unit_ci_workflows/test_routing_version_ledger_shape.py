# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：脚本/CI/表结构类 L0 不变式统一挂 MC-012 ——
#   `.github/cases/misc.yml` 的 MC-012 已登记「CI/工具链结构由 tests/unit_ci_workflows/ 单测验证，
#   skip_reason = [backend-contract]，不进 agent-eval 冒烟」。本文件同属该形态：零真实 DB。）
"""L0 静态判据：路线变更账 `production_routing_versions` 必须是**新模型**形状（issue #4581，P0）。

## 病灶（2026-09-19 商家面实测：新建 / 改工艺路线恒 500）

`ProductionRoutingCommandService.appendVersion()` 无条件写版本账，而该表仍是 V60 的**旧模型**形状
⇒ 每行 INSERT 都被 Postgres 拒 ⇒ `@Transactional` 回滚 ⇒ **连路线模板一起回滚**：

    ① `curtain_type` / `craft` 是 NOT NULL 且无默认值，写面只能传 null ⇒ not-null violation
       （MyBatis-Plus 的 NOT_NULL 策略只是把 null 字段从 INSERT 里**省掉**，省掉照样违约）；
    ② `routing_id` 上的外键指向 **`production_routings`（旧表，P2b / #4495 起已退役）**，
       而写面传的是 `production_route_templates.id` ⇒ FK violation。

改名 / 设默认 / 删除**不写版本账** ⇒ 那三条路径正常（这解释了「只有新建和改主线炸」）。

## 为什么必须有一条 L0 判据（mock 单测看不见 DB 约束）

admin-api 的 pom **没有** testcontainers / H2 ⇒ `ProductionRoutingCommandServiceTest` 的
`verify(insert)` 只能证明「调了 insert」，**证明不了「DB 会接受这一行」**—— 这正是本单的
「空跑绿」形态（断言的是**调用**，不是**效果**）。⇒ 表形状改由本文件静态守（零真实 DB、秒级）。

## 判据（①~⑤ 每条都要有红证：在修复前必须红）

  ① `production_routing_versions.routing_id` **不得**再挂指向 `production_routings` 的外键；
  ② 必须有指向 `production_route_templates` 的外键（旧表退役后新表才是真值源）；
  ③ `curtain_type` / `craft` 必须**可空**（列保留 = 历史行仍答得出「当时是哪条 部位×工艺」）；
  ④ **两处口径一致**：`docs/sql/schema.sql`（bootstrap 路径，**不跑迁移链**）与
     迁移 `V85__fix_routing_version_ledger_shape.sql`（存量库路径）叠加结果不得分叉
     —— 只修一处 = 另一条路径上照样 500（形态见 #3270）；
  ⑤ **写面静态判据**：`appendVersion` 段内不得再出现 `.curtainType(` / `.craft(`，且必须有 `.routingId(`。

## 红证（修复前实测，本文件写下时逐条验过）

未修状态下 ①（FK 指向旧表）/ ②（无新表 FK）/ ③（两列 NOT NULL）/ ④（迁移文件不存在）/ ⑤（写面传 null）
**全红**；落地 V85 + schema.sql + 写面三处改动后转绿。
⚠️ 表名 / 列名一律**现场解析**（不写死行号）：schema 或迁移里的位置一变，本判据照旧有效。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "docs" / "sql" / "schema.sql"
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
MIGRATION = MIGRATION_DIR / "V85__fix_routing_version_ledger_shape.sql"
SERVICE = (REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
           / "ProductionRoutingCommandService.java")

TABLE = "production_routing_versions"
OLD_ROUTING_TABLE = "production_routings"          # 旧模型真值源（P2b / #4495 起退役）
NEW_ROUTING_TABLE = "production_route_templates"   # 新模型真值源（写面落点）
LEGACY_COLUMNS = ("curtain_type", "craft")         # 旧模型路线键两维；新模型没有这一维


def _table_body(sql: str, table: str) -> str:
    """取 `CREATE TABLE <table> ( ... )` 的括号体（现场解析，不写死行号）。"""
    m = re.search(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+" + re.escape(table) + r"\s*\(([\s\S]*?)\n\);",
                  sql, re.I)
    assert m, f"{table} 的 CREATE TABLE 块没找到（表被改名/删除？）"
    return m.group(1)


def _column_def(body: str, column: str) -> str:
    """取括号体里某一列的**行内定义**（列名开头的整行；取不到即 fail-closed）。"""
    for line in body.split("\n"):
        line = line.strip()
        if re.match(r"^" + re.escape(column) + r"\s", line, re.I):
            return line
    raise AssertionError(f"列 {column} 不在表定义里")


def _foreign_keys(body: str) -> dict:
    """括号体里声明的外键：列 → 被引用表（两种形态都收：内联 `x REFERENCES t(id)` 与
    `FOREIGN KEY (x) REFERENCES t(id)`）。"""
    found: dict = {}

    def record(cols: str, ref: str):
        for col in cols.split(","):
            col = col.strip().strip('"')
            if col:
                found[col] = ref

    for m in re.finditer(r"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+([A-Za-z_][A-Za-z0-9_]*)",
                         body, re.I):
        record(m.group(1), m.group(2).lower())
    for m in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s+[^,\n]*?REFERENCES\s+([A-Za-z_][A-Za-z0-9_]*)",
                         body, re.I | re.M):
        record(m.group(1), m.group(2).lower())
    return found


def _schema_body() -> str:
    return _table_body(SCHEMA.read_text(encoding="utf-8"), TABLE)


def _migration_sql() -> str:
    assert MIGRATION.exists(), (
        f"{MIGRATION.name} 不存在 —— 表形状没修（改 V60 对存量库无效：MigrationRunner 的 "
        f"schema_migrations 按**文件名**记账，已应用的文件整份跳过；见 issue #4235）")
    return MIGRATION.read_text(encoding="utf-8")


def _service_append_version_body() -> str:
    """`appendVersion` 方法体（从签名到配平的花括号）—— 现场解析，不写死行号。"""
    src = SERVICE.read_text(encoding="utf-8")
    m = re.search(r"private\s+void\s+appendVersion\s*\([^)]*\)\s*\{", src)
    assert m, "appendVersion 方法没找到（写面被重构？请同步更新本判据）"
    i, depth = m.end(), 1
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    assert depth == 0, "appendVersion 的花括号没配平"
    return src[m.end():i - 1]


# ══════════════════════════ ① 不得再有指向旧表的外键 ══════════════════════════

def test_routing_id_has_no_fk_to_retired_routing_table():
    """schema.sql：`routing_id` 不得引用已退役的 `production_routings`。

    红证（修复前）：该行是 `routing_id VARCHAR(64) NOT NULL REFERENCES production_routings(id)`。
    """
    fks = _foreign_keys(_schema_body())
    assert fks.get("routing_id") != OLD_ROUTING_TABLE, (
        "routing_id 的外键仍指向已退役的 production_routings —— 写面传的是 "
        f"{NEW_ROUTING_TABLE}.id ⇒ 每行版本账都被 FK 拒（issue #4581 的违约 ②）")


def test_migration_drops_fk_pointing_to_retired_routing_table():
    """迁移里必须**按被引用表**现场摘掉旧外键（不写死约束名：bootstrap 与迁移路径名字可能不同）。"""
    sql = _migration_sql()
    assert "pg_constraint" in sql, "迁移必须遍历 pg_constraint 找外键，而不是写死约束名"
    assert OLD_ROUTING_TABLE in sql and "DROP CONSTRAINT" in sql, (
        f"迁移里没有「摘掉指向 {OLD_ROUTING_TABLE} 的外键」的语句")
    assert "conrelid = " in sql and "confrelid = " in sql, (
        "迁移必须按 (conrelid = 本表, confrelid = 旧表) 定位约束（写死名字会在别的 bootstrap 路径上漏掉）")


# ══════════════════════════ ② 必须挂到新表 ══════════════════════════

def test_routing_id_fk_points_to_route_templates_in_schema():
    """schema.sql：`routing_id` 必须引用 `production_route_templates`（新模型真值源）。"""
    fks = _foreign_keys(_schema_body())
    assert fks.get("routing_id") == NEW_ROUTING_TABLE, (
        f"routing_id 的外键必须指向 {NEW_ROUTING_TABLE}，实际 = {fks.get('routing_id')!r}")


def test_migration_adds_fk_to_route_templates_not_valid():
    """迁移必须把外键挂到新表，且带 `NOT VALID`。

    为什么 `NOT VALID` 是必须的（不是可选优化）：存量行可能引用旧表 id ⇒ 全量校验会让**存量库**
    的迁移失败；`NOT VALID` 只跳过存量行的校验，**新写入照旧强制**。
    """
    sql = _migration_sql()
    add = re.search(r"ADD\s+CONSTRAINT\s+\S+\s+FOREIGN\s+KEY\s*\(\s*routing_id\s*\)\s*"
                    r"REFERENCES\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.I)
    assert add, "迁移里没有 `ADD CONSTRAINT ... FOREIGN KEY (routing_id) REFERENCES ...`"
    assert add.group(1).lower() == NEW_ROUTING_TABLE, (
        f"新外键必须指向 {NEW_ROUTING_TABLE}，实际 = {add.group(1)}")
    assert re.search(r"REFERENCES\s+" + re.escape(NEW_ROUTING_TABLE) + r"\s*\([^)]*\)\s+NOT\s+VALID",
                     sql, re.I), "新外键必须带 NOT VALID（否则存量行会让迁移在存量库上失败）"


# ══════════════════════════ ③ 旧模型两列必须可空 ══════════════════════════

def test_legacy_columns_are_nullable_in_schema():
    """schema.sql：`curtain_type` / `craft` 必须可空（列保留 = 历史行仍答得出「当时是哪条」）。"""
    body = _schema_body()
    for col in LEGACY_COLUMNS:
        assert not re.search(r"\bNOT\s+NULL\b", _column_def(body, col), re.I), (
            f"{col} 仍是 NOT NULL —— 新模型没有「部位 × 工艺」这一维 ⇒ 写面只能传 null "
            f"⇒ not-null violation（issue #4581 的违约 ①）")


def test_migration_drops_not_null_on_legacy_columns():
    """迁移必须对两列 `ALTER COLUMN ... DROP NOT NULL`（存量库路径）。"""
    sql = _migration_sql()
    for col in LEGACY_COLUMNS:
        assert re.search(r"ALTER\s+TABLE\s+" + re.escape(TABLE) + r"\s+ALTER\s+COLUMN\s+"
                         + re.escape(col) + r"\s+DROP\s+NOT\s+NULL", sql, re.I), (
            f"迁移缺少 `ALTER TABLE {TABLE} ALTER COLUMN {col} DROP NOT NULL`")


# ══════════════════════════ ④ 两处口径一致 ══════════════════════════

def test_bootstrap_schema_and_migration_agree():
    """`docs/sql/schema.sql`（bootstrap，**不跑迁移链**）与 V85（存量库）必须同口径。

    只修一处 = 另一条路径上照样 500 —— bootstrap-first 栈正是用 schema.sql 建库的（形态见 #3270）。
    """
    schema_body = _schema_body()
    sql = _migration_sql()

    schema_fk = _foreign_keys(schema_body).get("routing_id")
    migration_fk = re.search(r"REFERENCES\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*id\s*\)\s+NOT\s+VALID",
                             sql, re.I)
    assert schema_fk == NEW_ROUTING_TABLE and migration_fk is not None, (
        "两处至少一处没修："
        f"schema.sql 的 routing_id 外键 = {schema_fk!r}；迁移里的新外键 = {migration_fk}")
    assert migration_fk.group(1).lower() == schema_fk, (
        f"两处口径分叉：schema.sql → {schema_fk}，迁移 → {migration_fk.group(1)}")

    for col in LEGACY_COLUMNS:
        schema_nullable = not re.search(r"\bNOT\s+NULL\b", _column_def(schema_body, col), re.I)
        migration_nullable = bool(re.search(r"ALTER\s+COLUMN\s+" + re.escape(col)
                                            + r"\s+DROP\s+NOT\s+NULL", sql, re.I))
        assert schema_nullable and migration_nullable, (
            f"{col} 两处口径分叉：schema.sql 可空 = {schema_nullable}，迁移 DROP NOT NULL = {migration_nullable}")

    # 列本身必须**保留**（承载历史行）——「删列」不是本单的修法
    for col in LEGACY_COLUMNS:
        assert _column_def(schema_body, col), f"{col} 列不得删除（历史行仍要能回答「当时是哪条」）"


# ══════════════════════════ ⑤ 写面静态判据 ══════════════════════════

def test_write_face_does_not_pass_legacy_columns():
    """`appendVersion` 不得再传旧模型两列，且必须钉住新模型的路由 id。

    为什么是**结构性**判据而不是「传了 null 也算」：传 null 与不传在 MyBatis-Plus 的 NOT_NULL 策略下
    **等价**，但只有「不传」才读得出「新模型不写这两列」的意图 —— 留着 `.curtainType(null)` 会让下一个人
    以为这两列还是路线键（本单的病灶正是「按旧形状读这张表」）。
    """
    body = _service_append_version_body()
    for call in (".curtainType(", ".craft("):
        assert call not in body, (
            f"appendVersion 仍在传 {call}…）—— 新模型不写这两列（列只为历史行保留）")
    assert ".routingId(" in body, "appendVersion 必须钉住 routingId（= production_route_templates.id）"
    assert ".operations(" in body and ".operationCount(" in body, (
        "appendVersion 必须写 operations 与 operationCount（版本账的核心载荷）")
