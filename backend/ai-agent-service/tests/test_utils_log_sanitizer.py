"""app/utils/log_sanitizer.py 单元测试（issue #2430，defense 域注入防护/日志脱敏）

覆盖：
- mask_phone：11 位手机号前3后4 / 短号 / 空串 / None / 7 位边界
- mask_text：手机号 + 邮箱正则脱敏 / 无敏感信息原样
- filter_params：SENSITIVE_KEYS → '***' / 字符串值走 mask_text / 非字符串与空值原样
"""
# case_ids: DF-010

from app.utils.log_sanitizer import LogSanitizer


class TestMaskPhone:
    def test_valid_phone_masks_middle(self):
        assert LogSanitizer.mask_phone("13812345678") == "138****5678"

    def test_short_phone_masks_entirely(self):
        assert LogSanitizer.mask_phone("12345") == "****"

    def test_none_phone_masks_entirely(self):
        assert LogSanitizer.mask_phone(None) == "****"

    def test_empty_phone_masks_entirely(self):
        assert LogSanitizer.mask_phone("") == "****"

    def test_seven_char_phone_boundary(self):
        # len == 7 仍执行前3后4脱敏
        assert LogSanitizer.mask_phone("1234567") == "123****4567"


class TestMaskText:
    def test_masks_phone(self):
        result = LogSanitizer.mask_text("联系 13912345678 谢谢")
        assert "139****5678" in result
        assert "13912345678" not in result

    def test_masks_email(self):
        result = LogSanitizer.mask_text("邮箱 test@example.com 请查收")
        assert "te***@example.com" in result

    def test_masks_phone_and_email_together(self):
        result = LogSanitizer.mask_text("13800001111 / abc@x.com")
        assert "138****1111" in result
        assert "ab***@x.com" in result

    def test_no_sensitive_unchanged(self):
        assert LogSanitizer.mask_text("普通文本 no sensitive") == "普通文本 no sensitive"


class TestFilterParams:
    def test_sensitive_keys_masked(self):
        result = LogSanitizer.filter_params({
            "password": "secret123",
            "api_key": "sk-abc",
            "Authorization": "Bearer x",
        })
        assert result["password"] == "***"
        assert result["api_key"] == "***"
        assert result["Authorization"] == "***"

    def test_sensitive_key_case_insensitive(self):
        assert LogSanitizer.filter_params({"PassWord": "secret"}) == {"PassWord": "***"}

    def test_string_value_passes_mask_text(self):
        result = LogSanitizer.filter_params({"msg": "call 13800001111"})
        assert "138****1111" in result["msg"]

    def test_non_string_value_unchanged(self):
        result = LogSanitizer.filter_params({"age": 25, "flag": True, "items": [1, 2]})
        assert result["age"] == 25
        assert result["flag"] is True
        assert result["items"] == [1, 2]

    def test_empty_and_none_unchanged(self):
        assert LogSanitizer.filter_params({}) == {}
        assert LogSanitizer.filter_params(None) is None


class TestSanitizeTree:
    """sanitize_tree：递归脱敏嵌套结构（日志脱敏用，DF-010）"""

    def test_nested_dict_phone_masked(self):
        result = LogSanitizer.sanitize_tree({
            "customer": {"name": "张三", "phone": "13812345678"},
            "address": "浙江省杭州市文一西路100号",
        })
        assert result["customer"]["phone"] == "138****5678"

    def test_sensitive_key_masked_recursively(self):
        result = LogSanitizer.sanitize_tree({"nested": {"api_key": "sk-abc"}})
        assert result["nested"]["api_key"] == "***"

    def test_list_recursion(self):
        result = LogSanitizer.sanitize_tree({
            "items": [{"phone": "13900001111"}, "call 13700002222"],
        })
        assert result["items"][0]["phone"] == "139****1111"
        assert "137****2222" in result["items"][1]

    def test_primitives_unchanged(self):
        assert LogSanitizer.sanitize_tree(None) is None
        assert LogSanitizer.sanitize_tree(25) == 25
        assert LogSanitizer.sanitize_tree(True) is True
        assert LogSanitizer.sanitize_tree("普通文本") == "普通文本"
