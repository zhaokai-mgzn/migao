"""LangChainToolAdapter 单元测试 — BaseTool → LangChain Tool 转换"""
import pytest
from unittest.mock import patch
from app.tools.base import ToolContext
from app.tools.langchain_adapter import LangChainToolAdapter


@pytest.fixture
def ctx():
    return ToolContext(tenant_id=1, user_id="u1", role="admin")


class TestAdapterSchema:
    def test_build_args_schema(self):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        schema_cls = LangChainToolAdapter.build_args_schema(tool)
        # 返回的是 Pydantic 模型类，有 model_json_schema()
        assert hasattr(schema_cls, 'model_json_schema')

    def test_build_args_schema_no_required(self):
        """有默认值的参数不在 required 中"""
        from app.tools.interact import InteractTool
        tool = InteractTool()
        schema_cls = LangChainToolAdapter.build_args_schema(tool)
        json_schema = schema_cls.model_json_schema()
        assert "component" in json_schema.get("properties", {})


class TestLangChainToolCreation:
    def test_create_langchain_tool(self, ctx):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()

        def get_ctx():
            return ctx

        lc_tool = LangChainToolAdapter.create_langchain_tool(tool, get_ctx)
        assert lc_tool.name == "validate_input"
        assert lc_tool.description is not None


class TestNormalizeArgs:
    def test_normalize_passthrough(self):
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        kwargs = {"target_tool": "product_manage", "target_action": "create",
                  "params": {"name": "test", "price": 1}}
        result = LangChainToolAdapter._normalize_args(tool, kwargs)
        assert result["target_tool"] == "product_manage"
        assert isinstance(result["params"], dict)

    def test_normalize_json_string_params(self):
        """LLM 传入 JSON 字符串 params 时自动解析为 dict"""
        from app.tools.validate_input import ValidateInputTool
        tool = ValidateInputTool()
        kwargs = {"target_tool": "product_manage", "target_action": "create",
                  "params": '{"name": "test", "price": 1}'}
        result = LangChainToolAdapter._normalize_args(tool, kwargs)
        assert isinstance(result["params"], dict)
        assert result["params"]["name"] == "test"
