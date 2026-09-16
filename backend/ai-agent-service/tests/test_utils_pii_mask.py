"""app/utils/pii_mask.py 单元测试（issue #3379，C 端回复脱敏）

模块契约（见 `app/utils/pii_mask.py` docstring）：
- 只脱敏**独立**手机号（数字边界 `(?<!\\d)…(?!\\d)`），保留前 3 后 4；
- 订单号/验证码/长数字串里的 11 位片段不得误伤（实测订单号 `20260913027050006`
  含 `13027050006`，无边界正则会把它啃成 `2026 130****0006`，订单号被毁）；
- 邮箱打码本地部分、保留域名。

为什么直接单测模块而不是只靠 `execute_skill` 间接覆盖：`pii_mask` 是 C 端输出脱敏的
唯一收敛点，边界误伤会毁掉真实订单号 —— 要锁的是边界本身，而不是某条链路的结果。
"""
# case_ids: CH-011, MC-013

import re

from app.utils.pii_mask import mask_phone, mask_pii


def _phone_match(text):
    """取文本中第一个手机号 Match，供 mask_phone（re.sub 回调）直测。"""
    return re.search(r"1[3-9]\d{9}", text)


class TestMaskPhone:
    """`mask_phone` 是 `re.sub` 回调：入参 Match，输出前 3 + **** + 后 4。"""

    def test_keeps_first_three_and_last_four(self):
        assert mask_phone(_phone_match("13800138000")) == "138****8000"

    def test_middle_digits_never_survive(self):
        masked = mask_phone(_phone_match("13912345678"))
        assert masked == "139****5678"
        assert "9123" not in masked


class TestMaskPiiPhone:
    def test_masks_phone_in_acceptance_reply(self):
        """验收 C-A2 R3 的实际泄露文本（issue #3379）：回显收货信息里的完整号码必须脱敏。"""
        reply = "另外，您的收货信息我也帮您调出来了：张三 · 13800138000 · 杭州市西湖区文三路1号"
        masked = mask_pii(reply)
        assert "13800138000" not in masked
        assert "138****8000" in masked

    def test_masks_every_phone_in_text(self):
        assert mask_pii("电话13800138000，备用13900139000") == "电话138****8000，备用139****9000"

    def test_phone_at_start_and_end_of_text(self):
        assert mask_pii("13800138000是本人号码") == "138****8000是本人号码"
        assert mask_pii("本人号码13800138000") == "本人号码138****8000"

    def test_already_masked_phone_stays_masked(self):
        assert mask_pii("手机号 138****8000") == "手机号 138****8000"


class TestMaskPiiDigitBoundaries:
    """数字边界：订单号/长数字串不得被当手机号（M115 变异锁死的行为）。"""

    def test_order_number_with_11_digit_fragment_untouched(self):
        # 20260913027050006 内的 13027050006 恰好 11 位且形如手机号 —— 无边界正则必然误伤
        assert mask_pii("订单号 20260913027050006 已创建") == "订单号 20260913027050006 已创建"

    def test_13_digit_run_untouched(self):
        assert mask_pii("流水号 1380013800012") == "流水号 1380013800012"

    def test_short_number_untouched(self):
        assert mask_pii("短号 1380013800") == "短号 1380013800"

    def test_non_mobile_11_digit_run_untouched(self):
        assert mask_pii("工号 11012345678") == "工号 11012345678"
        assert mask_pii("编号 12800138000") == "编号 12800138000"

    def test_verification_code_untouched(self):
        assert mask_pii("验证码 123456 已收到") == "验证码 123456 已收到"


class TestMaskPiiEmail:
    def test_masks_local_part_and_keeps_domain(self):
        assert mask_pii("联系 zhang.san@example.com") == "联系 zh***@example.com"

    def test_one_char_local_part_yields_single_at(self):
        """本地部分只有 1 个字符时，打码前缀不得把 `@` 本身也当前缀吞进去。"""
        assert mask_pii("邮箱 a@b.co 请查收") == "邮箱 a***@b.co 请查收"

    def test_phone_and_email_masked_in_same_text(self):
        assert mask_pii("zhang.san@example.com / 13800138000") == "zh***@example.com / 138****8000"


class TestMaskPiiEmpty:
    def test_empty_string_returned_as_is(self):
        assert mask_pii("") == ""

    def test_none_returned_as_is(self):
        assert mask_pii(None) is None

    def test_plain_text_unchanged(self):
        assert mask_pii("普通文本 no sensitive") == "普通文本 no sensitive"
