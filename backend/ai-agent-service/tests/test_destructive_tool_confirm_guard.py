"""破坏性写操作的确认守卫 — 回归测试

修复背景：写操作 confirm 铁律此前只在 Prompt 文本层，代码层无强制。
提示注入（RAG 文档/模型幻觉）可诱导 LLM 直接调用不可逆的 destructive 工具。

修复后：destructive=True 的工具执行前，当前轮用户消息必须是明确确认，
否则拦截并引导 LLM 先展示确认卡片。核心判断抽为 _is_explicit_confirmation。
"""
# case_ids: DF-008
from app.graph.skills.base_skill import _is_explicit_confirmation


class TestIsExplicitConfirmation:
    def test_short_confirm_word(self):
        assert _is_explicit_confirmation("确认") is True

    def test_contextual_confirm_value(self):
        # confirm 卡片回传的 confirmValue，如"确认取消订单123"
        assert _is_explicit_confirmation("确认取消订单123456") is True

    def test_confirm_yes_variant(self):
        assert _is_explicit_confirmation("好的") is True
        assert _is_explicit_confirmation("OK") is True

    def test_plain_query_is_not_confirmation(self):
        assert _is_explicit_confirmation("查一下我的订单") is False

    def test_cancel_command_is_not_confirmation(self):
        # 用户主动"帮我取消订单"是请求，不是对确认卡片的确认
        assert _is_explicit_confirmation("帮我取消所有订单") is False

    def test_empty_message_is_not_confirmation(self):
        assert _is_explicit_confirmation("") is False
        assert _is_explicit_confirmation(None) is False

    def test_long_message_with_confirm_substring_is_rejected(self):
        # 长篇消息夹带"确认"字样不应被误判为确认，避免注入/误放行
        long_msg = "这是一条很长很长的用户消息，里面提到了确认一下这个字眼，但实际上并不是用户在点击确认卡片"
        assert _is_explicit_confirmation(long_msg) is False
