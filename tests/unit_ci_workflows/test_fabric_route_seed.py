# case_ids: PG-018, PG-035, PG-039
"""布料基础路线的**种子层**守卫（issue #4529，包 F）—— 「每租户恰好两条路线 + 一条默认」。

## 本文件判什么

| # | 判据 | 红证形态 |
|---|---|---|
| 1 | **每租户恰好两条**基础路线：`窗帘工序路线（默认）`（`is_default=TRUE`）+ `布料工序路线`（`FALSE`） | 只种窗帘 ⇒ 红；布料也标默认 ⇒ 红 |
| 2 | **恰好一条默认**：DB 侧由部分唯一索引 `uk_production_route_templates_tenant_default`（`WHERE is_default AND deleted = 0`）保证 ≤1，种子侧由「一条 TRUE + 一条 FALSE」保证 ≥1 | 两条都 TRUE ⇒ 红；两条都 FALSE ⇒ 红 |
| 3 | 存量租户走**按租户循环**（`FROM tenants`）回填，不是只种 1 号租户 | 去掉 `FROM tenants` ⇒ 红 |
| 4 | 布料路线 = `positions=["布料"]` / `mainline=["配料","打包"]` / `is_default=FALSE`，且三源一致 | 改主线/改默认标记 ⇒ 红 |
| 5 | 窗帘主线的**终态**含 `打包`（10 道），且 `打包` 只出现 1 行 | 主线仍 9 道 ⇒ 红 |
| 6 | 每租户都必须有 `打包`/`配料` 两道**工序行**（否则 10 道主线在实例化时 `missing_operations` ⇒ 全量建单 422） | 只种 1 号租户的工序 ⇒ 红 |

## 为什么这几条必须落在**种子层**

`resolveRoute` 的 T3 是 fail-closed（#4116 已落码）：某租户没有默认路线模板 / 路线引用的工序
在库中缺行 ⇒ **该租户一张加工单也生成不了（422）**。而「10 道主线」一旦落进种子，任何**缺
`打包` 工序行**的租户都会当场 422 ⇒ 判据 6 是判据 5 的前置。

## 红证

`TestInjectedDrift` 用注入式自证证明解析器与判据**真能红**（少一条路线 / 两条默认 / 去掉按租户循环）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
SCHEMA = REPO / "docs/sql/schema.sql"
V79 = MIGRATION_DIR / "V79__seed_fabric_route_and_packing_operation.sql"

DEFAULT_TEMPLATE_NAME = "窗帘工序路线（默认）"
FABRIC_TEMPLATE_NAME = "布料工序路线"
FABRIC_MAINLINE = ("配料", "打包")
CURTAIN_MAINLINE = ("精裁", "三边", "熨烫", "定型", "复烫", "车被",
                    "外帘打卷", "打包", "外帘装袋", "外帘发货")

_VERSION_RE = re.compile(r"^V(\d+)__")


def _version_key(name: str):
    m = _VERSION_RE.match(Path(name).name)
    return (int(m.group(1)) if m else 1 << 30, name)


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _migration_sql() -> str:
    assert V79.exists(), f"缺 {V79.name}（布料路线与打包工序的种子迁移）"
    return _read(V79)


def _strip_comments(sql: str) -> str:
    """去 `--` 行注释 —— 守卫必须看**可执行 SQL**（注释里的字面量不是实现）。"""
    return "\n".join(line for line in sql.split("\n") if not line.lstrip().startswith("--"))


# ── 路线模板的 INSERT（字面量种子 vs 按租户派生回填）──

_TEMPLATE_INSERT_RE = re.compile(r"INSERT\s+INTO\s+production_route_templates\b[\s\S]*?;", re.I)
_NAME_DEFAULT_RE = re.compile(r"'(?P<name>[^']*)'\s*,\s*(?P<default>TRUE|FALSE)\s*,")


def template_inserts(sql: str) -> list:
    """`[(是否字面量, 语句)]`——**逐条**取（不去重、不排序）。"""
    out = []
    for stmt in _TEMPLATE_INSERT_RE.findall(sql):
        lowered = stmt.lower()
        values_at = lowered.find("values")
        select_at = lowered.find("select")
        literal = values_at != -1 and (select_at == -1 or values_at < select_at)
        out.append((literal, stmt))
    return out


def derived_template_inserts(migration_dir: Path = MIGRATION_DIR) -> list:
    """全部**按租户派生**的路线模板回填（`INSERT … SELECT … FROM tenants`），版本号序。"""
    out = []
    for path in sorted(Path(migration_dir).glob("V*.sql"), key=lambda p: _version_key(p.name)):
        body = _strip_comments(_read(path))
        for literal, stmt in template_inserts(body):
            if not literal and re.search(r"\bFROM\s+tenants\b", stmt, re.I):
                out.append((path.name, stmt))
    return out


def named_defaults(stmt: str) -> dict:
    """语句里 `'<路线名>', <TRUE|FALSE>,` 的映射（种子语句里该形态唯一）。"""
    return {m.group("name"): m.group("default") == "TRUE"
            for m in _NAME_DEFAULT_RE.finditer(stmt)}


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 1/2/3：每租户恰好两条路线、恰好一条默认、按租户循环
# ══════════════════════════════════════════════════════════════════════════════════

def test_every_tenant_gets_exactly_two_base_routes_with_one_default():
    """**每个**活跃租户拿到两条基础路线，且**恰好一条** `is_default=TRUE`。

    形态：V72 的按租户回填种窗帘路线（`TRUE`）+ V79 的按租户回填种布料路线（`FALSE`）
    ⇒ 两条派生回填、一条默认。只种窗帘（今天的状态）或两条都标默认 ⇒ 红。
    """
    derived = derived_template_inserts()
    assert derived, (
        "没有任何按租户派生回填的路线模板语句 ⇒ 存量租户拿不到路线（非 1 号租户建单 422）"
    )
    merged: dict = {}
    for name, stmt in derived:
        for route_name, is_default in named_defaults(stmt).items():
            if route_name in merged and merged[route_name] != is_default:
                raise AssertionError(
                    f"路线 `{route_name}` 在两个源里的默认标记冲突（{merged[route_name]} vs {is_default}）"
                )
            merged[route_name] = is_default
    assert merged == {DEFAULT_TEMPLATE_NAME: True, FABRIC_TEMPLATE_NAME: False}, (
        f"每租户的路线集合/默认标记不对：{merged} —— 应为「窗帘=默认 + 布料=非默认」"
        f"（V76 是 V72 的重做，故派生语句条数可能 > 2；这里判**去重后的路线集合**）"
    )
    assert sum(1 for v in merged.values() if v) == 1, "恰好一条默认（0 条 / 2 条默认 ⇒ 红）"


def test_derived_backfill_loops_over_tenants_and_is_idempotent():
    """两条回填都必须**按租户循环**且幂等（业务唯一键去重）—— 否则非 1 号租户零路线 ⇒ 建单 422。"""
    for name, stmt in derived_template_inserts():
        assert re.search(r"\bFROM\s+tenants\b", stmt, re.I), f"{name} 的路线回填没有按租户循环"
        assert re.search(r"\bNOT\s+EXISTS\b", stmt, re.I), (
            f"{name} 的路线回填没有按业务唯一键 `(tenant_id, name)` 去重 —— "
            f"重复套用会撞 `uk_production_route_templates_tenant_name`（或造出第二条默认）"
        )


def test_db_enforces_at_most_one_default_route_per_tenant():
    """DB 侧不变式：每租户活跃路线中**至多一条**默认（部分唯一索引）。"""
    schema = _read(SCHEMA)
    assert re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?uk_production_route_templates_tenant_default"
        r"[\s\S]{0,160}?WHERE\s+is_default\s+AND\s+deleted\s*=\s*0", schema, re.I), (
        "schema.sql 缺「每租户至多一条默认路线」的部分唯一索引 ⇒ 两条默认能在库里共存"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 4/5：终态（schema.sql）的两条路线逐值
# ══════════════════════════════════════════════════════════════════════════════════

def _literal_template_rows(sql: str) -> list:
    """字面量种子行 → `[{name, is_default, positions, mainline}]`（终态逐值口径）。"""
    rows = []
    for literal, stmt in template_inserts(sql):
        if not literal:
            continue
        for raw in re.findall(r"\(\s*'[^']*'\s*,\s*1\s*,\s*'([^']*)'\s*,\s*(TRUE|FALSE)\s*,\s*"
                              r"'([^']*)'::jsonb\s*,\s*'([^']*)'::jsonb\s*,\s*'([^']*)'\s*\)", stmt):
            rows.append({"name": raw[0], "is_default": raw[1] == "TRUE",
                         "positions": tuple(re.findall(r'"([^"]+)"', raw[2])),
                         "mainline": tuple(re.findall(r'"([^"]+)"', raw[3])),
                         "status": raw[4]})
    return rows


def test_schema_sql_terminal_state_has_both_routes():
    """bootstrap 终态（新建库不跑迁移链）必须**一次给全**两条路线（缺 ⇒ 新建库布料单 422）。"""
    rows = _literal_template_rows(_read(SCHEMA))
    by_name = {row["name"]: row for row in rows}
    assert set(by_name) == {DEFAULT_TEMPLATE_NAME, FABRIC_TEMPLATE_NAME}, (
        f"schema.sql 的路线终态 = {sorted(by_name)}（应为窗帘 + 布料两条）"
    )
    curtain = by_name[DEFAULT_TEMPLATE_NAME]
    fabric = by_name[FABRIC_TEMPLATE_NAME]
    assert curtain["is_default"] is True and fabric["is_default"] is False, \
        "默认标记错：窗帘=TRUE / 布料=FALSE（恰好一条默认）"
    assert curtain["mainline"] == CURTAIN_MAINLINE, (
        f"窗帘主线终态漂移：{curtain['mainline']}（应为 9 道 + 打包 = 10 道，打包在装袋之前）"
    )
    assert fabric["positions"] == ("布料",), f"布料路线的适用部位应为 [布料]：{fabric['positions']}"
    assert fabric["mainline"] == FABRIC_MAINLINE, f"布料主线应为 配料 → 打包：{fabric['mainline']}"
    assert all(row["status"] == "active" for row in rows), "路线终态必须都是 active（否则端点不可见）"


def test_curtain_mainline_carries_packing_in_every_source():
    """窗帘主线在两个源里都要含 `打包` 且**只一次**。

    · `schema.sql`（bootstrap 终态）：主线**字面量**逐字等于 10 道（含 `打包` 一次）；
    · `V79`（存量租户）：手术式 UPDATE 把 `打包` 插进默认路线的 `mainline`（插在 `外帘装袋`
      之前），幂等守卫 `NOT (mainline @> '["打包"]'::jsonb)`，且插入元素只出现一次。
    """
    schema_body = _strip_comments(_read(SCHEMA))
    literals = [ops for ops in re.findall(r"'(\[[^\]]*\])'::jsonb", schema_body)]
    assert any(tuple(re.findall(r'"([^"]+)"', ops)) == CURTAIN_MAINLINE for ops in literals), (
        f"schema.sql 里没有 10 道的窗帘主线字面量：{literals}"
    )
    body = _strip_comments(_migration_sql())
    assert re.search(r"UPDATE\s+production_route_templates\s+SET\s+mainline\s*=", body, re.I), (
        "V79 没有把 `打包` 插进存量租户的默认主线 ⇒ 存量租户的主线仍是 9 道"
    )
    inserted = '\'"打包"\'::jsonb'
    assert body.count(inserted) == 1, (
        f"V79 里插入的 `打包` 元素出现 {body.count(inserted)} 次（应为 1 次 —— 多插会双付）"
    )
    assert re.search(r"is_default", body, re.I), "V79 的主线回填没有限定默认路线（会污染布料路线）"
    assert "@>" in body, "V79 的主线回填没有幂等守卫（重复执行会插两次 `打包`）"


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 6：每租户都必须有 配料/打包 两道工序行（否则 10 道主线 fail-closed 422）
# ══════════════════════════════════════════════════════════════════════════════════

_OP_INSERT_RE = re.compile(r"INSERT\s+INTO\s+production_operations\b[\s\S]*?;", re.I)
_OP_ROW_RE = re.compile(
    r"\(\s*'(?P<id>[^']*)'\s*,\s*(?P<tenant>\d+|t\.id)\s*,\s*'(?P<name>[^']*)'\s*,\s*'(?P<group>[^']*)'\s*,"
    r"\s*(?P<position>NULL|'[^']*')\s*,\s*'(?P<unit>[^']*)'\s*,\s*(?P<price>NULL|[\d.]+)\s*,"
    r"\s*(?P<must>TRUE|FALSE)\s*,\s*(?P<start>TRUE|FALSE)\s*,\s*(?P<sort>\d+)\s*,\s*'(?P<status>[^']*)'\s*\)")


def operation_inserts(sql: str) -> list:
    """`[(是否字面量, 语句)]`。"""
    out = []
    for stmt in _OP_INSERT_RE.findall(sql):
        lowered = stmt.lower()
        values_at, select_at = lowered.find("values"), lowered.find("select")
        out.append((values_at != -1 and (select_at == -1 or values_at < select_at), stmt))
    return out


def test_new_operations_are_seeded_for_every_tenant():
    """两条工序必须**同时**有 1 号租户字面量种子与**按租户循环**的种子。

    只种 1 号租户 ⇒ 非 1 号租户的主线含 `打包` 而工序库没有它 ⇒ `missing_operations` ⇒
    该租户**全量建单 422**（T3 fail-closed）。
    """
    body = _strip_comments(_migration_sql())
    literal_names, derived_stmts = [], []
    for literal, stmt in operation_inserts(body):
        if literal:
            literal_names = [m.group("name") for m in _OP_ROW_RE.finditer(stmt)]
        else:
            derived_stmts.append(stmt)
    assert literal_names == ["配料", "打包"], (
        f"V79 的工序字面量种子应为 配料/打包 两行（顺序即真值源字典序），实测 {literal_names}"
    )
    assert derived_stmts, (
        "V79 没有按租户循环种这两道工序 ⇒ 非 1 号租户的工序库没有 `打包`，"
        "而窗帘主线已含它 ⇒ `missing_operations` ⇒ 该租户**全量建单 422**（T3 fail-closed）"
    )
    joined = " ".join(derived_stmts)
    assert re.search(r"\bFROM\s+tenants\b", joined, re.I), "按租户回填没有 `FROM tenants`"
    assert re.search(r"\bNOT\s+EXISTS\b", joined, re.I), "按租户回填没有按业务唯一键去重（不幂等）"
    for name in ("配料", "打包"):
        assert f"'{name}'" in joined, f"按租户回填里没有 `{name}` ⇒ 部分租户缺这道工序"


def test_new_operations_carry_unit_price_and_pending_provenance():
    """逐值：`配料`=米 / `打包`=套 / 单价 0（DDL `NOT NULL DEFAULT 0`）/ 来源 `占位待确认`。

    ⚠️ 设计稿写「单价留空（NULL）」，但 `production_operations.unit_price` 是
    `NOT NULL DEFAULT 0`（V49 DDL）⇒ 工序库行落 0；「未定价」由**部位价目行**的
    `unit_price=NULL + applicable=TRUE` 承载（见 `test_fabric_route.py` 判据 5）。
    """
    body = _strip_comments(_migration_sql())
    rows = {}
    for literal, stmt in operation_inserts(body):
        if not literal:
            continue
        for m in _OP_ROW_RE.finditer(stmt):
            rows[m.group("name")] = m.groupdict()
    assert set(rows) == {"配料", "打包"}, f"V79 的工序种子行 = {sorted(rows)}"
    assert rows["配料"]["unit"] == "米" and rows["配料"]["group"] == "后道"
    assert rows["打包"]["unit"] == "套" and rows["打包"]["group"] == "后道"
    for name, row in rows.items():
        assert row["price"] == "0", f"{name} 的工序库单价应为 0（DDL NOT NULL DEFAULT 0）：{row['price']}"
        assert row["must"] == "FALSE" and row["start"] == "FALSE", f"{name} 的必完/开始标记应为 FALSE"
        assert row["status"] == "active"
    assert re.search(r"WHEN\s+id\s+LIKE\s+'op-v79-%'\s+THEN\s+'占位待确认'", body), (
        "V79 没有把两道新工序的 source 标成「占位待确认」（按 id 前缀认领）⇒ 未定价在数据上不可见"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 红证（注入式自证）
# ══════════════════════════════════════════════════════════════════════════════════

class TestInjectedDrift:
    """逐条注入 ⇒ 对应判据必须变红。"""

    _CURTAIN_ONLY = (
        "INSERT INTO production_route_templates (id, tenant_id, name, is_default, positions, mainline, status)\n"
        "SELECT 'rt-x-' || t.id, t.id, '窗帘工序路线（默认）', TRUE, '[\"布帘\"]'::jsonb,\n"
        "       '[\"精裁\"]'::jsonb, 'active'\n"
        "  FROM tenants t WHERE t.deleted = 0 AND NOT EXISTS (SELECT 1 FROM production_route_templates e)\n"
        "ON CONFLICT (id) DO NOTHING;")
    _FABRIC = (
        "INSERT INTO production_route_templates (id, tenant_id, name, is_default, positions, mainline, status)\n"
        "SELECT 'rt-y-' || t.id, t.id, '布料工序路线', FALSE, '[\"布料\"]'::jsonb,\n"
        "       '[\"配料\", \"打包\"]'::jsonb, 'active'\n"
        "  FROM tenants t WHERE t.deleted = 0 AND NOT EXISTS (SELECT 1 FROM production_route_templates e)\n"
        "ON CONFLICT (id) DO NOTHING;")

    def test_parser_reads_derived_inserts(self):
        """解析器能读出「派生回填」的路线名与默认标记（否则下面的判据是空跑）。"""
        assert named_defaults(self._CURTAIN_ONLY) == {DEFAULT_TEMPLATE_NAME: True}
        assert named_defaults(self._FABRIC) == {FABRIC_TEMPLATE_NAME: False}

    def test_two_defaults_are_detected(self):
        """两条路线都标 `TRUE` ⇒ 「恰好一条默认」判据会红。"""
        merged = {**named_defaults(self._CURTAIN_ONLY), **named_defaults(
            self._FABRIC.replace("FALSE", "TRUE"))}
        assert sum(1 for v in merged.values() if v) == 2, "两条默认读不出来 ⇒ 判据是空断言"

    def test_missing_fabric_route_is_detected(self):
        """只种窗帘路线 ⇒ 路线集合判据会红（今天的真实状态就是它）。"""
        merged = named_defaults(self._CURTAIN_ONLY)
        assert set(merged) != {DEFAULT_TEMPLATE_NAME, FABRIC_TEMPLATE_NAME}, \
            "缺布料路线读不出来 ⇒ 判据是空断言"

    def test_literal_row_parser_reads_mainline_order(self):
        """终态解析器能读出主线**顺序**（改顺序/删一道 ⇒ 判据 5 红）。"""
        sql = ("INSERT INTO production_route_templates (id, tenant_id, name, is_default, positions, mainline, status)\n"
               "VALUES ('rt-1', 1, '窗帘工序路线（默认）', TRUE, '[\"布帘\"]'::jsonb,\n"
               "        '[\"精裁\", \"打包\", \"外帘装袋\"]'::jsonb, 'active')\nON CONFLICT (id) DO NOTHING;")
        rows = _literal_template_rows(sql)
        assert rows and rows[0]["mainline"] == ("精裁", "打包", "外帘装袋"), \
            "终态解析器读不出主线顺序 ⇒ 判据 5 是空断言"
        assert rows[0]["mainline"] != CURTAIN_MAINLINE, "自证：漂移的主线确实与冻结值不等"
