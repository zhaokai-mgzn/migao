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
| V82 没给 `option` 行落价 / 落错值 / 落错行 / 覆盖商家改价 | 特殊选项全按 0 收（白送）或**按错价收费**（改钱） | `test_v82_prices_exactly_the_option_rows` |
| 计件路径读了本列 | 对客售价泄漏成工人计件单价（两套账互读，判据 10） | `test_piecework_paths_never_read_customer_unit_price` |
| 读面改成重算 | 改价回算历史订单（R13 快照冻结被破，判据 11） | `test_read_paths_still_read_the_persisted_detail` |

## 红证（不会红的断言 = 空断言）

本文件自带**注入式自证**：`test_parsers_detect_injected_drift` 把迁移文本改一个字
（价格 / source / 列名）后必须**读得出差异**；`test_piecework_read_guard_detects_injected_read`
把一处假读取注入到**临时副本**上必须被照出来。没有这两条，上面的逐值比对与 grep 守卫
都可能「绿了但没跑」。

## 🔴 两条红线：合成组合价**不得参与取价** + 选项初始价**必须被钉死**（2026-09-19 改判）

`MigrationRunner` 在 **admin-api 启动时**执行迁移 ⇒ **生产一样会跑**；而取价侧只过滤
`status='active'`（**不按 `source` 过滤**）⇒ 任何一行 active 的合成价 = 生产 tenant 1
按随机价收费。故本文件钉两条红线：

* `test_synthetic_combination_rows_are_all_disabled` —— 92 行组合价**全部** `status='disabled'`
  （**口径不变**：组合价仍是「商家配了并启用才生效」）；
* `test_v82_prices_exactly_the_option_rows` —— **本判据由用户裁定改判**：V77 的口径是
  「迁移**不得**给 `customer_unit_price` 落任何价」（该列**无 status 可门控** ⇒ 落价即参与
  真实取价），而用户 2026-09-19 裁定「**特殊选项缺乏单价，通常按套收费**」「**特殊选项要有
  定价，随便初始化一份价格数据，单价是元/套**」⇒ 新判据 = **落价的范围与值都必须被钉死**：
  恰好 **16 条 `option` 行**、值**逐值**等于冻结清单、只在 `customer_unit_price IS NULL` 时写
  （**不覆盖商家改过的价**）、按租户（`FROM tenants`）、非 `option` 行保持 `NULL`。
  **已知代价（不粉饰）**：这 16 个**占位初始值会真的参与对客取价** —— 商家改价之前，选中这些
  特殊选项的订单就按这批价收费（用户已知并接受；改价即覆盖）。

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

MIGRATION = REPO / "backend/admin-api/src/main/resources/db/migration-archive/V77__customer_option_unit_price.sql"
V82 = REPO / "backend/admin-api/src/main/resources/db/migration-archive/V82__seed_option_customer_unit_price.sql"
SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"
FIXTURE = REPO / "tests/e2e/fixtures/processing-list.json"
JAVA_MAIN = REPO / "backend/admin-api/src/main/java"

#: `customer_unit_price` 的**唯一**合法读取点（取价层）。
#: 其它任何地方出现它 ⇒ 两套账互读（判据 10）⇒ 红。
CUSTOMER_PRICE_READ_ALLOWLIST = {
    "backend/admin-api/src/main/java/com/migao/admin/service/ProcessingFeeCalculator.java",
    # 实体字段声明本身（不是"读取"，但字符串会命中 ⇒ 显式登记，避免守卫退化成"全部命中"）
    "backend/admin-api/src/main/java/com/migao/admin/entity/ProductionRouteRule.java",
    # 配置读面（issue #4567，用户裁定「特殊选项要有定价」）：把该列**原样透出**给
    # 「工艺配置 → 条件工序规则」页的「单价（元/套）」列。**不是**计件路径。
    "backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingReadService.java",
    # 配置写面（issue #4567）：把商家填的「单价（元/套）」**原样写入**该列（含 422 逐条理由）。
    # 只写这一列，**不碰** `factor`（计件系数）—— 两套账不互读。
    "backend/admin-api/src/main/java/com/migao/admin/service/ProductionRoutingCommandService.java",
    # 写面的单列更新语句（`updateCustomerUnitPrice`：set 该列 + 租户隔离条件）
    "backend/admin-api/src/main/java/com/migao/admin/mapper/ProductionRouteRuleMapper.java",
    # 端点 javadoc 说明该键语义（无任何逻辑读取）
    "backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java",
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
        "V77 不该有任何 UPDATE（合成选项价不在 V77 落库 —— 落价走 V82，见文件头两条红线）"


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


# ── V82：16 条 `option` 行的**初始对客价**（用户裁定 2026-09-19，**推翻** V77 的「恒 NULL」）──
#
# 冻结清单 = 用户裁定的 16 个占位初始值（元/套）。⚠️ 它们**不是测试资产**：该列没有 status 可
# 门控，落库即参与对客取价 ⇒ **改这里 = 改钱**（改动必须走新迁移 + 同步改本清单 + schema.sql）。
FROZEN_OPTION_PRICES = {
    "拼1次": "3.00", "拼2次": "5.00", "拼3次": "7.00", "加花边": "4.00",
    "加铅块": "6.00", "接高": "2.50", "双眼皮接高": "5.00", "余料做绑带": "2.00",
    "布绑带": "3.00", "余料做帘头": "8.00", "抱枕": "12.00", "纱绑带": "3.00",
    "加logo条": "2.00", "加立边": "4.00", "扣环": "1.50", "防翘扣": "1.50",
}

NON_OPTION_TRIGGER_KINDS = ("craft", "shaped", "processing_item")


def _strip_sql_comments(sql: str) -> str:
    """剥掉 SQL 注释 —— 守卫必须判**真语句**（注释里写一句 `IS NULL` 不算守卫）。"""
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return re.sub(r"--[^\n]*", " ", sql)


def v82_text() -> str:
    assert V82.exists(), f"V82 迁移缺失：{V82}"
    return V82.read_text(encoding="utf-8")


def option_price_rows(sql: str) -> dict:
    """V82 的 `(VALUES …) AS v(trigger_value, unit_price)` → `{trigger_value: '元/套'}`（**逐值**）。

    ⚠️ 必须从 `AS v(trigger_value, unit_price)` 往**回**找**最近**的 `VALUES`
    —— 非贪婪的 `VALUES(.*?)…` 在 `schema.sql`（几万行、前面还有别的 `VALUES` 种子）上会
    从**文件里第一个** `VALUES` 开始吞，解析出错位的行（实测）。
    """
    end = re.search(r"\)\s*AS\s+v\s*\(\s*trigger_value\s*,\s*unit_price\s*\)", sql, re.I)
    assert end, "没有 `(VALUES …) AS v(trigger_value, unit_price)` 段"
    starts = [m.end() for m in re.finditer(r"\bVALUES\b", sql[:end.start()], re.I)]
    assert starts, "`AS v(trigger_value, unit_price)` 之前没有 `VALUES` 段"
    rows = {}
    for fields in _split_values(sql[starts[-1]:end.start()]):
        assert len(fields) == 2, f"选项价行不是 2 列（列序漂移即解析错位）: {fields}"
        rows[_unquote(fields[0])] = f"{float(fields[1]):.2f}"
    return rows


def non_option_pricing_violations(sql: str) -> list:
    """**写价面**的三条不变量（逐条返回违规说明；空列表 = 合规）。

    ① 只按 `trigger_kind = 'option'` 写价（工艺变体 / 定型 / 计件项不得被定价）；
    ② 有 `customer_unit_price IS NULL` 幂等守卫（**不覆盖商家改过的价**）；
    ③ 按租户（`FROM tenants`）—— 只覆盖 1 号租户 ⇒ 其它租户**永远没价**。

    ⚠️ **射程 = 写价语句**（issue #4589）：只认**触及 `customer_unit_price` 列**的
    `UPDATE production_route_rules`。同表还有别的 UPDATE（V86 的 `SET deleted = 1`
    软删计件系数档）—— 它不写价，三条不变量对它**不适用**；把它算进来会让本判据
    对一条合规迁移假红（「不写价」与「写错价」是两回事）。
    """
    hits = []
    for kind in NON_OPTION_TRIGGER_KINDS:
        if re.search(rf"trigger_kind\s*=\s*'{kind}'", sql, re.I):
            hits.append(f"出现了非 option 触发的写价路径：trigger_kind = '{kind}'")
    updates = [stmt for stmt in re.findall(r"\bUPDATE\s+production_route_rules\b(.*?);", sql, re.S | re.I)
               if re.search(r"customer_unit_price", stmt, re.I)]
    if not updates:
        hits.append("没有任何「写 customer_unit_price 的 `UPDATE production_route_rules …;`」语句"
                    "（解析失效 ⇒ 本判据空跑）")
    for stmt in updates:
        if not re.search(r"trigger_kind\s*=\s*'option'", stmt, re.I):
            hits.append("有一条 UPDATE 没有 `trigger_kind = 'option'` 门控")
        if not re.search(r"customer_unit_price\s+IS\s+NULL", stmt, re.I):
            hits.append("有一条 UPDATE 没有 `customer_unit_price IS NULL` 幂等守卫（会刷回商家改价）")
        if not re.search(r"\bFROM\s+tenants\b", stmt, re.I):
            hits.append("有一条 UPDATE 没有按租户（缺 `FROM tenants` ⇒ 其它租户永远没价）")
    return hits


def test_v82_prices_exactly_the_option_rows():
    """🔴 V82 必须**恰好**给 16 条 `option` 规则行定价，值**逐值**等于冻结清单（用户裁定 2026-09-19）。

    **改判沿革**：本判据前身是 `test_migration_never_prices_customer_unit_price`
    （「迁移**不得**给 `customer_unit_price` 落任何价」）。V77 的顾虑 —— 该列**无 status 可门控**
    ⇒ 落价即参与真实取价 —— **依然成立**；但用户 2026-09-19 裁定「特殊选项缺乏单价，通常按套收费」
    「特殊选项要有定价，随便初始化一份价格数据，单价是元/套」⇒ 判据从「不许落价」改判为
    **「落价的范围与值都必须被钉死」**。新判据**更强**：原判据只挡「有没有落价」，
    新判据还挡「落错值 / 落错行 / 覆盖商家改价 / 只覆盖 1 号租户」。

    **已知代价（不粉饰）**：这 16 个占位值**会真的参与对客取价**（取价侧只判 `IS NOT NULL`）。
    """
    sql = _strip_sql_comments(v82_text())
    rows = option_price_rows(sql)
    assert len(rows) == 16, f"V82 定价的 option 行不是 16 条：{len(rows)} —— {sorted(rows)}"
    assert rows == FROZEN_OPTION_PRICES, (
        f"V82 的价与冻结清单不一致（**改价 = 改钱**）：\n  迁移 = {rows}\n  清单 = {FROZEN_OPTION_PRICES}")
    violations = non_option_pricing_violations(sql)
    assert violations == [], "V82 写价面违反不变量：" + "; ".join(violations)
    assert re.search(r"customer_unit_price\s+IS\s+NULL", sql, re.I), \
        "V82 缺 `customer_unit_price IS NULL` 幂等守卫"
    assert re.search(r"\bFROM\s+tenants\b", sql, re.I), \
        "V82 缺 `FROM tenants` ⇒ 只覆盖 1 号租户，其它租户永远没价"


def test_v82_guard_detects_injected_drift():
    """**红证（注入式）**：改价 / 少一项 / 落错行 / 去掉守卫 / 去掉按租户 ⇒ 上面每条断言都会红。

    没有这一条，「逐值比对」与「三条不变量」都可能是空断言（不会红的断言 = 空断言）。
    """
    sql = _strip_sql_comments(v82_text())
    base = option_price_rows(sql)
    assert base, "解析出的选项价为 0 条 ⇒ 后续比对是空断言"

    # ① 改一个价 ⇒ 逐值比对必须读出差异
    drifted = sql.replace("('拼1次', 3.00)", "('拼1次', 9.99)")
    assert option_price_rows(drifted) != base, "改价读不出来 ⇒ 逐值比对是空断言"
    # ② 少一项 ⇒ 条数比对必须读出差异
    assert len(option_price_rows(sql.replace("('拼1次', 3.00),", "", 1))) == 15, "少一项读不出来"
    # ③ 落错行（非 option 触发）⇒ 不变量 ① 必须报出
    assert non_option_pricing_violations(
        sql + "UPDATE production_route_rules SET customer_unit_price = 1.00 "
              "WHERE trigger_kind = 'craft' AND customer_unit_price IS NULL;"), "落错行读不出来"
    # ④ 去掉 `IS NULL` 守卫 ⇒ 不变量 ② 必须报出
    assert non_option_pricing_violations(sql.replace("customer_unit_price IS NULL", "TRUE")), \
        "去掉幂等守卫读不出来"
    # ⑤ 去掉按租户 ⇒ 不变量 ③ 必须报出
    assert non_option_pricing_violations(sql.replace("FROM tenants t,", "", 1)), \
        "去掉按租户读不出来"


def test_schema_sql_carries_the_same_option_prices():
    """bootstrap 终态（`backend/admin-api/src/main/resources/db/init/schema.sql`）必须带**同源同值**的写价语句。

    该路径**不跑迁移链**（docker-entrypoint-initdb.d）⇒ 只改 V82 = 新建库（CI / 本地 docker 栈）
    选项全无价（同 #3270 形态）。判据 = 与 V82 **同一解析器**、逐值相等。
    """
    sql = _strip_sql_comments(SCHEMA.read_text(encoding="utf-8"))
    assert option_price_rows(sql) == FROZEN_OPTION_PRICES, \
        "schema.sql 的选项初始价与 V82 不同源（bootstrap 库与迁移库分叉）"
    assert non_option_pricing_violations(sql) == [], "schema.sql 的写价面违反不变量"


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

    ⚠️ 生成器里的 16 条合成价是**测试资产**（可重算）；**对客取价的真值源是 V82 的 16 条初始价**
    （用户裁定 2026-09-19）⇒ 本判据只钉「选项清单恰好 16 项」，**落价的范围与值**由
    `test_v82_prices_exactly_the_option_rows` 钉死。
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
    """bootstrap 路径（`backend/admin-api/src/main/resources/db/init/schema.sql`）必须同步终态 —— 该路径**不跑迁移链**。

    漏同步 = 全新库（CI / 本地 docker 栈）建库后取价读不到列（形态见 #3270）。
    """
    sql = SCHEMA.read_text(encoding="utf-8")
    assert re.search(r"customer_unit_price\s+NUMERIC\(12,\s*2\)", sql, re.I), \
        "backend/admin-api/src/main/resources/db/init/schema.sql 缺少 customer_unit_price 列（bootstrap 库与迁移库不一致）"


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


#: Java 的**字面量 ∪ 注释**词法扫描（顺序敏感：字面量必须排在注释之前）。
#: 为什么不能按 `//` 粗暴切行：Java 字符串里可能含 `//`（如 `"http://x"`），
#: 那样会把**同一行后面的真实读取**一起删掉 ⇒ 制造假绿（issue #4595 的取舍点）。
_JAVA_LEX_RE = re.compile(
    r'"""(?:\\.|[^\\])*?"""'      # 文本块（Java 15+；本仓 MigrationRunner 在用）
    r'|"(?:\\.|[^"\\])*"'         # 字符串字面量
    r"|'(?:\\.|[^'\\])*'"         # 字符字面量
    r'|//[^\n]*'                  # 行注释
    r'|/\*.*?\*/',                # 块注释
    re.S)


def java_code_only(text: str) -> str:
    """去掉 Java **注释**、**保留字面量** —— 本判据只认「代码里的读取」，不认「注释里的提及」。

    ## 为什么必须去注释（issue #4595，实证）

    旧实现是**裸子串扫描**（`if "customer_unit_price" in text`）：任何文件只要**提到**这个列名
    ——包括**把账本边界写清楚的 javadoc**（本仓鼓励的做法）—— 就被判成「计件路径越界读取」。
    实证：#4587 的两个新文件（矩阵写面 service + 版本账 entity）**一行读取都没有**，
    命中全部来自 javadoc 里那句「对客定价在别处：… `production_route_rules.customer_unit_price`」。

    ⚠️ 按仓库纪律，**不许靠改措辞绕过判据**（那等于把判据变成「谁不写注释谁通过」）⇒
    修**判据**：语义（docstring 自述）本来就是「读了这一列」，实现必须与之对齐。

    ⚠️ **判别力不降**（本单红线，见 `test_piecework_read_guard_still_catches_code_reads`）：
    字符串字面量**原样保留**（SQL 里的列名仍是真实读取），只有注释被换成空格。
    """
    def keep(match: "re.Match") -> str:
        token = match.group(0)
        return token if token[0] in '"\'' else " "

    return _JAVA_LEX_RE.sub(keep, text)


def customer_price_reads(sources) -> list:
    """读 `customer_unit_price` / `getCustomerUnitPrice` 的**文件相对路径**（allowlist 之外）。

    ⚠️ 只看**代码**（注释已剔除，见 {@link java_code_only}）：注释里提及列名不算读取。
    """
    hits = []
    for path in sources:
        text = java_code_only(path.read_text(encoding="utf-8"))
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
    只有**取价层**（`ProcessingFeeCalculator`）、**实体字段声明**、以及 **issue #4567 起新增的
    配置面**（读面 `ProductionRoutingReadService` + 端点 `ProductionController`：用户裁定
    「特殊选项要有定价」⇒ 商家必须能看见并改这个价）可以出现该标识符。

    ⚠️ **这不是放宽计件纪律**：配置面只做「原样透出 / 原样写入」，不参与任何计件计算；
    两套账的实质边界（`factor` 与 `customer_unit_price` 不互读）由
    `ProcessingFeeCalculatorTest::customerFeeNeverReadsPieceworkFactor` 独立钉住。
    新增**任何其它**文件**在代码里读取**该标识符 ⇒ 仍判红。

    ⚠️ **只看代码、不看注释**（issue #4595 改判）：旧实现是裸子串扫描 ⇒ 把 javadoc 里
    「解释账本边界」的**提及**当成越界读取（实证：#4587 的两个新文件零读取却被判红）。
    按仓库纪律不许靠改措辞绕门禁 ⇒ 判据改为**剔除注释后**再扫（字面量保留，SQL 里的列名仍算读取）。
    两条反向/正向自证见 `test_piecework_read_guard_ignores_comment_mentions` 与
    `test_piecework_read_guard_still_catches_code_reads`。
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


def test_piecework_read_guard_ignores_comment_mentions(tmp_path):
    """注释里**提及**列名不算读取（issue #4595 的改判点；改前此断言必红）。

    病灶实证：#4587 的两个新文件（矩阵写面 service + 版本账 entity）**一行读取都没有**，
    只因 javadoc 里写了「对客定价在别处：… `customer_route_rules.customer_unit_price`」
    就被旧实现判成越界读取 ⇒ CI 红。
    """
    # ① 行注释 + ② javadoc 块注释：两种形态都不得算命中
    (tmp_path / "LineComment.java").write_text(
        "class A {\n  // 对客价在 production_route_rules.customer_unit_price（元/套）\n  int x = 1;\n}\n",
        encoding="utf-8")
    (tmp_path / "BlockComment.java").write_text(
        "/**\n * 对客价 = {@code customer_unit_price}（元/套）\n * getCustomerUnitPrice 也不在本类读\n */\nclass B { int y = 2; }\n",
        encoding="utf-8")
    assert customer_price_reads([tmp_path / "LineComment.java"]) == [], "行注释里的提及被误判成读取"
    assert customer_price_reads([tmp_path / "BlockComment.java"]) == [], "块注释里的提及被误判成读取"


def test_piecework_read_guard_still_catches_code_reads(tmp_path):
    """判别力不许降（本单红线）：**代码里**的读取/字面量仍必须被照出来。

    三条形态各一：① 方法调用；② 字符串字面量（SQL 列名是真实读取）；
    ③ **字符串里含 `//`**（`"http://x"`）时，**同一行后面的读取**仍要被抓到
    —— 这条专治「按 `//` 粗暴切行」的假绿修法。
    """
    (tmp_path / "Call.java").write_text(
        "class C { void z() { rule.getCustomerUnitPrice(); } }", encoding="utf-8")
    (tmp_path / "Sql.java").write_text(
        'class D { String q = "SELECT customer_unit_price FROM production_route_rules"; }',
        encoding="utf-8")
    (tmp_path / "Tricky.java").write_text(
        'class E { String u = "http://x"; BigDecimal p = rule.getCustomerUnitPrice(); }',
        encoding="utf-8")
    for name in ("Call.java", "Sql.java", "Tricky.java"):
        assert customer_price_reads([tmp_path / name]) == [str(tmp_path / name)], \
            f"{name} 里的代码读取被漏判（判别力下降 = 本单红线）"


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
