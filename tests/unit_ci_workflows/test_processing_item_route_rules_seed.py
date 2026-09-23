# case_ids: PG-023, PG-031
"""加工项触发工序的**种子三源收敛 + 真库可执行**（issue #4577 任务 C）。

## 病根（用户裁定 2026-09-19）

「**加工项也触发工序**」—— `trigger_kind='processing_item'` 早在 V71 的白名单里（CHECK 覆盖
`craft`/`option`/`shaped`/`processing_item`），但**零种子行** ⇒ 勾了「花边 / 扣环 / 接高」
也不加工序 = 「设计过但从未接线」。本单补 **3 条**规则行（按租户种）。

## 本文件钉的四件事（各有红证，互不掩盖）

1. **逐值**：V84 的 3 行 = `backend/admin-api/src/main/resources/db/init/schema.sql`（bootstrap 终态，该路径不跑迁移链）
   = `ProductionSeedTemplateService`（开租套用）—— 三源逐值一致；
2. **按租户 + 工序库护栏**：`FROM tenants` + `deleted = 0` + 目标工序归一后存在才种
   （否则规则永远插不进来 = 黑洞）；
3. **幂等双保险**：`NOT EXISTS`（业务键）+ `ON CONFLICT (id) DO NOTHING`；
   `JOIN (VALUES …) AS r(…)` **必须带 `ON TRUE`**（V83 真库实测 P0：缺 `ON` ⇒ 整份迁移回滚）；
4. **刻意不建行的两个值**：`拼接` / `双眼皮` 不得出现在种子行里（拼几次由特殊选项表达，
   理由登记在 issue #4577）。

**真库**：`test_v84_runs_on_real_postgres_and_is_idempotent_per_tenant` 用本机 PG 二进制
（`initdb`/`pg_ctl`/`psql`）起一个**临时集群**真跑迁移 —— 静态文本判据不够（V83 的教训：
文本守卫全绿而真库整份回滚）。缺 PG 的处置收口在 `pg_cluster.py`（CI 判**红** / 本机显式 skip，issue #5203）。
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = (REPO / "backend/admin-api/src/main/resources/db/migration-archive"
             / "V84__seed_processing_item_route_rules.sql")
SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
SEED_SERVICE = (REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
                / "ProductionSeedTemplateService.java")

#: 冻结期望：`(trigger_kind, trigger_value, action, operation, after_operation, priority)`。
EXPECTED = (
    ("processing_item", "花边", "insert", "花边", "三边", 270),
    ("processing_item", "扣环", "insert", "扣环", "三边", 280),
    ("processing_item", "接高", "insert", "接高", "精裁", 290),
)

_VALUES_BLOCK = re.compile(
    r"JOIN\s*\(VALUES(.*?)\)\s*AS\s*r\s*\(([^)]*)\)", re.S | re.I)


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释。

    ⚠️ **必须**先剥注释：本迁移的注释里**逐字**引用了 `JOIN (VALUES …) AS r(…)` / `ON TRUE` /
    `FROM tenants` 等判据片段 ⇒ 不剥的话正则命中**注释**、判据变成空断言（改代码也照样绿）。
    """
    return re.sub(r"--[^\n]*", "", sql)


def _rule_rows(sql: str) -> list:
    """解析 `JOIN (VALUES …) AS r(rid, trigger_kind, …, priority)` 段 → 逐行字段元组。

    列序**从 SQL 自己声明的 `AS r(...)` 读**（不写死），字段数不符即 fail-closed。
    """
    match = _VALUES_BLOCK.search(_strip_comments(sql))
    assert match, "没有 `JOIN (VALUES …) AS r(…)` 段 —— 按租户种子行读不到（判据会空跑）"
    columns = [c.strip() for c in match.group(2).split(",")]
    assert columns == ["rid", "trigger_kind", "trigger_value", "action", "operation",
                       "after_operation", "priority"], f"列序漂移：{columns}"
    rows = []
    for raw in re.findall(r"\(([^()]*)\)", match.group(1)):
        fields = [f.strip().strip("'") for f in raw.split(",")]
        assert len(fields) == len(columns), f"字段数 ≠ 列数：{raw}"
        rows.append(dict(zip(columns, fields)))
    return rows


def _expected_from(rows) -> list:
    return [(r["trigger_kind"], r["trigger_value"], r["action"], r["operation"],
             r["after_operation"], int(r["priority"])) for r in rows]


def test_v84_seeds_exactly_the_three_processing_item_rules():
    """判据 1：V84 逐值 = 冻结期望（3 条，`processing_item`，priority 270/280/290）。"""
    sql = MIGRATION.read_text(encoding="utf-8")
    assert _expected_from(_rule_rows(sql)) == list(EXPECTED)


def test_bootstrap_schema_sql_carries_the_same_three_rows():
    """判据 1（bootstrap 半边）：`backend/admin-api/src/main/resources/db/init/schema.sql` 逐值同款（该路径不跑迁移链）。"""
    sql = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
    # ⚠️ 选择器按 `rr-v84-` 收敛（issue #4714 起）：V93 的补种段也含 `processing_item` 三个触发值，
    # 而它的列集是 **8 列**（带 `position`，与 V72 同形）⇒ 用旧的 `"processing_item" in chunk`
    # 选择器会把 V93 段也捞进来，`_rule_rows` 的 7 列列序判据当场假红。
    # **判据本身一字不放宽**：仍是「V84 段逐值 = EXPECTED」，且列序漂移照旧 fail-closed。
    matches = [_expected_from(_rule_rows(chunk))
               for chunk in re.findall(r"INSERT INTO production_route_rules(.*?);", sql, re.S)
               if "rr-v84-" in chunk]
    assert matches, "schema.sql 里没有 `processing_item` 规则种子 —— bootstrap 路径拿不到这 3 条"
    assert matches[0] == list(EXPECTED)


def test_java_seed_service_seeds_the_same_three_rows():
    """判据 1（开租套用半边）：`ProductionSeedTemplateService.PROCESSING_ITEM_RULES` 逐值同款。"""
    source = SEED_SERVICE.read_text(encoding="utf-8")
    block = re.search(r"PROCESSING_ITEM_RULES\s*=\s*\{(.*?)\n    \};", source, re.S)
    assert block, "`PROCESSING_ITEM_RULES` 读不到 —— 开租不会种加工项规则（新租户行为分叉）"
    rows = re.findall(r'\{"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\}', block.group(1))
    assert rows == [(t, a, o, af) for _, t, a, o, af, _ in EXPECTED], (
        f"开租种子与 V84 不一致：{rows}")


def test_v84_is_per_tenant_guarded_and_idempotent():
    """判据 2/3：按租户 + 工序库护栏 + 幂等双保险 + `ON TRUE`（V83 真库实测 P0）。"""
    sql = _strip_comments(MIGRATION.read_text(encoding="utf-8"))
    assert re.search(r"FROM\s+tenants\s+t\b", sql, re.I), "没有按租户循环（`FROM tenants`）"
    assert re.search(r"WHERE\s+t\.deleted\s*=\s*0", sql, re.I), "没限定 `t.deleted = 0`"
    assert re.search(r"FROM\s+production_operations\s+o\b", sql, re.I), \
        "没有「目标工序在该租户工序库里存在才种」的护栏（V72 同款）"
    assert re.search(r"AS\s+r\s*\([^)]*\)\s*ON\s+TRUE", sql, re.I), \
        "`JOIN (VALUES …) AS r(…)` 缺 `ON TRUE` ⇒ 真库语法错误、整份迁移回滚（V83 实测）"
    assert re.search(r"ON\s+CONFLICT\s*\(id\)\s*DO\s+NOTHING", sql, re.I), "缺 `ON CONFLICT (id) DO NOTHING`"
    assert re.search(r"NOT\s+EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+production_route_rules\s+e\b", sql, re.I), \
        "缺业务键 `NOT EXISTS` 去重（双保险的另一半）"
    # 不新增 CHECK / 不改表结构（`trigger_kind='processing_item'` 已在 V71 白名单里）
    assert not re.search(r"ALTER\s+TABLE\s+production_route_rules", sql, re.I), \
        "本迁移不得改表结构（白名单已含 processing_item）"
    # 刻意不建行的两个值（防「顺手补齐」）
    values_block = _VALUES_BLOCK.search(sql).group(1)
    for forbidden in ("拼接", "双眼皮"):
        assert not re.search(r"'[^']*" + forbidden + r"[^']*'", values_block), \
            f"`{forbidden}` 不得建规则行（理由登记在 issue #4577）"


def test_guard_detects_injected_drift():
    """红证：把 3 行改值 / 去掉 `ON TRUE` / 塞进 `拼接` ⇒ 对应判据必红（不是空断言）。"""
    sql = MIGRATION.read_text(encoding="utf-8")
    bare = _strip_comments(sql)

    mutated = sql.replace("'花边', 'insert', '花边', '三边', 270",
                          "'花边', 'insert', '花边', '车被', 270")
    assert mutated != sql and _expected_from(_rule_rows(mutated)) != list(EXPECTED), \
        "改锚点判据读不出来 ⇒ 判据是空断言"

    no_on = _strip_comments(sql.replace("    ON TRUE\n", ""))
    assert not re.search(r"AS\s+r\s*\([^)]*\)\s*ON\s+TRUE", no_on, re.I), \
        "去掉 `ON TRUE` 判据读不出来 ⇒ 判据是空断言"

    with_forbidden = sql.replace("('01', 'processing_item', '花边',",
                                 "('01', 'processing_item', '拼接',")
    assert re.search(r"'[^']*拼接[^']*'",
                     _VALUES_BLOCK.search(_strip_comments(with_forbidden)).group(1)), \
        "`拼接` 判据读不出来 ⇒ 判据是空断言"

    # 注释剥离本身也是判据（否则「改代码但注释还在」会让判据恒绿）
    assert "ON TRUE" in bare, "剥注释后正文里必须仍有 `ON TRUE`"


# ══════════ 真库（临时 PG 集群；缺 PG ⇒ CI 判红 / 本机 skip，收口在 pg_cluster.py）══════════


#: 与 V71 同形的最小 DDL（只建本迁移触碰的三张表 + 那条部分唯一索引）。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL, name VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active', deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_route_rules (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(24) NOT NULL
        CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item')),
    trigger_value VARCHAR(64) NOT NULL, position VARCHAR(16),
    action VARCHAR(16) NOT NULL CHECK (action IN ('insert', 'remove')),
    operation VARCHAR(64) NOT NULL, after_operation VARCHAR(64),
    priority INTEGER NOT NULL DEFAULT 100, status VARCHAR(16) NOT NULL DEFAULT 'active',
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_route_rules_tenant_trigger_operation
    ON production_route_rules (tenant_id, trigger_kind, trigger_value,
                               COALESCE(position, ''), action, operation)
    WHERE deleted = 0;
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限，pytest 的 tmp_path 太长 ⇒
    # `pg_ctl start` 直接失败（实测）。故另起一个短前缀的临时目录。
    sockdir = Path(tempfile.mkdtemp(prefix="pg4577-"))
    log = tmp_path / "pg.log"
    subprocess.run([realdb_binaries["initdb"], "-D", str(datadir), "-U", "postgres", "-A", "trust"],
                   check=True, capture_output=True)
    port = _free_port()
    started = subprocess.run(
        [realdb_binaries["pg_ctl"], "-D", str(datadir), "-l", str(log), "-o",
         f"-k {sockdir} -p {port} -c listen_addresses=''", "start"],
        capture_output=True, text=True)
    assert started.returncode == 0, (
        f"临时集群起不来：{started.stdout}\n{started.stderr}\n"
        f"{log.read_text(encoding='utf-8') if log.exists() else ''}")

    def run(sql: str) -> str:
        proc = subprocess.run(
            [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
             "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    try:
        yield run
    finally:
        subprocess.run([realdb_binaries["pg_ctl"], "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


def test_v84_runs_on_real_postgres_and_is_idempotent_per_tenant(psql):
    """判据 2/3 真库：按租户逐值 + 工序库护栏 + 重跑空转 + 软删槽位不复活（PK 冲突收敛）。"""
    psql(_DDL)
    psql("""
        INSERT INTO tenants (id) VALUES (1), (2), (3);
        -- 1 号租户：三道目标工序齐全（`花边-布` / `扣环-布` / `接高-布` ⇒ 归一后 = 花边/扣环/接高）
        INSERT INTO production_operations (id, tenant_id, name) VALUES
          ('o1', 1, '花边-布'), ('o2', 1, '扣环-布'), ('o3', 1, '接高-布'),
        -- 2 号租户：工序库为空 ⇒ 一条也不许种（否则规则永远插不进来 = 黑洞）
        -- 3 号租户：只有「接高-布」⇒ 只许种 1 条
          ('o4', 3, '接高-布');
    """)
    migration_sql = MIGRATION.read_text(encoding="utf-8")

    psql(migration_sql)
    rows = psql("""
        SELECT tenant_id || '|' || trigger_kind || '|' || trigger_value || '|' || operation
               || '|' || after_operation || '|' || priority
          FROM production_route_rules WHERE deleted = 0 ORDER BY tenant_id, priority;
    """).split()
    assert rows == ["1|processing_item|花边|花边|三边|270",
                    "1|processing_item|扣环|扣环|三边|280",
                    "1|processing_item|接高|接高|精裁|290",
                    "3|processing_item|接高|接高|精裁|290"], f"真库逐值不符：{rows}"

    # 幂等：重跑空转（不新增、不报错）
    psql(migration_sql)
    assert psql("SELECT count(*) FROM production_route_rules WHERE deleted = 0;").strip() == "4"

    # 商家软删一条后重跑：`NOT EXISTS` 判「该插」而槽位 id 被占 ⇒ `ON CONFLICT (id)` 收敛成无操作
    psql("UPDATE production_route_rules SET deleted = 1 WHERE id = 'rr-v84-1-01';")
    psql(migration_sql)
    assert psql("SELECT count(*) FROM production_route_rules WHERE deleted = 0;").strip() == "3", \
        "软删过的槽位不得被种子复活（PK 冲突必须收敛成无操作，而不是整份迁移回滚）"

    # bootstrap 路径（`backend/admin-api/src/main/resources/db/init/schema.sql` **不跑迁移链**）：同一段 SQL 必须**真能执行**且逐值同款
    psql("INSERT INTO tenants (id) VALUES (4);"
         "INSERT INTO production_operations (id, tenant_id, name) VALUES"
         " ('o5', 4, '花边-布'), ('o6', 4, '扣环-布'), ('o7', 4, '接高-布');")
    bootstrap = [stmt for stmt in re.findall(
        r"INSERT INTO production_route_rules.*?;",
        _strip_comments(SCHEMA.read_text(encoding="utf-8")), re.S) if "processing_item" in stmt]
    assert bootstrap, "schema.sql 里取不到加工项规则种子段"
    psql(bootstrap[0])
    assert psql("SELECT count(*) FROM production_route_rules"
                " WHERE tenant_id = 4 AND deleted = 0;").strip() == "3", \
        "bootstrap 终态没种出 3 条（该路径不跑迁移链 ⇒ 它必须自带这 3 行）"
