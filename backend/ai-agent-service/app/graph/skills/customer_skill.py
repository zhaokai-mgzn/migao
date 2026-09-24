"""
客户关系管理 Skill 节点（B 端米宝，**只读**，issue #5247）

处理客户档案查询、客户标签查询、客户历史订单查询。
🔴 建档 / 改资料 / 打标签 / 删标签已按用户裁定 2026-09-23 从 B 端移除。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 客户域只读工具
# customer_manage: 只读化后仅剩 list / detail / list_tags（#5247）
# order_query: 查该客户的历史订单
# product_search: 查推荐商品
CUSTOMER_TOOLS = ["customer_manage", "order_query", "product_search",
    "interact",        # 交互卡片：多个同名客户时的**消歧** choice（不再发写确认卡）
]

# 客户 Skill 专用 System Prompt
CUSTOMER_SYSTEM_PROMPT = """## 🔴 本域已只读（issue #5247 用户裁定 2026-09-23）

`customer_manage` **只剩 list / detail / list_tags**。建档、改资料、打标签、删标签**不在能力内**：
如实说明并引导商家到后台「客户列表」页（/customers）操作，**不得**承诺代办。

核心原则：
1. 查客户信息/档案/电话 → customer_manage(list/detail)
2. 查客户历史订单/买了什么/消费记录 → order_query
3. 查客户标签体系 → customer_manage(list_tags)
4. 同名客户多个结果 → 用 interact(component=choice) 让商家点选，不要猜
5. 数据均通过工具查询，工具失败友好提示
6. 跨领域需求承接引导，不拒绝

回复要求：
- 简洁高效，聚焦同事的客户运营场景
- 展示客户信息时以结构化方式呈现关键字段（姓名、电话、标签、最近下单、消费总额等）
- 多个客户结果以列表展示，并附上唯一标识便于后续查询
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
