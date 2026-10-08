"""定时任务（用户「预约」）Skill 节点（B 端黄金策，issue #6486 包 2）

## 本域是什么

商家把「到点要办的事」委托给黄金策：**建一条待办 → 到点收到站内通知**。

## 🔴 本域是 A 档可逆写（不是只读域）

与黄金策其余域（#5247 起大多只读）不同，本域**有一把写工具**：`scheduled_task_manage`。
它的准入由用户 2026-10-07 裁定（留痕 = `docs/wiki/agent-write-boundary.md` §五 + issue #6486），
白名单与绑定域由 `tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 机械钉住
（`A_TIER_SKILLS` 里 `scheduled_task_manage → reminder`）。

## 为什么单独一个 skill（而不是挂到既有域）

- 语义上它不属于 `order` / `product` / `aftersales` / `customer` / `staff` / `data` / `knowledge`
  任何一域 —— 它是**助手级**能力（跨域的「记住并提醒」），塞进任一业务域都会让该域的
  能力文案与工具面不自洽；
- 判据口径要求 A 档工具「**绑在且仅绑在**」某一个 skill ⇒ 独立域让那条判据**整域可判**
  （不会被业务域的工具集合变化牵连）。
"""

from app.graph.skills.skill_config import SkillConfig

# 定时提醒域工具
# scheduled_task_manage: 建 / 列 / 取消「到点提醒」待办（A 档可逆写）
# interact: 交互卡片 —— 建单前的**确认卡**（A 档要求：写操作要有确认门禁）
REMINDER_TOOLS = [
    "scheduled_task_manage",
    "interact",
]

# 定时提醒 Skill 专用 System Prompt
REMINDER_SYSTEM_PROMPT = """## 本域：把「到点要办的事」记下来（issue #6486）

商家说「3 天后提醒我跟进张先生」「下周提醒我催这批货款」时，用 `scheduled_task_manage` 建一条待办。

核心原则：
1. **建单前先确认**：把「什么时候 + 提醒什么 + 到点去哪办」用 `interact` 的 confirm 卡给商家看一遍，
   商家点头后再 create。**不要**没确认就落库（A 档要求：写操作要有确认门禁）。
2. **三件套一个都不能省**：
   - `criterion` = **商家自己的话**（「你说过：等王总回复后再跟进张先生」）—— 这是到点提醒里
     「为什么推给你」那一句；
   - `action_label` = 到点后去哪办（按钮文案）；
   - `action_url` = 后台页路径（如 `/customers?keyword=张先生`）。
   省了任何一件服务端都会拒 —— 而且**没有处置入口的提醒等于制造焦虑**，这是本域最硬的一条。
3. **fire_at 要带时区**：从当前时间按本机时区（Asia/Shanghai）推算，给完整 ISO8601，
   不要只说「明天」。
4. **只提醒、不代办**：到点发的是**站内通知**。要真去下单/改价/发货，到点后回会话来办 ——
   **不得**承诺「到点我帮你办了」。
5. **只管用户委托的那类**：「发货了通知我」这类**业务节点**提醒属系统派生的每日简报与主动规则，
   如实说明，不要重复建单。
6. 查已有待办 → `list`；商家说「不用提醒了」→ 先 `list` 拿到 ID 再 `cancel`。

回复要求：
- 建单成功后，把「什么时候 / 提醒什么 / 到点去哪」三件事复述一遍（商家靠这句核对）
- 不承诺本域做不到的事（不代办写操作、不提醒别人）
"""

REMINDER_SKILL_CONFIG = SkillConfig(
    name="reminder",
    domain="assistant",
    display_name="定时提醒",
    tool_names=REMINDER_TOOLS,
    route_keys=["reminder", "schedule", "scheduled_task"],
    intents=["scheduled_task_manage"],
    system_prompts={"mibao": REMINDER_SYSTEM_PROMPT},
    default_persona="mibao",
)
