# case_ids: PP-002, PG-040, PG-042
"""「接高」撤出加工项目录项（issue #5230）的承重判据 + 真库两遍幂等 + **存量不静默变价**。

（用户裁定 2026-09-23 原文：「**接高同接宽一样，都不要进加工项，但是会派生出拼接加工项**」；
同日 v2 收窄：「**移除接宽逻辑，接高在特殊选项中选择，但是仍然得自动推导**」⇒ 本单只撤「加工项目录项」
这一条通路，保留特殊选项那条（#5211），`接宽` 不建任何出口。）

## 本文件钉的事

| 面 | 判据 |
|---|---|
| 形态（静态） | 显式 `BEGIN;/COMMIT;`；可执行语句**只写** `processing_items` 的 `deleted` / `status` / `updated_at` 三列；谓词逐字含 `name = '接高'` + `deleted = 0`；**不碰**任何「价」与快照表；文件里不出现工序种子发现关键字（`INSERT INTO production_operations` / `VALUES`） |
| 真库（临时 PG） | 两遍真跑：第二遍净效果相同（存活行 `updated_at` 逐字不变）；**两个租户**的 `接高` 都退场、其它项一字不动；**已软删的同名行不被复活也不被改**（证明谓词带 `deleted = 0`）；`processing_fee_combinations` 指纹逐字节不变（**不改钱**）；`production_route_rules` 指纹逐字节不变（**不追溯存量单**） |
| 存量影响（判据 7） | 含 `接高` 的**活跃**组合在撤出后**仍在**（status / 价 / 键都不变）⇒「不得静默变价」= 迁移**自己不动钱**；「受影响的组合」由迁移头注释里登记的**可机械复算查询**给出，本文件在真库上逐行核它 |
| 判别力（注入红证） | ① 谓词写成 `name = '拼接'` ⇒ 迁移自带的终态对账当场抛并整份回滚（证明「不得误撤其它项」不是空断言）；② 抹掉 UPDATE（只留对账）⇒ 对账照样抛（证明它抓得住「没写/漏写」） |

## 为什么必须真跑

`MigrationRunner` 要求**所有**迁移可重复执行，而「幂等」只有真库能判：`UPDATE` 的谓词与 `NULL` /
`deleted` 的交互、`DO $$ … $$` 里 `RAISE EXCEPTION` 的回滚半径、单文件多语句在同一事务里的原子性
—— 三者都是**运行期**语义（V83 的静态守卫全绿而真库整份回滚，同族）。

## 真库判据（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

照 `tests/unit_ci_workflows/test_must_finish_retire_migration.py` 的范式（`initdb` / `pg_ctl` / `psql`
起临时集群真跑）。**权威仍在 CI**：本文件只是把「迁移在真库上的终态」变成可本地复算的读数。
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
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
V123 = MIGRATION_DIR / "V123__retire_join_height_processing_item.sql"

ITEM_TABLE = "processing_items"
RETIRED_NAME = "接高"
KEPT_NAME = "拼接"

#: **红线**：本迁移一字不许写的表（价 / 工序 / 规则 / 快照 —— 见迁移头注释的「红线」段）
RED_LINE_TABLES = (
    "processing_fee_combinations",      # 对客组合价（撤目录项 ≠ 改钱）
    "production_route_rules",           # 含 V84 的 `processing_item 接高` 规则（存量单照旧插工序）
    "production_operations",            # `接高-布` 工序行是特殊选项通路的承重件
    "production_operation_positions",   # 部位价目矩阵
    "processing_orders",                # 加工单快照
    "processing_position_operations",   # 工序实例快照
    "production_work_logs",             # 报工流水（历史工资）
)

#: 迁移头注释里**登记的**「受影响组合」查询（只读；商家 / 运维可原样执行）。
#: ⚠️ 本文件与迁移头**必须逐字同源**（改了源就改这里，否则「登记了」与「可复算」脱钩）——
#: 由 `test_registered_query_matches_migration_header` 钉住。
AFFECTED_COMBOS_QUERY = """SELECT c.tenant_id, c.id, c.composition_key, c.unit_price, c.status
  FROM processing_fee_combinations c
 WHERE c.deleted = 0
   AND c.status = 'active'
   AND c.items @> '["接高"]'::jsonb
 ORDER BY c.tenant_id, c.id;"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释与 `/* */` 块注释（判据读**可执行**语句，不读解释性文字）。"""
    without_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return "\n".join(re.sub(r"--.*$", "", line) for line in without_block.splitlines())


# ══════════════════════════ ① 静态形态判据 ══════════════════════════


def test_migration_file_exists_and_is_the_next_version():
    assert V123.exists(), f"缺少撤出迁移：{V123.name}"
    versions = sorted(
        int(m.group(1))
        for p in MIGRATION_DIR.glob("V*.sql")
        if (m := re.match(r"V(\d+)__", p.name))
    )
    assert versions[-1] == 123, f"V123 不是最新迁移（实测最大 = V{versions[-1]}）—— 合并前先 rebase 核对版本号"


def test_explicit_transaction_and_columns():
    body = _strip_comments(_read(V123))
    assert re.search(r"^\s*BEGIN\s*;", body, re.M | re.I), "缺少显式 BEGIN;"
    assert re.search(r"^\s*COMMIT\s*;", body, re.M | re.I), "缺少显式 COMMIT;"
    assert re.search(
        r"UPDATE\s+processing_items\s+SET\s+deleted\s*=\s*1\s*,\s*status\s*=\s*'disabled'\s*,\s*updated_at\s*=\s*NOW\(\)",
        body, re.I | re.S), "SET 子句不是「显式逐列写全」的形态（deleted / status / updated_at）"
    assert f"name = '{RETIRED_NAME}'" in body, "谓词没有点名要撤出的目录项名"
    assert re.search(r"deleted\s*=\s*0", body), "谓词丢了 `deleted = 0`（幂等闸 + 不复活已软删行）"


def test_only_the_catalog_item_table_is_written():
    """红线：本迁移只许 UPDATE `processing_items`，不许碰任何「价」与快照表。"""
    body = _strip_comments(_read(V123))
    offenders = {
        table: re.findall(
            rf"\b(UPDATE|INSERT\s+INTO|DELETE\s+FROM|ALTER\s+TABLE|TRUNCATE)\s+{table}\b",
            body, re.I)
        for table in RED_LINE_TABLES
    }
    offenders = {table: hits for table, hits in offenders.items() if hits}
    assert offenders == {}, (
        f"V123 触碰了红线表（撤目录项 ≠ 改钱 / ≠ 改规则 / ≠ 追溯快照）：{offenders} —— "
        "见迁移头注释的「红线」段")
    writes = set(re.findall(r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM|ALTER\s+TABLE)\s+(\w+)", body, re.I))
    assert writes == {ITEM_TABLE}, f"V123 的写语句落在非预期表上：{sorted(writes)}"
    # 没有 UPDATE 之外的结构改动（列/表都不删）
    assert not re.search(r"\bDROP\b", body, re.I), "V123 出现了 DROP —— 本迁移只软删行"


def test_no_seed_discovery_keywords():
    """防「被工序种子发现器误认成种子源」（V107 同款自证）。"""
    body = _strip_comments(_read(V123))
    assert "INSERT INTO production_operations" not in body
    assert not re.search(r"\bVALUES\b", body, re.I), "可执行语句里出现了行值构造关键字"
    assert not re.search(r"\bWITH\s+\w+\s+AS\s*\(", body, re.I), "V123 用了 CTE（本仓迁移不使用）"


def test_registered_query_matches_migration_header():
    """「影响面可机械复算」= 迁移头里登记的那条查询 == 本文件在真库上核的那条（逐字同源）。"""
    header = _read(V123)
    needle = AFFECTED_COMBOS_QUERY.splitlines()[0]
    assert needle in header, "迁移头注释里没有登记「受影响组合」查询 —— 影响因素不可复算"
    for line in AFFECTED_COMBOS_QUERY.splitlines():
        assert line.strip() in header, f"登记查询与本文件的副本漂移（缺行：{line.strip()}）"


def test_red_line_detector_has_teeth():
    """注入式自证：塞一条写红线表的语句 ⇒ 检测器必须读得出来（否则上面那条是空跑）。"""
    injected = "BEGIN;\nUPDATE processing_fee_combinations SET unit_price = 0 WHERE deleted = 0;\nCOMMIT;\n"
    hits = re.findall(r"\b(UPDATE)\s+processing_fee_combinations\b", _strip_comments(injected), re.I)
    assert hits, "红线检测器读不出注入的写语句 ⇒ 判据是空跑"


# ══════════════════════════ ② 真库判据（临时 PG 集群） ══════════════════════════
# ⚠️ 「缺 PG 怎么办」**不在本文件判**（issue #5203 收口）：一律经 `conftest.py::realdb_binaries`
#    （session 级夹具 ⇒ `pg_cluster.require_pg()`：CI 带 `MIGAO_REQUIRE_REALDB` ⇒ **判红** /
#     本机 ⇒ 显式 skip），argv **必须用它给的绝对路径**（runner 的 PG 在
#     `/usr/lib/postgresql/16/bin`，**不在 PATH** ⇒ 按裸名调用必 `FileNotFoundError`）。
#    本模块已登记进 `pg_cluster.REALDB_TEST_MODULES`（判据⑤的冻结表）。

#: 与 `docs/sql/schema.sql` / V83 同形的**最小** DDL（本迁移触碰的表 + 红线表）。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE processing_items (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_processing_items_tenant_name
    ON processing_items (tenant_id, name) WHERE deleted = 0;
CREATE TABLE processing_fee_combinations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    composition_key VARCHAR(256) NOT NULL, items JSONB NOT NULL DEFAULT '[]',
    unit_price DECIMAL(10,2) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_route_rules (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(32) NOT NULL, trigger_value VARCHAR(64) NOT NULL,
    action VARCHAR(16) NOT NULL, operation VARCHAR(64), after_operation VARCHAR(64),
    customer_unit_price DECIMAL(12,2),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
"""

#: 真库形态的种子（覆盖四条边界）：
#:   · **1 号租户**：`接高`（必须退场）+ `拼接`/`定型`/`超高`（一字不动）；
#:   · **2 号租户**：`接高`（证明「不按租户循环」也覆盖非 1 号租户）+ `拼接`；
#:   · **已软删的同名行**：`deleted = 1` 且 `status = 'active'`（留痕形态）⇒ 本迁移**不许动它**
#:     （谓词一旦丢 `deleted = 0`，它的 `status` 会被翻成 `disabled` ⇒ 该断言当场红）；
#:   · 组合 / 规则：撤出前后的**指纹**必须逐字节相同（不改钱、不追溯存量单）。
_SEED = """
INSERT INTO tenants (id) VALUES (1), (2);
INSERT INTO processing_items (id, tenant_id, name, status, deleted) VALUES
    ('pi-v83-1-09', 1, '接高', 'active', 0),
    ('pi-v83-1-10', 1, '拼接', 'active', 0),
    ('pi-v83-1-06', 1, '定型', 'active', 0),
    ('pi-v83-1-14', 1, '超高', 'active', 0),
    ('pi-v83-2-09', 2, '接高', 'active', 0),
    ('pi-v83-2-10', 2, '拼接', 'active', 0),
    ('pi-v83-1-99', 1, '接高', 'active', 1);
INSERT INTO processing_fee_combinations
    (id, tenant_id, composition_key, items, unit_price, status, deleted) VALUES
    ('c-1-keep',    1, '定型+接高+韩折', '["韩折","接高","定型"]'::jsonb, 5.00, 'active',   0),
    ('c-1-cheaper', 1, '定型+韩折',      '["韩折","定型"]'::jsonb,      3.00, 'active',   0),
    ('c-1-disabled',1, '接高',           '["接高"]'::jsonb,             9.00, 'disabled', 0),
    ('c-2-keep',    2, '拼接+接高',      '["接高","拼接"]'::jsonb,      4.00, 'active',   0);
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, action, operation, after_operation, customer_unit_price) VALUES
    ('rr-v84-1-03', 1, 'processing_item', '接高', 'insert', '接高', '精裁', NULL),
    ('opt-rt-06',   1, 'option',          '接高', 'insert', '接高', '精裁', 2.50);
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。

    ⚠️ 二进制一律取 `realdb_binaries[...]` 的**绝对路径**（见本段头注释）。
    """
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg5230-"))
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

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres",
             "-d", "postgres", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    run.raw = psql_raw
    try:
        yield run
    finally:
        subprocess.run([realdb_binaries["pg_ctl"], "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


def _as_runner_would(sql: str) -> str:
    """把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。

    ⚠️ 文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
    `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
    """
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _fingerprint(run, table: str) -> str:
    """表内容指纹（按 id 排序逐行拼接**全部业务列**）—— 用来判「一字不动」。"""
    return run(
        f"SELECT coalesce(string_agg(t::text, E'\\n' ORDER BY t::text), '') "
        f"FROM {table} t;")


def _items(run) -> str:
    return run(
        "SELECT coalesce(string_agg("
        "id || '|' || name || '|' || status || '|' || deleted || '|' || updated_at, "
        "E'\\n' ORDER BY id), '') FROM processing_items;")


@pytest.fixture
def seeded(psql):
    psql(_DDL + _SEED)
    return psql


def test_real_db_retires_every_tenant_and_touches_nothing_else(seeded):
    """判据 7 前半：撤出**只**撤「接高」，两个租户都覆盖，其它项与「价 / 规则」一字不动。"""
    run = seeded
    items_before = _items(run)
    combos_before = _fingerprint(run, "processing_fee_combinations")
    rules_before = _fingerprint(run, "production_route_rules")

    run(_as_runner_would(_read(V123)))

    live_join_height = run(
        f"SELECT count(*) FROM processing_items WHERE name = '{RETIRED_NAME}' AND deleted = 0;")
    assert live_join_height.strip() == "0", "撤出后仍有存活的「接高」目录项"
    retired = run(
        f"SELECT id || '|' || status FROM processing_items "
        f"WHERE name = '{RETIRED_NAME}' AND deleted = 1 ORDER BY id;")
    assert retired.splitlines() == [
        "pi-v83-1-09|disabled",
        "pi-v83-1-99|active",   # ← 早就软删过的那一行：**不许被改**（留痕；谓词带 deleted = 0 的证据）
        "pi-v83-2-09|disabled",
    ], f"「接高」行的终态不对（含「已软删行不许动」这条）：\n{retired}"
    kept = run(
        "SELECT id || '|' || deleted FROM processing_items "
        f"WHERE name <> '{RETIRED_NAME}' ORDER BY id;")
    assert kept.splitlines() == [
        "pi-v83-1-06|0", "pi-v83-1-10|0", "pi-v83-1-14|0", "pi-v83-2-10|0",
    ], f"撤出波及了其它目录项：\n{kept}"
    assert items_before != _items(run), "指纹没变 ⇒ 迁移根本没生效（本判据会假绿）"
    # **不改钱**：组合表逐字节不变（含 status / 价 / 键）
    assert _fingerprint(run, "processing_fee_combinations") == combos_before, (
        "撤目录项动了 `processing_fee_combinations` —— 本迁移自身不得改任何价 / 状态")
    # **不追溯存量单**：V84 的 `processing_item 接高` 规则必须留着
    assert _fingerprint(run, "production_route_rules") == rules_before, (
        "撤目录项动了 `production_route_rules` —— 存量单重放时会静默少一道工序")


def test_real_db_affected_combos_are_registered_and_recomputable(seeded):
    """判据 7 后半：**受影响组合**由登记的只读查询给出（活跃且含「接高」），且撤出前后同一批。"""
    run = seeded
    before = run(AFFECTED_COMBOS_QUERY)
    run(_as_runner_would(_read(V123)))
    after = run(AFFECTED_COMBOS_QUERY)
    expected = [
        "1|c-1-keep|定型+接高+韩折|5.00|active",
        "2|c-2-keep|拼接+接高|4.00|active",
    ]
    assert before.splitlines() == expected, f"登记查询读不出受影响的活跃组合：\n{before}"
    # 撤出**不改**这些组合（可见、价与状态都不变）——「不得静默变价」的落点：
    # 迁移只改「新单能不能产生这个名字」，钱由既有 unpriced 可见口径 + 商家改配承担
    assert after.splitlines() == expected, (
        "撤出后受影响组合的价 / 状态变了 ⇒ 迁移在静默改钱（本仓口径：不追溯、只登记 + 给处置）")
    # 停用态的组合不在影响面内（它本来就不参与取价）
    assert "c-1-disabled" not in after


def test_real_db_two_passes_are_idempotent(seeded):
    """幂等：第二遍匹配 0 行、净效果相同（存活行 `updated_at` 也逐字不变）。"""
    run = seeded
    sql = _as_runner_would(_read(V123))
    run(sql)
    items_after_first = _items(run)
    combos_after_first = _fingerprint(run, "processing_fee_combinations")
    rules_after_first = _fingerprint(run, "production_route_rules")

    matched_second_pass = run(
        f"SELECT count(*) FROM processing_items WHERE name = '{RETIRED_NAME}' AND deleted = 0;")
    run(sql)   # 第二遍：谓词已匹配 0 行 ⇒ 空操作，且**不得**抛（对账块两遍都成立）

    assert matched_second_pass.strip() == "0", "第二遍的谓词读数不为 0 —— 幂等闸不成立"
    assert _items(run) == items_after_first, "第二遍改动了目录项（`updated_at` 被重写？）"
    assert _fingerprint(run, "processing_fee_combinations") == combos_after_first
    assert _fingerprint(run, "production_route_rules") == rules_after_first


def test_terminal_reconciliation_catches_miswritten_predicate(seeded):
    """注入红证 ①：谓词写成 `拼接` ⇒ 迁移自带的终态对账当场抛并整份回滚。"""
    run = seeded
    mutated = _read(V123).replace(f"name = '{RETIRED_NAME}'", f"name = '{KEPT_NAME}'")
    assert mutated != _read(V123), "注入无效：源文件里没有可替换的谓词"
    proc = run.raw(_as_runner_would(mutated))
    assert proc.returncode != 0, "谓词写歪（误撤「拼接」）却照样通过 ⇒ 对账块没有判别力"
    assert "误撤" in proc.stderr or "误撤" in proc.stdout, (
        f"失败原因不是「误撤其它项」那条对账：\n{proc.stderr}\n{proc.stdout}")
    # 整份回滚：`接高` 仍在（PG 的 DO 抛异常会让整个事务回滚）
    assert run(f"SELECT count(*) FROM processing_items WHERE name = '{RETIRED_NAME}' AND deleted = 0;"
               ).strip() == "2", "注入失败后没有整份回滚 —— 迁移不是原子的"


def test_terminal_reconciliation_catches_missing_write(seeded):
    """注入红证 ②：抹掉 UPDATE（只留对账块）⇒ 对账照样抛（证明它抓得住「没写 / 漏写」）。"""
    run = seeded
    source = _read(V123)
    start = source.index("UPDATE processing_items")
    end = source.index(";", source.index("AND deleted = 0", start)) + 1
    mutated = source[:start] + source[end:]
    proc = run.raw(_as_runner_would(mutated))
    assert proc.returncode != 0, "没有写语句却通过了 ⇒ 终态对账形同虚设"
    assert "数量对账失败" in proc.stderr or "数量对账失败" in proc.stdout, (
        f"失败原因不是终态数量对账：\n{proc.stderr}\n{proc.stdout}")
