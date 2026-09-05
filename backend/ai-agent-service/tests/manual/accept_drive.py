"""真实链路验收驱动器 — 复现线上 sess_806703a2dcca4059 崩溃场景

场景（X-Debug-Role: customer → 小布）：
  T1: 模糊文本 "帮我看看"          → 期望触发澄清卡/交互 → 写入 pending_interact_skill
  T2: 带图消息 "就是这种" + 图片    → 修复前崩溃（AttributeError list.strip）；修复后正常 vision 链路

用法: python accept_drive.py <base_url> [--expect-error]
退出码: 0 = 无 error 事件（预期 GREEN）；1 = T2 出现 error（预期 RED 时的信号）;
       2 = 场景未按预期走（T1 未产生 interact 卡等）
"""
import asyncio, json, sys, httpx

BASE = sys.argv[1].rstrip("/")
EXPECT_ERROR = "--expect-error" in sys.argv
H = {"X-Debug-Role": "customer", "Content-Type": "application/json"}
IMG = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "https://picsum.photos/seed/curtain-fabric/800/600"


async def send(client, session_id, message, images=None, timeout=150):
    body = {"session_id": session_id, "message": message}
    if images:
        body["images"] = images
    events = {"text": "", "tool_calls": [], "errors": [], "done": False}
    try:
        async with client.stream("POST", f"{BASE}/api/chat/send", headers=H, json=body, timeout=timeout) as resp:
            if resp.status_code != 200:
                return {"http": resp.status_code}, await resp.aread()
            current = None
            async for line in resp.aiter_lines():
                line = line.strip()
                if line.startswith("event:"):
                    current = line[6:].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        p = json.loads(payload)
                    except Exception:
                        continue
                    if current == "text":
                        events["text"] += p.get("content", "")
                    elif current == "tool_call":
                        events["tool_calls"].append({"tool": p.get("tool", ""), "args": str(p.get("tool_input", ""))[:120]})
                    elif current == "error":
                        events["errors"].append(str(p))
                    elif current == "tool_result":
                        events["tool_results"] = events.get("tool_results", []) + [str(p)[:150]]
                    current = None
    except Exception as e:
        events["errors"].append(f"transport {type(e).__name__}: {e}")
    return events, None


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{BASE}/api/chat/sessions", headers=H, json={})
        sid = r.json()["data"]["id"]
        print(f"session={sid}")

        print("\n── T1: 帮我看看 ──")
        e1, _ = await send(c, sid, "帮我看看")
        print(f"  text={e1['text'][:120]!r}")
        print(f"  tools={[t['tool'] for t in e1['tool_calls']]}")
        if e1["errors"]:
            print(f"  ERRORS={e1['errors'][:2]}")
        t1_has_interact = any(t["tool"] == "interact" for t in e1["tool_calls"])

        print("\n── T2: 就是这种 + 图片 ──")
        e2, raw = await send(c, sid, "就是这种", [IMG])
        print(f"  text={e2['text'][:160]!r}")
        print(f"  tools={[t['tool'] for t in e2['tool_calls']]}")
        if e2["errors"]:
            for er in e2["errors"][:3]:
                print(f"  ERROR: {er[:300]}")
        else:
            print("  no-error ✓")

        crashed = bool(e2["errors"])
        print("\n── 判定 ──")
        print(f"  T1 interact 卡（pending_skill 写入前提）: {t1_has_interact}")
        print(f"  T2 出现 error 事件: {crashed}")
        if EXPECT_ERROR:
            ok = crashed
        else:
            ok = (not crashed) and e2["text"].strip()
        print(f"  结果: {'RED✓（复现线上崩溃）' if crashed else 'GREEN✓（无报错）'}")
        sys.exit(0 if ok else (1 if crashed else 2))


if __name__ == "__main__":
    asyncio.run(main())