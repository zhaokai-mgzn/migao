"""
Test C 端（小布）用例集契约（issue #3266）。

背景（假绿复盘）：`local_runner.py` 的 PERSONA=xiaobu 分支在 `filter_by_persona`
之后又加了一层 **宽 tag 过滤**：

    XIAOBU_ONLY_TAGS = {"order_query", "order_create", "aftersale", "query",
                        "product", "knowledge", "wiki"}

`query` / `product` 是通用 tag，几乎每个域都有 → 实测选中 33 条，其中仅 4 条真声明
`persona: xiaobu`，其余为 B 端管理类（DA-001 经营概览 / FN-001 资金流水 /
HR-001 员工列表 / CT-001 分类树 / CU-001 客户 / AS-001 售后工单 / ST-001 设置）——
小布工具集中根本没有 `dashboard_stats`/`finance_api`/`employee_manage`/
`customer_manage`/`after_sales_manage`，这些用例在小布上要么被合理拒绝后判失败，
要么根本没验证到任何东西，却计入「C 端评测通过率」。

本测试锁定两条契约：
1. **工具集真值**：C 端可用工具集 = 各 customer_* skill 的工具并集（防手写集合漂移）。
2. **用例集归属**：PERSONA=xiaobu 选中的用例，其期望工具必须全在 C 端工具集内 ——
   B 端专属工具不得出现在任何 C 端用例断言中。
"""
# case_ids: CH-008, CH-010, CH-012, CH-013, CH-014, CH-015, CH-017, CH-024, OR-012, ST-008, KN-001, KN-002, KN-008
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
SKILLS_DIR = REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"

# 被测 persona（显式传参，不依赖 local_runner 模块级 PERSONA 的默认值）
PERSONA = "xiaobu"

# 小布声明的 skill（app/agents/agents/xiaobu.py 的 XIAOBU_CONFIG.skill_names）
XIAOBU_SKILLS = [
    "customer_order",
    "customer_product",
    "customer_quote",
    "customer_aftersales",
    "customer_knowledge",
]
XIAOBU_FALLBACK_SKILL = "customer_general"

# 已声明 persona: xiaobu 的 C 端专属用例（R3.1 基线：修复后应全部被选中）
XIAOBU_ONLY = {
    "CH-008", "CH-010", "CH-012", "CH-013", "CH-014", "CH-015", "CH-017",
    "CH-024", "OR-012", "ST-008", "KN-001", "KN-002", "KN-008",
}

# B 端专属工具样本（出现即证明 C 端用例集混入 B 端管理用例）
MIBAO_ONLY_TOOLS = {
    "dashboard_stats", "finance_api", "employee_manage", "role_manage",
    "customer_manage", "after_sales_manage", "order_manage", "order_query",
    "product_manage", "inventory_manage", "category_manage",
    "processing_item_manage", "notification_manage", "session_manage",
    "settings_manage", "logistics_track", "sku_update",
}


def _skill_tools(skill_file: Path) -> set:
    """解析 customer_*_skill.py 里的 CUSTOMER_*_TOOLS 列表字面量。"""
    src = skill_file.read_text(encoding="utf-8")
    m = re.search(r"^CUSTOMER_[A-Z_]+_TOOLS\s*=\s*(\[[^\]]*\])", src, re.M)
    assert m, f"{skill_file.name} 未找到 CUSTOMER_*_TOOLS 定义"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _xiaobu_real_toolset() -> set:
    """从源码解析：小布各 skill 工具并集（单一真值来源）。"""
    tools = set()
    for skill in XIAOBU_SKILLS + [XIAOBU_FALLBACK_SKILL]:
        f = SKILLS_DIR / f"{skill}_skill.py"
        assert f.exists(), f"小布声明的 skill 文件缺失: {f}"
        tools |= _skill_tools(f)
    return tools


def _expected_tools(case: dict) -> set:
    """用例断言引用的工具名（expectations 里的 `- tool: xxx`）。"""
    out = set()
    for exp in case.get("expectations") or []:
        if isinstance(exp, dict) and exp.get("tool"):
            out.add(exp["tool"])
    return out


class TestXiaobuToolsetTruth:
    """C 端工具集真值：runner 内集合必须与 skill 源码一致（防手写漂移）"""

    def test_runner_toolset_matches_skill_source(self):
        from eval_case_filter import XIAOBU_TOOLS
        real = _xiaobu_real_toolset()
        assert set(XIAOBU_TOOLS) == real, (
            f"eval_case_filter.XIAOBU_TOOLS 与 skill 源码不一致\n"
            f"  源码多出: {sorted(real - set(XIAOBU_TOOLS))}\n"
            f"  runner 多出: {sorted(set(XIAOBU_TOOLS) - real)}"
        )

    def test_bmiabo_only_tools_absent_from_xiaobu(self):
        """B 端专属工具不得出现在小布工具集"""
        real = _xiaobu_real_toolset()
        leaked = real & MIBAO_ONLY_TOOLS
        assert not leaked, f"小布工具集混入 B 端专属工具: {sorted(leaked)}"

    def test_xiaobu_and_mibao_toolsets_disjoint_except_shared(self):
        """C 端与 B 端工具集允许的交集仅限共享只读工具"""
        real = _xiaobu_real_toolset()
        # 允许共享：商品查询 + 交互卡 + 校验
        allowed_shared = {"product_search", "product_detail", "interact", "validate_input"}
        overlap = real & MIBAO_ONLY_TOOLS
        assert overlap <= allowed_shared, f"非预期交集: {sorted(overlap - allowed_shared)}"


class TestXiaobuCaseSelection:
    """PERSONA=xiaobu 选中的用例集归属正确性（假绿防线）"""

    def _selected(self):
        from eval_case_filter import select_cases_for_persona
        return select_cases_for_persona(load_case_dicts(str(CASES_DIR)), PERSONA)

    def test_no_bmiabo_only_tool_in_selected_cases(self):
        """选中的 C 端用例断言中不得出现 B 端专属工具（issue #3266 核心）"""
        bad = {}
        for c in self._selected():
            hit = _expected_tools(c) & MIBAO_ONLY_TOOLS
            if hit:
                bad[c["id"]] = sorted(hit)
        assert not bad, (
            f"以下 C 端用例断言引用了 B 端专属工具（小布无此能力，评测结论不可信）: {bad}"
        )

    def test_bmiabo_admin_cases_excluded(self):
        """B 端管理类用例（经营概览/资金/员工/分类/客户/售后工单/设置）必须被排除"""
        sel = {c["id"] for c in self._selected()}
        for cid in ["DA-001", "DA-002", "DA-003", "DA-004", "FN-001",
                    "HR-001", "HR-004", "CT-001", "CU-001", "CU-002",
                    "AS-001", "AS-002", "ST-001", "ST-002", "ST-004"]:
            assert cid not in sel, f"B 端管理用例 {cid} 不应被 C 端用例集选中"

    def test_xiaobu_only_cases_all_selected(self):
        """persona: xiaobu 的用例必须全部被选中（不得漏跑）

        例外：声明了 skip_reason 的（纯前端/纯函数级，非 LLM 行为）不进评测。
        """
        skipped = {c["id"] for c in load_case_dicts(str(CASES_DIR)) if c.get("skip_reason")}
        expected = XIAOBU_ONLY - skipped
        sel = {c["id"] for c in self._selected()}
        assert expected <= sel, f"C 端专属用例漏选: {sorted(expected - sel)}"

    def test_skipped_cases_excluded(self):
        """skip_reason 非空的用例不进 C 端评测（纯前端 jest 用例）"""
        sel = {c["id"] for c in self._selected()}
        for cid in ["CH-030", "CH-031", "CH-032"]:
            assert cid not in sel, f"{cid} 声明了 skip_reason，不应进 C 端评测"

    def test_selection_nonempty(self):
        """C 端用例集不得为空（空集 = 评测静默假绿，issue #3062 同源）"""
        assert len(self._selected()) > 0, "C 端用例集为空 —— 评测将静默假绿"


class TestCrossSessionMemoryCaseContract:
    """跨会话记忆用例契约（issue #3357）——`new_session` 轮 + `post_session` 落库断言。

    背景：C 端长期记忆（user_memories）此前**没有任何可执行断言**，唯一相关用例
    CH-024 以「agent-eval 无稳定记忆数据」被 skip —— 于是「记忆一条都没落库」
    与「用户没表达偏好」在报告里长得一模一样，问题潜伏到 CI DB 审计才被发现。
    本组锁定新协议的数据契约（纯 YAML 校验，不 import local_runner：CI 的
    ci-workflow-helper job 只有 pytest+pyyaml，import runner 会崩）。
    """

    SUPPORTED_FETCH = {"user_memories"}

    def _cases(self):
        return load_case_dicts(str(CASES_DIR))

    def test_memory_case_is_active_and_has_post_session(self):
        """CH-024 必须真跑（不再 skip）且带可执行落库断言。"""
        ch = next(c for c in self._cases() if c.get("id") == "CH-024")
        assert not ch.get("skip_reason"), (
            "CH-024 又变成 skip 了 —— 长期记忆重新回到『零可执行覆盖』（issue #3357）"
        )
        assert ch.get("post_session"), "CH-024 缺 post_session 落库断言（记忆链路不可判定）"

    def test_memory_case_is_selected_for_customer_end(self):
        from eval_case_filter import select_cases_for_persona
        sel = {c["id"] for c in select_cases_for_persona(self._cases(), PERSONA)}
        assert "CH-024" in sel, "CH-024 未被 C 端用例集选中（persona/tier/skip 声明有问题）"

    def test_memory_case_probes_recall_not_restatement(self):
        """跨会话轮不得重述偏好词：否则断言测的是"复读"而不是"记忆"。

        第 1 轮声明偏好（奶油风），第 2 轮换会话后**不再出现**风格词 ——
        回复里出现该词只能来自记忆注入。
        """
        ch = next(c for c in self._cases() if c.get("id") == "CH-024")
        turns = ch.get("user_inputs") or []
        breaks = [i for i, t in enumerate(turns)
                  if isinstance(t, dict) and t.get("new_session")]
        assert breaks, "CH-024 缺 new_session 轮 —— 长期记忆只在新建会话时注入，同会话内看不到"
        recall_turn = turns[breaks[0]]
        for kw in (ch.get("want_text") or []):
            assert kw not in recall_turn.get("text", ""), (
                f"跨会话轮文本里出现了断言关键词「{kw}」—— 断言被自己泄题，测不出记忆注入"
            )

    def test_new_session_turns_have_text(self):
        """new_session 轮必须给 text（空文本会发出一条空消息，属用例书写错误）。"""
        bad = []
        for c in self._cases():
            for i, t in enumerate(c.get("user_inputs") or []):
                if isinstance(t, dict) and t.get("new_session") and not str(t.get("text") or "").strip():
                    bad.append(f"{c.get('id')} 第 {i + 1} 轮")
        assert not bad, f"new_session 轮缺 text: {bad}"

    def test_post_session_only_on_customer_end_cases(self):
        """user_memories 是 C 端专属（mibao 不抽取不落库）→ post_session 只能挂 xiaobu 用例。"""
        bad = [c.get("id") for c in self._cases()
               if c.get("post_session") and (c.get("persona") or "") != "xiaobu"]
        assert not bad, f"非 C 端用例声明了 post_session（B 端不产生记忆，必假失败）: {bad}"

    def test_post_session_fetch_supported(self):
        """fetch 值必须在 runner 支持集内（拼错 = 静默跳过断言 → 假绿）。"""
        bad = []
        for c in self._cases():
            for spec in c.get("post_session") or []:
                if not isinstance(spec, dict) or spec.get("fetch") not in self.SUPPORTED_FETCH:
                    bad.append(f"{c.get('id')}: {spec!r}")
                elif not (spec.get("checks") or []):
                    bad.append(f"{c.get('id')}: {spec!r}（checks 为空 = 无断言）")
        assert not bad, f"post_session 配置不合法（会被 runner 记违规或静默无效）: {bad}"


class TestXiaobuSmokeCoverage:
    """C 端 PR 门禁 smoke 档必须非空（否则 xiaobu-acceptance.yml 静默假绿）"""

    def test_smoke_tier_nonempty(self):
        from eval_case_filter import select_cases_for_persona
        smokes = [c for c in select_cases_for_persona(load_case_dicts(str(CASES_DIR)), PERSONA)
                  if c.get("tier") == "smoke"]
        assert smokes, (
            "C 端 smoke 档为空 —— xiaobu-acceptance.yml 的 local_runner smoke 步骤"
            "将 0 用例执行（_ci_verdict 判失败或需显式标注）"
        )

    def test_smoke_covers_core_customer_capability(self):
        """smoke 档应覆盖小布核心能力（身份/权限隔离类），不只知识问答"""
        from eval_case_filter import select_cases_for_persona
        smokes = {c["id"] for c in select_cases_for_persona(load_case_dicts(str(CASES_DIR)), PERSONA)
                  if c.get("tier") == "smoke"}
        assert len(smokes) >= 3, (
            f"C 端 smoke 档仅 {len(smokes)} 条（{sorted(smokes)}）——"
            "不足以支撑 PR 门禁的 C 端回归信号"
        )


class TestExpectationToolExtraction:
    """expectations → 工具名 的提取语义（防断言串误当工具名）"""

    def test_assertion_strings_not_treated_as_tools(self):
        """`success=true` / `data.orders.length >= 0` / 中文断言 不得被当作工具名"""
        from eval_case_filter import case_expectation_tools as _case_expectation_tools
        fake = {"expectations": ["success=true", "data.orders.length >= 0",
                                 "未被调用", "product_search"]}
        assert _case_expectation_tools(fake) == {"product_search"}

    def test_dict_form_expectations_supported(self):
        """原始 YAML 形态（dict）与归一字符串形态（str）提取结果一致"""
        from eval_case_filter import case_expectation_tools as _case_expectation_tools
        dict_form = {"expectations": [{"tool": "customer_order_query", "args": {"action": "list"}},
                                      {"tool": "interact"}, "success=true"]}
        str_form = {"expectations": ["customer_order_query(action=list)", "interact", "success=true"]}
        assert _case_expectation_tools(dict_form) == {"customer_order_query", "interact"}
        assert _case_expectation_tools(dict_form) == _case_expectation_tools(str_form)

    def test_or_branches_all_extracted(self):
        """`A or B` 的 OR 语义：两个分支的工具都要提取（runner 支持任一满足）"""
        from eval_case_filter import case_expectation_tools as _case_expectation_tools
        got = _case_expectation_tools({"expectations": ["human_handoff or direct_reply"]})
        assert got == {"human_handoff"}, f"direct_reply 是伪期望应剔除，实得 {got}"
        got2 = _case_expectation_tools(
            {"expectations": [{"tool": "after_sales_manage or aftersale_query"}]})
        assert got2 == {"after_sales_manage", "aftersale_query"}, got2

    def test_tool_with_args_forms(self):
        """`tool(args=1)` / `tool: args=1` / 纯 `tool` 三种形态都归一到工具名"""
        from eval_case_filter import case_expectation_tools as _case_expectation_tools
        for exp in ["customer_order_query(action=list)", "customer_order_query: action=list",
                    "customer_order_query"]:
            assert _case_expectation_tools({"expectations": [exp]}) == {"customer_order_query"}

    def test_direct_reply_is_pseudo_tool(self):
        """direct_reply 是 runner 伪期望（无工具+有文本），不算真实工具"""
        from eval_case_filter import case_expectation_tools as _case_expectation_tools
        assert _case_expectation_tools({"expectations": ["direct_reply"]}) == set()



class TestCustomerFacingSemanticGuard:
    """双端用例的语义适配收口（issue #3266 二轮：仅按工具集判定不够）"""

    def _sel_ids(self):
        from eval_case_filter import select_cases_for_persona
        return {c["id"] for c in select_cases_for_persona(load_case_dicts(str(CASES_DIR)), PERSONA)}

    def test_staff_proxy_order_cases_excluded(self):
        """店员代客下单/建品语义用例不得进 C 端（C 端顾客只为本人下单）"""
        sel = self._sel_ids()
        for cid in ["OR-008", "OR-016", "API-013", "UI-003"]:
            assert cid not in sel, f"{cid} 是 B 端/基建用例，不应进 C 端用例集"

    def test_adversarial_tier_preserved(self):
        """对抗档必须全部保留 —— 安全用例输入天然含 B 端语义词，
        但恰恰是 C 端最需要的越权/注入防线（先例 CH-011 跨用户订单拒绝）"""
        sel = self._sel_ids()
        for cid in ["CH-011", "DF-006", "DF-007", "DF-008", "DF-010"]:
            assert cid in sel, f"对抗用例 {cid} 被语义收口误伤"

    def test_customer_end_llm_cases_preserved(self):
        """C 端真实 LLM 用例必须保留（含显式 persona 与双端 C 端语义词）"""
        sel = self._sel_ids()
        for cid in ["AS-008", "KN-001", "KN-002", "KN-008", "OR-012", "PR-001",
                    "PR-003", "CH-008", "CH-010", "CH-012", "CH-015"]:
            assert cid in sel, f"C 端用例 {cid} 漏选"

    def test_filter_is_pure_function_of_case(self):
        """is_customer_facing_case 对同一用例幂等（无隐藏状态）"""
        from eval_case_filter import is_customer_facing_case
        cases = load_case_dicts(str(CASES_DIR))
        for c in cases[:40]:
            assert is_customer_facing_case(c) == is_customer_facing_case(c)


class TestXiaobuLoginShortCircuit:
    """PERSONA=xiaobu 时 login() 必须跳过 SMS 登录（issue #3270 死代码回归）。

    背景：502 重试重构把 `return await _retry_502(...)` 提到 xiaobu/SERVICE_TOKEN
    短路**之前**，使两个分支变成死代码 —— xiaobu 模式仍发真实 SMS 登录，
    本地/CI 栈无用户时 401「该手机号未注册」→ 评测 100% 失败。
    """

    def test_login_shortcircuits_before_retry_call(self):
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        i_xiaobu = src.find('if PERSONA == "xiaobu":')
        i_retry = src.find('return await _retry_502("登录", _do_login)')
        assert i_xiaobu != -1 and i_retry != -1
        assert i_xiaobu < i_retry, (
            "PERSONA=xiaobu 短路必须在 _retry_502 之前 —— "
            "否则 xiaobu 模式仍发 SMS 登录（本地栈 401 全失败）"
        )

    def test_login_returns_empty_before_sms_call(self):
        """xiaobu 短路必须返回空串，且不得发起 SMS 登录调用（源码级：`return ""` 在
        sms/login 之前，且 _retry_502 在其后 —— 不 import local_runner，避免
        Python 3.9 对 `X | None` 语法的兼容问题）"""
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        i_short = src.find('if PERSONA == "xiaobu":\n        return ""')
        i_call = src.find('return await _retry_502("登录", _do_login)')
        assert i_short != -1, "xiaobu 短路 `return ""` 不存在"
        assert i_call != -1, "_retry_502 调用不存在（结构变更需同步本测试）"
        # _do_login 里含 sms/login 字符串但那是**定义**；真正发起登录的是
        # _retry_502 的**调用**。短路必须在该调用之前。
        assert i_short < i_call, (
            "xiaobu 短路必须在 _retry_502 调用之前 —— 否则 xiaobu/CI 模式仍发真实"
            "SMS 登录（本地栈 401「该手机号未注册」评测全失败，issue #3270 实证）"
        )


class TestStaffProxyOrderSemantics:
    """B 端「店员代客下单」语义用例不得进 C 端（issue #3270 归因修复）。

    背景：C 端 normal 档首次基线 10/23，11 个失败里 **5 个是归属错误** ——
    OR-009/010/011/015/CR-001 的首轮都是**店员代客下单**语义
    （「我要给张三下单」「创建订单：张三 …」），小布（C 端自助、身份固定为本人）
    无法触发 → `order_create` 从未被调用 → 必然 0 分，污染基线。

    实测（CI，normal 档）：
      OR-009 `tools=[]`；OR-010/011/015 均无 `order_create`；CR-001 无 `order_create`
    """

    STAFF_PROXY = ["OR-008", "OR-009", "OR-010", "OR-011", "OR-015", "CR-001"]
    # 合法 C 端自助下单/选购用例必须在（防语义过滤误伤）
    LEGIT_CUSTOMER = ["OR-014", "OR-017", "CH-010", "OR-012", "AS-008"]

    def _sel(self):
        from eval_case_filter import select_cases_for_persona
        return {c["id"] for c in select_cases_for_persona(load_case_dicts(str(CASES_DIR)), PERSONA)}

    def test_staff_proxy_cases_excluded_from_customer_end(self):
        sel = self._sel()
        leaked = [c for c in self.STAFF_PROXY if c in sel]
        assert not leaked, (
            f"店员代客下单语义用例仍在 C 端用例集：{leaked} —— "
            "小布无法触发，必然 0 分污染基线"
        )

    def test_legit_customer_cases_preserved(self):
        sel = self._sel()
        missing = [c for c in self.LEGIT_CUSTOMER if c not in sel]
        assert not missing, f"合法 C 端用例被语义过滤误伤：{missing}"

    def test_first_person_phrase_not_overfiltered(self):
        """「帮我下单」是合法 C 端说法，不得因负向前瞻失效而误伤"""
        from eval_case_filter import is_customer_facing_case
        for text in ["帮我下单", "我要下单", "给我自己下单", "帮我查一下物流"]:
            case = {"user_inputs": [text], "expectations": []}
            assert is_customer_facing_case(case), f"「{text}」是合法 C 端说法，不应被过滤"

    def test_proxy_phrase_detected(self):
        from eval_case_filter import is_customer_facing_case
        for text in ["我要给张三下单，手机13800138000",
                     "创建订单：张三 13812345678",
                     "用遮光窗帘给张三创建订单，2件",
                     "帮我下个订单，客户张三，手机13800138000"]:
            case = {"user_inputs": [text], "expectations": []}
            assert not is_customer_facing_case(case), f"「{text}」是代客语义，应被过滤"


class TestCaseInputsAreUtterances:
    """C 端用例的 user_inputs 必须是**顾客会说的话**，不能是断言描述（issue #3270）。

    背景：CH-008 / CH-017 的 user_inputs 原本是**测试描述文字**：
      - CH-008 R1: "用户触发转人工后应创建 agent_session（waiting）并写入系统消息"
      - CH-017 R1: "用户与 AI 聊过 3 轮（含查单/商品咨询）后触发转人工，human_handoff 应携带…"
    agent 收到这种输入无法响应 → 从不调用 `human_handoff` → **必然 0 分**
    （CI normal 档实测：两条均 ❌）。这是「断言层」缺陷 —— 用例写错了，不是 agent 不行。

    ST-008 同款（输入是配置描述、断言是纯函数级）→ 已标 skip_reason。

    本测试作为**用例质量门禁**：可跑的 C 端用例，首轮输入不得是描述性文字。
    """

    # 描述性输入信号：以第三方/系统视角起手，或含「应…」断言式描述、API 路径
    _DESC = re.compile(
        r"^(用户|顾客|商家|客户|平台|系统|AI|C 端|B 端|米宝)"
        r"|应(创建|返回|携带|能|有|使用|触发)"
        r"|→|\bPOST /|\bGET /"
    )
    # 正当例外：攻击载荷（注入/越权用例的输入本身就是 payload）
    _ALLOW = {"DF-010"}

    def _sel(self):
        from eval_case_filter import select_cases_for_persona
        return select_cases_for_persona(load_case_dicts(str(CASES_DIR)), PERSONA)

    def test_no_descriptive_inputs_in_runnable_cases(self):
        bad = []
        for c in self._sel():
            if c["id"] in self._ALLOW:
                continue
            for u in (c.get("user_inputs") or []):
                if isinstance(u, str) and self._DESC.search(u):
                    bad.append((c["id"], u[:56]))
                    break
        assert not bad, (
            "以下可跑用例的首轮输入是**描述性文字**（agent 无法响应 → 必然 0 分）：\n  "
            + "\n  ".join(f"{cid}: {t}" for cid, t in bad)
            + "\n应改写为顾客会说的话，或标 skip_reason 并说明由单测覆盖。"
        )

    def test_ch008_and_ch017_use_real_dialogue(self):
        by = {c["id"]: c for c in load_case_dicts(str(CASES_DIR))}
        for cid in ("CH-008", "CH-017"):
            inputs = by[cid]["user_inputs"]
            assert all(isinstance(u, str) and not self._DESC.search(u) for u in inputs), (
                f"{cid} 仍含描述性输入: {inputs}"
            )
            # 转人工用例的最后一轮应为显式转人工请求
            assert any("转人工" in u for u in inputs), f"{cid} 末轮应触发转人工"

    def test_st008_skipped_with_reason(self):
        by = {c["id"]: c for c in load_case_dicts(str(CASES_DIR))}
        assert by["ST-008"].get("skip_reason"), (
            "ST-008 的断言是纯函数级（is_auto_handoff_trigger），agent-eval 无法设置 config —— "
            "必须标 skip_reason 说明由单测覆盖"
        )


class TestWriteCaseInputsAreComplete:
    """断言了「需验证码写工具」的用例，必须给出验证码那一轮（否则流程走不完）

    先例（run 34622425044，OR-014 / OR-017 / CH-010）：三条用例都断言 `order_create`，
    但 `user_inputs` 只到「确认」为止。而 C 端下单在代码里是**两步**：

        order_create 的 `sms_code` 对 customer 角色**必填**（tools/order_create.py：
        `_verify_sms_code`，dev/CI 栈由 SMS_BYPASS_CODE 提供万能码）
        → AI 正确地在确认后引导「请输入收到的短信验证码」
        → 用例不给码 → 流程**停在第 5 步**，order_create 永不发生
        → 报告显示「agent 不会下单」（实测 OR-014 R7 `tools=-`）

    这是「用例走不完真实流程」而不是「agent 能力不足」—— 与 fixture 缺数据同族。
    本测试把「断言了写工具 → 输入必须喂到该工具真的能被调用」变成可执行约束。
    """

    # 需要用户提供验证码的写工具（参数表里带 sms_code）
    OTP_TOOLS = {"order_create"}
    CODE_RE = re.compile(r"^\d{4,6}$")

    def _xiaobu_cases(self) -> list:
        cases = load_case_dicts(CASES_DIR)
        # 直接复用生产过滤口径，避免测试自造口径
        from eval_case_filter import select_cases_for_persona
        return select_cases_for_persona(cases, PERSONA)

    def test_parse_is_non_trivial(self):
        cases = self._xiaobu_cases()
        assert len(cases) >= 20, f"仅解析出 {len(cases)} 条 C 端用例 —— 过滤疑似失效"

    @classmethod
    def _texts_carried_by(cls, msg) -> list:
        """一轮输入里**所有可能被当作用户文本发出**的字符串。

        除了纯文本轮，还包括两类结构化轮：
        - `auto_respond.fallback`（无卡时发出的兜底文本）
        - `auto_respond.form_values` / `auto_fill` 的值（表单回填内容）
        只扫纯文本会漏判 —— 把验证码放进 auto_respond 兜底是完全等价的供码方式。
        """
        if isinstance(msg, str):
            return [msg]
        if not isinstance(msg, dict):
            return [str(msg)]
        out = []
        for key in ("auto_respond", "auto_fill"):
            block = msg.get(key)
            if isinstance(block, dict):
                if block.get("fallback") is not None:
                    out.append(str(block["fallback"]))
                for v in (block.get("form_values") or {}).values():
                    out.append(str(v))
                if key == "auto_fill":
                    for v in block.values():
                        out.append(str(v))
        for k, v in msg.items():
            if k not in ("auto_respond", "auto_fill") and isinstance(v, str):
                out.append(v)
        return out

    def test_cases_asserting_otp_tools_supply_a_code(self):
        offenders = []
        checked = 0
        for case in self._xiaobu_cases():
            expectations = case.get("expectations") or []
            used = {e.get("tool") for e in expectations if isinstance(e, dict)}
            if not (used & self.OTP_TOOLS):
                continue
            checked += 1
            provided = any(
                self.CODE_RE.match(t)
                for u in (case.get("user_inputs") or [])
                for t in self._texts_carried_by(u)
            )
            if not provided:
                offenders.append(case.get("id"))
        assert checked >= 3, f"仅 {checked} 条用例断言了需验证码的写工具 —— 解析疑似失效"
        assert not offenders, (
            "以下 C 端用例断言了需验证码的写工具（order_create），但 user_inputs 没有"
            "验证码那一轮 —— AI 会正确停在「请输入验证码」，该断言永远不可能满足：\n  "
            + "\n  ".join(offenders)
            + "\n修复：在 user_inputs 末尾补一轮验证码（dev/CI 栈 SMS_BYPASS_CODE=123456）。"
        )

    def test_sms_bypass_is_wired_in_dev_stack(self):
        """dev/CI 栈必须注入万能验证码，否则用例喂了码也过不了校验"""
        compose = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
        assert "SMS_BYPASS_CODE" in compose, (
            "dev compose 未注入 SMS_BYPASS_CODE —— order_create 的 customer 校验无法通过"
        )
