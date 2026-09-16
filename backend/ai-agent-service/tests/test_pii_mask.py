# case_ids: CH-011, CH-012, OR-018
"""`app/utils/pii_mask.py` 单元测试（issue #3379）。

为什么需要**独立单测文件**（除了 graph 层的集成测试）：
1. 这是顾客可见文本的最后一道口子，正则的**边界**行为必须逐条钉死
   （订单号里藏着 11 位数字片段、验证码 6 位、掩码幂等……）；
2. QA Growth Gate 按 tech-stack 规则要求 `app/utils/*.py` 有同名测试文件。
"""
import pytest

from app.utils.pii_mask import mask_pii


class TestPhoneMasking:
    def test_standalone_phone_masked(self):
        assert mask_pii("手机号 13800138000") == "手机号 138****8000"

    def test_phone_surrounded_by_punctuation_masked(self):
        out = mask_pii("张三 · 13800138000 · 杭州市西湖区文三路1号")
        assert "138****8000" in out and "13800138000" not in out

    def test_multiple_phones_masked(self):
        out = mask_pii("本人 13800138000，备用 13900139000")
        assert out.count("****") == 2
        assert "13800138000" not in out and "13900139000" not in out

    def test_mask_is_idempotent(self):
        once = mask_pii("13800138000")
        assert mask_pii(once) == once, "已脱敏的文本再次脱敏必须不变"

    @pytest.mark.parametrize("text", [
        "订单号 20260913027050006",           # 内含 13027050006（形如手机号）
        "订单号 EVAL-ORD-000213800138000",     # 数字片段紧邻字母
        "验证码 123456",
        "数量 3 米，合计 ¥408",
        "座机 0571-88886666",
    ])
    def test_non_phone_digits_untouched(self, text):
        assert mask_pii(text) == text, f"非手机号数字串被误改: {text!r}"

    def test_phone_inside_longer_digit_run_untouched(self):
        """前后都是数字时不算独立手机号（会毁掉订单号/流水号）。"""
        assert mask_pii("流水 9138001380001234") == "流水 9138001380001234"

    def test_invalid_prefix_untouched(self):
        assert mask_pii("编号 12800128000") == "编号 12800128000"  # 1[3-9] 才认


class TestEmailMasking:
    def test_email_masked(self):
        out = mask_pii("邮箱 zhangsan@example.com")
        assert out == "邮箱 zh***@example.com"

    def test_no_pii_returns_same_text(self):
        text = "亲，帮您查到啦～ 您名下共有 8 笔订单 📦"
        assert mask_pii(text) == text

    def test_empty_and_none(self):
        assert mask_pii("") == ""
        assert mask_pii(None) is None
