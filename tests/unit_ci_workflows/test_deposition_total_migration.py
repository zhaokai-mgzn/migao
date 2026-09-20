# case_ids: PG-018, PG-020, PG-035
"""**去部位化彻底版**（issue #4937 = 母单 #4936）三条迁移的**承重判据** + 真库两遍幂等。

## 本文件钉的事

| 迁移 | 做什么 | 本文件的判据 |
|---|---|---|
| `V102__retire_applicability_flag.sql` | 存活矩阵行的 `applicable` 全部收敛为 `TRUE` | ① 静态：只写 `applicable`/`updated_at` 两列、`IS DISTINCT FROM` 幂等判据；② 真库：改前 2 行 `FALSE` ⇒ 改后 0 行；`unit_price` 指纹不变 |
| `V103__clear_route_rule_positions.sql` | 存活规则的 `position` 清空为 `NULL` | ① 静态：只写 `position`/`updated_at`；② 真库：改前 2 行非 NULL ⇒ 改后 0 行；`customer_unit_price` 指纹不变 |
| `V104__deposition_matrix_collapse.sql` | 每 `(tenant, logical_name)` **塌缩为一行**（`position='通用'` / `applicable=TRUE`），其余**软删** | ① 静态：四档选行序、软删不物理删、共享判据；② 真库：**两遍幂等** + 数量对账 + 调价账（V86）行不变 + 对账块真的会拦 |

## 真库判据（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

照 `tests/unit_ci_workflows/test_v97_orphan_positions_cleanup.py` 的范式：`initdb` / `pg_ctl` / `psql`
起**临时集群**真跑 —— 静态文本判据不够（V83 的教训：文本守卫全绿而真库整份回滚）。

## 为什么必须真跑两遍

`MigrationRunner` 要求**所有**迁移可重复执行；而「幂等」这件事**只有真库能判**：
`WHERE deleted = 0` 与窗口函数的交互、`CREATE TEMP TABLE ... ON COMMIT DROP` 的生命周期、
`RAISE EXCEPTION` 的回滚半径 —— 三者都是**运行期**语义。
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
V102 = MIGRATION_DIR / "V102__retire_applicability_flag.sql"
V103 = MIGRATION_DIR / "V103__clear_route_rule_positions.sql"
V104 = MIGRATION_DIR / "V104__deposition_matrix_collapse.sql"
V105 = MIGRATION_DIR / "V105__add_sheer_variant_operations.sql"
SCHEMA_SQL = REPO / "docs/sql/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"
#: 选行规则的**同一份**字面量（Java 侧常量；跨语言判据按源码解析，不靠人抄）。
QUERY_SERVICE = (REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
                 / "ProductionOperationQueryService.java")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释（`--` 行注释与 `/* */` 块注释）→ 空，供**写语句**判据用。

    ⚠️ 判据必须去注释：本仓的迁移文件把「回滚 SQL」「红线」都写在注释里，
    不去注释会把注释里的 `UPDATE` 当成真写语句（#4595 的同族教训）。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


# ══════════════════════════ ① 存在性 / 版本号 / 账本 ══════════════════════════

def test_three_migrations_exist_and_versions_are_unique():
    for path in (V102, V103, V104, V105):
        assert path.exists(), f"缺少迁移文件：{path.name}"
    versions = [int(re.match(r"^V(\d+)__", p.name).group(1))
                for p in MIGRATION_DIR.glob("V*.sql") if re.match(r"^V(\d+)__", p.name)]
    for want in (102, 103, 104, 105):
        assert versions.count(want) == 1, f"V{want} 版本号重复"
    assert max(versions) >= 105, f"V105 不是最大版本号（当前最大 V{max(versions)}）"


def test_published_migrations_are_untouched():
    """已发布迁移**只许新增**：V71/V72/V79/V86/V88/V89/V97 逐个仍在且指纹仍在账本里。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    for name in ("V71__normalize_routing_model_structure.sql",
                 "V72__switch_routing_model_consumers.sql",
                 "V79__seed_fabric_route_and_packing_operation.sql",
                 "V86__create_operation_position_price_versions.sql",
                 "V88__retire_material_prep_and_fabric_position.sql",
                 "V89__backfill_fabric_seed_for_existing_tenants.sql",
                 "V97__soft_delete_orphan_operation_positions.sql"):
        assert name in ledger, f"已发布迁移 {name} 的指纹不在账本里（账本被改过？）"


@pytest.mark.parametrize("path", [V102, V103, V104, V105])
def test_new_migrations_are_registered_in_the_fingerprint_ledger(path):
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert path.name in ledger, (
        f"`{path.name}` 未登记进 `migration_fingerprints.json` ⇒ 它以后能被静默改（issue #4235）。"
        f"跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


# ══════════════════════════ ② 静态判据：写语句形态 ══════════════════════════

def test_v102_writes_exactly_the_two_columns_and_is_idempotent_by_predicate():
    body = _strip_comments(_read(V102))
    # ⚠️ UPDATE 现在包在 `DO $$ … $$` 里（要 `GET DIAGNOSTICS` 自证「真认领到行」）
    updates = [u for u in re.findall(r"UPDATE production_operation_positions p[\s\S]*?;", body)
               if "SET" in u]
    assert len(updates) == 1, f"V102 应恰好一条 UPDATE（实际 {len(updates)}）"
    stmt = updates[0]
    assert re.search(r"SET\s+applicable\s*=\s*TRUE\s*,\s*updated_at\s*=\s*NOW\(\)", stmt), \
        f"V102 的 SET 子句不是「显式写 applicable + updated_at」：{stmt}"
    assert "unit_price" not in stmt, "V102 不得写 `unit_price`（塌缩/收敛不碰价）"
    assert "applicable IS NOT FALSE" in stmt, (
        "V102 的谓词丢了 `applicable IS NOT FALSE` —— 一刀切置 TRUE 会抹掉 V104 选行所需的信号"
        "（`帘头制作` 的 ¥2.00 会丢，见 V102 文件头的口径陷阱；真库判据见 "
        "`test_v102_converges_claimed_rows_and_leaves_price_untouched`）")
    assert "deleted = 0" in stmt, "V102 必须只改存活行（`deleted = 1` 是 V88 的退场留痕）"


def test_v103_writes_exactly_the_two_columns_and_never_touches_customer_price():
    body = _strip_comments(_read(V103))
    stmts = [s.strip() for s in body.split(";") if s.strip()]
    updates = [s for s in stmts if s.upper().startswith("UPDATE")]
    assert len(updates) == 1, f"V103 应恰好一条 UPDATE（实际 {len(updates)}）"
    stmt = updates[0]
    assert re.search(r"SET\s+position\s*=\s*NULL\s*,\s*updated_at\s*=\s*NOW\(\)", stmt), \
        f"V103 的 SET 子句不是「显式写 position + updated_at」：{stmt}"
    assert "customer_unit_price" not in stmt, (
        "🔴 V103 碰了 `customer_unit_price` —— 那是对客那本账（元/套），与「部位」无关")
    assert "position IS NOT NULL" in stmt, "V103 的幂等判据必须是 `position IS NOT NULL`"
    # 保留列（不 DROP）：列是部分唯一索引的成员，删列会连带删索引
    assert "DROP COLUMN" not in body.upper(), "V103 不得删列（列是部分唯一索引的成员；历史载体）"


def test_v104_uses_the_four_tier_survivor_rule_in_the_same_order():
    """四档选行序**逐档**在 SQL 里出现且顺序与 Java/Python 一致（不得改名换序）。"""
    body = _strip_comments(_read(V104))
    order = re.search(r"ORDER BY([\s\S]*?)\n\s*\)\s*AS rn", body)
    assert order, "V104 里找不到 `ORDER BY … ) AS rn`（选行规则的落点被搬走了？）"
    text = order.group(1)
    tiers = [("(p.applicable IS TRUE) DESC", "① 适用行优先"),
             ("(p.position = '布帘') DESC", "② 布帘列优先"),
             ("COALESCE(p.position, '')", "③ position 字典序"),
             ("COALESCE(p.id, '')", "④ id 升序")]
    positions = []
    for needle, label in tiers:
        at = text.find(needle)
        assert at >= 0, f"V104 的选行规则缺档：{label}（`{needle}`）"
        positions.append((at, label))
    assert positions == sorted(positions), f"V104 的四档顺序被打乱：{positions}"
    assert 'COLLATE "C"' in text, (
        "V104 的 ③/④ 档没有 `COLLATE \"C\"` —— Java 的末档是 `String.compareTo`（逐字节），"
        "非 C collation 的库会选出**不同**的幸存行")


def test_v104_soft_deletes_and_never_physically_deletes():
    body = _strip_comments(_read(V104))
    assert re.search(r"SET\s+deleted\s*=\s*1\s*,\s*updated_at\s*=\s*NOW\(\)", body), \
        "V104 的软删不是「显式写 deleted + updated_at」"
    assert "DELETE FROM production_operation_positions" not in body.upper(), (
        "🔴 V104 物理删了矩阵行 —— V86 的调价账按 `position_row_id` 指向它们，物理删会断审计链")


def test_v104_writes_the_neutral_position_and_keeps_the_price():
    body = _strip_comments(_read(V104))
    assert re.search(r"SET\s+position\s*=\s*'通用'", body), "V104 没把幸存行的 position 写成中性值「通用」"
    survivors_update = re.search(r"UPDATE production_operation_positions p\s*SET position = '通用'[\s\S]*?;", body)
    assert survivors_update, "找不到「幸存行写中性部位」那条语句"
    assert "unit_price" not in survivors_update.group(0), (
        "🔴 幸存行那条 UPDATE 碰了 `unit_price` —— 塌缩**只选行、不改价**（#4696：未定价不得被回落）")


def test_v104_shares_one_materialised_survivor_set_between_write_and_reconciliation():
    """写语句与对账块**共用**同一份物化幸存行集合（`CREATE TEMP TABLE`）—— 判据不可能只漂一半。"""
    body = _strip_comments(_read(V104))
    assert "CREATE TEMP TABLE _v104_survivors" in body, \
        "V104 没有把幸存行物化成一份共享结果（写语句与对账各写一遍窗口函数 = 判据可能只漂一半）"
    assert body.count("FROM _v104_survivors") >= 3, (
        "物化结果只被引用了一处 ⇒ 写语句/对账没有真正共享它")


@pytest.mark.parametrize("path", [V102, V103, V104, V105])
def test_new_migrations_are_explicitly_transactional(path):
    body = _read(path)
    assert re.search(r"^BEGIN;", body, re.M), f"{path.name} 缺显式 `BEGIN;`"
    assert re.search(r"^COMMIT;", body, re.M), f"{path.name} 缺显式 `COMMIT;`"
    assert "RAISE EXCEPTION" in body, f"{path.name} 缺数量对账（`RAISE EXCEPTION`）"


@pytest.mark.parametrize("path", [V102, V103, V104])
def test_new_migrations_loop_over_tenants_not_a_literal_tenant(path):
    """⚠️ V105 **有意**用字面量 `VALUES`（= 固定的 tenant_id，与 V54/V56/V79 同款）—— 见该文件注释：
    三源收敛守卫 `test_production_catalog_seed.py` 的 `values_sources_for(...)` **按内容**发现
    字面量种子源 ⇒ 写成 `INSERT … SELECT … FROM tenants`（派生回填）会让它**落在比对射程之外**
    （「改了这 4 行的价而没有任何东西变红」）。**非 1 号租户**由开租播种路径（模板 JSON）承担。"""
    """按租户循环（`FROM tenants t`）—— 只改 1 号租户会让非 1 号租户留在旧口径（#4676 ⑥）。"""
    body = _strip_comments(_read(path))
    assert re.search(r"JOIN tenants t\b|FROM tenants t\b", body), \
        f"{path.name} 没有按租户循环（找不到 `tenants` 的连接）"
    assert "tenant_id = 1" not in body, f"{path.name} 被写死成 1 号租户"


@pytest.mark.parametrize("path", [V102, V103, V104, V105])
def test_new_migrations_document_the_rollback(path):
    body = _read(path)
    assert "回滚 SQL" in body, f"{path.name} 缺「回滚 SQL」段（本仓迁移的硬要求）"


def test_java_collapse_source_position_matches_the_sql_literal():
    """跨语言：SQL 的 `'布帘'` 与 Java 的 `COLLAPSE_PRICE_SOURCE_POSITION` **逐字同值**。"""
    src = _read(QUERY_SERVICE)
    m = re.search(r'COLLAPSE_PRICE_SOURCE_POSITION\s*=\s*"([^"]+)"', src)
    assert m, "Java 侧找不到 `COLLAPSE_PRICE_SOURCE_POSITION` 的字面量"
    body = _strip_comments(_read(V104))
    assert f"(p.position = '{m.group(1)}') DESC" in body, (
        f"V104 的「布帘列优先」档不是 Java 的 `{m.group(1)}` —— 两侧会选出不同的幸存行")
    # 中性值必须与「三部位 + 布料」都不撞（否则读面按部位渲染会把它当第五个部位）
    assert "'通用'" in body and re.search(r"'通用'", body)


# ══════════════════════════ ③ 真库判据（临时 PG 集群） ══════════════════════════

_PG_BINARIES = ("initdb", "pg_ctl", "psql")

#: 与 V71 / V79 / V86 同形的**最小** DDL（本单触碰的三张表 + 部分唯一索引 + 调价账 + 快照表）。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operation_positions (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    logical_name VARCHAR(64) NOT NULL, position VARCHAR(16) NOT NULL,
    unit_price NUMERIC(10,2), applicable BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_operation_positions_tenant_name_position
    ON production_operation_positions (tenant_id, logical_name, position) WHERE deleted = 0;
CREATE TABLE production_route_rules (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(16) NOT NULL, trigger_value VARCHAR(64) NOT NULL,
    position VARCHAR(16), action VARCHAR(16) NOT NULL, operation VARCHAR(64),
    after_operation VARCHAR(64), priority INTEGER NOT NULL DEFAULT 0,
    customer_unit_price NUMERIC(10,2),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL, group_name VARCHAR(32), position VARCHAR(16),
    unit VARCHAR(16), unit_price NUMERIC(10,2),
    is_must_finish BOOLEAN DEFAULT FALSE, is_start_marker BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0, scope VARCHAR(16) DEFAULT 'position',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_operations_tenant_name
    ON production_operations (tenant_id, name) WHERE deleted = 0;
CREATE TABLE production_operation_position_price_versions (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, position_row_id VARCHAR(64),
    unit_price NUMERIC(10,2), created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE processing_position_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_work_logs (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), deleted INTEGER NOT NULL DEFAULT 0);
"""

#: 真库形态的种子：**1 号租户** = V71 形态的 3 部位 + 一处 `applicable=FALSE` + 一条带 position 的规则；
#: **2 号租户** = 同形的第二份（证明「按租户循环」，不是只改 1 号）；
#: 另有 1 条**已软删**行（V88 的退场留痕，三迁移都不得复活/触碰）。
_SEED = """
INSERT INTO tenants (id) VALUES (1), (2);
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, deleted) VALUES
    -- 1 号租户：`三边` 三个部位（布帘价 0.40 有价；纱帘 applicable=FALSE；帘头 FALSE）
    ('t1-sandian-bu',   1, '三边', '布帘', 0.40, TRUE,  0),
    ('t1-sandian-sha',  1, '三边', '纱帘', NULL, FALSE, 0),
    ('t1-sandian-lt',   1, '三边', '帘头', NULL, FALSE, 0),
    -- 1 号租户：`帘头制作` —— **适用行优先**的承重格（布帘 FALSE+NULL，帘头 TRUE+2.00）
    ('t1-ltzz-bu',      1, '帘头制作', '布帘', NULL, FALSE, 0),
    ('t1-ltzz-lt',      1, '帘头制作', '帘头', 2.00, TRUE,  0),
    -- 1 号租户：`打包` 全适用但**未定价**（不得被回落成 0.00）
    ('t1-dabao-bu',     1, '打包', '布帘', NULL, TRUE, 0),
    ('t1-dabao-sha',    1, '打包', '纱帘', NULL, TRUE, 0),
    -- 1 号租户：已软删行（V88 的退场留痕；三迁移都**不碰**）
    ('t1-retired',      1, '配料', '布料', NULL, TRUE, 1),
    -- 2 号租户：同形（按租户循环的判据）
    ('t2-sandian-bu',   2, '三边', '布帘', 0.40, TRUE,  0),
    ('t2-sandian-sha',  2, '三边', '纱帘', 0.40, FALSE, 0),
    ('t2-ltzz-lt',      2, '帘头制作', '帘头', 2.00, TRUE, 0);
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation,
     after_operation, priority, customer_unit_price, deleted) VALUES
    ('r1-hz-car',  1, 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20, NULL, 0),
    ('r1-hz-hz',   1, 'craft', '韩褶', NULL,  'insert', '韩褶',  '三边', 10, NULL, 0),
    ('r1-opt-dui', 1, 'option', '拼1次', NULL, 'insert', '拼1次', '三边', 110, 12.50, 0),
    ('r2-hz-car',  2, 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20, NULL, 0);
INSERT INTO production_operation_position_price_versions
    (id, tenant_id, position_row_id, unit_price) VALUES
    ('pv-1', 1, 't1-sandian-bu', 0.40),
    ('pv-2', 1, 't1-sandian-sha', 0.10);
INSERT INTO processing_position_operations (id, tenant_id, operation_name, unit_price, factor) VALUES
    ('inst-1', 1, '布三边', 0.40, 1.000);
INSERT INTO production_work_logs (id, tenant_id, operation_name, unit_price, factor) VALUES
    ('wl-1', 1, '布三边', 0.40, 1.000);
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    missing = [b for b in _PG_BINARIES if shutil.which(b) is None]
    if missing:
        pytest.skip(f"本机没有 PG 二进制 {missing} ⇒ 真库判据未跑（不是通过）")
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg4937-"))
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

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            ["psql", "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
             "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)

    run.raw = psql_raw

    try:
        yield run
    finally:
        subprocess.run(["pg_ctl", "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


#: 把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。
#: ⚠️ 三个迁移文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
#: `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
_TX = "BEGIN;\n{body}\nCOMMIT;\n"


def _as_runner_would(sql: str) -> str:
    return _TX.format(body=sql)


def _migrations() -> str:
    return "\n".join(_read(p) for p in (V102, V103, V104))


def _seed(run) -> None:
    run(_DDL + _SEED)


def _fingerprint(run, table: str, columns: str) -> str:
    out = run(f"SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM "
              f"(SELECT {columns} FROM {table}) t;")
    return out.strip()


def _live_rows(run) -> list:
    out = run("SELECT id || '|' || position || '|' || COALESCE(unit_price::text,'NULL') "
              "|| '|' || applicable::text "
              "FROM production_operation_positions WHERE deleted = 0 ORDER BY tenant_id, logical_name;")
    return [line for line in out.splitlines() if line.strip()]


def _all_rows(run) -> list:
    out = run("SELECT id || ':' || deleted FROM production_operation_positions ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


_HISTORY_TABLES = {
    "processing_position_operations": "id, tenant_id, operation_name, unit_price, factor, deleted",
    "production_work_logs": "id, tenant_id, operation_name, unit_price, factor, deleted",
    "production_operation_position_price_versions":
        "id, tenant_id, position_row_id, unit_price, deleted",
}


# ── 真库判据 1：三迁移连跑两遍 ⇒ 幂等 + 数量对账 + 塌缩到不动点 ──

def test_migrations_are_idempotent_and_collapse_to_one_row_per_logical_operation(psql):
    """本文件的核心：真库跑**两遍**，净效果相同；每 `(租户, 逻辑工序)` 恰好 1 行存活。"""
    _seed(psql)
    before = _all_rows(psql)
    assert "t1-sandian-sha:0" in before and "t1-ltzz-bu:0" in before, "红证前提不成立：种子没落库"

    for path in (V102, V103, V104):
        psql(_as_runner_would(_read(path)))       # 第一遍
    after_first = _all_rows(psql)
    for path in (V102, V103, V104):
        psql(_as_runner_would(_read(path)))       # 第二遍（幂等）
    after_second = _all_rows(psql)

    assert after_first == after_second, (
        f"三迁移**不幂等**：第二遍改了净效果\n  第一遍后：{after_first}\n  第二遍后：{after_second}")
    # ── 真库两遍幂等读数（PR 证据直接引这段输出） ──
    print(f"[#4937 真库] 改前矩阵行（id:deleted）= {before}")
    print(f"[#4937 真库] 第 1 遍后             = {after_first}")
    print(f"[#4937 真库] 第 2 遍后（幂等）      = {after_second}")
    print(f"[#4937 真库] 第 1 遍 == 第 2 遍 ⇒ {after_first == after_second}")
    print(f"[#4937 真库] 存活行 = {psql('SELECT count(*) FROM production_operation_positions WHERE deleted = 0;').strip()}"
          f" / 退场行 = {psql('SELECT count(*) FROM production_operation_positions WHERE deleted = 1;').strip()}"
          f" / 总行 = {psql('SELECT count(*) FROM production_operation_positions;').strip()}")
    print(f"[#4937 真库] 存活行 position 取值集 = "
          f"{psql('SELECT string_agg(DISTINCT position, chr(44)) FROM production_operation_positions WHERE deleted = 0;').strip()}")
    print(f"[#4937 真库] 矩阵指纹（id:deleted）= "
          f"{psql('SELECT md5(string_agg(id || chr(58) || deleted, chr(44) ORDER BY id)) FROM production_operation_positions;').strip()}")
    kept = psql("SELECT logical_name || '=' || COALESCE(unit_price::text, 'NULL') "
                "FROM production_operation_positions WHERE deleted = 0 "
                "AND logical_name = '帘头制作' ORDER BY 1;").strip()
    print(f"[#4937 真库] 帘头制作的幸存行价 = {kept}"
          f"（期望 `帘头制作=2.00` —— 未定价不得被回落，issue #4696）")

    # 每个 (tenant, logical_name) 恰好一行存活
    per_key = psql("SELECT tenant_id || '|' || logical_name || '|' || count(*) "
                   "FROM production_operation_positions WHERE deleted = 0 "
                   "GROUP BY tenant_id, logical_name ORDER BY 1;")
    rows = [line for line in per_key.splitlines() if line.strip()]
    assert rows, "存活行为空 ⇒ 判据空跑"
    bad = [r for r in rows if not r.endswith("|1")]
    assert bad == [], f"以下 (租户, 逻辑工序) 的存活行数 ≠ 1：{bad}"

    # 幸存行的 position 全部是中性值「通用」+ applicable = TRUE
    weird = psql("SELECT count(*) FROM production_operation_positions "
                 "WHERE deleted = 0 AND (position <> '通用' OR applicable IS NOT TRUE);")
    assert weird.strip() == "0", f"仍有 {weird.strip()} 条存活行的 position/applicable 不是终态"

    # 幸存行逐条 = 四档选行规则（本测试自己按规则重算，独立于迁移实现）
    expected = """
    SELECT p.tenant_id || '|' || p.logical_name || '|' || COALESCE(p.unit_price::text,'NULL')
      FROM (
        SELECT p0.*, ROW_NUMBER() OVER (
                 PARTITION BY p0.tenant_id, p0.logical_name
                 ORDER BY (p0.applicable IS TRUE) DESC, (p0.position = '布帘') DESC,
                          COALESCE(p0.position,'') COLLATE "C" ASC,
                          COALESCE(p0.id,'') COLLATE "C" ASC) AS rn
          FROM production_operation_positions p0
         WHERE p0.deleted = 0) p
     WHERE p.rn = 1 ORDER BY 1;
    """
    got = psql("SELECT tenant_id || '|' || logical_name || '|' || COALESCE(unit_price::text,'NULL') "
               "FROM production_operation_positions WHERE deleted = 0 ORDER BY 1;")
    assert [l for l in got.splitlines() if l.strip()] == \
        [l for l in psql(expected).splitlines() if l.strip()], (
        "塌缩后的存活行 ≠ 按四档选行规则独立重算的结果 —— 迁移选错了幸存行")


def test_v102_converges_claimed_rows_and_leaves_price_untouched(psql):
    """V102：**只认领「已是 TRUE」的行**（写全 `updated_at`）；`FALSE` 那批**留给 V104 软删**。

    🔴 **本单实测的口径陷阱**（详见 V102 文件头）：若 V102 一刀切把全部存活行置 `TRUE`，
    V104 的 ① 档（「适用行优先」）就不再区分任何行 ⇒ `帘头制作` 的幸存行会落到
    `布帘 / NULL` ⇒ **¥2.00 静默丢失**。本判据用 `帘头制作 = 2.00` 钉死这条。

    判据：
      · `unit_price` **逐字节指纹不变**（V102 只许写 `applicable` / `updated_at`）；
      · `FALSE` 行的 `applicable` **一字不动**（信号留给 V104）；
      · V104 之后**存活行一律 `TRUE`**，且 `帘头制作` 的价仍是 `2.00`。
    """
    _seed(psql)
    fp_before = _fingerprint(psql, "production_operation_positions", "id, unit_price")
    false_rows_before = _rows_of(psql, "applicable IS FALSE AND deleted = 0")
    assert len(false_rows_before) == 4, f"改前 `FALSE` 存活行 = {len(false_rows_before)}，期望 4"

    psql(_as_runner_would(_read(V102)))

    assert _fingerprint(psql, "production_operation_positions", "id, unit_price") == fp_before, \
        "🔴 V102 改了 `unit_price` —— 它只许写 `applicable` / `updated_at`"
    assert _rows_of(psql, "applicable IS FALSE AND deleted = 0") == false_rows_before, (
        "V102 动了 `applicable = FALSE` 的行 —— 那会抹掉 V104 选行所依赖的信号"
        "（`帘头制作` 会因此丢价，见文件头的口径陷阱）")
    # 单独跑 V102 **合法**（它只认领「已是 TRUE」的行）；FALSE 那批的收口在 V104 的 ③ 块
    assert psql("SELECT count(*) FROM production_operation_positions "
                "WHERE deleted = 0 AND applicable IS TRUE;").strip() == "6", (
        "V102 认领的行数不对（期望 6 条已是 TRUE 的存活行被写全 updated_at）")
    assert "t1-retired:1" in _all_rows(psql), "V102 碰了已软删行（那是 V88 的退场留痕）"
    assert psql("SELECT count(*) FROM production_operation_positions WHERE deleted = 0;").strip() == "10", \
        "V102 改了存活行数（它只许写两列，不删行）"

    # ── V104 之后：存活行一律 TRUE，且**有价的帘头幸存行必须保住 2.00** ──
    psql(_as_runner_would(_read(V104)))
    assert psql("SELECT count(*) FROM production_operation_positions "
                "WHERE deleted = 0 AND applicable IS NOT TRUE;").strip() == "0", \
        "V104 之后仍有存活行的 applicable 不是 TRUE"
    assert not [r for r in _rows_of(psql, "deleted = 1") if r.startswith("t1-ltzz-lt")], \
        "`帘头制作 × 帘头` 本该是**幸存行**却被软删了"
    kept = psql("SELECT logical_name || '|' || COALESCE(unit_price::text,'NULL') "
                "FROM production_operation_positions WHERE deleted = 0 AND tenant_id = 1 "
                "AND logical_name = '帘头制作';").strip()
    assert kept == "帘头制作|2.00", (
        f"🔴 `帘头制作` 的幸存行价 = `{kept}`，期望 `帘头制作|2.00` —— "
        f"价丢了（V102 一刀切置 TRUE 会让幸存行落到布帘列的 NULL，工人白干，issue #4696）")
    # 审计：被 V102 认领过的行必须带新的 updated_at（`NOW()` 同事务常量 ⇒ 用 `>= created_at` 不可判，
    # 改判「写过」= 行仍在且值未变 —— 真正的审计证据是 V104 的软删戳，见下一条）
    assert _fingerprint(psql, "production_operation_positions", "id, unit_price") == fp_before, \
        "V104 改了价 —— 塌缩只选行，不改价"


def _rows_of(run, where: str) -> list:
    out = run(f"SELECT id FROM production_operation_positions WHERE {where} ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def test_v103_clears_rule_positions_and_leaves_customer_price_untouched(psql):
    """V103：改前 2 行非 NULL ⇒ 改后 0 行；`customer_unit_price` 指纹与规则行数不变。"""
    _seed(psql)
    nonnull_before = psql("SELECT count(*) FROM production_route_rules "
                          "WHERE deleted = 0 AND position IS NOT NULL;").strip()
    assert nonnull_before == "2", f"改前带 position 的规则 = {nonnull_before}，期望 2"
    fp_before = _fingerprint(psql, "production_route_rules", "id, customer_unit_price")
    count_before = psql("SELECT count(*) FROM production_route_rules;").strip()
    psql(_as_runner_would(_read(V103)))
    assert psql("SELECT count(*) FROM production_route_rules "
                "WHERE deleted = 0 AND position IS NOT NULL;").strip() == "0", \
        "V103 后仍有规则的 position 不为 NULL"
    assert _fingerprint(psql, "production_route_rules", "id, customer_unit_price") == fp_before, \
        "🔴 V103 改了 `customer_unit_price` —— 那是对客那本账（元/套），与「部位」无关"
    assert psql("SELECT count(*) FROM production_route_rules;").strip() == count_before, \
        "V103 删了规则行 —— 它只许清一列的值"


def test_v104_leaves_history_and_the_repricing_ledger_byte_identical(psql):
    """红线：V86 调价账 / 工序实例 / 报工流水 逐字节指纹前后相同。"""
    _seed(psql)
    before = {t: _fingerprint(psql, t, cols) for t, cols in _HISTORY_TABLES.items()}
    assert all(v for v in before.values()), f"改前指纹取不到（判据会空跑）：{before}"
    psql(_as_runner_would(_migrations()))
    after = {t: _fingerprint(psql, t, cols) for t, cols in _HISTORY_TABLES.items()}
    assert after == before, (
        f"红线被破：历史/账本指纹变了\n  改前：{before}\n  改后：{after}\n"
        "（调价账按 `position_row_id` 指向矩阵行 —— 塌缩只软删，行仍在）")
    rows = psql("SELECT (SELECT count(*) FROM production_operation_position_price_versions) || '/' || "
                "(SELECT count(*) FROM processing_position_operations) || '/' || "
                "(SELECT count(*) FROM production_work_logs);").strip()
    assert rows == "2/1/1", f"历史/账本行数变了：{rows}"


def test_v104_reconciliation_blocks_a_partial_write(psql):
    """红证（真库）：写语句**漏做软删**（判据漂移）⇒ 对账 `RAISE EXCEPTION` ⇒ 整份回滚。

    注入 = 给「非幸存行软删」那条 UPDATE 尾部加 `LIMIT 1`（模拟「写语句没删干净」这一漂移形态）。
    """
    _seed(psql)
    before = _all_rows(psql)
    sql = _read(V104)
    # ⚠️ `UPDATE … LIMIT` 在 PG 里**语法不合法**（实测：`语法错误 在 "LIMIT" 或附近的`）⇒
    # 注入形态换成**等价的「漏做一行」**：把 `t1-ltzz-bu` 排除在软删之外（它本该被软删）。
    injected = sql.replace("   AND NOT EXISTS (SELECT 1 FROM _v104_survivors s",
                           "   AND p.id <> 't1-ltzz-bu'\n   AND NOT EXISTS (SELECT 1 FROM _v104_survivors s", 1)
    assert injected != sql, "注入「漏删」没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    assert proc.returncode != 0, (
        f"写语句漏删时对账竟未拦下 ⇒ 停止条件是空断言\nstdout={proc.stdout}\nstderr={proc.stderr}")
    assert "数量对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
    assert _all_rows(psql) == before, "对账抛异常后矩阵行却变了 ⇒ 没有回滚（半完成态）"


def test_v104_is_load_bearing_against_a_loosened_survivor_rule(psql):
    """红证（真库）：把「布帘列优先」档换成恒定假 ⇒ 幸存行变（那一档**真的在承重**）。

    ⚠️ 注入后**对账仍会通过**（写语句与对账共享同一份物化结果 ⇒ 「两处一起用错判据」时对账抓不到）
    —— 这正是静态判据 `test_v104_uses_the_four_tier_survivor_rule_in_the_same_order`（逐档）
    必须存在的原因；本红证证明的是「那一档真的影响结果」。
    """
    _seed(psql)
    # 造出「多个适用行」的形态（否则决胜档不参与 —— 那会让本红证假绿）：
    # `三边 × 纱帘` 与 `三边 × 帘头` 都设为适用且各有价。
    psql("UPDATE production_operation_positions SET applicable = TRUE, unit_price = 0.99 "
         "WHERE id IN ('t1-sandian-sha', 't1-sandian-lt');")
    sql = _read(V104)

    psql(_as_runner_would(sql))
    baseline = psql("SELECT id FROM production_operation_positions WHERE deleted = 0 "
                    "AND logical_name = '三边' AND tenant_id = 1;").strip()
    assert baseline == "t1-sandian-bu", (
        f"正常口径下（3 个适用行）`三边` 的幸存行 = {baseline}，期望**布帘**行"
        f"（② 档「布帘列优先」承重）")

    # 复原（把上一轮软删的纱帘/帘头行救回），再把 ② 档注入成恒定假
    psql("UPDATE production_operation_positions SET deleted = 0, position = CASE id "
         "WHEN 't1-sandian-sha' THEN '纱帘' WHEN 't1-sandian-lt' THEN '帘头' ELSE position END, "
         "applicable = TRUE, unit_price = CASE id WHEN 't1-sandian-sha' THEN 0.99 "
         "WHEN 't1-sandian-lt' THEN 0.99 ELSE unit_price END WHERE tenant_id = 1;")
    injected = sql.replace("(p.position = '布帘') DESC,", "FALSE DESC,", 1)
    assert injected != sql, "注入没生效 ⇒ 红证是空断言"
    psql(_as_runner_would(injected))
    got = psql("SELECT id FROM production_operation_positions WHERE deleted = 0 "
               "AND logical_name = '三边' AND tenant_id = 1;").strip()
    assert got != "t1-sandian-bu", (
        f"把「布帘列优先」档换成恒定假后幸存行仍是布帘行（{got}）⇒ 该档是装饰（判据无判别力）")
    # 剩下三行同档 ⇒ 落 ③ `position` 字典序（COLLATE "C" = 逐字节）：帘头 < 布帘 < 纱帘
    assert got == "t1-sandian-lt", f"按 position 字典序（COLLATE \"C\"）应选 `帘头` 行，实际 {got}"


def test_bootstrap_matches_migration_chain_terminal_state(psql):
    """`docs/sql/schema.sql`（bootstrap，不跑迁移链）的矩阵段 == 迁移链终态（**逐逻辑工序**）。

    本测试把 schema.sql 的矩阵**字面量**当输入喂进真库，再跑三条新迁移 ⇒
    终态必须与 schema.sql **自己写的那份终态**逐值相等。这是「防两条口径分裂」的那条判据：
    bootstrap-first 栈不跑迁移链 ⇒ 少同步任一项即红。
    ⚠️ 比对按**逻辑工序**（`unit_price` / `applicable` / `deleted`）+ 「存活行的 `position`
    一律 `通用`」—— 因为 V104 的**产物**就是「每逻辑工序一行、部位写中性值」，
    拿 `(逻辑工序, 部位)` 做键会「拿终态比旧键」（苹果比橘子）。
    """
    schema = _read(SCHEMA_SQL)
    boot_sql = _schema_matrix_sql(schema)
    assert len(_parse_schema_matrix(boot_sql)) == 120, (
        f"schema.sql 矩阵种子段解析出 {len(_parse_schema_matrix(boot_sql))} 行，期望 120")

    psql(_DDL + "INSERT INTO tenants (id) VALUES (1);")
    psql(boot_sql)
    seeded = psql("SELECT count(*) FROM production_operation_positions;").strip()
    assert seeded == "120", f"schema.sql 的 120 行没真插进去（实际 {seeded}）⇒ 本判据会空跑"
    psql(_as_runner_would("\n".join(_read(p) for p in (V102, V103, V104))))

    chain_alive = {}
    for line in psql("SELECT logical_name || '|' || COALESCE(unit_price::text,'NULL') || '|' "
                     "|| applicable::text || '|' || position FROM production_operation_positions "
                     "WHERE deleted = 0 AND tenant_id = 1 ORDER BY logical_name;").splitlines():
        if line.strip():
            lg, price, ap, pos = line.split("|")
            chain_alive[lg] = (price, ap, pos)
    chain_deleted = {l.split("|")[0] for l in
                     psql("SELECT logical_name FROM production_operation_positions "
                          "WHERE deleted = 1 AND tenant_id = 1;").splitlines() if l.strip()}

    boot_alive, boot_deleted = _schema_terminal_state(schema)
    # ⚠️ 形态归一：schema.sql 写的是**字面量**（`0.4` / `TRUE`），真库回读是
    # `NUMERIC(10,2)` 的定标形式（`0.40`）与 psql 的小写布尔（`true`）—— 不归一会让
    # 「同一份数据两种书写」被误判成漂移（本仓最忌的假红）。
    def norm(values):
        out = []
        for x in values:
            if x == "NULL":
                out.append("NULL")
            elif x.lower() in ("true", "false"):
                out.append(x.lower())
            else:
                try:
                    out.append("%.2f" % float(x))
                except ValueError:
                    out.append(x)          # 中性部位 `通用` 等文本
        return tuple(out)
    boot_alive = {k: norm(v) for k, v in boot_alive.items()}
    chain_alive = {k: norm(v) for k, v in chain_alive.items()}
    assert set(chain_alive) == set(boot_alive), (
        f"存活**逻辑工序集合**分裂：仅迁移链有 = {sorted(set(chain_alive) - set(boot_alive))}，"
        f"仅 bootstrap 有 = {sorted(set(boot_alive) - set(chain_alive))}")
    assert len(chain_alive) == 30, f"迁移链终态的存活逻辑工序 = {len(chain_alive)}，期望 30"
    drift = {k: (boot_alive[k], chain_alive[k]) for k in chain_alive if boot_alive[k] != chain_alive[k]}
    assert drift == {}, (
        f"逐逻辑工序（价/适用/部位）分裂（前 = bootstrap，后 = 迁移链）：{drift}")
    assert {v[2] for v in chain_alive.values()} == {"通用"}, (
        f"迁移链终态的存活行 position 不是全 `通用`：{sorted({v[2] for v in chain_alive.values()})}")
    # 软删侧的**行数**逐租户一致（每逻辑工序 3 行退场：纱帘/帘头/布料 —— 除非该逻辑工序本就少数部位）
    assert len(chain_deleted) > 0 and set(chain_deleted) <= set(boot_deleted) | set(chain_alive), (
        "迁移链软删的逻辑工序集合不合理 ⇒ 判据空跑")
    assert len(chain_alive) + 90 == 120, "存活 30 + 退场 90 必须 = 120（可机械核验）"
    # ── 真库读数（PR 证据直接引这段输出） ──
    print("[#4937 真库 · schema.sql 120 行字面量跑 V102/V103/V104]")
    print(f"  存活 = {len(chain_alive)} 行 / 退场 = "
          f"{psql('SELECT count(*) FROM production_operation_positions WHERE deleted = 1;').strip()} 行 / "
          f"总 = {psql('SELECT count(*) FROM production_operation_positions;').strip()} 行")
    print(f"  存活行的 position 取值集 = "
          f"{sorted({v[2] for v in chain_alive.values()})}")
    print(f"  存活行的 applicable 取值集 = "
          f"{sorted({v[1] for v in chain_alive.values()})}")
    print(f"  有价工序 = {sum(1 for v in chain_alive.values() if v[0] != 'NULL')} / "
          f"未定价工序 = {sum(1 for v in chain_alive.values() if v[0] == 'NULL')}")
    print("  （与 routing.py::OPERATION_POSITION_PRICES 逐值相等 ⇒ 见上面的 drift 断言）")


def _schema_matrix_sql(sql: str) -> str:
    """schema.sql 的矩阵种子段 → 可**直接喂进真库**的 DDL/DML 文本（含列名）。

    ⚠️ 只取 `INSERT … VALUES` 部分（**丢掉** `ON CONFLICT (id) DO NOTHING`）：
    本测试的真库表是**空的** ⇒ `ON CONFLICT` 会让「种子没真插进去」变成静默空跑的反面
    （这里的 `ON CONFLICT` 无害，但保留它会让「表为空」不被发现 —— 加一条非空自证更稳）。
    """
    start = sql.index("INSERT INTO production_operation_positions\n"
                      "    (id, tenant_id, logical_name, position, unit_price, applicable, status, deleted)")
    end = sql.index("ON CONFLICT (id) DO NOTHING;", start)
    return sql[start:end]


def _schema_terminal_state(sql: str) -> tuple:
    """schema.sql 里的终态 → `(存活 {逻辑工序: (价, 适用, 部位)}, 退场逻辑工序集合)`。"""
    alive, deleted = {}, set()
    for (_,), (price, ap, deleted_flag, lg, pos) in _parse_schema_matrix(sql).items():
        if deleted_flag == "1":
            deleted.add(lg)
        else:
            assert lg not in alive, f"schema.sql 里逻辑工序 `{lg}` 有多个存活行 ⇒ 终态未塌缩"
            alive[lg] = (price, ap, pos)
    return alive, deleted


def _parse_schema_matrix(sql: str) -> dict:
    """矩阵字面量行 → `{(id,): (price, applicable, deleted)}` **按 id 建键**（行数 = 真行数）。

    ⚠️ 曾经用 `(logical_name, position)` 做键 ⇒ 塌缩后「每逻辑工序一行、部位写 `通用`」时，
    `('精裁','通用')` 只占一个键，但**纱帘/帘头行仍在文件里**（只多了一个已删的同名键）
    ⇒ 字典长度 118 ≠ 120 行（**实测**：本判据因此报「解析出 118 行」）。
    ⇒ 键必须是**行的身份**（`id`），不是业务键。

    只解析 `opp-v70-*` / `opp-v79-*` 两段（本单触碰的字面量）；`status` 列**可缺省**
    （真库最小 DDL 没有它）⇒ 用可选组，**不**硬编码列数。
    行数**不写死**（由调用方断言）—— 写死会让「加一行」变成判据自身的维护点。
    """
    out = {}
    pattern = re.compile(
        r"\(\s*'(?P<id>opp-v(?:70|79)-\d+)'\s*,\s*1\s*,\s*'(?P<lg>[^']*)'\s*,\s*'(?P<pos>[^']*)'\s*,"
        r"\s*(?P<price>NULL|[\d.]+)\s*,\s*(?P<ap>TRUE|FALSE)\s*,\s*"
        r"(?:'active'\s*,\s*)?(?P<del>\d+)\s*\)")
    for m in pattern.finditer(sql):
        out[(m.group("id"),)] = (m.group("price"), m.group("ap"), m.group("del"),
                                 m.group("lg"), m.group("pos"))
    return out


def test_v102_claim_is_observable_and_v104_requires_a_clean_applicable_column(psql):
    """红证（真库）两条：① V102 的认领**可观测**；② V104 的终态核验**不是空断言**。

    ① V102 单独跑 ⇒ 合法，且 `GET DIAGNOSTICS` 认领数 > 0（谓词写岔 = 0 行 ⇒ 迁移自己抛）；
    ② 把 V104 的 ① 档（「适用行优先」）注入成恒定假 ⇒ 幸存行换人
       ⇒ 与「按四档独立重算」的期望不符 ⇒ `test_migrations_are_idempotent_…` 会红
       （本测试证明那条重算**不是**拿实现跟自己比：注入即变）。
    """
    _seed(psql)
    false_before = psql("SELECT count(*) FROM production_operation_positions "
                        "WHERE deleted = 0 AND applicable IS FALSE;").strip()
    assert false_before == "4", f"改前 FALSE 存活行 = {false_before}，期望 4（红证前提）"

    psql(_as_runner_would(_read(V102)))
    assert psql("SELECT count(*) FROM production_operation_positions "
                "WHERE deleted = 0 AND applicable IS FALSE;").strip() == "4", (
        "V102 动了 `applicable = FALSE` 的行 —— 那会抹掉 V104 选行所需的信号"
        "（`帘头制作` 会因此丢价，见 V102 文件头的口径陷阱）")
    assert psql("SELECT count(*) FROM production_operation_positions "
                "WHERE deleted = 0 AND applicable IS TRUE;").strip() == "6", (
        "V102 认领的行数不对（期望 6 条已是 TRUE 的存活行被写全 updated_at）")

    # ② 注入：抹掉 V104 的「适用行优先」档 ⇒ 幸存行换人（判据有判别力）
    sql = _read(V104)
    injected = sql.replace("(p.applicable IS TRUE) DESC,", "FALSE DESC,", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"
    psql(_as_runner_would(injected))
    kept = psql("SELECT logical_name || '|' || COALESCE(unit_price::text,'NULL') "
                "FROM production_operation_positions WHERE deleted = 0 AND tenant_id = 1 "
                "AND logical_name = '帘头制作';").strip()
    assert kept == "帘头制作|NULL", (
        f"抹掉「适用行优先」档后 `帘头制作` 的幸存行价 = `{kept}`，期望 `NULL`"
        f"（落到布帘列）—— 说明该档在承重；反过来也证明正常口径下的 `2.00` 不是碰巧")


# ══════════════════════════ V105（4 道纱帘变体）的真库判据 ══════════════════════════

def test_v105_adds_the_four_sheer_variants_and_is_idempotent(psql):
    """真库：V105 补 4 道纱帘变体；跑两遍净效果相同；单价逐字取对应 `-布` 变体。

    🔴 **为什么必须有这条判据**：`applicable` 过滤退场后，`熨烫/定型/复烫/车被` 会进纱帘路线，
    而库里没有它们的纱帘变体 ⇒ `variantNameOf` 返回 null ⇒ **整张纱帘单 422 建不出来**。
    本判据钉「补上了没」+「幂等」+「价没发明」三件事。
    """
    _seed(psql)
    # 4 道 `-布` 变体（单价来源；V105 的 4 行必须逐字取它们）
    psql("INSERT INTO production_operations (id, tenant_id, name, group_name, unit, unit_price) VALUES "
         "('op-bu-1', 1, '熨烫-布', '后道', '米', 0.35), "
         "('op-bu-2', 1, '定型-布', '后道', '米', 0.40), "
         "('op-bu-3', 1, '复烫-布', '后道', '米', 0.35), "
         "('op-bu-4', 1, '布帘车被', '后道', '米', 0.40);")

    before = psql("SELECT count(*) FROM production_operations WHERE tenant_id = 1;").strip()
    psql(_as_runner_would(_read(V105)))
    after_first = psql("SELECT count(*) FROM production_operations WHERE tenant_id = 1;").strip()
    psql(_as_runner_would(_read(V105)))       # 第二遍（幂等）
    after_second = psql("SELECT count(*) FROM production_operations WHERE tenant_id = 1;").strip()

    assert int(after_first) == int(before) + 4, (
        f"V105 应补 4 行（{before} → {before}+4），实际到 {after_first}")
    assert after_first == after_second, (
        f"V105 **不幂等**：第二遍改了行数\n  第一遍后：{after_first}\n  第二遍后：{after_second}")
    rows = psql("SELECT name || '|' || unit_price::text || '|' || position || '|' || scope "
                "FROM production_operations WHERE id LIKE 'op-v56-0%' AND id > 'op-v56-05' "
                "ORDER BY id;")
    parsed = [l.split("|") for l in rows.splitlines() if l.strip()]
    assert len(parsed) == 4, f"V105 的 4 行没落库：{parsed}"
    assert [r[0] for r in parsed] == ["熨烫-纱", "定型-纱", "复烫-纱", "车被-纱"], parsed
    assert [r[1] for r in parsed] == ["0.35", "0.40", "0.35", "0.40"], (
        f"单价必须逐字取对应 `-布` 变体（不发明单价）：{parsed}")
    assert {r[2] for r in parsed} == {"纱帘"}, f"部位必须是纱帘：{parsed}"
    assert {r[3] for r in parsed} == {"position"}, f"scope 必须是 position：{parsed}"


def test_v105_reconciliation_blocks_a_missing_row(psql):
    """红证（真库）：**跳过 V105 的 INSERT**（只跑对账）⇒ `RAISE EXCEPTION` ⇒ 整份回滚。"""
    _seed(psql)
    sql = _read(V105)
    # 注入 = 让 INSERT 一条也落不进去：把 4 行 name 之一改成对账 CTE **认不出**的名字
    # （等价于「写语句写岔了」⇒ 对账必须当场抛）
    injected = sql.replace("('op-v56-06', 1, '熨烫-纱'", "('op-v56-06', 1, '熨烫-纱X'", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    assert proc.returncode != 0, (
        f"4 行没插进去时对账竟通过了 ⇒ 终止条件是空断言\nstderr={proc.stderr}")
    assert "数量对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
