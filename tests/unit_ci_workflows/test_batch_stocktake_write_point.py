# case_ids: MC-052
"""**批次账写入点唯一 + 来源族形状在 DB 上互斥** 的类级元守卫（issue #5865，铁律 8）。

## 为什么要有它（这一类缺陷长什么样）

按批次盘点（#5865）给 `stock_batch_consumptions` 加了**第三个来源**（`reason='stocktake'`）。
这类改动最常见的两种回归**都不会有东西变红**：

| 形态 | 后果 | 为什么别的判据抓不到 |
|---|---|---|
| **写入点分叉**：为了「方便」在第二个类里直接 `consumptionMapper.insert(...)` | 批次台账出现**绕过 `StockBatchConsumptionService`** 的写入 ⇒ 余量派生（`quantity + Σdelta`）仍在，但**盘前/盘后链**、幂等闸、来源列形状全都不再被强制 | 实例判据只覆盖被测的那条路径；新写入点自带测试、照样绿 |
| **来源族混淆**：盘点行填了 `processing_order_no`（或扣料行漏填） | 「这批为什么少了 1.5 米」答不出来 —— 读面分不清「加工单扣料」与「盘点调整」，`/consumptions?processingOrderNo=` 会查出盘点行（**假账**） | 应用层能自觉填对，**没有任何机械判据**要求它 |

⇒ 本文件把两件事钉成**结构性**判据：① 批次台账的 `insert` 只许出现在**一个**登记过的文件里
（未登记即红）；② 余量派生的 Σdelta 读口只许出现在登记过的文件里；③ 来源族的**列形状互斥**
必须以 DB 约束的形式存在于 `schema.sql` 与**活迁移**两边，且与 Java 常量取值逐字对齐。

## 判据是**纯函数**（输入 = 路径 → 源码文本）

于是注入式红证可以在**内存里**做完（不碰工作树）：构造一份坏语料 ⇒ 判据必须报出**具名**问题。
本文件末尾的 `test_injected_bad_corpora_are_named` 就是这些红证，随判据常驻。

## 边界（照实登记，§19.1）

- 判据只认**仓内文本形态**：`<mapper 标识符>.insert(`（标识符由 `StockBatchConsumptionMapper <名>`
  的声明取得）与 `getMapper(StockBatchConsumptionMapper.class).insert(`。用**反射 / 裸 SQL /
  JdbcTemplate** 写台账的代码不在射程内（本仓没有这种写法，出现时也不会有东西提醒）；
- 它判不了「盘点的业务口径对不对」（那是 `BatchStocktakeServiceTest` / `BatchStocktakeRealDbTest` 的事）；
- `schema.sql` 与迁移**只读文本**，不起真库（真库面判据在 `BatchStocktakeRealDbTest`）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code  # noqa: E402

MAIN_JAVA = REPO_ROOT / "backend/admin-api/src/main/java"
SCHEMA = REPO_ROOT / "backend/admin-api/src/main/resources/db/init/schema.sql"
MIGRATION_DIR = REPO_ROOT / "backend/admin-api/src/main/resources/db/migration"
FINGERPRINTS = REPO_ROOT / "tests/unit_ci_workflows/migration_fingerprints.json"

LEDGER_SERVICE = "com/migao/admin/service/StockBatchConsumptionService.java"
LEDGER_MAPPER = "com/migao/admin/mapper/StockBatchConsumptionMapper.java"

# ── 冻结台账（**未登记即红**；只许缩短，缩短时必须有等价的新承载体）────────────────
#
# 批次台账（`stock_batch_consumptions`）的**写入点**：全仓唯一一处。
# 新增写入点 ⇒ 本判据红，且报出是哪个文件、哪一行 —— 这时要么把它并回这里，要么
# 明确登记（登记 = 在本表加条目**并**在 PR 里说明幂等闸 / 来源列形状 / 盘前盘后链怎么保证）。
BATCH_LEDGER_WRITE_POINTS: tuple[str, ...] = (LEDGER_SERVICE,)

# 批次**余量派生**（入库量 + Σdelta）的读口：只许由台账服务与它自己的 mapper 调。
# 第二处聚合 Σdelta = 第二份「这批还剩多少」，而两份不会同时变红。
DERIVED_REMAINING_READERS: tuple[str, ...] = (LEDGER_SERVICE, LEDGER_MAPPER)

_SUM_CALLS = ("sumDeltaByBatchIds(", "sumDeltaBySku(")

_TYPE_DECL = re.compile(r"\bStockBatchConsumptionMapper\s+([A-Za-z_][A-Za-z0-9_]*)")
_INSERT_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*insert\s*\(")
_MAPPER_INSERT = re.compile(
    r"getMapper\s*\(\s*StockBatchConsumptionMapper\.class\s*\)\s*\.\s*insert\s*\(")

STOCKTAKE_REASON = "stocktake"
SOURCE_SHAPE_CONSTRAINT = "ck_batch_consumption_source_shape"
STOCKTAKE_IDEMPOTENCY_INDEX = "uk_batch_consumption_stocktake"


# ══════════════════════════════════════════════════════════════════════════════
# 一、判据本体（纯函数：输入语料 ⇒ 具名问题清单）
# ══════════════════════════════════════════════════════════════════════════════


def batch_ledger_write_points(sources: dict[str, str]) -> list[str]:
    """语料里**写批次台账**的文件（注释不算 —— `java_code` 把注释抹成空格）。"""
    hits: list[str] = []
    for path, text in sorted(sources.items()):
        code = java_code(text)
        names = set(_TYPE_DECL.findall(code))
        writes = [name for name in _INSERT_CALL.findall(code) if name in names]
        if writes or _MAPPER_INSERT.search(code):
            hits.append(path)
    return hits


def write_point_problems(sources: dict[str, str], registry: tuple[str, ...]) -> list[str]:
    """未登记即红 + **fail-closed**（登记表为空 / 登记的文件不存在 / 扫描零命中都算红）。"""
    out: list[str] = []
    if not registry:
        out.append("登记表 BATCH_LEDGER_WRITE_POINTS 为空 ⇒ 判据 fail-closed（零登记不许当绿）")
    live = batch_ledger_write_points(sources)
    if not live:
        out.append("扫描零命中：批次台账的写入点一个都没找到 ⇒ 判据本身失效（fail-closed）")
    for path in sorted(set(live) - set(registry)):
        out.append(
            f"批次台账出现**未登记**的写入点：`{path}` —— 新写入点必须并回 "
            f"`{LEDGER_SERVICE}`（幂等闸 / 来源列形状 / 盘前盘后链都挂在那里），"
            "或在 BATCH_LEDGER_WRITE_POINTS 登记并在 PR 里说明这三件事怎么保证"
        )
    for path in sorted(set(registry) - set(live)):
        out.append(f"登记表指向的写入点 `{path}` 已不再写台账（或文件没了）⇒ 陈旧登记，须销账")
    return out


def derived_reader_problems(sources: dict[str, str], registry: tuple[str, ...]) -> list[str]:
    """Σdelta 的读口只许在登记过的文件里（第二份余量口径 ⇒ 红）。"""
    out: list[str] = []
    live = [path for path, text in sorted(sources.items())
            if any(call in java_code(text) for call in _SUM_CALLS)]
    if not live:
        out.append("扫描零命中：Σdelta 的读口一个都没找到 ⇒ 判据本身失效（fail-closed）")
    for path in sorted(set(live) - set(registry)):
        out.append(
            f"`{path}` 自己聚合 Σdelta（批次余量派生的第二份口径）—— 余量口径的唯一入口是 "
            f"`{LEDGER_SERVICE}`；请改调它的读面，别另写第二份"
        )
    return out


def source_shape_problems(schema_text: str, migration_texts: dict[str, str],
                          java_constants: dict[str, str],
                          fingerprints: dict[str, str]) -> list[str]:
    """来源族形状互斥 + 幂等闸 + Java/DB 取值对齐，三面都要有。"""
    out: list[str] = []

    def require(cond: bool, message: str) -> None:
        if not cond:
            out.append(message)

    require(SOURCE_SHAPE_CONSTRAINT in schema_text,
            f"`schema.sql` 里没有 {SOURCE_SHAPE_CONSTRAINT}：盘点行与扣料行在**结构上**分不开了"
            "（新建库路径失去这条约束）")
    if SOURCE_SHAPE_CONSTRAINT in schema_text:
        # 取 `ADD CONSTRAINT <名>` 之后的那段（**不是**第一次出现名的地方：列注释里也会提它）
        anchor = f"ADD CONSTRAINT {SOURCE_SHAPE_CONSTRAINT}"
        start = schema_text.find(anchor)
        if start < 0:
            start = schema_text.find(SOURCE_SHAPE_CONSTRAINT)
        block = schema_text[start:start + 900]
        require("stocktake_run_id IS NOT NULL" in block,
                f"{SOURCE_SHAPE_CONSTRAINT} 没要求盘点行带 stocktake_run_id（幂等键可缺席）")
        require("processing_order_no IS NULL" in block,
                f"{SOURCE_SHAPE_CONSTRAINT} 没禁止盘点行携带加工单号（两族可被混淆成假账）")
        require("processing_order_no IS NOT NULL" in block,
                f"{SOURCE_SHAPE_CONSTRAINT} 没要求扣料行必须有加工单号（既有契约被放宽）")

    for label, text in [("schema.sql", schema_text), *sorted(migration_texts.items())]:
        if label != "schema.sql" and STOCKTAKE_REASON not in text:
            continue  # 别的迁移不涉及盘点来源
        require(STOCKTAKE_IDEMPOTENCY_INDEX in text,
                f"`{label}` 里没有幂等闸 {STOCKTAKE_IDEMPOTENCY_INDEX}"
                "（同一 run × 批次可重复落账 ⇒ 网络重试双记）")
        require("stocktake_run_id IS NOT NULL" in text,
                f"`{label}` 的 {STOCKTAKE_IDEMPOTENCY_INDEX} 不是部分唯一索引（谓词缺席）")
        require(f"'{STOCKTAKE_REASON}'" in text,
                f"`{label}` 的 reason 取值集合没有 '{STOCKTAKE_REASON}'（盘点行会被 23514 拒掉）")

    literal = java_constants.get("REASON_STOCKTAKE", "")
    require(literal == STOCKTAKE_REASON,
            f"Java 常量 REASON_STOCKTAKE = {literal!r}，DB 侧取值是 {STOCKTAKE_REASON!r} ⇒ 两边漂移"
            "（DB 约束会当场拒掉应用写出来的行）")

    stocktake_migrations = [name for name, text in migration_texts.items()
                            if STOCKTAKE_REASON in text]
    require(len(stocktake_migrations) >= 1,
            "活迁移目录里没有任何一条迁移引入盘点来源 ⇒ 存量库拿不到新列 / 新约束")
    for name in stocktake_migrations:
        require(name in fingerprints,
                f"迁移 `{name}` 未登记进 migration_fingerprints.json"
                "（跑 `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger`）")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 二、读真语料
# ══════════════════════════════════════════════════════════════════════════════


def java_sources() -> dict[str, str]:
    return {p.relative_to(MAIN_JAVA).as_posix(): p.read_text(encoding="utf8")
            for p in sorted(MAIN_JAVA.rglob("*.java"))}


def migration_texts() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf8") for p in sorted(MIGRATION_DIR.glob("*.sql"))}


def java_reason_constant() -> str:
    text = (MAIN_JAVA / "com/migao/admin/entity/StockBatchConsumption.java").read_text(encoding="utf8")
    match = re.search(r'REASON_STOCKTAKE\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else ""


def fingerprint_names() -> dict[str, str]:
    data = json.loads(FINGERPRINTS.read_text(encoding="utf8"))
    return dict(data["migrations"])


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据
# ══════════════════════════════════════════════════════════════════════════════


def test_batch_ledger_has_exactly_one_write_point() -> None:
    """批次台账的写入点唯一（未登记即红；登记表只许缩短 + 不许陈旧）。"""
    sources = java_sources()
    problems = write_point_problems(sources, BATCH_LEDGER_WRITE_POINTS)
    live = batch_ledger_write_points(sources)
    print(f"[MC-052] 批次台账写入点现取 = {live}（登记 = {list(BATCH_LEDGER_WRITE_POINTS)}）")
    assert problems == [], "\n".join(problems)


def test_batch_remaining_is_derived_in_one_place() -> None:
    """余量派生（Σdelta 读口）只许在登记过的文件里。"""
    sources = java_sources()
    problems = derived_reader_problems(sources, DERIVED_REMAINING_READERS)
    live = [p for p, t in sorted(sources.items()) if any(c in java_code(t) for c in _SUM_CALLS)]
    print(f"[MC-052] Σdelta 读口现取 = {live}")
    assert problems == [], "\n".join(problems)


def test_source_families_are_disjoint_in_the_database() -> None:
    """来源族形状互斥 + 幂等闸 + Java/DB 取值对齐（schema、活迁移、指纹账本三面）。"""
    problems = source_shape_problems(SCHEMA.read_text(encoding="utf8"), migration_texts(),
                                     {"REASON_STOCKTAKE": java_reason_constant()},
                                     fingerprint_names())
    assert problems == [], "\n".join(problems)


# ══════════════════════════════════════════════════════════════════════════════
# 四、判别力自证（注入式红证，**内存语料**，不碰工作树）
# ══════════════════════════════════════════════════════════════════════════════


def _good_sources() -> dict[str, str]:
    """最小合规语料：一个写点（登记过）+ 一个纯读文件。"""
    return {
        LEDGER_SERVICE: (
            "class StockBatchConsumptionService {\n"
            "  private final StockBatchConsumptionMapper consumptionMapper;\n"
            "  void apply() { consumptionMapper.insert(StockBatchConsumption.builder().build()); }\n"
            "  void reads() { consumptionMapper.sumDeltaByBatchIds(1L, ids); }\n"
            "}\n"),
        "com/migao/admin/service/BatchStocktakeService.java": (
            "class BatchStocktakeService {\n"
            "  // 本类**只**经台账服务写库：没有任何 mapper 字段\n"
            "  private final StockBatchConsumptionService batchStockService;\n"
            "}\n"),
    }


def test_injected_bad_corpora_are_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """四条坏形态各自**判红**，且红得具名；一条「只改注释」的对照**不红**。"""
    good = _good_sources()
    baseline = write_point_problems(good, BATCH_LEDGER_WRITE_POINTS)
    assert baseline == [], f"合规语料不该报红：{baseline}"

    # ① 第二个写入点（新服务自己 insert）⇒ 必红，且点名该文件
    forked = dict(good)
    forked["com/migao/admin/service/RogueService.java"] = (
        "class RogueService {\n"
        "  private final StockBatchConsumptionMapper consumptionMapper;\n"
        "  void w() { consumptionMapper.insert(StockBatchConsumption.builder().build()); }\n"
        "}\n")
    problems = write_point_problems(forked, BATCH_LEDGER_WRITE_POINTS)
    assert any("RogueService.java" in p for p in problems), problems

    # ② 登记表清空 ⇒ fail-closed 红
    assert write_point_problems(good, ()), "登记表清空必须红（fail-closed）"

    # ③ 扫描零命中（语料里没有任何写入点）⇒ 红，不许当绿
    silent = {LEDGER_SERVICE: "class StockBatchConsumptionService {}\n"}
    assert write_point_problems(silent, BATCH_LEDGER_WRITE_POINTS), "零命中必须红（判据失效自曝）"

    # ④ 对照：**只把 insert 写进注释** ⇒ 不红（注释不是写入点；判据不许被自己的文案喂红）
    commented = dict(good)
    commented["com/migao/admin/service/RogueService.java"] = (
        "class RogueService {\n"
        "  // 这里**不**允许出现 consumptionMapper.insert(...) 这种写法\n"
        "}\n")
    assert write_point_problems(commented, BATCH_LEDGER_WRITE_POINTS) == [], "注释不得被读成写入点"

    # ⑤ 余量口径的第二处聚合 ⇒ 必红
    rogue_reader = dict(good)
    rogue_reader["com/migao/admin/service/AnotherSum.java"] = (
        "class AnotherSum { void r() { consumptionMapper.sumDeltaByBatchIds(1L, ids); } }\n")
    assert derived_reader_problems(rogue_reader, DERIVED_REMAINING_READERS), "第二处 Σdelta 聚合必须红"
    assert derived_reader_problems(good, DERIVED_REMAINING_READERS) == [], "合规语料不该报红"

    # ⑥ 来源形状：约束缺席 / Java 与 DB 取值漂移 / 迁移未登记 ⇒ 三种都必红
    schema_ok = (f"ALTER TABLE stock_batch_consumptions ADD CONSTRAINT {SOURCE_SHAPE_CONSTRAINT}\n"
                 "    CHECK ((reason = 'stocktake' AND stocktake_run_id IS NOT NULL\n"
                 "        AND processing_order_no IS NULL AND order_item_id IS NULL AND order_no IS NULL)\n"
                 "      OR (reason <> 'stocktake' AND stocktake_run_id IS NULL\n"
                 "        AND processing_order_no IS NOT NULL AND order_item_id IS NOT NULL));\n"
                 f"CREATE UNIQUE INDEX {STOCKTAKE_IDEMPOTENCY_INDEX} ON stock_batch_consumptions\n"
                 "    (tenant_id, stocktake_run_id, batch_id)\n"
                 "    WHERE stocktake_run_id IS NOT NULL AND deleted = 0;\n"
                 f"ALTER TABLE stock_batch_consumptions ADD CONSTRAINT ck_batch_consumption_reason\n"
                 "    CHECK (reason IN ('processing_order', 'processing_order_cancelled', 'stocktake'));\n")
    mig = {"V143__add_stocktake_to_batch_consumptions.sql": schema_ok}
    fps = {"V143__add_stocktake_to_batch_consumptions.sql": "sha256:x"}
    clean = source_shape_problems(schema_ok, mig, {"REASON_STOCKTAKE": STOCKTAKE_REASON}, fps)
    assert clean == [], f"合规语料不该报红：{clean}"

    assert source_shape_problems(schema_ok.replace(SOURCE_SHAPE_CONSTRAINT, "zzz"), mig,
                                 {"REASON_STOCKTAKE": STOCKTAKE_REASON}, fps), "约束被删必须红"
    assert source_shape_problems(schema_ok, mig, {"REASON_STOCKTAKE": "stock_check"}, fps), \
        "Java 常量与 DB 取值漂移必须红"
    assert source_shape_problems(schema_ok, mig, {"REASON_STOCKTAKE": STOCKTAKE_REASON}, {}), \
        "活动迁移未登记指纹账本必须红"
