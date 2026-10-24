#!/usr/bin/env python3
"""补测通知中心：配置「售后新工单」模板+规则 → 真实创建工单触发事件 → 保留站内信。

背景：主回归 NTF-01 只验了手动创建/已读/删除，最后把消息删掉，通知中心为空；
且没有验「业务事件 → 规则 → 模板 → 站内信」这条真实生成链路。本脚本补这一条，
并**保留**生成的消息供验收查看（1 条未读 + 1 条已读）。
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
ADMIN_PHONE = "13900001025"
SMS_CODE = "123456"


def load_env() -> dict[str, str]:
    d = {}
    for line in (REPO / "backend/admin-api/.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def psql(e: dict[str, str], sql: str) -> str:
    p = subprocess.run(
        ["psql", "-h", e["RDS_HOST"], "-p", e.get("RDS_PORT", "5432"),
         "-U", e["RDS_USER"], "-d", e["RDS_DB"], "-X", "-q", "-A", "-t"],
        input=sql, capture_output=True, text=True,
        env={**os.environ, "PGPASSWORD": e["RDS_PASSWORD"]},
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()


def as_list(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "records", "list", "rows", "notifications"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def main() -> int:
    e = load_env()
    c = httpx.Client(base_url=BASE, timeout=60)
    tok = c.post("/api/auth/sms/login",
                 json={"phone": ADMIN_PHONE, "code": SMS_CODE}).json()["data"]["accessToken"]
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    checks: list[dict] = []

    def ck(name: str, cond: bool, detail: dict) -> None:
        checks.append({"name": name, "pass": bool(cond), "detail": detail})
        assert cond, f"{name}: {detail}"

    # 前置：租户通知开关
    st = c.get("/api/admin/settings", headers=h).json()["data"]
    ck("租户系统通知开关已开启", st.get("notificationEnabled") is True,
       {"notificationEnabled": st.get("notificationEnabled")})
    if st.get("notificationEnabled") is not True:
        r = c.put("/api/admin/settings", headers=h, json={"notificationEnabled": True})
        ck("补开系统通知开关", r.status_code == 200, {"http": r.status_code})

    # 订单
    o1 = psql(e, f"select id from orders where tenant_id={TENANT_ID} and order_no='20261018751390021'")
    o5 = psql(e, f"select id from orders where tenant_id={TENANT_ID} and order_no='20261018167300025'")
    ck("定位已完成订单 O1/O5", bool(o1 and o5), {"o1": o1, "o5": o5})

    # 模板
    tpl_body = {
        "name": "售后新工单待办（回归）",
        "type": "after_sales",
        "channel": "internal",
        "templateContent": "新售后工单：{{ticketNo}}（{{ticketType}}），请及时处理。",
        "variables": "ticketNo,ticketType",
        "status": "active",
    }
    r = c.post("/api/admin/notification-templates", headers=h, json=tpl_body)
    ck("创建售后工单通知模板", r.status_code == 200, {"http": r.status_code, "resp": r.json()})
    tpl = r.json()["data"]
    tpl_id = tpl["id"]

    # 规则
    rule_body = {
        "eventType": "after_sales_created",
        "recipientType": "employee",
        "channels": "internal",
        "enabled": True,
        "templateId": tpl_id,
    }
    r = c.post("/api/admin/notification-rules", headers=h, json=rule_body)
    ck("创建 after_sales_created 通知规则", r.status_code == 200, {"http": r.status_code, "resp": r.json()})
    rule = r.json()["data"]
    rule_id = rule["id"]

    # 真实业务事件：创建两张售后工单
    tickets = []
    for oid, ttype, desc in [
        (o1, "repair", "回归补测-通知中心真实消息（维修）"),
        (o5, "other", "回归补测-通知中心真实消息（其它）"),
    ]:
        r = c.post("/api/admin/after-sales", headers=h, json={
            "orderId": oid, "ticketType": ttype, "description": desc, "priority": "normal",
        })
        ck(f"创建售后工单触发事件（{ttype}）", r.status_code == 200,
           {"http": r.status_code, "resp": r.json()})
        tickets.append(r.json()["data"])

    # 通知列表
    r = c.get("/api/admin/notifications?page=1&size=50", headers=h)
    ck("通知中心列表可读", r.status_code == 200, {"http": r.status_code})
    page = r.json()["data"]
    notifications = as_list(page)
    # 只取本规则产生的两条
    ours = [n for n in notifications if str(n.get("ruleId")) == str(rule_id) or
            str(n.get("rule_id")) == str(rule_id)]
    ck("事件生成 ≥2 条站内信", len(ours) >= 2,
       {"total": page.get("total"), "ours": len(ours), "notifications": ours})
    for t in tickets:
        ticket_no = t.get("ticketNo") or t.get("ticket_no")
        ck(f"通知内容含工单号 {ticket_no}", any(ticket_no in (n.get("content") or "") for n in ours),
           {"ticketNo": ticket_no, "contents": [n.get("content") for n in ours]})

    # 未读数
    r = c.get("/api/admin/notifications/unread-count", headers=h)
    unread = r.json()["data"]
    before = int(unread.get("count") or 0)
    ck("未读数 ≥2", before >= 2, {"unread": before})

    # 标记 1 条已读，保留 1 条未读
    nid = ours[0].get("id")
    r = c.put(f"/api/admin/notifications/{nid}/read", headers=h)
    ck("标记一条已读", r.status_code == 200, {"http": r.status_code})
    r = c.get("/api/admin/notifications/unread-count", headers=h)
    after = int(r.json()["data"].get("count") or 0)
    ck("未读数减 1 且仍 ≥1", after == before - 1 and after >= 1, {"before": before, "after": after})

    # 持久化读数
    rows = psql(e, f"""select id,rule_id,template_id,recipient_id,channel,status,
                       replace(content, '|', '/') from notifications
                       where tenant_id={TENANT_ID} order by created_at desc limit 5""")
    ck("DB 中通知行 ≥2", len([x for x in rows.splitlines() if x]) >= 2,
       {"rows": rows})

    out = {
        "tenant_id": TENANT_ID,
        "template": tpl,
        "rule": rule,
        "tickets": [{"id": t.get("id"), "ticketNo": t.get("ticketNo"), "type": t.get("ticketType")}
                    for t in tickets],
        "notifications": ours,
        "unread_before": before,
        "unread_after": after,
        "db_rows": rows.splitlines(),
        "checks": checks,
        "all_pass": all(x["pass"] for x in checks),
    }
    (ROOT / "out/notification-center-backfill.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
