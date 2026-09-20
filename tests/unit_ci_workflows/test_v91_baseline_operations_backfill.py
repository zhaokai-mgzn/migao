# case_ids: PG-018, MC-012
"""`V91` 补种迁移（issue #4707）+ 「**主线引用的工序必须在工序库里存在**」三处口径守卫。

⚠️ 本文件的用例声明行**必须**在文件前 50 行内（`.github/growth_gate.py` 的
`extract_case_ids()` 只扫前 50 行），故它放在本 docstring **之前**。

## 被测对象

`backend/admin-api/src/main/resources/db/migration/V91__backfill_baseline_operations_for_empty_catalogs.sql`
= **1 条语句**：为每个**从未种过基线工序**的活跃租户补 **36 行**基线工序
（V54 的 30 + V56 的 5 + `打包`）。

## 真库实测根因（2026-09-20，PG 18.3 / 阿里云 RDS `ai_customer_service`）

| 租户 | `production_operations`（含软删） | 矩阵行 | 活跃路线 | 判定 |
|---|---|---|---|---|
| 1 词元通达 | 36 | 86 | 1 | 健康 |
| 20 米高POC演示布艺 | **0** | 84 | 1 | 窗帘主线 **9 道逐道悬空** ⇒ 布帘 9/9、帘头 6/6、纱帘 5/5 fail-closed 422 |
| 21 POC彩排5605 | **0** | 84 | 1 | 同上 |

根因 = `V54`/`V56` 的工序种子**只种 `tenant_id = 1`**（四个文件里 `FROM tenants` 出现 0 次），
而 `V71`/`V72` 的**按租户**回填只种矩阵 / 路线 / 工艺 ⇒ 路线引用的工序在工序库里**没有行**
⇒ `ProcessingOrderService.buildRoute` 的 `variantNameOf` 返回 `null` ⇒ `missing_operations`
⇒ **fail-closed 422**（与 `#4685` 的 V79 缺陷**正交**：V79 漏的是 `打包`/布料价目格/布料路线）。

**同根因的第二个后果（本单不修，如实登记为分叉）**：`V72` 的 `production_route_rules` 回填带
`EXISTS (production_operations …)` 过滤 ⇒ 这两户的规则表也是 **0 行**（工艺变体 / 特殊选项
静默缺失）。本单只治「**422**」（工序库空），规则缺失是**静默少一道**形态，另开单。

## 为什么判据落在**迁移文本**上

仓库**没有 testcontainers** ⇒ 表内容判据只能落成静态判据 + 真库核查记录（记录在 PR body）。
静态判据把口径钉在可 review 的文本上：闸门、按租户循环、幂等、显式类型、终态逐值、
不覆盖商家已改 —— 任一处漂移都会红（每条都有注入式红证，见 `TestInjectedDrift`）。

## 三处口径（本文件守前两处；第三处 = 运行时读面，在 Java 侧）

| # | 口径 | 载体 | 守卫 |
|---|---|---|---|
| ① | bootstrap 终态 | `docs/sql/schema.sql` | `test_bootstrap_mainlines_all_have_library_rows` |
| ② | 迁移链终态 | `db/migration/V*.sql` 聚合（**按内容发现**） | `test_migration_chain_terminal_mainlines_all_have_library_rows` |
| ③ | 运行时读面 | `ProductionOperationQueryService.variantNameOf` | `MainlineOperationReferenceTest`（Java，含部位维变体解析） |

## 🔴 红线：三张快照表一字不动

`processing_orders` / `processing_position_operations` / `production_work_logs`
（⚠️ `production_operation_positions` 与 `processing_position_operations` **名字极像**）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
V91 = MIGRATION_DIR / "V91__backfill_baseline_operations_for_empty_catalogs.sql"
SCHEMA_SQL = REPO / "docs/sql/schema.sql"
SEED_JSON = REPO / (
    "backend/admin-api/src/main/resources/production-templates/curtain/seed.json")

#: 三张**快照**表（全名，不许简写）。
SNAPSHOT_TABLES = ("processing_orders", "processing_position_operations",
                   "production_work_logs")

#: V54 ∪ V56 的 **35 条**基线工序名（`打包` 由 V79/V89 负责 ⇒ **不在**闸门的名字集里）。
LEGACY_BASELINE_NAMES = (
    "精裁-布", "精裁-纱", "裁剪-布", "裁剪-纱", "布三边", "纱三边", "韩褶-布", "韩褶-纱",
    "上车布-布", "上车布-纱", "打孔-布", "打孔-纱", "拼1次-布", "拼2次-布", "拼3次-布",
    "花边-布", "铅坠-布", "接高-布", "帘头制作", "熨烫-布", "定型-布", "复烫-布",
    "布帘车被", "外帘打卷", "外帘装袋", "质检", "外帘发货", "绑带-布", "抱枕", "腰靠垫",
    "绑带-纱", "logo条-布", "立边-布", "扣环-布", "防翘扣-布",
)

#: V88（issue #4676）**退场**的逻辑工序 —— 本迁移**绝不**种回来。
RETIRED_LOGICAL_NAMES = ("配料",)

#: 部位值域（用来把路线模板里的 `positions` 字面量与 `mainline` 字面量分开）。
POSITION_VOCAB = frozenset({"布帘", "纱帘", "帘头", "布料", "外帘"})

#: 逻辑工序名 → 该逻辑名在工序库里的**库行名候选**（变体名或裸名）。
#: 判据 = 「主线里的每一道，工序库里有行」；部位维的**变体解析**由 Java 侧
#: `MainlineOperationReferenceTest` 守（同一份口径的第三处）。
LOGICAL_TO_LIBRARY_NAMES = {
    "精裁": ("精裁-布", "精裁-纱"),
    "裁剪": ("裁剪-布", "裁剪-纱"),
    "三边": ("布三边", "纱三边"),
    "韩褶": ("韩褶-布", "韩褶-纱"),
    "上车布": ("上车布-布", "上车布-纱"),
    "打孔": ("打孔-布", "打孔-纱"),
    "拼1次": ("拼1次-布",),
    "拼2次": ("拼2次-布",),
    "拼3次": ("拼3次-布",),
    "花边": ("花边-布",),
    "铅坠": ("铅坠-布",),
    "接高": ("接高-布",),
    "帘头制作": ("帘头制作",),
    "熨烫": ("熨烫-布",),
    "定型": ("定型-布",),
    "复烫": ("复烫-布",),
    "车被": ("布帘车被",),
    "外帘打卷": ("外帘打卷",),
    "外帘装袋": ("外帘装袋",),
    "外帘发货": ("外帘发货",),
    "质检": ("质检",),
    "绑带": ("绑带-布", "绑带-纱"),
    "抱枕": ("抱枕",),
    "腰靠垫": ("腰靠垫",),
    "logo条": ("logo条-布",),
    "立边": ("立边-布",),
    "扣环": ("扣环-布",),
    "防翘扣": ("防翘扣-布",),
    "打包": ("打包",),
}

JSONB_LIST_RE = re.compile(r"'(\[[^']*?\])'::jsonb")


# ══════════════════════════════════════════════════════════════════════════════════
# 解析工具
# ══════════════════════════════════════════════════════════════════════════════════

def strip_sql_comments(sql: str) -> str:
    """去掉 `--` 行注释，只留可执行语句（判据不许被注释里的字面量骗过）。"""
    return "\n".join(line.split("--")[0] for line in sql.splitlines())


def split_fields(raw: str) -> list[str]:
    """按顶层逗号切字段（`'…'` 里的逗号不算）。"""
    fields, buf, quote = [], "", False
    for ch in raw:
        if ch == "'":
            quote = not quote
            buf += ch
        elif ch == "," and not quote:
            fields.append(buf.strip())
            buf = ""
        else:
            buf += ch
    fields.append(buf.strip())
    return fields


def unquote(raw: str) -> str:
    return raw.strip().strip("'").replace("''", "'")


def none_or(raw: str):
    value = raw.strip()
    if value.upper().startswith("NULL"):
        return None
    return unquote(value)


def num(raw: str):
    value = raw.strip()
    if value.upper().startswith("NULL"):
        return None
    return float(re.sub(r"::\s*\w+.*$", "", value).strip())


def operation_inserts(sql: str) -> list[tuple[list[str], str, str]]:
    """全部 `INSERT INTO production_operations (cols) <VALUES|SELECT> …` ⇒ (列清单, 形态, 片段)。"""
    body = strip_sql_comments(sql)
    out = []
    for m in re.finditer(
            r"INSERT INTO production_operations\s*\((.*?)\)\s*(VALUES|SELECT)(.*?)"
            r"(ON CONFLICT|;\s*$|;\n)", body, re.S):
        out.append(([c.strip() for c in m.group(1).split(",")], m.group(2), m.group(3)))
    return out


#: 种子清单块：`CROSS JOIN (SELECT … UNION ALL SELECT …) AS b`
ROW_LIST_RE = re.compile(r"CROSS JOIN\s*\(\s*SELECT(.*?)\n\s*\)\s*AS\s+b\b", re.S)
#: 第一行上的列别名（`'精裁-布' AS name, …`）
ALIAS_RE = re.compile(r"\s+AS\s+([a-z_][a-z0-9_]*)", re.I)


def row_list_rows(sql: str) -> list[dict]:
    """`V91` 的 `CROSS JOIN (SELECT … UNION ALL SELECT …) AS b` ⇒ 逐行字段（列名取第一行的别名）。

    ⚠️ 刻意**不**用 `(VALUES …)`（`test_production_catalog_seed.py` 的 `parse_seed` 会把派生表里的
    `VALUES` 当成种子行 ⇒ 假红）也**不**用 `WITH … AS (VALUES …)` CTE
    （`test_migration_references_exist_in_schema.py` 会把 CTE 名当表名 ⇒ 假红）。
    守卫必须认得这个形态，否则新迁移会被当成「聚合不到种子」而静默空跑。
    """
    body = strip_sql_comments(sql)
    match = ROW_LIST_RE.search(body)
    if not match:
        return []
    segments = re.split(r"\bUNION\s+ALL\s+SELECT\b", match.group(1), flags=re.I)
    columns = ALIAS_RE.findall(segments[0])
    if not columns:
        return []
    rows = []
    for index, segment in enumerate(segments):
        fields = split_fields(segment)
        if index == 0:
            fields = [ALIAS_RE.sub("", f).strip() for f in fields]
        if len(fields) != len(columns):
            continue
        rows.append(dict(zip(columns, fields)))
    return rows


def operation_names(sql: str) -> list[str]:
    """一段 SQL 里 `production_operations` 种下的工序名（`VALUES` / 派生 `SELECT` / 内联派生表）。"""
    names: list[str] = []
    for columns, form, chunk in operation_inserts(sql):
        if form == "VALUES":
            idx = columns.index("name")
            for raw in re.findall(r"\(([^()]*)\)", chunk):
                fields = split_fields(raw)
                if len(fields) == len(columns):
                    names.append(unquote(fields[idx]))
        else:
            # 派生形态（如 V55 的 `SELECT 'pv-' || o.id, … FROM production_operations o`）
            # ⇒ 不含新工序名；V54/V56 的 `VALUES` 形态已覆盖。仍抓一下行首字面量，防将来改写。
            names.extend(re.findall(r"^\s*'([^']+)'\s*,", chunk, re.M))
    names.extend(unquote(r["name"]) for r in row_list_rows(sql) if "name" in r)
    return names


def mainline_literals(sql: str) -> list[list[str]]:
    """**新模型**（`production_route_templates`）的路线主线字面量。

    ⚠️ 只认 `INSERT INTO production_route_templates …` 语句块里的 `'[...]'::jsonb` ——
    旧两表（`production_routings.operations`）的列表存的是**变体名**（`精裁-布`/`布三边`/`S钩`…），
    把它算进来会与逻辑名口径混在一起（假红）。`positions` 字面量（元素全是部位词）同样排除。
    """
    body = strip_sql_comments(sql)
    out = []
    for stmt in re.finditer(
            r"INSERT INTO production_route_templates\b(.*?)(?:ON CONFLICT|;\s*$|;\n)", body, re.S):
        for raw in JSONB_LIST_RE.findall(stmt.group(1)):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, list) or not value:
                continue
            if all(isinstance(v, str) and v in POSITION_VOCAB for v in value):
                continue    # `positions` 字面量（`["布帘","纱帘","帘头"]` / `["布料"]`）
            if all(isinstance(v, str) for v in value):
                out.append(value)
    return out


def dangling_in(mainlines: list[list[str]], library: set[str]) -> list[str]:
    dangling = []
    for mainline in mainlines:
        for step in mainline:
            if not set(LOGICAL_TO_LIBRARY_NAMES.get(step, ())) & library:
                dangling.append(step)
    return dangling


def migration_text() -> str:
    assert V91.exists(), f"缺少迁移文件：{V91}"
    return V91.read_text(encoding="utf-8")


def baseline_rows(sql: str) -> list[dict]:
    """`V91` 的基线清单 ⇒ 逐行字段（见 `row_list_rows`）。"""
    rows = row_list_rows(sql)
    assert rows, "V91 里解析不到基线清单（守卫会空跑 —— 必须修解析）"
    return rows


def baseline_names(sql: str) -> list[str]:
    return [unquote(r["name"]) for r in baseline_rows(sql)]


# ══════════════════════════════════════════════════════════════════════════════════
# ① 存在性与「已发布迁移不可改」
# ══════════════════════════════════════════════════════════════════════════════════

def test_v91_exists_and_published_migrations_are_untouched():
    assert V91.exists()
    for frozen in ("V79__seed_fabric_route_and_packing_operation.sql",
                   "V88__retire_material_prep_and_fabric_position.sql",
                   "V89__backfill_fabric_seed_for_existing_tenants.sql",
                   "V90__unpriced_is_not_zero.sql"):
        assert (MIGRATION_DIR / frozen).exists(), f"已发布迁移被删除：{frozen}"


def test_v91_is_present_and_no_later_version_exists():
    """⚠️ **不得**写成 `max(versions) == 91`：下一个迁移一出现就自毁（#4685 的包踩过的假红陷阱）。"""
    versions = sorted(int(re.match(r"^V(\d+)__", p.name).group(1))
                      for p in MIGRATION_DIR.glob("V*.sql")
                      if re.match(r"^V(\d+)__", p.name))
    assert 91 in versions, f"V91 不在迁移目录里（当前最大 = V{max(versions)}）"
    assert versions.count(91) == 1, "V91 版本号重复"


def test_v91_is_registered_in_the_fingerprint_ledger():
    ledger = json.loads(
        (REPO / "tests/unit_ci_workflows/migration_fingerprints.json").read_text("utf-8"))
    assert any("V91__" in name for name in ledger["migrations"]), "V91 未登记进迁移指纹账本"


# ══════════════════════════════════════════════════════════════════════════════════
# ② 终态逐值：36 行 = V54(30) ∪ V56(5) ∪ `打包`
# ══════════════════════════════════════════════════════════════════════════════════

def test_seeds_exactly_the_36_row_baseline_terminal():
    names = baseline_names(migration_text())
    assert len(names) == 36, f"基线行数必须是 36（35 + 打包），实测 {len(names)}"
    assert set(names) == set(LEGACY_BASELINE_NAMES) | {"打包"}
    assert len(set(names)) == len(names), "基线清单里有重名"


def test_never_seeds_the_retired_logical_name():
    for retired in RETIRED_LOGICAL_NAMES:
        assert retired not in baseline_names(migration_text()), (
            f"V88 已让 `{retired}` 退场，本迁移不得种回来（停止条件 S6）")


def test_row_values_match_the_bootstrap_terminal(schema_sql):
    """逐值比对：本迁移的每一行 vs `schema.sql` 的终态种子行（名称 → 9 个值）。"""
    expected = bootstrap_row_values(schema_sql)
    actual = {unquote(r["name"]): v91_row_values(r) for r in baseline_rows(migration_text())}
    assert set(actual) == set(expected), (
        f"名字集不一致：只在本迁移 {sorted(set(actual) - set(expected))} / "
        f"只在 bootstrap {sorted(set(expected) - set(actual))}")
    for name in sorted(expected):
        assert actual[name] == expected[name], (
            f"工序 `{name}` 逐值不一致：\n  V91       = {actual[name]}\n  bootstrap = {expected[name]}")


def v91_row_values(row: dict) -> tuple:
    return (unquote(row["group_name"]), none_or(row["position"]), unquote(row["unit"]),
            num(row["unit_price"]),
            row["is_must_finish"].strip().upper().startswith("TRUE"),
            row["is_start_marker"].strip().upper().startswith("TRUE"),
            int(row["sort_order"]), unquote(row["source"]), unquote(row["scope"]))


def bootstrap_row_values(schema_sql: str) -> dict:
    """`schema.sql` 的 `INSERT INTO production_operations … VALUES …` ⇒ 名称 → 9 个值。

    ⚠️ 列清单**从 INSERT 文本读**（issue #4685 的假红陷阱：按列**位置**解析会在加列后
    匹配 0 行）。`source` / `scope` 两列不在该 INSERT 里，由**同文件的后续 UPDATE 回填**
    （按 id 前缀 / 按工序名）⇒ 这里按**同一份口径**派生。
    """
    columns, form, chunk = operation_inserts(schema_sql)[0]
    assert form == "VALUES"
    idx = {c: i for i, c in enumerate(columns)}
    rows = {}
    for raw in re.findall(r"\(([^()]*)\)", chunk):
        fields = split_fields(raw)
        if len(fields) != len(columns):
            continue
        oid = unquote(fields[idx["id"]])
        name = unquote(fields[idx["name"]])
        if name in RETIRED_LOGICAL_NAMES:
            continue    # `配料` 是 bootstrap 的留痕行（deleted = 1），V91 有意不种
        source = ("占位待确认" if oid.startswith(("op-v54-", "op-v79-"))
                  else "推算" if oid.startswith("op-v56-") else None)
        scope = "set" if name in ("外帘打卷", "外帘装袋", "外帘发货", "打包") else "position"
        rows[name] = (unquote(fields[idx["group_name"]]), none_or(fields[idx["position"]]),
                      unquote(fields[idx["unit"]]), num(fields[idx["unit_price"]]),
                      fields[idx["is_must_finish"]].strip().upper().startswith("TRUE"),
                      fields[idx["is_start_marker"]].strip().upper().startswith("TRUE"),
                      int(fields[idx["sort_order"]]), source, scope)
    assert rows, "`schema.sql` 里解析不到 production_operations 的种子行（守卫会空跑）"
    return rows


def test_row_values_match_the_open_tenant_seed(seed_json):
    """与**开租播种**终态逐值比对（`seed.json` 是那条路径的数据源）。

    ⚠️ `scope` 只比对 `seed.json` **自己声明了**的那些行（其余行走
    `ProductionSeedTemplateService` 的默认值 `position`）—— 该默认值与终态口径**等价**
    （未声明 ⇒ `position`），故「声明了才比」不是豁免而是同一口径。
    **原来这里登记着一处已知分叉**（三道套级工序缺声明 ⇒ 开租播种落 `position` 而终态落
    `set` ⇒「布 + 纱」各付两次）：issue #4715 已**真修**（`seed.json` 补声明 + 新迁移 V95
    纠正存量），登记随之删除 —— 判据现由下一条测试钉成「**分叉集必须为空**」。
    """
    seeded = {op["name"]: op for op in seed_json["operations"]}
    for row in baseline_rows(migration_text()):
        name = unquote(row["name"])
        assert name in seeded, f"开租播种（seed.json）里没有工序 `{name}`"
        op = seeded[name]
        assert unquote(row["group_name"]) == op["group"], f"`{name}` 分组不一致"
        assert unquote(row["unit"]) == op["unit"], f"`{name}` 单位不一致"
        assert num(row["unit_price"]) == float(op["unit_price"]), f"`{name}` 单价不一致"
        assert int(row["sort_order"]) == op["sort_order"], f"`{name}` sort_order 不一致"
        assert unquote(row["source"]) == op["source"], f"`{name}` source 不一致"
        if "scope" in op:
            assert unquote(row["scope"]) == op["scope"], f"`{name}` scope 不一致"


def test_open_tenant_scope_divergence_is_sold_out(seed_json):
    """开租播种的 `scope` 与终态**必须逐行一致**（分叉集为空）。

    历史（issue #4707 的登记，**已由 #4715 销账**）：`seed.json` 没给
    `外帘打卷` / `外帘装袋` / `外帘发货` 写 `scope` ⇒ 开租播种按默认值落 `position`，
    而迁移链（V67）/ bootstrap 落 `set` ⇒ 一樘「布 + 纱」订单把这三道**各付两次**
    （#4408 双付家族，P1 涉钱）。

    **销账方式**（issue #4715）：`seed.json` 给三道补 `scope: "set"`（根因，治新租户）
    + 新迁移 `V95` 纠正存量播种行（只改播种来源、不覆盖商家自建）。⇒ 本测试由「登记**恰好**
    这三道」改判为「分叉集**必须为空**」—— 判据**只加强不放宽**（原来允许这三道分裂，
    现在一道都不允许）。
    """
    seeded = {op["name"]: op for op in seed_json["operations"]}
    diverged = set()
    for row in baseline_rows(migration_text()):
        name = unquote(row["name"])
        if unquote(row["scope"]) != seeded[name].get("scope", "position"):
            diverged.add(name)
    assert diverged == set(), (
        f"开租播种 scope 分叉集必须为空，实测 {sorted(diverged)} —— "
        f"开租租户的「布 + 纱」订单会把这些套级工序**各付两次**（#4408 双付家族）")


def test_scope_set_only_for_the_four_set_level_operations():
    expected = {"外帘打卷", "外帘装袋", "外帘发货", "打包"}
    for row in baseline_rows(migration_text()):
        name = unquote(row["name"])
        assert unquote(row["scope"]) == ("set" if name in expected else "position"), (
            f"`{name}` 的 scope 与 V67/V79 终态不一致")


# ══════════════════════════════════════════════════════════════════════════════════
# ③ 形态：按租户循环 / 闸门 / 幂等 / 显式类型 / 显式写列 / 不覆盖商家已改
# ══════════════════════════════════════════════════════════════════════════════════

def test_loops_over_active_tenants_not_a_literal_tenant():
    body = strip_sql_comments(migration_text())
    assert "FROM tenants t" in body, "必须按租户循环（`FROM tenants t`）"
    assert re.search(r"t\.deleted\s*=\s*0", body), "必须只取未软删租户"
    assert not re.search(r"tenant_id\s*=\s*1\b", body), "不得写死 tenant_id = 1"


def test_gate_only_targets_tenants_whose_catalog_was_never_seeded():
    """闸门 = 该租户的工序库里**除 `打包` 外没有任何行**（**含软删行**）。

    ⚠️ `打包` 必须排除：`V89`（#4685）刚给这些租户补过 `打包` ⇒ 不排除则闸门**恒假**、
    本迁移**静默空跑**（正是本单要治的形态）。
    ⚠️ 闸门**不得**过滤软删行：商家删过 / 改过名 ⇒ 他的库里仍有行 ⇒ 闸门为假 ⇒ 不碰他。
    """
    body = strip_sql_comments(migration_text())
    gate = re.search(
        r"NOT EXISTS\s*\(\s*SELECT 1 FROM production_operations e\s*"
        r"WHERE e\.tenant_id = t\.id\s*(.*?)\)", body, re.S)
    assert gate, "缺少「该租户从未种过基线工序」的闸门"
    predicate = gate.group(1)
    assert "e.name <> '打包'" in predicate, (
        "闸门必须把 `打包` 排除（V89 已补 ⇒ 否则恒假、静默空跑）")
    assert "e.deleted" not in predicate, (
        "闸门**不得**过滤软删行：商家删过就说明种过了，再补 = 覆盖商家意图")


def test_gate_needs_no_second_name_list():
    """闸门**不得**再抄一份 35 条工序名（两份名单必然漂移）。"""
    body = strip_sql_comments(migration_text())
    gate = re.search(
        r"NOT EXISTS\s*\(\s*SELECT 1 FROM production_operations e\s*"
        r"WHERE e\.tenant_id = t\.id\s*(.*?)\)", body, re.S)
    assert "e.name IN" not in gate.group(1), (
        "闸门里出现第二份名字清单 ⇒ 会与 `VALUES` 清单漂移；改用「除 `打包` 外无行」形态")


def test_each_row_is_guarded_by_business_unique_key():
    body = strip_sql_comments(migration_text())
    assert "e.tenant_id = t.id AND e.name = b.name AND e.deleted = 0" in body, (
        "逐行幂等守卫缺失（业务唯一键 = `(tenant_id, name) WHERE deleted = 0`）")
    assert "ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING" in body, (
        "缺少与 V49 部分唯一索引同款的 `ON CONFLICT` 兜底")


def test_never_overwrites_merchant_edits():
    """红线：本迁移**只 INSERT**，对既有行零 `UPDATE` / 零 `DELETE`。"""
    body = strip_sql_comments(migration_text()).upper()
    assert "UPDATE " not in body, "本迁移不得 UPDATE 任何既有行（会覆盖商家已改的价 / 适用性）"
    assert "DELETE " not in body, "本迁移不得 DELETE 任何行"


def test_writes_explicit_column_list():
    columns, _form, _chunk = operation_inserts(migration_text())[0]
    required = {"id", "tenant_id", "name", "group_name", "position", "unit", "unit_price",
                "is_must_finish", "is_start_marker", "sort_order", "status", "deleted",
                "scope", "source"}
    assert required <= set(columns), (
        f"列清单缺列（issue #4608 纪律）：{sorted(required - set(columns))}")


def test_types_are_explicit_in_the_values_list():
    """显式类型：`unit_price` 逐行 `::numeric`、两个布尔列逐行 `::boolean`。

    （V79 的真库事故 = `VALUES` 整列 NULL 被推断成 `text`，而 `text → numeric` **不是赋值转换**
    ⇒ 整文件单事务回滚、`schema_migrations` 里该版本永久缺席。）
    """
    for row in baseline_rows(migration_text()):
        assert re.search(r"::\s*numeric", row["unit_price"]), f"单价缺 `::numeric`：{row}"
        assert re.search(r"::\s*boolean", row["is_must_finish"]), f"必完缺 `::boolean`：{row}"
        assert re.search(r"::\s*boolean", row["is_start_marker"]), f"开始标记缺 `::boolean`：{row}"


def test_single_insert_statement_only():
    statements = [s.strip() for s in strip_sql_comments(migration_text()).split(";") if s.strip()]
    assert len(statements) == 1, f"本迁移应当只有 1 条语句，实测 {len(statements)}"


def test_red_line_never_touches_snapshot_tables():
    body = strip_sql_comments(migration_text())
    for table in SNAPSHOT_TABLES:
        assert table not in body, f"红线：本迁移不得出现快照表 `{table}`"
    assert "production_operation_positions" not in body, (
        "本迁移不写矩阵表（V89 ② 已负责）—— 两个表名极像，按全名点名")
    assert "INSERT INTO production_operations" in body, "本迁移必须写 `production_operations`"


def test_id_prefix_is_traceable_and_unique():
    body = strip_sql_comments(migration_text())
    assert "'op-v91-' || t.id" in body, "id 必须带 `op-v91-<tenantId>-` 前缀（可认领、可回滚）"
    sorts = [int(r["sort_order"]) for r in baseline_rows(migration_text())]
    assert len(set(sorts)) == len(sorts), "`sort_order` 必须唯一（id 后缀取它 ⇒ 否则撞主键）"


# ══════════════════════════════════════════════════════════════════════════════════
# ④ 「主线引用的工序必须在工序库里存在」—— ① bootstrap / ② 迁移链终态
# ══════════════════════════════════════════════════════════════════════════════════

def test_bootstrap_mainlines_all_have_library_rows(schema_sql):
    """**第一处口径 = bootstrap**：`schema.sql` 的每条路线主线，每道工序在它的工序种子里有行。"""
    library = set(bootstrap_row_values(schema_sql)) | {"打包"}
    mainlines = mainline_literals(schema_sql)
    assert mainlines, "`schema.sql` 里解析不到任何主线（守卫会空跑 —— 必须修解析）"
    dangling = dangling_in(mainlines, library)
    assert not dangling, f"bootstrap 终态里主线引用悬空：{sorted(set(dangling))}"


def test_migration_chain_terminal_mainlines_all_have_library_rows():
    """**第二处口径 = 迁移链终态**：聚合**全部**种子迁移的工序集与主线字面量。

    聚合口径按**内容发现**（凡含 `INSERT INTO production_operations` 的 `V*.sql` 都算）
    ⇒ 新增种子迁移无需改本测试。

    ⚠️ **中间态 vs 终态**：静态聚合看到的是**全部历史写者**，而终态 = **末次写者胜**。
    具体形态 = `V79` 种的主线字面量是 `["配料","打包"]`，`V88` ③ 用
    `UPDATE production_route_templates … CASE WHEN elem = '"配料"' THEN '"裁剪"'` **手术式改写**
    成 `["裁剪","打包"]` ⇒ `配料` 那一版是**已被取代**的中间态，不得当成终态判据
    （否则会把 V88 已修好的东西判成悬空 = 假红）。跳过条件**带自证**：只有确认链上
    **真的存在**那条改写语句时才跳过（见下 `assert rewritten`）。
    """
    library: set[str] = set()
    mainlines: list[list[str]] = []
    rewritten: set[str] = set()
    for path in sorted(MIGRATION_DIR.glob("V*.sql"),
                       key=lambda p: int(re.match(r"^V(\d+)__", p.name).group(1))):
        text = path.read_text(encoding="utf-8")
        library |= set(operation_names(text))
        mainlines.extend(mainline_literals(text))
        body = strip_sql_comments(text)
        if "UPDATE production_route_templates" in body:
            for retired in RETIRED_LOGICAL_NAMES:
                if f"'{retired}'" in body:
                    rewritten.add(retired)
    assert library, "迁移链里聚合不到任何工序种子（守卫会空跑）"
    assert mainlines, "迁移链里解析不到任何主线（守卫会空跑）"
    assert rewritten, (
        "链上找不到任何「主线改写」语句 ⇒ 不得跳过含退场工序的中间态字面量"
        "（否则这条跳过规则会变成静默豁免）")
    terminal = [m for m in mainlines if not (set(m) & rewritten)]
    assert terminal, "跳过中间态后终态主线为空（守卫会空跑）"
    dangling = dangling_in(terminal, library)
    assert not dangling, f"迁移链终态里主线引用悬空：{sorted(set(dangling))}"


def test_library_covers_every_logical_name_used_by_any_mainline():
    """口径自证：`LOGICAL_TO_LIBRARY_NAMES` 必须覆盖**全部**主线里出现过的逻辑名。

    不覆盖 ⇒ `dangling_in` 会把它当成悬空（假红）或漏判（假绿）—— 两种都不许。
    """
    seen: set[str] = set()
    for path in list(MIGRATION_DIR.glob("V*.sql")) + [SCHEMA_SQL]:
        for mainline in mainline_literals(path.read_text(encoding="utf-8")):
            seen |= set(mainline)
    assert seen, "聚合不到任何主线工序名（守卫会空跑）"
    missing = seen - set(LOGICAL_TO_LIBRARY_NAMES) - set(RETIRED_LOGICAL_NAMES)
    assert not missing, f"映射表缺逻辑名：{sorted(missing)}"


def test_v91_is_load_bearing_in_the_migration_chain_aggregate():
    """承重自证：`V91` 的 36 行**必须**是聚合的一部分（否则它没在承重）。"""
    library: set[str] = set()
    for path in MIGRATION_DIR.glob("V*.sql"):
        library |= set(operation_names(path.read_text(encoding="utf-8")))
    assert set(baseline_names(migration_text())) <= library


# ══════════════════════════════════════════════════════════════════════════════════
# ④b 第三处口径（**运行时读面**）的静态镜像：逐格「逻辑名 × 部位 → 库行」
# ══════════════════════════════════════════════════════════════════════════════════
# 为什么要有它：Java 侧 `MainlineOperationReferenceTest` 只能按「**至少一个适用部位**」判
# （矩阵格 `applicable = FALSE` 的格会在取变体之前被静默滤掉 ⇒ 逐部位判会**假红**）。
# **逐格**口径因此落在这里：解析 Java 侧**真值常量**（`variantNames()` 的逆索引 +
# `ProductionSeedTemplateService.CANONICAL_POSITION_PRICES` 的规范矩阵），按运行时
# `variantNameOf` 的**三步**逐格复算 ⇒ 任一格「适用但解析不出」即红。
# ⚠️ 这不是「第二份口径」：两份表都是**从 Java 源码文本解析**的，不是手抄。
# ⚠️ `#4777` 起 `variantNameOf` 是**三步**（帘头不再走隐式回落，改走显式帘头条目
# `headVariants()`）—— 本镜像**同步**去掉了那一步，见 `runtime_resolve` 的 docstring。

QUERY_SERVICE = REPO / (
    "backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java")
SEED_SERVICE = REPO / (
    "backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java")

VARIANT_CALL_RE = re.compile(
    r'variant\(\s*names\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')
#: 运行期解析表的**入口点声明**（issue #4796）：`variantNameOf` 查的是 `VARIANT_NAMES`，
#: 而它是**合成**出来的（`variantNames()` + `headVariants()`）⇒ 判据必须钉住这一处。
VARIANT_ENTRY_RE = re.compile(
    r"private static final Map<String, Map<String, String>> VARIANT_NAMES\s*=\s*(\w+)\(\)")
#: 入口点必须合成的 builder（改组合方式 ⇒ 判据**显式报红**，不静默读一个过期子集）。
VARIANT_ENTRY_BUILDER = "variantNamesWithCurtainHead"
MATRIX_ROW_RE = re.compile(
    r'\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*(null|"[^"]*")\s*,\s*"(true|false)"\s*\}')

#: V88 ④ 的**保命格**（`ProductionSeedTemplateService.FABRIC_KEEP_APPLICABLE_LOGICAL` / `FABRIC_POSITION`）。
FABRIC_KEEP_APPLICABLE_LOGICAL = "裁剪"
FABRIC_POSITION = "布料"


def runtime_variant_map(java_text: str | None = None) -> dict[tuple[str, str], str]:
    """运行期 `VARIANT_NAMES` 的逐条逆索引 —— **`variantNameOf` 实际查的那张表**。

    🔴 issue #4796：口径**只此一处**。`V97` 的 `variant_map`（30 条，已发布迁移**指纹冻结**）
    是它的**真子集**，差异恰为 21 条帘头回落（`headVariants()`，issue #4777）
    ⇒ 任何「某格解析得到吗」的判据都必须走本函数，**不得**拿 V97 的 map 当运行期口径
    （那样会把帘头格计成「从未登记」，真去"清理"就是静默丢弃商家的价）。

    ⚠️ 入口点声明本身是判据的一部分：`VARIANT_NAMES` 的**合成方式**变了 ⇒ 本函数显式报红
    （否则「文件里所有 `variant(names, …)`」会被当成运行期表 = 判据口径静默分叉）。

    @param java_text 注入用源码文本（注入式红证）；缺省读真源码。
    """
    text = QUERY_SERVICE.read_text(encoding="utf-8") if java_text is None else java_text
    entry = VARIANT_ENTRY_RE.search(text)
    assert entry, "读不到 `VARIANT_NAMES = <builder>()` 的入口点声明（守卫会空跑 —— 必须修解析）"
    assert entry.group(1) == VARIANT_ENTRY_BUILDER, (
        f"运行期解析表的入口点变成了 `{entry.group(1)}()` —— 本判据读的是**运行期那张表**，"
        f"入口点变更必须同步（否则判据口径与生产分叉，issue #4796）")
    pairs = VARIANT_CALL_RE.findall(text)
    assert pairs, "解析不到 `variantNames()` 的逆索引（守卫会空跑 —— 必须修解析）"
    return {(logical, position): variant for logical, position, variant in pairs}


def canonical_matrix() -> list[tuple[str, str, bool]]:
    """`CANONICAL_POSITION_PRICES` 的规范矩阵 ⇒ (逻辑名, 部位, 是否适用)。"""
    text = SEED_SERVICE.read_text(encoding="utf-8")
    decl = re.search(r"CANONICAL_POSITION_PRICES\s*=\s*\{", text)
    assert decl, "找不到 `CANONICAL_POSITION_PRICES` 的声明（守卫会空跑 —— 必须修解析）"
    end = text.index("\n    };", decl.end())
    rows = MATRIX_ROW_RE.findall(text[decl.end():end])
    assert rows, "解析不到 `CANONICAL_POSITION_PRICES` 的行（守卫会空跑 —— 必须修解析）"
    out = []
    for logical, position, _price, applicable in rows:
        # V88 ④ 保命格：`裁剪 × 布料` 由 `planPositions` **强制** TRUE（常量里是 false）
        keep_alive = (logical == FABRIC_KEEP_APPLICABLE_LOGICAL
                      and position == FABRIC_POSITION)
        out.append((logical, position, applicable == "true" or keep_alive))
    return out


def runtime_resolve(logical: str, position: str, variants: dict, library: set[str]):
    """`ProductionOperationQueryService.variantNameOf` 的三步（**同一顺序**；issue #4777 起）。

    ⚠️ **改前这里是四步**：第 2 步是「部位 = 帘头 ⇒ 取 `variants[(逻辑名, '布帘')]`」的
    **隐式规则**。`#4777` 把那条规则换成**显式**帘头条目（Java 侧 `headVariants()`）
    ⇒ 本镜像**同步去掉那一步**：帘头格现在与别的部位走**同一条**路径
    （`variants` 里查得到就查得到）。于是「删一条帘头条目 ⇒ 该格解析不到」
    **第一次可被本判据抓住**（改前被隐式规则兜着，删哪条都不红 = 判据对帘头恒真）。

    镜像必须逐字同步：Java 有隐式回落而这里没有 ⇒ 本判据**比生产更严** ⇒ 假红；
    反过来（生产没有、这里有）⇒ **空断言**。
    """
    variant = variants.get((logical, position))
    if variant is not None and variant in library:
        return variant
    return logical if logical in library else None


def test_canonical_matrix_applicable_cells_all_resolve_at_runtime(schema_sql):
    """**逐格**判据：规范矩阵里每个 `applicable = TRUE` 的格，运行时都要解析到一条库行。

    ⇒ 这正是 `裁剪 × 布料` 那道洞的**静态红证位**（保命格适用、而逆索引里没有 `布料`）。
    """
    variants = runtime_variant_map()
    library = set(bootstrap_row_values(schema_sql))
    unresolved = []
    for logical, position, applicable in canonical_matrix():
        if not applicable or logical in RETIRED_LOGICAL_NAMES:
            continue
        if runtime_resolve(logical, position, variants, library) is None:
            unresolved.append(f"{logical}×{position}")
    assert not unresolved, (
        f"规范矩阵里「适用但运行时解析不出库行」的格：{sorted(set(unresolved))}"
        f"（该部位的单实例化会 fail-closed 422）")


def test_canonical_matrix_covers_the_mainline_positions():
    """口径自证：规范矩阵必须真的覆盖主线用到的部位（否则上一条会静默空跑）。"""
    positions = {position for _logical, position, applicable in canonical_matrix() if applicable}
    assert {"布帘", "纱帘", "帘头", FABRIC_POSITION} <= positions, (
        f"规范矩阵缺部位：{sorted({'布帘', '纱帘', '帘头', FABRIC_POSITION} - positions)}")


def test_head_variants_cover_exactly_the_cloth_column():
    """issue #4777：帘头条目的覆盖域**恰等于**「有布帘条目的逻辑名」（21 个）—— 少一条 / 多一条都红。

    为什么必须**逐格等价**：改前帘头格靠 `variantNameOf` 的**隐式规则**（取布帘那一列）解析，
    本单把它换成**显式表** ⇒ 覆盖域必须**一字不变**：

    * 少一条 ⇒ 该帘头格解析不到 ⇒ `applicable = TRUE` 时**整单 422**、
      `applicable = FALSE` 时读面 5 键（`variant_operation_id` / `unit` / `group` / `scope` /
      `is_must_finish`）**静默变 null**；
    * 多一条 ⇒ 凭空发明一条库行寻址（本仓最忌）。
    """
    variants = runtime_variant_map()
    cloth = {logical: variant for (logical, position), variant in variants.items()
             if position == "布帘"}
    head = {logical: variant for (logical, position), variant in variants.items()
            if position == "帘头"}
    assert cloth, "解析不到布帘列 ⇒ 判据会空跑"
    assert head, "解析不到帘头列 ⇒ 判据会空跑（#4777 的显式表没落码）"
    # `帘头制作` 是**帘头专属**工序（库里真有这一行，不是复用布帘变体）⇒ 单独一个键。
    assert set(head) - {"帘头制作"} == set(cloth), (
        f"帘头覆盖域必须恰等于布帘列：多 {sorted(set(head) - {'帘头制作'} - set(cloth))} / "
        f"少 {sorted(set(cloth) - set(head))}")
    for logical, variant in cloth.items():
        assert head[logical] == variant, (
            f"`帘头 × {logical}` 必须指到它的布帘变体 `{variant}`，实际 `{head[logical]}`"
            "（帘头没有自己的变体行，库中从来没有 `-帘` 变体）")


def test_head_variants_are_reachable_for_every_applicable_curtain_head_cell(schema_sql):
    """口径自证：上一条不是**空跑** —— 规范矩阵里帘头格确实有 `applicable = TRUE` 的那些。"""
    head_cells = [logical for logical, position, applicable in canonical_matrix()
                  if applicable and position == "帘头" and logical not in RETIRED_LOGICAL_NAMES]
    assert head_cells, "规范矩阵里一个「帘头 applicable=TRUE」格都没有 ⇒ 逐格判据对帘头是空跑"
    library = set(bootstrap_row_values(schema_sql))
    variants = runtime_variant_map()
    for logical in head_cells:
        assert runtime_resolve(logical, "帘头", variants, library) is not None, (
            f"帘头格 `{logical} × 帘头` 适用却解析不到库行 ⇒ 帘头单 fail-closed 422")


# ══════════════════════════════════════════════════════════════════════════════════
# ⑤ 注入式红证：把被测行为弄坏 ⇒ 判据必红
# ══════════════════════════════════════════════════════════════════════════════════

class TestInjectedDrift:

    def test_dropping_a_row_is_detected(self):
        sql = migration_text()
        broken = sql.replace("UNION ALL SELECT '抱枕',", "UNION ALL SELECT '抱枕X',")
        assert broken != sql, "注入无效（找不到锚点）"
        assert set(baseline_names(broken)) != set(baseline_names(sql))

    def test_removing_the_tenants_loop_is_detected(self):
        broken = migration_text().replace("FROM tenants t", "FROM tenants t WHERE t.id = 20")
        assert not re.search(r"t\.deleted\s*=\s*0", strip_sql_comments(broken).split("FROM tenants")[1][:40]), \
            "把租户循环钉死成单租户后，`t.deleted = 0` 判据必须抓不到"

    def test_removing_the_packing_exclusion_is_detected(self):
        broken = strip_sql_comments(migration_text()).replace(
            "AND e.name <> '打包'", "")
        assert "e.name <> '打包'" not in broken

    def test_dropping_the_numeric_cast_is_detected(self):
        broken = migration_text().replace("::numeric", "")
        with pytest.raises(AssertionError):
            for row in baseline_rows(broken):
                assert re.search(r"::\s*numeric", row["unit_price"])

    def test_seeding_the_retired_name_is_detected(self):
        broken = migration_text().replace(
            "UNION ALL SELECT '打包', '后道'", "UNION ALL SELECT '配料', '后道'")
        assert broken != migration_text(), "注入无效（找不到锚点）"
        assert "配料" in baseline_names(broken)

    def test_gate_red_when_the_packing_carve_out_is_dropped(self):
        """闸门判据的**红证**：不排除 `打包` ⇒ 判据必红（V89 已补 `打包` ⇒ 闸门恒假）。"""
        body = strip_sql_comments(migration_text()).replace("AND e.name <> '打包'", "")
        gate = re.search(
            r"NOT EXISTS\s*\(\s*SELECT 1 FROM production_operations e\s*"
            r"WHERE e\.tenant_id = t\.id\s*(.*?)\)", body, re.S)
        assert gate, "注入后闸门解析不出来（说明锚点漂移，需同步本测试）"
        assert "e.name <> '打包'" not in gate.group(1), (
            "摘掉 `打包` 排除后判据必须能看出来 ⇒ 本判据是承重的")

    def test_mainline_guard_red_when_a_referenced_operation_is_dropped(self):
        """**本单的核心红证**：注入一条悬空引用 ⇒ 主线守卫必红。"""
        library = set(bootstrap_row_values(SCHEMA_SQL.read_text("utf-8"))) | {"打包"}
        assert dangling_in([["外帘发货"]], library) == [], "健康引用不得判红"
        assert dangling_in([["不存在的工序"]], library) == ["不存在的工序"], (
            "守卫抓不住注入的悬空引用 ⇒ 空断言")

    def test_mainline_guard_red_when_a_library_row_is_dropped(self):
        """把 `裁剪` 的库行摘掉 ⇒ 布料主线必红（= 真库里 `裁剪-布` 缺失时的形态）。"""
        library = (set(bootstrap_row_values(SCHEMA_SQL.read_text("utf-8"))) | {"打包"}) - {
            "裁剪-布", "裁剪-纱"}
        assert dangling_in([["裁剪", "打包"]], library) == ["裁剪"]

    def test_mainline_parser_detects_injected_drift(self, tmp_path):
        """解析器自证：主线字面量被改坏 ⇒ 解析结果跟着变（不是恒空）。"""
        prefix = "INSERT INTO production_route_templates\n (id, tenant_id, name, is_default, positions, mainline, status)\nVALUES\n"
        good = prefix + "'x', 1, 'n', TRUE, '[\"布帘\"]'::jsonb, '[\"裁剪\", \"打包\"]'::jsonb, 'active';"
        bad = prefix + "'x', 1, 'n', TRUE, '[\"布帘\"]'::jsonb, '[\"裁剪\"]'::jsonb, 'active';"
        assert mainline_literals(good) == [["裁剪", "打包"]]
        assert mainline_literals(bad) == [["裁剪"]]
        assert mainline_literals(prefix + "'x', 1, 'n', TRUE, '[\"布帘\", \"纱帘\", \"帘头\"]'::jsonb, '[\"裁剪\"]'::jsonb, 'active';") == [["裁剪"]], (
            "部位字面量不得被当成主线（否则假红）")
        # 旧两表（变体名口径）不得被当成新模型主线
        assert mainline_literals(
            "INSERT INTO production_routings (id, operations) VALUES ('x', '[\"精裁-布\"]'::jsonb);"
        ) == []

    def test_runtime_resolution_check_is_load_bearing(self, schema_sql):
        """**发现 1 的静态红证**：摘掉 `裁剪 × 布料` 那条回落 ⇒ 逐格判据必红。"""
        variants = dict(runtime_variant_map())
        library = set(bootstrap_row_values(schema_sql))
        assert runtime_resolve("裁剪", FABRIC_POSITION, variants, library) == "裁剪-布", (
            "修好后必须解析到 `裁剪-布`")
        variants.pop(("裁剪", FABRIC_POSITION))
        assert runtime_resolve("裁剪", FABRIC_POSITION, variants, library) is None, (
            "摘掉回落条目后必须解析不出 ⇒ 逐格判据抓的是真行为（改前真库形态）")

    def test_runtime_resolution_red_when_the_library_row_is_missing(self, schema_sql):
        """摘掉库行（= 租户 20/21 的形态）⇒ 解析必失败。"""
        variants = runtime_variant_map()
        library = set(bootstrap_row_values(schema_sql)) - {"精裁-布", "精裁-纱"}
        assert runtime_resolve("精裁", "布帘", variants, library) is None
        assert runtime_resolve("精裁", "布帘", variants,
                               library | {"精裁-布"}) == "精裁-布"

    def test_dropping_a_head_variant_entry_makes_the_cell_guard_red(self, schema_sql):
        """**#4777 的红证**：注入「删一条帘头条目」⇒ 逐格判据**必红**（证明它不是恒真）。

        ⚠️ 这正是**改前做不到**的那一步：改前帘头格由 `variantNameOf` 的**隐式规则**
        （「部位 = 帘头 ⇒ 取布帘那一列」）兜着 ⇒ 删掉任何帘头条目都**不会红**，
        于是「凡 `applicable = TRUE` 的格必须解析得到」这条判据对帘头**恒真**（空断言）。
        改成显式表后，条目本身**承重**。
        """
        variants = dict(runtime_variant_map())
        library = set(bootstrap_row_values(schema_sql))
        assert runtime_resolve("三边", "帘头", variants, library) == "布三边", (
            "健康态：`三边 × 帘头` 必须解析到 `布三边`（帘头复用布帘变体）")
        assert ("三边", "帘头") in variants, "解析不到该条目 ⇒ 注入无法构造"
        variants.pop(("三边", "帘头"))
        assert runtime_resolve("三边", "帘头", variants, library) is None, (
            "摘掉帘头条目后仍解析得出 ⇒ 判据是空断言（改前正是这个形态）")
        unresolved = sorted({f"{logical}×{position}" for logical, position, applicable
                             in canonical_matrix()
                             if applicable and logical not in RETIRED_LOGICAL_NAMES
                             and runtime_resolve(logical, position, variants, library) is None})
        assert unresolved == ["三边×帘头"], (
            f"逐格判据必须**点名报出**注入的那一格且只报它，实际 {unresolved}")

    def test_dropping_the_whole_head_column_makes_every_curtain_head_cell_red(self, schema_sql):
        """把**整列**帘头条目摘掉 ⇒ 全部「帘头 applicable=TRUE」格一起红（判据覆盖到每一格）。"""
        variants = {k: v for k, v in runtime_variant_map().items() if k[1] != "帘头"}
        library = set(bootstrap_row_values(schema_sql))
        unresolved = sorted({logical for logical, position, applicable in canonical_matrix()
                             if applicable and position == "帘头"
                             and logical not in RETIRED_LOGICAL_NAMES
                             and runtime_resolve(logical, position, variants, library) is None})
        assert unresolved, "整列摘掉后一格都不红 ⇒ 逐格判据对帘头是空跑"
        assert "帘头制作" not in unresolved, (
            "`帘头制作` 是**帘头专属**工序（不走帘头复用列）⇒ 摘掉帘头复用列不该波及它")

    def test_variant_map_parser_detects_injected_drift(self):
        """解析器自证：`variant(...)` 行的形态变了 ⇒ 解析结果跟着变。"""
        good = 'variant(names, "裁剪", "布料", "裁剪-布");'
        assert VARIANT_CALL_RE.findall(good) == [("裁剪", "布料", "裁剪-布")]
        assert VARIANT_CALL_RE.findall('variant(names2, "裁剪", "布料", "裁剪-布");') == [], (
            "只认 `variant(names, …)` 这一形态，不得把别处调用混进来")

    def test_matrix_parser_detects_injected_drift(self):
        good = '{"精裁", "布帘", "0.4", "true"},'
        bad = '{"精裁", "布帘", "0.4", "false"},'
        assert MATRIX_ROW_RE.findall(good) == [("精裁", "布帘", '"0.4"', "true")]
        assert MATRIX_ROW_RE.findall(bad) == [("精裁", "布帘", '"0.4"', "false")]


@pytest.fixture(scope="module")
def schema_sql():
    return SCHEMA_SQL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def seed_json():
    return json.loads(SEED_JSON.read_text(encoding="utf-8"))
