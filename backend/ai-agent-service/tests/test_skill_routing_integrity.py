"""
防线 3: Skill 路由覆盖测试

验证新增 Skill 不会抢走已有 Skill 的路由，
确保 Skill Registry 注册正确、意图映射不冲突。

issue #5247（B 端米宝只读，用户裁定 2026-09-23）：B 端全部 skill 只绑 `read_only=True`
工具 ⇒ 本文件两处派生面的前提随之变化（逐条写在相关用例 docstring 里）：
  · 「持有需确认写工具」的 skill 从 B 端 4 个变成 **C 端 2 个 + `settings`**（后者仍注册、
    仍绑 `settings_manage` / `notification_manage`，但已不在米宝的 `skill_names` 里）；
  · 需要「写工具清单」的判据一律改**注册表派生**（`read_only=False`），不再维护人工清单 ——
    人工清单在 `employee_manage` / `role_manage` / `inventory_manage` 被收窄为只读后立刻误红
    （§19.1「误红即坏断言」）。
"""
# case_ids: DF-008, DF-015, PR-008, OR-009, OR-010, CH-010, CH-019, HR-005, ST-003, ST-005, FN-001

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
    """兜底 general Skill 只应有**只读** Tool（写操作需确认后走领域 Skill）。

    issue #5247 重新锚定（B 端米宝只读）：原判据维护人工清单
    `{product_manage, order_create, inventory_manage, order_manage, employee_manage,
    role_manage, settings_manage}` —— 其中 `employee_manage` / `role_manage` /
    `inventory_manage`（连同 `customer_manage` / `category_manage` / `after_sales_manage` /
    `finance_api` / `session_manage`）已被产品裁定**收窄为只读工具**（保留工具名与只读
    action、权限码改读码）⇒ 它们进 general 是**预期**形态，人工清单从此恒红。
    判据改为**注册表派生**（同本文件 #3594/#3624 的收敛口径，也不再维护第二份人工清单）：
    general 绑定的**每个**工具都必须 `read_only=True` —— 比原清单更强（新写工具落地即入射程，
    不再依赖某次人工补名单）。
    """
    registry = get_skill_registry()
    tool_registry = get_tool_registry()
    general = registry.get("general")
    assert general is not None
    write_bound = sorted(
        name for name in (general.tool_names or [])
        if (tool := tool_registry.get_tool(name)) is not None and not tool.read_only
    )
    assert not write_bound, (
        f"非只读 Tool {write_bound} 出现在 general Skill 中 —— 写操作必须走领域 Skill 的"
        f"确认链（#5247：B 端兜底同样只读）"
    )


# 注（issue #3594 / #3624）：此处原有硬编码 `ALL_WRITE_TOOLS` 常量（12 个工具名）——
# 既从未被任何测试引用（死代码），又是与确认门禁测试同源的**枚举式清单**。
# 凡是需要"全部写工具"的判据，一律从注册表派生（见下方 registry 驱动测试与
# `TestWriteSkillInteractInvariant`），不再维护第二份人工清单（枚举必然滞后于现实，§16.1 L0）。


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

    issue #5247（B 端米宝只读）：派生集随绑定面收缩 —— B 端 skill 不再持有任何需确认写工具，
    持有者只剩 C 端（`customer_order` / `customer_aftersales`）与仍注册的 `settings`。
    判据本身（注册表派生 × 全部已注册 skill）**不需要改口径**：前提变了，判据自动跟着变
    —— 这正是 #3624 收敛掉硬编码枚举的收益。
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
    # ⚠️ issue #5247 重新锚定：原锚点 = B 端 4 元组
    # `("product", "order", "aftersales", "customer")` —— 那 4 个 skill 已不再持有任何
    # 需确认写工具（B 端只读）⇒ 锚点本身失效（`derived > legacy` 变成两个不相交集合的比较）。
    # 改用**仍持有需确认写工具**的 C 端子集（与 `test_skill_config_registry.py` 的 C 端
    # 清单同源）。锚点语义不变：派生集必须**严格超出**它 —— `settings` 不在任何人工枚举里，
    # 靠它证明"派生 ≠ 抄清单"（谁把判据改回硬编码，这里就红）。
    LEGACY_ENUMERATION = ("customer_aftersales", "customer_order")

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
    @pytest.mark.parametrize("skill_name", ["customer_order", "customer_aftersales"])
    def test_invariant_catches_skill_that_lost_interact(self, skill_name):
        """变验验证：拿掉某写 skill 的 `interact` → 派生必须把它报为违规。

        issue #5247 重新锚定：原参数含 `settings`（用户点名的回归场景）、`staff` / `data`
        （#3577 补绑的三处）与 `general`（兜底也持写工具）—— 后三个在 B 端只读后**不再持有
        任何需确认写工具**，拿掉它们的 `interact` 不再产生违规（不是写 skill 了）⇒ 旧参数
        恒红。改用**确实持有需确认写工具**的 skill：C 端 `customer_order` / `customer_aftersales`。
        判据本身仍覆盖全部已注册 skill（一处未漏）。

        🔴 **#5302 再次改判（判据面收窄，不是放宽）**：`settings` 的两把工具也收窄为只读
        （settings 域整域收口）⇒ 它不再是写 skill ⇒ 参数里去掉 `settings`（真值面只剩 C 端两个）。
        "派生 ≠ 抄清单"的判别力改由 `test_derivation_discovers_a_skill_outside_any_enumeration`
        的**合成注入**承担（见下）。
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
        """派生集必须**覆盖并超出**旧枚举 —— 旧枚举漏掉的 skill 必须有人检查。

        这条同时是防回退闸门：谁把判据改回硬编码 4 元组（或其等价物），这里就红。
        issue #5247：锚点从 B 端 4 元组改为 C 端 2 元组（见 `LEGACY_ENUMERATION` 注释）。

        🔴 **#5302 改判（不是放宽）**：原形式是 `derived > legacy`（**严格超出**），其唯一
        证据是 `settings` —— 它不在任何人工枚举里。本单把 settings 的两把工具也收窄为只读
        ⇒ 派生集与旧枚举**重合**（都是 C 端两个）⇒ "严格超出"不再可满足（拿它断言就是恒红）。
        处置：① 改成 `derived >= legacy` + **非空**（枚举里的 skill 一个都不许漏检）；
        ② "派生 ≠ 抄清单"的判别力**不因此消失** —— 改由
        `test_derivation_discovers_a_skill_outside_any_enumeration` 的**合成注入**承担
        （造一个名字不在任何枚举里的写 skill，派生必须认出来）。
        """
        derived = set(self._derived_write_skills())
        assert derived >= set(self.LEGACY_ENUMERATION), (
            f"派生集 {sorted(derived)} 未覆盖旧枚举 {sorted(self.LEGACY_ENUMERATION)} —— "
            f"枚举里的 skill 无人检查（#3624 的缺陷形态）"
        )
        assert derived, "派生集为空 ⇒ 本判据对空集恒真（空壳）"

    def test_derivation_discovers_a_skill_outside_any_enumeration(self):
        """**注入式自证（#5302 新增）**：派生必须能发现「不在任何人工枚举里」的写 skill。

        为什么必须补：`settings` 曾是不在任何枚举里、却持有需确认写工具的 skill（= "派生真的
        在派生"的活证据）。#5302 后它不再持有 ⇒ 该证据消失 ⇒ 若不补注入式自证，
        `test_derived_skills_strictly_exceed_legacy_enumeration` 会退化成"比对两个固定清单"
        （谁把判据改回硬编码，也没有任何东西会红）。
        红证：把 `_write_skills_missing_interact` 改成读硬编码清单 ⇒ 本用例立刻红。
        """
        gated = [t for t in get_tool_registry().get_all_tools()
                 if getattr(t, "destructive", False) or getattr(t, "requires_confirmation", False)]
        assert gated, "注册表里没有任何「需确认写工具」—— 本自证无从成立（fail-closed）"
        synthetic = dataclasses.replace(
            get_skill_registry().get_all()[0],
            name="zzz_synth_write", tool_names=[gated[0].name],
        )
        write_skills, violations = _write_skills_missing_interact(
            [synthetic], get_tool_registry())
        assert write_skills == ["zzz_synth_write"], (
            f"派生没认出合成写 skill（判据疑似读硬编码清单）：{write_skills}")
        assert violations and violations[0].startswith("zzz_synth_write "), violations
        assert "zzz_synth_write" not in self.LEGACY_ENUMERATION, (
            "合成名撞进了旧枚举 —— 本自证失去判别力（换一个名字）")

    @pytest.mark.parametrize("skill_name", ["customer_order", "customer_aftersales"])
    def test_real_write_skills_are_all_covered(self, skill_name):
        """真实写 skill 全部进入判据（防收敛过窄导致漏检）。

        名单 = **注册表派生**的写 skill（持有需确认写工具者）。issue #5247：原名单
        （旧枚举 ∪ #3577 补绑 interact 的 staff/settings/data ∪ 兜底 general）随 B 端
        只读失效 —— B 端 skill 已不持有任何需确认写工具，按本条既定口径（"若某个 skill
        **合法地**不再持有任何需确认写工具，应连同本条一起删掉该参数"）删去 B 端参数。
        🔴 **#5302**：`settings` 也按同一口径删除（它的两把工具收窄为只读 ⇒ 不再是写 skill）
        —— "派生结果不得缩水"的锚点改由 `test_derivation_discovers_a_skill_outside_any_enumeration`
        的合成注入承担。
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
