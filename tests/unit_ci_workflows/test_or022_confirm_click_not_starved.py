# case_ids: OR-022
"""**L0** 守卫：OR-022 的「验证码轮」不得吞掉待答的 confirm 卡（issue #9280）。

## 被钉住的缺陷（判定跑 46086496186 @be827c3d4，xiaobu 腿 OR-022 score 0 的**唯一**失败）

失败原文：`确认死循环: confirm 卡「请核对订单信息…」同样的事实共出现 3 次（R4/R5/R6）`。
而**同一份 trace** 的走向是：

| 轮 | 顾客消息 | 发生了什么 |
|---|---|---|
| R4 | `已选加工项：打孔（顶部打孔）` | 模型发 confirm 卡（`confirmValue=确认下单`）|
| R5 | `123456` | `order_create` → `confirmation_required_card_not_clicked`；模型重发同一张卡 |
| R6 | `123456` | 同上（第二次） |
| **R7** | `确认：加工=打孔…；合计=¥504`（= 那张卡的 confirmValue）| **点卡 → order_create 成功**（`orderNo=20261128157620009`）|

⇒ 流程在 9 轮内**收敛并真的建成了订单**；R4/R5/R6 三张同内容键的卡之所以出现，是因为
R5/R6 这两个「验证码轮」声明了 `prefer_text: true` —— 它的语义是**无视待答卡片、本轮硬发这句
文本**，于是 R4 刚发出的确认卡**两次都没有人点**，而确认卡未被点击时 `order_create` 必然被
`confirmation_required_card_not_clicked` 挡回、模型只能再发一次卡。判据把这条 harness 决策
读成了「模型层不收敛」。

## 本文件锁四件事

| # | 断言 | 红证（改回修前形态即红） |
|---|---|---|
| ① | OR-022 的**码轮**（fallback 为 6 位数字）不得声明 `prefer_text` | 给任一码轮加回 `prefer_text: true` ⇒ 红（点名命中轮次） |
| ② | **行为面**：把该 run 的真实形状（末轮发出 confirm 卡 + 码轮作答）喂给 `resolve_auto_respond`，答复必须是**那张卡的 `confirmValue`**（= 点卡回传），不是 `123456` | 同上 ⇒ 得到 `'123456'` ⇒ 红 |
| ③ | **夹具自证**：同一夹具在 `prefer_text=True` 下必须返回 `123456`（否则 ② 可能是空断言） | 夹具里的卡被删/改成无 `confirmValue` ⇒ 红 |
| ④ | **不缩水**：轮数仍是 9、`order_before: interact[confirm] before order_create` 仍在 —— 删轮或删掉
「确认卡先行」契约都算放宽 | 删任一轮 / 删该 `order_before` ⇒ 红 |

零 LLM、零网络：被锁的是纯函数 `resolve_auto_respond`（`local_runner` 模块级 `import httpx`
⇒ 用下方最小替身，与 `test_eval_auto_respond_l0.py` 同形）。
"""
import sys
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = REPO_ROOT / ".github" / "cases" / "order.yml"
sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))

CASE_ID = "OR-022"
#: 该 run R4 发出的那张 confirm 卡（逐字取自 artifact 的 `callargs`）
CONFIRM_CARD = {
    "type": "confirm",
    "title": "请核对订单信息，确认无误后提交",
    "confirmValue": "确认下单",
    "confirmLabel": "确认下单",
}
#: 该 run 的顾客侧轮次消息（R1~R4，逐字取自 trace；R4 之后卡在等）
CUSTOMER_MESSAGES = [
    "我想买遮光窗帘，米白 3 米，要打孔加工",
    "米白",
    "张三 13800138000 浙江省杭州市西湖区文三路1号1幢101室",
    "已选加工项：打孔（顶部打孔）",
]


def _load_runner():
    """导入 `local_runner`（缺 httpx 时注入最小替身；替身一旦被调用即抛错）。"""
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


def _case() -> dict:
    """取 OR-022 的**真值块**（只认 yml；命中条数 ≠ 1 即失败 —— 守卫对象缺失会静默空跑）。"""
    doc = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    hits = [c for c in (doc.get("cases") or []) if str(c.get("id")) == CASE_ID]
    assert len(hits) == 1, (
        f"{CASES_PATH} 里 {CASE_ID} 命中 {len(hits)} 条（期望恰好 1 条）—— "
        f"守卫对象缺失/重名，本文件的断言会静默空跑")
    return hits[0]


def _code_rounds(case: dict) -> list:
    """码轮 = 声明 `auto_respond.fallback` 为 6 位数字的轮次 → [(轮次, 该轮 auto_respond)]。"""
    found = []
    for idx, turn in enumerate(case.get("user_inputs") or [], 1):
        if not isinstance(turn, dict):
            continue
        spec = turn.get("auto_respond") or {}
        fallback = str(spec.get("fallback") or "").strip()
        if len(fallback) == 6 and fallback.isdigit():
            found.append((idx, spec))
    return found


def _fixture_results() -> list:
    """该 run 的真实形状：R1~R3 无卡、R4 末发出 confirm 卡（R5/R6 就是它的两个点卡机会）。"""
    results = [{"__round": i, "user_message": msg, "interactive": [], "tool_calls": []}
               for i, msg in enumerate(CUSTOMER_MESSAGES, 1)]
    results[-1]["interactive"] = [dict(CONFIRM_CARD)]
    return results


def test_no_code_round_declares_prefer_text():
    """① 码轮不得声明 `prefer_text` —— 它是「无视待答卡」的开关，会吃掉点卡机会。"""
    case = _case()
    offenders = [idx for idx, spec in _code_rounds(case) if spec.get("prefer_text")]
    assert offenders == [], (
        f"{CASE_ID} 的第 {offenders} 轮声明了 prefer_text —— 该轮会把待答的确认卡硬发成 "
        f"123456（= 点卡机会被吃掉 ⇒ order_create 被 confirmation_required_card_not_clicked "
        f"挡回 ⇒ 模型重发同一张卡 ⇒ 被 check_confirm_loop 判「确认死循环」，"
        f"实证 run 46086496186 的 R4/R5/R6）")


def test_code_round_clicks_the_pending_confirm_card():
    """② 行为面：码轮遇到待答 confirm 卡 ⇒ 必须回该卡的 `confirmValue`（点卡），不是码本身。"""
    case = _case()
    rounds = _code_rounds(case)
    assert [idx for idx, _ in rounds] == [5, 6], (
        f"{CASE_ID} 的码轮 = {[idx for idx, _ in rounds]}（期望 [5, 6]）—— "
        f"轮次表已变，本判据的前提（码轮紧跟在确认卡之后）需重新核对")
    for idx, spec in rounds:
        answer = lr.resolve_auto_respond(
            _fixture_results(),
            fallback=str(spec.get("fallback") or ""),
            form_values=dict(case.get("auto_fill") or {}),
            prefer_text=bool(spec.get("prefer_text")),
        )
        assert answer == CONFIRM_CARD["confirmValue"], (
            f"{CASE_ID} 第 {idx} 轮（码轮）对着待答的 confirm 卡回了 {answer!r} —— "
            f"点卡回传必须是卡自己的 confirmValue {CONFIRM_CARD['confirmValue']!r}；"
            f"回 {answer!r} 等于「顾客没点卡」，确认门禁会把下一轮 order_create 挡回")


def test_fixture_really_has_a_pending_confirm_card():
    """③ 夹具自证：同夹具 + `prefer_text=True` ⇒ 得到码本身（证明②不是空断言）。"""
    fixture = _fixture_results()
    pending = [iv for iv in fixture[-1]["interactive"] if iv.get("type") == "confirm"]
    assert len(pending) == 1, f"夹具末轮待答 confirm 卡 {len(pending)} 张（期望 1 张）"
    assert pending[0]["confirmValue"] == CONFIRM_CARD["confirmValue"]
    swallowed = lr.resolve_auto_respond(fixture, fallback="123456", form_values={},
                                        prefer_text=True)
    assert swallowed == "123456", (
        f"prefer_text=True 下应硬发码本身，实得 {swallowed!r} —— "
        f"若它变了，② 的「吞掉」语义已不成立，本判据需重新归因")


def test_case_budget_and_confirm_contract_not_shrunk():
    """④ 不缩水：9 轮 + 「确认卡先行」契约仍在（删轮/删契约都是另一种放宽）。"""
    case = _case()
    assert len(case.get("user_inputs") or []) == 9, (
        f"{CASE_ID} 轮数 = {len(case.get('user_inputs') or [])}（期望 9）—— "
        f"不得靠删轮规避判据")
    order_before = [str(x) for x in (case.get("order_before") or [])]
    assert "interact[confirm] before order_create" in order_before, (
        f"{CASE_ID} 缺 order_before「interact[confirm] before order_create」—— "
        f"本判据的前提（点卡必须先于 order_create）被删掉了: {order_before}")
