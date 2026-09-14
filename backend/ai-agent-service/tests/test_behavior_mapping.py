# case_ids: OR-016, AS-007, PR-019, PR-020, CH-010
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
    ])
    def test_rule_hit(self, path, expected):
        assert bm.map_changed_files_to_case_ids([path]) == expected

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
