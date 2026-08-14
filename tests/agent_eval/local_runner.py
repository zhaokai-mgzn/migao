"""
Mibao Agent 本地评测 — 直接调 localhost chat API，采集 SSE 事件

用法:
  PRIMARY_API_KEY=sk-xxx python local_runner.py smoke     # 冒烟
  PRIMARY_API_KEY=sk-xxx python local_runner.py full      # 全量
  PRIMARY_API_KEY=sk-xxx python local_runner.py case P005 # 单条
"""

import sys, os, json, time, asyncio, re
from pathlib import Path
from pathlib import Path

# CI stdout 可能默认 ascii 编码，强制 UTF-8（防中文/emoji 触发 UnicodeEncodeError）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

sys.path.insert(0, os.path.dirname(__file__))
from eval_cases import ALL_CASES, EvalCase, Skill, Difficulty

# Config
ADMIN_API = os.environ.get("ADMIN_API_URL", "http://localhost:8080")
AI_API = os.environ.get("AI_API_URL", "http://localhost:8001")
PHONE = os.environ.get("TEST_PHONE", "13800138000")
BYPASS_CODE = os.environ.get("BYPASS_CODE", "123456")
# CI 模式：SERVICE_TOKEN 存在时，chat/send 无 auth（DEBUG 默认用户），admin-api 用 X-Service-Token
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "")


def _validate_service_token(token: str) -> str | None:
    """校验 SERVICE_TOKEN 是否纯 ASCII（HTTP header 值必须是 ASCII）。

    返回 None 表示合法；否则返回人类可读的错误说明。
    """
    if not token:
        return None
    try:
        token.encode("ascii")
        return None
    except UnicodeEncodeError:
        bad = "".join(c for c in token if ord(c) > 127)
        return (
            f"SERVICE_TOKEN 含非 ASCII 字符（{bad[:10]}），HTTP 请求头必须纯 ASCII。"
            "请检查 GitHub Secrets 的 SMOKE_SERVICE_TOKEN 值：去掉中文/空格/换行，或换成有效的服务 token。"
        )


_token_err = _validate_service_token(SERVICE_TOKEN)
if _token_err:
    print(f"❌ {_token_err}", file=sys.stderr)
    sys.exit(1)

ADMIN_HEADERS = {"X-Service-Token": SERVICE_TOKEN, "X-Tenant-Id": "1"} if SERVICE_TOKEN else {}


def _admin_headers(token: str) -> dict:
    """admin-api 认证 header：CI 模式用 X-Service-Token，本地用 Bearer"""
    return ADMIN_HEADERS if SERVICE_TOKEN else ({"Authorization": f"Bearer {token}"} if token else {})

import httpx

# ── 数据隔离：保存/恢复商品状态 ──

_saved_states: dict = {}  # {product_id: {"price": ...}}


async def snapshot_product(token: str, product_keyword: str) -> str | None:
    """保存商品当前状态，返回 product_id"""
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                        params={"keyword": product_keyword, "page": 1, "size": 1})
        items = r.json().get("data", {}).get("items", [])
        if not items:
            return None
        p = items[0]
        pid = p["id"]
        price = p.get("price") or p.get("basePrice")
        _saved_states[pid] = {"price": price, "name": p.get("name", "")}
        return pid


async def restore_product(token: str, product_id: str):
    """恢复商品到保存的状态"""
    if product_id not in _saved_states:
        return
    saved = _saved_states[product_id]
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        price = saved.get("price")
        if price is not None:
            await c.patch(f"{ADMIN_API}/api/admin/agent/products/{product_id}",
                         headers=h, json={"price": price})


# ── Auth ──

async def login() -> str:
    """获取测试 token（CI 模式直接返回空字符串，走 SERVICE_TOKEN 无 auth）"""
    if SERVICE_TOKEN:
        return ""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{ADMIN_API}/api/auth/sms/login",
                         json={"phone": PHONE, "code": BYPASS_CODE}, timeout=10)
        return r.json()["data"]["accessToken"]

async def get_or_create_session(token: str, prefer_new: bool = True) -> str:
    """获取或创建会话"""
    async with httpx.AsyncClient() as c:
        h = {"Authorization": f"Bearer {token}"} if token else {}
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
        h = {"Authorization": f"Bearer {token}"} if token else {}

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

    # 检查 direct_reply（路由动作：直接回复、未调工具且有文本输出）
    if "direct_reply" in exp_lower:
        if not result.get("tool_calls") and result.get("final_text"):
            return True, "direct reply without tool call"
        return False, "expected direct_reply (no tool) but got tool calls"

    # 检查 tool 名称（支持 OR 逻辑：A or B）
    or_parts = [p.strip() for p in exp_lower.split(" or ")]
    for tool_name in result.get("__all_tool_names", []):
        for part in or_parts:
            if tool_name in part:
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

        # 数据隔离：修改类用例前后保存/恢复状态
        snapshot_pid = None
        if any(t in case.tags for t in ["id_reuse", "update", "full_lifecycle"]):
            snapshot_pid = await snapshot_product(token, "遮光窗帘") or await snapshot_product(token, "2699")

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
        finally:
            if snapshot_pid:
                await restore_product(token, snapshot_pid)

        await asyncio.sleep(1)  # rate limit

    # Summary
    n = len(results)
    avg_score = total_score / n if n > 0 else 0
    print(f"\n{'='*60}")
    print(f"  {label} 结果: {passed_count}/{n} 通过, 均分 {avg_score:.0%}")
    print(f"{'='*60}")

    return results


def load_cases_from_yaml(cases_dir: str) -> list:
    """从 cases/*.yml 加载用例（case-contract 单一源，替代 eval_cases.py 手写清单）。

    cases_dir 相对仓根（CI 形态: .github/cases）；yaml_light + render_cases 在 .github/ 下。
    """
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / ".github"))
    from render_cases import exp_to_str, load_case_dicts

    cases = []
    for c in load_case_dicts(cases_dir):
        cases.append(EvalCase(
            id=c.get("id", ""),
            legacy_id=c.get("legacy_id", ""),
            title=c.get("title", ""),
            skill=Skill.GENERAL,  # 域信息由 _domain 携带，runner 不消费 skill
            difficulty=Difficulty(c.get("tier", "normal")),
            user_inputs=c.get("user_inputs") or [],
            expectations=[exp_to_str(e) for e in (c.get("expectations") or [])],
            data_checks=c.get("data_checks") or [],
            skip_reason=c.get("skip_reason", ""),
            tags=c.get("tags") or [],
        ))
    return cases


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["smoke", "full", "adversarial", "case"], nargs="?", default="smoke")
    parser.add_argument("--case-id", help="单条用例 ID（支持新 ID 与 legacy_id，如 OR-002 或 O002）")
    parser.add_argument("--cases", help="用例库目录（cases/*.yml）——提供时直接读 YAML（单一源）")
    args = parser.parse_args()

    if args.cases:
        cases = load_cases_from_yaml(args.cases)
        print(f"📚 用例源: {args.cases}（{len(cases)} 条，YAML 单一源）")
    else:
        cases = ALL_CASES
        print(f"📚 用例源: eval_cases.py（生成物，{len(cases)} 条）")

    def smoke_cases():
        return [c for c in cases if c.difficulty == Difficulty.SMOKE and not c.skip_reason]

    def adversarial_cases():
        return [c for c in cases if c.difficulty == Difficulty.ADVERSARIAL and not c.skip_reason]

    def active_cases():
        return [c for c in cases if not c.skip_reason]

    if args.suite == "case":
        case = next((c for c in cases
                     if c.id == args.case_id or getattr(c, "legacy_id", "") == args.case_id), None)
        if not case:
            print(f"用例 {args.case_id} 不存在")
            return
        results = await run_suite([case], f"单条 {args.case_id}")
    elif args.suite == "smoke":
        results = await run_suite(smoke_cases(), "冒烟")
    elif args.suite == "adversarial":
        results = await run_suite(adversarial_cases(), "对抗")
    elif args.suite == "full":
        results = await run_suite(active_cases(), "全量")

    # CI 判定：有未通过用例 → exit 1
    failed = [r for r in results if r.get("score", 0) < 1.0]
    if failed:
        print(f"\n❌ {len(failed)}/{len(results)} 个用例未通过")
        sys.exit(1)
    print("\n✅ 全部用例通过")

if __name__ == "__main__":
    asyncio.run(main())
