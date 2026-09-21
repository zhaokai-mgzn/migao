# case_ids: PR-042, PR-043, PR-044, OR-046
"""V112 商品模型改造迁移的承重判据 + 真库两遍幂等 + bootstrap 终态镜像。

（用户裁定 2026-09-21，逐字：「商品需要增加 1 卷=多少米，作为**商品货号的基础参数**，
商品的售卖方式**整卷/散件不能作为 SKU 的组合项**，只能作为**基础属性**，商品的 SKU 由**颜色+门幅**
组成即可，在订单中再体现**客户要求优先整卷发货**，例子：客户买 100 米布，一卷=60 米，
那就发 1 整卷 60 + 散剪出的 40 米」）

## 本文件钉的事

| 面 | 判据 |
|---|---|
| 形态（静态） | 显式 `BEGIN;/COMMIT;`；`products` 加 `selling_methods` / `roll_length_m`；`product_skus` **DROP** `selling_method`；唯一键收窄为 `(product_id, color_id, door_width)`；`order_items` 加三列；文末 `DO` 块终态对账 |
| 顺序（不可交换） | 回填（从 SKU 取真值）**先于** DROP COLUMN；去重**先于** ADD CONSTRAINT（否则建约束失败 / 回填丢失真值） |
| 真库（临时 PG） | 两遍真跑：第二遍净效果相同；`selling_method` 列已消失；唯一键定义逐字 = `(product_id, color_id, door_width)`；**重复行被去重**（保留价格最低、同价取 id 最小）；`products.selling_methods` 回填自旧 SKU 真值、无 NULL |
| 判别力（注入红证） | ① 不去重就建唯一键 ⇒ 建约束失败（证明「去重」这条不是装饰）；② 把 `selling_method` 加回唯一键 ⇒ 终态对账抛（证明约束判据有判别力）；③ 回填挪到 DROP 之后 ⇒ 回填拿不到真值（顺序判据有判别力） |
| bootstrap 镜像 | `docs/sql/schema.sql`（bootstrap 路径**不跑迁移链**）的 `product_skus` 已无该列、唯一键已是两维、`products` 已带两列 |

## 为什么必须真跑两遍

`MigrationRunner` 要求**所有**迁移可重复执行，而「幂等」只有真库能判：
`ADD COLUMN IF NOT EXISTS` 与既有列的交互、`pg_constraint` 判据、`DELETE ... USING` 自连接的去重
幂等性、`DO $$ … $$` 里 `RAISE EXCEPTION` 的回滚半径 —— 都是**运行期**语义。

## 真库判据（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

照 `tests/unit_ci_workflows/test_must_finish_retire_migration.py` 的范式：`initdb` / `pg_ctl` / `psql`
起**临时集群**真跑 —— 静态文本判据不够。
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
V112 = MIGRATION_DIR / "V112__product_roll_length_and_selling_method_base_attribute.sql"
SCHEMA_SQL = REPO / "docs/sql/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

UNIQUE_CONSTRAINT = "uq_product_skus_combination"
UNIQUE_DEF = "(product_id, color_id, door_width)"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释（`--` 行注释与 `/* */` 块注释）→ 空，供**写语句**判据用。

    ⚠️ 必须去注释：本仓迁移把「回滚 SQL」写在注释里（V112 的回滚段里就有 `ALTER TABLE ... DROP`），
    不去注释会把注释里的语句当成真写语句（#4595 的同族教训）。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


# ══════════════════════════ ① 存在性 / 账本 / 形态 ══════════════════════════

def test_v111_exists_and_is_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏（issue #4235）：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    assert V112.exists(), f"缺少迁移文件：{V112.name}"
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert V112.name in ledger, (
        f"`{V112.name}` 未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`。\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


def test_v111_is_explicitly_transactional():
    """`psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 会留半完成态（V97/V102/V107 实测口径）。"""
    body = _read(V112)
    assert re.search(r"^BEGIN;", body, re.M), "V112 缺显式 `BEGIN;`"
    assert re.search(r"^COMMIT;", body, re.M), "V112 缺显式 `COMMIT;`"
    assert "RAISE EXCEPTION" in body, "V112 缺终态对账（`RAISE EXCEPTION`）"


def test_v111_drops_the_selling_method_column_from_product_skus():
    """红线：售卖方式必须是商品级基础属性 ⇒ `product_skus.selling_method` 必须被删掉。"""
    body = _strip_comments(_read(V112))
    assert re.search(r"ALTER TABLE product_skus\s+DROP COLUMN IF EXISTS selling_method", body), (
        "V112 没有 `ALTER TABLE product_skus DROP COLUMN IF EXISTS selling_method` —— "
        "售卖方式必须离开 SKU 组合（用户裁定）")


def test_v111_adds_both_product_columns_without_a_default_on_roll_length():
    """`roll_length_m` **不得有默认值**：NULL = 未配置是真值（行业卷长是区间值，不得编造）。"""
    body = _strip_comments(_read(V112))
    assert re.search(r"ADD COLUMN IF NOT EXISTS selling_methods JSONB", body), "缺 products.selling_methods"
    assert re.search(r"ADD COLUMN IF NOT EXISTS roll_length_m NUMERIC\(8,2\)", body), "缺 products.roll_length_m"
    assert not re.search(r"roll_length_m NUMERIC\(8,2\)\s+DEFAULT", body), (
        "roll_length_m 带了 DEFAULT —— 那会把「未配置」这一档从库里抹掉，"
        "订单侧就无法区分「一卷 60 米」与「没配卷长」（见 docs/curtain-selling-method-industry-research.md §5）")


def test_v111_backfill_precedes_the_drop_and_dedup_precedes_the_constraint():
    """顺序判据：回填要先于 DROP（否则取不到旧真值）；去重要先于建唯一键（否则建约束失败）。"""
    body = _strip_comments(_read(V112))
    backfill = body.index("SET selling_methods = agg.methods")  # 回填块（现包在「列在不在」判据里）
    drop = body.index("DROP COLUMN IF EXISTS selling_method")
    dedup = body.index("DELETE FROM product_skus victim")
    add_constraint = body.index("ADD CONSTRAINT uq_product_skus_combination")
    assert backfill < drop, "回填必须在 DROP COLUMN 之前 —— 之后就拿不到「旧 SKU 里出现过哪些售卖方式」了"
    assert dedup < add_constraint, (
        "去重必须在 ADD CONSTRAINT 之前 —— 旧唯一键允许同色同门幅两行（散剪/整卷），"
        "先去重才能建两维唯一键")


def test_v111_backfill_never_references_a_column_that_does_not_exist():
    """**静态钉住那个真缺陷**：回填**不得**引用 `product_skus.deleted`（该表没有这一列）。

    为什么必须有这条静态断言（而不只靠真库判据）：
    `product_skus` 全仓从未有过软删列（`docs/sql/schema.sql` 的 `CREATE TABLE product_skus` 无该列、
    迁移链无 `ALTER TABLE product_skus ADD COLUMN deleted`、`ProductSku` 无 `@TableLogic`，
    删除走 `deleteById` = **物理删除**）。回填写了 `AND deleted = 0` ⇒ 真库抛
    「字段 "deleted" 不存在」⇒ 整份迁移回滚，而 `MigrationRunner` 对非连接类失败是
    **跳过并继续**（只打一行 ERROR、不写 `schema_migrations`）⇒ **部署 success、三列永不建**。

    ⚠️ **本单第一版就是错的，而且是测试夹具把它挡掉的**：真库判据的 `_DDL` 自己给
    `product_skus` 补了 `deleted INTEGER NOT NULL DEFAULT 0` ⇒ 真库判据全绿。
    ⇒ 本文件同时做两件事：① 静态断言回填里不出现 `deleted`；② `_DDL` 与真 schema 逐列一致
    （见 `_DDL` 上方注释「不得加 deleted」）。独立对抗式复核实测抓到。
    """
    body = _strip_comments(_read(V112))
    backfill_start = body.index("$backfill$")
    backfill_end = body.index("$backfill$;", backfill_start + 1)
    backfill = body[backfill_start:backfill_end]
    assert "deleted" not in backfill, (
        "V112 的回填里出现了 `deleted` —— `product_skus` **没有**这一列（删除是物理删除）⇒ "
        "真库会抛「字段 deleted 不存在」⇒ 整份迁移回滚且被 MigrationRunner 静默跳过")
    # 同时钉住夹具与真 schema 一致（否则夹具会继续掩盖同类缺陷）
    ddl = _read(Path(__file__))
    skus_ddl = ddl[ddl.index("CREATE TABLE product_skus ("):]
    skus_ddl = skus_ddl[:skus_ddl.index(");")]
    assert "deleted" not in skus_ddl, (
        "真库判据的 `_DDL` 给 `product_skus` 加了 `deleted` —— 真 schema 没有这一列 ⇒ "
        "夹具会掩盖「回填引用不存在列」这类缺陷（本单实测）")


def test_v111_documents_rollback_and_its_irreversible_part():
    """迁移文件的硬要求：回滚 SQL + 不可复原项（回滚是有损的，必须照实登记）。"""
    body = _read(V112)
    assert "回滚" in body, "V112 缺「回滚」段（本仓迁移的硬要求）"
    assert "有损" in body or "不可复原" in body, "V112 没写「不可复原项」（去重删掉的行回不来）"


# ══════════════════════════ ② bootstrap 终态镜像（静态） ══════════════════════════

def test_bootstrap_schema_mirrors_the_v111_end_state():
    """`docs/sql/schema.sql` 是新建库路径（**不跑迁移链**）⇒ 必须已是 V112 终态。"""
    schema = _read(SCHEMA_SQL)
    skus = schema[schema.index("CREATE TABLE product_skus ("):]
    skus = skus[:skus.index(");")]

    assert "selling_method" not in skus, (
        "bootstrap 的 `product_skus` 仍有 selling_method 列 —— 新建库与迁移链两条路径 schema 分叉")
    assert re.search(
        r"ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination\s*\n\s*"
        r"UNIQUE \(product_id, color_id, door_width\);", schema), (
        "bootstrap 的唯一键不是 (product_id, color_id, door_width)")

    products = schema[schema.index("CREATE TABLE products ("):]
    products = products[:products.index(");")]
    assert "selling_methods JSONB" in products, "bootstrap 的 products 缺 selling_methods"
    assert "roll_length_m NUMERIC(8,2)" in products, "bootstrap 的 products 缺 roll_length_m"

    items = schema[schema.index("CREATE TABLE order_items ("):]
    items = items[:items.index(");")]
    for col in ("selling_method VARCHAR(20)", "roll_count INTEGER", "roll_length_m NUMERIC(8,2)"):
        assert col in items, f"bootstrap 的 order_items 缺 {col}"


# ══════════════════════════ ③ 真库两遍幂等（临时 PG 集群） ══════════════════════════

_PG_BINARIES = ("initdb", "pg_ctl", "psql")

#: 与 V112 触碰的三张表同形的**最小** DDL（含**旧**唯一键 + 同色同门幅的重复行）
_DDL = """
CREATE TABLE products (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE product_colors (
    id BIGSERIAL PRIMARY KEY, tenant_id BIGINT, product_id VARCHAR(64), color_name VARCHAR(30));
-- ⚠️ `product_skus` **没有** `deleted` 列（真 schema 如此：删除走 deleteById = 物理删除，
-- `ProductSku` 无 @TableLogic）—— **不得**为「跑得通」而在夹具里补一列。
-- 本单第一版正是补了它，于是夹具把「回填写了 AND deleted = 0」这个真缺陷挡掉了：
-- 真库上该句抛「字段 deleted 不存在」⇒ 整份迁移回滚 ⇒ 而 MigrationRunner 跳过并继续
-- ⇒ 部署 success、三列永不建（#4402 同族）。夹具必须与真 schema 逐列一致才有判别力。
CREATE TABLE product_skus (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    product_id VARCHAR(64) NOT NULL,
    color_id BIGINT,
    selling_method VARCHAR(20) NOT NULL,
    door_width VARCHAR(20) NOT NULL,
    price DECIMAL(10,2) NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    sku_code VARCHAR(50),
    sales_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());
ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination
    UNIQUE (product_id, color_id, selling_method, door_width);
CREATE TABLE order_items (
    id VARCHAR(36) PRIMARY KEY, tenant_id BIGINT, order_id VARCHAR(36),
    quantity DECIMAL(10,2), deleted INTEGER NOT NULL DEFAULT 0);
"""

#: 真库形态的种子：
#:   · p1：同色同门幅**两行**（散剪 ¥100 / 整卷 ¥88）⇒ 去重必须保留**低价**那行（整卷，id 更大）；
#:   · p2：同色同门幅**两行同价**（id 2 vs 3）⇒ 去重必须保留 **id 最小**那行（确定性）；
#:   · p3：只有一个 SKU（散剪）⇒ 回填必须只得到 ["bulk_cut"]（不是无脑默认两种）；
#:   · p4：**没有 SKU** ⇒ 保持列默认 ["bulk_cut","full_roll"]（最宽口径）；
#:   · p5：**混合写法**（`full_roll` 与 `整卷` 并存，真库形态）⇒ 回填必须归一化后去重成
#:         ["full_roll"]（不归一化会得到 ["full_roll","整卷"]，让订单侧把「整卷」判成越界 422）。
_SEED = """
INSERT INTO products (id, tenant_id, name) VALUES
    ('p1', 1, '同色同门幅两档价'), ('p2', 1, '同色同门幅同价'),
    ('p3', 1, '只有散剪'), ('p4', 1, '没有 SKU'), ('p5', 1, '混合写法');
INSERT INTO product_skus (id, tenant_id, product_id, color_id, selling_method, door_width, price, stock) VALUES
    (1, 1, 'p1', 11, 'bulk_cut',  '2.8', 100.00, 5),
    (2, 1, 'p1', 11, 'full_roll', '2.8',  88.00, 7),
    (3, 1, 'p2', 12, 'bulk_cut',  '2.8',  50.00, 5),
    (4, 1, 'p2', 12, 'full_roll', '2.8',  50.00, 9),
    (5, 1, 'p3', 13, 'bulk_cut',  '3.2',  30.00, 1),
    -- p5：真库形态的**混合写法**（中文字面与英文枚举并存，取证见 .github/cases/processing-order.yml
    -- 的「真库 11 个取值 bulk_cut/散剪/full_roll/整卷/…」）⇒ 回填必须归一化后去重，
    -- 否则会得到 ["full_roll","整卷"]，而订单侧的「归一化后逐项相等」判据会把「整卷」判成越界。
    (6, 1, 'p5', 15, 'full_roll', '2.8',  60.00, 3),
    (7, 1, 'p5', 15, '整卷',       '3.2',  60.00, 3);
"""


def _pg_available() -> bool:
    return all(shutil.which(b) for b in _PG_BINARIES)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _PgCluster:
    """临时 PG 集群（unix socket，不占 TCP 端口）。

    ⚠️ 照 `tests/unit_ci_workflows/test_must_finish_retire_migration.py` 的**可用**范式，
    三处细节不能想当然（本单实测踩过，形态是「`pg_ctl` 永久阻塞」而不是报错）：

    1. **socket 目录必须短**：unix socket 路径有 ~104 字节上限，`tmp_path` 落在
       macOS `$TMPDIR`（`/var/folders/_t/…/T/`）下已经很长 ⇒ 用 `tempfile.mkdtemp(prefix=…)`
       建**短前缀**目录；
    2. **不加 `-w`**：`pg_ctl … -w start` 在本机等不到 postmaster 就绪信号（实测 60s 超时），
       改为不加 `-w` + 后续 `psql` 重试轮询；
    3. **`-l <logfile>`** 落日志，起不来时能把 postgres 的原文打出来（否则只有「起不来」）。
    """

    def __init__(self, tmp_path: Path):
        self.datadir = tmp_path / "pgdata"
        self.log = tmp_path / "pg.log"
        # ⚠️ 短前缀（见类注释 ①）
        self.sockdir = Path(tempfile.mkdtemp(prefix="pg108-"))
        self.port = _free_port()

    def __enter__(self):
        subprocess.run(["initdb", "-D", str(self.datadir), "-U", "postgres", "-A", "trust"],
                       check=True, capture_output=True, timeout=120)
        started = subprocess.run(
            ["pg_ctl", "-D", str(self.datadir), "-l", str(self.log), "-o",
             f"-k {self.sockdir} -p {self.port} -c listen_addresses=''", "start"],
            capture_output=True, text=True, timeout=120)
        assert started.returncode == 0, (
            f"临时集群起不来：{started.stdout}\n{started.stderr}\n"
            f"{self.log.read_text(encoding='utf-8') if self.log.exists() else ''}")
        # 就绪轮询（不加 -w 的代价；不用 sleep 盲等，直接问库）
        for _ in range(60):
            probe = self._raw("SELECT 1;")
            if probe.returncode == 0:
                break
        else:
            raise AssertionError("临时集群起来了但连不上（60 次探测均失败）")
        return self

    def __exit__(self, *exc):
        subprocess.run(["pg_ctl", "-D", str(self.datadir), "-m", "immediate", "stop"],
                       capture_output=True, timeout=120)
        shutil.rmtree(self.sockdir, ignore_errors=True)

    def _raw(self, sql: str) -> subprocess.CompletedProcess:
        """不抛异常的 psql 入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            ["psql", "-h", str(self.sockdir), "-p", str(self.port), "-U", "postgres",
             "-d", "postgres", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True, timeout=120)

    def run(self, sql: str) -> subprocess.CompletedProcess:
        return self._raw(sql)

    def run_file(self, path: Path) -> subprocess.CompletedProcess:
        return self._raw(path.read_text(encoding="utf-8"))

    def q(self, sql: str) -> str:
        r = self._raw(sql)
        assert r.returncode == 0, f"SQL 失败：{sql}\n{r.stdout}\n{r.stderr}"
        return r.stdout.strip()


@pytest.fixture
def pg(tmp_path):
    """**函数级**临时集群：每条用例一个干净库。

    ⚠️ 不能用 module 级：`_DDL` 是**非幂等**建表（`CREATE TABLE products` 无 IF NOT EXISTS，
    照真库形态写）⇒ 同一个库里跑第二条用例会因「表已存在」而红，而那红与被测行为无关。
    """
    if not _pg_available():
        pytest.skip("本机缺 initdb/pg_ctl/psql ⇒ 真库判据显式 skip（不伪装成通过）")
    with _PgCluster(tmp_path) as cluster:
        yield cluster


def _seed_and_migrate(pg) -> None:
    r = pg.run(_DDL + _SEED)
    assert r.returncode == 0, f"建表/种子失败：{r.stderr}"
    r = pg.run_file(V112)
    assert r.returncode == 0, f"V112 首次执行失败：{r.stderr}"


def test_v111_real_db_end_state(pg):
    """真库终态：列已删 / 唯一键两维 / 去重保低价 / 回填取旧真值。"""
    _seed_and_migrate(pg)

    # ① selling_method 列已消失
    assert pg.q("SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='product_skus' AND column_name='selling_method'") == "0"

    # ② 唯一键逐字为两维
    assert pg.q("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                f"WHERE conname='{UNIQUE_CONSTRAINT}'") == f"UNIQUE {UNIQUE_DEF}"

    # ③ 去重：p1 保留**低价**行（id=2，¥88 整卷）；p2 同价保留 **id 最小**（id=3）
    assert pg.q("SELECT id FROM product_skus WHERE product_id='p1' ORDER BY id") == "2"
    assert pg.q("SELECT id FROM product_skus WHERE product_id='p2' ORDER BY id") == "3"
    assert pg.q("SELECT count(*) FROM product_skus") == "5"

    # ④ 回填取旧真值：p1 两种都出现过；p3 只有散剪；p4 无 SKU ⇒ 保持列默认
    assert pg.q("SELECT selling_methods::text FROM products WHERE id='p1'") == '["bulk_cut", "full_roll"]'
    assert pg.q("SELECT selling_methods::text FROM products WHERE id='p3'") == '["bulk_cut"]'
    assert pg.q("SELECT selling_methods::text FROM products WHERE id='p4'") == '["bulk_cut", "full_roll"]'
    # p5：混合写法归一化后去重（同一档的中文字面与英文枚举合并成一条）
    assert pg.q("SELECT selling_methods::text FROM products WHERE id='p5'") == '["full_roll"]'
    assert pg.q("SELECT count(*) FROM products WHERE selling_methods IS NULL") == "0"

    # ⑤ roll_length_m 未配置（NULL）—— 本迁移不回填、不给默认
    assert pg.q("SELECT count(*) FROM products WHERE roll_length_m IS NULL") == "5"

    # ⑥ order_items 三列已加
    for col in ("selling_method", "roll_count", "roll_length_m"):
        assert pg.q("SELECT count(*) FROM information_schema.columns "
                    f"WHERE table_name='order_items' AND column_name='{col}'") == "1"


def test_v111_is_idempotent_on_second_run(pg):
    """第二遍必须净效果相同（`MigrationRunner` 硬要求所有迁移可重复执行）。"""
    _seed_and_migrate(pg)
    fingerprint_before = pg.q(
        "SELECT string_agg(id::text || ':' || price::text, ',' ORDER BY id) FROM product_skus")
    methods_before = pg.q("SELECT string_agg(id || '=' || selling_methods::text, ',' ORDER BY id) "
                          "FROM products")

    r = pg.run_file(V112)
    assert r.returncode == 0, f"V112 第二遍失败（不幂等）：{r.stderr}"

    assert pg.q("SELECT string_agg(id::text || ':' || price::text, ',' ORDER BY id) FROM product_skus") \
        == fingerprint_before, "第二遍改了 SKU 行（不幂等）"
    assert pg.q("SELECT string_agg(id || '=' || selling_methods::text, ',' ORDER BY id) FROM products") \
        == methods_before, "第二遍改了 selling_methods（不幂等）"


def test_v111_red_proof_dedup_is_required(pg):
    """注入红证 ①：**不去重**就建两维唯一键 ⇒ 建约束失败（证明「去重」不是装饰）。"""
    r = pg.run(_DDL + _SEED)
    assert r.returncode == 0
    # 只做「删列 + 建新唯一键」，跳过去重 —— p1 同色同门幅两行（删列后组合相同）
    r = pg.run("ALTER TABLE product_skus DROP CONSTRAINT uq_product_skus_combination;"
                "ALTER TABLE product_skus DROP COLUMN selling_method;"
                "ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination "
                "UNIQUE (product_id, color_id, door_width);")
    assert r.returncode != 0, "不去重竟然建成了两维唯一键 —— 那说明种子里没有重复组合（红证失效）"
    assert "uq_product_skus_combination" in r.stderr or "duplicate" in r.stderr.lower()


def test_v111_red_proof_wrong_constraint_is_not_silently_accepted(pg):
    """注入红证 ②：建出来的唯一键**列清单不对** ⇒ 终态对账必须抛（不许静默留一个错误的唯一键）。

    注入形态为什么是**触发器改写 DDL**（而不是「先建个错的再跑」）：
    V112 自己会 `DROP CONSTRAINT IF EXISTS uq_product_skus_combination`（摘掉旧四维约束），
    所以「事先建一个错的」会被它正常摘掉、走的是**正确**路径 —— 那样这条红证就**不成立**
    （本单第一版正是这么写的，实测红证失败，属 `migac-acceptance` 的「空断言」形态）。
    触发器在**本迁移真正执行 `ADD CONSTRAINT` 的那一刻**改写列清单，才能打到终态对账那条判据。
    """
    r = pg.run(_DDL + _SEED)
    assert r.returncode == 0
    # 注入：把本次 ADD CONSTRAINT 改写成四维（多一个 tenant_id）
    # ⚠️ 函数必须建在 **public**：event trigger 在独立上下文里跑，`pg_temp` 里的函数它看不见
    #    （实测：建在 pg_temp ⇒ 触发器静默不生效 ⇒ 红证恒绿）。
    r = pg.run("""
        CREATE FUNCTION public.wrong_cols() RETURNS event_trigger AS $f$
        DECLARE obj record;
        BEGIN
            FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP
                -- ⚠️ `object_identity` 是**表名**（实测 `public.product_skus`），不是约束名 ——
                -- 按约束名匹配会永不命中（本单第一版正是这么写的 ⇒ 红证恒绿 = 空断言）。
                IF obj.command_tag = 'ALTER TABLE'
                   AND obj.object_identity LIKE '%product_skus%'
                   AND EXISTS (SELECT 1 FROM pg_constraint
                                WHERE conname = 'uq_product_skus_combination'
                                  AND conrelid = 'product_skus'::regclass
                                  AND pg_get_constraintdef(oid) = 'UNIQUE (product_id, color_id, door_width)') THEN
                    EXECUTE 'ALTER TABLE product_skus DROP CONSTRAINT uq_product_skus_combination';
                    EXECUTE 'ALTER TABLE product_skus ADD CONSTRAINT uq_product_skus_combination '
                         || 'UNIQUE (product_id, color_id, door_width, tenant_id)';
                END IF;
            END LOOP;
        END $f$ LANGUAGE plpgsql;
        CREATE EVENT TRIGGER wrong_cols_trigger ON ddl_command_end
            WHEN TAG IN ('ALTER TABLE') EXECUTE FUNCTION public.wrong_cols();
    """)
    assert r.returncode == 0, f"注入失败（红证无效）：{r.stderr}"

    r = pg.run_file(V112)

    assert r.returncode != 0, (
        "唯一键列清单不对（多了 tenant_id）时 V112 竟然通过了 —— 终态对账没有判别力")
    assert "终态对账失败" in r.stderr, f"报错不是终态对账（判据打偏了）：{r.stderr[:400]}"
