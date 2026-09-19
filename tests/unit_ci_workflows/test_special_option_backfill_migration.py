# case_ids: PG-020
"""特殊选项**旧名存量回填**迁移的静态守卫（issue #4399）。

## 病根

特殊选项名是「订单选配 → 车间工序 / 计件系数」的 **join key**。V65 只把**配置表**改成了 ERP 名，
**订单与加工单快照里的旧名**没回填 ⇒ 改名后生成加工单时查不到 ⇒ **条件工序不插、系数退回 1.0 = 少发工人钱**。

实况（2026-09-19 全量实测 781 张订单）：`{'一分二': 3}` ⇒ **非 0 行，缺陷是真的**。

## 本文件钉的四件事（每件都有红证）

1. **两处载体都覆盖** —— 漏一处 = 老订单回填了、它的加工单快照还是旧名；
2. **按数组元素替换**（不是对整段 JSONB 文本裸 `replace`）——
   `一分二` 是 `一分为二` 的**子串**，裸 replace 会把已正确的新名改成 `一一分为二`；
3. **保序** —— `jsonb_agg` 不带 `ORDER BY` 时顺序未定义 ⇒ 必须 `WITH ORDINALITY` + `ORDER BY`；
4. **幂等守卫** —— 带「仍含旧名」的 `@>` 条件 ⇒ 重跑空转。

**红证**：把任一载体删掉 / 改成 `replace(processing_info::text, …)` / 去掉 `ORDER BY` /
去掉 `@>` 守卫 ⇒ 对应判据红。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration"
V74_NAME = "V74__backfill_legacy_special_option_names.sql"

OLD_NAME = "一分二"
NEW_NAME = "一分为二"


def _sql() -> str:
    path = MIGRATION_DIR / V74_NAME
    assert path.exists(), (
        f"规格锚点变了：找不到 {path} —— issue #4399 的回填迁移（若改号，请同步本守卫）"
    )
    return path.read_text(encoding="utf-8")


def _balanced_calls(sql: str, func: str) -> list:
    """取 `func(...)` 的**完整**调用文本（按括号配平，能跨 CASE/子查询）。

    ⚠️ 为什么不用「非贪婪正则」提取：：`jsonb_agg` 的参数里含
    `CASE … END` 与子查询（还有嵌套的 `jsonb_agg`）⇒ 非贪婪正则会在**第一个 `)`** 处截断，
    把「有 ORDER BY」的调用误判成「没有」（假红）。本助手是纯文本扫描，不依赖正则。
    """
    out = []
    for m in re.finditer(re.escape(func) + r"\s*\(", sql):
        i = m.end() - 1          # 指向 '('
        depth = 0
        for j in range(i, len(sql)):
            if sql[j] == "(":
                depth += 1
            elif sql[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append(sql[m.start():j + 1])
                    break
    return out


def test_migration_exists_and_targets_the_confirmed_old_name():
    """自证 + 判据 0：迁移存在，且**同时**出现旧名与新名（否则改了个寂寞）。"""
    sql = _sql()
    assert OLD_NAME in sql, f"迁移里没有旧名 {OLD_NAME!r}"
    assert NEW_NAME in sql, f"迁移里没有 ERP 新名 {NEW_NAME!r}"


def test_both_carriers_are_covered():
    """判据 1：**两处载体**都要回填（订单 + 加工单快照）。"""
    sql = _sql()
    missing = []
    if not re.search(r"UPDATE\s+orders\b", sql, re.I):
        missing.append("orders（订单侧 processing_info）")
    if not re.search(r"UPDATE\s+processing_orders\b", sql, re.I):
        missing.append("processing_orders（加工单快照 items_snapshot）")
    assert not missing, (
        f"回填只覆盖了一部分载体，缺：{missing} ⇒ "
        f"漏一处 = 老订单回填了、它的加工单快照还是旧名（旧名仍在库里 ⇒ 缺陷仍在）"
    )


def test_replaces_by_array_element_not_raw_text():
    """判据 2：**按数组元素**替换，**不得**对整段 JSONB 文本裸 `replace`。"""
    sql = _sql()
    # 反例形态：对 jsonb 文本做 replace（`一分二` 是 `一分为二` 的子串 ⇒ 会把新名改成 `一一分为二`）
    assert not re.search(r"replace\s*\(\s*\w*\.?\s*(processing_info|items_snapshot)\s*::\s*text", sql, re.I), (
        "回填用了「对整段 JSONB 文本 replace」—— `一分二` 是 `一分为二` 的子串，"
        "裸 replace 会把**已经正确的新名**再改一次（`一分为二` → `一一分为二`）并可能误伤其它字段。"
        "必须按 `specialOptions` **数组元素**逐个比对替换。"
    )
    assert re.search(r"jsonb_array_elements_text\s*\(", sql, re.I), (
        "回填没有按数组元素展开（缺 `jsonb_array_elements_text`）⇒ 无法只改 `specialOptions` 的元素"
    )


def test_preserves_element_order():
    """判据 3：**保序** —— `jsonb_agg` 不带 `ORDER BY` 时顺序未定义。"""
    sql = _sql()
    aggs = _balanced_calls(sql, "jsonb_agg")
    assert aggs, "没有找到 jsonb_agg（重建数组）"
    unordered = [a for a in aggs if not re.search(r"ORDER\s+BY\b", a, re.I)]
    assert not unordered, (
        f"有 {len(unordered)} 处 `jsonb_agg(...)` 没有 `ORDER BY` ⇒ "
        f"`specialOptions` 的**元素顺序未定义**（选项顺序是展示与排查依据，不该被回填打乱）。"
        f"修法：`jsonb_array_elements_text(...) WITH ORDINALITY AS t(elem, ord)` + `ORDER BY ord`。"
    )
    assert re.search(r"WITH\s+ORDINALITY", sql, re.I), "缺 `WITH ORDINALITY`（保序所需的位次列）"


def test_is_idempotent_by_containment_guard():
    """判据 4：**幂等** —— 每条 UPDATE 都要带「仍含旧名」的 `@>` 守卫（重跑空转）。"""
    sql = _sql()
    updates = re.findall(r"UPDATE\s+(?:orders|processing_orders)\b[\s\S]*?;", sql, re.I)
    assert len(updates) == 2, f"预期 2 条 UPDATE（两处载体），实得 {len(updates)}"
    for stmt in updates:
        assert "@>" in stmt, (
            "有一条 UPDATE 没有 `@>` 包含守卫 ⇒ **不幂等**：重跑会再次改写"
            "（虽然元素替换是等值的，但缺守卫就无法证明「重跑空转」，"
            "且脏数据下可能反复重写整列）。"
        )


def test_does_not_touch_schema_sql():
    """判据 5：本迁移是**数据**回填 ⇒ **不得**改 schema（bootstrap 路径无需镜像）。"""
    sql = _sql()
    assert not re.search(r"\b(ALTER\s+TABLE|CREATE\s+TABLE|DROP\s+TABLE|CREATE\s+INDEX)\b", sql, re.I), (
        "回填迁移里出现了 DDL —— 本单只改**数据**，不动 schema（`docs/sql/schema.sql` 无需镜像）"
    )
