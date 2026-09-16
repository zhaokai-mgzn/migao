# case_ids: OR-021, CH-025
"""确认卡 XML 生成器必须能被**真解析器**解析（issue #3445）

链路事实（`app/api/chat.py`）：卡片的**唯一通用发射点**是解析回复文本里的
`<interact>…</interact>` XML 块（工具路径最终汇聚到同一协议）。所以"代码兜底发卡"
只能靠生成这段 XML —— 而生成的形状若与 `_parse_interact_xml` 不匹配，就会**静默发不出卡**。
本测试对着真解析器钉住形状（不是对着我自己的想象）。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "ai-agent-service"))

from app.api.chat import _parse_interact_xml          # noqa: E402
from app.graph.skills.base_skill import build_confirm_interact_xml  # noqa: E402


class TestConfirmInteractXmlBuilder:
    def _fields(self):
        return [{"label": "商品", "value": "遮光窗帘"},
                {"label": "数量", "value": "3米"},
                {"label": "合计", "value": "¥528"}]

    def test_parses_into_confirm_payload(self):
        xml = build_confirm_interact_xml("请确认订单信息", self._fields(),
                                         confirm_value="确认：商品=遮光窗帘")
        payload = _parse_interact_xml(xml)
        assert payload, "生成的 XML 解析不出来 —— 代码兜底会静默发不出卡"
        assert payload.get("component") == "confirm"
        assert payload.get("title") == "请确认订单信息"
        got = [(f.get("label"), f.get("value")) for f in (payload.get("fields") or [])]
        assert got == [("商品", "遮光窗帘"), ("数量", "3米"), ("合计", "¥528")], got

    def test_confirm_value_survives_roundtrip(self):
        """`confirmValue` 必须原样保留：它要与门禁的卡值口径一致，否则点了卡也过不了门禁。"""
        cv = "确认：商品=遮光窗帘；数量=3米"
        payload = _parse_interact_xml(build_confirm_interact_xml("请确认", self._fields(),
                                                                 confirm_value=cv))
        assert payload.get("confirmValue") == cv

    def test_labels_default_and_override(self):
        p1 = _parse_interact_xml(build_confirm_interact_xml("请确认", self._fields()))
        assert p1.get("confirmLabel") == "确认下单" and p1.get("cancelLabel") == "再改改"
        p2 = _parse_interact_xml(build_confirm_interact_xml("请确认", self._fields(),
                                                            confirm_label="确认", cancel_label="改一下"))
        assert p2.get("confirmLabel") == "确认" and p2.get("cancelLabel") == "改一下"

    def test_empty_fields_returns_empty_string(self):
        """`fields` 为空必须返回 ""（**实测**：解析器对字段缺失的块返回 None ⇒ 空卡片发不出去）。

        让调用方拿到空串去显式跳过，而不是生成一段注定被解析器丢弃的 XML。
        """
        assert build_confirm_interact_xml("请确认", []) == ""
        assert build_confirm_interact_xml("请确认", [{"value": "没有 label"}]) == ""

    def test_special_chars_are_fullwidth_replaced_not_escaped(self):
        """值里带 `<`/`&` 时：**保结构**且**不出现实体码**。

        实测依据：解析器是正则提取、**不做 unescape** ⇒ 若转义成 `&lt;`，顾客会看到 `&lt;`。
        故改用全角替换（`＜`/`＞`/`＆`）：结构安全、显示可读。
        """
        payload = _parse_interact_xml(build_confirm_interact_xml(
            "请确认 <订单>", [{"label": "备注", "value": "A & B <x>"}]))
        assert payload, "含特殊字符时解析失败（结构被破坏）"
        assert payload.get("title") == "请确认 ＜订单＞"
        val = (payload.get("fields") or [{}])[0].get("value")
        assert val == "A ＆ B ＜x＞", val
        assert "&lt;" not in val and "&amp;" not in val, "出现了实体码（解析器不 unescape，顾客会看到）"
