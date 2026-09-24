# case_ids: API-004, CH-021
"""图片管线单一事实源测试（issue #5321 包 1 · 抽识别内核）

判据（issue #5321 验收判据 1「识别内核可被页面路径独立调用」的前置）：
URL 校验 / CDN 重写 / 文本提示三段规则从**对话路径**（`app/api/chat.py` 的私有函数）
抽到 `app/vision/pipeline.py` 后：

1. **行为逐字不变** —— 对话路径改为调用本模块（`app/api/chat.py` 的 `_validate_image_url`
   / `_rewrite_image_url` / `_image_url_hint` 三个名字仍可导入；既有断言见
   `backend/ai-agent-service/tests/test_chat.py` 与 `test_api_chat_helpers.py`，一字未改）。
2. **页面路径可独立调用** —— 本模块不依赖对话会话、不 import `app.api.chat`、不 import 记忆层。
   ⇒ 建品页 / 建单页能在**没有会话**的情况下走同一条管线（这是本包真正的工程量所在）。
"""
from unittest.mock import patch

from app.vision.pipeline import (
    image_url_hint,
    normalize_image_urls,
    rewrite_image_url,
    validate_image_url,
)


class TestValidateImageUrl:
    """校验规则：只认 https:// 与 /api/files 前缀（其余一律拒）。"""

    def test_https_and_files_prefix_pass(self):
        assert validate_image_url("https://oss.example.com/a.jpg") is True
        assert validate_image_url("/api/files/upload/a.jpg") is True

    def test_http_blank_and_non_string_rejected(self):
        assert validate_image_url("http://oss.example.com/a.jpg") is False
        assert validate_image_url("") is False
        assert validate_image_url("   ") is False
        # 非字符串（前端可能传 None / 数字）不得抛异常，直接判无效
        assert validate_image_url(None) is False
        assert validate_image_url(12345) is False

    def test_leading_trailing_whitespace_is_stripped(self):
        assert validate_image_url("  https://oss.example.com/a.jpg  ") is True


class TestRewriteImageUrl:
    """CDN → OSS 域名的重写由 IMAGE_URL_REWRITE_FROM/TO 配置驱动。"""

    def test_rewrites_when_both_configured(self):
        with patch("app.vision.pipeline.settings") as s:
            s.IMAGE_URL_REWRITE_FROM = "https://cdn.a.com"
            s.IMAGE_URL_REWRITE_TO = "https://oss.a.com"
            assert rewrite_image_url("https://cdn.a.com/x.jpg") == "https://oss.a.com/x.jpg"

    def test_untouched_when_config_missing(self):
        with patch("app.vision.pipeline.settings") as s:
            s.IMAGE_URL_REWRITE_FROM = ""
            s.IMAGE_URL_REWRITE_TO = ""
            assert rewrite_image_url("https://cdn.a.com/x.jpg") == "https://cdn.a.com/x.jpg"

    def test_untouched_when_only_one_side_configured(self):
        with patch("app.vision.pipeline.settings") as s:
            s.IMAGE_URL_REWRITE_FROM = "https://cdn.a.com"
            s.IMAGE_URL_REWRITE_TO = ""
            assert rewrite_image_url("https://cdn.a.com/x.jpg") == "https://cdn.a.com/x.jpg"


class TestImageUrlHint:
    """文本提示：无效 URL 被过滤、保留的 URL 经 CDN 重写后按「；」连接。"""

    def test_filters_invalid_and_rewrites_cdn(self):
        with patch("app.vision.pipeline.settings") as s:
            s.IMAGE_URL_REWRITE_FROM = "https://cdn.a.com"
            s.IMAGE_URL_REWRITE_TO = "https://oss.a.com"
            hint = image_url_hint([
                "https://cdn.a.com/1.jpg",
                "http://bad.example.com/2.jpg",
                "/api/files/upload/3.jpg",
            ])
        assert hint == (
            "\n\n[用户上传的图片（可直接引用 URL）："
            "https://oss.a.com/1.jpg；/api/files/upload/3.jpg]"
        )

    def test_empty_and_all_invalid_produce_empty_string(self):
        assert image_url_hint([]) == ""
        assert image_url_hint(None) == ""
        assert image_url_hint(["http://bad.example.com/2.jpg"]) == ""


class TestNormalizeImageUrls:
    """页面路径唯一的入口：**一次**做完「过滤无效 + CDN 重写」。

    抽这段的动机（issue #5321）：对话路径里「校验一次、重写一次」写在两处
    （`_convert_history_to_agent_format` 与 `send_message`），页面路径再抄一遍必然漂移。
    """

    def test_drops_invalid_and_rewrites_kept_in_order(self):
        with patch("app.vision.pipeline.settings") as s:
            s.IMAGE_URL_REWRITE_FROM = "https://cdn.a.com"
            s.IMAGE_URL_REWRITE_TO = "https://oss.a.com"
            got = normalize_image_urls([
                "https://cdn.a.com/1.jpg",
                "ftp://bad/2.jpg",
                "",
                "/api/files/upload/3.jpg",
                "https://cdn.a.com/4.jpg",
            ])
        assert got == [
            "https://oss.a.com/1.jpg",
            "/api/files/upload/3.jpg",
            "https://oss.a.com/4.jpg",
        ]

    def test_non_list_input_yields_empty(self):
        assert normalize_image_urls(None) == []
        assert normalize_image_urls([]) == []


class TestPipelineIsNotCoupledToChatPath:
    """页面路径可独立调用：管线模块**不得**反向依赖对话路径或记忆层。

    这是「不依赖对话会话」的**静态**半边（运行时半边见
    `backend/ai-agent-service/tests/test_vision_recognize.py` 的
    `test_recognize_runs_without_a_conversation_session`）。
    """

    def test_pipeline_module_source_has_no_conversation_dependency(self):
        from pathlib import Path

        src = Path(__file__).resolve().parents[2] / "app" / "vision" / "pipeline.py"
        text = src.read_text(encoding="utf-8")
        for forbidden in ("app.api.chat", "app.memory", "session_memory", "SessionMemory"):
            assert forbidden not in text, f"图片管线反向依赖了对话路径: {forbidden}"


class TestChatPathSharesTheSameImplementation:
    """**抽内核的真正判据**：对话路径与页面路径用的是**同一个函数对象**，不是两份同源代码。

    「同源代码」是抽内核最常见的退化形态：谁都能在 `chat.py` 里再写一份等价实现，
    读起来没问题、行为今天也一样 —— 直到某天只改了一边（例如 CDN 域名重写规则加白名单）。
    `is` 身份断言把「共用」钉成机械判据（红证：在 `chat.py` 末尾补一份同名实现 ⇒ 本用例变红）。
    """

    def test_chat_helpers_are_the_very_same_function_objects(self):
        from app.api import chat
        from app.vision import pipeline

        assert chat._validate_image_url is pipeline.validate_image_url
        assert chat._rewrite_image_url is pipeline.rewrite_image_url
        assert chat._image_url_hint is pipeline.image_url_hint