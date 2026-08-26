# case_ids: CH-002, OR-007
"""取消意图检测测试 — base_skill._is_cancel_message

生产回归：
- 商品名含"取消"（如"回归测试取消Z03"）导致创建请求被误判为取消指令；
- "帮我取消订单X"被取消分支吞掉，订单并未真正取消（未调 order_manage）。
"""
import pytest

from app.graph.skills.base_skill import _is_cancel_message


class TestIsCancelMessage:
    @pytest.mark.parametrize("msg", [
        "算了，不创建了",
        "算了不买了",
        "不要了",
        "不用了",
        "取消创建",
        "算了",
        "取消",            # 短消息裸取消（确认卡片语境）
        "取消吧",
    ])
    def test_true_cancel_phrases(self, msg):
        assert _is_cancel_message(msg) is True

    @pytest.mark.parametrize("msg", [
        # 商品名含"取消"（实体名的一部分，创建语境）
        "帮我创建一个商品，名称回归测试取消Z03，价格66",
        "创建商品回归测试取消Z03",
        # 订单域的取消是业务动作，应交由 order_manage 处理而非被吞掉
        "帮我取消订单20260826708690102",
        "取消订单ORD1234567890123",
        "给订单20260826708690102取消掉",
        # "不要了"指客户行为（订单取消原因），不是放弃当前流程
        "取消订单 ORD-20260701-0001，原因是客户不要了",
        "客户说不要了，把这单取消",
        # 长消息中的"取消"不作为指令
        "客户说如果不满意的话就取消这笔订单，我先查一下订单状态",
    ])
    def test_not_cancel_when_entity_or_domain_action(self, msg):
        assert _is_cancel_message(msg) is False

    def test_empty_message(self):
        assert _is_cancel_message("") is False
        assert _is_cancel_message(None) is False
