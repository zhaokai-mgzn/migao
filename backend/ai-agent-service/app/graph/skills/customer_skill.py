"""
客户关系管理 Skill 节点（B 端黄金策，**查询 + 改客户资料**）

处理客户档案查询、客户标签查询、客户历史订单查询，以及**改客户资料**（issue #8618 接回：
`customer_manage(action=update)`，写、带确认门禁 + 权限复检）。
🔴 建档 / 打标签 / 删标签 / 删客户**仍不在能力内**（用户裁定 2026-10-16「其他操作都需要支持」
的射程内未接；本单只接「改资料」）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 客户域只读工具
# customer_manage: 五个只读 action + update（改客户资料，issue #8618 接回；写、带确认门禁）
# order_query: 查该客户的历史订单
# product_search: 查推荐商品
CUSTOMER_TOOLS = ["customer_manage", "order_query", "product_search",
    "interact",        # 交互卡片：多个同名客户时的**消歧** choice（不再发写确认卡）
]

# 客户 Skill 专用 System Prompt
CUSTOMER_SYSTEM_PROMPT = """## 本域写边界

`customer_manage` 的查询面 = list / detail / list_tags / profile_view / value_view；
**写面只有 `update`（改客户资料）**——建档、打标签、删标签、删客户**不在能力内**：
如实说明并引导商家到后台「客户列表」页（/customers）操作，**不得**承诺代办。

🔴 **改客户资料必须真的执行，不许只回一句引导**（CU-004 的判据 = 工具被真的调用 + 服务端真的改了数据）：
① 先 `customer_manage(action=list, keyword=姓名或手机号)` 拿到真实 `customer_id`（重名多处 ⇒ 先发
choice 卡消歧，不要猜）；② 发 `interact(component=confirm)` 确认卡，卡面逐字带出「哪位客户 + 每个
要改字段的『改前 → 改后』」；③ 商家点卡后立即 `customer_manage(action=update, customer_id, data={…})`
—— `data` 里只放要改的字段（键 = 档案字段名，姓名键是 wechatNickname），其余字段自动保留；
④ 成功后如实转述改了哪几个字段、**其余未动**。

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
