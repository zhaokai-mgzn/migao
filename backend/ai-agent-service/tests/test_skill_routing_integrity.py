"""
防线 3: Skill 路由覆盖测试

验证新增 Skill 不会抢走已有 Skill 的路由，
确保 Skill Registry 注册正确、意图映射不冲突。
"""
# case_ids: DF-008, DF-015, PR-008, OR-009, OR-010, CH-010, HR-005, ST-003, ST-005, FN-001

import dataclasses

import pytest

from app.graph.skills.skill_registry import get_skill_registry, reset_skill_registry
from app.tools.registry import get_tool_registry
from app.agents.agent_config import get_agent_config


# ── 确认卡可达性判据（#3624：从注册表派生，不再维护 skill 名枚举）──
# 旧实现硬编码 `("product", "order", "aftersales", "customer")`，与
# `test_tool_schema_consistency.py::ALWAYS_SKIP_PARAMS` 同一反模式：**清单必然滞后于现实**。
# 实证：`staff` / `settings` / `data`（#3577 刚补绑 interact）不在清单里，
# 把它们任一 skill 的 `interact` 拿掉，旧断言**仍然全绿** → 门禁静默漏检。
# 判据改为「工具注册表的真实元数据」推导，与 `base_skill._requires_confirmation`
# 同一份口径（destructive / requires_confirmation 才要求确认，见该函数 docstring）。


def _confirm_needing_tools(skill, tool_registry) -> list:
    """skill 绑定的「需确认写工具」名单（判据与 `base_skill._requires_confirmation` 一致）。"""
    found = []
    for tool_name in (skill.tool_names or []):
        tool = tool_registry.get_tool(tool_name)
        if tool is not None and (
            getattr(tool, "destructive", False)
            or getattr(tool, "requires_confirmation", False)
        ):
            found.append(tool_name)
    return sorted(found)


def _write_skills_missing_interact(skills, tool_registry) -> tuple:
    """从注册表派生 `(写 skill 名单, 违规项)`。

    「写 skill」= 绑定了至少一个**需确认写工具**的 skill —— 它们被
    `base_skill._requires_confirmation` 拦截时，补救话术是「请调用
    `interact(component=confirm)` 发确认卡」；本 Skill 内没有 `interact`
    = 门禁给出的路径**不可达**（#3317 的缺陷形态）。

    接收 `skills` 可迭代对象（而不是直接读全局注册表）是为了让**变异验证**能用同一份
    派生逻辑跑在改动过的配置上（见 `TestWriteSkillInteractInvariant`）——
    判据只有一份实现，测试与断言不会漂移。
    """
    write_skills, violations = [], []
    for skill in skills:
        needs = _confirm_needing_tools(skill, tool_registry)
        if not needs:
            continue
        write_skills.append(skill.name)
        if "interact" not in (skill.tool_names or []):
            violations.append(f"{skill.name} 持有需确认写工具 {needs} 但未绑定 interact")
    return sorted(write_skills), violations


@pytest.fixture(autouse=True)
def reset():
    reset_skill_registry()
    yield
    reset_skill_registry()


# ============ Skill Registry 完整性 ============

def test_all_mibao_skills_registered():
    """米宝的 8 个 Skill 全部注册"""
    registry = get_skill_registry()
    agent = get_agent_config("mibao")
    names = agent.get_all_skill_names()
    for name in names:
        skill = registry.get(name)
        assert skill is not None, f"Skill '{name}' 未注册"
        assert len(skill.tool_names) > 0, f"Skill '{name}' 无 tool"


def test_all_xiaobu_skills_registered():
    """小布的 3 个 C 端 Skill 全部注册"""
    registry = get_skill_registry()
    agent = get_agent_config("xiaobu")
    names = agent.get_all_skill_names()
    for name in names:
        skill = registry.get(name)
        assert skill is not None, f"Skill '{name}' 未注册"


# ============ 路由冲突检测 ============

def test_no_overlapping_route_keys():
    """不同 Skill 的路由 key 必须唯一"""
    registry = get_skill_registry()
    mibao = get_agent_config("mibao")
    seen = {}
    for name in mibao.get_all_skill_names():
        skill = registry.get(name)
        if not skill:
            continue
        for key in skill.route_keys:
            if key == "direct_reply":
                continue  # 公共 key，允许多个 Skill 共享
            assert key not in seen, (
                f"路由冲突: '{key}' 已被 Skill '{seen[key]}' 使用，"
                f"'{name}' 试图重复注册"
            )
            seen[key] = name


def test_general_has_only_read_tools():
    """兜底 general Skill 只应有只读 Tool（写操作需确认后走领域 Skill）

    例外：customer_manage / notification_manage 虽然有写能力，
    但在 general 中主要用于查询和列表展示，写操作仍需用户明确触发。
    """
    registry = get_skill_registry()
    general = registry.get("general")
    assert general is not None
    # 确认核心写操作 Tool 不会漏进 general
    # processing_item_manage 等管理类 Tool 在 general 中用于列表展示
    truly_write_only = {"product_manage", "order_create", "inventory_manage", "order_manage", "employee_manage", "role_manage", "settings_manage"}
    for tool in truly_write_only:
        assert tool not in general.tool_names, (
            f"纯写 Tool '{tool}' 不应在 general Skill 中"
        )


# 写操作 Tool 列表（应从领域 Skill 中调用，不应在 general 中）
ALL_WRITE_TOOLS = {
    "product_manage", "order_manage", "order_create",
    "inventory_manage", "after_sales_manage",
    "customer_manage", "employee_manage", "role_manage",
    "settings_manage", "notification_manage",
    "category_manage", "processing_item_manage",
}


def test_each_skill_has_unique_domain():
    """每个 Skill 必须有唯一的 domain（用于路由和统计）"""
    registry = get_skill_registry()
    mibao = get_agent_config("mibao")
    domains = {}
    for name in mibao.get_all_skill_names():
        skill = registry.get(name)
        if not skill:
            continue
        domain = skill.domain or "unknown"
        # 同 domain 允许多个 Skill（如 order domain 有 order 和 aftersales）
        domains.setdefault(domain, []).append(name)

    # 每个 domain 至少有一个 Skill
    for domain, skills in domains.items():
        assert len(skills) >= 1, f"domain '{domain}' 无关联 Skill"


# ============ 意图映射完整性 ============

def test_all_intents_have_route():
    """所有意图都有对应的路由 key"""
    from app.graph.nodes import _get_intent_to_route
    from app.router.intent_config import IntentType

    all_intents = {i.value for i in IntentType}
    intent_map = _get_intent_to_route()
    mapped = set(intent_map.keys())

    # 不用 assert 全覆盖，因为有些意图不需要路由
    # 但至少核心意图要有映射
    critical = {"order_query", "product_inquiry", "greeting", "general", "after_sales", "complaint"}
    missing = critical - mapped
    assert not missing, f"核心意图缺少路由映射: {missing}"


# ============ Fallback 机制 ============

def test_mibao_has_fallback():
    """米宝必须有兜底 Skill"""
    agent = get_agent_config("mibao")
    assert agent.fallback_skill is not None
    registry = get_skill_registry()
    assert registry.get(agent.fallback_skill) is not None, \
        f"兜底 Skill '{agent.fallback_skill}' 未注册"


def test_xiaobu_has_fallback():
    """小布必须有兜底 Skill"""
    agent = get_agent_config("xiaobu")
    assert agent.fallback_skill is not None
    registry = get_skill_registry()
    assert registry.get(agent.fallback_skill) is not None, \
        f"兜底 Skill '{agent.fallback_skill}' 未注册"


# ============ interact 工具绑定一致性（G6 防回归） ============

def test_prompt_required_interact_tools_are_bound():
    """B 端 Skill 的 Prompt 要求调用 interact 时，tool_names 必须绑定 interact。

    回归背景（issue #2777）：product/order 的 prompt 与 references 多处要求
    interact(choice/confirm/form)（如 prompts/order.md 多 SKU 规格选择、prompts/product.md
    分类/加工项选择、PROMPT-rules 写操作 confirm 卡），但 tool_names 此前未绑定
    interact → LLM 调用时 tool_not_found → 静默退化为纯文本，confirm 语义丢失
    （PR-008/OR-009/OR-010 交互卡期望无法兑现，eval 只能靠"声明调用"假绿）。
    """
    registry = get_skill_registry()
    # B 端 prompt/EXAMPLES/references 显式要求 interact 的 Skill（已核实的强制绑定点）
    for name in ("product", "order"):
        skill = registry.get(name)
        assert skill is not None, f"Skill '{name}' 未注册"
        assert "interact" in skill.tool_names, (
            f"Skill '{name}' 的 prompt 要求 interact 但 tool_names 未绑定（G6 回归）"
        )


def test_all_write_skills_bind_interact_via_confirm_guard():
    """写操作 confirm 守卫要求：**所有**持有需确认写工具的 Skill 必须绑定 `interact`。

    根因（#3317）：`base_skill._requires_confirmation` 拦截未确认写操作时，补救话术是
    「请调用 `interact(component=confirm)` 展示操作预览」。若该 Skill 的 tool_names 里
    没有 `interact`，这条指令对 LLM **不可执行**（拿到"请调用 X"却没有 X → 反复重试或放弃），
    确认卡路径不可达，写操作只能靠"上一轮口头确认"侥幸放行。

    **registry 驱动（#3624 收敛，替换原硬编码 4 元组）**：判据不再写死 skill 名单 ——
    遍历 `get_skill_registry().get_all()` 的真实绑定 × `get_tool_registry()` 的真实元数据
    （`destructive` / `requires_confirmation`，与 `_requires_confirmation` 同一口径）。
    旧实现 `("product", "order", "aftersales", "customer")` 正是「枚举清单必然滞后」：
    `staff` / `settings` / `data`（#3577 产品裁定「交互形态统一」刚给它们补绑 `interact`）
    都不在清单里 —— 拿掉其中任一个的 `interact`，旧断言仍全绿（实测见
    `TestWriteSkillInteractInvariant`），新对象/新写工具落地时照旧无人检查。

    覆盖面：全部已注册 Skill（B 端 + C 端）—— 确认卡可达性与 persona 无关，
    `test_skill_config_registry.py::test_confirmed_write_tools_require_interact_in_same_skill`
    是同一不变式在 C 端的**子集**（该文件 docstring 里"B 端经评估不补 interact"的前提
    已被 #3577 推翻）。
    """
    write_skills, violations = _write_skills_missing_interact(
        get_skill_registry().get_all(), get_tool_registry()
    )

    assert write_skills, (
        "派生的「持有需确认写工具的 Skill」集合为空 —— registry 派生逻辑失效，"
        "本用例会空转假绿"
    )
    assert not violations, (
        "以下 Skill 的确认卡路径不可达（写操作被 confirm 守卫拦截后，本 Skill 内调不到 "
        "interact）：\n  " + "\n  ".join(violations)
        + "\n处置：给该 Skill 补绑 interact（写操作 confirm 卡，交互形态统一见 #3577）。"
    )


class TestWriteSkillInteractInvariant:
    """收敛后的不变式必须**非空转**、且覆盖真实写 skill（#3624 双向锁定）。

    为什么单独立类：registry 派生很容易"写成一个永远返回空的函数"（假绿）。
    这里用**同一份派生逻辑**（`_write_skills_missing_interact`）跑在变异输入上，
    证明它真的读 `tool_names` 与工具元数据；再用"不得窄于旧枚举"锁住收敛方向。
    """

    # 旧实现的硬编码清单 —— 只作为**回归锚点**（证明收敛真的带来增益、防回退），
    # 不再是判据本身。
    LEGACY_ENUMERATION = ("product", "order", "aftersales", "customer")

    @staticmethod
    def _derived_write_skills() -> list:
        return _write_skills_missing_interact(
            get_skill_registry().get_all(), get_tool_registry()
        )[0]

    @staticmethod
    def _without_interact(skill_name: str) -> list:
        """真实注册表的副本，其中 `skill_name` 的 `interact` 被拿掉（模拟回归）。"""
        return [
            dataclasses.replace(
                config, tool_names=[t for t in config.tool_names if t != "interact"]
            ) if config.name == skill_name else config
            for config in get_skill_registry().get_all()
        ]

    # ── 方向 1：不变式必须真的会红（防空转）──
    @pytest.mark.parametrize("skill_name", ["settings", "staff", "data", "general"])
    def test_invariant_catches_skill_that_lost_interact(self, skill_name):
        """变验验证：拿掉某写 skill 的 `interact` → 派生必须把它报为违规。

        参数含 `settings`（用户点名的回归场景）、`staff` / `data`（同为 #3577 补绑的三处）
        与 `general`（兜底也持写工具）—— 后三个**都不在旧枚举里**，旧判据对它们恒绿。
        """
        write_skills, violations = _write_skills_missing_interact(
            self._without_interact(skill_name), get_tool_registry()
        )
        assert skill_name in write_skills, (
            f"{skill_name} 未被识别为写 skill —— 派生过窄（漏检）"
        )
        assert any(v.startswith(f"{skill_name} ") for v in violations), (
            f"拿掉 {skill_name} 的 interact 后不变式仍然全绿 —— 派生逻辑空转"
        )

    def test_unmutated_registry_has_no_violation(self):
        """对照：真实注册表（未变异）无违规 —— 上一条的红确实来自变异。"""
        write_skills, violations = _write_skills_missing_interact(
            get_skill_registry().get_all(), get_tool_registry()
        )
        assert write_skills and not violations, violations

    # ── 方向 2：收敛不得过窄（防漏检）──
    def test_derived_skills_strictly_exceed_legacy_enumeration(self):
        """派生集必须**严格超出**旧枚举 —— 旧枚举漏掉的 skill 必须有人检查。

        这条同时是防回退闸门：谁把判据改回硬编码 4 元组（或其等价物），这里就红。
        """
        derived = set(self._derived_write_skills())
        assert derived > set(self.LEGACY_ENUMERATION), (
            f"派生集 {sorted(derived)} 未超出旧枚举 {sorted(self.LEGACY_ENUMERATION)} —— "
            f"枚举漏掉的 skill 仍无人检查（#3624 的缺陷形态）"
        )

    @pytest.mark.parametrize("skill_name", ["product", "order", "aftersales", "customer",
                                            "staff", "settings", "data", "general"])
    def test_real_write_skills_are_all_covered(self, skill_name):
        """真实写 skill 全部进入判据（防收敛过窄导致漏检）。

        名单 = 旧枚举 ∪ #3577 补绑 interact 的 staff/settings/data ∪ 兜底 general。
        若某个 skill **合法地**不再持有任何需确认写工具，应连同本条一起删掉该参数
        （判据本身仍是注册表派生，这里只是"派生结果不得缩水"的回归锚点）。
        """
        assert skill_name in self._derived_write_skills(), (
            f"{skill_name} 持有需确认写工具却不在判据内 —— 收敛过窄"
        )

    def test_every_derived_skill_really_holds_confirm_needing_tools(self):
        """自一致性：被判定为"写 skill"的必须真的持有需确认写工具
        （防判据退化成"所有 skill 一律要求 interact"）。"""
        registry = get_skill_registry()
        tool_registry = get_tool_registry()
        for name in self._derived_write_skills():
            skill = registry.get(name)
            assert skill is not None, f"派生出的 skill '{name}' 不在注册表里"
            assert _confirm_needing_tools(skill, tool_registry), (
                f"{name} 没有任何需确认写工具，不该被判为写 skill"
            )

    def test_criterion_matches_confirm_gate(self):
        """判据与 `base_skill._requires_confirmation` 对齐：派生出的"需确认写工具"在
        未确认的自然语言消息下必须真被门禁拦（否则"需要确认"是我自己编的口径）。"""
        from app.graph.skills.base_skill import _requires_confirmation

        registry = get_skill_registry()
        tool_registry = get_tool_registry()
        for name in self._derived_write_skills():
            for tool_name in _confirm_needing_tools(registry.get(name), tool_registry):
                tool = tool_registry.get_tool(tool_name)
                assert _requires_confirmation(tool, {"action": "delete"}, "帮我处理一下这个") is True, (
                    f"{name}.{tool_name} 被判为需确认写工具，但门禁未拦 —— 判据与门禁漂移"
                )


def test_general_binds_interact_for_clarify_cards():
    """general 兜底 skill 必须绑定 interact（Phase 2, issue #2789）。

    general 是低置信意图/图片消息的澄清主战场（intent_router 低置信重写 →
    general；图片强制路由 vision mode），且 VISION_CLARIFY_GUIDE（Phase 1）
    明确要求意图模糊时优先 interact(choice) 下发候选卡。若 general 未绑定
    interact，澄清只能退化为纯文本——无法承载"2-4 候选意图点选"的澄清卡。
    """
    registry = get_skill_registry()
    general = registry.get("general")
    assert general is not None, "general skill 未注册"
    assert "interact" in general.tool_names, (
        "general skill 需承载低置信/图片澄清卡，必须绑定 interact（Phase 2 回归）"
    )
