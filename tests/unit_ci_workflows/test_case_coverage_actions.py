# case_ids: PG-016, PP-006, CU-005, OR-023
"""覆盖矩阵的 **action 级**判据契约（issue #3667）。

**为什么需要**：工具级矩阵问不出「这个工具**有**用例，但它的某个 action 从没被测」——
实证 `processing_item_manage` 9 个 action 只有 3 个被断言、`processing_order_update`
4 个只有 1 个（PG-016 用 `action: complete` 撑起整域覆盖），而工具级矩阵把它们显示成
"✅ 已覆盖"。真值取**工具源码的 action 枚举**（不是从用例反推，否则缺失的 action
根本不在集合里 = 缺口不可见）。

**处置分档（本文件锁住这个分档，防止后代把门禁做成摆设或做成一堵红墙）**：

| 判据 | 处置 | 理由 |
|---|---|---|
| `action_uncovered`：该工具有用例、该 action 零覆盖 | **只报告**（`check_problems()` 不含它） | 仓库实测 41 处 → 阻塞即大面积飘红 = 用存量债锁死流水线；本质是**厚度**指标（§14.5 已把"仅 1 条用例"定为只报告） |
| `action_dangling`：用例声明了工具**不存在**的 action | **阻塞**（可登记存量豁免） | 配置错误、断言永不满足（假红/假绿），与拼错工具名的 `dangling_cases` 同家族；实测首例仅 1 处（CU-005），已于 #3683 按真实语义修正 → **现为 0 处** |

判据不被削弱的锁：**去掉豁免清单必须红**（下 `test_repo_dangling_action_blocks_without_baseline`：
仓库已无悬空 action 可作反例，改为把人为悬空 action 注入真实用例集后验阻塞），
且人为注入一个悬空 action 时必须被报出来。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT / ".github", REPO_ROOT / "tests" / "agent_eval",
           REPO_ROOT / "scripts"):
    sys.path.insert(0, str(_p))

from case_coverage import (  # noqa: E402
    ACTION_TOOL_FLOOR, BASELINE_PATH, _attach_baseline, action_catalog,
    build_coverage_report, case_declared_actions, load_baseline,
    render_action_gaps, tool_declared_actions, toolset_for,
)
from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"


def _case(cid, tier="normal", expectations=None, **extra):
    c = {"id": cid, "tier": tier, "persona": "mibao", "skip_reason": "",
         "expectations": expectations or [], "user_inputs": ["x"]}
    c.update(extra)
    return c


def _rep(cases, persona="mibao", tools=None):
    return build_coverage_report(cases, persona, tools=tools)


# ── ① action 真值解析（源码枚举）──────────────────────────────────────────────

class TestToolActionTruth:
    """action 真值必须来自**工具源码枚举**，且解析失效要能被发现（不静默变空）。"""

    def test_parses_real_tool_enum(self):
        assert tool_declared_actions("order_manage") == {
            "update_status", "update_logistics", "cancel", "confirm_payment", "refund",
        }

    def test_tool_without_action_dimension_is_empty(self):
        # `knowledge_search` 无 action 维度（不是解析失败 —— 与"工具不存在"同返回空，
        # 故另有 catalog 下界守卫，见下一条）
        assert tool_declared_actions("knowledge_search") == set()

    def test_repo_catalog_is_not_silently_empty(self):
        """仓库下界：解析口径坏了（文件改名/枚举挪走）会让 action 报告**假绿**，必须拦住。"""
        for persona in ("mibao", "xiaobu"):
            catalog = action_catalog(toolset_for(persona))
            assert len(catalog) >= (ACTION_TOOL_FLOOR if persona == "mibao" else 1), (
                f"{persona} 只解析到 {len(catalog)} 个有 action 维度的工具 —— "
                f"源码解析口径漂移了（action 级报告会静默变空）"
            )


# ── ② 用例声明的 action 提取 ──────────────────────────────────────────────────

class TestCaseDeclaredActions:
    """只收**机器可判断言**里的 action；自然语义 data_checks 不算覆盖证据（§1.3）。"""

    def test_dict_expectations_args(self):
        c = _case("T-1", expectations=[{"tool": "order_manage", "args": {"action": "cancel"}}])
        assert case_declared_actions(c) == {"order_manage": {"cancel"}}

    def test_string_expectation_form(self):
        c = _case("T-2", expectations=["order_manage(action=update_status)"])
        assert case_declared_actions(c) == {"order_manage": {"update_status"}}

    def test_or_branch_string_is_not_attributed(self):
        """`A or B` 下 action 归属无法从文本判定 → 宁可不收（误收会造假阻塞）。"""
        c = _case("T-3", expectations=["order_manage(action=cancel) or order_query"])
        assert case_declared_actions(c) == {}

    def test_structured_assertion_keys(self):
        c = _case("T-4",
                  must_succeed=[{"tool": "processing_item_manage", "action": "update_item"}],
                  output_verify=[{"tool": "processing_item_manage", "action": "create_processing_item"}],
                  required_args=[{"tool": "employee_manage", "action": "update", "fields": ["phone"]}],
                  must_fail=[{"tool": "order_create", "action": "create"}],
                  db_verify=[{"fetch": "processing_order", "source": "processing_order_update",
                              "action": "complete", "checks": ["status==completed"]}])
        assert case_declared_actions(c) == {
            "processing_item_manage": {"update_item", "create_processing_item"},
            "employee_manage": {"update"},
            "order_create": {"create"},
            "processing_order_update": {"complete"},
        }

    def test_or_in_action_value_is_split(self):
        c = _case("T-5", expectations=[{"tool": "notification_manage",
                                        "args": {"action": "mark_read or read_all"}}])
        assert case_declared_actions(c) == {"notification_manage": {"mark_read", "read_all"}}

    def test_natural_language_data_checks_are_not_coverage_evidence(self):
        """自然语义 `data_checks`（"customer_id 从 customer_manage 查询获得"）不是判据。"""
        c = _case("T-6", expectations=[{"tool": "customer_manage"}],
                  data_checks=["customer_id 从 customer_manage(action=query) 查询获得"])
        assert case_declared_actions(c) == {}


# ── ③ 未覆盖 action：只报告，不阻塞 ───────────────────────────────────────────

class TestUncoveredActionsAreReportedNotBlocking:
    def test_multi_action_tool_reports_uncovered_actions(self):
        rep = _rep([_case("T-10", expectations=[{"tool": "order_manage",
                                                 "args": {"action": "cancel"}}])],
                   tools={"order_manage"})
        missed = {a for t, a in rep.action_uncovered if t == "order_manage"}
        assert missed == {"update_status", "update_logistics", "confirm_payment", "refund"}
        assert rep.action_cases[("order_manage", "cancel")] == ["T-10"]

    def test_all_actions_declared_reports_nothing(self):
        acts = sorted(tool_declared_actions("order_manage"))
        rep = _rep([_case("T-11", expectations=[{"tool": "order_manage",
                                                 "args": {"action": a}} for a in acts])],
                   tools={"order_manage"})
        assert rep.action_uncovered == []

    def test_single_action_tool_is_not_a_gap(self):
        """单 action 工具：调工具 == 调该 action，报"未覆盖"是**假缺口**，必须排除。"""
        rep = build_coverage_report(
            [{"id": "T-12", "tier": "normal", "persona": "xiaobu", "skip_reason": "",
              "user_inputs": ["我的订单"], "expectations": [{"tool": "customer_order_query"}]}],
            "xiaobu", tools={"customer_order_query"})
        assert rep.action_tools.get("customer_order_query") == {"list"}
        assert rep.action_uncovered == []

    def test_zero_case_tool_is_not_double_reported(self):
        """零用例工具的 action 由工具级 `uncovered` 报；action 级不重复报同一件事。"""
        rep = _rep([_case("T-13", expectations=[{"tool": "order_query"}])],
                   tools={"order_query", "order_manage"})
        assert "order_manage" in rep.uncovered
        assert [t for t, _a in rep.action_uncovered if t == "order_manage"] == []

    def test_uncovered_actions_do_not_enter_check_problems(self):
        """**分档锁**：action 未覆盖是厚度指标 —— 不许进 --check 的失败条件。"""
        rep = _rep([_case("T-14", expectations=[{"tool": "order_manage",
                                                 "args": {"action": "cancel"}}])],
                   tools={"order_manage"})
        assert rep.action_uncovered, "本测试需要非空的 action 缺口才有意义"
        assert rep.check_problems() == []

    def test_render_includes_uncovered_section(self):
        rep = _rep([_case("T-15", expectations=[{"tool": "order_manage",
                                                 "args": {"action": "cancel"}}])],
                   tools={"order_manage"})
        text = render_action_gaps(rep, "B 端米宝")
        assert "只报告不阻塞" in text and "update_status" in text
        assert "order_manage" in render_action_gaps(rep, "B 端米宝", md=True)

    def test_render_is_empty_without_action_dimension(self):
        """该端一个 action 维度都没有 → 渲染器返回空串（不往报告里塞空标题）。"""
        rep = _rep([_case("T-16", expectations=[{"tool": "knowledge_search"}])],
                   tools={"knowledge_search"})
        assert rep.action_tools == {}
        assert render_action_gaps(rep) == ""


# ── ④ 悬空 action：阻塞 + 可登记存量豁免 ──────────────────────────────────────

class TestDanglingActionBlocks:
    def test_declared_action_missing_from_tool_enum_is_reported(self):
        rep = _rep([_case("T-20", expectations=[{"tool": "order_manage",
                                                 "args": {"action": "ship"}}])],
                   tools={"order_manage"})
        assert rep.action_dangling == [("order_manage", "ship")]
        assert ("order_manage", "action_dangling") in rep.blocking_gaps()
        assert any("不存在" in p and "action=ship" in p for p in rep.check_problems())

    def test_baselined_dangling_action_is_exempted(self, tmp_path):
        """登记后必须全绿（否则存量豁免形同虚设 → 门禁在 main 上常红）。"""
        bl = load_baseline(_baseline_file(tmp_path, "action_dangling"), "mibao", {"order_manage"})
        rep = _attach_baseline(
            _rep([_case("T-21", expectations=[{"tool": "order_manage",
                                               "args": {"action": "ship"}}])],
                 tools={"order_manage"}), bl)
        assert rep.check_problems() == [], rep.check_problems()
        assert not rep.baseline_stale_blocking

    def test_baseline_entry_becomes_stale_after_case_fixed(self, tmp_path):
        """改用例（销账）后条目即陈旧 → 阻塞，逼删条目（清单只可能变短）。"""
        bl = load_baseline(_baseline_file(tmp_path, "action_dangling"), "mibao", {"order_manage"})
        rep = _attach_baseline(
            _rep([_case("T-22", expectations=[{"tool": "order_manage",
                                               "args": {"action": "cancel"}}])],
                 tools={"order_manage"}), bl)
        assert rep.baseline_stale_blocking == [("order_manage", "action_dangling")]
        assert any("已销账但条目未删" in p for p in rep.check_problems())


def _baseline_file(tmp_path, kind: str):
    f = tmp_path / "eval-coverage-baseline.yml"
    f.write_text(
        "version: 2\nentries:\n"
        "  - tool: order_manage\n"
        f"    kind: {kind}\n"
        "    persona: mibao\n"
        '    issue: "#3669"\n'
        "    reason: 测试用条目（单测注入的临时清单，非仓库清单）\n"
        '    added: "2026-09-14"\n',
        encoding="utf-8")
    return f


# ── ⑤ 仓库真值：判据在真实用例库上的行为（不被削弱）───────────────────────────

class TestRepoActionLevelJudgement:
    """仓库清单下 **全绿** + **去掉豁免清单必红** —— 判据没被削弱的唯一判据。"""

    @classmethod
    def setup_class(cls):
        cls.cases = load_case_dicts(str(CASES_DIR))

    def test_repo_reports_action_gaps_including_known_precedents(self):
        rep = _rep(self.cases)
        pairs = set(rep.action_uncovered)
        for expected in (("processing_order_update", "issue"),
                         ("processing_item_manage", "create_category"),
                         ("order_manage", "update_status")):
            assert expected in pairs, f"{expected} 未被报出 —— action 级判据没生效"
        assert len(pairs) >= 30, f"只报出 {len(pairs)} 处 action 缺口，疑似解析口径缩水"

    def test_repo_check_is_green_with_baseline(self):
        for persona in ("mibao", "xiaobu"):
            rep = _attach_baseline(
                _rep(self.cases, persona),
                load_baseline(BASELINE_PATH, persona, toolset_for(persona)))
            assert rep.check_problems() == [], f"{persona}: {rep.check_problems()}"

    def test_repo_dangling_action_blocks_without_baseline(self):
        """**去掉豁免清单必红** + 仓库真值归零（CU-005 修正后，issue #3683）。

        两半锁，缺一不可：
          ① 仓库真值：真实用例库**不得再有**悬空 action —— CU-005 的
             `customer_manage(action=query)` 已按真实语义改为 `action: list`（该工具枚举无
             query），两端都必须报 0 处；将来新引入的悬空 action 会立刻打红本断言；
          ② 判据不被削弱：把一个人为的悬空 action 注入**真实用例集**后，在**无清单**下
             必须阻塞（`action_dangling` + `check_problems()` + `blocking_gaps()` 三处同验）——
             真实仓库已无悬空 action 可作反例（那正是本次修复的目标），故用注入方式在同一套
             引擎（真实 cases + 真实工具枚举）上继续锁住「去掉清单必红」。
        """
        for persona in ("mibao", "xiaobu"):
            rep = _rep(self.cases, persona)
            assert rep.action_dangling == [], (
                f"{persona}: 用例库声明了工具不存在的 action"
                f"（配置错误，断言永不满足）—— {rep.action_dangling}")
        injected = list(self.cases) + [
            _case("T-DANGLING", expectations=[{"tool": "order_manage",
                                              "args": {"action": "no_such_action"}}])]
        rep2 = _rep(injected, "mibao")
        assert ("order_manage", "no_such_action") in rep2.action_dangling
        assert any("order_manage(action=no_such_action)" in p for p in rep2.check_problems())
        assert ("order_manage", "action_dangling") in rep2.blocking_gaps()

    def test_repo_uncovered_actions_alone_never_block(self):
        """仓库里 41 处 action 未覆盖，但（在清单下）不得产生任何阻塞项。"""
        rep = _attach_baseline(
            _rep(self.cases, "mibao"),
            load_baseline(BASELINE_PATH, "mibao", toolset_for("mibao")))
        assert len(rep.action_uncovered) >= 30
        assert rep.check_problems() == []

    def test_xiaobu_has_no_action_dangling(self):
        rep = _rep(self.cases, "xiaobu")
        assert rep.action_dangling == []
