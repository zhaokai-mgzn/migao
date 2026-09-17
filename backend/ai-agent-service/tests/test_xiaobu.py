"""小布（Xiaobu）Agent 配置与欢迎语解析单元测试（app/agents/agents/xiaobu.py）

覆盖（issue #2431，ai-chat 域 C 端客服）：
- XIAOBU_CONFIG 声明：name/display_name/persona/skill_names/fallback_skill/
  allowed_roles（customer 允许、admin 拒绝）/direct_replies 三键
- 常量：DEFAULT_BOT_NAME=小布、DEFAULT_GREETING 非空且含「小布」
- resolve_xiaobu_bot_name：定制名 strip / 无配置 / 空白 botName / 异常 → 默认
- resolve_xiaobu_greeting：greetingTemplate > channelConfigs(渠道) > channel 默认 > DEFAULT_GREETING
- get_xiaobu_greeting：纯委托 resolve_xiaobu_greeting 并原样返回
"""
# case_ids: CH-007, DF-007

import pytest
from unittest.mock import AsyncMock, patch

from app.agents.agent_config import AgentConfig
from app.agents.channel_config import resolve_greeting


def _mock_client(response):
    """构造 get_admin_api_client 返回的客户端：get() 返回指定响应。"""
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    return patch(
        "app.utils.http_client.get_admin_api_client", return_value=client
    )


class TestConstants:
    """L2-2: 系统默认常量"""

    def test_default_bot_name(self):
        from app.agents.agents.xiaobu import DEFAULT_BOT_NAME
        assert DEFAULT_BOT_NAME == "小布"

    def test_default_greeting_non_empty_and_contains_bot_name(self):
        from app.agents.agents.xiaobu import DEFAULT_GREETING
        assert len(DEFAULT_GREETING) > 0
        assert "小布" in DEFAULT_GREETING


class TestXiaobuConfig:
    """L2-1: XIAOBU_CONFIG 声明（C 端最小权限）"""

    def test_is_agent_config_instance(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert isinstance(XIAOBU_CONFIG, AgentConfig)

    def test_name_display_name_persona(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert XIAOBU_CONFIG.name == "xiaobu"
        assert XIAOBU_CONFIG.display_name == "小布"
        assert XIAOBU_CONFIG.persona == "xiaobu"

    def test_skill_names_exact_five(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert XIAOBU_CONFIG.skill_names == [
            "customer_order",
            "customer_product",
            "customer_quote",
            "customer_aftersales",
            "customer_knowledge",
        ]

    def test_fallback_skill(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert XIAOBU_CONFIG.fallback_skill == "customer_general"

    def test_allowed_roles_customer_only(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert XIAOBU_CONFIG.allowed_roles == {"customer"}
        assert XIAOBU_CONFIG.allows_role("customer")
        assert not XIAOBU_CONFIG.allows_role("admin")

    def test_direct_replies_has_three_keys(self):
        from app.agents.agents.xiaobu import XIAOBU_CONFIG
        assert set(XIAOBU_CONFIG.direct_replies.keys()) == {
            "greeting",
            "farewell",
            "capabilities",
        }

    def test_capabilities_does_not_promise_handoff(self):
        """能力清单是**直接回复给顾客**的文案：不得再承诺转人工（能力已退场）。

        变更沿革（用户裁定 2026-09-19）：「不应该存在 human_handoff 这种东西，以后全是
        AI 来判断」—— 原断言要求清单里出现「📞 **转人工** - 输入'转人工'联系客服」，
        那等于**当面告诉顾客**一个已经不存在的入口（顾客照着输入「转人工」只会得到
        「系统无人工转接通道」）。替代：清单只列真实可用的能力。
        """
        from app.agents.agents.xiaobu import XIAOBU_CONFIG

        caps = XIAOBU_CONFIG.direct_replies["capabilities"]
        for forbidden in ("转人工", "人工客服", "联系客服"):
            assert forbidden not in caps, (
                f"能力清单又承诺了「{forbidden}」—— 转人工能力已退场，"
                f"这是把顾客指向不存在的入口"
            )
        # 不是"删掉一行了事"：清单必须仍有真实能力项（防退化成空壳文案）
        assert "商品咨询" in caps and "订单查询" in caps and "售后申请" in caps, (
            "能力清单被削成空壳 —— 应只删退场项、保留真实能力"
        )


class TestResolveXiaobuBotName:
    """L2-3/4/5: bot_name 解析优先级 租户配置 → DEFAULT_BOT_NAME"""

    @pytest.mark.asyncio
    async def test_returns_stripped_custom_bot_name(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_bot_name
        with _mock_client(
            {"success": True, "data": {"botName": "  定制小布  "}}
        ):
            assert await resolve_xiaobu_bot_name(tenant_id=1) == "定制小布"

    @pytest.mark.asyncio
    async def test_returns_default_when_success_false(self):
        from app.agents.agents.xiaobu import (
            resolve_xiaobu_bot_name,
            DEFAULT_BOT_NAME,
        )
        with _mock_client({"success": False, "data": None}):
            assert await resolve_xiaobu_bot_name(tenant_id=1) == DEFAULT_BOT_NAME

    @pytest.mark.asyncio
    async def test_returns_default_when_data_none(self):
        from app.agents.agents.xiaobu import (
            resolve_xiaobu_bot_name,
            DEFAULT_BOT_NAME,
        )
        with _mock_client({"success": True, "data": None}):
            assert await resolve_xiaobu_bot_name(tenant_id=1) == DEFAULT_BOT_NAME

    @pytest.mark.asyncio
    async def test_returns_default_when_bot_name_blank(self):
        from app.agents.agents.xiaobu import (
            resolve_xiaobu_bot_name,
            DEFAULT_BOT_NAME,
        )
        with _mock_client({"success": True, "data": {"botName": "   "}}):
            assert await resolve_xiaobu_bot_name(tenant_id=1) == DEFAULT_BOT_NAME

    @pytest.mark.asyncio
    async def test_returns_default_on_exception(self):
        from app.agents.agents.xiaobu import (
            resolve_xiaobu_bot_name,
            DEFAULT_BOT_NAME,
        )
        with patch(
            "app.utils.http_client.get_admin_api_client",
            side_effect=Exception("network down"),
        ):
            assert await resolve_xiaobu_bot_name(tenant_id=1) == DEFAULT_BOT_NAME


class TestResolveXiaobuGreeting:
    """L2-6/7/8/9: 欢迎语优先级链"""

    @pytest.mark.asyncio
    async def test_greeting_template_highest_priority(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting
        with _mock_client(
            {
                "success": True,
                "data": {
                    "greetingTemplate": "你好 {bot_name}！",
                    "botName": "小布Plus",
                },
            }
        ):
            result = await resolve_xiaobu_greeting(tenant_id=1)
        assert result == "你好 小布Plus！"
        assert "{bot_name}" not in result

    @pytest.mark.asyncio
    async def test_greeting_template_defaults_bot_name(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting
        with _mock_client(
            {
                "success": True,
                "data": {"greetingTemplate": "欢迎 {bot_name} 光临"},
            }
        ):
            result = await resolve_xiaobu_greeting(tenant_id=1)
        assert result == "欢迎 小布 光临"

    @pytest.mark.asyncio
    async def test_channel_configs_dict_priority(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting
        with _mock_client(
            {
                "success": True,
                "data": {
                    "botName": "定制小布",
                    "channelConfigs": {
                        "web": {"greeting": "欢迎光临 {bot_name} 专营店"},
                    },
                },
            }
        ):
            result = await resolve_xiaobu_greeting(tenant_id=1, channel="web")
        assert result == "欢迎光临 定制小布 专营店"

    @pytest.mark.asyncio
    async def test_channel_configs_str_falls_back_to_channel_default(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting
        with _mock_client(
            {
                "success": True,
                "data": {
                    "botName": "定制小布",
                    # str 类型 channelConfigs 不满足 isinstance(dict)，
                    # json.loads 分支不可达，落到 channel 默认欢迎语
                    "channelConfigs": '{"web": {"greeting": "忽略"}}',
                },
            }
        ):
            result = await resolve_xiaobu_greeting(tenant_id=1, channel="web")
        assert result == resolve_greeting("web", bot_name="小布")

    @pytest.mark.asyncio
    async def test_no_config_with_channel_uses_channel_default(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting
        with _mock_client({"success": False}):
            result = await resolve_xiaobu_greeting(tenant_id=1, channel="web")
        assert result == resolve_greeting("web", bot_name="小布")

    @pytest.mark.asyncio
    async def test_exception_with_channel_uses_channel_default(self):
        from app.agents.agents.xiaobu import resolve_xiaobu_greeting
        with patch(
            "app.utils.http_client.get_admin_api_client",
            side_effect=Exception("network down"),
        ):
            result = await resolve_xiaobu_greeting(tenant_id=1, channel="web")
        assert result == resolve_greeting("web", bot_name="小布")

    @pytest.mark.asyncio
    async def test_no_config_no_channel_returns_default_greeting(self):
        from app.agents.agents.xiaobu import (
            resolve_xiaobu_greeting,
            DEFAULT_GREETING,
        )
        with _mock_client({"success": False}):
            result = await resolve_xiaobu_greeting(tenant_id=1)
        assert result == DEFAULT_GREETING

    @pytest.mark.asyncio
    async def test_exception_no_channel_returns_default_greeting(self):
        from app.agents.agents.xiaobu import (
            resolve_xiaobu_greeting,
            DEFAULT_GREETING,
        )
        with patch(
            "app.utils.http_client.get_admin_api_client",
            side_effect=Exception("network down"),
        ):
            result = await resolve_xiaobu_greeting(tenant_id=1)
        assert result == DEFAULT_GREETING


class TestGetXiaobuGreeting:
    """L2-10: 首选入口纯委托 resolve_xiaobu_greeting"""

    @pytest.mark.asyncio
    async def test_delegates_to_resolve_xiaobu_greeting(self):
        import app.agents.agents.xiaobu as xm
        from app.agents.agents.xiaobu import get_xiaobu_greeting
        with patch.object(
            xm, "resolve_xiaobu_greeting", new_callable=AsyncMock
        ) as mock:
            mock.return_value = "custom"
            result = await get_xiaobu_greeting(tenant_id=1, channel="web")
        assert result == "custom"
        mock.assert_called_once_with(1, "web")
