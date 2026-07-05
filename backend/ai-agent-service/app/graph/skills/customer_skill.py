"""
客户关系管理 Skill 节点

处理客户档案查询、客户标签管理、客户跟进等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 客户 Skill 可用的 Tool 列表
# customer_manage: 客户CRUD + 标签 + 跟进记录
# order_query: 查该客户的历史订单
# product_search: 查推荐商品
CUSTOMER_TOOLS = ["customer_manage", "order_query", "product_search",
    "validate_input",  # 写操作前置校验
]

# 客户 Skill 专用 System Prompt
CUSTOMER_SYSTEM_PROMPT = """当前对话聚焦在客户档案查询与维护、客户标签与跟进记录管理，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 查客户信息/档案/电话 → customer_manage
2. 查客户历史订单/买了什么/消费记录 → order_query
3. 写操作（更新资料/标签/备注）→ 先确认再执行
4. 高风险操作（合并/删除）→ 二次确认
5. 数据均通过工具查询，工具失败友好提示
6. 跨领域需求承接引导，不拒绝

回复要求：
- 简洁高效，聚焦同事的客户运营场景
- 展示客户信息时以结构化方式呈现关键字段（姓名、电话、标签、最近下单、消费总额等）
- 多个客户结果以列表展示，并附上唯一标识便于后续操作
- 使用专业高效、同事间协作的语气
- 涉及客户隐私字段（如手机号）时，按系统返回内容展示，不主动外泄
"""

CUSTOMER_SKILL_CONFIG = SkillConfig(
    name="customer",
    domain="crm",
    display_name="客户关系管理",
    tool_names=CUSTOMER_TOOLS,
    route_keys=["customer"],
    intents=["customer_manage", "customer_query"],
    system_prompts={"mibao": CUSTOMER_SYSTEM_PROMPT},
    default_persona="mibao",
)
