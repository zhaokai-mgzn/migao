"""写操作工具不得被缓存 — 回归测试

修复背景：_execute_tool_safe 曾对所有工具（含写操作）的结果做 60s 缓存，
导致非幂等写（如重复下单/售后）在 60s 内以相同参数重复调用时，
第二次直接返回缓存的 success=True 而不真正执行，造成静默写丢失。

修复后：仅 read_only=True 的工具参与缓存；read_only=False 的写工具每次都真正执行。
"""
import asyncio

from app.graph.skills.base_skill import _execute_tool_safe
from app.tools.base import BaseTool, ToolContext, ToolResult


class _CountingReadTool(BaseTool):
    name = "test_read_count"
    description = "只读计数工具（用于缓存回归测试）"
    read_only = True
    idempotent = True

    def __init__(self):
        super().__init__()
        self.calls = 0

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, data={"calls": self.calls})


class _CountingWriteTool(BaseTool):
    name = "test_write_count"
    description = "写计数工具（用于缓存回归测试）"
    read_only = False
    idempotent = False  # 非幂等写，绝不能被缓存

    def __init__(self):
        super().__init__()
        self.calls = 0

    async def execute(self, context: ToolContext, **kwargs) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, data={"calls": self.calls})


def _run_twice(tool: BaseTool) -> int:
    """用相同参数连续执行同一工具两次，返回实际 execute 调用次数。"""
    # 清空模块级缓存，避免跨用例污染
    if hasattr(_execute_tool_safe, "_cache"):
        _execute_tool_safe._cache = {}

    ctx = ToolContext(tenant_id=999, user_id="u-test", session_id="s-test", role="admin")
    state = {"session_id": "s-test", "tenant_id": 999}

    async def _scenario():
        await _execute_tool_safe(tool, {}, ctx, state)
        await _execute_tool_safe(tool, {}, ctx, state)

    asyncio.run(_scenario())
    return tool.calls


def test_readonly_tool_is_cached():
    """只读工具：第二次调用命中缓存，execute 只执行一次。"""
    assert _run_twice(_CountingReadTool()) == 1


def test_write_tool_is_not_cached():
    """写工具（非幂等）：第二次调用必须真正执行，不允许命中缓存。"""
    assert _run_twice(_CountingWriteTool()) == 2
