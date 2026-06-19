"""
小布（Xiaobu）Agent 声明 v2

C 端智能客服，面向微信小程序/H5/抖音小程序/Web 等多渠道终端消费者。
提供商品咨询、订单查询/创建、物流追踪、售后申请、知识问答、转人工等服务。

安全: 只读为主 + 订单/售后创建需 confirm + tenant_id 自动注入 + customer 角色隔离

v2 新增:
- TenantAiConfig 集成: botName + greetingTemplate 替换硬编码
- channel_config 集成: 不同渠道不同欢迎语
- human_handoff: 转人工自动创建工单
- 知识问答简化: LLM 内置知识替代 RAG
"""
from typing import Optional
from loguru import logger

from app.agents.agent_config import AgentConfig
from app.agents.channel_config import resolve_greeting

# ── 系统默认值（租户未配置时使用）──

DEFAULT_BOT_NAME = "小布"
DEFAULT_GREETING = (
    "您好！我是小布，米高窗帘的智能客服。"
    "我可以为您介绍商品、查询订单、追踪物流，"
    "还能解答窗帘相关的各种问题，请问有什么可以帮您的吗？"
)

XIAOBU_CONFIG = AgentConfig(
    name="xiaobu",
    display_name="小布",
    persona="xiaobu",
    skill_names=[
        "customer_order",       # 订单查询+物流+创建
        "customer_product",     # 商品搜索+详情
        "customer_aftersales",  # 售后申请+查询
        "customer_knowledge",   # 知识问答(LLM内置)
    ],
    fallback_skill="customer_general",
    allowed_roles={"customer"},
    greeting=DEFAULT_GREETING,
    direct_replies={
        "greeting": DEFAULT_GREETING,
        "farewell": "感谢您的咨询，祝您生活愉快！有需要随时找我哦~ 😊",
        "capabilities": (
            "您好！我是小布，米高窗帘的智能客服。我可以帮您：\n"
            "🔍 **商品咨询** - 搜索商品、查看详情、面料推荐\n"
            "📦 **订单查询** - 查询订单状态、物流追踪\n"
            "🛠️ **售后申请** - 提交售后工单\n"
            "📞 **转人工** - 输入'转人工'联系客服"
        ),
    },
)


# ── TenantAiConfig 集成 ──

async def resolve_xiaobu_bot_name(
    tenant_id: int,
    channel: Optional[str] = None,
) -> str:
    """从 TenantAiConfig 读取机器人名称，失败时回退到默认值。

    优先级: 租户 TenantAiConfig.botName → 系统 DEFAULT_BOT_NAME

    Args:
        tenant_id: 租户ID
        channel: 渠道标识（用于记录日志）

    Returns:
        str: 机器人名称
    """
    try:
        from app.utils.http_client import get_admin_api_client
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/tenant/ai-config",
            tenant_id=tenant_id,
        )
        if response.get("success") and response.get("data"):
            bot_name = response["data"].get("botName")
            if bot_name and bot_name.strip():
                logger.info(
                    f"[xiaobu] Tenant bot_name loaded: {bot_name} | "
                    f"tenant={tenant_id} channel={channel or 'unknown'}"
                )
                return bot_name.strip()
    except Exception as e:
        logger.warning(
            f"[xiaobu] Failed to load bot_name from TenantAiConfig: {e} | "
            f"falling back to default '{DEFAULT_BOT_NAME}'"
        )

    return DEFAULT_BOT_NAME


async def resolve_xiaobu_greeting(
    tenant_id: int,
    channel: Optional[str] = None,
) -> str:
    """获取小布欢迎语，优先使用租户 TenantAiConfig。

    优先级: 租户 TenantAiConfig.greetingTemplate
           → 渠道定制欢迎语（如果 channel 参数提供）
           → 系统 DEFAULT_GREETING

    Args:
        tenant_id: 租户ID
        channel: 渠道标识（wechat_mini / wechat_h5 / douyin_mini / web）

    Returns:
        str: 最终欢迎语
    """
    try:
        from app.utils.http_client import get_admin_api_client
        client = get_admin_api_client()
        response = await client.get(
            "/api/admin/tenant/ai-config",
            tenant_id=tenant_id,
        )
        if response.get("success") and response.get("data"):
            data = response["data"]

            # 1. 优先租户 greetingTemplate
            greeting_template = data.get("greetingTemplate")
            if greeting_template and greeting_template.strip():
                greeting = greeting_template.strip()
                # 替换 {bot_name} 占位符
                bot_name = data.get("botName") or DEFAULT_BOT_NAME
                result = greeting.replace("{bot_name}", bot_name)
                logger.info(
                    f"[xiaobu] Tenant greeting loaded from template | "
                    f"tenant={tenant_id} channel={channel or 'unknown'}"
                )
                return result

            # 2. 如果有 channel 配置，使用渠道专属欢迎语
            bot_name = data.get("botName") or DEFAULT_BOT_NAME
            channel_configs = data.get("channelConfigs")
            if channel and channel_configs and isinstance(channel_configs, dict):
                import json
                if isinstance(channel_configs, str):
                    channel_configs = json.loads(channel_configs)
                result = resolve_greeting(
                    channel, tenant_config=channel_configs, bot_name=bot_name
                )
                logger.info(
                    f"[xiaobu] Channel greeting loaded: channel={channel} | "
                    f"tenant={tenant_id}"
                )
                return result

    except Exception as e:
        logger.warning(
            f"[xiaobu] Failed to load greeting from TenantAiConfig: {e} | "
            f"falling back to default"
        )

    # 3. 如果传了 channel，用 channel 默认欢迎语
    if channel:
        from app.agents.channel_config import resolve_greeting as _resolve
        return _resolve(channel, bot_name=DEFAULT_BOT_NAME)

    return DEFAULT_GREETING


async def get_xiaobu_greeting(
    tenant_id: int,
    channel: Optional[str] = None,
) -> str:
    """获取小布欢迎语——整合 TenantAiConfig + channel_config 的首选入口。

    Args:
        tenant_id: 租户ID
        channel: 渠道标识

    Returns:
        str: 最终欢迎语文本
    """
    return await resolve_xiaobu_greeting(tenant_id, channel)
