#!/usr/bin/env python3
"""通知中心补测收口：复核事件生成的 2 条真实站内信，标记 1 条已读，保留 1 条未读。"""
from __future__ import annotations
import json, os, subprocess
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BASE = "https://api.migaozn.com"
TENANT_ID, ADMIN_PHONE, SMS_CODE = 46, "13900001025", "123456"
TITLE = "售后新工单待办（回归）"

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
    c = httpx.Client(base_url=BASE, timeout=60)
    tok = c.post("/api/auth/sms/login", json={"phone": ADMIN_PHONE, "code": SMS_CODE}).json()["data"]["accessToken"]
    h = {"Authorization": f"Bearer {tok}"}
    checks = []
    def ck(name, cond, detail):
        checks.append({"name": name, "pass": bool(cond), "detail": detail})
        assert cond, f"{name}: {detail}"

    page = c.get("/api/admin/notifications?page=1&size=50", headers=h).json()["data"]
    items = page.get("items", [])
    ours = [n for n in items if n.get("title") == TITLE]
    ck("通知中心有 2 条事件生成的真实站内信", len(ours) == 2,
       {"total": page.get("total"), "ours": len(ours)})
    db = psql(e, f"select content from notifications where tenant_id={TENANT_ID} and title='{TITLE}' order by created_at")
    ck("DB 中同一规则生成 2 行", len(db.splitlines()) == 2, {"db": db.splitlines()})
    for no in ("AS-20261018-0004", "AS-20261018-0005"):
        ck(f"通知内容含工单号 {no}", any(no in (n.get("content") or "") for n in ours),
           {"contents": [n.get("content") for n in ours]})

    unread = int(c.get("/api/admin/notifications/unread-count", headers=h).json()["data"].get("count") or 0)
    ck("保留 1 条未读", unread == 1, {"unread": unread})
    sent = c.get("/api/admin/notifications?status=sent&page=1&size=50", headers=h).json()["data"]
    read = c.get("/api/admin/notifications?status=read&page=1&size=50", headers=h).json()["data"]
    ck("sent 筛选 = 1（未读）", int(sent.get("total") or 0) == 1, {"total": sent.get("total")})
    ck("read 筛选 = 1（已读）", int(read.get("total") or 0) == 1, {"total": read.get("total")})

    out = {"tenant_id": TENANT_ID, "title": TITLE, "notifications": ours,
           "db_rows": db.splitlines(), "unread": unread, "sent_total": sent.get("total"), "read_total": read.get("total"),
           "checks": checks, "all_pass": all(x["pass"] for x in checks)}
    (ROOT / "out/notification-center-backfill.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["all_pass"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
