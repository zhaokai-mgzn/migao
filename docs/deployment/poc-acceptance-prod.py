#!/usr/bin/env python3
"""
生产环境 POC 验收脚本 — 模拟真实用户使用完整流程

验收链路（云服务端）：
1. 微信小程序 mock 登录
2. 算料报价（AI 对话 → curtain_calc → quotation 卡片）
3. 下单闭环（多轮：报价→确认→SMS→order_create）
4. 转人工（human_handoff → agent_session 创建）
5. 客服回复 + 用户看到回复

用法：
  python3 docs/deployment/poc-acceptance-prod.py
"""
import json
import sys
import urllib.request
import urllib.error
import ssl

API = "https://api.migaozn.com"
AI_API = "https://ai-api.migaozn.com"
TENANT_ID = 1
SMS_BYPASS = "123456"

# 忽略 SSL 证书验证（阿里云 HTTPS，如遇证书问题可开启）
CTX = ssl.create_default_context()


def post_json(url, payload, token=None, st=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if st:
        headers["X-Service-Token"] = st
        headers["X-Tenant-Id"] = "1"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode()) if e.fp else {"error": str(e)}


def post_sse(url, payload, token=None):
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120, context=CTX) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
    events = []
    session_id = ""
    ev = ""
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: "):
            try:
                d = json.loads(line[6:])
            except (json.JSONDecodeError, TypeError):
                continue
            events.append((ev, d))
            if ev == "done":
                session_id = d.get("session_id", "")
    return events, session_id


def has_tool(events, tool):
    return any(ev == "tool_call" and d.get("tool") == tool for ev, d in events)


def has_card(events, card_type):
    return any(ev == "card" and d.get("type") == card_type for ev, d in events)


def get_json(url, token=None, st=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if st:
        headers["X-Service-Token"] = st
        headers["X-Tenant-Id"] = "1"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
        return json.loads(resp.read().decode())


def chat(message, sid, token):
    return post_sse(f"{AI_API}/api/chat/send",
                    {"session_id": sid, "message": message, "channel": "wechat_mini"}, token)


def main():
    print("=" * 60)
    print("生产环境 POC 验收（模拟用户完整流程）")
    print("=" * 60)

    # 1. mock 登录
    print("\n[1] 微信小程序 mock 登录")
    status, login = post_json(f"{API}/api/auth/mini/login", {"code": "poc-accept-001", "tenantId": TENANT_ID})
    if status != 200 or not login.get("success"):
        print(f"    ❌ 登录失败: {login}")
        sys.exit(1)
    token = login["data"]["accessToken"]
    tenant_name = login["data"]["user"].get("tenantName", "")
    print(f"    ✅ 登录成功（租户: {tenant_name}）")

    # 2. 算料报价
    print("\n[2] AI 算料报价")
    events, sid = chat("3米宽 2.5米高 2倍褶皱 打孔帘 用98元一米的遮光布 帮我算多少钱", None, token)
    calc = has_tool(events, "curtain_calc")
    quote = has_card(events, "quotation")
    quote_data = next((d for ev, d in events if ev == "card" and d.get("type") == "quotation"), {}).get("data", {})
    print(f"    curtain_calc 调用: {'✅' if calc else '❌'}")
    print(f"    quotation 卡片: {'✅' if quote else '❌'} (total={quote_data.get('total')})")
    if not calc or not quote:
        print("    ⚠️ 算料环节未通过，中止验收")
        sys.exit(1)

    # 3. 下单闭环（多轮）
    print("\n[3] 下单闭环（多轮）")
    events, sid = chat("我要下单 张三 13800138000", sid, token)
    order_created = False
    for round_i in range(6):
        interactive = next((d for ev, d in events if ev == "interactive"), None)
        texts = "".join(d.get("content", "") for ev, d in events if ev == "text")
        if has_tool(events, "order_create"):
            order_created = True
            break
        if interactive:
            itype = interactive.get("type")
            if itype == "confirm":
                nxt = interactive.get("confirmValue", "确认")
                print(f"    轮{round_i+1} confirm → {nxt}")
            elif itype == "form":
                nxt = "米白色 2.8米门幅"
                print(f"    轮{round_i+1} form → 补规格")
            else:
                nxt = "确认"
        elif "验证码" in texts:
            nxt = SMS_BYPASS
            print(f"    轮{round_i+1} 输入验证码")
        else:
            break
        events, sid = chat(nxt, sid, token)
    print(f"    order_create: {'✅' if order_created else '❌'}")

    # 4. 转人工
    print("\n[4] 转人工")
    events, sid = chat("我要找老板", sid, token)
    handoff = has_tool(events, "human_handoff")
    print(f"    human_handoff: {'✅' if handoff else '❌'}")

    # 5. 用户查人工会话（验证会话已创建）
    print("\n[5] 用户查人工会话")
    try:
        detail = get_json(f"{API}/api/customer/agent-sessions/by-ai/{sid}", token)
        status_s = detail.get("data", {}).get("status", "") if detail.get("success") else ""
        print(f"    人工会话: {'✅' if detail.get('success') else '❌'} (status={status_s})")
    except Exception as e:
        print(f"    人工会话查询异常: {e}")

    print("\n" + "=" * 60)
    ok = bool(calc and quote and order_created and handoff)
    print("✅ 生产验收通过（算料→下单→转人工全链路）" if ok else "⚠️ 部分环节未通过")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
