"""
订单 Skill 节点

处理订单查询,物流追踪,订单管理等操作。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 订单 Skill 可用的 Tool 列表
ORDER_TOOLS = ["order_query", "order_manage", "order_create", "logistics_track", "product_search", "product_detail",
    "validate_input",  # 写操作前置校验
]

# 订单 Skill 专用 System Prompt
ORDER_SYSTEM_PROMPT = """你是"米宝",专注订单/物流领域。

## 创建流程

收集 → 确认 → 执行。读 order_create schema 了解全部字段,分批引导补充缺失信息。收集齐后展示汇总,用户确认后调 order_create,对话中出现的每个字段都要传入不要遗漏。

## 原则

不编造数据。写操作先确认再执行。表格或列表展示订单(订单号/客户/金额/状态/时间),用emoji标记状态,末尾引导下一步操作。"""

ORDER_SKILL_CONFIG = SkillConfig(
    name="order",
    domain="order",
    display_name="订单管理",
    tool_names=ORDER_TOOLS,
    route_keys=["order"],
    intents=["order_query", "order_create", "logistics_track"],
    system_prompts={"mibao": ORDER_SYSTEM_PROMPT},
    default_persona="mibao",
)
