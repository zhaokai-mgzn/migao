#!/usr/bin/env python3
"""按订单号精确删除测试/验收订单及其明细、物流、加工单、工序实例、报工、售后工单、发货单、收款流水
（默认 dry-run，需 --apply 才执行）。

用途：清理验收/冒烟过程在 dev 库创建的测试数据 —— 一张订单**挂在它下面的一切**：
订单 + 明细 + 物流 + 加工单 + 工序实例 + 报工 + 售后工单（含时间线/备注/返工单）
+ 发货单（含发货明细）+ 收款流水（含核销明细）。

用法：
    python3 scripts/delete_orders.py --order-nos 20260912392560001,20260912395290001
    python3 scripts/delete_orders.py --order-nos 2026... --apply
    # 已被软删（deleted≠0）的「墓碑单」也一起清：
    python3 scripts/delete_orders.py --order-nos 2026... --include-soft-deleted --apply

安全设计：
    - **仅按显式 order_no 精确匹配**（orders.order_no UNIQUE），不支持通配/批量条件；
    - 默认 dry-run，逐级打印将删除的行数；必须显式 --apply 才真正删除；
    - 事务内按 `DELETE_PLAN` 的依赖拓扑删除（被引用表先于引用表）；
    - **默认只匹配未软删的订单**（`deleted = 0`）。`--include-soft-deleted` 把 `deleted <> 0` 的
      「墓碑单」也纳入匹配，语义 = 「连同墓碑一起清」—— issue #7633 的现场：一张裸 SQL 把 55 张冒烟
      订单批量软删而子行没级联，而本脚本当时只认 `deleted = 0` ⇒ 对**最该清理的那批数据**一条也
      清不掉，最后只能手写 SQL。
      ⚠️ 风险：`order_no` 在库里唯一 ⇒ 开了开关就是「命中谁删谁」，**行级不可逆**；它还会连带删掉
      该订单的**收款流水与核销明细（涉钱行）**。只在你确认「这批单就是冒烟/验收残留、业务面已不再
      引用」后使用，且**先看 dry-run 汇总**。
      另外：**一笔收款冲多张单**时，删其中一张会连带删掉该收款的**全部**核销明细（收款行本身也删）——
      dry-run 的「收款核销明细」行数就是这个口径的读数。
    - **依赖拓扑必须与真库外键一致**：`DELETE_PLAN`（依赖拓扑）· `locators()`（键空间）
      · `TABLE_LABELS`（汇总）三者同源。判据 = `tests/unit_ci_workflows/test_delete_orders_fk_order.py`
      —— 它从建库脚本 + 迁移链**现场抽**外键边，并按「凡带 `order_id` 列的表都算这张订单的」取闭包：
      schema / 迁移加了一层依赖而本脚本没跟上 ⇒ 那条判据**先变红**（不会等到线上删不掉）。
    - **它只清「这张订单及其子行」**：不删订单以外的东西、**不做定时清理**（铁律 10：无人值守的删除 /
      破坏性动作不安全）、不按条件批量删、不动其它订单或租户的数据；日志/审计类表（`audit_logs` 等）
      按租户与操作留痕，不随订单消失。
    - 连接参数取自 backend/admin-api/.env 的 RDS_* 变量（可用 --env-file 覆盖），
      不硬编码任何凭据、不读 .env 以外的配置。
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 删除顺序 = 依赖拓扑（被引用表先于引用表）。每级 = (表, ((定位列, 键空间), ...))：
#   · 键空间 = 该列要比对的**父 id 列表**（order = 订单 id / po = 加工单 id / ticket = 售后工单 id
#     / shipment = 发货单 id / transaction = 收款流水 id）；父 id 由 run() 先查好再传进 locators()；
#   · 一张表可能有**两侧**定位（返工单 = 工单侧 + 订单侧、发货明细 = 发货单侧 + 订单侧、
#     收款核销明细 = 交易侧 + 订单侧）⇒ 合成**同一条** DELETE（`OR` 连接各侧精确主键等值），
#     这样一张表只删一次、dry-run 汇总也只报一次。
# 真值源：backend/admin-api/src/main/resources/db/init/schema.sql + 迁移链的外键链 ——
#   orders ← order_items / order_logistics / processing_orders / receipt_allocations
#          / （无外键的语义引用）after_sales_tickets / order_shipments / order_shipment_items
#          / finance_transactions / rework_orders
#   processing_orders ← processing_position_operations / production_work_logs
#                      / processing_order_sets / processing_set_part_tokens
#                      / production_instance_repricing_logs（V94，issue #4709）
#                      / worker_report_audits（V98，issue #4733：报工身份旁路账）
#                      / quality_inspections（V157，issue #5652：质检记录，成品帘级 —— 同时引用
#                        processing_orders 与 order_items 两张父表）
#   processing_order_sets ← processing_set_part_tokens（码行指向套行）
#   processing_position_operations ← production_instance_repricing_logs
#   after_sales_tickets ← ticket_timeline / ticket_notes / rework_orders（V185，真外键）
#   order_shipments ← order_shipment_items（V133，真外键）
#   finance_transactions ← receipt_allocations（V176，真外键 —— 删收款流水的前置）
# ⚠️ 新增指向 orders / order_items / processing_orders / after_sales_tickets / order_shipments
#    / finance_transactions 的外键（或新增带 order_id 列的表）时必须同步本表，
#    否则 DELETE 父表时会被外键拦下、或留下一辈子指不到父行的孤儿：
#    issue #4242：V49 加了两层，脚本没跟上 ⇒ 带加工单的订单删不掉；
#    issue #4698 切片 ⓪ 的 V92 又加了两层 = 套号载体 + 部位码载体，同款；
#    issue #4709 的 V94 再补一层 = 未定价实例补价动作账，同款；
#    issue #4733 的 V98 再补一层 = 报工身份旁路账（工人登录态落地后每笔报工 1:1 一行），同款；
#    issue #7370 段 3 的 V176 又补一层 = 收款核销明细（一笔收款冲多张单，每行引用一张订单），同款；
#    issue #7633（2026-10-24）实测：售后 / 发货 / 收款三族 + 核销明细的交易侧统统没跟上 ⇒
#      带收款/售后/发货的订单删不掉，最后只能手写 SQL（finance_transactions 55 行等）。
#    护栏（**不写死表名**，schema 加一层就自动要求跟上）：tests/unit_ci_workflows/test_delete_orders_fk_order.py
DELETE_PLAN = (
    # 质检记录（V157，issue #5652）同时引用**加工单**与**成品帘**两张父表（processing_order_id /
    # order_item_id 都是真外键）⇒ 必须最先删（两张父表都在它后面）
    ("quality_inspections", (("processing_order_id", "po"),)),
    # 报工身份旁路账（V98，issue #4733）引用**加工单**（work_log_id 是**语义**父行、无外键）
    # ⇒ 与 production_work_logs 同层最先删
    ("worker_report_audits", (("processing_order_id", "po"),)),
    # 补价动作账（V94）引用**加工单**与**工序实例**两张父表 ⇒ 必须最先删
    ("production_instance_repricing_logs", (("processing_order_id", "po"),)),
    # 售后族（issue #7633）：时间线 / 备注 / 返工单都引用 after_sales_tickets(id)（真外键）
    # ⇒ 必须早于售后工单；返工单还带 order_id（语义引用）与 processing_order_id ⇒ 排在加工单之前
    ("ticket_timeline", (("ticket_id", "ticket"),)),
    ("ticket_notes", (("ticket_id", "ticket"),)),
    ("rework_orders", (("after_sales_ticket_id", "ticket"), ("order_id", "order"))),
    ("production_work_logs", (("processing_order_id", "po"),)),
    ("processing_position_operations", (("processing_order_id", "po"),)),
    # ⚠️ 码行在套行**之前**（它引用 processing_order_sets.id）—— 顺序反了会被外键拦下
    ("processing_set_part_tokens", (("processing_order_id", "po"),)),
    ("processing_order_sets", (("processing_order_id", "po"),)),
    ("processing_orders", (("order_id", "order"),)),
    # 发货族（issue #7633）：明细的 shipment_id 是真外键 ⇒ 早于发货单；
    # 明细也带 order_id / order_item_id（语义引用）⇒ 早于订单明细
    ("order_shipment_items", (("shipment_id", "shipment"), ("order_id", "order"))),
    ("order_shipments", (("order_id", "order"),)),
    ("order_items", (("order_id", "order"),)),
    ("order_logistics", (("order_id", "order"),)),
    # 打印流水（V201，issue #7902）：print_logs.order_id 是**语义**引用（无外键，但属该订单的
    # 审计行）⇒ 早于 orders 删；append-only 事实表，删单时一并清掉（否则留下孤儿「已打印」读数）
    ("print_logs", (("order_id", "order"),)),
    # 售后工单本体（issue #7633）：after_sales_tickets.order_id 无外键但语义属该订单 ⇒ 早于 orders
    ("after_sales_tickets", (("order_id", "order"),)),
    # 收款核销明细（V176，issue #7370 段 3）引用**订单**（order_id 是真外键）⇒ 必须早于 orders 删；
    # issue #7633 补上它的 **transaction_id 一侧**（引用 finance_transactions 的真外键）⇒ 早于收款流水
    ("receipt_allocations", (("transaction_id", "transaction"), ("order_id", "order"))),
    # 收款流水（issue #7633）：finance_transactions.order_id 无外键但语义属该订单 ⇒ 早于 orders
    ("finance_transactions", (("order_id", "order"),)),
    # 成品在库 / 出库单（V196，issue #7750）：order_id 是真外键 ⇒ 必须早于 orders；
    # 出库明细先于出库单（outbound_order_id 是真外键）；入库明细同列引用 order_id。
    ("outbound_order_items", (("order_id", "order"),)),
    ("outbound_orders", (("order_id", "order"),)),
    ("inbound_order_items", (("order_id", "order"),)),
    ("finished_goods_stock", (("order_id", "order"),)),
    ("orders", (("id", "order"),)),
)
TABLE_LABELS = {
    "quality_inspections": "质检记录",
    "worker_report_audits": "报工身份旁路账",
    "production_instance_repricing_logs": "补价动作账",
    "ticket_timeline": "工单时间线",
    "ticket_notes": "工单备注",
    "rework_orders": "返工单",
    "production_work_logs": "报工",
    "processing_position_operations": "工序实例",
    "processing_set_part_tokens": "部位码",
    "processing_order_sets": "套号",
    "processing_orders": "加工单",
    "order_shipment_items": "发货明细",
    "order_shipments": "发货单",
    "order_items": "订单明细",
    "order_logistics": "物流",
    "print_logs": "打印流水",
    "after_sales_tickets": "售后工单",
    "receipt_allocations": "收款核销明细",
    "finance_transactions": "收款流水",
    "outbound_order_items": "出库单明细",
    "outbound_orders": "出库单",
    "inbound_order_items": "入库单明细",
    "finished_goods_stock": "成品在库",
    "orders": "订单",
}


def load_env(path: Path) -> dict:
    cfg = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


def locators(order_ids: list, po_ids: list, ticket_ids: list = (), shipment_ids: list = (),
             transaction_ids: list = ()) -> list:
    """按删除拓扑生成 [(表, WHERE 条件, 参数列表)] —— **纯函数**，不查库，故可零数据库单测。

    参数 = 各级要匹配的**父 id 列表**（键空间见 `DELETE_PLAN` 注释）。父 id 由 `run()` 预先查好
    传进来（先查父 id、再按父 id 定位子行）；一张表的两侧定位合成同一条 DELETE：
    `WHERE a = ANY($1::text[]) OR b = ANY($2::text[])`（每一侧都是精确主键等值）。
    """
    keys = {
        "order": list(order_ids),
        "po": list(po_ids),
        "ticket": list(ticket_ids),
        "shipment": list(shipment_ids),
        "transaction": list(transaction_ids),
    }
    return [(table,
             " OR ".join(f"{col} = ANY(${i}::text[])" for i, (col, _) in enumerate(columns, 1)),
             [keys[ks] for _, ks in columns])
            for table, columns in DELETE_PLAN]


async def run(order_nos: list, env_file: Path, apply: bool, include_soft_deleted: bool = False) -> int:
    cfg = load_env(env_file)
    for key in ("RDS_HOST", "RDS_USER", "RDS_PASSWORD", "RDS_DB"):
        if not cfg.get(key):
            print(f"❌ {env_file} 缺少 {key}", file=sys.stderr)
            return 2
    try:
        import asyncpg  # type: ignore
    except ImportError:
        print("❌ 需要 asyncpg（可用 backend/ai-agent-service/.venv/bin/python 运行）", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(
        host=cfg["RDS_HOST"],
        port=int(cfg.get("RDS_PORT", "5432")),
        user=cfg["RDS_USER"],
        password=cfg["RDS_PASSWORD"],
        database=cfg.get("RDS_DB", "ai_customer_service"),
        timeout=15,
    )
    try:
        if include_soft_deleted:
            print("⚠️  --include-soft-deleted：已软删（deleted≠0）的墓碑单也会被匹配 ⇒ 行级删除不可逆。")
        rows = await conn.fetch(
            "SELECT id, order_no, status, customer_name, remark FROM orders "
            "WHERE order_no = ANY($1::text[]) AND (deleted = 0 OR $2::bool)",
            order_nos, include_soft_deleted,
        )
        missing = set(order_nos) - {r["order_no"] for r in rows}
        print(f"匹配订单 {len(rows)}/{len(order_nos)} 个" + (f"（未找到: {sorted(missing)}）" if missing else ""))
        ids = [r["id"] for r in rows]
        if not ids:
            return 0
        # 子表父 id 一律**不带 deleted = 0**：软删行同样持有各自子表的外键，漏掉它的子行就删不掉它
        po_rows = await conn.fetch(
            "SELECT id, order_id, processing_order_no, status FROM processing_orders "
            "WHERE order_id = ANY($1::text[])",
            ids,
        )
        ticket_ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM after_sales_tickets WHERE order_id = ANY($1::text[])", ids)]
        shipment_ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM order_shipments WHERE order_id = ANY($1::text[])", ids)]
        txn_ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM finance_transactions WHERE order_id = ANY($1::text[])", ids)]
        steps = locators(ids, [p["id"] for p in po_rows], ticket_ids, shipment_ids, txn_ids)
        for r in rows:
            po = [p["processing_order_no"] for p in po_rows if p["order_id"] == r["id"]]
            print(f"  · {r['order_no']} [{r['status']}] {r['customer_name']} "
                  f"| 加工单: {po or '无'} | 明细: 见汇总")
        counts = [(t, await conn.fetchval(f"SELECT COUNT(*) FROM {t} WHERE {where}", *params))
                  for t, where, params in steps]
        print("  汇总: " + " | ".join(f"{TABLE_LABELS[t]} {n} 行" for t, n in counts))

        if not apply:
            print("🟡 dry-run（未删除）。确认无误后加 --apply 执行。")
            return 0

        deleted = []
        async with conn.transaction():
            for t, where, params in steps:
                deleted.append((t, await conn.execute(f"DELETE FROM {t} WHERE {where}", *params)))
        print("✅ 已删除: " + " | ".join(f"{TABLE_LABELS[t]} {res}" for t, res in deleted))
        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="按订单号精确删除测试订单及其子行（默认 dry-run）")
    ap.add_argument("--order-nos", required=True, help="逗号分隔的订单号（精确匹配）")
    ap.add_argument("--apply", action="store_true", help="真正执行删除（默认仅 dry-run）")
    ap.add_argument("--include-soft-deleted", action="store_true",
                    help="把已软删（deleted≠0）的墓碑单也纳入匹配（默认只匹配未软删的订单）")
    ap.add_argument("--env-file", default="backend/admin-api/.env", help="env 文件路径（取 RDS_*）")
    args = ap.parse_args()
    order_nos = [x.strip() for x in args.order_nos.split(",") if x.strip()]
    if not order_nos:
        print("❌ --order-nos 为空", file=sys.stderr)
        return 2
    return asyncio.run(run(order_nos, Path(args.env_file), args.apply, args.include_soft_deleted))


if __name__ == "__main__":
    sys.exit(main())
