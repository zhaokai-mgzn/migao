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
- extract_validation_failure / mark_validation_failure / clear_validation_failure
  ：**校验失败留痕**（issue #4073）

「校验失败留痕」（issue #4073，S2）—— 把 prompt 铁律落成代码闸门：
`PROMPT-rules.md` 写「**铁律：validate_input 校验失败时，禁止继续执行写工具。**」，
但代码侧原本只记**成功**（`PENDING_KEY`），失败路径一滴痕迹都不留 ⇒ 写调用点
无从判断"这个写刚刚校验失败过"，唯一防线是模型自觉（#3414/#3445 家族已证模型会跳过）。
本模块据 `VALIDATION_FAILURE_KEY` 留失败账，闸门本体在 `execution/react_turn.py`
的写调用点（**共享执行路径**，不是给某个 skill 打补丁）。

**适用域**：只管**被 `validate_input` 校验过的目标**（没有记录 ⇒ 不管）——
从未校验过的写流程照常放行（R2 ①）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# SessionStateStore 中的状态键（与 clarify / handoff 平级）
PENDING_KEY = "pending_validated_input"
#: 校验失败记录（与 PENDING_KEY **平级**的独立键；不合并进 pending —— 两者语义正交：
#: pending 是"校验过了、只差执行"，本键是"校验没过、别执行"）。
VALIDATION_FAILURE_KEY = "validation_failure"

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


# ── 校验失败留痕（issue #4073）──────────────────────────────────────────────
# 键的形态：{ "<target_tool>::<target_action>": {"target_tool", "target_action",
#                                               "error", "message", "suggestion"} }
# 用 `tool::action` 复合键而不是单个记录：同一会话可以在多个目标上同时欠账，
# 单个槽位会让后一次失败覆盖前一次 ⇒ 先失败的那个目标静默被放行。
# 复用 PENDING_KEY 已有的 `params 缺失即空` 口径：`target_action` 是工具**入参**，
# 缺省即 ""（与 `extract_pending` 要求非空的判据不同 —— 那里空 action 的待执行状态
# 无法回填执行提示，这里空 action 反而是合法目标，不能因此漏记）。


def validation_failure_key(target_tool: Any, target_action: Any) -> str:
    """失败记录的复合键（`<tool>::<action>`）。"""
    return f"{str(target_tool or '').strip()}::{str(target_action or '').strip()}"


def extract_validation_failure(tool_args: Dict[str, Any],
                               result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """校验**失败**时生成留痕记录；不是"针对某个目标的校验失败"就返回 None。

    只在 `result.success is False` 时留痕 —— 判据是**结果**而不是"调用过 validate_input"
    （后者会把"校验通过"也记成失败，直接锁死全部写流程）。

    Returns:
        {"target_tool", "target_action", "error", "message", "suggestion"} 或 None
    """
    if not isinstance(tool_args, dict) or not isinstance(result, dict):
        return None
    if result.get("success"):
        return None
    target_tool = str(tool_args.get("target_tool") or "").strip()
    if not target_tool:
        # 没有目标工具 ⇒ 无从判断该拦哪个写工具（适用域声明：没记录 = 不管）
        return None
    return {
        "target_tool": target_tool,
        "target_action": str(tool_args.get("target_action") or "").strip(),
        # 三段都截断后再落库：`validate_input` 的 `message` 是**逐条列出的失败明细**
        # （可能很长），原样入会话状态是给存储塞一个不受控大小的值。
        # `format_failure_block_message` 另有更紧的展示截断，两处口径不同、用途不同。
        "error": str(result.get("error") or "").strip()[:200],
        "message": str(result.get("message") or "").strip()[:2000],
        "suggestion": str(result.get("suggestion") or "").strip()[:500],
    }


def _failures_dict(full: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = (full or {}).get(VALIDATION_FAILURE_KEY)
    return raw if isinstance(raw, dict) else {}


def mark_validation_failure(full: Dict[str, Any],
                            failure: Dict[str, Any]) -> Dict[str, Any]:
    """把失败记录并入会话状态（返回**新** dict；纯函数，不改入参）。"""
    out = dict(full or {})
    key = validation_failure_key(failure.get("target_tool"),
                                 failure.get("target_action"))
    out[VALIDATION_FAILURE_KEY] = {**_failures_dict(full), key: dict(failure)}
    return out


def clear_validation_failure(full: Dict[str, Any], target_tool: Any,
                             target_action: Any) -> Dict[str, Any]:
    """清除**指定目标**的失败记录（返回新 dict）；该目标没记录则原样返回。

    清除点（issue #4073 交付形态 2）由调用方决定，共三个：
      ① 目标写工具**成功**执行（`_is_failure_for` 判定命中即清）；
      ② 该目标新的**成功** `validate_input`（补参后重新校验 = 模型的恢复路径）；
      ③ 事务终态重置（`reset_domain` 族，terminal 工具成功后）。
    只清指定目标：跨目标的失败账不得被顺手抹掉（否则等价于"新校验一次全放行"）。
    """
    failures = _failures_dict(full)
    key = validation_failure_key(target_tool, target_action)
    if key not in failures:
        return dict(full or {})
    out = dict(full or {})
    rest = {k: v for k, v in failures.items() if k != key}
    if rest:
        out[VALIDATION_FAILURE_KEY] = rest
    else:
        out.pop(VALIDATION_FAILURE_KEY, None)
    return out


def is_failure_for(full: Optional[Dict[str, Any]], tool: Any,
                   action: Any = "") -> bool:
    """该写调用是否命中一条**尚未被覆盖**的校验失败记录。

    判据是 `同 target_tool + 同 target_action`（issue #4073 交付形态 2）；
    目标对不上 ⇒ False（别的目标失败过，不拦本次写）。
    """
    key = validation_failure_key(tool, action)
    if key == "::":
        return False
    return key in _failures_dict(full)


def matched_failure(full: Optional[Dict[str, Any]], tool: Any,
                    action: Any = "") -> Optional[Dict[str, Any]]:
    """取出命中的失败记录（供闸门回填原因，模型才知道要补什么参数）。"""
    entry = _failures_dict(full).get(validation_failure_key(tool, action))
    return entry if isinstance(entry, dict) else None


def format_failure_block_message(tool: str, action: str,
                                 failure: Optional[Dict[str, Any]]) -> str:
    """生成拦截话术：**可执行的**恢复路径（补参 → 重新 validate_input → 再写）。

    fail-closed 但不得死锁（issue #4073 交付形态 3）：只给"不许写"就等于把会话
    锁死，模型唯一能做的只有反复重试同一个写调用（#3445 实测形态）。
    """
    entry = failure or {}
    action_part = f"(action='{action}')" if action else ""
    reason = str(entry.get("message") or entry.get("error") or "").strip()
    lines: List[str] = [
        f"写操作被拦截：{tool}{action_part} 刚刚**没有通过 `validate_input` 校验**"
        f"（铁律：校验失败时禁止继续执行写工具）。"
    ]
    if reason:
        lines.append(f"校验失败原因：{reason[:500]}")
    sugg = str(entry.get("suggestion") or "").strip()
    if sugg:
        lines.append(f"校验器给的修正方向：{sugg[:300]}")
    lines.append(
        "**本轮不要再次调用 "
        f"{tool}{action_part}，也不要靠顾客确认卡绕过** —— 参数没改，结果只会一样"
        "（顾客点确认也不放行）。唯一能走通的下一步："
        f"① 按上面的原因补齐/修正参数；② **重新调用 `validate_input`**"
        f"(target_tool='{tool}'"
        + (f", target_action='{action}'" if action else "")
        + ")；③ 校验通过（validated=true）之后再调用 "
        f"{tool}{action_part} 执行。"
    )
    return " ".join(lines)
