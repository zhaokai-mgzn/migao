"""
米宝（Mibao）Agent 声明

B 端智能工作助手，面向商家管理员和内部员工。
🔴 定位（用户裁定 2026-09-23 / issue #5247）：**只做数据查询与分析** ——
全部创建/更新能力已从 B 端移除（工具只读化 + 写工具解绑 + 提示词改判）。
覆盖：订单与加工单（含生产进度/报工）、商品与库存（台账/入库单/批次）、
工序库与工艺路线、算料配置、看板与经营日报、财务查询、售后/客户/员工岗位查询、知识库。
系统设置与通知配置**不在 B 端对话面**（settings skill 已从本 agent 解绑）。
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
        # settings 已解绑（issue #5247 用户裁定：系统设置/通知配置不进 B 端对话面）——
        # ⚠️ 本注释**不得**给 skill 名加双引号：权限守卫用双引号字面量解析 `skill_names`，
        # 带引号的注释会被读成「仍绑着 settings」（实测踩到，判据 1/3 立刻红）。
        # skill 文件本身保留在注册表里（`app/graph/skills/settings_skill.py`），
        # 因为删除它会让路由/账本口径漂移，而「不进 B 端」的判据是**绑定面**不是文件存在性。
        "data",
        "knowledge",  # 知识卡片检索（issue #3059：B 端米宝启用，本店政策/价目/售后走知识卡片）
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
        # ── admin-api 商户员工角色码（角色码漂移修复，POC 审查 D 项）──
        # admin-api 实际签发: admin/operator/product_manager/knowledge_editor/customer_service
        # （RegistrationService + RoleService）。此前缺失导致这些角色认证通过后
        # 仍被路由到小布（C 端人格），无法使用米宝 B 端能力。
        "operator",
        "knowledge_editor",
        "customer_service",
    },
    greeting=(
        "您好！我是米宝，您的智能工作助手。"
        "我可以帮您**查数据、做分析**：订单与物流、生产进度与报工、"
        "商品与库存（台账/入库单/批次）、看板与经营日报、财务流水与对账、"
        "售后工单、客户、员工与岗位、知识库。"
        "（创建/修改类操作请在后台对应页面进行。）有什么需要帮忙的吗？"
    ),
    direct_replies={
        "greeting": (
            "您好！我是米宝，您的智能工作助手。"
            "我可以帮您**查数据、做分析**：订单与物流、生产进度与报工、"
            "商品与库存（台账/入库单/批次）、看板与经营日报、财务流水与对账、"
            "售后工单、客户、员工与岗位、知识库。"
            "（创建/修改类操作请在后台对应页面进行。）有什么需要帮忙的吗？"
        ),
        "farewell": "好的，有需要随时找我~ 祝工作顺利！😊",
        "capabilities": (
            "您好！我是米宝，您的智能工作助手。我擅长**数据查询与分析**：\n"
            "📦 **订单与履约** - 订单/物流查询、生产进度（做到哪道工序）、报工明细、加工单查询\n"
            "🧵 **商品与库存** - 商品与 SKU 价格、实时库存与低库存预警、库存台账、入库单与批次、批次余量与省料\n"
            "🏭 **生产与算料** - 工序库、工艺路线模板、算料配置（参数查询）\n"
            "📊 **看板与分析** - 经营看板与趋势、今日经营日报、财务流水与应收对账、客服会话概览\n"
            "🔧 **售后与客户** - 售后工单查询、客户档案与标签、客户历史订单\n"
            "👥 **组织（只读）** - 员工账号、岗位与权限目录、计件工资\n"
            "📚 **知识查询** - 面料知识、工艺流程、产品规格\n"
            "⚠️ 创建、修改、删除类操作（下单/建品/改价/调库存/发通知/改配置等）米宝**不做**，"
            "请在后台对应页面操作。有什么需要帮忙的吗？"
        ),
    },
)