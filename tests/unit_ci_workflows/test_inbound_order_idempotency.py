# case_ids: PR-030, PR-031, PR-058
"""入库单的**并发过账闸**与**建单幂等**：真库判据（临时 PG 集群）+ V117 的索引/约束口径（issue #5148）。

## 为什么必须真库（Mockito 测不出来）

本单修的两个缺陷都**只在真库上存在**：

| 缺陷 | 为什么 mock 测不出 |
|---|---|
| 并发过账 ⇒ 库存加两次 | 缺的是「判断与写入同一条语句 + PG 行锁」这一**运行期**语义。Mockito 里两次 `post` 调用永远顺序执行，`markPosted` 的返回行数也是测试自己 stub 的 ⇒ 判据由被测对象的**替身**决定，与真库行为无关（#5141 的教训同族） |
| 同一导入重跑 ⇒ 建出第二张单 | 幂等键的**原子性**来自部分唯一索引（`ON CONFLICT`/23505 语义）。mock 不施加任何约束 ⇒ 「只落一张单」变成「我说只有一张」 |

⇒ 本文件照 `tests/unit_ci_workflows/test_must_finish_retire_migration.py` 的范式：`initdb` /
`pg_ctl` / `psql` 起**临时集群**真跑（缺 PG 的处置收口在 `pg_cluster.py`（CI 判**红** / 本机显式 skip，issue #5203））。

## 本文件钉的事

| 面 | 判据 |
|---|---|
| 并发过账（真库，两条会话真并发） | CAS 形态：**恰好一个**会话 `claimed=1`、库存**只加一次**、台账**只落一条**、单据 `posted`；且第二个会话**确实阻塞**在行锁上（真重叠，不是顺序跑） |
| 判别力（注入红证） | 同一场景换成**改前形态**（先 `SELECT status` 判 draft 再干活）⇒ **两个会话都干活**：库存加两次、台账两条 —— 证明上一条断言不是恒真 |
| 建单幂等（真库） | 同一 `(tenant_id, import_run_id)` 第二张单被 `uk_inbound_orders_tenant_import_run` 挡下（23505）；应用侧幂等分支的回读（`deleted = 0 AND tenant_id AND import_run_id`）命中既有那张 ⇒ **返回同一张**；**不误伤**：无运行标识的普通建单可建多张、另一租户同键允许 |
| 判别力（注入红证） | 把该索引 DROP 掉再跑同一场景 ⇒ 第二张单**建得进去**（读数 1 → 2）⇒ 「只有一张」不是空断言 |
| 口径一致（真库 + 源码） | 单号唯一索引 = `(tenant_id, inbound_no) WHERE deleted = 0`（**租户内**，与 V111 建表注释逐字一致）；改前同号跨租户被拒 ⇒ 改后允许，同租户仍被拒；`source` CHECK 拒 `gift`（23514）、缺省 `purchase`；列注释与索引口径一致 |
| 过账闸的**源码判据** | CAS 的 SQL 从 `InboundOrderMapper` 的 `@Update` **真源码**里取（不是测试里再抄一份）：谓词丢了 `status = 'draft'` / `tenant_id` / `deleted = 0` ⇒ 本文件当场红 |
| 迁移形态 | V117 已登记进 `migration_fingerprints.json`；显式 `BEGIN/COMMIT`；前置 fail-closed 在写语句之前；两遍真跑幂等；`backend/admin-api/src/main/resources/db/init/schema.sql`（bootstrap 路径不跑迁移链）已同步终态 |
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
import time
from decimal import Decimal
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



V111 = MIGRATION_DIR / "V111__create_inbound_orders_and_batches.sql"
V117 = MIGRATION_DIR / "V117__inbound_order_idempotency_and_source.sql"
MAPPER = REPO / "backend/admin-api/src/main/java/com/migao/admin/mapper/InboundOrderMapper.java"
SCHEMA_SQL = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

TENANT_A = 1
TENANT_B = 2
IMPORT_RUN = "opening-20260924-01"
#: 幂等用例的单号（**不能**撞上夹具里 ord-1 的 RK-20260924-0001：那是「同号」的判据，不是幂等键的）
RUN_NO_A = "RK-20260924-0101"
RUN_NO_NEXT = "RK-20260924-0102"

#: 过账场景的库存/数量读数（红证与通过态共用同一组数字，便于对照）
STOCK_BEFORE = 5
INBOUND_QTY = 30
ORDER_ID = "ord-1"
INBOUND_NO = "RK-20260924-0001"


#: 与 V111（已冻结）同形的**最小** DDL —— 起点是**改前**形态：单号索引是**全局**唯一。
#: 只建本单触碰的表/列（含过账场景要写的库存与台账），不复制整份 schema。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE inbound_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_no VARCHAR(32) NOT NULL,
    supplier VARCHAR(128),
    supplier_doc_no VARCHAR(64),
    warehouse VARCHAR(64),
    inbound_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    total_amount NUMERIC(16,4) NOT NULL DEFAULT 0,
    remark TEXT,
    posted_at TIMESTAMP WITH TIME ZONE,
    posted_by VARCHAR(64),
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancelled_by VARCHAR(64),
    cancelled_reason TEXT,
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);
-- V111 的原始形态：**全局**唯一（本迁移要修的就是它与建表注释「租户内唯一」的矛盾）
CREATE UNIQUE INDEX uk_inbound_orders_no ON inbound_orders (inbound_no);
CREATE TABLE product_skus (
    id BIGINT PRIMARY KEY, tenant_id BIGINT, stock NUMERIC(12,1) NOT NULL DEFAULT 0);
CREATE TABLE stock_ledger_entries (
    id BIGINT PRIMARY KEY, tenant_id BIGINT NOT NULL, product_id VARCHAR(64), sku_id BIGINT,
    delta NUMERIC(12,1) NOT NULL, before_qty NUMERIC(12,1), after_qty NUMERIC(12,1),
    reason VARCHAR(16) NOT NULL, ref_no VARCHAR(64));
-- 并发会话的**读数面**：每个会话把自己抢闸的结果写一行（不靠 psql 的 NOTICE 文案 ——
-- `-q` 会不会吃掉 NOTICE 属实现细节，判据不该建在它上面）
CREATE TABLE posting_attempts (ledger_id INTEGER PRIMARY KEY, outcome TEXT NOT NULL);
"""

_SEED = f"""
INSERT INTO tenants (id) VALUES ({TENANT_A}), ({TENANT_B});
INSERT INTO product_skus (id, tenant_id, stock) VALUES (11, {TENANT_A}, {STOCK_BEFORE});
INSERT INTO inbound_orders (id, tenant_id, inbound_no, status) VALUES
    ('{ORDER_ID}', {TENANT_A}, '{INBOUND_NO}', 'draft');
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释 → 空（供**写语句**判据用）。

    ⚠️ 必须去注释：本仓迁移把「回滚 SQL」写在注释里（V117 的回滚段里就有 `DROP INDEX` /
    `CREATE UNIQUE INDEX`），不去注释会把注释里的语句当成真写语句（#4595 的同族教训）。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


# ══════════════════════════ ① 过账闸：SQL 从**真源码**取（判据不许自说自话） ══════════════════════════

def _cas_sql_from_mapper() -> str:
    """从 `InboundOrderMapper` 的 `@Update` 里取过账 CAS 的 SQL（Java 字符串拼接 → 拼成一条）。

    为什么读源码而不是在测试里重写一条：测试里再抄一份时，源码把闸改宽/删掉**本文件照样全绿**
    —— 判据就成了自说自话（本仓 #4689 的同族教训）。
    """
    src = _read(MAPPER)
    m = re.search(r"@Update\((.*?)\)\s*\n\s*int\s+markPosted", src, re.S)
    assert m, "InboundOrderMapper 里找不到 markPosted 的 @Update —— 过账原子闸的载体变了"
    chunks = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    assert chunks, "markPosted 的 @Update 里没有 SQL 字面量"
    sql = re.sub(r"\s+", " ", " ".join(chunks)).strip()
    # 源码侧的闸判据：谓词必须是「仍是草稿」+ 租户限定 + 未软删，且写入状态与留痕同句
    assert re.search(r"status\s*=\s*'draft'", sql), f"CAS 丢了 `status = 'draft'` 谓词（闸失效）：{sql}"
    assert re.search(r"status\s*=\s*'posted'", sql), f"CAS 没把状态写成 posted：{sql}"
    assert "tenant_id = #{tenantId}" in sql, f"CAS 丢了租户限定：{sql}"
    assert "deleted = 0" in sql, f"CAS 丢了 deleted = 0（软删的单不得过账）：{sql}"
    assert "posted_by = #{operator}" in sql and "posted_at = #{postedAt}" in sql, (
        f"CAS 没有把「谁在何时过账」与状态写在同一句里：{sql}")
    return sql


def _cas_sql_executable(order_id: str = ORDER_ID, tenant_id: int = TENANT_A) -> str:
    """把 MyBatis 的 `#{…}` 占位换成真值（真库判据要能直接执行）。"""
    return (_cas_sql_from_mapper()
            .replace("#{postedAt}", "NOW()")
            .replace("#{operator}", "'op'")
            .replace("#{tenantId}", str(tenant_id))
            .replace("#{id}", f"'{order_id}'")
            .rstrip()
            .rstrip(";"))


#: 一个会话的过账脚本：**闸 → 加库存 → 落台账**（顺序与 `InboundOrderService.post` 一致）。
#: `__SLEEP__` 用来**持有行锁**制造真并发重叠（不然两个会话一前一后跑，等于没测并发）。
_CAS_SESSION = """
BEGIN;
DO $do$
DECLARE claimed INTEGER;
BEGIN
    __GATE__;
    GET DIAGNOSTICS claimed = ROW_COUNT;
    INSERT INTO posting_attempts (ledger_id, outcome) VALUES (__LEDGER_ID__, 'claimed=' || claimed);
    IF claimed = 1 THEN
        UPDATE product_skus SET stock = stock + __QTY__ WHERE id = 11;
        INSERT INTO stock_ledger_entries (id, tenant_id, product_id, sku_id, delta, reason, ref_no)
            VALUES (__LEDGER_ID__, __TENANT__, 'prod-1', 11, __QTY__, 'inbound', '__INBOUND_NO__');
        __SLEEP__
    END IF;
END $do$;
COMMIT;
"""

#: **改前形态**（红证用）：先 `SELECT status` 判 draft，再干活。
#: 事务外看不见对方未提交的写入（READ COMMITTED）⇒ 两个会话**都**看到 `draft` ⇒ 各加一遍库存。
_LEGACY_SESSION = """
BEGIN;
DO $do$
DECLARE st TEXT;
BEGIN
    SELECT status INTO st FROM inbound_orders
     WHERE id = '__ORDER_ID__' AND tenant_id = __TENANT__ AND deleted = 0;
    INSERT INTO posting_attempts (ledger_id, outcome) VALUES (__LEDGER_ID__, 'st=' || st);
    IF st = 'draft' THEN
        UPDATE product_skus SET stock = stock + __QTY__ WHERE id = 11;
        INSERT INTO stock_ledger_entries (id, tenant_id, product_id, sku_id, delta, reason, ref_no)
            VALUES (__LEDGER_ID__, __TENANT__, 'prod-1', 11, __QTY__, 'inbound', '__INBOUND_NO__');
        __SLEEP__
    END IF;
END $do$;
COMMIT;
"""


def _session_sql(template: str, ledger_id: int, sleep_seconds: float) -> str:
    sql = (template
           .replace("__GATE__", _cas_sql_executable())
           .replace("__ORDER_ID__", ORDER_ID)
           .replace("__TENANT__", str(TENANT_A))
           .replace("__QTY__", str(INBOUND_QTY))
           .replace("__LEDGER_ID__", str(ledger_id))
           .replace("__INBOUND_NO__", INBOUND_NO))
    sleep = f"PERFORM pg_sleep({sleep_seconds});" if sleep_seconds else ""
    return sql.replace("__SLEEP__", sleep)


# ══════════════════════════ ② 真库夹具（临时 PG 集群） ══════════════════════════

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg5148-"))
    log = tmp_path / "pg.log"
    port = _free_port()
    # 起集群的**唯一实现**（失败 / 中止路径也停库 —— issue #5263 判据①）
    pg_cluster.start_cluster(realdb_binaries, datadir, sockdir=sockdir, port=port, log=log)

    argv = [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
            "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"]
    scripts: list[Path] = []

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「**确实**失败」）。"""
        return subprocess.run(argv, input=sql, text=True, capture_output=True)

    def popen(sql: str):
        """并发会话入口：脚本落文件用 `psql -f` 跑（不碰 stdin，避免半关闭的坑）。"""
        f = tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False, encoding="utf-8")
        f.write(sql)
        f.close()
        scripts.append(Path(f.name))
        return subprocess.Popen(argv + ["-f", f.name],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    run.raw = psql_raw
    run.popen = popen
    try:
        yield run
    finally:
        pg_cluster.stop_cluster(realdb_binaries["pg_ctl"], datadir)
        shutil.rmtree(sockdir, ignore_errors=True)
        for script in scripts:
            script.unlink(missing_ok=True)


def _as_runner_would(sql: str) -> str:
    """把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。

    ⚠️ 文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
    `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
    """
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _migrate(psql) -> None:
    """灌入改前形态 + 过账场景夹具，再真跑 V117。"""
    psql(_DDL + _SEED)
    psql(_as_runner_would(_read(V117)))


def _readings(psql) -> dict:
    """并发过账的三条读数：库存 / 台账条数 / 单据状态。"""
    return {
        "stock": psql("SELECT stock::text FROM product_skus WHERE id = 11;").strip(),
        "ledger_rows": psql("SELECT count(*) FROM stock_ledger_entries "
                            f"WHERE ref_no = '{INBOUND_NO}';").strip(),
        "status": psql(f"SELECT status FROM inbound_orders WHERE id = '{ORDER_ID}';").strip(),
    }


def _run_two_sessions(psql, template: str, *, hold_seconds: float = 1.0, gap: float = 0.15):
    """两个会话真并发跑同一段过账脚本；返回 (读数, 各会话自报的抢闸结果, 第二个会话等待秒数)。

    ⚠️ 第一个会话用 `pg_sleep` **持有行锁** `hold_seconds` 秒，第二个会话在 `gap` 秒后启动
    ⇒ 两者的执行窗口**必然重叠**（否则「并发」只是顺序跑两遍，测不出任何东西）。
    """
    proc_a = psql.popen(_session_sql(template, ledger_id=101, sleep_seconds=hold_seconds))
    time.sleep(gap)
    proc_b = psql.popen(_session_sql(template, ledger_id=102, sleep_seconds=0.0))
    started = time.time()
    out_b, err_b = proc_b.communicate(timeout=60)
    elapsed_b = time.time() - started
    out_a, err_a = proc_a.communicate(timeout=60)
    assert proc_a.returncode == 0, f"会话 A 失败：{out_a}\n{err_a}"
    assert proc_b.returncode == 0, f"会话 B 失败：{out_b}\n{err_b}"
    assert elapsed_b > 0.3, (
        f"会话 B 只用了 {elapsed_b:.2f}s ⇒ 两个会话没有真正重叠（B 在 A 提交后才开始）"
        f"—— 本判据会退化成「顺序跑两遍」，什么也测不出")
    outcomes = psql("SELECT ledger_id::text || '=' || outcome FROM posting_attempts "
                    "ORDER BY ledger_id;").strip().splitlines()
    return _readings(psql), outcomes, elapsed_b


# ══════════════════════════ ③ 并发过账（判据 + 注入式红证） ══════════════════════════

def test_concurrent_posting_adds_stock_exactly_once(psql):
    """**核心判据**：两个并发 `post` ⇒ 恰好一个抢到过账权、库存只加一次、台账只落一条。"""
    _migrate(psql)
    readings, outcomes, elapsed_b = _run_two_sessions(psql, _CAS_SESSION)

    winners = sum(1 for o in outcomes if o.endswith("claimed=1"))
    losers = sum(1 for o in outcomes if o.endswith("claimed=0"))
    print(f"[#5148 真库 · CAS] 两会话自报 = {outcomes}（抢到闸 {winners} 个 / 被挡 {losers} 个）")
    print(f"[#5148 真库 · CAS] 库存 {STOCK_BEFORE} → {readings['stock']}（入库 {INBOUND_QTY}）")
    print(f"[#5148 真库 · CAS] 台账条数 = {readings['ledger_rows']}；单据状态 = {readings['status']}")
    print(f"[#5148 真库 · CAS] 第二个会话阻塞 {elapsed_b:.2f}s（证明两个会话真的重叠）")

    assert winners == 1, f"抢到过账权的会话有 {winners} 个（必须恰好 1 个）：{outcomes}"
    assert losers == 1, f"应有一个会话被闸挡住（实际 {losers} 个）：{outcomes}"
    assert Decimal(readings["stock"]) == Decimal(STOCK_BEFORE + INBOUND_QTY), (
        f"库存读数 = {readings['stock']}（并发过账把库存加了不止一次）")
    assert readings["ledger_rows"] == "1", f"台账落了 {readings['ledger_rows']} 条（应恰好 1 条）"
    assert readings["status"] == "posted", f"单据状态 = {readings['status']}"


def test_injected_legacy_shape_double_adds_stock(psql):
    """**注入式红证**：换成改前形态（先 `SELECT status` 判 draft 再干活）⇒ 两个会话**都**干活。

    这条不是「顺手再测一遍」，它是上一条的**判别力证明**：若夹具/断言恒真（例如两个会话从不重叠、
    或行锁逻辑根本没生效），这里也会「只加一次」—— 读数出现 **+2 倍** 才说明上一条真的测到了闸。
    """
    _migrate(psql)
    readings, outcomes, elapsed_b = _run_two_sessions(psql, _LEGACY_SESSION)

    saw_draft = sum(1 for o in outcomes if o.endswith("st=draft"))
    print(f"[#5148 真库 · 红证] 改前形态：两会话自报 = {outcomes}（都读到 draft 的有 {saw_draft} 个）")
    print(f"[#5148 真库 · 红证] 库存 → {readings['stock']}；台账 {readings['ledger_rows']} 条；"
          f"第二个会话阻塞 {elapsed_b:.2f}s")
    assert saw_draft == 2, (
        f"改前形态下应有两个会话都读到 draft（实际 {saw_draft}）—— 红证前提不成立：{outcomes}")
    assert Decimal(readings["stock"]) == Decimal(STOCK_BEFORE + 2 * INBOUND_QTY), (
        f"改前形态下库存应被加**两次**（{STOCK_BEFORE + 2 * INBOUND_QTY}），实际 {readings['stock']}"
        f" —— 那么上一条「只加一次」可能是恒真（空断言）")
    assert readings["ledger_rows"] == "2", (
        f"改前形态下台账应落 2 条，实际 {readings['ledger_rows']} —— 判别力不足")


def test_cas_source_text_keeps_the_gate_predicates():
    """闸的**源码判据**：CAS 的谓词必须仍在（丢了它 = 闸失效，而真库那两条判据仍会绿）。"""
    sql = _cas_sql_from_mapper()
    print(f"[#5148 源码] markPosted = {sql}")
    assert "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'draft' AND deleted = 0" in sql, (
        f"CAS 的 WHERE 子句形态变了（闸的判据就是它）：{sql}")


# ══════════════════════════ ④ 建单幂等（判据 + 注入式红证） ══════════════════════════

def _order_row(order_id: str, inbound_no: str, tenant_id: int, run_id: str | None) -> str:
    """建单行。⚠️ `run_id=None` 时**不写** `source` / `import_run_id` 两列 —— 这样同一句 SQL
    在 V117 之前（两列还不存在）也跑得通（「改前 vs 改后」的对照才成立），
    且顺带验证了缺省来源 = `purchase`（与 V117 的 `NOT NULL DEFAULT 'purchase'` 同口径）。
    """
    cols = "(id, tenant_id, inbound_no, status"
    vals = f"('{order_id}', {tenant_id}, '{inbound_no}', 'draft'"
    if run_id is not None:
        cols += ", source, import_run_id"
        vals += f", 'opening', '{run_id}'"
    return f"INSERT INTO inbound_orders {cols}) VALUES {vals});"


def test_same_import_run_never_creates_a_second_order(psql):
    """**核心判据**：同一 `(tenant_id, import_run_id)` 重跑 ⇒ 回读命中既有那张；第二张插不进去。"""
    _migrate(psql)
    psql(_order_row("o1", RUN_NO_A, TENANT_A, IMPORT_RUN))

    # 应用侧幂等分支的判据形状（`@TableLogic` ⇒ 查询一律带 deleted = 0）
    replayed = psql("SELECT id || '|' || inbound_no FROM inbound_orders "
                    f"WHERE deleted = 0 AND tenant_id = {TENANT_A} AND import_run_id = '{IMPORT_RUN}';").strip()
    assert replayed == f"o1|{RUN_NO_A}", (
        f"重跑建单没命中既有单据（幂等分支会退化成「又建一张」）：{replayed}")

    # 就算应用不查直接插，唯一索引也挡下（原子的那道保证）
    dup = psql.raw(_order_row("o2", RUN_NO_NEXT, TENANT_A, IMPORT_RUN))
    count = psql("SELECT count(*) FROM inbound_orders "
                 f"WHERE tenant_id = {TENANT_A} AND import_run_id = '{IMPORT_RUN}';").strip()
    print(f"[#5148 真库 · 幂等] 同运行第二张单：退出码 = {dup.returncode}；"
          f"stderr 含索引名 = {'uk_inbound_orders_tenant_import_run' in dup.stderr}；同键单据数 = {count}")
    assert dup.returncode != 0, "同一运行标识竟然建出了第二张单（重跑导入 ⇒ 库存会加两次）"
    assert "uk_inbound_orders_tenant_import_run" in dup.stderr, (
        f"拦下它的不是幂等索引：{dup.stderr[:300]}")
    assert count == "1", f"同一运行的单据数 = {count}（必须恰好 1）"

    # 不误伤：**不带**运行标识的普通建单不受影响（部分索引谓词 import_run_id IS NOT NULL）
    psql(_order_row("o3", "RK-20260924-0201", TENANT_A, None))
    psql(_order_row("o4", "RK-20260924-0202", TENANT_A, None))
    manual = psql(f"SELECT string_agg(id, ',' ORDER BY id) FROM inbound_orders "
                  f"WHERE tenant_id = {TENANT_A} AND import_run_id IS NULL;").strip()
    # 租户维度：另一个租户用同一个运行标识是允许的（索引是 (tenant_id, import_run_id)）
    psql(_order_row("o5", RUN_NO_A, TENANT_B, IMPORT_RUN))
    other = psql(f"SELECT count(*) FROM inbound_orders WHERE tenant_id = {TENANT_B};").strip()
    print(f"[#5148 真库 · 幂等] 无运行标识的普通建单 = [{manual}]（可并存，含夹具里的 ord-1）；"
          f"另一租户同键 = {other} 张")
    assert manual == "o3,o4,ord-1", (
        f"普通建单被误伤（部分索引谓词漏了 import_run_id IS NOT NULL）：{manual}")
    assert other == "1", f"另一租户同键建单被误伤（索引漏了 tenant_id）：{other}"


def test_injected_missing_index_would_allow_the_second_order(psql):
    """**注入式红证**：把幂等索引 DROP 掉 ⇒ 第二张单建得进去（读数 1 → 2）。

    证明上一条「同一运行只有一张」不是空断言（例如「第二张本来就插不进」这种恒真）。
    """
    _migrate(psql)
    psql("DROP INDEX uk_inbound_orders_tenant_import_run;")
    psql(_order_row("o1", RUN_NO_A, TENANT_A, IMPORT_RUN))
    psql(_order_row("o2", "RK-20260924-0002", TENANT_A, IMPORT_RUN))
    count = psql("SELECT count(*) FROM inbound_orders "
                 f"WHERE tenant_id = {TENANT_A} AND import_run_id = '{IMPORT_RUN}';").strip()
    print(f"[#5148 真库 · 红证] 去掉幂等索引后同键单据数 = {count}（正常口径应为 1）")
    assert count == "2", (
        f"没有索引也建不出第二张（读数 {count}）⇒ 上一条断言没有判别力（空断言）")


# ══════════════════════════ ⑤ 口径一致：单号索引范围 + source 取值 + 注释 ══════════════════════════

def test_number_index_scope_matches_the_comment(psql):
    """**核心判据（口径一致）**：索引范围 = 租户内，与 V111 建表注释逐字一致（改前是全局唯一 ⇒ 对不上）。"""
    psql(_DDL + _SEED)
    # 改前：全局唯一 ⇒ 另一个租户用同一个单号会被拒（这正是与注释矛盾之处）
    before = psql.raw(_order_row("b1", INBOUND_NO, TENANT_B, None))
    print(f"[#5148 真库 · 口径] 改前：另一租户用同一单号 ⇒ 退出码 = {before.returncode}；"
          f"报的是 uk_inbound_orders_no = {'uk_inbound_orders_no' in before.stderr}")
    assert before.returncode != 0 and "uk_inbound_orders_no" in before.stderr, (
        f"红证前提不成立：改前单号索引应是**全局**唯一（另一租户同号会被拒）：{before.stderr[:300]}")

    psql(_as_runner_would(_read(V117)))

    # 改后：租户内唯一 —— 跨租户同号允许、同租户同号仍拒
    psql(_order_row("b1", INBOUND_NO, TENANT_B, None))
    same_tenant = psql.raw(_order_row("a2", INBOUND_NO, TENANT_A, None))
    indexdef = psql("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
                    "AND tablename = 'inbound_orders' AND indexname = 'uk_inbound_orders_no';").strip()
    col_comment = psql("SELECT col_description('inbound_orders'::regclass, attnum) "
                       "FROM pg_attribute WHERE attrelid = 'inbound_orders'::regclass "
                       "AND attname = 'inbound_no';").strip()
    v111_comment = "租户内唯一" in _read(V111)
    print(f"[#5148 真库 · 口径] 改后索引 = {indexdef}")
    print(f"[#5148 真库 · 口径] 同租户重号 ⇒ 退出码 = {same_tenant.returncode}"
          f"（报的是 uk_inbound_orders_no = {'uk_inbound_orders_no' in same_tenant.stderr}）；跨租户同号已放行")
    print(f"[#5148 真库 · 口径] 列注释含「租户内唯一」= {'租户内唯一' in col_comment}；"
          f"V111 冻结注释亦写「租户内唯一」= {v111_comment}")

    assert "(tenant_id, inbound_no)" in indexdef and "deleted = 0" in indexdef, (
        f"单号唯一索引不是租户内（口径仍与注释矛盾）：{indexdef}")
    assert same_tenant.returncode != 0 and "uk_inbound_orders_no" in same_tenant.stderr, (
        f"同租户内重号竟被放行 ⇒ 防重号失效：{same_tenant.stderr[:300]}")
    assert "租户内唯一" in col_comment, f"列注释没有跟着改成租户内唯一：{col_comment}"
    assert v111_comment, "V111 的建表注释里没有「租户内唯一」（本迁移的统一方向就不是它了）"


def test_source_check_constraint_and_default(psql):
    """`source` 取值约束在场：写别的值当场 23514；不给值 ⇒ 缺省 `purchase`（存量口径）。"""
    _migrate(psql)
    bad = psql.raw("INSERT INTO inbound_orders (id, tenant_id, inbound_no, source) "
                   "VALUES ('s-bad', 1, 'RK-20260924-9001', 'gift');")
    psql("INSERT INTO inbound_orders (id, tenant_id, inbound_no) "
         "VALUES ('s-default', 1, 'RK-20260924-9002');")
    default_source = psql("SELECT source FROM inbound_orders WHERE id = 's-default';").strip()
    print(f"[#5148 真库 · source] 写 'gift' ⇒ 退出码 = {bad.returncode}；"
          f"stderr 含 ck_inbound_orders_source = {'ck_inbound_orders_source' in bad.stderr}；"
          f"缺省值 = {default_source}")
    assert bad.returncode != 0, f"source 取值约束没生效（写 'gift' 竟能落库）：{bad.stderr[:300]}"
    assert "ck_inbound_orders_source" in bad.stderr, f"拦下它的不是取值约束：{bad.stderr[:300]}"
    assert default_source == "purchase", f"缺省来源 = {default_source}（存量口径应为 purchase）"


# ══════════════════════════ ⑥ 迁移形态 / 账本 / bootstrap 镜像 ══════════════════════════

def test_v117_exists_and_is_the_unique_highest_version():
    assert V117.exists(), f"缺少迁移文件：{V117.name}"
    versions = [int(re.match(r"^V(\d+)__", p.name).group(1))
                for p in _migration_files("V*.sql") if re.match(r"^V(\d+)__", p.name)]
    assert versions.count(117) == 1, "V117 版本号重复"
    assert max(versions) >= 117, f"V117 不是最高版本号（当前最大 V{max(versions)}）"


def test_v117_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏（issue #4235）：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert V117.name in ledger, (
        f"`{V117.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_v117_is_explicitly_transactional_and_fails_closed_before_writing():
    body = _read(V117)
    assert re.search(r"^BEGIN;", body, re.M), "V117 缺显式 `BEGIN;`（psql -f 默认逐条 autocommit ⇒ 半完成态）"
    assert re.search(r"^COMMIT;", body, re.M), "V117 缺显式 `COMMIT;`"
    code = _strip_comments(body)
    first_write = min(code.index(k) for k in ("DROP INDEX", "ALTER TABLE", "CREATE UNIQUE INDEX"))
    assert code.index("RAISE EXCEPTION") < first_write, (
        "前置 fail-closed 判据排在写语句之后（缺表时会先改一半再抛）")
    assert "终态对账" in body, "V117 缺终态对账（判据漂移的停止条件）"


def test_v117_is_idempotent_on_a_real_database(psql):
    """两遍真跑：第二遍不报错、终态与数据都不变（`MigrationRunner` 要求所有迁移可重复执行）。"""
    psql(_DDL + _SEED)
    psql(_as_runner_would(_read(V117)))
    first = psql("SELECT indexdef FROM pg_indexes WHERE indexname = 'uk_inbound_orders_no';").strip()
    rows_first = psql("SELECT count(*) FROM inbound_orders;").strip()
    cols_first = psql("SELECT count(*) FROM information_schema.columns "
                      "WHERE table_name = 'inbound_orders';").strip()

    psql(_as_runner_would(_read(V117)))                 # 第二遍（幂等）

    assert psql("SELECT indexdef FROM pg_indexes WHERE indexname = 'uk_inbound_orders_no';").strip() == first
    assert psql("SELECT count(*) FROM inbound_orders;").strip() == rows_first, "第二遍动了行"
    assert psql("SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'inbound_orders';").strip() == cols_first, "第二遍增删了列"


def test_bootstrap_schema_sql_is_already_terminal():
    """bootstrap 路径（新建库**不跑迁移链**）必须与 V117 终态同形，否则新库与老库行为分叉。"""
    schema = _read(SCHEMA_SQL)
    assert re.search(r"uk_inbound_orders_no\s*\n?\s*ON inbound_orders \(tenant_id, inbound_no\)",
                     schema), "schema.sql 的单号唯一索引不是租户内口径（仍是全局唯一）"
    assert "uk_inbound_orders_tenant_import_run" in schema, "schema.sql 缺幂等键的部分唯一索引"
    assert re.search(r"import_run_id\s+VARCHAR\(128\)", schema), "schema.sql 缺 import_run_id 列"
    assert re.search(r"source\s+VARCHAR\(16\)\s+NOT NULL DEFAULT 'purchase'", schema), (
        "schema.sql 缺 source 列（或丢了 NOT NULL + 缺省值）")
    assert "source IN ('purchase', 'opening')" in schema, "schema.sql 缺 source 取值约束"
