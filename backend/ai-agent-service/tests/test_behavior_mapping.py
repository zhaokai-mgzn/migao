# case_ids: OR-016, AS-007, PR-019, PR-020, CH-010, CU-003, CU-004
"""行为改动 diff → 用例映射单测（tests/agent_eval/behavior_mapping.py，issue #3502）。

被测契约（详见模块 docstring）：
  · MAPPING_RULES 每条规则都要能把 §13.2 的改动类型映射到该跑的用例；
  · 命中多条规则 → 并集去重（同一文件可能是 agent prompt 又是订单 skill）；
  · 有 AI 行为文件但无规则命中 → DEFAULT_BEHAVIOR_CASES（不静默跳过）；
  · 无 AI 行为文件 / 空输入 → []（非行为改动不触发真实 LLM 评测）；
  · 输出稳定排序（同一 diff 在任何机器/任何次数下结果一致，PR 评论才可比对）。

为什么单独立测（而不是只靠 workflow 跑通）：映射错了不会崩 —— 只会"少跑几条用例"，
这正是本 issue 要消灭的那类静默失效（§16.1：能由 L0 静态层拦的缺陷不许流到真实 LLM）。
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "tests" / "agent_eval" / "behavior_mapping.py"
EVAL_CASES_PATH = REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bm = _load(MODULE_PATH, "migao_behavior_mapping")
# 用例库渲染产物（`render_cases.py` 单一源）：用来锁「映射引用的 case ID 真实存在」
_eval_cases = _load(EVAL_CASES_PATH, "migao_eval_cases_for_mapping")

# 各规则的「代表性改动文件」（取仓内真实路径，含 §13.2 列出的承载文件）
ORDER_PATH = "backend/ai-agent-service/app/graph/skills/order_skill.py"
AFTERSALES_PATH = "backend/ai-agent-service/app/graph/skills/aftersales_skill.py"
PRODUCT_PATH = "backend/ai-agent-service/app/graph/skills/product_skill.py"
CARD_PATH = "backend/ai-agent-service/app/graph/interact.py"
VISION_PATH = "backend/ai-agent-service/app/utils/vision_analyzer.py"
GUARD_PATH = "backend/ai-agent-service/app/tools/guard.py"
AGENT_PATH = "backend/ai-agent-service/app/agents/mibao.py"
CUSTOMER_PATH = "backend/ai-agent-service/app/tools/customer_manage.py"
CUSTOMER_SKILL_PATH = "backend/ai-agent-service/app/graph/skills/customer_skill.py"
FINANCE_PATH = "backend/ai-agent-service/app/tools/finance_api.py"

# 真实承载防御/熔断逻辑的源码（#3551 全表复核时实测：只有这些是仓内真实存在的载体）
REAL_DEFENSE_PATHS = [
    "backend/ai-agent-service/app/graph/clarify_guard.py",
    "backend/ai-agent-service/app/core/circuit_breaker.py",
    "backend/ai-agent-service/app/core/fallback.py",
    "backend/ai-agent-service/app/graph/skills/base_skill.py",
]


class TestRuleHits:
    """每条映射规则都要命中（规则表 = §13.2 的可执行形态，漏一条就漏一类改动）"""

    @pytest.mark.parametrize("path, expected", [
        (ORDER_PATH, ["OR-016"]),
        ("backend/ai-agent-service/app/tools/order_create.py", ["OR-016"]),
        ("backend/ai-agent-service/app/tools/order_query.py", ["OR-016"]),
        (AFTERSALES_PATH, ["AS-007"]),
        (PRODUCT_PATH, ["PR-019", "PR-020"]),
        (CARD_PATH, ["CH-010", "CH-019"]),
        (VISION_PATH, ["CH-021", "CH-026"]),
        (GUARD_PATH, ["DF-011", "DF-012"]),
        (AGENT_PATH, ["CH-003", "CH-022"]),
        # #3551 补客户域规则：改客户档案 Tool / 客户域 Skill → CU-003（标签）、CU-004（更新资料）
        (CUSTOMER_PATH, ["CU-003", "CU-004"]),
        (CUSTOMER_SKILL_PATH, ["CU-003", "CU-004"]),
    ])
    def test_rule_hit(self, path, expected):
        assert bm.map_changed_files_to_case_ids([path]) == expected

    def test_customer_manage_maps_to_customer_domain_cases(self):
        """改 `customer_manage.py` 必须映射出 CU-004（#3551 旁路发现）。

        修前：映射表无客户域规则 → 改客户档案写路径**不映射任何用例**（只有 prompt 关键词
        顺带把 prompts/customer.md 映射到 CH-003/CH-022，`customer_manage.py` 本体落兜底网）
        → 客户域行为改动逃过映射门禁。CU-004「更新客户资料（部分更新）」正是本次
        「姓名静默丢弃」的承载用例；CU-003（给客户打标签）同属该工具写路径。
        """
        cases = bm.map_changed_files_to_case_ids([CUSTOMER_PATH])
        assert "CU-004" in cases
        assert cases == ["CU-003", "CU-004"]

    def test_defense_rule_covers_injection_keyword(self):
        """防御规则的三种写法（guard/defense/injection）都要能触发 —— 漏一种就等于漏测。"""
        for path in ("backend/ai-agent-service/app/utils/defense_layer.py",
                     "backend/ai-agent-service/app/utils/injection_detector.py"):
            assert bm.map_changed_files_to_case_ids([path]) == ["DF-011", "DF-012"]

    def test_prompt_path_triggers_agent_rule(self):
        """prompt 单独成关键词：prompt 目录下的改动不经过 app/agents/ 也要跑 CH-003/CH-022。"""
        assert bm.map_changed_files_to_case_ids(
            ["backend/ai-agent-service/app/prompts/order_prompt.txt"]) == ["CH-003", "CH-022"]


class TestUnionAndDedupe:
    """多规则合并（并集）+ 去重"""

    def test_multi_rule_union(self):
        """一个文件同时命中 agent 规则与订单规则 → 两组用例都要跑（并集，不取第一个命中）。"""
        result = bm.map_changed_files_to_case_ids([AGENT_PATH, ORDER_PATH])
        assert result == ["CH-003", "CH-022", "OR-016"]

    def test_multi_file_across_rules_dedupes(self):
        """多个文件命中同一规则 → 用例 ID 只出现一次（去重）。"""
        result = bm.map_changed_files_to_case_ids([CARD_PATH, "backend/ai-agent-service/app/ui/card_view.py"])
        assert result == ["CH-010", "CH-019"]

    def test_same_path_twice_is_idempotent(self):
        assert bm.map_changed_files_to_case_ids([VISION_PATH, VISION_PATH]) == ["CH-021", "CH-026"]


class TestDefaultAndEmpty:
    """默认集与空集（"不静默跳过"与"非行为改动不烧 token"两条相反方向的防线）"""

    def test_ai_file_without_rule_hit_falls_back_to_default(self):
        """AI 行为文件改了但映射表没覆盖 → 默认集，不能返回空（空 = 把漏测伪装成无需测试）。"""
        assert bm.map_changed_files_to_case_ids(
            ["backend/ai-agent-service/app/main.py"]) == bm.DEFAULT_BEHAVIOR_CASES

    def test_eval_and_cases_dirs_are_ai_behavior_files(self):
        """评测基建与用例库本身也在行为域内（改了评测口径必须复验）。"""
        for path in ("tests/agent_eval/local_runner.py", ".github/cases/order.yml"):
            assert bm.map_changed_files_to_case_ids([path]) == bm.DEFAULT_BEHAVIOR_CASES

    def test_no_ai_behavior_file_returns_empty(self):
        assert bm.map_changed_files_to_case_ids(
            ["frontend/admin-web/src/app/page.tsx", "docs/wiki/Development.md"]) == []

    def test_empty_and_blank_input_returns_empty(self):
        assert bm.map_changed_files_to_case_ids([]) == []
        assert bm.map_changed_files_to_case_ids(["", "   ", "\n"]) == []

    def test_default_cases_are_not_empty(self):
        """默认集必须非空（若被改成 []，上面的兜底就变成了静默跳过）。"""
        assert len(bm.DEFAULT_BEHAVIOR_CASES) >= 1


class TestOrderingStability:
    """稳定排序：同一 diff 的结果必须可复现（PR 评论/输出比对依赖它）"""

    def test_output_is_sorted_and_input_order_independent(self):
        forward = bm.map_changed_files_to_case_ids([ORDER_PATH, CARD_PATH, AGENT_PATH])
        backward = bm.map_changed_files_to_case_ids([AGENT_PATH, CARD_PATH, ORDER_PATH])
        assert forward == backward
        assert forward == sorted(forward)
        assert forward == ["CH-003", "CH-010", "CH-019", "CH-022", "OR-016"]

    def test_rule_declaration_order_does_not_leak_into_output(self):
        """结果按用例 ID 字典序（不是 MAPPING_RULES 的声明序）——写死期望值锁住口径。"""
        result = bm.map_changed_files_to_case_ids([GUARD_PATH, PRODUCT_PATH])
        assert result == ["DF-011", "DF-012", "PR-019", "PR-020"]


class TestMappingSource:
    """结果来源分类（门禁分层：规则命中阻塞 / 兜底网只报告，issue #3502）

    背景（2026-09-14 dogfooding 首跑实证）：只改 `tests/agent_eval/behavior_mapping.py`
    （评测基建）会被兜底网里的 CH-010（小布下单）判红 —— 与本 PR 改动**无因果**。
    故 workflow 需要知道"这批用例是规则命中还是兜底网"，二者门禁强度不同。
    """

    def test_rule_hit_reports_rules_source(self):
        assert bm.map_changed_files_with_source([ORDER_PATH]) == (["OR-016"], "rules")

    def test_default_net_reports_default_source(self):
        cases, source = bm.map_changed_files_with_source(
            ["backend/ai-agent-service/app/main.py"])
        assert source == "default_net"
        assert cases == bm.DEFAULT_BEHAVIOR_CASES

    def test_no_ai_behavior_file_reports_none_source(self):
        assert bm.map_changed_files_with_source(["frontend/admin-web/src/app/page.tsx"]) == ([], "none")
        assert bm.map_changed_files_with_source([]) == ([], "none")

    def test_rule_hit_beats_default_net(self):
        """既改了无规则命中的 AI 文件、又命中规则 → 来源必须是 rules（不能退化成兜底网，
        否则真信号会被降级成"只报告"）。"""
        cases, source = bm.map_changed_files_with_source(
            ["backend/ai-agent-service/app/main.py", ORDER_PATH])
        assert source == "rules"
        assert cases == ["OR-016"]

    def test_source_api_and_plain_api_agree(self):
        """两个入口的用例集必须完全一致（单一实现，防两套口径漂移）。"""
        for paths in ([ORDER_PATH], ["backend/ai-agent-service/app/main.py"],
                      ["frontend/admin-web/src/app/page.tsx"], []):
            assert bm.map_changed_files_with_source(paths)[0] == bm.map_changed_files_to_case_ids(paths)


class TestRulesAnchorToSourcePaths:
    """规则只锚定 agent 本体源码（#3551 追加：假阻塞红）

    背景（另一 worker 实证）：规则此前对**所有** diff 路径匹配，于是新建的守卫测试文件
    `test_admin_api_client_kwargs_guard.py`（文件名含 `guard`）让"改 finance 工具"的 PR
    被判成命中防御规则 → DF-011/DF-012 以**阻塞**强度跑，而它与本 PR 改动**无因果**：
    假阻塞红 → 每次都要人/agent 花时间证伪，还会诱使去修不该修的东西。
    §16.5 的规则桶阻塞设计前提就是「规则命中 = 改动真的影响行为」，故必须双向钉住。
    """

    # ── 反方向 1：用例/测试/文档路径永不允许进规则桶（阻塞）──
    @pytest.mark.parametrize("path", [
        # 实证的误触源：测试文件名含 guard（防御规则关键词）
        "backend/ai-agent-service/tests/test_admin_api_client_kwargs_guard.py",
        # 其余典型测试/用例/文档路径（含 defense 关键词、纯 test_ 前缀）
        "backend/ai-agent-service/tests/test_defense_layer.py",
        "backend/ai-agent-service/tests/test_tools_finance_api.py",
        "backend/ai-agent-service/tests/test_order_card_render.py",
        "tests/agent_eval/behavior_mapping.py",
        ".github/cases/defense.yml",
        "docs/testing/mibao-verification-cases.md",
    ])
    def test_test_and_case_paths_never_hit_rule_bucket(self, path):
        """测试/用例/文档路径 + 一个本体源码文件同 diff → 必须落兜底网（不阻塞）。"""
        cases, source = bm.map_changed_files_with_source([FINANCE_PATH, path])
        assert source == "default_net", (
            f"{path} 误命中规则桶（source={source}, cases={cases}）→ 与改动无因果的假阻塞红"
        )
        assert cases == bm.DEFAULT_BEHAVIOR_CASES

    def test_guard_named_test_file_does_not_trigger_defense_rule(self):
        """回归（#3551 实证复现）：改 finance 工具 + 新增 `*_guard.py` 测试 → 不得阻塞 DF-011/DF-012。"""
        cases, source = bm.map_changed_files_with_source([
            FINANCE_PATH,
            "backend/ai-agent-service/tests/test_tools_finance_api.py",
            "backend/ai-agent-service/tests/test_admin_api_client_kwargs_guard.py",
        ])
        assert source == "default_net"
        assert cases == bm.DEFAULT_BEHAVIOR_CASES

    def test_rule_scope_is_subset_of_behavior_domain(self):
        """规则作用域必须是行为域的子集（防止有人把非行为路径加进作用域）。"""
        assert all(
            p.startswith(bm.AI_BEHAVIOR_PATH_PREFIXES) for p in bm.BEHAVIOR_SOURCE_PREFIXES
        )
        assert "tests/" not in "".join(bm.BEHAVIOR_SOURCE_PREFIXES)

    # ── 反方向 2：真实防御源码仍必须命中规则桶（防收窄成"永不命中" = 门禁静默失效）──
    @pytest.mark.parametrize("path", REAL_DEFENSE_PATHS)
    def test_real_defense_sources_still_hit_rule_bucket(self, path):
        assert bm.map_changed_files_with_source([path]) == (["DF-011", "DF-012"], "rules")

    def test_real_defense_sources_exist(self):
        """上面那组"真实载体"必须真的存在于仓内（防又变成凭空的文件名）。"""
        for path in REAL_DEFENSE_PATHS:
            assert (REPO_ROOT / path).is_file(), f"防御载体不存在：{path}"

    def test_customer_prompt_change_maps_to_customer_cases(self):
        """客户域引导词改动 → CU-003/CU-004（与 prompt 规则 CH-003/CH-022 取并集）。

        `prompts/customer.md` 直接规定"更新客户资料"下发的字段名 —— 改它必须真跑客户域用例。
        """
        cases, source = bm.map_changed_files_with_source(
            ["backend/ai-agent-service/app/graph/skills/references/prompts/customer.md"])
        assert source == "rules"
        assert cases == ["CH-003", "CH-022", "CU-003", "CU-004"]


class TestCaseIdsExistInCaseLibrary:
    """L0 不变式：映射引用的每个用例 ID 都必须真实存在于用例库（§16.1 静态层）"""

    def _existing_ids(self):
        return {c.id for c in _eval_cases.ALL_CASES}

    def test_mapping_rule_ids_exist(self):
        existing = self._existing_ids()
        missing = [cid for _, ids in bm.MAPPING_RULES for cid in ids if cid not in existing]
        assert missing == [], f"映射表引用了不存在的用例 ID: {missing}"

    def test_default_case_ids_exist(self):
        existing = self._existing_ids()
        missing = [cid for cid in bm.DEFAULT_BEHAVIOR_CASES if cid not in existing]
        assert missing == [], f"默认集引用了不存在的用例 ID: {missing}"
