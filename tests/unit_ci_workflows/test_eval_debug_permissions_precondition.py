# case_ids: HR-009, HR-010
"""评测可控权限（`X-Debug-Permissions`）的**前置自断言**：判据 = **服务端探针**（issue #4150）。

## 病灶（issue #4150，验证于 `origin/main`）

旧判据是**空断言**：`check_debug_permissions_effective(specs, effective)` 的 `effective`
取自**用例自己的 YAML 声明**（`_case_debug_permissions(case)`），而 `source` 又被本文件
锁成同一字段 ⇒ 两侧同源、**恒等恒绿**。它声称能抓的四类运行期形态（头名拼错 / 值含空格 /
角色写成 customer / 栈里 DEBUG=false）**一个都进不了 `effective`** ⇒ 一条都抓不到
（`migao-acceptance` §1.3.1 的「空断言」形态：真值与被测行为无关）。

## 新判据（本文件锁的不变式，每条都有红证）

判据必须**观测服务端真的给了什么范围**（不是"我声明了什么"）。观测面 = `__PAGE__` 分页协议
（`app/api/chat.py::_handle_page_request` → 直调 `registry.execute_tool`，`ToolContext.permissions`
取自 `current_user.permissions`）：**带本会话身份、零 LLM、零产品改动**。探针工具取自该协议
白名单里唯一**声明了权限码**的工具 `dashboard_stats`（需 `dashboard:view`）—— 其余白名单工具
只按角色层放行、对权限码不敏感，做不了判据。

1. `probe_permission_verdict`：探针那一轮读成 `allowed`（工具真执行了）/`denied`（工具层拒绝）
   /`unknown`（读不出 ⇒ **失败关闭**，不许当通过）；
2. **红线**：声明 `employee:list` 而服务端**回落通配**（探针被放行）⇒ **判红**
   —— 夹具 = 通配回落时服务端真实发出的 SSE 事件形状；
3. **绿线**：同一夹具换成"工具层拒绝"（声明范围真的生效）⇒ 绿（证明判据不恒红）；
4. 声明的码**没生效**（声明含 `dashboard:view` 却被拒）⇒ 判红（少给码 = 误拒，像 agent 不干活）；
5. `X-Debug-Permissions` **压根没下发**（persona 非 mibao / 无 SERVICE_TOKEN）⇒ 判红
   —— 该判据与 `_chat_headers` **同源**（问它自己有没有下发），不复制"什么条件下会下发"的知识；
6. 产品锚点仍在（探针工具 + 权限码 + 分页白名单 + 拒绝文案 + 通配回落），否则判据静默失去目标；
7. HR-009 / HR-010 两条用例都声明了这个前置，且 Case Trust Gate 认账。

## 与 HR-009 的「尝试一次」口径冲突（issue #4150 第 2 项）

`HR-009` 的 `expectations` 要求「越权请求**尝试一次** create」；同批注入面（#4107 F8）却写着
「超出范围的请求：**不要调用工具尝试**」。**本包裁定：以「尝试一次 → 工具层拒绝 → 如实说明 +
给开通路径」为意图行为**（F7 的判据原文只禁「**重复重试**」同一失败调用，未禁首次尝试）：
对齐到注入面会让 HR-009 的**计分通道为空**（`CASE-TRUST-EMPTY-ASSERTION`，静态门禁已实装，
本文件写下这一刻的机械证据）并丢掉「权限拒绝路径」唯一的 LLM 层证据 ⇒ 冲突应由**注入面收窄**
解决（见 `.github/cases/hr.yml` 里 HR-009 的说明 + issue #4147 的评论）。本文件锁住
「HR-009 不得为了变绿而删掉尝试断言 / 效果层断言」这一侧。
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from render_cases import load_case_dicts  # noqa: E402

import assertion_taxonomy as tax  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
TARGET_CASES = ("HR-009", "HR-010")
AI_AGENT = REPO_ROOT / "backend" / "ai-agent-service"

# ── 探针事件的**夹具**（形状取自服务端真实发点，产品锚点见 TestProductAnchors）──
# 通配回落：`check_permission` 放行 ⇒ `_page_stream` 的成功分支发 tool_call + tool_result。
WILDCARD_FIXTURE = {           # ← 「服务端回落通配」的探针观测 = 危险形态
    "tool_calls": [{"name": "dashboard_stats", "args": {"action": "overview"}}],
    "tool_results": [{"tool": "dashboard_stats",
                      "result": {"success": True, "data": {"orders": 3}}}],
    "error": None,
}
# 声明范围生效：`registry.execute_tool` 权限检查不过 ⇒ `_page_stream` 发
# `SSEEvent.error(result.message)`，`result.message` = 「您没有权限使用该功能」。
DENIED_FIXTURE = {
    "tool_calls": [],
    "tool_results": [],
    "error": "{'message': '您没有权限使用该功能'}",
}
# 读不出结局（工具执行失败 / 会话异常）：既没有工具事件、文案也不是权限拒绝。
UNKNOWN_FIXTURE = {
    "tool_calls": [],
    "tool_results": [],
    "error": "{'message': '翻页查询失败，请稍后重试'}",
}


def _runner():
    """加载 runner（CI 的 ci-workflow-tests job 只装 pytest+pyyaml ⇒ 缺 httpx 时注入**抛错**替身）。

    替身一旦被调用就抛错：本文件的探针全部被 monkeypatch 拦下，**不得真实发 HTTP**
    （否则"单测"会依赖活的评测栈 —— 那是评测层的事，不是 L0）。
    """
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _NoHTTP:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _NoHTTP
        sys.modules.setdefault("httpx", stub)
    os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    spec = importlib.util.spec_from_file_location(
        "migao_eval_runner_dbp", REPO_ROOT / "tests" / "agent_eval" / "local_runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cases():
    return {c["id"]: c for c in load_case_dicts(str(CASES_DIR))}


def _install_transport(lr, monkeypatch, fixture, calls=None):
    """把探针的**唯一传输面**换成夹具（会话创建 / 发消息 / 关会话），并记录实际请求。"""
    async def _new_session(token, prefer_new=True, debug_user="", debug_permissions=""):
        (calls if calls is not None else []).append(
            ("session", debug_user, debug_permissions))
        return "sess-probe"

    async def _send(token, session_id, message, images=None,
                    debug_user="", debug_permissions=""):
        (calls if calls is not None else []).append(
            ("send", session_id, message, debug_user, debug_permissions))
        return dict(fixture)

    async def _end(token, session_id, debug_user="", debug_permissions=""):
        (calls if calls is not None else []).append(("end", session_id))
        return None

    monkeypatch.setattr(lr, "get_or_create_session", _new_session)
    monkeypatch.setattr(lr, "send_message", _send)
    monkeypatch.setattr(lr, "_end_session", _end)


def _check(lr, monkeypatch, declared, fixture, source=None, calls=None,
           persona="mibao", service_token="svc-token"):
    """按 HR-009/HR-010 的真实调用形态跑一次前置断言（MIBao persona + SERVICE_TOKEN）。"""
    monkeypatch.setattr(lr, "PERSONA", persona)
    monkeypatch.setattr(lr, "SERVICE_TOKEN", service_token)
    _install_transport(lr, monkeypatch, fixture, calls)
    specs = [{"type": "debug_permissions_effective",
              "source": declared if source is None else source}]
    return asyncio.run(lr.check_debug_permissions_effective("tok", specs, declared))


# ══════════════════════════════════════════════════════════════════════════════
# 一、前置类型有实现（fail-closed，不静默跳过）
# ══════════════════════════════════════════════════════════════════════════════

class TestPreconditionTypeIsImplemented:

    def test_type_is_registered(self):
        lr = _runner()
        assert "debug_permissions_effective" in lr._PRECONDITION_TYPES, (
            "声明了没人实现的 type ⇒ check_precondition_declared 报 config_error"
            "（用例带一个不生效的守卫跑）")

    def test_declared_type_passes_static_check(self):
        lr = _runner()
        spec = [{"type": "debug_permissions_effective", "source": "employee:list"}]
        assert lr.check_precondition_declared(spec) == []

    def test_unknown_type_still_fail_closed(self):
        """兜底分支不得被放宽：未知 type 必须继续报错（防"新类型顺手开个大口子"）。"""
        lr = _runner()
        bad = lr.check_precondition_declared([{"type": "no_such_type", "source": "x"}])
        assert bad and "没有实现" in bad[0]


# ══════════════════════════════════════════════════════════════════════════════
# 二、探针读数（纯函数）：三种结局都可判，读不出 = 失败关闭
# ══════════════════════════════════════════════════════════════════════════════

class TestProbeVerdict:

    def test_wildcard_shape_reads_allowed(self):
        """通配回落时工具**真的执行**（tool_call/tool_result 事件在）⇒ allowed。"""
        lr = _runner()
        verdict, note = lr.probe_permission_verdict(WILDCARD_FIXTURE, "dashboard_stats")
        assert verdict == "allowed" and note

    def test_denied_shape_reads_denied(self):
        lr = _runner()
        verdict, note = lr.probe_permission_verdict(DENIED_FIXTURE, "dashboard_stats")
        assert verdict == "denied" and "没有权限" in note

    def test_unknown_shape_reads_unknown(self):
        """既没工具事件、错误文案也不是权限拒绝 ⇒ unknown（**不许**当"被拒"或"没问题"）。"""
        lr = _runner()
        verdict, _ = lr.probe_permission_verdict(UNKNOWN_FIXTURE, "dashboard_stats")
        assert verdict == "unknown"

    def test_other_tool_events_do_not_count_as_probe(self):
        """别的工具跑成功不算探针放行（防"任意工具事件即 allowed"的宽松读数）。"""
        lr = _runner()
        other = {"tool_calls": [{"name": "order_query", "args": {}}],
                 "tool_results": [{"tool": "order_query", "result": {"success": True}}],
                 "error": None}
        assert lr.probe_permission_verdict(other, "dashboard_stats")[0] == "unknown"

    def test_empty_result_is_unknown(self):
        lr = _runner()
        assert lr.probe_permission_verdict({}, "dashboard_stats")[0] == "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# 三、红线：服务端回落通配 ⇒ 判红（本包的核心红证）；正常 ⇒ 绿
# ══════════════════════════════════════════════════════════════════════════════

class TestAssertionObservesTheServer:

    def test_wildcard_fallback_is_red(self, monkeypatch):
        """**红线**：声明 `employee:list`，服务端却回落通配（探针被放行）⇒ 必红。

        这条就是本包存在的理由：旧判据拿"声明"比"声明"⇒ 恒绿，这一格永远抓不到。
        """
        lr = _runner()
        issues = _check(lr, monkeypatch, "employee:list", WILDCARD_FIXTURE)
        assert issues, "服务端回落通配却判绿 ⇒ 前置断言仍是空断言（假绿）"
        assert "通配" in issues[0] or "生效" in issues[0]

    def test_declared_scope_effective_is_green(self, monkeypatch):
        """**绿线**：声明 `employee:list` 且服务端真的只给了它（探针被拒）⇒ 绿。"""
        lr = _runner()
        assert _check(lr, monkeypatch, "employee:list", DENIED_FIXTURE) == []

    def test_hr010_declared_create_is_green_on_denied_probe(self, monkeypatch):
        """HR-010 的声明（`employee:create`）不含探针码 ⇒ 期望同为"被拒" ⇒ 绿。"""
        lr = _runner()
        assert _check(lr, monkeypatch, "employee:create", DENIED_FIXTURE) == []

    def test_declared_multi_code_is_green_on_denied_probe(self, monkeypatch):
        lr = _runner()
        assert _check(lr, monkeypatch, "employee:list,order:list", DENIED_FIXTURE) == []

    def test_unknown_verdict_is_red(self, monkeypatch):
        """读不出真相 ⇒ 失败关闭（"查不到"不许当"没问题"）。"""
        lr = _runner()
        issues = _check(lr, monkeypatch, "employee:list", UNKNOWN_FIXTURE)
        assert issues and "无法判定" in issues[0]

    def test_declared_probe_code_denied_is_red(self, monkeypatch):
        """声明的码**没生效**（声明含 `dashboard:view` 却被拒）⇒ 红（少给码 = 误拒）。"""
        lr = _runner()
        issues = _check(lr, monkeypatch, "dashboard:view", DENIED_FIXTURE)
        assert issues, "声明的码没生效却判绿 ⇒ 该用例的前提不成立（红/绿不可归因）"

    def test_declared_probe_code_allowed_is_green(self, monkeypatch):
        """正例（证明上一条不是恒红）：声明含探针码且真的放行 ⇒ 绿。"""
        lr = _runner()
        assert _check(lr, monkeypatch, "dashboard:view", WILDCARD_FIXTURE) == []

    @pytest.mark.parametrize("declared", ["", None, "*", " employee:list",
                                          "employee:list,,foo:bar", "EMPLOYEE:LIST"])
    def test_wildcard_and_invalid_declarations_are_red(self, monkeypatch, declared):
        """服务端对非法/空值**整串回落通配**（`_debug_permissions_override`）⇒ 这些声明形态
        在真实栈上必然拿到通配范围 ⇒ 探针被放行 ⇒ 必须判红（不得放过）。"""
        lr = _runner()
        issues = _check(lr, monkeypatch, declared or "", WILDCARD_FIXTURE)
        assert issues, f"回落形态 {declared!r} 被判绿 ⇒ 前置断言无效"

    def test_whitespace_variant_never_compares_equal(self, monkeypatch):
        """声明里的空白**不得被 strip 掉**：服务端不 normalize（含空白 = 非法 = 通配回落），
        客户端若"顺手修好"就会把这一格判绿（假绿）。"""
        lr = _runner()
        issues = _check(lr, monkeypatch, " dashboard:view", WILDCARD_FIXTURE)
        assert issues, "客户端 strip 了声明值 ⇒ 与服务端口径分叉（服务端会回落通配）"

    def test_header_not_sent_is_red(self, monkeypatch):
        """`X-Debug-Permissions` **压根没下发** ⇒ 判红（前提不可能成立）。

        判据与 `_chat_headers` **同源**：直接问它会不会下发该头（不复制"什么条件下下发"）。
        """
        lr = _runner()
        issues = _check(lr, monkeypatch, "employee:list", DENIED_FIXTURE,
                        persona="xiaobu")
        assert issues and "下发" in issues[0]

    def test_missing_service_token_is_red(self, monkeypatch):
        """无 SERVICE_TOKEN（本地真实登录路径）时同样不下发该头 ⇒ 判红。"""
        lr = _runner()
        issues = _check(lr, monkeypatch, "employee:list", DENIED_FIXTURE,
                        service_token="")
        assert issues and "下发" in issues[0]

    def test_empty_source_is_red_without_probing(self, monkeypatch):
        """声明了 type 却没说范围 ⇒ 报错（且**不发请求**：没有可判的东西）。"""
        lr = _runner()
        calls = []
        issues = _check(lr, monkeypatch, "employee:list", DENIED_FIXTURE,
                        source="", calls=calls)
        assert issues and "source" in issues[0]
        assert calls == [], "缺 source 还去发探针 ⇒ 无意义请求"

    def test_probe_uses_the_page_protocol_and_the_case_permissions(self, monkeypatch):
        """探针必须**真的**用「本用例声明的权限头」走 `__PAGE__` 直调（否则观测的不是被测前提）。"""
        lr = _runner()
        calls = []
        _check(lr, monkeypatch, "employee:list", DENIED_FIXTURE, calls=calls)
        sends = [c for c in calls if c[0] == "send"]
        assert len(sends) == 1, f"探针应恰好发一次（实际 {calls}）"
        _, sid, message, _du, perms = sends[0]
        assert message.startswith("__PAGE__|"), message
        assert "dashboard_stats" in message, message
        assert perms == "employee:list", f"探针没带用例声明的权限头：{perms!r}"
        assert sid == "sess-probe"
        assert [c for c in calls if c[0] == "end"], "探针会话必须关闭（不留残留会话）"

    def test_probe_params_are_accepted_by_the_tool(self, monkeypatch):
        """探针载荷必须过工具自己的入参契约（`dashboard_stats.parameters.required=[action]`）
        —— 否则工具在**健康栈**上也会失败，判据退化成恒红。"""
        lr = _runner()
        calls = []
        _check(lr, monkeypatch, "employee:list", DENIED_FIXTURE, calls=calls)
        message = [c for c in calls if c[0] == "send"][0][2]
        import json as _json
        params = _json.loads(message.split("|", 2)[2])
        assert params.get("action") == "overview", params


# ══════════════════════════════════════════════════════════════════════════════
# 四、产品锚点：判据的目标（探针工具 / 权限码 / 白名单 / 拒绝文案 / 回落）必须仍在
#     —— 任一漂移都让判据静默失去目标（"基于错误真相模型写出的护栏"）
# ══════════════════════════════════════════════════════════════════════════════

class TestProductAnchors:

    def _src(self, rel):
        return (AI_AGENT / rel).read_text(encoding="utf-8")

    def test_probe_tool_declares_the_probe_permission(self):
        src = self._src("app/tools/dashboard_stats.py")
        assert 'required_permissions = ["dashboard:view"]' in src, (
            "探针工具的权限码变了/没了 ⇒ 探针不再观测权限范围"
            "（无 required_permissions 时走角色层，对权限码不敏感）")

    def test_probe_tool_is_in_the_page_whitelist(self):
        src = self._src("app/api/chat.py")
        assert '"dashboard_stats"' in src, "探针工具不在分页协议白名单里 ⇒ 探针恒被判「不支持」"

    def test_page_path_executes_with_the_user_permissions(self):
        """探针的观测面成立的前提：分页协议直调工具、且 `permissions` 取自**当前用户**。"""
        src = self._src("app/api/chat.py")
        assert "permissions=getattr(current_user, \"permissions\", None) or []" in src, (
            "分页协议的 ToolContext 不再带用户权限码 ⇒ 探针观测不到权限范围")

    def test_denial_message_is_emitted_as_an_sse_error(self):
        """拒绝文案要能被 runner 读到：`registry` 定文案、分页路径把它作为 SSE error 发出。"""
        assert "您没有权限使用该功能" in self._src("app/tools/registry.py"), (
            "权限拒绝文案变了 ⇒ 探针的「被拒 vs 执行失败」消歧失效（改文案须同步 runner 锚点）")
        assert "SSEEvent.error(result.message" in self._src("app/api/chat.py"), (
            "分页路径不再把失败 message 作为 SSE error 发出 ⇒ 探针读不到结局")

    def test_wildcard_fallback_still_exists(self):
        """判据守的就是这一格：非法/缺省值**整串回落通配**。"""
        src = self._src("app/utils/auth.py")
        assert 'or ["*"]' in src, (
            "服务端不再回落通配 ⇒ 本判据守的形态变了（重新设计判据，别留着恒绿的守卫）")


# ══════════════════════════════════════════════════════════════════════════════
# 五、负效果断言（`employee_absent`）：形状 fail-closed
# ══════════════════════════════════════════════════════════════════════════════

class TestEmployeeAbsentShapeIsFailClosed:

    def test_missing_locator_is_config_error(self):
        """既无 name 也无 phone ⇒ 定位不到对象 ⇒ 必须报配置错误，不得"查不到就算过"。"""
        import asyncio
        lr = _runner()
        issues = asyncio.run(lr.check_db_verify("tok", [{"fetch": "employee_absent"}]))
        assert issues, "缺定位键却判过 ⇒ 这条断言永远绿（空断言）"
        assert "employee_absent" in issues[0]

    def test_supported_fetch_vocabulary_includes_absent(self):
        """L0 形状守卫的白名单必须同步（否则 CI 零依赖 job 会判"不支持的 fetch"）。"""
        src = (REPO_ROOT / "tests" / "unit_ci_workflows"
               / "test_assertion_specs_wellformed.py").read_text(encoding="utf-8")
        assert "employee_absent" in src, (
            "test_assertion_specs_wellformed.SUPPORTED_DB_FETCH 未收录 employee_absent"
            " ⇒ 用例里写了它会被 L0 判「不支持的 fetch」")


# ══════════════════════════════════════════════════════════════════════════════
# 六、真实用例：两条都声明了，且门禁认账
# ══════════════════════════════════════════════════════════════════════════════

class TestRealCasesDeclareThePrecondition:

    def test_both_cases_declare_effective_scope(self):
        by = _cases()
        for cid in TARGET_CASES:
            specs = by[cid].get("precondition") or []
            hits = [s for s in specs if isinstance(s, dict)
                    and s.get("type") == "debug_permissions_effective"]
            assert hits, f"{cid} 未声明权限范围前置：{specs}"
            assert hits[0].get("source") == by[cid].get("debug_permissions"), (
                f"{cid} 的前置 source 必须与用例声明的 debug_permissions **同源**"
                f"（否则探针期望与真实下发的头不是同一件事）："
                f"{hits[0]} vs {by[cid].get('debug_permissions')!r}")

    def test_gate_rule_f_accepts_the_declaration(self):
        """门禁 F 条必须认这个形态（否则 CI 仍红）。"""
        by = _cases()
        for cid in TARGET_CASES:
            ok, how = tax.declares_precondition(by[cid])
            assert ok, f"{cid} 的 precondition 声明未被门禁认账（{how}）"

    def test_hr009_has_negative_effect_assertion(self):
        """HR-009（被拒绝的写）必须有**负效果**断言：确认员工没有落库。"""
        c = _cases()["HR-009"]
        absent = [s for s in (c.get("db_verify") or [])
                  if isinstance(s, dict) and s.get("fetch") == "employee_absent"]
        assert absent, f"HR-009 缺效果层断言（写类用例不得只有「调用了」级断言）：{c.get('db_verify')}"
        assert tax.has_effect_assertion(c), "门禁的效果层判据仍不认它 ⇒ CI 仍红"

    def test_hr009_declares_self_clean(self):
        c = _cases()["HR-009"]
        assert c.get("pre_clean"), "HR-009 未声明自清理（门禁 b 条）"
        assert tax.self_clean_evidence(c) == "pre_clean", (
            "自清理证据必须是**强**形态 pre_clean（namespaces 是弱证据，不解决重试前置）")


# ══════════════════════════════════════════════════════════════════════════════
# 七、HR-009 的「尝试一次」口径（issue #4150 第 2 项）：冲突在**注入面**侧解决
# ══════════════════════════════════════════════════════════════════════════════

class TestHR009AttemptRequirementIsNotDropped:

    def test_hr009_keeps_a_scoring_attempt_assertion(self):
        """HR-009 必须保留「尝试一次」这条**计分**断言。

        为什么不能"为了与注入面对齐"删掉它：删了 ⇒ `scoring_assertion_count == 0`
        ⇒ 静态门禁判 `CASE-TRUST-EMPTY-ASSERTION`（恒绿形态，门禁已实装、且新增违规阻塞合并），
        且「权限拒绝路径」唯一的 LLM 层证据消失。故冲突只能由**注入面收窄**（#4147）解决。
        """
        c = _cases()["HR-009"]
        assert c.get("expectations"), f"HR-009 的计分断言被删空：{c.get('expectations')}"
        assert tax.scoring_assertion_count(c) > 0, (
            "计分断言数 = 0 ⇒ 该用例的 score 通道恒为 1.0（CASE-TRUST-EMPTY-ASSERTION）")
        assert "create" in str(c.get("expectations")), (
            f"HR-009 的计分断言不再是「越权 create 尝试一次」：{c.get('expectations')}")

    def test_hr009_keeps_must_fail_on_the_denied_write(self):
        """与"尝试一次"**并存**的负向断言：任何一次 create 都不得成功（跨轮机器判定）。"""
        c = _cases()["HR-009"]
        must_fail = [m for m in (c.get("must_fail") or [])
                     if isinstance(m, dict) and str(m.get("tool")) == "employee_manage"]
        assert must_fail, f"HR-009 缺「越权写不得成功」的跨轮断言：{c.get('must_fail')}"
        assert "create" in str(must_fail[0].get("action")), must_fail

    def test_case_records_the_product_side_channel(self):
        """用例必须**登记**冲突的产品侧归属（否则下一个人只看到一条"莫名红"的用例）。"""
        c = _cases()["HR-009"]
        log = str(c.get("merge_log") or "")
        assert "#4147" in log, (
            "HR-009 未在用例内登记「注入面收窄」的产品侧归属（#4147）"
            f"：{log[:120]!r}")

# ══════════════════════════════════════════════════════════════════════════════
# 八、配对隔离与登记（issue #4150 第四轮：真跑实测 run 35264687083 的两个真缺口）
# ══════════════════════════════════════════════════════════════════════════════

class TestThePairIsIsolatedAndRegistered:
    """HR-009（拒绝半）与 HR-010（允许半）共用**同一个员工身份**（李四/13800009999）：
    前者断言它**不存在**、后者把它**创建出来**。两个真缺陷都由"共用 + 零隔离"产生。
    """

    IDENTITY_NAME = "李四"
    IDENTITY_PHONE = "13800009999"

    def test_both_cases_declare_the_shared_identity_namespace(self):
        """**隔离归零的红证**：`namespace_conflict_groups` 只收 ≥2 条声明的键
        （#3835 实证）⇒ 单侧声明 = 零隔离 ⇒ HR-010 的产物会让 HR-009 的"不存在"断言
        恒红/闪烁，且报告读成"越权落库"（真跑实测 run 35264687083 的形态：
        `db_verify[employee_absent]: 员工「李四」已落库`）。两侧都必须声明同一对键。
        """
        by = _cases()
        for cid in TARGET_CASES:
            ns = by[cid].get("namespaces") or []
            assert f"employee_name:{self.IDENTITY_NAME}" in ns, (
                f"{cid} 未声明共享身份的命名空间 ⇒ 配对零隔离（HR-010 造、HR-009 断言不存在）：{ns}")
            assert f"employee_phone:{self.IDENTITY_PHONE}" in ns, f"{cid} 缺少手机号键：{ns}"

    def test_pair_actually_lands_in_one_conflict_group(self):
        """判据用 runner 自己的分组函数（**单一真相源**）——不是「声明里看起来有隔离」。

        按鸭子类型喂 `id`/`namespaces`（`namespace_conflict_groups` 只读这两处）：
        不依赖生成物 dataclass，用例 YAML 的声明就是唯一输入。
        """
        lr = _runner()
        by = _cases()
        pair = [types.SimpleNamespace(id=cid, namespaces=by[cid].get("namespaces") or [])
                for cid in TARGET_CASES]
        groups = lr.namespace_conflict_groups(pair)
        assert groups.get(f"employee_phone:{self.IDENTITY_PHONE}") == list(TARGET_CASES), (
            f"两条**没有**进同一争用组 ⇒ 隔离归零：{groups}")
        assert all(lr.needs_serial_lane(c, set(TARGET_CASES)) for c in pair), (
            "撞车用例必须走独占道（needs_serial_lane）")

    def test_hr009_absence_locator_is_that_same_identity(self):
        """三段必须说的是**同一个对象**：HR-009 的 `db_verify[employee_absent]` 定位键
        == 两条的命名空间声明 == HR-010 的落库期望。否则"不存在"这句话守的不是它自己的靶子
        （§18.3 不可变引用：定位必须用手机号这类不可变键）。"""
        by = _cases()
        absent = [s for s in (by["HR-009"].get("db_verify") or [])
                  if isinstance(s, dict) and s.get("fetch") == "employee_absent"][0]
        assert absent.get("phone") == self.IDENTITY_PHONE, absent
        assert absent.get("name") == self.IDENTITY_NAME, absent
        wait = [s for s in (by["HR-010"].get("db_verify") or [])
                if isinstance(s, dict) and s.get("fetch") == "employee"][0]
        assert wait.get("name") == self.IDENTITY_NAME, wait
        assert (wait.get("expect_fields") or {}).get("phone") == self.IDENTITY_PHONE, wait

    def test_runnable_pair_must_cite_the_product_dependency(self):
        """登记纪律：只要 `skip_reason` 非空（本包按真跑实测登记了这两条），它必须**点名**
        产品侧归属（#4147）与摘除判据的入口 —— 否则下一个人只看到"这两条不跑"，无从接手。
        （用例被 un-skip（skip_reason 清空）后本判据自动失效，不会挡住修复。）
        """
        for cid, c in _cases().items():
            reason = str(c.get("skip_reason") or "")
            if cid not in TARGET_CASES or not reason:
                continue
            assert "#4147" in reason, (
                f"{cid} 的 skip_reason 未点名产品侧归属（#4147）：{reason[:120]!r}")
            assert "un-skip" in reason or "摘掉" in reason, (
                f"{cid} 的 skip_reason 未写摘除判据（怎么才算修好）：{reason[:120]!r}")
