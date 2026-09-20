# case_ids: PG-020, PG-035
"""`V97` 存量孤儿矩阵行清理（issue #4672）的**承重判据** —— 工序已软删、矩阵行仍 active。

## 病根（真库实测 2026-09-20，PG 18.3 / 阿里云 RDS `ai_customer_service`）

`production_operation_positions` 的读面（`ProductionOperationQueryService.operationPositions`）
只过滤 `tenant_id + deleted = 0 + status = 'active'`，**不看它挂的那道工序是否已软删**
⇒ 商家「建自定义工序 → 删它」之后，那一格**照旧出现在工艺项表格里**。

`#4671`（issue #4665 的写面半边）已在 `delete` / `deleteDetaching` 的**同一事务**里级联软删矩阵行
（`matchingCells()` 单一实现 + 显式写列 + 影响 0 行 fail-closed 422）⇒ **新形态不再产生孤儿**，
但**存量**孤儿无人清理。本文件钉的就是「存量那一批」被**一次性、可审计、可回滚**地收口。

## 真库读数（本单第一步，先查后做）

| 租户 | `production_operations`（`deleted = 1`） | 对应活跃矩阵行 | 判定 |
|---|---|---|---|
| 1 词元通达 | `测试22`（`scope='set'`） | **2**（`测试22 × 布帘` ¥0.20 / `测试22 × 纱帘` ¥0.30） | **孤儿** |
| 20 米高POC演示布艺 | 无 | 0 | 无存量 |
| 21 POC彩排5605 | 无 | 0 | 无存量 |

⇒ 存量孤儿 = **2 条**（全库 `deleted = 1` 的工序行只有 1 条，见上表）。

## 本文件钉的事（各有红证，互不掩盖）

0. 🔴 **口径归属（issue #4796）**：`V97` 的 `variant_map`（30 条）**不是运行期口径** ——
   运行期 `VARIANT_NAMES = variantNamesWithCurtainHead()` = 该表 **+ `headVariants()` 的 21 条帘头回落**
   （#4777 把那条隐式回落改成显式表）。差异**恰为那 21 格**（判据 1b 逐格钉住）；
   拿 V97 的 map 当运行期口径 ⇒ 帘头格被计成「**从未登记**」（判据 1c 给出该假阳性读数）；
1. **`variant_map` = V97 冻结的那 30 条**：与 `ProductionOperationQueryService.variantNames()`
   **逐条相等**（解析 Java 源码双向比对，不写死条数）—— 这是**迁移不可变**的判据，
   **不是**「与运行期一致」的判据（见 0）；
2. **写形态 = 显式写列**：`SET deleted = 1, updated_at = NOW()` —— 禁 `setDeleted(1); updateById(...)`
   （MyBatis-Plus 全局逻辑删除会把该字段从 SET 子句剔除 ⇒ 静默 no-op，issue #4608）；
3. **只软删、不物理删**：全文**没有** `DELETE FROM production_operation_positions`；
4. **判据严格**：必须同时含「期望变体名 **`deleted = 1`** 存在」与「活跃库里没有」两半 ——
   去掉前半 ⇒ 变成「按错误判据清理」，会把**V97 口径下解析不到**的格一并删掉
   （真库读数 **105 条**，帘头占绝大多数、且带商家显式价）⇒ **红证**：注入 ⇒ 必红。
   ⚠️ 「105」是 **V97 口径的读数**（判据口径的产物，不是运行期事实）：其中帘头格在
   **运行期解析得到**（回落布帘变体）⇒ 真去删它就是**静默丢弃商家的价**（判据 1c 给对比读数）；
5. **数量对账**：迁移末尾的 `DO $$ … RAISE EXCEPTION` 与写语句**共用同一份判据**
   （判据漂移 ⇒ 当场回滚）；
6. **幂等**：真库跑两次净效果相同（第二次 0 行）；
7. **不动历史**：`processing_position_operations` / `production_work_logs` 逐字节指纹前后相同
   （本迁移只写矩阵表的 `deleted` / `updated_at` 两列）。

## 真库判据（本机 PG 二进制；缺则**显式 skip**，不伪装成通过）

`test_v97_*` 用 `initdb` / `pg_ctl` / `psql` 起**临时集群**真跑迁移 —— 静态文本判据不够
（V83 的教训：文本守卫全绿而真库整份回滚）。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ⚠️ 运行期口径（`variantNameOf` **实际查的那张表**）的**唯一**载体在 `test_v91_…`（issue #4796）：
# 「同一口径只放一处」—— 本文件**不**再自己解析一份「运行期表」，只解析 **V97 冻结的那 30 条**。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v91_baseline_operations_backfill import (  # noqa: E402
    RETIRED_LOGICAL_NAMES, SCHEMA_SQL, bootstrap_row_values, canonical_matrix,
    runtime_resolve, runtime_variant_map)

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
MIGRATION = MIGRATION_DIR / "V97__soft_delete_orphan_operation_positions.sql"
V71 = MIGRATION_DIR / "V71__normalize_routing_model_structure.sql"
QUERY_SERVICE = (REPO / "backend/admin-api/src/main/java/com/migao/admin/service"
                 / "ProductionOperationQueryService.java")
SCHEMA = REPO / "docs/sql/schema.sql"

#: `variantNameOf` 的逆索引源（逐条字面量；**不推导**）。
_VARIANT_CALL = re.compile(r'variant\(\s*names\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')
#: SQL 侧的 `variant_map` 行：`('精裁', '布帘', '精裁-布'),`
_SQL_MAP_ROW = re.compile(r"\(\s*'([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)")
#: 部位值域 = V71 的三部位闭词表 + V79 的 `布料`（第 4 部位）—— 逐格比对必须覆盖全部 4 个部位。
_VARIANT_POSITIONS = ("布帘", "纱帘", "帘头", "布料")


def _strip_comments(sql: str) -> str:
    """去掉 `--` 行注释（本迁移的注释里逐字引用了判据片段 ⇒ 不剥会让正则命中注释 = 空断言）。"""
    return re.sub(r"--[^\n]*", "", sql)


def _sql_variant_map(sql: str) -> set:
    r"""SQL 侧 `variant_map(logical_name, position, variant_name) AS (VALUES …)` 的三元组集合。

    ⚠️ 列清单本身**带括号**（`(logical_name, position, variant_name)`）⇒ 正则必须显式匹配它，
    不能用 `\(([^)]*)\)`（会在**列清单的右括号**处提前收口，整段读不到 = 空断言）。

    ⚠️ 结尾**不锚**逗号：本文件的 `variant_map` 是**最后一个** CTE（后面直接是 `MERGE` / `DO`），
    锚 `,\s*` 会让判据读不到段（= 空断言）。
    """
    text = _strip_comments(sql)
    match = re.search(
        r"variant_map\s*\(\s*[^)]*\)\s*AS\s*\(\s*VALUES(.*?)\n\)",
        text, re.S | re.I)
    assert match, "读不到 `variant_map(…) AS (VALUES …)` 段 —— 判据会空跑"
    return {tuple(m) for m in _SQL_MAP_ROW.findall(match.group(1))}


def _java_variant_map() -> set:
    """Java 侧 `variantNames()` 的三元组集合（**解析源码**，不写死条数）。"""
    src = QUERY_SERVICE.read_text(encoding="utf-8")
    start = src.find("private static Map<String, Map<String, String>> variantNames()")
    assert start != -1, "`ProductionOperationQueryService.variantNames()` 找不到 —— 判据会空跑"
    # 只取该方法体（到下一个 `private static void variant(` 之前）
    end = src.find("private static void variant(", start)
    body = src[start:end if end != -1 else len(src)]
    triples = {tuple(m) for m in _VARIANT_CALL.findall(body)}
    assert triples, "`variantNames()` 里读不到任何 `variant(names, …)` 调用 —— 判据会空跑"
    return triples


# ══════════════════ 口径对齐（issue #4796）：SQL map ⇄ 运行期解析 ══════════════════
# 运行期口径的**唯一**载体 = `test_v91_…::runtime_variant_map` / `runtime_resolve`（上面已 import）：
# 「同一口径只放一处」—— 本文件只负责「V97 冻结的那 30 条」与它的**逐格差异清单**。


def _sql_map() -> dict:
    """SQL 侧 `variant_map` 的 `{(逻辑名, 部位): 变体名}`。"""
    return {(l, p): v for l, p, v in _sql_variant_map(MIGRATION.read_text(encoding="utf-8"))}


def _map_vs_runtime_diff(sql_map: dict, runtime: dict) -> dict:
    """SQL map 口径 与 运行期口径 的**逐格差异清单**（键 = 格，值 = `(SQL 侧, 运行期侧)`）。

    格域 = 两表逻辑名**并集** × 4 个部位 —— 只在「两表都有的逻辑名」上比，会漏掉
    「一侧完全没有该逻辑名」这一差异形态。
    """
    logicals = {logical for logical, _ in sql_map} | {logical for logical, _ in runtime}
    diff = {}
    for logical in sorted(logicals):
        for position in _VARIANT_POSITIONS:
            cell = (logical, position)
            if sql_map.get(cell) != runtime.get(cell):
                diff[cell] = (sql_map.get(cell), runtime.get(cell))
    return diff


def _curtain_head_fallback_cells(runtime: dict) -> set:
    """运行期表里**帘头回落**那一族格 = 「有布帘条目的逻辑名」的帘头格（**不写死 21**）。"""
    cloth = {logical for logical, position in runtime if position == "布帘"}
    return {(logical, "帘头") for logical in cloth}


# ══════════════════════ 静态判据（文本层） ══════════════════════

def test_v97_migration_exists_and_version_is_unique():
    """迁移号**现取**：V97 存在，且目录里**恰有一个** V97（禁止与已发布迁移重号）。

    ⚠️ **不断言「V97 是最高号」**（第一版那样写，本单实测被 main 前进打红）：
    main 上已有 **V98**（工人登录态，#4733）⇒ 「最高号」是**可变**断言，
    一有更新的迁移就假红。真正的判据是**同号唯一**（另有全仓守卫
    `test_migration_version_uniqueness.py` 兜底），本处只钉「V97 在、且只此一条」。
    """
    assert MIGRATION.exists(), f"缺少 {MIGRATION.name}"
    v97 = sorted(p.name for p in MIGRATION_DIR.glob("V97__*.sql"))
    assert v97 == [MIGRATION.name], (
        f"V97 号不唯一（实际 {v97}）—— 若 V97 已被别的 PR 占用，本迁移必须改号并在 PR body 说明")


def test_v97_variant_map_matches_production_code():
    """判据 1：SQL 的 `variant_map` **逐条相等**于 Java `variantNames()`（双向，不写死条数）。

    ⚠️ 这是**迁移不可变**的判据（`variantNames()` = V97 冻结的那 30 条），**不是**运行期口径 ——
    运行期 `VARIANT_NAMES = variantNamesWithCurtainHead()` 另有 21 条帘头回落（判据 1b）。
    """
    sql_map = _sql_variant_map(MIGRATION.read_text(encoding="utf-8"))
    java_map = _java_variant_map()
    assert sql_map == java_map, (
        "V97 的 variant_map 与生产代码 variantNames() 不一致（判据漂移）：\n"
        f"  SQL 多出：{sorted(sql_map - java_map)}\n"
        f"  SQL 缺失：{sorted(java_map - sql_map)}")
    assert len(java_map) == len({(a, b) for a, b, _ in java_map}), (
        "生产代码里同一 (逻辑名, 部位) 出现两条不同变体 —— 逆索引有歧义")
    # 🔴 issue #4796：这张冻结表是**运行期表**的真子集 —— 它不得凭空发明一条运行期解析不到的变体名
    sql_cells = {(l, p): v for l, p, v in sql_map}
    runtime = runtime_variant_map()
    assert set(sql_cells) < set(runtime) and all(runtime[cell] == variant
                                                 for cell, variant in sql_cells.items()), (
        "V97 的 `variant_map` 必须是运行期 `VARIANT_NAMES` 的**真子集**"
        "（多出的条目 = 冻结表在运行期表之外发明了解析，见 issue #4796）")


def test_v97_map_vs_runtime_diff_is_exactly_the_curtain_head_fallback():
    """判据 1b（issue #4796）：SQL map 与**运行期解析**的逐格差异**恰为 21 条帘头回落**。

    「差异清单」是**机器钉住**的（不是"没发现"）：任何人再拿 V97 的 map 当运行期口径，
    差异面（帘头回落）与规模都在这里被断言 ⇒ 口径分叉不会静默。
    """
    sql_map = _sql_map()
    runtime = runtime_variant_map()
    assert sql_map and runtime, "读不到口径表 —— 判据会空跑"
    diff = _map_vs_runtime_diff(sql_map, runtime)
    expected = _curtain_head_fallback_cells(runtime)
    assert expected, "运行期表里读不到帘头回落那一族格 —— 判据会空跑"
    # 🔴 issue #4937：运行期表**还多出 4 格纱帘变体**（`熨烫/定型/复烫/车被 × 纱帘`）——
    # `applicable` 过滤退场后它们会进纱帘路线，故 `sheerVariants(...)` 新增了这 4 条映射。
    # ⚠️ 它们是**第二类可解释差异**，必须逐格钉住（不许把 `expected` 放宽成一团）。
    sheer_added = {("熨烫", "纱帘"), ("定型", "纱帘"), ("复烫", "纱帘"), ("车被", "纱帘")}
    assert sheer_added <= set(runtime), (
        "运行期表里缺 issue #4937 的 4 条纱帘变体 —— 纱帘单会 fail-closed")
    print(f"[#4796] V97 map {len(sql_map)} 条 / 运行期 {len(runtime)} 条 / 逐格差异 {len(diff)} 格"
          f"（期望恰为 {len(expected)} 条帘头回落 + {len(sheer_added)} 条 #4937 纱帘变体）")
    assert set(diff) == expected | sheer_added, (
        "V97 的 map 与运行期解析的差异**不止**「帘头回落 + #4937 纱帘变体」（判据口径与运行期分叉）：\n"
        f"  多出：{sorted(set(diff) - expected - sheer_added)}\n"
        f"  缺失：{sorted((expected | sheer_added) - set(diff))}")
    cloth = {logical: variant for (logical, position), variant in runtime.items()
             if position == "布帘"}
    for (logical, position), (v97, run) in sorted(diff.items()):
        if (logical, position) in sheer_added:
            # issue #4937 的第二类差异：V97 的 map 里没有该格（它是本包新增的），
            # 运行期解析到**纱帘变体**（`熨烫-纱` 一族）⇒ 逐格钉住值。
            assert v97 is None, (
                f"`{logical}×纱帘` 在 V97 的 map 里竟有值 `{v97}` ⇒ 它不是 #4937 新增的那一族")
            assert run == f"{logical}-纱", (
                f"运行期对 `{logical}×纱帘` 的解析必须是 `{logical}-纱`，实际 `{run}`")
            continue
        assert position == "帘头", f"差异格 `{logical}×{position}` 不是帘头格 ⇒ 口径分叉"
        assert v97 is None, (
            f"`{logical}×{position}` 在 V97 的 map 里竟有值 `{v97}` ⇒ 它就不是「表未命中 ⇒ 回落裸名」形态")
        assert run == cloth[logical], (
            f"运行期对 `{logical}×{position}` 的解析必须等于它的布帘变体 `{cloth[logical]}`，"
            f"实际 `{run}`（#4777 的帘头回落 = 取布帘那一列）")
    # 除「帘头 + #4937 纱帘变体」外**零差异** —— 含 #4707 的 `裁剪 × 布料` 回落：两表**都有**（不是差异）
    logicals = {logical for logical, _ in sql_map} | {logical for logical, _ in runtime}
    others = [(logical, position) for logical in sorted(logicals)
              for position in _VARIANT_POSITIONS
              if position != "帘头" and (logical, position) not in sheer_added]
    assert all(sql_map.get(cell) == runtime.get(cell) for cell in others), (
        "帘头之外还有口径差异（例如 #4707 的布料回落只落在一份表里）："
        f"{sorted(c for c in others if sql_map.get(c) != runtime.get(c))}")
    assert ("裁剪", "布料") in sql_map and sql_map[("裁剪", "布料")] == runtime[("裁剪", "布料")], (
        "#4707 的 `裁剪 × 布料` 回落必须**两表都有**（V97 的 map 刻意含它，运行期也含）")


def test_v97_criterion_miscounts_curtain_head_cells_that_the_runtime_resolves():
    """判据 1c（issue #4796 的**假阳性读数**）：同一批格，两份口径给出不同读数。

    对象 = 规范矩阵里 `applicable = TRUE` 的格（`ProductionSeedTemplateService.CANONICAL_POSITION_PRICES`）
    × 工序库（`docs/sql/schema.sql` 的 36 行基线）：

    * **V97 口径**（30 条 map，**刻意不含**帘头回落 —— 迁移注释逐字写明）⇒ 帘头格落裸逻辑名
      ⇒ 库里没有 ⇒ 计成「**从未登记 / 解析不到**」= `#4672`「105 格」的算法；
    * **运行期口径**（`VARIANT_NAMES` = map + 21 条帘头回落）⇒ **0 格**。

    ⇒ 那份读数是**判据口径的产物**，不是运行期事实；据此去"清理"那些格 = 丢掉商家的价
    （真库 `三边 × 帘头` 带商家显式价 ¥0.10 + `applicable = TRUE`）。
    """
    library = set(bootstrap_row_values(SCHEMA_SQL.read_text(encoding="utf-8")))
    sql_map = _sql_map()
    runtime = runtime_variant_map()
    applicable = [(logical, position) for logical, position, ok in canonical_matrix()
                  if ok and logical not in RETIRED_LOGICAL_NAMES]
    assert applicable, "规范矩阵里没有 applicable 的格 —— 判据会空跑"
    v97_unresolved = sorted(f"{l}×{p}" for l, p in applicable
                            if runtime_resolve(l, p, sql_map, library) is None)
    runtime_unresolved = sorted(f"{l}×{p}" for l, p in applicable
                                if runtime_resolve(l, p, runtime, library) is None)
    print(f"[#4796] applicable 格 {len(applicable)} 个：V97 口径「解析不到」{len(v97_unresolved)} 个 "
          f"{v97_unresolved} / 运行期口径 {len(runtime_unresolved)} 个 {runtime_unresolved}")
    assert runtime_unresolved == [], (
        f"运行期口径下 applicable 格竟解析不到：{runtime_unresolved}（该部位的单会 fail-closed 422）")
    cloth_logicals = {logical for (logical, position) in runtime if position == "布帘"}
    expected = {f"{logical}×帘头" for logical in cloth_logicals if (logical, "帘头") in applicable}
    assert expected, "规范矩阵里没有「布帘列逻辑名 × 帘头」的 applicable 格 —— 判据会空跑"
    assert set(v97_unresolved) == expected, (
        "V97 口径的「解析不到」读数必须**恰为**帘头格（= 假阳性面）：\n"
        f"  期望：{sorted(expected)}\n  实际：{v97_unresolved}")
    # 🔴 反向护栏（判据**没有**放宽成恒真）：真「解析不到」的格，两份口径都判 None
    for cell in (("配料", "布帘"), ("从未登记的工序", "帘头")):
        assert runtime_resolve(*cell, sql_map, library) is None, f"V97 口径把 {cell} 判成解析得到"
        assert runtime_resolve(*cell, runtime, library) is None, f"运行期口径把 {cell} 判成解析得到"
    # 🔴 反向护栏（**注入式**）：把一条真「解析不到」的格塞进 applicable 集 ⇒ 上面那半条判据必红
    injected = [f"{l}×{p}" for l, p in applicable + [("从未登记的工序", "帘头")]
                if runtime_resolve(l, p, runtime, library) is None]
    assert injected == ["从未登记的工序×帘头"], (
        f"注入一条真「解析不到」的格后运行期口径判据竟不报 ⇒ 判据被放宽成恒真（实际 {injected}）")


def test_v97_soft_deletes_explicitly_and_never_physically_deletes():
    """判据 2 + 3：显式写列 + 只软删（**无**物理删）。"""
    sql = _strip_comments(MIGRATION.read_text(encoding="utf-8"))
    assert re.search(r"MERGE\s+INTO\s+production_operation_positions\b", sql, re.I), \
        "没有 MERGE 矩阵表（写形态见下：`MERGE … USING (…)`，刻意避开 `UPDATE … FROM <CTE>`）"
    assert re.search(r"SET\s+deleted\s*=\s*1\s*,\s*updated_at\s*=\s*NOW\(\)", sql, re.I), (
        "写形态必须**显式写列** `SET deleted = 1, updated_at = NOW()`"
        "（禁 `setDeleted(1); updateById(...)` —— 那是 #4608 的静默 no-op）")
    assert not re.search(r"\bDELETE\s+FROM\s+production_operation_positions\b", sql, re.I), \
        "红线：**只软删**，不得物理删矩阵行"
    # 不得碰任何历史表
    for table in ("processing_position_operations", "production_work_logs", "processing_orders"):
        assert not re.search(rf"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+{table}\b", sql, re.I), \
            f"红线：本迁移不得写历史表 `{table}`"


def _drop_exists_half(text: str, *, expect: int) -> str:
    """从 `text` 里删掉「期望变体名**曾存在**（`d.deleted = 1`）」那一半（= 退化成错误判据）。

    ⚠️ 用 `finditer` **逐处**删（判据在整份文件里出现**两次**：UPDATE 的 CTE 与末尾对账块）。
    `re.sub(..., count=1)` 只删第一处 ⇒ 留下第二处 ⇒ 注入「看似生效」但迁移仍按严格判据跑
    （实测：一行都不多删）= **空断言**（本文件第三次踩同族坑，故此处显式逐处删 + fail-closed 断言）。

    ⚠️ 正则必须锚到 **`d.` 别名**（`EXISTS (… production_operations d … d.deleted = 1)`）——
    判据里紧跟着还有 `NOT EXISTS (… production_operations a … a.deleted = 0)`。
    宽形态会把 `a` 那一半**一起删** ⇒ 判据退化成「只 LEFT JOIN、无任何过滤」⇒ 连健康格都被删
    ⇒ 注入的不是「错误判据」而是「无判据」（实测：那样写时对账查不到任何孤儿、不抛 ⇒ 红证空断言）。
    """
    matches = list(re.finditer(
        r"AND EXISTS \(\s*SELECT 1 FROM production_operations d\b.*?d\.deleted = 1\)\s*",
        text, re.S))
    assert len(matches) == expect, (
        f"「期望变体名曾存在」那一半应恰好出现 {expect} 处，实际 {len(matches)} 处 "
        "—— 判据形态变了，注入无法构造")
    out = text
    for match in reversed(matches):
        out = out[:match.start()] + out[match.end():]
    assert "d.deleted = 1" not in out, "注入后仍读得到 `d.deleted = 1` ⇒ 注入没生效"
    assert "a.deleted = 0" in out, (
        "注入把「活跃库里没有」那一半也删掉了 ⇒ 判据退化成「无判据」（注入形态错了）")
    return out


def _loosen_predicate(sql: str) -> str:
    """注入「**按错误判据清理**」：判据退化成「该格在活跃工序库里解析不到任何变体」。

    = **删掉**「期望变体名**曾存在**（`d.deleted = 1`）」那一半，只留 `NOT EXISTS (活跃库)`。

    ⚠️ **必须在剥注释后的文本上注入**（本文件红证 ③ 的第一版踩了这个坑：注入目标那行在
    `--` 注释里，剥注释后该行消失 ⇒ `replace` 成 no-op ⇒ 红证是「注入没生效却判通过」= 空断言）。

    ⚠️ **第二版也踩了坑（照实登记，因为它正是「空断言」的第二种形态）**：第一版把
    `AND d.deleted = 1` 改成 `AND d.deleted IN (0, 1)` —— 这**没有**退化成错误判据，
    反而让 `EXISTS` 对所有行恒真 ⇒ `COALESCE(v.variant_name, p.logical_name)` 永远走前半
    ⇒ 「从未登记」的格（变体表未命中、期望名回落成裸逻辑名）**恒假** ⇒ 一行都不多删
    （实测：仍是 2 条）。注入「生效了」但判据没被削弱 ⇒ 红证依然是**空断言**。
    正确形态 = **整段删掉**那个 `EXISTS` 子句（只留「解析不到」这一半）。

    ⚠️ 本函数对**全文**生效（UPDATE 与末尾对账块一起放宽）⇒ 对账**不会**抛
    （它抓的是「写语句与对账漂移」，不是「两处一起用错判据」）。要证明对账**会**拦，
    用 {@link _loosen_write_only}。
    """
    injected = _drop_exists_half(_strip_comments(sql), expect=2)
    assert "d.deleted = 1" not in injected, "注入后仍读得到 `d.deleted = 1` ⇒ 注入没生效"
    return injected


def _loosen_write_only(sql: str) -> str:
    """只放宽 **UPDATE 的 CTE**、**保留**末尾对账块的严格判据（= 写语句与对账**漂移**）。

    用来证明**停止条件真的会拦**：对账用严格判据 ⇒ 它查得到 3 条被误删的「从未登记」格
    ⇒ `RAISE EXCEPTION` ⇒ 整份迁移回滚（`psql` 非零退出）。
    """
    stripped = _strip_comments(sql)
    cut = stripped.find("DO $$")
    assert cut != -1, "找不到末尾对账块（`DO $$`）—— 判据形态变了"
    write, check = stripped[:cut], stripped[cut:]
    write_loose = _drop_exists_half(write, expect=1)
    assert write_loose != write, "注入没生效（写语句侧没删掉「曾存在」那一半）"
    assert "d.deleted = 1" in check, "对账块必须**保留**严格判据（本注入只动写语句）"
    return write_loose + check


def test_v97_orphan_predicate_requires_the_deleted_operation_half():
    """判据 4：判据必须含「期望变体名 `deleted = 1` 存在」那一半（去掉它就是「按错误判据清理」）。"""
    sql = _strip_comments(MIGRATION.read_text(encoding="utf-8"))
    # 写语句的判据区 = `MERGE … USING ( … ) src` 的子查询体（判据落在这里）
    low = sql.lower()
    start = low.find("using (")
    end = low.find(") src", start)
    assert start != -1 and end > start, "读不到 `MERGE … USING ( … ) src` 判据区 —— 判据会空跑"
    cte = sql[start:end]
    # ⚠️ 一律带 `re.S`：SQL 是**多行**排版（`EXISTS (` 与 `SELECT 1 FROM …` 不同行），
    #    不带它这些判据会全部读不到 = 空断言（本单实测踩过）。
    assert re.search(r"EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+production_operations\s+d\b", cte, re.I | re.S), \
        "缺「期望变体名**曾存在**（`d.deleted = 1`）」这一半 —— 去掉它会把**从未登记**的格也删掉"
    assert re.search(r"d\.deleted\s*=\s*1", cte, re.I), "缺 `d.deleted = 1` 判据"
    assert re.search(r"NOT\s+EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+production_operations\s+a\b", cte, re.I | re.S), \
        "缺「活跃工序库里没有这个名字」这一半"
    assert re.search(r"a\.deleted\s*=\s*0", cte, re.I), "缺 `a.deleted = 0` 判据"
    # 读面活跃域必须与 operationPositions 同口径（`MERGE` 源子查询的别名是 `p0`）
    assert re.search(r"p0\.deleted\s*=\s*0", cte, re.I) and \
        re.search(r"p0\.status\s*=\s*'active'", cte, re.I), \
        "缺读面活跃域（`deleted = 0 AND status = 'active'`）—— 与 operationPositions 不同口径"
    # 幂等承重：`WHEN MATCHED AND deleted = 0` 必须在 MERGE 的 UPDATE 分支上（第二次跑 0 行）
    assert re.search(r"WHEN\s+MATCHED\s+AND\s+p\.deleted\s*=\s*0", sql, re.I), \
        "缺 `WHEN MATCHED AND p.deleted = 0` —— 第二次跑会重复写（不幂等）"
    # 显式回落：期望名 = 变体表命中 ? 变体名 : 裸逻辑名（与 variantNameOf 第 3 步同口径）
    assert re.search(r"CASE\s+WHEN\s+v\.logical_name\s+IS\s+NULL", cte, re.I), \
        "缺「变体表未命中 ⇒ 回落裸逻辑名」的显式分支 —— 部位无关的裸逻辑名工序会漏判"
    # 🔴 判据**不得**写成 `COALESCE(v.variant_name, p.logical_name)`（本单实测的空断言形态）：
    #    LEFT JOIN 未命中时 `COALESCE(NULL, NULL)` 仍是 NULL ⇒ 「表未命中」的格恒假
    #    ⇒ 判据对它们静默失效（真库实测：注入「放宽判据」时一行都不多删，红证是空断言）。
    assert not re.search(r"COALESCE\s*\(\s*v\.variant_name", cte, re.I), \
        "判据写成了 `COALESCE(v.variant_name, p.logical_name)` —— LEFT JOIN 未命中时它是 NULL，" \
        "「表未命中」的格会恒假（判据静默失效）；必须用 `CASE WHEN v.logical_name IS NULL`"


def test_v97_is_explicitly_transactional():
    """判据 5b：文件**显式** `BEGIN; … COMMIT;` —— 否则停止条件在 `psql` 路径下**不回滚**。

    实测（本单真库判据）：`MigrationRunner` 的 `jdbc.execute(整份文件)` 让 PG 隐式包一个事务，
    但 `psql -f` 默认**逐条 autocommit** ⇒ UPDATE 已提交、DO 块才抛 ⇒ 留下半完成态。
    显式事务让两条执行路径同语义（`jdbc.execute` 下 PostgreSQL 对重复 `BEGIN` 只发 warning）。
    """
    sql = _strip_comments(MIGRATION.read_text(encoding="utf-8"))
    assert re.search(r"^\s*BEGIN\s*;", sql, re.M | re.I), "缺显式 `BEGIN;`"
    assert re.search(r"^\s*COMMIT\s*;", sql, re.M | re.I), "缺显式 `COMMIT;`"
    assert sql.lower().rindex("begin;") < sql.lower().rindex("commit;"), "`BEGIN;` 必须在 `COMMIT;` 之前"


def test_v97_has_count_reconciliation_stop_condition():
    """判据 5：末尾有**数量对账**的 `RAISE EXCEPTION`（判据与写语句漂移 ⇒ 整份回滚）。"""
    sql = _strip_comments(MIGRATION.read_text(encoding="utf-8"))
    assert re.search(r"RAISE\s+EXCEPTION", sql, re.I), "缺停止条件（`RAISE EXCEPTION`）"
    assert re.search(r"IF\s+remaining\s*>\s*0\s+THEN", sql, re.I), \
        "对账判据必须显式取「判据仍查得到孤儿」这一形态（**不是**「删了 N 行」—— 那种写法第二次跑必抛，不幂等）"


def test_bootstrap_schema_sql_needs_no_v97_section():
    """bootstrap 路径（`docs/sql/schema.sql` 不跑迁移链）**结构上不含孤儿** ⇒ 无需同步段落。

    红证形态：往 `schema.sql` 里种一条 `测试22` 一类商家自建格 ⇒ 本判据红
    （那时才必须同步）。
    """
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "测试22" not in sql, (
        "`schema.sql` 里出现了商家自建格 `测试22` —— bootstrap 终态可能含孤儿，"
        "V97 必须补一段同步（本判据的前提被推翻）")


def test_guard_detects_injected_drift():
    """红证：改判据 / 放宽判据 / 换写形态 / 加物理删 ⇒ 对应判据必红（不是空断言）。"""
    sql = MIGRATION.read_text(encoding="utf-8")

    # ① 改一条变体映射（值漂移）
    drifted = sql.replace("('三边',   '布帘', '布三边')", "('三边',   '布帘', '三边-布')")
    assert drifted != sql, "注入「改变体映射」没生效 ⇒ 判据是空断言"
    assert _sql_variant_map(drifted) != _java_variant_map(), "改变体映射后仍判「一致」⇒ 逐条判据是空断言"

    # ② 删一条变体映射（条数不足）
    dropped = sql.replace("    ('裁剪',   '布料', '裁剪-布')\n", "")
    assert dropped != sql, "注入「删一条映射」没生效"
    assert _sql_variant_map(dropped) != _java_variant_map(), "删一条后仍判「一致」⇒ 条数判据是空断言"

    # ③ 放宽判据（去掉 `deleted = 1` 那一半）= 「按错误判据清理」
    loose = _loosen_predicate(sql)
    assert not re.search(r"d\.deleted\s*=\s*1", loose, re.I), \
        "放宽后仍读得到 `d.deleted = 1` ⇒ 判据 4 是空断言"

    # ④ 换成「按行数等值」的对账（第二次跑必抛 ⇒ 不幂等）
    by_count = _strip_comments(sql).replace("IF remaining > 0 THEN", "IF remaining <> 0 THEN")
    assert by_count != _strip_comments(sql), "注入「换成行数等值对账」没生效"

    # ⑤ 塞一条物理删
    with_delete = _strip_comments(sql) + "\nDELETE FROM production_operation_positions WHERE deleted = 1;\n"
    assert re.search(r"\bDELETE\s+FROM\s+production_operation_positions\b", with_delete, re.I), \
        "「只软删」判据读不出注入的物理删 ⇒ 该判据是空断言"

    # ⑥ 剥注释本身是承重的（否则「改代码但注释还在」会让判据恒绿）
    assert "SET deleted = 1" in _strip_comments(sql), "剥注释后正文里必须仍有 `SET deleted = 1`"

    # ⑦ #4796：从**运行期**表里删掉一条帘头条目 ⇒ 「逐格差异清单」判据必红（不是恒真）
    java = QUERY_SERVICE.read_text(encoding="utf-8")
    dropped_head = java.replace('variant(names, "三边", "帘头", "布三边");', "")
    assert dropped_head != java, "注入「删一条帘头条目」没生效 ⇒ 本红证是空断言"
    injected_runtime = runtime_variant_map(dropped_head)
    assert ("三边", "帘头") not in injected_runtime, "注入后运行期表里仍读得到该帘头条目 ⇒ 注入没生效"
    injected_diff = _map_vs_runtime_diff(_sql_map(), injected_runtime)
    injected_expected = _curtain_head_fallback_cells(injected_runtime)
    # 🔴 issue #4937：运行期表另含 4 格纱帘变体（第二类可解释差异，见判据 1b 的注释）
    injected_expected = injected_expected | {("熨烫", "纱帘"), ("定型", "纱帘"),
                                             ("复烫", "纱帘"), ("车被", "纱帘")}
    assert set(injected_diff) == injected_expected - {("三边", "帘头")}, (
        "删掉一条帘头条目后差异面**必须恰好少掉那一格** ⇒ 判据 1b 才不是空断言，"
        f"实际 {sorted(set(injected_diff) ^ (injected_expected - {('三边', '帘头')}))}")
    # 且该格在运行期口径下变成**真解析不到**（证明判据仍抓得住真缺口）
    library = set(bootstrap_row_values(SCHEMA_SQL.read_text(encoding="utf-8")))
    assert runtime_resolve("三边", "帘头", injected_runtime, library) is None, (
        "删掉帘头条目后 `三边 × 帘头` 竟仍解析得到 ⇒ 判据对真缺口无判别力")


# ══════════════════════ 真库判据（本机 PG 二进制；缺则显式 skip） ══════════════════════

_PG_BINARIES = ("initdb", "pg_ctl", "psql")

#: 与 V71 同形的**最小** DDL（本单触碰的两张表 + 那条部分唯一索引 + 两张历史快照表）。
_DDL = """
CREATE TABLE tenants (id BIGINT PRIMARY KEY, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'active',
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_operation_positions (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    logical_name VARCHAR(64) NOT NULL, position VARCHAR(16) NOT NULL,
    unit_price NUMERIC(10,2), applicable BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX uk_production_operation_positions_tenant_name_position
    ON production_operation_positions (tenant_id, logical_name, position) WHERE deleted = 0;
-- 历史快照表（**红线：本迁移一字不动**）—— 建出来才能机械核验「指纹没变」
CREATE TABLE processing_position_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE production_work_logs (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT, operation_name VARCHAR(64),
    unit_price NUMERIC(10,2), factor NUMERIC(6,3), deleted INTEGER NOT NULL DEFAULT 0);
"""

#: 真库形态的种子：**2 条真孤儿** + **3 条 V97 口径下「解析不到」的格** + 1 条健康格 + 历史快照行。
#: 那 3 条是判据 4 的反向护栏（放宽判据 ⇒ 它们被误删 ⇒ 红）；
#: ⚠️ 「解析不到」是 **V97 口径**的判定 —— `never-1`（`三边 × 帘头`）在运行期**解析得到**（判据 1c）。
_SEED = """
INSERT INTO tenants (id) VALUES (1);
-- 工序库：36 条健康变体里只种本测试用到的 + 1 条已软删的自定义工序
INSERT INTO production_operations (id, tenant_id, name, deleted) VALUES
    ('op-1', 1, '精裁-布', 0),
    ('op-2', 1, '布三边', 0),
    ('op-3', 1, '测试22', 1),
    ('op-4', 1, '旧工序', 1);
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, deleted) VALUES
    -- ① 真孤儿 2 条（工序 测试22 已 deleted = 1）
    ('orphan-1', 1, '测试22', '布帘', 0.20, TRUE, 0),
    ('orphan-2', 1, '测试22', '纱帘', 0.30, TRUE, 0),
    -- ② V97 口径下「解析不到」的格 3 条 —— 不得被删。
    --    ⚠️ `never-1` = `三边 × 帘头` 在**运行期解析得到** `布三边`（种子 `op-2`，`deleted = 0`）：
    --    它落在这里只因 **V97 的 `variant_map` 不含帘头回落**（判据 1b/1c 钉住该差异），
    --    不是「从未登记」；真去删它就是丢商家的价（真库该格 ¥0.10 / `applicable = TRUE`）。
    ('never-1',  1, '三边', '帘头', 0.10, TRUE, 0),
    ('never-2',  1, '定型', '纱帘', NULL, FALSE, 0),
    ('never-3',  1, '打包', '布料', NULL, TRUE, 0),
    -- ③ 健康格 1 条（变体在活跃库）
    ('healthy-1', 1, '三边', '布帘', 0.40, TRUE, 0),
    -- ④ 已软删的格（幂等/不复活：本迁移不碰）
    ('already-1', 1, '精裁', '布帘', 0.40, TRUE, 1),
    -- ⑤ **改前就已存在**的孤儿（其工序 `旧工序` 在本迁移之前就是 deleted = 1）
    --    —— 用途：让末尾对账块**改前**就查得到一条孤儿 ⇒ 「对账会拦」有可执行红证。
    ('preorphan-1', 1, '旧工序', '布帘', NULL, TRUE, 0);
INSERT INTO processing_position_operations (id, tenant_id, operation_name, unit_price, factor) VALUES
    ('inst-1', 1, '精裁-布', 0.40, 1.000),
    ('inst-2', 1, '布三边', 0.10, 1.000);
INSERT INTO production_work_logs (id, tenant_id, operation_name, unit_price, factor) VALUES
    ('wl-1', 1, '精裁-布', 0.40, 1.000),
    ('wl-2', 1, '布三边', 0.10, 1.000);
"""


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
    sockdir = Path(tempfile.mkdtemp(prefix="pg4672-"))
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
        proc = psql_raw(sql)
        assert proc.returncode == 0, f"psql 失败：\n{proc.stdout}\n{proc.stderr}"
        return proc.stdout

    def psql_raw(sql: str):
        """不抛异常的入口（红证要断言「迁移**确实**失败并回滚」）。"""
        return subprocess.run(
            ["psql", "-h", str(sockdir), "-p", str(port), "-U", "postgres", "-d", "postgres",
             "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1"],
            input=sql, text=True, capture_output=True)

    run.raw = psql_raw

    try:
        yield run
    finally:
        subprocess.run(["pg_ctl", "-D", str(datadir), "-m", "immediate", "stop"],
                       capture_output=True)
        shutil.rmtree(sockdir, ignore_errors=True)


#: 把迁移包进**一个事务**执行 —— 复现 `MigrationRunner` 的 `jdbc.execute(整份文件)` 语义
#: （PG 对多语句字符串隐式包一个事务）。`psql -f` 默认**逐条 autocommit** ⇒ 不包则停止条件
#: 抛异常时 MERGE 已提交、**不回滚**，判据就不是生产路径的语义。
#: ⚠️ V97 文件内另有自己的 `BEGIN; … COMMIT;`（#4758 合入版本）⇒ 外层再包一层会得到
#: PG 的 `WARNING: there is already a transaction in progress`（**不是错误**，无害）。
_TX = "BEGIN;\n{body}\nCOMMIT;\n"


def _as_runner_would(sql: str) -> str:
    return _TX.format(body=sql)


def _seed(run) -> None:
    run(_DDL + _SEED)


def _fingerprint(run, table: str, columns: str) -> str:
    out = run(f"SELECT md5(string_agg(t::text, '|' ORDER BY t.id)) FROM "
              f"(SELECT {columns} FROM {table}) t;")
    return out.strip()


_HISTORY_TABLES = {
    "processing_position_operations": "id, tenant_id, operation_name, unit_price, factor, deleted",
    "production_work_logs": "id, tenant_id, operation_name, unit_price, factor, deleted",
}


def _matrix_ids(run) -> list:
    out = run("SELECT id || ':' || deleted FROM production_operation_positions ORDER BY id;")
    return [line for line in out.splitlines() if line.strip()]


def test_v97_cleanup_is_idempotent_and_hits_exactly_the_orphans(psql):
    """判据 6 + 真库承重：改前 2 条孤儿 ⇒ 改后 0 条；非孤儿 4 条一字不动；跑两次净效果相同。"""
    _seed(psql)
    sql = MIGRATION.read_text(encoding="utf-8")

    before = _matrix_ids(psql)
    assert "orphan-1:0" in before and "orphan-2:0" in before, "红证前提不成立：种子里的孤儿行没落库"

    psql(_as_runner_would(sql))  # 第一次
    after_first = _matrix_ids(psql)
    psql(_as_runner_would(sql))  # 第二次（幂等）
    after_second = _matrix_ids(psql)

    assert after_first == after_second, (
        f"V97 **不幂等**：第二次跑改了净效果\n  第一次后：{after_first}\n  第二次后：{after_second}")
    assert "orphan-1:1" in after_first and "orphan-2:1" in after_first, \
        f"2 条真孤儿未被软删：{after_first}"
    assert "preorphan-1:1" in after_first, \
        f"改前就存在的孤儿未被软删（它同样是真孤儿，必须一并清理）：{after_first}"
    for kept in ("never-1:0", "never-2:0", "never-3:0", "healthy-1:0", "already-1:1"):
        assert kept in after_first, (
            f"非孤儿行 `{kept}` 被误删/误改 —— 判据放宽了（真库 **V97 口径**读数：这类格 105 条，"
            f"且带商家显式价；其中帘头格运行期解析得到，见判据 1b/1c）：{after_first}")
    # 软删必须带 updated_at 审计（不是「只改 deleted」）
    stamped = psql("SELECT count(*) FROM production_operation_positions "
                   "WHERE id IN ('orphan-1','orphan-2') AND deleted = 1 AND updated_at > created_at;")
    assert stamped.strip() == "2", "软删未写 `updated_at`（审计证据缺失）"


def test_v97_leaves_history_byte_identical(psql):
    """判据 7（红线）：历史快照逐字节指纹前后相同 —— 本迁移只写矩阵表的两列。"""
    _seed(psql)
    before = {t: _fingerprint(psql, t, cols) for t, cols in _HISTORY_TABLES.items()}
    assert all(v for v in before.values()), f"改前指纹取不到（判据会空跑）：{before}"

    psql(_as_runner_would(MIGRATION.read_text(encoding="utf-8")))

    after = {t: _fingerprint(psql, t, cols) for t, cols in _HISTORY_TABLES.items()}
    assert after == before, (
        "红线被破：历史快照指纹变了\n"
        f"  改前：{before}\n  改后：{after}\n"
        "（工序实例的旧名 / 报工流水的 unit_price·factor 必须一字不动）")
    # 历史快照行数也必须不变
    rows = psql("SELECT (SELECT count(*) FROM processing_position_operations) || '/' || "
                "(SELECT count(*) FROM production_work_logs);").strip()
    assert rows == "2/2", f"历史快照行数变了：{rows}"


def test_v97_reconciliation_blocks_a_partial_write(psql):
    """判据 5 的**红证**（真库）：**写语句漏删**（判据漂移）⇒ 对账 `RAISE EXCEPTION` ⇒ 整份回滚。

    注入 = 给 MERGE 源子查询的 `WHERE` 尾部加 `LIMIT 1`（模拟「写语句没删干净」这一漂移形态）。

    ⚠️ **为什么不用「放宽写语句」当漂移**（本文件第四次踩同族坑，照实登记）：把 `AND EXISTS
    (… d.deleted = 1)` 整段删掉后，写语句会**多删**「从未登记」的格，而**严格对账也查不到它们**
    （对严格判据而言它们本就不是孤儿）⇒ 对账 `remaining = 0`、**不抛**。实测证明：
    对账抓的是「**写语句漏删**」，**抓不到**「两处一起用错判据」——
    后者只能靠**静态判据 4** 钉住（见下一条红证）。
    """
    _seed(psql)
    before = _matrix_ids(psql)
    sql = MIGRATION.read_text(encoding="utf-8")
    injected = sql.replace(") src\n", "  LIMIT 1\n) src\n", 1)
    assert injected != sql, "注入「漏删」没生效 ⇒ 本红证是空断言"
    proc = psql.raw(_as_runner_would(injected))
    assert proc.returncode != 0, (
        "写语句漏删时对账竟未拦下 ⇒ 停止条件是空断言\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}")
    assert "数量对账失败" in proc.stderr, f"拦下的不是对账判据：{proc.stderr[:400]}"
    assert _matrix_ids(psql) == before, "对账抛异常后矩阵行却变了 ⇒ 没有回滚（半完成态）"


def test_v97_loosened_predicate_over_deletes_the_never_registered_cells(psql):
    """判据 4 的**红证**（真库）：**两处一起**放宽 ⇒ 3 条「从未登记」的格被误删。

    这是「按错误判据清理」的可执行复现 —— 证明判据里「期望变体名**曾存在**」那一半是**承重**的。

    ⚠️ **本红证证明的边界（照实登记）**：两处一起放宽时对账**不会**抛（它抓的是「写语句漏删」，
    不是「两处一起用错判据」）⇒ 判据正确性靠**静态判据 4** + 本红证钉住，**不能只靠对账**。
    上一条 `test_v97_reconciliation_blocks_a_partial_write` 覆盖「写语句漏删」那一半。
    """
    _seed(psql)
    psql(_as_runner_would(_loosen_predicate(MIGRATION.read_text(encoding="utf-8"))))
    ids = _matrix_ids(psql)
    for victim in ("never-1:1", "never-2:1", "never-3:1"):
        assert victim in ids, (
            f"注入「放宽判据」后 `{victim}` 竟未被误删 ⇒ 本红证没抓住「按错误判据清理」这一形态：{ids}")
    assert "healthy-1:0" in ids, "放宽判据不应误删健康格（变体在活跃库）"
    assert "orphan-1:1" in ids and "orphan-2:1" in ids, "放宽判据下真孤儿仍应被软删"
