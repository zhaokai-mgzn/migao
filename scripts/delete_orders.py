#!/usr/bin/env python3
"""按订单号精确删除测试/验收订单及其加工单/工序实例/报工（默认 dry-run，需 --apply 才执行）。

用途：清理验收过程在 dev 库创建的测试数据（订单 + 明细 + 物流 + 加工单 + 工序实例 + 报工）。

用法：
    python3 scripts/delete_orders.py --order-nos 20260912392560001,20260912395290001
    python3 scripts/delete_orders.py --order-nos 2026... --apply

安全设计：
    - **仅按显式 order_no 精确匹配**（orders.order_no UNIQUE），不支持通配/批量条件；
    - 默认 dry-run，逐级打印将删除的行数；必须显式 --apply 才真正删除；
    - 事务内按 `DELETE_PLAN` 的依赖拓扑删除（被引用表先于引用表）；
    - 连接参数取自 backend/admin-api/.env 的 RDS_* 变量（可用 --env-file 覆盖），
      不硬编码任何凭据、不读 .env 以外的配置。
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 删除顺序 = 外键依赖拓扑（被引用表先于引用表），每级 = (表, 定位列, 键空间)。
# 真值源：docs/sql/schema.sql + V49 迁移的外键链 ——
#   orders ← order_items / order_logistics / processing_orders
#   processing_orders ← processing_position_operations / production_work_logs
# ⚠️ 新增指向 orders / order_items / processing_orders 的外键时必须同步本表，
#    否则 DELETE 父表时会被外键拦下（issue #4242：V49 加了两层，脚本没跟上 ⇒ 带加工单的订单删不掉）。
DELETE_PLAN = (
    ("production_work_logs", "processing_order_id", "po"),
    ("processing_position_operations", "processing_order_id", "po"),
    ("processing_orders", "order_id", "order"),
    ("order_items", "order_id", "order"),
    ("order_logistics", "order_id", "order"),
    ("orders", "id", "order"),
)
TABLE_LABELS = {
    "production_work_logs": "报工",
    "processing_position_operations": "工序实例",
    "processing_orders": "加工单",
    "order_items": "订单明细",
    "order_logistics": "物流",
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


def locators(order_ids: list, po_ids: list) -> list:
    """按删除拓扑生成 [(表, 定位列, 参数)]；参数 = 该级要匹配的主键列表。

    `po` 键空间 = 该订单的**全部**加工单 id（含软删行 —— 软删加工单仍持有子表外键，
    不定位它的子行就会在删父表时被外键拦下）。
    """
    keys = {"order": order_ids, "po": po_ids}
    return [(t, c, keys[k]) for t, c, k in DELETE_PLAN]


async def run(order_nos: list, env_file: Path, apply: bool) -> int:
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
        rows = await conn.fetch(
            "SELECT id, order_no, status, customer_name, remark FROM orders "
            "WHERE order_no = ANY($1::text[]) AND deleted = 0",
            order_nos,
        )
        missing = set(order_nos) - {r["order_no"] for r in rows}
        print(f"匹配订单 {len(rows)}/{len(order_nos)} 个" + (f"（未找到: {sorted(missing)}）" if missing else ""))
        ids = [r["id"] for r in rows]
        if not ids:
            return 0
        # 不加 deleted = 0：软删加工单同样会被 DELETE（WHERE order_id = ANY），其子行必须先删
        po_rows = await conn.fetch(
            "SELECT id, order_id, processing_order_no, status FROM processing_orders "
            "WHERE order_id = ANY($1::text[])",
            ids,
        )
        steps = locators(ids, [p["id"] for p in po_rows])
        for r in rows:
            po = [p["processing_order_no"] for p in po_rows if p["order_id"] == r["id"]]
            print(f"  · {r['order_no']} [{r['status']}] {r['customer_name']} "
                  f"| 加工单: {po or '无'} | 明细: 见汇总")
        counts = [(t, await conn.fetchval(f"SELECT COUNT(*) FROM {t} WHERE {c} = ANY($1::text[])", a))
                  for t, c, a in steps]
        print("  汇总: " + " | ".join(f"{TABLE_LABELS[t]} {n} 行" for t, n in counts))

        if not apply:
            print("🟡 dry-run（未删除）。确认无误后加 --apply 执行。")
            return 0

        deleted = []
        async with conn.transaction():
            for t, c, a in steps:
                deleted.append((t, await conn.execute(f"DELETE FROM {t} WHERE {c} = ANY($1::text[])", a)))
        print("✅ 已删除: " + " | ".join(f"{TABLE_LABELS[t]} {res}" for t, res in deleted))
        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="按订单号精确删除测试订单及加工单（默认 dry-run）")
    ap.add_argument("--order-nos", required=True, help="逗号分隔的订单号（精确匹配）")
    ap.add_argument("--apply", action="store_true", help="真正执行删除（默认仅 dry-run）")
    ap.add_argument("--env-file", default="backend/admin-api/.env", help="env 文件路径（取 RDS_*）")
    args = ap.parse_args()
    order_nos = [x.strip() for x in args.order_nos.split(",") if x.strip()]
    if not order_nos:
        print("❌ --order-nos 为空", file=sys.stderr)
        return 2
    return asyncio.run(run(order_nos, Path(args.env_file), args.apply))


if __name__ == "__main__":
    sys.exit(main())
