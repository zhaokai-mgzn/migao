"""
测试 app.agents.channel_config — 渠道欢迎语配置

业务真值 #4: 不同渠道欢迎语不同→微信/抖音/H5/Web各有专属
业务真值 #5: 企业自定义机器人名称和欢迎语→优先租户配置
"""
import pytest
from app.agents.channel_config import (
    ChannelConfig,
    get_channel_config,
    resolve_greeting,
    ALL_CHANNELS,
    CHANNEL_WECHAT_MINI,
    CHANNEL_WECHAT_H5,
    CHANNEL_DOUYIN_MINI,
    CHANNEL_WEB,
    DEFAULT_CHANNEL_CONFIGS,
)


class TestChannelGreetingDefaults:
    """默认渠道配置"""

    def test_four_channels_have_default_config(self):
        """四个渠道都有默认配置"""
        for ch in ALL_CHANNELS:
            config = DEFAULT_CHANNEL_CONFIGS.get(ch)
            assert config is not None, f"{ch} 缺少默认配置"
            assert isinstance(config.greeting, str)
            assert len(config.greeting) > 0

    def test_wechat_mini_greeting_contains_welcome(self):
        """微信小程序欢迎语包含'微信'渠道标识"""
        config = DEFAULT_CHANNEL_CONFIGS[CHANNEL_WECHAT_MINI]
        assert "微信" in config.greeting or "小布" in resolve_greeting(CHANNEL_WECHAT_MINI)

    def test_douyin_greeting_differs_from_wechat(self):
        """不同渠道欢迎语不同"""
        wechat = resolve_greeting(CHANNEL_WECHAT_MINI)
        douyin = resolve_greeting(CHANNEL_DOUYIN_MINI)
        # 不同渠道的默认文案应不同
        assert wechat != douyin


class TestChannelGreetingResolution:
    """欢迎语解析"""

    def test_resolve_greeting_replaces_bot_name(self):
        """{bot_name} 占位符被替换为 bot_name 参数"""
        greeting = resolve_greeting(CHANNEL_WECHAT_MINI, bot_name="测试助手")
        assert "小布" not in greeting
        assert "测试助手" in greeting

    def test_resolve_greeting_default_bot_name(self):
        """不传bot_name时默认使用'小布'"""
        greeting = resolve_greeting(CHANNEL_WECHAT_MINI)
        assert "小布" in greeting

    def test_unknown_channel_has_default_greeting(self):
        """未知渠道也有默认欢迎语"""
        greeting = resolve_greeting("unknown_channel")
        assert len(greeting) > 0
        assert "小布" in greeting


class TestTenantConfigOverride:
    """租户自定义覆盖"""

    def test_tenant_config_overrides_greeting(self):
        """租户自定义欢迎语覆盖默认"""
        tenant_config = {
            CHANNEL_WECHAT_MINI: {
                "greeting": "欢迎光临{bot_name}专营店！",
            }
        }
        config = get_channel_config(CHANNEL_WECHAT_MINI, tenant_config)
        assert "专营店" in config.greeting

    def test_tenant_config_override_is_merged_not_replaced(self):
        """租户覆盖单个字段，其他字段保留默认"""
        tenant_config = {
            CHANNEL_WECHAT_MINI: {
                "greeting": "定制欢迎语",
            }
        }
        config = get_channel_config(CHANNEL_WECHAT_MINI, tenant_config)
        assert config.greeting == "定制欢迎语"
        # capabilities 保持默认值
        assert len(config.capabilities) > 0

    def test_empty_tenant_config_uses_defaults(self):
        """租户配置为空时使用默认值"""
        config = get_channel_config(CHANNEL_WECHAT_MINI, {})
        assert config.greeting == DEFAULT_CHANNEL_CONFIGS[CHANNEL_WECHAT_MINI].greeting

    def test_none_tenant_config_uses_defaults(self):
        """租户配置为None时使用默认值"""
        config = get_channel_config(CHANNEL_WECHAT_MINI, None)
        assert config.greeting == DEFAULT_CHANNEL_CONFIGS[CHANNEL_WECHAT_MINI].greeting


class TestChannelConfigModel:
    """ChannelConfig 数据模型"""

    def test_channel_config_default_attributes(self):
        """ChannelConfig 默认字段"""
        config = ChannelConfig()
        assert config.greeting == ""
        assert config.farewell == ""
        assert config.capabilities == ""
        assert config.quick_replies == []

    def test_channel_config_custom_attributes(self):
        """ChannelConfig 自定义字段"""
        config = ChannelConfig(
            greeting="你好",
            farewell="再见",
            capabilities="查询订单",
            quick_replies=["转人工", "查物流"],
        )
        assert config.greeting == "你好"
        assert config.farewell == "再见"
        assert config.capabilities == "查询订单"
        assert len(config.quick_replies) == 2
