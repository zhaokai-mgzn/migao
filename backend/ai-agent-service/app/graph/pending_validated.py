"""
确认-执行链的「已校验待执行」状态（issue #3031）。

背景（sess_50ff3e3c824c4a70 复盘）：售后换货工单创建，用户两次点「确认创建换货工单」，
agent 弹了三张 confirm 卡、从未调用 after_sales_manage(create)，工单未创建。
根因：validate_input 通过后结果未持久化——下一轮（用户点确认）LLM 看不到
「参数已校验、只差执行」，从零重走 validate_input → interact(confirm) 循环，
再叠加对话压缩把「已确认」上下文摘要化，循环放大。

本模块提供纯函数（可单测、无 IO）：
- extract_pending：从 validate_input 的 tool args 提取待执行状态
- format_execution_hint：生成注入 system prompt 的「已校验待执行」提示

持久化/读取由调用方（base_skill.execute_skill）经 SessionStateStore 完成。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# SessionStateStore 中的状态键（与 clarify / handoff 平级）
PENDING_KEY = "pending_validated_input"

# 确认轮提示模板：LLM 看到此提示应直接调用写工具，不再重走 validate + confirm。
_HINT_TEMPLATE = (
    "【已校验待执行】上一轮你已经调用 validate_input 校验过以下写操作参数并通过：\n"
    "  目标工具: {tool}\n"
    "  操作: {action}\n"
    "  参数: {params}\n"
    "用户当前消息是对确认卡片的确认回复。\n"
    "铁律：直接调用 {tool}(action='{action}', ...) 执行写操作，"
    "不要再调用 validate_input，也不要再发 interact(confirm) 确认卡。\n"
    "执行完成后才可回复用户操作结果。"
)


def extract_pending(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 validate_input 的 tool args 提取待执行状态。

    validate_input 的入参结构：{target_tool, target_action, params}。
    只有 target_tool 与 target_action 都非空时才算有效待执行状态（否则返回 None）。

    Args:
        args: validate_input 工具的调用参数

    Returns:
        {"target_tool", "target_action", "params"} 或 None（参数不完整）
    """
    if not isinstance(args, dict):
        return None
    target_tool = args.get("target_tool")
    target_action = args.get("target_action")
    if not target_tool or not target_action:
        return None
    params = args.get("params") or {}
    return {
        "target_tool": str(target_tool),
        "target_action": str(target_action),
        "params": params if isinstance(params, dict) else {},
    }


def format_execution_hint(pending: Dict[str, Any]) -> str:
    """生成「已校验待执行」提示，注入确认轮 system prompt。

    参数摘要截断，避免把超长 params 全量灌进 prompt（防 token 爆炸 + 防注入面扩大）。
    """
    import json

    tool = str(pending.get("target_tool", ""))
    action = str(pending.get("target_action", ""))
    params = pending.get("params") or {}
    try:
        params_str = json.dumps(params, ensure_ascii=False, default=str)
    except Exception:
        params_str = str(params)
    if len(params_str) > 500:
        params_str = params_str[:500] + "...(截断)"
    return _HINT_TEMPLATE.format(tool=tool, action=action, params=params_str)


def is_pending_for(pending: Optional[Dict[str, Any]], tool: str) -> bool:
    """判断待执行状态是否针对指定工具（写工具执行成功后据此清除）。"""
    if not pending:
        return False
    return str(pending.get("target_tool", "")) == str(tool)
