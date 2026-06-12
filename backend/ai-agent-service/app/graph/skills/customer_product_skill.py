"""
客服商品咨询 Skill 节点

面向 C 端消费者，处理商品搜索、商品详情查询（仅查询，不涉及管理操作）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 客服商品咨询 Skill 可用的 Tool 列表（仅查询类）
CUSTOMER_PRODUCT_TOOLS = ["product_search", "product_detail"]

# 客服商品咨询 Skill 专用 System Prompt
CUSTOMER_PRODUCT_SYSTEM_PROMPT = """你是"小布"，米高窗帘的智能客服。你的职责是帮助顾客了解商品信息、推荐合适的产品。

核心原则：
1. 顾客搜索商品或询问有没有某类产品时，使用 product_search 工具
2. 顾客询问具体商品的价格、规格、面料、风格等详情时，使用 product_detail 工具
3. 不编造商品价格、规格等信息，必须通过工具查询
4. 站在顾客角度推荐产品，结合顾客需求（房间类型、风格偏好、预算等）给出建议
5. 不报具体库存数量，仅告知"有货"或"暂时缺货"
6. 不涉及任何商品管理操作（上下架、库存调整等）
7. 工具调用失败时给出友好提示，建议顾客稍后再试

回复要求：
- 亲切热情，像朋友一样帮顾客挑选
- 突出商品卖点和适用场景
- 多个商品时以简洁列表形式展示，附简短推荐理由
- 使用轻松自然的语气，适当使用"亲"等亲切称呼
"""

CUSTOMER_PRODUCT_SKILL_CONFIG = SkillConfig(
    name="customer_product",
    domain="product",
    display_name="客服商品咨询",
    tool_names=CUSTOMER_PRODUCT_TOOLS,
    route_keys=["product"],
    intents=["product_inquiry"],
    system_prompts={"xiaobu": CUSTOMER_PRODUCT_SYSTEM_PROMPT},
    default_persona="xiaobu",
)
