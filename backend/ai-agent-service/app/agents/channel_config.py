"""
渠道配置 — 小布多渠道路由

支持渠道: wechat_mini / wechat_h5 / douyin_mini / web
新增渠道只需加配置，不改代码。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ── 渠道标识 ──
CHANNEL_WECHAT_MINI = "wechat_mini"
CHANNEL_WECHAT_H5 = "wechat_h5"
CHANNEL_DOUYIN_MINI = "douyin_mini"
CHANNEL_WEB = "web"

ALL_CHANNELS = {CHANNEL_WECHAT_MINI, CHANNEL_WECHAT_H5, CHANNEL_DOUYIN_MINI, CHANNEL_WEB}


@dataclass(frozen=True)
class ChannelConfig:
    """单个渠道的配置覆盖"""

    greeting: str = ""
    farewell: str = ""
    capabilities: str = ""
    quick_replies: List[str] = field(default_factory=list)


# ── 默认渠道配置 ──

DEFAULT_CHANNEL_CONFIGS: Dict[str, ChannelConfig] = {
    CHANNEL_WECHAT_MINI: ChannelConfig(
        greeting="您好！我是{bot_name}，米高窗帘的智能客服。我可以为您查订单、看物流、了解商品，有什么可以帮您的吗？",
        capabilities=(
            "🔍 **商品咨询** - 搜索商品、查看详情\n"
            "📦 **订单查询** - 查订单、追踪物流\n"
            "🛠️ **售后申请** - 提交售后工单\n"
            "📞 **转人工** - 输入「转人工」联系客服"
        ),
    ),
    CHANNEL_WECHAT_H5: ChannelConfig(
        greeting="您好！我是{bot_name}，米高窗帘的智能客服。有什么可以帮您的吗？",
    ),
    CHANNEL_DOUYIN_MINI: ChannelConfig(
        greeting="您好！我是{bot_name}，米高窗帘的智能客服。有什么可以帮您的吗？",
    ),
    CHANNEL_WEB: ChannelConfig(
        greeting="您好！我是{bot_name}，米高窗帘在线客服。有什么可以帮您的吗？",
    ),
}


def get_channel_config(channel: str, tenant_config: Optional[dict] = None) -> ChannelConfig:
    """获取渠道配置，支持租户自定义覆盖。

    优先级: 租户 TenantAiConfig.channelConfigs[channel]
           → 默认 DEFAULT_CHANNEL_CONFIGS[channel]
           → 空 ChannelConfig()

    Args:
        channel: 渠道标识 (wechat_mini / wechat_h5 / douyin_mini / web)
        tenant_config: 租户 TenantAiConfig 的 channelConfigs JSON

    Returns:
        ChannelConfig: 最终配置
    """
    default = DEFAULT_CHANNEL_CONFIGS.get(channel, ChannelConfig())

    if not tenant_config or not isinstance(tenant_config, dict):
        return default

    override = tenant_config.get(channel, {})
    if not isinstance(override, dict):
        return default

    # 合并：租户覆盖 > 默认值
    return ChannelConfig(
        greeting=override.get("greeting", default.greeting),
        farewell=override.get("farewell", default.farewell),
        capabilities=override.get("capabilities", default.capabilities),
        quick_replies=override.get("quick_replies", default.quick_replies),
    )


def resolve_greeting(channel: str, tenant_config: Optional[dict] = None, bot_name: str = "小布") -> str:
    """解析最终欢迎语，替换 {bot_name} 占位符"""
    ch = get_channel_config(channel, tenant_config)
    greeting = ch.greeting or "您好！我是{bot_name}，有什么可以帮您的吗？"
    return greeting.replace("{bot_name}", bot_name)
