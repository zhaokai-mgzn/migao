# case_ids: PR-051
"""库存米数小数化迁移 **V115** 的承重判据 + 真库两遍幂等 + bootstrap 终态镜像（issue #5063）。

（用户裁定逐字：「**库存米数是小数，1 位小数，必须改造**」＋「**不能损失客户**」⇒
精度取 `NUMERIC(12,1)`，与用料口径 `docs/curtain-fabric-quote-rules.md` §8「用料米数一律
**向上进位到 0.1**」一致。）

## 本文件钉的事

| 面 | 判据 |
|---|---|
| 形态（静态） | 显式 `BEGIN;/COMMIT;`；五张前置表 fail-closed；**只 ALTER 类型**（不 DROP 列、不建影子表）；幂等靠「先问 `information_schema` 再 `EXECUTE`」（已是终态 ⇒ `CONTINUE`）；文末 `DO` 块逐列核对 `data_type/numeric_precision/numeric_scale` |
| 真库（临时 PG） | 两遍真跑：都成功、终态列类型与精度一致、**存量整数值逐位不失**（`60 :: numeric(12,1)` = `60.0`）；把某列**退回 INTEGER** 后再跑 ⇒ 自愈回终态（证明 ALTER 路径可重入，不是一次性）；列集合前后不变（没有多列/少列） |
| 判别力（注入红证） | ① 目标列表漏一列 ⇒ 终态对账在 `col_count <> 9` 处 `RAISE EXCEPTION`；② 把某列错改成 `NUMERIC(12,2)` ⇒ 精度对账抛；③ DROP 一张前置表 ⇒ 前置 fail-closed 抛（不兜底建表） |
| bootstrap 镜像 | `backend/admin-api/src/main/resources/db/init/schema.sql`（**新建库路径不跑迁移链**）九列同为 `NUMERIC(12,1)` |
| 不可变护栏 | V115 已登记进 `migration_fingerprints.json`（#4235）—— 否则它以后能被静默改 |

## 为什么必须真跑

`ALTER COLUMN TYPE … USING` 的**有损性**、`information_schema` 在 `ALTER` 后的可见时机、
`DO $$ … $$` 里 `RAISE EXCEPTION` 的回滚半径 —— 三者都是**运行期**语义，静态文本判据判不出来
（V83 的教训：文本守卫全绿而真库整份回滚）。

## 真库判据（临时 PG 集群；缺 PG 的处置收口在 `pg_cluster.py`：CI 判**红** / 本机显式 skip，issue #5203）

照 `tests/unit_ci_workflows/test_must_finish_retire_migration.py` 的范式：`initdb` / `pg_ctl` /
`psql` 起**临时集群**真跑。
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



V115 = MIGRATION_DIR / "V115__stock_quantity_decimal_1dp.sql"
SCHEMA_SQL = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

#: 本迁移的目标：九列一律 `numeric(12,1)`（`(表, 列)`；与迁移里的 `VALUES` 列表同源，不另立一份）
TARGET_COLUMNS = (
    ("product_skus", "stock"),
    ("product_skus", "sales_count"),
    ("products", "stock"),
    ("products", "sales_count"),
    ("stock_ledger_entries", "delta"),
    ("stock_ledger_entries", "before_qty"),
    ("stock_ledger_entries", "after_qty"),
    ("inbound_order_items", "quantity"),
    ("stock_batches", "quantity"),
)


#: 与 `backend/admin-api/src/main/resources/db/init/schema.sql` 同形的**最小** DDL —— 起点是**改前**形态（数量列 INTEGER）。
#: 只建本迁移触碰的表/列（+ 前置判据要用的表名），不复制整份 schema。
_DDL = """
CREATE TABLE products (
    id VARCHAR(64) PRIMARY KEY,
    stock INTEGER DEFAULT 0,
    sales_count INTEGER DEFAULT 0);
CREATE TABLE product_skus (
    id BIGINT PRIMARY KEY,
    product_id VARCHAR(64),
    stock INTEGER NOT NULL DEFAULT 0,
    sku_code VARCHAR(50),
    sales_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE stock_ledger_entries (
    id BIGINT PRIMARY KEY,
    tenant_id BIGINT,
    product_id VARCHAR(64),
    sku_id BIGINT,
    sku_code VARCHAR(64),
    delta INT NOT NULL,
    before_qty INT NOT NULL,
    after_qty INT NOT NULL,
    reason VARCHAR(16) NOT NULL,
    ref_no VARCHAR(64),
    note VARCHAR(255));
CREATE TABLE inbound_order_items (
    id BIGINT PRIMARY KEY,
    product_id VARCHAR(64),
    sku_code VARCHAR(64),
    quantity INT NOT NULL,
    unit_cost NUMERIC(12,4));
CREATE TABLE stock_batches (
    id BIGINT PRIMARY KEY,
    batch_no VARCHAR(32) NOT NULL,
    product_id VARCHAR(64),
    sku_id BIGINT,
    quantity INT NOT NULL,
    unit_cost NUMERIC(12,4));
"""

#: 存量行：整数（**小数化前的真形态**）⇒ 迁移必须无损（60 仍是 60，不是 60.0 的"另一个值"）
_SEED = """
INSERT INTO products (id, stock, sales_count) VALUES ('prod-1', 100, 7);
INSERT INTO product_skus (id, product_id, stock, sku_code, sales_count)
    VALUES (100, 'prod-1', 60, 'SKU-100', 5);
INSERT INTO stock_ledger_entries
    (id, tenant_id, product_id, sku_id, sku_code, delta, before_qty, after_qty, reason, ref_no, note)
    VALUES (1, 1, 'prod-1', 100, 'SKU-100', 60, 0, 60, 'inbound', 'RK-1', '首次入库');
INSERT INTO inbound_order_items (id, product_id, sku_code, quantity, unit_cost)
    VALUES (1, 'prod-1', 'SKU-100', 60, 12.5000);
INSERT INTO stock_batches (id, batch_no, product_id, sku_id, quantity, unit_cost)
    VALUES (1, 'PC-20260922-0001', 'prod-1', 100, 60, 12.5000);
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释 → 空（供**写语句**判据用）。

    ⚠️ 必须去注释：本仓迁移把「回滚 SQL」写在注释里（V115 的回滚段里就有一串 `ALTER TABLE`），
    不去注释会把注释里的 `ALTER` 当成真写语句。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


# ══════════════════════════ ① 形态 / 账本（静态） ══════════════════════════

def test_v115_exists_and_is_the_unique_highest_version():
    assert V115.exists(), f"缺少迁移文件：{V115.name}"
    versions = [int(re.match(r"^V(\d+)__", p.name).group(1))
                for p in _migration_files("V*.sql") if re.match(r"^V(\d+)__", p.name)]
    assert versions.count(115) == 1, "V115 版本号重复"
    assert max(versions) >= 115, f"V115 不是最高版本号（当前最大 V{max(versions)}）"


def test_v115_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏（issue #4235）：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert V115.name in ledger, (
        f"`{V115.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_v115_is_explicitly_transactional_and_fails_closed():
    body = _read(V115)
    assert re.search(r"^BEGIN;", body, re.M), "V115 缺显式 `BEGIN;`（psql -f 默认逐条 autocommit ⇒ 半完成态）"
    assert re.search(r"^COMMIT;", body, re.M), "V115 缺显式 `COMMIT;`"
    assert body.count("RAISE EXCEPTION") >= 3, (
        "V115 缺 fail-closed 停止条件（前置表/列缺失 + 终态对账至少三处 `RAISE EXCEPTION`）")
    # 前置判据必须在**写语句之前**。⚠️ 位置判据必须落在**去注释后**的文本上：
    # 本文件头部的「回滚（新迁移，不删本文件）」段里有一串 `ALTER TABLE … TYPE INTEGER` 注释，
    # 不去注释会把注释里的 ALTER 当成真写语句 ⇒ 判据恒假（#4595 的同族教训）。
    code = _strip_comments(body)
    first_alter = code.index("ALTER TABLE")
    first_guard = code.index("RAISE EXCEPTION")
    assert first_guard < first_alter, "前置 fail-closed 判据排在写语句之后（半完成态风险）"


def test_v115_only_alters_types_and_never_drops_or_creates():
    body = _strip_comments(_read(V115))
    assert not re.search(r"\bDROP\s+(COLUMN|TABLE)\b", body, re.I), (
        "V115 出现 DROP —— 本迁移只许改类型（列/表一律保留，回滚见文件头注释）")
    assert not re.search(r"\bCREATE\s+TABLE\b", body, re.I), (
        "V115 出现 CREATE TABLE —— 前置表缺失必须 fail-closed，不兜底建影子表")
    alters = re.findall(r"ALTER TABLE\s+%I\s+ALTER COLUMN\s+%I\s+TYPE\s+NUMERIC\(12,1\)", body)
    assert len(alters) == 1, (
        f"V115 的 ALTER 必须只有一处（`EXECUTE format(...)` 里那一处，循环驱动九列）；实际 {len(alters)}")
    # 迁移里的 VALUES 列表为可读性做了列对齐（逗号后多个空格）⇒ 判据先归一空白再比
    normalized = re.sub(r"\s+", " ", body)
    for tbl, col in TARGET_COLUMNS:
        assert f"('{tbl}', '{col}')" in normalized, (
            f"目标列表缺 `{tbl}.{col}` —— 少一列 ⇒ 那一列永远停在 INTEGER 且无人发现")


def test_v115_idempotency_is_a_terminal_state_predicate():
    """幂等闸必须在「列当前类型」这一层：已是 `numeric(12,1)` ⇒ `CONTINUE`（不做无谓表重写）。"""
    body = _read(V115)
    assert "information_schema.columns" in body, "V115 没读 information_schema（无法判「已是终态」）"
    assert re.search(r"IF\s+current_type\s*=\s*'numeric'\s+AND\s+current_prec\s*=\s*12\s+AND\s+current_scal\s*=\s*1\s+THEN\s+CONTINUE",
                     body), "缺「已是终态则跳过」的判据（`CONTINUE`）—— 幂等闸不在类型层"
    assert "RAISE EXCEPTION" in body and "col_count <> 9" in body, "缺终态列数对账（`col_count <> 9`）"


def test_schema_sql_bootstrap_path_is_already_terminal():
    """bootstrap 路径（新建库**不跑迁移链**）必须与迁移终态同形 —— 两侧不一致 = 新库行为与老库分叉。"""
    schema = _read(SCHEMA_SQL)
    missing = []
    for tbl, col in TARGET_COLUMNS:
        # 在该表的 CREATE TABLE 段里找列定义
        # schema.sql 两种写法并存（`CREATE TABLE x (` 与 `CREATE TABLE IF NOT EXISTS x (`）⇒ 都要认
        m0 = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{tbl} \(", schema)
        assert m0, f"schema.sql 里没有表 {tbl}"
        table_start = m0.start()
        nxt_m = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?\w+ \(", schema[table_start + 10:])
        nxt = table_start + 10 + nxt_m.start() if nxt_m else len(schema)
        segment = schema[table_start:nxt]
        m = re.search(rf"^\s*{col}\s+([A-Za-z]+(?:\(\d+(?:,\s*\d+)?\))?)", segment, re.M)
        assert m, f"schema.sql 的 {tbl} 段里找不到列 {col}"
        if m.group(1).replace(" ", "").upper() != "NUMERIC(12,1)":
            missing.append(f"{tbl}.{col} = {m.group(1)}")
    assert not missing, f"schema.sql 未同步 V115 终态（仍是旧类型/精度）：{missing}"


# ══════════════════════════ ② 真库判据（临时 PG 集群） ══════════════════════════

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg5063-"))
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


def _as_runner_would(sql: str) -> str:
    """把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。

    ⚠️ 文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
    `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
    """
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _column_types(run) -> dict:
    """九列的 `(data_type, numeric_precision, numeric_scale)`（**派生**，不手写期望值）。"""
    rows = run("SELECT table_name || '.' || column_name || '=' || data_type || '/' || "
               "COALESCE(numeric_precision::text, '-') || '/' || COALESCE(numeric_scale::text, '-') "
               "FROM information_schema.columns WHERE table_schema = 'public' "
               "AND (table_name, column_name) IN (" +
               ", ".join(f"('{t}', '{c}')" for t, c in TARGET_COLUMNS) +
               ") ORDER BY table_name, column_name;")
    return dict(line.split("=", 1) for line in rows.splitlines() if line.strip())


def _snapshot(run) -> str:
    """存量数据的指纹（迁移前后必须逐字节相同：整数小数化是无损转换）。"""
    # ⚠️ 两侧都归一到 `numeric(12,1)::text` 再比：改前列是 INTEGER ⇒ `60::text` = '60'，
    # 改后是「整数 → NUMERIC(12,1) 必须**值**无损」（不是「文本逐字节相同」——
    # `60` 与 `60.0` 的文本本来就不同，那不是"改动"，是同一数值的两种书写）。
    return run(
        "SELECT md5(string_agg(t::text, '|' ORDER BY t::text)) FROM ("
        " SELECT stock::numeric(12,1)::text || ',' || sales_count::numeric(12,1)::text FROM products"
        " UNION ALL SELECT stock::numeric(12,1)::text || ',' || sales_count::numeric(12,1)::text"
        "   FROM product_skus"
        " UNION ALL SELECT delta::numeric(12,1)::text || ',' || before_qty::numeric(12,1)::text"
        "   || ',' || after_qty::numeric(12,1)::text FROM stock_ledger_entries"
        " UNION ALL SELECT quantity::numeric(12,1)::text FROM inbound_order_items"
        " UNION ALL SELECT quantity::numeric(12,1)::text FROM stock_batches) t;").strip()


def _seed(run) -> None:
    run(_DDL + _SEED)


def test_real_pg_two_runs_are_idempotent_and_lossless(psql):
    """核心：两遍真跑都成功、终态九列一律 `numeric(12,1)`、存量整数值逐位不失。"""
    _seed(psql)
    before_types = _column_types(psql)
    assert all(v.endswith("/-/-") or v.startswith("integer") for v in before_types.values()), (
        f"红证前提不成立：改前数量列应是 INTEGER（实际 {before_types}）")
    before_data = _snapshot(psql)

    psql(_as_runner_would(_read(V115)))                 # 第一遍
    after_first = _column_types(psql)
    data_first = _snapshot(psql)
    psql(_as_runner_would(_read(V115)))                 # 第二遍（幂等）
    after_second = _column_types(psql)
    data_second = _snapshot(psql)

    print(f"[#5063 真库] 改前列类型      = {sorted(before_types.values())[:3]} …")
    print(f"[#5063 真库] 第 1 遍后列类型   = {after_first}")
    print(f"[#5063 真库] 第 2 遍后列类型   = {after_second}  （与第 1 遍一致 ⇒ 幂等）")
    print(f"[#5063 真库] 存量数据指纹      = 改前 {before_data} / 1 遍后 {data_first} / 2 遍后 {data_second}")

    assert set(after_first) == {f"{t}.{c}" for t, c in TARGET_COLUMNS}, "终态列集合与目标不一致"
    for key, val in after_first.items():
        assert val == "numeric/12/1", f"{key} 终态不是 numeric(12,1)：{val}"
    assert after_second == after_first, f"V115 **不幂等**：第二遍改了终态\n{after_first}\n{after_second}"
    assert data_first == data_second, "第二遍改了存量数据（本迁移只许改类型）"
    assert before_data == data_first, (
        f"存量数据被改动（整数 → numeric(12,1) 必须无损）：{before_data} → {data_first}")


def test_real_pg_rolls_back_on_terminal_mismatch(psql):
    """红证①/②：目标列表漏一列 / 精度写错 ⇒ 终态对账抛 ⇒ **整份回滚**（不留半完成态）。"""
    _seed(psql)
    body = _read(V115)

    # 红证①：漏一列 ⇒ 列数对账（col_count <> 9）抛
    missing_one = body.replace("('stock_batches',        'quantity')",
                               "('stock_batches',        'quantity')".replace("'quantity'", "'quantity'"))
    anchor = "('inbound_order_items',  'quantity'),\n            ('stock_batches',        'quantity')"
    assert anchor in body, "注入锚点没匹配上（V115 的目标列表被改过？）⇒ 本红证是空断言"
    injected = body.replace(anchor, "('inbound_order_items',  'quantity')", 1)
    assert injected != body, "注入没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    print(f"[#5063 真库 · 红证①] 目标列表漏一列 ⇒ 回滚 = {proc.returncode != 0}；"
          f"stderr 含「终态对账失败」= {'终态对账失败' in proc.stderr}")
    assert proc.returncode != 0, "漏一列时终态对账竟通过了 ⇒ 停止条件是空断言"

    # 红证②：精度错写成 2 位 ⇒ 精度对账抛（$stmt$ 写对了但 scale 不符）
    wrong_scale = body.replace("TYPE NUMERIC(12,1) USING %I::numeric(12,1)",
                               "TYPE NUMERIC(12,2) USING %I::numeric(12,2)")
    assert wrong_scale != body, "注入没生效 ⇒ 本红证是空断言"
    proc2 = psql.raw(_as_runner_would(wrong_scale))
    print(f"[#5063 真库 · 红证②] 精度写成 NUMERIC(12,2) ⇒ 回滚 = {proc2.returncode != 0}")
    assert proc2.returncode != 0, "精度不符时终态对账竟通过了 ⇒ 精度判据是空断言"

    # 回滚的证据：两处失败后列仍是 INTEGER（没有半完成态）
    assert all("integer" in v or v.endswith("/-/-") for v in _column_types(psql).values()), (
        "_as_runner_would 没有真正回滚 —— 留下半完成态（比失败更危险）")


def test_real_pg_fails_closed_when_a_source_table_is_missing(psql):
    """红证③：前置表缺失 ⇒ 立即失败并停下（**不兜底建表**：影子表会造出无外键/无索引的结构）。"""
    psql(_DDL.replace("CREATE TABLE stock_batches (", "CREATE TABLE stock_batches_unused ("))
    proc = psql.raw(_as_runner_would(_read(V115)))
    print(f"[#5063 真库 · 红证③] 缺 stock_batches ⇒ 失败 = {proc.returncode != 0}；"
          f"stderr 含「前置表缺失」= {'前置表缺失' in proc.stderr}")
    assert proc.returncode != 0, "缺前置表时迁移竟通过了 ⇒ fail-closed 是空断言"
    assert "前置表缺失" in proc.stderr, f"失败原因不是前置判据：{proc.stderr[:300]}"
    assert psql("SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='stock_batches';").strip() == "0", (
        "迁移**建了**缺失的表（兜底建表 = 造影子表，本迁移明令禁止）")


def test_real_pg_reverts_to_terminal_when_a_column_was_rolled_back(psql):
    """自愈/可重入：某列被回滚成 INTEGER 后再跑一遍 ⇒ **收敛回** `numeric(12,1)` 且数据保真。

    这条是「幂等」的**判别力**所在 —— 只跑两遍相同输入时，「已是终态则跳过」与
    「无条件重 ALTER」两种实现读数完全一样；把起点改成**半回滚态**才能分开它们。
    """
    _seed(psql)
    psql(_as_runner_would(_read(V115)))
    psql("ALTER TABLE product_skus ALTER COLUMN stock TYPE INTEGER USING ROUND(stock)::integer;")
    assert _column_types(psql)["product_skus.stock"].startswith("integer"), "回滚注入没生效"

    psql(_as_runner_would(_read(V115)))

    after = _column_types(psql)
    print(f"[#5063 真库] 半回滚态 → 再跑一遍后 product_skus.stock = {after['product_skus.stock']}")
    assert after["product_skus.stock"] == "numeric/12/1", "V115 不能把半回滚态收敛回终态"
    assert all(v == "numeric/12/1" for v in after.values()), f"有列没收敛：{after}"
