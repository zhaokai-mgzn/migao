# case_ids: DF-018, CH-022
"""评测栈的两条能力缺口（issue #5482）：**长会话构造（`pre_turns`）/ 凭证复位**。

## 缺口是什么（对 `origin/main` 的逐字取证）

| 能力 | 今天的现状（取证） | 后果 |
|---|---|---|
| 长会话构造 | `run_case` 只遍历 `case.user_inputs`（`tests/agent_eval/local_runner.py` 的 `run_case` 里 `_turns = expand_repeat_turns(list(case.user_inputs or []))`）——**没有任何**注入历史轮次的入口（`git grep -n pre_turns origin/main` 命中 **0** 处） | 「会话里已经有 N 轮上下文」这类前置**构造不出来**：只能把历史写进 `user_inputs`，而那些轮会**进本用例的被测轨迹与计分**（轮号整体后移） |
| 凭证复位 | 夹具层登记表 `_CLEAN_TYPES` 共 14 类（`git grep -c` 见 PR body），**没有**任何一类作用在「已发验证码 / 已点确认卡 / 会话态」上 | 同一会话**连续跑两次**同一用例时，上一跑留下的凭证事实会放行本跑的写（`_stored_sms_code` 回填 `order_create.sms_code`、`confirmed_write_release` 按记录放行）⇒ 第二次的前置 ≠ 第一次 |

**现取需求条数 = 2**（`.github/cases/**` 里 `precondition`/`preconditions` 逐字声称
「同一会话内已发生的历史轮次 / 会话内累计状态」的用例）：`DF-018`、`CH-022`。
复算命令（零 LLM、零栈）：

```bash
python3 - <<'PY'
import sys, re; sys.path.insert(0, ".github"); import render_cases
def txt(v):
    if isinstance(v, str): return v
    if isinstance(v, list): return " ".join(txt(x) for x in v)
    if isinstance(v, dict): return " ".join(txt(x) for x in v.values())
    return "" if v is None else str(v)
pat = re.compile(r"第\\s*\\d+\\s*轮|同一会话|同会话|会话内|每会话|冷却|累积|上限")
print([c["id"] for c in render_cases.load_case_dicts(".github/cases")
       if pat.search(txt(c.get("precondition")) + txt(c.get("preconditions")))])
PY
```

- `DF-018`（`defense.yml`）逐字：`preconditions: "…且会话中存在一轮「提出补充商品属性」的上下文，
  使第 2 轮的「确认」是对它的确认而非新指令"`，其 `data_checks` 要求「**会话消息数 >20**」——
  而它的 `user_inputs` 只有 2 轮 ⇒ 触发形态在评测栈上**物理不可满足**（issue 原文点名的那条）。
- `CH-022`（`chat.yml`）逐字：`precondition: "…且每会话澄清上限 = MAX_CLARIFY_ROUNDS(2)"` +
  `data_checks: "低置信澄清（…）轮次计数存 SessionStateStore.clarify"` —— 会话内**累计**状态。

## 本文件钉住什么

1. **`pre_turns` 真被构造**：三轮历史走**同一条** `send_message` 路径、进**同一份** `results`
   轨迹（历史轮 = R1..R3，本用例的轮次顺延到 R4）⇒ 既有断言/计分口径不新增第二套；
2. **不声明 `pre_turns` 的用例行为不变**：缺该字段的对象与 `pre_turns=[]` 走同一条路径，
   轮号/标记/轨迹逐字一致（`getattr(case, "pre_turns", None) or []` 的缺省语义）；
3. **声明形态 fail-closed**：写成 JSON 字符串 / 空列表 / 非列表 ⇒ 折进 `case_issues`
   （构造不出来必须是**响的**，不能静默变成 0 轮）；
4. **`session_credential_restore` 是登记表里的一等类型**：与 `assertion_taxonomy` 的
   `KNOWN_PRECLEAN_TARGET_FIELDS` 对齐（既有元守卫），两阶段都可声明，失败 fail-closed；
5. **复位后重跑等价**：同一会话连跑两次，声明复位 ⇒ 第二次与第一次**逐值等价**；
   不声明 ⇒ 第二次被上一跑的凭证放行（**本文件把这一格当红基线钉住**）。

## 红证（注入式，实跑读数见 PR body）

| 断言 | 注入 | 预期 |
|---|---|---|
| ① 三轮历史真构造 | `run_case` 里 `_turns = _pre_turns + …` → `_turns = …`（抹掉历史） | 必红（只发 1 轮 / R3 取不到值） |
| ② 缺省路径逐字不变 | `_pre_turns = expand_repeat_turns(...)` → `_pre_turns = _turns` | 必红（轮号/标记整体错位） |
| ③ 复位后第二次等价 | `_restore_session_credentials` 首行 `return ""`（复位空转） | 必红（第二次只剩 1 轮、无本跑供码） |

⚠️ 本文件**不**发真实 HTTP、**不**连真实 DB、**不**跑真实 LLM（#4262：不自动进行真实评测）：
HTTP 边界由 `_FakeStack` 替身驱动，DB 边界由假 `asyncpg` 驱动（同一手法见
`tests/unit_ci_workflows/test_eval_case_asset_truth.py` 的 `_patch_asyncpg`）。
"""
import asyncio
import re
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
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
import render_cases  # noqa: E402
from eval_cases import Difficulty, EvalCase, Skill  # noqa: E402

SID = "sess_stub_5482"
CODE = "123456"
#: 顾客供码轮的形态（真值 = `base_skill.extract_sms_code`：4~6 位数字）
_CODE_RE = re.compile(r"\d{4,6}")


# ── 假栈：把 runner 的 **HTTP 边界**换成可控替身（真跑 `run_case` 本体）────────────
class _FakeStack:
    """会话工作状态的**忠实模型**（PG `session_states`，键 = `session_id`）。

    替身建模的是**产品侧真实行为**（不是为测试编的行为）：
      · 顾客供码轮 ⇒ 记住码（对应 `base_skill._remember_sms_code`）；
      · 下一步要下单时，**本跑没供码**也能拿到码 ⇒ 写照样成立
        （对应 `finalize_turn` 的确认收口：`resolve_sms_code(extract_sms_code(last_user_msg)
        or _stored_sms_code(session_id), …)`）；
      · 码未知 ⇒ 回一句索码（harness 的 `needs_verification_code` 据此供码）。
    这就是「同一会话连跑两次 ⇒ 第二次被第一次的凭证放行」的机制本体。
    """

    def __init__(self, sessions=None, states=None):
        self.sessions = set(sessions or [])            # `sessions` 表（存在性）
        self.states = dict(states or {})               # `session_states` 表（键 = session_id）
        self.sent = []                                 # 本跑实际发出的用户消息（逐轮）
        self.sessions_used = []                        # 每轮用的是哪个会话（证明"同一会话"）
        self.deleted = []                              # 被执行过的清空动作（幂等红证）
        self.drop_delete_fails = False                 # 注入：DELETE 不生效（回读不符红证）
        self.connections = 0

    async def send_message(self, token, session_id, message, images=None, **_kw):
        self.sent.append(message)
        self.sessions_used.append(session_id)
        state = self.states.setdefault(session_id, {})
        if _CODE_RE.fullmatch(message.strip()):
            # 顾客供码轮（真实链路 `base_skill._remember_sms_code`：码进会话状态）。
            # ⚠️ 这句回执**刻意不提「验证码」三个字**：harness 的索码判定含"文字里提到验证码"
            #    这条软信号（`needs_verification_code`），提了就会把每一轮都变成供码轮，
            #    后面的写轮永远不会发生（实测踩到：3 轮全是供码）。
            state["last_sms_code"] = message.strip()
            return self._round(message, images, final_text="好的，已记下，我这就为您办理")
        if state.get("last_sms_code"):
            return self._round(
                message, images, final_text="已为您下单",
                tool="order_create",
                args={"action": "create", "sms_code": state["last_sms_code"]})
        return self._round(message, images, final_text="请提供下单短信验证码")

    def _round(self, message, images, final_text, tool="", args=None):
        calls = [{"name": tool, "args": dict(args or {})}] if tool else []
        results = ([{"tool": tool, "result": {"success": True, "data": {"orderNo": "EVAL-STUB-1"}}}]
                   if tool else [])
        return {"user_message": message, "images": images or [], "tool_calls": calls,
                "tool_results": results, "interactive": [], "final_text": final_text,
                "error": None, "streamed": True, "done": True}


async def _no_case_issues(token, case):
    """`check_debug_user_precondition` 的替身（它会发 HTTP；本文件零网络）。"""
    return []


def _use_stack(monkeypatch, stack):
    monkeypatch.setattr(lr, "send_message", stack.send_message)
    monkeypatch.setattr(lr, "check_debug_user_precondition", _no_case_issues)
    monkeypatch.setattr(lr, "ROUND_SLEEP", 0)
    return stack


class _FakeConn:
    """假 asyncpg 连接：按 **SQL 形状**（拿 runner 的常量当锚点）改内存态。"""

    def __init__(self, stack):
        self.stack = stack

    async def fetchval(self, sql, *args):
        sid = args[0]
        if sql == lr._SESSION_EXISTS_SQL:
            return 1 if sid in self.stack.sessions else None
        if sql == lr._SESSION_STATE_READ_SQL:
            return self.stack.states.get(sid)
        raise AssertionError(f"假 asyncpg 收到未建模的 SQL：{sql}")

    async def execute(self, sql, *args):
        sid = args[0]
        if sql != lr._SESSION_STATE_CLEAR_SQL:
            raise AssertionError(f"假 asyncpg 收到未建模的 SQL：{sql}")
        self.stack.deleted.append(sid)
        if not self.stack.drop_delete_fails:
            self.stack.states.pop(sid, None)
        return "DELETE 1"

    async def close(self):
        return None


def _patch_asyncpg(monkeypatch, stack):
    mod = types.ModuleType("asyncpg")

    async def _connect(_dsn):
        stack.connections += 1
        return _FakeConn(stack)

    mod.connect = _connect
    monkeypatch.setitem(sys.modules, "asyncpg", mod)
    return stack


# ── 用例构造（真 `EvalCase`；只给必需字段）─────────────────────────────────────
def _case(pre_turns=..., user_inputs=None, expectations=None, data_checks=None):
    kwargs = dict(
        id="STUB-5482", title="长会话/凭证复位（stub 驱动）", skill=Skill.GENERAL,
        difficulty=Difficulty.NORMAL,
        user_inputs=user_inputs if user_inputs is not None else ["帮我下单"],
        expectations=(expectations if expectations is not None
                      else ["order_create(action=create)"]),
        data_checks=data_checks if data_checks is not None else [])
    if pre_turns is not ...:
        kwargs["pre_turns"] = pre_turns
    return EvalCase(**kwargs)


def _order_sms(run):
    """本跑 `order_create` 实际带上的 `sms_code`（值级证据，两个落盘通道都查）。

    `round_trace[*].write_args` / `call_args` 是 runner **落盘**的入参证据
    （`build_round_trace`），不是替身自己记的 —— 断言取证面与既有 `arg_values` 同一份。
    """
    for rnd in run.get("round_trace") or []:
        for ch in ("write_args", "call_args"):
            for c in (rnd.get(ch) or []):
                if "order_create" in str((c or {}).get("tool") or ""):
                    v = ((c or {}).get("args") or {}).get("sms_code")
                    if v:
                        return str(v)
    return ""


def _own_turns(run):
    """本跑**实际发出**的用户消息（落盘轨迹里的 `user`，含 harness 生成的协议轮答复）。"""
    return [str((r or {}).get("user") or "") for r in (run.get("round_trace") or [])]


# ── ① 长会话构造：三轮历史真被构造，且逐值断言到第 3 轮 ─────────────────────────
class TestPreTurnsAreConstructed:
    HISTORY = ["有没有遮光窗帘", "那件多少钱", "就要那件"]

    def test_three_pre_turns_are_sent_in_the_same_session_and_value_asserted(self, monkeypatch):
        stack = _use_stack(monkeypatch, _FakeStack(sessions={SID}))
        case = _case(pre_turns=list(self.HISTORY), user_inputs=["就按刚才那件下单"],
                     expectations=[], data_checks=["order_create 未被调用"])
        run = asyncio.run(lr.run_case(case, "", SID))

        # 同一会话：4 轮全发在**同一个** session_id 上（"长会话"的定义）
        assert stack.sessions_used == [SID] * 4
        # 逐值：第 3 轮**逐字**是第三条历史（不是"有 3 轮"这种存在性）
        assert stack.sent[0] == self.HISTORY[0]
        assert stack.sent[1] == self.HISTORY[1]
        assert stack.sent[2] == self.HISTORY[2]
        assert stack.sent[3] == "就按刚才那件下单"
        # 轨迹：历史轮在前（R1..R3，`__pre_turn=True`），本用例的轮顺延到 R4
        rounds = [r["round"] for r in run["round_trace"]]
        assert rounds == [1, 2, 3, 4]
        assert [t["user"] for t in run["round_trace"]] == list(self.HISTORY) + ["就按刚才那件下单"]
        assert run["rounds"] == 4
        # 计分口径**没变**：断言数/通过数仍按既有 `expectations` 算
        assert run["score"] == 1.0

    def test_control_turns_are_shared_with_user_inputs_grammar(self, monkeypatch):
        """`pre_turns` 与 `user_inputs` **同一套**轮次语法（控制轮 dict 照旧生效）。"""
        stack = _use_stack(monkeypatch, _FakeStack(sessions={SID}))
        case = _case(pre_turns=[{"auto_select": True}], user_inputs=["确认"],
                     expectations=[], data_checks=["order_create 未被调用"])
        asyncio.run(lr.run_case(case, "", SID))
        # 无待答卡 ⇒ 控制轮回落字面量「第一个」（既有语义，未改）
        assert stack.sent == ["第一个", "确认"]

    def test_a_request_without_the_field_keeps_the_identical_trajectory(self, monkeypatch):
        """缺省路径**逐字不变**：没有 `pre_turns` 属性的对象 == `pre_turns=[]`。"""
        legacy = _case(user_inputs=["一", "二"], expectations=[],
                       data_checks=["order_create 未被调用"])   # 不传 pre_turns ⇒ 缺省
        empty = _case(pre_turns=[], user_inputs=["一", "二"], expectations=[],
                      data_checks=["order_create 未被调用"])
        stack_a = _use_stack(monkeypatch, _FakeStack(sessions={SID}))
        run_a = asyncio.run(lr.run_case(legacy, "", SID))
        stack_b = _use_stack(monkeypatch, _FakeStack(sessions={SID}))
        run_b = asyncio.run(lr.run_case(empty, "", SID))
        assert stack_a.sent == stack_b.sent == ["一", "二"]
        assert _own_turns(run_a) == _own_turns(run_b) == ["一", "二"]
        assert [r["round"] for r in run_a["round_trace"]] == [1, 2]
        assert [r["round"] for r in run_b["round_trace"]] == [1, 2]
        assert run_a["score"] == run_b["score"] == 1.0

    def test_declarations_that_would_silently_build_zero_turns_are_fail_closed(self, monkeypatch):
        """构造不出来必须是**响的**：非列表形态 ⇒ 折进结论（score=0）；空列表 = **缺省**，放行。

        ⚠️ 空列表**不能**判红（实测教训）：`EvalCase.pre_turns` 的 dataclass 缺省就是 `[]`
        ⇒ 把 `[]` 当"声明了 0 轮"会让**全库 486 条用例**当场 score=0（判据自己变缺陷）。
        生成物侧也不落空列表字面量 ⇒ 这一格没有静默失效面。
        """
        for bad in ('["有没有遮光窗帘"]', "有没有遮光窗帘", {"text": "看看"}):
            _use_stack(monkeypatch, _FakeStack(sessions={SID}))
            run = asyncio.run(lr.run_case(_case(pre_turns=bad, user_inputs=["确认"],
                                                expectations=[], data_checks=[]), "", SID))
            assert run["score"] == 0.0, f"pre_turns={bad!r} 应被判失败"
            assert any("pre_turns" in str(f[0]) for f in run["failed"]), bad
        # 缺省（`[]`）与"没声明"等价 ⇒ 不被判失败（缺省路径不变）
        _use_stack(monkeypatch, _FakeStack(sessions={SID}))
        ok = asyncio.run(lr.run_case(
            _case(pre_turns=[], user_inputs=["确认"], expectations=[],
                  data_checks=["order_create 未被调用"]), "", SID))
        assert ok["score"] == 1.0
        assert ok["failed"] == []

    def test_the_two_control_turn_guards_share_one_criterion(self):
        """控制轮写成 JSON 字符串：`pre_turns` 与 `user_inputs` 走**同一份**判据。"""
        assert lr.check_pre_turns_declared(None) == []
        assert lr.check_pre_turns_declared(["正常"]) == []
        assert lr.check_pre_turns_declared([]) == []           # 缺省 = 没声明（见上一条测试）
        assert len(lr.check_pre_turns_declared('{"auto_select": true}')) == 1
        assert len(lr.check_pre_turns_declared(['{"auto_select": true}'])) == 1
        assert lr.check_pre_turns_declared([{"auto_select": True}]) == []
        assert lr.check_control_turns_declared(
            ['{"auto_select": true}'], field="pre_turns") == lr.check_pre_turns_declared(
            ['{"auto_select": true}'])


# ── ② 接通：yml 声明 → 生成物 → EvalCase（不许静默丢字段）───────────────────────
class TestTheFieldIsWiredEndToEnd:
    def test_the_renderer_emits_the_field_and_the_dataclass_exposes_it(self):
        """声明了 `pre_turns` 的用例必须在**生成物**里出现该字面量（否则=声明无消费）。"""
        gen = render_cases.to_eval_py([{
            "id": "STUB-1", "title": "t", "tier": "normal", "_domain": "chat",
            "user_inputs": ["确认"], "expectations": [],
            "pre_turns": ["有没有遮光窗帘", {"auto_select": True}],
        }])
        assert "pre_turns=['有没有遮光窗帘', {'auto_select': True}]" in gen
        # 缺省不落字面量（"缺省不改变既有行为"在 diff 上可读；dataclass 头那一行不算字面量）
        gen_plain = render_cases.to_eval_py([{
            "id": "STUB-2", "title": "t", "tier": "normal", "_domain": "chat",
            "user_inputs": ["确认"], "expectations": [],
        }])
        assert "    pre_turns=[" not in gen_plain
        assert _case().pre_turns == []

    def test_the_ci_yaml_loader_maps_the_field(self, monkeypatch):
        """**CI 走的是 YAML 装载路径**（`--cases .github/cases`）⇒ 漏映射 = 声明了却在 CI 上丢历史。

        本仓已记载 3 次同款假绿（`debug_user` / `output_verify` / `auto_fill`）：字段在
        渲染器映射了、`load_cases_from_yaml` 漏了 ⇒ 生成物看着正常、本地读生成物也正常，
        而 CI 走的正是 YAML 路径 ⇒ 该声明**从未生效**。这里驱动**真实装载体**
        （只替换它的数据源），去掉 `load_cases_from_yaml` 里的 `pre_turns=` 即红。
        """
        synthetic = {"id": "STUB-Y", "title": "t", "tier": "normal", "_domain": "chat",
                     "user_inputs": ["确认"], "expectations": [],
                     "pre_turns": ["有没有遮光窗帘", {"auto_select": True}]}
        monkeypatch.setattr(render_cases, "load_case_dicts", lambda _d: [dict(synthetic)])
        loaded = lr.load_cases_from_yaml(str(REPO_ROOT / ".github" / "cases"))
        assert [c.pre_turns for c in loaded] == [["有没有遮光窗帘", {"auto_select": True}]]
        assert [c.user_inputs for c in loaded] == [["确认"]]

    def test_no_case_in_the_library_uses_it_yet_so_the_default_path_is_untouched(self):
        """现取读数：本 PR **不动**任何存量用例 ⇒ 生成物 diff 只有 dataclass 一行。"""
        cases = render_cases.load_case_dicts(str(REPO_ROOT / ".github" / "cases"))
        assert len(cases) == 486
        assert [c["id"] for c in cases if c.get("pre_turns")] == []

    def test_every_library_case_passes_the_new_guard(self):
        """类级元守卫：全库 486 条**真 `EvalCase` 对象**过 `pre_turns` 判据 ⇒ 一条都不误伤。

        这一条是"缺省路径逐字不变"的**全量**形态：新判据若把 dataclass 缺省（`[]`）读成
        "声明了 0 轮历史"，全库每一条用例都会当场 score=0（开发中实测踩到）——
        本判据把那一格钉死，改回去即红。
        """
        import eval_cases
        assert len(eval_cases.ALL_CASES) == 486
        assert [c.id for c in eval_cases.ALL_CASES
                if lr.check_pre_turns_declared(c.pre_turns)] == []


# ── ③ 凭证复位：登记 + 两阶段 + fail-closed ────────────────────────────────────
class TestSessionCredentialRestoreIsRegistered:
    def test_registered_in_both_phases_with_the_restore_family_semantics(self):
        meta = lr._CLEAN_TYPES["session_credential_restore"]
        assert meta["phases"] == ("pre", "post")
        assert meta["attr"] == ""                      # 非商品夹具属性 ⇒ 不参与 attr↔复位映射
        assert "session_credential_restore" in lr._PRECLEAN_TYPES
        assert "session_credential_restore" in lr._POSTCLEAN_TYPES
        import assertion_taxonomy
        assert (assertion_taxonomy.KNOWN_PRECLEAN_TARGET_FIELDS["session_credential_restore"]
                == "session_id")

    def test_missing_session_id_is_a_config_error_in_both_phases(self, monkeypatch):
        monkeypatch.delenv("EVAL_SESSION_ID", raising=False)
        pre = asyncio.run(lr._run_clean_action("", {"type": "session_credential_restore"}, "pre"))
        post = asyncio.run(lr._run_clean_action("", {"type": "session_credential_restore"}, "post"))
        assert pre.startswith(lr._PRECONDITION_NOT_APPLIED)
        assert post.startswith("PRECONDITION_NOT_RESTORED")
        # 两阶段都必须被既有分类器捞出来（pre 进结论 / post 进 restore 通道）
        assert lr._classify_preclean_message({"type": "session_credential_restore"}, pre) == pre
        assert "PRECONDITION_NOT_RESTORED" in lr._classify_clean_message(
            {"type": "session_credential_restore"}, post, "post")

    def test_unknown_session_is_reported_as_a_missing_target(self, monkeypatch):
        stack = _patch_asyncpg(monkeypatch, _FakeStack(sessions=set()))
        msg = asyncio.run(lr._run_clean_action(
            "", {"type": "session_credential_restore", "session_id": "sess_nope"}, "pre"))
        assert msg.startswith(lr._PRECONDITION_NOT_APPLIED)
        assert "不在库里" in msg
        assert stack.deleted == []                     # 目标不在 ⇒ 一个写动作都不许发

    def test_idempotent_when_the_session_has_no_credential_facts(self, monkeypatch):
        stack = _patch_asyncpg(monkeypatch, _FakeStack(sessions={SID}))
        msg = asyncio.run(lr._run_clean_action(
            "", {"type": "session_credential_restore", "session_id": SID}, "pre"))
        assert "幂等" in msg
        assert stack.deleted == []                     # 已是初始态 ⇒ 不发 DELETE
        assert not msg.startswith(lr._PRECONDITION_NOT_APPLIED)
        assert "未复位" not in msg and "失败" not in msg   # 措辞红线（#3751）

    def test_readback_mismatch_is_flagged(self, monkeypatch):
        stack = _patch_asyncpg(monkeypatch, _FakeStack(
            sessions={SID}, states={SID: {"last_sms_code": CODE, "confirmed_write_tool": "x"}}))
        stack.drop_delete_fails = True
        msg = asyncio.run(lr._run_clean_action(
            "", {"type": "session_credential_restore", "session_id": SID}, "pre"))
        assert msg.startswith(lr._PRECONDITION_NOT_APPLIED)
        assert "没清干净" in msg

    def test_success_clears_the_facts_and_the_message_stays_on_the_success_side(self, monkeypatch):
        stack = _patch_asyncpg(monkeypatch, _FakeStack(
            sessions={SID}, states={SID: {"last_sms_code": CODE}}))
        msg = asyncio.run(lr._run_clean_action(
            "", {"type": "session_credential_restore", "session_id": SID}, "pre"))
        assert "未复位" not in msg and "失败" not in msg
        assert stack.deleted == [SID]
        assert stack.states == {}
        assert "初始态" in msg

    def test_env_var_session_id_is_the_replay_fallback(self, monkeypatch):
        stack = _patch_asyncpg(monkeypatch, _FakeStack(
            sessions={SID}, states={SID: {"last_sms_code": CODE}}))
        monkeypatch.setenv("EVAL_SESSION_ID", SID)
        msg = asyncio.run(lr._run_clean_action("", {"type": "session_credential_restore"}, "pre"))
        assert stack.deleted == [SID]
        assert SID in msg


# ── ④ 红基线 + 等价性：同一会话连跑两次 ───────────────────────────────────────
def _two_runs(monkeypatch, *, with_reset):
    """同一会话连跑两次同一用例（重放配置：会话由调用方给，`EVAL_SESSION_ID` 即此用）。"""
    stack = _use_stack(monkeypatch, _FakeStack(sessions={SID}))
    _patch_asyncpg(monkeypatch, stack)
    case = _case(user_inputs=[
        {"repeat_until": {"tool_called": "order_create", "max": 3},
         "code": CODE, "fallback": "帮我下单"},
    ])
    first = asyncio.run(lr.run_case(case, "", SID))
    reset_msgs = []
    if with_reset:
        monkeypatch.setenv("EVAL_SESSION_ID", SID)
        # `_run_pre_clean` 返回的是**归类后**的原始消息（`_run_clean_specs` 才返回列表）
        reset_msgs = [asyncio.run(lr._run_pre_clean(
            "", {"type": "session_credential_restore", "session_id": SID}))]
    second = asyncio.run(lr.run_case(case, "", SID))
    return stack, first, second, reset_msgs


class TestCredentialResetMakesTheSecondRunEquivalent:
    def test_without_the_reset_the_second_run_is_let_through_by_the_first(self, monkeypatch):
        """**红基线**（改前形态）：第二次本跑顾客一声没吭，写却带着上一跑的码。

        ⚠️ 落盘通道把验证码掩码（`_arg_value` 的 PII 掩码 ⇒ 值显示为 `***`）⇒ 这一格可判的是
        「**写带了码**」与「两次带的是**同一个**码」；「本跑到底有没有供码」由 `_own_turns`
        （本跑实际发出的每一轮，未掩码）承载 —— 两半合起来才是污染判据。
        """
        stack, first, second, _ = _two_runs(monkeypatch, with_reset=False)
        assert _own_turns(first) == ["帮我下单", CODE, "帮我下单"]   # 首跑：码是本跑顾客给的
        assert _order_sms(first)
        assert _own_turns(second) == ["帮我下单"]                  # 第二次：本跑**没供码**
        assert _order_sms(second) == _order_sms(first)            # ← 却被上一跑的码放行（污染）
        assert len(_own_turns(second)) < len(_own_turns(first))   # 两次的轮次结构已不等价
        assert stack.deleted == []

    def test_with_the_reset_the_second_run_matches_the_first_value_by_value(self, monkeypatch):
        """声明 `pre_clean[session_credential_restore]` ⇒ 第二次与第一次**逐值等价**。"""
        stack, first, second, reset_msgs = _two_runs(monkeypatch, with_reset=True)
        assert stack.deleted == [SID]                            # 复位真的落到存储上
        assert len(reset_msgs) == 1
        assert "未复位" not in reset_msgs[0] and "失败" not in reset_msgs[0]
        assert lr.check_preclean_not_applied(reset_msgs) == []
        # "第二次不受第一次状态影响"的**逐值**判据：本跑实际发出的每一轮都一样
        assert _own_turns(second) == _own_turns(first) == ["帮我下单", CODE, "帮我下单"]
        assert _order_sms(second) == _order_sms(first)
        assert _order_sms(second)                                # 第二次也带码（且来自本跑供码）
        assert second["rounds"] == first["rounds"] == 3
        assert second["score"] == first["score"] == 1.0

    def test_post_phase_reset_is_the_writer_side_cleanup(self, monkeypatch):
        """`post_clean` 同一类型：用例结束后把凭证事实清掉（"谁造的谁清"）。"""
        stack = _use_stack(monkeypatch, _FakeStack(sessions={SID}, states={SID: {"last_sms_code": CODE}}))
        _patch_asyncpg(monkeypatch, stack)
        msgs = asyncio.run(lr._run_post_clean(
            "", {"type": "session_credential_restore", "session_id": SID}))
        assert stack.states == {}
        assert "PRECONDITION_NOT_RESTORED" not in msgs[0]


if __name__ == "__main__":                               # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))