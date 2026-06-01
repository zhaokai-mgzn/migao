"""
小布（Xiaobu）Agent 声明

C 端智能客服，面向微信小程序等渠道的终端消费者。
提供商品咨询、订单查询、物流追踪、知识问答等服务，全部只读操作。
"""

from app.agents.agent_config import AgentConfig

XIAOBU_CONFIG = AgentConfig(
    name="xiaobu",
    display_name="小布",
    persona="xiaobu",
    skill_names=[
        "customer_order",
        "customer_product",
        "customer_knowledge",
    ],
    fallback_skill="customer_general",
    allowed_roles={
        "customer",
    },
    greeting=(
        "您好！我是小布，米高窗帘的智能客服。"
        "我可以为您介绍商品、查询订单、追踪物流，"
        "还能解答窗帘相关的各种问题，请问有什么可以帮您的吗？"
    ),
    direct_replies={
        "greeting": (
            "您好！我是小布，米高窗帘的智能客服。"
            "我可以为您介绍商品、查询订单、追踪物流，"
            "还能解答窗帘相关的各种问题，请问有什么可以帮您的吗？"
        ),
        "farewell": "感谢您的咨询，祝您生活愉快！有需要随时找我哦~ 😊",
        "capabilities": (
            "您好！我是小布，米高窗帘的智能客服。我可以帮您：\n"
            "🔍 **商品咨询** - 搜索商品、查看详情、面料推荐\n"
            "📦 **订单查询** - 查询订单状态、物流追踪\n"
            "📚 **知识问答** - 窗帘保养、安装方法、面料知识\n"
            "有什么可以帮您的吗？"
        ),
    },
)
