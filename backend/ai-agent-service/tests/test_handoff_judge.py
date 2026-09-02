"""小布 AI 主动引导转人工 — 判定纯函数单元测试（app/graph/handoff_judge.py）

覆盖（设计文档 xiaobu-ai-handoff-guidance.md §3）：
- D1 显式请求词 → 直转判定 is_explicit_handoff_request
- D3 信号：S1 负面情绪 / S2 负面重复 / S3 能力外（赔偿/法律）→ offer
- 冷却：offer_count ≥ 1 或用户已拒绝 → 不再 offer
- 意图过滤：明确业务意图（下单/报价/查单等）不 offer（防打断）
- 词表边界：普通中性表达不误触发

TDD Red：本文件先写，实现未就绪时应失败。
"""
# case_ids: CH-013, CH-014, CH-015, CH-016

import pytest

from app.graph.handoff_judge import (
    is_explicit_handoff_request,
    judge_handoff,
    HandoffJudgeResult,
    DEFAULT_HANDOFF_MAX_OFFERS,
)


# ────────────────────── D1 显式请求词 ──────────────────────


class TestExplicitHandoffRequest:
    def test_hit_core_keywords(self):
        for msg in [
            "我要转人工",
            "转人工客服",
            "帮我找人工客服",
            "转接人工",
            "我要找人工",
            "找真人客服",
            "请给我转人工",
        ]:
            assert is_explicit_handoff_request(msg) is True, f"应命中: {msg}"

    def test_miss_normal_queries(self):
        for msg in [
            "帮我查一下订单",
            "这个窗帘多少钱",
            "怎么算料",
            "我想退货怎么办",
            "你们几点营业",
            "人工客服是机器人吗",  # 咨询性质，非请求转人工
            "人工客服几点上班",  # 咨询而非请求转人工
        ]:
            assert is_explicit_handoff_request(msg) is False, f"不应命中: {msg}"

    def test_empty_message(self):
        assert is_explicit_handoff_request("") is False
        assert is_explicit_handoff_request(None) is False


# ────────────────────── D3 offer 判定：基础信号 ──────────────────────


class TestJudgeHandoffBaseSignals:
    def test_s1_negative_emotion_offers(self):
        result = judge_handoff(
            "你们窗帘质量太差了，气死我了",
            intent="general",
            handoff_state=None,
        )
        assert result.action == "offer"
        assert result.signal == "S1"

    def test_single_negative_in_aftersales_no_offer(self):
        # 售后自助流程中单轮表达对商品不满 → 不弹转人工卡（该引导 aftersale_create）
        result = judge_handoff(
            "这个窗帘质量真的太差了，我要退货",
            intent="after_sales",
            handoff_state=None,
        )
        assert result.action == "none"

    def test_s3_out_of_scope_offers(self):
        result = judge_handoff(
            "我要起诉你们，赔偿我的损失",
            intent="general",
            handoff_state=None,
        )
        assert result.action == "offer"
        assert result.signal == "S3"

    def test_normal_message_none(self):
        result = judge_handoff(
            "这个窗帘质量还不错，谢谢",
            intent="general",
            handoff_state=None,
        )
        assert result.action == "none"

    def test_pure_query_none(self):
        result = judge_handoff(
            "帮我查一下最近订单到哪了",
            intent="order_query",
            handoff_state=None,
        )
        assert result.action == "none"

    def test_s2_repeated_negative_across_turns_offers(self):
        # 本条中性，但最近 3 条用户消息 ≥2 条负面（同一诉求反复表达）
        recent = [
            "你们的窗帘质量问题怎么还没人管",
            "我等了三天了",
            "这个问题说了很多次了",
        ]
        result = judge_handoff(
            "那到底什么时候能解决",
            intent="after_sales",  # 售后多轮未解决 → 该建议转人工
            recent_user_messages=recent,
            handoff_state=None,
        )
        assert result.action == "offer"
        assert result.signal == "S2"


# ────────────────────── D3 offer 判定：冷却 ──────────────────────


class TestJudgeHandoffCooldown:
    def test_offer_count_reached_returns_none(self):
        result = judge_handoff(
            "你们太坑了，再也不买了",
            intent="general",
            handoff_state={"offer_count": DEFAULT_HANDOFF_MAX_OFFERS},
        )
        assert result.action == "none"

    def test_user_refused_returns_none(self):
        result = judge_handoff(
            "你们太坑了，再也不买了",
            intent="general",
            handoff_state={"offer_count": 0, "last_user_refused": True},
        )
        assert result.action == "none"

    def test_no_state_means_first_offer_allowed(self):
        result = judge_handoff(
            "你们太坑了，再也不买了",
            intent="general",
            handoff_state=None,
        )
        assert result.action == "offer"


# ────────────────────── D3 offer 判定：意图过滤 ──────────────────────


class TestJudgeHandoffIntentFilter:
    def test_no_offer_during_order_create(self):
        result = judge_handoff(
            "算了不买了，太贵了",  # 含议价情绪但处于下单流程
            intent="order_create",
            handoff_state=None,
        )
        assert result.action == "none"

    def test_no_offer_during_quote(self):
        result = judge_handoff(
            "这个褶皱倍数算得不对",
            intent="quote",
            handoff_state=None,
        )
        assert result.action == "none"

    def test_direct_reply_intents_never_offer(self):
        for intent in ["greeting", "farewell", "capabilities"]:
            result = judge_handoff("你好", intent=intent, handoff_state=None)
            assert result.action == "none"


# ────────────────────── 结果结构 ──────────────────────


class TestHandoffJudgeResult:
    def test_result_shape(self):
        result = judge_handoff("气死了", intent="general", handoff_state=None)
        assert isinstance(result, HandoffJudgeResult)
        assert result.action in {"offer", "none"}
        assert isinstance(result.reason, str)

    def test_none_result_has_empty_signal(self):
        result = judge_handoff("你好", intent="greeting", handoff_state=None)
        assert result.action == "none"
