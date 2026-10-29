"""通知中心 Skill 节点（B 端黄金策；issue #7040）

## 本域是什么

商家问「有没有未读通知 / 未读数是多少」，或说「把这条通知标为已读」「都标成已读」。
职责 = **查询通知 + 标记已读**。

## 🔴 本域为什么不是只读域（能力边界接线，issue #7040）

用户 2026-10-16 裁定（逐字，留痕 = issue #5247 评论「能力边界 终版」）：

> 「对比商家后台观星台的功能，不支持创建商品和订单，其他单据类的也不要支持创建，
> **只允许变更和查下分析类**」· 「删除/停用**不包含（只能改，不能删）**」

⇒ B 端支持面 = **变更（改已存在对象）+ 查询 / 分析 / 导航**。
「标记已读」正是**变更**（商家后台「通知中心」页就有「标记单条已读」/「全部标记已读」）。

接线前本 tool 被 issue #5247/#5302 收窄成纯只读（只有 `list` / `unread_count`）且
**没有任何 B 端 skill 绑定它** ⇒ 按 2026-10-16 的裁定，**「变更」在 B 端物理上不可达**
（这就是本单要修的形态）。接线方式：
- **工具面**：`app/tools/notification_manage.py` 加回 `mark_read` / `read_all`，
  `read_only=False` + `requires_confirmation=True`（变更走**既有**确认门禁）；
- **绑定面**：本 skill 把该工具接回 `mibao` 的 `skill_names`（并绑 `interact` 让确认卡可达）；
- **不接线**：`delete`（删除）/ `create`（创建 + 对外发送）。

判据：`tests/unit_ci_workflows/test_mibao_b_end_readonly.py`（MC-021 的判据 1/3/8）+
`tests/test_notification_manage_change_actions.py`（本域的实例判据）。
"""

from app.graph.skills.skill_config import SkillConfig

# 通知域工具
# notification_manage: list / unread_count（只读）+ mark_read / read_all（变更）
# interact: 交互卡片 —— 标记已读前的**确认卡**（变更走既有确认门禁，补救路径必须可达）
NOTIFICATION_TOOLS = [
    "notification_manage",
    "interact",
]

# 通知域专用 System Prompt
NOTIFICATION_SYSTEM_PROMPT = """## 本域：站内通知查询 + 标记已读

商家问「有没有通知 / 未读数」时用 `notification_manage(action=list|unread_count)`；
说「标为已读 / 都标已读」时用 `action=mark_read`（需 notification_id）或 `action=read_all`。

核心原则：
1. **变更前先确认**：`mark_read` / `read_all` 会改商家的通知状态，先用 `interact` 的 confirm 卡
   把「要改哪条 / 全改」说清楚，商家点头后再执行。**不要**没确认就改（变更要有确认门禁）。
2. **先查后改**：`mark_read` 需要 `notification_id` —— 商家说「把那条通知标为已读」但没给 ID 时，
   先 `list`（可带 `status=unread`）把候选念给商家，拿到 ID 再改；**不要**猜 ID。
3. **只能改自己的通知**：站内通知按当前登录用户隔离，`read_all` 只影响**他自己**的未读通知 ——
   如实说明，不要承诺「把同事的通知也标掉」。
4. **删除与发送不在能力内**：删除通知、给他人发通知**都不做**（用户裁定：删除 ⊂ 不支持；
   创建 + 对外发送同属不支持面）。如实告知，并引导商家到后台「通知中心」页处理。
5. 本域是**变更**域，不是"纯查询域"：商家明确要求标记已读时，**不要**只查询就停下 ——
   查完（需要时）确认后就把事办完。

回复要求：
- 改完复述「改了什么 / 还剩多少未读」（商家靠这句核对）
- 不承诺本域做不到的事（不删除、不代发、不改别人的通知）
"""

NOTIFICATION_SKILL_CONFIG = SkillConfig(
    name="notification",
    domain="notification",
    display_name="通知中心",
    tool_names=NOTIFICATION_TOOLS,
    # route_key 与 intent 都复用**既有** IntentType 成员（`IntentType.NOTIFICATION == "notification"`，
    # `app/router/intent_config.py`）—— 不新造意图：`get_skill_route_map` 会把 route_keys 映射到
    # 本 skill 的节点（`builder.py`：route_key → node_id），故 key 必须与 intent 同名同值。
    # 判据：`backend/ai-agent-service/tests/test_skill_intent_legality.py` 要求 intents ⊆ IntentType 值集。
    route_keys=["notification"],
    intents=["notification"],
    system_prompts={"mibao": NOTIFICATION_SYSTEM_PROMPT},
    default_persona="mibao",
)
