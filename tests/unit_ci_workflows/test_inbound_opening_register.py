# case_ids: PR-061
"""批次建账/初始化入口（issue #5153）：**真库判据**（临时 PG 集群）+ 两条实现禁令的源码判据。

## 为什么必须真库（Mockito 测不出来）

| 面 | 为什么 mock 测不出 |
|---|---|
| **0.5 米尾料能落库**（GAP-12 的前提） | 缺的是「`NUMERIC(12,1)` 到底收不收 0.5」这一**列语义**。mock 里的 `quantity` 是测试自己塞的 BigDecimal，落库精度由被测对象的替身决定，与真列无关（#5141 的教训同族） |
| **精度闸门只能在应用层**（禁令②） | PG 对超 scale 的写入**按四舍五入落库且不报错**（`2.75` → `2.8`）。「DB 会拦下 2 位小数」是**可证伪的**——只有这样，才谈得上「绕过服务层直写 SQL = 静默截断」 |
| **不虚增资产**（禁令①） | 要证明「按登记值落库」不是恒真，必须让**同一个真列**接受两个不同的归一方向（原值 vs 向上进位），读出 `+0.05` 的差额 |

⇒ 照 `tests/unit_ci_workflows/test_inbound_order_idempotency.py`（#5148）的范式：`initdb` /
`pg_ctl` / `psql` 起**临时集群**真跑（缺 PG 的处置收口在 `pg_cluster.py`（CI 判**红** / 本机显式 skip，issue #5203））。

## 本文件钉的事

| 面 | 判据 |
|---|---|
| GAP-12（真库） | 登记 **0.5 米** ⇒ 批次行 `quantity` 读数 **0.5**（不是 1、不是 0、不被任何归一改写） |
| 不虚增（真库 + 注入红证） | 3 个批次（含小数 / 缸号 / 旧系统批次号）⇒ `stock_batches` 落 **3 行**、`legacy_batch_no` 如实保存、余量 = **登记值**；注入红证 = 同一真列走「向上进位」方向 ⇒ 读数**变大**（证明断言不是恒真） |
| 精度闸门不放宽（真库） | PG 对 `2.75` **静默落成 2.8 且不报错** ⇒ 闸门只能在应用层；应用层拒绝 `2.755` 由 Java 判据钉（本文件钉「DB 不拦」这个前提） |
| 幂等（真库 + 注入红证） | 同一 `(tenant_id, import_run_id)` 的第二张期初单被 `uk_inbound_orders_tenant_import_run` 挡下（23505）、同键单据数 = 1；注入红证 = DROP 该索引 ⇒ 同键 2 张 |
| 分布可复算（真库） | 给定 `source='opening'` 的批次集合 ⇒ 逐值 `quantity + Σ(delta)` 可复算、两遍读数逐字相同（**不需要**物化快照表）、采购批次不进这一集合 |
| 两条禁令（源码，**去注释后**） | ① 期初/批次余量路径**不得**出现 `toStockScaleByCeiling`（订单侧向上进位口径）；② 导入器**不得**自己归一（`setScale` / `RoundingMode` / `intValue()` / `(long)` / `getNumericCellValue`），必须调服务层 `create` + `post` |
| 迁移形态 | V118 已登记进 `migration_fingerprints.json`；显式 `BEGIN/COMMIT`；前置 fail-closed 在写语句之前；两遍真跑幂等；`backend/admin-api/src/main/resources/db/init/schema.sql`（bootstrap 路径不跑迁移链）已同步终态 |
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
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



V117 = MIGRATION_DIR / "V117__inbound_order_idempotency_and_source.sql"
V118 = MIGRATION_DIR / "V118__stock_batch_legacy_no_and_opening_register.sql"
SERVICE_DIR = REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
INBOUND_SERVICE = SERVICE_DIR / "InboundOrderService.java"
IMPORT_SERVICE = SERVICE_DIR / "OpeningRegisterImportService.java"
CONTROLLER = REPO / "backend/admin-api/src/main/java/com/migao/admin/controller/InboundOrderController.java"
SCHEMA_SQL = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

TENANT_A = 1
TENANT_B = 2
IMPORT_RUN = "opening-register-20260924-01"
OPENING_NO = "RK-20260924-0301"
RUN_NO_NEXT = "RK-20260924-0302"
PURCHASE_NO = "RK-20260924-0303"

#: 三个登记批次的**登记值**（判据 2 的夹具：含小数、含缸号、含旧系统批次号）。
#: `quantity` 口径 = **登记时点的实物剩余量**（不是旧系统原始入库量 —— 见 V118 文件头「有损项」）。
OPENING_LINES = (
    # (旧系统批次号, 缸号, 登记剩余米数)
    ("OLD-2024-0001", "缸A-8891", "0.5"),
    ("OLD-2024-0002", "缸B-8892", "2.7"),
    (None, None, "60.5"),
)


#: 与 V111 / V115 / V116 / V117 同形的**最小** DDL。
#: 起点是**改前**形态：`stock_batches` / `inbound_order_items` 都**没有** `legacy_batch_no`。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE products (id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT);
CREATE TABLE product_skus (
    id BIGINT PRIMARY KEY, tenant_id BIGINT, stock NUMERIC(12,1) NOT NULL DEFAULT 0);
CREATE TABLE inbound_orders (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_no VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    source VARCHAR(16) NOT NULL DEFAULT 'purchase',
    import_run_id VARCHAR(128),
    posted_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);
CREATE TABLE inbound_order_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    inbound_order_id VARCHAR(64) NOT NULL REFERENCES inbound_orders(id) ON DELETE CASCADE,
    sku_id BIGINT,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_code VARCHAR(64),
    quantity NUMERIC(12,1) NOT NULL,
    unit_cost NUMERIC(12,4),
    batch_no VARCHAR(32),
    dye_lot VARCHAR(64),
    deleted INT DEFAULT 0
);
CREATE TABLE stock_batches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    batch_no VARCHAR(32) NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    sku_id BIGINT,
    sku_code VARCHAR(64),
    inbound_order_id VARCHAR(64) REFERENCES inbound_orders(id),
    inbound_item_id BIGINT,
    inbound_no VARCHAR(32),
    quantity NUMERIC(12,1) NOT NULL,
    unit_cost NUMERIC(12,4),
    amount NUMERIC(16,4),
    dye_lot VARCHAR(64),
    supplier VARCHAR(128),
    warehouse VARCHAR(64),
    received_date DATE,
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INT DEFAULT 0
);
CREATE UNIQUE INDEX uk_stock_batches_no ON stock_batches (tenant_id, batch_no);
-- V116 的消耗台账（余量 = quantity + Σ(delta)，**不原地改** quantity）—— 分布可复算要用
CREATE TABLE stock_batch_consumptions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    batch_id BIGINT NOT NULL REFERENCES stock_batches(id),
    batch_no VARCHAR(32) NOT NULL,
    delta NUMERIC(12,1) NOT NULL,
    reason VARCHAR(32) NOT NULL,
    deleted INT DEFAULT 0
);
"""

_SEED = f"""
INSERT INTO tenants (id) VALUES ({TENANT_A}), ({TENANT_B});
INSERT INTO products (id, tenant_id) VALUES ('prod-1', {TENANT_A}), ('prod-2', {TENANT_A});
INSERT INTO product_skus (id, tenant_id, stock) VALUES (11, {TENANT_A}, 0), (12, {TENANT_A}, 0);
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """注释 → 空（源码判据必须**只读代码**）。

    ⚠️ 必须去注释：本单的迁移与实现里**逐字写着**「不得复用 `toStockScaleByCeiling`」
    「不得静默取整」这类**禁令说明**，不去注释就会把说明文本当成真引用
    （§17.3「判据被自己的文案喂绿/喂红」的同族形态，#4595 / #4689 的教训）。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _sql_code(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


# ══════════════════════════ ① 真库夹具（临时 PG 集群） ══════════════════════════

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg5153-"))
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

    argv = [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
            "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"]

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def psql_raw(sql: str):
        """不抛异常的入口（判据要断言「**确实**失败」/「确实静默成功」）。"""
        return subprocess.run(argv, input=sql, text=True, capture_output=True)

    run.raw = psql_raw
    try:
        yield run
    finally:
        subprocess.run([realdb_binaries["pg_ctl"], "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


def _as_runner_would(sql: str) -> str:
    """把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。"""
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _migrate(psql) -> None:
    """灌入改前形态 + 夹具，再真跑 V117（来源/幂等键）与 V118（本单的缺口列）。"""
    psql(_DDL + _SEED)
    psql(_as_runner_would(_read(V117)))
    psql(_as_runner_would(_read(V118)))


# ══════════════════════════ ② 期初建账的写入面（与 `post` 同形的最小 SQL） ══════════════════════════

def _opening_order(order_id: str, inbound_no: str, run_id: str | None,
                   tenant_id: int = TENANT_A) -> str:
    cols = "(id, tenant_id, inbound_no, status, source"
    vals = f"('{order_id}', {tenant_id}, '{inbound_no}', 'posted', 'opening'"
    if run_id is not None:
        cols += ", import_run_id"
        vals += f", '{run_id}'"
    return f"INSERT INTO inbound_orders {cols}) VALUES {vals});"


def _opening_lines(order_id: str, lines=OPENING_LINES, sku_id: int = 11) -> str:
    """期初单明细行：`quantity` = 登记时点的**实物剩余量**；`legacy_batch_no` = 旧系统批次号。"""
    values = []
    for idx, (legacy, dye_lot, qty) in enumerate(lines, start=1):
        legacy_sql = "NULL" if legacy is None else f"'{legacy}'"
        dye_sql = "NULL" if dye_lot is None else f"'{dye_lot}'"
        values.append(f"({TENANT_A}, '{order_id}', {sku_id}, 'prod-1', 'SKU-11', "
                      f"{qty}, {legacy_sql}, {dye_sql}, 'PC-20260924-{idx:04d}')")
    return ("INSERT INTO inbound_order_items "
            "(tenant_id, inbound_order_id, sku_id, product_id, sku_code, quantity, "
            " legacy_batch_no, dye_lot, batch_no) VALUES " + ", ".join(values) + ";")


def _opening_batches(order_id: str, inbound_no: str, lines=OPENING_LINES, sku_id: int = 11,
                     seq_start: int = 1) -> str:
    """批次行 —— **列面与 `InboundOrderService.post` 逐字一致**，`quantity` 直接取登记值
    （**不做任何归一**：任何 `setScale` / 向上进位都会让「余量 = 登记值」当场不成立）。
    """
    values = []
    for idx, (legacy, dye_lot, qty) in enumerate(lines, start=seq_start):
        legacy_sql = "NULL" if legacy is None else f"'{legacy}'"
        dye_sql = "NULL" if dye_lot is None else f"'{dye_lot}'"
        values.append(f"({TENANT_A}, 'PC-20260924-{idx:04d}', 'prod-1', {sku_id}, 'SKU-11', "
                      f"'{order_id}', '{inbound_no}', {qty}, {legacy_sql}, {dye_sql})")
    return ("INSERT INTO stock_batches "
            "(tenant_id, batch_no, product_id, sku_id, sku_code, inbound_order_id, "
            " inbound_no, quantity, legacy_batch_no, dye_lot) VALUES " + ", ".join(values) + ";")


def _batches_of(psql, inbound_no: str) -> list[str]:
    raw = psql("SELECT batch_no || '|' || quantity::text || '|' || COALESCE(legacy_batch_no, '-') "
               f"|| '|' || COALESCE(dye_lot, '-') FROM stock_batches "
               f"WHERE inbound_no = '{inbound_no}' ORDER BY id;").strip()
    return [line for line in raw.splitlines() if line]


# ══════════════════════════ ③ GAP-12：0.5 米尾料能登记（真库） ══════════════════════════

def test_half_meter_tail_lands_exactly_as_registered(psql):
    """**核心判据（GAP-12）**：登记 **0.5 米**的批次 ⇒ 批次行 `quantity` 读数就是 **0.5**。

    用户痛点逐字：「当前企业剩余了**大量的 0.5 米左右**的批次布料」—— 改前应用层要求
    `quantity ≥ 1` 米（`InboundOrderService.validateRequest`），这些批次**连登记都进不来**
    （改前的失败形态由 `InboundOrderServiceTest` 的 Java 判据复现文案）。
    本判据钉的是另一半：**放宽下限之后真列收得下 0.5**，且没有任何归一把它改写成 1。
    """
    _migrate(psql)
    psql(_opening_order("o-half", OPENING_NO, IMPORT_RUN))
    psql(_opening_lines("o-half", lines=(("OLD-2024-0001", "缸A-8891", "0.5"),)))
    psql(_opening_batches("o-half", OPENING_NO, lines=(("OLD-2024-0001", "缸A-8891", "0.5"),)))

    rows = _batches_of(psql, OPENING_NO)
    print(f"[#5153 真库 · 0.5 米] 批次读数 = {rows}")
    assert len(rows) == 1, f"应恰好 1 行批次：{rows}"
    batch_no, quantity, legacy, dye_lot = rows[0].split("|")
    assert Decimal(quantity) == Decimal("0.5"), (
        f"0.5 米尾料落库不是 0.5（成了 {quantity}）—— 尾料被归一改写或被下限挡在门外")
    assert batch_no.startswith("PC-"), f"系统批次号形态变了：{batch_no}"
    assert legacy == "OLD-2024-0001", f"旧系统批次号没落进 legacy_batch_no：{legacy}"
    assert dye_lot == "缸A-8891", f"缸号丢了：{dye_lot}"


def test_decimal_precision_is_the_database_silent_rounding_trap(psql):
    """**禁令② 的前提（可证伪）**：`NUMERIC(12,1)` 对 `2.75` **静默落成 2.8 且不报错**。

    ⇒ 「DB 会拦下 2 位小数」是**假**的；fail-closed 只能在应用层（`StockQuantity.requireOneDecimal`）。
    绕过服务层直写 SQL（或让导入器自己归一）= 静默截断/虚增，且**没有任何东西会因此变红**。
    """
    _migrate(psql)
    psql(_opening_order("o-raw", OPENING_NO, None))
    silent = psql.raw(_opening_batches("o-raw", OPENING_NO, lines=((None, None, "2.75"),)))
    stored = psql(f"SELECT quantity::text FROM stock_batches WHERE inbound_no = '{OPENING_NO}';").strip()
    print(f"[#5153 真库 · 精度] 写 2.75 ⇒ 退出码 = {silent.returncode}；落库读数 = {stored}")
    assert silent.returncode == 0, (
        f"DB 竟然拒绝了 2 位小数（那本禁令②的前提就不成立）：{silent.stderr[:300]}")
    assert Decimal(stored) == Decimal("2.8"), (
        f"PG 没有静默四舍五入（落库 {stored}）—— 本判据的前提变了，需重新取证")


# ══════════════════════════ ④ 不虚增：余量 = 登记值（判据 + 注入式红证） ══════════════════════════

def test_registered_remaining_is_never_ceiled(psql):
    """**核心判据（禁令①）**：3 个批次（含小数 / 缸号 / 旧系统批次号）⇒ 3 行、旧号如实保存、
    **余量 = 登记值**（不是向上进位后的值）。

    用户裁定「**不能损失客户**」+ #5149 §3.6.2 显式禁令：归一**不得**复用订单侧的
    `toStockScaleByCeiling`（向上进位，模拟裁床用料）—— 期初/批次余量是**库存类输入**，
    用它每条最多虚增 `+0.099m` ⇒ **系统性虚增资产**。
    """
    _migrate(psql)
    psql(_opening_order("o-3", OPENING_NO, IMPORT_RUN))
    psql(_opening_lines("o-3"))
    psql(_opening_batches("o-3", OPENING_NO))

    rows = _batches_of(psql, OPENING_NO)
    print(f"[#5153 真库 · 不虚增] 3 个批次的落库读数 = {rows}")
    assert len(rows) == 3, f"应落 3 行批次（一个明细行 = 一个批次）：{rows}"

    got = [r.split("|") for r in rows]
    assert [Decimal(r[1]) for r in got] == [Decimal(q) for _, _, q in OPENING_LINES], (
        f"余量 != 登记值：{[(r[1], q) for r, (_, _, q) in zip(got, OPENING_LINES)]}")
    assert [r[2] for r in got] == ["OLD-2024-0001", "OLD-2024-0002", "-"], (
        f"旧系统批次号没有如实保存：{[r[2] for r in got]}")
    assert [r[3] for r in got] == ["缸A-8891", "缸B-8892", "-"], (
        f"缸号没有如实保存：{[r[3] for r in got]}")
    # 「不得互相冒充」：系统批次号（PC-*）与旧系统批次号各占一列，逐行不同
    assert all(r[0] != r[2] for r in got), f"旧系统批次号与系统批次号混为一列：{got}"


def test_injected_ceiling_would_inflate_the_registered_remaining(psql):
    """**注入式红证**：同一个 2 位小数原值，换上「订单侧向上进位」的归一方向 ⇒ 落库读数**变大**。

    上一条断言「余量 = 登记值」若恒真（例如真列根本不收小数、或夹具自己写错），这里也测不出差别。
    只有读数**真的虚增**，才说明上一条有判别力。

    取 `2.71`（不是 `2.75`）：两条方向在这一位上**分得开** ——
    四舍五入（PG 对超 scale 的静默落法）得 `2.7`，向上进位（`toStockScaleByCeiling` 的语义）
    得 `2.8` ⇒ 每条**虚增 0.1 米**（禁令①登记的「每条最多虚增 +0.099m」就是这个差额）。
    `2.75` 分不开：两条方向都落在 `2.8`。这正是「用一个分不开的值做红证 = 空断言」的坑。
    """
    _migrate(psql)
    raw = "2.71"
    psql(_opening_order("o-half-up", OPENING_NO, None))
    psql(_opening_batches("o-half-up", OPENING_NO, lines=((None, None, raw),)))
    half_up = psql(f"SELECT quantity::text FROM stock_batches WHERE inbound_no = '{OPENING_NO}';").strip()

    psql(_opening_order("o-ceil", RUN_NO_NEXT, None))
    # `toStockScaleByCeiling` 的正向语义（`ceiling(x*10)/10`）——用它写库就是**虚增**的那条路
    psql(_opening_batches("o-ceil", RUN_NO_NEXT,
                          lines=((None, None, f"CEIL({raw} * 10) / 10"),), seq_start=2))
    ceiled = psql(f"SELECT quantity::text FROM stock_batches WHERE inbound_no = '{RUN_NO_NEXT}';").strip()

    inflation = Decimal(ceiled) - Decimal(half_up)
    print(f"[#5153 真库 · 红证] 原值 {raw}：四舍五入方向 = {half_up}；向上进位方向 = {ceiled}"
          f"（虚增 {inflation} 米/条）")
    assert Decimal(ceiled) > Decimal(half_up), (
        f"进位方向没有让读数变大（{half_up} → {ceiled}）⇒ 上一条「余量 = 登记值」可能是恒真（空断言）")
    assert inflation == Decimal("0.1"), f"虚增幅度不符（应为 0.1 米/条）：{inflation}"


# ══════════════════════════ ⑤ 幂等：同一 run_id 不产生第二张单（判据 + 红证） ══════════════════════════

def test_same_import_run_never_creates_a_second_opening_order(psql):
    """**核心判据（幂等）**：同一 `(tenant_id, import_run_id)` 重跑期初建账 ⇒ 不产生第二张单。

    复用 #5148 的 `uk_inbound_orders_tenant_import_run`（V117）—— **不新造幂等键**：
    两张期初单都过账 = 库存加两次 = 凭空多出一批不存在的布。
    """
    _migrate(psql)
    psql(_opening_order("o1", OPENING_NO, IMPORT_RUN))

    replayed = psql("SELECT id || '|' || inbound_no FROM inbound_orders "
                    f"WHERE deleted = 0 AND tenant_id = {TENANT_A} "
                    f"AND import_run_id = '{IMPORT_RUN}';").strip()
    assert replayed == f"o1|{OPENING_NO}", (
        f"重跑没命中既有期初单（幂等分支会退化成「又建一张」）：{replayed}")

    dup = psql.raw(_opening_order("o2", RUN_NO_NEXT, IMPORT_RUN))
    count = psql("SELECT count(*) FROM inbound_orders "
                 f"WHERE tenant_id = {TENANT_A} AND import_run_id = '{IMPORT_RUN}';").strip()
    print(f"[#5153 真库 · 幂等] 同运行第二张期初单：退出码 = {dup.returncode}；"
          f"stderr 含索引名 = {'uk_inbound_orders_tenant_import_run' in dup.stderr}；同键单据数 = {count}")
    assert dup.returncode != 0, "同一运行标识竟建出第二张期初单（重跑会双倍加库存）"
    assert "uk_inbound_orders_tenant_import_run" in dup.stderr, (
        f"拦下它的不是幂等索引：{dup.stderr[:300]}")
    assert count == "1", f"同一运行的期初单据数 = {count}（必须恰好 1）"

    # 不误伤：**不带**运行标识的普通/期初建单不受影响（部分索引谓词 import_run_id IS NOT NULL）
    psql(_opening_order("o3", PURCHASE_NO, None))
    psql(f"INSERT INTO inbound_orders (id, tenant_id, inbound_no, status) "
         f"VALUES ('o4', {TENANT_A}, 'RK-20260924-0304', 'draft');")
    manual = psql("SELECT string_agg(id, ',' ORDER BY id) FROM inbound_orders "
                  f"WHERE tenant_id = {TENANT_A} AND import_run_id IS NULL;").strip()
    # 租户维度：另一个租户用同一个运行标识是允许的（索引是 (tenant_id, import_run_id)）
    psql(_opening_order("o5", OPENING_NO, IMPORT_RUN, tenant_id=TENANT_B))
    other = psql(f"SELECT count(*) FROM inbound_orders WHERE tenant_id = {TENANT_B};").strip()
    print(f"[#5153 真库 · 幂等] 无运行标识的建单 = [{manual}]；另一租户同键 = {other} 张")
    assert manual == "o3,o4", f"普通建单被误伤（谓词漏了 import_run_id IS NOT NULL）：{manual}"
    assert other == "1", f"另一租户同键建单被误伤（索引漏了 tenant_id）：{other}"


def test_injected_missing_index_would_allow_the_second_opening_order(psql):
    """**注入式红证**：DROP 掉幂等索引 ⇒ 第二张期初单建得进去（读数 1 → 2）。"""
    _migrate(psql)
    psql("DROP INDEX uk_inbound_orders_tenant_import_run;")
    psql(_opening_order("o1", OPENING_NO, IMPORT_RUN))
    psql(_opening_order("o2", RUN_NO_NEXT, IMPORT_RUN))
    count = psql("SELECT count(*) FROM inbound_orders "
                 f"WHERE tenant_id = {TENANT_A} AND import_run_id = '{IMPORT_RUN}';").strip()
    print(f"[#5153 真库 · 红证] 去掉幂等索引后同键期初单据数 = {count}（正常口径应为 1）")
    assert count == "2", f"没有索引也建不出第二张（读数 {count}）⇒ 上一条是空断言"


# ══════════════════════════ ⑥ 分布可复算（基线冻结点：posted_at + source='opening'） ══════════════════════════

def _recompute_opening_distribution(psql) -> list[str]:
    """给定 `source='opening'` 的批次集合 ⇒ 逐值复算余量（`quantity + Σ(delta)`）。

    **不读任何物化快照**：余量是派生值（V116 裁定「不原地改 `stock_batches.quantity`」），
    ⇒ 分布**永久可复算**（V118 有意不建快照表）。
    """
    raw = psql(
        "SELECT b.batch_no || '=' || "
        "       (b.quantity + COALESCE(SUM(c.delta), 0))::text "
        "  FROM stock_batches b "
        "  JOIN inbound_orders o ON o.id = b.inbound_order_id "
        "  LEFT JOIN stock_batch_consumptions c ON c.batch_id = b.id AND c.deleted = 0 "
        " WHERE o.source = 'opening' AND b.deleted = 0 "
        " GROUP BY b.id, b.batch_no, b.quantity "
        " ORDER BY b.batch_no;").strip()
    return [line for line in raw.splitlines() if line]


def test_opening_distribution_recomputes_value_by_value(psql):
    """**核心判据（分布可复算）**：`source='opening'` 的批次集合 ⇒ 逐值可复算、两遍同读数。

    基线冻结点 = `posted_at` + `source='opening'`；批次行不可改 + 余量派生
    ⇒ 分布**永久可复算**，**不需要**物化快照表（V118 有意不加表）。
    """
    _migrate(psql)
    psql(_opening_order("o-3", OPENING_NO, IMPORT_RUN))
    psql(_opening_lines("o-3"))
    psql(_opening_batches("o-3", OPENING_NO))
    # 采购批次（source 缺省 = purchase）**不得**进期初集合
    psql(f"INSERT INTO inbound_orders (id, tenant_id, inbound_no, status) "
         f"VALUES ('o-p', {TENANT_A}, '{PURCHASE_NO}', 'posted');")
    psql(_opening_batches("o-p", PURCHASE_NO, lines=((None, None, "12.5"),), sku_id=12,
                          seq_start=9))
    # 两条消耗事实：0.5 的尾料被用掉 0.3；60.5 那批被用掉 1.2
    psql("INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, delta, reason) "
         "SELECT 1, id, batch_no, -0.3, 'processing_order' FROM stock_batches "
         " WHERE inbound_no = '{}' AND batch_no = 'PC-20260924-0001';".format(OPENING_NO))
    psql("INSERT INTO stock_batch_consumptions (tenant_id, batch_id, batch_no, delta, reason) "
         "SELECT 1, id, batch_no, -1.2, 'processing_order' FROM stock_batches "
         " WHERE inbound_no = '{}' AND batch_no = 'PC-20260924-0003';".format(OPENING_NO))

    first = _recompute_opening_distribution(psql)
    second = _recompute_opening_distribution(psql)
    print(f"[#5153 真库 · 分布] 期初集合首遍 = {first}")
    print(f"[#5153 真库 · 分布] 期初集合二遍 = {second}")

    assert first == [
        "PC-20260924-0001=0.2",   # 0.5 - 0.3（尾料**看得见**：改前它连登记都进不来）
        "PC-20260924-0002=2.7",
        "PC-20260924-0003=59.3",  # 60.5 - 1.2
    ], f"期初集合逐值复算不符：{first}"
    assert first == second, f"同一集合两遍读数不同（不满足「永久可复算」）：{first} vs {second}"
    assert Decimal("0.2") + Decimal("2.7") + Decimal("59.3") == Decimal("62.2"), "夹具自证"
    assert all("PC-20260924-0004" not in line for line in first), (
        f"采购批次被算进了期初集合（source 基线没生效）：{first}")


# ══════════════════════════ ⑦ 两条禁令：源码判据（去注释后） ══════════════════════════

def test_import_goes_through_the_service_layer_and_normalizes_nothing():
    """**禁令① + ②的源码判据**：导入器**自己归一 = 违禁**，必须调服务层 `create` + `post`。

    - 禁令①：不得复用 `toStockScaleByCeiling`（订单侧向上进位口径；用在库存类输入上 = 系统性虚增）；
    - 禁令②：`NUMERIC(12,1)` 在 DB 层对 `2.75` 静默落成 2.8 且不报错（上一条真库判据已证）
      ⇒ 导入器必须把**原始值**交给服务层，由 `StockQuantity.requireOneDecimal` 一处定夺。
    """
    assert IMPORT_SERVICE.exists(), f"缺少导入器：{IMPORT_SERVICE.name}"
    code = _strip_comments(_read(IMPORT_SERVICE))
    for banned in ("toStockScaleByCeiling", "setScale", "RoundingMode", "intValue()",
                   "(long)", "(int)"):
        assert banned not in code, (
            f"导入器里出现了 `{banned}` —— 导入必须走服务层，**不得**自己归一/截断（禁令②）："
            f"DB 层的 NUMERIC(12,1) 会静默四舍五入")
    # 数值单元格必须按**十进制定点**读（`BigDecimal.valueOf(double)` = Double.toString 往返，
    # `2.75` 仍是 `2.75`）；`(long)` 一截就把 `0.5` 变成 `0`（ProductService 里登记过的同族缺陷）
    assert "getNumericCellValue" in code and "BigDecimal.valueOf(" in code, (
        "导入器没有按十进制定点读数值单元格（读 double 后必须转 BigDecimal，不许强转截断）")
    assert "inboundOrderService.create(" in code, "导入器没有调服务层建单（create）"
    assert "inboundOrderService.post(" in code, "导入器没有调服务层过账（post）—— 期初批次不会进库存"


def test_quantity_gate_is_the_single_place_and_lower_bound_is_relaxed():
    """**GAP-12 的源码判据**：数量闸门只有一处，且下限已是 `> 0 米`（不再是 `≥ 1 米`）。"""
    code = _strip_comments(_read(INBOUND_SERVICE))
    assert "toStockScaleByCeiling" not in code, (
        "入库服务里出现了 `toStockScaleByCeiling` —— 期初/批次余量属**库存类输入**，"
        "只能用 StockQuantity.requireOneDecimal 一族（禁令①）")
    assert "requireOneDecimal" in code, "数量精度准入没有走 StockQuantity.requireOneDecimal"
    assert "signum()" in code, "下限判据不见了（> 0 米）"
    assert "compareTo(BigDecimal.ONE) < 0" not in code, (
        "`≥1 米` 的老判据还在 —— 0.5 米的尾料仍然进不来（GAP-12 未闭环）")
    assert "数量必须 ≥1 米" not in code, "老文案（≥1 米）还在"


def test_import_requires_an_idempotency_key(psql):
    """**批量必带幂等键**（fail-closed）：没有运行标识就不许上批量导入（重跑 = 双倍加库存）。

    判据分两层：① 端点把 `importRunId` 声明成**必填**（不是 `required = false`）；
    ② 幂等键的准入判据只有**一处**（导入服务的 `requireRunId`）——「必填」这件事本身的行为红证
    在 `OpeningRegisterImportServiceTest`（空白 ⇒ 拒且**不调** create）。
    """
    controller = _strip_comments(_read(CONTROLLER))
    assert "opening-import" in controller, "缺少批量建账端点"
    assert '@RequestParam("importRunId")' in controller, (
        "批量建账端点没有把 importRunId 声明成必填参数（`@RequestParam(\"importRunId\")`）")
    assert re.search(r'importRunId"\s*,\s*required\s*=\s*false', controller) is None, (
        "批量建账端点把 importRunId 放宽成可选 —— 不带幂等键也能导入 = 重跑双倍加库存")

    importer = _strip_comments(_read(IMPORT_SERVICE))
    assert "requireRunId" in importer, "导入器没有幂等键准入判据（requireRunId）"
    assert re.search(r"hasText\(importRunId\)", importer), (
        "幂等键准入判据没有判「空白」（空白标识 = 没有幂等键）")
    assert "幂等键" in _read(IMPORT_SERVICE), "导入器没有把「为什么必须带幂等键」写清楚（注释）"


# ══════════════════════════ ⑧ 迁移形态 / 账本 / bootstrap 镜像 ══════════════════════════

def test_v118_exists_and_is_the_unique_highest_version():
    assert V118.exists(), f"缺少迁移文件：{V118.name}"
    versions = [int(re.match(r"^V(\d+)__", p.name).group(1))
                for p in _migration_files("V*.sql") if re.match(r"^V(\d+)__", p.name)]
    assert versions.count(118) == 1, "V118 版本号重复"
    # ⚠️ 原写 `max(versions) == 118`（「V118 是当前最大迁移号」）—— 那是本仓**点名过的自毁式真值主张**：
    #    下一个迁移一出现就必红，且报错文案把人指向错误行动。**#5158 新增 V119 时实测踩中**：
    #    `AssertionError: V118 不是最高版本号（当前最大 V119）`（CI job「ci workflow helper unit tests」）。
    #    判据本意（见方法名）= 「**迁移号撞车 ⇒ 有一条永远不会跑**」⇒ 正确口径 = 本档及以后无重复；
    #    同族口径与改法见 `tests/unit_ci_workflows/test_inbound_order_idempotency.py`（`>= 117`）与
    #    `backend/admin-api/src/test/java/com/migao/admin/mapper/StockBatchConsumptionMapperTest.java`
    #    （`doesNotHaveDuplicates`），V116 那份 javadoc 亦逐字登记过这条教训。
    assert max(versions) >= 118, f"V118 不是最高版本号（当前最大 V{max(versions)}）"
    assert len([v for v in versions if v >= 118]) == len({v for v in versions if v >= 118}), (
        "V118 及以后出现重复版本号（撞车 ⇒ 有一条永远不会跑）")


def test_v118_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏（issue #4235）：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert V118.name in ledger, (
        f"`{V118.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_v118_is_explicitly_transactional_and_fails_closed_before_writing():
    body = _read(V118)
    assert re.search(r"^BEGIN;", body, re.M), "V118 缺显式 `BEGIN;`（psql -f 默认逐条 autocommit ⇒ 半完成态）"
    assert re.search(r"^COMMIT;", body, re.M), "V118 缺显式 `COMMIT;`"
    code = _sql_code(body)
    first_write = min(code.index(k) for k in ("ALTER TABLE", "CREATE INDEX"))
    assert code.index("RAISE EXCEPTION") < first_write, (
        "前置 fail-closed 判据排在写语句之后（缺表时会先改一半再抛）")
    assert "终态对账" in body, "V118 缺终态对账（判据漂移的停止条件）"


def test_v118_is_idempotent_on_a_real_database(psql):
    """两遍真跑：第二遍不报错、终态与数据都不变（`MigrationRunner` 要求所有迁移可重复执行）。"""
    psql(_DDL + _SEED)
    psql(_as_runner_would(_read(V117)))
    psql(_as_runner_would(_read(V118)))
    cols_first = psql("SELECT count(*) FROM information_schema.columns "
                      "WHERE table_name IN ('stock_batches', 'inbound_order_items');").strip()
    idx_first = psql("SELECT indexdef FROM pg_indexes "
                     "WHERE indexname = 'idx_stock_batches_tenant_legacy_no';").strip()

    psql(_as_runner_would(_read(V118)))                 # 第二遍（幂等）

    assert psql("SELECT count(*) FROM information_schema.columns "
                "WHERE table_name IN ('stock_batches', 'inbound_order_items');").strip() == cols_first, (
        "第二遍增删了列")
    assert psql("SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'idx_stock_batches_tenant_legacy_no';").strip() == idx_first
    assert psql(f"SELECT count(*) FROM tenants;").strip() == "2", "第二遍动了行"


def test_v118_columns_are_visibly_separate_from_the_system_batch_no(psql):
    """**「不得互相冒充」的列面判据**（V111 明令）：旧系统批次号有**独立落点**，且列注释写明来路。"""
    _migrate(psql)
    cols = psql("SELECT table_name || '.' || column_name || ':' || data_type || '(' || "
                "COALESCE(character_maximum_length::text, '-') || ')' "
                "FROM information_schema.columns "
                "WHERE column_name = 'legacy_batch_no' ORDER BY table_name;").strip().splitlines()
    comment = psql("SELECT col_description('stock_batches'::regclass, attnum) FROM pg_attribute "
                   "WHERE attrelid = 'stock_batches'::regclass AND attname = 'legacy_batch_no';").strip()
    print(f"[#5153 真库 · 列面] legacy_batch_no = {cols}")
    print(f"[#5153 真库 · 列面] 注释含「旧系统」= {'旧系统' in comment}")
    assert cols == ["inbound_order_items.legacy_batch_no:character varying(64)",
                    "stock_batches.legacy_batch_no:character varying(64)"], (
        f"缺口列的落点不符（旧号必须有独立列，不得与 batch_no / dye_lot 混用）：{cols}")
    assert "旧系统" in comment, f"stock_batches.legacy_batch_no 的列注释没说清来路：{comment}"


def test_bootstrap_schema_sql_is_already_terminal():
    """bootstrap 路径（新建库**不跑迁移链**）必须与 V118 终态同形，否则新库与老库行为分叉。"""
    schema = _read(SCHEMA_SQL)
    assert len(re.findall(r"legacy_batch_no\s+VARCHAR\(64\)", schema)) == 2, (
        "schema.sql 里 legacy_batch_no 不是恰好两处（stock_batches + inbound_order_items）")
    assert re.search(r"idx_stock_batches_tenant_legacy_no", schema), (
        "schema.sql 缺 legacy_batch_no 的查询索引")
    assert re.search(r"upstream_run_id|import_run_id\s+VARCHAR\(128\)", schema), (
        "schema.sql 的 V117 终态（import_run_id）不见了")
