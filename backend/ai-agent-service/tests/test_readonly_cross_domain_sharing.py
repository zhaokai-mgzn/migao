# case_ids: OR-029, OR-014
"""只读工具跨域共享（**非对称切分**）+ persona 硬边界 —— issue #4125（关联 #4123 第二刀）。

## 被测事实（两条，都是读源得到）

1. **域切分原本读写同权**：`create_skill_registry(cfg.tool_names)` 只注册该 skill 声明的工具，
   并把**同一份名单**登记进 `set_tool_scope`（#4017 的不变式：校验域 == 执行域）。
   ⇒ 只读查询（`order_query` 等）在别的域里一律 `Tool not found` —— 模型看不到全局能力面。
2. **本包改成非对称切分**：**写工具**（`read_only=False`）仍按域收紧，**只读工具**
   （`BaseTool.read_only is True`）在**同一 persona 家族**内全域可见/可执行。

## 为什么是「persona 家族」而不是「全局」（R2 ③ 的判据就在这）

`xiaobu`（C 端顾客）与 `mibao`（B 端商家）的可达集是**硬边界**。实测**只被 B 端绑定**的只读
工具截至 issue #5302 为 **23 个**（= 7 把存量 B-only 只读 + #5247 收窄为只读的 **8** 把
（`after_sales_manage` / `category_manage` / `customer_manage` / `employee_manage` /
`finance_api` / `inventory_manage` / `role_manage` / `session_manage`）+ #5247 新增的 **6** 把
（`briefing_query` / `craft_calc_config_query` / `inbound_order_query` /
`operation_catalog_query` / `processing_order_set_query` / `stock_ledger_query`）
+ #5302 收窄为只读的 **2** 把（`notification_manage` / `settings_manage`）；
**唯一口径以 `test_witness_b_end_only_readonly_tools_never_reach_c_end_domains` 的见证集为准**
（本段数量只作导读，抄错即由那条判据报红）⇒ "全局并入只读"会让 C 端当场看见这 23 个 B 端工具
（越权面），故必须按 persona 家族切。家族由 `SkillConfig.system_prompts` 的 key **derive**（不写死
persona 字面量），且**歧义即 fail-closed 不并**（宁可少共享，也不跨 persona 泄露）。

**口径（复算命令，PR 里同款）**：
`persona 可达集 = ∪{cfg.tool_names : cfg.system_prompts ∋ persona}`；B-only = 两集合之差。
本文件所有断言都在**测试期现算**这份集合（**不是**手抄清单）——手抄清单错 1 个工具就漏 1 个
泄露面，故不抄（`migao-dev-flow` §18.1 读源纪律）。

## 每条断言的红证（改这一处即红）

| 用例 | 反例输入（改这一处即红） |
|---|---|
| `test_readonly_shared_within_persona_and_write_still_scoped` | 去掉 `create_skill_registry` 的只读并入 ⇒ 域外只读不可见（**改前实测红**，见 PR 红证表） |
| `test_scope_equals_the_tools_bound_to_the_model` | 只并 registry、不并 `set_tool_scope` ⇒ 校验域≠执行域（#4017 不变式断） |
| `test_no_persona_only_tool_leaks_into_another_personas_domains` | 把"persona 家族"换成"全局" ⇒ C 端域出现 `order_query` |
| `test_ambiguous_persona_request_does_not_widen` | 歧义也放宽 ⇒ 本用例红 |
| `test_widening_never_adds_a_write_tool` | 把写工具一起并进来 ⇒ 红（#4017 的 126 处**写**死角判据不许放松） |
| `test_persona_family_agrees_with_agent_config_reachability` | 两个独立来源（skill 配置 vs AgentConfig）分叉 ⇒ 红 |
"""
import itertools

import pytest

from app.agents.agent_config import get_agent_config
from app.graph.skills.base_skill import create_skill_registry
from app.graph.skills.skill_registry import get_skill_registry
from app.tools.registry import get_tool_registry, get_tool_scope


def _read_only_names() -> set:
    """注册表事实：`read_only is True` 的工具名（**唯一口径**；不用源码正则近似）。"""
    return {t.name for t in get_tool_registry().get_all_tools()
            if getattr(t, "read_only", False)}


def _tools_by_persona() -> dict:
    """`persona → 该 persona 可达的工具集`（∪ 各 SkillConfig.tool_names，现算）。"""
    out: dict = {}
    for cfg in get_skill_registry().get_all():
        for persona in (cfg.system_prompts or {}):
            out.setdefault(persona, set()).update(cfg.tool_names or [])
    assert out, "persona→工具集 派生为空 —— 判据会空跑（fail-closed）"
    return out


def _family_cfgs(cfg) -> list:
    """与 `cfg` 同 persona 家族的全部 SkillConfig（家族 = system_prompts 有交集）。"""
    personas = set(cfg.system_prompts or {})
    assert personas, f"{cfg.name} 没声明任何 persona —— 家族无从 derive"
    return [c for c in get_skill_registry().get_all()
            if personas & set(c.system_prompts or {})]


#: 🔴 **#5247 孤儿台账**（键 = Skill 名，值 = 退场理由）：注册表里**声明了 persona、
#: 却不在该 persona 的 `AgentConfig.skill_names` 里**的 Skill。
#: #5247 把 `settings` 从 `mibao.py` 的 `skill_names` 移出（B 端米宝只读化：它绑的两把
#: `settings_manage` / `notification_manage` 都是写工具），但配置文件与注册关系**保留**
#: ⇒ 两个来源在「工具集」上必然分叉。
#: 台账由 `test_persona_family_agrees_with_agent_config_reachability` 机械校验：
#: 理由必须非空、且与实际孤儿集**双向相等**（新增孤儿 ⇒ 红；陈旧条目 ⇒ 红）。
_ORPHANED_SKILLS: dict = {
    "settings": (
        "issue #5247：B 端米宝只读化 —— 该 Skill 只绑写工具（settings_manage / "
        "notification_manage），已从 mibao 的 skill_names 移出；配置与注册关系保留"
        "（类文件不删、C 端绑定不受影响）"
    ),
}


def _unreachable_declared_skills() -> set:
    """注册表里「声明了 persona、但该 persona 的 `AgentConfig` 够不到它」的 Skill 名集。"""
    out: set = set()
    for cfg in get_skill_registry().get_all():
        for persona in (cfg.system_prompts or {}):
            agent = get_agent_config(persona)
            if cfg.name not in set(agent.get_all_skill_names()):
                out.add(cfg.name)
    return out


def _a_family_with_out_of_domain_write() -> tuple:
    """现算：**存在「域外写工具」的 persona 家族**（返回 `(该家族某 cfg, 域外写工具集)`）。

    为什么要现算（#5302）：`mibao` 家族在 #5247 + #5302 之后**已无任何写工具** ——
    写方向的域拦判据不能再锚在它身上（会退化成恒真空断言）。当前唯一命中的是 C 端家族
    （`order_create` / `aftersale_create`）。**找不到任何这样的家族 ⇒ 由调用方 fail-closed 判红**，
    不允许判据因"恰好没有写工具"而静默消失。
    """
    read_only = _read_only_names()
    for cfg in sorted(get_skill_registry().get_all(), key=lambda c: c.name):
        own = set(cfg.tool_names or [])
        family_tools = {t for c in _family_cfgs(cfg) for t in (c.tool_names or [])}
        kept_out = (family_tools - read_only) - own
        if kept_out:
            return cfg, kept_out
    return None, set()


def _scope_after(tool_names):
    """生产同一工厂造域 → 返回 `(registry, 校验域, 绑定给模型的工具名集)`。

    第三条 = `get_langchain_tools()` 的名字集 —— 就是 `prepare_turn` 交给 `bind_tools` 的那份，
    与 `get_tool_scope()` **必须逐名相等**（#4017 不变式）。
    """
    reg = create_skill_registry(list(tool_names))
    bound = {t.name for t in reg.get_langchain_tools()}
    return reg, get_tool_scope(), bound


class TestReadonlySharingWithinPersona:
    """① 只读共享（正向）与写工具域拦（不得放松）—— 同一轮两个方向都断言。"""

    def test_readonly_shared_within_persona_and_write_still_scoped(self):
        """**红证主体**：域外**只读**工具改后必须可见/可执行；域外**写**工具仍不可见。

        两个方向在**同一条用例**里断言（防"只测放行"的单向假绿）。
        """
        cfg = get_skill_registry().get("product")
        if cfg is None:
            pytest.fail("product skill 不在注册表 —— 判据指错对象")

        own = set(cfg.tool_names)
        family = _family_cfgs(cfg)
        family_tools = {t for c in family for t in (c.tool_names or [])}
        read_only = _read_only_names()

        gained = (family_tools & read_only) - own          # 只读共享应带来的增量
        assert gained, "同家族里没有『域外只读』可共享 —— 判据空跑（fail-closed）"

        # 见证（现算集合的具体样本；产品域没有这两把查询工具，改前必然拿不到）
        assert {"order_query", "dashboard_stats"} <= gained, (
            f"派生的域外只读集 {sorted(gained)} 缺已知见证工具 —— 口径漂移了"
        )

        reg, scope, bound = _scope_after(cfg.tool_names)

        missed = sorted(n for n in gained if not (
            reg.get_tool(n) is not None and n in scope and n in bound))
        assert not missed, (
            f"域外**只读**工具在 {cfg.name} 域里仍不可见/不可执行：{missed} —— "
            f"只读跨域共享没落地（模型被拒时看不到别处的查询能力）"
        )

        # ── 反方向：域外**写**工具必须仍被域拦（#4017 的 126 处死角判据不许放松）────
        # 🔴 **#5302 改判（不是放宽）**：`mibao` 家族在 #5247 + #5302 之后**已无任何写工具**
        #    （settings 域是本轮最后两把）⇒ 写方向不能在它身上测（那里没有域外写工具，
        #    继续锚在它身上 = 恒真空断言）。改由**现算**找一个「家族内存在域外写工具」的域
        #    （当前 = C 端家族）；**找不到任何这样的家族 ⇒ fail-closed 判红**。
        write_cfg, kept_out = _a_family_with_out_of_domain_write()
        # 用 `raise` 而非 `assert … is not None`：后者会被弱断言门禁登记为「空断言」
        # （仓内先例：tests/test_skill_config_registry.py 的 fail-closed 前提自检）。
        if write_cfg is None:
            raise AssertionError(
                "全仓没有任何 persona 家族存在『域外写工具』—— R2 的写方向判据无从成立"
                "（fail-closed：判据不得静默退化）")
        w_reg, w_scope, w_bound = _scope_after(write_cfg.tool_names)
        leaked_writes = sorted(n for n in kept_out if (
            w_reg.get_tool(n) is not None or n in w_scope or n in w_bound))
        assert not leaked_writes, (
            f"域外**写**工具被放进了 {write_cfg.name} 域：{leaked_writes} —— "
            f"#4017 的域拦（126 处死角判据）被只读共享顺带放开了"
        )

    def test_scope_equals_the_tools_bound_to_the_model(self):
        """#4017 不变式（全 skill）：**校验域** == **执行域** == `bind_tools` 名字集。

        只并 registry 不并 `set_tool_scope`（或反之）都会让这条红 —— 那正是"一边并一边不并"
        的形态：`validate_input` 放行、模型却 `Tool not found`（空头承诺，后果链见 #3976）。
        """
        checked = 0
        for cfg in get_skill_registry().get_all():
            if not cfg.tool_names:
                continue
            reg, scope, bound = _scope_after(cfg.tool_names)
            checked += 1
            if scope is None:
                pytest.fail(f"{cfg.name}: 工厂没登记执行域（域闸门静默失效）")
            assert scope == frozenset(reg.get_tool_names()), (
                f"{cfg.name}: 校验域与 registry 实注册名单不一致 —— 域闸门判的不是模型手里的工具"
            )
            assert scope == frozenset(bound), (
                f"{cfg.name}: 校验域与 bind_tools 名字集不一致："
                f"仅校验域有 {sorted(scope - frozenset(bound))}，"
                f"仅绑定有 {sorted(frozenset(bound) - scope)}"
            )
        assert checked >= 10, f"只比对了 {checked} 个 skill —— 判据疑似扫不到对象"


class TestPersonaBoundaryIsHard:
    """R2 ③：C 端（xiaobu）不得因此看到 B 端工具 —— persona 可达集仍是硬边界。"""

    def test_no_persona_only_tool_leaks_into_another_personas_domains(self):
        """对称判据：**任一** persona 的专属工具都不得出现在**另一** persona 的域里。

        对 persona 两两取差集（不写死 `mibao`/`xiaobu`）——单向断言会漏掉反方向的泄露，
        而泄露后果同量级（拿别人的工具名去操作别人的数据面）。
        """
        by_persona = _tools_by_persona()
        personas = sorted(by_persona)
        assert len(personas) >= 2, f"只派生到 {personas} 个 persona —— 边界判据无从成立"

        leaks: list[str] = []
        checked = 0
        for owner, other in itertools.permutations(personas, 2):
            only_owner = by_persona[owner] - by_persona[other]
            assert only_owner, f"{owner} 没有专属工具 —— 判据对空集恒真（退化）"
            for cfg in get_skill_registry().get_all():
                if other not in (cfg.system_prompts or {}):
                    continue
                checked += 1
                _reg, scope, _bound = _scope_after(cfg.tool_names)
                hit = sorted(scope & only_owner)
                if hit:
                    leaks.append(
                        f"{cfg.name}（{other} 端）里出现了 {owner} 端专属工具 {hit}")
        assert checked >= 6, f"只比对了 {checked} 个域 —— 判据疑似空跑"
        assert not leaks, "persona 硬边界被只读共享打破：\n  " + "\n  ".join(leaks)

    def test_witness_b_end_only_readonly_tools_never_reach_c_end_domains(self):
        """见证（现算，不抄清单）：B 端专属**只读**工具 **23** 把，C 端域一个都不许有。

        这 23 把是 #4125 里"为什么不能全局并只读"的**唯一量化依据**：
        全局并只读 ⇒ C 端当场多出这 23 个越权查询面。

        🔴 **2026-09-21 改判（本 PR rebase 到当时 main 后实测，非放宽）**：
        ① 原写 5 把且含 `processing_item_query` —— 该工具**现已是两端共有**
           （实测 `mibao=True xiaobu=True`：#4371 把加工项与商品解耦、事实源改为**店铺级目录**之后，
           C 端小布也能查加工项）⇒ 它**不再是** B 端专属，留在见证清单里就是**假见证**；
        ② main 后续新增两把 B 端专属只读工具（`processing_order_query` / `production_worklog_query`）
           ⇒ 真实数量 5 → **6**。
        **判据由 `<=` 收紧为 `==`**（增强，不是放宽）：原 `<=` 只要求「清单里那几把都在」，
        于是**清单写错（多写一把已共有的工具）时它照样绿** —— 本次实测的漂移正是这种形态。
        改为**集合相等**后，任何一把进出都必须在本见证里显式留痕。

        🔴 **2026-09-23 改判（issue #5188 进场，实测）**：新增 `batch_stock_query`
        （批次余量 / 剩余量分布 / 省料度量；声明 `product:list` ⇒ C 端恒不可达，
        且批次成本与省料金额是内部口径）⇒ 6 → **7**。

        🔴 **2026-09-24 改判（issue #5247 进场，实测；B 端米宝只读化，用户裁定 2026-09-23）**：
        7 → **20**，两个来源都是本单的正面事实（不是口径漂移）：
        ① **8 把写工具收窄为只读**（写 action 删除 + `read_only = True`）⇒ 它们从"B 端写工具"
           变成"B 端专属只读工具"，**全部进场**：`after_sales_manage` / `category_manage` /
           `customer_manage` / `employee_manage` / `finance_api` / `inventory_manage` /
           `role_manage` / `session_manage`；
        ② #5247 新增 **6** 把只读工具（C 端 skill 一个都没绑 ⇒ B-only）：`briefing_query` /
           `craft_calc_config_query` / `inbound_order_query` / `operation_catalog_query` /
           `processing_order_set_query` / `stock_ledger_query`。
        ⇒ 本见证同时是 #5247「B 端只读面**没有**渗到 C 端」的量化判据：这 20 把只要有一把
        出现在任一 C 端域的 `set_tool_scope` 里，本用例红（越权面）。

        🔴 **2026-09-25 改判（issue #5302 进场，实测；settings 域收口）**：见证集 21 → **23**，
        进场的是 `settings_manage` / `notification_manage`（settings 域整域收窄为只读：
        `read_only=False` → `True` ⇒ 它们从"B 端写工具"变成"B 端专属只读工具"）。
        口径一字未改（仍是 `(mibao 可达 - xiaobu 可达) ∩ read_only`），进场是"工具面真的变成只读"
        的正面事实。**顺带订正**：本见证的散文原写「20 把」而集合实为 21 条（陈旧读数，
        集合相等断言不受影响）—— 本次一并订正为**实测值 23**。

        🔴 **2026-09-24 改判（issue #5368 包 2 进场，实测；Agent 深通道）**：23 → **24**，
        进场的是 `image_recognize`（图片识别 → **同页填充计划**：只调 vision 模型与
        `app/vision/**` 的纯函数，**无 admin-api 调用点**、不读也不写业务数据）。
        它绑在 B 端 `product` / `order` 两个 skill 上，**小布（C 端）一个都不绑**
        ⇒ 按本见证的既有口径（`(mibao 可达 - xiaobu 可达) ∩ read_only`）自然进场。
        口径一字未改；「C 端零改动」由此**量化**：C 端域里出现本工具 ⇒ 本用例红。
        """
        by_persona = _tools_by_persona()
        assert {"mibao", "xiaobu"} <= set(by_persona), (
            f"persona 家族集不含 mibao/xiaobu（实测 {sorted(by_persona)}）—— 见证指错对象")
        b_only_readonly = (by_persona["mibao"] - by_persona["xiaobu"]) & _read_only_names()
        assert b_only_readonly == {
            # ── 存量 7 把（#4125 见证起点；`batch_stock_query` 见 #5188 改判）───────────
            # issue #5188：批次账 / 省料度量（声明 `product:list` ⇒ C 端恒不可达；
            # 含批次成本与省料金额，属内部口径）
            "batch_stock_query",
            "dashboard_stats", "logistics_track", "order_query", "piecework_query",
            "processing_order_query", "production_worklog_query",
            # ── #5247 ① 收窄为只读的 8 把（写 action 已删除，见各工具文件的 #5247 注释）──
            "after_sales_manage", "category_manage", "customer_manage", "employee_manage",
            "finance_api", "inventory_manage", "role_manage", "session_manage",
            # ── #5247 ② 新增的 6 把只读工具 ────────────────────────────────────────
            "briefing_query", "craft_calc_config_query", "inbound_order_query",
            "operation_catalog_query", "processing_order_set_query", "stock_ledger_query",
            # ── #5302 ① settings 域整域收窄为只读的 2 把（写 action 已删除）──────────
            "notification_manage", "settings_manage",
            # ── #5368 包 2 进场（Agent 深通道：图 → 同页填充计划；纯本地只读）──────
            "image_recognize",
        }, (
            f"B 端专属只读工具集实测 {sorted(b_only_readonly)} —— 与见证集（24 把）不等，口径漂移"
            "（进场/退场都必须在本见证里显式改判，见 docstring 的 2026-09-21 / 2026-09-23 /"
            "2026-09-24 / 2026-09-25 / 2026-09-24(#5368) 五次改判说明）")
        for cfg in get_skill_registry().get_all():
            if "xiaobu" not in (cfg.system_prompts or {}):
                continue
            _reg, scope, _bound = _scope_after(cfg.tool_names)
            assert not (scope & b_only_readonly), (
                f"{cfg.name} 看见了 B 端专属只读工具 {sorted(scope & b_only_readonly)}")

    def test_persona_family_agrees_with_agent_config_reachability(self):
        """两个**独立来源**必须一致：`SkillConfig.system_prompts` vs `AgentConfig.skill_names`。

        家族派生若只信一处，配置漂移会静默改变边界（"写完没人会因为这件事变红"）。

        🔴 **issue #5247 改判（不是放宽：把分叉显式化，且台账双向相等）**：本单把
        `settings` 从 `mibao.py` 的 `skill_names` 里移出（它只绑写工具，B 端只读化后无理由留在
        米宝的可达集），但**注册关系与配置文件保留** ⇒ 两个来源在"工具集"上必然分叉。
        判据仍然成立、且**比原来更严**：分叉只允许发生在 `_ORPHANED_SKILLS` 逐条登记的
        Skill 上，且台账与实际孤儿集**双向相等** ——
        ① 新增孤儿（有人再摘掉一个 Skill）⇒ 红（原来也会红）；
        ② 台账陈旧（孤儿已归队 / 已从注册表删除）⇒ 红（原来无此判据）。
        """
        by_persona = _tools_by_persona()
        orphans = _unreachable_declared_skills()
        for name, reason in _ORPHANED_SKILLS.items():
            assert isinstance(reason, str) and reason.strip(), (
                f"孤儿台账里的 {name} 没写理由 —— 无理由的豁免等于宽泛 skip")
        assert orphans == set(_ORPHANED_SKILLS), (
            f"注册表里的『声明了 persona 却不在该 persona 的 AgentConfig.skill_names 里』"
            f"Skill 集实测 {sorted(orphans)} —— 与台账 {sorted(_ORPHANED_SKILLS)} 不等：\n"
            "  新增孤儿 ⇒ 要么把它接回 skill_names，要么在 _ORPHANED_SKILLS 里写明理由；\n"
            "  台账陈旧（已归队/已删）⇒ 从 _ORPHANED_SKILLS 删除该条（陈旧台账 = 永久后门）"
        )

        mismatches = []
        for persona in sorted(by_persona):
            agent = get_agent_config(persona)
            reachable: set = set()
            for name in agent.get_all_skill_names():
                cfg = get_skill_registry().get(name)
                if cfg is not None:
                    reachable.update(cfg.tool_names or [])
            # 孤儿 Skill 贡献的只是「仅 skill 配置」一侧的工具 —— 逐条在台账里登记过才允许扣除
            orphan_tools = {
                t
                for cfg in get_skill_registry().get_all()
                if cfg.name in _ORPHANED_SKILLS and persona in (cfg.system_prompts or {})
                for t in (cfg.tool_names or [])
            }
            left = by_persona[persona] - reachable
            only_agent = reachable - by_persona[persona]
            if (left - orphan_tools) or only_agent:
                mismatches.append(
                    f"{persona}: 仅 skill 配置有 {sorted((left - orphan_tools))}；"
                    f"仅 AgentConfig 有 {sorted(only_agent)}")
        assert not mismatches, "persona 家族的两个来源分叉：\n  " + "\n  ".join(mismatches)


class TestAsymmetricSplitIsConservative:
    """防"放宽过头"：非唯一家族不并、只并只读、且**确实**并了（防功能空转）。"""

    def test_ambiguous_persona_request_does_not_widen(self):
        """**fail-closed**：请求的工具集能被**多于一个** persona 解释 ⇒ 不并（不猜）。

        `product_search`/`product_detail` 两端都绑 ⇒ 家族不唯一。此时若"猜一个"家族，
        就是把一端工具泄给另一端的入口。
        """
        reg, scope, bound = _scope_after(["product_search", "product_detail"])
        expected = frozenset({"product_search", "product_detail"})
        assert scope == expected, (
            f"家族不唯一时仍并入了 {sorted(scope - expected)} —— fail-closed 失效")
        assert frozenset(reg.get_tool_names()) == expected == frozenset(bound)

    def test_widening_never_adds_a_write_tool(self):
        """全 skill 扫描：`域内声明之外**新增**的工具` 必须**全是**只读工具。

        这条等价于「#4017 的 126 处**写**死角判据不受影响」的机制侧判据：
        只要新增集里没有写工具，`validate_input` 的域比对对写目标的结果就不变。
        """
        read_only = _read_only_names()
        widened_domains = 0
        for cfg in get_skill_registry().get_all():
            if not cfg.tool_names:
                continue
            _reg, scope, _bound = _scope_after(cfg.tool_names)
            extra = set(scope) - set(cfg.tool_names)
            writes = sorted(extra - read_only)
            assert not writes, (
                f"{cfg.name} 域新增了**写**工具 {writes} —— 非对称切分被破坏")
            if extra:
                widened_domains += 1
        assert widened_domains > 0, (
            "没有任何域因只读共享而变宽 ⇒ 本包功能空转（判据全绿但没落地）")