"""Tests for misc-part2 — coverage gap issue #577"""
import pytest
from unittest.mock import patch

class TestSettings:
    def test_settings_exists(self):
        from app.config import Settings
        s = Settings()
        assert s.APP_NAME is not None

class TestParseExtractionResult:
    def test_valid_json_list(self):
        from app.memory.extractor import _parse_extraction_result
        result = _parse_extraction_result('[{"type":"preference","content":"likes blue"}]')
        assert len(result) == 1
        assert result[0]["type"] == "preference"

    def test_json_in_text(self):
        from app.memory.extractor import _parse_extraction_result
        result = _parse_extraction_result('text [{"type":"fact","content":"x"}] after')
        assert len(result) == 1

    def test_invalid_returns_empty(self):
        from app.memory.extractor import _parse_extraction_result
        assert _parse_extraction_result("no json") == []

    def test_not_list_returns_empty(self):
        from app.memory.extractor import _parse_extraction_result
        assert _parse_extraction_result('{"type":"not_list"}') == []

class TestExtractText:
    def test_string_passthrough(self):
        from app.router.intent_classifier import _extract_text
        assert _extract_text("hello") == "hello"

    def test_none_returns_empty(self):
        from app.router.intent_classifier import _extract_text
        assert _extract_text(None) == ""

    def test_multimodal_list(self):
        from app.router.intent_classifier import _extract_text
        content = [{"type":"text","text":"hello"},{"type":"image_url","image_url":{"url":"x"}},{"type":"text","text":"world"}]
        assert _extract_text(content) == "hello world"

class TestBuildClassifierPrompt:
    def test_returns_string(self):
        from app.router.intent_classifier import _build_classifier_prompt
        result = _build_classifier_prompt(["intent1","intent2"])
        assert isinstance(result, str)
        assert "intent1" in result

class TestBuildClassifierPromptCached:
    def test_returns_string(self):
        from app.router.intent_classifier import _build_classifier_prompt_cached
        result = _build_classifier_prompt_cached(("intent_a",))
        assert isinstance(result, str)

class TestHasSpecificEntities:
    def test_no_entities(self):
        from app.suggestions.follow_up import _has_specific_entities
        assert _has_specific_entities("请问有什么可以帮您的吗？") is False

class TestParseSuggestionsFromResponse:
    def test_valid_json(self):
        from app.suggestions.follow_up import _parse_suggestions_from_response
        result = _parse_suggestions_from_response('["q1","q2","q3","q4"]')
        assert result == ["q1","q2","q3"]

    def test_invalid_returns_none(self):
        from app.suggestions.follow_up import _parse_suggestions_from_response
        assert _parse_suggestions_from_response("no array") is None

class TestLLMFactory:
    def test_class_exists(self):
        from app.llm.factory import LLMFactory
        assert LLMFactory is not None

class TestRuleExtractText:
    def test_string_passthrough(self):
        from app.router.rule_matcher import _extract_text
        assert _extract_text("hello") == "hello"

    def test_none_returns_empty(self):
        from app.router.rule_matcher import _extract_text
        assert _extract_text(None) == ""

class TestCreateApp:
    def test_returns_app(self):
        from app.main import create_app
        app = create_app()
        assert app is not None
