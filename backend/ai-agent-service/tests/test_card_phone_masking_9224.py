# case_ids: CU-004, HR-010
"""确认卡只许展示**掩码**手机号（issue #9224；用户 2026-11-27 产品口径裁定）。

裁定原文（逐字）：

    「确认卡是否允许展示完整手机号，这个裁定是**展示脱敏后的手机号**，不能完整展示」

**被否决**的两个出口（不要再回去动它们）：

    ① 让 `interact` 的工具结果豁免脱敏（卡面直接显示完整号 ⇒ 静默改变聊天的隐私面）；
    ② 卡面携带 `rawValue` / `submitValue` 真值字段（真值进模型上下文与 SSE，等价于 ①）。

**已交付**的两半（不在本文件射程内，别重做）：PR #9253（掩码值唯一匹配顾客亲口给的号 ⇒ 改写放行）、
PR #9260（拦截时纠正提示只指向顾客给的号）。

本文件钉的是**展示面**这一半（落在 `_execute_tool_safe` 的出口 —— confirm 卡载荷的唯一产出点）：

    A. 卡片载荷里**不得出现任何完整 11 位手机号**（出现即红，具名打出来源 key）；
    B. 掩码必须对得上「**这次真正要写的那个号**」（真号 A + 模型抄来的旧掩码 B ⇒ 卡面出现
       mask(A)、不得出现 B）—— 本包的核心语义（CU-004 现场：展示旧号、写入新号）；
    C. 幂等：模型交上来已是掩码 ⇒ 输出逐字不变（掩码再掩码 = 同一串）；
    D. 边界：点卡**不**从卡面 `fields` 拼写参数 ⇒ 掩码化后写路径仍拿得到真值（`pending_validated_input`）。
"""

import ast
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from app.graph.skills.base_skill import confirm_value_for_fields
from app.graph.skills.phone_masking import (
    mask_confirm_card_fields,
    mask_phone_value,
    pending_write_phones,
    raw_phones_in,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: 顾客这次给的真号 = **本轮真正要写入**的号（CU-004 现场的新号）
NEW_NUMBER = "13900001111"
#: 模型从「被脱敏过的工具结果」里抄来的**旧号**掩码（CU-004 现场的卡面值）
OLD_MASK = "138****8000"
#: 旧号本身（模型把掩码填成 0 的形态，历史事故的落库值）
OLD_RAW = "13800008000"
#: 真号应有的掩码（前 3 + `****` + 后 4）
MASK_OF_NEW = "139****1111"


def _confirm_payload(fields):
    """`interact(component=confirm)` 的载荷形状（逐字对齐 `app/tools/interact.py` 的 confirm 分支）。"""
    return {
        "component": "confirm",
        "title": "请确认客户资料",
        "fields": fields,
        "confirmLabel": "确认",
        "cancelLabel": "取消",
        "confirmValue": confirm_value_for_fields(fields),
        "cancelValue": "取消",
    }


def _full_phones_in(payload):
    """载荷里出现的**完整** 11 位手机号 → `[(来源 key, 号码)]`（具名，便于归因）。"""
    hits = []

    def _walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                _walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                _walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            for phone in sorted(raw_phones_in(node)):
                hits.append((path, phone))

    _walk(payload, "")
    return hits


class _Store:
    """会话状态替身：`load` 每次返回**新副本**，`commit` 被逐次记录（写路径真值被改 = 红）。"""

    def __init__(self, full):
        self.full = full
        self.commits = []

    async def load(self, session_id):
        return json.loads(json.dumps(self.full))

    async def commit(self, session_id, new_full):
        self.commits.append(new_full)


async def _run_interact(fields, pending_params=None):
    """走**真实**的整形入口（`phone_masking.mask_confirm_card_result`）跑一张 confirm 卡。

    为什么不在单测里直接调 `mask_confirm_card_fields`：判据要钉的是「掩码化**长在卡片载荷那一跳**上」
    —— 实现在 `phone_masking.mask_confirm_card_result`，接线在
    `app/graph/skills/execution/react_turn.py`（追加 `ToolMessage` 之前调用并重算 `result_str`，
    见 `TestWiring`）。只测纯函数会漏掉这条接线，是本仓库反复批判的假绿形态。
    """
    from app.graph.skills.phone_masking import mask_confirm_card_result

    full = {}
    if pending_params is not None:
        full["pending_validated_input"] = {
            "target_tool": "customer_manage",
            "target_action": "update",
            "params": pending_params,
        }
    store = _Store(full)
    result_dict = {"success": True, "data": _confirm_payload(fields),
                   "error": None, "message": "已展示", "summary": "", "suggestion": "",
                   "terminal": False, "error_code": None, "missing_params": []}
    with patch("app.memory.session_state_store.SessionStateStore",
               side_effect=lambda *a, **k: store):
        await mask_confirm_card_result("interact", result_dict, "sess_9224")
    return result_dict["data"], store


def _run(fields, pending_params=None):
    return asyncio.run(_run_interact(fields, pending_params))


# ══════════ A. 卡片载荷里不得出现任何完整 11 位手机号 ══════════
class TestNoFullPhoneOnTheCard:
    def test_full_number_on_card_is_masked(self):
        """模型把**完整真号**写进卡片 ⇒ 卡面只能是掩码形态。"""
        card, _ = _run([{"label": "手机号", "value": NEW_NUMBER}])
        assert card["fields"][0]["value"] == MASK_OF_NEW, (
            f"卡面仍是完整手机号（来源 fields[0].value）：{card['fields']!r}")
        assert _full_phones_in(card) == [], (
            f"卡片载荷里出现了完整手机号（来源 key 具名）：{_full_phones_in(card)}")

    def test_phone_in_non_phone_named_field_is_masked_by_value(self):
        """字段名不是手机号（`备注`）但值像手机号 ⇒ **按值**判、同样掩码。"""
        card, _ = _run([
            {"label": "备注", "value": "顾客说有事打 13900001111"},
            {"label": "联系方式", "value": "13900001111"},
        ])
        assert card["fields"][0]["value"] == "顾客说有事打 139****1111", (
            f"备注里的号码未被掩码（来源 fields[0].value）：{card['fields']!r}")
        assert card["fields"][1]["value"] == "139****1111", (
            f"联系方式里的号码未被掩码（来源 fields[1].value）：{card['fields']!r}")
        assert _full_phones_in(card["confirmValue"]) == [], (
            f"confirmValue 仍含完整手机号（点卡回传的就是它）：{card['confirmValue']!r}")

    def test_order_number_is_not_mistaken_for_a_phone(self):
        """订单号里的 11 位数字片段**不得**被当成手机号掩码掉（数字边界口径）。"""
        card, _ = _run([{"label": "订单号", "value": "20260913027050006"}])
        assert card["fields"][0]["value"] == "20260913027050006", (
            f"订单号被误掩码（卡面/回执将认不出单号）：{card['fields']!r}")


# ══════════ B. 掩码必须对得上「这次真正要写的那个号」（本包核心语义）══════════
class TestMaskMatchesTheWriteNumber:
    def test_old_mask_on_card_is_replaced_by_the_new_number_mask(self):
        """真号 A + 模型抄来的旧掩码 B ⇒ 卡面必须是 mask(A)，**不得**出现 B（CU-004 现场）。"""
        card, store = _run(
            [{"label": "手机号", "value": OLD_MASK}],
            pending_params={"customer_phone": NEW_NUMBER},
        )
        assert card["fields"][0]["value"] == MASK_OF_NEW, (
            f"卡面展示的号与本轮要写入的号不是同一个（卡面 {card['fields'][0]['value']!r}，"
            f"将要写入 {NEW_NUMBER!r}）")
        assert OLD_MASK not in json.dumps(card, ensure_ascii=False), (
            f"卡面仍留着旧号的掩码（顾客会以为改的是旧号）：{card!r}")
        # confirmValue 由**掩码后**的字段派生（顾客点卡回传的就是它，门禁比对的也是它）
        assert card["confirmValue"] == confirm_value_for_fields(card["fields"]), (
            f"confirmValue 与卡面字段不同源 ⇒ 点卡会被判「未确认」：{card['confirmValue']!r}")
        assert MASK_OF_NEW in card["confirmValue"], (
            f"confirmValue 没跟着改写 ⇒ 回传/落库仍是旧口径：{card['confirmValue']!r}")
        assert store.commits == [], (
            f"掩码化不得回写会话状态（写参数真值被改 = 落库会拿到掩码值）：{store.commits!r}")

    def test_old_raw_number_on_card_is_replaced_by_the_new_number_mask(self):
        """模型把**旧号本身**（掩码填成 0 的形态）写进卡片 ⇒ 同样改写成 mask(A)。"""
        card, _ = _run(
            [{"label": "手机号", "value": OLD_RAW}],
            pending_params={"customer_phone": NEW_NUMBER},
        )
        assert card["fields"][0]["value"] == MASK_OF_NEW, (
            f"旧号被就地打码成 {card['fields'][0]['value']!r} 而不是本轮的 {MASK_OF_NEW!r}"
            f" ⇒ 卡面展示的号与落库的号仍不是同一个")

    def test_no_pending_write_keeps_self_mask(self):
        """没有待写入真号（还没走 validate_input）⇒ 至少要把完整号就地掩码，不得裸露。"""
        card, _ = _run([{"label": "手机号", "value": NEW_NUMBER}])
        assert card["fields"][0]["value"] == MASK_OF_NEW, (
            f"无 pending 时仍须掩码（宁可掩掉也不能露真号）：{card['fields']!r}")


# ══════════ C. 幂等 ══════════
class TestIdempotent:
    def test_already_masked_card_is_unchanged(self):
        """模型交上来已是掩码 ⇒ 输出逐字不变（掩码再掩码 = 同一串）。"""
        fields = [
            {"label": "手机号", "value": MASK_OF_NEW},
            {"label": "联系方式", "value": MASK_OF_NEW},
        ]
        card, _ = _run(fields, pending_params={"customer_phone": NEW_NUMBER})
        assert card["fields"] == fields, (
            f"已是掩码形态的值被改动了（幂等性破了）：{card['fields']!r}")

    def test_mask_phone_value_is_idempotent_without_truth(self):
        once, changed = mask_phone_value(f"手机 {OLD_RAW} 备用 {OLD_RAW}", ())
        twice, changed_again = mask_phone_value(once, ())
        assert (once, changed) == ("手机 138****8000 备用 138****8000", True), (
            f"完整号未就地掩码：{once!r}")
        assert (twice, changed_again) == (once, False), (
            f"掩码再掩码产生了新值（不是幂等）：{twice!r}")


# ══════════ 嵌套 / 结构判据 ══════════
class TestNestedAndBoundary:
    def test_nested_value_dict_is_masked(self):
        """`fields[].value` 是嵌套 dict（整块收货信息）⇒ 里面的号码同样掩码、其它内容保留。"""
        card, _ = _run([{"label": "收货信息",
                         "value": {"receiver": "张三", "phone": NEW_NUMBER}}])
        assert card["fields"][0]["value"] == {"receiver": "张三", "phone": MASK_OF_NEW}, (
            f"嵌套 value 里的手机号未掩码（或把收货人一起吃掉）：{card['fields']!r}")


class TestWiring:
    """接线判据：整形必须发生在**追加 `ToolMessage` 之前**，并重算 `result_str`。

    `customer_service_agent` 的 `tool_result` 事件正是从 `ToolMessage.content` 反序列化出来的
    ⇒ 晚一步改，顾客侧看到的仍是真号（掩码函数单测全绿也照样漏）。
    """

    def test_hop_runs_before_the_tool_message_is_appended(self):
        lines = (BACKEND_ROOT / "app/graph/skills/execution/react_turn.py").read_text(
            encoding="utf-8").splitlines()

        def _line(needle, after=-1):
            for index, line in enumerate(lines):
                if index > after and needle in line:
                    return index
            raise AssertionError(f"`react_turn.py` 里找不到 {needle!r}（掩码接线被拆掉了？）")

        call = _line("await mask_confirm_card_result(tool_name, result_dict, session_id)")
        reserialize = _line(
            "result_str = json.dumps(result_dict, ensure_ascii=False, default=str)", call)
        append = _line("new_messages.append(ToolMessage(content=result_str", reserialize)
        assert call < reserialize < append, (
            f"顺序不对（整形 {call} / 重算 {reserialize} / 追加 {append}）："
            f"必须在追加 ToolMessage 之前整形并重算 result_str")


class TestWritePathBoundary:
    """D. 只动展示面：点卡不从 `fields` 拼写参数 ⇒ 掩码化不改变落库值。"""

    def test_routing_layer_never_reads_card_fields(self):
        """结构判据：路由层的写参数来源是 `last_confirm_value` / `pending_validated_input`，
        源码里**没有任何** `"fields"` 字面量（防后人用卡面展示值当写参数）。"""
        src = (BACKEND_ROOT / "app/agents/customer_service_agent.py").read_text(encoding="utf-8")
        assert "pending_validated_input" in src, (
            "路由层不再读 pending_validated_input ⇒ 写参数真值来源变了，本判据与实现前提失效")
        assert "last_confirm_value" in src, (
            "路由层不再读 last_confirm_value ⇒ 点卡确认轮的判据来源变了")
        hits = [node.lineno for node in ast.walk(ast.parse(src))
                if isinstance(node, ast.Constant) and node.value == "fields"]
        assert hits == [], (
            f"路由层出现卡面字段取值 `\"fields\"`（第 {hits} 行）—— 写参数**不得**来自展示面，"
            f"否则掩码化会把真号换成掩码值落库")

    def test_write_truth_is_still_readable_after_masking(self):
        """掩码化之后，写路径的**真值**仍在（掩码只改载荷，不改会话状态）。"""
        card, store = _run(
            [{"label": "手机号", "value": OLD_MASK}],
            pending_params={"customer_phone": NEW_NUMBER},
        )
        assert card["fields"][0]["value"] == MASK_OF_NEW
        still = await_load(store)
        assert pending_write_phones(still) == [NEW_NUMBER], (
            f"掩码化把写路径的真号弄丢了：{pending_write_phones(still)!r}")


def await_load(store):
    """同步读一次替身的状态（`load` 是 async，但替身无 IO ⇒ 直接跑一次事件循环）。"""
    return asyncio.run(store.load("sess_9224"))


# ══════════ 掩码函数自身的边界（单测粒度）══════════
class TestMaskPhoneValueUnit:
    def test_label_is_not_the_masking_target(self):
        """只改 `value`，`label` 原样（卡面字段名不是展示值的一部分）。"""
        out = mask_confirm_card_fields([{"label": "手机号", "value": NEW_NUMBER}])
        assert out == [{"label": "手机号", "value": MASK_OF_NEW}], (
            f"字段结构被改动（label 不许被掩码）：{out!r}")

    def test_non_string_values_pass_through(self):
        """非字符串 value（数量/金额）原样保留，不得字符串化。"""
        out = mask_confirm_card_fields([{"label": "数量", "value": 3},
                                        {"label": "合计", "value": 504.0}])
        assert out == [{"label": "数量", "value": 3}, {"label": "合计", "value": 504.0}], (
            f"非字符串值被改动：{out!r}")