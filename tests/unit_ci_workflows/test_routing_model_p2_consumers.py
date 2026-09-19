# case_ids: PG-018, PG-035, PG-039
"""工序路线模型 **P2（切消费路径）** 的结构守卫（issue #4432 = 母单 #4423 的 P2/3）。

⚠️ 本文件的用例声明行**必须**在文件前 50 行内（`.github/growth_gate.py` 的 `extract_case_ids()`
只扫前 50 行），故它放在 docstring 之前。

## 为什么需要它（形态 = 「切了消费路径但存量租户没数据」⇒ 全量停摆）

P1（#4427）只**新增**三张表并把种子**只种 `tenant_id = 1`**（与 V54/V56/V58/V59 先例一致）。
P2 一旦把消费路径切到新表，`defaultRouteTemplate(tenantId)` 对**任何非 1 号租户**都返回 `null`
⇒ `resolveRoute` T3 fail-closed ⇒ **该租户一张加工单也生成不了（422）**。

这正是 #4316 的同族形态复发：当时修的只是「开租时自动套用」（只覆盖**此后新建**的租户），
对**存量租户**从来没有回填路径。⇒ 本单的 V72 **必须按租户循环回填**。

## 判据（各有独立红证，互不掩盖）

| # | 判据 | 红证形态 |
|---|---|---|
| A | V72 **按租户循环**（`FROM tenants`）为**每一个**活跃租户回填新三表；口径 = **该租户自己的** `production_operations`（不是从 1 号租户复制）；幂等 | 删掉按租户回填（或只保留 1 号）⇒ 红 |
| B | **商户级默认工艺**：V72 建 `production_crafts`（含 `is_default`）并为**每个租户**恰好种一条默认 —— 缺 `craft` 时取它，**不得**写死常量 `韩褶` | 缺默认工艺表/种子 ⇒ 红 |
| C | **旧规则表退场**：`production_option_routings` / `production_option_factors` 的活跃行软删为 0，且三个消费服务的 Java 源码里**零**读取点（读取点全改 `production_route_rules`）；**表先不 DROP** | 仍有读取点 ⇒ 红 |

红证原文（本文件对当前树的运行结果）见 PR body —— 本单按 TDD 先落本文件、确认**红**，再实现 V72。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
JAVA_SERVICE_DIR = REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
SCHEMA = REPO / "docs/sql/schema.sql"

#: 本单的迁移号（V71 已被 P1 / #4427 占用；已发布迁移不可改）。
V72_NAME = "V72__switch_routing_model_consumers.sql"
V72 = MIGRATION_DIR / V72_NAME

#: 新三表（P1 / #4427 建，本单开始有消费者）。
NEW_TABLES = ("production_operation_positions", "production_route_templates", "production_route_rules")
#: 旧规则表（本单软删退场；**表先不 DROP**，可回滚）。
RETIRED_TABLES = ("production_option_routings", "production_option_factors")
#: 旧规则表的读取点所在服务（issue #4432 §六·补：这三处必须全部改读 production_route_rules）。
RETIRED_READER_SERVICES = (
    "ProductionOperationQueryService.java",
    "ProcessingOrderService.java",
    "ProductionSeedTemplateService.java",
)
#: 退场后**唯一**的规则真值源。
RULE_TABLE = "production_route_rules"
#: 商户级默认工艺表（判据 B）。
CRAFT_TABLE = "production_crafts"


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释（守卫必须看**可执行 SQL**，不能把注释里的字面量当成实现）。"""
    return "\n".join(line for line in sql.split("\n") if not line.lstrip().startswith("--"))


def _insert_statements(body: str, table: str) -> list:
    """取出所有 `INSERT INTO <table> … ;` 语句（非贪婪到分号）。"""
    return re.findall(r"INSERT\s+INTO\s+" + table + r"\b[\s\S]*?;", body, re.I)


def _v72_body(sql: str | None = None) -> str:
    """V72 的**可执行** SQL（去注释）；可注入（红证用临时内容，不落盘）。"""
    return _strip_comments(sql if sql is not None else _read(V72))


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 A：按租户循环回填（P0 —— 漏了就是一次全量非 1 号租户停摆）
# ══════════════════════════════════════════════════════════════════════════════════

def test_v72_migration_exists():
    assert V72.exists(), (
        f"缺少 {V72_NAME} —— P2 的存量租户回填 + 默认工艺 + 旧规则表退场都在这个迁移里"
        f"（V71 已被 P1 / #4427 占用，已发布迁移不可改）"
    )


def test_per_tenant_backfill_loops_over_tenants(sql: str | None = None):
    """判据 A-1：回填必须**按租户循环**（`FROM tenants` 范式，同 V29/V32/V43）。"""
    body = _v72_body(sql)
    assert re.search(r"\bFROM\s+tenants\b", body, re.I), (
        "V72 没有 `FROM tenants` —— 回填没有按租户循环。"
        "只种 tenant_id = 1 ⇒ 切换消费路径那一刻，所有非 1 号租户 defaultRouteTemplate=null "
        "⇒ resolveRoute T3 fail-closed ⇒ 一张加工单也生成不了（#4316 同族复发）"
    )


def test_per_tenant_backfill_writes_all_three_tables(sql: str | None = None):
    """判据 A-2：三张新表**每一张**都要被按租户回填（漏一张 = 那一层读面为空）。"""
    body = _v72_body(sql)
    missing = [t for t in NEW_TABLES if not _insert_statements(body, t)]
    assert not missing, (
        f"V72 没有按租户回填这些新表：{missing} —— 三张表各自是一层读面"
        f"（部位价目 / 具名路线 / 规则），漏任一张 = 该层为空 ⇒ 实例化 fail-closed"
    )


def test_backfill_uses_tenants_own_operations_not_tenant_one(sql: str | None = None):
    """判据 A-3（P0 口径）：回填口径 = **该租户自己的** `production_operations`。

    从 1 号租户复制会把「已被客户改过的价」当成别人的初始价 —— 那是**静默的错价**，
    而错价直接算成工人工资（判据 17）。
    """
    body = _v72_body(sql)
    op_inserts = _insert_statements(body, "production_operations")  # 反向断言：不得有回填写工序库
    assert not op_inserts, (
        "V72 向 `production_operations` 写了行 —— 本单不动工序库（只读它作为回填口径来源）"
    )
    assert re.search(r"\bFROM\s+production_operations\b", body, re.I), (
        "V72 的回填没有从 `production_operations` 取口径 —— 口径必须是**该租户自己的**工序库行"
        "（判据 17：从 1 号租户复制 ⇒ 改过价的租户被覆盖）"
    )
    # 「按租户循环」的实质 = 有子查询把 production_operations 按**本租户**过滤
    # （`o.tenant_id = t.id`；`t` 是 `FROM tenants t` 的别名 —— 不写死别名，按形态取）
    tenants_alias = re.search(r"FROM\s+tenants\s+(\w+)", body, re.I)
    assert tenants_alias, "V72 没有 `FROM tenants <alias>` —— 无法判定「按租户循环」"
    alias = tenants_alias.group(1)
    op_alias = re.search(r"\bFROM\s+production_operations\s+(\w+)", body, re.I)
    assert op_alias, "V72 的 production_operations 没有作为数据源出现"
    joined = re.search(
        r"\b" + re.escape(op_alias.group(1)) + r"\s*\.\s*tenant_id\s*=\s*" + re.escape(alias) + r"\s*\.\s*id",
        body, re.I)
    assert joined, (
        f"V72 的 production_operations 没有与 tenants 按 `{op_alias.group(1)}.tenant_id = {alias}.id` 关联"
        f" —— 「按租户循环」的实质就是这条过滤（否则仍是从某个固定租户取）"
    )
    # 反向断言：**主线与规则**不得出现「从 1 号租户复制」的形态。
    # （部位价目表的回填源**是**规范矩阵 `p.tenant_id = 1 AND p.id LIKE 'opp-v70-%'` ——
    #   那是 P1 冻结的 84 行真值源、不是「某个租户被改过的数据」；价目口径见 V72 注释。）
    for stmt in _insert_statements(body, "production_route_templates") + \
            _insert_statements(body, "production_route_rules"):
        assert not re.search(r"tenant_id\s*=\s*1\b", stmt, re.I), (
            "V72 的回填语句里出现 `tenant_id = 1` —— 那是「从 1 号租户复制」，"
            "会把 1 号租户被客户改过的价复刻给别人（判据 17 的红证形态）"
        )


def test_backfill_is_idempotent(sql: str | None = None):
    """判据 A-4：幂等（`ON CONFLICT … DO NOTHING`）。

    `bootstrap-first` 会让迁移在建好终态的库上再跑一遍；裸 INSERT 会追加第二份（判据 16）。
    """
    body = _v72_body(sql)
    for table in NEW_TABLES:
        stmts = _insert_statements(body, table)
        assert stmts, f"V72 没有向 {table} 回填任何行"
        for stmt in stmts:
            assert re.search(r"ON\s+CONFLICT[\s\S]{0,200}?DO\s+NOTHING", stmt, re.I), (
                f"V72 向 {table} 的回填不是幂等的（缺 `ON CONFLICT … DO NOTHING`）"
                f" ⇒ 重复执行会追加第二份（判据 16 的红证形态）"
            )


def test_backfill_covers_all_active_tenants(sql: str | None = None):
    """判据 A-5：`FROM tenants` 必须限定**活跃**租户（`deleted = 0`），不漏不越。"""
    body = _v72_body(sql)
    chunks = re.findall(r"FROM\s+tenants\s+\w+[\s\S]*?(?=;\s*$|\n\s*(?:INSERT|CREATE|UPDATE|ALTER|COMMENT)\b)",
                        body, re.I | re.M)
    assert chunks, "V72 没有 `FROM tenants`"
    missing = [c for c in chunks if not re.search(r"deleted\s*=\s*0", c, re.I)]
    assert not missing, (
        f"V72 有 {len(missing)} 处 `FROM tenants` 没有限定 `deleted = 0` —— 会给已删除的租户也回填数据"
    )


def test_backfill_derives_operation_names_from_tenant_rows(sql: str | None = None):
    """判据 A-6：回填的工序名必须**来自该租户的工序库行**（不是写死的字面量清单）。

    写死清单 = 「发明口径」：客户改过工序名后回填出来的主线/规则与他的库对不上。

    适用范围 = **主线与规则**（它们按租户库归一）。**部位价目表**的源是 P1 冻结的规范矩阵
    （84 行，逐条溯源到 `production_operations.unit_price`），故不在此列 —— 它的判据是
    「逐行等于规范矩阵」，由 `test_production_catalog_seed.py` 的三源收敛守卫覆盖。
    """
    body = _v72_body(sql)
    for table in ("production_route_templates", "production_route_rules"):
        stmts = _insert_statements(body, table)
        assert stmts, f"V72 没有向 {table} 回填行"
        assert any(re.search(r"\bFROM\s+production_operations\b", s, re.I) or
                   re.search(r"\bJOIN\s+production_operations\b", s, re.I) for s in stmts), (
            f"{table} 的回填没有从 `production_operations` 取值 —— 写死清单即「发明口径」"
        )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 B：商户级默认工艺（缺 craft 不得写死常量 韩褶）
# ══════════════════════════════════════════════════════════════════════════════════

def test_default_craft_table_exists_with_is_default(sql: str | None = None):
    """判据 B-1：`production_crafts`（含 `is_default`）—— 商户级默认工艺的载体。

    规格订正（issue #4432 评论「🔴 规格订正：缺维补齐**不能**用默认路线的对应维」判据 21~24）：
    重构后**缺 `craft` 不能从默认路线取**（路线模板没有工艺维）⇒ 必须引入「商户级默认工艺」。
    本单取**形态②**（新表 + `is_default`），理由写进 PR。
    """
    body = _v72_body(sql)
    create = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + CRAFT_TABLE + r"\b[\s\S]*?\);",
                       body, re.I)
    assert create, (
        f"V72 没有建 {CRAFT_TABLE} —— 缺 `craft` 时无处可取（路线模板没有工艺维），"
        f"只能写死常量 `韩褶` ⇒ 商户只做打孔时会插错工序 + 算错计件系数 = 错发工资"
    )
    assert re.search(r"\bis_default\b", create.group(0), re.I), (
        f"{CRAFT_TABLE} 缺 `is_default` 列 —— 没有它就无法表达「恰一条默认工艺」"
    )


def test_default_craft_seeded_per_tenant(sql: str | None = None):
    """判据 B-2：**每个活跃租户**恰好一条默认工艺（按租户循环种，幂等）。"""
    body = _v72_body(sql)
    stmts = _insert_statements(body, CRAFT_TABLE)
    assert stmts, f"V72 没有向 {CRAFT_TABLE} 种任何行"
    assert any(re.search(r"\bFROM\s+tenants\b", s, re.I) for s in stmts), (
        f"{CRAFT_TABLE} 的种子没有按租户循环（缺 `FROM tenants`）—— 非 1 号租户无默认工艺"
        " ⇒ 缺 craft 时静默取常量（判据 23 的红证形态）"
    )
    for stmt in stmts:
        assert re.search(r"ON\s+CONFLICT[\s\S]{0,200}?DO\s+NOTHING", stmt, re.I), (
            f"{CRAFT_TABLE} 的种子不幂等（缺 `ON CONFLICT … DO NOTHING`）"
        )
    # 恰一条默认：必须用部分唯一索引把「≤1 条默认」变成数据不变式
    assert re.search(r"CREATE\s+UNIQUE\s+INDEX[\s\S]{0,200}?" + CRAFT_TABLE + r"[\s\S]{0,200}?is_default",
                     body, re.I), (
        f"{CRAFT_TABLE} 没有 `(tenant_id) WHERE is_default AND deleted = 0` 的部分唯一索引 —— "
        f"「恰一条默认工艺」就只是注释里的约定，第二条默认插得进来"
    )


@pytest.mark.xfail(reason="消费路径切换（ProcessingOrderService 缺 craft 改取商户级默认工艺）"
                         "不在本 PR 范围（见 PR 说明）；本判据是下一 PR 的红证前置", strict=False)
def test_no_hardcoded_default_craft_constant_in_derive_route_key():
    """判据 B-3：`deriveRouteKey` 缺 `craft` 时**不得**回落到常量 `DEFAULT_CRAFT`。

    常量本身可以保留（退化为**种子回填来源与文案措辞**，规格 §四明文允许），
    但**不得**再作为运行时的缺维补齐目标。
    """
    src = _read(JAVA_SERVICE_DIR / "ProcessingOrderService.java")
    derive = re.search(r"private\s+RouteKey\s+deriveRouteKey\s*\([\s\S]*?\n    \}", src)
    assert derive, "找不到 ProcessingOrderService.deriveRouteKey —— 规格锚点变了，请同步本守卫"
    assert "DEFAULT_CRAFT" not in derive.group(0), (
        "deriveRouteKey 仍在缺 `craft` 时回落到 `DEFAULT_CRAFT` 常量 —— 规格订正判据 22/24 要求"
        "改取**该租户的默认工艺**（配置可改）；写死常量 ⇒ 商户只做打孔时插错工序 + "
        "算错计件系数 = 错发工资"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 C：旧规则表退场 —— **C-1/C-5/C-6 属 P2b**（软删必须与消费切换同 PR）；
#        **C-7 属 P2a**（V72 不得提前软删）；C-2/C-3/C-4 属 P2a（搬迁是纯增量）
# ══════════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(reason="软删旧规则表**已从 V72 移出**（主会话复核 2026-09-19）："
                         "Java 此刻仍读旧表，提前软删 = 条件工序不插 / 系数退回 1.0 = 少发工人钱；"
                         "软删改与「三个消费服务改读规则表」同 PR 原子发布（P2b）", strict=False)
def test_old_rule_tables_soft_deleted(sql: str | None = None):
    """判据 C-1（**P2b**）：旧两表的活跃行软删为 0（判据 12）。

    ⚠️ 本判据**不属于 P2a** —— 见 `test_v72_must_not_retire_legacy_rule_tables` 的理由：
    软删必须与消费路径切换同 PR 原子发布，否则中间态**少发工人钱**。
    """
    body = _v72_body(sql)
    for table in RETIRED_TABLES:
        stmt = re.search(r"UPDATE\s+" + table + r"\b[\s\S]*?;", body, re.I)
        assert stmt, (
            f"V72 没有软删 {table} 的行 —— 不收口就是「同一份规则有两个真值源」，"
            f"而漏的那一处正好是条件工序与计件系数（= 工人工资）"
        )
        assert re.search(r"SET[\s\S]{0,120}?deleted\s*=\s*1", stmt.group(0), re.I), (
            f"V72 对 {table} 的处置不是软删（`SET deleted = 1`）"
        )


def test_old_rule_tables_not_dropped(sql: str | None = None):
    """判据 C-2：**表先不 DROP**（可回滚）；DROP 留待后续独立迁移。"""
    body = _v72_body(sql)
    for table in RETIRED_TABLES:
        assert not re.search(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + table + r"\b", body, re.I), (
            f"V72 直接 DROP 了 {table} —— 规格明文「表本身先不 DROP」（可回滚），"
            f"DROP 留待后续独立迁移（届时须确认零消费者）"
        )


def test_rule_table_gains_factor_column_and_relaxed_action(sql: str | None = None):
    """判据 C-3：V71 的规则表**没有 `factor` 列** ⇒ V72 补列 + 放宽 `action` CHECK + `operation` 可空。

    系数档位必须有地方存（`OPTION_FACTOR_SCOPES` 的「一分为二 → ×1.7」），
    而**不允许**把系数留在旧表（那就是第二份口径）。
    """
    body = _v72_body(sql)
    assert re.search(r"ALTER\s+TABLE\s+" + RULE_TABLE +
                     r"\b[\s\S]{0,200}?ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?factor\b", body, re.I), \
        f"V72 没有给 {RULE_TABLE} 补 `factor` 列"
    assert re.search(r"action\s+IN\s*\([^)]*'factor'[^)]*\)", body, re.I), (
        f"V72 没有把 {RULE_TABLE}.action 的 CHECK 放宽为含 'factor' —— 系数档无法落库"
    )
    assert re.search(r"ALTER\s+COLUMN\s+operation\s+DROP\s+NOT\s+NULL", body, re.I), (
        f"V72 没有把 {RULE_TABLE}.operation 改为可空 —— 平摊档（不限工序）无法表达"
    )


def test_option_factor_rules_migrated_into_rule_table(sql: str | None = None):
    """判据 C-4：旧 `production_option_factors` 的档位必须**搬进**规则表（`action='factor'`）。

    只软删旧表而不搬迁 = **静默丢掉计件系数**（`一分为二 ×1.7` 消失 ⇒ 工人少发钱）。
    """
    body = _v72_body(sql)
    stmts = _insert_statements(body, RULE_TABLE)
    assert stmts, f"V72 没有向 {RULE_TABLE} 写任何行"
    assert any(re.search(r"'factor'", s) and re.search(r"\bfactor\b\s*[,)]|\bfactor\b\s*=", s)
               for s in stmts) or re.search(r"'factor'", body), (
        f"V72 没有把计件系数档搬进 {RULE_TABLE}（`action='factor'`）—— "
        f"只软删旧表不搬迁 = 静默丢掉系数（改的是工人钱）"
    )


@pytest.mark.xfail(reason="旧规则表读取点收口（三个消费服务）不在本 PR 范围；"
                         "本判据是下一 PR 的红证前置", strict=False)
def test_no_reader_of_retired_rule_tables_in_consumer_services():
    """判据 C-5：三个消费服务的 Java 源码里**零**读取点（旧表已退场，判据 12）。

    读取点的机械判据 = 这些文件里不再出现旧表的 **entity / mapper** 类型
    （`ProductionOptionRouting` / `ProductionOptionFactor`）—— 读表必然经它们。
    """
    offenders = {}
    for name in RETIRED_READER_SERVICES:
        path = JAVA_SERVICE_DIR / name
        assert path.exists(), f"规格锚点变了：找不到 {path}"
        hits = sorted(set(re.findall(r"ProductionOption(?:Routing|Factor)", _read(path))))
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"这些服务仍在读旧规则表（经 entity/mapper 类型）：{offenders} —— "
        f"规格 §六·补要求读取点**全部**改读 `{RULE_TABLE}`；"
        f"不收口 = 同一份规则两个真值源，改一处漏一处（漏的是条件工序与计件系数 = 工人工资）"
    )


@pytest.mark.xfail(reason="消费服务改读 production_route_rules 不在本 PR 范围；"
                         "本判据是下一 PR 的红证前置", strict=False)
def test_consumers_read_the_rule_table():
    """判据 C-6：收口后三个服务确实读**新**规则表（不是把旧读取点删掉了事）。"""
    missing = [name for name in RETIRED_READER_SERVICES
               if "productionrouterules" not in _read(JAVA_SERVICE_DIR / name).replace("_", "").lower()]
    assert not missing, (
        f"这些服务没有出现 `{RULE_TABLE}`：{missing} —— "
        f"退场不等于删掉读取点（那会静默丢掉条件工序与计件系数）"
    )


# ══════════════════════════════════════════════════════════════════════════════════
# 判据 D：bootstrap 终态同步（只写迁移 = 新建库无表 ⇒ 读面 500，同 #3270 形态）
# ══════════════════════════════════════════════════════════════════════════════════

def test_schema_sql_carries_p2_terminal_state():
    """判据 D：`docs/sql/schema.sql` 必须同步本单的终态（列 + 表）。"""
    schema = _read(SCHEMA)
    assert re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + CRAFT_TABLE + r"\b", schema, re.I), (
        f"schema.sql 缺 {CRAFT_TABLE} —— bootstrap 栈（docker-entrypoint-initdb.d）**不跑迁移链**"
        f" ⇒ 只写迁移 = 新建库无该表 ⇒ 读面 500"
    )
    assert re.search(r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?factor\b", schema, re.I), (
        f"schema.sql 缺 {RULE_TABLE}.factor 列（同 #3270 形态）"
    )


def test_v72_must_not_retire_legacy_rule_tables(sql: str | None = None):
    """判据 C-7（**P2a 的「行为零变化」守卫**）：V72 **不得**软删旧规则表。

    理由（已实测，主会话 2026-09-19 复核）：Java 侧此刻**仍读**这两张旧表
    （`ProductionOperationQueryService.optionRoutings` / `optionFactors` →
    `ProcessingOrderService` 插条件工序 + 算计件系数），而**消费路径切换在 P2b**。
    ⇒ 若本迁移先把旧行软删、Java 还没切过去 ⇒ **条件工序不会插入、计件系数退回 1.0**
    ⇒ **少发工人钱**（#4230「静默黑洞」同族形态）。

    ⇒ 软删必须与「三个消费服务改读 `production_route_rules`」**同一 PR 原子发布**。

    **红证**：把两条 `UPDATE production_option_*  SET deleted = 1` 加回 V72 ⇒ 本判据红。
    """
    body = _v72_body(sql)
    for table in ("production_option_routings", "production_option_factors"):
        assert not re.search(rf"UPDATE\s+{table}\b", body, re.I), (
            f"V72 软删了旧规则表 `{table}` —— 但 Java **仍在读它**（消费切换在 P2b）⇒ "
            f"条件工序不插、计件系数退回 1.0 = **少发工人钱**。"
            f"软删必须与消费切换同一 PR 原子发布（本判据是「P2a 行为零变化」的承重断言）。"
        )
