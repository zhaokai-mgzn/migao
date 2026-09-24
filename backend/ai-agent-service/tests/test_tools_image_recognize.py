# case_ids: CH-021, PR-008
"""Agent 深通道的工具面（issue #5368 包 2）—— `image_recognize`。

## 这个工具是什么

米宝（B 端）在**同页**（建品页 / 建单页，浮动面板就在表单上方）拿到用户丢进对话的图片后，
调本工具 ⇒ **复用识别内核**（不是第二份识别实现）⇒ 得到「填哪几格 + 候选 + 解读」的
同页填充计划 ⇒ 由 `chat.py` 以**瞬时** SSE 事件（`page_fill`）推给页面表单。

## 判据（issue #5368）

1. **不落库**：工具**没有任何 admin-api 调用点**，也不触碰任何写入缝（静态扫描 + 判别力红证）；
   「提交永远是人的动作」——工具只产出「填哪几格」。
2. **一个内核，两个入口**：工具用的 `recognize` 必须**就是**内核里那个函数对象
   （`is` 身份断言）——「同名两份实现」在静态上与「共用」不可区分，只有身份能钉住。
3. **可达性**：工具注册进默认注册表，且绑在 B 端两个 skill 上（否则最深的能力也调不到）。
4. **角色层不误杀**：纯本地 + 只读 ⇒ 角色层不构成门禁（admin-api「角色管理」可建任意岗位码，
   手写角色清单必然把持码员工判成「权限不足」，见 `app/tools/base.py::check_permission`）。
"""
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from app.tools.base import ToolContext
from app.tools.image_recognize import ImageRecognizeTool
from app.vision.deep_channel import SOURCE_INTERPRETED, SOURCE_RECOGNIZED
from app.vision.recognizer import recognize

TOOL_PY = (
    Path(__file__).resolve().parents[1] / "app" / "tools" / "image_recognize.py"
)

PRODUCT_VISION = """{"fields": {
  "name":       {"value": "雪尼尔遮光窗帘", "confidence": 0.95},
  "color":      {"value": "雾霾蓝", "confidence": 0.90},
  "material":   {"value": null, "reason": "图片未标注材质"},
  "craft":      {"value": "遮光", "confidence": 0.80},
  "door_width": {"value": null, "reason": "图片未标注门幅"},
  "price":      {"value": null, "reason": "图上没有价格"}
}}"""


class VisionStub:
    """把 vision 调用钉在夹具上（与包 1 同法：内核其余部分跑真代码）。"""

    def __init__(self, payload: str = "", error: Exception = None):
        self.payload = payload
        self.error = error

    def install(self):
        llm = MagicMock()

        async def _ainvoke(messages):
            if self.error is not None:
                raise self.error
            return AIMessage(content=self.payload)

        llm.ainvoke = _ainvoke
        factory = MagicMock()
        factory.create_vision_llm = MagicMock(return_value=llm)
        return patch("app.vision.recognizer.LLMFactory", factory)


def ctx(role: str = "admin", permissions=None) -> ToolContext:
    return ToolContext(
        tenant_id=7,
        user_id="u-1",
        session_id="s-1",
        role=role,
        permissions=permissions if permissions is not None else ["*"],
    )


class TestToolDeclaration:
    def test_tool_is_read_only_and_declares_no_permission_code(self):
        tool = ImageRecognizeTool()
        assert tool.name == "image_recognize"
        assert tool.read_only is True
        assert tool.required_permissions == []
        assert "READONLY" in tool.description

    def test_custom_staff_role_is_not_falsely_rejected(self):
        """纯本地 + 只读 ⇒ 角色层不设限（任意岗位码都不该被判「权限不足」）。"""
        tool = ImageRecognizeTool()
        assert tool.check_permission(ctx(role="warehouse", permissions=["product:list"])) is True
        assert tool.check_permission(ctx(role="admin")) is True

    def test_kernel_is_the_same_function_object_not_a_second_implementation(self):
        import app.tools.image_recognize as mod

        assert mod.recognize is recognize

    def test_schema_is_renderable_and_names_the_two_targets(self):
        schema = ImageRecognizeTool().get_schema()
        props = schema["function"]["parameters"]["properties"]
        assert set(props) == {"target_type", "images", "catalog", "interpretations"}
        assert props["target_type"]["enum"] == ["product", "order"]
        assert schema["function"]["parameters"]["required"] == ["target_type", "images"]


class TestExecuteProducesAPageFillPlan:
    @pytest.mark.asyncio
    async def test_success_returns_a_page_fill_plan_with_both_sources(self):
        with VisionStub(PRODUCT_VISION).install():
            result = await ImageRecognizeTool().execute(
                ctx(),
                target_type="product",
                images=["https://oss.example.com/a.jpg"],
                catalog={"color": ["藏青", "天蓝"]},
                interpretations={"material": {"value": "雪尼尔", "note": "克重偏厚"}},
            )
        assert result.success is True
        plan = result.data
        assert plan["component"] == "page_fill"
        assert plan["target_type"] == "product"
        by_key = {f["key"]: f for f in plan["fields"]}
        assert by_key["name"]["source"] == SOURCE_RECOGNIZED
        assert by_key["material"]["source"] == SOURCE_INTERPRETED
        assert by_key["color"]["value"] is None
        assert by_key["color"]["candidates"]
        assert "宁可不填" in by_key["color"]["reason"]

    @pytest.mark.asyncio
    async def test_message_tells_the_model_the_candidates_and_the_no_fill_rule(self):
        with VisionStub(PRODUCT_VISION).install():
            result = await ImageRecognizeTool().execute(
                ctx(), target_type="product", images=["https://oss.example.com/a.jpg"],
                catalog={"color": ["藏青", "天蓝"]},
            )
        assert "藏青" in result.message
        assert "宁可不填" in result.message
        assert "同页" in result.message

    @pytest.mark.asyncio
    async def test_vision_failure_is_a_failed_tool_result_not_a_fabricated_plan(self):
        with VisionStub(error=RuntimeError("vision down")).install():
            result = await ImageRecognizeTool().execute(
                ctx(), target_type="product", images=["https://oss.example.com/a.jpg"]
            )
        assert result.success is False
        assert result.data in (None, {})
        assert result.message

    @pytest.mark.asyncio
    async def test_unknown_target_is_rejected_without_calling_vision(self):
        result = await ImageRecognizeTool().execute(
            ctx(), target_type="invoice", images=["https://oss.example.com/a.jpg"]
        )
        assert result.success is False
        assert "invoice" in f"{result.error}{result.message}"

    @pytest.mark.asyncio
    async def test_json_string_arguments_from_the_model_are_normalised(self):
        """模型常把 catalog / interpretations 传成 JSON 字符串（同 `interact` 的既有处置）。"""
        with VisionStub(PRODUCT_VISION).install():
            result = await ImageRecognizeTool().execute(
                ctx(),
                target_type="product",
                images='["https://oss.example.com/a.jpg"]',
                catalog='{"color": ["藏青"]}',
                interpretations='{"material": {"value": "雪尼尔"}}',
            )
        assert result.success is True
        by_key = {f["key"]: f for f in result.data["fields"]}
        assert by_key["color"]["value"] is None
        assert by_key["material"]["value"] == "雪尼尔"


class TestNoWriteBoundary:
    """判据 4：工具**只填表**，提交永远是人的动作。"""

    WRITE_SEAMS = (
        "app.api.chat",
        "app.memory",
        "SessionMemory",
        "session_memory",
        "get_admin_api_client",
        "commit(",
        "db.add(",
        "INSERT INTO",
    )

    @classmethod
    def scan(cls, source: str):
        return [seam for seam in cls.WRITE_SEAMS if seam in source]

    def test_tool_file_touches_no_write_seam(self):
        assert self.scan(TOOL_PY.read_text(encoding="utf-8")) == []

    def test_execute_source_touches_no_write_seam(self):
        assert self.scan(inspect.getsource(ImageRecognizeTool.execute)) == []

    def test_scanner_has_discriminative_power(self, tmp_path):
        """**注入式红证**：把写缝塞进工具源码 ⇒ 上面的断言必须变红（真写文件再扫）。"""
        source = TOOL_PY.read_text(encoding="utf-8")
        mutant = tmp_path / "image_recognize_mutant.py"
        mutant.write_text(
            source + "\n\nasync def _leak():\n    client = get_admin_api_client()\n",
            encoding="utf-8",
        )
        assert self.scan(mutant.read_text(encoding="utf-8")) == ["get_admin_api_client"]
        assert self.scan("    await SessionMemory().save_message(sid, text)\n") == ["SessionMemory"]
        assert self.scan("    return plan\n") == []


class TestReachability:
    def test_tool_is_registered_in_the_default_registry(self):
        from app.tools.registry import create_default_registry

        registry = create_default_registry()
        names = registry.get_tool_names()
        assert names.count("image_recognize") == 1, (
            f"工具未注册 ⇒ 模型不可达（能力等于不存在）；现注册 {len(names)} 个：{names}")
        assert registry.get_tool("image_recognize").get_schema()["function"]["name"] == "image_recognize"

    def test_tool_is_bound_to_both_b_end_skills(self):
        from app.graph.skills.order_skill import ORDER_TOOLS
        from app.graph.skills.product_skill import PRODUCT_TOOLS

        assert "image_recognize" in PRODUCT_TOOLS
        assert "image_recognize" in ORDER_TOOLS

    def test_tool_is_not_bound_to_the_c_end_agent(self):
        """C 端零改动：不把小布拖进这条链路。"""
        from app.graph.skills.customer_skill import CUSTOMER_TOOLS

        assert "image_recognize" not in CUSTOMER_TOOLS