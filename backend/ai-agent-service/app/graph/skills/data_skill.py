"""
数据分析 Skill 节点（B 端米宝，**只读**，issue #5247）

处理经营看板查询、经营日报（每日简报）、财务流水/对账查询、客服会话查询、计件工资查询。
🔴 登记收支、分配/结束会话已按用户裁定 2026-09-23 从 B 端移除：
本 skill 是「数据查询与分析」定位的主战场，全部工具 `read_only=True`。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 数据 Skill 只读工具
# session_manage: 只读化后仅剩 list / monitor / detail（#5247）
# finance_api:    只读化后仅剩 get_summary / get_transactions / get_reconciliation（#5247）
DATA_TOOLS = ["dashboard_stats", "finance_api", "session_manage",
    # 计件工资/人工成本（issue #3996，M4-I）：「这个月计件总额」「某单人工成本」按
    # 统计/成本语义（statistics/data_report）会路由到本 skill —— 不绑则商家问计件
    # 只能得到能力拒绝。只读，不对 C 端开放（工具 allowed_roles 已排除 customer）。
    "piecework_query",
    # 经营日报（issue #5247 模块覆盖：看板与分析补全）→ GET /api/admin/briefing/today
    # （dashboard:view）。此前 agent 侧完全没有入口。
    "briefing_query",
    "interact"]  # 交互卡片：时间范围/指标口径的**消歧** choice（不再发写确认卡）

# 数据 Skill 专用 System Prompt
DATA_SYSTEM_PROMPT = """当前聚焦经营看板、经营日报、财务查询与客服会话，遇到其他领域需求也应承接（如 "查看订单" → 引导进入订单管理）。

## 🔴 本域已只读（issue #5247 用户裁定 2026-09-23）

登记收支、分配/结束会话**不在能力内**：如实说明并引导商家到后台「财务对账」/「在线接待」页操作，
**不得**承诺代办、不得发写确认卡。

## 核心工具（全部只读）

| 工具 | 场景 |
|------|------|
| dashboard_stats | overview / order_trend / order_status / recent_orders / active_sessions |
| briefing_query | 今日经营日报（每日简报：当日单量/金额/待办等） |
| finance_api | get_summary(收支汇总) / get_transactions(资金流水) / get_reconciliation(应收对账) |
| session_manage | 在线会话 / 排队会话 / 会话详情（list/monitor/detail） |
| piecework_query | 计件工资/人工成本（某工人某月计件合计 + 明细，需姓名，月份可选） |

## 数据原则

- 基于工具返回的真实数据解读，不编造趋势
- 数据缺失时告知 "暂未取到数据"，建议核实时间范围或稍后重试
- 关键指标以 "指标名 + 当前值 + 同/环比" 呈现
- 点出异常波动（显著下滑/激增）并提示关注
- **只读**：任何「帮我记一笔 / 帮我转接」的请求都改为引导到对应后台页面

## 财务回复格式（按 action 之一）

- 收支汇总：收入 / 退款 / 净收入 / 待收款 四项呈现，净收入 = 收入 - 退款
- 资金流水：流水号、类型、金额、支付方式、时间
- 应收对账：订单号、应收、实收、差额，标注未对平项
"""

DATA_SKILL_CONFIG = SkillConfig(
    name="data",
    domain="analytics",
    display_name="数据分析",
    tool_names=DATA_TOOLS,
    route_keys=["data"],
    intents=["dashboard", "statistics", "data_report", "finance", "session_manage"],
    system_prompts={"mibao": DATA_SYSTEM_PROMPT},
    default_persona="mibao",
)
