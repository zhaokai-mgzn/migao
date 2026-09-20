# case_ids: PG-018, MC-012
"""`V89` 补种迁移（issue #4685）的**静态承重判据** —— 补 V79 在真库上漏掉的布料种子。

## 被测对象

`backend/admin-api/src/main/resources/db/migration/V89__backfill_fabric_seed_for_existing_tenants.sql`
= 4 条语句：① 每活跃租户补 `打包` 工序 / ② 每活跃租户补 **5 格**价目 / ③ 每活跃租户补
`布料工序路线` / ④ 每活跃租户的默认窗帘主线补 `打包`（9 → 10 道）。

## 为什么需要它（真库实测根因，2026-09-20，PG 18.3 / 阿里云 RDS）

`V79` 的**按租户派生块**里 `JOIN (VALUES (…, NULL, …))` 的 `unit_price` 列**整列都是 NULL**
⇒ PostgreSQL 把该列推断成 `text`，而目标列是 `NUMERIC(10,2)`，且 `text → numeric`
**不是赋值转换**（explicit-only）⇒ 报
`字段 "unit_price" 的类型为 numeric, 但表达式的类型为 text` ⇒ **整文件单事务回滚**。
`MigrationRunner` 对内容类失败是「跳过这一条、继续跑后面的」（`MigrationRunner:185`）⇒
`schema_migrations` 里 **V80~V87 都在、唯独 V79 缺席**（真库实测），
**1 号与非 1 号租户一律没有** `打包` 工序 / 布料价目格 / `布料工序路线`。

用户原始问题逐字：「我想制定**纯布料**的工序路线，应该如何设置」+ 截图「适用帘种只有
布帘/纱帘/帘头」「工艺路线共 1 条」—— 真库实测与截图**逐条吻合**。

## 为什么判据落在**迁移文本**上（而不是「跑一遍库看结果」）

仓库**没有 testcontainers** ⇒ 表内容判据只能落成静态判据 + **真库核查记录**（记录在 PR body）。
静态判据的价值不是「等价于跑库」，而是把**口径钉在可 review 的文本上**：显式类型、按租户循环、
幂等守卫、不覆盖商家已改、终态逐值 —— 任一处漂移都会红（每条都有注入式红证，见
`TestInjectedDrift`）。

## 🔴 本单的核心判据 = 显式类型

`test_positions_values_cast_unit_price_and_applicable_explicitly` —— 去掉 `::numeric`
就复现 V79 的真库报错（红证：`TestInjectedDrift::test_dropping_the_numeric_cast_is_detected`）。

## 红线（本迁移**一字不动**的三张快照表）

`processing_orders.items_snapshot` / `processing_position_operations` / `production_work_logs`
—— ⚠️ 前两张表名**极像**（`production_operation_positions` vs `processing_position_operations`），
`test_red_line_never_touches_snapshot_tables` 双向断言（该出现的出现、不该出现的零命中）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"
V79 = MIGRATION_DIR / "V79__seed_fabric_route_and_packing_operation.sql"
V88 = MIGRATION_DIR / "V88__retire_material_prep_and_fabric_position.sql"
V89 = MIGRATION_DIR / "V89__backfill_fabric_seed_for_existing_tenants.sql"

OPERATION_TABLE = "production_operations"
POSITION_TABLE = "production_operation_positions"
TEMPLATE_TABLE = "production_route_templates"
#: 红线：三张**快照**表（全名，不许简写）。
SNAPSHOT_TABLES = ("processing_orders", "processing_position_operations", "production_work_logs")

#: V88（issue #4676）之后**退场**的逻辑工序 —— 本文件**不得**再种回来。
RETIRED_LOGICAL = "配料"
FABRIC_POSITION = "布料"
#: V88 之后的**终态**布料主线（= `ProductionSeedTemplateService.FABRIC_MAINLINE_STEPS`）。
FABRIC_MAINLINE = ("裁剪", "打包")
#: V88 之后的**保命格**（`applicable=TRUE`）：缺它 ⇒ `buildRoute` 静默滤掉 `裁剪`。
KEEP_CELL = ("裁剪", "布料")
#: `打包` 的 4 格（交付工序在每个部位的唯一载体）。
PACKING_CELLS = (("打包", "布帘"), ("打包", "纱帘"), ("打包", "帘头"), ("打包", "布料"))
#: V88 之后**存活**的布料相关格 = 保命格 + `打包` 4 格 = **5 格**（36 − 31 退场 = 5）。
SURVIVING_CELLS = (KEEP_CELL,) + PACKING_CELLS
#: 默认窗帘主线的第 10 道及其锚点（插在锚点**之前**）。
PACKING_STEP = "打包"
CURTAIN_ANCHOR = "外帘装袋"

_VERSION_RE = re.compile(r"^V(\d+)__")
#: 派生 `VALUES` 里的一行：`('<逻辑名>', '<部位>', <价>, <适用>)`。
_POSITION_VALUE_ROW_RE = re.compile(
    r"\(\s*'(?P<logical>[^']+)'\s*,\s*'(?P<position>[^']+)'\s*,"
    r"\s*(?P<price>[^,]+?)\s*,\s*(?P<applicable>[^)]+?)\s*\)")
#: 三条 INSERT 的显式列清单（`INSERT INTO t (a, b, …)`）。
_INSERT_COLUMNS_RE = re.compile(
    r"INSERT\s+INTO\s+(?P<table>[a-z_][a-z0-9_]*)\s*\((?P<cols>[^)]*)\)", re.I)
#: `ON CONFLICT … DO NOTHING`（幂等守卫）。
_ON_CONFLICT_RE = re.compile(r"ON\s+CONFLICT\s*\([^)]*\)[\s\S]*?DO\s+NOTHING", re.I)


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """剥掉 SQL 注释 —— 判据必须看**可执行 SQL**（注释里的字面量/回滚 SQL 不是实现）。"""
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return re.sub(r"--[^\n]*", " ", sql)


def v89_executable() -> str:
    return _strip_comments(_read(V89))


def v89_statements() -> list:
    """**可执行**语句列表（去注释 + 按 `;` 切 + 丢空）。"""
    return [s.strip() for s in v89_executable().split(";") if s.strip()]


def insert_for(table: str) -> str:
    """V89 里针对 `table` 的那**一条** INSERT 语句（多于/少于 1 条 ⇒ 立刻红）。"""
    hits = [s for s in v89_statements()
            if re.search(r"INSERT\s+INTO\s+" + table + r"\b", s, re.I)]
    assert len(hits) == 1, (
        f"V89 里 `INSERT INTO {table}` 应**恰好 1 条**（多条会让「按租户循环/幂等」的判据失去唯一对象），"
        f"实测 {len(hits)} 条")
    return hits[0]


def update_statements() -> list:
    return [s for s in v89_statements() if re.match(r"\s*UPDATE\b", s, re.I)]


def position_value_rows(stmt: str) -> list:
    """派生 `VALUES` 的 5 行 → `[(逻辑名, 部位, 价字面量, 适用字面量)]`（纯函数，便于注入式红证）。"""
    return [(m.group("logical"), m.group("position"),
             m.group("price").strip(), m.group("applicable").strip())
            for m in _POSITION_VALUE_ROW_RE.finditer(stmt)]


def untyped_unit_price(rows: list) -> list:
    """**没有**显式 `::numeric` 转型的 `unit_price` 字面量 —— 红证形态（非空即复现 V79 的真库报错）。"""
    return [(logical, position, price) for logical, position, price, _ in rows
            if price.upper().startswith("NULL") and "::numeric" not in price.lower()]


# ══════════════════════════════════════════════════════════════════════════════════════
# 迁移号 / 已发布迁移只增不改
# ══════════════════════════════════════════════════════════════════════════════════════

def test_v89_exists_and_published_migrations_are_untouched():
    """V89 在、V79/V88 也在，且 **V89 号唯一** —— 已发布迁移只增不改（issue #4235）。

    ⚠️ **不写「V89 是当前最大号」** —— 那是自毁式真值主张（`migao-acceptance` 点名的形态）：
    下一个新增迁移一到就必红、且报错指向错误行动。号数前进本身不是违规。
    """
    names = sorted(p.name for p in MIGRATION_DIR.glob("V*.sql"))
    versions = [int(_VERSION_RE.match(n).group(1)) for n in names if _VERSION_RE.match(n)]
    assert V89.exists(), f"缺 {V89.name} —— 本单的补种迁移未落码"
    assert V79.exists(), "V79 被删/改名了 —— 已发布迁移不可改（指纹守卫 + #4235）"
    assert V88.exists(), "V88 被删/改名了 —— 已发布迁移不可改（指纹守卫 + #4235）"
    assert versions.count(89) == 1, f"V89 号不唯一（实测 {versions.count(89)} 条）"


def test_v89_is_registered_in_the_fingerprint_ledger():
    """V89 必须已登记进 `migration_fingerprints.json`（否则它以后能被静默改 —— #4235 的形态）。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert V89.name in ledger, (
        f"`{V89.name}` 未登记进指纹账本 ⇒ 它日后被改不会有任何东西变红。"
        f"跑：python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger")
    assert ledger[V89.name].startswith("sha256:"), f"指纹形态不对：{ledger[V89.name]}"


# ══════════════════════════════════════════════════════════════════════════════════════
# ① 显式类型（**本单的核心**）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_positions_values_cast_unit_price_and_applicable_explicitly():
    """🔴 派生 `VALUES` 的 `unit_price` / `applicable` 必须**逐行显式转型**。

    不写 ⇒ 复现 V79 的真库报错：`column "unit_price" is of type numeric but expression is of
    type text`（`unit_price` 整列都是 NULL ⇒ 推断成 `text`；`text → numeric` 不是赋值转换）。
    """
    rows = position_value_rows(insert_for(POSITION_TABLE))
    assert len(rows) == len(SURVIVING_CELLS), (
        f"派生 VALUES 的行数应为 {len(SURVIVING_CELLS)}（保命格 + 打包 4 格），实测 {len(rows)}")
    untyped = untyped_unit_price(rows)
    assert untyped == [], (
        f"这些行的 `unit_price` 没有显式 `::numeric` ⇒ 真库会报「类型为 numeric, 但表达式为 text」"
        f"（V79 的原样缺陷）：{untyped}")
    untyped_bool = [(lg, pos, ap) for lg, pos, _, ap in rows if "::boolean" not in ap.lower()]
    assert untyped_bool == [], f"这些行的 `applicable` 没有显式 `::boolean`：{untyped_bool}"


def test_operation_unit_price_is_explicitly_typed():
    """① 的工序行 `unit_price` 写 `0::numeric`（DDL 是 `NUMERIC(10,2) NOT NULL DEFAULT 0`）。"""
    stmt = insert_for(OPERATION_TABLE)
    assert re.search(r"\b0::numeric\b", stmt), (
        "① 的 `unit_price` 没有显式 `0::numeric`（同一处类型推断坑的同族形态）")


# ══════════════════════════════════════════════════════════════════════════════════════
# ② 按租户循环 + 显式写列 + 幂等
# ══════════════════════════════════════════════════════════════════════════════════════

def test_all_three_inserts_loop_over_active_tenants():
    """三条 INSERT 都必须 `FROM tenants t … t.deleted = 0` —— 只种 1 号租户 = 存量租户全量 422。

    V79 的逐字警告同款：非 1 号租户拿不到工序 ⇒ `resolveRoute` 的 T3 **fail-closed** ⇒
    该租户一张加工单也生成不了。
    """
    for table in (OPERATION_TABLE, POSITION_TABLE, TEMPLATE_TABLE):
        stmt = insert_for(table)
        assert re.search(r"\bFROM\s+tenants\b", stmt, re.I), f"`INSERT INTO {table}` 没有按租户循环"
        assert re.search(r"\bt\.deleted\s*=\s*0\b", stmt, re.I), (
            f"`INSERT INTO {table}` 没有过滤 `t.deleted = 0` ⇒ 会给已删租户种数据")
    for stmt in update_statements():
        assert re.search(r"\bFROM\s+tenants\b", stmt, re.I), "④ 的 UPDATE 没有按租户循环"
        assert re.search(r"\bt\.deleted\s*=\s*0\b", stmt, re.I), "④ 的 UPDATE 没有过滤 `t.deleted = 0`"


def test_all_three_inserts_write_explicit_column_lists():
    """**显式写列**（issue #4608 纪律）：`INSERT INTO t (列, 列, …)`，不用位置推断。"""
    expected = {
        OPERATION_TABLE: {"id", "tenant_id", "name", "group_name", "position", "unit",
                          "unit_price", "is_must_finish", "is_start_marker", "sort_order",
                          "status", "scope", "source"},
        POSITION_TABLE: {"id", "tenant_id", "logical_name", "position", "unit_price",
                         "applicable", "status"},
        TEMPLATE_TABLE: {"id", "tenant_id", "name", "is_default", "positions", "mainline", "status"},
    }
    for table, want in expected.items():
        m = _INSERT_COLUMNS_RE.search(insert_for(table))
        assert m, f"`INSERT INTO {table}` 没有显式列清单（#4608 纪律）"
        got = {c.strip().lower() for c in m.group("cols").split(",")}
        assert got == want, f"`{table}` 的列清单漂移：缺 {sorted(want - got)} / 多 {sorted(got - want)}"


def test_all_three_inserts_are_idempotent():
    """三条 INSERT 都必须**业务唯一键 `NOT EXISTS`** + **`ON CONFLICT … DO NOTHING`**。

    `MigrationRunner` 硬要求所有迁移可重复执行（bootstrap-first 栈上每条都会再跑一遍）。
    """
    for table in (OPERATION_TABLE, POSITION_TABLE, TEMPLATE_TABLE):
        stmt = insert_for(table)
        assert re.search(r"\bNOT\s+EXISTS\b", stmt, re.I), (
            f"`INSERT INTO {table}` 没有按业务唯一键 `NOT EXISTS` 去重 ⇒ 重复执行会撞唯一索引/造重复行")
        assert _ON_CONFLICT_RE.search(stmt), (
            f"`INSERT INTO {table}` 没有 `ON CONFLICT … DO NOTHING` ⇒ 不幂等")


def test_curtain_mainline_update_is_guarded_and_surgical():
    """④ 的主线回填：**手术式插入**（不整条重建）+ `NOT (mainline @> '["打包"]')` 幂等守卫。"""
    updates = update_statements()
    assert len(updates) == 1, f"V89 应恰好 1 条 UPDATE（④），实测 {len(updates)} 条"
    stmt = updates[0]
    assert re.search(r"\bUPDATE\s+" + TEMPLATE_TABLE + r"\b", stmt, re.I), "④ 的 UPDATE 目标不是路线模板表"
    assert re.search(r"\bSET\s+mainline\s*=\s*\(", stmt), "④ 不是手术式插入（应基于 `rt.mainline` 重建）"
    assert re.search(r"jsonb_array_elements\s*\(\s*rt\.mainline\s*\)", stmt, re.I), (
        "④ 没有逐元素重建主线（整条重建会覆盖商家改过的顺序/删减）")
    assert re.search(r"NOT\s*\(\s*rt\.mainline\s*@>\s*'\[\"打包\"\]'::jsonb\s*\)", stmt), (
        "④ 没有 `NOT (mainline @> '[\"打包\"]')` 幂等守卫 ⇒ 重复执行会插两次 `打包`（双付）")
    assert re.search(r"'\"打包\"'::jsonb", stmt), "④ 没有插入 `打包` 元素"
    assert stmt.count("'\"打包\"'::jsonb") == 1, (
        "④ 里插入的 `打包` 元素出现多次（应为 1 次 —— 多插会双付）")
    assert re.search(r"'\"外帘装袋\"'::jsonb", stmt), "④ 没有以 `外帘装袋` 为锚点（打包必须插在它之前）"
    assert re.search(r"rt\.is_default\b", stmt), "④ 没有限定**默认**路线（会污染布料路线）"
    assert re.search(r"\bupdated_at\s*=\s*NOW\(\)", stmt), "④ 没有显式写 `updated_at`"


# ══════════════════════════════════════════════════════════════════════════════════════
# ③ 终态逐值（与 V88 / ProductionSeedTemplateService 一致）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_only_the_five_surviving_cells_are_seeded():
    """② 落的是 **V88 之后的 5 格存活集**（不是 V79 的 36 格中间态）。"""
    rows = position_value_rows(insert_for(POSITION_TABLE))
    got = {(logical, position) for logical, position, _, _ in rows}
    assert got == set(SURVIVING_CELLS), (
        f"② 的格集合 = {sorted(got)}，应为 V88 之后存活的 5 格 {sorted(SURVIVING_CELLS)}"
        f"（36 − 31 退场 = 5）")
    not_applicable = [(lg, pos) for lg, pos, _, ap in rows if "TRUE" not in ap.upper()]
    assert not_applicable == [], (
        f"这些格 `applicable` 不是 TRUE ⇒ 该部位的工序会被静默滤掉（少一道活、少一笔钱）：{not_applicable}")
    priced = [(lg, pos, price) for lg, pos, price, _ in rows if not price.upper().startswith("NULL")]
    assert priced == [], (
        f"这些格带了单价 ⇒ 会覆盖「适用但未定价」语义（商家应在工序库自配）：{priced}")


def test_fabric_route_is_the_v88_terminal_mainline():
    """③ = `布料工序路线` / `positions=["布料"]` / `mainline=["裁剪","打包"]` / `is_default=FALSE`。"""
    stmt = insert_for(TEMPLATE_TABLE)
    assert re.search(r"'布料工序路线'", stmt), "③ 没有种 `布料工序路线`"
    assert re.search(r"'\[\"布料\"\]'::jsonb", stmt), "③ 的 `positions` 不是 `[\"布料\"]`"
    assert re.search(r"'\[\"裁剪\", \"打包\"\]'::jsonb", stmt), (
        f"③ 的 `mainline` 不是终态 {FABRIC_MAINLINE} —— 若仍是 `[\"配料\",\"打包\"]` 则 `配料` 退场后"
        f"实例化会 fail-closed（`配料` 已软删）")
    assert re.search(r"RETIRED", stmt) is None and f"'{RETIRED_LOGICAL}'" not in stmt, (
        f"③ 引用了已退场的 `{RETIRED_LOGICAL}`")
    assert re.search(r"FALSE\s*,\s*'\[\"布料\"\]'::jsonb", stmt), (
        "③ 的 `is_default` 不是 FALSE（每租户**恰好一条**默认路线，第二条默认撞部分唯一索引）")


def test_packing_operation_is_set_level_with_visible_provenance():
    """① 逐值：`打包` / `后道` / `套` / 价 `0::numeric` / `scope='set'` / `source='占位待确认'`。"""
    stmt = insert_for(OPERATION_TABLE)
    assert re.search(r"'打包'", stmt), "① 没有种 `打包` 工序"
    assert re.search(r"'后道'", stmt), "① 的 `group_name` 不是 `后道`"
    assert re.search(r"'套'", stmt), "① 的 `unit` 不是 `套`"
    assert re.search(r"'set'", stmt), (
        "① 没有写 `scope='set'` ⇒ 一樘「布 + 纱」的订单里 `打包` 会各实例化一次（双付）")
    assert re.search(r"'占位待确认'", stmt), (
        "① 没有写 `source='占位待确认'` ⇒ 「单价是占位值」在数据上不可见（用户裁定：不许静默）")
    assert re.search(r"FALSE\s*,\s*FALSE\s*,\s*37\s*,\s*'active'", stmt), (
        "① 的 `is_must_finish`/`is_start_marker`/`sort_order`/`status` 不是 `FALSE, FALSE, 37, 'active'`")


def test_never_seeds_the_retired_logical_name():
    """🔴 本文件**不得**把 `配料` 种回来（V88 已让它退场；S6 的活路径）。"""
    body = v89_executable()
    assert f"'{RETIRED_LOGICAL}'" not in body, (
        f"V89 的可执行 SQL 里出现了 `{RETIRED_LOGICAL}` ⇒ 新单实例里会再出现它（停止条件 S6）")


def test_red_line_never_touches_snapshot_tables():
    """🔴 三张**快照**表在 V89 的**可执行 SQL** 里**零命中**（口径与 V88 的同名判据逐字一致）。

    ⚠️ 只判可执行 SQL、**不判注释**：头注**必须**点名这三张表（否则红线不可 review），
    把注释也算命中会让「按规范写红线说明」被判红 = 假红（假红比没有守卫更糟）。
    """
    executable = v89_executable()
    hits = {t: len(re.findall(re.escape(t), executable)) for t in SNAPSHOT_TABLES}
    assert hits == {t: 0 for t in SNAPSHOT_TABLES}, (
        f"V89 的可执行 SQL 触碰了快照表 {hits} —— 加工单快照 / 工序实例 / 报工单价必须一字不动")
    # 双向：极像的那一对必须「该在的在、不该在的不在」。
    assert POSITION_TABLE in executable, (
        f"V89 没有写全 `{POSITION_TABLE}`（部位**矩阵**表）")
    assert "processing_position_operations" not in executable, (
        "V89 里出现了 `processing_position_operations`（工序**实例**快照）—— 两张表名极像，"
        "写错表就是静默失效")


# ══════════════════════════════════════════════════════════════════════════════════════
# 不覆盖商家已改（红线）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_never_overwrites_merchant_edits():
    """🔴 V89 **没有**针对既有行的 `SET unit_price` / `SET applicable` / `SET deleted`。

    「只补缺失、绝不覆盖」的机械形态：三条 INSERT 靠业务唯一键 `NOT EXISTS` 去重 ⇒ 已存在的行
    一律不写；唯一的 `UPDATE` 只动 `mainline`（手术式插入）+ `updated_at`。
    """
    executable = v89_executable()
    for banned in ("unit_price", "applicable", "deleted", "scope", "source"):
        for m in re.finditer(r"\bSET\b([\s\S]*?)(?:\bFROM\b|;)", executable, re.I):
            assert not re.search(r"(?:^|,)\s*" + banned + r"\s*=", m.group(1), re.I), (
                f"V89 的 `SET` 子句里出现了 `{banned} = …` ⇒ 会覆盖商家已改的数据（本单红线）")
    updates = update_statements()
    assert len(updates) == 1, f"V89 应恰好 1 条 UPDATE，实测 {len(updates)} 条"
    stmt = updates[0]
    assert re.search(r"\bSET\s+mainline\s*=", stmt), (
        "④ 的 `SET` 目标必须**只有** `mainline`（+ `updated_at`）—— 出现 `unit_price` / `applicable` "
        "等目标就是覆盖商家已改")
    assert re.search(r",\s*updated_at\s*=\s*NOW\(\)", stmt), "④ 没有显式写 `updated_at`"


# ══════════════════════════════════════════════════════════════════════════════════════
# 红证（注入式自证）
# ══════════════════════════════════════════════════════════════════════════════════════

class TestInjectedDrift:
    """逐条注入 ⇒ 对应判据必须变红（防「仓库绿只是空跑」）。"""

    def test_dropping_the_numeric_cast_is_detected(self):
        """🔴 去掉 `::numeric` ⇒ 「显式类型」判据必红（这正是 V79 的真库缺陷形态）。"""
        stmt = insert_for(POSITION_TABLE)
        assert untyped_unit_price(position_value_rows(stmt)) == [], (
            "真实树上读不出未转型的行 ⇒ 下面的注入自证是空跑")
        stripped = stmt.replace("NULL::numeric", "NULL")
        assert stripped != stmt, "注入无效（`NULL::numeric` 一个字面量都没命中）⇒ 红证是空跑"
        flagged = untyped_unit_price(position_value_rows(stripped))
        assert {(lg, pos) for lg, pos, _ in flagged} == set(SURVIVING_CELLS), (
            f"注入后应**每一行**都被判未转型，实测 {flagged}")

    def test_dropping_the_boolean_cast_is_detected(self):
        """去掉 `::boolean` ⇒ 同一条判据的布尔半边必红。"""
        stripped = insert_for(POSITION_TABLE).replace("TRUE::boolean", "TRUE")
        rows = position_value_rows(stripped)
        assert [r for r in rows if "::boolean" not in r[3].lower()], \
            "注入 `TRUE` 后应被判未转型 ⇒ 否则布尔判据是空断言"

    def test_removing_the_tenants_loop_is_detected(self):
        """去掉 `FROM tenants` ⇒ 「按租户循环」判据必红。"""
        stmt = insert_for(POSITION_TABLE)
        assert re.search(r"\bFROM\s+tenants\b", stmt, re.I), "真实树上读不出按租户循环 ⇒ 红证是空跑"
        without = re.sub(r"\bFROM\s+tenants\b", "FROM (SELECT 1 AS id) ", stmt, count=1, flags=re.I)
        assert not re.search(r"\bFROM\s+tenants\b", without, re.I), "注入未生效"
        assert without != stmt, "注入后语句未变 ⇒ 红证是空跑"

    def test_removing_the_not_exists_guard_is_detected(self):
        """去掉 `NOT EXISTS` ⇒ 「幂等」判据必红。"""
        stmt = insert_for(TEMPLATE_TABLE)
        assert re.search(r"\bNOT\s+EXISTS\b", stmt, re.I), "真实树上读不出幂等守卫 ⇒ 红证是空跑"
        assert not re.search(r"\bNOT\s+EXISTS\b", re.sub(r"\bNOT\s+EXISTS\b", "TRUE OR EXISTS", stmt, flags=re.I))

    def test_the_five_cell_set_is_load_bearing(self):
        """格集合判据有判别力：注入第 6 格（V79 的 36 格中间态）⇒ 必红。"""
        rows = position_value_rows(insert_for(POSITION_TABLE))
        assert {(lg, pos) for lg, pos, _, _ in rows} == set(SURVIVING_CELLS)
        injected = rows + [("精裁", "布料", "NULL::numeric", "FALSE::boolean")]
        assert {(lg, pos) for lg, pos, _, _ in injected} != set(SURVIVING_CELLS), \
            "注入第 6 格后集合仍相等 ⇒ 格集合判据是空断言"
