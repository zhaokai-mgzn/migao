"""
系统配置 Skill 节点

处理系统设置、AI 配置与站内通知等管理事务。

🔴 **B 端米宝只读化**（issue #5247 用户裁定 2026-09-23；settings 域整域收口 = issue #5302）：
本域已**只读** —— 提示词不再承诺任何写能力（改系统参数 / 改 AI 配置 / 改密码 /
标记已读 / 发通知 / 删通知），改为「如实告知 + 引导到商户后台页面」。
⚠️ 判据：`backend/ai-agent-service/tests/test_settings_domain_readonly.py`（提示词非否定句
零写能力承诺 + 引导目标必须在场）。往本文件写回任何写能力承诺 = 能力谎报。
"""

from app.graph.state import AgentState
from app.graph.skills.base_skill import execute_skill
from app.graph.skills.skill_config import SkillConfig

# 系统配置 Skill 可用的 Tool 列表
# category_manage 归属 product_skill，不在 settings 域
# #3081: quick_reply_manage 已随快捷回复功能下线移除（被知识卡片替代）
# interact（#3577，2026-09-14 产品裁定「交互形态统一」）：references/prompts/settings.md
# 承诺「写操作先校验参数 + 确认卡 + 用户确认后执行」，门禁补救话术亦要求发确认卡——
# 不绑则承诺不可执行（#3317 的 6 处之一）。写操作安全由 admin-api 层承担。
# 🔴 #5302 核对（按**实际能力**而非历史清单）：本域只读后两个管理工具仍有只读 action
# ⇒ 继续绑定（`settings_manage`：get_settings/get_ai_config/login_logs；
# `notification_manage`：list/unread_count）；本域已无任何写 action。
# ⚠️ `validate_input` **保留绑定**（如实登记，不粉饰）：#5247 把 validate_input 从 8 个 B 端
# skill 解绑，settings 是漏掉的第 9 个（本单**有意不**解绑）—— 解绑它会连带改判 3 条
# **期望 validate_input** 的 B 端用例（DF-003 / DF-010 / OR-030，判据见
# `tests/unit_ci_workflows/test_mibao_case_invariants.py` 的「B 端无任何可满足分支」与
# `scripts/mibao_coverage.py` 的孤儿用例体检），属**另一单**的范围（本单只做 settings 域
# 写能力下线）。
SETTINGS_TOOLS = ["validate_input", "settings_manage", "notification_manage", "interact"]

# 系统配置 Skill 专用 System Prompt
SETTINGS_SYSTEM_PROMPT = """当前对话聚焦在系统设置、AI 配置、站内通知等管理事务，但不要自我设限也不要拒绝其他领域问题。

核心原则：
1. 本域**已只读**（B 端米宝只读化，issue #5247 / #5302）：只做**查询**，不提供任何写操作。禁止承诺或暗示"我帮您改好""已修改成功"。
2. 同事查询系统参数、AI 配置（模型、温度、上下文窗口等）、租户级配置时，使用 settings_manage 工具（action=get_settings / get_ai_config / login_logs）
3. 同事查询站内通知（包括"有没有未读通知"这类查询）时，使用 notification_manage 工具（action=list / unread_count）
4. 同事要求**调整系统参数 / 修改 AI 配置**时，如实说明不在本域能力内，并引导其到商户后台「企业基础信息」页自助修改（基本设置 / AI 客服设置 两个页签）
5. 同事要求**修改密码**时，如实说明不在本域能力内（后台暂无自助改密入口），引导其联系管理员处理；不得编造"已改好"，也不得索取或转述密码
6. 同事要求**标记已读 / 全部已读 / 删除通知 / 发送通知**时，如实说明不在本域能力内，并引导其到商户后台「通知中心」页自助处理
7. 同事查询商品分类树、创建/更新/删除商品分类时，引导同事使用商品管理功能（或说"请切换到商品管理"），settings 域不直接提供分类管理工具
8. 不编造配置项与默认值，所有信息均通过工具查询确认；查不到就如实说查不到，不要用"应该是……"补齐
9. 当同事询问不在本技能工具范围内的需求（例如订单、商品详情、员工、报表等）时，以全能助手身份礼貌承接并提示同事重新描述，不得拒绝或自称只负责设置

回复要求：
- 结构化展示设置项：分组、键名、当前值、说明
- 结构化展示通知/模板/分类：标题、状态、更新时间、关联范围
- 分类树使用缩进/层级结构展示
- 使用专业高效、同事间协作的语气
- 工具调用失败时给出友好提示，建议同事核实参数或稍后重试
"""

SETTINGS_SKILL_CONFIG = SkillConfig(
    name="settings",
    domain="settings",
    display_name="系统配置",
    tool_names=SETTINGS_TOOLS,
    route_keys=["settings"],
    intents=["system_settings", "ai_config", "notification"],
    system_prompts={"mibao": SETTINGS_SYSTEM_PROMPT},
    default_persona="mibao",
)