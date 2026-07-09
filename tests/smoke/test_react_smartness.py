"""
ReAct 聪明度多轮对话测试

6 组高压场景，测试 LLM 在纯 ReAct 循环下的表现：
1. 隐含约束深链推理  2. 多实体并行追踪  3. 模糊约束+常识推理
4. 写操作+失败回滚   5. 上下文污染对抗  6. 矛盾处理+止损
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# Force UTF-8 everywhere - CI runners often default to ASCII
sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

AI_AGENT_URL = os.getenv("AI_AGENT_URL", "https://ai-api.migaozn.com")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", os.getenv("SMOKE_SERVICE_TOKEN", ""))

if not SERVICE_TOKEN:
    print("[WARN]  SERVICE_TOKEN not set")
    print("   Set SMOKE_SERVICE_TOKEN env var and re-run")
    exit(1)

# GitHub Secrets may contain non-ASCII chars — encode to Latin-1 for HTTP headers
try:
    SERVICE_TOKEN.encode("ascii")
except UnicodeEncodeError:
    print(f"[WARN] SERVICE_TOKEN has non-ASCII chars (len={len(SERVICE_TOKEN)}), using Latin-1")
    # httpx headers need Latin-1 compatible strings
    SERVICE_TOKEN = SERVICE_TOKEN.encode("utf-8").decode("latin-1", errors="replace")

@dataclass
class TurnResult:
    turn: int
    message: str
    tool_calls: list = field(default_factory=list)
    final_text: str = ""
    sse_events: list = field(default_factory=list)
    latency_ms: float = 0
    error: Optional[str] = None

@dataclass
class ScenarioResult:
    name: str
    turns: list = field(default_factory=list)
    passed: bool = False
    notes: list = field(default_factory=list)

# Write token to file to avoid shell encoding issues (mode 0o600 for security)
import stat
_TOKEN_HEADER_FILE = "/tmp/smoke_token_header"
with open(os.open(_TOKEN_HEADER_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
    f.write(f"X-Service-Token: {SERVICE_TOKEN}")

def _curl(method: str, path: str, body: dict = None) -> dict:
    url = f"{AI_AGENT_URL}{path}"
    cmd = ["curl", "-s", "--connect-timeout", "10", "--max-time", "120",
           "-X", method, url,
           "-H", f"@/tmp/smoke_token_header",
           "-H", "Content-Type: application/json; charset=utf-8"]
    # Write header file each time (curl doesn't support -H with @ inline)
    with open("/tmp/smoke_token_header", "w", encoding="utf-8") as f:
        f.write(f"X-Service-Token: {SERVICE_TOKEN}")
    if body:
        cmd += ["-d", json.dumps(body, ensure_ascii=False)]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    raw = result.stdout
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"curl failed: exit={result.returncode} stderr={result.stderr[:200]} raw={raw[:200]}")

def create_session() -> str:
    data = _curl("POST", "/api/chat/sessions", {"client_type": "web"})
    if not data.get("success"):
        raise RuntimeError(f"Session failed: {json.dumps(data, ensure_ascii=True)[:200]}")
    # Handle both response envelope formats
    session_data = data.get("data", data)
    sid = session_data.get("id", session_data.get("session_id", ""))
    if not sid:
        raise RuntimeError(f"No session_id in response: {json.dumps(data, ensure_ascii=True)[:200]}")
    return sid

def send_message(session_id: str, message: str) -> TurnResult:
    start = time.time()
    result = TurnResult(turn=0, message=message)
    try:
        url = f"{AI_AGENT_URL}/api/chat/messages"
        body = json.dumps({"session_id": session_id, "message": message}, ensure_ascii=False)
        proc = subprocess.Popen(
            ["curl", "-s", "-N", "--connect-timeout", "10", "--max-time", "120",
             "-X", "POST", url,
             "-H", "@/tmp/smoke_token_header",
             "-H", "Content-Type: application/json; charset=utf-8",
             "-d", body],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        current_event = None
        buffer = b""
        while True:
            chunk = proc.stdout.read(1)
            if not chunk:
                break
            buffer += chunk
            if chunk == b"\n":
                line = buffer.decode("utf-8", errors="replace").strip()
                buffer = b""
                if line.startswith("event: "):
                    current_event = line[7:]
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    result.sse_events.append({"event": current_event, "data": data})
                    # Debug: log all non-text event types
                    if current_event == "message":
                        msg_type = data.get("type", "")
                        if msg_type not in ("text", ""):
                            print(f"        [SSE] event={current_event} type={msg_type} keys={list(data.keys())}")
                        if msg_type == "tool_call":
                            result.tool_calls.append({"tool": data.get("tool", ""), "args": data.get("args", {})})
                        elif msg_type == "text":
                            result.final_text += data.get("content", "")
                    elif current_event and current_event != "done":
                        print(f"        [SSE] non-message event: {current_event}")
        proc.wait(timeout=120)
    except Exception as e:
        result.error = f"{type(e).__name__}: {str(e)[:100]}"
    result.latency_ms = (time.time() - start) * 1000
    return result

def run_scenario(name: str, messages: list[str]) -> ScenarioResult:
    """运行一组多轮对话场景"""
    result = ScenarioResult(name=name)
    try:
        sid = create_session()
        print(f"\n{'='*60}")
        print(f"[TEST] {name}")
        print(f"{'='*60}")

        for i, msg in enumerate(messages, 1):
            print(f"\n[Turn {i}] >> {msg}")
            turn = send_message(sid, msg)
            turn.turn = i
            result.turns.append(turn)

            tools_str = ", ".join(
                f"{tc['tool']}({json.dumps(tc['args'], ensure_ascii=False)[:80]})"
                for tc in turn.tool_calls
            ) if turn.tool_calls else "none"
            print(f"        [TOOLS] {tools_str}")

            if turn.final_text:
                preview = turn.final_text[:200].replace("\n", " ")
                print(f"        [TEXT] {preview}...")

            if turn.error:
                print(f"        [FAIL] {turn.error}")
                result.notes.append(f"Turn {i} error: {turn.error}")

            print(f"        [LAT]  {turn.latency_ms:.0f}ms")
    except Exception as e:
        result.notes.append(f"Scenario error: {e}")
        print(f"   [FAIL] Scenario failed: {e}")

    return result

# ─── 6 组测试场景 ───

SCENARIOS = {
    # TEMP: just test one scenario for debugging
}
    "场景1-深链推理": [
        "上周五来的那个新客户，买遮光窗帘那个，她的订单到哪了？",
        "哦不对，她好像还没下单，只是在咨询阶段。那她问了哪些产品？",
        "这些产品里哪些有现货？按价格从低到高排",
        "如果她要最便宜的那款，3米宽2.7米高，带打孔加工，一共多少钱？",
        "算了先别报价，你帮我看看她有没有在其他渠道留过联系方式",
        "有的话，用手机号查一下是不是老客户，之前在别的店买过没有",
    ],
    "场景2-多实体并行": [
        "帮我把待付款超过3天的、待发货的、还有最近7天已完成的订单都列出来",
        "待付款的那些按金额从高到低排只保留前5个；待发货的只看包含窗帘的；已完成的统计总额和平均客单价",
        "对比一下这三个维度的数据：哪个状态的订单金额占比最高？有没有明显的异常？",
        "如果有客户同时出现在待付款和待发货里，帮我把这些客户的手机号和订单号对照列出来",
    ],
    "场景3-模糊约束": [
        "最近有没有那种感觉不太对的订单？",
        "就是金额特别大或者特别小的，跟平时不太一样的",
        "对，还有那种同一个客户短时间内下了好几单的",
        "把符合这几种情况的订单都找出来，帮我标记一下哪些需要人工关注",
        "不用标记了，刚才那个金额异常的客户，看看他历史订单和售后记录，判断是不是恶意下单",
    ],
    "场景4-写操作回滚": [
        "创建一款新产品：高端雪尼尔窗帘布，价格168元/米，颜色有米白、深灰、藏青三种",
        "不对，价格改成158吧，藏青去掉换成墨绿",
        "确认创建",
        "创建完后发现墨绿色号写错了，应该是BG-8802而不是GN-7701，帮我改一下",
        "再给这款产品加个促销标签新品上市9折，然后帮我看看还有哪些产品也在促销",
        "算了，这个产品暂时不下架但是先不促销了，把标签去掉",
        "刚才创建的产品，确认一下最终的规格和价格是否正确",
    ],
    "场景5-上下文污染": [
        "张三买过遮光窗帘吗？",
        "李四呢？",
        "王五的订单号是什么来着？",
        "刚才说的三个人，谁买的最多？",
        "最多的那个人，把他买过的所有产品列出来，顺便推荐几个他没买过但可能有兴趣的",
        "别推荐了，我需要知道这三个人里有没有人之前退过货，退货原因是什么",
        "有退货的那个人，把退款金额、退货时间、处理结果都告诉我",
    ],
    "场景6-矛盾止损": [
        "把所有待发货订单的状态改成已发货",
        "等等，我搞错了，应该只改包含窗帘的待发货订单",
        "不对不对，先别改！帮我确认一下待发货的一共有多少单",
        "嗯...还是太多了。能不能只改最近3天下单的、金额超过500的？",
        "算了，根本不需要改状态。帮我看看这些订单的物流单号是不是都填了",
        "没填物流单号的，列出订单号和客户手机号，我一个个联系",
    ],
}

def main():
    print("=== ReAct Smartness Test")
    print(f"   Target: {AI_AGENT_URL}")
    print(f"   Scenarios: {len(SCENARIOS)}")
    print(f"   Total turns: {sum(len(v) for v in SCENARIOS.values())}")

    results = {}
    for name, messages in SCENARIOS.items():
        results[name] = run_scenario(name, messages)

    # ─── 汇总报告 ───
    print(f"\n\n{'='*60}")
    print("=== Test Summary")
    print(f"{'='*60}")

    total_turns = 0
    total_tools = 0
    total_latency = 0
    errors = 0

    for name, r in results.items():
        turns = len(r.turns)
        tools = sum(len(t.tool_calls) for t in r.turns)
        latency = sum(t.latency_ms for t in r.turns)
        errs = sum(1 for t in r.turns if t.error)

        total_turns += turns
        total_tools += tools
        total_latency += latency
        errors += errs

        avg_lat = f"{latency/turns:.0f}" if turns > 0 else "N/A"
        status = "[PASS]" if errs == 0 and turns > 0 else "[WARN]"
        print(f"\n{status} {name}: {turns}轮 {tools}次tool调用 均{avg_lat}ms/轮" + (f" {errs}错误" if errs else ""))

        if r.notes:
            for note in r.notes:
                print(f"   [TEXT] {note}")

    print(f"\n{'─'*60}")
    if total_turns > 0:
        print(f"Total: {total_turns} turns, {total_tools} tool calls, avg {total_latency/total_turns:.0f}ms/turn, {errors} errors")
        tools_per_turn = total_tools / total_turns
        print(f"\n[SCORE] Smartness Metrics:")
        print(f"   Tool call density: {tools_per_turn:.1f}/turn")
        print(f"   Avg latency: {total_latency/total_turns:.0f}ms/turn")
        print(f"   Error rate: {errors}/{total_turns} = {errors/total_turns*100:.1f}%")
    else:
        print(f"Total: 0 turns (all scenarios failed)")

if __name__ == "__main__":
    main()

SCENARIOS = {
    "场景2-多实体并行": [
        "帮我把待付款超过3天的、待发货的、还有最近7天已完成的订单都列出来",
        "待发货的只看包含窗帘的",
    ],
}
