# case_ids: PG-043
"""特殊选项按套计价的**迁移/种子/契约**守卫（issue #4525 = 设计 §4/§7/§8 包 A）。

## 为什么需要它（本单的静默失效面）

| 形态 | 后果 | 本文件的判据 |
|---|---|---|
| V77 没加列 / 类型不对 | 取价侧 `getCustomerUnitPrice()` 恒 null ⇒ **所有特殊选项静默按 0 收** | `test_v77_adds_customer_unit_price_column` |
| 非 `option` 行被写了价 | 工艺变体也按套收费（§4.1 冻结的边界被破） | `test_only_option_rows_carry_a_customer_price` |
| 种子价与生成器漂移 | 「固定种子生成一次、写死」这条硬约束失效 ⇒ 定价不可复现 | `test_seed_rows_match_the_deterministic_generator` |
| 种子缺 `source='synthetic'` | 测试价被当成真实价目（设计 §7 硬约束 ②） | 同上 + `test_seed_carries_synthetic_provenance` |
| 合成价以 `active` 落库 | **生产 tenant 1 按随机价收费**（P1 钱风险） | `test_synthetic_combination_rows_are_all_disabled` |
| 合成选项价落 `customer_unit_price` | 同上（该列无 status 可门控） | `test_migration_never_prices_customer_unit_price` |
| 计件路径读了本列 | 对客售价泄漏成工人计件单价（两套账互读，判据 10） | `test_piecework_paths_never_read_customer_unit_price` |
| 读面改成重算 | 改价回算历史订单（R13 快照冻结被破，判据 11） | `test_read_paths_still_read_the_persisted_detail` |

## 红证（不会红的断言 = 空断言）

本文件自带**注入式自证**：`test_parsers_detect_injected_drift` 把迁移文本改一个字
（价格 / source / 列名）后必须**读得出差异**；`test_piecework_read_guard_detects_injected_read`
把一处假读取注入到**临时副本**上必须被照出来。没有这两条，上面的逐值比对与 grep 守卫
都可能「绿了但没跑」。

## 🔴 合成价**一律不得参与取价**（issue #4525 复核的 P1 钱风险）

`MigrationRunner` 在 **admin-api 启动时**执行迁移 ⇒ **生产一样会跑**；而取价侧只过滤
`status='active'`（**不按 `source` 过滤**）⇒ 任何一行 active 的合成价 = 生产 tenant 1
按随机价收费。故本文件钉两条红线：

* `test_synthetic_combination_rows_are_all_disabled` —— 92 行组合价**全部** `status='disabled'`；
* `test_migration_never_prices_customer_unit_price` —— 迁移**不得**给 `customer_unit_price`
  落任何价（该列无 status 可门控 ⇒ 恒 `NULL` = 未定价 ⇒ `priced:false` 显式可见）。

## ⚠️ 设计文档与代码事实的冲突（以代码事实为准）

设计 §7 写「19 项特殊选项价」，但 §4.1 同时冻结「非 `option` 行一律 `NULL`」；
而 19 项里只有 **16 项**在 `production_route_rules` 里是 `trigger_kind='option'` 行
（`余料带回-布` / `余料带回-纱` 不计件、`一分为二` 只有计件系数档）。
⇒ 本文件按 **16** 判（`test_priced_option_rows_are_exactly_the_option_rules` 逐条点名），
并把该冲突登记在迁移文件头与生成器 docstring 里。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import synthetic_processing_fee_data as synthetic  # noqa: E402

MIGRATION = REPO / "backend/admin-api/src/main/resources/db/migration/V77__customer_option_unit_price.sql"
SCHEMA = REPO / "docs/sql/schema.sql"
FIXTURE = REPO / "tests/e2e/fixtures/processing-list.json"
JAVA_MAIN = REPO / "backend/admin-api/src/main/java"

#: `customer_unit_price` 的**唯一**合法读取点（取价层）。
#: 其它任何地方出现它 ⇒ 两套账互读（判据 10）⇒ 红。
CUSTOMER_PRICE_READ_ALLOWLIST = {
    "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingFeeCalculator.java",
    # 实体字段声明本身（不是"读取"，但字符串会命中 ⇒ 显式登记，避免守卫退化成"全部命中"）
    "backend/admin-api/src/main/java/com/migao/admin/entity/ProductionRouteRule.java",
}

_ROW_RE = re.compile(r"\(([^()]*)\)")


def migration_text() -> str:
    assert MIGRATION.exists(), f"V77 迁移缺失：{MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


def _split_values(body: str) -> list:
    """`VALUES` 段 → 行字段列表（简单 SQL 字面量切分：够用且不引第三方解析器）。"""
    rows = []
    for raw in _ROW_RE.findall(body):
        fields = []
        current = ""
        depth = 0
        in_string = False
        for char in raw:
            if char == "'" and not in_string:
                in_string = True
                current += char
            elif char == "'" and in_string:
                in_string = False
                current += char
            elif in_string:
                current += char
            elif char in "[(":
                depth += 1
                current += char
            elif char in "])":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                fields.append(current.strip())
                current = ""
            else:
                current += char
        fields.append(current.strip())
        rows.append(fields)
    return rows


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw


def combination_seed_rows(sql: str) -> dict:
    """V77 的组合价目行 → `{composition_key: (unit_price, source, items)}`（**逐值**口径）。"""
    match = re.search(
        r"INSERT\s+INTO\s+processing_fee_combinations\b.*?VALUES(.*?)ON\s+CONFLICT",
        sql, re.S | re.I)
    assert match, "V77 没有 `INSERT INTO processing_fee_combinations … VALUES` 段"
    rows = {}
    for fields in _split_values(match.group(1)):
        assert len(fields) == 8, f"组合价目行列数不是 8（列序漂移即解析错位）: {fields}"
        _, _, key, items, price, _status, _sort, source = fields
        items_json = re.sub(r"::jsonb$", "", items).strip()
        rows[_unquote(key)] = (
            _unquote(price), _unquote(source), tuple(json.loads(_unquote(items_json))))
    return rows


# ══════════════════════════ ① 列（设计 §4.1）══════════════════════════

def test_v77_adds_customer_unit_price_column():
    """V77 必须**幂等**地加 `customer_unit_price NUMERIC(12,2)` 并带 `COMMENT ON COLUMN`。

    幂等是 `MigrationRunner` 的硬要求（所有迁移可重复执行）；`COMMENT` 不是装饰 ——
    它把「对客售价账」与「计件路径绝不读本列」两条纪律**写进库**（`\\d+` 就能看到）。
    """
    sql = migration_text()
    assert re.search(
        r"ALTER\s+TABLE\s+production_route_rules\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+"
        r"customer_unit_price\s+NUMERIC\(12,\s*2\)", sql, re.I), \
        "V77 缺少幂等的 `ADD COLUMN IF NOT EXISTS customer_unit_price NUMERIC(12,2)`"
    comment = re.search(
        r"COMMENT\s+ON\s+COLUMN\s+production_route_rules\.customer_unit_price\s+IS(.*?);",
        sql, re.S | re.I)
    assert comment, "V77 缺少 `COMMENT ON COLUMN production_route_rules.customer_unit_price`"
    body = comment.group(1)
    # 注释必须写明：① 对客售价账 ② 计件路径绝不读本列 ③ NULL = 未定价（≠0）
    assert "对客售价账" in body, "列注释没写明账别（对客售价账）"
    assert "计件路径绝不读本列" in body, "列注释没写明「计件路径绝不读本列」这条纪律"
    assert "未定价" in body, "列注释没写明 NULL = 未定价（≠ 0）"


def test_v77_migration_is_idempotent():
    """重复执行必须空转：`ADD COLUMN IF NOT EXISTS` + `ON CONFLICT DO NOTHING`。

    反例（本测试要挡的形态）：裸 `ADD COLUMN` 第二次执行报错（迁移链断在半路）；
    种子 `INSERT` 无 `ON CONFLICT` ⇒ 第二次执行主键冲突。
    """
    sql = migration_text()
    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert re.search(r"ON\s+CONFLICT\s*\(id\)\s+DO\s+NOTHING", sql, re.I), \
        "组合价目种子没有 `ON CONFLICT (id) DO NOTHING`（重复执行会主键冲突）"
    assert not re.search(r"^\s*UPDATE\s", sql, re.M | re.I), \
        "V77 不该有任何 UPDATE（合成选项价不落库 —— 见文件头「合成价一律不得参与取价」）"


def test_synthetic_combination_rows_are_all_disabled():
    """🔴 **92 行合成价必须全部 `status='disabled'`**（issue #4525 复核的 P1 钱风险）。

    `MigrationRunner` 在 **admin-api 启动时**执行本迁移 ⇒ **生产一样会跑**；而取价侧
    （`ProcessingFeeCalculator.pricedCombinations`）只过滤 `tenantId + deleted=0 + status='active'`，
    **不按 `source` 过滤** ⇒ 任何一行 active 的合成价都会让**生产 tenant 1 的真实订单按随机价收费**。

    判据形态：逐行取 status 列，出现非 `disabled` ⇒ 红（点名是哪一行）。
    """
    match = re.search(
        r"INSERT\s+INTO\s+processing_fee_combinations\b.*?VALUES(.*?)ON\s+CONFLICT",
        migration_text(), re.S | re.I)
    assert match, "V77 没有组合价目 INSERT 段"
    bad = []
    for fields in _split_values(match.group(1)):
        assert len(fields) == 8, f"组合价目行列数不是 8: {fields}"
        status = _unquote(fields[5])
        if status != "disabled":
            bad.append((_unquote(fields[2]), status))
    assert bad == [], (
        f"合成价目里有**参与取价**的行（status != 'disabled'）：{bad[:5]}"
        f" —— 生产 tenant 1 会按随机价收费（#4525 P1 钱风险）")


def test_migration_never_prices_customer_unit_price():
    """🔴 V77 **不得**给 `customer_unit_price` 落任何价（复核裁定 (i)：列无 status 可门控）。

    取价侧判据是 `customer_unit_price IS NOT NULL`（`optionPrices` 只收非空行）⇒ 列一旦被
    合成值填充，**生产 tenant 1 的特殊选项就按随机价收费**，且没有任何 status 能挡住它。
    ⇒ 合成选项价**只作测试资产**（注释块 + 生成器），库中该列恒 `NULL` = 未定价
    （取价侧 `priced:false` + 可行动 hint，显式可见、不静默按 0 收）。

    判据：出现任何把该列写成非空值的语句 ⇒ 红。**可红性自证**见下方注入断言。
    """
    sql = migration_text()
    assert not re.search(r"SET\s+customer_unit_price\s*=", sql, re.I), \
        "V77 里出现了 `SET customer_unit_price = …` ⇒ 合成选项价会参与真实取价（#4525 P1）"
    # 注入式自证：同形态的语句必须被本条判据照出来
    injected = "UPDATE production_route_rules AS r SET customer_unit_price = 9.99 FROM (VALUES (1)) v;"
    assert re.search(r"SET\s+customer_unit_price\s*=", injected, re.I), \
        "本判据读不出注入的 `SET customer_unit_price =` ⇒ 它是空断言"
    # 生成器仍保留 16 条合成价作为**测试资产**（可重算、逐值相同）
    options = synthetic.option_rows()
    assert len(options) == 16
    assert {o["source"] for o in options} == {"synthetic"}


# ══════════════════════════ ② 种子（设计 §7）══════════════════════════

def test_combination_seed_is_exactly_92_rows():
    """组合价目 = **92 行**（91 组合 + `缎带`），且键唯一、单价落在 3.00~15.00 元/米。"""
    rows = combination_seed_rows(migration_text())
    assert len(rows) == 92, f"组合价目不是 92 行：{len(rows)}"
    assert "缎带" in rows, "92 行里缺 `缎带`（设计 §7 冻结：91 组合 + 缎带）"
    for key, (price, _source, _items) in rows.items():
        assert 3.00 <= float(price) <= 15.00, f"{key} 的单价 {price} 不在 3.00~15.00 元/米"


def test_seed_rows_match_the_deterministic_generator():
    """迁移里的种子必须**逐值**等于固定种子生成器的重算结果（「两次生成逐值相同」判据 9）。

    反例（本测试要挡的形态）：种子被手改一个字（改价 / 改名 / 改 source）⇒ 定价不再可复现，
    而取价逻辑照样绿（它只读库）⇒ 缺陷只有本判据照得出来。
    """
    expected = {row["composition_key"]: (row["unit_price"], row["source"], tuple(row["items"]))
                for row in synthetic.combination_rows()}
    assert len(expected) == 92
    assert combination_seed_rows(migration_text()) == expected, \
        "V77 的组合价目与固定种子生成器不一致（改价/改名必须同时改生成器，反之亦然）"


def test_seed_is_deterministic_across_two_runs():
    """两次生成**逐值相同**（固定种子；运行期随机 ⇒ 不可复现的定价 = 不可复现的订单金额）。"""
    assert synthetic.combination_rows() == synthetic.combination_rows()
    assert synthetic.option_rows() == synthetic.option_rows()
    assert synthetic.fixture_document() == synthetic.fixture_document()


def test_seed_carries_synthetic_provenance():
    """种子必须显式标 `source='synthetic'`（设计 §7 硬约束 ②：防测试价被当成真实价目）。"""
    rows = combination_seed_rows(migration_text())
    assert {source for _price, source, _items in rows.values()} == {"synthetic"}, \
        "组合价目里出现了非 synthetic 的来源标记（测试价不得冒充真实价目）"
    assert {row["source"] for row in synthetic.option_rows()} == {"synthetic"}


def test_priced_option_rows_are_exactly_the_option_rules():
    """合成选项价 = **16 条** `trigger_kind='option'` 规则行，逐条点名（设计 §4.1 + §7 的冲突登记）。

    逐条点名而不是只数条数：少一条 = 那个选项在测试资产里缺失（无从核对「未定价 vs 定价」两层）。

    ⚠️ 这些价**不落库**（复核裁定 (i)）⇒ 判据落在**生成器**上，并由
    `test_migration_never_prices_customer_unit_price` 保证迁移不把它们写进库。
    """
    options = synthetic.option_rows()
    expected_ids = {row["rule_id"] for row in options}
    assert len(options) == 16, f"合成选项价不是 16 条：{len(options)}"
    assert len(expected_ids) == 16
    assert len({row["name"] for row in options}) == 16
    # 19 项里没有 `option` 规则行的 3 项**不得**被定价（造规则行会违反 §4.1 与 R11 边界）
    assert len(synthetic.UNPRICED_BY_DESIGN) == 3
    assert set(synthetic.UNPRICED_BY_DESIGN) & {row["name"] for row in options} == set()
    for row in options:
        assert 1.00 <= float(row["unit_price"]) <= 10.00, \
            f"{row['rule_id']} 的单价 {row['unit_price']} 不在 1.00~10.00 元/套"
    # 逐条落在 V71 的 16 条 option 规则行上（id 形态可核）
    assert all(re.fullmatch(r"rr-v70-\d{2}", rid) for rid in expected_ids)


def test_schema_sql_carries_the_new_column():
    """bootstrap 路径（`docs/sql/schema.sql`）必须同步终态 —— 该路径**不跑迁移链**。

    漏同步 = 全新库（CI / 本地 docker 栈）建库后取价读不到列（形态见 #3270）。
    """
    sql = SCHEMA.read_text(encoding="utf-8")
    assert re.search(r"customer_unit_price\s+NUMERIC\(12,\s*2\)", sql, re.I), \
        "docs/sql/schema.sql 缺少 customer_unit_price 列（bootstrap 库与迁移库不一致）"


def test_e2e_fixture_is_the_rebuilt_feature_dictionary():
    """e2e fixture = **重建后的 L2 特征词典**（设计 §7：换掉旧的 13 条编造数据）。

    判据：① 旧的编造条目（`魔术贴安装` / `铅坠安装` / `高温定型`…）**一个都不剩**；
    ② 新条目带 `source='synthetic'`；③ 逐值等于生成器（两次生成相同）。
    """
    assert FIXTURE.exists(), f"fixture 缺失：{FIXTURE}"
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    items = document["data"]["items"]
    assert items == synthetic.fixture_items(), "fixture 与生成器不一致（改生成器后要重新写盘）"
    names = {item["name"] for item in items}
    stale = {"魔术贴安装", "铅坠安装", "高温定型", "普通定型", "罗马杆环安装", "S钩安装",
             "四爪钩安装", "包边处理", "双折边", "单折边"}
    assert not (names & stale), f"旧的编造数据还在 fixture 里：{sorted(names & stale)}"
    assert {item["source"] for item in items} == {"synthetic"}
    assert document["data"]["total"] == len(items)


# ══════════════════════════ ④ 两套账不互读（判据 10）══════════════════════════

def java_main_sources() -> list:
    return sorted(JAVA_MAIN.rglob("*.java"))


def customer_price_reads(sources) -> list:
    """读 `customer_unit_price` / `getCustomerUnitPrice` 的**文件相对路径**（allowlist 之外）。"""
    hits = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if "customer_unit_price" in text or "CustomerUnitPrice" in text:
            try:
                rel = str(path.relative_to(REPO))
            except ValueError:
                rel = str(path)
            if rel not in CUSTOMER_PRICE_READ_ALLOWLIST:
                hits.append(rel)
    return hits


def test_piecework_paths_never_read_customer_unit_price():
    """计件路径**零读取** `customer_unit_price`（判据 10；设计 §4.1 的两套账不互读）。

    列名带 `customer_` 前缀的全部理由就是让这条纪律**在 grep 层可判**：本判据扫 `main` 源码，
    只有取价层（`ProcessingFeeCalculator`）与实体字段声明可以出现该标识符。
    """
    sources = java_main_sources()
    assert sources, "没扫到任何 Java 源码 ⇒ 本判据是空跑"
    hits = customer_price_reads(sources)
    assert hits == [], (
        f"`customer_unit_price` 出现在取价层之外（两套账互读）：{hits}；"
        f"allowlist={sorted(CUSTOMER_PRICE_READ_ALLOWLIST)}")


def test_piecework_read_guard_detects_injected_read(tmp_path):
    """注入式自证：往**临时副本**里塞一处假读取 ⇒ 守卫必须照出来（否则它是空断言）。"""
    (tmp_path / "PieceworkService.java").write_text(
        "class PieceworkService { void x() { rule.getCustomerUnitPrice(); } }", encoding="utf-8")
    sources = [tmp_path / "PieceworkService.java"]
    assert customer_price_reads(sources) == [str(tmp_path / "PieceworkService.java")]
    # 反向：allowlist 里的文件不算命中
    allowed = REPO / next(iter(CUSTOMER_PRICE_READ_ALLOWLIST))
    assert customer_price_reads([allowed]) == []


# ══════════════════════════ ⑤ R13 快照冻结（判据 11）══════════════════════════

def test_read_paths_still_read_the_persisted_detail():
    """读面仍读**落库的** `processingFeeDetail`（不重算）—— 判据 11「历史订单一字不变」。

    反例（本测试要挡的形态）：把读面改成按**当前**价目表重算 ⇒ 改一次组合价，
    所有历史订单金额跟着漂移（R13 冻结被破）。判据落在 `OrderService` 的读面接线形态上。
    """
    order_service = (JAVA_MAIN / "com/migao/admin/service/OrderService.java").read_text(encoding="utf-8")
    assert "ProcessingFeeCalculator.storedFee(" in order_service, \
        "OrderService 读面不再读落库的 processingFeeDetail（改成重算 ⇒ R13 冻结被破）"
    assert "lineAmount()" in order_service, \
        "OrderService 的行金额不再含 Σ 选项价（#4525 的 R5 口径未接线）"


# ══════════════════════════ ⑥ 注入式自证（红证）══════════════════════════

def test_parsers_detect_injected_drift():
    """改迁移里一个字（价 / source / 列名 / 规则行）⇒ 解析结果必须不等（否则比对是空断言）。"""
    sql = migration_text()
    base_combos = combination_seed_rows(sql)

    # 组合价：把第一条的单价换成另一个数（**不写死具体值**：种子会随生成器前进）
    first_combo_price = sorted(base_combos.values())[0][0]
    drifted_price = sql.replace(f", {first_combo_price},", ", 99.99,", 1)
    assert combination_seed_rows(drifted_price) != base_combos, "改组合价读不出来"

    drifted_source = re.sub(r"'synthetic'\)", "'实证')", sql, count=1)
    assert combination_seed_rows(drifted_source) != base_combos, "改 provenance 读不出来"

    # 列名判据同样可红
    assert not re.search(r"customer_unit_price\s+NUMERIC\(12,\s*2\)",
                         sql.replace("customer_unit_price NUMERIC(12,2)", "customer_price NUMERIC(12,2)"))


def test_generator_rejects_drifted_row_counts(monkeypatch):
    """注入式自证：改掉枚举的一个特征 ⇒ 行数/内容跟着变（生成器不是写死的 92 行字面量）。"""
    base = synthetic.combination_rows()
    monkeypatch.setattr(synthetic, "MODIFIERS", synthetic.MODIFIERS[:-1])
    assert synthetic.combination_rows() != base, "改可叠加特征集合读不出差异 ⇒ 生成器是写死的字面量"


if __name__ == "__main__":  # pragma: no cover - 手工排查入口
    print(f"migration={MIGRATION}")
    print(f"combos={len(combination_seed_rows(migration_text()))} "
          f"options={len(synthetic.option_rows())}")
    raise SystemExit(pytest.main([__file__, "-q"]))
