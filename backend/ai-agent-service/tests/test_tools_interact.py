"""InteractTool 单元测试 — 生成交互组件，无 API 调用"""
import pytest
import json
from app.tools.interact import InteractTool


@pytest.fixture
def tool():
    return InteractTool()


class TestInteractChoice:
    async def test_choice_component(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[
                {"label": "打孔", "value": "hole"},
                {"label": "韩褶", "value": "pleat"},
            ],
        )
        assert result.success is True
        assert result.data["component"] == "choice"
        assert len(result.data["options"]) == 2

    async def test_choice_options_json_string(self, tool, sample_tool_context):
        """options 为 JSON 字符串时自动解析"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="选择色号",
            options=json.dumps([{"label": "深灰", "value": "dark_gray"}]),
        )
        assert result.success is True
        assert result.data["options"][0]["label"] == "深灰"

class TestInteractConfirm:
    async def test_confirm_component(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="确认创建商品？",
            fields=[
                {"label": "商品名称", "value": "遮光窗帘"},
                {"label": "价格", "value": "299元"},
            ],
            confirmLabel="确认创建商品",
        )
        assert result.success is True
        assert result.data["component"] == "confirm"
        assert len(result.data["fields"]) == 2


class TestInteractForm:
    async def test_form_component(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="form",
            title="创建商品",
            formFields=[
                {"key": "name", "label": "商品名称", "type": "text", "required": True},
                {"key": "price", "label": "价格", "type": "number", "required": True},
            ],
        )
        assert result.success is True
        assert result.data["component"] == "form"


class TestInteractError:
    async def test_invalid_component_type(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="invalid_type",
            title="test",
        )
        assert result.success is False

    async def test_choice_missing_options(self, tool, sample_tool_context):
        """choice 组件缺少 options 时报错"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="选择",
        )
        assert result.success is False
