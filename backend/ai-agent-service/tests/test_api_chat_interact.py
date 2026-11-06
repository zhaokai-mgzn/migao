# case_ids: MC-269
"""`app/api/chat_interact.py`（chat.py 切片单元）的镜像判据。

只经单元自身 import（不经 `chat.py`）⇒ 同时证明单元可独立装配、无反向依赖。

钉的行为：`<interact>` 块的三种组件解析（choice / confirm / form）、
**「本来没有块」与「有块但解析失败」的可区分**（后者必须留 warning，否则用户侧表现为
"该弹的卡没了"、评测侧只能归因成 agent 不干活，issue #3959）、以及引用对齐过滤。
"""

from app.api.chat_interact import (
    _extract_tag_value,
    _extract_tags,
    _filter_products_by_reference,
    _parse_interact_block_or_report,
    _parse_interact_xml,
    _strip_interact_xml,
)

CHOICE_XML = (
    "<interact><component>choice</component><title>请选择加工项</title><options>"
    "<option><label>打孔</label><value>punch</value><description>含罗马圈</description></option>"
    "<option><label>挂钩</label></option></options></interact>"
)
FORM_XML = (
    "<interact><component>form</component><formFields>"
    "<field><key>phone</key><label>手机号</label><placeholder>请输入手机号</placeholder>"
    "<required>true</required></field></formFields>"
    "<submitLabel>提交</submitLabel></interact>"
)
BROKEN_XML = (
    "<interact><component>choice</component><title>请选择</title>"
    "<options><option><value>only-value</value></option></options></interact>"
)


class TestTagExtraction:
    def test_first_tag_value_and_all_tag_values(self):
        assert _extract_tag_value(CHOICE_XML, "title") == "请选择加工项"
        assert _extract_tag_value(CHOICE_XML, "missing") is None
        assert _extract_tags(CHOICE_XML, "label") == ["打孔", "挂钩"]


class TestParseInteractXml:
    def test_choice_options_keep_value_and_description(self):
        assert _parse_interact_xml(CHOICE_XML) == {
            "component": "choice",
            "title": "请选择加工项",
            "options": [
                {"label": "打孔", "value": "punch", "description": "含罗马圈"},
                {"label": "挂钩", "value": "挂钩"},   # value 缺省 = label（协议口径）
            ],
        }

    def test_form_fields_keep_required_true_only(self):
        assert _parse_interact_xml(FORM_XML) == {
            "component": "form",
            "title": "请确认",
            "formFields": [
                {"key": "phone", "label": "手机号",
                 "placeholder": "请输入手机号", "required": True}],
            "submitLabel": "提交",
        }

    def test_incomplete_block_returns_none(self):
        assert _parse_interact_xml(BROKEN_XML) is None
        assert _parse_interact_xml("<interact><title>无组件</title></interact>") is None
        assert _parse_interact_xml("") is None

    def test_strip_removes_the_block_and_keeps_text(self):
        assert _strip_interact_xml(f"好的。{CHOICE_XML}请回复") == "好的。请回复"


class TestParseBlockOrReport:
    def test_no_block_is_not_a_parse_failure(self, caplog=None):
        assert _parse_interact_block_or_report("普通文本", "sess-1") is None

    def test_broken_block_returns_none_and_warns(self):
        records = []
        from loguru import logger
        sink = logger.add(lambda m: records.append(m.record["message"]), level=0)
        try:
            assert _parse_interact_block_or_report(f"前缀{BROKEN_XML}", "sess-9") is None
        finally:
            logger.remove(sink)
        assert len(records) == 1
        assert records[0].startswith("[interact-xml] 解析失败")
        assert "session=sess-9" in records[0]

    def test_valid_block_is_parsed(self):
        payload = _parse_interact_block_or_report(f"前缀{CHOICE_XML}", "sess-1")
        assert payload["title"] == "请选择加工项"
        assert [o["label"] for o in payload["options"]] == ["打孔", "挂钩"]


class TestFilterProductsByReference:
    PRODUCTS = [{"id": "p1", "name": "棉麻窗帘"}, {"id": "p2", "name": "遮光布"}, "junk"]

    def test_only_products_mentioned_in_text_are_kept(self):
        assert _filter_products_by_reference("第 1 件 棉麻窗帘", self.PRODUCTS) == [
            {"id": "p1", "name": "棉麻窗帘"}]

    def test_card_container_shape_is_accepted(self):
        assert _filter_products_by_reference(
            "只有 p2", {"products": self.PRODUCTS}) == [{"id": "p2", "name": "遮光布"}]

    def test_empty_text_means_no_card(self):
        assert _filter_products_by_reference("", self.PRODUCTS) == []
