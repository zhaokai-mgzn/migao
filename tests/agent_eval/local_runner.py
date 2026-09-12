"""
Mibao Agent 本地评测 — 直接调 localhost chat API，采集 SSE 事件

用法:
  PRIMARY_API_KEY=sk-xxx python local_runner.py smoke     # 冒烟
  PRIMARY_API_KEY=sk-xxx python local_runner.py full      # 全量
  PRIMARY_API_KEY=sk-xxx python local_runner.py case P005 # 单条
"""

import sys, os, json, time, asyncio, re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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

# ── 节流 sleep（可配，issue #3361 评测提速）──
# 为什么可配：评测墙钟时间几乎全花在真实 LLM 往返上，固定 sleep 是纯额外开销 ——
# 实测 C 端 normal 单跑 19m39s（18 条），其中 ~63s 是 0.5s/轮 + 1s/用例的固定等待，
# B 端 47 条约 3min。真实 LLM 有并发限流需求，故保留"可调"而不是删除：
# CI 用 EVAL_ROUND_SLEEP=0.2 / EVAL_CASE_SLEEP=0.3，本地调试可调回 0.5/1。
def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        print(f"⚠️ {name}={raw!r} 非法，回落默认 {default}")
        return default
    return v if v >= 0 else default


ROUND_SLEEP = _env_float("EVAL_ROUND_SLEEP", 0.5)
CASE_SLEEP = _env_float("EVAL_CASE_SLEEP", 1.0)

# ── C 端用例集选择（纯逻辑拆到 eval_case_filter，issue #3266）──
# 拆出去的动机：本文件有模块级 `import httpx`，而 CI 的 ci-workflow-helper 测试 job
# 只装 pytest+pyyaml → 任何想复用「用例集选择」的测试/脚本一 import 本模块就崩。
# eval_case_filter 零第三方依赖，runner/测试/覆盖体检三处共用同一实现。
sys.path.insert(0, os.path.dirname(__file__))
from eval_case_filter import (  # noqa: E402
    XIAOBU_TOOLS,
    case_expectation_tools as _case_expectation_tools,
    case_persona as _case_persona,
    case_skip_reason as _case_skip_reason,
    select_cases_for_persona,
)


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


def _safe_json(resp, default=None):
    """防御性 JSON 解析：响应非 JSON（限流/瞬断/400 HTML）时返回默认值，不中断评测。

    实测崩溃（2026-09-09）：对生产跑 normal 全量评测，中途 snapshot_product 的
    GET /api/admin/products 返回 400 HTML → r.json() 抛 JSONDecodeError →
    整个评测崩溃退出，后续用例全部未跑。评测基础设施的健壮性比单个用例
    失败更重要：任何辅助请求的非 JSON 响应都应降级（返回 None/[]），
    由后续断言与重试机制处理，而不是让一次瞬时限流毁掉整轮基线。
    """
    try:
        return json.loads(getattr(resp, "content", b""))
    except Exception:
        return default


async def snapshot_product(token: str, product_keyword: str) -> str | None:
    """保存商品当前状态，返回 product_id"""
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                        params={"keyword": product_keyword, "page": 1, "size": 1})
        items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
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


async def _end_session(token: str, session_id: str) -> None:
    """评测会话清理（协议 §2.2）：case 结束后关闭会话，并触发长时记忆 flush。

    **主路径必须是 ai-agent 的关闭接口**（PUT {AI_API}/api/chat/sessions/{id}/close）：
    该路径 SessionService.close → SessionMemory.close_session → _flush_pending_memories，
    是记忆候选落库 user_memories 的**唯一入口**（issue #2815 会话末聚合）。

    issue #3357 复盘（清理静默失败的假绿温床）：
      旧实现打 admin-api `POST /api/admin/agent-sessions/{id}/end`，但该接口操作的是
      **人工会话表 agent_sessions**，C 端评测会话在 ai-agent 的 **sessions** 表 ——
      两表 id 不互认 → 恒 404 → 被 `except: pass` 吞掉。后果有两层：
        1. 评测会话从未真正关闭（残留 active，与"实测 8 个残留会话未关闭"吻合）；
        2. close 路径从未执行 → 记忆候选从未 flush → user_memories 恒 0 条，
           而报告一片全绿（"记忆没落库"没有任何断言看得见）。
      故：主路径换成对的接口，且失败**打 warning**（清理失败必须可见，不再静默）。
    """
    try:
        async with httpx.AsyncClient() as c:
            r = await c.put(f"{AI_API}/api/chat/sessions/{session_id}/close",
                            headers=_chat_headers(token), timeout=15)
            if r.status_code >= 400:
                print(f"     ⚠️ 会话关闭失败 HTTP {r.status_code}: id={session_id} "
                      f"body={str(getattr(r, 'content', b''))[:120]}")
    except Exception as e:
        print(f"     ⚠️ 会话关闭异常: id={session_id} {type(e).__name__}: {e}")
    # 兼容调用已**删除**（issue #3361 顺手清理）：admin-api `agent_sessions` 是人工会话表，
    # 其主键与 ai-agent 会话 id 不互认，传 ai 会话 id 永远查不到行 —— 实测 CI 里每次调用
    # 都在 admin-api 侧留一条 `[NOT_FOUND] 客服会话不存在` 告警（死代码 + 噪音）。
    # 人工会话本身是**待人工处理的工单**，也不该由评测 harness 关闭。


async def _run_pre_clean(token: str, spec: dict) -> str:
    """评测前数据清理（写类 case 自我污染防线，§14.2/CU-003）。

    支持类型：
    - customer_tag_remove: 移除「customer_keyword 匹配的第 customer_index 位客户」
      上的 tag_name 标签（case 每次成功 add_tag 即污染生产数据 → 下一跑幂等拒绝，
      在 run_case 前把目标客户标签清干净，保证写流程从干净状态开始）。
    """
    _type = spec.get("type", "")
    if _type == "product_remove":
        # 清理建品测试残留（下架→删除，on_sale 不能直接删）：多次建品「测试窗帘」
        # 等残留 → 全量评测重名冲突（agent 发现已存在 → 澄清 → create 未达）。
        kw = str(spec.get("product_keyword", ""))
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                            params={"keyword": kw, "page": 1, "size": 20}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            removed = 0
            for p in items:
                if kw not in str(p.get("name", "")):
                    continue
                pid = p.get("id")
                await c.put(f"{ADMIN_API}/api/admin/products/{pid}/status", headers=h,
                            json={"status": "off_sale"}, timeout=15)
                await c.delete(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
                removed += 1
            return f"已清理 {removed} 个「{kw}」商品" if removed else f"无「{kw}」商品需清理"
    if _type == "product_dedupe":
        # 同名商品去重（Round 72 审计：3 件同名「遮光窗帘」¥100 是 6 个 case
        # 「确定性根因」的源头——agent 发选择卡 case 无槽位应答 → 目标工具
        # 从不执行）。按关键词清理重复：同名同价 >1 时保留最早创建（种子，
        # 加工项最全），删其余（下架→删除）。
        kw = str(spec.get("product_keyword", ""))
        price = spec.get("price")  # 可选：限定价格
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                            params={"keyword": kw, "page": 1, "size": 20}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            matched = [p for p in items if kw in str(p.get("name", ""))
                       and (price is None or p.get("price") == price)]
            if len(matched) <= 1:
                return f"「{kw}」无重复（{len(matched)} 件），无需去重"
            # 保留最早创建的（createdAt 最小）——种子商品
            matched.sort(key=lambda p: str(p.get("createdAt") or ""))
            keeper = matched[0]
            removed = 0
            for p in matched[1:]:
                pid = p.get("id")
                await c.put(f"{ADMIN_API}/api/admin/products/{pid}/status", headers=h,
                            json={"status": "off_sale"}, timeout=15)
                await c.delete(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
                removed += 1
            return f"已去重「{kw}」：删 {removed} 件重复，保留种子 {keeper.get('id','')[:8]}"
    if _type == "employee_reactivate":
        # 恢复被评测禁用的测试员工（HR-003 存量状态消耗）：王五被禁用后
        # agent 合理说「已停用无需操作」→ 评测前恢复 active。
        # Round 75：查不到时重试 2 次（网络波动 _safe_json 降级返回空 →
        # 误报「不存在」跳过 → 王五未恢复 → agent 见 disabled 合理不操作 → 失败）
        name = str(spec.get("employee_name", ""))
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            target = None
            for attempt in range(3):
                r = await c.get(f"{ADMIN_API}/api/admin/users", headers=h,
                                params={"page": 1, "size": 50}, timeout=15)
                items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
                target = next((u for u in items if u.get("name") == name), None)
                if target is not None:
                    break
            if target is None:
                return f"员工「{name}」查询 3 次未命中（跳过）"
            if target.get("status") != "disabled":
                return f"员工「{name}」状态 {target.get('status')}，无需恢复"
            await c.put(f"{ADMIN_API}/api/admin/users/{target.get('id')}/status",
                        headers=h, json={"status": "active"}, timeout=15)
            return f"已恢复「{name}」为 active（防存量消耗）"
    if _type == "aftersales_ticket_prepare":
        # 确保有 pending 工单供「关闭工单」case 使用：AS-004 关闭后存量被消耗 →
        # 无 pending 时用真实订单创建一张退款工单（数据治理：存量资源准备）。
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            r = await c.get(f"{ADMIN_API}/api/admin/after-sales", headers=h,
                            params={"page": 1, "size": 5}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            pending = [t for t in items if t.get("status") == "pending"]
            if pending:
                return f"已有 {len(pending)} 张 pending 工单"
            r = await c.get(f"{ADMIN_API}/api/admin/orders", headers=h,
                            params={"page": 1, "size": 1}, timeout=15)
            orders = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            if not orders:
                return "无订单可创建测试工单"
            await c.post(f"{ADMIN_API}/api/admin/after-sales", headers=h,
                         json={"orderId": orders[0].get("id"), "ticketType": "refund",
                               "reason": "评测准备工单"}, timeout=15)
            return "已创建测试工单（供关闭）"
    if _type != "customer_tag_remove":
        return f"未知 pre_clean 类型: {_type}（跳过）"
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        kw = str(spec.get("customer_keyword", ""))
        idx = int(spec.get("customer_index", 0) or 0)
        r = await c.get(f"{ADMIN_API}/api/admin/customers", headers=h,
                        params={"keyword": kw, "page": 1, "size": 10}, timeout=15)
        items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
        if idx >= len(items):
            return f"客户「{kw}」索引 {idx} 不存在（共 {len(items)} 位）"
        customer = items[idx]
        cid = customer.get("id")
        r = await c.get(f"{ADMIN_API}/api/admin/customer-tags", headers=h, timeout=15)
        data = (_safe_json(r, {}) or {}).get("data") or {}
        tags = data if isinstance(data, list) else (data.get("tags") or data.get("items") or [])
        tag_id = next((t.get("id") for t in tags
                       if isinstance(t, dict) and t.get("name") == spec.get("tag_name")), None)
        if not tag_id:
            return f"标签「{spec.get('tag_name')}」不存在（跳过清理）"
        if tag_id in (customer.get("tags") or []):
            await c.delete(f"{ADMIN_API}/api/admin/customers/{cid}/tags/{tag_id}",
                           headers=h, timeout=15)
            who = customer.get("name") or customer.get("phone") or cid
            return f"已清理 {who} 的「{spec.get('tag_name')}」标签"
        return f"客户无「{spec.get('tag_name')}」标签，无需清理"


# ── Auth ──

async def _retry_502(desc: str, fn, *args, max_retries: int = 6, **kwargs):
    """502/连接失败重试（Round 76：多会话并发部署窗口打断评测——等待部署
    结束自愈续跑，替代直接失败退出）。纯逻辑错误（400/401/403/404）不重试。"""
    import asyncio as _asyncio
    last = None
    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout,
                httpx.ReadError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            last = e
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in (502, 503, 504):
                last = e
            else:
                raise
        except RuntimeError as e:
            # 上层已格式化的 502 错误（"登录失败: HTTP 502 ..." / "创建会话失败: HTTP 502"）
            if "502" in str(e) or "502" in str(getattr(e, "args", "")):
                last = e
            else:
                raise
        if attempt == max_retries - 1:
            raise last
        wait = 20 * (attempt + 1)
        print(f"  ⏳ {desc} 遇 502/网络波动（第 {attempt+1} 次）——等待 {wait}s 重试（部署窗口自愈）")
        await _asyncio.sleep(wait)
    raise last


async def login() -> str:
    """获取测试 token（CI 模式直接返回空字符串，走 SERVICE_TOKEN 无 auth）"""
    async def _do_login() -> str:
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{ADMIN_API}/api/auth/sms/login",
                             json={"phone": PHONE, "code": BYPASS_CODE}, timeout=10)
            payload = _safe_json(r, {}) or {}
            access_token = (payload.get("data") or {}).get("accessToken")
            if not access_token:
                raise RuntimeError(f"登录失败: HTTP {getattr(r, 'status_code', '?')} {str(getattr(r, 'content', b''))[:200]}")
            return access_token
    # xiaobu 模式：不登录，走 DEBUG customer 身份（X-Debug-Role header 由 send 注入）
    # ⚠️ 必须先于 _retry_502：此前 502 重试重构把 return 提到短路之前，导致
    #    这两个分支变成**死代码** —— xiaobu/CI 模式仍发真实 SMS 登录，本地栈
    #    无用户时 401「该手机号未注册」，评测全部失败（issue #3270 实证）。
    if PERSONA == "xiaobu":
        return ""
    if SERVICE_TOKEN:
        return ""
    return await _retry_502("登录", _do_login)

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
    """获取或创建会话（502 重试：部署窗口自愈）"""
    async def _do() -> str:
        async with httpx.AsyncClient() as c:
            h = _chat_headers(token)
            if prefer_new:
                r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
                payload = _safe_json(r, {}) or {}
                sid = (payload.get("data") or {}).get("id")
                if not sid:
                    raise RuntimeError(f"创建会话失败: HTTP {getattr(r, 'status_code', '?')} {str(getattr(r, 'content', b''))[:200]}")
                return sid
            r = await c.get(f"{AI_API}/api/chat/sessions", headers=h, timeout=10)
            sessions = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            if sessions:
                return sessions[0]["id"]
            r = await c.post(f"{AI_API}/api/chat/sessions", headers=h, json={}, timeout=10)
            payload = _safe_json(r, {}) or {}
            sid = (payload.get("data") or {}).get("id")
            if not sid:
                raise RuntimeError(f"创建会话失败: HTTP {getattr(r, 'status_code', '?')} {str(getattr(r, 'content', b''))[:200]}")
            return sid
    return await _retry_502("创建会话", _do)

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
            "interactive": [],  # SSE interactive 事件（卡片：choice/confirm/form，验收协议 §3.5）
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
                    elif current_event == "interactive":
                        result["interactive"].append(payload)
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

# 只读查询类动作等价组（issue #2854 P0-3 回归修复，HR-004）：
# 工具 read_only_actions 常见 {list, all, detail, query, ...}，LLM 对「看角色列表/有哪些角色」
# 选择 action=all/list/query 均属业务等价合法调用——弱断言时代放行，args 收紧后不能误伤。
# 仅限只读查询语义；写操作（add/update/delete/create…）严格匹配。
_QUERY_ACTION_SYNONYMS: frozenset[str] = frozenset({
    "list", "all", "query", "detail", "get", "search", "view", "page", "list_categories",
})


def _is_query_action_equal(exp_s: str, act_s: str) -> bool:
    """只读查询类 action 是否业务等价（list≈all≈query≈detail）。"""
    return exp_s in _QUERY_ACTION_SYNONYMS and act_s in _QUERY_ACTION_SYNONYMS


def _scalar_value_matches(exp_s: str, act_s: str) -> bool:
    """标量值匹配：中文语义值仅验存在（key 已验）；bool 宽容；数字 str/int 混比；其余字面相等。"""
    if _RE_CJK.search(exp_s):
        # 中文语义描述值：仅 key 存在（旧弱断言兼容）
        return True
    if exp_s.lower() in ("true", "false"):
        truthy = {"true", "1"} if exp_s.lower() == "true" else {"false", "0"}
        return act_s.lower() in truthy
    try:
        return float(exp_s) == float(act_s)
    except ValueError:
        return exp_s == act_s


def _match_nested_dict(expected_dict: dict, actual_list: list) -> str | None:
    """列表内 dict 字段级匹配：期望 dict 每个字段须在某个实际 dict 中命中。

    Returns:
        None 表示命中；否则返回第一个不匹配描述。
    """
    for exp_k, exp_v in expected_dict.items():
        exp_s = str(exp_v).strip()
        # 期望字段须在至少一个实际 dict 中命中（值校验复用标量规则）
        matched = False
        for act_dict in actual_list:
            if not isinstance(act_dict, dict):
                continue
            if exp_k not in act_dict:
                continue
            act_s = str(act_dict[exp_k]).strip()
            if _scalar_value_matches(exp_s, act_s):
                matched = True
                break
        if not matched:
            return f"items[].{exp_k} expected {exp_s!r} not matched"
    return None


def _arg_mismatch_reason(actual: dict, expected: dict) -> str | None:
    """args 关键字段校验：返回第一个不匹配原因；全部匹配返回 None。

    规则（弱断言加固，issue #2854）：
    - key 必须存在于实际 args（关键字段缺失即失败）
    - 列表期望：
      * 元素为 dict → 字段级匹配（order_create items=[{sellingMethod, doorWidth}]
        每个期望 dict 的字段须在某个实际 dict 命中，值校验复用标量规则）——Phase 4
      * 元素为标量（item_ids=[打孔]）→ 实际列表必须包含期望每个元素（str 化子集）
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
            # 列表内元素为 dict → 字段级匹配（Phase 4，order_create items 结构断言）
            exp_dicts = [x for x in exp_val if isinstance(x, dict)]
            if exp_dicts:
                for exp_d in exp_dicts:
                    reason = _match_nested_dict(exp_d, act_val)
                    if reason:
                        return f"arg '{k}' {reason}"
                # 混有标量元素的，继续走子集语义
                exp_scalars = [x for x in exp_val if not isinstance(x, dict)]
                if exp_scalars:
                    exp_set = {str(x) for x in exp_scalars}
                    act_set = {str(x) for x in act_val if not isinstance(x, dict)}
                    if not exp_set.issubset(act_set):
                        return f"arg '{k}' missing {sorted(exp_set - act_set)}"
                continue
            # 纯标量列表 → 旧子集语义
            exp_set = {str(x) for x in exp_val}
            act_set = {str(x) for x in act_val}
            if not exp_set.issubset(act_set):
                return f"arg '{k}' missing {sorted(exp_set - act_set)}"
            continue
        exp_s = str(exp_val).strip()
        act_s = str(act_val).strip()
        # 只读查询类 action 等价（HR-004：list≈all≈query≈detail，业务等价不误伤）
        if k == "action" and _is_query_action_equal(exp_s.lower(), act_s.lower()):
            continue
        if _scalar_value_matches(exp_s, act_s):
            continue
        return f"arg '{k}' expected {exp_s} got {act_s}"
    return None


def _interactive_satisfies(exp_args, result: dict) -> tuple[bool, str]:
    """`interact` 期望是否可由 **SSE interactive 事件**满足（issue #3270）。

    卡片有三条发射路径，只有第一条产生 `tool_call` 事件：
      1. `interact` 工具调用 → tool_call + interactive 事件
      2. `handoff_offer` 节点（AI 主动建议转人工）→ **仅 interactive 事件**
      3. LLM 幻觉 `<interact>` XML 兜底解析 → **仅 interactive 事件**

    故 `expectations: tool: interact` 若只查 tool_calls，路径 2/3 下永不可能满足
    → 假失败（CI 实证 CH-013：行为正确却 50 分）。这里把「用户看到一张交互卡」
    作为真实语义：工具调用与 interactive 事件任一命中即可。

    exp_args 指定 `component` 时须组件类型一致（防松弛过度）。
    """
    cards = result.get("interactive") or []
    if not cards:
        return False, "无 interactive 事件"
    want_comp = ""
    if isinstance(exp_args, dict):
        want_comp = str(exp_args.get("component") or "").lower()
    for card in cards:
        comp = str(card.get("component") or card.get("type") or "").lower()
        if not want_comp or comp == want_comp:
            return True, f"interactive 事件命中（component={comp or '?'}）"
    return False, f"interactive 事件组件不匹配（期望 {want_comp}）"


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
            # interact 特例（issue #3270）：卡片可能仅以 interactive 事件下发
            # （handoff_offer 节点 / <interact> XML 兜底），无 tool_call。
            if "interact" in want:
                ok_iv, iv_detail = _interactive_satisfies(None, result)
                if ok_iv:
                    return True, iv_detail
            continue

        # 带 args 期望：本轮 tool_calls 里找名字匹配 + args 关键字段校验
        checked_args = True
        want = tool_name.lower()
        if PERSONA == "xiaobu" and want == "order_query":
            want = "customer_order_query"
        # interact 特例（issue #3270）：卡片可能仅以 interactive 事件下发 →
        # 用事件的 component 校验（等价于 args.component），避免假失败
        if want == "interact":
            ok_iv, iv_detail = _interactive_satisfies(exp_args, result)
            if ok_iv:
                return True, f"tool 'interact' {iv_detail}"
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


# ── 跨轮 case 级断言（acceptance-protocol §3.1/§3.4，issue #3033/#3042）──
# 「任意一轮命中即过」只能证明工具链路通，抓不到时序颠倒（confirm 卡先于加工项询问）
# 与 final_text 反模式（幻觉式撤回"尚未真正创建"）——这两类正是人工验收翻车的样本。
# v1.5（2026-09-08 工具自验证补强）：组件/语义限定时序（interact[choice:processing_items]、
# processing_ask 文本询问也算）、必填参数（create 缺 specifications/加工项价格）、
# 确认死循环、假成功——旧会话数据回放验证：A5/AS-007 旧失败现在全部可拦截。

def _parse_order_before(spec: str) -> tuple[str, str]:
    """解析时序断言 DSL（legacy）：'A before B' → (A, B)。保留兼容旧用例。"""
    parts = spec.split(" before ")
    if len(parts) != 2:
        raise ValueError(f"order_before 格式应为 'A before B'，实际: {spec!r}")
    return parts[0].strip(), parts[1].strip()


def _parse_qualified_order_before(spec: str) -> tuple:
    """解析时序断言 DSL v2：'A[comp:sem] before B[comp]' → 各段元组。

    支持形态：
      - 'interact before order_create'            （legacy 工具级）
      - 'interact[choice] before order_create'    （组件限定：choice 卡）
      - 'interact[choice:processing_items] before interact[confirm]'（加工项卡语义）
      - 'processing_ask before after_sales_manage'（语义 token：卡或文本的加工项询问）
    返回 (tool_a, comp_a, sem_a, tool_b, comp_b, sem_b)；格式错误抛 ValueError。
    """
    import re as _re
    m = _re.match(r"^([a-z_]+)(?:\[([a-z_]+)(?::([a-z_]+))?\])?\s+before\s+([a-z_]+)(?:\[([a-z_]+)(?::([a-z_]+))?\])?$",
                  spec.strip())
    if not m:
        raise ValueError(f"order_before 格式应为 'A[comp:sem] before B[comp]'，实际: {spec!r}")
    return m.groups()


def _is_processing_items_card(args: dict) -> bool:
    """choice 卡是否加工项选择卡（排除瑕疵商品等选项带 ¥ 的普通卡）。

    判定：title 含「加工项」**或「加工」**（OR-017 run 34670989760 实证：LLM 的合法
    加工项卡标题是「这款窗帘支持**加工**哦，需要帮您加上吗？」，不含「加工项」三个字
    但语义完全是加工项询问 —— 只认「加工项」会把 agent 的正确行为误判为"没问"），
    或任一 option value 以 proc_item_ 开头。
    """
    title = str((args or {}).get("title") or "")
    if not (args or {}).get("options"):
        return bool(title and ("加工项" in title or "加工" in title))
    if "加工项" in title or "加工" in title:
        return True
    return any(str(o.get("value", "")).startswith("proc_item") for o in args.get("options") or [])


def _processing_ask_in_round(r: dict) -> bool:
    """该轮是否包含加工项询问（卡或文本）。文本形态：final_text 含「加工项」+ 询问意图词。"""
    for tc in r.get("tool_calls") or []:
        a = tc.get("args") or {}
        if tc.get("name", "").lower() == "interact" and a.get("component") == "choice":
            if _is_processing_items_card(a):
                return True
    text = (r.get("final_text") or r.get("text") or "")
    return "加工项" in text and any(k in text for k in ("选择", "需要", "是否", "加"))


def _first_qualified_round(results: list, tool: str, comp: str | None, sem: str | None) -> int | None:
    """带组件/语义限定的首次调用轮次。"""
    for r in results:
        if tool == "processing_ask":
            if _processing_ask_in_round(r):
                return r.get("__round")
            continue
        for tc in r.get("tool_calls") or []:
            name = str(tc.get("name", "")).lower()
            if tool.lower() not in name:
                continue
            if tool.lower() == "interact" and comp:
                args = tc.get("args") or {}
                if args.get("component") != comp:
                    continue
                if sem == "processing_items" and not _is_processing_items_card(args):
                    continue
            return r.get("__round")
    return None


def _fmt_qualified(tool: str, comp: str | None, sem: str | None) -> str:
    if comp:
        return f"{tool}[{comp}" + (f":{sem}]" if sem else "]")
    return tool


def check_order_before(results: list, order_before: list) -> list:
    """时序断言（v2）：A 首次调用轮次必须早于 B。

    - A 全程未调用 → 违规（"未调用"）；B 未调用 → 不判时序（由 expectations 判工具缺失）；
    - 反序（B 早于 A）→ 违规，注明两轮次，便于按签名排查。
    """
    issues = []
    for spec in order_before or []:
        try:
            a_tool, a_comp, a_sem, b_tool, b_comp, b_sem = _parse_qualified_order_before(str(spec))
        except ValueError:
            issues.append(f"order_before: 无法解析 {spec!r}")
            continue
        ra = _first_qualified_round(results, a_tool, a_comp, a_sem)
        rb = _first_qualified_round(results, b_tool, b_comp, b_sem)
        a_name = _fmt_qualified(a_tool, a_comp, a_sem)
        b_name = _fmt_qualified(b_tool, b_comp, b_sem)
        if ra is None:
            issues.append(f"order_before[{a_name} before {b_name}]: 全程未调用 {a_name}")
        elif rb is not None and rb < ra:
            issues.append(f"order_before[{a_name} before {b_name}]: {a_name}(R{ra}) 晚于 {b_name}(R{rb})——应 {a_name} 先于 {b_name}")
    return issues


def check_confirm_loop(results: list, limit: int = 3) -> list:
    """确认死循环：同一标题 confirm 卡累计出现 >= limit 次 → 违规（sess_c1fce183dae24f22）。

    正常流程 confirm 卡只出现 1 次；2 次以内容忍（用户取消后重新确认）；>=3 次 = 死循环。
    """
    from collections import Counter
    cnt: Counter = Counter()
    for r in results:
        for tc in r.get("tool_calls") or []:
            a = tc.get("args") or {}
            if tc.get("name", "").lower() == "interact" and a.get("component") == "confirm":
                cnt[a.get("title", "(无标题)")] += 1
    return [f"确认死循环: confirm 卡「{t}」共出现 {c} 次未收敛" for t, c in cnt.items() if c >= limit]


def check_false_success(results: list) -> list:
    """假成功：前序轮报错 + 后续文本声称成功 → 违规（sess_e52cff42 类）。

    工具调用全对但用户看到的话是错的（"创建失败却答更新成功"）——验收协议 §3.4 反模式。

    2026-09-13 细化（issue #3365，CI run 34710420292 实证）：**报错 ≠ 谎报**。
    CH-010 该跑 R6 出现一次瞬时错误（R7 起自动恢复），R9 的 `order_create` 真的成功落库
    （`totalAmount=408.0` = 3×128，接地正确），末轮文本称成功 —— 这是**真话**，却被本守卫
    判红。原语义「只要前序轮报错就不许说成功」把"瞬时错误后自愈"也一并否掉了。
    新语义：报错后若**确有写操作成功**（tool_result success=true，与 must_succeed 同源），
    则声明成功不构成谎报；只有"报错且没有任何写成功"时才算假成功。
    """
    err_rounds = [r.get("__round") for r in results if r.get("error")]
    if not err_rounds:
        return []
    wrote_ok = any(st.get("ok")
                   for r in results
                   for st in _tool_result_status(r.get("tool_results") or []))
    for r in results:
        if "成功" in (r.get("final_text") or "") and any(e < r.get("__round") for e in err_rounds):
            if wrote_ok:
                print(f"     ℹ️ 假成功守卫放行(R{r.get('__round')})：前序轮报错但确有写操作成功"
                      f"（声明与现实一致）")
                return []
            return [f"假成功(R{r.get('__round')}): 前序轮报错(R{err_rounds[0]})但文本称成功"]
    return []


def _check_required_field(args: dict, field: str) -> tuple[bool, str]:
    """必填字段检查，支持多级深路径：'key' / 'list[].key' / 'list[].key.sub'。

    OR-009 实拍（Round 38）：order_create 的 sellingMethod/doorWidth/colorName
    在 items[].processing_info 嵌套层，旧实现只支持 list[].key 一级——递归解析
    剩余路径，兼容「items[].processing_info.sellingMethod」这类两级以上深路径。
    """
    if "." not in field:
        v = args.get(field)
        ok = bool(v) and (not isinstance(v, (list, dict)) or len(v) > 0)
        return ok, f"缺失或为空: {field}"
    head, _, rest = field.partition(".")
    key = head[:-2] if head.endswith("[]") else head
    v = args.get(key)
    # dict 层（如 items[].processing_info.sellingMethod 的 processing_info）→ 直接递归
    if isinstance(v, dict):
        ok, detail = _check_required_field(v, rest)
        return (True, "") if ok else (False, f"{head}.{detail}")
    if not isinstance(v, list) or not v:
        return False, f"字段 {head} 缺失或为空（应为非空列表）"
    for item in v:
        if not isinstance(item, dict):
            return False, f"{head} 元素非对象"
        ok, detail = _check_required_field(item, rest)
        if not ok:
            return False, f"{head}[].{detail}"
    return True, ""


def check_required_args(results: list, required_args: list) -> list:
    """必填参数断言：指定工具（可限定 action）的 args 必须含指定字段（支持 list[].key 深路径）。

    背景（2026-09-08 Round2 实拍）：S3 建品 create 只传加工项名称不带价格、缺 specifications
    → DB specs={}、加工项 ¥0.00——工具调用存在但数据正确性不达标，旧评测按工具名判过。
    """
    issues = []
    for req in required_args or []:
        tool = str(req.get("tool", ""))
        action = req.get("action")
        found = None
        for r in results:
            for tc in r.get("tool_calls") or []:
                if tool.lower() not in str(tc.get("name", "")).lower():
                    continue
                a = tc.get("args") or {}
                if action and a.get("action") != action:
                    continue
                found = (r.get("__round"), a)
                break
            if found:
                break
        if found is None:
            issues.append(f"required_args: 未调用 {tool}(action={action})")
            continue
        rnd, args = found
        for f in req.get("fields") or []:
            ok, detail = _check_required_field(args, str(f))
            if not ok:
                issues.append(f"required_args[{tool}.{f}](R{rnd}): {detail}")
    return issues


def check_forbidden_args(results: list, forbidden_args: list) -> list:
    """**禁止参数**断言：指定工具的 args 不得出现指定字段（required_args 的镜像）。

    背景（issue #3270 量化）：C 端 40 条用例里 29 条（72%）只断言「工具被调用」，
    最关键的下限（数据隔离/越权）要求无法机器判定 —— 例如 OR-012 的隔离铁律
    「无论 LLM 通过什么参数传快递单号都必须拒绝」此前只写在自然语义 data_checks
    里（按 acceptance-protocol §1.3 铁律，自然语义不算覆盖，不计分）。

    语义：对每次 `tool`（可限定 `action`）调用，`fields` 里的路径**都不得出现**
    （支持 `list[].key` 深路径，复用 required_args 的路径解析）。

    用例形态：
        forbidden_args:
          - tool: customer_logistics_track
            fields:
              - tracking_number        # 快递单号不得作为查询依据

    采用性与 required_args 对称，便于用例作者理解。
    """
    issues = []
    for spec in forbidden_args or []:
        tool = str(spec.get("tool", ""))
        action = spec.get("action")
        fields = [str(f) for f in (spec.get("fields") or [])]
        if not tool or not fields:
            continue
        for r in results:
            for tc in r.get("tool_calls") or []:
                if tool.lower() not in str(tc.get("name", "")).lower():
                    continue
                args = tc.get("args") or {}
                if action and args.get("action") != action:
                    continue
                for f in fields:
                    present, _detail = _check_required_field(args, f)
                    if present:
                        issues.append(
                            f"forbidden_args[{tool}.{f}](R{r.get('__round')}): "
                            f"该参数禁止出现（越权/数据隔离风险）")
    return issues


def _tool_name_matches(name: str, tool: str) -> bool:
    """工具名是否匹配（精确或 `前缀.工具名` 命名空间形态）。

    刻意**不用子串包含**：`"order_query" in "customer_order_query"` 为真，
    会把 B 端 order_query 的调用算到 customer_order_query 头上（required_args
    的旧实现在这类同尾工具名上会误判）。这里用精确/后缀匹配，语义明确。
    """
    n, t = str(name or "").lower(), str(tool or "").lower()
    if not n or not t:
        return False
    return n == t or n.endswith("." + t)


def check_must_succeed(results: list, must_succeed: list) -> list:
    """写工具**成功**断言：声明的工具必须至少真正成功一次（「调了」≠「成了」）。

    背景（CI 实证 run 34686905546 / 34685247189，issue #3361）：
    CH-010/OR-014/OR-017 三个下单用例的 `order_create` 分别返回
    `tool_execution_failed` / `confirmation_required` / `tool_not_found`，
    用例**照样判 100%**（断言只看望工具名出现在 tool_calls 里），DB 审计里
    `orders` 一条没新增。报告长相是「下单流程正常」，事实是「一单没成交」——
    这正是 §0 复盘「AI 验收全绿、人工验收全是问题」的同款假绿。

    语义（刻意不要求"每次调用都成功"）：
      - 已存在工具结果里**至少一次** `success=true` 即通过 —— 期间被 confirm 门禁
        拦下（`confirmation_required`）属**期望内的安全行为**，只要最终成功就不算违规；
      - 一次都没成功（含从未调用）→ 违规，并把每次尝试的轮次+错误码写进详情，
        工具层失败与模型层漏调在一行里可区分。

    用例形态：
        must_succeed:
          - tool: order_create            # 下单用例必须真的建出订单
          - tool: aftersale_create
            action: create                # 可选：按 args.action 过滤
    """
    issues = []
    for spec in must_succeed or []:
        if isinstance(spec, str):
            spec = {"tool": spec}
        tool = str(spec.get("tool", ""))
        action = spec.get("action")
        if not tool:
            issues.append(f"must_succeed: 配置缺 tool: {spec!r}")
            continue

        attempts: list = []   # [(round, ok, error)]
        for r in results or []:
            rnd = r.get("__round")
            # 调用侧：LLM 是否发起了该工具（按 action 过滤）
            called = False
            for tc in r.get("tool_calls") or []:
                if not _tool_name_matches(tc.get("name"), tool):
                    continue
                if action and (tc.get("args") or {}).get("action") != action:
                    continue
                called = True
                break
            # 结果侧：SSE tool_result 里该工具的成败（结果事件不带 args，无法按 action 过滤
            # —— 所以**指定 action 时只有该轮真的发起了匹配调用，其成功才算数**，
            # 否则同一工具不同 action 的成败会互相顶替：实测 `action: cancel` 的断言被
            # 同工具 `action: create` 的成功"顶过"而假绿）
            matched_results = [
                st for st in _tool_result_status(r.get("tool_results") or [])
                if _tool_name_matches(st.get("tool"), tool)
            ]
            if action and not called:
                continue
            if not called and not matched_results:
                continue
            if not matched_results:
                # 发起了但没有结果事件（流中断/并发丢弃）→ 按未成功记录，不许静默当成功
                attempts.append((rnd, False, "无结果事件"))
                continue
            for st in matched_results:
                attempts.append((rnd, bool(st.get("ok")), st.get("error")))

        if any(ok for _, ok, _ in attempts):
            continue
        if not attempts:
            issues.append(
                f"must_succeed: {tool} 从未被调用 → 没有发生任何写操作"
                "（期望里的工具名出现≠工具真的跑了）")
        else:
            detail = ", ".join(
                f"R{rnd}:{err or 'failed'}" for rnd, _ok, err in attempts
            )
            issues.append(
                f"must_succeed: {tool} 共 {len(attempts)} 次调用**无一成功**（{detail}）"
                "—— 调了 ≠ 成了")
    return issues


def check_forbidden_text(results: list, forbidden_text: list) -> list:
    """final_text 反模式词：任一轮回复含任一禁词 → 违规（幻觉式撤回/报错文案）。

    背景（2026-09-08 验收）：S3 建品 create 成功且 DB 已落库，agent 却因创建后
    即时验证查不到（索引延迟）撤回正确结论、声称"商品尚未真正创建"——工具调用全对
    但用户看到的话是错的（PR-019 用本断言拦截）。
    """
    issues = []
    for w in forbidden_text or []:
        w = str(w)
        for r in results:
            if w in (r.get("final_text") or ""):
                issues.append(f"forbidden_text: 回复含反模式词「{w}」（R{r.get('__round')}）")
                break
    return issues


def check_want_text(results: list, want_text: list) -> list:
    """final_text 正向关键词断言：任一关键词全程未出现 → 违规。

    验收协议 §3.4：关键轮次断言回复内容 = 正向关键词 + 反模式禁词表 双轨。
    forbidden_text 只防「说了不该说的」，防不住「该说的没说」——如兜底话术
    必须含「转人工」出口、写操作完成必须声明成果（订单号/成功），
    缺失即回复不完整，与反模式同等违规。
    """
    issues = []
    all_text = "\n".join(str(r.get("final_text") or "") for r in results)
    for w in want_text or []:
        w = str(w)
        if w not in all_text:
            issues.append(f"want_text: 全程回复未出现正向关键词「{w}」")
    return issues


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


# ── db_verify：落库层验证（acceptance-protocol §3.2 / issue #3056 回归防线）──
# 建品加工项价格曾因 BFF ids/configs 分支被静默丢弃（45→30 且读回退掩盖），
# required_args 只查 create args 层；db_verify 在创建后查 admin-api 落库数据，
# 断言加工项价格 = 用户确认价，双保险（args 层 + 落库层）。

def _evaluate_processing_configs_check(configs: list, check: str) -> tuple[bool, str]:
    """评估落库谓词：'processingItemConfigs.<all|加工项名>.<字段><op><值>'。

    例：processingItemConfigs.all.finalPrice>0
        processingItemConfigs.刺绣工艺.finalPrice==45
    返回 (是否通过, 详情)；字段为空（价格未带入）即失败。
    """
    import re as _re
    m = _re.match(r"^processingItemConfigs\.([^.]+)\.([A-Za-z_]+)(>=|<=|==|!=|>|<)(.+)$", check.strip())
    if not m:
        return False, f"无法解析 db 检查: {check!r}"
    scope, field, op, raw_val = m.groups()
    if not configs:
        return False, f"db 检查: 商品无 processingItemConfigs（{check}）"
    targets = configs if scope == "all" else [c for c in configs if c.get("processingItemName") == scope]
    if not targets:
        return False, f"db 检查: 未找到加工项「{scope}」"
    try:
        val = float(raw_val)
    except ValueError:
        return False, f"db 检查: 值无法解析 {raw_val!r}"
    for c in targets:
        fv = c.get(field)
        if fv is None:
            return False, f"db 检查[{check}]: 字段 {field} 为空（价格未带入？）"
        fv = float(fv)
        ok = {"==": fv == val, "!=": fv != val, ">": fv > val, "<": fv < val,
              ">=": fv >= val, "<=": fv <= val}[op]
        if not ok:
            return False, f"db 检查[{check}]: {c.get('processingItemName')}.{field}={fv} 不满足 {op}{val}"
    return True, ""


async def _fetch_product_configs(token: str, name: str) -> list:
    """按商品名查 admin-api，返回 processingItemConfigs（落库真实数据）。"""
    async with httpx.AsyncClient() as c:
        h = _admin_headers(token)
        r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                        params={"keyword": name, "page": 1, "size": 1}, timeout=15)
        items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
        if not items:
            return []
        pid = items[0]["id"]
        rd = await c.get(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
        return (_safe_json(rd, {}) or {}).get("data", {}).get("processingItemConfigs") or []


# ── amount_verify：下单金额正确性断言（acceptance-protocol §3.2 / issue #3365）──
# 为什么必须有：写工具「成功」只证明订单落库了，**不证明钱算对了**。
# 实证：OR-014 的 agent 在没查过商品的情况下发出确认卡写着「遮光窗帘3米+打孔加工，合计¥95.4」，
# 而该商品真实单价 ¥168/米 —— 这类"钱算错"此前只能靠 DB 审计人眼看（审计只打印金额）。
# 本断言把三个关系变成机器判定：
#   ① unit_price == 商品库单价（**接地**：单价必须来自商品数据，不能凭记忆）
#   ② subtotal   == quantity × unit_price（明细自洽）
#   ③ total      == Σsubtotal + ΣprocessingFee（总额自洽，若结果里带总额）

def _first_successful_call(results: list, tool: str) -> tuple:
    """返回该工具**首个成功调用**的 (轮次, args, result_data)；找不到返回 (None, None, None)。

    成功判定用 tool_result 的 success（与 must_succeed 同源），避免把被门禁拦下的调用当成功。
    """
    for r in results or []:
        calls = [tc for tc in (r.get("tool_calls") or []) if _tool_name_matches(tc.get("name"), tool)]
        if not calls:
            continue
        oks = [st for st in _tool_result_status(r.get("tool_results") or [])
               if _tool_name_matches(st.get("tool"), tool) and st.get("ok")]
        if not oks:
            continue
        return r.get("__round"), (calls[0].get("args") or {}), None
    return None, None, None


async def _fetch_product_price(token: str, name: str) -> float | None:
    """按商品名查商品库单价（接地真值）。"""
    try:
        async with httpx.AsyncClient() as c:
            h = _admin_headers(token)
            r = await c.get(f"{ADMIN_API}/api/admin/products", headers=h,
                            params={"keyword": name, "page": 1, "size": 1}, timeout=15)
            items = (_safe_json(r, {}) or {}).get("data", {}).get("items", [])
            if not items:
                return None
            pid = items[0]["id"]
            rd = await c.get(f"{ADMIN_API}/api/admin/products/{pid}", headers=h, timeout=15)
            data = (_safe_json(rd, {}) or {}).get("data", {}) or {}
            for key in ("price", "basePrice", "base_price"):
                if data.get(key) is not None:
                    return float(data[key])
    except Exception:
        return None
    return None


async def check_amount_verify(token: str, results: list, amount_verify: list) -> list:
    """执行下单金额断言：单价接地 / 小计自洽 / 总额自洽，返回违规列表。

    用例形态：
        amount_verify:
          - tool: order_create
            product_name: "遮光窗帘"        # 用于取商品库单价（接地真值）
            tolerance: 0.01                # 金额容差（默认 0.01）
            checks: [unit_price, subtotal, total]
    """
    issues = []
    for spec in amount_verify or []:
        if not isinstance(spec, dict):
            issues.append(f"amount_verify: 配置非字典: {spec!r}")
            continue
        tool = str(spec.get("tool") or "order_create")
        tol = float(spec.get("tolerance", 0.01))
        checks = [str(x) for x in (spec.get("checks") or ["unit_price", "subtotal", "total"])]
        rnd, args, _ = _first_successful_call(results, tool)
        if args is None:
            issues.append(f"amount_verify: 未找到 {tool} 的成功调用（金额无从核对）")
            continue
        items = args.get("items") or []
        if not isinstance(items, list) or not items:
            issues.append(f"amount_verify[{tool}](R{rnd}): items 为空，金额无从核对")
            continue

        price = None
        if "unit_price" in checks:
            name = str(spec.get("product_name") or "")
            if not name:
                issues.append("amount_verify: 声明了 unit_price 检查但未给 product_name（无法取真值）")
            else:
                price = await _fetch_product_price(token, name)
                if price is None:
                    issues.append(f"amount_verify: 商品「{name}」在商品库查不到单价（fixture 缺数据？）")

        subtotal_sum = 0.0
        processing_sum = 0.0
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                issues.append(f"amount_verify[{tool}](R{rnd}): items[{i}] 非对象")
                continue
            try:
                qty = float(item.get("quantity") or 0)
                up = float(item.get("unit_price") or 0)
                sub = item.get("subtotal")
                sub_f = float(sub) if sub is not None else qty * up
            except (TypeError, ValueError):
                issues.append(f"amount_verify[{tool}](R{rnd}): items[{i}] 数量/单价非数值: {item!r}")
                continue
            pname = str(item.get("product_name") or "")
            pinfo = item.get("processing_info") or {}
            if isinstance(pinfo, dict):
                try:
                    processing_sum += float(pinfo.get("processingFee") or 0)
                except (TypeError, ValueError):
                    pass
            subtotal_sum += sub_f
            if "unit_price" in checks and price is not None:
                # 只核对被声明商品的单价（多商品订单里其它行按各自商品库价另配 spec）
                if not spec.get("product_name") or str(spec["product_name"]) in pname:
                    if abs(up - price) > tol:
                        issues.append(
                            f"amount_verify[{tool}](R{rnd}): 「{pname}」单价 {up} ≠ 商品库 {price}"
                            f"（凭记忆报价？）")
            if "subtotal" in checks:
                if abs(sub_f - qty * up) > tol:
                    issues.append(
                        f"amount_verify[{tool}](R{rnd}): 「{pname}」小计 {sub_f} ≠ 数量{qty}×单价{up}")

        if "total" in checks:
            expected = subtotal_sum + processing_sum
            total = None
            for r in results or []:
                if r.get("__round") != rnd:
                    continue
                for tr in r.get("tool_results") or []:
                    if not _tool_name_matches(tr.get("tool"), tool):
                        continue
                    res = tr.get("result") if isinstance(tr.get("result"), dict) else {}
                    data = res.get("data") if isinstance(res.get("data"), dict) else {}
                    for key in ("totalAmount", "total_amount", "amount"):
                        if data.get(key) is not None:
                            total = float(data[key])
                            break
            if total is None:
                # 结果里没带总额 → 用 args 侧总额兜底；都没有则显式跳过（不静默当通过）
                total = args.get("total_amount")
                total = float(total) if total is not None else None
            if total is None:
                print(f"     ℹ️ amount_verify: {tool} 结果未带总额，跳过 total 检查（单价/小计已查）")
            elif abs(total - expected) > max(tol, 0.05):
                issues.append(
                    f"amount_verify[{tool}](R{rnd}): 总额 {total} ≠ Σ小计{subtotal_sum}+加工费{processing_sum}"
                    f"={expected}")
    return issues


async def check_db_verify(token: str, db_verify: list) -> list:
    """执行 db_verify 断言：fetch 指定资源 → 逐条评估谓词，返回违规列表。"""
    issues = []
    for spec in db_verify or []:
        if not isinstance(spec, dict) or spec.get("fetch") != "product_by_name":
            issues.append(f"db_verify: 不支持的 fetch 配置: {spec!r}")
            continue
        name = spec.get("name", "")
        configs = await _fetch_product_configs(token, name)
        for check in spec.get("checks") or []:
            ok, detail = _evaluate_processing_configs_check(configs, str(check))
            if not ok:
                issues.append(f"db_verify[{name}]: {detail}")
    return issues


# ── post_session：会话关闭后才可观察的落库断言（issue #3357）──
# 长时记忆（user_memories）不是每轮落库：每轮只把候选累积到 session_states，
# **会话关闭时**才 flush 落库（issue #2815 会话末聚合）。因此 run_case 内的
# db_verify 时点太早——必须在 _end_session 之后查询，否则断言的是"抽取还没跑完"
# 这个时序假象，而不是记忆能力本身。
# 查询接口：GET {AI_API}/api/chat/memories（个保法查询权，仅返回当前登录用户自己的记忆）。

def _evaluate_memory_check(memories: list, check: str) -> tuple:
    """评估记忆落库谓词，返回 (是否通过, 详情)。

    支持：
      count>=1 / count==2 / count<=3      条数比较
      has_key:curtain_style               存在该 key 的记忆
      value_contains:奶油风              存在 value 含该子串的记忆
    """
    import re as _re
    c = check.strip()
    m = _re.match(r"^count\s*(>=|<=|==|!=|>|<)\s*(\d+)$", c)
    if m:
        op, raw = m.groups()
        n = int(raw)
        actual = len(memories)
        ok = {">=": actual >= n, "<=": actual <= n, "==": actual == n,
              "!=": actual != n, ">": actual > n, "<": actual < n}[op]
        if not ok:
            keys = [mem.get("key") for mem in memories]
            return False, f"{check} 不满足（实际 {actual} 条，keys={keys}）"
        return True, ""
    if c.startswith("has_key:"):
        key = c.split(":", 1)[1].strip()
        if not key:
            return False, f"无法解析 db 检查: {check!r}（has_key 后缺 key）"
        if any((mem.get("key") or "") == key for mem in memories):
            return True, ""
        keys = [mem.get("key") for mem in memories]
        return False, f"未落库记忆 key={key}（实际 keys={keys}）"
    if c.startswith("value_contains:"):
        sub = c.split(":", 1)[1].strip()
        if not sub:
            return False, f"无法解析 db 检查: {check!r}（value_contains 后缺子串）"
        if any(sub in str(mem.get("value") or "") for mem in memories):
            return True, ""
        vals = [mem.get("value") for mem in memories]
        return False, f"无记忆 value 含「{sub}」（实际 values={vals}）"
    return False, f"无法解析 db 检查: {check!r}"


async def _fetch_user_memories(token: str, agent_type: str = "xiaobu") -> list:
    """查当前登录顾客已落库的长期记忆（agent_type 维度，默认 C 端 xiaobu）。"""
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{AI_API}/api/chat/memories",
                        headers=_chat_headers(token),
                        params={"agent_type": agent_type}, timeout=15)
        payload = _safe_json(r, {}) or {}
        return ((payload.get("data") or {}).get("memories")) or []


async def check_post_session(token: str, post_session: list) -> list:
    """执行会话关闭后的落库断言：fetch 指定资源 → 逐条评估谓词，返回违规列表。"""
    issues = []
    for spec in post_session or []:
        if not isinstance(spec, dict) or spec.get("fetch") != "user_memories":
            issues.append(f"post_session: 不支持的 fetch 配置: {spec!r}")
            continue
        agent_type = spec.get("agent_type") or "xiaobu"
        try:
            memories = await _fetch_user_memories(token, agent_type)
        except Exception as e:
            issues.append(f"post_session[user_memories]: 查询失败 {type(e).__name__}: {e}")
            continue
        for check in spec.get("checks") or []:
            ok, detail = _evaluate_memory_check(memories, str(check))
            if not ok:
                issues.append(f"post_session[user_memories/{agent_type}]: {detail}")
    return issues


async def _close_and_verify_session(case, token: str, r: dict, session_id: str) -> None:
    """关闭用例会话并执行关闭后置断言（失败按用例级失败计入 r）。

    必须在 **run_case 之后、重试分类之前** 调用，使 post_session 断言与普通断言同权：
    失败 → score=0 → 走同一套重试/指纹分类（噪声放行 / 确定性回归显式标注）。
    重试路径同样必须调用（否则重试通过时 post_session 从未被执行 → 假绿）。
    """
    await _end_session(token, r.get("final_session_id") or session_id)
    if not getattr(case, "post_session", None):
        return
    try:
        post_issues = await check_post_session(token, case.post_session)
    except Exception as e:
        post_issues = [f"post_session 执行失败: {type(e).__name__}: {e}"]
    if post_issues:
        print(f"     ❌ post_session 断言未通过: {post_issues}")
        r["score"] = 0.0
        r["passed"] = 0
        r["total"] = max(int(r.get("total") or 0), 1)
        r["failed"] = (r.get("failed") or []) + [
            (pi, "post-session check") for pi in post_issues
        ]


def resolve_auto_respond(results: list, fallback: str, form_values: dict) -> str:
    """`auto_respond` 轮：按**上一轮的待答卡片**自动作答，没有卡片则用 fallback。

    为什么要这个机制（CI 实证 run 34627856207，OR-014 / CH-010）：
    用例的 `user_inputs` 是按**某一种**流程形状写的（先选品→再加工项→再确认），
    而 agent 实际的提问顺序与卡片类型随模型而变（实测 OR-014 第 2 轮先发
    「收货信息 & 颜色」表单、第 3 轮才发加工项 choice 卡）。静态脚本对不上就卡死：
    第 4–8 轮每轮只重复 `customer_address_query`，**order_create 永不发生**。

    真实顾客不会"照着脚本说话"，而是**有什么卡就答什么卡** —— 本函数把这一真实行为
    搬进评测，使用例不再依赖某种特定提问顺序。

    优先级（按"最能推进流程"排序）：confirm > choice > form > fallback。
    - confirm → 回 `confirmValue`（前端点击协议就是发这个值），缺失时用 fallback
    - choice  → 回第一个 option 的 value（等同点击首项）
    - form    → 按 form 卡自己声明的 field key 匹配 `form_values`，拼 `__FORM__|{json}`
                （与 `_auto_fill_form` 同一协议）；无匹配字段 → fallback
    """
    rounds = results or []
    if rounds:
        cards = rounds[-1].get("interactive") or []
        by_comp = {}
        for iv in cards:
            comp = str(iv.get("type") or iv.get("component") or "")
            by_comp.setdefault(comp, iv)

        # 同一张卡**不重复点第二次**（发过的答复不再原样重发）：
        # 模型重发同一张确认卡时，若 harness 逐轮点同一张卡，就会陷入
        # 「模型重发 → 点卡 → 模型再重发」死循环、流程永不前进（CI run 34714932015 实证：
        # CH-010 九轮下来 order_create 三次都被"缺少短信验证码"拒 —— 验证码轮全被点卡吃掉）。
        # 真实顾客点过一次不会再点同一张，而是直接说下一步需要的信息（验证码/补充信息）——
        # 这正是 fallback 的语义，故已发过的答复一律改用 fallback。
        _sent = [str(r.get("user_message") or "").strip() for r in rounds]

        def _already_sent(answer: str) -> bool:
            return bool(answer) and answer.strip() in _sent

        confirm = by_comp.get("confirm")
        if confirm is not None:
            value = str(confirm.get("confirmValue") or "").strip()
            if _already_sent(value):
                return fallback
            return value or fallback

        choice = by_comp.get("choice")
        if choice is not None:
            answer = choice_card_answer(choice)
            if answer and not _already_sent(answer):
                return answer

        form = by_comp.get("form")
        if form is not None:
            filled = {}
            for f in (form.get("formFields") or []):
                key = str(f.get("key") or "")
                if key and key in (form_values or {}):
                    filled[key] = form_values[key]
            if filled:
                import json as _json
                return f"__FORM__|{_json.dumps(filled, ensure_ascii=False)}"

    return fallback


def _auto_fill_form(results: list, values: dict) -> str | None:
    """form 卡自动回填（OR-014 基建缺口）：检测最近一轮 interactive 的 form 卡，
    用 case 声明的字段值构造 `__FORM__|{json}` 回传（FormCard 提交协议，line 98）。

    只填 form 卡声明且 case 提供的字段；缺字段返回 None（调用方 fallback 文本）。
    """
    if not results:
        return None
    for iv in (results[-1].get("interactive") or []):
        comp = str(iv.get("type") or iv.get("component") or "")
        if comp != "form":
            continue
        fields = iv.get("formFields") or []
        filled = {}
        for f in fields:
            key = str(f.get("key") or "")
            if key and key in values:
                filled[key] = values[key]
        if not filled:
            return None
        import json as _json
        return f"__FORM__|{_json.dumps(filled, ensure_ascii=False)}"
    return None


def choice_card_answer(card: dict) -> str:
    """按**前端真实点击协议**构造 choice 卡的答复（issue #3365）。

    协议（`frontend/admin-web/src/components/chat/InteractiveMessage.tsx`，单一事实源）：
      单选：`sendMessage(opt.label || opt.value)`        —— 发**label**（人话），不是内部 id；
      多选：`sendMessage(`${multiSelectSubmitPrefix || '已选加工项：'}${labels.join('、')}`)`
            —— 前缀由后端卡片驱动 + **label** 以「、」连接（一次性提交，不是每点一次发一条）。

    为什么必须对齐（CI run 34715428643 实证）：harness 此前一律回 `options[0].value`
    （内部 id，如 `pi_eval_punch` / `proc_item_pi_eval_punch`）→ 模型看不懂"顾客选了什么"
    → **反复重发同一张加工项卡**，六轮耗尽也没走到 order_create（用例判红，长相像能力问题）。
    """
    options = (card or {}).get("options") or []
    if not options:
        return ""
    first = options[0] if isinstance(options[0], dict) else {}
    label = str(first.get("label") or first.get("value") or first.get("text") or "").strip()
    if not label:
        return ""
    if (card or {}).get("multiSelect"):
        prefix = str((card or {}).get("multiSelectSubmitPrefix") or "已选加工项：")
        return f"{prefix}{label}"
    return label


def _auto_select_first_option(results: list) -> str | None:
    """从最近一轮 interactive choice 卡取"按前端协议"的答复（自动回放选择）。

    ChoiceCard 点击协议见 `choice_card_answer`（单选发 label、多选发 `前缀+label`）；
    choice 卡内容由 LLM 动态生成，评测用静态 user_inputs 无法预知 →
    user_inputs 的 {"auto_select": true} 让 runner 自动作答第一个选项。
    无 choice 卡返回 None（调用方 fallback 文本指代，兼容 agent 文本澄清路径）。
    """
    if not results:
        return None
    for iv in (results[-1].get("interactive") or []):
        comp = str(iv.get("type") or iv.get("component") or "")
        if comp == "choice" and iv.get("options"):
            return choice_card_answer(iv) or None
    return None


def _legacy_auto_select_first_option(results: list) -> str | None:
    """从最近一轮的 interactive choice 卡取第一个 option 的 value（自动回放选择）。

    ChoiceCard 点击协议 = onAction(opt.value)；choice 卡内容由 LLM 动态生成，
    评测用静态 user_inputs 无法预知 → user_inputs 的 {"auto_select": true} 让
    runner 自动回第一个选项。无 choice 卡返回 None（调用方 fallback 文本指代，
    兼容 agent 文本澄清路径）。
    """
    if not results:
        return None
    for iv in (results[-1].get("interactive") or []):
        comp = str(iv.get("type") or iv.get("component") or "")
        if comp == "choice" and iv.get("options"):
            first = iv["options"][0]
            return str(first.get("value") or first.get("text") or "")
    return None


def build_round_trace(results: list) -> list:
    """构造逐轮轨迹：每轮的用户输入形态 / 工具 / 卡 / 回复摘要 / **工具成败**。

    为什么需要（issue #3270 归因层）：扁平 `tool_calls` 只说明「整场用过哪些工具」，
    无法回答**哪一轮走了哪个 Skill**——而「路由错到别的 Skill」与「Skill 没给这个
    工具」在报告里完全同形。实测 CH-012 报告为
        tools=['customer_order_query', 'human_handoff', 'aftersale_query']（4 轮）
    既可能是「R1 被路由到 customer_order（该 Skill 无 aftersale_create）」，
    也可能是「R1 路由正确但 LLM 没建单」—— 两种结论的修复方向完全相反。

    另一条同样致命的模糊：`tool_calls` 记录的是 **LLM 发起的调用**，不代表工具真的做成事。
    写工具被 confirm 门禁拦截时返回 `{"success": false, "error": "confirmation_required"}`，
    但调用名照样出现在 `tool_calls` 里 —— 「调了」与「成了」必须分开记，
    否则「写操作其实一次都没落库」会被读成「写操作正常执行」。
    故每轮另记 `results`：`{tool, ok, error}`（来自 SSE tool_result 事件）。

    设计取舍：本函数**只做事实记录，不做 Skill 推断**。Skill 工具集互不重叠，
    读轨迹者用「工具 → Skill」映射即可反推（该映射见
    docs/testing/xiaobu-eval-tooling.md，并以 app/graph/skills/*.py 为单一事实源）。
    刻意不在此处硬编码 Skill 表：local_runner 是零依赖脚本（CI 只装 httpx），
    不能 import app.*，硬编码副本必然与 skill 定义漂移。

    Returns:
        list[dict]: 每轮 {round, tools, results, cards, interactive, text, error}
    """
    trace: list[dict] = []
    for r in results or []:
        text = r.get("final_text") or ""
        trace.append({
            "round": r.get("__round"),
            # 本轮**实际发出**的用户消息（截断）。为什么必须记：协议轮（auto_respond /
            # auto_select / auto_fill）发出的不是用例静态文本，而是 harness 依上一轮卡片
            # 生成的答复（confirm 卡回 confirmValue、choice 卡回首项、form 回 __FORM__|json）。
            # 写操作被门禁拦（confirmation_required）时，「模型没拿到确认」与「harness 答错了
            # 卡」在旧轨迹里同形 —— 实测 OR-014 无法判断 R4 到底发了什么，归因只能靠猜。
            # 这条字段把「输入侧」也变成证据。
            "user": str(r.get("user_message") or "")[:60],
            "tools": [str(tc.get("name", "")) for tc in (r.get("tool_calls") or [])],
            "results": _tool_result_status(r.get("tool_results") or []),
            "cards": [str(c.get("type") or c.get("card_type") or "") for c in (r.get("cards") or [])],
            "interactive": [
                str(iv.get("type") or iv.get("component") or "")
                for iv in (r.get("interactive") or [])
            ],
            # 截断：轨迹用于归因，不是全文存档（全文另见 final_text / 产物）
            "text": text[:60],
            # 逐轮错误**原文**（issue #3365）：此前轨迹只打 `ERR` 标记，看不到是什么错 ——
            # 实测 CH-010 R6 报错、R7 自愈，归因时完全无从下手（容器日志里也没有对应 traceback）。
            "error": str(r.get("error"))[:120] if r.get("error") else None,
        })
    return trace


def _tool_result_status(tool_results: list) -> list:
    """把 SSE tool_result 事件压成 [{tool, ok, error, digest}]。

    `ok` 判定：结果 dict 的 `success` 为真才算成了 —— 缺失 `success` 视为未知，
    按**不成功**记录（宁可显性可疑，不可静默当成成功）。

    `digest`：结果的**极简载荷摘要**（列表给条数、标量给值），用于回答
    「工具成功了，但它返回了什么」——这是区分下面两种"卡住"的唯一证据：
      ① 工具返回空（`items=0` / `has_address=False`）→ 缺数据，改 fixture；
      ② 工具返回正常数据但 LLM 就是不往下走 → 引导层/模型层，改 prompt 或加代码兜底。
    实测 CH-012：4 轮只打 `customer_order_query`、不建单，无 digest 时无法判断是哪一种。
    """
    out = []
    for tr in tool_results or []:
        if not isinstance(tr, dict):
            continue
        res = tr.get("result") if isinstance(tr.get("result"), dict) else {}
        ok = bool(res.get("success"))
        out.append({
            "tool": str(tr.get("tool", "")),
            "ok": ok,
            "error": None if ok else str(res.get("error") or "no_success_flag"),
            "digest": _result_digest(res),
        })
    return out


# 摘要里最多展示多少个字段 / 每个值多少字符（轨迹是日志，不是全量存档）
_DIGEST_MAX_FIELDS = 6
_DIGEST_MAX_VALUE = 40


def _result_digest(res: dict) -> str:
    """结果的极简摘要：`items=2` / `has_address=True` / `error=xxx` 之类。

    只摘 `data` 的顶层字段（列表给长度、标量给值、嵌套给类型名），
    整体截断 —— 目的是让人**一眼判断"有没有数据"**，不是还原载荷。
    """
    if not isinstance(res, dict):
        return ""
    data = res.get("data")
    parts: list = []
    if isinstance(data, dict):
        for k in list(data.keys())[:_DIGEST_MAX_FIELDS]:
            v = data[k]
            if isinstance(v, (list, tuple)):
                parts.append(f"{k}={len(v)}")
            elif isinstance(v, dict):
                parts.append(f"{k}{{}}")
            elif isinstance(v, (str, int, float, bool)) or v is None:
                text = str(v)
                parts.append(f"{k}={text[:_DIGEST_MAX_VALUE]}")
            else:
                parts.append(f"{k}=<{type(v).__name__}>")
        if len(data) > _DIGEST_MAX_FIELDS:
            parts.append(f"(+{len(data) - _DIGEST_MAX_FIELDS} more)")
    elif isinstance(data, list):
        parts.append(f"list={len(data)}")
    elif data is not None:
        parts.append(str(data)[:_DIGEST_MAX_VALUE])
    if not parts:
        # 没有 data（如纯失败）：至少要能看出失败原因
        parts.append(str(res.get("error") or res.get("message") or "empty")[:_DIGEST_MAX_VALUE])
        return " ".join(parts)[:160]

    # 过长时**逐条丢弃字段**而不是整串硬截 —— 硬截会把末尾的 `(+N more)` 省略提示
    # 一起切掉，读者就分不清「结果只有这几个字段」还是「被截断了」（本函数首版即此 bug）。
    marker = ""
    if len(data) > _DIGEST_MAX_FIELDS:
        marker = f"(+{len(data) - _DIGEST_MAX_FIELDS} more)"
    fields = list(parts)
    while fields:
        candidate = " ".join(fields + ([marker] if marker else []))
        if len(candidate) <= 160:
            return candidate
        fields.pop()
    return (" ".join(parts[:1]) + (" " + marker if marker else ""))[:160]


def format_round_trace(trace: list) -> str:
    """把逐轮轨迹压成一行，供 CI 日志按用例打印。

    失败的工具带 `!error` 后缀 —— 让「调了但没成」在日志里一眼可见
    （confirm 门禁拦截的写工具就长这样）。
    """
    parts = []
    for t in trace or []:
        bits = [f"R{t.get('round')}"]
        # 输入侧证据：本轮实际发出的消息（协议轮的答复尤其关键——见 build_round_trace）
        if t.get("user"):
            bits.append(f"you={t['user']}")
        bits.append("tools=" + (",".join(t.get("tools") or []) or "-"))
        failed = [f"{x['tool']}!{x['error']}" for x in (t.get("results") or []) if not x.get("ok")]
        if failed:
            bits.append("failed=" + ",".join(failed))
        # 成功但"没数据"同样要可见：工具通了却没内容 = 缺数据（改 fixture），
        # 与"有数据但 LLM 不往下走"（改 prompt/代码）是两种完全不同的处置。
        # **必须无条件打印**：CH-012 那种"工具全成功但流程不走"的形态没有 failed 标记，
        # 若只在失败时附带摘要，最能说明问题的那一轮反而看不到证据。
        digests = [
            f"{x['tool']}({x.get('digest')})"
            for x in (t.get("results") or [])
            if x.get("digest")
        ][:3]
        if digests:
            bits.append("data=" + ";".join(digests))
        if t.get("interactive"):
            bits.append("cards=" + ",".join(t["interactive"]))
        if t.get("error"):
            bits.append(f"ERR({t['error'][:60]})")
        parts.append("[{}]".format(" ".join(bits)))
    return " ".join(parts)


async def run_case(case, token: str, session_id: str) -> dict:
    """运行单个评测用例（多轮对话）

    user_inputs 每轮可为 str（纯文本）或 dict（带图消息 / 自动回 choice 卡 / 跨会话）：
      {"text": "看看这个", "images": ["https://...jpg"]}      # 带图消息
      {"auto_select": true}                                    # choice 卡自动回第一个选项
      {"new_session": true, "text": "上次我说过……"}            # 先关闭当前会话再开新会话（跨会话记忆）

    new_session 轮（issue #3357）：发送前先 `_end_session` 关掉当前会话（触发记忆候选
    flush 落库）并新建会话。长期记忆只在**新会话**建立 prompt 时注入，同会话内看不到
    （候选要等会话关闭才落库），所以「老客户偏好识别」这类能力必须跨会话才能判定。
    该轮**必须给 text**（空文本会发出一条空消息，属用例书写错误）。
    """
    results = []
    all_tool_names = []
    session_breaks = 0

    # case 级表单值：所有 `auto_fill` 轮声明的并集 —— auto_respond 轮回答表单时复用，
    # 避免同一份收货信息在用例里重复声明（少一处漂移）
    case_form_values: dict = {}
    for _m in (case.user_inputs or []):
        if isinstance(_m, dict) and isinstance(_m.get("auto_fill"), dict):
            case_form_values.update(_m["auto_fill"])

    for i, msg in enumerate(case.user_inputs):
        images = []
        if isinstance(msg, dict) and msg.get("new_session"):
            await _end_session(token, session_id)
            session_id = await get_or_create_session(token, prefer_new=True)
            session_breaks += 1
        if isinstance(msg, dict) and msg.get("auto_select"):
            # choice 卡自动回放（CU-003 回归防线）：上一轮 agent 下发 choice 卡时，
            # 自动回第一个 option 的 value——ChoiceCard 点击协议 = onAction(opt.value)，
            # 而 card 内容（label/value）由 LLM 动态生成，评测用静态 user_inputs
            # 无法预知（「第一个」/「客户A」文本指代均不稳定）。
            # 无 choice 卡（agent 文本澄清路径）→ fallback「第一个」保持旧语义兼容。
            text = _auto_select_first_option(results) or "第一个"
        elif isinstance(msg, dict) and msg.get("auto_respond"):
            # 合作型用户：优先回答上一轮的待答卡片，无卡则用 fallback 文本
            spec = msg.get("auto_respond") or {}
            if not isinstance(spec, dict):
                spec = {}
            # 允许轮级 form_values 覆盖 case 级 auto_fill 声明
            form_values = dict(case_form_values)
            form_values.update(spec.get("form_values") or {})
            text = resolve_auto_respond(
                results,
                fallback=str(spec.get("fallback") or "确认"),
                form_values=form_values,
            )
        elif isinstance(msg, dict) and msg.get("auto_fill"):
            # form 卡自动回填（OR-014 基建缺口）：agent 发 form 卡（如客户信息）
            # 时用 case 声明的字段值构造 __FORM__|{json} 回传（FormCard 提交协议）。
            text = _auto_fill_form(results, msg.get("auto_fill") or {}) or "确认"
        elif isinstance(msg, dict):
            text = msg.get("text", "")
            images = msg.get("images") or []
        else:
            text = msg
        if isinstance(msg, dict) and msg.get("new_session") and not str(text).strip():
            # 用例书写错误必须响（不是 LLM 波动）：空文本会发出一条空消息，
            # 断言失败详情会指向模型，实际是 harness 输入错误。
            raise ValueError(
                f"用例 {case.id} 第 {i + 1} 轮声明了 new_session 但 text 为空"
                "——跨会话轮必须给出文本"
            )
        r = await send_message(token, session_id, text, images=images)
        r["__round"] = i + 1
        r["__all_tool_names"] = [tc["name"] for tc in r["tool_calls"]]
        all_tool_names.extend(r["__all_tool_names"])
        results.append(r)

        # 简单等待，避免请求过快（可配：EVAL_ROUND_SLEEP，见文件头说明）
        if ROUND_SLEEP:
            await asyncio.sleep(ROUND_SLEEP)

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

    # 跨轮 case 级断言（acceptance-protocol §3.1/§3.4）：时序 + final_text 反模式词
    # getattr 兜底：兼容未重新渲染的旧生成物（字段缺失按空处理，行为不变）。
    case_issues = []
    case_issues += check_order_before(results, getattr(case, "order_before", []) or [])
    case_issues += check_forbidden_text(results, getattr(case, "forbidden_text", []) or [])
    case_issues += check_want_text(results, getattr(case, "want_text", []) or [])
    case_issues += check_required_args(results, getattr(case, "required_args", []) or [])
    case_issues += check_forbidden_args(results, getattr(case, "forbidden_args", []) or [])
    # 写工具成功断言（issue #3361）：期望里有写工具 ≠ 写操作真的发生。
    # 放在 required_args 之后：先证明「参数给对了」，再证明「东西真做出来了」。
    case_issues += check_must_succeed(results, getattr(case, "must_succeed", []) or [])
    # 金额正确性断言（issue #3365）：写成功 ≠ 钱算对（单价接地/小计/总额）
    if getattr(case, "amount_verify", None):
        try:
            case_issues += await check_amount_verify(token, results, case.amount_verify)
        except Exception as e:
            case_issues.append(f"amount_verify 执行失败: {type(e).__name__}: {e}")
    case_issues += check_confirm_loop(results)
    case_issues += check_false_success(results)
    if getattr(case, "db_verify", None):
        try:
            case_issues += await check_db_verify(token, case.db_verify)
        except Exception as e:
            case_issues.append(f"db_verify 执行失败: {e}")
    if case_issues:
        for ci in case_issues:
            failed_expectations.append((ci, "case-level check"))
        score = 0.0

    return {
        "case_id": case.id,
        "title": case.title,
        "difficulty": case.difficulty.value,
        "tags": case.tags,
        "rounds": len(results),
        "tool_calls": all_tool_names,
        # ── 逐轮轨迹（issue #3270 归因层）──
        # 扁平 `tool_calls` 只说「整场用了哪些工具」，无法回答**哪一轮走了哪个 Skill**，
        # 于是「路由错」与「工具没给」在报告里长得一模一样（CH-012 实测：
        # tools=['customer_order_query','human_handoff','aftersale_query'] 4 轮，
        # 究竟 R1 路由到了 customer_order 还是 customer_aftersales 无从判断）。
        # Skill 的工具集互不重叠，因此**逐轮工具名可直接反推该轮 Skill** →
        # 归因从猜升级为证据（路由层 / 工具层可区分）。
        "round_trace": build_round_trace(results),
        "passed": passed_expectations,
        "total": total_exp,
        "score": score,
        "failed": failed_expectations,
        "session_breaks": session_breaks,
        # 跨会话用例（new_session 轮）在 run_case 内换了会话：关闭与后置断言必须针对
        # **最后一个**会话（否则残留 active + 末轮记忆候选不 flush）。
        "final_session_id": session_id,
        "last_error": results[-1].get("error") if results else None,
        "final_text": results[-1].get("final_text", "")[:200] if results else "",
    }

async def run_suite(cases, label: str, classify: bool = True, retry_budget: int = None,
                    concurrency: int = 1):
    """运行一组用例

    classify（默认开，issue #2890 波动分类）：失败用例重试 1 次并判定
    llm-noise / reproducible / unstable / infra（见 _classify_attempts），
    noise 自动放行并记 flake 台账；true regressions 显式标注禁止 rerun 掩盖。

    retry_budget（issue #3361 评测提速）：整跑允许的重试次数上限，None/0 表示不限。
    为什么需要：一次重试 = 整条用例重跑（实测 CH-010/OR-014/OR-017 单条 200-400s，
    4 条失败用例吃掉 19m39s 里的 87%）。失败多的一跑里"逐条重试"是主要成本，
    但它换来的只是**分类标签**，CI 判定（_ci_verdict）只看 score —— 故可设上限：
    前 N 条失败照旧重试/分类，其余直接按首次结果计入（标签标 no-retry-budget），
    报告照样诚实（没有掩盖失败，只是不再为标签支付分钟数）。
    """
    print(f"\n{'='*60}")
    print(f"  {label}: {len(cases)} 个用例" + ("" if classify else "（--no-classify 兼容模式）"))
    print(f"{'='*60}")

    try:
        token = await login()
        print(f"✅ 登录成功")
    except Exception as e:
        print(f"❌ 登录失败: {e}")
        raise RuntimeError(f"登录失败: {e}")

    results = []
    passed_count = 0
    total_score = 0.0
    flake_ledger = []  # 台账：一次运行中「首次失败经分类放行/确认」的用例
    retries_used = 0   # 已消耗的重试次数（受 retry_budget 约束）
    budget_exhausted = False

    async def _pre_clean_for_case(case, gate) -> None:
        """执行用例声明的 pre_clean（写共享数据的**短动作**）。

        issue #3361 提速第三轮：pre_clean 只需**它自身**与其它用例互斥，不必让随后的
        用例主体一起独占（后者会让慢用例变成整跑尾巴）。调用点负责提供独占窗口
        （gate.writer()），且**不能在本任务已持读位时调用** —— 那会死锁。
        """
        for spec in (getattr(case, "pre_clean", None) or []):
            try:
                _msg = await _run_pre_clean(token, spec)
                if _msg:
                    print(f"     🧹 pre_clean: {_msg}")
            except Exception as e:
                print(f"     ⚠️ pre_clean 失败（非致命）: {e}")

    _retry_lock = asyncio.Lock()

    async def _reserve_retry() -> bool:
        """判定并**占用**一个重试额度（原子）。

        并发下不能先看 `retries_used < budget` 再 `+=`：两个用例可能同时看到"还有额度"
        → 预算被突破（多跑整条用例 = 多花分钟数）。加锁后语义与串行一致：
        有额度 → 占用并返回 True；无额度 → 返回 False（不消耗、不重复打印提示）。
        """
        nonlocal retries_used, budget_exhausted
        async with _retry_lock:
            if retry_budget is not None and retries_used >= retry_budget:
                if not budget_exhausted:
                    print(f"     ⏳ 重试预算用尽（{retry_budget} 次）：后续失败用例按首次结果计入"
                          "（不再重跑，标签标 no-retry-budget）")
                    budget_exhausted = True
                return False
            retries_used += 1
            return True

    async def _run_one_case(i: int, case):
        """跑单个用例（会话/重试分类/打印/结果记录）。

        前置的 pre_clean 由调度器在**独占窗口**里先跑（见 `_pre_clean_for_case`）。
        """
        nonlocal budget_exhausted
        if case.skip_reason:
            return None

        # 用例起始时间戳（UTC）——用于把 CI 的**路由 dump**（ai-agent 日志，带时间戳）
        # 按用例切开。没有这个锚点，日志里连续的 intent/route 行无法归属到具体用例，
        # 「某用例被路由到哪个 Skill」就只能靠猜（实测踩到：CH-013/CH-014 交错无法分辨）。
        print(f"  ⏱ {case.id} start={datetime.now(timezone.utc).isoformat(timespec='seconds')}")

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

        # 注：pre_clean 已移到调度器（`_pre_clean_for_case`），因为它的独占窗口必须在
        # 用例主体**之外**获取 —— 若在持读位时再去要写位会死锁（本轮实测踩到：
        # 并行任务持 reader 又请求 writer → 互等 → 跑挂）。

        try:
            r = await run_case(case, token, session_id)
            # 真实 LLM 评测 flaky 容错：失败用例自动重试 1 次（新 session 隔离上下文），
            # 并按指纹分类（issue #2890）：噪声放行 + 记台账；复现型/不稳定型显式标注，
            # 禁止 rerun 掩盖确定性回归。
            classification = "pass"
            # 评测会话清理（协议 §2.2）+ 关闭后置断言（issue #3357）：
            # 长时记忆候选只在会话关闭时 flush 落库（issue #2815），故 user_memories
            # 断言只能在 _end_session **之后**执行；跨会话用例取 run_case 回报的最后
            # 一个会话 id（首个会话已在换会话时关闭）。
            await _close_and_verify_session(case, token, r, session_id)
            # 预算判定与占用由 _reserve_retry 原子完成（并发下不会突破预算）；
            # 短路求值保证「通过用例」不占用额度。
            if r["score"] < 1.0 and classify and not await _reserve_retry():
                # 重试预算用尽：不再重跑（标签显式标注，避免"看起来已验证两遍"）
                classification = "no-retry-budget"
            elif r["score"] < 1.0 and classify:
                retry_sid = await get_or_create_session(token, prefer_new=True)
                r2 = await run_case(case, token, retry_sid)
                r2["retried"] = True
                # 重试同样要关闭 + 跑 post_session：否则重试"通过"是假绿
                await _close_and_verify_session(case, token, r2, retry_sid)
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
            elif r["score"] < 1.0 and await _reserve_retry():
                # --no-classify 兼容模式：旧的无差别单次重试（同样受重试预算约束）
                retry_sid = await get_or_create_session(token, prefer_new=True)
                r2 = await run_case(case, token, retry_sid)
                r2["retried"] = True
                # 与 classify 路径一致：重试会话同样关闭 + 跑 post_session（否则假绿）
                await _close_and_verify_session(case, token, r2, retry_sid)
                if r2["score"] >= 1.0 or r2["score"] > r["score"]:
                    r = r2
            r["classification"] = classification
            # 结果不在此处 append（并发顺序不定）——由调用方按原始用例顺序回填

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
            # 逐轮轨迹：失败用例必打（归因证据），通过用例仅在详细模式打（避免日志膨胀）
            if r.get("round_trace") and (r["score"] < 1.0 or os.environ.get("AGENT_EVAL_TRACE_ALL") == "1"):
                print(f"     trace: {format_round_trace(r['round_trace'])}")
            if r["failed"]:
                for exp, detail in r["failed"][:2]:
                    print(f"     ❌ {exp[:80]}")
                    print(f"        → {detail[:120]}")
            if r["last_error"]:
                print(f"     ⚠️  last_error: {str(r['last_error'])[:100]}")
        except Exception as e:
            print(f"  {icon} ❌ {case.id}: EXCEPTION: {e}")
            exc_record = {
                "case_id": case.id, "title": case.title, "difficulty": case.difficulty.value,
                "tags": case.tags, "rounds": 0, "tool_calls": [], "round_trace": [],
                "passed": 0, "total": 0, "score": 0.0,
                "failed": [(f"EXCEPTION: {e}", "case crashed")],
                "last_error": str(e), "final_text": "", "classification": "error",
            }
            r = exc_record   # 崩溃用例同样交给调用方回填（顺序稳定）
        finally:
            for pid in snapshot_pids:
                await restore_product(token, pid)

        if CASE_SLEEP:
            await asyncio.sleep(CASE_SLEEP)  # rate limit（可配：EVAL_CASE_SLEEP）
        return r

    # ── 并行调度（issue #3361 评测提速第二轮）──
    # 实测（run 34692977836，3 片 × 6 条）：**评测本身**随并行线性变快
    # （单 job 11.6min/18 条 → 各片 5.3/7.2/1.7min/6 条，单条吞吐不变），
    # 但"另起 job"这条路把栈启动从 3.4min 抬到 12min（并发构建/拉镜像被打爆）
    # → 分片整体反而更慢（19.8min vs 15.6min）。结论：**要并行就并行用例、别并行建栈**。
    # 故：单 job + 进程内并发（Semaphore），栈只起一次。
    #
    # 隔离规则：会写**共享资源**的用例走串行道（独占，不与任何用例重叠）——
    #   ① 标签含 id_reuse/update/full_lifecycle（商品改价类，跑前后会快照/恢复同一批商品）；
    #   ② 声明 pre_clean（评测前清理共享数据）；
    #   ③ 声明 post_session（断言的是**用户级**长期状态，运行中会写 user_memories，
    #      而所有用例共用同一个评测顾客）。
    # 其余用例（只读查询 / 各自新建订单工单 / 纯对话）并行安全。
    def _needs_serial_lane(c) -> bool:
        """用例**主体**是否必须独占执行。

        判据（issue #3361 提速第三轮）：实测「独占用例」是**加性**的 —— 它不能与任何用例
        重叠，于是整段评测 = 并行段 + 独占段。C 端 normal 里 OR-014 因 `pre_clean`
        被判独占，一个人跑 ~5.5min，把 10.2min 的评测直接顶到上限。
        而 `pre_clean` 只是"评测前把共享数据清干净"的**短写动作**（product_dedupe 等），
        真正的隔离需求只覆盖这个动作，不覆盖随后的用例主体（主体是下单/查询，各自新建数据）。
        故：pre_clean 改由**独占窗口只包住清理动作**（见 `_run_one_case` 的 pre_clean 块），
        用例主体回到并行道；仍整体独占的只剩：
          - 标签 id_reuse/update/full_lifecycle（商品改价类：跑前快照、跑后恢复同一批商品，
            整个用例期间都持有共享商品状态）；
          - 声明 post_session（断言用户级长期状态，运行中写 user_memories，
            而所有用例共用同一个评测顾客）。
        """
        tags = set(getattr(c, "tags", None) or [])
        return bool(tags & {"id_reuse", "update", "full_lifecycle"}) \
            or bool(getattr(c, "post_session", None))

    indexed = [(i, c) for i, c in enumerate(cases)]
    parallel = [(i, c) for i, c in indexed if not _needs_serial_lane(c)]
    serial = [(i, c) for i, c in indexed if _needs_serial_lane(c)]
    results_by_idx: dict = {}

    gate = None
    if concurrency > 1 and parallel and serial:
        # 读写门：并行用例持读位、串行用例持写位 —— 串行用例**不必等整批跑完**
        # （否则慢串行用例变成整跑尾巴，实测白等 ~7min，见 ConcurrencyGate 注释）
        gate = ConcurrencyGate(concurrency)
        print(f"⚡ 并发执行：{len(parallel)} 条并行（并发度 {concurrency}）"
              f" + {len(serial)} 条串行（独占，读者排空即进入，不阻塞整批）")

        async def _parallel_task(i, c):
            # ① pre_clean（若有）在**独占窗口**里跑 —— 必须在读位之外获取，否则自锁
            if getattr(c, "pre_clean", None):
                async with gate.writer():
                    await _pre_clean_for_case(c, gate)
            # ② 主体并行
            async with gate.reader():
                results_by_idx[i] = await _run_one_case(i, c)

        async def _serial_task(i, c):
            # 独占用例：pre_clean 与主体在**同一个**独占窗口内（不再嵌套获取）
            async with gate.writer():
                await _pre_clean_for_case(c, gate)
                results_by_idx[i] = await _run_one_case(i, c)

        await asyncio.gather(*[_parallel_task(i, c) for i, c in parallel],
                             *[_serial_task(i, c) for i, c in serial])
    elif concurrency > 1 and parallel:
        sem = asyncio.Semaphore(concurrency)
        print(f"⚡ 并发执行：{len(parallel)} 条并行（并发度 {concurrency}）")

        gate = ConcurrencyGate(concurrency)   # 只用它的独占窗口包 pre_clean

        async def _bounded(i, c):
            if getattr(c, "pre_clean", None):
                async with gate.writer():          # 清理动作独占（此时本任务未持读位）
                    await _pre_clean_for_case(c, gate)
            async with sem:
                results_by_idx[i] = await _run_one_case(i, c)

        await asyncio.gather(*[_bounded(i, c) for i, c in parallel])
    else:
        for i, c in indexed:
            results_by_idx[i] = await _run_one_case(i, c)

    # 按**原始用例顺序**回填（并发不改变报告顺序，便于与历史 run 逐条对比）
    results = [results_by_idx[i] for i in sorted(results_by_idx) if results_by_idx[i] is not None]
    passed_count = sum(1 for r in results if r["score"] >= 1.0)
    total_score = sum(r["score"] for r in results)


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

    # ── 工具健康度（基础设施层优先，issue #3270）──
    # 工具大面积失败时，上面那个「均分」衡量的是**后端可用性**，不是 agent 能力。
    # 不显式说出来，读数的人一定会把它当成能力分（本项目实测踩过整整一轮）。
    health = summarize_tool_health(results)
    if health["total"]:
        print(f"\n🔧 工具健康度: {format_tool_health(health)}")
    if health["infra_suspect"]:
        print("\n" + "!" * 68)
        print(f"⚠️  工具失败率 {health['rate']:.0%} ≥ 阈值 "
              f"{_TOOL_HEALTH_INFRA_THRESHOLD:.0%} —— **本轮结果不可用于能力判断**")
        print("    这是**基础设施层**问题（后端 5xx / 熔断 / schema 缺列），不是 agent 能力。")
        print("    先修环境再谈分数：查 admin-api 日志有无 500、schema 是否缺列、熔断是否打开。")
        print("!" * 68)

    return results


# 工具失败率达到该比例即判定「本轮结果不可用于能力判断」——错误信息见
# summarize_tool_health 的 docstring（基础设施层优先原则）。
_TOOL_HEALTH_INFRA_THRESHOLD = 0.20


def summarize_tool_health(results: list) -> dict:
    """汇总工具调用成败，判定本轮结果**能否用于能力判断**。

    为什么必须有（issue #3270 实测踩坑，代价极大）：
    C 端验收栈的 bootstrap schema 缺列（`orders.actual_amount` / `product_skus.color_name`
    …）→ admin-api 查询 500 → 工具返回「服务暂时不可用」(CIRCUIT_OPEN) → **熔断器打开**
    → 后续同类工具全部失败。报告长成「agent 不会下单/不会建售后单」，
    于是我们去改 prompt、改工具、加引导 —— 全都在**错误的层**上忙了一天。
    真因（基础设施层）只有在加了 `data=` 载荷摘要之后才浮出水面。

    `migao-acceptance` 的五层归因（数据/断言/引导/工具/模型）里，**基础设施层必须排在最前**：
    工具本身在报错时，下面四层的结论一个都不成立。本函数把这个判断**自动化**，
    避免下次再靠人眼发现。

    Returns:
        dict: {"total", "failed", "rate", "infra_suspect", "top_failures"}
              - failed 依据 `round_trace[*].results[*].ok`（缺 success 一律记失败）
              - infra_suspect=True 表示失败率超阈值 → 结果不可用于能力判断
    """
    total = failed = 0
    counter: dict = {}
    for r in results or []:
        for rnd in (r.get("round_trace") or []):
            for res in (rnd.get("results") or []):
                total += 1
                if not res.get("ok"):
                    failed += 1
                    key = f"{res.get('tool')}!{res.get('error')}"
                    counter[key] = counter.get(key, 0) + 1
    rate = (failed / total) if total else 0.0
    top = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {
        "total": total,
        "failed": failed,
        "rate": round(rate, 4),
        "infra_suspect": bool(total) and rate >= _TOOL_HEALTH_INFRA_THRESHOLD,
        "top_failures": [{"failure": k, "count": v} for k, v in top],
    }


def format_tool_health(health: dict) -> str:
    """把工具健康度压成可读多行文本（CI 日志用）。"""
    lines = [
        f"工具调用 {health['total']} 次，失败 {health['failed']} 次"
        f"（{health['rate']:.0%}）"
    ]
    for item in health.get("top_failures") or []:
        lines.append(f"    · {item['failure']} × {item['count']}")
    return "\n".join(lines)


def _ci_verdict(results: list) -> tuple[bool, str]:
    """CI 判定（2026-09-08 假绿修复，issue #3062）：空结果 / 存在未通过 → 失败。

    背景：登录失败时 run_suite 曾返回 [] → main 判"全部通过"退出 0 → CI 假绿
    （0 用例执行却报 PASS）。零执行 = 环境/登录失败，必须显式失败。
    """
    if not results:
        return False, "0 个用例执行（疑似登录/环境失败，禁止假绿）"
    failed = [r for r in results if r.get("score", 0) < 1.0]
    if failed:
        return False, f"{len(failed)}/{len(results)} 个用例未通过"
    return True, "全部用例通过"


def write_summary_json(path: str, label: str, shard: str, results: list) -> None:
    """写机器可读的本次运行汇总（issue #3361 分片基建）。

    为什么需要：分片后每个 job 只跑一部分用例，后续步骤（DB 审计、假绿告警）若按
    "全局应有 N 条订单"判断就会误报 —— 审计必须知道**本片是否真的跑了写用例**。
    顺带让"本次跑了什么、结果如何"可被脚本消费（报告/看板/回归对比），不必解析日志。

    字段：
      label/shard/total/passed/failed/avg_score
      order_write_cases：本片声明 must_succeed: order_create 的用例数（0 → 审计不该告警）
      write_cases_ok：其中通过的条数（通过却没落库 = 真假绿）
      cases：[{id, score, classification}]
    """
    import json as _json
    def _declares_order_write(r) -> bool:
        # build_round_trace/结果里不保留 case 声明，故用"该用例的工具列表含 order_create"近似
        return "order_create" in (r.get("tool_calls") or [])
    payload = {
        "label": label,
        "shard": shard or "",
        "total": len(results),
        "passed": sum(1 for r in results if r.get("score", 0) >= 1.0),
        "failed": sum(1 for r in results if r.get("score", 0) < 1.0),
        "avg_score": (sum(r.get("score", 0) for r in results) / len(results)) if results else 0.0,
        "order_write_cases": sum(1 for r in results if _declares_order_write(r)),
        "write_cases_ok": sum(1 for r in results
                              if _declares_order_write(r) and r.get("score", 0) >= 1.0),
        "cases": [
            {"id": r.get("case_id"), "score": r.get("score", 0),
             "classification": r.get("classification", "")}
            for r in results
        ],
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"📊 运行汇总 → {path}（total={payload['total']} passed={payload['passed']} "
              f"order_write_cases={payload['order_write_cases']}）")
    except Exception as e:
        print(f"⚠️ 汇总写出失败（非致命）: {e}")


class ConcurrencyGate:
    """用例并发门（读写语义，issue #3361 提速第二轮）。

    为什么需要：串行道（共享资源用例）如果**等整批并行用例跑完**才开始，慢用例就变成
    整跑的尾巴 —— 实测 C 端 normal：16 条并行（并发度 3）只花 ~3min，而串行道的
    OR-014（含 pre_clean + 重试）一个人在末尾又跑了 ~7min，整段评测 10.6min 白等。

    语义：
      - `reader()`：并行用例（只读/各自新建数据）持位，最多 `max_readers` 个同时进行；
      - `writer()`：串行用例（写共享资源/断言用户级状态）独占 —— **既不与其它用例重叠，
        也不等整批跑完**（当前读者排空即进入）；
      - 写者优先（`_waiting_writers`）：串行用例一到，新读者排队，避免慢串行用例被
        源源不断的并行用例饿死。

    这是"隔离"与"墙钟"同时满足的关键：隔离要求本就是"不与其他用例重叠"，
    而不是"必须在最后跑"。
    """

    def __init__(self, max_readers: int):
        self._max_readers = max(1, int(max_readers))
        self._cond = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @asynccontextmanager
    async def reader(self):
        async with self._cond:
            while self._writer or self._waiting_writers or self._readers >= self._max_readers:
                await self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._cond:
                self._readers -= 1
                self._cond.notify_all()

    @asynccontextmanager
    async def writer(self):
        async with self._cond:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers > 0:
                    await self._cond.wait()
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            async with self._cond:
                self._writer = False
                self._cond.notify_all()


def shard_cases(cases: list, shard: str) -> list:
    """按 `--shard I/N` 切分用例（issue #3361 评测提速）。

    为什么按"用例"分片而不是把并发塞进 runner：评测用例共享同一个 DB（同一批 fixture、
    同一个 debug 顾客），进程内并发会让「谁先写订单/改商品价」变成不确定 ——
    评测工具的可信度建立在**可复现**上，不能为省时间拿掉它。
    分片是**语义不变**的加速：每片跑的是同一套 runner、同一套用例，只是各自一套
    DB/栈（CI 每个 job 自带 docker 栈）→ 天然隔离，墙钟时间近似除以 N。

    切法：`cases[i::N]` 轮转分配（用例耗时未知，轮转比"前 1/N 条"更均衡 ——
    实测慢用例（403s 的 OR-014）与快用例交错分布，顺序切会把慢用例堆在一片）。

    Args:
        cases: 已按 persona/tier 过滤后的用例列表
        shard: "I/N" 形态（I 从 0 开始）；空/None/非法 → 不切片（返回原列表）

    Returns:
        该分片应跑的用例
    """
    if not shard:
        return list(cases)
    try:
        part, total = str(shard).split("/", 1)
        idx, n = int(part), int(total)
    except (ValueError, AttributeError):
        print(f"⚠️ --shard={shard!r} 非法（应为 I/N，如 0/3），忽略分片")
        return list(cases)
    if n <= 1:
        return list(cases)
    if idx < 0 or idx >= n:
        raise ValueError(f"--shard 索引越界: {shard}（I 必须在 [0, {n - 1}]）")
    return list(cases)[idx::n]


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
            order_before=c.get("order_before") or [],
            forbidden_text=c.get("forbidden_text") or [],
            want_text=c.get("want_text") or [],
            required_args=c.get("required_args") or [],
            forbidden_args=c.get("forbidden_args") or [],
            must_succeed=c.get("must_succeed") or [],
            amount_verify=c.get("amount_verify") or [],
            db_verify=c.get("db_verify") or [],
            pre_clean=c.get("pre_clean") or [],
            post_session=c.get("post_session") or [],
        ))
    return cases


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=["smoke", "normal", "full", "adversarial", "case"], nargs="?", default="smoke")
    parser.add_argument("--case-id", help="单条用例 ID（支持新 ID 与 legacy_id，如 OR-002 或 O002）")
    parser.add_argument("--cases", help="用例库目录（cases/*.yml）——提供时直接读 YAML（单一源）")
    parser.add_argument("--concurrency", type=int,
                        default=int(os.environ.get("EVAL_CONCURRENCY", "1")),
                        help="用例级并发度（默认 1=串行）。单 job 内并发：栈只起一次；"
                             "实测评测吞吐随并发线性提升，而「多 job 分片」会被并发建栈拖慢。")
    parser.add_argument("--max-retries", type=int, default=None,
                        help="整跑重试次数上限（默认不限）；失败多的跑可设 3 省分钟数，"
                             "超限的失败用例标 no-retry-budget 而非静默")
    parser.add_argument("--shard", default="",
                        help="分片运行 I/N（如 0/3）——CI 用多 job 并行切片，语义不变只减墙钟")
    parser.add_argument("--no-classify", action="store_true",
                        help="关闭波动分类（issue #2890 兼容开关：恢复旧的无差别单次重试，调试用）")
    args = parser.parse_args()

    if args.cases:
        cases = load_cases_from_yaml(args.cases)
        print(f"📚 用例源: {args.cases}（{len(cases)} 条，YAML 单一源）")
    else:
        cases = ALL_CASES
        print(f"📚 用例源: eval_cases.py（生成物，{len(cases)} 条）")

    # persona 归属 + C 端工具集过滤（issue #2855 / #3266）
    # mibao：跳过 C 端专属（xiaobu）用例
    # xiaobu：#2855 persona 过滤 + #3266 工具集过滤（双端用例须其断言工具全在
    #         小布能力内；B 端管理用例——断言的工具小布没有——一律排除，
    #         防「跑在错误 Agent 上还计分」的假绿）
    before = len(cases)
    cases = select_cases_for_persona(cases, PERSONA)
    if len(cases) != before:
        print(f"🧪 Persona={PERSONA}：用例集过滤后 {len(cases)}/{before} 条"
              f"（排除 {before - len(cases)} 条另一端专属/超出本端工具能力）")

    if PERSONA == "xiaobu":
        # 空集 = 评测静默假绿（issue #3062 同源）——显式报错而非退出 0
        if not cases:
            print("❌ C 端用例集为空（persona/工具集过滤后无剩余）——"
                  "禁止假绿，请检查 .github/cases/ 的 persona 声明与 C 端工具集")
            sys.exit(1)
        print(f"🧪 Persona=xiaobu：C 端用例 {len(cases)} 条")

    def smoke_cases():
        return [c for c in cases if c.difficulty == Difficulty.SMOKE and not c.skip_reason]

    def normal_cases():
        # 每日回归：normal tier（smoke 由 PR gate 跑，adversarial 由每周任务跑）
        return [c for c in cases if c.difficulty == Difficulty.NORMAL and not c.skip_reason]

    def adversarial_cases():
        return [c for c in cases if c.difficulty == Difficulty.ADVERSARIAL and not c.skip_reason]

    def active_cases():
        return [c for c in cases if not c.skip_reason]

    # 分片（issue #3361 评测提速）：在 tier 选择之后切片 —— 保证「每片都只跑自己那份」，
    # 且空片显式报错（0 用例 = 该片白跑，属配置错误，不做静默假绿，同 _ci_verdict 语义）
    if args.shard:
        before_shard = {
            "smoke": smoke_cases, "normal": normal_cases,
            "adversarial": adversarial_cases, "full": active_cases,
        }
        if args.suite in before_shard:
            total_before = len(before_shard[args.suite]())
            sharded = shard_cases(before_shard[args.suite](), args.shard)
            print(f"🧩 分片 {args.shard}：本片 {len(sharded)}/{total_before} 条")
            if not sharded:
                print(f"❌ 分片 {args.shard} 为空（{args.suite} 档共 {total_before} 条）"
                      "—— 空片会静默假绿，请检查分片数与用例数")
                sys.exit(1)
            cases = sharded

    try:
        if args.suite == "case":
            case = next((c for c in cases
                         if c.id == args.case_id or getattr(c, "legacy_id", "") == args.case_id), None)
            if not case:
                print(f"用例 {args.case_id} 不存在")
                sys.exit(1)
            results = await run_suite([case], f"单条 {args.case_id}", classify=not args.no_classify)
        elif args.suite == "smoke":
            results = await run_suite(smoke_cases(), "冒烟", classify=not args.no_classify,
                                      retry_budget=args.max_retries,
                                      concurrency=args.concurrency)
        elif args.suite == "normal":
            results = await run_suite(normal_cases(), "每日回归（normal）",
                                      retry_budget=args.max_retries,
                                      concurrency=args.concurrency)
        elif args.suite == "adversarial":
            results = await run_suite(adversarial_cases(), "对抗")
        elif args.suite == "full":
            results = await run_suite(active_cases(), "全量")
        else:
            results = []
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # CI 判定（issue #3062 假绿修复）：空结果/未通过 → exit 1
    ok, msg = _ci_verdict(results)
    print(f"\n{'✅' if ok else '❌'} {msg}")

    # 机器可读汇总（分片审计/报告消费；env 未设则跳过）
    _sum_path = os.environ.get("AGENT_EVAL_SUMMARY_JSON")
    if _sum_path:
        write_summary_json(_sum_path, args.suite, args.shard, results)

    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    asyncio.run(main())
