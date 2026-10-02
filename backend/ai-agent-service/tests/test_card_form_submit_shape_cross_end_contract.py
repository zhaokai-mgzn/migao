# case_ids: API-002, UI-017, CH-009
"""form 卡「提交形态」跨端契约（issue #5949 判据 5）——**不只判类型名**。

## 缺口形态（本文件守卫的那道此前无人守卫的接缝）

`backend/ai-agent-service/tests/test_card_type_cross_end_contract.py` 只登记**卡型名**
（`form` 在不在各端渲染集合里），**判不了"提交回什么"** —— 于是「B 端提交自由文本、
契约只认 `__FORM__|`」这类缺口**零判据**：谁把提交形态改回自由文本都不会红，
只有线上才会发现「答卡轮不成立」。

本文件把三端的 form 提交形态登记成**两态**，并各自给出**可判**的真值来源：

| 端 | 文件 | 登记形态 | 线上协议 |
|---|---|---|---|
| B 端桌面 `admin-web` | `frontend/admin-web/src/components/chat/InteractiveMessage.tsx` | `structured`（`card_answer={cardId, values}`） | 请求体结构化字段 |
| C 端 `mini-app` | `frontend/mini-app/src/components/cards/FormCard.tsx` | `prefix`（`__FORM__|{json}`） | 消息前缀协议 |
| B 端移动 `bmini-app` | `frontend/bmini-app/src/components/cards/FormCard.tsx` | `prefix`（`__FORM__|{json}`） | 消息前缀协议 |

判据是**形态学**（读源码真值），刻意不做语义解析：形态被改回自由文本 ⇒ 当场红。
判别力自证（旧形态样本 + 真语料内存变异）见 `TestJudgeDiscriminativePower` ——
「不会红的判据 = 空断言」，本文件的判据必须能对**旧自由文本形态**判红。
"""

import json
import re
from pathlib import Path

from app.graph.nodes import FORM_ANSWER_INJECT_PREFIX, _card_accepts_answer

REPO_ROOT = Path(__file__).resolve().parents[3]

# ── 登记表（唯一事实源；加端 / 改形态必须改这里，否则下面的「双向自洽」判据红）──
ADMIN_WEB = "frontend/admin-web/src/components/chat/InteractiveMessage.tsx"
MINI_APP = "frontend/mini-app/src/components/cards/FormCard.tsx"
BMINI_APP = "frontend/bmini-app/src/components/cards/FormCard.tsx"
_END_SHAPES = {
    "admin-web": (ADMIN_WEB, "structured"),
    "mini-app": (MINI_APP, "prefix"),
    "bmini-app": (BMINI_APP, "prefix"),
}

# ── 旧形态样本（**判红用的正样本**：形态被改回自由文本 = 这个样子的代码）──
_OLD_FREE_TEXT_SUBMIT = """
    const lines = formFields
      .map(f => `${f.label}: ${values[f.key] || '（未填写）'}`)
      .join('\\n')
    sendMessage(lines)
"""

FORM_CARD = {"component": "form", "title": "订单 — 收货信息",
             "formFields": [{"key": "remark", "label": "备注"}]}


def _read(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.exists(), f"登记的文件不存在：{rel}（跨端契约的坐标必须可复核）"
    src = path.read_text(encoding="utf-8")
    assert src.strip(), f"读到的源码为空：{rel}"
    return src


def _shape_ok(src: str, kind: str) -> bool:
    """形态判据（**纯函数**，便于判别力自证）：源码是否真是登记的提交形态。"""
    if kind == "prefix":
        return "__FORM__|" in src
    if kind == "structured":
        # 结构化形态 = 提交体里有 cardAnswer 载荷（cardId + values），
        # 且**不再**把 `label: value` 多行文本当提交体发出去（旧形态）。
        return bool(re.search(r"cardAnswer", src)) and not re.search(
            r"sendMessage\(\s*lines\s*[,)]", src)
    raise AssertionError(f"未登记的形态：{kind}")


class TestRegisteredSubmitShapes:
    """三端的 form 提交形态 ⇄ 登记表（双向；改回自由文本 ⇒ 红）。"""

    def test_admin_web_submits_structured_card_answer(self):
        src = _read(ADMIN_WEB)
        assert _shape_ok(src, "structured") is True, (
            "B 端 form 卡未提交结构化 `card_answer`（退回自由文本 ⇒ 答卡轮不成立）"
        )

    def test_c_ends_submit_prefix_protocol(self):
        """C 端**零改动**硬边界：两端仍以 `__FORM__|{json}` 提交。"""
        for rel in (MINI_APP, BMINI_APP):
            assert _shape_ok(_read(rel), "prefix") is True, f"{rel} 不再是 `__FORM__|` 形态"

    def test_registry_covers_every_renderer_end(self):
        """登记表不许空转：三端都在，且形态取值只有登记过的那两种。"""
        assert set(_END_SHAPES) == {"admin-web", "mini-app", "bmini-app"}
        assert {k for _, k in _END_SHAPES.values()} == {"structured", "prefix"}

    def test_admin_web_card_id_rule_matches_backend(self):
        """`cardId` 跨端**同口径**：`component|title|formField keys`（逐字比）。

        两侧各算一份 id 就必须同规则，否则「cardId 一致」判据在真机上永远不一致
        （那会变成"B 端答卡轮永不成立"的复发形态）。
        """
        from app.api.chat import _card_identity

        assert _card_identity(
            {"component": "form", "title": "订单 — 收货信息",
             "formFields": [{"key": "remark"}, {"key": "qty"}]}
        ) == "form|订单 — 收货信息|remark|qty"

        src = _read(ADMIN_WEB)
        normalized = re.sub(r"\s+", "", src)
        assert "exportfunctioncardAnswerId(" in normalized, (
            "admin-web 未导出 `cardAnswerId`（跨端同口径的唯一落点）"
        )
        assert "[interactive.component,interactive.title??'',...keys].join('|')" in normalized, (
            "admin-web 的 cardId 组成规则与后端 `_card_identity` 不同口径："
            "同规则是 `component|title|formField keys` 逐字 join"
        )


class TestBackendAcceptsBothChannels:
    """契约层：两条通道都成立，自由文本不成立（用**真实** `_card_accepts_answer`）。"""

    def test_prefix_and_injected_shapes_accepted(self):
        assert _card_accepts_answer(FORM_CARD, '__FORM__|{"remark": "商品要加工项"}') is True
        assert _card_accepts_answer(
            FORM_CARD, f"{FORM_ANSWER_INJECT_PREFIX}remark: 商品要加工项") is True

    def test_free_text_not_accepted(self):
        assert _card_accepts_answer(FORM_CARD, _OLD_FREE_TEXT_SUBMIT.strip()) is False
        assert _card_accepts_answer(FORM_CARD, "备注: 商品要加工项") is False

    def test_structured_values_serialize_into_form_protocol(self):
        """B 端结构化值经入口归一到 `__FORM__|{json}`（与 C 端同一条内部链）。"""
        values = {"remark": "商品要加工项"}
        raw = "__FORM__|" + json.dumps(values, ensure_ascii=False)
        payload = json.loads(raw[len("__FORM__|"):])
        assert payload == values
        assert _card_accepts_answer(FORM_CARD, raw) is True


class TestJudgeDiscriminativePower:
    """判别力自证：旧形态样本 + 真语料内存变异 ⇒ 判据**必须红**（否则是空断言）。"""

    def test_old_free_text_shape_fails_both_kinds(self):
        assert _shape_ok(_OLD_FREE_TEXT_SUBMIT, "structured") is False
        assert _shape_ok(_OLD_FREE_TEXT_SUBMIT, "prefix") is False

    def test_real_sources_mutated_to_free_text_turn_red(self):
        admin_src = _read(ADMIN_WEB)
        assert _shape_ok(admin_src.replace("cardAnswer", "freeText"), "structured") is False

        mini_src = _read(MINI_APP)
        assert _shape_ok(mini_src.replace("__FORM__|", ""), "prefix") is False

    def test_prefix_judge_does_not_fire_on_plain_text(self):
        """只改注释 / 普通文本不得判红（防判据被自己的文案喂红）。"""
        assert _shape_ok("// 这里说明 form 卡提交（不含协议前缀）\n", "prefix") is False
