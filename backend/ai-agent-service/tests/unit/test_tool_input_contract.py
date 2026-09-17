# case_ids: OR-016, OR-017
"""工具入参契约：`parameters` 声明的 schema 必须**真的被两层消费**（issue #4080，母单 #4043 的 T-B 包）。

## 病灶（T2：声明存在、零消费）

| 事实 | 改前形态（`origin/main` @2af9e9b1） |
|---|---|
| 运行时**完全绕过** schema | `execution/react_turn.py` 的 `args = tool_call.get("args", {})` 直接取出即用 |
| `BaseTool._get_args_schema()` **字面 `return None`** | 注释自述"简化实现" ⇒ `to_langchain_tool()` 把 `None` 当 `args_schema` 传进去 |
| 工具**早已声明**契约 | 每个工具类都有 `parameters`（`type/properties/required/enum/description`）⇒ 声明在、消费为零 |

## 本文件锁的两条不变式

1. **契约真的被生成**：`_get_args_schema()` 从 `parameters` 生成 Pydantic 模型，
   `required` **只按 schema 显式声明**取（`order_create.sms_code` 的
   「customer 角色必填，admin/agent 不需要」因此**不得**进 `required`）。
2. **契约真的被校验**：缺显式 `required` / 类型不可解析 / 枚举越界 ⇒ **执行前**结构化失败
   （`error` + 可执行 `suggestion` + 结构化 `missing_params`），**不进入工具本体**，
   并接上既有 `_self_correct_retry` 自愈链（它第二行就是「没有 suggestion 就短路」）。

## R2 阴性负例（必须全绿，判据不得拦掉原本合法的输入）

- 参数齐全的合法调用**照常执行**（含 **B 端 `admin`/`agent` 不带 `sms_code`** 的形态）；
- **未知多余键**（`action` 这类跨工具幻觉参数）不得被拦；
- **只读工具**的合法调用不受影响；
- 工具**已经容忍**的宽松数值形态（`"3米"` / `"¥168.00"`，issue #3586 的既有契约）不得被拦。

## 不适用域（R1：适用域声明 + 不适用域负例）

- **嵌套 `items[].xxx`**：不做前置校验 —— `order_create` 自己对每个明细项有**更精确**的
  失败面（「商品明细第 N 项缺少 product_name」），前置拦下会把精确错误换成泛化错误（R2 假红）。
- **非 `BaseTool` 的替身/鸭子类型对象**：没有 `parameters` ⇒ 无契约可校验，一律放行
  （`tests/test_graph_skills.py` 里一批 `class T:` 替身依赖这条）。
- **`success` 为真 / 只读工具**：校验只在**调用前**发生，不改任何成功路径。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.skills.base_skill import _execute_tool_safe
from app.tools.base import BaseTool, ToolContext, ToolResult
from app.tools.order_create import OrderCreateTool


# ──────────────────────────────────────────────────────────────────────────────
# 夹具：真 `parameters`（真 order_create 的声明）+ 记录器 `execute`
#   为什么用子类而不是 MagicMock：要**真的**吃到 order_create 的 `parameters`
#   与 `_execute_tool_safe` 的真实流水线（normalize → sanitize → 校验 → 执行）。
# ──────────────────────────────────────────────────────────────────────────────


class _SpyOrderCreate(OrderCreateTool):
    """真 schema、真流水线，只把 `execute` 换成记录器（零 HTTP、零 DB、零 SMS）。"""

    def __init__(self):
        super().__init__()
        self.seen: list[dict] = []

    # 显式签名（与真 order_create 同形，**不用 `**kwargs`**）：未知多余键才会走既有净化链路
    # 被丢弃（`_accepted_param_names` 对 `**kwargs` 工具刻意不净化，见其 docstring）。
    async def execute(self, context, customer_name=None, customer_phone=None, sms_code=None,
                      customer_address=None, remark=None, items=None):
        self.seen.append({"customer_name": customer_name, "customer_phone": customer_phone,
                          "sms_code": sms_code, "customer_address": customer_address,
                          "remark": remark, "items": items})
        return ToolResult(success=True, data={"order_no": "MOCK-0001"}, message="建单成功")


class _SpyProductDetail(BaseTool):
    """只读工具的替身：吃真 `product_detail` 的 `parameters` 形态。"""

    name = "product_detail"
    description = "商品详情"
    read_only = True
    parameters = {
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "商品 ID（必填）"},
            "color": {"type": "string", "description": "颜色（可选）"},
        },
        "required": ["product_id"],
    }

    def __init__(self):
        super().__init__()
        self.seen: list[dict] = []

    async def execute(self, context, **kwargs):
        self.seen.append(kwargs)
        return ToolResult(success=True, data={"id": kwargs.get("product_id")}, message="ok")


class _EnumTool(BaseTool):
    """带 `enum` 声明的工具替身（枚举按声明执行）。"""

    name = "enum_probe"
    description = "枚举探针"
    read_only = False
    idempotent = True
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "update"], "description": "动作"},
            "note": {"type": "string", "description": "备注（可选）"},
        },
        "required": ["action"],
    }

    def __init__(self):
        super().__init__()
        self.seen: list[dict] = []

    async def execute(self, context, **kwargs):
        self.seen.append(kwargs)
        return ToolResult(success=True, data={"ok": True}, message="ok")


def _run(tool, args: dict, role: str = "customer") -> dict:
    """走**真实共享执行入口**（`_execute_tool_safe`），返回 `result_dict`。

    与生产同一条路径：`react_turn` / `finalize_turn` 都经它调工具（`ToolRegistry.execute_tool` 另接）。
    """
    ctx = ToolContext(tenant_id=1, user_id="u-test", role=role, session_id="s-test")
    _str, result_dict = asyncio.run(_execute_tool_safe(tool, dict(args), ctx, {"session_id": "s-test"}))
    return result_dict


_CUSTOMER_OK = {
    "customer_name": "张三",
    "customer_phone": "13800138000",
    "sms_code": "123456",
    "items": [{"product_name": "夏日清风窗帘", "quantity": 3, "unit_price": 168, "subtotal": 504}],
}


# ──────────────────────────────────────────────────────────────────────────────
# ① 红证：缺必填参数**改前直接进执行**，改后执行前拦下（结构化失败 + suggestion）
# ──────────────────────────────────────────────────────────────────────────────


class TestRequiredArgsAreEnforcedBeforeExecution:
    """`:red_circle:` 缺显式 `required` ⇒ 执行前结构化失败（工具本体一次都不该被调用）。"""

    def test_missing_required_arg_never_reaches_the_tool(self):
        """红证：`items` 缺失 —— 改前 `tool.seen` 有 1 条（真执行），改后必须为空。"""
        tool = _SpyOrderCreate()
        args = {"customer_name": "张三", "customer_phone": "13800138000"}  # 缺 items

        result = _run(tool, args)

        assert tool.seen == [], (
            "缺必填参数 `items` 的调用**进了工具本体**（改前形态）—— "
            "契约声明了 required，执行前却零校验"
        )
        assert result["success"] is False
        assert result["error"] == "missing_required_args"
        assert result["missing_params"] == ["items"], (
            "缺参必须以**结构化字段**给出（T3：中文错误原文子串匹配的替代品）"
        )
        assert result["suggestion"].strip(), "fail-closed 必须带可执行 suggestion（否则自愈链短路）"

    def test_all_missing_required_args_are_reported(self):
        """缺多个时逐个报出（只报一个会让模型补一次再撞一次）。"""
        tool = _SpyOrderCreate()

        result = _run(tool, {"items": []})

        assert tool.seen == []
        assert result["missing_params"] == ["customer_name", "customer_phone"]

    def test_enum_violation_is_rejected_with_allowed_values(self):
        """枚举越界 ⇒ 拦下并给出**允许取值**（模型据此即可自愈）。"""
        tool = _EnumTool()

        result = _run(tool, {"action": "delete"})

        assert tool.seen == []
        assert result["error"] == "invalid_arg_enum"
        assert "create" in result["suggestion"] and "update" in result["suggestion"]

    def test_type_mismatch_is_rejected(self):
        """类型不可解析（对象当姓名字符串）⇒ 拦下。"""
        tool = _SpyOrderCreate()
        args = {**_CUSTOMER_OK, "customer_name": {"bad": 1}}

        result = _run(tool, args)

        assert tool.seen == []
        assert result["error"] == "invalid_arg_type"

    def test_nested_item_fields_are_not_prevalidated(self):
        """**不适用域负例**：`items[].xxx` 不做前置校验 —— 工具自己的精确失败面负责它。

        前置拦下会把「商品明细第 1 项缺少 product_name」这类**更精确**的错误换成泛化错误
        （R2：判据不得劣化原本更清晰的失败面）。
        """
        tool = _SpyOrderCreate()
        args = {**_CUSTOMER_OK}
        args["items"] = [{"product_name": "x", "quantity": {"bad": 1},
                          "unit_price": 1, "subtotal": 1}]

        result = _run(tool, args)

        assert result["success"] is True, "嵌套明细项被前置拦下了（超出适用域）"
        assert len(tool.seen) == 1


# ──────────────────────────────────────────────────────────────────────────────
# ② 契约真的从 `parameters` 生成（含角色条件必填不得一刀切）
# ──────────────────────────────────────────────────────────────────────────────


class TestArgsSchemaIsGeneratedFromParameters:
    """`_get_args_schema()` 改前字面 `return None` —— 现在必须真生成。"""

    def test_get_args_schema_generates_a_pydantic_model(self):
        schema_cls = OrderCreateTool()._get_args_schema()

        assert schema_cls is not None, "`_get_args_schema()` 仍是 `return None`（T2 未落地）"
        json_schema = schema_cls.model_json_schema()
        assert set(json_schema.get("required", [])) == {"customer_name", "customer_phone", "items"}
        assert "sms_code" in json_schema["properties"]

    def test_role_conditional_field_is_not_treated_as_required(self):
        """`sms_code` 的 description 写着「customer 角色必填，admin/agent 不需要」。"""
        json_schema = OrderCreateTool()._get_args_schema().model_json_schema()

        assert "sms_code" not in json_schema.get("required", []), (
            "角色条件必填被一刀切当必填 ⇒ B 端（admin/agent）流程会被全拦死"
        )
        assert "customer角色必填" in json_schema["properties"]["sms_code"]["description"]

    def test_langchain_binding_receives_the_generated_schema(self):
        """消费点 ①：LangChain 绑定（改前 `args_schema=None` ⇒ 由 `**kwargs` 反推出空 schema）。"""
        from app.tools.langchain_adapter import LangChainToolAdapter

        lc_tool = LangChainToolAdapter.create_langchain_tool(OrderCreateTool(), lambda: None)
        properties = lc_tool.args_schema.model_json_schema()["properties"]

        assert set(properties) >= {"customer_name", "customer_phone", "items", "sms_code"}, (
            f"LangChain 侧拿到的 schema 不含工具声明的参数：{sorted(properties)}"
        )

    def test_tool_instance_accessor_and_langchain_adapter_share_one_implementation(self):
        """单一来源：`BaseTool._get_args_schema()` 与适配器产出**同一份字段集**（不写第二份逻辑）。"""
        from app.tools.langchain_adapter import LangChainToolAdapter

        tool = OrderCreateTool()
        own = set(tool._get_args_schema().model_json_schema()["properties"])
        adapter = set(LangChainToolAdapter.build_args_schema(tool).model_json_schema()["properties"])

        assert own == adapter


# ──────────────────────────────────────────────────────────────────────────────
# ③ R2 阴性负例：判据不得拦掉原本合法的输入
# ──────────────────────────────────────────────────────────────────────────────


class TestLegalCallsStillExecute:
    """R2：合法输入一律照常执行（每条都是"改前合法、改后必须仍合法"）。"""

    def test_complete_customer_call_executes(self):
        tool = _SpyOrderCreate()

        result = _run(tool, _CUSTOMER_OK)

        assert result["success"] is True, f"参数齐全的合法调用被拦下：{result}"
        assert len(tool.seen) == 1

    @pytest.mark.parametrize("role", ["admin", "agent"])
    def test_backend_role_without_sms_code_executes(self, role):
        """B 端形态：不带 `sms_code` 也必须照常执行（角色条件必填不得一刀切）。"""
        tool = _SpyOrderCreate()
        args = {k: v for k, v in _CUSTOMER_OK.items() if k != "sms_code"}

        result = _run(tool, args, role=role)

        assert result["success"] is True, f"B 端（role={role}）不带 sms_code 被拦下：{result}"
        assert len(tool.seen) == 1

    def test_unknown_extra_keys_are_not_blocked(self):
        """未知多余键 fail-open（`action` 这类跨工具幻觉参数由既有净化链路处理）。"""
        tool = _SpyOrderCreate()

        result = _run(tool, {**_CUSTOMER_OK, "action": "create", "whatever": 1})

        assert result["success"] is True, f"多传未知键被拦下（违反 fail-open）：{result}"
        assert "action" not in tool.seen[0]

    def test_readonly_tool_legal_call_is_unaffected(self):
        tool = _SpyProductDetail()

        result = _run(tool, {"product_id": "p-1"})

        assert result["success"] is True
        assert tool.seen == [{"product_id": "p-1"}]

    def test_lenient_numeric_forms_still_pass(self):
        """工具已容忍的宽松数值形态（issue #3586）不得被契约层拦掉。"""
        tool = _SpyOrderCreate()
        args = {**_CUSTOMER_OK}
        args["items"] = [{"product_name": "夏日清风窗帘", "quantity": "3米",
                          "unit_price": "¥168.00", "subtotal": "504"}]

        result = _run(tool, args)

        assert result["success"] is True, f"「3米」/「¥168.00」这类合法输入被拦下：{result}"

    def test_optional_numeric_field_left_empty_passes(self):
        """可选字段给空串 = "没填"，不得按类型错误拦下。"""
        tool = _EnumTool()

        result = _run(tool, {"action": "create", "note": ""})

        assert result["success"] is True

    def test_readonly_valid_enum_passes(self):
        tool = _EnumTool()

        result = _run(tool, {"action": "update"})

        assert result["success"] is True
        assert tool.seen == [{"action": "update"}]
# ──────────────────────────────────────────────────────────────────────────────
# T3：缺参必须走**结构化字段**，不得再靠中文错误原文子串匹配
# ──────────────────────────────────────────────────────────────────────────────


class _MissingParamTool(BaseTool):
    """返回带结构化缺参的失败结果（模拟工具侧生产者）。"""

    name = "missing_param_probe"
    description = "缺参探针"
    read_only = False
    idempotent = True
    parameters = {"type": "object", "properties": {"code": {"type": "string"}}}

    async def execute(self, context, **kwargs):
        return ToolResult(success=False, error="验证码错误或已过期", message="码不对",
                          suggestion="请重新获取验证码", missing_params=["sms_code"])


class TestMissingParamsAreStructured:
    """R5：**不得靠中文措辞语料**承载判据 —— 缺参走结构化字段。"""

    def test_tool_result_declares_missing_params(self):
        """字段必须**真的声明**（`extra="allow"` 会把没声明的关键字静默吞掉 = 假绿）。"""
        assert "missing_params" in ToolResult.model_fields, (
            "`ToolResult` 未声明 `missing_params` —— `Config.extra='allow'` 会静默吞掉它"
        )

    def test_execution_exit_carries_missing_params(self):
        """传递 ⇒ 消费链：结构化字段必须穿过执行出口（`result_dict`）。"""
        result = _run(_MissingParamTool(), {"code": "000000"})

        assert result["missing_params"] == ["sms_code"], (
            f"执行出口没有把结构化缺参带出来：{result}"
        )

    def test_chinese_error_text_table_is_gone(self):
        """R4：中文子串表**删除**（基线 4 条 → 0）—— 只许缩短，不得扩容。"""
        from app.graph.skills import base_skill

        assert not hasattr(base_skill, "WRITE_INPUT_ERROR_PARAMS"), (
            "中文错误原文 → 参数名 的子串表仍然存在（改一个字判据就静默失效）"
        )
        assert not hasattr(base_skill, "missing_input_param"), (
            "`missing_input_param()`（`key in text` 子串匹配）仍然存在"
        )

    @pytest.mark.parametrize("role,kwargs,expected_error", [
        # `items` 形参无默认值 ⇒ 走「缺少商品明细」失败面必须显式传 `None`
        ("customer", {"customer_name": "张三", "customer_phone": "13800138000",
                      "items": None}, "缺少商品明细"),
        ("customer", {"customer_name": "张三", "customer_phone": "13800138000",
                      "items": [{"product_name": "x", "quantity": 1,
                                 "unit_price": 1, "subtotal": 1}]}, "缺少短信验证码"),
    ])
    def test_order_create_failure_sites_carry_the_param(self, role, kwargs, expected_error):
        """`order_create` 的失败点**直接带上**结构化缺参（生产者侧，issue #4080 T3）。"""
        tool = OrderCreateTool()
        ctx = ToolContext(tenant_id=1, user_id="u-test", role=role, session_id="s-test")

        result = asyncio.run(tool.execute(ctx, **kwargs))

        assert result.error == expected_error
        assert result.missing_params == (["items"] if expected_error == "缺少商品明细" else ["sms_code"])

    def test_order_create_bad_code_format_carries_the_param(self):
        tool = OrderCreateTool()
        ctx = ToolContext(tenant_id=1, user_id="u-test", role="customer", session_id="s-test")

        result = asyncio.run(tool.execute(
            ctx, customer_name="张三", customer_phone="13800138000",
            items=[{"product_name": "x", "quantity": 1, "unit_price": 1, "subtotal": 1}],
            sms_code="abc"))

        assert result.error == "验证码格式无效"
        assert result.missing_params == ["sms_code"]

    def test_order_create_expired_code_carries_the_param(self):
        """验证码错误/过期同样必须结构化（此前靠「验证码错误或已过期」这条中文串反推）。"""
        tool = OrderCreateTool()
        ctx = ToolContext(tenant_id=1, user_id="u-test", role="customer", session_id="s-test")

        with patch.object(OrderCreateTool, "_verify_sms_code",
                          new=AsyncMock(return_value=False)):
            result = asyncio.run(tool.execute(
                ctx, customer_name="张三", customer_phone="13800138000",
                items=[{"product_name": "x", "quantity": 1, "unit_price": 1, "subtotal": 1}],
                sms_code="123456"))

        assert result.error == "验证码错误或已过期"
        assert result.missing_params == ["sms_code"]

    def test_backend_role_failure_has_no_missing_sms_code(self):
        """R2：B 端（admin）不需要 sms_code —— 失败面不得凭空报「缺 sms_code」。"""
        tool = OrderCreateTool()
        ctx = ToolContext(tenant_id=1, user_id="u-test", role="admin", session_id="s-test")

        result = asyncio.run(tool.execute(
            ctx, customer_name="张三", customer_phone="13800138000", items=None))

        assert result.error == "缺少商品明细"
        assert result.missing_params == ["items"]
