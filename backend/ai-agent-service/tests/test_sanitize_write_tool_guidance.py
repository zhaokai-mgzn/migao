"""写工具净化不再静默 — 图片类参数丢弃即失败并给正确工具指引（issue #3930）。

生产实证（sess_2efa2071bb1747d8，2026-09-15）：用户「先把这张色卡图设为主图」，
agent 把请求路由到 product_update（它没有 images 参数）→ `_sanitize_tool_args`
静默丢弃 images → 空字段调用 → 「没有要修改的字段」→ 模型外推「该入口不支持图片」
→ 编造性能力否定出站。

修复：写工具（read_only=False）丢弃**图片类**未知参数（images/detail_images/main_image）
时不再静默 —— 直接返回失败 + product_manage 指引（不执行），让模型改走
`product_manage(action=update, images=…)`。
只读工具与非图片类未知参数保持 issue #3361 的静默净化行为
（存量用例依赖，见 test_graph_skills.py 的 test_unexpected_kwarg_dropped）。
"""
# case_ids: PR-017, PR-026, PR-027

import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock

from app.graph.skills.base_skill import (
    _execute_tool_safe,
    _dropped_args_guidance,
)


class _FakeWriteTool:
    """显式签名的写工具替身（无 **kwargs → 净化生效）。"""

    name = "product_update"
    read_only = False
    destructive = False
    requires_confirmation = True
    idempotent = True

    def __init__(self, executed=None):
        self.executed = executed if executed is not None else []

    async def execute(self, context, product_id: str = None, price: float = None):
        self.executed.append({"product_id": product_id, "price": price})
        from app.tools.base import ToolResult
        return ToolResult(success=True, data={}, message="ok")


class _FakeReadOnlyTool:
    """只读工具替身：保持静默净化（查询类模型爱带多余参数，不能因此失败）。"""

    name = "product_search"
    read_only = True
    destructive = False
    requires_confirmation = False
    idempotent = True

    def __init__(self, executed=None):
        self.executed = executed if executed is not None else []

    async def execute(self, context, keyword: str = None):
        self.executed.append({"keyword": keyword})
        from app.tools.base import ToolResult
        return ToolResult(success=True, data={}, message="ok")


def _run(tool, args):
    """驱动 _execute_tool_safe（净化为恒等、ID 解析为恒等）。"""

    async def _scenario():
        return await _execute_tool_safe(tool, args, MagicMock(), {"session_id": "s"})

    with patch("app.graph.skills.base_skill._auto_resolve_ids",
               new=AsyncMock(side_effect=lambda tool, args, state: args)), \
         patch("app.tools.langchain_adapter.LangChainToolAdapter._normalize_args",
               staticmethod(lambda tool, args: args)):
        return asyncio.run(_scenario())


class TestWriteToolImageArgsDroppedFailsWithGuidance:
    """写工具丢弃图片类参数 → 失败 + product_manage 指引，且不执行（误宣链源头切断）。"""

    def test_images_dropped_returns_failure_with_product_manage_guidance(self):
        tool = _FakeWriteTool()
        result_str, result_dict = _run(
            tool, {"product_id": "p1", "images": ["http://x/1.jpg"]})
        assert result_dict["success"] is False
        assert "product_manage" in result_dict["error"], result_dict["error"]
        assert "images" in result_dict["error"]
        assert tool.executed == [], "丢弃参数后不得执行写工具（空字段调用正是「没有要修改的字段」误宣链）"
        parsed = json.loads(result_str)
        assert parsed["success"] is False
        assert "product_manage" in parsed["message"]

    def test_detail_images_and_main_image_covered(self):
        for arg in ("detail_images", "main_image"):
            tool = _FakeWriteTool()
            _, result_dict = _run(tool, {"product_id": "p1", arg: ["http://x/1.jpg"]})
            assert result_dict["success"] is False, f"{arg} 未拦截"
            assert "product_manage" in result_dict["error"], f"{arg} 指引缺失"
            assert tool.executed == []

    def test_no_dropped_args_executes_normally(self):
        tool = _FakeWriteTool()
        _, result_dict = _run(tool, {"product_id": "p1", "price": 168.0})
        assert result_dict["success"] is True
        assert tool.executed == [{"product_id": "p1", "price": 168.0}]

    def test_non_image_unknown_args_still_silent(self):
        """非图片类未知参数维持存量静默净化（test_graph_skills L0 依赖该行为）。"""
        tool = _FakeWriteTool()
        _, result_dict = _run(tool, {"product_id": "p1", "action": "update"})
        assert result_dict["success"] is True, "非图片未知参数不得拦截（存量行为）"
        assert tool.executed == [{"product_id": "p1", "price": None}]

    def test_readonly_tool_extra_args_still_silent(self):
        tool = _FakeReadOnlyTool()
        _, result_dict = _run(tool, {"keyword": "窗帘", "images": ["http://x/1.jpg"]})
        assert result_dict["success"] is True, "只读工具保持静默净化"
        assert tool.executed == [{"keyword": "窗帘"}]


class TestDroppedArgsGuidance:
    """`_dropped_args_guidance` 纯函数：空串 = 不拦截。"""

    def test_empty_for_readonly(self):
        assert _dropped_args_guidance(_FakeReadOnlyTool(), {"images": ["x"]}) == ""

    def test_empty_for_accepted_args(self):
        assert _dropped_args_guidance(_FakeWriteTool(), {"product_id": "p1"}) == ""

    def test_empty_for_non_image_unknown(self):
        assert _dropped_args_guidance(
            _FakeWriteTool(), {"product_id": "p1", "action": "x"}) == ""

    def test_image_args_get_product_manage_guidance(self):
        msg = _dropped_args_guidance(
            _FakeWriteTool(), {"product_id": "p1", "images": ["x"]})
        assert "product_manage(action=update, images" in msg, msg
        msg2 = _dropped_args_guidance(
            _FakeWriteTool(), {"product_id": "p1", "detail_images": ["x"]})
        assert "product_manage(action=update, detail_images" in msg2, msg2
