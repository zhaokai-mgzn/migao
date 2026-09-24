# case_ids: PG-018, PG-020, PG-035
"""必完（`is_must_finish`）概念退场迁移 **V107** 的承重判据 + 真库两遍幂等 + bootstrap 终态镜像。

（issue #4961；用户裁定 2026-09-21「**完工 = 全部工序全绿**」⇒ 「必完工序」这一档整体退场。）

## 本文件钉的事

| 面 | 判据 |
|---|---|
| 形态（静态） | 显式 `BEGIN;/COMMIT;`；只写 `is_must_finish` / `updated_at` 两列；幂等谓词逐字 = `WHERE deleted = 0 AND is_must_finish IS DISTINCT FROM FALSE`；**不 DROP 列** + `COMMENT ON COLUMN` 改成历史载体；不碰三张快照表；文件里不出现种子解析关键字（`INSERT INTO production_operations` / `VALUES` / CTE） |
| 真库（临时 PG） | 两遍真跑：**第二遍谓词匹配 0 行**、净效果相同；存活行（含非 1 号租户）全部 `FALSE`；**已软删的 TRUE 行不复活也不动**；列仍在（`information_schema.columns`）；三张快照表指纹逐字节不变 |
| 判别力（注入红证） | ① 写语句漏改一行 ⇒ 终态对账 `RAISE EXCEPTION` + 整份回滚；② 注入 `DROP COLUMN` ⇒ 红线护栏当场抛；③ 谓词丢掉 `deleted = 0` ⇒ 软删行被改（证明「软删行不动」那条断言**有判别力**，不是恒真） |
| bootstrap 镜像 | `backend/admin-api/src/main/resources/db/init/schema.sql`（bootstrap 路径，**不跑迁移链**）的工序库种子 `is_must_finish` 已全 `FALSE`；迁移链侧「冻结 V54 种子里的 `TRUE`」+ V107 ⇒ 全 `FALSE`；两侧终态取值集合相等 |

## 为什么必须真跑两遍

`MigrationRunner` 要求**所有**迁移可重复执行，而「幂等」只有真库能判：
`IS DISTINCT FROM` 与 `NULL` 的交互、`DO $$ … $$` 里 `RAISE EXCEPTION` 的回滚半径、
单文件多语句在同一事务里的原子性 —— 三者都是**运行期**语义。

⚠️ **本迁移的幂等形态与前几条新迁移不同**：V102/V104 靠「谓词恒匹配同一批行（重写 `updated_at`）」
保持幂等；V107 的谓词是 `IS DISTINCT FROM FALSE` ⇒ **第二遍天然匹配 0 行**。
所以本文件**不能**套用「认领 0 行 ⇒ 抛异常」的空跑自证（那会让第二次执行必失败），
空跑自证改由**终态对账**承担（见 V107 文末的 `DO` 块）。

## 真库判据（临时 PG 集群；缺 PG 的处置收口在 `pg_cluster.py`：CI 判**红** / 本机显式 skip，issue #5203）

照 `tests/unit_ci_workflows/test_deposition_total_migration.py` 的范式：`initdb` / `pg_ctl` / `psql`
起**临时集群**真跑 —— 静态文本判据不够（V83 的教训：文本守卫全绿而真库整份回滚）。
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration-archive"

# ── 迁移文件的**两个**载体目录（issue #5243）—— 单一事实源 = `_migration_paths.py`
# 共享件（issue #5243）：`tests/` 上 sys.path 才能按**包名**导入；直接以脚本运行时
#（如 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`）
# 包不在路径上，故显式补一次 —— 两种入口都要能跑。
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
from unit_ci_workflows._migration_paths import LIVE_DIR as _LIVE_MIGRATION_DIR, migration_files as _migration_files
from unit_ci_workflows import pg_cluster  # noqa: E402  （起/停集群的唯一收口，issue #5263）



V107 = MIGRATION_DIR / "V107__retire_must_finish_flag.sql"
V54 = MIGRATION_DIR / "V54__seed_production_operations.sql"
SCHEMA_SQL = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

TABLE = "production_operations"
COLUMN = "is_must_finish"
PREDICATE = "deleted = 0"

#: 三张**快照/历史**表（红线：V107 一字不动它们的列与行）
SNAPSHOT_TABLES = {
    "processing_position_operations": "id, tenant_id, operation_name, unit_price, factor, "
                                      "is_must_finish, deleted",
    "production_work_logs": "id, tenant_id, operation_name, unit_price, factor, deleted",
    "processing_orders": "id, tenant_id, items_snapshot::text, deleted",
}

#: 种子行形态（V54 与 `backend/admin-api/src/main/resources/db/init/schema.sql` 的工序库种子同形；后者多一列 `deleted`）
_ROW_RE = re.compile(
    r"\(\s*'(?P<id>op-[^']+)'\s*,\s*(?P<tenant>\d+)\s*,\s*'(?P<name>[^']*)'\s*,\s*"
    r"'(?P<group>[^']*)'\s*,\s*(?P<position>NULL|'[^']*')\s*,\s*'(?P<unit>[^']*)'\s*,\s*"
    r"(?P<price>[\d.]+)\s*,\s*(?P<must>TRUE|FALSE)\s*,\s*(?P<start>TRUE|FALSE)\s*,\s*"
    r"(?P<sort>\d+)\s*,\s*'(?P<status>[^']*)'(?:\s*,\s*(?P<deleted>\d+))?\s*\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释（`--` 行注释与 `/* */` 块注释）→ 空，供**写语句**判据用。

    ⚠️ 必须去注释：本仓迁移把「回滚 SQL」写在注释里（V107 的回滚段里就有一条 `UPDATE`），
    不去注释会把注释里的 `UPDATE` 当成真写语句（#4595 的同族教训）。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


def _seed_rows(sql: str) -> list:
    """种子字面量行 → [{id, name, must, deleted, ...}]（锚定 `op-` 前缀，避免误吃别处的括号）。"""
    return [m.groupdict() for m in _ROW_RE.finditer(sql)]


# ══════════════════════════ ① 存在性 / 账本 / 形态 ══════════════════════════

def test_v107_exists_and_is_the_highest_version():
    assert V107.exists(), f"缺少迁移文件：{V107.name}"
    versions = [int(re.match(r"^V(\d+)__", p.name).group(1))
                for p in _migration_files("V*.sql") if re.match(r"^V(\d+)__", p.name)]
    assert versions.count(107) == 1, "V107 版本号重复"
    assert max(versions) >= 107, f"V107 不是最高版本号（当前最大 V{max(versions)}）"


def test_v107_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏（issue #4235）：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert V107.name in ledger, (
        f"`{V107.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_v107_is_explicitly_transactional():
    """`psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 会留半完成态（V97/V102 的实测口径）。"""
    body = _read(V107)
    assert re.search(r"^BEGIN;", body, re.M), "V107 缺显式 `BEGIN;`"
    assert re.search(r"^COMMIT;", body, re.M), "V107 缺显式 `COMMIT;`"
    assert "RAISE EXCEPTION" in body, "V107 缺终态对账（`RAISE EXCEPTION`）"


def test_v107_writes_exactly_two_columns_with_the_idempotent_predicate():
    body = _strip_comments(_read(V107))
    updates = [u for u in re.findall(r"UPDATE production_operations[\s\S]*?;", body) if "SET" in u]
    assert len(updates) == 1, f"V107 应恰好一条 UPDATE（实际 {len(updates)}）"
    stmt = updates[0]
    assert re.search(r"SET\s+is_must_finish\s*=\s*FALSE\s*,\s*updated_at\s*=\s*NOW\(\)", stmt), (
        f"V107 的 SET 子句不是「显式写 is_must_finish + updated_at」：{stmt}")
    assert "WHERE deleted = 0" in stmt, "V107 的谓词丢了 `deleted = 0`（软删行是留痕，不得改）"
    assert "is_must_finish IS DISTINCT FROM FALSE" in stmt, (
        "V107 的幂等闸必须是 `is_must_finish IS DISTINCT FROM FALSE` —— 第二遍必须匹配 0 行")
    assert "<> FALSE" not in stmt and "!= FALSE" not in stmt, (
        "V107 用了 `<> FALSE`：它对 `NULL` 求值为 `NULL`（既不真也不假）⇒ 该行永远改不到且不留痕")
    # 单位列：不得顺手写别的业务列
    for forbidden in ("unit_price", "is_start_marker", "status", "scope", "sort_order", "name"):
        assert forbidden not in stmt, f"V107 的 UPDATE 碰了 `{forbidden}` —— 它只许写两列"


def test_v107_never_drops_the_column_and_relabels_it_as_a_historical_carrier():
    body = _read(V107)
    # ⚠️ 列注释的判据必须落在**去注释后**的文本上：文件头的「回滚 SQL」段里**故意**留着
    #    还原用的**旧注释文案**，拿全文找 `COMMENT ON COLUMN` 会先命中那一段（假绿/假红都会）。
    stripped = _strip_comments(body).upper()
    assert "DROP COLUMN" not in stripped, (
        "V107 里出现 `DROP COLUMN` —— 列是历史载体，且读面冻结键集与 `backend/admin-api/src/main/resources/db/init/schema.sql` 的 "
        "bootstrap 终态都仍带它（删列 = bootstrap 与迁移链两条路径的 schema 分叉）")
    executable = _strip_comments(body)
    assert re.search(r"COMMENT ON COLUMN production_operations\.is_must_finish IS", executable), (
        "V107 没有把列注释改成「历史载体」（概念退场必须在**库里**可见，而不只在代码注释里）")
    at = executable.index("COMMENT ON COLUMN production_operations.is_must_finish IS")
    comment = executable[at:executable.index(";", at)]
    assert "历史载体" in comment, f"列注释里没有「历史载体」这一档说法：{comment}"


def test_v107_does_not_touch_the_three_snapshot_tables():
    """红线：历史工资与历史实例不可回改（快照表在 V107 里**只能出现在注释**里）。"""
    body = _strip_comments(_read(V107))
    for table in SNAPSHOT_TABLES:
        assert table not in body, (
            f"V107 的可执行语句碰了快照表 `{table}` —— 历史工资/历史实例只能留痕，不可回改")


def test_v107_documents_rollback_loss_and_why_no_tenant_loop():
    """迁移文件的硬要求：回滚 SQL + 不可复原项 + 「为什么不按租户循环」的显式说明。"""
    body = _read(V107)
    assert "回滚 SQL" in body, "V107 缺「回滚 SQL」段（本仓迁移的硬要求）"
    assert "不可复原" in body, "V107 没写「不可复原项」（回滚是有损的，必须照实登记）"
    assert "全局目录属性" in body, (
        "V107 没写「该列是全局目录属性」这一条 —— issue #4961 正文写的是「按租户循环」，"
        "文件里必须说明**为什么不循环也满足其意图**（覆盖效果 + 覆盖面由对账块机械核验）")
    assert "无需按租户循环" in body or "不按租户循环" in body, "V107 缺「为什么不按租户循环」的正面结论"
    assert f"'{COLUMN}'" in body or COLUMN in body


def test_v107_does_not_confuse_the_seed_parsers():
    """V107 **不得**含种子解析关键字（本仓两个按内容发现种子的守卫会被它骗到）。

    · `tests/unit_ci_workflows/test_production_catalog_seed.py` 的发现正则 = 「含
      `INSERT INTO production_operations` 且 `VALUES` 在 `FROM` 之前」⇒ 一旦命中，它会把本文件
      当**种子源**去解析行（解析不出行 ⇒ 该守卫报红，而红的原因与被测行为无关）；
    · 同文件另有「每个种子源都要有贡献」的判据 ⇒ 同上。
    """
    body = _strip_comments(_read(V107))
    assert "INSERT INTO production_operations" not in body, (
        "V107 的可执行语句里有 `INSERT INTO production_operations` ⇒ 会被种子发现正则当种子源")
    assert not re.search(r"\bVALUES\b", body, re.I), "V107 的可执行语句里出现了行值构造关键字"
    assert not re.search(r"\bWITH\s+\w+\s+AS\s*\(", body, re.I), "V107 用了 CTE（本仓迁移不使用）"


# ══════════════════════════ ② 真库判据（临时 PG 集群） ══════════════════════════


#: 与 V49 / `backend/admin-api/src/main/resources/db/init/schema.sql` 同形的**最小** DDL（本单触碰的表 + 三张快照表）。
#: ⚠️ `production_operations.is_must_finish` 是 `NOT NULL DEFAULT FALSE`（V49 的原始定义）——
#: 本文件**照抄**该约束（不为了造 `NULL` 行而放宽）：V107 谓词里的 `IS DISTINCT FROM` 对
#: `NULL` 的覆盖是**防御性**的（真库下不可达），它防的是「将来某迁移把该列放宽成可空」。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL, group_name VARCHAR(16) NOT NULL DEFAULT '其他',
    position VARCHAR(16), unit VARCHAR(16) NOT NULL DEFAULT '米',
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,
    is_must_finish BOOLEAN NOT NULL DEFAULT FALSE,
    is_start_marker BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INT NOT NULL DEFAULT 0, scope VARCHAR(16) DEFAULT 'position',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_operations_tenant_name
    ON production_operations (tenant_id, name) WHERE deleted = 0;
CREATE TABLE processing_position_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), is_must_finish BOOLEAN DEFAULT FALSE,
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_work_logs (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE processing_orders (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, items_snapshot JSONB,
    deleted INTEGER NOT NULL DEFAULT 0);
"""

#: 真库形态的种子：
#:   · **1 号租户**：一条存活 `FALSE`（不该被写）+ 一条存活 `TRUE`（必须被收敛）；
#:   · **2 号租户**：一条存活 `TRUE`（证明「不按租户循环」也覆盖**非 1 号**租户）；
#:   · **已软删**两行（`TRUE` / `FALSE` 各一）：V107 一行都不许动（不复活、不翻值）；
#:   · 三张快照表各一行：指纹前后必须逐字节相同。
_SEED = """
INSERT INTO tenants (id) VALUES (1), (2);
INSERT INTO production_operations
    (id, tenant_id, name, unit_price, is_must_finish, deleted) VALUES
    ('t1-live-false',   1, '精裁-布',   0.40, FALSE, 0),
    ('t1-live-true',    1, '外帘装袋',   1.00, TRUE,  0),
    ('t2-live-true',    2, '韩褶-布',   0.40, TRUE,  0),
    ('t1-deleted-true', 1, '配料-旧',   0.50, TRUE,  1),
    ('t1-deleted-false',1, '配料-更旧',  0.50, FALSE, 1);
INSERT INTO processing_position_operations
    (id, tenant_id, operation_name, unit_price, factor, is_must_finish, deleted) VALUES
    ('inst-1', 1, '外帘装袋', 1.00, 1.000, TRUE, 0);
INSERT INTO production_work_logs (id, tenant_id, operation_name, unit_price, factor, deleted) VALUES
    ('wl-1', 1, '外帘装袋', 1.00, 1.000, 0);
INSERT INTO processing_orders (id, tenant_id, items_snapshot, deleted) VALUES
    ('po-1', 1, '{"items":[{"name":"外帘装袋","is_must_finish":true}]}'::jsonb, 0);
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg4961-"))
    log = tmp_path / "pg.log"
    port = _free_port()
    # 起集群的**唯一实现**（失败 / 中止路径也停库 —— issue #5263 判据①）
    pg_cluster.start_cluster(realdb_binaries, datadir, sockdir=sockdir, port=port, log=log)

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
             "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)

    run.raw = psql_raw
    try:
        yield run
    finally:
        pg_cluster.stop_cluster(realdb_binaries["pg_ctl"], datadir)
        shutil.rmtree(sockdir, ignore_errors=True)


#: 把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。
#: ⚠️ 文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
#: `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
def _as_runner_would(sql: str) -> str:
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _seed(run) -> None:
    run(_DDL + _SEED)


def _matched(run) -> str:
    """V107 谓词匹配的行数（**改前**应 > 0、**改后**必须是 0 —— 这就是「第二遍 0 行」的读数）。"""
    return run(f"SELECT count(*) FROM {TABLE} WHERE {PREDICATE} "
               f"AND {COLUMN} IS DISTINCT FROM FALSE;").strip()


def _values(run, where: str) -> list:
    out = run(f"SELECT id || '=' || {COLUMN}::text FROM {TABLE} WHERE {where} ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def _fingerprint(run, table: str, columns: str) -> str:
    return run(f"SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM "
               f"(SELECT {columns} FROM {table}) t;").strip()


def test_migration_is_idempotent_and_converges_every_live_row(psql):
    """核心：两遍真跑 ⇒ 第二遍匹配 **0 行**、净效果相同；每个租户的存活行一律 `FALSE`。"""
    _seed(psql)
    before_matched = _matched(psql)
    assert before_matched == "2", (
        f"红证前提不成立：改前应恰好 2 条存活行的 is_must_finish 非 FALSE（实际 {before_matched}）")

    psql(_as_runner_would(_read(V107)))                 # 第一遍
    after_first = {t: _values(psql, f"tenant_id = {t} AND {PREDICATE}") for t in (1, 2)}
    matched_after_first = _matched(psql)
    rows_first = psql(f"SELECT count(*) FROM {TABLE};").strip()
    psql(_as_runner_would(_read(V107)))                 # 第二遍（幂等）
    after_second = {t: _values(psql, f"tenant_id = {t} AND {PREDICATE}") for t in (1, 2)}
    matched_after_second = _matched(psql)

    # ── 真库两遍幂等读数（PR 证据直接引这段输出） ──
    print(f"[#4961 真库] 改前谓词匹配行数        = {before_matched}")
    print(f"[#4961 真库] 第 1 遍后谓词匹配行数     = {matched_after_first}")
    print(f"[#4961 真库] 第 2 遍后谓词匹配行数     = {matched_after_second}  （= 0 ⇒ 幂等闸生效）")
    print(f"[#4961 真库] 1 号租户存活行 = {after_first[1]}")
    print(f"[#4961 真库] 2 号租户存活行 = {after_first[2]}")
    print(f"[#4961 真库] 存活行 is_must_finish 取值集 = "
          f"{psql(f'SELECT string_agg(DISTINCT {COLUMN}::text, chr(44)) FROM {TABLE} WHERE {PREDICATE};').strip()}")
    column_rows = psql("SELECT count(*) FROM information_schema.columns "
                       f"WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}';").strip()
    print(f"[#4961 真库] 列仍在（information_schema）= {column_rows}（1 = 列保留）")

    assert matched_after_first == "0", f"第一遍后仍有 {matched_after_first} 条存活行的值非 FALSE"
    assert matched_after_second == "0", f"第二遍匹配 {matched_after_second} 行 ⇒ 幂等闸失效"
    assert after_first == after_second, (
        f"V107 **不幂等**：第二遍改了净效果\n  第一遍：{after_first}\n  第二遍：{after_second}")
    assert after_first[1] == ["t1-live-false=false", "t1-live-true=false"], after_first[1]
    assert after_first[2] == ["t2-live-true=false"], (
        f"**非 1 号租户**没被覆盖（{after_first[2]}）—— 按租户循环/写死 tenant_id = 1 的写法会漏掉它")
    assert psql(f"SELECT count(*) FROM {TABLE};").strip() == rows_first, "V107 增删了行（它只许改值）"
    assert psql(f"SELECT count(*) FROM information_schema.columns WHERE table_name = '{TABLE}' "
                f"AND column_name = '{COLUMN}';").strip() == "1", "列不见了（本迁移不许 DROP 列）"


def test_soft_deleted_true_row_is_never_resurrected_or_touched(psql):
    """红线：已软删的 `TRUE` 行是「商家当时这么配过」的留痕 ⇒ `deleted` 与值都一字不动。"""
    _seed(psql)
    before = _values(psql, "deleted = 1")
    assert before == ["t1-deleted-false=false", "t1-deleted-true=true"], (
        f"夹具没造出预期的软删行：{before}（红证前提不成立）")
    psql(_as_runner_would(_read(V107)))
    after = _values(psql, "deleted = 1")
    print(f"[#4961 真库] 软删行（改前）= {before}")
    print(f"[#4961 真库] 软删行（改后）= {after}  （必须逐字不变：不复活、不翻值）")
    assert after == before, f"V107 动了已软删行：{before} → {after}"
    assert psql(f"SELECT count(*) FROM {TABLE} WHERE deleted = 1;").strip() == "2", "软删行数变了"


def test_snapshot_tables_are_byte_identical(psql):
    """红线：三张快照表（历史实例 / 历史报工 / 加工单快照）指纹前后逐字节相同。"""
    _seed(psql)
    before = {t: _fingerprint(psql, t, cols) for t, cols in SNAPSHOT_TABLES.items()}
    assert all(before.values()), f"改前指纹取不到（判据会空跑）：{before}"
    psql(_as_runner_would(_read(V107)))
    after = {t: _fingerprint(psql, t, cols) for t, cols in SNAPSHOT_TABLES.items()}
    assert after == before, f"红线被破：快照表指纹变了\n  改前：{before}\n  改后：{after}"


# ── 注入式红证：三条判据各自的判别力 ──

def test_reconciliation_blocks_a_partial_write(psql):
    """红证①：写语句**漏改一行**（判据漂移）⇒ 终态对账 `RAISE EXCEPTION` ⇒ 整份回滚。"""
    _seed(psql)
    before = _values(psql, PREDICATE)
    sql = _read(V107)
    old = ("UPDATE production_operations\n"
           "   SET is_must_finish = FALSE,\n"
           "       updated_at = NOW()\n"
           " WHERE deleted = 0\n"
           "   AND is_must_finish IS DISTINCT FROM FALSE;")
    assert old in sql, "注入锚点没匹配上（V107 的写语句被改过？）⇒ 本红证是空断言"
    injected = sql.replace(old, old[:-1] + "\n   AND id <> 't1-live-true';", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    print(f"[#4961 真库 · 红证①] 漏改一行 ⇒ 回滚 = {proc.returncode != 0}；"
          f"stderr 含「数量对账失败」= {'数量对账失败' in proc.stderr}")
    assert proc.returncode != 0, (
        f"漏改一行时终态对账竟通过了 ⇒ 停止条件是空断言\nstderr={proc.stderr[:400]}")
    assert "数量对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
    assert _values(psql, PREDICATE) == before, "对账抛异常后数据却变了 ⇒ 没有回滚（半完成态）"


def test_drop_column_injection_trips_the_red_line_guard(psql):
    """红证②：注入 `DROP COLUMN` ⇒ 文末的「列必须仍在」护栏当场抛 + 整份回滚。

    这条证明「不许 DROP 列」不只是注释里的自律 —— 它在运行期是**可拦的**。
    """
    _seed(psql)
    sql = _read(V107)
    comment_stmt = ("COMMENT ON COLUMN production_operations.is_must_finish IS\n"
                    "    '历史载体：必完概念已退场（issue #4961：完工 = 全部工序全绿）；值恒 FALSE';")
    assert comment_stmt in sql, "注入锚点没匹配上（列注释被改过？）⇒ 本红证是空断言"
    injected = sql.replace(comment_stmt, f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN};", 1)
    assert "DROP COLUMN" in injected and injected != sql, "注入没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    print(f"[#4961 真库 · 红证②] 注入 DROP COLUMN ⇒ 回滚 = {proc.returncode != 0}；"
          f"stderr 含「不许 DROP 列」= {'不许 DROP 列' in proc.stderr}")
    assert proc.returncode != 0, (
        f"把列 DROP 掉时护栏竟没抛 ⇒ 「列必须仍在」是空断言\nstderr={proc.stderr[:400]}")
    assert "不许 DROP 列" in proc.stderr, f"拦下的不是红线护栏：{proc.stderr[:400]}"
    assert psql(f"SELECT count(*) FROM information_schema.columns WHERE table_name = '{TABLE}' "
                f"AND column_name = '{COLUMN}';").strip() == "1", (
        "抛异常后列却没了 ⇒ 没有回滚（半完成态：列被真删了）")


def test_predicate_without_the_deleted_gate_would_touch_soft_deleted_rows(psql):
    """红证③：谓词丢掉 `deleted = 0` ⇒ 软删行被改（证明上一条「软删行不动」**有判别力**）。

    ⚠️ 这条**不是**在说 V107 写错了：它是对**判据本身**的自证 —— 若哪天有人把 `deleted = 0`
    从谓词里删掉，上一条断言会红。不做这条注入，上一条可能是「恒真」（例如夹具里根本没有软删行）。
    """
    _seed(psql)
    sql = _read(V107)
    old = (" WHERE deleted = 0\n"
           "   AND is_must_finish IS DISTINCT FROM FALSE;")
    assert old in sql, "注入锚点没匹配上 ⇒ 本红证是空断言"
    injected = sql.replace(old, " WHERE is_must_finish IS DISTINCT FROM FALSE;", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"
    psql(_as_runner_would(injected))
    got = _values(psql, "deleted = 1")
    print(f"[#4961 真库 · 红证③] 去掉 `deleted = 0` 后的软删行 = {got}（正常口径应为 "
          f"t1-deleted-true=true）")
    assert "t1-deleted-true=false" in got, (
        "去掉 `deleted = 0` 后软删行**没有**被改 ⇒ 上一条「软删行不动」是空断言"
        "（夹具或谓词判据失效）")


# ══════════════════════════ ③ bootstrap 镜像（双路径终态一致） ══════════════════════════

def test_bootstrap_matches_migration_chain_terminal_state(psql):
    """`backend/admin-api/src/main/resources/db/init/schema.sql`（bootstrap，不跑迁移链）的终态 == 迁移链（V54 冻结种子 + V107）终态。

    核对方式（**机械**，不靠人读）：
      ① **bootstrap 侧**：解析 `backend/admin-api/src/main/resources/db/init/schema.sql` 的工序库种子字面量 ⇒ 存活行的
         `is_must_finish` 取值集合必须 == `{"FALSE"}`（且行数自证解析没失效）；
      ② **迁移链侧**：真库里灌入**冻结 V54 种子**里的 `TRUE` 行（`外帘装袋`）+ 其余行，跑 V107
         ⇒ 终态取值集合必须 == `{"FALSE"}`；
      ③ **两侧相等**：两个集合相等（都是 `{"FALSE"}`）；并且把 ① 的终态再喂一遍 V107
         ⇒ **净效果不变**（bootstrap 库本就是终态，V107 在它上面是幂等空操作）。
    ⚠️ **必须同时断言两侧的「改前」不同**（链侧有 `TRUE`、bootstrap 侧已无）
      —— 否则本判据在「两边都恰好没这列/没这行」时也会绿（空断言）。
    """
    schema = _read(SCHEMA_SQL)
    boot_block = schema[schema.index("INSERT INTO production_operations"):]
    boot_rows = _seed_rows(boot_block)
    assert len(boot_rows) == 41, (
        f"schema.sql 的工序库种子解析出 {len(boot_rows)} 行，期望 41 ⇒ 解析失效或种子被改")

    # ① bootstrap 侧：终态取值集合
    boot_terminal = {r["must"] for r in boot_rows if r["deleted"] in (None, "0")}
    boot_true = sorted(r["name"] for r in boot_rows
                       if r["must"] == "TRUE" and r["deleted"] in (None, "0"))
    print(f"[#4961 bootstrap] schema.sql 存活工序行 = "
          f"{len([r for r in boot_rows if r['deleted'] in (None, '0')])}；"
          f"is_must_finish 取值集 = {sorted(boot_terminal)}；TRUE 行 = {boot_true}")
    assert boot_true == [], (
        f"schema.sql 的工序库种子仍有存活行 `is_must_finish = TRUE`：{boot_true} —— "
        f"bootstrap 路径不跑迁移链 ⇒ 它必须**自己**就是终态（否则新建库落在旧口径）")
    assert boot_terminal == {"FALSE"}, f"bootstrap 终态取值集不是 {{FALSE}}：{boot_terminal}"

    # ② 迁移链侧：冻结 V54 种子的 TRUE 行 + V107 ⇒ 终态
    v54 = _seed_rows(_read(V54))
    v54_true = sorted(r["name"] for r in v54 if r["must"] == "TRUE")
    assert v54_true == ["外帘装袋"], (
        f"冻结 V54 种子里 `is_must_finish = TRUE` 的行 = {v54_true}，期望恰好 `外帘装袋` "
        f"（已发布迁移不可改；改了口径就是改历史）")
    psql(_DDL)
    psql("INSERT INTO tenants (id) VALUES (1);")
    for r in v54:
        # ⚠️ `_ROW_RE` 的 `position` 组**自带外层单引号**（形态是 `'布帘'` 或裸 `NULL`）
        # ⇒ 直接当 SQL 字面量用，**不要**再包一层引号（包了会生成 `''布帘''` 这种语法错）。
        pos_literal = r["position"]
        psql(f"INSERT INTO {TABLE} (id, tenant_id, name, group_name, position, unit, unit_price, "
             f"{COLUMN}, is_start_marker, sort_order, status, deleted) VALUES "
             f"('{r['id']}', {r['tenant']}, '{r['name']}', '{r['group']}', "
             f"{pos_literal}, '{r['unit']}', {r['price']}, "
             f"{r['must']}, {r['start']}, {r['sort']}, '{r['status']}', 0);")
    # ⚠️ psql 回读的布尔是**小写**（`false` / `true`），而种子字面量是**大写**（`FALSE` / `TRUE`）
    # ⇒ 两侧比对前统一成大写（不归一 = 把「同一份数据两种书写」误判成漂移，本仓最忌的假红）。
    chain_pre = psql(f"SELECT string_agg(DISTINCT {COLUMN}::text, chr(44)) FROM {TABLE} "
                     f"WHERE {PREDICATE};").strip().upper()
    assert chain_pre == "FALSE,TRUE", f"链侧改前的取值集 = {chain_pre}（红证前提：必须含 TRUE）"
    psql(_as_runner_would(_read(V107)))
    chain_terminal = {v.split("=")[1].upper() for v in _values(psql, PREDICATE)}
    print(f"[#4961 迁移链] V54 冻结种子的 TRUE 行 = {v54_true}；改前取值集 = {chain_pre}；"
          f"V107 后取值集 = {sorted(chain_terminal)}")

    # ③ 两侧相等 + bootstrap 库上再跑一遍 V107 是幂等空操作
    assert chain_terminal == boot_terminal, (
        f"两条路径的终态分裂：bootstrap = {sorted(boot_terminal)}，"
        f"迁移链 = {sorted(chain_terminal)}")
    matched_before = _matched(psql)
    psql(_as_runner_would(_read(V107)))
    assert _matched(psql) == matched_before == "0", (
        "在已是终态的库上跑 V107 竟然又匹配到行 ⇒ 谓词/幂等闸有问题")
