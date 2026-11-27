# case_ids: CH-009
"""`expectations: reply` —— 「本轮**有产出**」的产出侧语义 token（issue #9280）。

## 为什么加这个 token（CH-009 六周腐坏两次的类级根治）

被测行为（一字未变）= 「`__FORM__` 负载注入后本轮**必须有产出**（表单没被静默丢掉）」。
旧写法只能把「合格落地形态」逐条枚举成**工具名**，于是每换一次模型选择的只读工具就红一次：

| 时点 | 期望里的分支 | 红因 |
|---|---|---|
| 2026-10-16 前 | `direct_reply or order_create or interact` | 模型改走只读查询 ⇒ 三个分支都不命中 |
| 2026-10-16 | `direct_reply or interact` → 补 `customer_manage(action=list)` | — |
| 2026-11-27（run 46002922920） | 同上 | 模型改走 `order_query`（B 端 order 域只读，行为**正确**） |

⇒ 判据锚回**行为**（有产出），工具选择回到「实现细节」：

* `direct_reply` = 该轮**无** tool_calls 且有 final_text；
* `reply`（本文件）= 该轮**有** final_text（**工具调用不限**）。

## 判别力**不靠**它独自撑（所以它不是"放宽"）

本 token 只保证「有产出」。CH-009 同时用 `want_text`（客户名/手机号必须出现）兜住
「有产出但把负载丢掉」那一格 —— 见下方 `test_generic_greeting_passes_old_but_fails_want_text`：
**旧** `direct_reply` 期望在「零工具调用 + 一句客套话」上判绿，而 `want_text` 判红。

## 判据（本文件）

1. 记录里那一轮（`tools=['order_query']` + 文本）在新 token 下**绿**、在旧期望下**红**；
2. 一个字都没产出 ⇒ 红（`no_output(reply)`，与 `direct_reply` 的红族方向相反）；
3. `reply` 可与 ` or ` 组合（本分支不命中时继续尝试其它分支）；
4. `direct_reply` 语义**逐字未变**（防"顺手改坏老 token"）；
5. `reply` 已登记为伪工具（`eval_case_filter.PSEUDO_TOOLS`）—— 否则 Case Coverage Gate 会把它读成
   「声明了不存在的工具 / 用例挂错端」；
6. CH-009 的声明面：`expectations == ["reply"]` 且 `want_text` 非空（防"把产出侧断言也一起删了"）。
"""
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
sys.path.insert(0, str(REPO_ROOT / ".github"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；一旦被调用即抛错）。"""
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

#: run 46002922920 的 CH-009 那一轮（逐字来自 artifacts `post-deploy-eval-mibao`）。
#: `keyword=138****8000` 是**日志侧掩码**（`_arg_scalar`），真实入参是表单里的真号；
#: 本文件只用它验证「有工具调用 + 有文本」这一形态，与掩码无关。
TRACE_CH009 = {
    "tool_calls": [{"name": "order_query",
                    "args": {"action": "list", "keyword": "138****8000", "page_size": 10}}],
    "final_text": "📋 收到张三的下单信息了，但**建单不在我的能力内**——黄金策在订单域现在只做查询与分析，"
                  "下单得请您在后台操作：",
}

#: 同一轮的「假产出」形态：零工具调用 + 一句与表单无关的客套话。
TRACE_GENERIC_GREETING = {"tool_calls": [], "final_text": "您好，请问有什么可以帮您？"}

#: 改判**前**的期望原文（逐字，用于「旧期望在同一记录上判红」的红证）。
OLD_EXPECTATION = "direct_reply or interact or customer_manage(action=list)"


def test_recorded_turn_is_red_under_old_expectation_and_green_under_reply():
    """同一份记录：旧期望红（六周腐坏的形态）→ 新 token 绿（行为本来就是对的）。"""
    old_ok, old_detail = lr.check_expectation(TRACE_CH009, OLD_EXPECTATION)
    assert old_ok is False
    assert old_detail == f"unmatched expectation: {OLD_EXPECTATION[:80]}"

    new_ok, new_detail = lr.check_expectation(TRACE_CH009, "reply")
    assert new_ok is True
    assert new_detail == "reply (final_text present; tool calls allowed)"


def test_no_output_at_all_is_red():
    """一个字都没产出（表单被静默丢掉 / 注入链路炸了）⇒ 红，且红族具名 `no_output(reply)`。"""
    ok, detail = lr.check_expectation({"tool_calls": [], "final_text": ""}, "reply")
    assert ok is False
    assert detail == "expected reply (final_text) but got none"
    assert lr._expectation_atom("reply", detail) == "no_output(reply)"


def test_reply_composes_with_or_and_falls_through():
    """`reply or <另一分支>`：本分支不命中时继续尝试其它分支（与 `direct_reply or …` 同语义）。"""
    # 无文本、但有 interactive 事件 ⇒ 走 `interact` 分支（卡片三条发射路径里 2/3 条无 tool_call）
    interact_round = {"tool_calls": [], "final_text": "",
                      "interactive": [{"component": "choice"}]}
    ok, detail = lr.check_expectation(interact_round, "reply or interact")
    assert ok is True
    assert "interact" in detail

    # 无文本、但有 `order_query` 调用 ⇒ 走工具分支（裸工具名分支按跨轮工具名汇总匹配）
    tool_round = {"tool_calls": [{"name": "order_query", "args": {"action": "list"}}],
                  "final_text": "", "__all_tool_names": ["order_query"]}
    tool_ok, tool_detail = lr.check_expectation(tool_round, "reply or order_query")
    assert tool_ok is True
    assert tool_detail == "tool 'order_query' matched"

    # 无文本、且其它分支也不命中 ⇒ 仍然红
    bad_ok, _ = lr.check_expectation({"tool_calls": [], "final_text": ""},
                                     "reply or interact")
    assert bad_ok is False


def test_direct_reply_semantics_unchanged():
    """老 token 一字未改：零工具调用 + 文本 ⇒ 绿；有工具调用 ⇒ 红（防顺手改坏）。"""
    ok, detail = lr.check_expectation(TRACE_GENERIC_GREETING, "direct_reply")
    assert ok is True
    assert detail == "direct reply without tool call"

    red_ok, red_detail = lr.check_expectation(TRACE_CH009, "direct_reply")
    assert red_ok is False
    assert red_detail == "expected direct_reply (no tool) but got tool calls"


def test_generic_greeting_passes_old_but_fails_want_text():
    """判别力**加强**的红证：客套话能骗过旧 `direct_reply`，但 `want_text` 抓住它。"""
    ok, _ = lr.check_expectation(TRACE_GENERIC_GREETING, "direct_reply")
    assert ok is True, "夹具前提：旧期望对「零工具调用 + 客套话」判绿（这正是要堵的假绿）"

    issues = lr.check_want_text([TRACE_GENERIC_GREETING],
                                [{"any_of": ["张三", "13800138000", "138****8000"]}])
    assert len(issues) == 1
    assert "张三" in issues[0]

    # 真产出（回复点到客户身份）⇒ 该断言成立
    assert lr.check_want_text([TRACE_CH009],
                              [{"any_of": ["张三", "13800138000", "138****8000"]}]) == []


def test_reply_is_registered_as_pseudo_tool():
    """`reply` 不是工具名 ⇒ 必须登记进伪期望集合，否则工具集校验会把它读成"不存在的工具"。"""
    import eval_case_filter

    assert "reply" in eval_case_filter.PSEUDO_TOOLS
    assert "direct_reply" in eval_case_filter.PSEUDO_TOOLS
    # 反证：伪工具集合只吃**声明面**，不把 `reply` 误算成用例覆盖的工具
    assert "reply" not in eval_case_filter.case_expectation_tools(
        {"expectations": ["reply"]})


def test_ch009_declares_reply_plus_produce_side_assertion():
    """CH-009 的声明面：期望只剩产出侧 token，且产出侧断言（want_text）必须一起在。"""
    import yaml

    doc = yaml.safe_load((REPO_ROOT / ".github" / "cases" / "chat.yml").read_text(
        encoding="utf-8"))
    case = next(c for c in doc["cases"] if c["id"] == "CH-009")
    assert case["expectations"] == ["reply"]
    assert case["want_text"] == [{"any_of": ["张三", "13800138000", "138****8000"]}]
    # 写分支的条件效果层 + 自清理 + 前置自断言一字未动（本单只改期望与产出侧断言）
    assert case["must_succeed"] == [{"tool": "order_create", "only_if_called": True}]
    assert case["namespaces"] == ["customer_phone:13800138000"]
    assert case["precondition"] == [{"type": "order_count_for_phone",
                                     "source": "13800138000", "max_growth": 1}]
