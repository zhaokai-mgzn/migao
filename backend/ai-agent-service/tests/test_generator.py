"""商品图生成内核 + 内部端点（issue #7335）单测。

覆盖：
- 提示词按商品名/品类与 kinds 生成（主图/材质/工艺/场景）；
- 非法 kind / 缺 Key 的 fail-closed；
- 配额类错误（429 / AllocationQuota）自动切下一个模型；全部用尽 ⇒ 明确错误；
- 非配额错误不静默换模型；
- 全链都「接不了这类请求」⇒ 报不可用而非「额度用尽」（2026-10-23 起的默认链即此形态）；
- 默认链 = 用户 2026-10-24 的裁定（qwen-image-3.0-pro，issue #7661 切到 MaaS token-plan）；
- 缺 key 不回落 PRIMARY（DeepSeek key）；端点主机 = MaaS（旧 dashscope 痕迹退场）；
- 内部端点只回 `image_url` / `model`（不落库、不返回临时凭据）。
"""
# case_ids: UI-129

import asyncio
from unittest.mock import patch

import httpx
import pytest

from app.images import generator as gen


def _settings(monkeypatch, **overrides):
    defaults = {
        "IMAGE_GEN_ENABLED": True,
        "IMAGE_GEN_API_KEY": "sk-test",
        "IMAGE_GEN_MODELS": "model-a,model-b",
        "IMAGE_GEN_BASE_URL": "https://example.test/generate",
        "IMAGE_GEN_TIMEOUT": 5,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(gen.settings, key, value)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(image_url="https://dashscope.oss/out.png"):
    return httpx.Response(200, json={
        "output": {"choices": [{"message": {"content": [{"image": image_url}]}}]},
        "request_id": "rid-1",
    })


def test_prompt_contains_product_and_scene(monkeypatch):
    _settings(monkeypatch)
    main = gen.build_prompt("回归布帘-遮光提花", "main")
    assert "回归布帘-遮光提花" in main
    assert "主图" in main
    assert "布帘" in main

    roller = gen.build_prompt("回归卷帘-防水", "main")
    assert "卷帘" in roller
    assert "厨房" in roller

    texture = gen.build_prompt("回归面料-棉麻混纺", "texture")
    assert "微距" in texture
    assert "回归面料-棉麻混纺" in texture


def test_unknown_kind_is_rejected(monkeypatch):
    _settings(monkeypatch)
    with pytest.raises(ValueError):
        gen.build_prompt("某商品", "banner")


def test_missing_key_fails_closed(monkeypatch):
    _settings(monkeypatch, IMAGE_GEN_API_KEY="", ASR_API_KEY="")
    with pytest.raises(gen.ImageGenerationUnavailable):
        asyncio.run(gen.generate_product_image(
            "https://oss/sample.png", "某商品", "main", client=_client(lambda r: _ok())))


def test_disabled_fails_closed(monkeypatch):
    _settings(monkeypatch, IMAGE_GEN_ENABLED=False)
    with pytest.raises(gen.ImageGenerationUnavailable):
        asyncio.run(gen.generate_product_image(
            "https://oss/sample.png", "某商品", "main", client=_client(lambda r: _ok())))


def test_quota_error_switches_to_next_model(monkeypatch):
    _settings(monkeypatch)
    calls = []

    def handler(request):
        calls.append(request.read().decode())
        if len(calls) == 1:
            return httpx.Response(429, json={"code": "Throttling.RateQuota", "message": "quota"})
        return _ok()

    data = asyncio.run(gen.generate_product_image(
        "https://oss/sample.png", "某商品", "main", client=_client(handler)))
    assert data["model"] == "model-b"
    assert data["image_url"] == "https://dashscope.oss/out.png"
    assert len(calls) == 2
    assert '"model-a"' in calls[0]


def test_all_models_quota_raises_quota_exceeded(monkeypatch):
    _settings(monkeypatch)

    def handler(request):
        return httpx.Response(200, json={"code": "AllocationQuota.FreeTierOnly", "message": "free tier used"})

    with pytest.raises(gen.ImageGenerationQuotaExceeded):
        asyncio.run(gen.generate_product_image(
            "https://oss/sample.png", "某商品", "main", client=_client(handler)))


def test_invalid_parameter_switches_to_next_model(monkeypatch):
    """issue #7341 红证：旧逻辑把 400 InvalidParameter 当「其它错误」，回落链整条断掉。"""
    _settings(monkeypatch)
    calls = []

    def handler(request):
        calls.append(request.read().decode())
        if len(calls) == 1:
            return httpx.Response(400, json={"code": "InvalidParameter", "message": "model does not support messages"})
        return _ok()

    data = asyncio.run(gen.generate_product_image(
        "https://oss/sample.png", "某商品", "main", client=_client(handler)))
    assert data["model"] == "model-b"
    assert len(calls) == 2


def test_content_moderation_error_does_not_switch_model(monkeypatch):
    """审核类 400 不切模型：换模型只会把同一张违规图再送一遍。"""
    _settings(monkeypatch)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"code": "DataInspectionFailed", "message": "input image may contain unsafe content"})

    with pytest.raises(gen.ImageGenerationError):
        asyncio.run(gen.generate_product_image(
            "https://oss/sample.png", "某商品", "main", client=_client(handler)))
    assert len(calls) == 1


def test_default_chain_is_the_2026_10_24_user_decision():
    """默认链 = qwen-image-3.0-pro（用户 2026-10-24 裁定，issue #7661：生图切到 MaaS token-plan）。

    🔴 这条断言钉住「平台统一 key 真能出图」的那个模型：改回图片翻译模型 `qwen-mt-image-2.0`
    （不接图生图，issue #7341/#7538）等于让商家点一次拿一次 503。它红了通常是**好消息**
    —— 有人换了模型 ⇒ 请一并更新 app/config.py 的裁定注释、.env.example、
    .github/cases/ui.yml 的 UI-129 判据 3（别只删断言）。
    """
    from app.config import Settings

    default = Settings.model_fields["IMAGE_GEN_MODELS"].default
    assert [m.strip() for m in default.split(",") if m.strip()] == ["qwen-image-3.0-pro"]


def test_image_endpoint_is_maas_not_legacy_bailian():
    """生图端点 = MaaS 原生多模态路径（issue #7661）；旧 dashscope.aliyuncs.com 不得残留。"""
    from app.config import Settings

    base = Settings.model_fields["IMAGE_GEN_BASE_URL"].default
    assert "token-plan.cn-beijing.maas.aliyuncs.com" in base
    assert "/api/v1/services/aigc/" in base
    assert "dashscope.aliyuncs.com" not in base


def test_missing_key_never_falls_back_to_primary(monkeypatch):
    """旧百炼 key 退役后：IMAGE_GEN_API_KEY / ASR_API_KEY 都空 ⇒ fail-closed，绝不拿 PRIMARY 顶。

    PRIMARY 是 DeepSeek 的 key（主推理不动），打到 MaaS/百炼只会 401 —— 而且错因会被
    「有 key」这件事掩盖（响应变成 invalid_api_key 而不是「未配置」）。
    """
    _settings(monkeypatch, IMAGE_GEN_API_KEY="", ASR_API_KEY="")
    monkeypatch.setattr(gen.settings, "PRIMARY_API_KEY", "sk-deepseek-primary")

    assert gen._api_key() == ""
    with pytest.raises(gen.ImageGenerationUnavailable):
        asyncio.run(gen.generate_product_image("https://oss/sample.png", "某商品", "main"))


def test_all_models_unsupported_is_not_reported_as_quota(monkeypatch):
    """全链都「接不了这类请求」⇒ 报不可用，不报「额度用尽」（商家看到的理由必须是真的）。

    形态来源 = issue #7341 实测（图片翻译模型对图生图载荷回 400 InvalidParameter）。
    本用例只钉**语义**、不钉具体模型名 —— 模型会轮换（issue #7661），语义不许退化。
    """
    _settings(monkeypatch, IMAGE_GEN_MODELS="model-a")

    def handler(request):
        return httpx.Response(
            400, json={"code": "InvalidParameter", "message": "model does not support messages"})

    with pytest.raises(gen.ImageGenerationUnavailable) as excinfo:
        asyncio.run(gen.generate_product_image(
            "https://oss/sample.png", "某商品", "main", client=_client(handler)))
    message = str(excinfo.value)
    assert "model-a" in message
    assert "不接" in message
    assert "额度" not in message


def test_internal_endpoint_returns_only_preview_fields(monkeypatch):
    from app.api.internal import ImageGenerateRequest, image_generate

    async def fake_generate(image_url, product_name, kind):
        return {"image_url": "https://dashscope.oss/out.png", "model": "model-a"}

    request = ImageGenerateRequest(
        tenant_id=46, image_url="https://oss/sample.png", product_name="某商品", kind="main")
    with patch("app.api.internal.generate_product_image", fake_generate):
        resp = asyncio.run(image_generate(request, authorized=True))
    assert resp["success"] is True
    assert resp["data"] == {"image_url": "https://dashscope.oss/out.png", "model": "model-a"}
