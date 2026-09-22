# case_ids: PR-064
"""V119 真库判据：批次消耗台账的两个米数 + 「当时」均价（issue #5158；硬要求来自 #5159 L1）。

## 为什么必须真库

本迁移的判据全是**PG 自己的语义**：

| 判据 | 为什么 mock / 源码断言不够 |
|---|---|
| 历史行回填（`formula_meters = planned_meters = −delta`） | 回填是一句 `UPDATE … WHERE … IS NULL`；谓词写错在源码层面看不出来，只有**跑过才知道**（第二遍幂等也靠它） |
| 「只多不少」约束（`planned <= formula` 且两列同号） | 约束是否**真的拦得住**是 PG 的行为（23514）；只断言 `pg_constraint` 里有这行字，测的是我抄的字符串 |
| NOT NULL 生效 | 漏了它 ⇒ 「答不出省了多少」的账能静默落库，而源码里 `ADD COLUMN` 一句看不出可空性 |
| 两遍真跑幂等 | `MigrationRunner` 对**所有**迁移都要求可重复执行（`ADD COLUMN IF NOT EXISTS` / 覆盖式注释 / `SET NOT NULL` 的重复性） |

范式与 `tests/unit_ci_workflows/test_inbound_order_idempotency.py`（#5148）同款：
一次性真 PG 集群（`initdb` + `pg_ctl` + `psql`），本机缺 PG 二进制时**显式 skip**（不是通过）。

## 口径（本迁移新增的全部语义）

- `formula_meters` = 该行**行业公式口径**米数（与销售账扣减同源同函数）；
- `planned_meters` = 该行**排料口径**米数（= 改后实际扣减口径，恒等于 `−delta`）；
- `unit_cost` = **当时**该批次均价快照（`saved_amount = (formula − planned) × unit_cost` 的唯一来源）；
- 历史行：`formula = planned = −delta`（⇒ `saved = 0`，与「本单之前节省恒为 0」一致），
  均价**不回填**（NULL = 未知，不拿今天的批次价冒充当时价）。
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
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
V119 = MIGRATION_DIR / "V119__add_cutting_plan_meters_to_batch_consumptions.sql"
SCHEMA_SQL = REPO / "docs/sql/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

TENANT = 1
BATCH_ID = 77

#: 改前形态（V116 之后的 `stock_batch_consumptions`，**只建本迁移触碰的表**）。
#: 有意**不**建 FK 指向的表（tenants/products/stock_batches）—— 本迁移不碰外键，
#: 而「前置表缺失」的 fail-closed 判据只在**整表**缺失时才该触发（下面另有一条红证）。
_DDL = """
CREATE TABLE stock_batch_consumptions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    batch_id BIGINT NOT NULL,
    batch_no VARCHAR(32) NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    sku_id BIGINT,
    sku_code VARCHAR(64),
    delta NUMERIC(12,1) NOT NULL,
    before_qty NUMERIC(12,1) NOT NULL,
    after_qty NUMERIC(12,1) NOT NULL,
    reason VARCHAR(32) NOT NULL,
    processing_order_no VARCHAR(32) NOT NULL,
    order_no VARCHAR(32),
    order_item_id VARCHAR(36) NOT NULL,
    operator VARCHAR(64) NOT NULL,
    note VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX uk_batch_consumption_line
    ON stock_batch_consumptions (tenant_id, processing_order_no, batch_id, order_item_id, reason)
    WHERE deleted = 0;
"""

#: 两条**存量**行（改前写的账）：一扣（−3）一回补（+3）—— 回填的方向由此可判。
_SEED = f"""
INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, product_id, sku_id, sku_code,
    delta, before_qty, after_qty, reason, processing_order_no, order_no, order_item_id, operator)
VALUES
    ({TENANT}, {BATCH_ID}, 'PC-1', 'prod-1', 12, 'SKU-A', -3, 60, 57,
     'processing_order', 'JG-OLD', 'ORD-OLD', 'item-old-1', 'u1'),
    ({TENANT}, {BATCH_ID}, 'PC-1', 'prod-1', 12, 'SKU-A', 3, 57, 60,
     'processing_order_cancelled', 'JG-OLD', 'ORD-OLD', 'item-old-1', 'u1');
"""

_PG_BINARIES = ("initdb", "pg_ctl", "psql")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释 → 空（供**写语句**判据用）。本仓迁移把回滚 SQL 写在注释里 ⇒ 不去注释会误判。"""
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


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
    sockdir = Path(tempfile.mkdtemp(prefix="pg5158-"))  # socket 路径有 ~104 字节上限
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

    argv = ["psql", "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
            "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"]

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「**确实**失败」）。"""
        return subprocess.run(argv, input=sql, text=True, capture_output=True)

    run.raw = psql_raw
    try:
        yield run
    finally:
        subprocess.run(["pg_ctl", "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


def _as_runner_would(sql: str) -> str:
    """把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。"""
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _migrate_twice(psql) -> None:
    """改前形态 + 存量行夹具，再**真跑两遍** V119（第一遍做回填、第二遍证明幂等）。"""
    psql(_DDL + _SEED)
    psql(_as_runner_would(_read(V119)))
    psql(_as_runner_would(_read(V119)))


# ══════════════════════════ ① 三列 + NOT NULL + 历史行回填 ══════════════════════════

def test_columns_are_added_and_the_two_meters_are_not_null(psql):
    _migrate_twice(psql)
    cols = psql("SELECT column_name || ':' || is_nullable FROM information_schema.columns "
                "WHERE table_name = 'stock_batch_consumptions' "
                "AND column_name IN ('formula_meters', 'planned_meters', 'unit_cost') "
                "ORDER BY column_name;").strip().splitlines()
    print(f"[#5158 真库 · 列] {cols}")
    assert cols == ["formula_meters:NO", "planned_meters:NO", "unit_cost:YES"], (
        f"三列的可空性不对（两个米数必须 NOT NULL —— 否则「答不出省了多少」的账能静默落库）：{cols}")


def test_historical_rows_are_backfilled_with_minus_delta(psql):
    """回填口径 = 改前的扣减口径：`formula = planned = −delta` ⇒ `saved = 0`；均价**不猜**。"""
    _migrate_twice(psql)
    rows = psql("SELECT reason || '|' || formula_meters::text || '|' || planned_meters::text || '|' "
                "|| COALESCE(unit_cost::text, 'NULL') FROM stock_batch_consumptions ORDER BY id;"
                ).strip().splitlines()
    print(f"[#5158 真库 · 回填] {rows}")
    assert rows == [
        "processing_order|3.0|3.0|NULL",
        "processing_order_cancelled|-3.0|-3.0|NULL",
    ], f"历史行回填不对（扣减行应正、回补行应负、均价留 NULL 不猜）：{rows}"
    saved = psql("SELECT COALESCE(SUM(formula_meters - planned_meters), 0)::text "
                 "FROM stock_batch_consumptions;").strip()
    assert saved == "0.0", f"历史行的 saved 必须恒为 0（本单之前节省就是零）：{saved}"


# ══════════════════════════ ② 「只多不少」约束真的拦得住 ══════════════════════════

def _insert(psql, *, formula: str, planned: str, item: str):
    return psql.raw(
        "INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, product_id, sku_id,"
        " sku_code, delta, before_qty, after_qty, reason, processing_order_no, order_no,"
        " order_item_id, operator, formula_meters, planned_meters) VALUES"
        f" ({TENANT}, {BATCH_ID}, 'PC-1', 'prod-1', 12, 'SKU-A', {-float(planned)}, 60, 60,"
        f" 'processing_order', 'JG-NEW', 'ORD-NEW', '{item}', 'u1', {formula}, {planned});")


def test_plan_meters_constraint_rejects_planned_greater_than_formula(psql):
    """排料口径**大于**公式口径 = 排料反而多领 ⇒ 当场 23514（不是靠 Java 记得别写错）。"""
    _migrate_twice(psql)
    bad = _insert(psql, formula="3", planned="3.1", item="item-bad-1")
    ok = _insert(psql, formula="3", planned="1.5", item="item-ok")
    print(f"[#5158 真库 · 只多不少] 写 planned>formula ⇒ 退出码 = {bad.returncode}；"
          f"stderr 含约束名 = {'ck_batch_consumption_plan_meters' in bad.stderr}")
    assert bad.returncode != 0, f"「排料口径不得大于公式口径」没生效（竟能落库）：{bad.stderr[:300]}"
    assert "ck_batch_consumption_plan_meters" in bad.stderr, (
        f"拦下它的不是这条约束：{bad.stderr[:300]}")
    assert ok.returncode == 0, f"合法的（planned < formula）反被拦下：{ok.stderr[:300]}"


def test_plan_meters_constraint_rejects_sign_mismatch(psql):
    """两列**同号**：`(+6, −3)` 这种「符号打架」的行净额看着对、逐单审计是坏的 ⇒ 拦住。"""
    _migrate_twice(psql)
    bad = _insert(psql, formula="6", planned="-3", item="item-bad-2")
    print(f"[#5158 真库 · 同号] 写 (+6, −3) ⇒ 退出码 = {bad.returncode}；"
          f"stderr 含约束名 = {'ck_batch_consumption_plan_meters' in bad.stderr}")
    assert bad.returncode != 0, f"符号打架的行竟能落库：{bad.stderr[:300]}"
    assert "ck_batch_consumption_plan_meters" in bad.stderr, (
        f"拦下它的不是这条约束：{bad.stderr[:300]}")


def test_unit_cost_constraint_rejects_negative_cost(psql):
    """负成本 = 负的省钱数（读面看不出是坏数据）⇒ 拦住。"""
    _migrate_twice(psql)
    bad = psql.raw(
        "INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, product_id, sku_id,"
        " sku_code, delta, before_qty, after_qty, reason, processing_order_no, order_no,"
        " order_item_id, operator, formula_meters, planned_meters, unit_cost) VALUES"
        f" ({TENANT}, {BATCH_ID}, 'PC-1', 'prod-1', 12, 'SKU-A', -1.5, 60, 58.5,"
        " 'processing_order', 'JG-NEG', 'ORD-NEG', 'item-neg', 'u1', 3, 1.5, -12.5);")
    print(f"[#5158 真库 · 均价] 写 unit_cost = −12.5 ⇒ 退出码 = {bad.returncode}")
    assert bad.returncode != 0, f"负均价竟能落库：{bad.stderr[:300]}"
    assert "ck_batch_consumption_unit_cost" in bad.stderr, (
        f"拦下它的不是这条约束：{bad.stderr[:300]}")


# ══════════════════════════ ③ 幂等两遍（终态与数据都不变） ══════════════════════════

def test_second_run_changes_nothing(psql):
    """`MigrationRunner` 要求所有迁移可重复执行：两遍之后列数/行数/回填值逐值相同。"""
    psql(_DDL + _SEED)
    psql(_as_runner_would(_read(V119)))
    first = psql("SELECT count(*) || '|' || COALESCE(SUM(formula_meters), 0)::text || '|' "
                 "|| COALESCE(SUM(planned_meters), 0)::text FROM stock_batch_consumptions;").strip()
    cols_first = psql("SELECT count(*)::text FROM information_schema.columns "
                      "WHERE table_name = 'stock_batch_consumptions';").strip()

    psql(_as_runner_would(_read(V119)))  # 第二遍

    assert psql("SELECT count(*) || '|' || COALESCE(SUM(formula_meters), 0)::text || '|' "
                "|| COALESCE(SUM(planned_meters), 0)::text FROM stock_batch_consumptions;"
                ).strip() == first, "第二遍改动了存量数据（回填谓词不是 WHERE … IS NULL）"
    assert psql("SELECT count(*)::text FROM information_schema.columns "
                "WHERE table_name = 'stock_batch_consumptions';").strip() == cols_first, \
        "第二遍增删了列"


def test_missing_prerequisite_table_fails_closed(psql):
    """前置判据（表在不在）必须**先于**写语句：缺表时停下，不兜底建表、不留半完成态。"""
    bad = psql.raw(_as_runner_would(_read(V119)))
    print(f"[#5158 真库 · fail-closed] 空库跑 V119 ⇒ 退出码 = {bad.returncode}；"
          f"stderr 含「前置表缺失」= {'前置表缺失' in bad.stderr}")
    assert bad.returncode != 0, "空库跑 V119 竟然成功（前置判据没生效）"
    assert "前置表缺失" in bad.stderr, f"失败原因不是前置判据：{bad.stderr[:300]}"
    assert "stock_batch_consumptions" not in psql(
        "SELECT COALESCE(string_agg(table_name, ','), '') FROM information_schema.tables "
        "WHERE table_name = 'stock_batch_consumptions';"), "缺表时兜底建了表（应当停下）"


# ══════════════════════════ ④ 迁移形态 / 账本 / bootstrap 镜像（源码面） ══════════════════════════

def test_v119_is_the_unique_highest_version():
    assert V119.exists(), f"缺少迁移文件：{V119.name}"
    versions = [int(m.group(1)) for p in MIGRATION_DIR.glob("V*.sql")
                if (m := re.match(r"^V(\d+)__", p.name))]
    print(f"[#5158 迁移] 最高版本 = V{max(versions)}，V119 出现 {versions.count(119)} 次")
    assert versions.count(119) == 1, "V119 版本号重复（有一条永远不会跑）"
    assert max(versions) == 119, f"V119 不是最高版本号（当前最大 V{max(versions)}）"


def test_v119_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏（issue #4235）：新增迁移必须进内容指纹账本，否则以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert ledger.get(V119.name, "").startswith("sha256:"), (
        f"`{V119.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_v119_is_explicitly_transactional_and_fails_closed_before_writing():
    body = _read(V119)
    assert re.search(r"^BEGIN;", body, re.M), "缺显式 `BEGIN;`（psql -f 默认逐条 autocommit ⇒ 半完成态）"
    assert re.search(r"^COMMIT;", body, re.M), "缺显式 `COMMIT;`"
    code = _strip_comments(body)
    first_write = min(code.index(k) for k in ("ADD COLUMN", "ALTER TABLE", "UPDATE "))
    assert code.index("RAISE EXCEPTION") < first_write, (
        "前置 fail-closed 判据排在写语句之后（缺表时会先改一半再抛）")
    assert "终态对账" in body, "缺终态对账（判据漂移的停止条件）"
    # 回填必须有 `IS NULL` 谓词（否则第二遍会把已回填的值再取一次反 ⇒ 数据漂移）
    assert re.search(r"WHERE\s+formula_meters IS NULL OR planned_meters IS NULL", body), (
        "回填缺 `IS NULL` 谓词（重复执行会翻转历史值）")


def test_bootstrap_schema_sql_is_already_terminal():
    """bootstrap 路径（新建库**不跑迁移链**）必须与 V119 终态同形，否则新库与老库行为分叉。"""
    schema = _read(SCHEMA_SQL)
    assert re.search(r"formula_meters NUMERIC\(12,1\) NOT NULL", schema), "schema.sql 缺 formula_meters"
    assert re.search(r"planned_meters NUMERIC\(12,1\) NOT NULL", schema), "schema.sql 缺 planned_meters"
    assert re.search(r"unit_cost NUMERIC\(12,4\)", schema), "schema.sql 缺 unit_cost（或精度与批次表不一致）"
    assert "ck_batch_consumption_plan_meters" in schema, "schema.sql 缺「只多不少」约束"
    assert "planned_meters <= formula_meters AND formula_meters * planned_meters >= 0" in schema, (
        "schema.sql 的约束丢了后半句（两列同号）")
