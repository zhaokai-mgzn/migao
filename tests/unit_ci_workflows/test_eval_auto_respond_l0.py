# case_ids: OR-014, OR-022, OR-024, CR-003, PR-019, OR-023, PR-016
"""**L0** 守卫：`resolve_auto_respond` 的载荷窗口 + 形状不兼容的独立签名。

## 为什么单列一个 L0 文件（issue #3804 验收标准 2）

原单的原话是「**现有 72 项 L0 无一覆盖 `resolve_auto_respond`**」——
`grep -rn resolve_auto_respond tests/unit_ci_workflows/` 在抢救包 e2a094a1 里仍然 **0 命中**
（覆盖只落在 `backend/ai-agent-service/tests/` 的 L2 层）。L0（`tests/unit_ci_workflows/`，
`python3.11 -m pytest`，纯静态零 LLM、秒级）是唯一每个 PR 都必然跑的那一层，
把这个函数的**载荷窗口语义**锁在 L0，才能在"改用例资产的那一次 PR"上立刻变红
（L2 那层跑的是另一套 fixture，看不到 `.github/cases/` 的真实形状）。

## 本文件锁四件事

| # | 断言 | 红证（改回修前形态即红） |
|---|---|---|
| ① | `resolve_auto_respond` 在 L0 里被真正调用（form 分支：精确匹配 ⇒ `__FORM__\\|{json}`） | —— 反向守卫：正常路径**逐字不变** |
| ② | **CI 的 YAML 装载路径**把 `auto_fill` 装进 `EvalCase`（`load_cases_from_yaml`） | 去掉 `auto_fill=c.get("auto_fill") or {}` ⇒ OR-014 的 `case.auto_fill` 为空 ⇒ 红 |
| ③ | **载荷窗口不变式**：声明了载荷的用例，最后一个可作答轮次必须能交付载荷 | 删掉 OR-014 的用例级 `auto_fill`（退回只在 R4/R5 声明）⇒ 红（见 `test_or014_regression_variant_is_red`） |
| ④ | 载荷零匹配 ⇒ **不许静默降级**；且折叠出的原子与"agent 没做"**分属不同身份**（`#3803`） | 原子规则缺失/被删 ⇒ 折成 `no_success(order_create)` 形态 ⇒ 红 |
⚠️ 本目录在 CI 只 `pip install pytest pyyaml`（`.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 用下方最小替身（与
`test_eval_summary_attribution.py` / `test_eval_runner_same_round_scope.py` 同形）。
被锁的是**纯函数**（`resolve_auto_respond` / `payload_window_audit` / `load_cases_from_yaml`
/ `_case_issue_atom`），不该因缺一个 HTTP 客户端而不可测。
"""
import dataclasses
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"
CASES_DIR = REPO_ROOT / ".github" / "cases"

sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；替身一旦被调用即抛错）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:                  # 只满足模块级 `import httpx` 与类型引用
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


lr = _load_runner()


def _cases():
    return lr.load_cases_from_yaml(str(CASES_DIR))


def _case(case_id):
    """取唯一命中的用例；缺失/重名即失败（守卫对象不存在时下面的断言会静默空跑）。

    校验**命中条数**而不是"非空存在性"（后者是 QA Gate 的弱断言形态，命中即 block PR）。
    """
    found = [c for c in _cases() if str(getattr(c, "id", "")) == case_id]
    assert len(found) == 1, (
        f"用例库里 {case_id} 命中 {len(found)} 条（期望恰好 1 条）—— 守卫对象缺失或重名，"
        f"本文件的断言会静默空跑（用例库路径/解析失效）")
    return found[0]


def _as_dict(case) -> dict:
    """`EvalCase`（dataclass）→ `payload_window_audit` 吃的 dict 形态。"""
    return dataclasses.asdict(case)


def _last_card(card):
    """`resolve_auto_respond` 读的是**最后一轮**的 `interactive`。"""
    return [{"user_message": "x", "interactive": [card]}]


# ── ① L0 里真的调用了 resolve_auto_respond ──────────────────────────────────

def test_resolve_auto_respond_form_branch_is_exercised_in_l0():
    """form 分支正向：卡字段 == 载荷字段 ⇒ 精确同名回填（**正常路径逐字不变**）。"""
    card = {"type": "form", "formFields": [{"key": "customer_name"}, {"key": "customer_phone"}]}
    got = lr.resolve_auto_respond(_last_card(card), fallback="确认",
                                  form_values={"customer_name": "张三",
                                               "customer_phone": "13800138000"})
    assert got == '__FORM__|{"customer_name": "张三", "customer_phone": "13800138000"}', got


def test_resolve_auto_respond_falls_back_when_no_card():
    """无待答卡 ⇒ fallback（这条与上面合起来证明 L0 真的在行使这个函数）。"""
    assert lr.resolve_auto_respond(_last_card({"type": "text", "text": "好的"}),
                                   fallback="数量 3 米", form_values={}) == "数量 3 米"


# ── ② CI 的 YAML 装载路径必须把 auto_fill 装进 EvalCase（#3804）──────────────
# 这一格是"声称修了其实没修"的重灾区（`debug_user`/`output_verify`/`namespaces` 四次同款）：
# CI 跑的是 `--cases .github/cases` 的 **YAML 装载路径**，不是生成物 `eval_cases.py`
# ⇒ 漏映射 = 用例声明了没人消费 = 载荷窗口仍绑死在某些轮次。

def test_ci_yaml_loader_carries_case_level_auto_fill():
    case = _case("OR-014")
    af = getattr(case, "auto_fill", None)
    assert af, (f"OR-014 经 `load_cases_from_yaml` 装载后 `auto_fill` 为空（{af!r}）—— "
                f"CI 的装载路径没映射该字段 ⇒ 用例级载荷形同不存在（#3804 复发）")
    assert {"customer_name", "customer_phone", "customer_address"} <= set(af), af


def test_generated_eval_cases_also_carry_it():
    """生成物 `eval_cases.py` 与 YAML 单一源同口径（防止只改了一边）。"""
    src = (REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py").read_text(encoding="utf-8")
    assert re.search(r"auto_fill=\{[^}]*customer_name", src), (
        "生成物里没有 OR-014/OR-022/… 的用例级 auto_fill —— 生成物与 cases/*.yml 脱同步")


# ── ③ 载荷窗口不变式（全库扫描）────────────────────────────────────────────

def test_case_library_is_non_empty_and_has_payloads():
    """前提：守卫不是空转（用例库读得到、且确实有用例声明了载荷）。"""
    cases = _cases()
    assert len(cases) >= 100, f"只读到 {len(cases)} 条用例 —— 用例库路径/解析失效（守卫会静默空跑）"
    with_payload = [c.id for c in cases if lr.declared_payload_keys(_as_dict(c))]
    assert len(with_payload) >= 5, (
        f"只有 {len(with_payload)} 条用例声明了表单载荷 —— 窗口不变式接近空转：{with_payload}")


def test_every_declared_payload_covers_the_last_answerable_round():
    """**核心不变式**：载荷窗口不得在最后一个可作答轮次之前用尽（issue #3804）。"""
    bad = []
    for c in _cases():
        a = lr.payload_window_audit(_as_dict(c))
        if a["violation"]:
            bad.append(a["violation"])
    assert bad == [], ("以下用例的表单载荷绑死在固定轮次上（agent 发卡时机一漂移就整场不可完成，"
                       "且失败串会写成『agent 没做』= 归因错人）：\n  " + "\n  ".join(bad))


def test_guard_flags_single_round_window():
    """**红证（正向）**：载荷只在 R1、而 R3 还能作答 ⇒ 必须报违规（守卫不是恒真断言）。"""
    a = lr.payload_window_audit({
        "id": "TMP-WINDOW",
        "user_inputs": [
            {"auto_respond": {"fallback": "确认", "form_values": {"customer_name": "张三"}}},
            "谢谢",
            {"auto_respond": {"fallback": "确认"}},
        ],
    })
    assert a["applies"] and a["last_answer_round"] == 3, a
    assert a["deliverable_rounds"] == [1], a
    assert a["violation"], "单轮窗口 + 尾部仍有可作答轮 ⇒ 必须判违规"


def test_or014_regression_variant_is_red():
    """**红证（本单本体）**：把 OR-014 的用例级 `auto_fill` 去掉 ⇒ 必须回到违规态。

    这正是"退化即红"：谁把用例级载荷改回"只声明在第 4、5 轮"，本用例先红。
    """
    raw = _as_dict(_case("OR-014"))
    assert lr.payload_window_audit(raw)["violation"] == "", "OR-014 现状应当已经不违规"
    regressed = {k: v for k, v in raw.items() if k != "auto_fill"}
    a = lr.payload_window_audit(regressed)
    assert a["violation"], ("退回『载荷只声明在第 4、5 轮』后守卫仍判通过 —— "
                            "这条不变式是恒真断言（假绿）")
    assert a["last_answer_round"] == 8, a


def test_or023_repeat_until_window_is_not_flagged():
    """反向守卫：**不该**红的形态不许红（`repeat_until` 展开出的宽窗口，OR-023）。"""
    a = lr.payload_window_audit(_as_dict(_case("OR-023")))
    assert a["applies"], "OR-023 声明了载荷 —— 守卫必须适用（否则它在静默空跑）"
    assert not a["violation"], f"OR-023 的 repeat_until 窗口被误判为违规：{a}"
    assert len(a["deliverable_rounds"]) >= 8, a


# ── ④ 形状不兼容：零匹配不许静默，且归因必须可辨（#3803）──────────────────────

def test_zero_match_is_not_silently_downgraded_to_fallback():
    """载荷与卡字段**一个都对不上** ⇒ 独立签名，不再是静默 fallback（#3803）。"""
    card = {"type": "form", "formFields": [{"key": "unknown_key"}]}
    out = lr.resolve_auto_respond(_last_card(card), fallback="确认下单",
                                  form_values={"customer_name": "张三"})
    inc = lr.parse_harness_incompatible(out)
    assert isinstance(inc, dict), (
        f"载荷零匹配却静默降级为 fallback 文本 {out!r} —— "
        f"这类红会被写成『agent 没做』（归因错人，issue #3803）")
    assert inc["kind"] == "form_fields_mismatch", inc
    assert inc["card_fields"] == ["unknown_key"] and inc["case_fields"] == ["customer_name"], inc


def test_harness_incompatible_and_agent_failure_fold_to_different_atoms():
    """**归因可辨的判据**：折叠后的失败原子必须与"agent 没做"分属不同身份。

    红证：删掉 `_CASE_ATOM_RULES` 里的 `^harness_incompatible\\((\\w+)\\)` 规则 ⇒
    这条原文会落到通用原子（与 `no_success(order_create)` 同族）⇒
    "harness 形状对不上"与"agent 不会下单"在两次尝试的**同因判定**上重新混为一谈。
    """
    src = RUNNER_PATH.read_text(encoding="utf-8")
    assert 'f"harness_incompatible({_inc.get(\'kind\')}): 用例载荷字段 "' in src, (
        "runner 的 case 级原文格式变了 —— 本守卫用的字面量已不代表生产（会退化成空断言）")
    issue = ("harness_incompatible(form_fields_mismatch): 用例载荷字段 ['customer_name'] "
             "与待答 form 卡字段 ['name'] **零匹配** —— 本次红是 harness/用例形状不兼容")
    assert lr._case_issue_atom(issue) == "harness_incompatible(form_fields_mismatch)", (
        f"形状不兼容没被折成独立原子：{lr._case_issue_atom(issue)!r}")
    agent_fail = lr._case_issue_atom("must_succeed: order_create 从未被调用 → 没有发生任何写操作")
    assert agent_fail == "no_success(order_create)", agent_fail
    assert agent_fail != lr._case_issue_atom(issue), "两者折叠成同一原子 ⇒ 归因仍会错人"


def test_shape_mismatch_atom_is_stable_across_two_attempts():
    """同因判定：两次尝试的字段列表不同（每次卡形状都可能不同）也必须折成**同一**原子。

    否则 `_classify_attempts` 会把它读成"两次成因不同"（`unstable`），
    与真正的行为回归一起被误分类。
    """
    a = ("harness_incompatible(form_fields_mismatch): 用例载荷字段 ['customer_name'] "
         "与待答 form 卡字段 ['name'] **零匹配**")
    b = ("harness_incompatible(form_fields_mismatch): 用例载荷字段 "
         "['customer_name', 'customer_phone'] 与待答 form 卡字段 ['phone'] **零匹配**")
    assert lr._case_issue_atom(a) == lr._case_issue_atom(b) == "harness_incompatible(form_fields_mismatch)"


def test_completion_verdict_separates_harness_failures_from_agent_failures():
    """判定层：形状不兼容**仍然阻塞**（fail-closed），但不混进"agent 确定性回归"清单。"""
    v = lr.completion_verdict([{"case_id": "OR-014", "score": 0.0,
                                "classification": "reproducible",
                                "harness_incompatible": [{"kind": "form_fields_mismatch"}]}], ())
    assert v["ok"] is False, "形状不兼容被放行了 —— 那是放宽断言（禁止）"
    assert v["harness_incompatible_failures"] == ["OR-014"], v
    assert v["deterministic_failures"] == [], (
        "形状不兼容仍被计进『agent/产品的确定性回归』—— 归因继续指错人")
