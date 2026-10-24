#!/usr/bin/env python3
"""补充场景收口：复核 worker 发货单的打包/撤销打包/发货留痕，并完成订单。"""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BASE = "https://api.migaozn.com"
TENANT_ID, TENANT_CODE = 46, "f-l9lu"
ADMIN_PHONE, SMS_CODE = "13900001025", "123456"
ORDER_NO = "20261018167300025"

def env():
    d = {}
    for line in (REPO / "backend/admin-api/.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d

def psql(e, sql):
    p = subprocess.run(["psql", "-h", e["RDS_HOST"], "-p", e.get("RDS_PORT", "5432"),
                        "-U", e["RDS_USER"], "-d", e["RDS_DB"], "-X", "-q", "-A", "-t"],
                       input=sql, capture_output=True, text=True,
                       env={**os.environ, "PGPASSWORD": e["RDS_PASSWORD"]})
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()

def main():
    e = env()
    oid = psql(e, f"select id from orders where tenant_id={TENANT_ID} and order_no='{ORDER_NO}'")
    c = httpx.Client(base_url=BASE, timeout=60)
    tok = c.post("/api/auth/sms/login", json={"phone": ADMIN_PHONE, "code": SMS_CODE}).json()["data"]["accessToken"]
    h = {"Authorization": f"Bearer {tok}"}
    checks = []
    def ck(name, cond, detail):
        checks.append({"name": name, "pass": bool(cond), "detail": detail})
        assert cond, f"{name}: {detail}"
    d = c.get(f"/api/admin/orders/{oid}", headers=h).json()["data"]
    ck("订单已由工人发货（shipped）", d["status"] == "shipped", {"status": d["status"]})
    payload = c.get(f"/api/admin/orders/{oid}/shipments", headers=h).json()["data"]
    ships = payload.get("shipments") if isinstance(payload, dict) else payload
    ws = [s for s in ships if s.get("source") == "worker"]
    ck("存在 worker 来源发货单", len(ws) >= 1, {"shipment_count": len(ships), "worker_count": len(ws)})
    s = ws[0]
    ck("发货单含实发明细", len(s.get("items") or []) >= 1, {"items": s.get("items"), "totals": s.get("shipped_totals")})
    ck("打包留痕（packed_at）", bool(s.get("packed_at")), {"packed_at": s.get("packed_at"), "packed_by": s.get("packed_by")})
    ck("撤销打包留痕（unpacked_at/unpack_reason）", bool(s.get("unpacked_at")), {"unpacked_at": s.get("unpacked_at"), "unpack_reason": s.get("unpack_reason")})
    ck("发货人 = 回归工人一", s.get("shipped_by") == "回归工人一", {"shipped_by": s.get("shipped_by")})
    r = c.put(f"/api/admin/orders/{oid}/status", headers=h, json={"status": "completed"})
    d2 = c.get(f"/api/admin/orders/{oid}", headers=h).json()["data"]
    ck("商家确认收货 → completed", r.status_code == 200 and d2["status"] == "completed",
       {"http": r.status_code, "status": d2["status"], "receivedAt": d2.get("receivedAt")})
    out = {"order_no": ORDER_NO, "order_id": oid, "shipment": s, "checks": checks,
           "all_pass": all(x["pass"] for x in checks)}
    (ROOT / "out/worker-shipment-postcheck.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["all_pass"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
