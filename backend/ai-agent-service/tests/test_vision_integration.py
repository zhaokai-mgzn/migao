"""
单元测试: 多模态视觉集成 (Skill 执行层)

覆盖范围:
- has_images: 图文消息检测
- LLMFactory.create_vision_llm: 视觉模型工厂
- select_model(has_vision=True): 视觉路由
- MODEL_PRICING: 视觉模型定价

全部使用 mock，不发起真实 API 调用。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.config import settings
from app.llm import (
    LLMFactory,
    MODEL_PLUS,
    MODEL_MAX,
    MODEL_LITE,
    MODEL_PRICING,
    has_images,
    select_model,
)
from app.llm.factory import DASHSCOPE_BASE_URL


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture(autouse=True)
def _patch_api_key(monkeypatch):
    """ChatOpenAI 构造需要 api_key 非空"""
    monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", "test-api-key")


@pytest.fixture
def routing_on(monkeypatch):
    """开启模型路由"""
    monkeypatch.setattr(settings, "LLM_ENABLE_MODEL_ROUTING", True)


@pytest.fixture
def routing_off(monkeypatch):
    """关闭模型路由"""
    monkeypatch.setattr(settings, "LLM_ENABLE_MODEL_ROUTING", False)


@pytest.fixture
def vision_enabled(monkeypatch):
    """启用视觉路由"""
    monkeypatch.setattr(settings, "DASHSCOPE_VISION_ENABLED", True)
    monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")


@pytest.fixture
def vision_disabled(monkeypatch):
    """禁用视觉路由"""
    monkeypatch.setattr(settings, "DASHSCOPE_VISION_ENABLED", False)


# =============================================================================
# 0. 回归测试: base_skill 视觉路由不依赖模型名 (Issue #173)
# =============================================================================
class TestVisionRoutingNoModelNameCheck:
    """回归测试: 视觉 LLM 路由不能依赖模型名中的 'vl' 后缀

    Bug 背景 (Issue #173):
        base_skill.py 曾用 `"vl" in model` 判断是否走视觉 LLM。
        但非视觉专用模型同样支持视觉理解，
        导致图片被发给文本 LLM 处理，API 调用失败。

    测试策略:
        - 验证 select_model(has_vision=True) 在非 vl 模型时仍被正确路由
        - 验证 base_skill 使用 vision_detected + DASHSCOPE_VISION_ENABLED
          而非 "vl" in model 来决定是否创建视觉 LLM
    """

    def test_select_model_returns_non_vl_vision_model(self, routing_on, monkeypatch):
        """DASHSCOPE_VISION_ENABLED=True 时，has_vision=True 可返回非 vl 后缀的视觉模型"""
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_ENABLED", True)
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-plus")
        model = select_model(has_vision=True)
        assert model == "qwen3.6-plus"

    def test_base_skill_uses_vision_enabled_not_model_name(self, routing_on, monkeypatch):
        """base_skill 应通过 vision_detected + DASHSCOPE_VISION_ENABLED 路由，
        而非 "vl" in model — 确保非视觉专用模型也能走视觉 LLM"""
        from app.graph.skills.base_skill import get_skill_llm
        from langchain_core.messages import HumanMessage

        monkeypatch.setattr(settings, "DASHSCOPE_VISION_ENABLED", True)
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-plus")

        # 构造含图片的消息
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "这是什么？"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
            ]
        )

        # 调用 get_skill_llm，验证非 vl 后缀的视觉模型也能走视觉 LLM
        llm = get_skill_llm(
            intent="product_inquiry",
            messages=[msg],
            tool_count=0,
            text_length=100,
        )
        # 视觉 LLM 显式禁用 thinking
        extra_body = getattr(llm, "extra_body", None)
        if extra_body is None:
            model_kwargs = getattr(llm, "model_kwargs", {}) or {}
            extra_body = model_kwargs.get("extra_body", {})
        assert extra_body == {"enable_thinking": False}, (
            "Vision LLM must explicitly disable thinking"
        )
        assert llm.model_name == "qwen3.6-plus"


# =============================================================================
# 1. 多模态检测 has_images
# =============================================================================
class TestHasImages:
    """has_images 多模态检测测试"""

    def test_has_images_with_image_url(self):
        """含 image_url 的 HumanMessage 返回 True"""
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "这是什么？"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
            ]
        )
        assert has_images([msg]) is True

    def test_has_images_text_only(self):
        """纯文本消息返回 False"""
        msgs = [
            HumanMessage(content="你好"),
            AIMessage(content="您好，有什么可以帮您？"),
        ]
        assert has_images(msgs) is False

    def test_has_images_empty_messages(self):
        """空列表返回 False"""
        assert has_images([]) is False
        assert has_images(None) is False

    def test_has_images_mixed_messages(self):
        """多条消息中有一条含图片，返回 True"""
        msgs = [
            SystemMessage(content="你是客服助手"),
            HumanMessage(content="第一条问题"),
            AIMessage(content="您好"),
            HumanMessage(
                content=[
                    {"type": "text", "text": "看下这个"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}},
                ]
            ),
        ]
        assert has_images(msgs) is True

    def test_has_images_list_content_no_image(self):
        """list content 但全是 text 类型，返回 False"""
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "段落 1"},
                {"type": "text", "text": "段落 2"},
            ]
        )
        assert has_images([msg]) is False

    def test_has_images_only_checks_last_human_message(self):
        """历史消息有图片但最后一条 HumanMessage 是纯文本，返回 False

        回归场景 (Issue #204): 用户首条消息带图片，后续发纯文本消息时
        不应再走 Vision 分支，避免历史图片污染 LLM 上下文。
        """
        msgs = [
            SystemMessage(content="你是客服助手"),
            HumanMessage(
                content=[
                    {"type": "text", "text": "根据图片内容创建商品"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
                ]
            ),
            AIMessage(content="抱歉，我暂时无法生成回复。"),
            HumanMessage(content="识别图片创建商品"),  # 纯文本后续消息
        ]
        assert has_images(msgs) is False

    def test_has_images_last_human_message_has_image(self):
        """最后一条 HumanMessage 含图片，返回 True"""
        msgs = [
            HumanMessage(content="你好"),
            AIMessage(content="您好"),
            HumanMessage(
                content=[
                    {"type": "text", "text": "看看这个"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/b.jpg"}},
                ]
            ),
        ]
        assert has_images(msgs) is True


# =============================================================================
# 2. 视觉模型工厂 LLMFactory.create_vision_llm
# =============================================================================
class TestCreateVisionLLM:
    """LLMFactory.create_vision_llm 测试"""

    def test_create_vision_llm_default(self, monkeypatch):
        """默认视觉模型（DASHSCOPE_VISION_MODEL）"""
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")
        llm = LLMFactory.create_vision_llm()
        assert llm.model_name == "qwen3.6-flash"
        assert llm.temperature == 0.7
        assert llm.streaming is True
        assert llm.max_tokens == 2048
        assert float(llm.request_timeout) == 60.0
        assert llm.openai_api_base == DASHSCOPE_BASE_URL

    def test_create_vision_llm_override(self, monkeypatch):
        """model_override 显式覆盖默认模型"""
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")
        llm = LLMFactory.create_vision_llm(model_override="qwen3.6-plus")
        assert llm.model_name == "qwen3.6-plus"

    def test_create_vision_llm_no_thinking(self, monkeypatch):
        """视觉 LLM 显式禁用 thinking，防止思考内容泄漏（#204 regression）"""
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")
        llm = LLMFactory.create_vision_llm()
        extra_body = getattr(llm, "extra_body", None)
        if extra_body is None:
            model_kwargs = getattr(llm, "model_kwargs", {}) or {}
            extra_body = model_kwargs.get("extra_body", {})
        assert extra_body == {"enable_thinking": False}, (
            f"create_vision_llm must disable thinking, got extra_body={extra_body}"
        )


# =============================================================================
# 3. 视觉路由 select_model(has_vision=...)
# =============================================================================
class TestSelectModelWithVision:
    """select_model 视觉路由测试"""

    def test_select_model_with_vision(self, routing_on, vision_enabled, monkeypatch):
        """has_vision=True 且启用视觉，返回 DASHSCOPE_VISION_MODEL"""
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")
        assert select_model(has_vision=True) == "qwen3.6-flash"

        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-plus")
        assert select_model(has_vision=True) == "qwen3.6-plus"

    def test_select_model_with_vision_overrides_intent(self, routing_on, vision_enabled, monkeypatch):
        """has_vision=True 优先级高于简单意图"""
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")
        # 即便是 greeting 简单意图，含图片也走视觉模型
        assert select_model(intent="greeting", has_vision=True) == "qwen3.6-flash"

    def test_select_model_vision_disabled(self, routing_on, vision_disabled):
        """DASHSCOPE_VISION_ENABLED=False 时即使 has_vision=True 也走正常路由"""
        # 普通场景 → MODEL_PLUS
        assert select_model(has_vision=True) == MODEL_PLUS
        # 简单意图 → 轻量模型
        assert select_model(intent="greeting", has_vision=True) == MODEL_LITE
        # 复杂任务 → MODEL_MAX
        assert select_model(tool_count=5, has_vision=True) == MODEL_MAX

    def test_select_model_vision_with_routing_off(self, routing_off, vision_enabled, monkeypatch):
        """LLM_ENABLE_MODEL_ROUTING=False 时返回默认模型，无视 has_vision"""
        monkeypatch.setattr(settings, "DASHSCOPE_MODEL", "qwen3.7-max")
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")
        assert select_model(has_vision=True) == "qwen3.7-max"

    def test_select_model_vision_default_is_flash(self):
        """视觉模型默认配置与 settings 一致"""
        assert settings.DASHSCOPE_VISION_MODEL == "qwen3.7-plus"


# =============================================================================
# 4. 成本追踪 - 视觉模型定价
# =============================================================================
class TestVisionModelPricing:
    """视觉模型定价测试"""

    def test_vision_model_pricing(self):
        """轻量/平衡视觉模型定价存在且正确"""
        for m in ("qwen3.6-flash", "qwen3.6-plus"):
            assert m in MODEL_PRICING, f"missing pricing for {m}"
            assert "input" in MODEL_PRICING[m]
            assert "output" in MODEL_PRICING[m]
            assert MODEL_PRICING[m]["input"] > 0
            assert MODEL_PRICING[m]["output"] > 0

        # 轻量模型应比平衡模型便宜
        flash = MODEL_PRICING["qwen3.6-flash"]
        plus = MODEL_PRICING["qwen3.6-plus"]
        assert flash["input"] < plus["input"]
        assert flash["output"] < plus["output"]

    def test_vl_models_removed(self):
        """qwen-vl-plus / qwen-vl-max / qwen-vl-ocr 不在定价表中（账号不可用）"""
        for m in ("qwen-vl-plus", "qwen-vl-max", "qwen-vl-ocr"):
            assert m not in MODEL_PRICING, f"{m} should be removed (not available)"


# =============================================================================
# 5. Vision LLM thinking 模式控制
# =============================================================================
class TestVisionLLMNoThinking:
    """create_vision_llm 必须显式关闭 thinking，防止思考内容泄漏到用户回复"""

    def test_create_vision_llm_disables_thinking(self, monkeypatch):
        """create_vision_llm 应包含 extra_body={'enable_thinking': False}"""
        monkeypatch.setattr(settings, "DASHSCOPE_VISION_MODEL", "qwen3.6-flash")

        llm = LLMFactory.create_vision_llm()

        # ChatOpenAI 存储 extra_body 在 kwargs 中
        extra_body = getattr(llm, "extra_body", None)
        # 兼容不同 langchain 版本：可能在 model_kwargs 或直接在对象上
        if extra_body is None:
            model_kwargs = getattr(llm, "model_kwargs", {}) or {}
            extra_body = model_kwargs.get("extra_body", {})

        assert extra_body == {"enable_thinking": False}, (
            f"create_vision_llm must disable thinking, got extra_body={extra_body}"
        )

    def test_create_vision_llm_with_model_override(self, monkeypatch):
        """model_override 时也禁用 thinking"""
        llm = LLMFactory.create_vision_llm(model_override="qwen3.6-plus")

        extra_body = getattr(llm, "extra_body", None)
        if extra_body is None:
            model_kwargs = getattr(llm, "model_kwargs", {}) or {}
            extra_body = model_kwargs.get("extra_body", {})

        assert extra_body == {"enable_thinking": False}, (
            f"create_vision_llm with override must disable thinking, got extra_body={extra_body}"
        )


# =============================================================================
# 5. _sanitize_messages_for_text_path: 文本路径消息清理
# =============================================================================
class TestSanitizeMessagesForTextPath:
    """文本路径历史消息清理 — 避免 image_url 污染文本模型 (PR #204 regression)

    当 has_images() 只查最后一条 HumanMessage 时，历史消息中可能仍有 image_url。
    _sanitize_messages_for_text_path 负责清理这些内容块，防止 DashScope
    BadRequestError: "Unexpected item type in content"。
    """

    @pytest.fixture
    def sanitize(self):
        from app.graph.skills.base_skill import _sanitize_messages_for_text_path
        return _sanitize_messages_for_text_path

    # ── 纯文本 ──

    def test_text_only_passthrough(self, sanitize):
        """纯文本消息原样保留"""
        msgs = [HumanMessage(content="你好")]
        result = sanitize(msgs)
        assert len(result) == 1
        assert result[0].content == "你好"

    def test_text_only_multiple_messages(self, sanitize):
        """多条纯文本消息全部原样保留"""
        msgs = [
            HumanMessage(content="第一条"),
            AIMessage(content="回复1"),
            HumanMessage(content="第二条"),
        ]
        result = sanitize(msgs)
        assert len(result) == 3
        assert result[0].content == "第一条"
        assert result[1].content == "回复1"
        assert result[2].content == "第二条"

    # ── 混合内容 (text + image_url) ──

    def test_mixed_content_extracts_text(self, sanitize):
        """混合内容：保留 text，丢弃 image_url"""
        msgs = [
            HumanMessage(content=[
                {"type": "text", "text": "根据图片创建一个商品"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
            ]),
        ]
        result = sanitize(msgs)
        assert len(result) == 1
        assert result[0].content == "根据图片创建一个商品"
        # content 应该是纯字符串，不是 list
        assert isinstance(result[0].content, str)

    def test_mixed_content_multiple_text_blocks(self, sanitize):
        """多个 text 块用空格合并"""
        msgs = [
            HumanMessage(content=[
                {"type": "text", "text": "第一段"},
                {"type": "image_url", "image_url": {"url": "https://example.com/b.jpg"}},
                {"type": "text", "text": "第二段"},
            ]),
        ]
        result = sanitize(msgs)
        assert result[0].content == "第一段 第二段"

    # ── 纯图片 (无 text) ──

    def test_pure_image_becomes_placeholder(self, sanitize):
        """纯图片无文字 → '[图片]' 占位符"""
        msgs = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}},
            ]),
        ]
        result = sanitize(msgs)
        assert result[0].content == "[图片]"

    def test_pure_image_multiple_images(self, sanitize):
        """多条纯图片消息 → 每条都转为占位符"""
        msgs = [
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": "https://example.com/1.jpg"}},
            ]),
            AIMessage(content="收到了"),
            HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": "https://example.com/2.jpg"}},
            ]),
        ]
        result = sanitize(msgs)
        assert result[0].content == "[图片]"
        assert result[1].content == "收到了"
        assert result[2].content == "[图片]"

    # ── 最后一条含图片 → 应保留(让 Vision 分支处理) ──

    def test_last_message_with_image_preserved(self, sanitize):
        """最后一条含图片时也需清理(此时 is_multimodal=True，
        不会调用本函数；但被调用时仍安全处理)"""
        msgs = [
            HumanMessage(content=[
                {"type": "text", "text": "看看这个"},
                {"type": "image_url", "image_url": {"url": "https://example.com/last.jpg"}},
            ]),
        ]
        result = sanitize(msgs)
        # text 保留，image_url 丢弃
        assert result[0].content == "看看这个"

    # ── 边界情况 ──

    def test_empty_list(self, sanitize):
        """空消息列表 → 返回空列表"""
        assert sanitize([]) == []

    def test_aimessage_untouched(self, sanitize):
        """AIMessage 完全不受影响"""
        msgs = [AIMessage(content="这是一段很长的 AI 回复")]
        result = sanitize(msgs)
        assert len(result) == 1
        assert result[0].content == "这是一段很长的 AI 回复"
        assert isinstance(result[0], AIMessage)

    def test_system_message_untouched(self, sanitize):
        """SystemMessage 不受影响"""
        msgs = [SystemMessage(content="system prompt")]
        result = sanitize(msgs)
        assert result[0].content == "system prompt"

    def test_content_is_string_not_list(self, sanitize):
        """字符串 content 的 HumanMessage 原样保留"""
        msgs = [HumanMessage(content="纯文本消息")]
        result = sanitize(msgs)
        assert result[0].content == "纯文本消息"

    # ── 实际场景模拟 ──

    def test_real_world_scenario(self, sanitize):
        """模拟真实场景：图片→文本→文本，中间消息的 image_url 应被清理"""
        msgs = [
            # 第1轮用户：发图片
            HumanMessage(content=[
                {"type": "text", "text": "创建一个商品"},
                {"type": "image_url", "image_url": {"url": "https://oss.example.com/skb.jpg"}},
            ]),
            # 第1轮 AI：识别出商品信息
            AIMessage(content="图片显示这是《花序》色卡系列，2699号。请提供价格和库存。"),
            # 第2轮用户：纯文本
            HumanMessage(content="《花序》23.8元/米"),
            # 第2轮 AI
            AIMessage(content="已记录价格。库存数量是多少？"),
            # 第3轮用户：纯文本
            HumanMessage(content="库存 200"),
        ]
        result = sanitize(msgs)

        assert len(result) == 5
        # 第1条：image_url 应被清理
        assert isinstance(result[0].content, str)
        assert result[0].content == "创建一个商品"
        # AI 消息原样
        assert "花序" in result[1].content
        # 后续文本消息原样
        assert result[2].content == "《花序》23.8元/米"
        assert result[3].content == "已记录价格。库存数量是多少？"
        assert result[4].content == "库存 200"

        # 确认没有任何消息的 content 仍是 list
        for msg in result:
            assert not isinstance(msg.content, list), (
                f"content 不应该是 list: {msg.content[:100]}"
            )
