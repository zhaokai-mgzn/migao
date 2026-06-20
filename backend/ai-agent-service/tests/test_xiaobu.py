"""
Tests for app/agents/agents/xiaobu.py
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.agent_config import AgentConfig

class TestConstants:
    def test_default_bot_name(self):
        from app.agents.agents.xiaobu import DEFAULT_BOT_NAME
        assert DEFAULT_BOT_NAME == "小布"
    def test_default_greeting_not_empty(self):
        from app.agents.agents.xiaobu import DEFAULT_GREETING
        assert len(DEFAULT_GREETING) > 0
        assert "小布" in DEFAULT_GREETING

class TestXiaobuConfig:
    def test_config_is_agent_config(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert isinstance(XIAOBU_CONFIG, AgentConfig)
    def test_config_name(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert XIAOBU_CONFIG.name == "xiaobu"
    def test_config_has_skills(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert len(XIAOBU_CONFIG.skill_names) >= 3

def _mc(http_mock):
    return patch("app.utils.http_client.get_admin_api_client", return_value=http_mock)

class TestResolveXiaobuBotName:
    @pytest.mark.asyncio
    async def test_returns_default_when_no_config(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_bot_name, DEFAULT_BOT_NAME
        mc = AsyncMock(); mc.get = AsyncMock(return_value={"success": False, "data": None})
        with _mc(mc): assert await resolve_xiaobu_bot_name(tenant_id=999) == DEFAULT_BOT_NAME
    @pytest.mark.asyncio
    async def test_returns_custom_bot_name(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_bot_name
        mc = AsyncMock(); mc.get = AsyncMock(return_value={"success": True, "data": {"botName": "定制小布"}})
        with _mc(mc): assert await resolve_xiaobu_bot_name(tenant_id=1) == "定制小布"
    @pytest.mark.asyncio
    async def test_falls_back_on_exception(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_bot_name, DEFAULT_BOT_NAME
        with patch("app.utils.http_client.get_admin_api_client", side_effect=Exception("net")):
            assert await resolve_xiaobu_bot_name(tenant_id=1) == DEFAULT_BOT_NAME
    @pytest.mark.asyncio
    async def test_ignores_empty_bot_name(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_bot_name, DEFAULT_BOT_NAME
        mc = AsyncMock(); mc.get = AsyncMock(return_value={"success": True, "data": {"botName": "   "}})
        with _mc(mc): assert await resolve_xiaobu_bot_name(tenant_id=1) == DEFAULT_BOT_NAME

class TestResolveXiaobuGreeting:
    @pytest.mark.asyncio
    async def test_returns_default_when_no_config(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting, DEFAULT_GREETING
        mc = AsyncMock(); mc.get = AsyncMock(return_value={"success": False})
        with _mc(mc): assert await resolve_xiaobu_greeting(tenant_id=999) == DEFAULT_GREETING
    @pytest.mark.asyncio
    async def test_returns_greeting_template(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting
        mc = AsyncMock(); mc.get = AsyncMock(return_value={"success": True, "data": {"greetingTemplate": "你好 {bot_name}！", "botName": "小布Plus"}})
        with _mc(mc):
            result = await resolve_xiaobu_greeting(tenant_id=1)
            assert "小布Plus" in result and "{bot_name}" not in result
    @pytest.mark.asyncio
    async def test_falls_back_on_exception(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting, DEFAULT_GREETING
        with patch("app.utils.http_client.get_admin_api_client", side_effect=Exception("net")):
            assert await resolve_xiaobu_greeting(tenant_id=1) == DEFAULT_GREETING

class TestGetXiaobuGreeting:
    @pytest.mark.asyncio
    async def test_delegates_to_resolve(self):
        from app.agents.agents.xiaobu import get_xiaobu_greeting
        import app.agents.agents.xiaobu as xm
        with patch.object(xm, 'resolve_xiaobu_greeting', new_callable=AsyncMock) as m:
            m.return_value = "custom"
            result = await get_xiaobu_greeting(tenant_id=1, channel="web")
            assert result == "custom"
            m.assert_called_once_with(1, "web")
