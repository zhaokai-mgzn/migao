"""
米宝（Mibao）Agent 声明

B 端智能工作助手，面向商家管理员和内部员工。
覆盖商品管理、订单处理、客户管理、人事管理、系统配置、数据分析等全部后台事务。
"""

from app.agents.agent_config import AgentConfig

MIBAO_CONFIG = AgentConfig(
    name="mibao",
    display_name="米宝",
    persona="mibao",
    skill_names=[
        "order",
        "product",
        "aftersales",
        "customer",
        "staff",
        "settings",
        "data",
        # [RAG 禁用] "knowledge",  # 知识库功能当前禁用，启用后取消注释
    ],
    fallback_skill="general",
    allowed_roles={
        "admin",
        "agent",
        "tenant_admin",
        "operation_manager",
        "support_supervisor",
        "support_agent",
        "product_manager",
    },
    greeting=(
        "您好！我是米宝，您的智能工作助手。"
        "我可以帮您处理商品管理、订单处理、库存查询等工作事务，"
        "有什么需要帮忙的吗？"
    ),
    direct_replies={
        "greeting": (
            "您好！我是米宝，您的智能工作助手。"
            "我可以帮您处理商品管理、订单处理、库存查询等工作事务，"
            "有什么需要帮忙的吗？"
        ),
        "farewell": "好的，有需要随时找我~ 祝工作顺利！😊",
        "capabilities": (
            "您好！我是米宝，您的智能工作助手。我可以帮您：\n"
            "🔍 **商品管理** - 搜索商品、查看详情、管理库存\n"
            "📦 **订单处理** - 查询订单状态、物流跟踪、订单管理\n"
            "📚 **知识查询** - 面料知识、工艺流程、产品规格\n"
            "🔧 **售后处理** - 退换货处理、客户投诉、安装指导\n"
            "🖼️ **图片识别** - 上传商品图片，我可以帮您识别商品信息并创建商品记录\n"
            "有什么需要帮忙的吗？"
        ),
    },
)
