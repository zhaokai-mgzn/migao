# case_ids: PG-018, PG-020, PG-035
"""**去部位化彻底版：单条合并迁移 `V102` 的承重判据**（issue #4937 = 母单 #4936）。

## 被判对象

| 对象 | 做什么 | 本文件的判据 |
|---|---|---|
| `V102__retire_applicability_flag.sql`（**一条**，重写） | ① 矩阵按 `(tenant_id, logical_name)` **塌缩为一行**（幸存行 `position = '通用'` + `applicable = TRUE`，其余**软删**）；② 补 4 道 `-纱` 纱帘变体工序行（字面量 + 按租户派生回填） | ① 静态：四档选行序 / **先算后动** / **零时间戳判据** / 软删不物理删 / 写与自证共用物化判据 / 显式事务 / 回滚登记；② 真库：**两遍幂等** + 独立重算幸存行 + 存活/退场行数对账 + `帘头制作 = 2.00` + **`applicable IS NULL` 不致命** + 历史/账本指纹不变 |
| `V103` / `V104` / `V105` / `V106`（**已删除**） | 内容已并入 `V102`（`V103` 的意图另被 #4962 **作废**） | 文件**不在磁盘**、且**不在**迁移指纹账本里（「删文件 / 删账本条目 = 绕过」的机械判据） |

## 为什么可以合并重写（本单的立论前提，**核过**才动手）

五条**从未在任何环境成功应用过**：云测试环境 **2026-09-20** 容器启动日志逐条点名
`V102` / `V103` / `V104` / `V105` / `V106` 失败（另 4 条 `V40` / `V72` / `V74` / `V79` 是**存量噪音**，
不在本单射程）；线上读面实测矩阵 `position` 仍是 `布帘`/`帘头`、工序库里没有 4 道 `-纱` 变体。
`MigrationRunner` 的台账按**文件名**记账、已应用的文件整份跳过 ⇒ 它们是**没生效的半成品**。
用户裁定 2026-09-21：「**DB层的改造需要彻底**」+ 早先「这些都是**测试数据**，**不要怕搞坏**」+「**不计成本的改**」。

## 真库判据（临时 PG 集群；缺 PG 的处置收口在 `pg_cluster.py`：CI 判**红** / 本机显式 skip，issue #5203）

照本仓既有的临时集群范式：`initdb` / `pg_ctl` / `psql` 起**临时集群**真跑 ——
静态文本判据不够（文本守卫全绿而真库整份回滚的形态出现过）。

## 为什么必须真跑两遍

`MigrationRunner` 要求**所有**迁移可重复执行；而「幂等」只有真库能判：
`WHERE deleted = 0` 与窗口函数的交互、`CREATE TEMP TABLE … ON COMMIT DROP` 的生命周期、
`RAISE EXCEPTION` 的回滚半径 —— 三者都是**运行期**语义。

## 🔴 判据被削弱了没有（逐条对照上版，**这是本文件最该被 review 的地方**）

| 上版的判据 | 本文件 |
|---|---|
| `V102` 只认领「已是 TRUE」的行、`FALSE` 留给下一条迁移 | **改判**：五条合并为一条 ⇒ 「留给下一条迁移」这一格**失去对象**（没有下一条）。强度换到「**先算后动**」上：`test_v102_materialises_the_survivor_set_before_any_write` + 「`applicable IS NULL` 不致命」真库判据 |
| `V103` 清空规则 `position` | **改判（#4962）**：部位维**保留** ⇒ 本文件改判为「`V102` **一字不碰** `production_route_rules`」+「真库跑完规则表**逐字节指纹不变**」（见 `test_v102_never_touches_production_route_rules` 与 `test_route_rules_are_byte_identical`）。规则侧的**终态**判据在 `test_production_catalog_seed.py` 的「部位维在多源间一致」用例 |
| `V104` 四档选行 / 软删 / 共享物化判据 / 注入红证 | **全部保留**，另**加强**一格：幸存行由「**迁移前**状态上独立重算的期望集合」逐行核对（不再是「拿终态自重算的不动点」） |
| `V105` / `V106` 多租户补种 / 闸门 / 软删不复活 / 已知边界 | **全部保留**（合并成一条迁移的两个来源），另**加强**一格：单价/分组/单位/scope 必须**逐字取对应 `-布` 行**（夹具故意让 2 号租户的 `-布` 值不同 ⇒ 发明一个值即红） |
| bootstrap ↔ 迁移链终态一致 | **保留并加强**：除真库「不动点」判据外，新增静态判据把 `docs/sql/schema.sql` 的终态与「**迁移字面量按同一四档规则塌缩**」的结果**逐 id / 逐价**比对 |
| `no_applicable_position` 相关 | **改判**：该态随 `applicable` 退场而不可达（改判登记见 `.github/cases/processing-order.yml` 的 #4939 条目）⇒ 本文件不再判它，改判在「存活行 `applicable` 恒 `TRUE`」上 |
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
V102 = MIGRATION_DIR / "V102__retire_applicability_flag.sql"
#: **已删除**的四条（内容已并入 `V102`）—— 名字写在这里，是为了让「文件又冒出来」或
#: 「账本条目没删干净」都能被机械判出来（不是「静默不判」）。
SUPERSEDED = (
    "V103__clear_route_rule_positions.sql",
    "V104__deposition_matrix_collapse.sql",
    "V105__add_sheer_variant_operations.sql",
    "V106__backfill_sheer_variant_operations.sql",
)
SCHEMA_SQL = REPO / "docs/sql/schema.sql"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"
#: 选行规则的**同一份**字面量（Java 侧常量；跨语言判据按源码解析，不靠人抄）。
QUERY_SERVICE = (REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
                 / "ProductionOperationQueryService.java")
#: 4 道纱帘变体（纱帘变体名 → 对应 `-布` 变体名 —— 单价/分组/单位/scope 都取自后者）。
SHEER_VARIANTS = (("熨烫-纱", "熨烫-布"), ("定型-纱", "定型-布"),
                  ("复烫-纱", "复烫-布"), ("车被-纱", "布帘车被"))
#: 迁移侧矩阵字面量的两个来源（bootstrap 那份 120 行字面量就是这两段拼成的）。
MATRIX_LITERAL_SOURCES = (
    "V71__normalize_routing_model_structure.sql",
    "V79__seed_fabric_route_and_packing_operation.sql",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(sql: str) -> str:
    """SQL 注释（`--` 行注释与 `/* */` 块注释）→ 空，供**写语句**判据用。

    ⚠️ 判据必须去注释：本仓的迁移文件把「回滚 SQL」「红线」都写在注释里，
    不去注释会把注释里的 `UPDATE` 当成真写语句。
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


def _versions() -> list:
    return [int(re.match(r"^V(\d+)__", p.name).group(1))
            for p in MIGRATION_DIR.glob("V*.sql") if re.match(r"^V(\d+)__", p.name)]


# ══════════════════════════ ① 存在性 / 版本号 / 账本 ══════════════════════════

def test_single_merged_migration_exists_and_the_four_superseded_files_are_gone():
    """一条在、四条不在；版本号 `102` 恰好一个；`103` ~ `106` 不再占号。

    ⚠️ **不写 `max(versions) == 102`** —— 那是本仓点名过的「自毁式真值主张」
    （下一个新增迁移一到就必红，且报错指向**错误行动**）。这里只判「四条不再存在」。
    """
    assert V102.exists(), f"缺少合并后的迁移文件：{V102.name}"
    for name in SUPERSEDED:
        assert not (MIGRATION_DIR / name).exists(), (
            f"`{name}` 仍在磁盘上 —— 它的内容已并入 `V102`（同一个 PR 一次性重写），"
            f"留着会让同一批语义跑两遍（或与 `V102` 的判据互相矛盾）")
    versions = _versions()
    assert versions.count(102) == 1, f"V102 版本号重复（{versions.count(102)} 个）"
    for gone in (103, 104, 105, 106):
        assert gone not in versions, f"V{gone} 的版本号又被占用了（已合并进 V102，不得复活）"


def test_published_migrations_are_untouched():
    """已发布迁移**只许新增**：`V71` / `V72` / `V79` / `V86` / `V88` / `V89` / `V97` 逐个仍在且指纹仍在账本里。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    for name in ("V71__normalize_routing_model_structure.sql",
                 "V72__switch_routing_model_consumers.sql",
                 "V79__seed_fabric_route_and_packing_operation.sql",
                 "V86__create_operation_position_price_versions.sql",
                 "V88__retire_material_prep_and_fabric_position.sql",
                 "V89__backfill_fabric_seed_for_existing_tenants.sql",
                 "V97__soft_delete_orphan_operation_positions.sql"):
        assert name in ledger, f"已发布迁移 {name} 的指纹不在账本里（账本被改过？）"


def test_new_migration_is_registered_in_the_fingerprint_ledger():
    ledger = json.loads(_read(LEDGER))["migrations"]
    assert V102.name in ledger, (
        f"`{V102.name}` 未被登记进 `migration_fingerprints.json` ⇒ 它以后能被静默改（issue #4235）")


def test_superseded_migrations_are_absent_from_the_ledger():
    """「删文件 = 绕过」的机械判据：账本里**不得**残留这四条的条目（否则不可变判据 3 会红）。"""
    ledger = json.loads(_read(LEDGER))["migrations"]
    for name in SUPERSEDED:
        assert name not in ledger, (
            f"账本里仍有 `{name}` 的指纹条目，而磁盘上该文件已删 ⇒ "
            f"`test_migration_immutability.py` 的「条目指向已消失文件」判据会红")


def test_ledger_comment_records_the_one_off_justification():
    """账本的 `_comment` 必须写清「这次一次性改动」的正当性（证据 + 用户裁定原文）。

    本单**确实**改了已登记文件的指纹并删了 4 条条目 —— 那不是「刷新一下就好」，
    而是「这五条从未在任何环境成功应用」的一次性收口。正当性必须**落在账本里**（可被评审看见），
    而不是只活在 PR 描述里（PR 会关，账本会一直跟着代码）。
    """
    comment = json.loads(_read(LEDGER)).get("_comment", "")
    assert comment, "账本缺 `_comment`：这次「改 V102 + 删四条」的正当性没有任何落点"
    for needle, why in (("从未在任何环境成功应用", "缺「从未成功应用」这一核心事实"),
                        ("2026-09-20", "缺云测试环境启动日志的日期证据"),
                        ("MigrationRunner", "缺「迁移失败被跳过 ⇒ 静默失败」的证据载体"),
                        ("测试数据", "缺用户裁定原文的引用（「这些都是测试数据，不要怕搞坏」）")):
        assert needle in comment, f"账本 `_comment` {why}（`{needle}`）"
    for name in SUPERSEDED:
        assert name.split("__")[0] in comment, f"账本 `_comment` 没点名 {name.split('__')[0]}"


# ══════════════════════════ ② 静态判据：写语句形态 ══════════════════════════

def test_header_records_why_the_five_migrations_can_be_merged():
    """文件头必须**逐字**留下「为什么可以合并重写」的立论（读它的人不必去翻 PR）。"""
    body = _read(V102)
    for needle in ("从未在任何环境成功应用", "2026-09-20", "测试数据", "不要怕搞坏",
                   "V103", "V104", "V105", "V106", "已作废", "唯一载体"):
        assert needle in body, f"V102 文件头缺 `{needle}`（合并的立论不完整）"


def test_v102_has_no_timestamp_based_judgement():
    """🔴 **上版死因的机械判据**：文件**正文**（去注释后）不得出现 `created_at` 与时间戳比较。

    上版的收尾守卫按 `updated_at > created_at` 推断「谁被改动过」——它只说明这一行**历史上**
    被改过（商家改价等），**与本迁移无关** ⇒ 存量里有一行就把整条迁移判死、整份回滚
    （并拖垮同批的另外四条）。⇒ 正文里连 `created_at` 这个列名都不该出现
    （判据只读状态：收敛度 / 取值集 / 计数）。
    """
    body = _strip_comments(_read(V102))
    assert "created_at" not in body, (
        "V102 的正文里出现了 `created_at` ⇒ 又回到「按时间戳推断谁被改动」那条死路上去了"
        "（它会把历史上被商家改过的存量行误判成「本迁移越界」并整份回滚）")
    assert "updated_at >" not in body and "> updated_at" not in body, "正文字面量里仍有时间戳比较"


def test_v102_never_touches_production_route_rules():
    """🔴 **#4962 口径**：部位维只活在 `production_route_rules.position` 上 ⇒ `V102` **一字不碰**该表。

    改判理由：`V103`（清空规则 `position`）的意图**已作废**（用户裁定「结合新的需求（#4962
    适用条件加回部位维）统一考量」）⇒ 删除该文件即撤销它；`V102` 里**不该**出现该表名、
    `customer_unit_price` 更不该出现。
    """
    body = _strip_comments(_read(V102))
    assert "production_route_rules" not in body, (
        "V102 的正文里出现了 `production_route_rules` ⇒ 它动了部位维的载体"
        "（#4962 要把部位维加回来：该表的数据**一字不能动**，清空意图已随 `V103` 删除而作废）")
    assert "customer_unit_price" not in body, (
        "V102 的正文里出现了 `customer_unit_price` ⇒ 它动了对客那本账（元/套），与「部位」无关")
    assert "DROP COLUMN" not in body.upper(), (
        "V102 不得删列（矩阵的 `applicable` / `position` 两列的「值恒定 + 读面不消费」是收口口径，"
        "物理删列留给后续统一审计）")


def test_v102_treats_null_applicable_as_not_true():
    """🔴 **NULL 口径的机械判据**：幸存判据必须写 `(p.applicable IS TRUE)`，**不得**写 `IS NOT FALSE`。

    `applicable IS NOT FALSE` 对 `NULL` 求值为 `TRUE` ⇒ NULL 行会被当成「已经是 TRUE」放行
    （云库里确实存在 `applicable IS NULL` 的存活行 —— 上版的第二处口径错误）。
    真库红证 = `test_null_applicable_rows_do_not_kill_the_migration`。
    """
    body = _strip_comments(_read(V102))
    assert "(p.applicable IS TRUE) DESC" in body, \
        "V102 的 ① 档不是 `(p.applicable IS TRUE)` ⇒ NULL 行的排序位不明确"
    assert "IS NOT FALSE" not in body, (
        "V102 里出现 `IS NOT FALSE` —— 它会把 `applicable IS NULL` 放行（上版的 NULL 口径错误）")


def test_v102_materialises_the_survivor_set_before_any_write():
    """🔴 **先算幸存集，再动手**（否则 `帘头制作` 的 ¥2.00 会静默丢失，#4696 家族）。

    判据 = `CREATE TEMP TABLE _v102_survivors` 的位置**严格早于**第一条写矩阵的 UPDATE
    （先改 `applicable` 或先软删，选行所依赖的「迁移前信号」就没了），
    且写语句与收尾自证**共用**同一份物化结果（`FROM _v102_survivors` 至少三处引用）。
    """
    body = _strip_comments(_read(V102))
    materialise = body.index("CREATE TEMP TABLE _v102_survivors")
    first_write = body.index("UPDATE production_operation_positions")
    assert materialise < first_write, (
        "V102 先写了矩阵才物化幸存集 ⇒ 选行信号已被自己抹掉"
        "（`帘头制作` 的 ¥2.00 会静默丢失，真库判据见 "
        "`test_survivor_keeps_the_priced_curtain_head_and_never_invents_a_price`）")
    assert body.count("FROM _v102_survivors") >= 3, (
        "物化结果只被引用了一处 ⇒ 写语句/自证没有真正共享它（判据可能只漂一半）")


def test_v102_uses_the_four_tier_survivor_rule_in_the_same_order():
    """四档选行序**逐档**在 SQL 里出现且顺序与 Java / Python 一致（不得改名换序）。"""
    body = _strip_comments(_read(V102))
    order = re.search(r"ORDER BY([\s\S]*?)\n\s*\)\s*AS rn", body)
    assert order, "V102 里找不到 `ORDER BY … ) AS rn`（选行规则的落点被搬走了？）"
    text = order.group(1)
    tiers = [("(p.applicable IS TRUE) DESC", "① 适用行优先（NULL 按非 TRUE）"),
             ("(p.position = '布帘') DESC", "② 布帘列优先"),
             ("COALESCE(p.position, '')", "③ position 字典序"),
             ("COALESCE(p.id, '')", "④ id 升序")]
    positions = []
    for needle, label in tiers:
        at = text.find(needle)
        assert at >= 0, f"V102 的选行规则缺档：{label}（`{needle}`）"
        positions.append((at, label))
    assert positions == sorted(positions), f"V102 的四档顺序被打乱：{positions}"
    assert 'COLLATE "C"' in text, (
        'V102 的 ③/④ 档没有 `COLLATE "C"` —— Java 的末档是 `String.compareTo`（逐字节），'
        "非 C collation 的库会选出**不同**的幸存行")


def test_v102_soft_deletes_and_never_physically_deletes_nor_resurrects():
    """软删红线：非幸存行写 `deleted = 1` + `updated_at`；**不物理删**；**从不写 `deleted = 0`**。"""
    body = _strip_comments(_read(V102))
    assert re.search(r"SET\s+deleted\s*=\s*1\s*,\s*updated_at\s*=\s*NOW\(\)", body), \
        "V102 的软删不是「显式写 deleted + updated_at」"
    assert "DELETE FROM production_operation_positions" not in body.upper(), (
        "🔴 V102 物理删了矩阵行 —— `V86` 的调价账按 `position_row_id` 指向它们，物理删会断审计链")
    for set_clause in re.findall(r"SET([\s\S]*?)WHERE", body):
        assert not re.search(r"\bdeleted\s*=\s*0\b", set_clause), (
            f"🔴 V102 的 SET 子句里出现 `deleted = 0` ⇒ 它把软删行**复活**了"
            f"（红线：只许软删，不许复活）：{set_clause.strip()[:200]}")


def test_v102_writes_the_neutral_position_and_keeps_the_price():
    body = _strip_comments(_read(V102))
    assert re.search(r"SET\s+position\s*=\s*'通用'", body), \
        "V102 没把幸存行的 position 写成中性值「通用」"
    survivors_update = re.search(
        r"UPDATE production_operation_positions p\s*SET position = '通用'[\s\S]*?;", body)
    assert survivors_update, "找不到「幸存行写中性部位」那条语句"
    stmt = survivors_update.group(0)
    assert "unit_price" not in stmt, (
        "🔴 幸存行那条 UPDATE 碰了 `unit_price` —— 塌缩**只选行、不改价**（#4696：未定价不得被回落）")
    assert re.search(r"applicable\s*=\s*TRUE", stmt), (
        "幸存行那条 UPDATE 没把 `applicable` 收敛成 `TRUE`（终态要求：存活行一律适用）")


def test_v102_declares_the_sheer_variant_ids_by_the_tenant_scoped_rule():
    """纱帘变体的命名规则：`op-v102-<tenant_id>-<序号>`（**自带租户段**），且**不复用**别人的 id。"""
    body = _strip_comments(_read(V102))
    assert "'op-v102-' || t.id::text || '-' || r.seq::text" in body, (
        "派生回填段的 id 不是「自带租户段」的规则（`'op-v102-' || <tenant_id> || '-' || <序号>`）")
    for seq in range(1, 5):
        assert f"'op-v102-1-{seq}'" in body, f"字面量种子段缺 `op-v102-1-{seq}`（1 号租户的第 {seq} 道）"
    assert "op-v56-06" not in body and "op-v56-07" not in body, (
        "🔴 V102 复用了 1 号租户既有的 `op-v56-06..09` id（那是别的迁移的命名空间）—— "
        "id 是按租户唯一的")
    for sheer, _cloth in SHEER_VARIANTS:
        assert f"'{sheer}'" in body, f"V102 缺纱帘变体 `{sheer}`"


def test_v102_literal_seed_block_is_gated_and_the_derived_block_loops_tenants():
    """字面量段**带同一套闸门**（不无中生有）；派生段**按租户循环** + 逐行幂等去重 + 取自 `-布` 行。

    字面量段为什么必须存在（**不是冗余**）：`test_production_catalog_seed.py` 的多源收敛守卫按**内容**
    发现「含 `INSERT INTO production_operations` 且形如 `VALUES`」的迁移源 ⇒ 只留派生形态会让那
    4 道落在比对射程之外（改价没有任何东西变红）。
    """
    body = _strip_comments(_read(V102))
    literal = re.search(r"INSERT INTO production_operations[\s\S]*?\bVALUES\b[\s\S]*?ON CONFLICT "
                        r"\(tenant_id, name\) WHERE deleted = 0 DO NOTHING;", body)
    assert literal, ("V102 里没有「字面量 `VALUES` + `ON CONFLICT … DO NOTHING`」的工序种子段 ⇒ "
                     "多源收敛守卫看不到这 4 道（射程外）")
    assert "DO $$" in body[:literal.start()], (
        "字面量种子段没有被 `DO` 块包住 ⇒ 它对「`-布` 不齐」的租户也会插行（无中生有）")
    # 派生段：按租户循环 + 逐行 NOT EXISTS + ON CONFLICT + 逐列取 `-布` 行
    derived = re.search(r"INSERT INTO production_operations[\s\S]*?\bSELECT\b[\s\S]*?DO NOTHING;",
                        body[literal.end():])
    assert derived, "V102 缺派生回填段（非 1 号租户的 4 道 `-纱` 全靠它）"
    text = derived.group(0)
    assert "FROM tenants t" in text and "NOT EXISTS" in text and "ON CONFLICT" in text, (
        f"派生回填段的形态不完整（须含 `FROM tenants t` / `NOT EXISTS` / `ON CONFLICT`）：{text[:300]}")
    assert re.search(r"JOIN production_operations s\b", text), (
        "🔴 派生段的单价/分组/单位/scope 不是**逐字取对应 `-布` 变体那一行**"
        "（缺 `JOIN production_operations s`）—— 那就成了「发明单价」")


def test_v102_is_explicitly_transactional():
    body = _read(V102)
    assert re.search(r"^BEGIN;", body, re.M), "V102 缺显式 `BEGIN;`"
    assert re.search(r"^COMMIT;", body, re.M), "V102 缺显式 `COMMIT;`"
    assert "RAISE EXCEPTION" in body, "V102 缺数量对账 / 自证（`RAISE EXCEPTION`）"


def test_v102_documents_the_rollback():
    """回滚 SQL 必须**完整**（本仓迁移硬要求）：复活软删行 / `通用` 改回原部位 / `-纱` 按 id 前缀认领。"""
    body = _read(V102)
    assert "回滚 SQL" in body, "V102 缺「回滚 SQL」段"
    tail = body[body.index("回滚 SQL"):]
    for needle, why in (("deleted = 0", "缺「复活软删行」的语句"),
                        ("通用", "缺「把 `通用` 改回原部位」的语句"),
                        ("'op-v102-%'", "缺「按 id 前缀认领 `-纱` 变体」的语句"),
                        ("不可逆", "缺「哪些信息不可逆」的如实登记"),
                        ("v102_run_at", "缺「认领本迁移软删行」的执行时刻"
                                        "（否则会误复活更早的退场记录）")):
        assert needle in tail, f"V102 的回滚段{why}（`{needle}`）"


def test_java_collapse_source_position_matches_the_sql_literal():
    """跨语言：SQL 的 `'布帘'` 与 Java 的 `COLLAPSE_PRICE_SOURCE_POSITION` **逐字同值**。"""
    src = _read(QUERY_SERVICE)
    m = re.search(r'COLLAPSE_PRICE_SOURCE_POSITION\s*=\s*"([^"]+)"', src)
    assert m, "Java 侧找不到 `COLLAPSE_PRICE_SOURCE_POSITION` 的字面量"
    body = _strip_comments(_read(V102))
    assert f"(p.position = '{m.group(1)}') DESC" in body, (
        f"V102 的「布帘列优先」档不是 Java 的 `{m.group(1)}` —— 两侧会选出不同的幸存行")
    assert "'通用'" in body, "V102 的中性值必须与「三部位 + 布料」都不撞"


def test_java_neutral_position_matches_the_sql_literal():
    """跨语言：SQL 的 `'通用'` 与 Java 的 `COLLAPSE_NEUTRAL_POSITION` **逐字同值**（issue #5008）。

    读面靠这个值**认出塌缩终态**并回落到「取价同一行」（布帘列）解析变体元数据；
    两侧一旦漂移，库里只有变体名的那些工序会**再次静默丢分组/单位**（没有任何东西会因此变红）。
    """
    src = _read(QUERY_SERVICE)
    m = re.search(r'COLLAPSE_NEUTRAL_POSITION\s*=\s*"([^"]+)"', src)
    assert m, "Java 侧找不到 `COLLAPSE_NEUTRAL_POSITION` 的字面量"
    neutral = m.group(1)
    assert neutral not in ("布帘", "纱帘", "帘头", "布料"), (
        f"中性值 `{neutral}` 与真实部位撞车 ⇒ 读面会把真实部位误判成塌缩终态")
    assert f"SET position = '{neutral}'" in _strip_comments(_read(V102)), (
        f"V102 写的幸存行 position 不是 Java 的 `{neutral}` ⇒ 读面认不出塌缩终态")
    assert f"'{neutral}'" in _read(SCHEMA_SQL), (
        f"`docs/sql/schema.sql` 的矩阵终态里没有 `{neutral}`（bootstrap 路径不跑迁移链）")


# ══════════════════════════ ③ 真库判据（临时 PG 集群） ══════════════════════════


#: 与 `V71` / `V79` / `V86` 同形的**最小** DDL（本单触碰的几张表 + 部分唯一索引 + 调价账 + 快照表）。
#: ⚠️ `applicable` **可空**（`BOOLEAN DEFAULT TRUE`，**没有** `NOT NULL`）：云测试环境实测存在
#: `applicable IS NULL` 的存活行（上版死因之一就是 NULL 口径）⇒ 夹具必须能造出那个形态。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operation_positions (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    logical_name VARCHAR(64) NOT NULL, position VARCHAR(16) NOT NULL,
    unit_price NUMERIC(10,2), applicable BOOLEAN DEFAULT TRUE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_operation_positions_tenant_name_position
    ON production_operation_positions (tenant_id, logical_name, position) WHERE deleted = 0;
CREATE TABLE production_route_rules (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(16) NOT NULL, trigger_value VARCHAR(64) NOT NULL,
    position VARCHAR(16), action VARCHAR(16) NOT NULL, operation VARCHAR(64),
    after_operation VARCHAR(64), priority INTEGER NOT NULL DEFAULT 0,
    customer_unit_price NUMERIC(10,2),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL, group_name VARCHAR(32), position VARCHAR(16),
    unit VARCHAR(16), unit_price NUMERIC(10,2),
    is_must_finish BOOLEAN DEFAULT FALSE, is_start_marker BOOLEAN DEFAULT FALSE,
    sort_order INTEGER DEFAULT 0, scope VARCHAR(16) DEFAULT 'position',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_operations_tenant_name
    ON production_operations (tenant_id, name) WHERE deleted = 0;
CREATE TABLE production_operation_position_price_versions (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, position_row_id VARCHAR(64),
    unit_price NUMERIC(10,2), created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE processing_position_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_work_logs (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), deleted INTEGER NOT NULL DEFAULT 0);
"""

#: 真库矩阵/规则夹具。每个 `(tenant_id, logical_name)` 都为一个**具体的判据**而设，逐条注明：
#:   · `三边`      —— ① 档（适用行优先）：TRUE + 有价的布帘格胜出；
#:   · `帘头制作`  —— **承重格**：布帘格 `(NULL, FALSE)` vs 帘头格 `(2.00, TRUE)` ⇒ 幸存行必须是 2.00；
#:   · `打包`      —— ② 档候选：两个格都是 TRUE（价都 NULL），② 档「布帘列优先」决定谁活；
#:   · `熨烫`      —— 🔴 **`applicable IS NULL`** 的承重格：NULL 行 `(布帘, 0.35)` vs TRUE 行 `(帘头, 0.99)`
#:                   ⇒ NULL **必须**按「非 TRUE」处理（否则 NULL 行会靠 ② 档胜出、价变 0.35）；
#:   · `定型`      —— NULL 是**唯一**候选 ⇒ 仍被选为幸存行，且终态 `applicable` 收敛成 TRUE（价 0.50 保住）；
#:   · `韩褶`      —— ② 档「布帘列优先」的**判别力**：`外帘` 在 C collation 下排在 `布帘` **之前**
#:                   ⇒ 抹掉 ② 档，幸存行会换成 `外帘`（价 0.99）；
#:   · `t1-retired` —— **已软删**行（更早的退场留痕；本迁移**不碰**）。
_SEED = """
INSERT INTO tenants (id) VALUES (1), (2);
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, deleted) VALUES
    ('t1-sandian-bu',   1, '三边', '布帘', 0.40, TRUE,  0),
    ('t1-sandian-sha',  1, '三边', '纱帘', NULL, FALSE, 0),
    ('t1-sandian-lt',   1, '三边', '帘头', NULL, FALSE, 0),
    ('t1-ltzz-bu',      1, '帘头制作', '布帘', NULL, FALSE, 0),
    ('t1-ltzz-lt',      1, '帘头制作', '帘头', 2.00, TRUE,  0),
    ('t1-dabao-bu',     1, '打包', '布帘', NULL, TRUE, 0),
    ('t1-dabao-sha',    1, '打包', '纱帘', NULL, TRUE, 0),
    ('t1-yuntang-bu',   1, '熨烫', '布帘', 0.35, NULL,  0),
    ('t1-yuntang-lt',   1, '熨烫', '帘头', 0.99, TRUE,  0),
    ('t1-dingxing-sha', 1, '定型', '纱帘', 0.50, NULL,  0),
    ('t1-hanzhe-bu',    1, '韩褶', '布帘', 0.40, TRUE, 0),
    ('t1-hanzhe-wl',    1, '韩褶', '外帘', 0.99, TRUE, 0),
    ('t1-retired',      1, '配料', '布料', NULL, TRUE, 1),
    ('t2-sandian-bu',   2, '三边', '布帘', 0.40, TRUE,  0),
    ('t2-sandian-sha',  2, '三边', '纱帘', 0.40, FALSE, 0),
    ('t2-ltzz-lt',      2, '帘头制作', '帘头', 2.00, TRUE, 0),
    ('t2-yuntang-bu',   2, '熨烫', '布帘', 0.30, NULL,  0);
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation,
     after_operation, priority, customer_unit_price, deleted) VALUES
    ('r1-hz-car',  1, 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20, NULL, 0),
    ('r1-hz-hz',   1, 'craft', '韩褶', NULL,  'insert', '韩褶',  '三边', 10, NULL, 0),
    ('r1-opt-dui', 1, 'option', '拼1次', NULL, 'insert', '拼1次', '三边', 110, 12.50, 0),
    ('r2-hz-car',  2, 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20, NULL, 0);
INSERT INTO production_operation_position_price_versions
    (id, tenant_id, position_row_id, unit_price) VALUES
    ('pv-1', 1, 't1-sandian-bu', 0.40),
    ('pv-2', 1, 't1-sandian-sha', 0.10);
INSERT INTO processing_position_operations (id, tenant_id, operation_name, unit_price, factor) VALUES
    ('inst-1', 1, '布三边', 0.40, 1.000);
INSERT INTO production_work_logs (id, tenant_id, operation_name, unit_price, factor) VALUES
    ('wl-1', 1, '布三边', 0.40, 1.000);
"""

#: 4 个租户覆盖「补 / 不补」的全部形态：
#:   1 号 = `-布` 齐（**走字面量段**）+ 一条**已软删**的 `熨烫-纱`（商家删的，红线：不许复活）；
#:   2 号 = `-布` 齐（**走派生段**），且**单价/分组/单位/scope 故意与字面量不同**
#:          ⇒ 「逐字取对应 `-布` 行」与「发明单价」当场可分；
#:   3 号 = 只有 1 个 `-布`（闸门①不成立）⇒ **一行都不插**；
#:   4 号 = **空工序库**（不无中生有）⇒ **一行都不插**。
_SHEER_SEED = """
INSERT INTO tenants (id) VALUES (1), (2), (3), (4);
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price, scope, deleted) VALUES
    ('t1-bu-1', 1, '熨烫-布', '后道', '布帘', '米', 0.35, 'position', 0),
    ('t1-bu-2', 1, '定型-布', '后道', '布帘', '米', 0.40, 'position', 0),
    ('t1-bu-3', 1, '复烫-布', '后道', '布帘', '米', 0.35, 'position', 0),
    ('t1-bu-4', 1, '布帘车被', '后道', NULL, '米', 0.40, 'position', 0),
    ('t1-merchant-deleted', 1, '熨烫-纱', '后道', '纱帘', '米', 0.35, 'position', 1),
    ('t2-bu-1', 2, '熨烫-布', '车位', '布帘', '个', 1.23, 'set', 0),
    ('t2-bu-2', 2, '定型-布', '车位', '布帘', '个', 4.56, 'set', 0),
    ('t2-bu-3', 2, '复烫-布', '车位', '布帘', '个', 7.89, 'set', 0),
    ('t2-bu-4', 2, '布帘车被', '车位', NULL, '个', 3.21, 'set', 0),
    ('t3-bu-1', 3, '熨烫-布', '后道', '布帘', '米', 0.35, 'position', 0);
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def psql(tmp_path, realdb_binaries):
    """临时 PG 集群（unix socket，不占 TCP 端口）；退出时停库删目录。"""
    datadir = tmp_path / "pgdata"
    # ⚠️ socket 目录必须**短**：unix socket 路径有 ~104 字节上限。
    sockdir = Path(tempfile.mkdtemp(prefix="pg4937-"))
    log = tmp_path / "pg.log"
    subprocess.run([realdb_binaries["initdb"], "-D", str(datadir), "-U", "postgres", "-A", "trust"],
                   check=True, capture_output=True)
    port = _free_port()
    started = subprocess.run(
        [realdb_binaries["pg_ctl"], "-D", str(datadir), "-l", str(log), "-o",
         f"-k {sockdir} -p {port} -c listen_addresses=''", "start"],
        capture_output=True, text=True)
    assert started.returncode == 0, (
        f"临时集群起不来：{started.stdout}\n{started.stderr}\n"
        f"{log.read_text(encoding='utf-8') if log.exists() else ''}")

    def run(sql: str) -> str:
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            [realdb_binaries["psql"], "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
             "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)

    run.raw = psql_raw

    try:
        yield run
    finally:
        subprocess.run([realdb_binaries["pg_ctl"], "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


#: 把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义。
#: ⚠️ 迁移文件内另有自己的 `BEGIN; … COMMIT;` ⇒ 外层再包一层会得到 PG 的
#: `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
_TX = "BEGIN;\n{body}\nCOMMIT;\n"


def _as_runner_would(sql: str) -> str:
    return _TX.format(body=sql)


def _migration() -> str:
    return _read(V102)


def _seed(run) -> None:
    run(_DDL + _SEED)


def _table_fingerprint(run, table: str) -> str:
    """整表逐字节指纹（**全部列**，按 `id` 排序）—— 用于「一字不动」类红线。"""
    out = run(f"SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM (SELECT * FROM {table}) t;")
    return out.strip()


def _fingerprint(run, table: str, columns: str) -> str:
    out = run(f"SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM "
              f"(SELECT {columns} FROM {table}) t;")
    return out.strip()


def _all_rows(run) -> list:
    out = run("SELECT id || ':' || deleted FROM production_operation_positions ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def _rows_of(run, where: str) -> list:
    out = run(f"SELECT id FROM production_operation_positions WHERE {where} ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def _survivor_of(run, tenant_id: int, logical_name: str) -> str:
    """某个 `(租户, 逻辑工序)` 的幸存行 → `id|价|applicable`。"""
    return run("SELECT id || '|' || COALESCE(unit_price::text,'NULL') || '|' || applicable::text "
               "FROM production_operation_positions "
               f"WHERE deleted = 0 AND tenant_id = {tenant_id} "
               f"AND logical_name = '{logical_name}';").strip()


#: 「**迁移前**状态上独立重算幸存行」的期望表（判据独立于迁移实现：同一份四档规则、
#: 但读的是**迁移前**的 `applicable`/`position`）—— 写进一张真实表以免随之消失。
_EXPECT_SURVIVORS = """
CREATE TABLE _expect_survivors AS
SELECT id, tenant_id, logical_name, unit_price
  FROM (SELECT p.*,
               ROW_NUMBER() OVER (
                   PARTITION BY p.tenant_id, p.logical_name
                   ORDER BY (p.applicable IS TRUE) DESC, (p.position = '布帘') DESC,
                            COALESCE(p.position,'') COLLATE "C" ASC,
                            COALESCE(p.id,'') COLLATE "C" ASC) AS rn
          FROM production_operation_positions p
         WHERE p.deleted = 0) q
 WHERE q.rn = 1;
"""

_HISTORY_TABLES = {
    "processing_position_operations": "id, tenant_id, operation_name, unit_price, factor, deleted",
    "production_work_logs": "id, tenant_id, operation_name, unit_price, factor, deleted",
    "production_operation_position_price_versions":
        "id, tenant_id, position_row_id, unit_price, deleted",
}


# ── 真库判据 1（本文件核心）：跑两遍 ⇒ 幂等 + 塌缩到不动点 + 与独立重算逐行一致 ──

def test_migration_is_idempotent_and_collapses_to_one_row_per_logical_operation(psql):
    """真库跑**两遍**，净效果相同；每 `(租户, 逻辑工序)` 恰好 1 行存活，且与**独立重算**逐行相等。"""
    _seed(psql)
    before = _all_rows(psql)
    assert "t1-sandian-sha:0" in before and "t1-ltzz-bu:0" in before, "红证前提不成立：种子没落库"
    assert len(before) == 17, f"种子行数 = {len(before)}，期望 17（t1 13 + t2 4）"

    # 在**迁移前**的状态上独立重算期望幸存行（判据不读迁移实现，只在同一份四档规则上）
    psql(_EXPECT_SURVIVORS)

    psql(_as_runner_would(_migration()))            # 第一遍
    after_first = _all_rows(psql)
    psql(_as_runner_would(_migration()))            # 第二遍（幂等）
    after_second = _all_rows(psql)

    assert after_first == after_second, (
        f"V102 **不幂等**：第二遍改了净效果\n  第一遍后：{after_first}\n  第二遍后：{after_second}")

    alive = int(psql("SELECT count(*) FROM production_operation_positions WHERE deleted = 0;").strip())
    retired = int(psql("SELECT count(*) FROM production_operation_positions WHERE deleted = 1;").strip())
    # ── 真库两遍幂等读数（PR 证据直接引这段输出） ──
    print(f"[#4937 真库 · 合并后的单条 V102] 改前矩阵行 = {len(before)} 行")
    print(f"[#4937 真库] 第 1 遍后 = {after_first}")
    print(f"[#4937 真库] 第 2 遍后（幂等） = {after_second}")
    print(f"[#4937 真库] 第 1 遍 == 第 2 遍 ⇒ {after_first == after_second}")
    print(f"[#4937 真库] 存活 = {alive} / 退场 = {retired} / 总 = "
          f"{psql('SELECT count(*) FROM production_operation_positions;').strip()}")
    print(f"[#4937 真库] 存活行 position 取值集 = "
          f"{psql('SELECT string_agg(DISTINCT position, chr(44)) FROM production_operation_positions WHERE deleted = 0;').strip()}")
    print(f"[#4937 真库] 存活行 applicable 取值集 = "
          f"{psql('SELECT string_agg(DISTINCT applicable::text, chr(44)) FROM production_operation_positions WHERE deleted = 0;').strip()}")
    print(f"[#4937 真库] 矩阵指纹（id:deleted）= "
          f"{psql('SELECT md5(string_agg(id || chr(58) || deleted, chr(44) ORDER BY id)) FROM production_operation_positions;').strip()}")
    print(f"[#4937 真库] 帘头制作(1 号租户)的幸存行 = {_survivor_of(psql, 1, '帘头制作')}"
          f"（期望 `t1-ltzz-lt|2.00|true` —— 未定价不得被回落，issue #4696）")

    assert alive == 9 and retired == 8 and alive + retired == 17, (
        f"存活/退场对账不符：存活 {alive}（期望 9）/ 退场 {retired}（期望 8）/ 总 17")
    # 每个 (tenant, logical_name) 恰好一行存活
    per_key = psql("SELECT tenant_id || '|' || logical_name || '|' || count(*) "
                   "FROM production_operation_positions WHERE deleted = 0 "
                   "GROUP BY tenant_id, logical_name ORDER BY 1;")
    rows = [line for line in per_key.splitlines() if line.strip()]
    assert len(rows) == 9, f"存活键数 = {len(rows)}，期望 9（判据空跑？）"
    bad = [r for r in rows if not r.endswith("|1")]
    assert bad == [], f"以下 (租户, 逻辑工序) 的存活行数 ≠ 1：{bad}"

    # 🔴 幸存行 = **迁移前状态下独立重算**的期望集合（逐 id / 逐价）
    expected = [line for line in psql(
        "SELECT id || '|' || COALESCE(unit_price::text,'NULL') "
        "FROM _expect_survivors ORDER BY tenant_id, logical_name;").splitlines() if line.strip()]
    got = [line for line in psql(
        "SELECT id || '|' || COALESCE(unit_price::text,'NULL') "
        "FROM production_operation_positions WHERE deleted = 0 ORDER BY tenant_id, logical_name;"
    ).splitlines() if line.strip()]
    assert len(expected) == 9, f"期望幸存行 = {len(expected)}，期望 9"
    assert got == expected, (
        f"塌缩后的存活行 ≠ 在**迁移前**状态上独立重算的四档选行结果（`id|价`）：\n"
        f"  独立重算 = {expected}\n  迁移结果 = {got}")

    # 幸存行的 position 全部是中性值「通用」+ applicable = TRUE
    weird = psql("SELECT count(*) FROM production_operation_positions "
                 "WHERE deleted = 0 AND (position <> '通用' OR applicable IS NOT TRUE);")
    assert weird.strip() == "0", f"仍有 {weird.strip()} 条存活行的 position/applicable 不是终态"


def test_survivor_keeps_the_priced_curtain_head_and_never_invents_a_price(psql):
    """🔴 承重判据：`帘头制作` 的幸存行必须是**有价的帘头格（2.00）**，且价不丢、不被回落成 NULL/0。

    形态：`布帘 (NULL, FALSE)` / `帘头 (2.00, TRUE)`。若「先改 `applicable` 再选行」或「一刀切置 TRUE」
    ⇒ ① 档失效 ⇒ 决胜落到 ② 档「布帘列优先」⇒ 幸存行 = `布帘 / NULL` = **未定价** ⇒ ¥2.00 静默消失。
    """
    _seed(psql)
    fp_before = _fingerprint(psql, "production_operation_positions", "id, unit_price")
    psql(_as_runner_would(_migration()))

    assert _survivor_of(psql, 1, "帘头制作") == "t1-ltzz-lt|2.00|true", (
        f"`帘头制作` 的幸存行 = `{_survivor_of(psql, 1, '帘头制作')}`，期望 `t1-ltzz-lt|2.00|true`"
        f" —— 价丢了（工人白干，issue #4696）")
    assert _survivor_of(psql, 2, "帘头制作") == "t2-ltzz-lt|2.00|true", "2 号租户同款承重格丢了"
    # 价目**逐字节指纹不变**（塌缩只选行、不改价）
    assert _fingerprint(psql, "production_operation_positions", "id, unit_price") == fp_before, \
        "🔴 V102 改了矩阵的 `unit_price` —— 塌缩只选行、不改价"
    # 未定价必须仍是 NULL（不得被回落成 0.00 —— 与「显式 0 元」不可区分）
    assert _survivor_of(psql, 1, "打包") == "t1-dabao-bu|NULL|true", (
        f"`打包` 的幸存行 = `{_survivor_of(psql, 1, '打包')}`，期望未定价的布帘格（② 档产物）")
    # 已软删行（更早的退场留痕）**一字未动**
    assert "t1-retired:1" in _all_rows(psql), "V102 碰了已软删行（那是更早迁移的退场留痕）"


def test_null_applicable_rows_do_not_kill_the_migration(psql):
    """🔴 **`applicable IS NULL` 不致命**（上版的第二处死因），且 NULL 按「非 TRUE」参与选行。

    两条判据：
      ① 库里有 `applicable IS NULL` 的**存活**行时，迁移必须**成功跑完**（不抛、不整份回滚）；
      ② NULL 必须被当作**非 TRUE**：`熨烫` 的 NULL 格（布帘 / 0.35）不得靠 ② 档胜出，
         幸存行必须是 TRUE 的帘头格（0.99）；NULL 是**唯一**候选时仍被选为幸存行并收敛成 TRUE。
    """
    _seed(psql)
    nulls_before = _rows_of(psql, "applicable IS NULL AND deleted = 0")
    assert nulls_before == ["t1-dingxing-sha", "t1-yuntang-bu", "t2-yuntang-bu"], (
        f"红证前提不成立：改前 `applicable IS NULL` 的存活行 = {nulls_before}，期望 3 条")

    psql(_as_runner_would(_migration()))          # 不抛 = 第 ① 条判据成立

    assert _survivor_of(psql, 1, "熨烫") == "t1-yuntang-lt|0.99|true", (
        f"`熨烫` 的幸存行 = `{_survivor_of(psql, 1, '熨烫')}` —— NULL 行靠 ② 档胜出了 ⇒ "
        f"NULL 被当成了 TRUE（上版的 NULL 口径错误）")
    assert _survivor_of(psql, 1, "定型") == "t1-dingxing-sha|0.50|true", (
        f"`定型` 的幸存行 = `{_survivor_of(psql, 1, '定型')}`，期望 `t1-dingxing-sha|0.50|true`"
        f"（NULL 唯一候选 ⇒ 仍活，且终态收敛 applicable）")
    assert _survivor_of(psql, 2, "熨烫") == "t2-yuntang-bu|0.30|true", (
        f"2 号租户 `熨烫` 的幸存行 = `{_survivor_of(psql, 2, '熨烫')}`"
        f"（NULL 唯一候选 ⇒ 仍活，价 0.30 保住）")
    assert psql("SELECT count(*) FROM production_operation_positions "
                "WHERE deleted = 0 AND applicable IS NOT TRUE;").strip() == "0", \
        "迁移后仍有存活行的 applicable 不是 TRUE（NULL/FALSE 的终态收敛没生效）"
    assert "t1-yuntang-bu:1" in _all_rows(psql), "NULL 的非幸存行没被软删"
    print(f"[#4937 真库 · NULL 不致命] 改前 NULL 存活行 = {nulls_before}；"
          f"改后 熨烫 = {_survivor_of(psql, 1, '熨烫')} / 定型 = {_survivor_of(psql, 1, '定型')} / "
          f"2 号熨烫 = {_survivor_of(psql, 2, '熨烫')}")


def test_route_rules_are_byte_identical(psql):
    """🔴 **#4962 口径**：`V102` 对 `production_route_rules` **整表逐字节不动**（部位维保留）。

    改判前的判据是「`V103` 把 `position` 清空 ⇒ 改后 0 行非 NULL」；`V103` 的意图已作废
    ⇒ 现在判的是**反面且更强**的一格：整表（含 `position` / `customer_unit_price` /
    `updated_at` / `deleted` **全部列**）跑完 `V102` 后**指纹一字不变**，且那 2 条非 NULL 的
    `position` **仍在**（谁把它清掉即红）。
    """
    _seed(psql)
    nonnull_before = psql("SELECT count(*) FROM production_route_rules "
                          "WHERE deleted = 0 AND position IS NOT NULL;").strip()
    assert nonnull_before == "2", f"改前带 position 的规则 = {nonnull_before}，期望 2（红证前提）"
    fp_before = _table_fingerprint(psql, "production_route_rules")
    count_before = psql("SELECT count(*) FROM production_route_rules;").strip()

    psql(_as_runner_would(_migration()))

    assert _table_fingerprint(psql, "production_route_rules") == fp_before, (
        "🔴 V102 动了 `production_route_rules` —— 部位维（`position`）是 #4962 的**唯一载体**，"
        "本迁移对该表必须一字不碰（含 `customer_unit_price` 与行数）")
    assert psql("SELECT count(*) FROM production_route_rules "
                "WHERE deleted = 0 AND position IS NOT NULL;").strip() == nonnull_before, (
        "V102 把规则级 `position` 清掉了 ⇒ 部位维被抹（`V103` 的意图已作废，不得复活）")
    assert psql("SELECT count(*) FROM production_route_rules;").strip() == count_before, \
        "V102 增删了规则行 —— 它对该表必须零操作"


def test_history_and_the_repricing_ledger_are_byte_identical(psql):
    """红线：`V86` 调价账 / 工序实例 / 报工流水 逐字节指纹前后相同。"""
    _seed(psql)
    before = {t: _fingerprint(psql, t, cols) for t, cols in _HISTORY_TABLES.items()}
    assert all(v for v in before.values()), f"改前指纹取不到（判据会空跑）：{before}"

    psql(_as_runner_would(_migration()))

    after = {t: _fingerprint(psql, t, cols) for t, cols in _HISTORY_TABLES.items()}
    assert after == before, (
        f"红线被破：历史/账本指纹变了\n  改前：{before}\n  改后：{after}\n"
        "（调价账按 `position_row_id` 指向矩阵行 —— 塌缩只软删，行仍在）")
    rows = psql("SELECT (SELECT count(*) FROM production_operation_position_price_versions) || '/' || "
                "(SELECT count(*) FROM processing_position_operations) || '/' || "
                "(SELECT count(*) FROM production_work_logs);").strip()
    assert rows == "2/1/1", f"历史/账本行数变了：{rows}"


# ══════════════════════════ ④ 纱帘变体（多租户真库判据） ══════════════════════════

def _sheer_rows(psql, tenant_id: int) -> dict:
    """某租户的 4 道 `-纱` 变体（存活）→ `{纱帘变体名: (id, 价, 部位, 分组, 单位, scope)}`。

    ⚠️ 按 `name` 建**字典**而不是按行序比对：`ORDER BY name` 依赖库的 collation
    （CJK 在不同 locale 下顺序不同）⇒ 行序断言会变成**假红**源；字典逐键比对与 collation 无关。
    """
    out = psql("SELECT name || '|' || id || '|' || unit_price::text || '|' "
               "|| COALESCE(position,'NULL') || '|' || COALESCE(group_name,'NULL') || '|' "
               "|| COALESCE(unit,'NULL') || '|' || COALESCE(scope,'NULL') "
               "FROM production_operations "
               f"WHERE tenant_id = {tenant_id} AND deleted = 0 "
               "AND name IN ('熨烫-纱','定型-纱','复烫-纱','车被-纱');")
    rows = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        name, rid, price, pos, grp, unit, scope = line.split("|")
        rows[name] = (rid, price, pos, grp, unit, scope)
    return rows


def test_sheer_variants_are_backfilled_per_tenant_and_gated(psql):
    """真库（**多租户**）：`-布` 齐的租户拿到 4 行；空库 / 部分库租户**一行都不插**；两遍幂等。

    🔴 单价/分组/单位/scope 必须**逐字取对应 `-布` 行**：夹具里 2 号租户的 `-布` 值
    （车位 / 个 / 1.23 · 4.56 · 7.89 · 3.21 / scope=set）**故意与 1 号租户的字面量不同**
    ⇒ 「逐字取 `-布` 行」与「发明一个字面量价」当场可分。
    """
    psql(_DDL)
    psql(_SHEER_SEED)

    psql(_as_runner_would(_migration()))
    first = {t: _sheer_rows(psql, t) for t in (1, 2, 3, 4)}
    psql(_as_runner_would(_migration()))          # 第二遍（幂等）
    second = {t: _sheer_rows(psql, t) for t in (1, 2, 3, 4)}

    print("[#4937 真库 · V102 纱帘变体多租户读数]")
    for t in (1, 2, 3, 4):
        print(f"  tenant_id={t} 的 4 个 -纱 变体 = {first[t]}")

    assert first == second, f"纱帘段**不幂等**：第二遍改了净效果\n  第一遍：{first}\n  第二遍：{second}"
    # 1 号租户（走字面量段）
    assert set(first[1]) == {s for s, _c in SHEER_VARIANTS}, f"1 号租户缺行：{sorted(first[1])}"
    assert [first[1][s][0] for s, _c in SHEER_VARIANTS] == [f"op-v102-1-{i}" for i in (1, 2, 3, 4)], (
        f"1 号租户的行 id 不是 `op-v102-1-<序号>`：{first[1]}")
    assert {v[2] for v in first[1].values()} == {"纱帘"}, f"部位标识必须是「纱帘」：{first[1]}"
    assert [first[1][s][1] for s, _c in SHEER_VARIANTS] == ["0.35", "0.40", "0.35", "0.40"], (
        f"1 号租户（字面量段）的单价不是冻结的种子价：{first[1]}")
    # 2 号租户（走派生段）：🔴 逐字取对应 `-布` 行
    assert set(first[2]) == {s for s, _c in SHEER_VARIANTS}, f"2 号租户缺行：{sorted(first[2])}"
    assert all(v[0].startswith("op-v102-2-") for v in first[2].values()), (
        f"id 未自带租户段（2 号）：{first[2]}")
    assert {v[1] for v in first[2].values()} == {"1.23", "3.21", "4.56", "7.89"}, (
        f"🔴 单价不是**逐字取对应 `-布` 变体**（夹具里 2 号租户的 -布 价 = "
        f"1.23 / 3.21 / 4.56 / 7.89）⇒ 迁移**发明了单价**：{first[2]}")
    assert [first[2][s][1] for s, cloth in SHEER_VARIANTS] == ["1.23", "4.56", "7.89", "3.21"], (
        f"单价的「哪一道取哪一行 `-布`」对应关系错了：{first[2]}")
    assert {v[3] for v in first[2].values()} == {"车位"}, f"分组没与 `-布` 行对齐：{first[2]}"
    assert {v[4] for v in first[2].values()} == {"个"}, f"单位没与 `-布` 行对齐：{first[2]}"
    assert {v[5] for v in first[2].values()} == {"set"}, f"scope 没与 `-布` 行对齐：{first[2]}"
    # 3 号（只有 1 个 `-布`）/ 4 号（空工序库）⇒ 一行都不插（不无中生有）
    assert first[3] == {}, f"3 号租户（只有 1 个 `-布`）被插了行 ⇒ 闸门①（4 个齐）没生效：{first[3]}"
    assert first[4] == {}, (
        f"4 号租户（**空工序库**）被插了行 ⇒ 无中生有（工序库从未种过的租户必须整块跳过）：{first[4]}")


def test_sheer_backfill_is_not_scoped_to_tenant_one(psql):
    """🔴 **红证（可执行）**：让「`-布` 齐」的租户只有 **2 号** ⇒ 它必须被补上。

    这条专钉「字面量只种 `tenant_id = 1`」的缺陷形态：
    把「`-布` 齐」的租户换成 2 号，字面量写法会**一行都不补** ⇒ 该租户的纱帘单照样 422 ⇒ 本判据当场红。
    """
    psql(_DDL)
    psql("INSERT INTO tenants (id) VALUES (1), (2);")
    psql("INSERT INTO production_operations (id, tenant_id, name, group_name, position, unit, unit_price) "
         "VALUES ('t2-bu-1', 2, '熨烫-布', '后道', '布帘', '米', 0.35), "
         "('t2-bu-2', 2, '定型-布', '后道', '布帘', '米', 0.40), "
         "('t2-bu-3', 2, '复烫-布', '后道', '布帘', '米', 0.35), "
         "('t2-bu-4', 2, '布帘车被', '后道', NULL, '米', 0.40);")

    psql(_as_runner_would(_migration()))
    rows = _sheer_rows(psql, 2)
    print(f"[#4937 真库 · 非 1 号租户读数] tenant_id=2 的 4 个 -纱 变体 = {rows}")
    assert len(rows) == 4, (
        f"**非 1 号租户**没被 backfill（只补 tenant_id = 1 的写法会让它一行都不插）"
        f"⇒ 该租户的纱帘单会 422 整单中止：{rows}")
    assert all(v[0].startswith("op-v102-2-") for v in rows.values()), f"id 未自带租户段：{rows}"


def test_sheer_backfill_reconciliation_blocks_a_missing_row(psql):
    """红证（真库）：注入「闸门①恒假」（**部分租户拿不到行**）⇒ 收尾对账 `RAISE EXCEPTION` + 整份回滚。

    注入形态 = 把派生段闸门①的 `= 4` 改成 `= 5`（只改**写语句**的闸门，不改收尾判据 ⇒ 判据漂移）。
    """
    psql(_DDL)
    psql(_SHEER_SEED)
    before = psql("SELECT count(*) FROM production_operations;").strip()

    sql = _migration()
    injected = sql.replace("AND b.name IN ('熨烫-布', '定型-布', '复烫-布', '布帘车被')) = 4\n"
                           "   -- 闸门②",
                           "AND b.name IN ('熨烫-布', '定型-布', '复烫-布', '布帘车被')) = 5\n"
                           "   -- 闸门②", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    assert proc.returncode != 0, (
        f"该补的租户一行没补时对账竟通过了 ⇒ 数量对账是空断言\nstderr={proc.stderr}")
    assert "数量对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
    assert psql("SELECT count(*) FROM production_operations;").strip() == before, (
        "对账抛异常后工序库行数却变了 ⇒ 没有回滚（半完成态）")


def test_sheer_backfill_reconciliation_detects_a_partial_backfill(psql):
    """红证（真库）：**部分补种**（只补 1 道）⇒ 对账必须红（「四元组计数」判据的判别力）。"""
    psql(_DDL)
    psql(_SHEER_SEED)
    sql = _migration()
    # 注入：把 CROSS JOIN 的派生表裁到只剩 1 行（模拟「部分补种」）
    injected = sql.replace("      UNION ALL SELECT '定型-纱', '定型-布', 39, 2\n"
                           "      UNION ALL SELECT '复烫-纱', '复烫-布', 40, 3\n"
                           "      UNION ALL SELECT '车被-纱', '布帘车被', 41, 4\n", "", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    assert proc.returncode != 0, (
        f"只补 1 道时对账竟通过了 ⇒ 判据对「部分补种」无判别力\nstderr={proc.stderr}")
    assert "数量对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
    assert _sheer_rows(psql, 1) == {} and _sheer_rows(psql, 2) == {}, (
        "对账抛异常后却留下了半完成态（有租户被补了 1 道）")


def test_sheer_backfill_never_resurrects_a_soft_deleted_variant(psql):
    """红线（真库）：商家**软删过** `熨烫-纱` ⇒ 本迁移**永不把它复活**（`deleted` 保持 1）。

    形态：1 号租户 4 个 `-布` 齐 + 一条**已软删**的 `熨烫-纱`（商家删的）。
    闸门②只数 `deleted = 0`（= 0）⇒ 本迁移会补 4 行（其中 `熨烫-纱` 是新行）；
    **商家那一行一字不动**（`deleted` 仍是 1、`id` 不变）。
    """
    psql(_DDL)
    psql(_SHEER_SEED)

    psql(_as_runner_would(_migration()))
    rows = _sheer_rows(psql, 1)
    print(f"[#4937 真库 · 软删红线] 1 号租户存活 = {rows}")
    assert len(rows) == 4, f"闸门②（只数 deleted = 0）应生效 ⇒ 补 4 行，实际 {rows}"
    survived = psql("SELECT id || '|' || deleted::text FROM production_operations "
                    "WHERE id = 't1-merchant-deleted';").strip()
    assert survived == "t1-merchant-deleted|1", (
        f"商家软删的那一行被改动了（应保持 id 不变、deleted = 1）：{survived}")
    # 幂等 + 该租户历史上 2 行 `熨烫-纱`（1 软删 + 1 存活）
    psql(_as_runner_would(_migration()))
    total = psql("SELECT count(*) FROM production_operations WHERE tenant_id = 1 "
                 "AND name = '熨烫-纱';").strip()
    assert total == "2", f"第二遍不该再插（历史软删 1 行 + 本次 1 行 = 2），实际 {total}"


def test_sheer_backfill_fails_loud_when_only_one_variant_is_missing(psql):
    """已知边界（**真库红证，照实登记**）：某租户「3 行在 + 1 行被软删」⇒ 对账**整份回滚**。

    这是**有意**的取舍：`NOT EXISTS` 永不写已存在的行、也永不复活软删行 ⇒ 那一行**补不上**
    ⇒ 让对账 fail-loud（红在下一次 `verify-all`），而**不是**把该租户留成「纱帘单恒 422」的死状态。
    补那一行的正确做法 = 新开一条单行 `NOT EXISTS` 迁移（不碰软删行），不在本文件射程内。
    """
    psql(_DDL)
    psql("INSERT INTO tenants (id) VALUES (1);")
    psql("INSERT INTO production_operations "
         "(id, tenant_id, name, group_name, position, unit, unit_price, deleted) "
         "VALUES ('t1-bu-1', 1, '熨烫-布', '后道', '布帘', '米', 0.35, 0), "
         "('t1-bu-2', 1, '定型-布', '后道', '布帘', '米', 0.40, 0), "
         "('t1-bu-3', 1, '复烫-布', '后道', '布帘', '米', 0.35, 0), "
         "('t1-bu-4', 1, '布帘车被', '后道', NULL, '米', 0.40, 0), "
         "('t1-1', 1, '熨烫-纱', '后道', '纱帘', '米', 0.35, 0), "
         "('t1-2', 1, '定型-纱', '后道', '纱帘', '米', 0.40, 0), "
         "('t1-3', 1, '复烫-纱', '后道', '纱帘', '米', 0.35, 0), "
         "('t1-4', 1, '车被-纱', '后道', '纱帘', '米', 0.40, 1);")
    before = psql("SELECT count(*) FROM production_operations;").strip()

    proc = psql.raw(_as_runner_would(_migration()))
    print(f"[#4937 真库 · 已知边界] 回滚 = {proc.returncode != 0}；"
          f"stderr 含对账 = {'数量对账失败' in proc.stderr}")
    assert proc.returncode != 0, (
        "「3 行在 + 1 行软删」时本迁移静默跳过（不插也不抛）⇒ 该租户的纱帘单会**恒 422** "
        "而没有任何东西变红（正是本单要治的形态）")
    assert "数量对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
    assert psql("SELECT count(*) FROM production_operations;").strip() == before, (
        "对账抛异常后工序库行数却变了 ⇒ 没有回滚（半完成态）")


# ══════════════════════ ⑤ 注入式红证：判据有判别力（不是空断言） ══════════════════════

def test_reconciliation_blocks_a_partial_matrix_write(psql):
    """红证（真库）：软删语句**漏做一行**（判据漂移）⇒ 收尾自证 `RAISE EXCEPTION` ⇒ 整份回滚。

    注入 = 把 `t1-ltzz-bu` 排除在软删之外（它本该被软删）⇒ S1「塌缩未收敛」当场红。
    """
    _seed(psql)
    before = _all_rows(psql)
    sql = _migration()
    injected = sql.replace("   AND NOT EXISTS (SELECT 1 FROM _v102_survivors s WHERE s.id = p.id);",
                           "   AND p.id <> 't1-ltzz-bu'\n"
                           "   AND NOT EXISTS (SELECT 1 FROM _v102_survivors s WHERE s.id = p.id);", 1)
    assert injected != sql, "注入「漏删」没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    assert proc.returncode != 0, (
        f"写语句漏删时自证竟未拦下 ⇒ 停止条件是空断言\nstdout={proc.stdout}\nstderr={proc.stderr}")
    assert "塌缩未收敛" in proc.stderr, f"拦下的不是收敛判据：{proc.stderr[:400]}"
    assert _all_rows(psql) == before, "自证抛异常后矩阵行却变了 ⇒ 没有回滚（半完成态）"


def test_first_tier_is_load_bearing_for_the_null_and_false_cells(psql):
    """红证（真库）：把 ① 档（`applicable IS TRUE` 优先）注入成恒定假 ⇒ 幸存行换人。

    正常口径下 `熨烫` 的幸存行 = TRUE 的帘头格（0.99）；抹掉 ① 档后落到 ② 档「布帘列优先」
    ⇒ 换成 **NULL/未适用**的布帘格（0.35）—— 这证明那一档**真的在承重**，
    也证明「NULL 按非 TRUE 处理」不是碰巧（NULL 行没有靠 ② 档胜出）。
    """
    _seed(psql)
    sql = _migration()
    injected = sql.replace("(p.applicable IS TRUE) DESC,", "FALSE DESC,", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"

    psql(_as_runner_would(_migration()))
    assert _survivor_of(psql, 1, "熨烫") == "t1-yuntang-lt|0.99|true", "正常口径下的基线不成立"
    assert _survivor_of(psql, 1, "帘头制作") == "t1-ltzz-lt|2.00|true", "正常口径下的基线不成立"

    # 复原（把上一轮软删的行救回），再注入
    psql("UPDATE production_operation_positions SET deleted = 0 WHERE tenant_id IN (1, 2);")
    psql(_as_runner_would(injected))
    assert _survivor_of(psql, 1, "熨烫") == "t1-yuntang-bu|0.35|true", (
        f"抹掉 ① 档后 `熨烫` 的幸存行 = `{_survivor_of(psql, 1, '熨烫')}`，期望 NULL 的布帘格"
        f"（0.35）—— 说明该档在承重")
    assert _survivor_of(psql, 1, "帘头制作") == "t1-ltzz-bu|NULL|true", (
        f"抹掉 ① 档后 `帘头制作` 的幸存行 = `{_survivor_of(psql, 1, '帘头制作')}`，期望"
        f"布帘列的未定价格（NULL）—— 反过来证明正常口径的 `2.00` 不是碰巧")


def test_second_tier_is_load_bearing_against_the_c_collation_order(psql):
    """红证（真库）：把 ② 档（`position = '布帘'` 优先）注入成恒定假 ⇒ 幸存行换人。

    `韩褶` 的两个格都是 TRUE 且有价，`外帘` 在 `COLLATE "C"`（逐字节）下**排在 `布帘` 之前**
    ⇒ 抹掉 ② 档后 ③ 档会选出 `外帘`（0.99）。这证明 ② 档**不是装饰**。
    """
    _seed(psql)
    sql = _migration()
    injected = sql.replace("(p.position = '布帘') DESC,", "FALSE DESC,", 1)
    assert injected != sql, "注入没生效 ⇒ 本红证是空断言"

    psql(_as_runner_would(_migration()))
    assert _survivor_of(psql, 1, "韩褶") == "t1-hanzhe-bu|0.40|true", (
        f"正常口径下 `韩褶` 的幸存行 = `{_survivor_of(psql, 1, '韩褶')}`，期望布帘格")

    psql("UPDATE production_operation_positions SET deleted = 0 WHERE tenant_id = 1;")
    psql(_as_runner_would(injected))
    got = _survivor_of(psql, 1, "韩褶")
    assert got == "t1-hanzhe-wl|0.99|true", (
        f"抹掉 ② 档后 `韩褶` 的幸存行 = `{got}`，期望 `外帘` 行（③ 档 `COLLATE \"C\"` 的产物）"
        f"—— 否则该档是装饰（判据无判别力）")


# ══════════════════════ ⑥ bootstrap 镜像 ↔ 迁移链终态 ══════════════════════

#: 矩阵行字面量（迁移侧无 `deleted` 列；bootstrap 侧多一列 `status` 与 `deleted` ⇒ 两个可选组）。
_MATRIX_ROW_RE = re.compile(
    r"\(\s*'(?P<id>opp-[^']*)'\s*,\s*(?P<tenant>\d+)\s*,\s*'(?P<lg>[^']*)'\s*,\s*'(?P<pos>[^']*)'\s*,"
    r"\s*(?P<price>NULL|[\d.]+)\s*,\s*(?P<ap>TRUE|FALSE)\s*"
    r"(?:,\s*'[^']*'\s*)?(?:,\s*(?P<del>\d+)\s*)?\)")


def _matrix_rows(sql: str) -> list:
    """从「`INSERT INTO production_operation_positions (列清单) VALUES …`」段抽出矩阵行。"""
    rows = []
    for m in re.finditer(
            r"INSERT\s+INTO\s+production_operation_positions\s*\([^)]*\)\s*VALUES([\s\S]*?)"
            r"(?:ON\s+CONFLICT|;)", sql, re.I):
        rows += [r.groupdict() for r in _MATRIX_ROW_RE.finditer(m.group(1))]
    return rows


def _collapse_source_position() -> str:
    """四档规则第 ② 档的字面量（Java 侧常量 —— 不靠人抄）。"""
    m = re.search(r'COLLAPSE_PRICE_SOURCE_POSITION\s*=\s*"([^"]+)"', _read(QUERY_SERVICE))
    assert m, "Java 侧找不到 `COLLAPSE_PRICE_SOURCE_POSITION` 的字面量"
    return m.group(1)


def _four_tier_survivors(rows: list) -> dict:
    """四档选行（**与迁移同序**，在测试侧独立实现）：`(tenant, 逻辑工序)` → 幸存行。"""
    grouped: dict = {}
    for r in rows:
        grouped.setdefault((r["tenant"], r["lg"]), []).append(r)
    src = _collapse_source_position()

    def rank(r):
        return (0 if r["ap"] == "TRUE" else 1,
                0 if r["pos"] == src else 1,
                r["pos"], r["id"])

    return {k: sorted(v, key=rank)[0] for k, v in grouped.items()}


def test_bootstrap_matrix_terminal_equals_the_four_tier_collapse_of_the_migration_literals():
    """🔴 **静态强判据**：`docs/sql/schema.sql` 的矩阵终态 == 迁移字面量按四档规则塌缩的结果。

    口径：bootstrap 是 `docker-entrypoint-initdb.d` 的**单租户建库脚本**（**不跑迁移链**）
    ⇒ 它必须**一次给全终态**。迁移侧的**字面量**来源 = `V71` ∪ `V79`（bootstrap 那 120 行
    就是这两段拼成的，行集合由 `test_public_ops_v88_migration.py` 的 id 集合判据另钉）。
    ⇒ 比对**逐 row id / 逐价**：
      · bootstrap 的存活矩阵行 == 对字面量按四档规则选出的幸存行（**连物理行 id 都相同**）；
      · bootstrap 的退场行 == 其余全部（120 − 30 = 90）；
      改任一侧（价 / 部位 / `applicable` / `deleted` / 幸存行选择）都会红。
    """
    literals = []
    for name in MATRIX_LITERAL_SOURCES:
        literals += _matrix_rows(_read(MIGRATION_DIR / name))
    assert len(literals) == 120, f"迁移字面量解析出 {len(literals)} 行，期望 120"
    assert {r["del"] for r in literals} == {None}, (
        "迁移字面量里出现了 `deleted` 列 ⇒ 解析口径变了（迁移侧的字面量没有该列）")
    assert {r["tenant"] for r in literals} == {"1"}, "迁移字面量不止一个租户（bootstrap 是单租户脚本）"

    boot = _matrix_rows(_read(SCHEMA_SQL))
    assert len(boot) == 120, f"bootstrap 的矩阵字面量解析出 {len(boot)} 行，期望 120"
    assert {r["del"] for r in boot} <= {"0", "1"} and None not in {r["del"] for r in boot}, (
        "bootstrap 的矩阵行必须显式带 `deleted` 列（退场只能靠显式标记表达，不能删行）")

    survivors = _four_tier_survivors(literals)
    assert len(survivors) == 30, f"字面量按四档塌缩出 {len(survivors)} 行，期望 30"
    live = {r["id"]: r for r in boot if r["del"] == "0"}
    dead = {r["id"] for r in boot if r["del"] == "1"}

    assert set(live) == {r["id"] for r in survivors.values()}, (
        f"bootstrap 的存活行集合 ≠ 四档选出的幸存行集合：\n"
        f"  仅 bootstrap 存活 = {sorted(set(live) - {r['id'] for r in survivors.values()})}\n"
        f"  仅四档选中 = {sorted({r['id'] for r in survivors.values()} - set(live))}")
    assert len(live) == 30 and len(dead) == 90, f"存活 {len(live)} / 退场 {len(dead)}，期望 30 / 90"
    assert set(live) | dead == {r["id"] for r in literals}, (
        "bootstrap 的行集合 ≠ 迁移字面量的行集合（行整个消失 / 凭空多出）⇒ 两条口径不可比对")

    for key, row in sorted(survivors.items()):
        b = live[row["id"]]
        assert b["price"] == row["price"], (
            f"`{key[1]}` 的幸存行（`{row['id']}`）价不一致：bootstrap = `{b['price']}`，"
            f"迁移字面量 = `{row['price']}`")
        assert b["lg"] == row["lg"], f"幸存行 `{row['id']}` 的逻辑工序名漂移"
        assert b["pos"] == "通用", (
            f"bootstrap 里 `{key[1]}` 的存活行部位 = `{b['pos']}`，期望中性值 `通用`")
        assert b["ap"] == "TRUE", f"bootstrap 里 `{key[1]}` 的存活行 `applicable` 不是 TRUE"
    print("[#4937 · bootstrap 矩阵终态 ↔ 迁移字面量四档塌缩] "
          f"120 行 → 存活 {len(live)} / 退场 {len(dead)}；逐 id 逐价一致")


def test_bootstrap_matches_migration_chain_terminal_state(psql):
    """真库：`docs/sql/schema.sql` 的矩阵段是 `V102` 的**不动点**，且逐值等于真库终态。

    本测试把 `schema.sql` 的矩阵**字面量**当输入喂进真库，再跑本迁移 ⇒
    终态必须与 `schema.sql` **自己写的那份终态**逐值相等（防两条口径分裂：bootstrap 栈不跑迁移链）。
    ⚠️ 比对按**逻辑工序**（`unit_price` / `applicable` / `deleted`）+ 「存活行的 `position` 一律 `通用`」
    —— 因为本迁移的**产物**就是「每逻辑工序一行、部位写中性值」，拿 `(逻辑工序, 部位)` 做键是「拿终态比旧键」。
    ⚠️ 这条判的是**不动点**（终态投进去不变）；「终态 == 迁移字面量塌缩的结果」由上面那条**静态**判据钉。
    """
    schema = _read(SCHEMA_SQL)
    boot_sql = _schema_matrix_sql(schema)
    # ⚠️ 行数自证要读**整份** `schema.sql`（`boot_sql` 是喂库用的片段，右边界刻意止于
    # `ON CONFLICT` 之前 ⇒ 它没有语句终止符，不是本解析器的输入形态）。
    assert len(_matrix_rows(schema)) == 120, (
        f"schema.sql 的矩阵字面量解析出 {len(_matrix_rows(schema))} 行，期望 120")

    psql(_DDL + "INSERT INTO tenants (id) VALUES (1);")
    psql(boot_sql)
    seeded = psql("SELECT count(*) FROM production_operation_positions;").strip()
    assert seeded == "120", f"schema.sql 的 120 行没真插进去（实际 {seeded}）⇒ 本判据会空跑"

    psql(_as_runner_would(_migration()))

    chain_alive = {}
    for line in psql("SELECT logical_name || '|' || COALESCE(unit_price::text,'NULL') || '|' "
                     "|| applicable::text || '|' || position FROM production_operation_positions "
                     "WHERE deleted = 0 AND tenant_id = 1 ORDER BY logical_name;").splitlines():
        if line.strip():
            lg, price, ap, pos = line.split("|")
            chain_alive[lg] = (price, ap, pos)
    chain_deleted = {l.split("|")[0] for l in
                     psql("SELECT logical_name FROM production_operation_positions "
                          "WHERE deleted = 1 AND tenant_id = 1;").splitlines() if l.strip()}

    boot_alive, boot_deleted = _schema_terminal_state(schema)

    def norm(values):
        """形态归一：`schema.sql` 写的是字面量（`0.4` / `TRUE`），真库回读是 `NUMERIC(10,2)` 的定标
        形式（`0.40`）与 psql 的小写布尔（`true`）—— 不归一会把「同一份数据两种书写」误判成漂移。"""
        out = []
        for x in values:
            if x == "NULL":
                out.append("NULL")
            elif x.lower() in ("true", "false"):
                out.append(x.lower())
            else:
                try:
                    out.append("%.2f" % float(x))
                except ValueError:
                    out.append(x)          # 中性部位 `通用` 等文本
        return tuple(out)

    boot_alive = {k: norm(v) for k, v in boot_alive.items()}
    chain_alive = {k: norm(v) for k, v in chain_alive.items()}
    assert set(chain_alive) == set(boot_alive), (
        f"存活**逻辑工序集合**分裂：仅迁移链有 = {sorted(set(chain_alive) - set(boot_alive))}，"
        f"仅 bootstrap 有 = {sorted(set(boot_alive) - set(chain_alive))}")
    assert len(chain_alive) == 30, f"迁移链终态的存活逻辑工序 = {len(chain_alive)}，期望 30"
    assert len(chain_deleted) == 30, (
        f"迁移链终态被软删的逻辑工序 = {len(chain_deleted)}，期望 30（120 行 = 30 逻辑工序 × 4 部位）")
    drift = {k: (boot_alive[k], chain_alive[k]) for k in chain_alive if boot_alive[k] != chain_alive[k]}
    assert drift == {}, f"逐逻辑工序（价/适用/部位）分裂（前 = bootstrap，后 = 迁移链）：{drift}"
    assert {v[2] for v in chain_alive.values()} == {"通用"}, (
        f"迁移链终态的存活行 position 不是全 `通用`：{sorted({v[2] for v in chain_alive.values()})}")
    assert {v[1] for v in chain_alive.values()} == {"true"}, (
        f"迁移链终态的存活行 applicable 不是全 TRUE：{sorted({v[1] for v in chain_alive.values()})}")
    deleted_rows = psql("SELECT count(*) FROM production_operation_positions WHERE deleted = 1;").strip()
    assert deleted_rows == "90", f"退场行 = {deleted_rows}，期望 90（120 − 30）"
    assert set(chain_deleted) == set(chain_alive), (
        f"软删逻辑工序集合 ≠ 存活集合：仅软删 = {sorted(set(chain_deleted) - set(chain_alive))}，"
        f"仅存活 = {sorted(set(chain_alive) - set(chain_deleted))}")
    assert len(chain_alive) + int(deleted_rows) == 120, "存活 30 + 退场 90 必须 = 120（可机械核验）"
    # ── 真库读数（PR 证据直接引这段输出） ──
    print("[#4937 真库 · schema.sql 120 行字面量跑合并后的 V102]")
    print(f"  存活 = {len(chain_alive)} 行 / 退场 = {deleted_rows} 行 / 总 = "
          f"{psql('SELECT count(*) FROM production_operation_positions;').strip()} 行")
    print(f"  存活行的 position 取值集 = {sorted({v[2] for v in chain_alive.values()})}")
    print(f"  存活行的 applicable 取值集 = {sorted({v[1] for v in chain_alive.values()})}")
    print(f"  有价工序 = {sum(1 for v in chain_alive.values() if v[0] != 'NULL')} / "
          f"未定价工序 = {sum(1 for v in chain_alive.values() if v[0] == 'NULL')}")


def _schema_matrix_sql(sql: str) -> str:
    """schema.sql 的矩阵种子段 → 可**直接喂进真库**的 DDL/DML 文本（含列名）。

    ⚠️ 只取 `INSERT … VALUES` 部分（**丢掉** `ON CONFLICT (id) DO NOTHING`）：
    本测试的真库表是**空的**，先自证「120 行真插进去了」再跑迁移（防空跑）。
    """
    start = sql.index("INSERT INTO production_operation_positions\n"
                      "    (id, tenant_id, logical_name, position, unit_price, applicable, status, deleted)")
    end = sql.index("ON CONFLICT (id) DO NOTHING;", start)
    return sql[start:end]


def _schema_terminal_state(sql: str) -> tuple:
    """schema.sql 里的终态 → `(存活 {逻辑工序: (价, 适用, 部位)}, 退场逻辑工序集合)`。"""
    alive, deleted = {}, set()
    for r in _matrix_rows(sql):
        if r["del"] == "1":
            deleted.add(r["lg"])
        else:
            assert r["lg"] not in alive, f"schema.sql 里逻辑工序 `{r['lg']}` 有多个存活行 ⇒ 终态未塌缩"
            alive[r["lg"]] = (r["price"], r["ap"], r["pos"])
    return alive, deleted


def _schema_alive_matrix_rows(schema: str) -> list:
    """`schema.sql` 矩阵字面量里的**存活行**（`deleted = 0`）→ `[(id, logical, position, price)]`。"""
    return [(r["id"], r["lg"], r["pos"], r["price"]) for r in _matrix_rows(schema) if r["del"] == "0"]


def test_collapsed_matrix_judgement_detects_a_resurrected_cell():
    """红证（静态）：把一行**已软删**的矩阵格改成存活 ⇒ 存活行数判据必红。

    钉的是上面两条 bootstrap 判据的**判别力**：它们断言「bootstrap 的存活行 = 30」——
    本红证证明「复活一格」这个漂移**真的**会被照出来，不是恒真的空断言。
    """
    schema = _read(SCHEMA_SQL)
    alive = _schema_alive_matrix_rows(schema)
    assert len(alive) == 30, f"bootstrap 的存活矩阵行 = {len(alive)}，期望 30（红证前提不成立）"
    assert len({r[1] for r in alive}) == 30, "存活行应恰好 30 个逻辑工序（一工序一行）"

    # 复活一格：找一条**已软删**的矩阵行，把它的 `deleted` 由 1 改成 0（逐字节替换，
    # 不用正则做替换 —— 行形态里有 8 列，正则容易在引号/逗号上失手）
    dead = re.search(r"  \('(opp-v(?:70|79)-\d+)', 1, '([^']*)', '([^']*)', (?:NULL|[\d.]+), "
                     r"(?:TRUE|FALSE), 'active', 1\),", schema)
    assert dead, "bootstrap 里找不到任何已软删的矩阵行 ⇒ 红证前提不成立"
    row_text = dead.group(0)
    injected = schema.replace(row_text, row_text.replace("'active', 1)", "'active', 0)"), 1)
    assert injected != schema, "注入没生效 ⇒ 本红证是空断言"

    after = _schema_alive_matrix_rows(injected)
    assert len(after) == 31, (
        f"复活一格后存活行数 = {len(after)}（期望 31）⇒ 存活行数判据对「复活」无判别力")
    assert {r[1] for r in after} == {r[1] for r in alive}, (
        "复活同一逻辑工序的另一格 ⇒ 逻辑工序集合不变（判据的判别力落在**行数**上，不是集合上）"
        "—— 这正是本判据要说明的边界")
    # 迁移字面量侧同款：把一条**本该退场**的行改成存活 ⇒ 存活集合 ≠ 四档选中的幸存行集合
    literals = []
    for name in MATRIX_LITERAL_SOURCES:
        literals += _matrix_rows(_read(MIGRATION_DIR / name))
    survivors = {r["id"] for r in _four_tier_survivors(literals).values()}
    live_ids = {r["id"] for r in _matrix_rows(injected) if r["del"] == "0"}
    assert live_ids != survivors, "复活一格后存活集合仍等于四档幸存集 ⇒ 那条判据是空断言"
