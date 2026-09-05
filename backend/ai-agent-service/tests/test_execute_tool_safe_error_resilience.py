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
"""
import asyncio

from app.graph.skills.base_skill import _execute_tool_safe
from app.tools.interact import InteractTool
from app.tools.base import ToolContext


def _run_with_unknown_kwarg() -> tuple[str, dict]:
    """向 InteractTool 传 execute 签名不存在的参数（触发 TypeError 分支）。"""
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
        return await _execute_tool_safe(InteractTool(), args, ctx, state)

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