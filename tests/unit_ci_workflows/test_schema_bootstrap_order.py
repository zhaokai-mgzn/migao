# case_ids: PG-031, MC-012
"""`docs/sql/schema.sql` 建库顺序守卫（issue #4762）。

## 缺陷（#4741 的包实测发现，本单复现）

`production_route_signals` 的种子（V60 段）**排在租户种子（V40 段）之前** ⇒
`psql -v ON_ERROR_STOP=1 -f docs/sql/schema.sql` 在
`production_route_signals_tenant_id_fkey` 上**中止**。中止点 = V60 段
（段首 `-- 信号种子（tenant_id=1；`，本文件用 `_SIGNAL_BLOCK` 按**文本锚点**定位它）
里的 `INSERT INTO production_route_signals … ON CONFLICT DO NOTHING;`，报错原文：

    ERROR:  insert or update on table "production_route_signals"
            violates foreign key constraint "production_route_signals_tenant_id_fkey"
    描述:  Key (tenant_id)=(1) is not present in table "tenants".
    EXIT=3

而 `deploy/docker-compose.yml` 正把该文件挂成
`docker-entrypoint-initdb.d/001_schema.sql`（该文件 `volumes:` 段里的挂载项），postgres 官方 entrypoint 用
`psql -v ON_ERROR_STOP=1` 执行 initdb 脚本 ⇒ **本地/CI docker 栈建库中止**（新开发者走的那条路）。

⚠️ **隐蔽点**：判据若用 `ON_ERROR_STOP=0` 跑全文 ⇒ **错误被吞掉**、脚本「看起来成功」
（实测：全新库上全文恰好只有这 **1** 条 ERROR，而 psql **exit=0**）—— 正是本仓最忌的**静默失败**。
⇒ 本守卫的机械判据 = **`ON_ERROR_STOP=1` 跑全文 exit 0** + **零 ERROR** + **目标段落真跑到**。

## 本文件钉的四件事（各有红证）

1. **静态顺序判据**（不需要 PG ⇒ CI 可见）：全文**每一处**带字面量 FK 值的 `INSERT`，
   它引用的那一行必须在**更早**的 `INSERT` 里已经种下 ⇒ 越序即红。
   **不是只钉 `production_route_signals` 一处** —— 判据是**全表扫描**（换任何一张表越序同样红）；
2. **注入式红证**（`test_injected_wrong_order_is_detected`）：把本段移回租户种子**之前**
   ⇒ 判据 1 必红；移回**之后** ⇒ 绿。两条方向都断言，防「判据恒红」与「判据恒绿」；
3. **真库判据**（`test_schema_sql_builds_with_on_error_stop_1`）：`ON_ERROR_STOP=1` 跑**全文**
   **exit 0** + **零 ERROR**。缺 PG 的处置收口在 `pg_cluster.py`（CI 判**红** / 本机显式 skip，issue #5203）；
4. **目标段落真跑到**：`production_route_signals` 行数 == schema.sql **自己给的行数**
   （**不写死数字**，数字从文件现场派生）且 V63 终态（`四爪钩/四叉钩` → `韩褶`）真的生效
   —— **不把「没跑到」读成「没问题」**（否则行数判据退化成空断言）。

## 登记不改（#4767 的面）

`deploy/docker-compose.yml` 的挂载与 entrypoint 的 `ON_ERROR_STOP` 属部署链（#4767 在飞）
⇒ 本单**只登记不改**；挂载存在性由既有 `test_schema_integrity.py` 的
`test_compose_mounts_schema_sql_as_init_script` 守（不在此重复一道门）。
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
SCHEMA = REPO / "docs" / "sql" / "schema.sql"

#: `deploy/docker-compose.yml` 把本文件挂成的 initdb 脚本名（**登记用**，见模块 docstring）
COMPOSE_INITDB_TARGET = "docker-entrypoint-initdb.d/001_schema.sql"

_INSERT_ANY = re.compile(r"INSERT\s+INTO\s+(\w+)", re.I)
_INSERT_HEAD = re.compile(
    r"INSERT\s+INTO\s+(\w+)\s*\(([^)]*)\)\s*(?:OVERRIDING\s+SYSTEM\s+VALUE\s*)?VALUES",
    re.I,
)
#: 逐租户重放形态（`INSERT … SELECT … FROM tenants`）：值级判不了（键是 `'x-' || t.id`），
#: 但**顺序**同样致命 —— 排在租户种子之前会静默插入 **0 行**（本仓最忌的静默失败）。
_INSERT_SELECT = re.compile(
    r"INSERT\s+INTO\s+(\w+)\s*(?:\([^)]*\))?\s*(?:OVERRIDING\s+SYSTEM\s+VALUE\s*)?SELECT",
    re.I,
)
_FROM_TENANTS = re.compile(r"\bFROM\s+tenants\b", re.I)
_CREATE_TABLE = re.compile(
    r"\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(", re.I
)
_ALTER_FK = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)\s+ADD\s+CONSTRAINT\s+\w+\s+"
    r"FOREIGN\s+KEY\s*\(\s*(\w+)\s*\)\s*REFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)",
    re.I,
)
_INT_LITERAL = re.compile(r"^-?\d+$")
#: V60 信号种子段（含紧随其后的 V63 终态 `UPDATE`）—— 见 `_signal_seed_block()`
_SIGNAL_BLOCK = re.compile(r"-- 信号种子（tenant_id=1；.*?AND deleted = 0;\n", re.S)


# ══════════════════════════════════════════════════════════════════════════════════════
# 解析：`CREATE TABLE` 的外键图 + 每处 `INSERT … VALUES` 的逐行字面量
# ══════════════════════════════════════════════════════════════════════════════════════

def _table_fks(text: str) -> dict[str, dict[str, tuple[str, str]]]:
    """`{表: {本表列: (被引用表, 被引用列)}}` —— 列内联 `REFERENCES` + 表级 `FOREIGN KEY` + `ALTER TABLE`。"""
    fks: dict[str, dict[str, tuple[str, str]]] = {}
    cur: str | None = None
    for line in text.split("\n"):
        code = line.split("--", 1)[0]
        m = _CREATE_TABLE.match(code)
        if m:
            cur = m.group(1).lower()
            fks.setdefault(cur, {})
        if cur is not None:
            inline = re.match(
                r"\s*(\w+)\s+[^,]*?\bREFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)", code, re.I
            )
            if inline:
                fks[cur].setdefault(
                    inline.group(1).lower(), (inline.group(2).lower(), inline.group(3).lower())
                )
            table_level = re.search(
                r"\bFOREIGN\s+KEY\s*\(\s*(\w+)\s*\)\s*REFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)",
                code, re.I,
            )
            if table_level:
                fks[cur].setdefault(
                    table_level.group(1).lower(),
                    (table_level.group(2).lower(), table_level.group(3).lower()),
                )
        if re.match(r"\s*\)\s*;", code):
            cur = None
    for m in _ALTER_FK.finditer(text):
        fks.setdefault(m.group(1).lower(), {}).setdefault(
            m.group(2).lower(), (m.group(3).lower(), m.group(4).lower())
        )
    return fks


def _scan_literal(chunk: str, i: int) -> int:
    """`chunk[i]` 是单引号 ⇒ 返回**收尾引号之后**的下标（`''` 是转义，不结束）。"""
    j = i + 1
    while j < len(chunk):
        if chunk[j] == "'":
            if j + 1 < len(chunk) and chunk[j + 1] == "'":
                j += 2
                continue
            return j + 1
        j += 1
    return len(chunk)


def _rows_of_values(text: str, start: int) -> list[str]:
    """从 `VALUES` 之后扫出顶层 `(…)` 行（字符串字面量内的括号/逗号不参与）。"""
    rows: list[str] = []
    i, depth, cur = start, 0, ""
    while i < len(text):
        ch = text[i]
        if ch == "'":
            end = _scan_literal(text, i)
            if depth >= 1:
                cur += text[i:end]
            i = end
            continue
        if ch == "(":
            depth += 1
            if depth == 1:
                cur = ""
                i += 1
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                rows.append(cur)
                cur = ""
                i += 1
                continue
        elif ch == ";" and depth == 0:
            break
        if depth >= 1:
            cur += ch
        i += 1
    return rows


def _split_values(row: str) -> list[str]:
    """按**顶层**逗号拆一行 `VALUES`（嵌套括号/字符串字面量内的逗号不拆）。"""
    out: list[str] = []
    i, depth, cur = 0, 0, ""
    while i < len(row):
        ch = row[i]
        if ch == "'":
            end = _scan_literal(row, i)
            cur += row[i:end]
            i = end
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            i += 1
            continue
        cur += ch
        i += 1
    out.append(cur.strip())
    return out


def _inserts(text: str) -> list[tuple[int, str, list[str], list[list[str]]]]:
    """`[(起始行号, 表, 列名, 逐行值)]` —— 只收 `INSERT … (列) … VALUES` 形态。"""
    out = []
    for m in _INSERT_HEAD.finditer(text):
        cols = [c.strip().lower() for c in m.group(2).split(",")]
        rows = [_split_values(r) for r in _rows_of_values(text, m.end())]
        out.append((text.count("\n", 0, m.start()) + 1, m.group(1).lower(), cols, rows))
    return out


def _literal(value: str) -> str | None:
    """字面量归一化；**表达式/函数调用 ⇒ `None`**（判不了就不猜）。"""
    v = value.strip()
    if v == "" or v.upper() == "NULL":
        return None
    if v.startswith("'") and v.endswith("'") and len(v) >= 2:
        return v[1:-1].replace("''", "'")
    if _INT_LITERAL.match(v):
        return str(int(v))
    return None


def fk_seed_order_violations(text: str) -> list[str]:
    """全文扫描：带字面量 FK 值的 `INSERT` 引用的行，是否已在**更早**的 `INSERT` 里种下。

    返回违规描述列表（空 = 合规）。**表级 + 值级**双判：
    `越序` = 该值只在**后面**才种下（本单的缺陷形态）；`缺失` = 全文根本没种下
    （bootstrap 不跑迁移链 ⇒ 同样是建库必炸，只是不一定是顺序问题）。
    """
    fks = _table_fks(text)
    inserts = _inserts(text)
    # `{表: {被引用列: {值: 最早行号}}}`
    seeded: dict[str, dict[str, dict[str, int]]] = {}
    for lineno, table, cols, rows in inserts:
        for row in rows:
            for idx, col in enumerate(cols):
                if idx >= len(row):
                    continue
                val = _literal(row[idx])
                if val is None:
                    continue
                seeded.setdefault(table, {}).setdefault(col, {}).setdefault(val, lineno)

    violations: list[str] = []
    for lineno, table, cols, rows in inserts:
        for col, (ref_table, ref_col) in sorted(fks.get(table, {}).items()):
            if col not in cols:
                continue
            idx = cols.index(col)
            for row in rows:
                if idx >= len(row):
                    continue
                val = _literal(row[idx])
                if val is None:
                    continue
                at = seeded.get(ref_table, {}).get(ref_col, {}).get(val)
                if at is None:
                    violations.append(
                        f"L{lineno} INSERT INTO {table} 的 {col}={val!r} 引用的 "
                        f"{ref_table}.{ref_col} 全文未种下（bootstrap 不跑迁移链 ⇒ 建库必炸）"
                    )
                elif at > lineno:
                    violations.append(
                        f"L{lineno} INSERT INTO {table} 的 {col}={val!r} 引用的 "
                        f"{ref_table}.{ref_col}={val!r} 在 **L{at}**（更晚）才种下 ⇒ "
                        f"越序（ON_ERROR_STOP=1 下建库在此中止）"
                    )
    return sorted(set(violations))


def _signal_seed_block(text: str) -> str:
    """V60 信号种子 + V63 终态修正那一段（逐字；含注释）。"""
    hits = _SIGNAL_BLOCK.findall(text)
    assert len(hits) == 1, (
        f"schema.sql 里 V60 信号种子段（`-- 信号种子（tenant_id=1；` … `AND deleted = 0;`）"
        f"应恰好 1 段，实为 {len(hits)} 段 —— 段落被删/被改名/被复制 ⇒ 本文件的顺序判据会"
        "退化成空断言，故在此 fail-closed"
    )
    return hits[0]


def _inject_wrong_order(text: str) -> str:
    """红证注入：把信号种子段移到**租户种子之前**（= 本单修复前的越序形态）。"""
    block = _signal_seed_block(text)
    rest = text.replace(block, "", 1)
    at = rest.index("INSERT INTO tenants")
    return rest[:at] + block + rest[at:]


# ══════════════════════════════════════════════════════════════════════════════════════
# ① 静态顺序判据（不需要 PG ⇒ CI 可见）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_no_fk_seed_precedes_the_row_it_references():
    """机械判据：全文**任何**带字面量 FK 值的种子，都不得越序（不许只修一处）。"""
    text = SCHEMA.read_text(encoding="utf-8")
    violations = fk_seed_order_violations(text)
    assert violations == [], (
        "docs/sql/schema.sql 有越序的 FK 种子 ⇒ `ON_ERROR_STOP=1` 建库会中止"
        "（docker-entrypoint-initdb.d 栈正是该模式）：\n  " + "\n  ".join(violations)
    )


def test_order_scan_is_not_vacuous():
    """自证：扫描器真的看到了 FK 与种子，且**每一处 `INSERT` 都被分类**（防「解析坏了 ⇒ 假绿」）。"""
    text = SCHEMA.read_text(encoding="utf-8")
    fks = _table_fks(text)
    inserts = _inserts(text)
    signal_fks = fks.get("production_route_signals", {})
    assert signal_fks.get("tenant_id") == ("tenants", "id"), (
        f"扫描器没解出 `production_route_signals.tenant_id → tenants.id`：{signal_fks!r} "
        "⇒ 顺序判据是空断言"
    )
    assert len(fks) > 40, f"扫描器只解出 {len(fks)} 张表的 FK —— 解析坏了，判据不可信"

    # 每一处 `INSERT INTO` 必须归入两类之一：`VALUES`（值级可判）或 `SELECT`（逐租户重放，
    # 由下面的专门判据守顺序）。**不写死条数** —— 等式本身就是「无遗漏」的判据。
    total = len(_INSERT_ANY.findall(text))
    select_form = len(_INSERT_SELECT.findall(text))
    assert len(inserts) + select_form == total, (
        f"有 INSERT 没被分类：全部 {total} 处、VALUES 形态 {len(inserts)} 处、"
        f"SELECT 形态 {select_form} 处 ⇒ 有种子悄悄逃出了判据（假绿）"
    )
    assert len(inserts) > 0 and select_form > 0, "两类种子至少各有一处，否则等式是空断言"


def test_tenants_seed_precedes_every_seed_that_references_tenant_1():
    """本单的靶心（判据读起来像人话的那一半）：引用 `tenants(id)=1` 的种子都在租户种子之后。"""
    text = SCHEMA.read_text(encoding="utf-8")
    fks = _table_fks(text)
    tenants_at = text.index("INSERT INTO tenants")
    referencing = [
        (lineno, table)
        for lineno, table, cols, rows in _inserts(text)
        if fks.get(table, {}).get("tenant_id", ("", ""))[0] == "tenants"
        and "tenant_id" in cols
        and any(
            idx < len(row) and _literal(row[idx]) is not None
            for row in rows
            for idx in [cols.index("tenant_id")]
        )
    ]
    # 非空断言要有**结构性锚点**（不写死条数）：这三张表必然在其列，否则扫描器漏解了 FK。
    tables = {t for _, t in referencing}
    assert {"roles", "production_operations", "production_route_signals"} <= tables, (
        f"扫描器漏掉了必然引用 tenants(id) 的种子表：找到 {sorted(tables)} ⇒ 判据不可信"
    )
    tenants_line = text.count("\n", 0, tenants_at) + 1
    too_early = [f"L{lineno} {table}" for lineno, table in referencing if lineno < tenants_line]
    assert too_early == [], (
        f"这些引用 tenants(id) 的种子排在租户种子（L{tenants_line}）之前："
        f"{too_early} ⇒ 建库在 FK 上中止（issue #4762）"
    )


def test_per_tenant_replay_seeds_run_after_the_tenant_seed():
    """`INSERT … SELECT … FROM tenants` 的逐租户重放段也必须排在租户种子之后。

    排在之前 ⇒ 读不到租户行 ⇒ **静默插入 0 行**（脚本 exit 0、库里空）—— 与 FK 中止同源，
    只是显形方式更隐蔽（本仓最忌的静默失败形态）。
    """
    text = SCHEMA.read_text(encoding="utf-8")
    tenants_line = text.count("\n", 0, text.index("INSERT INTO tenants")) + 1
    replayed = []
    for m in _INSERT_SELECT.finditer(text):
        body = text[m.start():m.start() + 4000]
        body = body[:body.find(";") + 1 if ";" in body else len(body)]
        if _FROM_TENANTS.search(body):
            replayed.append((text.count("\n", 0, m.start()) + 1, m.group(1).lower()))
    assert len(replayed) > 0, (
        "没找到任何 `INSERT … SELECT … FROM tenants` 段 ⇒ 本判据是空断言（扫描口径漂了）"
    )
    too_early = [f"L{lineno} {table}" for lineno, table in replayed if lineno < tenants_line]
    assert too_early == [], (
        f"这些逐租户重放段排在租户种子（L{tenants_line}）之前：{too_early} "
        "⇒ 读不到租户行 ⇒ 静默插入 0 行（exit 0、库里空）"
    )


def test_signal_seed_and_its_terminal_update_stay_adjacent_in_order():
    """`INSERT` 与紧随其后的 `UPDATE` 必须同段且**顺序不变**（分开 = 终态漂移）。

    `UPDATE … WHERE signal IN ('四爪钩','四叉钩')` 命中的正是 `INSERT` 刚种下的两行
    ⇒ 把 `UPDATE` 留在原处而只搬 `INSERT`，终态会静默退回 `craft='四爪钩'`（本仓最忌的静默）。
    """
    text = SCHEMA.read_text(encoding="utf-8")
    block = _signal_seed_block(text)
    i_insert = block.index("INSERT INTO production_route_signals")
    i_update = block.index("UPDATE production_route_signals")
    assert i_insert < i_update, "信号种子的 `UPDATE` 排到了 `INSERT` 之前 ⇒ 终态漂移（改不到刚种的行）"


def test_injected_wrong_order_is_detected():
    """🔴 红证（注入式，两个方向都断言，防「恒红」与「恒绿」）。"""
    text = SCHEMA.read_text(encoding="utf-8")
    assert fk_seed_order_violations(text) == [], "前提失效：修好的文件本身应当零违规"

    broken = _inject_wrong_order(text)
    assert broken != text, "注入没有生效（段落替换没命中）⇒ 本红证是空断言"
    violations = fk_seed_order_violations(broken)
    assert violations != [], "把信号种子移回租户种子之前，顺序判据**没红** ⇒ 判据抓不住本单的缺陷"
    assert any("production_route_signals" in v for v in violations), (
        f"红是红了，但红的不是靶心：{violations}"
    )


def test_compose_initdb_mount_name_is_still_the_documented_one():
    """**登记用**：compose 挂的 initdb 脚本名（#4767 在飞 ⇒ 本单只登记不改）。

    只核「这个名字在 compose 里出现过」—— 部署链的实质判据在
    `test_schema_integrity.py`（挂载 + entrypoint + healthcheck），不在此重复。
    """
    compose = (REPO / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert COMPOSE_INITDB_TARGET in compose, (
        f"compose 不再把 schema.sql 挂成 {COMPOSE_INITDB_TARGET} ⇒ 本守卫的靶子（本地/CI 建库路径）"
        "变了，需同步复核（部署链属 #4767 的面）"
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# ② 真库判据（临时 PG 集群；缺 PG 的处置收口在 `pg_cluster.py`：CI 判**红** / 本机 skip）
# ══════════════════════════════════════════════════════════════════════════════════════



def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Pg:
    """临时集群句柄：`query()` 严格跑单条；`run_file()` 复刻 docker entrypoint 的 `-f` + `ON_ERROR_STOP=1`。"""

    def __init__(self, sockdir: Path, port: int, bins: dict[str, str]):
        self.sockdir, self.port = sockdir, port
        self.bins = bins  # 收口件给的**绝对路径**（issue #5203）

    def _psql(self, args: list[str], **kw) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.bins["psql"], "-h", str(self.sockdir), "-p", str(self.port), "-U", "postgres",
             "-d", "postgres", "-X", "-q", *args],
            text=True, capture_output=True, **kw,
        )

    def query(self, sql: str) -> str:
        proc = self._psql(["-t", "-A", "-v", "ON_ERROR_STOP=1", "-c", sql])
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout.strip()

    def run_file(self, path: Path) -> subprocess.CompletedProcess:
        """`ON_ERROR_STOP=1` 跑**全文** —— 与 docker entrypoint 执行 initdb 脚本同款。"""
        return self._psql(["-v", "ON_ERROR_STOP=1", "-f", str(path)])


@pytest.fixture(scope="module")
def pg(realdb_binaries):
    """真库夹具；缺 PG 的处置收口在 `pg_cluster.py`（CI 判**红** / 本机显式 skip，issue #5203）。"""
    with tempfile.TemporaryDirectory(prefix="migao4762-") as td:
        tmp = Path(td)
        datadir = tmp / "pgdata"
        # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限（tmp_path 太长 ⇒ pg_ctl start 失败）。
        sockdir = Path(tempfile.mkdtemp(prefix="pg4762-"))
        log = tmp / "pg.log"
        subprocess.run([realdb_binaries["initdb"], "-D", str(datadir), "-U", "postgres", "-A", "trust"],
                       check=True, capture_output=True)
        port = _free_port()
        started = subprocess.run(
            [realdb_binaries["pg_ctl"], "-D", str(datadir), "-l", str(log), "-o",
             f"-k {sockdir} -p {port} -c listen_addresses=''", "start"],
            capture_output=True, text=True,
        )
        assert started.returncode == 0, (
            f"临时集群起不来：{started.stdout}\n{started.stderr}\n"
            f"{log.read_text(encoding='utf-8') if log.exists() else ''}")
        try:
            yield _Pg(sockdir, port, realdb_binaries)
        finally:
            subprocess.run([realdb_binaries["pg_ctl"], "-D", str(datadir), "-m", "immediate", "stop"],
                           capture_output=True)
            shutil.rmtree(sockdir, ignore_errors=True)


def test_real_db_harness_actually_ran(pg):
    """自证：真库夹具真的起来了（防「夹具坏了 ⇒ 后面全 skip ⇒ 看起来像绿」）。"""
    assert pg.query("SELECT 1") == "1", "临时集群没起来 —— 后续真库判据全是假绿"


def test_schema_sql_builds_with_on_error_stop_1(pg):
    """🔴 机械判据：`ON_ERROR_STOP=1` 跑**全文** ⇒ **exit 0** + **零 ERROR**。

    ⚠️ **不许**用 `ON_ERROR_STOP=0`（那正是吞掉错误的原因：实测越序时它 exit=0、只留一行 ERROR
    在输出里，脚本「看起来成功」）。
    """
    proc = pg.run_file(SCHEMA)
    combined = proc.stdout + proc.stderr
    errors = [l for l in combined.splitlines() if "ERROR:" in l or "错误:" in l]
    assert errors == [], f"schema.sql 建库报错（ON_ERROR_STOP=1 下即中止）：\n  " + "\n  ".join(errors)
    assert proc.returncode == 0, (
        f"`psql -v ON_ERROR_STOP=1 -f docs/sql/schema.sql` 非零退出（exit={proc.returncode}）⇒ "
        f"docker-entrypoint-initdb.d 栈会建库中止。输出尾部：\n{combined[-1500:]}"
    )


def test_target_segment_actually_ran(pg):
    """目标段落**真的跑到了**（行数从 schema.sql 现场派生，**不写死数字**）+ V63 终态生效。"""
    text = SCHEMA.read_text(encoding="utf-8")
    block = _signal_seed_block(text)
    seed_rows = _rows_of_values(block, block.index("VALUES"))
    assert len(seed_rows) > 0, "信号种子段解析出 0 行 ⇒ 本判据会退化成空断言（fail-closed）"

    counted = pg.query("SELECT count(*) FROM production_route_signals;")
    assert counted == str(len(seed_rows)), (
        f"`production_route_signals` 实际 {counted} 行，schema.sql 的种子段给了 {len(seed_rows)} 行 "
        "⇒ 段落没跑到 / 被 ON CONFLICT 吞了 / 解析口径漂了"
    )

    targets = re.findall(r"'([^']+)'", re.search(r"WHERE signal IN \(([^)]*)\)", block).group(1))
    assert len(targets) == 2, f"V63 的 UPDATE 目标信号应为 2 个，实为 {targets}"
    repointed = pg.query(
        "SELECT count(*) FROM production_route_signals WHERE craft = '韩褶' "
        f"AND signal IN ({', '.join(repr(t) for t in targets)});"
    )
    assert repointed == "2", (
        f"V63 终态没生效：`{'/'.join(targets)}` 里只有 {repointed} 行 craft='韩褶' "
        "⇒ `UPDATE` 没跑在 `INSERT` 之后（或 `INSERT` 没跑到）"
    )
