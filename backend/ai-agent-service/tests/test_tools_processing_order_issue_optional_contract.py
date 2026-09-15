# case_ids: PG-016
"""
发加工「加工方 / 交期」的可选性口径一致性（PG-016）——零 LLM 确定性守卫

## 病灶（PG-016 首跑逐轮 trace，mibao 腿 run `34908262839`）

    R5 you=这笔加工单发加工，交期下周三 → ai=「还缺两项信息：1. **加工方**」
    R6 you=确认                        → ai=「两项**必填**信息还没给我：1. **加工方**」
    R7 you=开始加工                    → ai=「当前状态为『已生成』，还没发加工」
    R8 you=确认                        → interact(component=form … formFields=2)
    R9 you=这笔加工单加工完成了，标记完成 → ai=「当前状态仍是『已生成』」
    R10 you=确认                       → interact(component=form … formFields=2)
    ❌ processing_order_update(action=complete) → unmatched expectation
    ❌ must_succeed: processing_order_update 从未被调用 → 没有发生任何写操作

⇒ 指纹 `no_success(processing_order_update)`：agent **一次都没发出过** update，
把「加工方」当成发加工的前置条件反复索要（两次文本 + 两次 form 卡），而用例的
`auto_respond` 只有文本 `fallback: 确认`、填不上那张卡 ⇒ 死循环到轮数耗尽。

## 归因：**产品侧**——LLM 面对的口径与「可强制层」口径不一致

`processor` / `expected_delivery_date` 在**四处可强制层**一致地是**可选**：

  · `ProcessingOrderUpdateTool.parameters`：`required == ["id", "action"]`，
    processor 描述写明「加工方（issue 时**可选**）」
  · `validate_input._VALIDATION_RULES["processing_order_update"]["issue"]["required"] == ["id"]`，
    字段标签「加工方（**可选**）」
  · `ProcessingOrderUpdateRequest.processor` javadoc「issue 时**可选**」
  · `ProcessingOrderService.updateStatus` 对 `issue` 不校验 processor

唯独 **LLM 面对的口径** `prompts/order.md` 的「发加工」行把 `processor=加工方` 写进调用
签名且**不带「可选」标注**——而**同一行**的 `cancel(reason=必填)` 却显式标注必填，
对照之下模型只能读成「发加工要带加工方」。

反证（不是接口必填）：
  · run `34908262839` 的**重试**里 agent **未带 processor** 直接 issue 成功（服务端接受）；
  · run `34867559987` 的 PG-016 首跑直接发出、无索要。
⇒ 时松时紧的不是接口契约，是 prompt 口径。

## 本文件断言什么

把「prompt 声明的可选性 == 可强制层声明的可选性」钉成确定性断言（零 LLM）：
  ① 正向：`order.md` 发加工行必须声明 processor/交期为**可选**，且**不得**写成必填；
  ② 口径一致：可选性声明必须与工具 schema + `validate_input` 的 `required` 一致；
  ③ 出路：发加工行必须含**禁止性条款**（不得为可选字段索要/阻塞/重复发卡）——
     否则「缺字段」这一形态仍然只能死循环；
  ④ 非空证明：检查器喂**改前原文**（逐字取自 `origin/main` 的发加工行）必须报违规，
     且三个违规分支各自可被触发 —— 否则本文件就是一堆「不会红的断言」；
  ⑤ 反向守卫：用 **runner 自己的** `check_must_succeed` × **用例自己声明的**
     `must_succeed`（`ALL_CASES` 的 PG-016）跑合成轨迹 —— 「真的没调 complete」仍必须红。
"""
import os
import re
import sys

from app.tools.processing_order_update import ProcessingOrderUpdateTool

_HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_PATH = os.path.join(
    _HERE, "..", "app", "graph", "skills", "references", "prompts", "order.md"
)
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
RUNNER_DIR = os.path.join(_REPO_ROOT, "tests", "agent_eval")

# ⚠️ 逐字取自 `origin/main` 的「发加工」行（改前原文）——用于证明本文件的断言**会红**。
#    改 prompt 时**不要**同步改这里：它是"病灶快照"，是断言非空的唯一凭据。
PRE_FIX_ISSUE_LINE = (
    "- 发加工：`processing_order_update(action=issue, processor=加工方, "
    "expected_delivery_date=交期)`；开始 `start`；完成 `complete`（提示可发货，不自动发货）；"
    "取消 `cancel(reason=必填)`，取消后订单回退已确认"
)

# ── 「发加工」行的口径检查器（纯函数：可喂改前原文 / 各种突变体，证明每个分支都会红）──
OPTIONAL_MARKER_RE = re.compile(r"可选|选填|非必填")
# 反向：把 processor/交期写成必填（与可强制层口径相反）。分隔符排除 `；;。`
# 以免把同一行后半段的 `cancel(reason=必填)` 误判成 processor 的必填标注。
REQUIRED_MARKER_RE = re.compile(
    r"(processor|expected_delivery_date|加工方|交期)[^；;。]{0,12}必填"
)
# 出路：必须显式禁止「为可选字段原地索要 / 阻塞 / 重复发卡」
EXIT_CLAUSE_RE = re.compile(r"(禁止|不得|不要)[^；;。]{0,40}(索要|当必填|阻塞|卡住|重复|不发)")


def read_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


# 锚点必须是**调用签名**那一行，不能只按「发加工」+ 工具名定位：
# order.md 顶部还有一行路由表 `| 发加工/开始/完成/取消加工单 | processing_order_update |`，
# 先匹配到它就会检查错对象（本文件首版即此 bug —— 正是 §18.3「按可变键定位」的同族形态）。
ISSUE_LINE_ANCHOR = "processing_order_update(action=issue"


def issue_line(prompt_text: str) -> str:
    """取「发加工」的**调用签名行**（含「发加工」且含 `processing_order_update(action=issue`）。"""
    for line in prompt_text.splitlines():
        if "发加工" in line and ISSUE_LINE_ANCHOR in line:
            return line
    return ""


def optional_contract_violations(prompt_text: str) -> list:
    """返回发加工行上违反「可选性口径」的问题清单（空 = 合规）。"""
    line = issue_line(prompt_text)
    if not line:
        return ["锚点缺失：找不到同时含「发加工」与 processing_order_update 的行"]
    issues = []
    if "processor" not in line:
        issues.append("发加工行未提及 processor ⇒ 无从判定其可选性")
    if not OPTIONAL_MARKER_RE.search(line):
        issues.append(
            "发加工行未声明 processor/交期为「可选」⇒ 与工具 schema"
            "（required=['id','action']）和 validate_input（required=['id']）口径不一致，"
            "模型会据此自造必填并反复索要（PG-016 首跑即此形态）"
        )
    if REQUIRED_MARKER_RE.search(line):
        issues.append("发加工行把 processor/交期标成「必填」⇒ 与可强制层口径相反")
    if not EXIT_CLAUSE_RE.search(line):
        issues.append(
            "发加工行未给出「缺可选字段时的可推进出路」（无禁止性条款）"
            "⇒ 缺字段即原地死循环索要"
        )
    return issues


def _runner():
    """导入评测 runner（断言代码的**单一真相源**，不在本文件里复制一份等价物）。"""
    if RUNNER_DIR not in sys.path:
        sys.path.insert(0, RUNNER_DIR)
    import local_runner  # noqa: E402  （路径注入后导入）

    return local_runner


# ── ① / ③ 正向：真实 prompt 必须合规 ────────────────────────────────────────
def test_order_prompt_issue_line_declares_optional_contract():
    """`order.md` 发加工行必须声明 processor/交期可选 + 含「不得死循环索要」的出路。

    ⚠️ 2026-09-15（issue #3917）起，**期望翻转**：加工单工具对 agent 关闭，
    order.md 的「加工单操作」章节（含发加工行）已整体替换为「加工项 vs 加工单
    概念区分 + 不接入声明」⇒ 当前正确状态 = **不存在** `processing_order_update`
    操作行（锚点缺失不再是违规）。恢复接入加工单工具时（registry + order_skill +
    prompt 三处一起恢复），把本断言改回 `violations == []`（本文件 docstring 与
    PRE_FIX_ISSUE_LINE 保留旧口径与病灶快照，作为恢复时的检查器凭据）。
    """
    text = read_prompt()
    line = issue_line(text)
    assert line == "", (
        "order.md 又出现了发加工操作行（processing_order_update(action=issue）——"
        "加工单工具对 agent 未开放（issue #3917），概念区分口径下不应存在操作指引；"
        "若确要恢复接入，请同步恢复 registry 注册 + order_skill 工具绑定，"
        "并把本断言改回 optional_contract_violations(text) == []"
    )
    assert "processing_order_update" not in text, (
        "order.md 不应再引用 processing_order_update 工具（agent 暂不接入，issue #3917）"
    )


# ── ② 口径一致：prompt 的可选性 == 可强制层的 required ───────────────────────
def test_optionality_is_consistent_across_enforced_layers():
    """工具 schema 对 processor 与交期的可选性口径自洽（可强制层的残留契约）。

    ⚠️ 2026-09-15（issue #3917）：加工单工具对 agent 关闭 —— 工具类保留但未注册，
    `validate_input` 的加工单闸门规则已随注册表移除（死键不变式，见
    `tests/test_tools_validate_input.py::TestValidationRuleKeysAreLive`）⇒ 本测试只钉
    **工具类自身 schema**（恢复接入时 validate_input 规则需按 git 历史版本补回并
    与本 schema 对齐）；prompt 侧由
    `test_order_prompt_issue_line_declares_optional_contract` 按新口径守护。
    """
    schema = ProcessingOrderUpdateTool.parameters
    assert schema["required"] == ["id", "action"], (
        "工具 schema 的 required 变了 ⇒ 请同步 validate_input / 服务端 DTO，"
        f"不要只改一处（现为 {schema['required']}）"
    )
    for field in ("processor", "expected_delivery_date"):
        assert field in schema["properties"], f"{field} 必须仍在工具参数里（只是可选）"
        assert field not in schema["required"], f"{field} 不应成为工具层必填"


# ── ④ 非空证明：检查器在「改前原文」上必须报违规，且每个分支都能被触发 ─────────
def test_checker_flags_pre_fix_prompt_verbatim():
    """改前原文（逐字 origin/main）必须被判违规 —— 否则 ① 是空断言。"""
    violations = optional_contract_violations(PRE_FIX_ISSUE_LINE)
    assert violations, "检查器对改前原文无反应 ⇒ ① 的断言不会红（空断言）"
    assert any("可选" in v for v in violations), violations


def test_each_violation_branch_is_reachable():
    """三个违规分支（未标可选 / 未提及 processor / 标成必填 / 无出路）必须各自可被触发。"""
    base = "- 发加工：`processing_order_update(action=issue, processor=加工方)`；开始 `start`"

    no_processor = optional_contract_violations(
        "- 发加工：`processing_order_update(action=issue)`；开始 `start`"
    )
    assert any("未提及 processor" in v for v in no_processor), no_processor

    no_optional = optional_contract_violations(base)
    assert any("未声明" in v for v in no_optional), no_optional

    marked_required = optional_contract_violations(base + "（processor 必填）")
    assert any("标成「必填」" in v for v in marked_required), marked_required

    no_exit = optional_contract_violations(base + "（processor/交期可选）")
    assert any("出路" in v for v in no_exit), no_exit
    # 三条都补齐后必须转绿（证明检查器不是"永远报错"）
    assert optional_contract_violations(
        base + "（processor/交期可选）；禁止把它们当必填去索要或因此不发加工单"
    ) == []


# ── ⑤ 反向守卫：真失败形态（从未调用 complete）仍必须红 ──────────────────────
def _round(round_no: int) -> dict:
    return {"__round": round_no, "tool_calls": [], "tool_results": []}


def test_case_expectation_still_reds_when_complete_never_called():
    """用**用例自己声明的** must_succeed × **runner 自己的**断言跑合成轨迹。

    这条是「不许为了让用例变绿而删写操作期望」的机械守卫：
    真的没调 `action=complete` ⇒ `check_must_succeed` 必须报违规；
    真的调成功 ⇒ 必须放行。两侧都断言，防止断言退化成恒真/恒假。
    """
    lr = _runner()
    matching = [c for c in lr.ALL_CASES if c.id == "PG-016"]
    assert len(matching) == 1, (
        f"ALL_CASES 里 PG-016 应有且仅有 1 条（实为 {len(matching)}）⇒ 本守卫失锚"
    )
    case = matching[0]
    assert case.must_succeed == [{"tool": "processing_order_update", "action": "complete"}], (
        f"PG-016 的 must_succeed 被改动了（现为 {case.must_succeed}）"
        "—— 写操作期望不得放宽/删除"
    )

    # 真失败形态：全程没调过 processing_order_update ⇒ 必须红
    never_called = lr.check_must_succeed([_round(i) for i in range(1, 9)], case.must_succeed)
    assert never_called, "从未调用写工具却放行 ⇒ 反向守卫失效"

    # 仅发过 issue/start、从未 complete ⇒ 也必须红（action 过滤不得被子串顶替）
    partial = [
        {
            "__round": 6,
            "tool_calls": [{"name": "processing_order_update", "args": {"id": "JG-1", "action": "issue"}}],
            "tool_results": [{"tool": "processing_order_update", "result": {"success": True}}],
        }
    ]
    assert lr.check_must_succeed(partial, case.must_succeed), "只 issue 没 complete 却放行"

    # 真成功形态：complete 成功一次 ⇒ 必须放行（防"恒红"）
    completed = [
        {
            "__round": 6,
            "tool_calls": [{"name": "processing_order_update", "args": {"id": "JG-1", "action": "complete"}}],
            "tool_results": [{"tool": "processing_order_update", "result": {"success": True}}],
        }
    ]
    assert lr.check_must_succeed(completed, case.must_succeed) == []
