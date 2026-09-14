"""失败指纹必须 **根因稳定**（root-cause-stable）——确定性失败不得被洗成 LLM 波动。

## 为什么需要这组守卫（issue #3728）

`local_runner._failure_signature` 是「两次失败是不是同一个根因」的唯一判据，
它决定 `_classify_attempts` 出 `reproducible` 还是 `unstable`，而 `completion_verdict`
按放行档（`_COMPLETION_RELEASED_CLASSES`）决定"这条红灯能不能按波动放过去"。
旧实现把**断言渲染文本**当指纹（`exp` + 细节前 60 字）→ 同一根因经由不同断言路径
渲染、尾随细节不同、组件条数不同，就判成 `unstable` → 当时按「LLM 波动」放行 →
`deterministic_failures=[]` → `completion.ok` 由 false 变 true（**假绿**）。

### 两个真实形态（都要盖住，本文件各有一个逐字夹具）

- **形态 A（PG-016，run 34846098440 / SHA `4c466d4d`）＝ 同根因、不同措辞**：
  两次失败的第 0/1 组件逐字相同（`must_succeed: … 从未被调用`、
  `output_verify[…] 找不到成功调用的结果`）——根因同一个：agent **从未成功调用**
  `processing_order_update(action=complete)`；差异只在第 2/3 组件（`unmatched
  expectation: …(action=complete)` vs `tool '…' matched but arg 'action' expected …`，
  且 `required_args: 未调用 …` 只在一次里出现）⇒ 靠**归并**解决 ⇒ `reproducible`。
- **形态 B（OR-014，run 34841029062 / SHA `1b3d2f2a`）＝ 两次皆败、成因不同**：
  一次"下单成功但**金额错**（168≠198）"、一次"**`order_create` 从未被调用**"，
  两次渲染组件**零重叠** ⇒ 指纹本就该不同 ⇒ `unstable`。**归并解决不了它** ——
  它的问题在**放行档**：两次都没通过，「LLM 波动放行」的前提（有一次是对的）不成立
  ⇒ 必须阻塞（口径变更，**待裁定**）。

## 守卫（缺一不可）

1. **同根因归并（形态 A）**：PG-016 真实两条指纹归一后**相同** ⇒ `reproducible`；
2. **异根因区分**：真不同的失败（工具从未调用 vs 载荷参数/产出不符）指纹**必须不同**
   ⇒ 仍 `unstable`（防把签名做成常量）；
3. **退化守卫（双向）**：小语料逐条断言分类结果 —— 既防「签名恒等」（全变 reproducible
   → 刷红），也防「签名恒不等」（全变 unstable → 继续洗白）；
4. **不许放宽**：真确定性失败仍确定性；真 LLM 波动（首次失败 + 重试通过）仍放行；
5. **两次皆败不得放行（形态 B）**：PG-016 与 OR-014 两个形态**都**进阻塞桶；
   台账 `released` 字段与放行档同源。

夹具还原口径：台账条目只留**渲染串**（`exp|detail[:60]` 排序去重后 `||` 连接），
故按 `||` 拆组件、每组件按**最后一个** `|` 拆回 `(exp, detail)`；唯一的有损处是 detail
的 60 字截断（不影响任何断言）。
"""
# case_ids: PG-016, OR-014
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

# ── OR-014 真实夹具（逐字取自 run 34841029062 / SHA 1b3d2f2a 的 flake 台账）──
# 第二个形态：**两次都真失败、但成因不同**（不是同一根因的两种措辞）——
#   第 1 次：下单成功但**金额错**（「遮光窗帘」单价 168.0 ≠ 商品库 198.0，凭记忆报价）
#   第 2 次：**order_create 从未被调用**（无写操作、金额无从核对）
# 两次的渲染组件**零重叠** ⇒ 旧口径判 `unstable` ⇒ 按"LLM 发散"放行；但它 2/2 都真失败，
# 没有一次通过 —— 「波动放行」的前提（其中一次是对的）根本不成立。
OR014_FIRST = (
"amount_verify[order_create](R7): 「遮光窗帘」单价 168.0 ≠ 商品库 198.0（凭记忆报价？）|case-level check"
)
OR014_SECOND = (
"amount_verify: 未找到 order_create 的成功调用（金额无从核对）|case-level check||must_succeed: order_create 从未被调用 → 没有发生任何写操作（期望里的工具名出现≠工具真的跑了）|case-level check||order_create|unmatched expectation: order_create"
)

# ── AS-004 真实夹具（逐字取自 run 34849029334 / SHA 929732b4 的 flake 台账）──
# 第三个形态：**指纹子集** —— 首败的失败项是次败的**真子集**（次败只多挂 1 条断言）。
#   首败（2 条，都是**实质**落库断言）：
#     · 「落库字段 closeReason 为空」（关闭态必须写入 closedAt/closeReason）
#     · 「closeReason None 不含期望 '协商一致'」
#   次败（3 条）= 上面 2 条 **+** `after_sales_manage(action=update_status, …)
#     unmatched expectation`（当次额外抖出来的一条）
# ⇒ 共有部分（两条 db_verify 实质失败）**稳定复现** ⇒ 应为 `reproducible`；机械按
# "指纹不同"判 `unstable` 会让真回归被洗成波动，且 `deterministic_failures` **漏计**。
AS004_FIRST = (
"db_verify[after_sales_ticket]: 工单 tkt_eval_as_9001 落库 closeReason None 不含期望 '协商一致' —— 用户点名的关闭原因必须落到 closeReason|case-level check||db_verify[after_sales_ticket]: 工单 tkt_eval_as_9001 落库字段 closeReason 为空（关闭态必须写入 closedAt/closeReason；只记 internalNotes 不算关闭留痕）|case-level check"
)
AS004_SECOND = (
"after_sales_manage(action=update_status, status=closed)|unmatched expectation: after_sales_manage(action=update_stat||db_verify[after_sales_ticket]: 工单 tkt_eval_as_9001 落库 closeReason None 不含期望 '协商一致' —— 用户点名的关闭原因必须落到 closeReason|case-level check||db_verify[after_sales_ticket]: 工单 tkt_eval_as_9001 落库字段 closeReason 为空（关闭态必须写入 closedAt/closeReason；只记 internalNotes 不算关闭留痕）|case-level check"
)

# ── OR-026 真实夹具（逐字取自 run 34849029334 / SHA 929732b4 的 **xiaobu** 台账）──
# 形态②（两次皆败、成因不同，且**无包含关系**）：
#   首败：「order_create 共 2 次调用**无一成功**（R3/R4: confirmation_required_no_card）」
#         + `db_verify[order_phone]: 找不到成功调用`（无订单落库）
#   次败：「状态宣告无工具落地(R2): 回复称「已更新」，但截至本轮没有任何写工具成功」
# ⇒ 交集为空 ⇒ `unstable`（不属放行档 ⇒ 默认阻塞）。该 run 的 xiaobu 腿
# `completion.ok` **正是建立在这条放行上**（旧口径 ok=true）。
OR026_FIRST = (
"db_verify[order_phone]: 找不到 order_create 的成功调用（无订单可核对）—— 判失败而非跳过|case-level check||must_succeed: order_create 共 2 次调用**无一成功**（R3:confirmation_required_no_card, R4:confirmation_required_no_card）—— 调了 ≠ 成了|case-level check"
)
OR026_SECOND = (
"状态宣告无工具落地(R2): 回复称「已更新」，但截至本轮没有任何写工具成功（草稿态不得用完成态措辞）|case-level check"
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


def _or014_first():
    return _attempt_from_rendered(OR014_FIRST)


def _or014_second():
    return _attempt_from_rendered(OR014_SECOND)


def _as004_first():
    return _attempt_from_rendered(AS004_FIRST)


def _as004_second():
    return _attempt_from_rendered(AS004_SECOND)


def _or026_first():
    return _attempt_from_rendered(OR026_FIRST)


def _or026_second():
    return _attempt_from_rendered(OR026_SECOND)


CASE_LEVEL = "case-level check"

# 旧的**放行档**（改前口径，见 `local_runner._COMPLETION_RELEASED_CLASSES` 的历史值）：
# `unstable` 曾与 `llm-noise` 一并放行。这里显式留一份旧值，用来证明 OR-014 的夹具
# 「改前会被放行」（改前必红），而不是靠一句注释断言。
LEGACY_RELEASED_CLASSES = frozenset({"llm-noise", "unstable"})


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

    def test_verdict_blocks_it_under_both_layers_of_the_fix(self):
        """修复的**影响**：PG-016 现在被阻塞，而且**两层独立成立**——
        ① 分类由 `unstable` 变 `reproducible`（本 PR① 的指纹修复）；
        ② 放行档只剩 `llm-noise`（本 PR② 的口径变更，`unstable` 被移出放行档）。
        任一层单独成立就足以阻塞，故这条不再依赖"旧口径会放行"的断言。"""
        first, second = _pg016_first(), _pg016_second()
        cls = lr._classify_attempts(first, second)
        now = lr.completion_verdict([dict(second, case_id="PG-016", classification=cls)])
        assert now["deterministic_failures"] == ["PG-016"]
        assert now["flake_released"] == []
        assert now["ok"] is False
        assert cls == "reproducible", "① 指纹修复：同根因不同措辞必须归并 ⇒ reproducible"
        assert "unstable" not in lr._COMPLETION_RELEASED_CLASSES, "② 口径变更：unstable 不再放行"


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
        action 的）参数值不符」 —— B 多出一条载荷层违反 ⇒ **指纹必须不同**。

        ⚠️ 与规则③（子集 ⇒ `reproducible`）的**交界**（必须一起读）：
        指纹不同**不等于**必然 `unstable`。这里 B 的原子集是 A 的**超集**
        （共有 `no_success(tool)` 这个稳定核心），故分类是 `reproducible`
        —— 两种判据服务不同目的：**指纹**回答"是不是同一件事"，
        **分类**回答"这条红灯该怎么处置"；"多挂一条断言"不改变共有核心的确定性。
        """
        never = _attempt([
            ("must_succeed: processing_order_update 从未被调用 → 没有发生任何写操作", CASE_LEVEL)])
        other_action = _attempt([
            ("processing_order_update(action=complete)",
             "unmatched expectation: processing_order_update(action=comple"),
            ("required_args[processing_order_update.orderId](R4): 字段 orderId 缺失或为空",
             CASE_LEVEL),
        ])
        assert lr._failure_signature(never) != lr._failure_signature(other_action)
        a, b = lr._failure_atoms(never), lr._failure_atoms(other_action)
        assert a < b, "该形态是**真子集**（共有 no_success 核心 + B 多一条载荷层违反）"
        assert lr._classify_attempts(never, other_action) == "reproducible"

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
    # ── ③ 指纹子集（AS-004 真实夹具）与两个新形态的真实台账 ──
    ("③ 子集：AS-004 真实夹具（首败 ⊂ 次败 ⇒ 共有部分稳定复现）",
     _as004_first(), _as004_second(), "reproducible"),
    ("③ 子集：次败 ⊂ 首败（方向相反，同样是稳定复现）",
     _as004_second(), _as004_first(), "reproducible"),
    ("⑥ 两次皆败、成因不同：OR-026 真实夹具（无包含关系 ⇒ unstable）",
     _or026_first(), _or026_second(), "unstable"),
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

    def test_unstable_classification_preserved_but_no_longer_released(self):
        """真发散（两次是不同的违反点）仍被**识别**为 `unstable`（分类档没被关死），
        但自**口径变更**起它不再进放行档 —— 两次都没通过就没有"波动"证据。"""
        a = _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)],
                     score=0.4)
        b = _attempt([("db_verify[order_phone]: 订单 20260913384380002 落库手机号 13800008000 "
                       "≠ 期望 13800138000", CASE_LEVEL)], score=0.0)
        assert lr._classify_attempts(a, b) == "unstable"
        verdict = lr.completion_verdict([dict(b, case_id="OR-001", classification="unstable")])
        assert verdict["flake_released"] == []
        assert verdict["deterministic_failures"] == ["OR-001"]
        assert verdict["ok"] is False

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


# ── 守卫 ⑤：两次皆败（无一次通过）不是「LLM 波动」——第二个真实形态 OR-014 ────────
#
# PG-016 与 OR-014 是**两个不同形态**，都要盖住：
#   · PG-016 = 同一根因、诊断细节/断言路径不同（指归并成同一指纹 ⇒ reproducible）；
#   · OR-014 = **两次都真失败、但成因不同**（指纹本就该不同 ⇒ unstable）——
#     与 PG-016 相反，**不能**靠归并解决；它的问题在**放行档**：两次都没通过，
#     「LLM 波动放行」的前提（其中一次是对的）不成立 ⇒ 必须阻塞。

class TestBothAttemptsFailedNotReleasable:
    """`unstable`（两次皆败、成因不同）**不得**被当作可放行波动（口径变更，待裁定）。"""

    def test_or014_fixture_is_the_both_failed_shape(self):
        """夹具自证形态：两次的渲染组件**零重叠**、指纹不同 ⇒ 分类是 `unstable`
        （而不是 PG-016 那种"同根因不同措辞"⇒ `reproducible`）。"""
        first, second = _or014_first(), _or014_second()
        comp_a = {c for c in OR014_FIRST.split("||") if c}
        comp_b = {c for c in OR014_SECOND.split("||") if c}
        if comp_a & comp_b:
            import pytest
            pytest.fail(f"夹具两次组件有重叠（{comp_a & comp_b}）—— 它不是 OR-014 的真实台账")
        assert lr._failure_signature(first) != lr._failure_signature(second)
        assert lr._classify_attempts(first, second) == "unstable"

    def test_or014_fixture_captures_both_real_failures(self):
        """两条渲染串各自代表一次**真失败**：一次"金额算错"、一次"写工具从未调用"。"""
        assert "单价 168.0 ≠ 商品库 198.0" in OR014_FIRST
        assert "must_succeed: order_create 从未被调用" in OR014_SECOND
        assert lr._failure_signature(_or014_second()) == "no_success(order_create)"

    def test_or014_must_not_be_released(self):
        """**改前必红**：OR-014 两次皆败 ⇒ 不得进放行档；必须在阻塞桶里。"""
        first, second = _or014_first(), _or014_second()
        cls = lr._classify_attempts(first, second)
        verdict = lr.completion_verdict([dict(second, case_id="OR-014", classification=cls)])
        assert verdict["flake_released"] == []
        assert verdict["deterministic_failures"] == ["OR-014"]
        assert verdict["ok"] is False

    def test_legacy_policy_would_have_released_it(self):
        """改前必红的**证据**：用旧的放行档（含 `unstable`）跑同一条失败 ⇒ 会被放行。
        这一条把"改前必红"变成可执行断言，而不是注释里的一句话。"""
        second = _or014_second()
        released_cases = ["OR-014"] if "unstable" in LEGACY_RELEASED_CLASSES else []
        assert released_cases == ["OR-014"], "旧放行档应含 unstable —— 夹具才有'改前被放行'的性质"
        blocked = [c for c in ["OR-014"]
                   if "unstable" not in lr._COMPLETION_RELEASED_CLASSES]
        assert blocked == ["OR-014"], "新放行档不含 unstable ⇒ 同一条现在必须阻塞"
        assert lr.completion_verdict(
            [dict(second, case_id="OR-014", classification="unstable")])["ok"] is False

    def test_both_shapes_are_covered_and_both_block(self):
        """两形态并列：PG-016（同根因）⇒ `reproducible`；OR-014（成因不同）⇒ `unstable`；
        **两者都阻塞**（一个都不许被当成波动放行）。"""
        shapes = [
            ("PG-016", _pg016_first(), _pg016_second(), "reproducible"),
            ("OR-014", _or014_first(), _or014_second(), "unstable"),
        ]
        wrong = []
        for cid, a, b, expect in shapes:
            got = lr._classify_attempts(a, b)
            v = lr.completion_verdict([dict(b, case_id=cid, classification=got)])
            if got != expect:
                wrong.append(f"{cid}: 期望分类 {expect} 实得 {got}")
            if v["ok"] is not False or cid not in v["deterministic_failures"]:
                wrong.append(f"{cid}: 未被阻塞（ok={v['ok']} buckets={v}")
        if wrong:
            import pytest
            pytest.fail("两形态守卫失败：\n  - " + "\n  - ".join(wrong))

    def test_llm_noise_positive_still_released(self):
        """防"凡失败即阻塞"的另一半退化：**首次失败 + 重试通过**（`llm-noise`）仍放行。
        两种形态都要成立：① 判定输入里 `llm-noise` 且 score<1（放行档本身）；
        ② 真实链路里重试通过 → 该用例 score=1.0（verdict 根本不会把它算成失败）。"""
        first = _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)])
        second = _attempt([], score=1.0)
        assert lr._classify_attempts(first, second) == "llm-noise"
        # ① 放行档：llm-noise 分类的失败仍进 flake_released（唯一的放行档）
        verdict = lr.completion_verdict([dict(first, case_id="OR-014", classification="llm-noise")])
        assert verdict["flake_released"] == ["OR-014"]
        assert verdict["deterministic_failures"] == []
        assert verdict["ok"] is True
        # ② 真实链路：重试通过 ⇒ score=1.0 ⇒ 既不放行也不阻塞（它本来就通过了）
        passed = lr.completion_verdict([dict(second, case_id="OR-014", classification="llm-noise")])
        assert passed["deterministic_failures"] == []
        assert passed["ok"] is True

    def test_ledger_self_declares_release_state(self):
        """台账自证放行与否（口径变更后"分类名"已读不出处置）。"""
        first, second = _or014_first(), _or014_second()
        blocked = lr.build_flake_entry("OR-014", "t", "unstable", first, second, "r", "s")
        released = lr.build_flake_entry("OR-014", "t", "llm-noise", first, second, "r", "s")
        assert blocked["released"] is False
        assert released["released"] is True
        for entry in (blocked, released):
            assert entry["released"] == (entry["classification"] in lr._COMPLETION_RELEASED_CLASSES)


# ── 守卫 ⑥：指纹**子集** ⇒ 共有部分稳定复现（第三个真实形态 AS-004）─────────────
#
# 纯结构判据（集合包含），不需要语义理解；挡的是最机械的漏网：**"第二次多挂一条断言"
# 就把确定性回归洗成"发散"**。AS-004 实证：两次共有的两条 db_verify 实质失败
# （落库 closeReason 为空 / 不等期望值）逐字相同，次败只多一条 `unmatched expectation`。

class TestSubsetFingerprintIsReproducible:
    def test_as004_fixture_is_a_real_strict_subset(self):
        """夹具自证形态：**渲染串**层面首败 ⊂ 次败（次败 = 首败 + 1 条）。"""
        comp_a = {c for c in AS004_FIRST.split("||") if c}
        comp_b = {c for c in AS004_SECOND.split("||") if c}
        if not comp_a < comp_b:
            import pytest
            pytest.fail(f"AS-004 夹具不是真子集（A={len(comp_a)} B={len(comp_b)}）—— 夹具已被改写")
        assert len(comp_b) - len(comp_a) == 1

    def test_as004_normalized_atoms_are_also_nested(self):
        """归一后**仍是**包含关系（归一把两条 db_verify 变成两个稳定字段身份）。"""
        a, b = lr._failure_atoms(_as004_first()), lr._failure_atoms(_as004_second())
        assert a < b
        assert sorted(a) == ["db_empty(after_sales_ticket,closeReason)",
                            "db_mismatch(after_sales_ticket,close_reason)"]
        assert "no_success(after_sales_manage)" in b

    def test_as004_classifies_reproducible_and_blocks(self):
        """**改前必红**（规则③实现前它被判 `unstable`）：共有部分稳定复现 ⇒ reproducible。"""
        first, second = _as004_first(), _as004_second()
        assert lr._failure_signature(first) != lr._failure_signature(second), (
            "两条指纹本就不同（不是 PG-016 那种同根因不同措辞）—— 靠的是子集规则")
        assert lr._classify_attempts(first, second) == "reproducible"
        verdict = lr.completion_verdict(
            [dict(second, case_id="AS-004", classification="reproducible")])
        assert verdict["deterministic_failures"] == ["AS-004"]
        assert verdict["ok"] is False

    def test_extra_assertion_does_not_flip_determinism(self):
        """素形态：核心失败相同 + 次败多一条无关断言 ⇒ 仍 `reproducible`（双向都成立）。"""
        core = [("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)]
        extra = core + [("forbidden_text: 回复含反模式词「暂不支持」（R5）", CASE_LEVEL)]
        a, b = _attempt(core), _attempt(extra)
        assert lr._classify_attempts(a, b) == "reproducible"
        assert lr._classify_attempts(b, a) == "reproducible"

    def test_disjoint_failures_are_not_swallowed_by_the_subset_rule(self):
        """防过并：**交集为空**（真不同根因）不受子集规则影响 ⇒ 仍 `unstable`。"""
        a = _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作", CASE_LEVEL)])
        b = _attempt([("db_verify[order_phone]: 订单 20260913384380002 落库手机号 13800008000 "
                       "≠ 期望 13800138000", CASE_LEVEL)])
        assert not (lr._failure_atoms(a) & lr._failure_atoms(b))
        assert lr._classify_attempts(a, b) == "unstable"

    def test_empty_side_does_not_trigger_the_subset_rule(self):
        """防真空包含：`∅ ⊆ X` 恒真，故**共有部分必须非空** —— 空指纹一侧不得把
        "这次没记录到失败"洗成"稳定复现"。"""
        empty = _attempt([], score=0.0)
        nonempty = _attempt([("must_succeed: order_create 从未被调用 → 没有发生任何写操作",
                              CASE_LEVEL)])
        atoms_empty, atoms_nonempty = lr._failure_atoms(empty), lr._failure_atoms(nonempty)
        assert atoms_empty == frozenset()
        assert atoms_empty & atoms_nonempty == frozenset()
        assert lr._classify_attempts(empty, nonempty) == "unstable"


# ── 守卫 ⑦：OR-026（两次皆败、成因不同、无包含关系）——第二个真实台账 ────────────

class TestBothFailedDifferentCausesFixture:
    def test_or026_fixture_atoms_are_disjoint(self):
        """夹具自证形态：首败 =「调了但无一成功 + 无订单落库」，次败 =「声称已更新但零写成功」，
        两边**无共有原子**（所以它落在 `unstable`，不是 AS-004 那种子集）。"""
        a, b = lr._failure_atoms(_or026_first()), lr._failure_atoms(_or026_second())
        assert a == frozenset({"no_success(order_create)"})
        assert b == frozenset({"unbacked_state_claim"})
        assert a & b == frozenset()

    def test_or026_must_not_be_released(self):
        """**改前必红**：run 34849029334 的 xiaobu 腿 `completion.ok=true` 就建立在
        这条 `unstable` 被放行上；新口径下它必须进阻塞桶。"""
        first, second = _or026_first(), _or026_second()
        assert lr._classify_attempts(first, second) == "unstable"
        verdict = lr.completion_verdict(
            [dict(second, case_id="OR-026", classification="unstable")])
        assert verdict["flake_released"] == []
        assert verdict["deterministic_failures"] == ["OR-026"]
        assert verdict["ok"] is False

    def test_or026_was_the_run_that_flipped_xiaobu_verdict(self):
        """这条夹具对应**历史结论翻转**：run 34849029334 xiaobu 旧口径 `ok=true`
        （1 条放行波动）→ 新口径 `ok=false`。此处用同一份输入重放两个口径。"""
        second = _or026_second()
        legacy_ok = not [c for c in ["OR-026"] if "unstable" not in LEGACY_RELEASED_CLASSES]
        assert legacy_ok is True, "旧放行档含 unstable ⇒ 该 run 旧口径判 ok"
        assert lr.completion_verdict(
            [dict(second, case_id="OR-026", classification="unstable")])["ok"] is False
