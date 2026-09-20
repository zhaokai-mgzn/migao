# case_ids: PG-018
r"""报工明细「去重没有 DB 兜底」的真值面守卫（issue #4845）。

## 病根（本单要治的**静默误信**形态）

`production_work_logs` 是计件的**唯一凭证**，而它在**全库 migration 里没有任何 UNIQUE**
（建表迁移
`backend/admin-api/src/main/resources/db/migration/V49__create_production_operations_and_work_logs.sql`
只建了两条**非唯一**索引）。挡住重复写入的**不是**数据库，而是
`ProductionScanService` / `ProductionScanCompleteService` / `ProductionService` 里的**三道业务判据**。
真值源若**没写出**这条边界，后来人会**以为有 DB 兜底**（于是新增写路径时不再复用那三道判据），
或者反过来**顺手加一个 UNIQUE 约束**去"补兜底" —— 而**分段完成**
（同一工序两次合法提交之和 = 应做数量）本来就是**合法的多行**，
加约束会把合法写入**判死**。两种错误都不会有任何东西变红 —— 这正是本守卫存在的理由。

## 判据（每条都给「怎么让它红」）

| # | 判据 | 怎么让它红 |
|---|---|---|
| C1 | 全库 SQL（迁移目录 + `docs/sql/schema.sql`）对 `production_work_logs` **零 UNIQUE**（唯一索引 / 建表体内约束 / `ALTER TABLE … UNIQUE` 三种形态都扫） | 新增一个 `CREATE UNIQUE INDEX … ON production_work_logs …` 的迁移；或往建表体里塞 `UNIQUE (…)` |
| C2 | 三道应用层判据的**落点符号**仍在（`ProductionScanService` 的 `pending` + `isDone` 过滤 / `ProductionScanCompleteService#plannedRemaining` / `ProductionService#assertWithinPlannedQty` + `advanceDoneQtyIfUnchanged` 的 CAS） | 摘掉或改名任一处 ⇒ 去重只剩两道或更少 |
| C3 | 真值源**登记了**该边界（设计 `docs/design/set-code-and-scan-loop.md` 的 §5.3.2 + `docs/curtain-production-rules.md` 的 §5 各有一段文本锚点） | 删掉登记语句 ⇒ 边界重新变成「没人知道」 |
| C4 | **判据不恒真**（反空跑 + 判别力）：检测器在**注入载荷**上必须报出来、在**非唯一索引**与**别的表**上必须不报；且真扫读到的 SQL 文件数 > 0、目标表建表体真的被解析到 | 检测器改成恒返回 `[]` ⇒ C4 红 |

## 引用纪律（本仓红线）

一律**符号引用**（类名#方法名 / 索引名 / 迁移文件名），**禁写** `path:行号` / 裸 `第 N 行` ——
drift 面 `ref-freshness` 与 Case Trust 规则 G 会把裸行号判红（`migao-dev-flow` §16.7）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
SCHEMA_SQL = REPO / "docs/sql/schema.sql"
SERVICE_DIR = REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
DESIGN = REPO / "docs/design/set-code-and-scan-loop.md"
PRODUCTION_RULES = REPO / "docs/curtain-production-rules.md"

#: 被判的表（计件明细 = 唯一凭证）
TARGET_TABLE = "production_work_logs"

#: 真值源里的**文本锚点**（不写行号 —— 行号会随文档编辑腐烂）
DESIGN_ANCHOR = "去重/幂等的真值面"
RULES_ANCHOR = "去重不靠 DB 唯一约束"

#: 三道应用层判据的落点（**符号引用** = 类#方法 + **方法体里**必须真的出现的调用）。
#: ⚠️ **判据落在「方法体内」而不是「文件里」**（实测教训）：`isDone(` 这类符号在同一个类里
#: **别处也有**（`ProductionScanService#completedAt` 同样调它）⇒ 按**文件级存在性**判就是
#: **空判据** —— 把 `pending` 的 `isDone` 过滤摘掉，文件级判据**照样绿**（本守卫初版正是这样，
#: 注入红证时当场暴露）。故按方法签名 + 花括号配平取体后判。
APP_LAYER_SITES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ProductionScanService", "pending", ("isDone(",)),
    ("ProductionScanCompleteService", "plannedRemaining", (".subtract(",)),
    ("ProductionService", "applyReport", ("assertWithinPlannedQty(", "advanceDoneQtyIfUnchanged(")),
)

# ── 检测器（纯函数，便于注入式自证）────────────────────────────────────────

_CREATE_UNIQUE_INDEX = re.compile(
    r"CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>[^\s(]+)\s+ON\s+(?P<table>[^\s(]+)\s*\(",
    re.I,
)
_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>[^\s(]+)\s*\(",
    re.I,
)
_ALTER_TABLE_UNIQUE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<table>[^\s(]+)\b(?P<body>[^;]*?)\bUNIQUE\b",
    re.I | re.S,
)
_UNIQUE_KEYWORD = re.compile(r"\bUNIQUE\b", re.I)


def _bare_table(token: str) -> str:
    """`public.production_work_logs` / `"production_work_logs"` ⇒ `production_work_logs`（小写）。"""
    return token.strip().strip('"`').split(".")[-1].lower()


def _token_before(sql: str, pos: int, pattern: str) -> str:
    """取 `pos` 之前最近的 `<pattern> <token>` 里的 token（用于读 `CONSTRAINT … UNIQUE` 的名字）。"""
    m = None
    for m in re.finditer(pattern, sql[:pos], re.I):
        pass
    return m.group(1) if m else ""


def table_bodies(sql: str, table: str) -> list[str]:
    """取 `CREATE TABLE <table> ( … )` 的括号体（**配平**，不看行号）。"""
    bodies: list[str] = []
    for m in _CREATE_TABLE.finditer(sql):
        if _bare_table(m.group("table")) != table.lower():
            continue
        start = sql.index("(", m.end() - 1)
        depth = 0
        for idx in range(start, len(sql)):
            if sql[idx] == "(":
                depth += 1
            elif sql[idx] == ")":
                depth -= 1
                if depth == 0:
                    bodies.append(sql[start: idx + 1])
                    break
    return bodies


def unique_constraints_on(sql: str, table: str) -> list[str]:
    """列出**指向 `table`** 的 UNIQUE（唯一索引 / 建表体内约束 / `ALTER TABLE … UNIQUE`）。

    🔴 **三种形态都扫**：只扫一种会**漏**（例如只扫 `CREATE UNIQUE INDEX` 就会漏掉
    建表体里的 `UNIQUE (tenant_id, operation_id)`）—— 漏 = 本守卫空跑。
    """
    hits: list[str] = []
    for m in _CREATE_UNIQUE_INDEX.finditer(sql):
        if _bare_table(m.group("table")) == table.lower():
            hits.append(f"UNIQUE INDEX {m.group('name')}")
    for body in table_bodies(sql, table):
        for u in _UNIQUE_KEYWORD.finditer(body):
            fragment = " ".join(body[max(0, u.start() - 60): u.end() + 60].split())
            hits.append(f"表内 UNIQUE：…{fragment}…")
    for m in _ALTER_TABLE_UNIQUE.finditer(sql):
        if _bare_table(m.group("table")) == table.lower():
            hits.append("ALTER TABLE … UNIQUE")
    return hits


def _sql_files() -> list[Path]:
    files = sorted(p for p in MIGRATION_DIR.glob("*.sql") if p.is_file())
    if SCHEMA_SQL.is_file():
        files.append(SCHEMA_SQL)
    return files


# ── C1：全库零 UNIQUE ─────────────────────────────────────────────────────

def test_c1_no_unique_constraint_on_work_logs_anywhere():
    offenders: dict[str, list[str]] = {}
    for path in _sql_files():
        hits = unique_constraints_on(path.read_text(encoding="utf8"), TARGET_TABLE)
        if hits:
            offenders[path.relative_to(REPO).as_posix()] = hits
    assert not offenders, (
        f"{TARGET_TABLE} 上出现了 UNIQUE：{offenders} —— 该表**有意**不加唯一约束："
        "「分段完成」（同一工序两次合法提交之和 = 应做数量）本来就是**合法的多行**，"
        "加约束会把合法写入判死（登记见 docs/design/set-code-and-scan-loop.md §5.3.2）。"
        "若确要加：先改真值源登记与本守卫，并证明分段完成不再合法"
    )


def test_c1_scan_is_not_vacuous():
    """反空跑：文件面非空、目标表**真的**被解析到、且当前读数是 0（不是"没读到"）。"""
    files = _sql_files()
    assert len(files) >= 20, f"迁移文件只读到 {len(files)} 个 ⇒ 扫描面疑似失效（真值源读不到 = 判据空跑）"

    create_sql = next(
        (p for p in files if p.name.startswith("V49__create_production_operations_and_work_logs")),
        None,
    )
    assert create_sql is not None, f"{TARGET_TABLE} 的建表迁移没被读到 ⇒ 扫描口径失效"
    text = create_sql.read_text(encoding="utf8")
    assert table_bodies(text, TARGET_TABLE), (
        f"建表体没解析出来（{create_sql.name}）⇒ table_bodies 的口径失效 ⇒ C1 会空跑"
    )
    assert unique_constraints_on(text, TARGET_TABLE) == [], (
        "建表迁移里读到了 UNIQUE —— 与 issue #4845 的真值登记相反"
    )
    # 建表体里**确实**有两处索引声明（非唯一）——证明这段 SQL 真的被本检测器读到了
    assert text.count("CREATE INDEX IF NOT EXISTS idx_work_logs_") == 2, (
        "建表迁移里 `idx_work_logs_*` 的两条**非唯一**索引没读到 ⇒ 读源口径漂了"
    )


# ── C2：三道应用层判据的落点仍在 ──────────────────────────────────────────

_METHOD_SIG = (
    r"^\s*(?:public|private|protected)\s+(?:static\s+)?[\w<>,.\[\]\s?]+?\s+%s\s*\([^;{]*\)\s*"
    r"(?:throws\s+[\w,.\s]+)?\{"
)


def method_body(src: str, method: str) -> str:
    """按**符号**取方法体（花括号配平）；取不到（改名/重载/搬走）⇒ 返回空串，由调用方判红。"""
    hits = list(re.finditer(_METHOD_SIG % re.escape(method), src, re.M))
    if len(hits) != 1:
        return ""
    start = src.index("{", hits[0].start())
    depth = 0
    for idx in range(start, len(src)):
        if src[idx] == "{":
            depth += 1
        elif src[idx] == "}":
            depth -= 1
            if depth == 0:
                return src[start: idx + 1]
    return ""


def test_c2_app_layer_dedup_sites_still_exist():
    missing: list[str] = []
    for cls, method, symbols in APP_LAYER_SITES:
        path = SERVICE_DIR / f"{cls}.java"
        assert path.is_file(), (
            f"落点源码不存在：{path.relative_to(REPO).as_posix()} ⇒ "
            "类被改名/搬走时，本守卫的「去重靠应用层判据」登记必须同步"
        )
        body = method_body(path.read_text(encoding="utf8"), method)
        if not body:
            missing.append(f"{cls}#{method}（方法体取不到 ⇒ 已改名/重载/搬走）")
            continue
        for symbol in symbols:
            if symbol not in body:
                missing.append(f"{cls}#{method} 的方法体里没有 {symbol}")
    assert not missing, (
        f"去重的应用层落点不见了：{missing} —— 该表**没有** DB 兜底（全库零 UNIQUE），"
        "这三道业务判据是**唯一**的去重承重；摘掉/改名时请同步真值源登记与本守卫"
    )


# ── C3：真值源登记了该边界 ────────────────────────────────────────────────

def test_c3_truth_sources_register_the_no_db_fallback_boundary():
    design = DESIGN.read_text(encoding="utf8")
    assert "### 5.3.2" in design, (
        "设计文档少了 §5.3.2（去重/幂等的真值面）⇒ 「没有 DB 兜底」重新变成没人知道的事"
    )
    assert DESIGN_ANCHOR in design, f"设计文档 §5.3.2 的文本锚点不见了：{DESIGN_ANCHOR!r}"
    assert TARGET_TABLE in design, f"设计文档 §5.3.2 没点名被判的表 {TARGET_TABLE}"

    rules = PRODUCTION_RULES.read_text(encoding="utf8")
    assert RULES_ANCHOR in rules, (
        f"真值源 {PRODUCTION_RULES.relative_to(REPO).as_posix()} 少了边界条目：{RULES_ANCHOR!r}"
    )
    assert TARGET_TABLE in rules, f"真值源 §5 的边界条目没点名被判的表 {TARGET_TABLE}"


# ── C4：注入式自证（检测器有判别力，不是恒返回 []）──────────────────────────

class TestDetectorSelfProof:
    """证明 C1 的绿**不是空跑**：同一判定体在注入载荷上必须报出来，在良性载荷上必须不报。"""

    def test_injected_unique_index_is_detected(self):
        sql = (
            "CREATE UNIQUE INDEX IF NOT EXISTS uk_probe_work_logs "
            f"ON {TARGET_TABLE} (tenant_id, operation_id) WHERE deleted = 0;"
        )
        assert unique_constraints_on(sql, TARGET_TABLE), "注入的唯一索引没被检测到 ⇒ C1 空跑"

    def test_injected_unique_inside_table_body_is_detected(self):
        sql = (
            f"CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (\n"
            "    id VARCHAR(64) PRIMARY KEY,\n"
            "    tenant_id BIGINT NOT NULL,\n"
            "    operation_id VARCHAR(64) NOT NULL,\n"
            "    UNIQUE (tenant_id, operation_id)\n"
            ");"
        )
        assert unique_constraints_on(sql, TARGET_TABLE), "注入的表内 UNIQUE 没被检测到 ⇒ 少扫一种形态"

    def test_injected_alter_table_unique_is_detected(self):
        sql = f"ALTER TABLE {TARGET_TABLE} ADD CONSTRAINT uk_probe UNIQUE (tenant_id, operation_id);"
        assert unique_constraints_on(sql, TARGET_TABLE), "注入的 ALTER TABLE … UNIQUE 没被检测到"

    def test_non_unique_index_is_not_flagged(self):
        """判别力：**非唯一**索引（本表真实形态）不得被误报 —— 否则 C1 变成永远红。"""
        sql = (
            "CREATE INDEX IF NOT EXISTS idx_work_logs_po "
            f"ON {TARGET_TABLE} (processing_order_id, operation_id) WHERE deleted = 0;"
        )
        assert unique_constraints_on(sql, TARGET_TABLE) == [], "非唯一索引被误判成 UNIQUE ⇒ C1 永远红"

    def test_unique_on_another_table_is_not_attributed(self):
        sql = "CREATE UNIQUE INDEX IF NOT EXISTS uk_keys ON client_request_keys (tenant_id, client_request_id);"
        assert unique_constraints_on(sql, TARGET_TABLE) == [], "别的表的 UNIQUE 被算到本表头上"
