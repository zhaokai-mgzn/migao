# case_ids: OR-014, OR-022, OR-024, CR-003, PR-019, OR-023
"""表单载荷**窗口**不变式（issue #3804）：载荷不得绑死在固定轮次上。

## 为什么需要这条守卫（判定跑 34873715194 铁证，零 LLM 可复算）

`OR-014` 判 `reproducible` / `score=0.0`，失败串 `order_create 从未被调用` —— 看起来像
"agent 不会下单"，实际是**用例资产 + harness 的窗口语义**问题：

- 客户信息载荷（`customer_name/phone/address/color`）原先**只声明在第 4、5 轮**，
  且**没有 case 级 `auto_fill`**；
- runner 回填 form 卡需要「**本轮**声明了载荷」×「上一轮待答卡是 form」**同时**成立
  （`resolve_auto_respond` 的 form 分支）；
- 而 agent 的发卡时机**只要晚一轮**（本 run：R4 被产品侧兜底话术吃掉），载荷就
  **再也送不出去** —— 余下轮次里 4 轮是 `prefer_text`（显式无视卡片）、其余轮声明里没有载荷。

⇒ 本用例的判决**不是**"agent 会不会下单"，而是"agent 的发卡时机**恰好**落在第 4/5 轮"。
⇒ 于是同一个 agent 行为在不同 run 里红/绿翻转（#3789 的"红色形态未钉住"）。

## 不变式（本文件锁死的那一条）

> 若用例声明了表单载荷，则**最后一个"能作答 form 卡"的轮次**必须能交付载荷。

等价说法：**载荷窗口不得在最后一个可作答轮次之前用尽**。判据取"最后一个"而不是"每一个"
是为了**零误报**：早先那些"答别的卡"的轮次（如 OR-014 的 R2/R3 答规格/加工项卡）没有载荷
是合法的 —— 只要**尾部**仍有窗口，agent 晚发卡也能补上。而"只有单轮、且后面还有可作答轮次"
正是 OR-014 的必死形态。

## 红证（本文件自带，不依赖真实 LLM）

| 断言 | 红证 |
|---|---|
| 载荷窗口覆盖最后一个可作答轮次 | 把 OR-014 的 case 级 `auto_fill` 去掉（载荷退回只在 R4/R5 声明）⇒ 红（`test_or014_window_regression_is_red` 正在跑这个变体） |
| 守卫非空转 | `test_guard_flags_single_round_window`：构造"载荷只在 R1、R3 还能作答"的用例 ⇒ 必须报违规 |

## 与其它守卫的分工

- `tests/test_acceptance_case_checks.py::TestAssertionVocabularyIsMappedByLoader`：保证
  用例级 `auto_fill` 经 **CI 的 YAML 装载路径**活下来（漏映射 ⇒ 本守卫永远绿）。
- 本文件：保证**载荷位置**不再是红/绿的决定因素。
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
CASES_DIR = REPO_ROOT / ".github" / "cases"


def _load_runner():
    spec = importlib.util.spec_from_file_location("migao_eval_runner_payload_window", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = _load_runner()

import sys  # noqa: E402

if str(REPO_ROOT / ".github") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / ".github"))
from render_cases import load_case_dicts  # noqa: E402


# ⚠️ 两个纯函数（`declared_payload_keys` / `payload_window_audit`）的**单一实现**在
# `tests/agent_eval/local_runner.py`（#3804）—— 本文件与 L0
# `tests/unit_ci_workflows/test_eval_auto_respond_l0.py` 共用，避免两处各写一套口径。
declared_payload_keys = lr.declared_payload_keys
payload_window_audit = lr.payload_window_audit


def _cases():
    return load_case_dicts(str(CASES_DIR))


def _must_case(case_id):
    """取唯一命中的用例；**缺失/重名即失败**（守卫对象不存在时下面的断言会静默空跑）。

    刻意不用「非空存在性断言」：那是 QA Gate 的弱断言形态
    （`growth_gate.py --check-weak`，命中即 block PR）。这里校验的是**命中条数**，
    比"非空"更强，也说明清楚"为什么必须是 1 条"。
    """
    found = [c for c in _cases() if c.get("id") == case_id]
    assert len(found) == 1, (
        f"用例库里 {case_id} 命中 {len(found)} 条（期望恰好 1 条）—— 守卫对象缺失或重名，"
        f"本文件的断言会静默空跑")
    return found[0]


def test_guard_is_not_vacuous():
    """守卫的**前提**：用例库能被读到（否则下面的逐条断言静默空跑 = 假绿）。"""
    cases = _cases()
    assert len(cases) >= 100, f"只读到 {len(cases)} 条用例 —— 用例库路径/解析失效"
    assert any(declared_payload_keys(c) for c in cases), "没有任何用例声明表单载荷 —— 守卫空转"


def test_every_declared_payload_covers_last_answerable_round():
    """**核心不变式**：声明了载荷的用例，载荷必须能覆盖最后一个可作答轮次。"""
    bad = [a["violation"] for a in (payload_window_audit(c) for c in _cases()) if a["violation"]]
    assert not bad, ("以下用例的表单载荷绑死在固定轮次上（agent 发卡时机一漂移就整场不可完成）：\n  "
                     + "\n  ".join(bad))


def test_guard_flags_single_round_window():
    """**红证（正向）**：载荷只在 R1、而 R3 还能作答 ⇒ 必须报违规（守卫不是恒真断言）。"""
    case = {
        "id": "TMP-WINDOW",
        "user_inputs": [
            {"auto_respond": {"fallback": "确认", "form_values": {"customer_name": "张三"}}},
            "谢谢",
            {"auto_respond": {"fallback": "确认"}},
        ],
    }
    a = payload_window_audit(case)
    assert a["applies"] and a["last_answer_round"] == 3
    assert a["deliverable_rounds"] == [1], a
    assert a["violation"], "单轮窗口 + 尾部仍有可作答轮 ⇒ 必须判违规"


def test_guard_flags_or014_regression_variant():
    """**红证（本单本体）**：把 OR-014 的 case 级 `auto_fill` 去掉 ⇒ 必须回到违规态。

    这正是"退化即红"：若哪天有人把用例级载荷改回"只声明在第 4、5 轮"，本用例先红。
    """
    or014 = _must_case("OR-014")
    assert payload_window_audit(or014)["violation"] == "", "OR-014 现状应当已经不违规"

    regressed = {k: v for k, v in or014.items() if k != "auto_fill"}
    a = payload_window_audit(regressed)
    assert a["violation"], (
        "退回『载荷只声明在第 4、5 轮』后守卫仍判通过 —— 这条不变式是恒真断言（假绿）")
    # 2026-09-15（OR-014 交互轮修复，issue #3892）：四个「123456」轮去掉 prefer_text 后
    # 变为可作答轮（答卡/回填载荷），故最后一个可作答轮从 R8 延到 R11 —— 违规判据
    # （R11 拿不到载荷）不变，仅该读数值随可作答轮延伸更新（旧值 8 是 prefer_text 时代的
    # 读数值）。与 tests/unit_ci_workflows/test_eval_auto_respond_l0.py 的 L0 孪生断言同源。
    assert a["last_answer_round"] == 11, a


def test_or023_repeat_until_window_is_wide():
    """反向守卫：**不该**红的形态不许红（`repeat_until` 展开出的宽窗口，OR-023）。"""
    or023 = _must_case("OR-023")
    a = payload_window_audit(or023)
    assert a["applies"], "OR-023 声明了载荷 —— 守卫必须适用（否则它在静默空跑）"
    assert not a["violation"], f"OR-023 的 repeat_until 窗口被误判为违规：{a}"
    assert len(a["deliverable_rounds"]) >= 8, a


@pytest.mark.parametrize("case_id", ["PR-019"])
def test_auto_fill_only_cases_are_covered(case_id):
    """`auto_fill` 轮并集也构成 case 级窗口（PR-019 是这一形态的正例）。

    变更沿革：原参数是 `PR-016`（「建品加工项价格落库盯防」）—— 该用例已随
    issue #4371「商品↔加工项解耦」**整条删除**（其断言对象 `processingItemConfigs.finalPrice`
    已不存在），故换成本形态的另一真实正例 PR-019（建品规格落库，同样在用例级声明
    `auto_fill`：商品名/价格/颜色/售卖方式/门幅/货号）。判据（`applies` ∧ 无 `violation`）未变。
    """
    case = _must_case(case_id)
    a = payload_window_audit(case)
    assert a["applies"] and not a["violation"], a


# ── 逐轮重放（issue #3804 验收标准 1：零 LLM 红证固化为单测）────────────────────
# 针 = **真实** `resolve_auto_respond()`；输入 = 判定跑 34873715194（SHA 30527b73）
# OR-014 第 2 次尝试的逐轮"上一轮 agent 发卡"序列（取自作业日志 `Run mibao normal`）：
#   R1 规格 choice 卡 → R2 加工项多选卡 → R3 纯文本（无卡）→ R4/R5 无卡（产品侧兜底话术
#   吃掉）→ R6 form 卡 + prefer_text（验证码轮）→ R7/R8 form 卡 → R9-R11 prefer_text。
# 预期：**修前**（载荷只在 R4/R5）`__FORM__` 命中 **0**；**修后**（case 级载荷）命中 **≥1**
# （R7/R8 本来就在等 form 卡、也没有 prefer_text，本该回填）。
_SPEC_CARD = {"type": "choice", "title": "请选择遮光窗帘的规格（颜色）",
              "options": [{"label": "米白", "value": "米白"}]}
_PROC_CARD = {"type": "choice", "title": "请选择遮光窗帘的加工项（可多选）", "multiSelect": True,
              "options": [{"label": "韩式波浪折边", "value": "pi_hem"}]}
_FORM_CARD = {"type": "form", "title": "请填写客户信息（下单必填）",
              "formFields": [{"key": "customer_name"}, {"key": "customer_phone"},
                             {"key": "customer_address"}]}
_RUN3_TURNS = [
    (1, _SPEC_CARD, None),
    (2, _PROC_CARD, {"fallback": "选有打孔的那件"}),
    (3, None, {"fallback": "不需要其他加工项"}),
    (4, None, {"fallback": "确认下单"}),
    (5, None, {"fallback": "确认"}),
    (6, _FORM_CARD, {"fallback": "123456", "prefer_text": True}),
    (7, _FORM_CARD, {"fallback": "确认"}),
    (8, _FORM_CARD, {"fallback": "确认"}),
    (9, None, {"fallback": "123456", "prefer_text": True}),
    (10, None, {"fallback": "123456", "prefer_text": True}),
    (11, None, {"fallback": "123456", "prefer_text": True}),
]


def _replay_run3(case_level: dict, declared_rounds: dict | None = None) -> dict:
    """按 run3 的逐轮序列重放；`case_level` = 用例级载荷，`declared_rounds` = 轮级载荷。"""
    declared_rounds = declared_rounds or {}
    results, sent = [], {}
    for n, emitted, spec in _RUN3_TURNS:
        if spec is not None:
            fv = dict(case_level)
            fv.update(declared_rounds.get(n) or {})
            sent[n] = lr.resolve_auto_respond(
                results, fallback=str(spec.get("fallback") or "确认"),
                form_values=fv, prefer_text=bool(spec.get("prefer_text")))
        results.append({"user_message": sent.get(n, ""),
                        "interactive": [emitted] if emitted else []})
    return sent


def test_or014_run3_replay_hits_form_payload():
    """OR-014 重放：case 级载荷让 `__FORM__` 从 **0** 变 **>0**（本单的核心红证）。"""
    or014 = _must_case("OR-014")
    case_level = dict(or014.get("auto_fill") or {})
    assert case_level, "OR-014 缺用例级载荷 —— 修复被回退（本断言即红证之一）"
    # 轮级载荷（修前唯一的通道）：只声明在第 4、5 轮
    round_level = {}
    for i, m in enumerate(or014.get("user_inputs") or [], 1):
        if isinstance(m, dict) and ((m.get("auto_respond") or {}).get("form_values")):
            round_level[i] = m["auto_respond"]["form_values"]

    before = _replay_run3({}, round_level)              # 修前形态
    after = _replay_run3(case_level, round_level)       # 修后形态
    hits_before = sum("__FORM__" in str(v) for v in before.values())
    hits_after = sum("__FORM__" in str(v) for v in after.values())
    assert hits_before == 0, f"修前形态竟能发出载荷（{before}）—— 重放没复现缺陷的前提"
    assert hits_after > 0, f"修后仍未发出载荷（{after}）—— 用例级载荷没生效"
    assert hits_after == 2 and "__FORM__" in str(after.get(7)) and "__FORM__" in str(after.get(8)), (
        f"应当在 R7/R8 命中（那两轮就在等 form 卡且非 prefer_text），实际 {after}")


def test_resolve_auto_respond_normal_path_unchanged():
    """反向守卫（issue #3803）：字段**能**精确匹配时行为逐字不变（不得把正常路径改红）。"""
    results = [{"user_message": "x", "interactive": [
        {"type": "form", "formFields": [{"key": "customer_name"}, {"key": "customer_phone"}]}]}]
    got = lr.resolve_auto_respond(results, fallback="确认",
                                  form_values={"customer_name": "张三", "customer_phone": "123"})
    assert got == '__FORM__|{"customer_name": "张三", "customer_phone": "123"}', got
