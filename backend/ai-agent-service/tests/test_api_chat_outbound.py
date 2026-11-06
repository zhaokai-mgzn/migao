# case_ids: MC-269
"""`app/api/chat_outbound.py`（chat.py 切片单元）的镜像判据。

tech-stack 的 `app/api/(.+).py` 规则要求每个业务 api 模块有镜像测试 —— 本文件同时承担
**切片单元的独立性证明**：它只 `from app.api.chat_outbound import ...`，不经过 `chat.py`
（单元若反向依赖入口 ⇒ 这里先 ImportError/循环）。

钉的是切片**最容易搬坏**的四处（都是可观测面）：
① 卡型表（工具名 → 卡型）与发卡门槛（空态/缺文案/缺图不许发卡）；
② 订单卡归一（单订单 → `order`，多订单 → `orders`，无有效订单 → 不发）；
③ 脱敏只打**可见文本**：`formFields[].value` / `options[].value` / `confirmValue` 是协议值，**不动**
   （动了 = 顾客回传掩码号码下单，issue #3379 的实测事故）；
④ 卡片声称判据不得被布艺域高频词（卡其色 / 色卡）误触发。
"""

from types import SimpleNamespace

from app.api.chat_outbound import (
    _detect_card_type,
    _has_card_claim,
    _mask_card_for_customer,
    _mask_for_customer,
    _normalize_order_card_data,
    _rewrite_card_claims,
    _sanitize_outbound_text,
    _should_send_card,
)

CUSTOMER = SimpleNamespace(role="customer")
MERCHANT = SimpleNamespace(role="merchant")


class TestCardTypeAndGate:
    def test_tool_to_card_type_table(self):
        assert _detect_card_type("product_search", {}) == "product_list"
        assert _detect_card_type("product_detail", {}) == "product_detail"
        assert _detect_card_type("logistics_track", {}) == "logistics"
        assert _detect_card_type("customer_order_query", {}) == "order"
        assert _detect_card_type("curtain_calc", {}) == "quotation"
        assert _detect_card_type("batch_stock_query", {}) == "batch_stock"
        assert _detect_card_type("no_such_tool", {}) is None

    def test_failed_result_never_sends_a_card(self):
        failed = {"success": False, "data": {"products": [{"id": "p1"}]}}
        assert _should_send_card("product_search", failed) is False

    def test_empty_state_is_still_a_card_for_contract_tools(self):
        # 「无数据」是合法答案且必须看得见（production_progress / payment 的空 dict 不发）
        assert _should_send_card(
            "production_progress_query", {"success": True, "data": {}}) is False
        assert _should_send_card(
            "production_progress_query",
            {"success": True, "data": {"progress_percent": 0}}) is True
        assert _should_send_card(
            "batch_stock_query", {"success": True, "data": {"action": "batches"}}) is True

    def test_poster_without_copy_is_not_sent(self):
        no_title = {"success": True, "data": {
            "product": {"id": "p1"}, "copy": {"title": "  ", "selling_points": ["遮光"]}}}
        assert _should_send_card("marketing_poster", no_title) is False


class TestOrderCardNormalization:
    def test_single_order_becomes_order_key(self):
        assert _normalize_order_card_data(
            {"orders": [{"orderNo": "SO1"}]}) == {"order": {"orderNo": "SO1"}}

    def test_multi_order_keeps_list(self):
        two = [{"orderNo": "SO1"}, {"orderNo": "SO2"}]
        assert _normalize_order_card_data({"items": two}) == {"orders": two}

    def test_no_valid_order_means_no_card(self):
        assert _normalize_order_card_data({"orders": []}) is None
        assert _normalize_order_card_data("oops") is None


class TestOutboundMasking:
    def test_customer_text_is_masked(self):
        assert _mask_for_customer("请联系 13800138000", CUSTOMER) == "请联系 138****8000"

    def test_merchant_text_is_not_masked(self):
        # 客服要照实号码联系顾客（B 端不脱敏）
        assert _mask_for_customer("请联系 13800138000", MERCHANT) == "请联系 13800138000"

    def test_internal_route_is_stripped_for_both_sides(self):
        text = "发货需要在后台「销售订单」页（/orders）找到该订单。"
        expected = "发货需要在后台「销售订单」页找到该订单。"
        assert _sanitize_outbound_text(text, MERCHANT) == expected
        assert _sanitize_outbound_text(text, CUSTOMER) == expected

    def test_card_protocol_values_are_never_masked(self):
        card = {
            "component": "form",
            "title": "联系方式 13800138000",
            "formFields": [
                {"key": "customer_phone", "label": "手机号 13800138000", "value": "13800138000"}],
            "options": [{"label": "尾号 8000", "value": "13800138000"}],
            "confirmValue": "13800138000",
        }
        masked = _mask_card_for_customer(card, CUSTOMER)
        assert masked["formFields"][0]["value"] == "13800138000"      # 回传要精确匹配
        assert masked["options"][0]["value"] == "13800138000"         # 协议值
        assert masked["confirmValue"] == "13800138000"                # 协议值
        assert masked["formFields"][0]["label"] == "手机号 138****8000"  # 可见文本才脱敏
        assert masked["title"] == "联系方式 138****8000"

    def test_merchant_card_is_returned_untouched(self):
        card = {"component": "confirm", "fields": [{"label": "电话", "value": "13800138000"}]}
        assert _mask_card_for_customer(card, MERCHANT) == card


class TestCardClaimGuard:
    def test_claim_pointing_at_missing_widget_is_detected_and_rewritten(self):
        text = "请点击下方确认卡片完成提交。"
        assert _has_card_claim(text) is True
        assert _rewrite_card_claims(text) == "请回复『确认』完成提交。"

    def test_legal_mentions_and_text_completable_actions_do_not_match(self):
        assert _has_card_claim("请查看上方结果卡片。") is False
        assert _has_card_claim("请您选择需要的加工项。") is False

    def test_fabric_domain_words_are_not_widget_claims(self):
        # 「卡其色」「色卡」是布艺域高频词，不是"指向卡片"（用户 2026-10-19 报障形态）
        assert _has_card_claim("请选择卡其色的窗帘。") is False
        assert _has_card_claim("请选择色卡上的米白色。") is False
        assert _rewrite_card_claims("请选择卡其色的窗帘。") == "请选择卡其色的窗帘。"

    def test_rewrite_is_idempotent(self):
        once = _rewrite_card_claims("开单表单已发出，请查看。")
        assert once == "开单回复『确认』，请查看。"
        assert _rewrite_card_claims(once) == once
