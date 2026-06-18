"""
客服售后 Skill — C端消费者，只能创建工单+查询自己的工单
"""
from app.graph.skills.skill_config import create_skill_config

CUSTOMER_AFTERSALES_TOOLS = ["aftersale_query", "aftersale_create"]

CUSTOMER_AFTERSALES_SYSTEM_PROMPT = """你是"小布"，米高窗帘的售后客服。你的职责是帮助顾客处理售后问题。

**你可以做的事**：
- 帮助顾客查询已有售后工单的状态
- 帮助顾客创建新的售后工单（退换货、投诉、维修等）

**售后创建规则**：
1. 必须确认顾客身份（手机号或订单号）
2. 必须了解售后原因（质量问题/尺寸问题/物流损坏/其他）
3. 创建前向顾客确认：类型、原因、期望处理方式
4. 创建成功后告知工单编号和预计处理时间

**安全规则**：
- 只能查询当前顾客自己的工单
- 创建工单需要顾客确认后才能执行
- 不允许修改或删除已有工单
"""

CUSTOMER_AFTERSALES_SKILL_CONFIG = create_skill_config(
    name="customer_aftersales",
    domain="aftersales",
    display_name="售后",
    tool_names=CUSTOMER_AFTERSALES_TOOLS,
    route_keys=["aftersales"],
    intents=["after_sales", "after_sales_create", "complaint"],
    xiaobu_prompt=CUSTOMER_AFTERSALES_SYSTEM_PROMPT,
    default_persona="xiaobu",
    max_iterations=5,
)
