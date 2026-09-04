"""
真实环境验收 runner（issue #2801 澄清能力真实验收）

与 agent-eval local_runner 的区别：
- 捕获完整 SSE 事件：text / tool_call / tool_result / interactive（choice/confirm/form
  澄清卡！）/ error / done —— 验收必须看到澄清卡是否弹出
- 真实登录：mibao 用线上万能码登录；xiaobu 用 X-Debug-Role: customer
- 支持每轮 text + images（真实图片 URL）
- 输出结构化验收记录（每轮：用户输入 → AI 文本 / 工具 / 澄清卡）

用法（打线上真实端点）：
    PERSONA=mibao python3 tests/agent_eval/acceptance_runner.py <场景json>
    PERSONA=xiaobu python3 tests/agent_eval/acceptance_runner.py <场景json>

场景 JSON 格式：
    {"id": "C-01", "title": "纯图找同款", "domain": "product",
     "rounds": [{"text": "", "images": ["https://..."]}, {"text": "确认", "images": []}]}
"""
import asyncio
import json
import os
import sys

import httpx

AI_API = os.environ.get("AI_API_URL", "https://ai-api.migaozn.com")
ADMIN_API = os.environ.get("ADMIN_API_URL", "https://api.migaozn.com")
PHONE = os.environ.get("TEST_PHONE", "13800138000")
BYPASS_CODE = os.environ.get("TEST_CODE", "123456")
PERSONA = os.environ.get("PERSONA", "mibao").strip().lower()


async def login() -> str:
    """mibao：真实登录拿 token；xiaobu：空字符串走 X-Debug-Role"""
    if PERSONA == "xiaobu":
        return ""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{ADMIN_API}/api/auth/sms/login",
                         json={"phone": PHONE, "code": BYPASS_CODE}, timeout=15)
        return r.json()["data"]["accessToken"]


def _headers(token: str) -> dict:
    if PERSONA == "xiaobu":
        return {"X-Debug-Role": "customer"}
    return {"Authorization": f"Bearer {token}"}


async def send(session_id: str, token: str, text: str, images=None) -> dict:
    """发送一轮消息，捕获完整事件"""
    body = {"session_id": session_id, "message": text}
    if images:
        body["images"] = images
    result = {
        "text": "", "tool_calls": [], "tool_results": [],
        "interactive": [], "cards": [], "error": None, "done": False,
    }
    async with httpx.AsyncClient(timeout=120) as c:
        async with c.stream("POST", f"{AI_API}/api/chat/send",
                            headers=_headers(token), json=body) as resp:
            current = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    current = line[6:].strip()
                elif line.startswith("data:"):
                    ds = line[5:].strip()
                    if ds == "[DONE]":
                        break
                    try:
                        p = json.loads(ds)
                    except json.JSONDecodeError:
                        continue
                    if current == "text":
                        result["text"] += p.get("content", "")
                    elif current == "tool_call":
                        result["tool_calls"].append({"name": p.get("tool", ""), "args": p.get("args", {})})
                    elif current == "tool_result":
                        result["tool_results"].append(p)
                    elif current == "interactive":
                        result["interactive"].append(p)
                    elif current == "card":
                        result["cards"].append(p)
                    elif current == "error":
                        result["error"] = str(p)
                    elif current == "done":
                        result["done"] = True
                    current = None
    return result


def _fmt_tool(t: dict) -> str:
    args = t.get("args") or {}
    return f"  🔧 {t['name']}({json.dumps(args, ensure_ascii=False)[:200]})"


def _fmt_interactive(i: dict) -> str:
    comp = i.get("component") or i.get("type")
    title = i.get("title", "")
    opts = i.get("options")
    if opts:
        labels = [o.get("label", "") for o in opts][:6]
        return f"  🃏 [澄清卡 choice] {title} → {' | '.join(labels)}"
    fields = i.get("fields")
    if fields:
        return f"  🃏 [确认卡 confirm] {title} → {json.dumps(fields, ensure_ascii=False)[:200]}"
    return f"  🃏 [{comp}] {title}"


async def run_scenario(sc: dict, token: str) -> dict:
    """跑一个场景（多轮），返回完整记录"""
    # 新建会话（线上偶发失败重试 2 次）
    session_id = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient() as c:
                r = await c.post(f"{AI_API}/api/chat/sessions",
                                 headers=_headers(token), json={}, timeout=15)
                session_id = r.json()["data"]["id"]
            if session_id:
                break
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(1.0)

    rounds = []
    for i, rd in enumerate(sc.get("rounds", [])):
        text = rd.get("text", "")
        images = rd.get("images") or []
        res = await send(session_id, token, text, images)
        rounds.append({
            "round": i + 1,
            "user_text": text,
            "user_images": len(images),
            "ai_text": res["text"],
            "tools": res["tool_calls"],
            "interactive": res["interactive"],
            "error": res["error"],
        })
        await asyncio.sleep(0.6)

    return {"id": sc["id"], "title": sc["title"], "domain": sc.get("domain", ""),
            "rounds": rounds}


def render(scenario_result: dict) -> str:
    """渲染成可读验收记录（供人工评估）"""
    lines = []
    lines.append(f"## {scenario_result['id']} [{scenario_result['domain']}] {scenario_result['title']}")
    for rd in scenario_result["rounds"]:
        img = f" [📷x{rd['user_images']}]" if rd["user_images"] else ""
        lines.append(f"\n**R{rd['round']} 用户**: {rd['user_text'] or '(纯图片)'}{img}")
        for i in rd["interactive"]:
            lines.append(_fmt_interactive(i))
        for t in rd["tools"]:
            lines.append(_fmt_tool(t))
        if rd["ai_text"]:
            lines.append(f"  💬 {rd['ai_text'][:300]}")
        if rd["error"]:
            lines.append(f"  ⚠️ error: {rd['error'][:150]}")
    return "\n".join(lines)


async def main():
    if len(sys.argv) < 2:
        print("用法: PERSONA=mibao|xiaobu python3 acceptance_runner.py <场景json>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        scenarios = json.load(f)
    token = await login()
    print(f"PERSONA={PERSONA} | token={'真实登录' if token else 'X-Debug-Role'}")
    for sc in scenarios:
        print("\n" + "=" * 70)
        result = await run_scenario(sc, token)
        print(render(result))
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
