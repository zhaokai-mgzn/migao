# case_ids: MC-012
"""结论档「阻塞条目」按两类分组（issue #4207）—— 红证。

## 症状（值级证据，判定 run 35295494688 @d5bca241）

| 腿 | total/passed | 阻塞桶 | 「未通过」清单 |
|---|---|---|---|
| mibao | 87 / **79** | det 3 + systemic 6 | 列了 **8** 条 |
| xiaobu | 36 / **33** | det **0** + systemic **5** | 列了 **3** 条 |

`systemic` 桶里的 `AS-007`（mibao）、`OR-021`/`OR-023`（xiaobu）**`score=1.0`**
（首败 + 重试通过）—— 它们在 `passed` 计数里、**也不在失败清单里**，却阻塞 `completion.ok`。
⇒ 结论档/issue 的「未通过」清单把两类东西混在一起：① 真失败（score<1）
② **通过但被 fail-closed 阻塞**（score=1）。读者按"未通过清单"数条数会**系统性少算**
（xiaobu 腿少算 2 条：列 3 条、实为 5 条阻塞）。

**本单不动判定口径**：`_is_recurring` 先于分类/旅程守卫是 #3806 的**有意 fail-closed**，
只修**读法/报告**（`ok` 的表达式、`_COMPLETION_RELEASED_CLASSES`、`case_asset_failures`
语义一字不动）。

## 判据（每条都有红证）

| # | 断言 | 红证 |
|---|---|---|
| ① | `score=1.0 + cross_run_recurrence` ⇒ 落 **第二组**（`blocked_but_passed`），**不**落 `must_fix_failures`；`reason` 里带「通过但被 fail-closed 阻塞（跨 run 复发，score=1）」 | 改前本文件必红（`KeyError: 'must_fix_failures'`）；注入"按桶不按 score 分组"⇒ 落第一组 |
| ② | **反向**：`score<1` 的真失败 ⇒ 仍落第一组（`must_fix_failures`） | 注入"一律读成通过但阻塞"⇒ 本断言红 |
| ③ | `ok` 的阻塞语义**不变**：新字段不得让任何阻塞条目变成放行 | 注入"把第二组当放行"（`ok` 里排除它）⇒ 本断言红 |
| ④ | 计数关系可读：`阻塞条目共 N 条（failed=… + 通过但被阻塞=… + 用例资产=…）` —— 「passed + failed ≠ 阻塞数」不再被当成 bug | 同上（改前 reason 无该句） |
| ⑤ | summary JSON 的 `completion` 带**结构化**两组（下游 issue 渲染器不必再推导） | 改前无该键 |
| ⑥ | `case_asset_failures`（#4245）**不**折进第一组，文案契约不变 | 注入"把用例资产算进必须处理的失败"⇒ 本断言红 |

## 为什么用单测

`completion_verdict` / `blocking_groups` / `write_summary_json` 都是**纯函数**
（吃 results 列表），零 LLM / 零网络（`migao-dev-flow` §16.1：能下层不上层）。
⚠️ 本目录在 CI 只 `pip install pytest pyyaml`（`.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 用下方最小替身（与
`test_eval_summary_attribution.py` 同形）。
"""
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
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

# 本 PR 新增的两个结构化字段名（下游渲染器按名读；改名即视为破坏契约）
MUST_FIX_KEY = "must_fix_failures"
BLOCKED_KEY = "blocked_but_passed"


# ── fixtures ────────────────────────────────────────────────────────────────

def _r(cid, score=0.0, classification="reproducible", **kw):
    """一个用例结果（`run_case` 返回值里判定/序列化用到的字段）。"""
    base = {"case_id": cid, "score": score, "classification": classification,
            "failed": [], "pre_clean": []}
    base.update(kw)
    return base


def _recurring(r, prior=1):
    """跨 run 复发标注（#3806）：同一首跑指纹在历史 run 出现过 ⇒ 不按波动放行。

    真实形态（run 35295494688）：`AS-007` / `OR-021` / `OR-023` **首败 + 重试通过**
    ⇒ `score=1.0` + `flake_released=True` + `cross_run_recurrence.prior_count=1`。
    """
    r["cross_run_recurrence"] = {"case_id": r["case_id"],
                                 "fingerprint": f"fp({r['case_id']})",
                                 "prior_runs": ["35295494688"], "prior_count": prior}
    return r


def _precond_r(cid):
    """`precondition_not_applied` 族夹具（#4245）：原文自带"不可归因于 agent 行为"。"""
    issue = (f"precondition[product_count_for_keyword]: 前置在本次运行期间漂移 —— "
             f"本次红/绿不可归因于 agent 行为")
    return _r(cid, 0.0, "reproducible",
              failed=[(issue, lr._CASE_LEVEL_DETAIL)],
              precondition_not_applied=[issue])


def _leg_xiaobu():
    """`35295494688` xiaobu 腿的形态：det **0** + systemic **5**（其中 2 条 `score=1.0`）。"""
    return [
        _r("OR-011", 0.0, "reproducible"),
        _r("OR-013", 0.0, "unstable"),
        _r("OR-018", 0.0, "no-retry-budget"),
        _recurring(_r("OR-021", 1.0, "llm-noise", flake_released=True)),
        _recurring(_r("OR-023", 1.0, "llm-noise", flake_released=True)),
    ]


def _write(tmp_path, results):
    out = tmp_path / "eval-summary.json"
    lr.write_summary_json(str(out), "post-deploy", "", results)
    return json.loads(out.read_text(encoding="utf-8"))


# ── ① 通过但被 fail-closed 阻塞 ⇒ 第二组（不是"未通过"）───────────────────────

class TestPassedButBlockedGoesToTheSecondGroup:

    def test_score_one_recurrence_is_the_second_group(self):
        """`AS-007` 的真实形态（mibao 关键旅程 + `score=1.0` + 跨 run 复发）。

        它在 `passed` 计数里、也不在失败清单里 —— 却阻塞 `ok`。旧读法把它从"未通过清单"
        里整个丢掉 ⇒ 条数被少算。
        """
        results = [_recurring(_r("AS-007", 1.0, "llm-noise", flake_released=True))]
        v = lr.completion_verdict(results, lr.KEY_JOURNEYS_MIBAO)
        g = lr.blocking_groups(results, v)
        assert g[MUST_FIX_KEY] == [], (
            f"`score=1.0` 的阻塞条目被算进『必须处理的失败』—— 那正是 #4207 的病：{g}")
        assert g[BLOCKED_KEY] == ["AS-007"], g
        assert v["ok"] is False, "夹具没触发阻塞（本组断言会退化成空断言）"
        assert v["passed"] == 1, "夹具与真实形态不符：该条目应在 passed 计数里"
        assert lr.BLOCKED_BUT_PASSED_LABEL in v["reason"], v["reason"]
        assert "1 条: AS-007" in v["reason"], v["reason"]
        assert lr.MUST_FIX_LABEL not in v["reason"], (
            f"第一组为空时不得出现该组标题（否则与 #4245 的文案契约冲突）：{v['reason']}")

    def test_the_undercount_is_now_visible(self):
        """xiaobu 腿的形态：按"未通过清单"数 = 3 条，实为 **5** 条阻塞（少算 2 条）。"""
        results = _leg_xiaobu()
        v = lr.completion_verdict(results, ())
        g = lr.blocking_groups(results, v)
        assert g[MUST_FIX_KEY] == ["OR-011", "OR-013", "OR-018"], g
        assert g[BLOCKED_KEY] == ["OR-021", "OR-023"], g
        assert len(g["blocking_ids"]) == 5, g
        # ③ 计数关系必须写在 reason 里（否则「passed + failed ≠ 阻塞数」还会被当成 bug）
        assert "阻塞条目共 5 条" in v["reason"], v["reason"]
        assert "failed=3" in v["reason"], v["reason"]
        assert "通过但被阻塞=2" in v["reason"], v["reason"]
        assert "passed=2 已含被阻塞条目" in v["reason"], v["reason"]


# ── ② 反向：真失败（score<1）仍落第一组 ───────────────────────────────────────

class TestRealFailuresStayInTheFirstGroup:

    def test_score_below_one_lands_in_must_fix(self):
        results = [_r("OR-029", 0.0, "reproducible")]
        v = lr.completion_verdict(results, ())
        g = lr.blocking_groups(results, v)
        assert g[MUST_FIX_KEY] == ["OR-029"], g
        assert g[BLOCKED_KEY] == [], (
            f"真失败被洗成『通过但被阻塞』—— 反向指错人：{g}")
        assert f"{lr.MUST_FIX_LABEL}1 条: OR-029" in v["reason"], v["reason"]

    def test_mixed_run_splits_both_ways(self):
        """一条真失败 + 一条通过但阻塞 ⇒ 两组各一条，**不互相吞并**。"""
        results = [_r("OR-029", 0.0, "reproducible"),
                   _recurring(_r("OR-021", 1.0, "llm-noise", flake_released=True))]
        v = lr.completion_verdict(results, ())
        g = lr.blocking_groups(results, v)
        assert g[MUST_FIX_KEY] == ["OR-029"], g
        assert g[BLOCKED_KEY] == ["OR-021"], g
        assert "阻塞条目共 2 条" in v["reason"], v["reason"]

    def test_journey_and_harness_and_restore_failures_are_kept(self):
        """分组**不许**吞掉既有桶：旅程 / harness / 前置未复位仍各自阻塞、仍进第一组。"""
        results = [
            _r(lr.KEY_JOURNEYS_MIBAO[0], 0.0, "reproducible"),
            _r("PG-013", 0.0, "reproducible", harness_incompatible="form_fields_mismatch"),
            _r("OR-010", 0.0, "reproducible", restore=["PRECONDITION_NOT_RESTORED: price"]),
        ]
        v = lr.completion_verdict(results, lr.KEY_JOURNEYS_MIBAO)
        g = lr.blocking_groups(results, v)
        assert set(g[MUST_FIX_KEY]) == {lr.KEY_JOURNEYS_MIBAO[0], "PG-013", "OR-010"}, g
        assert g[BLOCKED_KEY] == [], g
        assert v["ok"] is False, v


# ── ③ `ok` 的阻塞语义不变（新字段不是放行通道）────────────────────────────────

class TestBlockingStrengthUnchanged:

    def test_new_fields_do_not_release_anything(self):
        """**核心护栏**：第二组里的条目仍阻塞 `ok`（新字段只是"读法"，不是"放行"）。

        红证 = 注入"把第二组当放行"（`ok` 里排除它）⇒ 本断言红。
        """
        results = [_recurring(_r("AS-007", 1.0, "llm-noise", flake_released=True))]
        v = lr.completion_verdict(results, lr.KEY_JOURNEYS_MIBAO)
        g = lr.blocking_groups(results, v)
        assert g[BLOCKED_KEY] == ["AS-007"], "夹具没触发第二组 ⇒ 本断言是空的"
        assert v["ok"] is False, (
            "新字段把 fail-closed 的阻塞条目放行了 —— #3806 的收紧被绕过（禁止放宽）")
        assert v["systemic_recurrence"] == ["AS-007"], v
        assert v["flake_released"] == [], (
            f"复发条目不得留在放行桶里：{v}")

    def test_grouping_is_a_partition_of_the_blocking_set(self):
        """不变量：`must_fix ∪ blocked_but_passed ∪ case_asset == 各阻塞桶的去重并集`。

        与 `scripts/eval_closeout.py::blocking_buckets()` **同源**（都是"阻塞桶并集"），
        本函数只按 `score` 再切一刀 —— 不造第二套判据。
        """
        results = _leg_xiaobu() + [_precond_r("PR-016")]
        v = lr.completion_verdict(results, ())
        g = lr.blocking_groups(results, v)
        assert set(g["blocking_ids"]) == (
            set(g[MUST_FIX_KEY]) | set(g[BLOCKED_KEY]) | set(v["case_asset_failures"])), g
        assert v["ok"] is False, v

    def test_ok_branch_is_not_touched(self):
        """全绿时两组都空，且 `reason` 仍带放行波动（既有文案一字不动）。"""
        results = [_r("OR-001", 1.0, "pass"),
                   _r("PR-005", 1.0, "llm-noise", flake_released=True)]
        v = lr.completion_verdict(results, ())
        g = lr.blocking_groups(results, v)
        assert v["ok"] is True and g[MUST_FIX_KEY] == [] and g[BLOCKED_KEY] == [], g
        assert "放行波动 1 条" in v["reason"], v["reason"]


# ── ⑥ `case_asset_failures`（#4245）不折进第一组 ──────────────────────────────

class TestCaseAssetStaysSeparate:

    def test_case_asset_is_not_folded_into_must_fix(self):
        """#4245 的文案契约（另一个包的文件锁着）：「必须处理的失败」不得出现在纯用例资产场景。"""
        results = [_precond_r("PR-016")]
        v = lr.completion_verdict(results, ())
        g = lr.blocking_groups(results, v)
        assert v["case_asset_failures"] == ["PR-016"], v
        assert g[MUST_FIX_KEY] == [] and g[BLOCKED_KEY] == [], g
        assert "用例资产缺陷" in v["reason"], v["reason"]
        assert "必须处理的失败" not in v["reason"], (
            f"用例资产缺陷被算进『必须处理的失败』—— 文案与分桶自相矛盾：{v['reason']}")
        assert v["ok"] is False, "用例资产缺陷被放行（禁止放宽）"


# ── ⑤ summary JSON 的结构化字段（下游渲染器直接分组，不必再推导）───────────────

class TestSummaryCarriesTheGroups:

    def test_completion_has_both_structured_groups(self, tmp_path):
        data = _write(tmp_path, _leg_xiaobu())
        c = data["completion"]
        assert c[MUST_FIX_KEY] == ["OR-011", "OR-013", "OR-018"], c
        assert c[BLOCKED_KEY] == ["OR-021", "OR-023"], c
        # 既有桶一字未动（只加字段，不改判定/不改分桶）
        assert c["deterministic_failures"] == ["OR-011", "OR-013", "OR-018"], c
        assert c["systemic_recurrence"] == ["OR-021", "OR-023"], c
        assert c["flake_released"] == [] and c["ok"] is False, c
        assert data["passed"] == 2 and data["failed"] == 3, data

    def test_keys_are_always_present_even_when_green(self, tmp_path):
        """固定键集（消费者按名读）：全绿 / 零用例也要有这两个键，值为空列表。"""
        green = _write(tmp_path, [_r("OR-001", 1.0, "pass")])["completion"]
        assert green[MUST_FIX_KEY] == [] and green[BLOCKED_KEY] == [], green
        empty = _write(tmp_path, [])["completion"]
        assert empty[MUST_FIX_KEY] == [] and empty[BLOCKED_KEY] == [], empty
        assert set(empty) == set(green), sorted(set(green) ^ set(empty))

    def test_summary_reason_is_the_same_verdict_reason(self, tmp_path):
        """summary 的 `reason` 与判定函数逐字一致（两处渲染**同源**，不造第二套文案）。"""
        results = _leg_xiaobu()
        data = _write(tmp_path, results)
        assert data["completion"]["reason"] == lr.completion_verdict(results, ())["reason"]
