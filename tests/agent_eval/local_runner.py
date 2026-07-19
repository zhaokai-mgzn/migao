"""
Mibao Agent 本地评测 — 直接调 localhost chat API，采集 SSE 事件

用法:
  PRIMARY_API_KEY=sk-xxx python local_runner.py smoke     # 冒烟
  PRIMARY_API_KEY=sk-xxx python local_runner.py full      # 全量
  PRIMARY_API_KEY=sk-xxx python local_runner.py case P005 # 单条
"""

import sys, os, json, time, asyncio, re
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from eval_cases import ALL_CASES, get_smoke_cases, get_adversarial_cases, get_active_cases, Difficulty

# Config
ADMIN_API = os.environ.get("ADMIN_API_URL", "http://localhost:8080")
AI_API = os.environ.get("AI_API_URL", "http://localhost:8001")
PHONE = os.environ.get("TEST_PHONE", "13800138000")
BYPASS_CODE = os.environ.get("BYPASS_CODE", "123456")

import httpx

async def login() -> str:
    """获取测试 token"""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{ADMIN_API}/api/auth/sms/login",
                         json={"phone": PHONE, "code": BYPASS_CODE}, timeout=10)
        return r.json()["data"]["accessToken"]

async def get_or_create_session(token: str, prefer_new: bool = True) -> str:
    """获取或创建会话"""
    async with httpx.AsyncClient() as c:
        h = {"Authorization": f"Bearer {token}"}
        if prefer_new:
            r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
            return r.json()["data"]["id"]
        r = await c.get(f"{AI_API}/api/chat/sessions", headers=h, timeout=10)
        sessions = r.json().get("data", {}).get("items", [])
        if sessions:
            return sessions[0]["id"]
        r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
        return r.json()["data"]["id"]

async def send_message(token: str, session_id: str, message: str) -> dict:
    """发送消息并收集 SSE 事件"""
    async with httpx.AsyncClient(timeout=120) as c:
        h = {"Authorization": f"Bearer {token}"}

        result = {
            "user_message": message,
            "tool_calls": [],
            "tool_results": [],
            "final_text": "",
            "error": None,
            "streamed": False,
            "done": False,
        }

        current_event = None
        async with c.stream("POST", f"{AI_API}/api/chat/send",
                            headers=h,
                            json={"session_id": session_id, "message": message}) as resp:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue

                # SSE: event: <name>  or  data: <json>
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        payload = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if current_event == "text":
                        result["final_text"] += payload.get("content", "")
                        result["streamed"] = True
                    elif current_event == "tool_call":
                        tc = {
                            "name": payload.get("tool", ""),
                            "args": payload.get("args", {}),
                        }
                        result["tool_calls"].append(tc)
                    elif current_event == "tool_result":
                        result["tool_results"].append(payload)
                    elif current_event == "error":
                        result["error"] = str(payload)
                    elif current_event == "done":
                        result["done"] = True
                    current_event = None

        return result

def check_expectation(result: dict, expectation: str) -> tuple[bool, str]:
    """检查一条 expectation 是否满足"""
    exp_lower = expectation.lower()

    # 检查 tool 名称
    for tool_name in result.get("__all_tool_names", []):
        if tool_name in exp_lower:
            return True, f"tool '{tool_name}' matched"

    # 检查 success
    if "success=true" in exp_lower or "success=true" in exp_lower:
        if not result.get("error"):
            return True, "success=true (no error)"
        return False, f"expected success but got error: {result['error']}"

    # 检查 error code
    if "error.code=" in exp_lower or "error.code =" in exp_lower:
        expected_code = re.search(r'error\.code\s*=\s*(\w+)', exp_lower)
        if expected_code:
            actual_error = str(result.get("error", ""))
            if expected_code.group(1).lower() in actual_error.lower():
                return True, f"error code matched"
            return False, f"expected error {expected_code.group(1)} but got {actual_error}"

    # 检查 suggestion
    if "suggestion" in exp_lower:
        if result.get("error"):
            return True, "error returned (suggestion may be present)"
        return False, "expected error with suggestion but got success"

    # 兜底：检查 tool 调用
    if "未被调用" in expectation or "not called" in exp_lower:
        for tc in result["tool_calls"]:
            if tc["name"] in exp_lower:
                return False, f"tool {tc['name']} was called but should NOT be"
        return True, "tool not called as expected"

    return False, f"unmatched expectation: {expectation[:80]}"

async def run_case(case, token: str, session_id: str) -> dict:
    """运行单个评测用例（多轮对话）"""
    results = []
    all_tool_names = []

    for i, msg in enumerate(case.user_inputs):
        r = await send_message(token, session_id, msg)
        r["__round"] = i + 1
        r["__all_tool_names"] = [tc["name"] for tc in r["tool_calls"]]
        all_tool_names.extend(r["__all_tool_names"])
        results.append(r)

        # 简单等待，避免请求过快
        await asyncio.sleep(0.5)

    # 汇总所有轮的 tool 名称
    for r in results:
        r["__all_tool_names"] = all_tool_names

    # 检查 expectations
    passed_expectations = 0
    failed_expectations = []
    for exp in case.expectations:
        passed = False
        detail = ""
        # 在每一轮的结果中检查
        for r in results:
            ok, detail = check_expectation(r, exp)
            if ok:
                passed = True
                break
        if passed:
            passed_expectations += 1
        else:
            failed_expectations.append((exp, detail))

    total_exp = len(case.expectations)
    score = passed_expectations / total_exp if total_exp > 0 else 1.0

    return {
        "case_id": case.id,
        "title": case.title,
        "difficulty": case.difficulty.value,
        "tags": case.tags,
        "rounds": len(results),
        "tool_calls": all_tool_names,
        "passed": passed_expectations,
        "total": total_exp,
        "score": score,
        "failed": failed_expectations,
        "last_error": results[-1].get("error") if results else None,
        "final_text": results[-1].get("final_text", "")[:200] if results else "",
    }

async def run_suite(cases, label: str):
    """运行一组用例"""
    print(f"\n{'='*60}")
    print(f"  {label}: {len(cases)} 个用例")
    print(f"{'='*60}")

    try:
        token = await login()
        print(f"✅ 登录成功")
    except Exception as e:
        print(f"❌ 登录失败: {e}")
        return []

    results = []
    passed_count = 0
    total_score = 0.0

    for i, case in enumerate(cases):
        if case.skip_reason:
            continue

        # 每个用例用独立 session，避免前序用例污染上下文
        session_id = await get_or_create_session(token, prefer_new=True)

        icon = {Difficulty.SMOKE: "🟢", Difficulty.NORMAL: "🔵",
                Difficulty.EDGE: "🟡", Difficulty.ADVERSARIAL: "🔴"}.get(case.difficulty, "⚪")

        try:
            r = await run_case(case, token, session_id)
            results.append(r)
            total_score += r["score"]
            if r["score"] >= 1.0:
                passed_count += 1

            status = "✅" if r["score"] >= 1.0 else "⚠️" if r["score"] >= 0.5 else "❌"
            print(f"  {icon} {status} {case.id}: {case.title[:50]}")
            print(f"     rounds={r['rounds']} tools={r['tool_calls']} score={r['score']:.0%}")
            if r["failed"]:
                for exp, detail in r["failed"][:2]:
                    print(f"     ❌ {exp[:80]}")
                    print(f"        → {detail[:120]}")
            if r["last_error"]:
                print(f"     ⚠️  last_error: {str(r['last_error'])[:100]}")
        except Exception as e:
            print(f"  {icon} ❌ {case.id}: EXCEPTION: {e}")

        await asyncio.sleep(1)  # rate limit

    # Summary
    n = len(results)
    avg_score = total_score / n if n > 0 else 0
    print(f"\n{'='*60}")
    print(f"  {label} 结果: {passed_count}/{n} 通过, 均分 {avg_score:.0%}")
    print(f"{'='*60}")

    return results

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["smoke", "full", "adversarial", "case"], nargs="?", default="smoke")
    parser.add_argument("--case-id", help="单条用例 ID")
    args = parser.parse_args()

    if args.suite == "case":
        case = next((c for c in ALL_CASES if c.id == args.case_id), None)
        if not case:
            print(f"用例 {args.case_id} 不存在")
            return
        await run_suite([case], f"单条 {args.case_id}")
    elif args.suite == "smoke":
        await run_suite(get_smoke_cases(), "冒烟")
    elif args.suite == "adversarial":
        await run_suite(get_adversarial_cases(), "对抗")
    elif args.suite == "full":
        await run_suite(get_active_cases(), "全量")

if __name__ == "__main__":
    asyncio.run(main())
