# case_ids: PG-018, MC-012
"""`V93` 补种迁移（issue #4714）的**承重判据** —— 工序库为空的租户不再被静默跳过出厂规则。

## 病根（真库实测 2026-09-20，PG 18.3 / 阿里云 RDS `ai_customer_service`）

`V72__switch_routing_model_consumers.sql` ⑤ 的按租户规则回填带一道**工序库护栏**
（`EXISTS (SELECT 1 FROM production_operations … 归一后 = r.operation)`），`V84` 的 3 条
`processing_item` 规则同款护栏 ⇒ 租户的工序库为空时**整批规则被静默跳过**：

| 租户 | `production_route_rules` | `production_operations` |
|---|---|---|
| 1 词元通达 | **29**（V71 的 26 + V84 的 3） | 36 |
| 20 米高POC演示布艺 | **0** | **0** |
| 21 POC彩排5605 | **0** | **0** |

后果 = 韩褶 / 打孔 / 四爪钩 / 穿杆 / 平幔 / 特殊选项（拼几次 / 花边 / 扣环 / 接高…）的工序
**静默不出现** = **少一道活、少一笔计件钱**，且**不报错**（本仓最忌的静默错误形态）。

## 本文件钉的五件事（各有红证，互不掩盖）

1. **红证（改前必红）**：真库形态下跑 V71 / V72 / V84 ⇒ 空工序库租户 **0 条**规则（静默跳过）；
   跑 V93 ⇒ 该租户 **29 条**出厂规则逐条出现；
2. **出厂真值 = 29 = V71 的 26（21 insert + 5 remove）∪ V84 的 3**，逐值比对（不是只数条数）；
3. **幂等**：V93 跑两次净效果相同（第二次零插入）；
4. **不覆盖商家已改**：商家改过/软删过某条规则 ⇒ V93 一字不动（**红证**：先改一条再跑，值不变）；
5. **三处口径一致**：迁移链终态（V93）↔ bootstrap 终态（`docs/sql/schema.sql`）↔ 出厂真值（V71∪V84）。

## 真库判据（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

`test_v93_*` 用 `initdb`/`pg_ctl`/`psql` 起**临时集群**真跑迁移 —— 静态文本判据不够
（V83 的教训：文本守卫全绿而真库整份回滚）。
"""
from __future__ import annotations

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
MIGRATION = MIGRATION_DIR / "V93__backfill_route_rules_for_empty_catalogs.sql"
V71 = MIGRATION_DIR / "V71__normalize_routing_model_structure.sql"
V72 = MIGRATION_DIR / "V72__switch_routing_model_consumers.sql"
V84 = MIGRATION_DIR / "V84__seed_processing_item_route_rules.sql"
SCHEMA = REPO / "docs/sql/schema.sql"

#: 规则字段（**不含 id**：id 是各迁移自己的槽位命名，出厂知识比的是业务字段）。
RULE_FIELDS = ("trigger_kind", "trigger_value", "position", "action",
               "operation", "after_operation", "priority")

#: 派生形态：`JOIN (VALUES …) AS r(rid, trigger_kind, …)`（V72 / V84 / V93 与 schema.sql 的 V93 段）
_DERIVED_BLOCK = re.compile(
    r"JOIN\s*\(VALUES(.*?)\)\s*AS\s*r\s*\(([^)]*)\)", re.S | re.I)
#: 字面量形态：`INSERT INTO <表> (cols) VALUES …`（V71 / V84 与 schema.sql 的终态段）
_LITERAL_BLOCK = re.compile(
    r"INSERT\s+INTO\s+production_route_rules\s*\(([^)]*)\)\s*VALUES(.*?)(?:ON\s+CONFLICT|;)",
    re.S | re.I)


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释。

    ⚠️ **必须**先剥注释：本迁移的注释里**逐字**引用了 `EXISTS (production_operations …)` /
    `JOIN (VALUES …) AS r(…)` / `ON TRUE` 等判据片段 ⇒ 不剥的话正则命中**注释**、
    判据变成空断言（改代码也照样绿）。
    """
    return re.sub(r"--[^\n]*", "", sql)


def _rows_of(block: str, columns: list) -> list:
    rows = []
    for raw in re.findall(r"\(([^()]*)\)", block):
        fields = [f.strip() for f in raw.split(",")]
        assert len(fields) == len(columns), f"字段数 ≠ 列数：{raw}"
        rows.append(dict(zip(columns, fields)))
    return rows


def _rule_rows(sql: str, *, required: bool = True) -> list:
    """解析**任一形态**的规则种子段 → 逐行 dict（列序**从 SQL 自己声明的清单读**，不写死）。

    两种形态都要认（否则判据只覆盖一半，另一半是空断言）：
      · **字面量**（V71 / V84 / `schema.sql` 的终态段）：`INSERT INTO <表> (cols) VALUES (…)`；
      · **派生**（V72 / V93 / `schema.sql` 的 V93 段）：`INSERT … SELECT … JOIN (VALUES …) AS r(cols) ON TRUE`。

    ⚠️ `schema.sql` 里有多条 `production_route_rules` 语句 ⇒ 字面量分支**逐条取第一个含全部
    规则字段的**（按 `id` 位置识别），不靠「第一条」。
    """
    text = _strip_comments(sql)
    match = _DERIVED_BLOCK.search(text)
    if match:
        columns = [c.strip() for c in match.group(2).split(",")]
        return _rows_of(match.group(1), columns)
    for cols_raw, block in _LITERAL_BLOCK.findall(text):
        columns = [c.strip() for c in cols_raw.split(",")]
        if not all(f in columns for f in RULE_FIELDS):
            continue
        return _rows_of(block, columns)
    assert not required, "没有可解析的规则种子段（字面量 / 派生两种形态都读不到）—— 判据会空跑"
    return []


def _norm(raw: str) -> str:
    """字面量归一化：去引号 / 去 `::varchar` / `::integer` 转型 / `NULL` 统一大写。"""
    value = raw.strip()
    value = re.sub(r"::(varchar|integer|numeric|text)$", "", value, flags=re.I).strip()
    if value.upper() == "NULL":
        return "NULL"
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _norm_rows(rows) -> list:
    """把各源的列集**补齐**到 `RULE_FIELDS`（缺列 ⇒ `NULL`）。

    ⚠️ 各迁移声明的列集**不同**：V71 有 `position`、V84 没有（它的 `position` 恒 NULL）、
    V93 有。不补齐 ⇒ `KeyError`（判据崩）或静默错位 —— 两者都不是「逐值比对」。
    """
    return [{f: row.get(f, "NULL") for f in RULE_FIELDS} for row in rows]


def _rule_key(row: dict) -> tuple:
    """规则业务键（出厂知识比的就是它）—— 与 `uk_production_route_rules_tenant_trigger_operation` 同序。"""
    return tuple(_norm(row[f]) for f in RULE_FIELDS)


def _factory_truth() -> list:
    """出厂真值 = **V71 的 26 条 ∪ V84 的 3 条**（从两份**已发布**种子迁移的文本里读，不写死）。

    ⚠️ 用 `required=True` fail-closed：任一份读不到 ⇒ 判据空跑（不是"恰好 0 条"）。
    """
    rows = []
    for path in (V71, V84):
        block = _rule_rows(path.read_text(encoding="utf-8"))
        assert block, f"{path.name} 里读不到规则种子段（出厂真值判据空跑）"
        rows += _norm_rows(block)
    return rows


def _by_key(rows) -> dict:
    out = {}
    for row in rows:
        out.setdefault(_rule_key(row), []).append(row)
    return out


# ══════════════════════ 静态判据（文本层） ══════════════════════

def test_v93_seeds_exactly_the_factory_truth():
    """判据 2：V93 的 29 行 **逐值** = 出厂真值（V71 的 26 ∪ V84 的 3），一条不多一条不少。"""
    got = _by_key(_norm_rows(_rule_rows(MIGRATION.read_text(encoding="utf-8"))))
    want = _by_key(_factory_truth())
    assert set(got) == set(want), (
        "V93 与出厂真值（V71 ∪ V84）不一致：\n"
        f"  V93 多出：{sorted(set(got) - set(want))}\n"
        f"  V93 缺失：{sorted(set(want) - set(got))}")
    assert len(want) == 29, f"出厂真值不是 29 条（21 insert + 5 remove + 3 processing_item）：{len(want)}"
    assert sum(1 for k in want if k[3] == "remove") == 5, "出厂真值里 remove 规则不是 5 条"


def test_v93_is_per_tenant_and_has_no_operation_catalog_filter():
    """判据 1（形态半边）：按租户 + `deleted = 0` + **刻意不带**工序库护栏（那是本缺陷的成因）。"""
    sql = _strip_comments(MIGRATION.read_text(encoding="utf-8"))
    assert re.search(r"FROM\s+tenants\s+t\b", sql, re.I), "没有按租户循环（`FROM tenants`）"
    assert re.search(r"WHERE\s+t\.deleted\s*=\s*0", sql, re.I), "没限定 `t.deleted = 0`"
    assert not re.search(r"FROM\s+production_operations\b", sql, re.I), (
        "V93 不得带工序库护栏（`EXISTS (production_operations …)`）—— 那正是「工序库为空 ⇒ "
        "整批规则静默跳过」的成因；工序库由 V91（issue #4707）补")
    assert re.search(r"AS\s+r\s*\([^)]*\)\s*ON\s+TRUE", sql, re.I), (
        "`JOIN (VALUES …) AS r(…)` 缺 `ON TRUE` ⇒ 真库语法错误、整份迁移回滚（V83 实测 P0）")
    assert re.search(r"ON\s+CONFLICT\s*\(id\)\s*DO\s+NOTHING", sql, re.I), "缺 `ON CONFLICT (id) DO NOTHING`"
    assert re.search(r"NOT\s+EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+production_route_rules\s+e\b", sql, re.I), \
        "缺业务键 `NOT EXISTS` 去重（幂等双保险的另一半 / 不覆盖商家已改的承重点）"
    # 只写不覆盖：不得有 UPDATE / DELETE（商家改过的规则一字不动）
    assert not re.search(r"\bUPDATE\s+production_route_rules\b", sql, re.I), \
        "V93 不得 UPDATE 规则表（红线：绝不覆盖商家已改）"
    assert not re.search(r"\bDELETE\s+FROM\s+production_route_rules\b", sql, re.I), \
        "V93 不得 DELETE 规则表（红线：只补缺失）"
    # 类型显式（V79 真库事故：整列 NULL 被推断成 text ⇒ 整文件回滚）
    assert re.search(r"NULL::varchar", sql, re.I) and re.search(r"::integer", sql, re.I), \
        "`position` / `after_operation` / `priority` 必须逐行显式转型（V79 的 text/numeric 事故同款）"


def test_bootstrap_schema_sql_carries_the_same_factory_truth():
    """判据 5：bootstrap 终态（`docs/sql/schema.sql`，该路径**不跑迁移链**）逐值同款。

    ⚠️ bootstrap **不需要** V93 的段落：该文件的 V72 ⑤ 回填块 + V84 块已经在**建库那一刻**
    给每个租户落齐 26 + 3 条（`schema.sql` 的 `tenants` 是空集也无所谓 —— 回填是
    `FROM tenants t`，后续开租时租户行已存在；「先建库、后开租」的时序下由
    `ProductionSeedTemplateService` 承接）。本判据机械核验的正是这一点：
    **bootstrap 侧 26 + 3 = 29 = 迁移链终态（V93）= 出厂真值**（三处口径一致）。
    """
    sql = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
    # 逐段找 `JOIN (VALUES …) AS r(…)`（**段内**首次命中）：不整文件取首个 ——
    # 本文件有多条派生种子段（V72 的 26 条 / V84 的 3 条），整文件取首个只会读到其中一段。
    got = []
    for chunk in re.findall(r"INSERT INTO production_route_rules(.*?);", sql, re.S):
        match = re.search(r"JOIN\s*\(VALUES(.*?)\)\s*AS\s*r\s*\(([^)]*)\)", chunk, re.S | re.I)
        if not match:
            continue
        columns = [c.strip() for c in match.group(2).split(",")]
        got += _norm_rows(_rows_of(match.group(1), columns))
    assert got, "schema.sql 里读不到规则种子段（判据会空跑）"

    want = _by_key(_factory_truth())
    got_keys = _by_key(got)
    assert set(got_keys) == set(want), (
        "schema.sql 的 bootstrap 终态与出厂真值（V71 ∪ V84）不一致：\n"
        f"  多出：{sorted(set(got_keys) - set(want))}\n  缺失：{sorted(set(want) - set(got_keys))}")
    assert len(got_keys) == 29, f"bootstrap 终态不是 29 条：{len(got_keys)}"


def test_guard_detects_injected_drift():
    """红证：删一条 / 改一个锚点 / 去掉 `ON TRUE` / 塞回工序库护栏 ⇒ 对应判据必红（不是空断言）。"""
    sql = MIGRATION.read_text(encoding="utf-8")
    want = _by_key(_factory_truth())

    # ① 删一条（守卫能抓「规则条数不足」—— 本单验收判据的机械形态）
    dropped = sql.replace(
        "      ('26', 'option', '防翘扣',     NULL::varchar, 'insert', '防翘扣',    '三边', 260::integer),\n", "")
    assert dropped != sql, "注入「删一条」没生效 ⇒ 判据是空断言"
    assert set(_by_key(_norm_rows(_rule_rows(dropped)))) != set(want), "删一条后仍判「一致」⇒ 条数判据是空断言"

    # ② 改一个锚点（值漂移）
    moved = sql.replace("'insert', '花边', '三边', 270::integer", "'insert', '花边', '车被', 270::integer")
    assert moved != sql and set(_by_key(_norm_rows(_rule_rows(moved)))) != set(want), \
        "改锚点后仍判「一致」⇒ 逐值判据是空断言"

    # ③ 去掉 `ON TRUE`（真库语法错 ⇒ 整份回滚）
    no_on = _strip_comments(sql.replace("    ON TRUE\n", ""))
    assert not re.search(r"AS\s+r\s*\([^)]*\)\s*ON\s+TRUE", no_on, re.I), "去掉 `ON TRUE` 判据读不出来"

    # ④ 塞回工序库护栏（本缺陷的成因）
    with_guard = _strip_comments(sql.replace(
        " WHERE t.deleted = 0\n", " WHERE t.deleted = 0\n   AND EXISTS (SELECT 1 FROM production_operations o)\n", 1))
    assert re.search(r"FROM\s+production_operations\b", with_guard, re.I), \
        "「不得带工序库护栏」判据读不出来 ⇒ 本缺陷会原地复发而守卫不红"

    # 注释剥离本身也是判据（否则「改代码但注释还在」会让判据恒绿）
    assert "ON TRUE" in _strip_comments(sql), "剥注释后正文里必须仍有 `ON TRUE`"


# ══════════════════════ 真库判据（本机 PG 二进制；缺则显式 skip） ══════════════════════

_PG_BINARIES = ("initdb", "pg_ctl", "psql")

#: 与 V71 / V72 同形的**最小** DDL（只建本单触碰的三张表 + 那条部分唯一索引 + V72 的两处放宽）。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active',
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_route_rules (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(24) NOT NULL
        CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item')),
    trigger_value VARCHAR(64) NOT NULL, position VARCHAR(16),
    action VARCHAR(16) NOT NULL CHECK (action IN ('insert', 'remove')),
    operation VARCHAR(64) NOT NULL, after_operation VARCHAR(64),
    priority INTEGER NOT NULL DEFAULT 100, status VARCHAR(16) NOT NULL DEFAULT 'active',
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_route_rules_tenant_trigger_operation
    ON production_route_rules (tenant_id, trigger_kind, trigger_value,
                               COALESCE(position, ''), action, COALESCE(operation, ''))
    WHERE deleted = 0;
-- 快照表（**红线：本迁移一字不动**）—— 建出来才能机械核验「行数没变」
CREATE TABLE processing_orders (id VARCHAR(64) PRIMARY KEY, items_snapshot JSONB);
CREATE TABLE processing_position_operations (id VARCHAR(64) PRIMARY KEY, unit_price NUMERIC(10,2));
CREATE TABLE production_work_logs (id VARCHAR(64) PRIMARY KEY, unit_price NUMERIC(10,2),
                                   factor NUMERIC(6,3));
"""

#: 1 号租户的工序库（V54 形态的**子集**：规则引用到的逻辑工序各有变体名）。
_TENANT1_OPS = ("精裁-布", "布三边", "纱三边", "韩褶-布", "上车布-布", "打孔-布",
                "拼1次-布", "拼2次-布", "拼3次-布", "花边-布", "铅坠-布", "接高-布",
                "帘头制作", "熨烫-布", "定型-布", "复烫-布", "布帘车被", "外帘打卷",
                "外帘装袋", "外帘发货", "绑带-布", "抱枕", "logo条-布", "立边-布",
                "扣环-布", "防翘扣-布")


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
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限（实测：tmp_path 太长 ⇒ `pg_ctl start` 失败）。
    sockdir = Path(tempfile.mkdtemp(prefix="pg4714-"))
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
        proc = subprocess.run(
            ["psql", "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
             "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    try:
        yield run
    finally:
        subprocess.run(["pg_ctl", "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


def _rules_of(psql, tenant_id: int) -> list:
    out = psql(f"""
        SELECT trigger_kind || '|' || trigger_value || '|' || COALESCE(position, 'NULL') || '|'
               || action || '|' || operation || '|' || COALESCE(after_operation, 'NULL') || '|'
               || priority
          FROM production_route_rules
         WHERE tenant_id = {tenant_id} AND deleted = 0
         ORDER BY priority, id;
    """)
    return [line for line in out.split() if line]


def _seed_tenants_and_ops(psql) -> None:
    """1 号租户工序库齐全；20 / 21 号租户工序库为空（= 真库实测的形态）。"""
    ops = ",".join(f"('op-{i}', 1, '{name}')" for i, name in enumerate(_TENANT1_OPS))
    psql(f"INSERT INTO tenants (id) VALUES (1), (20), (21);"
         f"INSERT INTO production_operations (id, tenant_id, name) VALUES {ops};")


def _strip_statements_touching(sql: str, tables) -> str:
    """删掉**引用到**这些表的语句（按 `;` 切段）—— 本 harness 的 DDL 只建本单触碰的表。

    ⚠️ 逐段判断（不是按「表名紧跟在动词后」的正则）：V72 的系数档回填是
    `INSERT INTO production_route_rules … JOIN production_option_factors f ON …` ——
    按动词+表名的正则会漏掉它，psql 当场报「关系不存在」（实测）。
    被删的段落与本单的判据无关；**V72 的规则回填段与 V84 全文原样执行**。
    """
    kept = []
    for chunk in re.split(r"(?<=;)\s*\n", sql):
        if any(re.search(r"\b" + re.escape(t) + r"\b", _strip_comments(chunk)) for t in tables):
            continue
        kept.append(chunk)
    return "\n".join(kept)


def _run_real_v72_and_v84(psql) -> None:
    """真跑 V72 / V84 的**规则回填段**（其余段落的表不在本 harness 的 DDL 里，整段略过）。

    ⚠️ 剥离是**按段**的（不是删判据）：V72 的规则段与 V84 全文原样执行 ⇒ 红证测的是真 SQL。
    """
    psql(_strip_statements_touching(
        V72.read_text(encoding="utf-8"),
        ("production_operation_positions", "production_route_templates",
         "production_crafts", "production_option_factors")))
    psql(V84.read_text(encoding="utf-8"))


def test_before_v93_empty_catalog_tenants_are_silently_skipped(psql):
    """🔴 红证（改前必红）：真库形态下，空工序库租户的出厂规则**整批静默跳过**（0 条，不报错）。"""
    psql(_DDL)
    _seed_tenants_and_ops(psql)
    _run_real_v72_and_v84(psql)

    assert len(_rules_of(psql, 1)) == 29, "1 号租户（工序库齐全）应拿到 26 + 3 = 29 条出厂规则"
    assert _rules_of(psql, 20) == [], (
        "红证失效：租户 20 的工序库为空时本应**一条规则都没有**（静默跳过）—— "
        "若这里已经有规则，说明 V72/V84 的护栏已被改（那是已发布迁移，不可改）")
    assert _rules_of(psql, 21) == [], "红证失效：租户 21 同上"


def test_v93_runs_on_real_postgres_and_backfills_empty_catalog_tenants(psql):
    """判据 1/2/3 真库：V93 后空工序库租户拿到 29 条出厂规则；重跑空转（幂等）。"""
    psql(_DDL)
    _seed_tenants_and_ops(psql)
    _run_real_v72_and_v84(psql)
    migration_sql = MIGRATION.read_text(encoding="utf-8")

    psql(migration_sql)
    for tenant in (1, 20, 21):
        got = _rules_of(psql, tenant)
        assert len(got) == 29, f"租户 {tenant} 的出厂规则不是 29 条：{len(got)}\n{got}"
        assert got == sorted(got, key=lambda line: int(line.rsplit("|", 1)[1])), \
            f"租户 {tenant} 的 priority 序漂移（顺序敏感：锚点先后决定工序位置）"

    # 幂等：重跑空转（不新增、不报错、不复活软删）
    before = psql("SELECT count(*) FROM production_route_rules WHERE deleted = 0;").strip()
    psql(migration_sql)
    after = psql("SELECT count(*) FROM production_route_rules WHERE deleted = 0;").strip()
    assert before == after == "87", f"重跑不幂等：{before} → {after}（应为 29 × 3 租户 = 87）"

    # 快照表**一字不动**（红线）：本迁移只写配置表
    psql("INSERT INTO processing_orders (id, items_snapshot) VALUES ('po-1', '[]'::jsonb);"
         "INSERT INTO processing_position_operations (id, unit_price) VALUES ('ppo-1', 1.00);"
         "INSERT INTO production_work_logs (id, unit_price, factor) VALUES ('wl-1', 1.00, 1.0);")
    snap_before = psql("SELECT (SELECT count(*) FROM processing_orders) || '/' ||"
                       " (SELECT count(*) FROM processing_position_operations) || '/' ||"
                       " (SELECT count(*) FROM production_work_logs);").strip()
    psql(migration_sql)
    snap_after = psql("SELECT (SELECT count(*) FROM processing_orders) || '/' ||"
                      " (SELECT count(*) FROM processing_position_operations) || '/' ||"
                      " (SELECT count(*) FROM production_work_logs);").strip()
    assert snap_before == snap_after, f"快照表被动了（红线）：{snap_before} → {snap_after}"


def test_v93_does_not_overwrite_merchant_edits(psql):
    """判据 4（红证）：商家改过 / 软删过的规则 ⇒ 重跑 V93 一字不动、不复活。

    形态与 `test_v84_runs_on_real_postgres_and_is_idempotent_per_tenant` 同款：先让迁移把行种下，
    再让商家改 / 软删，然后**重跑**迁移 —— 这才是「补种 vs 商家数据」的真实时序
    （先改后补的写法只会测到「该行本来就还不存在」，是空断言）。
    """
    psql(_DDL)
    _seed_tenants_and_ops(psql)
    _run_real_v72_and_v84(psql)
    migration_sql = MIGRATION.read_text(encoding="utf-8")

    psql(migration_sql)                      # 先补种（20 号租户拿到 29 条）
    assert len(_rules_of(psql, 20)) == 29

    # ① 商家把 20 号租户的「韩褶 insert 韩褶」锚点从 `三边` 改成 `精裁`（改过）
    psql("UPDATE production_route_rules SET after_operation = '精裁'"
         " WHERE tenant_id = 20 AND trigger_kind = 'craft' AND trigger_value = '韩褶'"
         "   AND action = 'insert' AND operation = '韩褶' AND deleted = 0;")
    # ② 商家把 20 号租户的「防翘扣」整条软删（删过）
    psql("UPDATE production_route_rules SET deleted = 1"
         " WHERE tenant_id = 20 AND trigger_value = '防翘扣' AND deleted = 0;")

    psql(migration_sql)                      # 重跑：不得覆盖 / 不得复活

    kept = [r for r in _rules_of(psql, 20) if r.startswith("craft|韩褶|")]
    assert any(r.endswith("|精裁|10") for r in kept), (
        f"商家改过的锚点被覆盖了（红线）：{kept}")
    assert not any(r.startswith("option|防翘扣|") for r in _rules_of(psql, 20)), \
        "商家软删过的规则被种子复活了（红线）"
    # 其余 27 条照常（29 − 改过 1 − 软删 1）—— 补齐与不覆盖同时成立
    # ⚠️ 实测 **28** 而不是 27：软删行**仍占主键槽位** ⇒ `NOT EXISTS` 判「该插」而 `ON CONFLICT (id)`
    #    收敛成无操作 ⇒ 活跃行少 1、**不被复活**（与 V84 的 `test_v84_...` 同款实测）。
    assert len(_rules_of(psql, 20)) == 28, \
        f"除商家改/删的 2 条外应补齐（活跃 28 = 29 − 软删 1），实测 {len(_rules_of(psql, 20))}"


def test_bootstrap_schema_sql_rule_blocks_run_on_real_postgres(psql):
    """判据 5 真库：bootstrap（不跑迁移链）的规则回填段**真能执行**，且给空工序库租户落齐 29 条。

    ⚠️ bootstrap 侧的 29 条 = **V72 ⑤ 的 26 条 + V84 的 3 条**（该文件本就是终态镜像，不需要
    V93 的段落）—— 本判据把它**真跑一遍**并与出厂真值逐值比对（文本层判据不够，见 V83 的教训）。
    """
    psql(_DDL)
    _seed_tenants_and_ops(psql)
    stmts = [stmt for stmt in re.findall(
        r"INSERT INTO production_route_rules.*?;",
        _strip_comments(SCHEMA.read_text(encoding="utf-8")), re.S)
        if "JOIN" in stmt and "VALUES" in stmt]
    assert stmts, "schema.sql 里取不到规则回填段"
    for stmt in stmts:
        psql(stmt)

    want = sorted("|".join(_rule_key(r)) for r in _factory_truth())
    for tenant in (1, 20, 21):
        got = sorted(_rules_of(psql, tenant))
        assert got == want, (
            f"bootstrap 终态在租户 {tenant} 上 ≠ 出厂真值（29 条）：\n"
            f"  实测 {len(got)} 条 / 期望 {len(want)} 条\n"
            f"  多出：{sorted(set(got) - set(want))}\n  缺失：{sorted(set(want) - set(got))}")


if __name__ == "__main__":  # pragma: no cover - 手工排查入口
    sys.exit(pytest.main([__file__, "-q"]))
