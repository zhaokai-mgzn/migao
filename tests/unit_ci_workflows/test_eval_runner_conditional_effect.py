# case_ids: AS-003, AS-005, CH-009
"""条件效果层（`must_succeed[only_if_called]`）+ 三条用例的**逐条红证**（issue #3778）。

## 本文件锁什么

#3778 的病：**「调用了 ≠ 成了」** —— `expectations` 只做工具名匹配（runner 里走
`__all_tool_names`，**跨轮累积的工具名子串匹配**，完全不看工具结果），于是一次**被后端拒绝**
的写调用照样满足期望，用例判绿。静态侧的分类判据在
`tests/unit_ci_workflows/test_case_trust_gate.py`（写用例必须 ≥1 条效果层断言）；
本文件锁的是另一半 —— **断言真的会红**：

| 用例 | 补强前（红证的「前」半） | 补强后（红证的「后」半） |
|---|---|---|
| `AS-003` | 效果层只有 `data_checks: ["success=true"]`，而该分支**只读轮级 `result["error"]`**（工具级失败不算）⇒ 工单没建出来也绿 | `must_succeed[aftersale_create]` ⇒ 判红 |
| `AS-005` | `expectations` 里的 `after_sales_manage or aftersale_create` 按名字命中 ⇒ 建单失败也绿 | `must_succeed[aftersale_create]` ⇒ 判红 |
| `CH-009` | 写分支是**可选**的 OR（`direct_reply or order_create or interact`）⇒ 下单失败那一轮既无文本也无卡，仍按名字命中判绿 | `must_succeed[order_create, only_if_called]` ⇒ 判红；「只发文本」的合格行为**不受影响** |

「前」「后」两半都在下面的断言里，不是叙述 —— 拿掉任一半，本文件就红。

## 为什么需要 `only_if_called`（条件效果层）

可选写分支过去只有两条路，都是本仓最忌讳的形态：**不声明**（该分支无论怎么失败都判绿 =
#3778 的原病）或**无条件声明**（`direct_reply` 那一支的合格行为被误判成失败 = 假红）。
`only_if_called: true` 把真值说准：「没去下单」不算失败，「**去下单了就必须成了**」。

## 末节：声明的用例真的**接线**了

`TestDeclaredCasesAreWired` 直接读 `.github/cases/*.yml` 里这三条用例**声明的** `must_succeed`，
喂给 runner 的同一批断言函数 ⇒ 证明「用例里写的」与「运行期判的」是同一件事
（不是两套各自漂移的口径）。

⚠️ 本目录跑在 CI 的 `ci workflow helper unit tests` job（只 `pip install pytest pyyaml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 见下方 `_load_runner()` 的最小替身。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，一旦被调用即抛错）。"""
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


def _round(rnd, calls, results, text=""):
    """构造一轮 `results` 条目（与 `test_eval_runner_same_round_scope.py` 同形）。

    calls   : [(tool, args)]（args 直接作为该次调用回显的参数）
    results : [(tool, success)]（与该轮**同名工具**的调用按顺序对应）
    """
    return {
        "__round": rnd,
        "tool_calls": [{"name": t, "args": a} for t, a in calls],
        "tool_results": [
            {"tool": t, "result": {"success": ok}} for t, ok in results
        ],
        "final_text": text,
        "__all_tool_names": sorted({t for t, _ in calls}),
    }


def _failed_create_round(tool, rnd=3):
    """「写调用被后端拒绝」那一轮的确定性再现（零 LLM、零网络）。

    `order_query` 成功 + 目标写工具 `success=false` —— #3778 要求的红证形态就是这一格：
    **写失败**而其余一切看起来正常。
    """
    return _round(
        rnd,
        calls=[("order_query", {}), (tool, {})],
        results=[("order_query", True), (tool, False)],
        text="",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 一、条件效果层本身的语义（三态 + 配置硬化 + 向后兼容）
# ══════════════════════════════════════════════════════════════════════════════

class TestConditionalEffectLayer:
    """`must_succeed[only_if_called]`：没调用 ⇒ 放过；调用过但无一成功 ⇒ **判红**。"""

    COND = [{"tool": "order_create", "only_if_called": True}]
    UNCOND = [{"tool": "order_create"}]

    def test_attempted_and_failed_is_red(self):
        """核心一格：调用了但没成功 ⇒ 必须判红（这是效果层断言的存在理由）。"""
        issues = lr.check_must_succeed([_failed_create_round("order_create")], self.COND)
        assert len(issues) == 1, f"应恰好 1 条违规，实得 {issues}"
        assert "order_create" in issues[0] and "无一成功" in issues[0], issues[0]

    def test_attempted_and_succeeded_passes(self):
        """成功了 ⇒ 不报（防「加断言 = 恒红」）。"""
        r = _round(2, [("order_create", {})], [("order_create", True)], text="已下单")
        assert lr.check_must_succeed([r], self.COND) == []

    def test_never_called_passes_only_when_conditional(self):
        """从未调用：条件式**放过**（合格行为「只发文本」），无条件式**判红**。

        两半必须同时成立 —— 只测「条件式放过」会让整条断言在「无条件式也放过」时恒绿。
        """
        only_text = [_round(1, [], [], text="请告诉我想要的商品，我来帮您安排～")]
        assert lr.check_must_succeed(only_text, self.COND) == [], (
            "条件式在「从未调用」时不应报 —— 否则「只发文本」这条合格行为被误判成失败（假红）"
        )
        issues = lr.check_must_succeed(only_text, self.UNCOND)
        assert len(issues) == 1 and "从未被调用" in issues[0], (
            f"无条件式在「从未调用」时必须判红，实得 {issues}"
        )

    def test_unknown_key_is_config_error_not_silent_pass(self):
        """未支持的键 ⇒ 配置错误（过去**静默忽略** ⇒ 断言降级/空转而用例照旧判绿）。"""
        issues = lr.check_must_succeed(
            [_failed_create_round("order_create")],
            [{"tool": "order_create", "only_if_called": True, "typo_key": 1}],
        )
        assert len(issues) == 1 and "未支持的键" in issues[0], issues

    def test_plain_string_spec_stays_unconditional(self):
        """向后兼容：字符串形态（`must_succeed: [order_create]`）语义一字不变。"""
        only_text = [_round(1, [], [], text="好的")]
        issues = lr.check_must_succeed(only_text, ["order_create"])
        assert len(issues) == 1 and "从未被调用" in issues[0], issues

    def test_missing_tool_is_config_error(self):
        """缺 `tool` ⇒ 配置错误（不与「未调用」混为一谈）。"""
        issues = lr.check_must_succeed([], [{"only_if_called": True}])
        assert len(issues) == 1 and "配置缺 tool" in issues[0], issues


# ══════════════════════════════════════════════════════════════════════════════
# 二、逐条红证：补强前判绿 / 补强后判红（三条用例各自的形态）
# ══════════════════════════════════════════════════════════════════════════════

class TestWriteFailureRedProofs:
    """三条用例的「前/后」两半，逐条钉死（#3778 要求「不接受『看起来对了』」）。"""

    def test_as_003_round_level_success_true_survives_a_failed_ticket(self):
        """AS-003：补强前唯一的效果层是 `data_checks: ["success=true"]`。

        该分支**只读轮级 `result["error"]`**（见 `check_expectation`），工具级失败不算 ⇒
        工单没建出来也满足它。这条断言把「补强前的假绿」钉成可复算的事实。
        """
        r = _failed_create_round("aftersale_create")
        ok, detail = lr.check_expectation(r, "success=true")
        assert ok is True, f"补强前的形式本应放过（这正是假绿），实得 ok={ok} {detail}"

        issues = lr.check_must_succeed([r], [{"tool": "aftersale_create"}])
        assert len(issues) == 1 and "无一成功" in issues[0], issues

    def test_as_005_expectation_name_match_survives_a_failed_ticket(self):
        """AS-005：`after_sales_manage or aftersale_create` 按**名字**命中（不看结果）。"""
        r = _failed_create_round("aftersale_create")
        ok, detail = lr.check_expectation(r, "after_sales_manage or aftersale_create")
        assert ok is True, f"裸工具名期望本应放过失败的调用（#3778 原病），实得 {ok} {detail}"

        issues = lr.check_must_succeed([r], [{"tool": "aftersale_create"}])
        assert len(issues) == 1 and "aftersale_create" in issues[0], issues

    def test_ch_009_optional_write_branch_is_red_when_the_write_failed(self):
        """CH-009：写分支可选 ⇒ 必须条件化，但**一旦真去下单**就必须成了。

        三半：① 补强前按名字命中判绿（那一轮顾客其实什么都没得到 —— 无文本、无卡、无单）；
        ② 条件效果层判红；③ 纯文本的合格落地形态**不被**误判。
        """
        exp = "direct_reply or order_create or interact"
        r = _failed_create_round("order_create")
        ok, detail = lr.check_expectation(r, exp)
        assert ok is True, f"补强前本应放过（名字命中），实得 {ok} {detail}"

        issues = lr.check_must_succeed(
            [r], [{"tool": "order_create", "only_if_called": True}])
        assert len(issues) == 1 and "无一成功" in issues[0], issues

        text_only = [_round(1, [], [], text="收到，请告诉我您想要的款式，我来帮您安排～")]
        assert lr.check_expectation(text_only[0], exp)[0] is True
        assert lr.check_must_succeed(
            text_only, [{"tool": "order_create", "only_if_called": True}]) == [], (
            "「只发文本」是本用例的合格落地形态之一，不得被效果层断言判红"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 三、接线判据：用例 yml 里**声明的**断言 == 运行期真正判的断言
# ══════════════════════════════════════════════════════════════════════════════

class TestDeclaredCasesAreWired:
    """读 `.github/cases/*.yml` 的**声明**，喂给 runner 的断言函数 ⇒ 两处是同一件事。

    为什么必须有一条：只测合成夹具时，「用例里到底写没写」与「写了会不会被判」是两件事，
    中间断掉（声明写错工具名 / 键名拼错 / 渲染丢失）时两边都不会红。
    """

    CASES_DIR = REPO_ROOT / ".github" / "cases"

    @classmethod
    def _case(cls, case_id: str) -> dict:
        sys.path.insert(0, str(REPO_ROOT / ".github"))
        from render_cases import load_case_dicts
        for c in load_case_dicts(str(cls.CASES_DIR)):
            if c.get("id") == case_id:
                return c
        raise AssertionError(f"用例库解析不到 {case_id} —— 判据坐标失效")

    def _declared_issues(self, spec: list, sse_rounds: list) -> list:
        """按**条目自己声明的面**逐条判定（issue #4097：`source` 缺省 = SSE 面）。

        为什么要按面分发：`source: metadata` 的条目读的是**落库面**，用 SSE 轨迹喂它必然
        fail-closed 报「断言未评估」（那是设计使然，不是缺陷）—— 本判据的目标是
        「用例里声明的 == 运行期判的」，所以每条都要在**它自己的面**上被判定；
        只喂 SSE 面会让新增的落库面条目在这一格恒红（并把真实信号淹掉）。
        落库面 rounds 由 SSE 同形 rounds **反投影**（同一份事实两种投影，
        与 runner 的 `rounds_from_history_payload` 产出的形状一致）。
        """
        sse = [s for s in spec if not (isinstance(s, dict) and s.get("source") == "metadata")]
        meta = [s for s in spec if isinstance(s, dict) and s.get("source") == "metadata"]
        issues = lr.check_must_succeed(sse_rounds, sse)
        if meta:
            issues += lr.check_must_succeed([], meta, metadata_rounds=self._as_metadata(sse_rounds))
        return issues

    @staticmethod
    def _as_metadata(rounds: list) -> list:
        """SSE 同形 rounds → 落库面同形 rounds（`{tool, result:{success,error}}`）。"""
        out = []
        for r in rounds or []:
            out.append({
                "__round": r.get("__round"),
                "tool_calls": [{"name": tc.get("name"), "args": tc.get("args") or {}}
                               for tc in r.get("tool_calls") or []],
                "tool_results": [
                    {"tool": t.get("tool"),
                     "result": {"success": bool((t.get("result") or {}).get("success")),
                                "error": (t.get("result") or {}).get("error")}}
                    for t in r.get("tool_results") or []],
                "__source": "metadata",
            })
        return out

    def test_declared_effect_assertions_catch_the_failed_write(self):
        """三条用例声明的 `must_succeed` 在「写失败」轨迹上**逐条**判红（各在自己的面）。"""
        probes = {
            "AS-003": "aftersale_create",
            "AS-005": "aftersale_create",
            "CH-009": "order_create",
        }
        for cid, tool in probes.items():
            spec = self._case(cid).get("must_succeed") or []
            assert spec, f"{cid} 未声明 must_succeed —— #3778 的效果层断言被移除"
            declared_tools = [str(s.get("tool")) for s in spec]
            assert tool in declared_tools, f"{cid} 声明的写工具不含 {tool}：{declared_tools}"
            issues = self._declared_issues(spec, [_failed_create_round(tool)])
            assert len(issues) == len(spec), (
                f"{cid} 在写失败轨迹上未判红（效果层是空断言）：{issues}")

    def test_declared_effect_assertions_stay_green_when_the_write_succeeded(self):
        """反向护栏：同一批声明在「写成功」轨迹上不报（防「加断言 = 恒红」）。"""
        for cid, tool in (("AS-003", "aftersale_create"), ("AS-005", "aftersale_create"),
                          ("CH-009", "order_create")):
            spec = self._case(cid).get("must_succeed") or []
            r = _round(3, [("order_query", {}), (tool, {})],
                       [("order_query", True), (tool, True)], text="已建单")
            assert self._declared_issues(spec, [r]) == [], f"{cid} 写成功时不应报"