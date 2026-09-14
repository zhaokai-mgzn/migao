"""失败指纹必须 **根因稳定**（root-cause-stable）——确定性失败不得被洗成 LLM 波动。

## 为什么需要这组守卫（issue #3728）

`local_runner._failure_signature` 是「两次失败是不是同一个根因」的唯一判据，
它决定 `_classify_attempts` 出 `reproducible` 还是 `unstable`，而 `completion_verdict`
把 `unstable` 与 `llm-noise` 一并**放行**（`_COMPLETION_RELEASED_CLASSES`）。
旧实现把**断言渲染文本**当指纹（`exp` + 细节前 60 字）→ 同一根因经由不同断言路径
渲染、尾随细节不同、组件条数不同，就判成 `unstable` → 按「LLM 波动」放行 →
`deterministic_failures=[]` → `completion.ok` 由 false 变 true（**假绿**）。

实证（**本文件里是逐字真实夹具**，取自 run 34846098440 / SHA `4c466d4d` 的
`post-deploy-eval-mibao/agent-eval-flakes.json` 的 PG-016 条目，台账里
`classification: unstable`）：两次失败的第 0/1 组件逐字相同（`must_succeed: … 从未被
调用`、`output_verify[…] 找不到成功调用的结果`）——根因同一个：agent **从未成功调用**
`processing_order_update(action=complete)`；差异只在第 2/3 组件（`unmatched
expectation: …(action=complete)` vs `tool '…' matched but arg 'action' expected …`，
且 `required_args: 未调用 …` 只在一次里出现）。

## 四个守卫（缺一不可）

1. **同根因归并**：PG-016 真实两条指纹归一后**相同** ⇒ `reproducible`；
2. **异根因区分**：真不同的失败（工具从未调用 vs 载荷参数/产出不符）指纹**必须不同** ⇒
   仍 `unstable`（防把签名做成常量）；
3. **退化守卫（双向）**：小语料逐条断言分类结果 —— 既防「签名恒等」（全变 reproducible
   → 刷红），也防「签名恒不等」（全变 unstable → 继续洗白）；
4. **不许放宽**：真确定性失败仍确定性；真 LLM 波动（重试通过）仍放行。

夹具还原口径：台账条目只留**渲染串**（`exp|detail[:60]` 排序去重后 `||` 连接），
故按 `||` 拆组件、每组件按**最后一个** `|` 拆回 `(exp, detail)`；唯一的有损处是 detail
的 60 字截断（不影响任何断言）。
"""
# case_ids: PG-016
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner_sig", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()

# ── PG-016 真实夹具（逐字取自 run 34846098440 / SHA 4c466d4d 的 flake 台账）──
PG016_FIRST = (
"must_succeed: processing_order_update 从未被调用 → 没有发生任何写操作（期望里的工具名出现≠工具真的跑了）|case-level check||output_verify[processing_order_update](action=complete): 找不到成功调用的结果（无从核对产出）|case-level check||processing_order_update(action=complete)|tool 'processing_order_update' matched but arg 'action' expe"
)
PG016_SECOND = (
'must_succeed: processing_order_update 从未被调用 → 没有发生任何写操作（期望里的工具名出现≠工具真的跑了）|case-level check||output_verify[processing_order_update](action=complete): 找不到成功调用的结果（无从核对产出）|case-level check||processing_order_update(action=complete)|unmatched expectation: processing_order_update(action=comple||required_args: 未调用 processing_order_update(action=None)|case-level check'
)


def _attempt(failed, last_error=None, score=0.0):
    """一次失败尝试的结果字典（`failed` = [(断言/检查, 细节)]）。"""
    return {"failed": list(failed), "last_error": last_error, "score": score}


def _attempt_from_rendered(sig):
    """渲染串 → 尝试字典（与 `_failure_signature` 的构造式互逆，见模块 docstring）。"""
    failed = []
    for comp in [c for c in str(sig).split("||") if c]:
        exp, _, detail = comp.rpartition("|")
        failed.append((exp, detail))
    return _attempt(failed)


def _legacy_signature(result):
    """**旧实现**的指纹公式（改前口径），仅用于证明夹具「改前必红」。"""
    parts = sorted({f"{exp}|{str(detail)[:60]}" for exp, detail in result.get("failed", [])})
    if result.get("last_error"):
        parts.append(f"error|{str(result['last_error'])[:100]}")
    return "||".join(parts)


def _pg016_first():
    return _attempt_from_rendered(PG016_FIRST)


def _pg016_second():
    return _attempt_from_rendered(PG016_SECOND)


CASE_LEVEL = "case-level check"


# ── 守卫 ①：同根因 ⇒ 同一指纹（PG-016 真实夹具）──────────────────────────────

class TestSameRootCauseMerges:
    """PG-016 的两次失败是**同一个根因**（「声明的那次调用没成功发生」），
    只是经由不同断言路径渲染 —— 指纹必须相同 ⇒ 判 `reproducible`（改前判 `unstable`）。"""

    def test_fixture_is_a_real_change_case(self):
        """夹具自证「改前必红」：旧口径下两条渲染串**不同**（所以旧代码判 `unstable`）。

        这一条在改前改后都成立 —— 它证明夹具不是「本来就相等」的空夹具。
        """
        first, second = _pg016_first(), _pg016_second()
        if _legacy_signature(first) == _legacy_signature(second):
            import pytest
            pytest.fail("夹具两次渲染串相同 —— 它不是 PG-016 的真实夹具（改前必红的前提不成立）")
        if first["failed"][0] != second["failed"][0]:
            import pytest
            pytest.fail("夹具第 0 组件应逐字相同（真实台账如此），否则夹具已被改写")

    def test_same_root_cause_same_signature(self):
        """**改前必红**：旧实现两条指纹不同；新实现必须归一成同一个 token。"""
        first, second = _pg016_first(), _pg016_second()
        assert lr._failure_signature(first) == lr._failure_signature(second)
        assert lr._failure_signature(first) == "no_success(processing_order_update)"
        assert lr._classify_attempts(first, second) == "reproducible"

    def test_verdict_blocks_it_now_and_would_have_released_it_before(self):
        """修复的**影响**：同一条失败，`reproducible` 进确定性失败（`ok=False`）；
        若仍判 `unstable`（= 本次修掉的假绿通道）则被放行（`ok=True`）。"""
        first, second = _pg016_first(), _pg016_second()
        cls = lr._classify_attempts(first, second)
        now = lr.completion_verdict([dict(second, case_id="PG-016", classification=cls)])
        assert now["deterministic_failures"] == ["PG-016"]
        assert now["flake_released"] == []
        assert now["ok"] is False
        before = lr.completion_verdict([dict(second, case_id="PG-016", classification="unstable")])
        assert before["deterministic_failures"] == []
        assert before["flake_released"] == ["PG-016"]
        assert before["ok"] is True


# ── 守卫 ②：真不同根因 ⇒ 不同指纹（防把签名做成常量）──────────────────────────

class TestDifferentRootCausesStayDifferent:
    """签名**不能是常量** —— 否则真波动会被判成确定性失败（刷红），
    也会让 `unstable` 这一档失去意义。"""

    def test_never_called_vs_payload_and_output_mismatch(self):
        never = _attempt([
            ("must_succeed: processing_order_update 从未被调用 → 没有发生任何写操作"
             "（期望里的工具名出现≠工具真的跑了）", CASE_LEVEL),
            ("output_verify[processing_order_update](action=complete): 找不到成功调用的结果"
             "（无从核对产出）", CASE_LEVEL),
        ])
        payload = _attempt([
            ("processing_order_update(action=complete, id=A1)",
             "tool 'processing_order_update' matched but arg 'id' expected A1 got B2"),
            ("output_verify[processing_order_update]: 结果里没有字段 'status'"
             "（实际字段: ['action', 'id']）", CASE_LEVEL),
        ])
        assert lr._failure_signature(never) != lr._failure_signature(payload)
        assert lr._classify_attempts(never, payload) == "unstable"

    def test_never_called_vs_other_action_arg_mismatch(self):
        """字面口径的对照：A=「工具从未被调用」vs B=「工具被调用了，但（另一个
        action 的）参数值不符」 —— B 多出一条载荷层违反 ⇒ 指纹必须不同。"""
        never = _attempt([
            ("must_succeed: processing_order_update 从未被调用 → 没有发生任何写操作", CASE_LEVEL)])
        other_action = _attempt([
            ("processing_order_update(action=complete)",
             "unmatched expectation: processing_order_update(action=comple"),
            ("required_args[processing_order_update.orderId](R4): 字段 orderId 缺失或为空",
             CASE_LEVEL),
        ])
        assert lr._failure_signature(never) != lr._failure_signature(other_action)
        assert lr._classify_attempts(never, other_action) == "unstable"

    def test_action_selector_is_not_a_payload_key(self):
        """归一的**边界**（本次修复的核心取舍，必须锁住）：
        `action` 是**调用选择器** —— 它不符 ≡ 「声明的那次调用没发生」（与
        `unmatched expectation` 归一）；`action` **之外**的键不符是载荷层违反
        （≠ 没发生）。两者方向相反，锁在同一处以免以后被"顺手"改坏。"""
        never = _attempt([
            ("must_succeed: processing_order_update 从未被调用 → 没有发生任何写操作", CASE_LEVEL)])
        selector = _attempt([
            ("processing_order_update(action=complete)",
             "tool 'processing_order_update' matched but arg 'action' expected complete got query")])
        payload = _attempt([
            ("processing_order_update(action=complete, id=A1)",
             "tool 'processing_order_update' matched but arg 'id' expected A1 got B2")])
        assert lr._failure_signature(selector) == lr._failure_signature(never)
        assert lr._failure_signature(payload) != lr._failure_signature(never)


# ── 守卫 ③：退化守卫（双向）────────────────────────────────────────────────

# (说明, 第一次尝试, 第二次尝试, 期望分类)
_DEGENERACY_CORPUS = (
    ("PG-016 真实夹具：同根因、渲染路径不同、组件条数 3 vs 4",
     _pg016_first(), _pg016_second(), "reproducible"),
    ("同根因：从未被调用 vs 调了但无一成功（错误码/轮次不同）",
     _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)]),
     _attempt([("must_succeed: order_create 共 2 次调用**无一成功**"
                "（R3:confirmation_required, R5:tool_execution_failed）—— 调了 ≠ 成了",
                CASE_LEVEL)]),
     "reproducible"),
    ("同根因：产出值不符（实际值不同、轮次不同）",
     _attempt([("output_verify[processing_order_update]: status 期望 'completed'，实际 'processing'",
                CASE_LEVEL)]),
     _attempt([("output_verify[processing_order_update]: status 期望 'completed'，实际 'issued'"
                "（差 0.0000）", CASE_LEVEL)]),
     "reproducible"),
    ("同根因：反模式词命中轮次不同",
     _attempt([("forbidden_text: 回复含反模式词「暂不支持」（R3）", CASE_LEVEL)]),
     _attempt([("forbidden_text: 回复含反模式词「暂不支持」（R9）", CASE_LEVEL)]),
     "reproducible"),
    ("异根因：调用从未发生 vs 载荷参数不符",
     _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)]),
     _attempt([("required_args[order_create.customer_phone](R6): 字段 customer_phone 缺失或为空",
                CASE_LEVEL)]),
     "unstable"),
    ("异根因：产出缺字段 vs 产出值不符",
     _attempt([("output_verify[processing_order_update]: 结果里没有字段 'status'（实际字段: [])",
                CASE_LEVEL)]),
     _attempt([("output_verify[processing_order_update]: status 期望 'completed'，实际 'issued'",
                CASE_LEVEL)]),
     "unstable"),
    ("异根因：调用从未发生 vs 落库字段不符",
     _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)]),
     _attempt([("db_verify[order_phone]: 订单 20260913384380002 落库手机号 13800008000 ≠ 期望 "
                "13800138000（掩码填充值会静默写错号码）", CASE_LEVEL)]),
     "unstable"),
    ("异根因：反模式词 vs 正向关键词缺失",
     _attempt([("forbidden_text: 回复含反模式词「暂不支持」（R2）", CASE_LEVEL)]),
     _attempt([("want_text: 全程回复未出现正向关键词「已完成」", CASE_LEVEL)]),
     "unstable"),
)


class TestDegeneracyGuard:
    """双向退化守卫：**签名恒等**（全变 `reproducible` → 刷红）与
    **签名恒不等**（全变 `unstable` → 继续洗白）都会被这组断言抓住。"""

    def test_every_corpus_pair_classifies_as_expected(self):
        wrong = []
        for label, first, second, expect in _DEGENERACY_CORPUS:
            got = lr._classify_attempts(first, second)
            if got != expect:
                wrong.append(f"{label}: 期望 {expect} 实得 {got}")
        if wrong:
            import pytest
            pytest.fail("分类与预期不符：\n  - " + "\n  - ".join(wrong))

    def test_corpus_covers_both_outcomes(self):
        """语料自身必须**双向**非空 —— 否则这组守卫会退化成单侧空转。"""
        got = [lr._classify_attempts(f, s) for _, f, s, _ in _DEGENERACY_CORPUS]
        if "reproducible" not in got or "unstable" not in got:
            import pytest
            pytest.fail(f"语料没有同时覆盖两种结论（reproducible/unstable），实得 {sorted(set(got))}")

    def test_signature_is_neither_constant_nor_injective(self):
        """指纹既**不是常量**（>1 个不同取值）也**不是恒不等**（语料里存在相等的两次签名）。"""
        sigs = [lr._failure_signature(f) for _, f, _, _ in _DEGENERACY_CORPUS] + \
               [lr._failure_signature(s) for _, _, s, _ in _DEGENERACY_CORPUS]
        assert len(set(sigs)) > 1, "指纹退化成常量 —— 所有失败都会被判成同一个根因"
        assert sum(1 for _, f, s, _ in _DEGENERACY_CORPUS
                   if lr._failure_signature(f) == lr._failure_signature(s)) >= 1, \
            "语料里没有任何一对同根因被判同指纹 —— 指纹退化成「恒不等」"


# ── 守卫 ④：不许放宽（真波动仍放行、真确定性失败仍确定性）──────────────────────

class TestNoLoosening:
    def test_real_llm_noise_still_released(self):
        """真波动：首跑失败、新 session 重试通过 → 仍 `llm-noise` 且**不算确定性失败**。"""
        first = _attempt([("must_succeed: processing_order_update 从未被调用 → x", CASE_LEVEL)])
        second = _attempt([], score=1.0)
        assert lr._classify_attempts(first, second) == "llm-noise"
        verdict = lr.completion_verdict([dict(second, case_id="PG-016", classification="llm-noise")])
        assert verdict["deterministic_failures"] == []
        assert verdict["ok"] is True

    def test_true_divergence_channel_still_open(self):
        """真发散（两次是不同的违反点）仍走 `unstable` 并被放行 ——
        修复**没有**把 `unstable` 档关死（那是"真波动被刷红"的另一半退化）。"""
        a = _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)],
                     score=0.4)
        b = _attempt([("db_verify[order_phone]: 订单 20260913384380002 落库手机号 13800008000 "
                       "≠ 期望 13800138000", CASE_LEVEL)], score=0.0)
        assert lr._classify_attempts(a, b) == "unstable"
        verdict = lr.completion_verdict([dict(b, case_id="OR-001", classification="unstable")])
        assert verdict["flake_released"] == ["OR-001"]
        assert verdict["deterministic_failures"] == []
        assert verdict["ok"] is True

    def test_real_deterministic_failure_still_deterministic(self):
        """真确定性失败：两次同一条断言同样地失败 → 仍 `reproducible`（不因修复被放行）。"""
        same = [("output_verify[processing_order_update]: status 期望 'completed'，实际 'issued'",
                 CASE_LEVEL)]
        first, second = _attempt(same, score=0.5), _attempt(same, score=0.0)
        assert lr._classify_attempts(first, second) == "reproducible"
        verdict = lr.completion_verdict([dict(second, case_id="PG-016", classification="reproducible")])
        assert verdict["deterministic_failures"] == ["PG-016"]
        assert verdict["ok"] is False

    def test_infra_and_error_kinds_still_distinguished(self):
        """运行级错误仍走 `infra`（先行分流）；错误**种类**不同仍不同指纹。"""
        assert lr._classify_attempts(_attempt([], last_error="httpx.ConnectError: connection refused"),
                                     _attempt([])) == "infra"
        a = _attempt([], last_error="AttributeError: 'list' object has no attribute 'strip'")
        b = _attempt([], last_error="KeyError: 'items'")
        assert lr._failure_signature(a) != lr._failure_signature(b)
        assert lr._classify_attempts(a, b) == "unstable"

    def test_flake_ledger_keeps_both_attempts_canonical(self):
        """台账（放行的唯一长期证据）存的是**规范指纹**，两次都在。"""
        first, second = _pg016_first(), _pg016_second()
        entry = lr.build_flake_entry("PG-016", "更新加工单状态", "reproducible",
                                     first, second, "run-x", "sha-y")
        assert entry["signature"] == entry["first_attempt_signature"]
        assert entry["signature"] == "no_success(processing_order_update)"
