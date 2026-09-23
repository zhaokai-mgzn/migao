# case_ids: PG-020, MC-012
"""`V92` 套号落库迁移（issue #4698 切片 ⓪）的**静态承重判据** —— 扫码报工闭环的**数据层地基**。

设计依据：`docs/design/set-code-and-scan-loop.md`（#4691 已合并）§2 / §11 / §12 / §14；
用户裁定：**一樘窗 = 一套** / **套号要落库** / **一部位一码** / **A 模式**。

## 被测对象

`backend/admin-api/src/main/resources/db/migration-archive/V92__add_processing_order_sets_and_scan_loop.sql`
= ① `processing_order_sets`（一单 × 一套，两个唯一键）② `processing_set_part_tokens`（一部位一码）
③ 工序实例六列（全可空）④ 卡点索引 ⑤ 存量回填（套行）⑥ 实例行回填 ⑦ 软停读数 ⑧ 硬停断言。

## 为什么判据落在**迁移文本**上（而不是「跑一遍库看结果」）

仓库**没有 testcontainers**（`test_v89_fabric_seed_backfill.py` 同款边界）⇒ 表内容判据只能落成
静态判据 + **真库核查记录**（记录在 PR body：本机 PG 上跑了两遍 + 五条停止条件逐条注入）。
静态判据的价值不是「等价于跑库」，而是把**口径钉在可 review 的文本上**：
唯一键与理由 / 序号只增不复用 / 回填唯一输入 / 幂等形态 / 红线表零写入 / 停止条件 —— 任一处漂移都会红
（每条都有注入式红证，见 `TestInjectedDrift`）。

## 本文件钉的六件事（每件都有红证）

1. **载体与唯一键**（§2.2）：两个唯一键**各有理由**，缺任一个 ⇒ 红；
2. **序号只增不复用**（§2.4 / 用户裁定）：号池上界的 `MAX` 查询**不带 `deleted = 0`**
   —— 带上它 ⇒ 软删行不再占号 ⇒ **已删号会被复用**（红证）；
3. **回填只读 `items_snapshot`**（§2.5）：出现 `FROM order_items` / `JOIN order_items` ⇒ 红
   （读现值 = 回填结果不可复现）；
4. **幂等形态**：`ON CONFLICT … DO NOTHING` + `IS DISTINCT FROM` 守卫 + 全套 `IF NOT EXISTS`；
5. **红线**：`production_work_logs` / `qr_token` 零写入；回填 UPDATE 的 `SET` 子句
   **只允许 `set_id` / `set_no`**（既有列零赋值 ⇒「历史值一字不动」可机械核验）；
6. **停止条件可执行**：S1~S5 是 `RAISE EXCEPTION`（立即停）+ 软停①~⑤ 是 `RAISE WARNING`（不中止），
   且**逐条不空转**（各自的判据谓词都在）。

## 边界（如实登记）

本片**只落数据层**：`processing_set_part_tokens` **不种行**（码在打印时生成）、实例六列中的
C 模式三列**零消费者**；`granularity` 降级形态是**响应字段**（读时派生）不是列 ⇒ 不在本片。
扫码解析 / 工序推断（切片 ①）、完成主闭环（②）、卡点报表（③）、防呆④⑤（④）**仍在 #4698 未完成**。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATION_DIR = REPO / "backend/admin-api/src/main/resources/db/migration-archive"
LEDGER = Path(__file__).resolve().parent / "migration_fingerprints.json"
SCHEMA = REPO / "backend/admin-api/src/main/resources/db/init/schema.sql"

MIGRATION = MIGRATION_DIR / "V92__add_processing_order_sets_and_scan_loop.sql"
#: 回滚 = **新迁移**（设计 §11.4）。⚠️ **只登记、不落码** —— 落码即会被 `MigrationRunner`
#: 当场执行（它按文件名顺序跑全部未记账迁移）⇒ 把本迁移立刻撤销。与 V88 / V89 同款处置。
ROLLBACK_NAME = "V93__rollback_processing_order_sets_and_scan_loop.sql"

SETS_TABLE = "processing_order_sets"
TOKENS_TABLE = "processing_set_part_tokens"
INSTANCE_TABLE = "processing_position_operations"
#: 红线：报工快照表（历史工资不回溯）—— 本文件**零写入**。
RED_LINE_TABLES = ("production_work_logs",)

#: 设计 §2.2 逐列（列名 → 类型片段）。少一列 / 类型漂移 ⇒ 红。
SETS_COLUMNS = {
    "id": "VARCHAR(64) PRIMARY KEY",
    "tenant_id": "BIGINT NOT NULL REFERENCES tenants(id)",
    "processing_order_id": "VARCHAR(64) NOT NULL REFERENCES processing_orders(id)",
    "set_index": "INT NOT NULL",
    "set_no": "VARCHAR(64) NOT NULL",
    "craft_line_id": "VARCHAR(64)",
    "position_item_ids": "JSONB NOT NULL DEFAULT '[]'",
    "created_at": "TIMESTAMP WITH TIME ZONE",
    "updated_at": "TIMESTAMP WITH TIME ZONE",
    "deleted": "INTEGER NOT NULL DEFAULT 0",
}

#: 工序实例六列（设计 §11.2 ④：**全部可空**，存量行留空）
INSTANCE_NEW_COLUMNS = ("set_id", "set_no", "done_at", "worker_id", "worker_name", "started_at")


def _strip_comments(sql: str) -> str:
    """剥掉 SQL 注释后再做文本判据。

    ⚠️ **必须剥**：本迁移的头注释**逐条描述**红线与停止条件（含 `production_work_logs`、
    `qr_token`、`MAX(set_index)` 等字样）⇒ 不剥注释会把说明文字当成真实 SQL，产生**假红**
    （本仓已两次栽在这上面：V74 守卫、V88 守卫）。
    """
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    return re.sub(r"--[^\n]*", " ", sql)


def _strip_literals(sql: str) -> str:
    """把 `'…'` 字符串字面量抹平（**保留空串形态**）。

    ⚠️ **必须抹**（与「必须剥注释」同因）：`COMMENT ON TABLE processing_set_part_tokens IS '…与
    processing_orders.qr_token 同格式…'` 是**文档性字符串**，不是 SQL 引用 ⇒ 不抹会把说明文字
    当成「迁移碰了 qr_token」= **假红**（本仓已有两次同类教训：V74 / V88 守卫）。
    """
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _sql() -> str:
    assert MIGRATION.is_file(), (
        f"规格锚点变了：找不到 {MIGRATION.name} —— issue #4698 切片 ⓪ 的套号落库迁移"
        f"（若改号，请同步本守卫与 migration_fingerprints.json）"
    )
    return MIGRATION.read_text(encoding="utf-8")


def _table_block(sql: str, table: str) -> str:
    m = re.search(
        r"CREATE TABLE IF NOT EXISTS\s+" + re.escape(table) + r"\s*\(([\s\S]*?)\n\);", sql, re.I)
    assert m, f"迁移里没有 `CREATE TABLE IF NOT EXISTS {table} (...)`"
    return m.group(1)


def _update_set_columns(sql: str) -> list:
    """取 `UPDATE <表> SET …` 的赋值列清单（按表）。

    与 `test_migration_references_exist_in_schema.py::_update_set_columns` **同款**：
    `UPDATE orders SET processing_info = …` 那种**不带表前缀**的写法才是真缺陷形态
    （只查 `表.列` 限定引用会漏掉它）。
    """
    out = []
    for m in re.finditer(
            # ⚠️ 必须允许 `UPDATE t alias SET`（本迁移用的就是别名形态 `o`）。仓库共享守卫
            # `test_migration_references_exist_in_schema._update_set_columns` 的正则**不支持别名**
            # ⇒ 对本文件的 UPDATE 是**盲的**（实测）—— 本助手补上，红线的机械核验才落在真语句上。
            r"\bUPDATE\s+([a-z_][a-z0-9_]*)(?:\s+[a-z_][a-z0-9_]*)?\s+SET\s+([\s\S]*?)(?:\bWHERE\b|;)",
            sql, re.I):
        table, assignments = m.group(1).lower(), m.group(2)
        cols = []
        for a in re.split(r",(?![^()]*\))", assignments):
            cm = re.match(r"\s*([a-z_][a-z0-9_]*)\s*=", a, re.I)
            if cm:
                cols.append(cm.group(1).lower())
        out.append((table, cols))
    return out


def _cte_body(sql: str, name: str) -> str:
    """取 `"name" AS ( … )` 的完整体（按括号配平，能跨 CASE/子查询）。"""
    m = re.search(r'"' + re.escape(name) + r'"\s+AS\s*\(', sql, re.I)
    assert m, f"迁移里没有 CTE `{name}`"
    start = m.end() - 1
    depth = 0
    for i in range(start, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[start + 1:i]
    raise AssertionError(f"CTE `{name}` 括号不配平")


# ── 判据本体（**入参是 SQL 文本** ⇒ 注入式红证可直接复用）────────────────────────

def _check_carriers_and_unique_keys(sql: str) -> None:
    """判据 1：两张载体表 + **四个**唯一键（套表两个 / 码表两个）。"""
    sets_block = _table_block(sql, SETS_TABLE)
    for col, type_frag in SETS_COLUMNS.items():
        assert re.search(r"\b" + col + r"\s+" + re.escape(type_frag), sets_block), (
            f"`{SETS_TABLE}.{col}` 缺失或类型漂移（设计 §2.2 逐列；期望 `{type_frag}`）"
        )
    tokens_block = _table_block(sql, TOKENS_TABLE)
    for col in ("tenant_id", "processing_order_id", "set_id", "order_item_id", "position_kind",
                "token", "print_count"):
        assert re.search(r"\b" + col + r"\s+", tokens_block), f"`{TOKENS_TABLE}.{col}` 缺失"

    expect = {
        "uk_processing_order_sets_index": r"\(\s*tenant_id\s*,\s*processing_order_id\s*,\s*set_index\s*\)",
        "uk_processing_order_sets_no": r"\(\s*tenant_id\s*,\s*set_no\s*\)",
        "uk_set_part_tokens_token": r"\(\s*token\s*\)",
        "uk_set_part_tokens_part": r"\(\s*tenant_id\s*,\s*set_id\s*,\s*order_item_id\s*\)",
    }
    for name, cols in expect.items():
        m = re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS\s+" + name + r"\b([\s\S]*?);", sql, re.I)
        assert m, f"缺唯一索引 `{name}`（设计 §2.2 指定；缺它 ⇒ 并发建套/扫码解析无库层兜底）"
        body = m.group(1)
        assert re.search(cols, body, re.I), f"`{name}` 的列清单与设计不符（期望 {cols}）"
        assert re.search(r"WHERE\s+deleted\s*=\s*0", body, re.I), (
            f"`{name}` 必须是**部分**唯一索引（`WHERE deleted = 0`，设计 §2.2 逐字）"
        )


def _check_set_no_format(sql: str) -> None:
    """判据 2：套号 = `{processing_order_no}-{3 位零填充 set_index}`（设计 §2.1）。"""
    assert re.search(
        r"processing_order_no\s*\|\|\s*'-'\s*\|\|\s*lpad\(\s*\w*\.?new_index::text\s*,\s*3\s*,\s*'0'\s*\)",
        sql, re.I), (
        "套号格式不符设计 §2.1：必须是 `{processing_order_no}-{lpad(set_index,3,'0')}`"
        "（3 位零填充是与真值源「第 14 套/共 22 套」同形的要求；不加填充 ⇒ 排序不稳）"
    )


def _check_monotonic_never_reuses_deleted(sql: str) -> None:
    """判据 3（**用户裁定的反向护栏**）：号池上界的 `MAX` **不带 `deleted = 0`**。

    这是「已删的号不回收」的**唯一实现方式**（设计 §2.4 规则 1）：软删行仍占号 ⇒ 号池单调。
    带上 `deleted = 0` ⇒ 删一个窗再加一个**会复用已删号** ⇒ 红。
    """
    high = _cte_body(sql, "v92_high")
    assert re.search(r"MAX\(\s*s\.set_index\s*\)", high, re.I), "号池上界 CTE 里没有 `MAX(set_index)`"
    assert not re.search(r"deleted\s*=\s*0", high, re.I), (
        "🔴 号池上界的 `MAX(set_index)` 查询**带了 `deleted = 0`** ⇒ 软删行不再占号 ⇒ "
        "「删一个窗再加一个」会**复用已删号**，违反用户裁定「已删的号不回收」（设计 §2.4 规则 1）"
    )
    live = _cte_body(sql, "v92_live")
    assert re.search(r"deleted\s*=\s*0", live, re.I), (
        "「认领已有套行」的 CTE 必须只看 **live** 行（否则软删行会被当成已分配 ⇒ 该窗反而没有 live 套行）"
    )
    numbered = _cte_body(sql, "v92_numbered")
    assert re.search(r"COALESCE\(\s*h\.max_index\s*,\s*0\s*\)\s*\+\s*ROW_NUMBER\(\)", numbered, re.I), (
        "新窗的序号必须是 `MAX(set_index) + ROW_NUMBER()`（**只增**）；按快照位置 `ROW_NUMBER()` 直接当序号"
        "会在「软删过 + 中间插窗」时复用已删号"
    )


def _check_backfill_reads_only_snapshot(sql: str) -> None:
    """判据 4：回填**只读 `items_snapshot`**（固化真相），不读 `order_items` 现值（设计 §2.5）。"""
    assert re.search(r"jsonb_array_elements\(\s*po\.items_snapshot\s*\)", sql, re.I), (
        "回填没有从 `processing_orders.items_snapshot` 展开（它是回填的**唯一输入**）"
    )
    assert not re.search(r"\b(FROM|JOIN)\s+order_items\b", sql, re.I), (
        "🔴 回填读了 `order_items` **现值** —— 它会被改名 / 改行序影响 ⇒ 回填结果**不可复现**"
        "（设计 §2.5：必须只读 `items_snapshot`）"
    )
    # 分组口径与 ProcessingOrderService.craftGroupKey 同口径
    assert re.search(r"btrim\(\s*\w*\.?value\s*->>\s*'craftLineId'\s*\)", sql, re.I), "分组键没有取 craftLineId"
    assert re.search(r"btrim\(\s*\w*\.?value\s*->>\s*'itemId'\s*\)", sql, re.I), "分组键没有回落 itemId"
    assert re.search(r"'ord:'\s*\|\|", sql), "分组键没有「两者皆缺 ⇒ 各自成组」的兜底（会静默并组）"
    assert re.search(r"'componentRole'\s*,\s*''\s*\)\s*=\s*'配布边'", sql), (
        "没有排除被吸收的**配布边行**（`componentRole='配布边'`）⇒ 一扇窗被算成两扇（与实例化循环不同口径）"
    )


def _check_idempotent(sql: str) -> None:
    """判据 5：幂等形态齐备（`MigrationRunner` 硬要求所有迁移可重复执行）。"""
    assert len(re.findall(r"CREATE TABLE IF NOT EXISTS", sql, re.I)) == 2, "两张新表都要 `IF NOT EXISTS`"
    assert len(re.findall(r"CREATE UNIQUE INDEX IF NOT EXISTS", sql, re.I)) == 4, "四个唯一索引都要 `IF NOT EXISTS`"
    assert len(re.findall(r"ADD COLUMN IF NOT EXISTS", sql, re.I)) == 6, "六列都要 `ADD COLUMN IF NOT EXISTS`"
    assert re.search(r"CREATE INDEX IF NOT EXISTS\s+idx_position_operations_status_done", sql, re.I), \
        "卡点索引缺 `IF NOT EXISTS`（或索引名与设计 §11.2 ⑥ 不符）"
    assert re.search(r"ON CONFLICT\s*\(\s*tenant_id\s*,\s*processing_order_id\s*,\s*set_index\s*\)"
                     r"\s*WHERE\s+deleted\s*=\s*0\s+DO NOTHING", sql, re.I), (
        "回填 INSERT 缺 `ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING`"
        "（并发 / 重复执行的幂等靠它，设计 §2.4 规则 3）"
    )
    assert re.search(r"o\.set_id\s+IS\s+DISTINCT\s+FROM\s+s\.id", sql, re.I), (
        "回填 UPDATE 缺 `o.set_id IS DISTINCT FROM s.id` 守卫 ⇒ 第二次执行不是 0 行（幂等形态缺失）"
    )


def _check_tenant_scoped(sql: str) -> None:
    """判据 6：两条回填 DML **都**按租户限定（`JOIN tenants … deleted = 0`）。"""
    body = _strip_comments(sql)
    joins = re.findall(r"JOIN\s+tenants\s+t\s+ON\s+t\.id\s*=\s*([a-z_.]+)\s+AND\s+t\.deleted\s*=\s*0", body, re.I)
    targets = {j.lower().split(".")[0] for j in joins}
    assert "po" in targets, "套行回填没有按租户限定（缺 `JOIN tenants t ON t.id = po.tenant_id AND t.deleted = 0`）"
    assert "s" in targets, "实例行回填没有按租户限定（缺 `JOIN tenants t ON t.id = s.tenant_id AND t.deleted = 0`）"


def _check_instance_backfill_touches_only_new_columns(sql: str) -> None:
    """判据 7（**红线**）：实例行回填的 `SET` 子句**只允许 `set_id` / `set_no`**。

    多写任何一列（尤其 `updated_at` / `status` / `done_qty` / `unit_price` / `factor`）⇒ 改历史值 ⇒ 红。
    """
    updates = [(t, cols) for t, cols in _update_set_columns(_strip_comments(sql)) if t == INSTANCE_TABLE]
    assert updates, f"迁移里没有针对 `{INSTANCE_TABLE}` 的 `UPDATE … SET`（实例行回填缺失）"
    for _, cols in updates:
        assert sorted(cols) == ["set_id", "set_no"], (
            f"🔴 实例行回填的 `SET` 子句是 {cols} —— 只允许 `['set_id', 'set_no']`。"
            f"写别的列 = 改**历史值**（红线：`processing_position_operations` 既有列一字不动；"
            f"`updated_at` 会被污染、`status`/`done_qty` 会造假进度）"
        )


def _check_red_line_tables_untouched(sql: str) -> None:
    """判据 8（**红线**）：报工快照表与 `qr_token` 零写入；`processing_orders` 只读。"""
    body = _strip_literals(_strip_comments(sql))
    for table in RED_LINE_TABLES:
        for verb in ("INSERT INTO", "UPDATE", "DELETE FROM", "ALTER TABLE"):
            assert not re.search(verb + r"\s+" + table + r"\b", body, re.I), (
                f"🔴 迁移**写**了红线表 `{table}`（{verb}）—— 报工明细与计件金额的历史值一字不动"
            )
    assert not re.search(r"qr_token", body, re.I), (
        "🔴 迁移碰了 `processing_orders.qr_token`（设计 §2.6 明令：不碰、不设强制失效日 —— "
        "已有打印件不作废）"
    )
    assert not re.search(r"(INSERT INTO|UPDATE|DELETE FROM|ALTER TABLE)\s+processing_orders\b", body, re.I), (
        "🔴 迁移**写**了 `processing_orders`（`items_snapshot` 是回填的只读输入，固化真相不得改）"
    )


def _check_stop_conditions(sql: str) -> None:
    """判据 9：五条**硬停**是可执行断言（`RAISE EXCEPTION`），且**逐条不空转**。"""
    body = _strip_comments(sql)
    assert len(re.findall(r"RAISE EXCEPTION", body)) >= 5, (
        "硬停断言不足 5 条 —— S1 套号重复 / S2 序号跳号 / S3 套数≠窗数 / S4 套号格式 / S5 套归属对不上"
        "（issue #4698 要求「停止条件落成可执行断言」）"
    )
    assert len(re.findall(r"RAISE WARNING", body)) >= 4, (
        "软停读数不足 4 条（设计 §11.3 条件 1/2/4/5：脏数据跳过但**必须可见**，不静默）"
    )
    # S1 套号重复：按 (tenant_id, set_no) 分组 + HAVING COUNT(*) > 1
    s1 = re.search(r"GROUP BY\s+s\.tenant_id\s*,\s*s\.set_no\s*HAVING\s+COUNT\(\*\)\s*>\s*1", body, re.I)
    assert s1, "S1 不空转判据缺失：必须 `GROUP BY s.tenant_id, s.set_no HAVING COUNT(*) > 1`（同租户套号重复）"
    # S2 序号跳号：MIN <> 1 OR MAX <> COUNT(*)
    assert re.search(r"HAVING\s+MIN\(s\.set_index\)\s*<>\s*1\s+OR\s+MAX\(s\.set_index\)\s*<>\s*COUNT\(\*\)", body, re.I), (
        "S2 不空转判据缺失：必须 `HAVING MIN(set_index) <> 1 OR MAX(set_index) <> COUNT(*)`"
        "（软删行仍占号 ⇒ 序号必须连续；跳号 = 号池被复用/丢失）"
    )
    # S3 套数 ≠ 窗数：live 套数 vs 快照窗数，且排除 >999 跳过的单
    assert re.search(r"COUNT\(\*\)\s*<>\s*COALESCE\(\s*l\.live_sets\s*,\s*0\s*\)", body, re.I), (
        "S3 不空转判据缺失：必须把 live 套行数与快照窗数**逐单比对**（`COUNT(*) <> COALESCE(l.live_sets, 0)`）"
    )
    assert re.search(r"HAVING\s+COUNT\(\*\)\s*<=\s*999", body, re.I), (
        "S3 必须排除「分组数 > 999 被软停②跳过」的单（它们的套行本就不该存在）"
    )
    # S4 套号格式：与 {单号}-{pad3} 逐行比对
    assert re.search(r"s\.set_no\s*<>\s*po\.processing_order_no\s*\|\|\s*'-'\s*\|\|\s*lpad\(\s*s\.set_index::text", body, re.I), (
        "S4 不空转判据缺失：必须逐行比对 `set_no <> 单号-'-'-lpad(set_index,3,'0')`（>999 的**显式拒绝**）"
    )
    # S5 套归属：跨单 / 不在部位清单里
    assert re.search(r"s\.processing_order_id\s*<>\s*o\.processing_order_id", body, re.I), \
        "S5 不空转判据缺失：必须检出 `set_id` **跨单**"
    assert re.search(r"NOT\s*\(\s*s\.position_item_ids\s*@>\s*to_jsonb\(\s*o\.order_item_id\s*\)\s*\)", body, re.I), \
        "S5 不空转判据缺失：必须检出「该行 order_item_id 不在所属套的部位清单里」"
    # 软停② 与 ⑤ 的判据也在（分组数 >999 / order_item_id 非空但未回填）
    assert re.search(r"HAVING\s+COUNT\(\*\)\s*>\s*999", body, re.I), "软停②（分组数 > 999）的判据缺失"
    assert re.search(r"COUNT\(\*\)\s+FILTER\s*\(\s*WHERE\s+o\.set_id\s+IS\s+NOT\s+NULL\s*\)\s*<>\s*COUNT\(\*\)", body, re.I), (
        "软停⑤（对账读数：order_item_id 非空但未回填 set_id）的判据缺失"
    )


def _check_group_skip_predicate_is_shared(sql: str) -> None:
    """判据 10：回填的跳过判据（`分组数 <= 999`）与 S3 的排除判据**同口径**（设计 §11.3 条件 2）。"""
    body = _strip_comments(sql)
    assert re.search(r"WHERE\s+\w*\.?group_count\s*<=\s*999", body, re.I), (
        "回填缺「分组数 > 999 ⇒ 跳过该单」的判据（设计 §11.3 条件 2：**不静默截断**）"
    )


def _check_rollback_is_registered(sql: str) -> None:
    """判据 11：回滚 = **新迁移**（设计 §11.4），且**只登记不落码**。"""
    assert ROLLBACK_NAME in sql, (
        f"迁移头注没有登记回滚迁移 `{ROLLBACK_NAME}`（设计 §11.4：回滚 = 新迁移，**不删本迁移**）"
    )
    assert not (MIGRATION_DIR / ROLLBACK_NAME).exists(), (
        f"🔴 `{ROLLBACK_NAME}` **落码了** —— 它会被 `MigrationRunner` 当场执行（按文件名顺序跑全部未记账迁移）"
        f"⇒ 本迁移刚建的载体被立刻 DROP。回滚脚本只登记在头注释里（与 V88 / V89 同款处置）"
    )
    for action in ("DROP TABLE IF EXISTS processing_set_part_tokens",
                   "DROP TABLE IF EXISTS processing_order_sets",
                   "DROP INDEX IF EXISTS idx_position_operations_status_done"):
        assert action in sql, f"回滚登记缺动作：`{action}`"
    for col in INSTANCE_NEW_COLUMNS:
        assert f"DROP COLUMN IF EXISTS {col}" in sql, f"回滚登记缺 `DROP COLUMN IF EXISTS {col}`"


# ── 判据入口（真值 = 磁盘上的迁移）────────────────────────────────────────────

def test_migration_exists_and_registered_in_the_ledger():
    """自证：迁移存在（**红证①**：删掉它 ⇒ 本文件全红）且已登记指纹账本（迁移不可变护栏）。"""
    sql = _sql()
    assert len(sql) > 1000, "迁移文件疑似被截断（只有注释没有语句 —— 见 #4543 的实证形态）"
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))["migrations"]
    assert MIGRATION.name in ledger, (
        f"`{MIGRATION.name}` 未登记进 `migration_fingerprints.json` ⇒ "
        f"`test_migration_immutability` 会判红（重生成：python3 tests/unit_ci_workflows/"
        f"test_migration_immutability.py --write-ledger）"
    )
    # ⚠️ 此处原有 `assert len(ledger) == 89`（「本单只应**新增** 1 条」）—— 它是**全局计数**，
    # 任何**别的**包新增迁移都会把它判红（issue #4709 的 V94 实测：`90 ≠ 89` ⇒ 与本包无关的 PR 红，
    # 且 #4714 的 V93 会再撞一次）。判据本意 = 「本单的迁移在不在账本里 + **已发布迁移有没有被动**」：
    #   · 前者 = 上面的在场断言；
    #   · 后者 = **逐字节指纹**（`test_migration_immutability.py::test_registered_migrations_are_byte_identical`
    #     + `test_ledger_covers_every_migration_on_disk`），本文件**不复制**那份规则。
    # ⇒ 换成**不写死数字**的等价判据：账本登记值必须等于本文件**当前内容**的 sha256
    #   （比"在场"更强：既证登记了、也证登记的是**这一份**内容；同 #4696 对
    #    `test_public_ops_v88_migration.py` 的 `max(versions) == 88` 的处置）。
    assert ledger[MIGRATION.name] == "sha256:" + hashlib.sha256(MIGRATION.read_bytes()).hexdigest(), (
        f"`{MIGRATION.name}` 的账本指纹与文件**当前内容**不符 ⇒ 已发布迁移被改过"
        f"（改已发布迁移 = `MigrationRunner` 按文件名整份跳过 ⇒ 存量环境永远拿不到）"
    )


def test_carriers_and_unique_keys_match_the_design():
    _check_carriers_and_unique_keys(_strip_comments(_sql()))


def test_set_no_format_is_order_no_plus_pad3():
    _check_set_no_format(_strip_comments(_sql()))


def test_index_allocation_is_monotonic_and_never_reuses_deleted_numbers():
    """🔴 反向护栏：**只增不复用**（删一个窗再加一个 ⇒ 不得复用已删号）。"""
    _check_monotonic_never_reuses_deleted(_strip_comments(_sql()))


def test_backfill_reads_only_the_snapshot():
    _check_backfill_reads_only_snapshot(_strip_comments(_sql()))


def test_backfill_is_idempotent():
    _check_idempotent(_strip_comments(_sql()))


def test_backfill_is_tenant_scoped():
    _check_tenant_scoped(_sql())


def test_instance_backfill_touches_only_the_two_new_columns():
    """🔴 红线：既有列零赋值（历史值一字不动，可机械核验）。"""
    _check_instance_backfill_touches_only_new_columns(_sql())


def test_red_line_tables_and_qr_token_are_untouched():
    """🔴 红线：`production_work_logs` / `qr_token` / `items_snapshot` 零写入。"""
    _check_red_line_tables_untouched(_sql())


def test_stop_conditions_are_executable_and_not_vacuous():
    _check_stop_conditions(_sql())


def test_group_skip_predicate_is_shared_with_the_assertion_block():
    _check_group_skip_predicate_is_shared(_sql())


def test_rollback_is_a_new_migration_registered_but_not_shipped():
    _check_rollback_is_registered(_sql())


def test_six_instance_columns_are_added_nullable():
    """设计 §11.2 ④：六列**全部可空**（存量行留空 = 明确语义，不猜）+ 每列有列注释。"""
    sql = _strip_comments(_sql())
    for col in INSTANCE_NEW_COLUMNS:
        m = re.search(r"ALTER TABLE\s+" + INSTANCE_TABLE + r"\s+ADD COLUMN IF NOT EXISTS\s+" + col + r"\s+([A-Z()0-9 ]+)",
                      sql, re.I)
        assert m, f"缺 `ALTER TABLE {INSTANCE_TABLE} ADD COLUMN IF NOT EXISTS {col} …`"
        assert "NOT NULL" not in m.group(1).upper(), (
            f"`{col}` 是 NOT NULL —— 存量行没有该值（无法可靠回填）⇒ 加 NOT NULL 会让迁移在存量库上失败"
        )
    for col in INSTANCE_NEW_COLUMNS:
        assert f"COMMENT ON COLUMN {INSTANCE_TABLE}.{col} IS" in sql, f"`{col}` 缺列注释（口径必须写在库里）"


def test_status_domain_is_extended_without_touching_the_column_definition():
    """设计 §11.2 ⑤：`status` 只**扩取值域**（列注释），**不改列定义**（`VARCHAR(16)` 装得下）。"""
    sql = _strip_comments(_sql())
    assert re.search(r"COMMENT ON COLUMN\s+" + INSTANCE_TABLE + r"\.status\s+IS\s+'[^']*in_progress", sql, re.I), (
        "缺 `status` 的列注释扩展（`pending` / `in_progress`（C 模式预留）/ `done`）"
    )
    assert not re.search(r"ALTER TABLE\s+" + INSTANCE_TABLE + r"[\s\S]{0,80}status", sql, re.I), (
        "`status` 被改了列定义 —— 设计 §11.2 ⑤ 要求**只改注释**（改列定义 = 存量库上的无谓风险）"
    )


def test_token_carrier_ships_no_rows():
    """本片只落载体：码在**打印**那一刻生成 ⇒ 迁移里**不得**给 `processing_set_part_tokens` 种行。"""
    sql = _strip_comments(_sql())
    assert not re.search(r"INSERT INTO\s+" + TOKENS_TABLE, sql, re.I), (
        f"迁移给 `{TOKENS_TABLE}` 种了行 —— 码必须由打印入口生成（一部位一码 + 复用同一 token），"
        f"回填阶段**不知道**要打印什么"
    )


def test_bootstrap_schema_carries_the_terminal_state():
    """设计 §11.2 ⑩：`backend/admin-api/src/main/resources/db/init/schema.sql` 必须同步终态（新建库路径**不跑迁移链**）。

    不同步 ⇒ bootstrap 库没有这两张表 / 六列，而存量库有 ⇒ 两条路径分叉（#3270 同族）。
    """
    schema = SCHEMA.read_text(encoding="utf-8")
    for table in (SETS_TABLE, TOKENS_TABLE):
        assert re.search(r"CREATE TABLE IF NOT EXISTS\s+" + table, schema, re.I), f"schema.sql 缺表 `{table}`"
    for col in INSTANCE_NEW_COLUMNS:
        assert re.search(r"\b" + col + r"\s+(VARCHAR\(64\)|TIMESTAMP WITH TIME ZONE)", schema, re.I), (
            f"schema.sql 的 `{INSTANCE_TABLE}` 缺列 `{col}`"
        )
    for idx in ("uk_processing_order_sets_index", "uk_processing_order_sets_no",
                "uk_set_part_tokens_token", "uk_set_part_tokens_part",
                "idx_position_operations_status_done"):
        assert re.search(r"CREATE (UNIQUE )?INDEX IF NOT EXISTS\s+" + idx, schema, re.I), (
            f"schema.sql 缺索引 `{idx}`"
        )


def test_bootstrap_and_migration_agree_on_the_new_objects():
    """两路径终态逐项一致：迁移建的表/列/索引名，schema.sql 里**一个不少**。"""
    mig = _strip_comments(_sql())
    schema = SCHEMA.read_text(encoding="utf-8")
    created_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+([a-z_][a-z0-9_]*)", mig, re.I))
    assert created_tables == {SETS_TABLE, TOKENS_TABLE}, f"迁移建的表集合变了：{sorted(created_tables)}"
    created_indexes = set(re.findall(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS\s+([a-z_][a-z0-9_]*)", mig, re.I))
    missing = {i for i in created_indexes if not re.search(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS\s+" + i, schema, re.I)}
    assert not missing, f"迁移建了但 schema.sql 没有的索引：{sorted(missing)}"


# ── 注入式红证（**改坏即红**）────────────────────────────────────────────────

class TestInjectedDrift:
    """每条判据注入一个**真实缺陷形态** ⇒ 必须判红（防「守卫被写弱成永远绿」）。"""

    def _mutated(self, old: str, new: str) -> str:
        """在**剥掉注释后**的 SQL 上注入漂移。

        ⚠️ 为什么不在原文上替换：头注释里**逐条复述**了真实 SQL 的形态（`ON CONFLICT …`、
        `MAX(set_index)` …）⇒ 在原文上 `replace(…, 1)` 会改到**注释里那一处**、真语句原封不动
        ⇒ 判据照旧通过 = **假绿**（本文件首版实测踩到，靠「DID NOT RAISE」暴露）。
        """
        if not MIGRATION.is_file():
            raise LookupError(f"被测迁移不存在（{MIGRATION.name}）—— 注入式红证无从谈起")
        body = _strip_comments(_sql())
        if old not in body:
            # ⚠️ 抛 **LookupError** 而不是 AssertionError：`pytest.raises(AssertionError)` 会把它
            # 一起吞掉 ⇒ 锚点漂移时这些用例会**假绿**（实测：删掉被测迁移时 5 条仍「通过」）。
            raise LookupError(f"注入锚点漂移了（剥注释后找不到 {old!r}）—— 请同步本测试")
        return body.replace(old, new, 1)

    def test_red_when_set_carrier_is_absent(self):
        """**红证①**：载体不存在 ⇒ 红（删掉整张表）。"""
        import pytest
        with pytest.raises(AssertionError):
            _check_carriers_and_unique_keys(
                _strip_comments(self._mutated("CREATE TABLE IF NOT EXISTS processing_order_sets", "-- 删掉了")))

    def test_red_when_the_readable_no_unique_key_is_dropped(self):
        """缺 `uk_processing_order_sets_no` ⇒ 红（码里印的是它，重复 ⇒ 扫码解析到两套）。"""
        import pytest
        with pytest.raises(AssertionError):
            _check_carriers_and_unique_keys(_strip_comments(
                self._mutated("CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_order_sets_no",
                              "CREATE INDEX IF NOT EXISTS uk_processing_order_sets_no")))

    def test_red_when_unique_index_loses_the_partial_predicate(self):
        """唯一键丢掉 `WHERE deleted = 0` ⇒ 红（与设计 §2.2 逐字不符）。"""
        import pytest
        sql = self._mutated(
            "    ON processing_order_sets (tenant_id, processing_order_id, set_index)\n    WHERE deleted = 0;",
            "    ON processing_order_sets (tenant_id, processing_order_id, set_index);")
        with pytest.raises(AssertionError):
            _check_carriers_and_unique_keys(_strip_comments(sql))

    def test_red_when_max_query_filters_out_soft_deleted_rows(self):
        """🔴 反向护栏的红证：`MAX` 带上 `deleted = 0` ⇒ **已删号会被复用** ⇒ 红。"""
        import pytest
        sql = self._mutated(
            'SELECT s.tenant_id, s.processing_order_id, MAX(s.set_index) AS max_index\n'
            '      FROM processing_order_sets s\n     GROUP BY',
            'SELECT s.tenant_id, s.processing_order_id, MAX(s.set_index) AS max_index\n'
            '      FROM processing_order_sets s\n     WHERE s.deleted = 0\n     GROUP BY')
        with pytest.raises(AssertionError):
            _check_monotonic_never_reuses_deleted(_strip_comments(sql))

    def test_red_when_index_is_positional_instead_of_monotonic(self):
        """把「MAX+ROW_NUMBER」退回「按快照位置编号」⇒ 红（那正是复用已删号的形态）。"""
        import pytest
        sql = self._mutated(
            "COALESCE(l.set_index,\n                    (COALESCE(h.max_index, 0) + ROW_NUMBER() OVER (",
            "COALESCE(l.set_index,\n                    (0 + ROW_NUMBER() OVER (")
        with pytest.raises(AssertionError):
            _check_monotonic_never_reuses_deleted(_strip_comments(sql))

    def test_red_when_backfill_reads_order_items_current_values(self):
        """回填改读 `order_items` 现值 ⇒ 红（回填结果不可复现，设计 §2.5）。"""
        import pytest
        sql = self._mutated("FROM processing_orders po", "FROM processing_orders po JOIN order_items oi ON TRUE")
        with pytest.raises(AssertionError):
            _check_backfill_reads_only_snapshot(_strip_comments(sql))

    def test_red_when_backfill_update_also_writes_updated_at(self):
        """🔴 红线红证：回填多写一列（`updated_at`）⇒ 改历史值 ⇒ 红。"""
        import pytest
        sql = self._mutated("   SET set_id = s.id,\n       set_no = s.set_no",
                            "   SET set_id = s.id,\n       set_no = s.set_no,\n       updated_at = NOW()")
        with pytest.raises(AssertionError):
            _check_instance_backfill_touches_only_new_columns(sql)

    def test_red_when_a_red_line_table_is_written(self):
        """🔴 红线红证：写 `production_work_logs` ⇒ 红。"""
        import pytest
        sql = self._mutated("DO $$", "UPDATE production_work_logs SET factor = 1;\nDO $$")
        with pytest.raises(AssertionError):
            _check_red_line_tables_untouched(sql)

    def test_red_when_qr_token_is_touched(self):
        """🔴 红线红证：碰 `qr_token` ⇒ 红（设计 §2.6：不碰、不设强制失效日）。"""
        import pytest
        sql = self._mutated("DO $$", "UPDATE processing_orders SET qr_token = NULL;\nDO $$")
        with pytest.raises(AssertionError):
            _check_red_line_tables_untouched(sql)

    def test_red_when_idempotency_guards_are_dropped(self):
        """去掉 `ON CONFLICT … DO NOTHING` / `IS DISTINCT FROM` ⇒ 红（幂等形态缺失）。"""
        import pytest
        for old, new in (
            ("ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING", ";"),
            ("AND o.set_id IS DISTINCT FROM s.id", ""),
        ):
            with pytest.raises(AssertionError):
                _check_idempotent(_strip_comments(self._mutated(old, new)))

    def test_red_when_tenant_scope_is_dropped(self):
        """去掉按租户限定 ⇒ 红（`issue #4676 ⑥` 同款口径：软删租户一条都不写）。"""
        import pytest
        sql = self._mutated("JOIN tenants t ON t.id = s.tenant_id AND t.deleted = 0", "")
        with pytest.raises(AssertionError):
            _check_tenant_scoped(sql)

    def test_red_when_a_stop_condition_becomes_vacuous(self):
        """把 S2 的判据改成恒假（`MIN(set_index) <> 1` 删掉）⇒ 红（空断言 = 没断言）。"""
        import pytest
        sql = self._mutated("HAVING MIN(s.set_index) <> 1 OR MAX(s.set_index) <> COUNT(*)",
                            "HAVING FALSE")
        with pytest.raises(AssertionError):
            _check_stop_conditions(_strip_comments(sql))

    def test_red_when_hard_stop_becomes_a_warning(self):
        """把硬停降级成 WARNING（不再「立即停」）⇒ 红。"""
        import pytest
        sql = self._mutated("V92 停止条件 S3（存量单套数 ≠ 窗数）", "V92 软停③（存量单套数 ≠ 窗数）")
        sql = sql.replace("RAISE EXCEPTION 'V92 软停③", "RAISE WARNING 'V92 软停③")
        with pytest.raises(AssertionError):
            _check_stop_conditions(_strip_comments(sql))

    def test_red_when_set_no_format_loses_zero_padding(self):
        """套号去掉 3 位零填充 ⇒ 红（设计 §2.1：`014` 与 `14` 排序对齐不稳）。"""
        import pytest
        sql = self._mutated("lpad(n.new_index::text, 3, '0')", "n.new_index::text")
        with pytest.raises(AssertionError):
            _check_set_no_format(_strip_comments(sql))

    def test_red_when_rollback_migration_is_shipped(self):
        """回滚脚本被**落码**成真迁移 ⇒ 红（会被 `MigrationRunner` 当场执行）。"""
        import pytest
        target = MIGRATION_DIR / ROLLBACK_NAME
        sql = _sql()          # ⚠️ 在 `with` **之外**取（文件不存在时不许被 pytest.raises 吞掉）
        target.write_text("-- 注入式红证夹具（会被本测试删除）\nDROP TABLE IF EXISTS processing_order_sets;\n",
                          encoding="utf-8")
        try:
            with pytest.raises(AssertionError):
                _check_rollback_is_registered(sql)
        finally:
            target.unlink()
