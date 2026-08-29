#!/usr/bin/env python3
"""
POC 下单闭环多轮集成测试

验证完整链路：mock 登录 → 算料报价(quotation) → 下单引导(form/confirm) → 补规格 → confirm → SMS(bypass) → order_create

用法：
  ADMIN_API=http://localhost:8080 AI_API=http://localhost:8001 \
  python3 docs/deployment/poc-order-flow-test.py

依赖：admin-api(:8080) + ai-agent-service(:8001) 已启动；SMS_BYPASS_CODE=123456
"""
import json
import os
import sys
import urllib.request
import urllib.error

ADMIN_API = os.environ.get("ADMIN_API", "http://localhost:8080")
AI_API = os.environ.get("AI_API", "http://localhost:8001")
TENANT_ID = 1
SMS_BYPASS = "123456"


def post_json(url, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode() if e.fp else ""}


def post_sse(url, payload, token=None):
    """SSE 流式请求，返回 (events, session_id)"""
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        return [], ""
    events = []
    session_id = ""
    current_event = ""
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("event: "):
            current_event = line[7:]
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            events.append((current_event, data))
            if current_event == "done":
                session_id = data.get("session_id", "")
    return events, session_id


def find_tool_call(events, tool_name):
    for ev, data in events:
        if ev == "tool_call" and data.get("tool") == tool_name:
            return data.get("args", {})
    return None


def find_card(events, card_type):
    for ev, data in events:
        if ev == "card" and data.get("type") == card_type:
            return data.get("data", {})
    return None


def find_interactive(events, component=None):
    for ev, data in events:
        if ev == "interactive" and (component is None or data.get("type") == component):
            return data
    return None


def find_text(events):
    texts = [d.get("content", "") for ev, d in events if ev == "text"]
    return "".join(texts)


def chat(message, session_id, token):
    return post_sse(f"{AI_API}/api/chat/send",
                    {"session_id": session_id, "message": message, "channel": "wechat_mini"}, token)


def main():
    print("=" * 60)
    print("POC 下单闭环多轮集成测试")
    print("=" * 60)

    # 1. mock 登录
    print("\n[1] mock 登录")
    status, data = post_json(f"{ADMIN_API}/api/auth/mini/login", {"code": "poc-order-002", "tenantId": TENANT_ID})
    if status != 200 or not data.get("success"):
        print(f"    ❌ 登录失败: {data}")
        sys.exit(1)
    token = data["data"]["accessToken"]
    print("    ✅ 登录成功")

    # 2. 算料报价（含完整信息，减少下单补规格环节）
    print("\n[2] 算料报价")
    events, session_id = chat("3米宽 2.5米高 2倍褶皱 打孔帘 用98元一米的遮光布 米白色 2.8米门幅 帮我算多少钱", None, token)
    quote = find_card(events, "quotation")
    calc_args = find_tool_call(events, "curtain_calc")
    print(f"    {'✅' if calc_args else '❌'} curtain_calc: total={quote.get('total') if quote else 'N/A'}")

    # 3~N. 下单闭环（轮次驱动：form→confirm→SMS→order_create）
    print("\n[3] 下单闭环（多轮）")
    events, session_id = chat("我要下单，张三 13800138000", session_id, token)

    order_create = find_tool_call(events, "order_create")
    confirm_seen = False
    sms_seen = False
    max_rounds = 6
    for round_i in range(max_rounds):
        if order_create:
            break
        interactive = find_interactive(events)
        text = find_text(events)
        # 打印本轮关键事件
        for ev, d in events:
            if ev == "interactive":
                print(f"    轮{round_i+1} interactive: type={d.get('type')} title={d.get('title','')[:30]}")
            elif ev == "tool_call" and d.get("tool") == "order_create":
                print(f"    轮{round_i+1} order_create 触发")

        if interactive:
            itype = interactive.get("type")
            if itype == "confirm":
                confirm_seen = True
                nxt = interactive.get("confirmValue", "确认")
                print(f"    轮{round_i+1} → 发送确认: {nxt}")
            elif itype == "form":
                nxt = "米白色 2.8米门幅"
                print(f"    轮{round_i+1} → 补规格: {nxt}")
            elif itype == "choice":
                nxt = interactive.get("options", [{}])[0].get("value", "确认")
                print(f"    轮{round_i+1} → 选择: {nxt}")
            else:
                break
        elif "验证码" in text:
            sms_seen = True
            nxt = SMS_BYPASS
            print(f"    轮{round_i+1} → 输入验证码: {nxt}")
        else:
            # 无交互组件，看文本是否含下单成功
            if "订单" in text or "成功" in text:
                print(f"    轮{round_i+1} 文本回复: {text[:80]}")
            break

        events, session_id = chat(nxt, session_id, token)
        order_create = find_tool_call(events, "order_create")

    # 结果汇总
    print("\n" + "=" * 60)
    print("结果汇总")
    print(f"  curtain_calc:  {'✅' if calc_args else '❌'}")
    print(f"  quotation 卡片: {'✅' if quote else '❌'} (total={quote.get('total') if quote else 'N/A'})")
    print(f"  confirm 确认:   {'✅' if confirm_seen else '❌'}")
    print(f"  SMS 验证:      {'✅' if sms_seen else '⚠️'}")
    print(f"  order_create:  {'✅' if order_create else '❌'}")
    if order_create:
        print(f"    下单参数: {json.dumps(order_create, ensure_ascii=False)[:250]}")
    ok = bool(calc_args and quote and order_create)
    print("=" * 60)
    print("✅ 下单闭环全部验证通过" if ok else "⚠️ 部分环节未通过（见上方）")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
