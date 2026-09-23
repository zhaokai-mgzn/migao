# case_ids: MC-012
"""V81 补偿迁移（V3/V4 丢失的两笔意图回填）守卫 + **真库语义判据**（issue #4551）。

## 病根（取证来源：`acceptance/2026-09-19/4548-v2v3v4-intent/FINDINGS.md`）

`b11c172ad`（Flyway → 自研 `MigrationRunner`）把 V3 / V4 重建成了**占号空文件**，
而 `MigrationRunner` 的台账按**文件名**记账、这两个文件名是**新建**的
⇒ 对自研迁移器它们是**从未生效的 no-op**，且**无任何替代实现**。

- **V4（实质风险）**：`in_warehouse` 今天不是合法态 —— `ProductService.STATUS_TRANSITIONS`
  的键集不含它、`batchOnShelf`/`batchDelete` 允许集不含它、前端枚举已剔除
  ⇒ 存量行**永久卡死**（不能上架/下架/删除）且**不会变红**。
- **V3（附带）**：读时 `toEmployeeMap` 有兜底，但**绕过它的读取面**
  （`UserController.getCurrentUser` / `AuthService` 登录返回）**无兜底** ⇒ 老用户拿到空值。

## 本文件钉的判据（issue #4551 判据 1/2，**每条都有红证**）

| 判据 | 形态 | 红证（改坏 ⇒ 红） |
|---|---|---|
| V4 语义 | 构造 `status='in_warehouse'` 行 ⇒ 迁移后 `on_sale` | 删掉那条 UPDATE ⇒ `in_warehouse` 仍在 ⇒ 红 |
| V4 幂等 | 再跑一次 ⇒ 受影响 **0** 行 | 去掉 `WHERE` ⇒ 重跑命中全表 ⇒ 红 |
| V3 语义 | `position` 为 `NULL` / `''` 且 `role='manager'` ⇒ 迁移后 `position='manager'` | 删掉那条 UPDATE ⇒ 仍为 NULL ⇒ 红 |
| V3 不覆盖 | 已非空 `position`（`'custom'`）**不得被改写** | 去掉 `WHERE` ⇒ 被改成 `role` ⇒ 红 |
| V3 幂等 | 再跑一次 ⇒ 受影响 **0** 行 | 去掉 `WHERE` ⇒ 重跑命中全表 ⇒ 红 |

## ⚠️ 为什么必须**真库执行**（而不是只断言 SQL 文本）

判据 1/2 是**语义**判据（「迁移后这一行变成什么」+「重跑几行」）——
文本断言只能证明「文件里写了这句话」，证明不了「这句话在真库上把那一行改了、且重跑空转」。
本仓已有文本断言先例（`test_special_option_backfill_migration.py` 等），但那些钉的是**形态**
（按元素替换 / 保序 / 有守卫）；本单的判据是**效果**，故落真库。

真库由本文件**自建临时集群**（`initdb` + `pg_ctl`，unix socket 于临时目录，随机端口），
**只建本迁移用到的两列族的最小表**（不载 `backend/admin-api/src/main/resources/db/init/schema.sql`：那是 65 张表的大工程，
且本迁移的射程只有 `products.status` / `users.position` / `users.role`）。
跑完即 `pg_ctl stop` + 删临时目录。

⚠️ **环境边界（2026-09-23 改判，issue #5203）**：原口径「CI 的 `ci workflow helper unit tests`
job（`ubuntu-latest`）**不装 postgres server** ⇒ 本文件的真库判据会**显式 skip**、权威执行点是本地」
**已失效且正是病灶本身** —— 该 job 不装 PG **服务**，但 runner 镜像**自带 PG 二进制**
（`/usr/lib/postgresql/16/bin`，本文件起的是**一次性集群**、要的正是二进制）；
改前只有**硬编码兜底路径**的少数模块（含本文件）能跑起来，其余模块探测只认 `PATH` ⇒ 静默 skip 成绿。
现在发现与处置都收口在 `tests/unit_ci_workflows/pg_cluster.py`：CI 上缺 PG 判**红**、本机 skip。
文本判据在所有环境都跑。
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration-archive"
MIGRATION_NAME = "V81__compensate_lost_v3_v4_backfill.sql"

# Flyway 时代的原文出处（红证锚点用**不可变引用** `@<sha>`，不读 `origin/main` —— 它会随合并变）
FLYWAY_ERA_SHA = "5bb68d18b^"


def _migration_sql() -> str:
    path = MIGRATION_DIR / MIGRATION_NAME
    assert path.exists(), (
        f"规格锚点变了：找不到 {path} —— issue #4551 的补偿迁移（若改号，请同步本守卫）"
    )
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """剥掉 SQL 注释后再做文本判据（注释里**描述**被改的表/列是正常写法，不剥会假红）。"""
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return re.sub(r"--[^\n]*", " ", sql)


# ══════════════════════════════════════════════════════════════════════════════════════
# 文本判据（零依赖，所有环境都跑）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_migration_contains_the_two_lost_statements():
    """判据 0（自证）：本文件确实含**两条**UPDATE，且目标表是 `products` / `users`。"""
    sql = _strip_comments(_migration_sql())
    updates = re.findall(r"\bUPDATE\s+([a-z_][a-z0-9_]*)\b", sql, re.I)
    assert sorted(u.lower() for u in updates) == ["products", "users"], (
        f"预期恰好两条 UPDATE（products + users），实得 {updates} —— "
        f"缺任一条 = 对应那笔意图仍丢失（issue #4551 判据 1/2 直接红）"
    )


def test_v4_statement_matches_flyway_era_original():
    """判据 1（形态）：V4 那条与 Flyway 时代原文**逐字同语义**（`in_warehouse` → `on_sale`）。"""
    sql = _strip_comments(_migration_sql())
    m = re.search(r"UPDATE\s+products\s+SET\s+status\s*=\s*'([a-z_]+)'\s+WHERE\s+status\s*=\s*'([a-z_]+)'", sql, re.I)
    assert m, "找不到 `UPDATE products SET status = '<x>' WHERE status = '<y>'` 形态的语句"
    assert (m.group(1).lower(), m.group(2).lower()) == ("on_sale", "in_warehouse"), (
        f"V4 语义写反了：实得 status {m.group(2)!r} → {m.group(1)!r}；"
        f"原文（{FLYWAY_ERA_SHA}）是 in_warehouse → on_sale"
    )


def test_v3_statement_backfills_only_empty_positions():
    """判据 2（形态）：V3 那条**只补空值**（`position IS NULL OR position = ''`）且取自 `role`。"""
    sql = _strip_comments(_migration_sql())
    m = re.search(r"UPDATE\s+users\s+SET\s+position\s*=\s*role\s+WHERE\s+([\s\S]*?);", sql, re.I)
    assert m, "找不到 `UPDATE users SET position = role WHERE …` 形态的语句"
    where = m.group(1)
    assert re.search(r"position\s+IS\s+NULL", where, re.I), (
        "WHERE 缺 `position IS NULL` ⇒ NULL 行不会被回填（老用户仍拿到空值）"
    )
    assert re.search(r"position\s*=\s*''", where, re.I), (
        "WHERE 缺 `position = ''` ⇒ 空串行不会被回填（#4548 实测里空串与 NULL 都存在）"
    )
    assert " OR " in where.upper(), "两个条件必须是 OR（AND 会让判据恒不成立 = 空转）"


def test_migration_is_pure_data_migration_without_ddl():
    """判据 4（形态）：纯数据迁移 ⇒ **不得**含 DDL（`backend/admin-api/src/main/resources/db/init/schema.sql` 无需同步）。"""
    sql = _strip_comments(_migration_sql())
    ddl = re.findall(r"\b(ALTER\s+TABLE|CREATE\s+(?:TABLE|INDEX|UNIQUE\s+INDEX)|DROP\s+(?:TABLE|INDEX))\b", sql, re.I)
    assert not ddl, (
        f"数据回填迁移里出现了 DDL {ddl} ⇒ 本单是纯 `UPDATE`，改 schema 会让 "
        f"`backend/admin-api/src/main/resources/db/init/schema.sql` 的同步要求被触发（issue #4551 硬约束 4）"
    )


def test_migration_is_not_comment_only():
    """判据 5（#4543 同族）：迁移**不得只剩注释**（`MigrationRunner` 会把它记账成「已生效」）。"""
    sql = _strip_comments(_migration_sql())
    assert re.search(r"\bUPDATE\s+[a-z_]", sql, re.I), (
        "剥掉注释后没有任何 UPDATE —— 迁移空跑（#4543 的 V78 事故形态：脚本改写注释时截掉了 SQL）"
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# 真库语义判据（initdb + pg_ctl 临时集群）
# ══════════════════════════════════════════════════════════════════════════════════════

# 只建本迁移射程内的最小表（不载 schema.sql —— 65 张表与本迁移无关）
_MINIMAL_DDL = """
CREATE TABLE products (id VARCHAR(64) PRIMARY KEY, status VARCHAR(32));
CREATE TABLE users (id VARCHAR(64) PRIMARY KEY, role VARCHAR(64), position VARCHAR(64));
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Db:
    """一个临时 Postgres 集群（unix socket + 随机端口），只服务本文件的真库判据。"""

    def __init__(self, tmpdir: Path, initdb: str, pg_ctl: str, psql: str):
        self.tmpdir = tmpdir
        self.initdb = initdb
        self.pg_ctl = pg_ctl
        self.psql = psql
        self.data = tmpdir / "data"
        self.sock = tmpdir / "sock"
        self.sock.mkdir(parents=True, exist_ok=True)
        self.port = _free_port()
        self.dbname = "migao4551"

    def _psql(self, sql: str, dbname: str | None = None) -> str:
        cmd = [self.psql, "-h", str(self.sock), "-p", str(self.port), "-U", "migao",
               "-d", dbname or self.dbname, "-v", "ON_ERROR_STOP=1", "-Atc", sql]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        assert proc.returncode == 0, (
            f"psql 失败（sql={sql[:120]!r}）：\nSTDOUT:{proc.stdout}\nSTDERR:{proc.stderr}"
        )
        return proc.stdout.strip()

    def start(self) -> None:
        subprocess.run([self.initdb, "-D", str(self.data), "-U", "migao", "--auth=trust",
                        "-E", "UTF8", "--locale=C"], check=True, capture_output=True, text=True)
        subprocess.run([self.pg_ctl, "-D", str(self.data),
                        "-o", f"-p {self.port} -k {self.sock} -c listen_addresses=''",
                        "-l", str(self.tmpdir / "pg.log"), "-w", "start"],
                       check=True, capture_output=True, text=True)
        self._psql("SELECT 1", dbname="postgres")
        self._psql(f'CREATE DATABASE "{self.dbname}"', dbname="postgres")

    def stop(self) -> None:
        subprocess.run([self.pg_ctl, "-D", str(self.data), "-m", "immediate", "-w", "stop"],
                       capture_output=True, text=True)

    def setup_minimal_schema(self) -> None:
        self._psql(_MINIMAL_DDL)

    def run_migration(self) -> None:
        """按 `MigrationRunner` 的同款形态执行：**整个文件作为一条简单查询**发给 PG。

        ⚠️ 必须同款（`jdbc.execute(整个文件)`）—— 那样 PG 会把它包成**一个隐式事务**
        ⇒ 「文件里任何一条失败 ⇒ 整份回滚」（V76 注释里的本仓特有机制）。
        逐条 `psql -c` 会掩盖这个语义，测出来的就不是线上行为。
        """
        self._psql(_migration_sql())

    def query(self, sql: str) -> list:
        out = self._psql(sql)
        return [line.split("|") for line in out.split("\n") if line]


@pytest.fixture(scope="module")
def db(realdb_binaries):
    """真库夹具；缺 PG 的处置收口在 `pg_cluster.py`（CI 判**红** / 本机显式 skip，issue #5203）。"""
    with tempfile.TemporaryDirectory(prefix="migao-v81-pg-") as td:
        database = _Db(Path(td), realdb_binaries["initdb"],
                       realdb_binaries["pg_ctl"], realdb_binaries["psql"])
        # 集群起不来 = **红**（不是「未跑」）：CI 上「真库判据没跑」绝不能是绿（issue #5203）。
        # 与其余真库模块同款（那里的 `assert started.returncode == 0` 同样是红）。
        database.start()
        try:
            yield database
        finally:
            database.stop()


def test_real_db_harness_actually_ran(db):
    """自证：真库夹具真的起来了（防「夹具坏了 ⇒ 后面全 skip ⇒ 看起来像绿」）。"""
    assert db.query("SELECT 1") == [["1"]], "临时集群没起来 —— 后续真库判据全是假绿"


@pytest.fixture(scope="module")
def migrated(db):
    """建最小表 → 造存量行 → 跑一次迁移。返回 `(db, 第一次/第二次受影响行数)`。"""
    db.setup_minimal_schema()
    db.query(
        "INSERT INTO products (id, status) VALUES "
        "('p-in-warehouse-1', 'in_warehouse'), ('p-in-warehouse-2', 'in_warehouse'), "
        "('p-on-sale', 'on_sale'), ('p-draft', 'draft');"
    )
    db.query(
        "INSERT INTO users (id, role, position) VALUES "
        "('u-null-manager', 'manager', NULL), "
        "('u-empty-operator', 'operator', ''), "
        "('u-filled-custom', 'manager', 'custom'), "
        "('u-null-no-role', NULL, NULL);"
    )
    db.run_migration()
    return db


def test_v4_semantics_in_warehouse_becomes_on_sale(migrated):
    """判据 1a（V4 语义，**承重**）：`in_warehouse` 行 ⇒ 迁移后 `on_sale`。

    红证：把迁移里那条 `UPDATE products …` 删掉 ⇒ 这两行仍是 `in_warehouse` ⇒ 本断言红。
    """
    rows = migrated.query("SELECT id, status FROM products ORDER BY id")
    got = dict(rows)
    assert got["p-in-warehouse-1"] == "on_sale", (
        f"存量在库行未被迁到在售（实得 {got['p-in-warehouse-1']!r}）—— "
        f"这些行今天**永久卡死**（状态机拒绝、前端无选项、不能删），issue #4551 判据 1 红"
    )
    assert got["p-in-warehouse-2"] == "on_sale", f"第二行也没迁（实得 {got['p-in-warehouse-2']!r}）"
    # 对照面：其它状态**不得**被顺手改掉
    assert got["p-on-sale"] == "on_sale" and got["p-draft"] == "draft", (
        f"非 in_warehouse 的行被改动了（实得 {got}）—— 迁移的 WHERE 限定失效"
    )


def test_v3_semantics_null_and_empty_position_backfilled(migrated):
    """判据 2a（V3 语义）：`position` 为 NULL / `''` ⇒ 迁移后 = `role`。

    红证：删掉那条 `UPDATE users …` ⇒ `u-null-manager` 仍为 NULL ⇒ 本断言红。
    """
    rows = dict(migrated.query("SELECT id, COALESCE(position, '<NULL>') FROM users ORDER BY id"))
    assert rows["u-null-manager"] == "manager", (
        f"position IS NULL 的行没被回填（实得 {rows['u-null-manager']!r}）—— "
        f"绕过 toEmployeeMap 的读取面（getCurrentUser / 登录返回）拿到空值，issue #4551 判据 2 红"
    )
    assert rows["u-empty-operator"] == "operator", (
        f"position = '' 的行没被回填（实得 {rows['u-empty-operator']!r}）—— WHERE 少了空串分支"
    )


def test_v3_does_not_overwrite_non_empty_position(migrated):
    """判据 2b（V3 **不覆盖**）：已非空 `position` 不得被 `role` 改写。

    红证：去掉 `WHERE position IS NULL OR position = ''` ⇒ `u-filled-custom` 被改成 `'manager'` ⇒ 红。
    （这是「回填」与「覆盖商家数据」的分界线 —— 覆盖 = 静默改掉人工维护的岗位。）
    """
    rows = dict(migrated.query("SELECT id, position FROM users ORDER BY id"))
    assert rows["u-filled-custom"] == "custom", (
        f"已非空的 position 被覆盖成了 role（实得 {rows['u-filled-custom']!r}）—— "
        f"WHERE 限定失效，回填变成了**覆盖人工数据**"
    )
    # role 为 NULL 的行：position 保持 NULL（`position = role` 把 NULL 写成 NULL，不改语义）
    rows_null = dict(migrated.query("SELECT id, COALESCE(position, '<NULL>') FROM users ORDER BY id"))
    assert rows_null["u-null-no-role"] == "<NULL>", (
        f"role 为 NULL 的行被写成了非 NULL（实得 {rows_null['u-null-no-role']!r}）—— 凭空造值"
    )


def test_migration_is_idempotent_on_rerun(migrated):
    """判据 1b/2c（**幂等**）：重跑**不改动任何一行**；`role` 非空的行重跑受影响 **0** 行。

    判据形态用 CTE 把 `UPDATE` 的受影响行数**显式算出来**（真库给数），
    **不是**「再跑一次没报错」—— 后者对幂等是**空断言**（改写型非幂等 SQL 重跑照样不报错）。

    ⚠️ **一处如实登记的真库事实（不粉饰）**：`users.role` 是 **nullable** 的
    （`backend/admin-api/src/main/resources/db/init/schema.sql` 的 `CREATE TABLE users` 里 `role VARCHAR(64)` 无 `NOT NULL`；
    `User.role` 同样可空）。当 `role IS NULL AND position IS NULL` 时，
    `SET position = role` 把 NULL 写成 NULL ⇒ **数据不变，但 PG 照记 1 行受影响**。
    ⇒ 这种行**永远**会被计入受影响行数（重跑 1 行是**不可避免且无副作用**的）。
    本判据因此分两层，**两层都保留**（去掉任一层都会漏掉一种坏形态）：
      ① **数据层**（承重）：重跑前后**逐行逐列完全相同** —— 抓「重跑又改了一遍」；
      ② **行数层**：`role` 非空的行重跑受影响 **0** 行 —— 抓「WHERE 限定失效 ⇒ 命中全表」。

    红证：去掉任一条 WHERE 限定 ⇒ ① 被改写（`p-on-sale`/`p-draft` 被顺手改、
    `u-filled-custom` 被 role 覆盖）或 ② 命中全表 ⇒ 红。
    """
    sql = _strip_comments(_migration_sql())
    statements = re.findall(r"UPDATE\s+[a-z_][a-z0-9_]*\s+SET\s+[\s\S]*?;", sql, re.I)
    assert len(statements) == 2, f"预期 2 条 UPDATE，实得 {len(statements)}"

    before = {
        "products": migrated.query("SELECT id, status FROM products ORDER BY id"),
        "users": migrated.query("SELECT id, COALESCE(role,'<NULL>'), COALESCE(position,'<NULL>') "
                                "FROM users ORDER BY id"),
    }

    affected_by_table = {}
    for stmt in statements:
        table = re.search(r"UPDATE\s+([a-z_][a-z0-9_]*)", stmt, re.I).group(1).lower()
        # ⚠️ 不能写 `… RETURNING 1` 再数返回行：**0 行受影响时 RETURNING 一行都不返回**
        # ⇒ 那种写法对「0 行」与「语句没执行」不可区分（正是本仓「空断言」的形态）。
        counted = f"WITH u AS ({stmt.rstrip().rstrip(';')} RETURNING 1) SELECT count(*) FROM u;"
        affected_by_table[table] = int(migrated.query(counted)[0][0])

    after = {
        "products": migrated.query("SELECT id, status FROM products ORDER BY id"),
        "users": migrated.query("SELECT id, COALESCE(role,'<NULL>'), COALESCE(position,'<NULL>') "
                                "FROM users ORDER BY id"),
    }

    # ① 数据层：重跑不得改动任何一行（这是「幂等」的业务含义）
    for table in ("products", "users"):
        assert after[table] == before[table], (
            f"重跑改动了 `{table}` 的数据 ⇒ **不幂等**（迁移在已建好终态的库上再跑一遍会重复改写）：\n"
            f"  重跑前 {before[table]}\n  重跑后 {after[table]}"
        )

    # ② 行数层：`role` 非空的行必须 0 行（`role IS NULL` 的行见本测试 docstring 的登记）
    assert affected_by_table["products"] == 0, (
        f"重跑 `UPDATE products` 受影响 {affected_by_table['products']} 行（预期 0）"
        f"⇒ WHERE 限定失效（非幂等）"
    )
    role_null = migrated.query("SELECT count(*) FROM users WHERE role IS NULL")[0][0]
    assert affected_by_table["users"] == int(role_null), (
        f"重跑 `UPDATE users` 受影响 {affected_by_table['users']} 行，"
        f"而 `role IS NULL` 的行只有 {role_null} 行 ⇒ 多出来的行说明 WHERE 限定失效"
        f"（`position` 非空的行被重复写入）"
    )


def test_idempotency_check_would_catch_a_non_idempotent_rewrite(db):
    """**红证（注入式）**：把 WHERE 限定去掉后重跑**确实**会被抓到（本守卫不是摆设）。

    形态要求：这里**不得**写成「仓库当下恰有该缺陷」的真值主张 —— 那种断言修好即红、
    报错指向错误方向（`migao-acceptance`「断言形态」节明令）。
    ⇒ 在**独立的临时库**里注入一条**无 WHERE** 的改写，证明判据 ② 的机制会红。
    """
    db._psql("DROP DATABASE IF EXISTS idem_probe", dbname="postgres")
    db._psql("CREATE DATABASE idem_probe", dbname="postgres")
    db._psql(_MINIMAL_DDL, dbname="idem_probe")
    db._psql("INSERT INTO products (id, status) VALUES ('a','on_sale'), ('b','draft');",
             dbname="idem_probe")

    def _affected(stmt: str) -> int:
        counted = f"WITH u AS ({stmt.rstrip().rstrip(';')} RETURNING 1) SELECT count(*) FROM u;"
        return int(db._psql(counted, dbname="idem_probe"))

    # 非幂等形态（无 WHERE）：第二次执行**照样**命中全表
    non_idempotent = "UPDATE products SET status = 'on_sale';"
    assert _affected(non_idempotent) == 2, "第一次应命中 2 行"
    assert _affected(non_idempotent) == 2, (
        "无 WHERE 的改写第二次执行必须**仍命中全表** —— 若这里为 0，说明本判据的机制失效，"
        "`test_migration_is_idempotent_on_rerun` 就成了空断言"
    )
    # 对照面：带 WHERE 的形态第二次为 0
    idempotent = "UPDATE products SET status = 'on_sale' WHERE status = 'in_warehouse';"
    assert _affected(idempotent) == 0, "带 WHERE 的形态第二次必须 0 行（这才是幂等）"
