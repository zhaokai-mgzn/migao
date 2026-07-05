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

🔴 用户说"创建订单"→ 立刻调 order_create。禁止先调 product_search！
🔴 用户已提供客户名+手机+商品名+数量+单价 → 直接 order_create，不查商品不犹豫。
缺字段 → 引导补充。商品信息以用户提供的为准，不需要去商品库验证。

⚠️ 商品明细中的颜色/门幅/SKU编码/加工项必须传入 item 的 processing_info 对象。
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
