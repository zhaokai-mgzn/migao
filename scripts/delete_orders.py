#!/usr/bin/env python3
"""按订单号精确删除测试/验收订单及其加工单（默认 dry-run，需 --apply 才执行）。

用途：清理验收过程在 dev 库创建的测试数据（订单 + 加工单 + 明细）。

用法：
    python3 scripts/delete_orders.py --order-nos 20260912392560001,20260912395290001
    python3 scripts/delete_orders.py --order-nos 2026... --apply

安全设计：
    - **仅按显式 order_no 精确匹配**（orders.order_no UNIQUE），不支持通配/批量条件；
    - 默认 dry-run，打印将删除的行数；必须显式 --apply 才真正删除；
    - 事务内按依赖顺序删除 processing_orders → order_items → orders；
    - 连接参数取自 backend/admin-api/.env 的 RDS_* 变量（可用 --env-file 覆盖），
      不硬编码任何凭据、不读 .env 以外的配置。
"""
import argparse
import asyncio
import sys
from pathlib import Path


def load_env(path: Path) -> dict:
    cfg = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


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
        po_rows = await conn.fetch(
            "SELECT order_id, processing_order_no, status FROM processing_orders "
            "WHERE order_id = ANY($1::text[]) AND deleted = 0",
            ids,
        )
        item_count = await conn.fetchval(
            "SELECT COUNT(*) FROM order_items WHERE order_id = ANY($1::text[]) AND deleted = 0", ids
        )
        for r in rows:
            po = [p["processing_order_no"] for p in po_rows if p["order_id"] == r["id"]]
            print(f"  · {r['order_no']} [{r['status']}] {r['customer_name']} "
                  f"| 加工单: {po or '无'} | 明细: 见汇总")
        print(f"  汇总: 加工单 {len(po_rows)} 行 | 订单明细 {item_count} 行 | 订单 {len(ids)} 行")

        if not apply:
            print("🟡 dry-run（未删除）。确认无误后加 --apply 执行。")
            return 0

        async with conn.transaction():
            po_deleted = await conn.execute("DELETE FROM processing_orders WHERE order_id = ANY($1::text[])", ids)
            item_deleted = await conn.execute("DELETE FROM order_items WHERE order_id = ANY($1::text[])", ids)
            order_deleted = await conn.execute("DELETE FROM orders WHERE id = ANY($1::text[])", ids)
        print(f"✅ 已删除: {po_deleted} / {item_deleted} / {order_deleted}（加工单/明细/订单）")
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
