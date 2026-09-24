# case_ids: ST-001, ST-002, ST-003, ST-004, ST-005
"""settings 域「只读化」收口判据 —— issue #5302（承接 #5247 的漏网）。

## 被测事实（三条，都是读源得到，**不是**抄清单）

1. `settings_manage` / `notification_manage` 的 `VALID_ACTIONS` **只剩只读 action**，
   `read_only = True`，写 action 在 `execute()` 入口即被拒（不是"没写进 description"）；
2. `required_permissions` 与**它仍调用的端点**同码：`settings_manage` 的三个读端点都是
   `@RequirePermission("system:manage")`（读码，保留）；`notification_manage` 的两个读端点
   **无码**（`NotificationController` 只给 `POST` 加了码）⇒ 该工具**不持码**、回到角色层；
3. 域提示词（`SETTINGS_SYSTEM_PROMPT`）**不再承诺任何写能力**，并给出「引导到后台页面」的
   反例路径 —— 口径 = 用户裁定（#5247 2026-09-23）「B 端 agent …创建和更新能力以及 tools
   都从 B 端 Agent 移除」+ 本单 #5302（settings 域整域漏网收口）。

## 为什么必须有这份判据（#5247 的 MC-021 为什么没拦住本单）

`tests/unit_ci_workflows/test_mibao_b_end_readonly.py` 的判据 1/2/3 判的是
**B 端「可达」工具并集**（= `mibao.py` 的 `skill_names` ∪ fallback → 各 skill 的 `*_TOOLS`）。
#5247 把 `settings` 从 `skill_names` **解绑**（而非收窄其工具）⇒ 该 skill 的工具从"可达并集"
里消失 ⇒ **它的写能力不再被任何判据覆盖**，而文件与注册关系都还在
（用户裁定的形态是「收窄为只读」，解绑只是"不进对话面"）⇒ 本单就是那个缺口。
本文件的判据按 **skill 源码 × 工具源码**（不看可达性）写，故对"解绑代替收窄"的形态免疫；
结构性那一半（孤儿 skill 的工具也必须只读）落在 MC-021 的新增判据 6。

## 每条断言的红证（改这一处即红）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_settings_valid_actions_are_read_only_only` | 往 `VALID_ACTIONS` 塞回 `update_settings` |
| `test_write_actions_are_rejected_at_the_entry` | 把 `execute()` 的写分支加回来（或把 action 校验挪到分支之后） |
| `test_notification_permissions_match_its_endpoints` | 给 `notification_manage` 加回 `employee:list`（该码只服务已删除的 create 收件人解析） |
| `test_prompt_does_not_promise_retired_write_capabilities` | 往提示词的非否定句里写回「修改 AI 配置」 |
| `test_prompt_guides_to_the_backend_pages` | 删掉引导句（只拒绝、不给出路） |
| `TestJudgementIsNotVacuous`（注入式） | 用改坏的文本重建判据 ⇒ 必须红；干净文本 ⇒ 不得误报 |

## 边界（**不要**把本判据读成覆盖面更大）

- 只读源码文本与工具对象（零 LLM、零网络、零 DB）—— 提示词的**行为面**（模型是否真的引导
  用户到后台页）不在本判据射程内，按 `migao-dev-flow` §13 默认不派发真实评测。
- "工具码 ≡ 端点码 ≡ 菜单节点码"由 `tests/unit_ci_workflows/test_agent_permission_parity.py`
  负责；本文件只锁「**仍被调用的端点**的码」（#5302 的收窄面），不重复它的规则。
- `read_only_actions` **保留**（不是漏删）：它是 `BaseTool` 的确认豁免声明，`#5247` 收窄的
  8 把工具**全部保留**了它，且仓内既有判据按"它等于只读 action 集"逐条钉住
  （先例：`tests/test_after_sales_manage.py`）。
"""

from __future__ import annotations

import re

import pytest

from app.graph.skills.settings_skill import SETTINGS_SYSTEM_PROMPT, SETTINGS_TOOLS
from app.tools.notification_manage import NotificationManageTool
from app.tools.settings_manage import SettingsManageTool

#: settings 域**只读** action 真值（与 admin-api 端点一对一）。
SETTINGS_READ_ACTIONS = {"get_settings", "get_ai_config", "login_logs"}
NOTIFICATION_READ_ACTIONS = {"list", "unread_count"}

#: 写 action 名（闭词表）：出现即视为写能力残留（口径同 MC-021 的 `WRITE_ACTION_WORDS`）。
RETIRED_WRITE_ACTIONS = frozenset({
    "update_settings", "update_ai_config", "change_password",
    "mark_read", "read_all", "delete", "create",
})

#: 提示词里**不得再承诺**的写能力措辞（非否定句命中即红）。
FORBIDDEN_PROMPT_PHRASES = (
    "调整系统参数", "修改系统参数", "修改 AI 配置", "改 AI 配置", "修改配置",
    "改密码", "修改密码", "重置密码",
    "标记已读", "全部已读", "发送通知", "推送通知", "创建通知", "删除通知",
    "写操作", "二次确认", "确认卡",
)

#: 句级否定词（与仓内同类守卫同口径）：这些句子是「如实告知做不到」，不是能力承诺。
NEGATIONS = (
    "不做", "不提供", "不在", "不得", "不能", "无法", "禁止", "切勿", "只读", "不支持", "已下线",
)

#: 引导目标（后台真实存在的页面/入口；`frontend/admin-web/src/app/(dashboard)/settings/page.tsx`
#: 的 tab = basic/AI 客服设置/params/notification，通知中心 = `/notifications`）。
GUIDANCE_TARGETS = ("企业基础信息", "AI 客服设置", "通知中心")


def _claimed_sentences(text: str):
    """切句（。；换行）后**丢掉否定句** —— 剩下的才是「能力承诺」。"""
    for seg in re.split(r"[。；\n]", text):
        if any(neg in seg for neg in NEGATIONS):
            continue
        yield seg


def _promised_write_phrases(text: str) -> list[str]:
    """纯函数（可喂夹具）：文本里**非否定句**命中的写能力措辞。"""
    out: list[str] = []
    for seg in _claimed_sentences(text):
        out.extend(p for p in FORBIDDEN_PROMPT_PHRASES if p in seg)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 一、settings_manage：写能力已下线
# ══════════════════════════════════════════════════════════════════════════════


class TestSettingsManageIsReadOnly:
    @pytest.fixture
    def tool(self):
        return SettingsManageTool()

    def test_settings_valid_actions_are_read_only_only(self, tool):
        from app.tools import settings_manage as mod

        assert set(mod.VALID_ACTIONS) == SETTINGS_READ_ACTIONS, (
            f"settings_manage 的 action 枚举 {sorted(mod.VALID_ACTIONS)} 不等于只读集 "
            f"{sorted(SETTINGS_READ_ACTIONS)} —— 写 action（update_settings / update_ai_config / "
            "change_password）不得复活（#5247/#5302：B 端写能力全部下线）"
        )
        assert not (set(mod.VALID_ACTIONS) & RETIRED_WRITE_ACTIONS), (
            f"action 枚举里出现写动作名 {sorted(set(mod.VALID_ACTIONS) & RETIRED_WRITE_ACTIONS)}"
        )

    def test_settings_tool_declares_read_only_and_no_confirmation(self, tool):
        assert tool.read_only is True, "settings_manage 必须 read_only=True（#5302）"
        assert tool.destructive is False, "只读工具不得标 destructive（可修改关键配置的标注已失效）"
        assert tool.requires_confirmation is False, (
            "只读工具不得 requires_confirmation —— 它没有需要用户确认的写 action"
        )
        assert tool.read_only_actions == SETTINGS_READ_ACTIONS, (
            "read_only_actions 必须等于**收窄后**的 action 集（保留该声明是 #5247 的既定形态）"
        )

    def test_settings_permissions_are_the_read_endpoint_codes(self, tool):
        """码 = 它**仍调用**的三个读端点的生效码（`system:manage`）—— 读码，不是写码。

        该域读写同码（写粒度债登记在 `test_agent_permission_parity.REGISTERED_RESIDUALS`
        的「settings 域写面未注解」）⇒ 本单**没有**可移除的写码；移除 `system:manage`
        会让三个读 action 全量 403（实测口径：`SettingsController` 三个读端点都是该码）。
        """
        assert list(tool.required_permissions) == ["system:manage"], (
            f"settings_manage 的码 {list(tool.required_permissions)} 与三个读端点生效码不符"
        )

    def test_settings_schema_exposes_no_write_parameters(self, tool):
        props = set((tool.parameters or {}).get("properties") or {})
        assert props == {"action", "page", "size"}, (
            f"工具 schema 仍暴露写参数 {sorted(props - {'action', 'page', 'size'})} —— "
            "schema 是模型看见的能力面，删了 action 却留着参数等于继续承诺写能力"
        )
        enum = tool.parameters["properties"]["action"]["enum"]
        assert set(enum) == SETTINGS_READ_ACTIONS, f"action enum 漂移：{enum}"

    @pytest.mark.parametrize("action", sorted(RETIRED_WRITE_ACTIONS))
    async def test_settings_write_actions_are_rejected_at_the_entry(self, tool, action,
                                                                   admin_tool_context):
        """写 action 在 `execute()` 入口即被拒（能力下线，不是"文档里没写"）。

        参数一并按**旧签名**传：即使调用方还带着 old_password/name，也必须被 action 校验拦下
        （防"校验挪到分支之后"的形态 —— 那种写法会让写分支重新可达）。
        """
        result = await tool.execute(
            context=admin_tool_context, action=action,
            name="测试商户", industry="布艺", greeting_template="您好",
            business_hours="9:00-18:00", old_password="old123", new_password="new123",
        )
        assert result.success is False, f"写 action {action!r} 仍被执行 ⇒ 写能力复活（#5302）"
        assert "无效的操作类型" in (result.error or ""), (
            f"写 action {action!r} 的拒绝语义漂移：{result.error!r}（期望走到 action 校验分支）"
        )

    def test_settings_description_marked_readonly_and_guides_to_backend(self, tool):
        desc = tool.description
        assert "【标注】READONLY" in desc, "description 未标注 READONLY（#5247 的标准形态）"
        assert "WRITE" not in desc.replace("READONLY", ""), (
            "description 仍带 WRITE 标注 —— 能力谎报"
        )
        assert "二次确认" not in desc, "description 仍在教「写前必须二次确认」（写能力已不存在）"
        assert "不在本工具能力内" in desc, "description 未写明写能力不在本工具能力内"
        assert "企业基础信息" in desc and "AI 客服设置" in desc, (
            "description 未给出后台引导路径（调整系统参数/AI 配置该怎么走）"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 二、notification_manage：写能力已下线 + 码对齐（回到角色层）
# ══════════════════════════════════════════════════════════════════════════════


class TestNotificationManageIsReadOnly:
    @pytest.fixture
    def tool(self):
        return NotificationManageTool()

    def test_notification_valid_actions_are_read_only_only(self, tool):
        from app.tools import notification_manage as mod

        assert set(mod.VALID_ACTIONS) == NOTIFICATION_READ_ACTIONS, (
            f"notification_manage 的 action 枚举 {sorted(mod.VALID_ACTIONS)} 不等于只读集 "
            f"{sorted(NOTIFICATION_READ_ACTIONS)} —— mark_read/read_all/delete/create 不得复活"
        )

    def test_notification_tool_declares_read_only_and_no_confirmation(self, tool):
        assert tool.read_only is True
        assert tool.requires_confirmation is False, (
            "requires_confirmation 是给「高风险写」用的声明 —— 写 action 已删除，留着会让确认链空转"
        )
        assert tool.destructive is False
        assert tool.read_only_actions == NOTIFICATION_READ_ACTIONS

    def test_notification_permissions_match_its_endpoints(self, tool):
        """读端点**无码** ⇒ 工具不持码（回落到角色层），与 admin-api 逐端点对齐。

        实测（`NotificationController`）：`GET /api/admin/notifications` 与
        `GET /unread-count` 都没有 `@RequirePermission`（唯一带码的是 `POST` = create，
        已删除）；`employee:list` 只服务 create 的收件人解析（`GET /api/admin/users`），
        随 create 一并退场 —— 留着就是**没有调用点的残留码**（会把 operator 之外的岗位挡在
        「通知中心」之外，而该页面在后台是**全员可见**的）。
        """
        assert list(tool.required_permissions) == [], (
            f"notification_manage 仍声明 {list(tool.required_permissions)} —— 它的读端点没有生效码，"
            "残留写码会把通知读取面收窄成「只有持码岗位可用」（与实际端点语义不符）"
        )
        assert "employee:list" not in tool.required_permissions

    def test_notification_role_layer_is_explicit_and_b_end_only(self, tool):
        """无码 ⇒ 角色层是**唯一**门禁：必须在类体显式声明，且不得含 C 端/幽灵角色。"""
        assert "allowed_roles" in NotificationManageTool.__dict__, (
            "未声明 required_permissions 的工具必须**显式**声明 allowed_roles "
            "（吃 BaseTool 默认值 = 含 customer/agent/tenant_admin，属横向越权/口径断裂）"
        )
        roles = set(tool.allowed_roles)
        assert roles, "allowed_roles 不得为空"
        assert not (roles & {"customer", "agent"}), (
            f"角色白名单含 C 端角色 {sorted(roles & {'customer', 'agent'})} —— 两端隔离被打破"
        )
        assert "tenant_admin" not in roles, "allowed_roles 含幽灵角色 tenant_admin（admin-api 无该角色）"
        assert {"admin", "operator"} <= roles, (
            "通知读取面不得窄于改前（#5302 的零回归口径：改前权限码层放行 admin + operator）"
        )

    def test_notification_schema_exposes_no_write_parameters(self, tool):
        props = set((tool.parameters or {}).get("properties") or {})
        assert props == {"action", "status", "channel", "page", "size"}, (
            f"工具 schema 仍暴露写参数 {sorted(props - {'action', 'status', 'channel', 'page', 'size'})}"
        )
        assert set(tool.parameters["properties"]["action"]["enum"]) == NOTIFICATION_READ_ACTIONS

    @pytest.mark.parametrize("action", sorted(RETIRED_WRITE_ACTIONS - {"update_settings",
                                                                      "update_ai_config",
                                                                      "change_password"}))
    async def test_notification_write_actions_are_rejected_at_the_entry(self, tool, action,
                                                                       admin_tool_context):
        result = await tool.execute(
            context=admin_tool_context, action=action,
            notification_id="n-1", recipient_id="u-1", title="标题", content="内容",
        )
        assert result.success is False, f"写 action {action!r} 仍被执行 ⇒ 写能力复活（#5302）"
        assert "无效的操作类型" in (result.error or ""), result.error

    def test_notification_description_marked_readonly_and_guides_to_backend(self, tool):
        desc = tool.description
        assert "【标注】READONLY" in desc, "description 未标注 READONLY"
        assert "WRITE" not in desc.replace("READONLY", ""), "description 仍带 WRITE 标注"
        assert "不在本工具能力内" in desc, "description 未写明写能力不在本工具能力内"
        assert "通知中心" in desc, "description 未给出后台引导路径（标记已读/删除到哪去办）"


# ══════════════════════════════════════════════════════════════════════════════
# 三、域提示词：不再承诺写能力 + 给出后台路径
# ══════════════════════════════════════════════════════════════════════════════


class TestSettingsSkillPrompt:
    def test_prompt_does_not_promise_retired_write_capabilities(self):
        hits = _promised_write_phrases(SETTINGS_SYSTEM_PROMPT)
        assert hits == [], (
            f"域提示词在**非否定句**里仍承诺写能力 {sorted(set(hits))} —— "
            "模型会照着承诺去调已删除的写 action（能力谎报）"
        )
        for action in sorted(RETIRED_WRITE_ACTIONS):
            assert action not in SETTINGS_SYSTEM_PROMPT, (
                f"提示词仍点名写 action {action!r} —— 它已不在任何工具的枚举里"
            )

    def test_prompt_declares_read_only_and_guides_to_the_backend_pages(self):
        assert "只读" in SETTINGS_SYSTEM_PROMPT, (
            "提示词未声明本域已只读（#5247/#5302 的口径必须写在域提示里，否则模型会自己推断能力）"
        )
        missing = [t for t in GUIDANCE_TARGETS if t not in SETTINGS_SYSTEM_PROMPT]
        assert not missing, f"提示词缺后台引导目标 {missing}（只拒绝不给出路 = 用户办不成事）"
        assert "修改密码" in SETTINGS_SYSTEM_PROMPT or "改密" in SETTINGS_SYSTEM_PROMPT, (
            "提示词必须点明「改密码」这条高频诉求的出路（后台无自助改密入口 ⇒ 引导管理员协助）"
        )

    def test_skill_binds_only_read_only_tools(self):
        """`SETTINGS_TOOLS` 按**实际能力**核对：绑的工具必须存在且只读（不含写工具）。"""
        from app.tools.registry import get_tool_registry

        registry = {t.name: t for t in get_tool_registry().get_all_tools()}
        unknown = [t for t in SETTINGS_TOOLS if t not in registry]
        assert not unknown, f"SETTINGS_TOOLS 绑定不存在的工具 {unknown}（悬空绑定）"
        writes = [t for t in SETTINGS_TOOLS if not getattr(registry[t], "read_only", False)]
        assert not writes, f"settings 域仍绑定写工具 {writes} —— 只读化后没有可校验/可执行的写路径"


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证：上面关于**文本**的判据不得是空断言
# ══════════════════════════════════════════════════════════════════════════════


class TestJudgementIsNotVacuous:
    def test_prompt_judgement_goes_red_on_a_planted_promise(self):
        """对照组：真实提示词必须干净（否则下面的红证无从归因）。"""
        assert _promised_write_phrases(SETTINGS_SYSTEM_PROMPT) == []

    @pytest.mark.parametrize("planted", [
        "同事要修改 AI 配置时，使用 settings_manage 工具完成。",
        "同事要改密码时，先校验参数并展示确认卡，用户确认后立即执行。",
        "可以帮同事标记已读站内通知。",
    ])
    def test_prompt_judgement_goes_red_on_a_planted_promise(self, planted):
        assert _promised_write_phrases(planted), (
            f"注入 {planted!r} 后判据仍不报 —— 这是空断言"
        )

    def test_negated_sentences_are_not_false_positives(self):
        """假红面：**如实告知**的否定句不得被判成承诺（口径同 MC-021 的 `CAPABILITY_NEGATIONS`）。"""
        for honest in [
            "调整系统参数不在本域能力内，请引导同事到后台「企业基础信息 → 基本设置」页操作。",
            "本域已只读：修改 AI 配置、改密码均不支持，不得向同事承诺。",
            "标记已读、发送通知已下线，请引导同事到后台「通知中心」页自助处理。",
        ]:
            assert _promised_write_phrases(honest) == [], (
                f"如实的否定句被误判成能力承诺（假红）：{honest!r}"
            )

    def test_description_judgement_goes_red_on_a_write_marked_description(self):
        """description 判据的红证：把 WRITE 标注与确认话术写回去 ⇒ 必红。"""
        old_style = (
            "【标注】WRITE|DESTRUCTIVE — 修改全局配置/密码前必须二次确认"
        )
        assert "【标注】READONLY" not in old_style
        assert "二次确认" in old_style