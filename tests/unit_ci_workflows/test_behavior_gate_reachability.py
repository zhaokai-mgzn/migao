# case_ids: OR-015, OR-017, AS-003, OR-016, AS-007, PR-019, CH-010
"""行为映射门禁「可达性」守卫 + 门禁分层锁（issue #3725）—— L0 静态锁，秒级零 LLM。

## 病根（issue #3725）

`tests/agent_eval/behavior_mapping.py` 决定「改了哪些文件 → 跑哪些用例」。修前
**OR-015 / OR-017 / AS-003** 三条例**既不在 `MAPPING_RULES`、也不在 `DEFAULT_BEHAVIOR_CASES`**
⇒ 无论改什么文件，这个门禁都**选不中**它们（结构性不可达）。
实证危害：PR **#3718**（修 OR-015「模块越界拒绝」）自己的真实 LLM 迭代档选中的是
`CH-003/CH-013/CH-014/CH-015/DF-011/DF-012` —— **目标用例没跑**。

## 为什么"在映射集合里"不够（本文件存在的理由）

workflow 的 map job **不是**把映射结果直接当 `case_ids` 传下去，而是用**用例库自己的选择
函数**（`render_cases.load_case_dicts` + `eval_case_filter.select_cases_for_persona`）把结果
切成 **(persona, tier) 分桶**，评测步骤**逐桶**调用 runner
（`.github/workflows/agent-behavior-eval.yml` 的 map job，文件内 `:41-46` 注释说明了同一件事）。
⇒ **"在兜底网里" ≠ "会真的跑"**：persona 不匹配 / 工具集不属于该端 / `skip_reason` 非空
（落 `unrunnable`）都会被分桶丢掉 —— 只判集合成员会成为一个**恒绿的空断言**
（never-fires，`migao-acceptance` v1.2「空断言」）。

## 可达性判据链（三段都要过，缺一段即不可达）

1. 在 `DEFAULT_BEHAVIOR_CASES` ∪ 规则命中内（**必要不充分**）；
2. `select_cases_for_persona` 在**至少一个** persona 下选得中它（真能被调度）；
3. `skip_reason` 为空（否则按 workflow 语义该进 `unrunnable`，不算可达）。

再加一层**真实入口见证**：用代表性 diff 走 `map_changed_files_with_source` → 按 workflow
的分桶规则（`owners[0]`）算出它会进哪个桶 —— 证明"真的会被调度"，而不是集合代数上成立。

## 关键用例集合的定义（可解释，不是三个魔数）

见 `KEY_BEHAVIOR_CASES` 的**逐条依据**（入选判据 A/B，每条都带 run 号或 issue 号）：

- 判据 A —— **结论档确定性失败清单**（`eval-summary-*.json` 的
  `completion.deterministic_failures`）里出现过：这类用例能红、且红的是真行为缺陷（高价值信号）；
- 判据 B —— **结构上不可达但已证明是行为面承载用例**（issue #3725 的病根形态）：
  不可达 = "射程被无声缩小"，它与用例写得好不好无关，是门禁**自己看不见**。

新增/移出本表 = 改门禁射程，必须在 PR 里写依据（`TestKeyCaseRegistry` 会强制每条带证据引用）。

## 反向风险（为什么本文件不锁"必须进规则桶"）

`behavior_mapping.py:55-62` 记录了 #3551 的教训：**规则过宽 ⇒ 假阻塞红**，而"假阻塞比没有
门禁更糟"。本 PR 只把三条补进**兜底网（只报告、不阻塞）**；`graph/nodes.py` 的**阻塞型**
规则桶留待稳定性校准后单独裁决。故 `TestLayeringUnchanged` 锁的是"**本 PR 没扩大阻塞面**"
（分层语义逐字不变），不是"路由层永远不准进规则桶"——后者是决策闸门，注释已写明更新方式。
"""
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

from behavior_mapping import (  # noqa: E402
    DEFAULT_BEHAVIOR_CASES,
    MAPPING_RULES,
    map_changed_files_with_source,
)
from eval_case_filter import case_skip_reason, select_cases_for_persona  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402

CASES_DIR = REPO_ROOT / ".github" / "cases"
BEHAVIOR_EVAL_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "agent-behavior-eval.yml"
PERSONAS = ("mibao", "xiaobu")

# ── 代表性 diff（真实仓内路径，均有 is_file 见证断言）──
# 兜底网的触发形态：`app/` 下的 AI 行为源文件、且不命中任何 MAPPING_RULES 关键词
# （= 映射表盲区，正是兜底网的适用场景；也是本 PR 三条新用例的可达见证）。
UNMAPPED_AI_SOURCE = "backend/ai-agent-service/app/main.py"
# 规则桶的代表性 diff：订单 skill 本体（锚定 OR-016/OR-028），用于锁"规则命中仍是 rules 来源"。
RULES_ANCHOR_SOURCE = "backend/ai-agent-service/app/graph/skills/order_skill.py"
# 路由判据层（本 PR 刻意**不**给它加阻塞型规则桶，见模块 docstring「反向风险」）。
ROUTING_SOURCE = "backend/ai-agent-service/app/graph/nodes.py"

# ══════════════════════════════════════════════════════════════════════════════
# 「门禁必须可达」的关键用例登记表（issue #3725 的可解释化定义）
# ══════════════════════════════════════════════════════════════════════════════
# 每条 = 用例 ID → 入选依据（**必须**带 run 号或 issue 号，否则 TestKeyCaseRegistry 会红）。
KEY_BEHAVIOR_CASES = {
    # ── 判据 A + B（结论档确定性失败 + 结构性不可达）──
    "OR-015": (
        "判据 A+B：run 34841029062 的 mibao `eval-summary` 里 completion.deterministic_failures "
        "= ['AS-003','CR-001','OR-008','OR-015','PG-016','PP-007']（含本用例）；"
        "同时它修前不可达（issue #3725）——正是 PR #3718「模块越界拒绝」的暴露用例，"
        "而该 PR 自己的门禁没选中它。"
    ),
    "AS-003": (
        "判据 A+B：run 34841029062 的 mibao `eval-summary` 的 deterministic_failures 含 AS-003"
        "（跨域复用 order_id 创建退款工单）；修前亦不可达（issue #3725）。"
    ),
    "OR-017": (
        "判据 B：修前不可达（issue #3725），且它是 OR-015/OR-016「加工项闭环」的 **C 端对位用例**"
        "（§13.2 订单域）——不可达 = C 端自助下单加工项整条链路在 PR 门禁里零信号。"
        "说明：全量 run 34841029062 的 xiaobu 腿 36/36 通过 ⇒ **未观测到失败**，"
        "入选理由是「消掉结构性不可达 + 保住 C 端对位信号」，不是「已观测到缺陷」。"
    ),
    # ── 判据 B 之「兜底网现有成员」：兜底网成员必须可达，否则兜底网自身失效 ──
    "CH-010": (
        "判据 B：兜底网现有成员（issue #3502），且是其中**唯一的 C 端交互卡用例**"
        "（选购下单表单化交互，#3653 的 paths 前置门后仍靠它保住 C 端主链路信号；"
        "#3725 补入 OR-017 后，C 端成员由 1 条增至 2 条）。"
    ),
    "OR-016": (
        "判据 B：兜底网现有成员（issue #3502）——下单引导/加工项询问（§13.2 订单域核心）。"
    ),
    "PR-019": (
        "判据 B：兜底网现有成员（issue #3502）——建品规格与加工项价格落库（§13.2 商品域核心）。"
    ),
    "AS-007": (
        "判据 B：兜底网现有成员（issue #3502）——换货选目标商品后确认加工项（§13.2 售后域核心）。"
    ),
}

# 本次新增进兜底网的三条（红线锁用：它们**只报告、不阻塞**）
NEWLY_ADDED_FALLBACK_CASES = ("OR-015", "OR-017", "AS-003")


# ══════════════════════════════════════════════════════════════════════════════
# 纯函数：可达性判定（注入式红证用 —— 与仓库当下真值解耦）
# ══════════════════════════════════════════════════════════════════════════════
def schedulable_personas(case_id, runnable_by_persona, skip_reasons):
    """该用例**真能被调度**的 persona 列表（判据链 ②③）。

    `skip_reason` 非空 → 按 workflow 语义进 `unrunnable`（不算可达）→ 返回 []。
    """
    if skip_reasons.get(case_id, ""):
        return []
    return [p for p in PERSONAS if case_id in runnable_by_persona.get(p, set())]


def unreachable_key_cases(key_cases, mapped_ids, runnable_by_persona, skip_reasons):
    """关键用例里**不可达**的那些 → `[(case_id, 原因串), ...]`（空列表 = 全可达）。

    判据链三段独立判定（三段都可被注入样本触发 → 没有恒不执行的死分支）：
      ① 在映射结果（规则命中 ∪ 兜底网）内；② 至少一个 persona 能调度；③ skip_reason 为空。
    """
    bad = []
    for case_id in sorted(key_cases):
        reasons = []
        if case_id not in mapped_ids:
            reasons.append("不在 MAPPING_RULES 命中 ∪ DEFAULT_BEHAVIOR_CASES 内"
                           "（无论改什么文件都选不中 = 结构性不可达）")
        if skip_reasons.get(case_id, ""):
            reasons.append(f"skip_reason 非空（{skip_reasons[case_id]}）→ 落 unrunnable")
        if not schedulable_personas(case_id, runnable_by_persona, skip_reasons):
            reasons.append("没有任何 persona 能调度它（分桶后为空 = 在网里也不会执行）")
        if reasons:
            bad.append((case_id, "；".join(reasons)))
    return bad


# ══════════════════════════════════════════════════════════════════════════════
# 仓库真值装载 + workflow 分桶镜像
# ══════════════════════════════════════════════════════════════════════════════
def _case_dicts():
    return load_case_dicts(str(CASES_DIR))


def _runnable_ids(case_dicts, persona):
    return {str(c.get("id") or "") for c in select_cases_for_persona(case_dicts, persona)}


def _runnable_by_persona(case_dicts):
    return {p: _runnable_ids(case_dicts, p) for p in PERSONAS}


def _skip_reasons(case_dicts):
    return {str(c.get("id") or ""): case_skip_reason(c) for c in case_dicts}


def _rule_case_ids():
    """MAPPING_RULES 覆盖的全部用例 ID（规则桶 = 阻塞档）。"""
    return {cid for _pattern, ids in MAPPING_RULES for cid in ids}


def _mapped_case_ids():
    """映射结果全集（规则桶 ∪ 兜底网）= 门禁**能选中**的用例上界。"""
    return _rule_case_ids() | set(DEFAULT_BEHAVIOR_CASES)


def _workflow_plan(paths, case_dicts):
    """workflow map job 的**分桶镜像** → `(buckets, source)`，`buckets = {persona: [case_id]}`。

    同源复用 `map_changed_files_with_source` + `select_cases_for_persona`；唯一复述的是
    workflow 那 4 行分桶规则（`owners = [p for p in ("mibao","xiaobu") if cid in runnable[p]]`
    → `owners[0]`）。**漂移守卫**见 `TestWorkflowBucketingIsMirrored`。
    """
    ids, source = map_changed_files_with_source(paths)
    runnable = _runnable_by_persona(case_dicts)
    buckets = {}
    for cid in ids:
        owners = [p for p in PERSONAS if cid in runnable[p]]
        if not owners:
            continue  # → workflow 的 unrunnable 名单（在网里也不会执行）
        buckets.setdefault(owners[0], []).append(cid)
    return buckets, source


def _map_step_script():
    """取 `agent-behavior-eval.yml`「计算执行计划」步骤的内联脚本正文。"""
    wf = yaml.safe_load(BEHAVIOR_EVAL_WORKFLOW.read_text(encoding="utf-8")) or {}
    for job in (wf.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("id") == "map":
                return step.get("run") or ""
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# A. 登记表自身（可解释性 + 陈旧即红）
# ══════════════════════════════════════════════════════════════════════════════
class TestKeyCaseRegistry:
    """关键用例集合必须**可解释**（每条带证据引用）且**不过期**。"""

    def test_every_entry_cites_evidence(self):
        """每条依据都要带 run 号或 issue 号（防退化成"三个魔数"的清单）。"""
        for cid, reason in KEY_BEHAVIOR_CASES.items():
            assert re.search(r"run \d+|#\d+", reason), (
                f"{cid} 的依据没有可追溯引用（run 号 / issue 号）—— 关键用例集合必须可解释，"
                f"否则下一个人无法判断该不该移出。现依据：{reason!r}"
            )

    def test_newly_added_fallback_cases_are_registered_as_key_cases(self):
        """本 PR 补进兜底网的三条都必须在登记表里（否则补了却没有守卫保护）。"""
        missing = [cid for cid in NEWLY_ADDED_FALLBACK_CASES if cid not in KEY_BEHAVIOR_CASES]
        assert missing == [], f"这几条已在兜底网里但未登记为关键用例：{missing}"

    def test_registry_entries_still_exist_in_case_library(self):
        """陈旧即红：用例被删/改名后必须同步登记表（报错指向正确动作：更新登记表）。"""
        existing = {str(c.get("id") or "") for c in _case_dicts()}
        missing = sorted(cid for cid in KEY_BEHAVIOR_CASES if cid not in existing)
        assert missing == [], (
            f"登记表里的用例已不在 `.github/cases/` 中：{missing} —— "
            "请更新 KEY_BEHAVIOR_CASES（用例真被删除时）或恢复用例。"
        )


# ══════════════════════════════════════════════════════════════════════════════
# B. 可达性守卫（本文件的核心产出）
# ══════════════════════════════════════════════════════════════════════════════
class TestKeyCasesAreReachable:
    """每条关键用例都必须「能被门禁选中 **且** 真能被调度」。"""

    def test_no_key_case_is_unreachable(self):
        """**核心守卫**：射程被无声缩小时必红（issue #3725 的病根形态）。"""
        case_dicts = _case_dicts()
        bad = unreachable_key_cases(
            KEY_BEHAVIOR_CASES, _mapped_case_ids(),
            _runnable_by_persona(case_dicts), _skip_reasons(case_dicts),
        )
        assert bad == [], (
            "以下关键用例**不可达**（无论改什么文件，门禁都选不中/跑不到它们）：\n"
            + "\n".join(f"  · {cid}：{why}" for cid, why in bad)
            + "\n修法：补进 DEFAULT_BEHAVIOR_CASES（只报告）或 MAPPING_RULES（阻塞，需先校准）；"
            "用例被跳过则需先修 skip_reason。见 issue #3725。"
        )

    @pytest.mark.parametrize("case_id", sorted(KEY_BEHAVIOR_CASES))
    def test_key_case_enters_a_real_bucket_through_the_entrypoint(self, case_id):
        """真实入口见证：代表性 diff → 映射 → 分桶，该用例确实进了一个 (persona) 桶。"""
        case_dicts = _case_dicts()
        buckets, source = _workflow_plan([UNMAPPED_AI_SOURCE], case_dicts)
        assert source == "default_net", (
            f"{UNMAPPED_AI_SOURCE} 不再落兜底网（source={source}）—— "
            "本见证的前提失效，请换一个「映射表盲区」的代表性文件。"
        )
        runnable = _runnable_by_persona(case_dicts)
        owners = [p for p in PERSONAS if case_id in runnable[p]]
        assert owners, (
            f"{case_id} 没有任何 persona 能调度它（会进 workflow 的 unrunnable 名单）—— "
            "它就算在兜底网里也永远不会执行 = 空断言。"
        )
        # workflow 的分桶规则：双端用例归 owners[0]（仓库默认 persona）
        assert case_id in buckets.get(owners[0], []), (
            f"{case_id} 未进入 persona={owners[0]} 的执行桶（桶内容：{buckets}）—— "
            "门禁不会真的跑它。"
        )

    def test_representative_diffs_still_exist(self):
        """上面几个代表性路径必须真的存在（防退化成凭空的文件名）。"""
        for path in (UNMAPPED_AI_SOURCE, RULES_ANCHOR_SOURCE, ROUTING_SOURCE):
            assert (REPO_ROOT / path).is_file(), f"代表性 diff 路径不存在：{path}"


class TestReachabilityCheckerActuallyFires:
    """注入式红证（`migao-acceptance` v1.4：与被测真值解耦，永远有效）——

    证明上面那条守卫**会红**、三段判据**都活着**（不是恒绿的空断言）。
    """

    def test_reports_case_missing_from_mapping(self):
        """判据 ①：不在映射集合内 → 点名该用例（本 PR 修的就是这一形态）。"""
        bad = unreachable_key_cases({"OR-015"}, {"CH-010"}, {"mibao": {"CH-010"}}, {})
        assert [cid for cid, _ in bad] == ["OR-015"]
        assert "结构性不可达" in bad[0][1]

    def test_reports_case_filtered_out_by_persona_bucketing(self):
        """判据 ②：在映射集合内、但没有任何 persona 选得中 → 仍然判不可达。"""
        bad = unreachable_key_cases(
            {"OR-017"}, {"OR-017"}, {"mibao": set(), "xiaobu": set()}, {})
        assert [cid for cid, _ in bad] == ["OR-017"]
        assert "没有任何 persona 能调度" in bad[0][1]

    def test_reports_case_with_skip_reason(self):
        """判据 ③：skip_reason 非空 → 落 unrunnable，不算可达。"""
        bad = unreachable_key_cases(
            {"AS-003"}, {"AS-003"}, {"mibao": {"AS-003"}},
            {"AS-003": "纯前端 jest 用例（非 LLM 行为）"})
        assert [cid for cid, _ in bad] == ["AS-003"]
        assert "skip_reason 非空" in bad[0][1]

    def test_persona_selector_drops_skipped_cases_premise(self):
        """前提守卫：判据 ③ 依赖 `select_cases_for_persona` 真的丢掉 skip_reason 非空的用例。"""
        rows = [{"id": "XX-999", "persona": "xiaobu", "skip_reason": "纯前端 jest"}]
        assert select_cases_for_persona(rows, "xiaobu") == []
        rows[0]["skip_reason"] = ""
        assert [c["id"] for c in select_cases_for_persona(rows, "xiaobu")] == ["XX-999"]


class TestWorkflowBucketingIsMirrored:
    """分桶镜像的漂移守卫：workflow 改了分桶口径 → 本文件必须同步（否则守卫会撒谎）。"""

    def test_map_step_uses_the_same_selection_functions(self):
        script = _map_step_script()
        assert script, "找不到 agent-behavior-eval.yml 的 map 步骤内联脚本（守卫前提失效）"
        for anchor in ("select_cases_for_persona", "case_skip_reason", "owners[0]"):
            assert anchor in script, (
                f"map job 的分桶实现里找不到 {anchor!r} —— 分桶口径变了，"
                "请同步本文件的 `_workflow_plan` 镜像后再更新本断言。"
            )


# ══════════════════════════════════════════════════════════════════════════════
# C. 门禁分层锁（红线：本 PR **不**扩大阻塞面）
# ══════════════════════════════════════════════════════════════════════════════
class TestLayeringUnchanged:
    """红线（issue #3725）：只补兜底网（只报告），"规则命中仍阻塞 / 兜底网仍只报告"逐字不变。"""

    def test_workflow_mode_derivation_is_verbatim(self):
        """workflow 的 `source → mode` 判定逐字锁定（改了就等于改门禁分层语义）。"""
        script = _map_step_script()
        assert 'mode = "blocking" if source == "rules" else "report-only"' in script, (
            "agent-behavior-eval.yml 的 mode 判定已变 —— 本 PR 的前提是分层语义**逐字不变**"
            "（规则命中 = blocking / 兜底网 = report-only）；"
            "若确要改门禁强度，请与 issue #3725 的校准结论一起改并更新本断言。"
        )

    def test_rule_hit_still_reports_rules_source(self):
        """规则命中仍走 rules（阻塞档）——不因本 PR 的补充而改变。

        order_skill.py 自 #3917 起同时命中「下单引导」（OR-016/OR-028）与
        「加工单概念区分」（PG-017）两条规则 → 并集（含 PG-017）。
        """
        case_ids, source = map_changed_files_with_source([RULES_ANCHOR_SOURCE])
        assert (case_ids, source) == (["OR-016", "OR-028", "PG-017"], "rules")

    def test_default_net_diff_still_reports_default_net_source(self):
        """兜底网仍走 default_net（只报告）——且内容与常量逐字一致。"""
        case_ids, source = map_changed_files_with_source([UNMAPPED_AI_SOURCE])
        assert source == "default_net"
        assert case_ids == list(DEFAULT_BEHAVIOR_CASES)

    def test_fallback_net_is_sorted_and_deduped(self):
        """兜底网自身保持"去重 + 字典序"（映射 API 的稳定性契约，workflow 输出可比对）。"""
        assert DEFAULT_BEHAVIOR_CASES == sorted(set(DEFAULT_BEHAVIOR_CASES)), (
            f"兜底网未去重/未排序：{DEFAULT_BEHAVIOR_CASES} —— "
            "workflow 的 case_ids 输出与 PR 评论要能跨机器/跨次数比对。"
        )

    @pytest.mark.parametrize("case_id", NEWLY_ADDED_FALLBACK_CASES)
    def test_newly_added_cases_are_not_rule_anchored(self, case_id):
        """本次补进兜底网的三条**只能**走兜底网（report-only），不得同时具备阻塞力。

        想让它们具备阻塞力 ⇒ 必须先完成稳定性校准（issue #3725 的另半），
        并同步本断言与 #3551 的反向风险（规则过宽 ⇒ 假阻塞红比没有门禁更糟）。
        """
        assert case_id not in _rule_case_ids(), (
            f"{case_id} 同时被 MAPPING_RULES 锚定 ⇒ 阻塞面被扩大（本 PR 的红线是**不**扩大）。"
            "若这是校准后的有意决策，请更新本断言并在 PR 里给出稳定性证据。"
        )

    def test_routing_layer_still_falls_to_report_only_net(self):
        """决策闸门：`graph/nodes.py` 当下仍**无规则桶**（走兜底网 = 只报告）。

        issue #3725 的反向风险：给路由判据本体加**阻塞型**规则桶会让每个改 `nodes.py` 的
        PR 吃到真实 LLM 规则桶（#3551 实证的"规则过宽 ⇒ 假阻塞红"），须先校准稳定性。
        **更新方式**：确已校准并决定加规则桶时，本断言与 evidence 一并改（它是那次决策的
        显式闸门，不是"路由层永远不准进规则桶"）。
        """
        case_ids, source = map_changed_files_with_source([ROUTING_SOURCE])
        assert source == "default_net", (
            f"{ROUTING_SOURCE} 已进规则桶（source={source}, cases={case_ids}）—— "
            "若为有意校准，请同步本断言；若非有意，请检查新规则是否误命中路由层。"
        )
        assert case_ids == list(DEFAULT_BEHAVIOR_CASES)
