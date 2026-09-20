# case_ids: PG-020, PG-018, MC-012
"""`V96` 补种迁移（issue #4741）+ 「**版本账条数 = 派生真值**」三处一致守卫。

⚠️ 本文件的用例声明行**必须**在文件前 50 行内（`.github/growth_gate.py` 的
`extract_case_ids()` 只扫前 50 行），故它放在本 docstring **之前**。

## 被测对象

`backend/admin-api/src/main/resources/db/migration/V96__backfill_operation_price_versions.sql`
= **1 条语句**：为**每条没有版本账的活跃工序**补 1 行初始版本行
（`'pv-v96-' || o.id` / `unit_price = o.unit_price` / 逐工序 `NOT EXISTS` 守卫）。

## 病根（真库实测 2026-09-21，PG 18.3 / 阿里云 RDS `ai_customer_service`）

`V55__create_production_operation_price_versions.sql` 的回填是**按 `production_operations` 派生**
（`NOT EXISTS` 守卫）⇒ 它执行那一刻**工序库里没有行**的租户/工序**整批静默跳过**：

| 租户 | `production_operations`（活跃） | `production_operation_price_versions`（活跃） | 活跃工序缺账 |
|---|---|---|---|
| 1 词元通达 | 36 | 41 | **1**（`打包`，V79 补种未补账） |
| 20 米高POC演示布艺 | 36 | **0** | **36** |
| 21 POC彩排5605 | 36 | **0** | **36** |

后果 = 价目版本账缺 ⇒ 「**当前价 = 最新版本行**」（V55 的冻结契约）对这些工序不成立
⇒ **历史定价 / 版本化单价的回溯能力缺失**（不是 422、不报错 ⇒ **静默**，本仓最忌的形态）。
⚠️ 缺账**不只在 20/21 两户**：健康租户 1 号的 `打包` 同样缺账 —— 同一条根因
（**V55 之后进库的工序没有补账**）的另一种显形 ⇒ 闸门必须是**逐工序**的。

**为什么必须新迁移**：`MigrationRunner` 台账按**文件名**记账、已应用文件**整份跳过** ⇒
重跑 V55 不会发生（issue #4235「CI 绿、功能静默缺失」），V55 另被
`tests/unit_ci_workflows/migration_fingerprints.json` 逐字节冻结。

## 本文件钉的五件事（各有红证，互不掩盖）

1. **红证（改前必红）**：真库形态下跑 V55 ⇒ 20/21 号租户版本账 **0 行**（静默跳过）；
   跑 V96 ⇒ 差集归零、每户拿到**恰好等于其活跃工序数**的行（**数字从现场派生，不写死**）；
2. **三处一致**：迁移链终态（真跑 V55→V79→V89→V91→**V96**）↔ bootstrap 终态
   （**真跑 `docs/sql/schema.sql`**）↔ 从 `production_operations` **现场派生** —— 三处都断言
   「活跃工序缺账 = 0」，且**不写死任何条数**；
3. **幂等**：V96 跑两次净效果相同（第二次零插入；逐表行指纹一致）；
4. **反向护栏**：不覆盖商家已改（改价后再跑，值一字不动）· 不复活软删（软删的**工序**与
   **版本行**都不会被种回来）· 三张快照表一字不动；
5. **守卫能抓「条数不足」**：删掉一行版本账 ⇒ 派生真值差集非空 ⇒ 必红（注入式红证）。

## 真库判据（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

`test_v96_*` 用 `initdb`/`pg_ctl`/`psql` 起**临时集群**真跑迁移 —— 静态文本判据不够
（V83 的教训：文本守卫全绿而真库整份回滚）。
⚠️ bootstrap 那一格**真跑 schema.sql**：该文件当前在 `production_route_signals` 的 FK 上
有一条**既有**建库顺序缺陷（租户种子在它之后）⇒ 用 `ON_ERROR_STOP=0` 跑完全文，并断言
**承运面（`production_operation*`）零 ERROR** + 目标段落**真的跑到了**（活跃工序数 > 0）——
**不把「没跑到」读成「没问题」**（否则差集恒 0 = 空断言）。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
MIGRATION = MIGRATION_DIR / "V96__backfill_operation_price_versions.sql"
V55 = MIGRATION_DIR / "V55__create_production_operation_price_versions.sql"
V79 = MIGRATION_DIR / "V79__seed_fabric_route_and_packing_operation.sql"
V89 = MIGRATION_DIR / "V89__backfill_fabric_seed_for_existing_tenants.sql"
V91 = MIGRATION_DIR / "V91__backfill_baseline_operations_for_empty_catalogs.sql"
V93 = MIGRATION_DIR / "V93__backfill_route_rules_for_empty_catalogs.sql"
SCHEMA = REPO / "docs/sql/schema.sql"

#: 本迁移的 id 前缀（回滚 / 认领判据；与 V55 的 `pv-` 区分开）。
PREFIX = "pv-v96-"

#: 🔴 红线：三张快照表（本迁移的 DML 只碰 1 张**配置**表）。
SNAPSHOT_TABLES = ("processing_orders", "processing_position_operations", "production_work_logs")

#: 「活跃工序缺账」的**派生真值**（单一出处；三处一致与红证都用它，**不写死数字**）。
DERIVED_TRUTH = """
SELECT count(*) FROM production_operations o
 WHERE o.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operation_price_versions v
        WHERE v.operation_id = o.id AND v.deleted = 0);
"""


def _sql() -> str:
    assert MIGRATION.is_file(), f"被扫目标不存在：{MIGRATION}（fail-closed）"
    return MIGRATION.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释。

    ⚠️ **必须**先剥注释：本迁移的注释里**逐字**引用了 `EXISTS (production_operations …)` /
    `UPDATE` / `DELETE` 等判据片段 ⇒ 不剥的话正则命中**注释**、判据变成空断言（改代码也照样绿）。
    """
    return re.sub(r"--[^\n]*", "", sql)


def _statements(sql: str) -> str:
    """只看**真语句**（剥注释）—— 所有「不许出现 X」的判据都跑在它上面。"""
    return _strip_comments(sql)


# ══════════════════════ 静态判据（每条都有注入式红证） ══════════════════════

def guard_catalog_gate(sql: str) -> list:
    """🔴 存在性护栏（**缺陷成因**）：`EXISTS (SELECT … FROM production_operations …)`。

    V72 ⑤ / V84 的缺陷形态：被派生面为空 ⇒ 整批静默跳过。本迁移**刻意不带**它。
    """
    return re.findall(
        r"(?:NOT\s+)?EXISTS\s*\(\s*SELECT[^()]*FROM\s+production_operations\b",
        _statements(sql), re.I | re.S)


def guard_tenant_level_ledger_gate(sql: str) -> list:
    """租户级账本闸门（另一种「静默跳过」形态）：`NOT EXISTS` 里按 `tenant_id` 判。

    逐工序去重必须按 `v.operation_id = o.id`；按租户判 ⇒ 该租户**整块**被跳过
    （有账的租户不会再被补，没账的租户也会因为别的原因漏）。
    """
    return re.findall(r"v\.tenant_id\s*=\s*(?:o|t)\.id", _statements(sql), re.I)


def guard_no_update_or_delete(sql: str) -> list:
    """红线：**无 UPDATE / DELETE**（不覆盖商家已改、不复活软删）。"""
    return re.findall(r"\b(UPDATE|DELETE|TRUNCATE)\b", _statements(sql), re.I)


def guard_idempotency(sql: str) -> list:
    """幂等构件：逐工序 `NOT EXISTS`（按 `v.operation_id = o.id`）+ `ON CONFLICT (id) DO NOTHING`。"""
    body = _statements(sql)
    missing = []
    if not re.search(r"NOT\s+EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+production_operation_price_versions\s+v"
                     r"\s+WHERE\s+v\.operation_id\s*=\s*o\.id\s*\)", body, re.I | re.S):
        missing.append("逐工序 NOT EXISTS(v.operation_id = o.id)")
    if not re.search(r"ON\s+CONFLICT\s*\(\s*id\s*\)\s*DO\s+NOTHING", body, re.I):
        missing.append("ON CONFLICT (id) DO NOTHING")
    return missing


def guard_explicit_types(sql: str) -> list:
    """显式类型（**V79 的真库事故教训**）：`unit_price` 必须显式 `::numeric`。"""
    body = _statements(sql)
    return [] if re.search(r"unit_price::numeric", body, re.I) else ["unit_price 未显式 ::numeric"]


def guard_explicit_columns(sql: str) -> list:
    """**显式写列**（不许 `INSERT INTO t SELECT …` 隐式对齐列序）。"""
    body = _statements(sql)
    m = re.search(r"INSERT\s+INTO\s+production_operation_price_versions\s*\(([^)]*)\)", body, re.I | re.S)
    if not m:
        return ["INSERT 未显式写列"]
    cols = [c.strip() for c in m.group(1).split(",")]
    return [] if cols == ["id", "tenant_id", "operation_id", "unit_price", "created_at"] else [f"列清单不符：{cols}"]


def guard_no_snapshot_tables(sql: str) -> list:
    """🔴 红线：三张快照表在**真语句**里一字不提。"""
    body = _statements(sql)
    return [t for t in SNAPSHOT_TABLES if re.search(r"\b" + re.escape(t) + r"\b", body)]


def guard_not_a_literal_seed(sql: str) -> list:
    """**派生**语句（不是字面量 `VALUES` 种子）。

    理由：`tests/unit_ci_workflows/test_production_catalog_seed.py` 把
    「`INSERT INTO <表> … VALUES`」认成**字面量种子源**并参与逐值比对 ⇒ 本文件若写成字面量，
    会把自己追加进那条射程（**假红**）。派生形态（`INSERT … SELECT … FROM production_operations`）
    与 V55 / V56 / V91 同形。
    """
    body = _statements(sql)
    return ["出现 VALUES 关键字（会被当字面量种子源）"] if re.search(r"\bVALUES\b", body, re.I) else []


def guard_rollback_and_stop_conditions(sql: str) -> list:
    """回滚（**只删本单前缀**）+ 停止条件（含「**V91 未合入不得先上**」）必须写在文件里。"""
    problems = []
    if f"LIKE '{PREFIX}%'" not in sql:
        problems.append(f"回滚未按本单前缀 `{PREFIX}%` 认领")
    if not re.search(r"V91\s*未合入", sql):
        problems.append("停止条件缺「V91 未合入不得先上」")
    if not re.search(r"##\s*回滚", sql):
        problems.append("缺「回滚」节")
    if not re.search(r"##\s*停止条件", sql):
        problems.append("缺「停止条件」节")
    return problems


class TestMigrationShape:
    """静态判据：迁移文本本身必须满足的形态（每条对应一条注入式红证）。"""

    def test_v96_is_a_derivation_with_explicit_columns_and_types(self):
        sql = _sql()
        assert guard_not_a_literal_seed(sql) == [], guard_not_a_literal_seed(sql)
        assert guard_explicit_columns(sql) == [], guard_explicit_columns(sql)
        assert guard_explicit_types(sql) == [], guard_explicit_types(sql)

    def test_v96_carries_no_existence_guard_and_no_tenant_level_gate(self):
        """🔴 本迁移**刻意不带**存在性护栏 —— 那正是缺陷成因（与 #4714 同款判断）。"""
        sql = _sql()
        assert guard_catalog_gate(sql) == [], (
            f"V96 带了 `EXISTS (… FROM production_operations …)` 护栏：{guard_catalog_gate(sql)} "
            "—— 工序库为空时会让本迁移**静默空跑**（正是本单要治的形态）")
        assert guard_tenant_level_ledger_gate(sql) == [], (
            f"V96 按 tenant_id 判账（租户级闸门）：{guard_tenant_level_ledger_gate(sql)}")

    def test_v96_is_idempotent_and_write_only(self):
        sql = _sql()
        assert guard_idempotency(sql) == [], guard_idempotency(sql)
        assert guard_no_update_or_delete(sql) == [], (
            f"V96 出现 UPDATE/DELETE：{guard_no_update_or_delete(sql)} —— 不覆盖商家已改、不复活软删")

    def test_v96_leaves_the_three_snapshot_tables_untouched(self):
        assert guard_no_snapshot_tables(_sql()) == [], guard_no_snapshot_tables(_sql())

    def test_v96_documents_rollback_and_stop_conditions(self):
        assert guard_rollback_and_stop_conditions(_sql()) == [], guard_rollback_and_stop_conditions(_sql())

    def test_v96_does_not_rerun_v55_and_v55_is_still_frozen(self):
        """承重前提：本单**不改** V55（已发布迁移不可变），V96 是新文件。

        红证：把 V96 的修复写回 V55 ⇒ 指纹守卫
        （`tests/unit_ci_workflows/test_migration_immutability.py`）必红；本判据钉「新迁移」这一形态。
        """
        assert MIGRATION.name == "V96__backfill_operation_price_versions.sql", MIGRATION.name
        assert V55.is_file(), "V55 必须仍在（本单只读它）"
        assert "production_operation_price_versions" in V55.read_text(encoding="utf-8")

    def test_guard_detects_injected_drift(self):
        """注入式自证：每个守卫**都会红**（不会红的判据 = 空断言）。"""
        sql = _sql()

        # ① 注入存在性护栏 ⇒ guard_catalog_gate 红
        injected = sql.replace(
            "   AND NOT EXISTS (\n       SELECT 1 FROM production_operation_price_versions v",
            "   AND EXISTS (SELECT 1 FROM production_operations x)\n"
            "   AND NOT EXISTS (\n       SELECT 1 FROM production_operation_price_versions v")
        assert injected != sql, "注入点未命中（判据自己选择沉默）"
        assert guard_catalog_gate(injected) != []

        # ② 改成租户级账闸门 ⇒ guard_tenant_level_ledger_gate 红
        injected = sql.replace("WHERE v.operation_id = o.id)", "WHERE v.tenant_id = o.id)")
        assert injected != sql
        assert guard_tenant_level_ledger_gate(injected) != []

        # ③ 加一条 UPDATE ⇒ guard_no_update_or_delete 红
        injected = sql + "\nUPDATE production_operations SET unit_price = 0;\n"
        assert guard_no_update_or_delete(injected) != []

        # ④ 去掉 ON CONFLICT ⇒ guard_idempotency 红
        injected = sql.replace("ON CONFLICT (id) DO NOTHING;", ";")
        assert injected != sql
        assert guard_idempotency(injected) != []

        # ⑤ 去掉 ::numeric ⇒ guard_explicit_types 红
        injected = sql.replace("o.unit_price::numeric", "o.unit_price")
        assert injected != sql
        assert guard_explicit_types(injected) != []

        # ⑥ 隐式列序 ⇒ guard_explicit_columns 红
        injected = sql.replace(
            "INSERT INTO production_operation_price_versions\n"
            "    (id, tenant_id, operation_id, unit_price, created_at)\nSELECT",
            "INSERT INTO production_operation_price_versions\nSELECT")
        assert injected != sql
        assert guard_explicit_columns(injected) != []

        # ⑦ 提到快照表 ⇒ guard_no_snapshot_tables 红
        injected = sql + "\nSELECT 1 FROM production_work_logs;\n"
        assert guard_no_snapshot_tables(injected) != []

        # ⑧ 写成字面量 VALUES ⇒ guard_not_a_literal_seed 红
        injected = sql.replace("SELECT 'pv-v96-' || o.id,", "VALUES ('pv-v96-x',")
        assert injected != sql
        assert guard_not_a_literal_seed(injected) != []

        # ⑨ 去掉回滚前缀 ⇒ guard_rollback_and_stop_conditions 红
        injected = sql.replace(f"LIKE '{PREFIX}%'", "LIKE 'pv-%'")
        assert injected != sql
        assert guard_rollback_and_stop_conditions(injected) != []


class TestBootstrapOrdering:
    """bootstrap 那一格（`docs/sql/schema.sql` 不跑迁移链）**已经是终态** —— 本单只加指针注释。

    承重判据 = **顺序**：schema.sql 的单价版本回填段必须位于**所有** `production_operations`
    写语句**之后**（否则 bootstrap 建出的库会缺账，正是本单要治的形态）。
    """

    def test_bootstrap_price_version_backfill_runs_after_every_operation_write(self):
        body = SCHEMA.read_text(encoding="utf-8")
        lines = _strip_comments(body).split("\n")
        backfill = [i for i, l in enumerate(lines)
                    if re.search(r"INSERT\s+INTO\s+production_operation_price_versions", l, re.I)]
        assert backfill, "schema.sql 里找不到单价版本回填段（bootstrap 会缺账）"
        first_backfill = backfill[0]
        writes = [i for i, l in enumerate(lines)
                  if i < first_backfill
                  and re.search(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+production_operations\b", l, re.I)]
        after = [i for i, l in enumerate(lines)
                 if i > first_backfill
                 and re.search(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+production_operations\b", l, re.I)]
        assert writes, "回填段之前应当有工序库写语句（否则本判据是空断言）"
        assert after == [], (
            f"schema.sql 第 {[i + 1 for i in after]} 行在单价版本回填**之后**写 production_operations "
            "—— bootstrap 建出的库会缺账（本单要治的形态）⇒ 回填段必须移到所有工序写语句之后")

    def test_schema_sql_points_at_v96(self):
        """指针注释（本单对 schema.sql 的**唯一**改动）：不复制派生语句（复制 = 多一份会漂移的口径）。"""
        body = SCHEMA.read_text(encoding="utf-8")
        assert "V96" in body, "schema.sql 未指向 V96（迁移链的对应补种）"
        assert body.count("INSERT INTO production_operation_price_versions") == 1, (
            "schema.sql 出现了第二段单价版本回填 —— 会造出第二份会漂移的口径")


# ══════════════════════ 真库判据（本机 PG 二进制；缺则显式 skip） ══════════════════════

_PG_BINARIES = ("initdb", "pg_ctl", "psql")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Pg:
    """临时集群句柄：`sql()` 严格跑（ON_ERROR_STOP=1）；`loose_file()` 宽松跑整份文件。"""

    def __init__(self, sockdir, port):
        self.sockdir, self.port = sockdir, port

    def sql(self, text: str) -> str:
        proc = subprocess.run(
            ["psql", "-h", str(self.sockdir), "-p", str(self.port), "-U", "postgres",
             "-d", "postgres", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=text, text=True, capture_output=True)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def loose_file(self, path: Path) -> str:
        """宽松跑（`ON_ERROR_STOP=0`）：schema.sql 有一条**既有**建库顺序缺陷（见模块 docstring）。"""
        proc = subprocess.run(
            ["psql", "-h", str(self.sockdir), "-p", str(self.port), "-U", "postgres",
             "-d", "postgres", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=0", "-f", str(path)],
            text=True, capture_output=True)
        return proc.stdout + proc.stderr


@pytest.fixture
def pg(tmp_path):
    missing = [b for b in _PG_BINARIES if shutil.which(b) is None]
    if missing:
        pytest.skip(f"本机没有 PG 二进制 {missing} ⇒ 真库判据未跑（不是通过）")
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限（实测：tmp_path 太长 ⇒ `pg_ctl start` 失败）。
    sockdir = Path(tempfile.mkdtemp(prefix="pg4741-"))
    log = tmp_path / "pg.log"
    subprocess.run(["initdb", "-D", str(datadir), "-U", "postgres", "-A", "trust"],
                   check=True, capture_output=True)
    port = _free_port()
    started = subprocess.run(
        ["pg_ctl", "-D", str(datadir), "-l", str(log), "-o",
         f"-k {sockdir} -p {port} -c listen_addresses=''", "start"],
        capture_output=True, text=True)
    assert started.returncode == 0, (
        f"临时集群起不来：{started.stdout}\n{started.stderr}\n"
        f"{log.read_text(encoding='utf-8') if log.exists() else ''}")
    try:
        yield _Pg(sockdir, port)
    finally:
        subprocess.run(["pg_ctl", "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


def _ddl_from_schema(table: str) -> str:
    """从 `docs/sql/schema.sql` 抽出**真终态 DDL**（不手抄列清单 —— 手抄会漂移）。

    含 `CREATE TABLE` + 该表**所有** `ALTER TABLE … ADD COLUMN IF NOT EXISTS` 语句
    （终态列集由 schema.sql 自己给，例如 `production_operations.source` / `.scope` 是
    V62 / V67 的 ALTER 加的，不在 CREATE TABLE 里）。
    """
    body = SCHEMA.read_text(encoding="utf-8")
    m = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{table}\s*\(.*?\n\);", body, re.S)
    assert m, f"schema.sql 里找不到 {table} 的 DDL"
    alters = re.findall(
        rf"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS [^;]*;", body, re.I | re.S)
    return m.group(0) + "\n" + "\n".join(alters) + "\n"


#: 与真实迁移链同形的**最小** DDL：真表结构（从 schema.sql 抽）+ V49 的部分唯一索引
#: + 三张快照表（**红线：本迁移一字不动**，建出来才能机械核验）。
_DDL = (
    _ddl_from_schema("tenants")
    + _ddl_from_schema("production_operations")
    + """
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operations_tenant_name
    ON production_operations (tenant_id, name) WHERE deleted = 0;
CREATE TABLE processing_orders (id VARCHAR(64) PRIMARY KEY, items_snapshot JSONB);
CREATE TABLE processing_position_operations (id VARCHAR(64) PRIMARY KEY, unit_price NUMERIC(10,2));
CREATE TABLE production_work_logs (id VARCHAR(64) PRIMARY KEY, unit_price NUMERIC(10,2),
                                   factor NUMERIC(6,3));
"""
)

#: 1 号租户的工序库（V54 ∪ V56 的**子集**；数量不是判据 —— 判据一律从现场派生）。
_TENANT1_OPS = ("精裁-布", "布三边", "纱三边", "韩褶-布", "上车布-布", "打孔-布",
                "帘头制作", "熨烫-布", "定型-布", "外帘打卷", "外帘装袋", "外帘发货",
                "绑带-纱", "logo条-布", "立边-布")

_TENANT_IDS = (1, 20, 21)


def _strip_statements_touching(sql: str, tables) -> str:
    """删掉**引用到**这些表的语句（按 `;` 切段）—— harness 的 DDL 只建本单触碰的表。

    ⚠️ 逐段判断（不是按「表名紧跟在动词后」的正则）：V79 有 `INSERT … JOIN` 形态，
    按动词+表名的正则会漏掉它，psql 当场报「关系不存在」（实测）。
    被删的段落与本单的判据无关；**V55 / V79 / V89 / V91 的 `production_operations` 段原样执行**。
    """
    kept = []
    for chunk in re.split(r"(?<=;)\s*\n", sql):
        if any(re.search(r"\b" + re.escape(t) + r"\b", _strip_comments(chunk)) for t in tables):
            continue
        kept.append(chunk)
    return "\n".join(kept)


_OTHER_TABLES = ("production_operation_positions", "production_routings",
                 "production_route_templates", "production_crafts", "production_option_factors")


def _replay_chain_to_just_before_v96(pg) -> None:
    """真跑迁移链的**承运段**：V55 →（租户 20/21 后建）→ V89 → V91（= V96 之前的状态）。

    与真库时间线同形：V54/V56 的工序种子只种 1 号租户；20/21 号租户**建得晚**
    （V79 的按租户循环跑时它们还不存在）⇒ 它们的 `打包` 来自 V89、其余 35 道来自 V91。
    """
    pg.sql(_DDL)
    ops = ",".join(f"('op-v54-{i:02d}', 1, '{n}')" for i, n in enumerate(_TENANT1_OPS))
    pg.sql("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE "
           "VALUES (1, '词元通达', 'migao');"
           f"INSERT INTO production_operations (id, tenant_id, name) VALUES {ops};")
    # ① V55：建表 + 回填（此刻只有 1 号租户有工序库 ⇒ 20/21 注定拿不到账）
    pg.sql(V55.read_text(encoding="utf-8"))
    # ② V79：1 号租户拿到 `配料` / `打包`（**V79 当时没补账** —— 本单的同族半边）
    pg.sql(_strip_statements_touching(V79.read_text(encoding="utf-8"), _OTHER_TABLES))
    # ③ 20/21 号租户此时才建（真库时间线）
    pg.sql("INSERT INTO tenants (id, name, code) OVERRIDING SYSTEM VALUE VALUES "
           "(20, '米高POC演示布艺', 'poc20'), (21, 'POC彩排5605', 'poc21');")
    # ④ V89 / V91：给 20/21 补 `打包` + 其余 35 道基线工序
    pg.sql(_strip_statements_touching(V89.read_text(encoding="utf-8"), _OTHER_TABLES))
    pg.sql(_strip_statements_touching(V91.read_text(encoding="utf-8"), _OTHER_TABLES))


def _derived_truth(pg) -> int:
    """从 `production_operations` **现场派生**的「活跃工序缺账」条数（**不写死数字**）。"""
    return int(pg.sql(DERIVED_TRUTH).strip())


def _missing_by_tenant(pg) -> dict:
    out = pg.sql("""
        SELECT o.tenant_id || '|' || count(*) FROM production_operations o
         WHERE o.deleted = 0
           AND NOT EXISTS (SELECT 1 FROM production_operation_price_versions v
                            WHERE v.operation_id = o.id AND v.deleted = 0)
         GROUP BY o.tenant_id ORDER BY o.tenant_id;""")
    return {int(a): int(b) for a, b in (l.split("|") for l in out.split() if l)}


def _active_ops_by_tenant(pg) -> dict:
    out = pg.sql("SELECT tenant_id || '|' || count(*) FROM production_operations "
                 "WHERE deleted = 0 GROUP BY tenant_id ORDER BY tenant_id;")
    return {int(a): int(b) for a, b in (l.split("|") for l in out.split() if l)}


def _ledger_rows(pg, tenant_id: int) -> int:
    return int(pg.sql("SELECT count(*) FROM production_operation_price_versions "
                      f"WHERE tenant_id = {tenant_id} AND deleted = 0;").strip())


def _fingerprint(pg, table: str) -> str:
    """内容指纹（**禁 mtime/size**）：全行 md5（#4260 的红证卫生纪律）。"""
    out = pg.sql(f"SELECT coalesce(md5(string_agg(t::text, '|' ORDER BY t::text)), '-') "
                 f"FROM {table} t;").strip()
    return out or "-"


def test_before_v96_the_ledger_is_empty_for_backfilled_catalogs(pg):
    """🔴 红证（改前必红）：真库形态下，V55 之后进库的工序**整批没有版本账**（静默、不报错）。"""
    _replay_chain_to_just_before_v96(pg)

    active = _active_ops_by_tenant(pg)
    missing = _missing_by_tenant(pg)
    assert active.get(20, 0) > 0, "前提失效：20 号租户的工序库应由 V91 补满（否则本判据是空断言）"
    assert active.get(21, 0) > 0, "前提失效：21 号租户的工序库应由 V91 补满"
    assert _ledger_rows(pg, 20) == 0, (
        "红证失效：20 号租户的版本账本应为 **0 行**（V55 派生时它还没有工序）"
        "—— 若这里已有账，说明 V55 的派生口径被改了（那是已发布迁移，不可改）")
    assert _ledger_rows(pg, 21) == 0, "红证失效：21 号租户同上"
    assert missing.get(20) == active[20], "20 号租户**全部**活跃工序都应缺账"
    assert missing.get(21) == active[21], "21 号租户同上"
    assert missing.get(1, 0) > 0, (
        "红证失效：1 号租户也应有缺账工序（`打包` —— V79 补种未补账）"
        "；若为 0，说明缺账只发生在空库租户上，本单的逐工序闸门判据需重新核")


def test_v96_backfills_and_the_three_carriers_agree(pg):
    """判据 1/2/3 真库：V96 后**三处一致**都归零，且每户拿到恰好等于其活跃工序数的账。"""
    _replay_chain_to_just_before_v96(pg)
    before = _derived_truth(pg)
    assert before > 0, "红证前提失效：改前差集应为正（否则 V96 是空跑）"

    pg.sql(_sql())

    assert _derived_truth(pg) == 0, "V96 后仍有活跃工序没有版本账"
    active = _active_ops_by_tenant(pg)
    for tenant in _TENANT_IDS:
        # 数字**从现场派生**：该租户的账行数 ≥ 其活跃工序数（含历史改价行 ⇒ 用 ≥）
        assert _ledger_rows(pg, tenant) >= active[tenant], (
            f"租户 {tenant}：账行 {_ledger_rows(pg, tenant)} < 活跃工序 {active[tenant]}")
    # 每一行都如实记当前价（不是发明价、不是 0）
    bad = pg.sql("""
        SELECT count(*) FROM production_operations o
          JOIN production_operation_price_versions v
            ON v.operation_id = o.id AND v.deleted = 0
         WHERE o.deleted = 0 AND v.id LIKE 'pv-v96-%' AND v.unit_price <> o.unit_price;""").strip()
    assert bad == "0", f"{bad} 行账的单价 ≠ 工序库当前价（V96 发明了价）"
    # id 认领：本迁移的行**只**用本单前缀
    assert pg.sql("SELECT count(*) FROM production_operation_price_versions "
                  "WHERE id NOT LIKE 'pv-v96-%' AND id LIKE 'pv-v96%';").strip() == "0"


def test_guard_red_when_one_ledger_row_is_deleted(pg):
    """🔴 红证（守卫能抓「条数不足」）：删一条账 ⇒ 派生真值差集**必红**。"""
    _replay_chain_to_just_before_v96(pg)
    pg.sql(_sql())
    assert _derived_truth(pg) == 0

    victim = pg.sql("SELECT operation_id FROM production_operation_price_versions "
                    "WHERE deleted = 0 ORDER BY operation_id LIMIT 1;").strip()
    assert victim, "前提失效：V96 后应至少有一行账"
    pg.sql(f"DELETE FROM production_operation_price_versions WHERE operation_id = '{victim}';")
    assert _derived_truth(pg) == 1, "守卫失效：删掉一行账后差集仍为 0（= 空断言）"

    pg.sql(_sql())
    assert _derived_truth(pg) == 0, "重跑 V96 应把删掉的那条补回来（迁移是幂等补种，不是一次性）"


def test_v96_is_idempotent_on_real_postgres(pg):
    """反向护栏：跑两次净效果相同（第二次零插入；逐表内容指纹一致）。"""
    _replay_chain_to_just_before_v96(pg)
    pg.sql(_sql())
    first = {t: _fingerprint(pg, t) for t in ("production_operation_price_versions",) + SNAPSHOT_TABLES}
    count_first = int(pg.sql("SELECT count(*) FROM production_operation_price_versions;").strip())

    pg.sql(_sql())
    second = {t: _fingerprint(pg, t) for t in ("production_operation_price_versions",) + SNAPSHOT_TABLES}
    count_second = int(pg.sql("SELECT count(*) FROM production_operation_price_versions;").strip())

    assert count_first == count_second, f"重跑后账行数变了：{count_first} → {count_second}"
    assert first == second, "重跑后内容指纹变了（不是幂等）"


def test_v96_does_not_overwrite_merchant_edits(pg):
    """反向护栏：商家改过价（账上有行）⇒ V96 一字不动。"""
    _replay_chain_to_just_before_v96(pg)
    pg.sql(_sql())

    victim = pg.sql("SELECT operation_id FROM production_operation_price_versions "
                    "WHERE id LIKE 'pv-v96-%' AND deleted = 0 ORDER BY operation_id LIMIT 1;").strip()
    assert victim, "前提失效：应有本迁移插入的账行"
    # 模拟商家改价：工序库价 + 同事务追加一行账（写面 `ProductionOperationCommandService` 的口径）
    pg.sql(f"UPDATE production_operations SET unit_price = 9.99 WHERE id = '{victim}';"
           f"INSERT INTO production_operation_price_versions (id, tenant_id, operation_id, unit_price) "
           f"SELECT 'pv-merchant-1', tenant_id, id, 9.99 FROM production_operations WHERE id = '{victim}';")
    before = _fingerprint(pg, "production_operation_price_versions")

    pg.sql(_sql())

    assert _fingerprint(pg, "production_operation_price_versions") == before, (
        "V96 覆盖/追加了商家已改的账（红线）")
    newest = pg.sql("SELECT unit_price FROM production_operation_price_versions "
                    f"WHERE operation_id = '{victim}' AND deleted = 0 "
                    "ORDER BY created_at DESC, id DESC LIMIT 1;").strip()
    assert newest == "9.99", f"最新版本行不是商家改的价：{newest}"


def test_v96_does_not_resurrect_soft_deleted(pg):
    """反向护栏：软删的**工序**与**版本行**都不会被种回来（含软删行的闸门是承重的）。"""
    _replay_chain_to_just_before_v96(pg)
    pg.sql(_sql())

    # ① 软删工序 ⇒ 不再为它补账
    op = pg.sql("SELECT id FROM production_operations WHERE deleted = 0 ORDER BY id LIMIT 1;").strip()
    pg.sql(f"UPDATE production_operations SET deleted = 1 WHERE id = '{op}';"
           f"DELETE FROM production_operation_price_versions WHERE operation_id = '{op}';")
    pg.sql(_sql())
    assert pg.sql("SELECT count(*) FROM production_operation_price_versions "
                  f"WHERE operation_id = '{op}';").strip() == "0", "V96 复活了软删工序的账"

    # ② 软删**版本行**（该工序再无活跃账行）⇒ 仍不补（有过账行 = 记过账）
    op2 = pg.sql("SELECT operation_id FROM production_operation_price_versions "
                 "WHERE deleted = 0 ORDER BY operation_id LIMIT 1;").strip()
    assert op2 and op2 != op, "前提失效：需要一个仍有活跃账的工序"
    pg.sql(f"UPDATE production_operation_price_versions SET deleted = 1 WHERE operation_id = '{op2}';")
    pg.sql(_sql())
    assert pg.sql("SELECT count(*) FROM production_operation_price_versions "
                  f"WHERE operation_id = '{op2}' AND deleted = 0;").strip() == "0", (
        "V96 复活了商家软删的版本行（闸门漏了 `deleted` 之外的形态）")


def test_v96_leaves_snapshot_tables_untouched(pg):
    """🔴 红线：三张快照表一字不动（有哨兵行才不是空断言）。"""
    _replay_chain_to_just_before_v96(pg)
    pg.sql("INSERT INTO processing_orders (id, items_snapshot) VALUES ('po-1', '[]'::jsonb);"
           "INSERT INTO processing_position_operations (id, unit_price) VALUES ('ppo-1', 1.23);"
           "INSERT INTO production_work_logs (id, unit_price, factor) VALUES ('wl-1', 4.00, 1.70);")
    before = {t: _fingerprint(pg, t) for t in SNAPSHOT_TABLES}

    pg.sql(_sql())

    after = {t: _fingerprint(pg, t) for t in SNAPSHOT_TABLES}
    assert before == after, f"快照表被写了：{ {k: (before[k], after[k]) for k in before if before[k] != after[k]} }"
    assert guard_no_snapshot_tables(_sql()) == []


def test_bootstrap_schema_sql_terminal_state_matches_derived_truth(pg):
    """bootstrap 那一格**真跑一遍**：`docs/sql/schema.sql` 建出的库，活跃工序缺账 = **0**。

    ⚠️ schema.sql 有一条**既有**建库顺序缺陷（`production_route_signals` 的种子在租户种子之前）
    ⇒ 用 `ON_ERROR_STOP=0` 跑完全文；但**承运面零 ERROR** 与「目标段落真的跑到了」两件都断言
    —— **不把「没跑到」读成「没问题」**（否则差集恒 0 = 空断言）。
    """
    out = pg.loose_file(SCHEMA)
    errors = [l for l in out.splitlines() if "错误:" in l or "ERROR:" in l]
    carrier_errors = [l for l in errors if "production_operation" in l]
    assert carrier_errors == [], f"schema.sql 的承运面报错：{carrier_errors}"

    active = int(pg.sql("SELECT count(*) FROM production_operations WHERE deleted = 0;").strip())
    assert active > 0, (
        "schema.sql 的工序种子段落**没跑到**（活跃工序 = 0）⇒ 本判据会退化成空断言；"
        f"现场输出：{out[-500:]}")
    assert _derived_truth(pg) == 0, (
        "bootstrap 终态缺账：schema.sql 的单价版本回填段没有覆盖所有活跃工序"
        "（回填段必须在**所有** production_operations 写语句之后）")
    # `打包` 这一道（V79 补种、迁移链上曾缺账）在 bootstrap 上必须有账
    packed = pg.sql("SELECT count(*) FROM production_operations o "
                    "JOIN production_operation_price_versions v "
                    "ON v.operation_id = o.id AND v.deleted = 0 "
                    "WHERE o.deleted = 0 AND o.name = '打包';").strip()
    assert packed != "0", "bootstrap 上 `打包` 缺账（迁移链的同族半边在 bootstrap 未覆盖）"
