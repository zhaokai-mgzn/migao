# case_ids: OR-016, OR-028, AS-007, PR-019, CH-010, CU-003, CU-004, HR-001, HR-005, ST-003, ST-005, DA-004, FN-001, PP-002, PP-006, PG-017, CH-013, CH-014, CH-015, CH-008
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
# #3624 补齐的三类承载文件（此前全部落兜底网 = 一条本域用例都不跑）
STAFF_PATH = "backend/ai-agent-service/app/graph/skills/staff_skill.py"
SETTINGS_PATH = "backend/ai-agent-service/app/graph/skills/settings_skill.py"
DATA_PATH = "backend/ai-agent-service/app/graph/skills/data_skill.py"
# 加工项目录（PP-* 域）：processing_item_manage=写 / processing_item_query=查目录
PROCESSING_ITEM_MANAGE_PATH = "backend/ai-agent-service/app/tools/processing_item_manage.py"
PROCESSING_ITEM_QUERY_PATH = "backend/ai-agent-service/app/tools/processing_item_query.py"
# 商品侧加工项挂载 Tool（与目录 CRUD 是两件事，仍归商品域）
PRODUCT_PROCESSING_ITEM_PATH = "backend/ai-agent-service/app/tools/product_processing_item_manage.py"
# 加工单概念区分（PG-* 域）：prompts/order.md 与 order_skill.py 是概念区分口径的承载文件
# （#3917：agent 暂不接入加工单工具；PG-013/015/016 已 skip，工具实现文件不再映射）
ORDER_PROMPT_PATH = "backend/ai-agent-service/app/graph/skills/references/prompts/order.md"
PROCESSING_ORDER_GENERATE_PATH = "backend/ai-agent-service/app/tools/processing_order_generate.py"
# 加工单三工具实现文件（类保留但未注册，#3917）：改动落兜底网（default_net），不再锚用例
PROCESSING_ORDER_QUERY_PATH = "backend/ai-agent-service/app/tools/processing_order_query.py"
PROCESSING_ORDER_UPDATE_PATH = "backend/ai-agent-service/app/tools/processing_order_update.py"
# 路由层（#3921）：rule_matcher.py（加工单/JG-xxx → 订单域规则）与 nodes.py
# （会话连续性关键词）是概念区分的承载 —— 改路由不改 prompt 时「加工单被归到商品域
# 当加工项查」的缺陷就复现（PG-017 首跑 0 分实证），必须映射 PG-017。
RULE_MATCHER_PATH = "backend/ai-agent-service/app/router/rule_matcher.py"
ROUTING_NODES_PATH = "backend/ai-agent-service/app/graph/nodes.py"
# 守卫代码的共享载体（防御/熔断 + 写操作守卫 + 转人工建议卡守卫），见 TestBaseSkillRules
BASE_SKILL_PATH = "backend/ai-agent-service/app/graph/skills/base_skill.py"
# 转人工 Tool 本体（创建人工会话/工单/通知），见 TestHumanHandoffRules
HUMAN_HANDOFF_PATH = "backend/ai-agent-service/app/tools/human_handoff.py"

# 真实承载防御/熔断逻辑的源码（#3551 全表复核时实测：只有这些是仓内真实存在的载体）
# 注：`base_skill.py` 也是防御载体之一，但它同时承载写操作/转人工守卫（#3624 追加规则），
# 期望集不再是纯 DF-*，故单列到 TestBaseSkillRules 里断言全集。
REAL_DEFENSE_PATHS = [
    "backend/ai-agent-service/app/graph/clarify_guard.py",
    "backend/ai-agent-service/app/core/circuit_breaker.py",
    "backend/ai-agent-service/app/core/fallback.py",
]


class TestRuleHits:
    """每条映射规则都要命中（规则表 = §13.2 的可执行形态，漏一条就漏一类改动）"""

    @pytest.mark.parametrize("path, expected", [
        # order_skill.py 同时命中「下单引导」规则（OR-016/OR-028）与「加工单概念区分」规则
        # （PG-017，#3917）→ 并集 + 字典序
        (ORDER_PATH, ["OR-016", "OR-028", "PG-017"]),
        ("backend/ai-agent-service/app/tools/order_create.py", ["OR-016", "OR-028"]),
        ("backend/ai-agent-service/app/tools/order_query.py", ["OR-016", "OR-028"]),
        (AFTERSALES_PATH, ["AS-007"]),
        (PRODUCT_PATH, ["PR-019"]),
        (CARD_PATH, ["CH-010", "CH-019"]),
        (VISION_PATH, ["CH-021", "CH-026"]),
        (GUARD_PATH, ["DF-011", "DF-012"]),
        (AGENT_PATH, ["CH-003", "CH-022"]),
        # #3551 补客户域规则：改客户档案 Tool / 客户域 Skill → CU-003（标签）、CU-004（更新资料）
        (CUSTOMER_PATH, ["CU-003", "CU-004"]),
        (CUSTOMER_SKILL_PATH, ["CU-003", "CU-004"]),
        # #3624 补 staff/settings/data 三个 skill（此前全部落兜底网）
        (STAFF_PATH, ["HR-001", "HR-005"]),
        (SETTINGS_PATH, ["ST-003", "ST-005"]),
        (DATA_PATH, ["DA-004", "FN-001"]),
        # #3624 补加工项目录域（此前被商品规则的 `processing_item` 关键词吞掉 → 映射成建品价格用例）
        (PROCESSING_ITEM_MANAGE_PATH, ["PP-002", "PP-006"]),
        (PROCESSING_ITEM_QUERY_PATH, ["PP-002", "PP-006"]),
        # #3624 补转人工 Tool 本体（2026-09-19 退场后 CH-008 已 unrunnable ⇒ 只剩 CH-015）
        (HUMAN_HANDOFF_PATH, ["CH-015"]),
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


class TestStaffSettingsDataRules:
    """#3624 缺口①：staff / settings / data 三个 skill 必须映射到本域用例。

    修前实测（origin/main）：三个 skill 文件全部得到
    `(DEFAULT_BEHAVIOR_CASES, 'default_net')` —— 改它们一条 HR/ST/DA 用例都不跑；而
    #3577（产品裁定「交互形态统一」）刚把 `interact` 绑进这三个 skill（确认卡形态变了）。
    兜底网按 #3502 分层「只报告」，于是 HR/ST/DA 的确认卡行为在 CI 里**没有任何真实 LLM 信号**。

    映射依据（逐条读用例真实内容后确定，不是照抄）：
      · HR-001「员工列表」→ `employee_manage(action=list)`（staff 绑定工具之一，smoke）
      · HR-005「创建角色 - 分配权限」→ `role_manage(action=create)` + 「确认创建」轮
        （覆盖另一个绑定工具与 confirm 卡路径）
      · ST-003「修改密码」→ `settings_manage(action=change_password)`（该 skill 的写路径 + 确认）
      · ST-005「通知标记已读」→ `notification_manage(mark_read/read_all)`（第二个写工具）
      · DA-004「客服会话监控」→ `session_manage(action=monitor)`
      · FN-001「资金流水查询与登记」→ `finance_api(action=create_transaction)` + 「确认」轮
    刻意**不**映射 HR-002/HR-003（employee_manage 写路径）：本地 flake 台账
    （`agent-eval-flakes.json`，2026-09-14）里它们是 `reproducible`（同指纹两次失败，非波动）
    —— 放进强信号集会让每个改 staff 的 PR 恒红、且与本 PR 改动无因果（假阻塞成因）；
    待其按 §14.2 归因修复后再评估是否纳入。
    """

    @pytest.mark.parametrize("path, expected", [
        (STAFF_PATH, ["HR-001", "HR-005"]),
        (SETTINGS_PATH, ["ST-003", "ST-005"]),
        (DATA_PATH, ["DA-004", "FN-001"]),
    ])
    def test_skill_change_lands_in_rules_bucket(self, path, expected):
        """改这三个 skill 的本体 → 命中规则桶，且就是本域用例（来源必须是 rules）。"""
        assert bm.map_changed_files_with_source([path]) == (expected, "rules")

    @pytest.mark.parametrize("path", [STAFF_PATH, SETTINGS_PATH, DATA_PATH])
    def test_anchored_skill_file_exists(self, path):
        """规则锚定的是本体源码真实路径（防退化成凭空的文件名）。"""
        assert (REPO_ROOT / path).is_file(), f"锚定文件不存在：{path}"

    @pytest.mark.parametrize("path, expected_source", [
        # 与三个新规则同名的**测试**文件（第三个含历史上误触过的 `guard` 关键词）——
        # `backend/ai-agent-service/tests/**` 不在 AI 行为域内 → 整个 diff 不触发评测（none）
        ("backend/ai-agent-service/tests/test_staff_skill.py", "none"),
        ("backend/ai-agent-service/tests/test_settings_skill_guard.py", "none"),
        ("backend/ai-agent-service/tests/test_data_skill.py", "none"),
        # 评测基建 / 用例库单一源在行为域内，但绝不能进规则桶 → 兜底网
        ("tests/agent_eval/behavior_mapping.py", "default_net"),
        (".github/cases/hr.yml", "default_net"),
        (".github/cases/settings.yml", "default_net"),
        (".github/cases/data.yml", "default_net"),
    ])
    def test_test_and_case_paths_never_enter_rules_bucket(self, path, expected_source):
        """反向断言（#3551 回归防线）：新规则不得把 tests/**、.github/cases/** 拉进规则桶。

        规则桶 = 与改动有因果的强信号集；若测试文件名/用例文件名能命中规则，就会出现
        「与改动无因果的红」—— 正是 #3551 实证过的假阻塞（`*_guard.py` 命中防御规则）。
        两者都可能出现：非行为域路径 → `none`（不触发评测）；行为域内的测试/用例路径
        → `default_net`（跑兜底网但**不**是规则桶）。判据只有一个：**source != "rules"**。
        """
        cases, source = bm.map_changed_files_with_source([path])
        assert source == expected_source, f"{path} 误进规则桶（cases={cases}）"
        assert source != "rules"
        assert cases == ([] if expected_source == "none" else bm.DEFAULT_BEHAVIOR_CASES)

    def test_mixed_diff_with_test_file_does_not_change_case_ids(self):
        """同一个 diff 里混入测试文件 → 规则桶用例集不增不减。"""
        assert bm.map_changed_files_with_source(
            [STAFF_PATH, "backend/ai-agent-service/tests/test_staff_skill_guard.py"]
        ) == (["HR-001", "HR-005"], "rules")

    def test_case_library_paths_alone_fall_to_default_net(self):
        """用例库路径单独出现时同样只落兜底网（不因 hr.yml/settings.yml/data.yml 触发新规则）。"""
        assert bm.map_changed_files_with_source(
            [".github/cases/hr.yml", ".github/cases/settings.yml", ".github/cases/data.yml"]
        ) == (bm.DEFAULT_BEHAVIOR_CASES, "default_net")


class TestProcessingDomainRules:
    """#3624 缺口③：加工项目录（PP-*）与加工单生成（PG-*）此前无规则。

    实证（#3591 收口）：改 `processing_item_manage.py`，映射推出的却是
    **PR-019（商品建品价格）** —— 根因是 product 规则的 `processing_item`
    关键词把加工项目录文件吞进商品域（union 里也没有任何 PP-*），加工项目录自己的
    用例一条没跑（#3511 的旁路同型：规则的**关键词**比意图宽 → 映射到无因果的用例）。
    """

    @pytest.mark.parametrize("path", [PROCESSING_ITEM_MANAGE_PATH, PROCESSING_ITEM_QUERY_PATH])
    def test_processing_item_library_hits_pp_cases(self, path):
        """PP-002（分类列表，期望 `processing_item_query or processing_item_manage`）覆盖查目录；
        PP-006（计价方式 + 新增加工项，期望 `processing_item_query(keyword=打孔)` +
        `processing_item_manage(action=create_processing_item)`）覆盖写目录与确认轮。"""
        assert bm.map_changed_files_with_source([path]) == (["PP-002", "PP-006"], "rules")

    @pytest.mark.parametrize("path", [PROCESSING_ITEM_MANAGE_PATH, PROCESSING_ITEM_QUERY_PATH])
    def test_processing_item_library_no_longer_maps_to_product_cases(self, path):
        """改加工项目录**不得**再映射到商品建品价格用例（PR-019 断言的是
        `product_manage(action=create)`，与目录 CRUD 无因果 —— 那就是假阻塞）。"""
        cases = bm.map_changed_files_to_case_ids([path])
        assert "PR-019" not in cases

    def test_product_side_processing_item_binding_is_gone(self):
        """issue #4371（商品↔加工项解耦）：**商品侧加工项挂载**已退场。

        旧形态：`product_processing_item_manage.py`（给**商品**挂加工项）映射到
        商品域 PR-019 + 直测 PP-001/PP-003。该工具与 PR-020 用例已随解耦一并删除，
        映射表里也不再有「商品侧加工项」规则桶 —— 此路径现落**兜底网**（不静默跳过）。
        """
        assert not (REPO_ROOT / PRODUCT_PROCESSING_ITEM_PATH).exists(), (
            "商品侧加工项挂载工具已退场，不得复活")
        assert bm.map_changed_files_with_source([PRODUCT_PROCESSING_ITEM_PATH]) == (
            bm.DEFAULT_BEHAVIOR_CASES, "default_net")

    def test_order_prompt_change_maps_to_pg017(self):
        """改 prompts/order.md（加工项 vs 加工单概念区分口径，#3917）→ PG-017 进强信号集。

        与 prompt 规则（CH-003/CH-022）取并集 —— 概念区分口径改动必须真跑概念区分用例。
        """
        assert bm.map_changed_files_with_source([ORDER_PROMPT_PATH]) == (
            ["CH-003", "CH-022", "PG-017"], "rules")

    def test_routing_change_stays_in_report_only_net(self):
        """#3921：路由层（rule_matcher 加工单/JG 规则、nodes 会话连续性关键词）**不加**规则桶。

        #3725 决策闸门（test_behavior_gate_reachability 同族）：路由文件是高流量共享层，
        进 blocking 桶 ⇒ 每个改动吃真实 LLM 规则桶（#3551「规则过宽 ⇒ 假阻塞红」）；
        PG-017 首跑即 0 分，稳定性未达校准门槛。加工单路由的确定性回归由 L0 单测承担
        （test_rule_matcher.TestProcessingOrderRouting / test_graph_nodes 加工单逃逸），
        评测守护经 prompts 规则间接触发（改路由必连带改 prompt 场景另计）。
        """
        for path in (RULE_MATCHER_PATH, ROUTING_NODES_PATH):
            cases, source = bm.map_changed_files_with_source([path])
            assert source == "default_net", f"{path} 不应进规则桶（source={source}）"
            assert cases == bm.DEFAULT_BEHAVIOR_CASES

    def test_general_prompt_change_maps_to_pg017(self):
        """#3921：general.md 也补了加工单≠加工项兜底口径 → 改它应触发 PG-017。"""
        cases = bm.map_changed_files_to_case_ids(
            ["backend/ai-agent-service/app/graph/skills/references/prompts/general.md"])
        assert "PG-017" in cases

    def test_processing_order_tool_files_no_longer_anchor_cases(self):
        """#3917：加工单工具已从注册表与 ORDER_TOOLS 移除（类保留），改工具实现文件
        **不再**映射 PG-013/015/016（已 skip、对 agent 不可跑，锚了 = 挂不可跑用例 =
        假阻塞）—— 落兜底网（只报告，不阻塞）。
        """
        for path in (PROCESSING_ORDER_GENERATE_PATH,
                     PROCESSING_ORDER_QUERY_PATH,
                     PROCESSING_ORDER_UPDATE_PATH):
            cases, source = bm.map_changed_files_with_source([path])
            assert source == "default_net", f"{path} 不应再进规则桶（source={source}）"
            assert cases == bm.DEFAULT_BEHAVIOR_CASES

    @pytest.mark.parametrize("path", [
        "backend/ai-agent-service/tests/test_tools_processing_item_manage.py",
        "backend/ai-agent-service/tests/test_tools_processing_order_generate.py",
    ])
    def test_processing_unit_test_paths_do_not_trigger_rules(self, path):
        """`backend/ai-agent-service/tests/**` 不在行为域内 → 不触发评测（更不会进规则桶）。"""
        assert bm.map_changed_files_with_source([path]) == ([], "none")

    @pytest.mark.parametrize("path", [
        ".github/cases/processing.yml",
        ".github/cases/processing-order.yml",
    ])
    def test_processing_case_library_paths_fall_to_default_net(self, path):
        """用例库路径只能在行为域内走兜底网，绝不进规则桶。"""
        assert bm.map_changed_files_with_source([path]) == (
            bm.DEFAULT_BEHAVIOR_CASES, "default_net")


class TestBaseSkillRules:
    """#3624 追加：`base_skill.py` 是守卫代码的**共享载体**，必须映射到它守护的行为面。

    证据（幂等重试 #3564 收口实测）：改 `base_skill.py` 此前只映射 `DF-011`/`DF-012`
    （防御规则），§13.2 的转人工族 `CH-013`/`CH-014`/`CH-015` **不在集合内** —— 而
    base_skill 的守卫判据（不满情绪→建议卡→用户确认转人工；用户拒绝后本会话不再自动建议；
    显式「转人工」不经建议卡直接转）正是这三条用例要覆盖的行为面。

    **明确排除 OR-016**：它当前是已知的用例自相矛盾（`user_inputs[1]` 为裸文本，与
    `order_before` 时序断言冲突，由另一包校准中）。挂上去会让**每个改 `base_skill.py` 的 PR**
    吃到规则命中红（仓库级红，与 #3551 的 DF-011 假阻塞同型）。**待 OR-016 校准合入后再补映射。**
    """

    def test_base_skill_maps_to_handoff_cases(self):
        """改守卫载体 → 转人工族用例必须进强信号集（修复前只有 DF-*）。"""
        cases, source = bm.map_changed_files_with_source([BASE_SKILL_PATH])
        assert source == "rules"
        assert {"CH-013", "CH-014", "CH-015"} <= set(cases)

    def test_base_skill_keeps_defense_mapping(self):
        """共享载体：防御规则对 base_skill 的锚定不得因新规则丢失（并集语义）。"""
        cases, _ = bm.map_changed_files_with_source([BASE_SKILL_PATH])
        assert [c for c in cases if c.startswith("DF-")] == ["DF-011", "DF-012"]

    def test_base_skill_does_not_map_to_order_case(self):
        """刻意排除 OR-016（用例自相矛盾、校准中）——防"每个改 base_skill 的 PR"恒红。"""
        cases, _ = bm.map_changed_files_with_source([BASE_SKILL_PATH])
        assert "OR-016" not in cases

    def test_base_skill_expected_full_set(self):
        """锁定全集（并集 + 字典序）：新规则只能通过改这条断言进入。"""
        assert bm.map_changed_files_with_source([BASE_SKILL_PATH]) == (
            ["CH-013", "CH-014", "CH-015", "DF-011", "DF-012"], "rules")

    @pytest.mark.parametrize("path", [
        # issue #4049：execute_skill 的三段实现搬到了 execution/ —— 转人工守卫判据与写门禁链
        # 随之搬走。若规则只锚 base_skill.py，改这三个文件会**一条 CH-* 都不跑**（假绿）。
        "backend/ai-agent-service/app/graph/skills/execution/prepare_turn.py",
        "backend/ai-agent-service/app/graph/skills/execution/react_turn.py",
        "backend/ai-agent-service/app/graph/skills/execution/finalize_turn.py",
    ])
    def test_split_regions_map_to_handoff_cases(self, path):
        """搬迁家族必须与 base_skill.py **同等**锚定转人工族（扩正则，不是放行）。"""
        cases, source = bm.map_changed_files_with_source([path])
        assert source == "rules", f"{path} 落到了 {source} —— 搬迁后守卫面漏跑用例"
        assert {"CH-013", "CH-014", "CH-015"} <= set(cases), (
            f"{path} 未映射到转人工族：{cases}"
        )

    def test_split_regions_exist_and_are_not_caught_by_the_old_narrow_rule(self):
        """反向：新正则确实**比原来宽**（否则上面那条是假绿）。"""
        import re

        old = r"app/graph/skills/base_skill\.py"
        new = [p for p, _ in bm.MAPPING_RULES if "execution" in p]
        assert new, "MAPPING_RULES 里没有覆盖 execution/*.py 的规则"
        region = "backend/ai-agent-service/app/graph/skills/execution/react_turn.py"
        assert re.search(old, region) is None, "旧正则本不该命中 —— 负例夹具失效"
        assert any(re.search(p, region) for p in new), "新规则没覆盖搬迁模块"

    @pytest.mark.parametrize("path, expected_source", [
        ("backend/ai-agent-service/tests/test_base_skill.py", "none"),
        ("backend/ai-agent-service/tests/test_base_skill_guard.py", "none"),
        (".github/cases/chat.yml", "default_net"),
    ])
    def test_base_skill_test_and_case_paths_never_enter_rules_bucket(self, path, expected_source):
        """反向断言（#3551 假阻塞防线）：测试/用例路径绝不允许因新规则进规则桶。"""
        cases, source = bm.map_changed_files_with_source([path])
        assert source == expected_source
        assert cases == ([] if expected_source == "none" else bm.DEFAULT_BEHAVIOR_CASES)


class TestHumanHandoffRules:
    """#3624 追加：转人工 Tool 本体 → `CH-015`（显式「转人工」→ 如实告知无人工通道 + 禁止假承诺）。

    来源（写工具确认门禁包 #3606 收口实测）：改 `human_handoff.py` 此前落**兜底网**，
    而当时它看起来"命中了规则"其实只是**测试文件名** `*_confirm_guard.py` 撞上防御关键词
    `guard` 的误报面（#3551 已用 `BEHAVIOR_SOURCE_PREFIXES` 集中过滤掉）——真正该跑的
    转人工用例一条没跑。

    映射依据（读用例真实内容）：
      · `CH-015`「用户显式『转人工』→ 如实告知无人工通道并继续服务」`user_inputs: ["我要转人工"]`
        （覆盖对话侧的正确行为，与 base_skill 的建议卡分流互补）
      · ~~`CH-008`~~：2026-09-19 随转人工工具退场标 **unrunnable**（断言不可满足，覆盖改指
        admin-api + 工具直测单测）⇒ 从规则里移除 —— 规则桶只能选**跑得动**的用例，否则
        "改了文件却只选中一条不跑的用例" = 门禁看似有射程、实际零执行（§19.1）。
    这条与 base_skill 规则给出的 `CH-013`/`CH-014`/`CH-015` 是**并集**（同一个转人工族，
    入口不同：Tool 本体 vs 守卫判据）。
    """

    def test_human_handoff_maps_to_handoff_cases(self):
        assert bm.map_changed_files_with_source([HUMAN_HANDOFF_PATH]) == (
            ["CH-015"], "rules")

    def test_human_handoff_does_not_map_to_defense_cases(self):
        """防误报面回归：转人工与防御/注入无关 —— 改它也**不得**把 DF-011/DF-012 拉进来
        （那是 #3606 收口实测的误报形态：`*_confirm_guard.py` 测试文件名命中了防御规则）。"""
        cases, _ = bm.map_changed_files_with_source([HUMAN_HANDOFF_PATH])
        assert [c for c in cases if c.startswith("DF-")] == []

    @pytest.mark.parametrize("path, expected_source", [
        ("backend/ai-agent-service/tests/test_human_handoff.py", "none"),
        ("backend/ai-agent-service/tests/test_human_handoff_confirm_guard.py", "none"),
        (".github/cases/chat.yml", "default_net"),
    ])
    def test_human_handoff_test_and_case_paths_never_enter_rules_bucket(self, path, expected_source):
        cases, source = bm.map_changed_files_with_source([path])
        assert source == expected_source
        assert cases == ([] if expected_source == "none" else bm.DEFAULT_BEHAVIOR_CASES)


class TestUnionAndDedupe:
    """多规则合并（并集）+ 去重"""

    def test_multi_rule_union(self):
        """一个文件同时命中 agent 规则与订单规则 → 两组用例都要跑（并集，不取第一个命中）。"""
        result = bm.map_changed_files_to_case_ids([AGENT_PATH, ORDER_PATH])
        assert result == ["CH-003", "CH-022", "OR-016", "OR-028", "PG-017"]

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
        assert forward == ["CH-003", "CH-010", "CH-019", "CH-022", "OR-016", "OR-028", "PG-017"]

    def test_rule_declaration_order_does_not_leak_into_output(self):
        """结果按用例 ID 字典序（不是 MAPPING_RULES 的声明序）——写死期望值锁住口径。"""
        result = bm.map_changed_files_to_case_ids([GUARD_PATH, PRODUCT_PATH])
        assert result == ["DF-011", "DF-012", "PR-019"]


class TestMappingSource:
    """结果来源分类（门禁分层：规则命中阻塞 / 兜底网只报告，issue #3502）

    背景（2026-09-14 dogfooding 首跑实证）：只改 `tests/agent_eval/behavior_mapping.py`
    （评测基建）会被兜底网里的 CH-010（小布下单）判红 —— 与本 PR 改动**无因果**。
    故 workflow 需要知道"这批用例是规则命中还是兜底网"，二者门禁强度不同。
    """

    def test_rule_hit_reports_rules_source(self):
        assert bm.map_changed_files_with_source([ORDER_PATH]) == (
            ["OR-016", "OR-028", "PG-017"], "rules")

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
        assert cases == ["OR-016", "OR-028", "PG-017"]

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
