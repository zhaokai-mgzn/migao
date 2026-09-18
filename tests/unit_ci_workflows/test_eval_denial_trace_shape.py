# case_ids: HR-009, HR-010
"""权限拒绝的**归因留痕**：调用留下「工具名 + action + 结果码」的可判读形状（issue #4197 第 3 项）。

## 病灶（值级证据，issue #4197 第三节）

判定 run `35295494688`（@`d5bca241`）的 HR-010 首跑 trace 逐字只有：

```
tools=['role_manage','employee_manage','validate_input','interact']
failed=role_manage!权限不足,employee_manage!权限不足
```

被拒那一次 `employee_manage` 的 **action 未落盘**（runner 的 `write_args` 只收写工具名单，
`employee_manage` 不在其中）⇒ 只能给到**存在性级**结论（"它调过 employee_manage 且失败了"），
无法断言"它调的是 `list`（读）"、也无法断言"失败是权限类而非参数/网络"（`#3823` 族缺口：
证据等级不得越级 —— 要"值相等"级结论就得先确认 runner 落盘了 tool args）。

## 本文件锁什么（**只加证据，不改判定口径**）

`_tool_result_status` 的结果条目新增两个字段，`_failure_shape` 把它们渲染进轨迹：

| 字段 | 取值 | 为什么 |
|---|---|---|
| `action` | 与本次结果**配对的那一次调用**的 `action`/`operation`/`op` | 配对口径与服务端 `_pending_calls` **同款**：同名调用**队列队首**（按到达顺序），不是取最后一条 |
| `error_code` | 结果 dict 里的**结构化码**（权限拒绝 = `PERMISSION_DENIED`） | 文案会变（"权限不足"→"您没有权限使用该功能"），**码是契约** ⇒ 值级可分"权限拒绝"与"其它失败" |

渲染形状 = `工具名{action=…}!error[CODE]`，例：
`employee_manage{action=list}!权限不足[PERMISSION_DENIED]`。缺 `action`/码时**不填占位符**
（没观测到就不写 —— 占位符 = "看起来有证据"的假证据）。

## 红证（每条断言都会红；回退修复 ⇒ 判据必红）

| 断言 | 回退后的红形态 |
|---|---|
| `action` 落盘（含**读**工具） | 回退 = 条目无 `action` 键 ⇒ `KeyError: 'action'` |
| 同名多次调用按**队首**配对 | 回退（或改成"取最后一条"）⇒ 第一个结果的 action 算成 `create` ⇒ 断言值不等 |
| `error_code` 落盘 + **不从文案反推** | 回退 = 无 `error_code` 键 ⇒ `KeyError`；从文案反推 ⇒ 负例（文案含码但无字段）会算出码 ⇒ 断言值不等 |
| 形状渲染 | 回退 = 轨迹里没有 `{action=` 与 `[PERMISSION_DENIED]` ⇒ 断言 not-in 命中 |
| **只加证据**（旧字段逐字不变） | 旧字段与**独立逐字副本** `_legacy_tool_result_status` 整字典比对；改旧字段即红 |

## 为什么用单测而不是真实链路

真实链路要 docker 栈 + 真实 LLM（本机没有；PR 层真实 LLM 已按 #4034 裁定关闭）。
本改动是**纯序列化/渲染**（`build_round_trace` → `format_round_trace` 的字段增补），
不含任何判定逻辑 —— `run_case` 产出的 `results` 结构就是全部输入契约（`migao-dev-flow` §16.1：
能下层不上层）。**行为复核并入下一次全量档**（issue #4197 第五节）。

⚠️ 本目录在 CI 只 `pip install pytest pyyaml`，而 `local_runner` 有模块级 `import httpx`
→ 用下方 `_load_runner()` 的最小替身（与 `test_eval_runner_readback_scope.py` 同形）。
"""
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，且一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()

AI_AGENT = REPO_ROOT / "backend" / "ai-agent-service"

#: 产品侧常量值（`app/tools/base.py::PERMISSION_DENIED_CODE`）—— 锚点由
#: `TestTheCodeIsTheProductsConstant` 逐字核源码，漂移即红。
DENIED_CODE = "PERMISSION_DENIED"

#: 工具层权限拒绝的真实回显形状（`_denial_result` → `_execute_tool_safe` 出口字典）。
DENIED_RESULT = {
    "success": False,
    "data": None,
    "error": "权限不足",
    "message": "您没有权限执行该操作",
    "suggestion": "请联系管理员在「角色管理」中开通该权限",
    "error_code": DENIED_CODE,
}


def _denied(**over):
    out = dict(DENIED_RESULT)
    out.update(over)
    return out


def _round(calls, results):
    """构造一轮 `results` 条目（calls: [(tool, args)]，results: [(tool, result_dict)]）。"""
    return {
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [{"tool": t, "result": r} for t, r in results],
    }


def _status(r):
    """按 `build_round_trace` 的同款调用取状态条目（**两条**参数都传）。"""
    return lr._tool_result_status(r.get("tool_results") or [], r.get("tool_calls") or [])


# ── 改造前的**独立逐字副本**（红证 + "只加证据"的对照基线）─────────────────────
# 刻意不复用 `_tool_result_status`（否则两边同源 ⇒ 改了旧字段一起变 ⇒ 闸门失效）；
# 只复用 `_result_digest` —— 该 helper 不属本单改动范围（其自身漂移不在本闸门职责内）。
def _legacy_tool_result_status(tool_results: list) -> list:
    """issue #4197 **之前**的 `_tool_result_status` 逐字副本（无 action / error_code）。"""
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
            "digest": lr._result_digest(res),
        })
    return out


def _legacy_failure_shape(entry: dict) -> str:
    """issue #4197 **之前**的失败渲染逐字副本：`工具名!error`（无 action、无码）。"""
    return f"{entry['tool']}!{entry['error']}"


# ══════════════════════════════════════════════════════════════════════════════
# 一、被拒的那次调用必须留下 action（**读工具也记** —— 这正是 #4197 的证据缺口）
# ══════════════════════════════════════════════════════════════════════════════

class TestDenialCallLeavesItsAction:
    """`employee_manage(action=list)` 被权限层拒绝 ⇒ 轨迹必须能读出"它调的是 list"。"""

    def test_read_tool_denial_records_its_action(self):
        """HR-010 首跑的真实形态：读 action 被拒，action 必须落盘（改前只留工具名）。"""
        r = _round([("employee_manage", {"action": "list"})],
                   [("employee_manage", _denied())])
        entry = _status(r)[0]
        assert entry["action"] == "list", (
            f"读工具被拒时 action 必须落盘（#4197 的证据缺口）：{entry}")
        assert entry["error_code"] == DENIED_CODE, entry
        # 红证：改前的条目**没有** action 键 ⇒ 上面的断言在回退后是 KeyError（红）。
        assert "action" not in _legacy_tool_result_status(r["tool_results"])[0], (
            "夹具失效：改前的条目本就带 action，则本判据不是 #4197 的红证")

    def test_action_key_precedence_matches_the_page_guard(self):
        """`action` / `operation` / `op` 三选一，且**优先级**与服务端分页守卫逐字同款。

        读取侧另立一套口径必然漂移（#3681 的 action 对齐纪律）⇒ 这里同时锁**实现**
        与**产品源码锚点**（守卫改键序 ⇒ 本测试红）。
        """
        assert lr._call_action({"action": "list"}) == "list"
        assert lr._call_action({"operation": "detail"}) == "detail"
        assert lr._call_action({"op": "refund"}) == "refund"
        assert lr._call_action({"action": "list", "operation": "detail", "op": "refund"}) == "list", (
            "优先级必须与 `_page_action_allowed` 一致：action > operation > op")
        assert lr._call_action({"action": "", "operation": "detail"}) == "detail", (
            "空串按**缺席**处理（守卫用 `or` 链，空串会继续往下取）")
        assert lr._call_action({}) == ""
        assert lr._call_action(None) == ""
        src = (AI_AGENT / "app" / "api" / "chat.py").read_text(encoding="utf-8")
        assert 'params.get("action") or params.get("operation") or params.get("op")' in src, (
            "分页守卫的 action 取值口径变了 ⇒ runner 的 `_call_action` 与之分叉（#3681 复发）")

    def test_action_is_not_invented_when_no_call_is_paired(self):
        """配对不到调用（结果由代码收口执行 / 调用事件缺失）⇒ `action` 留空，**不臆造**。"""
        r = _round([], [("employee_manage", _denied())])
        assert _status(r)[0]["action"] == ""
        # 结果里自带的结构化码与调用无关，仍须保留。
        assert _status(r)[0]["error_code"] == DENIED_CODE

    def test_same_name_calls_pair_by_queue_head_not_by_last(self):
        """同名多次调用：结果按**到达顺序**配队首（与服务端 `_pending_calls` 同款）。

        取最后一条会把"第一次调 list"配成"第二次调 create" —— 归因直接错位
        （服务端 `chat.py` 的 `_pending_calls` 注释点名了这条：结果与调用按到达顺序一一配对）。
        """
        r = _round(
            [("employee_manage", {"action": "list"}),
             ("employee_manage", {"action": "create"})],
            [("employee_manage", _denied(error="查询被拒")),
             ("employee_manage", _denied(error="写入被拒"))],
        )
        observed = [x["action"] for x in _status(r)]
        assert observed == ["list", "create"], f"配对口径必须是队首：{observed}"
        # 负例夹具（证明上面不是恒绿）：若按"取最后一次同名调用"配对，会算成 create/create
        # —— 判据必须能把这两种形态分开。
        last_wins = ["create", "create"]
        assert observed != last_wins, (
            "夹具失效：队首配对与取末条配对给出同一结果，则本判据不具判别力")

    def test_legacy_call_sites_still_work_with_one_argument(self):
        """既有 8 处 `_tool_result_status(results)` 单参调用不得崩（新参数有默认值）。"""
        r = _round([("employee_manage", {"action": "list"})],
                   [("employee_manage", _denied())])
        single = lr._tool_result_status(r["tool_results"])
        assert single[0]["tool"] == "employee_manage"
        assert single[0]["action"] == "", (
            "不传 tool_calls ⇒ 无从配对 ⇒ 留空（旧调用点行为不变）")


# ══════════════════════════════════════════════════════════════════════════════
# 二、结果码是**结构化契约**，不是从文案里反推出来的
# ══════════════════════════════════════════════════════════════════════════════

class TestTheCodeIsTheProductsConstant:
    """`PERMISSION_DENIED` 必须与产品侧**同一来源**（漂移 ⇒ 判据静默失去目标）。"""

    def test_the_code_we_render_is_the_products_constant(self):
        src = (AI_AGENT / "app" / "tools" / "base.py").read_text(encoding="utf-8")
        m = re.search(r'^PERMISSION_DENIED_CODE = "([^"]+)"', src, re.M)
        assert m, "产品侧不再导出 `PERMISSION_DENIED_CODE` ⇒ 归因留痕的码失去单一来源"
        assert m.group(1) == DENIED_CODE, (
            f"产品侧常量改了（{m.group(1)!r}）⇒ 本文件与 runner 的码口径必须同步")

    def test_code_comes_from_the_field_not_from_the_error_text(self):
        """**不从文案反推**：error 文本里含 `PERMISSION_DENIED` 但没有字段 ⇒ 码必须留空。

        为什么这是硬判据：文案会变（"权限不足" → "您没有权限使用该功能"），
        靠子串反推的码会在文案改版当天静默失效（同族形态：#4122 的"从不带 error_code"）。
        """
        r = _round([("order_manage", {"action": "refund"})],
                   [("order_manage", {"success": False,
                                      "error": "PERMISSION_DENIED: 无退款权限"})])
        assert _status(r)[0]["error_code"] == "", (
            "码只能取自结构化字段 —— 从 error 文案里抠出来 = 假证据（文案即变）")

    def test_non_permission_failure_has_no_code(self):
        """非权限类失败（超时/参数错）没有码 ⇒ 留空，与权限拒绝**值级可分**。"""
        r = _round([("order_query", {"action": "list"})],
                   [("order_query", {"success": False, "error": "请求超时"})])
        entry = _status(r)[0]
        assert entry["error_code"] == ""
        assert entry["action"] == "list", "非权限失败同样要留 action（归因面不挑失败类型）"


# ══════════════════════════════════════════════════════════════════════════════
# 三、渲染形状：`工具名{action=…}!error[CODE]`（缺观测就不写，不填占位符）
# ══════════════════════════════════════════════════════════════════════════════

class TestFailureShapeIsValueLevel:

    def test_shape_carries_action_and_code(self):
        """#4197 的目标形态逐字：一行同时钉住"哪个 action"与"哪种码"。"""
        entry = _status(_round([("employee_manage", {"action": "list"})],
                               [("employee_manage", _denied())]))[0]
        assert lr._failure_shape(entry) == \
            f"employee_manage{{action=list}}!权限不足[{DENIED_CODE}]"

    def test_shape_omits_absent_fields_without_placeholders(self):
        """缺 action / 缺码 ⇒ 不写占位符（"没观测到"不许长得像"有证据"）。"""
        assert lr._failure_shape(
            {"tool": "order_query", "error": "请求超时", "action": "", "error_code": ""}) == \
            "order_query!请求超时"
        assert lr._failure_shape(
            {"tool": "order_query", "error": "请求超时", "action": "list", "error_code": ""}) == \
            "order_query{action=list}!请求超时"
        assert lr._failure_shape(
            {"tool": "order_query", "error": "请求超时", "action": "", "error_code": DENIED_CODE}) == \
            f"order_query!请求超时[{DENIED_CODE}]"

    def test_legacy_shape_could_not_separate_action_or_code(self):
        """负例对照：改前的 `工具名!error` 里**既没有 action 也没有码** ⇒ 存在性级。"""
        r = _round([("employee_manage", {"action": "list"})],
                   [("employee_manage", _denied())])
        entry = _status(r)[0]
        legacy = _legacy_failure_shape(_legacy_tool_result_status(r["tool_results"])[0])
        assert legacy == "employee_manage!权限不足", legacy
        assert "{action=" not in legacy and DENIED_CODE not in legacy, (
            "夹具失效：改前的形状本就带 action/码，则本判据不是 #4197 的红证")
        assert lr._failure_shape(entry) != legacy, "新形状必须真的比旧形状多出信息"

    def test_format_round_trace_shows_the_shape(self):
        """端到端：`build_round_trace` → `format_round_trace` 的 `failed=` 段带新形状。"""
        r = _round([("employee_manage", {"action": "list"}),
                    ("role_manage", {"action": "list"})],
                   [("employee_manage", _denied()),
                    ("role_manage", _denied(error="权限不足"))])
        r["__round"] = 1
        line = lr.format_round_trace(lr.build_round_trace([r]))
        assert f"employee_manage{{action=list}}!权限不足[{DENIED_CODE}]" in line, line
        assert "role_manage{action=list}!权限不足[PERMISSION_DENIED]" in line, line
        # 信息是**超集**：工具名与 error 原文仍在（没有为了塞新字段而丢掉旧信号）。
        assert "employee_manage" in line and "权限不足" in line, line
        # 负例对照（证明上面不是恒绿）：改前的渲染形态**不满足**上面的判据 ——
        # `failed=工具名!error` 里既没有 `{action=` 也没有 `[CODE]`，正是 #4197 的"存在性级"。
        legacy_line = "failed=" + ",".join(
            _legacy_failure_shape(x)
            for x in _legacy_tool_result_status(r["tool_results"]))
        assert "employee_manage{action=list}" not in legacy_line, (
            "夹具失效：改前的渲染本就带 action，则本判据不是 #4197 的红证")
        assert f"[{DENIED_CODE}]" not in legacy_line, (
            "夹具失效：改前的渲染本就带码，则本判据不是 #4197 的红证")


# ══════════════════════════════════════════════════════════════════════════════
# 四、**只加证据**：旧字段（tool/ok/error/digest）逐字不变，判定口径一字未动
# ══════════════════════════════════════════════════════════════════════════════

class TestOnlyEvidenceWasAdded:
    """`ok`/`error`/`digest` 与改造前**整字典相等**（除两个新键）—— 防止"顺手改了判定"。"""

    #: 覆盖真实形态：成功 / 权限拒绝 / 缺 success 标志 / 无 data 的失败 / 结果不是 dict
    SHAPES = (
        ("成功带数据", {"tool": "order_query", "result": {"success": True, "data": {"items": [1, 2]}}}),
        ("权限拒绝", {"tool": "employee_manage", "result": DENIED_RESULT}),
        ("缺 success 标志", {"tool": "order_create", "result": {"data": {"order_id": "o1"}}}),
        ("无 data 的失败", {"tool": "order_create", "result": {"success": False, "error": "参数缺失"}}),
        ("结果非 dict", {"tool": "interact", "result": None}),
    )

    def test_legacy_fields_are_byte_identical(self):
        """逐形态比对：旧四字段必须与**独立逐字副本**相等（含 `ok` 的"缺失即不成功"口径）。"""
        for name, tr in self.SHAPES:
            new = lr._tool_result_status([tr])
            old = _legacy_tool_result_status([tr])
            legacy_view = [{k: e[k] for k in ("tool", "ok", "error", "digest")} for e in new]
            assert legacy_view == old, f"{name}：旧字段被改动了（本单只许**加**证据）"

    def test_the_only_new_keys_are_action_and_error_code(self):
        """键集必须**恰好**是旧键集 ∪ {action, error_code} —— 多一个键同样是口径变更。"""
        for name, tr in self.SHAPES:
            new = lr._tool_result_status([tr])
            old = _legacy_tool_result_status([tr])
            assert set(new[0]) == set(old[0]) | {"action", "error_code"}, (
                f"{name}：键集变了 —— 新键应恰好是 action/error_code")

    def test_missing_success_flag_is_still_not_ok(self):
        """`ok` 的既有口径不变：缺 `success` ⇒ 按**不成功**记（宁可显性可疑）。"""
        entry = lr._tool_result_status([self.SHAPES[2][1]])[0]
        assert entry["ok"] is False
        assert entry["error"] == "no_success_flag"

    def test_denial_digest_still_shows_the_reason(self):
        """无 data 的失败仍从 digest 看出原因（既有能力不得因新增字段而丢失）。"""
        entry = lr._tool_result_status([{"tool": "employee_manage", "result": DENIED_RESULT}])[0]
        assert entry["digest"] == "权限不足", entry["digest"]
