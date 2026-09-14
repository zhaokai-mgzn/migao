# case_ids: OR-014, OR-022, OR-024, CR-003, PR-019, OR-023, PR-016, OR-026
"""**L0** 守卫：`resolve_auto_respond` 的载荷窗口 + `resolve_repeat_turn` 的载荷饿死 + 形状不兼容签名。

## 为什么单列一个 L0 文件（issue #3804 验收标准 2）

原单的原话是「**现有 72 项 L0 无一覆盖 `resolve_auto_respond`**」——
`grep -rn resolve_auto_respond tests/unit_ci_workflows/` 在抢救包 e2a094a1 里仍然 **0 命中**
（覆盖只落在 `backend/ai-agent-service/tests/` 的 L2 层）。L0（`tests/unit_ci_workflows/`，
`python3.11 -m pytest`，纯静态零 LLM、秒级）是唯一每个 PR 都必然跑的那一层，
把这个函数的**载荷窗口语义**锁在 L0，才能在"改用例资产的那一次 PR"上立刻变红
（L2 那层跑的是另一套 fixture，看不到 `.github/cases/` 的真实形状）。

## 本文件锁六件事

| # | 断言 | 红证（改回修前形态即红） |
|---|---|---|
| ① | `resolve_auto_respond` 在 L0 里被真正调用（form 分支：精确匹配 ⇒ `__FORM__\\|{json}`） | —— 反向守卫：正常路径**逐字不变** |
| ② | **CI 的 YAML 装载路径**把 `auto_fill` 装进 `EvalCase`（`load_cases_from_yaml`） | 去掉 `auto_fill=c.get("auto_fill") or {}` ⇒ OR-014 的 `case.auto_fill` 为空 ⇒ 红 |
| ③ | **载荷窗口不变式**：声明了载荷的用例，最后一个可作答轮次必须能交付载荷 | 删掉 OR-014 的用例级 `auto_fill`（退回只在 R4/R5 声明）⇒ 红（见 `test_or014_regression_variant_is_red`） |
| ④ | 载荷零匹配 ⇒ **不许静默降级**；且折叠出的原子与"agent 没做"**分属不同身份**（`#3803`） | 原子规则缺失/被删 ⇒ 折成 `no_success(order_create)` 形态 ⇒ 红 |
| ⑤ | `repeat_until` 轮的**载荷饿死**：文字提到"验证码"不得挤掉**可回填的 form 卡**（`#3829` / OR-026） | 恢复旧优先级 ⇒ `test_soft_code_mention_no_longer_starves_fillable_form_card` 得到 `'123456'` ⇒ 红 |
| ⑥ | **S1 全族**（`repeat_until` 同时声明 `code` + 载荷）的离线重放台账：窗口内必须交付载荷 | 同上 ⇒ 全族 `__FORM__` 命中 0（`0/7,0/8×5`）⇒ 红 |
⚠️ 本目录在 CI 只 `pip install pytest pyyaml`（`.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 用下方最小替身（与
`test_eval_summary_attribution.py` / `test_eval_runner_same_round_scope.py` 同形）。
被锁的是**纯函数**（`resolve_auto_respond` / `resolve_repeat_turn` / `payload_window_audit`
/ `load_cases_from_yaml` / `_case_issue_atom`），不该因缺一个 HTTP 客户端而不可测。
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


# ── ⑤ `repeat_until` 轮的**载荷饿死**（issue #3829 / OR-026 C 端腿判红）──────────
# 病灶（判定跑 34908262839 @2b8dfbc2，same-fingerprint 首跑 34865780382）：`resolve_repeat_turn`
# 把「agent 文字里出现『验证码』」当成"在索码"，且**无条件优先于答卡**。当 agent 卡在
# "手机号不对"这一步、每轮都解释「需要 11 位手机号**用来接收下单验证码**」时，harness 每轮
# 都回 `123456`，而它刚发的那张 form 卡（载荷完全对得上）**永远没人答** ⇒ `__FORM__` 全场
# 命中 **0** ⇒ `order_create`/`validate_input` 从未发生 ⇒ 用例必红，失败串还写成
# 「agent 不会下单」。零 LLM 重放（真实函数）：改前 8 轮全 `123456`（命中 0/8）→ 改后 R4 交付。

_SOFT_MENTION = "亲，需要 11 位手机号哦（用来接收下单验证码）～ 我把收货信息表发给您"
_PAYLOAD = {"customer_name": "张三", "customer_phone": "13800138000",
            "customer_address": "浙江省杭州市西湖区文三路1号1幢101室"}


def _round(*, text="", cards=(), calls=(), statuses=None, user="123456"):
    r = {"round": 1, "user_message": user, "final_text": text,
         "interactive": list(cards),
         "tool_calls": [{"name": c} for c in calls]}
    if statuses is not None:
        r["tool_results"] = [{"tool": c, "result": {"success": s}}
                             for c, s in zip(calls, statuses)]
    return r


def _form_card(keys=("customer_name", "customer_phone", "customer_address")):
    return [{"type": "form", "title": "请补充收货信息（手机号需 11 位）",
             "formFields": [{"key": k} for k in keys]}]


def test_soft_code_mention_no_longer_starves_fillable_form_card():
    """**本单本体**：文字提到"验证码" + 待答 form 卡**可回填** ⇒ 必须交载荷（不是再发码）。

    红证：把 `resolve_repeat_turn` 的 ② 段（`_code_gate_blocked` 之后的 form 卡优先）删掉 ⇒
    本断言退回 `'123456'` ⇒ 红。前提断言（`needs_verification_code` 为真）保证本用例
    不是"因为压根没有索码信号"而侥幸通过（那是恒真断言）。
    """
    results = [_round(text=_SOFT_MENTION, cards=_form_card())]
    assert lr.needs_verification_code(results) is True, (
        "前提不成立：这条轨迹根本没有索码信号 —— 本用例会退化成恒真断言")
    got = lr.resolve_repeat_turn(results, {"code": "123456", "fallback": "确认下单",
                                           "form_values": _PAYLOAD}, {})
    assert got.startswith("__FORM__|"), (
        f"文字提及『验证码』把**可回填的 form 卡**挤掉了（载荷饿死，OR-026 根因）：{got!r}")
    assert "13800138000" in got, f"交出去的载荷里没有改正后的手机号：{got!r}"


def test_soft_code_mention_still_truthy():
    """反向守卫：软信号**仍然算真**（不许把 `needs_verification_code` 收窄成只看工具失败）。"""
    assert lr.needs_verification_code([_round(text=_SOFT_MENTION)]) is True, (
        "文字索码不再被识别 ⇒ CH-010/OR-021 那类验证码轮会送不出码（把一类红换成另一类）")


def test_hard_missing_code_gate_still_wins_over_fillable_form_card():
    """反向守卫（#3430 的原始死锁）：写调用**因缺码被挡**时，硬信号仍最优先 ⇒ 供码。"""
    r = _round(text="好的亲～", cards=_form_card(), calls=["order_create"], statuses=[False])
    r["tool_results"][0]["result"] = {"success": False, "error": "缺少短信验证码"}
    got = lr.resolve_repeat_turn([r], {"code": "123456", "fallback": "确认下单",
                                       "form_values": _PAYLOAD}, {})
    assert got == "123456", f"缺码硬信号被 form 卡挤掉（run 34768306581 的死锁会复发）：{got!r}"


def test_confirm_and_choice_cards_still_yield_the_code_when_asked():
    """反向守卫（OR-023 同族正向半）：索码 + 待答 confirm/choice 卡 ⇒ 仍供码（卡型无关）。"""
    confirm = [{"type": "confirm", "title": "请确认订单信息", "confirmValue": "确认：商品=遮光窗帘"}]
    choice = [{"type": "choice", "title": "要哪些加工项",
               "options": [{"label": "纳米圈打孔", "value": "pi1"}]}]
    for cards in (confirm, choice):
        got = lr.resolve_repeat_turn([_round(text=_SOFT_MENTION, cards=cards)],
                                     {"code": "123456", "fallback": "确认下单",
                                      "form_values": _PAYLOAD}, {})
        assert got == "123456", f"索码时非 form 卡的行为被改了（{cards[0]['type']}）：{got!r}"


def test_code_still_sent_when_form_card_keys_do_not_match():
    """反向守卫（残留缺口，**如实登记不粉饰**）：卡字段与载荷零匹配 ⇒ 仍供码。

    此时载荷**确实填不进去**（issue #3803 的同义组也没覆盖的字段名），发码是旧行为；
    这条锁住它不被"顺手改成 signature" —— 那会把本来能推进的验证码轮判成红（绿→红）。
    可辨性由 `pending_card_summary` 带出字段名承担（见下方用例）。
    """
    results = [_round(text=_SOFT_MENTION, cards=_form_card(("receiver_phone", "ship_to")))]
    got = lr.resolve_repeat_turn(results, {"code": "123456", "fallback": "确认下单",
                                           "form_values": _PAYLOAD}, {})
    assert got == "123456", f"零匹配时不该乱改行为（见 docstring）：{got!r}"


def test_delivered_payload_is_not_resent_forever():
    """防"镜像死锁"：同一份载荷已发过 ⇒ 不再重复发（退回供码），避免卡在原地。

    与 `resolve_auto_respond` 对 confirm/choice 的"不重复点同一张卡"同源纪律。
    """
    payload = lr._auto_fill_form([_round(cards=_form_card())], _PAYLOAD)
    assert payload and payload.startswith("__FORM__|"), payload
    results = [_round(text=_SOFT_MENTION, cards=_form_card(), user="123456"),
               _round(text=_SOFT_MENTION, cards=_form_card(), user=payload)]
    got = lr.resolve_repeat_turn(results, {"code": "123456", "fallback": "确认下单",
                                           "form_values": _PAYLOAD}, {})
    assert got == "123456", f"同一份载荷被反复重发（agent 没接住时会原地打转）：{got!r}"


def test_pending_card_summary_names_form_fields():
    """可辨性（#3829）：待答 form 卡的**字段名**必须出现在失败诊断里。

    判红时"是不是字段名对不上"此前取不到证据（trace 里只有 `formFields=3` 的**个数**）。
    反向守卫：**不带 formFields 的 form 卡**输出必须逐字保持 `form` ——
    L2 `tests/test_acceptance_case_checks.py::test_summary_handles_multiple_cards_and_missing_title`
    锁了 `"form、confirm:确认下单"` 这个字面量（本改动不得让它变红）。
    """
    got = lr.pending_card_summary([_round(cards=_form_card(("name", "phone")))])
    assert "name" in got and "phone" in got, got
    bare = lr.pending_card_summary([{"user_message": "x", "interactive": [
        {"type": "form", "title": ""}, {"component": "confirm", "title": "确认下单"}]}])
    assert bare == "form、confirm:确认下单", bare


def test_or026_offline_replay_delivers_corrected_phone():
    """**真实用例资产的端到端重放**（零 LLM）：OR-026 的 repeat_until 窗口内必须交付改正后的手机号。

    轨迹形态取自判定跑 34908262839 的首跑 trace（R3 起 agent 每轮复读含『验证码』的解释
    并下发 form 卡；`you=` 一直是 `123456`）。判据 = 在 max=8 的窗口内至少交付一次载荷，
    且载荷里带 13800138000（否则「改正后继续走完闭环」的数据检查永远不可能满足）。
    """
    case = _case("OR-026")
    turns = lr.expand_repeat_turns(list(case.user_inputs or []))
    reps = [t for t in turns if isinstance(t, dict) and t.get("__repeat__")]
    assert len(reps) == 8, (f"OR-026 的 repeat_until 展开出 {len(reps)} 轮（期望 8 = 声明的 max）"
                            f"—— 用例形状变了，本重放的窗口判据需要重新校准")
    opts = reps[0]["opts"]
    assert str(opts.get("code") or ""), f"OR-026 的协作轮没声明验证码：{opts}"
    assert opts.get("form_values"), f"OR-026 的协作轮没声明表单载荷：{opts}"
    base = dict(getattr(case, "auto_fill", None) or {})

    results = [_round(text=_SOFT_MENTION, cards=_form_card(), user="123456")]
    delivered = []
    for _ in range(8):
        text = lr.resolve_repeat_turn(results, opts, base)
        delivered.append(text)
        results.append(_round(text=_SOFT_MENTION, cards=_form_card(), user=text))
    hits = [t for t in delivered if str(t).startswith("__FORM__|")]
    assert hits, ("OR-026 的整段协作窗口里 `__FORM__` 命中 0 —— 载荷永远送不出去，"
                  "`order_create`/`validate_input` 必然不发生（改前形态，issue #3829）")
    assert "13800138000" in hits[0] and "张三" in hits[0], hits[0]


# ── ⑥ 同类扫描（issue #3829 交付物 4）：S1 全族的**离线重放台账**────────────────
# 口径：「载荷的交付路径上有一张**由 agent 当轮决定形状的卡**，交付与否取决于 harness
# 侧的裁决（卡型 / 字段名 / 码优先级）」。S1 = `repeat_until` 同时声明 `code` 与表单载荷
# —— 与 OR-026 同族（同一处修复覆盖，故**不动任何用例 YAML**）。
# 判据：声明的 `max` 轮窗口内 `__FORM__` 至少交付 1 次。改前全族 0 次（`0/7,0/8×5`）。
S1_FAMILY = ("CH-010", "CH-025", "OR-021", "OR-023", "OR-026", "OR-028")

_SOFT_CODE_MENTION = "亲，需要 11 位手机号哦（用来接收下单验证码）～ 我把信息表发给您，填一下就好"


def _replay_repeat_window(case):
    """按用例**真实声明**（repeat opts + 卡字段形状 = 用例载荷字段名）重放协作窗口。

    返回 `(交付次数, 窗口轮数)`。卡形状取"用例作者预期的卡"（字段名 = 载荷字段名）——
    这正是 `payload_window_audit` 的同款口径，两处判据保持一致。
    """
    raw = _as_dict(case)
    rep = [m for m in raw["user_inputs"] if isinstance(m, dict) and m.get("repeat_until")]
    assert len(rep) == 1, f"{case.id}: repeat_until 轮命中 {len(rep)} 个"
    spec = rep[0]["repeat_until"]
    opts = {k: v for k, v in rep[0].items() if k != "repeat_until"}
    keys = sorted((opts.get("form_values") or {}).keys())
    assert keys, f"{case.id}: 协作轮没声明表单载荷（S1 判据不适用）"
    card = [{"type": "form", "title": "请补充收货信息",
             "formFields": [{"key": k} for k in keys]}]
    n = int(spec.get("max") or 3)
    results = [_round(text=_SOFT_CODE_MENTION, cards=card)]
    hits = 0
    for _ in range(n):
        text = lr.resolve_repeat_turn(results, opts, dict(raw.get("auto_fill") or {}))
        if str(text).startswith("__FORM__|"):
            hits += 1
        results.append(_round(text=_SOFT_CODE_MENTION, cards=card, user=text))
    return hits, n


def test_s1_family_replay_ledger():
    """**S1 全族**（同族脆弱清单）：6 条 `code + 载荷` 用例的载荷都必须在窗口内交付。

    红证：改回旧优先级 ⇒ 全族 `__FORM__` 命中 **0**（`0/7,0/8×5`）⇒ 本用例红。
    """
    ledger = {}
    for cid in S1_FAMILY:
        ledger[cid] = _replay_repeat_window(_case(cid))
    starved = {k: v for k, v in ledger.items() if v[0] == 0}
    assert starved == {}, (f"以下用例的整段协作窗口里 `__FORM__` 命中 0（载荷永不交付 ⇒ "
                           f"`order_create`/`validate_input` 必然不发生）：{starved}\n全族台账：{ledger}")
    assert len(ledger) == len(S1_FAMILY), ledger


