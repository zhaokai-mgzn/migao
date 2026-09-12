"""确认-执行链「已校验待执行」状态纯函数单测（issue #3031）。

背景（sess_50ff3e3c824c4a70 复盘）：售后换货用户两次点确认、agent 弹三张 confirm 卡
从不调用 after_sales_manage(create)——validate_input 通过后结果未持久化，确认轮从零重走。
本模块测 extract_pending / format_execution_hint / is_pending_for 三个纯函数，
保证「校验通过 → 待执行状态 → 确认轮直接执行」的底座正确。
"""
# case_ids: AS-006, AS-007, OR-009, OR-010
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, patch

# tests/ 在 backend/ai-agent-service/tests/，REPO_ROOT(backend/ai-agent-service) = parents[1]
REPO_ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = REPO_ROOT / "app" / "graph" / "pending_validated.py"

spec = importlib.util.spec_from_file_location("pending_validated", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestExtractPending:
    def test_valid_validate_args_extract(self):
        args = {
            "target_tool": "after_sales_manage",
            "target_action": "create",
            "params": {"ticket_type": "exchange", "order_id": "ORD123"},
        }
        p = mod.extract_pending(args)
        assert p["target_tool"] == "after_sales_manage"
        assert p["target_action"] == "create"
        assert p["params"]["order_id"] == "ORD123"

    def test_missing_target_tool_returns_none(self):
        assert mod.extract_pending({"target_action": "create", "params": {}}) is None

    def test_missing_target_action_returns_none(self):
        assert mod.extract_pending({"target_tool": "order_create", "params": {}}) is None

    def test_non_dict_args_returns_none(self):
        assert mod.extract_pending("not a dict") is None

    def test_missing_params_defaults_empty(self):
        p = mod.extract_pending({"target_tool": "order_create", "target_action": "create"})
        assert p["params"] == {}

    def test_non_dict_params_coerced_empty(self):
        p = mod.extract_pending(
            {"target_tool": "order_create", "target_action": "create", "params": "oops"}
        )
        assert p["params"] == {}


class TestFormatExecutionHint:
    def test_hint_contains_tool_action_params(self):
        p = {"target_tool": "after_sales_manage", "target_action": "create",
             "params": {"order_id": "ORD123", "ticket_type": "exchange"}}
        hint = mod.format_execution_hint(p)
        assert "after_sales_manage" in hint
        assert "create" in hint
        assert "ORD123" in hint
        # 铁律：禁止重走 validate / confirm
        assert "不要再调用 validate_input" in hint
        assert "不要" in hint and "confirm" in hint

    def test_hint_truncates_long_params(self):
        p = {"target_tool": "order_create", "target_action": "create",
             "params": {"remark": "x" * 2000}}
        hint = mod.format_execution_hint(p)
        assert "截断" in hint
        assert len(hint) < 1500

    def test_hint_handles_non_serializable_params(self):
        p = {"target_tool": "order_create", "target_action": "create",
             "params": {"f": object()}}
        hint = mod.format_execution_hint(p)
        assert "order_create" in hint


class TestIsPendingFor:
    def test_matching_tool_true(self):
        assert mod.is_pending_for({"target_tool": "order_create"}, "order_create") is True

    def test_non_matching_tool_false(self):
        assert mod.is_pending_for({"target_tool": "order_create"}, "product_manage") is False

    def test_none_pending_false(self):
        assert mod.is_pending_for(None, "order_create") is False


class TestInjectPendingValidated:
    """确认-执行链注入（_inject_pending_validated）：仅确认轮注入执行提示。

    用 AsyncMock 替换 SessionStateStore，验证三个门控：
    1. 无 pending → 原样返回；
    2. 有 pending 但用户消息非确认 → 不注入（防纠偏/新意图轮误注入）；
    3. 有 pending 且确认轮 → 前置注入执行提示。
    """
    def _state(self, session_id="sess-1"):
        return {"session_id": session_id}

    def test_no_pending_returns_unchanged(self):
        import asyncio
        from app.graph.skills.base_skill import _inject_pending_validated
        with patch("app.memory.session_state_store.SessionStateStore") as m_store_cls:
            m_store_cls.return_value.load = AsyncMock(return_value={})
            result = asyncio.run(_inject_pending_validated(
                "base prompt", self._state(), "确认创建换货工单"
            ))
        assert result == "base prompt"

    def test_pending_but_not_confirmation_round_not_injected(self):
        import asyncio
        from app.graph.skills.base_skill import _inject_pending_validated
        pending = {"target_tool": "after_sales_manage", "target_action": "create",
                   "params": {"order_id": "ORD123"}}
        with patch("app.memory.session_state_store.SessionStateStore") as m_store_cls:
            m_store_cls.return_value.load = AsyncMock(
                return_value={"pending_validated_input": pending}
            )
            result = asyncio.run(_inject_pending_validated(
                "base prompt", self._state(), "等等，我要换个商品"  # 纠偏，非确认
            ))
        assert result == "base prompt"

    def test_confirmation_round_injects_hint(self):
        import asyncio
        from app.graph.skills.base_skill import _inject_pending_validated
        pending = {"target_tool": "after_sales_manage", "target_action": "create",
                   "params": {"order_id": "ORD123", "ticket_type": "exchange"}}
        committed = {}
        with patch("app.memory.session_state_store.SessionStateStore") as m_store_cls:
            m_store_cls.return_value.load = AsyncMock(
                return_value={"pending_validated_input": pending}
            )
            # 确认轮现在会**落放行标记**（issue #3361：文本确认也要记住，否则验证码轮被门禁拦）
            m_store_cls.return_value.commit = AsyncMock(
                side_effect=lambda sid, full: committed.update(full))
            result = asyncio.run(_inject_pending_validated(
                "base prompt", self._state(), "确认创建换货工单"
            ))
        assert "已校验待执行" in result
        assert "after_sales_manage" in result
        assert result.endswith("base prompt")  # hint 前置
        assert committed.get("confirmed_write_tool") == "after_sales_manage", (
            "确认轮未记录跨轮放行标记 —— 下一轮补充信息时写操作会被门禁拦"
        )

    def test_no_session_returns_unchanged(self):
        import asyncio
        from app.graph.skills.base_skill import _inject_pending_validated
        result = asyncio.run(_inject_pending_validated(
            "base prompt", {"session_id": ""}, "确认"
        ))
        assert result == "base prompt"
