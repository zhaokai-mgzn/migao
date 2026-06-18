"""
小布（Xiaobu）Agent 声明 v2

C 端智能客服，面向微信小程序/H5/抖音小程序/Web 等多渠道终端消费者。
提供商品咨询、订单查询/创建、物流追踪、售后申请、知识问答、转人工等服务。

安全: 只读为主 + 订单/售后创建需 confirm + tenant_id 自动注入 + customer 角色隔离
"""
from app.agents.agent_config import AgentConfig

XIAOBU_CONFIG = AgentConfig(
    name="xiaobu",
    display_name="小布",
    persona="xiaobu",
    skill_names=[
        "customer_order",       # 订单查询+物流+创建
        "customer_product",     # 商品搜索+详情
        "customer_aftersales",  # 售后申请+查询  ← 新建
        "customer_knowledge",   # 知识问答(LLM内置)
    ],
    fallback_skill="customer_general",
    allowed_roles={"customer"},
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
            "🛠️ **售后申请** - 提交售后工单\n"
            "📞 **转人工** - 输入"转人工"联系客服"
        ),
    },
)
