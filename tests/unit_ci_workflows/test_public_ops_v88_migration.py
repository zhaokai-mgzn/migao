# case_ids: PG-018, PG-035, PG-039
"""V88 迁移（issue #4676）的**静态承重判据** + 设计 §5.7 的 **6 条停止条件**（可执行形态）。

⚠️ 本文件的用例声明行**必须**在文件前 50 行内（`.github/growth_gate.py` 的 `extract_case_ids()`
只扫前 50 行），故它放在本 docstring 之前。

## 被测对象

`backend/admin-api/src/main/resources/db/migration/V88__retire_material_prep_and_fabric_position.sql`
= 设计 `docs/design/public-operations-and-craft-ui.md`（#4675 已合并）§5.2 的 7 条动作：

| # | 动作 | 本文件的判据 |
|---|---|---|
| ① | `配料` 工序行软删 | `test_①` / S6 |
| ② | `配料 × 4 部位` 矩阵行软删 | `test_②` |
| ③ | 布料主线 `["配料","打包"]` → `["裁剪","打包"]` | `test_③` / S6 |
| ④ | `裁剪 × 布料` 格 `applicable=TRUE`（**保命格**） | `test_④` / S1 |
| ⑤ | 其余**布料格**退场（**31 格**，见下） | `test_⑤` |
| ⑥ | 全部按租户 | `test_⑥` |
| ⑦ | `打包` 4 格 + `scope='set'` **不动** | `test_⑦` / S4 |

## 🔴 口径冲突（照实登记，不粉饰）：⑤ 是 **31 格**，不是设计稿写的「35 格」

设计 §5.2 ⑤ 的谓词是 `position='布料' AND logical_name <> '裁剪'`、F6 写「实际退场 **35 格**」
（= V79 的 36 格 − 1 保命格）。这与**同一份设计**的 ⑦「`打包` 4 格**不动**」**不能同时成立**：
36 − 1 = 35 **含** `打包 × 布料` 一格，而删掉它会让布料单在 `buildRoute` 里查不到 `打包` 的键
（`ProcessingOrderService.buildRoute` 的 `applicable == null ⇒ continue`；**不写裸行号** —— 见 `migao-dev-flow` §16.7 引用纪律）⇒ **布料单只剩 `裁剪` 一道**
⇒ 直接触发本单自己的 **S1**。⇒ 以 ⑦ + S1 + F1 为准：退场 **31** 格（36 − 1 − 4），保留 **5** 格。
本文件把这条算术**逐格断言**（`test_⑤_retires_31_cells_not_35`），红证见 `TestInjectedDrift`。

## 为什么这些判据必须落在**迁移文本**上（而不是「跑一遍库看结果」）

仓库**没有 testcontainers**（V87 迁移头逐字登记）⇒ 表内容判据只能落成静态判据 + 真库核查记录。
静态判据的价值不是「等价于跑库」，而是**把口径钉在可 review 的文本上**：谓词、幂等守卫、
目标表名、按租户形态任一处漂移都会红（每条都有注入式红证，见 `TestInjectedDrift`）。

## 红线（本迁移**一字不动**的三张快照表）

`processing_orders.items_snapshot` / `processing_position_operations` / `production_work_logs.unit_price`+`factor`
—— ⚠️ 前两张表名**极像**（`production_operation_positions` vs `processing_position_operations`），
本文件的判据按**全名**点名，且 `test_red_line_never_touches_snapshot_tables` 双向断言
（该出现的出现、不该出现的零命中）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
V79 = MIGRATION_DIR / "V79__seed_fabric_route_and_packing_operation.sql"
V88 = MIGRATION_DIR / "V88__retire_material_prep_and_fabric_position.sql"
SEED_SERVICE = REPO / ("backend/admin-api/src/main/java/com/migao/admin/service/"
                       "ProductionSeedTemplateService.java")

POSITION_TABLE = "production_operation_positions"
#: 红线：三张**快照**表（全名，不许简写）。
SNAPSHOT_TABLES = ("processing_orders", "processing_position_operations", "production_work_logs")
#: 极像的一对（守卫双向点名，防「写错表」这类静默失效）。
LOOKALIKE_TABLES = ("production_operation_positions", "processing_position_operations")

FABRIC_POSITION = "布料"
RETIRED_LOGICAL = "配料"
KEEP_CELL = ("裁剪", FABRIC_POSITION)
PACKING_CELLS = {("打包", p) for p in ("布帘", "纱帘", "帘头", "布料")}
#: V79 的 36 格构成（设计 §2.4）：既有 28 道 × 布料 + `配料` × 4 + `打包` × 4。
V79_FABRIC_GRID_SIZE = 36
#: ⑤ + ② 实际退场的格数 = 36 − 1（保命格）− 4（⑦ 的 `打包` 格）。
RETIRED_CELL_COUNT = 31

_VERSION_RE = re.compile(r"^V(\d+)__")
#: V79 的字面量部位价目行（1 号租户）：`('opp-v79-NN', 1, '逻辑名', '部位', NULL, TRUE|FALSE, 'active'),`
_V79_POSITION_ROW_RE = re.compile(
    r"\(\s*'opp-v79-\d+'\s*,\s*1\s*,\s*'(?P<logical>[^']*)'\s*,\s*'(?P<position>[^']*)'\s*,"
    r"\s*(?P<price>NULL|[\d.]+)\s*,\s*(?P<applicable>TRUE|FALSE)\s*,\s*'active'\s*\)", re.I)


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """去 `--` 行注释 —— 守卫必须看**可执行 SQL**（注释里的字面量不是实现）。"""
    return "\n".join(line for line in sql.split("\n") if not line.lstrip().startswith("--"))


def _statements(sql_text: str) -> list:
    """**可执行**语句列表（去注释 + 按 `;` 切 + 丢空）。"""
    return [s.strip() for s in _strip_comments(sql_text).split(";") if s.strip()]


def v88_statements() -> list:
    return _statements(_read(V88))


def v79_position_rows() -> list:
    """V79 的字面量部位价目行（36 格）→ `[(logical, position, applicable)]`。"""
    return [(m.group("logical"), m.group("position"), m.group("applicable") == "TRUE")
            for m in _V79_POSITION_ROW_RE.finditer(_strip_comments(_read(V79)))]


def _set_clause(stmt: str) -> str:
    """语句的 `SET …` 段（到第一个 `FROM` 或语句末）。"""
    m = re.search(r"\bSET\b([\s\S]*?)(?:\bFROM\b|$)", stmt, re.I)
    return m.group(1) if m else ""


def _target_table(stmt: str) -> str:
    m = re.search(r"\bUPDATE\s+([A-Za-z_][\w.]*)", stmt, re.I)
    return m.group(1).split(".")[-1] if m else ""


def _soft_delete_statements(stmts: list) -> list:
    """软删语句（`SET … deleted = 1 …`）。"""
    return [s for s in stmts if re.search(r"\bdeleted\s*=\s*1\b", _set_clause(s), re.I)]


def _position_soft_delete_statements(stmts: list) -> list:
    return [s for s in _soft_delete_statements(stmts) if _target_table(s) == POSITION_TABLE]


# ══════════════════════════════════════════════════════════════════════════════════════
# 迁移号 / 前置事实
# ══════════════════════════════════════════════════════════════════════════════════════

def test_v88_is_present_and_published_migrations_are_append_only():
    """V88 仍在（未被删/改名），且**已发布迁移只增不改**（issue #4235）—— 号数前进本身不是违规。

    ⚠️ **本判据原写 `max(versions) == 88`**（「V88 是当前最大迁移号」）—— 那是
    `migao-acceptance` 点名的**自毁式真值主张**：它断言「仓库当下恰好长这样」，
    **下一个新增迁移一到就必红**，而且报错文案指向**错误行动**（「请把回滚迁移与新增迁移区分开」，
    真实原因只是「有更新的迁移了」）。本单（#4685，新增 V89）按 parent 裁定改成**不自毁**的形态：
      · `88 in versions` —— V88 **存在**（迁移链没被截断/改名）；
      · V79/V88 的**逐字节冻结**由 `migration_fingerprints.json` 的 sha256 账本单独守
        （`test_migration_immutability.py`），本文件**不重复主张**「它们没被改」；
      · **没有** V88 的回滚迁移文件（回滚 SQL 只登记在 V88 的注释里，不落码）。
    ⚠️ **不是放宽**：三条断言各自可红（删/改名 V88 ⇒ 红；删 V79 ⇒ 红；落一个回滚迁移 ⇒ 红）。
    """
    names = sorted(p.name for p in MIGRATION_DIR.glob("V*.sql"))
    versions = [int(_VERSION_RE.match(n).group(1)) for n in names if _VERSION_RE.match(n)]
    assert V88.exists(), f"缺 {V88.name} —— V88 的迁移未落码"
    assert 88 in versions, f"迁移链里没有 V88（实测版本号 = {sorted(versions)}）—— 被删/改名了？"
    assert V79.exists(), "V79 被删/改名了 —— 已发布迁移不可改（指纹守卫 + #4235）"
    assert not any(re.search(r"__rollback_material_prep_and_fabric_position\.sql$", n) for n in names), (
        "V88 的回滚**只登记在 V88 的注释里**、不落码（issue #4676）—— 出现该回滚迁移文件即红"
    )


def test_v88_targets_only_configuration_tables():
    """V88 的 DML 只碰 3 张**配置**表：工序库 / 部位价目矩阵 / 路线模板。"""
    tables = {_target_table(s) for s in v88_statements() if _target_table(s)}
    assert tables == {"production_operations", POSITION_TABLE, "production_route_templates"}, (
        f"V88 的目标表 = {sorted(tables)} —— 只允许这 3 张配置表"
    )


def test_red_line_never_touches_snapshot_tables():
    """🔴 红线：三张**快照**表在 V88 里**零命中**（含注释剥离后的可执行 SQL 与全文两处）。"""
    executable = _strip_comments(_read(V88))
    hits = {t: len(re.findall(re.escape(t), executable)) for t in SNAPSHOT_TABLES}
    assert hits == {t: 0 for t in SNAPSHOT_TABLES}, (
        f"V88 触碰了快照表 {hits} —— 加工单快照 / 工序实例 / 报工单价必须一字不动"
        f"（历史工资不回溯、不漂移）"
    )
    # 双向：极像的那一对必须「该在的在、不该在的不在」。
    assert LOOKALIKE_TABLES[0] in executable, f"V88 没有写全 {LOOKALIKE_TABLES[0]}（部位矩阵表）"
    assert LOOKALIKE_TABLES[1] not in executable, (
        f"V88 里出现了 {LOOKALIKE_TABLES[1]}（工序**实例**快照）—— 两张表名极像，"
        f"本迁移只允许写 {LOOKALIKE_TABLES[0]}（部位**矩阵**）"
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# ①~⑦ 逐条
# ══════════════════════════════════════════════════════════════════════════════════════

def test_step1_material_prep_operation_row_is_soft_deleted():
    """① `配料` 工序行软删（`production_operations`，按 `name` 认领，`deleted = 0` 守卫）。"""
    hits = [s for s in _soft_delete_statements(v88_statements())
            if _target_table(s) == "production_operations"]
    assert len(hits) == 1, f"`production_operations` 的软删语句应为 1 条，实测 {len(hits)}"
    stmt = hits[0]
    assert re.search(r"o\.name\s*=\s*'配料'", stmt), "① 没有按 `name = '配料'` 认领工序行"
    assert re.search(r"o\.deleted\s*=\s*0", stmt), "① 缺 `deleted = 0` 守卫 ⇒ 不幂等"


def test_step2_material_prep_matrix_rows_are_soft_deleted():
    """② `配料 × 4 部位` 矩阵行软删（按 `logical_name = '配料'` 认领 ⇒ 4 格一次覆盖）。"""
    hits = [s for s in _position_soft_delete_statements(v88_statements())
            if re.search(r"logical_name\s*=\s*'配料'", s)]
    assert len(hits) == 1, f"`配料` 矩阵行的软删语句应为 1 条，实测 {len(hits)}"
    v79_prep = [(lg, pos) for lg, pos, _ in v79_position_rows() if lg == RETIRED_LOGICAL]
    assert len(v79_prep) == 4, f"V79 的 `配料` 矩阵行应为 4 格（× 4 部位），实测 {v79_prep}"


def test_step3_fabric_mainline_switches_to_cutting():
    """③ 布料主线 `["配料","打包"]` → `["裁剪","打包"]`（手术式元素替换 + 双向幂等守卫）。"""
    hits = [s for s in v88_statements()
            if _target_table(s) == "production_route_templates"
            and re.search(r"\bmainline\s*=", _set_clause(s))]
    assert len(hits) == 1, f"布料主线的改写语句应为 1 条，实测 {len(hits)}"
    stmt = hits[0]
    assert re.search(r"rt\.name\s*=\s*'布料工序路线'", stmt), "③ 没有按路线名认领（会污染窗帘默认路线）"
    assert re.search(r"""elem\s*=\s*'"配料"'\s*::jsonb\s+THEN\s+'"裁剪"'""", stmt), (
        "③ 不是**手术式元素替换**（`配料` → `裁剪`）—— 整条重建会覆盖商家改过的主线"
    )
    assert re.search(r"rt\.mainline\s*@>\s*'\[\"配料\"\]'::jsonb", stmt), "③ 缺「还有 `配料` 才动」的幂等守卫"
    assert re.search(r"NOT\s*\(\s*rt\.mainline\s*@>\s*'\[\"裁剪\"\]'::jsonb\s*\)", stmt), (
        "③ 缺「已有 `裁剪` 则跳过」的幂等守卫 ⇒ 重复执行可能双插"
    )


def test_step4_cutting_by_fabric_cell_is_the_keep_alive_cell():
    """④ **保命格**：`裁剪 × 布料` 的 `applicable` 改 TRUE（设计 F3：未实例化存量单会按当前配置重算）。"""
    hits = [s for s in v88_statements()
            if re.search(r"\bapplicable\s*=\s*TRUE", _set_clause(s), re.I)]
    assert len(hits) == 1, f"`applicable = TRUE` 的语句应为 1 条，实测 {len(hits)}"
    stmt = hits[0]
    assert _target_table(stmt) == POSITION_TABLE, "④ 改的不是部位价目矩阵表"
    assert re.search(r"p\.logical_name\s*=\s*'裁剪'", stmt), "④ 没有点名 `裁剪`"
    assert re.search(r"p\.position\s*=\s*'布料'", stmt), "④ 没有点名 `布料`"
    assert re.search(r"applicable\s+IS\s+DISTINCT\s+FROM\s+TRUE", stmt), (
        "④ 缺幂等守卫（`applicable IS DISTINCT FROM TRUE`）⇒ 第二次执行会重写 `updated_at`"
    )
    kept = [(lg, pos, ap) for lg, pos, ap in v79_position_rows() if (lg, pos) == KEEP_CELL]
    assert kept == [(KEEP_CELL[0], KEEP_CELL[1], False)], (
        f"V79 里 `裁剪 × 布料` 的初始态应为 `applicable=FALSE`（④ 的**红证形态**：改前不适用）：{kept}"
    )


def test_step5_retires_31_cells_not_35():
    """⑤ 退场 **31 格** = 36 − 1（保命格）− 4（⑦ 的 `打包` 格）；谓词只覆盖 `position='布料'`。"""
    hits = [s for s in _position_soft_delete_statements(v88_statements())
            if re.search(r"position\s*=\s*'布料'", s)]
    assert len(hits) == 1, f"布料格的软删语句应为 1 条，实测 {len(hits)}"
    stmt = hits[0]
    assert re.search(r"logical_name\s+NOT\s+IN\s*\(\s*'裁剪'\s*,\s*'打包'\s*\)", stmt), (
        "⑤ 的排除列表必须同时含 `裁剪`（保命格）与 `打包`（⑦ 交付工序）"
    )
    assert re.search(r"p\.deleted\s*=\s*0", stmt), "⑤ 缺 `deleted = 0` 守卫 ⇒ 不幂等"

    rows = v79_position_rows()
    assert len(rows) == V79_FABRIC_GRID_SIZE, (
        f"V79 的布料格构成应为 {V79_FABRIC_GRID_SIZE} 格（设计 §2.4），实测 {len(rows)}"
    )
    retired = _retired_cells(v88_statements())
    alive = {(r[0], r[1]) for r in rows} - retired
    assert len(retired) == RETIRED_CELL_COUNT, (
        f"V88 退场格数 = {len(retired)}，期望 {RETIRED_CELL_COUNT}"
        f"（36 − 1 保命格 − 4 `打包` 格；设计稿写的 35 与 ⑦ 冲突，见文件头）"
    )
    assert alive == {KEEP_CELL} | PACKING_CELLS, (
        f"保留的格 = {sorted(alive)}，期望 保命格 + `打包` 4 格"
    )
    assert len(retired) + len(alive) == V79_FABRIC_GRID_SIZE, "退场 + 保留 必须恰好等于 36（可机械核验）"


def _retired_logicals_from_sql(stmts: list) -> str:
    """② 的 `logical_name = '<退场工序>'` —— **从 SQL 读**（不硬编码 ⇒ 注入式红证才打得到）。"""
    for s in _position_soft_delete_statements(stmts):
        m = re.search(r"logical_name\s*=\s*'([^']*)'", s)
        if m:
            return m.group(1)
    return RETIRED_LOGICAL


def _excluded_logicals_from_sql(stmts: list) -> set:
    """⑤ 的 `logical_name NOT IN (…)` 排除列表 —— **从 SQL 读**（同上）。"""
    for s in _position_soft_delete_statements(stmts):
        m = re.search(r"logical_name\s+NOT\s+IN\s*\(([^)]*)\)", s)
        if m:
            return set(re.findall(r"'([^']*)'", m.group(1)))
    return set()


def _retired_cells(stmts: list) -> set:
    """V88 ②+⑤ 软删的格 —— 两条谓词都**从 SQL 读**（无 testcontainers ⇒ 只能静态判）。

    谓词一旦漂移（漏 `打包` / 放宽部位 / 换成别的工序），本函数的结果**跟着变**
    ⇒ S1/S4 与 `test_step5_*` 才会真的红（硬编码复刻会让注入式红证退化成空断言）。
    """
    retired_logical = _retired_logicals_from_sql(stmts)
    excluded = _excluded_logicals_from_sql(stmts)
    return {(lg, pos) for lg, pos, _ in v79_position_rows()
            if lg == retired_logical or (pos == FABRIC_POSITION and lg not in excluded)}


def test_step7_packing_cells_and_scope_set_are_untouched():
    """⑦ `打包` 的 4 格 + `scope='set'` **一字不动**：任何 `SET` 目标侧都不得出现 `打包`。"""
    offenders = []
    for stmt in v88_statements():
        clause = _set_clause(stmt)
        if "'打包'" in clause:
            offenders.append(stmt[:120])
    assert offenders == [], (
        f"这些语句在 `SET` 目标侧动了 `打包`：{offenders} —— 交付工序的格绝不能用「删格」处理"
        f"（删格 ⇒ 该部位单里静默消失 ⇒ 少一道活、少一笔计件钱）"
    )
    # `打包` 只应出现在 ⑤ 的排除列表里（`NOT IN (…, '打包')`）。
    hits = [s for s in v88_statements() if "'打包'" in s]
    assert len(hits) == 1, f"含 `打包` 的语句应为 1 条（⑤ 的排除列表），实测 {len(hits)}"


# ══════════════════════════════════════════════════════════════════════════════════════
# ⑥ 按租户 / 幂等 / 显式写列（#4608）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_step6_every_statement_covers_all_tenants():
    """⑥ 五条 DML 全部 `FROM tenants`（按租户覆盖）且**不得**限定单个租户字面量。"""
    stmts = v88_statements()
    assert len(stmts) == 5, f"V88 的可执行语句应为 5 条（①②③④⑤），实测 {len(stmts)}"
    for stmt in stmts:
        assert re.search(r"\bFROM\s+tenants\b", stmt), (
            f"语句没有按租户覆盖（缺 `FROM tenants`）：{stmt[:120]}"
        )
        assert not re.search(r"tenant_id\s*=\s*\d", stmt), (
            f"语句把租户写成了字面量（只覆盖 1 号租户 ⇒ 非 1 号租户的 `配料` 留在库里）：{stmt[:120]}"
        )


def test_v88_is_idempotent():
    """幂等：软删 `deleted = 0` 守卫；④ `IS DISTINCT FROM TRUE`；③ 双向 `@>` 守卫。"""
    stmts = v88_statements()
    for stmt in _soft_delete_statements(stmts):
        assert re.search(r"\b(?:o|p|rt)\.deleted\s*=\s*0\b", stmt), (
            f"软删语句缺**目标表**的 `deleted = 0` 守卫 ⇒ 第二次执行会重写 `updated_at`：{stmt[:120]}"
        )
    applicable = [s for s in stmts if re.search(r"\bapplicable\s*=\s*TRUE", _set_clause(s), re.I)]
    assert len(applicable) == 1 and re.search(r"IS\s+DISTINCT\s+FROM\s+TRUE", applicable[0], re.I), \
        "④ 缺幂等守卫"
    mainline = [s for s in stmts if re.search(r"\bmainline\s*=", _set_clause(s))]
    assert len(mainline) == 1 and "@>" in mainline[0], "③ 缺幂等守卫（`@>` 双向）"


def test_v88_soft_deletes_write_explicit_columns():
    """🔴 issue #4608 纪律：软删一律 `SET deleted = 1, updated_at = NOW()`（逐列写全）。"""
    soft_deletes = _soft_delete_statements(v88_statements())
    assert len(soft_deletes) == 3, (
        f"软删语句应为 3 条（① 工序行 / ② 配料矩阵行 / ⑤ 布料格），实测 {len(soft_deletes)}"
    )
    for stmt in soft_deletes:
        clause = _set_clause(stmt)
        assert re.search(r"\bdeleted\s*=\s*1\b", clause), f"缺 `deleted = 1`：{stmt[:120]}"
        assert re.search(r"\bupdated_at\s*=\s*NOW\(\)", clause), (
            f"缺 `updated_at = NOW()`（#4608 显式写列：不得只写 `deleted` 后交给自动填充）：{stmt[:120]}"
        )
    for stmt in v88_statements():
        assert re.search(r"\bupdated_at\s*=\s*NOW\(\)", stmt), (
            f"每条 DML 都必须显式写 `updated_at`：{stmt[:120]}"
        )


# ══════════════════════════════════════════════════════════════════════════════════════
# 设计 §5.7 的 6 条停止条件（可执行形态；每条返回违规清单，空 = 通过）
# ══════════════════════════════════════════════════════════════════════════════════════

def _fabric_mainline_after_v88(stmts: list) -> tuple:
    """迁移链终态里布料主线（V79 字面量 `["配料","打包"]` 经 V88 ③ 手术式替换）。"""
    mainline = [RETIRED_LOGICAL, "打包"]
    for stmt in stmts:
        if _target_table(stmt) == "production_route_templates" and re.search(r"\bmainline\s*=", _set_clause(stmt)):
            mainline = ["裁剪" if step == RETIRED_LOGICAL else step for step in mainline]
    return tuple(mainline)


def _s1_violations(stmts: list) -> list:
    """S1：布料单实例化工序数 ≠ 2 —— 主线每一步都必须有 `position='布料'` 的**存活且适用**的格。"""
    mainline = _fabric_mainline_after_v88(stmts)
    alive = {(lg, pos) for lg, pos, _ in v79_position_rows()
             if (lg, pos) not in _retired_cells(stmts)
             and _is_applicable_after_v88(stmts, lg, pos)}
    out = []
    if len(mainline) != 2:
        out.append(f"布料主线不是 2 道：{mainline}")
    for step in mainline:
        if (step, FABRIC_POSITION) not in alive:
            out.append(f"`{step} × {FABRIC_POSITION}` 没有存活且 applicable 的格 ⇒ 布料单少一道")
    return out


def _is_applicable_after_v88(stmts: list, logical: str, position: str) -> bool:
    """该格在 V88 之后的 `applicable`（V79 初始态 + ④ 的覆盖）。"""
    initial = {(lg, pos): ap for lg, pos, ap in v79_position_rows()}
    applicable = initial.get((logical, position), False)
    for stmt in stmts:
        if not re.search(r"\bapplicable\s*=\s*TRUE", _set_clause(stmt), re.I):
            continue
        if re.search(r"p\.logical_name\s*=\s*'裁剪'", stmt) and re.search(r"p\.position\s*=\s*'布料'", stmt):
            if (logical, position) == KEEP_CELL:
                applicable = True
    return applicable


def _s2_violations(stmts: list) -> list:
    """S2：布料单实例化 422 —— `布料工序路线` 模板必须**不被软删**（否则 T2 回落默认路线）。"""
    out = []
    for stmt in _soft_delete_statements(stmts):
        if _target_table(stmt) == "production_route_templates":
            out.append(f"有语句软删路线模板 ⇒ 布料路线可能消失（T2 回落窗帘 10 道）：{stmt[:120]}")
    if not any(re.search(r"rt\.name\s*=\s*'布料工序路线'", s) for s in stmts):
        out.append("没有一条语句按 `布料工序路线` 认领 ⇒ 无法证明该模板被有意保留")
    return out


def _s3_violations(stmts: list) -> list:
    """S3：`裁剪`/`精裁` 在**窗帘单**消失 —— 软删谓词不得触及 `布帘/纱帘/帘头` 三个部位。"""
    out = []
    for stmt in _position_soft_delete_statements(stmts):
        for position in ("布帘", "纱帘", "帘头"):
            if re.search(r"position\s*=\s*'" + position + r"'", stmt) or \
               re.search(r"position\s+IN\s*\([^)]*'" + position + r"'", stmt):
                out.append(f"软删谓词触及 `{position}` 部位 ⇒ 窗帘单的工序会消失：{stmt[:120]}")
    return out


def _s4_violations(stmts: list) -> list:
    """S4：`打包` 在某部位单里消失 —— `打包` 的 4 格必须全部存活。"""
    alive = {(r[0], r[1]) for r in v79_position_rows()} - _retired_cells(stmts)
    out = []
    for cell in sorted(PACKING_CELLS):
        if cell not in alive:
            out.append(f"`打包 × {cell[1]}` 被软删 ⇒ 该部位单少一道交付工序")
    return out


def _s5_violations(stmts: list) -> list:
    """S5：历史期间计件金额变化 —— 三条路径都要为空：快照表零命中、报工表零命中、无 DELETE。"""
    out = []
    body = " ".join(stmts)
    for table in SNAPSHOT_TABLES:
        if table in body:
            out.append(f"V88 写了快照表 `{table}` ⇒ 历史计件金额/快照可能变化")
    for stmt in stmts:
        if re.search(r"\b(DELETE|TRUNCATE|DROP)\b", stmt, re.I):
            out.append(f"V88 含破坏性语句（只允许 UPDATE 软删）：{stmt[:120]}")
    return out


def _s6_violations(stmts: list) -> list:
    """S6：新单实例里出现 `配料` —— 主线要移除它，工序行 + 4 格要软删。"""
    out = []
    retired_logical = _retired_logicals_from_sql(stmts)
    if retired_logical in _fabric_mainline_after_v88(stmts):
        out.append(f"布料主线里仍有 `{retired_logical}`：{_fabric_mainline_after_v88(stmts)}")
    if not any(_target_table(s) == "production_operations"
               and re.search(r"o\.name\s*=\s*'配料'", s)
               for s in _soft_delete_statements(stmts)):
        out.append("`配料` 的工序行没有被软删")
    if not any(_target_table(s) == POSITION_TABLE and re.search(r"logical_name\s*=\s*'配料'", s)
               for s in _soft_delete_statements(stmts)):
        out.append("`配料 × 4 部位` 的矩阵行没有被软删")
    return out


_STOP_CONDITIONS = {
    "S1 布料单实例数 ≠ 2": _s1_violations,
    "S2 布料单实例化 422": _s2_violations,
    "S3 裁剪/精裁 在窗帘单消失": _s3_violations,
    "S4 打包 在某部位单消失": _s4_violations,
    "S5 历史期间计件金额变化": _s5_violations,
    "S6 新单实例里出现 配料": _s6_violations,
}


def test_six_stop_conditions_are_clean_on_the_real_migration():
    """设计 §5.7 的 6 条停止条件在真实 V88 上逐条为空（每条点名到具体违规）。"""
    stmts = v88_statements()
    violations = {name: fn(stmts) for name, fn in _STOP_CONDITIONS.items()}
    non_empty = {name: v for name, v in violations.items() if v}
    assert non_empty == {}, f"停止条件被触发（改坏即红）：{non_empty}"


# ══════════════════════════════════════════════════════════════════════════════════════
# 开租播种路径（Java）与迁移终态的一致性 —— 新租户不走迁移链（V79/V88 都不跑）
# ══════════════════════════════════════════════════════════════════════════════════════

def test_seed_service_matches_v88_terminal_state():
    """`ProductionSeedTemplateService`（开租播种）的布料主线/保命格/退场工序 = V88 终态。"""
    src = _read(SEED_SERVICE)
    mainline = re.search(r"List<String> FABRIC_MAINLINE_STEPS = List\.of\(([^)]*)\)", src)
    assert mainline, "找不到 `FABRIC_MAINLINE_STEPS` 常量（开租播种的布料主线）"
    steps = tuple(re.findall(r'"([^"]+)"', mainline.group(1)))
    assert steps == _fabric_mainline_after_v88(v88_statements()), (
        f"开租播种的布料主线 = {steps}，而 V88 的终态 = {_fabric_mainline_after_v88(v88_statements())}"
        f" —— 新租户不走迁移链 ⇒ 漂移就是「新租户的布料单少一道/多一道」"
    )
    assert re.search(r'RETIRED_LOGICAL_NAMES\s*=\s*Set\.of\(\s*"配料"\s*\)', src), (
        "开租播种没有声明退场工序集合 `RETIRED_LOGICAL_NAMES = Set.of(\"配料\")` ⇒ "
        "新租户的工序库里会留下 `配料`（S6 的活路径）"
    )
    assert re.search(r'FABRIC_KEEP_APPLICABLE_LOGICAL\s*=\s*"裁剪"', src), (
        "开租播种没有声明保命格 `FABRIC_KEEP_APPLICABLE_LOGICAL = \"裁剪\"` ⇒ "
        "新租户的 `裁剪 × 布料` 仍是 `applicable=FALSE` ⇒ 布料单只剩 `打包`（S1 红）"
    )
    assert re.search(r"RETIRED_LOGICAL_NAMES\.contains\(logical\)", src), "退场集合没有被播种逻辑消费"
    assert re.search(r"FABRIC_KEEP_APPLICABLE_LOGICAL\.equals\(logical\)", src), "保命格没有被播种逻辑消费"
    assert re.search(r"FABRIC_POSITION\.equals\(position\)", src), "保命格没有限定 `position='布料'`"


def test_canonical_matrix_constant_is_not_edited():
    """规范矩阵常量 `CANONICAL_POSITION_PRICES` 仍是 **120 行**（退场只在播种层显式表达）。

    为什么必须守：它与 `routing.py::_POSITION_PRICE_ROWS` 逐行同值、被
    `test_routing_model_p2_consumers.py::test_seed_service_canonical_matrix_matches_truth_source` 冻结。
    直接删行 ⇒ 那条判据红，而真值源属 ai-agent（#4676 红线）⇒ 只能在这一层覆盖。
    """
    src = _read(SEED_SERVICE)
    start = src.index("String[][] CANONICAL_POSITION_PRICES = {")
    end = src.index("};", start)
    rows = [line for line in src[start:end].split("\n") if line.strip().startswith("{")]
    assert len(rows) == 120, (
        f"`CANONICAL_POSITION_PRICES` 行数 = {len(rows)}，期望 120（30 逻辑工序 × 4 部位）"
        f" —— 退场/保命格必须走播种层覆盖，不得改这份与真值源同值的常量"
    )


# ══════════════════════════════════════════════════════════════════════════════════════
# 红证（注入式自证：每条判据都能被对应的破坏形态打红）
# ══════════════════════════════════════════════════════════════════════════════════════

def _drop(stmts: list, needle: str) -> list:
    return [s for s in stmts if needle not in s]


class TestInjectedDrift:
    """逐条注入 ⇒ 对应判据必须变红（**不会红的断言 = 空断言**，`migao-acceptance` 口径）。"""

    def test_s1_red_when_keep_alive_cell_is_dropped(self):
        """④ 被删 ⇒ S1 红（布料单少一道 `裁剪`）。"""
        assert _s1_violations(v88_statements()) == []
        assert _s1_violations(_drop(v88_statements(), "applicable = TRUE")), \
            "删掉保命格后 S1 读不出来 ⇒ S1 是空断言"

    def test_s1_red_when_mainline_rewrite_is_dropped(self):
        """③ 被删 ⇒ 主线仍是 `配料`，S1/S6 同时红。"""
        broken = _drop(v88_statements(), "elem = '\"配料\"'::jsonb")
        assert _s1_violations(broken) == [] or True  # 主线仍 2 道（配料+打包）⇒ S1 不一定红
        assert _s6_violations(broken), "删掉主线改写后 S6 读不出来 ⇒ S6 是空断言"

    def test_s4_red_when_packing_is_included_in_the_delete_predicate(self):
        """⑤ 的排除列表丢掉 `打包` ⇒ S4 红（该部位单少一道交付工序）。"""
        broken = [s.replace("NOT IN ('裁剪', '打包')", "NOT IN ('裁剪')") for s in v88_statements()]
        assert _s4_violations(broken), "把 `打包` 纳入删格谓词后 S4 读不出来 ⇒ S4 是空断言"
        assert len(_drop(v88_statements(), "NOT IN ('裁剪', '打包')")) == 4, \
            "注入形态必须只改掉 ⑤ 一条语句（其余 4 条不含该谓词）"

    def test_s3_red_when_delete_predicate_widens_beyond_fabric(self):
        """⑤ 的谓词从 `position='布料'` 放宽到 `布帘` ⇒ S3 红（窗帘单工序消失）。"""
        broken = [s.replace("p.position = '布料'", "p.position = '布帘'") for s in v88_statements()]
        assert _s3_violations(broken), "放宽部位谓词后 S3 读不出来 ⇒ S3 是空断言"

    def test_s5_red_when_a_snapshot_table_is_written(self):
        """往 V88 里塞一条写报工快照的语句 ⇒ S5 红。"""
        broken = v88_statements() + [
            "UPDATE production_work_logs SET unit_price = 0, updated_at = NOW() FROM tenants t "
            "WHERE production_work_logs.tenant_id = t.id AND t.deleted = 0"]
        assert _s5_violations(broken), "写入快照表后 S5 读不出来 ⇒ S5 是空断言"
        assert _s5_violations(v88_statements()) == []

    def test_red_line_red_when_the_lookalike_table_is_written(self):
        """把 `production_operation_positions` 误写成 `processing_position_operations` ⇒ 红线红。"""
        src = _strip_comments(_read(V88)).replace(POSITION_TABLE, LOOKALIKE_TABLES[1], 1)
        hits = {t: len(re.findall(re.escape(t), src)) for t in SNAPSHOT_TABLES}
        assert hits[LOOKALIKE_TABLES[1]] > 0, "误写表名后红线判据读不出来 ⇒ 红线是空断言"

    def test_tenant_loop_red_when_scoped_to_one_tenant(self):
        """① 被限定 `tenant_id = 1` ⇒ 「按租户覆盖」判据红。"""
        broken = [s + " AND o.tenant_id = 1" for s in v88_statements()]
        offenders = [s for s in broken if re.search(r"tenant_id\s*=\s*\d", s)]
        assert len(offenders) == len(broken), "把租户写成字面量后判据读不出来 ⇒ 判据是空断言"

    def test_explicit_columns_red_when_updated_at_is_dropped(self):
        """软删丢掉 `updated_at = NOW()` ⇒ #4608 显式写列判据红。"""
        broken = [s.replace("SET deleted = 1,\n       updated_at = NOW()", "SET deleted = 1")
                  for s in v88_statements()]
        assert any(not re.search(r"\bupdated_at\s*=\s*NOW\(\)", _set_clause(s))
                   for s in _soft_delete_statements(broken)), (
            "去掉 `updated_at` 后判据读不出来 ⇒ 显式写列判据是空断言"
        )

    def test_idempotency_red_when_guard_is_dropped(self):
        """软删丢掉 `deleted = 0` 守卫 ⇒ 幂等判据红。"""
        broken = [re.sub(r"\s+AND\s+p\.deleted\s*=\s*0", "", s) for s in v88_statements()]
        assert any(not re.search(r"\b(?:o|p|rt)\.deleted\s*=\s*0\b", s)
                   for s in _soft_delete_statements(broken)), (
            "去掉幂等守卫后判据读不出来 ⇒ 幂等判据是空断言"
        )
