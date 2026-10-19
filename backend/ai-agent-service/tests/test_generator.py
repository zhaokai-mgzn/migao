"""商品图生成内核 + 内部端点（issue #7335）单测。

覆盖：
- 提示词按商品名/品类与 kinds 生成（主图/材质/工艺/场景）；
- 非法 kind / 缺 Key 的 fail-closed；
- 配额类错误（429 / AllocationQuota）自动切下一个模型；全部用尽 ⇒ 明确错误；
- 非配额错误不静默换模型；
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


def test_non_quota_error_does_not_switch_model(monkeypatch):
    _settings(monkeypatch)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"code": "InvalidParameter", "message": "bad image"})

    with pytest.raises(gen.ImageGenerationError):
        asyncio.run(gen.generate_product_image(
            "https://oss/sample.png", "某商品", "main", client=_client(handler)))
    assert len(calls) == 1


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
