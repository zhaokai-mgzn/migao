# case_ids: PG-018, PG-020, PG-035
"""「加回适用条件的**部位维**」（issue #4962）两条迁移的**承重判据** + 真库两遍幂等 + bootstrap 终态镜像。

（父单 #4936；上一单 #4937 的 O2 曾把该维整体退场，本单**有界**回归 —— 只写回种子里那一条。）

## 本文件钉的事

| 迁移 | 做什么 | 本文件的判据 |
|---|---|---|
| `V108__restore_route_rule_positions.sql` | 每个**活跃租户**上把**唯一**那条部位限定规则（`craft`/`韩褶`/`insert`/`上车布`/锚 `韩褶`）写回 `position = '布帘'` | ① 静态：恰好一条 `UPDATE`；`SET` 列**恰好** `['position','updated_at']`；含 `BEGIN`/`COMMIT`/`RAISE EXCEPTION`；含 `r.position IS NULL` 幂等谓词；不含 `DROP COLUMN`；谓词逐字与 **V71 冻结种子**同源；② 真库：两遍幂等（命中 2 → 0）、终态对账、**非 1 号租户**一并拿回、软删行与「商家已写过的值」不动、`customer_unit_price` 与**行数**不变；③ 注入红证（见文末表） |
| `V109__allow_position_trigger_kind.sql` | 放开 `production_route_rules.trigger_kind` 的**表级 CHECK 闭词表**，加第 4 档 `position` | ① 静态：`BEGIN`/`COMMIT`、**可执行语句里没有任何 `INSERT`/`UPDATE`/`DELETE`**（只改约束、不动数据）、含 `DROP CONSTRAINT` 与逐字 `'position'`；② 真库：改前插 `trigger_kind='position'` **必被拒**（`23514`，即红证前提）⇒ 改后插入成功；两遍幂等且**约束恰好一条**；闭词表**仍是闭的**（`bogus` 仍被拒）；**规则行数不变** |
| bootstrap 镜像 | `docs/sql/schema.sql`（`docker-entrypoint-initdb.d`，**不跑迁移链**）必须**自己就是终态** | ① `rr-v70-*` 26 行字面量里**有且只有 1 行**非 `NULL`（`rr-v70-02` = `'布帘'`）；② 闭词表含 `position`，且与 V109 的 `ADD CONSTRAINT` **逐字**同款；③ 把 bootstrap 的 26 行字面量喂进真库 + 跑 V103 ⇒ V108 ⇒ 终态与 bootstrap **逐值**相等 |

## 为什么必须真跑真库

`MigrationRunner` 要求**所有**迁移可重复执行，而「幂等」只有真库能判：
`GET DIAGNOSTICS ROW_COUNT` 与 `DO $$ … $$` 的交互、`RAISE EXCEPTION` 的**回滚半径**
（写语句必须一起回滚，不能留半完成态）、`pg_constraint` 上 `DROP`+`ADD` 的**幂等分支**、
以及 CHECK 约束的**触发时机** —— 四者都是**运行期**语义。静态文本判据不够
（V83 的教训：文本守卫全绿而真库整份回滚）。

## 真库夹具（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

照 `tests/unit_ci_workflows/test_deposition_total_migration.py` 与
`tests/unit_ci_workflows/test_must_finish_retire_migration.py` 的既有形态：
`initdb` / `pg_ctl` / `psql` 起**临时集群**（unix socket，不占 TCP 端口）。

## 红证（每条断言都能**单独**变红；注入法逐条列出）

| 断言 | 注入法 | 预期变红的读数 |
|---|---|---|
| `test_v108_shape_is_clean`（SET 只有两列） | 往 `SET` 里加 `customer_unit_price = 0` | `_v108_violations()` 报「SET 列 = [position, updated_at, customer_unit_price]」+「碰了 customer_unit_price」 |
| 同上（幂等谓词） | 删掉写语句里的 `AND r.position IS NULL` | `_v108_violations()` 报「缺幂等谓词」 |
| 同上（不 DROP 列） | 注入 `ALTER TABLE … DROP COLUMN position;` | `_v108_violations()` 报「出现 DROP COLUMN」 |
| `test_v108_is_idempotent…`（第二遍 0 行） | 删掉写语句的 NULL 闸（`AND r.position IS NULL`） | 第二遍 `claimed_rows = 2 ≠ 0` |
| `test_v108_restores_…`（商家已写值不动） | 同上（删掉 NULL 闸） | 那条商家行**进入写语句射程** ⇒ 撞部分唯一索引 `uk_production_route_rules_tenant_trigger_operation` ⇒ 迁移失败并回滚 |
| `test_v108_reconciliation_blocks_a_partial_write` | 给写语句加 `AND r.id <> 'rr-v93-2-02'` | `RAISE EXCEPTION`（`终态对账失败`）+ 整份回滚（数据一字未变） |
| `test_v109_shape_is_clean`（闭词表逐字 `'position'`） | 从 `ADD CONSTRAINT` 的闭词表里删掉 `'position'` | `_v109_violations()` 报「缺 `'position'`」 |
| 同上（不动数据） | 注入 `UPDATE production_route_rules SET position = NULL;` | `_v109_violations()` 报「出现 `UPDATE`」 |
| `test_v109_lets_position_trigger_kind_rows_land…`（改前必被拒） | 不注入 —— 夹具本身就是「V109 之前」的表（内联 CHECK 无 `position`） | 改前那条 INSERT 的 `returncode != 0` 且 stderr 点名 `production_route_rules_trigger_kind_check` |
| 同上（闭词表仍是闭的） | 把 V109 的 ADD CONSTRAINT 换成恒真式（如 `CHECK (trigger_kind <> '')`） | `bogus` 行**插得进去** ⇒ 反向护栏红 |

## 如实登记的边界

- V108 的 `DO` 块对账用**与写语句逐字同一份判据**（同 `V103` 的形态）⇒ 它能抓
  「写语句被改窄、对账没同步」这类**漂移**；但**抓不住**「写语句的闸被整体放宽」
  （两处一起放宽 ⇒ 对账跟着放宽 ⇒ 不抛）。那一形态由本文件的**真库幂等读数**兜
  （见上表第 4 行）—— 这是有意的分工，不是判据漏项。
- 静态判据**不能**替代真库执行（`GET DIAGNOSTICS` 的行数、约束的 `DROP`+`ADD` 顺序、
  事务回滚半径都只有真库能判）。
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
V71 = MIGRATION_DIR / "V71__normalize_routing_model_structure.sql"
V108 = MIGRATION_DIR / "V108__restore_route_rule_positions.sql"
V109 = MIGRATION_DIR / "V109__allow_position_trigger_kind.sql"
SCHEMA_SQL = REPO / "docs/sql/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"

TABLE = "production_route_rules"
#: V108 写回的那个值（逐字；与 V71 冻结种子 / `docs/sql/schema.sql` 三处必须一致）
RESTORED_VALUE = "布帘"
#: 那条规则的**形态**（谓词的业务部分；id 前缀因租户而异 ⇒ 不能按 id 匹配）
SHAPE = [("trigger_kind", "craft"), ("trigger_value", "韩褶"),
         ("action", "insert"), ("operation", "上车布"), ("after_operation", "韩褶")]
#: V109 放开后的闭词表（逐字；与 `docs/sql/schema.sql` 的 CHECK 同款）
TRIGGER_KIND_VOCAB = "('craft', 'option', 'shaped', 'processing_item', 'position')"

#: `rr-v70-*` 种子行形态（V71 与 `docs/sql/schema.sql` 同形；`position` / `operation` /
#: `after_operation` 三列可能是裸 `NULL`，也可能是自带引号的字面量）。
_RULE_ROW_RE = re.compile(
    r"\(\s*'(?P<id>rr-v70-\d+)'\s*,\s*(?P<tenant>\d+)\s*,\s*'(?P<kind>[^']*)'\s*,\s*"
    r"'(?P<value>[^']*)'\s*,\s*(?P<position>NULL|'[^']*')\s*,\s*'(?P<action>[^']*)'\s*,\s*"
    r"(?P<operation>NULL|'[^']*')\s*,\s*(?P<after>NULL|'[^']*')\s*,\s*(?P<priority>\d+)\s*,\s*"
    r"'(?P<status>[^']*)'\s*\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释（`--` 行注释与 `/* */` 块注释）→ 空，供**写语句**判据用。

    ⚠️ 必须去注释：本仓迁移把「回滚 SQL」写在注释里（V108 的回滚段里就有一条 `UPDATE`，
    V109 的回滚段里有 `DROP CONSTRAINT` / `ADD CONSTRAINT`），不去注释会把注释里的语句
    当成真语句（#4595 的同族教训：判据与实现一起漂移）。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


def _rule_rows(sql: str) -> list:
    """`rr-v70-*` 种子字面量行 → [{id, position, …}]（锚定 id 前缀，避免误吃别处的括号）。"""
    return [m.groupdict() for m in _RULE_ROW_RE.finditer(sql)]


def _as_literal(position: str) -> str:
    """值 → **种子字面量**形态（真库回读的 `<null>` → `NULL`；`布帘` → `'布帘'`）。

    ⚠️ 已经带引号的字面量（来自 `_rule_rows` 的 `position` 组）**原样返回** ——
    再包一层会得到 `''布帘''`，把「同一份数据两种书写」误判成漂移（本仓最忌的假红）。
    """
    p = position.strip()
    if p.upper() in ("NULL", "<NULL>"):
        return "NULL"
    if len(p) >= 2 and p.startswith("'") and p.endswith("'"):
        return p
    return "'" + p + "'"


def _set_columns(stmt: str) -> list:
    """`UPDATE … SET <列> = …, <列> = … FROM …` 里被赋值的列名（小写、按出现序）。"""
    m = re.search(r"\bSET\b([\s\S]*?)\bFROM\b", stmt, re.I)
    assert m, f"写语句里找不到 `SET … FROM`（判据无法建立）：{stmt}"
    return [c.lower() for c in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", m.group(1))]


# ══════════════════ 判据本体（纯函数 ⇒ 可注入式自证「它会红」） ══════════════════

def _v108_violations(body: str) -> list:
    """V108 形态判据 → 违规清单（空 = 合规）。注入式自证见 `test_shape_guards_are_load_bearing`。"""
    code = _strip_comments(body)
    updates = re.findall(r"UPDATE\s+production_route_rules[\s\S]*?;", code, re.I)
    if len(updates) != 1:
        return [f"`UPDATE production_route_rules` 条数 = {len(updates)}（应恰好 1 条写语句）"]
    stmt = updates[0]
    out = []
    columns = _set_columns(stmt)
    if columns != ["position", "updated_at"]:
        out.append(f"SET 列 = {columns}（应**恰好** ['position', 'updated_at']）")
    if "r.position IS NULL" not in stmt:
        out.append("写语句缺幂等谓词 `r.position IS NULL`（第二遍会重复改同一批行）")
    if "customer_unit_price" in stmt:
        out.append("写语句碰了 `customer_unit_price` —— 那是对客那本账（元/套），与「部位」无关")
    if "drop column" in code.lower():
        out.append("出现 `DROP COLUMN` —— 列是历史载体，且是部分唯一索引的成员")
    if RESTORED_VALUE not in stmt:
        out.append(f"写语句没有逐字写入 `{RESTORED_VALUE}`")
    return out


def _v109_violations(body: str) -> list:
    """V109 形态判据 → 违规清单（空 = 合规）。红线 = **只改约束、绝不动数据**。"""
    code = _strip_comments(body)
    out = []
    for kw in ("BEGIN;", "COMMIT;"):
        if not re.search(r"^" + re.escape(kw), body, re.M):
            out.append(f"缺显式 `{kw}`（`psql -f` 默认逐条 autocommit ⇒ 会留半完成态）")
    for dml in ("INSERT", "UPDATE", "DELETE"):
        if re.search(r"\b" + dml + r"\b", code, re.I):
            out.append(f"可执行语句里出现 `{dml}` —— V109 只改约束（`pg_constraint`），**不动数据**")
    for kw in ("DROP CONSTRAINT", "ADD CONSTRAINT", "trigger_kind", "position"):
        if kw not in code:
            out.append(f"可执行语句里缺 `{kw}`")
    if "'" + "position" + "'" not in code:
        out.append("闭词表里没有逐字 `'position'`（第 4 档落不了库）")
    return out


# ══════════════════════════ ① 存在性 / 版本号 / 账本 ══════════════════════════

def test_both_migrations_exist_with_unique_versions():
    for path, version in ((V108, 108), (V109, 109)):
        assert path.exists(), f"缺少迁移文件：{path.name}"
    versions = [int(re.match(r"^V(\d+)__", p.name).group(1))
                for p in MIGRATION_DIR.glob("V*.sql") if re.match(r"^V(\d+)__", p.name)]
    for want in (108, 109):
        assert versions.count(want) == 1, f"V{want} 版本号重复"
    assert max(versions) >= 109, f"V109 不是最高版本号（当前最大 V{max(versions)}）"


def test_both_migrations_are_registered_in_the_fingerprint_ledger():
    """迁移不可变护栏（issue #4235）：新增迁移必须在内容指纹账本里，否则它以后能被静默改。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    missing = [p.name for p in (V108, V109) if p.name not in ledger]
    assert missing == [], (
        f"这些迁移未登记进 `tests/unit_ci_workflows/migration_fingerprints.json`：{missing}\n"
        f"  跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")


# ══════════════ ② V108 静态判据（写语句形态 / 跨源逐字 / 文档义务） ══════════════

def test_v108_is_explicitly_transactional_and_reconciles():
    body = _read(V108)
    assert re.search(r"^BEGIN;", body, re.M), "V108 缺显式 `BEGIN;`"
    assert re.search(r"^COMMIT;", body, re.M), "V108 缺显式 `COMMIT;`"
    assert "RAISE EXCEPTION" in body, "V108 缺终态对账（`RAISE EXCEPTION`）"


def test_v108_shape_is_clean():
    """写语句形态：恰好一条 `UPDATE`、`SET` 只两列、含 NULL 闸、不碰对客价 / 不 DROP 列。"""
    assert _v108_violations(_read(V108)) == []


def test_v108_loops_over_tenants_and_never_writes_a_literal_tenant():
    """**按租户循环**：只改 1 号租户会让非 1 号租户的部位限定永远拿不回来（#4676 ⑥ 同款教训）。"""
    code = _strip_comments(_read(V108))
    assert re.search(r"FROM tenants t\b", code), "V108 没有按租户循环（找不到 `FROM tenants t`）"
    assert "tenant_id = 1" not in code, "V108 被写死成 1 号租户"
    assert code.count("t.deleted = 0") >= 1, "V108 没有排除已软删租户"


def test_v108_write_predicate_matches_the_frozen_v71_seed_row():
    """跨源**逐字**：V108 写回的那条规则 = V71 冻结种子里**唯一**带 `position` 的那一行。

    这条防的是「两处字面量各自漂移」——改 V108 的谓词而不改种子（或反之）会让
    「回归的部位限定」落到**另一条规则**上，而任何单侧判据都不会红。
    """
    frozen = _rule_rows(_read(V71))
    assert len(frozen) == 26, f"V71 的 `rr-v70-*` 种子解析出 {len(frozen)} 行，期望 26"
    carrying = [r for r in frozen if r["position"] != "NULL"]
    assert len(carrying) == 1, (
        f"V71 冻结种子里带 `position` 的行 = {[(r['id'], r['position']) for r in carrying]}，"
        f"期望恰好 1 行（V103 前的存量为 1 条部位限定）")
    only = carrying[0]
    assert only["id"] == "rr-v70-02", f"V71 里带 position 的是 `{only['id']}`，期望 `rr-v70-02`"
    assert _as_literal(RESTORED_VALUE) == only["position"], (
        f"V108 写回值 `{RESTORED_VALUE}` ≠ V71 种子那一行的字面量 `{only['position']}`")

    code = _strip_comments(_read(V108))
    stmt = re.findall(r"UPDATE\s+production_route_rules[\s\S]*?;", code, re.I)[0]
    for column, raw in (("trigger_kind", only["kind"]), ("trigger_value", only["value"]),
                        ("action", only["action"]), ("operation", only["operation"]),
                        ("after_operation", only["after"])):
        literal = f"{column} = {_as_literal(raw)}"
        assert literal in stmt, (
            f"V108 的写语句里缺 `{literal}`（= V71 冻结种子 `{only['id']}` 的 `{column}`）"
            f"—— 谓词与种子漂移，会写到**另一条**规则上：{stmt}")


def test_v108_documents_rollback_limits_and_stop_conditions():
    """迁移文件的硬要求：回滚 SQL + **不可复原项** + 为什么是新迁移 + 停止条件 S1~S4。"""
    body = _read(V108)
    for needle, label in (("回滚 SQL", "回滚 SQL 段"),
                          ("不可复原", "不可复原项（回滚有损，必须照实登记）"),
                          ("MigrationRunner", "为什么必须是新迁移（按文件名记账 ⇒ 改已发布迁移 = 静默缺失）"),
                          ("S1", "停止条件 S1"), ("S2", "停止条件 S2"),
                          ("S3", "停止条件 S3"), ("S4", "停止条件 S4"),
                          ("按租户循环", "按租户循环的显式说明")):
        assert needle in body, f"V108 缺{label}（`{needle}`）"


def test_v108_does_not_confuse_the_seed_parsers():
    """V108 **不得**含种子解析关键字（本仓按内容发现种子源的守卫会被它骗到）。

    `tests/unit_ci_workflows/test_production_catalog_seed.py` 的 `values_sources_for()` 用
    「`INSERT INTO production_route_rules` … 行值关键字」的**原始文本**正则发现字面量种子源
    ⇒ 一旦命中，V108 会被当种子源去解析行（解析不出 ⇒ 该守卫报红，而红的原因与被测行为无关）。
    """
    body = _strip_comments(_read(V108))
    assert "INSERT INTO production_route_rules" not in body, (
        "V108 的可执行语句里有 `INSERT INTO production_route_rules` ⇒ 会被种子发现正则当种子源")
    assert not re.search(r"\bVALUES\b", body, re.I), "V108 的可执行语句里出现了行值构造关键字"
    assert not re.search(r"\bWITH\s+\w+\s+AS\s*\(", body, re.I), "V108 用了 CTE（本仓迁移不使用）"


# ══════════════════════════ ③ V109 静态判据 ══════════════════════════

def test_v109_shape_is_clean():
    """V109 = **只改约束、绝不动数据**（它的红线）；闭词表里必须逐字有 `'position'`。"""
    assert _v109_violations(_read(V109)) == []


def test_v109_leaves_data_untouched_is_not_vacuous():
    """V109 的**红线判据自身**承重：可执行语句里连 `production_route_rules` 的行数据都没碰。

    （`_v109_violations` 的 DML 分支若因为「剥注释把整份文件剥空了」而恒真，这条会红：
    `_strip_comments` 必须留下 `DROP CONSTRAINT` / `ADD CONSTRAINT` 这些真语句。）
    """
    code = _strip_comments(_read(V109))
    assert "DROP CONSTRAINT" in code and "ADD CONSTRAINT" in code, (
        "剥注释后看不到真语句 ⇒ 上一条的「无 DML」是空断言")
    for dml in ("INSERT", "UPDATE", "DELETE"):
        assert len(re.findall(r"\b" + dml + r"\b", code, re.I)) == 0, (
            f"V109 的可执行语句里出现 `{dml}` ⇒ 它不只改约束")


# ══════════════════ ④ 注入式红证：静态判据**会**红（不是空断言） ══════════════════

def _inject(body: str, old: str, new: str) -> str:
    """注入式变异（锚点必须**唯一**，否则本红证自己就是空断言）。"""
    assert body.count(old) == 1, f"注入锚点出现 {body.count(old)} 次（应恰好 1 次）：{old!r}"
    mutated = body.replace(old, new, 1)
    assert mutated != body, "注入没生效 ⇒ 本红证是空断言"
    return mutated


def test_v108_shape_guard_is_load_bearing():
    body = _read(V108)
    assert _v108_violations(body) == [], "改前就不合规 ⇒ 本红证的前提不成立"

    price = _inject(body,
                    "           updated_at = NOW()\n      FROM tenants t",
                    "           updated_at = NOW(),\n           customer_unit_price = 0\n"
                    "      FROM tenants t")
    price_hits = _v108_violations(price)
    assert any("customer_unit_price" in h for h in price_hits), (
        f"把 `customer_unit_price` 加进 SET 后判据没红 ⇒ 「只写两列」是空断言：{price_hits}")
    assert any("SET 列" in h for h in price_hits), f"SET 列判据没红：{price_hits}"

    gate = _inject(body, "       AND r.deleted = 0\n       AND r.position IS NULL\n",
                   "       AND r.deleted = 0\n")
    gate_hits = _v108_violations(gate)
    assert any("幂等谓词" in h for h in gate_hits), (
        f"删掉 `AND r.position IS NULL` 后判据没红 ⇒ 幂等闸判据是空断言：{gate_hits}")

    dropped = _inject(body, "\nCOMMIT;\n",
                      "\nALTER TABLE production_route_rules DROP COLUMN position;\n\nCOMMIT;\n")
    drop_hits = _v108_violations(dropped)
    assert any("DROP COLUMN" in h for h in drop_hits), (
        f"注入 `DROP COLUMN` 后判据没红 ⇒ 列保留的判据是空断言：{drop_hits}")


def test_v109_shape_guard_is_load_bearing():
    body = _read(V109)
    assert _v109_violations(body) == [], "改前就不合规 ⇒ 本红证的前提不成立"

    no_position = _inject(body, "'processing_item', 'position'));", "'processing_item'));")
    hits = _v109_violations(no_position)
    assert any("'position'" in h for h in hits), (
        f"从闭词表里删掉 `'position'` 后判据没红 ⇒ 第 4 档的判据是空断言：{hits}")

    with_dml = _inject(body, "\nCOMMIT;\n",
                       "\nUPDATE production_route_rules SET position = NULL;\n\nCOMMIT;\n")
    dml_hits = _v109_violations(with_dml)
    assert any("`UPDATE`" in h for h in dml_hits), (
        f"给 V109 注入 `UPDATE` 后判据没红 ⇒ 「只改约束不动数据」是空断言：{dml_hits}")


# ══════════════════════════ ⑤ 真库判据（临时 PG 集群） ══════════════════════════

_PG_BINARIES = ("initdb", "pg_ctl", "psql")

#: 与 V71 / `docs/sql/schema.sql` 同形的**最小** DDL（本单触碰的表 + 部分唯一索引）。
#: ⚠️ `trigger_kind` 的 CHECK **逐字照抄 V71 的内联 CHECK**（= V109 之前的口径）
#: —— 夹具必须能复现「`trigger_kind='position'` 落不了库」这个改前形态，否则 V109 的红证是空跑。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_route_rules (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(24) NOT NULL
        CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item')),
    trigger_value VARCHAR(64) NOT NULL,
    position VARCHAR(16), action VARCHAR(16) NOT NULL, operation VARCHAR(64),
    after_operation VARCHAR(64), priority INTEGER NOT NULL DEFAULT 100,
    customer_unit_price NUMERIC(12,2),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_route_rules_tenant_trigger_operation
    ON production_route_rules (tenant_id, trigger_kind, trigger_value,
                              COALESCE(position, ''), action, COALESCE(operation, ''))
    WHERE deleted = 0;
"""

#: 真库形态的种子 = **V103 之后**的终态：
#:   · **1 号租户**：`rr-v70-02` 形态的一条（`position = NULL`，待写回）+ 两条「不限部位」邻居；
#:   · 一条**同形态但商家自己写过值**（`纱帘`）的行 —— V108 的 NULL 闸**必须放过它**；
#:   · 一条**已软删**行（历史留痕，值非 NULL）—— V108 一行都不许动；
#:   · **2 号租户**：同形态的一条（`rr-v93-<tenant>-02` 形态）—— 证明「按租户循环」。
#: 行数 = 6（V108 只许改值，不许增删行）。
_SEED = """
INSERT INTO tenants (id) VALUES (1), (2);
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation,
     after_operation, priority, customer_unit_price, deleted) VALUES
    ('rr-v70-02',   1, 'craft',  '韩褶',   NULL,   'insert', '上车布',  '韩褶',  20,  NULL,  0),
    ('rr-v70-01',   1, 'craft',  '韩褶',   NULL,   'insert', '韩褶',    '三边',  10,  NULL,  0),
    ('rr-v70-11',   1, 'option', '拼1次',  NULL,   'insert', '拼1次',   '三边',  110, 12.50, 0),
    ('rr-v70-02b',  1, 'craft',  '韩褶',   '纱帘', 'insert', '上车布',  '韩褶',  21,  99.00, 0),
    ('rr-v70-09x',  1, 'craft',  '平幔',   '布帘', 'insert', '帘头制作','三边',  90,  NULL,  1),
    ('rr-v93-2-02', 2, 'craft',  '韩褶',   NULL,   'insert', '上车布',  '韩褶',  20,  30.00, 0);
"""

_TOTAL_ROWS = 6


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
    sockdir = Path(tempfile.mkdtemp(prefix="pg4962-"))
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

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            ["psql", "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
             "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    run.raw = psql_raw
    try:
        yield run
    finally:
        subprocess.run(["pg_ctl", "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


def _as_runner_would(sql: str) -> str:
    """把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。

    ⚠️ 文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
    「已经有一个事物在运行中」**警告**（不是错误，无害）。
    """
    return "BEGIN;\n" + sql + "\nCOMMIT;\n"


def _seed(run) -> None:
    run(_DDL + _SEED)


def _live(run, tenant: int) -> list:
    out = run(f"SELECT id || '=' || COALESCE(position, '<null>') FROM {TABLE} "
              f"WHERE tenant_id = {tenant} AND deleted = 0 ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def _predicate_count(run, tenant: int = 0) -> str:
    """「应写回而还没写回」的行数（= V108 写语句谓词的业务部分；**每租户 1 行**）。"""
    scope = f" AND r.tenant_id = {tenant}" if tenant else ""
    return run("SELECT count(*) FROM production_route_rules r "
               "JOIN tenants t ON t.id = r.tenant_id AND t.deleted = 0 "
               "WHERE r.deleted = 0 AND r.position IS NULL "
               "AND r.trigger_kind = 'craft' AND r.trigger_value = '韩褶' "
               "AND r.action = 'insert' AND r.operation = '上车布' "
               f"AND r.after_operation = '韩褶'{scope};").strip()


def _restored_count(run) -> str:
    """已写回 `'布帘'` 的存活行数（终态对账 / 回滚往返的读数）。"""
    return run("SELECT count(*) FROM production_route_rules r "
               "JOIN tenants t ON t.id = r.tenant_id AND t.deleted = 0 "
               "WHERE r.deleted = 0 AND r.position = '布帘' "
               "AND r.trigger_kind = 'craft' AND r.trigger_value = '韩褶' "
               "AND r.action = 'insert' AND r.operation = '上车布' "
               "AND r.after_operation = '韩褶';").strip()


def _fingerprint(run, table: str, columns: str) -> str:
    return run(f"SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM "
               f"(SELECT {columns} FROM {table}) t;").strip()


def _rows_total(run) -> str:
    return run(f"SELECT count(*) FROM {TABLE};").strip()


def _apply(run, path: Path):
    """跑一份迁移（`_as_runner_would`）并返回 CompletedProcess（红证要读 stderr 里的 NOTICE）。"""
    proc = run.raw(_as_runner_would(_read(path)))
    assert proc.returncode == 0, f"{path.name} 失败：\n{proc.stdout}\n{proc.stderr}"
    return proc


def _claimed(stderr: str) -> str:
    """从 V108 的 `RAISE NOTICE … claimed_rows=N` 里读出本轮 `UPDATE` 命中行数。

    ⚠️ `psql -q` **不**抑制服务端 NOTICE（实测）⇒ 这个自证是**可读的**。
    用 `findall` + 精确条数断言，而不是 `is not None`（弱断言会被 QA Gate 拦）。
    """
    found = re.findall(r"claimed_rows=(\d+)", stderr)
    assert len(found) == 1, (
        f"V108 的 `GET DIAGNOSTICS` 自证丢了（期望恰好 1 条 `claimed_rows=`）：{stderr[-500:]}")
    return found[0]


def _constraint_defs(run) -> list:
    out = run("SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
              "JOIN pg_class t ON t.oid = c.conrelid "
              f"WHERE t.relname = '{TABLE}' AND c.contype = 'c' "
              "AND pg_get_constraintdef(c.oid) LIKE '%trigger_kind%' ORDER BY 1;")
    return [line for line in out.splitlines() if line.strip()]


# ══════════════════ V108 真库：写回 / 幂等 / 终态对账 / 多租户 / 红线 ══════════════════

def test_v108_restores_the_position_for_every_tenant_and_touches_nothing_else(psql):
    """核心：**每个活跃租户**拿回那条部位限定；邻居 / 商家已写值 / 软删行 / 对客价 / 行数全不动。"""
    _seed(psql)
    before = {t: _live(psql, t) for t in (1, 2)}
    before_deleted = _live_deleted(psql)
    price_fp = _fingerprint(psql, TABLE, "id, customer_unit_price")
    total = _rows_total(psql)
    pending = _predicate_count(psql)
    assert before[1] == ["rr-v70-01=<null>", "rr-v70-02=<null>", "rr-v70-02b=纱帘",
                         "rr-v70-11=<null>"], f"夹具不是「V103 之后」的终态：{before[1]}"
    assert before[2] == ["rr-v93-2-02=<null>"], f"夹具不是「V103 之后」的终态：{before[2]}"
    assert pending == "2", f"改前「待写回」的行数 = {pending}，期望 2（两个租户各 1 行）"

    proc = _apply(psql, V108)

    after = {t: _live(psql, t) for t in (1, 2)}
    claimed = _claimed(proc.stderr)
    pending_after = _predicate_count(psql)
    restored = _restored_count(psql)
    print(f"[#4962 真库 · V108 第一遍] UPDATE 命中行数 claimed_rows = {claimed}")
    print(f"[#4962 真库] 1 号租户存活行 = {after[1]}")
    print(f"[#4962 真库] 2 号租户存活行 = {after[2]}（非 1 号租户必须一并拿回）")
    print(f"[#4962 真库] 软删行（必须逐字不变）= {_live_deleted(psql)}")
    print(f"[#4962 真库] 写回 `布帘` 的存活行数 = {restored}；"
          f"「待写回」剩余 = {pending_after}")

    assert claimed == "2", f"第一遍命中 {claimed} 行，期望 2（每租户 1 行）"
    assert _predicate_count(psql, 1) == "0" and pending_after == "0", (
        f"写回后仍有「待写回」的行（1 号租户 = {_predicate_count(psql, 1)}，合计 = {pending_after}）")
    assert after[1] == ["rr-v70-01=<null>", "rr-v70-02=布帘", "rr-v70-02b=纱帘",
                        "rr-v70-11=<null>"], (
        f"1 号租户终态不对：{after[1]}\n"
        f"（`rr-v70-02` 应为 `布帘`；`rr-v70-01`/`rr-v70-11` 仍 `NULL`；"
        f"`rr-v70-02b` 是**商家自己写过**的值，必须原样保留）")
    assert after[2] == ["rr-v93-2-02=布帘"], (
        f"**非 1 号租户**没拿回部位限定（{after[2]}）—— 写死 `tenant_id = 1` 的写法会漏掉它")
    assert restored == "2", (
        f"**写回 `布帘`** 的存活行数 = {restored}，期望 2（两个租户各 1 条；"
        f"商家的那条是 `纱帘`，不属于写回值）")
    assert _live_deleted(psql) == before_deleted, (
        f"V108 动了已软删行：{before_deleted} → {_live_deleted(psql)}")
    assert _fingerprint(psql, TABLE, "id, customer_unit_price") == price_fp, (
        "🔴 V108 改了 `customer_unit_price` —— 那是对客那本账（元/套），与「部位」无关")
    assert _rows_total(psql) == total == str(_TOTAL_ROWS), (
        f"V108 增删了规则行（{total} → {_rows_total(psql)}）—— 它只许改一列的值")


def _live_deleted(run) -> list:
    out = run(f"SELECT id || '=' || COALESCE(position, '<null>') FROM {TABLE} "
              f"WHERE deleted = 1 ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def test_v108_is_idempotent_two_runs_and_second_claims_zero_rows(psql):
    """`MigrationRunner` 硬要求：第二遍**空操作**（命中 0 行）+ 净效果逐字相同、不抛异常。"""
    _seed(psql)
    first = _apply(psql, V108)
    after_first = {t: _live(psql, t) for t in (1, 2)}
    pending_first = _predicate_count(psql)
    second = _apply(psql, V108)
    after_second = {t: _live(psql, t) for t in (1, 2)}

    claimed_first, claimed_second = _claimed(first.stderr), _claimed(second.stderr)
    print(f"[#4962 真库 · 两遍幂等] 第 1 遍 claimed_rows = {claimed_first}；"
          f"第 2 遍 claimed_rows = {claimed_second}（= 0 ⇒ 幂等闸生效）")
    print(f"[#4962 真库] 1 号租户：第一遍后 = {after_first[1]}；第二遍后 = {after_second[1]}")
    print(f"[#4962 真库] 2 号租户：第一遍后 = {after_first[2]}；第二遍后 = {after_second[2]}")
    print(f"[#4962 真库] 第 1 遍后「待写回」= {pending_first}；"
          f"第 2 遍后「待写回」= {_predicate_count(psql)}")

    assert claimed_first == "2", f"第 1 遍命中 {claimed_first} 行，期望 2（每租户 1 行）"
    assert claimed_second == "0", (
        f"第 2 遍命中 {claimed_second} 行 ⇒ **不幂等**（谓词丢了 `r.position IS NULL`？）")
    assert after_first == after_second, (
        f"V108 不幂等：第二遍改了净效果\n  第一遍：{after_first}\n  第二遍：{after_second}")
    assert pending_first == "0", f"第一遍后仍有 {pending_first} 行待写回"


def test_v108_reconciliation_blocks_a_partial_write(psql):
    """红证（真库）：写语句**漏改一个租户** ⇒ 终态对账 `RAISE EXCEPTION` ⇒ 整份回滚。

    注入 = 给写语句的 `WHERE` 尾部加 `AND r.id <> 'rr-v93-2-02'`（模拟「判据与写语句漂移」）。
    """
    _seed(psql)
    before = {t: _live(psql, t) for t in (1, 2)}
    sql = _read(V108)
    old = ("       AND r.after_operation = '韩褶';\n    GET DIAGNOSTICS")
    injected = _inject(sql, old, "       AND r.after_operation = '韩褶'\n"
                                 "       AND r.id <> 'rr-v93-2-02';\n    GET DIAGNOSTICS")
    proc = psql.raw(_as_runner_would(injected))
    after = {t: _live(psql, t) for t in (1, 2)}
    print(f"[#4962 真库 · 红证] 漏改一个租户 ⇒ 回滚 = {proc.returncode != 0}；"
          f"stderr 含「终态对账失败」= {'终态对账失败' in proc.stderr}")
    assert proc.returncode != 0, (
        f"漏改一个租户时终态对账竟通过了 ⇒ 停止条件 S1 是空断言\nstderr={proc.stderr[:400]}")
    assert "终态对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
    assert after == before, (
        f"对账抛异常后数据却变了 ⇒ 没有回滚（半完成态）：\n  改前 {before}\n  改后 {after}")


def test_v108_null_gate_is_load_bearing_for_idempotency(psql):
    """红证（真库）：删掉写语句的 `AND r.position IS NULL` ⇒ **第二遍不再匹配 0 行**。

    夹具**特意不含**「同形态、`position` 非 NULL」的行（那种行会让去掉闸的写语句撞上部分唯一
    索引，见下一条）—— 本红证只想**单独**证明「第二遍 0 行」这条判据有判别力，不掺别的机制。
    """
    psql(_DDL)
    psql("INSERT INTO tenants (id) VALUES (1), (2);")
    psql("INSERT INTO production_route_rules (id, tenant_id, trigger_kind, trigger_value, position, "
         "action, operation, after_operation, priority) VALUES "
         "('rr-v70-02', 1, 'craft', '韩褶', NULL, 'insert', '上车布', '韩褶', 20), "
         "('rr-v93-2-02', 2, 'craft', '韩褶', NULL, 'insert', '上车布', '韩褶', 20);")
    assert _predicate_count(psql) == "2", "红证前提不成立：改前应有 2 行待写回"

    injected = _inject(_read(V108), "       AND r.deleted = 0\n       AND r.position IS NULL\n",
                       "       AND r.deleted = 0\n")
    first = _apply_sql(psql, injected)
    second = _apply_sql(psql, injected)
    print(f"[#4962 真库 · 红证] 去掉 NULL 闸后：第 1 遍 claimed_rows = {_claimed(first.stderr)}；"
          f"第 2 遍 claimed_rows = {_claimed(second.stderr)}（正常口径必须是 0）")
    assert _claimed(first.stderr) == "2", "去掉闸后第一遍的命中数就不对（红证前提不成立）"
    assert _claimed(second.stderr) != "0", (
        "去掉 NULL 闸后第二遍仍命中 0 行 ⇒ 「第二遍 0 行」那条断言没有判别力（是空断言）")


def test_v108_null_gate_keeps_a_merchant_configured_row_out_of_the_write(psql):
    """红证（真库）：去掉 NULL 闸后，**商家配置的同形态行进入了写语句射程**。

    夹具里的 `rr-v70-02b` 是「同形态、`position = '纱帘'`」（= 商家自己配的部位限定）。
    正常口径下 NULL 闸把它挡在写语句之外（它保持 `纱帘`，见 `test_v108_restores_…`）；
    去掉闸后写语句会去改它 ⇒ 撞部分唯一索引 `uk_production_route_rules_tenant_trigger_operation`
    ⇒ 整份迁移**失败并回滚**（fail-closed，不是静默覆写）。

    ⇒ 这条证明「商家已写的值保持 `纱帘`」那句断言**不是恒真**：它成立**依赖**那个 NULL 闸。
    """
    _seed(psql)
    before = {t: _live(psql, t) for t in (1, 2)}
    injected = _inject(_read(V108), "       AND r.deleted = 0\n       AND r.position IS NULL\n",
                       "       AND r.deleted = 0\n")
    proc = psql.raw(_as_runner_would(injected))
    after = {t: _live(psql, t) for t in (1, 2)}
    print(f"[#4962 真库 · 红证] 去掉 NULL 闸后：回滚 = {proc.returncode != 0}；"
          f"撞上的部分唯一索引 = "
          f"{'uk_production_route_rules_tenant_trigger_operation' in proc.stderr}")
    assert proc.returncode != 0, (
        "去掉 NULL 闸后写语句竟没去碰商家的同形态行 ⇒ 「商家值不动」那条断言没有判别力")
    assert "uk_production_route_rules_tenant_trigger_operation" in proc.stderr, (
        f"失败的不是部分唯一索引 ⇒ 说明那条商家行**没进**写语句射程：{proc.stderr[:400]}")
    assert after == before, f"失败后数据却变了（没回滚）：\n  改前 {before}\n  改后 {after}"


def _apply_sql(run, sql: str):
    proc = run.raw(_as_runner_would(sql))
    assert proc.returncode == 0, f"注入后的迁移失败了（本红证只想看数据形态）：\n{proc.stderr[:600]}"
    return proc


def _rollback_sql() -> str:
    """从 V108 的注释里抽出**回滚 SQL**（`-- ```sql … -- ``` ` 围栏内、逐行 `-- ` 前缀）。"""
    body = _read(V108)
    opened = body.index("-- ```sql", body.index("-- ## 回滚 SQL"))
    closed = body.index("-- ```", opened + len("-- ```sql"))
    lines = []
    for raw in body[opened + len("-- ```sql"):closed].splitlines():
        if not raw.strip():
            continue
        assert raw.startswith("-- "), f"回滚段里的行不是注释形态：{raw!r}"
        lines.append(raw[3:])
    sql = "\n".join(lines)
    code = _strip_comments(sql)
    assert code.count(";") == 1, f"回滚段应是**一条**可执行语句：{sql}"
    assert "SET position = NULL" in code, f"回滚段没有把 position 清回 NULL：{sql}"
    return code


def test_v108_rollback_sql_round_trips(psql):
    """回滚 SQL **真跑**：清回 `NULL`（只清 V108 写回的那个值，商家值仍在）⇒ V108 再跑又能拿回。"""
    _seed(psql)
    _apply(psql, V108)
    rollback = _rollback_sql()

    psql(_as_runner_would(rollback))
    after_rollback = {t: _live(psql, t) for t in (1, 2)}
    print(f"[#4962 真库 · 回滚] 回滚后 1 号租户 = {after_rollback[1]}；2 号租户 = {after_rollback[2]}")
    assert after_rollback[1] == ["rr-v70-01=<null>", "rr-v70-02=<null>", "rr-v70-02b=纱帘",
                                 "rr-v70-11=<null>"], (
        f"回滚没有把 `rr-v70-02` 清回 NULL，或误清了商家的 `纱帘`：{after_rollback[1]}")
    assert after_rollback[2] == ["rr-v93-2-02=<null>"], f"回滚没覆盖非 1 号租户：{after_rollback[2]}"
    assert _restored_count(psql) == "0", "回滚后仍有写回值 ⇒ 回滚谓词与写语句不同源"

    # 回滚自己也幂等（第二遍空操作）
    psql(_as_runner_would(rollback))
    assert _restored_count(psql) == "0", "回滚第二遍改了东西 ⇒ 回滚不幂等"

    # 互相幂等：回滚后 V108 再跑一次，又能拿回（且命中数仍 = 每租户 1 行）
    again = _apply(psql, V108)
    print(f"[#4962 真库 · 回滚往返] 回滚后再跑 V108 claimed_rows = {_claimed(again.stderr)}；"
          f"1 号租户 = {_live(psql, 1)}")
    assert _claimed(again.stderr) == "2", "回滚后 V108 没把两条都拿回来"
    assert _live(psql, 1) == ["rr-v70-01=<null>", "rr-v70-02=布帘", "rr-v70-02b=纱帘",
                              "rr-v70-11=<null>"], (
        f"回滚往返后 1 号租户不是写回后的终态：{_live(psql, 1)}")
    assert _restored_count(psql) == "2", "回滚往返后的终态条数不对（期望 2 = 每租户 1 条）"


# ══════════════════ V109 真库：闭词表放开 / 不动数据 / 幂等 ══════════════════

_V109_INSERT = ("INSERT INTO production_route_rules "
                "(id, tenant_id, trigger_kind, trigger_value, position, action, operation, "
                "after_operation) VALUES "
                "('rr-position-1', 1, 'position', '布帘', '布帘', 'insert', '上车布', '韩褶');")


def test_v109_lets_position_trigger_kind_rows_land_and_leaves_data_untouched(psql):
    """核心：改前插 `trigger_kind='position'` **必被拒**（这就是承重性，不是「顺手加个枚举」）；
    改后插入成功，且 V109 **只改约束**（行数不变）、**两遍幂等**（约束恰好一条）、闭词表**仍是闭的**。"""
    _seed(psql)
    total_before = _rows_total(psql)
    rejected = psql.raw(_V109_INSERT)
    print(f"[#4962 真库 · V109 改前] 插 `trigger_kind='position'` 被拒 = "
          f"{rejected.returncode != 0}；点名约束 = "
          f"{'production_route_rules_trigger_kind_check' in rejected.stderr}")
    assert total_before == str(_TOTAL_ROWS), f"夹具行数 = {total_before}，期望 {_TOTAL_ROWS}"
    assert rejected.returncode != 0, (
        "改前 `trigger_kind='position'` 竟然插得进去 ⇒ 本红证的前提不成立（夹具没照 V71 的 CHECK 建表）")
    assert "production_route_rules_trigger_kind_check" in rejected.stderr, (
        f"被拒的不是那条 CHECK 约束（23514）：{rejected.stderr[:400]}")
    assert _rows_total(psql) == total_before, "被拒的那条 INSERT 竟留下了行"

    _apply(psql, V109)
    defs = _constraint_defs(psql)
    total_after_v109 = _rows_total(psql)
    print(f"[#4962 真库 · V109 改后] 约束定义 = {defs}")
    print(f"[#4962 真库 · V109 改后] 规则行数 = {total_after_v109}（V109 前后必须相等，它不动数据）")
    assert len(defs) == 1, f"`trigger_kind` 的 CHECK 约束条数 = {len(defs)}，期望恰好 1：{defs}"
    assert defs[0].count("position") == 1, (
        f"闭词表里的 `position` 出现 {defs[0].count('position')} 次，期望 1：{defs[0]}")
    assert TRIGGER_KIND_VOCAB in _read(V109), (
        f"V109 的闭词表不是逐字 `{TRIGGER_KIND_VOCAB}`（与 bootstrap 的 CHECK 不同源）")
    assert total_after_v109 == total_before, (
        f"🔴 V109 动了行数据（{total_before} → {total_after_v109}）—— 它只许改约束")

    psql(_V109_INSERT)
    assert _rows_total(psql) == str(_TOTAL_ROWS + 1), (
        "V109 之后 `trigger_kind='position'` 的行没插进去 ⇒ 第 4 档落不了库（前端提交必 500）")

    bogus = psql.raw("INSERT INTO production_route_rules "
                     "(id, tenant_id, trigger_kind, trigger_value, action, operation) VALUES "
                     "('rr-bogus-1', 1, 'bogus', 'x', 'insert', '上车布');")
    print(f"[#4962 真库 · V109] 闭词表仍是**闭**的（`bogus` 被拒）= {bogus.returncode != 0}")
    assert bogus.returncode != 0, (
        "V109 之后 `bogus` 也能插 ⇒ 闭词表被整体放开（判据只查了有没有 `position`，"
        "没查它**仍是闭词表**）")
    assert _rows_total(psql) == str(_TOTAL_ROWS + 1), "被拒的 `bogus` 行留下了"

    second = _apply(psql, V109)
    print(f"[#4962 真库 · V109 第二遍] 走了幂等分支 = {'跳过' in second.stderr}；"
          f"约束条数 = {len(_constraint_defs(psql))}")
    assert "跳过" in second.stderr, (
        f"第二遍没走幂等分支（`RAISE NOTICE … 跳过`）⇒ 它可能重复 `ADD CONSTRAINT`："
        f"{second.stderr[:400]}")
    assert len(_constraint_defs(psql)) == 1, "V109 第二遍重复加了约束"
    assert _rows_total(psql) == str(_TOTAL_ROWS + 1), "V109 第二遍动了行数据"


# ══════════════════ ⑥ bootstrap 镜像（两条路径终态一致） ══════════════════

def test_bootstrap_schema_sql_is_the_terminal_state_of_the_migration_chain(psql):
    """`docs/sql/schema.sql`（bootstrap，**不跑迁移链**）的 V70 规则终态 == 迁移链（V71 种子 + V103 + V108）终态。

    核对方式（**机械**，不靠人读）：
      ① **bootstrap 侧**：解析 `docs/sql/schema.sql` 的 `rr-v70-*` 26 行字面量 ⇒
         **有且只有 1 行**非 `NULL`，且必是 `rr-v70-02` = `'布帘'`（其余 25 行 `NULL`）；
      ② **迁移链侧**：把 **V71 冻结种子**的 26 行喂进真库 ⇒ 跑 V103 ⇒（此时必须**全 NULL**，
         否则本判据在「两边恰好都是 NULL」时也会绿 = 空断言）⇒ 跑 V108 ⇒ 终态；
      ③ **逐值相等**：两边的 `{id: position 字面量}` 映射必须**完全相等**。
    """
    schema = _read(SCHEMA_SQL)
    boot_rows = _rule_rows(schema)
    assert len(boot_rows) == 26, (
        f"schema.sql 的 `rr-v70-*` 规则解析出 {len(boot_rows)} 行，期望 26 ⇒ 解析失效或种子被改")
    boot_positions = {r["id"]: _as_literal(r["position"]) for r in boot_rows}
    boot_non_null = sorted(k for k, v in boot_positions.items() if v != "NULL")
    print(f"[#4962 bootstrap] schema.sql 的 rr-v70-* 26 行里非 NULL 的 = {boot_non_null}；"
          f"取值 = {[boot_positions[k] for k in boot_non_null]}")
    assert boot_non_null == ["rr-v70-02"], (
        f"schema.sql 的 V70 规则段非 NULL 的行 = {boot_non_null}，期望恰好 `['rr-v70-02']`"
        f"（V108 只写回这一条；其余 25 行仍 NULL）")
    assert boot_positions["rr-v70-02"] == _as_literal(RESTORED_VALUE), (
        f"schema.sql 的 `rr-v70-02` = {boot_positions['rr-v70-02']}，"
        f"与 V108 写回值 `{_as_literal(RESTORED_VALUE)}` 不同 ⇒ 两条路径终态分裂")

    # ② 迁移链侧：V71 冻结种子 ⇒ V103 ⇒ V108
    psql(_DDL)
    psql("INSERT INTO tenants (id) VALUES (1);")
    frozen = _rule_rows(_read(V71))
    assert len(frozen) == 26, f"V71 的 `rr-v70-*` 种子解析出 {len(frozen)} 行，期望 26"
    for r in frozen:
        psql(f"INSERT INTO {TABLE} (id, tenant_id, trigger_kind, trigger_value, position, "
             f"action, operation, after_operation, priority, status) VALUES "
             f"('{r['id']}', {r['tenant']}, '{r['kind']}', '{r['value']}', {r['position']}, "
             f"'{r['action']}', {r['operation']}, {r['after']}, {r['priority']}, "
             f"'{r['status']}');")
    # 🔴 **V103 已不存在**（issue #4980 把 V102~V106 合并重写为单条 `V102`，且**有意撤销** V103 的意图
    # —— `V102__retire_applicability_flag.sql` 文件头逐字：「`V103` 的意图已作废 ⇒ **删除该文件就是撤销它**」）
    # ⇒ 链模拟里不能再跑它（按文件名读会 `FileNotFoundError`，issue #4990）。
    # ⚠️ **但判别力必须保住**：原设计的判别来自「V103 清空后必须全 NULL」那一步；该步不可达之后，
    # 「两条路径终态相等」会退化成「两边恰好都是 NULL」的**空断言** ⇒ 改为**注入式判别**：
    # 手工把 `rr-v70-02` 置 `NULL`（= 模拟「若 V103 真跑过」的形态）⇒ 跑 V108 ⇒ 必须被写回。
    # 若 V108 变成 no-op / 谓词写错 ⇒ 下面的 `injected` 判据先红（注入没生效），或终态比对红。
    psql(f"UPDATE {TABLE} SET position = NULL WHERE tenant_id = 1 AND id = 'rr-v70-02';")
    mid = _chain_positions(psql)
    assert mid["rr-v70-02"] == "NULL", (
        f"注入失败：`rr-v70-02` 的 position 仍 = {mid['rr-v70-02']} ⇒ 下面的 V108 写回判据会**空跑**")
    _apply(psql, V108)
    chain = _chain_positions(psql)
    chain_non_null = sorted(k for k, v in chain.items() if v != "NULL")
    print(f"[#4962 迁移链] V71 种子 ⇒ 注入 rr-v70-02=NULL ⇒ V108 后非 NULL 的 = {chain_non_null}；"
          f"取值 = {[chain[k] for k in chain_non_null]}")

    assert chain_non_null == boot_non_null, (
        f"两条路径的**非 NULL 行集合**分裂：bootstrap = {boot_non_null}，迁移链 = {chain_non_null}")
    assert chain == boot_positions, (
        "两条路径的 V70 规则终态分裂（前 = bootstrap，后 = 迁移链）："
        f"{ {k: (boot_positions[k], chain[k]) for k in boot_positions if boot_positions[k] != chain[k]} }")


def _chain_positions(run) -> dict:
    out = run(f"SELECT id || '|' || COALESCE(position, '<null>') FROM {TABLE} "
              f"WHERE tenant_id = 1 ORDER BY id;")
    return {line.split("|")[0]: _as_literal(line.split("|")[1])
            for line in out.splitlines() if line.strip()}


def test_bootstrap_trigger_kind_vocabulary_includes_position():
    """bootstrap 的 CHECK 闭词表必须含 `position`，且与 V109 的 `ADD CONSTRAINT` **逐字**同款。

    少同步任一侧 ⇒ 新开库（bootstrap-first 栈不跑迁移链）上「第 4 档」落不了库，
    而迁移链那侧是好的 —— 两条路径分叉。
    """
    schema = _read(SCHEMA_SQL)
    v109 = _read(V109)
    assert TRIGGER_KIND_VOCAB in schema, (
        f"docs/sql/schema.sql 的 `trigger_kind` CHECK 不是逐字 `{TRIGGER_KIND_VOCAB}`")
    assert TRIGGER_KIND_VOCAB in v109, (
        f"V109 的 `ADD CONSTRAINT` 不是逐字 `{TRIGGER_KIND_VOCAB}`")
    # 逐字同款的反面（自证判据非空跑）：把 `position` 从任一侧拿掉，本判据即红
    for label, text in (("bootstrap", schema), ("V109", v109)):
        doctored = text.replace(TRIGGER_KIND_VOCAB, TRIGGER_KIND_VOCAB.replace(", 'position'", ""))
        assert doctored != text, f"{label} 侧的锚点没匹配上 ⇒ 本判据是空断言"
        assert TRIGGER_KIND_VOCAB not in doctored, f"{label} 侧的闭词表判据可被绕过"


def test_v108_written_value_matches_the_bootstrap_literal_exactly():
    """V108 写回值 / V71 冻结种子 / bootstrap 字面量 **三处逐字一致**（防单侧漂移）。"""
    boot = {r["id"]: r for r in _rule_rows(_read(SCHEMA_SQL))}
    frozen = {r["id"]: r for r in _rule_rows(_read(V71))}
    assert sorted(boot) == sorted(frozen), (
        f"bootstrap 与冻结 V71 的规则 id 集合不同：仅 bootstrap = "
        f"{sorted(set(boot) - set(frozen))}，仅 V71 = {sorted(set(frozen) - set(boot))}")
    assert boot["rr-v70-02"]["position"] == frozen["rr-v70-02"]["position"], (
        f"`rr-v70-02` 的 position：bootstrap = {boot['rr-v70-02']['position']}，"
        f"V71 = {frozen['rr-v70-02']['position']}")
    assert boot["rr-v70-02"]["position"] == _as_literal(RESTORED_VALUE), (
        f"bootstrap 的 `rr-v70-02` 不是 `{_as_literal(RESTORED_VALUE)}`")
    for r in frozen.values():
        if r["id"] != "rr-v70-02":
            assert r["position"] == "NULL", (
                f"V71 冻结种子 `{r['id']}` 意外带了 position = {r['position']}"
                f"（V108 只写回那一条 ⇒ 这里必须仍是 NULL）")


def test_referenced_migrations_exist():
    """本模块引用的每个迁移文件都必须**存在** —— 缺失要给**可读判据**，而不是 `FileNotFoundError`。

    失败形态实测（issue #4990）：`#4980` 把 V102~V106 合并重写为单条 `V102` 并**删除** V103，
    而本模块当时按文件名硬编码读它 ⇒ 测试直接抛 `FileNotFoundError`（回溯指向 `pathlib.read_text`），
    读者要翻栈才知道「是迁移被删了」而不是「迁移写错了」。
    """
    refs = {"V71": V71, "V108": V108, "V109": V109}
    missing = sorted(name for name, path in refs.items() if not path.is_file())
    assert missing == [], (
        f"本模块引用的迁移文件不存在：{missing}（实际路径见模块顶部的常量）—— "
        "迁移被合并重写/删除时，**必须同 PR 更新本模块的引用**（判据形态：这里给可读清单，"
        "而不是让 `_read()` 抛 FileNotFoundError）；V103 的撤销先例见 issue #4980 / #4990")
