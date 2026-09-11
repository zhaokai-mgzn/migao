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
# case_ids: CH-008, CH-010, CH-012, CH-013, CH-014, CH-015, CH-017, OR-012, ST-008, KN-001, KN-002, KN-008
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
    "OR-012", "ST-008", "KN-001", "KN-002", "KN-008",
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
        from local_runner import XIAOBU_TOOLS
        real = _xiaobu_real_toolset()
        assert set(XIAOBU_TOOLS) == real, (
            f"local_runner.XIAOBU_TOOLS 与 skill 源码不一致\n"
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
        from local_runner import select_cases_for_persona
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
        """persona: xiaobu 的用例必须全部被选中（不得漏跑）"""
        sel = {c["id"] for c in self._selected()}
        assert XIAOBU_ONLY <= sel, f"C 端专属用例漏选: {sorted(XIAOBU_ONLY - sel)}"

    def test_skipped_cases_excluded(self):
        """skip_reason 非空的用例不进 C 端评测（纯前端 jest 用例）"""
        sel = {c["id"] for c in self._selected()}
        for cid in ["CH-030", "CH-031", "CH-032"]:
            assert cid not in sel, f"{cid} 声明了 skip_reason，不应进 C 端评测"

    def test_selection_nonempty(self):
        """C 端用例集不得为空（空集 = 评测静默假绿，issue #3062 同源）"""
        assert len(self._selected()) > 0, "C 端用例集为空 —— 评测将静默假绿"


class TestXiaobuSmokeCoverage:
    """C 端 PR 门禁 smoke 档必须非空（否则 xiaobu-acceptance.yml 静默假绿）"""

    def test_smoke_tier_nonempty(self):
        from local_runner import select_cases_for_persona
        smokes = [c for c in select_cases_for_persona(load_case_dicts(str(CASES_DIR)), PERSONA)
                  if c.get("tier") == "smoke"]
        assert smokes, (
            "C 端 smoke 档为空 —— xiaobu-acceptance.yml 的 local_runner smoke 步骤"
            "将 0 用例执行（_ci_verdict 判失败或需显式标注）"
        )

    def test_smoke_covers_core_customer_capability(self):
        """smoke 档应覆盖小布核心能力（身份/权限隔离类），不只知识问答"""
        from local_runner import select_cases_for_persona
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
        from local_runner import _case_expectation_tools
        fake = {"expectations": ["success=true", "data.orders.length >= 0",
                                 "未被调用", "product_search"]}
        assert _case_expectation_tools(fake) == {"product_search"}

    def test_dict_form_expectations_supported(self):
        """原始 YAML 形态（dict）与归一字符串形态（str）提取结果一致"""
        from local_runner import _case_expectation_tools
        dict_form = {"expectations": [{"tool": "customer_order_query", "args": {"action": "list"}},
                                      {"tool": "interact"}, "success=true"]}
        str_form = {"expectations": ["customer_order_query(action=list)", "interact", "success=true"]}
        assert _case_expectation_tools(dict_form) == {"customer_order_query", "interact"}
        assert _case_expectation_tools(dict_form) == _case_expectation_tools(str_form)

    def test_or_branches_all_extracted(self):
        """`A or B` 的 OR 语义：两个分支的工具都要提取（runner 支持任一满足）"""
        from local_runner import _case_expectation_tools
        got = _case_expectation_tools({"expectations": ["human_handoff or direct_reply"]})
        assert got == {"human_handoff"}, f"direct_reply 是伪期望应剔除，实得 {got}"
        got2 = _case_expectation_tools(
            {"expectations": [{"tool": "after_sales_manage or aftersale_query"}]})
        assert got2 == {"after_sales_manage", "aftersale_query"}, got2

    def test_tool_with_args_forms(self):
        """`tool(args=1)` / `tool: args=1` / 纯 `tool` 三种形态都归一到工具名"""
        from local_runner import _case_expectation_tools
        for exp in ["customer_order_query(action=list)", "customer_order_query: action=list",
                    "customer_order_query"]:
            assert _case_expectation_tools({"expectations": [exp]}) == {"customer_order_query"}

    def test_direct_reply_is_pseudo_tool(self):
        """direct_reply 是 runner 伪期望（无工具+有文本），不算真实工具"""
        from local_runner import _case_expectation_tools
        assert _case_expectation_tools({"expectations": ["direct_reply"]}) == set()

