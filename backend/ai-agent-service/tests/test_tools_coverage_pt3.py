"""Tests for app/tools/*.py — coverage gap issue #580"""
import pytest
from unittest.mock import MagicMock, patch

class TestToolContext:
    def test_create_basic(self):
        from app.tools.base import ToolContext
        ctx = ToolContext(tenant_id=1, user_id="u1", session_id="s1", role="customer")
        assert ctx.tenant_id == 1
        assert ctx.user_id == "u1"
        assert ctx.role == "customer"

class TestToolResult:
    def test_success(self):
        from app.tools.base import ToolResult
        r = ToolResult(success=True, data={"k": "v"}, message="ok")
        assert r.success is True
        assert r.data == {"k": "v"}
        assert r.message == "ok"

    def test_failure(self):
        from app.tools.base import ToolResult
        r = ToolResult(success=False, message="error")
        assert r.success is False
        assert r.message == "error"

class TestEnsureList:
    def test_list_passthrough(self):
        from app.tools.interact import _ensure_list
        result = _ensure_list(["a", "b"], "test")
        assert result == ["a", "b"]

    def test_none_returns_none(self):
        from app.tools.interact import _ensure_list
        assert _ensure_list(None, "test") is None

class TestJsonStringParser:
    def test_json_string_parsed(self):
        from app.tools.langchain_adapter import _json_string_parser
        result = _json_string_parser('{"a": 1}')
        assert result == {"a": 1}

    def test_non_json_passthrough(self):
        from app.tools.langchain_adapter import _json_string_parser
        result = _json_string_parser(42)
        assert result == 42

    def test_invalid_json_passthrough(self):
        from app.tools.langchain_adapter import _json_string_parser
        result = _json_string_parser("not json")
        assert result == "not json"

class TestLangChainAdapter:
    def test_adapter_exists(self):
        from app.tools.langchain_adapter import LangChainToolAdapter
        assert LangChainToolAdapter is not None

class TestCategoryManageTool:
    def test_tool_class_exists(self):
        from app.tools.category_manage import CategoryManageTool
        assert CategoryManageTool is not None

class TestAftersaleQueryTool:
    def test_tool_class_exists(self):
        from app.tools.aftersale_query import AftersaleQueryTool
        assert AftersaleQueryTool is not None

class TestAftersaleCreateTool:
    def test_tool_class_exists(self):
        from app.tools.aftersale_create import AftersaleCreateTool
        assert AftersaleCreateTool is not None

class TestSessionManageTool:
    def test_tool_class_exists(self):
        from app.tools.session_manage import SessionManageTool
        assert SessionManageTool is not None

class TestInteractTool:
    def test_tool_class_exists(self):
        from app.tools.interact import InteractTool
        assert InteractTool is not None
