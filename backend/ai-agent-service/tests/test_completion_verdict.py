"""评测完成判定谓词单测（tests/agent_eval/local_runner.py::completion_verdict）

#3483 T2「完成定义前置」：评测完成 = 确定性失败清零 + 关键旅程 case 全过 +
已知波动（**只有** llm-noise）由 flake 台账放行。取代「全量 100% 绿才算完」的
旧判据（B 端 80 轮差距分析实证：最后 5-10% 是 LLM 方差，追 100% 边际收益为负——
三测自述「逐个校准 case 追波动边际收益递减」）。

判定语义（**口径变更**：`unstable` 不再放行，见 `_COMPLETION_RELEASED_CLASSES`）：
- 必须处理的失败（阻塞）：除 `llm-noise` 外的一切 score<1 ——
  reproducible / unstable / error / no-retry-budget / infra / 未知分类；
- 关键旅程用例（KEY_JOURNEYS_*，P0 跨域核心链路）任何一条 score<1 → 未完成
  （旅程是用户真会走的路，波动也不放行）；
- `llm-noise`（首次失败、新 session 重试通过，已记入 flake 台账）→ 放行但列出。

为什么 `unstable` 也被阻塞：它只证明"两次失败不是同一件事"，**没有**证明"其中
有一次是对的"（实证 OR-014 run 34841029062：一次"下单成功但金额错 168≠198"、
一次"order_create 从未被调用" —— 2/2 都真失败）。波动放行的前提是"有一次通过"。
"""
# case_ids: OR-016, PR-019, AS-007, FN-004, HR-003, DA-002, CU-003, CT-002, OR-012, CH-010, OR-017, KN-001, CH-008, CH-024, OR-014
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner3", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()

JOURNEY = ("OR-016", "PR-019")


def _r(case_id, score, classification="pass", flake_released=False):
    """一条用例结果。`flake_released=True` = 真实链路里 `run_case` 在
    「首败 + 重试通过」那一刻打的标记（issue #3781；此时 `score == 1.0`）。"""
    d = {"case_id": case_id, "score": score, "classification": classification}
    if flake_released:
        d["flake_released"] = True
    return d


class TestCompletionVerdict:
    def test_all_pass_is_complete(self):
        v = lr.completion_verdict([_r("OR-001", 1.0), _r("OR-016", 1.0)], JOURNEY)
        assert v["ok"] is True

    def test_empty_results_blocks(self):
        v = lr.completion_verdict([], JOURNEY)
        assert v["ok"] is False
        assert "0 个用例" in v["reason"]

    def test_reproducible_blocks(self):
        v = lr.completion_verdict([_r("FN-004", 0.0, "reproducible")], JOURNEY)
        assert v["ok"] is False
        assert "FN-004" in v["deterministic_failures"]

    def test_error_blocks(self):
        v = lr.completion_verdict([_r("HR-003", 0.0, "error")], JOURNEY)
        assert v["ok"] is False
        assert "HR-003" in v["deterministic_failures"]

    def test_no_retry_budget_blocks(self):
        """重试预算用尽 = 未重试未分类，保守视为确定性失败（诚实报告，不得放行）"""
        v = lr.completion_verdict([_r("DA-002", 0.0, "no-retry-budget")], JOURNEY)
        assert v["ok"] is False

    def test_infra_blocks_this_run(self):
        """infra 失败使本轮不可信（环境问题可整跑重试，但结论不能基于本轮）"""
        v = lr.completion_verdict([_r("CT-002", 0.0, "infra")], JOURNEY)
        assert v["ok"] is False

    def test_llm_noise_released(self):
        v = lr.completion_verdict([_r("AS-007", 0.0, "llm-noise")], JOURNEY)
        assert v["ok"] is True
        assert "AS-007" in v["flake_released"]

    # ── issue #3781：`flake_released` 曾是**恒为空**的死字段（真实 run 34856561459）──
    # 放行档的语义前提是"重试**通过**" ⇒ 该用例最终 `score == 1.0`，而旧实现的断言序是
    # 「score >= 1.0 → continue」在前、「分类命中放行档 → 记入 flake_released」在后
    # ⇒ 放行条目**永远走不到那一句**。run 实证：mibao `classes = pass 67 / reproducible 5
    # / llm-noise 6`、台账 `released=True` 6 条（PG-016/OR-010/OR-016/PR-007/PP-001/PR-005），
    # 而 `completion.flake_released == []`；xiaobu 同形（1 条 llm-noise → `[]`）。

    def test_released_flake_with_passing_score_is_listed(self):
        """**红证**：真实形态（首败+重试通过 → score=1.0 + 标记）必须出现在放行列表里。

        改造前本用例必红（`flake_released == []`）——见 `_legacy_guard_released()` 的
        "改造前算法"复刻，两者对比即"改前不列 / 改后必列"。
        """
        v = lr.completion_verdict(
            [_r("PR-005", 1.0, "llm-noise", flake_released=True),
             _r("PR-007", 1.0, "llm-noise", flake_released=True),
             _r("OR-001", 1.0, "pass")], JOURNEY)
        assert v["ok"] is True
        assert sorted(v["flake_released"]) == ["PR-005", "PR-007"], (
            f"重试通过的放行条目没有出现在 flake_released（旧 bug 复现）：{v}")
        assert "放行波动 2 条" in v["reason"], v["reason"]

    def test_legacy_guard_drops_the_same_entries_red_proof(self):
        """**红证**（对照）：把判定循环还原成**改造前**的写法 ⇒ 同输入下放行列表为空。

        这是"改造前该断言会红"的机器证明：不需要 git 回滚，直接在测试里保留旧算法的
        独立副本（刻意不复用新实现 —— 复用会让两边同源、一起变，红证失效）。
        """
        results = [_r("PR-005", 1.0, "llm-noise", flake_released=True)]
        legacy = []
        for r in results:
            if r.get("score", 0) >= 1.0:
                continue                      # ← 改造前的第一句：放行条目在这里被丢掉
            if str(r.get("classification") or "") in lr._COMPLETION_RELEASED_CLASSES:
                legacy.append(r["case_id"])
        assert legacy == [], "旧算法不该列出任何放行条目（这正是要修的 bug）"
        assert lr.completion_verdict(results, JOURNEY)["flake_released"] == ["PR-005"], (
            "新算法必须列出它 —— 否则本次修复没有改变任何行为")

    def test_journey_release_marker_does_not_leak_into_released_bucket(self):
        """关键旅程优先不变：**失败**的旅程用例即使打了放行标记也只进 `journey_failures`。

        两种形态分开断言（这是最容易写错的地方）：
          · 旅程用例 `score<1` + 分类命中放行档（离线夹具形态）⇒ 进 `journey_failures`，
            **不**进 `flake_released`（见既有 `test_journey_failure_blocks_even_llm_noise`）；
          · 旅程用例 `score==1.0`（重试**通过**，带放行标记）⇒ 它根本不是失败 ⇒ 不进任何
            失败桶，**也绝不进放行桶**（放行桶只列"失败被放行"的条目，不是"通过的用例"）。
        """
        v = lr.completion_verdict(
            [_r("OR-016", 1.0, "llm-noise", flake_released=True)], JOURNEY)
        assert v["ok"] is True, v
        assert v["flake_released"] == [], (
            f"通过的旅程用例被列进了放行桶（放行桶语义是「失败但被放行」）：{v}")
        assert v["journey_failures"] == [] and v["deterministic_failures"] == [], v
        # 对照：**失败**的旅程用例（离线夹具形态）必须被拦下
        blocked = lr.completion_verdict([_r("OR-016", 0.0, "llm-noise")], JOURNEY)
        assert blocked["ok"] is False and blocked["journey_failures"] == ["OR-016"]
        assert blocked["flake_released"] == []

    def test_unstable_blocks(self):
        """**口径变更**：`unstable`（两次皆败、成因不同）不再放行 ——
        它只证明"两次不是同一件事"，没有证明"其中有一次是对的"（OR-014 实证）。"""
        v = lr.completion_verdict([_r("CU-003", 0.0, "unstable")], JOURNEY)
        assert v["ok"] is False
        assert "CU-003" in v["deterministic_failures"]
        assert v["flake_released"] == []

    def test_journey_failure_blocks_even_llm_noise(self):
        """关键旅程不放行：P0 旅程 score<1 即使分类 llm-noise 也判未完成"""
        v = lr.completion_verdict([_r("OR-016", 0.0, "llm-noise")], JOURNEY)
        assert v["ok"] is False
        assert "OR-016" in v["journey_failures"]

    def test_unknown_classification_blocks_conservative(self):
        """无分类证据的失败（旧数据/异常形态）按确定性失败处理，不放行"""
        v = lr.completion_verdict([_r("X-001", 0.0, "")], JOURNEY)
        assert v["ok"] is False
        assert "X-001" in v["deterministic_failures"]

    def test_pass_classification_with_low_score_blocks(self):
        """no-classify 兼容路径的形态：classification=pass 但 score<1 → 保守按确定性失败"""
        v = lr.completion_verdict([_r("X-002", 0.5, "pass")], JOURNEY)
        assert v["ok"] is False

    def test_legacy_shape_without_classification_ok_when_pass(self):
        v = lr.completion_verdict([{"case_id": "A", "score": 1.0}], JOURNEY)
        assert v["ok"] is True

    def test_reason_mentions_both_groups(self):
        v = lr.completion_verdict(
            [_r("FN-004", 0.0, "reproducible"), _r("OR-016", 0.0, "llm-noise")], JOURNEY)
        assert v["ok"] is False
        assert "FN-004" in v["reason"] and "OR-016" in v["reason"]

    def test_journey_ids_are_sane_constants(self):
        """关键旅程常量必须引用真实存在的用例（防拼错 = 完成判定空转）"""
        import sys
        sys.path.insert(0, str(REPO_ROOT / ".github"))
        from render_cases import load_case_dicts
        ids = {c["id"] for c in load_case_dicts(str(REPO_ROOT / ".github" / "cases"))}
        for jid in (set(lr.KEY_JOURNEYS_MIBAO) | set(lr.KEY_JOURNEYS_XIAOBU)):
            assert jid in ids, f"关键旅程 {jid} 不存在于 cases/（完成判定将空转）"


# ── 契约守卫（口径变更的护栏）：分类枚举封闭 + buckets 三方一致 ──────────────────
#
# 为什么需要：`completion_verdict` 的输出被三方消费 —— runner 打印、summary 的
# `completion` 字段、flake 台账（`cases[].classification` ↔ `deterministic_failures` /
# `flake_released` ↔ 台账条目）。口径变更（`unstable` 移出放行档）如果只改常量、
# 不锁契约，就会出现"分类说一套、bucket 说另一套"的静默漂移。

# 分类值是**封闭枚举**（`_classify_attempts` + 两条终态路径）。新增/改名必须同时
# 更新这里 + `FLAKE_REASONS` + 台账消费方；本守卫以红灯逼出这次同步。
CLASSIFICATIONS = frozenset({
    "pass", "llm-noise", "reproducible", "unstable", "infra", "no-retry-budget", "error"})
# 需要 flake 台账 reason 文案的档（pass/error 是终态，不进 flake 台账）
FLAKE_CLASSES = CLASSIFICATIONS - {"pass", "error"}


class TestVerdictContract:
    def test_released_classes_are_a_subset_of_the_closed_enum(self):
        assert lr._COMPLETION_RELEASED_CLASSES <= CLASSIFICATIONS
        assert lr._COMPLETION_RELEASED_CLASSES == frozenset({"llm-noise"}), (
            "放行档只允许 llm-noise（首次失败 + 重试通过）；`unstable` 已改为阻塞")

    def test_every_flake_class_has_a_reason(self):
        assert set(lr.FLAKE_REASONS) == FLAKE_CLASSES, (
            "FLAKE_REASONS 必须与分类枚举一一对应（新增分类必须给 reason，删除必须清）")
        missing = [c for c in FLAKE_CLASSES if len(str(lr.FLAKE_REASONS.get(c) or "")) < 8]
        assert missing == [], f"这些分类的 reason 文案缺失/过短: {missing}"

    def test_classify_attempts_only_returns_enum_members(self):
        """穷举 16 种尝试组合（首次成败 × 重试成败 × infra × 指纹同异）→ 返回值都属枚举。"""
        same = [("tool: order_create", "unmatched")]
        diff = [("tool: order_query", "unmatched")]
        seen = set()
        for s1 in (1.0, 0.0):
            for s2 in (1.0, 0.0):
                for infra in (None, "httpx.ConnectError: refused"):
                    for f2 in (same, diff):
                        got = lr._classify_attempts(
                            {"score": s1, "failed": same, "last_error": infra},
                            {"score": s2, "failed": f2, "last_error": infra})
                        seen.add(got)
        unknown = sorted(seen - CLASSIFICATIONS)
        assert unknown == [], f"_classify_attempts 返回了枚举外的分类: {unknown}"
        assert seen == CLASSIFICATIONS - {"pass", "error"} or len(seen) >= 4, (
            f"穷举未覆盖到足够多的分类（实得 {sorted(seen)}）—— 守卫疑似空转")

    def test_buckets_partition_failed_cases_and_follow_the_release_policy(self):
        """三方一致：失败用例**恰好**落在 deterministic / journey / released 三者之一，
        且 `released` 桶 == 分类命中放行档的用例（关键旅程优先）。"""
        results = [
            _r("OK-001", 1.0, "pass"),
            _r("AS-007", 0.0, "llm-noise"),        # 放行档（非旅程）
            _r("OR-001", 0.0, "reproducible"),
            _r("OR-014", 0.0, "unstable"),         # 口径变更后阻塞
            _r("CT-002", 0.0, "infra"),
            _r("DA-002", 0.0, "no-retry-budget"),
            _r("X-001", 0.0, ""),                  # 无分类证据 → 保守阻塞
            _r("FN-004", 0.0, "error"),
            _r("OR-016", 0.0, "llm-noise"),        # 关键旅程：旅程桶优先于放行
        ]
        journey = ("OR-016", "PR-019")
        v = lr.completion_verdict(results, journey)
        failed = {r["case_id"] for r in results if r["score"] < 1.0}
        det, rel, jou = (set(v["deterministic_failures"]), set(v["flake_released"]),
                         set(v["journey_failures"]))
        assert det | rel | jou == failed, "有失败用例没落进任何一个桶（三方不一致）"
        assert not (det & rel) and not (det & jou) and not (rel & jou), "桶之间必须互斥"
        assert v["ok"] == (not det and not jou)
        by_id = {r["case_id"]: r for r in results}
        for cid in rel:
            assert str(by_id[cid].get("classification") or "") in lr._COMPLETION_RELEASED_CLASSES, (
                f"{cid} 进了放行桶但分类不在放行档（放行口径漂移）")
        for cid in det - jou:
            assert str(by_id[cid].get("classification") or "") not in lr._COMPLETION_RELEASED_CLASSES
        assert "OR-014" in det, "unstable 必须落在阻塞桶"
        assert "OR-016" in jou, "关键旅程优先于放行档"

    def test_ledger_released_flag_matches_the_policy(self):
        """台账条目的 `released` 字段与放行档同源（台账是"为什么放行"的唯一长期证据）。"""
        attempt = {"score": 0.0, "failed": [("tool: order_create", "unmatched")], "last_error": None}
        bad = []
        for cls in sorted(FLAKE_CLASSES):
            entry = lr.build_flake_entry("OR-014", "t", cls, attempt, attempt, "run", "sha")
            if entry["released"] != (cls in lr._COMPLETION_RELEASED_CLASSES):
                bad.append(f"{cls}: released={entry['released']} 与放行档不符")
        assert bad == [], "台账 released 与放行档漂移：\n  " + "\n  ".join(bad)


# ── 跨 run 指纹复发（issue #3806）：放行政策补上「跨 run」这一维 ──────────────────
#
# 病灶：放行判据只看**本次 run 的两次尝试**（首败 + 重试通过 = `llm-noise` = 放行），
# 而台账每次 run 独立生成 ⇒「同一首跑指纹」可以永远"首次出现"。
# 铁证（三个**真实** run 的 `agent-eval-flakes.json`，PR-016）：
#   run 34856561459 / 34865780382 / 34873715194 的首跑指纹**恒为**
#   `no_success(interact)||required_arg(processing_item_query,applicable_category_id)`
#   （首跑通过率 **0/3**），第三次却因"重试碰巧过"被判 `llm-noise` + 放行。
# ⇒ 判据补一维：同一 `(用例, 首跑指纹)` 在历史 run 里出现过 ⇒ **不是随机波动** ⇒ 不放行。
# 夹具即上面三个 run 的**真实指纹**（不是编的），且阈值/去重/空指纹都有反向守卫。
PR016_FP = ("no_success(interact)||"
            "required_arg(processing_item_query,applicable_category_id)")
RUN1, RUN2, RUN3 = "34856561459", "34865780382", "34873715194"


def _entry(case_id, fingerprint, run_id):
    return {"case_id": case_id, "first_attempt_signature": fingerprint, "run_id": run_id}


class TestCrossRunRecurrence:
    def _history(self, pairs):
        hist = {}
        for rid, entries in pairs:
            hist = lr.merge_flake_history(hist, entries, rid)
        return hist

    def _run3_history(self):
        """run1 / run2 的真实指纹（run3 之前）"""
        return self._history([
            (RUN1, [_entry("PR-016", PR016_FP, RUN1), _entry("PR-012", "唯一指纹A", RUN1)]),
            (RUN2, [_entry("PR-016", PR016_FP, RUN2)]),
        ])

    def test_recurring_fingerprint_is_not_released(self):
        """**核心**：PR-016 在 run3 被判 llm-noise（重试通过）—— 历史里指纹已出现 2 次 ⇒ 不放行。"""
        hist = self._run3_history()
        r = {"case_id": "PR-016", "score": 1.0, "classification": "llm-noise",
             "flake_released": True}
        marked = lr.annotate_cross_run_recurrence([r], [_entry("PR-016", PR016_FP, RUN3)], hist)
        assert [m["case_id"] for m in marked] == ["PR-016"], "复发指纹没被标注"
        assert marked[0]["prior_count"] == 2
        v = lr.completion_verdict([r], ())
        assert v["ok"] is False, "跨 run 复发的系统性缺口被放行了（政策仍缺这一维）"
        assert v["systemic_recurrence"] == ["PR-016"]
        assert v["flake_released"] == [], "复发条目不得留在放行桶里"
        assert "跨 run 复发" in v["reason"]

    def test_red_proof_without_history_the_old_policy_releases(self):
        """**红证**：没有历史（= 修前口径）时同一条被判放行 ⇒ 证明新判据真的改变了结论。"""
        r = {"case_id": "PR-016", "score": 1.0, "classification": "llm-noise",
             "flake_released": True}
        assert lr.annotate_cross_run_recurrence([r], [_entry("PR-016", PR016_FP, RUN3)], {}) == []
        v = lr.completion_verdict([r], ())
        assert v["ok"] is True and v["flake_released"] == ["PR-016"]
        assert v["systemic_recurrence"] == []

    def test_random_flake_is_still_released(self):
        """**反向守卫**：指纹不在历史里（真随机波动）⇒ 仍然放行，不得改判。"""
        hist = self._run3_history()
        r = {"case_id": "OR-017", "score": 1.0, "classification": "llm-noise",
             "flake_released": True}
        lr.annotate_cross_run_recurrence([r], [_entry("OR-017", "抖动指纹X", RUN3)], hist)
        assert r.get("cross_run_recurrence") is None
        v = lr.completion_verdict([r], ())
        assert v["ok"] is True and v["flake_released"] == ["OR-017"]

    def test_empty_fingerprint_never_counts_as_recurrence(self):
        """空指纹必须永不判复发：`空 == 空` 会把一批无关用例互相"确认"成复发（假红）。"""
        hist = self._history([(RUN1, [_entry("A-001", "", RUN1)]), (RUN2, [_entry("A-001", "", RUN2)])])
        r = {"case_id": "A-001", "score": 1.0, "classification": "llm-noise", "flake_released": True}
        assert lr.annotate_cross_run_recurrence([r], [_entry("A-001", "", RUN3)], hist) == []
        assert lr.completion_verdict([r], ())["ok"] is True

    def test_same_fingerprint_across_different_cases_is_only_informational(self):
        """键带 case_id：不同用例落到同一泛化指纹时**不得**互相判复发（只做信息性提示）。"""
        hist = self._history([(RUN1, [_entry("PR-016", "no_success(interact)", RUN1)])])
        r = {"case_id": "PR-014", "score": 1.0, "classification": "llm-noise", "flake_released": True}
        assert lr.annotate_cross_run_recurrence(
            [r], [_entry("PR-014", "no_success(interact)", RUN3)], hist) == []
        assert lr.completion_verdict([r], ())["ok"] is True
        assert lr.cross_case_fingerprint_cases(hist) == {}   # 历史里只有一条用例

    def test_merge_is_idempotent_per_run(self):
        """同一 run 重复并入必须只计一次（否则自己把自己判成复发）。"""
        e = [_entry("PR-016", PR016_FP, RUN1)]
        hist = lr.merge_flake_history({}, e, RUN1)
        hist = lr.merge_flake_history(hist, e, RUN1)
        assert hist["PR-016"][PR016_FP]["runs"] == [RUN1]

    def test_current_run_does_not_count_itself(self):
        """**顺序契约**：run_suite 必须「先标注（用历史）→ 再并入本次」。

        顺序反过来时，本次 run 会出现在自己的"历史"里 ⇒ **首次出现**的指纹被判复发（假红）。
        本用例把这条顺序锁进断言（配 `test_merge_is_idempotent_per_run` 的 run_id 去重）。
        """
        hist = self._run3_history()
        new_fp = "首见指纹B"
        e_new = [_entry("PR-016", new_fp, RUN3)]
        r = {"case_id": "PR-016", "score": 1.0, "classification": "llm-noise", "flake_released": True}
        # ① 先标注（历史里没有该指纹）⇒ 不复发（= 本次 run 没把自己算进去）
        assert lr.annotate_cross_run_recurrence([r], e_new, hist) == []
        # ② 再并入 ⇒ 下一次 run 看到它才算复发（这正是"跨 run"的含义）
        hist2 = lr.merge_flake_history(hist, e_new, RUN3)
        r2 = {"case_id": "PR-016", "score": 1.0, "classification": "llm-noise", "flake_released": True}
        assert lr.annotate_cross_run_recurrence(
            [r2], [_entry("PR-016", new_fp, "run-next")], hist2), (
            "上一次 run 出现过的指纹，本次必须判复发")

    def test_merge_does_not_mutate_input_history(self):
        """纯函数：不得就地改入参（调用方可能还要用旧索引做对比）。"""
        hist = self._history([(RUN1, [_entry("PR-016", PR016_FP, RUN1)])])
        before = repr(hist)
        lr.merge_flake_history(hist, [_entry("PR-016", PR016_FP, RUN2)], RUN2)
        assert repr(hist) == before

    def test_recurrence_only_downgrades_released_entries(self):
        """复发条目以 `systemic_recurrence` 呈现（盲审缺陷二口径，判定跑 34923425338 实证）。

        旧契约（本测试曾锁）：score<1.0 + 分类 reproducible 的复发条目进
        `deterministic_failures` 且 **不进** systemic（"不重复计数"）⇒ OR-014
        （`cross_run_recurrence {prior_count: 1}`）在 `systemic_recurrence` 里
        **漏报**，报告的"跨 run 复发"维永远缺该条（本轮因 det 阻塞而无害，但
        构成口径不合）。新判据（§16.7 结论构成）：凡 `cross_run_recurrence.
        prior_count>0` 且指纹同型 ⇒ **一律**进 `systemic_recurrence`，不因
        "本轮失败 / 旅程身份 / 分类非放行"而改桶 —— 失败路径与通过路径同判。
        `ok` 语义不变：det 与 systemic 都是阻塞桶，改前改后都 False。
        """
        hist = self._run3_history()
        r = {"case_id": "PR-016", "score": 0.0, "classification": "reproducible"}
        lr.annotate_cross_run_recurrence([r], [_entry("PR-016", PR016_FP, RUN3)], hist)
        v = lr.completion_verdict([r], ())
        assert v["systemic_recurrence"] == ["PR-016"] and v["deterministic_failures"] == [], v
        assert v["ok"] is False

    def test_fingerprint_key_carries_case_and_signature(self):
        assert lr.flake_fingerprint_key(_entry("PR-016", "fp", RUN1)) == ("PR-016", "fp")
        assert lr.CROSS_RUN_RECURRENCE_MIN_PRIOR >= 1, "阈值必须 fail-closed（≥1 次历史即复发）"



# ── 真实数据锚点：**哪些既有放行会被改判**（issue #3806 的红证要求）────────────
# 上面几条用的是 PR-016 一个指纹；这里把**真实历史**整体冻成夹具：数据抄自 8 个真实 run
# 的 `agent-eval-flakes.json`（`gh run download`，零 LLM；复算脚本见 PR body）。
# 判据 = **真实** `cross_run_recurrence`，输入 = 真实台账条目，期望 = 真实复算结果。
# 价值：口径若被放松（如阈值改回"看本次两次尝试"、键去掉 case_id、指纹被清空），
# 这 5 条改判会立刻消失 ⇒ 红。
# 真实数据（8 个真实 run 的 agent-eval-flakes.json；本 run = 34873715194，历史 = 前 3 个 run）
REAL_PRIOR_RUNS = ['34856561459', '34865780382', '34867559987']
REAL_TARGET_RUN = '34873715194'
# 该 run 里被判 released 的真实条目（case_id, 首跑指纹）—— 全部抄自 artifact，未编造
REAL_RELEASED = [
    ('PG-016', 'no_success(processing_order_update)'),
    ('PR-012', 'no_success(processing_item_query)'),
    ('PR-016', 'no_success(interact)||required_arg(processing_item_query,applicable_category_id)'),
    ('PP-001', 'no_success(product_processing_item_manage)'),
    ('OR-011', 'no_success(order_create)'),
    ('OR-010', 'no_success(order_create)||no_success(validate_input)||want_text_missing(订单号)'),
    ('PR-017', 'no_success(product_update)'),
]
REAL_REJUDGED = ['OR-011', 'PG-016', 'PP-001', 'PR-016', 'PR-017']
REAL_STILL_RELEASED = ['OR-010', 'PR-012']
REAL_HISTORY = {
    ('OR-011', 'no_success(order_create)'): ['34865780382'],
    ('PG-016', 'no_success(processing_order_update)'): ['34856561459', '34865780382'],
    ('PP-001', 'no_success(product_processing_item_manage)'): ['34856561459', '34865780382', '34867559987'],
    ('PR-016', 'no_success(interact)||required_arg(processing_item_query,applicable_category_id)'): ['34856561459', '34865780382'],
    ('PR-017', 'no_success(product_update)'): ['34865780382', '34867559987'],
}

class TestRealHistoryRejudgement:
    """run 34873715194 的 7 条放行里，**5 条**在真实历史上应被改判、**2 条**仍放行。"""

    def _history(self):
        hist = {}
        for (cid, fp), runs in REAL_HISTORY.items():
            for rid in runs:
                hist = lr.merge_flake_history(
                    hist, [{"case_id": cid, "first_attempt_signature": fp}], rid)
        return hist

    def test_five_of_seven_released_entries_are_rejudged(self):
        hist = self._history()
        rejudged, still = set(), set()
        for cid, fp in REAL_RELEASED:
            entry = {"case_id": cid, "first_attempt_signature": fp,
                     "classification": "llm-noise", "released": True}
            (rejudged if lr.cross_run_recurrence(entry, hist) else still).add(cid)
        assert sorted(rejudged) == REAL_REJUDGED, (
            f"真实历史上应被改判的放行条目变了：{sorted(rejudged)} ≠ {REAL_REJUDGED}"
            f"（口径被放松 ⇒ 系统性缺口又会按『LLM 波动』放行）")
        assert sorted(still) == REAL_STILL_RELEASED, (
            f"应仍放行的随机波动条目变了：{sorted(still)} ≠ {REAL_STILL_RELEASED}")

    def test_verdict_blocks_exactly_the_rejudged_ones(self):
        """端到端（判定层）：改判的进 `systemic_recurrence`，随机的留在 `flake_released`。"""
        hist = self._history()
        results = [{"case_id": cid, "score": 1.0, "classification": "llm-noise",
                    "flake_released": True} for cid, _ in REAL_RELEASED]
        ledger = [{"case_id": cid, "first_attempt_signature": fp, "classification": "llm-noise"}
                  for cid, fp in REAL_RELEASED]
        lr.annotate_cross_run_recurrence(results, ledger, hist)
        v = lr.completion_verdict(results, ())
        assert sorted(v["systemic_recurrence"]) == REAL_REJUDGED, v
        assert sorted(v["flake_released"]) == REAL_STILL_RELEASED, v
        assert v["ok"] is False, "跨 run 复发的系统性缺口被放行了（#3806 的政策没生效）"
        assert "跨 run 复发" in v["reason"], v["reason"]

    def test_build_time_index_is_empty_for_these_runs(self):
        """**红证（修前口径）**：不提供历史（= 只看本次两次尝试）⇒ 7 条**全部**放行、ok=True。

        这一条就是"修前会怎样"的可执行版本：`REAL_REJUDGED` 里的 5 条在修前全被放行。
        """
        results = [{"case_id": cid, "score": 1.0, "classification": "llm-noise",
                    "flake_released": True} for cid, _ in REAL_RELEASED]
        v = lr.completion_verdict(results, ())
        assert v["ok"] is True, v
        assert sorted(v["flake_released"]) == sorted({cid for cid, _ in REAL_RELEASED}), v
        assert v["systemic_recurrence"] == [], v
