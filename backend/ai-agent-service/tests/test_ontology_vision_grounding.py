"""
vision 候选实体 → 上下文实体槽 grounding 测试（issue #2821 切片 2 + 延续切片 C）

覆盖 AgentContextManager 公共契约：
- record_vision_candidates: vision 分析识别出的候选商品/订单/客户写入实体槽（source=vision）
- record_vision_analysis: vision 分析全文落槽 → build_context 跨 skill 注入（G10 召回保障）
- 重复写入语义、非法 entity_type 拒绝、与 _extract_entities 共存

Seam: AgentContextManager 公共方法（不触碰内部实现细节）。
"""
# case_ids: ON-002, ON-004, CH-021

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage

from app.memory.context_manager import AgentContextManager


@pytest.fixture
def mgr():
    """独立实例（不走全局单例，避免测试间污染）"""
    return AgentContextManager()


class TestRecordVisionCandidates:
    def test_writes_candidates_with_vision_source(self, mgr):
        """写入后 get_entities 返回带 source=vision 的候选"""
        mgr.record_vision_candidates(
            "sess_v1",
            "product_ids",
            [{"id": "sku-1", "name": "雪尼尔遮光窗帘"}],
        )
        entities = mgr.get_entities("sess_v1")
        assert entities["product_ids"] == [
            {"id": "sku-1", "name": "雪尼尔遮光窗帘", "source": "vision"}
        ]

    def test_build_context_injects_vision_candidates(self, mgr):
        """build_context 注入包含 vision 候选实体（跨轮召回保障）"""
        mgr.record_vision_candidates(
            "sess_v2",
            "product_ids",
            [{"id": "sku-9", "name": "米白雪尼尔"}],
        )
        context = mgr.build_context("sess_v2", "product")
        assert "sku-9" in context
        assert "米白雪尼尔" in context

    def test_duplicate_candidates_deduplicated(self, mgr):
        """重复写入同一候选去重（同 id 或同 name 均不重复）"""
        mgr.record_vision_candidates(
            "sess_v3", "order_nos", [{"id": "o-1", "name": "单号123"}]
        )
        mgr.record_vision_candidates(
            "sess_v3", "order_nos", [{"id": "o-1", "name": "单号123"}]
        )
        mgr.record_vision_candidates(
            "sess_v3", "order_nos", [{"id": "o-1", "name": "单号123改"}]
        )
        entities = mgr.get_entities("sess_v3")
        assert len(entities["order_nos"]) == 1

    def test_invalid_entity_type_rejected(self, mgr):
        """非法 entity_type（不在 ENTITY_DOMAIN）必须拒绝"""
        with pytest.raises(ValueError):
            mgr.record_vision_candidates(
                "sess_v4", "unknown_type", [{"id": "x", "name": "y"}]
            )

    def test_coexists_with_tool_extraction(self, mgr):
        """vision 候选与工具结果提取共存：同类型追加，互不覆盖"""
        # 先通过工具结果提取一个商品实体（模拟 _extract_entities 路径）
        mgr.record_tool_result(
            "sess_v5",
            "product_search",
            {"data": {"products": [{"id": "sku-a", "name": "布艺窗帘"}]}},
        )
        # 再写入 vision 候选
        mgr.record_vision_candidates(
            "sess_v5",
            "product_ids",
            [{"id": "sku-b", "name": "雪尼尔"}],
        )
        entities = mgr.get_entities("sess_v5")
        ids = [e["id"] for e in entities["product_ids"]]
        assert ids == ["sku-a", "sku-b"]
        # 工具提取的 source 保留 tool 名，不被 vision 覆盖
        assert {e["source"] for e in entities["product_ids"]} == {
            "product_search",
            "vision",
        }


class TestRecordVisionAnalysis:
    """切片 C：vision 分析全文落槽 → build_context 跨 skill 注入（G10 召回保障）"""

    def test_build_context_injects_vision_analysis(self, mgr):
        """写入后 build_context 注入包含 vision 分析文本（图片关联对象有召回保障）"""
        mgr.record_vision_analysis("sess_v6", "图片中是雪尼尔遮光窗帘，米白色")
        context = mgr.build_context("sess_v6", "product")
        assert "雪尼尔遮光窗帘" in context
        assert "米白色" in context

    def test_newer_analysis_overwrites_old(self, mgr):
        """重复写入覆盖旧文本（最新图片分析优先）"""
        mgr.record_vision_analysis("sess_v7", "第一张图：灰色布艺")
        mgr.record_vision_analysis("sess_v7", "第二张图：蓝色雪尼尔")
        context = mgr.build_context("sess_v7", "product")
        assert "蓝色雪尼尔" in context
        assert "灰色布艺" not in context

    def test_empty_text_not_recorded(self, mgr):
        """空文本不落槽（不产生空上下文噪音）"""
        mgr.record_vision_analysis("sess_v8", "")
        context = mgr.build_context("sess_v8", "product")
        assert "图片分析" not in context

    def test_long_analysis_truncated(self, mgr):
        """超长分析文本截断到 MAX_CONTEXT_LENGTH（防上下文撑爆）"""
        long_text = "分析" * 500  # 1000 字符
        mgr.record_vision_analysis("sess_v9", long_text)
        context = mgr.build_context("sess_v9", "product")
        assert len(context) <= mgr.MAX_CONTEXT_LENGTH


class TestBaseSkillVisionWiring:
    """切片 C：base_skill vision 分支分析成功后调用 record_vision_analysis（ON-004 接线验证）

    验证 execute_skill 多模态路径：vision 分析成功 → get_context_manager().record_vision_analysis
    被调用（与 set_vision_analysis 并列，异常降级不破坏主流程）。
    """

    @pytest.fixture(autouse=True)
    def _capture(self):
        """构造 mock：拦截 LLM 调用返回分析文本，捕获 context_manager 调用"""
        captured_mgr = MagicMock()

        async def _capture_and_respond(messages):
            resp = MagicMock(spec=AIMessage)
            resp.content = "图片中是雪尼尔遮光窗帘，米白色，可能是店铺商品"
            resp.tool_calls = []
            return resp

        mock_registry = MagicMock()
        mock_registry.get_langchain_tools.return_value = []
        mock_breaker = MagicMock()

        async def _passthrough_breaker(fn):
            return await fn()

        mock_breaker.call = _passthrough_breaker
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=_capture_and_respond)
        mock_llm.model_name = "qwen3.6-flash"

        patchers = [
            patch("app.graph.skills.base_skill.create_skill_registry", return_value=mock_registry),
            patch("app.graph.skills.base_skill.set_tool_context"),
            patch("app.graph.skills.base_skill.get_breaker", return_value=mock_breaker),
            patch("app.graph.skills.base_skill.get_skill_llm", return_value=mock_llm),
            # 接线目标：context_manager 的 record_vision_analysis
            patch("app.memory.context_manager.get_context_manager", return_value=captured_mgr),
        ]
        for p in patchers:
            p.start()
        self.captured_mgr = captured_mgr
        yield
        for p in patchers:
            p.stop()

    async def test_vision_analysis_writes_to_context(self):
        """vision 分析成功后 record_vision_analysis 被调用（含分析文本）"""
        from app.graph.skills.base_skill import execute_skill
        from langchain_core.messages import HumanMessage

        state = {
            "messages": [
                HumanMessage(content=[
                    {"type": "text", "text": "这个多少钱"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
                ])
            ],
            "tenant_id": 1,
            "user_id": 100,
            "session_id": "sess_wiring_1",
            "role": "customer",
            "intent_result": None,
            "route_decision": None,
            "entities": {},
            "intent_chain": [],
            "stage": "initial",
            "cached_answer": None,
            "final_answer": "",
            "skill_used": "",
            "suggestions": [],
        }
        await execute_skill(
            state=state,
            skill_name="product",
            tool_names=[],
            system_prompt="你是商品助手",
        )
        self.captured_mgr.record_vision_analysis.assert_called_once()
        args, kwargs = self.captured_mgr.record_vision_analysis.call_args
        assert args[0] == "sess_wiring_1"
        assert "雪尼尔" in args[1]


class TestVisionAnalysisQualityGuard:
    """弱分析判定与重试/缓存守卫（issue #2914 次生问题）

    线上会话 sess_c40f60ffcae94f2b 实证：
    vision 弱分析（"受图片分辨率限制…不敢编造色号"）会被 set_vision_analysis
    缓存并注入后续轮次，一次弱结果毒化整个会话。
    守卫目标：弱分析重试一次；重试后仍弱则不缓存、走兜底话术。
    """

    def test_empty_is_degraded(self):
        from app.graph.skills.base_skill import _is_degraded_vision_analysis
        assert _is_degraded_vision_analysis("") is True
        assert _is_degraded_vision_analysis(None) is True

    def test_short_text_is_degraded(self):
        from app.graph.skills.base_skill import _is_degraded_vision_analysis
        assert _is_degraded_vision_analysis("这是窗帘") is True

    def test_resolution_excuse_is_degraded(self):
        """线上实测弱分析原文：只概括不枚举，并自称看不清"""
        from app.graph.skills.base_skill import _is_degraded_vision_analysis
        text = "受图片分辨率限制，我没有十足把握，不敢编造色号糊弄您"
        assert _is_degraded_vision_analysis(text) is True

    def test_full_color_enumeration_not_degraded(self):
        from app.graph.skills.base_skill import _is_degraded_vision_analysis
        text = "1#轻轻茉莉 2#杏仁奶盖 3#栀子生椰 4#丝绒奶茶 …… 共 18 个色号，无 9#"
        assert _is_degraded_vision_analysis(text) is False

    def test_retry_needed_only_on_first_attempt(self):
        from app.graph.skills.base_skill import _is_degraded_vision_analysis, _vision_retry_needed
        assert _vision_retry_needed("受图片分辨率限制", 0) is True
        assert _vision_retry_needed("受图片分辨率限制", 1) is False
        assert _vision_retry_needed("", 0) is True
        good_short = "1#轻轻茉莉 2#杏仁奶盖 3#栀子生椰"  # >20 字符的实质分析
        assert _is_degraded_vision_analysis(good_short) is False
        assert _vision_retry_needed(good_short, 0) is False

    def test_usable_analysis_blanks_degraded(self):
        """弱分析清空 → 不入缓存、走兜底（防一次弱结果毒化会话后续轮次）"""
        from app.graph.skills.base_skill import _usable_vision_analysis
        assert _usable_vision_analysis("受图片分辨率限制") == ""
        assert _usable_vision_analysis("这是窗帘") == ""
        assert _usable_vision_analysis("1#轻轻茉莉 2#杏仁奶盖 …… 共18色") != ""
