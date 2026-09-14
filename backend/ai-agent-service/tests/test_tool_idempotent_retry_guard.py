"""非幂等写工具不得被 `_self_correct_retry` 自动重试 — 回归测试（issue #3564）

## 缺陷
`base_skill._self_correct_retry` 的判据只有「`success=False` + 有 `suggestion`」，
**不看工具幂等性**：于是 `order_create`（建单）/ `aftersale_create`（建工单）/
`human_handoff`（转人工）/ `notification_manage`（发通知）这类**非幂等写工具**
在失败时会被同一参数自动重试一次 → **重复副作用**（重复建单/重复转人工/重复通知）。

真实触发面很宽：工具「第一次已产生副作用但返回 success=False」（下游超时/响应丢失），
或 `suggestion` 本身就是"参数怎么补"的引导语（工具作者写 suggestion 时想的是
"让 LLM 引导用户修好再来"，而不是"让框架立刻重放"）。

## 修复
护栏放在 **retry 侧**（机制层），不靠每个工具在 suggestion 里写"请勿重试"自觉：
`_self_correct_retry` 消费 `BaseTool.idempotent`（MCP 风格标注，`app/tools/base.py:86`，
**已是既有单一真值**——`get_schema()` 早就用它拼 `NON_IDEMPOTENT` 标签给 LLM 看），
`idempotent=False` 时**不重试**，把失败 + suggestion 原样交回模型决策，并留日志
`non-idempotent: retry suppressed`。

## 静态锁（L0 / 零 LLM）
`BaseTool.idempotent` 默认 `True`，新写工具若忘记声明就会**默认落进"可重试"**。
故本文件同时锁定：注册表里**每个写工具（read_only=False）必须显式声明 idempotent**
（在自己的类体里表态，不能吃基类默认值）——未表态即红，强制新工具落地时做一次幂等性判断。
（migao-dev-flow §16.1：结构性改动必须带静态不变式，禁止只靠真实 LLM 全旅程去撞。）
"""
# case_ids: DF-008, DF-011, CH-013, CH-015
import json
from unittest.mock import MagicMock, patch

from app.graph.skills.base_skill import _self_correct_retry
from app.tools.base import BaseTool, ToolContext, ToolResult


# ── 替身 ────────────────────────────────────────────────────────────────────

class _WriteTool(BaseTool):
    """写工具替身：参数不完整（name 为空）→ 失败；修正后 → 成功。

    调用参数与成败的对应关系是**幂等**的（同样的参数永远给同样的结果），
    这样断言与"执行了几次"无关，只取决于"是否发生了重试执行"。
    """

    name = "fake_write_tool"
    description = "写工具替身（用于非幂等重试护栏测试）"
    read_only = False
    parameters = {"type": "object", "properties": {"name": {"type": "string"}}}

    def __init__(self):
        super().__init__()
        self.calls: list[dict] = []

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        if not kwargs.get("name"):
            return ToolResult(
                success=False,
                error="bad_param",
                message="参数不完整",
                suggestion="请补全 name 后重试",
            )
        return ToolResult(success=True, data={"created": True}, message="创建成功")


class _NonIdempotentWriteTool(_WriteTool):
    """非幂等写（等价 order_create / human_handoff 的语义）。"""

    name = "fake_non_idempotent_write"
    idempotent = False


class _IdempotentWriteTool(_WriteTool):
    """幂等写（等价 product_update / sku_update：按 id 覆盖，重复调用结果一致）。"""

    name = "fake_idempotent_write"
    idempotent = True


class _IdempotentReadTool(_WriteTool):
    """只读 + 幂等（等价 order_query）。"""

    name = "fake_idempotent_read"
    read_only = True
    idempotent = True


class _NoDeclarationTool(BaseTool):
    """写工具但**不声明** idempotent（吃基类默认 True）—— 静态锁必须拦下它。"""

    name = "fake_undeclared_write"
    description = "未表态的写工具"
    read_only = False

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(success=True)


class _FakeLLM:
    """suggestion_llm 替身：返回一组"修正后的参数"JSON。"""

    def __init__(self, payload: dict):
        self.temperature = 0.0
        self._payload = payload
        self.invoked: list[str] = []

    async def ainvoke(self, messages):
        self.invoked.append(messages[0].content if messages else "")
        return MagicMock(content=json.dumps(self._payload, ensure_ascii=False))


_CTX = ToolContext(tenant_id=999, user_id="u-test", session_id="s-test", role="admin")
_STATE = {"session_id": "s-test", "tenant_id": 999}
_FAILED = {
    "success": False,
    "error": "bad_param",
    "message": "参数不完整",
    "suggestion": "请补全 name 后重试",
}


async def _retry(tool, result_dict=None) -> tuple:
    """复刻调用点语义（`base_skill.py` 的 `if corrected: result_str, result_dict = corrected`）。

    Returns:
        (outcome, effective)：
        - outcome = `_self_correct_retry` 原返回值（None = 未重试）；
        - effective = **模型最终看到的工具结果 dict** —— 断言一律以业务口径（这个 payload）
          为准，而不是断言哨兵值，这样"护栏生效"与"模型收到什么"是同一件事。
    """
    original = dict(result_dict or _FAILED)
    outcome = await _self_correct_retry(
        tool, {"name": ""}, _CTX, "test_skill",
        dict(original), "s-test", 999, dict(_STATE),
    )
    effective = outcome[1] if outcome else original
    return outcome, effective


# ── 行为护栏：非幂等不重试 ───────────────────────────────────────────────────

class TestNonIdempotentRetrySuppressed:
    """非幂等写工具：即使失败 + 带 suggestion，也不得自动重试（否则重复副作用）。

    断言口径：`tool.calls` 为空 = **没有任何"重放"发生**（首次失败是调用方给的既成事实，
    重试才是本护栏要拦的那一次真实副作用）；`effective` = 模型侧实际收到的结果。
    """

    async def test_non_idempotent_write_tool_not_retried(self):
        tool = _NonIdempotentWriteTool()
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=llm,
        ) as factory:
            _, effective = await _retry(tool)

        assert factory.call_count == 0, "非幂等写工具不得触发 suggestion_llm（重试入口必须关闭）"
        assert llm.invoked == [], "非幂等写工具不得调用修正 LLM"
        assert tool.calls == [], f"非幂等写工具不得被重放执行（实际 {tool.calls!r}）→ 重复副作用"
        # 业务口径：模型拿到的仍是**原始失败 + suggestion**（交回模型决策），不是被重试"救"成的成功
        assert effective["success"] is False, "模型必须收到失败结果（而非重试后的成功）"
        assert effective["error"] == "bad_param"
        assert effective["suggestion"] == _FAILED["suggestion"], "suggestion 必须原样交回模型"

    async def test_human_handoff_like_tool_not_retried(self):
        """转人工（CH-013/015）：非幂等，重复调用会创建重复人工会话。"""
        tool = _NonIdempotentWriteTool()
        tool.name = "human_handoff_like"
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=_FakeLLM({"name": "修正后的名字"}),
        ):
            _, effective = await _retry(tool)
        assert tool.calls == [], "转人工类工具不得被重放（重复人工会话）"
        assert effective["success"] is False

    async def test_tool_without_idempotency_attribute_not_retried(self):
        """未声明 idempotent 的**非 BaseTool** 替身：fail-safe 视为不可重试。"""

        class _Bare:
            name = "bare_write"
            read_only = False
            parameters = {"type": "object", "properties": {"name": {"type": "string"}}}

            def __init__(self):
                self.calls = 0

            async def execute(self, context, **kwargs):
                self.calls += 1
                return ToolResult(success=False, suggestion="再试一次")

        tool = _Bare()
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=_FakeLLM({"name": "修正后的名字"}),
        ):
            _, effective = await _retry(tool)
        assert tool.calls == 0, "缺幂等性标注的工具不得被重试"
        assert effective["success"] is False


# ── 防回归：幂等工具既有重试能力不得被关闭 ──────────────────────────────────

class TestIdempotentRetryPreserved:
    """幂等工具（只读查询 / 按 id 覆盖写）：既有自动重试能力必须保留。"""

    async def test_idempotent_write_tool_still_retried(self):
        tool = _IdempotentWriteTool()
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=llm,
        ) as factory:
            outcome, effective = await _retry(tool)

        assert factory.call_count == 1, "幂等写工具的既有重试不得被关闭"
        # 业务口径：重试成功 → 模型收到的是**修正后的成功结果**（含真实数据）
        assert effective["success"] is True, "幂等写工具修正成功应把成功结果交回模型"
        assert effective["data"] == {"created": True}
        assert json.loads(outcome[0])["data"] == {"created": True}
        assert tool.calls == [{"name": "修正后的名字"}], "幂等写工具应带修正参数重试一次"

    async def test_idempotent_read_tool_still_retried(self):
        tool = _IdempotentReadTool()
        llm = _FakeLLM({"name": "修正后的名字"})
        with patch(
            "app.graph.skills.base_skill.LLMFactory.create_suggestion_llm",
            return_value=llm,
        ):
            _, effective = await _retry(tool)

        assert effective["success"] is True
        assert tool.calls == [{"name": "修正后的名字"}]

    async def test_no_suggestion_still_no_retry(self):
        """既有语义不变：无 suggestion 时不重试。"""
        tool = _IdempotentWriteTool()
        _, effective = await _retry(tool, {"success": False, "message": "失败"})
        assert tool.calls == []
        assert effective["success"] is False


# ── 静态锁（L0）：每个写工具必须显式表态幂等性 ─────────────────────────────

def _declares_idempotency_explicitly(tool) -> bool:
    """工具是否在自己的类体里显式声明了 idempotent（不吃 BaseTool 默认值）。

    沿 MRO 找第一个声明者：只要在 `BaseTool` 之前有类声明过就算显式
    （允许工具通过中间基类表达，如 `class _BoomTool(InteractTool)`）。
    """
    for klass in type(tool).__mro__:
        if klass is BaseTool:
            return False
        if "idempotent" in klass.__dict__:
            return True
    return False


def _unclassified_write_tools(tools) -> list[str]:
    """写工具（read_only=False）中**未显式表态**幂等性的工具名。"""
    return sorted(t.name for t in tools if not t.read_only and not _declares_idempotency_explicitly(t))


class TestIdempotencyClassificationLock:
    """静态锁：注册表里每个写工具都必须显式归类为幂等/非幂等。

    价值：`BaseTool.idempotent` 默认 `True` = 「未表态」会静默落进"可重试"。
    新写工具落地时必须被迫表态，否则 CI 红（本测试在 pr-check 的 ai-agent 单测里跑）。
    """

    def test_every_registered_write_tool_declares_idempotency(self):
        from app.tools.registry import create_default_registry

        tools = create_default_registry().get_all_tools()
        missing = _unclassified_write_tools(tools)
        assert missing == [], (
            "以下写工具未显式声明 idempotent（无法判断是否允许自动重试）："
            f"{missing}。请在工具类体里写 idempotent = True/False 表态。"
        )

    def test_lock_can_go_red_on_unclassified_write_tool(self):
        """锁必须真的能红：未表态的写工具会被抓出来（防"恒绿假锁"）。"""
        assert _unclassified_write_tools([_NoDeclarationTool()]) == ["fake_undeclared_write"]

    def test_lock_ignores_read_only_tools(self):
        """只读工具无需表态（重试只读查询无副作用，强制表态是纯噪声）。"""

        class _UndeclaredRead(BaseTool):
            name = "fake_undeclared_read"
            description = "未表态的只读工具"
            read_only = True

            async def execute(self, context, **kwargs) -> ToolResult:
                return ToolResult(success=True)

        assert _unclassified_write_tools([_UndeclaredRead()]) == []

    def test_inherited_declaration_counts_as_classified(self):
        """通过中间基类表态 → 视为已归类（避免误伤继承形态的工具）。"""
        assert _unclassified_write_tools([_NonIdempotentWriteTool()]) == []
        assert _unclassified_write_tools([_IdempotentWriteTool()]) == []

    def test_real_registry_has_known_non_idempotent_writes(self):
        """真值抽样：核心非幂等写工具必须仍是 idempotent=False（防被顺手改成 True）。"""
        from app.tools.registry import create_default_registry

        by_name = {t.name: t for t in create_default_registry().get_all_tools()}
        for name in (
            "order_create",       # 建单
            "aftersale_create",   # 建售后工单
            "human_handoff",      # 转人工
            "notification_manage",  # 发通知
            "customer_manage",    # 建客户
            "product_manage",     # 建商品
            "role_manage",        # 建/删角色
            "finance_api",        # 财务写
            "inventory_manage",   # 库存调整
        ):
            assert name in by_name, f"{name} 未注册"
            assert by_name[name].idempotent is False, (
                f"{name} 是非幂等写工具，idempotent 必须为 False（否则失败会被自动重试 → 重复副作用）"
            )
