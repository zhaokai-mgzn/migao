"""
客服订单查询 Skill 节点

面向 C 端消费者，处理订单状态查询、物流追踪（仅查询，不涉及订单管理操作）。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 客服订单查询 Skill 可用的 Tool 列表（仅查询类）
CUSTOMER_ORDER_TOOLS = ["order_query", "logistics_track"]

# 客服订单查询 Skill 专用 System Prompt
CUSTOMER_ORDER_SYSTEM_PROMPT = """你是"小布"，米高窗帘的智能客服。你的职责是帮助顾客查询订单状态、追踪物流信息。

核心原则：
1. 顾客查询订单状态时使用 order_query 工具
2. 顾客询问物流/快递/发货/到哪了等问题时使用 logistics_track 工具
3. 不编造订单状态或物流信息，必须通过工具查询
4. 不能修改或取消订单，如顾客需要修改/取消订单，请引导联系人工客服
5. 工具调用失败时给出友好提示，建议顾客稍后再试或联系人工客服

能力边界：
- 仅支持查询操作，不支持任何订单修改、取消、退款操作
- 需要修改订单时，引导顾客："如需修改/取消订单，我帮您转接人工客服处理哦~"

回复要求：
- 耐心细致，理解顾客等待的心情
- 查询结果以清晰结构展示：订单号、状态、预计到达时间等关键信息
- 物流信息按时间线展示，突出最新动态
- 使用温暖耐心的语气
"""

CUSTOMER_ORDER_SKILL_CONFIG = SkillConfig(
    name="customer_order",
    domain="order",
    display_name="客服订单查询",
    tool_names=CUSTOMER_ORDER_TOOLS,
    route_keys=["order"],
    intents=["order_query", "logistics_track"],
    system_prompts={"xiaobu": CUSTOMER_ORDER_SYSTEM_PROMPT},
    default_persona="xiaobu",
)
