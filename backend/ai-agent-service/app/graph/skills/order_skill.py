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
ORDER_SYSTEM_PROMPT = """## 创建订单

用户说"创建订单"→ 直接调 order_create，不要先查 product_search。
如果用户已提供客户姓名+手机号+商品名+数量+单价 → 立即汇总确认 → order_create。
缺字段 → 引导补充，不查商品。

⚠️ 商品明细中的颜色/门幅/SKU编码/加工项必须传入 item 的 processing_info 对象，禁止丢弃。
手机号必须 11 位中国大陆手机号。"""

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
