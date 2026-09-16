"""_execute_tool_safe 异常路径健壮性 — 回归测试
# case_ids: PP-001, PR-010

生产事故（sess_fba38395ed094a9d，2026-09-05）：
- 用户在创建商品流程选了分类后，agent 下一轮展示加工项选择器时崩溃无回复；
- 服务器日志两层异常叠在一起：
  1. `TypeError: InteractTool.execute() got an unexpected keyword argument 'pageMeta'`
     —— processing_item_query 返回 pageMeta 提示 LLM「interact(choice) 直接透传」，
        但 interact 工具 execute 签名缺该参数（本文件同目录 test_tools_interact.py 覆盖修复）；
  2. `ValueError: unmatched '{' in format spec`（日志层）—— _execute_tool_safe 的 except
     分支 `logger.error(f"...args={json.dumps(...)}", exc_info=True)` 把含未配对 `{` 的 JSON
     拼进消息文本，loguru 因 exc_info 触发 `message.format()` 二次解析 → 二次异常**穿透 except**，
     真实 TypeError 被掩盖，整个 agent 流崩溃、assistant 消息不落库。

本文件锁定第二层：工具执行抛错时，_execute_tool_safe 必须返回失败结果，
不得因日志格式化二次抛错而把异常传出去。

⚠️ 2026-09-12 更新（issue #3361）：第一层的"未知 kwarg → TypeError"已被**参数净化**
取代 —— `_execute_tool_safe` 现在会按工具 execute() 签名丢弃不受支持的参数并打警告
（CI 实证：[tool-exec] order_create ERROR: got an unexpected keyword argument 'action'
→ 模型重试两次才成功，是 CH-010/OR-014 抖动的真因）。
故本文件的**触发方式**改为"工具内部真抛错"（含未配对花括号的 args 仍用于触发日志二次
格式化的风险点），**断言不变**：必须返回失败结果、不得抛异常。
"""
import asyncio

from app.graph.skills.base_skill import _execute_tool_safe
from app.tools.interact import InteractTool
from app.tools.base import ToolContext


class _BoomTool(InteractTool):
    """执行即抛 TypeError 的替身：保留"args 含未配对花括号 → 日志二次格式化"的风险点。"""

    name = "interact"

    async def execute(self, context, **kwargs):  # noqa: D401
        raise TypeError("InteractTool.execute() boom (模拟工具内部真异常)")


def _run_with_unknown_kwarg() -> tuple[str, dict]:
    """触发工具**内部**异常（含未配对花括号的 args 仍进入日志格式化路径）。"""
    if hasattr(_execute_tool_safe, "_cache"):
        _execute_tool_safe._cache = {}

    ctx = ToolContext(tenant_id=999, user_id="u-test", session_id="s-test", role="admin")
    state = {"session_id": "s-test", "tenant_id": 999}

    args = {
        "component": "choice",
        "title": "请选择加工项",
        "options": [{"label": "1. 罗马杆环安装", "value": "proc_item_hook_roman"}],
        "pageMeta": {  # 生产回归：LLM 按 processing_item_query 的 pageMeta 提示透传
            "current": 1,
            "total": 4,
            "totalCount": 32,
            "tool": "processing_item_query",
            "params": '{"keyword":"","page":1,"size":10}',
        },
        "unexpected_param": {"dirty": "{unmatched"},  # 日志 args 里出现未配对花括号
    }

    async def _scenario():
        return await _execute_tool_safe(_BoomTool(), args, ctx, state)

    return asyncio.run(_scenario())


def test_execute_tool_safe_returns_error_tuple_on_typeerror():
    """工具 execute 抛 TypeError 时返回失败结果，不被日志二次异常穿透。

    修复前（sess_fba38395ed094a9d）：args 含未配对花括号 → except 分支
    logger.error 二次 format 抛 ValueError → _execute_tool_safe 直接抛异常，
    LangGraph 节点崩溃、SSE 只发 error、assistant 消息不落库。
    """
    result_str, result_dict = _run_with_unknown_kwarg()
    assert result_dict["success"] is False
    assert result_dict["error"] == "tool_execution_failed"
    # 失败结果应以 JSON 字符串返回（ToolMessage 可直接装载），不得抛异常
    import json
    parsed = json.loads(result_str)
    assert parsed["success"] is False