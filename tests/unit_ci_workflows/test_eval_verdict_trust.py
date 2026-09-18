# case_ids: OR-016, OR-010, OR-015, PG-013
"""结论层可信度修复 —— GLM-5.3-Flash 盲审 4 处缺陷（run 34916256903 @1eea267a）的红证。

盲审结论（权威）：`gh issue view <本单>`；判定跑 `34916256903` 的 artifact
（`eval-summary-mibao.json` / `agent-eval-flakes.json` / `flake-history.json`）是全部证据源。
四处缺陷与判据：

| 缺陷 | 病灶 | 判据（改后） |
|---|---|---|
| 一（P0） | `completion_verdict` 的 `score>=1.0` 分支里「journey 守卫」先于「跨 run 复发检查」⇒ 关键旅程里的放行条目（OR-016）把 `_is_recurring` 短路掉，从**所有桶**消失 = 静默放行（同证据集里 PP-001 却被拦下） | 凡 `cross_run_recurrence.prior_count>0` 且指纹同型 ⇒ 一律进 `systemic_recurrence`（fail-closed），不因"本轮通过 / 旅程身份 / 分类 llm-noise"放行；prior_count=0 的新失败（首见）不得进 systemic |
| 二（P0） | 台账 reason 是静态模板「未在历史 run 复发」—— OR-016（prior_count=2）/ PP-001（prior_count=4）的台账与数据直接矛盾 | reason 从数据生成（含实际 `prior_count`/`prior_runs`）；prior>0 禁止「未复发」字样；历史不可得标「数据缺失」 |
| 三（P1） | 通过用例 summary 只有 id/score/classification/pre_clean —— 空断言假绿不可见 | 每条 case 落 `assertions_fired`（计分断言命中/可失败性 + 效果层触发）；计分断言全为存在性/散文且效果层未触发 ⇒ 标 `unfailable_green`（与 verdict 分开单列，不改 ok） |
| 四（P1） | `确认死循环` 检测器不附卡原文 ⇒「同样的事实 ×3」无法独立复核（PR-016 的 R5 trace 无 interact，复核者只能靠猜）；无内容卡被计数的同时却冒充「已核实的同样事实」 | 「同事实」判据 = 内容键（confirmValue / fields 集合）；失败信息附每张卡的原文摘要 + 判据；无内容卡按标题计数（fail-closed 历史契约）但**显式标注「按标题近似」**，不得冒充已核实事实 |

本文件锁**判定逻辑**（纯函数层），全部离线可跑、零 LLM；「改前红证」用
独立复写的旧逻辑副本（不复用新实现，否则两边同源、红证失效）。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身，单测不得真实 HTTP）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


# ── fixtures（照 run 34916256903 的真实形态构造，prior_count 与盲审一致）────────

def _released_recurring(cid, fingerprint, prior_runs):
    """重试通过 + 跨 run 复发的放行条目（真实 run 中 OR-016/PP-001 的形状）。"""
    return {
        "case_id": cid, "score": 1.0, "classification": "llm-noise",
        "flake_released": True,
        "cross_run_recurrence": {"case_id": cid, "fingerprint": fingerprint,
                                 "prior_runs": list(prior_runs),
                                 "prior_count": len(prior_runs)},
    }


def _confirm_round(rnd, args):
    return {"__round": rnd, "tool_calls": [{"name": "interact", "args": args}]}


# ── 缺陷一：systemic fail-closed 漏放 OR-016 ─────────────────────────────────

def _legacy_pass_bucket(cid, r, journey_set):
    """**改造前** `completion_verdict` 的 score>=1.0 分支（独立复写，红证用）。

    旧断言序「flake_released and cid not in journey_set」在前、`_is_recurring` 在后
    ⇒ 关键旅程里的放行条目（OR-016）把复发检查短路，从所有桶消失。
    """
    if r.get("score", 0) >= 1.0:
        if r.get("flake_released") and cid not in journey_set:
            if r.get("cross_run_recurrence"):
                return "systemic"
            return "flake_released"
        return None                    # ← OR-016 在这里被静默放行
    if cid in journey_set:
        return "journey"
    if str(r.get("classification") or "") in lr._COMPLETION_RELEASED_CLASSES:
        if r.get("cross_run_recurrence"):
            return "systemic"
        return "flake_released"
    return "deterministic"


class TestSystemicFailClosedCoversJourneyCases:
    OR016 = _released_recurring(
        "OR-016", "order_before_missing(interact[choice:processing_items])",
        ["34867559987", "34865780382"])
    PP001 = _released_recurring(
        "PP-001", "no_success(product_processing_item_manage)",
        ["34908262839", "34873715194", "34867559987", "34865780382"])

    def test_legacy_red_released_journey_recurring_from_all_buckets(self):
        """**改前红证**：旧断言序对 OR-016（旅程 + 复发 + 放行）返回 None = 从所有桶消失。"""
        bucket = _legacy_pass_bucket("OR-016", self.OR016, set(lr.KEY_JOURNEYS_MIBAO))
        assert not bucket, (
            f"旧逻辑给了桶 {bucket!r} —— 若已给桶，说明红证夹具没构造出「旅程短路」形态")
        # 对照：同证据集里 PP-001（非旅程）在旧逻辑里就被拦下 ⇒ 同构两例不同判（盲审原话）
        assert _legacy_pass_bucket("PP-001", self.PP001, set(lr.KEY_JOURNEYS_MIBAO)) == "systemic"

    def test_fixed_both_recurring_entries_go_to_systemic(self):
        """改后：OR-016 与 PP-001 一律进 `systemic_recurrence`（fail-closed 做全）。"""
        results = [dict(self.OR016), dict(self.PP001)]
        v = lr.completion_verdict(results, lr.KEY_JOURNEYS_MIBAO)
        assert sorted(v["systemic_recurrence"]) == ["OR-016", "PP-001"], v
        assert v["flake_released"] == [], v
        assert v["ok"] is False, "复发条目压 ok（收紧后失败数上升是设计效果，非回归）"

    def test_reverse_first_seen_noise_still_released(self):
        """反向守卫：prior_count=0 的新失败（本轮首见 llm-noise）不得进 systemic。"""
        first_seen = {"case_id": "OR-099", "score": 1.0,
                      "classification": "llm-noise", "flake_released": True}
        v = lr.completion_verdict([first_seen], ())
        assert v["flake_released"] == ["OR-099"], v
        assert v["systemic_recurrence"] == [], v
        assert v["ok"] is True, "首见波动被误判成阻塞（假红）"

    def test_non_recurring_journey_pass_unchanged(self):
        """非复发的旅程放行条目维持原语义（不进任何桶，它通过了）。"""
        ok_journey = {"case_id": "OR-016", "score": 1.0, "classification": "pass"}
        v = lr.completion_verdict([ok_journey], lr.KEY_JOURNEYS_MIBAO)
        assert v["journey_failures"] == [] and v["systemic_recurrence"] == [], v
        assert v["ok"] is True, v


# ── 缺陷二：放行台账 reason 从数据生成 ───────────────────────────────────────

class TestFlakeLedgerReasonComesFromData:
    ENTRY = {"case_id": "OR-016", "classification": "llm-noise"}
    PRIOR = {"case_id": "OR-016", "fingerprint": "fp",
             "prior_runs": ["34867559987", "34865780382"], "prior_count": 2}

    def test_legacy_template_contradicts_data(self):
        """**改前红证**：静态模板恒写「未在历史 run 复发」—— 与 prior_count=2 直接矛盾。"""
        legacy = lr.FLAKE_REASONS["llm-noise"]
        assert "未在历史 run 复发" in legacy, (
            "模板文本变了 —— 红证夹具要锁的是「模板不读数据」这个旧形态")

    def test_prior_gt_zero_reason_carries_data_and_no_denial(self):
        reason = lr.flake_reason_with_recurrence(self.ENTRY, self.PRIOR, True)
        assert "prior_count=2" in reason, reason
        assert "34867559987" in reason and "34865780382" in reason, reason
        assert "未在历史 run 复发" not in reason, reason
        assert "不按波动放行" in reason, reason

    def test_rewrite_flake_reasons_applies_to_ledger(self):
        """端到端：台账条目（build_flake_entry 产物）被 rewrite 改成数据驱动。"""
        first = {"score": 0.0, "failed": [("x", "")]}
        second = {"score": 1.0, "failed": []}
        entry = lr.build_flake_entry("OR-016", "t", "llm-noise", first, second, "r1", "sha")
        # 历史索引的键 = 台账条目的 first_attempt_signature（与真实 flake-history.json 同构）
        fp = entry["first_attempt_signature"]
        lr.rewrite_flake_reasons([entry], {"OR-016": {fp: {"runs": ["34867559987"]}}}, True)
        assert "prior_count=1" in entry["reason"], entry["reason"]
        assert "未在历史 run 复发" not in entry["reason"], entry["reason"]

    def test_no_history_marks_data_missing(self):
        """历史索引不可得 ⇒ 标「数据缺失」，不冒充「未复发」（没查过 = 没资格说没复发）。"""
        reason = lr.flake_reason_with_recurrence(self.ENTRY, None, False)
        assert "数据缺失" in reason, reason
        assert "未在历史 run 复发" not in reason, reason

    def test_prior_zero_allows_first_seen_wording(self):
        """反向：prior_count=0（历史已查、首次出现）⇒ 维持「未在历史 run 复发」措辞。"""
        reason = lr.flake_reason_with_recurrence(self.ENTRY, None, True)
        assert "未在历史 run 复发" in reason, reason
        assert "数据缺失" not in reason, reason


# ── 缺陷三：通过侧断言证据（绿的不可审计性）──────────────────────────────────

class TestPassingCasesCarryAssertionEvidence:
    def _case(self, **effect):
        from types import SimpleNamespace
        defaults = {"must_succeed": [], "db_verify": [], "amount_verify": [],
                    "output_verify": [], "order_before": []}
        defaults.update(effect)
        return SimpleNamespace(**defaults)

    def _round(self):
        return {"tool_calls": [{"name": "order_query", "args": {}}],
                "__all_tool_names": ["order_query"], "final_text": "ok"}

    def test_existential_only_passing_case_is_unfailable_green(self):
        """通过 + 计分断言全为存在性（裸工具名）+ 无效果层 ⇒ `unfailable_green`。"""
        case = self._case()
        af = lr._assertions_fired_summary(case, ["order_query"], [self._round()], 1.0)
        assert af["scoring"] == [{"check": "order_query", "failable": False, "passed": True}]
        assert af["effect_layers"] == {"must_succeed": False, "db_verify": False,
                                       "amount_verify": False, "output_verify": False}
        assert lr._unfailable_green(1.0, ["order_query"], af, False) is True

    def test_no_scoring_checks_passing_is_unfailable_green(self):
        """通过但**无任何计分断言**（score=1.0 纯构造）⇒ 同样标假绿候选。"""
        case = self._case()
        af = lr._assertions_fired_summary(case, [], [], 1.0)
        assert af["scoring"] == []
        assert lr._unfailable_green(1.0, [], af, False) is True

    def test_amount_verify_fired_prevents_the_flag(self):
        """通过 + `amount_verify` 真触发 ⇒ 不标 `unfailable_green`（绿有实据）。"""
        case = self._case(amount_verify=[{"tool": "order_create", "checks": []}])
        af = lr._assertions_fired_summary(case, [], [], 1.0)
        assert af["effect_layers"]["amount_verify"] is True
        assert lr._unfailable_green(1.0, [], af, False) is False

    def test_must_succeed_fired_prevents_the_flag(self):
        case = self._case(must_succeed=[{"tool": "order_create"}])
        af = lr._assertions_fired_summary(case, [], [], 1.0)
        assert af["effect_layers"]["must_succeed"] is True
        assert lr._unfailable_green(1.0, [], af, False) is False

    def test_failable_scoring_check_prevents_the_flag(self):
        """通过但计分断言含可失败项（带 args / 反向断言）⇒ 不算假绿候选。"""
        case = self._case()
        af = lr._assertions_fired_summary(
            case, ["after_sales_manage(action=list)"], [self._round()], 1.0)
        assert af["scoring"][0]["failable"] is True
        assert lr._unfailable_green(1.0, ["after_sales_manage(action=list)"], af, False) is False

    def test_failing_case_never_flagged(self):
        """失败用例不受影响（不标假绿候选—— 它已经红了）。"""
        case = self._case()
        af = lr._assertions_fired_summary(case, [], [], 0.0)
        assert lr._unfailable_green(0.0, [], af, False) is False

    def test_order_before_declared_does_not_block_the_flag(self):
        """`order_before` 不进 `assertions_fired` profile ⇒ 不再阻断 `unfailable_green`
        （盲审判据「同 profile 必同标记」：OR-015/PG-013 与 OR-010 的 profile 逐字段
        相同，判定跑 34923425338 实证漏标；标记只读 profile，见
        `_unfailable_green` docstring 的弃用说明）。"""
        case = self._case(order_before=["order_query before order_create"])
        af = lr._assertions_fired_summary(case, [], [], 1.0)
        assert lr._unfailable_green(1.0, [], af, True) is True

    def test_scoring_check_failable_taxonomy(self):
        """可失败性判据表（与 taxonomy 行为层口径同源）。"""
        assert lr._scoring_check_is_failable("order_create 未被调用") is True
        assert lr._scoring_check_is_failable("sku_update not called") is True
        assert lr._scoring_check_is_failable("error.code=NOT_FOUND") is True
        assert lr._scoring_check_is_failable("success=true") is True
        assert lr._scoring_check_is_failable("sku_update(price=150)") is True
        assert lr._scoring_check_is_failable("direct_reply") is True
        assert lr._scoring_check_is_failable("order_query") is False
        assert lr._scoring_check_is_failable("interact") is False

    def test_summary_serializes_assertion_evidence(self, tmp_path):
        """summary 每条 case 落 `assertions_fired` + `unfailable_green`（可审计）。"""
        case = self._case()
        af = lr._assertions_fired_summary(case, ["order_query"], [self._round()], 1.0)
        assert lr._unfailable_green(1.0, ["order_query"], af, False) is True
        result = {"case_id": "OR-088", "score": 1.0, "classification": "pass",
                  "pre_clean": [], "assertions_fired": af, "unfailable_green": True}
        out = tmp_path / "s.json"
        lr.write_summary_json(str(out), "post-deploy", "", [result])
        import json
        data = json.loads(out.read_text(encoding="utf-8"))
        entry = data["cases"][0]
        assert entry["assertions_fired"]["scoring"] == af["scoring"], entry
        assert entry["assertions_fired"]["effect_layers"]["must_succeed"] is False
        assert entry["unfailable_green"] is True, entry
        # 判定不受影响：绿照旧是绿（假绿候选只是审计标记）
        assert data["completion"]["ok"] is True, data["completion"]

    def test_synthetic_fixture_without_evidence_stays_byte_compatible(self, tmp_path):
        """无 `assertions_fired` 的合成结果 ⇒ summary 条目不带新键（回归锚点不破）。"""
        result = {"case_id": "OR-088", "score": 1.0, "classification": "pass", "pre_clean": []}
        out = tmp_path / "s.json"
        lr.write_summary_json(str(out), "post-deploy", "", [result])
        import json
        entry = json.loads(out.read_text(encoding="utf-8"))["cases"][0]
        assert "assertions_fired" not in entry and "unfailable_green" not in entry


# ── 缺陷四：确认死循环「同事实」判据 + 附原文摘要 ─────────────────────────────


class TestConfirmLoopSameFactCriterion:
    def test_three_identical_content_cards_still_red(self):
        """**红证 A**：3 张内容相同的卡 ⇒ 仍判死循环（检测器不失效）。"""
        card = {"component": "confirm", "title": "确认创建商品",
                "confirmValue": "确认：加工项=刺绣工艺；分类=窗帘布艺；单价=100"}
        issues = lr.check_confirm_loop([_confirm_round(4, card), _confirm_round(5, card),
                                        _confirm_round(6, card)])
        assert len(issues) == 1, issues
        assert "R4/R5/R6" in issues[0], issues[0]
        assert "确认：加工项=刺绣工艺" in issues[0], (
            f"失败信息未附卡的原文摘要 —— 复核无法独立完成: {issues[0]}")
        assert "判据=内容键" in issues[0], issues[0]

    def test_three_different_content_cards_no_false_positive(self):
        """**红证 B**：3 张内容不同的卡（confirmValue 事实不同）⇒ 不得误报。

        改前改后一致不误报（内容键天然区分）；本测试同时锁「不同事实 ≠ 同批事实」
        判据本身 —— 把卡内容改成相同 ⇒ 本测试必红（防止夹具退化）。
        """
        cards = [_confirm_round(4, {"component": "confirm", "title": "确认创建商品",
                                    "confirmValue": "加工项=刺绣工艺"}),
                 _confirm_round(5, {"component": "confirm", "title": "确认创建商品",
                                    "confirmValue": "加工项=刺绣工艺、高温定型"}),
                 _confirm_round(6, {"component": "confirm", "title": "确认创建商品",
                                    "confirmValue": "加工项=刺绣工艺、高温定型、定型"})]
        assert lr.check_confirm_loop(cards) == [], "不同事实的卡被判成死循环（误报）"
        # 防退化：内容改为相同 ⇒ 必须判红（否则本用例是空断言）
        same = [_confirm_round(4, {"component": "confirm", "title": "确认创建商品",
                                   "confirmValue": "加工项=刺绣工艺"})]
        assert lr.check_confirm_loop(same + same + same), "内容相同的卡没被判定（夹具退化）"

    def test_title_only_same_title_cards_still_detected_fail_closed(self):
        """无内容（无 confirmValue/fields）的同标题卡 ×3 ⇒ 仍判死循环（fail-closed 历史契约，
        `backend/ai-agent-service/tests/test_acceptance_case_checks.py::TestConfirmLoop`
        「同标题 confirm 卡 >=3 次未收敛」），但失败信息必须**显式标注「按标题近似」**。"""
        cards = [_confirm_round(4, {"component": "confirm", "title": "确认创建商品"}),
                 _confirm_round(5, {"component": "confirm", "title": "确认创建商品"}),
                 _confirm_round(6, {"component": "confirm", "title": "确认创建商品"})]
        issues = lr.check_confirm_loop(cards)
        assert len(issues) == 1, issues
        assert "按标题近似" in issues[0], (
            f"无内容卡的计数没被标注为近似 —— 复核者会把近似当成已核实的同样事实: {issues[0]}")
        assert "无 confirmValue/fields" in issues[0], issues[0]
        assert "判据=内容键" in issues[0], issues[0]

    def test_two_title_only_cards_still_tolerated(self):
        """无内容同标题 2 次仍容忍（< limit），不误报。"""
        cards = [_confirm_round(1, {"component": "confirm", "title": "确认创建商品"}),
                 _confirm_round(2, {"component": "confirm", "title": "确认创建商品"})]
        assert lr.check_confirm_loop(cards) == []

    def test_fields_based_key_still_counts(self):
        """无 confirmValue 但 fields 相同 ⇒ 仍按内容键计数（同事实）。"""
        card = {"component": "confirm", "title": "确认创建商品",
                "fields": [{"label": "加工项", "value": "刺绣工艺"}]}
        issues = lr.check_confirm_loop([_confirm_round(1, card), _confirm_round(2, card),
                                        _confirm_round(3, card)])
        assert len(issues) == 1 and "R1/R2/R3" in issues[0], issues
        assert "加工项=刺绣工艺" in issues[0], issues[0]

    def test_two_cards_still_tolerated(self):
        """2 次以内容忍（顾客取消后重新确认）不判死循环。"""
        card = {"component": "confirm", "title": "确认创建商品",
                "confirmValue": "加工项=刺绣工艺"}
        assert lr.check_confirm_loop([_confirm_round(1, card), _confirm_round(2, card)]) == []
