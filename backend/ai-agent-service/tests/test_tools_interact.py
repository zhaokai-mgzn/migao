"""InteractTool 单元测试 — 生成交互组件，无 API 调用"""
# case_ids: PP-001, PR-010
import pytest
import json
from app.tools.interact import InteractTool


@pytest.fixture
def tool():
    return InteractTool()


class TestConfirmValueDeterministic:
    """confirm 卡的 `confirmValue` 必须由**实质内容**决定（issue #3401 根因）。

    实证（run 34756290189 工具健康度）：`order_create!confirmation_required × 4` ——
    确认门禁要求"用户消息**精确等于**最近一次确认卡的 confirmValue"，而该值由**模型**书写
    （工具描述还要求它"包含上下文"）→ 模型每次重发确认卡换一种措辞，值就变了 →
    顾客点的是上一张卡的值 → 门禁判"没确认" → 模型再发卡 → **确认死循环、订单落不了库**
    （OR-019/OR-023/OR-024 三条用例的失败形态）。

    修法：值只由**字段（顾客要确认的事实）**决定 —— 同样的事实 ⇒ 同样的值（点击必中）；
    事实变了（数量 3→4、总价变）⇒ 值变（顾客必须重新确认，语义不被削弱）。
    """

    def _value(self, tool, fields, model_value, ctx):
        import asyncio
        res = asyncio.run(tool.execute(
            context=ctx, component="confirm", title="请确认订单信息",
            fields=fields, confirmValue=model_value))
        assert res.success, res.error
        return res.data["confirmValue"]

    def _fields(self, qty=3, total="528"):
        return [{"label": "商品", "value": f"遮光窗帘 米白 {qty}米"},
                {"label": "总价", "value": f"¥{total}"}]

    def test_same_facts_same_value_regardless_of_wording(self, tool, sample_tool_context):
        a = self._value(tool, self._fields(), "确认下单：遮光窗帘 米白 3米 合计528元", sample_tool_context)
        b = self._value(tool, self._fields(), "请核对后确认创建订单（遮光窗帘 3 米）", sample_tool_context)
        assert a == b, (
            f"同一张卡的两种措辞必须得到同一个 confirmValue（否则顾客点击不中）: {a!r} vs {b!r}")

    def test_changed_facts_change_value(self, tool, sample_tool_context):
        a = self._value(tool, self._fields(qty=3, total="528"), "确认下单", sample_tool_context)
        b = self._value(tool, self._fields(qty=4, total="704"), "确认下单", sample_tool_context)
        assert a != b, "数量/金额变了必须换值（顾客要重新确认新明细）"

    def test_field_order_does_not_matter(self, tool, sample_tool_context):
        """同一批事实换个**字段顺序**（模型自由发挥）也必须同值。"""
        a = self._value(tool, self._fields(), "确认", sample_tool_context)
        rev = list(reversed(self._fields()))
        b = self._value(tool, rev, "确认", sample_tool_context)
        assert a == b, f"字段顺序变了值就变 → 点击仍可能不中: {a!r} vs {b!r}"

    def test_value_still_reads_as_confirmation(self, tool, sample_tool_context):
        """值仍需以确认词开头（门禁的 `_is_explicit_confirmation` 短词判定依赖它）。"""
        v = self._value(tool, self._fields(), "确认下单", sample_tool_context)
        assert v.startswith("确认"), v


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


class TestCardPiiNotMaskedAtToolLayer:
    """工具层**不脱敏**（issue #3379 边界修正，实测回归）。

    首版把卡片脱敏做在 `interact` 工具里 → 工具返回值同时进入**模型上下文**与
    `confirmValue`（顾客回传后要精确匹配）→ 实测把流程搞坏（run 34736385849：
    卡片显示"待补充完整手机号"，模型反过来问顾客要号码；验收 2 条违规）。
    脱敏移到**出站序列化**（`chat.py` 的 SSE 层）后，顾客看到的仍是脱敏值。
    本测试锁住这个边界：工具层必须保持原值。
    """

    async def test_tool_keeps_raw_values(self, tool, sample_tool_context):
        result = await tool.execute(
            context=sample_tool_context,
            component="confirm",
            title="请确认收货信息",
            fields=[{"label": "手机号", "value": "13800138000"}],
            confirmValue="确认提交：13800138000",
        )
        payload = json.dumps(result.data, ensure_ascii=False)
        assert "13800138000" in payload, "工具层不得脱敏（会污染模型上下文与 confirmValue）"
