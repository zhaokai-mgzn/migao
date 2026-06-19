"""Tests for channel-aware greeting integration."""
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.customer_service_agent import AgentContext


class TestChannelGreeting:
    """Channel-aware greeting tests."""

    def test_agent_context_has_identity_type(self):
        """AgentContext carries channel information."""
        ctx = AgentContext(
            user_id="user_001",
            tenant_id=1,
            session_id="sess_001",
            role="customer",
            identity_type="wechat_mini",
        )
        assert ctx.identity_type == "wechat_mini"

    def test_agent_context_default_identity_type(self):
        """Default identity_type is wechat_mini."""
        ctx = AgentContext(
            user_id="user_001",
            tenant_id=1,
            session_id="sess_001",
        )
        assert ctx.identity_type == "wechat_mini"

    def test_agent_context_douyin_channel(self):
        """Douyin mini channel is preserved."""
        ctx = AgentContext(
            user_id="user_001",
            tenant_id=1,
            session_id="sess_001",
            identity_type="douyin_mini",
        )
        assert ctx.identity_type == "douyin_mini"


class TestChannelConfigModule:
    """channel_config.py module tests."""

    def test_resolve_greeting_wechat_mini(self):
        """WeChat mini gets channel-specific greeting."""
        from app.agents.channel_config import resolve_greeting

        greeting = resolve_greeting("wechat_mini", bot_name="小布")
        assert "小布" in greeting
        assert "米高窗帘" in greeting

    def test_resolve_greeting_substitutes_bot_name(self):
        """{bot_name} placeholder is replaced."""
        from app.agents.channel_config import resolve_greeting

        greeting = resolve_greeting("web", bot_name="定制助手")
        assert "定制助手" in greeting
        assert "{bot_name}" not in greeting

    def test_resolve_greeting_fallback_unknown_channel(self):
        """Unknown channel gets fallback greeting."""
        from app.agents.channel_config import resolve_greeting

        greeting = resolve_greeting("unknown_channel", bot_name="小布")
        assert "小布" in greeting

    def test_resolve_greeting_tenant_override(self):
        """Tenant config overrides default channel greeting."""
        from app.agents.channel_config import resolve_greeting

        tenant_config = {
            "web": {"greeting": "欢迎光临{bot_name}专属客服！"}
        }
        greeting = resolve_greeting("web", tenant_config=tenant_config, bot_name="定制助手")
        assert "欢迎光临定制助手专属客服！" == greeting

    def test_get_channel_config_merges_fields(self):
        """Tenant override only changes specified fields."""
        from app.agents.channel_config import get_channel_config

        tenant_config = {
            "wechat_mini": {"greeting": "自定义欢迎语"}
        }
        config = get_channel_config("wechat_mini", tenant_config)
        assert config.greeting == "自定义欢迎语"
        # capabilities preserved from default
        assert "商品咨询" in config.capabilities
