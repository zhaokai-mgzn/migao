# case_ids: OR-026, OR-021, OR-023, CH-010
"""**L0 守卫**：`_agent_asked_for_code` 必须是**形态判据**，不是「出现『验证码』就算索码」（issue #3757）。

## 病灶（run 34854258883 / SHA 9bb789ea，真实 LLM，逐轮 trace 直证）

改前判据 = 单词命中（`any(h in final_text for h in ("验证码", …))`）⇒ 「**验证码已收到 / 别再发 /
就差您点卡**」这类**收讫语义**的正确话术也被判成"agent 在索码" ⇒ `resolve_repeat_turn` 每轮走
「供码」分支、**一次都不点确认卡** ⇒ 写调用被确认门禁反复拦回（`confirmation_required_no_card`）
⇒ 同一张卡重复下发 ⇒ 轮数耗尽。OR-026 首跑 R3~R9 的 `you=` 全是 `123456`、`cards=confirm` 无人答。

## 修法依据（不是加词表，也不是换一套子串）

「出现『验证码』」降级为**必要条件**，另加**形态过滤**，两侧都判：

1. **索取形态**（面向码的请求动作：发我 / 提供 / 是多少 / 输入 / 再发一次…）⇒ 判索码；
2. **收讫 / 否定形态**（已收到 / 收好 / 记下 / 看到 / 收不到 / 别再发 / 不用再…）⇒ **不**判索码
   （判据只在这一侧翻转 ⇒ harness 走「有卡答卡」，点卡才是正确下一步）；
3. 两侧并存 ⇒ **索取优先**（「已收到，但过期的请再发一次」是真的还要码，不得判成回执）；
4. 两侧皆无（描述性提及，如「用来接收下单验证码」）⇒ **保持旧行为（判索码）**。

第 4 条是**刻意的取舍**（§23.5 坐标漂移）：把描述性提及也翻成"不判索码"，会让 #3829 的 L0 红证
`test_soft_code_mention_no_longer_starves_fillable_form_card`（删掉 form 卡优先段 ⇒ 必红）**退化**
—— 该夹具会改走「有卡答卡」分支并照样交载荷，「删段也绿」= 空断言。故默认值不动，只翻转收讫侧。

**未固化边界（如实登记，见本文件末条）**：既无索取形态、也无收讫形态的**转人工/旁观**话术
（实测 R10：`看您连着发了好几次验证码…我这就帮您转人工客服`）仍判索码 —— 该形态无任何可判的
收讫/否定标记；修复后流程在 R3~R9 就已点卡推进，不再走到那一轮。

## 本文件锁八件事（全部 L0、零 LLM、秒级）

| # | 断言 | 红证（改回修前形态即红） |
|---|---|---|
| ① | **真实 trace 逐字回执**（10 条 `ai=` 原文）判「不在索码」 | 改前子串判据 ⇒ 每条都 `True` ⇒ 红 |
| ② | 回执轮 + 待答 confirm 卡 ⇒ harness **点卡**（回 confirmValue），不是再发 `123456` | 改前 ⇒ 得到 `'123456'`（OR-026 死循环原形）⇒ 红 |
| ③ | 真索取形态（"请提供验证码" / "验证码是多少" / 描述性手机号索取）仍判索码 | 把判据改死（恒 False）⇒ 红 |
| ④ | 收讫 + 再索取并存 ⇒ 仍判索码（索取优先） | 只做"收讫即否"的粗判 ⇒ 红 |
| ⑤ | **判别力自证**：把改前的"子串充分条件"喂给校验器 ⇒ 必须报出误判（防校验器空转） | 校验器恒绿 ⇒ 红 |
| ⑥ | 当前判据在上述语料上**零违规**（语料两侧都有，非单极） | 判据漏判/误判任一条 ⇒ 红 |
| ⑦ | **孪生入口**（验收侧 `acceptance_runner.needs_code` 的文字腿）同一语义 | 只修评测侧 ⇒ 红（同一缺陷在姊妹 runner 里复活） |
| ⑧ | **词表单一归属**：`tests/agent_eval/*.py` 里定义"验证码词表"的文件只能有一个 | 谁再复制一张表 ⇒ 红并指名 |

⚠️ 本目录在 CI 只 `pip install pytest pyyaml`（`.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 用与 `test_eval_auto_respond_l0.py` 同形的最小替身。
被锁的是**纯函数**（`text_requests_code` / `_agent_asked_for_code` / `resolve_repeat_turn`）与
姊妹 runner 的文字腿，不该因缺一个 HTTP 客户端而不可测。
"""
import re
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_EVAL = REPO_ROOT / "tests" / "agent_eval"

sys.path.insert(0, str(AGENT_EVAL))


def _install_httpx_stub():
    """`local_runner` / `acceptance_runner` 都有模块级 `import httpx`（零依赖 L0 环境的替身）。"""
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:                  # 只满足模块级 `import httpx` 与类型引用
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)


_install_httpx_stub()

import local_runner as lr  # noqa: E402


# ── ① 真实 trace 逐字回执（run 34854258883 的 `ai=` 字段原文，未改写）──────────
# 逐字口径说明（不许当"近似"读）：`local_runner.format_round_trace` 打印的是
# `build_round_trace` 里的 `text[:60]` —— 即**60 字截断后的日志全貌**，本表逐条复制自
# `gh run view --job 104009612849 --log` 的 `ai=` 字段，未补全、未润色。
_TRACE_ACK = (
    # 首跑 trace R3~R9（`you=` 全是 123456、`cards=confirm` 无人答）
    "亲，验证码我记下啦～不过系统这边还差最后一步：麻烦您点一下上面卡片里的「确认下单」按钮哦🙏 （这是为了您的账户安全，确",
    "亲，验证码我已经收好啦 ✅ 就差您点一下上面卡片里的「确认下单」按钮（不是打字哦，点按钮就行），点完我立刻帮您把订单提交",
    "亲，验证码我收到啦 ✅ 现在只差您**点一下上面卡片里的「确认下单」按钮**这一步哦（点按钮就行，不用再打字发验证码啦）",
    "亲，验证码我收到啦 ✅ 估计是确认按钮没显示出来，我重新给您发一张卡片～ 麻烦点一下卡片里的「**确认下单**」按钮就",
    "亲，新的确认卡片已经发上去啦 👆 麻烦您**点卡片里的「确认下单」按钮**（点按钮就行，不用再发验证码啦），点完我立刻",
    "亲，别着急～验证码我已经收到啦 ✅ 我再帮您把确认卡片递上来一次，这次麻烦您**直接在卡片上点「确认下单」**就好（不用",
    "亲，看到您发的验证码啦 ✅ 不过「填验证码」和「点确认」是两步哦——**订单必须由您亲手点一下确认按钮才会提交**，我这",
    # 同 run 的**重试** trace R4（首次失败、换 session 重试才通过 —— 同一判据的第二次命中）
    "亲，验证码收到啦～ 最后一步请您在下面这张卡片上点一下「**确认下单**」就好，我收到后立刻帮您提交订单 ✅ （订单明",
    # R1（首跑）：解释"这个号码收不到短信验证码"，同样是**描述收讫状态**、不在索码
    "亲，收到啦～下单前有两件事跟您确认一下哦： 1️⃣ 您给的 05718886666 是固定电话，收不到短信验证码呢～麻",
    # issue #3757 验收标准逐字点名的两个形态
    "验证码已收到，别再发了",
    "验证码我收到啦，不用再发啦～请您点一下上面的确认卡片",
)

#: 真索取形态（**不得**被改判 —— 防"把判据改死"）
_ASK_FORMS = (
    "请提供验证码",
    "验证码是多少",
    "请把收到的验证码发我",
    "麻烦您提供一下短信验证码",
    "验证码输入错误，请重新输入",
    "为了您的账户安全，请输入收到的短信验证码",
    # 既有 L0 夹具（#3829 锁定的"软信号仍算真"，逐字取自 test_eval_auto_respond_l0.py）
    "亲，需要 11 位手机号哦（用来接收下单验证码）～ 我把收货信息表发给您",
    "亲，需要 11 位手机号哦（用来接收下单验证码）～ 我把信息表发给您，填一下就好",
)

#: 收讫 + **再索取**并存（索取优先 ⇒ 仍判索码；不许做成"见收讫即否"）
_REASK_FORMS = (
    "验证码已收到，不过刚才那个过期了，请再发一次",
    "亲，还没收到您的验证码呢，麻烦发一下～",
)

#: **未固化边界**（如实登记）：无索取形态、也无收讫标记的转人工/旁观话术（实测 R10 逐字）。
#: 本条不是"期望它错"，而是**把现状钉住**：谁若把它改成"不判索码"（例如引入结构信号），
#: 必须同时更新本登记与 PR 里的影响面结论，不许静默改判。
_RESIDUAL_ACK = (
    "亲，看您连着发了好几次验证码，估计是确认按钮一直点不动吧？😥 不耽误您时间了，我这就帮您转人工客服，让同事协助您把订单提",
)

_CORPUS = tuple([(t, False) for t in _TRACE_ACK]
                + [(t, True) for t in _ASK_FORMS]
                + [(t, True) for t in _REASK_FORMS])


def _round(*, text="", cards=(), user="123456"):
    """一轮 SSE 轨迹（字段名与 `build_round_trace` 同源）。"""
    return {"round": 1, "user_message": user, "final_text": text,
            "interactive": list(cards), "tool_calls": [], "tool_results": []}


def _pending_confirm_round(text: str):
    """上一轮形态 = 真实 trace R3：待答确认卡 + 收讫话术 + 写调用被确认门禁拦回。"""
    r = _round(text=text, cards=[{"type": "confirm", "title": "亲，请核对订单信息，点「确认下单」我就帮您提交～",
                                  "confirmValue": _CONFIRM_VALUE}])
    r["tool_calls"] = [{"name": "order_create"}]
    r["tool_results"] = [{"tool": "order_create",
                          "result": {"success": False, "error": "confirmation_required_no_card"}}]
    return [r]


_CONFIRM_VALUE = "确认：加工项=纳米圈打孔 ¥8/米 × 3米 = ¥24；商品=遮光窗帘（米白 · 门幅 2.8 米）× 3 米"


# ── ① 真实 trace 逐字回执判「不在索码」（改前必红）─────────────────────────────

def test_verbatim_ack_replies_are_not_code_requests():
    """改前子串判据把 10 条逐字回执全判成"在索码"（红）；形态判据下必须全部为 False。"""
    still = [t for t in _TRACE_ACK if lr._agent_asked_for_code([_round(text=t)])]
    assert still == [], (
        "以下**收讫语义**的回复仍被判成『agent 在索码』⇒ harness 不会点卡、只会一轮轮回验证码"
        "（OR-026 死循环原形，issue #3757）：\n  " + "\n  ".join(repr(t) for t in still))


def test_verbatim_ack_round_clicks_the_pending_confirm_card():
    """**本单本体（行为层）**：收讫话术 + 待答 confirm 卡 ⇒ 本轮必须**点卡**（回 confirmValue）。

    改前：`_code_gate_blocked` 为 False（拦回原因 `confirmation_required_no_card` 不含码），
    但文字命中"验证码" ⇒ 走供码分支 ⇒ 得到 `'123456'` ⇒ 卡永远没人点。红证 = 本断言收到 `'123456'`。
    """
    got = lr.resolve_repeat_turn(_pending_confirm_round(_TRACE_ACK[3]),
                                 {"code": "123456", "fallback": "确认下单"}, {})
    assert got != "123456", (
        f"收讫话术仍让 harness 再发一次验证码（{got!r}）—— 确认卡不会被点，"
        f"写调用必被确认门禁反复拦回（issue #3757）")
    assert got == _CONFIRM_VALUE, (
        f"本轮的下一步不是点卡（发的是 {got!r}）—— 前端点击协议要求回 confirmValue，"
        f"否则产品闸门仍判 confirmation_required_card_not_clicked")


def test_verbatim_ack_round_would_still_send_the_code_when_the_gate_blocked_on_code():
    """反向守卫（#3430 的原始死锁，**语义逐字不变**）：写调用**因缺码被挡** ⇒ 硬信号最优先 ⇒ 供码。

    收讫话术也压不过硬信号 —— 那是"码没送到"的真实事故，必须先把码送出去。
    """
    rounds = _pending_confirm_round(_TRACE_ACK[3])
    rounds[0]["tool_results"] = [{"tool": "order_create",
                                  "result": {"success": False, "error": "缺少短信验证码"}}]
    got = lr.resolve_repeat_turn(rounds, {"code": "123456", "fallback": "确认下单"}, {})
    assert got == "123456", f"缺码硬信号被形态判据挤掉了（run 34768306581 的死锁会复发）：{got!r}"


# ── ③ 真索取形态不得被改判（防"把判据改死"）────────────────────────────────

def test_request_forms_are_still_code_requests():
    """真索取形态 + 既有 L0 夹具（#3829 的软信号）⇒ 必须仍判索码。"""
    missed = [t for t in _ASK_FORMS if not lr._agent_asked_for_code([_round(text=t)])]
    assert missed == [], (
        "以下**真在索码**的回复不再被识别 ⇒ CH-010/OR-021 那类验证码轮会送不出码"
        "（把一类红换成另一类）：\n  " + "\n  ".join(repr(t) for t in missed))


def test_receipt_with_a_reask_is_still_a_code_request():
    """收讫 + 再索取并存 ⇒ **索取优先**（只做"见收讫即否"的粗判会把这一类判死）。"""
    missed = [t for t in _REASK_FORMS if not lr._agent_asked_for_code([_round(text=t)])]
    assert missed == [], (
        "『已收到/没收到 + 请再发一次』被判成回执 ⇒ 该供码时供不出码：\n  "
        + "\n  ".join(repr(t) for t in missed))


def test_residual_handoff_form_is_registered_as_still_asking():
    """**未固化边界登记**：转人工/旁观话术（无索取形态、无收讫标记）当前仍判索码。

    钉住现状：改成"不判索码"必须同 PR 更新本登记与影响面结论（不许静默改判）。
    """
    got = lr._agent_asked_for_code([_round(text=_RESIDUAL_ACK[0])])
    assert got is True, (
        f"该形态的判定变了（现在 {got!r}）—— 未固化边界被静默改判：请同步更新 "
        f"`_RESIDUAL_ACK` 的登记理由与 PR 影响面")


# ── ⑤⑥ 判别力自证（防校验器空转）────────────────────────────────────────────

def _corpus_violations(classify) -> list:
    """**纯函数校验器**：按 `_CORPUS` 逐条比对，返回违规清单（空 = 全部判对）。"""
    out = []
    for text, want_ask in _CORPUS:
        got = bool(classify(text))
        if got != want_ask:
            out.append(f"{'误判成索码' if got else '漏判索码'}: want={want_ask} got={got} {text!r}")
    return out


def test_corpus_validator_rejects_the_substring_only_criterion():
    """**判别力自证**：把改前的"子串充分条件"喂给校验器 ⇒ 必须报出**误判**（否则校验器是空转）。

    同时钉住"改前对真索取是判对的" —— 证明本单的差异**只**在收讫侧（不是把判据整体推翻）。
    """
    def legacy_substring_only(text):
        return any(h in text for h in lr._CODE_REQUEST_HINTS)

    bad = _corpus_violations(legacy_substring_only)
    assert bad, "校验器对改前形态零违规 —— 它是空转的（不会红的断言 = 空断言）"
    assert all(v.startswith("误判成索码") for v in bad), (
        "改前形态的问题应**只在收讫侧**（真索取侧它本来就判对）：\n  " + "\n  ".join(bad))


def test_corpus_is_two_sided_and_clean_for_the_current_criterion():
    """语料两侧都有（非单极）+ 当前判据零违规（漏判/误判任一条 ⇒ 红）。"""
    polarities = sorted({want for _, want in _CORPUS})
    assert polarities == [False, True], f"语料只有单极（{polarities}）—— 断言会退化成恒真"
    bad = _corpus_violations(lr.text_requests_code)
    assert bad == [], "当前判据在校验语料上仍有违规：\n  " + "\n  ".join(bad)


# ── ⑦ 孪生入口（验收侧）同一语义 ────────────────────────────────────────────

def _load_acceptance_runner():
    """导入 `acceptance_runner`（与本目录其它 L0 文件同形的零依赖加载）。"""
    import importlib.util as _ilu
    path = AGENT_EVAL / "acceptance_runner.py"
    spec = _ilu.spec_from_file_location("migao_acceptance_runner_for_l0", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_twin_entry_point_uses_the_same_semantics():
    """**类级**：验收侧 `acceptance_runner.needs_code` 的文字腿必须与评测侧同一语义。

    红证：本单只改评测侧 ⇒ 收讫话术在验收剧本里仍被当"在要码" ⇒ 本断言红。
    """
    ar = _load_acceptance_runner()
    ack = [{"ai_text": _TRACE_ACK[3], "interactive": [{"type": "confirm", "confirmValue": "确认下单"}]}]
    ask = [{"ai_text": _ASK_FORMS[0], "interactive": []}]
    assert ar.needs_code(ack) is False, (
        "验收剧本侧仍把『验证码已收到/点卡』当索码 ⇒ 剧本会一轮轮供码、不点卡（issue #3757 同形）")
    assert ar.needs_code(ask) is True, "验收剧本侧不再识别真索取 ⇒ 该供码时供不出码"


def test_hard_signal_still_wins_in_the_twin_entry_point():
    """反向守卫：孪生入口的**硬信号**（写调用因缺码失败）语义逐字不变。"""
    ar = _load_acceptance_runner()
    rounds = [{"ai_text": "好的亲～", "interactive": [],
               "tool_results": [{"result": {"success": False, "error": "缺少短信验证码"}}]}]
    assert ar.needs_code(rounds) is True, "验收侧缺码硬信号被形态判据挤掉（#3431 的死锁会复发）"


# ── ⑧ 词表单一归属（防"同一张表复制三份"）────────────────────────────────────

def _hint_table_definitions():
    """扫 `tests/agent_eval/*.py`：非注释行里同时定义 ≥2 个验证码词 + 词表赋值形态。"""
    rows = []
    for path in sorted(AGENT_EVAL.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if not re.search(r"(HINTS?|_HINTS?)\s*[:=]", line):
                continue
            hits = [w for w in ("验证码", "校验码", "短信码", "动态码") if w in line]
            if len(hits) >= 2:
                rows.append((path.name, line.strip()[:70]))
    return rows


def test_code_hint_wordlist_has_a_single_home():
    """**类级元守卫**：验证码词表只能有一处定义 —— 谁再复制一张（新 runner / 新腿）⇒ 红并指名。

    理由即本单病根的同族：一张表复制三份 ⇒ 语义必然漂移（`needs_code` 与
    `_agent_asked_for_code` 此前就是各写一份子串判据，改一处漏一处）。
    """
    rows = _hint_table_definitions()
    homes = sorted({name for name, _ in rows})
    assert homes == ["local_runner.py"], (
        f"验证码词表的定义处应恰好是 ['local_runner.py']，实际 {homes}：\n  "
        + "\n  ".join(f"{n}: {line}" for n, line in rows)
        + "\n修法：复用 `local_runner.CODE_HINTS`（硬信号腿）与 "
          "`local_runner.text_requests_code()`（文字腿），不要各写一张表")