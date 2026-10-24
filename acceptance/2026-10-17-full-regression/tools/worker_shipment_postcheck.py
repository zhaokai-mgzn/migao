#!/usr/bin/env python3
"""补充场景：工人端「打包 → 撤销打包 → 再打包 → 发货 → 商家确认收货」。

覆盖主回归未触发的 `packed` 状态与 `worker unpack` 撤销路径（issue #5648 载体分离）。
证据落盘：`out/worker-shipment-postcheck.json`。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BASE = "https://api.migaozn.com"
TENANT_ID = 46
TENANT_CODE = "f-l9lu"
ADMIN_PHONE = "13900001025"
SMS_CODE = "123456"
WORKER_NO = "W-1001"
WORKER_PIN = "246810"
ORDER_NO = "20261018167300025"  # O5：producing，加工单已完成


def load_env() -> dict[str, str]:
    env = {}
    for line in (REPO / "backend/admin-api/.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def psql(env: dict[str, str], sql: str) -> str:
    p = subprocess.run(
        ["psql", "-h", env["RDS_HOST"], "-p", env.get("RDS_PORT", "5432"),
         "-U", env["RDS_USER"], "-d", env["RDS_DB"], "-X", "-q", "-A", "-t"],
        input=sql, capture_output=True, text=True,
        env={**os.environ, "PGPASSWORD": env["RDS_PASSWORD"]},
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()


def main() -> int:
    env = load_env()
    order_id = psql(env, f"select id from orders where tenant_id={TENANT_ID} and order_no='{ORDER_NO}'")
    assert order_id, "O5 不存在"
    c = httpx.Client(base_url=BASE, timeout=60.0)
    out: dict = {"order_id": order_id, "order_no": ORDER_NO, "checks": []}

    def check(name: str, cond: bool, detail: dict) -> None:
        out["checks"].append({"name": name, "pass": bool(cond), "detail": detail})
        assert cond, f"{name} 失败: {detail}"

    # admin login
    r = c.post("/api/auth/sms/login", json={"phone": ADMIN_PHONE, "code": SMS_CODE})
    admin = r.json()["data"]["accessToken"]
    ah = {"Authorization": f"Bearer {admin}"}

    # worker login
    r = c.post("/api/worker/login", json={
        "workerNo": WORKER_NO, "pin": WORKER_PIN, "enterpriseCode": TENANT_CODE,
    })
    wd = r.json()["data"]
    sid = wd["session_id"]
    wh = {"X-Worker-Session-Id": sid}
    out["worker"] = {"worker_id": wd["worker_id"], "worker_name": wd["worker_name"]}

    # 前置状态（本场景可能从 packing 中断恢复）
    detail = c.get(f"/api/admin/orders/{order_id}", headers=ah).json()["data"]
    status = detail["status"]
    out["initial_status"] = status
    if status == "producing":
        r = c.post(f"/api/worker/shipment/orders/{order_id}/pack", headers=wh)
        detail = c.get(f"/api/admin/orders/{order_id}", headers=ah).json()["data"]
        check("工人打包 → packed", r.status_code == 200 and detail["status"] == "packed",
              {"http": r.status_code, "status": detail["status"], "resp": r.json()})
    else:
        check("前置：订单已处于 packed（首轮 pack 已成功）", status == "packed", {"status": status})

    # unpack -> producing
    r = c.post(f"/api/worker/shipment/orders/{order_id}/unpack",
               headers=wh, json={"reason": "回归补充-打包规格复核"})
    detail = c.get(f"/api/admin/orders/{order_id}", headers=ah).json()["data"]
    check("工人撤销打包 → producing", r.status_code == 200 and detail["status"] == "producing",
          {"http": r.status_code, "status": detail["status"], "resp": r.json()})

    # pack again
    r = c.post(f"/api/worker/shipment/orders/{order_id}/pack", headers=wh)
    detail = c.get(f"/api/admin/orders/{order_id}", headers=ah).json()["data"]
    check("再次打包 → packed", r.status_code == 200 and detail["status"] == "packed",
          {"http": r.status_code, "status": detail["status"]})

    # ship：逐行实发明细（合同要求 order_item_id / shipped_quantity / unit）
    detail = c.get(f"/api/admin/orders/{order_id}", headers=ah).json()["data"]
    items = [
        {"order_item_id": it["id"], "shipped_quantity": it["quantity"],
         "unit": it.get("unit") or "米", "product_name": it.get("productName")}
        for it in (detail.get("items") or detail.get("orderItems") or [])
    ]
    out["ship_items"] = items
    r = c.post(f"/api/worker/shipment/orders/{order_id}/ship",
               headers={**wh, "X-Client-Request-Id": "reg-worker-ship-o5-v2"},
               json={"trackingNo": "SF13900001025", "logisticsCompany": "顺丰速运", "items": items})
    ship = r.json()
    r2 = c.get(f"/api/admin/orders/{order_id}", headers=ah)
    check("工人发货 → shipped", r.status_code == 200 and r2.json()["data"]["status"] == "shipped",
          {"http": r.status_code, "status": r2.json()["data"]["status"], "resp": ship})

    # shipments row
    r = c.get(f"/api/admin/orders/{order_id}", headers=ah)
    shipments = r.json()["data"].get("shipments") or []
    check("订单详情可见 worker 发货单", len(shipments) >= 1,
          {"shipment_count": len(shipments), "shipments": shipments[:1]})

    # complete
    r = c.put(f"/api/admin/orders/{order_id}/status", headers=ah, json={"status": "completed"})
    r2 = c.get(f"/api/admin/orders/{order_id}", headers=ah)
    check("商家确认收货 → completed", r.status_code == 200 and r2.json()["data"]["status"] == "completed",
          {"http": r.status_code, "status": r2.json()["data"]["status"]})

    out["all_pass"] = all(x["pass"] for x in out["checks"])
    (ROOT / "out/worker-shipment-postcheck.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
