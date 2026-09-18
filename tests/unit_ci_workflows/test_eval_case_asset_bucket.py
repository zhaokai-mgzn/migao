# case_ids: MC-012, PR-016
"""`precondition_not_applied` 型失败单列 `case_asset_failures` 桶（issue #4245）—— 红证。

## 症状（值级证据，判定 run 35295494688 @d5bca241）

`PR-016` 本次 `score=0.0`，其 failure 原文里 runner **自己写着**「本次红/绿**不可归因于
agent 行为**」（`precondition[product_count_for_keyword]: 前置在本次运行期间漂移 …`），
但它的分桶结果是 `deterministic_failures` —— 那是"agent/产品的**确定性回归**"清单。
⇒ 每个读到它的人都会去查 agent 行为，而 runner 已断言这条红与 agent 无关
（同族：`migao-acceptance`「归因强度必须匹配证据强度」/「无归因的红是待归因项」）。
`PR-008` 同类落 `systemic_recurrence`（跨 run 复发），同属归因错层。

## 判据（三条，改前/注入后各有红证）

| # | 断言 | 红证 |
|---|---|---|
| ① | 前置不成立 ⇒ 落 `case_asset_failures`，且 `deterministic_failures == []` | 改前落 `deterministic_failures`（本文件 `KeyError: 'case_asset_failures'`） |
| ② | 反向：`score<1` 但**无**前置失败 ⇒ 仍落 `deterministic_failures` | 注入"把失败一律读成用例资产缺陷"⇒ 本断言红（防改过头把真回归洗白） |
| ③ | `ok` 仍为 `False`（**阻塞强度不变**），且空结果分支键集合一致 | 注入"把单列当放行"（`ok` 里去掉该桶）⇒ 本断言红 |

## 范式（沿用 #3803，不造第二套判据）

`harness_incompatible`（#3803）的范式 = **结构化事实字段**（随结果落盘）
→ 判定层**单列一桶** → 在 `deterministic` 链上**不重复计入**。
本文件与 `test_eval_auto_respond_l0.py::test_completion_verdict_separates_harness_failures_from_agent_failures`
逐条同形；族身份锚定既有原子（`_failure_atom` 的
`precondition_not_applied(declared:…)` / `precondition_not_applied(pre_clean)`），
**不新增判据**（前置的判据与 `max_growth` 语义属 #4200/#3835，本单不动）。

## 为什么用单测

`completion_verdict` / `precondition_not_applied_fact` / `write_summary_json` 都是
**纯函数**（吃 results 列表），零 LLM / 零网络（`migao-dev-flow` §16.1：能下层不上层）。
⚠️ 本目录在 CI 只 `pip install pytest pyyaml`（`.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 用下方最小替身（与
`test_eval_summary_attribution.py` 同形）。
"""
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()

# ── 夹具：**照生产原文构造**（不手抄 —— 由 `check_precondition_drift` 本人生成）────────
# PR-016 的形态：`product_count_for_keyword` 在本次运行期间从 0 漂到 1（并行用例建的）。
DRIFT_SRC = "E2E建品流程样品帘"
DRIFT_KEY = f"product_count_for_keyword:{DRIFT_SRC}"
DRIFT_SPEC = [{"type": "product_count_for_keyword", "source": DRIFT_SRC}]


def _drift_issue() -> str:
    """运行期前置漂移的**断言级原文**（PR-016 / run 35295494688 的形态）。"""
    issues = lr.check_precondition_drift(DRIFT_SPEC, {DRIFT_KEY: 0}, {DRIFT_KEY: 1})
    assert len(issues) == 1, f"夹具没造出漂移问题串：{issues}"
    return issues[0]


def _preclean_issue() -> str:
    """同族另一支：夹具层前置**未应用**（`PR-008` 的形态）。"""
    return f"{lr._PRECONDITION_NOT_APPLIED}: 员工「王五」查询 3 次未命中"


def _r(cid, score=0.0, classification="reproducible", **kw):
    """一个用例结果（`run_case` 返回值里判定/序列化用到的字段）。"""
    base = {"case_id": cid, "score": score, "classification": classification,
            "failed": [], "pre_clean": []}
    base.update(kw)
    return base


def _precond_r(cid, issue, **kw):
    """照**生产形态**构造：同一条原文**既**进 `failed`（断言级可读原因）**又**进结构化事实
    （`_run_one_case` 的收尾块就是这么写的：`failed` 来自 `_issues`/`_pre_clean_bad`，
    事实由 `precondition_not_applied_fact` 从同一处折出）。"""
    return _r(cid, 0.0, "reproducible",
              failed=[(issue, lr._CASE_LEVEL_DETAIL)],
              precondition_not_applied=[issue], **kw)


def _recurring(r, fingerprint):
    r["cross_run_recurrence"] = {"case_id": r["case_id"], "fingerprint": fingerprint,
                                 "prior_runs": ["35295494688"], "prior_count": 1}
    return r


# ── ⓪ 夹具真实性与族身份（前置断言：证明下面的红/绿不是在测一个空夹具）──────────

def test_fixtures_are_the_real_family_members():
    """两支夹具都必须**折成既有原子** `precondition_not_applied(...)`。

    这是"不造第二套判据"的证据：本桶锚定的是 `_failure_signature` 里**已经存在**的族
    （#3781/#3835 落码），新加的只是"把这族从 agent 回归清单里分出来"。
    夹具若漂成别的原子（例如折进 `no_success(...)`），下面的桶断言就变成了空断言。
    """
    drift, pre = _drift_issue(), _preclean_issue()
    assert drift.startswith("precondition[product_count_for_keyword]"), drift
    assert "不可归因于 agent 行为" in drift, drift
    assert lr._failure_atom(drift, lr._CASE_LEVEL_DETAIL) == \
        "precondition_not_applied(declared:product_count_for_keyword)", \
        f"漂移族没折成前置原子：{lr._failure_atom(drift, lr._CASE_LEVEL_DETAIL)!r}"
    assert lr._failure_atom(pre, lr._CASE_LEVEL_DETAIL) == \
        "precondition_not_applied(pre_clean)", \
        f"pre_clean 族没折成前置原子：{lr._failure_atom(pre, lr._CASE_LEVEL_DETAIL)!r}"


# ── ① 结构化事实的提取（runner 侧生产方；两支同族，复位族不得被吞进来）──────────

class TestFactExtraction:
    """`precondition_not_applied_fact` —— 判定层读的**唯一**结构化来源。

    §20 R5 第 1 条形态（"声明无消费"）的镜像：只有生产方真的写、消费方真的读，
    这个桶才不是恒空字段。
    """

    def test_both_family_members_are_collected(self):
        drift, pre = _drift_issue(), _preclean_issue()
        assert lr.precondition_not_applied_fact({}, []) == [], "空输入产出了非空事实（假信号）"
        assert lr.precondition_not_applied_fact({}, [pre]) == [pre]
        assert lr.precondition_not_applied_fact({"precondition_check": drift}, []) == [drift]
        assert lr.precondition_not_applied_fact(
            {"precondition_check": drift}, [pre]) == [pre, drift]

    def test_restore_family_is_not_swallowed(self):
        """**反向**：`PRECONDITION_NOT_RESTORED`（复位族）不属于本族 —— 它有自己的桶
        （`restore_failures`）。吞进来会把"共享状态没归零"洗成"用例资产缺陷"。"""
        restore = {"precondition": "PRECONDITION_NOT_RESTORED: 共享状态复位未生效（…）"}
        assert lr.precondition_not_applied_fact(restore, []) == []

    def test_runner_actually_writes_the_fact_field(self):
        """静态接线守卫：`_run_one_case` 必须真的把事实写进结果。

        为什么必须锁这一格：纯函数层全绿也可以"字段永远为空"（生产方没接上）——
        那正是本仓反复踩的"声明无消费"形态。静态断言与
        `test_eval_summary_attribution.py::test_runner_actually_records_and_passes_timings`
        同形（`_run_one_case` 是 `run_suite` 内的闭包，L0 层无法直接调用）。
        """
        src = RUNNER_PATH.read_text(encoding="utf-8")
        assert "precondition_not_applied_fact(" in src, (
            "结构化事实没有生产方 —— `case_asset_failures` 会恒空（假功能）")
        assert 'r["precondition_not_applied"]' in src, (
            "事实没写进结果 dict —— 判定层读不到（声明无消费）")


# ── ② 分桶：前置不成立 ⇒ case_asset_failures（不再进 deterministic/systemic）──────

class TestPreconditionNotAppliedIsCaseAssetNotAgentRegression:

    def test_drift_failure_lands_in_case_asset_bucket(self):
        """① `PR-016` 形态：漂移失败 ⇒ `case_asset_failures`，`deterministic_failures` 为空。"""
        v = lr.completion_verdict([_r("PR-016", precondition_not_applied=[_drift_issue()])], ())
        assert v["deterministic_failures"] == [], (
            f"前置不成立仍被计进『agent/产品的确定性回归』—— 归因继续指错人：{v}")
        assert v["case_asset_failures"] == ["PR-016"], v
        assert v["systemic_recurrence"] == [] and v["journey_failures"] == [], v
        assert v["total"] == 1 and v["passed"] == 0, v

    def test_preclean_family_lands_in_the_same_bucket(self):
        """同族另一支（夹具层前置未应用）必须进**同一个**桶，不另开第三桶。"""
        v = lr.completion_verdict([_r("PR-008", precondition_not_applied=[_preclean_issue()])], ())
        assert v["case_asset_failures"] == ["PR-008"], v
        assert v["deterministic_failures"] == [], v

    def test_recurring_precondition_is_not_a_systemic_recurrence(self):
        """`PR-008` 的真实形态：前置失败**跨 run 复发** ⇒ 仍归"用例资产"，
        不得折进 `systemic_recurrence`（那桶语义是"agent/产品 × 跨 run 复发"）。"""
        r = _recurring(_r("PR-008", precondition_not_applied=[_preclean_issue()]),
                       "precondition_not_applied(pre_clean)")
        v = lr.completion_verdict([r], ())
        assert v["systemic_recurrence"] == [], (
            f"前置失败被折进『跨 run 复发的系统性缺口』—— 归因指向 agent/产品：{v}")
        assert v["case_asset_failures"] == ["PR-008"], v

    def test_journey_precondition_is_not_a_journey_failure(self):
        """关键旅程里的前置失败同样**只**归"用例资产"：旅程没失败，是靶子没成立。"""
        journey = lr.KEY_JOURNEYS_MIBAO[0]
        v = lr.completion_verdict(
            [_r(journey, precondition_not_applied=[_drift_issue()])], lr.KEY_JOURNEYS_MIBAO)
        assert v["journey_failures"] == [], v
        assert v["case_asset_failures"] == [journey], v

    def test_reason_groups_case_asset_apart_from_required_failures(self):
        """`reason` 文案必须把两件事**分组**：必须处理的失败 vs 用例资产缺陷。"""
        v = lr.completion_verdict([_r("PR-016", precondition_not_applied=[_drift_issue()])], ())
        assert "用例资产缺陷" in v["reason"], v["reason"]
        assert "不可归因于 agent" in v["reason"], v["reason"]
        assert "必须处理的失败" not in v["reason"], (
            f"用例资产缺陷被算进『必须处理的失败』—— 文案与分桶自相矛盾：{v['reason']}")


# ── ③ 阻塞强度不变（单列 ≠ 放行）+ 反向（真回归不得被洗白）──────────────────────

class TestBlockingStrengthUnchanged:

    def test_single_listing_still_blocks_ok(self):
        """③ 前置不成立 ⇒ 该用例红/绿**无判别力** ⇒ 结论不可用 ⇒ `ok` 必须仍为 False。"""
        v = lr.completion_verdict([_r("PR-016", precondition_not_applied=[_drift_issue()])], ())
        assert v["case_asset_failures"] == ["PR-016"], v
        assert v["ok"] is False, (
            "单列桶被当成放行 —— 前置不成立时该用例的红/绿无判别力，结论不可用（禁止放宽）")

    def test_mixed_run_blocks_on_both_kinds(self):
        """一条前置失败 + 一条真回归 ⇒ 两个桶各归各的，且都阻塞。"""
        v = lr.completion_verdict([
            _r("PR-016", precondition_not_applied=[_drift_issue()]),
            _r("OR-014", 0.0, "reproducible",
               failed=[("must_succeed: order_create 从未被调用", "case-level check")]),
        ], ())
        assert v["case_asset_failures"] == ["PR-016"], v
        assert v["deterministic_failures"] == ["OR-014"], v
        assert v["ok"] is False, v

    def test_real_regression_without_precondition_stays_deterministic(self):
        """② **反向**：`score<1` 但**无**前置失败 ⇒ 仍落 `deterministic_failures`。

        防"改过头"：把真回归洗成"用例资产缺陷"等于把阻塞理由写错（虽然仍阻塞），
        下一个人会去改用例而不是改产品。
        """
        v = lr.completion_verdict([_r("OR-014", 0.0, "reproducible",
                                      failed=[("must_succeed: order_create 从未被调用",
                                               "case-level check")])], ())
        assert v["deterministic_failures"] == ["OR-014"], v
        assert v["case_asset_failures"] == [], (
            f"真回归被洗成用例资产缺陷 —— 归因反向指错人：{v}")
        assert v["ok"] is False, v

    def test_empty_results_branch_has_the_same_key_set(self):
        """空结果分支（环境/登录失败）必须补齐新键 —— 消费者按**固定键集**读。

        判据不是"看起来有"，而是与正常分支的键集合**逐键相等**（新桶只加一处即红）。
        """
        empty = lr.completion_verdict([], ())
        normal = lr.completion_verdict([_r("KN-001", 1.0, "pass")], ())
        assert empty["case_asset_failures"] == [], empty
        assert set(empty) == set(normal), (
            f"空结果分支与正常分支的键集合不一致：{sorted(set(normal) ^ set(empty))}")
        assert empty["ok"] is False, "零用例被放行（假绿）"


# ── ④ 消费方同步：artifact 落盘 + failure_reasons ──────────────────────────────

class TestSummaryConsumers:

    def _summary(self, tmp_path, results):
        out = tmp_path / "eval-summary.json"
        lr.write_summary_json(str(out), "post-deploy", "", results)
        return json.loads(out.read_text(encoding="utf-8"))

    def test_case_entry_and_reason_map_carry_the_fact(self, tmp_path):
        """结构化事实随 artifact 落盘 + `failure_reasons` 给出"为什么"。

        缺任一条：结论档只给一串 ID，归因又要回去翻有保留期的 job 日志
        （`migao-acceptance` L1「失败可归因」）。
        """
        drift = _drift_issue()
        data = self._summary(tmp_path, [_precond_r("PR-016", drift)])
        assert data["cases"][0]["precondition_not_applied"] == [drift], (
            f"结构化事实没随 artifact 落盘：{data['cases'][0]}")
        assert data["completion"]["case_asset_failures"] == ["PR-016"], data["completion"]
        assert "PR-016" in data["completion"]["failure_reasons"], (
            f"『为什么』没进 failure_reasons：{data['completion'].get('failure_reasons')}")
        assert data["completion"]["failure_reasons"]["PR-016"].startswith(
            "precondition[product_count_for_keyword]"), data["completion"]["failure_reasons"]

    def test_passing_case_does_not_grow_the_entry(self, tmp_path):
        """**无噪音**：不属该族的用例条目不得多出这个键（同 `failures`/`harness_incompatible`）。"""
        data = self._summary(tmp_path, [_r("KN-001", 1.0, "pass")])
        assert "precondition_not_applied" not in data["cases"][0], data["cases"][0]
        assert data["completion"]["case_asset_failures"] == [], data["completion"]
