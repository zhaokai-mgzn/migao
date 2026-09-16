# case_ids: OR-014
"""**L0 红证**：OR-014 交互轮从「发验证码 `123456`」改为「点击/应答确认卡」（B 端代客下单免验证码）。

## 证据（窄跑 34930597539，main 6a55d73b，persona=mibao，零 LLM 复现）

产品侧已修，**剩下的红是用例陈旧**：

1. R8 确认卡金额**已接地正确**（单价 168）：
   `confirmValue=确认：加工项=纳米圈打孔 ¥8/米 × 3 米 = ¥24；商品=遮光窗帘 …合计=¥528`
2. R9~R11 轮声明 `prefer_text: true` + fallback `123456` ⇒ harness **故意无视待答确认卡**、
   逐轮发文本 `123456`（日志逐字：「↳ R9 prefer_text 忽略了待答卡片 [confirm:…] → 本轮发文本 '123456'」）。
3. 确认卡从未被点击 ⇒ R11 的 `order_create` 被产品闸门以
   `confirmation_required_card_not_clicked` 拒绝（`base_skill.py` 的写工具确认门禁：
   用户消息必须**精确等于**最近确认卡的 `confirmValue` 才算点击，`_is_card_confirm_value`）。

## 本文件锁三件事（全部 L0、零 LLM、走 runner 既有 `resolve_auto_respond` 口径）

| # | 断言 | 红证（改回修前形态即红） |
|---|---|---|
| ① | **改前形态**（`prefer_text: true` + `123456`）重放 R9~R11 ⇒ 确认卡从未被点击 ⇒ `order_create` 必被 `confirmation_required_card_not_clicked` 拒（复现窄跑） | —— 负向夹具：旧声明是红因 |
| ② | **改后形态**（同轮去掉 `prefer_text`）同一重放 ⇒ 确认卡被点击（回 `confirmValue`）⇒ `order_create` 成功路径可达（绿） | 把 ② 用到的轮改回 `prefer_text: true` ⇒ 红 |
| ③ | **反向**：真的不点卡（回任意非 `confirmValue` 文本）仍必须被拒 ⇒ 产品闸门有效、不许绕过 | 移除产品闸门模型 ⇒ 空断言（禁止） |

断言（`must_succeed`/`amount_verify`/`precondition`/`pre_clean`）**零改动**，本文件末格锁定。

⚠️ 本目录在 CI 只 `pip install pytest pyyaml`（`.github/workflows/pr-check.yml`），
而 `local_runner` 有模块级 `import httpx` ⇒ 用下方最小替身（与
`test_eval_auto_respond_l0.py` 同形）。被锁的是纯函数 `resolve_auto_respond` 与
用例声明本身，不该因缺一个 HTTP 客户端而不可测。
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
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


def _or014():
    """取 OR-014 用例；缺失/重名即失败（守卫对象不存在时断言会静默空跑）。"""
    found = [c for c in lr.load_cases_from_yaml(str(CASES_DIR))
             if str(getattr(c, "id", "")) == "OR-014"]
    assert len(found) == 1, (
        f"用例库里 OR-014 命中 {len(found)} 条（期望恰好 1 条）—— 用例库路径/解析失效")
    return found[0]


# ── 窄跑 R8 的待答确认卡（金额已接地：单价 168、加工费 24、合计 528）──────────
_CONFIRM_VALUE = ("确认：加工项=纳米圈打孔 ¥8/米 × 3 米 = ¥24；"
                  "商品=遮光窗帘 · 米白 ｜ 散剪 ｜ 门幅 2.8 米；合计=¥528")


def _pending_confirm_round():
    """上一轮**待答确认卡**（窄跑 R8 形态：`cardreq=confirm:请核对订单信息，确认后立即下单`）。"""
    return [{"user_message": "x", "interactive": [
        {"type": "confirm", "title": "请核对订单信息，确认后立即下单",
         "confirmValue": _CONFIRM_VALUE}]}]


def _product_gate_rejects(last_user_msg: str) -> bool:
    """**产品闸门模型**（与 `base_skill.py::_is_card_confirm_value` 精确匹配同源）：
    写工具（order_create）放行 ⇔ 用户消息**逐字符等于**最近确认卡的 confirmValue
    （= 顾客点了确认按钮）；否则 ⇒ `confirmation_required_card_not_clicked`。

    红证（③ 反向）：把本模型改成"任何文本都放行" ⇒ ① 的"必被拒"断言红（空断言自毁）。
    """
    return str(last_user_msg or "").strip() != _CONFIRM_VALUE


# ── ① 改前形态（prefer_text=true + 123456）重放 ⇒ 必红（复现窄跑）────────────

def test_stale_shape_prefer_text_round_never_clicks_confirm_card():
    """改前声明 `{fallback: "123456", prefer_text: true}` ⇒ harness 无视待答确认卡、
    逐轮发 '123456' ⇒ 确认卡从未被点击 ⇒ 产品闸门必拒 `order_create`
    （窄跑 34930597539 R9~R11 逐字复现，失败指纹 `confirmation_required_card_not_clicked`）。"""
    got = lr.resolve_auto_respond(
        _pending_confirm_round(), fallback="123456", form_values={}, prefer_text=True)
    assert got == "123456", f"改前形态应无视卡发验证码文本，实际发 {got!r}"
    assert got != _CONFIRM_VALUE, "改前形态竟点击了确认卡 —— 复现前提失效"
    assert _product_gate_rejects(got), (
        "确认卡未被点击，order_create 却被产品闸门放行 —— 闸门模型失效（假绿）")


def test_stale_shape_rounds_still_exist_as_negative_fixture():
    """把 OR-014 的四个「123456」轮逐轮断言：**当前（修后）声明不是** prefer_text=true。
    红证：把这四个轮改回 `prefer_text: true` ⇒ 本断言红（用例陈旧形态不得复活）。"""
    case = _or014()
    code_rounds = [u for u in case.user_inputs
                   if isinstance(u, dict)
                   and str((u.get("auto_respond") or {}).get("fallback") or "") == "123456"]
    assert len(code_rounds) == 4, (
        f"OR-014 的 123456 轮数量变了（{len(code_rounds)}，期望 4）—— 用例形状被改动，本守卫需重新校准")
    for u in code_rounds:
        ar = u.get("auto_respond") or {}
        assert not ar.get("prefer_text"), (
            f"OR-014 的 123456 轮仍声明 prefer_text=true：{ar} —— "
            f"B 端代客下单免验证码，它只会无视待答确认卡（窄跑 34930597539 红因）")


# ── ② 改后形态（去掉 prefer_text）同一重放 ⇒ 确认卡被点击 ⇒ 绿 ───────────────

def test_fixed_shape_replay_clicks_confirm_card():
    """改后声明 `{fallback: "123456"}`（无 prefer_text）⇒ 有待答确认卡就**点击**
    （回 confirmValue，前端点击协议）⇒ 产品闸门放行 ⇒ `order_create` 成功路径可达。

    红证：把本轮的 `prefer_text` 参数改回 True ⇒ 回到 '123456' ⇒ 本断言红。
    """
    got = lr.resolve_auto_respond(
        _pending_confirm_round(), fallback="123456", form_values={}, prefer_text=False)
    assert got == _CONFIRM_VALUE, (
        f"去掉 prefer_text 后仍未点击确认卡（发 {got!r}）—— 确认卡被点击的路径不可达")
    assert not _product_gate_rejects(got), "已点击确认卡仍被产品闸门拒 —— 成功路径不可达"


def test_fixed_case_rounds_resolve_to_click_on_pending_confirm():
    """**同一重放用真实用例文件**：OR-014 的 123456 轮（无 prefer_text）在待答确认卡时
    必须解析出 confirmValue（点击），而不是 '123456'。红证：改回 prefer_text ⇒ 红。"""
    case = _or014()
    hits = 0
    for u in case.user_inputs:
        if not (isinstance(u, dict) and u.get("auto_respond")):
            continue
        ar = u["auto_respond"]
        if str(ar.get("fallback") or "") != "123456":
            continue
        got = lr.resolve_auto_respond(
            _pending_confirm_round(),
            fallback=str(ar.get("fallback") or "123456"),
            form_values=dict(getattr(case, "auto_fill", None) or {}),
            prefer_text=bool(ar.get("prefer_text")),
        )
        if got == _CONFIRM_VALUE:
            hits += 1
    assert hits >= 1, (
        "OR-014 的 123456 轮在待答确认卡时没有一个解析出 confirmValue —— "
        "改后形态未真正落到用例声明（窄跑 R9~R11 形态会复发）")


# ── ③ 反向：真的不点卡仍必须被拒（产品闸门有效，不许绕过）────────────────────

def test_reverse_no_click_is_still_rejected():
    """反向：即使用例改成"答卡优先"，**真的不点卡**（顾客回任意非 confirmValue 文本）
    ⇒ 产品闸门仍以 `confirmation_required_card_not_clicked` 拒 `order_create`。

    意义：改的是**用例交互轮**，不是**产品闸门** —— 闸门有效性是红证的前提，
    不许通过"放宽断言/绕过闸门"来让用例变绿。
    """
    for msg in ("123456", "确认下单", "好的", "确认", ""):
        assert _product_gate_rejects(msg), f"顾客没点卡（回 {msg!r}）却被放行 —— 闸门被绕过"


def test_product_gate_error_code_exists_in_product_source():
    """产品闸门**真实存在**（不是测试自造的模型）：`base_skill.py` 的写工具确认门禁
    必须仍在源码里（删掉 = 所有"点确认"交互轮一起失效，本用例红证随之失去意义）。"""
    src = (REPO_ROOT / "backend" / "ai-agent-service" / "app" / "graph" / "skills"
           / "base_skill.py").read_text(encoding="utf-8")
    assert "confirmation_required_card_not_clicked" in src, (
        "产品侧确认卡门禁错误码已不存在 —— 产品行为变更，本 L0 红证的前提失效")
    assert "_is_card_confirm_value" in src, (
        "产品侧确认卡点击判据函数已改名 —— 闸门模型与产品源码脱同步")


# ── 断言零改动（锁）：不许为让单绿删/改断言 ──────────────────────────────────

def test_or014_assertions_are_unchanged():
    """断言零改动锁：`must_succeed: order_create`、`amount_verify`（unit_price/subtotal/total）、
    `precondition[product_count_for_keyword: 遮光窗帘, expect: 1]`、`pre_clean[product_dedupe]`
    必须原样保留（本 PR 只动交互轮，不改任何断言）。红证：删任一 ⇒ 红。"""
    case = _or014()
    assert [x.get("tool") for x in case.must_succeed] == ["order_create"], case.must_succeed
    av = case.amount_verify
    assert av and av[0].get("tool") == "order_create", av
    checks = av[0].get("checks") or []
    for want in ("unit_price", "subtotal", "total"):
        assert want in checks, f"amount_verify 的 checks 缺失 {want}：{checks}"
    assert any(p.get("type") == "product_count_for_keyword"
               and p.get("source") == "遮光窗帘" and p.get("expect") == 1
               for p in case.precondition), case.precondition
    assert any(p.get("type") == "product_dedupe"
               and p.get("product_keyword") == "遮光窗帘"
               for p in case.pre_clean), case.pre_clean
