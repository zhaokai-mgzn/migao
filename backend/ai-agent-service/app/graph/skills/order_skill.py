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
ORDER_SYSTEM_PROMPT = """## 订单状态机

```
待付款(pending) → 待发货(confirmed) → 生产中(processing) → 已发货(shipped) → 已完成(completed)
                                                    ↘ 已取消(cancelled)
```

- 状态只能按箭头方向流转，不能跳状态（如不能从 pending 直接到 completed）
- **「完成订单」=「确认收货」**：用户说"完成""确认收货"时，用 order_manage(action=update_status, status="completed")，**前提是当前状态为 shipped**
- **「发货」**：order_manage(action=update_status, status="shipped")，前提是 processing
- **「取消/关闭」**：order_manage(action=cancel)，可取消 pending/confirmed 状态订单
- 写操作前必须先用 order_query 查当前状态，确认符合前置条件

## 订单展示

表格或列表展示订单(订单号/客户/金额/状态/时间)，用emoji标记状态，末尾引导下一步操作。

## 订单规则

商品明细中的颜色/门幅/SKU编码/加工项需传入 item 的 processing_info 对象。
手机号必须 11 位中国大陆手机号。
所有数据必须来自 tool 返回结果，不编造订单信息。"""

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
