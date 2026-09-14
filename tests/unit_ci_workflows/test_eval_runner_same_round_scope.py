# case_ids: AS-007, PG-016, PP-006, OR-026
"""`local_runner` 断言实现的**口径/同轮精度**缺陷（issue #3681，确定性层）。

本文件锁住两条**在归因报告里被确证**的断言实现缺陷（零 LLM、纯函数，秒级）：

| 缺陷 | 证据 |
|---|---|
| `_processing_ask_in_round` **两条分支口径不一致**（假红温床）：卡片分支接受「加工项」**或「加工」**（OR-017 run 34670989760 修过），文本分支却**必须**出现字面「加工项」三字 → agent 用文本主动询问加工项（「刺绣工艺（按面积）需要选哪种？」）被误判"没问" → `order_before[processing_ask …]` 判「全程未调用」→ **整例 score 0** | 归因报告 G2 §3.3（`acceptance/2026-09-15/agent-gap-triage/REPORT.md`）：AS-007 `data_checks` 自己写着「文本询问亦可，语义由 order_before 保证」（`.github/cases/aftersales.yml:346`）⇒ **用例声明与检测实现不一致**。AS-007 真实波动 run `34812509606`（0.75）与该假红同形 |
| `check_must_succeed` / `check_must_fail` 声明 `action` 时**同轮不精确**（假绿）：`tool_result` 事件不带 args，旧实现只按**工具名**取该轮全部结果 → 同一轮里**别的 action 成功**也能让 `must_succeed[action=X]` 通过 | 同族先例：#3667 为 `_first_successful_payload` 做的同轮 payload 对齐（PR #3673）；PG-016 的 `must_succeed[action=complete]`（`.github/cases/processing-order.yml:512`）正处这个形态 |

为什么必须由**单测**锁住：两条都是"取错证据/口径不一致"型缺陷，症状是假红/假绿，
**假绿在评测报告里看不出来**（报告一片全绿），假红则会让正确行为被记为"没做到"。
真实 LLM 重放既慢又带方差，不可能每次改动都靠它兜底（`migao-dev-flow` §16.1：L0 静态不变式优先）。

⚠️ 本目录（`tests/unit_ci_workflows`）跑在 CI 的 `ci workflow helper unit tests` job 里，
该 job 只 `pip install pytest pyyaml`（见 `.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` → 见下方 `_load_runner()` 的最小替身。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身）。

    被锁的函数都是**纯函数**（吃 `results` 列表、吐 issue 列表），不该因缺一个 HTTP
    客户端而不可测。替身只在 httpx 真的缺失时注入，且一旦被调用即抛错 ——
    单测不得真实发起 HTTP（`migao-dev-flow` §9.2 红线）。
    """
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:                  # 只满足模块级 `import httpx` 与类型引用
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _round(rnd, calls, results, text=""):
    """构造一轮 `results` 条目（与 `test_eval_runner_assertion_scope.py` 同形）。

    calls   : [(tool, action)]（action=None/"" 表示该调用不带 action 参数）
    results : [(tool, success, data)]（与该轮**同名工具**的调用按顺序对应）
    """
    return {
        "__round": rnd,
        "tool_calls": [
            {"name": t, "args": ({**({"action": a} if a else {})})} for t, a in calls
        ],
        "tool_results": [
            {"tool": t, "result": {"success": ok, "data": d}} for t, ok, d in results
        ],
        "final_text": text,
    }


# ── ① `_processing_ask_in_round` 的文本分支口径（AS-007 假红）──────────────────

class TestProcessingAskTextScope:
    """文本询问与卡片询问必须**同口径**：问的是"加工项/加工工艺"，不是"有没有这三个字"。

    真值内核**不放宽**：仍要求"询问意图"（陈述句不得算问）。
    """

    def test_text_ask_without_the_exact_three_chars_is_true(self):
        """agent 用自然表述问加工项（不含「加工项」三字）→ 必须判 True（修复前 False）。

        实例取自归因报告 G2：真实 run 的 agent 会说「刺绣工艺（按面积）需要选哪种？」；
        卡片分支早就接受「加工」二字（OR-017 先例），文本分支却要求字面三字 ⇒ 假红。
        """
        for text in (
            "这款面料需要加刺绣工艺吗？",
            "刺绣工艺（按面积）需要选哪种？",
            "这款支持打孔加工，要一起做吗？",
        ):
            assert lr._processing_ask_in_round(
                {"__round": 3, "tool_calls": [], "final_text": text}) is True, text

    def test_plain_statement_is_not_an_ask(self):
        """纯陈述句（无询问意图）→ 不得误判 True（防放宽过头）。"""
        for text in (
            "您的订单已发货，预计明天送达。",
            "这款窗帘的工艺是刺绣，已记录。",
            "好的，已为您创建换货工单。",
            "加工已完成，工人今天会发货。",
            "该商品无可用加工项。",
            "",
        ):
            assert lr._processing_ask_in_round(
                {"__round": 3, "tool_calls": [], "final_text": text}) is False, text

    def test_card_ask_still_true(self):
        """卡片分支既有行为不变（防改动误伤 OR-017 先例）。"""
        r = {"__round": 2, "final_text": "",
             "tool_calls": [{"name": "interact",
                             "args": {"component": "choice",
                                      "title": "这款窗帘支持加工哦，需要帮您加上吗？",
                                      "options": [{"value": "proc_item_1"}]}}],
             "tool_results": []}
        assert lr._processing_ask_in_round(r) is True

    def test_text_ask_does_not_need_a_card(self):
        """纯文本询问（无 interact 调用）也要被判为"问了" —— AS-007 的文本路径。"""
        assert lr._processing_ask_in_round(
            {"__round": 4, "tool_calls": [], "tool_results": [],
             "final_text": "换货方案里需要加哪些加工项？"}) is True


# ── ② `must_succeed` / `must_fail` 的 action 同轮精度（假绿）──────────────────

_TOOL = "processing_order_update"


class TestMustSucceedActionSameRoundPrecision:
    """声明 `action` 时，成功必须是**那次调用**的成功（同轮别的 action 不许顶替）。

    证据：PG-016 的 `must_succeed[action=complete]`（`.github/cases/processing-order.yml:512`）——
    状态机三步（issue → start → complete）走的是**同一个** `processing_order_update`。
    """

    def test_other_action_success_in_same_round_does_not_satisfy(self):
        """同轮只有 `action=issued` 成功、`complete` 那一次被拒 → **必须判红**（修复前假绿）。"""
        results = [_round(
            1,
            [(_TOOL, "issued"), (_TOOL, "complete")],
            [(_TOOL, True, {"action": "issued"}),
             (_TOOL, False, {"error": "非法状态迁移"})],
        )]
        issues = lr.check_must_succeed(results, [{"tool": _TOOL, "action": "complete"}])
        assert issues, "同轮别的 action 成功不得算作 complete 成功（假绿）"

    def test_other_action_success_in_later_round_does_not_satisfy(self):
        results = [
            _round(1, [(_TOOL, "issued")], [(_TOOL, True, {"action": "issued"})]),
            _round(2, [(_TOOL, "complete")],
                   [(_TOOL, False, {"error": "缺少确认"})]),
        ]
        assert lr.check_must_succeed(results, [{"tool": _TOOL, "action": "complete"}])

    def test_declared_action_own_success_still_passes(self):
        """反向：该 action 自己成功 → 仍判绿（不许收紧过头造新假红）。"""
        results = [
            _round(1, [(_TOOL, "issued")], [(_TOOL, True, {"action": "issued"})]),
            _round(2, [(_TOOL, "complete")], [(_TOOL, True, {"action": "complete"})]),
        ]
        assert lr.check_must_succeed(results, [{"tool": _TOOL, "action": "complete"}]) == []

    def test_declared_action_success_with_other_action_failure_same_round(self):
        """同轮：声明 action 成功、别的 action 失败 → 判绿（对齐到"那一次"）。"""
        results = [_round(
            1,
            [(_TOOL, "complete"), (_TOOL, "cancel")],
            [(_TOOL, True, {"action": "complete"}),
             (_TOOL, False, {"error": "无权限"})],
        )]
        assert lr.check_must_succeed(results, [{"tool": _TOOL, "action": "complete"}]) == []

    def test_blocked_then_success_across_rounds_still_passes(self):
        """跨轮语义不变：先被门禁拦一次、后一轮该 action 成功 → 通过。"""
        results = [
            _round(1, [(_TOOL, "complete")], [(_TOOL, False, {"error": "缺少确认"})]),
            _round(2, [(_TOOL, "complete")], [(_TOOL, True, {"action": "complete"})]),
        ]
        assert lr.check_must_succeed(results, [{"tool": _TOOL, "action": "complete"}]) == []

    def test_no_action_keeps_tool_level_semantics(self):
        """不声明 action（单 action 工具）→ 旧语义原样（防误伤存量用例）。"""
        results = [_round(1, [(_TOOL, "issued")], [(_TOOL, True, {"action": "issued"})])]
        assert lr.check_must_succeed(results, [{"tool": _TOOL}]) == []

    def test_unalignable_round_does_not_claim_never_called(self):
        """对不齐的合成轨迹（有调用、结果数不等）→ 得红，但**不得**谎报"从未被调用"。

        对不齐时（合成轨迹/节点重放）回退**工具级**旧语义 —— 判定结论（红）不变，
        但措辞不能从"调了没成"退化成"从未调用"（那会把"确实调过"说成"没调"，误导归因）。
        """
        r = {"__round": 1,
             "tool_calls": [{"name": _TOOL, "args": {"action": "complete"}},
                            {"name": _TOOL, "args": {"action": "cancel"}}],
             "tool_results": [{"tool": _TOOL,
                               "result": {"success": False, "error": "无权限"}}],
             "final_text": ""}
        issues = lr.check_must_succeed([r], [{"tool": _TOOL, "action": "complete"}])
        assert issues and "从未被调用" not in issues[0] and "无一成功" in issues[0]


class TestMustFailActionSameRoundPrecision:
    """`must_fail[action=X]` 是 `must_succeed` 的镜像：只有 **X 自己**成功才算违规。"""

    def test_other_action_failure_same_round_is_not_a_violation(self):
        """同轮别的 action 失败、声明的 action 压根没调用 → 不得误判违规（假红）。"""
        results = [_round(
            1,
            [(_TOOL, "complete")],
            [(_TOOL, False, {"error": "非法状态迁移"})],
        )]
        assert lr.check_must_fail(results, [{"tool": _TOOL, "action": "cancel"}]) == []

    def test_other_action_success_same_round_is_not_a_violation(self):
        """同轮别的 action 成功、声明 action 未调用 → 不得算 X 成功（假绿方向）。"""
        results = [_round(
            1,
            [(_TOOL, "issued")],
            [(_TOOL, True, {"action": "issued"})],
        )]
        assert lr.check_must_fail(results, [{"tool": _TOOL, "action": "cancel"}]) == []

    def test_declared_action_own_success_still_violates(self):
        """反向：该 action 自己成功了 → 仍判违规（不许收紧过头漏掉真违规）。"""
        results = [_round(
            1,
            [(_TOOL, "issued"), (_TOOL, "cancel")],
            [(_TOOL, True, {"action": "issued"}),
             (_TOOL, True, {"action": "cancel"})],
        )]
        issues = lr.check_must_fail(results, [{"tool": _TOOL, "action": "cancel"}])
        assert issues and "cancel" in issues[0] and "R1" in issues[0]

    def test_declared_action_failure_while_other_succeeds_is_clean(self):
        """同轮：声明 action 失败、别的 action 成功 → 合格拒绝，不算违规。"""
        results = [_round(
            1,
            [(_TOOL, "cancel"), (_TOOL, "issued")],
            [(_TOOL, False, {"error": "无权限"}),
             (_TOOL, True, {"action": "issued"})],
        )]
        assert lr.check_must_fail(results, [{"tool": _TOOL, "action": "cancel"}]) == []

    def test_no_action_keeps_tool_level_semantics(self):
        """不声明 action → 旧语义原样（任一成功即违规）。"""
        results = [_round(1, [(_TOOL, "issued")], [(_TOOL, True, {"action": "issued"})])]
        assert lr.check_must_fail(results, [{"tool": _TOOL}])
