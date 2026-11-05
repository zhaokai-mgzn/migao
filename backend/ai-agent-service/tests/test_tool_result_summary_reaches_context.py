# case_ids: MC-222
"""`ToolResult.summary` 的**消费面**判据（issue #5511 第四节 / 来源台账 #4025 F23）。

## 裁定：选 B（保留字段 + 钉住消费面），**不**选 A（删字段 + 删赋值点）

台账/issue 原文的证据是 `git grep -n "\\.summary" origin/main -- backend/ai-agent-service/app`
⇒ 只有 `memory/context_builder.py` 的 `state.summary`（**不同对象**）。那条读法**漏掉了两种形态**：

1. **属性字符串取值** `getattr(result, "summary", None)`（`git grep '\.summary'` 看不见）；
2. **字段进了模型上下文**这条链路（不是靠属性名出现来读的）。

现取三处证据（`origin/main`，可复制复核）：

    git show origin/main:backend/ai-agent-service/app/graph/skills/base_skill.py | grep -n 'summary='
    #   summary=getattr(result, "summary", None) or "",     ← 出口字典（5 条出口共用）
    git show origin/main:backend/ai-agent-service/app/graph/skills/execution/react_turn.py | grep -n 'ToolMessage(content='
    #   ToolMessage(content=result_str, tool_call_id=…, name=tool_name)   ← 原样进模型上下文

`result_str` 就是 `json.dumps(result_dict, …)` ⇒ **`summary` 是模型看得到的工具结果字段**。
⇒ 「零消费」不成立。反过来，**删字段会真的从模型上下文里拿掉一段信息**（行为变更；按 #4262
又不自动跑真实 LLM 评测）⇒ A 不可取；B = 把这条消费面**钉住**，谁拆掉它，下面两条判据立刻红。

## 两条判据（各自会红）

1. `test_summary_value_reaches_the_model_facing_json` —— **运行期值透传**：真跑
   `_execute_tool_safe`（替身工具），断言出口字典与**那个交给 `ToolMessage` 的 JSON 字符串**
   里都是工具设的值。反例输入：把出口字典那一行的 `summary=` 删掉 / 改成常量 ⇒ 红。
2. `test_missing_summary_is_empty_string_not_missing_key` —— 没填 summary 的工具**不得缺键**
   （消费点 `result_dict["summary"]` 在既有代码里是直接取键的，缺键 = KeyError）。
3. `TestWiringIsNotVacuous` —— **链路静态锁 + 判别力自证**：出口 dict 必须带 `summary=`
   且 `react_turn.py` 必须有 `ToolMessage(content=result_str, …)`；两条分别注入拆除 ⇒ 判据点名，
   不注入 ⇒ 不报。
"""
import ast
import asyncio
import json
from pathlib import Path

import pytest

from app.graph.skills.base_skill import _execute_tool_safe
from app.tools.base import BaseTool, ToolContext, ToolResult

SERVICE_DIR = Path(__file__).resolve().parents[1]
BASE_SKILL = SERVICE_DIR / "app" / "graph" / "skills" / "base_skill.py"
REACT_TURN = SERVICE_DIR / "app" / "graph" / "skills" / "execution" / "react_turn.py"

#: 工具自己设的摘要（值本身就当断言对象：透传与否一目了然）。
SUMMARY_TEXT = "共3个分类: 卧室系列,窗帘布艺,测试分类"

_CTX = ToolContext(tenant_id=1, user_id="u-summary", session_id="s-summary", role="operator",
                   permissions=["category:query"])
_STATE = {"session_id": "s-summary", "tenant_id": 1}


class _SummaryTool(BaseTool):
    """只读幂等替身：成功时带 summary（只读 ⇒ 走缓存分支，本文件每条用例前清缓存）。"""

    name = "fake_summary_tool"
    description = "summary 透传替身"
    read_only = True
    idempotent = True
    parameters = {"type": "object", "properties": {}}

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={"count": 3}, message="共 3 个分类",
                          summary=SUMMARY_TEXT)


class _SilentTool(_SummaryTool):
    """同形态但**不填** summary（缺省语义判据用）。"""

    name = "fake_silent_tool"

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={"count": 0}, message="0 个分类")


@pytest.fixture(autouse=True)
def _clear_read_only_tool_cache():
    """清只读工具缓存：同名同参的替身会命中上一条用例的成功结果（假绿/假红形态）。"""
    _execute_tool_safe._cache = {}
    _execute_tool_safe._cache_lock = asyncio.Lock()
    yield
    _execute_tool_safe._cache = {}


async def test_summary_value_reaches_the_model_facing_json():
    """工具设的摘要必须出现在**模型看到的那段 JSON**里（issue #4018 的出口 + react_turn 的消费）。"""
    result_str, result_dict = await _execute_tool_safe(_SummaryTool(), {}, _CTX, dict(_STATE))

    assert result_dict["summary"] == SUMMARY_TEXT, (
        f"出口字典必须原样带出 summary（实测 {result_dict.get('summary')!r}）"
    )
    assert json.loads(result_str)["summary"] == SUMMARY_TEXT, (
        "`result_str` 就是交给 `ToolMessage(content=…)` 的那段 JSON —— 它缺了 summary，"
        "模型上下文里就没有这条摘要（消费面断裂）"
    )
    assert result_dict["success"] is True, "替身工具必须真的执行成功（否则测的是异常出口）"


async def test_missing_summary_is_empty_string_not_missing_key():
    """没填 summary ⇒ 键在、值为空串（消费点直接取键，缺键 = KeyError）。"""
    result_str, result_dict = await _execute_tool_safe(_SilentTool(), {}, _CTX, dict(_STATE))

    assert result_dict["summary"] == "", (
        f"缺省必须是空串而不是缺键（实测 {result_dict.get('summary')!r}）"
    )
    assert json.loads(result_str)["summary"] == "", (
        "模型上下文里的缺省形态也必须是空串（与出口字典同一份真值）"
    )


def _wiring_gaps(base_src: str, react_src: str) -> list:
    """纯函数内核：① 出口 dict 带 `summary=`；② `ToolMessage(content=result_str, …)` 仍在。

    两条都**用 AST 判**（不按引号扫源码原文取值 —— 注释里的假字面量会被当成真站点）。
    """
    gaps = []

    passed_through = False
    for node in ast.walk(ast.parse(base_src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "result_dict"
                and any(kw.arg == "summary" for kw in node.keywords)):
            passed_through = True
    if not passed_through:
        gaps.append("`_execute_tool_safe` 的出口 `result_dict.update(...)` 里没有 `summary=`")

    fed_to_model = False
    for node in ast.walk(ast.parse(react_src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "ToolMessage"):
            for kw in node.keywords:
                if (kw.arg == "content" and isinstance(kw.value, ast.Name)
                        and kw.value.id == "result_str"):
                    fed_to_model = True
    if not fed_to_model:
        gaps.append("`react_turn.py` 里没有 `ToolMessage(content=result_str, …)` —— "
                    "那段 JSON 不再进模型上下文（消费面消失，需重新裁定）")

    return gaps


class TestWiringIsNotVacuous:
    """链路静态锁 + 判别力自证（注入式红证：拆掉任一环必红，不拆不报）。"""

    def test_real_sources_have_no_gap(self):
        gaps = _wiring_gaps(BASE_SKILL.read_text(encoding="utf-8"),
                            REACT_TURN.read_text(encoding="utf-8"))
        assert gaps == [], f"`summary` 的消费面被拆了：{gaps}"

    def test_removing_the_exit_passthrough_is_named(self):
        src = BASE_SKILL.read_text(encoding="utf-8")
        anchor = 'summary=getattr(result, "summary", None) or "",'
        assert anchor in src, "变异锚点漂移（先看 `_execute_tool_safe` 出口 update 现在长什么样）"
        mutated = src.replace(anchor, "")
        assert mutated != src, "变异没生效（锚点漂移）—— 不许把「注入失效」报成「判据没牙」"
        gaps = _wiring_gaps(mutated, REACT_TURN.read_text(encoding="utf-8"))
        assert any("没有 `summary=`" in g for g in gaps), f"注入后必须点名（实测 {gaps}）"

    def test_removing_the_context_feed_is_named(self):
        src = REACT_TURN.read_text(encoding="utf-8")
        anchor = "ToolMessage(content=result_str,"
        assert anchor in src, "变异锚点漂移（先看 react_turn.py 里 ToolMessage 现在怎么构造）"
        mutated = src.replace(anchor, "ToolMessage(content=result_dict,")
        assert mutated != src, "变异没生效（锚点漂移）—— 不许把「注入失效」报成「判据没牙」"
        gaps = _wiring_gaps(BASE_SKILL.read_text(encoding="utf-8"), mutated)
        assert any("不再进模型上下文" in g for g in gaps), f"注入后必须点名（实测 {gaps}）"
