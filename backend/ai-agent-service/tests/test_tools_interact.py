"""InteractTool 单元测试 — 生成交互组件，无 API 调用"""
# case_ids: PP-001, PR-010
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

    async def test_choice_with_pagemeta(self, tool, sample_tool_context):
        """choice 组件接收 pageMeta 并透传（加工项列表分页展示）。

        生产回归（sess_fba38395ed094a9d）：processing_item_query 返回的 pageMeta
        提示 LLM「调用 interact(choice) 时直接透传」，但 execute 签名无该参数
        导致 TypeError → 整个 agent 流崩溃、assistant 消息不落库。
        """
        page_meta = {
            "current": 1,
            "total": 4,
            "totalCount": 32,
            "tool": "processing_item_query",
            "params": json.dumps({"keyword": "", "page": 1, "size": 10}, ensure_ascii=False),
        }
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[
                {"label": "1. 罗马杆环安装", "value": "proc_item_hook_roman"},
                {"label": "2. 高温定型", "value": "proc_item_shape_high"},
            ],
            pageMeta=page_meta,
        )
        assert result.success is True
        assert result.data["component"] == "choice"
        assert result.data["pageMeta"] == page_meta

    async def test_choice_multi_select_passthrough(self, tool, sample_tool_context):
        """choice 组件 multiSelect=True 时透传到 data（B 端加工项多选）。

        回归（issue #2894）：加工项选择需支持多次点击选择（每个选项分别发送），
        multiSelect 标记须透传，前端 ChoiceCard 据此不锁死卡片并保留翻页控件。
        """
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择加工项",
            options=[
                {"label": "打孔加工", "value": "pi_hole"},
                {"label": "韩式折边", "value": "pi_pleat"},
            ],
            pageMeta={
                "current": 1,
                "total": 3,
                "totalCount": 22,
                "tool": "processing_item_query",
                "params": json.dumps({"keyword": "", "page": 1, "size": 10}, ensure_ascii=False),
            },
            multiSelect=True,
        )
        assert result.success is True
        assert result.data["multiSelect"] is True

    async def test_choice_multi_select_default_false(self, tool, sample_tool_context):
        """未显式传 multiSelect 时默认为单选（不输出 multiSelect 字段）。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="请选择分类",
            options=[{"label": "窗帘", "value": "curtain"}],
        )
        assert result.success is True
        assert "multiSelect" not in result.data

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


class TestCardPiiMasking:
    """卡片字段里的 PII 脱敏（issue #3379 P2-2 残留）。

    为什么要做在**卡片层**而不是只做回复文本层：
    验收复跑（run 34734188947）里新增的全局断言仍抓到一次完整手机号出现在 `final_text`，
    而回复文本层已经脱敏 —— 泄露点更可能在**卡片字段值**（confirm 卡的"收货信息"、
    form 卡的预填手机号）。而卡片是顾客**直接看到**的东西，CH-011 只守了列表卡（订单卡片），
    confirm/form 卡的地址块没人守。

    规则：**顾客可见的文本**脱敏（title / fields.label|value / formFields.label|value /
    options.label / confirmValue / cancelValue）；**协议值不动**（options[].value 是回传标识，
    脱敏会让后端认不出选了什么）。
    """

    async def test_confirm_fields_masked_for_customer(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认收货信息",
            fields=[
                {"label": "收货人", "value": "张三"},
                {"label": "手机号", "value": "13800138000"},
                {"label": "地址", "value": "杭州市西湖区文三路1号"},
            ],
            confirmValue="确认提交：张三 13800138000",
        )
        data = result.data
        assert "13800138000" not in json.dumps(data, ensure_ascii=False), \
            f"卡片字段仍含完整手机号: {json.dumps(data, ensure_ascii=False)[:200]}"
        assert "138****8000" in json.dumps(data, ensure_ascii=False)

    async def test_form_prefill_masked_for_customer(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="form",
            title="请确认收货信息",
            formFields=[
                {"key": "customer_phone", "label": "手机号", "value": "13800138000"},
                {"key": "customer_address", "label": "地址", "value": "杭州市西湖区文三路1号"},
            ],
        )
        payload = json.dumps(result.data, ensure_ascii=False)
        assert "13800138000" not in payload
        assert "138****8000" in payload

    async def test_staff_card_not_masked(self, tool, admin_tool_context):
        """B 端不脱敏：客服要照着实号码联系顾客。"""
        result = await tool.execute(
            context=admin_tool_context,
            component="confirm",
            title="请确认客户信息",
            fields=[{"label": "手机号", "value": "13800138000"}],
        )
        assert "13800138000" in json.dumps(result.data, ensure_ascii=False)

    async def test_option_value_ids_untouched(self, tool, sample_tool_context):
        """`options[].value` 是回传协议值 —— 脱敏会让"选了什么"丢失。"""
        result = await tool.execute(
            context=sample_tool_context,
            component="choice",
            title="选一下",
            # ⚠️ value 里**故意放手机号形态**：否则"给协议值也脱敏"这个变异检测不出来
            # （首版 value 是 `proc_item_pi1`，脱敏对它无影响 → M117 变异存活，属假守卫）
            options=[{"label": "打孔 13800138000", "value": "opt_13800138000"}],
        )
        data = result.data
        vals = [o.get("value") for o in data.get("options", [])]
        assert "opt_13800138000" in vals, f"协议值被改动（客户端回传会认不出）: {vals}"
        labels = json.dumps([o.get("label") for o in data.get("options", [])], ensure_ascii=False)
        assert "13800138000" not in labels, "选项标签里的手机号应脱敏（顾客看得到）"

    async def test_order_number_in_card_untouched(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认订单信息",
            fields=[{"label": "订单号", "value": "20260913027050006"}],
        )
        assert "20260913027050006" in json.dumps(result.data, ensure_ascii=False), \
            "订单号不得被误当手机号脱敏"
