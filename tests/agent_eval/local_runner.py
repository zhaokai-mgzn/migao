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
# 模块级注入 .github（render_cases/filter_by_persona 单一源，issue #2855）——
# 保证无 --cases（ALL_CASES 生成物）路径下 main() 也能 import
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / ".github"))
from eval_cases import ALL_CASES, EvalCase, Skill, Difficulty

# Config
ADMIN_API = os.environ.get("ADMIN_API_URL", "http://localhost:8080")
AI_API = os.environ.get("AI_API_URL", "http://localhost:8001")
PHONE = os.environ.get("TEST_PHONE", "13800138000")
BYPASS_CODE = os.environ.get("BYPASS_CODE", "123456")
# CI 模式：SERVICE_TOKEN 存在时，chat/send 无 auth（DEBUG 默认用户），admin-api 用 X-Service-Token
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "")

# Persona：mibao（默认，B 端工作助手）/ xiaobu（C 端客服小布）
# xiaobu 模式：不带 Bearer token，通过 X-Debug-Role: customer 让 DEBUG 模式路由到小布，
# 并验证 C 端数据隔离（customer_order_query 而非 order_query）。
PERSONA = os.environ.get("PERSONA", "mibao").strip().lower()


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
    # xiaobu 模式：不登录，走 DEBUG customer 身份（X-Debug-Role header 由 send 注入）
    if PERSONA == "xiaobu":
        return ""
    if SERVICE_TOKEN:
        return ""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{ADMIN_API}/api/auth/sms/login",
                         json={"phone": PHONE, "code": BYPASS_CODE}, timeout=10)
        return r.json()["data"]["accessToken"]

def _chat_headers(token: str) -> dict:
    """ai-agent 请求头：调试身份必须显式声明（P0-3 安全加固）

    - xiaobu（C 端）：X-Debug-Role: customer（DEBUG 本地栈/CI 显式注入小布身份）
    - mibao（B 端）+ SERVICE_TOKEN（CI）：X-Debug-Role: mibao——此前不带任何头
      依赖"无 token → DEBUG 静默降级 tenant1 管理员"，服务端已 fail-closed，
      现改为显式声明管理员调试身份，语义不变（eval 仍跑 tenant1 词元通达）。
    - 其它（本地真实登录）：Bearer token
    """
    if PERSONA == "xiaobu":
        return {"X-Debug-Role": "customer"}
    if SERVICE_TOKEN:
        return {"X-Debug-Role": "mibao"}
    return {"Authorization": f"Bearer {token}"} if token else {}

async def get_or_create_session(token: str, prefer_new: bool = True) -> str:
    """获取或创建会话"""
    async with httpx.AsyncClient() as c:
        h = _chat_headers(token)
        if prefer_new:
            r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
            return r.json()["data"]["id"]
        r = await c.get(f"{AI_API}/api/chat/sessions", headers=h, timeout=10)
        sessions = r.json().get("data", {}).get("items", [])
        if sessions:
            return sessions[0]["id"]
        r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
        return r.json()["data"]["id"]

async def send_message(token: str, session_id: str, message: str, images: list = None) -> dict:
    """发送消息并收集 SSE 事件

    Args:
        message: 文本内容
        images: 可选图片 URL 列表（后端 ChatSendRequest.images，≤3 张，
                https:// 或 /api/files 开头）。带图时后端走多模态/vision 链路
                （图片意图澄清用例端到端验收，issue #2794）。
    """
    body = {"session_id": session_id, "message": message}
    if images:
        body["images"] = images

    async with httpx.AsyncClient(timeout=120) as c:
        h = _chat_headers(token)

        result = {
            "user_message": message,
            "images": images or [],
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
                            json=body) as resp:
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

def _parse_expectation(exp: str) -> tuple[str, dict | None]:
    """解析 'tool(k=v, k2=[a, b])' 期望 → (工具名, args 字典)。

    纯工具名（无括号）→ (工具名, None)。args 值为列表时解析为 list。
    兼容语义描述值（复用上轮 UUID / 本月1号 / 遮光窗帘 等中文值原样保留）。
    """
    m = re.match(r"^([a-zA-Z_]\w*)\s*\((.*)\)\s*$", exp.strip())
    if not m:
        return exp.strip(), None
    tool = m.group(1)
    body = m.group(2)
    args: dict = {}
    for seg in _split_top_level(body, ","):
        seg = seg.strip()
        if not seg or "=" not in seg:
            continue
        k, _, v = seg.partition("=")
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1]
            items = [x.strip().strip('"\'') for x in inner.split(",")]
            args[k] = [x for x in items if x != ""]
        else:
            args[k] = v.strip('"\'')
    return tool, args


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """按最外层分隔符切分（忽略括号内逗号，如 item_ids=[1, 3, 5]）"""
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


_RE_CJK = re.compile(r"[\u4e00-\u9fff]")


def _arg_mismatch_reason(actual: dict, expected: dict) -> str | None:
    """args 关键字段校验：返回第一个不匹配原因；全部匹配返回 None。

    规则（弱断言加固，issue #2854）：
    - key 必须存在于实际 args（关键字段缺失即失败）
    - 列表期望（item_ids=[打孔]）：实际列表必须包含期望每个元素（str 化比较）
    - 纯 ASCII 标量（action/days/price/component）：宽容相等（数字 str/int 混比、bool 大小写）
    - 含中文标量（复用上轮 UUID / 本月1号 / 遮光窗帘）：语义描述，仅校验 key 存在
      （与旧弱断言兼容，防止把语义描述期望误判为字面值）
    """
    for k, exp_val in expected.items():
        if k not in actual:
            return f"missing arg '{k}'"
        act_val = actual[k]
        if isinstance(exp_val, list):
            if not isinstance(act_val, list):
                act_val = [act_val]
            exp_set = {str(x) for x in exp_val}
            act_set = {str(x) for x in act_val}
            if not exp_set.issubset(act_set):
                return f"arg '{k}' missing {sorted(exp_set - act_set)}"
            continue
        exp_s = str(exp_val).strip()
        act_s = str(act_val).strip()
        if _RE_CJK.search(exp_s):
            # 中文语义描述值：仅 key 存在（旧弱断言兼容）
            continue
        if exp_s.lower() in ("true", "false"):
            truthy = {"true", "1"} if exp_s.lower() == "true" else {"false", "0"}
            if act_s.lower() not in truthy:
                return f"arg '{k}' expected {exp_s} got {act_s}"
            continue
        try:
            if float(exp_s) != float(act_s):
                return f"arg '{k}' expected {exp_s} got {act_s}"
        except ValueError:
            if exp_s != act_s:
                return f"arg '{k}' expected {exp_s} got {act_s}"
    return None


def check_expectation(result: dict, expectation: str) -> tuple[bool, str]:
    """检查一条 expectation 是否满足

    支持 OR 逻辑（'A or B'）：任一满足即通过。
    direct_reply 语义（澄清/引导形态）：该轮无 tool_calls 且有 final_text。
    组合形态如 'direct_reply or interact'（模糊意图澄清：文本引导或澄清卡均可）。
    'tool(k=v, ...)' 形态 → args 关键字段校验（issue #2854 P0-3 弱断言加固）。
    """
    exp_lower = expectation.lower()

    # 拆 OR 分支（保持向后兼容：无 or 时等价于单分支）
    parts = [p.strip() for p in expectation.split(" or ") if p.strip()]
    parts_lower = [p.lower() for p in parts]
    has_direct_part = any("direct_reply" in p for p in parts_lower)

    if has_direct_part:
        # direct_reply 分支满足：无工具调用且有文本输出
        if not result.get("tool_calls") and result.get("final_text"):
            return True, "direct reply without tool call"
        # 单值 direct_reply（无 or）→ 维持旧语义：有工具调用即失败
        if len(parts) == 1:
            return False, "expected direct_reply (no tool) but got tool calls"
        # 含 or：direct 分支未命中，继续尝试其他工具分支
        parts = [p for i, p in enumerate(parts) if "direct_reply" not in parts_lower[i]]

    # 反转断言（未被调用 / not called）优先：不受下方工具名匹配干扰
    if "未被调用" in expectation or "not called" in exp_lower:
        for tc in result["tool_calls"]:
            if tc["name"] in exp_lower:
                return False, f"tool {tc['name']} was called but should NOT be"
        return True, "tool not called as expected"

    # 检查 tool 名称 + args 关键字段（支持 OR 逻辑：A or B）
    checked_args = False
    last_args_detail = ""
    for part in parts:
        tool_name, exp_args = _parse_expectation(part)
        p_lower = part.lower()
        if exp_args is None:
            # 纯工具名（跨轮汇总子串匹配，保持向后兼容）
            # xiaobu 模式：expectation 里的 order_query 视为 customer_order_query
            want = p_lower
            if PERSONA == "xiaobu" and "order_query" in want:
                want = want.replace("order_query", "customer_order_query")
            for tn in result.get("__all_tool_names", []):
                if tn.lower() in want:
                    return True, f"tool '{tn}' matched"
            continue

        # 带 args 期望：本轮 tool_calls 里找名字匹配 + args 关键字段校验
        checked_args = True
        want = tool_name.lower()
        if PERSONA == "xiaobu" and want == "order_query":
            want = "customer_order_query"
        if not result.get("tool_calls"):
            continue
        for tc in result["tool_calls"]:
            tc_name = str(tc.get("name") or "").lower()
            if tc_name != want and want not in tc_name:
                continue
            reason = _arg_mismatch_reason(tc.get("args") or {}, exp_args)
            if reason is None:
                return True, f"tool '{tc['name']}' matched with key args"
            last_args_detail = f"tool '{tc['name']}' matched but {reason}"

    if checked_args and last_args_detail:
        return False, last_args_detail

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

def _last_round_error_verdict(results: list, expectations: list, data_checks: list) -> str | None:
    """真实验收守卫（issue #2887 验收复盘）：最后轮报错 → 用例判失败。

    背景：expectations 是「任意一轮命中即过」，图片轮报错时前面的轮次可能已命中
    success=true / tool 等 expectation，用例仍被计为通过（假验收 —— 线上
    sess_806703a2dcca4059 的图片崩溃正是类假阳性）。
    规则：最后一轮（用例终点）出现 error 事件且用例未显式预期错误
    （expectations/data_checks 含 error.code= 或 suggestion）→ 返回失败原因；
    否则返回 None。
    """
    if not results:
        return None
    last_error = results[-1].get("error")
    if not last_error:
        return None
    expected_err_markers = ("error.code", "suggestion")
    all_checks = list(expectations or []) + list(data_checks or [])
    expects_error = any(
        any(m in (str(c).lower()) for m in expected_err_markers)
        for c in all_checks
    )
    if expects_error:
        return None
    return f"最后轮报错（用例未预期错误）: {str(last_error)[:120]}"


# ── 波动分类（issue #2890：Agent Eval smoke 偶发 LLM 波动根治）──
# 目标：把「失败→人工 gh run rerun 拼人品」变成「机器判定」——
#   - llm-noise     ：第二次（新 session）通过 → 噪声，自动放行并记 flake 台账；
#   - reproducible  ：两次同指纹失败 → 确定性回归，禁止 rerun 掩盖（按签名排查）；
#   - unstable      ：两次失败但指纹不同 → LLM 发散，标注待查（可 rerun 取证）；
#   - infra         ：失败为传输/超时/5xx → 运行级重试（workflow 已整跑重试 1 次）。
_INFRA_MARKERS = (
    "transport", "connect", "timeout", "all connection attempts failed",
    " 502", " 503", " 504", "internal server error", "bad gateway",
)


def _is_infra_error(err) -> bool:
    """失败是否运行级（网络/超时/5xx）——与 LLM 波动无关，重试属于合理操作。"""
    s = str(err).lower()
    return any(m in s for m in _INFRA_MARKERS)


def _failure_signature(result: dict) -> str:
    """失败指纹：失败期望（断言+原因）与最后轮错误首行 → 判定两次失败是否同根因。

    两次失败指纹一致 = 大概率确定性复现（同一违反点），不一致 = 各次不同路径的
    随机失败。错误事件保留前 100 字符（如 "AttributeError: 'list' object ..."）。
    """
    parts = [
        f"{exp}|{str(detail)[:60]}"
        for exp, detail in result.get("failed", [])
    ]
    parts = sorted(set(parts))
    err = result.get("last_error")
    if err:
        parts.append(f"error|{str(err)[:100]}")
    return "||".join(parts)


def _classify_attempts(first: dict, second: dict) -> str:
    """两次尝试（同用例、新 session）结果的波动分类。"""
    if first.get("score", 0) >= 1.0:
        return "pass"
    if second.get("score", 0) >= 1.0:
        return "llm-noise"
    if _is_infra_error(first.get("last_error")) or _is_infra_error(second.get("last_error")):
        return "infra"
    if _failure_signature(first) == _failure_signature(second):
        return "reproducible"
    return "unstable"


async def run_case(case, token: str, session_id: str) -> dict:
    """运行单个评测用例（多轮对话）

    user_inputs 每轮可为 str（纯文本）或 dict（带图消息）：
      {"text": "看看这个", "images": ["https://...jpg"]}
    """
    results = []
    all_tool_names = []

    for i, msg in enumerate(case.user_inputs):
        if isinstance(msg, dict):
            text = msg.get("text", "")
            images = msg.get("images") or []
        else:
            text = msg
            images = []
        r = await send_message(token, session_id, text, images=images)
        r["__round"] = i + 1
        r["__all_tool_names"] = [tc["name"] for tc in r["tool_calls"]]
        all_tool_names.extend(r["__all_tool_names"])
        results.append(r)

        # 简单等待，避免请求过快
        await asyncio.sleep(0.5)

    # 汇总所有轮的 tool 名称
    for r in results:
        r["__all_tool_names"] = all_tool_names

    # data_checks 中机器可判定的条目（success=true 等）计入评分（issue #2854 P0-3）
    # 自然语义的 data_checks（如「返回趋势数据」）保持原语义：仅在最后轮错误守卫中参与
    scoring_checks = list(case.expectations or [])
    for dc in (case.data_checks or []):
        dcs = str(dc).strip().lower()
        if "success=true" in dcs or "error.code=" in dcs or "未被调用" in dc or "not called" in dcs:
            scoring_checks.append(str(dc))

    # 检查 expectations + 机器可判定 data_checks
    passed_expectations = 0
    failed_expectations = []
    for exp in scoring_checks:
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

    total_exp = len(scoring_checks)
    score = passed_expectations / total_exp if total_exp > 0 else 1.0

    # 真实验收守卫：最后轮报错 → 整体判失败（除非用例显式预期错误）
    verdict = _last_round_error_verdict(results, case.expectations, case.data_checks)
    if verdict:
        failed_expectations.append((verdict, results[-1].get("error", "")))
        score = 0.0

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

async def run_suite(cases, label: str, classify: bool = True):
    """运行一组用例

    classify（默认开，issue #2890 波动分类）：失败用例重试 1 次并判定
    llm-noise / reproducible / unstable / infra（见 _classify_attempts），
    noise 自动放行并记 flake 台账；true regressions 显式标注禁止 rerun 掩盖。
    """
    print(f"\n{'='*60}")
    print(f"  {label}: {len(cases)} 个用例" + ("" if classify else "（--no-classify 兼容模式）"))
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
    flake_ledger = []  # 台账：一次运行中「首次失败经分类放行/确认」的用例

    for i, case in enumerate(cases):
        if case.skip_reason:
            continue

        # 每个用例用独立 session，避免前序用例污染上下文
        session_id = await get_or_create_session(token, prefer_new=True)

        icon = {Difficulty.SMOKE: "🟢", Difficulty.NORMAL: "🔵",
                Difficulty.EDGE: "🟡", Difficulty.ADVERSARIAL: "🔴"}.get(case.difficulty, "⚪")

        # 数据隔离：修改类用例前后保存/恢复状态。
        # 覆盖两类被改的商品：PR-009 改「遮光窗帘」（米白色遮光窗帘），PR-010 改「2699 系列雪尼尔窗帘」。
        # 之前只快照「遮光窗帘」命中错商品，导致 PR-010 改价后未被恢复。
        snapshot_pids = []
        if any(t in case.tags for t in ["id_reuse", "update", "full_lifecycle"]):
            for kw in ("2699", "遮光窗帘"):
                pid = await snapshot_product(token, kw)
                if pid and pid not in snapshot_pids:
                    snapshot_pids.append(pid)

        try:
            r = await run_case(case, token, session_id)
            # 真实 LLM 评测 flaky 容错：失败用例自动重试 1 次（新 session 隔离上下文），
            # 并按指纹分类（issue #2890）：噪声放行 + 记台账；复现型/不稳定型显式标注，
            # 禁止 rerun 掩盖确定性回归。
            classification = "pass"
            if r["score"] < 1.0 and classify:
                retry_sid = await get_or_create_session(token, prefer_new=True)
                r2 = await run_case(case, token, retry_sid)
                r2["retried"] = True
                classification = _classify_attempts(r, r2)
                if classification == "llm-noise":
                    r = r2
                    flake_ledger.append({
                        "case_id": case.id,
                        "title": case.title,
                        "classification": "llm-noise",
                        "reason": "首次失败、新 session 重试通过（LLM 波动）",
                        "signature": _failure_signature(r2),
                        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                        "sha": os.environ.get("GITHUB_SHA", "")[:12],
                    })
                else:
                    # reproducible / unstable / infra：保留第二次尝试作为失败证据
                    r = r2
                    flake_ledger.append({
                        "case_id": case.id,
                        "title": case.title,
                        "classification": classification,
                        "reason": {
                            "reproducible": "两次同指纹失败（确定性回归，禁止 rerun 掩盖，按签名排查）",
                            "unstable": "两次失败但指纹不同（LLM 发散，标注待查）",
                            "infra": "传输/超时/5xx（运行级，可整跑重试）",
                        }.get(classification, classification),
                        "signature": _failure_signature(r2),
                        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                        "sha": os.environ.get("GITHUB_SHA", "")[:12],
                    })
            elif r["score"] < 1.0:
                # --no-classify 兼容模式：旧的无差别单次重试
                retry_sid = await get_or_create_session(token, prefer_new=True)
                r2 = await run_case(case, token, retry_sid)
                r2["retried"] = True
                if r2["score"] >= 1.0 or r2["score"] > r["score"]:
                    r = r2
            r["classification"] = classification
            results.append(r)
            total_score += r["score"]
            if r["score"] >= 1.0:
                passed_count += 1

            status = "✅" if r["score"] >= 1.0 else "⚠️" if r["score"] >= 0.5 else "❌"
            retry_note = "（重试后通过）" if r.get("retried") and r["score"] >= 1.0 else ""
            cls_note = {
                "llm-noise": " 🎲噪声·重试放行(已记账)",
                "reproducible": " 🔬复现型回归·禁止rerun",
                "unstable": " 🧬不稳定·两次不同指纹",
                "infra": " 🌐运行级故障",
            }.get(classification, "")
            print(f"  {icon} {status} {case.id}: {case.title[:50]}{retry_note}{cls_note}")
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
            for pid in snapshot_pids:
                await restore_product(token, pid)

        await asyncio.sleep(1)  # rate limit

    # ── flake 台账（issue #2890）：落盘 + 摘要，驱动断言收敛与高波动用例治理 ──
    if classify and flake_ledger:
        try:
            import json as _json
            ledger_path = os.environ.get("AGENT_EVAL_FLAKE_LOG", "agent-eval-flakes.json")
            _prev = []
            if os.path.exists(ledger_path):
                try:
                    import json as _json2
                    with open(ledger_path, "r", encoding="utf-8") as _f:
                        _prev = _json2.load(_f)
                except Exception:
                    _prev = []
            with open(ledger_path, "w", encoding="utf-8") as _f:
                _json.dump(_prev + flake_ledger, _f, ensure_ascii=False, indent=1)
            print(f"\n⚠️ flake 台账（{len(flake_ledger)} 条本次新增）→ {ledger_path}")
            for entry in flake_ledger:
                print(f"   - {entry['case_id']} [{entry['classification']}] {entry['reason'][:46]}")
        except Exception as e:
            print(f"⚠️ 台账写入失败（非致命）: {e}")

    # ── 运行级 infra 提示 ──
    if any(r.get("classification") == "infra" for r in results):
        print("\n🌐 检测到运行级故障（传输/超时/5xx）：整跑重试是合理操作（workflow 已自动做 1 次）；")
        print("   复现型（🔬）失败【不要】rerun——签名一致即确定性回归，直接按签名排查。")

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
            persona=c.get("persona", ""),
        ))
    return cases


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["smoke", "normal", "full", "adversarial", "case"], nargs="?", default="smoke")
    parser.add_argument("--case-id", help="单条用例 ID（支持新 ID 与 legacy_id，如 OR-002 或 O002）")
    parser.add_argument("--cases", help="用例库目录（cases/*.yml）——提供时直接读 YAML（单一源）")
    parser.add_argument("--no-classify", action="store_true",
                        help="关闭波动分类（issue #2890 兼容开关：恢复旧的无差别单次重试，调试用）")
    args = parser.parse_args()

    if args.cases:
        cases = load_cases_from_yaml(args.cases)
        print(f"📚 用例源: {args.cases}（{len(cases)} 条，YAML 单一源）")
    else:
        cases = ALL_CASES
        print(f"📚 用例源: eval_cases.py（生成物，{len(cases)} 条）")

    # persona 归属过滤（issue #2855）：mibao 跳过 C 端专属（xiaobu）用例，
    # xiaobu 跳过 B 端专属（mibao）用例；未标记=双端保留。
    from render_cases import filter_by_persona
    before = len(cases)
    cases = filter_by_persona(cases, PERSONA)
    if len(cases) != before:
        print(f"🧪 Persona={PERSONA}：persona 过滤后 {len(cases)}/{before} 条（排除 {before - len(cases)} 条另一端专属）")

    # xiaobu 模式：仅跑 C 端可用用例（订单查询/下单/售后/通用），
    # 跳过管理类（order_manage/after_sales_manage/product_manage 等 B 端工具）用例
    if PERSONA == "xiaobu":
        XIAOBU_ONLY_TAGS = {"order_query", "order_create", "aftersale", "query", "product"}
        def xiaobu_filter(c):
            if c.skip_reason:
                return False
            tags = set(c.tags or [])
            return bool(tags & XIAOBU_ONLY_TAGS)
        cases = [c for c in cases if xiaobu_filter(c)]
        print(f"🧪 Persona=xiaobu：过滤后 {len(cases)} 条 C 端用例")

    def smoke_cases():
        return [c for c in cases if c.difficulty == Difficulty.SMOKE and not c.skip_reason]

    def normal_cases():
        # 每日回归：normal tier（smoke 由 PR gate 跑，adversarial 由每周任务跑）
        return [c for c in cases if c.difficulty == Difficulty.NORMAL and not c.skip_reason]

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
        results = await run_suite([case], f"单条 {args.case_id}", classify=not args.no_classify)
    elif args.suite == "smoke":
        results = await run_suite(smoke_cases(), "冒烟", classify=not args.no_classify)
    elif args.suite == "normal":
        results = await run_suite(normal_cases(), "每日回归（normal）")
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
