"""ReAct Smartness Test — 6 scenarios, 35 turns"""
import json, os, subprocess, sys, time
from dataclasses import dataclass, field
from typing import Optional

AI_AGENT_URL = os.getenv("AI_AGENT_URL", "https://ai-api.migaozn.com")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", os.getenv("SMOKE_SERVICE_TOKEN", ""))

if not SERVICE_TOKEN:
    print("SERVICE_TOKEN not set"); exit(1)

_TOKEN_HDR = "/tmp/smoke_hdr"
with open(os.open(_TOKEN_HDR, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
    f.write(f"X-Service-Token: {SERVICE_TOKEN}")

@dataclass
class TurnResult:
    turn: int = 0; message: str = ""
    tool_calls: list = field(default_factory=list)
    final_text: str = ""; latency_ms: float = 0; error: Optional[str] = None

@dataclass
class ScenarioResult:
    name: str; turns: list = field(default_factory=list)
    notes: list = field(default_factory=list)

def _post(path, body=None):
    cmd = ["curl", "-s", "--max-time", "120", "-X", "POST", f"{AI_AGENT_URL}{path}",
           "-H", f"@{_TOKEN_HDR}", "-H", "Content-Type: application/json"]
    if body: cmd += ["-d", json.dumps(body, ensure_ascii=False)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return json.loads(r.stdout)

def create_session():
    d = _post("/api/chat/sessions", {"client_type": "web"})
    sid = d.get("data", {}).get("id", "") or d.get("data", {}).get("session_id", "")
    if not sid: raise RuntimeError(f"No session id in: {json.dumps(d)[:200]}")
    return sid

def send_message(sid, msg):
    t0 = time.time(); r = TurnResult(message=msg)
    try:
        body = json.dumps({"session_id": sid, "message": msg}, ensure_ascii=False)
        raw = subprocess.run(
            ["curl", "-s", "-N", "--max-time", "120", "-X", "POST",
             f"{AI_AGENT_URL}/api/chat/send",
             "-H", f"@{_TOKEN_HDR}", "-H", "Content-Type: application/json", "-d", body],
            capture_output=True, timeout=120).stdout.decode("utf-8", errors="replace")

        ev = None
        for line in raw.split("\n"):
            s = line.strip()
            if s.startswith("event: "): ev = s[7:]
            elif s.startswith("data: ") and ev:
                try: d = json.loads(s[6:])
                except: continue
                if ev == "tool_call":
                    r.tool_calls.append({"tool": d.get("tool", d.get("name","")), "args": d.get("args", d.get("input",{}))})
                elif ev in ("text", "loading"):
                    r.final_text += d.get("content","")
    except Exception as e:
        r.error = f"{type(e).__name__}: {str(e)[:100]}"
    r.latency_ms = (time.time() - t0) * 1000
    return r

SCENARIOS = {
    "S1-DeepChain": [
        "上周五来的那个新客户，买遮光窗帘那个，她的订单到哪了？",
        "哦不对，她好像还没下单，只是在咨询阶段。那她问了哪些产品？",
        "这些产品里哪些有现货？按价格从低到高排",
        "如果她要最便宜的那款，3米宽2.7米高，带打孔加工，一共多少钱？",
        "算了先别报价，你帮我看看她有没有在其他渠道留过联系方式",
        "有的话，用手机号查一下是不是老客户，之前在别的店买过没有",
    ],
    "S2-Parallel": [
        "帮我把待付款超过3天的、待发货的、还有最近7天已完成的订单都列出来",
        "待发货的只看包含窗帘的，已完成的统计总额和平均客单价",
        "如果有客户同时出现在待付款和待发货里，列出手机号和订单号",
    ],
    "S3-Fuzzy": [
        "最近有没有那种感觉不太对的订单？",
        "就是金额特别大或者特别小的，跟平时不太一样的",
        "还有那种同一个客户短时间内下了好几单的",
        "把符合这几种情况的订单都找出来，看看是否需要人工关注",
    ],
    "S4-WriteRollback": [
        "创建一款新产品：高端雪尼尔窗帘布，价格168元/米，颜色有米白、深灰、藏青三种",
        "不对，价格改成158吧，藏青去掉换成墨绿",
        "确认创建",
        "创建完后发现墨绿色号写错了，应该是BG-8802而不是GN-7701，帮我改一下",
        "刚才创建的产品，确认一下最终的规格和价格是否正确",
    ],
    "S5-ContextPollution": [
        "张三买过遮光窗帘吗？",
        "李四呢？",
        "王五的订单号是什么来着？",
        "刚才说的三个人，谁买的最多？",
        "最多的那个人，把他买过的所有产品列出来",
    ],
    "S6-Contradiction": [
        "把所有待发货订单的状态改成已发货",
        "等等，我搞错了，应该只改包含窗帘的待发货订单",
        "不对不对，先别改！帮我确认一下待发货的一共有多少单",
        "算了，根本不需要改状态，帮我看看这些订单的物流单号是不是都填了",
        "没填物流单号的，列出订单号和客户手机号",
    ],
}

def main():
    print(f"=== ReAct Smartness Test ({len(SCENARIOS)} scenarios, {sum(len(v) for v in SCENARIOS.values())} turns)")
    results = {}
    for name, msgs in SCENARIOS.items():
        r = ScenarioResult(name=name)
        try:
            sid = create_session()
            print(f"\n[TEST] {name}")
            for i, msg in enumerate(msgs, 1):
                turn = send_message(sid, msg); turn.turn = i; r.turns.append(turn)
                tools = ", ".join(f"{t['tool']}({json.dumps(t['args'],ensure_ascii=False)[:60]})" for t in turn.tool_calls) if turn.tool_calls else "none"
                txt = turn.final_text[:150].replace("\n"," ") if turn.final_text else "(no text)"
                print(f"  T{i}: {tools} | {txt}... | {turn.latency_ms:.0f}ms" + (f" ERR:{turn.error}" if turn.error else ""))
        except Exception as e:
            r.notes.append(str(e)); print(f"  FAIL: {e}")
        results[name] = r

    tt = sum(len(r.turns) for r in results.values())
    tc = sum(sum(len(t.tool_calls) for t in r.turns) for r in results.values())
    tl = sum(sum(t.latency_ms for t in r.turns) for r in results.values())
    errs = sum(1 for r in results.values() for t in r.turns if t.error)
    print(f"\n=== Summary: {tt} turns, {tc} tool calls, avg {tl/tt:.0f}ms/turn, {errs} errors" if tt > 0 else "\nAll failed")
    if tt > 0:
        print(f"Tool density: {tc/tt:.1f}/turn | Error rate: {errs}/{tt}={errs/tt*100:.1f}%")

if __name__ == "__main__":
    main()
