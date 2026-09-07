# case_ids: CH-029
"""偏好注入建议个性化测试（issue #2997：flag 门控，默认关闭）

覆盖 base_skill 的偏好注入接线（_inject_user_preferences）：
- 开关默认关闭（SUGGESTION_PREFERENCE_ENABLED=False）→ 不注入、不调 tracker（零行为变化）
- 开启且 xiaobu 有偏好意图 → 消毒后的 <user_preferences> 块前置注入 system prompt + [preference-inject] 日志
- mibao 不注入 / 无 tenant/user / 无偏好 / tracker 异常 → 原样返回，不破坏主流程
- 标签文本做 XML 转义消毒（对齐审计 07 P1-L9 注入安全原则）
"""
import pytest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

from app.config import settings
from app.graph.skills.base_skill import _inject_user_preferences


def _make_state(agent_type: str, tenant_id: int = 1, user_id: str = "u1") -> dict:
    return {
        "agent_type": agent_type,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "session_id": "s1",
        "messages": [HumanMessage(content="你好")],
    }


class TestInjectUserPreferences:
    @pytest.mark.asyncio
    async def test_flag_off_no_injection(self, monkeypatch):
        """开关默认关闭 → 原样返回，tracker 不被调用"""
        monkeypatch.setattr(settings, "SUGGESTION_PREFERENCE_ENABLED", False)
        base_prompt = "你是小布，米高窗帘的智能客服。"
        with patch(
            "app.graph.skills.base_skill.PreferenceTracker"
        ) as mock_cls:
            result = await _inject_user_preferences(
                base_prompt, _make_state("xiaobu")
            )
        assert result == base_prompt
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_xiaobu_injects(self, monkeypatch):
        """开关开启 + xiaobu 有偏好 → <user_preferences> 消毒块前置注入"""
        monkeypatch.setattr(settings, "SUGGESTION_PREFERENCE_ENABLED", True)
        base_prompt = "你是小布，米高窗帘的智能客服。"
        with patch(
            "app.graph.skills.base_skill.PreferenceTracker"
        ) as mock_cls:
            tracker = mock_cls.return_value
            tracker.get_top_intents = AsyncMock(return_value=[
                {"intent_type": "order_query", "click_count": 12, "label": "订单查询"},
                {"intent_type": "product_inquiry", "click_count": 3, "label": "商品查询"},
            ])
            result = await _inject_user_preferences(
                base_prompt, _make_state("xiaobu")
            )

        assert "<user_preferences>" in result
        assert "订单查询" in result
        assert "商品查询" in result
        assert "12 次" in result
        assert result.startswith("<user_preferences>")
        assert base_prompt in result
        mock_cls.return_value.get_top_intents.assert_awaited_once_with(
            1, "u1", limit=5
        )

    @pytest.mark.asyncio
    async def test_mibao_does_not_inject(self, monkeypatch):
        """mibao（B 端）不注入偏好（agent_type 分流）"""
        monkeypatch.setattr(settings, "SUGGESTION_PREFERENCE_ENABLED", True)
        base_prompt = "你是米宝，商家后台助手。"
        with patch(
            "app.graph.skills.base_skill.PreferenceTracker"
        ) as mock_cls:
            result = await _inject_user_preferences(
                base_prompt, _make_state("mibao")
            )
        assert result == base_prompt
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_tenant_or_user_skips(self, monkeypatch):
        """缺 tenant/user → 跳过不注入"""
        monkeypatch.setattr(settings, "SUGGESTION_PREFERENCE_ENABLED", True)
        base_prompt = "你是小布。"
        with patch(
            "app.graph.skills.base_skill.PreferenceTracker"
        ) as mock_cls:
            result = await _inject_user_preferences(
                base_prompt, _make_state("xiaobu", tenant_id=0, user_id="")
            )
        assert result == base_prompt
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_prefs_no_injection(self, monkeypatch):
        """开启但无偏好记录 → 原样返回"""
        monkeypatch.setattr(settings, "SUGGESTION_PREFERENCE_ENABLED", True)
        base_prompt = "你是小布。"
        with patch(
            "app.graph.skills.base_skill.PreferenceTracker"
        ) as mock_cls:
            tracker = mock_cls.return_value
            tracker.get_top_intents = AsyncMock(return_value=[])
            result = await _inject_user_preferences(
                base_prompt, _make_state("xiaobu")
            )
        assert result == base_prompt

    @pytest.mark.asyncio
    async def test_tracker_exception_safe(self, monkeypatch):
        """tracker 异常 → 不抛，原样返回（fire-and-forget 语义）"""
        monkeypatch.setattr(settings, "SUGGESTION_PREFERENCE_ENABLED", True)
        base_prompt = "你是小布。"
        with patch(
            "app.graph.skills.base_skill.PreferenceTracker"
        ) as mock_cls:
            tracker = mock_cls.return_value
            tracker.get_top_intents = AsyncMock(side_effect=RuntimeError("db down"))
            result = await _inject_user_preferences(
                base_prompt, _make_state("xiaobu")
            )
        assert result == base_prompt

    @pytest.mark.asyncio
    async def test_label_xml_escaped(self, monkeypatch):
        """标签含 <>& 等字符 → XML 转义消毒后注入"""
        monkeypatch.setattr(settings, "SUGGESTION_PREFERENCE_ENABLED", True)
        base_prompt = "你是小布。"
        with patch(
            "app.graph.skills.base_skill.PreferenceTracker"
        ) as mock_cls:
            tracker = mock_cls.return_value
            tracker.get_top_intents = AsyncMock(return_value=[
                {"intent_type": "x", "click_count": 1, "label": "退<货>&查询"},
            ])
            result = await _inject_user_preferences(
                base_prompt, _make_state("xiaobu")
            )
        assert "&lt;user_preferences&gt;" not in result
        assert "<user_preferences>" in result
        assert "退&lt;货&gt;&amp;查询" in result