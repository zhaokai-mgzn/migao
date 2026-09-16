# case_ids: PR-006, PR-018
"""行为映射门禁「已声明覆盖关系」守卫（issue #3837）—— L0 静态锁，秒级零 LLM。

## 病根（与 issue #3725 的 OR-015 同族：「改了 X，门禁一条 X 的用例都没跑」）

`tests/agent_eval/behavior_mapping.py` 决定「改哪些文件 → 跑哪些用例」。修前实测
（本包用**同一纯函数**复算 PR #3831 的真实变更集，即改了「低库存」口径那一次）：

    mapping_source = default_net
    case_ids = AS-003, AS-007, CH-010, OR-015, OR-016, OR-017, PR-019

- `MAPPING_RULES` 里**没有任何一条**锚定库存侧工具
  （`app/tools/product_search.py` / `inventory_manage.py` / `stock_semantics.py`）；
- `DEFAULT_BEHAVIOR_CASES` 也不含 `PR-006` / `PR-018`；
- ⇒ **改了低库存口径，门禁一条低库存用例都没跑**：兜底网只管"主链路没被改崩"
  （与本次改动**无因果**，失败只报告、连 issue 都不开）。

它不是"少跑几条"那么轻：这正是 `#3725` 记录过的形态（修 OR-015 的 PR 自己没跑 OR-015）。
本文件把「**已声明的覆盖关系**」变成可执行断言 —— 让它**不能再无声缩水**。

## 守卫判据（`DECLARED_TOOL_FILE_COVERAGE`：工具文件 → 触碰它后**必须**选中的用例）

1. **选中**：对每个已声明文件，`map_changed_files_with_source([file])` 必须是
   `source == "rules"`（有因果的规则桶）且返回集 ⊇ 声明集 ——
   *"改了这个文件，这些用例必须被选中"*；
2. **真能跑到**（"在映射结果里" ≠ "会真的跑"，同 `#3725` 的教训）：声明集里每条用例都要
   (a) 存在且 `skip_reason` 为空、(b) 至少一个 persona 选得中、(c) 通过**该文件的真实入口**
   （diff → 映射 → workflow 分桶）落进一个真实的 (persona, tier) 桶；
3. **persona 相容**（本包最容易踩的坑）：映射结果按 workflow 的分桶规则（`owners[0]`）分桶后，
   **任何一条会启动的腿都不能拿到不属于本腿可跑集的 ID** —— 否则 `local_runner` 会以
   `❌ --case-ids 里有无法解析的用例 ID …（禁止静默少跑）` 直接 `sys.exit(1)`，把整条腿弄红
   （`#3822`：单端用例**不能靠"配对"豁免**，`case_ids` 是**逐 ID 校验**）。
   本包锚定的用例是 `PR-006`（**只在 mibao 可跑**）+ `PR-018`（双端可跑 → workflow 归 mibao 桶）
   ⇒ 派生 persona 矩阵 = `["mibao"]`，**xiaobu 腿根本不会被启动** ——
   这是"按命中的用例分桶派生 persona"（`#3653`）的既有语义，不是绕过守卫。
   前提（workflow 仍按 persona 分桶 + matrix 消费派生结果）由
   `TestWorkflowPersonaBucketingPremise` 锁住：premise 一变，本判据必须重新审视。

## 红证（不靠"补规则前的历史"，而是注入式 —— 与被测真值解耦，永远有效）

`TestCoverageCheckerActuallyFires` 用**注入样本**证明判据三段都活着，其中第一段注入的
正是"补规则前的真实行为"（无规则命中 → 兜底网）。另附**真实红证**：把本文件跑在补规则前的
`behavior_mapping.py` 上必红（见 PR body / issue #3837 的红证原文）。

## 已知边界（如实登记，不假装覆盖）

- 本表**只声明低库存口径**三个文件。`inventory_manage.py` 的 `query`/`adjust` 两条路径
  （`PR-004`/`PR-005`）**不在**声明内 —— 改那两条路径时本规则不构成覆盖。要补就加进
  `DECLARED_TOOL_FILE_COVERAGE` + `MAPPING_RULES`，本文件会强制它对上；
- `PR-002` 刻意**不入**（复核后排除）：它断言的是另一个枚举值 `stock_status: out_of_stock`
  （库存≤0），`product_search.py` 的该分支在 #3831 里一行未改，且其 `data_checks` 是
  `data.products.length >= 0`（恒真）。
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

# ══════════════════════════════════════════════════════════════════════════════
# 已声明的覆盖关系（本文件的核心事实：工具文件 → 触碰它后**必须**选中的用例）
# ══════════════════════════════════════════════════════════════════════════════
# 每条 = 文件路径 → (必须选中的用例, 依据)。依据必须带 issue/PR 号（`TestDeclaredCoverageRegistry`
# 会强制），否则下一个人无法判断"为什么是这个文件配这几条用例"。
DECLARED_TOOL_FILE_COVERAGE = {
    "backend/ai-agent-service/app/tools/stock_semantics.py": (
        ["PR-006", "PR-018"],
        "低库存口径的**单点来源**（issue #3783 / PR #3831）：`LOW_STOCK_THRESHOLD`、"
        "`low_stock_phrase`、`low_stock_alert_threshold_schema` 两工具共用 ⇒ 改它两条工具路径"
        "都可能变 ⇒ PR-006（inventory_manage 侧）与 PR-018（product_search 侧）都必须选中。",
    ),
    "backend/ai-agent-service/app/tools/product_search.py": (
        ["PR-018"],
        "`stock_status=low_stock` 分支的**显式承载用例**（PR-018 的期望就是 "
        "`product_search(stock_status=low_stock)`）。必须钉住 OR 的这一个分支（#3837）："
        "只锚 PR-006 时 `product_search` 单分支回归会被 `inventory_manage` 分支掩盖"
        "（PR-006 是 OR 断言）。",
    ),
    "backend/ai-agent-service/app/tools/inventory_manage.py": (
        ["PR-006"],
        "`action=low_stock_alert` 的**唯一**承载用例（PR-006 的 OR 分支之一）；"
        "PR #3831 的**真实行为变更**（不传 threshold 时默认 10→100）就在这条路径上。",
    ),
}

# 真实入口见证用的 diff：**PR #3831 的完整变更集**（改了低库存口径那一次，含用例/生成物文件）
PR_3831_CHANGED_FILES = [
    "backend/ai-agent-service/app/tools/inventory_manage.py",
    "backend/ai-agent-service/app/tools/product_search.py",
    "backend/ai-agent-service/app/tools/stock_semantics.py",
    ".github/cases/product.yml",
    "docs/testing/mibao-verification-cases.md",
    "tests/agent_eval/eval_cases.py",
]

# 低库存承载文件之外，**同类**的既有锚定文件（证明"每个工具文件的规则都还带得动用例"，
# 也是本守卫的对照样本：若将来某人把 MAPPING_RULES 里某条的用例清空，这里会一起红）。
CONTROL_ANCHORED_FILES = [
    "backend/ai-agent-service/app/tools/order_create.py",
    "backend/ai-agent-service/app/graph/skills/order_skill.py",
    "backend/ai-agent-service/app/tools/human_handoff.py",
]


# ══════════════════════════════════════════════════════════════════════════════
# 纯函数：缺口判定（注入式红证用 —— 与被测真值解耦）
# ══════════════════════════════════════════════════════════════════════════════
def declared_coverage_gaps(declared, mapping_fn):
    """已声明覆盖关系的缺口 → `[(path, missing_ids, source), ...]`（空列表 = 全对上）。

    判据 = *"改了这个文件，声明覆盖的用例**必须**被选中（且走有因果的规则桶）"*。
    两段都可被注入样本触发：① 用例没被选中；② 选中了但来源不是 `rules`（兜底网 = 无因果）。
    """
    gaps = []
    for path, (required, _why) in declared.items():
        selected, source = mapping_fn([path])
        missing = sorted(cid for cid in required if cid not in selected)
        if missing or source != "rules":
            gaps.append((path, missing, source))
    return gaps


def bucket_by_persona(ids, runnable_by_persona, personas=PERSONAS):
    """workflow map job 的分桶镜像 → `({persona: [case_id]}, [无人可跑的 case_id])`。

    唯一复述的是 workflow 那两行分桶规则（`owners = [p for p in ("mibao","xiaobu")
    if cid in runnable[p]]` → `owners[0]`）；premise 由
    `TestWorkflowPersonaBucketingPremise` 锁住（workflow 改了分桶口径这里必须同步）。
    """
    buckets, orphan = {}, []
    for cid in ids:
        owners = [p for p in personas if cid in runnable_by_persona.get(p, set())]
        if not owners:
            orphan.append(cid)
            continue
        buckets.setdefault(owners[0], []).append(cid)
    return buckets, orphan


def legs_that_cannot_resolve(buckets, runnable_by_persona):
    """**会启动的腿**里，哪些拿到了不属于本腿可跑集的 ID（⇒ runner `exit 1`）→ `{persona: [...]}`。

    空 dict = 没有任何腿会撞上 `禁止静默少跑`（`#3822`：`case_ids` 逐 ID 校验、配对不豁免）。
    """
    bad = {}
    for persona, cids in buckets.items():
        allowed = runnable_by_persona.get(persona, set())
        foreign = sorted(c for c in cids if c not in allowed)
        if foreign:
            bad[persona] = foreign
    return bad


# ══════════════════════════════════════════════════════════════════════════════
# 仓库真值装载
# ══════════════════════════════════════════════════════════════════════════════
def _case_dicts():
    return load_case_dicts(str(CASES_DIR))


def _runnable_by_persona(case_dicts=None):
    case_dicts = case_dicts if case_dicts is not None else _case_dicts()
    return {p: {str(c.get("id") or "") for c in select_cases_for_persona(case_dicts, p)}
            for p in PERSONAS}


def _skip_reasons(case_dicts=None):
    case_dicts = case_dicts if case_dicts is not None else _case_dicts()
    return {str(c.get("id") or ""): case_skip_reason(c) for c in case_dicts}


def _declared_case_ids():
    return sorted({cid for ids, _why in DECLARED_TOOL_FILE_COVERAGE.values() for cid in ids})


def _map_step_script():
    """取 `agent-behavior-eval.yml`「计算执行计划」步骤（id=map）的内联脚本正文。"""
    wf = yaml.safe_load(BEHAVIOR_EVAL_WORKFLOW.read_text(encoding="utf-8")) or {}
    for job in (wf.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if step.get("id") == "map":
                return step.get("run") or ""
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# A. 登记表自身（可解释 + 不过期 + 无空条目）
# ══════════════════════════════════════════════════════════════════════════════
class TestDeclaredCoverageRegistry:
    """已声明覆盖关系必须**可解释**、**不空**、**不过期**。"""

    @pytest.mark.parametrize("path", sorted(DECLARED_TOOL_FILE_COVERAGE))
    def test_declared_file_exists(self, path):
        """代表性路径必须真的存在（防退化成凭空的文件名 —— 那样守卫恒绿）。"""
        assert (REPO_ROOT / path).is_file(), (
            f"已声明覆盖关系的文件不存在：{path} —— 请更新 DECLARED_TOOL_FILE_COVERAGE"
            "（文件被删/改名后，本守卫会因'路径不存在'而失去判据）"
        )

    @pytest.mark.parametrize("path", sorted(DECLARED_TOOL_FILE_COVERAGE))
    def test_declared_entry_is_not_empty_and_cites_evidence(self, path):
        """每条声明都要带用例 + 可追溯依据（issue/PR 号），防退化成"魔数清单"。"""
        required, why = DECLARED_TOOL_FILE_COVERAGE[path]
        assert required, f"{path} 的声明集为空 —— 空条目 = 空断言，请删除该条或补用例"
        assert re.search(r"#\d+", why), (
            f"{path} 的依据没有可追溯引用（issue/PR 号）—— 现依据：{why!r}"
        )

    def test_declared_cases_exist_and_are_not_skipped(self):
        """陈旧即红：声明集里的用例必须存在于用例库，且 `skip_reason` 为空。

        `skip_reason` 非空 ⇒ 按 workflow 语义进 `unrunnable`（不是"少跑一条"，是**跑不到**），
        此时声明本身就是假的。
        """
        existing = {str(c.get("id") or "") for c in _case_dicts()}
        skips = _skip_reasons()
        missing = sorted(cid for cid in _declared_case_ids() if cid not in existing)
        skipped = sorted(cid for cid in _declared_case_ids() if skips.get(cid, ""))
        assert missing == [], (
            f"声明集里的用例不在 `.github/cases/` 中：{missing} —— 用例被删/改名后必须同步声明表"
        )
        assert skipped == [], (
            f"声明集里的用例 `skip_reason` 非空（任何 persona 都跑不到）：{[ (c, skips[c]) for c in skipped ]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# B. 核心守卫：改了这个文件 → 声明的用例必须被选中
# ══════════════════════════════════════════════════════════════════════════════
class TestDeclaredCoverageIsSelected:
    """本文件的核心产出：覆盖面**无声缩水**必红（issue #3837 的病根形态）。"""

    def test_no_declared_coverage_gap(self):
        gaps = declared_coverage_gaps(DECLARED_TOOL_FILE_COVERAGE,
                                      map_changed_files_with_source)
        assert gaps == [], (
            "以下工具文件「被改后选中的用例」与**已声明的覆盖关系**不一致"
            "（= 改了它却跑不到声明覆盖的用例，静默少跑）：\n"
            + "\n".join(f"  · {p}：未选中 {missing}（映射来源={source}）"
                        for p, missing, source in gaps)
            + "\n修法：在 `MAPPING_RULES` 里给该文件补/修规则（来源必须是 `rules` —— "
              "兜底网与本文件改动无因果），或修正 DECLARED_TOOL_FILE_COVERAGE。见 issue #3837。"
        )

    def test_lowstock_rule_is_anchored_to_rules_bucket_not_the_net(self):
        """低库存用例**不得**只活在兜底网里（兜底网 = 只报告、与改动无因果、不开 issue）。

        `#3837` 的病根正是"低库存用例在映射表里不存在" ⇒ 这里把"来源必须是 rules"钉死在
        低库存域上：谁把这条规则删了/挪回兜底网，本测试就红。
        """
        case_ids, source = map_changed_files_with_source(
            ["backend/ai-agent-service/app/tools/stock_semantics.py"])
        assert source == "rules", (
            f"改低库存单点来源却落到 `{source}`（应为 `rules`）—— case_ids={case_ids}。"
            "兜底网与本改动无因果（失败连 issue 都不开）= 回到 issue #3837 的病根。"
        )
        assert set(case_ids) >= set(_declared_case_ids()), (
            f"低库存域选中的用例 {case_ids} 未覆盖已声明集 {_declared_case_ids()}"
        )

    def test_pr3831_real_diff_witness(self):
        """真实入口见证：PR #3831 的**完整变更集**（含用例/生成物文件）必须选中低库存用例。

        为什么用完整变更集（而不是只喂 `app/` 下的三个文件）：真实 PR 的 diff 里混着
        `.github/cases/**`、生成物等路径，而规则桶的作用域被收窄到 `BEHAVIOR_SOURCE_PREFIXES`
        （`#3551`）—— 只有"混着也不会漏"才算真的修好。
        """
        case_ids, source = map_changed_files_with_source(PR_3831_CHANGED_FILES)
        assert (source, sorted(case_ids)) == ("rules", ["PR-006", "PR-018"]), (
            f"复算 PR #3831 变更集得到 source={source}, case_ids={case_ids} —— "
            "期望 ('rules', ['PR-006', 'PR-018'])。这就是本守卫要防的形态："
            "改了低库存口径，门禁一条低库存用例都没跑。"
        )

    @pytest.mark.parametrize("path", CONTROL_ANCHORED_FILES)
    def test_control_anchored_files_still_bring_cases(self, path):
        """对照样本：既有的工具锚定文件仍必须带出（非空）用例集且来源为 `rules`。

        防"为了修本包而顺手把规则表改空/改窄"这类全局性退化。
        """
        case_ids, source = map_changed_files_with_source([path])
        assert source == "rules" and case_ids, (
            f"{path} 的规则锚定失效（source={source}, case_ids={case_ids}）—— "
            "该文件本就是规则桶成员，它掉出规则桶说明映射表被改窄了"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C. 「在映射结果里」≠「会真的跑」：调度可达性 + persona 相容
# ══════════════════════════════════════════════════════════════════════════════
class TestDeclaredCoverageIsActuallyDispatched:
    """声明集必须**真能被调度**（persona 过滤 / skip / 空桶都会让它消失）。"""

    @pytest.mark.parametrize("case_id", _declared_case_ids())
    def test_declared_case_is_schedulable_in_some_persona(self, case_id):
        runnable = _runnable_by_persona()
        owners = [p for p in PERSONAS if case_id in runnable[p]]
        assert owners, (
            f"{case_id} 没有任何 persona 能调度它（会进 workflow 的 `unrunnable` 名单）—— "
            "它就算在规则桶里也永远不会执行 = 空覆盖。"
        )

    def test_no_declared_file_leaves_an_orphan_case(self):
        """入口见证：通过**每个已声明文件的真实 diff** 走到底，不能产生 `unrunnable` 条目。"""
        runnable = _runnable_by_persona()
        for path in DECLARED_TOOL_FILE_COVERAGE:
            case_ids, _source = map_changed_files_with_source([path])
            buckets, orphan = bucket_by_persona(case_ids, runnable)
            assert orphan == [], (
                f"改 {path} 映射出的 {orphan} 不属于任何 persona 的可跑集 —— "
                "workflow 的 `unrunnable` 名单会披露它们，但**不会执行**（= 声明的覆盖是假的）"
            )
            assert buckets, f"改 {path} 分桶后为空（映射结果 {case_ids}）—— 没有任何腿会启动"

    def test_declared_case_lands_in_a_real_bucket(self):
        """每条声明用例都要在**它自己文件的入口**下落进一个真实 (persona) 桶。"""
        runnable = _runnable_by_persona()
        for path, (required, _why) in DECLARED_TOOL_FILE_COVERAGE.items():
            case_ids, _source = map_changed_files_with_source([path])
            buckets, _orphan = bucket_by_persona(case_ids, runnable)
            dispatched = {cid for cids in buckets.values() for cid in cids}
            missing = sorted(cid for cid in required if cid not in dispatched)
            assert missing == [], (
                f"改 {path} 时声明覆盖的 {missing} 没有落进任何执行桶"
                f"（桶内容：{buckets}）—— 门禁不会真的跑它们"
            )

    def test_no_started_leg_would_exit_1_on_the_declared_diffs(self):
        """**persona 陷阱守卫**：本包锚定的 diff 不能让任何一条会启动的腿拿不到 ID。

        `local_runner` 对 `--case-ids` 是**逐 ID 校验**，任一 ID 不在该腿 persona 过滤集内就
        `sys.exit(1)`（`禁止静默少跑`，见 `#3822`：单端用例不能靠"配对"豁免）。故本包
        「B 端专属用例（PR-006）进了规则桶」必须**同时**满足：派生出的腿拿到的 ID 全在
        本腿可跑集内。修前那种"把并集无差别喂给两条腿"的写法会在这里红。
        """
        runnable = _runnable_by_persona()
        diffs = dict(DECLARED_TOOL_FILE_COVERAGE)
        diffs["PR #3831 完整变更集"] = (PR_3831_CHANGED_FILES, "")
        # 跨端混改（低库存 + 交互卡）：双腿都会启动 ⇒ 双腿都必须干净
        diffs["低库存 + 交互卡（跨端）"] = (
            ["backend/ai-agent-service/app/tools/stock_semantics.py",
             "backend/ai-agent-service/app/graph/interact.py"], "")
        bad_report = []
        for name, (paths, _why) in diffs.items():
            case_ids, _source = map_changed_files_with_source(paths)
            buckets, _orphan = bucket_by_persona(case_ids, runnable)
            bad = legs_that_cannot_resolve(buckets, runnable)
            if bad:
                bad_report.append(f"{name}: {bad}（桶内容 {buckets}）")
        assert bad_report == [], (
            "以下 diff 会让某条会启动的腿拿到不属于本腿的用例 ID ⇒ 该腿 "
            "`local_runner` 直接 `exit 1`（禁止静默少跑，见 #3822）：\n  "
            + "\n  ".join(bad_report)
        )

    def test_derived_personas_for_lowstock_diff_is_mibao_only(self):
        """低库存 diff 派生出的 persona 矩阵 = `["mibao"]`（xiaobu 腿不启动 = 不可能是"红腿"）。

        这是"**为什么本包不需要给 C 端配一条对位用例**"的机器证据（`#3653`：persona 从分桶
        派生，单 persona 命中只起一套栈）。⚠️ 它锁的是**派生结果**，不是"双端用例必须归 mibao"
        这条规则本身（后者由 `TestWorkflowPersonaBucketingPremise` 的 premise 锚点承担）。
        """
        runnable = _runnable_by_persona()
        case_ids, _source = map_changed_files_with_source(
            ["backend/ai-agent-service/app/tools/inventory_manage.py"])
        buckets, _orphan = bucket_by_persona(case_ids, runnable)
        assert sorted(buckets) == ["mibao"], (
            f"低库存 diff 的 persona 分桶为 {sorted(buckets)}（桶内容 {buckets}）—— "
            "期望只有 mibao（PR-006 仅 mibao 可跑；PR-018 双端可跑但按 owners[0] 归 mibao）。"
            "若 PR-018 变成 xiaobu 专属/被 skip，请重新审视本包的 persona 相容性结论。"
        )


class TestWorkflowPersonaBucketingPremise:
    """premise 守卫：上面那条"persona 相容"结论**依赖 workflow 的既有分桶语义**。

    workflow 一旦改成"把映射并集无差别喂给两条腿"（`#3822` 的朴素修法），
    `PR-006` 就会让 xiaobu 腿 `exit 1` —— 那时本包的规则需要重新设计（或改为登记缺口）。
    故把 premise 钉在这里：premise 变 ⇒ 本文件红 ⇒ 必须重新审视。
    """

    def test_map_step_buckets_per_persona(self):
        script = _map_step_script()
        assert script, "找不到 agent-behavior-eval.yml 的 map 步骤内联脚本（premise 失效）"
        for anchor in ('owners[0]', "select_cases_for_persona", "personas.append"):
            assert anchor in script, (
                f"map job 的分桶实现里找不到 {anchor!r} —— 「按 persona 分桶派生腿」的 premise 变了；"
                "本文件的 persona 相容性断言（test_no_started_leg_would_exit_1…）必须重新设计。"
            )

    def test_eval_matrix_consumes_derived_personas(self):
        wf = yaml.safe_load(BEHAVIOR_EVAL_WORKFLOW.read_text(encoding="utf-8")) or {}
        be = (wf.get("jobs") or {}).get("behavior-eval") or {}
        matrix_expr = str((be.get("strategy") or {}).get("matrix") or "")
        assert "needs.map.outputs.personas" in matrix_expr and "fromJSON" in matrix_expr, (
            f"behavior-eval 的 matrix 未消费 map 派生的 personas（{matrix_expr!r}）—— "
            "写死双端会让 PR-006 必然弄红 xiaobu 腿（#3822 形态），本包结论失效"
        )


# ══════════════════════════════════════════════════════════════════════════════
# D. 注入式红证（`migao-acceptance`：不会红的断言 = 空断言）
# ══════════════════════════════════════════════════════════════════════════════
class TestCoverageCheckerActuallyFires:
    """证明上面三条判据**都会红**（用注入样本，不依赖仓库当下真值，永远有效）。"""

    def test_fires_when_no_rule_selects_the_declared_cases(self):
        """判据 ① 的核心形态：**补规则前的真实行为**（无规则命中 → 兜底网）。

        注入样本 = `#3831` 修前的映射行为（`("default_net", DEFAULT_BEHAVIOR_CASES)`）。
        """
        prefix_behavior = lambda _paths: (list(DEFAULT_BEHAVIOR_CASES), "default_net")  # noqa: E731
        gaps = declared_coverage_gaps(DECLARED_TOOL_FILE_COVERAGE, prefix_behavior)
        assert len(gaps) == len(DECLARED_TOOL_FILE_COVERAGE), (
            f"补规则前的映射行为应让**每个**已声明文件都报缺口，实测 {gaps}"
        )
        for path, missing, source in gaps:
            assert missing == sorted(DECLARED_TOOL_FILE_COVERAGE[path][0]), (
                f"{path} 的缺口用例集不对：{missing}"
            )
            assert source == "default_net"

    def test_fires_when_rule_exists_but_selects_the_wrong_case(self):
        """判据 ① 的第二形态：规则在，但**选中的用例不是声明覆盖的那些**。"""
        wrong = lambda _paths: (["PR-002"], "rules")  # noqa: E731
        gaps = declared_coverage_gaps(
            {"backend/ai-agent-service/app/tools/inventory_manage.py": (["PR-006"], "")}, wrong)
        assert gaps == [("backend/ai-agent-service/app/tools/inventory_manage.py",
                         ["PR-006"], "rules")], f"选中错用例未报缺口：{gaps}"

    def test_fires_when_case_happens_to_live_in_the_default_net(self):
        """判据 ① 的第三形态：用例**恰好在兜底网里**（ID 对上了）但来源不是 `rules`。

        这正是"最容易骗过守卫"的形态：只看"ID 在不在结果里"会判绿，而改动的因果性
        （报告制 vs 强信号 + 自动开 issue）其实已经丢了 ⇒ 必须按 `source` 一起判。
        """
        net_behavior = lambda _paths: (["PR-006"], "default_net")  # noqa: E731
        gaps = declared_coverage_gaps(
            {"backend/ai-agent-service/app/tools/inventory_manage.py": (["PR-006"], "")},
            net_behavior)
        assert gaps == [("backend/ai-agent-service/app/tools/inventory_manage.py", [],
                         "default_net")], f"来源非 rules 却未报缺口：{gaps}"

    def test_fires_when_a_started_leg_gets_a_foreign_case_id(self):
        """判据 ③：把映射并集**无差别**喂给两条腿 → `PR-006` 落到 xiaobu 腿 ⇒ 必红。

        这条注入样本就是 `#3822` 的真实形态（run 34907040543：`OR-013` 让 xiaobu 腿 `exit 1`）。
        """
        runnable = {"mibao": {"PR-006", "PR-018"}, "xiaobu": {"CH-010", "PR-018"}}
        bad = legs_that_cannot_resolve({"mibao": sorted(runnable["mibao"]),
                                        "xiaobu": ["CH-010", "PR-006"]}, runnable)
        assert bad == {"xiaobu": ["PR-006"]}, (
            f"无差别双端喂 ID 未被判红：{bad} —— 该守卫必须能报出 #3822 的形态"
        )
        # 反向：本包的真实形态（PR-006/PR-018 都落 mibao 桶）必须是干净的
        buckets, orphan = bucket_by_persona(["PR-006", "PR-018"], runnable)
        assert (buckets, orphan) == ({"mibao": ["PR-006", "PR-018"]}, [])
        assert legs_that_cannot_resolve(buckets, runnable) == {}

    def test_fires_when_a_case_is_unrunnable_in_every_persona(self):
        """判据 ②：在规则桶里但没有任何 persona 能调度 → 必须判红（不是"少跑"，是"跑不到"）。"""
        runnable = {"mibao": {"PR-018"}, "xiaobu": {"CH-010"}}
        _buckets, orphan = bucket_by_persona(["PR-006", "PR-018"], runnable)
        assert orphan == ["PR-006"], f"无人可跑的用例未被识别：{orphan}"
