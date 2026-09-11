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


class TestS1AfterSalesWithoutActionableRequest:
    """S1 在 `after_sales` 意图下的**条件**触发（CH-013/CH-014 抖动根因）

    实测背景（CI 两次 run 同一用例结果相反）：
      run 34612040268 CH-014 ✅（拿到 interact 建议卡）
      run 34613307565 CH-014 ❌（R1/R2 无任何工具，未弹卡）
    同一输入、同一代码，差别只在 **LLM 把「你们太坑了，再也不买了」分到
    general 还是 after_sales** —— 旧规则里 S1 仅对 general 生效，于是用例成败
    变成分类器抽奖，不可复现（不符合企业级评测要求）。

    设计本意（xiaobu-ai-handoff-guidance.md §3.3 原文）防的是**打断有正事要办的
    业务流**，例子给的是"质量太差**我要退货**"——关键是「我要退货」这个可执行诉求，
    不是意图标签本身。故判据改为：**消息里有没有可执行业务诉求**。

    - `after_sales` + 纯发泄（无动作词）→ offer（难过到要转人工，正是该建议的时候）
    - `after_sales` + 可执行诉求（我要退货）→ 不 offer（继续售后流程，不打断）
    """

    def test_pure_venting_in_aftersales_offers(self):
        result = judge_handoff(
            "你们窗帘质量太差了，气死我了",
            intent="after_sales",
            handoff_state=None,
        )
        assert result.action == "offer", (
            "纯发泄无业务诉求时不弹建议卡 → 用例成败取决于意图分类抽奖（见类 docstring）"
        )
        assert result.signal == "S1"

    def test_actionable_request_still_suppressed(self):
        """回归：带明确动作（我要退货）仍不打断售后流程"""
        result = judge_handoff(
            "这个窗帘质量真的太差了，我要退货",
            intent="after_sales",
            handoff_state=None,
        )
        assert result.action == "none", "有可执行诉求时不得弹卡打断售后流程"

    def test_actionable_request_variants_suppressed(self):
        """动作词表覆盖常见售后/下单诉求（逐个断言，防词表漏项回归）"""
        for msg in [
            "质量太差了，我要换货",
            "太差了，退款给我",
            "气死了，帮我下单",
            "很差，查订单到哪了",
            "太坑了，快递怎么还没到",
        ]:
            result = judge_handoff(msg, intent="after_sales", handoff_state=None)
            assert result.action == "none", f"{msg!r} 含可执行诉求，不应弹卡（实得 {result.action}）"

    def test_general_intent_unchanged(self):
        """general 意图行为不变（负面即 offer）"""
        result = judge_handoff(
            "你们窗帘质量太差了，气死我了", intent="general", handoff_state=None)
        assert result.action == "offer" and result.signal == "S1"

    def test_non_whitelist_intent_still_blocked(self):
        """白名单外意图仍一律不 offer（防打断业务流的能力不退化）"""
        for intent in ["order_create", "order_query", "product_inquiry", "knowledge_faq"]:
            result = judge_handoff(
                "你们窗帘质量太差了，气死我了", intent=intent, handoff_state=None)
            assert result.action == "none", f"意图 {intent} 不该 offer"

    def test_cooldown_still_wins(self):
        """冷却优先级最高：纯发泄也要被冷却拦住（防骚扰不退化）"""
        result = judge_handoff(
            "你们窗帘质量太差了，气死我了",
            intent="after_sales",
            handoff_state={"offer_count": 1},
        )
        assert result.action == "none"

    def test_whitelist_blocks_s2_for_non_business_flow_intents(self):
        """白名单的真正作用面在 S2/S3：白名单外意图即使多轮负面也不 offer

        （S1 分支本身只认 general/after_sales，故只测 S1 抓不到"白名单被放宽"这类改动；
          必须从 S2 多轮路径断言，才能锁住白名单语义。）
        """
        # 注意：recent_user_messages 是"本条之前"的消息，且必须落在负面词表内
        # （"一直没解决"在词表里，"一直没人解决"不在 —— 首版写错导致该测试假失败）
        # 当前消息必须**中性**：否则 S1（单轮负面）先命中，测不到 S2 路径
        recent = ["你们太坑了", "一直没解决"]
        for intent in ["order_create", "order_query", "product_inquiry", "knowledge_faq"]:
            result = judge_handoff(
                "那你们怎么处理", intent=intent,
                recent_user_messages=recent, handoff_state=None)
            assert result.action == "none", (
                f"意图 {intent} 不在 offer 白名单，多轮负面也不该弹卡（实得 {result.action}）"
            )

    def test_whitelist_allows_s2_for_after_sales(self):
        """白名单内意图的多轮未解决仍可 offer（防改动把 S2 一起关掉）"""
        result = judge_handoff(
            "那你们怎么处理", intent="after_sales",
            recent_user_messages=["你们太坑了", "一直没解决"], handoff_state=None)
        assert result.action == "offer"
        assert result.signal == "S2"
